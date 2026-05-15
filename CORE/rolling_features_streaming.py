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

    # ─── GROUPE B (4 MEDIUM + 3 AUDIT + 3 TIER1 + 2 DYNAMIC + 1 MQ) ────────
    # Pour shift(5) features : dist_vwap_d, ib_position_pct
    dist_vwap_d_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    ib_pos_mid_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    # Pour range_vs_atr_10 : besoin max/min sur 10 derniers prix
    price_long: deque = field(default_factory=lambda: deque(maxlen=10))
    # Pour ctx_instant_absorption (rolling std delta_bar sur INSTANT_ABSORPTION_WINDOW)
    delta_for_std: deque = field(
        default_factory=lambda: deque(maxlen=INSTANT_ABSORPTION_WINDOW)
    )
    # price_diff shift 1 pour instant_absorption (price[t] - price[t-1])
    prev_price_for_diff: Optional[float] = None
    # Pour ctx_absorption_streak_5 : rolling sum sur 5 derniers ctx_instant_absorption
    instant_absorb_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    # Pour ctx_large_trader_slope_5 : slope sur 5 dernieres large_trader_ratio
    large_trader_mid: deque = field(default_factory=lambda: deque(maxlen=5))
    # Pour ctx_delta_exhaustion : max(|delta_bar|) sur 10 derniers
    delta_abs_long: deque = field(default_factory=lambda: deque(maxlen=10))

    # ─── GROUPE C (6 Market Profile advanced) ──────────────────────────────
    # ctx_poc_migration_10 : slope poc_position sur 10
    poc_position_long: deque = field(default_factory=lambda: deque(maxlen=10))
    # ctx_va_developing_10 : va_width - shift 10 (long+1=11)
    va_width_long_plus: deque = field(default_factory=lambda: deque(maxlen=11))
    # ctx_rotation_factor_20 : cross VPOC sur 20 (changes 0/1)
    vpoc_side_changes_20: deque = field(default_factory=lambda: deque(maxlen=20))
    prev_vpoc_side: Optional[int] = None
    has_seen_first_vpoc_side: bool = False
    # ctx_failed_auction : inside_cur_va lookback 3, 4, 5
    inside_va_short_plus: deque = field(default_factory=lambda: deque(maxlen=6))
    # ctx_excess_high/low_bars : near_high/low rolling sum sur 60
    near_high_60: deque = field(default_factory=lambda: deque(maxlen=60))
    near_low_60: deque = field(default_factory=lambda: deque(maxlen=60))

    # ─── GROUPE D (Delta divergence reconstruction SC ID33) ────────────────
    # Reset par trading_date CME (18:00 ET = 22:00 UTC cutoff)
    current_trading_date: Optional[Any] = None
    daily_high_running: Optional[float] = None  # cummax bar_high par session
    daily_low_running: Optional[float] = None   # cummin bar_low par session
    # prev_trading_date : pour same_session check (batch trading_date == shift(1))
    prev_trading_date: Optional[Any] = None

    # ─── GROUPE E (Trapped traders + session-specific + confluence) ────────
    # Session reset detection
    current_session: Optional[int] = None  # 0=Asia 1=London 2=US
    # ctx_cvd_session : delta cumsum reset par session
    cvd_session_running: float = 0.0
    # ctx_rvol_session : rolling 30 mean dans la session
    vol_session_window: deque = field(default_factory=lambda: deque(maxlen=30))
    # ctx_bars_since_div : compteur depuis last divergence
    bars_since_last_div: Optional[int] = None  # None si aucune div vue
    # ctx_div_density_20 : sum divergences sur 20
    div_fired_long: deque = field(default_factory=lambda: deque(maxlen=20))


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
    # REVERT RE-ENABLE 2026-05-15 Review #4 NOGO : asymetrie semantique
    # batch/stream PIRE que la perte. Batch consume DMP-C++ exact `diag_imbalance`
    # (footprint VAP cellule), stream produirait proxy OFI (delta_bar/total_vol).
    # Meme NOM avec definition DIFFERENTE -> drift ML train/inference garanti.
    # Stream produit `diag_imbalance_ofi_proxy` (rename) accessible pour gates
    # mais PAS pour ML training. ctx_diag_imbalance_mean_5 reste droppe.
    # IDEAS_BACKLOG : retraitement V4 batch avec OFI proxy si parite ML requise.

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


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-engine #7 — GROUPE B (13 features : MEDIUM + AUDIT + TIER1 + DYNAMIC + MQ)
# ═══════════════════════════════════════════════════════════════════════════════
# Reutilise RollingFeaturesState (etendu avec deques B). Convention pipeline :
#   add_rolling_features_basic_streaming(row, state)    # GROUPE A 13 features
#   add_rolling_features_medium_streaming(row, state)   # GROUPE B 13 features
#
# Certaines features GROUPE B utilisent les outputs GROUPE A (climax_signal
# depend de vol_z_5 + delta_sum_3). Donc l'ordre d'appel basic AVANT medium
# est OBLIGATOIRE. Si user appelle medium seul, fallback 0 (mirror batch
# `df.get("col", pd.Series(0, index=df.index))`).


