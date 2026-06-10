"""
Phase 1b — Analyse fine MFE / outcomes / lecon-cle
"""
import json, pandas as pd, numpy as np
from pathlib import Path

PAPER_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
trades = []
for f in sorted(PAPER_DIR.glob("*_trades.jsonl")):
    if "databento" in f.name: continue
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try: trades.append(json.loads(line))
            except: pass

df = pd.DataFrame(trades)
TICK = 0.25
df['mfe'] = pd.to_numeric(df['mfe'], errors='coerce')
df['mae'] = pd.to_numeric(df['mae'], errors='coerce')
df['pnl_ticks'] = pd.to_numeric(df['pnl_ticks'], errors='coerce')
df['sl_dist_ticks'] = (df['sl_price'] - df['entry_price']).abs() / TICK
df['tp_dist_ticks'] = (df['tp_price'] - df['entry_price']).abs() / TICK
df['mfe_pct_sl'] = df['mfe'] / df['sl_dist_ticks']
df['mfe_pct_tp'] = df['mfe'] / df['tp_dist_ticks']

# === ANALYSE OUTCOME ===
print("=== Distribution MFE par outcome ===")
for oc in df['outcome'].unique():
    sub = df[df['outcome'] == oc]
    print(f"  {oc:8s} N={len(sub):2d}  MFE_med={sub['mfe'].median():5.1f}t  "
          f"MFE_max={sub['mfe'].max():5.1f}t  PnL_med={sub['pnl_ticks'].median():+5.1f}t  "
          f"PnL_sum={sub['pnl_ticks'].sum():+5.0f}t")

# Trades qui ont touche +20t puis sont reparti: combien sont SL vs TIMEOUT?
print("\n=== Trades MFE >= 20t (n=...) ===")
big_mfe = df[df['mfe'] >= 20]
print(f"N total: {len(big_mfe)}")
for oc in big_mfe['outcome'].value_counts().index:
    sub = big_mfe[big_mfe['outcome'] == oc]
    print(f"  {oc:8s} N={len(sub):2d}  MFE_med={sub['mfe'].median():5.1f}t  PnL_med={sub['pnl_ticks'].median():+5.1f}t")

# Strategy A : BE move @ ratio (test plusieurs seuils)
print("\n=== Strategy A : BE move - sensibilite seuil ===")
for thr in [0.30, 0.40, 0.50, 0.60, 0.70, 1.00]:
    df[f'pnl_be_{thr}'] = np.where(
        df['mfe_pct_sl'] >= thr,
        np.where(df['mfe_pct_tp'] >= 1.0, df['tp_dist_ticks'], 0.0),
        df['pnl_ticks']
    )
    delta = df[f'pnl_be_{thr}'].sum() - df['pnl_ticks'].sum()
    nb_armed = (df['mfe_pct_sl'] >= thr).sum()
    print(f"  thr={thr:.2f}  PnL_BE={df[f'pnl_be_{thr}'].sum():+5.0f}t  delta={delta:+5.0f}t  N_armed={nb_armed}")

# Strategy B : trailing apres BE (simulation simple : SL = entry + max(MFE-30%ATR, 0))
# trop complexe sans intra-bar -> approx sur MFE final
# On approxime : si BE arme, et MFE final >= 1.5*SL, garde 70% des MFE final
print("\n=== Strategy B (approx) : BE@50% + trail 30%ATR ===")
def hypo_trail(row):
    if pd.isna(row['mfe_pct_sl']): return row['pnl_ticks']
    if row['mfe_pct_sl'] >= 0.5:
        # trailing approx : capture 70% du MFE max si MFE >= 1.5x SL, sinon BE ou TP
        if row['mfe_pct_tp'] >= 1.0:
            return row['tp_dist_ticks']
        if row['mfe_pct_sl'] >= 1.5:
            return row['mfe'] * 0.7
        return 0.0
    return row['pnl_ticks']
df['pnl_trail'] = df.apply(hypo_trail, axis=1)
print(f"  PnL_trail = {df['pnl_trail'].sum():+5.0f}t  delta={df['pnl_trail'].sum()-df['pnl_ticks'].sum():+5.0f}t")

# Strategy C : take 50% partial @ 1R (= 1x SL distance)
print("\n=== Strategy C : Partial 50% @ 1R ===")
def hypo_partial_1R(row):
    if pd.isna(row['mfe_pct_sl']): return row['pnl_ticks']
    if row['mfe_pct_sl'] >= 1.0:
        # 50% sortie a 1R, le reste continue jusqu'a SL ou TP
        # pour simplicity : 50% * SL_dist + 50% * pnl_actuel
        return 0.5 * row['sl_dist_ticks'] + 0.5 * row['pnl_ticks']
    return row['pnl_ticks']
df['pnl_partial_1R'] = df.apply(hypo_partial_1R, axis=1)
print(f"  PnL_partial = {df['pnl_partial_1R'].sum():+5.0f}t  delta={df['pnl_partial_1R'].sum()-df['pnl_ticks'].sum():+5.0f}t")

# Save
df.to_pickle("D:/TRADING_SIERRA_CHART_AUTO/CORE/research/audit_runtime_exits/trades_bot1.pkl")
print("\nSaved trades_bot1.pkl")
