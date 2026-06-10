"""Audit COMPLET Bot 1 (Continuation + MP) nuit 28-29/05.

Compile 14 trades (9 Bot 1 Continuation bot3_v3 + 5 Bot 3 MP paper_v2) avec
contexte features. Identifier patterns wins vs losses.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import collections

TICK = {'NQ': 0.25, 'ES': 0.25}
TICK_USD = {'NQ': 0.50, 'ES': 1.25}

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z','+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# 1. Bot 1 Continuation (bot3_v3)
v3_trades = []
for d in ['20260528','20260529']:
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
                        v3_trades.append({
                            'bot': 'V3', 'date': d, 'ts': op.get('ts'),
                            'sym': op.get('symbol'), 'level': op.get('level'),
                            'side': 'LONG' if op.get('side')=='LONG' else 'SHORT',
                            'entry': op.get('entry_price'),
                            'pnl_usd': e.get('pnl_usd', 0) or 0,
                            'exit_cause': e.get('exit_cause'),
                        })
            except: pass

# 2. Bot 3 MP (paper_v2 trading log BOT3_TRADE_OPEN)
mp_trades = []
for d in ['20260528','20260529']:
    fp = Path(f'D:/tmp_bot1_trading_logs/trading_{d}_paper_v2.jsonl')
    if not fp.exists(): continue
    opens = collections.defaultdict(list)
    closes = collections.defaultdict(list)
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('code') == 'BOT3_TRADE_OPEN':
                    ctx = e.get('ctx', {})
                    k = (ctx.get('sym'), ctx.get('level'))
                    opens[k].append({'e': e, 'ts': e.get('ts')})
                elif e.get('code') == 'BOT3_TRADE_CLOSE':
                    ctx = e.get('ctx', {})
                    k = (ctx.get('sym'), ctx.get('level'))
                    closes[k].append({'e': e, 'ts': e.get('ts')})
            except: pass
    # Match
    for k in opens:
        sym, level = k
        ops = sorted(opens[k], key=lambda x: x['ts'])
        cls = sorted(closes.get(k, []), key=lambda x: x['ts'])
        used = set()
        for op in ops:
            for ci, cl in enumerate(cls):
                if ci in used: continue
                if cl['ts'] <= op['ts']: continue
                used.add(ci)
                ctx_op = op['e'].get('ctx', {})
                ctx_cl = cl['e'].get('ctx', {})
                qty = ctx_op.get('qty', 1)
                pnl_ticks = ctx_cl.get('pnl', 0) or 0
                pnl_usd = pnl_ticks * TICK_USD.get(sym, 1) * qty
                mp_trades.append({
                    'bot': 'MP', 'date': d, 'ts': op['ts'],
                    'sym': sym, 'level': level,
                    'side': 'LONG' if ctx_op.get('side')=='LONG' else 'SHORT',
                    'entry': ctx_op.get('price'),
                    'pnl_usd': pnl_usd,
                    'exit_cause': ctx_cl.get('reason'),
                    'qty': qty,
                })
                break

# Filter night session
def is_night(t):
    return ((t['date']=='20260528' and t['ts'] >= '2026-05-28T22:00:00Z')
            or (t['date']=='20260529' and t['ts'] < '2026-05-29T06:00:00Z'))
v3_night = [t for t in v3_trades if is_night(t)]
mp_night = [t for t in mp_trades if is_night(t)]
all_night = v3_night + mp_night
all_night.sort(key=lambda x: x['ts'])

print(f'=== AUDIT BOT 1 NUIT 28-29/05 ===')
print(f'Bot 1 Continuation (V3) : {len(v3_night)} trades')
print(f'Bot 3 MP : {len(mp_night)} trades')
print(f'TOTAL : {len(all_night)} trades')
print(f'PnL global : ${sum(t["pnl_usd"] for t in all_night):+.2f}')

# Load live_enriched
bars = {}
for sym in ('NQ','ES'):
    for d in ['20260528','20260529']:
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

# Features for each trade
for t in all_night:
    sym = t['sym']
    all_bars = bars.get((sym, '20260528'), []) + bars.get((sym, '20260529'), [])
    all_bars.sort(key=lambda x: x['_t'])
    target = parse_ts(t['ts'])
    prior = [b for b in all_bars if b['_t'] <= target]
    if not prior:
        t['close']=None; continue
    eb = prior[-1]
    t['close'] = eb.get('close')
    t['pir'] = eb.get('position_in_range')
    t['vslope'] = eb.get('vwap_slope_10')
    t['delta'] = eb.get('delta_bar')
    t['aggro'] = eb.get('aggressor_imbalance')
    if len(prior) >= 60:
        c60 = prior[-60].get('close')
        t['cd60'] = (t['close']-c60)/TICK[sym] if t['close'] and c60 else None
    else:
        t['cd60'] = None

# Print all with verdict
print('\n' + '='*180)
print(f'{"BOT":<3} {"TIME":<9} {"SYM":<3} {"LVL":<14} {"DIR":<5} {"ENTRY":>10} {"PIR":>5} {"VSLP":>6} {"CD60":>6} {"DELTA":>6} {"AGGRO":>6} {"EXIT":<10} {"PnL$":>8} {"VERDICT"}')
print('='*180)
for t in all_night:
    pir_s = f'{t.get("pir"):.2f}' if t.get('pir') is not None else 'NA'
    vsl_s = f'{t.get("vslope"):+.2f}' if t.get('vslope') is not None else 'NA'
    cd_s = f'{t.get("cd60"):+.0f}' if t.get('cd60') is not None else 'NA'
    db_s = f'{t.get("delta"):+.0f}' if t.get('delta') is not None else 'NA'
    ag_s = f'{t.get("aggro"):+.2f}' if t.get('aggro') is not None else 'NA'
    v = 'WIN' if t['pnl_usd']>0 else 'LOSS'
    if abs(t['pnl_usd']) > 50:
        v = '** GROS ' + v + ' **'
    print(f'{t["bot"]:<3} {t["ts"][11:19]:<9} {t["sym"]:<3} {t["level"][:14]:<14} {t["side"]:<5} {t["entry"]:>10.2f} {pir_s:>5} {vsl_s:>6} {cd_s:>6} {db_s:>6} {ag_s:>6} {t["exit_cause"]:<10} {t["pnl_usd"]:>+8.1f} {v}')

# Patterns
print('\n=== Distribution by LEVEL ===')
ls = collections.defaultdict(lambda: {'n':0,'w':0,'l':0,'pnl':0})
for t in all_night:
    k = t['level']
    ls[k]['n'] += 1
    if t['pnl_usd']>0: ls[k]['w'] += 1
    elif t['pnl_usd']<0: ls[k]['l'] += 1
    ls[k]['pnl'] += t['pnl_usd']
for k, s in sorted(ls.items(), key=lambda x: x[1]['pnl']):
    print(f'  {k:<15} n={s["n"]:<2} W={s["w"]:<2} L={s["l"]:<2} PnL=${s["pnl"]:+.2f}')

print('\n=== Distribution by BOT ===')
bs = collections.defaultdict(lambda: {'n':0,'w':0,'l':0,'pnl':0})
for t in all_night:
    bs[t['bot']]['n'] += 1
    if t['pnl_usd']>0: bs[t['bot']]['w'] += 1
    elif t['pnl_usd']<0: bs[t['bot']]['l'] += 1
    bs[t['bot']]['pnl'] += t['pnl_usd']
for k, s in bs.items():
    print(f'  {k:<3} n={s["n"]:<2} W={s["w"]:<2} L={s["l"]:<2} PnL=${s["pnl"]:+.2f}')
