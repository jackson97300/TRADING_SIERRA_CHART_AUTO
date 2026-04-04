// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Globals.h - Variables globales et forward declarations
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 626-700)
// Date refactoring: 31/01/2026
// 🆕 14/03/2026: Ajout SessionPlan, Asia IB, per-session tracking
// ═══════════════════════════════════════════════════════════════════════════════

#pragma once

#include "MIA_Config.h"
#include "MIA_SessionPlan.h"  // 🆕 14/03/2026: Session Planner

// ═══════════════════════════════════════════════════════════════════════════════
// DONNÉES MARCHÉ LIVE
// ═══════════════════════════════════════════════════════════════════════════════

struct MarketLiveData {
    float vix;
    float atr_es;
    float atr_nq;
    float vwap_slope_es;
    float vwap_slope_nq;
    int vix_regime;      // 0=CALM, 1=NORMAL, 2=VOLATILE
    bool vix_valid;
    bool atr_valid;
};

inline MarketLiveData g_market_live = {20.0f, 0.0f, 0.0f, 0, 0, 1, false, false};
// 🆕 14/03: ATR defaults à 0 (pas 15/350) — sera calculé live

// ═══════════════════════════════════════════════════════════════════════════════
// VARIABLES GLOBALES PERSISTANTES
// ═══════════════════════════════════════════════════════════════════════════════

inline BotState g_es_state;
inline BotState g_nq_state;
inline DashboardData g_dashboard;
inline std::vector<TradeSnapshot> g_trade_history;

// Trade ID unique (pour journal WHY)
inline int g_trade_why_id = 1;

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 14/03/2026: SESSION PLANNER — Variables persistantes
// ═══════════════════════════════════════════════════════════════════════════════
// Plans de session (recalculés quand la phase change)
inline SessionPlan g_session_plan_es;
inline SessionPlan g_session_plan_nq;

// Asia IB partagée (ES et NQ voient le même range asiatique)
inline IBRange g_asia_ib;

// Phase courante (pour détecter les changements)
inline SessionPhase g_last_phase_es = PHASE_UNKNOWN;
inline SessionPhase g_last_phase_nq = PHASE_UNKNOWN;

// Trades par session (reset quand la phase change)
inline int g_trades_london_es  = 0;
inline int g_trades_london_nq  = 0;
inline int g_trades_us_es      = 0;
inline int g_trades_us_nq      = 0;

// ═══════════════════════════════════════════════════════════════════════════════
// FORWARD DECLARATIONS
// ═══════════════════════════════════════════════════════════════════════════════

void NotifyDiscordTradeOpened(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config, float bn_score, float vwap_slope);
void NotifyDiscordTradeClosed(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config);

// ═══════════════════════════════════════════════════════════════════════════════
// FIN MIA_Globals.h
// ═══════════════════════════════════════════════════════════════════════════════
