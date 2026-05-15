"""
mia_rule_backtest.py — Backtest du moteur de regles MIA sur donnees DMP brutes
================================================================================

Charge les JSONL ES et NQ, evalue 7 regles + filtres qualite, simule les trades
avec TP/SL fixes, et produit un rapport par instrument et par session.

Usage:
    python -X utf8 CORE/mia_rule_backtest.py DATA/ES DATA/NQ

Auteur : MIA Trading System
Date   : 2026-04-10
"""

import glob
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Constantes
# ═══════════════════════════════════════════════════════════════

TICK_SIZE = 0.25

# TP/SL en ticks
SL_TICKS = {"ES": 5, "NQ": 20}
TP_TICKS = {"ES": 9, "NQ": 36}

# Sessions
SESSION_ASIA = 0
SESSION_LONDON = 1
SESSION_US = 2
SESSION_NAMES = {SESSION_ASIA: "Asia", SESSION_LONDON: "London", SESSION_US: "US"}

# Lunch no-trade zone (UTC) — 12:15-13:15 ET = 16:15-17:15 UTC
LUNCH_START_UTC_H = 16
LUNCH_START_UTC_M = 15
LUNCH_END_UTC_H = 17
LUNCH_END_UTC_M = 15

# Filtres
MIN_BIAS_SCORE = 0.25
COOLDOWN_BARS = 5
MAX_TRADES_PER_DAY = 10
VIX_MIN = 12.0
VIX_MAX = 35.0
MAX_SESS_RANGE_ATR = 2.0
TRADE_TIMEOUT_BARS = 60
MIN_BARS_PER_DAY = 50


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _get(row: dict, col: str, default: float = 0.0) -> float:
    """Recupere une valeur numerique, avec fallback NaN-safe."""
    v = row.get(col, default)
    if v is None:
        return default
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return default
        return fv
    except (ValueError, TypeError):
        return default


def _get_int(row: dict, col: str, default: int = 0) -> int:
    """Recupere un entier."""
    v = row.get(col, default)
    if v is None:
        return default
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return default
        return int(fv)
    except (ValueError, TypeError):
        return default


