"""Backtest delta_div features sur 5 jours NQ live_enriched.

Pour chaque fire (delta_div_buy_clean=1 ou delta_div_sell_clean=1) :
  - Calcule MFE / MAE / close à +5, +10, +20 bars
  - Win rate hypothetique R:R 1:1 (TP=10t, SL=10t)

Compare avec baseline (toutes bars confondues).
"""
import json
from pathlib import Path
from datetime import datetime, timezone

TICK = 0.25
DAYS = ['20260524','20260525','20260526','20260527','20260528']
BASE = Path('D:/TRADING_SIERRA_CHART_AUTO/DATA/live_enriched/NQ')

def parse_ts(s):
    if 'Z' in s: s = s.replace('Z', '+00:00')
    if '+' not in s and 'T' in s: s += '+00:00'
    return datetime.fromisoformat(s)

bars = []
for d in DAYS:
    fp = BASE / f'{d}_NQ.jsonl'
    if not fp.exists(): continue
    with open(fp, encoding='utf-8') as f:
        for line in f:
            try:
                b = json.loads(line)
                t = b.get('ts_event')
                if t:
                    b['_t'] = parse_ts(t)
                    bars.append(b)
            except: pass
bars.sort(key=lambda x: x['_t'])
# Dedup : keep first occurrence per ts_event (file split entre live_enriched produit doublons)
seen = set()
uniq = []
for b in bars:
    t = b['_t']
    if t in seen: continue
    seen.add(t); uniq.append(b)
bars = uniq
print(f'Bars uniques 24-28/05 NQ : {len(bars)}')

def get(b, k):
    v = b.get(k)
    if v is None: return None
    try:
        f = float(v)
        if f != f: return None
        return f
    except (ValueError, TypeError): return None

# Liste des features delta_div binaires/numeriques a tester
FEATURES_TO_TEST = {
    # Binaires (1=fire)
    'delta_div_buy': lambda b: get(b, 'delta_div_buy') == 1,
    'delta_div_buy_clean': lambda b: get(b, 'delta_div_buy_clean') == 1,
    'delta_div_sell': lambda b: get(b, 'delta_div_sell') == 1,
    'delta_div_sell_clean': lambda b: get(b, 'delta_div_sell_clean') == 1,
    'delta_divergence_clean': lambda b: get(b, 'delta_divergence_clean') == 1,
    # Cluster proxies
    'n_buy_cluster>=2': lambda b: (get(b, 'n_delta_div_buy_cluster_within_0_2pct') or 0) >= 2,
    'n_buy_cluster>=4': lambda b: (get(b, 'n_delta_div_buy_cluster_within_0_2pct') or 0) >= 4,
    'n_sell_cluster>=2': lambda b: (get(b, 'n_delta_div_sell_cluster_within_0_2pct') or 0) >= 2,
    'n_sell_cluster>=4': lambda b: (get(b, 'n_delta_div_sell_cluster_within_0_2pct') or 0) >= 4,
    # Strength
    'delta_div_strength>=0.5': lambda b: (get(b, 'delta_div_strength') or 0) >= 0.5,
}

# Pour chaque feature, mesurer mouvement post-fire
def measure_move(idx, n_bars):
    """Retourne (max_high - close_now, min_low - close_now) sur n_bars apres idx."""
    if idx + n_bars >= len(bars): return None
    close_now = get(bars[idx], 'close')
    if close_now is None: return None
    highs = []
    lows = []
    for j in range(1, n_bars+1):
        h = get(bars[idx+j], 'bar_high') or get(bars[idx+j], 'close')
        l = get(bars[idx+j], 'bar_low') or get(bars[idx+j], 'close')
        if h is not None: highs.append(h)
        if l is not None: lows.append(l)
    if not highs or not lows: return None
    return (max(highs) - close_now)/TICK, (min(lows) - close_now)/TICK, (get(bars[idx+n_bars],'close') - close_now)/TICK if get(bars[idx+n_bars],'close') is not None else None

# Direction du fire (pour mesurer MFE direction-aware)
DIRECTION = {
    'delta_div_buy': 'LONG',
    'delta_div_buy_clean': 'LONG',
    'n_buy_cluster>=2': 'LONG',
    'n_buy_cluster>=4': 'LONG',
    'delta_div_sell': 'SHORT',
    'delta_div_sell_clean': 'SHORT',
    'n_sell_cluster>=2': 'SHORT',
    'n_sell_cluster>=4': 'SHORT',
    'delta_divergence_clean': 'EITHER',
    'delta_div_strength>=0.5': 'EITHER',
}

print(f'\n{"FEATURE":<30} {"FIRES":>8} {"RATE%":>6} {"MFE+5t":>8} {"MAE+5t":>8} {"CLOSE+5t":>9} {"MFE+10":>7} {"MAE+10":>7} {"CLOSE+10":>9} {"MFE+20":>7} {"MAE+20":>7} {"R:R 1:1 WR@10t":>16}')
print('=' * 145)

