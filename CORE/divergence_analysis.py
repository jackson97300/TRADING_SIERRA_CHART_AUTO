"""Analyse des divergences sur donnees DMP."""
import sys, pandas as pd, numpy as np
from scipy import stats
sys.path.insert(0, 'D:/TRADING_SIERRA_CHART_AUTO/CORE')
from dmp_reader import DmpReader

reader = DmpReader('D:/TRADING_SIERRA_CHART_AUTO/DATA')
dates = ['20260330', '20260331', '20260401']
TICK = 0.25; TP = 20; SL = 20

def load_all(sym):
    frames = []
    for d in dates:
        try:
            df = reader.load_file(f'D:/TRADING_SIERRA_CHART_AUTO/DATA/{sym}/{d}_{sym}.jsonl')
            if df is not None: frames.append(df)
        except: pass
    return pd.concat(frames, ignore_index=True)

def label(df):
    p = df['price'].values; n = len(p)
    br, sr = np.zeros(n, int), np.zeros(n, int)
    for i in range(n - 1):
        e = p[i]
        for j in range(i + 1, min(i + 31, n)):
            if p[j] >= e + TP * TICK: br[i] = 1; break
            if p[j] <= e - SL * TICK: br[i] = -1; break
        for j in range(i + 1, min(i + 31, n)):
            if p[j] <= e - TP * TICK: sr[i] = 1; break
            if p[j] >= e + SL * TICK: sr[i] = -1; break
    df['bw'] = br == 1; df['bl'] = br == -1
    df['sw'] = sr == 1; df['sl_'] = sr == -1
    return df

def test(df, mask, direction, label_str):
    if direction == 'buy':
        wc, lc = 'bw', 'bl'
    else:
        wc, lc = 'sw', 'sl_'
    tm = mask & (df[wc] | df[lc])
    n = tm.sum()
    if n < 5:
        return None
    wr = df.loc[tm, wc].mean()
    w = int(df.loc[tm, wc].sum())
    base = df[df[wc] | df[lc]][wc].mean()
    edge = wr - base
    pf = (w * TP) / max((n - w) * SL, 1)
    pv = stats.binomtest(w, int(n), base, alternative='greater').pvalue
    v = 'VALIDE' if pv < 0.05 else 'FRAGILE' if pv < 0.15 else 'bruit'
    print(f'  {direction.upper():4s} | {label_str:55s} | WR={wr:.1%} edge={edge:+.1%} n={n:3d} PF={pf:.2f} p={pv:.3f} [{v}]')
    return {'rule': label_str, 'd': direction, 'wr': wr, 'edge': edge, 'n': int(n), 'pf': pf, 'pv': pv}