def add_rolling_features_medium_streaming(
    row: dict,
    state: RollingFeaturesState,
    short: int = 3,
    mid: int = 5,
    long: int = 10,
    symbol: str = "ES",
    tick_size: Optional[float] = None,
) -> dict:
    """Sub-engine #7 — 13 features GROUPE B streaming.

    Features :
      MEDIUM (4) : ctx_delta_sum_10, ctx_dist_vwap_velocity,
                   ctx_range_vs_atr_10, ctx_ib_position_velocity
      AUDIT (3) :  ctx_instant_absorption, ctx_absorption_streak_5,
                   ctx_climax_signal
      TIER1 (3) :  ctx_vol_slope_5, ctx_delta_exhaustion,
                   ctx_large_trader_slope_5
      DYNAMIC (2): ctx_trend_day_score, ctx_day_type_intensity
      MQ (1) :     ctx_mq_put_call_ratio

    Args:
        row : dict avec les inputs DMP + outputs GROUPE A (vol_z_5, delta_sum_3).
        state : RollingFeaturesState mutable (deques B etendues).
        short/mid/long : fenetres (default 3, 5, 10).
        symbol : pour tick_size si non passe (default ES=0.25).
        tick_size : override explicite (MGC=0.10).

    Returns:
        dict row + 13 features ctx_*.

    Convention NaN/None : mirror batch (NaN propagated, fallback 0 sur deps absentes).
    """
    out = dict(row)

    if tick_size is None:
        # Mirror batch RollingFeatures._get_tick_size
        tick_size = 0.10 if symbol.upper() == "MGC" else 0.25

    # ─── Extract inputs ─────────────────────────────────────────────────────
    price = _safe_float(out.get("price"))
    delta = _safe_float(out.get("delta_bar"))
    vol = _safe_float(out.get("total_vol"))
    atr = _safe_float(out.get("atr"))
    dist_vwap_d = _safe_float(out.get("dist_vwap_d"))
    ib_position_pct = _safe_float(out.get("ib_position_pct"))
    large_trader = _safe_float(out.get("large_trader_ratio"))
    dist_vwap_d_atr = _safe_float(out.get("dist_vwap_d_atr"))
    ib_range_atr = _safe_float(out.get("ib_range_atr"))
    ib_broken_up = out.get("ib_broken_up", 0)
    ib_broken_dn = out.get("ib_broken_down", 0)
    vwap_d_side = _safe_float(out.get("vwap_d_side"))
    delta_day_dir = _safe_float(out.get("delta_day_dir"))
    # P2.2 fix Jackson 15/05/2026 : utiliser dist_mq_*_pct (calcules par P1.4)
    # au lieu de dist_mq_* (vides V4 batch 0/14418). Cf ligne 733 ratio calc.
    # Fallback dist_mq_*_pct -> dist_mq_* (legacy) -> NaN.
    dist_mq_put = _safe_float(out.get("dist_mq_put_pct") or out.get("dist_mq_put"))
    dist_mq_call = _safe_float(out.get("dist_mq_call_pct") or out.get("dist_mq_call"))

    # Outputs GROUPE A si disponibles (mirror batch df.get fallback Series 0)
    ctx_vol_z_5 = _safe_float(out.get("ctx_vol_z_5"))
    ctx_delta_sum_3 = _safe_float(out.get("ctx_delta_sum_3"))

    # ─── Update deques GROUPE B ─────────────────────────────────────────────
    state.dist_vwap_d_mid_plus.append(dist_vwap_d)
    state.ib_pos_mid_plus.append(ib_position_pct)
    state.price_long.append(price)
    state.delta_for_std.append(delta)
    state.large_trader_mid.append(large_trader)
    # delta_abs_long pour exhaustion
    if delta is not None:
        state.delta_abs_long.append(abs(delta))
    else:
        state.delta_abs_long.append(None)

    # ─── 14. ctx_delta_sum_10 ──────────────────────────────────────────────
    # Mirror batch : delta_bar.rolling(10, min_periods=1).sum()
    delta_vals_long = [d for d in state.delta_long if d is not None]
    if delta_vals_long:
        out["ctx_delta_sum_10"] = float(sum(delta_vals_long))
    else:
        out["ctx_delta_sum_10"] = 0.0

    # ─── 15. ctx_dist_vwap_velocity ────────────────────────────────────────
    # Mirror batch : dist_vwap_d - dist_vwap_d.shift(5)
    if len(state.dist_vwap_d_mid_plus) >= 6 and dist_vwap_d is not None:
        prev_dvwap = state.dist_vwap_d_mid_plus[0]
        if prev_dvwap is not None:
            out["ctx_dist_vwap_velocity"] = dist_vwap_d - prev_dvwap
        else:
            out["ctx_dist_vwap_velocity"] = np.nan
    else:
        out["ctx_dist_vwap_velocity"] = np.nan

    # ─── 16. ctx_range_vs_atr_10 ───────────────────────────────────────────
    # Mirror batch : price_max = price.rolling(10, min_p=2).max()
    #                price_min = price.rolling(10, min_p=2).min()
    #                range_ticks = (max - min) / tick_size
    #                ratio = range_ticks / atr (replace 0 -> NaN)
    price_vals_long = [p for p in state.price_long if p is not None]
    if len(price_vals_long) >= 2 and atr is not None:
        p_max = max(price_vals_long)
        p_min = min(price_vals_long)
        range_ticks = (p_max - p_min) / tick_size
        if atr != 0.0:
            out["ctx_range_vs_atr_10"] = range_ticks / atr
        else:
            out["ctx_range_vs_atr_10"] = np.nan
    else:
        out["ctx_range_vs_atr_10"] = np.nan

    # ─── 17. ctx_ib_position_velocity ──────────────────────────────────────
    # Mirror batch : ib_position_pct - ib_position_pct.shift(5)
    if len(state.ib_pos_mid_plus) >= 6 and ib_position_pct is not None:
        prev_ib_pos = state.ib_pos_mid_plus[0]
        if prev_ib_pos is not None:
            out["ctx_ib_position_velocity"] = ib_position_pct - prev_ib_pos
        else:
            out["ctx_ib_position_velocity"] = np.nan
    else:
        out["ctx_ib_position_velocity"] = np.nan

    # ─── 18. ctx_instant_absorption ────────────────────────────────────────
    # Mirror batch : seuil dynamique = std(delta_bar, 50) * K
    #   buy_absorb = (delta > +threshold) & (price_diff < 0)  -> -1.0 (bear)
    #   sell_absorb = (delta < -threshold) & (price_diff > 0) -> +1.0 (bull)
    #   else 0.0
    # Convention rolling.std min_periods=10 (mirror batch).
    delta_for_std_vals = [d for d in state.delta_for_std if d is not None]
    instant_absorb = 0.0
    if (
        len(delta_for_std_vals) >= 10
        and delta is not None
        and price is not None
        and state.prev_price_for_diff is not None
    ):
        # sample std (ddof=1) sur la fenetre
        n_std = len(delta_for_std_vals)
        m_std = sum(delta_for_std_vals) / n_std
        var_std = sum((x - m_std) ** 2 for x in delta_for_std_vals) / (n_std - 1)
        delta_std = var_std ** 0.5
        threshold = delta_std * INSTANT_ABSORPTION_DELTA_K
        price_diff_1 = price - state.prev_price_for_diff
        if delta > threshold and price_diff_1 < 0:
            instant_absorb = -1.0  # bear absorption
        elif delta < -threshold and price_diff_1 > 0:
            instant_absorb = +1.0  # bull absorption
    out["ctx_instant_absorption"] = instant_absorb

    # Update prev_price + instant_absorb deque APRES calcul
    state.prev_price_for_diff = price
    state.instant_absorb_mid.append(instant_absorb)

    # ─── 19. ctx_absorption_streak_5 ───────────────────────────────────────
    # Mirror batch : ctx_instant_absorption.rolling(5, min_p=1).sum()
    out["ctx_absorption_streak_5"] = float(sum(state.instant_absorb_mid))

    # ─── 20. ctx_climax_signal ─────────────────────────────────────────────
    # Mirror batch : np.where(vol_z.abs() > 1.0, sign(delta_sum), 0.0)
    # vol_z = ctx_vol_z_5, delta_sum = ctx_delta_sum_3 (outputs GROUPE A)
    if ctx_vol_z_5 is not None and ctx_delta_sum_3 is not None:
        if abs(ctx_vol_z_5) > 1.0:
            if ctx_delta_sum_3 > 0:
                out["ctx_climax_signal"] = 1.0
            elif ctx_delta_sum_3 < 0:
                out["ctx_climax_signal"] = -1.0
            else:
                out["ctx_climax_signal"] = 0.0
        else:
            out["ctx_climax_signal"] = 0.0
    else:
        # Mirror batch fallback : df.get("col", pd.Series(0)) -> 0
        out["ctx_climax_signal"] = 0.0

    # ─── 21. ctx_vol_slope_5 ───────────────────────────────────────────────
    # Mirror batch : _slope(total_vol, 5)
    out["ctx_vol_slope_5"] = _linreg_slope(list(state.vol_mid))

    # ─── 22. ctx_delta_exhaustion ──────────────────────────────────────────
    # Mirror batch : delta.abs() / delta.abs().rolling(10, min_p=2).max()
    delta_abs_vals = [d for d in state.delta_abs_long if d is not None]
    if len(delta_abs_vals) >= 2 and delta is not None:
        max_delta_abs = max(delta_abs_vals)
        if max_delta_abs != 0.0:
            out["ctx_delta_exhaustion"] = abs(delta) / max_delta_abs
        else:
            out["ctx_delta_exhaustion"] = np.nan
    else:
        out["ctx_delta_exhaustion"] = np.nan

    # ─── 23. ctx_large_trader_slope_5 ──────────────────────────────────────
    # REVERT RE-ENABLE 2026-05-15 Review #4 NOGO : asymetrie semantique
    # batch/stream. Batch consume DMP-C++ `large_trader_ratio` (avg_ask/bid_size
    # VAP cellule), stream produirait proxy max_size B/S. MEME NOM definition
    # DIFFERENTE -> drift ML. ctx_large_trader_slope_5 reste droppe.
    # Stream produit `large_trader_max_size_proxy` (rename) pour gates uniquement.

    # ─── 24. ctx_trend_day_score (composite 5 criteres) ────────────────────
    # Mirror batch : score additif clip(0.0, 1.0)
    #   IB comprime (ib_range_atr < 0.40) : +0.20
    #   IB casse unilateral             : +0.25
    #   Vol accelere (vol_slope_5 > 0)  : +0.15
    #   Prix loin VWAP (|dist_vwap_d_atr| > 0.15) : +0.20
    #   Delta day aligne avec vwap_d_side : +0.20
    score = 0.0
    if ib_range_atr is not None and ib_range_atr < 0.40:
        score += 0.20
    # ib_broken cast bool
    ib_up_bool = bool(ib_broken_up) if ib_broken_up is not None else False
    ib_dn_bool = bool(ib_broken_dn) if ib_broken_dn is not None else False
    if (ib_up_bool and not ib_dn_bool) or (ib_dn_bool and not ib_up_bool):
        score += 0.25
    ctx_vol_slope_5 = out.get("ctx_vol_slope_5")
    if ctx_vol_slope_5 is not None and not (isinstance(ctx_vol_slope_5, float) and np.isnan(ctx_vol_slope_5)) and ctx_vol_slope_5 > 0:
        score += 0.15
    if dist_vwap_d_atr is not None and abs(dist_vwap_d_atr) > 0.15:
        score += 0.20
    if (
        vwap_d_side is not None
        and delta_day_dir is not None
        and vwap_d_side == delta_day_dir
    ):
        score += 0.20
    out["ctx_trend_day_score"] = max(0.0, min(1.0, score))

    # ─── 25. ctx_day_type_intensity (signed [-1, +1]) ──────────────────────
    # Mirror batch : dir * mag clip(-1, 1)
    #   dir = +1 si ib_up only, -1 si ib_dn only, 0 sinon
    #   mag = |dist_vwap_d_atr|
    if ib_up_bool and not ib_dn_bool:
        dir_val = 1.0
    elif ib_dn_bool and not ib_up_bool:
        dir_val = -1.0
    else:
        dir_val = 0.0
    if dist_vwap_d_atr is not None:
        mag = abs(dist_vwap_d_atr)
        intensity = dir_val * mag
        out["ctx_day_type_intensity"] = max(-1.0, min(1.0, intensity))
    else:
        out["ctx_day_type_intensity"] = 0.0

    # ─── 26. ctx_mq_put_call_ratio ─────────────────────────────────────────
    # Mirror batch : |dist_mq_put| / |dist_mq_call| (replace 0 -> NaN)
    if dist_mq_put is not None and dist_mq_call is not None:
        put_abs = abs(dist_mq_put)
        call_abs = abs(dist_mq_call)
        if call_abs != 0.0:
            out["ctx_mq_put_call_ratio"] = put_abs / call_abs
        else:
            out["ctx_mq_put_call_ratio"] = np.nan
    else:
        out["ctx_mq_put_call_ratio"] = np.nan

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-engine #8 — GROUPE C (6 Market Profile advanced features)
# ═══════════════════════════════════════════════════════════════════════════════

