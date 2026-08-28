#!/usr/bin/env python3
"""Continuously show Soysan connectivity status on the 2-inch LCD."""

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch, load_font


os.environ["TZ"] = os.environ.get("SOYSAN_LCD_TIMEZONE", "America/New_York")
if hasattr(time, "tzset"):
    time.tzset()

stop_requested = False
WEBSOCKET_PORT = 8765
MOCKINGBEAT_API_PORT = 3000
EXPECTED_WEBSOCKET_CLIENTS = (
    ("mockingbeat", "MOCKING"),
    ("7empest", "7EMPEST"),
)


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
    websocket_client: str
    mockingbeat_api_online: bool
    current_time: str
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
        return "Unavailable", "--", {}

    try:
        status = json.loads(output)
    except json.JSONDecodeError:
        return "Error", "--", {}

    self_status = status.get("Self") or {}
    addresses = self_status.get("TailscaleIPs") or status.get("TailscaleIPs") or []
    ipv4 = next((address for address in addresses if ":" not in address), "--")
    running = status.get("BackendState") == "Running"
    online = self_status.get("Online", running)

    expected_peers = {}
    for peer in (status.get("Peer") or {}).values():
        hostname = (peer.get("HostName") or peer.get("DNSName") or "").strip()
        short_name = hostname.rstrip(".").split(".", 1)[0].lower()
        if short_name not in {name for name, _label in EXPECTED_WEBSOCKET_CLIENTS}:
            continue
        expected_peers[short_name] = {
            "addresses": peer.get("TailscaleIPs") or [],
            "online": bool(peer.get("Online")),
        }

    if running and online:
        return "Connected", ipv4, expected_peers
    if running:
        return "Starting", ipv4, expected_peers
    return status.get("BackendState") or "Offline", ipv4, expected_peers


def endpoint_host(endpoint: str) -> str:
    if endpoint.startswith("[") and "]" in endpoint:
        return endpoint[1 : endpoint.index("]")]
    host, separator, _port = endpoint.rpartition(":")
    return host if separator else endpoint


def websocket_client(expected_peers) -> str:
    output = run_command(
        ["ss", "-Htn", "state", "established", f"sport = :{WEBSOCKET_PORT}"]
    )
    remote_addresses = {
        endpoint_host(line.split()[-1])
        for line in output.splitlines()
        if line.split()
    }

    for peer_name, label in EXPECTED_WEBSOCKET_CLIENTS:
        peer = expected_peers.get(peer_name) or {}
        if remote_addresses.intersection(peer.get("addresses") or []):
            return label
    return "OFF"


def tcp_port_online(host: str, port: int, timeout: float) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def collect_status(internet_timeout: float) -> StatusSnapshot:
    mode, connection, interface, local_ip = network_status()
    tailscale_state, tailscale_ip, expected_peers = tailscale_status()
    internet_is_online = internet_online(internet_timeout)
    connected_websocket_client = websocket_client(expected_peers)
    mockingbeat = expected_peers.get("mockingbeat") or {}
    mockingbeat_addresses = mockingbeat.get("addresses") or []
    mockingbeat_ipv4 = next(
        (address for address in mockingbeat_addresses if ":" not in address),
        "mockingbeat",
    )
    mockingbeat_api_online = tcp_port_online(
        mockingbeat_ipv4,
        MOCKINGBEAT_API_PORT,
        min(internet_timeout, 1.0),
    )
    timestamp = eastern_timestamp()
    return StatusSnapshot(
        ubuntu=ubuntu_version(),
        network_mode=mode,
        network_name=connection,
        interface=interface,
        local_ip=local_ip,
        internet_online=internet_is_online,
        tailscale_state=tailscale_state,
        tailscale_ip=tailscale_ip,
        websocket_client=connected_websocket_client,
        mockingbeat_api_online=mockingbeat_api_online,
        current_time=timestamp,
        updated_at=timestamp,
    )


