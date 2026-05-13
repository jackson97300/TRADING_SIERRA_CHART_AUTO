"""rolling_features_streaming.py

API streaming-aware (row-by-row) du module CORE/rolling_features.py.

Reproduit les 45+ features ctx_* sur fenetres glissantes (rolling 3/5/10
barres + 20/60 pour features avancees). Le module batch reste INTOUCHE
(additive-only). Sub-engines streaming = ADDITIONNELS.

Architecture :
    Le module batch utilise pandas.rolling/shift/groupby sur DataFrame entier.
    Le module streaming maintient des deques par feature input dans
    RollingFeaturesState et calcule incrementalement chaque sortie.

Niveau de complexite :
    GROUPE A (CE FICHIER, sub-engine #6) — 13 features TIER 1 :
      CRITICAL (5) : ctx_price_delta_div_3, ctx_absorption_score_5,
                     ctx_vol_sell_buy_ratio_5, ctx_vwap_slope_accel,
                     ctx_cvd_recovery_rate
      HIGH (8) :     ctx_price_slope_5, ctx_delta_slope_5, ctx_delta_sum_3,
                     ctx_vol_z_5, ctx_diag_imbalance_mean_5,
                     ctx_finish_strength_mean_5, ctx_va_position_velocity,
                     ctx_side_flip_count_10

    GROUPES B-E (commits futurs Phase 3b semaine 3) :
      ctx_delta_sum_10, ctx_dist_vwap_velocity, ctx_range_vs_atr_10,
      ctx_ib_position_velocity, ctx_instant_absorption, ctx_absorption_streak_5,
      ctx_climax_signal, ctx_vol_slope_5, ctx_delta_exhaustion,
      ctx_large_trader_slope_5, ctx_trend_day_score, ctx_day_type_intensity,
      ctx_mq_put_call_ratio, ctx_poc_migration_10, ctx_va_developing_10,
      ctx_ib_extension_ratio, ctx_rotation_factor_20, ctx_failed_auction,
      ctx_excess_high/low_bars, ctx_poor_high/low, delta_div_*, trapped traders,
      session-specific, divergence confluence.

Non-portables streaming (documente) :
    div_forward_return_20b : utilise price.shift(-20) (LOOKAHEAD FUTUR).
    Impossible en stream sans buffer de 20 bars futures. Cette feature ne
    peut etre calculee qu'en batch ou en deferred mode (replay J+1).

Auteur : Phase 3b Mardi soir (2026-05-13)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from constants import INSTANT_ABSORPTION_DELTA_K, INSTANT_ABSORPTION_WINDOW


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers locaux (mirror methodes statiques RollingFeatures batch)
# ═══════════════════════════════════════════════════════════════════════════════

def _linreg_slope(values: list) -> float:
    """Pente regression lineaire sur une fenetre (mirror _slope batch).

    Reproduit exactement linreg_slope() de RollingFeatures :
      n = len(values)
      valid = ~np.isnan(values)
      si valid.sum() < 2 -> NaN
      x = arange(n)[valid], y = values[valid]
      mx, my = means
      denom = sum((x-mx)^2)
      si denom == 0 -> 0.0
      slope = sum((x-mx)*(y-my)) / denom
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 2:
        return np.nan
    valid = ~np.isnan(arr)
    if valid.sum() < 2:
        return np.nan
    x = np.arange(n, dtype=float)[valid]
    y = arr[valid]
    mx, my = x.mean(), y.mean()
    denom = ((x - mx) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - mx) * (y - my)).sum() / denom)


