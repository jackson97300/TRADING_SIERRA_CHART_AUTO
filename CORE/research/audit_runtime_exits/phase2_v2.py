"""
Phase 2 v2 — Match avec parquet V4 et reconstruction trajectoire intra-bar
"""
import json, pandas as pd, numpy as np
from pathlib import Path

PAPER_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
PARQUET_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")
TICK = 0.25

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

# Load parquet 04-2026
df_nq = pd.read_parquet(PARQUET_DIR / "symbol=NQ.c.0/year=2026/month=04/data.parquet")
df_es = pd.read_parquet(PARQUET_DIR / "symbol=ES.c.0/year=2026/month=04/data.parquet")
df_nq['ts_event'] = pd.to_datetime(df_nq['ts_event']).dt.tz_localize('UTC')
df_es['ts_event'] = pd.to_datetime(df_es['ts_event']).dt.tz_localize('UTC')
df_nq = df_nq.set_index('ts_event').sort_index()
df_es = df_es.set_index('ts_event').sort_index()

results = []
for t in trades:
    sym = t['symbol']
    df_src = df_nq if sym == 'NQ' else df_es
    entry_t = pd.to_datetime(t['entry_time'])
    exit_t = pd.to_datetime(t['exit_time'])
    if entry_t.tz is None: entry_t = entry_t.tz_localize('UTC')
    if exit_t.tz is None: exit_t = exit_t.tz_localize('UTC')

    # Bars apres entry, jusqu'a exit
    sub = df_src.loc[entry_t : exit_t]
    if len(sub) == 0: continue

    direction = t['direction']
    entry_p = t['entry_price']

    # Trajectoire MFE/MAE par bar (running cumulative)
    if direction == 'LONG':
        run_mfe = (sub['high'] - entry_p).cummax() / TICK
        run_mae = (sub['low'] - entry_p).cummin() / TICK
    else:
        run_mfe = (entry_p - sub['low']).cummax() / TICK
        run_mae = (entry_p - sub['high']).cummin() / TICK

    # Bar idx ou MFE max atteint
    mfe_peak_bar_idx = int(np.argmax(run_mfe.values))  # index 0..N-1 dans sub
    bars_to_mfe_peak = mfe_peak_bar_idx + 1  # 1-based

    bar_at_mfe = sub.iloc[mfe_peak_bar_idx]
    mfe_peak_ticks = float(run_mfe.iloc[mfe_peak_bar_idx])

    # Niveaux au moment du MFE peak (en ticks abs)
    levels_to_check = ['dist_cur_vah', 'dist_cur_val', 'dist_cur_vpoc',
                       'dist_vwap_d_sd1u', 'dist_vwap_d_sd1d',
                       'dist_vwap_d_sd2u', 'dist_vwap_d_sd2d',
                       'dist_vwap_d_sd3u', 'dist_vwap_d_sd3d',
                       'dist_gex_nearest_up', 'dist_gex_nearest_dn',
                       'dist_mq_call', 'dist_mq_put', 'dist_mq_hvl',
                       'dist_ib_high', 'dist_ib_low']

    # Pour LONG : niveaux de RESISTANCE = dist > 0 (au-dessus). Convertir en ticks.
    # dist_X est deja en POINTS dans v4 (typiquement). On divise par TICK pour ticks.
    levels_in_pts = {}
    for col in levels_to_check:
        v = bar_at_mfe.get(col)
        if v is None or pd.isna(v): continue
        levels_in_pts[col] = float(v)

    # Niveau pertinent : direction LONG -> resistance au-dessus (dist > 0)
    #                    direction SHORT -> support en dessous (dist < 0)
    threshold_ticks = 8  # 2 points = 8 ticks tolerance
    relevant = {}
    for k, v_pts in levels_in_pts.items():
        v_ticks = v_pts / TICK
        if direction == 'LONG' and 0 < v_ticks <= threshold_ticks:
            relevant[k] = v_ticks
        elif direction == 'SHORT' and -threshold_ticks <= v_ticks < 0:
            relevant[k] = v_ticks

    closest_lvl_name = min(relevant.items(), key=lambda x: abs(x[1]))[0] if relevant else None
    closest_lvl_dist = min(relevant.values(), key=abs) if relevant else None

    results.append({
        'trade_id': t['trade_id'],
        'symbol': sym,
        'direction': direction,
        'outcome': t['outcome'],
        'pnl_ticks': t['pnl_ticks'],
        'mfe_stored': t['mfe'],
        'mae_stored': t['mae'],
        'mfe_peak_recomp_ticks': mfe_peak_ticks,
        'bars_to_mfe_peak': bars_to_mfe_peak,
        'bars_held': len(sub),
        'frac_to_mfe': bars_to_mfe_peak / max(len(sub), 1),
        'has_level_within_8t_at_mfe': len(relevant) > 0,
        'n_levels_close': len(relevant),
        'closest_lvl_name': closest_lvl_name,
        'closest_lvl_dist_ticks': closest_lvl_dist,
    })

res = pd.DataFrame(results)
print(f"=== Phase 2 : matched {len(res)}/{len(trades)} trades ===\n")

print("Coherence MFE stocke vs MFE recompute parquet :")
print(f"  median delta = {(res.mfe_peak_recomp_ticks - res.mfe_stored).median():.1f}t")
print(f"  mean delta = {(res.mfe_peak_recomp_ticks - res.mfe_stored).mean():.1f}t")
print()

# Bars to MFE peak : critical info pour calibrer trailing
print("=== Bars to MFE peak (= combien de minutes apres entry on touche le high) ===")
print(f"  median bars_to_mfe = {res.bars_to_mfe_peak.median():.0f}")
print(f"  median bars_held   = {res.bars_held.median():.0f}")
print(f"  median fraction    = {res.frac_to_mfe.median():.2%}")
print()

# % MFE peak fin de trade vs early
res['mfe_position'] = pd.cut(res['frac_to_mfe'], bins=[0, 0.25, 0.5, 0.75, 1.0],
                              labels=['Q1_early','Q2','Q3','Q4_late'])
print("Distribution position MFE peak :")
print(res['mfe_position'].value_counts().sort_index())
print()

# === Niveau proche au MFE peak ? ===
print("=== Niveau (HVN/VAH/VAL/SD/GEX) dans 8t du MFE peak ? ===")
n_lvl = res['has_level_within_8t_at_mfe'].sum()
print(f"  N={n_lvl}/{len(res)} = {n_lvl/len(res)*100:.0f}%")
print()
print("Top niveaux qui marquent les MFE peaks :")
print(res['closest_lvl_name'].value_counts().head(10))
print()

# Stats par outcome
print("=== Comparaison outcomes : presence niveau au MFE peak ===")
for oc in ['TP', 'TIMEOUT', 'SL']:
    sub = res[res['outcome']==oc]
    if len(sub) == 0: continue
    pct_lvl = sub['has_level_within_8t_at_mfe'].mean()*100
    print(f"  {oc:8s} N={len(sub):2d}  has_lvl_at_peak={pct_lvl:.0f}%  MFE_med={sub['mfe_peak_recomp_ticks'].median():.0f}t")

res.to_pickle("D:/TRADING_SIERRA_CHART_AUTO/CORE/research/audit_runtime_exits/phase2_match_v2.pkl")
print("\nSaved phase2_match_v2.pkl")
