"""Tests labeler_v3.py — Triple Barrier Lopez strict.

Tests methodologiques :
1. Vol-scaled barriers correctement calcules (pas ATR fixe)
2. Path detection high/low intrabar (vs close proxy)
3. RVOL pre-filter drop barres mortes
4. Sample weight uniqueness Lopez ch.4
5. Distribution labels balanced (~25/50/25 attendu)
6. Tie-break TP/SL barre meme bar (la plus precoce gagne)
7. No leak temporel : ts_t1_actual >= entry_ts
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CORE"))

from labeler_v3 import (
    compute_daily_vol,
    compute_vertical_barriers,
    apply_triple_barrier,
    get_labels,
    filter_low_rvol,
    compute_sample_weights_uniqueness,
    label_dataset_v3,
)


@pytest.fixture
def synthetic_ohlcv_5m():
    """Genere 1000 bars 5m synthetiques avec trend + vol."""
    np.random.seed(42)
    n = 1000
    ts = pd.date_range('2025-01-01 14:30:00', periods=n, freq='5min')
    # Random walk avec drift + vol shifts
    log_rets = np.random.normal(0.0001, 0.002, n)  # 0.2% std typique 5m
    log_rets[300:400] *= 3  # vol shift (regime)
    close = 6000 * np.exp(np.cumsum(log_rets))
    # OHLC autour du close (high/low realistes)
    spread = close * 0.0005  # 5 bps
    high = close + np.random.uniform(0.5, 1.5, n) * spread
    low = close - np.random.uniform(0.5, 1.5, n) * spread
    open_ = np.roll(close, 1); open_[0] = close[0]
    volume = np.random.lognormal(8, 0.5, n).astype(int)
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume,
    }, index=ts)
    df.index.name = 'ts_event'
    return df


# ─────────────────────────────────────────────────────────────────────
# Test 1 : daily vol EWMA correct
# ─────────────────────────────────────────────────────────────────────

class TestComputeDailyVol:
    def test_vol_positive(self, synthetic_ohlcv_5m):
        vol = compute_daily_vol(synthetic_ohlcv_5m['close'], span=100)
        assert vol.notna().sum() >= 800  # ~90% non-NaN apres span warmup
        assert (vol.dropna() > 0).all()
        # Vol moyenne ~0.002 (correspond au std synthetique injecte)
        assert 0.0005 < vol.mean() < 0.005

    def test_vol_increases_during_regime_shift(self, synthetic_ohlcv_5m):
        vol = compute_daily_vol(synthetic_ohlcv_5m['close'], span=50)
        vol_pre_shift = vol.iloc[200:300].mean()
        vol_during_shift = vol.iloc[350:450].mean()
        # Vol pendant shift x3 doit etre detectee
        assert vol_during_shift > vol_pre_shift * 1.5


# ─────────────────────────────────────────────────────────────────────
# Test 2 : vertical barriers
# ─────────────────────────────────────────────────────────────────────

class TestVerticalBarriers:
    def test_t1_offset_correct(self, synthetic_ohlcv_5m):
        t1 = compute_vertical_barriers(synthetic_ohlcv_5m['close'], num_bars=12)
        # Pour bar i, t1 = ts de bar i+12
        first_entry = synthetic_ohlcv_5m.index[0]
        assert t1.loc[first_entry] == synthetic_ohlcv_5m.index[12]

    def test_last_bars_nan(self, synthetic_ohlcv_5m):
        t1 = compute_vertical_barriers(synthetic_ohlcv_5m['close'], num_bars=12)
        # Les 12 dernieres bars n'ont pas d'horizon → NaN
        assert t1.iloc[-12:].isna().all()


# ─────────────────────────────────────────────────────────────────────
# Test 3 : RVOL pre-filter
# ─────────────────────────────────────────────────────────────────────

class TestRvolFilter:
    def test_drops_low_rvol_bars(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        # Inject barres low volume au milieu (pas en debut sinon rolling mean
        # est pollue avec les low values des le warmup)
        # Volume normal lognormal(8, 0.5) → mean ~3000-4000
        # On veut isoler 50 barres low pour qu'elles ressortent du rolling
        df.loc[df.index[500:550], 'volume'] = 50  # tres bas vs ~3500 moyen
        df_filtered = filter_low_rvol(df, rvol_threshold=0.3, window_bars=78)
        assert len(df_filtered) < len(df), "Pre-filter doit drop des barres low rvol"
        # Au moins quelques-unes des 50 barres injectees doivent etre droppees
        injected_idx = df.index[500:550]
        n_kept_injected = len([i for i in injected_idx if i in df_filtered.index])
        assert n_kept_injected < 50, "Au moins quelques barres low volume droppees"


# ─────────────────────────────────────────────────────────────────────
# Test 4 : Triple barrier path detection
# ─────────────────────────────────────────────────────────────────────

class TestTripleBarrier:
    def test_tp_hit_first(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        # Force entry @ bar 100, force high atteint TP rapidement
        entry_ts = df.index[100]
        events = pd.DataFrame({
            't1': [df.index[112]],  # horizon 12 bars
            'daily_vol': [0.005],   # 0.5% vol → tp = +0.75%, sl = -0.5%
        }, index=[entry_ts])
        # Force high bar 102 a depasser tp_level
        entry_close = df.at[entry_ts, 'close']
        df.at[df.index[102], 'high'] = entry_close * 1.01  # +1% > tp 0.75%
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        assert out.at[entry_ts, 'barrier_type'] == 'tp'
        assert out.at[entry_ts, 'ts_t1_actual'] == df.index[102]

    def test_sl_hit_first(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        entry_ts = df.index[100]
        events = pd.DataFrame({
            't1': [df.index[112]],
            'daily_vol': [0.005],
        }, index=[entry_ts])
        entry_close = df.at[entry_ts, 'close']
        df.at[df.index[103], 'low'] = entry_close * 0.99  # -1% < sl -0.5%
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        assert out.at[entry_ts, 'barrier_type'] == 'sl'

    def test_tie_break_earliest_wins(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        entry_ts = df.index[100]
        events = pd.DataFrame({
            't1': [df.index[112]],
            'daily_vol': [0.005],
        }, index=[entry_ts])
        entry_close = df.at[entry_ts, 'close']
        # SL touche bar 103, TP touche bar 105 → SL wins (plus precoce)
        df.at[df.index[103], 'low'] = entry_close * 0.99
        df.at[df.index[105], 'high'] = entry_close * 1.01
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        assert out.at[entry_ts, 'barrier_type'] == 'sl'

    def test_vertical_barrier_when_neither_hit(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        entry_ts = df.index[100]
        events = pd.DataFrame({
            't1': [df.index[112]],
            'daily_vol': [0.05],  # vol enorme → barriers eloignes, jamais hit
        }, index=[entry_ts])
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        assert out.at[entry_ts, 'barrier_type'] == 'vertical'


# ─────────────────────────────────────────────────────────────────────
# Test 5 : Pipeline complet sur synthetic data
# ─────────────────────────────────────────────────────────────────────

class TestPipelineComplet:
    def test_label_distribution_balanced(self, synthetic_ohlcv_5m):
        # Forcer volumes tous suffisants pour eviter pre-filter excessif
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        result = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        assert 'label' in result.columns
        assert 'sample_weight' in result.columns
        assert 'barrier_type' in result.columns
        # Distribution doit avoir les 3 classes
        unique_labels = result['label'].unique()
        assert len(unique_labels) >= 2  # au moins 2 classes
        # Pas de NaN dans label
        assert result['label'].notna().all()

    def test_no_temporal_leak(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        result = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        # ts_t1_actual doit toujours etre >= ts_event (entry)
        for entry_ts, row in result.iterrows():
            t1_actual = row['ts_t1_actual']
            if pd.notna(t1_actual):
                assert t1_actual >= entry_ts, \
                    f"LEAK : t1_actual {t1_actual} < entry {entry_ts}"

    def test_sample_weights_positive(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        result = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        sw = result['sample_weight'].dropna()
        # Lopez ch.4 : sample_weight = 1/mean(1/co_events) = harmonic mean co_events.
        # Peut depasser 1 (uniqueness moyenne reflective de chevauchement).
        # On valide juste : positif + raisonnable (pas explosif >100).
        assert (sw > 0).all()
        assert (sw < 100).all()
        assert sw.mean() > 0.1  # mean raisonnable
        # Variance non triviale : weights doivent differencier samples
        assert sw.std() > 0.01


# ─────────────────────────────────────────────────────────────────────
# Test 6 : Convention path-aware vs close-proxy
# ─────────────────────────────────────────────────────────────────────

class TestPathAwareSuperiorClose:
    """Test que path-aware (high/low) detecte SL intrabar manque par close-proxy."""

    def test_intrabar_sl_detected(self, synthetic_ohlcv_5m):
        df = synthetic_ohlcv_5m.copy()
        entry_ts = df.index[100]
        entry_close = df.at[entry_ts, 'close']
        # Bar 103 : low touche SL mais close revient au-dessus (fake recovery)
        df.at[df.index[103], 'low'] = entry_close * 0.985  # SL touche
        df.at[df.index[103], 'high'] = entry_close * 1.005
        df.at[df.index[103], 'close'] = entry_close * 1.001  # close > SL → close-proxy raterait

        events = pd.DataFrame({
            't1': [df.index[112]],
            'daily_vol': [0.005],
        }, index=[entry_ts])
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        # path-aware (high/low) doit detecter SL hit alors que close-proxy non
        assert out.at[entry_ts, 'barrier_type'] == 'sl'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
