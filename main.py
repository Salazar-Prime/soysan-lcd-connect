#!/usr/bin/env python3
"""Continuously show Soysan connectivity status on the 2-inch LCD."""

import argparse
import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

try:
    import websockets
except ImportError:
    websockets = None

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch, load_font


os.environ["TZ"] = os.environ.get("SOYSAN_LCD_TIMEZONE", "America/New_York")
if hasattr(time, "tzset"):
    time.tzset()

stop_requested = False
WEBSOCKET_PORT = 8765
MOCKINGBEAT_API_PORT = 3000
WEBSOCKET_GRACE_SECONDS = 10.0
BATTERY_MAX_AGE_SECONDS = 5.0
EXPECTED_WEBSOCKET_CLIENTS = (
    ("mockingbeat", "MOCKING"),
    ("7empest", "7EMPEST"),
)
websocket_client_last_seen = {}


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
    websocket_clients: tuple
    mockingbeat_api_online: bool
    drone_battery: Optional[int]
    current_time: str
    updated_at: str


class DroneBatteryMonitor:
    """Keep the latest fresh battery value from Soysan's telemetry stream."""

    def __init__(self) -> None:
        self._enabled = False
        self._tailscale_ip = ""
        self._battery = None
        self._battery_updated_at = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        if websockets is None or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            name="soysan-lcd-battery",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=4.0)

    def set_enabled(self, enabled: bool, tailscale_ip: str) -> None:
        usable_ip = tailscale_ip if tailscale_ip not in {"", "--"} else ""
        with self._lock:
            self._enabled = enabled and bool(usable_ip)
            self._tailscale_ip = usable_ip
            if not self._enabled:
                self._battery = None
                self._battery_updated_at = 0.0

    def battery(self) -> Optional[int]:
        with self._lock:
            if not self._enabled or self._battery is None:
                return None
            if time.monotonic() - self._battery_updated_at > BATTERY_MAX_AGE_SECONDS:
                return None
            return self._battery

    def _connection_state(self):
        with self._lock:
            return self._enabled, self._tailscale_ip

    def _set_battery(self, battery) -> None:
        with self._lock:
            if battery is None:
                self._battery = None
                self._battery_updated_at = 0.0
                return
            self._battery = max(0, min(100, int(round(float(battery)))))
            self._battery_updated_at = time.monotonic()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as error:
            print(f"Battery telemetry monitor stopped: {error}", flush=True)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            enabled, tailscale_ip = self._connection_state()
            if not enabled:
                await asyncio.sleep(0.5)
                continue

            try:
                await self._consume_telemetry(tailscale_ip)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._set_battery(None)
                await asyncio.sleep(2.0)

    async def _consume_telemetry(self, tailscale_ip: str) -> None:
        endpoint = (
            f"ws://[{tailscale_ip}]:{WEBSOCKET_PORT}"
            if ":" in tailscale_ip
            else f"ws://{tailscale_ip}:{WEBSOCKET_PORT}"
        )
        async with websockets.connect(
            endpoint,
            open_timeout=3,
            close_timeout=1,
            ping_interval=10,
            ping_timeout=5,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "subscribe_telemetry",
                        "commandId": "lcd-battery-monitor",
                    }
                )
            )

            while not self._stop_event.is_set():
                enabled, current_ip = self._connection_state()
                if not enabled or current_ip != tailscale_ip:
                    self._set_battery(None)
                    return
                try:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                try:
                    message = json.loads(raw_message)
                except (json.JSONDecodeError, TypeError):
                    continue
                data = message.get("data") or {}
                battery = data.get("battery")
                if (
                    message.get("type") == "telemetry"
                    and message.get("aircraftConnected") is True
                    and isinstance(battery, (int, float))
                ):
                    self._set_battery(battery)


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


def websocket_clients(expected_peers, now: Optional[float] = None) -> tuple:
    output = run_command(
        ["ss", "-Htn", "state", "established", f"sport = :{WEBSOCKET_PORT}"]
    )
    remote_addresses = {
        endpoint_host(line.split()[-1])
        for line in output.splitlines()
        if line.split()
    }

    checked_at = time.monotonic() if now is None else now
    detected = set()
    for peer_name, label in EXPECTED_WEBSOCKET_CLIENTS:
        peer = expected_peers.get(peer_name) or {}
        if remote_addresses.intersection(peer.get("addresses") or []):
            detected.add(label)
            websocket_client_last_seen[label] = checked_at

    return tuple(
        label
        for _peer_name, label in EXPECTED_WEBSOCKET_CLIENTS
        if label in detected
        or checked_at - websocket_client_last_seen.get(label, float("-inf"))
            <= WEBSOCKET_GRACE_SECONDS
    )


