"""Bot 3 — Decision Engine.

Vetos absolus + filtres directionnels + confirmation orderflow + confidence + SL adaptatif.

Pipeline :
  1. Vetos absolus (roll_day / news / volume mort) → return SKIP
  2. Resolution side (LONG/SHORT) selon level["side"] + position du prix
  3. Required context (Tier 3 only)
  4. Filtres anti-trend (poc_mig, va_dev)
  5. Filtre orderflow (delta + finish coherent avec direction)
  6. Calcul confidence (whales, sweep, failed_auction, smt, trapped)
  7. SL adaptatif (atr_14m_pct vs baseline)
  8. Return (trade=True, side, sl_ticks, confidence)

Pure function, no side effects. Testable unitairement.

IMPORTANT — Les `reason` strings retournees ("VETO_NEWS_IMMINENT", "SKIP_BULL_STRONG"...)
sont des ETIQUETTES descriptives, PAS des codes du `log_catalog`. Pour emettre un log,
l'appelant DOIT utiliser `bot3_mp_engine.reason_to_log_code(reason)` qui mappe
vers les codes stables (BOT3_VETO_NEWS, BOT3_DECISION_SKIP, BOT3_TIER3_MISS, etc.).
Sinon `log_catalog.resolve()` lèvera KeyError en production.
"""
from __future__ import annotations

from typing import Optional

try:
    from .bot3_config import (
        ATR_BASELINE,
        ATR_MULTIPLIER_CLAMP,
        BLOCKED_COMBOS_BOT3,
        BOT3_TRADE_BREAKOUTS,
        BOT3_TRADE_REJECTIONS,
        GUARD_RAILS_BOT3,
        NEUTRAL_BAR_BODY_STRONG,
        NEUTRAL_COLOR_IMBALANCE_BLOCK_MIN,
        NEUTRAL_DELTA_PCT_THRESHOLD,
        NEUTRAL_FINISH_THRESHOLD,
        NEUTRAL_HAMMER_LOWER_WICK_MIN,
        NEUTRAL_POC_SPEED_STRONG,
        NEUTRAL_POC_SPEED_WEAK,
        NEUTRAL_SHOOTING_STAR_UPPER_WICK_MIN,
        NEUTRAL_SPIKE_LAG_BLOCK,
        NEUTRAL_VA_BUCKETS_RANGE,
        NEUTRAL_VA_BUCKETS_TREND,
        NEUTRAL_VA_CONTRACT_THRESHOLD,
        NEUTRAL_VA_EXPAND_THRESHOLD,
        NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN,
        SESSION_BOOST_CONFIDENCE,
        SWING_COLOR_BOOSTED,
        SWING_COLOR_PROXIMITY_PCT,
        VETO_NEWS_AFTER_MIN,
        VETO_RVOL_MIN,
        VETO_ROLL_DAY,
    )
except ImportError:
    from bot3_config import (
        ATR_BASELINE,
        ATR_MULTIPLIER_CLAMP,
        BLOCKED_COMBOS_BOT3,
        BOT3_TRADE_BREAKOUTS,
        BOT3_TRADE_REJECTIONS,
        GUARD_RAILS_BOT3,
        NEUTRAL_BAR_BODY_STRONG,
        NEUTRAL_COLOR_IMBALANCE_BLOCK_MIN,
        NEUTRAL_DELTA_PCT_THRESHOLD,
        NEUTRAL_FINISH_THRESHOLD,
        NEUTRAL_HAMMER_LOWER_WICK_MIN,
        NEUTRAL_POC_SPEED_STRONG,
        NEUTRAL_POC_SPEED_WEAK,
        NEUTRAL_SHOOTING_STAR_UPPER_WICK_MIN,
        NEUTRAL_SPIKE_LAG_BLOCK,
        NEUTRAL_VA_BUCKETS_RANGE,
        NEUTRAL_VA_BUCKETS_TREND,
        NEUTRAL_VA_CONTRACT_THRESHOLD,
        NEUTRAL_VA_EXPAND_THRESHOLD,
        NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN,
        SESSION_BOOST_CONFIDENCE,
        SWING_COLOR_BOOSTED,
        SWING_COLOR_PROXIMITY_PCT,
        VETO_NEWS_AFTER_MIN,
        VETO_RVOL_MIN,
        VETO_ROLL_DAY,
    )


