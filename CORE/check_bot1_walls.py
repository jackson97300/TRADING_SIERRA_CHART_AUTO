"""Verifier sl_wall + tp_wall pour TOUS les trades Bot 1 Sim3."""
import json
from pathlib import Path
from collections import Counter
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# Charger tous les trades Bot 1 (exclure databento)
all_trades = []
for fp in sorted(PAPER_DIR.glob("*_trades.jsonl")):
    if "databento" in fp.name:
        continue
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    all_trades.append(json.loads(s))
                except json.JSONDecodeError:
                    pass

df = pd.DataFrame(all_trades)
print(f"Total trades Bot 1 (tous jours) : {len(df)}\n")

# === CHECK 1 : SL wall ===
print("=== SL WALL ===")
print(f"  Cols disponibles : {[c for c in df.columns if 'sl' in c.lower() or 'wall' in c.lower()][:10]}")

if "sl_wall" in df.columns:
    sl_walls = df["sl_wall"].fillna("(missing)").value_counts()
    print(f"\n  Distribution sl_wall (top 20) :")
    for wall, cnt in sl_walls.head(20).items():
        print(f"    {wall:50s} : {cnt}")
    n_no_wall = int((df["sl_wall"].isna() | (df["sl_wall"] == "") | (df["sl_wall"] == "FIXED")).sum())
    print(f"\n  Trades SANS wall valide : {n_no_wall}/{len(df)} = {100*n_no_wall/len(df):.1f}%")
else:
    print("  Pas de col sl_wall dans schema Bot 1")

# === CHECK 2 : SL tier ===
if "sl_tier" in df.columns:
    print(f"\n=== SL TIER ===")
    print(f"  Distribution sl_tier :")
    for tier, cnt in df["sl_tier"].fillna(0).value_counts().sort_index().items():
        print(f"    Tier {tier} : {cnt}")

# === CHECK 3 : TP wall ===
print(f"\n=== TP WALL ===")
if "tp_wall" in df.columns:
    tp_walls = df["tp_wall"].fillna("(missing)").value_counts()
    print(f"\n  Distribution tp_wall (top 20) :")
    for wall, cnt in tp_walls.head(20).items():
        print(f"    {wall:50s} : {cnt}")
    n_tp_standard = int(df["tp_wall"].astype(str).str.contains("STANDARD").sum())
    print(f"\n  TP standard (fallback x2 SL, pas de mur) : {n_tp_standard}/{len(df)} = {100*n_tp_standard/len(df):.1f}%")
else:
    print("  Pas de col tp_wall dans schema Bot 1")

# === CHECK 4 : aujourd'hui spécifique ===
df["date"] = pd.to_datetime(df.get("entry_time", df.get("entry_ts", 0)), errors="coerce", unit=None).dt.date
today = pd.Timestamp("2026-04-28").date()
df_today = df[df["date"] == today]
print(f"\n=== AUJOURD'HUI 28/04 ({len(df_today)} trades) ===")
if len(df_today) > 0 and "sl_wall" in df_today.columns:
    print(f"\n  Detail sl_wall + sl_tier + tp_wall :")
    for _, t in df_today.iterrows():
        time_str = str(t.get("entry_time", ""))[11:19]
        sym = t.get("symbol", "?")
        direction = t.get("direction", "?")
        outcome = t.get("outcome", "?")
        sl_wall = t.get("sl_wall", "?")
        sl_tier = t.get("sl_tier", "?")
        tp_wall = t.get("tp_wall", "?")
        sl_ticks = t.get("sl_ticks", 0)
        tp_ticks = t.get("tp_ticks", 0)
        print(f"    {time_str} {sym:2s} {direction:5s} {outcome:7s} "
              f"SL={sl_ticks:>3.0f}t [{str(sl_wall):25s} T{sl_tier}]  "
              f"TP={tp_ticks:>3.0f}t [{str(tp_wall):25s}]")
