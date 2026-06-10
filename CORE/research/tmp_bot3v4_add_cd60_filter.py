"""Verifier impact d'ajouter F3 close_delta_60bars > 30t aux 9 trades Bot 3 v4.

Logique : LONG bloque si close - close_60bars_ago < -30t (falling knife)
          SHORT bloque si close - close_60bars_ago > +30t (rebond fort)

Combine F1 (15t buffer level) + F2 (aggro 0.30) + NEW F3 (CD60 30t).
"""
import json
from pathlib import Path
from datetime import datetime, timezone

TICK = 0.25
DAYS = ['20260524','20260525','20260526','20260527','20260528']
LEVEL_TO_COL = {
    'SWING_HIGH': '_last_swing_high_price', 'SWING_LOW': '_last_swing_low_price',
    'CUR_VAH': 'cur_vah', 'CUR_VAL': 'cur_val', 'CUR_VPOC': 'cur_vpoc',
    'PREV_VAH': 'prev_vah', 'PREV_VAL': 'prev_val', 'PREV_VPOC': 'prev_vpoc',
    'VWAP_D_SD2U': 'vwap_d_sd2u', 'VWAP_D_SD2D': 'vwap_d_sd2d',
    'VWAP_D_SD1U': 'vwap_d_sd1u', 'VWAP_D_SD1D': 'vwap_d_sd1d',
}

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# Reuse parsing from previous bot3v4 backtest script
log_base = Path('D:/tmp_bot3_v4_logs')
opens_by_date = {}
closes_by_date = {}
for d in DAYS:
    opens_by_date[d] = []
    closes_by_date[d] = []
    fp = log_base / f'bot3_v4_v1_{d}.jsonl'
    if not fp.exists(): continue
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                evt = e.get('event')
                if evt == 'TRADE_OPEN':
                    opens_by_date[d].append(e)
                elif evt == 'TRADE_CLOSE':
                    closes_by_date[d].append(e)
            except: pass

trades = []
for d in DAYS:
    opens = sorted(opens_by_date[d], key=lambda x: x['ts'])
    closes = sorted(closes_by_date[d], key=lambda x: x['ts'])
    used_closes = set()
    for op in opens:
        sid = op['signal_id']
        op_ts = parse_ts(op['ts'])
        match = None
        for i, cl in enumerate(closes):
            if i in used_closes: continue
            if cl.get('signal_id') != sid: continue
            if parse_ts(cl['ts']) <= op_ts: continue
            match = (i, cl)
            break
        if match:
            used_closes.add(match[0])
            cl = match[1]
            trades.append({
                'sid': sid, 'date': d, 'ts': op['ts'],
                'level': op.get('level'), 'side': op.get('side'),
                'entry': op.get('entry_price'),
                'outcome': cl.get('outcome'), 'pnl_usd': cl.get('pnl_usd', 0),
            })

closed = [t for t in trades if t['outcome'] in ('WIN','LOSS','BREAKEVEN')]
print(f'Closed trades : {len(closed)}')

# Load NQ bars
bars_by_day = {}
for d in DAYS:
    fp = Path(f'D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ/{d}_NQ.jsonl')
    bars = []
    if fp.exists():
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

PREV_DAY = {'20260525':'20260524','20260526':'20260525','20260527':'20260526','20260528':'20260527','20260524':None}

# Extract features for each trade
for t in closed:
    bars_today = bars_by_day.get(t['date'], [])
    bars_yest = bars_by_day.get(PREV_DAY.get(t['date']), []) or []
    all_bars = bars_yest + bars_today
    all_bars.sort(key=lambda x: x['_t'])
    target = parse_ts(t['ts'])
    prior = [b for b in all_bars if b['_t'] <= target]
    if not prior:
        t['close'] = None; t['level_price'] = None; t['aggro'] = None; t['cd60'] = None
        continue
    eb = prior[-1]
    t['close'] = eb.get('close')
    col = LEVEL_TO_COL.get(t['level'])
    t['level_price'] = eb.get(col) if col else None
    t['aggro'] = eb.get('aggressor_imbalance')
    if len(prior) >= 60:
        c60 = prior[-60].get('close')
        if t['close'] and c60:
            t['cd60'] = (t['close'] - c60) / TICK
        else:
            t['cd60'] = None
    else:
        t['cd60'] = None

# Filters
def F1_close_favorable(t, buf_ticks=15):
    cl = t.get('close'); lp = t.get('level_price'); side = t.get('side')
    if cl is None or lp is None: return True
    buf = buf_ticks * TICK
    if side == 'SHORT': return cl < lp - buf
    if side == 'LONG':  return cl > lp + buf
    return True