def tcp_port_online(host: str, port: int, timeout: float) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def collect_status(
    internet_timeout: float,
    drone_battery: Optional[int] = None,
) -> StatusSnapshot:
    mode, connection, interface, local_ip = network_status()
    tailscale_state, tailscale_ip, expected_peers = tailscale_status()
    internet_is_online = internet_online(internet_timeout)
    connected_websocket_clients = websocket_clients(expected_peers)
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
        websocket_clients=connected_websocket_clients,
        mockingbeat_api_online=mockingbeat_api_online,
        drone_battery=drone_battery,
        current_time=timestamp,
        updated_at=timestamp,
    )


def eastern_timestamp() -> str:
    return datetime.now().astimezone().strftime("%I:%M:%S %p")


def fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textsize(text, font=font)[0] <= max_width:
        return text
    shortened = text
    while shortened and draw.textsize(f"{shortened}...", font=font)[0] > max_width:
        shortened = shortened[:-1]
    return f"{shortened}..." if shortened else "..."


def status_color(healthy: bool):
    return (26, 170, 99) if healthy else (210, 62, 74)


def load_data_font(size: int):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            size,
        )
    except OSError:
        return load_font(size)


def draw_right_text(draw, right: int, y: int, text: str, font, fill) -> None:
    width = draw.textsize(text, font=font)[0]
    draw.text((right - width, y), text, fill=fill, font=font)


def draw_rounded_rectangle(draw, bounds, radius: int, fill, outline=None) -> None:
    left, top, right, bottom = bounds
    diameter = radius * 2
    draw.rectangle((left + radius, top, right - radius, bottom), fill=fill)
    draw.rectangle((left, top + radius, right, bottom - radius), fill=fill)
    draw.ellipse((left, top, left + diameter, top + diameter), fill=fill)
    draw.ellipse((right - diameter, top, right, top + diameter), fill=fill)
    draw.ellipse((left, bottom - diameter, left + diameter, bottom), fill=fill)
    draw.ellipse((right - diameter, bottom - diameter, right, bottom), fill=fill)
    if outline is None:
        return
    draw.line((left + radius, top, right - radius, top), fill=outline)
    draw.line((left + radius, bottom, right - radius, bottom), fill=outline)
    draw.line((left, top + radius, left, bottom - radius), fill=outline)
    draw.line((right, top + radius, right, bottom - radius), fill=outline)
    draw.arc((left, top, left + diameter, top + diameter), 180, 270, fill=outline)
    draw.arc((right - diameter, top, right, top + diameter), 270, 360, fill=outline)
    draw.arc((left, bottom - diameter, left + diameter, bottom), 90, 180, fill=outline)
    draw.arc((right - diameter, bottom - diameter, right, bottom), 0, 90, fill=outline)


def draw_status_pill(draw, bounds, label: str, healthy: bool, font) -> None:
    ink = (31, 45, 59)
    border = (205, 216, 225)
    draw_rounded_rectangle(draw, bounds, radius=15, fill="white", outline=border)
    left, top, _right, _bottom = bounds
    draw.ellipse((left + 10, top + 9, left + 22, top + 21), fill=status_color(healthy))
    draw.text((left + 29, top + 6), label, fill=ink, font=font)


def draw_phone_icon(draw, x: int, y: int, color) -> None:
    pale_green = (231, 248, 239)
    draw_rounded_rectangle(
        draw,
        (x, y, x + 15, y + 25),
        radius=3,
        fill=pale_green,
        outline=color,
    )
    draw.line((x + 5, y + 4, x + 10, y + 4), fill=color, width=1)
    draw.ellipse((x + 6, y + 20, x + 9, y + 23), fill=color)


def draw_laptop_icon(draw, x: int, y: int, color) -> None:
    pale_green = (231, 248, 239)
    draw.rectangle(
        (x + 2, y, x + 24, y + 16),
        fill=pale_green,
        outline=color,
        width=2,
    )
    draw.polygon(
        ((x, y + 18), (x + 26, y + 18), (x + 22, y + 22), (x + 4, y + 22)),
        fill=color,
    )


def draw_battery(draw, percentage: int, font) -> None:
    if percentage > 50:
        color = (46, 204, 113)
    elif percentage > 20:
        color = (242, 169, 59)
    else:
        color = (239, 83, 80)

    x, y = 164, 17
    draw_rounded_rectangle(
        draw,
        (x, y, x + 27, y + 16),
        radius=2,
        fill=(15, 42, 67),
        outline=color,
    )
    draw.rectangle((x + 28, y + 5, x + 31, y + 11), fill=color)
    fill_width = int(21 * percentage / 100)
    if fill_width > 0:
        draw.rectangle((x + 3, y + 3, x + 3 + fill_width, y + 13), fill=color)
    draw_right_text(draw, WIDTH - 9, 15, f"{percentage}%", font, "white")