def add_rolling_features_advanced_streaming(
    row: dict,
    state: RollingFeaturesState,
    short: int = 3,
    mid: int = 5,
    long: int = 10,
) -> dict:
    """Sub-engine #8 — 6 features GROUPE C Market Profile streaming.

    Features (Steidlmayer / Dalton) :
      ctx_poc_migration_10    - slope poc_position 10 barres
      ctx_va_width            - largeur Value Area (composite intermediate)
      ctx_va_developing_10    - delta VA width sur 10 (acceptance/rejection)
      ctx_ib_extension_ratio  - distance hors IB / (IB_range/2)
      ctx_rotation_factor_20  - count cross VPOC sur 20 (range vs trend day)
      ctx_failed_auction      - sortie+retour VA en <5 barres (reversal)
      ctx_excess_high_bars    - bars pres session high (rolling 60)
      ctx_poor_high           - bool excess_high_bars < 3 (unfinished auction)
      ctx_excess_low_bars     - idem low
      ctx_poor_low            - bool

    Total : 6 features principales + 4 derivees = 10 sorties.
    """
    out = dict(row)

    # ─── Inputs ────────────────────────────────────────────────────────────
    poc_position = _safe_float(out.get("poc_position"))
    dist_cur_vah = _safe_float(out.get("dist_cur_vah"))
    dist_cur_val = _safe_float(out.get("dist_cur_val"))
    dist_cur_vpoc = _safe_float(out.get("dist_cur_vpoc"))
    ib_range_ticks = _safe_float(out.get("ib_range_ticks"))
    dist_ib_high = _safe_float(out.get("dist_ib_high"))
    dist_ib_low = _safe_float(out.get("dist_ib_low"))
    inside_cur_va = out.get("inside_cur_va")
    dist_sess_high = _safe_float(out.get("dist_sess_high"))
    dist_sess_low = _safe_float(out.get("dist_sess_low"))
    atr = _safe_float(out.get("atr"))

    # Cast inside_cur_va (batch fillna(0).astype(int))
    try:
        inside_int = int(inside_cur_va) if inside_cur_va is not None else 0
    except (TypeError, ValueError):
        inside_int = 0

    # ─── 27. ctx_poc_migration_10 ──────────────────────────────────────────
    state.poc_position_long.append(poc_position)
    out["ctx_poc_migration_10"] = _linreg_slope(list(state.poc_position_long))

    # ─── 28a. ctx_va_width (composite intermediate) ────────────────────────
    if dist_cur_vah is not None and dist_cur_val is not None:
        va_width = abs(dist_cur_vah) + abs(dist_cur_val)
    else:
        va_width = np.nan
    out["ctx_va_width"] = va_width

    # ─── 28b. ctx_va_developing_10 ─────────────────────────────────────────
    # Mirror batch : va_width - va_width.shift(10)
    state.va_width_long_plus.append(va_width if not pd.isna(va_width) else None)
    if len(state.va_width_long_plus) >= 11 and not pd.isna(va_width):
        prev_va_width = state.va_width_long_plus[0]
        if prev_va_width is not None:
            out["ctx_va_developing_10"] = va_width - prev_va_width
        else:
            out["ctx_va_developing_10"] = np.nan
    else:
        out["ctx_va_developing_10"] = np.nan

    # ─── 29. ctx_ib_extension_ratio ────────────────────────────────────────
    # Mirror batch : max_ext = max(|dist_ib_high|, |dist_ib_low|)
    #                ratio = max_ext / (ib_range / 2)
    if (
        ib_range_ticks is not None and ib_range_ticks != 0
        and (dist_ib_high is not None or dist_ib_low is not None)
    ):
        d_high_abs = abs(dist_ib_high) if dist_ib_high is not None else 0.0
        d_low_abs = abs(dist_ib_low) if dist_ib_low is not None else 0.0
        max_ext = max(d_high_abs, d_low_abs)
        out["ctx_ib_extension_ratio"] = max_ext / (ib_range_ticks / 2.0)
    else:
        out["ctx_ib_extension_ratio"] = np.nan

    # ─── 30. ctx_rotation_factor_20 ────────────────────────────────────────
    # Mirror batch : vpoc_side = (dist_cur_vpoc > 0).astype(int)
    #                vpoc_cross = (vpoc_side != vpoc_side.shift(1)).astype(float)
    #                rolling(20, min_p=5).sum()
    # Stockage CHANGES (0/1) directement comme side_flip_count_10.
    if dist_cur_vpoc is not None:
        vpoc_side_int = 1 if dist_cur_vpoc > 0 else 0
    else:
        vpoc_side_int = None
    if not state.has_seen_first_vpoc_side:
        # Premier bar : virtual flip = 1 (IEEE 754 NaN != value)
        state.vpoc_side_changes_20.append(1)
        state.has_seen_first_vpoc_side = True
    else:
        curr_none = vpoc_side_int is None
        prev_none = state.prev_vpoc_side is None
        if curr_none or prev_none:
            state.vpoc_side_changes_20.append(1)
        elif vpoc_side_int != state.prev_vpoc_side:
            state.vpoc_side_changes_20.append(1)
        else:
            state.vpoc_side_changes_20.append(0)
    state.prev_vpoc_side = vpoc_side_int
    # min_periods=5 mirror batch
    if len(state.vpoc_side_changes_20) >= 5:
        out["ctx_rotation_factor_20"] = float(sum(state.vpoc_side_changes_20))
    else:
        out["ctx_rotation_factor_20"] = np.nan

    # ─── 31. ctx_failed_auction ────────────────────────────────────────────
    # Mirror batch : pour lookback in [3, 4, 5] :
    #   was_in = inside.shift(lookback)
    #   min_inside = inside.rolling(lookback, min_p=1).min()
    #   failed |= (inside == 1) & (was_in == 1) & (min_inside == 0)
    # On stocke les inside_int dans un deque maxlen=6 (lookback max 5 + 1).
    state.inside_va_short_plus.append(inside_int)
    failed = 0
    inside_list = list(state.inside_va_short_plus)
    n = len(inside_list)
    if inside_int == 1 and n >= 2:
        for lookback in (3, 4, 5):
            if n < lookback + 1:
                continue  # pas assez d'historique
            # was_in : inside[t - lookback] = inside_list[-(lookback+1)]
            was_in_idx = n - 1 - lookback
            if was_in_idx < 0:
                continue
            was_in = inside_list[was_in_idx]
            # min_inside : rolling(lookback) ending at current bar
            window_inside = inside_list[n - lookback:n]
            min_inside = min(window_inside)
            if was_in == 1 and min_inside == 0:
                failed = 1
                break
    out["ctx_failed_auction"] = failed

    # ─── 32a. ctx_excess_high_bars + ctx_poor_high ─────────────────────────
    # Mirror batch : near_high = (|dist_sess_high| / atr < 0.04).astype(float)
    #                excess_high_bars = near_high.rolling(60, min_p=10).sum()
    #                poor_high = (excess_high_bars < 3).astype(float)
    if dist_sess_high is not None and atr is not None and atr != 0:
        near_high_curr = 1.0 if abs(dist_sess_high) / atr < 0.04 else 0.0
    else:
        near_high_curr = None  # NaN
    state.near_high_60.append(near_high_curr)
    near_high_vals = [v for v in state.near_high_60 if v is not None]
    if len(near_high_vals) >= 10:
        excess_high = float(sum(near_high_vals))
        out["ctx_excess_high_bars"] = excess_high
        out["ctx_poor_high"] = 1.0 if excess_high < 3 else 0.0
    else:
        out["ctx_excess_high_bars"] = np.nan
        out["ctx_poor_high"] = 0.0  # batch default 0 si col absente/incalculable

    # ─── 32b. ctx_excess_low_bars + ctx_poor_low ───────────────────────────
    if dist_sess_low is not None and atr is not None and atr != 0:
        near_low_curr = 1.0 if abs(dist_sess_low) / atr < 0.04 else 0.0
    else:
        near_low_curr = None
    state.near_low_60.append(near_low_curr)
    near_low_vals = [v for v in state.near_low_60 if v is not None]
    if len(near_low_vals) >= 10:
        excess_low = float(sum(near_low_vals))
        out["ctx_excess_low_bars"] = excess_low
        out["ctx_poor_low"] = 1.0 if excess_low < 3 else 0.0
    else:
        out["ctx_excess_low_bars"] = np.nan
        out["ctx_poor_low"] = 0.0

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-engine #9 — GROUPE D (Delta divergence reconstruction SC ID33 - 4 features)
# ═══════════════════════════════════════════════════════════════════════════════
# Reproduit fidelement Sierra Chart "Daily OHLC" ID33 "LINKED TO DELTA DIVERGENCE"
# (SG2=High cumulatif, SG3=Low cumulatif par trading session CME).
#
# Formule SC exacte (mirror batch ligne 484-489) :
#   BUY  : AND(daily_low  < daily_low[-1],  delta_b >= 0) & same_session
#   SELL : AND(daily_high > daily_high[-1], delta_b <= 0) & same_session
#
# DIVERGENCE BATCH/STREAM DOCUMENTEE :
# delta_div_strength batch fait quantile(0.995) sur TOUTES les valeurs actives
# du DataFrame (forward-looking). En stream impossible sans buffer infini.
# Decision : streaming output raw_strength SANS clip. Distribution shift
# acceptable (intensite max naturellement bornee par |delta_bar| qui est
# deja borne en pratique).


