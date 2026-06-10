"""range_detector_v3.py — Detection range V3 multi-niveaux + color inversion + buffer zones.

Mission (07/05/2026) : depasser V2 (NOGO agent code-reviewer car 9/462 features V4
utilisees, manque AMT 3 piliers). V3 ajoute :

  1. **Buffer zones extremes** (observation Jackson "LES RANGE SON PAS TOUT LE TEMPS
     PROPRE IL FAUT UN BUFFER"). Utilise quantile 5/95 + buffer ticks par instrument.
     Tolere wicks ponctuels sans declencher fake breakout.

  2. **M5-M8 macro Auction Market Theory** (Steidlmayer/Dalton + features V4 enriched
     swing/VA/POC/aggressor). Verdict macro = >= 4/7 criteres (au lieu 2/3 V2).

  3. **Color inversion detector** (observation Jackson 07/05 "LES ROUGE ON ATTAQUER
     LE CAMPS DES VERT"). Quand COLOR DN apparait dans la zone basse (range_pos<0.40)
     = penetration agressive vendeuse = signal cassure imminente. Confirmation HIGH
     si LONG DN bar dans cette zone. Inverse pour cassure haut.

ARCHITECTURE V3 (7 macro + 2 micro + density + inversion) :

  Macro (lookback 60 bars, >= 4/7) :
    M1. ADX(14) < 22                                — pas de trend
    M2. Choppiness(14) > 60                         — range etabli
    M3. ATR_now / ATR_baseline < 0.85
        OR im_rolling_correlation_10 < 0.93         — contraction vol OU desync ES/NQ
    M5. bars_since_last_swing >= 30 (high AND low)  — swings tenus (pas nouveaux pivots)
    M6. last(inside_value_area)==1
        AND std(ctx_va_width_atr[-20:]) / mean<0.20 — VA stable session = balance area
    M7. abs(ctx_poc_migration_10) < 0.005           — POC stable (pas de migration)
    M8. abs(rolling_mean_30(aggressor_imbalance))
        < 0.10                                       — flow two-sided (pas dominance)

  Micro (lookback 20 bars) :
    G1. range_size_atr in [1.0, 5.0]                — geometrie exploitable
    G2. no_breakout sur 15 bars                     — extremes (avec buffer) tenus

  Density extremes (qualite signal, sans gating) :
    D1. n_color_up_cluster + n_long_up_cluster
        + n_edge_buy_active >= 2 autour de low      — zones support actives
    D2. n_color_dn_cluster + n_long_dn_cluster
        + n_edge_sell_active >= 2 autour de high    — zones resistance actives

  Color Inversion (range_break_risk, NEW V3) :
    Si range_pos < 0.40 AND n_color_dn_cluster > 0 → DOWN_BREAK_IMMINENT
       (rouges penetrent zone basse = aggression vendeuse)
       Confirmation HIGH si long_dn_bar==1 dans la barre courante
    Si range_pos > 0.60 AND n_color_up_cluster > 0 → UP_BREAK_IMMINENT
       (verts penetrent zone haute = aggression acheteuse)
       Confirmation HIGH si long_up_bar==1 dans la barre courante

  Verdict :
    is_range_macro = sum(M1..M8) >= 4 (sur 7)
    is_range_micro = G1 OR G2
    is_range = is_range_macro AND (is_range_micro OR D1 OR D2)
              AND range_break_risk == NONE        — un break_risk INVALIDE le range

  Signal hints (NE PAS gater du trade — expose features pour ML) :
    range_pos = (close - range_low_zone) / (range_high_zone - range_low_zone)
    if is_range AND range_pos < 0.30 AND D1 AND no break_risk -> "LONG_FADE_HINT"
    if is_range AND range_pos > 0.70 AND D2 AND no break_risk -> "SHORT_FADE_HINT"

API (compatible avec V2) :
    detector = RangeDetectorV3(sym='NQ')
    result = detector.detect(df)              # RangeResultV3
    df_aug = detector.detect_iterative(df)    # df + cols audit V3

Anti-leak : aucune feature *_fwd1, aucun label, pas de prix absolu pour gating.

Date : 2026-05-07
Auteur : MIA Trading System
Reviewed-by: TBD (apres audit empirique V2 vs V3)
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

# Buffer ticks autour des quantiles pour creer "zones" (observation Jackson 07/05)
# Calibrage : ~ATR/20 (NQ ATR 80t → 4t buffer, ES ATR 32t → 2t buffer)
RANGE_BUFFER_TICKS: dict[str, int] = {"NQ": 4, "ES": 2}

# Lookbacks
MACRO_LOOKBACK = 60
MICRO_LOOKBACK = 20
NO_BREAKOUT_LOOKBACK = 15
VA_STABILITY_LOOKBACK = 20
AGGRESSOR_LOOKBACK = 30

# Quantile pour bornes robustes (tolere 5% wicks haut + 5% bas)
RANGE_QUANTILE_HIGH = 0.95
RANGE_QUANTILE_LOW = 0.05

# Seuils macro V2 (M1-M3)
ADX_THRESHOLD = 22.0
CHOP_THRESHOLD = 60.0
ATR_RATIO_THRESHOLD = 0.85
IM_CORR_THRESHOLD = 0.93

# Seuils macro V3 (M5-M8) — calibre sur V4 enriched (median/q75 documentes)
SWING_BARS_MIN = 30                     # M5 : >= 30 bars depuis last swing (median V4=26, q75=58)
VA_WIDTH_STD_RATIO_MAX = 0.20           # M6 : CV < 20% sur 20 bars
POC_MIGRATION_ABS_MAX = 0.005           # M7 : |slope POC| < 0.005 (median=0, q75=0.005)
AGGRESSOR_MEAN_ABS_MAX = 0.10           # M8 : |mean(aggressor)| < 0.10 (two-sided flow)

# Seuils micro
RANGE_SIZE_ATR_MIN = 1.0
RANGE_SIZE_ATR_MAX = 5.0

# Seuils density extremes
DENSITY_MIN_ZONES = 2

# Verdict macro
MIN_MACRO_CRITERES_V3 = 4               # >= 4/7 (vs 2/3 V2)

# Range pos seuils signal hints
LOW_FADE_THRESHOLD = 0.30
HIGH_FADE_THRESHOLD = 0.70

# Color inversion seuils (range_break_risk)
INVERSION_LOW_ZONE = 0.40               # range_pos<0.40 = zone basse
INVERSION_HIGH_ZONE = 0.60              # range_pos>0.60 = zone haute
INVERSION_CLUSTER_MIN = 2               # >= 2 clusters required (not just >0) — density real
                                        # Audit V3 vs V2 07/05 : >0 declenche 67% bars (faux positifs)


# ─── Result struct ────────────────────────────────────────────────────────

@dataclass
class RangeResultV3:
    """Resultat detection V3 pour 1 fenetre."""

    is_range: bool = False
    is_range_macro: bool = False
    is_range_micro: bool = False

    # Geometrie (zones avec buffer, pas prix exacts)
    range_high_zone: Optional[float] = None         # quantile 95 + buffer ticks
    range_low_zone: Optional[float] = None          # quantile 5 - buffer ticks
    range_high_raw: Optional[float] = None          # max(highs) brut, audit only
    range_low_raw: Optional[float] = None           # min(lows) brut, audit only
    range_mid: Optional[float] = None
    range_size_ticks: Optional[float] = None         # zone width in ticks
    range_pos: Optional[float] = None                # 0 (low_zone) - 1 (high_zone)

    # M1-M3 macro V2 (heritage)
    adx: Optional[float] = None
    adx_ok: bool = False
    choppiness: Optional[float] = None
    chop_ok: bool = False
    atr_ratio: Optional[float] = None
    im_corr: Optional[float] = None
    contraction_ok: bool = False

    # M5-M8 macro V3 (NEW)
    bars_since_swing_high: Optional[int] = None
    bars_since_swing_low: Optional[int] = None
    swing_ok: bool = False                            # M5
    inside_va: Optional[int] = None
    va_width_atr_std: Optional[float] = None
    va_width_atr_mean: Optional[float] = None
    va_stable_ok: bool = False                        # M6
    poc_migration: Optional[float] = None
    poc_stable_ok: bool = False                       # M7
    aggressor_mean: Optional[float] = None
    aggressor_balanced_ok: bool = False               # M8

    n_macro_ok: int = 0                                # /7 V3 (vs /3 V2)

    # Micro criteres
    range_size_atr: Optional[float] = None
    geo_ok: bool = False
    no_breakout_ok: bool = False

    # Density extremes
    density_low: int = 0
    density_high: int = 0
    density_low_ok: bool = False
    density_high_ok: bool = False

    # Color inversion (NEW V3)
    color_dn_in_low_zone: int = 0                     # n_color_dn_cluster quand range_pos<0.40
    color_up_in_high_zone: int = 0                    # n_color_up_cluster quand range_pos>0.60
    long_dn_bar_in_low: bool = False                  # confirmation aggression vendeuse
    long_up_bar_in_high: bool = False                 # confirmation aggression acheteuse
    range_break_risk: str = "NONE"                    # "DOWN_BREAK_IMMINENT" | "UP_BREAK_IMMINENT" | "NONE"
    break_risk_confidence: str = "NONE"               # "HIGH" si LONG bar confirme | "MED"

    # Signal hint (PAS gating, juste tag)
    signal_hint: str = "NONE"

    # Diagnostic
    n_bars_used: int = 0
    reason: str = ""


# ─── Detector ──────────────────────────────────────────────────────────────

class RangeDetectorV3:
    """Detection range V3 hybride macro AMT + micro + density + color inversion.

    Usage :
        det = RangeDetectorV3(sym='NQ')
        result = det.detect(df)
        if result.is_range and result.signal_hint == "LONG_FADE_HINT":
            print(f"Fade low [{result.range_low_zone}-{result.range_high_zone}]")
        if result.range_break_risk != "NONE":
            print(f"WARNING: {result.range_break_risk} confidence={result.break_risk_confidence}")
    """

    REQUIRED_OHLC: Sequence[str] = ("high", "low", "close")
    OPTIONAL_FEATURES_V2: Sequence[str] = (
        "im_rolling_correlation_10",
        "n_color_up_cluster_within_0_2pct",
        "n_color_dn_cluster_within_0_2pct",
        "n_long_up_cluster_within_0_2pct",
        "n_long_dn_cluster_within_0_2pct",
        "n_edge_buy_active",
        "n_edge_sell_active",
    )
    OPTIONAL_FEATURES_V3: Sequence[str] = (
        "bars_since_last_swing_high",
        "bars_since_last_swing_low",
        "inside_value_area",
        "ctx_va_width_atr",
        "ctx_poc_migration_10",
        "aggressor_imbalance",
        "long_up_bar",
        "long_dn_bar",
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
        min_macro_criteres: int = MIN_MACRO_CRITERES_V3,
        buffer_ticks: Optional[int] = None,
        inversion_cluster_min: int = INVERSION_CLUSTER_MIN,
        # 11/05 v3.1 patches (market-analyst verdict) — defaults = comportement V3 inchange
        use_atr_macro: bool = False,
        use_close_breakout: bool = False,
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
        self.min_macro_criteres = min_macro_criteres
        self.atr_baseline_ticks = ATR_BASELINE_TICKS[sym]
        self.tick_size = TICK_SIZE[sym]
        self.buffer_ticks = buffer_ticks if buffer_ticks is not None else RANGE_BUFFER_TICKS[sym]
        self.inversion_cluster_min = inversion_cluster_min
        # 11/05 v3.1 patches : market-analyst verdict
        # - use_atr_macro : ATR Wilder n=14 sur 60 bars macro (au lieu de n=14 sur 20 micro)
        #   Fix bug GEO : range macro 60 bars / ATR micro 20 bars = ratio mecaniquement 8-12x
        #   = inatteignable seuil 5.0. ATR macro corrige sans changer seuils.
        # - use_close_breakout : NoBO check sur closes (au lieu de highs/lows)
        #   Tolere wicks (springs/upthrusts Wyckoff/AMT) = constitutif du range.
        #   Refuse vraie cassure (cloture au-dela borne).
        self.use_atr_macro = use_atr_macro
        self.use_close_breakout = use_close_breakout

    # ─── Helpers ───
    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_OHLC if c not in df.columns]
        if missing:
            raise ValueError(f"Colonnes OHLC manquantes: {missing}")

    def _compute_robust_extremes(self, df_window_macro: pd.DataFrame, result: RangeResultV3) -> None:
        """Bornes robustes range = quantile 5/95 +/- buffer ticks (zones, pas prix exacts).

        Observation Jackson 07/05 : les wicks ponctuels (3-4 ticks) ne doivent pas
        compter comme breakout. On utilise quantile pour ignorer 5% des extremes
        (wicks/spikes), puis on ajoute un buffer ticks pour creer une "zone".
        """
        highs = df_window_macro["high"].to_numpy(dtype=np.float64)
        lows = df_window_macro["low"].to_numpy(dtype=np.float64)
        closes = df_window_macro["close"].to_numpy(dtype=np.float64)

        # Bornes brutes (audit)
        result.range_high_raw = round(float(highs.max()), 4)
        result.range_low_raw = round(float(lows.min()), 4)

        # Bornes robustes : quantile + buffer
        q_high = float(np.quantile(highs, RANGE_QUANTILE_HIGH))
        q_low = float(np.quantile(lows, RANGE_QUANTILE_LOW))
        buffer_pts = self.buffer_ticks * self.tick_size
        range_high_zone = q_high + buffer_pts
        range_low_zone = q_low - buffer_pts

        result.range_high_zone = round(range_high_zone, 4)
        result.range_low_zone = round(range_low_zone, 4)
        result.range_mid = round((range_high_zone + range_low_zone) / 2.0, 4)

        zone_size = range_high_zone - range_low_zone
        if zone_size > 1e-9:
            result.range_size_ticks = round(zone_size / self.tick_size, 1)
            close_now = float(closes[-1])
            # Clip range_pos a [0, 1] pour gerer wicks > zones
            raw_pos = (close_now - range_low_zone) / zone_size
            result.range_pos = round(max(0.0, min(1.0, raw_pos)), 3)

    def _compute_macro_v2(self, df_window: pd.DataFrame, result: RangeResultV3) -> int:
        """M1-M3 macro V2 (ADX + Chop + contraction). Retourne nb criteres OK."""
        highs = df_window["high"].to_numpy(dtype=np.float64)
        lows = df_window["low"].to_numpy(dtype=np.float64)
        closes = df_window["close"].to_numpy(dtype=np.float64)

        atr_now = atr_wilder(highs, lows, closes, n=14)

        # M1 ADX
        adx_val = adx_wilder(highs, lows, closes, n=14)
        if not np.isnan(adx_val):
            result.adx = round(float(adx_val), 1)
            result.adx_ok = adx_val < self.adx_threshold

        # M2 Choppiness
        chop = choppiness_index(highs, lows, closes, n=14)
        if not np.isnan(chop):
            result.choppiness = round(float(chop), 1)
            result.chop_ok = chop > self.chop_threshold

        # M3 contraction (ATR ratio OR im_corr)
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

        return int(result.adx_ok) + int(result.chop_ok) + int(result.contraction_ok)

    def _compute_swing_structure(self, df_window: pd.DataFrame, result: RangeResultV3) -> bool:
        """M5 : bars_since_last_swing_high >= 30 AND bars_since_last_swing_low >= 30.

        Justification : si pivot recent (< 30 bars), structure pas tenue = trend ou
        breakout en formation. Median V4=26, q75=58.
        """
        if "bars_since_last_swing_high" not in df_window.columns or \
           "bars_since_last_swing_low" not in df_window.columns:
            return False

        last = df_window.iloc[-1]
        bsh = last.get("bars_since_last_swing_high")
        bsl = last.get("bars_since_last_swing_low")

        if pd.isna(bsh) or pd.isna(bsl):
            return False

        bsh_int = int(bsh)
        bsl_int = int(bsl)
        result.bars_since_swing_high = bsh_int
        result.bars_since_swing_low = bsl_int

        result.swing_ok = (bsh_int >= SWING_BARS_MIN) and (bsl_int >= SWING_BARS_MIN)
        return result.swing_ok

    def _compute_va_stability(self, df_window: pd.DataFrame, result: RangeResultV3) -> bool:
        """M6 : last(inside_value_area)==1 AND CV(va_width_atr[-20:]) < 20%.

        Justification : VA persistante session = balance area Dalton. Si VA s'elargit/
        retrecit drastiquement, equilibre rompu.
        """
        if "inside_value_area" not in df_window.columns or \
           "ctx_va_width_atr" not in df_window.columns:
            return False

        last = df_window.iloc[-1]
        iva = last.get("inside_value_area")
        if pd.isna(iva):
            return False
        result.inside_va = int(iva)

        # CV VA width sur 20 dernieres bars
        va_widths = df_window["ctx_va_width_atr"].iloc[-VA_STABILITY_LOOKBACK:].dropna()
        if len(va_widths) < VA_STABILITY_LOOKBACK // 2:
            return False

        mean_w = float(va_widths.mean())
        std_w = float(va_widths.std())
        result.va_width_atr_mean = round(mean_w, 3)
        result.va_width_atr_std = round(std_w, 3)

        if mean_w <= 1e-6:
            return False
        cv = std_w / mean_w

        result.va_stable_ok = (int(iva) == 1) and (cv < VA_WIDTH_STD_RATIO_MAX)
        return result.va_stable_ok

    def _compute_poc_stability(self, df_window: pd.DataFrame, result: RangeResultV3) -> bool:
        """M7 : abs(ctx_poc_migration_10) < 0.005.

        Justification : POC stable = pas de migration directionnelle = balance.
        Median V4=0, q75=0.005.
        """
        if "ctx_poc_migration_10" not in df_window.columns:
            return False

        last = df_window.iloc[-1]
        poc_mig = last.get("ctx_poc_migration_10")
        if pd.isna(poc_mig):
            return False

        poc_mig_f = float(poc_mig)
        result.poc_migration = round(poc_mig_f, 4)
        result.poc_stable_ok = abs(poc_mig_f) < POC_MIGRATION_ABS_MAX
        return result.poc_stable_ok

    def _compute_aggressor_balance(self, df_window: pd.DataFrame, result: RangeResultV3) -> bool:
        """M8 : abs(rolling_mean_30(aggressor_imbalance)) < 0.10.

        Justification : range = two-sided trading, aggression equilibree. Si
        deviation > 0.10, dominance directionnelle = trend ou breakout.
        """
        if "aggressor_imbalance" not in df_window.columns:
            return False

        agg_series = df_window["aggressor_imbalance"].iloc[-AGGRESSOR_LOOKBACK:].dropna()
        if len(agg_series) < AGGRESSOR_LOOKBACK // 2:
            return False

        mean_agg = float(agg_series.mean())
        result.aggressor_mean = round(mean_agg, 3)
        result.aggressor_balanced_ok = abs(mean_agg) < AGGRESSOR_MEAN_ABS_MAX
        return result.aggressor_balanced_ok

    def _compute_micro(self, df_window_micro: pd.DataFrame, result: RangeResultV3,
                        df_window_macro: Optional[pd.DataFrame] = None) -> None:
        """Micro : geometrie (range_size_atr) + no_breakout (sur zones, pas raw).

        Patches 11/05 v3.1 (market-analyst verdict) :
          - `use_atr_macro=True` : ATR n=14 sur df_window_macro (60 bars) au lieu
            de df_window_micro (20 bars). Fix bug GEO : range macro / ATR micro =
            ratio mecaniquement inatteignable.
          - `use_close_breakout=True` : NoBO check sur closes (au lieu high/low).
            Tolere wicks (springs/upthrusts Wyckoff/AMT) = constitutif du range.
        """
        if len(df_window_micro) < self.micro_lookback:
            return

        highs = df_window_micro["high"].to_numpy(dtype=np.float64)
        lows = df_window_micro["low"].to_numpy(dtype=np.float64)
        closes = df_window_micro["close"].to_numpy(dtype=np.float64)

        # PATCH 1 (use_atr_macro) : ATR sur fenetre macro pour mesurer vol contextuelle
        if self.use_atr_macro and df_window_macro is not None and len(df_window_macro) >= 15:
            highs_macro = df_window_macro["high"].to_numpy(dtype=np.float64)
            lows_macro = df_window_macro["low"].to_numpy(dtype=np.float64)
            closes_macro = df_window_macro["close"].to_numpy(dtype=np.float64)
            atr_now = atr_wilder(highs_macro, lows_macro, closes_macro, n=14)
        else:
            atr_now = atr_wilder(highs, lows, closes, n=14)

        if result.range_high_zone is not None and result.range_low_zone is not None:
            zone_size = result.range_high_zone - result.range_low_zone
            if not np.isnan(atr_now) and atr_now > 0 and zone_size > 0:
                range_size_atr = zone_size / atr_now
                result.range_size_atr = round(float(range_size_atr), 2)
                result.geo_ok = self.range_size_atr_min <= range_size_atr <= self.range_size_atr_max

        # No breakout sur les `no_breakout_lookback` dernieres bars : utilise zones
        # (range_high_zone / range_low_zone) qui contiennent deja le buffer.
        # PATCH 2 (use_close_breakout) : check sur closes (tolere wicks)
        nb = min(self.no_breakout_lookback, len(highs))
        if nb >= 5 and result.range_high_zone is not None and result.range_low_zone is not None:
            if self.use_close_breakout:
                recent_closes = closes[-nb:]
                no_high_break = float(recent_closes.max()) <= result.range_high_zone
                no_low_break = float(recent_closes.min()) >= result.range_low_zone
            else:
                recent_highs = highs[-nb:]
                recent_lows = lows[-nb:]
                no_high_break = float(recent_highs.max()) <= result.range_high_zone
                no_low_break = float(recent_lows.min()) >= result.range_low_zone
            result.no_breakout_ok = bool(no_high_break and no_low_break)

        result.is_range_micro = bool(result.geo_ok or result.no_breakout_ok)

    def _compute_density(self, df_window_micro: pd.DataFrame, result: RangeResultV3) -> None:
        """Density color/long/edge zones autour des extremes du range."""
        if result.range_pos is None:
            return

        last = df_window_micro.iloc[-1]

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

    def _compute_color_inversion(self, df_window_micro: pd.DataFrame, result: RangeResultV3) -> None:
        """Color inversion = signal cassure imminente (observation Jackson 07/05).

        Quand COLOR DN cluster apparait dans la zone basse (range_pos<0.40), c'est
        une penetration agressive vendeuse dans le camp acheteur = signal cassure
        baissiere. Confirmation HIGH si LONG DN bar dans la barre courante.
        Inverse pour cassure haussiere.
        """
        if result.range_pos is None:
            return

        last = df_window_micro.iloc[-1]

        # Cassure baissiere : color_dn dans zone basse
        if result.range_pos < INVERSION_LOW_ZONE:
            if "n_color_dn_cluster_within_0_2pct" in df_window_micro.columns:
                cdn = last.get("n_color_dn_cluster_within_0_2pct", 0)
                if pd.notna(cdn):
                    result.color_dn_in_low_zone = int(cdn)

            if result.color_dn_in_low_zone >= self.inversion_cluster_min:
                result.range_break_risk = "DOWN_BREAK_IMMINENT"
                # Confirmation par LONG DN bar
                if "long_dn_bar" in df_window_micro.columns:
                    ldn = last.get("long_dn_bar", 0)
                    if pd.notna(ldn) and int(ldn) == 1:
                        result.long_dn_bar_in_low = True
                        result.break_risk_confidence = "HIGH"
                    else:
                        result.break_risk_confidence = "MED"
                else:
                    result.break_risk_confidence = "MED"

        # Cassure haussiere : color_up dans zone haute
        elif result.range_pos > INVERSION_HIGH_ZONE:
            if "n_color_up_cluster_within_0_2pct" in df_window_micro.columns:
                cup = last.get("n_color_up_cluster_within_0_2pct", 0)
                if pd.notna(cup):
                    result.color_up_in_high_zone = int(cup)

            if result.color_up_in_high_zone >= self.inversion_cluster_min:
                result.range_break_risk = "UP_BREAK_IMMINENT"
                if "long_up_bar" in df_window_micro.columns:
                    lup = last.get("long_up_bar", 0)
                    if pd.notna(lup) and int(lup) == 1:
                        result.long_up_bar_in_high = True
                        result.break_risk_confidence = "HIGH"
                    else:
                        result.break_risk_confidence = "MED"
                else:
                    result.break_risk_confidence = "MED"

    def _final_verdict(self, result: RangeResultV3) -> None:
        """Verdict V3 :
            is_range_macro = n_macro_ok >= 4 sur 7
            is_range = is_range_macro AND (is_range_micro OR D1 OR D2)
                       AND range_break_risk == NONE   <- INVALIDE si cassure imminente

        Signal hint : NEVER emit fade hint si break_risk dans la meme direction
        (Jackson 07/05 : pattern color inversion invalide signal mean-reversion).
        """
        # Compte macro V3 : M1-M3 V2 deja calcules + M5/M6/M7/M8
        macro_count_v2 = int(result.adx_ok) + int(result.chop_ok) + int(result.contraction_ok)
        macro_count_v3 = (
            int(result.swing_ok)
            + int(result.va_stable_ok)
            + int(result.poc_stable_ok)
            + int(result.aggressor_balanced_ok)
        )
        result.n_macro_ok = macro_count_v2 + macro_count_v3
        result.is_range_macro = result.n_macro_ok >= self.min_macro_criteres

        # Verdict final : macro_ok AND (micro OR density) AND no break_risk
        result.is_range = bool(
            result.is_range_macro
            and (
                result.is_range_micro
                or result.density_low_ok
                or result.density_high_ok
            )
            and result.range_break_risk == "NONE"
        )

        # Signal hint : SUPPRIMER si break_risk meme direction
        hint = "NONE"
        if result.is_range and result.range_pos is not None:
            if result.range_pos <= LOW_FADE_THRESHOLD and result.density_low_ok:
                # LONG_FADE_HINT : fade depuis low → veut un rebond. Si DOWN_BREAK
                # en cours, ne PAS emit (on serait long contre cassure).
                if result.range_break_risk != "DOWN_BREAK_IMMINENT":
                    hint = "LONG_FADE_HINT"
            elif result.range_pos >= HIGH_FADE_THRESHOLD and result.density_high_ok:
                if result.range_break_risk != "UP_BREAK_IMMINENT":
                    hint = "SHORT_FADE_HINT"
        result.signal_hint = hint

        # Reason explicit (audit)
        ok = lambda b, name: name if b else f"!{name}"
        result.reason = (
            f"macro={result.n_macro_ok}/7"
            f"[{ok(result.adx_ok,'ADX')},{ok(result.chop_ok,'CHOP')},{ok(result.contraction_ok,'CTR')},"
            f"{ok(result.swing_ok,'SWING')},{ok(result.va_stable_ok,'VA')},"
            f"{ok(result.poc_stable_ok,'POC')},{ok(result.aggressor_balanced_ok,'AGG')}] "
            f"micro=[{ok(result.geo_ok,'GEO')},{ok(result.no_breakout_ok,'NoBO')}] "
            f"dens=[L{result.density_low}/H{result.density_high}] "
            f"pos={result.range_pos} "
            f"break_risk={result.range_break_risk}({result.break_risk_confidence}) "
            f"hint={result.signal_hint}"
        )

    # ─── API publique ───
    def detect(self, df: pd.DataFrame) -> RangeResultV3:
        """Detect range V3 sur les bars fournies (au moins macro_lookback rows)."""
        self._validate_input(df)
        result = RangeResultV3()

        if len(df) < self.macro_lookback:
            result.reason = f"insufficient_bars_{len(df)}_lt_{self.macro_lookback}"
            return result

        # Window macro (60 bars)
        df_macro = df.iloc[-self.macro_lookback:]
        result.n_bars_used = len(df_macro)

        # Bornes robustes (zones avec buffer) — DOIT etre fait avant micro
        self._compute_robust_extremes(df_macro, result)

        # M1-M3 V2
        self._compute_macro_v2(df_macro, result)

        # M5-M8 V3 (AMT)
        self._compute_swing_structure(df_macro, result)
        self._compute_va_stability(df_macro, result)
        self._compute_poc_stability(df_macro, result)
        self._compute_aggressor_balance(df_macro, result)

        # Window micro (20 bars)
        df_micro = df.iloc[-self.micro_lookback:]
        # Patch 11/05 v3.1 : passer df_macro pour ATR macro si use_atr_macro=True
        self._compute_micro(df_micro, result, df_window_macro=df_macro)
        self._compute_density(df_micro, result)
        self._compute_color_inversion(df_micro, result)

        # Verdict final + hint
        self._final_verdict(result)
        return result

    def detect_iterative(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pour chaque bar i, detect range sur la fenetre [i-macro_lookback+1, i]."""
        self._validate_input(df)
        n = len(df)

        out = {
            "is_range": [False] * n,
            "is_range_macro": [False] * n,
            "is_range_micro": [False] * n,
            "range_high_zone": [np.nan] * n,
            "range_low_zone": [np.nan] * n,
            "range_pos": [np.nan] * n,
            "adx": [np.nan] * n,
            "choppiness": [np.nan] * n,
            "atr_ratio": [np.nan] * n,
            "im_corr": [np.nan] * n,
            "range_size_atr": [np.nan] * n,
            "n_macro_ok": [0] * n,
            "swing_ok": [False] * n,
            "va_stable_ok": [False] * n,
            "poc_stable_ok": [False] * n,
            "aggressor_balanced_ok": [False] * n,
            "density_low": [0] * n,
            "density_high": [0] * n,
            "range_break_risk": ["NONE"] * n,
            "break_risk_confidence": ["NONE"] * n,
            "signal_hint": ["NONE"] * n,
        }

        for i in range(self.macro_lookback - 1, n):
            window = df.iloc[i - self.macro_lookback + 1: i + 1]
            r = self.detect(window)
            out["is_range"][i] = r.is_range
            out["is_range_macro"][i] = r.is_range_macro
            out["is_range_micro"][i] = r.is_range_micro
            out["range_high_zone"][i] = r.range_high_zone if r.range_high_zone is not None else np.nan
            out["range_low_zone"][i] = r.range_low_zone if r.range_low_zone is not None else np.nan
            out["range_pos"][i] = r.range_pos if r.range_pos is not None else np.nan
            out["adx"][i] = r.adx if r.adx is not None else np.nan
            out["choppiness"][i] = r.choppiness if r.choppiness is not None else np.nan
            out["atr_ratio"][i] = r.atr_ratio if r.atr_ratio is not None else np.nan
            out["im_corr"][i] = r.im_corr if r.im_corr is not None else np.nan
            out["range_size_atr"][i] = r.range_size_atr if r.range_size_atr is not None else np.nan
            out["n_macro_ok"][i] = r.n_macro_ok
            out["swing_ok"][i] = r.swing_ok
            out["va_stable_ok"][i] = r.va_stable_ok
            out["poc_stable_ok"][i] = r.poc_stable_ok
            out["aggressor_balanced_ok"][i] = r.aggressor_balanced_ok
            out["density_low"][i] = r.density_low
            out["density_high"][i] = r.density_high
            out["range_break_risk"][i] = r.range_break_risk
            out["break_risk_confidence"][i] = r.break_risk_confidence
            out["signal_hint"][i] = r.signal_hint

        df_out = df.copy()
        for k, v in out.items():
            df_out[k] = v
        return df_out