def eastern_timestamp() -> str:
    return datetime.now().astimezone().strftime("%I:%M:%S %p %Z")


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
    draw.text((12, 35), status.current_time, fill=(185, 208, 231), font=font_body)

    draw.rectangle((8, 67, WIDTH - 8, 138), fill="white", outline=border)
    draw.text((18, 75), "NETWORK", fill=muted, font=font_label)
    mode_color = status_color(status.network_mode != "Disconnected")
    draw.ellipse((18, 99, 28, 109), fill=mode_color)
    draw.text((35, 91), status.network_mode, fill=(26, 36, 46), font=font_value)
    draw.text((18, 118), f"IP  {status.local_ip}", fill=muted, font=font_body)

    draw.rectangle((8, 147, WIDTH - 8, 207), fill="white", outline=border)
    draw.text((18, 155), "CONNECTIVITY", fill=muted, font=font_label)
    draw.ellipse((18, 181, 30, 193), fill=status_color(status.internet_online))
    draw.text((37, 175), "INTERNET", fill=(26, 36, 46), font=font_body)

    tailscale_online = status.tailscale_state == "Connected"
    draw.ellipse((130, 181, 142, 193), fill=status_color(tailscale_online))
    draw.text((149, 175), "TAILSCALE", fill=(26, 36, 46), font=font_body)

    draw.rectangle((8, 216, WIDTH - 8, 294), fill="white", outline=border)
    draw.text((18, 224), "SERVICES", fill=muted, font=font_label)

    websocket_online = status.websocket_client != "OFF"
    draw.text((18, 244), "WS", fill=(26, 36, 46), font=font_body)
    draw.ellipse((55, 249, 67, 261), fill=status_color(websocket_online))
    draw.text((75, 243), status.websocket_client, fill=(26, 36, 46), font=font_body)

    draw.text((18, 271), "MB API :3000", fill=(26, 36, 46), font=font_body)
    draw.ellipse(
        (136, 276, 148, 288),
        fill=status_color(status.mockingbeat_api_online),
    )
    api_text = "UP" if status.mockingbeat_api_online else "DOWN"
    draw.text((157, 270), api_text, fill=(26, 36, 46), font=font_body)

    footer = f"updated {status.updated_at}"
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
        default=1.0,
        help="display refresh interval in seconds (default: 1)",
    )
    parser.add_argument(
        "--status-interval",
        type=positive_float,
        default=5.0,
        help="network status refresh interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--internet-timeout",
        type=positive_float,
        default=1.0,
        help="timeout per Internet check in seconds (default: 1)",
    )
    return parser.parse_args()


def request_stop(_signum, _frame) -> None:
    global stop_requested
    stop_requested = True


def main() -> None:
    args = parse_args()

    if args.print_status:
        print(json.dumps(asdict(collect_status(args.internet_timeout)), indent=2))
        return

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    display = Waveshare2Inch()
    try:
        display.initialize()
        display.show(render_starting())

        status: Optional[StatusSnapshot] = None
        next_status_refresh = 0.0
        while not stop_requested:
            started = time.monotonic()
            status_refreshed = status is None or started >= next_status_refresh
            if status_refreshed:
                status = collect_status(args.internet_timeout)
                next_status_refresh = started + args.status_interval
            else:
                status = replace(status, current_time=eastern_timestamp())

            display.show(render_status(status))
            if status_refreshed:
                print(
                    f"{status.updated_at} network={status.network_mode} "
                    f"ip={status.local_ip} internet={'online' if status.internet_online else 'offline'} "
                    f"tailscale={status.tailscale_state} tailscale_ip={status.tailscale_ip} "
                    f"websocket={status.websocket_client.lower()} "
                    f"mockingbeat_api={'up' if status.mockingbeat_api_online else 'down'}",
                    flush=True,
                )

            if args.once or stop_requested:
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.1, args.interval - elapsed))
    finally:
        display.close()


if __name__ == "__main__":
    main()
