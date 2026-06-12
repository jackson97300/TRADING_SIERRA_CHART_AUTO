"""market_profile_v5.py - Phase A Market Profile enrichment Python.

Sortie audit ULTRATHINK 12/06 PM cross-check 2 agents (market-analyst +
trading-strategy-analyst). Identifies 10 angles morts du Market Profile
absent du pipeline actuel.

Phase A.2a EASY features (5) :
  1. PSD+2 / PSD-2     : Previous Standard Deviation 2 (extension SD1 existante)
  2. Open Relation     : Dalton classification OAIR/OAOR/OOR
  3. Profile Overlap   : % overlap session courante vs veille
  4. Range Extension   : RE_above/below_ib vs Initial Balance
  5. FVG (Fair Value Gap) : rolling 3-bar detector

Aucune dépendance externe (data nouvelle). Utilise features existantes :
  - prev_vwap, prev_vwap_sd1u, prev_vwap_sd1d (PSD)
  - prev_vah, prev_val, prev_vpoc, pdh, pdl, open_cash (Open Relation + Overlap)
  - cur_vah, cur_val, cur_vpoc (Overlap)
  - ib_high, ib_low, sess_high, sess_low (Range Extension)
  - bar_high, bar_low (FVG state machine)

Output : 12+ features ajoutees au payload :
  - prev_vwap_sd2u, prev_vwap_sd2d
  - open_above_prev_vah, open_within_prev_va, open_below_prev_val,
    open_outside_prev_range, open_relation_type (categorical 0-3)
  - profile_overlap_pct, profile_overlap_above_pdh, profile_overlap_below_pdl
  - range_extension_above_ib_atr, range_extension_below_ib_atr,
    range_extension_completed
  - fvg_up_active, fvg_dn_active, dist_fvg_up_nearest_atr, dist_fvg_dn_nearest_atr

Auteur : MIA Trading V5 Phase A enrichment
Date   : 2026-06-12
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# 1. PSD+2 / PSD-2 (Previous Standard Deviation 2)
# ════════════════════════════════════════════════════════════════════════════

def compute_psd_sd2_levels(payload: dict) -> dict:
    """Calcule PSD+2 / PSD-2 a partir de prev_vwap + SD1 existante.

    Convention :
      sd_unit = (prev_vwap_sd1u - prev_vwap) = ecart-type previous session
      sd2u = prev_vwap + 2 * sd_unit
      sd2d = prev_vwap - 2 * sd_unit

    Returns dict avec keys :
      prev_vwap_sd2u, prev_vwap_sd2d  (None si inputs manquants)
    """
    prev_vwap = payload.get("prev_vwap")
    sd1u = payload.get("prev_vwap_sd1u")
    sd1d = payload.get("prev_vwap_sd1d")

    if prev_vwap is None or sd1u is None or sd1d is None:
        return {"prev_vwap_sd2u": None, "prev_vwap_sd2d": None}

    try:
        sd_unit = float(sd1u) - float(prev_vwap)
        sd2u = float(prev_vwap) + 2.0 * sd_unit
        sd2d = float(prev_vwap) - 2.0 * sd_unit
    except (TypeError, ValueError):
        return {"prev_vwap_sd2u": None, "prev_vwap_sd2d": None}

    return {
        "prev_vwap_sd2u": round(sd2u, 2),
        "prev_vwap_sd2d": round(sd2d, 2),
    }


# ════════════════════════════════════════════════════════════════════════════
# 2. Open Relation Type (Dalton classification)
# ════════════════════════════════════════════════════════════════════════════

# Dalton "Markets in Profile" p.143-156 :
#   OAIR  = Open Auction In Range (open dans prev VA = continuation likely)
#   OAOR  = Open Auction Out of Range (open hors prev VA mais dans prev range)
#   OOR   = Open Outside Range (open hors prev_high ou prev_low = trend day prob)

OPEN_RELATION_OAIR = 1     # Open within prev VA
OPEN_RELATION_OAOR = 2     # Out of prev VA but within prev range
OPEN_RELATION_OOR = 3      # Outside prev range entirely
OPEN_RELATION_UNKNOWN = 0


def classify_open_relation(payload: dict) -> dict:
    """Classifie l'open vs previous session range (Dalton).

    Returns dict avec keys :
      open_above_prev_vah  : bool
      open_within_prev_va  : bool
      open_below_prev_val  : bool
      open_outside_prev_range : bool (above pdh OR below pdl)
      open_relation_type   : int (0-3, cf constants above)
    """
    open_cash = payload.get("open_cash")
    prev_vah = payload.get("prev_vah")
    prev_val = payload.get("prev_val")
    pdh = payload.get("pdh")
    pdl = payload.get("pdl")

    defaults = {
        "open_above_prev_vah": False,
        "open_within_prev_va": False,
        "open_below_prev_val": False,
        "open_outside_prev_range": False,
        "open_relation_type": OPEN_RELATION_UNKNOWN,
    }
    if any(v is None for v in (open_cash, prev_vah, prev_val, pdh, pdl)):
        return defaults

    try:
        oc = float(open_cash)
        vah = float(prev_vah)
        val = float(prev_val)
        ph = float(pdh)
        pl = float(pdl)
    except (TypeError, ValueError):
        return defaults

    above_vah = oc > vah
    below_val = oc < val
    within_va = (oc >= val) and (oc <= vah)
    outside_range = (oc > ph) or (oc < pl)

    if outside_range:
        rel_type = OPEN_RELATION_OOR
    elif within_va:
        rel_type = OPEN_RELATION_OAIR
    else:
        rel_type = OPEN_RELATION_OAOR  # Above VAH or below VAL but within range

    return {
        "open_above_prev_vah": above_vah,
        "open_within_prev_va": within_va,
        "open_below_prev_val": below_val,
        "open_outside_prev_range": outside_range,
        "open_relation_type": rel_type,
    }


# ════════════════════════════════════════════════════════════════════════════
# 3. Profile Overlap % (session courante vs veille)
# ════════════════════════════════════════════════════════════════════════════

def compute_profile_overlap(payload: dict) -> dict:
    """Calcule % overlap entre cur_va et prev_va (Dalton continuation indicator).

    Logique :
      overlap_range = max(0, min(cur_vah, prev_vah) - max(cur_val, prev_val))
      prev_va_range = prev_vah - prev_val
      overlap_pct = overlap_range / prev_va_range (si prev_va_range > 0)

    Egalement : overlap_above_pdh = max(0, cur_vah - pdh) / cur_va_range
    Et         overlap_below_pdl = max(0, pdl - cur_val) / cur_va_range

    Returns dict :
      profile_overlap_pct       : float 0-1 (overlap session vs veille)
      profile_overlap_above_pdh : float 0-1 (extension haut)
      profile_overlap_below_pdl : float 0-1 (extension bas)
    """
    cur_vah = payload.get("cur_vah")
    cur_val = payload.get("cur_val")
    prev_vah = payload.get("prev_vah")
    prev_val = payload.get("prev_val")
    pdh = payload.get("pdh")
    pdl = payload.get("pdl")

    defaults = {
        "profile_overlap_pct": None,
        "profile_overlap_above_pdh": None,
        "profile_overlap_below_pdl": None,
    }
    if any(v is None for v in (cur_vah, cur_val, prev_vah, prev_val)):
        return defaults

    try:
        cvah = float(cur_vah)
        cval = float(cur_val)
        pvah = float(prev_vah)
        pval = float(prev_val)
    except (TypeError, ValueError):
        return defaults

    prev_va_range = pvah - pval
    cur_va_range = cvah - cval
    if prev_va_range <= 0 or cur_va_range <= 0:
        return defaults

    overlap_range = max(0.0, min(cvah, pvah) - max(cval, pval))
    overlap_pct = overlap_range / prev_va_range

    above_pdh = 0.0
    below_pdl = 0.0
    if pdh is not None:
        try:
            ph = float(pdh)
            above_pdh = max(0.0, cvah - ph) / cur_va_range
        except (TypeError, ValueError):
            pass
    if pdl is not None:
        try:
            pl = float(pdl)
            below_pdl = max(0.0, pl - cval) / cur_va_range
        except (TypeError, ValueError):
            pass

    return {
        "profile_overlap_pct": round(overlap_pct, 4),
        "profile_overlap_above_pdh": round(above_pdh, 4),
        "profile_overlap_below_pdl": round(below_pdl, 4),
    }


# ════════════════════════════════════════════════════════════════════════════
# 4. Range Extension vs Initial Balance (Dalton)
# ════════════════════════════════════════════════════════════════════════════

def compute_range_extension(payload: dict) -> dict:
    """Calcule range extension au-dessus/au-dessous de l'IB.

    Conventions Dalton :
      IB = 09:30-10:30 ET (first hour RTH)
      RE_above = (sess_high - ib_high) / ib_range si sess_high > ib_high else 0
      RE_below = (ib_low - sess_low) / ib_range  si sess_low < ib_low  else 0
      range_extension_completed = (sess_high > ib_high) AND (sess_low < ib_low)

    Returns dict :
      range_extension_above_ib_atr : float (en ATR units)
      range_extension_below_ib_atr : float
      range_extension_completed    : bool (both directions extended)
    """
    ib_high = payload.get("ib_high")
    ib_low = payload.get("ib_low")
    sess_high = payload.get("sess_high")
    sess_low = payload.get("sess_low")
    atr = payload.get("atr")

    defaults = {
        "range_extension_above_ib_atr": None,
        "range_extension_below_ib_atr": None,
        "range_extension_completed": False,
    }
    if any(v is None for v in (ib_high, ib_low, sess_high, sess_low, atr)):
        return defaults

    try:
        ih = float(ib_high)
        il = float(ib_low)
        sh = float(sess_high)
        sl = float(sess_low)
        a = float(atr)
    except (TypeError, ValueError):
        return defaults

    if a <= 0:
        return defaults

    above = max(0.0, sh - ih) / a
    below = max(0.0, il - sl) / a
    completed = (sh > ih) and (sl < il)

    return {
        "range_extension_above_ib_atr": round(above, 4),
        "range_extension_below_ib_atr": round(below, 4),
        "range_extension_completed": completed,
    }


# ════════════════════════════════════════════════════════════════════════════
# 5. FVG (Fair Value Gap) detector - state machine 3-bar rolling
# ════════════════════════════════════════════════════════════════════════════
# Concept ICT : Fair Value Gap = imbalance volume entre 3 bars consecutives
#   FVG UP   : bar[t-2].high < bar[t].low  (gap entre haute bar n-2 et basse bar n)
#   FVG DN   : bar[t-2].low  > bar[t].high (gap inverse)
# Le gap reste actif jusqu'a etre "fill" (price re-traverse la zone gap).

class FVGState:
    """State machine pour FVG detection rolling 3-bar."""

    def __init__(self, max_active: int = 20):
        self.max_active = max_active
        self.bars_buffer: deque = deque(maxlen=3)  # 3 dernieres bars (high, low)
        self.active_fvg_up: list = []  # list of (gap_low, gap_high, ts_created)
        self.active_fvg_dn: list = []  # idem


def detect_fvg(payload: dict, state: FVGState) -> dict:
    """Detecte et tracke les FVG actifs.

    Args:
        payload : bar courante avec bar_high, bar_low, close
        state   : FVGState mutable persistent across bars

    Returns dict :
      fvg_up_active           : int, count FVG up actifs
      fvg_dn_active           : int, count FVG dn actifs
      fvg_up_created_this_bar : bool, nouveau FVG up cree cette bar
      fvg_dn_created_this_bar : bool, nouveau FVG dn cree cette bar
      dist_fvg_up_nearest_atr : float ou None, distance vers FVG up le plus proche
      dist_fvg_dn_nearest_atr : float ou None, distance vers FVG dn le plus proche
    """
    bar_high = payload.get("bar_high") or payload.get("high")
    bar_low = payload.get("bar_low") or payload.get("low")
    close = payload.get("close")
    atr = payload.get("atr")

    defaults = {
        "fvg_up_active": 0,
        "fvg_dn_active": 0,
        "fvg_up_created_this_bar": False,
        "fvg_dn_created_this_bar": False,
        "dist_fvg_up_nearest_atr": None,
        "dist_fvg_dn_nearest_atr": None,
    }
    if any(v is None for v in (bar_high, bar_low, close)):
        # Pas ajouter la bar au buffer si donnees incompletes
        return defaults

    try:
        bh = float(bar_high)
        bl = float(bar_low)
        c = float(close)
    except (TypeError, ValueError):
        return defaults

    # Ajoute la bar courante au buffer
    state.bars_buffer.append((bh, bl))

    # Detecte nouveau FVG (besoin de 3 bars : t-2, t-1, t)
    fvg_up_created = False
    fvg_dn_created = False
    if len(state.bars_buffer) == 3:
        bar_t2 = state.bars_buffer[0]  # t-2
        bar_t = state.bars_buffer[2]   # t (current)
        # FVG UP : bar_t2.high < bar_t.low
        if bar_t2[0] < bar_t[1]:
            gap_low = bar_t2[0]
            gap_high = bar_t[1]
            state.active_fvg_up.append((gap_low, gap_high))
            fvg_up_created = True
        # FVG DN : bar_t2.low > bar_t.high
        if bar_t2[1] > bar_t[0]:
            gap_low = bar_t[0]
            gap_high = bar_t2[1]
            state.active_fvg_dn.append((gap_low, gap_high))
            fvg_dn_created = True

    # Cleanup : retire FVG "fully filled" (close traverse entierement la zone gap)
    #
    # CHOIX EXPLICITE Phase A.4 review code-reviewer reserve #4 :
    #   FVG UP "filled" = close DESCEND sous gap_low (= zone gap completement fillee)
    #     -> filter actif tant que c >= lo (close au-dessus ou DANS le gap = encore actif)
    #   FVG DN "filled" = close MONTE au-dessus gap_high
    #     -> filter actif tant que c <= hi (close en-dessous ou DANS le gap = encore actif)
    #
    # Definition "Closed FVG" ICT stricte = 100% fill. Alternative "Equilibrium FVG"
    # (fill = 50%) non implementee. Si downstream consumer veut 50% fill, calculer
    # via `dist_fvg_*_nearest_atr` + threshold custom (pas hardcoder ici).
    state.active_fvg_up = [
        (lo, hi) for (lo, hi) in state.active_fvg_up
        if c >= lo  # actif tant que close pas ENCORE traverse sous gap_low
    ]
    state.active_fvg_dn = [
        (lo, hi) for (lo, hi) in state.active_fvg_dn
        if c <= hi  # actif tant que close pas ENCORE traverse au-dessus gap_high
    ]

    # Cap max_active (FIFO)
    if len(state.active_fvg_up) > state.max_active:
        state.active_fvg_up = state.active_fvg_up[-state.max_active:]
    if len(state.active_fvg_dn) > state.max_active:
        state.active_fvg_dn = state.active_fvg_dn[-state.max_active:]

    # Distance nearest FVG (en ATR)
    dist_up = None
    dist_dn = None
    if state.active_fvg_up and atr is not None:
        try:
            a = float(atr)
            if a > 0:
                # Nearest FVG up = gap le plus proche au-dessus de close
                aboves = [(lo, hi) for (lo, hi) in state.active_fvg_up if lo >= c]
                if aboves:
                    nearest = min(aboves, key=lambda g: g[0] - c)
                    dist_up = round((nearest[0] - c) / a, 4)
        except (TypeError, ValueError):
            pass
    if state.active_fvg_dn and atr is not None:
        try:
            a = float(atr)
            if a > 0:
                belows = [(lo, hi) for (lo, hi) in state.active_fvg_dn if hi <= c]
                if belows:
                    nearest = max(belows, key=lambda g: g[1])
                    dist_dn = round((nearest[1] - c) / a, 4)
        except (TypeError, ValueError):
            pass

    return {
        "fvg_up_active": len(state.active_fvg_up),
        "fvg_dn_active": len(state.active_fvg_dn),
        "fvg_up_created_this_bar": fvg_up_created,
        "fvg_dn_created_this_bar": fvg_dn_created,
        "dist_fvg_up_nearest_atr": dist_up,
        "dist_fvg_dn_nearest_atr": dist_dn,
    }


# ════════════════════════════════════════════════════════════════════════════
# API publique : compute_market_profile_v5_features
# ════════════════════════════════════════════════════════════════════════════

def compute_market_profile_v5_features(payload: dict, fvg_state: FVGState) -> dict:
    """Calcule les 5 EASY features Phase A.2a sur un bar.

    Args:
        payload   : bar courante (dict, mutable mais on return un new dict)
        fvg_state : FVGState mutable persistent across bars

    Returns dict avec 12+ features ajoutees (cf docstring module).
    """
    out = {}
    out.update(compute_psd_sd2_levels(payload))
    out.update(classify_open_relation(payload))
    out.update(compute_profile_overlap(payload))
    out.update(compute_range_extension(payload))
    out.update(detect_fvg(payload, fvg_state))
    return out
