"""Audit bot vs parquet : combien de features lues par le bot vs disponibles."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
SNAPSHOTS = ROOT / "DATA/PAPER_TRADES/20260428_databento_paper_snapshots.jsonl"
PARQUET_ES = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet"

# 1. Last 3 snapshots du bot
snapshots = []
with open(SNAPSHOTS, "r", encoding="utf-8") as f:
    for line in f:
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
print(f"Total snapshots: {len(snapshots)}")
last_snap = snapshots[-1]
print(f"\n=== LAST SNAPSHOT ({last_snap['symbol']}) ===")
print(f"  bar_ts: {last_snap.get('bar_ts')}")
print(f"  direction: {last_snap.get('direction')}")
print(f"  bull/bear: {last_snap.get('bull_pts')}/{last_snap.get('bear_pts')}")

features = last_snap.get('features', {})
n_total = len(features)
n_filled = sum(1 for v in features.values() if v is not None)
print(f"  features lues par bot: {n_total}")
print(f"  features non-null: {n_filled}/{n_total} = {100*n_filled/n_total:.0f}%")

null_features = [k for k, v in features.items() if v is None]
filled_features = [k for k, v in features.items() if v is not None]
print(f"\n  FEATURES LUES + REMPLIES ({n_filled}):")
for f in filled_features:
    val = features[f]
    if isinstance(val, float):
        print(f"    {f:35s} = {val:.4f}")
    else:
        print(f"    {f:35s} = {val}")

print(f"\n  FEATURES LUES MAIS NULL ({len(null_features)}):")
for f in null_features:
    print(f"    {f}")

# 2. Cross-check : que MANQUE le bot vs ce qui existe dans parquet
df = pd.read_parquet(PARQUET_ES)
df_today = df[pd.to_datetime(df['ts_event']).dt.date == pd.Timestamp("2026-04-28").date()]
last_bar_parquet = df_today.iloc[-1]
parquet_cols = set(df_today.columns)
bot_features_set = set(features.keys())
parquet_filled_today = set([c for c in df_today.columns if df_today[c].notna().any()])

missed_by_bot = parquet_filled_today - bot_features_set
print(f"\n=== CROSS-CHECK ===")
print(f"  Parquet ES cols total: {len(parquet_cols)}")
print(f"  Parquet ES cols REMPLIES today: {len(parquet_filled_today)}")
print(f"  Bot features lues: {len(bot_features_set)}")
print(f"  Features REMPLIES dans parquet mais PAS LUES par bot: {len(missed_by_bot)}")
print(f"  Top 50 missed (par categorie):")
for f in sorted(missed_by_bot)[:50]:
    print(f"    {f}")
