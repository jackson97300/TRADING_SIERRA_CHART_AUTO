"""Fonctions build_* du dashboard MIA.

Chaque builder prend une barre JSONL (dict) et retourne un dict structure
pour le frontend. Toutes les distances sont converties en prix absolus.
"""
import logging
from typing import List, Optional, Tuple

from DASHBOARD.api.readers import (
    DAY_TYPE_LABELS,
    OPEN_TYPE_LABELS,
    PROFILE_SHAPE_LABELS,
    RVOL_REGIME_LABELS,
    TICK_SIZE,
    VIX_REGIME_LABELS,
    dist_to_price,
    get_field,
    get_int_field,
    get_nullable_field,
    get_str_field,
    rvol_to_regime,
    vix_dist_to_price,
)


def _nullable_round(val, ndigits=4):
    """Round si val est numerique, sinon retourne None (pour features nullable)."""
    if val is None:
        return None
    try:
        return round(float(val), ndigits)
    except (ValueError, TypeError):
        return None

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Helper partage
# ═══════════════════════════════════════════════════════════════


def _calc_confidence(score: float, factors: list[dict]) -> float:
    """Confiance = consensus facteurs + amplitude score.

    Malus si peu de facteurs actifs (< 3).
    """
    if not factors:
        return 0.0
    bulls = sum(1 for f in factors if f.get("icon") == "bull")
    bears = sum(1 for f in factors if f.get("icon") == "bear")
    active = bulls + bears
    if active == 0:
        return 0.0
    consensus = max(bulls, bears) / active
    amplitude = min(abs(score) * 2, 1.0)
    confidence = consensus * 0.6 + amplitude * 0.4
    # Malus si trop peu de facteurs — 1 facteur seul ne vaut pas 84%
    if active < 3:
        confidence *= active / 3
    return min(confidence, 1.0)


# ═══════════════════════════════════════════════════════════════
# Builder 0 : Bot Status
# ═══════════════════════════════════════════════════════════════


def build_bot_status(bot_data: dict) -> dict:
    """Statut bot basique."""
    bs = bot_data.get("bot_status", {})
    return {
        "running": bs.get("running", False),
        "global_status": bs.get("global_status", "UNKNOWN"),
        "last_heartbeat": bs.get("last_heartbeat", ""),
    }


