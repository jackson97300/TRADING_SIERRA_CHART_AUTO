"""Test VSLP filter SPLIT PAR JOUR pour voir impact sur bons vs mauvais jours.

Question : filter degrade-t-il les jours profitables (28/05) ?
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

# Reuse collection
exec(open('D:/TRADING_SIERRA_CHART_AUTO/CORE/research/tmp_vslp_filter_backtest.py').read().split('# Filter logic')[0])

# Filter Bot 1 only (V3 + MP)
bot1_trades = [t for t in v3 + mp if t.get('vslp') is not None]
print(f'Bot 1 trades avec VSLP : {len(bot1_trades)}')
print(f'  V3 Continuation : {len(v3)}')
print(f'  MP : {len(mp)}')

def F_vslp(t, thr=0.0):
    vs = t.get('vslp')
    if vs is None: return True
    if t['side'] == 'LONG' and vs <= thr: return False
    if t['side'] == 'SHORT' and vs >= -thr: return False
    return True

# Group by ts date (UTC) - real session date if cross-day
def session_date(t):
    """Return logical session date (Asia trade at 22h UTC belongs to next day's session)."""
    h = int(t['ts'][11:13])
    d = t['ts'][:10]
    if h >= 22:  # Asia evening → next day session
        from datetime import datetime, timedelta
        next_d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime('%Y-%m-%d')
        return next_d
    return d

# Group by calendar date (simpler)
by_date = collections.defaultdict(list)
for t in bot1_trades:
    by_date[t['date']].append(t)

print(f'\n=== PAR JOUR (date calendrier) ===')
print(f'{"DATE":<10} {"N":>4} {"W":>3} {"L":>3} {"BASELINE":>10} {"FILTERED":>10} {"DELTA":>10} {"VETOED":>7}')
total_baseline = 0
total_filtered = 0
for d in sorted(by_date.keys()):
    trades = by_date[d]
    baseline = sum(t['pnl_usd'] for t in trades)
    filtered = sum(t['pnl_usd'] for t in trades if F_vslp(t))
    n_veto = sum(1 for t in trades if not F_vslp(t))
    nw = sum(1 for t in trades if t['pnl_usd']>0)
    nl = sum(1 for t in trades if t['pnl_usd']<0)
    delta = filtered - baseline
    total_baseline += baseline
    total_filtered += filtered
    marker = ' ⭐' if delta > 50 else (' ⚠️' if delta < -20 else '')
    print(f'{d:<10} {len(trades):>4} {nw:>3} {nl:>3} {baseline:>+10.2f} {filtered:>+10.2f} {delta:>+10.2f} {n_veto:>4}{marker}')

print(f'\nTOTAL : Baseline ${total_baseline:+.2f} | Filtered ${total_filtered:+.2f} | Delta ${total_filtered-total_baseline:+.2f}')

# Focus jour 28/05 (bonne journee)
print(f'\n=== ZOOM 28/05 (Bot 1 bonne journee) ===')
trades_28 = by_date.get('20260528', [])
print(f'{len(trades_28)} trades. Detail :')
for t in trades_28:
    keep = F_vslp(t)
    vslp = t.get('vslp')
    vslp_s = f'{vslp:+.3f}' if vslp is not None else 'NA'
    marker = '[VETO]' if not keep else '[KEEP]'
    print(f"  {t['ts'][11:19]} {t['src']:<2} {t['sym']:<2} {t['level']:<14} {t['side']:<5} VSLP={vslp_s:>7} PnL=${t['pnl_usd']:+.2f}  {marker}")

# Wins detruits par filter ?
wins_killed = [t for t in bot1_trades if t['pnl_usd']>0 and not F_vslp(t)]
losses_kept = [t for t in bot1_trades if t['pnl_usd']<0 and F_vslp(t)]
losses_blocked = [t for t in bot1_trades if t['pnl_usd']<0 and not F_vslp(t)]
print(f'\n=== Impact filter VSLP > 0 ===')
print(f'WINS tues par filter : {len(wins_killed)} (PnL perdu : ${sum(t["pnl_usd"] for t in wins_killed):+.2f})')
for t in wins_killed:
    print(f"  {t['date']} {t['ts'][11:19]} {t['sym']} {t['level']} {t['side']} VSLP={t['vslp']:+.3f} PnL=${t['pnl_usd']:+.2f}")
print(f'\nLOSSES bloques par filter : {len(losses_blocked)} (PnL sauve : ${-sum(t["pnl_usd"] for t in losses_blocked):+.2f})')
for t in losses_blocked:
    print(f"  {t['date']} {t['ts'][11:19]} {t['sym']} {t['level']} {t['side']} VSLP={t['vslp']:+.3f} PnL=${t['pnl_usd']:+.2f}")
