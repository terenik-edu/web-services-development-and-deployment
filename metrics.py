"""
metrics.py - is a common module for processing and storing measurement results.

It is used by all three stages of the experiment so that metrics
are calculated using a single methodology and are comparable with each other.
"""

import csv
import math
import os
from typing import List, Dict, Any

# Масштаби даних згідно з пунктом 3 завдання
DATA_SCALES = {
    "small": 100,      # ~1 KB   (KB — кілобайт)
    "medium": 1_000,   # ~10 KB
    "large": 10_000,   # ~100 KB
}

RUNS = 100      # кількість вимірюваних запитів на сценарій
WARMUP = 10     # кількість «прогрівальних» запусків (у статистику не входять)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def percentile(values: List[float], p: float) -> float:
    """
    Обчислює перцентиль методом лінійної інтерполяції.

    p95 (95-й перцентиль) — значення, гірше за яке лише 5 % запитів.
    Саме воно показує реальні «хвости» затримок, які втрачає середнє.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return ordered[int(k)]
    return ordered[lower] * (upper - k) + ordered[upper] * (k - lower)


def summarize(latencies_ms: List[float]) -> Dict:
    """
    Зводить серію вимірювань затримки (мс) до набору метрик.

    :param latencies_ms: список часів виконання у мілісекундах
    :return: словник метрик
    """
    n = len(latencies_ms)
    mean = sum(latencies_ms) / n
    variance = sum((x - mean) ** 2 for x in latencies_ms) / n
    return {
        # Кількість врахованих вимірювань (без «прогрівальних»)
        "runs": n,
        # Середній час виконання одного запуску
        "mean_ms": round(mean, 4),
        # Медіана (p50) — типовий час, стійкий до поодиноких викидів
        "median_ms": round(percentile(latencies_ms, 50), 4),
        # 95-й перцентиль — межа, яку не перевищують 95 % запусків
        "p95_ms": round(percentile(latencies_ms, 95), 4),
        # 99-й перцентиль — найважчі «хвости» затримок
        "p99_ms": round(percentile(latencies_ms, 99), 4),
        # Найшвидший запуск серії
        "min_ms": round(min(latencies_ms), 4),
        # Найповільніший запуск серії
        "max_ms": round(max(latencies_ms), 4),
        # Стандартне відхилення — розкид часу, показник стабільності
        "std_dev_ms": round(math.sqrt(variance), 4),
        # Пропускна здатність: скільки запитів за секунду витримує сценарій
        "throughput_rps": round(1000.0 / mean, 2) if mean > 0 else 0.0,
    }


def save_raw(stage: str, rows: List[Dict[str, Any]]) -> str:
    """Зберігає сирі вимірювання (кожен окремий запуск) у файл CSV."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{stage}_raw.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def save_summary(stage: str, rows: List[Dict[str, Any]]) -> str:
    """Зберігає зведені метрики етапу у файл CSV."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{stage}_summary.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def print_table(title: str, rows: List[Dict[str, Any]]) -> None:
    """Виводить зведену таблицю метрик у консоль (для скріншота у звіт)."""
    print()
    print("=" * 104)
    print(title)
    print("=" * 104)
    header = (f"{'Обсяг':<10}{'N елем.':>10}{'Середнє,мс':>13}{'Медіана,мс':>13}"
              f"{'p95,мс':>11}{'Мін,мс':>11}{'Макс,мс':>11}{'Запитів/с':>13}")
    print(header)
    print("-" * 104)
    for r in rows:
        print(f"{r['scale']:<10}{r['size']:>10}{r['mean_ms']:>13.3f}"
              f"{r['median_ms']:>13.3f}{r['p95_ms']:>11.3f}"
              f"{r['min_ms']:>11.3f}{r['max_ms']:>11.3f}{r['throughput_rps']:>13.2f}")
    print("=" * 104)
    print()
