#!/usr/bin/env bash
set -u

failures=0

pass() {
  printf 'PASS: %s\n' "$1"
}

fail() {
  printf 'FAIL: %s\n' "$1"
  failures=$((failures + 1))
}

model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)
printf 'Board: %s\n' "${model:-unknown}"

if [[ "$model" == *"Jetson Xavier NX Developer Kit"* ]]; then
  pass "Xavier NX Developer Kit detected"
else
  fail "expected the Xavier NX Developer Kit"
fi

if [[ -r /etc/nv_tegra_release ]]; then
  printf 'Jetson Linux: '
  head -n 1 /etc/nv_tegra_release
  pass "Jetson Linux release metadata found"
else
  fail "/etc/nv_tegra_release is unavailable"
fi

if grep -q '^DEFAULT JetsonIO' /boot/extlinux/extlinux.conf 2>/dev/null; then
  pass "JetsonIO is the default boot entry"
else
  fail "JetsonIO is not the default boot entry"
fi

if [[ -d /sys/bus/spi/devices/spi0.0 ]]; then
  pass "kernel SPI device spi0.0 exists"
else
  fail "kernel SPI device spi0.0 is missing"
fi

if grep -qw spidev /proc/modules; then
  pass "spidev kernel module is loaded"
else
  fail "spidev is not loaded; run: sudo modprobe spidev"
fi

if [[ -e /dev/spidev0.0 ]]; then
  pass "/dev/spidev0.0 exists"
  ls -l /dev/spidev0.0
else
  fail "/dev/spidev0.0 is missing"
fi

python3 - <<'PY'
modules = ("spidev", "Jetson.GPIO", "PIL")
failed = False
for name in modules:
    try:
        module = __import__(name)
        version = getattr(module, "__version__", "installed")
        print(f"PASS: Python module {name} ({version})")
    except Exception as error:
        failed = True
        print(f"FAIL: Python module {name}: {error}")
raise SystemExit(1 if failed else 0)
PY

if [[ $? -ne 0 ]]; then
  failures=$((failures + 1))
fi

if [[ $failures -eq 0 ]]; then
  printf 'READY: LCD software prerequisites are present.\n'
  exit 0
fi

printf 'NOT READY: %d check(s) failed. See README.md for remediation.\n' "$failures"
exit 1
