"""range_detector.py — Detection fiable de RANGE multi-criteres (Jackson 07/05).

Demande : detection range automatisee qui matche les ranges visuels reels (cf trade
manuel NQ 06/05 28656.75-28694.00 sur ~3h). Critique pour :
  - Bot 3 : ajouter setups RANGE_LOW / RANGE_HIGH (fade extremes)
  - Bot 1+2 : relacher RegimeGate STRICT sur range days (sinon 0 trade)

Methodologie : 5 criteres independants (chacun mesure un aspect du range), >= 3/5
valides → RANGE confirme. Pattern hybride pro (vs single-indicator fragile).

Criteres :
  1. Volatilite faible : ATR(14) / ATR_baseline_60d < seuil
  2. Pas de directionnalite : ADX(14) < 25 (Wilder canon)
  3. Choppiness eleve : Choppiness Index > 60
  4. Geometrie range stable : 1.5 < (High_60 - Low_60) / ATR < 4.0
  5. Pas de breakout recent : new_high(20) < High_60 AND new_low(20) > Low_60

API :
    detector = RangeDetector(sym='NQ')
    result = detector.detect(df_recent_bars)  # dict {is_range, n_criteres, range_high, range_low, ...}
    is_range_series = detector.detect_iterative(df_full)  # pd.Series bool pour audit

Tests : CORE/tests/test_range_detector.py (synthetiques + cas reels)

Date : 2026-05-07
Auteur : MIA Trading System
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ─── Config par instrument ────────────────────────────────────────────────

# ATR baseline (atr_14m_pct mediane sur 318j V4) — cf bot3_config.py
ATR_BASELINE_PCT = {"NQ": 0.033, "ES": 0.027}
# ATR en ticks pour le seuil de range geometrique (median session)
ATR_BASELINE_TICKS = {"NQ": 80, "ES": 32}

# Seuils detection (calibrables, default canon hybride)
ATR_RATIO_RANGE_THRESHOLD = 0.85    # ATR_now / baseline < 0.85 = volatilite contracted
ADX_RANGE_THRESHOLD = 25.0           # ADX < 25 = pas de trend (Wilder canon)
CHOPPINESS_RANGE_THRESHOLD = 60.0    # Chop > 60 = range
RANGE_SIZE_ATR_MIN = 1.5              # Range / ATR > 1.5 (sinon trop serre = pas de range expoitable)
RANGE_SIZE_ATR_MAX = 4.0              # Range / ATR < 4.0 (sinon range etendu = pas mean revert)
NO_BREAKOUT_LOOKBACK_BARS = 20        # No new high/low sur 20 dernieres bars
RANGE_LOOKBACK_BARS = 60               # Window pour detecter range geometrique

# Score minimum criteres pour confirmer range (>= 3/5)
MIN_CRITERES_VALID = 3


@dataclass
class RangeDetectionResult:
    """Resultat detection range pour une fenetre de bars."""
    is_range: bool = False
    n_criteres: int = 0
    n_criteres_total: int = 5
    # Geometric extremes detectes
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    range_mid: Optional[float] = None
    range_size_ticks: Optional[float] = None
    # Critere details
    atr_ratio: Optional[float] = None         # ATR_now / baseline
    atr_ratio_ok: bool = False                 # < threshold
    adx: Optional[float] = None
    adx_ok: bool = False                        # < threshold
    choppiness: Optional[float] = None
    choppiness_ok: bool = False                 # > threshold
    range_size_atr: Optional[float] = None
    range_size_atr_ok: bool = False             # 1.5-4.0
    no_breakout_recent: bool = False
    # Diagnostic / audit
    n_bars_used: int = 0
    reason: str = ""


# ─── Indicators (Wilder canon) ────────────────────────────────────────────

def true_range(high: np.ndarray, low: np.ndarray, close_prev: np.ndarray) -> np.ndarray:
    """True Range (TR) = max(high-low, |high-close_prev|, |low-close_prev|)."""
    return np.maximum.reduce([
        high - low,
        np.abs(high - close_prev),
        np.abs(low - close_prev),
    ])


def atr_wilder(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int = 14) -> float:
    """Average True Range (Wilder smoothing). Retourne valeur la plus recente."""
    if len(highs) < n + 1:
        return float("nan")
    tr = true_range(highs[1:], lows[1:], closes[:-1])
    # Wilder smoothing : ATR_i = (ATR_{i-1} * (n-1) + TR_i) / n
    atr = tr[:n].mean()
    for i in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[i]) / n
    return float(atr)


def adx_wilder(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int = 14) -> float:
    """Average Directional Index (Wilder canon). 0 = no trend, 100 = trend max.

    < 20 : pas de trend (range)
    20-25 : trend faible
    > 25 : trend etabli
    > 50 : trend fort
    """
    if len(highs) < 2 * n + 1:
        return float("nan")

    # Mouvement directionnel
    up_move = np.diff(highs)
    down_move = -np.diff(lows)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # True Range
    tr = true_range(highs[1:], lows[1:], closes[:-1])

    # Wilder smoothing : sums initial = sum(n) puis (sum * (n-1) + new) / n
    def wilder_smooth(arr: np.ndarray, n: int) -> np.ndarray:
        smoothed = np.zeros(len(arr))
        smoothed[n - 1] = arr[:n].sum()
        for i in range(n, len(arr)):
            smoothed[i] = smoothed[i - 1] - smoothed[i - 1] / n + arr[i]
        return smoothed

    tr_s = wilder_smooth(tr, n)
    plus_dm_s = wilder_smooth(plus_dm, n)
    minus_dm_s = wilder_smooth(minus_dm, n)

    # +DI / -DI
    plus_di = 100 * plus_dm_s / np.maximum(tr_s, 1e-9)
    minus_di = 100 * minus_dm_s / np.maximum(tr_s, 1e-9)

    # DX
    dx = 100 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-9)

    # ADX = Wilder smooth of DX (premier calcul = mean des n DX, puis Wilder)
    if len(dx) < 2 * n:
        return float("nan")
    adx_arr = np.zeros(len(dx))
    adx_arr[2 * n - 2] = dx[n - 1: 2 * n - 1].mean()
    for i in range(2 * n - 1, len(dx)):
        adx_arr[i] = (adx_arr[i - 1] * (n - 1) + dx[i]) / n

    return float(adx_arr[-1])


def choppiness_index(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int = 14) -> float:
    """Choppiness Index : 0 = trend pur, 100 = range total.

    Formule : 100 * log10(sum(TR_n) / (max(High_n) - min(Low_n))) / log10(n)

    Interpretation :
      < 38.2 : trend etabli
      > 61.8 : range etabli
      38.2-61.8 : zone neutre
    """
    if len(highs) < n + 1:
        return float("nan")

    tr = true_range(highs[1:], lows[1:], closes[:-1])
    if len(tr) < n:
        return float("nan")

    sum_tr = tr[-n:].sum()
    range_n = highs[-n:].max() - lows[-n:].min()
    if range_n <= 0:
        return float("nan")

    return float(100 * np.log10(sum_tr / range_n) / np.log10(n))


# ─── Detector principal ───────────────────────────────────────────────────

class RangeDetector:
    """Detection range multi-criteres pour 1 instrument.

    Usage :
        det = RangeDetector(sym='NQ')
        result = det.detect(df_last_60_bars)
        if result.is_range:
            print(f"Range {result.range_low:.2f} - {result.range_high:.2f}")
    """

    def __init__(self, sym: str = "NQ",
                  lookback: int = RANGE_LOOKBACK_BARS,
                  no_breakout_lookback: int = NO_BREAKOUT_LOOKBACK_BARS,
                  atr_ratio_threshold: float = ATR_RATIO_RANGE_THRESHOLD,
                  adx_threshold: float = ADX_RANGE_THRESHOLD,
                  choppiness_threshold: float = CHOPPINESS_RANGE_THRESHOLD,
                  range_size_atr_min: float = RANGE_SIZE_ATR_MIN,
                  range_size_atr_max: float = RANGE_SIZE_ATR_MAX,
                  min_criteres_valid: int = MIN_CRITERES_VALID):
        self.sym = sym
        self.lookback = lookback
        self.no_breakout_lookback = no_breakout_lookback
        self.atr_ratio_threshold = atr_ratio_threshold
        self.adx_threshold = adx_threshold
        self.choppiness_threshold = choppiness_threshold
        self.range_size_atr_min = range_size_atr_min
        self.range_size_atr_max = range_size_atr_max
        self.min_criteres_valid = min_criteres_valid
        self.atr_baseline_ticks = ATR_BASELINE_TICKS.get(sym, 80)

    def detect(self, df: pd.DataFrame) -> RangeDetectionResult:
        """Detect range sur les bars fournies. df doit contenir colonnes high, low, close.

        Args:
            df : pd.DataFrame avec >= lookback bars (60 bars par defaut)

        Returns:
            RangeDetectionResult avec is_range + diagnostics
        """
        result = RangeDetectionResult()

        if len(df) < self.lookback:
            result.reason = f"insufficient_bars_{len(df)}_lt_{self.lookback}"
            return result

        # Prendre les `lookback` dernieres bars
        df_window = df.iloc[-self.lookback:]
        result.n_bars_used = len(df_window)

        highs = df_window["high"].values.astype(np.float64)
        lows = df_window["low"].values.astype(np.float64)
        closes = df_window["close"].values.astype(np.float64)

        # ─── Critere 1 : ATR ratio ───
        atr_now = atr_wilder(highs, lows, closes, n=14)
        if not np.isnan(atr_now) and self.atr_baseline_ticks > 0:
            # Convertir baseline en points (ticks * tick_size) pour comparaison directe
            # ATR Wilder est en points, baseline est en ticks → convertir
            tick_size = 0.25  # NQ et ES sont 0.25
            atr_baseline_pts = self.atr_baseline_ticks * tick_size
            result.atr_ratio = round(atr_now / atr_baseline_pts, 3)
            result.atr_ratio_ok = result.atr_ratio < self.atr_ratio_threshold

        # ─── Critere 2 : ADX ───
        adx_val = adx_wilder(highs, lows, closes, n=14)
        if not np.isnan(adx_val):
            result.adx = round(adx_val, 1)
            result.adx_ok = adx_val < self.adx_threshold

        # ─── Critere 3 : Choppiness ───
        chop = choppiness_index(highs, lows, closes, n=14)
        if not np.isnan(chop):
            result.choppiness = round(chop, 1)
            result.choppiness_ok = chop > self.choppiness_threshold

        # ─── Critere 4 : Geometrie range ───
        range_high = float(highs.max())
        range_low = float(lows.min())
        range_size = range_high - range_low
        result.range_high = round(range_high, 2)
        result.range_low = round(range_low, 2)
        result.range_mid = round((range_high + range_low) / 2, 2)
        # Range size en ticks
        result.range_size_ticks = round(range_size / 0.25, 1)
        if not np.isnan(atr_now) and atr_now > 0:
            result.range_size_atr = round(range_size / atr_now, 2)
            result.range_size_atr_ok = (
                self.range_size_atr_min <= result.range_size_atr <= self.range_size_atr_max
            )

        # ─── Critere 5 : Pas de breakout recent ───
        if len(df_window) >= self.no_breakout_lookback:
            recent_highs = highs[-self.no_breakout_lookback:]
            recent_lows = lows[-self.no_breakout_lookback:]
            # Tolerance 2 ticks (= 0.5 pts) pour ne pas bloquer sur micro-spikes
            tol = 2 * 0.25
            recent_no_high_break = recent_highs.max() < range_high - tol
            recent_no_low_break = recent_lows.min() > range_low + tol
            result.no_breakout_recent = bool(recent_no_high_break and recent_no_low_break)

        # ─── Score final ───
        n = sum([
            result.atr_ratio_ok,
            result.adx_ok,
            result.choppiness_ok,
            result.range_size_atr_ok,
            result.no_breakout_recent,
        ])
        result.n_criteres = n
        result.is_range = n >= self.min_criteres_valid

        # Reason explicit
        ok = lambda b, name: name if b else f"!{name}"
        result.reason = (
            f"{n}/5: "
            f"{ok(result.atr_ratio_ok, 'ATR')}+"
            f"{ok(result.adx_ok, 'ADX')}+"
            f"{ok(result.choppiness_ok, 'CHOP')}+"
            f"{ok(result.range_size_atr_ok, 'GEO')}+"
            f"{ok(result.no_breakout_recent, 'NoBO')}"
        )

        return result

    def detect_iterative(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pour chaque bar i de df, detect range sur la fenetre [i-lookback, i].
        Returne df augmentee avec colonnes is_range, n_criteres, range_high, range_low.

        Usage : audit historique pour visualiser la detection bar-by-bar.
        """
        if len(df) < self.lookback:
            df_out = df.copy()
            df_out["is_range"] = False
            df_out["n_criteres"] = 0
            df_out["range_high"] = np.nan
            df_out["range_low"] = np.nan
            return df_out

        results = []
        for i in range(len(df)):
            if i < self.lookback - 1:
                results.append(RangeDetectionResult())
                continue
            window = df.iloc[i - self.lookback + 1: i + 1]
            results.append(self.detect(window))

        df_out = df.copy()
        df_out["is_range"] = [r.is_range for r in results]
        df_out["n_criteres"] = [r.n_criteres for r in results]
        df_out["range_high"] = [r.range_high for r in results]
        df_out["range_low"] = [r.range_low for r in results]
        df_out["range_mid"] = [r.range_mid for r in results]
        df_out["adx"] = [r.adx for r in results]
        df_out["choppiness"] = [r.choppiness for r in results]
        df_out["atr_ratio"] = [r.atr_ratio for r in results]
        df_out["range_size_atr"] = [r.range_size_atr for r in results]
        return df_out
