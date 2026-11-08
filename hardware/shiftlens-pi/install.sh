#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo ./install.sh" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_USER="${SUDO_USER:-pi}"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Pi user '$SERVICE_USER' does not exist. Run with sudo from your Pi user's shell." >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-opencv python3-venv
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" /opt/shiftlens-pi
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 "$SOURCE_DIR/capture_agent.py" /opt/shiftlens-pi/capture_agent.py
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 "$SOURCE_DIR/requirements.txt" /opt/shiftlens-pi/requirements.txt
python3 -m venv --system-site-packages /opt/shiftlens-pi/.venv
/opt/shiftlens-pi/.venv/bin/pip install --upgrade pip
/opt/shiftlens-pi/.venv/bin/pip install -r /opt/shiftlens-pi/requirements.txt
install -d -m 0750 /etc/shiftlens
if [[ ! -f /etc/shiftlens/shiftlens-pi.env ]]; then
  install -m 0600 "$SOURCE_DIR/shiftlens-pi.env.example" /etc/shiftlens/shiftlens-pi.env
fi
sed "s/^User=.*/User=$SERVICE_USER/" "$SOURCE_DIR/shiftlens-pi.service" >/etc/systemd/system/shiftlens-pi.service
chmod 0644 /etc/systemd/system/shiftlens-pi.service
systemctl daemon-reload

echo
echo "ShiftLens Pi software installed. Edit /etc/shiftlens/shiftlens-pi.env with the Mac API URL and shared token."
echo "Then enable with: sudo systemctl enable --now shiftlens-pi"
echo "Camera only; audio is disabled. The agent samples five frames in RAM and uploads them for a draft every configured interval."
