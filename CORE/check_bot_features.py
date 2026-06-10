"""check_bot_features.py — Audit exhaustif features bot databento_paper.

Audit :
1. Parquet enrichi : combien de cols, lesquelles fill rate <100% sur 28/04
2. Snapshot bot : combien de features captures, lesquelles null
3. Cross check : que MANQUE le bot vs le parquet
4. Process decision step-by-step
"""
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
PARQUET = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet"
SNAPSHOTS = ROOT / "DATA/PAPER_TRADES/20260428_databento_paper_snapshots.jsonl"

print("=" * 80)
print(" AUDIT FEATURES BOT databento_paper_trader Sim2 ")
print("=" * 80)

# ========================================================================
# 1. PARQUET ENRICHI
# ========================================================================
df = pd.read_parquet(PARQUET)
print(f"\n[1] PARQUET ES avril 2026")
print(f"   Shape: {df.shape}")
print(f"   ts_range: {df['ts_event'].min()} -> {df['ts_event'].max()}")

# Filter today (28/04)
df_today = df[df['ts_event'].dt.date == pd.Timestamp("2026-04-28").date()]
print(f"\n   28/04 only: {df_today.shape}")

# Fill rate par feature (28/04 only)
fill_rates_today = (df_today.notna().sum() / len(df_today) * 100).sort_values(ascending=False)
n_full = (fill_rates_today == 100).sum()
n_partial = ((fill_rates_today > 0) & (fill_rates_today < 100)).sum()
n_zero = (fill_rates_today == 0).sum()
print(f"\n   Cols avec fill rate 100% sur 28/04 : {n_full}/{len(fill_rates_today)}")
print(f"   Cols avec fill rate partiel       : {n_partial}/{len(fill_rates_today)}")
print(f"   Cols avec fill rate 0% sur 28/04  : {n_zero}/{len(fill_rates_today)}")

# Cols vides (Phase B non applique sur 28/04 partial day)
zero_cols = fill_rates_today[fill_rates_today == 0].index.tolist()
print(f"\n   Top 30 cols vides 28/04 (Phase B non applique): {zero_cols[:30]}")

# ========================================================================
# 2. SNAPSHOT BOT
# ========================================================================
print(f"\n[2] SNAPSHOTS BOT Sim2 (28/04)")
snapshots = []
with open(SNAPSHOTS, "r", encoding="utf-8") as f:
    for line in f:
        try:
            snapshots.append(json.loads(line))
        except:
            pass
print(f"   Nb snapshots: {len(snapshots)}")

if snapshots:
    s = snapshots[-1]  # dernier
    features = s.get("features", {})
    n_total = len(features)
    n_filled = sum(1 for v in features.values() if v is not None)
    n_null = n_total - n_filled
    print(f"   Features captures par bot: {n_total}")
    print(f"   Features non-null         : {n_filled}/{n_total} = {100*n_filled/n_total:.0f}%")
    print(f"   Features NULL             : {n_null}/{n_total}")
    null_features = [k for k, v in features.items() if v is None]
    filled_features = [k for k, v in features.items() if v is not None]
    print(f"\n   FILLED ({n_filled}): {filled_features}")
    print(f"\n   NULL ({n_null}): {null_features}")

# ========================================================================
# 3. CROSS CHECK : BOT vs PARQUET
# ========================================================================
print(f"\n[3] CROSS CHECK : ce que le bot voit vs ce qui existe dans parquet")
parquet_today_cols = set(df_today.columns)
parquet_today_filled_cols = set(df_today.columns[df_today.notna().any()])
bot_filled = set(filled_features)
bot_all = set(features.keys())
bot_null = set(null_features)

# Features que le bot LIST mais qui sont VIDES dans parquet (= legitime)
null_because_parquet_empty = [c for c in bot_null if c in parquet_today_cols and df_today[c].notna().sum() == 0]
# Features que le bot LIST et qui SONT remplies dans parquet mais bot voit null (= bug bot)
null_bug_bot = [c for c in bot_null if c in parquet_today_filled_cols]
# Features que le bot LIST mais qui n'existent PAS dans parquet (= bug naming)
null_missing_parquet = [c for c in bot_null if c not in parquet_today_cols]

print(f"   Bot null car col vide parquet (normal partial day Phase B): {len(null_because_parquet_empty)}")
print(f"      → {null_because_parquet_empty[:10]}")
print(f"   Bot null mais col remplie parquet (BUG BOT)              : {len(null_bug_bot)}")
print(f"      → {null_bug_bot}")
print(f"   Bot null car col absente parquet (BUG NOM)               : {len(null_missing_parquet)}")
print(f"      → {null_missing_parquet}")

# Features du parquet remplies que le bot N'ECOUTE PAS
parquet_filled_not_in_bot = [c for c in parquet_today_filled_cols if c not in bot_all]
print(f"\n   Features dispo parquet PAS lues par bot ({len(parquet_filled_not_in_bot)}):")
print(f"      {parquet_filled_not_in_bot[:30]}")

# ========================================================================
# 4. PROCESS DECISION (extracte du checks)
# ========================================================================
print(f"\n[4] PROCESS DECISION (snapshot dernier)")
if snapshots:
    print(f"   Symbol: {s['symbol']}")
    print(f"   Bar ts: {s['bar_ts']}")
    print(f"   close:  {features.get('close')}")
    print(f"   Score:  bull={s['bull_pts']} bear={s['bear_pts']}")
    print(f"   Direction: {s['direction']}")
    print(f"   Checks contributing to score:")
    for c in s.get("checks", []):
        print(f"      - {c}")
