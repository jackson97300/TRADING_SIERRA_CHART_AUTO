"""Backtest sweep param buffer_ticks pour fix Bot 3 v4 TOUCH != TRADE.

Logique fix : exiger close de la bar TOUCH du cote FAVORABLE au niveau :
  - SHORT : close < level_price - buffer*tick (respect du niveau, pas breakout)
  - LONG  : close > level_price + buffer*tick

Sweep buffer = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15] ticks (NQ tick = 0.25).

Trades historiques Bot 3 v4 24-28/05 dans LOGS/bot3_v4/.
Live enriched dans DATA/live_enriched/NQ/.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

TICK = 0.25
DAYS = ['20260524','20260525','20260526','20260527','20260528']

# Map level name -> live_enriched column
LEVEL_TO_COL = {
    'SWING_HIGH': '_last_swing_high_price',
    'SWING_LOW': '_last_swing_low_price',
    'CUR_VAH': 'cur_vah',
    'CUR_VAL': 'cur_val',
    'CUR_VPOC': 'cur_vpoc',
    'PREV_VAH': 'prev_vah',
    'PREV_VAL': 'prev_val',
    'PREV_VPOC': 'prev_vpoc',
    'VWAP_D_SD2U': 'vwap_d_sd2u',
    'VWAP_D_SD2D': 'vwap_d_sd2d',
    'VWAP_D_SD1U': 'vwap_d_sd1u',
    'VWAP_D_SD1D': 'vwap_d_sd1d',
}

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# Charger trades + outcomes
trade_logs_base = Path('D:/tmp_bot3_v4_logs')
trades = []  # list of dict with sid, ts, level, side, entry, sl, tp, outcome, pnl_usd

# Parse logs Bot 3 v4 : grouper par sid (TRADE_OPEN + TRADE_CLOSE matching)
opens = {}  # sid_short -> open event
closes = {}  # sid_short -> close event
for d in DAYS:
    fp = trade_logs_base / f'bot3_v4_v1_{d}.jsonl'
    if not fp.exists(): continue
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                evt = e.get('event')
                sid = e.get('signal_id')
                if not sid: continue
                # Unique key = sid + ts_date (signal_id reused after restart)
                key = f"{sid}__{d}"
                if evt == 'TRADE_OPEN':
                    opens[key] = e
                elif evt == 'TRADE_CLOSE':
                    closes[key] = e
            except: pass

# Build matched trades
for key, op in opens.items():
    cl = closes.get(key)
    pnl = cl.get('pnl_usd', 0.0) if cl else None
    outcome = cl.get('outcome', 'PENDING') if cl else 'PENDING'
    trades.append({
        'sid': op.get('signal_id'),
        'date': op.get('ts', '')[:10].replace('-',''),
        'ts': op.get('ts'),
        'level': op.get('level'),
        'side': op.get('side'),
        'entry': op.get('entry_price'),
        'sl': op.get('sl_price'),
        'tp': op.get('tp_price'),
        'outcome': outcome,
        'pnl_usd': pnl,
        'exit_cause': cl.get('exit_cause') if cl else None,
        'duration_bars': cl.get('duration_bars') if cl else None,
    })

print(f'Trades total : {len(trades)}')
trades_closed = [t for t in trades if t['outcome'] != 'PENDING']
print(f'Trades closed (outcome known) : {len(trades_closed)}')
print(f'Wins : {sum(1 for t in trades_closed if t["outcome"]=="WIN")}')
print(f'Losses : {sum(1 for t in trades_closed if t["outcome"]=="LOSS")}')
print(f'Breakeven : {sum(1 for t in trades_closed if t["outcome"]=="BREAKEVEN")}')
print(f'Total PnL : ${sum(t["pnl_usd"] or 0 for t in trades_closed):+.2f}')

# Charger live_enriched par jour, indexer par minute
bars_by_day = {}
for d in DAYS:
    fp = Path(f'D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ/{d}_NQ.jsonl')
    if not fp.exists():
        bars_by_day[d] = []
        continue
    bars = []
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                b = json.loads(line)
                t = b.get('ts_event')
                if t:
                    b['_t'] = parse_ts(t)
                    bars.append(b)
            except: pass
    bars_by_day[d] = sorted(bars, key=lambda x: x['_t'])

# Pour chaque trade : trouver bar entry (close <= trade_ts) + extraire level_price + close
for t in trades:
    bars = bars_by_day.get(t['date'], [])
    target = parse_ts(t['ts'])
    prior = [b for b in bars if b['_t'] <= target]
    if not prior:
        t['bar_close'] = None
        t['level_price'] = None
        continue
    entry_bar = prior[-1]
    t['bar_close'] = entry_bar.get('close')
    col = LEVEL_TO_COL.get(t['level'])
    if col:
        t['level_price'] = entry_bar.get(col)
    else:
        t['level_price'] = None

# Filter logic
def filter_pass(t, buffer_ticks: int) -> bool:
    """True = trade pass (keep), False = veto."""
    close = t.get('bar_close')
    lvl = t.get('level_price')
    side = t.get('side')
    if close is None or lvl is None:
        return True  # contexte insuffisant -> defaults safe = pass
    buf = buffer_ticks * TICK
    if side == 'SHORT':
        # SHORT respect = close < lvl - buf
        return close < lvl - buf
    if side == 'LONG':
        return close > lvl + buf
    return True

# Sweep
BUFFERS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15]
print('\n' + '='*120)
print(f'{"BUFFER":>7} {"PASS":>6} {"VETO":>6} {"VETO%":>6} {"WIN_PASS":>9} {"WIN_VETO":>9} {"LOSS_PASS":>10} {"LOSS_VETO":>10} {"PnL_baseline":>14} {"PnL_filtered":>14} {"PnL_DELTA":>12}')
print('='*120)
baseline_pnl = sum(t['pnl_usd'] or 0 for t in trades_closed)
for buf in BUFFERS:
    n_pass = sum(1 for t in trades if filter_pass(t, buf))
    n_veto = len(trades) - n_pass
    win_pass = sum(1 for t in trades_closed if t['outcome']=='WIN' and filter_pass(t, buf))
    win_veto = sum(1 for t in trades_closed if t['outcome']=='WIN' and not filter_pass(t, buf))
    loss_pass = sum(1 for t in trades_closed if t['outcome']=='LOSS' and filter_pass(t, buf))
    loss_veto = sum(1 for t in trades_closed if t['outcome']=='LOSS' and not filter_pass(t, buf))
    pnl_filtered = sum(t['pnl_usd'] or 0 for t in trades_closed if filter_pass(t, buf))
    pnl_delta = pnl_filtered - baseline_pnl
    veto_pct = 100*n_veto/len(trades)
    print(f'{buf:>7} {n_pass:>6} {n_veto:>6} {veto_pct:>5.0f}% {win_pass:>9} {win_veto:>9} {loss_pass:>10} {loss_veto:>10} {baseline_pnl:>+14.2f} {pnl_filtered:>+14.2f} {pnl_delta:>+12.2f}')

# Distribution levels
print('\n=== Distribution levels ===')
level_dist = defaultdict(lambda: {'n':0, 'wins':0, 'losses':0, 'pnl':0.0})
for t in trades_closed:
    lvl = t['level']
    level_dist[lvl]['n'] += 1
    if t['outcome']=='WIN': level_dist[lvl]['wins'] += 1
    elif t['outcome']=='LOSS': level_dist[lvl]['losses'] += 1
    level_dist[lvl]['pnl'] += t['pnl_usd'] or 0
for lvl, st in sorted(level_dist.items(), key=lambda x: x[1]['pnl']):
    print(f"  {lvl:<15} n={st['n']:<3} W={st['wins']:<3} L={st['losses']:<3} PnL={st['pnl']:+.2f}")

# Coverage : combien de trades ont level_price valide
missing_level = sum(1 for t in trades if t['level_price'] is None)
print(f'\n=== Coverage ===')
print(f'Trades sans level_price (skip filter) : {missing_level}/{len(trades)}')

# Detail buffer=2 (recommandation agent)
print('\n=== DETAIL buffer=2 (recommandation agent) ===')
print(f'{"sid":<25} {"date":<10} {"side":<6} {"level":<13} {"close":>10} {"lvl_px":>10} {"diff_t":>8} {"outcome":<8} {"PnL":>8} {"filter":<6}')
for t in trades_closed:
    cl = t.get('bar_close')
    lp = t.get('level_price')
    if cl is not None and lp is not None:
        diff = (cl - lp) / TICK
    else:
        diff = None
    diff_s = f'{diff:+.0f}' if diff is not None else 'NA'
    keep = filter_pass(t, 2)
    print(f"  {t['sid'][-15:]:<25} {t['date']:<10} {t['side']:<6} {t['level']:<13} {cl if cl is not None else '?':>10} {lp if lp is not None else '?':>10} {diff_s:>8} {t['outcome']:<8} {t['pnl_usd'] or 0:>+8.1f} {'PASS' if keep else 'VETO':<6}")
