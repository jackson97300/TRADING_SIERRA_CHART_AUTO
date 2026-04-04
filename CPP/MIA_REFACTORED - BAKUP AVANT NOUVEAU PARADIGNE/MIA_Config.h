// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Config.h - Configuration et Structures de données
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 122-625)
// Date refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#pragma once

#include "sierrachart.h"
#include <string>
#include <vector>
#include <algorithm>
#include <fstream>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <map>

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1: CONFIGURATION ET CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// --- VERSION ET BUILD ---
// 🆕 31/01/2026: Versioning des schémas JSON pour compatibilité Python/C++
inline const char* MIA_SCHEMA_VERSION = "2.1.0";
inline const char* MIA_BUILD_DATE = "2026-01-31";
inline const char* MIA_BUILD_REFACTORED = "v1.2-REFACTORED";

// --- SYMBOLES ---
enum SymbolType { SYM_ES = 0, SYM_NQ = 1 };

// --- CAPITAL DE RÉFÉRENCE (Position Sizing / Drawdown) ---
// 01/03/2026: Externalisé depuis MIA_Main.cpp (était hardcodé 10000.0f)
inline const float ACCOUNT_CAPITAL_BASE = 10000.0f;

// --- CONFIGURATION PAR SYMBOLE ---
struct SymbolConfig {
    const char* name;
    float tick_size;
    float tick_value;

    // SL/TP
    int sl_default_ticks;
    int sl_min_ticks;
    int sl_max_ticks;
    int sl_buffer_ticks;
    int tp_default_ticks;
    int tp_max_ticks;
    int tp_buffer_ticks;
    float min_rr_ratio;

    // Trailing
    int trailing_activation_ticks;
    int trailing_distance_ticks;

    // Break-Even Auto
    int break_even_activation_ticks;
    int break_even_buffer_ticks;

    // Cooldown
    int max_consecutive_losses;
    int cooldown_after_losses_min;
    int cooldown_win_min;
    int cooldown_loss_min;

    // Détection annonces
    int spread_alert_ticks;
    int dom_min_depth;

    // Layers
    float l2_bn_score_min_long;
    float l2_bn_score_max_short;
    float l4_combo_required;
};

inline const SymbolConfig CONFIG_ES = {
    "ES",
    0.25f,      // tick_size
    1.25f,      // tick_value = MICRO MES (était 12.50f pour Mini ES)

    // SL/TP
    20,         // sl_default_ticks (5 pts)
    16,         // sl_min_ticks (4 pts)
    28,         // sl_max_ticks (7 pts)
    3,          // sl_buffer_ticks
    24,         // tp_default_ticks (6 pts)
    32,         // tp_max_ticks (8 pts)
    2,          // tp_buffer_ticks
    1.20f,      // min_rr_ratio

    // TRAILING
    15,         // trailing_activation_ticks
    8,          // trailing_distance_ticks

    // BREAK-EVEN
    10,         // break_even_activation_ticks
    1,          // break_even_buffer_ticks

    // COOLDOWN
    3,          // max_consecutive_losses
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min

    // ANNONCES
    4,          // spread_alert_ticks
    30,         // dom_min_depth

    // LAYERS
    -0.05f,     // l2_bn_score_min_long
    0.05f,      // l2_bn_score_max_short
    1           // l4_combo_required (🆕 01/02/2026: ACTIVÉ - Score Qualité)
};

inline const SymbolConfig CONFIG_NQ = {
    "NQ",
    0.25f,      // tick_size
    0.50f,      // tick_value = MICRO MNQ (était 5.00f pour Mini NQ)

    // SL/TP
    28,         // sl_default_ticks (7 pts)
    20,         // sl_min_ticks (5 pts)
    40,         // sl_max_ticks (10 pts)
    5,          // sl_buffer_ticks
    35,         // tp_default_ticks (8.75 pts)
    50,         // tp_max_ticks (12.5 pts)
    3,          // tp_buffer_ticks
    1.25f,      // min_rr_ratio

    // TRAILING (🔧 01/02/2026: Ajusté pour volatilité NQ)
    35,         // trailing_activation_ticks (était 25 - trop tôt pour NQ volatile)
    12,         // trailing_distance_ticks

    // BREAK-EVEN
    15,         // break_even_activation_ticks
    2,          // break_even_buffer_ticks

    // COOLDOWN (🔧 01/02/2026: Uniformisé avec ES)
    3,          // max_consecutive_losses (était 4 - NQ volatile = plus conservateur)
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min

    // ANNONCES
    8,          // spread_alert_ticks
    30,         // dom_min_depth

    // LAYERS
    -0.05f,     // l2_bn_score_min_long
    0.05f,      // l2_bn_score_max_short
    1           // l4_combo_required (🆕 01/02/2026: ACTIVÉ - Score Qualité)
};

// --- SESSIONS ---
inline const int SESSION_START_ET = 18 * 60;
inline const int SESSION_END_ET = 15 * 60;
inline const int US_OPEN_ET = 9 * 60 + 30;
inline const int US_OPR_END_ET = 9 * 60 + 45;
inline const int PRE_US_PAUSE_START_ET = 9 * 60;
inline const int TEST_SESSION_START_ET = 18 * 60;
inline const int TEST_SESSION_END_ET = 17 * 60;

