# Soysan LCD

Status and utility scripts for the Waveshare 2-inch LCD on the Xavier NX.

## Main status screen

`main.py` shows local and Tailscale IPs, Internet and Tailscale health,
connected WebSocket devices, and Mockingbeat API port 3000. The top strip shows
the drone model and charge when telemetry is fresh, or a disconnected-drone
indicator otherwise. The telemetry identifier `PM430` is displayed as
`M300 RTK`. The footer shows Eastern time and the relative age of the last
status check. Time refreshes every second; status checks refresh every five
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
