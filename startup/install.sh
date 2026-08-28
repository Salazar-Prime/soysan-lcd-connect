#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
service_template="${script_dir}/soysan-lcd.service.template"
service_target="/etc/systemd/system/soysan-lcd.service"

if [[ $EUID -eq 0 ]]; then
  run_user=${SUDO_USER:-}
  sudo_command=()
else
  run_user=$USER
  sudo_command=(sudo)
fi

if [[ -z "$run_user" || "$run_user" == "root" ]]; then
  printf 'Run this installer as the desktop user, not directly as root.\n' >&2
  exit 1
fi

run_group=$(id -gn "$run_user")
home_dir=$(getent passwd "$run_user" | cut -d: -f6)
rendered_service=$(mktemp)
trap 'rm "$rendered_service"' EXIT

sed \
  -e "s|@RUN_USER@|${run_user}|g" \
  -e "s|@RUN_GROUP@|${run_group}|g" \
  -e "s|@HOME_DIR@|${home_dir}|g" \
  -e "s|@PROJECT_DIR@|${project_dir}|g" \
  "$service_template" > "$rendered_service"

"${sudo_command[@]}" install -m 0644 "$rendered_service" "$service_target"
"${sudo_command[@]}" systemctl daemon-reload
"${sudo_command[@]}" systemctl enable --now soysan-lcd.service
"${sudo_command[@]}" systemctl --no-pager --full status soysan-lcd.service
