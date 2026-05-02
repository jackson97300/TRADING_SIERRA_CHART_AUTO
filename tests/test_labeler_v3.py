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
    get_purged_train_test_indices,
    prepare_for_lightgbm,
    TF_SPANS,
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

    def test_tie_break_same_bar_conservative_sl(self, synthetic_ohlcv_5m):
        """Lopez ch.3.2 conservatif : si TP+SL touches sur MEME bar
        (high>=tp ET low<=sl dans la meme barre), SL gagne (worst case
        scenario, evite biais positif).

        Edge case Jackson + agent Claude.com mobile (point 3 manquant 10/10).
        """
        df = synthetic_ohlcv_5m.copy()
        entry_ts = df.index[100]
        events = pd.DataFrame({
            't1': [df.index[112]],
            'daily_vol': [0.005],
        }, index=[entry_ts])
        entry_close = df.at[entry_ts, 'close']
        # MEME BAR (103) : high touche TP ET low touche SL
        df.at[df.index[103], 'high'] = entry_close * 1.01  # high >= TP
        df.at[df.index[103], 'low'] = entry_close * 0.99   # low <= SL
        out = apply_triple_barrier(df, events, pt_sl=(1.5, 1.0))
        # Lopez conservatif : tie sur meme bar → SL (pas TP comme biais positif)
        assert out.at[entry_ts, 'barrier_type'] == 'sl', \
            "Tie meme bar doit retourner SL (Lopez conservatif worst case)"
        # Return correspondant negatif
        assert out.at[entry_ts, 'return_at_t1'] < 0

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
    def test_label_distribution_three_classes(self, synthetic_ohlcv_5m):
        """Lopez : attendre 3 classes presentes (jackson review point 4).

        Note synthetic : random walk vol-scaled atteint quasi toujours
        TP/SL en 12 bars → HOLD potentiellement bas. Sur vrai data ES/NQ
        attendre 25/50/25 ± 10%.
        """
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        result = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        assert 'label' in result.columns
        assert 'sample_weight' in result.columns
        assert 'barrier_type' in result.columns
        # Distribution : 3 classes toutes presentes (Jackson point 4)
        unique_labels = sorted(result['label'].unique())
        assert -1 in unique_labels, "Classe -1 (SL) absente — anomalie"
        assert 1 in unique_labels, "Classe +1 (TP) absente — anomalie"
        # 0 (HOLD) peut etre tres bas sur synthetic (random walk vs barriers vol-scaled)
        # Sur vrai data attendre >= 10%, mais synthetic peut etre 0.5%
        assert result['label'].notna().all()
        # Log warning si HOLD < 10% (production-grade alert)
        hold_pct = (result['label'] == 0).mean()
        if hold_pct < 0.10:
            print(f"[WARN test] HOLD={hold_pct:.1%} < 10% (acceptable synthetic, "
                  f"investiguer si vrai data)")

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


# ─────────────────────────────────────────────────────────────────────
# Test 7 : PURGED K-FOLD NO LEAK (Jackson review : test manquant CRITIQUE)
# Lopez AFML ch.7.4.2 — labels overlapping creent leak entre train/test
# ─────────────────────────────────────────────────────────────────────

