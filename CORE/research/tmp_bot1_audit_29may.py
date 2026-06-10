"""Audit Bot 1 trades nuit 28/29 mai (Asia + early London).

11 trades observes :
- 4 wins (TP) : +$219.50
- 7 losses : -$167.00
- PnL net : +$52.50 (33% WR, mais 1 gros win ES +$187.50 et 1 gros loss ES -$125)

Audit :
- Features bar entry (PIR, slope, delta, aggro, close_delta_60)
- Test combo CD30+AG30 (filter Bot 1 backtest 24-28/05)
- Identifier patterns wins vs losses
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import collections

TICK = {'NQ': 0.25, 'ES': 0.25}
TICK_VALUE_USD = {'NQ': 0.50, 'ES': 1.25}
DAYS = ['20260528','20260529']  # cross-day (Asia: 22h-04h UTC)

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z', '+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

# Parse trades
log_base = Path('D:/tmp_bot1_trading_logs')
opens_by_day = collections.defaultdict(list)
closes_by_day = collections.defaultdict(list)
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

# Match open-close
trades = []
for d in DAYS:
    opens = sorted(opens_by_day[d], key=lambda x: x['ts'])
    closes = sorted(closes_by_day[d], key=lambda x: x['ts'])
    used = set()
    for op in opens:
        op_ts = parse_ts(op['ts'])
        ctx = op.get('ctx', {})
        sym = ctx.get('sym'); level = ctx.get('level')
        match_idx = None
        for i, cl in enumerate(closes):
            if i in used: continue
            if parse_ts(cl['ts']) <= op_ts: continue
            cl_ctx = cl.get('ctx', {})
            if cl_ctx.get('sym') == sym and cl_ctx.get('level') == level:
                match_idx = i; break
        if match_idx is not None:
            used.add(match_idx)
            cl = closes[match_idx]; cl_ctx = cl.get('ctx', {})
            pnl_ticks = cl_ctx.get('pnl', 0)
            qty = ctx.get('qty', 1)
            pnl_usd = pnl_ticks * TICK_VALUE_USD.get(sym, 1) * qty
            trades.append({
                'date': d, 'ts': op['ts'], 'sym': sym, 'level': level,
                'side': ctx.get('side'), 'qty': qty,
                'entry': ctx.get('price'), 'sl_ticks': ctx.get('sl'),
                'reason': cl_ctx.get('reason'),
                'pnl_ticks': pnl_ticks, 'pnl_usd': pnl_usd,
                'mfe': cl_ctx.get('mfe'), 'mae': cl_ctx.get('mae'),
                'duration_sec': cl_ctx.get('dur'),
            })

# Filtrer trades de la session de la nuit (22:00 UTC 28/05 -> 06:00 UTC 29/05)
session_trades = [t for t in trades
                  if (t['date']=='20260528' and t['ts'] >= '2026-05-28T22:00:00Z')
                  or (t['date']=='20260529' and t['ts'] < '2026-05-29T06:00:00Z')]
print(f'Trades session nuit 28-29/05 : {len(session_trades)}')
print(f'Total PnL : ${sum(t["pnl_usd"] for t in session_trades):+.2f}')

# Load live_enriched
bars_by_sym_day = {}
for sym in ('NQ','ES'):
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

# For each trade : extract features bar entry
for t in session_trades:
    # Get bars for both days for context spanning
    bars_today = bars_by_sym_day.get((t['sym'], t['date']), [])
    other_day = '20260528' if t['date'] == '20260529' else '20260529'
    bars_other = bars_by_sym_day.get((t['sym'], other_day), [])
    # Use both days for context window
    all_bars = bars_other + bars_today
    all_bars.sort(key=lambda x: x['_t'])
    target = parse_ts(t['ts'])
    prior = [b for b in all_bars if b['_t'] <= target]
    if not prior:
        t['close']=None; t['pir']=None; t['vslope']=None; t['delta']=None; t['aggro']=None; t['cd60']=None
        continue
    eb = prior[-1]
    t['close'] = eb.get('close')
    t['pir'] = eb.get('position_in_range')
    t['vslope'] = eb.get('vwap_slope_10')
    t['delta'] = eb.get('delta_bar')
    t['aggro'] = eb.get('aggressor_imbalance')
    t['mq_hvl'] = eb.get('mq_hvl')
    t['atr'] = eb.get('atr_14m')
    t['session_high'] = eb.get('session_high')
    t['session_low'] = eb.get('session_low')
    if len(prior) >= 60:
        c60 = prior[-60].get('close')
        if t['close'] and c60:
            t['cd60'] = (t['close'] - c60) / TICK[t['sym']]
        else:
            t['cd60'] = None
    else:
        t['cd60'] = None

# Print all trades with context
print('\n' + '='*180)
print(f'{"HEURE":<9} {"SYM":<3} {"LVL":<18} {"DIR":<5} {"QTY":>4} {"ENTRY":>10} {"PIR":>5} {"VSLP":>7} {"CD60":>6} {"DELTA":>6} {"AGGRO":>6} {"REASON":<10} {"PnL_t":>6} {"PnL$":>8} {"VERDICT":<20}')
print('='*180)
for t in session_trades:
    pir_s = f'{t["pir"]:.2f}' if t.get('pir') is not None else 'NA'
    vsl_s = f'{t["vslope"]:+.2f}' if t.get('vslope') is not None else 'NA'
    cd_s = f'{t["cd60"]:+.0f}' if t.get('cd60') is not None else 'NA'
    db_s = f'{t["delta"]:+.0f}' if t.get('delta') is not None else 'NA'
    ag_s = f'{t["aggro"]:+.2f}' if t.get('aggro') is not None else 'NA'
    is_win = t['pnl_ticks'] > 0
    verdict = 'WIN' if is_win else 'LOSS'
    if abs(t['pnl_usd']) > 100:
        verdict = '** GROS ' + verdict + ' **'
    print(f'{t["ts"][11:19]:<9} {t["sym"]:<3} {t["level"][:18]:<18} {t["side"]:<5} {t["qty"]:>4} {t["entry"]:>10.2f} {pir_s:>5} {vsl_s:>7} {cd_s:>6} {db_s:>6} {ag_s:>6} {t["reason"]:<10} {t["pnl_ticks"]:>+6.1f} {t["pnl_usd"]:>+8.1f} {verdict:<20}')

# Stats by level
print('\n=== Par LEVEL ===')
lvl_stats = collections.defaultdict(lambda: {'n':0,'w':0,'l':0,'pnl':0.0})
for t in session_trades:
    k = t['level']
    lvl_stats[k]['n'] += 1
    if t['pnl_ticks'] > 0: lvl_stats[k]['w'] += 1
    elif t['pnl_ticks'] < 0: lvl_stats[k]['l'] += 1
    lvl_stats[k]['pnl'] += t['pnl_usd']
for k, s in sorted(lvl_stats.items(), key=lambda x: x[1]['pnl']):
    print(f'  {k:<20} n={s["n"]:<3} W={s["w"]:<2} L={s["l"]:<2} PnL=${s["pnl"]:+.2f}')

# Test combo CD30+AG30 retroactivement
def F_combo(t, cd_thr=30, ag_thr=0.30):
    """Bot 1 combo : veto LONG si aggro < -0.30 OR close_delta_60 < -30t."""
    a = t.get('aggro')
    cd = t.get('cd60')
    if a is None and cd is None: return True
    if t['side'] == 'BUY':  # LONG
        if a is not None and a < -ag_thr: return False
        if cd is not None and cd < -cd_thr: return False
    elif t['side'] == 'SELL':  # SHORT
        if a is not None and a > ag_thr: return False
        if cd is not None and cd > cd_thr: return False
    return True

print('\n=== Backtest combo CD=30 + AG=0.30 (retro nuit 28/29) ===')
baseline = sum(t['pnl_usd'] for t in session_trades)
wins_baseline = sum(1 for t in session_trades if t['pnl_ticks']>0)
losses_baseline = sum(1 for t in session_trades if t['pnl_ticks']<0)
print(f'Baseline : {wins_baseline}W/{losses_baseline}L PnL ${baseline:+.2f}')

pass_combo = [t for t in session_trades if F_combo(t)]
veto_combo = [t for t in session_trades if not F_combo(t)]
filtered_pnl = sum(t['pnl_usd'] for t in pass_combo)
print(f'\nApres filter CD30+AG30 :')
print(f'  PASS : {len(pass_combo)} trades, PnL ${filtered_pnl:+.2f}')
for t in pass_combo:
    print(f'    {t["ts"][11:19]} {t["sym"]} {t["level"][:18]:<18} {t["side"]} PnL${t["pnl_usd"]:+.2f} ({"WIN" if t["pnl_ticks"]>0 else "LOSS"})')
print(f'  VETO : {len(veto_combo)} trades, PnL bloque ${sum(t["pnl_usd"] for t in veto_combo):+.2f}')
for t in veto_combo:
    print(f'    {t["ts"][11:19]} {t["sym"]} {t["level"][:18]:<18} {t["side"]} aggro={t.get("aggro")} cd60={t.get("cd60")} PnL${t["pnl_usd"]:+.2f} ({"WIN" if t["pnl_ticks"]>0 else "LOSS"})')
print(f'\nDELTA combo : ${filtered_pnl - baseline:+.2f}')
