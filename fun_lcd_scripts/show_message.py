#!/usr/bin/env python3
"""Show a command-line emoji and message on the Soysan LCD."""

import argparse
from io import BytesIO
from pathlib import Path
import sys
import urllib.error
import urllib.request

from PIL import Image, ImageColor, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lcd_driver import HEIGHT, WIDTH, Waveshare2Inch, load_font


# Twemoji graphics are copyright their contributors and licensed CC-BY 4.0.
TWEMOJI_URL = (
    "https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{codepoint}.png"
)
CACHE_DIR = Path.home() / ".cache" / "soysan-lcd" / "twemoji"


def emoji_codepoint(value: str) -> str:
    """Return the filename format used by Twemoji."""
    codepoints = (f"{ord(character):x}" for character in value)
    # Twemoji filenames normally omit the emoji variation selector.
    return "-".join(codepoint for codepoint in codepoints if codepoint != "fe0f")


def load_emoji(value: str):
    """Load a cached Twemoji image or download it once."""
    codepoint = emoji_codepoint(value)
    if not codepoint:
        return None

    cache_path = CACHE_DIR / f"{codepoint}.png"
    if cache_path.exists():
        return Image.open(str(cache_path)).convert("RGBA")

    request = urllib.request.Request(
        TWEMOJI_URL.format(codepoint=codepoint),
        headers={"User-Agent": "soysan-lcd/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            content = response.read()
        emoji = Image.open(BytesIO(content)).convert("RGBA")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        return emoji
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
        print(f"Warning: could not load Twemoji graphic: {error}", file=sys.stderr)
        return None


def text_width(draw: ImageDraw.ImageDraw, value: str, font) -> int:
    return draw.textsize(value, font=font)[0]


def split_long_word(draw, word: str, font, max_width: int):
    pieces = []
    current = ""
    for character in word:
        candidate = current + character
        if current and text_width(draw, candidate, font) > max_width:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def wrap_text(draw, value: str, font, max_width: int):
    lines = []
    for paragraph in value.splitlines() or [""]:
        words = paragraph.split() or [""]
        current = ""
        for word in words:
            candidates = (
                split_long_word(draw, word, font, max_width)
                if text_width(draw, word, font) > max_width
                else [word]
            )
            for candidate_word in candidates:
                candidate_line = (
                    f"{current} {candidate_word}" if current else candidate_word
                )
                if current and text_width(draw, candidate_line, font) > max_width:
                    lines.append(current)
                    current = candidate_word
                else:
                    current = candidate_line
        lines.append(current)
    return lines


def fit_message(draw, value: str, max_width: int, max_height: int):
    for size in range(30, 13, -1):
        font = load_font(size)
        lines = wrap_text(draw, value, font, max_width)
        line_height = size + 6
        if len(lines) * line_height <= max_height:
            return font, lines, line_height
    font = load_font(14)
    return font, wrap_text(draw, value, font, max_width), 20


def draw_message(emoji_text: str, message: str, background, foreground, size: int):
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)

    emoji = load_emoji(emoji_text)
    if emoji is not None:
        scale = min(size / emoji.width, size / emoji.height)
        emoji = emoji.resize(
            (max(1, round(emoji.width * scale)), max(1, round(emoji.height * scale))),
            Image.LANCZOS,
        )
        emoji_x = (WIDTH - emoji.width) // 2
        emoji_y = 18 + (size - emoji.height) // 2
        image.paste(emoji, (emoji_x, emoji_y), emoji)
    else:
        # Monochrome fallback for symbols supported by DejaVu Sans.
        emoji_font = load_font(min(size, 96))
        emoji_width, emoji_height = draw.textsize(emoji_text, font=emoji_font)
        draw.text(
            ((WIDTH - emoji_width) // 2, 18 + (size - emoji_height) // 2),
            emoji_text,
            font=emoji_font,
            fill=foreground,
        )

    message_top = min(178, size + 38)
    max_height = HEIGHT - message_top - 14
    font, lines, line_height = fit_message(draw, message, WIDTH - 28, max_height)
    y = message_top + max(0, (max_height - len(lines) * line_height) // 2)
    for line in lines:
        width = text_width(draw, line, font)
        draw.text(((WIDTH - width) // 2, y), line, font=font, fill=foreground)
        y += line_height

    return image


def parse_color(parser, value: str):
    try:
        return ImageColor.getrgb(value)
    except ValueError:
        parser.error(f"invalid color: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("emoji", help='emoji to display, for example "🚁"')
    parser.add_argument("text", nargs="+", help="message shown below the emoji")
    parser.add_argument("--background", default="white", help="background color")
    parser.add_argument("--text-color", default="black", help="message color")
    parser.add_argument(
        "--emoji-size",
        type=int,
        default=128,
        choices=range(48, 161),
        metavar="48-160",
    )
    args = parser.parse_args()

    if not Path("/dev/spidev0.0").exists():
        parser.error("/dev/spidev0.0 is missing; run: sudo modprobe spidev")

    background = parse_color(parser, args.background)
    foreground = parse_color(parser, args.text_color)
    message = " ".join(args.text)
    image = draw_message(
        args.emoji,
        message,
        background,
        foreground,
        args.emoji_size,
    )

    display = Waveshare2Inch()
    try:
        display.initialize()
        display.show(image)
        print(f'Displayed {args.emoji} with message: "{message}"')
    finally:
        display.close()


if __name__ == "__main__":
    main()
