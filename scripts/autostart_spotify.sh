#!/usr/bin/env bash
set -euo pipefail

trap 'rc=$?; echo ""; echo "Fel: scriptet avslutas med kod $rc"; exit $rc' ERR INT TERM

if [ "$EUID" -ne 0 ]; then
  echo "Det här skriptet måste köras som root. Kör med sudo." >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF_PATH="/etc/raspotify/conf"

echo "[autostart] Säkrar att Raspotify finns, konfigureras och körs (NOVA)..."

# install if missing
if ! command -v librespot >/dev/null 2>&1 && ! systemctl list-unit-files | grep -q raspotify; then
  echo "Raspotify verkar saknas — installerar via officiellt script..."
  curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
fi

# ensure config file exists
mkdir -p /etc/raspotify
touch "$CONF_PATH"

# helper
set_config_var() {
  local file="$1"; local key="$2"; local value="$3"
  if grep -qE "^[#[:space:]]*${key}=" "$file"; then
    sed -r -i "s~^[#[:space:]]*${key}=.*~${key}=${value}~" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

set_config_var "$CONF_PATH" "DEVICE_NAME" "\"NOVA\""
set_config_var "$CONF_PATH" "BITRATE" "320"

echo "Konfig uppdaterad: $CONF_PATH"

if command -v systemctl >/dev/null 2>&1; then
  echo "Aktiverar raspotify service vid boot..."
  systemctl enable raspotify || true
  echo "Startar/omstartar raspotify..."
  systemctl restart raspotify || true
  # Check active
  if systemctl is-active --quiet raspotify; then
    echo "Raspotify är aktiv."
  else
    echo "Varning: raspotify är inte aktiv efter restart." >&2
  fi
else
  echo "systemctl ej tillgängligt. Kontrollera manuellt." >&2
fi

echo "[autostart] klart."

exit 0
