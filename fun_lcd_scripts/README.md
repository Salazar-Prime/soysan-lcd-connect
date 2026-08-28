# Fun LCD scripts

Small visual experiments for the Soysan LCD.

## Show an image

Stop the status screen, then pass an image path:

```bash
sudo systemctl stop soysan-lcd.service
python3 show_image.py ~/Pictures/photo.jpg
```

Use `--fit cover` to fill the screen by cropping the edges, or change the
letterbox color with `--background white`. Restart the status screen afterward:

```bash
sudo systemctl start soysan-lcd.service
```

## Show a message

Show an emoji and message:

```bash
python3 show_message.py "🚁" "Soysan ready"
```

Change the colors:

```bash
python3 show_message.py "✅" "Connected" --background navy --text-color white
```

The first use of an emoji downloads its Twemoji image and caches it locally.