def render_status(status: StatusSnapshot) -> Image.Image:
    background = (239, 244, 248)
    navy = (15, 42, 67)
    ink = (31, 45, 59)
    muted = (82, 96, 109)
    border = (205, 216, 225)

    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    font_time = load_font(18)
    font_mode = load_font(17)
    font_body = load_font(13)
    font_label = load_font(11)
    font_small = load_font(10)
    font_data = load_data_font(12)

    # Flight-deck strip: time and fresh aircraft battery only.
    draw.rectangle((0, 0, WIDTH, 49), fill=navy)
    draw.text((11, 13), status.current_time, fill="white", font=font_time)
    if status.drone_battery is not None:
        draw_battery(draw, status.drone_battery, font_body)

    # Network identity. The two addresses share one quiet navigation band.
    draw.rectangle((0, 50, WIDTH, 105), fill="white")
    draw.text((12, 58), status.network_mode, fill=ink, font=font_mode)
    draw_right_text(draw, WIDTH - 12, 61, status.local_ip, font_data, ink)
    draw.line((12, 79, WIDTH - 12, 79), fill=border)
    draw.text((12, 84), "TAILSCALE IP", fill=muted, font=font_small)
    draw_right_text(draw, WIDTH - 12, 82, status.tailscale_ip, font_data, muted)

    draw_status_pill(
        draw,
        (8, 113, 113, 143),
        "Internet",
        status.internet_online,
        font_body,
    )
    draw_status_pill(
        draw,
        (121, 113, WIDTH - 8, 143),
        "Tailscale",
        status.tailscale_state == "Connected",
        font_body,
    )

    draw.text((11, 156), "SOYSAN STATUS", fill=muted, font=font_label)
    draw_rounded_rectangle(
        draw,
        (8, 174, WIDTH - 8, 294),
        radius=6,
        fill="white",
        outline=border,
    )

    draw.text((18, 187), "WebSocket", fill=ink, font=font_body)
    clients = set(status.websocket_clients)
    connected_color = status_color(True)
    if clients == {"MOCKING", "7EMPEST"}:
        draw_laptop_icon(draw, 160, 183, connected_color)
        draw_phone_icon(draw, 207, 181, connected_color)
    elif "MOCKING" in clients:
        draw_laptop_icon(draw, 119, 183, connected_color)
        draw.text((154, 187), "MOCKING", fill=ink, font=font_body)
    elif "7EMPEST" in clients:
        draw_phone_icon(draw, 133, 181, connected_color)
        draw.text((158, 187), "7EMPEST", fill=ink, font=font_body)
    else:
        draw.ellipse((174, 190, 186, 202), fill=status_color(False))
        draw.text((194, 184), "OFF", fill=ink, font=font_body)

    draw.line((18, 224, WIDTH - 18, 224), fill=border)
    draw.text((18, 247), "API server", fill=ink, font=font_body)
    draw.text((91, 249), ":3000", fill=muted, font=font_data)
    draw.ellipse(
        (171, 252, 183, 264),
        fill=status_color(status.mockingbeat_api_online),
    )
    api_text = "UP" if status.mockingbeat_api_online else "DOWN"
    draw.text((192, 246), api_text, fill=ink, font=font_body)

    footer = f"updated {status.updated_at}"
    draw.text(
        (12, 305),
        fit_text(draw, footer, font_small, WIDTH - 24),
        fill=muted,
        font=font_small,
    )
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

    battery_monitor = DroneBatteryMonitor()
    battery_monitor.start()
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
                status = collect_status(
                    args.internet_timeout,
                    drone_battery=battery_monitor.battery(),
                )
                battery_monitor.set_enabled(
                    bool(status.websocket_clients),
                    status.tailscale_ip,
                )
                next_status_refresh = started + args.status_interval
            else:
                status = replace(
                    status,
                    current_time=eastern_timestamp(),
                    drone_battery=battery_monitor.battery(),
                )

            display.show(render_status(status))
            if status_refreshed:
                print(
                    f"{status.updated_at} network={status.network_mode} "
                    f"ip={status.local_ip} internet={'online' if status.internet_online else 'offline'} "
                    f"tailscale={status.tailscale_state} tailscale_ip={status.tailscale_ip} "
                    f"websocket={','.join(client.lower() for client in status.websocket_clients) or 'off'} "
                    f"mockingbeat_api={'up' if status.mockingbeat_api_online else 'down'} "
                    f"battery={status.drone_battery if status.drone_battery is not None else '--'}",
                    flush=True,
                )

            if args.once or stop_requested:
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.1, args.interval - elapsed))
    finally:
        battery_monitor.stop()
        display.close()


if __name__ == "__main__":
    main()
