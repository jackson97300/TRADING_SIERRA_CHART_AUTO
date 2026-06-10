"""Investigue features manquantes V4 enriched (range_pos NaN, dist_swing_low N/A).

Vérifie :
1. Liste exhaustive colonnes V4 enriched parquet (ES+NQ)
2. Stats null per column pour les features critiques
3. Compare avec colonnes Sierra DMP JSONL
"""
import json
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

V4_NQ = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
V4_ES = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=05" / "data.parquet"
SIERRA_NQ = ROOT / "DATA" / "NQ" / "20260511_NQ.jsonl"

print("=" * 100)
print("INVESTIGATION : range_pos + dist_swing_low dans V4 enriched")
print("=" * 100)

# 1. Liste colonnes V4 NQ
print("\n=== 1. COLONNES V4 ENRICHED NQ ===")
df_v4 = pq.read_table(V4_NQ).to_pandas()
print(f"N bars : {len(df_v4)}")
print(f"N cols : {len(df_v4.columns)}")
print(f"Cols : {sorted(df_v4.columns.tolist())}")

# 2. Cherche range_pos et dist_swing_low (et variantes)
print("\n=== 2. SEARCH features ciblees ===")
targets = ["range_pos", "dist_swing_low", "dist_swing_high", "swing_low", "swing_high",
           "session_low", "session_high", "sess_high", "sess_low", "dist_sess_low", "dist_sess_high"]
for t in targets:
    matches = [c for c in df_v4.columns if t.lower() in c.lower()]
    if matches:
        for col in matches:
            n_null = df_v4[col].isna().sum()
            n_total = len(df_v4)
            pct_null = round(100 * n_null / n_total, 1)
            non_null_sample = df_v4[col].dropna().head(3).tolist()
            print(f"  ✅ {col:<35} null={n_null}/{n_total} ({pct_null}%) sample={non_null_sample}")
    else:
        print(f"  ❌ {t:<35} ABSENT")

# 3. Compare avec Sierra DMP
print("\n=== 3. SIERRA DMP JSONL features dispo (1ere ligne 11/05 NQ) ===")
if SIERRA_NQ.exists():
    with open(SIERRA_NQ, "r", encoding="utf-8") as f:
        first = f.readline()
        j = json.loads(first)
    sierra_cols = sorted(j.keys())
    print(f"N cols Sierra : {len(sierra_cols)}")
    # Cherche les memes targets
    for t in targets:
        matches = [c for c in sierra_cols if t.lower() in c.lower()]
        if matches:
            for col in matches:
                v = j.get(col)
                print(f"  ✅ Sierra {col:<35} value={v}")
        else:
            print(f"  ❌ Sierra {t:<35} ABSENT")

# 4. Diff cols Sierra vs V4
print("\n=== 4. DIFF cols ===")
if SIERRA_NQ.exists():
    set_sierra = set(sierra_cols)
    set_v4 = set(df_v4.columns)
    only_sierra = sorted(set_sierra - set_v4)
    only_v4 = sorted(set_v4 - set_sierra)
    common = sorted(set_sierra & set_v4)
    print(f"Common cols : {len(common)}")
    print(f"Sierra-only ({len(only_sierra)}) : {only_sierra[:30]}...")
    print(f"V4-only ({len(only_v4)}) : {only_v4[:30]}...")

# 5. range_size_ticks dans V4 ?
print("\n=== 5. Features Sierra critiques DANS V4 ? ===")
critical = ["range_pos", "range_size_ticks", "dist_swing_high", "dist_swing_low",
            "swing_range_ticks", "dist_sess_high", "dist_sess_low", "sess_range_ticks",
            "open_type", "day_type", "profile_shape", "trend_day_probability",
            "vwap_d_side", "vwap_slope_10", "rvol", "rvol_zscore",
            "bn_color_up", "bn_absorb_ask", "bn_absorb_bid",
            "mq_call", "mq_put", "mq_hvl", "dist_mq_call_0dte",
            "open_bias_conf", "open_zone", "open_direction",
            "bool_above_vwap_d", "bool_above_mq_hvl",
            "bars_in_va", "inside_cur_va",
            "delta_bar", "delta_day", "cvd_day_dir",
            "bars_since_last_swing_high", "bars_since_last_swing_low",
            "bar_upper_wick_pct", "bar_lower_wick_pct", "volume_z",
            "n_edge_buy_active", "n_edge_sell_active",
            "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct"]
print(f"{'Feature':<35}{'V4 ENRICHED':<20}{'SIERRA DMP'}")
print("-" * 90)
for c in critical:
    v4_status = "?"
    if c in df_v4.columns:
        n_null = df_v4[c].isna().sum()
        pct_null = round(100 * n_null / len(df_v4), 1)
        if pct_null == 100:
            v4_status = "EXISTS 100% NaN"
        elif pct_null > 50:
            v4_status = f"EXISTS {pct_null}% NaN"
        else:
            v4_status = f"OK ({pct_null}% NaN)"
    else:
        v4_status = "ABSENT"
    sierra_status = "OK" if SIERRA_NQ.exists() and c in j else "ABSENT"
    print(f"{c:<35}{v4_status:<20}{sierra_status}")
