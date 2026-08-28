#!/usr/bin/env python3
"""Shared ST7789 driver for the Soysan Waveshare 2-inch LCD."""

import time

import Jetson.GPIO as GPIO
import spidev
from PIL import Image, ImageFont


WIDTH = 240
HEIGHT = 320
DC_PIN = 29
RST_PIN = 31
SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 10_000_000


class Waveshare2Inch:
    def __init__(self) -> None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(DC_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(RST_PIN, GPIO.OUT, initial=GPIO.HIGH)

        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEVICE)
        self.spi.mode = 0
        self.spi.bits_per_word = 8
        self.spi.max_speed_hz = SPI_SPEED_HZ

    def close(self) -> None:
        self.spi.close()
        GPIO.cleanup()

    def reset(self) -> None:
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.01)
        GPIO.output(RST_PIN, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.12)

    def command(self, value: int, data=()) -> None:
        GPIO.output(DC_PIN, GPIO.LOW)
        self.spi.xfer2([value])
        if data:
            GPIO.output(DC_PIN, GPIO.HIGH)
            self.spi.xfer2(list(data))

    def initialize(self) -> None:
        self.reset()
        commands = (
            (0x36, (0x00,)),
            (0x3A, (0x05,)),
            (0x21, ()),
            (0x2A, (0x00, 0x00, 0x01, 0x3F)),
            (0x2B, (0x00, 0x00, 0x00, 0xEF)),
            (0xB2, (0x0C, 0x0C, 0x00, 0x33, 0x33)),
            (0xB7, (0x35,)),
            (0xBB, (0x1F,)),
            (0xC0, (0x2C,)),
            (0xC2, (0x01,)),
            (0xC3, (0x12,)),
            (0xC4, (0x20,)),
            (0xC6, (0x0F,)),
            (0xD0, (0xA4, 0xA1)),
            (
                0xE0,
                (0xD0, 0x08, 0x11, 0x08, 0x0C, 0x15, 0x39,
                 0x33, 0x50, 0x36, 0x13, 0x14, 0x29, 0x2D),
            ),
            (
                0xE1,
                (0xD0, 0x08, 0x10, 0x08, 0x06, 0x06, 0x39,
                 0x44, 0x51, 0x0B, 0x16, 0x14, 0x2F, 0x31),
            ),
        )
        for command, data in commands:
            self.command(command, data)

        self.command(0x11)
        time.sleep(0.12)
        self.command(0x29)
        time.sleep(0.02)

    def set_window(self) -> None:
        self.command(0x36, (0x00,))
        self.command(0x2A, (0x00, 0x00, 0x00, WIDTH - 1))
        self.command(
            0x2B,
            (0x00, 0x00, (HEIGHT - 1) >> 8, (HEIGHT - 1) & 0xFF),
        )
        self.command(0x2C)

    def write_pixels(self, pixels: bytes) -> None:
        self.set_window()
        GPIO.output(DC_PIN, GPIO.HIGH)
        for offset in range(0, len(pixels), 4096):
            self.spi.writebytes2(pixels[offset : offset + 4096])

    def fill(self, rgb565: int) -> None:
        pixel = bytes((rgb565 >> 8, rgb565 & 0xFF))
        self.write_pixels(pixel * (WIDTH * HEIGHT))

    def show(self, image: Image.Image) -> None:
        image = image.convert("RGB").resize((WIDTH, HEIGHT))
        output = bytearray(WIDTH * HEIGHT * 2)
        index = 0
        for red, green, blue in image.getdata():
            value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
            output[index] = value >> 8
            output[index + 1] = value & 0xFF
            index += 2
        self.write_pixels(output)


def load_font(size: int):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()
