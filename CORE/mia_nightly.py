"""
mia_nightly.py — Pipeline nocturne automatique MIA
====================================================
Lance les 4 tests/analyses apres la cloture US (22:15 Paris).
Se lance tous les jours via Task Scheduler — verifie lui-meme
si c'est un jour de trading avant d'executer.

Ordre d'execution :
    1. dmp_validator.py    — Validation schema JSONL du jour
    2. test_all.py         — Tests unitaires pipeline (54+ tests)
    3. mia_session_replay.py — Analyse niveaux post-session
    4. mia_bench.py        — Benchmark complet (19 tests, ~20 min)

Output :
    DATA/LOGS/nightly_YYYYMMDD.log  — log complet de la nuit

Usage :
    python -X utf8 CORE/mia_nightly.py            # auto-detect date
    python -X utf8 CORE/mia_nightly.py --force     # ignore check jour trading
    python -X utf8 CORE/mia_nightly.py --skip-bench # sans bench (rapide)

Auteur : MIA Trading System
Date   : 2026-04-06
"""

import os
import sys
import subprocess
import time
from datetime import datetime, date
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
CORE_DIR = ROOT_DIR / "CORE"
DATA_DIR = ROOT_DIR / "DATA"
LOG_DIR = DATA_DIR / "LOGS"

MIN_FILE_SIZE = 100_000  # 100KB minimum pour un vrai jour de trading


def is_trading_day(today: date = None) -> tuple[bool, str]:
    """Verifie si aujourd'hui est un jour de trading.

    Returns:
        (True/False, raison)
    """
    if today is None:
        today = date.today()

    # Weekend
    if today.weekday() >= 5:
        return False, f"Weekend ({today.strftime('%A')})"

    # Jours feries CME 2026 (marches fermes ou early close)
    cme_holidays = {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 19): "MLK Day",
        date(2026, 2, 16): "Presidents Day",
        date(2026, 4, 3): "Good Friday",
        date(2026, 5, 25): "Memorial Day",
        date(2026, 7, 3): "Independence Day (observed)",
        date(2026, 9, 7): "Labor Day",
        date(2026, 11, 26): "Thanksgiving",
        date(2026, 12, 25): "Christmas",
    }

    if today in cme_holidays:
        return False, f"Jour ferie CME: {cme_holidays[today]}"

    # Verifier si on a des donnees du jour (le check le plus fiable)
    date_str = today.strftime("%Y%m%d")
    es_file = DATA_DIR / "ES" / f"{date_str}_ES.jsonl"
    nq_file = DATA_DIR / "NQ" / f"{date_str}_NQ.jsonl"

    es_ok = es_file.exists() and es_file.stat().st_size > MIN_FILE_SIZE
    nq_ok = nq_file.exists() and nq_file.stat().st_size > MIN_FILE_SIZE

    if not es_ok and not nq_ok:
        return False, f"Pas de JSONL du jour (ES={es_file.exists()}, NQ={nq_file.exists()})"

    return True, "Jour de trading"


def run_step(name: str, cmd: list[str], log_file, timeout: int = 1800) -> bool:
    """Execute une etape du pipeline.

    Args:
        name: Nom de l'etape
        cmd: Commande a executer
        log_file: Fichier log ouvert en ecriture
        timeout: Timeout en secondes (default 30 min)

    Returns:
        True si succes
    """
    header = f"\n{'='*60}\n  ETAPE: {name}\n  Commande: {' '.join(cmd)}\n  Debut: {datetime.now().strftime('%H:%M:%S')}\n{'='*60}\n"
    log_file.write(header)
    log_file.flush()
    print(header, end="")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - start

        log_file.write(result.stdout)
        if result.stderr:
            log_file.write(f"\n--- STDERR ---\n{result.stderr}")

        status = "OK" if result.returncode == 0 else f"ERREUR (code {result.returncode})"
        summary = f"\n  [{status}] {name} — {elapsed:.1f}s\n"
        log_file.write(summary)
        log_file.flush()
        print(f"  [{status}] {name} — {elapsed:.1f}s")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        msg = f"\n  [TIMEOUT] {name} — depasse {timeout}s\n"
        log_file.write(msg)
        log_file.flush()
        print(msg, end="")
        return False

    except Exception as e:
        msg = f"\n  [CRASH] {name} — {e}\n"
        log_file.write(msg)
        log_file.flush()
        print(msg, end="")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MIA Nightly Pipeline")
    parser.add_argument("--force", action="store_true", help="Ignorer le check jour de trading")
    parser.add_argument("--skip-bench", action="store_true", help="Sauter le bench (rapide)")
    args = parser.parse_args()

    today = date.today()
    date_str = today.strftime("%Y%m%d")
    date_fmt = today.strftime("%Y-%m-%d")

    # Header
    print(f"\n{'#'*60}")
    print(f"  MIA NIGHTLY PIPELINE — {date_fmt}")
    print(f"  Heure: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'#'*60}")

    # Check jour de trading
    if not args.force:
        is_trading, reason = is_trading_day(today)
        if not is_trading:
            print(f"\n  SKIP — {reason}")
            print(f"  Utiliser --force pour executer quand meme\n")
            return

    # Creer le dossier logs
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"nightly_{date_str}.log"

    python = sys.executable

    # Definir les etapes
    steps = [
        (
            "1. DMP Validator",
            [python, "-X", "utf8", str(CORE_DIR / "dmp_validator.py"),
             str(DATA_DIR / "ES" / f"{date_str}_ES.jsonl"),
             str(DATA_DIR / "NQ" / f"{date_str}_NQ.jsonl")],
            120,
        ),
        (
            "2. Test All (54+ tests)",
            [python, "-X", "utf8", str(CORE_DIR / "test_all.py")],
            300,
        ),
        (
            "3. Session Replay",
            [python, "-X", "utf8", str(CORE_DIR / "mia_session_replay.py"),
             "--date", date_fmt],
            300,
        ),
    ]

    if not args.skip_bench:
        steps.append((
            "4. Benchmark (19 tests)",
            [python, "-X", "utf8", str(CORE_DIR / "mia_bench.py"),
             str(DATA_DIR / "ES"), str(DATA_DIR / "NQ")],
            1800,
        ))

    # Executer
    results = {}
    total_start = time.time()

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"MIA NIGHTLY PIPELINE — {date_fmt}\n")
        log.write(f"Debut: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log.write(f"Python: {python}\n")
        log.write(f"Root: {ROOT_DIR}\n\n")

        for name, cmd, timeout in steps:
            ok = run_step(name, cmd, log, timeout)
            results[name] = ok

        # Resume final
        total_elapsed = time.time() - total_start
        passed = sum(1 for v in results.values() if v)
        total = len(results)

        summary = f"""
{'#'*60}
  RESUME NIGHTLY — {date_fmt}
{'#'*60}
"""
        for name, ok in results.items():
            status = "PASS" if ok else "FAIL"
            icon = "[OK]" if ok else "[!!]"
            summary += f"  {icon} {name}: {status}\n"

        summary += f"""
  Total: {passed}/{total} etapes OK
  Duree: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)
  Log: {log_path}
{'#'*60}
"""
        log.write(summary)
        print(summary)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