def F2_aggressor(t, thr=0.30):
    a = t.get('aggro')
    if a is None: return True
    if t['side'] == 'LONG' and a < -thr: return False
    if t['side'] == 'SHORT' and a > thr: return False
    return True

def F3_close_delta_60(t, thr=30):
    cd = t.get('cd60')
    if cd is None: return True
    if t['side'] == 'LONG' and cd < -thr: return False
    if t['side'] == 'SHORT' and cd > thr: return False
    return True

# Test combos
print('\n' + '='*150)
print(f'{"DATE":<11} {"SIDE":<6} {"LEVEL":<13} {"close":>10} {"lvl":>10} {"aggro":>7} {"cd60":>7} {"out":<5} {"PnL":>7} {"F1":<5} {"F2":<5} {"F3(30)":<7} {"F3(20)":<7} {"All3":<5}')
print('='*150)
for t in closed:
    cl = t.get('close'); lp = t.get('level_price')
    ag = t.get('aggro'); cd = t.get('cd60')
    cl_s = f'{cl:.2f}' if cl is not None else 'NA'
    lp_s = f'{lp:.2f}' if isinstance(lp, float) else 'NA'
    ag_s = f'{ag:+.2f}' if ag is not None else 'NA'
    cd_s = f'{cd:+.0f}' if cd is not None else 'NA'
    f1 = F1_close_favorable(t); f2 = F2_aggressor(t); f3_30 = F3_close_delta_60(t, 30); f3_20 = F3_close_delta_60(t, 20)
    all3 = f1 and f2 and f3_30
    print(f"{t['date']:<11} {t['side']:<6} {t['level'][:13]:<13} {cl_s:>10} {lp_s:>10} {ag_s:>7} {cd_s:>7} {t['outcome']:<5} {t['pnl_usd']:>+7.1f} {'P' if f1 else 'V':<5} {'P' if f2 else 'V':<5} {'P' if f3_30 else 'V':<7} {'P' if f3_20 else 'V':<7} {'P' if all3 else 'V':<5}")

# Stats
def measure(closed, fn):
    pnl_pass = sum(t['pnl_usd'] for t in closed if fn(t))
    w_pass = sum(1 for t in closed if t['outcome']=='WIN' and fn(t))
    w_veto = sum(1 for t in closed if t['outcome']=='WIN' and not fn(t))
    l_pass = sum(1 for t in closed if t['outcome']=='LOSS' and fn(t))
    l_veto = sum(1 for t in closed if t['outcome']=='LOSS' and not fn(t))
    return pnl_pass, w_pass, w_veto, l_pass, l_veto

baseline = sum(t['pnl_usd'] for t in closed)
print(f'\nBaseline : PnL ${baseline:+.2f}')

print('\n=== STRATEGIES ===')
print(f'{"strategy":<35} {"W":>3} {"L":>3} {"PnL":>10} {"delta":>10}')
strategies = [
    ('Current F1 only (already deployed)', lambda t: F1_close_favorable(t)),
    ('Current F1+F2 (already deployed)', lambda t: F1_close_favorable(t) and F2_aggressor(t)),
    ('+ ADD F3 CD60=30t', lambda t: F1_close_favorable(t) and F2_aggressor(t) and F3_close_delta_60(t, 30)),
    ('+ ADD F3 CD60=20t', lambda t: F1_close_favorable(t) and F2_aggressor(t) and F3_close_delta_60(t, 20)),
    ('+ ADD F3 CD60=15t', lambda t: F1_close_favorable(t) and F2_aggressor(t) and F3_close_delta_60(t, 15)),
    ('+ ADD F3 CD60=50t', lambda t: F1_close_favorable(t) and F2_aggressor(t) and F3_close_delta_60(t, 50)),
    ('F3 ALONE CD60=30t (no F1, no F2)', lambda t: F3_close_delta_60(t, 30)),
    ('F1+F3 CD60=30t (no F2)', lambda t: F1_close_favorable(t) and F3_close_delta_60(t, 30)),
    ('F2+F3 CD60=30t (no F1)', lambda t: F2_aggressor(t) and F3_close_delta_60(t, 30)),
]
for name, fn in strategies:
    pnl, wp, wv, lp_, lv = measure(closed, fn)
    print(f'{name:<35} {wp:>3} {lp_:>3} {pnl:>+10.2f} {pnl-baseline:>+10.2f}')
