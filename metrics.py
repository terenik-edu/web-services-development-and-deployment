"""
metrics.py - is a common module for processing and storing measurement results.

It is used by all three stages of the experiment so that metrics
are calculated using a single methodology and are comparable with each other.
"""

import csv
import math
import os
import resource
import sys
from typing import List, Dict, Any

# Масштаби даних згідно з пунктом 3 завдання
DATA_SCALES = {
    "small": 100,      # ~1 KB   (KB – кілобайт)
    "medium": 1_000,   # ~10 KB
    "large": 10_000,   # ~100 KB
}

RUNS = 100      # кількість вимірюваних запитів на сценарій
WARMUP = 10     # кількість «прогрівальних» запусків (у статистику не входять)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def percentile(values: List[float], p: float) -> float:
    """
    Обчислює перцентиль методом лінійної інтерполяції.

    p95 (95-й перцентиль) – значення, гірше за яке лише 5 % запитів.
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
        # Медіана (p50) – типовий час, стійкий до поодиноких викидів
        "median_ms": round(percentile(latencies_ms, 50), 4),
        # 95-й перцентиль – межа, яку не перевищують 95 % запусків
        "p95_ms": round(percentile(latencies_ms, 95), 4),
        # 99-й перцентиль – найважчі «хвости» затримок
        "p99_ms": round(percentile(latencies_ms, 99), 4),
        # Найшвидший запуск серії
        "min_ms": round(min(latencies_ms), 4),
        # Найповільніший запуск серії
        "max_ms": round(max(latencies_ms), 4),
        # Стандартне відхилення – розкид часу, показник стабільності
        "std_dev_ms": round(math.sqrt(variance), 4),
        # Пропускна здатність: скільки запитів за секунду витримує сценарій
        "throughput_rps": round(1000.0 / mean, 2) if mean > 0 else 0.0,
    }


def _max_rss_to_mb(ru_maxrss: int) -> float:
    """
    Переводить піковий обсяг пам'яті у мегабайти.

    Одиниця виміру ru_maxrss залежить від операційної системи:
    macOS повертає байти, Linux – кілобайти. Без нормалізації значення
    Етапу 3 (контейнер на Linux) були б у 1024 рази меншими за значення
    Етапів 1 і 2 і непорівнюваними з ними.

    :param ru_maxrss: значення поля ru_maxrss зі структури getrusage
    :return: піковий обсяг оперативної пам'яті у мегабайтах
    """
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return ru_maxrss / divisor


def resource_snapshot() -> Dict[str, float]:
    """
    Знімає миттєвий зріз використання ресурсів поточним процесом.

    Використовується лише стандартна бібліотека (модуль resource),
    щоб не додавати зовнішніх залежностей до вимірювальної частини.

    :return: словник із процесорним часом і піковою пам'яттю
    """
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        # Процесорний час у користувацькому режимі (виконання самого коду)
        "cpu_user_s": usage.ru_utime,
        # Процесорний час у системному режимі (системні виклики ядра)
        "cpu_sys_s": usage.ru_stime,
        # Пікове використання оперативної пам'яті за весь час життя процесу
        "max_rss_mb": _max_rss_to_mb(usage.ru_maxrss),
    }


def resource_delta(before: Dict[str, float], after: Dict[str, float]) -> Dict[str, float]:
    """
    Обчислює витрати ресурсів між двома зрізами.

    Процесорний час береться як різниця: це час, витрачений саме на серію
    вимірювань. Пікова пам'ять береться як абсолютне значення другого зрізу,
    бо ru_maxrss – це максимум за весь час життя процесу, і його різниця
    майже завжди дорівнює нулю.

    :param before: зріз, знятий до серії вимірювань
    :param after: зріз, знятий після серії вимірювань
    :return: словник метрик використання ресурсів
    """
    cpu_user = after["cpu_user_s"] - before["cpu_user_s"]
    cpu_sys = after["cpu_sys_s"] - before["cpu_sys_s"]
    return {
        # Процесорний час користувача, витрачений на серію (мс)
        "cpu_user_ms": round(cpu_user * 1000.0, 3),
        # Процесорний час системи, витрачений на серію (мс)
        "cpu_sys_ms": round(cpu_sys * 1000.0, 3),
        # Сумарний процесорний час серії (мс)
        "cpu_total_ms": round((cpu_user + cpu_sys) * 1000.0, 3),
        # Пік оперативної пам'яті процесу на момент завершення серії (МБ)
        "max_rss_mb": round(after["max_rss_mb"], 2),
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


def print_resources(title: str, rows: List[Dict[str, Any]]) -> None:
    """
    Виводить таблицю використання ресурсів (для скріншота у звіт).

    Показники подано окремою таблицею, щоб не перевантажувати основну
    таблицю затримок: це різні за природою метрики – час відгуку
    і споживання обчислювальних ресурсів.

    :param title: заголовок таблиці
    :param rows: рядки зі зведеними метриками етапу
    """
    print()
    print("=" * 104)
    print(title)
    print("=" * 104)
    header = (f"{'Обсяг':<10}{'N елем.':>10}{'CPU user,мс':>14}{'CPU sys,мс':>14}"
              f"{'CPU разом,мс':>16}{'Пік пам’яті,МБ':>18}")
    print(header)
    print("-" * 104)
    for r in rows:
        print(f"{r['scale']:<10}{r['size']:>10}{r['cpu_user_ms']:>14.3f}"
              f"{r['cpu_sys_ms']:>14.3f}{r['cpu_total_ms']:>16.3f}"
              f"{r['max_rss_mb']:>18.2f}")
    print("=" * 104)
    print()


def print_breakdown(title: str, rows: List[Dict[str, Any]]) -> None:
    """
    Виводить розклад повного часу запиту на складові (для скріншота у звіт).

    Це головна аналітична таблиця Етапів 2 і 3: видно, яка частина часу
    припадає на корисне обчислення, а яка – на накладні витрати архітектури
    (транспорт, розбір та формування JSON).

    :param title: заголовок таблиці
    :param rows: рядки зі зведеними метриками етапу
    """
    print()
    print("=" * 104)
    print(title)
    print("=" * 104)
    header = (f"{'Обсяг':<10}{'T_total,мс':>12}{'T_server,мс':>13}{'Десеріал.,мс':>14}"
              f"{'Обчисл.,мс':>12}{'Серіал.,мс':>12}{'Транспорт,мс':>14}{'Тіло,КБ':>11}")
    print(header)
    print("-" * 104)
    for r in rows:
        print(f"{r['scale']:<10}{r['mean_ms']:>12.3f}{r['server_total_ms']:>13.3f}"
              f"{r['server_deserialize_ms']:>14.3f}{r['server_compute_ms']:>12.3f}"
              f"{r['server_serialize_ms']:>12.3f}{r['transport_ms']:>14.3f}"
              f"{r['request_bytes'] / 1024.0:>11.1f}")
    print("=" * 104)
    print()