for sym in ['ES', 'NQ']:
    df = load_all(sym)

    # Construire divergences derivees
    df['price_diff_10'] = df['price'].diff(10)

    # 1. CVD vs Prix
    if 'cvd_day' in df.columns:
        df['cvd_diff_10'] = df['cvd_day'].diff(10)
        df['div_cvd_bear'] = (df['price_diff_10'] > 2) & (df['cvd_diff_10'] < -50)
        df['div_cvd_bull'] = (df['price_diff_10'] < -2) & (df['cvd_diff_10'] > 50)

    # 2. VWAP slope vs prix
    if 'vwap_slope_10' in df.columns:
        df['div_vwap_bear'] = (df['price_diff_10'] > 2) & (df['vwap_slope_10'] < -0.5)
        df['div_vwap_bull'] = (df['price_diff_10'] < -2) & (df['vwap_slope_10'] > 0.5)

    # 3. Delta bar vs mouvement
    if 'delta_bar' in df.columns:
        df['div_dbar_bear'] = (df['price'].diff() > 0) & (df['delta_bar'] < -50)
        df['div_dbar_bull'] = (df['price'].diff() < 0) & (df['delta_bar'] > 50)

    # 4. Pullback Delta
    if 'high_pullback_delta' in df.columns:
        df['div_hpd_sell'] = df['high_pullback_delta'] < -10
        df['div_lpd_buy'] = df['low_pullback_delta'] < -10

    # 5. Diagonal Imbalance
    if 'diag_pos_delta' in df.columns:
        df['diag_ratio'] = df['diag_pos_delta'] / (df['diag_neg_delta'] + 1)
        df['div_diag_bear'] = (df['price_diff_10'] > 2) & (df['diag_ratio'] < 0.5)
        df['div_diag_bull'] = (df['price_diff_10'] < -2) & (df['diag_ratio'] > 2.0)

    df = label(df)

    buy_base = df[df['bw'] | df['bl']]['bw'].mean()
    sell_base = df[df['sw'] | df['sl_']]['sw'].mean()

    print(f'\n{"=" * 70}')
    print(f'  {sym} — DIVERGENCES (base BUY={buy_base:.1%} SELL={sell_base:.1%})')
    print(f'{"=" * 70}')

    # 1. CVD vs Prix
    print(f'\n  --- CVD vs Prix (10 barres) ---')
    test(df, df.get('div_cvd_bear', pd.Series(False, index=df.index)), 'sell', 'prix monte + CVD baisse (div bearish)')
    test(df, df.get('div_cvd_bull', pd.Series(False, index=df.index)), 'buy', 'prix baisse + CVD monte (div bullish)')

    # 2. VWAP slope
    print(f'\n  --- VWAP Slope vs Prix ---')
    test(df, df.get('div_vwap_bear', pd.Series(False, index=df.index)), 'sell', 'prix monte + VWAP slope negatif')
    test(df, df.get('div_vwap_bull', pd.Series(False, index=df.index)), 'buy', 'prix baisse + VWAP slope positif')

    # 3. Delta bar
    print(f'\n  --- Delta Bar vs Mouvement ---')
    test(df, df.get('div_dbar_bear', pd.Series(False, index=df.index)), 'sell', 'prix monte + delta_bar < -50')
    test(df, df.get('div_dbar_bull', pd.Series(False, index=df.index)), 'buy', 'prix baisse + delta_bar > +50')

    # 4. Pullback
    print(f'\n  --- Pullback Delta ---')
    test(df, df.get('div_hpd_sell', pd.Series(False, index=df.index)), 'sell', 'high_pullback_delta < -10 (vendeurs au high)')
    test(df, df.get('div_lpd_buy', pd.Series(False, index=df.index)), 'buy', 'low_pullback_delta < -10 (acheteurs au low)')

    # 5. Diagonal
    print(f'\n  --- Diagonal Imbalance ---')
    test(df, df.get('div_diag_bear', pd.Series(False, index=df.index)), 'sell', 'prix monte + diag ratio < 0.5')
    test(df, df.get('div_diag_bull', pd.Series(False, index=df.index)), 'buy', 'prix baisse + diag ratio > 2.0')

    # === COMBOS ===
    print(f'\n  --- COMBOS : Divergence + Double Top/Bottom ---')

    if 'retest_high_count' in df.columns and 'div_cvd_bear' in df.columns:
        mask = (df['retest_high_count'] >= 2) & df['div_cvd_bear']
        test(df, mask, 'sell', 'double_top + CVD divergence bearish')
        mask = (df['retest_high_count'] >= 1) & df['div_cvd_bear']
        test(df, mask, 'sell', 'retest_high>=1 + CVD div bearish')
        mask = (df['retest_high_count'] >= 1) & df['div_dbar_bear']
        test(df, mask, 'sell', 'retest_high>=1 + delta_bar div bearish')

    if 'retest_low_count' in df.columns and 'div_cvd_bull' in df.columns:
        mask = (df['retest_low_count'] >= 2) & df['div_cvd_bull']
        test(df, mask, 'buy', 'double_bottom + CVD divergence bullish')
        mask = (df['retest_low_count'] >= 1) & df['div_cvd_bull']
        test(df, mask, 'buy', 'retest_low>=1 + CVD div bullish')
        mask = (df['retest_low_count'] >= 1) & df['div_dbar_bull']
        test(df, mask, 'buy', 'retest_low>=1 + delta_bar div bullish')

    # Absorption + divergence
    print(f'\n  --- Absorption + Divergence ---')
    if 'bn_absorb_ask' in df.columns and 'div_cvd_bear' in df.columns:
        mask = (df['bn_absorb_ask'] > 0) & df['div_cvd_bear']
        test(df, mask, 'sell', 'absorption ask + CVD div bearish')
    if 'bn_absorb_bid' in df.columns and 'div_cvd_bull' in df.columns:
        mask = (df['bn_absorb_bid'] > 0) & df['div_cvd_bull']
        test(df, mask, 'buy', 'absorption bid + CVD div bullish')

    # Triple combo
    print(f'\n  --- TRIPLE COMBO ---')
    if all(c in df.columns for c in ['retest_high_count', 'div_cvd_bear', 'bn_absorb_ask']):
        mask = (df['retest_high_count'] >= 1) & df['div_cvd_bear'] & (df['bn_absorb_ask'] > 0)
        test(df, mask, 'sell', 'retest_high + CVD div + absorption ask')

    if all(c in df.columns for c in ['retest_low_count', 'div_cvd_bull', 'bn_absorb_bid']):
        mask = (df['retest_low_count'] >= 1) & df['div_cvd_bull'] & (df['bn_absorb_bid'] > 0)
        test(df, mask, 'buy', 'retest_low + CVD div + absorption bid')

    # VA extreme + divergence
    if 'va_position_pct' in df.columns:
        mask = (df['va_position_pct'] > 0.8) & df.get('div_cvd_bear', False)
        test(df, mask, 'sell', 'VA haute + CVD div bearish')
        mask = (df['va_position_pct'] < 0.2) & df.get('div_cvd_bull', False)
        test(df, mask, 'buy', 'VA basse + CVD div bullish')

    # Prev level + divergence
    print(f'\n  --- Previous Level + Divergence ---')
    if 'dist_prev_vpoc' in df.columns:
        mask = (df['dist_prev_vpoc'].abs() < 5) & df.get('div_cvd_bull', False)
        test(df, mask, 'buy', 'prev_vpoc < 5t + CVD div bullish')
        mask = (df['dist_prev_vpoc'].abs() < 5) & df.get('div_dbar_bull', False)
        test(df, mask, 'buy', 'prev_vpoc < 5t + delta_bar div bullish')

print('\nDone.')
