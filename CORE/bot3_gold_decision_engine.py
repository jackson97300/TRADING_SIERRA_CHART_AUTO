"""Bot 3 Gold — Decision Engine 8 scénarios dynamiques (PROMPT_CLAUDE_CODE_BOT3_GOLD).

Architecture :
  - 8 scénarios (vs 7 NQ/ES) : ajout S7 Gold/Silver ratio + S8 Macro alignment
  - Niveaux NEUTRAUX → side dynamique selon contexte
  - 12 dimensions standard + 8 Gold-spécifiques
  - Fallbacks gracieux pour features absentes (n_big_*_v2_t3, position_in_range)

Pure function, no side effects.
"""
from __future__ import annotations
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT BUILDER (12 standard + 8 Gold)
# ─────────────────────────────────────────────────────────────────────────────

def detect_session(bar: dict) -> str:
    if int(bar.get("is_in_us_cash", 0) or 0) == 1:
        return "US_CASH"
    if int(bar.get("is_in_us_after", 0) or 0) == 1:
        return "US_AFTER"
    if int(bar.get("is_in_london", 0) or 0) == 1:
        return "LONDON"
    if int(bar.get("is_in_asia", 0) or 0) == 1:
        return "ASIA"
    return "OTHER"


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:
            return default
        return int(f)
    except (TypeError, ValueError):
        return default


