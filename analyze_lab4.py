"""
analyze_lab4.py - LAB 4 summary: VM CPU / RAM for idle and every load level.

Reads results/lab4_vmstat_<level>.log written by deploy/run_level.sh and the
level parameters written by bench_load.py, prints one table for the report
and the change of each level relative to idle.

Usage: python analyze_lab4.py [level ...]   (default: idle rate20 rate50 rate100 max)
"""

import csv
import os
import sys
from typing import Any, Dict, List, Optional

from metrics import RESULTS_DIR, save_summary

DEFAULT_LEVELS = ["idle", "rate20", "rate50", "rate100", "max"]
# Перший рядок vmstat – середнє з моменту завантаження ОС, не поточний стан
SKIP_SAMPLES = 1
LINE_LENGTH = 116


def parse_vmstat(path: str) -> Dict[str, Any]:
    """
    Розбирає лог run_level.sh: MemTotal, CPU-час процесу сервісу,
    вивід vmstat -t -n -S M, VmRSS/VmHWM процесу.

    :param path: шлях до логу
    :return: усереднені показники CPU і RAM VM та ресурси процесу сервісу
    """
    mem_total_mb = 0.0
    clk_tck = 100.0
    cpu_ticks: Dict[str, float] = {}
    names: List[str] = []
    samples: List[Dict[str, float]] = []
    proc: Dict[str, float] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "MemTotal:":
                mem_total_mb = float(tokens[1]) / 1024.0
            elif tokens[0] == "CLK_TCK":
                clk_tck = float(tokens[1])
            elif tokens[0].startswith("SERVICE_CPU_"):
                cpu_ticks[tokens[0]] = float(tokens[1])
            elif tokens[0] in ("VmRSS:", "VmHWM:"):
                proc[tokens[0].rstrip(":")] = float(tokens[1]) / 1024.0
            elif tokens[0] == "r" and "id" in tokens:
                # vmstat -t: останній стовпець заголовка – часовий пояс мітки часу, не метрика
                names = tokens[:-1]
            elif names and tokens[0].isdigit():
                samples.append({name: float(tokens[i]) for i, name in enumerate(names)})

    window_s = float(len(samples))
    used = samples[SKIP_SAMPLES:]
    if not used:
        sys.exit(f"[!] У {path} немає вимірювань vmstat")

    def mean(values: List[float]) -> float:
        return sum(values) / len(values)

    busy = [100.0 - s["id"] for s in used]
    ram_used = [mem_total_mb - s["free"] - s["buff"] - s["cache"] for s in used]
    service_cpu_s = (cpu_ticks.get("SERVICE_CPU_AFTER", 0.0) - cpu_ticks.get("SERVICE_CPU_BEFORE", 0.0)) / clk_tck
    return {
        "window_s": window_s,
        "cpu_busy_pct": round(mean(busy), 1),
        "cpu_busy_max_pct": round(max(busy), 1),
        "cpu_us_pct": round(mean([s["us"] for s in used]), 1),
        "cpu_sy_pct": round(mean([s["sy"] for s in used]), 1),
        "cpu_st_pct": round(mean([s.get("st", 0.0) for s in used]), 1),
        # Завантаження одного ядра процесом сервісу (uvicorn з одним воркером – максимум 100 %)
        "service_cpu_pct": round(service_cpu_s / window_s * 100.0, 1),
        "mem_total_mb": round(mem_total_mb, 0),
        "ram_used_mb": round(mean(ram_used), 0),
        "ram_used_max_mb": round(max(ram_used), 0),
        "service_rss_mb": round(proc.get("VmRSS", 0.0), 1),
        "service_peak_mb": round(proc.get("VmHWM", 0.0), 1),
    }


def load_level_params(label: str) -> Optional[Dict[str, str]]:
    """Параметри рівня від bench_load.py або None для простою."""
    path = os.path.join(RESULTS_DIR, f"lab4_load_{label}_summary.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f))


def main() -> None:
    levels = sys.argv[1:] or DEFAULT_LEVELS
    rows: List[Dict[str, Any]] = []
    for level in levels:
        log = os.path.join(RESULTS_DIR, f"lab4_vmstat_{level}.log")
        if not os.path.exists(log):
            sys.exit(f"[!] Немає {log}\n    Спершу виконайте на VM: ./deploy/run_level.sh {level} <запитів/с>")
        params = load_level_params(level)
        row: Dict[str, Any] = {
            "level": level,
            "rate_target": float(params["rate_target"]) if params else 0.0,
            "size": int(params["size"]) if params else 0,
            "rps": float(params["rps"]) if params else 0.0,
            "mean_ms": float(params["mean_ms"]) if params else 0.0,
            "handler_busy_pct": float(params["handler_busy_pct"]) if params else 0.0,
        }
        row.update(parse_vmstat(log))
        rows.append(row)

    base = rows[0]
    print()
    print("=" * LINE_LENGTH)
    print(f"ЛР4. ВИКОРИСТАННЯ РЕСУРСІВ VM ЗАЛЕЖНО ВІД НАВАНТАЖЕННЯ  (RAM VM: {base['mem_total_mb']:.0f} МБ)")
    print("=" * LINE_LENGTH)
    print(f"{'Рівень':<9}{'Ціль,зап/с':>11}{'Факт,зап/с':>11}{'Затр.,мс':>10}"
          f"{'CPU VM,%':>10}{'макс,%':>8}{'CPU сервісу,%':>15}"
          f"{'RAM VM,МБ':>11}{'ΔRAM,МБ':>9}{'Процес,МБ':>11}{'Пік,МБ':>8}")
    print("-" * LINE_LENGTH)
    for r in rows:
        target = "-" if r["level"] == "idle" else ("макс." if r["rate_target"] == 0 else f"{r['rate_target']:g}")
        print(f"{r['level']:<9}{target:>11}{r['rps']:>11.1f}{r['mean_ms']:>10.2f}"
              f"{r['cpu_busy_pct']:>10.1f}{r['cpu_busy_max_pct']:>8.1f}{r['service_cpu_pct']:>15.1f}"
              f"{r['ram_used_mb']:>11.0f}{r['ram_used_mb'] - base['ram_used_mb']:>+9.0f}"
              f"{r['service_rss_mb']:>11.1f}{r['service_peak_mb']:>8.1f}")
    print("=" * LINE_LENGTH)
    print("CPU VM – середня зайнятість усіх vCPU (100 − id) за vmstat, разом із генератором навантаження.")
    print("CPU сервісу – завантаження одного ядра процесом uvicorn (utime + stime за вікно вимірювань).")
    print("RAM VM = total − free − buff − cache. Процес/Пік – VmRSS/VmHWM процесу сервісу наприкінці рівня.")
    print()
    print(f"Зведення: {save_summary('lab4', rows)}")


if __name__ == "__main__":
    sys.exit(main())