def _compute_swing_color_consensus(side: str, ctx: dict) -> str:
    """Classifie le consensus COLOR-zone vs aggressor_imbalance pour ce side.

    Pattern Jackson 17/05 : "retour sur niveau defendu par color_up a beaucoup
    de chances de monter, RESPECTER LA TENDANCE pour qualite du rebond".

    Empiriquement (DSR Lopez=1.0 sur 11 combos NQ+ES, 11356 trades 6m v4 enriched) :
      - CONFLUENCE_STRONG : zone COLOR meme polarite proche + imbalance aligne
      - CONFLUENCE_OK     : zone COLOR meme polarite proche seule
      - DIVERGENCE        : zone COLOR polarite opposee proche + imbalance contraire
      - NEUTRE            : aucune zone COLOR proche

    Returns : "CONFLUENCE_STRONG" / "CONFLUENCE_OK" / "DIVERGENCE" / "NEUTRE".
    """
    dist_up = ctx.get("dist_color_up_nearest_pct")
    dist_dn = ctx.get("dist_color_dn_nearest_pct")
    imb = ctx.get("aggressor_imbalance", 0.0) or 0.0

    def _close(d):
        if d is None: return False
        try:
            return abs(float(d)) < SWING_COLOR_PROXIMITY_PCT
        except (TypeError, ValueError):
            return False

    close_up = _close(dist_up)
    close_dn = _close(dist_dn)

    if side == "LONG":
        if close_up and imb >= 0:
            return "CONFLUENCE_STRONG"
        if close_up:
            return "CONFLUENCE_OK"
        if close_dn and imb < 0:
            return "DIVERGENCE"
        return "NEUTRE"
    elif side == "SHORT":
        if close_dn and imb <= 0:
            return "CONFLUENCE_STRONG"
        if close_dn:
            return "CONFLUENCE_OK"
        if close_up and imb > 0:
            return "DIVERGENCE"
        return "NEUTRE"
    return "NEUTRE"


