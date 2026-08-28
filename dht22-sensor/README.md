# DHT22 console sensor

Read temperature and humidity from a three-wire DHT22/AM2302 module while the
Waveshare LCD remains connected.

## Wiring

Shut down Xavier and disconnect its power before changing wires. These are
physical J12 header pin numbers.

| Wire color | Sensor connection | Xavier NX J12 pin |
|---|---|---:|
| Purple | `+` / VCC | **1** — shared 3.3 V |
| Blue | `OUT` / DATA | **7** — free GPIO |
| Green | `-` / GND | **6** — ground |

Pin 1 is already used by the LCD's purple VCC wire. Use a breadboard power rail
or a proper two-way splitter:

1. Connect Xavier physical pin **1** to the breadboard positive rail.
2. Connect both the LCD purple VCC and DHT22 purple `+` wires to that rail.
3. Leave the LCD grey backlight wire on physical pin **17**.
4. Connect DHT22 blue `OUT` to physical pin **7**.
5. Connect DHT22 green `-` to physical pin **6**.

Do not power this module from a 5 V header pin. A three-wire DHT22 module often
has a pull-up resistor already. If yours does not, add a **4.7 kΩ to 10 kΩ**
resistor between purple `+` and blue `OUT`.

This guide assumes three electrical connections because three wires were
specified. A bare DHT22 normally has four pins (VCC, DATA, unused, GND). If the
device truly has only two terminals, stop and identify it before connecting it.

## Install

```bash
cd ~/work/LCD-screen-soysan/dht22-sensor
python3 -m pip install --user -r requirements.txt
```

## Read values

Read once, retrying transient DHT errors up to five times:

```bash
python3 read_dht22.py --once
```

Continuously print a reading every 2.5 seconds:

```bash
python3 read_dht22.py
```

Stop with `Ctrl+C`. DHT22 readings must be spaced by at least two seconds. The
script uses Blinka `board.D4`, which maps to Xavier NX physical pin **7**.

## Troubleshooting

- `DHT sensor not found`: recheck all three wires and the data pull-up.
- Intermittent checksum errors are normal; the script reports and retries them.
- Implausible readings: confirm the sensor is a DHT22/AM2302, not a DHT11.
- The LCD and sensor use different data pins and can operate at the same time.

References: [Adafruit DHT wiring guide](https://learn.adafruit.com/dht) and
[NVIDIA Jetson.GPIO](https://github.com/NVIDIA/jetson-gpio).
