#!/usr/bin/env python3
"""Color and text test for the Waveshare 2-inch ST7789 SPI LCD.

Wiring for the NVIDIA Jetson Xavier NX Developer Kit (BOARD numbering):
  LCD VCC -> pin 1       LCD GND -> pin 20
  LCD DIN -> pin 19      LCD CLK -> pin 23
  LCD CS  -> pin 24      LCD DC  -> pin 29
  LCD RST -> pin 31      LCD BL  -> pin 17
"""

import argparse
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch, load_font



def make_test_image() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 62), fill=(22, 74, 145))
    draw.text((18, 15), "VED SCOUT", fill="white", font=load_font(25))
    draw.text((18, 82), "LCD connected", fill="black", font=load_font(22))
    draw.text((18, 120), "240 x 320", fill=(60, 60, 60), font=load_font(18))
    draw.rectangle((18, 166, 73, 221), fill="red")
    draw.rectangle((92, 166, 147, 221), fill="green")
    draw.rectangle((166, 166, 221, 221), fill="blue")
    draw.text((35, 255), "SPI TEST: PASS", fill=(0, 110, 45), font=load_font(20))
    return image


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=positive_int, default=1)
    parser.add_argument("--color-seconds", type=nonnegative_float, default=1.0)
    parser.add_argument("--test-seconds", type=nonnegative_float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    display = Waveshare2Inch()
    try:
        print("Initializing ST7789 display...")
        display.initialize()
        test_image = make_test_image()

        for cycle in range(1, args.cycles + 1):
            print(f"LCD cycle {cycle} of {args.cycles}")
            for name, color in (
                ("red", 0xF800),
                ("green", 0x07E0),
                ("blue", 0x001F),
            ):
                print(f"Showing {name}...")
                display.fill(color)
                time.sleep(args.color_seconds)

            print("Showing labeled test image...")
            display.show(test_image)
            if cycle < args.cycles:
                time.sleep(args.test_seconds)

        print("Display test complete; the final image will remain on screen.")
    finally:
        display.close()


if __name__ == "__main__":
    main()
