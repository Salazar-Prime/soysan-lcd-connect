# Soysan LCD

Status and utility scripts for the Waveshare 2-inch LCD on the Xavier NX.

## Main status screen

`main.py` shows Ubuntu, network mode, local IP, Internet status, and Tailscale
status. It refreshes every five seconds.

```bash
./run_status_display.sh
```

Useful alternatives:

```bash
./run_status_display.sh --once
python3 main.py --print-status
```

## Folders

- [`test-screen-setup/`](test-screen-setup/) — wiring, SPI setup, verification,
  and color tests.
- [`fun_lcd_scripts/`](fun_lcd_scripts/) — small visual and message scripts.

`lcd_driver.py` is the shared LCD driver used by all scripts.
