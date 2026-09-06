"""
bench_client.py - benchmark client shared by STAGE 2 and STAGE 3.

The very same file measures the local web service and the containerized one:
only the service address changes (--url). Any difference between the client
code of the two stages would make their results incomparable, so the script
is parameterized instead of being copied.

Measured value: T_total - the full round trip seen by the client. The service
reports its own internal timings in the response body, and the difference
between the two gives the transport component of the overhead.
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Tuple

import requests

from core import generate_array
from metrics import (
    DATA_SCALES,
    RUNS,
    WARMUP,
    summarize,
    resource_delta,
    save_raw,
    save_summary,
    print_table,
    print_resources,
    print_breakdown,
)

LINE_LENGTH = 104
HEADERS = {"Content-Type": "application/json"}
HEALTH_TIMEOUT_S = 30.0


def wait_for_service(session: requests.Session, url: str) -> None:
    """
    Очікує готовності сервісу через кінцеву точку /health.

    Потрібно насамперед Етапу 3: контейнер стартує не миттєво, і перші
    запити впали б з помилкою з'єднання, а не через архітектуру.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :raises SystemExit: якщо сервіс не відповів за відведений час
    """
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            response = session.get(f"{url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except requests.RequestException:
            time.sleep(0.2)
    sys.exit(f"[!] Сервіс за адресою {url} не відповідає. Спершу запустіть його.")


def print_environment(url: str, stage: str) -> None:
    """Виводить параметри прогону – для протоколу експерименту."""
    print("-" * LINE_LENGTH)
    print("ПАРАМЕТРИ ПРОГОНУ")
    print("-" * LINE_LENGTH)
    print(f"Етап                : {stage}")
    print(f"Адреса сервісу      : {url}")
    print(f"Запусків на сценарій: {RUNS} (+ {WARMUP} прогрівальних)")
    print(f"З'єднання           : одне постійне (keep-alive), requests.Session")
    print("-" * LINE_LENGTH)


def run_scale(
        session: requests.Session,
        url: str,
        stage: str,
        scale_name: str,
        size: int
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:

    """
    Проводить серію вимірювань для одного масштабу даних.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :param stage: позначка етапу (stage2 / stage3)
    :param scale_name: умовна назва масштабу (small / medium / large)
    :param size: кількість елементів масиву
    :return: словник зведених метрик та список результатів окремих запитів
    """
    endpoint = f"{url}/compute"
    data = generate_array(size)

    # Тіло запиту серіалізується ОДИН РАЗ поза вимірюваною ділянкою.
    # Інакше в T_total потрапляв би час кодування JSON на клієнті, і різниця
    # T_total - T_server_total перестала б означати транспорт. Час цієї
    # одноразової серіалізації фіксується окремо як довідковий показник.
    t_ser_start = time.perf_counter_ns()
    body = json.dumps({"data": data})
    client_serialize_ms = (time.perf_counter_ns() - t_ser_start) / 1_000_000.0

    # Прогрів: перші запити спотворені стартом сервера та розігрівом стека
    for _ in range(WARMUP):
        response = session.post(endpoint, data=body, headers=HEADERS)
        response.raise_for_status()

    # Мінімальна перевірка коректності замість контрольної суми: сервіс мав
    # обробити рівно стільки елементів, скільки надіслано. Ловить обрізання
    # тіла запиту та неявні перетворення типів. Виконується поза замірами.
    checked = response.json()
    if checked["result"]["count"] != size:
        sys.exit(f"[!] Сервіс обробив {checked['result']['count']} елементів замість {size}")

    # Ресурси знімаються з процесу СЕРВЕРА до та після серії
    res_before = session.get(f"{url}/stats").json()

    per_request: List[Dict[str, Any]] = []
    for run_index in range(1, RUNS + 1):
        start = time.perf_counter_ns()
        response = session.post(endpoint, data=body, headers=HEADERS)
        elapsed_ns = time.perf_counter_ns() - start

        # Розбір відповіді – поза таймером, він не є частиною T_total
        payload = response.json()
        total_ms = elapsed_ns / 1_000_000.0
        per_request.append({
            "stage": stage,
            "scale": scale_name,
            "size": size,
            "run": run_index,
            # Повний час з боку клієнта
            "latency_ms": round(total_ms, 6),
            # Час усередині обробника сервісу
            "server_total_ms": round(payload["server_total_ms"], 6),
            "server_deserialize_ms": round(payload["server_deserialize_ms"], 6),
            "server_compute_ms": round(payload["server_compute_ms"], 6),
            "server_serialize_ms": round(payload["server_serialize_ms"], 6),
            # Усе, що поза обробником: мережевий стек, HTTP, ASGI, маршрутизація
            "transport_ms": round(total_ms - payload["server_total_ms"], 6),
        })

    res_after = session.get(f"{url}/stats").json()

    stats = summarize([r["latency_ms"] for r in per_request])
    stats.update({
        "stage": stage,
        "scale": scale_name,
        "size": size,
        # Середні значення складових розкладу накладних витрат
        "server_total_ms": round(_mean(per_request, "server_total_ms"), 4),
        "server_deserialize_ms": round(_mean(per_request, "server_deserialize_ms"), 4),
        "server_compute_ms": round(_mean(per_request, "server_compute_ms"), 4),
        "server_serialize_ms": round(_mean(per_request, "server_serialize_ms"), 4),
        "transport_ms": round(_mean(per_request, "transport_ms"), 4),
        # Реальний розмір тіла запиту в байтах (за даними сервера)
        "request_bytes": payload["request_bytes"],
        # Довідково: одноразова серіалізація масиву на клієнті
        "client_serialize_ms": round(client_serialize_ms, 4),
    })
    stats.update(resource_delta(res_before, res_after))
    return stats, per_request


def _mean(rows: List[Dict[str, Any]], key: str) -> float:
    """
    Обчислює середнє значення одного поля по всіх запитах серії.

    :param rows: результати окремих запитів
    :param key: назва поля
    :return: середнє арифметичне
    """
    return sum(r[key] for r in rows) / len(rows)


def parse_args() -> argparse.Namespace:
    """Розбирає аргументи командного рядка."""
    parser = argparse.ArgumentParser(description="Бенчмарк веб-сервісу для Етапів 2 і 3 лабораторної роботи 1")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="базова адреса сервісу (за замовчуванням http://127.0.0.1:8000)"
    )
    parser.add_argument(
        "--stage",
        choices=["stage2", "stage3"],
        default="stage2",
        help="позначка етапу для файлів результатів"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = args.url.rstrip("/")
    stage = args.stage

    if stage == "stage2":
        title = "ЕТАП 2. МОДЕЛЬ «SERVICE-ORIENTED COMPUTING» – ЛОКАЛЬНИЙ ВЕБ-СЕРВІС"
    else:
        title = "ЕТАП 3. МОДЕЛЬ «CLOUD COMPUTING» – ВЕБ-СЕРВІС У КОНТЕЙНЕРІ DOCKER"

    print()
    print("#" * LINE_LENGTH)
    print(title)
    print("#" * LINE_LENGTH)
    print_environment(url, stage)

    summary_rows: List[Dict[str, Any]] = []
    raw_rows: List[Dict[str, Any]] = []

    # Одне постійне з'єднання на весь прогін: інакше в кожен замір
    # потрапило б встановлення TCP-з'єднання, і результат був би про мережу,
    # а не про архітектуру сервісу
    with requests.Session() as session:
        wait_for_service(session, url)
        for scale_name, size in DATA_SCALES.items():
            print(f"[+] Сценарій '{scale_name}' – масив на {size} елементів... ",
                  end="", flush=True)
            stats, per_request = run_scale(session, url, stage, scale_name, size)
            print("готово")
            summary_rows.append(stats)
            raw_rows.extend(per_request)

    stage_number = "2" if stage == "stage2" else "3"
    print_table(f"ЕТАП {stage_number} – ЗВЕДЕНІ РЕЗУЛЬТАТИ (T_total з боку клієнта)", summary_rows)
    print_breakdown(f"ЕТАП {stage_number} – РОЗКЛАД ПОВНОГО ЧАСУ ЗАПИТУ НА СКЛАДОВІ", summary_rows)
    print_resources(f"ЕТАП {stage_number} – ВИКОРИСТАННЯ РЕСУРСІВ ПРОЦЕСОМ СЕРВІСУ (на серію з {RUNS} запитів)", summary_rows)

    p1 = save_raw(stage, raw_rows)
    p2 = save_summary(stage, summary_rows)
    print(f"Сирі вимірювання : {p1}")
    print(f"Зведені метрики  : {p2}")


if __name__ == "__main__":
    sys.exit(main())