from datetime import timedelta, timezone as dt_timezone
from datetime import datetime as dt_datetime
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET_TZ = _ZoneInfo("America/New_York")
except ImportError:
    _ET_TZ = None


def _ts_to_trading_date_cme(ts_ms: float):
    """Convertit ts_ms epoch -> trading_date CME (18:00 ET cutoff).

    Mirror batch ligne 461-467 :
      dt_utc = pd.to_datetime(ts_ms, unit='ms', utc=True)
      dt_et = dt_utc.tz_convert('America/New_York')
      shift_day = 1 si hour_ET >= 18 sinon 0
      trading_date = dt_et.normalize().date() + shift_day_days
    """
    if ts_ms is None or pd.isna(ts_ms):
        return None
    try:
        ts_int = int(ts_ms)
    except (TypeError, ValueError):
        return None
    if _ET_TZ is None:
        return None
    dt_utc = dt_datetime.fromtimestamp(ts_int / 1000.0, tz=dt_timezone.utc)
    dt_et = dt_utc.astimezone(_ET_TZ)
    if dt_et.hour >= 18:
        return (dt_et + timedelta(days=1)).date()
    return dt_et.date()


def add_rolling_features_delta_div_streaming(
    row: dict,
    state: RollingFeaturesState,
) -> dict:
    """Sub-engine #9 — 4 features GROUPE D delta divergence streaming.

    Features :
      delta_div_buy_clean    - 1 si new daily low ET delta_b >= 0
      delta_div_sell_clean   - 1 si new daily high ET delta_b <= 0
      delta_divergence_clean - buy - sell (-1/0/+1)
      delta_div_strength     - magnitude |delta_b| si div active (SANS clip
                                stream, divergence vs batch p99.5 documentee)

    Args:
        row : dict avec bar_high, bar_low, delta_bar, ts.
        state : RollingFeaturesState mutable.

    Returns:
        dict row + 4 features.
    """
    out = dict(row)

    bar_high = _safe_float(out.get("bar_high"))
    bar_low = _safe_float(out.get("bar_low"))
    delta_b = _safe_float(out.get("delta_bar"))
    if delta_b is None:
        delta_b = 0.0  # batch fillna(0)
    ts = _safe_float(out.get("ts"))

    # 1. Calcul trading_date_CME
    trading_date = _ts_to_trading_date_cme(ts)
    if trading_date is None or bar_high is None or bar_low is None:
        # Inputs critiques manquants -> output 0 (batch ligne 502-505)
        out["delta_div_buy_clean"] = 0
        out["delta_div_sell_clean"] = 0
        out["delta_divergence_clean"] = 0
        out["delta_div_strength"] = 0.0
        return out

    # 2. same_session = trading_date == prev_trading_date
    same_session = (
        state.prev_trading_date is not None
        and trading_date == state.prev_trading_date
    )

    # 3. Reset state si nouvelle session
    if trading_date != state.current_trading_date:
        state.current_trading_date = trading_date
        state.daily_high_running = None
        state.daily_low_running = None

    # 4. Snapshot AVANT update : ce sont les daily_high/low de la bar PRECEDENTE
    # (mirror batch shift(1) sur cummax/cummin)
    prev_dh = state.daily_high_running
    prev_dl = state.daily_low_running

    # 5. Update daily running avec bar courante (mirror cummax/cummin)
    if state.daily_high_running is None or bar_high > state.daily_high_running:
        state.daily_high_running = bar_high
    if state.daily_low_running is None or bar_low < state.daily_low_running:
        state.daily_low_running = bar_low

    # 6. Conditions divergence (mirror batch formule SC exacte)
    div_buy = 0
    div_sell = 0
    if same_session and prev_dl is not None and prev_dh is not None:
        # BUY : new daily low + buyers en embuscade (delta >= 0)
        if state.daily_low_running < prev_dl and delta_b >= 0:
            div_buy = 1
        # SELL : new daily high + sellers en embuscade (delta <= 0)
        if state.daily_high_running > prev_dh and delta_b <= 0:
            div_sell = 1

    out["delta_div_buy_clean"] = div_buy
    out["delta_div_sell_clean"] = div_sell
    out["delta_divergence_clean"] = div_buy - div_sell

    # 7. delta_div_strength : magnitude |delta_b| si div active
    # NB : pas de winsorization p99.5 en stream (forward-looking impossible)
    # Distribution shift vs batch documente.
    if div_buy or div_sell:
        out["delta_div_strength"] = abs(delta_b)
    else:
        out["delta_div_strength"] = 0.0

    # 8. Update prev_trading_date pour same_session next bar
    state.prev_trading_date = trading_date

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-engine #10 — GROUPE E (Trapped traders + session-specific + confluence)
# ═══════════════════════════════════════════════════════════════════════════════
# 12 features finales du module rolling_features.py.
# Note : div_forward_return_20b NON portable streaming (lookahead -20).
#
# Convention pipeline complet :
#   basic -> medium -> advanced -> delta_div -> session_confluence


