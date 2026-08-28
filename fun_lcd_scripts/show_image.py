#!/usr/bin/env python3
"""Display an image file on the Soysan LCD."""

import argparse
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch


def resize_image(
    image: Image.Image,
    fit: str,
    background,
    rotation: int = 0,
) -> Image.Image:
    """Orient and fit an image onto the LCD-sized canvas."""
    source = ImageOps.exif_transpose(image).convert("RGBA")
    if rotation:
        source = source.rotate(-rotation, expand=True)
    size = (WIDTH, HEIGHT)

    if fit == "stretch":
        fitted = source.resize(size, Image.LANCZOS)
    elif fit == "cover":
        fitted = ImageOps.fit(source, size, method=Image.LANCZOS)
    else:
        fitted = source.copy()
        fitted.thumbnail(size, Image.LANCZOS)

    canvas = Image.new("RGB", size, background)
    position = ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2)
    canvas.paste(fitted, position, fitted)
    return canvas


def load_image(
    path: Path,
    fit: str,
    background,
    rotation: int = 0,
) -> Image.Image:
    try:
        with Image.open(str(path)) as image:
            return resize_image(image, fit, background, rotation)
    except FileNotFoundError:
        raise ValueError(f"image not found: {path}")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"could not open image {path}: {error}")


def service_is_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", "soysan-lcd.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def parse_color(parser: argparse.ArgumentParser, value: str):
    try:
        return ImageColor.getrgb(value)[:3]
    except ValueError:
        parser.error(f"invalid background color: {value}")


def multiple_of_90(value: str) -> int:
    try:
        degrees = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number")
    if degrees % 90 != 0:
        raise argparse.ArgumentTypeError("must be a multiple of 90 degrees")
    return degrees % 360


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        type=Path,
        help="path to a PNG, JPEG, or other Pillow image",
    )
    parser.add_argument(
        "--fit",
        choices=("contain", "cover", "stretch"),
        default="contain",
        help="sizing mode (default: contain)",
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
    args = parser.parse_args()

    if not Path("/dev/spidev0.0").exists():
        parser.error("/dev/spidev0.0 is missing; run: sudo modprobe spidev")

    background = parse_color(parser, args.background)
    try:
        image = load_image(
            args.image.expanduser(),
            args.fit,
            background,
            args.rotate,
        )
    except ValueError as error:
        parser.error(str(error))

    if service_is_active():
        print(
            "Warning: soysan-lcd.service is active and may replace this image. "
            "Stop it first with: sudo systemctl stop soysan-lcd.service",
            file=sys.stderr,
        )

    display = Waveshare2Inch()
    try:
        display.initialize()
        display.show(image)
        print(
            f"Displayed {args.image} using {args.fit} fit "
            f"with {args.rotate} degree clockwise rotation."
        )
    finally:
        display.close()


if __name__ == "__main__":
    main()