def _safe_float(x) -> Optional[float]:
    """Cast safe : retourne float ou None si NaN/exception."""
    if x is None:
        return None
    try:
        f = float(x)
        if np.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# State sub-engine #6 (Groupe A — 13 features TIER 1)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RollingFeaturesState:
    """State sub-engine #6 — rolling features groupe A.

    Deques par feature input (maxlen calibre pour la fenetre la plus longue
    + 1 pour shift). Pickle-safe : deques de floats/None primitifs.

    Convention windows :
      short = 3   (delta_sum_3, divergence)
      mid   = 5   (slopes, means, z-scores)
      long  = 10  (cvd_recovery, flip_count)

    Note : on garde +1 dans certains maxlen pour les features avec shift()
    (vwap_slope_accel = current - shift(5), va_position_velocity = idem,
    side_flip_count = compare shift(1)).
    """
    # short window (3)
    delta_short: deque = field(default_factory=lambda: deque(maxlen=3))
    # mid window (5) : pour slopes, means, z-score
    price_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    delta_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    vol_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    diag_imb_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    finish_str_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    # mid+1 = 6 pour absorption_score_5 (besoin price[t-5] pour diff au bar 0
    # de la fenetre, mirror batch price.diff() AVANT rolling)
    price_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    delta_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    # mid+1 = 6 pour shift(5) features
    vwap_slope_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    va_pos_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    # long window (10)
    delta_long: deque = field(default_factory=lambda: deque(maxlen=10))
    vol_long: deque = field(default_factory=lambda: deque(maxlen=10))
    # long+1 = 11 pour cvd_recovery (cvd_day - shift(10))
    cvd_day_long_plus: deque = field(default_factory=lambda: deque(maxlen=11))
    # FIX P0 audit smoke test : pour side_flip_count, on stocke directement
    # les CHANGES (0 ou 1) avec maxlen=long. Le premier bar produit un
    # virtual flip (side != NaN -> 1) inclus dans le rolling window pendant
    # les 10 premiers bars. Cleaner que stocker sides et reconstruire.
    side_changes_long: deque = field(default_factory=lambda: deque(maxlen=10))
    prev_vwap_side: Optional[int] = None
    has_seen_first_side: bool = False
    # divergence prix-delta sur 3 : besoin price[t] et price[t-3]
    price_short_plus: deque = field(default_factory=lambda: deque(maxlen=4))


