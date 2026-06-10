"""Audit exhaustif features BN (BookFlux) dans le snapshot v3 + parquet."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
SNAPSHOTS = ROOT / "DATA/PAPER_TRADES/20260428_databento_paper_snapshots.jsonl"
PARQUET_ES = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet"

# === 1. BN dans le PARQUET ENRICHI (toutes cols, fill rate today) ===
df = pd.read_parquet(PARQUET_ES)
df_today = df[pd.to_datetime(df['ts_event']).dt.date == pd.Timestamp("2026-04-28").date()]

bn_cols = sorted([c for c in df.columns if 'bn_' in c.lower() or c.lower().startswith('bn')])
big_cols = sorted([c for c in df.columns if 'big_' in c.lower()])
absorb_cols = sorted([c for c in df.columns if 'absorb' in c.lower()])
trapped_cols = sorted([c for c in df.columns if 'trapped' in c.lower()])
print(f"=== PARQUET ES (today: {len(df_today)} bars) ===")
print(f"\nBN features ({len(bn_cols)}):")
for c in bn_cols:
    n_filled = df_today[c].notna().sum()
    pct = 100 * n_filled / len(df_today) if len(df_today) > 0 else 0
    last_val = df_today[c].iloc[-1] if len(df_today) > 0 else None
    print(f"  {c:40s} fill={pct:5.1f}% ({n_filled:4d}/{len(df_today)})  last={last_val}")

print(f"\nBIG features ({len(big_cols)}):")
for c in big_cols:
    n_filled = df_today[c].notna().sum()
    pct = 100 * n_filled / len(df_today) if len(df_today) > 0 else 0
    last_val = df_today[c].iloc[-1] if len(df_today) > 0 else None
    print(f"  {c:40s} fill={pct:5.1f}% ({n_filled:4d}/{len(df_today)})  last={last_val}")

print(f"\nABSORB features ({len(absorb_cols)}):")
for c in absorb_cols:
    n_filled = df_today[c].notna().sum()
    pct = 100 * n_filled / len(df_today) if len(df_today) > 0 else 0
    last_val = df_today[c].iloc[-1] if len(df_today) > 0 else None
    print(f"  {c:40s} fill={pct:5.1f}% ({n_filled:4d}/{len(df_today)})  last={last_val}")

print(f"\nTRAPPED features ({len(trapped_cols)}):")
for c in trapped_cols:
    n_filled = df_today[c].notna().sum()
    pct = 100 * n_filled / len(df_today) if len(df_today) > 0 else 0
    last_val = df_today[c].iloc[-1] if len(df_today) > 0 else None
    print(f"  {c:40s} fill={pct:5.1f}% ({n_filled:4d}/{len(df_today)})  last={last_val}")

# === 2. BN dans le DERNIER SNAPSHOT v3 ===
print(f"\n=== SNAPSHOT v3 LATEST ===")
lines = SNAPSHOTS.read_text(encoding="utf-8").splitlines()
v3_lines = [l for l in lines if "snapshot_v3" in l]
if v3_lines:
    s = json.loads(v3_lines[-1])
    feats = s.get("features", {})
    print(f"  symbol={s['symbol']} bar_ts={s['bar_ts']} n_features={s['n_features']}")
    bn_in_snap = {k: v for k, v in feats.items() if 'bn_' in k.lower() or 'absorb' in k.lower() or 'trapped' in k.lower() or 'big_' in k.lower()}
    print(f"\n  Microstructure features (BN/big/absorb/trapped) : {len(bn_in_snap)}")
    for k, v in sorted(bn_in_snap.items()):
        print(f"    {k:40s} = {v}")
