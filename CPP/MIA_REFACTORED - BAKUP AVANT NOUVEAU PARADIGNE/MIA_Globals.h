// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Globals.h - Variables globales et forward declarations
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 626-700)
// Date refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#pragma once

#include "MIA_Config.h"

// ═══════════════════════════════════════════════════════════════════════════════
// DONNÉES MARCHÉ LIVE
// ═══════════════════════════════════════════════════════════════════════════════
// 🔧 28/02/2026: Déplacé depuis MIA_Indicators.h → MIA_Globals.h
//    Raison: 7 modules utilisaient g_market_live via Indicators.h de manière
//    implicite. MIA_DataDumper.h n'incluant que MIA_Config.h, l'accès à
//    g_market_live était undefined si l'ordre des includes changeait.
//    Désormais déclaré ici, accessible à tout module incluant MIA_Globals.h.

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

inline MarketLiveData g_market_live = {20.0f, 15.0f, 350.0f, 0, 0, 1, false, false};

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
// FORWARD DECLARATIONS
// ═══════════════════════════════════════════════════════════════════════════════

void NotifyDiscordTradeOpened(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config, float bn_score, float vwap_slope);
void NotifyDiscordTradeClosed(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config);

// ═══════════════════════════════════════════════════════════════════════════════
// FIN MIA_Globals.h
// ═══════════════════════════════════════════════════════════════════════════════