def evaluate_decision(
    level_name: str,
    level_def: dict,
    ctx: dict,
    symbol: str,
    dist_signed: float,
) -> tuple[bool, str, dict]:
    """Decide GO/SKIP pour un contact niveau-prix.

    Args:
        level_name : "SINGLE_PRINT" / "IB_LOW" / etc.
        level_def : dict du niveau (TIER1/2/3)
        ctx : dict des 12 dimensions de contexte
        symbol : "NQ" ou "ES"
        dist_signed : dist_pct (signe inclus). Negatif = prix au-dessus,
                      positif = prix en-dessous.

    Returns:
        (trade : bool, reason : str, params : dict)
        params si trade=True : {side, action, confidence, sl_ticks, atr_multiplier}
        params si trade=False : {reason_detail} optionnel
    """
    # ═══════════════════ VETOS ABSOLUS ═══════════════════

    if VETO_ROLL_DAY and ctx.get("is_roll_day", 0) == 1:
        return False, "VETO_ROLL_DAY", {}

    # News imminente : 5 min avant ou en cours
    # Liste reelle des creneaux news dispo dans V4 enriched (Jackson 03/05) :
    # 715, 730, 830, 845, 900, 930 ET. Pas de 1000 ni 1400 dans les features.
    if (ctx.get("within_news_715_5m") or
        ctx.get("within_news_730_5m") or
        ctx.get("within_news_830_5m") or
        ctx.get("within_news_845_5m") or
        ctx.get("within_news_900_5m") or
        ctx.get("within_news_930_5m")):
        return False, "VETO_NEWS_IMMINENT", {}

    # News juste passee : < 3 min apres
    if 0 <= ctx.get("mins_since_news", 999) < VETO_NEWS_AFTER_MIN:
        return False, "VETO_NEWS_JUST_HIT", {"mins_since_news": ctx["mins_since_news"]}

    # Volume mort
    if ctx.get("rvol", 1.0) < VETO_RVOL_MIN:
        return False, "VETO_VOLUME_MORT", {"rvol": ctx["rvol"]}

    # BONUS 2 (Jackson 03/05) : MQ levels stale → veto les niveaux MQ_*
    # Anti trade sur niveaux perimes (MQ ingestion failed >12h).
    if ctx.get("mq_levels_stale", False) and level_name.startswith("MQ_"):
        return False, "VETO_MQ_STALE", {"level": level_name}

    # ═══════════════════ BLOCK COMBO Session × Level (Phase 1.7b 17/05/2026) ═══════════════════
    # Source : audit Phase 1.0 post-enrichissement v4 enriched (454 cols).
    # 5 combos avec DSR_block=1.0 Bonferroni n_trials=1064, walk-forward 8-10/12
    # folds PF<0.7 stable. Edge negatif structurel ES marche bull 2026.
    # Cf bot3_config.py:BLOCKED_COMBOS_BOT3 + DOCS/BOT3_V2_PHASE1_0_AUDIT_REPORT.md
    session = ctx.get("session", "OTHER")
    combo_key = (symbol, session, level_name)
    if combo_key in BLOCKED_COMBOS_BOT3:
        block_info = BLOCKED_COMBOS_BOT3[combo_key]
        return False, f"BLOCK_COMBO_{symbol}_{session}_{level_name}", {
            "pf_observed": block_info["pf_observed"],
            "n_calibration": block_info["n"],
            "dsr_block": block_info["dsr_block"],
            "session": session,
            "level": level_name,
        }

    # ═══════════════════ RESOLUTION SIDE + ACTION ═══════════════════

    level_side = level_def["side"]
    side: Optional[str] = None
    action: str = "REJECTION"  # ou "BREAKOUT"

    if level_side in ("LONG", "SHORT"):
        # Niveau directionnel fixe (ex: IB_LOW = LONG, MQ_PUT_0DTE = LONG)
        side = level_side
        action = "REJECTION"
    elif level_side == "REJECTION":
        # FIX BUG D 15/05/2026 : convention NEW (level - close) compliant DMP C++.
        # dist_signed > 0 = level AU-DESSUS du prix → resistance → rejection SHORT
        # dist_signed < 0 = level EN-DESSOUS du prix → support → rejection LONG
        if dist_signed < 0:
            side = "LONG"  # level sous prix = support
        elif dist_signed > 0:
            side = "SHORT"  # level au-dessus = resistance
        else:
            return False, "SKIP_DIST_ZERO", {}
        action = "REJECTION"
    elif level_side == "NEUTRAL":
        # ═══ NIVEAU NEUTRE — STRUCTURE + ORDERFLOW (7 scenarios) ═══
        # Jackson 03/05 soir : logs funnel ultra detaille pour audit.
        side, action, neutral_reason, funnel = _resolve_neutral_side_with_funnel(ctx)
        if side is None:
            # Funnel = dict avec evaluation par scenario : pourquoi chaque a echoue
            return False, neutral_reason, {
                "poc_dir": ctx.get("poc_mig_dir", 0),
                "poc_speed": round(ctx.get("poc_mig_speed", 0.0), 4),
                "va_dev": round(ctx.get("va_dev", 0.0), 2),
                "delta_pct": round(ctx.get("delta_pct", 0.0), 3),
                "finish": ctx.get("finish_strength", 0.0),
                "funnel": funnel,                  # Jackson 03/05 : audit conditions
            }
    else:
        return False, f"SKIP_SIDE_INVALID_{level_side}", {}

    # ═══════════════════ TIER 3 : REQUIRED CONTEXT ═══════════════════

    if "required_context" in level_def:
        for key, expected in level_def["required_context"].items():
            # Cas special : seuil >= sur position_in_range_above
            if key == "position_in_range_above":
                actual_pos = ctx.get("position_in_range", 0.5)
                if actual_pos < expected:
                    return False, f"TIER3_MISS_{key}={actual_pos:.2f}_need>={expected}", {}
                continue  # check passe, continuer les autres required_context
            # Cas standard : equality check
            actual = _resolve_required_context(key, ctx)
            if actual is None:
                return False, f"TIER3_MISS_{key}_unresolved", {}
            if actual != expected:
                return False, f"TIER3_MISS_{key}={actual}_need={expected}", {}

    # ═══════════════════ FILTRE ANTI-TREND ═══════════════════
    # Skip pour les niveaux NEUTRAL : la convergence structure + orderflow
    # est deja inclue dans _resolve_neutral_side (7 scenarios).
    is_neutral = (level_def.get("side") == "NEUTRAL")

    poc_dir = ctx.get("poc_mig_dir", 0)
    poc_speed = ctx.get("poc_mig_speed", 0.0)
    va_dev = ctx.get("va_dev", 0.0)

    if not is_neutral:
        if side == "SHORT":
            if poc_dir == 1 and poc_speed > 0.05:
                return False, "SKIP_BULL_STRONG", {"poc_dir": poc_dir, "poc_speed": poc_speed}
            if va_dev > 2.0:
                return False, "SKIP_VA_EXPANDING", {"va_dev": va_dev}

        if side == "LONG":
            if poc_dir == -1 and poc_speed < -0.05:
                return False, "SKIP_BEAR_STRONG", {"poc_dir": poc_dir, "poc_speed": poc_speed}

    # ═══════════════════ FILTRE ORDERFLOW (REJECTION vs ACCEPTANCE) ═══════════════════
    # FIX market-analyst Section 4 + Jackson 03/05 : NE PAS inverser direction
    # sur 1 barre (anti-pattern Steidlmayer/Steenbarger). A la place :
    #   - Si orderflow crush (delta + finish coherents avec breakout)
    #   - Et que le niveau autorise inversion (REJECTION + tier < 3)
    #   - Et BOT3_TRADE_BREAKOUTS = True
    #   → return reason "PENDING_BREAKOUT_REGISTERED" + params side_break
    #   → le mp_engine register le pending dans BreakoutRetestStateMachine
    #   → le signal sera genere PLUS TARD apres acceptance multi-barres + retest
    # Pas d'entry sur la barre du touch.

    delta = ctx.get("delta_bar", 0.0)
    finish = ctx.get("finish_strength", 0.0)
    rvol = ctx.get("rvol", 1.0)

    # Magnitudes : seuils relatifs au rvol pour normaliser
    delta_strong_threshold = 50.0 * max(rvol, 0.5)
    finish_strong_threshold = 25.0

    # Autoriser detection breakout UNIQUEMENT sur level REJECTION + tier < 3
    # Skip pour NEUTRAL : decision deja prise via 7 scenarios.
    level_side_def = level_def.get("side")
    allow_breakout_detection = (
        level_side_def == "REJECTION" and level_def.get("tier", 1) < 3
    )

    if is_neutral:
        # Skip filtre orderflow PENDING_BREAKOUT (deja inclus dans 7 scenarios)
        pass
    elif side == "LONG":
        # Pour LONG (rejection support) : on veut delta > 0 (acheteurs)
        # Si delta tres negatif + finish negatif → vendeurs ecrasent → support casse
        if delta < -delta_strong_threshold and finish < -finish_strong_threshold:
            if BOT3_TRADE_BREAKOUTS and allow_breakout_detection:
                # PENDING : le mp_engine va register le breakout pour acceptance + retest
                return False, "PENDING_BREAKOUT_REGISTERED", {
                    "side_break": "SHORT",
                    "delta": delta,
                    "finish": finish,
                    "level_side_def": level_side_def,
                }
            elif BOT3_TRADE_BREAKOUTS and not allow_breakout_detection:
                return False, "SKIP_SELLERS_CRUSHING_DIRECTIONAL_LEVEL", {
                    "delta": delta, "finish": finish, "tier": level_def.get("tier")}
            else:
                return False, "SKIP_SELLERS_CRUSHING_NO_BREAKOUT_MODE", {
                    "delta": delta, "finish": finish}

    elif side == "SHORT":
        # Pour SHORT (rejection resistance) : on veut delta < 0
        if delta > delta_strong_threshold and finish > finish_strong_threshold:
            if BOT3_TRADE_BREAKOUTS and allow_breakout_detection:
                return False, "PENDING_BREAKOUT_REGISTERED", {
                    "side_break": "LONG",
                    "delta": delta,
                    "finish": finish,
                    "level_side_def": level_side_def,
                }
            elif BOT3_TRADE_BREAKOUTS and not allow_breakout_detection:
                return False, "SKIP_BUYERS_CRUSHING_DIRECTIONAL_LEVEL", {
                    "delta": delta, "finish": finish, "tier": level_def.get("tier")}
            else:
                return False, "SKIP_BUYERS_CRUSHING_NO_BREAKOUT_MODE", {
                    "delta": delta, "finish": finish}

    # action est toujours REJECTION ici (BREAKOUT passe par PENDING_BREAKOUT_REGISTERED)
    if not BOT3_TRADE_REJECTIONS:
        return False, "SKIP_REJECTIONS_DISABLED", {}

    # ═══════════════════ CALCUL CONFIDENCE (TRACKING-ONLY Phase 1) ═══════════════════
    # FIX market-analyst Section 5 (review 03/05) : pondérations heuristiques
    # NON regressees sur outcomes. NE JAMAIS utiliser pour decider/sizer
    # avant validation empirique (regression LightGBM ou logistic apres 200+ trades).
    # Cf feedback_lightgbm_no_composite_indicators.md (18/04) - composite indicators
    # hardcodes = anti-pattern. Phase 1 = tracking pour calibration ulterieure.
    # Variable s'appelle "confidence" pour compatibilite logs/dashboard mais
    # semantiquement = context_score_tracking. Plafonne a 100.

    confidence = 50  # baseline neutre

    # Whales : big traders confirment la direction
    if side == "LONG":
        whale_score = ctx.get("n_big_bid_t2", 0) + ctx.get("n_big_bid_t3", 0) * 3
        confidence += min(whale_score * 5, 15)
    else:  # SHORT
        whale_score = ctx.get("n_big_ask_t2", 0) + ctx.get("n_big_ask_t3", 0) * 3
        confidence += min(whale_score * 5, 15)

    # Liquidity sweep = Wyckoff spring (avant le touch)
    if side == "LONG" and ctx.get("liq_sweep_low"):
        confidence += 10
    if side == "SHORT" and ctx.get("liq_sweep_high"):
        confidence += 10

    # Failed auction (profil desequilibre = reversal probable)
    if abs(ctx.get("failed_auction", 0.0)) > 0.5:
        confidence += 10

    # Cross-instrument confirmation (ES/NQ d'accord)
    if ctx.get("cross_delta_agree", 0.0) > 0.7:
        confidence += 10

    # SMT divergence (un casse, l'autre pas → reversal)
    if ctx.get("smt_divergence"):
        confidence += 8

    # Trapped traders (squeeze potential)
    if side == "LONG" and ctx.get("n_trapped_sell_cluster", 0) > 0:
        confidence += 10  # trapped sellers near support = squeeze up
    if side == "SHORT" and ctx.get("n_trapped_buy_cluster", 0) > 0:
        confidence += 10  # trapped buyers near resistance = squeeze down

    # === BOOST Session × Level (Phase 1.7b 17/05/2026) ===
    # Source : audit Phase 1.0 post-enrichissement v4 enriched.
    # NQ LONDON SIDAK_COLOR_UP_zone : PF 2.02 n=459, CI [1.59, 2.63], DSR_boost=1.0.
    # ES US_CASH SIDAK_COLOR_DN_zone HOLD (CI plus large, n=189, re-eval J+30).
    # Cf bot3_config.py:SESSION_BOOST_CONFIDENCE
    boost_key = (symbol, session, level_name)
    boost_applied: Optional[dict] = None
    if boost_key in SESSION_BOOST_CONFIDENCE:
        boost_applied = SESSION_BOOST_CONFIDENCE[boost_key]
        confidence += boost_applied["boost"]

    # === BOOST Swing × Color confluence (Phase 1.7d 17/05/2026) ===
    # Pattern Jackson : "retour sur niveau defendu par color a beaucoup de
    # chances de monter, respecter la tendance pour qualite du rebond".
    # Audit empirique : 11 GOOD_EDGE combos COLOR seul (DSR Lopez 1.0,
    # n>=50, PF>=1.3). Anti Pattern 11 : 1 feature derivee, 0 gate.
    # Cf bot3_config.py:SWING_COLOR_BOOSTED + audit_color_vs_longbar_comparison.py
    swing_color_bucket = _compute_swing_color_consensus(side, ctx)
    swc_key = (symbol, level_name, swing_color_bucket)
    swing_color_boost_applied: Optional[int] = None
    if swc_key in SWING_COLOR_BOOSTED:
        swing_color_boost_applied = SWING_COLOR_BOOSTED[swc_key]
        confidence += swing_color_boost_applied

    # FIX M-1 (review code-reviewer 03/05) : clamp confidence 0-100
    # avant int() pour eviter score >100 (113 max sur test_confidence_full_stack)
    # qui casserait l'echelle d'un futur seuil decisionnel.
    confidence = max(0, min(100, confidence))

    # ═══════════════════ SL ADAPTATIF (ATR) ═══════════════════

    atr_baseline = ATR_BASELINE.get(symbol, 0.030)
    atr_current = ctx.get("atr_14m_pct", 0.0) or atr_baseline
    if atr_current <= 0:
        atr_current = atr_baseline

    atr_ratio = atr_current / atr_baseline
    atr_multiplier = max(ATR_MULTIPLIER_CLAMP[0], min(ATR_MULTIPLIER_CLAMP[1], atr_ratio))

    base_sl = GUARD_RAILS_BOT3[symbol]["sl_ticks_base"]
    adjusted_sl = int(round(base_sl * atr_multiplier))

    params = {
        "side": side,
        "action": action,         # REJECTION ou BREAKOUT
        "confidence": int(confidence),
        "sl_ticks": adjusted_sl,
        "atr_multiplier": round(atr_multiplier, 3),
        "atr_current": round(atr_current, 5),
        # Phase 1.7d : toujours expose le bucket pour tracking/audit
        "swing_color_consensus": swing_color_bucket,
    }
    # Phase 1.7b : tracer BOOST applique pour emit log BOT3_BOOST_APPLIED
    if boost_applied is not None:
        params["boost_applied"] = {
            "session": session,
            "level": level_name,
            "boost": boost_applied["boost"],
            "pf_observed": boost_applied["pf_observed"],
            "n_calibration": boost_applied["n"],
        }
    # Phase 1.7d : tracer BOOST swing_color applique
    if swing_color_boost_applied is not None:
        params["swing_color_boost_applied"] = {
            "level": level_name,
            "bucket": swing_color_bucket,
            "boost": swing_color_boost_applied,
        }
    return True, "GO", params


