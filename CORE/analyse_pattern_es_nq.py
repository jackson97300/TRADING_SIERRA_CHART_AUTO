"""Analyse pattern bias directionnel cross-instrument ES/NQ Bot 1 Sim3."""
import json
import sys
from pathlib import Path
from datetime import timedelta
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# Charger les trades du jour 28/04 du Bot 1
trades = []
fp = PAPER_DIR / "20260428_trades.jsonl"
if not fp.exists():
    print(f"MISSING {fp}")
    sys.exit(1)
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        s = line.strip()
        if s:
            try:
                trades.append(json.loads(s))
            except json.JSONDecodeError:
                pass

df = pd.DataFrame(trades)
df["entry_dt"] = pd.to_datetime(df["entry_time"])
df = df.sort_values("entry_dt").reset_index(drop=True)
print(f"Trades 28/04 Bot 1 Sim3 : {len(df)}\n")

# === Pattern 1 : repartition direction ===
print("=== Direction par symbol ===")
print(df.groupby(["symbol", "direction"]).size().unstack(fill_value=0))

# === Pattern 2 : trades cross-instrument dans fenetre courte ===
print("\n=== Trades cross-instrument < 30 min ===")
n_pairs_same_dir = 0
n_pairs_opposite = 0
pairs = []
for i, row in df.iterrows():
    sym_i = row["symbol"]
    other_sym = "NQ" if sym_i == "ES" else "ES"
    # Cherche trade autre symbole dans 30 min
    later = df[(df["symbol"] == other_sym) &
                (df["entry_dt"] > row["entry_dt"]) &
                (df["entry_dt"] - row["entry_dt"] < pd.Timedelta(minutes=30))]
    if len(later) > 0:
        next_other = later.iloc[0]
        delta_min = (next_other["entry_dt"] - row["entry_dt"]).total_seconds() / 60
        same_dir = (row["direction"] == next_other["direction"])
        if same_dir:
            n_pairs_same_dir += 1
        else:
            n_pairs_opposite += 1
        pairs.append({
            "ts1": str(row["entry_dt"])[11:19], "sym1": sym_i, "dir1": row["direction"],
            "pnl1": row.get("pnl_ticks", 0),
            "ts2": str(next_other["entry_dt"])[11:19], "sym2": other_sym, "dir2": next_other["direction"],
            "pnl2": next_other.get("pnl_ticks", 0),
            "delta_min": round(delta_min, 1),
            "same_dir": same_dir,
        })
print(f"Pairs same direction:  {n_pairs_same_dir}")
print(f"Pairs opposite:        {n_pairs_opposite}")
print(f"% same direction:      {100 * n_pairs_same_dir / max(1, n_pairs_same_dir + n_pairs_opposite):.0f}%")
print()
print("Detail (chronologique) :")
for p in pairs[:15]:
    sym_pnl1 = f"{p['pnl1']:+.0f}t"
    sym_pnl2 = f"{p['pnl2']:+.0f}t"
    print(f"  {p['ts1']} {p['sym1']:2s} {p['dir1']:5s} {sym_pnl1:>6s}  →  "
          f"{p['ts2']} {p['sym2']:2s} {p['dir2']:5s} {sym_pnl2:>6s}  "
          f"({p['delta_min']:>5.1f}min, {'SAME' if p['same_dir'] else 'OPPOS'})")

# === Pattern 3 : sequences de trades meme direction ===
print("\n=== Sequences meme direction (run length) ===")
runs = []
cur_run = [df.iloc[0]]
for i in range(1, len(df)):
    if df.iloc[i]["direction"] == cur_run[-1]["direction"]:
        cur_run.append(df.iloc[i])
    else:
        runs.append(cur_run)
        cur_run = [df.iloc[i]]
runs.append(cur_run)
for run in runs:
    if len(run) >= 2:
        first = run[0]
        last = run[-1]
        sl_count = sum(1 for r in run if r.get("outcome") == "SL")
        tp_count = sum(1 for r in run if r.get("outcome") == "TP")
        pnl_sum = sum(r.get("pnl_ticks", 0) for r in run)
        delta = (last["entry_dt"] - first["entry_dt"]).total_seconds() / 60
        print(f"  {first['direction']:5s} run de {len(run):>2d} trades : "
              f"{str(first['entry_dt'])[11:19]} → {str(last['entry_dt'])[11:19]} ({delta:>4.0f}min) "
              f"TP={tp_count} SL={sl_count} PnL={pnl_sum:+.0f}t")

# === Pattern 4 : circuit breaker observe ? ===
print("\n=== Verification circuit breaker (3 SL/60min devrait pause) ===")
sls = df[df["outcome"] == "SL"].copy()
print(f"Total SL: {len(sls)}")
for i in range(len(sls)):
    window_start = sls.iloc[i]["entry_dt"]
    window_end = window_start + pd.Timedelta(minutes=60)
    in_window = sls[(sls["entry_dt"] >= window_start) & (sls["entry_dt"] < window_end)]
    if len(in_window) >= 3:
        print(f"  3+ SL en 60min depuis {str(window_start)[11:19]} : "
              f"{len(in_window)} SL ({[str(t)[11:19] for t in in_window['entry_dt']]})")
        # Trade suivant apres window
        next_trade = df[df["entry_dt"] > in_window.iloc[-1]["entry_dt"]].head(1)
        if len(next_trade):
            gap_min = (next_trade.iloc[0]["entry_dt"] - in_window.iloc[-1]["entry_dt"]).total_seconds() / 60
            print(f"    Next trade : {str(next_trade.iloc[0]['entry_dt'])[11:19]} "
                  f"({gap_min:.1f}min apres dernier SL) — circuit OFF si <60min ?")
        break
