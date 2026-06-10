"""Backtest CONFIRMATION POST-TOUCH pour Bot 3 v4.

Logique :
- TOUCH detecte a bar T → NO ENTRY immediate
- Bar T+1 receive → check si close encore cote favorable du niveau + buffer
- Si OUI : ENTRY a close T+1 (prix different)
- Si NON : VETO trade

Trade-offs :
- (+) Evite les entries au pic d'un breakout/breakdown explosif
- (-) Entry price moins favorable (1 min retard)
- (-) Plus restrictif (moins de trades)

Sweep buffer T+1 confirmation : 3, 5, 8, 15 ticks.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import collections

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

# Parse Bot 3 v4 logs : trades closed
log_base = Path('D:/tmp_bot3_v4_logs')
all_trades = []  # tous TRADE_CLOSE avec pnl_usd
for d in DAYS:
    fp = log_base / f'bot3_v4_v1_{d}.jsonl'
    if not fp.exists(): continue
    opens = {}
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get('event') == 'TRADE_OPEN':
                    opens[e.get('signal_id')] = e
                elif e.get('event') == 'TRADE_CLOSE':
                    sid = e.get('signal_id')
                    op = opens.get(sid)
                    if op:
                        pnl = e.get('pnl_usd', 0) or 0
                        outcome = e.get('outcome') or ('WIN' if pnl > 0.5 else ('LOSS' if pnl < -0.5 else 'BE'))
                        all_trades.append({
                            'sid': sid, 'date': d, 'ts': op['ts'],
                            'level': op.get('level'), 'side': op.get('side'),
                            'entry': op.get('entry_price'),
                            'outcome': outcome, 'pnl_usd': pnl,
                            'exit_cause': e.get('exit_cause'),
                            'duration_bars': e.get('duration_bars'),
                            'tp_price': op.get('tp_price'),
                            'sl_price': op.get('sl_price'),
                        })
            except: pass

print(f'Total matched trades : {len(all_trades)}')

# Load NQ bars per day + previous day
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

# Pour chaque trade : extraire bar T (TOUCH) + bar T+1 (confirmation)
for t in all_trades:
    bars_today = bars_by_day.get(t['date'], [])
    bars_yest = bars_by_day.get(PREV_DAY.get(t['date']), []) or []
    all_bars = bars_yest + bars_today
    all_bars.sort(key=lambda x: x['_t'])
    target = parse_ts(t['ts'])
    # bar T = la bar du TOUCH (close <= ts)
    prior = [(idx, b) for idx, b in enumerate(all_bars) if b['_t'] <= target]
    if not prior:
        t['bar_T_close'] = None
        t['bar_T1_close'] = None
        t['level_price'] = None
        continue
    idx_T, bar_T = prior[-1]
    t['bar_T_close'] = bar_T.get('close')
    col = LEVEL_TO_COL.get(t['level'])
    t['level_price'] = bar_T.get(col) if col else None
    # bar T+1 = next bar dans live_enriched
    if idx_T + 1 < len(all_bars):
        bar_T1 = all_bars[idx_T + 1]
        # Dedup : si timestamp == bar_T, prendre la suivante
        while idx_T + 1 < len(all_bars) and all_bars[idx_T + 1]['_t'] == bar_T['_t']:
            idx_T += 1
        if idx_T + 1 < len(all_bars):
            bar_T1 = all_bars[idx_T + 1]
            t['bar_T1_close'] = bar_T1.get('close')
            t['bar_T1_high'] = bar_T1.get('bar_high')
            t['bar_T1_low'] = bar_T1.get('bar_low')
        else:
            t['bar_T1_close'] = None
    else:
        t['bar_T1_close'] = None

# Filter logique : entry seulement si T+1 close encore cote favorable + buffer
def F_confirmation(t, buffer_ticks):
    """True = trade pass (confirme), False = veto."""
    t1 = t.get('bar_T1_close'); lp = t.get('level_price'); side = t.get('side')
    if t1 is None or lp is None: return True  # contexte manquant : pass
    buf = buffer_ticks * TICK
    if side == 'SHORT':
        # SHORT : T+1 doit close encore SOUS le niveau - buffer
        return t1 < lp - buf
    if side == 'LONG':
        # LONG : T+1 doit close encore AU-DESSUS du niveau + buffer
        return t1 > lp + buf
    return True

# Simuler trade avec entry @ T+1 close au lieu de entry original
def simulate_with_t1_entry(t, sl_ticks_buffer=30):
    """Retourne (outcome_simulated, pnl_simulated_usd)."""
    t1 = t.get('bar_T1_close')
    lp = t.get('level_price')
    side = t['side']
    if t1 is None or lp is None: return ('UNKNOWN', 0)
    # Nouvelle entry @ T+1 close
    # Nouveau SL @ niveau (= lp), TP @ niveau ± 2*sl_ticks (R:R 2)
    if side == 'LONG':
        new_entry = t1
        new_sl = lp  # SL au niveau (juste sous T+1 close)
        sl_dist_ticks = (new_entry - new_sl) / TICK
        if sl_dist_ticks <= 0: return ('UNKNOWN', 0)
        # On suppose mêmes TP/SL ratios que original
        new_tp = new_entry + sl_dist_ticks * 1.5 * TICK
    else:
        new_entry = t1
        new_sl = lp
        sl_dist_ticks = (new_sl - new_entry) / TICK
        if sl_dist_ticks <= 0: return ('UNKNOWN', 0)
        new_tp = new_entry - sl_dist_ticks * 1.5 * TICK

    # Simplification : on suppose que si le trade original (avec entry plus tot) a WIN,
    # alors le trade avec T+1 entry aussi WIN (mais peut-etre avec PnL different)
    # Si trade original a LOSS, on regarde si T+1 a tjs valide la direction (donc apres confirmation)
    # = la confirmation va PRESERVER les WIN et bloquer certains LOSS
    return ('SIMULATED', t['pnl_usd'])  # placeholder

# Stats : combien WINS et LOSSES passent avec confirmation buffer X
print('\n' + '='*100)
print('CONFIRMATION POST-TOUCH BUFFER SWEEP')
print('='*100)

def measure(trades_in, filter_fn):
    pnl = sum(t['pnl_usd'] for t in trades_in if filter_fn(t))
    w_pass = sum(1 for t in trades_in if t['outcome']=='WIN' and filter_fn(t))
    w_veto = sum(1 for t in trades_in if t['outcome']=='WIN' and not filter_fn(t))
    l_pass = sum(1 for t in trades_in if t['outcome']=='LOSS' and filter_fn(t))
    l_veto = sum(1 for t in trades_in if t['outcome']=='LOSS' and not filter_fn(t))
    return pnl, w_pass, w_veto, l_pass, l_veto

closed = [t for t in all_trades if t['outcome'] in ('WIN','LOSS','BE')]
baseline = sum(t['pnl_usd'] for t in closed)
n_wins_total = sum(1 for t in closed if t['outcome']=='WIN')
n_losses_total = sum(1 for t in closed if t['outcome']=='LOSS')
print(f'Sample : {len(closed)} trades closed | {n_wins_total}W/{n_losses_total}L | Baseline PnL ${baseline:+.2f}')

print(f'\n{"BUFFER":>7} {"W_pass":>6} {"W_veto":>6} {"L_pass":>6} {"L_veto":>6} {"PnL_keep":>10} {"delta":>10} {"%W_pres":>8} {"%L_veto":>8}')
for buf in [0, 2, 3, 5, 8, 10, 15, 20, 30]:
    pnl, wp, wv, lp, lv = measure(closed, lambda t: F_confirmation(t, buf))
    w_pres = 100*wp/max(n_wins_total,1)
    l_block = 100*lv/max(n_losses_total,1)
    print(f'{buf:>7} {wp:>6} {wv:>6} {lp:>6} {lv:>6} {pnl:>+10.2f} {pnl-baseline:>+10.2f} {w_pres:>7.0f}% {l_block:>7.0f}%')

# Detail buffer=5 (medium)
print('\n=== DETAIL buffer=5t (medium) ===')
print(f'{"DATE":<11} {"SIDE":<6} {"LEVEL":<13} {"close_T":>9} {"close_T+1":>10} {"level":>10} {"diff_T+1":>9} {"OUT":<5} {"PnL":>7} {"PASS":<5}')
for t in closed:
    cT = t.get('bar_T_close'); cT1 = t.get('bar_T1_close'); lp = t.get('level_price')
    cT_s = f'{cT:.2f}' if cT is not None else 'NA'
    cT1_s = f'{cT1:.2f}' if cT1 is not None else 'NA'
    lp_s = f'{lp:.2f}' if isinstance(lp, float) else 'NA'
    diff = None
    if cT1 is not None and isinstance(lp, float):
        diff = (cT1 - lp) / TICK
    diff_s = f'{diff:+.0f}' if diff is not None else 'NA'
    keep = F_confirmation(t, 5)
    print(f"{t['date']:<11} {t['side']:<6} {t['level'][:13]:<13} {cT_s:>9} {cT1_s:>10} {lp_s:>10} {diff_s:>9} {t['outcome']:<5} {t['pnl_usd']:>+7.1f} {'PASS' if keep else 'VETO':<5}")
PYEOF
