"""Backtest sweep filters Bot 1 (Bot3 MP via paper_v2) sur 25-28/05 ES + NQ.

Inspire methodologie Bot 3 v4 :
- Pour chaque TRADE_OPEN, extraire features bar entry depuis live_enriched
- Sweep filters : position_in_range, vwap_slope_10, close_delta_60bars, delta_bar, aggressor
- Trouver combo qui preserve wins + bloque losses
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import itertools

TICK = {'NQ': 0.25, 'ES': 0.25, 'MGC': 0.10}
TICK_VALUE_USD = {'NQ': 0.50, 'ES': 1.25, 'MGC': 1.00}  # micro
DAYS = ['20260525','20260526','20260527','20260528']

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z', '+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# Parse Bot 1 trades (BOT3_TRADE_OPEN + BOT3_TRADE_CLOSE)
log_base = Path('D:/tmp_bot1_trading_logs')
opens_by_day = defaultdict(list)
closes_by_day = defaultdict(list)
for d in DAYS:
    fp = log_base / f'trading_{d}_paper_v2.jsonl'
    if not fp.exists(): continue
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('code') == 'BOT3_TRADE_OPEN':
                    opens_by_day[d].append(e)
                elif e.get('code') == 'BOT3_TRADE_CLOSE':
                    closes_by_day[d].append(e)
            except: pass

# Match open-close par sym + level + chronologie
trades = []
for d in DAYS:
    opens = sorted(opens_by_day[d], key=lambda x: x['ts'])
    closes = sorted(closes_by_day[d], key=lambda x: x['ts'])
    used = set()
    for op in opens:
        op_ts = parse_ts(op['ts'])
        ctx = op.get('ctx', {})
        sym = ctx.get('sym')
        level = ctx.get('level')
        # Find first close with same sym+level after open_ts
        match_idx = None
        for i, cl in enumerate(closes):
            if i in used: continue
            cl_ts = parse_ts(cl['ts'])
            if cl_ts <= op_ts: continue
            cl_ctx = cl.get('ctx', {})
            if cl_ctx.get('sym') == sym and cl_ctx.get('level') == level:
                match_idx = i
                break
        if match_idx is not None:
            used.add(match_idx)
            cl = closes[match_idx]
            cl_ctx = cl.get('ctx', {})
            pnl_ticks = cl_ctx.get('pnl', 0)
            pnl_usd = pnl_ticks * TICK_VALUE_USD.get(sym, 1.0) * ctx.get('qty', 1)
            trades.append({
                'date': d, 'ts': op['ts'], 'sym': sym, 'level': level,
                'side': ctx.get('side'), 'qty': ctx.get('qty'),
                'entry': ctx.get('price'), 'sl_ticks': ctx.get('sl'),
                'reason': cl_ctx.get('reason'),
                'pnl_ticks': pnl_ticks, 'pnl_usd': pnl_usd,
                'mfe': cl_ctx.get('mfe'), 'mae': cl_ctx.get('mae'),
            })

print(f'Total trades Bot 1 (25-28/05) : {len(trades)}')
print(f'ES trades : {sum(1 for t in trades if t["sym"]=="ES")}')
print(f'NQ trades : {sum(1 for t in trades if t["sym"]=="NQ")}')

wins = [t for t in trades if t['pnl_ticks'] > 0]
losses = [t for t in trades if t['pnl_ticks'] < 0]
print(f'\nWins : {len(wins)} (PnL ${sum(t["pnl_usd"] for t in wins):+.2f})')
print(f'Losses : {len(losses)} (PnL ${sum(t["pnl_usd"] for t in losses):+.2f})')
print(f'Total PnL : ${sum(t["pnl_usd"] for t in trades):+.2f}')

# Charger live_enriched par sym/jour
bars_by_sym_day = {}
for sym in ('ES', 'NQ'):
    for d in DAYS:
        fp = Path(f'D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/{sym}/{d}_{sym}.jsonl')
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
        bars_by_sym_day[(sym, d)] = sorted(bars, key=lambda x: x['_t'])

# Pour chaque trade : entry bar features
for t in trades:
    bars = bars_by_sym_day.get((t['sym'], t['date']), [])
    target = parse_ts(t['ts'])
    prior = [b for b in bars if b['_t'] <= target]
    if not prior:
        t['close'] = None; t['pir'] = None; t['vslope10'] = None
        t['delta_bar'] = None; t['aggro'] = None; t['close_60bars_ago'] = None
        continue
    eb = prior[-1]
    t['close'] = eb.get('close')
    t['pir'] = eb.get('position_in_range')
    t['vslope10'] = eb.get('vwap_slope_10')
    t['delta_bar'] = eb.get('delta_bar')
    t['aggro'] = eb.get('aggressor_imbalance')
    ctx60 = prior[-60:] if len(prior) >= 60 else prior
    if len(ctx60) >= 60:
        t['close_60bars_ago'] = ctx60[0].get('close')
        if t['close'] and t['close_60bars_ago']:
            t['close_delta_60'] = (t['close'] - t['close_60bars_ago']) / TICK[t['sym']]
        else:
            t['close_delta_60'] = None
    else:
        t['close_60bars_ago'] = None
        t['close_delta_60'] = None

# Filters
def F_pir(t, thr_long=0.70, thr_short=0.30):
    """LONG bloque si pir > thr_long, SHORT bloque si pir < thr_short."""
    pir = t.get('pir')
    if pir is None: return True
    if t['side'] == 'LONG' and pir > thr_long: return False
    if t['side'] == 'SHORT' and pir < thr_short: return False
    return True

def F_close_delta(t, thr_ticks=15):
    """LONG bloque si close baisse trop, SHORT bloque si close monte trop."""
    cd = t.get('close_delta_60')
    if cd is None: return True
    if t['side'] == 'SHORT' and cd > thr_ticks: return False
    if t['side'] == 'LONG' and cd < -thr_ticks: return False
    return True

def F_aggro(t, thr=0.30):
    aggro = t.get('aggro')
    if aggro is None: return True
    if t['side'] == 'LONG' and aggro < -thr: return False
    if t['side'] == 'SHORT' and aggro > thr: return False
    return True

def F_slope10(t, thr=0.20):
    sl = t.get('vslope10')
    if sl is None: return True
    if t['side'] == 'SHORT' and sl > thr: return False
    if t['side'] == 'LONG' and sl < -thr: return False
    return True

def F_delta_bar(t):
    db = t.get('delta_bar')
    if db is None: return True
    if t['side'] == 'LONG' and db < 0: return False
    if t['side'] == 'SHORT' and db > 0: return False
    return True

def measure_filter(trades, filter_fn):
    pnl = sum(t['pnl_usd'] for t in trades if filter_fn(t))
    w_pass = sum(1 for t in trades if t['pnl_ticks']>0 and filter_fn(t))
    w_veto = sum(1 for t in trades if t['pnl_ticks']>0 and not filter_fn(t))
    l_pass = sum(1 for t in trades if t['pnl_ticks']<0 and filter_fn(t))
    l_veto = sum(1 for t in trades if t['pnl_ticks']<0 and not filter_fn(t))
    return {'pnl': pnl, 'w_pass': w_pass, 'w_veto': w_veto, 'l_pass': l_pass, 'l_veto': l_veto}

baseline_pnl = sum(t['pnl_usd'] for t in trades)
print(f'\n--- BASELINE : {len(wins)}W/{len(losses)}L PnL ${baseline_pnl:+.2f} ---')

# Print all trades context
print('\n' + '='*150)
print(f'{"DATE":<11} {"TIME":<9} {"SYM":<4} {"LVL":<19} {"SIDE":<6} {"QTY":>4} {"ENTRY":>9} {"PIR":>6} {"VSLP":>7} {"CD60":>7} {"DB":>5} {"AGGRO":>7} {"REASON":<9} {"PnL_t":>7} {"PnL$":>9}')
print('='*150)
for t in trades:
    pir_s = f'{t["pir"]:.2f}' if t.get('pir') is not None else 'NA'
    vsl_s = f'{t["vslope10"]:+.2f}' if t.get('vslope10') is not None else 'NA'
    cd_s = f'{t["close_delta_60"]:+.0f}' if t.get('close_delta_60') is not None else 'NA'
    db_s = f'{t["delta_bar"]:+.0f}' if t.get('delta_bar') is not None else 'NA'
    aggro_s = f'{t["aggro"]:+.2f}' if t.get('aggro') is not None else 'NA'
    print(f'{t["date"]:<11} {t["ts"][11:19]:<9} {t["sym"]:<4} {t["level"][:19]:<19} {t["side"]:<6} {t["qty"]:>4} {t["entry"]:>9.2f} {pir_s:>6} {vsl_s:>7} {cd_s:>7} {db_s:>5} {aggro_s:>7} {t["reason"]:<9} {t["pnl_ticks"]:>+7.1f} {t["pnl_usd"]:>+9.1f}')

# Sweep PIR
print('\n=== F_PIR Sweep (LONG bloque si > thr, SHORT bloque si < 1-thr) ===')
print(f'{"thr_LONG":>9} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')
for thr_L in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    thr_S = 1 - thr_L
    m = measure_filter(trades, lambda t: F_pir(t, thr_L, thr_S))
    print(f'{thr_L:>9.2f} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f}')

# Sweep close_delta
print('\n=== F_CLOSE_DELTA_60 Sweep ===')
print(f'{"thr_ticks":>10} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')
for thr in [10, 15, 20, 30, 50, 80]:
    m = measure_filter(trades, lambda t: F_close_delta(t, thr))
    print(f'{thr:>10} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f}')

# Sweep aggro
print('\n=== F_AGGRO Sweep ===')
print(f'{"thr":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')
for thr in [0.10, 0.20, 0.30, 0.40, 0.50]:
    m = measure_filter(trades, lambda t: F_aggro(t, thr))
    print(f'{thr:>5.2f} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f}')

# Sweep slope10
print('\n=== F_SLOPE10 Sweep ===')
print(f'{"thr":>5} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')
for thr in [0.10, 0.20, 0.30, 0.50, 0.80]:
    m = measure_filter(trades, lambda t: F_slope10(t, thr))
    print(f'{thr:>5.2f} {m["w_pass"]:>6} {m["w_veto"]:>6} {m["l_pass"]:>6} {m["l_veto"]:>6} {m["pnl"]:>+10.2f} {m["pnl"]-baseline_pnl:>+10.2f}')

# Sweep delta_bar (binary)
print('\n=== F_DELTA_BAR (binary sign) ===')
m = measure_filter(trades, F_delta_bar)
print(f'{"":>5} W_pass={m["w_pass"]} W_veto={m["w_veto"]} L_pass={m["l_pass"]} L_veto={m["l_veto"]} PnL={m["pnl"]:+.2f} delta={m["pnl"]-baseline_pnl:+.2f}')

# Combos preserve all wins
print('\n=== COMBOS (filter all wins preserved) ===')
print(f'{"combo":<60} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL":>10} {"delta":>10}')

PIR_GRID = [None, 0.65, 0.70, 0.75]
CD_GRID = [None, 15, 30, 50]
AGGRO_GRID = [None, 0.30, 0.50]
SLOPE_GRID = [None, 0.20, 0.50]

results = []
for pir, cd, ag, sl in itertools.product(PIR_GRID, CD_GRID, AGGRO_GRID, SLOPE_GRID):
    def combo(t, pir=pir, cd=cd, ag=ag, sl=sl):
        if pir is not None and not F_pir(t, pir, 1-pir): return False
        if cd is not None and not F_close_delta(t, cd): return False
        if ag is not None and not F_aggro(t, ag): return False
        if sl is not None and not F_slope10(t, sl): return False
        return True
    m = measure_filter(trades, combo)
    if m['w_veto'] == 0:  # preserve all wins
        results.append({'pir':pir, 'cd':cd, 'ag':ag, 'sl':sl, **m, 'delta': m['pnl']-baseline_pnl})

results.sort(key=lambda r: -r['delta'])
for r in results[:15]:
    def fmt(v): return 'OFF' if v is None else f'{v:g}'
    lbl = f"PIR={fmt(r['pir'])} CD={fmt(r['cd'])} AG={fmt(r['ag'])} SL={fmt(r['sl'])}"
    print(f'{lbl:<60} {r["w_pass"]:>6} {r["w_veto"]:>6} {r["l_pass"]:>6} {r["l_veto"]:>6} {r["pnl"]:>+10.2f} {r["delta"]:>+10.2f}')
