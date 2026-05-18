"""Diff features bar LIVE enricher (toutes 60s) vs V4 enriched parquet (5min).

Jackson 19/05 priorite absolue : "ON A TOUTE LES CODE ET FORMULE - PROPAGE
LES FEATURES BN ABSENTES dans V4 enriched parquet".

Strategy :
1. Read bar LIVE NQ (DATA/live_enriched/NQ/20260518_NQ.jsonl last line)
2. Read 1 row V4 enriched NQ parquet (DATA/datasets/v4_enriched/symbol=NQ.c.0)
3. Diff : keys present in LIVE but absent (ou null partout) in V4

Output : listing categorise des features manquantes
- BN flag features (bar_color_up/dn, bar_long_*, bar_edge_*)
- BN distance features (dist_ext_*)
- BN zone features (n_*_active, n_*_cluster, dist_*_nearest_pct)
- Autres

Usage : python -X utf8 tools/diff_live_vs_v4_features.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

LIVE_NQ = Path("C:/Users/jacks/AppData/Local/Temp/last_nq.json")
V4_NQ = Path("DATA/V4_TEMP/NQ_5months_combined.parquet")


def categorize(field: str) -> str:
    f = field.lower()
    if any(k in f for k in ["bar_color", "bar_long", "bar_edge"]):
        return "BN_BAR_FLAG"
    if "dist_ext_" in f:
        return "BN_EXT_DISTANCE"
    if any(k in f for k in ["color_up", "color_dn"]):
        return "BN_COLOR_ZONE"
    if any(k in f for k in ["edge_buy", "edge_sell"]):
        return "BN_EDGE_ZONE"
    if any(k in f for k in ["trapped_buy", "trapped_sell", "trapped_buyers", "trapped_sellers"]):
        return "BN_TRAPPED"
    if any(k in f for k in ["absorb", "stack"]):
        return "BN_ABSORB_STACK"
    if "delta_div" in f:
        return "BN_DELTA_DIV"
    if any(k in f for k in ["big_ask", "big_bid", "n_big"]):
        return "BN_BIG_ORDERS"
    if "cluster" in f:
        return "BN_CLUSTER"
    if any(k in f for k in ["spike", "swing"]):
        return "STRUCTURE"
    if "naked_poc" in f:
        return "STRUCTURE_NAKED_POC"
    if "vwap" in f:
        return "VWAP"
    if any(k in f for k in ["vpoc", "vah", "val"]):
        return "VOLUME_PROFILE"
    if any(k in f for k in ["mq_", "gex_", "blind_"]):
        return "MENTHORQ"
    return "OTHER"


def main() -> int:
    if not LIVE_NQ.exists():
        print(f"ERR : {LIVE_NQ} absent")
        return 1
    if not V4_NQ.exists():
        print(f"ERR : {V4_NQ} absent")
        return 1

    live = json.loads(LIVE_NQ.read_text().strip())
    print(f"LIVE bar : {len(live)} fields, ts={live.get('ts_event_iso')}")

    df = pd.read_parquet(V4_NQ)
    v4_cols = set(df.columns)
    print(f"V4 parquet : {len(v4_cols)} columns, rows={len(df)}")

    live_keys = set(live.keys())
    in_both = live_keys & v4_cols
    only_live = live_keys - v4_cols
    only_v4 = v4_cols - live_keys

    print(f"\n--- Diff ---")
    print(f"  In both         : {len(in_both)}")
    print(f"  ONLY LIVE (manquant V4) : {len(only_live)}")
    print(f"  ONLY V4 (calcule par pipeline) : {len(only_v4)}")

    # Categoriser ONLY LIVE
    by_cat: dict[str, list[str]] = {}
    for k in sorted(only_live):
        cat = categorize(k)
        by_cat.setdefault(cat, []).append(k)

    print(f"\n=== FEATURES PRESENTES EN LIVE MAIS ABSENTES DE V4 (PROPAGATION NEEDED) ===")
    for cat in sorted(by_cat):
        fields = by_cat[cat]
        print(f"\n  [{cat}] ({len(fields)} fields)")
        for f in fields:
            v = live.get(f)
            print(f"    {f:50s}  example_value = {v}")

    # Pour chaque "in both", check si V4 est NULL partout (= present mais inutilise)
    print(f"\n=== FEATURES IN BOTH MAIS NULL PARTOUT EN V4 (dead) ===")
    null_in_v4 = []
    sample = df.tail(1000)  # last 1000 bars
    for k in in_both:
        if categorize(k) in ("OTHER",):
            continue
        if k not in df.columns:
            continue
        series = sample[k]
        n_null = series.isnull().sum()
        if n_null >= len(sample) * 0.95:  # 95%+ null
            null_in_v4.append((k, n_null, len(sample)))
    null_in_v4.sort(key=lambda x: -x[1])
    for k, n_null, n_total in null_in_v4[:30]:
        print(f"    {k:50s}  {n_null}/{n_total} null  ({n_null / n_total * 100:.0f}%)")

    print(f"\n=== Bilan propagation needed ===")
    print(f"  Total features a propager = {len(only_live)} (manquantes) + {len(null_in_v4)} (presentes mais null)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