def _ts_to_utc(ts_ms: float) -> datetime:
    """Convertit un timestamp ms en datetime UTC."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)


def _is_lunch_zone(ts_ms: float) -> bool:
    """True si la barre est dans la zone no-trade lunch (12:15-13:15 ET)."""
    dt = _ts_to_utc(ts_ms)
    minutes = dt.hour * 60 + dt.minute
    lunch_start = LUNCH_START_UTC_H * 60 + LUNCH_START_UTC_M
    lunch_end = LUNCH_END_UTC_H * 60 + LUNCH_END_UTC_M
    return lunch_start <= minutes < lunch_end


# ═══════════════════════════════════════════════════════════════
# Chargement des donnees
# ═══════════════════════════════════════════════════════════════

def load_jsonl_dir(data_dir: str) -> dict[str, list[dict]]:
    """Charge tous les JSONL d'un repertoire, groupes par jour.

    Returns:
        dict {date_str: [bar_dicts]} trie par date.
        Skip les jours avec < MIN_BARS_PER_DAY barres (weekends).
    """
    pattern = os.path.join(data_dir, "*.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"  ERREUR: aucun fichier JSONL dans {data_dir}")
        return {}

    days = {}
    for fpath in files:
        basename = os.path.basename(fpath)
        date_str = basename.split("_")[0]
        bars = []
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    bars.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if len(bars) < MIN_BARS_PER_DAY:
            continue
        days[date_str] = bars

    print(f"  Charge {len(days)} jours depuis {data_dir} "
          f"({sum(len(v) for v in days.values())} barres)")
    return dict(sorted(days.items()))


# ═══════════════════════════════════════════════════════════════
# Moteur de regles
# ═══════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """Signal produit par le moteur de regles."""
    direction: int = 0      # +1=BUY, -1=SELL, 0=HOLD
    score: float = 0.0
    rules: list = field(default_factory=list)


def evaluate_rules(bar: dict) -> Signal:
    """Evalue les 7 regles + filtres et retourne un signal.

    Convention distances DMP (FIX BUG D 15/05/2026 - NEW conv compliant C++):
        dist_X = (level - close) / tick, positif = niveau AU-DESSUS du prix.
        dist_vwap_d > 0 => VWAP au-dessus du prix => prix EN-DESSOUS du VWAP (bearish)
        dist_vwap_d < 0 => VWAP en-dessous du prix => prix AU-DESSUS du VWAP (bullish)
        dist_mq_hvl > 0 => HVL au-dessus => prix EN-DESSOUS du HVL
        dist_mq_hvl < 0 => HVL sous le prix => prix AU-DESSUS du HVL (bullish)
    """
    buy_score = 0.0
    sell_score = 0.0
    rules_fired = []

    # ───────────────────────────────────────────────────────
    # Regle 1 : BIAS Score (5 facteurs ponderes)
    # ───────────────────────────────────────────────────────
    range_pos = _get(bar, "range_pos", 50.0)
    delta_day_dir = _get_int(bar, "delta_day_dir", 0)
    delta_pct = _get(bar, "delta_pct", 0.0)
    dist_vwap = _get(bar, "dist_vwap_d", 0.0)
    vwap_slope = _get(bar, "vwap_slope_10", 0.0)
    cvd_dir = _get_int(bar, "cvd_day_dir", 0)

    # 1a. Range position (30%)
    if range_pos <= 20:
        score_range = 0.30
    elif range_pos >= 80:
        score_range = -0.30
    else:
        score_range = 0.0

    # 1b. Delta jour (25%)
    if delta_day_dir > 0 and abs(delta_pct) > 0.05:
        score_delta = 0.25
    elif delta_day_dir < 0 and abs(delta_pct) > 0.05:
        score_delta = -0.25
    elif delta_day_dir > 0:
        score_delta = 0.10
    elif delta_day_dir < 0:
        score_delta = -0.10
    else:
        score_delta = 0.0

    # 1c. VWAP position (20%) — dist_vwap > 0 = prix en-dessous = bearish
    if dist_vwap < -15:
        score_vwap = 0.20  # prix au-dessus du VWAP = bullish
    elif dist_vwap > 15:
        score_vwap = -0.20  # prix en-dessous du VWAP = bearish
    else:
        score_vwap = 0.0

    # 1d. VWAP slope (15%)
    if vwap_slope > 2:
        score_slope = 0.15
    elif vwap_slope < -2:
        score_slope = -0.15
    else:
        score_slope = 0.0

    # 1e. CVD direction (10%)
    if cvd_dir > 0:
        score_cvd = 0.10
    elif cvd_dir < 0:
        score_cvd = -0.10
    else:
        score_cvd = 0.0

    bias_score = score_range + score_delta + score_vwap + score_slope + score_cvd
    bias_score = max(-1.0, min(1.0, bias_score))

    # Le BIAS seul ne genere PAS de signal — il pondere les autres regles.
    # On le stocke pour l'utiliser comme multiplicateur plus bas.
    # Signal BIAS seulement si tres fort (>= 0.50)
    if abs(bias_score) >= 0.50:
        if bias_score > 0:
            buy_score += bias_score * 0.3
            rules_fired.append(f"BIAS_FORT({bias_score:+.2f})->BUY")
        else:
            sell_score += abs(bias_score) * 0.3
            rules_fired.append(f"BIAS_FORT({bias_score:+.2f})->SELL")

    # ───────────────────────────────────────────────────────
    # Regle 2 : Session filter (applique dans la boucle principale)
    # ───────────────────────────────────────────────────────
    # Gere hors de cette fonction, dans la boucle de backtest.

    # ───────────────────────────────────────────────────────
    # Regle 2b : Niveaux Previous (rebond/rejet)
    # ───────────────────────────────────────────────────────
    # prev_VPOC — aimant, rebond dans la direction d'approche
    # FIX BUG D 15/05/2026 : convention NEW (level - close).
    # dist < 0 = level sous prix = prix au-dessus, descend vers level -> BUY rebond
    for col, weight in [("dist_prev_vpoc", 0.20), ("dist_prev_vwap", 0.18)]:
        dist_raw = _get(bar, col, 0.0)
        dist_abs = abs(dist_raw)
        if 0 < dist_abs < 12:
            w = weight if dist_abs < 5 else weight * 0.6
            if dist_raw < 0:  # level sous prix, prix descend vers -> BUY rebond
                buy_score += w
                rules_fired.append(f"{col}({dist_raw:+.0f}t)->BUY")
            else:  # level au-dessus, prix monte vers -> SELL rejet
                sell_score += w
                rules_fired.append(f"{col}({dist_raw:+.0f}t)->SELL")

    # prev_VWAP SD bands — mean reversion
    # FIX BUG D : SD1d sous le prix (dist > 0) = prix au-dessus SD1d = neutre.
    # SD1d au-dessus du prix (dist > 0 en NEW) = prix EN-DESSOUS = survendu = BUY.
    dist_sd1d = _get(bar, "dist_prev_vwap_sd1d", 0.0)
    if dist_sd1d > 0 and abs(dist_sd1d) < 12:
        w = 0.20 if abs(dist_sd1d) < 5 else 0.12
        buy_score += w
        rules_fired.append(f"prev_SD1d({dist_sd1d:+.0f}t)->BUY")

    dist_sd1u = _get(bar, "dist_prev_vwap_sd1u", 0.0)
    if dist_sd1u < 0 and abs(dist_sd1u) < 12:
        # SD1u sous le prix = prix au-dessus = surachete = SELL
        w = 0.18 if abs(dist_sd1u) < 5 else 0.10
        sell_score += w
        rules_fired.append(f"prev_SD1u({dist_sd1u:+.0f}t)->SELL")

    # prev_VAL (support) et prev_VAH (resistance)
    # FIX BUG D : VAL sous prix (dist < 0) = prix au-dessus du support -> BUY
    dist_val = _get(bar, "dist_prev_val", 0.0)
    dist_abs_val = abs(dist_val)
    if 0 < dist_abs_val < 12:
        if dist_val < 0:
            buy_score += 0.10
            rules_fired.append(f"prev_VAL({dist_val:+.0f}t)->BUY")
        else:
            sell_score += 0.08
            rules_fired.append(f"prev_VAL({dist_val:+.0f}t)->SELL")

    dist_vah = _get(bar, "dist_prev_vah", 0.0)
    dist_abs_vah = abs(dist_vah)
    if 0 < dist_abs_vah < 12:
        if dist_vah > 0:  # VAH au-dessus du prix = resistance -> SELL
            sell_score += 0.10
            rules_fired.append(f"prev_VAH({dist_vah:+.0f}t)->SELL")
        else:  # VAH sous prix = prix au-dessus = breakout -> BUY
            buy_score += 0.08
            rules_fired.append(f"prev_VAH({dist_vah:+.0f}t)->BUY")

    # ───────────────────────────────────────────────────────
    # Regle 2c : Options 0DTE (Call/Put)
    # ───────────────────────────────────────────────────────
    # FIX BUG D : Call au-dessus du prix (dist > 0 NEW) = prix monte vers -> SELL.
    # Put sous le prix (dist < 0 NEW) = prix descend vers -> BUY.
    dist_call_0dte = _get(bar, "dist_mq_call_0dte", 0.0)
    dist_abs_call = abs(dist_call_0dte)
    if 0 < dist_abs_call < 15:
        w = 0.18 if dist_abs_call < 8 else 0.10
        if dist_call_0dte > 0:  # Call au-dessus du prix, monte vers -> SELL
            sell_score += w
            rules_fired.append(f"Call0DTE({dist_call_0dte:+.0f}t)->SELL")

    dist_put_0dte = _get(bar, "dist_mq_put_0dte", 0.0)
    dist_abs_put = abs(dist_put_0dte)
    if 0 < dist_abs_put < 20:
        w = 0.18 if dist_abs_put < 10 else 0.10
        if dist_put_0dte < 0:  # Put sous le prix, descend vers -> BUY
            buy_score += w
            rules_fired.append(f"Put0DTE({dist_put_0dte:+.0f}t)->BUY")

    # ───────────────────────────────────────────────────────
    # Regle 3 : Divergence contrarian
    # ───────────────────────────────────────────────────────
    delta_div = _get_int(bar, "delta_divergence", 0)
    if delta_div == 1:
        if range_pos >= 80:
            sell_score += 0.30
            rules_fired.append("DIV_top(rp>=80)->SELL")
        elif range_pos <= 20:
            buy_score += 0.30
            rules_fired.append("DIV_bottom(rp<=20)->BUY")
        # Bonus si extremement loin du VWAP (surextension)
        # FIX BUG D : dist_vwap > 0 NEW = VWAP au-dessus = prix EN-DESSOUS = BUY rebond.
        # dist_vwap < 0 NEW = VWAP sous le prix = prix AU-DESSUS = SELL rejet.
        if abs(dist_vwap) > 40:
            bonus = 0.10
            if dist_vwap > 0 and range_pos <= 30:
                buy_score += bonus
                rules_fired.append("DIV+VWAP_ext->BUY")
            elif dist_vwap < 0 and range_pos >= 70:
                sell_score += bonus
                rules_fired.append("DIV+VWAP_ext->SELL")

    # ───────────────────────────────────────────────────────
    # Regle 4 : Trapped traders (retest + divergence)
    # ───────────────────────────────────────────────────────
    retest_high_div = _get_int(bar, "retest_high_delta_div", 0)
    bars_since_high = _get(bar, "bars_since_retest_high", 999)
    retest_low_div = _get_int(bar, "retest_low_delta_div", 0)
    bars_since_low = _get(bar, "bars_since_retest_low", 999)
    diag_imb = _get(bar, "diag_imbalance", 0.0)

    if retest_high_div == 1 and bars_since_high <= 5:
        if cvd_dir == -1 or diag_imb < 0:
            sell_score += 0.25
            rules_fired.append(f"TRAPPED_high(bars={bars_since_high:.0f})->SELL")

    if retest_low_div == 1 and bars_since_low <= 5:
        if cvd_dir == 1 or diag_imb > 0:
            buy_score += 0.25
            rules_fired.append(f"TRAPPED_low(bars={bars_since_low:.0f})->BUY")

    # ───────────────────────────────────────────────────────
    # Regle 5 : Open Type bias
    # ───────────────────────────────────────────────────────
    open_conf = _get(bar, "open_bias_conf", 0.0)
    open_dir = _get_int(bar, "open_direction", 0)

    if open_conf >= 0.70:
        if open_dir == 1:
            buy_score += 0.15
            rules_fired.append(f"OPEN_UP(conf={open_conf:.2f})->BUY")
        elif open_dir == -1:
            sell_score += 0.15
            rules_fired.append(f"OPEN_DN(conf={open_conf:.2f})->SELL")

    # ───────────────────────────────────────────────────────
    # Regle 6 : HVL MenthorQ
    # ───────────────────────────────────────────────────────
    dist_hvl = _get(bar, "dist_mq_hvl", 0.0)
    # dist_mq_hvl < 0 = prix AU-DESSUS du HVL (bullish)
    # dist_mq_hvl > 0 = prix EN-DESSOUS du HVL (bearish)
    # IMPORTANT : seulement pertinent si HVL est PROCHE (< 100 ticks)
    # Au-dela de 100t le HVL n'a plus d'influence sur le prix
    hvl_abs = abs(dist_hvl)
    if dist_hvl != 0.0 and hvl_abs < 100:
        if dist_hvl < -20:
            buy_score += 0.20
            rules_fired.append(f"HVL_above({dist_hvl:.0f})->BUY")
        elif dist_hvl > 20:
            sell_score += 0.20
            rules_fired.append(f"HVL_below({dist_hvl:+.0f})->SELL")

    # ───────────────────────────────────────────────────────
    # Regle 7 : VWAP SD bands mean-reversion
    # ───────────────────────────────────────────────────────
    dist_sd2u = _get(bar, "dist_vwap_d_sd2u", 0.0)
    dist_sd2d = _get(bar, "dist_vwap_d_sd2d", 0.0)
    # dist_vwap_d_sd2u < 0 = prix AU-DESSUS du SD2 upper = surachete
    # dist_vwap_d_sd2d > 0 = prix EN-DESSOUS du SD2 lower = survendu
    if dist_sd2u < -5:
        sell_score += 0.20
        rules_fired.append("VWAP_SD2U_above->SELL")
    elif dist_sd2d > 5:
        buy_score += 0.20
        rules_fired.append("VWAP_SD2D_below->BUY")

    # ───────────────────────────────────────────────────────
    # Regle 8 : Double top/bottom + delta divergence (from rule_engine)
    # ───────────────────────────────────────────────────────
    retest_high_count = _get_int(bar, "retest_high_count", 0)
    retest_low_count = _get_int(bar, "retest_low_count", 0)

    if retest_high_count >= 2 and retest_high_div == 1:
        sell_score += 0.20
        rules_fired.append("double_top+div->SELL")

    if retest_low_count >= 2 and retest_low_div == 1:
        buy_score += 0.20
        rules_fired.append("double_bottom+div->BUY")

    # ───────────────────────────────────────────────────────
    # Regle 9 : Trend day probability + day type
    # ───────────────────────────────────────────────────────
    trend_prob = _get(bar, "trend_day_probability", 0.0)
    day_type = _get_int(bar, "day_type", 0)
    # Trend day (type 1 ou 2) avec forte probabilite = favoriser la direction du trend
    if trend_prob > 0.60 and day_type in (1, 2):
        if vwap_slope > 0:
            buy_score += 0.12
            rules_fired.append(f"TREND_UP(p={trend_prob:.0%})->BUY")
        elif vwap_slope < 0:
            sell_score += 0.12
            rules_fired.append(f"TREND_DN(p={trend_prob:.0%})->SELL")

    # ───────────────────────────────────────────────────────
    # Application du BIAS comme multiplicateur
    # ───────────────────────────────────────────────────────
    # Le bias booste ou penalise les scores existants
    if bias_score > 0.15 and buy_score > 0:
        buy_score *= 1.0 + bias_score * 0.3
    elif bias_score < -0.15 and sell_score > 0:
        sell_score *= 1.0 + abs(bias_score) * 0.3
    # Penalite si trade contre le bias
    if bias_score > 0.30 and sell_score > buy_score:
        sell_score *= 0.70
        rules_fired.append("BIAS_contra_sell")
    elif bias_score < -0.30 and buy_score > sell_score:
        buy_score *= 0.70
        rules_fired.append("BIAS_contra_buy")

    # ───────────────────────────────────────────────────────
    # Confirmations order flow
    # ───────────────────────────────────────────────────────

    # Absorption
    absorb_ask = _get_int(bar, "bn_absorb_ask", 0)
    absorb_bid = _get_int(bar, "bn_absorb_bid", 0)
    if absorb_ask and buy_score > 0:
        buy_score *= 1.15
        rules_fired.append("absorb_ask_confirm")
    if absorb_bid and sell_score > 0:
        sell_score *= 1.15
        rules_fired.append("absorb_bid_confirm")

    # BN color
    bn_up = _get_int(bar, "bn_color_up_2", 0)
    bn_dn = _get_int(bar, "bn_color_dn_2", 0)
    if not (bn_up and bn_dn):  # pas contradictoire
        if buy_score > 0 and bn_up:
            buy_score *= 1.10
            rules_fired.append("BN_up_confirm")
        elif buy_score > 0 and bn_dn:
            buy_score *= 0.70
            rules_fired.append("BN_dn_contra")
        if sell_score > 0 and bn_dn:
            sell_score *= 1.10
            rules_fired.append("BN_dn_confirm")
        elif sell_score > 0 and bn_up:
            sell_score *= 0.70
            rules_fired.append("BN_up_contra")

    # Delta bar
    delta_bar = _get(bar, "delta_bar", 0.0)
    if delta_bar > 30 and buy_score > 0:
        buy_score *= 1.08
        rules_fired.append("delta+_confirm")
    elif delta_bar < -30 and sell_score > 0:
        sell_score *= 1.08
        rules_fired.append("delta-_confirm")

    # ───────────────────────────────────────────────────────
    # Momentum filter — bloque les trades contra-trend fort
    # ───────────────────────────────────────────────────────
    delta_day = _get(bar, "delta_day", 0.0)
    if buy_score > 0 and vwap_slope < -0.3 and delta_day < -10000:
        buy_score = 0.0
        rules_fired.append("BLOCKED_bear_momentum")
    if sell_score > 0 and vwap_slope > 0.3 and delta_day > 10000:
        sell_score = 0.0
        rules_fired.append("BLOCKED_bull_momentum")

    # ───────────────────────────────────────────────────────
    # Filtre HVN chemin libre
    # ───────────────────────────────────────────────────────
    hvn_above = _get(bar, "dist_session_hvn_above", 999)
    hvn_below = _get(bar, "dist_session_hvn_below", 999)

    if buy_score > 0 and 0 < hvn_above <= 12:
        buy_score = 0.0
        rules_fired.append(f"BLOCKED_HVN_above={hvn_above:.0f}t")
    if sell_score > 0 and 0 < hvn_below <= 12:
        sell_score = 0.0
        rules_fired.append(f"BLOCKED_HVN_below={hvn_below:.0f}t")

    # ───────────────────────────────────────────────────────
    # Decision
    # ───────────────────────────────────────────────────────
    net = buy_score - sell_score
    sig = Signal(rules=rules_fired)

    if net > MIN_BIAS_SCORE:
        sig.direction = 1
        sig.score = min(net, 1.0)
    elif net < -MIN_BIAS_SCORE:
        sig.direction = -1
        sig.score = max(net, -1.0)
    else:
        sig.score = net

    return sig


# ═══════════════════════════════════════════════════════════════
# Simulation des trades
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """Un trade simule."""
    bar_idx: int = 0
    entry_price: float = 0.0
    direction: int = 0          # +1 BUY, -1 SELL
    sl_price: float = 0.0
    tp_price: float = 0.0
    exit_price: float = 0.0
    exit_bar_idx: int = 0
    result: str = ""            # WIN, LOSS, TIMEOUT
    pnl_ticks: float = 0.0
    session: int = 0
    score: float = 0.0
    rules: list = field(default_factory=list)
    date: str = ""


def simulate_trade(
    bars: list[dict],
    entry_idx: int,
    direction: int,
    sl_ticks: int,
    tp_ticks: int,
) -> Optional[Trade]:
    """Simule un trade a partir de entry_idx.

    Pour chaque barre suivante, verifie si bar_high/bar_low touchent TP ou SL.
    Le SL est teste EN PREMIER (worst case — biais realiste).
    Timeout apres TRADE_TIMEOUT_BARS barres.
    """
    entry_bar = bars[entry_idx]
    entry_price = _get(entry_bar, "price")

    sl_dist = sl_ticks * TICK_SIZE
    tp_dist = tp_ticks * TICK_SIZE

    trade = Trade(
        bar_idx=entry_idx,
        entry_price=entry_price,
        direction=direction,
        session=_get_int(entry_bar, "session", 2),
    )

    if direction == 1:  # BUY
        trade.sl_price = entry_price - sl_dist
        trade.tp_price = entry_price + tp_dist
    else:  # SELL
        trade.sl_price = entry_price + sl_dist
        trade.tp_price = entry_price - tp_dist

    # Scanner les barres suivantes
    max_idx = min(entry_idx + TRADE_TIMEOUT_BARS, len(bars) - 1)
    for i in range(entry_idx + 1, max_idx + 1):
        bar = bars[i]
        bar_high = _get(bar, "bar_high", _get(bar, "price"))
        bar_low = _get(bar, "bar_low", _get(bar, "price"))

        if direction == 1:  # BUY
            # SL teste en premier (worst case)
            if bar_low <= trade.sl_price:
                trade.exit_price = trade.sl_price
                trade.exit_bar_idx = i
                trade.result = "LOSS"
                trade.pnl_ticks = -sl_ticks
                return trade
            if bar_high >= trade.tp_price:
                trade.exit_price = trade.tp_price
                trade.exit_bar_idx = i
                trade.result = "WIN"
                trade.pnl_ticks = tp_ticks
                return trade
        else:  # SELL
            # SL teste en premier
            if bar_high >= trade.sl_price:
                trade.exit_price = trade.sl_price
                trade.exit_bar_idx = i
                trade.result = "LOSS"
                trade.pnl_ticks = -sl_ticks
                return trade
            if bar_low <= trade.tp_price:
                trade.exit_price = trade.tp_price
                trade.exit_bar_idx = i
                trade.result = "WIN"
                trade.pnl_ticks = tp_ticks
                return trade

    # Timeout — exit au prix de la derniere barre scannee
    if max_idx > entry_idx:
        last_bar = bars[max_idx]
        trade.exit_price = _get(last_bar, "price")
        trade.exit_bar_idx = max_idx
        trade.result = "TIMEOUT"
        if direction == 1:
            trade.pnl_ticks = (trade.exit_price - entry_price) / TICK_SIZE
        else:
            trade.pnl_ticks = (entry_price - trade.exit_price) / TICK_SIZE

    return trade


# ═══════════════════════════════════════════════════════════════
# Backtest complet
# ═══════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    """Resultats d'un backtest."""
    instrument: str = ""
    trades: list = field(default_factory=list)
    days_count: int = 0