def _resolve_neutral_side_with_funnel(ctx: dict) -> tuple:
    """Wrapper : retourne (side, action, reason, funnel_dict).

    funnel_dict = analyse condition-par-condition POUR CHAQUE SCENARIO :
    quelle condition aurait passe ou bloque. Permet audit precis Jackson 03/05 :
    "savoir exactement quelle feature bloque a chaque etape".

    Le scenario qui MATCH est marque "MATCHED". Les autres listent les
    conditions echouees (col_name=actual_value vs expected).
    """
    side, action, reason = _resolve_neutral_side(ctx)
    funnel = _build_funnel(ctx, matched_side=side, matched_action=action)
    return side, action, reason, funnel


def _build_funnel(ctx: dict, matched_side: Optional[str], matched_action: Optional[str]) -> dict:
    """Audit conditions des 7 scenarios. Retourne dict pour log JSONL."""
    poc_dir = ctx.get("poc_mig_dir", 0)
    poc_speed = ctx.get("poc_mig_speed", 0.0)
    va_dev = ctx.get("va_dev", 0.0)
    delta_pct = ctx.get("delta_pct", 0.0)
    finish = ctx.get("finish_strength", 0.0)
    rvol = ctx.get("rvol", 1.0)
    delta_threshold = NEUTRAL_DELTA_PCT_THRESHOLD * max(rvol, 0.5)
    absorb_bid = ctx.get("bn_absorb_bid_at_level", 0)
    absorb_ask = ctx.get("bn_absorb_ask_at_level", 0)
    n_big_bid_inst = ctx.get("n_big_bid_t3", 0) + ctx.get("n_big_bid_t4", 0)
    n_big_ask_inst = ctx.get("n_big_ask_t3", 0) + ctx.get("n_big_ask_t4", 0)
    liq_sweep_high = ctx.get("liq_sweep_high", 0)
    liq_sweep_low = ctx.get("liq_sweep_low", 0)
    vol_z = ctx.get("vol_zscore_20", 0.0)
    cvd_div_dir = ctx.get("cvd_divergence_dir", 0)
    color_imb = ctx.get("color_imbalance", 0)
    bar_body_pct = ctx.get("bar_body_pct", 0.0)
    bar_no_trade = ctx.get("bar_no_trade", 0)
    cur_va_n_buckets = ctx.get("cur_va_n_buckets", 0)
    spike_lag3 = ctx.get("spike_detected_lag3", 0)
    vol_spike_up = ctx.get("vol_spike_up", 0)
    vol_spike_dn = ctx.get("vol_spike_dn", 0)
    bn_stack_ask = ctx.get("bn_stack_ask", 0)
    bn_stack_bid = ctx.get("bn_stack_bid", 0)

    f = {"matched_scenario": None, "matched_side": matched_side, "matched_action": matched_action}

    # Vetos universels
    f["veto_bar_no_trade"] = bool(bar_no_trade)
    f["veto_spike_recent"] = bool(spike_lag3) if NEUTRAL_SPIKE_LAG_BLOCK else False

    # Scenario 6 TREND day
    is_trend = (abs(poc_speed) > NEUTRAL_POC_SPEED_STRONG and va_dev > NEUTRAL_VA_EXPAND_THRESHOLD)
    f["s6_is_trend_day"] = is_trend
    if is_trend:
        f["s6_long_ok"] = (poc_dir == 1 and delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
                           and finish > NEUTRAL_FINISH_THRESHOLD
                           and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
                           and n_big_bid_inst > 0)
        f["s6_short_ok"] = (poc_dir == -1 and delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
                            and finish < -NEUTRAL_FINISH_THRESHOLD
                            and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
                            and n_big_ask_inst > 0)

    # Scenario 5 RANGE day
    is_range = (poc_dir == 0 and va_dev < NEUTRAL_VA_CONTRACT_THRESHOLD
                and abs(delta_pct) > NEUTRAL_DELTA_PCT_THRESHOLD
                and cur_va_n_buckets >= NEUTRAL_VA_BUCKETS_RANGE)
    f["s5_is_range_day"] = is_range
    if is_range:
        f["s5_fade_short_ok"] = (delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
                                  and finish > NEUTRAL_FINISH_THRESHOLD
                                  and n_big_bid_inst == 0)
        f["s5_fade_long_ok"] = (delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
                                 and finish < -NEUTRAL_FINISH_THRESHOLD
                                 and n_big_ask_inst == 0)

    # Scenario 1 BREAKOUT LONG conditions individuelles
    f["s1_poc_dir_ok"] = (poc_dir == 1)
    f["s1_delta_ok"] = (delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD)
    f["s1_finish_ok"] = (finish > NEUTRAL_FINISH_THRESHOLD)
    f["s1_vol_z_ok"] = (vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN)
    f["s1_big_bid_ok"] = (n_big_bid_inst > 0)
    f["s1_no_absorb_ask"] = (absorb_ask == 0)
    f["s1_no_liq_sweep_high"] = (not liq_sweep_high)
    f["s1_color_ok"] = (color_imb >= 0)
    f["s1_footprint_ok"] = (vol_spike_up == 1 or bn_stack_bid > bn_stack_ask)
    f["s1_body_ok"] = (bar_body_pct >= NEUTRAL_BAR_BODY_STRONG)

    # Scenario 2 BREAKOUT SHORT conditions
    f["s2_poc_dir_ok"] = (poc_dir == -1)
    f["s2_delta_ok"] = (delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD)
    f["s2_finish_ok"] = (finish < -NEUTRAL_FINISH_THRESHOLD)
    f["s2_vol_z_ok"] = (vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN)
    f["s2_big_ask_ok"] = (n_big_ask_inst > 0)
    f["s2_no_absorb_bid"] = (absorb_bid == 0)
    f["s2_no_liq_sweep_low"] = (not liq_sweep_low)
    f["s2_color_ok"] = (color_imb <= 0)
    f["s2_footprint_ok"] = (vol_spike_dn == 1 or bn_stack_ask > bn_stack_bid)
    f["s2_body_ok"] = (bar_body_pct >= NEUTRAL_BAR_BODY_STRONG)

    # Scenario 3 REJECTION SHORT counter-trend
    f["s3_poc_neutre"] = (poc_dir >= 0)
    f["s3_delta_neg"] = (delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD)
    f["s3_finish_neg"] = (finish < -NEUTRAL_FINISH_THRESHOLD)
    f["s3_poc_speed_weak"] = (abs(poc_speed) < NEUTRAL_POC_SPEED_WEAK)
    f["s3_no_absorb_bid"] = (absorb_bid == 0)
    f["s3_big_ask_ok"] = (n_big_ask_inst > 0)
    f["s3_cvd_not_bullish"] = (cvd_div_dir != 1)

    # Scenario 4 REJECTION LONG counter-trend
    f["s4_poc_neutre_or_down"] = (poc_dir <= 0)
    f["s4_delta_pos"] = (delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD)
    f["s4_finish_pos"] = (finish > NEUTRAL_FINISH_THRESHOLD)
    f["s4_poc_speed_weak"] = (abs(poc_speed) < NEUTRAL_POC_SPEED_WEAK)
    f["s4_no_absorb_ask"] = (absorb_ask == 0)
    f["s4_big_bid_ok"] = (n_big_bid_inst > 0)
    f["s4_cvd_not_bearish"] = (cvd_div_dir != -1)

    # Identifier scenario matched (si applicable)
    if matched_side:
        if matched_action == "BREAKOUT" and is_trend:
            f["matched_scenario"] = "S6_TREND_DAY"
        elif matched_action == "REJECTION" and is_range:
            f["matched_scenario"] = "S5_RANGE_FADE"
        elif matched_action == "BREAKOUT":
            f["matched_scenario"] = f"S{1 if matched_side == 'LONG' else 2}_BREAKOUT"
        elif matched_action == "REJECTION":
            f["matched_scenario"] = f"S{4 if matched_side == 'LONG' else 3}_COUNTER_TREND"

    return f


