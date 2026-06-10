"""Audit FORENSIQUE profond session 29/04 — Bot 1 + cross-bot + impact $ par bug."""
import json
from pathlib import Path
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")


def load_trades(fp):
    rows = []
    if not fp.exists():
        return pd.DataFrame()
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    rows.append(json.loads(s))
                except json.JSONDecodeError:
                    pass
    return pd.DataFrame(rows)


# Bot 1 + Bot 2 cumul
df1 = load_trades(PAPER_DIR / "20260429_trades.jsonl")
df2 = load_trades(PAPER_DIR / "20260429_databento_trades.jsonl")
df1["entry_dt"] = pd.to_datetime(df1["entry_time"], errors="coerce")
df2["entry_dt"] = pd.to_datetime(df2["entry_time"], errors="coerce")
df1 = df1.sort_values("entry_dt").reset_index(drop=True)
df2 = df2.sort_values("entry_dt").reset_index(drop=True)

print("="*80)
print("  AUDIT FORENSIQUE SESSION 29/04 — IMPACT $ PAR BUG")
print("="*80)

# Helper conversion
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}
def usd(t, sym, n=3):
    return t * TICK_VALUE.get(sym, 1.0) * n


# ============================================================
# 1. STATS GLOBALES
# ============================================================
print("\n[1] STATS GLOBALES")
print("-"*80)
for label, df in [("BOT 1 Sim3", df1), ("BOT 2 Sim2", df2)]:
    if df.empty:
        continue
    df["_pnl"] = pd.to_numeric(df.get("pnl_ticks", 0), errors="coerce").fillna(0)
    df["_usd"] = pd.to_numeric(df.get("pnl_usd", 0), errors="coerce").fillna(0)
    n = len(df)
    n_w = (df["_pnl"] > 0).sum()
    print(f"  {label}: n={n}, WR={n_w/n*100:.0f}%, PnL={df['_pnl'].sum():+.0f}t / "
          f"${df['_usd'].sum():+.2f}")

# ============================================================
# 2. ANALYSE TIMEOUTs : MFE perdu = revenu potentiel TP partiel
# ============================================================
print("\n[2] TIMEOUTs — REVENU POTENTIEL si TP partiel @ 1.5R")
print("-"*80)
to1 = df1[df1["outcome"] == "TIMEOUT"].copy()
to1["_mfe"] = pd.to_numeric(to1["mfe"], errors="coerce").fillna(0)
print(f"\n  TIMEOUTs Bot 1: {len(to1)}/{len(df1)}")
n_high_mfe = (to1["_mfe"] >= 30).sum()
n_med_mfe = ((to1["_mfe"] >= 10) & (to1["_mfe"] < 30)).sum()
n_low_mfe = (to1["_mfe"] < 10).sum()
print(f"    MFE >= 30t (gros mouvement raté) : {n_high_mfe}")
print(f"    MFE 10-29t (mouvement modéré)    : {n_med_mfe}")
print(f"    MFE <  10t (chop pur)             : {n_low_mfe}")

# Calcul revenu si TP partiel @ 50% à 1.5R (= sl_ticks * 1.5 lock)
# On prend 50% × min(MFE, 1.5R) capturé
rev_partial = 0
for _, t in to1.iterrows():
    sl_t = pd.to_numeric(t.get("sl_ticks"), errors="coerce")
    mfe = float(t["_mfe"])
    if pd.isna(sl_t) or sl_t == 0:
        continue
    target = sl_t * 1.5  # TP1 à 1.5R
    captured = min(mfe, target)
    if captured > 0:
        rev_partial += captured * 0.5  # 50% taille à TP1
        runner = max(0, mfe - target) * 0.5  # 50% runner (si MFE > 1.5R)
        rev_partial += runner * 0.7  # discount 70% (runner pas toujours TP final)
    pnl_t = pd.to_numeric(t.get("pnl_ticks"), errors="coerce") or 0
    sym = t.get("symbol", "ES")
    rev_partial -= pnl_t  # on retire le pnl actuel pour estimer LE GAIN
print(f"\n  Revenu additionnel TP partiel estimé : {rev_partial:+.0f}t (vs PnL TIMEOUT actuel)")

# ============================================================
# 3. ANALYSE BIAS : combien de SL d'affilée avant le 1 SHORT switch
# ============================================================
print("\n[3] BIAIS — RUN LENGTH / CHANGEMENT DIRECTION")
print("-"*80)
runs = []
cur = [df1.iloc[0]]
for i in range(1, len(df1)):
    if df1.iloc[i]["direction"] == cur[-1]["direction"]:
        cur.append(df1.iloc[i])
    else:
        runs.append(cur)
        cur = [df1.iloc[i]]
runs.append(cur)
print(f"\n  Runs same direction Bot 1:")
for r in runs:
    if len(r) == 0: continue
    f = r[0]; l = r[-1]
    sl_count = sum(1 for x in r if x.get("outcome") == "SL")
    pnl = sum(pd.to_numeric(x.get("pnl_ticks", 0), errors="coerce") or 0 for x in r)
    duration = (l["entry_dt"] - f["entry_dt"]).total_seconds() / 60
    print(f"    {f['direction']:5s} run de {len(r):>2d} trades : "
          f"{str(f['entry_dt'])[11:16]} → {str(l['entry_dt'])[11:16]} "
          f"({duration:>5.0f}min) SL={sl_count} PnL={pnl:+.0f}t")

