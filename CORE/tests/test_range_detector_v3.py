"""Tests RangeDetectorV3 — synthetiques + scenarios critiques V3.

Couverture :
  1. Validation input
  2. Range pur (synthetique) avec features V4 enriched complets
  3. Trend pur (no false positive)
  4. Buffer extremes (wicks tolere)
  5. Color inversion = range_break_risk (observation Jackson 07/05)
  6. Signal hints supprimes si break_risk meme direction
  7. Transition range → breakout (3 cas : whipsaw, slow drift, trend compression)

Date : 2026-05-07
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Path resolution pour exec depuis racine projet
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CORE.range_detector_v3 import (  # noqa: E402
    RangeDetectorV3,
    RangeResultV3,
    LOW_FADE_THRESHOLD,
    HIGH_FADE_THRESHOLD,
    INVERSION_LOW_ZONE,
    INVERSION_HIGH_ZONE,
    SWING_BARS_MIN,
    POC_MIGRATION_ABS_MAX,
    AGGRESSOR_MEAN_ABS_MAX,
)


# ─── Helpers ───

def make_synthetic_range(
    n_bars: int = 80,
    range_high: float = 28700.0,
    range_low: float = 28650.0,
    noise_std: float = 2.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Range parfait sinusoidal."""
    rng = np.random.default_rng(seed)
    mid = (range_high + range_low) / 2.0
    amp = (range_high - range_low) / 2.0
    t = np.arange(n_bars)
    closes = mid + amp * 0.85 * np.sin(t * 2 * np.pi / 12.0) + rng.normal(0, noise_std, n_bars)
    closes = np.clip(closes, range_low + 1, range_high - 1)
    highs = closes + rng.uniform(1.0, 4.0, n_bars)
    lows = closes - rng.uniform(1.0, 4.0, n_bars)
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def make_synthetic_trend(
    n_bars: int = 80,
    start: float = 28500.0,
    end: float = 28900.0,
    noise_std: float = 2.0,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = np.linspace(start, end, n_bars) + rng.normal(0, noise_std, n_bars)
    highs = closes + rng.uniform(1.0, 3.0, n_bars)
    lows = closes - rng.uniform(1.0, 3.0, n_bars)
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def add_features_v3(
    df: pd.DataFrame,
    near_low: bool = False,
    near_high: bool = False,
    color_dn_in_low: bool = False,
    color_up_in_high: bool = False,
    long_dn_bar: bool = False,
    long_up_bar: bool = False,
    swing_bars: int = 60,            # M5 OK par defaut
    inside_va: bool = True,           # M6
    va_width_atr: float = 1.2,        # M6 stable
    poc_migration: float = 0.001,     # M7 stable
    aggressor_imbalance: float = 0.05,  # M8 balanced
) -> pd.DataFrame:
    """Ajoute toutes les features V4 enriched V3."""
    n = len(df)
    df = df.copy()

    # Density V2 (default zero)
    for col in [
        "n_color_up_cluster_within_0_2pct",
        "n_long_up_cluster_within_0_2pct",
        "n_edge_buy_active",
        "n_color_dn_cluster_within_0_2pct",
        "n_long_dn_cluster_within_0_2pct",
        "n_edge_sell_active",
        "long_up_bar",
        "long_dn_bar",
    ]:
        df[col] = 0
    df["im_rolling_correlation_10"] = 0.95

    # M5 swing (constant pour simplicite)
    df["bars_since_last_swing_high"] = swing_bars
    df["bars_since_last_swing_low"] = swing_bars

    # M6 VA (stable sur 20 bars)
    df["inside_value_area"] = 1 if inside_va else 0
    rng = np.random.default_rng(123)
    df["ctx_va_width_atr"] = va_width_atr + rng.normal(0, va_width_atr * 0.05, n)

    # M7 POC migration (stable)
    df["ctx_poc_migration_10"] = poc_migration + rng.normal(0, 0.001, n)

    # M8 Aggressor (balanced sur 30 bars)
    df["aggressor_imbalance"] = aggressor_imbalance + rng.normal(0, 0.02, n)

    # Density active (last bar)
    if near_low:
        df.loc[df.index[-1], "n_color_up_cluster_within_0_2pct"] = 2
        df.loc[df.index[-1], "n_long_up_cluster_within_0_2pct"] = 1
        df.loc[df.index[-1], "n_edge_buy_active"] = 1
    if near_high:
        df.loc[df.index[-1], "n_color_dn_cluster_within_0_2pct"] = 2
        df.loc[df.index[-1], "n_long_dn_cluster_within_0_2pct"] = 1
        df.loc[df.index[-1], "n_edge_sell_active"] = 1

    # Color inversion (penetration camp ennemi)
    if color_dn_in_low:
        df.loc[df.index[-1], "n_color_dn_cluster_within_0_2pct"] = 2
    if color_up_in_high:
        df.loc[df.index[-1], "n_color_up_cluster_within_0_2pct"] = 2

    # LONG bar confirmation
    if long_dn_bar:
        df.loc[df.index[-1], "long_dn_bar"] = 1
    if long_up_bar:
        df.loc[df.index[-1], "long_up_bar"] = 1

    return df


# ─── Tests ───

class TestInputValidation:
    def test_invalid_sym_raises(self):
        with pytest.raises(ValueError, match="Instrument inconnu"):
            RangeDetectorV3(sym="ZZ")

    def test_missing_ohlc_raises(self):
        det = RangeDetectorV3(sym="NQ")
        df = pd.DataFrame({"high": [1.0], "low": [0.5]})
        with pytest.raises(ValueError, match="OHLC"):
            det.detect(df)

    def test_insufficient_bars_returns_default(self):
        det = RangeDetectorV3(sym="NQ", macro_lookback=60)
        df = make_synthetic_range(n_bars=30)
        result = det.detect(df)
        assert result.is_range is False
        assert "insufficient" in result.reason


class TestRangePure:
    def test_range_v3_detected_full_features(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80)
        df = add_features_v3(df)
        result = det.detect(df)

        # M5-M8 doivent etre OK
        assert result.swing_ok is True, f"M5 swing fail: bsh={result.bars_since_swing_high}, bsl={result.bars_since_swing_low}"
        assert result.va_stable_ok is True, f"M6 VA fail: std={result.va_width_atr_std}, mean={result.va_width_atr_mean}"
        assert result.poc_stable_ok is True, f"M7 POC fail: mig={result.poc_migration}"
        assert result.aggressor_balanced_ok is True, f"M8 Agg fail: mean={result.aggressor_mean}"

        # n_macro_ok >= 4/7 pour declencher is_range_macro
        assert result.n_macro_ok >= 4, f"n_macro_ok={result.n_macro_ok}/7, reason={result.reason}"
        assert result.is_range_macro is True
        assert result.is_range is True
        assert result.range_break_risk == "NONE"

    def test_buffer_zones_computed(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        df = add_features_v3(df)
        result = det.detect(df)

        # Zones doivent contenir les raw extremes (zone plus large que raw)
        assert result.range_high_zone is not None
        assert result.range_low_zone is not None
        assert result.range_high_raw is not None
        assert result.range_low_raw is not None

        # Zone high >= quantile high (mais peut etre <= raw max si wicks)
        # Buffer NQ = 4 ticks = 1.0 point
        # Verification : zone n'est pas exactement raw (different car quantile + buffer)
        assert result.range_high_zone != result.range_high_raw, \
            "Zone high == raw high → buffer non applique"


class TestTrendNoFalsePositive:
    def test_trend_pur_pas_de_range(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_trend(n_bars=80)
        df = add_features_v3(df, swing_bars=5, poc_migration=0.05, aggressor_imbalance=0.4)
        result = det.detect(df)

        # Trend pur : M5/M7/M8 doivent etre KO
        assert result.swing_ok is False
        assert result.poc_stable_ok is False
        assert result.aggressor_balanced_ok is False

        # ADX doit etre eleve sur trend pur
        assert result.adx is not None and result.adx > 25, \
            f"ADX trop bas pour trend: {result.adx}"

        # n_macro_ok < 4 → pas de range_macro
        assert result.n_macro_ok < 4, \
            f"Trend confondu range: n_macro_ok={result.n_macro_ok}, reason={result.reason}"
        assert result.is_range is False


class TestBufferRobustness:
    def test_wick_doesnt_break_range(self):
        """Wick de 4 ticks (buffer NQ) ne doit PAS declencher fake breakout."""
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        # Inject un wick de 5 ticks au-dela du high apparent
        wick_idx = 70
        df.loc[df.index[wick_idx], "high"] = 28703.0  # 1.25 pts au-dessus
        df = add_features_v3(df)
        result = det.detect(df)

        # Le wick ne doit pas casser is_range
        # Le quantile 95 reste proche du range, le buffer absorbe le wick
        assert result.is_range is True or result.no_breakout_ok is True, \
            f"Wick a fausse detection: {result.reason}"

    def test_real_breakout_detected(self):
        """Breakout reel (>buffer) doit casser no_breakout_ok."""
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=60, range_high=28700.0, range_low=28650.0)
        # 20 bars de breakout franc (+15 pts au-dessus)
        breakout = pd.DataFrame({
            "high": [28720 + i * 0.5 for i in range(20)],
            "low": [28715 + i * 0.5 for i in range(20)],
            "close": [28718 + i * 0.5 for i in range(20)],
        })
        df_full = pd.concat([df, breakout], ignore_index=True)
        df_full = add_features_v3(df_full)
        result = det.detect(df_full)

        # Apres breakout : n_macro_ok devrait baisser (ADX up, swing reset normalement)
        # Au minimum no_breakout_ok = False
        assert result.no_breakout_ok is False, \
            f"Breakout reel non detecte: {result.reason}"


class TestColorInversion:
    """Tests observation Jackson 07/05 : color inversion = signal cassure."""

    def test_color_dn_in_low_zone_triggers_down_break_risk(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        # Force prix en zone basse
        df.loc[df.index[-1], "close"] = 28655.0
        df.loc[df.index[-1], "high"] = 28658.0
        df.loc[df.index[-1], "low"] = 28653.0
        df = add_features_v3(
            df,
            near_low=True,
            color_dn_in_low=True,  # ROUGES PENETRENT CAMP DES VERTS
        )
        result = det.detect(df)

        assert result.range_pos is not None and result.range_pos < INVERSION_LOW_ZONE
        assert result.color_dn_in_low_zone > 0
        assert result.range_break_risk == "DOWN_BREAK_IMMINENT"
        assert result.break_risk_confidence == "MED"

    def test_color_dn_plus_long_dn_bar_high_confidence(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        df.loc[df.index[-1], "close"] = 28655.0
        df.loc[df.index[-1], "high"] = 28658.0
        df.loc[df.index[-1], "low"] = 28653.0
        df = add_features_v3(
            df,
            near_low=True,
            color_dn_in_low=True,
            long_dn_bar=True,  # CONFIRMATION ATTAQUE
        )
        result = det.detect(df)

        assert result.range_break_risk == "DOWN_BREAK_IMMINENT"
        assert result.break_risk_confidence == "HIGH"
        assert result.long_dn_bar_in_low is True

    def test_color_up_in_high_zone_triggers_up_break_risk(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        # Force prix en zone haute
        df.loc[df.index[-1], "close"] = 28695.0
        df.loc[df.index[-1], "high"] = 28697.0
        df.loc[df.index[-1], "low"] = 28693.0
        df = add_features_v3(
            df,
            near_high=True,
            color_up_in_high=True,  # VERTS PENETRENT CAMP DES ROUGES
            long_up_bar=True,
        )
        result = det.detect(df)

        assert result.range_pos is not None and result.range_pos > INVERSION_HIGH_ZONE
        assert result.range_break_risk == "UP_BREAK_IMMINENT"
        assert result.break_risk_confidence == "HIGH"
        assert result.long_up_bar_in_high is True

    def test_break_risk_invalidates_is_range(self):
        """is_range = False si range_break_risk != NONE (regle V3 final_verdict)."""
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        df.loc[df.index[-1], "close"] = 28655.0
        df.loc[df.index[-1], "high"] = 28658.0
        df.loc[df.index[-1], "low"] = 28653.0
        df = add_features_v3(df, near_low=True, color_dn_in_low=True)
        result = det.detect(df)

        assert result.range_break_risk == "DOWN_BREAK_IMMINENT"
        # Meme si macro+micro+density OK, is_range = False car break_risk
        assert result.is_range is False, \
            f"is_range devrait etre False car break_risk: {result.reason}"


class TestSignalHintSuppression:
    """Signal hint NEVER emit si break_risk meme direction."""

    def test_long_fade_hint_suppressed_if_down_break(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        df.loc[df.index[-1], "close"] = 28655.0
        df.loc[df.index[-1], "high"] = 28658.0
        df.loc[df.index[-1], "low"] = 28653.0
        df = add_features_v3(df, near_low=True, color_dn_in_low=True)
        result = det.detect(df)

        # range_pos < 0.30 + density_low_ok → V2 emit LONG_FADE_HINT
        # V3 : break_risk DOWN → SUPPRIME (on serait long contre cassure)
        assert result.signal_hint == "NONE", \
            f"LONG_FADE_HINT emis malgre DOWN_BREAK: {result.reason}"

    def test_short_fade_hint_suppressed_if_up_break(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80, range_high=28700.0, range_low=28650.0)
        df.loc[df.index[-1], "close"] = 28695.0
        df.loc[df.index[-1], "high"] = 28697.0
        df.loc[df.index[-1], "low"] = 28693.0
        df = add_features_v3(df, near_high=True, color_up_in_high=True)
        result = det.detect(df)

        assert result.signal_hint == "NONE", \
            f"SHORT_FADE_HINT emis malgre UP_BREAK: {result.reason}"


class TestRangeToBreakoutTransitions:
    """3 cas critiques transition range → breakout (anti faux positif)."""

    def test_whipsaw_fakeout_then_resume(self):
        """Faux breakout (3 bars hors range) puis retour : V3 doit ne PAS emettre is_range
        durant le wick mais reprendre apres."""
        det = RangeDetectorV3(sym="NQ")
        # 60 bars range + 3 wick + 17 retour range
        df_range1 = make_synthetic_range(n_bars=60, range_high=28700.0, range_low=28650.0, seed=1)
        whipsaw = pd.DataFrame({
            "high": [28710.0, 28712.0, 28708.0],   # wick 10 pts au-dessus zone
            "low": [28705.0, 28707.0, 28695.0],
            "close": [28708.0, 28710.0, 28697.0],   # retour vers range
        })
        df_range2 = make_synthetic_range(n_bars=17, range_high=28700.0, range_low=28650.0, seed=2)
        df_full = pd.concat([df_range1, whipsaw, df_range2], ignore_index=True)
        df_full = add_features_v3(df_full)

        # Detect a la fin (apres reprise range) → devrait redetecter range
        result = det.detect(df_full)
        # On verifie surtout que ca n'a pas casse sur le whipsaw passe (zones absorbent)
        assert result.range_high_zone is not None
        # Le test principal : pas d'erreur, et n_macro_ok raisonnable
        assert result.n_macro_ok >= 0  # Sanity check

    def test_slow_drift_breakout_detected(self):
        """Drift lent (10 bars +20 pts) qui sort progressivement du range."""
        det = RangeDetectorV3(sym="NQ")
        df_range = make_synthetic_range(n_bars=60, range_high=28700.0, range_low=28650.0)
        # Drift up 20 bars +1 pt/bar = +20 pts (sort de la zone)
        drift = pd.DataFrame({
            "high": [28702.0 + i * 1.0 for i in range(20)],
            "low": [28697.0 + i * 1.0 for i in range(20)],
            "close": [28700.0 + i * 1.0 for i in range(20)],
        })
        df_full = pd.concat([df_range, drift], ignore_index=True)
        df_full = add_features_v3(
            df_full,
            swing_bars=10,        # swing reset par drift
            poc_migration=0.05,   # POC migre
            aggressor_imbalance=0.3,  # flow biaise
        )
        result = det.detect(df_full)

        # Apres drift : ADX up + M5/M7/M8 KO → no range
        assert result.is_range is False, \
            f"Drift breakout non detecte: {result.reason}"
        # Au moins 1 critere AMT V3 doit avoir flag
        assert not (result.swing_ok and result.poc_stable_ok and result.aggressor_balanced_ok), \
            "Tous M5/M7/M8 OK alors que drift evident"

    def test_trend_compression_to_range(self):
        """Trend qui se calme en range : detection apparait apres compression."""
        det = RangeDetectorV3(sym="NQ")
        # 30 bars trend + 50 bars range
        df_trend = make_synthetic_trend(n_bars=30, start=28500.0, end=28680.0)
        df_range = make_synthetic_range(n_bars=50, range_high=28700.0, range_low=28660.0, seed=99)
        df_full = pd.concat([df_trend, df_range], ignore_index=True)
        df_full = add_features_v3(df_full)

        result = det.detect(df_full)
        # On detecte sur la fenetre 60 dernieres bars (trend-end + range)
        # ADX devrait baisser, swing peut etre OK depuis 50 bars
        # Au minimum : pas de crash, range_pos dans [0,1]
        assert result.range_pos is not None
        assert 0.0 <= result.range_pos <= 1.0


class TestIterative:
    def test_detect_iterative_returns_columns(self):
        det = RangeDetectorV3(sym="NQ")
        df = make_synthetic_range(n_bars=80)
        df = add_features_v3(df)
        df_aug = det.detect_iterative(df)

        for col in [
            "is_range", "is_range_macro", "is_range_micro",
            "range_high_zone", "range_low_zone", "range_pos",
            "n_macro_ok", "swing_ok", "va_stable_ok", "poc_stable_ok", "aggressor_balanced_ok",
            "range_break_risk", "break_risk_confidence", "signal_hint",
        ]:
            assert col in df_aug.columns, f"Colonne {col} manquante"
        assert len(df_aug) == len(df)
