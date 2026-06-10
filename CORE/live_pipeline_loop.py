"""live_pipeline_loop.py — Loop infini live_pipeline toutes les N minutes.

Lance live_pipeline.py en boucle. Garde le dataset enrichi a jour.

Usage :
    # Run en background (Ctrl+C pour arret propre) :
    python -X utf8 CORE/live_pipeline_loop.py

    # Avec interval personnalise (default 5 min) :
    python -X utf8 CORE/live_pipeline_loop.py --interval 300

    # Skip Phase B sur les iterations intermediaires (Phase B chaque 6 iters seulement) :
    python -X utf8 CORE/live_pipeline_loop.py --phase-b-every 6

Resilience :
  - Si une iteration echoue (rc != 0), log + continue (next iter)
  - Si Ctrl+C : arret propre apres iteration courante
  - Log timestamp + duration + status pour chaque iter
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "LOGS" / "live_pipeline_loop.log"
LIVE_PIPELINE = ROOT / "CORE" / "live_pipeline.py"

PYTHON_EXE = sys.executable

_stop_requested = False


def _signal_handler(signum, frame):
    global _stop_requested
    print(f"\n[LOOP] Signal {signum} recu, arret apres iteration courante...")
    _stop_requested = True


def _log_line(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="Loop infini live_pipeline batch")
    ap.add_argument("--interval", type=int, default=300,
                    help="Secondes entre iterations (default 300 = 5 min)")
    ap.add_argument("--phase-b-every", type=int, default=1,
                    help="Run Phase B chaque N iterations (default 1 = chaque iter). "
                         "Mettre 6 = Phase B chaque 30 min (5 min iter * 6)")
    ap.add_argument("--max-iter", type=int, default=0,
                    help="Limite nb iterations (0 = infini)")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)

    _log_line(f"START loop interval={args.interval}s phase_b_every={args.phase_b_every}")

    iter_count = 0
    while not _stop_requested:
        iter_count += 1
        if args.max_iter and iter_count > args.max_iter:
            _log_line(f"max-iter {args.max_iter} reached, stopping")
            break

        run_phase_b = (iter_count % args.phase_b_every == 0)
        skip_phase_b_arg = [] if run_phase_b else ["--skip-phase-b"]

        cmd = [
            PYTHON_EXE, "-X", "utf8",
            str(LIVE_PIPELINE),
            *skip_phase_b_arg,
        ]
        _log_line(f"iter {iter_count} START (phase_b={'yes' if run_phase_b else 'no'})")
        t0 = time.time()
        try:
            result = subprocess.run(cmd, timeout=900)
            elapsed = time.time() - t0
            status = "OK" if result.returncode == 0 else f"FAIL rc={result.returncode}"
            _log_line(f"iter {iter_count} {status} ({elapsed:.1f}s)")
        except subprocess.TimeoutExpired:
            _log_line(f"iter {iter_count} TIMEOUT after 900s")
        except Exception as e:
            _log_line(f"iter {iter_count} EXCEPTION: {e}")

        if _stop_requested:
            break

        # Sleep until next iteration
        sleep_remaining = max(0, args.interval - (time.time() - t0))
        if sleep_remaining > 0:
            _log_line(f"sleep {sleep_remaining:.0f}s before next iter")
            # Sleep in chunks pour pouvoir interrompre vite
            chunks = int(sleep_remaining // 5) + 1
            for _ in range(chunks):
                if _stop_requested:
                    break
                time.sleep(min(5, sleep_remaining))
                sleep_remaining -= 5

    _log_line(f"STOP after {iter_count} iterations")


if __name__ == "__main__":
    main()