def build_gold_context(bar: dict) -> dict:
    """Construit le contexte 20 dimensions Gold."""
    ctx = {}

    # ── 12 STANDARD ──
    ctx["open_type"] = _safe_int(bar.get("open_type"))
    ctx["day_type"] = _safe_int(bar.get("day_type"))
    ctx["poc_mig_dir"] = _safe_int(bar.get("poc_migration_dir"))
    ctx["poc_mig_speed"] = _safe_float(bar.get("ctx_poc_migration_10"))
    ctx["va_dev"] = _safe_float(bar.get("ctx_va_developing_10"))
    ctx["session"] = detect_session(bar)
    ctx["session_segment"] = _safe_int(bar.get("session_segment"))
    ctx["delta_bar"] = _safe_float(bar.get("delta_bar"))
    ctx["delta_pct"] = _safe_float(bar.get("delta_pct"))
    ctx["finish_strength"] = _safe_float(bar.get("finish_strength"))
    ctx["rvol"] = _safe_float(bar.get("rvol"), default=1.0)
    ctx["cvd_session"] = _safe_float(bar.get("cvd_session"))
    ctx["cvd_day"] = _safe_float(bar.get("cvd_day"))
    ctx["delta_day_dir"] = _safe_int(bar.get("delta_day_dir"))
    ctx["failed_auction"] = _safe_float(bar.get("ctx_failed_auction"))
    ctx["rotation_factor"] = _safe_float(bar.get("ctx_rotation_factor_20"))
    ctx["ib_extension_ratio"] = _safe_float(bar.get("ctx_ib_extension_ratio"))

    # position_in_range : fallback calcul si absent
    pos_range = bar.get("position_in_range")
    if pos_range is None or (isinstance(pos_range, float) and pos_range != pos_range):
        # Fallback : (close - cash_low) / (cash_high - cash_low)
        close = _safe_float(bar.get("close"))
        ch = _safe_float(bar.get("cash_high"))
        cl = _safe_float(bar.get("cash_low"))
        if ch > 0 and cl > 0 and ch > cl:
            ctx["position_in_range"] = max(0.0, min(1.0, (close - cl) / (ch - cl)))
        else:
            ctx["position_in_range"] = 0.5
    else:
        ctx["position_in_range"] = _safe_float(pos_range, default=0.5)

    ctx["mins_since_news"] = _safe_int(bar.get("mins_since_news"), default=999)
    for k in ("within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
              "within_news_845_5m", "within_news_900_5m", "within_news_930_5m"):
        ctx[k] = _safe_int(bar.get(k))

    # Big traders (fallback : t3 absent → utilise t2 seul)
    ctx["n_big_bid_t2"] = _safe_int(bar.get("n_big_bid_v2_t2"))
    ctx["n_big_ask_t2"] = _safe_int(bar.get("n_big_ask_v2_t2"))
    ctx["n_big_bid_t3"] = _safe_int(bar.get("n_big_bid_v2_t3"))  # défault 0 si absent
    ctx["n_big_ask_t3"] = _safe_int(bar.get("n_big_ask_v2_t3"))

    # Trapped
    ctx["trapped_buyers_near"] = _safe_float(
        bar.get("dist_trapped_buyers_nearest_pct"), default=999.0)
    ctx["trapped_sellers_near"] = _safe_float(
        bar.get("dist_trapped_sellers_nearest_pct"), default=999.0)
    ctx["bn_absorb_bid"] = _safe_int(bar.get("bn_absorb_bid_at_level"))
    ctx["bn_absorb_ask"] = _safe_int(bar.get("bn_absorb_ask_at_level"))

    # ICT (peut être absent → 0)
    ctx["liq_sweep_high"] = _safe_int(bar.get("liquidity_sweep_high_lag5"))
    ctx["liq_sweep_low"] = _safe_int(bar.get("liquidity_sweep_low_lag5"))

    # ATR
    ctx["atr"] = _safe_float(bar.get("atr"), default=17.0)
    ctx["atr_14m_pct"] = _safe_float(bar.get("atr_14m_pct"), default=0.035)
    ctx["vol_zscore_20"] = _safe_float(bar.get("vol_zscore_20"))

    ctx["is_roll_day"] = _safe_int(bar.get("is_roll_day"))
    ctx["regime_mode"] = str(bar.get("regime_mode", "NORMAL"))
    ctx["regime_favor"] = str(bar.get("regime_favor", "NEUTRE"))

    # ── 8 GOLD-SPÉCIFIQUES ──
    ctx["dxy_corr"] = _safe_float(bar.get("im_dxy_corr_60d"), default=-0.45)
    ctx["dxy_decoupled"] = ctx["dxy_corr"] > -0.15
    ctx["real_yields"] = _safe_float(bar.get("im_real_yields_proxy"))
    ctx["gs_ratio_z"] = _safe_float(bar.get("gold_silver_ratio_zscore_60d"))
    ctx["oil_gold_z"] = _safe_float(bar.get("oil_gold_ratio_zscore_60d"))
    ctx["copper_gold_mom"] = _safe_float(bar.get("copper_gold_ratio_momentum_30"))
    ctx["asia_breakout"] = _safe_float(bar.get("asia_breakout_strength"))
    ctx["in_london_fix"] = bool(
        _safe_int(bar.get("london_fix_window_10_30"))
        or _safe_int(bar.get("london_fix_window_15_00"))
    )
    ctx["session_break_accel"] = _safe_float(bar.get("mgc_session_break_acceleration"))

    # ── MACRO BIAS COMPOSITE (calculé) ──
    macro_bull = 0
    macro_bear = 0
    if ctx["real_yields"] < -0.5: macro_bull += 1
    if ctx["real_yields"] > 0.5:  macro_bear += 1
    if ctx["dxy_corr"] < -0.30:   macro_bull += 1
    if ctx["dxy_corr"] > -0.10:   macro_bear += 1
    if ctx["gs_ratio_z"] < -1.0:  macro_bull += 1
    if ctx["gs_ratio_z"] > 1.0:   macro_bear += 1
    if ctx["oil_gold_z"] > 0.5:   macro_bull += 1
    if ctx["oil_gold_z"] < -0.5:  macro_bear += 1
    if ctx["copper_gold_mom"] < -0.3: macro_bull += 1
    if ctx["copper_gold_mom"] > 0.3:  macro_bear += 1
    ctx["macro_bull_count"] = macro_bull
    ctx["macro_bear_count"] = macro_bear
    ctx["macro_bias"] = "BULL" if macro_bull >= 3 else ("BEAR" if macro_bear >= 3 else "NEUTRAL")

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# DECISION ENGINE — 8 SCÉNARIOS DYNAMIQUES
# ─────────────────────────────────────────────────────────────────────────────

