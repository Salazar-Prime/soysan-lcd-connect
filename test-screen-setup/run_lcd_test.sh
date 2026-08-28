#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if ! grep -qw spidev /proc/modules; then
  sudo modprobe spidev
fi

python3 "${script_dir}/waveshare_2inch_lcd_test.py" "$@"
