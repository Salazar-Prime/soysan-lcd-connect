#!/usr/bin/env python3
"""Continuously show Soysan connectivity status on the 2-inch LCD."""

import argparse
import json
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch, load_font


@dataclass(frozen=True)
class Device:
    name: str
    kind: str
    state: str
    connection: str


@dataclass(frozen=True)
class StatusSnapshot:
    ubuntu: str
    network_mode: str
    network_name: str
    interface: str
    local_ip: str
    internet_online: bool
    tailscale_state: str
    tailscale_ip: str
    updated_at: str


def run_command(arguments: List[str], timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def ubuntu_version() -> str:
    try:
        values = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
        return values.get("PRETTY_NAME") or f"Ubuntu {values.get('VERSION_ID', '')}".strip()
    except OSError:
        return "Ubuntu"


def active_devices() -> List[Device]:
    output = run_command(
        [
            "nmcli",
            "-t",
            "--escape",
            "no",
            "-f",
            "DEVICE,TYPE,STATE,CONNECTION",
            "device",
            "status",
        ]
    )
    devices = []
    for line in output.splitlines():
        fields = line.split(":", 3)
        if len(fields) != 4:
            continue
        device = Device(*fields)
        if device.state in {"connected", "connecting"}:
            devices.append(device)
    return devices


def default_interface() -> str:
    route = run_command(["ip", "-4", "route", "show", "default"])
    match = re.search(r"\bdev\s+(\S+)", route)
    return match.group(1) if match else ""


def is_hotspot(device: Device) -> bool:
    if device.kind != "wifi":
        return False

    profile_mode = run_command(
        [
            "nmcli",
            "-g",
            "802-11-wireless.mode",
            "connection",
            "show",
            device.connection,
        ]
    ).lower()
    if profile_mode in {"ap", "hotspot"}:
        return True

    wireless_info = run_command(["iw", "dev", device.name, "info"])
    return bool(re.search(r"^\s*type\s+AP\s*$", wireless_info, re.MULTILINE))


def interface_ipv4(interface: str) -> str:
    if not interface:
        return "--"
    output = run_command(
        ["ip", "-4", "-o", "addr", "show", "dev", interface, "scope", "global"]
    )
    match = re.search(r"\binet\s+(\d+(?:\.\d+){3})/", output)
    return match.group(1) if match else "--"


def infer_mode(device: Device, hotspot: bool) -> str:
    if hotspot:
        return "Hotspot"
    if device.kind == "wifi":
        return "Wi-Fi"
    if device.kind == "ethernet":
        return "Ethernet"
    if device.name.startswith(("wl", "wifi")):
        return "Wi-Fi"
    if device.name.startswith(("eth", "en")):
        return "Ethernet"
    return "Connected"


def network_status():
    devices = active_devices()
    primary_name = default_interface()

    hotspot = next((device for device in devices if is_hotspot(device)), None)
    primary = next((device for device in devices if device.name == primary_name), None)
    selected = hotspot or primary

    if selected is None:
        selected = next(
            (device for device in devices if device.kind in {"ethernet", "wifi"}),
            None,
        )

    if selected is None and primary_name:
        selected = Device(primary_name, "", "connected", primary_name)

    if selected is None:
        return "Disconnected", "No active network", "--", "--"

    selected_is_hotspot = selected == hotspot
    mode = infer_mode(selected, selected_is_hotspot)
    connection = selected.connection or selected.name
    return mode, connection, selected.name, interface_ipv4(selected.name)


def internet_online(timeout: float) -> bool:
    for address in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection(address, timeout=timeout):
                return True
        except OSError:
            continue
    return False


def tailscale_status():
    output = run_command(["tailscale", "status", "--json"], timeout=3.0)
    if not output:
        return "Unavailable", "--"

    try:
        status = json.loads(output)
    except json.JSONDecodeError:
        return "Error", "--"

    self_status = status.get("Self") or {}
    addresses = self_status.get("TailscaleIPs") or status.get("TailscaleIPs") or []
    ipv4 = next((address for address in addresses if ":" not in address), "--")
    running = status.get("BackendState") == "Running"
    online = self_status.get("Online", running)

    if running and online:
        return "Connected", ipv4
    if running:
        return "Starting", ipv4
    return status.get("BackendState") or "Offline", ipv4


def collect_status(internet_timeout: float) -> StatusSnapshot:
    mode, connection, interface, local_ip = network_status()
    tailscale_state, tailscale_ip = tailscale_status()
    return StatusSnapshot(
        ubuntu=ubuntu_version(),
        network_mode=mode,
        network_name=connection,
        interface=interface,
        local_ip=local_ip,
        internet_online=internet_online(internet_timeout),
        tailscale_state=tailscale_state,
        tailscale_ip=tailscale_ip,
        updated_at=datetime.now().strftime("%H:%M:%S"),
    )


def fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textsize(text, font=font)[0] <= max_width:
        return text
    shortened = text
    while shortened and draw.textsize(f"{shortened}...", font=font)[0] > max_width:
        shortened = shortened[:-1]
    return f"{shortened}..." if shortened else "..."


def status_color(healthy: bool):
    return (20, 145, 75) if healthy else (205, 57, 57)


def render_status(status: StatusSnapshot) -> Image.Image:
    background = (241, 244, 247)
    navy = (20, 48, 80)
    muted = (91, 104, 118)
    border = (213, 220, 227)

    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    font_header = load_font(19)
    font_label = load_font(12)
    font_value = load_font(21)
    font_body = load_font(14)
    font_small = load_font(11)

    draw.rectangle((0, 0, WIDTH, 58), fill=navy)
    ubuntu = fit_text(draw, status.ubuntu, font_header, WIDTH - 22)
    draw.text((11, 7), ubuntu, fill="white", font=font_header)
    draw.text((12, 36), "SOYSAN CONNECTION STATUS", fill=(185, 208, 231), font=font_small)

    draw.rectangle((8, 67, WIDTH - 8, 165), fill="white", outline=border)
    draw.text((18, 75), "NETWORK", fill=muted, font=font_label)
    mode_color = status_color(status.network_mode != "Disconnected")
    draw.ellipse((18, 99, 28, 109), fill=mode_color)
    draw.text((35, 91), status.network_mode, fill=(26, 36, 46), font=font_value)
    network_name = fit_text(draw, status.network_name, font_body, WIDTH - 36)
    draw.text((18, 123), network_name, fill=muted, font=font_body)
    draw.text((18, 144), f"IP  {status.local_ip}", fill=(26, 36, 46), font=font_body)

    draw.rectangle((8, 174, WIDTH - 8, 219), fill="white", outline=border)
    draw.text((18, 182), "INTERNET", fill=muted, font=font_label)
    internet_text = "ONLINE" if status.internet_online else "OFFLINE"
    draw.ellipse((145, 190, 157, 202), fill=status_color(status.internet_online))
    draw.text((164, 184), internet_text, fill=(26, 36, 46), font=font_body)

    draw.rectangle((8, 228, WIDTH - 8, 292), fill="white", outline=border)
    draw.text((18, 236), "TAILSCALE", fill=muted, font=font_label)
    tailscale_online = status.tailscale_state == "Connected"
    draw.ellipse((18, 260, 30, 272), fill=status_color(tailscale_online))
    tailscale_text = fit_text(draw, status.tailscale_state.upper(), font_body, 94)
    draw.text((37, 253), tailscale_text, fill=(26, 36, 46), font=font_body)
    draw.text((137, 253), status.tailscale_ip, fill=muted, font=font_small)

    footer = f"{status.interface or '--'}  |  updated {status.updated_at}"
    draw.text((12, 303), fit_text(draw, footer, font_small, WIDTH - 24), fill=muted, font=font_small)
    return image


def render_starting() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (20, 48, 80))
    draw = ImageDraw.Draw(image)
    draw.text((27, 115), "SOYSAN", fill="white", font=load_font(30))
    draw.text((42, 161), "Checking connections...", fill=(185, 208, 231), font=load_font(14))
    return image


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="update once and exit")
    parser.add_argument(
        "--print-status",
        action="store_true",
        help="print detected status as JSON without using the LCD",
    )
    parser.add_argument(
        "--interval",
        type=positive_float,
        default=5.0,
        help="refresh interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--internet-timeout",
        type=positive_float,
        default=1.0,
        help="timeout per Internet check in seconds (default: 1)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.print_status:
        print(json.dumps(asdict(collect_status(args.internet_timeout)), indent=2))
        return

    display = Waveshare2Inch()
    try:
        display.initialize()
        display.show(render_starting())

        while True:
            started = time.monotonic()
            status = collect_status(args.internet_timeout)
            display.show(render_status(status))
            print(
                f"{status.updated_at} network={status.network_mode} "
                f"ip={status.local_ip} internet={'online' if status.internet_online else 'offline'} "
                f"tailscale={status.tailscale_state} tailscale_ip={status.tailscale_ip}",
                flush=True,
            )

            if args.once:
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.1, args.interval - elapsed))
    finally:
        display.close()


if __name__ == "__main__":
    main()
