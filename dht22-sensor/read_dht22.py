#!/usr/bin/env python3
"""Print DHT22 temperature and humidity readings to the console."""

import argparse
from datetime import datetime
import sys
import time


def read_interval(value: str) -> float:
    interval = float(value)
    if interval < 2.0:
        raise argparse.ArgumentTypeError("must be at least 2 seconds")
    return interval


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def load_sensor():
    try:
        import adafruit_dht
        import board
    except ImportError as error:
        print(
            "DHT dependencies are missing. Run: "
            "python3 -m pip install --user -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(2) from error

    if not hasattr(board, "D4"):
        print("Blinka did not expose Xavier GPIO D4 (physical pin 7).", file=sys.stderr)
        raise SystemExit(2)

    return adafruit_dht.DHT22(board.D4, use_pulseio=False)


def format_reading(temperature_c: float, humidity: float) -> str:
    temperature_f = temperature_c * 9 / 5 + 32
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %I:%M:%S %p %Z")
    return (
        f"{timestamp} | Temperature: {temperature_c:.1f} °C / "
        f"{temperature_f:.1f} °F | Humidity: {humidity:.1f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="print one reading and exit",
    )
    parser.add_argument(
        "--interval",
        type=read_interval,
        default=2.5,
        help="seconds between attempts; minimum 2 (default: 2.5)",
    )
    parser.add_argument(
        "--retries",
        type=positive_int,
        default=5,
        help="maximum attempts with --once (default: 5)",
    )
    args = parser.parse_args()

    sensor = load_sensor()
    failed_attempts = 0
    try:
        while True:
            try:
                temperature_c = sensor.temperature
                humidity = sensor.humidity
                if temperature_c is None or humidity is None:
                    raise RuntimeError("sensor returned an empty reading")
                print(format_reading(temperature_c, humidity), flush=True)
                if args.once:
                    return
            except RuntimeError as error:
                failed_attempts += 1
                print(f"Read failed: {error}", file=sys.stderr, flush=True)
                if args.once and failed_attempts >= args.retries:
                    raise SystemExit(1)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped DHT22 reader.")
    finally:
        sensor.exit()


if __name__ == "__main__":
    main()
