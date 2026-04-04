"""
v1_engines.py — Logique metier extraite du V1 MIA, epuree pour le dashboard V2.
7 moteurs autonomes, zero dependance externe, input = dict features DMP.

Modules :
  1. bn_score()           — Battle Navale scoring contrarian (Order Flow)
  2. detect_confluence()   — Confluence multi-niveaux (Options/Gamma)
  3. analyze_corridor()    — Corridor CALL/PUT + headroom (Options/Gamma)
  4. check_health()        — Catastrophe monitor (Bot Status)
  5. detect_regime()       — Regime tracker BULL/BEAR/NEUTRAL (Market Context)
  6. compute_sltp()        — SL/TP adaptatifs sur niveaux (Signaux)
  7. suggest_trade()       — Suggestion de trade avec grade (Signaux)
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


TICK_SIZE = 0.25


# ===================================================================
# 1. BATTLE NAVALE — Scoring contrarian (Order Flow)
# ===================================================================

EDGE_CONTRARIAN_THRESHOLD = 1
DEPTH_THRESHOLD = 0.05
PCT_THRESHOLD = 0.52
MAX_DIST = {"ES": 20, "NQ": 30}


def bn_score(features: Dict[str, Any], symbol: str = "ES") -> Dict[str, Any]:
    """Score Battle Navale contrarian. Layers: distance → edge → pct."""
    edge_buy = features.get("fp_edge_buy", 0) + features.get("bar_edge_buy", 0)
    edge_sell = features.get("fp_edge_sell", 0) + features.get("bar_edge_sell", 0)
    depth = features.get("ask_bid_imbalance", 0.0)
    buy_pct = features.get("ask_pct", 0.5)
    sell_pct = features.get("bid_pct", 0.5)

    dist_call = abs(features.get("dist_mq_call", 999))
    dist_put = abs(features.get("dist_mq_put", 999))
    dist_hvl = abs(features.get("dist_mq_hvl", 999))
    nearest_dist = min(dist_call, dist_put, dist_hvl)

    max_d = MAX_DIST.get(symbol, 20)
    passed, failed = [], []

    # Layer 1 : distance au niveau le plus proche
    if nearest_dist > max_d:
        failed.append(f"L1_dist={nearest_dist:.0f}t>{max_d}")
        return _bn_result("NEUTRAL", 0.0, edge_buy, edge_sell, passed, failed)

    direction = "LONG" if dist_put < dist_call else "SHORT"
    passed.append(f"L1_{nearest_dist:.0f}t_{direction}")

    # Layer 2 : edge contrarian (vendeurs epuises → LONG, acheteurs epuises → SHORT)
    if direction == "LONG":
        l2_ok = edge_sell >= EDGE_CONTRARIAN_THRESHOLD or depth > DEPTH_THRESHOLD
    else:
        l2_ok = edge_buy >= EDGE_CONTRARIAN_THRESHOLD or depth < -DEPTH_THRESHOLD

    if not l2_ok:
        failed.append("L2_no_edge")
        return _bn_result("NEUTRAL", 0.0, edge_buy, edge_sell, passed, failed)
    passed.append("L2_edge_ok")

    # Layer 3 : confirmation pct (bonus)
    l3_ok = (buy_pct > PCT_THRESHOLD) if direction == "LONG" else (sell_pct > PCT_THRESHOLD)
    if l3_ok:
        passed.append("L3_pct_ok")

    confidence = 0.8 + (0.2 if l3_ok else 0.0)
    return _bn_result(direction, confidence, edge_buy, edge_sell, passed, failed)


def _bn_result(signal, confidence, edge_buy, edge_sell, passed, failed):
    return {
        "signal": signal, "confidence": round(confidence, 2),
        "edge_buy": edge_buy, "edge_sell": edge_sell,
        "layers_passed": passed, "layers_failed": failed,
    }


# ===================================================================
# 2. CONFLUENCE DETECTOR (Options/Gamma)
# ===================================================================

CONFLUENCE_TOLERANCE = 15  # ticks
CONFLUENCE_MIN_LEVELS = 2
CONFLUENCE_BONUS_PER_LEVEL = 0.10
CONFLUENCE_MAX_BONUS = 0.25


def detect_confluence(features: Dict[str, Any]) -> Dict[str, Any]:
    """Detecte les confluences de niveaux dans un rayon de 15 ticks."""
    levels = _extract_price_levels(features)
    if len(levels) < CONFLUENCE_MIN_LEVELS:
        return {"confluences": [], "max_bonus": 0.0, "count": 0}

    confluences = []
    i = 0
    while i < len(levels):
        group = [levels[i]]
        j = i + 1
        while j < len(levels) and abs(levels[j][0] - levels[i][0]) / TICK_SIZE <= CONFLUENCE_TOLERANCE:
            group.append(levels[j])
            j += 1
        if len(group) >= CONFLUENCE_MIN_LEVELS:
            avg_price = sum(p for p, _ in group) / len(group)
            bonus = min(CONFLUENCE_BONUS_PER_LEVEL * (len(group) - 1), CONFLUENCE_MAX_BONUS)
            names = [n for _, n in group]
            confluences.append({
                "price": round(avg_price, 2), "count": len(group),
                "levels": names, "bonus": round(bonus, 2),
            })
        i = j if j > i + 1 else i + 1

    max_bonus = max((c["bonus"] for c in confluences), default=0.0)
    return {"confluences": confluences, "max_bonus": max_bonus, "count": len(confluences)}


def _extract_price_levels(f: Dict) -> List:
    """Extrait les niveaux avec prix, tries par prix croissant."""
    levels = []
    for key in ["dist_mq_call", "dist_mq_put", "dist_mq_hvl",
                "dist_mq_call_0dte", "dist_mq_put_0dte",
                "dist_gex_nearest_up", "dist_gex_nearest_dn",
                "dist_prev_vpoc", "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",
                "dist_vwap_d", "dist_vwap_d_sd1u", "dist_vwap_d_sd1d",
                "dist_swing_high", "dist_swing_low"]:
        val = f.get(key)
        if val is not None and val != 0 and str(val) != "INVALID":
            levels.append((float(val), key.replace("dist_", "")))
    return sorted(levels, key=lambda x: x[0])


# ===================================================================
# 3. CORRIDOR MANAGER (Options/Gamma)
# ===================================================================

NEAR_WALL_THRESHOLD = 0.0018  # 0.18%


def analyze_corridor(features: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse la position dans le corridor CALL/PUT."""
    call_dist = features.get("dist_mq_call", 0)
    put_dist = features.get("dist_mq_put", 0)
    hvl_dist = features.get("dist_mq_hvl", 0)

    # Distances positives = au-dessus, negatives = en-dessous
    in_corridor = call_dist > 0 and put_dist < 0  # entre call (au-dessus) et put (en-dessous)

    call_ticks = abs(call_dist) if call_dist else 999
    put_ticks = abs(put_dist) if put_dist else 999
    total_width = call_ticks + put_ticks if call_ticks < 999 and put_ticks < 999 else 0

    # Position dans le corridor (0 = au put, 1 = au call)
    position_pct = put_ticks / total_width if total_width > 0 else 0.5

    # Headroom
    hr_long = call_ticks
    hr_short = put_ticks

    # Near wall
    near_call = call_ticks <= 10
    near_put = put_ticks <= 10

    # Risk factor
    if min(call_ticks, put_ticks) <= 5:
        risk = "HIGH"
    elif min(call_ticks, put_ticks) <= 15:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "in_corridor": in_corridor,
        "call_dist_ticks": round(call_ticks, 1),
        "put_dist_ticks": round(put_ticks, 1),
        "hvl_dist_ticks": round(abs(hvl_dist), 1) if hvl_dist else None,
        "corridor_width": round(total_width, 1),
        "position_pct": round(position_pct * 100, 1),
        "near_call": near_call,
        "near_put": near_put,
        "risk": risk,
    }