def add_rolling_features_basic_streaming(
    row: dict,
    state: RollingFeaturesState,
    short: int = 3,
    mid: int = 5,
    long: int = 10,
) -> dict:
    """Sub-engine #6 — 13 rolling features TIER 1 streaming.

    Args:
        row : dict avec price, delta_bar, total_vol, vwap_slope_10, dist_vwap_d,
              cvd_day, diag_imbalance, finish_strength, va_position_pct,
              vwap_d_side.
        state : RollingFeaturesState mutable.
        short, mid, long : fenetres (default 3, 5, 10).

    Returns:
        dict row + 13 features ctx_*.

    Note : aucun fail-loud sur deps manquantes (batch utilise .get fallback
    NaN). Convention mirror batch ligne 88-92 qui print WARNING + return df.
    """
    out = dict(row)

    # ─── Extract inputs avec safe cast ──────────────────────────────────────
    price = _safe_float(out.get("price"))
    delta = _safe_float(out.get("delta_bar"))
    vol = _safe_float(out.get("total_vol"))
    vwap_slope_10 = _safe_float(out.get("vwap_slope_10"))
    cvd_day = _safe_float(out.get("cvd_day"))
    diag_imb = _safe_float(out.get("diag_imbalance"))
    finish_str = _safe_float(out.get("finish_strength"))
    va_pos = _safe_float(out.get("va_position_pct"))
    vwap_side = out.get("vwap_d_side")  # peut etre -1/0/+1

    # Cast vwap_side (mirror batch comparison != shift(1))
    if vwap_side is not None:
        try:
            vwap_side_int = int(vwap_side)
        except (TypeError, ValueError):
            vwap_side_int = None
    else:
        vwap_side_int = None

    # ─── Update deques (append meme si None pour preserver alignement temporel)
    # Convention pandas rolling : NaN sont conserves dans la fenetre (skipna geree
    # par les fonctions de calcul). On stocke None et on filtre dans le calcul.
    state.price_short_plus.append(price)
    state.price_mid.append(price)
    state.price_mid_plus.append(price)
    state.delta_short.append(delta)
    state.delta_mid.append(delta)
    state.delta_mid_plus.append(delta)
    state.delta_long.append(delta)
    state.vol_mid.append(vol)
    state.vol_long.append(vol)
    state.diag_imb_mid.append(diag_imb)
    state.finish_str_mid.append(finish_str)
    state.vwap_slope_mid_plus.append(vwap_slope_10)
    state.cvd_day_long_plus.append(cvd_day)
    state.va_pos_mid_plus.append(va_pos)

    # Update side_changes (FIX P0 side_flip_count + P1-1 NaN IEEE 754)
    # Mirror batch : changes_series[t] = side[t] != side[t-1]
    # Au tout premier bar : side[0] != NaN -> True (1) virtuel.
    #
    # FIX P1-1 audit code-reviewer : pandas applique IEEE 754 NaN comparison
    # ou NaN != NaN = True. Python natif : None != None = False. Pour matcher
    # batch sur cas vwap_d_side NaN/None consecutifs, on traite explicitement :
    #   - Si curr OU prev est None  -> change = 1 (NaN != value = True en pandas)
    #   - Sinon                      -> change = (curr != prev)
    if not state.has_seen_first_side:
        # Premier bar : virtual flip = 1 (batch convention NaN-shift)
        state.side_changes_long.append(1)
        state.has_seen_first_side = True
    else:
        curr_none = vwap_side_int is None
        prev_none = state.prev_vwap_side is None
        if curr_none or prev_none:
            # Mirror pandas IEEE 754 : NaN != anything (y compris NaN) = True
            state.side_changes_long.append(1)
        elif vwap_side_int != state.prev_vwap_side:
            state.side_changes_long.append(1)
        else:
            state.side_changes_long.append(0)
    state.prev_vwap_side = vwap_side_int

    # ─── 1. ctx_price_delta_div_3 ──────────────────────────────────────────
    # Mirror batch : price_change = price - price.shift(3), delta_sum = delta.rolling(3).sum()
    # +1 = price up, delta sum < 0 (bull div) ; -1 = price down, delta sum > 0
    if len(state.price_short_plus) >= 4 and price is not None:
        price_t_minus_3 = state.price_short_plus[0]  # price il y a 3 bars (maxlen=4)
        if price_t_minus_3 is not None:
            price_change = price - price_t_minus_3
            # delta_sum sur les 3 dernieres barres (incluant la barre courante)
            delta_vals_short = [d for d in state.delta_short if d is not None]
            if delta_vals_short:
                delta_sum_3_raw = sum(delta_vals_short)
                if price_change > 0 and delta_sum_3_raw < 0:
                    out["ctx_price_delta_div_3"] = 1.0
                elif price_change < 0 and delta_sum_3_raw > 0:
                    out["ctx_price_delta_div_3"] = -1.0
                else:
                    out["ctx_price_delta_div_3"] = 0.0
            else:
                out["ctx_price_delta_div_3"] = 0.0
        else:
            out["ctx_price_delta_div_3"] = 0.0
    else:
        out["ctx_price_delta_div_3"] = 0.0

    # ─── 2. ctx_absorption_score_5 ─────────────────────────────────────────
    # FIX P0 audit : batch utilise price.diff() AVANT rolling, donc price_diff
    # est disponible pour CHAQUE bar de la fenetre (sauf bar 0 du DataFrame).
    # On utilise price_mid_plus (maxlen=6) pour avoir price[t-1] meme pour le
    # plus ancien bar de la fenetre de 5.
    #
    # Mirror batch :
    #   price_diff = price.diff()  -> NaN au bar 0 du DF entier
    #   buy_absorb = (delta > 10) & (price_diff <= 0)   -> 0 si price_diff NaN
    #   sell_absorb = (delta < -10) & (price_diff >= 0) -> 0 si price_diff NaN
    #   score = rolling(5, min_periods=1).sum() / 5
    threshold = 10.0
    pmp_list = list(state.price_mid_plus)
    dmp_list = list(state.delta_mid_plus)
    if len(pmp_list) >= 2:
        absorb_count = 0.0
        # Fenetre cible = 5 derniers bars (= les 5 derniers de price_mid_plus)
        # Pour chacun, on a besoin du bar precedent qui est dans price_mid_plus.
        n_window = min(mid, len(pmp_list))
        # On itere sur les n_window derniers bars du deque
        for offset in range(n_window):
            # idx dans pmp_list : len-n_window+offset = position dans fenetre
            idx = len(pmp_list) - n_window + offset
            p_curr = pmp_list[idx]
            d_curr = dmp_list[idx] if idx < len(dmp_list) else None
            # Bar precedent : idx-1 dans pmp_list, OU NaN si idx=0 (bar 0 du DF)
            if idx - 1 >= 0:
                p_prev = pmp_list[idx - 1]
            else:
                p_prev = None  # bar 0 du DF -> price_diff NaN -> contribution 0
            if p_curr is None or p_prev is None or d_curr is None:
                continue
            price_diff = p_curr - p_prev
            if d_curr > threshold and price_diff <= 0:
                absorb_count += 1.0
            elif d_curr < -threshold and price_diff >= 0:
                absorb_count += 1.0
        out["ctx_absorption_score_5"] = absorb_count / float(mid)
    else:
        out["ctx_absorption_score_5"] = 0.0

    # ─── 3. ctx_vol_sell_buy_ratio_5 ───────────────────────────────────────
    # Mirror batch : sell_mean = vol.where(delta<0).rolling(5).mean()
    #                buy_mean = vol.where(delta>0).rolling(5).mean()
    #                ratio = sell_mean / buy_mean (1.0 si NaN)
    sell_vols = []
    buy_vols = []
    for v, d in zip(state.vol_mid, state.delta_mid):
        if v is None or d is None:
            continue
        if d < 0:
            sell_vols.append(v)
        elif d > 0:
            buy_vols.append(v)
    if sell_vols and buy_vols:
        sell_mean = sum(sell_vols) / len(sell_vols)
        buy_mean = sum(buy_vols) / len(buy_vols)
        if buy_mean != 0.0:
            out["ctx_vol_sell_buy_ratio_5"] = sell_mean / buy_mean
        else:
            out["ctx_vol_sell_buy_ratio_5"] = 1.0
    else:
        out["ctx_vol_sell_buy_ratio_5"] = 1.0

    # ─── 4. ctx_vwap_slope_accel ───────────────────────────────────────────
    # Mirror batch : vwap_slope_10 - vwap_slope_10.shift(5)
    if len(state.vwap_slope_mid_plus) >= 6 and vwap_slope_10 is not None:
        prev_slope = state.vwap_slope_mid_plus[0]  # il y a 5 bars (maxlen=6)
        if prev_slope is not None:
            out["ctx_vwap_slope_accel"] = vwap_slope_10 - prev_slope
        else:
            out["ctx_vwap_slope_accel"] = np.nan
    else:
        out["ctx_vwap_slope_accel"] = np.nan

    # ─── 5. ctx_cvd_recovery_rate ──────────────────────────────────────────
    # Mirror batch : (cvd_day - cvd_day.shift(10)) / vol.rolling(10).mean()
    if (
        len(state.cvd_day_long_plus) >= 11
        and cvd_day is not None
    ):
        cvd_t_minus_10 = state.cvd_day_long_plus[0]  # maxlen=11
        if cvd_t_minus_10 is not None:
            cvd_delta = cvd_day - cvd_t_minus_10
            vol_vals = [v for v in state.vol_long if v is not None]
            if vol_vals:
                vol_mean_long = sum(vol_vals) / len(vol_vals)
                if vol_mean_long != 0.0:
                    out["ctx_cvd_recovery_rate"] = cvd_delta / vol_mean_long
                else:
                    out["ctx_cvd_recovery_rate"] = np.nan
            else:
                out["ctx_cvd_recovery_rate"] = np.nan
        else:
            out["ctx_cvd_recovery_rate"] = np.nan
    else:
        out["ctx_cvd_recovery_rate"] = np.nan

    # ─── 6. ctx_price_slope_5 ──────────────────────────────────────────────
    # Mirror batch : _slope(price, 5) = rolling(5, min_periods=2).apply(linreg_slope)
    out["ctx_price_slope_5"] = _linreg_slope(list(state.price_mid))

    # ─── 7. ctx_delta_slope_5 ──────────────────────────────────────────────
    out["ctx_delta_slope_5"] = _linreg_slope(list(state.delta_mid))

    # ─── 8. ctx_delta_sum_3 ────────────────────────────────────────────────
    # Mirror batch : delta_bar.rolling(3, min_periods=1).sum()
    delta_vals_short = [d for d in state.delta_short if d is not None]
    if delta_vals_short:
        out["ctx_delta_sum_3"] = float(sum(delta_vals_short))
    else:
        # rolling.sum sur all-NaN avec min_periods=1 -> 0 (skipna=True default)
        out["ctx_delta_sum_3"] = 0.0

    # ─── 9. ctx_vol_z_5 ────────────────────────────────────────────────────
    # Mirror batch : (vol - vol.rolling(5, min_p=2).mean()) / vol.rolling(5, min_p=2).std()
    vol_vals_mid = [v for v in state.vol_mid if v is not None]
    if len(vol_vals_mid) >= 2 and vol is not None:
        v_mean = sum(vol_vals_mid) / len(vol_vals_mid)
        # std pandas default ddof=1 (sample std)
        v_var = sum((x - v_mean) ** 2 for x in vol_vals_mid) / (len(vol_vals_mid) - 1)
        v_std = v_var ** 0.5
        if v_std != 0.0:
            out["ctx_vol_z_5"] = (vol - v_mean) / v_std
        else:
            out["ctx_vol_z_5"] = np.nan
    else:
        out["ctx_vol_z_5"] = np.nan

    # ─── 10. ctx_diag_imbalance_mean_5 ─────────────────────────────────────
    diag_vals = [d for d in state.diag_imb_mid if d is not None]
    if diag_vals:
        out["ctx_diag_imbalance_mean_5"] = sum(diag_vals) / len(diag_vals)
    else:
        out["ctx_diag_imbalance_mean_5"] = np.nan

    # ─── 11. ctx_finish_strength_mean_5 ────────────────────────────────────
    finish_vals = [f for f in state.finish_str_mid if f is not None]
    if finish_vals:
        out["ctx_finish_strength_mean_5"] = sum(finish_vals) / len(finish_vals)
    else:
        out["ctx_finish_strength_mean_5"] = np.nan

    # ─── 12. ctx_va_position_velocity ──────────────────────────────────────
    # Mirror batch : va_position_pct - va_position_pct.shift(5)
    if len(state.va_pos_mid_plus) >= 6 and va_pos is not None:
        prev_va = state.va_pos_mid_plus[0]
        if prev_va is not None:
            out["ctx_va_position_velocity"] = va_pos - prev_va
        else:
            out["ctx_va_position_velocity"] = np.nan
    else:
        out["ctx_va_position_velocity"] = np.nan

    # ─── 13. ctx_side_flip_count_10 ────────────────────────────────────────
    # FIX P0 audit : on stocke directement les CHANGES (0/1) dans
    # state.side_changes_long (maxlen=10). Le premier bar produit un virtual
    # flip (side != NaN -> 1) inclus dans le rolling. Output = sum(deque).
    # Mirror exact batch : (side != side.shift(1)).rolling(10, min_p=1).sum()
    out["ctx_side_flip_count_10"] = float(sum(state.side_changes_long))

    return out
