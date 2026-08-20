#!/usr/bin/env bash
set -euo pipefail

trap 'rc=$?; echo ""; echo "Setup failed with exit code $rc"; exit $rc' ERR INT TERM

if [ "${EUID}" -ne 0 ]; then
  echo "This script must be run as root. Use: sudo ./scripts/setup_spotify_device.sh"
  exit 1
fi

conf_path="/etc/raspotify/conf"
service_name="raspotify"

echo "Preparing Spotify Connect receiver for NOVA..."

if ! command -v curl >/dev/null 2>&1; then
  echo "Installing curl..."
  apt-get update
  apt-get install -y curl ca-certificates
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required on Raspberry Pi OS."
  exit 2
fi

if ! systemctl list-unit-files | grep -q "^${service_name}\.service" && ! command -v librespot >/dev/null 2>&1; then
  echo "Installing Raspotify..."
  curl -fsSL https://dtcooper.github.io/raspotify/install.sh | sh
fi

mkdir -p "$(dirname "$conf_path")"
touch "$conf_path"

backup_path="${conf_path}.bak.$(date +%s)"
cp -a "$conf_path" "$backup_path"
echo "Backed up existing config to $backup_path"

set_config_var() {
  local file="$1"
  local key="$2"
  local value="$3"

  if grep -qE "^[#[:space:]]*${key}=" "$file"; then
    sed -i -E "s~^[#[:space:]]*${key}=.*~${key}=${value}~" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

set_config_var "$conf_path" "DEVICE_NAME" '"NOVA"'
set_config_var "$conf_path" "BITRATE" "320"
set_config_var "$conf_path" "BACKEND" '"alsa"'
set_config_var "$conf_path" "DEVICE" '"default"'
set_config_var "$conf_path" "OPTIONS" '"--backend alsa --device default"'

echo "Configured device name NOVA and ALSA default output."

systemctl daemon-reload
systemctl enable "$service_name"
systemctl restart "$service_name"

if systemctl is-active --quiet "$service_name"; then
  echo "Raspotify is running and will start on boot."
else
  echo "Raspotify is not active after restart. Recent logs:"
  journalctl -u "$service_name" -n 50 --no-pager || true
  exit 3
fi

echo "Done. The Pi should appear in Spotify as NOVA."