def build_instrument_status(bot_data: dict, symbol: str) -> dict:
    """Statut d'un instrument (ES ou NQ)."""
    instr = bot_data.get(symbol.lower(), {})
    return {
        "enabled": instr.get("enabled", False),
        "in_position": instr.get("in_position", False),
        "status": instr.get("status", "Bot offline"),
        "trades_today": instr.get("trades_today", 0),
        "wins": instr.get("wins", 0),
        "losses": instr.get("losses", 0),
        "pnl_today": instr.get("pnl_today", 0.0),
        "consecutive_losses": instr.get("consecutive_losses", 0),
        "last_rejected": instr.get("last_rejected", ""),
        "signals_rejected": instr.get("signals_rejected", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 1 : Price Banner
# ═══════════════════════════════════════════════════════════════


def build_price_banner(bar_es: dict, bar_nq: dict) -> dict:
    """Bandeau prix live ES + NQ."""
    def _instrument(bar: dict) -> dict:
        if not bar:
            return {"price": 0, "atr": 0, "change_pct": 0, "session": "N/A"}
        price = get_field(bar, "price", 0.0)
        sess_range = get_field(bar, "sess_range_ticks", 0.0)
        dist_sess_low = get_field(bar, "dist_sess_low", 0.0)
        # Position dans le range session en %
        range_pct = 0.0
        if sess_range > 0:
            range_pct = round(dist_sess_low / sess_range * 100, 1)
        return {
            "price": price,
            "bar_high": get_field(bar, "bar_high", price),
            "bar_low": get_field(bar, "bar_low", price),
            "atr": round(get_field(bar, "atr", 0.0), 1),
            "session": get_str_field(bar, "session_id", "N/A"),
            "session_range": sess_range,
            "range_position_pct": range_pct,
            "ts": bar.get("ts", 0),
        }

    return {
        "es": _instrument(bar_es),
        "nq": _instrument(bar_nq),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 2 : Regime & Context
# ═══════════════════════════════════════════════════════════════


def build_regime_context(bar: dict) -> dict:
    """VIX complet + VWAP tendance + momentum + bias calcule."""
    if not bar:
        return {}

    vix = get_field(bar, "vix_level", 0.0)
    vix_regime = get_int_field(bar, "vix_regime", 1)
    atr = get_field(bar, "atr", 0.0)
    atr_ratio = get_field(bar, "sess_range_atr", 0.0)

    # VWAP slopes et sides
    vwap_slope_10 = get_field(bar, "vwap_slope_10", 0.0)
    vwap_slope_30 = get_field(bar, "vwap_slope_30", 0.0)
    vwap_d_side = get_int_field(bar, "vwap_d_side", 0)
    vwap_w_side = get_int_field(bar, "vwap_w_side", 0)
    vwap_m_side = get_int_field(bar, "vwap_m_side", 0)
    triple_align = get_int_field(bar, "vwap_triple_align", 0)

    # Momentum
    momentum_3 = get_field(bar, "momentum_3b", 0.0)
    momentum_5 = get_field(bar, "momentum_5b", 0.0)
    ma_trend = get_int_field(bar, "ma_trend", 0)

    # Bias (inspire du V1 calculate_bias)
    score = 0.0
    factors = []

    # Position dans range 1D (30%)
    pos = get_field(bar, "range_pos", 50.0)
    new_high = get_int_field(bar, "new_swing_high", 0)
    new_low = get_int_field(bar, "new_swing_low", 0)
    delta_day = get_field(bar, "delta_day", 0.0)
    if pos >= 80:
        # Breakout detection : nouveau high + delta positif = expansion, pas un top
        if new_high and delta_day > 0:
            score += 0.10
            factors.append({"icon": "bull", "text": f"Position 1D: {pos:.0f}% (BREAKOUT UP)"})
        else:
            score -= 0.30
            factors.append({"icon": "bear", "text": f"Position 1D: {pos:.0f}% (TOP)"})
    elif pos <= 20:
        if new_low and delta_day < 0:
            score -= 0.10
            factors.append({"icon": "bear", "text": f"Position 1D: {pos:.0f}% (BREAKDOWN)"})
        else:
            score += 0.30
            factors.append({"icon": "bull", "text": f"Position 1D: {pos:.0f}% (BOTTOM)"})
    else:
        factors.append({"icon": "neutral", "text": f"Position 1D: {pos:.0f}% (MIDDLE)"})

    # OrderFlow — base sur le delta cumule du jour (stable) + delta barre (confirmation)
    delta_pct = get_field(bar, "delta_pct", 0.0)
    delta_day_dir = get_int_field(bar, "delta_day_dir", 0)
    # Le delta jour donne la tendance. Le delta barre confirme ou contredit.
    if delta_day_dir > 0 and delta_pct > 0.05:
        score += 0.25
        factors.append({"icon": "bull", "text": f"OrderFlow: jour ACHETEUR + barre {delta_pct:+.1%}"})
    elif delta_day_dir < 0 and delta_pct < -0.05:
        score -= 0.25
        factors.append({"icon": "bear", "text": f"OrderFlow: jour VENDEUR + barre {delta_pct:+.1%}"})
    elif delta_day_dir > 0:
        score += 0.10
        factors.append({"icon": "bull", "text": f"OrderFlow: jour ACHETEUR (barre neutre {delta_pct:+.1%})"})
    elif delta_day_dir < 0:
        score -= 0.10
        factors.append({"icon": "bear", "text": f"OrderFlow: jour VENDEUR (barre neutre {delta_pct:+.1%})"})
    else:
        factors.append({"icon": "neutral", "text": f"OrderFlow: neutre ({delta_pct:+.1%})"})

    # VWAP position (20%) — dist_vwap_d = (VWAP-prix)/tick, positif = VWAP au-dessus = bear
    dist_vwap = get_field(bar, "dist_vwap_d", 0.0)
    if dist_vwap < -15:
        score += 0.20
        factors.append({"icon": "bull", "text": f"VWAP: {dist_vwap:.1f}t (PRIX AU-DESSUS)"})
    elif dist_vwap > 15:
        score -= 0.20
        factors.append({"icon": "bear", "text": f"VWAP: +{dist_vwap:.1f}t (PRIX EN-DESSOUS)"})
    else:
        factors.append({"icon": "neutral", "text": f"VWAP: {dist_vwap:+.1f}t (PROCHE)"})

    # VWAP slope (15%)
    if vwap_slope_10 > 2:
        score += 0.15
        factors.append({"icon": "bull", "text": f"VWAP Slope: {vwap_slope_10:+.1f} (HAUSSIER)"})
    elif vwap_slope_10 < -2:
        score -= 0.15
        factors.append({"icon": "bear", "text": f"VWAP Slope: {vwap_slope_10:+.1f} (BAISSIER)"})
    else:
        factors.append({"icon": "neutral", "text": f"VWAP Slope: {vwap_slope_10:+.1f} (PLAT)"})

    # CVD direction (10%)
    cvd_dir = get_int_field(bar, "cvd_day_dir", 0)
    if cvd_dir == 1:
        score += 0.10
        factors.append({"icon": "bull", "text": "CVD: ACCUMULATION"})
    elif cvd_dir == -1:
        score -= 0.10
        factors.append({"icon": "bear", "text": "CVD: DISTRIBUTION"})

    # ── Divergence Quality Score ──
    # Une div seule = bruit. Une div avec contexte = sniper shot.
    delta_div = get_int_field(bar, "delta_divergence", 0)
    div_quality = 0.0
    div_factors = []

    if delta_div:
        # 1. Extension VWAP (le facteur le plus important)
        vwap_stretch = abs(dist_vwap)
        if vwap_stretch > 200:
            div_quality += 3.0
            div_factors.append(f"VWAP stretch extreme ({vwap_stretch:.0f}t)")
        elif vwap_stretch > 80:
            div_quality += 2.0
            div_factors.append(f"VWAP stretch fort ({vwap_stretch:.0f}t)")
        elif vwap_stretch > 30:
            div_quality += 1.0
            div_factors.append(f"VWAP stretch modere ({vwap_stretch:.0f}t)")
        # <50t = div sans extension = bruit

        # 2. Range position extreme
        if pos >= 90 or pos <= 10:
            div_quality += 2.0
            div_factors.append(f"Range extreme ({pos:.0f}%)")
        elif pos >= 80 or pos <= 20:
            div_quality += 1.0
            div_factors.append(f"Range eleve ({pos:.0f}%)")

        # 3. Sess/ATR etendu (le marche a deja beaucoup bouge)
        if atr_ratio > 1.3:
            div_quality += 1.5
            div_factors.append(f"Session etendue ({atr_ratio:.2f}x ATR)")
        elif atr_ratio > 1.0:
            div_quality += 0.5
            div_factors.append(f"Session active ({atr_ratio:.2f}x ATR)")

        # 4. VIX eleve = mouvements plus amples = div plus significative
        if vix > 25:
            div_quality += 1.0
            div_factors.append(f"VIX eleve ({vix:.1f})")
        elif vix > 20:
            div_quality += 0.5
            div_factors.append(f"VIX modere ({vix:.1f})")

        # 5. VWAP triple align CONTRE la direction du prix = mean reversion
        # Prix au-dessus des 3 VWAPs (dist_vwap < 0) = overextended haut
        if dist_vwap < -100 and vwap_d_side == 1 and vwap_w_side == 1 and vwap_m_side == 1:
            div_quality += 1.5
            div_factors.append("Triple VWAP au-dessous (mean reversion)")
        elif dist_vwap > 100 and vwap_d_side == -1 and vwap_w_side == -1 and vwap_m_side == -1:
            div_quality += 1.5
            div_factors.append("Triple VWAP au-dessus (mean reversion)")

        # 6. RVOL qui baisse = le push se fait sans conviction
        rvol = get_field(bar, "rvol", 1.0)
        if rvol < 0.7:
            div_quality += 1.0
            div_factors.append(f"Volume faible ({rvol:.2f}x) = push sans conviction")

    # Seuils de qualite divergence
    # 0-2 = bruit, 3-5 = moderee, 6-8 = forte, 9+ = extreme
    div_grade = "NONE"
    if div_quality >= 6:
        div_grade = "EXTREME"
    elif div_quality >= 4:
        div_grade = "FORTE"
    elif div_quality >= 3:
        div_grade = "MODEREE"
    elif delta_div:
        div_grade = "FAIBLE"

    # Appliquer le score de divergence au bias — SEULEMENT hors tendance forte
    # Fix 09/04 : ne pas fade un breakout en trending. Trending detecte via
    # VWAP slope fort + delta_day dans le sens du move.
    trending_up = vwap_slope_10 > 5 and delta_day_dir > 0
    trending_dn = vwap_slope_10 < -5 and delta_day_dir < 0
    is_trending = trending_up or trending_dn

    if div_quality >= 5 and not is_trending:
        div_bias = 0.0
        if pos >= 70 and dist_vwap < -50:
            div_bias = -min(div_quality / 20.0, 0.35)
            factors.append({"icon": "bear", "text": f"DIV {div_grade}: prix overextended haut ({div_quality:.0f}/10)"})
        elif pos <= 30 and dist_vwap > 50:
            div_bias = min(div_quality / 20.0, 0.35)
            factors.append({"icon": "bull", "text": f"DIV {div_grade}: prix overextended bas ({div_quality:.0f}/10)"})
        score += div_bias
    elif div_quality >= 5 and is_trending:
        # Divergence forte mais on est en breakout — NE PAS fade
        factors.append({"icon": "neutral", "text": f"DIV {div_grade} ignoree — trending (slope={vwap_slope_10:+.1f})"})
    elif div_quality >= 3:
        factors.append({"icon": "neutral", "text": f"DIV {div_grade}: contexte insuffisant ({div_quality:.0f}/10)"})

    score = max(-1.0, min(1.0, score))  # borner le score

    if score > 0.25:
        bias, bias_label = "BULLISH", "HAUSSIER"
    elif score < -0.25:
        bias, bias_label = "BEARISH", "BAISSIER"
    else:
        bias, bias_label = "NEUTRAL", "NEUTRE"

    # Mode marche (TREND vs RANGE) — systeme de votes pro (10 criteres)
    trend_votes = 0
    range_votes = 0
    regime_details = []

    # 1. IB Breakout — le plus fiable (ignorer si IB pas encore formee)
    ib_up = get_int_field(bar, "ib_broken_up", 0)
    ib_dn = get_int_field(bar, "ib_broken_down", 0)
    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    if ib_up or ib_dn:
        trend_votes += 2
        regime_details.append("IB cassee " + ("UP" if ib_up else "DOWN"))
    elif ib_range > 0:
        range_votes += 1
        regime_details.append("IB intacte")
    # Si ib_range == 0, l'IB n'est pas encore formee — pas de vote

    # 2. Day Type (Market Profile)
    # FIX 22/04/2026 : mapping corrige vs readers.py DAY_TYPE_LABELS
    # Bug detecte : code 3=NEUTRAL, 2=NORM_VARIATION (42% des jours).
    # Auparavant 3 etait classe "Normal Variation" (faux) et 2 "Neutral" (faux).
    # DMP enum : 0=NonTrend, 1=Normal, 2=NormVariation, 3=Neutral, 4=Trend
    day_type = get_int_field(bar, "day_type", 0)
    if day_type == 4:  # Trend Day (19%)
        trend_votes += 2
        regime_details.append("Day Type: Trend")
    elif day_type == 2:  # Norm Variation (42%, ext 1 cote = directionnel)
        trend_votes += 1
        regime_details.append("Day Type: Norm Variation")
    elif day_type == 1:  # Normal (respect IB, range 2%)
        range_votes += 1
        regime_details.append("Day Type: Normal")
    elif day_type == 3:  # Neutral (ext 2 cotes + close milieu, 30% whipsaw)
        range_votes += 1
        regime_details.append("Day Type: Neutral")
    # day_type == 0 (NonTrend, 7%) : pas de vote, marche comprime

    # 3. Single Prints — empreinte de conviction
    single_prints = get_int_field(bar, "single_print_count", 0)
    if single_prints > 10:
        trend_votes += 1
        regime_details.append(f"Single prints: {single_prints} (fort)")
    elif single_prints < 3:
        range_votes += 1
        regime_details.append(f"Single prints: {single_prints} (faible)")

    # 4. VWAP Slope — pente du VWAP
    vwap_sl = abs(vwap_slope_10)
    if vwap_sl > 5:
        trend_votes += 1
        regime_details.append(f"VWAP slope: {vwap_slope_10:+.1f} (directionnel)")
    elif vwap_sl < 1:
        range_votes += 1
        regime_details.append(f"VWAP slope: {vwap_slope_10:+.1f} (plat)")

    # 5. Sess/ATR
    if atr_ratio > 1.2:
        trend_votes += 1
        regime_details.append(f"Sess/ATR: {atr_ratio:.2f}x (expansion)")
    elif atr_ratio < 0.6:
        range_votes += 1
        regime_details.append(f"Sess/ATR: {atr_ratio:.2f}x (compression)")

    # 6. Open Type — OD/OTD = trend, ORR = range
    open_type = get_int_field(bar, "open_type", 0)
    if open_type in (1, 2):  # OD up/down
        trend_votes += 1
        regime_details.append("Open Drive")
    elif open_type in (3, 4):  # OTD
        trend_votes += 1
        regime_details.append("Open Test Drive")
    elif open_type in (5, 6):  # ORR
        range_votes += 1
        regime_details.append("Open Rejection Reverse")

    # 7. Profile Shape — P-shape (1) et b-shape (2) = directionnel ; D-shape (0) et Double Dist (3) = range
    profile_shape = get_int_field(bar, "profile_shape", -1)
    if profile_shape in (1, 2):
        trend_votes += 1
        regime_details.append("Profile shape: directionnel (" + ("P" if profile_shape == 1 else "b") + "-Shape)")
    elif profile_shape in (0, 3):
        range_votes += 1
        regime_details.append("Profile shape: range (" + ("D-Shape" if profile_shape == 0 else "Double Dist") + ")")

    # 8. POC distance — POC qui migre = trend
    poc_dist = get_field(bar, "poc_bar_dist", 0.0)
    if poc_dist > 30:
        trend_votes += 1
        regime_details.append(f"POC distant: {poc_dist:.0f} barres (migration)")
    elif poc_dist < 5:
        range_votes += 1
        regime_details.append(f"POC proche: {poc_dist:.0f} barres (statique)")

    # 9. Bars in VA — prix dans la VA = range
    bars_va = get_field(bar, "bars_in_va", 0.0)
    if bars_va > 60:
        range_votes += 1
        regime_details.append(f"Bars in VA: {bars_va:.0f}% (confine)")
    elif bars_va < 30:
        trend_votes += 1
        regime_details.append(f"Bars in VA: {bars_va:.0f}% (hors VA)")

    # 10. Trend Day Probability
    tdp = get_field(bar, "trend_day_probability", 0.5)
    if tdp > 0.65:
        trend_votes += 1
        regime_details.append(f"Trend prob: {tdp:.0%}")
    elif tdp < 0.3:
        range_votes += 1
        regime_details.append(f"Trend prob: {tdp:.0%} (faible)")

    # Verdict — seuil a 4 votes pour conviction
    if trend_votes >= 5:
        mode = "TREND"
    elif range_votes >= 5:
        mode = "RANGE"
    elif trend_votes >= range_votes + 2:
        mode = "TREND"
    elif range_votes >= trend_votes + 2:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # Direction a favoriser
    if mode == "RANGE":
        if pos >= 70:
            favor = "SHORT"
        elif pos <= 30:
            favor = "LONG"
        else:
            favor = "NEUTRE"
    elif bias == "BULLISH":
        favor = "LONG"
    elif bias == "BEARISH":
        favor = "SHORT"
    else:
        favor = "NEUTRE"

    # Override coherence : evite LONG quand la structure est bearish
    bear_factors = sum(1 for f in factors if f.get("icon") == "bear")
    bull_factors = sum(1 for f in factors if f.get("icon") == "bull")
    if favor == "LONG" and bear_factors >= 3:
        favor = "NEUTRE"  # Range bas MAIS structure bearish = pas un rebond
    elif favor == "SHORT" and bull_factors >= 3:
        favor = "NEUTRE"  # Range haut MAIS structure bullish = pas un top

    # Volatilite regime
    if atr_ratio >= 2.0:
        vol_regime = "EXTREME"
    elif atr_ratio >= 1.2:
        vol_regime = "HIGH"
    elif atr_ratio >= 0.5:
        vol_regime = "NORMAL"
    else:
        vol_regime = "LOW"

    return {
        "vix": vix,
        "vix_regime": vix_regime,
        "vix_regime_label": VIX_REGIME_LABELS.get(vix_regime, "NORMAL"),
        "atr": round(atr, 1),
        "sess_range_ticks": get_field(bar, "sess_range_ticks", 0.0),
        "sess_range_atr": round(atr_ratio, 3),
        "vwap_slope_10": round(vwap_slope_10, 2),
        "vwap_slope_30": round(vwap_slope_30, 2),
        "vwap_slope_10_dir": get_int_field(bar, "vwap_slope_10_dir", 0),
        "vwap_d_side": vwap_d_side,
        "vwap_w_side": vwap_w_side,
        "vwap_m_side": vwap_m_side,
        "vwap_ma_align": get_int_field(bar, "vwap_ma_align", 0),
        "vwap_triple_align": triple_align,
        "momentum_3b": momentum_3,
        "momentum_5b": momentum_5,
        "ma_trend": ma_trend,
        "bias": bias,
        "bias_label": bias_label,
        "bias_score": round(score, 3),
        "bias_confidence": round(_calc_confidence(score, factors), 2),
        "bias_factors": factors,
        "mode": mode,
        "mode_trend_votes": trend_votes,
        "mode_range_votes": range_votes,
        "mode_details": regime_details,
        "favor": favor,
        "vol_regime": vol_regime,
        "range_pos": round(pos, 1),
        "_price": get_field(bar, "price", 0.0),
        # Divergence
        "div_active": bool(delta_div),
        "div_quality": round(div_quality, 1),
        "div_grade": div_grade,
        "div_factors": div_factors,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 3 : Session & Open
# ═══════════════════════════════════════════════════════════════


def build_session_open(bar: dict) -> dict:
    """Open type, overnight, gap, AMD phase."""
    if not bar:
        return {}

    open_type = get_int_field(bar, "open_type", 0)
    session_val = get_int_field(bar, "session", 0)

    return {
        "open_type": open_type,
        "open_type_label": OPEN_TYPE_LABELS.get(open_type, "UNKNOWN"),
        "open_direction": get_int_field(bar, "open_direction", 0),
        "open_zone": get_int_field(bar, "open_zone", 0),
        "open_gap_ticks": get_field(bar, "open_gap_ticks", 0.0),
        "open_in_prev_va": get_int_field(bar, "open_in_prev_va", 0),
        "open_position": get_int_field(bar, "open_position", 0),
        "open_bias_conf": get_field(bar, "open_bias_conf", 0.0),
        "session": session_val,
        "session_label": get_str_field(bar, "session_id", "Closed"),
        "session_id": get_str_field(bar, "session_id", "N/A"),
        "day_type": get_int_field(bar, "day_type", 0),
        "day_type_label": DAY_TYPE_LABELS.get(get_int_field(bar, "day_type", 0), "NEUTRAL"),
        "trend_day_prob": get_field(bar, "trend_day_probability", 0.0),
        "ovn_range_ticks": get_field(bar, "ovn_range_ticks", 0.0),
        "ovn_high_price": dist_to_price(bar, "dist_ovn_high"),
        "ovn_low_price": dist_to_price(bar, "dist_ovn_low"),
        "open_cash_price": dist_to_price(bar, "dist_open_cash"),
        "open_830_price": dist_to_price(bar, "dist_open_830"),
        "sess_high_price": dist_to_price(bar, "dist_sess_high"),
        "sess_low_price": dist_to_price(bar, "dist_sess_low"),
        "bool_session_early": get_int_field(bar, "bool_session_early", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 4 : Options & Gamma (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_options_levels(bar: dict) -> dict:
    """Murs options MQ + GEX en prix absolus."""
    if not bar:
        return {}

    price = get_field(bar, "price", 0.0)
    next_wall_dist = get_field(bar, "next_wall_dist_ticks", 0.0)
    next_wall_is_call = get_int_field(bar, "next_wall_is_call", 0)
    wall_sign = 1 if next_wall_is_call else -1
    next_wall_price = round(price + wall_sign * next_wall_dist * TICK_SIZE, 2) if price else None

    return {
        "call_wall_price": dist_to_price(bar, "dist_mq_call"),
        "put_wall_price": dist_to_price(bar, "dist_mq_put"),
        "hvl_price": dist_to_price(bar, "dist_mq_hvl"),
        "call_0dte_price": dist_to_price(bar, "dist_mq_call_0dte"),
        "put_0dte_price": dist_to_price(bar, "dist_mq_put_0dte"),
        "dist_mq_call": get_field(bar, "dist_mq_call", 0.0),
        "dist_mq_put": get_field(bar, "dist_mq_put", 0.0),
        "dist_mq_hvl": get_field(bar, "dist_mq_hvl", 0.0),
        "dist_mq_call_0dte": get_field(bar, "dist_mq_call_0dte", 0.0),
        "dist_mq_put_0dte": get_field(bar, "dist_mq_put_0dte", 0.0),
        "gex_up_price": dist_to_price(bar, "dist_gex_nearest_up"),
        "gex_dn_price": dist_to_price(bar, "dist_gex_nearest_dn"),
        "dist_gex_up": get_field(bar, "dist_gex_nearest_up", 0.0),
        "dist_gex_dn": get_field(bar, "dist_gex_nearest_dn", 0.0),
        "gex_cluster_count": get_int_field(bar, "gex_cluster_count", 0),
        "gex_flip_zone": get_int_field(bar, "bool_gex_flip_zone", 0),
        "next_wall_price": next_wall_price,
        "next_wall_dist": next_wall_dist,
        "next_wall_side": "CALL" if next_wall_is_call else "PUT",
        "bool_above_mq_hvl": get_int_field(bar, "bool_above_mq_hvl", 0),
        "bool_above_mq_call": get_int_field(bar, "bool_above_mq_call", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 5 : VIX Gamma (prix VIX absolus)
# ═══════════════════════════════════════════════════════════════


def build_vix_gamma(bar: dict) -> dict:
    """VIX options en prix absolus."""
    if not bar:
        return {}

    vix = get_field(bar, "vix_level", 0.0)
    return {
        "vix_level": vix,
        "vix_regime": get_int_field(bar, "vix_regime", 1),
        "vix_regime_label": VIX_REGIME_LABELS.get(get_int_field(bar, "vix_regime", 1), "NORMAL"),
        "vix_call_price": vix_dist_to_price(bar, "dist_vix_call"),
        "vix_put_price": vix_dist_to_price(bar, "dist_vix_put"),
        "vix_hvl_price": vix_dist_to_price(bar, "dist_vix_hvl"),
        "vix_call_0dte_price": vix_dist_to_price(bar, "dist_vix_call_0dte"),
        "vix_put_0dte_price": vix_dist_to_price(bar, "dist_vix_put_0dte"),
        "vix_hvl_0dte_price": vix_dist_to_price(bar, "dist_vix_hvl_0dte"),
        "vix_gex_up_price": vix_dist_to_price(bar, "dist_vix_gex_nearest_up"),
        "vix_gex_dn_price": vix_dist_to_price(bar, "dist_vix_gex_nearest_dn"),
        "vix_above_hvl": get_int_field(bar, "vix_above_hvl", 0),
        "vix_above_hvl_0dte": get_int_field(bar, "vix_above_hvl_0dte", 0),
        "dist_vix_call": get_field(bar, "dist_vix_call", 0.0),
        "dist_vix_put": get_field(bar, "dist_vix_put", 0.0),
        "dist_vix_hvl": get_field(bar, "dist_vix_hvl", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 6 : Order Flow V2 (30 champs)
# ═══════════════════════════════════════════════════════════════


def build_order_flow(bar: dict) -> dict:
    """Delta, CVD, RVOL, volume, pression, diagnostics."""
    if not bar:
        return {}

    rvol = get_field(bar, "rvol", 0.0)
    rvol_regime = rvol_to_regime(rvol)
    delta_pct = get_field(bar, "delta_pct", 0.0)

    # Climax : volume > 3x ET delta extreme
    climax = 0
    if rvol >= 3.0 and abs(delta_pct) > 0.6:
        climax = 1 if delta_pct > 0 else -1

    return {
        "delta_bar": get_field(bar, "delta_bar", 0.0),
        "delta_pct": round(delta_pct, 4),
        "delta_bar_vol_norm": get_field(bar, "delta_bar_vol_norm", 0.0),
        "delta_day": get_field(bar, "delta_day", 0.0),
        "delta_day_dir": get_int_field(bar, "delta_day_dir", 0),
        "delta_divergence": get_int_field(bar, "delta_divergence", 0),
        "cvd_day": get_field(bar, "cvd_day", 0.0),
        "cvd_day_dir": get_int_field(bar, "cvd_day_dir", 0),
        "cvd_bar_delta": get_field(bar, "cvd_bar_delta", 0.0),
        "cvd_ohlc_range": get_field(bar, "cvd_ohlc_range", 0.0),
        "rvol": round(rvol, 4),
        "rvol_zscore": round(get_field(bar, "rvol_zscore", 0.0), 4),
        "rvol_regime": rvol_regime,
        "rvol_regime_label": RVOL_REGIME_LABELS.get(rvol_regime, "Normal"),
        "rvol_buy": get_int_field(bar, "rvol_buy", 0),
        "rvol_sell": get_int_field(bar, "rvol_sell", 0),
        "rvol_absorb_buy": get_field(bar, "rvol_absorb_buy", 0.0),
        "rvol_absorb_sell": get_field(bar, "rvol_absorb_sell", 0.0),
        "total_vol": get_field(bar, "total_vol", 0.0),
        "buy_vol": get_field(bar, "buy_vol", 0.0),
        "sell_vol": get_field(bar, "sell_vol", 0.0),
        "buy_sell_ratio": round(get_field(bar, "buy_sell_ratio", 0.5), 4),
        "vol_per_sec": round(get_field(bar, "vol_per_sec", 0.0), 2),
        "volume_imbalance": round(get_field(bar, "volume_imbalance", 0.0), 4),
        "ask_pct": round(get_field(bar, "ask_pct", 0.5), 4),
        "bid_pct": round(get_field(bar, "bid_pct", 0.5), 4),
        "ask_bid_imbalance": round(get_field(bar, "ask_bid_imbalance", 0.0), 4),
        "large_trader_ratio": round(get_field(bar, "large_trader_ratio", 0.0), 4),
        "finish_strength": get_field(bar, "finish_strength", 0.0),
        "climax_signal": climax,
        "diag_imbalance": round(get_field(bar, "diag_imbalance", 0.0), 4),
        "diag_pos_delta": get_field(bar, "diag_pos_delta", 0.0),
        "diag_neg_delta": get_field(bar, "diag_neg_delta", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 7 : Battle Navale
# ═══════════════════════════════════════════════════════════════


def build_battle_navale(bar: dict) -> dict:
    """BN score + 12 composants + edges."""
    if not bar:
        return {}

    # Features GARDER uniquement (DROP list du CLAUDE.md retiree)
    return {
        "bn_score_raw": get_field(bar, "bn_score_raw", 0.0),
        "bn_score_bear": get_field(bar, "bn_score_bear", 0.0),
        "bn_color_up_2": get_int_field(bar, "bn_color_up_2", 0),
        "bn_color_dn_2": get_int_field(bar, "bn_color_dn_2", 0),
        "bn_absorb_ask": get_int_field(bar, "bn_absorb_ask", 0),
        "bn_absorb_bid": get_int_field(bar, "bn_absorb_bid", 0),
        "bn_pressure_bid": get_field(bar, "bn_pressure_bid", 0.0),
        "bar_edge_buy": get_int_field(bar, "bar_edge_buy", 0),
        "bar_edge_sell": get_int_field(bar, "bar_edge_sell", 0),
        "fp_edge_buy": get_int_field(bar, "fp_edge_buy", 0),
        "fp_edge_sell": get_int_field(bar, "fp_edge_sell", 0),
        "bar_pressure_bid": get_int_field(bar, "bar_pressure_bid", 0),
        "avg_trade_size": round(get_field(bar, "avg_trade_size", 0.0), 2),
        "avg_ask_size": round(get_field(bar, "avg_ask_size", 0.0), 2),
        "avg_bid_size": round(get_field(bar, "avg_bid_size", 0.0), 2),
        "finish_delta_pct": get_field(bar, "finish_delta_pct", 0.0),
        "high_pullback_delta": get_field(bar, "high_pullback_delta", 0.0),
        "low_pullback_delta": get_field(bar, "low_pullback_delta", 0.0),
        "rotation_up": get_field(bar, "rotation_up", 0.0),
        "rotation_dn": get_field(bar, "rotation_dn", 0.0),
        "rotation_zz_osc": get_field(bar, "rotation_zz_osc", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 8 : Market Profile (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_market_profile(bar: dict) -> dict:
    """VPOC, VA, composites, HVN/LVN, profil shape — tout en prix."""
    if not bar:
        return {}

    profile_shape = get_int_field(bar, "profile_shape", 0)
    day_type = get_int_field(bar, "day_type", 0)
    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    sess_range = get_field(bar, "sess_range_ticks", 0.0)
    ib_ext = round((sess_range - ib_range) / ib_range, 3) if ib_range > 0 else 0.0

    return {
        "profile_shape": profile_shape,
        "profile_shape_label": PROFILE_SHAPE_LABELS.get(profile_shape, "D-Shape"),
        "profile_skew": round(get_field(bar, "profile_skew", 0.0), 4),
        "profile_hvn_dominant": get_field(bar, "profile_hvn_dominant", 0.0),
        "is_double_dist": get_int_field(bar, "is_double_dist", 0),
        "day_type": day_type,
        "day_type_label": DAY_TYPE_LABELS.get(day_type, "NEUTRAL"),
        "poc_position": get_field(bar, "poc_position", 0.0),
        "poc_bar_dist": get_field(bar, "poc_bar_dist", 0.0),
        "poc_separation_ticks": get_field(bar, "poc_separation_ticks", 0.0),
        # VPOC en prix
        "cur_vpoc_price": dist_to_price(bar, "dist_cur_vpoc"),
        "cur_vah_price": dist_to_price(bar, "dist_cur_vah"),
        "cur_val_price": dist_to_price(bar, "dist_cur_val"),
        "cur_vwap_vp_price": dist_to_price(bar, "dist_cur_vwap_vp"),
        "inside_cur_va": get_int_field(bar, "inside_cur_va", 0),
        # FIX 2026-04-16 : va_position_pct est null hors VA (pas 0.5 default).
        # Sinon le dashboard affichait "VA Position 50%" en meme temps que
        # "Dans VA : non" -> contradiction visuelle. Le JS fmtPct(null) -> "--".
        "va_position_pct": _nullable_round(get_nullable_field(bar, "va_position_pct"), 4),
        "bars_in_va": get_field(bar, "bars_in_va", 0.0),
        "vah_touches_20b": get_field(bar, "vah_touches_20b", 0.0),
        "val_touches_20b": get_field(bar, "val_touches_20b", 0.0),
        # Previous day
        "prev_vpoc_price": dist_to_price(bar, "dist_prev_vpoc"),
        "prev_vah_price": dist_to_price(bar, "dist_prev_vah"),
        "prev_val_price": dist_to_price(bar, "dist_prev_val"),
        "prev_vwap_price": dist_to_price(bar, "dist_prev_vwap"),
        "inside_prev_va": get_int_field(bar, "inside_prev_va", 0),
        # Composites
        "comp_20d_vpoc_price": dist_to_price(bar, "dist_comp_20d_vpoc"),
        "comp_20d_vah_price": dist_to_price(bar, "dist_comp_20d_vah"),
        "comp_20d_val_price": dist_to_price(bar, "dist_comp_20d_val"),
        "comp_50d_vpoc_price": dist_to_price(bar, "dist_comp_50d_vpoc"),
        "comp_50d_vah_price": dist_to_price(bar, "dist_comp_50d_vah"),
        "comp_50d_val_price": dist_to_price(bar, "dist_comp_50d_val"),
        "comp_vpoc_align_20_50": get_int_field(bar, "comp_vpoc_align_20_50", 0),
        "comp_vpoc_align_day_20": get_int_field(bar, "comp_vpoc_align_day_20", 0),
        # HVN / LVN
        "session_hvn_above_price": dist_to_price(bar, "dist_session_hvn_above"),
        "session_hvn_below_price": dist_to_price(bar, "dist_session_hvn_below"),
        "session_lvn_above_price": dist_to_price(bar, "dist_session_lvn_above"),
        "session_lvn_below_price": dist_to_price(bar, "dist_session_lvn_below"),
        "session_hvn_count": get_int_field(bar, "session_hvn_count", 0),
        "session_lvn_count": get_int_field(bar, "session_lvn_count", 0),
        "hvn_between": get_int_field(bar, "hvn_between", 0),
        "lvn_between": get_int_field(bar, "lvn_between", 0),
        "lvn_confluence_count": get_int_field(bar, "lvn_confluence_count", 0),
        # Single prints
        "single_print_count": get_int_field(bar, "single_print_count", 0),
        "single_print_mid": get_field(bar, "single_print_mid", 0.0),
        # Rule 80%
        "rule_80pct": get_int_field(bar, "rule_80pct", 0),
        # IB extension ratio
        "ib_extension_ratio": ib_ext,
        "bool_va_confluence": get_int_field(bar, "bool_va_confluence", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 9 : Initial Balance
# ═══════════════════════════════════════════════════════════════


def build_initial_balance(bar: dict) -> dict:
    """IB complet en prix absolus."""
    if not bar:
        return {}

    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    sess_range = get_field(bar, "sess_range_ticks", 0.0)
    ib_ext = round((sess_range - ib_range) / ib_range, 3) if ib_range > 0 else 0.0

    # Fix C1-data : masque le bug C++ ou ib_complete=1 en Asia/London
    # IB valide seulement si ib_range_ticks > 0 ET session US
    ib_complete_raw = get_int_field(bar, "ib_complete", 0)
    session_id = bar.get("session_id", "")
    ib_complete_fixed = 1 if (ib_complete_raw == 1 and ib_range > 0 and session_id == "US") else 0

    return {
        "ib_high_price": dist_to_price(bar, "dist_ib_high"),
        "ib_low_price": dist_to_price(bar, "dist_ib_low"),
        "ib_range_ticks": ib_range,
        "ib_range_atr": get_field(bar, "ib_range_atr", 0.0),
        "ib_complete": ib_complete_fixed,
        "ib_broken_up": get_int_field(bar, "ib_broken_up", 0),
        "ib_broken_down": get_int_field(bar, "ib_broken_down", 0),
        "ib_is_narrow": get_int_field(bar, "ib_is_narrow", 0),
        "ib_is_wide": get_int_field(bar, "ib_is_wide", 0),
        # FIX 2026-04-16 : ib_position_pct est null hors IB/RTH (pas 0.0 default).
        # Sinon le dashboard affichait "ib_position 0%" en pre-IB (09:30-10:30 ET)
        # et hors RTH, suggerant "au plus bas de l'IB" (trompeur).
        "ib_position_pct": get_nullable_field(bar, "ib_position_pct"),
        "bool_ib_inside": get_int_field(bar, "bool_ib_inside", 0),
        "ib_extension_ratio": ib_ext,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 10 : Niveaux & Distances (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_levels_distances(bar: dict) -> dict:
    """Tous les niveaux de S/R en prix absolus."""
    if not bar:
        return {}

    return {
        # Swing
        "swing_high_price": dist_to_price(bar, "dist_swing_high"),
        "swing_low_price": dist_to_price(bar, "dist_swing_low"),
        "swing_range_ticks": get_field(bar, "swing_range_ticks", 0.0),
        "price_vs_swing_mid": get_field(bar, "price_vs_swing_mid", 0.0),
        "new_swing_high": get_int_field(bar, "new_swing_high", 0),
        "new_swing_low": get_int_field(bar, "new_swing_low", 0),
        # Session
        "sess_high_price": dist_to_price(bar, "dist_sess_high"),
        "sess_low_price": dist_to_price(bar, "dist_sess_low"),
        "sess_range_ticks": get_field(bar, "sess_range_ticks", 0.0),
        "range_pos": get_field(bar, "range_pos", 50.0),
        "range_size_ticks": get_field(bar, "range_size_ticks", 0.0),
        # VWAP Daily + SD bands
        "vwap_d_price": dist_to_price(bar, "dist_vwap_d"),
        "vwap_d_sd1u_price": dist_to_price(bar, "dist_vwap_d_sd1u"),
        "vwap_d_sd1d_price": dist_to_price(bar, "dist_vwap_d_sd1d"),
        "vwap_d_sd2u_price": dist_to_price(bar, "dist_vwap_d_sd2u"),
        "vwap_d_sd2d_price": dist_to_price(bar, "dist_vwap_d_sd2d"),
        "vwap_d_sd3u_price": dist_to_price(bar, "dist_vwap_d_sd3u"),
        "vwap_d_sd3d_price": dist_to_price(bar, "dist_vwap_d_sd3d"),
        "dist_vwap_d_atr": get_field(bar, "dist_vwap_d_atr", 0.0),
        "bool_above_vwap_d": get_int_field(bar, "bool_above_vwap_d", 0),
        # VWAP Weekly/Monthly
        "vwap_w_price": dist_to_price(bar, "dist_vwap_w"),
        "dist_vwap_w_atr": get_field(bar, "dist_vwap_w_atr", 0.0),
        "bool_above_vwap_w": get_int_field(bar, "bool_above_vwap_w", 0),
        "vwap_m_price": dist_to_price(bar, "dist_vwap_m"),
        "dist_vwap_m_atr": get_field(bar, "dist_vwap_m_atr", 0.0),
        "bool_above_vwap_m": get_int_field(bar, "bool_above_vwap_m", 0),
        # Overnight
        "ovn_high_price": dist_to_price(bar, "dist_ovn_high"),
        "ovn_low_price": dist_to_price(bar, "dist_ovn_low"),
        "ovn_range_ticks": get_field(bar, "ovn_range_ticks", 0.0),
        "open_cash_price": dist_to_price(bar, "dist_open_cash"),
        "open_830_price": dist_to_price(bar, "dist_open_830"),
        # Retest
        "retest_high_count": get_int_field(bar, "retest_high_count", 0),
        "retest_low_count": get_int_field(bar, "retest_low_count", 0),
        "retest_high_delta_div": get_int_field(bar, "retest_high_delta_div", 0),
        "retest_low_delta_div": get_int_field(bar, "retest_low_delta_div", 0),
        "bars_since_retest_high": bar.get("bars_since_retest_high"),
        "bars_since_retest_low": bar.get("bars_since_retest_low"),
        # Range 1D
        "day_max_price": dist_to_price(bar, "dist_1d_max_ticks"),
        "day_min_price": dist_to_price(bar, "dist_1d_min_ticks"),
        # Extreme zones
        "ext_color_up_price": dist_to_price(bar, "dist_ext_color_up"),
        "ext_color_dn_price": dist_to_price(bar, "dist_ext_color_dn"),
        "ext_long_up_price": dist_to_price(bar, "dist_ext_long_up"),
        "ext_long_dn_price": dist_to_price(bar, "dist_ext_long_dn"),
        "ext_edge_buy_price": dist_to_price(bar, "dist_ext_edge_buy"),
        "ext_edge_sell_price": dist_to_price(bar, "dist_ext_edge_sell"),
        # Blind spots
        "blind_up_price": dist_to_price(bar, "dist_blind_nearest_up"),
        "blind_dn_price": dist_to_price(bar, "dist_blind_nearest_dn"),
        # Booleans position
        "bool_above_cur_vpoc": get_int_field(bar, "bool_above_cur_vpoc", 0),
        "bool_above_prev_vpoc": get_int_field(bar, "bool_above_prev_vpoc", 0),
        "bool_near_level": get_int_field(bar, "bool_near_level", 0),
        # Previous day VWAP bands
        "prev_vwap_sd1u_price": dist_to_price(bar, "dist_prev_vwap_sd1u"),
        "prev_vwap_sd1d_price": dist_to_price(bar, "dist_prev_vwap_sd1d"),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 11 : Big Orders
# ═══════════════════════════════════════════════════════════════


def build_big_orders(bar: dict) -> dict:
    """Big orders institutionnels par tier + clusters."""
    if not bar:
        return {}

    return {
        # Counts par tier
        "n_big_ask_t1": get_field(bar, "n_big_ask_t1", 0.0),
        "n_big_bid_t1": get_field(bar, "n_big_bid_t1", 0.0),
        "n_big_ask_t2": get_field(bar, "n_big_ask_t2", 0.0),
        "n_big_bid_t2": get_field(bar, "n_big_bid_t2", 0.0),
        "n_big_ask_t3": get_field(bar, "n_big_ask_t3", 0.0),
        "n_big_bid_t3": get_field(bar, "n_big_bid_t3", 0.0),
        "n_big_ask_t4": get_field(bar, "n_big_ask_t4", 0.0),
        "n_big_bid_t4": get_field(bar, "n_big_bid_t4", 0.0),
        # Clusters
        "big_ask_cluster_20t": get_field(bar, "big_ask_cluster_20t", 0.0),
        "big_bid_cluster_20t": get_field(bar, "big_bid_cluster_20t", 0.0),
        "big_ask_cluster_50t": get_field(bar, "big_ask_cluster_50t", 0.0),
        "big_bid_cluster_50t": get_field(bar, "big_bid_cluster_50t", 0.0),
        # Clusters par tier (20t)
        "big_ask_cluster_20t_t1": get_field(bar, "big_ask_cluster_20t_t1", 0.0),
        "big_bid_cluster_20t_t1": get_field(bar, "big_bid_cluster_20t_t1", 0.0),
        "big_ask_cluster_20t_t2": get_field(bar, "big_ask_cluster_20t_t2", 0.0),
        "big_bid_cluster_20t_t2": get_field(bar, "big_bid_cluster_20t_t2", 0.0),
        "big_ask_cluster_20t_t3": get_field(bar, "big_ask_cluster_20t_t3", 0.0),
        "big_bid_cluster_20t_t3": get_field(bar, "big_bid_cluster_20t_t3", 0.0),
        "big_ask_cluster_20t_t4": get_field(bar, "big_ask_cluster_20t_t4", 0.0),
        "big_bid_cluster_20t_t4": get_field(bar, "big_bid_cluster_20t_t4", 0.0),
        # Nearest big orders en prix
        "big_ask_up_price": dist_to_price(bar, "dist_big_ask_nearest_up"),
        "big_ask_dn_price": dist_to_price(bar, "dist_big_ask_nearest_dn"),
        "big_bid_up_price": dist_to_price(bar, "dist_big_bid_nearest_up"),
        "big_bid_dn_price": dist_to_price(bar, "dist_big_bid_nearest_dn"),
        # Volume details
        "high_ask_vol_pct": get_field(bar, "high_ask_vol_pct", 0.0),
        "low_bid_vol_pct": get_field(bar, "low_bid_vol_pct", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 12 : Intermarket ES/NQ
# ═══════════════════════════════════════════════════════════════


def build_intermarket(bar_es: dict, bar_nq: dict) -> dict:
    """Comparaison ES vs NQ."""
    if not bar_es and not bar_nq:
        return {}

    es_dir = get_int_field(bar_es, "delta_day_dir", 0) if bar_es else 0
    nq_dir = get_int_field(bar_nq, "delta_day_dir", 0) if bar_nq else 0
    cross_delta = 1 if (es_dir == nq_dir and es_dir != 0) else 0

    es_new_h = get_int_field(bar_es, "new_swing_high", 0) if bar_es else 0
    nq_new_h = get_int_field(bar_nq, "new_swing_high", 0) if bar_nq else 0
    es_new_l = get_int_field(bar_es, "new_swing_low", 0) if bar_es else 0
    nq_new_l = get_int_field(bar_nq, "new_swing_low", 0) if bar_nq else 0
    smt = 1 if (es_new_h != nq_new_h or es_new_l != nq_new_l) else 0

    # SMT enrichi : direction de la divergence
    smt_direction = "NONE"
    smt_detail = ""
    if es_new_h and not nq_new_h:
        smt_direction = "BEARISH"
        smt_detail = "ES fait un nouveau high, NQ ne confirme PAS — faiblesse NQ"
    elif nq_new_h and not es_new_h:
        smt_direction = "BEARISH"
        smt_detail = "NQ fait un nouveau high, ES ne confirme PAS — faiblesse ES"
    elif es_new_l and not nq_new_l:
        smt_direction = "BULLISH"
        smt_detail = "ES fait un nouveau low, NQ ne confirme PAS — force NQ"
    elif nq_new_l and not es_new_l:
        smt_direction = "BULLISH"
        smt_detail = "NQ fait un nouveau low, ES ne confirme PAS — force ES"

    # Divergence de momentum : ES et NQ en directions opposees
    es_range_pos = get_field(bar_es, "range_pos", 50.0) if bar_es else 50.0
    nq_range_pos = get_field(bar_nq, "range_pos", 50.0) if bar_nq else 50.0
    range_pos_gap = abs(es_range_pos - nq_range_pos)
    momentum_div = range_pos_gap > 30  # gap significatif entre ES et NQ

    es_rvol = get_field(bar_es, "rvol", 0.0) if bar_es else 0.0
    nq_rvol = get_field(bar_nq, "rvol", 0.0) if bar_nq else 0.0
    if es_rvol > nq_rvol * 1.2:
        vol_lead = "ES"
    elif nq_rvol > es_rvol * 1.2:
        vol_lead = "NQ"
    else:
        vol_lead = "EQUAL"

    es_ltr = get_field(bar_es, "large_trader_ratio", 0.0) if bar_es else 0.0
    nq_ltr = get_field(bar_nq, "large_trader_ratio", 0.0) if bar_nq else 0.0

    es_price = get_field(bar_es, "price", 0.0) if bar_es else 0.0
    nq_price = get_field(bar_nq, "price", 0.0) if bar_nq else 0.0
    ratio = round(es_price / nq_price, 6) if nq_price > 0 else 0.0

    es_mid = get_field(bar_es, "price_vs_swing_mid", 0.0) if bar_es else 0.0
    nq_mid = get_field(bar_nq, "price_vs_swing_mid", 0.0) if bar_nq else 0.0

    # Correlation multi-facteurs : swing_mid + delta_dir + range_pos
    es_rpos = get_field(bar_es, "range_pos", 50.0) if bar_es else 50.0
    nq_rpos = get_field(bar_nq, "range_pos", 50.0) if bar_nq else 50.0
    # Normaliser range_pos de 0-100 vers -1..+1
    es_rn = (es_rpos - 50) / 50
    nq_rn = (nq_rpos - 50) / 50
    # Score concordance sur 3 facteurs
    mid_agree = 1.0 if es_mid * nq_mid > 0 else (-1.0 if es_mid * nq_mid < 0 else 0.0)
    dir_agree = 1.0 if es_dir == nq_dir and es_dir != 0 else (-1.0 if es_dir != 0 and nq_dir != 0 and es_dir != nq_dir else 0.0)
    rpos_agree = es_rn * nq_rn  # produit : meme cote = positif
    corr = round(0.4 * mid_agree + 0.3 * dir_agree + 0.3 * min(1.0, max(-1.0, rpos_agree * 2)), 3)
    corr = round(corr, 3)

    return {
        "cross_delta_agreement": cross_delta,
        "smt_divergence": smt,
        "smt_direction": smt_direction,
        "smt_detail": smt_detail,
        "momentum_divergence": momentum_div,
        "range_pos_gap": round(range_pos_gap, 1),
        "rolling_correlation": corr,
        "price_ratio": ratio,
        "volume_lead": vol_lead,
        "ltr_diff": round(es_ltr - nq_ltr, 4),
        "es_rvol": round(es_rvol, 4),
        "nq_rvol": round(nq_rvol, 4),
        "es_delta_dir": es_dir,
        "nq_delta_dir": nq_dir,
        "es_range_pos": round(es_range_pos, 1),
        "nq_range_pos": round(nq_range_pos, 1),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 13 : Advisory / Conseils educatifs
# ═══════════════════════════════════════════════════════════════


def build_advisory(regime: dict, session_open: dict) -> dict:
    """Genere les conseils educatifs : QUI A LA MAIN, FAVORISER, conseils."""
    if not regime:
        return {"conseils": [], "favor": "NEUTRE", "qui_a_la_main": "PERSONNE"}

    bias = regime.get("bias", "NEUTRAL")
    mode = regime.get("mode", "NORMAL")
    favor = regime.get("favor", "NEUTRE")
    vol = regime.get("vol_regime", "NORMAL")
    score = regime.get("bias_score", 0.0)

    # Qui a la main
    if abs(score) > 0.5:
        qui = "ACHETEURS" if score > 0 else "VENDEURS"
        force = "FORTE"
    elif abs(score) > 0.25:
        qui = "ACHETEURS" if score > 0 else "VENDEURS"
        force = "MODEREE"
    else:
        qui = "PERSONNE"
        force = "EQUILIBRE"

    conseils = []

    # Session
    session_label = session_open.get("session_label", "Closed") if session_open else "N/A"
    if session_label == "US":
        conseils.append({
            "type": "ok",
            "text": f"Session US active — Meilleure liquidite, ideal pour trader",
        })
    elif session_label in ("Asia", "London"):
        conseils.append({
            "type": "warn",
            "text": f"Session {session_label} — Liquidite reduite, spreads plus larges",
        })
    else:
        conseils.append({
            "type": "danger",
            "text": "Hors session — NE PAS TRADER",
        })

    # Volatilite
    if vol == "EXTREME":
        conseils.append({
            "type": "danger",
            "text": "VOLATILITE EXTREME — Reduire la taille, elargir les stops",
        })
    elif vol == "HIGH":
        conseils.append({
            "type": "warn",
            "text": "Volatilite elevee — Prudence, stops elargis recommandes",
        })
    elif vol == "LOW":
        conseils.append({
            "type": "info",
            "text": "Volatilite basse — Targets reduits, patience requise",
        })

    # Mode
    if mode == "TREND":
        conseils.append({
            "type": "ok",
            "text": f"Mode TREND — Suivre la direction ({favor}), pas de fade",
        })
    elif mode == "RANGE":
        conseils.append({
            "type": "info",
            "text": "Mode RANGE — Fader les extremes, eviter le milieu du range",
        })
    else:
        conseils.append({
            "type": "info",
            "text": "Mode NORMAL — Chercher des confluences de niveaux",
        })

    # Divergence override — une div FORTE/EXTREME au bord du range
    # prime sur le bias classique (Mark Douglas : le casino joue son edge)
    # MAIS ne pas fade un breakout en mode TREND
    div_active = regime.get("div_active", False)
    div_grade = regime.get("div_grade", "NONE")
    div_quality = regime.get("div_quality", 0)
    range_pos = regime.get("range_pos", 50)
    reg_mode = regime.get("mode", "NORMAL")

    # En mode TREND, pas de divergence contrarian
    if div_grade in ("EXTREME", "FORTE") and (range_pos >= 80 or range_pos <= 20) and reg_mode != "TREND":
        if range_pos >= 80:
            favor = "SHORT"
            regime["favor"] = "SHORT"  # Propager au regime pour coherence
            conseils.append({
                "type": "danger",
                "text": f"DIVERGENCE {div_grade} ({div_quality:.0f}/10) — Prix au TOP du range "
                        f"({range_pos:.0f}%), le flow ne confirme PAS la montee. FAVORISER SHORT.",
            })
        else:
            favor = "LONG"
            regime["favor"] = "LONG"  # Propager au regime pour coherence
            conseils.append({
                "type": "danger",
                "text": f"DIVERGENCE {div_grade} ({div_quality:.0f}/10) — Prix au BOTTOM du range "
                        f"({range_pos:.0f}%), le flow ne confirme PAS la baisse. FAVORISER LONG.",
            })
    elif div_active and div_grade == "MODEREE":
        conseils.append({
            "type": "warn",
            "text": f"Divergence detectee ({div_quality:.0f}/10) mais contexte insuffisant — "
                    "NE PAS trader sur ce signal seul",
        })
    elif div_active and div_grade == "FAIBLE":
        conseils.append({
            "type": "info",
            "text": "Divergence faible detectee — surveiller si le contexte se renforce",
        })

    # Direction (apres override eventuel par la div)
    if favor == "LONG":
        conseils.append({
            "type": "ok",
            "text": "FAVORISER ACHAT — Le biais est haussier, chercher des longs sur support",
        })
    elif favor == "SHORT":
        conseils.append({
            "type": "ok",
            "text": "FAVORISER VENTE — Le biais est baissier, chercher des shorts sur resistance",
        })
    else:
        conseils.append({
            "type": "warn",
            "text": "PAS DE DIRECTION CLAIRE — Attendre un signal ou une cassure",
        })

    # Open type
    if session_open:
        ot = session_open.get("open_type_label", "")
        if "OD" in ot:
            conseils.append({
                "type": "info",
                "text": f"Open Drive ({ot}) — Forte conviction directionnelle a l'open",
            })
        elif "OTD" in ot:
            conseils.append({
                "type": "info",
                "text": f"Open Test Drive ({ot}) — Test d'un niveau puis continuation",
            })

    return {
        "qui_a_la_main": qui,
        "force": force,
        "favor": favor,
        "bias": bias,
        "mode": mode,
        "vol_regime": vol,
        "conseils": conseils,
    }


# ═══════════════════════════════════════════════════════════════
# Gamma Gate — positionnement options (MenthorQ walls + GEX)
# ═══════════════════════════════════════════════════════════════
#
# Regle Jackson (mentor) : "Mieux vaut avoir moins de recommandations a
# trader que de trader contre le flux institutionnel."
#
# Architecture : cap absolu au lieu de penalite graduee.
#   - Si le prix est proche d'un call wall MQ (seuil adaptatif ATR),
#     bull_pts est cape a 3 → impossible d'atteindre "ACHAT" (besoin 4+).
#   - Idem symetrique pour put support.
#   - GEX flip zone = regime change dealer → cap les deux cotes.
#
# Propriete mathematique garantie : jamais de reco ACHAT/VENTE en presence
# d'un mur proche, quel que soit le score des 6 autres signaux.
#
# Reference : audit dashboard 2026-04-13 (agent Explore) + review plan
# gamma gate 2026-04-13 (code-reviewer).


# Gamma gate — constantes (AT modifiable via PR si recalibration necessaire)
_GAMMA_THRESHOLD_MIN_TICKS: float = 10.0   # plancher seuil (evite desactiver sur ATR bas)
_GAMMA_THRESHOLD_MAX_TICKS: float = 80.0   # plafond seuil (evite derive sur ATR extreme)
_GAMMA_THRESHOLD_ATR_RATIO: float = 0.5    # seuil = 0.5 × ATR (demi range de barre typique)
_GAMMA_CAP_BULL_BEAR: int = 3              # cap applique sur bull_pts / bear_pts si mur proche
_GAMMA_DEFAULT_ATR: float = 30.0           # fallback ATR si absent de la barre


def _gamma_gate_check(
    bar: dict,
    options: Optional[dict],
) -> Tuple[bool, bool, List[str]]:
    """Check gamma gate : renvoie (block_long, block_short, warnings).

    Logique :
      - block_long  = True si le prix est proche d'un call wall MQ
        ou dans une zone GEX flip. Signal : ne pas recommander LONG.
      - block_short = True idem pour put support.
      - warnings = liste de strings explicatifs a afficher au user.

    Gestion de la sentinelle 0.0 ambigue (DMP retourne 0.0 quand mur
    absent OU quand prix pile sur le mur) :
      - On considere `0 < dist < threshold` comme "mur proche mais pas dessus"
      - On considere `dist == 0` avec un prix absolu pour le mur
        (`call_wall_price` / `put_wall_price`) non null comme "pile dessus"
        → block = True (cas le plus critique, ne JAMAIS passer a cote).

    Args:
        bar     : barre JSONL courante (pour lire ATR)
        options : dict retourne par build_options_levels() — peut etre None.
                  Si None → aucun blocage (rétro-compat).

    Returns:
        (block_long, block_short, warnings)
    """
    if not options:
        return False, False, []

    # Seuil adaptatif proportionnel a l'ATR, borne [10, 80]
    atr = get_field(bar, "atr", _GAMMA_DEFAULT_ATR) or _GAMMA_DEFAULT_ATR
    threshold = max(
        _GAMMA_THRESHOLD_MIN_TICKS,
        min(_GAMMA_THRESHOLD_MAX_TICKS, atr * _GAMMA_THRESHOLD_ATR_RATIO),
    )

    block_long = False
    block_short = False
    warnings: List[str] = []

    call_dist = options.get("dist_mq_call", 0.0) or 0.0
    put_dist = options.get("dist_mq_put", 0.0) or 0.0
    call_wall_price = options.get("call_wall_price")
    put_wall_price = options.get("put_wall_price")
    gex_flip = options.get("gex_flip_zone", 0)

    # Call wall : proche (dist > 0) OU pile dessus (dist == 0 + prix absolu present)
    call_near = 0 < call_dist <= threshold
    call_on = call_dist == 0.0 and call_wall_price is not None
    if call_near or call_on:
        block_long = True
        if call_on:
            warnings.append("GAMMA: prix PILE sur CALL WALL MQ")
        else:
            warnings.append(f"GAMMA: CALL WALL a {call_dist:.0f}t (seuil {threshold:.0f}t)")

    # Put support : idem symetrique
    put_near = 0 < put_dist <= threshold
    put_on = put_dist == 0.0 and put_wall_price is not None
    if put_near or put_on:
        block_short = True
        if put_on:
            warnings.append("GAMMA: prix PILE sur PUT SUPPORT MQ")
        else:
            warnings.append(f"GAMMA: PUT SUPPORT a {put_dist:.0f}t (seuil {threshold:.0f}t)")

    # GEX flip zone = regime dealer instable, bloque les deux cotes
    if gex_flip:
        block_long = True
        block_short = True
        warnings.append("GAMMA: GEX FLIP ZONE — regime dealer instable")

    return block_long, block_short, warnings


# ═══════════════════════════════════════════════════════════════
# Builder : Conseil Global (meme logique que le JS renderGlobalAdvice)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# Signal State Tracker — fix bug critique signal persistance (22/04)
# ═══════════════════════════════════════════════════════════════
# Bug identifie par Jackson : signal ACHAT emis a 9h00 affiche "ACHAT"
# pendant plusieurs barres (9h05, 9h15 etc) car conditions toujours
# vraies. Humain croit voir nouveau signal → FOMO trade late = perdant.
# Fix : distinguer EVENEMENT (transition False→True) de ETAT (persistance).
_SIGNAL_STATE = {}  # {symbol: {"action": str, "first_bar_ts": int, "signal_id": str, "last_seen_ts": int}}
_MAX_SIGNAL_AGE_BARS = 2  # barres max avant EXPIRED (timeframe 1min)


def _evaluate_signal_freshness(symbol: str, action: str, bar_ts_ms: int) -> dict:
    """State machine transition vs persistance.

    Retourne {freshness: NEW|PERSISTENT|EXPIRED|IDLE, age_bars: int, signal_id: str}.
    NEW       = transition ATTENDRE/autre → signal actif (evenement tradable)
    PERSISTENT = meme signal, age 1-MAX → encore affichable mais pas tradable
    EXPIRED   = meme signal, age > MAX → action forcee ATTENDRE, pas tradable
    IDLE      = pas de signal (ATTENDRE/CONFLIT)
    """
    import uuid as _uuid
    prev = _SIGNAL_STATE.get(symbol, {"action": "ATTENDRE", "first_bar_ts": 0, "signal_id": None, "last_seen_ts": 0})

    is_active = action in ("ACHAT", "VENTE", "ACHAT PRUDENT", "VENTE PRUDENTE")

    if not is_active:
        _SIGNAL_STATE[symbol] = {"action": action, "first_bar_ts": 0, "signal_id": None, "last_seen_ts": bar_ts_ms}
        return {"freshness": "IDLE", "age_bars": 0, "signal_id": None}

    if action != prev["action"]:
        new_id = _uuid.uuid4().hex[:8]
        _SIGNAL_STATE[symbol] = {"action": action, "first_bar_ts": bar_ts_ms, "signal_id": new_id, "last_seen_ts": bar_ts_ms}
        return {"freshness": "NEW", "age_bars": 0, "signal_id": new_id}

    age_bars = int((bar_ts_ms - prev["first_bar_ts"]) / 60000)
    freshness = "NEW" if age_bars == 0 else ("PERSISTENT" if age_bars <= _MAX_SIGNAL_AGE_BARS else "EXPIRED")
    _SIGNAL_STATE[symbol] = {**prev, "last_seen_ts": bar_ts_ms}
    return {"freshness": freshness, "age_bars": age_bars, "signal_id": prev["signal_id"]}


def build_conseil_global(
    bar: dict,
    regime: dict,
    options: Optional[dict] = None,
) -> dict:
    """Calcule le Conseil Global — verdict final ACHAT/VENTE/ATTENDRE/CONFLIT.

    Integre le gamma gate via cap absolu sur bull_pts / bear_pts quand
    options != None et qu'un mur MQ est proche (voir `_gamma_gate_check`).
    Le parametre `options` est optionnel pour retro-compatibilite — les
    anciens appelants continueront de fonctionner sans gamma gate.

    v1.5 (22/04) : ajoute freshness (NEW/PERSISTENT/EXPIRED/IDLE) + signal_id
    + age_bars pour distinguer evenement (transition) de etat (persistance).
    Fix bug signal ACHAT affiche pendant 15 min (Jackson directive).
    """
    if not bar or not regime:
        return {"action": "ATTENDRE", "bull_points": 0, "bear_points": 0, "reason": "pas de donnees",
                "freshness": "IDLE", "age_bars": 0, "signal_id": None}

    bull_pts = 0
    bear_pts = 0
    checks = []

    # 1. Bias regime (poids 2)
    bias = regime.get("bias", "NEUTRAL")
    if bias == "BULLISH":
        bull_pts += 2
    elif bias == "BEARISH":
        bear_pts += 2
    checks.append(f"Bias: {bias}")

    # 2. Delta direction jour
    delta_dir = get_int_field(bar, "delta_day_dir", 0)
    if delta_dir > 0:
        bull_pts += 1
    elif delta_dir < 0:
        bear_pts += 1
    checks.append(f"Delta: {'acheteurs' if delta_dir > 0 else 'vendeurs' if delta_dir < 0 else 'neutre'}")

    # 3. RVOL (informatif, pas de points)
    rvol = get_field(bar, "rvol", 0)
    checks.append(f"RVOL: {rvol:.1f}x")

    # 4. Position range — seuils alignes avec build_regime_context (80/20)
    pos = regime.get("range_pos", 50)
    if pos <= 20:
        bull_pts += 1
    elif pos >= 80:
        bear_pts += 1
    checks.append(f"Range: {pos:.0f}%")

    # 5. MTF (poids 2 si 4/4, 1 si 3/4)
    mtf_bulls = regime.get("mtf_bulls", 0)
    mtf_bears = regime.get("mtf_bears", 0)
    if mtf_bulls >= 3:
        mtf_w = 2 if mtf_bulls == 4 else 1
        bull_pts += mtf_w
    if mtf_bears >= 3:
        mtf_w = 2 if mtf_bears == 4 else 1
        bear_pts += mtf_w
    checks.append(f"MTF: {regime.get('mtf_verdict', 'N/A')}")

    # 6. Divergence forte (poids 2) — seuils alignes 80/20
    div_grade = regime.get("div_grade", "NONE")
    if div_grade in ("EXTREME", "FORTE"):
        if pos <= 20:
            bull_pts += 2
        elif pos >= 80:
            bear_pts += 2
    checks.append(f"DIV: {div_grade}")

    # 7. Gamma gate — cap absolu (regle Jackson : "moins de recos > contre-trader")
    # Applique APRES les 6 signaux, AVANT le verdict. Garantit qu'un mur proche
    # force ATTENDRE quel que soit le score des autres signaux.
    block_long, block_short, gamma_warnings = _gamma_gate_check(bar, options)
    if block_long:
        bull_pts = min(bull_pts, _GAMMA_CAP_BULL_BEAR)
    if block_short:
        bear_pts = min(bear_pts, _GAMMA_CAP_BULL_BEAR)
    checks.extend(gamma_warnings)

    # PATCH 22/04/2026 : Ajout BN footprint events aux checks (visibilite trader)
    # Ne modifie PAS bull_pts/bear_pts (pour eviter pattern 11 hardcoded).
    # Audit market-analyst 22/04 : v2 enrichi degrade PF -> on garde v1 pondere,
    # on ajoute juste les events BN comme CONTEXTE dans la deroulante.
    bn_color_up = get_int_field(bar, "bn_color_up", 0)
    bn_color_dn = get_int_field(bar, "bn_color_dn", 0)
    bn_long_up = get_int_field(bar, "bn_long_up", 0)
    bn_long_dn = get_int_field(bar, "bn_long_dn", 0)
    bn_absorb_bid = get_int_field(bar, "bn_absorb_bid", 0)
    bn_absorb_ask = get_int_field(bar, "bn_absorb_ask", 0)
    bn_bull = bn_color_up + bn_long_up + bn_absorb_bid
    bn_bear = bn_color_dn + bn_long_dn + bn_absorb_ask
    if bn_bull > 0 or bn_bear > 0:
        bn_parts = []
        if bn_color_up: bn_parts.append("color_up")
        if bn_long_up: bn_parts.append("long_up")
        if bn_absorb_bid: bn_parts.append("absorb_bid")
        if bn_color_dn: bn_parts.append("color_dn")
        if bn_long_dn: bn_parts.append("long_dn")
        if bn_absorb_ask: bn_parts.append("absorb_ask")
        checks.append(f"BN events ({bn_bull}+/{bn_bear}-): {' '.join(bn_parts)}")

    # Verdict
    conflict = bull_pts >= 3 and bear_pts >= 3
    if conflict:
        action = "CONFLIT"
    elif bull_pts >= 5 and bear_pts <= 2:
        action = "ACHAT"
    elif bear_pts >= 5 and bull_pts <= 2:
        action = "VENTE"
    elif bull_pts >= 4 and bear_pts <= 2:
        action = "ACHAT PRUDENT"
    elif bear_pts >= 4 and bull_pts <= 2:
        action = "VENTE PRUDENTE"
    else:
        action = "ATTENDRE"

    # PATCH 22/04/2026 : BLOCK SELL signals
    # Audit market-analyst 22/04 : SELL PF=0.00 sur ES (0/6 wins), PF=0.60 NQ.
    # Jackson a bust son compte Topstep sur SELL trade (news imprevue).
    # Revalidation obligatoire sur v4 propre mi-mai avant re-activation.
    if action in ("VENTE", "VENTE PRUDENTE"):
        original_action = action
        action = "ATTENDRE"
        checks.append(f"SELL DISABLED (audit 22/04 : PF=0.00 ES / PF=0.60 NQ)")
        checks.append(f"  Signal original : {original_action} ({bear_pts} bear pts)")
        checks.append(f"  Re-activation apres validation v4 propre")

    # v1.5 (22/04) State machine transition vs persistance
    symbol_key = str(bar.get("sym", "UNKNOWN")).upper()
    bar_ts_ms = int(bar.get("ts", 0))
    state = _evaluate_signal_freshness(symbol_key, action, bar_ts_ms)

    # EXPIRED : force action → ATTENDRE (signal perime, plus tradable)
    if state["freshness"] == "EXPIRED":
        checks.append(f"SIGNAL EXPIRE apres {state['age_bars']} barres (max {_MAX_SIGNAL_AGE_BARS})")
        checks.append(f"  Action forcee → ATTENDRE (signal non tradable, conditions persistantes)")
        display_action = "ATTENDRE"
    else:
        display_action = action

    return {
        "action": display_action,
        "bull_points": bull_pts,
        "bear_points": bear_pts,
        "reason": f"{bull_pts} bull / {bear_pts} bear",
        "checks": checks,
        "gamma_block_long": block_long,
        "gamma_block_short": block_short,
        "freshness": state["freshness"],
        "age_bars": state["age_bars"],
        "signal_id": state["signal_id"],
        "raw_action": action,  # action avant expiration (pour debug)
    }


# ═══════════════════════════════════════════════════════════════
# Builder 14 : Trade Suggestion
# ═══════════════════════════════════════════════════════════════


def build_trade_suggestion(bar: dict, symbol: str, regime: dict, options: dict) -> dict:
    """Suggestion de trade + checklist pre-trade.

    Integre le gamma gate en check #7 : si le prix est proche d'un mur MQ
    du cote de la direction favoree (LONG vs call wall, SHORT vs put), la
    check echoue → grade degrade → has_signal = False.

    Regle Jackson : "mieux vaut moins de signaux que trader contre le flux".
    """
    if not bar or not regime:
        return {"has_signal": False}

    favor = regime.get("favor", "NEUTRE")
    mode = regime.get("mode", "NORMAL")
    vol = regime.get("vol_regime", "NORMAL")
    bias_conf = regime.get("bias_confidence", 0.0)

    # Checklist pre-trade
    checks = []

    # 1. Session tradable?
    session = get_str_field(bar, "session_id", "N/A")
    is_us = session == "US"
    checks.append({"name": "Session US", "ok": is_us})

    # 2. VIX pas extreme
    vix = get_field(bar, "vix_level", 0.0)
    vix_ok = 12 < vix < 35
    checks.append({"name": f"VIX acceptable ({vix:.1f})", "ok": vix_ok})

    # 3. Volatilite pas extreme
    vol_ok = vol != "EXTREME"
    checks.append({"name": f"Volatilite {vol}", "ok": vol_ok})

    # 4. Direction claire
    dir_ok = favor in ("LONG", "SHORT")
    checks.append({"name": f"Direction: {favor}", "ok": dir_ok})

    # 5. Pas de divergence prix/delta
    div = get_int_field(bar, "delta_divergence", 0)
    checks.append({"name": "Pas de divergence P/D", "ok": div == 0})

    # 6. Confidence suffisante
    conf_ok = bias_conf >= 0.4
    checks.append({"name": f"Confidence {bias_conf:.0%}", "ok": conf_ok})

    # 7. Gamma gate — options positioning (ajoute si options fournis)
    # On utilise la meme logique que build_conseil_global pour coherence.
    if options:
        block_long, block_short, _gamma_warnings = _gamma_gate_check(bar, options)
        if favor == "LONG" and block_long:
            checks.append({"name": "Gamma: mur CALL proche", "ok": False})
        elif favor == "SHORT" and block_short:
            checks.append({"name": "Gamma: support PUT proche", "ok": False})
        else:
            checks.append({"name": "Gamma: clair", "ok": True})

    # SL/TP adaptatifs
    atr = get_field(bar, "atr", 0.0)
    sl_ticks = round(atr * 0.08, 1) if atr > 0 else 10.0
    tp_ticks = round(sl_ticks * 2.0, 1)
    price = get_field(bar, "price", 0.0)

    if favor == "LONG":
        sl_price = round(price - sl_ticks * TICK_SIZE, 2)
        tp_price = round(price + tp_ticks * TICK_SIZE, 2)
    elif favor == "SHORT":
        sl_price = round(price + sl_ticks * TICK_SIZE, 2)
        tp_price = round(price - tp_ticks * TICK_SIZE, 2)
    else:
        sl_price = None
        tp_price = None

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    # Grade dynamique adapte au nombre de checks (6 ou 7 selon options fournis)
    # Seuils relatifs au total pour eviter une regression "A → B" juste parce
    # qu'on a ajoute une 7e check.
    if passed == total:
        grade = "A"
    elif passed >= total - 1:
        grade = "B"
    elif passed >= total - 2:
        grade = "C"
    else:
        grade = "D"

    # Gamma gate hard-fail : si le check gamma est rouge, on refuse le signal
    # meme si le grade reste B. Coherent avec la regle Jackson "moins de
    # signaux > contre-trader le flux institutionnel".
    gamma_failed = any(
        c["name"].startswith("Gamma:") and not c["ok"] for c in checks
    )
    has_signal = (
        grade in ("A", "B")
        and dir_ok
        and conf_ok
        and not gamma_failed
    )

    action = "GO" if has_signal else "WAIT" if grade in ("B", "C") else "NO TRADE"

    return {
        "has_signal": has_signal,
        "action": action,
        "grade": grade,
        "direction": favor,
        "checks": checks,
        "passed": passed,
        "total": total,
        "sl_ticks": sl_ticks,
        "tp_ticks": tp_ticks,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "rr": 2.0,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 15 : Signals Journal (depuis bot JSON)
# ═══════════════════════════════════════════════════════════════


def build_signals_journal(bot_data: dict) -> dict:
    """Signaux et journal depuis le dashboard JSON du bot."""
    sj = bot_data.get("signals_journal", {})
    return {
        "current_signal": sj.get("current_signal"),
        "signal_score": sj.get("signal_score"),
        "signal_reason": sj.get("signal_reason", ""),
        "sl_ticks": sj.get("sl_ticks"),
        "tp_ticks": sj.get("tp_ticks"),
        "rr_ratio": sj.get("rr_ratio"),
        "recent_trades": sj.get("recent_trades", []),
        "recent_rejections": sj.get("recent_rejections", []),
    }