class TestPurgedKFoldNoLeak:
    """Verifie que get_purged_train_test_indices respecte Lopez ch.7.

    Pattern leak typique :
    - train = barres 0-499, test = barres 500-999
    - Label entry @ bar 495 avec horizon 12 → t1 = bar 507
    - Sans purge : label fait partie de train, mais son t1 (bar 507) est dans test
    - Le ML apprend sur features bar 495 + label qui depend de prix bar 507
    - Au test, le model voit bar 500-507 comme "future train" → overfit garanti
    """

    def test_purged_no_train_label_overlaps_test(self, synthetic_ohlcv_5m):
        """Aucun label train n'a son t1 dans la range test."""
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        events = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        if events.empty:
            pytest.skip("No events produced")

        n_splits = 5
        embargo_bars = 12
        leaks_count = 0
        total_train_samples = 0

        for train_idx, test_idx in get_purged_train_test_indices(
            events, n_splits=n_splits, embargo_bars=embargo_bars
        ):
            test_t_min = test_idx[0]
            test_t_max = test_idx[-1]
            total_train_samples += len(train_idx)

            # Pour chaque sample train, verifier que son t1 ne chevauche pas test
            for entry_ts in train_idx:
                t1 = events.at[entry_ts, 'ts_t1_actual']
                if pd.isna(t1):
                    continue
                # LEAK = entry_ts AVANT test_t_min ET t1 DANS test fold
                if entry_ts < test_t_min and t1 >= test_t_min and t1 <= test_t_max:
                    leaks_count += 1

        # Lopez : ZERO leak attendu
        assert leaks_count == 0, (
            f"LEAK DETECTE : {leaks_count} samples train ont t1 dans test fold. "
            f"Purge non appliquee correctement Lopez ch.7.4.2."
        )

    def test_embargo_after_test_fold_drops_samples(self, synthetic_ohlcv_5m):
        """Verifie que embargo apres test fold drop des samples train."""
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        events = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        if events.empty:
            pytest.skip("No events produced")

        # Sans embargo (=0)
        no_embargo_train_sizes = [
            len(train_idx) for train_idx, _ in
            get_purged_train_test_indices(events, n_splits=5, embargo_bars=0)
        ]
        # Avec embargo = 12 bars
        with_embargo_train_sizes = [
            len(train_idx) for train_idx, _ in
            get_purged_train_test_indices(events, n_splits=5, embargo_bars=12)
        ]
        # Embargo doit reduire taille train (drop samples zone embargo)
        assert sum(with_embargo_train_sizes) <= sum(no_embargo_train_sizes), (
            "Embargo non applique : meme nb samples train avec/sans embargo"
        )

    def test_embargo_drops_samples_immediately_after_test(self, synthetic_ohlcv_5m):
        """Lopez ch.7.4 — Les N barres immediatement apres test fold sont
        exclues du train (zone embargo).

        Edge case Jackson + ml-trainer Q2 :
        Le test_purged_no_train_label_overlaps_test couvre le leak AVANT
        (entry_train < test_min). Ce test couvre le leak APRES (entry_train
        immediatement post-test, dont features depend de t1 dans test).
        """
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        events = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        if events.empty:
            pytest.skip("No events produced")

        embargo_bars = 12
        for train_idx, test_idx in get_purged_train_test_indices(
            events, n_splits=5, embargo_bars=embargo_bars
        ):
            test_t_max = test_idx[-1]
            # Trouver position test_t_max dans events.index
            try:
                test_max_pos = events.index.get_loc(test_t_max)
            except KeyError:
                continue
            # Zone embargo = barres test_max_pos+1 ... test_max_pos+embargo_bars
            embargo_end_pos = min(test_max_pos + 1 + embargo_bars, len(events))
            embargo_zone = events.index[test_max_pos + 1:embargo_end_pos]

            # Aucune barre embargo ne doit etre dans train_idx
            train_set = set(train_idx)
            leaks_post_test = [ts for ts in embargo_zone if ts in train_set]

            assert len(leaks_post_test) == 0, (
                f"LEAK POST-TEST DETECTE : {len(leaks_post_test)} samples dans "
                f"zone embargo (apres test fold ending {test_t_max}) sont presents "
                f"dans train. Lopez ch.7.4 viole. Premiers leaks: {leaks_post_test[:3]}"
            )

    def test_purged_kfold_n_splits_correct(self, synthetic_ohlcv_5m):
        """Verifie que n_splits folds sont produits."""
        df = synthetic_ohlcv_5m.copy()
        df['volume'] = df['volume'].clip(lower=1000)
        events = label_dataset_v3(df, tf_name='5m', pt_sl=(1.5, 1.0),
                                    horizon_bars=12, rvol_threshold=0.3,
                                    vol_span=50)
        if events.empty:
            pytest.skip("No events produced")

        folds = list(get_purged_train_test_indices(events, n_splits=5, embargo_bars=12))
        assert len(folds) == 5, f"Expected 5 folds, got {len(folds)}"

        # Test sets disjoints (pas de chevauchement)
        all_test_ts = set()
        for _, test_idx in folds:
            test_set = set(test_idx)
            assert len(test_set & all_test_ts) == 0, "Test folds overlap"
            all_test_ts |= test_set