// --- MODES ---
enum BotMode { MODE_PRODUCTION = 0, MODE_TEST = 1 };

// --- TIMEOUTS ---
inline const int ORDER_TIMEOUT_SECONDS = 15;
inline const int LIMIT_ORDER_TIMEOUT_SECONDS = 90;
inline const int NEWS_BLOCK_MINUTES = 30;

// --- MODE PRODUCTION vs TEST ---
// 🆕 31/01/2026: Mettre à false pour DÉSACTIVER le circuit breaker en test
// ⚠️ IMPORTANT: Passer à TRUE avant de trader en réel!
inline const bool CIRCUIT_BREAKER_ENABLED = true;  // true = PRODUCTION, false = TEST (illimité)

// --- CIRCUIT BREAKER (Protection max loss/jour) - PRODUCTION SEULEMENT ---
// Ces seuils ne s'appliquent QUE si CIRCUIT_BREAKER_ENABLED = true
// 🔧 01/02/2026: Compromis pour MICRO avec Position Sizing Dynamique
// - Grade A: 5 MES × 20 ticks × $1.25 = $125/trade → $500 = ~4 trades
// - Grade A: 3 MNQ × 28 ticks × $0.50 = $42/trade → $500 = ~12 trades
// - En TEST: Mettre CIRCUIT_BREAKER_ENABLED = false → ILLIMITÉ
inline const float MAX_DAILY_LOSS_ES = -500.0f;    // Max perte ES par jour ($) - COMPROMIS
inline const float MAX_DAILY_LOSS_NQ = -500.0f;    // Max perte NQ par jour ($) - COMPROMIS
inline const float MAX_DAILY_LOSS_TOTAL = -1000.0f; // Max perte combinée ($) - COMPROMIS
inline const int MAX_CONSECUTIVE_LOSSES = 3;        // Max pertes consécutives avant pause
inline const float CIRCUIT_BREAKER_COOLDOWN_HOURS = 2.0f;  // Heures de pause après circuit breaker

// --- POSITION SIZING DYNAMIQUE (MICRO) ---
// 🆕 01/02/2026: Game Changer #1 - Taille position selon qualité du setup
inline const int BASE_QTY_MES = 3;      // Base: 3 Micro ES ($1.25/tick × 3 = $3.75/tick)
inline const int BASE_QTY_MNQ = 2;      // Base: 2 Micro NQ ($0.50/tick × 2 = $1.00/tick)

