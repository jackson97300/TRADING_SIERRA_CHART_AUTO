import pandas as pd
import numpy as np
from scipy import stats as sps

df_us = pd.read_pickle('/tmp/df_us.pkl')
n = len(df_us)
print("US RTH bars loaded:", n)

TICK = 0.25
PROXIMITY_PCT = 0.0005
REJECTION_TICKS = 10
INVALIDATION_TICKS = 10
LOOKAHEAD_BARS = 30
COSTS_TICKS = 2

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

rej_ticks = REJECTION_TICKS * TICK
inval_ticks = INVALIDATION_TICKS * TICK

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
        if struct_up and of_up and cvd_up:
            return "BREAKOUT_LONG"
        if struct_dn and of_up:
            return "REJECTION_reversal"
        if struct_up and of_up:
            return "REJECTION_counter_trend"
        if struct_dn and of_dn:
            return "BREAKOUT_SHORT"
        if va_contract:
            return "RANGE_fade"
        if va_expand and struct_up:
            return "TREND_same_dir"
        return "SKIP"
    else:
        if struct_dn and of_dn and cvd_dn:
            return "BREAKOUT_SHORT"
        if struct_up and of_dn:
            return "REJECTION_reversal"
        if struct_dn and of_dn:
            return "REJECTION_counter_trend"
        if struct_up and of_up:
            return "BREAKOUT_LONG"
        if va_contract:
            return "RANGE_fade"
        if va_expand and struct_dn:
            return "TREND_same_dir"
        return "SKIP"

def scan_touches(level_arr, side):
    touches = []
    for i in range(n - LOOKAHEAD_BARS):
        lvl = level_arr[i]
        if not np.isfinite(lvl) or lvl <= 0:
            continue
        proximity = lvl * PROXIMITY_PCT
        if side == "LONG":
            is_touch = (prices_low[i] <= lvl + proximity) and (prices_close[i] > lvl)
        else:
            is_touch = (prices_high[i] >= lvl - proximity) and (prices_close[i] < lvl)
        if not is_touch:
            continue
        entry_price = prices_close[i]
        scenario = classify_scenario(i, side)
        rejection = False
        invalidated = False
        exit_price = entry_price
        exit_bar = None
        if side == "LONG":
            target = entry_price + rej_ticks
            invalidation = lvl - inval_ticks
            for j in range(i+1, min(i+1+LOOKAHEAD_BARS, n)):
                if prices_low[j] <= invalidation:
                    invalidated = True
                    exit_price = invalidation
                    exit_bar = j
                    break
                if prices_high[j] >= target:
                    rejection = True
                    exit_price = target
                    exit_bar = j
                    break
            if exit_bar is None:
                exit_price = prices_close[min(i+LOOKAHEAD_BARS, n-1)]
        else:
            target = entry_price - rej_ticks
            invalidation = lvl + inval_ticks
            for j in range(i+1, min(i+1+LOOKAHEAD_BARS, n)):
                if prices_high[j] >= invalidation:
                    invalidated = True
                    exit_price = invalidation
                    exit_bar = j
                    break
                if prices_low[j] <= target:
                    rejection = True
                    exit_price = target
                    exit_bar = j
                    break
            if exit_bar is None:
                exit_price = prices_close[min(i+LOOKAHEAD_BARS, n-1)]
        if side == "LONG":
            pnl_ticks = (exit_price - entry_price) / TICK - COSTS_TICKS
        else:
            pnl_ticks = (entry_price - exit_price) / TICK - COSTS_TICKS
        touches.append({
            'bar_idx': i,
            'ts': df_us['ts_event'].iloc[i],
            'price': entry_price,
            'level': lvl,
            'scenario': scenario,
            'rejection': rejection,
            'invalidated': invalidated,
            'pnl_ticks': pnl_ticks,
        })
    return pd.DataFrame(touches)

pval_df = scan_touches(prev_val, "LONG")
pvah_df = scan_touches(prev_vah, "SHORT")
pval_df.to_pickle('/tmp/pval_es_us.pkl')
pvah_df.to_pickle('/tmp/pvah_es_us.pkl')
print("PVAL ES US RTH touches:", len(pval_df))
print("PVAH ES US RTH touches:", len(pvah_df))

def pf_calc(df):
    wins = df[df['pnl_ticks']>0]['pnl_ticks'].sum()
    losses = -df[df['pnl_ticks']<0]['pnl_ticks'].sum()
    return wins/losses if losses > 0 else float('inf')

def stats_by_scenario(df, label):
    print("\n=== %s Breakdown ===" % label)
    print("%-28s %6s %10s %8s %10s" % ('scenario','n','rej_rate','pf','mean_t'))
    rows = []
    for sc, g in df.groupby('scenario'):
        n_ = len(g)
        rej = g['rejection'].mean()*100
        pf = pf_calc(g)
        mt = g['pnl_ticks'].mean()
        rows.append((sc,n_,rej,pf,mt))
    rows.sort(key=lambda x:-x[1])
    for sc,n_,rej,pf,mt in rows:
        print("%-28s %6d %9.1f%% %8.2f %10.2f" % (sc,n_,rej,pf,mt))
    print("  TOTAL n=%d rej=%.1f%% pf=%.2f mean_t=%.2f" % (len(df), df['rejection'].mean()*100, pf_calc(df), df['pnl_ticks'].mean()))

stats_by_scenario(pval_df, "PVAL ES US RTH")
stats_by_scenario(pvah_df, "PVAH ES US RTH")

def psr(returns):
    n_=len(returns)
    if n_<30: return None,None
    sr = returns.mean()/returns.std() if returns.std()>0 else 0
    skew = sps.skew(returns); kurt = sps.kurtosis(returns)
    denom = np.sqrt(1 - skew*sr + ((kurt-1)/4)*sr**2) / np.sqrt(n_-1)
    if denom==0 or not np.isfinite(denom): return None,sr
    z = sr/denom
    return sps.norm.cdf(z), sr

print("\n=== PSR Lopez ===")
for label,dfx in [("PVAL ES",pval_df),("PVAH ES",pvah_df)]:
    p,sr=psr(dfx['pnl_ticks'].values)
    if p is not None:
        print("%s n=%d SR=%.3f PSR=%.3f" % (label,len(dfx),sr,p))

def walk_forward(df, label, k=12):
    df=df.sort_values('ts').reset_index(drop=True)
    fold_size=len(df)//k
    print("\n=== %s WF %d-fold ===" % (label,k))
    rej_rates=[]; pfs=[]
    for f in range(k):
        start=f*fold_size; end=(f+1)*fold_size if f<k-1 else len(df)
        g=df.iloc[start:end]
        if len(g)==0: continue
        rej=g['rejection'].mean()*100; pf=pf_calc(g); mt=g['pnl_ticks'].mean()
        rej_rates.append(rej); pfs.append(pf if np.isfinite(pf) else 5.0)
        print("f%d n=%d rej=%.1f%% pf=%.2f mt=%.2f %s->%s" % (f+1,len(g),rej,pf,mt,g['ts'].min().date(),g['ts'].max().date()))
    print("  mean rej=%.1f%% std=%.1f mean_pf=%.2f folds_rej>50%%=%d/%d" % (np.mean(rej_rates),np.std(rej_rates),np.mean(pfs),sum(1 for r in rej_rates if r>50),len(rej_rates)))

walk_forward(pval_df,"PVAL ES")
walk_forward(pvah_df,"PVAH ES")
