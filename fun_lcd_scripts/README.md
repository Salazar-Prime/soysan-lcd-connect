# Fun LCD scripts

Small visual experiments for the Soysan LCD.

Show an emoji and message:

```bash
python3 show_message.py "🚁" "Soysan ready"
```

Change the colors:

```bash
python3 show_message.py "✅" "Connected" --background navy --text-color white
```

The first use of an emoji downloads its Twemoji image and caches it locally.
