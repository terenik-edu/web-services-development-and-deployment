#!/usr/bin/env bash
#
# run_stage3.sh - повний цикл Етапу 3: збірка образу, запуск контейнера
# з обмеженням ресурсів, очікування готовності, прогін бенчмарку зі збором
# docker stats і зупинка контейнера.
#
# Один скрипт замість послідовності ручних команд робить прогін відтворюваним:
# параметри експерименту (ліміти ресурсів, порт, кількість воркерів) задані
# в одному місці й не змінюються від запуску до запуску.

set -euo pipefail

cd "$(dirname "$0")"

# --- Параметри експерименту (фіксуються у звіті) ---
IMAGE="lab1-service"
CONTAINER="lab1-service"
HOST_PORT=8001          # навмисно не 8000: щоб сервіс Етапу 2 міг працювати одночасно
CPUS="1.0"              # імітація хмарного екземпляра з одним ядром
MEMORY="512m"           # ліміт оперативної пам'яті контейнера
STATS_INTERVAL=1        # пауза між заміри docker stats, секунди
STATS_FILE="results/stage3_docker_stats.csv"
LOAD_SECONDS=20         # фаза навантаження після замірів – під неї знімається docker stats

# Інтерпретатор із локального .venv – там встановлено requests
PYTHON=".venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"

# Контейнер видаляється за будь-якого завершення скрипта, зокрема аварійного:
# інакше наступний запуск упав би на зайнятому імені або порті
cleanup() {
    if [ -n "${STATS_PID:-}" ]; then
        kill "$STATS_PID" 2>/dev/null || true
    fi
    docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Збірка образу '$IMAGE'"
docker build -t "$IMAGE" .

echo "==> Запуск контейнера (--cpus=$CPUS --memory=$MEMORY, порт $HOST_PORT)"
docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
docker run --detach \
    --name "$CONTAINER" \
    --cpus="$CPUS" \
    --memory="$MEMORY" \
    --publish "$HOST_PORT:8000" \
    "$IMAGE"

echo "==> Очікування готовності сервісу (GET /health)"
for _ in $(seq 1 60); do
    if curl --silent --fail "http://127.0.0.1:$HOST_PORT/health" >/dev/null 2>&1; then
        echo "    сервіс відповідає"
        break
    fi
    sleep 0.5
done

docker ps --filter "name=$CONTAINER" \
    --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# --- Збір метрик ресурсів контейнера паралельно з прогоном ---
# docker stats знімає показники з погляду ХОСТА: відсоток CPU і використання
# пам'яті відносно ліміту. Це доповнює GET /stats, який бачить лише сам процес
# усередині контейнера і нічого не знає про накладені обмеження.
#
# Сама серія вимірювань триває близько секунди – коротше за один виклик
# docker stats. Тому бенчмарк після збереження результатів створює окрему
# фазу навантаження на LOAD_SECONDS секунд, і саме під неї збирається
# статистика контейнера.
mkdir -p results
echo "timestamp,cpu_perc,mem_usage,mem_perc" > "$STATS_FILE"
(
    while true; do
        if line=$(docker stats "$CONTAINER" --no-stream \
                    --format "{{.CPUPerc}};{{.MemUsage}};{{.MemPerc}}" 2>/dev/null); then
            echo "$(date +%H:%M:%S),${line//;/,}" >> "$STATS_FILE"
        fi
        sleep "$STATS_INTERVAL"
    done
) &
STATS_PID=$!

echo "==> Прогін бенчмарку Етапу 3"
"$PYTHON" bench_client.py \
    --stage stage3 \
    --url "http://127.0.0.1:$HOST_PORT" \
    --load-seconds "$LOAD_SECONDS"

kill "$STATS_PID" 2>/dev/null || true
wait "$STATS_PID" 2>/dev/null || true
STATS_PID=""

echo "==> Використання ресурсів контейнера під навантаженням ($STATS_FILE)"
awk -F',' 'NR > 1 {
        cpu = $2; gsub("%", "", cpu);
        if (cpu + 0 > max_cpu) max_cpu = cpu + 0;
        sum_cpu += cpu + 0;
        printf("    %s   CPU %-8s пам’ять %-22s (%s від ліміту)\n", $1, $2, $3, $4);
        n++
    }
    END {
        if (n) {
            print  "    ---------------------------------------------------------------";
            printf("    Замірів: %d   Пік CPU: %.2f%%   Середнє CPU: %.2f%% (100%% = одне ядро)\n",
                   n, max_cpu, sum_cpu / n);
        } else {
            print "    (замірів не зібрано)";
        }
    }' "$STATS_FILE"

echo "==> Зупинка контейнера"
docker rm --force "$CONTAINER" >/dev/null
trap - EXIT
echo "==> Готово"
