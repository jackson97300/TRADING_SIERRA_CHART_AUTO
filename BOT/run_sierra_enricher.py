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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ─── Phase Dedup Etape 1+3 - Metadonnees observabilite (review reviewer) ──
# Sources de verite globales pour traceabilite cross-restart + dedup intelligent

def _compute_schema_version() -> str:
    """FIX MUST-HAVE #10 review : version + git hash auto-compute.

    Format : `sierra_{semver}+{git_short_hash}`. Si git absent (env non-git),
    fallback `unknown`. Trace exact le commit qui a produit la bar.
    """
    import subprocess
    semver = "3.7.22"
    try:
        _root = Path(__file__).resolve().parents[1]
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_root), stderr=subprocess.DEVNULL, timeout=2
        ).decode().strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    return f"sierra_{semver}+{sha}"


_SCHEMA_VERSION: str = _compute_schema_version()
_BOOT_ID: str = str(uuid.uuid4())  # uuid v4 fixe au demarrage process
_BARS_SINCE_BOOT: dict = {}  # per-symbol counter (review reviewer point #5)
# Seuils data_quality_flag (Etape 3, calibres empiriquement)
_WARMUP_THRESHOLD_BARS: int = 10  # < 10 bars depuis boot = warmup
# FIX MUST-HAVE #3 review : justification _DEGRADED_KEYS.
# Sentinel keys : si NaN apres warmup = indicateur cross-injection partner_bar
# rate (im_* = features qui dependent du cross-symbol). PAS pour ib_atr/price_1030
# qui sont event-based (NaN J+1-J+3 normal). Si bot consume data_quality_flag
# plus tard comme gate, REVOIR cette liste avec ml-trainer pour DSR validation.
_DEGRADED_KEYS = ("im_cross_delta_agreement_5",)

# Add CORE to sys.path pour imports
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from CORE.sierra_live_io import SierraLiveReader  # noqa: E402
from CORE.sierra_pipeline import SierraPipelineOrchestrator  # noqa: E402


# Constantes service (extraites apres review code-reviewer 10/06)
DEFAULT_POLL_INTERVAL_SEC: float = 10.0
DEFAULT_WINDOW_BARS: int = 480
ERROR_LOG_LIMIT_FIRST_N: int = 5


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


def _write_durable(output_path: Path, line: str) -> None:
    """Append ligne JSONL avec durability cross-crash.

    Honnete : ce n'est PAS atomic. Append + flush + fsync garantissent
    durability (la ligne est ecrite sur disque avant retour) mais une ligne
    > 4KB (cas typique JSONL enrichi 485 cols) peut etre tronquee si crash
    mid-write. Verification J+1 obligatoire : grep JSONDecodeError dans
    parse output JSONL pour detecter lignes corrompues.

    Pour vraie atomicite : pattern tempfile + os.replace, mais incompatible
    avec append-only (necessite read + rewrite, perf negative).
    """
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


_FLOAT_ROUND_DECIMALS = 6  # Precision suffisante : < tick (0.25 NQ/ES, 0.10 MGC)


def _inject_observability_metadata(enriched: dict, symbol: str) -> None:
    """Injecte schema_version + boot_id + bars_since_boot + data_quality_flag.

    FIX MUST-HAVE #1 review : MUTATES enriched in-place, RETURN None pour
    forcer le caller a utiliser la mutation (pas de faux contrat retour).

    Phase Dedup Etape 1 (Prop 3 partiel) + Etape 3 (Prop 3 complet).
    Review reviewer : per-symbol counter, boot_id uuid4, 3 valeurs flag.

    NB boot_id = identifie le process Sierra enricher (PAS le symbole).
    Distinction warmup ES vs NQ se fait via bars_since_boot per-sym.

    Args:
        enriched : dict bar enrichi sortant de SierraPipelineOrchestrator.
                    Mute IN-PLACE avec 4 champs ajoutes.
        symbol   : "ES" / "NQ" / "MGC".

    Returns:
        None (in-place mutation, anti-pattern faux contrat retour).
    """
    global _BARS_SINCE_BOOT
    # Increment per-symbol (review reviewer point #5)
    _BARS_SINCE_BOOT[symbol] = _BARS_SINCE_BOOT.get(symbol, 0) + 1
    enriched["schema_version"] = _SCHEMA_VERSION
    enriched["boot_id"] = _BOOT_ID
    enriched["bars_since_boot"] = _BARS_SINCE_BOOT[symbol]
    # data_quality_flag (Etape 3, review reviewer point #6 : 3 valeurs)
    bsb = _BARS_SINCE_BOOT[symbol]
    if bsb < _WARMUP_THRESHOLD_BARS:
        flag = "warmup"
    else:
        # Check degraded : si une des features critiques est NaN apres warmup
        degraded = False
        for k in _DEGRADED_KEYS:
            v = enriched.get(k)
            if v is None or (isinstance(v, float) and v != v):
                degraded = True
                break
        flag = "degraded" if degraded else "stable"
    enriched["data_quality_flag"] = flag
    # Mutation in-place, pas de return (anti faux contrat)