for fname, fn in FEATURES_TO_TEST.items():
    direction = DIRECTION[fname]
    # Trouver tous les fires
    fires = [i for i, b in enumerate(bars) if fn(b)]
    n_fires = len(fires)
    rate = 100 * n_fires / len(bars) if bars else 0

    mfes5, maes5, closes5 = [], [], []
    mfes10, maes10, closes10 = [], [], []
    mfes20, maes20, closes20 = [], [], []
    wins_rr1, total_evaluated = 0, 0

    for i in fires:
        m5 = measure_move(i, 5)
        m10 = measure_move(i, 10)
        m20 = measure_move(i, 20)
        if m5:
            mfe, mae, cls = m5
            if direction == 'LONG':
                mfes5.append(mfe); maes5.append(mae); closes5.append(cls)
            elif direction == 'SHORT':
                mfes5.append(-mae); maes5.append(-mfe); closes5.append(-cls if cls else None)
            else:
                mfes5.append(max(mfe, -mae) if mfe is not None and mae is not None else None)
        if m10:
            mfe, mae, cls = m10
            if direction == 'LONG':
                mfes10.append(mfe); maes10.append(mae); closes10.append(cls)
            elif direction == 'SHORT':
                mfes10.append(-mae); maes10.append(-mfe); closes10.append(-cls if cls else None)
            # R:R 1:1 sim : si MFE>=10t avant que MAE<=-10t -> WIN
            if direction in ('LONG', 'SHORT'):
                # Cherche bar-by-bar dans 10 bars apres
                close_now = get(bars[i], 'close')
                hit_tp = False; hit_sl = False
                for j in range(1, 11):
                    if i+j >= len(bars): break
                    h = get(bars[i+j], 'bar_high'); l = get(bars[i+j], 'bar_low')
                    if h is None or l is None: continue
                    if direction == 'LONG':
                        if (l - close_now)/TICK <= -10: hit_sl = True; break
                        if (h - close_now)/TICK >= 10: hit_tp = True; break
                    elif direction == 'SHORT':
                        if (h - close_now)/TICK >= 10: hit_sl = True; break
                        if (l - close_now)/TICK <= -10: hit_tp = True; break
                if hit_tp:
                    wins_rr1 += 1
                if hit_tp or hit_sl:
                    total_evaluated += 1
        if m20:
            mfe, mae, cls = m20
            if direction == 'LONG':
                mfes20.append(mfe); maes20.append(mae); closes20.append(cls)
            elif direction == 'SHORT':
                mfes20.append(-mae); maes20.append(-mfe); closes20.append(-cls if cls else None)

    def avg(lst):
        clean = [x for x in lst if x is not None]
        return sum(clean)/len(clean) if clean else None
    def fmt(v):
        if v is None: return 'NA'
        return f'{v:+.1f}'

    avg5_mfe = fmt(avg(mfes5))
    avg5_mae = fmt(avg(maes5))
    avg5_close = fmt(avg(closes5))
    avg10_mfe = fmt(avg(mfes10))
    avg10_mae = fmt(avg(maes10))
    avg10_close = fmt(avg(closes10))
    avg20_mfe = fmt(avg(mfes20))
    avg20_mae = fmt(avg(maes20))
    wr_s = f'{100*wins_rr1/total_evaluated:.0f}% ({wins_rr1}/{total_evaluated})' if total_evaluated else 'NA'

    print(f'{fname:<30} {n_fires:>8} {rate:>5.2f}% {avg5_mfe:>8} {avg5_mae:>8} {avg5_close:>9} {avg10_mfe:>7} {avg10_mae:>7} {avg10_close:>9} {avg20_mfe:>7} {avg20_mae:>7} {wr_s:>16}')

# BASELINE : tous les bars (random entry)
print('\n=== BASELINE (random entry - reference comparaison) ===')
import random
random.seed(42)
sample_idxs = random.sample(range(len(bars)), min(300, len(bars)))
for direction in ['LONG', 'SHORT']:
    wins = 0; total = 0
    for i in sample_idxs:
        close_now = get(bars[i], 'close')
        if close_now is None: continue
        hit_tp = False; hit_sl = False
        for j in range(1, 11):
            if i+j >= len(bars): break
            h = get(bars[i+j], 'bar_high'); l = get(bars[i+j], 'bar_low')
            if h is None or l is None: continue
            if direction == 'LONG':
                if (l - close_now)/TICK <= -10: hit_sl = True; break
                if (h - close_now)/TICK >= 10: hit_tp = True; break
            else:
                if (h - close_now)/TICK >= 10: hit_sl = True; break
                if (l - close_now)/TICK <= -10: hit_tp = True; break
        if hit_tp: wins += 1
        if hit_tp or hit_sl: total += 1
    wr_baseline = 100 * wins / total if total else 0
    print(f'  {direction} random R:R 1:1 (10t/10t) sur 10 bars : {wr_baseline:.0f}% ({wins}/{total})')
