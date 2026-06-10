"""Backtest 8 strategies sur 21 setups TRADE + 5 trades executes BN V4."""
import json
from pathlib import Path
from datetime import datetime, timezone

setups = []
with open('D:/tmp_setups_trade.json', encoding='utf-8') as f:
    for line in f:
        try:
            s = json.loads(line)
            setups.append(s)
        except: pass
print(f'Loaded {len(setups)} TRADE setups')

base = Path('D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ')
days = ['20260524','20260525','20260526','20260527','20260528']

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z', '+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

bars_by_day = {}
for d in days:
    fp = base / f'{d}_NQ.jsonl'
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

EXEC_OUTCOMES = {
    'BN_V4_NQ_20260526_003': ('WIN', 97.0),
    'BN_V4_NQ_20260527_001': ('WIN', 102.5),
    'BN_V4_NQ_20260528_046': ('LOSS', -19.0),
    'BN_V4_NQ_20260528_055': ('LOSS', -7.5),
    'BN_V4_NQ_20260528_057': ('LOSS', -13.5),
}

def find_entry_bar(setup):
    ts = setup.get('ts')
    if not ts: return None, None
    date_str = ts[:10].replace('-','')
    prev_day = {'20260524':None,'20260525':'20260524','20260526':'20260525','20260527':'20260526','20260528':'20260527'}.get(date_str)
    target = parse_ts(ts)
    all_bars = (bars_by_day.get(prev_day) or []) + bars_by_day.get(date_str, [])
    prior = [b for b in all_bars if b['_t'] <= target]
    if not prior: return None, None
    entry_bar = prior[-1]
    ctx60 = prior[-60:] if len(prior) >= 60 else prior
    return entry_bar, ctx60

results = []
for s in setups:
    sid = s['signal_id']
    direction = s['direction']
    n_levels = s.get('n_levels')
    entry_bar, ctx60 = find_entry_bar(s)
    if not entry_bar:
        continue
    close_now = entry_bar.get('close')
    close_60ago = ctx60[0].get('close') if ctx60 else None
    close_delta_60 = (close_now - close_60ago) / 0.25 if (close_now and close_60ago) else None
    sl_vals = [b.get('vwap_slope_10') for b in ctx60 if b.get('vwap_slope_10') is not None]
    vwap_slope_mean_60 = sum(sl_vals)/len(sl_vals) if sl_vals else None
    pir_vals = [b.get('position_in_range') for b in ctx60 if b.get('position_in_range') is not None]
    pir_mean_60 = sum(pir_vals)/len(pir_vals) if pir_vals else None
    delta_bar_now = entry_bar.get('delta_bar')
    outcome = EXEC_OUTCOMES.get(sid, ('UNKNOWN', 0.0))
    results.append({
        'sid': sid[-15:], 'date': s.get('ts','')[:10], 'dir': direction,
        'n_levels': n_levels,
        'close_delta_60t': close_delta_60, 'vwap_slope_mean_60': vwap_slope_mean_60,
        'pir_mean_60': pir_mean_60, 'delta_bar': delta_bar_now,
        'outcome': outcome[0], 'pnl': outcome[1],
    })

def strat_A(r):
    return r['n_levels'] is not None and r['n_levels'] >= 6

def strat_B(r):
    nl = r['n_levels']
    if nl is None: return False
    if nl < 5: return False
    if nl >= 7: return True
    cd = r['close_delta_60t']
    if cd is None: return False
    if r['dir']=='short' and cd > 15: return False
    if r['dir']=='long' and cd < -15: return False
    return True

def strat_ALPHA(r):
    cd = r['close_delta_60t']
    if cd is None: return True
    if r['dir']=='short' and cd > 15: return False
    if r['dir']=='long' and cd < -15: return False
    return True

def strat_GAMMA(r):
    pir = r['pir_mean_60']
    if pir is None: return True
    if r['dir']=='short' and pir < 0.50: return False
    if r['dir']=='long' and pir > 0.50: return False
    return True

def strat_BETA(r):
    sl = r['vwap_slope_mean_60']
    if sl is None: return True
    if r['dir']=='short' and sl > 0.20: return False
    if r['dir']=='long' and sl < -0.20: return False
    return True

def strat_DELTA(r):
    db = r['delta_bar']
    if db is None: return True
    if r['dir']=='short' and db > 0: return False
    if r['dir']=='long' and db < 0: return False
    return True

def strat_C(r):
    return strat_A(r) and strat_ALPHA(r)

STRATEGIES = {
    'NONE (actuel baseline)': lambda r: True,
    'A (n_levels>=6 dur)': strat_A,
    'B (SOFT n_lev+ALPHA marginal)': strat_B,
    'ALPHA seul (close_delta>15)': strat_ALPHA,
    'GAMMA seul (pir_mean_60)': strat_GAMMA,
    'BETA seul (slope_mean_60>0.2)': strat_BETA,
    'DELTA seul (delta_bar>0 short)': strat_DELTA,
    'C combo (n_lev>=6 AND ALPHA)': strat_C,
}

print('\n' + '='*150)
print(f'{"DATE":<11} {"SID":<18} {"DIR":<5} {"NL":>3} {"DLT60":>7} {"VSLP60":>7} {"PIR60":>6} {"DB":>5} {"OUTCOME":>8} {"PnL":>6}')
print('='*150)
for r in results:
    cd_s = f'{r["close_delta_60t"]:+.0f}' if r['close_delta_60t'] is not None else 'NaN'
    vs_s = f'{r["vwap_slope_mean_60"]:+.2f}' if r['vwap_slope_mean_60'] is not None else 'NaN'
    pir_s = f'{r["pir_mean_60"]:.2f}' if r['pir_mean_60'] is not None else 'NaN'
    db_s = f'{r["delta_bar"]:+.0f}' if r['delta_bar'] is not None else 'NaN'
    print(f"{r['date']:<11} {r['sid']:<18} {r['dir']:<5} {str(r['n_levels']):>3} {cd_s:>7} {vs_s:>7} {pir_s:>6} {db_s:>5} {r['outcome']:>8} {r['pnl']:>6.1f}")

print('\n' + '='*110)
print(f'{"STRATEGY":<35} {"setups":>9} {"%":>5} {"WIN_pass":>9} {"LOSS_pass":>10} {"PnL_exec":>10}')
print('='*110)
exec_results = [r for r in results if r['outcome'] != 'UNKNOWN']
for name, fn in STRATEGIES.items():
    n_pass = sum(1 for r in results if fn(r))
    n_win_pass = sum(1 for r in exec_results if r['outcome']=='WIN' and fn(r))
    n_loss_pass = sum(1 for r in exec_results if r['outcome']=='LOSS' and fn(r))
    pnl_total = sum(r['pnl'] for r in exec_results if fn(r))
    print(f"{name:<35} {n_pass:>3}/{len(results):<5} {100*n_pass/len(results):>4.0f}% {n_win_pass:>9} {n_loss_pass:>10} {pnl_total:>10.1f}")
