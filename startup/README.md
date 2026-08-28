# Start the LCD on boot

Install and start the systemd service:

```bash
./install.sh
```

The clock refreshes every second. Network, Internet, and Tailscale status are
checked every five seconds.

Check it:

```bash
systemctl status soysan-lcd.service
journalctl -u soysan-lcd.service -f
```

Stop or restart it:

```bash
sudo systemctl stop soysan-lcd.service
sudo systemctl restart soysan-lcd.service
```

Remove the boot service:

```bash
./uninstall.sh
```

Stop the service before running another LCD script. The display is write-only,
so physical panel presence cannot be read back; the service verifies the Xavier
SPI endpoint instead. Restart the service after reconnecting the LCD.
