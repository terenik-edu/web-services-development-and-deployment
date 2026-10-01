"""
compare_lab2.py - LAB 2 summary table: local run vs Azure App Service.

Reads the summaries written by bench_tasks.py for both targets and prints
request latency, algorithm latency and overhead side by side (for the report).
"""

import csv
import os
import sys
from typing import Dict

from metrics import DATA_SCALES_LAB2, RESULTS_DIR

LOCAL_PATH = os.path.join(RESULTS_DIR, "lab2_local_summary.csv")
AZURE_PATH = os.path.join(RESULTS_DIR, "lab2_azure_summary.csv")
LINE_LENGTH = 128


def load_summary(path: str, target: str) -> Dict[str, Dict[str, float]]:
    """
    Читає зведення одного середовища.

    :param path: шлях до CSV від bench_tasks.py
    :param target: позначка середовища – для підказки, якщо файлу немає
    :return: {масштаб: {поле: значення}} лише з потрібними числовими полями
    :raises SystemExit: якщо файлу немає
    """
    if not os.path.exists(path):
        sys.exit(f"[!] Немає файлу {path}\n"
                 f"    Спершу виконайте: python3 bench_tasks.py --target {target} --url <адреса сервісу>")
    with open(path, newline="", encoding="utf-8") as f:
        return {
            row["scale"]: {key: float(row[key]) for key in ("mean_ms", "server_compute_ms", "overhead_ms")}
            for row in csv.DictReader(f)
        }


def main() -> None:
    local = load_summary(LOCAL_PATH, "local")
    azure = load_summary(AZURE_PATH, "azure")

    print()
    print("=" * LINE_LENGTH)
    print("ЛР2 – LOCAL vs AZURE (середні значення серії, мс)")
    print("=" * LINE_LENGTH)
    print(f"{'Обсяг':<10}{'Request local':>15}{'Request azure':>15}{'Algorithm local':>17}"
          f"{'Algorithm azure':>17}{'Overhead local':>16}{'Overhead azure':>16}{'Overhead azure/local':>22}")
    print("-" * LINE_LENGTH)
    for scale in DATA_SCALES_LAB2:
        if scale not in local or scale not in azure:
            print(f"{scale:<10}немає даних в одному з файлів")
            continue
        lo, az = local[scale], azure[scale]
        ratio = az["overhead_ms"] / lo["overhead_ms"] if lo["overhead_ms"] > 0 else float("nan")
        print(f"{scale:<10}{lo['mean_ms']:>15.3f}{az['mean_ms']:>15.3f}"
              f"{lo['server_compute_ms']:>17.3f}{az['server_compute_ms']:>17.3f}"
              f"{lo['overhead_ms']:>16.3f}{az['overhead_ms']:>16.3f}{ratio:>21.1f}×")
    print("=" * LINE_LENGTH)
    print()


if __name__ == "__main__":
    sys.exit(main())