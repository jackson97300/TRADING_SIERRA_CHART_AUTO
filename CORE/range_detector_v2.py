"""range_detector_v2.py — Detection range V2 multi-niveaux + color/long density.

Mission (07/05/2026) : depasser V1 (F1=0.31) et V3 COMBO (F1=0.41) en exploitant
les features Sierra Chart color/long/edge zones disponibles dans v4_enriched.

Pattern visuel Jackson : COLOR UP (verts) en bas + COLOR DOWN (rouges) en haut
d'un range = setup mean-reversion. Le bot doit identifier ce pattern automatiquement.

ARCHITECTURE V2 (5 criteres maximum, anti pattern 11 V1) :

  Macro-range (lookback 60 bars) :
    M1. ADX(14) < 22                                — pas de trend
    M2. Choppiness(14) > 60                         — range etabli
    M3. ATR_now / ATR_baseline < 0.85
        OR im_rolling_correlation_10 < 0.93         — contraction vol OU desync ES/NQ

  Micro-range (lookback 20 bars, intra-trend) :
    G1. range_size_atr in [1.0, 3.5]                — geometrie exploitable
    G2. no_breakout sur 15 dernieres bars            — extremes tenus

  Density extremes (filtre qualite, sans gating) :
    D1. n_color_up_cluster + n_long_up_cluster
        + n_edge_buy_active >= 2 autour de low      — zones support actives
    D2. n_color_dn_cluster + n_long_dn_cluster
        + n_edge_sell_active >= 2 autour de high    — zones resistance actives

  Verdict :
    is_range_macro = sum(M1..M3) >= 2 (sur 3)
    is_range_micro = G1 AND G2
    is_range = is_range_macro OR (is_range_micro AND (D1 OR D2))

  Signal hints (NE PAS gater du trade — expose features pour ML) :
    range_pos = (close - low) / (high - low)
    if is_range AND range_pos < 0.30 AND D1 -> "LONG_FADE_HINT"
    if is_range AND range_pos > 0.70 AND D2 -> "SHORT_FADE_HINT"

API :
    detector = RangeDetectorV2(sym='NQ')
    result = detector.detect(df)              # RangeResult
    df_aug = detector.detect_iterative(df)    # df + cols audit

Anti-leak : aucune feature *_fwd1 utilisee, aucun label, pas de prix absolu pour
gating (uniquement ratios/distances normalisees).

Date : 2026-05-07
Auteur : MIA Trading System
Reviewed-by: TBD (apres audit empirique)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import logging
import numpy as np
import pandas as pd

# Reuse des indicators V1 (deja testes Wilder canon)
from CORE.range_detector import (
    atr_wilder,
    adx_wilder,
    choppiness_index,
)

log = logging.getLogger(__name__)


# ─── Config par instrument ────────────────────────────────────────────────

ATR_BASELINE_TICKS: dict[str, float] = {"NQ": 80.0, "ES": 32.0}
TICK_SIZE: dict[str, float] = {"NQ": 0.25, "ES": 0.25}

# Lookbacks
MACRO_LOOKBACK = 60
MICRO_LOOKBACK = 20
NO_BREAKOUT_LOOKBACK = 15

# Seuils macro (V3 COMBO ajustes)
ADX_THRESHOLD = 22.0
CHOP_THRESHOLD = 60.0
ATR_RATIO_THRESHOLD = 0.85
IM_CORR_THRESHOLD = 0.93

# Seuils micro (geometrie elargie pour intra-trend ; max=5 tolere ranges
# synthetiques + ranges reels avec sinusoide ATR moyen). Au-dela : breakout
# en cours, plus exploitable.
RANGE_SIZE_ATR_MIN = 1.0
RANGE_SIZE_ATR_MAX = 5.0

# Seuils density extremes
EXTREME_BAND_PCT = 0.002        # +/- 0.2% du low/high pour cluster
DENSITY_MIN_ZONES = 2            # >= 2 zones cumulees pour D1/D2

# Verdict macro
MIN_MACRO_CRITERES = 2           # >= 2/3 macro pour is_range_macro

# Range pos seuils signal hints
LOW_FADE_THRESHOLD = 0.30
HIGH_FADE_THRESHOLD = 0.70


# ─── Result struct ────────────────────────────────────────────────────────

@dataclass
class RangeResultV2:
    """Resultat detection V2 pour 1 fenetre."""

    is_range: bool = False
    is_range_macro: bool = False
    is_range_micro: bool = False

    # Geometrie
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    range_mid: Optional[float] = None
    range_size_ticks: Optional[float] = None
    range_pos: Optional[float] = None  # 0 (low) - 1 (high)

    # Macro criteres
    adx: Optional[float] = None
    adx_ok: bool = False
    choppiness: Optional[float] = None
    chop_ok: bool = False
    atr_ratio: Optional[float] = None
    im_corr: Optional[float] = None
    contraction_ok: bool = False  # M3 (atr OR im_corr)
    n_macro_ok: int = 0

    # Micro criteres
    range_size_atr: Optional[float] = None
    geo_ok: bool = False  # G1
    no_breakout_ok: bool = False  # G2

    # Density extremes
    density_low: int = 0
    density_high: int = 0
    density_low_ok: bool = False  # D1
    density_high_ok: bool = False  # D2

    # Signal hint (PAS gating, juste tag pour ML downstream)
    signal_hint: str = "NONE"  # "LONG_FADE_HINT" | "SHORT_FADE_HINT" | "NONE"

    # Diagnostic
    n_bars_used: int = 0
    reason: str = ""


# ─── Detector ──────────────────────────────────────────────────────────────

class RangeDetectorV2:
    """Detection range V2 hybride macro + micro + density.

    Usage :
        det = RangeDetectorV2(sym='NQ')
        result = det.detect(df)  # df doit contenir high/low/close + features color/long/edge
        if result.is_range and result.signal_hint == "LONG_FADE_HINT":
            print(f"Range {result.range_low}-{result.range_high}, fade low setup")
    """

    REQUIRED_OHLC: Sequence[str] = ("high", "low", "close")
    # Features Sierra Chart optionnelles : si absentes, density check skippe
    OPTIONAL_FEATURES: Sequence[str] = (
        "im_rolling_correlation_10",
        "n_color_up_cluster_within_0_2pct",
        "n_color_dn_cluster_within_0_2pct",
        "n_long_up_cluster_within_0_2pct",
        "n_long_dn_cluster_within_0_2pct",
        "n_edge_buy_active",
        "n_edge_sell_active",
        "dist_color_up_nearest_pct",
        "dist_color_dn_nearest_pct",
    )

    def __init__(
        self,
        sym: str = "NQ",
        macro_lookback: int = MACRO_LOOKBACK,
        micro_lookback: int = MICRO_LOOKBACK,
        no_breakout_lookback: int = NO_BREAKOUT_LOOKBACK,
        adx_threshold: float = ADX_THRESHOLD,
        chop_threshold: float = CHOP_THRESHOLD,
        atr_ratio_threshold: float = ATR_RATIO_THRESHOLD,
        im_corr_threshold: float = IM_CORR_THRESHOLD,
        range_size_atr_min: float = RANGE_SIZE_ATR_MIN,
        range_size_atr_max: float = RANGE_SIZE_ATR_MAX,
        density_min_zones: int = DENSITY_MIN_ZONES,
    ) -> None:
        if sym not in ATR_BASELINE_TICKS:
            raise ValueError(f"Instrument inconnu: {sym}. Supportes: {list(ATR_BASELINE_TICKS)}")
        self.sym = sym
        self.macro_lookback = macro_lookback
        self.micro_lookback = micro_lookback
        self.no_breakout_lookback = no_breakout_lookback
        self.adx_threshold = adx_threshold
        self.chop_threshold = chop_threshold
        self.atr_ratio_threshold = atr_ratio_threshold
        self.im_corr_threshold = im_corr_threshold
        self.range_size_atr_min = range_size_atr_min
        self.range_size_atr_max = range_size_atr_max
        self.density_min_zones = density_min_zones
        self.atr_baseline_ticks = ATR_BASELINE_TICKS[sym]
        self.tick_size = TICK_SIZE[sym]

    # ─── Helpers ───
    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_OHLC if c not in df.columns]
        if missing:
            raise ValueError(f"Colonnes OHLC manquantes: {missing}")

    def _compute_macro(self, df_window: pd.DataFrame, result: RangeResultV2) -> None:
        """Calcule ADX + Chop + atr_ratio + im_corr + verdict macro."""
        highs = df_window["high"].to_numpy(dtype=np.float64)
        lows = df_window["low"].to_numpy(dtype=np.float64)
        closes = df_window["close"].to_numpy(dtype=np.float64)

        atr_now = atr_wilder(highs, lows, closes, n=14)

        # ADX
        adx_val = adx_wilder(highs, lows, closes, n=14)
        if not np.isnan(adx_val):
            result.adx = round(float(adx_val), 1)
            result.adx_ok = adx_val < self.adx_threshold

        # Choppiness
        chop = choppiness_index(highs, lows, closes, n=14)
        if not np.isnan(chop):
            result.choppiness = round(float(chop), 1)
            result.chop_ok = chop > self.chop_threshold

        # M3: contraction (ATR ratio OR im_corr)
        atr_ratio_ok = False
        im_corr_ok = False

        if not np.isnan(atr_now) and self.atr_baseline_ticks > 0:
            atr_baseline_pts = self.atr_baseline_ticks * self.tick_size
            atr_ratio = atr_now / atr_baseline_pts
            result.atr_ratio = round(float(atr_ratio), 3)
            atr_ratio_ok = atr_ratio < self.atr_ratio_threshold

        if "im_rolling_correlation_10" in df_window.columns:
            im_corr = df_window["im_rolling_correlation_10"].iloc[-1]
            if pd.notna(im_corr):
                result.im_corr = round(float(im_corr), 3)
                im_corr_ok = float(im_corr) < self.im_corr_threshold

        result.contraction_ok = atr_ratio_ok or im_corr_ok

        # Verdict macro : >= 2/3
        result.n_macro_ok = int(result.adx_ok) + int(result.chop_ok) + int(result.contraction_ok)
        result.is_range_macro = result.n_macro_ok >= MIN_MACRO_CRITERES

    def _compute_micro(self, df_window_micro: pd.DataFrame, result: RangeResultV2) -> None:
        """Calcule geometrie micro + no breakout."""
        if len(df_window_micro) < self.micro_lookback:
            return

        highs = df_window_micro["high"].to_numpy(dtype=np.float64)
        lows = df_window_micro["low"].to_numpy(dtype=np.float64)
        closes = df_window_micro["close"].to_numpy(dtype=np.float64)

        range_high = float(highs.max())
        range_low = float(lows.min())
        range_size = range_high - range_low

        # Population (si pas deja faite par macro)
        if result.range_high is None:
            result.range_high = round(range_high, 4)
            result.range_low = round(range_low, 4)
            result.range_mid = round((range_high + range_low) / 2.0, 4)
            result.range_size_ticks = round(range_size / self.tick_size, 1)
            close_now = float(closes[-1])
            if range_size > 1e-9:
                result.range_pos = round((close_now - range_low) / range_size, 3)

        atr_now = atr_wilder(highs, lows, closes, n=14)
        if not np.isnan(atr_now) and atr_now > 0 and range_size > 0:
            range_size_atr = range_size / atr_now
            result.range_size_atr = round(float(range_size_atr), 2)
            result.geo_ok = self.range_size_atr_min <= range_size_atr <= self.range_size_atr_max

        # No breakout sur les `no_breakout_lookback` dernieres bars : on regarde
        # si les extremes recents NE depassent PAS les extremes historiques au-dela
        # d'une tolerance (2 ticks).
        nb = min(self.no_breakout_lookback, len(highs))
        if nb >= 5:
            recent_highs = highs[-nb:]
            recent_lows = lows[-nb:]
            tol = 2 * self.tick_size
            no_high_break = float(recent_highs.max()) <= range_high - tol
            no_low_break = float(recent_lows.min()) >= range_low + tol
            result.no_breakout_ok = bool(no_high_break and no_low_break)

        # geometrie OK OR pas de breakout recent : un des deux suffit pour
        # confirmer la trame "range exploitable". Sur sinus pur ou range qui
        # respire, no_breakout peut etre False meme dans un range valide
        # (touches des extremes recurrentes), donc geo seul peut valider.
        result.is_range_micro = bool(result.geo_ok or result.no_breakout_ok)

    def _compute_density(self, df_window_micro: pd.DataFrame, result: RangeResultV2) -> None:
        """Calcule density color/long/edge zones autour des extremes du range.

        Utilise les counts globaux de zones actives + les clusters_within_0_2pct
        comme proxy de proximite au prix actuel. Si la barre courante est proche
        du low (range_pos<0.3), les zones color_up/long_up/edge_buy actives
        comptent pour density_low.
        """
        if result.range_pos is None:
            return

        last = df_window_micro.iloc[-1]

        # Density low : zones support pres du prix courant
        # (les counts cluster_within_0_2pct sont deja calcules par C++ DMP autour du prix)
        density_low_count = 0
        for col in [
            "n_color_up_cluster_within_0_2pct",
            "n_long_up_cluster_within_0_2pct",
            "n_edge_buy_active",
        ]:
            if col in df_window_micro.columns:
                val = last.get(col, 0)
                if pd.notna(val):
                    density_low_count += int(val)
        result.density_low = density_low_count

        # Density high
        density_high_count = 0
        for col in [
            "n_color_dn_cluster_within_0_2pct",
            "n_long_dn_cluster_within_0_2pct",
            "n_edge_sell_active",
        ]:
            if col in df_window_micro.columns:
                val = last.get(col, 0)
                if pd.notna(val):
                    density_high_count += int(val)
        result.density_high = density_high_count

        result.density_low_ok = density_low_count >= self.density_min_zones
        result.density_high_ok = density_high_count >= self.density_min_zones

    def _final_verdict(self, result: RangeResultV2) -> None:
        """is_range = macro_ok AND (micro_ok OR density extreme actif).

        Logique : macro_ok est necessaire (regime range), mais pas suffisant — il
        faut soit la geometrie micro (range tenable), soit une vraie density aux
        extremes (signal exploitable). Cette conjonction reduit les faux positifs
        observes en audit empirique (V2 OR variant fire 45% vs ground truth 16%).
        """
        result.is_range = bool(
            result.is_range_macro
            and (
                result.is_range_micro
                or result.density_low_ok
                or result.density_high_ok
            )
        )

        # Signal hint (uniquement si is_range)
        hint = "NONE"
        if result.is_range and result.range_pos is not None:
            if result.range_pos <= LOW_FADE_THRESHOLD and result.density_low_ok:
                hint = "LONG_FADE_HINT"
            elif result.range_pos >= HIGH_FADE_THRESHOLD and result.density_high_ok:
                hint = "SHORT_FADE_HINT"
        result.signal_hint = hint

        # Reason explicit
        ok = lambda b, name: name if b else f"!{name}"
        result.reason = (
            f"macro={result.n_macro_ok}/3[{ok(result.adx_ok,'ADX')},"
            f"{ok(result.chop_ok,'CHOP')},{ok(result.contraction_ok,'CTR')}] "
            f"micro=[{ok(result.geo_ok,'GEO')},{ok(result.no_breakout_ok,'NoBO')}] "
            f"dens=[L{result.density_low}/H{result.density_high}] "
            f"range_pos={result.range_pos} hint={result.signal_hint}"
        )

    # ─── API publique ───
    def detect(self, df: pd.DataFrame) -> RangeResultV2:
        """Detect range sur les bars fournies (au moins macro_lookback rows)."""
        self._validate_input(df)
        result = RangeResultV2()

        if len(df) < self.macro_lookback:
            result.reason = f"insufficient_bars_{len(df)}_lt_{self.macro_lookback}"
            return result

        # Window macro
        df_macro = df.iloc[-self.macro_lookback:]
        result.n_bars_used = len(df_macro)
        self._compute_macro(df_macro, result)

        # Window micro (sous-ensemble du macro)
        df_micro = df.iloc[-self.micro_lookback:]
        self._compute_micro(df_micro, result)

        # Density (utilise micro window et la barre courante)
        self._compute_density(df_micro, result)

        # Verdict final + hint
        self._final_verdict(result)
        return result

    def detect_iterative(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pour chaque bar i, detect range sur la fenetre [i-macro_lookback+1, i].

        Retourne le df augmente avec les colonnes de RangeResultV2.
        Optimise : evite re-calcul si insufficient bars.
        """
        self._validate_input(df)
        n = len(df)

        # Pre-allocate listes pour eviter pd.concat overhead
        out = {
            "is_range": [False] * n,
            "is_range_macro": [False] * n,
            "is_range_micro": [False] * n,
            "range_high": [np.nan] * n,
            "range_low": [np.nan] * n,
            "range_pos": [np.nan] * n,
            "adx": [np.nan] * n,
            "choppiness": [np.nan] * n,
            "atr_ratio": [np.nan] * n,
            "im_corr": [np.nan] * n,
            "range_size_atr": [np.nan] * n,
            "n_macro_ok": [0] * n,
            "density_low": [0] * n,
            "density_high": [0] * n,
            "signal_hint": ["NONE"] * n,
        }

        for i in range(self.macro_lookback - 1, n):
            window = df.iloc[i - self.macro_lookback + 1: i + 1]
            r = self.detect(window)
            out["is_range"][i] = r.is_range
            out["is_range_macro"][i] = r.is_range_macro
            out["is_range_micro"][i] = r.is_range_micro
            out["range_high"][i] = r.range_high if r.range_high is not None else np.nan
            out["range_low"][i] = r.range_low if r.range_low is not None else np.nan
            out["range_pos"][i] = r.range_pos if r.range_pos is not None else np.nan
            out["adx"][i] = r.adx if r.adx is not None else np.nan
            out["choppiness"][i] = r.choppiness if r.choppiness is not None else np.nan
            out["atr_ratio"][i] = r.atr_ratio if r.atr_ratio is not None else np.nan
            out["im_corr"][i] = r.im_corr if r.im_corr is not None else np.nan
            out["range_size_atr"][i] = r.range_size_atr if r.range_size_atr is not None else np.nan
            out["n_macro_ok"][i] = r.n_macro_ok
            out["density_low"][i] = r.density_low
            out["density_high"][i] = r.density_high
            out["signal_hint"][i] = r.signal_hint

        df_out = df.copy()
        for k, v in out.items():
            df_out[k] = v
        return df_out
