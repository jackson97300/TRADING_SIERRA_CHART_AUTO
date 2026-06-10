"""Audit des trades simultanes Bot 1 (Sim3) vs Bot 2 (Sim2) le 29/04/2026.

Detecte les fenetres ou les 2 bots ont une position OPPOSEE sur le MEME
instrument (BUY vs SELL ES en meme temps, ou BUY vs SELL NQ).
"""
import json
from pathlib import Path
import pandas as pd

FP1 = Path("DATA/PAPER_TRADES/20260429_trades.jsonl")           # Bot 1 Sim3
FP2 = Path("DATA/PAPER_TRADES/20260429_databento_trades.jsonl")  # Bot 2 Sim2


def load(fp):
    rows = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    df["entry_dt"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_dt"] = pd.to_datetime(df["exit_time"], utc=True)
    return df


df1 = load(FP1)
df2 = load(FP2)
df1["bot"] = "BOT1_Sim3"
df2["bot"] = "BOT2_Sim2"

# Direction normaliser
def norm_dir(s):
    s = str(s).upper()
    if "LONG" in s or "BUY" in s:
        return "LONG"
    if "SHORT" in s or "SELL" in s:
        return "SHORT"
    return s
df1["dir_n"] = df1["direction"].apply(norm_dir)
df2["dir_n"] = df2["direction"].apply(norm_dir)

# Filter 29/04 only
mask1 = df1["entry_dt"] >= "2026-04-29T00:00:00+00:00"
mask2 = df2["entry_dt"] >= "2026-04-29T00:00:00+00:00"
df1 = df1[mask1]
df2 = df2[mask2]

print("=" * 90)
print("  AUDIT TRADES SIMULTANES BOT 1 vs BOT 2 — 29/04/2026")
print("=" * 90)
print(f"Bot 1 Sim3 : {len(df1)} trades")
print(f"Bot 2 Sim2 : {len(df2)} trades")

# === Detection chevauchements ===
print("\n" + "=" * 90)
print("  CHEVAUCHEMENTS (positions actives en meme temps)")
print("=" * 90)
print(f"{'Bot1':<10s} {'Sym':<3s} {'Dir':<5s} {'Entry':>9s} {'Bot1_t':<19s} {'Bot1_exit':<19s} || "
      f"{'Bot2':<10s} {'Sym':<3s} {'Dir':<5s} {'Entry':>9s} {'Bot2_t':<19s}")
print("-" * 130)

n_simult_same_dir = 0
n_simult_opposite_dir = 0
n_simult_same_sym_opposite_dir = 0
n_total_overlaps = 0

for _, t1 in df1.iterrows():
    for _, t2 in df2.iterrows():
        # Overlap : t1 ouverte avant que t2 ferme ET t1 ferme apres que t2 ouvre
        if t1["entry_dt"] <= t2["exit_dt"] and t1["exit_dt"] >= t2["entry_dt"]:
            n_total_overlaps += 1
            same_sym = t1["symbol"] == t2["symbol"]
            same_dir = t1["dir_n"] == t2["dir_n"]
            if same_dir:
                n_simult_same_dir += 1
            else:
                n_simult_opposite_dir += 1
                if same_sym:
                    n_simult_same_sym_opposite_dir += 1
                    flag = "⚠️ OPPOSE MEME SYM"
                else:
                    flag = "OK (sym diff)"
                print(f"BOT1 {t1['symbol']:<3s} {t1['dir_n']:<5s} "
                      f"{float(t1['entry_price']):>9.2f} "
                      f"{str(t1['entry_dt'])[:19]:<19s} {str(t1['exit_dt'])[:19]:<19s} || "
                      f"BOT2 {t2['symbol']:<3s} {t2['dir_n']:<5s} "
                      f"{float(t2['entry_price']):>9.2f} "
                      f"{str(t2['entry_dt'])[:19]:<19s} {flag}")

print("\n" + "=" * 90)
print(f"  STATS")
print("=" * 90)
print(f"  Total chevauchements : {n_total_overlaps}")
print(f"  Meme direction       : {n_simult_same_dir}")
print(f"  Direction opposee    : {n_simult_opposite_dir}")
print(f"  ⚠️  OPPOSE MEME SYM   : {n_simult_same_sym_opposite_dir} (HEDGE involontaire)")

# Stats individuelles
print("\n" + "=" * 90)
print("  PROFIL DIRECTION PAR BOT (29/04 only)")
print("=" * 90)
for label, df in [("Bot 1 Sim3", df1), ("Bot 2 Sim2", df2)]:
    n = len(df)
    n_long = (df["dir_n"] == "LONG").sum()
    n_short = (df["dir_n"] == "SHORT").sum()
    print(f"  {label:<12s} : {n} trades | LONG {n_long} ({n_long/n*100:.0f}%) | SHORT {n_short} ({n_short/n*100:.0f}%)")

# Distribution heure d'entry
print("\n" + "=" * 90)
print("  ECARTS TEMPS D'ENTRY (bot 1 vs bot 2 sur meme symbole)")
print("=" * 90)
ecarts = []
for _, t1 in df1.iterrows():
    for _, t2 in df2.iterrows():
        if t1["symbol"] == t2["symbol"]:
            delta_sec = abs((t1["entry_dt"] - t2["entry_dt"]).total_seconds())
            if delta_sec < 1800:  # < 30 min
                ecarts.append({
                    "sym": t1["symbol"],
                    "delta_sec": delta_sec,
                    "bot1_entry": t1["entry_dt"],
                    "bot2_entry": t2["entry_dt"],
                    "bot1_dir": t1["dir_n"],
                    "bot2_dir": t2["dir_n"],
                })
ec_df = pd.DataFrame(ecarts)
if len(ec_df):
    print(f"  N entrys < 30min d'ecart sur meme sym : {len(ec_df)}")
    print(f"  Median ecart : {ec_df['delta_sec'].median():.0f}s ({ec_df['delta_sec'].median()/60:.1f}min)")
    print(f"  Min ecart    : {ec_df['delta_sec'].min():.0f}s")
print("=" * 90)