DELTA_THRESHOLD = 0.20
FINISH_THRESHOLD = 10.0
POC_SPEED_WEAK = 0.05
POC_SPEED_STRONG = 0.05
VA_CONTRACT = -0.5
VA_EXPAND = 1.0
GS_EXTREME = 1.5

# Seuils Gold-calibrés (relâchés vs ES/NQ pour compenser Tier 3 absent)
BIG_TRADER_MIN = 1   # Tier 2 seul accepté (vs Tier 3+4 NQ/ES)


def resolve_gold_neutral_side(level_def: dict, ctx: dict) -> tuple:
    """Décide LONG/SHORT/SKIP pour niveau NEUTRAL Gold (8 scénarios).

    Returns: (side, action, reason)
    """
    # ── VETOS ABSOLUS ──
    if ctx["is_roll_day"]:
        return None, None, "VETO_ROLL_DAY"
    if ctx["within_news_830_5m"] or ctx["within_news_930_5m"]:
        return None, None, "VETO_NEWS_IMMINENT"
    if ctx["mins_since_news"] < 3:
        return None, None, "VETO_NEWS_JUST_HIT"
    if ctx["rvol"] < 0.3:
        return None, None, "VETO_VOLUME_MORT"
    if ctx["in_london_fix"]:
        return None, None, "VETO_LONDON_FIX"
    if ctx["session"] != "US_CASH":
        return None, None, "VETO_NOT_RTH"

    poc_dir = ctx["poc_mig_dir"]
    poc_speed = ctx["poc_mig_speed"]
    va_dev = ctx["va_dev"]
    delta_pct = ctx["delta_pct"]
    finish = ctx["finish_strength"]
    big_bids = ctx["n_big_bid_t2"] + ctx["n_big_bid_t3"] * 3
    big_asks = ctx["n_big_ask_t2"] + ctx["n_big_ask_t3"] * 3
    absorb_bid = ctx["bn_absorb_bid"]
    absorb_ask = ctx["bn_absorb_ask"]
    macro_bias = ctx["macro_bias"]
    gs_z = ctx["gs_ratio_z"]

    # ── S1 — Structure UP + OF UP = BREAKOUT LONG ──
    if (poc_dir == 1 and delta_pct > DELTA_THRESHOLD and finish > FINISH_THRESHOLD
            and big_bids >= BIG_TRADER_MIN and not absorb_ask):
        if macro_bias == "BEAR" and ctx["macro_bear_count"] >= 4:
            return None, None, "SKIP_MACRO_BEARISH_OVERRIDE"
        return "LONG", "BREAKOUT", "S1_STRUCT_UP_FLOW_UP"

    # ── S2 — Structure DOWN + OF DOWN = BREAKOUT SHORT ──
    if (poc_dir == -1 and delta_pct < -DELTA_THRESHOLD and finish < -FINISH_THRESHOLD
            and big_asks >= BIG_TRADER_MIN and not absorb_bid):
        if macro_bias == "BULL" and ctx["macro_bull_count"] >= 4:
            return None, None, "SKIP_MACRO_BULLISH_OVERRIDE"
        return "SHORT", "BREAKOUT", "S2_STRUCT_DN_FLOW_DN"

    # ── S3 — Structure faible + OF DOWN = REJECTION SHORT ──
    if (poc_dir >= 0 and abs(poc_speed) < POC_SPEED_WEAK
            and delta_pct < -DELTA_THRESHOLD and finish < -FINISH_THRESHOLD
            and not absorb_bid and big_asks >= BIG_TRADER_MIN):
        return "SHORT", "REJECTION", "S3_WEAK_STRUCT_COUNTER_SHORT"

    # ── S4 — Structure faible + OF UP = REJECTION LONG ──
    if (poc_dir <= 0 and abs(poc_speed) < POC_SPEED_WEAK
            and delta_pct > DELTA_THRESHOLD and finish > FINISH_THRESHOLD
            and not absorb_ask and big_bids >= BIG_TRADER_MIN):
        return "LONG", "REJECTION", "S4_WEAK_STRUCT_COUNTER_LONG"

    # ── S5 — RANGE DAY (poc=0 + va contract) = fade extremes ──
    if poc_dir == 0 and va_dev < VA_CONTRACT:
        pos = ctx["position_in_range"]
        if pos > 0.80 and delta_pct < -DELTA_THRESHOLD:
            return "SHORT", "REJECTION", "S5_RANGE_FADE_HIGH"
        if pos < 0.20 and delta_pct > DELTA_THRESHOLD:
            return "LONG", "REJECTION", "S5_RANGE_FADE_LOW"
        return None, None, "SKIP_RANGE_NO_EXTREME"

    # ── S6 — TREND DAY (poc fast + va expand) = same-direction ──
    if abs(poc_speed) > POC_SPEED_STRONG and va_dev > VA_EXPAND:
        if poc_dir == 1 and delta_pct > DELTA_THRESHOLD:
            return "LONG", "BREAKOUT", "S6_TREND_DAY_LONG"
        if poc_dir == -1 and delta_pct < -DELTA_THRESHOLD:
            return "SHORT", "BREAKOUT", "S6_TREND_DAY_SHORT"
        return None, None, "SKIP_TREND_COUNTER"

    # ── S7 — Gold/Silver Ratio Extreme (Gold-specific, validé edge discovery) ──
    if abs(gs_z) > GS_EXTREME:
        if gs_z > GS_EXTREME and delta_pct < -DELTA_THRESHOLD:
            return "SHORT", "REJECTION", "S7_GS_RATIO_EXTREME_SHORT"
        if gs_z < -GS_EXTREME and delta_pct > DELTA_THRESHOLD:
            return "LONG", "BREAKOUT", "S7_GS_RATIO_EXTREME_LONG"

    # ── S8 — Macro Intermarket Full Alignment ──
    if ctx["macro_bull_count"] >= 4 and delta_pct > DELTA_THRESHOLD:
        return "LONG", "BREAKOUT", "S8_MACRO_FULL_BULL"
    if ctx["macro_bear_count"] >= 4 and delta_pct < -DELTA_THRESHOLD:
        return "SHORT", "BREAKOUT", "S8_MACRO_FULL_BEAR"

    return None, None, "SKIP_NO_CONVERGENCE"


