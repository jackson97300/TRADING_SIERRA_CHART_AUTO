"""Backtest SWEEP 3 filtres pour Bot 3 v4 (Jackson 29/05) :
  F1 = TOUCH != TRADE : close bar TOUCH cote favorable au niveau (buffer ticks)
  F2 = AGGRESSOR opposite : veto si aggressor_imbalance fortement oppose direction
  F3 = POSITION_IN_RANGE opposite : veto si LONG en haut range / SHORT en bas range

Find best combo en preservant WINS (cible : 100% WINS preserves, max LOSSES blocked).
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import itertools

TICK = 0.25
DAYS = ['20260524','20260525','20260526','20260527','20260528']

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

# Parse logs + match TRADE_OPEN avec TRADE_CLOSE par ts proximity
trade_logs_base = Path('D:/tmp_bot3_v4_logs')
opens_by_date = defaultdict(list)
closes_by_date = defaultdict(list)
for d in DAYS:
    fp = trade_logs_base / f'bot3_v4_v1_{d}.jsonl'
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

# Match open->close par sid + chronologie (closest close AFTER open with same sid)
trades = []
for d in DAYS:
    opens = sorted(opens_by_date[d], key=lambda x: x['ts'])
    closes = sorted(closes_by_date[d], key=lambda x: x['ts'])
    used_closes = set()
    for op in opens:
        sid = op['signal_id']
        op_ts = parse_ts(op['ts'])
        # Trouver le 1er close avec meme sid apres op_ts (et pas deja utilise)
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
                'outcome': cl.get('outcome', 'UNKNOWN'),
                'pnl_usd': cl.get('pnl_usd', 0.0),
                'exit_cause': cl.get('exit_cause'),
                'duration_bars': cl.get('duration_bars'),
            })
        else:
            trades.append({
                'sid': sid, 'date': d, 'ts': op['ts'],
                'level': op.get('level'), 'side': op.get('side'),
                'entry': op.get('entry_price'),
                'outcome': 'UNMATCHED', 'pnl_usd': 0.0,
                'exit_cause': None, 'duration_bars': None,
            })

print(f'Trades total : {len(trades)}')
closed = [t for t in trades if t['outcome'] in ('WIN','LOSS','BREAKEVEN')]
print(f'Closed matched : {len(closed)}')
n_w = sum(1 for t in closed if t['outcome']=='WIN')
n_l = sum(1 for t in closed if t['outcome']=='LOSS')
print(f'W={n_w} L={n_l} (PnL baseline : ${sum(t["pnl_usd"] for t in closed):+.2f})')

# Charger live_enriched bars
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

# Pour chaque trade : extraire features bar entry
for t in trades:
    bars = bars_by_day.get(t['date'], [])
    target = parse_ts(t['ts'])
    prior = [b for b in bars if b['_t'] <= target]
    if not prior:
        t['bar_close'] = None; t['level_price'] = None
        t['aggressor_imbalance'] = None; t['position_in_range'] = None
        t['delta_bar'] = None
        continue
    eb = prior[-1]
    t['bar_close'] = eb.get('close')
    col = LEVEL_TO_COL.get(t['level'])
    t['level_price'] = eb.get(col) if col else None
    t['aggressor_imbalance'] = eb.get('aggressor_imbalance')
    t['position_in_range'] = eb.get('position_in_range')
    t['delta_bar'] = eb.get('delta_bar')

# 3 filters
def F1_touch(t, buf_ticks):
    """TOUCH filter : close cote favorable au niveau."""
    cl = t.get('bar_close'); lp = t.get('level_price'); side = t.get('side')
    if cl is None or lp is None: return True
    buf = buf_ticks * TICK
    if side == 'SHORT': return cl < lp - buf
    if side == 'LONG':  return cl > lp + buf
    return True

def F2_aggressor(t, thr):
    """Aggressor opposite direction veto. thr=None=disabled."""
    if thr is None: return True
    ai = t.get('aggressor_imbalance')
    if ai is None: return True
    if t['side'] == 'LONG' and ai < -thr: return False  # vendeurs agressifs vs LONG
    if t['side'] == 'SHORT' and ai > thr: return False  # acheteurs agressifs vs SHORT
    return True

def F3_pir(t, thr):
    """Position_in_range veto opposite direction. thr=None=disabled."""
    if thr is None: return True
    pir = t.get('position_in_range')
    if pir is None: return True
    if t['side'] == 'LONG' and pir > thr: return False  # LONG en haut range
    if t['side'] == 'SHORT' and pir < (1.0 - thr): return False  # SHORT en bas range
    return True

# Sweep individual
def measure(closed_trades, filter_fn):
    pnl_pass = sum(t['pnl_usd'] for t in closed_trades if filter_fn(t))
    w_pass = sum(1 for t in closed_trades if t['outcome']=='WIN' and filter_fn(t))
    w_veto = sum(1 for t in closed_trades if t['outcome']=='WIN' and not filter_fn(t))
    l_pass = sum(1 for t in closed_trades if t['outcome']=='LOSS' and filter_fn(t))
    l_veto = sum(1 for t in closed_trades if t['outcome']=='LOSS' and not filter_fn(t))
    return {'pnl': pnl_pass, 'w_pass': w_pass, 'w_veto': w_veto,
            'l_pass': l_pass, 'l_veto': l_veto,
            'preserve_wins': w_pass / max(n_w, 1)}

baseline_pnl = sum(t['pnl_usd'] for t in closed)

print('\n' + '='*100)
print('=== F1 (TOUCH != TRADE buffer) SWEEP ===')
print(f'{"buf":>4} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%W_preserved":>14}')
for buf in [0,1,2,3,4,5,6,8,10,15,20]:
    m = measure(closed, lambda t: F1_touch(t, buf))
    print(f'{buf:>4} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f} {100*m["preserve_wins"]:>13.0f}%')

print('\n=== F2 (aggressor_imbalance opposite) SWEEP ===')
print(f'{"thr":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%W_preserved":>14}')
for thr in [None, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
    m = measure(closed, lambda t: F2_aggressor(t, thr))
    label = f'{thr:.2f}' if thr is not None else 'OFF'
    print(f'{label:>5} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f} {100*m["preserve_wins"]:>13.0f}%')

print('\n=== F3 (position_in_range opposite) SWEEP ===')
print(f'{"thr":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%W_preserved":>14}')
for thr in [None, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    m = measure(closed, lambda t: F3_pir(t, thr))
    label = f'{thr:.2f}' if thr is not None else 'OFF'
    print(f'{label:>5} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f} {100*m["preserve_wins"]:>13.0f}%')

# Combos : F1 + F2, F1 + F3, F2 + F3, F1 + F2 + F3
print('\n=== COMBOS BEST (preserve 100% wins) ===')
print(f'{"combo":<40} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')

best_results = []
F1_GRID = [0, 2, 3, 5, 8, 15]
F2_GRID = [None, 0.3, 0.5, 0.6]
F3_GRID = [None, 0.65, 0.70, 0.80]

for f1, f2, f3 in itertools.product(F1_GRID, F2_GRID, F3_GRID):
    def combo(t, f1=f1, f2=f2, f3=f3):
        return F1_touch(t, f1) and F2_aggressor(t, f2) and F3_pir(t, f3)
    m = measure(closed, combo)
    if m['preserve_wins'] >= 1.0:  # 100% wins
        best_results.append({
            'f1': f1, 'f2': f2, 'f3': f3, **m,
            'delta': m['pnl'] - baseline_pnl,
        })

# Sort by delta desc
best_results.sort(key=lambda x: -x['delta'])
for r in best_results[:15]:
    f2_s = 'OFF' if r['f2'] is None else f"{r['f2']:.2f}"
    f3_s = 'OFF' if r['f3'] is None else f"{r['f3']:.2f}"
    lbl = f"F1={r['f1']}t F2={f2_s} F3={f3_s}"
    print(f'{lbl:<40} {r["w_pass"]:>6} {r["w_veto"]:>6} {r["l_pass"]:>6} {r["l_veto"]:>6} {r["pnl"]:>+10.2f} {r["delta"]:>+10.2f}')

# Detail trades with best combo
if best_results:
    best = best_results[0]
    print(f'\n=== DETAIL BEST COMBO F1={best["f1"]}t F2={best["f2"]} F3={best["f3"]} ===')
    def best_combo(t):
        return F1_touch(t, best['f1']) and F2_aggressor(t, best['f2']) and F3_pir(t, best['f3'])
    for t in closed:
        cl = t.get('bar_close'); lp = t.get('level_price')
        ai = t.get('aggressor_imbalance'); pir = t.get('position_in_range')
        diff = (cl - lp)/TICK if (cl is not None and lp is not None) else None
        diff_s = f'{diff:+.0f}t' if diff is not None else 'NA'
        ai_s = f'{ai:+.2f}' if ai is not None else 'NA'
        pir_s = f'{pir:.2f}' if pir is not None else 'NA'
        lp_s = f'{lp:.2f}' if isinstance(lp, float) else str(lp)
        keep = best_combo(t)
        print(f"  {t['date']} {t['side']:<6} {t['level']:<12} close={cl} lvl={lp_s} diff={diff_s} aggro={ai_s} pir={pir_s} {t['outcome']:<5} PnL={t['pnl_usd']:+.1f} -> {'PASS' if keep else 'VETO'}")