# Compteur SL consecutifs avant switch
sl_consec_before_switch = 0
prev_dir = None
for _, t in df1.iterrows():
    if prev_dir is not None and t["direction"] != prev_dir:
        break
    if t.get("outcome") == "SL":
        sl_consec_before_switch += 1
    prev_dir = t["direction"]

# Position du 1 SHORT dans la séquence
n_before_short = 0
for _, t in df1.iterrows():
    if t["direction"] == "SHORT":
        break
    n_before_short += 1
print(f"\n  Nb trades AVANT le 1 SHORT (13:34) : {n_before_short}")
print(f"  Soit 17h+ de bias BULL avant le seul switch")

# ============================================================
# 4. CROSS-INSTRUMENT : trades ES + NQ proches (corrélation perte)
# ============================================================
print("\n[4] CROSS-INSTRUMENT — paires ES+NQ < 30 min même direction")
print("-"*80)
n_pairs = 0
n_both_loss = 0
n_both_win = 0
total_loss_correlated = 0
for i, t in df1.iterrows():
    sym = t["symbol"]
    other = "NQ" if sym == "ES" else "ES"
    later = df1[(df1["symbol"] == other) &
                 (df1["direction"] == t["direction"]) &
                 (df1["entry_dt"] > t["entry_dt"]) &
                 ((df1["entry_dt"] - t["entry_dt"]) < pd.Timedelta(minutes=30))]
    if not later.empty:
        n_pairs += 1
        next_t = later.iloc[0]
        pnl1 = pd.to_numeric(t.get("pnl_ticks", 0), errors="coerce") or 0
        pnl2 = pd.to_numeric(next_t.get("pnl_ticks", 0), errors="coerce") or 0
        if pnl1 < 0 and pnl2 < 0:
            n_both_loss += 1
            usd_loss = usd(pnl1, sym) + usd(pnl2, other)
            total_loss_correlated += usd_loss
        elif pnl1 > 0 and pnl2 > 0:
            n_both_win += 1
print(f"\n  Pairs ES+NQ same dir < 30 min : {n_pairs}")
print(f"  Both LOSS : {n_both_loss} (corrélation perte = doublement risk)")
print(f"  Both WIN  : {n_both_win}")
print(f"  Perte $ corrélée additionnelle : ${total_loss_correlated:.2f}")

# ============================================================
# 5. IMPACT TRADE 14:13 +176t (luck or skill ?)
# ============================================================
print("\n[5] IMPACT TRADE GAGNANT 14:13 NQ LONG +176t")
print("-"*80)
df1["_pnl"] = pd.to_numeric(df1.get("pnl_ticks", 0), errors="coerce").fillna(0)
total_pnl = df1["_pnl"].sum()
total_pnl_usd = pd.to_numeric(df1["pnl_usd"], errors="coerce").sum()
big_win = df1.loc[df1["_pnl"] > 100]
print(f"\n  Trades > +100t : {len(big_win)}")
for _, t in big_win.iterrows():
    print(f"    {str(t['entry_dt'])[11:19]} {t['symbol']} {t['direction']} "
          f"+{t['_pnl']:.0f}t / ${pd.to_numeric(t['pnl_usd'], errors='coerce'):+.2f}")
if not big_win.empty:
    sans = total_pnl - big_win["_pnl"].sum()
    sans_usd = total_pnl_usd - pd.to_numeric(big_win["pnl_usd"], errors="coerce").sum()
    print(f"\n  Total PnL session : {total_pnl:+.0f}t / ${total_pnl_usd:+.2f}")
    print(f"  PnL SANS le big win 14:13 : {sans:+.0f}t / ${sans_usd:+.2f}")
    print(f"  → l'edge tient à 1 trade (variance / luck)")

# ============================================================
# 6. SL EVITES si "STOP after 3 SL same dir"
# ============================================================
print("\n[6] FIX #1 SIMULATION — STOP after 3 SL same direction")
print("-"*80)
sl_count_dir = 0
trades_evitees = []
last_dir = None
for _, t in df1.iterrows():
    if t.get("direction") != last_dir:
        sl_count_dir = 0
    last_dir = t.get("direction")
    if sl_count_dir >= 3:
        trades_evitees.append(t)
        continue
    if t.get("outcome") == "SL":
        sl_count_dir += 1
print(f"\n  Trades qui auraient été bloqués : {len(trades_evitees)}")
gain = 0
for t in trades_evitees:
    pnl_t = pd.to_numeric(t.get("pnl_ticks", 0), errors="coerce") or 0
    sym = t.get("symbol", "ES")
    g = usd(-pnl_t, sym)  # bloquer = inverser le pnl (négatif devient positif)
    gain += g
    print(f"    {str(t['entry_dt'])[11:19]} {t['symbol']} {t['direction']} "
          f"{t.get('outcome')} {pnl_t:+.0f}t = ${usd(pnl_t, sym):+.2f}")
print(f"\n  Gain $ si bloqués : ${gain:+.2f}")

print("\n" + "="*80)
print("  FIN AUDIT")
print("="*80)