def _resolve_neutral_side(ctx: dict) -> tuple:
    """Resout side + action pour un niveau NEUTRAL via 7 scenarios.

    Jackson 03/05 Option B+ : convergence renforcee.
    Structure (poc_mig + va_dev) + Orderflow Tier 1 (delta_pct + absorb_at_level
    + big_traders) + Tier 2 (liq_sweep + vol_zscore + cvd_divergence + color_imbalance)
    convergent pour determiner BREAKOUT / REJECTION / SKIP.

    Discipline (pas Pattern 11) :
    - Chaque scenario demande convergence simultanee 4-6 conditions
    - Si convergence → trade. Sinon → SKIP.
    - Pas de cascade de gates rejetants.

    Returns:
        (side, action, reason_if_skip)
        side : "LONG" / "SHORT" / None (skip)
        action : "BREAKOUT" / "REJECTION" / None
        reason : raison du skip si side=None
    """
    # Structure
    poc_dir = ctx.get("poc_mig_dir", 0)
    poc_speed = ctx.get("poc_mig_speed", 0.0)
    va_dev = ctx.get("va_dev", 0.0)
    # Orderflow Tier 1
    delta_pct = ctx.get("delta_pct", 0.0)
    finish = ctx.get("finish_strength", 0.0)
    absorb_bid = ctx.get("bn_absorb_bid_at_level", 0)
    absorb_ask = ctx.get("bn_absorb_ask_at_level", 0)
    n_big_bid_inst = ctx.get("n_big_bid_t3", 0) + ctx.get("n_big_bid_t4", 0)
    n_big_ask_inst = ctx.get("n_big_ask_t3", 0) + ctx.get("n_big_ask_t4", 0)
    # Orderflow Tier 2
    liq_sweep_high = ctx.get("liq_sweep_high", 0)
    liq_sweep_low = ctx.get("liq_sweep_low", 0)
    vol_z = ctx.get("vol_zscore_20", 0.0)
    cvd_div = ctx.get("cvd_divergence", False)
    color_imb = ctx.get("color_imbalance", 0)
    # TIER S features (Jackson 03/05 audit V4)
    bar_body_pct = ctx.get("bar_body_pct", 0.0)
    bar_upper_wick_pct = ctx.get("bar_upper_wick_pct", 0.0)
    bar_lower_wick_pct = ctx.get("bar_lower_wick_pct", 0.0)
    bar_no_trade = ctx.get("bar_no_trade", 0)
    cur_va_n_buckets = ctx.get("cur_va_n_buckets", 0)
    cur_va_total_vol = ctx.get("cur_va_total_vol", 0.0)
    spike_lag3 = ctx.get("spike_detected_lag3", 0)
    vol_spike_up = ctx.get("vol_spike_up", 0)
    vol_spike_dn = ctx.get("vol_spike_dn", 0)
    bn_stack_ask = ctx.get("bn_stack_ask", 0)
    bn_stack_bid = ctx.get("bn_stack_bid", 0)
    # Wyckoff effort/result : pic delta intra-bar vs delta close
    max_delta_bar = ctx.get("max_delta_bar", 0.0)
    min_delta_bar = ctx.get("min_delta_bar", 0.0)
    delta_bar = ctx.get("delta_bar", 0.0)
    # Absorption signature Wyckoff : pic delta retracé > 2x delta close = absorption
    delta_peak_abs = max(abs(max_delta_bar), abs(min_delta_bar))
    delta_close_abs = abs(delta_bar)
    delta_absorbed = (delta_close_abs > 0 and delta_peak_abs / max(delta_close_abs, 1.0) >= 2.0)

    # ─── VETO universel TIER S : barre sans trade ou spike recent pollue ───
    if bar_no_trade == 1:
        return None, None, "SKIP_NEUTRAL_BAR_NO_TRADE"
    if NEUTRAL_SPIKE_LAG_BLOCK and spike_lag3 == 1:
        return None, None, "SKIP_NEUTRAL_SPIKE_RECENT_POLLUTED"

    # ─── SCENARIO 6 (priorite) : TREND day = same-direction only ───
    # Renforcement : volume z >= 1.0 (trend = vivant), big_traders direction confirmee
    if (abs(poc_speed) > NEUTRAL_POC_SPEED_STRONG
        and va_dev > NEUTRAL_VA_EXPAND_THRESHOLD):
        if (poc_dir == 1
            and delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
            and finish > NEUTRAL_FINISH_THRESHOLD
            and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
            and n_big_bid_inst > 0):
            return "LONG", "BREAKOUT", ""
        elif (poc_dir == -1
              and delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
              and finish < -NEUTRAL_FINISH_THRESHOLD
              and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
              and n_big_ask_inst > 0):
            return "SHORT", "BREAKOUT", ""
        else:
            return None, None, "SKIP_TREND_DAY_COUNTER_OR_NO_VOL_OR_NO_BIG"

    # ─── SCENARIO 5 (priorite) : RANGE day = fade extremes ───
    # TIER S : cur_va_n_buckets >= NEUTRAL_VA_BUCKETS_RANGE + volume distribue suffisant.
    # cur_va_total_vol > 0 confirme que le profile actuel a accumule du volume
    # (sinon profil vide = pas de vrai range, juste consolidation transitoire).
    if (poc_dir == 0
        and va_dev < NEUTRAL_VA_CONTRACT_THRESHOLD
        and abs(delta_pct) > NEUTRAL_DELTA_PCT_THRESHOLD
        and cur_va_n_buckets >= NEUTRAL_VA_BUCKETS_RANGE
        and cur_va_total_vol > 0):
        if (delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
            and finish > NEUTRAL_FINISH_THRESHOLD
            and n_big_bid_inst == 0):
            return "SHORT", "REJECTION", ""
        elif (delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
              and finish < -NEUTRAL_FINISH_THRESHOLD
              and n_big_ask_inst == 0):
            return "LONG", "REJECTION", ""
        else:
            return None, None, "SKIP_RANGE_INSTITUTIONAL_DRIVE"

    # ─── SCENARIO 1 : Structure UP + Orderflow UP = BREAKOUT LONG ───
    # TIER S : vol_spike_up=1 OR bn_stack_bid > bn_stack_ask + bar_body fort.
    if (poc_dir == 1
        and delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
        and finish > NEUTRAL_FINISH_THRESHOLD
        and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
        and n_big_bid_inst > 0
        and absorb_ask == 0
        and not liq_sweep_high
        and color_imb >= 0
        and (vol_spike_up == 1 or bn_stack_bid > bn_stack_ask)
        and bar_body_pct >= NEUTRAL_BAR_BODY_STRONG):
        return "LONG", "BREAKOUT", ""

    # ─── SCENARIO 2 : Structure DOWN + Orderflow DOWN = BREAKOUT SHORT ───
    if (poc_dir == -1
        and delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
        and finish < -NEUTRAL_FINISH_THRESHOLD
        and vol_z >= NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN
        and n_big_ask_inst > 0
        and absorb_bid == 0
        and not liq_sweep_low
        and color_imb <= 0
        and (vol_spike_dn == 1 or bn_stack_ask > bn_stack_bid)
        and bar_body_pct >= NEUTRAL_BAR_BODY_STRONG):
        return "SHORT", "BREAKOUT", ""

    # ─── SCENARIO 3 : Structure neutre/up faible + Orderflow DOWN = REJECTION SHORT ───
    # FIX P5 v2 (review code-reviewer + market-analyst 03/05) :
    # cvd_divergence_dir == -1 (intraday DOWN vs 5d UP = bearish reversal Wyckoff)
    # est un BONUS de conviction. Si cvd_divergence_dir == +1 (contraire) → BLOCK
    # car Wyckoff smart money buy = pas de short reversal credible.
    # FIX market-analyst+code-reviewer 03/05 round 4 : RETIRE `delta_absorbed`
    # filter (Pattern 11 V1 — composite indicator hardcode non backteste).
    # max_delta_bar / min_delta_bar restent extraits pour audit Phase 1 mais
    # ne pilotent pas la decision. Revoir Phase 2+ avec backtest empirique.
    cvd_div_dir = ctx.get("cvd_divergence_dir", 0)
    if (poc_dir >= 0
        and delta_pct < -NEUTRAL_DELTA_PCT_THRESHOLD
        and finish < -NEUTRAL_FINISH_THRESHOLD
        and abs(poc_speed) < NEUTRAL_POC_SPEED_WEAK
        and absorb_bid == 0                            # CRITIQUE : pas de spring Wyckoff
        and n_big_ask_inst > 0                         # vendeurs institutionnels
        and cvd_div_dir != 1):                         # PAS de bullish reversal multi-TF
        return "SHORT", "REJECTION", ""

    # ─── SCENARIO 4 : Structure neutre/down faible + Orderflow UP = REJECTION LONG ───
    if (poc_dir <= 0
        and delta_pct > NEUTRAL_DELTA_PCT_THRESHOLD
        and finish > NEUTRAL_FINISH_THRESHOLD
        and abs(poc_speed) < NEUTRAL_POC_SPEED_WEAK
        and absorb_ask == 0
        and n_big_bid_inst > 0
        and cvd_div_dir != -1):                        # PAS de bearish reversal multi-TF
        return "LONG", "REJECTION", ""

    # ─── SCENARIO 7 : aucune convergence = SKIP ───
    return None, None, "SKIP_NEUTRAL_NO_CONVERGENCE"


def _resolve_required_context(key: str, ctx: dict):
    """Resoud la valeur d'un required_context (equality check uniquement).

    Cas speciaux (ex: position_in_range_above) traites en amont dans evaluate_decision.
    Mappe les keys sur les champs ctx derives :
      - cvd_trend : "FLAT" / "UP" / "DOWN" depuis delta_day_dir (calcule dans context_analyzer)
      - open_type : ctx["open_type"]
      - poc_migration_dir : ctx["poc_mig_dir"] (rename)
    """
    if key == "cvd_trend":
        return ctx.get("cvd_trend", "FLAT")
    if key == "open_type":
        return ctx.get("open_type", -1)
    if key == "poc_migration_dir":
        return ctx.get("poc_mig_dir", 0)
    return ctx.get(key)
