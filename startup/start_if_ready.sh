#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)

model=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)
if [[ "$model" != *"Jetson Xavier NX"* ]]; then
  printf 'LCD startup skipped: expected a Jetson Xavier NX, found %s\n' "${model:-unknown}" >&2
  exit 1
fi

if [[ ! -e /dev/spidev0.0 ]]; then
  printf 'LCD startup waiting: /dev/spidev0.0 is unavailable.\n' >&2
  exit 1
fi

if [[ ! -f "${project_dir}/main.py" ]]; then
  printf 'LCD startup failed: %s/main.py is missing.\n' "$project_dir" >&2
  exit 1
fi

printf 'LCD SPI endpoint ready; starting Soysan status display.\n'
exec /usr/bin/python3 "${project_dir}/main.py" \
  --interval "${LCD_REFRESH_INTERVAL:-1}" \
  --status-interval "${LCD_STATUS_INTERVAL:-5}"
