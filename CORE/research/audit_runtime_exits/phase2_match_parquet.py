"""
Phase 2 — Match trades Bot 1 -> parquet V4 minute bars
Reconstruire trajectoires intra-trade pour eviter biais de Phase 1
"""
import json, pandas as pd, numpy as np
from pathlib import Path

PAPER_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
PARQUET_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")

# Load trades
trades = []
for f in sorted(PAPER_DIR.glob("*_trades.jsonl")):
    if "databento" in f.name: continue
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try: trades.append(json.loads(line))
            except: pass

# Load parquet 04-2026 NQ + ES
df_nq = pd.read_parquet(PARQUET_DIR / "symbol=NQ.c.0/year=2026/month=04/data.parquet")
df_es = pd.read_parquet(PARQUET_DIR / "symbol=ES.c.0/year=2026/month=04/data.parquet")

# Convertir en TZ aware UTC
df_nq['ts_event'] = pd.to_datetime(df_nq['ts_event']).dt.tz_localize('UTC')
df_es['ts_event'] = pd.to_datetime(df_es['ts_event']).dt.tz_localize('UTC')

# Set index timestamp
df_nq = df_nq.set_index('ts_event').sort_index()
df_es = df_es.set_index('ts_event').sort_index()

# Pour chaque trade : extraire les bars entre entry_time et exit_time
print(f"NQ parquet : {len(df_nq)} bars  range {df_nq.index.min()} -> {df_nq.index.max()}")
print(f"ES parquet : {len(df_es)} bars  range {df_es.index.min()} -> {df_es.index.max()}")
print()

results = []
for t in trades:
    sym = t['symbol']
    df_src = df_nq if sym == 'NQ' else df_es
    entry_t = pd.to_datetime(t['entry_time'])
    exit_t = pd.to_datetime(t['exit_time'])
    if entry_t.tz is None: entry_t = entry_t.tz_localize('UTC')
    if exit_t.tz is None: exit_t = exit_t.tz_localize('UTC')
    # Bars dans [entry, exit]
    sub = df_src.loc[entry_t : exit_t]
    if len(sub) == 0: continue

    direction = t['direction']
    entry_p = t['entry_price']
    sl_p = t['sl_price']
    tp_p = t['tp_price']
    TICK = 0.25

    # Trajectoire MFE/MAE par bar (monotone running)
    if direction == 'LONG':
        run_mfe_pts = (sub['high'] - entry_p).cummax()
        run_mae_pts = (sub['low'] - entry_p).cummin()
    else:
        run_mfe_pts = (entry_p - sub['low']).cummax()
        run_mae_pts = (entry_p - sub['high']).cummin()

    # Bar idx ou MFE max atteint
    if direction == 'LONG':
        idx_mfe_max = (sub['high']).idxmax()
    else:
        idx_mfe_max = (sub['low']).idxmin()

    bars_to_mfe = list(sub.index).index(idx_mfe_max) + 1 if idx_mfe_max in sub.index else len(sub)

    # Niveaux au moment du MFE max
    bar_at_mfe = sub.loc[idx_mfe_max]
    levels_at_mfe = {
        'dist_cur_vah_ticks': bar_at_mfe.get('dist_cur_vah'),
        'dist_cur_val_ticks': bar_at_mfe.get('dist_cur_val'),
        'dist_cur_vpoc_ticks': bar_at_mfe.get('dist_cur_vpoc'),
        'dist_vwap_d_sd1u': bar_at_mfe.get('dist_vwap_d_sd1u'),
        'dist_vwap_d_sd1d': bar_at_mfe.get('dist_vwap_d_sd1d'),
        'dist_vwap_d_sd2u': bar_at_mfe.get('dist_vwap_d_sd2u'),
        'dist_vwap_d_sd2d': bar_at_mfe.get('dist_vwap_d_sd2d'),
        'dist_gex_up': bar_at_mfe.get('dist_gex_nearest_up'),
        'dist_gex_dn': bar_at_mfe.get('dist_gex_nearest_dn'),
        'dist_mq_call': bar_at_mfe.get('dist_mq_call'),
        'dist_mq_put': bar_at_mfe.get('dist_mq_put'),
        'dist_mq_hvl': bar_at_mfe.get('dist_mq_hvl'),
    }

    # Test : un niveau qui aurait fait sortir le trade au MFE max
    mfe_pts = run_mfe_pts.iloc[-1]  # MFE final
    mfe_at_max_pts = (bar_at_mfe['high'] - entry_p) if direction == 'LONG' else (entry_p - bar_at_mfe['low'])

    # Niveau critique : un de ces niveaux dans les +/- 4 ticks (1 point) du high MFE ?
    # Pour LONG : niveau "dist_X" represente la distance au prix actuel. Si LONG monte, prix >= entry
    # Niveau de RESISTANCE (au-dessus) qui pourrait stopper : un dist_X > 0 et faible (~1pt = 4 ticks)
    threshold_ticks = 4  # 1 point = 4 ticks
    levels_close = {}
    for k, v in levels_at_mfe.items():
        if v is not None and not pd.isna(v):
            if direction == 'LONG' and 0 < v <= threshold_ticks:
                levels_close[k] = v  # niveau resistance proche au-dessus
            elif direction == 'SHORT' and -threshold_ticks <= v < 0:
                levels_close[k] = v
    has_resistance_at_mfe = len(levels_close) > 0

    results.append({
        'trade_id': t['trade_id'],
        'symbol': sym,
        'direction': direction,
        'outcome': t['outcome'],
        'pnl_ticks': t['pnl_ticks'],
        'mfe_stored': t['mfe'],
        'mfe_recomputed_pts': float(mfe_pts),
        'mfe_recomputed_ticks': float(mfe_pts / TICK),
        'bars_to_mfe': bars_to_mfe,
        'bars_held': len(sub),
        'has_level_at_mfe': has_resistance_at_mfe,
        'n_levels_close_at_mfe': len(levels_close),
        'closest_level_name': min(levels_close.items(), key=lambda x: abs(x[1]))[0] if levels_close else None,
        'closest_level_dist_ticks': min(levels_close.values(), key=abs) if levels_close else None,
    })

