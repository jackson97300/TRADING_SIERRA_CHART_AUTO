"""Audit comptabilite Bot 2 Sim2 (databento_paper_trader.py).

Verifie :
1. RR theorique vs RR pratique (apres slippage entry plausible)
2. PnL declare vs PnL plausible apres slippage Databento delay
3. Detection des trades avec RR < 1 (bot perdant garanti)
"""
import json
from pathlib import Path
import pandas as pd

FP = Path("DATA/PAPER_TRADES/20260429_databento_trades.jsonl")
TICK_SIZE = 0.25
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
print("=" * 80)
print("  AUDIT COMPTABILITE BOT 2 Sim2 — 28-29/04/2026")
print("=" * 80)
print(f"N trades : {len(df)}")
print(f"Colonnes interessantes : entry_price, exit_price, sl_ticks, tp_ticks, pnl_ticks, pnl_usd")

# === 1. RR theorique par trade ===
print("\n" + "=" * 80)
print("  1. RR THEORIQUE PAR TRADE (sl_ticks vs tp_ticks declares)")
print("=" * 80)
print(f"{'Time':<19s} {'Sym':<3s} {'Dir':<5s} {'Entry':>9s} {'SL':>7s} {'TP':>7s} {'SL_t':>6s} {'TP_t':>6s} {'RR':>5s} {'Out':<8s} {'PnL_t':>6s}")
print("-" * 100)
for _, t in df.iterrows():
    sl_t = float(t.get("sl_ticks") or 0)
    tp_t = float(t.get("tp_ticks") or 0)
    rr = (tp_t / sl_t) if sl_t > 0 else 0
    pnl_t = float(t.get("pnl_ticks") or 0)
    print(f"{str(t.get('entry_time',''))[:19]:<19s} "
          f"{t.get('symbol',''):<3s} "
          f"{t.get('direction','')[:5]:<5s} "
          f"{float(t.get('entry_price') or 0):>9.2f} "
          f"{float(t.get('sl_price') or t.get('sl') or 0):>7.2f} "
          f"{float(t.get('tp_price') or t.get('tp') or 0):>7.2f} "
          f"{sl_t:>6.1f} "
          f"{tp_t:>6.1f} "
          f"{rr:>5.2f} "
          f"{str(t.get('outcome',''))[:8]:<8s} "
          f"{pnl_t:>+6.0f}")

# === 2. Distribution RR ===
print("\n" + "=" * 80)
print("  2. DISTRIBUTION RR")
print("=" * 80)
df["sl_ticks_n"] = pd.to_numeric(df.get("sl_ticks"), errors="coerce")
df["tp_ticks_n"] = pd.to_numeric(df.get("tp_ticks"), errors="coerce")
df["rr"] = df["tp_ticks_n"] / df["sl_ticks_n"]
print(f"  RR median : {df['rr'].median():.2f}")
print(f"  RR mean   : {df['rr'].mean():.2f}")
print(f"  RR min    : {df['rr'].min():.2f}")
print(f"  RR max    : {df['rr'].max():.2f}")
n_rr_lt_1 = (df["rr"] < 1).sum()
n_rr_lt_15 = (df["rr"] < 1.5).sum()
print(f"  N trades RR < 1.0 : {n_rr_lt_1} ({n_rr_lt_1/len(df)*100:.0f}%)")
print(f"  N trades RR < 1.5 : {n_rr_lt_15} ({n_rr_lt_15/len(df)*100:.0f}%)")

# === 3. PnL theorique declare ===
print("\n" + "=" * 80)
print("  3. PNL DECLARE (BOT)")
print("=" * 80)
df["pnl_usd_n"] = pd.to_numeric(df.get("pnl_usd"), errors="coerce").fillna(0)
df["pnl_ticks_n"] = pd.to_numeric(df.get("pnl_ticks"), errors="coerce").fillna(0)
total_usd = df["pnl_usd_n"].sum()
total_ticks = df["pnl_ticks_n"].sum()
n_wins = (df["pnl_ticks_n"] > 0).sum()
n_loss = (df["pnl_ticks_n"] < 0).sum()
print(f"  N wins / loss : {n_wins} / {n_loss}")
print(f"  PnL ticks total : {total_ticks:+.0f}")
print(f"  PnL USD total   : ${total_usd:+.2f}")