def add_rolling_features_session_confluence_streaming(
    row: dict,
    state: RollingFeaturesState,
) -> dict:
    """Sub-engine #10 — 12 features GROUPE E streaming.

    Features :
      TRAPPED TRADERS (2) :
        ctx_double_top_trap      - retest swing + div + confirmation
        ctx_momentum_exhaustion  - mouvement fort + rejet intra-barre

      SESSION-SPECIFIC (3) :
        ctx_cvd_session    - cumsum delta reset par session
        ctx_rvol_session   - volume / rolling_mean 30 dans session
        ctx_session_phase  - phase fine (0-7 enum)

      DIVERGENCE RECENCE (3) :
        ctx_bars_since_div - barres depuis last delta_divergence_clean
        ctx_div_density_20 - sum divergences sur 20
        ctx_div_at_swing   - confluence div + swing proximity

      DIVERGENCE CONFLUENCE (4) :
        div_at_key_level_ticks   - min dist niveaux cles si div active
        div_confluence_dmp       - score 0-4 (DMP pur)
        div_regime_proxy_ok      - regime favorable proxies
        div_confluence_with_regime - score 0-5 (DMP + regime)

    Convention NaN/None : fallback explicite 0/NaN selon batch.
    """
    out = dict(row)

    # ─── Inputs ────────────────────────────────────────────────────────────
    rhdv = _safe_float(out.get("retest_high_delta_div")) or 0
    bsrh = _safe_float(out.get("bars_since_retest_high"))
    if bsrh is None or pd.isna(bsrh):
        bsrh = 999.0
    rldv = _safe_float(out.get("retest_low_delta_div")) or 0
    bsrl = _safe_float(out.get("bars_since_retest_low"))
    if bsrl is None or pd.isna(bsrl):
        bsrl = 999.0
    cvd_dir = _safe_float(out.get("cvd_day_dir")) or 0
    diag = _safe_float(out.get("diag_imbalance")) or 0
    mom = _safe_float(out.get("momentum_5b")) or 0
    finish = _safe_float(out.get("finish_strength")) or 0
    session_raw = out.get("session")
    delta = _safe_float(out.get("delta_bar")) or 0
    vol = _safe_float(out.get("total_vol")) or 0
    ts = _safe_float(out.get("ts"))
    ib_complete = _safe_float(out.get("ib_complete")) or 0
    dist_swing_low = _safe_float(out.get("dist_swing_low"))
    dist_swing_high = _safe_float(out.get("dist_swing_high"))
    vix_regime = _safe_float(out.get("vix_regime")) or 0
    gex_flip = _safe_float(out.get("bool_gex_flip_zone")) or 0
    bn_absorb_bid = _safe_float(out.get("bn_absorb_bid")) or 0
    bn_absorb_ask = _safe_float(out.get("bn_absorb_ask")) or 0
    rvol_zscore = _safe_float(out.get("rvol_zscore"))
    rvol_raw = _safe_float(out.get("rvol"))
    # Use delta_divergence_clean from GROUPE D (chain pipeline)
    dd = _safe_float(out.get("delta_divergence_clean")) or 0

    # Cast session int
    try:
        session = int(session_raw) if session_raw is not None else -1
    except (TypeError, ValueError):
        session = -1

    # ─── 39. ctx_double_top_trap ────────────────────────────────────────────
    # Mirror batch ligne 554-556 :
    #   dt_bear = (rhdv==1) & (bsrh<=5) & ((cvd_dir==-1) | (diag<0))
    #   dt_bull = (rldv==1) & (bsrl<=5) & ((cvd_dir==1) | (diag>0))
    dt_bear = (rhdv == 1) and (bsrh <= 5) and ((cvd_dir == -1) or (diag < 0))
    dt_bull = (rldv == 1) and (bsrl <= 5) and ((cvd_dir == 1) or (diag > 0))
    if dt_bear:
        out["ctx_double_top_trap"] = -1.0
    elif dt_bull:
        out["ctx_double_top_trap"] = 1.0
    else:
        out["ctx_double_top_trap"] = 0.0

    # ─── 40. ctx_momentum_exhaustion ───────────────────────────────────────
    # Mirror batch ligne 566-569 :
    #   bear_exhaust = (mom<-8) & (finish>10) -> BUY (1)
    #   bull_exhaust = (mom>8) & (finish<-10) -> SELL (-1)
    if mom < -8 and finish > 10:
        out["ctx_momentum_exhaustion"] = 1.0
    elif mom > 8 and finish < -10:
        out["ctx_momentum_exhaustion"] = -1.0
    else:
        out["ctx_momentum_exhaustion"] = 0.0

    # ─── 36. ctx_cvd_session ────────────────────────────────────────────────
    # Mirror batch ligne 580-583 : delta.groupby(session_change.cumsum()).cumsum()
    # Reset cumsum a chaque changement de session.
    if session != state.current_session:
        state.cvd_session_running = 0.0
        state.current_session = session
        # Reset vol_session_window aussi
        state.vol_session_window.clear()
    state.cvd_session_running += delta
    out["ctx_cvd_session"] = state.cvd_session_running

    # ─── 37. ctx_rvol_session ──────────────────────────────────────────────
    # Mirror batch ligne 595-600 : rolling(30, min_p=5).mean() dans la session
    # Si session_avg > 0 : vol / session_avg, sinon 1.0
    state.vol_session_window.append(vol)
    vol_vals_session = [v for v in state.vol_session_window if v > 0]
    # Note : batch utilise .mean() qui ignore NaN. Synth vol > 0 toujours.
    # min_periods=5 mirror batch
    if len(state.vol_session_window) >= 5:
        session_avg = sum(state.vol_session_window) / len(state.vol_session_window)
        if session_avg > 0:
            out["ctx_rvol_session"] = vol / session_avg
        else:
            out["ctx_rvol_session"] = 1.0
    else:
        out["ctx_rvol_session"] = 1.0

    # ─── 38. ctx_session_phase ─────────────────────────────────────────────
    # Mirror batch ligne 608-625 (simplified)
    # 0=Asia, 2=London, 4=IB_Formation US default, 5=Mid_AM si ib_complete=1
    phase = 0
    if session == 0:
        phase = 0  # Asia
    elif session == 1:
        phase = 2  # London
    elif session == 2:
        phase = 4  # default IB_Formation
        if ib_complete == 1:
            phase = 5  # Mid_AM par defaut post-IB
    out["ctx_session_phase"] = phase

    # ─── 33. ctx_bars_since_div ────────────────────────────────────────────
    # ATTENTION BATCH BUG (rolling_features.py ligne 514-518) :
    #   cumfire = div_fired.cumsum()
    #   last_fire_idx = cumfire.where(div_fired == 1).ffill()  # stocke cumfire, pas l'index
    #   bars_since = cumfire - last_fire_idx                    # toujours 0 entre divs
    # Resultat batch : NaN tant qu'aucune div vue, puis 0 partout apres.
    # La variable est dead-code (jamais utilisee semantiquement par le bot).
    #
    # Pour PARITE batch on reproduit le bug : NaN si aucune div, 0 sinon.
    # Le compteur REEL (correct semantically) est trace dans state.bars_since_last_div
    # mais n'est PAS exporte. Bug a fixer dans batch dans une session dediee.
    div_fired_this_bar = 1 if dd != 0 else 0
    state.div_fired_long.append(div_fired_this_bar)
    if div_fired_this_bar == 1:
        state.bars_since_last_div = 0
    elif state.bars_since_last_div is not None:
        state.bars_since_last_div += 1
    # Mirror batch BUG : 0 si div vue, NaN sinon
    if state.bars_since_last_div is not None:
        out["ctx_bars_since_div"] = 0.0
    else:
        out["ctx_bars_since_div"] = np.nan

    # ─── 34. ctx_div_density_20 ────────────────────────────────────────────
    # Mirror batch ligne 522 : div_fired.rolling(20, min_p=1).sum()
    out["ctx_div_density_20"] = float(sum(state.div_fired_long))

    # ─── 35. ctx_div_at_swing ──────────────────────────────────────────────
    # Mirror batch ligne 527-537 :
    #   near_swing_low = |dist_swing_low|.fillna(999) < 15
    #   near_swing_high = |dist_swing_high|.fillna(999) < 15
    #   +1 si (dd==1) & near_swing_low, -1 si (dd==-1) & near_swing_high
    near_sl = (abs(dist_swing_low) < 15) if dist_swing_low is not None else False
    near_sh = (abs(dist_swing_high) < 15) if dist_swing_high is not None else False
    if dd == 1 and near_sl:
        out["ctx_div_at_swing"] = 1.0
    elif dd == -1 and near_sh:
        out["ctx_div_at_swing"] = -1.0
    else:
        out["ctx_div_at_swing"] = 0.0

    # ─── 41. div_at_key_level_ticks ────────────────────────────────────────
    # Mirror batch ligne 636-651 : min(|dist_*|) parmi 14 niveaux si div active
    dist_cols = [
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte",
        "dist_swing_high", "dist_swing_low",
        "dist_cur_vah", "dist_cur_val",
        "dist_ib_high", "dist_ib_low",
        "dist_blind_nearest_up", "dist_blind_nearest_dn",
        "next_wall_dist_ticks",
    ]
    dist_vals = []
    for c in dist_cols:
        v = _safe_float(out.get(c))
        if v is not None:
            dist_vals.append(abs(v))
    if dd != 0 and dist_vals:
        out["div_at_key_level_ticks"] = min(dist_vals)
    else:
        out["div_at_key_level_ticks"] = np.nan

    # ─── 42. div_confluence_dmp ────────────────────────────────────────────
    # Mirror batch ligne 655-680 : score 0-4 (DMP pur)
    div_active = 1 if dd != 0 else 0
    at_level = 0
    div_level_val = out.get("div_at_key_level_ticks")
    if (
        div_level_val is not None and not pd.isna(div_level_val)
        and div_level_val < 20 and dd != 0
    ):
        at_level = 1
    # absorb : div buy + bn_absorb_bid OU div sell + bn_absorb_ask
    absorb_score = 0
    if dd == 1 and bn_absorb_bid > 0:
        absorb_score = 1
    elif dd == -1 and bn_absorb_ask > 0:
        absorb_score = 1
    # rvol_score : |rvol_zscore| >= 2 OU rvol >= 2 (selon col dispo)
    rvol_score = 0
    if rvol_zscore is not None and abs(rvol_zscore) >= 2.0 and dd != 0:
        rvol_score = 1
    elif rvol_raw is not None and rvol_raw >= 2.0 and dd != 0:
        rvol_score = 1
    out["div_confluence_dmp"] = div_active + at_level + absorb_score + rvol_score

    # ─── 44. div_regime_proxy_ok ───────────────────────────────────────────
    # Mirror batch ligne 700-705 : vix_regime>=1 ET bool_gex_flip_zone==0
    out["div_regime_proxy_ok"] = 1 if (vix_regime >= 1 and gex_flip == 0) else 0

    # ─── 45. div_confluence_with_regime ────────────────────────────────────
    # Mirror batch ligne 707-711 : div_confluence_dmp + div_regime_proxy_ok
    out["div_confluence_with_regime"] = (
        out["div_confluence_dmp"] + out["div_regime_proxy_ok"]
    )

    return out




