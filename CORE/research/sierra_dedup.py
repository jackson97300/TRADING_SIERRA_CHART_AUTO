"""sierra_dedup.py - Dedup Sierra JSONL enriched (Prop 1B + Prop 2 ATOMIQUE).

Suite review code-reviewer (commit f71d63a) :
- Prop 1B + Prop 2 doivent etre ATOMIQUES (round = input dedup)
- Primary key = (sym, ts_event_minute, is_bar_closed) avec
  completeness-aware tiebreak (preserve OHLCV complet vs intermediate)
- Loggue BAR_DUPLICATE_DETECTED ALERTE chaque dedup (anti masquage bug DMP)

Usage :
    python -X utf8 CORE/research/sierra_dedup.py \\
        --input DATA/_sierra_20260611.jsonl \\
        --output DATA/_sierra_20260611_dedup.jsonl \\
        --skip-before-idx 1028

Etape 0 (1A) : extraction runs propres (POST idx 1028 dans le cas 11/06 NQ)
    + Etape 2 dedup atomique = dataset propre pour Phase 4 v3.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


# Champs critiques pour completeness score (presence non-None)
COMPLETENESS_FIELDS = [
    "high", "low", "open", "close", "volume",
    "delta_bar", "buy_vol", "sell_vol", "ask_pct",
]


def completeness_score(bar: dict) -> int:
    """Score = nb de champs critiques avec valeur non-None."""
    score = 0
    for f in COMPLETENESS_FIELDS:
        v = bar.get(f)
        if v is None:
            continue
        if isinstance(v, float) and v != v:
            continue
        score += 1
    return score


def is_bar_closed(bar: dict) -> bool:
    """Heuristique : bar close si OHLCV tous non-None et non-NaN."""
    for f in ("high", "low", "open", "close", "volume"):
        v = bar.get(f)
        if v is None:
            return False
        if isinstance(v, float) and v != v:
            return False
    return True


def round_ts_to_minute(ts_ms: int) -> int:
    """ROUND (nearest) timestamp ms epoch -> minute precise.

    FIX Jackson 11/06 : FLOOR collisionnait sur 31% des bars Sierra qui
    ferment a HH:MM:59 (alors que les bars normales sont a HH:MM:00).
    Avec FLOOR : 16:44:00 et 16:44:59 collisionnent sur 16:44 -> 16:45 vide.
    Avec ROUND : 16:44:59 -> 16:45:00 -> capture correctement la bar.

    Validation empirique : 200 bars NQ analysees 11/06, distribution
    {:00 = 137 (68%), :59 = 62 (31%)}. Sans fix, dedup perd ~31% des bars
    en compression artificielle.
    """
    return round(ts_ms / 60_000) * 60_000


def dedup_jsonl(input_path: Path, output_path: Path,
                 skip_before_idx: int = 0,
                 emit_log: bool = True) -> dict:
    """Dedup Sierra JSONL avec primary key completeness-aware.

    FIX MUST-HAVE #9 review : emit_log=True par defaut declenche logging_v2
    `BAR_DUPLICATE_DETECTED` ALERTE pour chaque dup detectee (anti-Pattern 11 :
    sans ca, dedup silencieux masquerait bug DMP futur).
    Mettre False pour tests/scripts standalone (evite dep logging_v2).
    """
    stats = defaultdict(int)
    best_bar: dict = {}
    # Setup logging_v2 si emit_log
    _log = None
    if emit_log:
        try:
            from CORE.logging_v2 import get_logger
            _log = get_logger("sierra_dedup", process="dedup_cli")
        except Exception:  # noqa: BLE001
            _log = None

    with open(input_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            stats["n_input"] += 1
            if i < skip_before_idx:
                stats["n_skip"] += 1
                continue
            bar = json.loads(line)
            sym = bar.get("sym", "?")
            ts = bar.get("ts")
            if ts is None:
                stats["n_no_ts"] += 1
                continue
            ts_min = round_ts_to_minute(int(ts))
            closed = is_bar_closed(bar)
            bar["ts_event_minute"] = ts_min
            bar["is_bar_closed"] = closed
            bar["_dedup_completeness"] = completeness_score(bar)

            # Primary key initial = (sym, ts_minute, closed_status)
            key = (sym, ts_min, closed)
            existing = best_bar.get(key)
            if existing is None:
                best_bar[key] = bar
                stats["n_unique"] += 1
            else:
                if bar["_dedup_completeness"] > existing["_dedup_completeness"]:
                    best_bar[key] = bar
                    stats["n_dup_replaced_more_complete"] += 1
                else:
                    stats["n_dup_dropped"] += 1
                stats["n_dup_detected"] += 1
                # FIX MUST-HAVE #9 review : log ALERTE chaque dup (anti-Pattern 11)
                if _log is not None:
                    try:
                        _log.emit("BAR_DUPLICATE_DETECTED",
                                   sym=sym, ts_min=ts_min,
                                   completeness_existing=existing["_dedup_completeness"],
                                   completeness_new=bar["_dedup_completeness"])
                    except Exception:  # noqa: BLE001
                        pass

    # Etape 2 : pour chaque (sym, ts_min), preferer is_closed=True
    final: dict = {}
    for (sym, ts_min, closed), bar in best_bar.items():
        key2 = (sym, ts_min)
        existing = final.get(key2)
        if existing is None:
            final[key2] = bar
        else:
            if closed and not existing.get("is_bar_closed", False):
                final[key2] = bar
                stats["n_closed_wins_over_open"] += 1
            elif (closed == existing.get("is_bar_closed", False)
                   and bar["_dedup_completeness"] > existing["_dedup_completeness"]):
                final[key2] = bar
                stats["n_better_completeness"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for key2 in sorted(final.keys()):
            bar = final[key2]
            f.write(json.dumps(bar, separators=(",", ":"), default=str) + "\n")
            stats["n_output"] += 1

    return dict(stats)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-before-idx", type=int, default=0)
    args = parser.parse_args()

    stats = dedup_jsonl(args.input, args.output, args.skip_before_idx)
    print("=== Dedup stats ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:38s} = {v}")
    print(f"\nInput  -> {stats['n_input']} bars")
    print(f"Skip   -> {stats.get('n_skip', 0)} bars (pre-deploy)")
    print(f"Dups   -> {stats['n_dup_detected']} detected")
    print(f"Output -> {stats['n_output']} unique bars")
    ratio = stats['n_input'] / max(stats['n_output'], 1)
    print(f"Ratio  -> {ratio:.2f}x compression")


if __name__ == "__main__":
    main()
