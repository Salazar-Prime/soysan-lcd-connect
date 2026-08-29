# Soysan LCD

Status and utility scripts for the Waveshare 2-inch LCD on the Xavier NX.

## Main status screen

`main.py` shows Eastern time, local and Tailscale IPs, Internet and Tailscale
health, connected WebSocket devices, and Mockingbeat API port 3000. Fresh drone
telemetry adds the battery percentage while a recognized WebSocket client is
connected. The time refreshes every second; status checks refresh every five
seconds.

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
- [`fun_lcd_scripts/`](fun_lcd_scripts/) — display video, images, and messages.
- [`startup/`](startup/) — install or remove the automatic boot service.

`lcd_driver.py` is the shared LCD driver used by all scripts.
