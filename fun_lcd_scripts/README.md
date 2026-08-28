# Fun LCD scripts

Small visual experiments for the Soysan LCD.

## Show a video stream

Stream a V4L2 capture device until `Ctrl+C`:

```bash
sudo systemctl stop soysan-lcd.service
python3 show_video.py /dev/video0
```

Rotate a landscape feed or stop automatically after 30 seconds:

```bash
python3 show_video.py /dev/video0 --rotate 90 --fit contain
python3 show_video.py /dev/video0 --duration 30
```

The defaults request 640×480 MJPEG at 30 capture FPS and update the LCD at up
to 5 FPS. OpenCV is required (`sudo apt install python3-opencv`). Use
`v4l2-ctl --list-devices` to find capture devices; some adjacent `/dev/video*`
nodes contain metadata rather than frames.

## Show an image

Stop the status screen, then pass an image path:

```bash
sudo systemctl stop soysan-lcd.service
python3 show_image.py ~/Pictures/photo.jpg
```

Use `--fit cover` to fill the screen by cropping the edges, or change the
letterbox color with `--background white`. Rotate between portrait and landscape
with a clockwise multiple of 90 degrees:

```bash
python3 show_image.py ~/Pictures/photo.jpg --rotate 90
python3 show_image.py ~/Pictures/photo.jpg --rotate -90 --fit cover
```

Restart the status screen afterward:

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
