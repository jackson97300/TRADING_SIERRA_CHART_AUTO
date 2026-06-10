"""Bot 3 Gold — Configuration centrale (selon PROMPT_CLAUDE_CODE_BOT3_GOLD).

Guard rails execution + risk management + vetos absolus.
Toute constante magique vit ici (regle V2CLEAN config centralisee).
"""
from __future__ import annotations


# ════════════════════════════════════════════════════════════════════════
# Phase de deploiement
# ════════════════════════════════════════════════════════════════════════
# Phase 1 : OBSERVE-ONLY (1 semaine) — détecte contacts, log decisions, NE TRADE PAS
# Phase 2 : PAPER Tier 1 only (2 semaines)
# Phase 3 : PAPER Full (Tier 1 + 2)
# Phase 4 : Compare ML vs Rules
BOT3G_OBSERVE_ONLY = True               # Phase 1 init = OBSERVE only
BOT3G_ENABLE_TIER2 = False              # Phase 2 active Tier 1 seul
BOT3G_ENABLE_HEDGE_CROSS_ASSET = False  # Phase 3 active hedge


# ════════════════════════════════════════════════════════════════════════
# Connexion DTC — Sim1 (Bot 3 MGC partage compte Bot 3 ES/NQ)
# ════════════════════════════════════════════════════════════════════════
# Mapping bots (Jackson 12/05/2026 DEFINITIF) :
#   Bot 1 ES/NQ/MGC (DMP + ML LightGBM)   = Sim3
#   Bot 2 ES/NQ/MGC (SetupEngine V6)      = Sim2
#   Bot 3 ES/NQ/MGC (Levels + Rules Gold) = Sim1
# Bot 3 Gold tourne dans le meme process que Bot 3 MP (databento_paper_trader_v2)
# → meme compte Sim1, meme DTC connector, meme recv_loop OCO routing.
TRADE_ACCOUNT_BOT3G = "Sim1"


# ════════════════════════════════════════════════════════════════════════
# Garde-fous execution (cf prompt PROMPT_CLAUDE_CODE_BOT3_GOLD)
# ════════════════════════════════════════════════════════════════════════
GUARD_RAILS_GOLD: dict[str, dict] = {
    "MGC": {
        "n_contracts": 3,                 # 3 MNQ-équiv. = $3/tick Gold
        "sl_ticks_base": 200,             # 20 pts Gold = $200 (1 MGC) / $600 (3 MGC)
        "trailing_activation": 80,        # +8 pts Gold pour armer trailing
        "trailing_distance": 50,          # trail à 5 pts du best
        "timeout_minutes": 60,
        "tp_cap_ticks": 400,              # 40 pts Gold cap absolu (R/R max 2)
        "tick_value": 1.00,               # $1/tick MGC
        "tick_size": 0.10,                # tick Gold
    },
}


# ════════════════════════════════════════════════════════════════════════
# Risk management — Gold dedie
# ════════════════════════════════════════════════════════════════════════
RISK_GOLD: dict[str, dict] = {
    "MGC": {
        "max_trades_per_day": 3,          # cap data quality
        "max_losses_per_day": 2,          # circuit breaker
        "kill_switch_daily_pnl": -600.0,  # 2 × $300 max loss/jour
        "position_size": 3,               # 3 micros
    },
}


# ════════════════════════════════════════════════════════════════════════
# ATR baseline Gold (calcul SL adaptatif)
# ════════════════════════════════════════════════════════════════════════
ATR_BASELINE_GOLD = 0.035              # atr_14m_pct median Gold (~3.5%)
ATR_CLAMP_GOLD = (0.7, 1.5)            # clamp ratio atr_current / baseline


# ════════════════════════════════════════════════════════════════════════
# VETOS ABSOLUS GOLD
# ════════════════════════════════════════════════════════════════════════
# Documentation des vetos appliqués dans bot3_gold_decision_engine.py
GOLD_VETOS_DESC = {
    "ROLL_DAY":       "is_roll_day == 1",
    "NEWS_IMMINENT":  "within_news_830_5m or within_news_930_5m == 1",
    "NEWS_JUST_HIT":  "mins_since_news < 3",
    "VOLUME_MORT":    "rvol < 0.3",
    "LONDON_FIX":     "london_fix_window_10_30 or london_fix_window_15_00 == 1",
    "NOT_RTH":        "is_in_us_cash != 1 (Phase 1-3 : RTH only)",
}


# ════════════════════════════════════════════════════════════════════════
# Niveaux activés par phase
# ════════════════════════════════════════════════════════════════════════
# Phase 2 = Tier 1 seulement (haute fiabilité validée edge discovery)
GOLD_TIER1_LEVELS = [
    "MQ_CALL_0DTE", "MQ_PUT_0DTE", "MQ_HVL_0DTE",  # Gold-specific 0DTE
    "SINGLE_PRINT", "IB_LOW", "IB_HIGH",            # MP standard Tier 1
    "CUR_VPOC", "OPEN_830", "VWAP_D",
]

# Phase 3 = Tier 1 + Tier 2 (Blind spots, sessions, VWAP SD, etc.)


# ════════════════════════════════════════════════════════════════════════
# Logging
# ════════════════════════════════════════════════════════════════════════
LOG_CATEGORY_BOT3G = "bot3_gold"  # nouvelle catégorie LOGS/bot3_gold/
SNAPSHOT_BAR_BY_BAR = True
SNAPSHOT_MAX_BARS = 60  # = timeout_minutes
