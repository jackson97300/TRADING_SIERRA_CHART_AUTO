"""
game_changers.py — Module Market Profile pour MIA Python
=========================================================

Réplique exacte des algorithmes C++ de DMP_OpenType.h et DMP_ProfileShape.h.
Chaque enum, seuil et branche conditionnelle est vérifiée contre le code source.

Références C++ :
  - DMP_OpenType.h    §5  → classify_open_type()
  - DMP_OpenType.h    §4  → classify_open_zone()
  - DMP_OpenType.h    §7  → classify_day_type()
  - DMP_OpenType.h    §8  → Rule80Pct (machine à états)
  - DMP_OpenType.h    §11 → bias_boost()
  - DMP_OpenType.h    §11a→ direction()
  - DMP_ProfileShape.h §9 → classify_profile_shape()

Emplacement : D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\game_changers.py

Auteur  : MIA Trading System
Version : 1.0 — 2026-03-01
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — ENUMS (parité exacte avec DMP_OpenType.h lignes 93-120)
# ═══════════════════════════════════════════════════════════════════════════════

class OpenType(IntEnum):
    """12 valeurs — DMP_OpenType.h:93-105"""
    UNKNOWN   = 0
    OD_UP     = 1
    OD_DOWN   = 2
    OTD_UP    = 3
    OTD_DOWN  = 4
    ORR_UP    = 5
    ORR_DOWN  = 6
    OAIR      = 7
    OAOR_UP   = 8
    OAOR_DOWN = 9
    ODF_UP    = 10
    ODF_DOWN  = 11


class OpenZone(IntEnum):
    """7 zones — DMP_OpenType.h:107-114"""
    BELOW_PDL = 1
    VAL_PDL   = 2
    POC_VAL   = 3
    AT_POC    = 4
    VAH_POC   = 5
    PDH_VAH   = 6
    ABOVE_PDH = 7


class DayType(IntEnum):
    """5 valeurs — DMP_OpenType.h:41-47"""
    NON_TREND = 0
    NORMAL    = 1
    NORM_VAR  = 2  # Défaut (42% des jours)
    NEUTRAL   = 3
    TREND     = 4


class ProfileShape(IntEnum):
    """4 formes — DMP_ProfileShape.h:67-70"""
    D_SHAPE  = 0  # Distribution normale (équilibre)
    P_SHAPE  = 1  # Volume en haut (bullish)
    B_LOWER  = 2  # Volume en bas (bearish) — lowercase b
    B_DOUBLE = 3  # Double distribution (breakout)


class Rule80State(IntEnum):
    """4 états — DMP_OpenType.h:117-120"""
    IDLE      = 0
    PRIMED    = 1
    IN_VA     = 2
    CONFIRMED = 3


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONSTANTES (parité exacte DMP_OpenType.h:122-133)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Seuils open_type ──────────────────────────────────────────────────────────
OT_POC_TOL_TICKS  = 3.0    # ±3 ticks = "at POC"
OT_OD_RATIO       = 0.75   # > 75% IB = Open Drive
OT_OAIR_RATIO     = 0.50   # ≤ 50% IB = OAIR (range)
OT_ODF_TICKS      = 8.0    # Reversal > 8 ticks = ODF

# ── Seuils day_type ───────────────────────────────────────────────────────────
DT_NONTREND       = 0.15   # IB < 15% ATR → NonTrend
DT_NORMAL         = 0.80   # IB > 80% ATR → Normal
DT_TREND_MULT     = 2.0    # Ext > 2×IB → Trend
DT_NEUTRAL_CENTER = 0.35   # Close dans ±35% milieu
DT_NORMAL_EXT_MAX = 0.20   # Extension < 20% IB → Normal

# ── Seuils profile_shape (DMP_ProfileShape.h:73-78) ──────────────────────────
PS_POC_HIGH_THRESH = 0.70  # POC > 70% du range = P-shape
PS_POC_LOW_THRESH  = 0.30  # POC < 30% du range = b-shape
PS_SKEW_THRESH     = 0.25  # |skew| > 0.25 = asymétrique
PS_IMBAL_THRESH    = 1.40  # Ratio > 1.4 = déséquilibre

# ── Confiances (DMP_OpenType.h:135-142) ──────────────────────────────────────
CONFIDENCE = {
    OpenType.ODF_UP:    0.90,
    OpenType.ODF_DOWN:  0.90,
    OpenType.OD_UP:     0.85,
    OpenType.OD_DOWN:   0.85,
    OpenType.OTD_UP:    0.70,
    OpenType.OTD_DOWN:  0.70,
    OpenType.OAOR_UP:   0.65,
    OpenType.OAOR_DOWN: 0.65,
    OpenType.ORR_UP:    0.60,
    OpenType.ORR_DOWN:  0.60,
    OpenType.OAIR:      0.30,
    OpenType.UNKNOWN:   0.00,
}

# ── Tick sizes ────────────────────────────────────────────────────────────────
TICK_SIZE = {"ES": 0.25, "NQ": 0.25}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CLASSIFIEURS (répliques C++ ligne par ligne)
# ═══════════════════════════════════════════════════════════════════════════════

def classify_open_zone(
    open_cash: float,
    prev_vah: float, prev_val: float, prev_vpoc: float,
    pdh: float, pdl: float,
    tick_size: float = 0.25,
) -> int:
    """
    Réplique exacte de DMP_ClassifyOpenZone() — DMP_OpenType.h:190-224.
    Retourne OpenZone (1-7). Défaut = AT_POC (4).
    """
    if not _valid(open_cash):
        return OpenZone.AT_POC
    tol = OT_POC_TOL_TICKS * tick_size

    if _valid(pdh) and open_cash > pdh:
        return OpenZone.ABOVE_PDH
    if _valid(prev_vah) and open_cash > prev_vah:
        return OpenZone.PDH_VAH
    if _valid(prev_vpoc) and open_cash > prev_vpoc + tol:
        return OpenZone.VAH_POC
    if _valid(prev_vpoc) and abs(open_cash - prev_vpoc) <= tol:
        return OpenZone.AT_POC
    if _valid(prev_val) and open_cash > prev_val:
        return OpenZone.POC_VAL
    if _valid(pdl) and open_cash > pdl:
        return OpenZone.VAL_PDL
    return OpenZone.BELOW_PDL


def classify_open_type(
    open_cash: float,
    prev_vah: float, prev_val: float,
    ib_high: float, ib_low: float,
    price_at_1030: float,
) -> int:
    """
    Réplique exacte de DMP_ClassifyOpenType() — DMP_OpenType.h:240-279.

    Priorité : OD > ORR > OAOR > OTD > OAIR.
    Retourne OpenType (0-11). Défaut = UNKNOWN (0).
    """
    if not all(_valid(v) for v in (open_cash, prev_vah, prev_val,
                                    ib_high, ib_low, price_at_1030)):
        return OpenType.UNKNOWN

    ib_range = ib_high - ib_low
    if ib_range <= 0.0:
        return OpenType.UNKNOWN

    open_above_va = open_cash > prev_vah
    open_below_va = open_cash < prev_val
    open_in_va    = not open_above_va and not open_below_va
    move          = price_at_1030 - open_cash
    move_abs      = abs(move)
    move_up       = move > 0.0

    # 1. OD (85%) : mouvement > 75% IB
    if move_abs > ib_range * OT_OD_RATIO:
        return OpenType.OD_UP if move_up else OpenType.OD_DOWN

    # 2. ORR (60%) : ouverture hors VA + reversal rentré dans VA
    if open_above_va and price_at_1030 < prev_vah:
        return OpenType.ORR_DOWN
    if open_below_va and price_at_1030 > prev_val:
        return OpenType.ORR_UP

    # 3. OAOR (65%) : gap hors VA qui tient
    if open_above_va and price_at_1030 > prev_vah:
        return OpenType.OAOR_UP
    if open_below_va and price_at_1030 < prev_val:
        return OpenType.OAOR_DOWN

    # 4. OTD (70%) : dans VA + mouvement > 50% IB
    if open_in_va and move_abs > ib_range * OT_OAIR_RATIO:
        return OpenType.OTD_UP if move_up else OpenType.OTD_DOWN

    # 5. OAIR (30%) : range
    return OpenType.OAIR


def check_odf(
    open_type: int,
    price_close: float,
    ib_high: float, ib_low: float,
    tick_size: float = 0.25,
) -> int:
    """
    Réplique exacte de DMP_CheckODF() — DMP_OpenType.h:315-332.
    Surveillance continue post-10h30 si OD actif.
    """
    if open_type not in (OpenType.OD_UP, OpenType.OD_DOWN):
        return open_type
    if not _valid(price_close):
        return open_type

    threshold = OT_ODF_TICKS * tick_size

    if open_type == OpenType.OD_UP and _valid(ib_low):
        if price_close < ib_low - threshold:
            return OpenType.ODF_UP

    if open_type == OpenType.OD_DOWN and _valid(ib_high):
        if price_close > ib_high + threshold:
            return OpenType.ODF_DOWN

    return open_type


def classify_day_type(
    ib_atr: float,
    sess_high: float, sess_low: float,
    price_close: float,
    ib_high: float, ib_low: float,
) -> int:
    """
    Réplique exacte de DMP_ClassifyDayType() — DMP_OpenType.h:345-385.

    ⚠️ Nuance critique (ligne 366) :
      Trend exige extension forte sur 1 côté ET AUCUNE extension de l'autre.
      (strong_up && !ext_down) || (strong_dn && !ext_up)

    Défaut = NORM_VAR (2).
    """
    if not _valid(ib_atr) or ib_atr <= 0.0:
        return DayType.NORM_VAR
    if not _valid(sess_high) or not _valid(sess_low):
        return DayType.NORM_VAR
    if not _valid(ib_high) or not _valid(ib_low):
        return DayType.NORM_VAR
    if ib_high <= ib_low:
        return DayType.NORM_VAR

    ib_range  = ib_high - ib_low
    ext_up    = sess_high > ib_high
    ext_down  = sess_low < ib_low
    ext_up_sz = (sess_high - ib_high) if ext_up else 0.0
    ext_dn_sz = (ib_low - sess_low) if ext_down else 0.0

    # 0 = NonTrend : IB ultra-comprimée
    if ib_atr < DT_NONTREND:
        return DayType.NON_TREND

    # 4 = Trend : extension > 2×IB sur 1 côté, AUCUNE extension de l'autre
    strong_up = ext_up_sz > ib_range * DT_TREND_MULT
    strong_dn = ext_dn_sz > ib_range * DT_TREND_MULT
    if (strong_up and not ext_down) or (strong_dn and not ext_up):
        return DayType.TREND

    # 3 = Neutral : extension 2 côtés + close au milieu (±35%)
    if ext_up and ext_down and _valid(price_close):
        rng = sess_high - sess_low
        if rng > 0.0:
            pos = (price_close - sess_low) / rng
            if (0.5 - DT_NEUTRAL_CENTER) <= pos <= (0.5 + DT_NEUTRAL_CENTER):
                return DayType.NEUTRAL

    # 1 = Normal : IB large, session contenue (ext < 20% IB)
    if ib_atr >= DT_NORMAL:
        if max(ext_up_sz, ext_dn_sz) < ib_range * DT_NORMAL_EXT_MAX:
            return DayType.NORMAL

    # 2 = NormVar : défaut
    return DayType.NORM_VAR


def direction(open_type: int) -> int:
    """
    Réplique exacte de DMP_OT_Direction() — DMP_OpenType.h:622-630.
    +1 = bullish, -1 = bearish, 0 = neutre.
    """
    v = int(open_type)
    if v in (1, 3, 5, 8):   # OD_UP, OTD_UP, ORR_UP, OAOR_UP
        return +1
    if v in (2, 4, 6, 9):   # OD_DOWN, OTD_DOWN, ORR_DOWN, OAOR_DOWN
        return -1
    return 0                 # OAIR, ODF_UP, ODF_DOWN, UNKNOWN


def confidence(open_type: int) -> float:
    """Réplique exacte de DMP_OT_Confidence() — DMP_OpenType.h:282-291."""
    return CONFIDENCE.get(OpenType(int(open_type)), 0.0)


def bias_boost(signal_dir: int, open_type: int) -> float:
    """
    Réplique exacte de DMP_OT_BiasBoost() — DMP_OpenType.h:644-672.
    Retourne float entre -0.30 et +0.20.
    """
    ot = int(open_type)
    strong_bull = (ot == 1)
    bull        = ot in (3, 5, 8)
    strong_bear = (ot == 2)
    bear        = ot in (4, 6, 9)

    if signal_dir > 0:    # Long
        if strong_bull: return +0.20
        if bull:        return +0.10
        if strong_bear: return -0.30  # NE JAMAIS fader OD_DOWN
        if bear:        return -0.15
    elif signal_dir < 0:  # Short
        if strong_bear: return +0.20
        if bear:        return +0.10
        if strong_bull: return -0.30  # NE JAMAIS fader OD_UP
        if bull:        return -0.15

    return 0.0  # OAIR, ODF, UNKNOWN : neutre


def classify_profile_shape(
    poc_position: float,
    skewness: float,
    volume_imbalance: float,
    is_bimodal: bool,
) -> int:
    """
    Réplique exacte de PS_ClassifyShape() — DMP_ProfileShape.h:452-480.
    """
    if is_bimodal:
        return ProfileShape.B_DOUBLE

    if (poc_position >= PS_POC_HIGH_THRESH or
            skewness >= PS_SKEW_THRESH or
            volume_imbalance >= PS_IMBAL_THRESH):
        return ProfileShape.P_SHAPE

    if (poc_position <= PS_POC_LOW_THRESH or
            skewness <= -PS_SKEW_THRESH or
            volume_imbalance <= (1.0 / PS_IMBAL_THRESH)):
        return ProfileShape.B_LOWER

    return ProfileShape.D_SHAPE


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MACHINE À ÉTATS RULE 80% (DMP_OpenType.h:395-435)
# ═══════════════════════════════════════════════════════════════════════════════

class Rule80Pct:
    """
    Machine à 4 états pour la règle des 80%.
    Conditions : Open HORS VA → rentre dans VA → y reste 60 barres
    Résultat   : 80% probabilité de traverser toute la VA.

    Réplique exacte de DMP_CheckRule80pct() — DMP_OpenType.h:395-435.
    """

    def __init__(self, bars_required: int = 60):
        """
        bars_required : 3600 / sec_per_bar (60 pour 1-min, 12 pour 5-min).
        Défaut = 60 (chart 1-min comme le G3 Dumper).
        """
        self.state: Rule80State = Rule80State.IDLE
        self.entry_bar: int = -1
        self.bars_required: int = bars_required

    def reset(self) -> None:
        self.state = Rule80State.IDLE
        self.entry_bar = -1

    def update(self, bar_index: int, price_close: float,
               prev_vah: float, prev_val: float) -> float:
        """
        Retourne 1.0 si confirmé, 0.0 sinon.
        Appelé à chaque barre.
        """
        if not _valid(price_close) or not _valid(prev_vah) or not _valid(prev_val):
            return 0.0
        if prev_vah <= prev_val:
            return 0.0

        in_va = prev_val <= price_close <= prev_vah

        if self.state == Rule80State.CONFIRMED:
            return 1.0

        if self.state == Rule80State.IDLE:
            if not in_va:
                self.state = Rule80State.PRIMED
            return 0.0

        if self.state == Rule80State.PRIMED:
            if in_va:
                self.state = Rule80State.IN_VA
                self.entry_bar = bar_index
            return 0.0

        if self.state == Rule80State.IN_VA:
            if not in_va:
                self.state = Rule80State.PRIMED
                self.entry_bar = -1
                return 0.0
            if bar_index - self.entry_bar >= self.bars_required:
                self.state = Rule80State.CONFIRMED
                return 1.0
            return 0.0

        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — CLASSIFIEUR PAR SESSION (orchestrateur)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SessionState:
    """État interne d'une session de trading (9h30-16h00 ET)."""
    open_cash: Optional[float] = None
    price_1030: Optional[float] = None
    open_type: int = OpenType.UNKNOWN
    open_zone: int = OpenZone.AT_POC
    day_type: int = DayType.NORM_VAR
    rule80: Rule80Pct = field(default_factory=Rule80Pct)
    ib_complete: bool = False
    # PDH/PDL persistants (inter-sessions, jamais reset)
    pdh: float = float('nan')
    pdl: float = float('nan')


