"""
analyze_lab4.py - LAB 4 summary: VM CPU / RAM for idle and every load level.

Reads results/lab4_vmstat_<level>.log written by deploy/run_level.sh and the
level parameters written by bench_load.py, prints one table for the report
and the change of each level relative to idle.
"""

import csv
import os
import sys
from typing import Any, Dict, List, Optional

from metrics import DATA_SCALES_LAB2, RESULTS_DIR, save_summary

LEVELS = ["idle"] + list(DATA_SCALES_LAB2)
# Перші секунди відкидаються: перший рядок vmstat – середнє з моменту завантаження,
# далі – старт клієнта і прогрівальні запити
SKIP_SAMPLES = 10
LINE_LENGTH = 112


def parse_vmstat(path: str) -> Dict[str, Any]:
    """
    Розбирає лог run_level.sh: MemTotal, вивід vmstat -t -n -S M, VmRSS/VmHWM процесу.

    :param path: шлях до логу
    :return: усереднені показники CPU і RAM VM та пам'ять процесу сервісу
    """
    mem_total_mb = 0.0
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
            elif tokens[0] in ("VmRSS:", "VmHWM:"):
                proc[tokens[0].rstrip(":")] = float(tokens[1]) / 1024.0
            elif tokens[0] == "r" and "id" in tokens:
                # vmstat -t: останній стовпець заголовка – часовий пояс мітки часу, не метрика
                names = tokens[:-1]
            elif names and tokens[0].isdigit():
                samples.append({name: float(tokens[i]) for i, name in enumerate(names)})

    used = samples[SKIP_SAMPLES:]
    if not used:
        sys.exit(f"[!] У {path} замало вимірювань vmstat")

    def mean(values: List[float]) -> float:
        return sum(values) / len(values)

    busy = [100.0 - s["id"] for s in used]
    ram_used = [mem_total_mb - s["free"] - s["buff"] - s["cache"] for s in used]
    return {
        "samples": len(used),
        "cpu_busy_pct": round(mean(busy), 1),
        "cpu_busy_max_pct": round(max(busy), 1),
        "cpu_us_pct": round(mean([s["us"] for s in used]), 1),
        "cpu_sy_pct": round(mean([s["sy"] for s in used]), 1),
        "cpu_st_pct": round(mean([s.get("st", 0.0) for s in used]), 1),
        "mem_total_mb": round(mem_total_mb, 0),
        "ram_used_mb": round(mean(ram_used), 0),
        "ram_used_max_mb": round(max(ram_used), 0),
        "service_rss_mb": round(proc.get("VmRSS", 0.0), 1),
        "service_peak_mb": round(proc.get("VmHWM", 0.0), 1),
    }


def load_level_params(scale: str) -> Optional[Dict[str, str]]:
    """Параметри рівня від bench_load.py або None для простою."""
    path = os.path.join(RESULTS_DIR, f"lab4_load_{scale}_summary.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f))


def main() -> None:
    rows: List[Dict[str, Any]] = []
    for level in LEVELS:
        log = os.path.join(RESULTS_DIR, f"lab4_vmstat_{level}.log")
        if not os.path.exists(log):
            sys.exit(f"[!] Немає {log}\n    Спершу виконайте: VM_IP=<IP> ./deploy/run_level.sh {level}")
        row: Dict[str, Any] = {"level": level, "size": DATA_SCALES_LAB2.get(level, 0)}
        params = load_level_params(level) if level != "idle" else None
        row["rps"] = float(params["rps"]) if params else 0.0
        row["mean_ms"] = float(params["mean_ms"]) if params else 0.0
        row["handler_busy_pct"] = float(params["handler_busy_pct"]) if params else 0.0
        row.update(parse_vmstat(log))
        rows.append(row)

    idle = rows[0]
    print()
    print("=" * LINE_LENGTH)
    print(f"ЛР4. ВИКОРИСТАННЯ РЕСУРСІВ VM ЗАЛЕЖНО ВІД НАВАНТАЖЕННЯ  (RAM VM: {idle['mem_total_mb']:.0f} МБ)")
    print("=" * LINE_LENGTH)
    print(f"{'Рівень':<8}{'N елем.':>9}{'Запит/с':>9}{'Затр.,мс':>10}"
          f"{'CPU сер.,%':>12}{'CPU макс,%':>12}{'us/sy/st,%':>14}"
          f"{'RAM VM,МБ':>11}{'ΔRAM,МБ':>9}{'Процес,МБ':>11}{'Пік,МБ':>8}")
    print("-" * LINE_LENGTH)
    for r in rows:
        split = f"{r['cpu_us_pct']:.0f}/{r['cpu_sy_pct']:.0f}/{r['cpu_st_pct']:.0f}"
        print(f"{r['level']:<8}{r['size']:>9}{r['rps']:>9.1f}{r['mean_ms']:>10.1f}"
              f"{r['cpu_busy_pct']:>12.1f}{r['cpu_busy_max_pct']:>12.1f}{split:>14}"
              f"{r['ram_used_mb']:>11.0f}{r['ram_used_mb'] - idle['ram_used_mb']:>+9.0f}"
              f"{r['service_rss_mb']:>11.1f}{r['service_peak_mb']:>8.1f}")
    print("=" * LINE_LENGTH)
    print("CPU – частка зайнятого часу (100 − id) за vmstat; us/sy/st – користувацький, системний")
    print("та «вкрадений» гіпервізором час. RAM VM = total − free − buff − cache. Процес/Пік – VmRSS/VmHWM")
    print(f"процесу сервісу наприкінці рівня. Перші {SKIP_SAMPLES} с кожного рівня відкинуто.")
    print()
    print(f"Зведення: {save_summary('lab4', rows)}")


if __name__ == "__main__":
    sys.exit(main())
