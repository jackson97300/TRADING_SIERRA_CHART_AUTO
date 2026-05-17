"""Bot 3 — Context Analyzer.

Extrait les 12 dimensions de contexte au moment du touch d'un niveau.

12 dimensions :
  1. Open Type Dalton + Day Type
  2. POC migration (consensus institutionnel)
  3. Session + segment + time_to_close
  4. Orderflow au contact (delta, finish, rvol, cvd)
  5. Structure Dalton (failed_auction, rotation, IB extension, position_in_range)
  6. News proximity (VETO si imminente)
  7. Big traders / whales (n_big_bid/ask t1-t4)
  8. Trapped traders (squeeze potential)
  9. ICT / Liquidity (sweeps + equal highs/lows)
  10. Cross-instrument (SMT divergence + delta agreement)
  11. ATR regime (vol expansion vs contraction)
  12. Roll day (VETO si is_roll_day)

Pure function, no side effects, retourne dict serializable.
"""
from __future__ import annotations

from typing import Any


def _safe_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):  # NaN / Inf check
            return default
        return f
    except (TypeError, ValueError):
        return default


def analyze_context(bar: dict) -> dict:
    """Extrait les 12 dimensions du contexte depuis une barre V4 enriched.

    Args:
        bar : dict-like (pd.Series or dict) avec les features V4

    Returns:
        dict ctx avec toutes les dimensions normalisees
    """
    ctx: dict[str, Any] = {}

    # ═══ DIM 1 — OPEN TYPE DALTON + DAY TYPE ═══
    # T0=Open Drive, T1=Open Test Drive, T2=Open Rejection Reverse, T3=Open Auction
    ctx["open_type"] = _safe_int(bar.get("open_type"), 0)
    ctx["day_type"] = _safe_int(bar.get("day_type"), 0)

    # ═══ DIM 2 — POC MIGRATION (consensus institutionnel) ═══
    # POC UP = institutions achetent (supports tiennent, resistances cassent)
    # POC FLAT = range day (tous les niveaux tiennent mieux)
    # POC DOWN = institutions vendent (resistances tiennent, supports cassent)
    ctx["poc_mig_dir"] = _safe_int(bar.get("poc_migration_dir"), 0)
    ctx["poc_mig_speed"] = _safe_float(bar.get("ctx_poc_migration_10"), 0.0)
    ctx["va_dev"] = _safe_float(bar.get("ctx_va_developing_10"), 0.0)

    # ═══ DIM 3 — SESSION + SEGMENT + TIME_TO_CLOSE ═══
    if _safe_int(bar.get("is_in_asia"), 0) == 1:
        ctx["session"] = "ASIA"
    elif _safe_int(bar.get("is_in_london"), 0) == 1:
        ctx["session"] = "LONDON"
    elif _safe_int(bar.get("is_in_us_cash"), 0) == 1:
        ctx["session"] = "US_CASH"
    elif _safe_int(bar.get("is_in_us_after"), 0) == 1:
        ctx["session"] = "US_AFTER"
    else:
        ctx["session"] = "OTHER"
    ctx["session_segment"] = _safe_int(bar.get("session_segment"), 0)
    ctx["time_to_close"] = _safe_float(bar.get("time_to_session_close_norm"), 0.5)

    # ═══ DIM 4 — ORDERFLOW AU CONTACT ═══
    # BUY agressif au support = defenseurs presents = rejection probable
    # SELL agressif au support = le support lache = acceptance
    ctx["delta_bar"] = _safe_float(bar.get("delta_bar"), 0.0)
    # Jackson 03/05 Option B+ : delta_pct (delta_bar/total_vol) =
    # normalisation universelle Asia/RTH/Open. Anti-piege seuil absolu.
    ctx["delta_pct"] = _safe_float(bar.get("delta_pct"), 0.0)
    ctx["finish_strength"] = _safe_float(bar.get("finish_strength"), 0.0)
    ctx["rvol"] = _safe_float(bar.get("rvol"), 1.0)
    ctx["delta_day_dir"] = _safe_int(bar.get("delta_day_dir"), 0)
    ctx["cvd_session"] = _safe_float(bar.get("cvd_session"), 0.0)
    ctx["cvd_day"] = _safe_float(bar.get("cvd_day"), 0.0)
    ctx["cvd_5d_rolling"] = _safe_float(bar.get("cvd_5d_rolling"), 0.0)
    # vol_zscore_20 : volume relatif aux 20 dernieres barres (breakout vivant ?)
    ctx["vol_zscore_20"] = _safe_float(bar.get("vol_zscore_20"), 0.0)
    # cvd_trend derivable : UP si delta_day_dir > 0, DOWN si < 0, FLAT sinon
    if ctx["delta_day_dir"] > 0:
        ctx["cvd_trend"] = "UP"
    elif ctx["delta_day_dir"] < 0:
        ctx["cvd_trend"] = "DOWN"
    else:
        ctx["cvd_trend"] = "FLAT"
    # FIX P5 v3 (calibration empirique Jackson 03/05) : seuil cvd_5d magnitude
    # CALIBRE sur distribution reelle V4. cvd_5d_rolling NQ : p25=1460 p50=3939
    # p75=8014. Seuil ancien 200 trivial. Nouveau : >= p25 = 1500 (au moins
    # quartile bas pour eviter noise).
    # Critere doctrine Wyckoff : intraday >= 50% magnitude 5j ET 5j non-trivial.
    cvd_int = ctx["cvd_session"]
    cvd_5d = ctx["cvd_5d_rolling"]
    cvd_int_abs = abs(cvd_int)
    cvd_5d_abs = abs(cvd_5d)
    cvd_int_sign = 1 if cvd_int > 0 else (-1 if cvd_int < 0 else 0)
    cvd_5d_sign = 1 if cvd_5d > 0 else (-1 if cvd_5d < 0 else 0)
    # Magnitude_ok : 5j >= p25 (1500) ET intraday >= 50% magnitude 5j
    magnitude_ok = (cvd_5d_abs >= 1500.0) and (cvd_int_abs >= 0.5 * cvd_5d_abs)
    ctx["cvd_divergence"] = (
        cvd_int_sign != 0 and cvd_5d_sign != 0
        and cvd_int_sign != cvd_5d_sign
        and magnitude_ok
    )
    ctx["cvd_divergence_dir"] = cvd_int_sign if ctx["cvd_divergence"] else 0

    # ═══ TIER S features (Jackson 03/05 audit V4 features manquees) ═══
    # Brief : 7 features TIER S branchees concretement (pas inertes).
    # FIX market-analyst round 4 : retrait des features inertes (bar_body_ticks,
    # delta_change) qui chargeaient memoire sans usage. Si Phase 2+ besoin → reintegrer.
    #
    # Bar structure (hammer/shooting star → acceptance hybride breakout_retest)
    ctx["bar_body_pct"] = _safe_float(bar.get("bar_body_pct"), 0.0)
    ctx["bar_upper_wick_pct"] = _safe_float(bar.get("bar_upper_wick_pct"), 0.0)
    ctx["bar_lower_wick_pct"] = _safe_float(bar.get("bar_lower_wick_pct"), 0.0)
    ctx["bar_no_trade"] = _safe_int(bar.get("bar_no_trade"), 0)
    # Volume profile structure (range vs trend day)
    ctx["cur_va_n_buckets"] = _safe_int(bar.get("cur_va_n_buckets"), 0)
    ctx["cur_va_total_vol"] = _safe_float(bar.get("cur_va_total_vol"), 0.0)
    # Wyckoff effort/result : pic intra-bar delta (audit Phase 1 only,
    # PAS branche en filtre — Pattern 11 V1 evite, cf review 03/05 round 4)
    ctx["max_delta_bar"] = _safe_float(bar.get("max_delta_bar"), 0.0)
    ctx["min_delta_bar"] = _safe_float(bar.get("min_delta_bar"), 0.0)
    # Acceleration delta (Mark Douglas inflexion) — utilise dans
    # _compute_breakout_retest_confidence (bonus +5 si direction alignee)
    ctx["delta_change"] = _safe_float(bar.get("delta_change"), 0.0)
    # Spike + footprint (BREAKOUT confirmation)
    ctx["spike_detected_lag3"] = _safe_int(bar.get("spike_detected_lag3"), 0)
    ctx["vol_spike_up"] = _safe_int(bar.get("vol_spike_up"), 0)
    ctx["vol_spike_dn"] = _safe_int(bar.get("vol_spike_dn"), 0)
    ctx["bn_stack_ask"] = _safe_int(bar.get("bn_stack_ask"), 0)
    ctx["bn_stack_bid"] = _safe_int(bar.get("bn_stack_bid"), 0)

    # ═══ DIM 4b — ABSORPTION AU NIVEAU + COLOR IMBALANCE (Jackson 03/05 Option B+) ═══
    # Anti spring Wyckoff : si bn_absorb_bid_at_level > 0 lors d'un sell-off,
    # les acheteurs absorbent au support → c'est un spring, pas un breakdown.
    ctx["bn_absorb_bid_at_level"] = _safe_int(bar.get("bn_absorb_bid_at_level"), 0)
    ctx["bn_absorb_ask_at_level"] = _safe_int(bar.get("bn_absorb_ask_at_level"), 0)
    # Color cluster imbalance : > 0 buyers dominent zone proche, < 0 sellers dominent
    n_color_up = _safe_int(bar.get("n_color_up_cluster_within_0_2pct"), 0)
    n_color_dn = _safe_int(bar.get("n_color_dn_cluster_within_0_2pct"), 0)
    ctx["color_cluster_up"] = n_color_up
    ctx["color_cluster_dn"] = n_color_dn
    ctx["color_imbalance"] = n_color_up - n_color_dn

    # ═══ DIM 5 — STRUCTURE DALTON ═══
    # Failed auction = reversal probable (profil desequilibre)
    # Rotation factor = range (eleve) vs trend (bas)
    ctx["failed_auction"] = _safe_float(bar.get("ctx_failed_auction"), 0.0)
    ctx["rotation_factor"] = _safe_float(bar.get("ctx_rotation_factor_20"), 0.0)
    ctx["ib_extension_ratio"] = _safe_float(bar.get("ctx_ib_extension_ratio"), 0.0)
    ctx["position_in_range"] = _safe_float(bar.get("position_in_range"), 0.5)
    ctx["premium_zone"] = _safe_int(bar.get("premium_zone"), 0)
    ctx["discount_zone"] = _safe_int(bar.get("discount_zone"), 0)

    # ═══ DIM 6 — NEWS PROXIMITY (VETO) ═══
    # Creneaux news reels V4 (ET) : 715, 730, 830, 845, 900, 930
    ctx["mins_since_news"] = _safe_int(bar.get("mins_since_news"), 999)
    ctx["mins_to_news"] = _safe_int(bar.get("mins_to_next_news"), 999)
    ctx["within_news_715_5m"] = _safe_int(bar.get("within_news_715_5m"), 0)
    ctx["within_news_730_5m"] = _safe_int(bar.get("within_news_730_5m"), 0)
    ctx["within_news_830_5m"] = _safe_int(bar.get("within_news_830_5m"), 0)
    ctx["within_news_845_5m"] = _safe_int(bar.get("within_news_845_5m"), 0)
    ctx["within_news_900_5m"] = _safe_int(bar.get("within_news_900_5m"), 0)
    ctx["within_news_930_5m"] = _safe_int(bar.get("within_news_930_5m"), 0)
    ctx["is_news_715"] = _safe_int(bar.get("is_news_715"), 0)
    ctx["is_news_730"] = _safe_int(bar.get("is_news_730"), 0)
    ctx["is_news_830"] = _safe_int(bar.get("is_news_830"), 0)
    ctx["is_news_845"] = _safe_int(bar.get("is_news_845"), 0)
    ctx["is_news_900"] = _safe_int(bar.get("is_news_900"), 0)
    ctx["is_news_930"] = _safe_int(bar.get("is_news_930"), 0)

    # ═══ DIM 7 — BIG TRADERS / WHALES ═══
    # Big bids au support = institutions defendent = support tient
    # Big asks au resistance = institutions defendent = resistance tient
    ctx["n_big_bid_t1"] = _safe_int(bar.get("n_big_bid_v2_t1"), 0)
    ctx["n_big_bid_t2"] = _safe_int(bar.get("n_big_bid_v2_t2"), 0)
    ctx["n_big_bid_t3"] = _safe_int(bar.get("n_big_bid_v2_t3"), 0)
    ctx["n_big_bid_t4"] = _safe_int(bar.get("n_big_bid_v2_t4"), 0)
    ctx["n_big_ask_t1"] = _safe_int(bar.get("n_big_ask_v2_t1"), 0)
    ctx["n_big_ask_t2"] = _safe_int(bar.get("n_big_ask_v2_t2"), 0)
    ctx["n_big_ask_t3"] = _safe_int(bar.get("n_big_ask_v2_t3"), 0)
    ctx["n_big_ask_t4"] = _safe_int(bar.get("n_big_ask_v2_t4"), 0)
    ctx["max_big_bid_vol"] = _safe_int(bar.get("max_big_bid_vol_in_bar"), 0)
    ctx["max_big_ask_vol"] = _safe_int(bar.get("max_big_ask_vol_in_bar"), 0)
    ctx["p99_trade_size"] = _safe_float(bar.get("p99_trade_size"), 0.0)

    # ═══ DIM 8 — TRAPPED TRADERS ═══
    # Trapped buyers near = ils vendront si support casse
    # Trapped sellers near = short squeeze possible si support tient
    ctx["trapped_buyers_near_pct"] = _safe_float(bar.get("dist_trapped_buyers_nearest_pct"), 999.0)
    ctx["trapped_sellers_near_pct"] = _safe_float(bar.get("dist_trapped_sellers_nearest_pct"), 999.0)
    ctx["n_trapped_buy_cluster"] = _safe_int(bar.get("n_trapped_buyers_cluster_within_0_2pct"), 0)
    ctx["n_trapped_sell_cluster"] = _safe_int(bar.get("n_trapped_sellers_cluster_within_0_2pct"), 0)
    ctx["n_trapped_buy_zones"] = _safe_int(bar.get("n_trapped_buyers_zones_active"), 0)
    ctx["n_trapped_sell_zones"] = _safe_int(bar.get("n_trapped_sellers_zones_active"), 0)

    # ═══ DIM 9 — ICT / LIQUIDITY ═══
    # Liquidity sweep AVANT le touch = Wyckoff spring
    ctx["liq_sweep_high"] = _safe_int(bar.get("liquidity_sweep_high_lag5"), 0)
    ctx["liq_sweep_low"] = _safe_int(bar.get("liquidity_sweep_low_lag5"), 0)
    ctx["equal_highs"] = _safe_int(bar.get("equal_highs_detected"), 0)
    ctx["equal_lows"] = _safe_int(bar.get("equal_lows_detected"), 0)

    # ═══ DIM 10 — CROSS-INSTRUMENT ═══
    # SMT divergence ES/NQ = un casse et pas l'autre = signal de reversal
    # Cross delta agreement = ES et NQ d'accord = signal fort
    ctx["smt_divergence"] = _safe_int(bar.get("im_smt_divergence"), 0)
    ctx["cross_delta_agree"] = _safe_float(bar.get("im_cross_delta_agreement_5"), 0.0)
    ctx["volume_lead"] = _safe_float(bar.get("im_volume_lead"), 0.0)
    ctx["delta_day_divergence"] = _safe_int(bar.get("im_delta_day_divergence"), 0)

    # ═══ DIM 11 — ATR REGIME ═══
    ctx["atr"] = _safe_float(bar.get("atr"), 0.0)
    ctx["atr_14m_pct"] = _safe_float(bar.get("atr_14m_pct"), 0.0)
    ctx["atr_regime_zscore_60d"] = _safe_float(bar.get("atr_regime_zscore_60d"), 0.0)
    ctx["rvol_regime"] = _safe_int(bar.get("rvol_regime"), 1)
    ctx["vol_zscore_20"] = _safe_float(bar.get("vol_zscore_20"), 0.0)

    # ═══ DIM 12 — ROLL DAY (VETO) ═══
    ctx["is_roll_day"] = _safe_int(bar.get("is_roll_day"), 0)
    ctx["roll_phase"] = _safe_int(bar.get("roll_phase"), 0)
    ctx["days_since_roll"] = _safe_int(bar.get("days_since_roll"), 99)

    # ═══ BONUS 2 v2 (review code-reviewer 03/05) — MQ levels stale ═══
    # Bug fix : distinguer NaN (donnee absente) vs 0.0 (valeur reelle nulle).
    # Avant : _safe_float(NaN)=0 puis filtre >0 excluait → 3/4 NaN = pas stale (FAUX NEG).
    # Maintenant : utiliser bar.get(col) brut + check NaN explicit.
    import math
    mq_cols = ["dist_mq_call_pct", "dist_mq_put_pct",
               "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct"]
    mq_present_dists = []
    n_missing = 0
    for col in mq_cols:
        v = bar.get(col) if hasattr(bar, "get") else None
        if v is None:
            n_missing += 1
            continue
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                n_missing += 1
                continue
            mq_present_dists.append(abs(f))
        except (TypeError, ValueError):
            n_missing += 1
    # MQ stale si :
    # - >= 3/4 features manquantes (ingestion failed silencieux), OU
    # - toutes les features presentes ont dist > 5% (prix loin de tous les walls)
    if n_missing >= 3:
        ctx["mq_levels_stale"] = True
    elif mq_present_dists and all(d > 5.0 for d in mq_present_dists):
        ctx["mq_levels_stale"] = True
    else:
        ctx["mq_levels_stale"] = False

    # ═══ DIM 14 — SWING_COLOR_CONSENSUS inputs (Phase 1.7d 17/05/2026) ═══
    # FIX VALIDATION_MISS code-reviewer 17/05 : sans ces 3 features dans ctx,
    # _compute_swing_color_consensus dans decision_engine retourne TOUJOURS
    # "NEUTRE" -> aucun boost applique en prod malgre tests verts.
    # Default 999.0 pour distances (= "loin", pas confluence) au lieu de 0.0
    # (=faux positif CONFLUENCE puisque |0| < proximity 0.05%).
    ctx["dist_color_up_nearest_pct"] = _safe_float(
        bar.get("dist_color_up_nearest_pct"), 999.0)
    ctx["dist_color_dn_nearest_pct"] = _safe_float(
        bar.get("dist_color_dn_nearest_pct"), 999.0)
    ctx["aggressor_imbalance"] = _safe_float(
        bar.get("aggressor_imbalance"), 0.0)

    return ctx