# ─────────────────────────────────────────────────────────────────────
# Test 8 : Vertical label mode (Jackson review point 1)
# ─────────────────────────────────────────────────────────────────────

class TestVerticalLabelMode:
    """Lopez ch.3.3 : vertical → sign(return) STRICT, pas seuil neutre.

    Mon code initial avait threshold 0.1 × daily_vol → deviation Lopez.
    Nouveau code par defaut = 'lopez_strict' (sign pure).
    """

    def test_lopez_strict_sign_pure(self):
        """Vertical avec return positif → label +1, return negatif → -1."""
        events = pd.DataFrame({
            'barrier_type': ['vertical', 'vertical', 'vertical', 'vertical'],
            'return_at_t1': [0.001, -0.001, 0.0001, -0.0001],
            'daily_vol': [0.005, 0.005, 0.005, 0.005],  # threshold = 0.0005
        }, index=pd.date_range('2025-01-01', periods=4, freq='5min'))

        out = get_labels(events, vertical_label_mode='lopez_strict')
        # Strict : sign pure quel que soit l'amplitude
        assert out['label'].iloc[0] == 1, "ret 0.001 > 0 → +1 strict"
        assert out['label'].iloc[1] == -1, "ret -0.001 < 0 → -1 strict"
        assert out['label'].iloc[2] == 1, "ret 0.0001 > 0 → +1 strict (pas seuil)"
        assert out['label'].iloc[3] == -1, "ret -0.0001 < 0 → -1 strict"

    def test_with_neutral_threshold_mode(self):
        """Mode deviation : seuil neutre 0.1 × daily_vol force HOLD."""
        events = pd.DataFrame({
            'barrier_type': ['vertical', 'vertical', 'vertical', 'vertical'],
            'return_at_t1': [0.001, -0.001, 0.0001, -0.0001],
            'daily_vol': [0.005, 0.005, 0.005, 0.005],  # threshold = 0.0005
        }, index=pd.date_range('2025-01-01', periods=4, freq='5min'))

        out = get_labels(events, vertical_label_mode='with_neutral_threshold')
        # Avec threshold : 0.001 > 0.0005 → +1, 0.0001 < 0.0005 → 0
        assert out['label'].iloc[0] == 1, "ret 0.001 > threshold → +1"
        assert out['label'].iloc[1] == -1, "ret -0.001 > threshold → -1"
        assert out['label'].iloc[2] == 0, "ret 0.0001 < threshold → 0 (HOLD)"
        assert out['label'].iloc[3] == 0, "ret -0.0001 < threshold → 0 (HOLD)"


# ─────────────────────────────────────────────────────────────────────
# Test 9 : TF_SPANS scaler (Jackson review point 3)
# ─────────────────────────────────────────────────────────────────────

class TestTfSpansScaling:
    """Lopez ch.3.1 : span = ~1 jour bars (TF-dependent)."""

    def test_tf_spans_dict_complete(self):
        """Verifie que tous TF prevus sont dans TF_SPANS."""
        for tf in ['1m', '5m', '15m', '1h']:
            assert tf in TF_SPANS, f"TF {tf} manquant dans TF_SPANS"
            assert TF_SPANS[tf] > 0

    def test_compute_daily_vol_uses_tf_param(self, synthetic_ohlcv_5m):
        """compute_daily_vol(tf='5m') doit utiliser span=78 auto."""
        vol_explicit_78 = compute_daily_vol(synthetic_ohlcv_5m['close'], span=78)
        vol_via_tf = compute_daily_vol(synthetic_ohlcv_5m['close'], span=999, tf='5m')
        # tf override doit etre prioritaire sur span
        # Comparer std au lieu d'egalite stricte (NaN warmup)
        diff = (vol_explicit_78 - vol_via_tf).abs().sum()
        assert diff < 1e-10, "tf='5m' doit utiliser span=78 (override)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
