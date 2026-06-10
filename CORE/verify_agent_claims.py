"""Verifier 3 claims feature-engineer agent :
1. Aujourd'hui 33/421 (8%) remplies >50% (vs ma claim 394/421 = 93%)
2. Snapshot 28/04 19:14 = 21/49 non-null (vs ma claim 46/49 = 94%)
3. Le parquet du jour courant n'a que 33 features remplies
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
PARQUET = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet"
SNAPSHOTS = ROOT / "DATA/PAPER_TRADES/20260428_databento_paper_snapshots.jsonl"

# === CLAIM 1 + 3 : Parquet today fill rates ===
df = pd.read_parquet(PARQUET)
df_today = df[pd.to_datetime(df['ts_event']).dt.date == pd.Timestamp("2026-04-28").date()]
df_yest = df[pd.to_datetime(df['ts_event']).dt.date == pd.Timestamp("2026-04-27").date()]

print(f"=== PARQUET ES ===")
print(f"Total: {df.shape}")
print(f"TODAY (28/04): {df_today.shape}")
print(f"YESTERDAY (27/04): {df_yest.shape}")

# Method 1: notna().any() — au moins 1 valeur non-null
any_nonnull_today = (df_today.notna().any()).sum()
any_nonnull_yest = (df_yest.notna().any()).sum()

# Method 2: notna().mean() > 50% — strict
mean_50_today = ((df_today.notna().sum() / len(df_today)) > 0.5).sum()
mean_50_yest = ((df_yest.notna().sum() / len(df_yest)) > 0.5).sum()

# Method 3: notna().mean() > 90%
mean_90_today = ((df_today.notna().sum() / len(df_today)) > 0.9).sum()
mean_90_yest = ((df_yest.notna().sum() / len(df_yest)) > 0.9).sum()

print(f"\n--- Fill rate TODAY (28/04) sur {len(df_today)} bars ---")
print(f"  cols avec >=1 valeur non-null  : {any_nonnull_today}/421")
print(f"  cols avec >50% non-null        : {mean_50_today}/421")
print(f"  cols avec >90% non-null        : {mean_90_today}/421")

print(f"\n--- Fill rate HIER (27/04) sur {len(df_yest)} bars ---")
print(f"  cols avec >=1 valeur non-null  : {any_nonnull_yest}/421")
print(f"  cols avec >50% non-null        : {mean_50_yest}/421")
print(f"  cols avec >90% non-null        : {mean_90_yest}/421")

# === CLAIM 2 : Snapshot bot non-null ratio ===
print(f"\n=== SNAPSHOT BOT ===")
snapshots = []
with open(SNAPSHOTS, "r", encoding="utf-8") as f:
    for line in f:
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
print(f"Total snapshots: {len(snapshots)}")

# Check chaque snapshot
print(f"\n--- ratio non-null par snapshot (5 derniers) ---")
for s in snapshots[-5:]:
    feats = s.get('features', {})
    n_total = len(feats)
    n_filled = sum(1 for v in feats.values() if v is not None)
    sym = s.get('symbol', '?')
    bar_ts = s.get('bar_ts', '?')
    print(f"  {sym} {bar_ts}: {n_filled}/{n_total} = {100*n_filled/n_total:.0f}%")

# === DIAGNOSTIC LAG PIPELINE ===
print(f"\n=== DIAGNOSTIC LAG ENRICHISSEMENT ===")
# Pour la dernière bar today, combien de features sont remplies vs combien existent ?
last_bar = df_today.iloc[-1]
n_total = len(last_bar)
n_filled = last_bar.notna().sum()
print(f"Last bar TODAY ({last_bar['ts_event']}):")
print(f"  cols total: {n_total}")
print(f"  cols non-null: {n_filled}")
print(f"  cols null: {n_total - n_filled}")

# Yesterday last bar
last_bar_y = df_yest.iloc[-1]
n_filled_y = last_bar_y.notna().sum()
print(f"\nLast bar YESTERDAY ({last_bar_y['ts_event']}):")
print(f"  cols non-null: {n_filled_y}/{n_total}")

# Sample des cols NULL aujourd'hui pour voir pattern
null_today_cols = [c for c in df_today.columns if df_today[c].isna().all()]
print(f"\n--- Cols 100% NULL aujourd'hui ({len(null_today_cols)}) sample 20 ---")
for c in null_today_cols[:20]:
    print(f"  {c}")
