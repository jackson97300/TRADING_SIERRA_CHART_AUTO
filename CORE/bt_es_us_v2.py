import pandas as pd
import numpy as np
from scipy import stats as sps

df_us = pd.read_pickle('/tmp/df_us.pkl')
n = len(df_us)

TICK = 0.25
PROXIMITY_PCT = 0.0005
COSTS_TICKS = 2
LOOKAHEAD_BARS = 30

prices_high = df_us['bar_high'].values
prices_low = df_us['bar_low'].values
prices_close = df_us['close'].values
prev_val = df_us['prev_val'].values
prev_vah = df_us['prev_vah'].values
delta_bar = df_us['delta_bar'].values
cvd_dir = df_us['cvd_day_dir'].fillna(0).values
aggressor = df_us['aggressor_imbalance'].fillna(0).values
poc_mig = df_us['poc_migration_dir'].fillna(0).values
va_dev = df_us['ctx_va_developing_10'].fillna(0).values if 'ctx_va_developing_10' in df_us.columns else np.zeros(n)


def classify_scenario(i, side_hyp):
    of_up = delta_bar[i] > 0 and aggressor[i] > 0.2
    of_dn = delta_bar[i] < 0 and aggressor[i] < -0.2
    cvd_up = cvd_dir[i] > 0
    cvd_dn = cvd_dir[i] < 0
    struct_up = poc_mig[i] > 0
    struct_dn = poc_mig[i] < 0
    va_expand = va_dev[i] > 0
    va_contract = va_dev[i] < 0
    if side_hyp == "LONG":
        if struct_up and of_up and cvd_up: return "BREAKOUT_LONG"
        if struct_dn and of_up: return "REJECTION_reversal"
        if struct_up and of_up: return "REJECTION_counter_trend"
        if struct_dn and of_dn: return "BREAKOUT_SHORT"
        if va_contract: return "RANGE_fade"
        if va_expand and struct_up: return "TREND_same_dir"
        return "SKIP"
    else:
        if struct_dn and of_dn and cvd_dn: return "BREAKOUT_SHORT"
        if struct_up and of_dn: return "REJECTION_reversal"
        if struct_dn and of_dn: return "REJECTION_counter_trend"
        if struct_up and of_up: return "BREAKOUT_LONG"
        if va_contract: return "RANGE_fade"
        if va_expand and struct_dn: return "TREND_same_dir"
        return "SKIP"


def scan_touches(level_arr, side, target_ticks, sl_ticks):
    touches = []
    target_pts = target_ticks * TICK
    sl_pts = sl_ticks * TICK
    for i in range(n - LOOKAHEAD_BARS):
        lvl = level_arr[i]
        if not np.isfinite(lvl) or lvl <= 0:
            continue
        proximity = lvl * PROXIMITY_PCT
        if side == "LONG":
            is_touch = (prices_low[i] <= lvl + proximity) and (prices_close[i] > lvl)
        else:
            is_touch = (prices_high[i] >= lvl - proximity) and (prices_close[i] < lvl)
        if not is_touch: continue
        entry_price = prices_close[i]
        scenario = classify_scenario(i, side)
        rejection = False
        invalidated = False
        exit_price = entry_price
        exit_bar = None
        if side == "LONG":
            target = entry_price + target_pts
            invalidation = entry_price - sl_pts
            for j in range(i+1, min(i+1+LOOKAHEAD_BARS, n)):
                # If both hit in same bar, conservative: assume SL hit first
                if prices_low[j] <= invalidation and prices_high[j] >= target:
                    invalidated = True; exit_price = invalidation; exit_bar = j; break
                if prices_low[j] <= invalidation:
                    invalidated = True; exit_price = invalidation; exit_bar = j; break
                if prices_high[j] >= target:
                    rejection = True; exit_price = target; exit_bar = j; break
            if exit_bar is None:
                exit_price = prices_close[min(i+LOOKAHEAD_BARS, n-1)]
        else:
            target = entry_price - target_pts
            invalidation = entry_price + sl_pts
            for j in range(i+1, min(i+1+LOOKAHEAD_BARS, n)):
                if prices_high[j] >= invalidation and prices_low[j] <= target:
                    invalidated = True; exit_price = invalidation; exit_bar = j; break
                if prices_high[j] >= invalidation:
                    invalidated = True; exit_price = invalidation; exit_bar = j; break
                if prices_low[j] <= target:
                    rejection = True; exit_price = target; exit_bar = j; break
            if exit_bar is None:
                exit_price = prices_close[min(i+LOOKAHEAD_BARS, n-1)]
        if side == "LONG":
            pnl_ticks = (exit_price - entry_price) / TICK - COSTS_TICKS
        else:
            pnl_ticks = (entry_price - exit_price) / TICK - COSTS_TICKS
        touches.append({
            'bar_idx': i, 'ts': df_us['ts_event'].iloc[i],
            'price': entry_price, 'level': lvl, 'scenario': scenario,
            'rejection': rejection, 'invalidated': invalidated, 'pnl_ticks': pnl_ticks,
        })
    return pd.DataFrame(touches)


def pf_calc(df):
    wins = df[df['pnl_ticks']>0]['pnl_ticks'].sum()
    losses = -df[df['pnl_ticks']<0]['pnl_ticks'].sum()
    return wins/losses if losses > 0 else float('inf')

print("=== Sensibilite R:R (PVAL ES) ===")
for tp, sl in [(10,10), (12,8), (15,8), (15,10), (20,10), (8,10)]:
    pval_df = scan_touches(prev_val, "LONG", tp, sl)
    print("TP=%dt SL=%dt n=%d rej=%.1f%% pf=%.2f mean_t=%.2f" % (
        tp, sl, len(pval_df), pval_df['rejection'].mean()*100, pf_calc(pval_df), pval_df['pnl_ticks'].mean()))

print("\n=== Sensibilite R:R (PVAH ES) ===")
for tp, sl in [(10,10), (12,8), (15,8), (15,10), (20,10), (8,10)]:
    pvah_df = scan_touches(prev_vah, "SHORT", tp, sl)
    print("TP=%dt SL=%dt n=%d rej=%.1f%% pf=%.2f mean_t=%.2f" % (
        tp, sl, len(pvah_df), pvah_df['rejection'].mean()*100, pf_calc(pvah_df), pvah_df['pnl_ticks'].mean()))

# Top scenarios par config R:R sweet
print("\n=== PVAL ES TP=12 SL=8 (R:R 1.5) breakdown ===")
pval_df = scan_touches(prev_val, "LONG", 12, 8)
for sc, g in pval_df.groupby('scenario'):
    if len(g) >= 20:
        print("  %-28s n=%d rej=%.1f%% pf=%.2f mt=%.2f" % (
            sc, len(g), g['rejection'].mean()*100, pf_calc(g), g['pnl_ticks'].mean()))

print("\n=== PVAH ES TP=12 SL=8 (R:R 1.5) breakdown ===")
pvah_df = scan_touches(prev_vah, "SHORT", 12, 8)
for sc, g in pvah_df.groupby('scenario'):
    if len(g) >= 20:
        print("  %-28s n=%d rej=%.1f%% pf=%.2f mt=%.2f" % (
            sc, len(g), g['rejection'].mean()*100, pf_calc(g), g['pnl_ticks'].mean()))
