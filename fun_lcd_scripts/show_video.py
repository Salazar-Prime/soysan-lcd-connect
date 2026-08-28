#!/usr/bin/env python3
"""Stream a V4L2 video device to the Soysan LCD."""

import argparse
from pathlib import Path
import sys
import time

try:
    import cv2
except ImportError:
    cv2 = None
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from lcd_driver import Waveshare2Inch
from show_image import multiple_of_90, parse_color, resize_image, service_is_active


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def fourcc_code(value: str) -> str:
    code = value.upper()
    if len(code) != 4:
        raise argparse.ArgumentTypeError("must contain exactly four characters")
    return code


def open_capture(device: Path, width: int, height: int, fps: float, fourcc: str):
    capture = cv2.VideoCapture(str(device), cv2.CAP_V4L2)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"could not open video device: {device}")

    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def stream_frames(capture, display, args, background) -> tuple:
    started = time.monotonic()
    next_frame = started
    frames_displayed = 0
    read_failures = 0
    frame_interval = 1.0 / args.lcd_fps

    try:
        while args.duration is None or time.monotonic() - started < args.duration:
            delay = next_frame - time.monotonic()
            if delay > 0:
                time.sleep(delay)

            available, frame = capture.read()
            if not available:
                read_failures += 1
                if read_failures >= 10:
                    raise RuntimeError("video device returned no frames")
                time.sleep(0.1)
                continue

            read_failures = 0
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = resize_image(
                Image.fromarray(rgb_frame),
                args.fit,
                background,
                args.rotate,
            )
            display.show(image)
            frames_displayed += 1
            next_frame = max(next_frame + frame_interval, time.monotonic())
    except KeyboardInterrupt:
        print("Stopping video stream.")

    return frames_displayed, time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "device",
        nargs="?",
        type=Path,
        default=Path("/dev/video0"),
        help="V4L2 capture device (default: /dev/video0)",
    )
    parser.add_argument("--width", type=positive_int, default=640)
    parser.add_argument("--height", type=positive_int, default=480)
    parser.add_argument(
        "--capture-fps",
        type=positive_float,
        default=30.0,
        help="requested camera frame rate (default: 30)",
    )
    parser.add_argument(
        "--lcd-fps",
        type=positive_float,
        default=5.0,
        help="target LCD frame rate (default: 5)",
    )
    parser.add_argument(
        "--fourcc",
        type=fourcc_code,
        default="MJPG",
        help="camera pixel format code (default: MJPG)",
    )
    parser.add_argument(
        "--fit",
        choices=("contain", "cover", "stretch"),
        default="cover",
        help="sizing mode (default: cover)",
    )
    parser.add_argument(
        "--background",
        default="black",
        help="letterbox color used with --fit contain (default: black)",
    )
    parser.add_argument(
        "--rotate",
        type=multiple_of_90,
        default=0,
        metavar="DEGREES",
        help="clockwise rotation in multiples of 90 degrees (default: 0)",
    )
    parser.add_argument(
        "--duration",
        type=positive_float,
        help="stop after this many seconds (default: run until Ctrl+C)",
    )
    args = parser.parse_args()

    if cv2 is None:
        parser.error(
            "OpenCV is missing; install it with: sudo apt install python3-opencv"
        )
    if not args.device.exists():
        parser.error(f"video device is missing: {args.device}")
    if not Path("/dev/spidev0.0").exists():
        parser.error("/dev/spidev0.0 is missing; run: sudo modprobe spidev")

    background = parse_color(parser, args.background)
    if service_is_active():
        print(
            "Warning: soysan-lcd.service is active and may overwrite the video. "
            "Stop it first with: sudo systemctl stop soysan-lcd.service",
            file=sys.stderr,
        )

    try:
        capture = open_capture(
            args.device,
            args.width,
            args.height,
            args.capture_fps,
            args.fourcc,
        )
    except RuntimeError as error:
        parser.error(str(error))

    actual_width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = capture.get(cv2.CAP_PROP_FPS)
    print(
        f"Streaming {args.device}: {actual_width}x{actual_height} "
        f"at {actual_fps:.1f} capture FPS; target LCD FPS {args.lcd_fps:g}."
    )
    print("Press Ctrl+C to stop.")

    display = None
    frames_displayed = 0
    elapsed = 0.0
    try:
        display = Waveshare2Inch()
        display.initialize()
        frames_displayed, elapsed = stream_frames(
            capture,
            display,
            args,
            background,
        )
    except RuntimeError as error:
        print(f"Video stream failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        capture.release()
        if display is not None:
            display.close()

    average_fps = frames_displayed / elapsed if elapsed else 0.0
    print(
        f"Displayed {frames_displayed} frames "
        f"at an average of {average_fps:.1f} FPS."
    )


if __name__ == "__main__":
    main()