# === 4. Slippage estime sur exit_price (vs sl_price/tp_price declares) ===
print("\n" + "=" * 80)
print("  4. SLIPPAGE EXIT (exit_price vs sl_price/tp_price declares)")
print("=" * 80)
slip_rows = []
for _, t in df.iterrows():
    outcome = t.get("outcome")
    exit_price = float(t.get("exit_price") or 0)
    if not exit_price:
        continue
    if outcome == "TP":
        target = float(t.get("tp_price") or t.get("tp") or 0)
    elif outcome == "SL":
        target = float(t.get("sl_price") or t.get("sl") or 0)
    else:
        continue
    if not target:
        continue
    slip_pts = exit_price - target
    direction = t.get("direction", "")
    # Pour LONG TP : exit > target = bonus, exit < target = slip negatif
    # Pour LONG SL : exit < target = slip negatif (pire), exit > target = bonus
    # Pour SHORT TP : exit < target = bonus
    # Pour SHORT SL : exit > target = slip negatif
    if outcome == "TP":
        slip_signed = (target - exit_price) if direction == "SHORT" else (exit_price - target)
    else:  # SL
        slip_signed = (target - exit_price) if direction == "LONG" else (exit_price - target)
    slip_t = slip_signed / TICK_SIZE
    slip_rows.append({
        "sym": t.get("symbol"),
        "outcome": outcome,
        "direction": direction,
        "target": target,
        "exit": exit_price,
        "slip_t": slip_t,
        "pnl_t": t.get("pnl_ticks"),
    })
slip_df = pd.DataFrame(slip_rows)
if len(slip_df):
    print(f"  N TP/SL avec donnees : {len(slip_df)}")
    print(f"  Slippage exit median : {slip_df['slip_t'].median():+.1f}t")
    print(f"  Slippage exit mean   : {slip_df['slip_t'].mean():+.1f}t")
    print(f"  Slippage exit worst  : {slip_df['slip_t'].min():+.1f}t")
    print(f"\n  Top 5 worst slippage exit :")
    worst = slip_df.nsmallest(5, "slip_t")
    for _, r in worst.iterrows():
        print(f"    {r['sym']} {r['direction'][:5]} {r['outcome']} target={r['target']:.2f} "
              f"exit={r['exit']:.2f} slip={r['slip_t']:+.1f}t")

# === 5. Analyse breakeven WR par RR ===
print("\n" + "=" * 80)
print("  5. WR BREAKEVEN REQUIS PAR RR (PF=1)")
print("=" * 80)
df["wr_breakeven"] = 1 / (1 + df["rr"]) * 100
print(f"  WR breakeven median : {df['wr_breakeven'].median():.0f}%")
print(f"  WR breakeven max    : {df['wr_breakeven'].max():.0f}%")
n_unfeasible = (df["wr_breakeven"] > 60).sum()
print(f"  N trades necessitant WR > 60% pour PF=1 : {n_unfeasible} ({n_unfeasible/len(df)*100:.0f}%)")

# === 6. Concentration outcome ===
print("\n" + "=" * 80)
print("  6. CONCENTRATION OUTCOME")
print("=" * 80)
out_counts = df["outcome"].value_counts()
print(out_counts.to_string())

# === 7. Verdict ===
print("\n" + "=" * 80)
print("  7. VERDICT BOT 2")
print("=" * 80)
print(f"  PnL declare bot : ${total_usd:+.2f}")
print(f"  Trades avec RR < 1 : {n_rr_lt_1}/{len(df)}")
if df["rr"].median() < 1:
    print(f"  ⚠️  RR median < 1 = bot perdant structurellement (sauf WR > 50%)")
print(f"  Slippage exit median : {slip_df['slip_t'].median():+.1f}t (negatif = mauvais fill)")
print(f"  ⚠️  Note : entry_price enregistre = close de bar, pas fill broker reel")
print(f"  ⚠️  Slippage entry NON instrumente (cf bug Databento delay 30min)")
print("=" * 80)
