"""Audit NaN live JSONL NQ vs V4 batch parquet — categorise legitimes vs bugs."""
import json
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "DATA" / "live_enriched" / "NQ_c_0" / "20260515.jsonl"
V4_PATH = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"

# Load live
rows = []
with open(LIVE_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line.replace("NaN", "null")))
            except json.JSONDecodeError:
                pass
df_live = pd.DataFrame(rows)
print(f"LIVE NQ : {len(df_live)} rows / {len(df_live.columns)} cols")

# Categorise NaN ratio per feature
nan_ratios = {}
for c in df_live.columns:
    nan_ratios[c] = df_live[c].isna().mean() if df_live[c].dtype.kind in "fc" else (df_live[c].astype(str) == "None").mean()

# Features 100% NaN
fully_nan = [c for c, r in nan_ratios.items() if r >= 0.99]
print(f"\n=== {len(fully_nan)} features 100% NaN sur LIVE ===")

# Categorise legitimes vs suspects
PRE_RTH_LEGIT = {
    "ib_high", "ib_low", "ib_range", "ib_range_ticks", "ib_position_pct",
    "ib_range_atr", "ib_complete",
    "dist_ib_high_pct", "dist_ib_low_pct", "dist_ib_high", "dist_ib_low",
    "ctx_ib_extension_ratio", "ctx_ib_position_velocity",
    "cash_high", "cash_low", "dist_cash_high_pct", "dist_cash_low_pct",
    "is_new_cash_high", "is_new_cash_low",
    "open_cash", "price_1030",
    "open_830_et", "open_930_et", "dist_open_830_pct", "dist_open_930_pct",
    "us_high", "us_low", "dist_us_high_pct", "dist_us_low_pct",
    "after_high", "after_low", "dist_after_high_pct", "dist_after_low_pct",
    "ny_open", "dist_ny_open_pct", "above_ny_open",
    "after_open", "dist_after_open_pct", "above_after_open",
    "asia_open", "dist_asia_open_pct",
    "london_open", "dist_london_open_pct",
}
EVENT_BASED_LEGIT = {
    "dist_big_ask_nearest_pct", "dist_big_bid_nearest_pct",
    "dist_cluster_nearest_up_pct", "dist_cluster_nearest_dn_pct",
    "dist_swing_high", "dist_swing_low",
    "dist_last_swing_high_pct", "dist_last_swing_low_pct",
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
    "div_at_key_level_ticks",
    "ovn_high", "ovn_low", "ovn_range_ticks", "dist_ovn_high_pct", "dist_ovn_low_pct",
}
MQ_0DTE_LEGIT = {
    "mq_call_0dte", "mq_put_0dte", "vix_call_0dte", "vix_put_0dte",
    "vix_gamma_wall_0dte",
    "dist_vix_call_0dte", "dist_vix_put_0dte", "dist_vix_gamma_wall_0dte",
}
R1_KNOWN = {
    "im_ltr_slope_diff",  # R1 large_trader_ratio absent Databento
}

# J-1 seed suspect (devrait etre rempli depuis V4 J-1)
J1_SEED_SUSPECT = {
    "prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
    "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pdh_pct", "dist_pdl_pct",
}

# Sessions historique (devraient avoir asia values vu que session deja passe)
SESSIONS_SUSPECT = {
    "asia_high", "asia_low",
    "dist_asia_high_pct", "dist_asia_low_pct",
}

# Intermarket features qui peuvent etre legit NaN si partner stale
INTERMARKET_LEGIT = {
    "im_delta_day_divergence",  # depend delta_day_dir partner = NaN si pas calcule
    "im_volume_lead",  # depend partner volume cumsum
}

# Categorise fully_nan
cat_A_pre_rth = [c for c in fully_nan if c in PRE_RTH_LEGIT]
cat_B_event = [c for c in fully_nan if c in EVENT_BASED_LEGIT]
cat_C_mq0dte = [c for c in fully_nan if c in MQ_0DTE_LEGIT]
cat_D_r1 = [c for c in fully_nan if c in R1_KNOWN]
cat_E_intermarket = [c for c in fully_nan if c in INTERMARKET_LEGIT]
cat_F_j1_seed = [c for c in fully_nan if c in J1_SEED_SUSPECT]
cat_G_sessions = [c for c in fully_nan if c in SESSIONS_SUSPECT]
all_known = (
    PRE_RTH_LEGIT | EVENT_BASED_LEGIT | MQ_0DTE_LEGIT | R1_KNOWN
    | INTERMARKET_LEGIT | J1_SEED_SUSPECT | SESSIONS_SUSPECT
)
cat_H_unknown = [c for c in fully_nan if c not in all_known]

print(f"\n=== CATEGORISATION ===")
print(f"  A. Pre-RTH legitimes ({len(cat_A_pre_rth)}) : {cat_A_pre_rth[:5]}...")
print(f"  B. Event-based legitimes ({len(cat_B_event)}) : {cat_B_event[:5]}...")
print(f"  C. MQ 0DTE manquants ({len(cat_C_mq0dte)}) : {cat_C_mq0dte}")
print(f"  D. R1 known (large_trader_ratio) ({len(cat_D_r1)}) : {cat_D_r1}")
print(f"  E. Intermarket legit ({len(cat_E_intermarket)}) : {cat_E_intermarket}")
print(f"\n  F. J-1 seed SUSPECT ({len(cat_F_j1_seed)}) : {cat_F_j1_seed}")
print(f"  G. Sessions Asia SUSPECT ({len(cat_G_sessions)}) : {cat_G_sessions}")
print(f"  H. UNKNOWN (a investiguer) ({len(cat_H_unknown)}) :")
for c in cat_H_unknown[:30]:
    print(f"    - {c}")
if len(cat_H_unknown) > 30:
    print(f"    ... ({len(cat_H_unknown) - 30} more)")

# Verif J-1 dans V4 parquet
if V4_PATH.exists():
    df_v4 = pd.read_parquet(V4_PATH)
    print(f"\n=== V4 NQ MAY 2026 ===")
    print(f"  Rows: {len(df_v4)}")
    for c in ["prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
              "asia_high", "asia_low"]:
        if c in df_v4.columns:
            nn = df_v4[c].notna().sum()
            print(f"  {c:20s} non-null V4 = {nn}/{len(df_v4)}")
        else:
            print(f"  {c:20s} ABSENT V4 schema")
