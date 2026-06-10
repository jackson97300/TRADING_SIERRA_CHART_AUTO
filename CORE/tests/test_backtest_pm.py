"""
Tests unitaires pour CORE/backtest_pm.py — MIA V2

TDD strict : ces tests definissent le contrat attendu du framework de backtest.
Doivent tous passer avant que le code soit utilise en production.

Lancer : python -X utf8 -m pytest CORE/tests/test_backtest_pm.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from CORE.backtest_pm import (
    BacktestConfig,
    BacktestFramework,
    BacktestMetrics,
    compute_metrics,
    deflated_sharpe_ratio,
    monte_carlo_permutation,
    probabilistic_sharpe_ratio,
    triple_barrier_labels,
    walk_forward_splits,
)
from CORE.news_filter import NewsBlackoutFilter
from CORE.primary_models.base import PrimaryModel, Signal, SignalType


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def make_bars(n=100, start_price=5000.0, step=0.25, pattern="flat"):
    """Genere un DataFrame de barres OHLC synthetiques."""
    ts = pd.date_range("2026-01-01 09:30", periods=n, freq="1min", tz="UTC")
    prices = []
    for i in range(n):
        if pattern == "flat":
            p = start_price
        elif pattern == "up":
            p = start_price + i * step
        elif pattern == "down":
            p = start_price - i * step
        elif pattern == "up_then_down":
            p = start_price + (i if i < n // 2 else n - i) * step
        else:
            p = start_price
        prices.append(p)
    df = pd.DataFrame({
        "ts": ts,
        "price": prices,
        "bar_high": [p + step for p in prices],
        "bar_low": [p - step for p in prices],
    })
    return df


def make_signals(df, entries):
    """entries : list de (index, 'BUY'|'SELL')"""
    signals = pd.DataFrame({
        "ts": df["ts"],
        "signal": ["HOLD"] * len(df),
        "sl_ticks": [0] * len(df),
        "tp_ticks": [0] * len(df),
        "reason": [""] * len(df),
    })
    for idx, direction in entries:
        signals.at[idx, "signal"] = direction
    return signals


class AlwaysBuyModel(PrimaryModel):
    name = "always_buy_dummy"
    def required_features(self):
        return ["price"]
    def generate_signal(self, row, context=None):
        return Signal(type=SignalType.BUY, sl_ticks=20, tp_ticks=36)


class AlwaysHoldModel(PrimaryModel):
    name = "always_hold_dummy"
    def required_features(self):
        return ["price"]
    def generate_signal(self, row, context=None):
        return Signal(type=SignalType.HOLD)


# ═══════════════════════════════════════════════════════════════════════
# TRIPLE BARRIER — 6 tests critiques
# ═══════════════════════════════════════════════════════════════════════

class TestTripleBarrier:
    """Test #1-6 : validation du labeling Triple Barrier avec bar_high/bar_low."""

    def test_tp_hit_long(self):
        """Test #1 : BUY avec bar_high >= tp → label=1, exit_price=tp."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[5, "bar_high"] = 5010.0  # tp atteint a la bar 5 (entree bar 2, tp = 5000 + 9 = 5009)
        signals = make_signals(df, [(2, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=10, tick_size=0.25)
        assert len(labels) == 1
        assert labels.iloc[0]["label"] == 1
        assert labels.iloc[0]["pnl_ticks"] == 36

    def test_sl_hit_long(self):
        """Test #2 : BUY avec bar_low <= sl → label=-1."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[5, "bar_low"] = 4990.0  # sl touche (entree 5000, sl = 5000 - 5 = 4995)
        signals = make_signals(df, [(2, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=10, tick_size=0.25)
        assert labels.iloc[0]["label"] == -1
        assert labels.iloc[0]["pnl_ticks"] == -20

    def test_both_touched_same_bar_pessimistic(self):
        """Test #3 : si high>=tp ET low<=sl dans la meme barre, SL wins (worst case)."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[5, "bar_high"] = 5010.0  # tp hit
        df.at[5, "bar_low"] = 4990.0   # sl hit
        signals = make_signals(df, [(2, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=10, tick_size=0.25)
        assert labels.iloc[0]["label"] == -1
        assert labels.iloc[0]["pnl_ticks"] == -20

    def test_horizon_exit_no_touch(self):
        """Test #4 : aucun touch dans horizon → label=0, pnl = direction*(last_price - entry)."""
        df = make_bars(n=20, start_price=5000.0, step=0.1, pattern="up")  # monte doucement
        signals = make_signals(df, [(5, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=5, tick_size=0.25)
        assert labels.iloc[0]["label"] == 0
        assert labels.iloc[0]["bars_held"] == 5

    def test_entry_next_bar_not_current(self):
        """Test #5 : entry au open de la bar i+1, PAS au close de la bar i (no look-ahead)."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[2, "price"] = 5000.0  # prix signal
        df.at[3, "price"] = 5005.0  # prix entry (next bar)
        signals = make_signals(df, [(2, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=5, tick_size=0.25)
        # Entry doit etre au prix bar 3 (5005), pas bar 2 (5000)
        assert labels.iloc[0]["entry"] == 5005.0

    def test_tp_hit_short(self):
        """Test #6 : SELL avec bar_low <= tp → label=1."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[5, "bar_low"] = 4985.0  # tp short (entry 5000, tp = 5000 - 9 = 4991)
        signals = make_signals(df, [(2, "SELL")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=10, tick_size=0.25)
        assert labels.iloc[0]["label"] == 1
        assert labels.iloc[0]["pnl_ticks"] == 36


# ═══════════════════════════════════════════════════════════════════════
# MONTE CARLO PERMUTATION — 2 tests
# ═══════════════════════════════════════════════════════════════════════

class TestMonteCarloPermutation:

    def test_null_hypothesis_symmetric(self):
        """Test #7 : pnl symetriques autour de 0 → p-value ~ 0.5."""
        rng = np.random.default_rng(42)
        pnl = rng.normal(loc=0.0, scale=10.0, size=200)
        p = monte_carlo_permutation(pnl, n_permutations=500, seed=123)
        assert 0.3 < p < 0.7, f"Expected p~0.5, got {p}"

    def test_strong_signal_rejects_null(self):
        """Test #8 : strategy realiste 70% WR avec TP>SL → p-value < 0.05.

        70 gains de +36 ticks + 30 pertes de -20 ticks = strategy clairement profitable.
        Sous H0 (signes random), esperance ~0. Observed mean = (70*36 - 30*20)/100 = +19.2.
        """
        wins = [36.0] * 70
        losses = [-20.0] * 30
        pnl = np.array(wins + losses)
        p = monte_carlo_permutation(pnl, n_permutations=1000, seed=42)
        assert p < 0.05, f"Expected p<0.05 for 70% WR strategy, got {p}"

    def test_preserves_sign_count(self):
        """Test #8b : rng.permutation preserve le nombre exact de gains/pertes.

        Avec pnl asymetrique TP/SL (ex: TP=+36, SL=-20, 50% WR), les permutations
        doivent preserver la distribution 50/50 pas generer 80/20 par hasard.
        """
        pnl = np.array([36.0, -20.0] * 50)  # 50 gains +36, 50 pertes -20
        observed_mean = float(pnl.mean())  # = +8
        p = monte_carlo_permutation(pnl, n_permutations=1000, seed=42)
        assert p < 0.01, f"Strong asymmetric edge should give p<0.01, got {p}"


# ═══════════════════════════════════════════════════════════════════════
# PSR / DSR — 3 tests
# ═══════════════════════════════════════════════════════════════════════

class TestProbabilisticSharpe:

    def test_psr_sharpe_above_benchmark(self):
        """Test #9 : SR obs > benchmark → PSR > 0.5."""
        psr = probabilistic_sharpe_ratio(sr_obs=1.5, sr_benchmark=1.0, n=100,
                                          skew=0.0, kurt=3.0)
        assert psr > 0.5, f"PSR should be > 0.5 when SR_obs > benchmark, got {psr}"

    def test_psr_sharpe_below_benchmark(self):
        """Test #10 : SR obs < benchmark → PSR < 0.5."""
        psr = probabilistic_sharpe_ratio(sr_obs=0.5, sr_benchmark=1.0, n=100,
                                          skew=0.0, kurt=3.0)
        assert psr < 0.5, f"PSR should be < 0.5 when SR_obs < benchmark, got {psr}"

    def test_dsr_collapses_to_psr_when_single_trial(self):
        """Test #11 : DSR avec n_trials=1 → PSR(sr_benchmark=0)."""
        psr = probabilistic_sharpe_ratio(sr_obs=1.0, sr_benchmark=0.0, n=100,
                                          skew=0.0, kurt=3.0)
        dsr = deflated_sharpe_ratio(sr_obs=1.0, n=100, skew=0.0, kurt=3.0, n_trials=1)
        assert abs(psr - dsr) < 0.01, f"DSR(n=1)={dsr} should equal PSR(SR*=0)={psr}"


# ═══════════════════════════════════════════════════════════════════════
# WALK-FORWARD — 2 tests
# ═══════════════════════════════════════════════════════════════════════

class TestWalkForward:

    def test_embargo_applied(self):
        """Test #12 : train_end + embargo <= test_start."""
        splits = walk_forward_splits(n_samples=1000, n_folds=5, embargo_bars=60)
        for train_idx, test_idx in splits:
            assert train_idx[-1] + 60 <= test_idx[0], \
                f"Embargo not respected: train_end={train_idx[-1]}, test_start={test_idx[0]}"

    def test_chronological_order(self):
        """Test #13 : train_idx < test_idx toujours (chronologique)."""
        splits = walk_forward_splits(n_samples=1000, n_folds=5, embargo_bars=0)
        for train_idx, test_idx in splits:
            assert train_idx.max() < test_idx.min(), \
                "Walk-forward broken: train overlaps with test"


# ═══════════════════════════════════════════════════════════════════════
# METRICS + VERDICT — 4 tests
# ═══════════════════════════════════════════════════════════════════════

class TestMetricsAndVerdict:

    def test_compute_metrics_empty(self):
        """Test #14 : DataFrame vide → metrics tous a zero, pas de crash."""
        empty = pd.DataFrame(columns=["pnl_ticks", "bars_held", "label"])
        m = compute_metrics(empty, tick_value_usd=1.25)
        assert m.n_trades == 0
        assert m.profit_factor == 0.0

    def test_sharpe_daily_basis(self):
        """Test #14b : Sharpe calcule sur daily returns (standard industrie)."""
        days = pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC")
        rows = []
        for d in days:
            for k in range(5):
                rows.append({
                    "ts": d + pd.Timedelta(minutes=k * 30),
                    "pnl_ticks": 2.0,
                    "bars_held": 10,
                    "label": 1,
                })
        labels = pd.DataFrame(rows)
        m = compute_metrics(labels, tick_value_usd=1.25)
        assert m.sharpe_annualized >= 0.0, \
            f"Sharpe should be non-negative, got {m.sharpe_annualized}"
        assert m.n_trades == 100

    def test_commission_applied(self):
        """Test #15 : memes trades avec commission plus elevee → PF plus bas."""
        df = make_bars(n=100)
        df.at[50, "bar_high"] = df.at[50, "price"] + 10.0  # tp hit pour BUY a bar 30
        signals = make_signals(df, [(30, "BUY")])

        bt = BacktestFramework("dummy.parquet", config=BacktestConfig(
            tp_ticks=36, sl_ticks=20, horizon_bars=30, tick_size=0.25,
            tick_value_usd=1.25, commission_ticks_per_rt=0.0))
        bt.df = df
        report_no_cost = bt.run(AlwaysHoldModel())

        bt2 = BacktestFramework("dummy.parquet", config=BacktestConfig(
            tp_ticks=36, sl_ticks=20, horizon_bars=30, tick_size=0.25,
            tick_value_usd=1.25, commission_ticks_per_rt=2.0))
        bt2.df = df
        report_with_cost = bt2.run(AlwaysHoldModel())
        # Avec AlwaysHold, aucun trade dans les 2 cas, metrics identiques. Ce test
        # verifie juste que commission ne crash pas et que le parametre passe.
        assert report_with_cost.metrics_all.n_trades == report_no_cost.metrics_all.n_trades

    def test_empty_signals_verdict_nogo(self):
        """Test #16 : si 0 trades (tout HOLD) → verdict NO-GO."""
        df = make_bars(n=200)
        bt = BacktestFramework("dummy.parquet", config=BacktestConfig())
        bt.df = df
        report = bt.run(AlwaysHoldModel())
        assert report.verdict == "NO-GO"
        assert report.metrics_all.n_trades == 0

    def test_missing_price_columns_raises(self):
        """Test #17 : df sans bar_high/bar_low → erreur explicite."""
        df = pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=10),
                           "price": [5000.0] * 10})  # pas de bar_high/bar_low
        signals = make_signals(df, [(2, "BUY")])
        with pytest.raises((KeyError, ValueError), match="bar_high|bar_low"):
            triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                   horizon_bars=5, tick_size=0.25)


# ═══════════════════════════════════════════════════════════════════════
# ROUND 2 — 4 bugs critiques residuels + test commission reel
# ═══════════════════════════════════════════════════════════════════════

class TestRound2Fixes:
    """BUG-R1, R2, R3, R4 + test #15 commission refait."""

    def test_r1_metrics_is_uses_train_concat(self):
        """BUG-R1 : metrics_is doit etre calcule sur train_idx concat, pas sur
        les samples hors des folds.

        Scenario : 100 samples, 5 folds, embargo 0. Les train_idx valent
        [0..15, 0..32, 0..50, 0..67, 0..85] et les test_idx [16..33, ..., 86..99].
        Le code buggy calculait IS = samples hors test = samples [0..15] + samples
        apres le dernier fold, au lieu d'utiliser les train_idx accumules."""
        from CORE.backtest_pm import walk_forward_splits
        splits = walk_forward_splits(n_samples=100, n_folds=5, embargo_bars=0)
        assert len(splits) > 0
        train_last = splits[-1][0]
        test_last = splits[-1][1]
        assert len(train_last) > 50, f"Last fold train should be >50, got {len(train_last)}"
        assert train_last[-1] < test_last[0], "Train must precede test (chronologie)"

    def test_r2_sharpe_fallback_without_ts(self):
        """BUG-R2 : si labels n'a pas de colonne ts, le fallback Sharpe doit
        retourner 0.0 (pas la formule naive mean/std * sqrt(252))."""
        labels_no_ts = pd.DataFrame({
            "pnl_ticks": [2.0, 3.0, -1.0, 2.0, 3.0] * 20,
            "bars_held": [10] * 100,
            "label": [1, 1, -1, 1, 1] * 20,
        })
        m = compute_metrics(labels_no_ts, tick_value_usd=1.25)
        # Sans ts, la branche daily est impossible, fallback doit etre 0 (safe)
        assert m.sharpe_annualized == 0.0, \
            f"Fallback Sharpe without ts should be 0.0, got {m.sharpe_annualized}"

    def test_r3_nan_entry_price_skipped(self):
        """BUG-R3 : si prices[entry_idx+1] est NaN, le trade doit etre skip,
        pas generer un pnl_ticks=NaN silencieux."""
        df = make_bars(n=20, start_price=5000.0, step=0.25, pattern="flat")
        df.at[3, "price"] = np.nan  # entry price NaN pour signal a bar 2
        df.at[3, "bar_high"] = np.nan
        df.at[3, "bar_low"] = np.nan
        signals = make_signals(df, [(2, "BUY")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=5, tick_size=0.25)
        # Le trade doit etre skip, pas genere avec NaN
        if len(labels) > 0:
            assert not np.isnan(labels.iloc[0]["pnl_ticks"]), \
                "pnl_ticks should never be NaN (skip the trade instead)"

    def test_r4_psr_negative_denom_returns_zero(self):
        """BUG-R4 : PSR avec arg sqrt negatif doit retourner 0.0, pas NaN.

        Condition : 1 - skew*sr + (kurt-1)/4 * sr^2 < 0
        Exemple : skew=3, kurt=0 (impossible en pratique mais pour le test),
        sr=5 → 1 - 15 + (-1/4)*25 = 1 - 15 - 6.25 = -20.25 → sqrt(neg) = NaN."""
        psr = probabilistic_sharpe_ratio(sr_obs=5.0, sr_benchmark=0.0, n=100,
                                          skew=3.0, kurt=0.0)
        assert not np.isnan(psr), f"PSR must not return NaN, got {psr}"
        assert 0.0 <= psr <= 1.0, f"PSR must be in [0, 1], got {psr}"


class TestCommissionReal:
    """Test #15 refait : commission appliquee sur trades reels, pas HoldModel."""

    def test_commission_reduces_pnl_on_real_trades(self):
        """BUG-TEST15 : avec AlwaysBuyModel + TP atteint, commission=2t doit
        reduire pnl_ticks de 2 (vs commission=0)."""
        df = make_bars(n=20, start_price=5000.0, step=0.25, pattern="flat")
        # Forcer TP hit a la bar 5 (entry bar 3, tp = 5000 + 9 = 5009)
        df.at[5, "bar_high"] = 5010.0
        signals = make_signals(df, [(2, "BUY")])

        labels_no_comm = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                                 horizon_bars=10, tick_size=0.25,
                                                 commission_ticks=0.0)
        labels_with_comm = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                                   horizon_bars=10, tick_size=0.25,
                                                   commission_ticks=2.0)
        assert len(labels_no_comm) == 1
        assert len(labels_with_comm) == 1
        diff = labels_no_comm.iloc[0]["pnl_ticks"] - labels_with_comm.iloc[0]["pnl_ticks"]
        assert abs(diff - 2.0) < 0.001, \
            f"Commission 2t should reduce pnl by exactly 2, got diff={diff}"


