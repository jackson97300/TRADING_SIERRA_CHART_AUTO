"""
Dalton Features — L1 + L2 + L4 (audit 21/04/2026)
===================================================

Implementation des 3 priorites absolues de l'audit Dalton :
- L1 : Responsive vs Initiating (gap critique #1)
- L2 : VA Placement day-over-day (gap critique #2)
- L4 : RISK gate anti-POC-magnet trend day (erreur #1 retail)

PHILOSOPHIE DALTON
------------------
Un mouvement de prix se qualifie differemment selon le contexte :
- RESPONSIVE : prix reagit a la valeur veille (mean reversion probable)
- INITIATING : acteur initie nouveau move (continuation probable)
Faire l'inverse = perdre.

Dalton Markets in Profile, ch. 3-4 : "range extension buy SOUS PVAL =
responsive ; AU-DESSUS PVAH = initiating. La difference determine le sens."

VA PLACEMENT
------------
Chaque jour, comparer VA jour vs VA veille :
- HIGHER : VA entierement au-dessus PVAH
- OVERLAP_HIGHER : chevauche, legerement haut
- OVERLAP : VA ≈ VA veille
- OVERLAP_LOWER : chevauche, bas
- LOWER : VA entierement sous PVAL

Regle : 3+ jours consecutifs SANS overlap = TREND CONFIRME.

ANTI-POC-MAGNET
---------------
60-70% des pertes retail = trader mean reversion (POC magnet) en trend day.
En trend day, le prix NE REVIENT PAS au POC. VETO ces trades.

USAGE
-----
Stateful helper - maintient buffers en memoire pour features rolling.

  helper = DaltonFeatureHelper(va_placement_window_days=10)
  for bar in bars_stream:
      features = helper.compute(bar)
      # features = {"ctx_responsive_buy": 0/1, "ctx_initiating_buy": 0/1,
      #             "ctx_va_placement": -2/-1/0/1/2, "ctx_va_migration_streak": N,
      #             "ctx_anti_poc_magnet_veto": bool}

SOURCE RAPPORT
--------------
DOCS/DALTON_AUDIT_JACKSON_20260421.md (Sections 2 + 3)

Auteur : Claude (mentor Jackson) — 21/04/2026
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


TICK_SIZE_NQ = 0.25


def _finite(v):
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# L1 — Responsive vs Initiating
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResponsiveInitiatingState:
    """
    State tracker pour detecter :
    - RESPONSIVE : prix est SORTI de la VA veille (ex: sous PVAL) puis REVIENT dedans
    - INITIATING : prix a CASSE au-dessus PVAH (ou sous PVAL) avec volume
    """
    window_bars: int = 20  # Lookback pour detecter sortie recente
    out_below_pval_bar: int = -9999  # Bar index ou prix est sorti sous PVAL
    out_above_pvah_bar: int = -9999  # Bar index ou prix est sorti au-dessus PVAH
    current_bar: int = 0
    vol_buffer: deque = field(default_factory=lambda: deque(maxlen=20))


def compute_responsive_initiating(row: pd.Series,
                                   state: ResponsiveInitiatingState) -> dict:
    """
    Calcule les 5 features Responsive/Initiating sur la barre courante.

    Convention DMP :
    - dist_prev_vah = PVAH - price (ticks). dist > 0 = prix SOUS PVAH.
    - dist_prev_val = PVAL - price. dist < 0 = prix AU-DESSUS PVAL.

    Logique :
    - Prix sous PVAL : dist_prev_val > 0
    - Prix au-dessus PVAH : dist_prev_vah < 0
    - Prix dans VA veille : dist_prev_val < 0 AND dist_prev_vah > 0

    Returns:
        dict avec 5 features int 0/1 + 1 float ratio
    """
    state.current_bar += 1

    dpvah = _finite(row.get("dist_prev_vah"))      # ticks, = PVAH - price
    dpval = _finite(row.get("dist_prev_val"))      # ticks, = PVAL - price
    vol = _finite(row.get("total_vol")) or 0
    state.vol_buffer.append(vol)

    # Defaults si features manquantes
    if dpvah is None or dpval is None:
        return {
            "ctx_responsive_buy": 0,
            "ctx_responsive_sell": 0,
            "ctx_initiating_buy": 0,
            "ctx_initiating_sell": 0,
            "ctx_init_vs_resp_ratio": 0.0,
        }

    # Etat actuel
    below_pval = dpval > 0     # prix SOUS PVAL (dist positive)
    above_pvah = dpvah < 0     # prix AU-DESSUS PVAH (dist negative)
    inside_va = (dpval < 0) and (dpvah > 0)

    # Update tracking : note quand le prix SORT de la VA
    if below_pval:
        state.out_below_pval_bar = state.current_bar
    if above_pvah:
        state.out_above_pvah_bar = state.current_bar

    # Volume spike (pour initiating)
    vol_spike = False
    if len(state.vol_buffer) >= 10:
        avg_vol = sum(list(state.vol_buffer)[-11:-1]) / 10
        if avg_vol > 0 and vol / avg_vol >= 1.5:
            vol_spike = True

    # RESPONSIVE BUY : prix etait sous PVAL recemment, maintenant revenu dedans
    bars_since_out_pval = state.current_bar - state.out_below_pval_bar
    responsive_buy = 1 if (inside_va and 0 < bars_since_out_pval <= state.window_bars) else 0

    # RESPONSIVE SELL : prix etait au-dessus PVAH recemment, revenu dedans
    bars_since_out_pvah = state.current_bar - state.out_above_pvah_bar
    responsive_sell = 1 if (inside_va and 0 < bars_since_out_pvah <= state.window_bars) else 0

    # INITIATING BUY : prix est au-dessus PVAH MAINTENANT + volume spike
    initiating_buy = 1 if (above_pvah and vol_spike) else 0

    # INITIATING SELL : prix est sous PVAL + volume spike
    initiating_sell = 1 if (below_pval and vol_spike) else 0

    # Ratio : init_net - resp_net
    init_total = initiating_buy + initiating_sell
    resp_total = responsive_buy + responsive_sell
    total = init_total + resp_total
    ratio = (init_total - resp_total) / total if total > 0 else 0.0

    return {
        "ctx_responsive_buy": responsive_buy,
        "ctx_responsive_sell": responsive_sell,
        "ctx_initiating_buy": initiating_buy,
        "ctx_initiating_sell": initiating_sell,
        "ctx_init_vs_resp_ratio": ratio,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# L2 — VA Placement day-over-day
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VaPlacementState:
    """
    Tracker VA placement jour-sur-jour.

    Stocke pour chaque jour : VAH et VAL (derives du prev_vah/val en fin de session).
    Compare le jour courant au jour precedent.
    """
    history: deque = field(default_factory=lambda: deque(maxlen=10))  # 10 derniers jours
    current_date: Optional[str] = None
    current_vah_accum: list = field(default_factory=list)  # Echantillons cur_vah du jour
    current_val_accum: list = field(default_factory=list)
    migration_streak: int = 0
    last_placement: int = 0  # -2, -1, 0, 1, 2


def _classify_va_placement(today_vah: float, today_val: float,
                          prev_vah: float, prev_val: float,
                          overlap_threshold: float = 0.1) -> tuple[int, float]:
    """
    Classifier VA placement en 5 classes.

    Returns:
        (placement, overlap_pct)
        placement : -2 LOWER / -1 OVERLAP_LOWER / 0 OVERLAP / 1 OVERLAP_HIGHER / 2 HIGHER
        overlap_pct : 0.0 a 1.0
    """
    # Compute overlap (zone commune)
    overlap_low = max(today_val, prev_val)
    overlap_high = min(today_vah, prev_vah)
    overlap_width = max(0.0, overlap_high - overlap_low)
    today_width = today_vah - today_val
    prev_width = prev_vah - prev_val
    min_width = min(today_width, prev_width)
    overlap_pct = overlap_width / min_width if min_width > 0 else 0.0

    # Classification
    if today_val > prev_vah:
        return (2, 0.0)  # HIGHER strict
    if today_vah < prev_val:
        return (-2, 0.0)  # LOWER strict
    # Overlap
    if overlap_pct > overlap_threshold:
        mid_today = (today_vah + today_val) / 2
        mid_prev = (prev_vah + prev_val) / 2
        if mid_today > mid_prev * 1.001:
            return (1, overlap_pct)  # OVERLAP_HIGHER
        if mid_today < mid_prev * 0.999:
            return (-1, overlap_pct)  # OVERLAP_LOWER
        return (0, overlap_pct)  # OVERLAP
    return (0, overlap_pct)


def compute_va_placement(row: pd.Series, state: VaPlacementState) -> dict:
    """
    Update state avec row courante, retourne features VA placement.

    Retourne :
        ctx_va_placement : -2 a 2
        ctx_va_overlap_pct : 0 a 1
        ctx_va_migration_streak : N (nb jours consecutifs sans overlap)
    """
    # Date courante
    ts = _finite(row.get("ts"))
    if ts is None:
        return {"ctx_va_placement": state.last_placement,
                "ctx_va_overlap_pct": 0.0,
                "ctx_va_migration_streak": state.migration_streak}

    import datetime as dt
    date_utc = dt.datetime.fromtimestamp(ts / 1000, tz=dt.timezone.utc).date()
    date_str = date_utc.isoformat()

    # Cur_vah/val absolus (calcul : price + (dist = niveau - price) donne niveau)
    price = _finite(row.get("price"))
    dcvah_atr = _finite(row.get("dist_cur_vah_atr"))
    dcval_atr = _finite(row.get("dist_cur_val_atr"))
    atr = _finite(row.get("atr"))

    # Besoin de niveaux ABS cur_vah / cur_val pour classification
    # dist_cur_vah_atr = (cur_vah - price) / atr. Donc cur_vah = price + dist_cur_vah_atr * atr
    # atr est en TICKS d'apres lessons.md 09/04
    if None in (price, dcvah_atr, dcval_atr, atr):
        return {"ctx_va_placement": state.last_placement,
                "ctx_va_overlap_pct": 0.0,
                "ctx_va_migration_streak": state.migration_streak}

    cur_vah = price + dcvah_atr * atr * TICK_SIZE_NQ
    cur_val = price + dcval_atr * atr * TICK_SIZE_NQ

    # Detection changement de jour : enregistre jour precedent
    if state.current_date is not None and date_str != state.current_date:
        if state.current_vah_accum and state.current_val_accum:
            # Moyenne des vah/val du jour ecoule
            day_vah = sum(state.current_vah_accum) / len(state.current_vah_accum)
            day_val = sum(state.current_val_accum) / len(state.current_val_accum)
            state.history.append({
                "date": state.current_date,
                "vah": day_vah,
                "val": day_val,
            })
        state.current_vah_accum = []
        state.current_val_accum = []

    state.current_date = date_str
    if cur_vah > cur_val:
        state.current_vah_accum.append(cur_vah)
        state.current_val_accum.append(cur_val)

    # Classification vs jour precedent
    if len(state.history) == 0 or not state.current_vah_accum:
        return {"ctx_va_placement": 0,
                "ctx_va_overlap_pct": 1.0,
                "ctx_va_migration_streak": 0}

    today_vah = sum(state.current_vah_accum) / len(state.current_vah_accum)
    today_val = sum(state.current_val_accum) / len(state.current_val_accum)
    prev = state.history[-1]

    placement, overlap_pct = _classify_va_placement(today_vah, today_val,
                                                    prev["vah"], prev["val"])

    # Update migration_streak : increment si no overlap (|placement|>=2), reset sinon
    if abs(placement) >= 2 and placement == state.last_placement:
        state.migration_streak += 1
    elif abs(placement) < 2:
        state.migration_streak = 0
    else:
        state.migration_streak = 1  # 1er jour sans overlap

    state.last_placement = placement

    return {
        "ctx_va_placement": placement,
        "ctx_va_overlap_pct": overlap_pct,
        "ctx_va_migration_streak": state.migration_streak,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# L4 — RISK gate anti-POC-magnet trend day
# ═══════════════════════════════════════════════════════════════════════════════

def check_anti_poc_magnet(row: pd.Series, trade_thesis: str,
                          trend_day_threshold: float = 0.6,
                          poc_proximity_atr: float = 0.5) -> tuple[bool, str]:
    """
    VETO si trade thesis = "return_to_POC" EN trend day confirme.

    Args:
        row : barre courante
        trade_thesis : {"return_to_POC", "breakout_continuation", "range_fade", ...}
        trend_day_threshold : seuil ctx_trend_day_score au-dessus duquel = trend day
        poc_proximity_atr : seuil dist_cur_vpoc_atr absolue sous lequel on considere
                           que le trade VISE le POC.

    Returns:
        (allow: bool, reason: str)
        allow=False -> veto
    """
    trend_score = _finite(row.get("ctx_trend_day_score"))
    dist_vpoc_atr = _finite(row.get("dist_cur_vpoc_atr"))

    # Si features manquantes -> autorise (fail-open, le meta-labeler filtrera)
    if trend_score is None or dist_vpoc_atr is None:
        return (True, "features_missing")

    # Check trend day
    if abs(trend_score) < trend_day_threshold:
        return (True, f"not_trend_day_{trend_score:.2f}")

    # Check si trade vise POC
    if trade_thesis not in ("return_to_POC", "revert_to_POC", "mean_reversion_POC"):
        return (True, f"thesis_not_poc_{trade_thesis}")

    # Si prix eloigne du POC, pas un magnet trade
    if abs(dist_vpoc_atr) > poc_proximity_atr:
        return (True, f"poc_too_far_{dist_vpoc_atr:.2f}atr")

    # VETO applique
    return (False, f"dalton_anti_poc_magnet_veto trend={trend_score:.2f} dist_vpoc={dist_vpoc_atr:.2f}")


# ═══════════════════════════════════════════════════════════════════════════════
# L3 — Day Types Dalton enum 6 classes
# ═══════════════════════════════════════════════════════════════════════════════

# MIA day_type actuel (5 classes, DMP_OpenType.h)
DAY_TYPE_MIA_NON_TREND = 0   # IB < 15% ATR
DAY_TYPE_MIA_NORMAL    = 1   # IB > 80% ATR
DAY_TYPE_MIA_NORMVAR   = 2   # Ext 1 cote (42% defaut)
DAY_TYPE_MIA_NEUTRAL   = 3   # Ext 2 cotes + close milieu (30%)
DAY_TYPE_MIA_TREND     = 4   # Ext > 2x IB (19%)

# Dalton 6 classes canoniques (L3)
DAY_TYPE_DALTON_NORMAL        = 0  # IB range, respect IB
DAY_TYPE_DALTON_NORMAL_VAR    = 1  # Ext 1 cote, default
DAY_TYPE_DALTON_NEUTRAL       = 2  # Ext 2 cotes, close milieu
DAY_TYPE_DALTON_NEUTRAL_EXT   = 3  # Ext 2 cotes, close HORS IB
DAY_TYPE_DALTON_TREND         = 4  # Ext massive 1 cote + close extreme
DAY_TYPE_DALTON_DOUBLE_DIST   = 5  # IB tres narrow + breakout tardif, 2 zones volume

DAY_TYPE_DALTON_NAMES = {
    0: "Normal", 1: "NormalVariation", 2: "Neutral",
    3: "NeutralExtreme", 4: "Trend", 5: "DoubleDistribution",
}


def compute_day_type_dalton(row: pd.Series, context: Optional[dict] = None) -> int:
    """
    Enrichir notre day_type 5 classes -> Dalton 6 classes.

    Ajoute :
    - NEUTRAL_EXTREME : notre NEUTRAL (3) + close HORS IB (au lieu de dans IB)
    - DOUBLE_DIST : NORMVAR/TREND + ib_is_narrow tres fort + extension tardive

    Input features requises :
    - day_type (MIA enum 5 classes)
    - ib_broken_up, ib_broken_down (les 2 cotes casses = Neutral)
    - range_pos (position close dans range du jour)
    - ib_is_narrow (< 15% ATR typically)
    - ib_range_atr

    Returns Dalton enum 6 classes (0-5).
    """
    dt_mia = _finite(row.get("day_type"))
    if dt_mia is None:
        return DAY_TYPE_DALTON_NORMAL  # default

    dt_mia = int(dt_mia)
    ib_broken_up = int(_finite(row.get("ib_broken_up")) or 0)
    ib_broken_dn = int(_finite(row.get("ib_broken_down")) or 0)
    range_pos = _finite(row.get("range_pos"))  # 0-100 typiquement
    ib_is_narrow = int(_finite(row.get("ib_is_narrow")) or 0)
    ib_range_atr = _finite(row.get("ib_range_atr"))

    # DoubleDistribution detection (IB tres narrow + cassure tardive + close loin de POC)
    # Proxy simple : ib_is_narrow=1 ET (trend ou normvar)
    # Condition stricte : IB < 0.3 ATR ET close eloigne de IB midpoint
    if ib_is_narrow == 1 and ib_range_atr is not None and ib_range_atr < 0.3:
        if dt_mia in (DAY_TYPE_MIA_NORMVAR, DAY_TYPE_MIA_TREND):
            return DAY_TYPE_DALTON_DOUBLE_DIST

    # NeutralExtreme : MIA Neutral (3) + close hors IB (range_pos extreme)
    if dt_mia == DAY_TYPE_MIA_NEUTRAL:
        if range_pos is not None and (range_pos > 80 or range_pos < 20):
            return DAY_TYPE_DALTON_NEUTRAL_EXT
        return DAY_TYPE_DALTON_NEUTRAL

    # Mapping simple des autres
    mapping = {
        DAY_TYPE_MIA_NON_TREND: DAY_TYPE_DALTON_NORMAL,   # NonTrend -> Normal
        DAY_TYPE_MIA_NORMAL:    DAY_TYPE_DALTON_NORMAL,
        DAY_TYPE_MIA_NORMVAR:   DAY_TYPE_DALTON_NORMAL_VAR,
        DAY_TYPE_MIA_TREND:     DAY_TYPE_DALTON_TREND,
    }
    return mapping.get(dt_mia, DAY_TYPE_DALTON_NORMAL)


# ═══════════════════════════════════════════════════════════════════════════════
# L5 — Open Type regime switch (meta-labeler size multiplier)
# ═══════════════════════════════════════════════════════════════════════════════

# MIA open_type codes (DMP_OpenType.h)
OT_UNKNOWN = 0
OT_OD_UP = 1;   OT_OD_DOWN = 2
OT_OTD_UP = 3;  OT_OTD_DOWN = 4
OT_ORR_UP = 5;  OT_ORR_DOWN = 6
OT_OAIR = 7
OT_OAOR_UP = 8; OT_OAOR_DOWN = 9
OT_ODF_UP = 10; OT_ODF_DOWN = 11  # Open Drive FAIL = DANGER

# Size multipliers selon confidence Dalton + innovation MIA ODF
OPEN_TYPE_SIZE_MULT = {
    OT_UNKNOWN:    0.5,   # Avant 10h30, prudence
    OT_OD_UP:      1.2,   # Trend Day 85% probable -> size +20%
    OT_OD_DOWN:    1.2,
    OT_OTD_UP:     1.1,   # 70% confidence -> size +10%
    OT_OTD_DOWN:   1.1,
    OT_ORR_UP:     1.0,   # 60% -> baseline
    OT_ORR_DOWN:   1.0,
    OT_OAIR:       0.7,   # 30% range day -> reduction
    OT_OAOR_UP:    0.9,   # 65% gap -> legere reduction
    OT_OAOR_DOWN:  0.9,
    OT_ODF_UP:     0.5,   # Open Drive FAIL = reversal violent -> tres prudent
    OT_ODF_DOWN:   0.5,
}

OPEN_TYPE_NAMES = {
    0: "UNKNOWN", 1: "OD_UP", 2: "OD_DOWN",
    3: "OTD_UP", 4: "OTD_DOWN", 5: "ORR_UP", 6: "ORR_DOWN",
    7: "OAIR", 8: "OAOR_UP", 9: "OAOR_DOWN",
    10: "ODF_UP", 11: "ODF_DOWN",
}


def compute_open_type_size_mult(row: pd.Series) -> tuple[float, str]:
    """
    Retourne multiplicateur size base sur open_type MIA enum 12 codes.

    Exploite notre granularite (direction + ODF) pour sizing Kelly-like.

    Returns:
        (multiplier, reason_str)
    """
    ot = _finite(row.get("open_type"))
    if ot is None:
        return (0.5, "open_type_missing")

    ot_int = int(ot)
    mult = OPEN_TYPE_SIZE_MULT.get(ot_int, 0.5)
    name = OPEN_TYPE_NAMES.get(ot_int, f"OT_{ot_int}")

    # Affiner avec open_bias_conf si dispo (pondere confidence declaree)
    bias_conf = _finite(row.get("open_bias_conf"))
    if bias_conf is not None:
        # bias_conf range 0.0-1.0. Ajuste mult si conf faible : mult * (0.5 + 0.5 * bias_conf)
        # ex: bias=1.0 -> mult inchange ; bias=0.5 -> mult * 0.75 ; bias=0.0 -> mult * 0.5
        conf_factor = 0.5 + 0.5 * max(0.0, min(1.0, bias_conf))
        mult_adjusted = mult * conf_factor
        return (mult_adjusted, f"{name}_conf{bias_conf:.2f}_mult{mult_adjusted:.2f}")

    return (mult, name)


# ═══════════════════════════════════════════════════════════════════════════════
# Helper unifie
# ═══════════════════════════════════════════════════════════════════════════════

class DaltonFeatureHelper:
    """
    Helper stateful qui calcule L1 + L2 sur stream de barres.
    L4 est un check a appeler separement (pas une feature mais une gate).

    Usage :
        helper = DaltonFeatureHelper()
        for bar in bars:
            features = helper.compute(bar)
            # features = {ctx_responsive_buy, ..., ctx_va_placement, ...}

        # Puis pour chaque signal candidate :
        allow, reason = check_anti_poc_magnet(bar, thesis="return_to_POC")
    """

    def __init__(self, responsive_window_bars: int = 20):
        self.resp_state = ResponsiveInitiatingState(window_bars=responsive_window_bars)
        self.va_state = VaPlacementState()

    def compute(self, row: pd.Series) -> dict:
        features = {}
        features.update(compute_responsive_initiating(row, self.resp_state))
        features.update(compute_va_placement(row, self.va_state))
        # L3 : Day Type Dalton 6 classes
        features["ctx_day_type_dalton"] = compute_day_type_dalton(row)
        # L5 : Open Type size multiplier (Kelly-like)
        mult, reason = compute_open_type_size_mult(row)
        features["ctx_open_type_size_mult"] = mult
        features["ctx_open_type_label"] = reason
        return features

    def reset(self):
        self.resp_state = ResponsiveInitiatingState(window_bars=self.resp_state.window_bars)
        self.va_state = VaPlacementState()