def evaluate_decision_gold(level_name: str, level_def: dict, ctx: dict,
                            dist_signed: float) -> tuple[bool, str, dict]:
    """Top-level decision pour Bot 3 Gold."""
    side, action, reason = resolve_gold_neutral_side(level_def, ctx)
    if side is None:
        return False, reason, {}

    # Confidence
    confidence = 50
    if action == "BREAKOUT": confidence += 10
    if action == "REJECTION": confidence += 5
    # Bonus macro aligné
    if ctx["macro_bias"] == "BULL" and side == "LONG":
        confidence += min(15, ctx["macro_bull_count"] * 3)
    if ctx["macro_bias"] == "BEAR" and side == "SHORT":
        confidence += min(15, ctx["macro_bear_count"] * 3)
    confidence = max(0, min(100, confidence))

    # SL adaptatif ATR
    atr_pct = ctx["atr_14m_pct"]
    atr_baseline = 0.035
    atr_mult = max(0.7, min(1.5, atr_pct / atr_baseline if atr_baseline > 0 else 1.0))
    sl_ticks = int(round(200 * atr_mult))  # base 200 ticks Gold (20 pts)

    return True, "GO", {
        "side": side, "action": action, "confidence": int(confidence),
        "sl_ticks": sl_ticks, "atr_multiplier": round(atr_mult, 3),
        "level_name": level_name, "scenario": reason,
        "macro_bias": ctx["macro_bias"],
    }
