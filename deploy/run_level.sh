#!/usr/bin/env bash
# ЛР4: один рівень навантаження. Запускається на Mac з кореня репозиторію:
#   VM_IP=<IP VM> ./deploy/run_level.sh idle|small|medium|large
#
# 1. Перезапускає сервіс на VM – кожен рівень стартує з «чистого» процесу,
#    тож пам'ять процесу не накопичується між рівнями.
# 2. Знімає на VM vmstat (CPU і RAM щосекунди) протягом DURATION секунд,
#    а наприкінці – поточну і пікову пам'ять процесу сервісу.
# 3. Паралельно (крім idle) запускає bench_load.py на DURATION + 15 с,
#    щоб навантаження покривало весь інтервал vmstat.
# Лог зберігається в results/lab4_vmstat_<рівень>.log.
set -euo pipefail

LEVEL="${1:?Вкажіть рівень: idle | small | medium | large}"
: "${VM_IP:?Вкажіть VM_IP=<публічна IP-адреса VM>}"
VM_USER="${VM_USER:-azureuser}"
DURATION="${DURATION:-180}"
PYTHON="${PYTHON:-.venv/bin/python}"
SERVICE=tmio-lab4

SSH_OPTS=(-o BatchMode=yes)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")
VM="$VM_USER@$VM_IP"
LOG="results/lab4_vmstat_${LEVEL}.log"
mkdir -p results

REMOTE='grep MemTotal /proc/meminfo; vmstat -t -n -S M 1 '"$DURATION"'; PID=$(systemctl show -p MainPID --value '"$SERVICE"'); grep -E "^(VmRSS|VmHWM)" /proc/$PID/status'

echo "[+] Перезапуск сервісу на VM"
ssh "${SSH_OPTS[@]}" "$VM" "sudo systemctl restart $SERVICE && sleep 5"

if [ "$LEVEL" = "idle" ]; then
    echo "[+] Простій: vmstat $DURATION с, початок $(date -u +%H:%M:%S) UTC..."
    ssh "${SSH_OPTS[@]}" "$VM" "$REMOTE" > "$LOG"
else
    ssh "${SSH_OPTS[@]}" "$VM" "$REMOTE" > "$LOG" &
    VMSTAT_PID=$!
    "$PYTHON" bench_load.py --url "http://$VM_IP:8000" --scale "$LEVEL" --duration $((DURATION + 15))
    wait "$VMSTAT_PID"
fi
echo "[+] Лог ресурсів VM: $LOG"
