#!/usr/bin/env bash
# ЛР4: один рівень навантаження. Запускається НА VM з кореня репозиторію:
#   ./deploy/run_level.sh idle            – простій, без навантаження
#   ./deploy/run_level.sh rate50 50       – 50 запитів/с
#   ./deploy/run_level.sh max 0           – без обмеження інтенсивності
#
# Генератор працює на тій самій VM (127.0.0.1): з Mac через ~200 мс мережевої
# затримки до West US 2 послідовний клієнт не створює відчутного навантаження.
# Щоб відокремити сервіс від генератора, окрім vmstat (уся VM) знімається
# процесорний час самого процесу сервісу.
#
# 1. Перезапуск сервісу – кожен рівень стартує з «чистого» процесу.
# 2. Генератор стартує у фоні; через 5 с (прогрів) починається вікно вимірювань.
# 3. У вікні DURATION секунд: vmstat щосекунди + CPU-час процесу сервісу
#    на початку і в кінці; наприкінці – поточна та пікова пам'ять процесу.
# Лог: results/lab4_vmstat_<рівень>.log, параметри рівня: results/lab4_load_<рівень>_summary.csv
set -euo pipefail

LABEL="${1:?Вкажіть назву рівня: idle | rate20 | ... | max}"
RATE="${2:-}"
DURATION="${DURATION:-180}"
SCALE="${SCALE:-medium}"
PYTHON="${PYTHON:-.venv/bin/python}"
SERVICE=tmio-lab4
LOG="results/lab4_vmstat_${LABEL}.log"
mkdir -p results

cpu_ticks() {
    # utime + stime процесу (поля 14 і 15 /proc/PID/stat), у тактах CLK_TCK
    awk '{print $14 + $15}' "/proc/$1/stat"
}

echo "[+] Перезапуск сервісу"
sudo systemctl restart "$SERVICE"
sleep 5
PID=$(systemctl show -p MainPID --value "$SERVICE")

if [ "$LABEL" != "idle" ]; then
    : "${RATE:?Для рівня навантаження вкажіть інтенсивність (0 – без обмеження)}"
    "$PYTHON" bench_load.py --url http://127.0.0.1:8000 --label "$LABEL" --rate "$RATE" \
        --scale "$SCALE" --duration $((DURATION + 15)) &
    BENCH_PID=$!
    sleep 5
fi

echo "[+] Вікно вимірювань $DURATION с, початок $(date -u +%H:%M:%S) UTC"
{
    grep MemTotal /proc/meminfo
    echo "CLK_TCK $(getconf CLK_TCK)"
    echo "SERVICE_CPU_BEFORE $(cpu_ticks "$PID")"
    vmstat -t -n -S M 1 "$DURATION"
    echo "SERVICE_CPU_AFTER $(cpu_ticks "$PID")"
    grep -E '^(VmRSS|VmHWM)' "/proc/$PID/status"
} > "$LOG"

if [ "$LABEL" != "idle" ]; then wait "$BENCH_PID"; fi
echo "[+] Лог ресурсів: $LOG"
