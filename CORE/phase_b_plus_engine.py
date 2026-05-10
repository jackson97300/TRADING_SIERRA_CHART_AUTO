"""
phase_b_plus_engine.py — Phase B+ P1 : reproduction features SC OHLC-only.

Reproduit en Python pur les etudes Sierra Chart visuelles que Jackson utilise
manuellement. Toutes les formules sont basees sur l'audit
DOCS/AUDIT_SC_STUDIES_REPRODUCTIBLE.md + DOCS/FORMULES_FEATURES_PHASE_B_PLUS.md.

Categories :
  A. Color Up/Down + variantes 2 (formule O[1]>C, H[1]>L+40t, H[1]>H)
  B. Long Up/Down Bar (body >= 9 ticks)
  C. Long Up Down / Down Up Bar (rejection patterns 3 bars)
  D. Volume spike Up/Down (vol > 2x MA20 + direction)
  E. VWAP daily + SD bands (anchored cumsum sur typical price)
  F. VWAP weekly + SD bands
  G. OVN high/low (overnight session 18:00 ET veille -> 09:30 ET J)
  H. Opens 08:30 / 09:30 (futures + cash)
  I. News flags temporels (07:15, 07:30, 08:30, 08:45, 09:00, 09:30 ET)

Inputs : OHLC + volume + ts_event UTC (deja dans v4_enriched).
Outputs : ~50 nouvelles colonnes ML-usable (apres screening Spearman).

LOOKAHEAD WARNING :
  - Color Up/Down + Long Up Down/Down Up utilisent O[1] et H[1] (barre future).
  - Sur historique : OK (data future disponible).
  - En LIVE : decalage 1 bar inevitable. Marquage explicit via suffixe '_lag1'
    NON applique ici (Jackson valide demain). Pour ML training shift +1 si besoin.

Auteur : Phase B+ Session 1 (2026-04-26)
"""
from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer

# Import constants per-symbole (try/except pour 2 conventions sys.path :
# bot launching depuis ROOT/ vs bot legacy depuis CORE/)
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:  # noqa: F401
    from constants import get_tick_size as _get_tick_size

ET = ZoneInfo("America/New_York")
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick via apply_phase_b_plus(symbol)


# ═══════════════════════════════════════════════════════════════════════════════
# A. COLOR UP / COLOR DOWN
# ═══════════════════════════════════════════════════════════════════════════════

COLOR_THRESHOLD_TICKS = {
    "ES": 12,   # SC formules officielles Jackson 26/04/2026
    # FIX 27/04 (audit ULTRATHINK + market-analyst rescue) :
    # NQ avant=40 (ratio fuite n_color_up/dn_zones_active NQ/ES = 3.18).
    # NQ apres=60 (cible fire ratio NQ/ES < 1.5).
    "NQ": 60,   # AVANT 40
}


