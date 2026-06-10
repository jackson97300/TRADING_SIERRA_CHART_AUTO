import sys
sys.path.insert(0, 'CORE/research')
from _edge_search_lib import *
import numpy as np

nq = load_trades('NQ')
nq = merge_with_confl(nq, load_confl('NQ'))

# Bootstrap 95% CI sur PF agrege (Lopez)
CORE_PLUS_VWAP = {'IB_LOW', 'MQ_PUT_0DTE', 'MQ_HVL', 'VWAP_W_SD1D'}
mask = nq['level_name'].isin(CORE_PLUS_VWAP) & (nq['confl_count'] >= 1) & nq['session_at_entry'].isin(['LONDON', 'US_CASH'])
g = nq[mask]
pnl = g['pnl_ticks_net'].values

# Bootstrap 1000 iterations
rng = np.random.default_rng(42)
pfs = []
for _ in range(1000):
    sample = rng.choice(pnl, size=len(pnl), replace=True)
    w = sample[sample > 0].sum()
    l = -sample[sample < 0].sum()
    pf = w / l if l > 0 else 5.0
    pfs.append(min(pf, 10.0))

pfs = np.array(pfs)
print(f'Bootstrap PF 95% CI: [{np.quantile(pfs, 0.025):.2f}, {np.quantile(pfs, 0.975):.2f}]')
print(f'Bootstrap PF mean: {pfs.mean():.2f}')
print(f'P(PF < 1.3): {(pfs < 1.3).mean()*100:.1f}%')
print(f'P(PF < 1.0): {(pfs < 1.0).mean()*100:.1f}%')

# Bootstrap CI on Sharpe daily
daily = g.groupby('date')['pnl_ticks_net'].sum().values
srs = []
for _ in range(1000):
    s = rng.choice(daily, size=len(daily), replace=True)
    sr = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else 0
    srs.append(sr)
srs = np.array(srs)
print()
print(f'Bootstrap Sharpe 95% CI: [{np.quantile(srs, 0.025):.2f}, {np.quantile(srs, 0.975):.2f}]')
print(f'P(Sharpe < 1.0): {(srs < 1.0).mean()*100:.1f}%')

# Forward-only test : keep last 30% for OOS
n = len(g)
g_sorted = g.sort_values('entry_dt').reset_index(drop=True)
oos_start = int(n * 0.7)
in_sample = g_sorted.iloc[:oos_start]
oos = g_sorted.iloc[oos_start:]
def pf_calc(d):
    p = d['pnl_ticks_net'].values
    w = p[p > 0].sum(); l = -p[p < 0].sum()
    return w/l if l > 0 else 5.0
print()
print(f'OOS test (last 30%):')
print(f'  In-sample 70% (first 9 mo) : n={len(in_sample)}, PF={pf_calc(in_sample):.2f}, WR={(in_sample["pnl_ticks_net"] > 0).mean()*100:.1f}%')
print(f'  OOS 30% (last 4-5 mo)      : n={len(oos)}, PF={pf_calc(oos):.2f}, WR={(oos["pnl_ticks_net"] > 0).mean()*100:.1f}%')
print(f'  OOS dates: {oos["entry_dt"].min()} -> {oos["entry_dt"].max()}')
