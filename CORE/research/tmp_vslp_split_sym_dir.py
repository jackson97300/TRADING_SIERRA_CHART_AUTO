"""Backtest VSLP filter SPLIT par sym (ES vs NQ) et direction (LONG vs SHORT).

Repond aux questions :
- ES seul vs ES+NQ : meme edge ou diff ?
- LONG seul vs SHORT vs combo : ou est le vrai edge ?
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import collections

TICK_USD = {'NQ':0.50, 'ES':1.25}

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# Re-utiliser la collecte de tmp_vslp_filter_backtest.py
exec(open('D:/TRADING_SIERRA_CHART_AUTO/CORE/research/tmp_vslp_filter_backtest.py').read().split('# Filter logic')[0])

# Ajouter VSLP si pas deja fait
all_trades_with_vslp = [t for t in all_trades if t.get('vslp') is not None]
print(f'\nTrades avec VSLP : {len(all_trades_with_vslp)}/{len(all_trades)}')

# Split par sym + direction
splits = {
    'ES_LONG':  [t for t in all_trades_with_vslp if t['sym']=='ES' and t['side']=='LONG'],
    'ES_SHORT': [t for t in all_trades_with_vslp if t['sym']=='ES' and t['side']=='SHORT'],
    'NQ_LONG':  [t for t in all_trades_with_vslp if t['sym']=='NQ' and t['side']=='LONG'],
    'NQ_SHORT': [t for t in all_trades_with_vslp if t['sym']=='NQ' and t['side']=='SHORT'],
}

def F_vslp(t, thr):
    vs = t.get('vslp')
    if vs is None: return True
    if t['side'] == 'LONG' and vs <= thr: return False
    if t['side'] == 'SHORT' and vs >= -thr: return False
    return True

def measure(trades, fn):
    pnl = sum(t['pnl_usd'] for t in trades if fn(t))
    w_pass = sum(1 for t in trades if t['pnl_usd']>0 and fn(t))
    w_veto = sum(1 for t in trades if t['pnl_usd']>0 and not fn(t))
    l_pass = sum(1 for t in trades if t['pnl_usd']<0 and fn(t))
    l_veto = sum(1 for t in trades if t['pnl_usd']<0 and not fn(t))
    return pnl, w_pass, w_veto, l_pass, l_veto

for split_name, trades in splits.items():
    if not trades:
        print(f'\n=== {split_name} : 0 trades, skip ===')
        continue
    baseline = sum(t['pnl_usd'] for t in trades)
    nw = sum(1 for t in trades if t['pnl_usd']>0)
    nl = sum(1 for t in trades if t['pnl_usd']<0)
    print(f'\n=== {split_name} (N={len(trades)}) — Baseline {nw}W/{nl}L PnL ${baseline:+.2f} ===')
    print(f'{"thr":>5} {"PASS":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%Wpres":>7}')
    for thr in [-0.20, 0.0, 0.05, 0.10, 0.20, 0.50]:
        pnl, wp, wv, lp_, lv = measure(trades, lambda t: F_vslp(t, thr))
        n_pass = sum(1 for t in trades if F_vslp(t, thr))
        wpres = 100*wp/max(nw,1)
        marker = ' ⭐' if thr == 0.0 else ''
        print(f'{thr:>5.2f} {n_pass:>5} {wp:>6} {wv:>6} {lp_:>6} {lv:>6} {pnl:>+10.2f} {pnl-baseline:>+10.2f} {wpres:>6.0f}%{marker}')

# Composite : ES+NQ par direction
print('\n' + '='*100)
print('=== COMBO PAR DIRECTION (ES+NQ) ===')
for direction in ['LONG', 'SHORT']:
    trades = [t for t in all_trades_with_vslp if t['side']==direction]
    if not trades: continue
    baseline = sum(t['pnl_usd'] for t in trades)
    nw = sum(1 for t in trades if t['pnl_usd']>0)
    nl = sum(1 for t in trades if t['pnl_usd']<0)
    print(f'\n{direction} ES+NQ combined (N={len(trades)}) — Baseline {nw}W/{nl}L PnL ${baseline:+.2f}')
    pnl, wp, wv, lp_, lv = measure(trades, lambda t: F_vslp(t, 0.0))
    print(f'  Seuil 0 : {wp}/{nw} wins preserves, {lv}/{nl} losses bloques, PnL=${pnl:+.2f} delta=${pnl-baseline:+.2f}')
