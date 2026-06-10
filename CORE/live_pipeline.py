"""live_pipeline.py — Orchestrateur batch 5min : download Databento + enrichi.

Usage typique (cron 5 min) :
    python -X utf8 CORE/live_pipeline.py
    # ou
    python -X utf8 CORE/live_pipeline.py --date 2026-04-28

Workflow :
  1. Determine date courante (UTC) + partial_end = now - DATABENTO_DELAY_MIN
  2. Download Databento (ohlcv-1m + trades) via databento_download.py
  3. Convert trades dbn.zst -> parquet (databento_dumper ne le fait pas)
  4. Run build_dataset_v4_dmp_databento --test-day {date} --use-mq-lite
  5. Run build_dataset_v4_phase_b --month {YYYY-MM}
  6. Log resultat + duration

Resultat : DATA/datasets/v4_enriched/ mis a jour avec les barres jusqu'a partial_end.
Le bot peut consommer ce parquet directement.

Resilience :
  - Si une etape echoue, log + sortie code != 0, ne casse pas l'historique
  - Si Databento Historical n'a pas encore tout (data_end_after_available_end),
    fallback sur partial_end plus court automatiquement
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import databento as db

ROOT = Path(__file__).resolve().parents[1]
DBN_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3"
TRADES_ROOT = DBN_ROOT / "trades"

# 11/05 Jackson "nos garde-fous" : brancher logging_v2 pour emit codes
# DOWNLOAD_STALE_POST_FETCH visible dashboard widget "Erreurs recentes".
sys.path.insert(0, str(ROOT))
try:
    from CORE.logging_v2 import get_logger
    _v2log = get_logger("live_pipeline", process="pipeline")
except Exception:
    _v2log = None

def _emit(code: str, **ctx):
    if _v2log is None:
        return
    try:
        _v2log.emit(code, **ctx)
    except Exception:
        pass

DATABENTO_DELAY_MIN = 15  # 01/05 v3 : test DELAY=5 a montre Databento livre
                          # seulement jusqu'a end-30min (delay reel API ~30 min
                          # constate empiriquement). DELAY=15 = compromis safe.
                          # VRAIE solution = Bot 2 lit LIVE_CACHE pour scoring
                          # (refactor en cours, pas Historical pipeline).
PYTHON_EXE = sys.executable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_cmd(cmd: list[str], step: str) -> bool:
    """Run a command, return True if success. Print output."""
    print(f"\n[{step}] {' '.join(cmd)}")
    t0 = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = time.time() - t0
        if result.returncode == 0:
            print(f"[{step}] OK ({elapsed:.1f}s)")
            # Print last 5 lines stdout for context
            tail = result.stdout.strip().split("\n")[-5:]
            for ln in tail:
                print(f"    {ln}")
            return True
        else:
            print(f"[{step}] FAILED rc={result.returncode} ({elapsed:.1f}s)")
            print(f"    stdout last 10:")
            for ln in result.stdout.strip().split("\n")[-10:]:
                print(f"      {ln}")
            print(f"    stderr last 10:")
            for ln in result.stderr.strip().split("\n")[-10:]:
                print(f"      {ln}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[{step}] TIMEOUT after 600s")
        return False
    except Exception as e:
        print(f"[{step}] EXCEPTION: {e}")
        return False


def convert_trades_to_parquet(target_date: date, symbols: list[str]) -> bool:
    """Convertit trades dbn.zst -> parquet pour la date cible (databento_download
    ne le fait que pour OHLCV)."""
    print(f"\n[CONVERT TRADES] {target_date}")
    n_ok = 0
    for sym in symbols:
        fp = (TRADES_ROOT / f"symbol={sym}" /
              f"year={target_date.year}" / f"month={target_date.month}" / f"day={target_date.day}" /
              "data.dbn.zst")
        if not fp.exists():
            print(f"  [SKIP] {sym} {target_date} : dbn.zst not found at {fp}")
            continue
        out_fp = fp.with_name("data.parquet")
        if out_fp.exists() and out_fp.stat().st_mtime >= fp.stat().st_mtime:
            print(f"  [SKIP] {sym} {target_date} : parquet already up-to-date")
            n_ok += 1
            continue
        try:
            store = db.DBNStore.from_file(str(fp))
            df = store.to_df()
            df.to_parquet(out_fp, compression="zstd", index=True)
            size_kb = out_fp.stat().st_size / 1024
            print(f"  [OK] {sym} {len(df)} trades -> {out_fp.name} ({size_kb:.0f} KB)")
            n_ok += 1
        except Exception as e:
            print(f"  [ERR] {sym} {target_date}: {e}")
    return n_ok > 0


def main():
    ap = argparse.ArgumentParser(description="Live pipeline batch 5min : download + enrich")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    # 12/05/2026 fix Bot 3 MGC : ajout MGC.v.0 aux symbols par defaut
    # Avant ce fix : live_pipeline_loop tournait sans --symbols → defaut ES+NQ
    # → V4 enriched MGC pas regenere depuis 23/04 → Bot 3 MGC BAR_STALE en boucle.
    # Note : build_dataset_v4_dmp_databento.py supporte MGC depuis Chantier 5bis (10/05).
    ap.add_argument("--symbols", nargs="+", default=["ES.c.0", "NQ.c.0", "MGC.v.0"])
    ap.add_argument("--symbols-short", nargs="+", default=["ES", "NQ", "MGC"],
                    help="Format court pour pipeline V4 (sans .c.0)")
    ap.add_argument("--delay-min", type=int, default=DATABENTO_DELAY_MIN,
                    help=f"Delay Databento Historical API en minutes (default {DATABENTO_DELAY_MIN})")
    ap.add_argument("--skip-download", action="store_true",
                    help="Skip Databento download (utilise parquets deja presents)")
    ap.add_argument("--skip-phase-b", action="store_true",
                    help="Skip Phase B (output 50 cols seulement)")
    args = ap.parse_args()

    target = date.fromisoformat(args.date) if args.date else utc_now().date()
    now_utc = utc_now()
    partial_end = now_utc - timedelta(minutes=args.delay_min)
    # Si la date target est passee, partial_end = end of day
    if target < now_utc.date():
        partial_end_str = None  # full day
    else:
        partial_end_str = partial_end.strftime("%H:%M")

    t_start = time.time()
    print("=" * 70)
    print(f" LIVE PIPELINE — {target} (UTC now={now_utc:%H:%M})")
    print(f" partial_end_utc={partial_end_str or 'FULL_DAY'}")
    print(f" symbols={args.symbols}")
    print("=" * 70)

    success_steps = []
    failed_steps = []

    # 1. Download Databento
    if not args.skip_download:
        cmd = [
            PYTHON_EXE, "-X", "utf8",
            str(ROOT / "CORE" / "databento_download.py"),
            "--symbols", *args.symbols,
            "--schemas", "ohlcv-1m", "trades",
            "--date", target.isoformat(),
        ]
        if partial_end_str:
            # FIX intra-day pipeline (29/04 backlog) : sans --force, le download
            # SKIP si .dbn.zst existe deja → fichier OHLCV gele a la 1re iter,
            # bot tradait sur bar vieille de 2h+ (incident 28/04 17:17).
            # En mode partial (intra-day live), on doit forcer le refresh.
            cmd.extend(["--partial-end", partial_end_str, "--force"])
        # FIX 11/05 code-reviewer R4 : snapshot mtime AVANT download pour
        # detecter les fichiers qui n'ont PAS ete refresh (silent skip / EMPTY).
        # Incident 11/05/2026 : ohlcv-1m ES.c.0 stuck 2h+ sans aucune erreur log.
        from datetime import datetime as _dt2, timezone as _tz2
        t_start_dl = _dt2.now(_tz2.utc).timestamp()
        ok = run_cmd(cmd, "DOWNLOAD")
        (success_steps if ok else failed_steps).append("DOWNLOAD")
        if not ok:
            print("\n[FATAL] Download failed — abort pipeline")
            sys.exit(1)
        # Post-check : pour CHAQUE (symbol, schema), verifier que le DBN.zst
        # a bien ete refresh (mtime > t_start_dl) si on est en partial mode.
        if partial_end_str:
            stale_files = []
            # 12/05 FIX FAUX POSITIF : transition jour UTC (00:00-00:30) =
            # DBN day=N pas encore telecharge par Databento (data dispo API ~00:15-00:30).
            # Skip emit "missing" pendant cette fenetre = comportement NORMAL.
            # Sans ce fix : 38+ emit DOWNLOAD_STALE_POST_FETCH CRITIQUE chaque midnight UTC.
            _now_utc = _dt2.now(_tz2.utc)
            _grace_window = (_now_utc.hour == 0 and _now_utc.minute < 30)
            for sym in args.symbols:
                for sch in ("ohlcv-1m", "trades"):
                    fp = (DBN_ROOT / sch / f"symbol={sym}" /
                          f"year={target.year}" / f"month={target.month}" /
                          f"day={target.day}" / "data.dbn.zst")
                    if not fp.exists():
                        # Pendant grace transition jour UTC : SKIP emit (normal)
                        if not _grace_window:
                            stale_files.append((sch, sym, "missing"))
                        continue
                    age_since_dl = t_start_dl - fp.stat().st_mtime
                    # Si DBN plus vieux que le start du download = pas refresh
                    if age_since_dl > 60:  # tolerance 60s
                        age_min = age_since_dl / 60
                        stale_files.append((sch, sym, f"stale_{age_min:.1f}min"))
            if stale_files:
                print(f"\n[WARN] Post-DL : {len(stale_files)} fichier(s) NON refresh "
                      f"(silent skip Databento) :")
                for sch, sym, reason in stale_files:
                    print(f"  - {sch:10s} {sym:8s} {reason}")
                    # Emit pour visibilite dashboard "Erreurs recentes"
                    _emit("DOWNLOAD_STALE_POST_FETCH",
                          schema=sch, symbol=sym, reason=reason)
                # Pas FATAL : on continue (build_v4 utilisera last bars dispo)
                # mais signal visible dans log pour audit J+1.

    # 2. Convert trades dbn.zst -> parquet
    ok = convert_trades_to_parquet(target, args.symbols)
    (success_steps if ok else failed_steps).append("CONVERT_TRADES")

    # 3. Build V4
    cmd = [
        PYTHON_EXE, "-X", "utf8",
        str(ROOT / "CORE" / "build_dataset_v4_dmp_databento.py"),
        "--test-day", target.isoformat(),
        "--use-mq-lite",
        "--symbols", *args.symbols_short,
    ]
    ok = run_cmd(cmd, "BUILD_V4")
    (success_steps if ok else failed_steps).append("BUILD_V4")
    if not ok:
        print("\n[FATAL] V4 failed — abort pipeline")
        sys.exit(2)

    # 4. Phase B (sauf si skip)
    if not args.skip_phase_b:
        month_str = f"{target.year}-{target.month:02d}"
        cmd = [
            PYTHON_EXE, "-X", "utf8",
            str(ROOT / "CORE" / "build_dataset_v4_phase_b.py"),
            "--month", month_str,
            "--symbols", *args.symbols_short,
        ]
        ok = run_cmd(cmd, "PHASE_B")
        (success_steps if ok else failed_steps).append("PHASE_B")

    # Bilan
    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print(f" BILAN — total {elapsed:.1f}s")
    print(f"  OK     : {', '.join(success_steps) if success_steps else '(none)'}")
    print(f"  FAILED : {', '.join(failed_steps) if failed_steps else '(none)'}")
    print("=" * 70)

    sys.exit(0 if not failed_steps else 3)


if __name__ == "__main__":
    main()