def add_color_features(df: pd.DataFrame, symbol: str = "ES",
                        tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    SC formules officielles Jackson 26/04 :
      ES Chart 1 ID 56/57/104/105 + NQ Chart 2 ID 53/54/3/5
      Threshold per-symbole : ES=12t (3pts) / NQ=40t (10pts)

    COLOR UP    = AND(O[1]>C, H[1]>L+TICKSIZE*N, H[1]>H)
    COLOR DOWN  = AND(O[1]<C, H>L[1]+TICKSIZE*N, L[1]<L)

    COLOR UP 2  = AND(
                    O[1]>C, H[1]>L+TICKSIZE*N, H[1]>H,                  # Bloc 1: COLOR UP sur bar i
                    O[-1]>C[-2], H[-1]>L[-2]+TICKSIZE*N, H[-1]>H[-2],   # Bloc 2: COLOR UP sur bar i-2 (referencant i-1)
                    L>L[-1]                                              # Bloc 3: continuation up
                  )

    COLOR DOWN 2 = AND(
                    O[1]<C, H>L[1]+TICKSIZE*N, L[1]<L,                   # Bloc 1: COLOR DOWN sur bar i
                    O[-1]<C[-2], H[-2]>L[-1]+TICKSIZE*N, L[-1]<L[-2],    # Bloc 2: COLOR DOWN sur bar i-2
                    H<H[-1]                                              # Bloc 3: continuation down
                  )

    SUFFIX `_fwd1` = LOOKAHEAD : utilise O[1], H[1], L[1] = barre i+1 (futur).
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold_ticks = COLOR_THRESHOLD_TICKS.get(sym, 40)
    threshold = threshold_ticks * tick

    o_curr, c_curr, h_curr, l_curr = df["open"], df["close"], df["high"], df["low"]
    o_next, h_next, l_next = o_curr.shift(-1), h_curr.shift(-1), l_curr.shift(-1)   # i+1
    o_prev, c_prev, h_prev, l_prev = o_curr.shift(1), c_curr.shift(1), h_curr.shift(1), l_curr.shift(1)   # i-1
    c_prev2, h_prev2, l_prev2 = c_curr.shift(2), h_curr.shift(2), l_curr.shift(2)    # i-2

    # COLOR UP : O[1]>C, H[1]>L+threshold, H[1]>H
    color_up_curr = (
        (o_next > c_curr) &
        (h_next > l_curr + threshold) &
        (h_next > h_curr)
    )
    df["bn_color_up_fwd1"] = color_up_curr.fillna(False).astype("int8")

    # COLOR DOWN : O[1]<C, H>L[1]+threshold, L[1]<L
    # Note: H > L[1]+t equivaut a L[1] < H-t (formule originale Jackson preferee)
    color_dn_curr = (
        (o_next < c_curr) &
        (h_curr > l_next + threshold) &
        (l_next < l_curr)
    )
    df["bn_color_dn_fwd1"] = color_dn_curr.fillna(False).astype("int8")

    # COLOR UP 2 : Bloc 1 (i, i+1) AND Bloc 2 (i-2, i-1) AND L>L[-1]
    # Bloc 2 = COLOR UP standard evalue sur bar i-2 :
    #   O[k+1]>C[k] avec k=-2 -> O[-1]>C[-2] (open i-1 > close i-2)
    #   H[k+1]>L[k]+threshold avec k=-2 -> H[-1]>L[-2]+threshold
    #   H[k+1]>H[k] avec k=-2 -> H[-1]>H[-2]
    color_up_at_i_minus_2 = (
        (o_prev > c_prev2) &
        (h_prev > l_prev2 + threshold) &
        (h_prev > h_prev2)
    )
    df["bn_color_up_2_fwd1"] = (
        color_up_curr & color_up_at_i_minus_2 & (l_curr > l_prev)
    ).fillna(False).astype("int8")

    # COLOR DOWN 2 : Bloc 1 (i, i+1) AND Bloc 2 (i-2, i-1) AND H<H[-1]
    # Bloc 2 = COLOR DOWN standard evalue sur bar i-2 :
    #   O[k+1]<C[k] avec k=-2 -> O[-1]<C[-2]
    #   H[k]>L[k+1]+threshold avec k=-2 -> H[-2]>L[-1]+threshold (notation Jackson)
    #   L[k+1]<L[k] avec k=-2 -> L[-1]<L[-2]
    color_dn_at_i_minus_2 = (
        (o_prev < c_prev2) &
        (h_prev2 > l_prev + threshold) &
        (l_prev < l_prev2)
    )
    df["bn_color_dn_2_fwd1"] = (
        color_dn_curr & color_dn_at_i_minus_2 & (h_curr < h_prev)
    ).fillna(False).astype("int8")

    return df


def add_color_extension_lines(df: pd.DataFrame, cluster_pct: float = 0.2) -> pd.DataFrame:
    """
    Reproduit la mecanique SC `Draw Extension Lines at Color Bar Value = Extend to Future Inters`.

    Pour chaque COLOR UP fire bar i : trace une zone (ligne) au LOW de cette bar.
    Pour chaque COLOR DOWN fire bar i : trace une zone au HIGH de cette bar.
    La zone reste active jusqu'a ce qu'un bar futur la touche (overlap).

    Cluster logic (Jackson 27/04/2026) : zones non-touchees groupees pres du prix
    courant = niveau de support/resistance puissant. Capture via cluster_within_pct.

    Args:
        df: DataFrame avec ts_event, high, low, close + bn_color_up_fwd1 + bn_color_dn_fwd1
        cluster_pct: range autour du close (en %) pour cluster local (default 0.2%)

    Adds 6 features :
      n_color_up_zones_active, n_color_dn_zones_active : count zones non-touchees
      dist_color_up_nearest_pct, dist_color_dn_nearest_pct : distance signed close vers zone (en %)
      n_color_up_cluster_within_0_2pct, n_color_dn_cluster_within_0_2pct : count cluster local
    """
    df = df.copy()
    n = len(df)
    buf_up = ExtensionLineBuffer()
    buf_dn = ExtensionLineBuffer()

    n_up_active = np.zeros(n, dtype=np.int32)
    n_dn_active = np.zeros(n, dtype=np.int32)
    dist_up_nearest = np.full(n, np.nan, dtype=np.float64)
    dist_dn_nearest = np.full(n, np.nan, dtype=np.float64)
    n_up_cluster = np.zeros(n, dtype=np.int32)
    n_dn_cluster = np.zeros(n, dtype=np.int32)

    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values
    fire_up = df["bn_color_up_fwd1"].values
    fire_dn = df["bn_color_dn_fwd1"].values

    for i in range(n):
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        close = close_arr[i]

        # 1. UPDATE buffers : deactivate zones touchees par ce bar
        buf_up.update_with_bar(i, bar_low, bar_high)
        buf_dn.update_with_bar(i, bar_low, bar_high)

        # 2. ADD nouvelle zone si fire ce bar
        # COLOR UP : zone au LOW de la bar (support)
        if fire_up[i] == 1:
            buf_up.add_zone(i, [float(bar_low)], "buy")
        # COLOR DOWN : zone au HIGH (resistance)
        if fire_dn[i] == 1:
            buf_dn.add_zone(i, [float(bar_high)], "sell")

        # 3. FEATURES count + nearest + cluster
        n_up_active[i] = buf_up.count_active("buy")
        n_dn_active[i] = buf_dn.count_active("sell")

        d_up = buf_up.nearest_distance("buy", close)
        d_dn = buf_dn.nearest_distance("sell", close)
        if not np.isnan(d_up) and close > 0:
            dist_up_nearest[i] = (d_up / close) * 100
        if not np.isnan(d_dn) and close > 0:
            dist_dn_nearest[i] = (d_dn / close) * 100

        # Cluster : count zones actives dans [close*(1-pct/100), close*(1+pct/100)]
        cluster_range = close * (cluster_pct / 100)
        cluster_low = close - cluster_range
        cluster_high = close + cluster_range
        n_up_cluster[i] = sum(
            1 for z in buf_up.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        n_dn_cluster[i] = sum(
            1 for z in buf_dn.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    df["n_color_up_zones_active"] = n_up_active
    df["n_color_dn_zones_active"] = n_dn_active
    df["dist_color_up_nearest_pct"] = dist_up_nearest
    df["dist_color_dn_nearest_pct"] = dist_dn_nearest
    df["n_color_up_cluster_within_0_2pct"] = n_up_cluster
    df["n_color_dn_cluster_within_0_2pct"] = n_dn_cluster
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# B. LONG UP / DOWN BAR
# ═══════════════════════════════════════════════════════════════════════════════

LONG_BAR_THRESHOLD_TICKS = {
    "ES": 12,   # SC formules officielles Jackson 27/04/2026
    "NQ": 24,   # NQ x2 ES (volatilite)
}


def add_long_bar_features(df: pd.DataFrame, symbol: str = "ES",
                           tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    SC formules officielles Jackson 27/04 :
      ES Chart 1 ID 21/22 + NQ Chart 2 ID 23/24
      Threshold per-symbole : ES=12t (3pts) / NQ=24t (6pts)

    LONG UP   = AND(O > C[-1], H > L[-1] + TICKSIZE*N)
    LONG DOWN = AND(O < C[-1], H[-1] > L + TICKSIZE*N)

    Utilise uniquement [-1] et current -> PAS de lookahead.
    Pas de suffix _fwd1.

    BUG corrige : avant je calculais |close-open| >= 9t (taille body),
    formule completement differente de la vraie SC qui mesure range
    H-L[-1] (UP) ou H[-1]-L (DOWN) avec threshold per-symbole.
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold_ticks = LONG_BAR_THRESHOLD_TICKS.get(sym, 24)
    threshold = threshold_ticks * tick

    o_curr, h_curr, l_curr = df["open"], df["high"], df["low"]
    c_prev = df["close"].shift(1)
    h_prev = df["high"].shift(1)
    l_prev = df["low"].shift(1)

    # LONG UP : O > C[-1] AND H > L[-1] + threshold
    df["long_up_bar"] = (
        (o_curr > c_prev) &
        (h_curr > l_prev + threshold)
    ).fillna(False).astype("int8")

    # LONG DOWN : O < C[-1] AND H[-1] > L + threshold
    # (equivalent a L < H[-1] - threshold)
    df["long_dn_bar"] = (
        (o_curr < c_prev) &
        (h_prev > l_curr + threshold)
    ).fillna(False).astype("int8")

    # Helper feature : body en ticks (peut servir au ML comme info complementaire)
    df["bar_body_ticks"] = ((df["close"] - df["open"]).abs() / tick).round().astype("float64")
    # Helper : range bar courant vs bar precedent en ticks
    df["range_h_minus_lprev_ticks"] = ((h_curr - l_prev) / tick).round().astype("float64")
    df["range_hprev_minus_l_ticks"] = ((h_prev - l_curr) / tick).round().astype("float64")
    return df


def add_long_extension_lines(df: pd.DataFrame, cluster_pct: float = 0.2) -> pd.DataFrame:
    """
    Reproduit la mecanique SC `Draw Extension Lines at Long Up/Down Bar = Extend to Future Inters`.

    Pour chaque LONG UP fire bar i : trace une zone (ligne) au LOW de cette bar (support).
    Pour chaque LONG DOWN fire bar i : trace une zone au HIGH de cette bar (resistance).
    La zone reste active jusqu'a ce qu'un bar futur la touche (overlap H/L).

    Logique trading manuel Jackson : Long Up/Dn Bar (range >= threshold) cree une
    zone de demande/offre institutionnelle. Une fois touchee, elle "meurt" — la
    valeur edge est dans le RETEST avant invalidation, pas dans le pulse 1-bar.

    Args:
        df: DataFrame avec ts_event, high, low, close + long_up_bar + long_dn_bar
        cluster_pct: range autour du close (en %) pour cluster local (default 0.2%)

    Adds 6 features :
      n_long_up_zones_active, n_long_dn_zones_active : count zones non-touchees
      dist_long_up_nearest_pct, dist_long_dn_nearest_pct : distance signed close vers zone (%)
      n_long_up_cluster_within_0_2pct, n_long_dn_cluster_within_0_2pct : count cluster local
    """
    df = df.copy()
    n = len(df)
    buf_up = ExtensionLineBuffer()
    buf_dn = ExtensionLineBuffer()

    n_up_active = np.zeros(n, dtype=np.int32)
    n_dn_active = np.zeros(n, dtype=np.int32)
    dist_up_nearest = np.full(n, np.nan, dtype=np.float64)
    dist_dn_nearest = np.full(n, np.nan, dtype=np.float64)
    n_up_cluster = np.zeros(n, dtype=np.int32)
    n_dn_cluster = np.zeros(n, dtype=np.int32)

    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values
    fire_up = df["long_up_bar"].values if "long_up_bar" in df.columns else np.zeros(n)
    fire_dn = df["long_dn_bar"].values if "long_dn_bar" in df.columns else np.zeros(n)

    for i in range(n):
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        close = close_arr[i]

        buf_up.update_with_bar(i, bar_low, bar_high)
        buf_dn.update_with_bar(i, bar_low, bar_high)

        if fire_up[i] == 1:
            buf_up.add_zone(i, [float(bar_low)], "buy")
        if fire_dn[i] == 1:
            buf_dn.add_zone(i, [float(bar_high)], "sell")

        n_up_active[i] = buf_up.count_active("buy")
        n_dn_active[i] = buf_dn.count_active("sell")

        d_up = buf_up.nearest_distance("buy", close)
        d_dn = buf_dn.nearest_distance("sell", close)
        if not np.isnan(d_up) and close > 0:
            dist_up_nearest[i] = (d_up / close) * 100
        if not np.isnan(d_dn) and close > 0:
            dist_dn_nearest[i] = (d_dn / close) * 100

        cluster_range = close * (cluster_pct / 100)
        cluster_low = close - cluster_range
        cluster_high = close + cluster_range
        n_up_cluster[i] = sum(
            1 for z in buf_up.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        n_dn_cluster[i] = sum(
            1 for z in buf_dn.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    df["n_long_up_zones_active"] = n_up_active
    df["n_long_dn_zones_active"] = n_dn_active
    df["dist_long_up_nearest_pct"] = dist_up_nearest
    df["dist_long_dn_nearest_pct"] = dist_dn_nearest
    df["n_long_up_cluster_within_0_2pct"] = n_up_cluster
    df["n_long_dn_cluster_within_0_2pct"] = n_dn_cluster
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# C. LONG UP DOWN / DOWN UP BAR (rejection 3-bar patterns)
# ═══════════════════════════════════════════════════════════════════════════════

LONG_UPDN_THRESHOLD_TICKS = {
    "ES": 9,    # Chart 25 ES ID 38/39 (formule AVEC [1] lookahead)
    "NQ": 40,   # Chart 23 NQ ID 23/24 (formule SANS lookahead, decale 1 bar)
}


def add_long_updown_features(df: pd.DataFrame, symbol: str = "ES",
                              tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    SC formules officielles Jackson 27/04 — DIFFERENTES per-symbole :

    ES (Chart 25 ID 38/39, threshold 9 ticks) AVEC LOOKAHEAD [1] :
      LONG DOWN UP = AND(O<C[-1], H[-1]>L+9t, O[1]>C, H[1]>L+9t, H[1]>H[-1])
      LONG UP DOWN = AND(O>C[-1], H>L[-1]+9t, O[1]<C, H>L[1]+9t, L[1]<L[-1])
      Pattern bars (i-1, i, i+1) evalue sur barre i.
      LIVE : marker apparait avec 1 bar delay (apres cloture i+1).

    NQ (Chart 23 ID 23/24, threshold 40 ticks) SANS LOOKAHEAD :
      LONG DOWN UP = AND(O[-1]<C[-2], H[-2]>L[-1]+40t, O>C[-1], H>L[-1]+40t, H>H[-1])
      LONG UP DOWN = AND(O[-1]>C[-2], H[-1]>L[-2]+40t, O<C[-1], H[-1]>L+40t, L<L[-1])
      Pattern bars (i-2, i-1, i) evalue sur barre i.
      LIVE : marker apparait immediatement.

    Output : long_dn_up_pattern, long_up_dn_pattern (nom unique, formule per-symbole).
    LIVE warning ES : shift +1 bar avant ML training pour eviter biais.
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold_ticks = LONG_UPDN_THRESHOLD_TICKS.get(sym, 40)
    threshold = threshold_ticks * tick

    o_curr, h_curr, l_curr, c_curr = df["open"], df["high"], df["low"], df["close"]
    o_prev = df["open"].shift(1); c_prev = df["close"].shift(1)
    h_prev = df["high"].shift(1); l_prev = df["low"].shift(1)
    c_prev2 = df["close"].shift(2); h_prev2 = df["high"].shift(2); l_prev2 = df["low"].shift(2)
    o_next = df["open"].shift(-1); c_next = df["close"].shift(-1)
    h_next = df["high"].shift(-1); l_next = df["low"].shift(-1)

    if sym == "ES":
        # ES formule AVEC lookahead [1]
        # LONG DOWN UP : O<C[-1], H[-1]>L+9t, O[1]>C, H[1]>L+9t, H[1]>H[-1]
        long_dn_up = (
            (o_curr < c_prev) &
            (h_prev > l_curr + threshold) &
            (o_next > c_curr) &
            (h_next > l_curr + threshold) &
            (h_next > h_prev)
        )
        # LONG UP DOWN : O>C[-1], H>L[-1]+9t, O[1]<C, H>L[1]+9t, L[1]<L[-1]
        long_up_dn = (
            (o_curr > c_prev) &
            (h_curr > l_prev + threshold) &
            (o_next < c_curr) &
            (h_curr > l_next + threshold) &
            (l_next < l_prev)
        )
    else:  # NQ formule SANS lookahead
        # LONG DOWN UP : O[-1]<C[-2], H[-2]>L[-1]+40t, O>C[-1], H>L[-1]+40t, H>H[-1]
        long_dn_up = (
            (o_prev < c_prev2) &
            (h_prev2 > l_prev + threshold) &
            (o_curr > c_prev) &
            (h_curr > l_prev + threshold) &
            (h_curr > h_prev)
        )
        # LONG UP DOWN : O[-1]>C[-2], H[-1]>L[-2]+40t, O<C[-1], H[-1]>L+40t, L<L[-1]
        long_up_dn = (
            (o_prev > c_prev2) &
            (h_prev > l_prev2 + threshold) &
            (o_curr < c_prev) &
            (h_prev > l_curr + threshold) &
            (l_curr < l_prev)
        )

    df["long_dn_up_pattern"] = long_dn_up.fillna(False).astype("int8")
    df["long_up_dn_pattern"] = long_up_dn.fillna(False).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# D. VOLUME SPIKE UP / DOWN
# ═══════════════════════════════════════════════════════════════════════════════

VOLUME_THRESHOLD = {
    "ES": 1200,   # Chart 1 ES ID 2/4 (formule officielle Jackson 27/04)
    "NQ": 400,    # Chart 2 NQ ID 35/36 (NQ x3 moins ES car contrat plus gros)
}


def add_volume_spike_features(df: pd.DataFrame, symbol: str = "ES",
                               window: int = 20) -> pd.DataFrame:
    """
    SC formules officielles Jackson 27/04 :
      ES Chart 1 ID 2/4   threshold V > 1200 contracts
      NQ Chart 2 ID 35/36 threshold V > 400 contracts

    VOLUME UP   = AND(O > C[-1], V > threshold)
    VOLUME DOWN = AND(O < C[-1], V > threshold)

    Pas de lookahead (utilise [-1] et current).
    Pas de check direction (close > open).

    BUG corrige : avant je calculais V > MA20*2 + close>open, completement different.

    + helper vol_zscore_20 conserve (z-score 20 bars, info complementaire ML).
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold = VOLUME_THRESHOLD.get(sym, 400)

    o_curr = df["open"]
    c_prev = df["close"].shift(1)
    v = df["volume"]

    df["vol_spike_up"] = (
        (o_curr > c_prev) & (v > threshold)
    ).fillna(False).astype("int8")
    df["vol_spike_dn"] = (
        (o_curr < c_prev) & (v > threshold)
    ).fillna(False).astype("int8")

    # Helper z-score 20 bars (signal complementaire pour ML)
    vol_ma = v.rolling(window, min_periods=5).mean()
    vol_std = v.rolling(window, min_periods=5).std()
    df["vol_zscore_20"] = ((v - vol_ma) / vol_std.replace(0, np.nan)).clip(-5, 5)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# E. ROTATION UP / DOWN (Chart 1 ES ID 19/20 + Chart 2 NQ ID 21/22)
# ═══════════════════════════════════════════════════════════════════════════════

def add_rotation_features(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    SC formules officielles Jackson 27/04 (MEME formule ES + NQ, pas de threshold) :
      ES Chart 1 ID 19/20 + NQ Chart 2 ID 21/22

    ROTATION UP   = AND(O > C[-1], H > H[-2])
    ROTATION DOWN = AND(O < C[-1], L < L[-2])

    Pas de lookahead (utilise [-1] et [-2]).
    Pas d'Extension Lines (Draw Extension Lines = None dans inputs SC).

    Logique : breakout swing recent (depasse high/low de 2 bars en arriere).
    """
    df = df.copy()
    o_curr, h_curr, l_curr = df["open"], df["high"], df["low"]
    c_prev = df["close"].shift(1)
    h_prev2 = df["high"].shift(2)
    l_prev2 = df["low"].shift(2)

    df["rotation_up"] = (
        (o_curr > c_prev) & (h_curr > h_prev2)
    ).fillna(False).astype("int8")
    df["rotation_dn"] = (
        (o_curr < c_prev) & (l_curr < l_prev2)
    ).fillna(False).astype("int8")
    return df


# NOTE Bloc 3 #8 Swing : DEPLACE dans CORE/sessions_swings_engine.py
# (add_swing_features_v2 + add_session_metadata_v2 + add_session_highs_lows + add_session_opens
#  + add_liquidity_sweep + add_equal_swings + add_premium_discount)
# Pipeline : appele via apply_sessions_swings(df, symbol) APRES apply_phase_b_plus_plus.


# ═══════════════════════════════════════════════════════════════════════════════
# E. VWAP DAILY + SD BANDS
# ═══════════════════════════════════════════════════════════════════════════════

def _add_vwap_anchored(df: pd.DataFrame, anchor_col: str, suffix: str) -> pd.DataFrame:
    """Helper: anchored VWAP + SD bands (cumul reset par valeur de anchor_col)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = (typical * df["volume"]).groupby(df[anchor_col]).cumsum()
    cv = df["volume"].groupby(df[anchor_col]).cumsum()
    vwap = (pv / cv.replace(0, np.nan)).astype("float64")
    df[f"vwap_{suffix}"] = vwap

    # Anchored SD : Var = sum((p-vwap)^2 * v) / sum(v)
    sq_diff = (typical - vwap) ** 2 * df["volume"]
    sq_cum = sq_diff.groupby(df[anchor_col]).cumsum()
    var_anchored = sq_cum / cv.replace(0, np.nan)
    sd = np.sqrt(var_anchored.clip(lower=0))

    for n in (1, 2, 3):
        df[f"vwap_{suffix}_sd{n}u"] = vwap + n * sd
        df[f"vwap_{suffix}_sd{n}d"] = vwap - n * sd

    df[f"dist_vwap_{suffix}_pct"] = ((df["close"] - vwap) / df["close"] * 100).astype("float32")
    df[f"dist_vwap_{suffix}_sd1u_pct"] = ((df["close"] - df[f"vwap_{suffix}_sd1u"]) / df["close"] * 100).astype("float32")
    df[f"dist_vwap_{suffix}_sd1d_pct"] = ((df["close"] - df[f"vwap_{suffix}_sd1d"]) / df["close"] * 100).astype("float32")
    df[f"dist_vwap_{suffix}_sd2u_pct"] = ((df["close"] - df[f"vwap_{suffix}_sd2u"]) / df["close"] * 100).astype("float32")
    df[f"dist_vwap_{suffix}_sd2d_pct"] = ((df["close"] - df[f"vwap_{suffix}_sd2d"]) / df["close"] * 100).astype("float32")
    return df


def add_vwap_features(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP daily + weekly + monthly + SD bands + cross/sd1_above derivees."""
    df = df.copy()
    if "date_et" not in df.columns:
        ts_et = df["ts_event"].dt.tz_convert(ET) if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
        df["date_et"] = ts_et.dt.date
    df = _add_vwap_anchored(df, "date_et", "d")

    # Weekly anchor : ISO week+year
    ts_et = df["ts_event"].dt.tz_convert(ET) if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
    iso = ts_et.dt.isocalendar()
    df["week_anchor"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    df = _add_vwap_anchored(df, "week_anchor", "w")
    df.drop(columns=["week_anchor"], inplace=True)

    # Monthly anchor : year-month
    df["month_anchor"] = ts_et.dt.to_period("M").astype(str)
    df = _add_vwap_anchored(df, "month_anchor", "m")
    df.drop(columns=["month_anchor"], inplace=True)

    # F.2 VWAP cross + sd1 above/below (booleens)
    # cross_up : close passe au-dessus de vwap_d apres etre en dessous
    above_d = df["close"] > df["vwap_d"]
    df["vwap_d_cross_up"] = (above_d & ~above_d.shift(1).fillna(above_d)).astype("int8")
    df["vwap_d_cross_dn"] = (~above_d & above_d.shift(1).fillna(~above_d)).astype("int8")
    df["vwap_d_sd1_above"] = (df["close"] > df["vwap_d_sd1u"]).astype("int8")
    df["vwap_d_sd1_below"] = (df["close"] < df["vwap_d_sd1d"]).astype("int8")
    df["vwap_d_sd2_above"] = (df["close"] > df["vwap_d_sd2u"]).astype("int8")
    df["vwap_d_sd2_below"] = (df["close"] < df["vwap_d_sd2d"]).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# F. OVN HIGH / LOW (overnight session 18:00 ET veille -> 09:30 ET J)
# ═══════════════════════════════════════════════════════════════════════════════

def add_ovn_features(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """OVN range = session pre-cash. Reset chaque jour a 09:30 ET.

    FIX 27/04 (anti-leak) : ovn_high/low broadcast par session a TOUTES les bars
    du jour de trading creait un look-ahead massif (bar OVN active voyait MAX
    futur de toute la session OVN). Solution : masker la valeur a NaN pendant
    la session OVN active. Disponible seulement a partir de 09:30 ET (post-OVN).

    Detection bug : SHAP analysis 27/04 -> dist_ovn_high_pct domine 4× #2 SHAP.
    Confirmation empirique : bar 04:00 ET 2025-08-19, ovn_high broadcast = 6477.5
    alors que running_max(high) jusqu'a cette bar = 6460.25 (17.25 pts dans futur).
    Voir DOCS/INCIDENT_LOG.md 2026-04-27 20:30.
    """
    df = df.copy()
    ts_et = df["ts_event"].dt.tz_convert(ET) if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
    df["mins_et_loc"] = ts_et.dt.hour * 60 + ts_et.dt.minute
    df["date_et_loc"] = ts_et.dt.date

    # Session OVN = mins_et >= 1080 (18:00) OU mins_et < 570 (09:30)
    is_ovn = (df["mins_et_loc"] >= 1080) | (df["mins_et_loc"] < 570)

    # Trading day = date_et+1 si on est apres 18:00, sinon date_et
    df["ovn_session_date"] = np.where(
        df["mins_et_loc"] >= 1080,
        (ts_et + pd.Timedelta(hours=8)).dt.date,
        df["date_et_loc"],
    )

    # Aggregate OVN high/low par session
    ovn_only = df.where(is_ovn)
    ovn_agg = ovn_only.groupby(df["ovn_session_date"]).agg(
        ovn_high=("high", "max"),
        ovn_low=("low", "min"),
    )
    df = df.merge(ovn_agg, left_on="ovn_session_date", right_index=True, how="left")

    # FIX ANTI-LEAK : masker ovn_high/low pendant session OVN active
    # OVN active = mins_et < 570 (avant 09:30 ET) OU mins_et >= 1080 (apres 18:00 ET)
    # Disponibilite : seulement quand session OVN est terminee = mins_et entre 570 et 1080
    is_ovn_active = is_ovn  # meme condition que ci-dessus
    df.loc[is_ovn_active, "ovn_high"] = np.nan
    df.loc[is_ovn_active, "ovn_low"] = np.nan

    df["ovn_range_ticks"] = ((df["ovn_high"] - df["ovn_low"]) / tick).round().astype("float64")
    df["dist_ovn_high_pct"] = ((df["close"] - df["ovn_high"]) / df["close"] * 100).astype("float32")
    df["dist_ovn_low_pct"] = ((df["close"] - df["ovn_low"]) / df["close"] * 100).astype("float32")
    # ovn_broken_up/dn : seulement applicable post-OVN (sinon comparison sur futur)
    df["ovn_broken_up"] = ((df["high"] > df["ovn_high"]) & (~is_ovn_active)).fillna(False).astype("int8")
    df["ovn_broken_dn"] = ((df["low"] < df["ovn_low"]) & (~is_ovn_active)).fillna(False).astype("int8")

    df.drop(columns=["mins_et_loc", "date_et_loc", "ovn_session_date"], inplace=True)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# G. OPENS 08:30 / 09:30
# ═══════════════════════════════════════════════════════════════════════════════

def add_open_features(df: pd.DataFrame) -> pd.DataFrame:
    """Open futures (08:30 ET) + open cash (09:30 ET) + distances en %.

    FIX 27/04 (anti-leak) : open_830/930 broadcast a tout le jour creait un leak
    pour les bars avant 08:30/09:30 ET (qui voyaient le futur). Solution : masker
    open_830 a NaN pour bars avant 08:30, open_930 a NaN pour bars avant 09:30.
    """
    df = df.copy()
    ts_et = df["ts_event"].dt.tz_convert(ET) if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
    mins_et = ts_et.dt.hour * 60 + ts_et.dt.minute
    date_et = ts_et.dt.date

    # Open 08:30 = open de la barre 08:30 ET (mins_et == 510)
    open_830 = df[mins_et == 510].groupby(date_et)["open"].first()
    open_930 = df[mins_et == 570].groupby(date_et)["open"].first()

    df["__date_et"] = date_et
    df["__mins_et"] = mins_et.values
    df = df.merge(open_830.rename("open_830_et"), left_on="__date_et", right_index=True, how="left")
    df = df.merge(open_930.rename("open_930_et"), left_on="__date_et", right_index=True, how="left")

    # FIX ANTI-LEAK : masker avant l'heure de l'open
    # open_830 disponible seulement a partir de 08:30 ET (mins_et >= 510)
    df.loc[df["__mins_et"] < 510, "open_830_et"] = np.nan
    # open_930 disponible seulement a partir de 09:30 ET (mins_et >= 570)
    df.loc[df["__mins_et"] < 570, "open_930_et"] = np.nan
    df.drop(columns=["__date_et", "__mins_et"], inplace=True)

    df["dist_open_830_pct"] = ((df["close"] - df["open_830_et"]) / df["close"] * 100).astype("float32")
    df["dist_open_930_pct"] = ((df["close"] - df["open_930_et"]) / df["close"] * 100).astype("float32")
    df["above_open_830"] = (df["close"] > df["open_830_et"]).astype("int8")
    df["above_open_930"] = (df["close"] > df["open_930_et"]).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# H. NEWS FLAGS (07:15, 07:30, 08:30, 08:45, 09:00, 09:30 ET)
# ═══════════════════════════════════════════════════════════════════════════════

NEWS_TIMES_ET = [
    (7, 15, "news_715"),
    (7, 30, "news_730"),
    (8, 30, "news_830"),
    (8, 45, "news_845"),
    (9, 0, "news_900"),
    (9, 30, "news_930"),
]


def add_news_features(df: pd.DataFrame, window_mins: int = 5) -> pd.DataFrame:
    """Markers temporels heures news standard ET + minutes since/to next news."""
    df = df.copy()
    ts_et = df["ts_event"].dt.tz_convert(ET) if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
    mins_et = (ts_et.dt.hour * 60 + ts_et.dt.minute).astype("int32")

    for h, m, name in NEWS_TIMES_ET:
        target_mins = h * 60 + m
        df[f"is_{name}"] = (mins_et == target_mins).astype("int8")
        df[f"within_{name}_5m"] = (
            (mins_et >= target_mins) & (mins_et < target_mins + window_mins)
        ).astype("int8")

    news_mins_arr = np.array([h * 60 + m for h, m, _ in NEWS_TIMES_ET])
    # mins_since_news = mins_et - latest news <= mins_et (vectorise)
    mins_v = mins_et.values
    diffs_since = mins_v[:, None] - news_mins_arr[None, :]  # (N, K)
    diffs_since = np.where(diffs_since >= 0, diffs_since, 9999)
    mins_since = diffs_since.min(axis=1)
    mins_since = np.where(mins_since == 9999, -1, mins_since)
    df["mins_since_news"] = mins_since.astype("int16")

    diffs_to = news_mins_arr[None, :] - mins_v[:, None]
    diffs_to = np.where(diffs_to > 0, diffs_to, 9999)
    mins_to = diffs_to.min(axis=1)
    mins_to = np.where(mins_to == 9999, -1, mins_to)
    df["mins_to_next_news"] = mins_to.astype("int16")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# I. ALL-IN-ONE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_B_PLUS_GENERATED = {
    # Color (LOOKAHEAD _fwd1 — utilise barre i+1)
    "bn_color_up_fwd1", "bn_color_dn_fwd1", "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
    # Color Extension Lines (zones non-touchees + cluster local)
    "n_color_up_zones_active", "n_color_dn_zones_active",
    "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
    "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    # Long bar (formule SC officielle Jackson 27/04, threshold per-symbole)
    "long_up_bar", "long_dn_bar", "bar_body_ticks",
    "range_h_minus_lprev_ticks", "range_hprev_minus_l_ticks",
    # Long Extension Lines (zones non-touchees + cluster local — Jackson trading manuel)
    "n_long_up_zones_active", "n_long_dn_zones_active",
    "dist_long_up_nearest_pct", "dist_long_dn_nearest_pct",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
    # Long Up Down / Down Up pattern (formule per-symbole, ES lookahead / NQ no lookahead)
    "long_up_dn_pattern", "long_dn_up_pattern",
    # Volume spike (formule SC officielle V > threshold per-symbole)
    "vol_spike_up", "vol_spike_dn", "vol_zscore_20",
    # Rotation Up/Down (formule SC OHLC pure, MEME ES + NQ, pas Extension Lines)
    "rotation_up", "rotation_dn",
    # VWAP D + SD bands
    "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u", "vwap_d_sd2d", "vwap_d_sd3u", "vwap_d_sd3d",
    "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct", "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
    # VWAP D cross + sd1/sd2 above/below (NOUVEAU - F.2)
    "vwap_d_cross_up", "vwap_d_cross_dn",
    "vwap_d_sd1_above", "vwap_d_sd1_below", "vwap_d_sd2_above", "vwap_d_sd2_below",
    # VWAP W + SD
    "vwap_w", "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w_sd2u", "vwap_w_sd2d", "vwap_w_sd3u", "vwap_w_sd3d",
    "dist_vwap_w_pct", "dist_vwap_w_sd1u_pct", "dist_vwap_w_sd1d_pct", "dist_vwap_w_sd2u_pct", "dist_vwap_w_sd2d_pct",
    # VWAP M (NOUVEAU - F.1 Monthly)
    "vwap_m", "vwap_m_sd1u", "vwap_m_sd1d", "vwap_m_sd2u", "vwap_m_sd2d", "vwap_m_sd3u", "vwap_m_sd3d",
    "dist_vwap_m_pct", "dist_vwap_m_sd1u_pct", "dist_vwap_m_sd1d_pct", "dist_vwap_m_sd2u_pct", "dist_vwap_m_sd2d_pct",
    # OVN
    "ovn_high", "ovn_low", "ovn_range_ticks", "dist_ovn_high_pct", "dist_ovn_low_pct",
    "ovn_broken_up", "ovn_broken_dn",
    # Opens
    "open_830_et", "open_930_et", "dist_open_830_pct", "dist_open_930_pct",
    "above_open_830", "above_open_930",
    # News
    "is_news_715", "is_news_730", "is_news_830", "is_news_845", "is_news_900", "is_news_930",
    "within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
    "within_news_845_5m", "within_news_900_5m", "within_news_930_5m",
    "mins_since_news", "mins_to_next_news",
}


def apply_phase_b_plus(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """
    Pipeline complet Phase B+ P1 (OHLC-only). Idempotent.

    symbol : 'ES', 'NQ' ou 'MGC' - utilise pour :
      - seuils per-symbole (ex: COLOR threshold 12 ES / 40 NQ)
      - tick_size (MGC=0.10 vs ES/NQ=0.25) propage aux helpers tick-aware
    """
    tick = _get_tick_size(symbol)

    df = df.copy()
    drop_existing = [c for c in PHASE_B_PLUS_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    df = add_color_features(df, symbol=symbol, tick=tick)
    df = add_color_extension_lines(df)
    df = add_long_bar_features(df, symbol=symbol, tick=tick)
    df = add_long_extension_lines(df)
    df = add_long_updown_features(df, symbol=symbol, tick=tick)
    df = add_volume_spike_features(df, symbol=symbol)  # fix Passe B v2 : pas de tick
    df = add_rotation_features(df, tick=tick)
    df = add_vwap_features(df)
    df = add_ovn_features(df, tick=tick)
    df = add_open_features(df)
    df = add_news_features(df)
    return df
