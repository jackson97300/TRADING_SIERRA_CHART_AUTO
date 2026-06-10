"""Audit complet Bot 1 Sim3 session 29/04/2026.

Stats : globales / direction / symbole / outcome / session / outlier / pattern SL.
Reponse a la demande Jackson "ANALYSE CES TRADES + TODO + AGENT".
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import statistics

import pandas as pd

FP = Path("DATA/PAPER_TRADES/20260429_trades.jsonl")
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}

rows = []
with open(FP, "r", encoding="utf-8") as f:
    for line in f:
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            pass

df = pd.DataFrame(rows)
print(f"=== AUDIT BOT 1 Sim3 — 29/04/2026 ===")
print(f"N trades total : {len(df)}")
print(f"Colonnes : {list(df.columns)[:30]}")

# Sanity : keep only closed trades
if "outcome" in df.columns:
    df = df[df["outcome"].notna() & df["outcome"].isin(["TP", "SL", "TIMEOUT"])]
    print(f"N trades fermes valides : {len(df)}")

# ── STATS GLOBALES ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("  1. STATS GLOBALES")
print("=" * 70)
df["pnl_ticks"] = pd.to_numeric(df["pnl_ticks"], errors="coerce").fillna(0)
df["pnl_usd"] = pd.to_numeric(df.get("pnl_usd", 0), errors="coerce").fillna(0)
n = len(df)
wins = df[df["pnl_ticks"] > 0]
losses = df[df["pnl_ticks"] < 0]
zeros = df[df["pnl_ticks"] == 0]
gross_win = wins["pnl_usd"].sum()
gross_loss = abs(losses["pnl_usd"].sum())
net = df["pnl_usd"].sum()
pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
wr = len(wins) / n * 100 if n else 0
print(f"  N trades        : {n}")
print(f"  Wins / Losses   : {len(wins)} / {len(losses)} (zeros: {len(zeros)})")
print(f"  Win rate        : {wr:.1f}%")
print(f"  Gross win       : ${gross_win:+.2f}")
print(f"  Gross loss      : ${-gross_loss:+.2f}")
print(f"  Profit Factor   : {pf:.2f}")
print(f"  PnL net         : ${net:+.2f}")
print(f"  Mean PnL/trade  : ${net/n:+.2f} ({df['pnl_ticks'].mean():+.1f}t)")
print(f"  Median PnL      : {df['pnl_ticks'].median():+.1f}t")

# ── DIRECTION ────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  2. STATS PAR DIRECTION")
print("=" * 70)
dir_col = "direction" if "direction" in df.columns else "side"
for direction in df[dir_col].unique():
    d = df[df[dir_col] == direction]
    nd = len(d)
    wd = (d["pnl_ticks"] > 0).sum()
    pnl = d["pnl_usd"].sum()
    pf_d = d[d["pnl_ticks"] > 0]["pnl_usd"].sum() / max(abs(d[d["pnl_ticks"] < 0]["pnl_usd"].sum()), 1e-9)
    print(f"  {direction:>5s} | n={nd:>3d} ({nd/n*100:.1f}%) | WR={wd/nd*100:.1f}% | PF={pf_d:.2f} | PnL=${pnl:+.2f}")

# ── SYMBOLE ──────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  3. STATS PAR SYMBOLE")
print("=" * 70)
for sym in df["symbol"].unique():
    s = df[df["symbol"] == sym]
    ns = len(s)
    ws = (s["pnl_ticks"] > 0).sum()
    pnl = s["pnl_usd"].sum()
    pf_s = s[s["pnl_ticks"] > 0]["pnl_usd"].sum() / max(abs(s[s["pnl_ticks"] < 0]["pnl_usd"].sum()), 1e-9)
    avg = s["pnl_ticks"].mean()
    print(f"  {sym:>3s} | n={ns:>3d} | WR={ws/ns*100:.1f}% | PF={pf_s:.2f} | PnL=${pnl:+.2f} | avg={avg:+.1f}t")

# ── OUTCOME ──────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  4. STATS PAR OUTCOME")
print("=" * 70)
for outcome in ["TP", "SL", "TIMEOUT"]:
    o = df[df["outcome"] == outcome]
    no = len(o)
    if no == 0:
        continue
    pnl = o["pnl_usd"].sum()
    avg_t = o["pnl_ticks"].mean()
    median_t = o["pnl_ticks"].median()
    pos = (o["pnl_ticks"] > 0).sum()
    print(f"  {outcome:>8s} | n={no:>3d} ({no/n*100:.1f}%) | PnL=${pnl:+.2f} | avg={avg_t:+.1f}t | median={median_t:+.1f}t | n>0={pos}")

# ── SESSION ──────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  5. STATS PAR SESSION (UTC entry time)")
print("=" * 70)
def session_of(ts_str):
    if not ts_str:
        return "UNKNOWN"
    try:
        dt = pd.to_datetime(ts_str, utc=True)
        h = dt.hour
        # Asia: 22:00-06:00 UTC, London: 06:00-13:30 UTC, RTH: 13:30-21:00 UTC
        if 22 <= h or h < 6:
            return "ASIA"
        elif 6 <= h < 13:
            return "LONDON"
        elif 13 <= h < 21:
            return "RTH"
        else:
            return "POST"
    except (TypeError, ValueError):
        return "UNKNOWN"
df["session"] = df["entry_time"].apply(session_of)
for sess in ["ASIA", "LONDON", "RTH", "POST", "UNKNOWN"]:
    s = df[df["session"] == sess]
    ns = len(s)
    if ns == 0:
        continue
    ws = (s["pnl_ticks"] > 0).sum()
    pnl = s["pnl_usd"].sum()
    pf_s = s[s["pnl_ticks"] > 0]["pnl_usd"].sum() / max(abs(s[s["pnl_ticks"] < 0]["pnl_usd"].sum()), 1e-9)
    print(f"  {sess:>7s} | n={ns:>3d} | WR={ws/ns*100:.1f}% | PF={pf_s:.2f} | PnL=${pnl:+.2f}")

# ── OUTLIER TEST ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  6. OUTLIER-DRIVEN TEST (retrait du top trade)")
print("=" * 70)
top = df.nlargest(1, "pnl_usd").iloc[0]
print(f"  Top trade : {top['entry_time']} {top['symbol']} {top.get(dir_col,'?')} +{top['pnl_ticks']:.0f}t ${top['pnl_usd']:+.2f}")
df_no_top = df[df.index != top.name]
net_no_top = df_no_top["pnl_usd"].sum()
gw = df_no_top[df_no_top["pnl_ticks"] > 0]["pnl_usd"].sum()
gl = abs(df_no_top[df_no_top["pnl_ticks"] < 0]["pnl_usd"].sum())
pf_no_top = gw / gl if gl > 0 else float("inf")
print(f"  PnL sans top : ${net_no_top:+.2f} (vs ${net:+.2f} = {top['pnl_usd']/net*100:.1f}% du PnL si net>0)")
print(f"  PF sans top  : {pf_no_top:.2f} (vs {pf:.2f})")
print(f"  Edge fragile : {'OUI' if pf_no_top < 1 and pf >= 1 else 'NON'}")

# ── PATTERN SL CONSECUTIFS ────────────────────────────────────────
print("\n" + "=" * 70)
print("  7. PATTERN SL CONSECUTIFS MEME DIRECTION (pattern 11 V1 ?)")
print("=" * 70)
df_sorted = df.sort_values("entry_time").reset_index(drop=True)
streaks = []
current_streak = 0
current_dir = None
for _, row in df_sorted.iterrows():
    if row["outcome"] == "SL" and row[dir_col] == current_dir:
        current_streak += 1
    else:
        if current_streak >= 2:
            streaks.append((current_streak, current_dir))
        current_streak = 1 if row["outcome"] == "SL" else 0
        current_dir = row[dir_col] if row["outcome"] == "SL" else None
if current_streak >= 2:
    streaks.append((current_streak, current_dir))
print(f"  Streaks SL consecutifs (>=2) : {len(streaks)}")
for n, d in streaks:
    print(f"    {n} SL {d} consecutifs")
max_streak = max((n for n, _ in streaks), default=0)
print(f"  Max streak : {max_streak}")

# ── SLIPPAGE (Action #1 instrumentation) ────────────────────────
print("\n" + "=" * 70)
print("  8. SLIPPAGE EXIT (instrumentation Action #1)")
print("=" * 70)
if "slip_exit_calc" in df.columns or "slip_exit_ticks" in df.columns:
    col = "slip_exit_calc" if "slip_exit_calc" in df.columns else "slip_exit_ticks"
    sl_trades = df[df["outcome"] == "SL"]
    if len(sl_trades) > 0 and col in sl_trades.columns:
        slips = pd.to_numeric(sl_trades[col], errors="coerce").dropna()
        if len(slips) > 0:
            print(f"  N SL trades avec slip data : {len(slips)}")
            print(f"  Slippage median : {slips.median():+.1f}t")
            print(f"  Slippage mean   : {slips.mean():+.1f}t")
            print(f"  Slippage worst  : {slips.min():+.1f}t")
        else:
            print(f"  Pas de donnees slip exploitables (col {col} vide ou nan)")
    else:
        print(f"  Pas de SL trades ou colonne manquante")
else:
    print("  ❌ Aucune colonne slippage instrumentee — instrumentation midi non encore appliquee aux trades du jour")
    print(f"     Colonnes presentes : {[c for c in df.columns if 'slip' in c.lower() or 'sl_' in c.lower()][:10]}")

# ── HEURE PAR HEURE ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("  9. DISTRIBUTION HORAIRE (UTC)")
print("=" * 70)
df["hour_utc"] = df["entry_time"].apply(lambda x: pd.to_datetime(x, utc=True).hour if x else -1)
for h in sorted(df["hour_utc"].unique()):
    if h < 0:
        continue
    h_df = df[df["hour_utc"] == h]
    pnl = h_df["pnl_usd"].sum()
    n_h = len(h_df)
    if n_h:
        print(f"  {h:>2d}h | n={n_h:>2d} | PnL=${pnl:+.2f}")

print("\n" + "=" * 70)
print("FIN AUDIT — pour dispatch agent market-analyst")
print("=" * 70)
