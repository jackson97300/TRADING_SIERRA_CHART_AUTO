"""audit_v4_v5_columns.py — Inventaire colonnes parquet V4 enrichi pour dashboard."""
import sys, json, os
from pathlib import Path
try:
    import pyarrow.parquet as pq
    import pandas as pd
except ImportError as e:
    print(f"FAIL import: {e}")
    sys.exit(1)

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
V4 = ROOT / "DATA/datasets/v4_enriched"

# Lire le parquet V4 le plus recent (NQ ET ES)
for sym in ("NQ.c.0", "ES.c.0"):
    print(f"\n{'='*80}\n=== V4 enriched {sym} ===\n{'='*80}")
    pattern = V4 / f"symbol={sym}" / "year=2026" / "month=05" / "data.parquet"
    if not pattern.exists():
        print(f"  ABSENT : {pattern}")
        continue
    schema = pq.read_schema(str(pattern))
    cols = sorted(schema.names)
    print(f"  Total colonnes : {len(cols)}")
    print(f"  Fichier : {pattern}")
    # Lire les 2 dernieres rows pour voir les valeurs typiques
    try:
        df = pd.read_parquet(str(pattern))
        print(f"  Total rows : {len(df)}")
        if len(df) > 0:
            last_ts = df.iloc[-1].get("ts_event") or df.iloc[-1].get("ts_event_ns")
            print(f"  Last row ts : {last_ts}")
    except Exception as e:
        print(f"  Read error : {e}")

# Cross-ref avec les 36 features dashboard
print(f"\n\n{'='*80}\n=== CROSS-CHECK 36 FEATURES DASHBOARD ===\n{'='*80}")
WANTED = {
    "VWAP align": ["vwap_d_side", "vwap_w_side", "vwap_m_side", "vwap_slope_10",
                    "vwap_slope_10_dir", "vwap_triple_align"],
    "RVOL": ["rvol", "rvol_zscore"],
    "Delta DIV": ["delta_divergence_clean", "delta_div_buy_clean",
                   "delta_div_sell_clean", "delta_div_strength"],
    "Next Wall": ["next_wall_dist_ticks", "next_wall_is_call"],
    "Trapped": ["bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
                 "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active"],
    "POC migration": ["poc_migration_dir", "ctx_poc_migration_10",
                       "poc_position", "dist_cur_vpoc"],
    "Absorption": ["bn_absorb_bid", "bn_absorb_ask", "bool_near_level"],
    "Setup composite": ["ib_broken_up", "ib_broken_down", "ib_is_narrow",
                         "ib_position_pct", "profile_shape", "va_position_pct",
                         "bars_in_va", "open_bias_conf", "vix_regime",
                         "dist_swing_high", "dist_swing_low"],
}

# Lire colonnes V4 NQ (pris comme reference, V4 ES devrait avoir les memes)
v4_path = V4 / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
if v4_path.exists():
    schema = pq.read_schema(str(v4_path))
    v4_cols = set(schema.names)
    print(f"\nWidget                      Feature                                   V4?")
    print("-" * 80)
    total = ok = 0
    missing_features = []
    for widget, feats in WANTED.items():
        for feat in feats:
            total += 1
            present = feat in v4_cols
            mark = "✓" if present else "✗"
            if present:
                ok += 1
            else:
                missing_features.append((widget, feat))
            print(f"  {widget:<26s} {feat:<42s} {mark}")
    print("-" * 80)
    print(f"\nTotal : {ok}/{total} ({100*ok/total:.0f}%) features dispo dans V4 enriched")
    if missing_features:
        print(f"\nFeatures manquantes V4 ({len(missing_features)}) :")
        for w, f in missing_features:
            print(f"  - {w}: {f}")

    # Sample de colonnes V4 par categorie
    print(f"\n=== Echantillon colonnes V4 par theme ===")
    themes = {
        "VWAP": [c for c in v4_cols if "vwap" in c.lower()],
        "Profile/POC/VA": [c for c in v4_cols if any(k in c.lower() for k in ["poc","vah","val","va_","profile","prof_"])],
        "Trapped/BN": [c for c in v4_cols if "trapped" in c.lower() or "bn_" in c.lower()],
        "Delta/CVD": [c for c in v4_cols if "delta" in c.lower() or "cvd" in c.lower()],
        "Volume/RVOL": [c for c in v4_cols if "rvol" in c.lower() or "vol" in c.lower()],
        "MQ/Wall": [c for c in v4_cols if "mq_" in c.lower() or "wall" in c.lower() or "gex" in c.lower()],
        "IB": [c for c in v4_cols if "ib_" in c.lower() or "ib_" in c[:4].lower()],
    }
    for theme, items in themes.items():
        if items:
            print(f"\n  [{theme}] ({len(items)} cols)")
            for c in sorted(items)[:15]:
                print(f"    - {c}")
            if len(items) > 15:
                print(f"    ... +{len(items)-15} autres")