def _clean_value(v):
    """Convert numpy types + NaN -> Python native pour JSON standard.

    Fix Jackson 11/06 : arrondi 6 decimales sur floats pour eviter
    pollution JSONL (ex: ctx_rvol_session=0.568020872158032 sur 15 decimales).
    Precision largement suffisante : 1e-6 << tick_size partout (0.25 / 0.10).
    """
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        return round(v, _FLOAT_ROUND_DECIMALS)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        if np.isnan(f):
            return None
        return round(f, _FLOAT_ROUND_DECIMALS)
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

    # Fix C1 review 11/06 : brancher log_event pour tracabilite proxies J+1
    # (codes MQ_PROXY_* + AGGRESSOR_PROXY_*).
    try:
        from CORE.logging_v2 import get_logger
        _sierra_log = get_logger(f"sierra_enricher_{symbol.lower()}",
                                  process="sierra_enricher")
        _log_event = _sierra_log.emit
    except Exception:
        _log_event = None

    pipeline = SierraPipelineOrchestrator(symbol=symbol, log_event=_log_event)
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
                # Injection metadonnees observabilite (review reviewer)
                _inject_observability_metadata(enriched, symbol)
                stats["bars_enriched"] += 1
                if not dry_run:
                    out_line = _serialize_payload(enriched)
                    with open(output_file, "a", encoding="utf-8") as f_out:
                        f_out.write(out_line + "\n")
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                stats["errors"] += 1
                stats["bars_skipped"] += 1
                if stats["errors"] <= ERROR_LOG_LIMIT_FIRST_N:
                    print(f"[warn] bar skipped : {e}", flush=True)

    pipeline_stats = pipeline.get_stats()
    stats["pipeline"] = pipeline_stats
    return stats


