# Waveshare 2-inch LCD on Soysan

This folder documents and tests the Waveshare **2inch LCD Module** connected to
the NVIDIA Jetson Xavier NX Developer Kit named `soysan`.

Verified on August 28, 2026 with:

- NVIDIA Jetson Xavier NX Developer Kit and P3509 carrier board
- Jetson Linux R35.6.0
- Waveshare 2inch LCD Module, 240 x 320, ST7789, four-wire SPI
- Linux SPI device `/dev/spidev0.0`

## Physical connection

The pin numbers below are **physical J12 header numbers** (`GPIO.BOARD`
numbering), not Linux GPIO numbers. Connect or change wiring only while the
Xavier is shut down and its power supply is disconnected.

| Jumper color | LCD pin | Xavier NX J12 physical pin | Purpose |
|---|---|---:|---|
| Purple | `VCC` | **1** | 3.3 V power |
| White | `GND` | **20** | Ground |
| Green | `DIN` | **19** | SPI MOSI |
| Orange | `CLK` | **23** | SPI clock |
| Yellow | `CS` | **24** | SPI chip select 0 |
| Blue | `DC` | **29** | Data/command GPIO |
| Brown | `RST` | **31** | Reset GPIO |
| Grey | `BL` | **17** | 3.3 V, backlight always on |

Relevant portion of the header:

```text
Odd-numbered row                    Even-numbered row

Pin  1: Purple (VCC)          Pin  2: 5 V — do not use
             ...                           ...
Pin 17: Grey   (BL)           Pin 18
Pin 19: Green  (DIN/MOSI)     Pin 20: White  (GND)
Pin 21: MISO, not connected   Pin 22
Pin 23: Orange (CLK)          Pin 24: Yellow (CS)
Pin 25: GND                   Pin 26
Pin 27                        Pin 28
Pin 29: Blue   (DC)           Pin 30: GND
Pin 31: Brown  (RST)          Pin 32
```

Important:

- The Xavier header uses 3.3 V signaling, so the LCD is powered from 3.3 V.
- Never connect a 5 V header pin to `DIN`, `CLK`, `CS`, `DC`, or `RST`.
- `BL` is tied to 3.3 V for full brightness. It is not software-controlled in
  this wiring.
- The LCD is write-only in this setup, so its MISO connection is not required.
- This is an SPI graphics panel, not an HDMI monitor. It does not automatically
  mirror the Xavier desktop.

## Enable SPI on the Xavier NX

First confirm the model and Jetson Linux release:

```bash
tr -d '\0' < /proc/device-tree/model
echo
cat /etc/nv_tegra_release
```

Enable `spi1`, which NVIDIA maps to physical pins 19, 21, 23, 24, and 26 and
exposes to Linux as SPI bus 0:

```bash
sudo /opt/nvidia/jetson-io/config-by-function.py -o dtb spi1
sudo reboot
```

The Jetson-IO command creates a custom device-tree boot entry. After rebooting,
load the user-space SPI driver and verify the display's SPI endpoint:

```bash
sudo modprobe spidev
ls -l /dev/spidev0.0
```

To load `spidev` automatically on future boots:

```bash
echo spidev | sudo tee /etc/modules-load.d/spidev.conf
```

You can inspect the active Jetson-IO boot entry with:

```bash
grep -E '^DEFAULT|LABEL JetsonIO|FDT .*user-custom' /boot/extlinux/extlinux.conf
```

## Python dependencies

Jetson.GPIO and Pillow are supplied as Ubuntu/NVIDIA packages on this machine.
The SPI Python binding was installed for user `usr`:

```bash
sudo apt update
sudo apt install python3-pip python3-pil python3-jetson-gpio
python3 -m pip install --user spidev
```

## Verify and test

Check the board, boot entry, SPI endpoint, and Python modules without changing
the display:

```bash
./verify_setup.sh
```

Run one red/green/blue cycle followed by the labeled test screen:

```bash
./run_lcd_test.sh
```

Run five cycles:

```bash
./run_lcd_test.sh --cycles 5
```

Useful options:

```text
--cycles N          Number of complete test cycles
--color-seconds S   Seconds to show each solid color (default: 1)
--test-seconds S    Seconds to show the labeled image between cycles (default: 2)
```

The last labeled image remains on the display after the program exits. User
`usr` belongs to the `gpio` group and runs the Python program normally. The run
wrapper requests `sudo` only when it needs to load the `spidev` kernel module.

## Files

- `waveshare_2inch_lcd_test.py` — ST7789 initialization and display test
- `run_lcd_test.sh` — loads `spidev` when needed and runs the Python test
- `verify_setup.sh` — read-only hardware and software readiness checks
- `requirements.txt` — Python package needed in addition to the Jetson packages

## Troubleshooting

- **Backlight off:** recheck Purple/VCC, White/GND, and Grey/BL with power off.
- **Backlight on but blackish-grey:** power is present, but the ST7789 has not
  received a valid reset or SPI initialization. Recheck Green/DIN, Orange/CLK,
  Yellow/CS, Blue/DC, and Brown/RST.
- **No `/dev/spidev0.0`:** confirm the JetsonIO boot entry is active, then run
  `sudo modprobe spidev`.
- **Permission denied opening SPI or GPIO:** confirm the current account belongs
  to the `gpio` group with `id`. Log out and back in after changing group
  membership.
- **Wrong colors or orientation:** confirm this is the non-touch Waveshare
  2inch LCD Module using the ST7789 controller, not another two-inch model.

## References

- [Waveshare 2inch LCD Module documentation](https://www.waveshare.com/wiki/2inch_LCD_Module)
- [NVIDIA Jetson expansion-header configuration](https://docs.nvidia.com/jetson/archives/r35.6.4/DeveloperGuide/HR/ConfiguringTheJetsonExpansionHeaders.html)