@dataclass
class BacktestConfig:
    """Configuration parametrable du backtest."""
    sessions_allowed: list = field(default_factory=lambda: [SESSION_LONDON, SESSION_US])
    directions_allowed: list = field(default_factory=lambda: [1, -1])  # +1=BUY, -1=SELL
    min_score: float = MIN_BIAS_SCORE
    london_min_score: float = 0.40
    cooldown_bars: int = COOLDOWN_BARS
    max_trades_day: int = MAX_TRADES_PER_DAY
    skip_lunch: bool = True
    label: str = ""


# Configs pre-definies pour comparaison
CONFIGS = {
    "US_ONLY": BacktestConfig(
        sessions_allowed=[SESSION_US],
        min_score=0.25,
        london_min_score=999,
        label="US seulement",
    ),
    "US+LONDON": BacktestConfig(
        sessions_allowed=[SESSION_LONDON, SESSION_US],
        min_score=0.25,
        london_min_score=0.40,
        label="US + London (London seuil 0.40)",
    ),
    "STRICT": BacktestConfig(
        sessions_allowed=[SESSION_US],
        min_score=0.35,
        cooldown_bars=8,
        max_trades_day=6,
        label="US strict (seuil 0.35, cooldown 8, max 6/j)",
    ),
    "SELL_ONLY": BacktestConfig(
        sessions_allowed=[SESSION_US],
        directions_allowed=[-1],
        min_score=0.30,
        cooldown_bars=8,
        max_trades_day=5,
        label="SELL only US (seuil 0.30, cooldown 8)",
    ),
    "HIGH_CONVICTION": BacktestConfig(
        sessions_allowed=[SESSION_US],
        min_score=0.45,
        cooldown_bars=10,
        max_trades_day=4,
        label="High conviction (seuil 0.45, cooldown 10, max 4/j)",
    ),
}