class MarketProfileClassifier:
    """
    Classifieur Market Profile par session.

    Usage pour G3 JSONL (déjà calculé, juste parser) :
        clf = MarketProfileClassifier("ES")
        rows = clf.load_g3_jsonl("20260301_ES.jsonl")

    Usage pour calcul Python pur (sur données Python DMP) :
        clf = MarketProfileClassifier("ES")
        result = clf.classify_bar(row_dict, bar_index)
    """

    # Champs G9 dans le G3 JSONL
    G9_FIELDS = [
        "open_type", "open_zone", "open_bias_conf", "open_direction",
        "day_type", "rule_80pct", "trend_day_probability",
    ]

    # Champs G12 dans le G3 JSONL
    G12_FIELDS = [
        "profile_shape", "profile_skew", "poc_position",
        "volume_imbalance", "is_double_dist", "poc_separation_ticks",
        "single_print_mid", "single_print_count", "profile_hvn_dominant",
    ]

    ALL_FIELDS = G9_FIELDS + G12_FIELDS

    def __init__(self, symbol: str = "ES"):
        self.symbol = symbol.upper()
        self.tick_size = TICK_SIZE.get(self.symbol, 0.25)
        self.session = SessionState()

    def new_session(self, prev_sess_high: float = float('nan'),
                    prev_sess_low: float = float('nan')) -> None:
        """
        Reset pour nouvelle session.
        PDH/PDL sont préservés (inter-sessions) sauf si fournis explicitement.
        Réplique DMP_OT_ResetSession() + DMP_OT_SaveEODLevels().
        """
        old_pdh = self.session.pdh
        old_pdl = self.session.pdl

        # Sauvegarder PDH/PDL de la session précédente si fournis
        if _valid(prev_sess_high):
            old_pdh = prev_sess_high
        if _valid(prev_sess_low):
            old_pdl = prev_sess_low

        self.session = SessionState(pdh=old_pdh, pdl=old_pdl)

    def classify_bar(self, row: dict, bar_index: int = 0) -> dict:
        """
        Classifier une barre. Appelé barre par barre dans l'ordre chronologique.

        Attend les clés du JSONL Python DMP :
          - structure.ibh, structure.ibl
          - vva.vah, vva.val, vva.vpoc
          - atr, high, low, close (ou mid)
          - session_elapsed_s

        Retourne dict avec les 8 game changers + satellites.
        """
        s = self.session

        # ── Extraction données ────────────────────────────────────────────
        ibh = _get_nested(row, "structure", "ibh")
        ibl = _get_nested(row, "structure", "ibl")
        vah = _get_nested(row, "vva", "vah")
        val = _get_nested(row, "vva", "val")
        vpoc = _get_nested(row, "vva", "vpoc")
        atr = row.get("atr")
        price = row.get("close") or row.get("mid")
        elapsed = row.get("session_elapsed_s", 0)
        sess_high = row.get("high")
        sess_low = row.get("low")

        # ── Capturer open_cash (1ère barre RTH, < 2 min) ─────────────────
        if s.open_cash is None and elapsed is not None and elapsed < 120:
            if _valid(price):
                s.open_cash = price

        # ── Capturer price_1030 (IB complete = 3600s) ─────────────────────
        if s.price_1030 is None and elapsed is not None and elapsed >= 3600:
            if _valid(price):
                s.price_1030 = price
                s.ib_complete = True

        # ── Open Zone (une seule fois, dès que open_cash disponible) ──────
        if s.open_cash is not None and s.open_zone == OpenZone.AT_POC:
            s.open_zone = classify_open_zone(
                s.open_cash, vah, val, vpoc,
                s.pdh, s.pdl, self.tick_size
            )

        # ── Open Type (une seule fois, à IB complete) ─────────────────────
        if s.ib_complete and s.open_type == OpenType.UNKNOWN:
            if ibh is not None and ibl is not None:
                s.open_type = classify_open_type(
                    s.open_cash, vah, val, ibh, ibl, s.price_1030
                )

        # ── ODF surveillance continue ─────────────────────────────────────
        current_ot = s.open_type
        if s.ib_complete and _valid(price) and ibh is not None and ibl is not None:
            current_ot = check_odf(s.open_type, price, ibh, ibl, self.tick_size)
            if current_ot != s.open_type:
                s.open_type = current_ot

        # ── Day Type (progressif, chaque barre après IB) ──────────────────
        if s.ib_complete and ibh is not None and ibl is not None:
            ib_range = ibh - ibl
            ib_atr = (ib_range / atr) if (_valid(atr) and atr > 0) else 0.0
            s.day_type = classify_day_type(
                ib_atr, sess_high, sess_low, price, ibh, ibl
            )

        # ── Rule 80% (chaque barre) ──────────────────────────────────────
        r80 = 0.0
        if _valid(price) and _valid(vah) and _valid(val):
            r80 = s.rule80.update(bar_index, price, vah, val)

        # ── Résultat ──────────────────────────────────────────────────────
        ot = s.open_type
        return {
            "open_type":        ot,
            "open_zone":        s.open_zone,
            "open_bias_conf":   confidence(ot),
            "open_direction":   direction(ot),
            "day_type":         s.day_type,
            "rule_80pct":       int(r80),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — PARSER G3 JSONL
# ═══════════════════════════════════════════════════════════════════════════════

def load_g3_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """
    Charge un fichier G3 JSONL (produit par DMP_Writer.h).

    Format : JSON plat, 1 ligne par barre 1-min.
    Chemin : D:\\TRADING_SIERRA_CHART_AUTO\\DATA\\YYYY\\MM\\SYM\\YYYYMMDD_SYM.jsonl

    Retourne une liste de dicts avec tous les champs.
    """
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                rows.append(row)
            except json.JSONDecodeError as e:
                print(f"[game_changers] WARN: ligne {line_no} JSON invalide: {e}")
    return rows


def extract_game_changers(row: dict) -> dict:
    """
    Extrait les 16 champs game changers (G9+G12) d'une ligne G3 JSONL.
    Retourne un dict avec les champs disponibles, None pour les manquants.
    """
    result = {}
    for field_name in MarketProfileClassifier.ALL_FIELDS:
        result[field_name] = row.get(field_name)
    return result


def find_g3_files(
    base_dir: str,
    symbol: str = "ES",
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> List[str]:
    """
    Recherche les fichiers G3 JSONL dans l'arborescence YYYY/MM/SYM/.

    Supporte DEUX structures :
      - Nouvelle : BASE\\YYYY\\MM\\SYM\\YYYYMMDD_SYM.jsonl
      - Ancienne : BASE\\SYM\\YYYYMMDD_SYM.jsonl

    Retourne les chemins triés par date.
    """
    found = []
    base = Path(base_dir)
    sym = symbol.upper()
    pattern = f"*_{sym}.jsonl"

    # Nouvelle structure : YYYY/MM/SYM/
    for jsonl in base.rglob(pattern):
        # Vérifier que le parent est SYM
        if jsonl.parent.name == sym:
            if year and jsonl.parent.parent.parent.name != str(year):
                continue
            if month and jsonl.parent.parent.name != f"{month:02d}":
                continue
            found.append(str(jsonl))

    return sorted(found)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — HELPERS INTERNES
# ═══════════════════════════════════════════════════════════════════════════════

def _valid(v) -> bool:
    """Vérifie qu'une valeur est utilisable (pas None, pas NaN, pas sentinel)."""
    if v is None:
        return False
    try:
        return not math.isnan(v) and not math.isinf(v)
    except (TypeError, ValueError):
        return False


def _get_nested(d: dict, key1: str, key2: str, default=None):
    """Accès nested pour les dicts imbriqués du Python DMP (vva.vah, structure.ibh)."""
    sub = d.get(key1)
    if isinstance(sub, dict):
        return sub.get(key2, default)
    # Fallback : clé plate (format G3)
    flat_key = f"{key1}_{key2}" if key1 else key2
    return d.get(flat_key, default)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — NOMS LISIBLES (debug / logs)
# ═══════════════════════════════════════════════════════════════════════════════

def open_type_name(ot: int) -> str:
    """Réplique DMP_OT_Name() — DMP_OpenType.h:293-303."""
    names = {
        0: "UNKNOWN", 1: "OD_UP", 2: "OD_DOWN",
        3: "OTD_UP", 4: "OTD_DOWN", 5: "ORR_UP", 6: "ORR_DOWN",
        7: "OAIR", 8: "OAOR_UP", 9: "OAOR_DOWN",
        10: "ODF_UP", 11: "ODF_DOWN",
    }
    return names.get(int(ot), "UNKNOWN")


def day_type_name(dt: int) -> str:
    names = {0: "NonTrend", 1: "Normal", 2: "NormVar", 3: "Neutral", 4: "Trend"}
    return names.get(int(dt), "NormVar")


def profile_shape_name(ps: int) -> str:
    """Réplique PS_ShapeName() — DMP_ProfileShape.h:482-491."""
    names = {0: "D", 1: "P", 2: "b", 3: "B"}
    return names.get(int(ps), "?")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — TESTS DE PARITÉ C++ ↔ PYTHON
# ═══════════════════════════════════════════════════════════════════════════════

def run_parity_tests() -> bool:
    """
    Tests exhaustifs de parité avec le C++.
    Chaque test vérifie un chemin de code spécifique dans les classifieurs.
    Retourne True si tous passent.
    """
    passed = 0
    failed = 0
    total = 0

    def check(name: str, got, expected):
        nonlocal passed, failed, total
        total += 1
        if got == expected:
            passed += 1
        else:
            failed += 1
            print(f"  ❌ {name}: attendu {expected}, obtenu {got}")

    print("=" * 70)
    print("TESTS DE PARITÉ C++ ↔ PYTHON — game_changers.py")
    print("=" * 70)

    # ── 1. Enums ──────────────────────────────────────────────────────────
    print("\n📋 1. Parité Enums")
    check("OT_UNKNOWN",    OpenType.UNKNOWN,    0)
    check("OT_OD_UP",      OpenType.OD_UP,      1)
    check("OT_OD_DOWN",    OpenType.OD_DOWN,    2)
    check("OT_OTD_UP",     OpenType.OTD_UP,     3)
    check("OT_OTD_DOWN",   OpenType.OTD_DOWN,   4)
    check("OT_ORR_UP",     OpenType.ORR_UP,     5)
    check("OT_ORR_DOWN",   OpenType.ORR_DOWN,   6)
    check("OT_OAIR",       OpenType.OAIR,       7)
    check("OT_OAOR_UP",    OpenType.OAOR_UP,    8)
    check("OT_OAOR_DOWN",  OpenType.OAOR_DOWN,  9)
    check("OT_ODF_UP",     OpenType.ODF_UP,     10)
    check("OT_ODF_DOWN",   OpenType.ODF_DOWN,   11)
    check("OZ_BELOW_PDL",  OpenZone.BELOW_PDL,  1)
    check("OZ_ABOVE_PDH",  OpenZone.ABOVE_PDH,  7)
    check("DT_NON_TREND",  DayType.NON_TREND,   0)
    check("DT_TREND",      DayType.TREND,        4)
    check("PS_D_SHAPE",    ProfileShape.D_SHAPE,  0)
    check("PS_B_DOUBLE",   ProfileShape.B_DOUBLE, 3)
    check("R80_IDLE",      Rule80State.IDLE,      0)
    check("R80_CONFIRMED", Rule80State.CONFIRMED, 3)

    # ── 2. Confiances ─────────────────────────────────────────────────────
    print("\n📋 2. Parité Confiances")
    check("conf_ODF",  confidence(OpenType.ODF_UP),    0.90)
    check("conf_OD",   confidence(OpenType.OD_UP),     0.85)
    check("conf_OTD",  confidence(OpenType.OTD_DOWN),  0.70)
    check("conf_OAOR", confidence(OpenType.OAOR_UP),   0.65)
    check("conf_ORR",  confidence(OpenType.ORR_DOWN),  0.60)
    check("conf_OAIR", confidence(OpenType.OAIR),      0.30)
    check("conf_UNK",  confidence(OpenType.UNKNOWN),   0.00)

    # ── 3. Direction ──────────────────────────────────────────────────────
    print("\n📋 3. Parité Direction")
    check("dir_OD_UP",     direction(1),  +1)
    check("dir_OD_DOWN",   direction(2),  -1)
    check("dir_OTD_UP",    direction(3),  +1)
    check("dir_OTD_DOWN",  direction(4),  -1)
    check("dir_ORR_UP",    direction(5),  +1)
    check("dir_ORR_DOWN",  direction(6),  -1)
    check("dir_OAIR",      direction(7),   0)
    check("dir_OAOR_UP",   direction(8),  +1)
    check("dir_OAOR_DOWN", direction(9),  -1)
    check("dir_ODF_UP",    direction(10),  0)
    check("dir_ODF_DOWN",  direction(11),  0)
    check("dir_UNKNOWN",   direction(0),   0)

    # ── 4. Bias Boost ─────────────────────────────────────────────────────
    print("\n📋 4. Parité Bias Boost")
    # Long signals
    check("bb_long+OD_UP",    bias_boost(+1, 1),   +0.20)
    check("bb_long+OTD_UP",   bias_boost(+1, 3),   +0.10)
    check("bb_long+ORR_UP",   bias_boost(+1, 5),   +0.10)
    check("bb_long+OAOR_UP",  bias_boost(+1, 8),   +0.10)
    check("bb_long+OD_DOWN",  bias_boost(+1, 2),   -0.30)
    check("bb_long+OTD_DOWN", bias_boost(+1, 4),   -0.15)
    check("bb_long+OAIR",     bias_boost(+1, 7),    0.00)
    check("bb_long+ODF_UP",   bias_boost(+1, 10),   0.00)
    # Short signals
    check("bb_short+OD_DOWN",  bias_boost(-1, 2),   +0.20)
    check("bb_short+OTD_DOWN", bias_boost(-1, 4),   +0.10)
    check("bb_short+OD_UP",    bias_boost(-1, 1),   -0.30)
    check("bb_short+OTD_UP",   bias_boost(-1, 3),   -0.15)
    check("bb_short+OAIR",     bias_boost(-1, 7),    0.00)
    # Neutral signal
    check("bb_neutral+OD_UP",  bias_boost(0, 1),    0.00)

    # ── 5. Open Type classification ───────────────────────────────────────
    print("\n📋 5. Parité Open Type Classification")
    # OD_UP : move > 75% IB, move up
    # open=5000, p1030=5020, IB=5000-5025 → move=20, ib_range=25, 20/25=80% > 75%
    check("OT_OD_UP", classify_open_type(5000, 5050, 4950, 5025, 5000, 5020), OpenType.OD_UP)
    # OD_DOWN : move > 75% IB, move down
    check("OT_OD_DOWN", classify_open_type(5020, 5050, 4950, 5025, 5000, 5000), OpenType.OD_DOWN)

    # ORR_DOWN : open above VA + price rentré dans VA (move < 75% IB pour éviter OD)
    # open=5060 (> vah=5050), p1030=5045 (< vah=5050), move=15, ib=25, 15/25=60% < 75%
    check("OT_ORR_DOWN", classify_open_type(5060, 5050, 4950, 5025, 5000, 5045), OpenType.ORR_DOWN)
    # ORR_UP : open below VA + price rentré dans VA
    # open=4940 (< val=4950), p1030=4955 (> val=4950), move=15, 15/25=60% < 75%
    check("OT_ORR_UP", classify_open_type(4940, 5050, 4950, 5025, 5000, 4955), OpenType.ORR_UP)

    # OAOR_UP : open above VA + price reste au-dessus VA
    check("OT_OAOR_UP", classify_open_type(5060, 5050, 4950, 5025, 5000, 5065), OpenType.OAOR_UP)
    # OAOR_DOWN : open below VA + price reste sous VA
    check("OT_OAOR_DOWN", classify_open_type(4940, 5050, 4950, 5025, 5000, 4935), OpenType.OAOR_DOWN)

    # OTD_UP : open dans VA + move > 50% IB, up
    # open=5000, in VA [4950,5050], p1030=5014, move=14, ib=25, 14/25=56% > 50%
    check("OT_OTD_UP", classify_open_type(5000, 5050, 4950, 5025, 5000, 5014), OpenType.OTD_UP)
    # OTD_DOWN
    check("OT_OTD_DOWN", classify_open_type(5010, 5050, 4950, 5025, 5000, 4996), OpenType.OTD_DOWN)

    # OAIR : open dans VA + faible mouvement
    # open=5000, p1030=5005, move=5, ib=25, 5/25=20% < 50%
    check("OT_OAIR", classify_open_type(5000, 5050, 4950, 5025, 5000, 5005), OpenType.OAIR)

    # UNKNOWN : données invalides
    check("OT_UNKNOWN_nan", classify_open_type(float('nan'), 5050, 4950, 5025, 5000, 5005), OpenType.UNKNOWN)
    check("OT_UNKNOWN_none", classify_open_type(None, 5050, 4950, 5025, 5000, 5005), OpenType.UNKNOWN)

    # ── 6. ODF ────────────────────────────────────────────────────────────
    print("\n📋 6. Parité ODF")
    # OD_UP actif, prix casse ib_low - 8 ticks → ODF_UP
    # ib_low=5000, threshold=8*0.25=2.0, price=4997 < 5000-2.0=4998 → ODF
    check("ODF_UP", check_odf(OpenType.OD_UP, 4997.0, 5025, 5000, 0.25), OpenType.ODF_UP)
    # Pas assez de reversal
    check("ODF_UP_no", check_odf(OpenType.OD_UP, 4999.0, 5025, 5000, 0.25), OpenType.OD_UP)
    # OD_DOWN + price casse ib_high + 8 ticks
    check("ODF_DOWN", check_odf(OpenType.OD_DOWN, 5028.0, 5025, 5000, 0.25), OpenType.ODF_DOWN)
    # Non-OD passthrough
    check("ODF_passthrough", check_odf(OpenType.OAIR, 4997.0, 5025, 5000, 0.25), OpenType.OAIR)

    # ── 7. Day Type classification ────────────────────────────────────────
    print("\n📋 7. Parité Day Type")
    # NonTrend : ib_atr < 0.15
    check("DT_NonTrend", classify_day_type(0.10, 5030, 4995, 5010, 5025, 5000), DayType.NON_TREND)

    # Trend : ext > 2×IB sur 1 côté, AUCUNE extension de l'autre
    # ib=5000-5025 (range=25), sess_high=5080 (ext_up=55 > 50=2×25), sess_low=5002 (> ib_low → !ext_down)
    check("DT_Trend_up", classify_day_type(0.50, 5080, 5002, 5070, 5025, 5000), DayType.TREND)
    # Trend down
    check("DT_Trend_dn", classify_day_type(0.50, 5024, 4920, 4930, 5025, 5000), DayType.TREND)
    # Trend refusé si ext des 2 côtés (même si un côté > 2×IB)
    check("DT_NOT_Trend_both", classify_day_type(0.50, 5080, 4990, 5040, 5025, 5000), DayType.NEUTRAL)

    # Neutral : ext 2 côtés + close milieu
    # ext_up + ext_down, close milieu ±35% → pos=0.5, dans [0.15, 0.85]
    check("DT_Neutral", classify_day_type(0.50, 5040, 4980, 5010, 5025, 5000), DayType.NEUTRAL)

    # Normal : ib_atr >= 0.80, ext < 20% IB
    # ib_atr=0.85, ib_range=25, sess_low=5000 (= ib_low → pas d'ext_down), ext_up=3 < 5 (20% of 25)
    check("DT_Normal", classify_day_type(0.85, 5028, 5000, 5015, 5025, 5000), DayType.NORMAL)

    # NormVar : défaut
    check("DT_NormVar", classify_day_type(0.50, 5040, 5000, 5020, 5025, 5000), DayType.NORM_VAR)

    # ── 8. Open Zone classification ───────────────────────────────────────
    print("\n📋 8. Parité Open Zone")
    check("OZ_ABOVE_PDH", classify_open_zone(5110, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.ABOVE_PDH)
    check("OZ_PDH_VAH",   classify_open_zone(5060, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.PDH_VAH)
    check("OZ_VAH_POC",   classify_open_zone(5010, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.VAH_POC)
    check("OZ_AT_POC",    classify_open_zone(5000.5, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.AT_POC)
    check("OZ_POC_VAL",   classify_open_zone(4970, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.POC_VAL)
    check("OZ_VAL_PDL",   classify_open_zone(4940, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.VAL_PDL)
    check("OZ_BELOW_PDL", classify_open_zone(4890, 5050, 4950, 5000, 5100, 4900, 0.25), OpenZone.BELOW_PDL)

    # ── 9. Profile Shape classification ───────────────────────────────────
    print("\n📋 9. Parité Profile Shape")
    check("PS_B_DOUBLE",  classify_profile_shape(0.50, 0.0, 1.0, True),   ProfileShape.B_DOUBLE)
    check("PS_P_SHAPE_poc", classify_profile_shape(0.75, 0.0, 1.0, False), ProfileShape.P_SHAPE)
    check("PS_P_SHAPE_skew", classify_profile_shape(0.50, 0.30, 1.0, False), ProfileShape.P_SHAPE)
    check("PS_P_SHAPE_imbal", classify_profile_shape(0.50, 0.0, 1.50, False), ProfileShape.P_SHAPE)
    check("PS_B_LOWER_poc", classify_profile_shape(0.25, 0.0, 1.0, False), ProfileShape.B_LOWER)
    check("PS_B_LOWER_skew", classify_profile_shape(0.50, -0.30, 1.0, False), ProfileShape.B_LOWER)
    check("PS_B_LOWER_imbal", classify_profile_shape(0.50, 0.0, 0.60, False), ProfileShape.B_LOWER)
    check("PS_D_SHAPE",  classify_profile_shape(0.50, 0.0, 1.0, False),   ProfileShape.D_SHAPE)

    # ── 10. Rule 80% machine à états ──────────────────────────────────────
    print("\n📋 10. Parité Rule 80%")
    r80 = Rule80Pct(bars_required=3)  # 3 barres pour test rapide
    vah, val = 5050.0, 4950.0

    check("R80_start_idle", r80.state, Rule80State.IDLE)
    r80.update(0, 5000.0, vah, val)  # in VA → reste IDLE
    check("R80_in_va_idle", r80.state, Rule80State.IDLE)
    r80.update(1, 5060.0, vah, val)  # hors VA → PRIMED
    check("R80_hors_va_primed", r80.state, Rule80State.PRIMED)
    r80.update(2, 5040.0, vah, val)  # rentre en VA → IN_VA
    check("R80_rentre_in_va", r80.state, Rule80State.IN_VA)
    r80.update(3, 5060.0, vah, val)  # sort VA → retour PRIMED
    check("R80_sort_primed", r80.state, Rule80State.PRIMED)
    r80.update(4, 5020.0, vah, val)  # rentre en VA → IN_VA (bar=4)
    check("R80_rentre2_in_va", r80.state, Rule80State.IN_VA)
    result = r80.update(5, 5010.0, vah, val)  # bar 5, entry=4 → 5-4=1 < 3
    check("R80_not_yet", result, 0.0)
    result = r80.update(7, 5010.0, vah, val)  # bar 7, entry=4 → 7-4=3 >= 3
    check("R80_confirmed", result, 1.0)
    check("R80_state_confirmed", r80.state, Rule80State.CONFIRMED)
    result = r80.update(8, 5060.0, vah, val)  # reste confirmé même hors VA
    check("R80_stays_confirmed", result, 1.0)

    # ── 11. Noms lisibles ─────────────────────────────────────────────────
    print("\n📋 11. Noms lisibles")
    check("name_OD_UP",    open_type_name(1),  "OD_UP")
    check("name_ODF_DOWN", open_type_name(11), "ODF_DOWN")
    check("name_UNKNOWN",  open_type_name(99), "UNKNOWN")
    check("name_DT_Trend", day_type_name(4),   "Trend")
    check("name_PS_b",     profile_shape_name(2), "b")

    # ── Résumé ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    if failed == 0:
        print(f"✅ TOUS LES TESTS PASSENT : {passed}/{total}")
    else:
        print(f"❌ ÉCHECS : {failed}/{total}")
    print(f"{'=' * 70}")

    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    success = run_parity_tests()
    exit(0 if success else 1)
