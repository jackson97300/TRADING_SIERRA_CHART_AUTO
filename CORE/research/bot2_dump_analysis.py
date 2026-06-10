"""bot2_dump_analysis.py — Analyse pourquoi Bot 2 BN V4 ne capte pas les dumps Asia.

Verifie sur 5/05 et 12/05 (dumps Asia) si :
1. Les conditions BN V4 SHORT etaient remplies AVANT le dump
2. Quel gate (open_window, trend_recent, levels, density, edge) bloque
3. Combien de bars avant le dump auraient pu etre setup
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v4_engine import BNV4Params
from CORE.research.bot2_setup_counter import count_setups_vectorized


def main():
    df = pd.read_parquet(ROOT / 'DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=05/data.parquet')
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"])

    # Dumps a etudier
    dumps = [
        ("2026-05-05 00:00", "2026-05-05 01:00"),
        ("2026-05-12 00:00", "2026-05-12 01:30"),
    ]

    configs = {
        "A++_strict": BNV4Params(grade_min="A++", require_open_window=True,
                                  require_long_trend_aligned=True),
        "A++_no_window": BNV4Params(grade_min="A++", require_open_window=False,
                                     require_long_trend_aligned=True),
        "A_no_window": BNV4Params(grade_min="A", require_open_window=False,
                                   require_long_trend_aligned=True),
        "B_no_filter": BNV4Params(grade_min="B", require_open_window=False,
                                   require_long_trend_aligned=False),
    }

    results = []
    for ts_start, ts_end in dumps:
        ts_start = pd.Timestamp(ts_start, tz="UTC")
        ts_end = pd.Timestamp(ts_end, tz="UTC")
        mask_window = (df["ts_event"] >= ts_start - pd.Timedelta(hours=4)) & \
                       (df["ts_event"] <= ts_end + pd.Timedelta(hours=1))
        df_window = df[mask_window].reset_index(drop=True)
        if len(df_window) < 50:
            continue
        print(f"\n=== DUMP {ts_start} -> {ts_end} ===")
        print(f"  Window bars: {len(df_window)}")
        ts_dump_start_idx = df_window[df_window["ts_event"] >= ts_start].index[0] if (df_window["ts_event"] >= ts_start).any() else None
        close_pre = df_window.iloc[max(0, ts_dump_start_idx - 5)]["close"]
        close_post = df_window[df_window["ts_event"] <= ts_end]["close"].min()
        print(f"  Move: {close_pre:.1f} -> {close_post:.1f} = {close_post - close_pre:+.1f} pts")

        for name, params in configs.items():
            # Detection SHORT
            setup_mask, stats = count_setups_vectorized(df_window, params, "short")
            n_in_window = int(setup_mask.sum())
            # Avant le dump
            mask_before = df_window["ts_event"] <= ts_start
            n_before_dump = int((setup_mask & mask_before.values).sum())
            print(f"  {name} SHORT:")
            print(f"    funnel: open={stats['n_open_ok']} trend_recent={stats['n_trend_recent_ok']} "
                  f"trend_long={stats['n_trend_long_ok']} levels={stats['n_levels_ok']} "
                  f"density={stats['n_density_ok']} edge={stats['n_edge_ok']}")
            print(f"    setups: {n_in_window} (avant dump: {n_before_dump})")
            results.append({
                "dump_start": str(ts_start),
                "config": name,
                "direction": "short",
                "n_setups_in_window": n_in_window,
                "n_setups_before_dump": n_before_dump,
                "move_pts": float(close_post - close_pre),
                "funnel": stats,
            })

    out = ROOT / "LOGS/bot2_research/dump_analysis.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
