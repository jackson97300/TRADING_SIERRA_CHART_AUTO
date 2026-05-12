"""Rebuild V4 enriched complet ES + NQ mai 2026.

Safe pattern :
1. Stop MIA-LivePipeline service (eviter conflit DuckDB)
2. Rebuild jour par jour 01/05 → 12/05 ES + NQ
3. PHASE_B sur tout mai
4. RESTART MIA-LivePipeline (try/finally garanti)
5. Audit post-rebuild

Run sur VPS uniquement.
"""
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
PYTHON = "C:/Program Files/Python311/python.exe"

START = date(2026, 5, 1)
END = date(2026, 5, 12)
SYMBOLS = ["ES", "NQ"]


def run(cmd: list, label: str, timeout: int = 600) -> bool:
    print(f"\n[{label}] {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            tail = result.stdout.strip().split("\n")[-5:]
            for line in tail:
                print(f"    {line}")
            return True
        else:
            print(f"    FAILED rc={result.returncode}")
            for line in result.stderr.strip().split("\n")[-10:]:
                print(f"      {line}")
            return False
    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT after {timeout}s")
        return False
    except Exception as e:
        print(f"    EXCEPTION {type(e).__name__}: {e}")
        return False


def main():
    # 1. Stop live pipeline
    print("=" * 70)
    print("REBUILD V4 enriched ES + NQ mai 2026")
    print("=" * 70)

    run(["powershell", "-Command", "nssm stop MIA-LivePipeline"], "STOP_PIPELINE", timeout=60)

    pipeline_restarted = False
    try:
        # 2. Rebuild jour par jour
        cur = START
        n_ok = 0
        n_fail = 0
        while cur <= END:
            date_str = cur.isoformat()
            cmd = [
                PYTHON, "-X", "utf8",
                str(ROOT / "CORE" / "build_dataset_v4_dmp_databento.py"),
                "--test-day", date_str,
                "--use-mq-lite",
                "--symbols", *SYMBOLS,
            ]
            ok = run(cmd, f"BUILD_V4 {date_str}", timeout=300)
            if ok:
                n_ok += 1
            else:
                n_fail += 1
            cur += timedelta(days=1)

        print(f"\nBUILD_V4 : {n_ok} OK, {n_fail} FAIL")

        # 3. PHASE_B sur tout mai
        cmd_phase_b = [
            PYTHON, "-X", "utf8",
            str(ROOT / "CORE" / "build_dataset_v4_phase_b.py"),
            "--month", "2026-05",
            "--symbols", *SYMBOLS,
        ]
        run(cmd_phase_b, "PHASE_B 2026-05", timeout=900)

    finally:
        # 4. RESTART live pipeline (try/finally garanti)
        print(f"\n[CRITICAL] Restart MIA-LivePipeline")
        ok = run(["powershell", "-Command", "nssm start MIA-LivePipeline"],
                 "START_PIPELINE", timeout=60)
        pipeline_restarted = ok
        if not ok:
            print("\n!!! PIPELINE PAS REDEMARRE — ACTION MANUELLE REQUISE !!!")
            print("    ssh VPS : nssm start MIA-LivePipeline")

    print("\n" + "=" * 70)
    print(f"  REBUILD DONE — pipeline_restarted={pipeline_restarted}")
    print("=" * 70)


if __name__ == "__main__":
    main()
