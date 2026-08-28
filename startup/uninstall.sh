#!/usr/bin/env bash
set -euo pipefail

service_target="/etc/systemd/system/soysan-lcd.service"

if [[ $EUID -eq 0 ]]; then
  sudo_command=()
else
  sudo_command=(sudo)
fi

"${sudo_command[@]}" systemctl disable --now soysan-lcd.service 2>/dev/null || true
if [[ -e "$service_target" ]]; then
  "${sudo_command[@]}" rm "$service_target"
fi
"${sudo_command[@]}" systemctl daemon-reload
"${sudo_command[@]}" systemctl reset-failed soysan-lcd.service 2>/dev/null || true
printf 'Soysan LCD boot service removed.\n'
