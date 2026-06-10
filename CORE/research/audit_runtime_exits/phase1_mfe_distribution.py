"""
Phase 1 — MFE/MAE distribution Bot 1 reels
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from glob import glob

PAPER_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# Charger tous les trades Bot 1 (exclure databento)
trades = []
for f in sorted(PAPER_DIR.glob("*_trades.jsonl")):
    if "databento" in f.name:
        continue
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                trades.append(t)
            except json.JSONDecodeError:
                continue

print(f"N trades Bot 1 charges : {len(trades)}")
df = pd.DataFrame(trades)
print(f"Colonnes : {list(df.columns)[:30]}")
print()
print(f"Symbol counts: {df['symbol'].value_counts().to_dict()}")
print(f"Outcome counts: {df['outcome'].value_counts().to_dict()}")
print(f"Direction counts: {df['direction'].value_counts().to_dict()}")
print()

# Stats pnl/mae/mfe
df['mfe'] = pd.to_numeric(df['mfe'], errors='coerce')
df['mae'] = pd.to_numeric(df['mae'], errors='coerce')
df['pnl_ticks'] = pd.to_numeric(df['pnl_ticks'], errors='coerce')

print("=== Stats globales ===")
print(f"PnL_ticks  median={df['pnl_ticks'].median():.1f}  mean={df['pnl_ticks'].mean():.2f}  sum={df['pnl_ticks'].sum():.0f}")
print(f"MFE        median={df['mfe'].median():.1f}  mean={df['mfe'].mean():.2f}  p25={df['mfe'].quantile(.25):.1f}  p75={df['mfe'].quantile(.75):.1f}")
print(f"MAE        median={df['mae'].median():.1f}  mean={df['mae'].mean():.2f}  p25={df['mae'].quantile(.25):.1f}  p75={df['mae'].quantile(.75):.1f}")
print()

# SL distance from sl_price/entry_price
def sl_distance_ticks(row):
    if pd.isna(row.get('sl_price')) or pd.isna(row.get('entry_price')):
        return np.nan
    tick = 0.25
    return abs(row['sl_price'] - row['entry_price']) / tick

def tp_distance_ticks(row):
    if pd.isna(row.get('tp_price')) or pd.isna(row.get('entry_price')):
        return np.nan
    tick = 0.25
    return abs(row['tp_price'] - row['entry_price']) / tick

df['sl_dist_ticks'] = df.apply(sl_distance_ticks, axis=1)
df['tp_dist_ticks'] = df.apply(tp_distance_ticks, axis=1)

print(f"SL distance ticks  median={df['sl_dist_ticks'].median():.1f}  mean={df['sl_dist_ticks'].mean():.2f}")
print(f"TP distance ticks  median={df['tp_dist_ticks'].median():.1f}  mean={df['tp_dist_ticks'].mean():.2f}")
print()

# % MFE >= 0.5*SL (candidat BE move)
df['mfe_ratio_sl'] = df['mfe'] / df['sl_dist_ticks']
df['mfe_ratio_tp'] = df['mfe'] / df['tp_dist_ticks']

mfe_ge_50pct_sl = (df['mfe_ratio_sl'] >= 0.5).sum()
mfe_ge_tp = (df['mfe_ratio_tp'] >= 1.0).sum()

print(f"=== Cles diagnostic ===")
print(f"% trades MFE >= 0.5 * SL_dist : {mfe_ge_50pct_sl}/{len(df)} = {mfe_ge_50pct_sl/len(df)*100:.1f}%  (candidat BE move)")
print(f"% trades MFE >= TP            : {mfe_ge_tp}/{len(df)} = {mfe_ge_tp/len(df)*100:.1f}%  (deja gagnants, BE inutile)")
print()

# "Rendu" = MFE > 30 ticks (LONG NQ ~75$) mais exit SL ou TIMEOUT negatif
df['was_in_profit'] = df['mfe'] >= 20  # au moins +20 ticks de favorable
df['ended_loss_or_be'] = df['pnl_ticks'] <= 0
df['rendu'] = df['was_in_profit'] & df['ended_loss_or_be']

n_rendu = df['rendu'].sum()
print(f"Trades 'rendu' (MFE >= 20t puis exit <= 0) : {n_rendu}/{len(df)} = {n_rendu/len(df)*100:.1f}%")
print(f"PnL total des rendus : {df.loc[df['rendu'], 'pnl_ticks'].sum():.0f} ticks")
print(f"MFE total perdu (potentiel) : {df.loc[df['rendu'], 'mfe'].sum():.0f} ticks")
print()

# Hypothetique BE-move @ 50% SL : BE means exit = 0 ticks (- slippage)
def hypothetical_be(row):
    if pd.isna(row['mfe_ratio_sl']):
        return row['pnl_ticks']
    if row['mfe_ratio_sl'] >= 0.5:
        # BE move triggered, then 2 outcomes:
        # 1) MFE >= TP -> exit TP (capture full TP)
        # 2) MFE < TP -> exit BE (0 ticks)
        if row['mfe_ratio_tp'] >= 1.0:
            return row['tp_dist_ticks']
        else:
            return 0.0
    return row['pnl_ticks']  # baseline

df['pnl_hypo_be'] = df.apply(hypothetical_be, axis=1)
print(f"PnL baseline (actuel)     : {df['pnl_ticks'].sum():.0f} ticks")
print(f"PnL hypothetique BE @50%  : {df['pnl_hypo_be'].sum():.0f} ticks")
print(f"Delta BE-move             : {df['pnl_hypo_be'].sum() - df['pnl_ticks'].sum():+.0f} ticks")
print()

# Per symbol
print("=== Par symbole ===")
for sym in df['symbol'].unique():
    sub = df[df['symbol'] == sym]
    pnl_b = sub['pnl_ticks'].sum()
    pnl_h = sub['pnl_hypo_be'].sum()
    n_rdu = sub['rendu'].sum()
    print(f"  {sym}  N={len(sub):3d}  PnL_base={pnl_b:+5.0f}t  PnL_BE={pnl_h:+5.0f}t  Rendu={n_rdu}")

# Sauvegarde dataset enrichi
out = Path("D:/TRADING_SIERRA_CHART_AUTO/CORE/research/audit_runtime_exits/trades_bot1_enriched.parquet")
df.to_parquet(out, index=False)
print(f"\nSauvegarde : {out}")
