"""
bench_tasks.py - LAB 2 benchmark client for service_tasks.py.

The same file measures the service run locally and deployed to Azure App
Service: only the address (--url) and the label (--target) change.

For every request it records the request latency (client timer), the
algorithm latency (server_compute_ms from the response) and their difference -
the overhead, further split into deserialization, serialization and transport.
The client methodology repeats bench_client.py (LR1).
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Tuple

import requests

from core import generate_array
from metrics import (
    DATA_SCALES_LAB2,
    RUNS,
    WARMUP,
    summarize,
    resource_delta,
    save_raw,
    save_summary,
    print_table,
    print_overhead,
    print_resources,
)

LINE_LENGTH = 104
HEADERS = {"Content-Type": "application/json"}
DEFAULT_URL = "http://127.0.0.1:8000"
# Масив на 100 000 елементів (~1,9 МБ) через інтернет передається секундами
REQUEST_TIMEOUT_S = 120.0
# Холодний старт застосунку в хмарі може тривати до хвилини і більше
HEALTH_TIMEOUT_S = 120.0


def wait_for_service(session: requests.Session, url: str) -> None:
    """
    Очікує готовності сервісу через /health.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :raises SystemExit: якщо сервіс не відповів за HEALTH_TIMEOUT_S
    """
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if session.get(f"{url}/health", timeout=10.0).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1.0)
    sys.exit(f"[!] Сервіс за адресою {url} не відповідає {HEALTH_TIMEOUT_S:.0f} с.")


def prepare_body(size: int) -> Tuple[str, float]:
    """
    Серіалізує масив ОДИН РАЗ поза замірами, щоб кодування JSON на клієнті
    не потрапляло в request latency.

    :param size: кількість елементів масиву
    :return: тіло запиту та довідковий час його серіалізації, мс
    """
    data = generate_array(size)
    start = time.perf_counter_ns()
    body = json.dumps({"data": data})
    return body, (time.perf_counter_ns() - start) / 1_000_000.0


def print_environment(url: str, target: str, bodies: Dict[str, Tuple[str, float]]) -> None:
    """Виводить параметри прогону – для протоколу експерименту."""
    print("-" * LINE_LENGTH)
    print("ПАРАМЕТРИ ПРОГОНУ")
    print("-" * LINE_LENGTH)
    print(f"Середовище          : {target}")
    print(f"Адреса сервісу      : {url}")
    print(f"Запусків на сценарій: {RUNS} (+ {WARMUP} прогрівальних)")
    print(f"З'єднання           : одне постійне (keep-alive), requests.Session")
    print(f"Таймаут запиту      : {REQUEST_TIMEOUT_S:.0f} с")
    for scale_name, size in DATA_SCALES_LAB2.items():
        body_kb = len(bodies[scale_name][0].encode("utf-8")) / 1024.0
        print(f"Тіло '{scale_name}'".ljust(20) + f": {size} елем., {body_kb:.1f} КБ")
    print("-" * LINE_LENGTH)


def post_task(session: requests.Session, endpoint: str, body: str) -> requests.Response:
    """Надсилає POST /tasks; будь-який код, крім 201, зупиняє прогін."""
    response = session.post(endpoint, data=body, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    if response.status_code != 201:
        sys.exit(f"[!] POST /tasks повернув {response.status_code}: {response.text[:200]}")
    return response


def run_scale(
        session: requests.Session,
        url: str,
        target: str,
        scale_name: str,
        size: int,
        body: str,
        client_serialize_ms: float,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[int]]:
    """
    Проводить серію вимірювань для одного масштабу даних.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :param target: позначка середовища (local / azure)
    :param scale_name: назва масштабу (small / medium / large)
    :param size: кількість елементів масиву
    :param body: заздалегідь серіалізоване тіло запиту
    :param client_serialize_ms: довідковий час серіалізації тіла на клієнті
    :return: зведені метрики, результати окремих запитів, id усіх створених задач
    """
    endpoint = f"{url}/tasks"
    created_ids: List[int] = []

    for _ in range(WARMUP):
        response = post_task(session, endpoint, body)
        created_ids.append(response.json()["id"])

    # Перевірка коректності поза замірами: оброблено рівно стільки, скільки надіслано
    checked = response.json()
    if checked["result"]["count"] != size:
        sys.exit(f"[!] Сервіс обробив {checked['result']['count']} елементів замість {size}")

    res_before = session.get(f"{url}/stats", timeout=REQUEST_TIMEOUT_S).json()

    per_request: List[Dict[str, Any]] = []
    for run_index in range(1, RUNS + 1):
        start = time.perf_counter_ns()
        response = post_task(session, endpoint, body)
        elapsed_ns = time.perf_counter_ns() - start

        # Розбір відповіді – поза таймером
        payload = response.json()
        created_ids.append(payload["id"])
        latency_ms = elapsed_ns / 1_000_000.0
        per_request.append({
            "target": target,
            "scale": scale_name,
            "size": size,
            "run": run_index,
            "task_id": payload["id"],
            # Request latency
            "latency_ms": round(latency_ms, 6),
            # Algorithm latency
            "server_compute_ms": round(payload["server_compute_ms"], 6),
            "overhead_ms": round(latency_ms - payload["server_compute_ms"], 6),
            "server_deserialize_ms": round(payload["server_deserialize_ms"], 6),
            "server_serialize_ms": round(payload["server_serialize_ms"], 6),
            "server_total_ms": round(payload["server_total_ms"], 6),
            # Усе поза обробником: мережа, TLS, фронтенд платформи, HTTP, ASGI
            "transport_ms": round(latency_ms - payload["server_total_ms"], 6),
        })

    res_after = session.get(f"{url}/stats", timeout=REQUEST_TIMEOUT_S).json()

    stats = summarize([r["latency_ms"] for r in per_request])
    stats.update({
        "target": target,
        "scale": scale_name,
        "size": size,
        "server_compute_ms": round(_mean(per_request, "server_compute_ms"), 4),
        "overhead_ms": round(_mean(per_request, "overhead_ms"), 4),
        "server_deserialize_ms": round(_mean(per_request, "server_deserialize_ms"), 4),
        "server_serialize_ms": round(_mean(per_request, "server_serialize_ms"), 4),
        "server_total_ms": round(_mean(per_request, "server_total_ms"), 4),
        "transport_ms": round(_mean(per_request, "transport_ms"), 4),
        "request_bytes": payload["request_bytes"],
        "client_serialize_ms": round(client_serialize_ms, 4),
    })
    stats.update(resource_delta(res_before, res_after))
    return stats, per_request, created_ids


def cleanup_tasks(session: requests.Session, url: str, task_ids: List[int]) -> int:
    """
    Перевіряє GET /tasks і видаляє створені задачі (поза замірами).

    Перевіряє список і видалення API та звільняє пам'ять сервісу перед наступним масштабом.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :param task_ids: id задач, створених у серії (включно з прогрівальними)
    :return: кількість успішно видалених задач
    """
    history = session.get(f"{url}/tasks", timeout=REQUEST_TIMEOUT_S).json()
    missing = set(task_ids) - {t["id"] for t in history["tasks"]}
    if missing:
        sys.exit(f"[!] В історії GET /tasks немає {len(missing)} створених задач")

    deleted = 0
    for task_id in task_ids:
        response = session.delete(f"{url}/tasks/{task_id}", timeout=REQUEST_TIMEOUT_S)
        if response.status_code == 204:
            deleted += 1
    return deleted


def _mean(rows: List[Dict[str, Any]], key: str) -> float:
    """Середнє значення поля по всіх запитах серії."""
    return sum(r[key] for r in rows) / len(rows)


def parse_args() -> argparse.Namespace:
    """Розбирає аргументи командного рядка."""
    parser = argparse.ArgumentParser(description="Бенчмарк сервісу задач лабораторної роботи 2")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"базова адреса сервісу (за замовчуванням {DEFAULT_URL}; для azure – обов'язково)",
    )
    parser.add_argument(
        "--target",
        choices=["local", "azure"],
        default="local",
        help="позначка середовища для файлів результатів і заголовків",
    )
    args = parser.parse_args()
    # Захист від прогону «azure» проти локального сервісу і змішування результатів
    if args.target == "azure" and args.url == DEFAULT_URL:
        parser.error("для --target azure вкажіть --url https://<app>.azurewebsites.net")
    return args


def main() -> None:
    args = parse_args()
    url = args.url.rstrip("/")
    target = args.target

    if target == "local":
        title = "ЛР2. СЕРВІС ЗАДАЧ – ЛОКАЛЬНИЙ ЗАПУСК"
    else:
        title = "ЛР2. СЕРВІС ЗАДАЧ – AZURE APP SERVICE"
    label = target.upper()

    bodies = {name: prepare_body(size) for name, size in DATA_SCALES_LAB2.items()}

    print()
    print("#" * LINE_LENGTH)
    print(title)
    print("#" * LINE_LENGTH)
    print_environment(url, target, bodies)

    summary_rows: List[Dict[str, Any]] = []
    raw_rows: List[Dict[str, Any]] = []

    # Одне постійне з'єднання: TCP і TLS встановлюються один раз і в заміри не потрапляють
    with requests.Session() as session:
        wait_for_service(session, url)
        for scale_name, size in DATA_SCALES_LAB2.items():
            print(f"[+] Сценарій '{scale_name}' – масив на {size} елементів... ",
                  end="", flush=True)
            body, client_serialize_ms = bodies[scale_name]
            stats, per_request, created_ids = run_scale(
                session, url, target, scale_name, size, body, client_serialize_ms)
            deleted = cleanup_tasks(session, url, created_ids)
            print(f"готово (видалено задач: {deleted} з {len(created_ids)})")
            summary_rows.append(stats)
            raw_rows.extend(per_request)

    print_table(f"ЛР2 [{label}] – REQUEST LATENCY (повний час запиту з боку клієнта)", summary_rows)
    print_overhead(f"ЛР2 [{label}] – OVERHEAD = REQUEST LATENCY − ALGORITHM LATENCY", summary_rows)
    print_resources(f"ЛР2 [{label}] – РЕСУРСИ ПРОЦЕСУ СЕРВІСУ (на серію з {RUNS} запитів)", summary_rows)

    p1 = save_raw(f"lab2_{target}", raw_rows)
    p2 = save_summary(f"lab2_{target}", summary_rows)
    print(f"Сирі вимірювання : {p1}")
    print(f"Зведені метрики  : {p2}")


if __name__ == "__main__":
    sys.exit(main())