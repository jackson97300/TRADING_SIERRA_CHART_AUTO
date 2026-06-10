"""Backtest filter VSLP_10 (vwap_slope_10) bidirectionnel sur trades historiques :
  - Bot 1 Continuation (V3) : tous LONG, 24-29/05
  - Bot 3 MP (paper_v2) : LONG + SHORT, 25-29/05
  - Bot 3 v4 data-driven : LONG + SHORT, 24-28/05

Filter : LONG si VSLP > +seuil, SHORT si VSLP < -seuil.
Sweep seuil [0.0, 0.10, 0.20, 0.30, 0.50, 1.0, 2.0].
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import collections

TICK = {'NQ':0.25, 'ES':0.25}
TICK_USD = {'NQ':0.50, 'ES':1.25}

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# 1. Bot 1 Continuation (V3) — tous logs bot3_v3
V3_DAYS = ['20260525','20260526','20260527','20260528','20260529']
v3 = []
for d in V3_DAYS:
    fp = Path(f'D:/tmp_bot3_v4_logs/bot3_v3_v1_{d}.jsonl')
    if not fp.exists(): continue
    opens = {}
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('event') == 'TRADE_OPEN':
                    opens[e.get('signal_id')] = e
                elif e.get('event') == 'TRADE_CLOSE':
                    op = opens.get(e.get('signal_id'))
                    if op:
                        v3.append({
                            'src':'V3','date':d,'ts':op.get('ts'),'sym':op.get('symbol'),
                            'level':op.get('level'),'side':op.get('side'),
                            'entry':op.get('entry_price'),
                            'pnl_usd':e.get('pnl_usd',0) or 0,
                        })
            except: pass

# 2. Bot 3 MP (paper_v2 BOT3_TRADE_OPEN)
MP_DAYS = ['20260525','20260526','20260527','20260528','20260529']
mp = []
for d in MP_DAYS:
    fp = Path(f'D:/tmp_bot1_trading_logs/trading_{d}_paper_v2.jsonl')
    if not fp.exists(): continue
    opens = collections.defaultdict(list)
    closes = collections.defaultdict(list)
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('code') == 'BOT3_TRADE_OPEN':
                    ctx = e.get('ctx',{})
                    opens[(ctx.get('sym'),ctx.get('level'))].append(e)
                elif e.get('code') == 'BOT3_TRADE_CLOSE':
                    ctx = e.get('ctx',{})
                    closes[(ctx.get('sym'),ctx.get('level'))].append(e)
            except: pass
    for k in opens:
        sym, lvl = k
        used = set()
        for op in sorted(opens[k], key=lambda x: x['ts']):
            for ci, cl in enumerate(sorted(closes.get(k,[]), key=lambda x: x['ts'])):
                if ci in used or cl['ts'] <= op['ts']: continue
                used.add(ci)
                ctx_o, ctx_c = op.get('ctx',{}), cl.get('ctx',{})
                qty = ctx_o.get('qty',1)
                pnl = (ctx_c.get('pnl',0) or 0) * TICK_USD.get(sym,1) * qty
                mp.append({
                    'src':'MP','date':d,'ts':op['ts'],'sym':sym,'level':lvl,
                    'side':ctx_o.get('side'),'entry':ctx_o.get('price'),
                    'pnl_usd':pnl,
                })
                break

# 3. Bot 3 v4 — trades closed
BV4_DAYS = ['20260524','20260525','20260526','20260527','20260528']
bv4 = []
for d in BV4_DAYS:
    fp = Path(f'D:/tmp_bot3_v4_logs/bot3_v4_v1_{d}.jsonl')
    if not fp.exists(): continue
    opens = {}
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('event') == 'TRADE_OPEN':
                    opens[e.get('signal_id')] = e
                elif e.get('event') == 'TRADE_CLOSE':
                    op = opens.get(e.get('signal_id'))
                    if op:
                        pnl = e.get('pnl_usd', 0) or 0
                        bv4.append({
                            'src':'V4','date':d,'ts':op.get('ts'),'sym':op.get('symbol'),
                            'level':op.get('level'),'side':op.get('side'),
                            'entry':op.get('entry_price'),
                            'pnl_usd':pnl,
                        })
            except: pass

all_trades = v3 + mp + bv4
print(f'Total trades historique : V3={len(v3)} MP={len(mp)} V4={len(bv4)} → {len(all_trades)}')
print(f'  LONG : {sum(1 for t in all_trades if t["side"]=="LONG")}')
print(f'  SHORT : {sum(1 for t in all_trades if t["side"]=="SHORT")}')

# Charger live_enriched
bars = {}
for sym in ('NQ','ES'):
    for d in V3_DAYS + ['20260524']:
        fp = Path(f'D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/{sym}/{d}_{sym}.jsonl')
        b = []
        if fp.exists():
            with open(fp, encoding='utf-8') as f:
                for line in f:
                    try:
                        bb = json.loads(line)
                        t = bb.get('ts_event')
                        if t:
                            bb['_t'] = parse_ts(t)
                            b.append(bb)
                    except: pass
        bars[(sym, d)] = sorted(b, key=lambda x: x['_t'])

# Extract VSLP for each trade
n_extracted = 0
for t in all_trades:
    sym = t['sym']
    # Build context from prev_day + day
    PREV = {'20260524':None,'20260525':'20260524','20260526':'20260525','20260527':'20260526','20260528':'20260527','20260529':'20260528'}
    prev_d = PREV.get(t['date'])
    all_bars = (bars.get((sym, prev_d), []) if prev_d else []) + bars.get((sym, t['date']), [])
    all_bars.sort(key=lambda x: x['_t'])
    target = parse_ts(t['ts'])
    prior = [b for b in all_bars if b['_t'] <= target]
    if not prior:
        t['vslp'] = None; continue
    eb = prior[-1]
    t['vslp'] = eb.get('vwap_slope_10')
    if t['vslp'] is not None: n_extracted += 1
print(f'Trades avec VSLP extracted : {n_extracted}/{len(all_trades)}')

# Filter logic
def F_vslp(t, thr):
    """LONG si vslp > +thr, SHORT si vslp < -thr."""
    vs = t.get('vslp')
    if vs is None: return True  # pas de data : let pass (defensive)
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

# Sweep ALL trades
print('\n=== ALL TRADES (V3+MP+V4) — Sweep VSLP threshold ===')
baseline = sum(t['pnl_usd'] for t in all_trades)
nw = sum(1 for t in all_trades if t['pnl_usd']>0)
nl = sum(1 for t in all_trades if t['pnl_usd']<0)
print(f'Baseline : {nw}W/{nl}L PnL ${baseline:+.2f}\n')
print(f'{"thr":>5} {"PASS":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%Wpres":>7}')
for thr in [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0, 2.0]:
    pnl, wp, wv, lp_, lv = measure(all_trades, lambda t: F_vslp(t, thr))
    n_pass = sum(1 for t in all_trades if F_vslp(t, thr))
    wpres = 100*wp/max(nw,1)
    print(f'{thr:>5.2f} {n_pass:>5} {wp:>6} {wv:>6} {lp_:>6} {lv:>6} {pnl:>+10.2f} {pnl-baseline:>+10.2f} {wpres:>6.0f}%')

# Sweep LONG only (Bot 1 V3 + MP)
long_trades = [t for t in v3+mp if t['side']=='LONG']
print(f'\n=== LONG-only trades (V3+MP), N={len(long_trades)} — Sweep VSLP threshold ===')
baseline_L = sum(t['pnl_usd'] for t in long_trades)
nw_L = sum(1 for t in long_trades if t['pnl_usd']>0)
nl_L = sum(1 for t in long_trades if t['pnl_usd']<0)
print(f'Baseline : {nw_L}W/{nl_L}L PnL ${baseline_L:+.2f}\n')
print(f'{"thr":>5} {"PASS":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%Wpres":>7}')
for thr in [-0.50, -0.20, 0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0, 2.0]:
    pnl, wp, wv, lp_, lv = measure(long_trades, lambda t: F_vslp(t, thr))
    n_pass = sum(1 for t in long_trades if F_vslp(t, thr))
    wpres = 100*wp/max(nw_L,1)
    print(f'{thr:>5.2f} {n_pass:>5} {wp:>6} {wv:>6} {lp_:>6} {lv:>6} {pnl:>+10.2f} {pnl-baseline_L:>+10.2f} {wpres:>6.0f}%')

# Sweep SHORT only (Bot 3 v4 mostly)
short_trades = [t for t in all_trades if t['side']=='SHORT']
print(f'\n=== SHORT-only trades, N={len(short_trades)} — Sweep VSLP threshold ===')
if short_trades:
    baseline_S = sum(t['pnl_usd'] for t in short_trades)
    nw_S = sum(1 for t in short_trades if t['pnl_usd']>0)
    nl_S = sum(1 for t in short_trades if t['pnl_usd']<0)
    print(f'Baseline : {nw_S}W/{nl_S}L PnL ${baseline_S:+.2f}\n')
    print(f'{"thr":>5} {"PASS":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10} {"%Wpres":>7}')
    for thr in [-0.50, -0.20, 0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0, 2.0]:
        pnl, wp, wv, lp_, lv = measure(short_trades, lambda t: F_vslp(t, thr))
        n_pass = sum(1 for t in short_trades if F_vslp(t, thr))
        wpres = 100*wp/max(nw_S,1)
        print(f'{thr:>5.2f} {n_pass:>5} {wp:>6} {wv:>6} {lp_:>6} {lv:>6} {pnl:>+10.2f} {pnl-baseline_S:>+10.2f} {wpres:>6.0f}%')