res = pd.DataFrame(results)
print(f"=== Match parquet : {len(res)}/{len(trades)} trades matchent V4 ===")
print()
print("Coherence MFE stocke vs MFE recompute (devraient etre proches) :")
res['delta_mfe'] = res['mfe_recomputed_ticks'] - res['mfe_stored']
print(f"  median delta = {res['delta_mfe'].median():.1f}t  mean = {res['delta_mfe'].mean():.1f}t")
print()
print("Bars to MFE peak :")
print(f"  median = {res['bars_to_mfe'].median():.0f}  mean = {res['bars_to_mfe'].mean():.1f}")
print(f"  bars_held med = {res['bars_held'].median():.0f}")
print(f"  ratio bars_to_mfe / bars_held median = {(res['bars_to_mfe']/res['bars_held']).median():.2f}")
print()
print("=== Phase 2 finding : niveau proche au moment du MFE peak ? ===")
n_with_level = res['has_level_at_mfe'].sum()
print(f"% trades avec niveau dans +/-4t au moment MFE peak : {n_with_level}/{len(res)} = {n_with_level/len(res)*100:.0f}%")
print()
print("Distribution closest_level_name (top niveaux qui marquent les MFE peaks) :")
print(res['closest_level_name'].value_counts().head(15))
print()

# Stats par outcome
print("=== Stats has_level_at_mfe par outcome ===")
for oc in res['outcome'].unique():
    sub = res[res['outcome']==oc]
    pct = sub['has_level_at_mfe'].mean()*100
    print(f"  {oc:8s}  N={len(sub):2d}  has_level_at_mfe={pct:.0f}%  MFE_med={sub['mfe_recomputed_ticks'].median():.0f}t")

res.to_pickle("D:/TRADING_SIERRA_CHART_AUTO/CORE/research/audit_runtime_exits/phase2_match.pkl")
print("\nSaved phase2_match.pkl")
