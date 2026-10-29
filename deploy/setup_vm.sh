#!/usr/bin/env bash
# ЛР4: підготовка VM Ubuntu 24.04 і запуск сервісу задач.
# Запуск на VM із кореня клонованого репозиторію:
#   bash deploy/setup_vm.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=tmio-lab4

echo "[1/4] Системні пакети"
sudo apt-get update -q
sudo apt-get install -y -q python3-venv

echo "[2/4] Віртуальне середовище і залежності сервісу"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "[3/4] systemd-юніт $SERVICE"
sed -e "s|__USER__|$USER|g" -e "s|__APP_DIR__|$APP_DIR|g" \
    "$APP_DIR/deploy/$SERVICE.service" | sudo tee "/etc/systemd/system/$SERVICE.service" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE"

echo "[4/4] Перевірка"
for _ in $(seq 1 15); do
    curl -fsS http://127.0.0.1:8000/health && echo && break
    sleep 1
done
"$APP_DIR/.venv/bin/python" --version
systemctl --no-pager status "$SERVICE" | head -n 5
