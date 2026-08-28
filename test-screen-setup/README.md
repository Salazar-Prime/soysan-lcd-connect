# Screen setup and tests

Hardware wiring and SPI details are in
[`CONNECTION_GUIDE.md`](CONNECTION_GUIDE.md).

Install the Python dependency:

```bash
python3 -m pip install --user -r requirements.txt
```

Check the setup:

```bash
./verify_setup.sh
```

Run the color test:

```bash
./run_lcd_test.sh
./run_lcd_test.sh --cycles 5
```
