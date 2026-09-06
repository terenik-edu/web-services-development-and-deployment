"""
bench_stage1.py - STAGE 1: Cluster / Grid Computing model (Direct Execution).

The algorithm is executed as a direct computing function
directly in the system environment: no network wrappers, no container.

The time obtained here is the NET COMPUTATION TIME (T_compute),
the baseline against which the overhead is measured in Stages 2 and 3.
"""

import time
import platform
import sys
from typing import Tuple, Dict, List

from core import generate_array, process_array
from metrics import (
    DATA_SCALES,
    RUNS,
    WARMUP,
    summarize,
    save_raw,
    save_summary,
    print_table,
)

STAGE = "stage1"
line_length = 104


def print_environment() -> None:
    """Виводить параметри середовища — для протоколу експерименту."""
    print("-" * line_length)
    print("СЕРЕДОВИЩЕ ВИКОНАННЯ ЕКСПЕРИМЕНТУ")
    print("-" * line_length)
    print(f"Операційна система : {platform.system()} {platform.release()}")
    print(f"Архітектура        : {platform.machine()}")
    print(f"Процесор           : {platform.processor() or 'н/д'}")
    print(f"Python             : {platform.python_version()}")
    print(f"Запусків на сценарій: {RUNS} (+ {WARMUP} прогрівальних)")
    print("-" * line_length)


def run_scale(scale_name: str, size: int) -> Tuple[Dict, List[float]]:
    """
    Проводить серію вимірювань для одного масштабу даних.

    :param scale_name: умовна назва масштабу (small / medium / large)
    :param size: кількість елементів масиву
    :return: словник зведених метрик
    """
    data = generate_array(size)

    # Прогрів: перші запуски спотворені кешуванням та розігрівом інтерпретатора
    for _ in range(WARMUP):
        process_array(data)

    latencies = []
    for _ in range(RUNS):
        start = time.perf_counter_ns()
        process_array(data)
        elapsed_ns = time.perf_counter_ns() - start
        latencies.append(elapsed_ns / 1_000_000.0)  # наносекунди -> мілісекунди

    stats = summarize(latencies)
    stats.update({
        "stage": STAGE,
        "scale": scale_name,
        "size": size
    })
    return stats, latencies


def main() -> None:
    print()
    print("#" * line_length)
    print("ЕТАП 1. МОДЕЛЬ «CLUSTER / GRID COMPUTING» — ПРЯМЕ ВИКОНАННЯ (DIRECT EXECUTION)")
    print("#" * line_length)
    print_environment()

    summary_rows = []
    raw_rows = []

    for scale_name, size in DATA_SCALES.items():
        print(f"[+] Сценарій '{scale_name}' — масив на {size} елементів... ", end="", flush=True)
        stats, latencies = run_scale(scale_name, size)
        print("готово")
        summary_rows.append(stats)
        for i, ms in enumerate(latencies, start=1):
            raw_rows.append({
                "stage": STAGE,
                "scale": scale_name,
                "size": size,
                "run": i,
                "latency_ms": round(ms, 6)
            })

    print_table("ЕТАП 1 — ЗВЕДЕНІ РЕЗУЛЬТАТИ (базова лінія T_compute)", summary_rows)

    p1 = save_raw(STAGE, raw_rows)
    p2 = save_summary(STAGE, summary_rows)
    print(f"Сирі вимірювання : {p1}")
    print(f"Зведені метрики  : {p2}")


if __name__ == "__main__":
    sys.exit(main())