def run_backtest(
    days_data: dict[str, list[dict]],
    instrument: str,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """Execute le backtest sur toutes les journees d'un instrument."""
    if config is None:
        config = CONFIGS["US+LONDON"]

    result = BacktestResult(instrument=instrument, days_count=len(days_data))
    sl_ticks = SL_TICKS[instrument]
    tp_ticks = TP_TICKS[instrument]

    for date_str, bars in days_data.items():
        trades_today = 0
        last_trade_bar = -config.cooldown_bars

        for i, bar in enumerate(bars):
            session = _get_int(bar, "session", 0)

            # Filtre session
            if session not in config.sessions_allowed:
                continue

            # Filtre VIX
            vix = _get(bar, "vix_level", 20.0)
            if vix < VIX_MIN or vix > VIX_MAX:
                continue

            # Filtre volatilite extreme
            sess_atr = _get(bar, "sess_range_atr", 0.0)
            if sess_atr > MAX_SESS_RANGE_ATR:
                continue

            # Filtre lunch no-trade
            if config.skip_lunch:
                ts = _get(bar, "ts", 0)
                if ts > 0 and _is_lunch_zone(ts):
                    continue

            # Cooldown
            if i - last_trade_bar < config.cooldown_bars:
                continue

            # Max trades/jour
            if trades_today >= config.max_trades_day:
                continue

            # Evaluer les regles
            signal = evaluate_rules(bar)

            if signal.direction == 0:
                continue

            # Seuil minimum
            if abs(signal.score) < config.min_score:
                continue

            # Filtre direction
            if signal.direction not in config.directions_allowed:
                continue

            # Filtre session specifique — London exige un score plus haut
            if session == SESSION_LONDON:
                if abs(signal.score) < config.london_min_score:
                    continue

            # Simuler le trade
            trade = simulate_trade(bars, i, signal.direction, sl_ticks, tp_ticks)
            if trade is None:
                continue

            trade.score = signal.score
            trade.rules = signal.rules
            trade.date = date_str

            result.trades.append(trade)
            trades_today += 1

            # Sauter les barres ou le trade est actif
            if trade.exit_bar_idx > 0:
                last_trade_bar = trade.exit_bar_idx
            else:
                last_trade_bar = i

    return result


# ═══════════════════════════════════════════════════════════════
# Rapport
# ═══════════════════════════════════════════════════════════════

def print_report(result: BacktestResult):
    """Affiche le rapport de backtest."""
    trades = result.trades
    instrument = result.instrument
    n_days = result.days_count

    if not trades:
        print(f"\n{'='*60}")
        print(f"  {instrument} — AUCUN TRADE")
        print(f"{'='*60}")
        return

    # Metriques globales
    wins = [t for t in trades if t.result == "WIN"]
    losses = [t for t in trades if t.result == "LOSS"]
    timeouts = [t for t in trades if t.result == "TIMEOUT"]

    total = len(trades)
    n_wins = len(wins)
    n_losses = len(losses)
    n_timeouts = len(timeouts)

    wr = n_wins / total * 100 if total > 0 else 0.0

    gross_profit = sum(t.pnl_ticks for t in trades if t.pnl_ticks > 0)
    gross_loss = abs(sum(t.pnl_ticks for t in trades if t.pnl_ticks < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    total_pnl = sum(t.pnl_ticks for t in trades)
    ev_trade = total_pnl / total if total > 0 else 0.0

    trades_per_day = total / n_days if n_days > 0 else 0.0

    # Max drawdown (en ticks)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.pnl_ticks
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Rapport global
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS — {instrument}")
    print(f"{'='*60}")
    print(f"  Jours testes     : {n_days}")
    print(f"  Total trades     : {total}")
    print(f"    Wins           : {n_wins}")
    print(f"    Losses         : {n_losses}")
    print(f"    Timeouts       : {n_timeouts}")
    print(f"  Win Rate         : {wr:.1f}%")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  EV/trade         : {ev_trade:+.2f} ticks")
    print(f"  Total P&L        : {total_pnl:+.1f} ticks")
    print(f"  Max Drawdown     : {max_dd:.1f} ticks")
    print(f"  Trades/jour      : {trades_per_day:.1f}")

    # TP/SL utilises
    sl = SL_TICKS[instrument]
    tp = TP_TICKS[instrument]
    print(f"  SL={sl}t ({sl*TICK_SIZE:.2f} pts) / TP={tp}t ({tp*TICK_SIZE:.2f} pts)")

    # Breakeven WR theorique
    be_wr = sl / (sl + tp) * 100
    print(f"  Breakeven WR     : {be_wr:.1f}%")

    # Par session
    print(f"\n  {'─'*50}")
    print(f"  Par session:")
    for sess_id in [SESSION_LONDON, SESSION_US]:
        sess_trades = [t for t in trades if t.session == sess_id]
        if not sess_trades:
            print(f"    {SESSION_NAMES[sess_id]:8s}: 0 trades")
            continue
        sess_wins = sum(1 for t in sess_trades if t.result == "WIN")
        sess_total = len(sess_trades)
        sess_wr = sess_wins / sess_total * 100
        sess_pnl = sum(t.pnl_ticks for t in sess_trades)
        sess_gp = sum(t.pnl_ticks for t in sess_trades if t.pnl_ticks > 0)
        sess_gl = abs(sum(t.pnl_ticks for t in sess_trades if t.pnl_ticks < 0))
        sess_pf = sess_gp / sess_gl if sess_gl > 0 else float("inf")
        print(f"    {SESSION_NAMES[sess_id]:8s}: {sess_total:3d} trades, "
              f"WR {sess_wr:5.1f}%, PF {sess_pf:.2f}, "
              f"P&L {sess_pnl:+.1f}t")

    # Par direction
    print(f"\n  {'─'*50}")
    print(f"  Par direction:")
    for d, dname in [(1, "BUY"), (-1, "SELL")]:
        dir_trades = [t for t in trades if t.direction == d]
        if not dir_trades:
            print(f"    {dname:5s}: 0 trades")
            continue
        dir_wins = sum(1 for t in dir_trades if t.result == "WIN")
        dir_total = len(dir_trades)
        dir_wr = dir_wins / dir_total * 100
        dir_pnl = sum(t.pnl_ticks for t in dir_trades)
        print(f"    {dname:5s}: {dir_total:3d} trades, "
              f"WR {dir_wr:5.1f}%, P&L {dir_pnl:+.1f}t")

    # Par jour
    print(f"\n  {'─'*50}")
    print(f"  Par jour:")
    dates = sorted(set(t.date for t in trades))
    for d in dates:
        day_trades = [t for t in trades if t.date == d]
        day_wins = sum(1 for t in day_trades if t.result == "WIN")
        day_total = len(day_trades)
        day_wr = day_wins / day_total * 100 if day_total > 0 else 0
        day_pnl = sum(t.pnl_ticks for t in day_trades)
        marker = "  " if day_pnl >= 0 else "<<"
        print(f"    {d}: {day_total:2d} trades, "
              f"WR {day_wr:5.1f}%, P&L {day_pnl:+6.1f}t {marker}")

    # Top regles actives
    print(f"\n  {'─'*50}")
    print(f"  Regles les plus frequentes:")
    rule_counts: dict[str, int] = {}
    rule_wins: dict[str, int] = {}
    for t in trades:
        for r in t.rules:
            # Ignorer les confirmations et bloqueurs pour le comptage principal
            if "confirm" in r or "contra" in r or "BLOCKED" in r:
                continue
            base = r.split("(")[0]
            rule_counts[base] = rule_counts.get(base, 0) + 1
            if t.result == "WIN":
                rule_wins[base] = rule_wins.get(base, 0) + 1

    sorted_rules = sorted(rule_counts.items(), key=lambda x: x[1], reverse=True)
    for rule_name, count in sorted_rules[:10]:
        w = rule_wins.get(rule_name, 0)
        rw = w / count * 100 if count > 0 else 0
        print(f"    {rule_name:35s}: {count:3d}x, WR {rw:5.1f}%")

    # Top 5 trades
    print(f"\n  {'─'*50}")
    print(f"  Meilleurs trades:")
    best = sorted(trades, key=lambda t: t.pnl_ticks, reverse=True)[:5]
    for t in best:
        d = "BUY" if t.direction == 1 else "SELL"
        print(f"    {t.date} {d} @ {t.entry_price:.2f}, "
              f"P&L {t.pnl_ticks:+.1f}t, "
              f"{', '.join(t.rules[:3])}")

    print(f"\n  Pires trades:")
    worst = sorted(trades, key=lambda t: t.pnl_ticks)[:5]
    for t in worst:
        d = "BUY" if t.direction == 1 else "SELL"
        print(f"    {t.date} {d} @ {t.entry_price:.2f}, "
              f"P&L {t.pnl_ticks:+.1f}t, "
              f"{', '.join(t.rules[:3])}")


def print_combined_summary(results: list[BacktestResult]):
    """Resume combine tous instruments."""
    all_trades = []
    for r in results:
        all_trades.extend(r.trades)

    if not all_trades:
        print("\nAucun trade genere sur aucun instrument.")
        return

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t.result == "WIN")
    wr = wins / total * 100

    total_pnl = sum(t.pnl_ticks for t in all_trades)
    gp = sum(t.pnl_ticks for t in all_trades if t.pnl_ticks > 0)
    gl = abs(sum(t.pnl_ticks for t in all_trades if t.pnl_ticks < 0))
    pf = gp / gl if gl > 0 else float("inf")

    total_days = sum(r.days_count for r in results)
    tpd = total / total_days * 2 if total_days > 0 else 0  # /2 car 2 instruments

    print(f"\n{'='*60}")
    print(f"  RESUME COMBINE (tous instruments)")
    print(f"{'='*60}")
    print(f"  Total trades : {total}")
    print(f"  Win Rate     : {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Total P&L    : {total_pnl:+.1f} ticks")
    print(f"  Trades/jour  : ~{tpd:.1f} (par instrument)")

    # Verdict GO/NO-GO
    print(f"\n  {'─'*50}")
    print(f"  VERDICT:")
    issues = []
    if pf < 1.3:
        issues.append(f"PF {pf:.2f} < 1.3")
    if wr < 45:
        issues.append(f"WR {wr:.1f}% < 45%")
    ev = total_pnl / total if total > 0 else 0
    if ev < 1.0:
        issues.append(f"EV {ev:.2f}t < 1.0t")

    if issues:
        print(f"    NO-GO : {', '.join(issues)}")
        print(f"    -> Les regles seules ne suffisent PAS. ML necessaire.")
    else:
        print(f"    GO : Toutes les metriques au-dessus des seuils !")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def _detect_instrument(data_dir: str) -> str:
    """Detecte l'instrument depuis le nom du dossier ou le premier fichier."""
    dirname = os.path.basename(os.path.normpath(data_dir)).upper()
    if dirname in ("ES", "NQ"):
        return dirname
    files = sorted(glob.glob(os.path.join(data_dir, "*.jsonl")))
    if files:
        with open(files[0], "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line:
                d = json.loads(first_line)
                return d.get("sym", "ES").upper()
    return "ES"


def main():
    """Point d'entree principal."""
    if len(sys.argv) < 2:
        print("Usage: python -X utf8 CORE/mia_rule_backtest.py DATA/ES [DATA/NQ]")
        sys.exit(1)

    dirs = sys.argv[1:]

    # Charger toutes les donnees d'abord
    datasets: list[tuple[str, dict]] = []
    for data_dir in dirs:
        instrument = _detect_instrument(data_dir)
        print(f"\n--- Chargement {instrument} depuis {data_dir} ---")
        days_data = load_jsonl_dir(data_dir)
        if days_data:
            datasets.append((instrument, days_data))

    if not datasets:
        print("Aucune donnee chargee.")
        sys.exit(1)

    # Tester chaque config
    for config_name, config in CONFIGS.items():
        print(f"\n{'#'*60}")
        print(f"# CONFIG: {config_name} — {config.label}")
        print(f"{'#'*60}")

        results = []
        for instrument, days_data in datasets:
            bt_result = run_backtest(days_data, instrument, config)
            results.append(bt_result)
            print_report(bt_result)

        if len(results) > 1:
            print_combined_summary(results)


if __name__ == "__main__":
    main()