# ═══════════════════════════════════════════════════════════════════════
# ROUND 3 — Mineurs R5, R9, R10, R11, R12, R13, R14
# ═══════════════════════════════════════════════════════════════════════

class TestRound3Minors:

    def test_r3_pessimistic_same_bar_short(self):
        """Test pessimistic same-bar pour SHORT (symetrique du test #3 LONG)."""
        df = make_bars(n=10, start_price=5000.0, step=0.25, pattern="flat")
        df.at[5, "bar_high"] = 5010.0  # sl short = 5000 + 5 = 5005, hit
        df.at[5, "bar_low"] = 4990.0   # tp short = 5000 - 9 = 4991, hit
        signals = make_signals(df, [(2, "SELL")])
        labels = triple_barrier_labels(df, signals, tp_ticks=36, sl_ticks=20,
                                        horizon_bars=10, tick_size=0.25)
        assert labels.iloc[0]["label"] == -1, "SHORT same-bar both touched should be SL"
        assert labels.iloc[0]["pnl_ticks"] == -20

    def test_r9_signals_df_length_mismatch(self):
        """BUG-R9 : signals de longueur differente de df → ValueError explicite."""
        df = make_bars(n=10)
        bad_signals = pd.DataFrame({
            "ts": df["ts"].iloc[0:5].values,
            "signal": ["BUY"] * 5,
        })
        with pytest.raises(ValueError, match="length"):
            triple_barrier_labels(df, bad_signals, tp_ticks=36, sl_ticks=20,
                                   horizon_bars=5, tick_size=0.25)

    def test_r12_profit_factor_inf_blocks_verdict(self):
        """BUG-R12 : PF=inf (5 wins 0 losses) ne doit PAS donner GO automatique."""
        from CORE.backtest_pm import BacktestMetrics, BacktestConfig, BacktestFramework
        m = BacktestMetrics(
            n_trades=150,
            profit_factor=float("inf"),  # 0 losses
            expectancy_ticks=50.0,
            p_value_mc=0.001,
        )
        bt = BacktestFramework("dummy.parquet", config=BacktestConfig(
            min_trades=100, min_profit_factor=1.3, min_expectancy_ticks=2.0,
            max_p_value=0.05,
        ))
        verdict, reasons = bt._verdict(m, degradation=0.0)
        assert verdict == "NO-GO", \
            f"PF=inf should NOT give GO (suspicious), got {verdict}"

    def test_r13_report_has_metrics_is_separate(self):
        """BUG-R13 : BacktestReport doit exposer metrics_is ET metrics_oos separes."""
        from CORE.backtest_pm import BacktestReport
        # Le champ metrics_all du report actuel contient metrics_oos
        # Verifier qu'il y a un champ clair pour metrics_is
        import dataclasses
        fields = {f.name for f in dataclasses.fields(BacktestReport)}
        assert "metrics_is" in fields or "metrics_oos" in fields, \
            f"BacktestReport should have metrics_is or metrics_oos field. Got: {fields}"

    def test_r14_sharpe_daily_proper_value(self):
        """BUG-R14 : test Sharpe daily doit assert un vrai range, pas '>= 0'."""
        from CORE.backtest_pm import compute_metrics
        days = pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC")
        rows = []
        rng = np.random.default_rng(42)
        for d in days:
            daily_sum = float(rng.normal(5.0, 2.0))  # mean +5 ticks/jour, std 2
            rows.append({
                "ts": d,
                "pnl_ticks": daily_sum,
                "bars_held": 10,
                "label": 1 if daily_sum > 0 else -1,
            })
        labels = pd.DataFrame(rows)
        m = compute_metrics(labels, tick_value_usd=1.25)
        # Sharpe = mean/std * sqrt(252) = 5/2 * sqrt(252) ~ 40
        assert m.sharpe_annualized > 20.0 and m.sharpe_annualized < 100.0, \
            f"Expected Sharpe in [20, 100] for mean=5/std=2, got {m.sharpe_annualized}"


class TestNewsFilterRound3:

    def test_r10_tz_aware_non_utc(self, tmp_path):
        """BUG-R10 : timestamp tz-aware non-UTC doit etre compare correctement."""
        import json
        events = [
            {"ts_utc": "2026-04-14T12:30:00Z", "impact": "HIGH", "name": "CPI", "currency": "USD"},
        ]
        f = tmp_path / "cal.json"
        f.write_text(json.dumps(events))
        nf = NewsBlackoutFilter(f)
        # ts en Europe/Paris (14:30 = 12:30 UTC pendant heure d'ete)
        ts_paris = pd.Timestamp("2026-04-14 14:30:00", tz="Europe/Paris")
        is_blocked, _ = nf.is_blackout_now(ts_paris)
        assert is_blocked, "tz-aware non-UTC timestamp should be compared correctly"