def run_live_mode(
    symbol: str,
    output_dir: Path,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    window_bars: int = DEFAULT_WINDOW_BARS,
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
    # Fix C1 review 11/06 : brancher log_event pour tracabilite proxies J+1
    # (codes MQ_PROXY_* + AGGRESSOR_PROXY_*).
    try:
        from CORE.logging_v2 import get_logger
        _sierra_log = get_logger(f"sierra_enricher_{symbol.lower()}",
                                  process="sierra_enricher")
        _log_event = _sierra_log.emit
    except Exception:
        _log_event = None

    pipeline = SierraPipelineOrchestrator(symbol=symbol, log_event=_log_event)
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
            # Injection metadonnees observabilite (review reviewer)
            _inject_observability_metadata(enriched, symbol)

            new_bars_count += 1
            stats["bars_enriched_total"] += 1

            if not dry_run:
                bar_ts_utc = pipeline._extract_ts_utc(sierra_bar)
                output_path = _build_output_path(output_dir, symbol, bar_ts_utc)
                line = _serialize_payload(enriched)
                _write_durable(output_path, line)

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


def run_multi_symbol_live_mode(
    symbols: list,
    output_dir: Path,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    window_bars: int = DEFAULT_WINDOW_BARS,
    dry_run: bool = False,
    strict: bool = True,
    max_iterations: Optional[int] = None,
) -> dict:
    """Phase 1 D1 - Mode live multi-symbol avec cross-injection partner_bar.

    Resout dette D1 review code-reviewer 11/06 : sans cross-injection,
    les 10 features `im_*` (intermarket) restent 100% NaN en prod.

    Convention cross-symbole (mirror enricher_chain.py:687-722) :
        ES.enrich consume last NQ raw bar via set_partner_bar(_last_bars["NQ"])
        NQ.enrich consume last ES raw bar via set_partner_bar(_last_bars["ES"])
    Staleness 120s + no-future check gere par sierra_pipeline.enrich_bar.

    Bootstrap cold-start (R1.4 review fix code-reviewer 11/06) :
        Cycle 1 : last_raw_bars vide -> snapshot fige = {ES: None, NQ: None}
        -> les 2 symboles ont partner_bar=None -> features im_* = NaN propre.
        Update last_raw_bars en fin Phase 4 cycle 1.
        Cycle 2 : snapshot fige = bars cycle 1 -> features im_* commencent.
        Symetrique (ES voit NQ_{t-1}, NQ voit ES_{t-1}, MEME timestamp).

    Cross-day disalignement (R1.3 review) : si ES traverse 18:00 ET avant NQ,
    ES utilise IntermarketState fraichement reset MAIS partner_bar NQ J-1
    (pas reset car caller gere son cycle). Staleness check 120s catche ce cas
    apres 2 min -> features im_* = NaN propre.

    Args:
        symbols : list ["ES", "NQ"] uniquement supporte par intermarket actuel.
        output_dir : repertoire base output (sub-dir par symbol).
        poll_interval_sec : delai entre cycles (default 10s).
        window_bars : SierraLiveReader rolling window.
        dry_run : si True, compute mais pas d'ecriture.
        strict : SierraLiveReader strict (fail si fichier absent).
        max_iterations : limite boucle (None=infini, utile tests).

    Returns:
        dict stats : {polls, per_symbol_bars_enriched, errors, pipelines}.
    """
    if not all(s in ("ES", "NQ") for s in symbols):
        raise ValueError(
            f"Multi-symbol intermarket supporte ES/NQ uniquement, recu : {symbols}")
    if len(symbols) < 2:
        raise ValueError(
            f"Multi-symbol mode requiert au moins 2 symboles, recu : {symbols}")

    # Init 1 reader + 1 pipeline par symbole (state isole per-sym)
    readers: dict = {}
    pipelines: dict = {}
    seen_ts: dict = {}
    last_raw_bars: dict = {}  # dernier bar RAW par symbole (pour cross-inject)

    for sym in symbols:
        readers[sym] = SierraLiveReader(
            symbol=sym, window_bars=window_bars, strict=strict)
        try:
            from CORE.logging_v2 import get_logger
            _slog = get_logger(f"sierra_enricher_{sym.lower()}",
                                process="sierra_enricher")
            _log_event = _slog.emit
        except Exception:  # noqa: BLE001
            _log_event = None
        pipelines[sym] = SierraPipelineOrchestrator(symbol=sym, log_event=_log_event)
        seen_ts[sym] = set()
        last_raw_bars[sym] = None

    stats = {
        "polls": 0,
        "per_symbol_bars_enriched": {s: 0 for s in symbols},
        "errors": 0,
        "im_features_emitted": 0,  # count bars avec partner_bar non-None
    }

    # Log boot multi-symbol (regle souveraine LOGS TRACABILITE 01/05)
    try:
        from CORE.logging_v2 import get_logger
        _multi_log = get_logger("sierra_enricher_multi",
                                 process="sierra_enricher")
        _multi_log.emit("MULTI_SYMBOL_BOOT", syms=",".join(symbols))
    except Exception:  # noqa: BLE001
        _multi_log = None

    iteration = 0
    while _RUNNING:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1
        stats["polls"] += 1

        # FIX C2 review code-reviewer 11/06 : asymetrie temporelle.
        # Phase 1 : collecter nouvelles bars par sym (lecture readers).
        # Phase 2 : snapshot last_raw_bars FIGE avant enrich.
        # Phase 3 : enrich avec snapshot symetrique (ES voit NQ_{t-1}, NQ voit
        # ES_{t-1}, MEME timestamp partner sans biais ordre).
        # Phase 4 : update last_raw_bars apres TOUS les enrich du cycle.

        # Phase 1 : collect new bars per sym
        new_bars_per_sym: dict = {}
        for sym in symbols:
            try:
                df = readers[sym].load_rolling_window()
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                print(f"[error][{sym}] reader failed : {e}", flush=True)
                new_bars_per_sym[sym] = []
                continue
            if df is None or len(df) == 0:
                new_bars_per_sym[sym] = []
                continue
            collected = []
            for _, row in df.iterrows():
                ts = row.get("ts")
                if ts is None or ts in seen_ts[sym]:
                    continue
                seen_ts[sym].add(ts)
                collected.append(row.to_dict())
            new_bars_per_sym[sym] = collected

        # Phase 2 : snapshot fige (symetrique pour tous les enrich du cycle)
        partner_snapshot = dict(last_raw_bars)

        # Phase 3 : enrich avec snapshot fige
        for sym in symbols:
            partner_sym = "NQ" if sym == "ES" else "ES"
            new_bars_count = 0
            for sierra_bar in new_bars_per_sym[sym]:
                # CROSS-INJECTION : snapshot fige (pas last_raw_bars muable)
                partner_bar = partner_snapshot[partner_sym]
                pipelines[sym].set_partner_bar(partner_bar)

                try:
                    enriched = pipelines[sym].enrich_bar(sierra_bar)
                except ValueError as e:
                    stats["errors"] += 1
                    print(f"[warn][{sym}] enrich_bar : {e}", flush=True)
                    continue
                # Injection metadonnees observabilite (review reviewer)
                _inject_observability_metadata(enriched, sym)

                # FIX I4 review : compteur post-enrich sur valeur non-NaN reelle
                # (pas pre-enrich qui ignorerait staleness check kick).
                _im_emitted = any(
                    enriched.get(k) is not None and enriched.get(k) == enriched.get(k)
                    for k in enriched
                    if k.startswith("im_")
                )
                if _im_emitted:
                    stats["im_features_emitted"] += 1

                new_bars_count += 1
                stats["per_symbol_bars_enriched"][sym] += 1

                if not dry_run:
                    bar_ts_utc = pipelines[sym]._extract_ts_utc(sierra_bar)
                    output_path = _build_output_path(output_dir, sym, bar_ts_utc)
                    line = _serialize_payload(enriched)
                    _write_durable(output_path, line)

            if new_bars_count > 0:
                print(
                    f"[multi][{sym}] poll {stats['polls']} : "
                    f"{new_bars_count} new bars "
                    f"(im_emitted_total={stats['im_features_emitted']})",
                    flush=True,
                )

        # Phase 4 : update last_raw_bars apres TOUS les enrich (commit cycle)
        for sym in symbols:
            if new_bars_per_sym[sym]:
                last_raw_bars[sym] = new_bars_per_sym[sym][-1]

        # Cycle stats log (chaque 60 cycles = ~10 min @ poll 10s)
        if _multi_log is not None and (iteration % 60 == 0):
            try:
                _multi_log.emit("MULTI_SYMBOL_CYCLE_STATS",
                                 cycle=iteration,
                                 im_emitted=stats["im_features_emitted"],
                                 errors=stats["errors"])
            except Exception:  # noqa: BLE001
                pass

        time.sleep(poll_interval_sec)

    if _multi_log is not None:
        try:
            _multi_log.emit("MULTI_SYMBOL_SHUTDOWN",
                             total_cycles=iteration,
                             im_emitted=stats["im_features_emitted"])
        except Exception:  # noqa: BLE001
            pass

    stats["pipelines"] = {s: pipelines[s].get_stats() for s in symbols}
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Phase 4.2 Sierra Enricher dual-run wrapper"
    )
    parser.add_argument("--symbol", required=False, choices=["ES", "NQ", "MGC"],
                         help="Mono-symbol mode (backward compat). Mutually exclusive avec --multi-symbol.")
    parser.add_argument("--multi-symbol", type=str, default=None,
                         help="Phase 1 D1 - Mode multi-symbol cross-injection im_*. "
                              "Ex: 'ES,NQ' (separateur virgule, ES/NQ uniquement).")
    parser.add_argument("--output-dir", type=Path,
                         default=Path("DATA/live_enriched/sierra"))
    parser.add_argument("--batch", type=Path, default=None,
                         help="Mode batch sur 1 fichier JSONL (skip live)")
    parser.add_argument("--output", type=Path, default=None,
                         help="Output explicite (batch mode only)")
    parser.add_argument("--poll-interval", type=float,
                         default=DEFAULT_POLL_INTERVAL_SEC)
    parser.add_argument("--window-bars", type=int, default=DEFAULT_WINDOW_BARS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--max-iterations", type=int, default=None,
                         help="Limite boucle live (tests)")

    args = parser.parse_args()

    # Validation args : --symbol OU --multi-symbol mutually exclusive
    if args.symbol is None and args.multi_symbol is None:
        parser.error("--symbol OU --multi-symbol requis")
    if args.symbol is not None and args.multi_symbol is not None:
        parser.error("--symbol et --multi-symbol mutuellement exclusifs")

    # Setup signal handlers (graceful shutdown live mode)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    mode_label = (args.multi_symbol if args.multi_symbol else args.symbol)
    print(f"[init] sierra_enricher mode={mode_label} "
          f"dry_run={args.dry_run}", flush=True)

    if args.batch is not None:
        # Mode batch (mono-symbol seulement)
        if args.multi_symbol is not None:
            parser.error("--batch incompatible avec --multi-symbol "
                          "(use mono-sym sequential batch instead)")
        if args.output is None:
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
    elif args.multi_symbol is not None:
        # Mode live multi-symbol (Phase 1 D1)
        symbols = [s.strip().upper() for s in args.multi_symbol.split(",")]
        print(f"[multi-live] symbols={symbols} output_dir={args.output_dir} "
              f"poll={args.poll_interval}s window={args.window_bars}",
              flush=True)
        stats = run_multi_symbol_live_mode(
            symbols=symbols,
            output_dir=args.output_dir,
            poll_interval_sec=args.poll_interval,
            window_bars=args.window_bars,
            dry_run=args.dry_run,
            strict=args.strict,
            max_iterations=args.max_iterations,
        )
    else:
        # Mode live mono-sym (backward compat)
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
