"""
bench_load.py - LAB 4 load generator for service_tasks.py deployed on an Azure VM.

One client sends POST /tasks sequentially over one keep-alive connection
for a fixed time. A load level is set by the target intensity (--rate,
requests per second; 0 - as fast as possible). CPU and RAM are recorded
separately by deploy/run_level.sh (vmstat + CPU time of the service process);
this script records the parameters of the level: number of requests, actual
RPS, latency and the share of time the service handler was busy.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from bench_tasks import HEADERS, REQUEST_TIMEOUT_S, wait_for_service
from core import generate_array
from metrics import DATA_SCALES_LAB2, percentile, save_summary

LINE_LENGTH = 72
# Кілька запитів перед відліком: встановлення з'єднання і «прогрів» інтерпретатора
WARMUP_REQUESTS = 5


def utc_now() -> str:
    """Поточний час UTC – для зіставлення з vmstat і графіками Azure Monitor."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def run_load(session: requests.Session, url: str, body: str, duration_s: float, rate: float) -> Dict[str, Any]:
    """
    Надсилає POST /tasks один за одним протягом duration_s секунд
    із заданою інтенсивністю.

    :param session: сесія з постійним з'єднанням
    :param url: базова адреса сервісу
    :param body: заздалегідь серіалізоване тіло запиту
    :param duration_s: тривалість рівня навантаження, с
    :param rate: цільова інтенсивність, запитів/с; 0 – без обмеження
    :return: сирі показники рівня
    """
    endpoint = f"{url}/tasks"
    latencies_ms: List[float] = []
    server_total_ms: List[float] = []
    server_compute_ms: List[float] = []
    errors = 0

    interval = 1.0 / rate if rate > 0 else 0.0
    started = time.perf_counter()
    deadline = started + duration_s
    next_send = started
    while time.perf_counter() < deadline:
        if interval:
            # Рівномірний темп: чекаємо на наступний «слот»; якщо сервіс не встигає,
            # не надсилаємо пачку навздогін, а продовжуємо від поточного моменту
            pause = next_send - time.perf_counter()
            if pause > 0:
                time.sleep(pause)
            next_send = max(next_send + interval, time.perf_counter())
        t0 = time.perf_counter_ns()
        try:
            response = session.post(endpoint, data=body, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException:
            errors += 1
            continue
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        if response.status_code != 201:
            errors += 1
            continue
        payload = response.json()
        latencies_ms.append(elapsed_ms)
        server_total_ms.append(payload["server_total_ms"])
        server_compute_ms.append(payload["server_compute_ms"])

    return {
        "elapsed_s": time.perf_counter() - started,
        "latencies_ms": latencies_ms,
        "server_total_ms": server_total_ms,
        "server_compute_ms": server_compute_ms,
        "errors": errors,
    }


def summarize_level(label: str, rate: float, scale: str, size: int, body: str, raw: Dict[str, Any],
                    started_utc: str, finished_utc: str) -> Dict[str, Any]:
    """Зводить рівень навантаження до параметрів для звіту."""
    lat = raw["latencies_ms"]
    n = len(lat)
    if n == 0:
        sys.exit("[!] Жоден запит не виконано успішно")
    elapsed = raw["elapsed_s"]
    return {
        "label": label,
        "rate_target": rate,
        "scale": scale,
        "size": size,
        "body_kb": round(len(body.encode("utf-8")) / 1024.0, 1),
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_s": round(elapsed, 1),
        "requests": n,
        "errors": raw["errors"],
        "rps": round(n / elapsed, 2),
        "mean_ms": round(sum(lat) / n, 2),
        "median_ms": round(percentile(lat, 50), 2),
        "p95_ms": round(percentile(lat, 95), 2),
        "server_compute_ms": round(sum(raw["server_compute_ms"]) / n, 3),
        "server_total_ms": round(sum(raw["server_total_ms"]) / n, 3),
        # Частка часу, коли обробник сервісу був зайнятий: оцінка «знизу» для CPU
        "handler_busy_pct": round(sum(raw["server_total_ms"]) / (elapsed * 1000.0) * 100.0, 1),
    }


def print_level(s: Dict[str, Any]) -> None:
    """Виводить параметри рівня (для скріншота у звіт)."""
    rows = [
        ("Цільова інтенсивність", f"{s['rate_target']:g} запитів/с" if s["rate_target"] else "без обмеження"),
        ("Вхідні дані", f"{s['scale']} – {s['size']} елем., тіло {s['body_kb']} КБ"),
        ("Інтервал, UTC", f"{s['started_utc']} – {s['finished_utc']} ({s['duration_s']} с)"),
        ("Запитів / помилок", f"{s['requests']} / {s['errors']}"),
        ("Фактична інтенсивність", f"{s['rps']} запитів/с"),
        ("Затримка: сер. / мед. / p95", f"{s['mean_ms']} / {s['median_ms']} / {s['p95_ms']} мс"),
        ("Обчислення на сервері (сер.)", f"{s['server_compute_ms']} мс"),
        ("Обробник на сервері (сер.)", f"{s['server_total_ms']} мс"),
        ("Зайнятість обробника", f"{s['handler_busy_pct']} % часу"),
    ]
    print("=" * LINE_LENGTH)
    print(f"ЛР4. РІВЕНЬ НАВАНТАЖЕННЯ '{s['label']}'")
    print("=" * LINE_LENGTH)
    for name, value in rows:
        print(f"{name:<30}: {value}")
    print("=" * LINE_LENGTH)


def parse_args() -> argparse.Namespace:
    """Розбирає аргументи командного рядка."""
    parser = argparse.ArgumentParser(description="Генератор навантаження лабораторної роботи 4")
    parser.add_argument("--url", required=True, help="базова адреса сервісу, напр. http://<IP VM>:8000")
    parser.add_argument("--label", required=True, help="назва рівня для файлу результатів, напр. rate50")
    parser.add_argument("--rate", type=float, default=0.0,
                        help="цільова інтенсивність, запитів/с (0 – без обмеження)")
    parser.add_argument("--scale", choices=list(DATA_SCALES_LAB2), default="medium",
                        help="масштаб масиву з ЛР2 (за замовчуванням medium – 10 000 елем.)")
    parser.add_argument("--duration", type=float, default=180.0, help="тривалість рівня, с (за замовчуванням 180)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = args.url.rstrip("/")
    size = DATA_SCALES_LAB2[args.scale]
    body = json.dumps({"data": generate_array(size)})

    with requests.Session() as session:
        wait_for_service(session, url)
        for _ in range(WARMUP_REQUESTS):
            session.post(f"{url}/tasks", data=body, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
        started_utc = utc_now()
        print(f"[+] Рівень '{args.label}': {args.rate:g} запитів/с (0 – без обмеження), {size} елем., "
              f"{args.duration:.0f} с, початок {started_utc} UTC...", flush=True)
        raw = run_load(session, url, body, args.duration, args.rate)
        finished_utc = utc_now()

    summary = summarize_level(args.label, args.rate, args.scale, size, body, raw, started_utc, finished_utc)
    print_level(summary)
    path = save_summary(f"lab4_load_{args.label}", [summary])
    print(f"Параметри рівня: {path}")


if __name__ == "__main__":
    sys.exit(main())
