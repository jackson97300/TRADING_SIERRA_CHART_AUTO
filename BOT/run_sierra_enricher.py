r"""run_sierra_enricher.py — Service wrapper Phase 4.2 dual-run Sierra.

Phase 4.2 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s5.

Tourne EN PARALLELE de l'enricher Databento actuel :
  - Lit les bars Sierra DMP JSONL via SierraLiveReader (incremental tail).
  - Pour chaque NOUVELLE bar, appelle SierraPipelineOrchestrator.enrich_bar().
  - Ecrit dans DATA/live_enriched/sierra/{symbol}/{date}.jsonl (append-only).
  - **NE TOUCHE PAS** DATA/live_enriched/databento/ (Databento enricher existant).

Architecture dual-run (Phase 4.2-4.4) :
  Sierra DMP JSONL                       Databento Live
       |                                       |
       v                                       v
  SierraLiveReader                       enricher_chain.py
       |                                       |
       v                                       v
  SierraPipelineOrchestrator             compose_enriched_payload
       |                                       |
       v                                       v
  live_enriched/sierra/*.jsonl           live_enriched/databento/*.jsonl
                       \                       /
                        \                     /
                         v                   v
                     Phase 4.3 convergence audit
                     (compare features > 95%)

Usage :
  # Live (default) - tail JSONL Sierra et enrich en continu
  python -X utf8 BOT/run_sierra_enricher.py --symbol NQ

  # Batch (1-shot) - traiter un fichier JSONL Sierra deja existant
  python -X utf8 BOT/run_sierra_enricher.py --symbol NQ \\
      --batch DATA/NQ/20260608_NQ.jsonl --output /tmp/sierra_enriched.jsonl

  # Mode dry-run (compute mais pas d'ecriture, debug)
  python -X utf8 BOT/run_sierra_enricher.py --symbol NQ --dry-run

CLI args :
  --symbol            : "ES" / "NQ" / "MGC" (required)
  --output-dir        : repertoire output (default DATA/live_enriched/sierra)
  --batch FILE        : mode batch sur 1 fichier JSONL (skip live tail)
  --output FILE       : output explicite (mode batch only)
  --poll-interval     : secondes entre polls live (default 10)
  --window-bars       : SierraLiveReader window (default 480)
  --dry-run           : compute mais pas d'ecriture
  --strict            : fail-loud si fichier Sierra absent (default True)

Anti-patterns evites :
  - FAIL LOUD si symbol non supporte (raise ValueError)
  - NaN propre cold-start (sierra_pipeline gere)
  - Atomic write (.tmp + rename) pour eviter JSONL corrompu si crash
  - Graceful shutdown (SIGTERM + SIGINT) -> flush buffer + exit propre

Auteur : MIA Trading V2 (Phase 4.2 Sierra Migration)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add CORE to sys.path pour imports
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

import pandas as pd  # noqa: E402

from CORE.sierra_live_io import SierraLiveReader  # noqa: E402
from CORE.sierra_pipeline import SierraPipelineOrchestrator  # noqa: E402


# Graceful shutdown flag
_RUNNING: bool = True


def _signal_handler(signum, frame):
    """SIGTERM/SIGINT -> stop boucle live proprement."""
    global _RUNNING
    print(f"[signal] received {signum}, shutdown gracefully...", flush=True)
    _RUNNING = False


def _build_output_path(
    base_dir: Path,
    symbol: str,
    bar_ts_utc: datetime,
) -> Path:
    """Construit path output : base_dir/symbol/YYYYMMDD.jsonl."""
    date_str = bar_ts_utc.strftime("%Y%m%d")
    output_dir = base_dir / symbol.upper()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{date_str}_{symbol.upper()}_sierra_enriched.jsonl"


def _write_atomic(output_path: Path, line: str) -> None:
    """Append atomic ligne JSONL (rename .tmp -> final).

    Pour live mode : on append plutot que rename complet (perf).
    Mais on flush + fsync pour durability cross-crash.
    """
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _clean_value(v):
    """Convert numpy types + NaN -> Python native pour JSON standard."""
    import numpy as np

    if v is None:
        return None
    if isinstance(v, float):
        return None if (v != v) else v  # NaN -> None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if np.isnan(f) else f
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [_clean_value(x) for x in v.tolist()]
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {k: _clean_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in v]
    return v


def _serialize_payload(payload: dict) -> str:
    """Serialize payload dict en ligne JSONL JSON-standard.

    Convert numpy types + NaN -> Python native (None pour NaN).
    Output respect JSON standard (allow_nan=False compatible).
    """
    cleaned = _clean_value(payload)
    return json.dumps(cleaned, allow_nan=False, separators=(",", ":"),
                       default=str)


def run_batch_mode(
    symbol: str,
    batch_file: Path,
    output_file: Path,
    dry_run: bool = False,
) -> dict:
    """Mode batch : traite 1 fichier JSONL Sierra deja existant.

    Args:
        symbol : "ES" / "NQ" / "MGC"
        batch_file : path JSONL Sierra source
        output_file : path JSONL sortie enrichi
        dry_run : si True, compute mais pas d'ecriture

    Returns:
        dict stats : {bars_read, bars_enriched, bars_skipped, errors}.

    Raises:
        FileNotFoundError : si batch_file absent.
    """
    if not batch_file.exists():
        raise FileNotFoundError(f"Batch file not found : {batch_file}")

    pipeline = SierraPipelineOrchestrator(symbol=symbol)
    stats = {"bars_read": 0, "bars_enriched": 0, "bars_skipped": 0, "errors": 0}

    if not dry_run:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        # Truncate output si existant (batch mode = reset)
        output_file.write_text("", encoding="utf-8")

    with open(batch_file, "r", encoding="utf-8") as f_in:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            stats["bars_read"] += 1
            try:
                sierra_bar = json.loads(line)
                enriched = pipeline.enrich_bar(sierra_bar)
                stats["bars_enriched"] += 1
                if not dry_run:
                    out_line = _serialize_payload(enriched)
                    with open(output_file, "a", encoding="utf-8") as f_out:
                        f_out.write(out_line + "\n")
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                stats["errors"] += 1
                stats["bars_skipped"] += 1
                if stats["errors"] <= 5:  # log seulement les 5 premieres
                    print(f"[warn] bar skipped : {e}", flush=True)

    pipeline_stats = pipeline.get_stats()
    stats["pipeline"] = pipeline_stats
    return stats


def run_live_mode(
    symbol: str,
    output_dir: Path,
    poll_interval_sec: float = 10.0,
    window_bars: int = 480,
    dry_run: bool = False,
    strict: bool = True,
    max_iterations: Optional[int] = None,
) -> dict:
    """Mode live : tail JSONL Sierra et enrich en continu.

    Args:
        symbol : "ES" / "NQ" / "MGC"
        output_dir : repertoire base output (sub-dir par symbol)
        poll_interval_sec : delai entre lectures incrementales
        window_bars : SierraLiveReader rolling window
        dry_run : si True, compute mais pas d'ecriture
        strict : SierraLiveReader strict (fail si fichier absent)
        max_iterations : limite boucle (None = infini, utile tests)

    Returns:
        dict stats orchestrateur final.
    """
    reader = SierraLiveReader(
        symbol=symbol,
        window_bars=window_bars,
        strict=strict,
    )
    pipeline = SierraPipelineOrchestrator(symbol=symbol)
    seen_ts: set = set()
    stats = {"polls": 0, "bars_enriched_total": 0, "errors": 0}

    iteration = 0
    while _RUNNING:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1
        stats["polls"] += 1

        try:
            df = reader.load_rolling_window()
        except Exception as e:
            stats["errors"] += 1
            print(f"[error] reader.load_rolling_window failed : {e}", flush=True)
            time.sleep(poll_interval_sec)
            continue

        if df is None or len(df) == 0:
            time.sleep(poll_interval_sec)
            continue

        # Process nouvelles bars (pas vues)
        new_bars_count = 0
        for _, row in df.iterrows():
            ts = row.get("ts")
            if ts is None or ts in seen_ts:
                continue
            seen_ts.add(ts)

            sierra_bar = row.to_dict()
            try:
                enriched = pipeline.enrich_bar(sierra_bar)
            except ValueError as e:
                stats["errors"] += 1
                print(f"[warn] enrich_bar failed for ts={ts} : {e}", flush=True)
                continue

            new_bars_count += 1
            stats["bars_enriched_total"] += 1

            if not dry_run:
                bar_ts_utc = pipeline._extract_ts_utc(sierra_bar)
                output_path = _build_output_path(output_dir, symbol, bar_ts_utc)
                line = _serialize_payload(enriched)
                _write_atomic(output_path, line)

        if new_bars_count > 0:
            print(
                f"[live] poll {stats['polls']} : "
                f"{new_bars_count} new bars enriched "
                f"(total {stats['bars_enriched_total']})",
                flush=True,
            )

        time.sleep(poll_interval_sec)

    stats["pipeline"] = pipeline.get_stats()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Phase 4.2 Sierra Enricher dual-run wrapper"
    )
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ", "MGC"])
    parser.add_argument("--output-dir", type=Path,
                         default=Path("DATA/live_enriched/sierra"))
    parser.add_argument("--batch", type=Path, default=None,
                         help="Mode batch sur 1 fichier JSONL (skip live)")
    parser.add_argument("--output", type=Path, default=None,
                         help="Output explicite (batch mode only)")
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--window-bars", type=int, default=480)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--max-iterations", type=int, default=None,
                         help="Limite boucle live (tests)")

    args = parser.parse_args()

    # Setup signal handlers (graceful shutdown live mode)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    print(f"[init] sierra_enricher symbol={args.symbol} "
          f"dry_run={args.dry_run}", flush=True)

    if args.batch is not None:
        # Mode batch
        if args.output is None:
            # Default : meme dir que batch, suffix _sierra_enriched
            args.output = args.batch.parent / (
                args.batch.stem + "_sierra_enriched.jsonl"
            )
        print(f"[batch] input={args.batch} output={args.output}", flush=True)
        stats = run_batch_mode(
            symbol=args.symbol,
            batch_file=args.batch,
            output_file=args.output,
            dry_run=args.dry_run,
        )
    else:
        # Mode live
        print(f"[live] output_dir={args.output_dir} "
              f"poll={args.poll_interval}s window={args.window_bars}",
              flush=True)
        stats = run_live_mode(
            symbol=args.symbol,
            output_dir=args.output_dir,
            poll_interval_sec=args.poll_interval,
            window_bars=args.window_bars,
            dry_run=args.dry_run,
            strict=args.strict,
            max_iterations=args.max_iterations,
        )

    print(f"[done] stats : {json.dumps(stats, default=str)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
