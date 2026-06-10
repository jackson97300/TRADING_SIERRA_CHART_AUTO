"""RESERVE 6 (code-reviewer 29/05) : re-stat backtest VSLP Bot 1 sans le -$296 outlier.

Question : le delta +$622 est-il porte par un seul trade (data mining trap) ?
Outlier identifie : 20260528 ES MQ_CALL_POC_FLAT SHORT VSLP=+0.059 PnL=-$296.

Stats avec et sans cet outlier au threshold = 0 (filtre deploye).
"""
import json
from pathlib import Path
from datetime import datetime, timezone

TICK_USD = {'NQ': 0.50, 'ES': 1.25}


def parse_ts(s):
    if 'Z' in s:
        s = s.replace('Z', '+00:00')
    if '+' not in s and 'T' in s:
        s += '+00:00'
    return datetime.fromisoformat(s)


# Reuse collection (split first part of original script)
exec(open('D:/TRADING_SIERRA_CHART_AUTO/CORE/research/tmp_vslp_filter_backtest.py').read().split('# Filter logic')[0])

# Bot 1 = V3 + MP (le filtre deploye s'applique aux deux via _bot3_execute_trade)
bot1_trades = [t for t in v3 + mp if t.get('vslp') is not None]


def F0(t):
    """Filter threshold = 0 (filtre actif en prod)."""
    vs = t.get('vslp')
    if vs is None:
        return True
    if t['side'] == 'LONG' and vs <= 0:
        return False
    if t['side'] == 'SHORT' and vs >= 0:
        return False
    return True


def stats(trades, label):
    baseline = sum(t['pnl_usd'] for t in trades)
    filtered = sum(t['pnl_usd'] for t in trades if F0(t))
    delta = filtered - baseline
    nw_b = sum(1 for t in trades if t['pnl_usd'] > 0)
    nl_b = sum(1 for t in trades if t['pnl_usd'] < 0)
    nw_f = sum(1 for t in trades if t['pnl_usd'] > 0 and F0(t))
    nl_f = sum(1 for t in trades if t['pnl_usd'] < 0 and F0(t))
    n_veto = sum(1 for t in trades if not F0(t))
    losses_blocked = [t for t in trades if t['pnl_usd'] < 0 and not F0(t)]
    pnl_saved = -sum(t['pnl_usd'] for t in losses_blocked)
    wins_killed = [t for t in trades if t['pnl_usd'] > 0 and not F0(t)]
    pnl_lost = sum(t['pnl_usd'] for t in wins_killed)
    wr_b = 100 * nw_b / max(nw_b + nl_b, 1)
    wr_f = 100 * nw_f / max(nw_f + nl_f, 1)
    print(f'\n=== {label} (N={len(trades)}) ===')
    print(f'  Baseline   : {nw_b}W / {nl_b}L  WR={wr_b:.1f}%  PnL=${baseline:+.2f}')
    print(f'  Filtered   : {nw_f}W / {nl_f}L  WR={wr_f:.1f}%  PnL=${filtered:+.2f}')
    print(f'  Vetos      : {n_veto}  (Losses bloques={len(losses_blocked)}  Wins tues={len(wins_killed)})')
    print(f'  PnL sauve  : ${pnl_saved:+.2f}  PnL perdu : ${pnl_lost:+.2f}  DELTA NET : ${delta:+.2f}')
    return delta, len(losses_blocked)


# 1. Stats COMPLETS
delta_full, n_blocked_full = stats(bot1_trades, 'AVEC outlier -$296 (full backtest)')

# 2. Stats SANS le -$296
outlier_match = lambda t: (t['date'] == '20260528' and t['sym'] == 'ES'
                           and t['level'] == 'MQ_CALL_POC_FLAT' and t['side'] == 'SHORT'
                           and abs(t['pnl_usd'] - (-296)) < 5)
trades_no_outlier = [t for t in bot1_trades if not outlier_match(t)]
outlier_trades = [t for t in bot1_trades if outlier_match(t)]
print(f'\nOutlier(s) identifie(s) : {len(outlier_trades)}')
for o in outlier_trades:
    print(f"  {o['date']} {o['ts'][11:19]} {o['sym']} {o['level']} {o['side']} VSLP={o['vslp']:+.3f} PnL=${o['pnl_usd']:+.2f}")

delta_no_outlier, n_blocked_no_outlier = stats(trades_no_outlier, 'SANS outlier -$296')

# 3. Comparaison
print(f'\n=== COMPARAISON (RESERVE 6 code-reviewer) ===')
print(f'  Delta avec outlier : ${delta_full:+.2f} ({n_blocked_full} losses bloques)')
print(f'  Delta sans outlier : ${delta_no_outlier:+.2f} ({n_blocked_no_outlier} losses bloques)')
print(f'  Part de l\'outlier  : ${delta_full - delta_no_outlier:+.2f} ({100*(delta_full-delta_no_outlier)/max(abs(delta_full),1):.0f}%)')
print(f'\n  → Verdict : ', end='')
if delta_no_outlier > 100:
    print('ROBUSTE (delta positif > $100 meme sans outlier)')
elif delta_no_outlier > 0:
    print('MARGINAL (delta positif mais faible sans outlier)')
else:
    print('FRAGILE (delta porte par outlier — pattern 11 V1 / data mining)')

# 4. Detail SHORTs bloques (pour comprendre la part SHORT vs LONG)
print(f'\n=== DETAIL LOSSES BLOQUES PAR FILTRE (sans outlier) ===')
shorts_blocked = [t for t in trades_no_outlier if t['pnl_usd'] < 0 and not F0(t) and t['side'] == 'SHORT']
longs_blocked = [t for t in trades_no_outlier if t['pnl_usd'] < 0 and not F0(t) and t['side'] == 'LONG']
print(f'  LONG bloques : {len(longs_blocked)}  PnL sauve : ${-sum(t["pnl_usd"] for t in longs_blocked):+.2f}')
for t in longs_blocked:
    print(f"    {t['date']} {t['ts'][11:19]} {t['sym']} {t['level']:<14} VSLP={t['vslp']:+.4f} PnL=${t['pnl_usd']:+.2f}")
print(f'  SHORT bloques : {len(shorts_blocked)}  PnL sauve : ${-sum(t["pnl_usd"] for t in shorts_blocked):+.2f}')
for t in shorts_blocked:
    print(f"    {t['date']} {t['ts'][11:19]} {t['sym']} {t['level']:<14} VSLP={t['vslp']:+.4f} PnL=${t['pnl_usd']:+.2f}")
