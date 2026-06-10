"""
Backfill GRATUIT complet — orchestre 4 runs sequentiels du script batch.

Pack telecharge :
  Run 1 : OHLCV-1m + OHLCV-1d sur 15 ans (2011-04-25 -> 2026-04-25)
  Run 2 : Definition + Statistics sur 15 ans
  Run 3 : Trades sur 12 mois (2025-04-25 -> 2026-04-25)
  Run 4 : MBP-10 + MBO sur 1 mois (2026-03-25 -> 2026-04-25)

Volume estime : ~13 GB
Cout : $0 (tout inclus dans plan Standard $179)
Duree estimee : 30-60 min
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "CORE" / "databento_backfill_batch.py"
PYTHON = "C:/Program Files/Python313/python"

RUNS = [
    {
        "name": "Run 1 — OHLCV (1m + 1d) 15 ans",
        "schemas": ["ohlcv-1m", "ohlcv-1d"],
        "start": "2011-04-25",
        "end": "2026-04-25",
    },
    {
        "name": "Run 2 — Definition + Statistics 15 ans",
        "schemas": ["definition", "statistics"],
        "start": "2011-04-25",
        "end": "2026-04-25",
    },
    {
        "name": "Run 3 — Trades 12 mois",
        "schemas": ["trades"],
        "start": "2025-04-25",
        "end": "2026-04-25",
    },
    {
        "name": "Run 4 — MBP-10 + MBO 1 mois",
        "schemas": ["mbp-10", "mbo"],
        "start": "2026-03-25",
        "end": "2026-04-25",
    },
]


def main():
    print("=" * 90)
    print(" BACKFILL GRATUIT COMPLET — 4 runs sequentiels")
    print(f" Demarrage : {datetime.now().isoformat()}")
    print("=" * 90)

    overall_start = time.time()
    results = []

    for i, run in enumerate(RUNS, 1):
        print(f"\n{'='*90}")
        print(f" [{i}/{len(RUNS)}] {run['name']}")
        print(f"{'='*90}\n")

        run_start = time.time()
        cmd = [
            PYTHON, "-X", "utf8", str(SCRIPT),
            "--symbols", "ES.c.0", "NQ.c.0",
            "--schemas", *run["schemas"],
            "--start", run["start"],
            "--end", run["end"],
            "--no-confirm",
        ]
        print(f"  CMD: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, timeout=14400)  # 4h max per run
            run_dur = time.time() - run_start
            results.append({
                "run": run["name"],
                "exit_code": proc.returncode,
                "duration_sec": int(run_dur),
            })
            status = "OK" if proc.returncode == 0 else f"FAIL (exit {proc.returncode})"
            print(f"\n  [{run['name']}] -> {status} en {run_dur:.0f}s")

            if proc.returncode != 0:
                print(f"  [WARN] {run['name']} a echoue. On continue les autres runs.")
        except subprocess.TimeoutExpired:
            print(f"  [FATAL] {run['name']} timeout 4h depasse")
            results.append({"run": run["name"], "exit_code": -1, "duration_sec": -1})

    # Final summary
    total_dur = time.time() - overall_start
    print("\n" + "=" * 90)
    print(" SUMMARY ALL RUNS")
    print("=" * 90)
    for r in results:
        status = "OK" if r["exit_code"] == 0 else f"FAIL ({r['exit_code']})"
        print(f"  {r['run']:<50s} {status:<15s} {r['duration_sec']}s")
    print(f"\n  Total duration: {total_dur/60:.1f} min")
    print(f"  Finished at: {datetime.now().isoformat()}")

    n_ok = sum(1 for r in results if r["exit_code"] == 0)
    print(f"  {n_ok}/{len(results)} runs OK")
    sys.exit(0 if n_ok == len(results) else 1)


if __name__ == "__main__":
    main()