# ===================================================================
# 4. CATASTROPHE MONITOR (Bot Status)
# ===================================================================

def check_health(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    """Verifie la sante du systeme depuis le dashboard JSON du bot."""
    checks = {}
    issues = []

    # Bot running
    bs = bot_data.get("bot_status", {})
    running = bs.get("running", False)
    checks["bot"] = "OK" if running else "DOWN"
    if not running:
        issues.append("bot_offline")

    # Heartbeat freshness
    hb = bs.get("last_heartbeat", "")
    if hb:
        try:
            hb_time = datetime.strptime(hb, "%Y-%m-%d %H:%M:%S")
            age_sec = (datetime.now() - hb_time).total_seconds()
            checks["heartbeat"] = "OK" if age_sec < 30 else ("STALE" if age_sec < 120 else "DEAD")
            if age_sec >= 30:
                issues.append(f"heartbeat_stale_{int(age_sec)}s")
        except ValueError:
            checks["heartbeat"] = "UNKNOWN"
    else:
        checks["heartbeat"] = "UNKNOWN"

    # VIX data
    ml = bot_data.get("market_live", {})
    vix_valid = ml.get("vix_valid", False)
    checks["vix"] = "OK" if vix_valid else "NO_DATA"
    if not vix_valid:
        issues.append("vix_no_data")

    # ATR data
    atr_valid = ml.get("atr_valid", False)
    checks["atr"] = "OK" if atr_valid else "NO_DATA"
    if not atr_valid:
        issues.append("atr_no_data")

    # Warnings
    warnings = bot_data.get("warnings", {})
    news = warnings.get("news_detected", False)
    checks["news"] = "BLOCKED" if news else "CLEAR"
    if news:
        issues.append(f"news_block:{warnings.get('news_message', '')}")

    # ES status
    es = bot_data.get("es", {})
    es_consec = es.get("consecutive_losses", 0)
    checks["es_streak"] = "OK" if es_consec < 3 else "PAUSE"
    if es_consec >= 3:
        issues.append(f"es_consecutive_losses_{es_consec}")

    # NQ status
    nq = bot_data.get("nq", {})
    nq_consec = nq.get("consecutive_losses", 0)
    checks["nq_streak"] = "OK" if nq_consec < 3 else "PAUSE"
    if nq_consec >= 3:
        issues.append(f"nq_consecutive_losses_{nq_consec}")

    # Mode final
    n_ok = sum(1 for v in checks.values() if v == "OK")
    n_total = len(checks)

    if any(v in ("DOWN", "DEAD") for v in checks.values()):
        mode = "KILL"
    elif any(v in ("STALE", "PAUSE", "BLOCKED", "NO_DATA") for v in checks.values()):
        mode = "WARN"
    else:
        mode = "OK"

    return {
        "mode": mode,
        "checks": checks,
        "health_pct": round(n_ok / n_total * 100) if n_total else 0,
        "issues": issues,
    }


# ===================================================================
# 5. REGIME TRACKER (Market Context)
# ===================================================================

def detect_regime(features: Dict[str, Any]) -> Dict[str, Any]:
    """Detecte le regime de marche depuis les features DMP."""
    bull_votes, bear_votes = 0, 0
    votes = {}

    # VWAP triple align
    vta = features.get("vwap_triple_align", 0)
    if vta > 0:
        bull_votes += 1
        votes["vwap_align"] = "BULL"
    elif vta < 0:
        bear_votes += 1
        votes["vwap_align"] = "BEAR"

    # VWAP slope
    slope = features.get("vwap_slope_10", 0)
    if slope > 0.5:
        bull_votes += 1
        votes["vwap_slope"] = "BULL"
    elif slope < -0.5:
        bear_votes += 1
        votes["vwap_slope"] = "BEAR"

    # Delta day direction
    ddd = features.get("delta_day_dir", 0)
    if ddd > 0:
        bull_votes += 1
        votes["delta_day"] = "BULL"
    elif ddd < 0:
        bear_votes += 1
        votes["delta_day"] = "BEAR"

    # CVD direction
    cvd = features.get("cvd_day_dir", 0)
    if cvd > 0:
        bull_votes += 1
        votes["cvd"] = "BULL"
    elif cvd < 0:
        bear_votes += 1
        votes["cvd"] = "BEAR"

    # IB extension
    ib_up = features.get("ib_broken_up", 0)
    ib_dn = features.get("ib_broken_down", 0)
    if ib_up and not ib_dn:
        bull_votes += 1
        votes["ib_break"] = "BULL"
    elif ib_dn and not ib_up:
        bear_votes += 1
        votes["ib_break"] = "BEAR"

    # AMD session bias
    amd = features.get("amd_session_bias", 0)
    if amd > 0.3:
        bull_votes += 1
        votes["amd_bias"] = "BULL"
    elif amd < -0.3:
        bear_votes += 1
        votes["amd_bias"] = "BEAR"

    min_votes = 3
    if bull_votes >= min_votes and bull_votes > bear_votes:
        regime = "BULLISH"
    elif bear_votes >= min_votes and bear_votes > bull_votes:
        regime = "BEARISH"
    else:
        regime = "NEUTRAL"

    return {
        "regime": regime,
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
        "votes": votes,
        "strength": abs(bull_votes - bear_votes),
    }


# ===================================================================
# 6. ADAPTIVE SL/TP (Signaux)
# ===================================================================

SL_CONFIG = {
    "ES": {"buf": 3, "min": 12, "max": 30, "default": 15, "tp_default": 15},
    "NQ": {"buf": 5, "min": 15, "max": 40, "default": 25, "tp_default": 31},
}


def compute_sltp(
    symbol: str, direction: str, entry: float, features: Dict[str, Any]
) -> Dict[str, Any]:
    """Calcule SL/TP adaptatifs depuis les niveaux DMP."""
    cfg = SL_CONFIG.get(symbol, SL_CONFIG["ES"])
    buf = cfg["buf"] * TICK_SIZE
    min_d = cfg["min"] * TICK_SIZE
    max_d = cfg["max"] * TICK_SIZE
    default_sl = cfg["default"] * TICK_SIZE
    default_tp = cfg["tp_default"] * TICK_SIZE

    # Collecter les niveaux comme SL potentiels
    level_keys = [
        "dist_session_hvn_below", "dist_session_lvn_below",
        "dist_cur_val", "dist_cur_vpoc", "dist_swing_low",
        "dist_mq_put", "dist_mq_hvl", "dist_vwap_d",
        "dist_session_hvn_above", "dist_session_lvn_above",
        "dist_cur_vah", "dist_swing_high",
        "dist_mq_call", "dist_gex_nearest_up", "dist_gex_nearest_dn",
    ]

    sl, sl_source = entry - default_sl, "fixed"
    tp, tp_source = entry + default_tp, "fixed"

    if direction == "LONG":
        # SL = niveau sous le prix
        candidates = []
        for key in level_keys:
            dist = features.get(key)
            if dist is not None and dist < 0 and str(dist) != "INVALID":
                sl_price = entry + float(dist) * TICK_SIZE - buf
                sl_dist = entry - sl_price
                if min_d <= sl_dist <= max_d:
                    candidates.append((sl_price, key, sl_dist))
        if candidates:
            candidates.sort(key=lambda x: x[2])  # le plus serre
            sl, sl_source, _ = candidates[0]

        # TP = premier obstacle au-dessus
        for key in level_keys:
            dist = features.get(key)
            if dist is not None and dist > 0 and str(dist) != "INVALID":
                tp_price = entry + float(dist) * TICK_SIZE
                if tp_price > entry:
                    tp, tp_source = tp_price, key
                    break
    else:
        # SL = niveau au-dessus
        candidates = []
        for key in level_keys:
            dist = features.get(key)
            if dist is not None and dist > 0 and str(dist) != "INVALID":
                sl_price = entry + float(dist) * TICK_SIZE + buf
                sl_dist = sl_price - entry
                if min_d <= sl_dist <= max_d:
                    candidates.append((sl_price, key, sl_dist))
        if candidates:
            candidates.sort(key=lambda x: x[2])
            sl, sl_source, _ = candidates[0]

        # TP = premier obstacle en-dessous
        for key in level_keys:
            dist = features.get(key)
            if dist is not None and dist < 0 and str(dist) != "INVALID":
                tp_price = entry + float(dist) * TICK_SIZE
                if tp_price < entry:
                    tp, tp_source = tp_price, key
                    break

    sl_ticks = abs(entry - sl) / TICK_SIZE
    tp_ticks = abs(tp - entry) / TICK_SIZE
    rr = tp_ticks / sl_ticks if sl_ticks > 0 else 0

    return {
        "sl": round(sl, 2), "tp": round(tp, 2),
        "sl_ticks": round(sl_ticks, 1), "tp_ticks": round(tp_ticks, 1),
        "rr": round(rr, 2),
        "sl_source": sl_source.replace("dist_", ""),
        "tp_source": tp_source.replace("dist_", ""),
    }


# ===================================================================
# 7. TRADE SUGGESTION (Signaux)
# ===================================================================

SESSIONS = {
    "ASIA": (0, 8, 0.6), "LONDON": (8, 11, 0.9), "PRE_US": (11, 15, 0.5),
    "US_OPEN": (15, 17, 1.0), "US_LUNCH": (17, 20, 0.7),
    "US_POWER": (20, 22, 1.0), "CLOSED": (22, 24, 0.0),
}


def get_session(hour: int = None) -> Dict[str, Any]:
    """Retourne la session de trading actuelle."""
    h = hour if hour is not None else datetime.utcnow().hour
    for name, (start, end, quality) in SESSIONS.items():
        if start <= h < end:
            return {"name": name, "quality": quality, "tradable": quality >= 0.7}
    return {"name": "CLOSED", "quality": 0.0, "tradable": False}


def suggest_trade(features: Dict[str, Any], symbol: str = "ES") -> Dict[str, Any]:
    """Genere une suggestion de trade basee sur les niveaux les plus proches."""
    # Trouver le niveau le plus proche
    level_priority = {
        "mq_hvl": 100, "mq_call": 92, "mq_put": 92,
        "mq_call_0dte": 94, "mq_put_0dte": 94,
        "gex_nearest_up": 85, "gex_nearest_dn": 85,
        "cur_vpoc": 90, "cur_vah": 88, "cur_val": 88,
        "swing_high": 80, "swing_low": 80,
        "vwap_d": 75, "prev_vpoc": 78,
    }

    max_entry = 10 if symbol == "NQ" else 8
    best_level = None
    best_priority = -1
    best_dist = 999

    for key, priority in level_priority.items():
        dist_key = f"dist_{key}"
        dist = features.get(dist_key)
        if dist is None or str(dist) == "INVALID":
            continue
        abs_dist = abs(float(dist))
        if abs_dist <= max_entry and priority > best_priority:
            best_level = key
            best_priority = priority
            best_dist = abs_dist

    if not best_level:
        return {"has_signal": False, "reason": f"Aucun niveau <= {max_entry}t"}

    dist_val = features.get(f"dist_{best_level}", 0)
    direction = "LONG" if float(dist_val) < 0 else "SHORT"

    session = get_session()
    sltp = compute_sltp(symbol, direction, features.get("bar_high", 0) or 0, features)

    # Score qualite
    score = 0
    if best_priority >= 95:
        score += 30
    elif best_priority >= 85:
        score += 20
    if best_dist <= 5:
        score += 20
    elif best_dist <= 10:
        score += 10
    if sltp["rr"] >= 2.0:
        score += 15
    elif sltp["rr"] >= 1.5:
        score += 10
    if session["quality"] >= 0.9:
        score += 10
    if features.get("bool_va_confluence", 0):
        score += 10

    grade = "A" if score >= 70 else ("B" if score >= 50 else ("C" if score >= 30 else "D"))

    return {
        "has_signal": True,
        "direction": direction,
        "level": best_level,
        "level_dist": round(best_dist, 1),
        "sltp": sltp,
        "quality_score": score,
        "grade": grade,
        "session": session,
    }