// Fonction de Position Sizing Dynamique
// Ajuste la quantité selon: Grade L4 + VIX + Drawdown
inline int CalculatePositionSize(bool is_nq, char grade, int vix_regime, float drawdown_pct) {
    // Base selon symbole
    int base = is_nq ? BASE_QTY_MNQ : BASE_QTY_MES;
    float multiplier = 1.0f;
    
    // 1. AJUSTEMENT PAR GRADE L4 (le plus important!)
    switch (grade) {
        case 'A':
            multiplier = 1.5f;   // Grade A = +50% (setup excellent)
            break;
        case 'B':
            multiplier = 1.0f;   // Grade B = normal
            break;
        case 'C':
            multiplier = 0.75f;  // Grade C = -25% (setup moyen)
            break;
        case 'D':
            return 0;            // Grade D = PAS DE TRADE!
    }
    
    // 2. AJUSTEMENT PAR VIX (volatilité marché)
    if (vix_regime >= 2) {
        // VIX VOLATILE (>25) = réduire 50%
        multiplier *= 0.5f;
    } else if (vix_regime == 0) {
        // VIX CALM (<15) = légèrement augmenter
        multiplier *= 1.1f;
    }
    
    // 3. AJUSTEMENT PAR DRAWDOWN (protection capital)
    if (drawdown_pct > 0.08f) {
        // DD > 8% = réduire 75%
        multiplier *= 0.25f;
    } else if (drawdown_pct > 0.05f) {
        // DD 5-8% = réduire 50%
        multiplier *= 0.5f;
    } else if (drawdown_pct > 0.03f) {
        // DD 3-5% = réduire 25%
        multiplier *= 0.75f;
    }
    
    // Calcul final (minimum 1 contrat)
    int final_qty = (int)(base * multiplier);
    if (final_qty < 1) final_qty = 1;
    
    // Maximum: 2x base (pour éviter sur-leverage)
    int max_qty = base * 2;
    if (final_qty > max_qty) final_qty = max_qty;
    
    return final_qty;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 RÉGIME DE MARCHÉ MULTI-FACTEURS (01/02/2026)
// Système PRO: Score composite pour détecter TREND vs RANGE
// Utilise: VWAP Slope + ATR + VIX + CVD + Structure
// ═══════════════════════════════════════════════════════════════════════════════

enum MarketRegime {
    REGIME_STRONG_TREND = 0,  // Score 75-100: Trending fort
    REGIME_TREND = 1,         // Score 55-74: Trending normal
    REGIME_WEAK = 2,          // Score 40-54: Faible/Transition
    REGIME_RANGE = 3          // Score 0-39: Range/Consolidation
};

struct RegimeResult {
    MarketRegime regime;
    float score;              // 0-100
    float size_multiplier;    // Ajustement taille
    float tp_multiplier;      // Ajustement TP
    bool trailing_enabled;    // Trailing ON/OFF
    char description[64];
};

// Fonction principale: Calcul du Régime Multi-Facteurs
inline RegimeResult CalculateMarketRegime(
    float vwap_slope,      // VWAP slope du symbole
    float atr,             // ATR actuel
    float atr_avg,         // ATR moyenne (20 périodes) - approximation: atr * 0.85
    int vix_regime,        // 0=CALM, 1=NORMAL, 2=VOLATILE
    float cvd_slope,       // CVD slope (ou fpbs_delta comme proxy)
    float swing_high,      // Dernier swing high
    float swing_low,       // Dernier swing low
    float current_price,   // Prix actuel
    bool is_nq             // 🆕 01/02/2026: true = NQ (seuils adaptés), false = ES
) {
    RegimeResult result = {REGIME_WEAK, 50.0f, 1.0f, 1.0f, true, ""};
    float score = 0.0f;
    
    // ═══════════════════════════════════════════════════════════════════════
    // FACTEUR 1: VWAP SLOPE (30 pts max)
    // 🆕 Seuils adaptés: NQ ~2x plus volatile que ES
    // ═══════════════════════════════════════════════════════════════════════
    float vwap_abs = fabs(vwap_slope);
    float vwap_score = 0.0f;
    
    // 🆕 Seuils adaptés: NQ ~2x plus volatile → seuils plus bas
    float thresh_strong = is_nq ? 0.035f : 0.05f;   // NQ: 0.035, ES: 0.05
    float thresh_med    = is_nq ? 0.02f  : 0.03f;   // NQ: 0.02, ES: 0.03
    float thresh_weak   = is_nq ? 0.01f  : 0.015f;  // NQ: 0.01, ES: 0.015
    float thresh_flat   = is_nq ? 0.004f : 0.005f;  // NQ: 0.004, ES: 0.005
    
    if (vwap_abs > thresh_strong) {
        vwap_score = 30.0f;  // Fort trending
    } else if (vwap_abs > thresh_med) {
        vwap_score = 25.0f;  // Trending modéré
    } else if (vwap_abs > thresh_weak) {
        vwap_score = 18.0f;  // Légèrement trending
    } else if (vwap_abs > thresh_flat) {
        vwap_score = 10.0f;  // Quasi-flat
    } else {
        vwap_score = 5.0f;   // Range total
    }
    score += vwap_score;
    
    // ═══════════════════════════════════════════════════════════════════════
    // FACTEUR 2: VOLATILITÉ ATR (25 pts max)
    // ATR élevé = mouvement, ATR faible = range
    // ═══════════════════════════════════════════════════════════════════════
    float atr_ratio = (atr_avg > 0) ? (atr / atr_avg) : 1.0f;
    float atr_score = 0.0f;
    if (atr_ratio > 1.3f) {
        atr_score = 25.0f;   // Expansion volatilité = trending
    } else if (atr_ratio > 1.1f) {
        atr_score = 20.0f;
    } else if (atr_ratio > 0.9f) {
        atr_score = 15.0f;   // Normal
    } else if (atr_ratio > 0.7f) {
        atr_score = 10.0f;   // Contraction = range probable
    } else {
        atr_score = 5.0f;    // Très calme = range
    }
    score += atr_score;
    
    // ═══════════════════════════════════════════════════════════════════════
    // FACTEUR 3: VIX CONTEXT (20 pts max)
    // VIX modéré = bon pour trending, extrêmes = mauvais
    // ═══════════════════════════════════════════════════════════════════════
    float vix_score = 0.0f;
    if (vix_regime == 1) {        // NORMAL (15-25)
        vix_score = 20.0f;        // Optimal pour trending
    } else if (vix_regime == 0) { // CALM (<15)
        vix_score = 12.0f;        // Peut être range ou trending calme
    } else {                       // VOLATILE (>25)
        vix_score = 8.0f;         // Volatilité extrême = moins prévisible
    }
    score += vix_score;
    
    // ═══════════════════════════════════════════════════════════════════════
    // FACTEUR 4: MOMENTUM CVD/DELTA (15 pts max)
    // CVD en hausse/baisse forte = trending
    // ═══════════════════════════════════════════════════════════════════════
    // 🔴 CORRIGÉ 01/02/2026: cvd_slope est en CENTAINES (100-500), pas en décimales!
    // ═══════════════════════════════════════════════════════════════════════
    float cvd_abs = fabs(cvd_slope);
    float cvd_score = 0.0f;
    if (cvd_abs > 500.0f) {        // Fort momentum (était 0.5f - FAUX!)
        cvd_score = 15.0f;
    } else if (cvd_abs > 300.0f) { // Momentum modéré-fort (était 0.3f)
        cvd_score = 12.0f;
    } else if (cvd_abs > 100.0f) { // Momentum faible (était 0.1f)
        cvd_score = 8.0f;
    } else {
        cvd_score = 4.0f;          // Pas de momentum = range
    }
    score += cvd_score;
    
    // ═══════════════════════════════════════════════════════════════════════
    // FACTEUR 5: STRUCTURE SWING (10 pts max)
    // Prix proche des extrêmes = trending, au milieu = range
    // ═══════════════════════════════════════════════════════════════════════
    float structure_score = 0.0f;
    if (swing_high > 0 && swing_low > 0 && swing_high > swing_low) {
        float range = swing_high - swing_low;
        float position = (current_price - swing_low) / range;  // 0-1
        
        // Proche des extrêmes (>0.8 ou <0.2) = potentiel breakout/continuation
        if (position > 0.85f || position < 0.15f) {
            structure_score = 10.0f;  // Près des extrêmes = trending probable
        } else if (position > 0.7f || position < 0.3f) {
            structure_score = 7.0f;
        } else {
            structure_score = 4.0f;   // Au milieu = range
        }
    } else {
        structure_score = 5.0f;  // Pas assez de data
    }
    score += structure_score;
    
    // ═══════════════════════════════════════════════════════════════════════
    // CLASSIFICATION DU RÉGIME
    // ═══════════════════════════════════════════════════════════════════════
    result.score = score;
    
    if (score >= 75.0f) {
        result.regime = REGIME_STRONG_TREND;
        result.size_multiplier = 1.3f;    // +30% size
        result.tp_multiplier = 1.4f;      // +40% TP
        result.trailing_enabled = true;
        snprintf(result.description, sizeof(result.description), 
                 "STRONG_TREND (%.0f): Size+30%% TP+40%%", score);
    } else if (score >= 55.0f) {
        result.regime = REGIME_TREND;
        result.size_multiplier = 1.0f;    // Normal
        result.tp_multiplier = 1.0f;      // Normal
        result.trailing_enabled = true;
        snprintf(result.description, sizeof(result.description), 
                 "TREND (%.0f): Normal", score);
    } else if (score >= 40.0f) {
        result.regime = REGIME_WEAK;
        result.size_multiplier = 0.75f;   // -25% size
        result.tp_multiplier = 0.85f;     // -15% TP
        result.trailing_enabled = true;   // Trailing prudent
        snprintf(result.description, sizeof(result.description), 
                 "WEAK (%.0f): Size-25%% TP-15%%", score);
    } else {
        result.regime = REGIME_RANGE;
        result.size_multiplier = 0.5f;    // -50% size
        result.tp_multiplier = 0.7f;      // -30% TP
        result.trailing_enabled = false;  // PAS de trailing en range!
        snprintf(result.description, sizeof(result.description), 
                 "RANGE (%.0f): Size-50%% TP-30%% NoTrail", score);
    }
    
    return result;
}

// Helper: Nom du régime
inline const char* GetRegimeName(MarketRegime regime) {
    switch (regime) {
        case REGIME_STRONG_TREND: return "STRONG_TREND";
        case REGIME_TREND: return "TREND";
        case REGIME_WEAK: return "WEAK";
        case REGIME_RANGE: return "RANGE";
        default: return "UNKNOWN";
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2: STRUCTURES DE DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════

// --- ÉTAT DU BOT PAR SYMBOLE ---
struct BotState {
    bool enabled;
    bool paused;
    bool in_position;
    int position_direction;
    int direction;              // Alias pour position_direction (compatibilité)

    // Ordres
    int parent_order_id;
    int sl_order_id;
    int tp_order_id;
    SCDateTime order_sent_time;
    bool pending_limit_order;

    // Position
    float entry_price;
    float sl_price;
    float tp_price;
    float trailing_sl;
    bool trailing_activated;
    bool trailing_allowed;       // 🆕 01/02/2026: Contrôlé par le régime (false en RANGE)
    bool break_even_activated;
    SCDateTime entry_time;
    SCDateTime last_trade_time; // Heure du dernier trade

    // Stats journalieres
    int trades_today;
    int wins_today;
    int losses_today;
    float pnl_today;
    float best_trade;
    float worst_trade;
    int consecutive_losses;
    float last_processed_pnl;

    // Cooldown
    SCDateTime cooldown_until;
    SCDateTime news_block_until;
    
    // 🆕 Circuit Breaker (31/01/2026)
    bool circuit_breaker_active;      // True si max loss atteint
    SCDateTime circuit_breaker_until; // Quand le circuit breaker expire
    char circuit_breaker_reason[128]; // Raison du déclenchement

    // Status message
    char status_message[256];
    char waiting_for[256];

    // Dernier signal
    int last_signal_direction;
    float last_signal_confidence;
    char last_signal_reason[512];
    char last_reject_reason[256]; // Raison du dernier rejet

    // Discord
    float discord_bn_score;
    float discord_l1_conf;
    float discord_l2_conf;
    float discord_l3_conf;
    int discord_l4_combo;
    float discord_vwap_slope;
    bool discord_is_rectangle;
};

// --- DONNÉES BATAILLE NAVALE ---
struct BN_Data {
    // SIGNAUX FOOTPRINT
    float edge_buy;
    float edge_sell;
    float color_up;
    float color_down;
    float absorb_ask;
    float absorb_bid;
    float double_ask;
    float double_bid;
    float triple_ask;
    float triple_bid;
    float rotation_up;
    float rotation_down;
    float volume_up;
    float volume_down;

    // GROS ORDRES
    float ask_100;
    float bid_100;
    float ask_150;
    float bid_150;
    float ask_400;
    float bid_400;
    float ask_1000;
    float bid_1000;
    float cluster_vol;

    // SIGNAUX BARRES
    float long_down_up;
    float long_up_down;
    float bar_color_up;
    float bar_color_down;
    float bar_edge_buy;
    float bar_edge_sell;

    // FPBS
    float fpbs_ask_pct;
    float fpbs_bid_pct;
    float fpbs_delta;
    float fpbs_delta_day;
    float fpbs_cvd;
    float fpbs_poc;
    
    // CVD & POC ANALYSIS
    float prev_cvd;
    float cvd_slope;
    int poc_confirm;
    bool cvd_divergence;
    float cvd_trend_score;
    
    // NQ ORDRES GRANULAIRES
    float ask_10;
    float bid_10;
    float ask_30;
    float bid_30;

    // SCORES CALCULÉS
    float score;                    // Score BN global (-1 à +1) - PRINCIPAL
    float signal;                   // ⚠️ DEPRECATED: Utiliser score directement (signal = sign(score))
    float momentum_score;           // Score momentum global (-1 à +1) - UTILISÉ L3
    float reversal_score;
    float institutional_pressure;

    // MOMENTUM DELTA
    float prev_color_up;
    float prev_color_down;
    float color_momentum;           // ⚠️ INTERMÉDIAIRE: Sert à calculer momentum_shift
    float momentum_shift;           // Changement de momentum - UTILISÉ L2

    // RECTANGLES FRAIS
    float prev_double_bid;
    float prev_double_ask;
    bool fresh_rectangle_buy;
    bool fresh_rectangle_sell;
    int fresh_rect_age_bars;

    // EDGE ZONE RATIO
    float edge_ratio;
    bool edge_dominant_buy;
    bool edge_dominant_sell;

    // EXTENSION LINES
    float ext_lines_support[10];
    float ext_lines_resist[10];
    int num_ext_support;
    int num_ext_resist;
    float nearest_ext_support;
    float nearest_ext_resist;
    float dist_nearest_support_ticks;  // Distance au support le plus proche en ticks
    float dist_nearest_resist_ticks;   // Distance à la résistance la plus proche en ticks

    // RECTANGLES TRADABLES
    float long_up_bar_ext[10];
    float long_down_bar_ext[10];
    int num_long_up_bar;
    int num_long_down_bar;
    float nearest_long_up_bar;
    float nearest_long_down_bar;
    bool has_tradable_support;
    bool has_tradable_resist;

    // EDGE ZONE RECTANGLES
    float edge_rect_buy_bottom[5];
    float edge_rect_buy_top[5];
    float edge_rect_sell_bottom[5];
    float edge_rect_sell_top[5];
    int num_edge_rect_buy;
    int num_edge_rect_sell;
    float nearest_edge_rect_support;
    float nearest_edge_rect_resist;
    bool price_in_edge_rect_buy;
    bool price_in_edge_rect_sell;

    // BATAILLE NAVALE AVANCÉE
    float lowest_edge_buy;
    float highest_edge_sell;
    bool bn_attack_long_valid;
    bool bn_attack_short_valid;
    int stacked_buy_zones;
    int stacked_sell_zones;
    float attack_strength_buy;
    float attack_strength_sell;
    bool all_signals_bullish;
    bool all_signals_bearish;
    float directional_coherence;
    
    // BOULES INDIVIDUELLES (COLOR UP/DOWN)
    float color_up_prices[20];
    float color_down_prices[20];
    int num_color_up_prices;
    int num_color_down_prices;
    float green_base_price;
    float red_base_price;
    bool bn_subtile_long_valid;
    bool bn_subtile_short_valid;
    char subtile_long_reason[64];
    char subtile_short_reason[64];
    
    // MODE RANGE
    bool is_range;
    float range_support;
    float range_resistance;
    float range_midpoint;
    float range_size_pts;
    float price_position_pct;
    int price_position;
    
    // CHAMPS ADDITIONNELS POUR COMPATIBILITÉ
    float long_up_bar;           // Alias pour nearest_long_up_bar
    float long_down_bar;         // Alias pour nearest_long_down_bar
    float buyer_strength;        // Force des acheteurs
    float seller_strength;       // Force des vendeurs
    int num_rect_buy;            // Nombre de rectangles BUY
    int num_rect_sell;           // Nombre de rectangles SELL
    float rect_buy_price;        // Prix rectangle BUY
    float rect_sell_price;       // Prix rectangle SELL
    
    // 🔧 01/02/2026: Champs manquants ajoutés
    float vwap;                  // VWAP depuis chart barres
    int direction;               // Direction calculée: 1=BUY, -1=SELL, 0=NEUTRAL
    float buy_pct;               // Alias pour fpbs_bid_pct (compatibilité)
    float sell_pct;              // Alias pour fpbs_ask_pct (compatibilité)
    
    // 🆕 31/01/2026: DELTA DIVERGENCE (Chart 26/27)
    // Signal de retournement basé sur divergence prix/delta
    bool delta_div_buy;          // Divergence bullish détectée (prix down + delta up)
    bool delta_div_sell;         // Divergence bearish détectée (prix up + delta down)
    float delta_div_strength;    // Force de la divergence (0-1)
    
    // 🆕 31/01/2026: SWING STRUCTURE + SINGLE PRINTS (Chart 28/29)
    // Points pivots de structure et zones de faiblesse (creux volume)
    float swing_high;            // Dernier Swing High détecté
    float swing_low;             // Dernier Swing Low détecté
    bool delta_bar_bullish;      // Barre actuelle: delta positif (acheteurs > vendeurs)
    bool delta_bar_bearish;      // Barre actuelle: delta négatif (vendeurs > acheteurs)
    float single_print_high;     // Niveau haut du Single Print le plus proche
    float single_print_low;      // Niveau bas du Single Print le plus proche
    bool near_single_print;      // Prix proche d'une zone Single Print (creux)
    
    // 🆕 01/02/2026: SESSION OHLC (Study 29)
    float session_open;          // Open de la session
    float session_high;          // High de la session
    float session_low;           // Low de la session
    float session_close;         // Close de la session (= prix actuel)
    float dist_session_high_ticks;  // Distance au High de session en ticks
    float dist_session_low_ticks;   // Distance au Low de session en ticks
    
    // 🆕 01/02/2026: SESSION VOLUME PROFILE (Study 35)
    float session_vpoc;          // VPOC de la session
    float session_vah;           // VAH de la session
    float session_val;           // VAL de la session
    float session_vwap_vp;       // VWAP du Volume Profile session
    float session_hvn;           // HVN de la session (High Volume Node)
    float session_lvn;           // LVN de la session (Low Volume Node)
    
    // 🆕 01/02/2026: VWAP + STANDARD DEVIATIONS (Study 20)
    float vwap_sd1_up;           // VWAP + 1 SD
    float vwap_sd1_dn;           // VWAP - 1 SD
    float vwap_sd2_up;           // VWAP + 2 SD
    float vwap_sd2_dn;           // VWAP - 2 SD
    
    // 🆕 30/01/2026: TOUS les LVN (Low Volume Nodes) du Volume Profile
    float lvn_levels[10];        // Tous les niveaux LVN (creux) du Volume Profile
    int num_lvn;                 // Nombre de LVN valides (>0)
    float nearest_lvn_above;     // LVN le plus proche au-dessus du prix
    float nearest_lvn_below;     // LVN le plus proche en-dessous du prix
    
    float session_poc;           // POC de la session (alias pour compatibilité)
    
    // 🆕 DISTANCES aux LVN/POC (comme GEX/Blind)
    float dist_single_print_ticks;  // Distance au Single Print le plus proche (LVN)
    float dist_lvn_above_ticks;     // Distance au LVN le plus proche au-dessus
    float dist_lvn_below_ticks;     // Distance au LVN le plus proche en-dessous
    float dist_session_poc_ticks;   // Distance au POC de session
    float dist_session_vah_ticks;   // Distance à la VAH
    float dist_session_val_ticks;   // Distance à la VAL
};

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 01/02/2026: COMPOSITE PROFILES MULTI-PÉRIODES (Charts 30/31)
// ═══════════════════════════════════════════════════════════════════════════════
// Données collectées des 5 COMPOSITE PROFILES (1j, 20j, 50j, 100j, 200j)
// Charts: ES = 31, NQ = 30

// Constantes pour les COMPOSITE PROFILES (study_id identiques ES & NQ)
inline const int CP_STUDY_1D   = 34;  // 1 jour (Jaune)
inline const int CP_STUDY_20D  = 2;   // 20 jours (Orange)
inline const int CP_STUDY_50D  = 3;   // 50 jours (Violet)
inline const int CP_STUDY_100D = 4;   // 100 jours (Bleu)
inline const int CP_STUDY_200D = 5;   // 200 jours (Gris)

// Subgraphs des COMPOSITE PROFILES
inline const int CP_SG_VPOC = 1;   // Point of Control
inline const int CP_SG_VAH  = 2;   // Value Area High
inline const int CP_SG_VAL  = 3;   // Value Area Low
inline const int CP_SG_VWAP = 4;   // Volume Weighted Average Price
inline const int CP_SG_HVN  = 17;  // High Volume Node
inline const int CP_SG_LVN  = 18;  // Low Volume Node

// Structure pour UN SEUL profile (une période)
struct SingleProfile {
    int period_days;        // 1, 20, 50, 100, 200
    float vpoc;             // Point of Control
    float vah;              // Value Area High
    float val;              // Value Area Low
    float vwap;             // VWAP du profile
    float hvn;              // High Volume Node le plus proche
    float lvn;              // Low Volume Node le plus proche
    bool valid;             // Données valides?
    
    // Distances en ticks par rapport au prix actuel
    float dist_vpoc_ticks;
    float dist_vah_ticks;
    float dist_val_ticks;
    float dist_hvn_ticks;
    float dist_lvn_ticks;
};

// Structure pour TOUS les profiles (5 périodes)
struct CompositeProfile_Data {
    SingleProfile p1d;      // Profile 1 jour
    SingleProfile p20d;     // Profile 20 jours
    SingleProfile p50d;     // Profile 50 jours
    SingleProfile p100d;    // Profile 100 jours
    SingleProfile p200d;    // Profile 200 jours
    
    // Niveaux agrégés les plus proches (toutes périodes confondues)
    float nearest_lvn_above;        // LVN le plus proche au-dessus (toutes périodes)
    float nearest_lvn_below;        // LVN le plus proche en-dessous (toutes périodes)
    float nearest_hvn_above;        // HVN le plus proche au-dessus
    float nearest_hvn_below;        // HVN le plus proche en-dessous
    int nearest_lvn_above_period;   // Période du LVN (1, 20, 50, 100, 200)
    int nearest_lvn_below_period;
    int nearest_hvn_above_period;
    int nearest_hvn_below_period;
    
    // Distances en ticks
    float dist_nearest_lvn_above_ticks;
    float dist_nearest_lvn_below_ticks;
    float dist_nearest_hvn_above_ticks;
    float dist_nearest_hvn_below_ticks;
    
    // Confluence (plusieurs périodes au même niveau)
    int lvn_confluence_count;       // Nombre de LVN proches (<5 ticks)
    int hvn_confluence_count;       // Nombre de HVN proches (<5 ticks)
    float strongest_lvn;            // LVN avec le plus de confluence
    float strongest_hvn;            // HVN avec le plus de confluence
};

// --- DONNÉES MENTHORQ ---
struct MenthorQ_Data {
    float gex[10];
    float hvl;
    float hvl_0dte;
    float call_resistance;
    float call_resistance_0dte;
    float put_support;
    float put_support_0dte;
    float gamma_wall;
    float gamma_wall_0dte;
    float day_min;
    float day_max;
    float vwap;
    float vwap_up1;
    float vwap_dn1;
    float vwap_up2;
    float vwap_dn2;
    float blind_spots[9];
    float vah;
    float val;
    float next_wall_price;
    float next_wall_strength;
    int next_wall_side;
    float next_wall;             // Alias pour next_wall_price (compatibilité)
    float wall_distance_ticks;   // Distance au mur en ticks
    
    // 🆕 DISTANCES (comme Python: menthor_distances)
    float dist_gex_up_ticks;     // Distance au GEX le plus proche au-dessus
    float dist_gex_dn_ticks;     // Distance au GEX le plus proche en-dessous  
    float dist_blind_ticks;      // Distance au blind spot le plus proche
    float dist_gamma_ticks;      // Distance au gamma wall le plus proche
    float dist_call_ticks;       // Distance au call resistance
    float dist_put_ticks;        // Distance au put support
    float nearest_gex_up;        // Prix du GEX le plus proche au-dessus
    float nearest_gex_dn;        // Prix du GEX le plus proche en-dessous
    float nearest_blind;         // Prix du blind spot le plus proche
    
    // 🆕 31/01/2026: PREVIOUS LEVELS (Chart 26/27)
    // Niveaux de la session/jour précédent - TRÈS utiles pour support/résistance
    float prev_vah;              // Previous Value Area High
    float prev_val;              // Previous Value Area Low  
    float prev_vpoc;             // Previous Volume Point of Control
    float prev_vwap;             // Previous VWAP
    float prev_vwap_sd1_up;      // Previous VWAP +1 SD
    float prev_vwap_sd1_dn;      // Previous VWAP -1 SD
};

// --- SNAPSHOT TRADE ---
struct TradeSnapshot {
    char symbol[8];
    int trade_id;
    SCDateTime entry_time;
    SCDateTime exit_time;

    int direction;
    float entry_price;
    float exit_price;
    float sl_price;
    float tp_price;
    float pnl;
    char exit_reason[64];

    bool l1_passed;
    float l1_confidence;
    char l1_level_name[32];
    float l1_level_price;
    float l1_distance_ticks;

    bool l2_passed;
    float l2_confidence;
    float l2_bn_score;
    char l2_correlation[32];
    int l2_visual_signals;

    bool l3_passed;
    float l3_confidence;
    char l3_context[64];

    bool l4_passed;
    int l4_combo_aligned;
    bool l4_pct_ok;
    bool l4_delta_ok;
    bool l4_bn_ok;
    bool l4_vwap_ok;

    bool is_rectangle_trade;
    float extension_line_dist;
    float vwap_slope;
    int confluence_count;

    bool is_high_quality;
    float hq_score;
    char hq_reason[128];

    BN_Data bn_es;
    BN_Data bn_nq;
    MenthorQ_Data menthorq;

    float vix;
    float atr;
    float spread;
    int dom_depth_bid;
    int dom_depth_ask;
    float delta;
    float cum_delta;
    float buy_pct;
    float sell_pct;
    char session[16];

    float microprice;
    float ob_center;
    float pressure_strength;
};

// --- DASHBOARD DATA ---
struct DashboardData {
    bool bot_running;
    SCDateTime last_heartbeat;
    char global_status[128];

    BotState es_state;
    BotState nq_state;

    char current_session[32];
    char next_event[64];
    SCDateTime next_event_time;

    bool news_detected;
    char news_message[128];

    char no_trade_reason_es[256];
    char no_trade_reason_nq[256];
    char last_rejected_es[256];
    char last_rejected_nq[256];
    int signals_rejected_es;
    int signals_rejected_nq;
    char bot_action_es[128];
    char bot_action_nq[128];
    
    // 🆕 01/02/2026: COMPTEURS PAR LAYER - Pour identifier le goulot d'étranglement
    int l1_reject_es;      // Rejets L1 (pas de niveau proche)
    int l2_reject_es;      // Rejets L2 (order flow)
    int l3_veto_es;        // VETOs L3 (anti-trend, golden rule)
    int l3_reject_es;      // Rejets L3 (contexte insuffisant)
    int l4_reject_es;      // Rejets L4 (score qualité < 55)
    int min_reject_es;     // Rejets seuils min (L1/L2/L3/BN/confluence)
    int sltp_reject_es;    // Rejets SLTP (R:R invalide)
    int total_evals_es;    // Total d'évaluations ES
    
    int l1_reject_nq;
    int l2_reject_nq;
    int l3_veto_nq;
    int l3_reject_nq;
    int l4_reject_nq;
    int min_reject_nq;
    int sltp_reject_nq;
    int total_evals_nq;
};

// --- LAYER RESULTS ---
struct Layer1Result {
    bool passed;
    float confidence;
    int direction;           // 1=LONG, -1=SHORT, 0=NEUTRAL
    char level_name[64];
    float level_price;
    float distance_ticks;
    int importance_score;    // Score du niveau (1=mineur, 2=important, 3=majeur)
};

struct Layer2Result {
    bool passed;
    float confidence;
    float bn_score;
    char correlation[64];
    char reason[256];        // Agrandi pour messages détaillés
    int visual_count;        // 🆕 01/02/2026: Nombre de signaux visuels BN (pour L4 Score Qualité)
};

struct Layer3Result {
    bool passed;
    float confidence;
    char context[64];
    bool veto;
    char veto_reason[128];
};

struct Layer4Result {
    bool passed;
    int combo_aligned;  // 0-4 (règles alignées)
    bool pct_ok;        // Buy/Sell % > 52%
    bool edge_ok;       // Edge/Rectangle Dominant
    bool delta_ok;      // Delta aligné
    bool bn_ok;         // BN score aligné
    bool vwap_ok;       // VWAP slope aligné
    // 🆕 01/02/2026: Score Qualité Globale
    float quality_score;  // Score 0-100
    char grade;           // 'A', 'B', 'C', 'D'
    float tp_multiplier;  // Multiplicateur TP (1.0-1.3)
};

struct SLTPResult {
    float sl_price;
    float tp_price;
    int sl_ticks;
    int tp_ticks;
    float rr_ratio;
    char sl_based_on[32];
    char tp_based_on[64];
    bool is_valid;
};

struct HQResult {
    bool is_hq;
    float hq_score;
    float tp_multiplier;
    float sl_multiplier;
    int position_size_mult;
    char reason[128];
};

// --- TRADE WHY ---
struct TradeWhy {
    int trade_id;
    SCDateTime timestamp;
    char symbol[8];
    char side[8];
    char execution_mode[32];
    char trigger_level_type[32];
    float trigger_level_price;
    float trigger_distance_ticks;
    float bn_score;
    float l1_confidence;
    float l2_confidence;
    float l3_confidence;
    int l4_combo;
    float vwap_slope;
    bool is_rectangle;
    int visual_signals_count;
    float entry_price;
    float sl_price;
    float tp_price;
    char sl_based_on[32];
    char tp_based_on[32];
    float rr_ratio;
    bool is_high_quality;
    char hq_reason[64];
    
    // Champs additionnels pour logging complet
    float anchor_final;          // Prix d'ancrage final
    float anchor_ext;            // Prix extension line
    float anchor_color;          // Prix color (boule)
    float dist_ticks_to_anchor;  // Distance à l'ancrage en ticks
    int qty;                     // Quantité
    int l1_ok;                   // Layer 1 passé (0/1)
    int l2_ok;                   // Layer 2 passé (0/1)
    int l3_ok;                   // Layer 3 passé (0/1)
    int l4_ok;                   // Layer 4 passé (0/1)
    float confluence_score;      // Score de confluence
    float vwap_dist_ticks;       // Distance au VWAP en ticks
    float vix_value;             // Valeur VIX
    char vix_regime[16];         // Régime VIX (LOW, MEDIUM, HIGH, EXTREME)
    int dom_healthy;             // DOM healthy (0/1)
    float spread_ticks;          // Spread en ticks
    int veto_triggered;          // Veto déclenché (0/1)
    char veto_reason[64];        // Raison du veto
    char layer_reject_reason[128]; // Raison de rejet layer
    char notes[256];             // Notes additionnelles
};

// ═══════════════════════════════════════════════════════════════════════════════
// FIN MIA_Config.h
// ═══════════════════════════════════════════════════════════════════════════════
