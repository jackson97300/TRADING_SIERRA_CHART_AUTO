// ═══════════════════════════════════════════════════════════════════════════════
// MIA AUTO-TRADER BATAILLE NAVALE v1.2-STRUCTURED
// ═══════════════════════════════════════════════════════════════════════════════
//
// Sierra Chart ACSIL Auto-Trading Study
// Base sur la logique Layer 1-4 de MIA avec Bataille Navale
//
// Author: MIA Trading System
// Date: 2026-01-17
// Version: 1.2-STRUCTURED (30/01/2026)
//
// FONCTIONNALITES:
// - Ordres Parent/Enfant (Entry LIMIT + SL STOP MARKET + TP LIMIT)
// - Sessions FR: 02h30 - 21h00 avec pause Open US
// - Detection annonces (spread + DOM)
// - Cooldown Win/Loss
// - Dashboard complet (JSON + Console)
// - Trailing Stop adaptatif
// - Break-Even automatique
// - Controles independants ES/NQ
// - Snapshots ultra-complets par trade
// - SYNC positions manuelles/SimpleBracket
//
// ═══════════════════════════════════════════════════════════════════════════════
// 📁 TABLE DES MATIÈRES - PRÉPARATION REFACTORING FUTUR
// ═══════════════════════════════════════════════════════════════════════════════
//
// Ce fichier monolithique (~8800 lignes) sera découpé en modules lors du
// refactoring. La structure ci-dessous indique les futurs fichiers:
//
// ┌─────────────────────────────────────────────────────────────────────────────┐
// │  FUTUR FICHIER             │ CONTENU                      │ LIGNES ACTUELLES │
// ├─────────────────────────────────────────────────────────────────────────────┤
// │                                                                             │
// │  📄 MIA_Config.h           │ Constantes et configuration  │                 │
// │     ├── SECTION 1          │ SymbolConfig, Sessions       │ 123 - 266       │
// │     └── SECTION 2          │ Structures (BotState, etc.)  │ 267 - 626       │
// │                                                                             │
// │  📄 MIA_Globals.h          │ Variables globales           │                 │
// │     ├── SECTION 3          │ g_es_state, g_nq_state       │ 627 - 635       │
// │     └── SECTION 3.5        │ Forward declarations         │ 636 - 701       │
// │                                                                             │
// │  📄 MIA_ExtensionTracker.h │ Tracking Extension Lines     │                 │
// │     └── SECTION 3.6        │ ExtensionLinesTracker        │ 702 - 976       │
// │                                                                             │
// │  📄 MIA_SLTP.h             │ Calcul Stop Loss / Take Prof │                 │
// │     └── SECTION 3.7        │ SL/TP Extension Lines        │ 977 - 1110      │
// │                                                                             │
// │  📄 MIA_Utils.h            │ Fonctions utilitaires        │                 │
// │     └── SECTION 4          │ Helpers, conversions         │ 1111 - 1260     │
// │                                                                             │
// │  📄 MIA_DataReader.h       │ Lecture données marché       │                 │
// │     ├── SECTION 5          │ CollectBatailleNavale()      │ 1261 - 2427     │
// │     ├── SECTION 6          │ CollectMenthorQ()            │ 2428 - 2521     │
// │     └── SECTION 6.4        │ CalculateNextWall()          │ 2522 - 2606     │
// │                                                                             │
// │  📄 MIA_Indicators.h       │ Calculs indicateurs          │                 │
// │     └── SECTION 6.5        │ VIX, ATR, VWAP, Confluence   │ 2607 - 3207     │
// │                                                                             │
// │  📄 MIA_Layers.h           │ Logique de filtrage L1-L4    │                 │
// │     ├── SECTION 7          │ Layer 1 - MenthorQ Levels    │ 3208 - 3567     │
// │     ├── SECTION 7B         │ Layer 1 Alt - Rectangles     │ 3568 - 3854     │
// │     ├── SECTION 8          │ Layer 2 - OrderFlow + BN     │ 3855 - 4606     │
// │     ├── SECTION 9          │ Layer 3 - Context (VWAP+SM)  │ 4607 - 4899     │
// │     └── SECTION 10         │ Layer 4 - Combo Filter       │ 4900 - 4978     │
// │                                                                             │
// │  📄 MIA_SLTP_Calc.h        │ CalculateSLTP() principal    │                 │
// │     └── SECTION 11         │ CalculateProtectedSLTP()     │ 4979 - 5470     │
// │                                                                             │
// │  📄 MIA_Execution.h        │ Gestion des ordres           │                 │
// │     └── SECTION 12         │ SendBracketOrder, Trailing   │ 5471 - 6367     │
// │                                                                             │
// │  📄 MIA_Logging.h          │ Logs et snapshots            │                 │
// │     └── SECTION 13         │ SaveSnapshot, LogWhy, etc.   │ 6368 - 7514     │
// │                                                                             │
// │  📄 MIA_Main.cpp           │ Boucle principale (COMPILÉ)  │                 │
// │     └── SECTION 14         │ scsf_MIA_AutoTrader()        │ 7515 - 8929     │
// │                                                                             │
// └─────────────────────────────────────────────────────────────────────────────┘
//
// ═══════════════════════════════════════════════════════════════════════════════
// 🔧 CHANGELOG
// ═══════════════════════════════════════════════════════════════════════════════
//
// [2026-01-30] v1.2-STRUCTURED - Table des matières + L3 optimisé
//   - ADD: Table des matières préparant le refactoring futur
//   - MOD: Layer 3 = VWAP_slope + smart_money (NQ) / delta (ES)
//   - MOD: WinRate attendu: NQ 78%, ES 82%
//
// [2026-01-23] v1.1-TRACKING - Base VERSION STABLE + Tracking complet
//   - ADD: SYNC positions manuelles/SimpleBracket (detecte trades externes)
//   - ADD: LogSyncPosition() pour tracer les trades manuels detectes
//   - ADD: entry_time dans BotState (pour duration et audit)
//   - ADD: break_even_activated dans BotState
//   - MOD: Trailing ACTIF (ES: 15 ticks, NQ: 25 ticks)
//   - MOD: Break-Even AUTO (ES: 10 ticks, NQ: 15 ticks)
//   - KEEP: Logique de trading Layer 1-4 INTACTE
//
// [2026-01-17] v1.0 - VERSION STABLE ORIGINALE
//   - Base: Logique Layer 1-4 complete
//   - Ordres OCO (Entry + SL + TP)
//   - Dashboard JSON + Console
//   - Logging complet (WHY, WIN, LOSS, REJETS)
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "sierrachart.h"
#include <string>
#include <vector>
#include <algorithm>  // 🔧 27/01/2026: Pour std::sort dans CalculateBNAnchor
#include <fstream>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <map>

SCDLLName("MIA_AutoTrader_BN_v1")

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1: CONFIGURATION ET CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// --- SYMBOLES ---
enum SymbolType { SYM_ES = 0, SYM_NQ = 1 };

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

const SymbolConfig CONFIG_ES = {
    "ES",
    0.25f,      // tick_size
    12.50f,     // tick_value

    // 🔧 SL ÉLARGI (26/01/2026) - ANTI-PULLBACK: Plus de respiration!
    20,         // sl_default_ticks (5 pts - laisse respirer les pullbacks)
    16,         // sl_min_ticks (4 pts minimum)
    28,         // sl_max_ticks (7 pts max)
    3,          // sl_buffer_ticks
    24,         // tp_default_ticks (6 pts - ajusté pour RR ~1.2)
    32,         // tp_max_ticks (8 pts max)
    2,          // tp_buffer_ticks
    1.20f,      // min_rr_ratio (TP/SL = 24/20 = 1.2)

    // TRAILING ACTIF
    15,         // trailing_activation_ticks (active a +3.75 pts profit)
    8,          // trailing_distance_ticks (suit le prix a 2 pts)

    // BREAK-EVEN AUTO
    10,         // break_even_activation_ticks (active a +2.5 pts profit)
    1,          // break_even_buffer_ticks (+1 tick au-dessus entry)

    3,          // max_consecutive_losses
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min

    4,          // spread_alert_ticks (>4 ticks = 1.0 pt) - 🔧 27/01 augmenté (était 2)
    30,         // dom_min_depth

    -0.05f,     // l2_bn_score_min_long (VIX normal)
    0.05f,      // l2_bn_score_max_short
    0           // 🔧 l4_combo_required = 0 (OFF - backtest 25/01/2026)
};

const SymbolConfig CONFIG_NQ = {
    "NQ",
    0.25f,      // tick_size
    5.00f,      // tick_value

    // SL ELARGI - NQ VOLATIL
    28,         // sl_default_ticks (7 pts - laisse respirer)
    20,         // sl_min_ticks (5 pts minimum)
    40,         // sl_max_ticks (10 pts max)
    5,          // sl_buffer_ticks
    35,         // tp_default_ticks (8.75 pts)
    50,         // tp_max_ticks (12.5 pts)
    3,          // tp_buffer_ticks
    1.25f,      // min_rr_ratio (TP/SL = 35/28 = 1.25)

    // TRAILING ACTIF
    25,         // trailing_activation_ticks (active a +6.25 pts profit)
    12,         // trailing_distance_ticks (suit le prix a 3 pts)

    // BREAK-EVEN AUTO
    15,         // break_even_activation_ticks (active a +3.75 pts profit)
    2,          // break_even_buffer_ticks (+2 ticks au-dessus entry)

    4,          // max_consecutive_losses
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min

    8,          // spread_alert_ticks (>8 ticks = 2.0 pts) - 🔧 27/01 augmenté (était 4)
    30,         // dom_min_depth

    -0.05f,     // l2_bn_score_min_long
    0.05f,      // l2_bn_score_max_short
    0           // 🔧 l4_combo_required = 0 (OFF - backtest 25/01/2026)
};

// --- SESSIONS (Heure FR convertie en minutes depuis minuit ET) ---
// FR = ET + 6h (hiver) ou ET + 5h (été)
// On utilise ET car Sierra Chart est en ET par défaut

// MODE PRODUCTION: Horaires stricts (🔧 20/01/2026: Début à 00:00 FR = Session Asia)
const int SESSION_START_ET = 18 * 60;            // 18:00 ET = 00:00 FR (ouverture Asia)
const int SESSION_END_ET = 15 * 60;              // 15:00 ET = 21:00 FR
const int US_OPEN_ET = 9 * 60 + 30;              // 09:30 ET = 15:30 FR
const int US_OPR_END_ET = 9 * 60 + 45;           // 09:45 ET = 15:45 FR (OPR 15 min)
const int PRE_US_PAUSE_START_ET = 9 * 60;        // 09:00 ET = 15:00 FR (30 min avant)

// MODE TEST: Session étendue (Asie → Fermeture US)
const int TEST_SESSION_START_ET = 18 * 60;       // 18:00 ET = 00:00 FR (ouverture Asie)
const int TEST_SESSION_END_ET = 17 * 60;         // 17:00 ET = 23:00 FR (fermeture US)

// --- MODES ---
enum BotMode { MODE_PRODUCTION = 0, MODE_TEST = 1 };

// --- TIMEOUTS ---
const int ORDER_TIMEOUT_SECONDS = 15;
// 🔧 27/01/2026: Augmenté à 90 sec pour Smart Money Entry
// On place le LIMIT sur l'Edge Zone et on ATTEND le pullback
const int LIMIT_ORDER_TIMEOUT_SECONDS = 90;
const int NEWS_BLOCK_MINUTES = 30;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2: STRUCTURES DE DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════

// --- ÉTAT DU BOT PAR SYMBOLE ---
struct BotState {
    bool enabled;                    // Bot actif pour ce symbole
    bool paused;                     // En pause manuelle
    bool in_position;                // Position ouverte
    int position_direction;          // 1=LONG, -1=SHORT, 0=flat

    // Ordres
    int parent_order_id;
    int sl_order_id;
    int tp_order_id;
    SCDateTime order_sent_time;
    bool pending_limit_order;        // 🆕 Ordre LIMIT en attente d'exécution

    // Position
    float entry_price;
    float sl_price;
    float tp_price;
    float trailing_sl;
    bool trailing_activated;
    bool break_even_activated;  // Break-even SL active
    SCDateTime entry_time;      // Heure d'entree (pour SYNC et duration)

    // Stats journalieres
    int trades_today;
    int wins_today;
    int losses_today;
    float pnl_today;
    float best_trade;
    float worst_trade;
    int consecutive_losses;
    float last_processed_pnl;  // 🆕 28/01: Track dernier PNL traité (éviter doublons)

    // Cooldown
    SCDateTime cooldown_until;
    SCDateTime news_block_until;

    // Status message
    char status_message[256];
    char waiting_for[256];

    // Dernier signal
    int last_signal_direction;       // 1=LONG, -1=SHORT, 0=none
    float last_signal_confidence;
    char last_signal_reason[512];

    // 🆕 Données pour Discord (stockées lors de l'envoi de l'ordre)
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
    // === SIGNAUX FOOTPRINT (Chart 28/39) ===
    float edge_buy;
    float edge_sell;
    float color_up;
    float color_down;
    float absorb_ask;
    float absorb_bid;
    float double_ask;      // ES
    float double_bid;      // ES
    float triple_ask;      // NQ
    float triple_bid;      // NQ
    float rotation_up;     // Momentum haussier (CRITIQUE)
    float rotation_down;   // Momentum baissier (CRITIQUE)
    float volume_up;       // NQ
    float volume_down;     // NQ

    // === GROS ORDRES (Seuils institutionnels) ===
    float ask_100;         // Ordres ASK >= 100 lots
    float bid_100;         // Ordres BID >= 100 lots
    float ask_150;         // ES: Ordres ASK >= 150 lots
    float bid_150;         // ES: Ordres BID >= 150 lots
    float ask_400;         // ES: Ordres ASK >= 400 lots
    float bid_400;         // ES: Ordres BID >= 400 lots
    float ask_1000;        // ES: Ordres ASK >= 1000 lots
    float bid_1000;        // ES: Ordres BID >= 1000 lots
    float cluster_vol;     // Clusters de volume concentré

    // === SIGNAUX BARRES (Chart 29/40) ===
    float long_down_up;    // Reversal haussier V (CRITIQUE - x2)
    float long_up_down;    // Reversal baissier ^ (CRITIQUE - x2)
    float bar_color_up;    // COLOR UP depuis barres
    float bar_color_down;  // COLOR DOWN depuis barres
    float bar_edge_buy;    // EDGE BUY depuis barres
    float bar_edge_sell;   // EDGE SELL depuis barres

    // === FPBS (Force Pression) ===
    float fpbs_ask_pct;    // % pression acheteuse FPBS
    float fpbs_bid_pct;    // % pression vendeuse FPBS
    
    // === 🆕 FPBS AVANCÉ (Delta, CVD, POC) ===
    float fpbs_delta;      // Delta de la barre actuelle (achat - vente)
    float fpbs_delta_day;  // Delta cumulé du jour
    float fpbs_cvd;        // Cumulative Delta Volume (trend)
    float fpbs_poc;        // Point Of Control Volume (prix le plus échangé)
    
    // === 🆕 CVD & POC ANALYSIS (Confirmation Trend) ===
    float prev_cvd;        // CVD de la barre précédente (pour calcul slope)
    float cvd_slope;       // Pente CVD = (CVD - prev_CVD) normalisée
    int poc_confirm;       // +1=BULLISH (Close>POC), 0=NEUTRAL, -1=BEARISH (Close<POC)
    bool cvd_divergence;   // TRUE si forte divergence détectée (VETO!)
    float cvd_trend_score; // Score trend CVD: >0 bullish, <0 bearish
    
    // === 🆕 NQ ORDRES GRANULAIRES (+10, +30) ===
    float ask_10;          // NQ: Ordres ASK >= 10 lots (petits)
    float bid_10;          // NQ: Ordres BID >= 10 lots
    float ask_30;          // NQ: Ordres ASK >= 30 lots (moyens)
    float bid_30;          // NQ: Ordres BID >= 30 lots

    // === SCORES CALCULÉS ===
    float score;           // Score global BN [-1, +1]
    float signal;          // Signal: -1=bear, 0=neutral, +1=bull
    float momentum_score;  // Score momentum (rotation)
    float reversal_score;  // Score reversals (long bars)
    float institutional_pressure; // Pression gros ordres

    // === 🆕 PRO: MOMENTUM DELTA (détection changements) ===
    float prev_color_up;       // Valeur précédente color_up
    float prev_color_down;     // Valeur précédente color_down
    float color_momentum;      // Delta: (color_up - color_down) - prev
    float momentum_shift;      // +1=shift bullish, -1=shift bearish, 0=stable

    // === 🆕 PRO: RECTANGLES FRAIS (pas cumulatifs) ===
    float prev_double_bid;     // Valeur précédente double_bid
    float prev_double_ask;     // Valeur précédente double_ask
    bool fresh_rectangle_buy;  // Zone achat VIENT d'être touchée
    bool fresh_rectangle_sell; // Zone vente VIENT d'être touchée
    int fresh_rect_age_bars;   // Âge du rectangle frais (barres)

    // === 🆕 PRO: EDGE ZONE RATIO (domination claire) ===
    float edge_ratio;          // edge_buy / (edge_buy + edge_sell)
    bool edge_dominant_buy;    // Acheteurs dominent clairement
    bool edge_dominant_sell;   // Vendeurs dominent clairement

    // === EXTENSION LINES (Zones de réaction des gros) ===
    float ext_lines_support[10];  // Zones support (COLOR UP + EDGE BUY + LONG DOWN UP)
    float ext_lines_resist[10];   // Zones résistance (COLOR DOWN + EDGE SELL + LONG UP DOWN)
    int num_ext_support;
    int num_ext_resist;
    float nearest_ext_support;
    float nearest_ext_resist;

    // === 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR) - SÉPARÉS DES BOULES ===
    // Ces rectangles verts/rouges sont des NIVEAUX TRADABLES (pas juste confluence)
    float long_up_bar_ext[10];     // RECTANGLES VERTS = SUPPORT TRADABLE (SG1 prix)
    float long_down_bar_ext[10];   // RECTANGLES ROUGES = RESISTANCE TRADABLE (SG1 prix)
    int num_long_up_bar;           // Nombre de rectangles verts actifs
    int num_long_down_bar;         // Nombre de rectangles rouges actifs
    float nearest_long_up_bar;     // Rectangle vert le plus proche du prix
    float nearest_long_down_bar;   // Rectangle rouge le plus proche du prix
    bool has_tradable_support;     // TRUE si rectangle vert proche (tradable level)
    bool has_tradable_resist;      // TRUE si rectangle rouge proche (tradable level)

    // === 🆕 GROS RECTANGLES EDGE ZONE (Adjacent Alert Highlight 48-57) ===
    // Ces rectangles épais représentent les zones d'absorption/imbalance massives
    float edge_rect_buy_bottom[5];   // Bottom des rectangles BUY (support)
    float edge_rect_buy_top[5];      // Top des rectangles BUY
    float edge_rect_sell_bottom[5];  // Bottom des rectangles SELL
    float edge_rect_sell_top[5];     // Top des rectangles SELL (résistance)
    int num_edge_rect_buy;
    int num_edge_rect_sell;
    float nearest_edge_rect_support;  // Rectangle support le plus proche
    float nearest_edge_rect_resist;   // Rectangle résist le plus proche
    bool price_in_edge_rect_buy;      // Prix actuellement DANS un rectangle BUY
    bool price_in_edge_rect_sell;     // Prix actuellement DANS un rectangle SELL

    // === 🆕 BATAILLE NAVALE AVANCÉE (Configuration spatiale) ===
    // Règle "Pas de boule opposée sous/dessus"
    float lowest_edge_buy;            // Plus bas niveau de tous les edge_buy
    float highest_edge_sell;          // Plus haut niveau de tous les edge_sell
    bool bn_attack_long_valid;        // LONG: pas de edge_sell sous lowest_edge_buy
    bool bn_attack_short_valid;       // SHORT: pas de edge_buy au dessus highest_edge_sell

    // Règle "Empilement" = Force de l'attaque
    int stacked_buy_zones;            // Nombre de rectangles verts empilés
    int stacked_sell_zones;           // Nombre de rectangles rouges empilés
    float attack_strength_buy;        // Force attaque acheteurs (0-1)
    float attack_strength_sell;       // Force attaque vendeurs (0-1)

    // Règle "Cohérence directionnelle"
    bool all_signals_bullish;         // TOUS les signaux sont bullish
    bool all_signals_bearish;         // TOUS les signaux sont bearish
    float directional_coherence;      // Score de cohérence (-1 à +1)
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 30/01/2026: BOULES INDIVIDUELLES (COLOR UP/DOWN) - Pour règle subtile
    // Alignement avec bot Python: utiliser les BOULES, pas les rectangles
    // ═══════════════════════════════════════════════════════════════════════════
    float color_up_prices[20];        // Prix de TOUTES les boules vertes actives
    float color_down_prices[20];      // Prix de TOUTES les boules rouges actives
    int num_color_up_prices;          // Nombre de boules vertes
    int num_color_down_prices;        // Nombre de boules rouges
    
    // Règle subtile avec BOULES (comme Python)
    float green_base_price;           // Base verte = max(boules vertes sous prix)
    float red_base_price;             // Base rouge = min(boules rouges au-dessus prix)
    bool bn_subtile_long_valid;       // LONG: pas de rouge sous green_base
    bool bn_subtile_short_valid;      // SHORT: pas de vert au-dessus red_base
    char subtile_long_reason[64];     // Raison si LONG bloqué
    char subtile_short_reason[64];    // Raison si SHORT bloqué
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 30/01/2026: MODE RANGE - Détection et position dans le range
    // Alignement avec bot Python: acheter en bas, vendre en haut
    // ═══════════════════════════════════════════════════════════════════════════
    bool is_range;                    // Mode RANGE actif?
    float range_support;              // Min des ext_lines_support
    float range_resistance;           // Max des ext_lines_resist
    float range_midpoint;             // Milieu du range
    float range_size_pts;             // Taille du range en points
    float price_position_pct;         // Position du prix (0% = support, 100% = résistance)
    int price_position;               // 0=NEAR_SUPPORT, 1=MIDDLE, 2=NEAR_RESISTANCE
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
    // AJOUTS PARITÉ PYTHON
    float vah;              // Value Area High
    float val;              // Value Area Low
    float next_wall_price;  // Prochain mur MenthorQ (priorité max)
    float next_wall_strength;
    int next_wall_side;     // 0=call, 1=put
};

// --- SNAPSHOT TRADE ---
struct TradeSnapshot {
    // Identifiants
    char symbol[8];
    int trade_id;
    SCDateTime entry_time;
    SCDateTime exit_time;

    // Trade
    int direction;           // 1=LONG, -1=SHORT
    float entry_price;
    float exit_price;
    float sl_price;
    float tp_price;
    float pnl;
    char exit_reason[64];    // "TP", "SL", "TRAILING", "MANUAL"

    // Layers validation
    bool l1_passed;
    float l1_confidence;
    char l1_level_name[32];
    float l1_level_price;
    float l1_distance_ticks;   // 🆕 Distance au niveau

    bool l2_passed;
    float l2_confidence;
    float l2_bn_score;
    char l2_correlation[32];
    int l2_visual_signals;     // 🆕 Nombre de signaux visuels BN

    bool l3_passed;
    float l3_confidence;
    char l3_context[64];

    bool l4_passed;
    int l4_combo_aligned;
    bool l4_pct_ok;            // 🆕 Détail combo
    bool l4_delta_ok;          // 🆕 Détail combo
    bool l4_bn_ok;             // 🆕 Détail combo
    bool l4_vwap_ok;           // 🆕 Détail combo

    // 🆕 NOUVELLES DONNÉES POUR ANALYSE
    bool is_rectangle_trade;   // Trade déclenché par rectangle (pas MenthorQ)
    float extension_line_dist; // Distance à l'extension line la plus proche
    float vwap_slope;          // Pente VWAP au moment du trade
    int confluence_count;      // Nombre de niveaux en confluence pour SL

    // 🆕 TRADE HAUTE QUALITÉ (risque augmenté)
    bool is_high_quality;      // True = trade haute qualité avec risque augmenté
    float hq_score;            // Score de qualité (0-1)
    char hq_reason[128];       // Raison du classement HQ

    // Bataille Navale
    BN_Data bn_es;
    BN_Data bn_nq;

    // MenthorQ
    MenthorQ_Data menthorq;

    // Market context
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

    // Microstructure
    float microprice;
    float ob_center;
    float pressure_strength;
};

// --- DASHBOARD DATA ---
struct DashboardData {
    // Bot status
    bool bot_running;
    SCDateTime last_heartbeat;
    char global_status[128];

    // Per symbol
    BotState es_state;
    BotState nq_state;

    // Schedule
    char current_session[32];
    char next_event[64];
    SCDateTime next_event_time;

    // Warnings
    bool news_detected;
    char news_message[128];

    // 🆕 Raisons de non-trade (pour debugging et transparence)
    char no_trade_reason_es[256];     // Pourquoi ES ne trade pas
    char no_trade_reason_nq[256];     // Pourquoi NQ ne trade pas
    char last_rejected_es[256];       // Dernier signal ES rejeté
    char last_rejected_nq[256];       // Dernier signal NQ rejeté
    int signals_rejected_es;          // Nombre de signaux rejetés ES aujourd'hui
    int signals_rejected_nq;          // Nombre de signaux rejetés NQ aujourd'hui
    char bot_action_es[128];          // Ce que le bot fait maintenant (ES)
    char bot_action_nq[128];          // Ce que le bot fait maintenant (NQ)
};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3: VARIABLES GLOBALES PERSISTANTES
// ═══════════════════════════════════════════════════════════════════════════════

BotState g_es_state;
BotState g_nq_state;
DashboardData g_dashboard;
std::vector<TradeSnapshot> g_trade_history;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3.5: FORWARD DECLARATIONS
// ═══════════════════════════════════════════════════════════════════════════════

void NotifyDiscordTradeOpened(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config, float bn_score, float vwap_slope);
void NotifyDiscordTradeClosed(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config);

// 🆕 Trade ID unique (pour journal WHY)
int g_trade_why_id = 1;

// ═══════════════════════════════════════════════════════════════════════════════
// STRUCTURE TRADE WHY - Journal explicatif de chaque trade
// ═══════════════════════════════════════════════════════════════════════════════
struct TradeWhy {
    int trade_id;
    SCDateTime timestamp;

    char symbol[8];
    char side[8];              // "LONG"/"SHORT"
    char execution_mode[32];   // "IMMEDIATE"/"PENDING_LIMIT"/"SKIP_TOO_FAR"/"REJECTED"

    // Déclencheur (le plus important)
    char trigger_level_type[32];  // "EXT_SUPPORT"/"EXT_RESIST"/"COLOR_UP"/"COLOR_DOWN"/"RECT"/"EDGE_ZONE"/"VWAP"/"VP"/"MENTHORQ"
    float trigger_level_price;
    float anchor_ext;
    float anchor_color;
    float anchor_final;
    float dist_ticks_to_anchor;

    // Trade info
    float entry_price;
    float sl_price;
    float tp_price;
    int qty;

    // Layers / Scores
    int l1_ok;
    int l2_ok;
    int l3_ok;
    int l4_ok;
    float l1_confidence;
    float l2_confidence;
    float l3_confidence;
    int l4_combo;
    float bn_score;
    float confluence_score;
    bool is_rectangle;

    // Contexte marché
    float vwap_slope;
    float vwap_dist_ticks;
    float vix_value;
    char vix_regime[16];
    int dom_healthy;          // 1=OK, 0=degraded
    float spread_ticks;

    // Veto / blocages
    int veto_triggered;       // 1=oui, 0=non
    char veto_reason[256];
    char layer_reject_reason[256];  // Raison si rejeté par un layer

    // Notes additionnelles
    char notes[512];
};
int g_next_trade_id = 1;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3.6: EXTENSION LINES TRACKER - TRACKING PERSISTANT INTELLIGENT
// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 25/01/2026: Tracker intelligent qui garde les Extension Lines entre les snapshots
//
// PROBLÈME RÉSOLU:
// - Avant: Les Extension Lines étaient recalculées à chaque appel (perdues!)
// - Maintenant: On tracke TOUTES les lignes actives, même si > 10 ticks du prix
// - Quand le prix revient vers une ligne, on la détecte!
//
// LOGIQUE:
// 1. Ajouter les Extension Lines du snapshot au tracker (déduplication)
// 2. Marquer une ligne comme INACTIVE quand le prix la touche
// 3. Quand le prix s'approche d'une ligne active → signal disponible
// ═══════════════════════════════════════════════════════════════════════════════

// Structure pour une Extension Line trackée
struct ExtLineTracked {
    float price;
    char line_type;       // 'S' = support, 'R' = resist
    char source[16];      // "COLOR_UP", "EDGE_BUY", "RECT", etc.
    SCDateTime created_ts;
    bool is_active;
    SCDateTime touched_ts;
    
    ExtLineTracked() : price(0), line_type('S'), is_active(true) {
        source[0] = '\0';
    }
    
    ExtLineTracked(float p, char t, const char* s, SCDateTime ts) 
        : price(p), line_type(t), is_active(true) {
        strncpy(source, s, sizeof(source) - 1);
        source[sizeof(source) - 1] = '\0';
        created_ts = ts;
    }
};

// Configuration du tracker
const int EXT_TRACKER_MAX_LINES = 30;          // Max lignes par type
const float EXT_TRACKER_TOUCH_TOLERANCE = 2.0f; // Ticks pour considérer touchée
const int EXT_TRACKER_MAX_AGE_MINUTES = 120;    // Durée max de vie (2h)

// Tracker persistant pour un symbole
struct ExtensionLinesTracker {
    ExtLineTracked supports[EXT_TRACKER_MAX_LINES];
    ExtLineTracked resists[EXT_TRACKER_MAX_LINES];
    int num_supports;
    int num_resists;
    SCDateTime last_update;
    float tick_size;
    
    ExtensionLinesTracker() : num_supports(0), num_resists(0), tick_size(0.25f) {}
    
    // Ajoute une ligne (avec déduplication)
    bool AddLine(float price, char line_type, const char* source, SCDateTime ts) {
        if (price <= 0) return false;
        
        // Choisir la liste appropriée
        ExtLineTracked* lines = (line_type == 'S') ? supports : resists;
        int& count = (line_type == 'S') ? num_supports : num_resists;
        
        // Vérifier si doublon (prix similaire à 1 tick)
        for (int i = 0; i < count; i++) {
            if (lines[i].is_active && fabs(lines[i].price - price) < tick_size * 1.5f) {
                return false; // Doublon
            }
        }
        
        // Ajouter si place disponible
        if (count < EXT_TRACKER_MAX_LINES) {
            lines[count] = ExtLineTracked(price, line_type, source, ts);
            count++;
            return true;
        }
        
        // Sinon remplacer la plus ancienne
        int oldest_idx = 0;
        for (int i = 1; i < count; i++) {
            if (lines[i].created_ts < lines[oldest_idx].created_ts) {
                oldest_idx = i;
            }
        }
        lines[oldest_idx] = ExtLineTracked(price, line_type, source, ts);
        return true;
    }
    
    // Met à jour avec le prix actuel (marque les lignes touchées)
    void UpdateWithPrice(float current_price, SCDateTime current_ts) {
        float tolerance = EXT_TRACKER_TOUCH_TOLERANCE * tick_size;
        
        // Vérifier supports (prix descend vers eux)
        for (int i = 0; i < num_supports; i++) {
            if (supports[i].is_active) {
                if (current_price <= supports[i].price + tolerance) {
                    supports[i].is_active = false;
                    supports[i].touched_ts = current_ts;
                }
            }
        }
        
        // Vérifier résistances (prix monte vers elles)
        for (int i = 0; i < num_resists; i++) {
            if (resists[i].is_active) {
                if (current_price >= resists[i].price - tolerance) {
                    resists[i].is_active = false;
                    resists[i].touched_ts = current_ts;
                }
            }
        }
        
        last_update = current_ts;
    }
    
    // Nettoie les lignes trop anciennes
    void CleanupOldLines(SCDateTime current_ts) {
        // Supprimer les lignes inactives ou trop anciennes
        for (int i = num_supports - 1; i >= 0; i--) {
            if (!supports[i].is_active) {
                // Garder les lignes touchées un moment pour analyse
                continue;
            }
            double age_minutes = (current_ts.GetAsDouble() - supports[i].created_ts.GetAsDouble()) * 24.0 * 60.0;
            if (age_minutes > EXT_TRACKER_MAX_AGE_MINUTES) {
                supports[i].is_active = false;
            }
        }
        
        for (int i = num_resists - 1; i >= 0; i--) {
            if (!resists[i].is_active) {
                continue;
            }
            double age_minutes = (current_ts.GetAsDouble() - resists[i].created_ts.GetAsDouble()) * 24.0 * 60.0;
            if (age_minutes > EXT_TRACKER_MAX_AGE_MINUTES) {
                resists[i].is_active = false;
            }
        }
    }
    
    // Trouve le support le plus proche SOUS le prix
    float GetNearestSupport(float current_price, float* out_distance = nullptr) const {
        float nearest = 0;
        float min_dist = 999999.0f;
        
        for (int i = 0; i < num_supports; i++) {
            if (supports[i].is_active && supports[i].price < current_price) {
                float dist = current_price - supports[i].price;
                if (dist < min_dist) {
                    min_dist = dist;
                    nearest = supports[i].price;
                }
            }
        }
        
        if (out_distance && nearest > 0) {
            *out_distance = min_dist / tick_size;
        }
        return nearest;
    }
    
    // Trouve la résistance la plus proche AU-DESSUS du prix
    float GetNearestResist(float current_price, float* out_distance = nullptr) const {
        float nearest = 0;
        float min_dist = 999999.0f;
        
        for (int i = 0; i < num_resists; i++) {
            if (resists[i].is_active && resists[i].price > current_price) {
                float dist = resists[i].price - current_price;
                if (dist < min_dist) {
                    min_dist = dist;
                    nearest = resists[i].price;
                }
            }
        }
        
        if (out_distance && nearest > 0) {
            *out_distance = min_dist / tick_size;
        }
        return nearest;
    }
    
    // Compte les lignes actives dans une distance donnée
    int CountLinesWithinDistance(float current_price, float max_dist_ticks, char line_type) const {
        int count = 0;
        float max_dist = max_dist_ticks * tick_size;
        
        if (line_type == 'S') {
            for (int i = 0; i < num_supports; i++) {
                if (supports[i].is_active && supports[i].price < current_price) {
                    if (current_price - supports[i].price <= max_dist) {
                        count++;
                    }
                }
            }
        } else {
            for (int i = 0; i < num_resists; i++) {
                if (resists[i].is_active && resists[i].price > current_price) {
                    if (resists[i].price - current_price <= max_dist) {
                        count++;
                    }
                }
            }
        }
        
        return count;
    }
    
    // Résumé pour debug
    void GetSummary(char* buffer, int buffer_size, float current_price) const {
        int active_sup = 0, active_res = 0;
        for (int i = 0; i < num_supports; i++) {
            if (supports[i].is_active) active_sup++;
        }
        for (int i = 0; i < num_resists; i++) {
            if (resists[i].is_active) active_res++;
        }
        
        float nearest_sup_dist = 0, nearest_res_dist = 0;
        GetNearestSupport(current_price, &nearest_sup_dist);
        GetNearestResist(current_price, &nearest_res_dist);
        
        snprintf(buffer, buffer_size, 
            "ExtTracker: %d sup (%d active), %d res (%d active) | "
            "Nearest: SUP %.1ft, RES %.1ft",
            num_supports, active_sup, num_resists, active_res,
            nearest_sup_dist, nearest_res_dist);
    }
};

// 🆕 TRACKERS GLOBAUX PERSISTANTS (un par symbole)
ExtensionLinesTracker g_ext_tracker_es;
ExtensionLinesTracker g_ext_tracker_nq;

// Met à jour le tracker avec les Extension Lines du snapshot BN
void UpdateExtensionLinesTracker(
    ExtensionLinesTracker& tracker,
    const BN_Data& bn,
    float current_price,
    SCDateTime current_ts,
    float tick_size
) {
    tracker.tick_size = tick_size;
    
    // Ajouter les supports du BN_Data
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0) {
            tracker.AddLine(bn.ext_lines_support[i], 'S', "BN_SUPPORT", current_ts);
        }
    }
    
    // Ajouter les résistances du BN_Data
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > 0) {
            tracker.AddLine(bn.ext_lines_resist[i], 'R', "BN_RESIST", current_ts);
        }
    }
    
    // Ajouter les rectangles Edge Zone comme Extension Lines
    for (int i = 0; i < bn.num_edge_rect_buy; i++) {
        if (bn.edge_rect_buy_top[i] > 0) {
            tracker.AddLine(bn.edge_rect_buy_top[i], 'S', "EDGE_RECT_BUY", current_ts);
        }
    }
    for (int i = 0; i < bn.num_edge_rect_sell; i++) {
        if (bn.edge_rect_sell_bottom[i] > 0) {
            tracker.AddLine(bn.edge_rect_sell_bottom[i], 'R', "EDGE_RECT_SELL", current_ts);
        }
    }
    
    // Mettre à jour avec le prix actuel (marque les lignes touchées)
    tracker.UpdateWithPrice(current_price, current_ts);
    
    // Nettoyer les lignes trop anciennes
    tracker.CleanupOldLines(current_ts);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3.7: SL/TP DYNAMIQUE BASÉ SUR EXTENSION LINES TRACKÉES
// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 25/01/2026: Utilise les Extension Lines trackées pour placer dynamiquement SL/TP
//
// RÈGLES:
// 1. SL: Placer sous le dernier niveau visible (Extension Line) + buffer
//    - LONG: SL sous le dernier support visible
//    - SHORT: SL au-dessus de la dernière résistance visible
//
// 2. TP: Si obstacle visuel détecté avant le TP normal → TP avant l'obstacle
// ═══════════════════════════════════════════════════════════════════════════════

const int EXT_SL_BUFFER_TICKS = 2;      // Buffer sous/au-dessus du niveau pour SL
const int EXT_TP_BUFFER_TICKS = 2;      // Buffer avant l'obstacle pour TP
const int EXT_MAX_DIST_FOR_SL = 50;     // Distance max pour chercher un niveau pour SL

// Calcule SL basé sur les Extension Lines trackées
float CalculateSLFromTrackedExtLines(
    const ExtensionLinesTracker& tracker,
    int direction,
    float entry_price,
    float tick_size,
    int default_sl_ticks,
    int sl_min_ticks,
    int sl_max_ticks,
    const char** out_reason
) {
    float buffer = EXT_SL_BUFFER_TICKS * tick_size;
    float min_sl = sl_min_ticks * tick_size;
    float max_sl = sl_max_ticks * tick_size;
    
    if (direction == 1) {  // LONG - SL sous support
        float nearest_support = 0;
        float nearest_dist = 0;
        
        // Trouver le support le plus proche SOUS le prix d'entrée
        nearest_support = tracker.GetNearestSupport(entry_price, &nearest_dist);
        
        if (nearest_support > 0 && nearest_dist <= EXT_MAX_DIST_FOR_SL) {
            float sl_price = nearest_support - buffer;
            float sl_distance = entry_price - sl_price;
            
            // Vérifier que le SL est dans les limites
            if (sl_distance >= min_sl && sl_distance <= max_sl) {
                *out_reason = "EXT_SUPPORT_TRACKED";
                return sl_price;
            }
        }
        
        // Fallback: SL par défaut
        *out_reason = "FIXED";
        return entry_price - (default_sl_ticks * tick_size);
        
    } else {  // SHORT - SL au-dessus résistance
        float nearest_resist = 0;
        float nearest_dist = 0;
        
        // Trouver la résistance la plus proche AU-DESSUS du prix d'entrée
        nearest_resist = tracker.GetNearestResist(entry_price, &nearest_dist);
        
        if (nearest_resist > 0 && nearest_dist <= EXT_MAX_DIST_FOR_SL) {
            float sl_price = nearest_resist + buffer;
            float sl_distance = sl_price - entry_price;
            
            // Vérifier que le SL est dans les limites
            if (sl_distance >= min_sl && sl_distance <= max_sl) {
                *out_reason = "EXT_RESIST_TRACKED";
                return sl_price;
            }
        }
        
        // Fallback: SL par défaut
        *out_reason = "FIXED";
        return entry_price + (default_sl_ticks * tick_size);
    }
}

// Calcule TP avec vérification d'obstacles trackés
float CalculateTPWithTrackedObstacles(
    const ExtensionLinesTracker& tracker,
    int direction,
    float entry_price,
    float tick_size,
    int default_tp_ticks,
    const char** out_reason
) {
    float buffer = EXT_TP_BUFFER_TICKS * tick_size;
    float default_tp = (direction == 1) 
        ? entry_price + (default_tp_ticks * tick_size)
        : entry_price - (default_tp_ticks * tick_size);
    
    if (direction == 1) {  // LONG - chercher obstacles (résistances) au-dessus
        float nearest_resist = 0;
        float nearest_dist = 0;
        
        nearest_resist = tracker.GetNearestResist(entry_price, &nearest_dist);
        
        if (nearest_resist > 0) {
            // Vérifier si l'obstacle est avant le TP par défaut
            float tp_obstacle = nearest_resist - buffer;
            
            if (tp_obstacle < default_tp && (tp_obstacle - entry_price) >= (default_tp_ticks * tick_size * 0.5f)) {
                // Obstacle avant TP et au moins 50% du TP par défaut
                *out_reason = "EXT_RESIST_OBSTACLE";
                return tp_obstacle;
            }
        }
        
        *out_reason = "FIXED";
        return default_tp;
        
    } else {  // SHORT - chercher obstacles (supports) en-dessous
        float nearest_support = 0;
        float nearest_dist = 0;
        
        nearest_support = tracker.GetNearestSupport(entry_price, &nearest_dist);
        
        if (nearest_support > 0) {
            // Vérifier si l'obstacle est avant le TP par défaut
            float tp_obstacle = nearest_support + buffer;
            
            if (tp_obstacle > default_tp && (entry_price - tp_obstacle) >= (default_tp_ticks * tick_size * 0.5f)) {
                // Obstacle avant TP et au moins 50% du TP par défaut
                *out_reason = "EXT_SUPPORT_OBSTACLE";
                return tp_obstacle;
            }
        }
        
        *out_reason = "FIXED";
        return default_tp;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4: FONCTIONS UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════════

// --- Conversion temps ---
// 🆕 FIX: Convertir heure locale (FR) en ET
// ═══════════════════════════════════════════════════════════════════════════
// CONVERSION HEURE LOCALE → HEURE ET (Eastern Time)
// ═══════════════════════════════════════════════════════════════════════════
// 🔧 IMPORTANT: Ajuster FR_TO_ET_OFFSET selon la config Sierra Chart!
// - Si Sierra Chart est en heure FR: FR_TO_ET_OFFSET = 6 (hiver) ou 5 (été)
// - Si Sierra Chart est en heure ET: FR_TO_ET_OFFSET = 0
// - Si Sierra Chart est en UTC: FR_TO_ET_OFFSET = -5 (hiver) ou -4 (été)
// ═══════════════════════════════════════════════════════════════════════════
// 🔧 27/01/2026: Sierra Chart affiche l'heure UTC!
// Conversion: UTC → ET (Eastern Time)
// - Hiver (EST): UTC - 5h → FR_TO_ET_OFFSET = 5
// - Été (EDT): UTC - 4h → FR_TO_ET_OFFSET = 4
// Formule: now_min_et = now_min_utc - FR_TO_ET_OFFSET * 60
const int FR_TO_ET_OFFSET = 5;  // 🔧 Sierra Chart en UTC → conversion vers EST (hiver)

int GetMinutesSinceMidnightET(SCDateTime dt) {
    int hour, minute, second;
    dt.GetTimeHMS(hour, minute, second);
    int now_min_local = hour * 60 + minute;

    int now_min_et = now_min_local - FR_TO_ET_OFFSET * 60;
    if (now_min_et < 0) now_min_et += 24 * 60;  // Wrap-around minuit
    if (now_min_et >= 24 * 60) now_min_et -= 24 * 60;  // Wrap-around 24h

    return now_min_et;
}

// --- Vérification session ---
// 🆕 Paramètre mode: 0=PRODUCTION (horaires stricts), 1=TEST (session étendue)
bool IsWithinTradingSession(SCStudyInterfaceRef sc, int mode = MODE_PRODUCTION) {
    int now_min = GetMinutesSinceMidnightET(sc.CurrentSystemDateTime);
    bool in_session = false;

    if (mode == MODE_TEST) {
        // ═══════════════════════════════════════════════════════════════════
        // MODE TEST: Session étendue (Asie 18:00 ET → Fermeture US 17:00 ET)
        // = Minuit FR → 23h00 FR (presque 24h sauf 1h de maintenance)
        // SANS pause US Open pour maximiser les tests
        // ═══════════════════════════════════════════════════════════════════

        // Session quasi-continue: 18:00 ET → 17:00 ET (23h/24)
        // Seule pause: 17:00-18:00 ET (maintenance CME)
        if (now_min >= TEST_SESSION_START_ET || now_min < TEST_SESSION_END_ET) {
            in_session = true;
        }

        // PAS de pause US Open en mode TEST

    } else {
        // ═══════════════════════════════════════════════════════════════════
        // MODE PRODUCTION: Horaires stricts (02h30 FR → 21h00 FR)
        // AVEC pause US Open (15:00-15:45 FR)
        // ═══════════════════════════════════════════════════════════════════

        // Session overnight: 20:30 ET -> 15:00 ET (next day)
        if (now_min >= SESSION_START_ET || now_min < SESSION_END_ET) {
            in_session = true;
        }

        // Pause avant/pendant US Open (PRODUCTION uniquement)
        if (now_min >= PRE_US_PAUSE_START_ET && now_min < US_OPR_END_ET) {
            in_session = false;
        }
    }

    return in_session;
}

// --- Nom de session actuelle ---
const char* GetCurrentSessionName(SCStudyInterfaceRef sc) {
    int now_min = GetMinutesSinceMidnightET(sc.CurrentSystemDateTime);

    if (now_min >= 20 * 60 + 30 || now_min < 3 * 60) {
        return "Asia";
    } else if (now_min >= 3 * 60 && now_min < 9 * 60) {
        return "London";
    } else if (now_min >= 9 * 60 && now_min < 9 * 60 + 45) {
        return "US_Open_Pause";
    } else if (now_min >= 9 * 60 + 45 && now_min < 15 * 60) {
        return "US";
    } else {
        return "Closed";
    }
}

// --- Détection spread anormal (annonces) ---
bool IsSpreadAbnormal(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    float spread = sc.Ask - sc.Bid;
    float spread_ticks = spread / config.tick_size;
    return spread_ticks > config.spread_alert_ticks;
}

// --- Détection DOM vide ---
bool IsDOMEmpty(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    // Lire profondeur DOM niveau 1
    s_MarketDepthEntry bid_entry, ask_entry;
    sc.GetBidMarketDepthEntryAtLevel(bid_entry, 0);
    sc.GetAskMarketDepthEntryAtLevel(ask_entry, 0);

    int total_depth = bid_entry.Quantity + ask_entry.Quantity;
    return total_depth < config.dom_min_depth;
}

// --- Format timestamp ---
std::string FormatTimestamp(SCDateTime dt) {
    int year, month, day, hour, minute, second;
    dt.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    std::ostringstream oss;
    oss << year << "-"
        << std::setfill('0') << std::setw(2) << month << "-"
        << std::setfill('0') << std::setw(2) << day << " "
        << std::setfill('0') << std::setw(2) << hour << ":"
        << std::setfill('0') << std::setw(2) << minute << ":"
        << std::setfill('0') << std::setw(2) << second;
    return oss.str();
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER: Lecture Study Array avec vérification
// NOTE: sc.GetStudyArrayFromChartUsingID() retourne void, pas int!
// ═══════════════════════════════════════════════════════════════════════════════
inline bool GetStudyValue(SCStudyInterfaceRef sc, int chart, int study_id, int subgraph,
                          SCFloatArray& arr, float& out_value, int bar_offset = 0) {
    sc.GetStudyArrayFromChartUsingID(chart, study_id, subgraph, arr);
    int size = arr.GetArraySize();
    if (size > bar_offset) {
        out_value = arr[size - 1 - bar_offset];
        return true;
    }
    return false;
}

// Version qui retourne directement la valeur (0 si échec)
inline float ReadStudyValue(SCStudyInterfaceRef sc, int chart, int study_id, int subgraph, int bar_offset = 0) {
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study_id, subgraph, arr);
    int size = arr.GetArraySize();
    if (size > bar_offset) {
        return arr[size - 1 - bar_offset];
    }
    return 0.0f;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5: COLLECTE DONNÉES BATAILLE NAVALE
// ═══════════════════════════════════════════════════════════════════════════════

void CollectBN_Data(SCStudyInterfaceRef sc, int chart_footprint, int chart_barres, BN_Data& bn, bool is_nq) {
    // 🔧 FIX CVD SLOPE: Sauvegarder prev_cvd AVANT le memset (utilise persistent vars)
    // Index 100 pour ES, 101 pour NQ
    int cvd_persist_idx = is_nq ? 101 : 100;
    float saved_prev_cvd = sc.GetPersistentFloat(cvd_persist_idx);
    
    // Reset
    memset(&bn, 0, sizeof(BN_Data));
    
    // 🔧 FIX CVD SLOPE: Restaurer prev_cvd APRÈS le memset
    bn.prev_cvd = saved_prev_cvd;

    SCGraphData footprint_data;
    SCGraphData barres_data;

    // Collecter depuis Footprint
    sc.GetChartBaseData(chart_footprint, footprint_data);

    // Collecter depuis Barres
    sc.GetChartBaseData(chart_barres, barres_data);

    // ═══════════════════════════════════════════════════════════════════════════
    // STUDY IDs - VRAIS IDs DES CHARTS (scan du 17/01/2026)
    // ═══════════════════════════════════════════════════════════════════════════

    // --- CHART 1: ES FOOTPRINT (Chart 28) ---
    const int ES_FP_EDGE_BUY = 32;        // EDGE ZONES IMBALANCE BUY
    const int ES_FP_EDGE_SELL = 35;       // EDGE ZONES IMBALANCE SELL
    const int ES_FP_COLOR_UP = 56;        // [AV] COLOR UP
    const int ES_FP_COLOR_DOWN = 57;      // [AV] COLOR DOWN
    const int ES_FP_ABSORB_ASK = 25;      // [AV] ABSORPTION ASK
    const int ES_FP_ABSORB_BID = 26;      // [AV] ABSORPTION BID
    const int ES_FP_DOUBLE_ASK = 28;      // [AV] DOUBLE ASK
    const int ES_FP_DOUBLE_BID = 27;      // [AV] DOUBLE BID
    const int ES_FP_ROTATION_UP = 19;     // [AV] ROTATION UP
    const int ES_FP_ROTATION_DOWN = 20;   // [AV] ROTATION DOWN
    const int ES_FP_FPBS = 31;            // FPBS VOLUME
    const int ES_FP_ASK_100 = 102;        // ASK +100 lots (gros ordres)
    const int ES_FP_BID_100 = 103;        // BID +100 lots
    const int ES_FP_ASK_150 = 6;          // ASK +150 lots
    const int ES_FP_BID_150 = 7;          // BID +150 lots
    const int ES_FP_ASK_400 = 8;          // ASK +400 lots
    const int ES_FP_BID_400 = 9;          // BID +400 lots
    const int ES_FP_ASK_1000 = 29;        // ASK +1000 lots (très gros)
    const int ES_FP_BID_1000 = 30;        // BID +1000 lots
    const int ES_FP_CLUSTER_VOL = 10;     // CLUSTER VOLUME

    // --- CHART 2: NQ FOOTPRINT (Chart 39) ---
    const int NQ_FP_EDGE_BUY = 55;        // EDGE ZONES IMBALANCE BUY rev8
    const int NQ_FP_EDGE_SELL = 56;       // EDGE ZONES IMBALANCE SELL rev8
    const int NQ_FP_COLOR_UP = 53;        // [AV] COLOR UP
    const int NQ_FP_COLOR_DOWN = 54;      // [AV] COLOR DOWN
    const int NQ_FP_ABSORB_ASK = 29;      // [AV] ABSORPTION ASK
    const int NQ_FP_ABSORB_BID = 30;      // [AV] ABSORPTION BID
    const int NQ_FP_TRIPLE_ASK = 28;      // [AV] TRIPLE ASK
    const int NQ_FP_TRIPLE_BID = 27;      // [AV] TRIPLE BID
    const int NQ_FP_ROTATION_UP = 21;     // [AV] ROTATION UP
    const int NQ_FP_ROTATION_DOWN = 22;   // [AV] ROTATION DOWN
    const int NQ_FP_VOLUME_UP = 35;       // [AV] VOLUME UP
    const int NQ_FP_VOLUME_DOWN = 36;     // [AV] VOLUME DOWN
    const int NQ_FP_FPBS = 33;            // FPBS VOLUME
    const int NQ_FP_ASK_10 = 8;           // 🆕 ASK +10 lots (petits ordres)
    const int NQ_FP_BID_10 = 9;           // 🆕 BID +10 lots
    const int NQ_FP_ASK_30 = 10;          // 🆕 ASK +30 lots (ordres moyens)
    const int NQ_FP_BID_30 = 11;          // 🆕 BID +30 lots
    const int NQ_FP_ASK_100 = 31;         // ASK +100 lots (gros ordres)
    const int NQ_FP_BID_100 = 32;         // BID +100 lots
    const int NQ_FP_CLUSTER_VOL = 12;     // CLUSTER VOLUME
    
    // --- FPBS SUBGRAPHS (identiques ES et NQ) ---
    const int FPBS_SG_DELTA = 0;          // 🆕 Delta de la barre
    const int FPBS_SG_DELTA_DAY = 9;      // 🆕 Delta cumulé du jour
    const int FPBS_SG_CVD = 18;           // 🆕 Cumulative Delta Volume
    const int FPBS_SG_POC_VOL = 19;       // Point Of Control VOLUME (nombre de contrats)
    const int FPBS_SG_POC_PRICE = 41;     // 🆕 Point Of Control PRICE (le prix du POC!)
    const int FPBS_SG_ASK_PCT = 16;       // Ask Volume Percent (existant)
    const int FPBS_SG_BID_PCT = 17;       // Bid Volume Percent (existant)

    // --- CHART 25: ES BARRES (Daily ES) --- 🔧 30/01/2026: IDs CORRECTS depuis study_inventory
    // ATTENTION: Les commentaires originaux étaient CORRECTS (Chart 25 = ES, Chart 23 = NQ)
    const int ES_BAR_COLOR_UP = 24;       // [AV] COLOR UP (Study 24 sur Chart 25)
    const int ES_BAR_COLOR_DOWN = 25;     // [AV] COLOR DOWN (Study 25 sur Chart 25)
    const int ES_BAR_LONG_DOWN_UP = 38;   // [AV] LONG DOWN UP BAR ROND JAUNE (Study 38 sur Chart 25)
    const int ES_BAR_LONG_UP_DOWN = 39;   // [AV] LONG UP DOWN BAR ROND JAUNE (Study 39 sur Chart 25)
    const int ES_BAR_LONG_UP_BAR = 18;    // [AV] LONG UP BAR - RECTANGLE VERT TRADABLE (Study 18)
    const int ES_BAR_LONG_DOWN_BAR = 17;  // [AV] LONG DOWN BAR - RECTANGLE ROUGE TRADABLE (Study 17)
    const int ES_BAR_EDGE_BUY = 16;       // EDGE ZONES IMBALANCE BUY 600%DIAG (Study 16 sur Chart 25)
    const int ES_BAR_EDGE_SELL = 44;      // EDGE ZONES IMBALANCE SELL 600%DIAG (Study 44 sur Chart 25)
    const int ES_BAR_MQ_GAMMA = 2;        // MenthorQ Gamma Levels (Study 2 sur Chart 25)
    const int ES_BAR_MQ_BLIND = 22;       // MenthorQ Blind Spots Levels (Study 22 sur Chart 25)
    const int ES_BAR_VWAP = 1;            // VWAP (Study 1)

    // --- CHART 23: NQ BARRES (Daily NQ) --- 🔧 30/01/2026: IDs CORRECTS depuis study_inventory
    const int NQ_BAR_COLOR_UP = 26;       // [AV] COLOR UP (Study 26 sur Chart 23)
    const int NQ_BAR_COLOR_DOWN = 27;     // [AV] COLOR DOWN (Study 27 sur Chart 23)
    const int NQ_BAR_LONG_DOWN_UP = 23;   // [AV] LONG DOWN UP BAR (Study 23 sur Chart 23)
    const int NQ_BAR_LONG_UP_DOWN = 24;   // [AV] LONG UP DOWN BAR (Study 24 sur Chart 23)
    const int NQ_BAR_LONG_UP_BAR = 18;    // [AV] LONG UP BAR - RECTANGLE VERT TRADABLE (Study 18)
    const int NQ_BAR_LONG_DOWN_BAR = 17;  // [AV] LONG DOWN BAR - RECTANGLE ROUGE TRADABLE (Study 17)
    const int NQ_BAR_EDGE_BUY = 32;       // EDGE ZONES IMBALANCE BUY rev8 0DIAG (Study 32 sur Chart 23)
    const int NQ_BAR_EDGE_SELL = 33;      // EDGE ZONES IMBALANCE SELL rev8 0DIAG (Study 33 sur Chart 23)
    const int NQ_BAR_MQ_GAMMA = 25;       // MenthorQ Gamma Levels (Study 25 sur Chart 23)
    const int NQ_BAR_MQ_BLIND = 2;        // MenthorQ Blind Spots (Study 2 sur Chart 23)
    const int NQ_BAR_VWAP = 1;            // VWAP (Study 1)

    // --- ALIASES pour compatibilité avec le code existant ---
    int STUDY_EDGE_BUY, STUDY_EDGE_SELL, STUDY_COLOR_UP, STUDY_COLOR_DOWN;
    int STUDY_ABSORB_ASK, STUDY_ABSORB_BID;
    int STUDY_DOUBLE_ASK, STUDY_DOUBLE_BID, STUDY_TRIPLE_ASK, STUDY_TRIPLE_BID;
    int STUDY_ROTATION_UP, STUDY_ROTATION_DOWN;
    int STUDY_LONG_DOWN_UP, STUDY_LONG_UP_DOWN;
    int STUDY_VOLUME_UP, STUDY_VOLUME_DOWN;

    if (is_nq) {
        // NQ Footprint (Chart 2)
        STUDY_EDGE_BUY = NQ_FP_EDGE_BUY;
        STUDY_EDGE_SELL = NQ_FP_EDGE_SELL;
        STUDY_COLOR_UP = NQ_FP_COLOR_UP;
        STUDY_COLOR_DOWN = NQ_FP_COLOR_DOWN;
        STUDY_ABSORB_ASK = NQ_FP_ABSORB_ASK;
        STUDY_ABSORB_BID = NQ_FP_ABSORB_BID;
        STUDY_TRIPLE_ASK = NQ_FP_TRIPLE_ASK;
        STUDY_TRIPLE_BID = NQ_FP_TRIPLE_BID;
        STUDY_ROTATION_UP = NQ_FP_ROTATION_UP;
        STUDY_ROTATION_DOWN = NQ_FP_ROTATION_DOWN;
        STUDY_VOLUME_UP = NQ_FP_VOLUME_UP;
        STUDY_VOLUME_DOWN = NQ_FP_VOLUME_DOWN;
        // NQ Barres (Chart 4)
        STUDY_LONG_DOWN_UP = NQ_BAR_LONG_DOWN_UP;
        STUDY_LONG_UP_DOWN = NQ_BAR_LONG_UP_DOWN;
    } else {
        // ES Footprint (Chart 1)
        STUDY_EDGE_BUY = ES_FP_EDGE_BUY;
        STUDY_EDGE_SELL = ES_FP_EDGE_SELL;
        STUDY_COLOR_UP = ES_FP_COLOR_UP;
        STUDY_COLOR_DOWN = ES_FP_COLOR_DOWN;
        STUDY_ABSORB_ASK = ES_FP_ABSORB_ASK;
        STUDY_ABSORB_BID = ES_FP_ABSORB_BID;
        STUDY_DOUBLE_ASK = ES_FP_DOUBLE_ASK;
        STUDY_DOUBLE_BID = ES_FP_DOUBLE_BID;
        STUDY_ROTATION_UP = ES_FP_ROTATION_UP;
        STUDY_ROTATION_DOWN = ES_FP_ROTATION_DOWN;
        // ES Barres (Chart 3)
        STUDY_LONG_DOWN_UP = ES_BAR_LONG_DOWN_UP;
        STUDY_LONG_UP_DOWN = ES_BAR_LONG_UP_DOWN;
    }

    // Lecture Footprint (dernier index)
    int last_idx = footprint_data[0].GetArraySize() - 1;
    if (last_idx < 0) return;

    // Edge Buy/Sell - Subgraph 0 = "Trigger 0" (PRIX du premier niveau edge actif)
    // 🔧 30/01/2026: IMPORTANT - EDGE ZONES n'ont PAS de subgraph "Count"!
    // - sg0-46 = Triggers = PRIX des niveaux edge actifs
    // - sg48-57 = Rectangles (bottom/top pairs)
    // - Il n'y a PAS de sg58 "Count of Alerts" pour EDGE ZONES
    // DONC: edge_buy/edge_sell stockent le PRIX du niveau (utile pour SL/TP)
    //       Pour le COUNT, utiliser num_edge_rect_buy/sell calculé plus bas
    bn.edge_buy = ReadStudyValue(sc, chart_footprint, STUDY_EDGE_BUY, 0);   // Trigger 0 = prix niveau
    bn.edge_sell = ReadStudyValue(sc, chart_footprint, STUDY_EDGE_SELL, 0); // Trigger 0 = prix niveau

    // Color Up/Down
    // Color Up/Down - Subgraph 2 = "Sum of Alerts" (COUNT)
    bn.color_up = ReadStudyValue(sc, chart_footprint, STUDY_COLOR_UP, 2);
    bn.color_down = ReadStudyValue(sc, chart_footprint, STUDY_COLOR_DOWN, 2);

    // Absorb - Subgraph 2 = "Sum of Alerts" (COUNT)
    bn.absorb_ask = ReadStudyValue(sc, chart_footprint, STUDY_ABSORB_ASK, 2);
    bn.absorb_bid = ReadStudyValue(sc, chart_footprint, STUDY_ABSORB_BID, 2);

    // ═══════════════════════════════════════════════════════════════════════════
    // NOTE: Pour NQ, TRIPLE/VOLUME/ROTATION sont sur FOOTPRINT (Chart 2)
    //       Pour ES, DOUBLE/ROTATION sont sur FOOTPRINT (Chart 1)
    //       Les patterns V/^ (LONG_DOWN_UP, LONG_UP_DOWN) sont sur les BARRES
    // ═══════════════════════════════════════════════════════════════════════════

    if (is_nq) {
        // === NQ FOOTPRINT (Chart 39) ===
        // 🔧 27/01/2026: FIX - Subgraph 2 = COUNT (utilisé dans buyer/seller_strength)
        bn.triple_ask = ReadStudyValue(sc, chart_footprint, NQ_FP_TRIPLE_ASK, 2);
        bn.triple_bid = ReadStudyValue(sc, chart_footprint, NQ_FP_TRIPLE_BID, 2);
        bn.volume_up = ReadStudyValue(sc, chart_footprint, NQ_FP_VOLUME_UP, 2);  // 🔧 FIX: subgraph 2 = Sum of Alerts (pas 0 = Color Bar/prix)
        bn.volume_down = ReadStudyValue(sc, chart_footprint, NQ_FP_VOLUME_DOWN, 2);
        bn.rotation_up = ReadStudyValue(sc, chart_footprint, NQ_FP_ROTATION_UP, 2);  // 🔧 FIX: subgraph 2 = Sum of Alerts
        bn.rotation_down = ReadStudyValue(sc, chart_footprint, NQ_FP_ROTATION_DOWN, 2);

        // 🆕 NQ: Ordres granulaires (+10, +30, +100)
        bn.ask_10 = ReadStudyValue(sc, chart_footprint, NQ_FP_ASK_10, 0);
        bn.bid_10 = ReadStudyValue(sc, chart_footprint, NQ_FP_BID_10, 0);
        bn.ask_30 = ReadStudyValue(sc, chart_footprint, NQ_FP_ASK_30, 0);
        bn.bid_30 = ReadStudyValue(sc, chart_footprint, NQ_FP_BID_30, 0);
        bn.ask_100 = ReadStudyValue(sc, chart_footprint, NQ_FP_ASK_100, 0);
        bn.bid_100 = ReadStudyValue(sc, chart_footprint, NQ_FP_BID_100, 0);
        bn.cluster_vol = ReadStudyValue(sc, chart_footprint, NQ_FP_CLUSTER_VOL, 0);

        // NQ: FPBS basique (subgraph 16=Ask%, 17=Bid%)
        bn.fpbs_ask_pct = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_ASK_PCT);
        bn.fpbs_bid_pct = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_BID_PCT);
        
        // 🆕 NQ: FPBS avancé (Delta, CVD, POC)
        bn.fpbs_delta = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_DELTA);
        bn.fpbs_delta_day = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_DELTA_DAY);
        bn.fpbs_cvd = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_CVD);
        bn.fpbs_poc = ReadStudyValue(sc, chart_footprint, NQ_FP_FPBS, FPBS_SG_POC_PRICE);  // 🔧 CORRIGÉ: POC PRICE, pas VOLUME!

        // === NQ BARRES (Chart 23) ===
        // 🔧 30/01/2026: FIX - sg2 = "Sum of Alerts" (COUNT), pas sg0 = prix!
        bn.long_down_up = ReadStudyValue(sc, chart_barres, NQ_BAR_LONG_DOWN_UP, 2);  // COUNT of patterns
        bn.long_up_down = ReadStudyValue(sc, chart_barres, NQ_BAR_LONG_UP_DOWN, 2);  // COUNT of patterns
        // 🔧 30/01/2026: FIX - Subgraphs corrigés depuis study_inventory
        // [AV] COLOR = sg2 ("Sum of Alerts")
        // EDGE ZONES = sg58 ("Count of Alerts") - PAS sg2!
        bn.bar_color_up = ReadStudyValue(sc, chart_barres, NQ_BAR_COLOR_UP, 2);
        bn.bar_color_down = ReadStudyValue(sc, chart_barres, NQ_BAR_COLOR_DOWN, 2);
        bn.bar_edge_buy = ReadStudyValue(sc, chart_barres, NQ_BAR_EDGE_BUY, 58);   // 🔧 FIX: sg58!
        bn.bar_edge_sell = ReadStudyValue(sc, chart_barres, NQ_BAR_EDGE_SELL, 58); // 🔧 FIX: sg58!

    } else {
        // === ES FOOTPRINT (Chart 28) ===
        // 🔧 27/01/2026: FIX - Subgraph 2 = COUNT (utilisé dans buyer/seller_strength)
        bn.double_ask = ReadStudyValue(sc, chart_footprint, ES_FP_DOUBLE_ASK, 2);
        bn.double_bid = ReadStudyValue(sc, chart_footprint, ES_FP_DOUBLE_BID, 2);
        bn.rotation_up = ReadStudyValue(sc, chart_footprint, ES_FP_ROTATION_UP, 2);  // 🔧 FIX: subgraph 2 = Sum of Alerts
        bn.rotation_down = ReadStudyValue(sc, chart_footprint, ES_FP_ROTATION_DOWN, 2);

        // ES: Gros ordres (seuils institutionnels)
        bn.ask_100 = ReadStudyValue(sc, chart_footprint, ES_FP_ASK_100, 0);
        bn.bid_100 = ReadStudyValue(sc, chart_footprint, ES_FP_BID_100, 0);
        bn.ask_150 = ReadStudyValue(sc, chart_footprint, ES_FP_ASK_150, 0);
        bn.bid_150 = ReadStudyValue(sc, chart_footprint, ES_FP_BID_150, 0);
        bn.ask_400 = ReadStudyValue(sc, chart_footprint, ES_FP_ASK_400, 0);
        bn.bid_400 = ReadStudyValue(sc, chart_footprint, ES_FP_BID_400, 0);
        bn.ask_1000 = ReadStudyValue(sc, chart_footprint, ES_FP_ASK_1000, 0);
        bn.bid_1000 = ReadStudyValue(sc, chart_footprint, ES_FP_BID_1000, 0);
        bn.cluster_vol = ReadStudyValue(sc, chart_footprint, ES_FP_CLUSTER_VOL, 0);
        
        // ES: Pas de +10/+30 (seulement NQ a ces niveaux granulaires)
        bn.ask_10 = 0;
        bn.bid_10 = 0;
        bn.ask_30 = 0;
        bn.bid_30 = 0;

        // ES: FPBS basique (subgraph 16=Ask%, 17=Bid%)
        bn.fpbs_ask_pct = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_ASK_PCT);
        bn.fpbs_bid_pct = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_BID_PCT);
        
        // 🆕 ES: FPBS avancé (Delta, CVD, POC)
        bn.fpbs_delta = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_DELTA);
        bn.fpbs_delta_day = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_DELTA_DAY);
        bn.fpbs_cvd = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_CVD);
        bn.fpbs_poc = ReadStudyValue(sc, chart_footprint, ES_FP_FPBS, FPBS_SG_POC_PRICE);  // 🔧 CORRIGÉ: POC PRICE, pas VOLUME!

        // === ES BARRES (Chart 25) ===
        // 🔧 30/01/2026: FIX - sg2 = "Sum of Alerts" (COUNT), pas sg0 = prix!
        bn.long_down_up = ReadStudyValue(sc, chart_barres, ES_BAR_LONG_DOWN_UP, 2);  // COUNT of patterns
        bn.long_up_down = ReadStudyValue(sc, chart_barres, ES_BAR_LONG_UP_DOWN, 2);  // COUNT of patterns
        // 🔧 30/01/2026: FIX - Subgraphs corrigés depuis study_inventory
        // [AV] COLOR = sg2 ("Sum of Alerts")
        // EDGE ZONES = sg58 ("Count of Alerts") - PAS sg2!
        bn.bar_color_up = ReadStudyValue(sc, chart_barres, ES_BAR_COLOR_UP, 2);
        bn.bar_color_down = ReadStudyValue(sc, chart_barres, ES_BAR_COLOR_DOWN, 2);
        bn.bar_edge_buy = ReadStudyValue(sc, chart_barres, ES_BAR_EDGE_BUY, 58);   // 🔧 FIX: sg58!
        bn.bar_edge_sell = ReadStudyValue(sc, chart_barres, ES_BAR_EDGE_SELL, 58); // 🔧 FIX: sg58!
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // COLLECTER EXTENSION LINES (Zones de réaction des gros)
    // ═══════════════════════════════════════════════════════════════════════════
    // Subgraph 1 = Extension Lines pour:
    //   - COLOR UP/DOWN (boules vertes/rouges)
    //   - LONG DOWN UP / LONG UP DOWN BAR (rectangles verts/rouges = reversals)
    // On scanne les dernières 50 barres pour trouver les extensions actives

    bn.num_ext_support = 0;
    bn.num_ext_resist = 0;
    bn.nearest_ext_support = 0;
    bn.nearest_ext_resist = 0;

    // === 🆕 INITIALISER RECTANGLES TRADABLES (LONG UP/DOWN BAR) ===
    bn.num_long_up_bar = 0;
    bn.num_long_down_bar = 0;
    bn.nearest_long_up_bar = 0;
    bn.nearest_long_down_bar = 0;
    bn.has_tradable_support = false;
    bn.has_tradable_resist = false;
    for (int i = 0; i < 10; i++) {
        bn.long_up_bar_ext[i] = 0;
        bn.long_down_bar_ext[i] = 0;
    }

    float current_price = footprint_data[SC_LAST][last_idx];
    int scan_bars = 50;  // Scanner les dernières 50 barres
    int start_bar = (last_idx > scan_bars) ? (last_idx - scan_bars) : 0;

    // --- Study IDs pour Extension Lines des reversals (LONG UP/DOWN BAR) ---
    // 🔧 30/01/2026: CORRIGÉ - Utilise les constantes ES_BAR_*/NQ_BAR_* définies plus haut
    // Chart 25 (ES Barres): LONG_DOWN_UP=38, LONG_UP_DOWN=39
    // Chart 23 (NQ Barres): LONG_DOWN_UP=23, LONG_UP_DOWN=24
    int STUDY_REVERSAL_SUPPORT = is_nq ? NQ_BAR_LONG_DOWN_UP : ES_BAR_LONG_DOWN_UP;  // LONG DOWN UP BAR (reversal V = Support)
    int STUDY_REVERSAL_RESIST = is_nq ? NQ_BAR_LONG_UP_DOWN : ES_BAR_LONG_UP_DOWN;   // LONG UP DOWN BAR (reversal ^ = Resist)

    // --- 🆕 Study IDs pour RECTANGLES TRADABLES (LONG UP/DOWN BAR) ---
    // Ces sont les VRAIS rectangles verts/rouges - NIVEAUX TRADABLES!
    // 🔧 30/01/2026: Utilise les constantes pour cohérence
    // Chart 25 (ES Barres): LONG_UP_BAR=18, LONG_DOWN_BAR=17
    // Chart 23 (NQ Barres): LONG_UP_BAR=18, LONG_DOWN_BAR=17
    int STUDY_LONG_UP_BAR = is_nq ? NQ_BAR_LONG_UP_BAR : ES_BAR_LONG_UP_BAR;      // Rectangle vert = SUPPORT TRADABLE
    int STUDY_LONG_DOWN_BAR = is_nq ? NQ_BAR_LONG_DOWN_BAR : ES_BAR_LONG_DOWN_BAR; // Rectangle rouge = RESISTANCE TRADABLE

    // --- Study IDs pour EDGE ZONES IMBALANCE (Extension Lines depuis Footprint) ---
    // 🔧 30/01/2026: CORRIGÉ - Utilise les constantes ES_FP_*/NQ_FP_*
    // ES Footprint (Chart 1): BUY=32, SELL=35
    // NQ Footprint (Chart 2): BUY=55, SELL=56
    int STUDY_EDGE_IMBALANCE_BUY = is_nq ? NQ_FP_EDGE_BUY : ES_FP_EDGE_BUY;     // EDGE ZONES BUY = Support
    int STUDY_EDGE_IMBALANCE_SELL = is_nq ? NQ_FP_EDGE_SELL : ES_FP_EDGE_SELL;  // EDGE ZONES SELL = Résistance

    // Helper lambda pour ajouter une extension sans doublon
    auto add_ext_support = [&](float ext_val) {
        if (ext_val > 0 && ext_val < current_price && bn.num_ext_support < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_ext_support; j++) {
                if (fabs(bn.ext_lines_support[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.ext_lines_support[bn.num_ext_support++] = ext_val;
            }
        }
    };

    auto add_ext_resist = [&](float ext_val) {
        if (ext_val > 0 && ext_val > current_price && bn.num_ext_resist < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_ext_resist; j++) {
                if (fabs(bn.ext_lines_resist[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.ext_lines_resist[bn.num_ext_resist++] = ext_val;
            }
        }
    };

    // 🆕 HELPERS pour RECTANGLES TRADABLES (séparés des boules/confluence)
    auto add_tradable_support = [&](float ext_val) {
        if (ext_val > 0 && ext_val < current_price && bn.num_long_up_bar < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_long_up_bar; j++) {
                if (fabs(bn.long_up_bar_ext[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.long_up_bar_ext[bn.num_long_up_bar++] = ext_val;
                // AUSSI ajouter aux extensions générales (rétrocompatibilité)
                add_ext_support(ext_val);
            }
        }
    };

    auto add_tradable_resist = [&](float ext_val) {
        if (ext_val > 0 && ext_val > current_price && bn.num_long_down_bar < 10) {
            bool duplicate = false;
            for (int j = 0; j < bn.num_long_down_bar; j++) {
                if (fabs(bn.long_down_bar_ext[j] - ext_val) < 0.5f) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                bn.long_down_bar_ext[bn.num_long_down_bar++] = ext_val;
                // AUSSI ajouter aux extensions générales (rétrocompatibilité)
                add_ext_resist(ext_val);
            }
        }
    };

    // Array pour lire les Extension Lines
    SCFloatArray study_array;
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 30/01/2026: Initialiser les arrays de boules pour règle subtile
    // ═══════════════════════════════════════════════════════════════════════════
    bn.num_color_up_prices = 0;
    bn.num_color_down_prices = 0;
    bn.green_base_price = 0;
    bn.red_base_price = 0;
    bn.bn_subtile_long_valid = true;
    bn.bn_subtile_short_valid = true;
    bn.subtile_long_reason[0] = '\0';
    bn.subtile_short_reason[0] = '\0';
    
    // Initialiser RANGE
    bn.is_range = false;
    bn.range_support = 0;
    bn.range_resistance = 0;
    bn.range_midpoint = 0;
    bn.range_size_pts = 0;
    bn.price_position_pct = 50.0f;
    bn.price_position = 1;  // MIDDLE par défaut

    // === 1. COLOR UP (boules vertes) = SUPPORT ===
    // 🆕 30/01/2026: Stocker TOUTES les boules pour règle subtile (pas de filtre prix)
    sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_COLOR_UP, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
            float price = study_array[i];
            if (price > 0) {
                // Stocker dans array dédié pour règle subtile (TOUTES les boules)
                if (bn.num_color_up_prices < 20) {
                    bool dup = false;
                    for (int j = 0; j < bn.num_color_up_prices; j++) {
                        if (fabs(bn.color_up_prices[j] - price) < 0.5f) { dup = true; break; }
                    }
                    if (!dup) bn.color_up_prices[bn.num_color_up_prices++] = price;
                }
                // AUSSI ajouter aux ext_lines (rétrocompatibilité)
                add_ext_support(price);
            }
        }
    }

    // === 2. COLOR DOWN (boules rouges) = RÉSISTANCE ===
    // 🆕 30/01/2026: Stocker TOUTES les boules pour règle subtile (pas de filtre prix)
    sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_COLOR_DOWN, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
            float price = study_array[i];
            if (price > 0) {
                // Stocker dans array dédié pour règle subtile (TOUTES les boules)
                if (bn.num_color_down_prices < 20) {
                    bool dup = false;
                    for (int j = 0; j < bn.num_color_down_prices; j++) {
                        if (fabs(bn.color_down_prices[j] - price) < 0.5f) { dup = true; break; }
                    }
                    if (!dup) bn.color_down_prices[bn.num_color_down_prices++] = price;
                }
                // AUSSI ajouter aux ext_lines (rétrocompatibilité)
                add_ext_resist(price);
            }
        }
    }

    // === 3. LONG DOWN UP BAR (rectangles verts = reversal haussier) = SUPPORT ===
    int barres_last_idx_ext = barres_data[0].GetArraySize() - 1;
    int barres_start = (barres_last_idx_ext > scan_bars) ? (barres_last_idx_ext - scan_bars) : 0;

    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_REVERSAL_SUPPORT, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            add_ext_support(study_array[i]);
        }
    }

    // === 4. LONG UP DOWN BAR (rectangles rouges = reversal baissier) = RÉSISTANCE ===
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_REVERSAL_RESIST, 1, study_array);
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            add_ext_resist(study_array[i]);
        }
    }

    // === 5. EDGE ZONES IMBALANCE BUY (imbalance 800% = TRÈS FORT) = SUPPORT ===
    // Les Edge Zones utilisent des "Triggers" (subgraph 0-9) pour stocker les niveaux
    for (int trigger = 0; trigger < 10; trigger++) {
        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, trigger, study_array);
        if (study_array.GetArraySize() > 0) {
            for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
                float edge_val = study_array[i];
                if (edge_val > 0) {
                    add_ext_support(edge_val);  // EDGE BUY = Support (acheteurs agressifs)
                }
            }
        }
    }

    // === 6. EDGE ZONES IMBALANCE SELL (imbalance 800% = TRÈS FORT) = RÉSISTANCE ===
    for (int trigger = 0; trigger < 10; trigger++) {
        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, trigger, study_array);
        if (study_array.GetArraySize() > 0) {
            for (int i = start_bar; i <= last_idx && i < study_array.GetArraySize(); i++) {
                float edge_val = study_array[i];
                if (edge_val > 0) {
                    add_ext_resist(edge_val);  // EDGE SELL = Résistance (vendeurs agressifs)
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 7. LONG UP BAR - RECTANGLES VERTS TRADABLES (depuis Chart Barres)
    // ═══════════════════════════════════════════════════════════════════════════
    // Ces sont les VRAIS rectangles verts - NIVEAUX TRADABLES à prioriser!
    // 🔧 30/01/2026: Essayer SG1 (Extension Lines) d'abord, puis SG0 (Color Bar) en fallback
    
    // Essai 1: SG1 = Extension Lines (niveaux prolongés)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_UP_BAR, 1, study_array);  // SG1 = Extension Lines
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_support(rect_val);  // Rectangle vert = SUPPORT TRADABLE
            }
        }
    }
    // Essai 2: SG0 = Color Bar (prix de la barre où le rectangle apparaît)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_UP_BAR, 0, study_array);  // SG0 = Color Bar
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_support(rect_val);  // Rectangle vert = SUPPORT TRADABLE (fallback)
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 8. LONG DOWN BAR - RECTANGLES ROUGES TRADABLES (depuis Chart Barres)
    // ═══════════════════════════════════════════════════════════════════════════
    // Ces sont les VRAIS rectangles rouges - NIVEAUX TRADABLES à prioriser!
    // 🔧 30/01/2026: Essayer SG1 (Extension Lines) d'abord, puis SG0 (Color Bar) en fallback
    
    // Essai 1: SG1 = Extension Lines (niveaux prolongés)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_DOWN_BAR, 1, study_array);  // SG1 = Extension Lines
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_resist(rect_val);  // Rectangle rouge = RESISTANCE TRADABLE
            }
        }
    }
    // Essai 2: SG0 = Color Bar (prix de la barre où le rectangle apparaît)
    sc.GetStudyArrayFromChartUsingID(chart_barres, STUDY_LONG_DOWN_BAR, 0, study_array);  // SG0 = Color Bar
    if (study_array.GetArraySize() > 0) {
        for (int i = barres_start; i <= barres_last_idx_ext && i < study_array.GetArraySize(); i++) {
            float rect_val = study_array[i];
            if (rect_val > 0) {
                add_tradable_resist(rect_val);  // Rectangle rouge = RESISTANCE TRADABLE (fallback)
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 COLLECTER GROS RECTANGLES EDGE ZONE (Adjacent Alert Highlight)
    // ═══════════════════════════════════════════════════════════════════════════
    // Subgraphs 48-57 contiennent les coordonnées des rectangles épais
    // 48,50,52,54,56 = Bottom | 49,51,53,55,57 = Top
    // Ces zones représentent des imbalances/absorptions massives

    bn.num_edge_rect_buy = 0;
    bn.num_edge_rect_sell = 0;
    bn.nearest_edge_rect_support = 0;
    bn.nearest_edge_rect_resist = 0;
    bn.price_in_edge_rect_buy = false;
    bn.price_in_edge_rect_sell = false;

    // Collecter rectangles BUY (support) - Subgraphs 48-56 (bottom/top pairs)
    for (int rect_idx = 0; rect_idx < 5 && bn.num_edge_rect_buy < 5; rect_idx++) {
        int sg_bottom = 48 + (rect_idx * 2);  // 48, 50, 52, 54, 56
        int sg_top = sg_bottom + 1;            // 49, 51, 53, 55, 57

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, sg_bottom, study_array);
        float bottom = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_BUY, sg_top, study_array);
        float top = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        if (bottom > 0 && top > bottom) {  // Rectangle valide
            bn.edge_rect_buy_bottom[bn.num_edge_rect_buy] = bottom;
            bn.edge_rect_buy_top[bn.num_edge_rect_buy] = top;
            bn.num_edge_rect_buy++;

            // Vérifier si prix dans ce rectangle
            if (current_price >= bottom && current_price <= top) {
                bn.price_in_edge_rect_buy = true;
            }

            // Trouver rectangle support le plus proche
            if (top < current_price) {  // Rectangle en dessous = support
                float dist = current_price - top;
                if (bn.nearest_edge_rect_support == 0 || dist < fabs(current_price - bn.nearest_edge_rect_support)) {
                    bn.nearest_edge_rect_support = top;
                }
            }
        }
    }

    // Collecter rectangles SELL (résistance)
    for (int rect_idx = 0; rect_idx < 5 && bn.num_edge_rect_sell < 5; rect_idx++) {
        int sg_bottom = 48 + (rect_idx * 2);
        int sg_top = sg_bottom + 1;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, sg_bottom, study_array);
        float bottom = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        sc.GetStudyArrayFromChartUsingID(chart_footprint, STUDY_EDGE_IMBALANCE_SELL, sg_top, study_array);
        float top = (study_array.GetArraySize() > last_idx) ? study_array[last_idx] : 0;

        if (bottom > 0 && top > bottom) {  // Rectangle valide
            bn.edge_rect_sell_bottom[bn.num_edge_rect_sell] = bottom;
            bn.edge_rect_sell_top[bn.num_edge_rect_sell] = top;
            bn.num_edge_rect_sell++;

            // Vérifier si prix dans ce rectangle
            if (current_price >= bottom && current_price <= top) {
                bn.price_in_edge_rect_sell = true;
            }

            // Trouver rectangle résistance le plus proche
            if (bottom > current_price) {  // Rectangle au dessus = résistance
                float dist = bottom - current_price;
                if (bn.nearest_edge_rect_resist == 0 || dist < fabs(bn.nearest_edge_rect_resist - current_price)) {
                    bn.nearest_edge_rect_resist = bottom;
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 BATAILLE NAVALE AVANCÉE - ANALYSE CONFIGURATION SPATIALE
    // ═══════════════════════════════════════════════════════════════════════════

    // --- 1. Trouver les extrêmes des zones (plus bas BUY, plus haut SELL) ---
    bn.lowest_edge_buy = 999999.0f;
    bn.highest_edge_sell = 0.0f;

    for (int i = 0; i < bn.num_edge_rect_buy; i++) {
        if (bn.edge_rect_buy_bottom[i] < bn.lowest_edge_buy) {
            bn.lowest_edge_buy = bn.edge_rect_buy_bottom[i];
        }
    }
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0 && bn.ext_lines_support[i] < bn.lowest_edge_buy) {
            bn.lowest_edge_buy = bn.ext_lines_support[i];
        }
    }
    if (bn.lowest_edge_buy > 900000.0f) bn.lowest_edge_buy = 0;

    for (int i = 0; i < bn.num_edge_rect_sell; i++) {
        if (bn.edge_rect_sell_top[i] > bn.highest_edge_sell) {
            bn.highest_edge_sell = bn.edge_rect_sell_top[i];
        }
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > bn.highest_edge_sell) {
            bn.highest_edge_sell = bn.ext_lines_resist[i];
        }
    }

    // --- 2. Règle "Pas de boule opposée sous/dessus" ---
    // LONG valide = PAS de edge_sell SOUS le plus bas edge_buy
    bn.bn_attack_long_valid = true;
    if (bn.lowest_edge_buy > 0 && bn.num_edge_rect_buy > 0) {
        // Vérifier s'il y a un rectangle SELL sous le plus bas BUY
        for (int i = 0; i < bn.num_edge_rect_sell; i++) {
            if (bn.edge_rect_sell_top[i] < bn.lowest_edge_buy) {
                bn.bn_attack_long_valid = false;  // ❌ Boule rouge sous le vert!
                break;
            }
        }
    }

    // SHORT valide = PAS de edge_buy AU-DESSUS du plus haut edge_sell
    bn.bn_attack_short_valid = true;
    if (bn.highest_edge_sell > 0 && bn.num_edge_rect_sell > 0) {
        for (int i = 0; i < bn.num_edge_rect_buy; i++) {
            if (bn.edge_rect_buy_bottom[i] > bn.highest_edge_sell) {
                bn.bn_attack_short_valid = false;  // ❌ Boule verte au-dessus du rouge!
                break;
            }
        }
    }

    // --- 3. Comptage de l'empilement (zones empilées = attaque coordonnée) ---
    bn.stacked_buy_zones = bn.num_edge_rect_buy;
    bn.stacked_sell_zones = bn.num_edge_rect_sell;

    // Force de l'attaque basée sur empilement + domination
    bn.attack_strength_buy = 0.0f;
    bn.attack_strength_sell = 0.0f;

    if (bn.stacked_buy_zones >= 3) {
        bn.attack_strength_buy = 1.0f;  // 3+ rectangles = attaque MASSIVE
    } else if (bn.stacked_buy_zones == 2) {
        bn.attack_strength_buy = 0.7f;  // 2 rectangles = attaque forte
    } else if (bn.stacked_buy_zones == 1) {
        bn.attack_strength_buy = 0.4f;  // 1 rectangle = zone isolée
    }
    // Bonus si edge_dominant_buy
    if (bn.edge_dominant_buy) bn.attack_strength_buy += 0.2f;
    if (bn.attack_strength_buy > 1.0f) bn.attack_strength_buy = 1.0f;

    if (bn.stacked_sell_zones >= 3) {
        bn.attack_strength_sell = 1.0f;
    } else if (bn.stacked_sell_zones == 2) {
        bn.attack_strength_sell = 0.7f;
    } else if (bn.stacked_sell_zones == 1) {
        bn.attack_strength_sell = 0.4f;
    }
    if (bn.edge_dominant_sell) bn.attack_strength_sell += 0.2f;
    if (bn.attack_strength_sell > 1.0f) bn.attack_strength_sell = 1.0f;

    // --- 4. Cohérence directionnelle ---
    // Compter combien de signaux pointent dans chaque direction
    int bullish_signals = 0;
    int bearish_signals = 0;

    // 🔧 30/01/2026: FIX - Utiliser les COUNTS de rectangles, pas les PRIX
    if (bn.num_edge_rect_buy > bn.num_edge_rect_sell) bullish_signals++; 
    else if (bn.num_edge_rect_sell > bn.num_edge_rect_buy) bearish_signals++;
    if (bn.color_up > bn.color_down) bullish_signals++; else if (bn.color_down > bn.color_up) bearish_signals++;
    if (bn.rotation_up > bn.rotation_down) bullish_signals++; else if (bn.rotation_down > bn.rotation_up) bearish_signals++;
    if (bn.absorb_bid > bn.absorb_ask) bullish_signals++; else if (bn.absorb_ask > bn.absorb_bid) bearish_signals++;
    if (bn.long_down_up > bn.long_up_down) bullish_signals++; else if (bn.long_up_down > bn.long_down_up) bearish_signals++;
    if (bn.num_edge_rect_buy > bn.num_edge_rect_sell) bullish_signals++;
    else if (bn.num_edge_rect_sell > bn.num_edge_rect_buy) bearish_signals++;

    int total_signals = bullish_signals + bearish_signals;
    bn.all_signals_bullish = (bullish_signals >= 4 && bearish_signals == 0);
    bn.all_signals_bearish = (bearish_signals >= 4 && bullish_signals == 0);

    if (total_signals > 0) {
        bn.directional_coherence = (float)(bullish_signals - bearish_signals) / (float)total_signals;
    } else {
        bn.directional_coherence = 0.0f;
    }

    // Trouver la plus proche de chaque côté
    if (bn.num_ext_support > 0) {
        bn.nearest_ext_support = bn.ext_lines_support[0];
        for (int i = 1; i < bn.num_ext_support; i++) {
            if (bn.ext_lines_support[i] > bn.nearest_ext_support) {
                bn.nearest_ext_support = bn.ext_lines_support[i];  // Support le plus haut = plus proche
            }
        }
    }
    if (bn.num_ext_resist > 0) {
        bn.nearest_ext_resist = bn.ext_lines_resist[0];
        for (int i = 1; i < bn.num_ext_resist; i++) {
            if (bn.ext_lines_resist[i] < bn.nearest_ext_resist) {
                bn.nearest_ext_resist = bn.ext_lines_resist[i];  // Résistance la plus basse = plus proche
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 30/01/2026: RÈGLE SUBTILE AVEC LES BOULES (Alignement Python)
    // - LONG: Pas de boule ROUGE sous la BASE VERTE
    // - SHORT: Pas de boule VERTE au-dessus de la BASE ROUGE
    // ═══════════════════════════════════════════════════════════════════════════
    
    // 1. Trouver la BASE VERTE = max(boules vertes SOUS le prix)
    bn.green_base_price = 0;
    for (int i = 0; i < bn.num_color_up_prices; i++) {
        if (bn.color_up_prices[i] < current_price && bn.color_up_prices[i] > bn.green_base_price) {
            bn.green_base_price = bn.color_up_prices[i];
        }
    }
    
    // 2. Trouver la BASE ROUGE = min(boules rouges AU-DESSUS du prix)
    bn.red_base_price = 999999.0f;
    for (int i = 0; i < bn.num_color_down_prices; i++) {
        if (bn.color_down_prices[i] > current_price && bn.color_down_prices[i] < bn.red_base_price) {
            bn.red_base_price = bn.color_down_prices[i];
        }
    }
    if (bn.red_base_price > 900000.0f) bn.red_base_price = 0;
    
    // 3. RÈGLE SUBTILE LONG: Pas de rouge sous la base verte
    bn.bn_subtile_long_valid = true;
    if (bn.green_base_price > 0) {
        for (int i = 0; i < bn.num_color_down_prices; i++) {
            if (bn.color_down_prices[i] < bn.green_base_price) {
                bn.bn_subtile_long_valid = false;
                snprintf(bn.subtile_long_reason, sizeof(bn.subtile_long_reason),
                         "Rouge %.2f sous base verte %.2f", bn.color_down_prices[i], bn.green_base_price);
                break;
            }
        }
    }
    
    // 4. RÈGLE SUBTILE SHORT: Pas de vert au-dessus de la base rouge
    bn.bn_subtile_short_valid = true;
    if (bn.red_base_price > 0) {
        for (int i = 0; i < bn.num_color_up_prices; i++) {
            if (bn.color_up_prices[i] > bn.red_base_price) {
                bn.bn_subtile_short_valid = false;
                snprintf(bn.subtile_short_reason, sizeof(bn.subtile_short_reason),
                         "Verte %.2f au-dessus base rouge %.2f", bn.color_up_prices[i], bn.red_base_price);
                break;
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 30/01/2026: MODE RANGE - Détection et position (Alignement Python)
    // Range = min(ext_lines_support) à max(ext_lines_resist)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Paramètres de range selon symbole
    float range_min_pts = is_nq ? 20.0f : 5.0f;   // NQ: 20-200, ES: 5-50
    float range_max_pts = is_nq ? 200.0f : 50.0f;
    float near_pct = 15.0f;  // 15% = NEAR_SUPPORT ou NEAR_RESISTANCE
    
    // Trouver min support et max résistance
    float min_support = 999999.0f;
    float max_resist = 0.0f;
    
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0 && bn.ext_lines_support[i] < min_support) {
            min_support = bn.ext_lines_support[i];
        }
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > max_resist) {
            max_resist = bn.ext_lines_resist[i];
        }
    }
    
    // Calculer le range
    if (min_support < 900000.0f && max_resist > 0 && max_resist > min_support) {
        float range_size = max_resist - min_support;
        
        // Valider la taille du range
        if (range_size >= range_min_pts && range_size <= range_max_pts) {
            bn.is_range = true;
            bn.range_support = min_support;
            bn.range_resistance = max_resist;
            bn.range_midpoint = (min_support + max_resist) / 2.0f;
            bn.range_size_pts = range_size;
            
            // Position du prix dans le range (0% = support, 100% = résistance)
            bn.price_position_pct = ((current_price - min_support) / range_size) * 100.0f;
            if (bn.price_position_pct < 0) bn.price_position_pct = 0;
            if (bn.price_position_pct > 100) bn.price_position_pct = 100;
            
            // Déterminer la zone
            if (bn.price_position_pct <= near_pct) {
                bn.price_position = 0;  // NEAR_SUPPORT
            } else if (bn.price_position_pct >= (100.0f - near_pct)) {
                bn.price_position = 2;  // NEAR_RESISTANCE
            } else {
                bn.price_position = 1;  // MIDDLE
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 TROUVER RECTANGLES TRADABLES LES PLUS PROCHES
    // ═══════════════════════════════════════════════════════════════════════════
    float tick_size = is_nq ? 0.25f : 0.25f;  // Tick size pour calculs
    float proximity_threshold = is_nq ? 30.0f : 8.0f;  // 30 pts NQ, 8 pts ES

    if (bn.num_long_up_bar > 0) {
        bn.nearest_long_up_bar = bn.long_up_bar_ext[0];
        for (int i = 1; i < bn.num_long_up_bar; i++) {
            if (bn.long_up_bar_ext[i] > bn.nearest_long_up_bar) {
                bn.nearest_long_up_bar = bn.long_up_bar_ext[i];  // Support le plus haut = plus proche
            }
        }
        // Vérifier si assez proche pour être "tradable"
        float dist_support = current_price - bn.nearest_long_up_bar;
        bn.has_tradable_support = (dist_support > 0 && dist_support <= proximity_threshold);
    }

    if (bn.num_long_down_bar > 0) {
        bn.nearest_long_down_bar = bn.long_down_bar_ext[0];
        for (int i = 1; i < bn.num_long_down_bar; i++) {
            if (bn.long_down_bar_ext[i] < bn.nearest_long_down_bar) {
                bn.nearest_long_down_bar = bn.long_down_bar_ext[i];  // Résistance la plus basse = plus proche
            }
        }
        // Vérifier si assez proche pour être "tradable"
        float dist_resist = bn.nearest_long_down_bar - current_price;
        bn.has_tradable_resist = (dist_resist > 0 && dist_resist <= proximity_threshold);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // CALCUL SCORE BN COMPLET - Toutes données utilisées
    // ═══════════════════════════════════════════════════════════════════════════

    // === 1. SIGNAUX FOOTPRINT (base) ===
    // 🔧 30/01/2026: FIX - edge_buy/edge_sell sont des PRIX, pas des COUNTS!
    //               Utiliser num_edge_rect_buy/sell * poids comme proxy pour l'activité edge
    float edge_weight = 50.0f;  // Un rectangle edge ≈ signal fort
    float buyer_strength = (bn.num_edge_rect_buy * edge_weight) + bn.color_up + bn.absorb_bid;
    float seller_strength = (bn.num_edge_rect_sell * edge_weight) + bn.color_down + bn.absorb_ask;

    // === 2. MOMENTUM (rotation) - CRITIQUE ===
    // Le momentum donne la direction court-terme
    bn.momentum_score = 0;
    float rotation_total = bn.rotation_up + bn.rotation_down;
    if (rotation_total > 0) {
        bn.momentum_score = (bn.rotation_up - bn.rotation_down) / rotation_total;
    }
    // Ajouter au score (poids x0.5 pour normaliser)
    buyer_strength += bn.rotation_up * 0.5f;
    seller_strength += bn.rotation_down * 0.5f;

    // === 3. REVERSALS (long_down_up/up_down) - CRITIQUE x2 ===
    // Les reversals sont des signaux FORTS de retournement
    bn.reversal_score = 0;
    if (bn.long_down_up > 0 || bn.long_up_down > 0) {
        bn.reversal_score = (bn.long_down_up - bn.long_up_down) / fmax(1.0f, bn.long_down_up + bn.long_up_down);
    }
    // Poids x2 car signal de retournement institutionnel
    buyer_strength += bn.long_down_up * 2.0f;
    seller_strength += bn.long_up_down * 2.0f;

    // === 4. SIGNAUX SPÉCIFIQUES NQ/ES ===
    if (is_nq) {
        buyer_strength += bn.triple_bid + bn.volume_up;
        seller_strength += bn.triple_ask + bn.volume_down;
    } else {
        buyer_strength += bn.double_bid;
        seller_strength += bn.double_ask;
    }

    // === 5. GROS ORDRES (Pression institutionnelle) ===
    // Les gros ordres montrent l'intérêt des institutionnels
    bn.institutional_pressure = 0;
    float inst_buy = bn.bid_100 + bn.bid_150 * 1.5f + bn.bid_400 * 2.0f + bn.bid_1000 * 3.0f;
    float inst_sell = bn.ask_100 + bn.ask_150 * 1.5f + bn.ask_400 * 2.0f + bn.ask_1000 * 3.0f;
    if (inst_buy + inst_sell > 0) {
        bn.institutional_pressure = (inst_buy - inst_sell) / (inst_buy + inst_sell);
    }
    // Ajouter avec poids progressif
    buyer_strength += inst_buy * 0.3f;
    seller_strength += inst_sell * 0.3f;

    // === 6. FPBS (Force de pression) ===
    // Déséquilibre FPBS confirme la direction
    if (bn.fpbs_ask_pct > 0 || bn.fpbs_bid_pct > 0) {
        buyer_strength += bn.fpbs_bid_pct * 10.0f;  // Normaliser sur ~1
        seller_strength += bn.fpbs_ask_pct * 10.0f;
    }
    
    // === 🆕 6b. FPBS DELTA (Direction de la barre) ===
    // Delta > 0 = Plus d'achats que de ventes sur cette barre
    // Delta < 0 = Plus de ventes que d'achats sur cette barre
    if (bn.fpbs_delta != 0) {
        // Normalisation: Delta peut être très grand (milliers), on normalise
        float delta_normalized = bn.fpbs_delta / 1000.0f;  // Échelle ~1
        if (delta_normalized > 3.0f) delta_normalized = 3.0f;  // Cap
        if (delta_normalized < -3.0f) delta_normalized = -3.0f;
        
        if (delta_normalized > 0) {
            buyer_strength += delta_normalized * 0.5f;  // Delta positif = acheteurs
        } else {
            seller_strength += (-delta_normalized) * 0.5f;  // Delta négatif = vendeurs
        }
    }
    
    // === 🆕 6c. FPBS DELTA_DAY (Biais journalier) ===
    // Delta_Day cumulé indique le biais global de la journée
    if (bn.fpbs_delta_day != 0) {
        float delta_day_normalized = bn.fpbs_delta_day / 10000.0f;  // Plus grand car cumulé
        if (delta_day_normalized > 2.0f) delta_day_normalized = 2.0f;
        if (delta_day_normalized < -2.0f) delta_day_normalized = -2.0f;
        
        if (delta_day_normalized > 0) {
            buyer_strength += delta_day_normalized * 0.3f;  // Biais acheteur journalier
        } else {
            seller_strength += (-delta_day_normalized) * 0.3f;  // Biais vendeur journalier
        }
    }

    // === 7. SIGNAUX BARRES (confirmation) ===
    // Les barres donnent une vue plus "macro"
    buyer_strength += bn.bar_color_up * 0.3f + bn.bar_edge_buy * 0.5f;
    seller_strength += bn.bar_color_down * 0.3f + bn.bar_edge_sell * 0.5f;

    // === 8. CLUSTER VOLUME (zones d'intérêt) ===
    // Les clusters ajoutent de la confluence
    if (bn.cluster_vol > 0) {
        // Cluster renforce le côté dominant
        if (buyer_strength > seller_strength) {
            buyer_strength += bn.cluster_vol * 0.2f;
        } else {
            seller_strength += bn.cluster_vol * 0.2f;
        }
    }

    float total = buyer_strength + seller_strength;

    // === FIX BUG BN SCORE ±1.0 ===
    // Compter les signaux valides de chaque côté
    // 🔧 30/01/2026: FIX - Utiliser num_edge_rect_buy/sell au lieu de edge_buy/sell (qui sont des PRIX)
    int buyer_signals = (bn.num_edge_rect_buy > 0 ? 1 : 0) + (bn.color_up > 0 ? 1 : 0) +
                        (bn.absorb_bid > 0 ? 1 : 0) + (bn.rotation_up > 0 ? 1 : 0);
    int seller_signals = (bn.num_edge_rect_sell > 0 ? 1 : 0) + (bn.color_down > 0 ? 1 : 0) +
                         (bn.absorb_ask > 0 ? 1 : 0) + (bn.rotation_down > 0 ? 1 : 0);

    // Si un côté n'a AUCUN signal mais l'autre oui = données incomplètes
    // Dans ce cas, score = 0 (neutre) au lieu de ±1.0
    bool data_incomplete = (buyer_signals == 0 && seller_signals > 0) ||
                          (seller_signals == 0 && buyer_signals > 0);

    if (total > 0 && !data_incomplete) {
        bn.score = (buyer_strength - seller_strength) / total;
        // Clamp pour éviter les extrêmes dus à des artefacts
        if (bn.score > 0.95f) bn.score = 0.95f;
        if (bn.score < -0.95f) bn.score = -0.95f;
    } else if (data_incomplete) {
        // Données incomplètes = ne pas utiliser, score neutre
        bn.score = 0.0f;
        bn.signal = 0;
        return;  // Exit early
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 PRO FEATURE 1: MOMENTUM DELTA (détection changements)
    // ═══════════════════════════════════════════════════════════════════════════
    float current_momentum = bn.color_up - bn.color_down;
    float prev_momentum = bn.prev_color_up - bn.prev_color_down;
    bn.color_momentum = current_momentum - prev_momentum;

    // Détecter shift de momentum (changement significatif)
    if (bn.color_momentum > 5.0f) {
        bn.momentum_shift = 1.0f;   // Shift BULLISH!
        bn.score += 0.05f;          // Bonus au score
    } else if (bn.color_momentum < -5.0f) {
        bn.momentum_shift = -1.0f;  // Shift BEARISH!
        bn.score -= 0.05f;          // Malus au score
    } else {
        bn.momentum_shift = 0.0f;   // Stable
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 PRO FEATURE 2: RECTANGLES FRAIS (détection nouvelles zones)
    // ═══════════════════════════════════════════════════════════════════════════
    // Un rectangle FRAIS = zone institutionnelle VIENT d'être touchée
    bn.fresh_rectangle_buy = (bn.double_bid > bn.prev_double_bid);
    bn.fresh_rectangle_sell = (bn.double_ask > bn.prev_double_ask);

    if (bn.fresh_rectangle_buy) {
        bn.score += 0.08f;  // GROS bonus! Zone achat frais = signal fort
        bn.fresh_rect_age_bars = 0;
    }
    if (bn.fresh_rectangle_sell) {
        bn.score -= 0.08f;  // GROS malus! Zone vente frais = signal fort
        bn.fresh_rect_age_bars = 0;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 PRO FEATURE 3: EDGE ZONE RATIO (domination claire)
    // 🔧 30/01/2026: FIX - Utilise num_edge_rect_buy/sell (COUNTS réels) au lieu de
    //               edge_buy/edge_sell qui retournent des PRIX (pas de sg "Count" pour EDGE ZONES)
    // ═══════════════════════════════════════════════════════════════════════════
    int edge_count_buy = bn.num_edge_rect_buy;
    int edge_count_sell = bn.num_edge_rect_sell;
    int edge_total = edge_count_buy + edge_count_sell;
    
    if (edge_total > 0) {
        bn.edge_ratio = (float)edge_count_buy / (float)edge_total;

        // Domination claire si ratio > 0.65 ou < 0.35
        bn.edge_dominant_buy = (bn.edge_ratio > 0.65f);
        bn.edge_dominant_sell = (bn.edge_ratio < 0.35f);

        // Bonus/Malus pour domination
        if (bn.edge_dominant_buy) {
            bn.score += 0.04f;  // Acheteurs dominent (plus de rectangles verts)
        }
        if (bn.edge_dominant_sell) {
            bn.score -= 0.04f;  // Vendeurs dominent (plus de rectangles rouges)
        }
    } else {
        bn.edge_ratio = 0.5f;
        bn.edge_dominant_buy = false;
        bn.edge_dominant_sell = false;
    }
    
    // 🆕 Stocker le premier trigger actif pour référence (prix du niveau edge)
    // Note: edge_buy/edge_sell contiennent le prix du trigger 0 s'il existe
    // Ce n'est PAS un count mais le prix de la zone - utile pour SL/TP

    // Sauvegarder valeurs pour prochaine itération
    bn.prev_color_up = bn.color_up;
    bn.prev_color_down = bn.color_down;
    bn.prev_double_bid = bn.double_bid;
    bn.prev_double_ask = bn.double_ask;

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 CVD & POC ANALYSIS (Confirmation de Tendance)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // --- CVD SLOPE CALCULATION ---
    // Calcule la pente du CVD pour détecter la tendance et les divergences
    // CVD slope > 0 = acheteurs accumulent = bullish
    // CVD slope < 0 = vendeurs accumulent = bearish
    // Divergence = prix monte + CVD baisse (ou inverse) = DANGER!
    
    bn.cvd_slope = 0;
    bn.cvd_divergence = false;
    bn.cvd_trend_score = 0;
    
    if (bn.fpbs_cvd != 0 && bn.prev_cvd != 0) {
        // Slope = variation du CVD (normalisé)
        bn.cvd_slope = bn.fpbs_cvd - bn.prev_cvd;
        
        // Trend score basé sur la magnitude du slope
        // +100 à +500 = légèrement bullish → +500 à +2000 = fortement bullish
        if (bn.cvd_slope > 100) {
            bn.cvd_trend_score = fmin(bn.cvd_slope / 500.0f, 1.0f);  // Max 1.0
        } else if (bn.cvd_slope < -100) {
            bn.cvd_trend_score = fmax(bn.cvd_slope / 500.0f, -1.0f);  // Min -1.0
        }
        
        // Détection DIVERGENCE (CVD vs Prix)
        // Forte divergence = CVD slope > 500 dans direction opposée au prix
        // On utilise le score BN comme proxy du mouvement de prix
        if (bn.score > 0.1f && bn.cvd_slope < -500) {
            // Prix monte (score bullish) MAIS CVD chute fortement = DIVERGENCE BEARISH
            bn.cvd_divergence = true;
        }
        if (bn.score < -0.1f && bn.cvd_slope > 500) {
            // Prix baisse (score bearish) MAIS CVD monte fortement = DIVERGENCE BULLISH
            bn.cvd_divergence = true;
        }
    }
    
    // 🔧 FIX CVD SLOPE: Sauvegarder CVD pour prochaine itération (persistant!)
    // NOTE: Ne PAS écraser bn.prev_cvd ici - on garde la valeur originale pour le diagnostic!
    // bn.prev_cvd = bn.fpbs_cvd;  // ❌ Supprimé pour debug
    sc.SetPersistentFloat(cvd_persist_idx, bn.fpbs_cvd);  // Persiste entre les appels!
    
    // --- POC CONFIRMATION ---
    // Compare le prix actuel (Close) avec le POC de la bougie
    // Close > POC = acheteurs ont gagné la bougie = BULLISH confirmation
    // Close < POC = vendeurs ont gagné la bougie = BEARISH confirmation
    
    bn.poc_confirm = 0;  // Neutre par défaut
    
    if (bn.fpbs_poc > 0 && current_price > 0) {
        float poc_distance = current_price - bn.fpbs_poc;
        float tick_threshold = is_nq ? 2.0f : 0.5f;  // 2 ticks NQ, 0.5 pts ES
        
        if (poc_distance > tick_threshold) {
            bn.poc_confirm = 1;   // BULLISH - Close au-dessus POC
        } else if (poc_distance < -tick_threshold) {
            bn.poc_confirm = -1;  // BEARISH - Close en-dessous POC
        }
        // Sinon reste 0 (neutre - Close ≈ POC)
    }

    // Re-clamp après bonus/malus
    if (bn.score > 0.95f) bn.score = 0.95f;
    if (bn.score < -0.95f) bn.score = -0.95f;

    // Signal: 1=bullish, -1=bearish, 0=neutral
    // 🔧 27/01/2026: Seuils assouplis 0.15 → 0.08 (London/Asia ont scores plus bas)
    if (bn.score > 0.08f) bn.signal = 1;
    else if (bn.score < -0.08f) bn.signal = -1;
    else bn.signal = 0;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6: COLLECTE DONNÉES MENTHORQ
// ═══════════════════════════════════════════════════════════════════════════════

void CollectMenthorQ_Data(SCStudyInterfaceRef sc, int main_chart, MenthorQ_Data& mq, bool is_nq) {
    memset(&mq, 0, sizeof(MenthorQ_Data));

    SCFloatArray study_array;
    SCGraphData chart_data;
    sc.GetChartBaseData(main_chart, chart_data);

    int last_idx = chart_data[0].GetArraySize() - 1;
    if (last_idx < 0) return;

    // ═══════════════════════════════════════════════════════════════════════════
    // STUDY IDs MenthorQ - VRAIS IDs DES CHARTS (scan du 17/01/2026)
    // ═══════════════════════════════════════════════════════════════════════════
    // MenthorQ Gamma Levels subgraphs:
    //   0=Call Resistance, 1=Put Support, 2=HVL, 3=1D Min, 4=1D Max,
    //   5=Call 0DTE/Gamma Wall, 6=Put 0DTE, 7=HVL 0DTE, 8=Gamma Wall 0DTE,
    //   9-18=GEX 1-10
    // MenthorQ Blind Spots subgraphs: 0-9=BL 1-10
    // VWAP subgraphs: 0=VWAP, 1=+1σ, 2=-1σ, 3=+2σ, 4=-2σ...

    int STUDY_MQ_GAMMA, STUDY_MQ_BLINDSPOT, STUDY_MQ_VWAP;

    if (is_nq) {
        // Chart 4 - NQ Barres
        STUDY_MQ_GAMMA = 25;      // MenthorQ Gamma Levels
        STUDY_MQ_BLINDSPOT = 2;   // MenthorQ Blind Spots
        STUDY_MQ_VWAP = 1;        // VWAP
    } else {
        // Chart 3 - ES Barres
        STUDY_MQ_GAMMA = 2;       // MenthorQ Gamma Levels
        STUDY_MQ_BLINDSPOT = 22;  // MenthorQ Blind Spots
        STUDY_MQ_VWAP = 1;        // VWAP
    }

    // Call/Put Resistance/Support (subgraphs 0, 1)
    mq.call_resistance = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 0);
    mq.put_support = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 1);

    // HVL (subgraph 2)
    mq.hvl = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 2);

    // 🔧 28/01/2026: FIX - Lire TOUS les niveaux 0DTE (manquaient!)
    // Ces niveaux sont CRITIQUES pour détecter les obstacles intraday!
    // Subgraphs MenthorQ Gamma:
    //   5 = call_resistance_0dte
    //   6 = put_support_0dte  
    //   7 = hvl_0dte
    //   8 = gamma_wall_0dte
    mq.call_resistance_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 5);
    mq.put_support_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 6);
    mq.hvl_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 7);
    mq.gamma_wall_0dte = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 8);

    // 1D Min/Max (subgraphs 3, 4)
    mq.day_min = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 3);
    mq.day_max = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 4);

    // GEX 1-10 (subgraphs 9-18)
    for (int i = 0; i < 10; i++) {
        mq.gex[i] = ReadStudyValue(sc, main_chart, STUDY_MQ_GAMMA, 9 + i);
    }

    // VWAP et bandes
    mq.vwap = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 0);
    mq.vwap_up1 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 1);
    mq.vwap_dn1 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 2);
    mq.vwap_up2 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 3);
    mq.vwap_dn2 = ReadStudyValue(sc, main_chart, STUDY_MQ_VWAP, 4);

    // ═══════════════════════════════════════════════════════════════════════════
    // Value Area (VAH/VAL) - PARITÉ PYTHON
    // ═══════════════════════════════════════════════════════════════════════════
    // TODO: Ajuster Study ID si nécessaire selon votre configuration Volume Profile
    // Typiquement c'est un Volume Profile study avec subgraphs VAH/VAL/POC
    int STUDY_VP = is_nq ? 3 : 3;  // Volume Profile study ID (à ajuster)

    // VAH subgraph typiquement index 0 ou 1
    float vah_tmp = ReadStudyValue(sc, main_chart, STUDY_VP, 0);
    if (vah_tmp > 0) mq.vah = vah_tmp;

    // VAL subgraph typiquement index 1 ou 2
    float val_tmp = ReadStudyValue(sc, main_chart, STUDY_VP, 1);
    if (val_tmp > 0) mq.val = val_tmp;

    // Blind Spots (subgraphs 0-9 = BL 1-10)
    for (int i = 0; i < 9; i++) {
        mq.blind_spots[i] = ReadStudyValue(sc, main_chart, STUDY_MQ_BLINDSPOT, i);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6.4: CALCUL NEXT_WALL (PARITÉ PYTHON)
// ═══════════════════════════════════════════════════════════════════════════════
// next_wall = niveau MenthorQ le plus important ET le plus proche du prix actuel
// Priorité: HVL (5pts), GEX_TOP (4pts), Put/Call (3pts), Gamma Wall (3pts)

void CalculateNextWall(MenthorQ_Data& mq, float current_price) {
    // Structure pour stocker les candidats
    struct WallCandidate {
        float price;
        int importance;  // Points d'importance
        int side;        // 0=call/resist, 1=put/support
    };

    std::vector<WallCandidate> candidates;

    // HVL - importance max (5 points)
    if (mq.hvl > 0) {
        int side = (mq.hvl > current_price) ? 0 : 1;  // Au-dessus = résistance
        candidates.push_back({mq.hvl, 5, side});
    }
    if (mq.hvl_0dte > 0 && fabs(mq.hvl_0dte - mq.hvl) > 1.0f) {
        int side = (mq.hvl_0dte > current_price) ? 0 : 1;
        candidates.push_back({mq.hvl_0dte, 5, side});
    }

    // GEX TOP 1-3 (4 points)
    for (int i = 0; i < 3; i++) {
        if (mq.gex[i] > 0) {
            int side = (mq.gex[i] > current_price) ? 0 : 1;
            candidates.push_back({mq.gex[i], 4, side});
        }
    }

    // Call/Put Resistance/Support (3 points)
    if (mq.call_resistance > 0) {
        candidates.push_back({mq.call_resistance, 3, 0});  // Toujours résistance
    }
    if (mq.put_support > 0) {
        candidates.push_back({mq.put_support, 3, 1});  // Toujours support
    }
    if (mq.call_resistance_0dte > 0 && fabs(mq.call_resistance_0dte - mq.call_resistance) > 1.0f) {
        candidates.push_back({mq.call_resistance_0dte, 3, 0});
    }
    if (mq.put_support_0dte > 0 && fabs(mq.put_support_0dte - mq.put_support) > 1.0f) {
        candidates.push_back({mq.put_support_0dte, 3, 1});
    }

    // Gamma Walls (3 points)
    if (mq.gamma_wall > 0) {
        int side = (mq.gamma_wall > current_price) ? 0 : 1;
        candidates.push_back({mq.gamma_wall, 3, side});
    }
    if (mq.gamma_wall_0dte > 0 && fabs(mq.gamma_wall_0dte - mq.gamma_wall) > 1.0f) {
        int side = (mq.gamma_wall_0dte > current_price) ? 0 : 1;
        candidates.push_back({mq.gamma_wall_0dte, 3, side});
    }

    // Trouver le next_wall: le niveau le plus proche avec importance max
    // Formule: score = importance / (1 + distance_ticks/10)
    float best_score = 0;
    int best_idx = -1;

    for (size_t i = 0; i < candidates.size(); i++) {
        float distance = fabs(candidates[i].price - current_price);
        float score = candidates[i].importance / (1.0f + distance / 10.0f);

        if (score > best_score) {
            best_score = score;
            best_idx = i;
        }
    }

    // Assigner le next_wall
    if (best_idx >= 0) {
        mq.next_wall_price = candidates[best_idx].price;
        mq.next_wall_strength = best_score / 5.0f;  // Normaliser sur 1.0
        mq.next_wall_side = candidates[best_idx].side;
    } else {
        mq.next_wall_price = 0;
        mq.next_wall_strength = 0;
        mq.next_wall_side = 0;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6.5: VIX LIVE, ATR DAILY, VWAP SLOPE, GOLDEN RULES, CONFLUENCE
// ═══════════════════════════════════════════════════════════════════════════════

// --- Structure pour données de marché live ---
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

// Global pour données marché
MarketLiveData g_market_live = {20.0f, 15.0f, 350.0f, 0, 0, 1, false, false};

// --- Lecture VIX LIVE ---
float GetVIX_Live(SCStudyInterfaceRef sc, int vix_chart) {
    if (vix_chart <= 0) return 20.0f;  // Défaut

    SCGraphData vix_data;
    sc.GetChartBaseData(vix_chart, vix_data);

    int last_idx = vix_data[0].GetArraySize() - 1;
    if (last_idx < 0) return 20.0f;

    // VIX = Close du chart
    float vix = vix_data[SC_LAST][last_idx];

    // Validation: VIX entre 9 et 80
    if (vix < 9 || vix > 80) return 20.0f;

    return vix;
}

// --- Lecture ATR Daily ---
float GetATR_Daily(SCStudyInterfaceRef sc, int daily_chart, int study_id) {
    if (daily_chart <= 0) return 0;

    // Utiliser la fonction helper
    return ReadStudyValue(sc, daily_chart, study_id, 0);
}

// --- Déterminer régime VIX ---
int GetVIXRegime(float vix) {
    if (vix < 15) return 0;       // CALM - seuils stricts
    else if (vix <= 25) return 1; // NORMAL - seuils standards
    else return 2;                // VOLATILE - seuils permissifs
}

const char* GetVIXRegimeName(int regime) {
    switch (regime) {
        case 0: return "CALM";
        case 1: return "NORMAL";
        case 2: return "VOLATILE";
        default: return "UNKNOWN";
    }
}

// 🔍 DIAGNOSTIC: Écrire les infos de debug VWAP
void WriteDiagnosticVWAP(SCStudyInterfaceRef sc, int chart, int study_id, 
                         const SCFloatArray& vwap_array, float slope, const char* symbol) {
    // Fichier diagnostic à la racine
    std::ofstream diag1("D:\\TRADING_SIERRA_CHART_AUTO\\debug_vwap_slope.txt", std::ios::app);
    std::ofstream diag2("D:\\MIA_IA_system\\debug_vwap_slope.txt", std::ios::app);
    
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    int last_idx = vwap_array.GetArraySize() - 1;
    float vwap_now = (last_idx >= 0) ? vwap_array[last_idx] : 0;
    
    char msg[512];
    snprintf(msg, sizeof(msg),
             "%02d:%02d:%02d|%s|Chart:%d|StudyID:%d|ArraySize:%d|VWAP:%.2f|Slope:%.6f\n",
             hour, minute, second, symbol, chart, study_id, 
             vwap_array.GetArraySize(), vwap_now, slope);
    
    diag1 << msg;
    diag2 << msg;
    
    diag1.close();
    diag2.close();
}

// --- Calcul VWAP Slope (tendance sur N bars) ---
float CalculateVWAPSlope(SCStudyInterfaceRef sc, int chart, int study_id, int lookback_bars, const char* symbol = "UNKNOWN") {
    if (chart <= 0 || lookback_bars < 2) return 0;

    SCFloatArray vwap_array;
    sc.GetStudyArrayFromChartUsingID(chart, study_id, 0, vwap_array);

    int last_idx = vwap_array.GetArraySize() - 1;
    
    // 🔍 DIAGNOSTIC: Si array vide, logger
    if (last_idx < 0) {
        WriteDiagnosticVWAP(sc, chart, study_id, vwap_array, 0, symbol);
        return 0;
    }
    
    if (last_idx < lookback_bars) {
        WriteDiagnosticVWAP(sc, chart, study_id, vwap_array, 0, symbol);
        return 0;
    }

    // Calcul pente = (VWAP actuel - VWAP N bars) / N
    float vwap_now = vwap_array[last_idx];
    float vwap_past = vwap_array[last_idx - lookback_bars];

    if (vwap_past == 0) {
        WriteDiagnosticVWAP(sc, chart, study_id, vwap_array, 0, symbol);
        return 0;
    }

    // Pente normalisée (en % par bar)
    float slope = (vwap_now - vwap_past) / vwap_past * 100.0f / lookback_bars;

    // 🔍 DIAGNOSTIC: Logger toutes les 10 secondes
    static int diag_counter = 0;
    if (++diag_counter % 10 == 0) {
        WriteDiagnosticVWAP(sc, chart, study_id, vwap_array, slope, symbol);
    }

    return slope;
}

// ═══════════════════════════════════════════════════════════════════════════════
// GOLDEN RULES BATAILLE NAVALE
// ═══════════════════════════════════════════════════════════════════════════════

// --- Golden Rule #1: Ratio 1.5x VETO ---
// Si l'adversaire a 1.5x+ de force → BLOQUER le trade
// AMÉLIORÉ: Utilise TOUTES les données BN maintenant
bool CheckGoldenRule1_Veto(const BN_Data& bn, int direction) {
    // Calculer forces COMPLÈTES (inclut toutes les données)
    // ⚠️ COLOR_UP/DOWN = flux local, pas obstacle structurel → poids très faible (0.1x)
    // 🔧 30/01/2026: FIX - edge_buy/sell sont des PRIX, utiliser num_edge_rect_buy/sell
    float edge_weight = 50.0f;
    float buyer_strength = (bn.num_edge_rect_buy * edge_weight) + (bn.color_up * 0.1f) + bn.absorb_bid;
    float seller_strength = (bn.num_edge_rect_sell * edge_weight) + (bn.color_down * 0.1f) + bn.absorb_ask;

    // Momentum (rotation) - poids 0.5
    buyer_strength += bn.rotation_up * 0.5f;
    seller_strength += bn.rotation_down * 0.5f;

    // Reversals (long bars) - poids x2 (signal fort)
    buyer_strength += bn.long_down_up * 2.0f;
    seller_strength += bn.long_up_down * 2.0f;

    // Doubles/Triples selon symbole
    buyer_strength += bn.double_bid + bn.triple_bid + bn.volume_up;
    seller_strength += bn.double_ask + bn.triple_ask + bn.volume_down;

    // Gros ordres (institutionnels) - poids progressif
    buyer_strength += bn.bid_100 * 0.3f + bn.bid_150 * 0.5f + bn.bid_400 * 1.0f + bn.bid_1000 * 1.5f;
    seller_strength += bn.ask_100 * 0.3f + bn.ask_150 * 0.5f + bn.ask_400 * 1.0f + bn.ask_1000 * 1.5f;

    // Signaux barres
    // ⚠️ bar_color_up/down = flux local → poids réduit (0.1x au lieu de 0.3x)
    buyer_strength += bn.bar_color_up * 0.1f + bn.bar_edge_buy * 0.5f;
    seller_strength += bn.bar_color_down * 0.1f + bn.bar_edge_sell * 0.5f;
    
    // 🆕 FPBS Delta (direction instantanée)
    if (bn.fpbs_delta > 0) {
        buyer_strength += fmin(bn.fpbs_delta / 1000.0f, 2.0f) * 0.5f;
    } else if (bn.fpbs_delta < 0) {
        seller_strength += fmin(-bn.fpbs_delta / 1000.0f, 2.0f) * 0.5f;
    }

    if (direction == 1) {  // LONG
        // VETO si sellers > buyers * 1.5
        if (buyer_strength > 0 && seller_strength > buyer_strength * 1.5f) {
            return true;  // VETO!
        }
    } else {  // SHORT
        // VETO si buyers > sellers * 1.5
        if (seller_strength > 0 && buyer_strength > seller_strength * 1.5f) {
            return true;  // VETO!
        }
    }

    return false;  // Pas de veto
}

// --- Golden Rule #2: Absence = Confirmation ---
// Si pas de signal adverse → bonus de confirmation
// AMÉLIORÉ: Vérifie aussi les reversals, momentum, et gros ordres
float CheckGoldenRule2_Bonus(const BN_Data& bn, int direction) {
    float bonus = 0;

    if (direction == 1) {  // LONG
        // Pas de rectangles rouges (edge_sell) = voie libre!
        // 🔧 30/01/2026: FIX - utiliser num_edge_rect_sell
        if (bn.num_edge_rect_sell == 0) {
            bonus += 0.03f;
        }
        // Pas d'absorption ask = pas de résistance
        if (bn.absorb_ask == 0) {
            bonus += 0.02f;
        }
        // Pas de reversal baissier = tendance intacte
        if (bn.long_up_down == 0) {
            bonus += 0.02f;
        }
        // Pas de gros vendeurs = pas de pression institutionnelle
        if (bn.ask_400 == 0 && bn.ask_1000 == 0) {
            bonus += 0.02f;
        }
        // Momentum favorable
        if (bn.momentum_score > 0) {
            bonus += 0.01f;
        }
    } else {  // SHORT
        // Pas de rectangles verts (edge_buy) = voie libre!
        // 🔧 30/01/2026: FIX - utiliser num_edge_rect_buy
        if (bn.num_edge_rect_buy == 0) {
            bonus += 0.03f;
        }
        // Pas d'absorption bid = pas de support
        if (bn.absorb_bid == 0) {
            bonus += 0.02f;
        }
        // Pas de reversal haussier = tendance intacte
        if (bn.long_down_up == 0) {
            bonus += 0.02f;
        }
        // Pas de gros acheteurs = pas de support institutionnel
        if (bn.bid_400 == 0 && bn.bid_1000 == 0) {
            bonus += 0.02f;
        }
        // Momentum favorable
        if (bn.momentum_score < 0) {
            bonus += 0.01f;
        }
    }

    return bonus;
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONFLUENCE DETECTOR ROBUSTE v3 - PARITÉ PYTHON MIA
// ═══════════════════════════════════════════════════════════════════════════════
//
// LOGIQUE: Détecte les zones où plusieurs niveaux MenthorQ sont PROCHES ENTRE EUX
//          Identique au détecteur Python de MIA
//
// PONDÉRATION DES NIVEAUX (strength × importance):
//   - next_wall: 5 points (PRIORITÉ MAX) + bonus spécial +10%
//   - HVL/HVL_0DTE: 4 points (très important)
//   - GEX 1-3: 3 points (important)
//   - Put/Call Support/Resistance: 3 points
//   - VWAP: 3 points
//   - VAH/VAL (Value Area): 2 points
//   - VWAP Bandes (±1σ, ±2σ): 2 points
//   - GEX 4-10: 1 point
//   - Blind Spots 0-8: 1 point
//
// CONFLUENCE VALIDE SI:
//   - Au moins 2 niveaux dans une zone de 15 ticks
//   - Score pondéré >= 5 points
//
// BONUS MAX: 25% (identique Python)
// ═══════════════════════════════════════════════════════════════════════════════

struct LevelInfo {
    float price;
    int weight;        // Poids du niveau (1-5)
    const char* type;  // Type pour debug
    bool is_next_wall; // Flag next_wall pour bonus spécial
};

struct ConfluenceCluster {
    int start_idx;
    int end_idx;
    int weighted_score;
    float center;
    float zone_width_ticks;
    bool has_next_wall;
};

struct ConfluenceResult {
    int num_levels;           // Nombre de niveaux dans la zone
    float zone_center;        // Centre de la zone de confluence
    float zone_width_ticks;   // Largeur de la zone en ticks
    float strength;           // Force de la confluence (0-1)
    bool has_confluence;      // Confluence détectée?
    int weighted_score;       // Score pondéré total
    float distance_to_price;  // Distance du centre au prix actuel
    char levels_desc[256];    // Description des niveaux (debug)
    // AJOUTS PARITÉ PYTHON
    bool has_next_wall;       // next_wall présent dans la confluence?
    int num_clusters;         // Nombre total de clusters détectés
    float best_cluster_score; // Score du meilleur cluster
};

// Constantes pour la détection
const float CONFLUENCE_TOLERANCE_TICKS = 15.0f;  // Distance max entre niveaux
const int MIN_CONFLUENCE_SCORE = 5;              // Score minimum pour confluence valide
const float MAX_CONFLUENCE_BONUS = 0.25f;        // Bonus max 25% (parité Python)
const float NEXT_WALL_BONUS = 0.10f;             // Bonus spécial next_wall +10%

ConfluenceResult DetectConfluence(
    const MenthorQ_Data& mq,
    float current_price,
    float tick_size,
    float cluster_max_ticks  // Distance max ENTRE niveaux pour former un cluster
) {
    ConfluenceResult result = {0, 0, 0, 0, false, 0, 0, "", false, 0, 0};

    // === 1. COLLECTER TOUS LES NIVEAUX AVEC POIDS (PARITÉ PYTHON) ===
    std::vector<LevelInfo> all_levels;

    // next_wall (poids 5 - PRIORITÉ MAX)
    if (mq.next_wall_price > 0) {
        all_levels.push_back({mq.next_wall_price, 5, "NEXT_WALL", true});
    }

    // HVL (poids 4 - très important)
    if (mq.hvl > 0) {
        all_levels.push_back({mq.hvl, 4, "HVL", false});
    }
    if (mq.hvl_0dte > 0 && fabs(mq.hvl_0dte - mq.hvl) > tick_size) {
        all_levels.push_back({mq.hvl_0dte, 4, "HVL_0DTE", false});
    }

    // GEX 1-3 (poids 3)
    for (int i = 0; i < 3; i++) {
        if (mq.gex[i] > 0) {
            all_levels.push_back({mq.gex[i], 3, "GEX_TOP", false});
        }
    }

    // Put/Call (poids 3)
    if (mq.put_support > 0) {
        all_levels.push_back({mq.put_support, 3, "PUT", false});
    }
    if (mq.call_resistance > 0) {
        all_levels.push_back({mq.call_resistance, 3, "CALL", false});
    }
    if (mq.put_support_0dte > 0 && fabs(mq.put_support_0dte - mq.put_support) > tick_size) {
        all_levels.push_back({mq.put_support_0dte, 3, "PUT_0DTE", false});
    }
    if (mq.call_resistance_0dte > 0 && fabs(mq.call_resistance_0dte - mq.call_resistance) > tick_size) {
        all_levels.push_back({mq.call_resistance_0dte, 3, "CALL_0DTE", false});
    }

    // VWAP (poids 3)
    if (mq.vwap > 0) {
        all_levels.push_back({mq.vwap, 3, "VWAP", false});
    }

    // Value Area VAH/VAL (poids 2) - NOUVEAU PARITÉ PYTHON
    if (mq.vah > 0) {
        all_levels.push_back({mq.vah, 2, "VAH", false});
    }
    if (mq.val > 0) {
        all_levels.push_back({mq.val, 2, "VAL", false});
    }

    // VWAP Bandes ±1σ, ±2σ (poids 2) - NOUVEAU PARITÉ PYTHON
    if (mq.vwap_up1 > 0) {
        all_levels.push_back({mq.vwap_up1, 2, "VWAP+1s", false});
    }
    if (mq.vwap_dn1 > 0) {
        all_levels.push_back({mq.vwap_dn1, 2, "VWAP-1s", false});
    }
    if (mq.vwap_up2 > 0) {
        all_levels.push_back({mq.vwap_up2, 2, "VWAP+2s", false});
    }
    if (mq.vwap_dn2 > 0) {
        all_levels.push_back({mq.vwap_dn2, 2, "VWAP-2s", false});
    }

    // GEX 4-10 (poids 1)
    for (int i = 3; i < 10; i++) {
        if (mq.gex[i] > 0) {
            all_levels.push_back({mq.gex[i], 1, "GEX", false});
        }
    }

    // Blind Spots 0-8 COMPLET (poids 1) - PARITÉ PYTHON
    for (int i = 0; i < 9; i++) {
        if (mq.blind_spots[i] > 0) {
            all_levels.push_back({mq.blind_spots[i], 1, "BLIND", false});
        }
    }

    // Gamma Walls (poids 2)
    if (mq.gamma_wall > 0) {
        all_levels.push_back({mq.gamma_wall, 2, "GAMMA", false});
    }
    if (mq.gamma_wall_0dte > 0 && fabs(mq.gamma_wall_0dte - mq.gamma_wall) > tick_size) {
        all_levels.push_back({mq.gamma_wall_0dte, 2, "GAMMA_0DTE", false});
    }

    if (all_levels.size() < 2) {
        return result;  // Pas assez de niveaux
    }

    // === 2. TRIER PAR PRIX ===
    std::sort(all_levels.begin(), all_levels.end(),
              [](const LevelInfo& a, const LevelInfo& b) { return a.price < b.price; });

    // === 3. DÉTECTER TOUS LES CLUSTERS (MULTI-CONFLUENCES) ===
    float cluster_distance = (cluster_max_ticks > 0 ? cluster_max_ticks : CONFLUENCE_TOLERANCE_TICKS) * tick_size;
    std::vector<ConfluenceCluster> clusters;

    for (size_t i = 0; i < all_levels.size(); i++) {
        int cluster_weight = all_levels[i].weight;
        bool cluster_has_next_wall = all_levels[i].is_next_wall;
        size_t j = i;

        // Étendre le cluster tant que les niveaux sont proches
        while (j + 1 < all_levels.size() &&
               (all_levels[j + 1].price - all_levels[i].price) <= cluster_distance) {
            j++;
            cluster_weight += all_levels[j].weight;
            if (all_levels[j].is_next_wall) cluster_has_next_wall = true;
        }

        // Sauvegarder le cluster s'il est valide (au moins 2 niveaux et score min)
        if (j > i && cluster_weight >= MIN_CONFLUENCE_SCORE) {
            ConfluenceCluster cluster;
            cluster.start_idx = i;
            cluster.end_idx = j;
            cluster.weighted_score = cluster_weight;
            cluster.has_next_wall = cluster_has_next_wall;

            // Calculer centre pondéré
            float weighted_sum = 0;
            float total_weight = 0;
            for (size_t k = i; k <= j; k++) {
                weighted_sum += all_levels[k].price * all_levels[k].weight;
                total_weight += all_levels[k].weight;
            }
            cluster.center = weighted_sum / total_weight;
            cluster.zone_width_ticks = (all_levels[j].price - all_levels[i].price) / tick_size;

            clusters.push_back(cluster);
        }
    }

    result.num_clusters = clusters.size();

    if (clusters.empty()) {
        return result;  // Aucun cluster valide
    }

    // === 4. TROUVER LE MEILLEUR CLUSTER (priorité: next_wall, puis score) ===
    int best_idx = 0;
    for (size_t i = 1; i < clusters.size(); i++) {
        // Priorité 1: cluster avec next_wall
        if (clusters[i].has_next_wall && !clusters[best_idx].has_next_wall) {
            best_idx = i;
        }
        // Priorité 2: meilleur score (si même statut next_wall)
        else if (clusters[i].has_next_wall == clusters[best_idx].has_next_wall &&
                 clusters[i].weighted_score > clusters[best_idx].weighted_score) {
            best_idx = i;
        }
    }

    ConfluenceCluster& best = clusters[best_idx];

    // === 5. REMPLIR LE RÉSULTAT ===
    result.has_confluence = true;
    result.num_levels = best.end_idx - best.start_idx + 1;
    result.weighted_score = best.weighted_score;
    result.zone_center = best.center;
    result.zone_width_ticks = best.zone_width_ticks;
    result.has_next_wall = best.has_next_wall;
    result.best_cluster_score = best.weighted_score;
    result.distance_to_price = fabs(current_price - result.zone_center) / tick_size;

    // Description des niveaux
    char desc[256] = "";
    int desc_len = 0;
    for (int i = best.start_idx; i <= best.end_idx; i++) {
        if (desc_len < 200) {
            desc_len += snprintf(desc + desc_len, sizeof(desc) - desc_len,
                                 "%s%.0f ", all_levels[i].type, all_levels[i].price);
        }
    }
    strncpy(result.levels_desc, desc, sizeof(result.levels_desc) - 1);

    // Force: basée sur le score pondéré (max théorique ~25+)
    // Score 5 = 0.2, Score 10 = 0.4, Score 15 = 0.6, Score 20+ = 0.8+
    result.strength = fmin(1.0f, best.weighted_score / 25.0f);

    return result;
}

// === HELPER: Vérifier si le prix est dans une zone de confluence ===
bool IsPriceInConfluenceZone(
    const ConfluenceResult& conf,
    float current_price,
    float tick_size,
    float tolerance_ticks  // Tolérance autour de la zone
) {
    if (!conf.has_confluence) return false;

    float tolerance = tolerance_ticks * tick_size;
    float zone_half_width = (conf.zone_width_ticks / 2.0f) * tick_size;

    float zone_low = conf.zone_center - zone_half_width - tolerance;
    float zone_high = conf.zone_center + zone_half_width + tolerance;

    return (current_price >= zone_low && current_price <= zone_high);
}

// === HELPER: Bonus de confidence basé sur confluence (PARITÉ PYTHON) ===
float GetConfluenceBonus(const ConfluenceResult& conf, float current_price, float tick_size) {
    if (!conf.has_confluence) return 0;

    float distance_ticks = fabs(current_price - conf.zone_center) / tick_size;

    // Plus proche = plus de bonus (0 tick = max, 20+ ticks = rien)
    float proximity_factor = fmax(0, 1.0f - distance_ticks / 20.0f);

    // Base bonus: strength * proximity * 0.15 (max 15% de base)
    float base_bonus = conf.strength * proximity_factor * 0.15f;

    // Bonus spécial next_wall: +10% si présent dans la confluence
    float next_wall_bonus = conf.has_next_wall ? NEXT_WALL_BONUS : 0;

    // Total plafonné à 25% (parité Python)
    return fmin(MAX_CONFLUENCE_BONUS, base_bonus + next_wall_bonus);
}

// ═══════════════════════════════════════════════════════════════════════════════
// BONUS EXTENSION LINES BN - Renforce la confluence avec les zones des gros
// ═══════════════════════════════════════════════════════════════════════════════
// Les Extension Lines (COLOR UP/DOWN, EDGE ZONES, LONG UP/DOWN BAR) représentent
// les vraies zones de défense des institutionnels. Si elles sont proches d'une
// confluence MenthorQ, c'est un signal TRÈS fort.
//
// Bonus: +5% par Extension Line proche (max +15%)

float GetBNExtensionBonus(
    const BN_Data& bn,
    float current_price,
    float tick_size,
    int direction  // 1=LONG, -1=SHORT
) {
    float bonus = 0;
    float tolerance = 15.0f * tick_size;  // 15 ticks de tolérance

    if (direction == 1) {  // LONG: bonus si supports BN proches
        int nearby_supports = 0;
        for (int i = 0; i < bn.num_ext_support && nearby_supports < 3; i++) {
            float distance = current_price - bn.ext_lines_support[i];
            if (distance > 0 && distance <= tolerance) {
                nearby_supports++;
            }
        }
        bonus = nearby_supports * 0.05f;  // +5% par support proche
    }
    else {  // SHORT: bonus si résistances BN proches
        int nearby_resists = 0;
        for (int i = 0; i < bn.num_ext_resist && nearby_resists < 3; i++) {
            float distance = bn.ext_lines_resist[i] - current_price;
            if (distance > 0 && distance <= tolerance) {
                nearby_resists++;
            }
        }
        bonus = nearby_resists * 0.05f;  // +5% par résistance proche
    }

    return fmin(0.15f, bonus);  // Max +15%
}

// ═══════════════════════════════════════════════════════════════════════════════
// COLLECTE DONNÉES MARCHÉ COMPLÈTES
// ═══════════════════════════════════════════════════════════════════════════════

void CollectMarketLiveData(
    SCStudyInterfaceRef sc,
    int vix_chart,
    int es_daily_chart,
    int nq_daily_chart,
    int es_barres_chart,
    int nq_barres_chart
) {
    // VIX
    g_market_live.vix = GetVIX_Live(sc, vix_chart);
    g_market_live.vix_regime = GetVIXRegime(g_market_live.vix);
    g_market_live.vix_valid = (g_market_live.vix >= 9 && g_market_live.vix <= 80);

    // ATR Daily (study_id = 1)
    g_market_live.atr_es = GetATR_Daily(sc, es_daily_chart, 1);
    g_market_live.atr_nq = GetATR_Daily(sc, nq_daily_chart, 1);
    g_market_live.atr_valid = (g_market_live.atr_es > 0 || g_market_live.atr_nq > 0);

    // VWAP Slope (VWAP study_id = 1 sur barres charts, lookback 20 bars)
    g_market_live.vwap_slope_es = CalculateVWAPSlope(sc, es_barres_chart, 1, 20, "ES");
    g_market_live.vwap_slope_nq = CalculateVWAPSlope(sc, nq_barres_chart, 1, 20, "NQ");
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7: LAYER 1 - MENTHORQ LEVELS
// ═══════════════════════════════════════════════════════════════════════════════

struct Layer1Result {
    bool passed;
    float confidence;
    int direction;           // 1=LONG, -1=SHORT
    char level_name[32];
    float level_price;
    float distance_ticks;
    int importance_score;    // 🆕 Score du niveau (1=mineur, 2=important, 3=majeur)
};

Layer1Result ValidateLayer1(
    SCStudyInterfaceRef sc,
    const MenthorQ_Data& mq,
    float current_price,
    const SymbolConfig& config,
    float momentum_score = 0.0f,  // 🆕 Confirmation momentum (optionnel)
    const BN_Data* bn = nullptr,  // 🆕 Pour vérifier confluence score 1
    bool is_es = true             // 🆕 ES ou NQ (pour Edge Zone 600% vs 0DIAG)
) {
    Layer1Result result = {false, 0, 0, "", 0, 0, 0};  // +importance_score

    float tick_size = config.tick_size;
    float best_distance = 999999.0f;

    // Chercher niveau le plus proche
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 SYSTÈME DE SCORE D'IMPORTANCE DES NIVEAUX
    // ═══════════════════════════════════════════════════════════════════════════
    // Score 3 (MAJEUR): HVL, GAMMA, GEX 1-3 → Trade validé seul
    // Score 2 (IMPORTANT): PUT/CALL, 1D MIN/MAX, VAH/VAL, GEX 4-5, SD±2 → OK
    // 🔧 TOUS LES NIVEAUX OPTIONS ACCEPTÉS (19/01/2026)
    // Score 3: HVL, GAMMA, GEX 1-3 (bonus +10%)
    // Score 2: PUT/CALL, 1D, VAH/VAL, GEX 4-5 (bonus +5%)
    // Score 1: VWAP, SD±1, BLIND, GEX 6-10 (base)
    // ═══════════════════════════════════════════════════════════════════════════
    const int MIN_LEVEL_SCORE = 1;  // 🔧 TOUS les niveaux acceptés

    struct LevelCandidate {
        const char* name;
        float price;
        int support_direction;  // 1=support (LONG), -1=resistance (SHORT)
        int importance;         // 🆕 Score 1-3
    };

    std::vector<LevelCandidate> candidates;

    // === SCORE 3 (MAJEUR) ===
    // HVL (support/résistance dynamique)
    if (mq.hvl_0dte > 0) {
        int dir = (current_price > mq.hvl_0dte) ? 1 : -1;
        candidates.push_back({"HVL_0DTE", mq.hvl_0dte, dir, 3});
    }
    if (mq.hvl > 0) {
        int dir = (current_price > mq.hvl) ? 1 : -1;
        candidates.push_back({"HVL", mq.hvl, dir, 3});
    }

    // Gamma Walls (MAJEUR)
    if (mq.gamma_wall > 0) {
        int dir = (current_price > mq.gamma_wall) ? 1 : -1;
        candidates.push_back({"GAMMA_WALL", mq.gamma_wall, dir, 3});
    }
    if (mq.gamma_wall_0dte > 0 && fabs(mq.gamma_wall_0dte - mq.gamma_wall) > tick_size) {
        int dir = (current_price > mq.gamma_wall_0dte) ? 1 : -1;
        candidates.push_back({"GAMMA_0DTE", mq.gamma_wall_0dte, dir, 3});
    }

    // GEX (supports/résistances) - Score décroissant
    for (int i = 0; i < 10; i++) {
        if (mq.gex[i] > 0) {
            int dir = (current_price > mq.gex[i]) ? 1 : -1;
            char name[16];
            snprintf(name, sizeof(name), "GEX_%d", i + 1);
            int score = (i < 3) ? 3 : ((i < 5) ? 2 : 1);  // GEX 1-3=3, GEX 4-5=2, GEX 6-10=1
            candidates.push_back({name, mq.gex[i], dir, score});
        }
    }

    // === SCORE 2 (IMPORTANT) ===
    // 🔧 27/01/2026: Call Resistance = SHORT si en-dessous, LONG si breakout au-dessus!
    if (mq.call_resistance > 0) {
        if (current_price < mq.call_resistance) {
            candidates.push_back({"CALL_RESIST", mq.call_resistance, -1, 2});  // SHORT vers résistance
        } else {
            // Prix AU-DESSUS = breakout! Call Resistance devient SUPPORT pour continuation LONG
            candidates.push_back({"CALL_BREAKOUT", mq.call_resistance, 1, 2});
        }
    }
    // 🔧 27/01/2026: Put Support = LONG si au-dessus, SHORT si breakdown en-dessous!
    if (mq.put_support > 0) {
        if (current_price > mq.put_support) {
            candidates.push_back({"PUT_SUPPORT", mq.put_support, 1, 2});  // LONG vers support
        } else {
            // Prix EN-DESSOUS = breakdown! Put Support devient RÉSISTANCE pour continuation SHORT
            candidates.push_back({"PUT_BREAKDOWN", mq.put_support, -1, 2});
        }
    }

    // 1D MIN/MAX (Expected Move) - IMPORTANT
    if (mq.day_min > 0 && current_price > mq.day_min) {
        candidates.push_back({"1D_MIN", mq.day_min, 1, 2});
    }
    if (mq.day_max > 0 && current_price < mq.day_max) {
        candidates.push_back({"1D_MAX", mq.day_max, -1, 2});
    }

    // Value Area (VAH/VAL) - IMPORTANT
    if (mq.vah > 0 && current_price < mq.vah) {
        candidates.push_back({"VAH", mq.vah, -1, 2});
    }
    if (mq.val > 0 && current_price > mq.val) {
        candidates.push_back({"VAL", mq.val, 1, 2});
    }

    // VWAP SD±2 - IMPORTANT (zones extrêmes)
    if (mq.vwap_dn2 > 0 && current_price > mq.vwap_dn2) {
        candidates.push_back({"VWAP_SD-2", mq.vwap_dn2, 1, 2});
    }
    if (mq.vwap_up2 > 0 && current_price < mq.vwap_up2) {
        candidates.push_back({"VWAP_SD+2", mq.vwap_up2, -1, 2});
    }

    // === SCORE 1 (MINEUR - NE PEUT PAS DÉCLENCHER SEUL) ===
    // VWAP Central
    if (mq.vwap > 0) {
        int dir = (current_price > mq.vwap) ? 1 : -1;
        candidates.push_back({"VWAP", mq.vwap, dir, 1});
    }

    // VWAP SD±1 - MINEUR
    if (mq.vwap_dn1 > 0 && current_price > mq.vwap_dn1) {
        candidates.push_back({"VWAP_SD-1", mq.vwap_dn1, 1, 1});
    }
    if (mq.vwap_up1 > 0 && current_price < mq.vwap_up1) {
        candidates.push_back({"VWAP_SD+1", mq.vwap_up1, -1, 1});
    }

    // Blind Spots - MINEUR
    for (int i = 0; i < 9; i++) {
        if (mq.blind_spots[i] > 0) {
            int dir = (current_price > mq.blind_spots[i]) ? 1 : -1;
            char name[16];
            snprintf(name, sizeof(name), "BLIND_%d", i);
            candidates.push_back({name, mq.blind_spots[i], dir, 1});
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 LOGIQUE CONFLUENCE POUR NIVEAUX SCORE 1 (20/01/2026)
    // Score 2-3: Trade direct avec BN basique
    // Score 1: EXIGE soit niveau 2/3 proche (<10t), soit 2+ confluences
    // ═══════════════════════════════════════════════════════════════════════════

    // D'abord, trouver s'il y a un niveau score 2/3 proche (pour valider score 1)
    // 🔧 27/01/2026: Augmenté 10 → 25 ticks pour capter breakouts
    bool has_strong_level_nearby = false;
    for (const auto& cand : candidates) {
        if (cand.importance >= 2) {
            float dist = fabs(current_price - cand.price) / tick_size;
            if (dist <= 25.0f) {
                has_strong_level_nearby = true;
                break;
            }
        }
    }

    // Compter les confluences BN (pour score 1 sans niveau fort proche)
    int confluence_count = 0;
    if (bn != nullptr) {
        // Rectangle vert/rouge
        if (bn->long_down_up > 0 || bn->long_up_down > 0) confluence_count++;
        // Boule Edge Zone (600% ES, 0DIAG NQ)
        if (bn->edge_buy > 0 || bn->edge_sell > 0) confluence_count++;
        // OrderFlow FORT
        if (fabs(bn->score) > 0.15f) confluence_count++;
        // Absorption présente
        if (bn->absorb_bid > 3 || bn->absorb_ask > 3) confluence_count++;
        // Double/Triple signal
        if (bn->double_bid > 0 || bn->double_ask > 0 ||
            bn->triple_bid > 0 || bn->triple_ask > 0) confluence_count++;
    }

    // Compter cluster de niveaux (2+ niveaux dans 5 ticks)
    int levels_in_cluster = 0;
    for (const auto& cand : candidates) {
        float dist = fabs(current_price - cand.price) / tick_size;
        if (dist <= 5.0f) levels_in_cluster++;
    }
    if (levels_in_cluster >= 2) confluence_count++;

    int best_importance = 0;
    for (const auto& cand : candidates) {
        float distance = fabs(current_price - cand.price);
        float distance_ticks = distance / tick_size;

        // 🔧 27/01/2026: Max 20 ticks de distance (était 6 = trop strict!)
        // NQ: 20 ticks = 5 pts, ES: 20 ticks = 5 pts
        // Permet de capter les breakouts (prix juste au-dessus niveau)
        if (distance_ticks > 20) continue;

        // 🆕 RÈGLE CONFLUENCE POUR SCORE 1
        if (cand.importance == 1) {
            // Score 1 accepté UNIQUEMENT si:
            // - Niveau 2/3 proche (<10 ticks), OU
            // - Au moins 2 confluences
            if (!has_strong_level_nearby && confluence_count < 2) {
                continue;  // REJET: pas assez de confluence
            }
        }

        // Priorité: importance d'abord, puis distance
        if (cand.importance > best_importance ||
            (cand.importance == best_importance && distance < best_distance)) {
            best_distance = distance;
            best_importance = cand.importance;
            result.direction = cand.support_direction;
            strncpy(result.level_name, cand.name, sizeof(result.level_name) - 1);
            result.level_price = cand.price;
            result.distance_ticks = distance_ticks;
            result.importance_score = cand.importance;  // 🆕 Score pour HQ detection

            // Confidence basée sur distance + importance + confluence
            float importance_bonus = (cand.importance == 3) ? 0.10f :
                                     (cand.importance == 2) ? 0.05f : 0.0f;

            // Bonus confluence pour score 1
            float confluence_bonus = (cand.importance == 1 && confluence_count >= 2) ? 0.05f : 0.0f;

            if (distance_ticks <= 4) {
                result.confidence = 0.45f + importance_bonus + confluence_bonus;
            } else {
                result.confidence = 0.30f * (1.0f - (distance_ticks - 4) / 4.0f) + importance_bonus + confluence_bonus;
            }

            // EQUILIBRE: Valide si confidence >= 0.25
            result.passed = (result.confidence >= 0.25f);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 PRO: CONFIRMATION DE REJET/REBOND (Règle d'Or)
    // On ne trade PAS pendant le contact, mais APRÈS confirmation!
    // Fenêtre optimale: 2-5 ticks + momentum aligné
    // ═══════════════════════════════════════════════════════════════════════
    if (result.passed && result.level_price > 0) {
        float tick_size = config.tick_size;
        float distance_ticks = result.distance_ticks;

        bool rejection_confirmed = false;
        float confidence_modifier = 0.0f;

        // === RÈGLE 1: Fenêtre de distance optimale ===
        // < 1 tick: contact en cours → ATTENDRE
        // 1-2 ticks: début de réaction → OK
        // 2-5 ticks: zone optimale → OK + bonus
        // > 5 ticks: peut être tardif → OK mais pas de bonus

        if (distance_ticks < 1.0f) {
            // Contact en cours - on attend confirmation
            rejection_confirmed = false;
        } else if (distance_ticks >= 1.0f && distance_ticks <= 5.0f) {
            // Zone de confirmation optimale
            rejection_confirmed = true;
            if (distance_ticks >= 2.0f && distance_ticks <= 4.0f) {
                confidence_modifier += 0.05f;  // Sweet spot!
            }
        } else {
            // 5-8 ticks: Accepté mais peut être tardif
            rejection_confirmed = true;
            confidence_modifier -= 0.03f;  // Léger malus
        }

        // === RÈGLE 2: Momentum doit confirmer la direction ===
        // SHORT: momentum_score négatif (vendeurs actifs)
        // LONG: momentum_score positif (acheteurs actifs)
        if (rejection_confirmed && momentum_score != 0.0f) {
            if (result.direction == -1) {
                // SHORT: on veut momentum NÉGATIF (bearish)
                if (momentum_score < -0.1f) {
                    confidence_modifier += 0.08f;  // Forte confirmation!
                } else if (momentum_score < 0) {
                    confidence_modifier += 0.03f;  // Confirmation légère
                } else if (momentum_score > 0.15f) {
                    // Momentum BULLISH mais on veut SHORT = DANGER!
                    rejection_confirmed = false;
                    confidence_modifier = 0.0f;
                }
            } else if (result.direction == 1) {
                // LONG: on veut momentum POSITIF (bullish)
                if (momentum_score > 0.1f) {
                    confidence_modifier += 0.08f;  // Forte confirmation!
                } else if (momentum_score > 0) {
                    confidence_modifier += 0.03f;  // Confirmation légère
                } else if (momentum_score < -0.15f) {
                    // Momentum BEARISH mais on veut LONG = DANGER!
                    rejection_confirmed = false;
                    confidence_modifier = 0.0f;
                }
            }
        }

        // Appliquer le résultat
        if (rejection_confirmed) {
            result.confidence += confidence_modifier;
        } else {
            result.passed = false;
            result.confidence = 0;
            // Ajouter note pour debug
            char note[64];
            if (distance_ticks < 1.0f) {
                snprintf(note, sizeof(note), "%s_CONTACT", result.level_name);
            } else {
                snprintf(note, sizeof(note), "%s_MOMENTUM_AGAINST", result.level_name);
            }
            strncpy(result.level_name, note, sizeof(result.level_name) - 1);
        }
    }

    // 🔧 26/01/2026: RECTANGLES COMME NIVEAU PRINCIPAL (pas seulement bonus!)
    // Si aucun niveau MenthorQ trouvé MAIS rectangle présent → ACCEPTER
    if (!result.passed && bn != nullptr) {
        // Rectangle vert (LONG) ou rouge (SHORT)
        if (bn->long_down_up > 0) {
            // Rectangle VERT = Support = LONG
            result.passed = true;
            result.direction = 1;  // LONG
            result.confidence = 0.35f;  // Base pour rectangle seul
            result.level_price = current_price;  // On est au contact
            result.distance_ticks = 0;
            result.importance_score = 2;  // Importance moyenne
            strncpy(result.level_name, "RECT_VERT", sizeof(result.level_name) - 1);
            
            // BONUS si Edge Buy présent
            if (bn->edge_buy > 0) {
                result.confidence += 0.10f;
            }
        } else if (bn->long_up_down > 0) {
            // Rectangle ROUGE = Résistance = SHORT
            result.passed = true;
            result.direction = -1;  // SHORT
            result.confidence = 0.35f;  // Base pour rectangle seul
            result.level_price = current_price;  // On est au contact
            result.distance_ticks = 0;
            result.importance_score = 2;  // Importance moyenne
            strncpy(result.level_name, "RECT_ROUGE", sizeof(result.level_name) - 1);
            
            // BONUS si Edge Sell présent
            if (bn->edge_sell > 0) {
                result.confidence += 0.10f;
            }
        }
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7B: LAYER 1 ALTERNATIF - RECTANGLES + CONFLUENCE (SCALP)
// ═══════════════════════════════════════════════════════════════════════════════
// Stratégie: Trade les rectangles verts/rouges (Long Down Up / Long Up Down Bar)
// quand il y a confluence avec les points verts/rouges (Color Up/Down)
// ═══════════════════════════════════════════════════════════════════════════════

struct RectangleSignal {
    bool has_signal;
    int direction;          // 1=LONG, -1=SHORT
    float confidence;
    float rectangle_price;  // Prix du rectangle
    float confluence_score; // Score de confluence
    char reason[256];
};

RectangleSignal DetectRectangleConfluence(
    SCStudyInterfaceRef sc,
    const BN_Data& bn,
    const MenthorQ_Data& mq,  // 🆕 AJOUT: Pour exiger niveau score >= 2
    float current_price,
    const SymbolConfig& config,
    bool is_nq
) {
    RectangleSignal result = {false, 0, 0, 0, 0, ""};

    float tick_size = config.tick_size;
    float max_distance_ticks = 10.0f;  // Max 10 ticks de l'extension line

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 TOUS LES NIVEAUX OPTIONS ACCEPTÉS (19/01/2026)
    // Layer 1B Rectangles - Niveau proche requis mais tous scores OK
    // Bonus confidence si score élevé (3 = +8%, 2 = +5%)
    // ═══════════════════════════════════════════════════════════════════════════
    const int MIN_LEVEL_SCORE_FOR_RECT = 1;  // 🔧 TOUS acceptés
    const float MAX_LEVEL_DISTANCE_TICKS = 25.0f;  // 🔧 27/01/2026: Chercher dans 25 ticks (était 15)

    struct LevelCheck {
        float price;
        int score;
        const char* name;
    };
    std::vector<LevelCheck> option_levels;

    // Score 3 (MAJEUR)
    if (mq.hvl > 0) option_levels.push_back({mq.hvl, 3, "HVL"});
    if (mq.hvl_0dte > 0) option_levels.push_back({mq.hvl_0dte, 3, "HVL_0DTE"});
    if (mq.gamma_wall > 0) option_levels.push_back({mq.gamma_wall, 3, "GAMMA"});
    if (mq.gamma_wall_0dte > 0) option_levels.push_back({mq.gamma_wall_0dte, 3, "GAMMA_0DTE"});
    for (int i = 0; i < 3; i++) if (mq.gex[i] > 0) option_levels.push_back({mq.gex[i], 3, "GEX_TOP"});

    // Score 2 (IMPORTANT)
    if (mq.put_support > 0) option_levels.push_back({mq.put_support, 2, "PUT"});
    if (mq.call_resistance > 0) option_levels.push_back({mq.call_resistance, 2, "CALL"});
    if (mq.day_min > 0) option_levels.push_back({mq.day_min, 2, "1D_MIN"});
    if (mq.day_max > 0) option_levels.push_back({mq.day_max, 2, "1D_MAX"});
    if (mq.vah > 0) option_levels.push_back({mq.vah, 2, "VAH"});
    if (mq.val > 0) option_levels.push_back({mq.val, 2, "VAL"});
    for (int i = 3; i < 5; i++) if (mq.gex[i] > 0) option_levels.push_back({mq.gex[i], 2, "GEX_MID"});
    if (mq.vwap_up2 > 0) option_levels.push_back({mq.vwap_up2, 2, "SD+2"});
    if (mq.vwap_dn2 > 0) option_levels.push_back({mq.vwap_dn2, 2, "SD-2"});

    // Chercher le niveau score >= 2 le plus proche
    float nearest_option_level = 0;
    float nearest_option_dist = 999999.0f;
    int nearest_option_score = 0;
    const char* nearest_option_name = "";

    for (const auto& lvl : option_levels) {
        if (lvl.score >= MIN_LEVEL_SCORE_FOR_RECT) {
            float dist = fabs(current_price - lvl.price) / tick_size;
            if (dist <= MAX_LEVEL_DISTANCE_TICKS && dist < nearest_option_dist) {
                nearest_option_dist = dist;
                nearest_option_level = lvl.price;
                nearest_option_score = lvl.score;
                nearest_option_name = lvl.name;
            }
        }
    }

    // 🆕 REJET si aucun niveau score >= 2 à proximité
    bool has_valid_option_level = (nearest_option_level > 0);
    if (!has_valid_option_level) {
        snprintf(result.reason, sizeof(result.reason),
                 "RECT_REJET: Pas de niveau Options score>=2 proche");
        return result;  // Pas de signal!
    }

    // === RECTANGLES (Reversals) ===
    // long_down_up > 0 = Rectangle VERT/BLEU (support) → LONG
    // long_up_down > 0 = Rectangle ROUGE (résistance) → SHORT

    bool has_green_rect = bn.long_down_up > 0;
    bool has_red_rect = bn.long_up_down > 0;

    // === PROXIMITÉ AUX EXTENSION LINES ===
    // Chercher l'extension line support la plus proche (pour LONG)
    float nearest_support = 0;
    float nearest_support_dist = 999999.0f;
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0 && bn.ext_lines_support[i] < current_price) {
            float dist = (current_price - bn.ext_lines_support[i]) / tick_size;
            if (dist < nearest_support_dist && dist <= max_distance_ticks) {
                nearest_support_dist = dist;
                nearest_support = bn.ext_lines_support[i];
            }
        }
    }
    bool near_support_ext = (nearest_support > 0);

    // Chercher l'extension line résistance la plus proche (pour SHORT)
    float nearest_resist = 0;
    float nearest_resist_dist = 999999.0f;
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > 0 && bn.ext_lines_resist[i] > current_price) {
            float dist = (bn.ext_lines_resist[i] - current_price) / tick_size;
            if (dist < nearest_resist_dist && dist <= max_distance_ticks) {
                nearest_resist_dist = dist;
                nearest_resist = bn.ext_lines_resist[i];
            }
        }
    }
    bool near_resist_ext = (nearest_resist > 0);

    // === POINTS (Color) ===
    // Seuils assouplis: color > 5 au lieu de > 10
    bool green_points_present = bn.color_up > 5;
    bool red_points_present = bn.color_down > 5;
    bool green_points_dominant = bn.color_up > bn.color_down;
    bool red_points_dominant = bn.color_down > bn.color_up;

    // === AUTRES SIGNAUX ACHETEURS ===
    // 🔧 30/01/2026: FIX - utiliser num_edge_rect_buy/sell (COUNT) pas edge_buy/sell (PRIX)
    bool has_edge_buy = bn.num_edge_rect_buy > 0;
    bool has_absorb_bid = bn.absorb_bid > 0;
    float double_bid = is_nq ? bn.triple_bid : bn.double_bid;
    bool has_double_bid = double_bid > 0;

    // === AUTRES SIGNAUX VENDEURS ===
    bool has_edge_sell = bn.num_edge_rect_sell > 0;
    bool has_absorb_ask = bn.absorb_ask > 0;
    float double_ask = is_nq ? bn.triple_ask : bn.double_ask;
    bool has_double_ask = double_ask > 0;

    // === CONFLUENCE LONG ===
    // CONDITION: Doit être PROCHE d'une extension line support OU avoir rectangle
    int long_signals = 0;
    if (has_green_rect) long_signals += 2;  // Rectangle = poids 2
    if (near_support_ext) long_signals += 2;  // Proche extension line = poids 2
    if (green_points_present && green_points_dominant) long_signals++;
    if (has_edge_buy) long_signals++;
    if (has_absorb_bid) long_signals++;
    if (has_double_bid) long_signals++;

    // Signal LONG si au moins 2 points ET (proche extension OU rectangle)
    bool long_valid = (long_signals >= 2) && (near_support_ext || has_green_rect);

    if (long_valid) {
        float confluence = 0.30f + (long_signals * 0.08f);  // Base 30% + 8% par signal

        // 🆕 BONUS BOULES VERTES (Color Up) - TRÈS IMPORTANT!
        int green_bonus_pct = 0;
        if (bn.color_up > 20) {
            confluence += 0.12f;  // Beaucoup de boules = +12%
            green_bonus_pct = 12;
        } else if (bn.color_up > 10) {
            confluence += 0.08f;  // Moyennement = +8%
            green_bonus_pct = 8;
        } else if (bn.color_up > 5) {
            confluence += 0.05f;  // Quelques boules = +5%
            green_bonus_pct = 5;
        }

        // Bonus proximité extension line (plus proche = mieux)
        if (near_support_ext && nearest_support_dist <= 5.0f) {
            confluence += 0.10f;  // Très proche = +10%
        } else if (near_support_ext) {
            confluence += 0.05f;  // Proche = +5%
        }

        // Bonus si pas de signaux contraires
        if (!has_red_rect && !has_edge_sell) {
            confluence += 0.08f;
        }

        // Bonus momentum
        if (bn.momentum_score > 0.05f) {
            confluence += 0.05f;
        }

        // ⚠️ COLOR_DOWN = flux local, pas obstacle structurel → malus léger seulement
        if (bn.color_down > bn.color_up * 1.5f) {
            confluence -= 0.05f;  // Réduit de -0.15 à -0.05 (flux local, pas veto)
        }

        // Bonus si proche d'un niveau score 3 (MAJEUR)
        if (nearest_option_score == 3 && nearest_option_dist <= 10.0f) {
            confluence += 0.08f;  // Bonus niveau majeur!
        }

        // Valider si confluence >= 0.60 (qualité!)
        if (confluence >= 0.60f) {
            result.has_signal = true;
            result.direction = 1;  // LONG
            result.confidence = confluence;
            result.rectangle_price = near_support_ext ? nearest_support : (has_green_rect ? bn.long_down_up : current_price);
            result.confluence_score = confluence;
            snprintf(result.reason, sizeof(result.reason),
                "RECT_LONG: %s@%.0ft Boules+%d%% Rect=%d Conf=%.0f%%",
                nearest_option_name, nearest_option_dist,
                green_bonus_pct, has_green_rect?1:0, confluence * 100);
        }
    }

    // === CONFLUENCE SHORT ===
    // CONDITION: Doit être PROCHE d'une extension line résistance OU avoir rectangle
    int short_signals = 0;
    if (has_red_rect) short_signals += 2;  // Rectangle = poids 2
    if (near_resist_ext) short_signals += 2;  // Proche extension line = poids 2
    if (red_points_present && red_points_dominant) short_signals++;
    if (has_edge_sell) short_signals++;
    if (has_absorb_ask) short_signals++;
    if (has_double_ask) short_signals++;

    // Signal SHORT si au moins 2 points ET (proche extension OU rectangle) ET pas déjà LONG
    bool short_valid = !result.has_signal && (short_signals >= 2) && (near_resist_ext || has_red_rect);

    if (short_valid) {
        float confluence = 0.30f + (short_signals * 0.08f);  // Base 30% + 8% par signal

        // 🆕 BONUS BOULES ROUGES (Color Down) - TRÈS IMPORTANT!
        int red_bonus_pct = 0;
        if (bn.color_down > 20) {
            confluence += 0.12f;  // Beaucoup de boules = +12%
            red_bonus_pct = 12;
        } else if (bn.color_down > 10) {
            confluence += 0.08f;  // Moyennement = +8%
            red_bonus_pct = 8;
        } else if (bn.color_down > 5) {
            confluence += 0.05f;  // Quelques boules = +5%
            red_bonus_pct = 5;
        }

        // Bonus proximité extension line (plus proche = mieux)
        if (near_resist_ext && nearest_resist_dist <= 5.0f) {
            confluence += 0.10f;  // Très proche = +10%
        } else if (near_resist_ext) {
            confluence += 0.05f;  // Proche = +5%
        }

        // Bonus si pas de signaux contraires
        if (!has_green_rect && !has_edge_buy) {
            confluence += 0.08f;
        }

        // Bonus momentum
        if (bn.momentum_score < -0.05f) {
            confluence += 0.05f;
        }

        // ⚠️ COLOR_UP = flux local, pas obstacle structurel → malus léger seulement
        if (bn.color_up > bn.color_down * 1.5f) {
            confluence -= 0.05f;  // Réduit de -0.15 à -0.05 (flux local, pas veto)
        }

        // Bonus si proche d'un niveau score 3 (MAJEUR)
        if (nearest_option_score == 3 && nearest_option_dist <= 10.0f) {
            confluence += 0.08f;  // Bonus niveau majeur!
        }

        // Valider si confluence >= 0.60 (qualité!)
        if (confluence >= 0.60f) {
            result.has_signal = true;
            result.direction = -1;  // SHORT
            result.confidence = confluence;
            result.rectangle_price = near_resist_ext ? nearest_resist : (has_red_rect ? bn.long_up_down : current_price);
            result.confluence_score = confluence;
            snprintf(result.reason, sizeof(result.reason),
                "RECT_SHORT: %s@%.0ft Boules+%d%% Rect=%d Conf=%.0f%%",
                nearest_option_name, nearest_option_dist,
                red_bonus_pct, has_red_rect?1:0, confluence * 100);
        }
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8: LAYER 2 - ORDERFLOW + BATAILLE NAVALE
// ═══════════════════════════════════════════════════════════════════════════════

struct Layer2Result {
    bool passed;
    float confidence;
    float bn_score;
    char correlation[32];
    char reason[256];
};

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 TRADE HAUTE QUALITÉ - Détection et configuration risque augmenté
// ═══════════════════════════════════════════════════════════════════════════════
// Critères Haute Qualité:
// ✅ Niveau Score ≥ 2
// ✅ visual_count >= 2 (au moins 2 signaux)
// ✅ stacked_buy_zones >= 2 OU attack_strength >= 0.6
// ✅ bn_attack_valid = true (pas de signal opposé)
// ✅ Entrée au PLUS BAS des visuels
// ✅ TP sans obstacle
// ═══════════════════════════════════════════════════════════════════════════════

struct HighQualityResult {
    bool is_high_quality;
    float hq_score;           // 0.0 à 1.0
    char reason[128];

    // Paramètres de risque pour HQ
    float tp_multiplier;      // Multiplicateur TP (ex: 1.5x)
    float sl_multiplier;      // Multiplicateur SL (ex: 1.2x pour plus de marge)
    int position_size_mult;   // Multiplicateur taille position (ex: 2)
};

HighQualityResult DetectHighQualityTrade(
    int direction,
    const BN_Data& bn,
    int level_score,          // Score du niveau MenthorQ (1, 2, ou 3)
    int visual_count,         // Nombre de signaux visuels
    bool has_obstacle_tp      // Y a-t-il un obstacle avant le TP?
) {
    HighQualityResult result = {false, 0.0f, "", 1.0f, 1.0f, 1};

    float hq_score = 0.0f;
    int criteria_met = 0;

    // === Critère 1: Niveau Score ≥ 2 (OBLIGATOIRE pour HQ) ===
    if (level_score >= 2) {
        hq_score += 0.20f;
        criteria_met++;
    } else {
        // Score 1 = pas haute qualité
        snprintf(result.reason, sizeof(result.reason), "Score=%d (<2)", level_score);
        return result;
    }

    // === Critère 2: Au moins 2 signaux visuels ===
    if (visual_count >= 2) {
        hq_score += 0.15f;
        criteria_met++;
        if (visual_count >= 3) hq_score += 0.10f;  // Bonus 3+ signaux
    }

    // === Critère 3: Empilement ou force d'attaque ===
    bool has_stacking = false;
    if (direction == 1) {
        if (bn.stacked_buy_zones >= 2 || bn.attack_strength_buy >= 0.6f) {
            hq_score += 0.20f;
            criteria_met++;
            has_stacking = true;
        }
    } else {
        if (bn.stacked_sell_zones >= 2 || bn.attack_strength_sell >= 0.6f) {
            hq_score += 0.20f;
            criteria_met++;
            has_stacking = true;
        }
    }

    // === Critère 4: Configuration Bataille Navale valide ===
    bool bn_valid = (direction == 1) ? bn.bn_attack_long_valid : bn.bn_attack_short_valid;
    if (bn_valid) {
        hq_score += 0.15f;
        criteria_met++;
    }

    // === Critère 5: Cohérence directionnelle ===
    bool coherent = (direction == 1) ? (bn.directional_coherence > 0.5f) : (bn.directional_coherence < -0.5f);
    if (coherent) {
        hq_score += 0.10f;
        criteria_met++;
    }

    // === Critère 6: Pas d'obstacle vers le TP ===
    if (!has_obstacle_tp) {
        hq_score += 0.10f;
        criteria_met++;
    }

    // === DÉCISION HAUTE QUALITÉ ===
    // Minimum 4 critères sur 6 ET score >= 0.60
    result.is_high_quality = (criteria_met >= 4 && hq_score >= 0.60f);
    result.hq_score = hq_score;

    if (result.is_high_quality) {
        // === PARAMÈTRES DE RISQUE AUGMENTÉ POUR HQ ===

        // TP plus ambitieux (+50%)
        result.tp_multiplier = 1.5f;

        // SL légèrement plus large pour éviter le bruit (+20%)
        result.sl_multiplier = 1.2f;

        // Position size x2 (à configurer selon capital)
        result.position_size_mult = 2;

        // Si cohérence TOTALE + empilement fort = encore plus agressif
        bool all_aligned = (direction == 1) ? bn.all_signals_bullish : bn.all_signals_bearish;
        if (all_aligned && has_stacking && hq_score >= 0.80f) {
            result.tp_multiplier = 2.0f;  // TP x2
            result.position_size_mult = 2; // Garder x2 (pas trop risqué)
            snprintf(result.reason, sizeof(result.reason),
                     "🔥 HQ PREMIUM: Score=%.0f%% Crit=%d Stack=%d Coh=TOTAL → TP×2",
                     hq_score * 100, criteria_met,
                     direction == 1 ? bn.stacked_buy_zones : bn.stacked_sell_zones);
        } else {
            snprintf(result.reason, sizeof(result.reason),
                     "✅ HQ: Score=%.0f%% Crit=%d/%d Stack=%d → TP×1.5 Size×2",
                     hq_score * 100, criteria_met, 6,
                     direction == 1 ? bn.stacked_buy_zones : bn.stacked_sell_zones);
        }
    } else {
        snprintf(result.reason, sizeof(result.reason),
                 "Standard: Score=%.0f%% Crit=%d/6", hq_score * 100, criteria_met);
    }

    return result;
}

Layer2Result ValidateLayer2(
    int direction,
    const BN_Data& bn_primary,
    const BN_Data& bn_secondary,
    float vix,
    float delta,
    float buy_pct,
    const SymbolConfig& config,
    bool is_nq,
    float depth_imbalance = 0.0f,   // 🔧 AJOUT 25/01/2026
    float sell_pct = 0.5f,          // 🔧 AJOUT 25/01/2026
    float vwap_slope = 0.0f         // 🔧 AJOUT 25/01/2026
) {
    Layer2Result result = {false, 0, 0, "", ""};

    result.bn_score = bn_primary.score;

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 OPTIMISÉ 25/01/2026: LAYER 2 = EDGE DOMINANT + DEPTH IMBALANCE (2/2 REQUIS)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Calculer edge_buy et edge_sell totaux
    float edge_buy = bn_primary.edge_buy + bn_primary.bar_edge_buy;
    float edge_sell = bn_primary.edge_sell + bn_primary.bar_edge_sell;
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026 16h30: EDGE DOMINANT = OBLIGATOIRE (PAS D'EXCEPTION!)
    // Leçon du jour: Le bot a BIEN FAIT de rejeter le LONG à 7005
    // → Le marché a chuté de 18 pts après! Les vendeurs étaient là.
    // "Mieux vaut rater un trade que prendre un trade perdant"
    // ═══════════════════════════════════════════════════════════════════════════
    
    // 1. EDGE DOMINANT - 🔧 28/01/2026: DÉSACTIVÉ!
    // RAISON: Les études EDGE ZONES retournent des PRIX, pas des counts!
    // Les logs montrent buy=52568 sell=52569 (prix NQ) au lieu de counts
    // Ce filtre est INUTILISABLE tant que les données sont incorrectes
    // TODO: Trouver la bonne source de données Edge ou supprimer ce filtre
    /*
    bool edge_ok = false;
    bool edge_neutral = (edge_buy == edge_sell);
    if (edge_neutral) {
        edge_ok = true;
    } else if (direction == 1) {
        edge_ok = (edge_buy >= edge_sell);
    } else {
        edge_ok = (edge_sell >= edge_buy);
    }
    if (!edge_ok) {
        snprintf(result.reason, sizeof(result.reason),
                 "L2 REJET: Edge CONTRE nous (buy=%.0f sell=%.0f) pour %s",
                 edge_buy, edge_sell, direction == 1 ? "LONG" : "SHORT");
        return result;
    }
    */
    
    // 2. DEPTH IMBALANCE (ASSOUPLI - 28/01/2026)
    // 🔧 FIX v2: Zone neutre ÉLARGIE à ±0.25 (DOM fluctue beaucoup!)
    // Rejette SEULEMENT si DOM FORTEMENT CONTRE nous (> 25% déséquilibre)
    bool depth_ok = false;
    bool depth_neutral = (fabs(depth_imbalance) < 0.25f);  // Zone neutre ±0.25
    
    if (depth_neutral) {
        // DOM neutre ou légèrement biaisé = on laisse passer
        depth_ok = true;
    } else if (direction == 1) {  // LONG
        // 🔧 28/01/2026: ASSOUPLI -0.25 → -0.50 (accepte plus de pressure vendeuse)
        // LONG: OK si depth >= -0.50 (accepte neutre et positif)
        depth_ok = (depth_imbalance >= -0.50f);
    } else {  // SHORT
        // 🔧 28/01/2026: ASSOUPLI 0.25 → 0.50 (accepte plus de pressure acheteuse)
        // SHORT: OK si depth <= 0.50 (accepte neutre et négatif)
        depth_ok = (depth_imbalance <= 0.50f);
    }
    
    if (!depth_ok) {
        snprintf(result.reason, sizeof(result.reason),
                 "L2 REJET: Depth CONTRE nous (imb=%.3f) pour %s",
                 depth_imbalance, direction == 1 ? "LONG" : "SHORT");
        return result;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 LAYER 3: VWAP SLOPE + BUY/SELL % (25/01/2026)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // 🔧 27/01/2026: VWAP Slope ASSOUPLI - seuil adaptatif par symbole
    // ES (is_nq=false): ±0.05 (très permissif, rejette seulement forte contre-tendance)
    // NQ/RTY (is_nq=true): ±0.03 (assoupli de 0.01 → 0.03, NQ bouge plus!)
    float vwap_threshold = is_nq ? 0.03f : 0.05f;
    
    bool vwap_ok = false;
    if (direction == 1) {  // LONG
        vwap_ok = (vwap_slope > -vwap_threshold);
    } else {  // SHORT
        vwap_ok = (vwap_slope < vwap_threshold);
    }
    
    // 🔧 28/01/2026: FILTRE VWAP "DEAD ZONE" encore plus assoupli
    // Seuil réduit: 0.0001 → 0.00003 (permet marchés très calmes)
    // Rejette seulement si VWAP complètement plat (< 0.00003)
    if (fabs(vwap_slope) < 0.00003f) {
        snprintf(result.reason, sizeof(result.reason),
                 "L3 REJET: VWAP trop plat (%.5f < 0.00003) - Marché indecis!",
                 vwap_slope);
        return result;
    }
    
    if (!vwap_ok) {
        snprintf(result.reason, sizeof(result.reason),
                 "L3 REJET: VWAP slope=%.4f hors seuil (%s: >%.2f LONG, <%.2f SHORT)",
                 vwap_slope, is_nq ? "NQ" : "ES", -vwap_threshold, vwap_threshold);
        return result;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 30/01/2026 NUIT: NOUVEAU LAYER 3 SIMPLIFIÉ (78% NQ, 82% ES WinRate!)
    // Basé sur tests L1+L2+features - VWAP_SLOPE + indicateur spécifique
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Métriques clés pour L3
    // NQ: vwap_slope + smart_money (institutional_pressure)
    // ES: vwap_slope + deltaPct (fpbs_delta)
    
    bool smart_money_bullish = (bn_primary.institutional_pressure > 0);
    bool smart_money_bearish = (bn_primary.institutional_pressure < 0);
    
    // fpbs_delta > 0 = plus d'achats que de ventes (bullish)
    // fpbs_delta < 0 = plus de ventes que d'achats (bearish)
    bool delta_bullish = (bn_primary.fpbs_delta > 0);
    bool delta_bearish = (bn_primary.fpbs_delta < 0);
    
    // VWAP slope déjà vérifié plus haut, on utilise vwap_slope
    bool vwap_bullish = (vwap_slope > 0);
    bool vwap_bearish = (vwap_slope < 0);
    
    bool l3_passed = false;
    char l3_detail[128] = "";
    
    if (is_nq) {
        // ═══════════════════════════════════════════════════════════════════════
        // NQ: vwap_slope>0 AND smart_money>0 (78.4% WinRate, 37 trades)
        // ═══════════════════════════════════════════════════════════════════════
        if (direction == 1) {  // LONG
            l3_passed = vwap_bullish && smart_money_bullish;
            snprintf(l3_detail, sizeof(l3_detail),
                     "NQ LONG: VWAP=%.4f (>0?%s) + SmartMoney=%.2f (>0?%s)",
                     vwap_slope, vwap_bullish ? "OK" : "NO",
                     bn_primary.institutional_pressure, smart_money_bullish ? "OK" : "NO");
        } else {  // SHORT
            l3_passed = vwap_bearish && smart_money_bearish;
            snprintf(l3_detail, sizeof(l3_detail),
                     "NQ SHORT: VWAP=%.4f (<0?%s) + SmartMoney=%.2f (<0?%s)",
                     vwap_slope, vwap_bearish ? "OK" : "NO",
                     bn_primary.institutional_pressure, smart_money_bearish ? "OK" : "NO");
        }
    } else {
        // ═══════════════════════════════════════════════════════════════════════
        // ES: vwap_slope>0 AND deltaPct>0 (81.8% WinRate, 11 trades)
        // ═══════════════════════════════════════════════════════════════════════
        if (direction == 1) {  // LONG
            l3_passed = vwap_bullish && delta_bullish;
            snprintf(l3_detail, sizeof(l3_detail),
                     "ES LONG: VWAP=%.4f (>0?%s) + Delta=%.0f (>0?%s)",
                     vwap_slope, vwap_bullish ? "OK" : "NO",
                     bn_primary.fpbs_delta, delta_bullish ? "OK" : "NO");
        } else {  // SHORT
            l3_passed = vwap_bearish && delta_bearish;
            snprintf(l3_detail, sizeof(l3_detail),
                     "ES SHORT: VWAP=%.4f (<0?%s) + Delta=%.0f (<0?%s)",
                     vwap_slope, vwap_bearish ? "OK" : "NO",
                     bn_primary.fpbs_delta, delta_bearish ? "OK" : "NO");
        }
    }
    
    if (!l3_passed) {
        snprintf(result.reason, sizeof(result.reason),
                 "L3 REJET: %s", l3_detail);
        return result;
    }
    
    // Log succès pour debug
    // snprintf(result.reason, sizeof(result.reason), "L3 OK: %s", l3_detail);
    
    // ═══════════════════════════════════════════════════════════════════════════
    // ANCIEN CODE BN SCORE (DÉSACTIVÉ - GARDÉ POUR RÉFÉRENCE)
    // ═══════════════════════════════════════════════════════════════════════════
    /*
    // === 🆕 PRO: Seuils adaptatifs VIX (STRICTS) ===
    float bn_long_min, bn_short_max;
    if (vix < 15) {
        bn_long_min = 0.05f;
        bn_short_max = -0.05f;
    } else if (vix <= 25) {
        bn_long_min = 0.0f;
        bn_short_max = 0.0f;
    } else {
        bn_long_min = -0.03f;
        bn_short_max = 0.03f;
    }

    bool bn_ok = false;
    if (direction == 1) {
        bn_ok = bn_primary.score >= bn_long_min;
    } else {
        bn_ok = bn_primary.score <= bn_short_max;
    }

    if (!bn_ok) {
        snprintf(result.reason, sizeof(result.reason),
                 "BN score %.2f hors seuil", bn_primary.score);
        return result;
    }
    */

    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 RÈGLE CRITIQUE: EXIGER AU MOINS UN SIGNAL VISUEL (boule/edge/rectangle)
    // Les trades SANS signaux visuels ont un taux de SL beaucoup plus élevé!
    // ═══════════════════════════════════════════════════════════════════════
    bool has_visual_signal = false;
    int visual_count = 0;

    if (direction == 1) {  // LONG - chercher signaux ACHETEURS
        // Boules vertes (Color Up)
        if (bn_primary.color_up > 10) { has_visual_signal = true; visual_count++; }
        // Edge Buy (imbalance DIAG: 600% ES, 0% NQ)
        if (bn_primary.edge_buy > 0) { has_visual_signal = true; visual_count++; }
        // Rectangle vert reversal (Long Down Up Bar)
        if (bn_primary.long_down_up > 0) { has_visual_signal = true; visual_count++; }
        // 🆕 Rectangle vert TRADABLE (Long Up Bar) - NOUVEAU!
        if (bn_primary.has_tradable_support) { has_visual_signal = true; visual_count++; }
        // Double/Triple Bid
        if (bn_primary.double_bid > 0 || bn_primary.triple_bid > 0) { has_visual_signal = true; visual_count++; }
        // Absorption Bid
        if (bn_primary.absorb_bid > 0) { has_visual_signal = true; visual_count++; }
        // Prix DANS un gros rectangle vert (Edge Zone massive)
        if (bn_primary.price_in_edge_rect_buy) { has_visual_signal = true; visual_count++; }
    } else {  // SHORT - chercher signaux VENDEURS
        // Boules rouges (Color Down)
        if (bn_primary.color_down > 10) { has_visual_signal = true; visual_count++; }
        // Edge Sell (imbalance DIAG: 600% ES, 0% NQ)
        if (bn_primary.edge_sell > 0) { has_visual_signal = true; visual_count++; }
        // Rectangle rouge reversal (Long Up Down Bar)
        if (bn_primary.long_up_down > 0) { has_visual_signal = true; visual_count++; }
        // 🆕 Rectangle rouge TRADABLE (Long Down Bar) - NOUVEAU!
        if (bn_primary.has_tradable_resist) { has_visual_signal = true; visual_count++; }
        // Double/Triple Ask
        if (bn_primary.double_ask > 0 || bn_primary.triple_ask > 0) { has_visual_signal = true; visual_count++; }
        // Absorption Ask
        if (bn_primary.absorb_ask > 0) { has_visual_signal = true; visual_count++; }
        // Prix DANS un gros rectangle rouge (Edge Zone massive)
        if (bn_primary.price_in_edge_rect_sell) { has_visual_signal = true; visual_count++; }
    }

    if (!has_visual_signal) {
        snprintf(result.reason, sizeof(result.reason),
                 "REJET: Aucun signal visuel BN (boule/edge/rect) pour %s",
                 direction == 1 ? "LONG" : "SHORT");
        return result;
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 BONUS CONFLUENCE: Si RECTANGLE TRADABLE présent, vérifier CONFLUENCE
    // Les rectangles SEULS ne suffisent PAS - il faut AUSSI des boules!
    // Règle: RECTANGLE + CONFLUENCE = Trade de qualité supérieure
    // ═══════════════════════════════════════════════════════════════════════
    bool has_tradable_rect = false;
    bool has_confluence = false;
    
    if (direction == 1) {  // LONG
        has_tradable_rect = bn_primary.has_tradable_support || bn_primary.long_down_up > 0;
        has_confluence = (bn_primary.color_up > 5) || (bn_primary.rotation_up > 30) || 
                         (bn_primary.absorb_bid > 0) || (bn_primary.edge_buy > 2);
    } else {  // SHORT
        has_tradable_rect = bn_primary.has_tradable_resist || bn_primary.long_up_down > 0;
        has_confluence = (bn_primary.color_down > 5) || (bn_primary.rotation_down > 30) || 
                         (bn_primary.absorb_ask > 0) || (bn_primary.edge_sell > 2);
    }
    
    // Si on a un rectangle tradable SANS confluence, c'est un signal FAIBLE
    // On le LOG mais on ne REJETTE PAS (les autres filtres font le travail)
    if (has_tradable_rect && !has_confluence) {
        // Log d'avertissement mais pas de rejet
        // Les autres filtres (Edge Dominant, Depth, VWAP) protègent déjà
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 VETO SIGNAL OPPOSÉ: Ne JAMAIS trader contre une zone visible!
    // Une boule verte = acheteurs agressifs → NE PAS VENDRE
    // Une boule rouge = vendeurs agressifs → NE PAS ACHETER
    // Un gros rectangle vert = zone achat → NE PAS VENDRE ICI
    // Un gros rectangle rouge = zone vente → NE PAS ACHETER ICI
    // ═══════════════════════════════════════════════════════════════════════
    if (direction == -1) {  // SHORT
        // 🆕 VETO si prix DANS un gros rectangle vert (zone d'achat!)
        if (bn_primary.price_in_edge_rect_buy) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO: Prix DANS rectangle VERT - Zone ACHETEURS! NE PAS VENDRE!");
            return result;
        }
        // 🆕 BATAILLE NAVALE: VETO si configuration "pas de boule verte au-dessus" invalide
        if (!bn_primary.bn_attack_short_valid && bn_primary.num_edge_rect_buy > 0) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO BN: Boule VERTE au-dessus des ROUGES - Configuration SHORT invalide!");
            return result;
        }
        // ═══════════════════════════════════════════════════════════════════════════
        // 🆕 30/01/2026: RÈGLE SUBTILE AVEC BOULES (Alignement Python)
        // SHORT bloqué si boule VERTE au-dessus de la BASE ROUGE
        // ═══════════════════════════════════════════════════════════════════════════
        if (!bn_primary.bn_subtile_short_valid) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO SUBTILE: %s - Configuration SHORT invalide!", 
                     bn_primary.subtile_short_reason);
            return result;
        }
        // ═══════════════════════════════════════════════════════════════════════════
        // 🆕 30/01/2026: MODE RANGE - SHORT bloqué si prix NEAR_SUPPORT
        // En mode RANGE: acheter en BAS, vendre en HAUT
        // ═══════════════════════════════════════════════════════════════════════════
        if (bn_primary.is_range && bn_primary.price_position == 0) {  // 0 = NEAR_SUPPORT
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO RANGE: SHORT bloqué en BAS du range (%.0f%%) - Support %.2f Resist %.2f",
                     bn_primary.price_position_pct, bn_primary.range_support, bn_primary.range_resistance);
            return result;
        }
        // 🔧 26/01/2026: VETO BN ASSOUPLI - Ratio au lieu de binaire
        // Tolérer jusqu'à 30% de signal opposé (au lieu de rejeter dès edge_buy > 0)
        // Exemple: edge_buy=10, edge_sell=40 → OK (10 < 40*0.3=12)
        float bn_veto_ratio = 0.3f;
        if (bn_primary.edge_buy > bn_primary.edge_sell * bn_veto_ratio) {
            snprintf(result.reason, sizeof(result.reason),
                     "VETO BN: Boule VERTE trop forte (edge_buy=%d > edge_sell=%d * 0.3) - Structure SHORT compromise!",
                     (int)bn_primary.edge_buy, (int)bn_primary.edge_sell);
            return result;
        }
        // VETO si forte absorption BID (acheteurs défendent) - seuil releve a 10
        if (bn_primary.absorb_bid > 10) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO: Absorption BID forte (%d) - Acheteurs defendent!",
                     (int)bn_primary.absorb_bid);
            return result;
        }
    } else {  // LONG
        // 🆕 VETO si prix DANS un gros rectangle rouge (zone de vente!)
        if (bn_primary.price_in_edge_rect_sell) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO: Prix DANS rectangle ROUGE - Zone VENDEURS! NE PAS ACHETER!");
            return result;
        }
        // 🆕 BATAILLE NAVALE: VETO si configuration "pas de boule rouge sous" invalide
        if (!bn_primary.bn_attack_long_valid && bn_primary.num_edge_rect_sell > 0) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO BN: Boule ROUGE sous les VERTS - Configuration LONG invalide!");
            return result;
        }
        // ═══════════════════════════════════════════════════════════════════════════
        // 🆕 30/01/2026: RÈGLE SUBTILE AVEC BOULES (Alignement Python)
        // LONG bloqué si boule ROUGE sous la BASE VERTE
        // ═══════════════════════════════════════════════════════════════════════════
        if (!bn_primary.bn_subtile_long_valid) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO SUBTILE: %s - Configuration LONG invalide!", 
                     bn_primary.subtile_long_reason);
            return result;
        }
        // ═══════════════════════════════════════════════════════════════════════════
        // 🆕 30/01/2026: MODE RANGE - LONG bloqué si prix NEAR_RESISTANCE
        // En mode RANGE: acheter en BAS, vendre en HAUT
        // ═══════════════════════════════════════════════════════════════════════════
        if (bn_primary.is_range && bn_primary.price_position == 2) {  // 2 = NEAR_RESISTANCE
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO RANGE: LONG bloqué en HAUT du range (%.0f%%) - Support %.2f Resist %.2f",
                     bn_primary.price_position_pct, bn_primary.range_support, bn_primary.range_resistance);
            return result;
        }
        // 🔧 26/01/2026: VETO BN ASSOUPLI - Ratio au lieu de binaire
        // Tolérer jusqu'à 30% de signal opposé (au lieu de rejeter dès edge_sell > 0)
        // Exemple: edge_sell=10, edge_buy=40 → OK (10 < 40*0.3=12)
        float bn_veto_ratio = 0.3f;
        if (bn_primary.edge_sell > bn_primary.edge_buy * bn_veto_ratio) {
            snprintf(result.reason, sizeof(result.reason),
                     "VETO BN: Boule ROUGE trop forte (edge_sell=%d > edge_buy=%d * 0.3) - Structure LONG compromise!",
                     (int)bn_primary.edge_sell, (int)bn_primary.edge_buy);
            return result;
        }
        // VETO si forte absorption ASK (vendeurs défendent) - seuil releve a 10
        if (bn_primary.absorb_ask > 10) {
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO: Absorption ASK forte (%d) - Vendeurs defendent!",
                     (int)bn_primary.absorb_ask);
            return result;
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 CVD DIVERGENCE VETO - NE JAMAIS trader contre le flow cumulé!
    // Divergence = Prix monte + CVD chute (bull trap) ou inverse
    // C'est un signal de PIÈGE institutionnel - très fiable!
    // ═══════════════════════════════════════════════════════════════════════
    if (bn_primary.cvd_divergence) {
        if (direction == 1) {  // LONG avec divergence bearish
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO CVD: DIVERGENCE BEARISH! CVD chute (slope=%.0f) pendant que prix monte - BULL TRAP!",
                     bn_primary.cvd_slope);
            return result;
        } else {  // SHORT avec divergence bullish
            snprintf(result.reason, sizeof(result.reason),
                     "🛑 VETO CVD: DIVERGENCE BULLISH! CVD monte (slope=%.0f) pendant que prix baisse - BEAR TRAP!",
                     bn_primary.cvd_slope);
            return result;
        }
    }
    
    // 🆕 CVD STRONG COUNTER-TREND VETO (même sans divergence flagrante)
    // Si CVD va fortement contre notre direction = DANGER
    const float CVD_STRONG_THRESHOLD = 500.0f;
    if (direction == 1 && bn_primary.cvd_slope < -CVD_STRONG_THRESHOLD) {
        snprintf(result.reason, sizeof(result.reason),
                 "🛑 VETO CVD: Flow VENDEUR fort (slope=%.0f < -500) - NE PAS acheter contre le flow!",
                 bn_primary.cvd_slope);
        return result;
    }
    if (direction == -1 && bn_primary.cvd_slope > CVD_STRONG_THRESHOLD) {
        snprintf(result.reason, sizeof(result.reason),
                 "🛑 VETO CVD: Flow ACHETEUR fort (slope=%.0f > +500) - NE PAS vendre contre le flow!",
                 bn_primary.cvd_slope);
        return result;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 BATAILLE NAVALE: BONUS pour configuration d'attaque valide
    // ═══════════════════════════════════════════════════════════════════════
    float bn_attack_bonus = 0.0f;

    if (direction == 1 && bn_primary.bn_attack_long_valid) {
        // BONUS: Rectangles verts empilés = attaque coordonnée
        bn_attack_bonus += bn_primary.attack_strength_buy * 0.10f;
        // BONUS: Cohérence directionnelle totale
        if (bn_primary.all_signals_bullish) {
            bn_attack_bonus += 0.08f;
        } else if (bn_primary.directional_coherence > 0.5f) {
            bn_attack_bonus += 0.04f;
        }
    }
    if (direction == -1 && bn_primary.bn_attack_short_valid) {
        bn_attack_bonus += bn_primary.attack_strength_sell * 0.10f;
        if (bn_primary.all_signals_bearish) {
            bn_attack_bonus += 0.08f;
        } else if (bn_primary.directional_coherence < -0.5f) {
            bn_attack_bonus += 0.04f;
        }
    }

    // === Corrélation ES/NQ (si NQ) ===
    strcpy(result.correlation, "SOLO");
    float corr_bonus = 0;

    // 🔧 25/01/2026: Définir seuils BN pour corrélation (valeurs fixes car VIX adaptatif désactivé)
    float bn_long_min = config.l2_bn_score_min_long;   // Typiquement -0.05
    float bn_short_max = config.l2_bn_score_max_short; // Typiquement 0.05

    if (is_nq) {
        float score_es = bn_secondary.score;

        if (direction == 1) {  // LONG NQ
            if (score_es > bn_primary.score && score_es > 0) {
                strcpy(result.correlation, "ES_LEADS_BULL");
                corr_bonus = 0.03f;
            } else if (score_es > bn_long_min * 0.5f) {
                strcpy(result.correlation, "ES_CONFIRMS");
                corr_bonus = 0.01f;
            } else if (score_es < -0.20f) {
                // VETO - ES trop bearish
                snprintf(result.reason, sizeof(result.reason),
                         "VETO Divergence ES/NQ: ES=%.2f vs NQ=%.2f",
                         score_es, bn_primary.score);
                strcpy(result.correlation, "DIVERGENT");
                return result;
            }
        } else {  // SHORT NQ
            if (score_es < bn_primary.score && score_es < 0) {
                strcpy(result.correlation, "ES_LEADS_BEAR");
                corr_bonus = 0.03f;
            } else if (score_es < bn_short_max * 0.5f) {
                strcpy(result.correlation, "ES_CONFIRMS");
                corr_bonus = 0.01f;
            } else if (score_es > 0.20f) {
                // VETO
                snprintf(result.reason, sizeof(result.reason),
                         "VETO Divergence ES/NQ: ES=%.2f vs NQ=%.2f",
                         score_es, bn_primary.score);
                strcpy(result.correlation, "DIVERGENT");
                return result;
            }
        }
    }

    // === Règle d'Or #2: Absence = Confirmation (fonction complète) ===
    float absence_bonus = CheckGoldenRule2_Bonus(bn_primary, direction);

    // === OrderFlow classique ===
    float of_score = 0;
    if (direction == 1) {
        if (delta > 0) of_score += 0.05f;
        if (buy_pct > 0.50f) of_score += 0.03f;
    } else {
        if (delta < 0) of_score += 0.05f;
        if (buy_pct < 0.50f) of_score += 0.03f;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 PRO FEATURES BONUS - Utilisation des nouvelles métriques
    // ═══════════════════════════════════════════════════════════════════════════
    float pro_bonus = 0;

    // 1. MOMENTUM SHIFT BONUS (+5%)
    // Si le momentum vient de changer en notre faveur = signal frais!
    if (direction == 1 && bn_primary.momentum_shift > 0) {
        pro_bonus += 0.05f;  // Shift bullish pour LONG
    }
    if (direction == -1 && bn_primary.momentum_shift < 0) {
        pro_bonus += 0.05f;  // Shift bearish pour SHORT
    }

    // 2. RECTANGLE FRAIS BONUS (+8%)
    // Une zone institutionnelle VIENT d'être touchée = signal TRÈS fort!
    if (direction == 1 && bn_primary.fresh_rectangle_buy) {
        pro_bonus += 0.08f;  // Zone achat frais pour LONG
    }
    if (direction == -1 && bn_primary.fresh_rectangle_sell) {
        pro_bonus += 0.08f;  // Zone vente frais pour SHORT
    }

    // 3. EDGE DOMINANT BONUS (+4%)
    // Domination claire des edge zones = forte conviction
    if (direction == 1 && bn_primary.edge_dominant_buy) {
        pro_bonus += 0.04f;  // Acheteurs dominent pour LONG
    }
    if (direction == -1 && bn_primary.edge_dominant_sell) {
        pro_bonus += 0.04f;  // Vendeurs dominent pour SHORT
    }

    // 4. CONTRE-SIGNAL MALUS (-5%)
    // Si les métriques PRO sont CONTRE notre direction = malus
    if (direction == 1 && bn_primary.momentum_shift < 0) {
        pro_bonus -= 0.05f;  // Shift bearish mais on veut LONG
    }
    if (direction == -1 && bn_primary.momentum_shift > 0) {
        pro_bonus -= 0.05f;  // Shift bullish mais on veut SHORT
    }

    // === BONUS CONFLUENCE VISUELLE (+3% par signal supplémentaire) ===
    float visual_bonus = 0;
    if (visual_count >= 2) {
        visual_bonus = (visual_count - 1) * 0.03f;  // +3% par signal après le 1er
        if (visual_bonus > 0.12f) visual_bonus = 0.12f;  // Max +12%
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 COLOR_UP/DOWN BONUS/MALUS (flux local, pas veto structurel)
    // ⚠️ COLOR_UP/DOWN = petits points de flux/momentum → ajuste confiance seulement
    // ═══════════════════════════════════════════════════════════════════════════
    float color_bonus = 0.0f;
    if (direction == 1) {  // LONG
        // Bonus si COLOR_UP présent (momentum local haussier)
        if (bn_primary.color_up > 10) {
            color_bonus += 0.05f;  // +5% si beaucoup de points verts
        } else if (bn_primary.color_up > 5) {
            color_bonus += 0.03f;  // +3% si quelques points verts
        }
        // Malus léger si COLOR_DOWN dominant (momentum local baissier)
        if (bn_primary.color_down > bn_primary.color_up * 1.5f) {
            color_bonus -= 0.05f;  // -5% seulement (pas de veto)
        }
    } else {  // SHORT
        // Bonus si COLOR_DOWN présent (momentum local baissier)
        if (bn_primary.color_down > 10) {
            color_bonus += 0.05f;  // +5% si beaucoup de points rouges
        } else if (bn_primary.color_down > 5) {
            color_bonus += 0.03f;  // +3% si quelques points rouges
        }
        // Malus léger si COLOR_UP dominant (momentum local haussier)
        if (bn_primary.color_up > bn_primary.color_down * 1.5f) {
            color_bonus -= 0.05f;  // -5% seulement (pas de veto)
        }
    }

    // === Score final (incluant bonus Bataille Navale) ===
    result.confidence = 0.06f + corr_bonus + absence_bonus + of_score + pro_bonus + visual_bonus + color_bonus + bn_attack_bonus;
    result.passed = true;

    // Détail de l'attaque BN pour le log
    const char* attack_status = "";
    if (direction == 1 && bn_primary.attack_strength_buy > 0.6f && bn_primary.bn_attack_long_valid) {
        attack_status = "ATTAQUE_LONG!";
    } else if (direction == -1 && bn_primary.attack_strength_sell > 0.6f && bn_primary.bn_attack_short_valid) {
        attack_status = "ATTAQUE_SHORT!";
    }

    snprintf(result.reason, sizeof(result.reason),
             "BN=%.2f Sig=%d Stack=%d/%d Coh=%.1f %s %s",
             bn_primary.score,
             visual_count,
             bn_primary.stacked_buy_zones,
             bn_primary.stacked_sell_zones,
             bn_primary.directional_coherence,
             attack_status,
             result.correlation);

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9: LAYER 3 - CONTEXT
// ═══════════════════════════════════════════════════════════════════════════════

struct Layer3Result {
    bool passed;
    float confidence;
    char context[64];
    bool veto;
    char veto_reason[128];
};

Layer3Result ValidateLayer3(
    int direction,
    const BN_Data& bn,
    float current_price,
    const MenthorQ_Data& mq,
    float vix,
    float atr,
    const char* session,
    bool is_nq = false  // 🆕 Pour utiliser le bon VWAP slope
) {
    Layer3Result result = {false, 0, "", false, ""};

    float score = 0;

    // === BLOC A: Position Context ===
    // Distance VWAP
    if (mq.vwap > 0 && atr > 0) {
        float d_vwap = fabs(current_price - mq.vwap);
        float d_vwap_atr = d_vwap / atr;

        if (d_vwap_atr < 0.5f) {
            score += 0.04f;  // Proche VWAP = zone neutre, bon pour reversals
        } else if (d_vwap_atr > 2.0f) {
            score -= 0.02f;  // Trop loin = extension
        }
    }

    // === BLOC A2: VWAP SLOPE PRO ANALYSIS (AMÉLIORÉ) ===
    // Usage PRO institutionnel:
    // - |slope| > 0.03 = Tendance FORTE (trade WITH only)
    // - |slope| > 0.01 = Tendance MODÉRÉE
    // - |slope| < 0.005 = Range/Consolidation
    float vwap_slope = is_nq ? g_market_live.vwap_slope_nq : g_market_live.vwap_slope_es;

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 VETO ANTI-TENDANCE (20/01/2026) - Backtest: +24% score!
    // Ne JAMAIS trader contre une tendance VWAP forte (> 0.012)
    // ═══════════════════════════════════════════════════════════════════════════
    const float VWAP_SLOPE_VETO_THRESHOLD = 0.012f;

    if (direction == 1 && vwap_slope < -VWAP_SLOPE_VETO_THRESHOLD) {
        // VETO: Ne pas acheter quand VWAP descend fortement!
        result.veto = true;
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "VETO Anti-Trend: LONG interdit - VWAP descend (%.4f < -%.3f)",
                 vwap_slope, VWAP_SLOPE_VETO_THRESHOLD);
        return result;
    }
    if (direction == -1 && vwap_slope > VWAP_SLOPE_VETO_THRESHOLD) {
        // VETO: Ne pas vendre quand VWAP monte fortement!
        result.veto = true;
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "VETO Anti-Trend: SHORT interdit - VWAP monte (%.4f > +%.3f)",
                 vwap_slope, VWAP_SLOPE_VETO_THRESHOLD);
        return result;
    }

    if (direction == 1) {  // LONG
        if (vwap_slope > 0.03f) {
            // Tendance UP forte = EXCELLENT pour LONG
            score += 0.05f;
        } else if (vwap_slope > 0.01f) {
            // Tendance UP modérée = BON
            score += 0.03f;
        } else if (vwap_slope > -0.01f) {
            // Range/Neutre = OK
            score += 0.01f;
        } else if (vwap_slope > -0.03f) {
            // Légèrement contre-tendance = ATTENTION
            score -= 0.03f;
        } else {
            // FORT contre-tendance = RISQUÉ
            score -= 0.06f;
            // Note: On ne VETO pas ici, on laisse L2/L4 décider
        }
    } else {  // SHORT
        if (vwap_slope < -0.03f) {
            // Tendance DOWN forte = EXCELLENT pour SHORT
            score += 0.05f;
        } else if (vwap_slope < -0.01f) {
            // Tendance DOWN modérée = BON
            score += 0.03f;
        } else if (vwap_slope < 0.01f) {
            // Range/Neutre = OK
            score += 0.01f;
        } else if (vwap_slope < 0.03f) {
            // Légèrement contre-tendance = ATTENTION
            score -= 0.03f;
        } else {
            // FORT contre-tendance = RISQUÉ
            score -= 0.06f;
        }
    }

    // === BLOC A3: Momentum Context (NOUVEAU) ===
    // Utilise le momentum_score calculé dans BN_Data
    if (direction == 1 && bn.momentum_score > 0.1f) {
        score += 0.02f;  // Momentum haussier confirme LONG
    } else if (direction == -1 && bn.momentum_score < -0.1f) {
        score += 0.02f;  // Momentum baissier confirme SHORT
    } else if ((direction == 1 && bn.momentum_score < -0.2f) ||
               (direction == -1 && bn.momentum_score > 0.2f)) {
        score -= 0.02f;  // Momentum contraire = risque
    }

    // === BLOC A4: Reversal Context (NOUVEAU) ===
    // Les reversals sont des signaux forts
    if (direction == 1 && bn.reversal_score > 0.3f) {
        score += 0.04f;  // Reversal haussier fort
    } else if (direction == -1 && bn.reversal_score < -0.3f) {
        score += 0.04f;  // Reversal baissier fort
    }

    // === BLOC A5: Institutional Pressure (NOUVEAU) ===
    // Pression des gros ordres
    if (direction == 1 && bn.institutional_pressure > 0.2f) {
        score += 0.03f;  // Gros acheteurs
    } else if (direction == -1 && bn.institutional_pressure < -0.2f) {
        score += 0.03f;  // Gros vendeurs
    } else if ((direction == 1 && bn.institutional_pressure < -0.3f) ||
               (direction == -1 && bn.institutional_pressure > 0.3f)) {
        score -= 0.02f;  // Institutionnels contre nous
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 BLOC A6: POC CONFIRMATION (Point Of Control de la bougie)
    // Close > POC = acheteurs ont gagné la bougie → BULLISH
    // Close < POC = vendeurs ont gagné la bougie → BEARISH
    // ═══════════════════════════════════════════════════════════════════════
    if (direction == 1) {  // LONG
        if (bn.poc_confirm == 1) {
            score += 0.02f;  // POC BULLISH confirme LONG
        } else if (bn.poc_confirm == -1) {
            score -= 0.01f;  // POC BEARISH contre LONG (malus léger)
        }
    } else {  // SHORT
        if (bn.poc_confirm == -1) {
            score += 0.02f;  // POC BEARISH confirme SHORT
        } else if (bn.poc_confirm == 1) {
            score -= 0.01f;  // POC BULLISH contre SHORT (malus léger)
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 BLOC A7: CVD TREND CONFIRMATION (Cumulative Volume Delta)
    // CVD rising = acheteurs accumulent → BULLISH trend
    // CVD falling = vendeurs accumulent → BEARISH trend
    // Note: Les VETO sur forte divergence sont dans Layer2
    // ═══════════════════════════════════════════════════════════════════════
    const float CVD_CONFIRM_THRESHOLD = 100.0f;   // Seuil pour confirmation
    const float CVD_AGAINST_THRESHOLD = -100.0f;  // Seuil pour contre-tendance
    
    if (direction == 1) {  // LONG
        if (bn.cvd_slope > CVD_CONFIRM_THRESHOLD) {
            // CVD monte = acheteurs accumulent = EXCELLENT pour LONG
            float cvd_bonus = fmin(bn.cvd_slope / 500.0f, 0.03f);  // Max +0.03
            score += cvd_bonus;
        } else if (bn.cvd_slope < CVD_AGAINST_THRESHOLD) {
            // CVD baisse légèrement = attention (les VETO forts sont dans L2)
            float cvd_malus = fmax(bn.cvd_slope / 1000.0f, -0.02f);  // Max -0.02
            score += cvd_malus;  // (valeur négative)
        }
    } else {  // SHORT
        if (bn.cvd_slope < -CVD_CONFIRM_THRESHOLD) {
            // CVD baisse = vendeurs accumulent = EXCELLENT pour SHORT
            float cvd_bonus = fmin(-bn.cvd_slope / 500.0f, 0.03f);  // Max +0.03
            score += cvd_bonus;
        } else if (bn.cvd_slope > CVD_CONFIRM_THRESHOLD) {
            // CVD monte légèrement = attention (les VETO forts sont dans L2)
            float cvd_malus = fmax(-bn.cvd_slope / 1000.0f, -0.02f);  // Max -0.02
            score += cvd_malus;  // (valeur négative)
        }
    }

    // === BLOC B: Battle Context (Règle d'Or #1) ===
    // Utilise les forces complètes déjà calculées dans bn
    // ⚠️ COLOR_UP/DOWN = flux local, pas obstacle structurel → poids très faible (0.1x)
    // 🔧 30/01/2026: FIX - edge_buy/sell sont des PRIX, utiliser num_edge_rect_buy/sell
    float edge_weight_b = 50.0f;
    float buyer_strength = (bn.num_edge_rect_buy * edge_weight_b) + (bn.color_up * 0.1f) + bn.absorb_bid +
                          bn.rotation_up * 0.5f + bn.long_down_up * 2.0f +
                          (bn.bar_color_up * 0.1f) + bn.bar_edge_buy * 0.5f;
    float seller_strength = (bn.num_edge_rect_sell * edge_weight_b) + (bn.color_down * 0.1f) + bn.absorb_ask +
                           bn.rotation_down * 0.5f + bn.long_up_down * 2.0f +
                           (bn.bar_color_down * 0.1f) + bn.bar_edge_sell * 0.5f;
    
    // 🆕 FPBS Delta (direction instantanée) - GAME CHANGER
    if (bn.fpbs_delta > 0) {
        buyer_strength += fmin(bn.fpbs_delta / 1000.0f, 2.0f) * 0.5f;
    } else if (bn.fpbs_delta < 0) {
        seller_strength += fmin(-bn.fpbs_delta / 1000.0f, 2.0f) * 0.5f;
    }

    // Règle d'Or #1: Ratio 1.5x
    if (direction == 1) {  // LONG
        if (seller_strength > buyer_strength * 1.5f && buyer_strength > 0) {
            result.veto = true;
            snprintf(result.veto_reason, sizeof(result.veto_reason),
                     "VETO Regle Or #1: Sellers %.0f > Buyers %.0f x 1.5",
                     seller_strength, buyer_strength);
            return result;
        }
        if (buyer_strength > seller_strength * 1.2f) {
            score += 0.04f;  // Buyers dominent
        }
    } else {  // SHORT
        if (buyer_strength > seller_strength * 1.5f && seller_strength > 0) {
            result.veto = true;
            snprintf(result.veto_reason, sizeof(result.veto_reason),
                     "VETO Regle Or #1: Buyers %.0f > Sellers %.0f x 1.5",
                     buyer_strength, seller_strength);
            return result;
        }
        if (seller_strength > buyer_strength * 1.2f) {
            score += 0.04f;  // Sellers dominent
        }
    }

    // === BLOC C: Value Area Context (NOUVEAU) ===
    // Position par rapport à la Value Area (VAH/VAL)
    bool in_value_area = false;
    if (mq.vah > 0 && mq.val > 0) {
        in_value_area = (current_price >= mq.val && current_price <= mq.vah);

        if (in_value_area) {
            // Dans la VA = zone de consolidation, OK pour trades courts
            score += 0.01f;
        } else if (current_price > mq.vah) {
            // Au-dessus de VAH
            if (direction == 1) {
                score += 0.02f;  // LONG au-dessus VAH = breakout bull
            } else {
                score += 0.01f;  // SHORT au-dessus VAH = retour possible
            }
        } else if (current_price < mq.val) {
            // En-dessous de VAL
            if (direction == -1) {
                score += 0.02f;  // SHORT en-dessous VAL = breakout bear
            } else {
                score += 0.01f;  // LONG en-dessous VAL = rebond possible
            }
        }

        // Proximité des bornes VA (zones de réaction)
        float dist_vah = fabs(current_price - mq.vah);
        float dist_val = fabs(current_price - mq.val);
        if (dist_vah < atr * 0.2f || dist_val < atr * 0.2f) {
            score += 0.02f;  // Proche d'une borne = zone de réaction
        }
    }

    // === BLOC D: Timing Context ===
    // Session bonus
    if (strcmp(session, "US") == 0) {
        score += 0.03f;  // US = meilleure liquidité
    } else if (strcmp(session, "London") == 0) {
        score += 0.02f;
    } else if (strcmp(session, "Asia") == 0) {
        score += 0.01f;
    }

    // VIX context
    if (vix >= 15 && vix <= 25) {
        score += 0.02f;  // VIX normal = conditions optimales
    } else if (vix > 35) {
        score -= 0.02f;  // Trop volatile
    }

    // === EQUILIBRE: Résultat avec seuil raisonnable ===
    result.confidence = score;
    result.passed = score >= 0.10f;  // Seuil EQUILIBRE

    snprintf(result.context, sizeof(result.context),
             "%s VIX=%.1f VA=%s Buy=%.0f/Sell=%.0f Mom=%.2f",
             session, vix,
             in_value_area ? "IN" : (current_price > mq.vah ? "ABOVE" : "BELOW"),
             buyer_strength, seller_strength, bn.momentum_score);

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 10: LAYER 4 - COMBO FILTER (V54: 2 REGLES BACKTEST, 1/2 REQUIS)
// ═══════════════════════════════════════════════════════════════════════════════
// 25/01/2026: BACKTEST RIGOUREUX - 2 nouvelles règles validées, 1/2 requis
// 1. Buy/Sell % > 52% (amélioration +863% vs baseline)
// 2. Edge Dominant (amélioration +366% vs baseline, très stable)
//
// ANCIENS indicateurs gardés pour référence mais NON bloquants

struct Layer4Result {
    bool passed;
    int combo_aligned;  // 0-2 (nouvelles règles)
    bool pct_ok;        // Buy/Sell % > 52%
    bool edge_ok;       // Edge Dominant
    // Anciens (info seulement)
    bool delta_ok;
    bool bn_ok;
    bool vwap_ok;
};

Layer4Result ValidateLayer4(
    int direction,
    float buy_pct,
    float sell_pct,     // 🔧 AJOUT 25/01/2026
    float edge_buy,     // 🔧 AJOUT 25/01/2026
    float edge_sell,    // 🔧 AJOUT 25/01/2026
    float cum_delta,
    float bn_score,
    float vwap_slope,
    const SymbolConfig& config
) {
    Layer4Result result = {false, 0, false, false, false, false, false};

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 30/01/2026 SOIR: pct_ok désactivé (Layer 3 fait maintenant le filtrage)
    // Le nouveau Layer 3 utilise: smart_money + edge (NQ) ou edge + rotation (ES)
    // ═══════════════════════════════════════════════════════════════════════════
    result.pct_ok = true;  // Toujours OK, Layer 3 a déjà filtré

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 NOUVELLE REGLE 2: Edge Dominant (backtest: +366%, très stable)
    // ═══════════════════════════════════════════════════════════════════════════
    float total_edge = edge_buy + edge_sell;
    if (total_edge > 0) {
        if (direction == 1) {  // LONG
            result.edge_ok = (edge_buy > edge_sell);
        } else {  // SHORT
            result.edge_ok = (edge_sell > edge_buy);
        }
    } else {
        // Pas d'edge data = on laisse passer (neutre)
        result.edge_ok = true;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // ANCIENNES REGLES (info seulement, NON bloquantes)
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == 1) {
        result.delta_ok = cum_delta > 0;
        result.bn_ok = bn_score > 0;
        result.vwap_ok = vwap_slope > 0;
    } else {
        result.delta_ok = cum_delta < 0;
        result.bn_ok = bn_score < 0;
        result.vwap_ok = vwap_slope < 0;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // VALIDATION: 1/2 nouvelles règles requis
    // ═══════════════════════════════════════════════════════════════════════════
    result.combo_aligned = (result.pct_ok ? 1 : 0) + (result.edge_ok ? 1 : 0);
    
    // 1/2 requis (soit Buy/Sell OK, soit Edge Dominant OK)
    int required = (config.l4_combo_required > 0) ? 1 : 0;  // Si combo actif, exiger 1/2
    result.passed = (required == 0) || (result.combo_aligned >= required);

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11: CALCUL SL/TP PROTÉGÉ
// ═══════════════════════════════════════════════════════════════════════════════

struct SLTPResult {
    float sl_price;
    float tp_price;
    int sl_ticks;
    int tp_ticks;
    float rr_ratio;
    char sl_based_on[32];
    char tp_based_on[64];  // 🆕 Agrandi pour message VETO
    bool is_valid = true;  // 🆕 false si obstacle bloque R:R
};

SLTPResult CalculateProtectedSLTP(
    int direction,
    float entry_price,
    const MenthorQ_Data& mq,
    const BN_Data& bn,  // AJOUT: Extension Lines BN
    const SymbolConfig& config,
    const ExtensionLinesTracker* ext_tracker = nullptr  // 🆕 25/01/2026: Tracker persistant
) {
    SLTPResult result = {0, 0, 0, 0, 0, "", ""};
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: DÉSACTIVÉ LE TRACKER DYNAMIQUE - CAUSE DES VALEURS HORS LIMITES!
    // Le tracker retournait des SL de 8 ticks et des TP de 70 ticks sur NQ
    // Problème: les bornes min/max n'étaient pas appliquées après le tracker
    // Solution temporaire: utiliser UNIQUEMENT la logique existante (fiable)
    // TODO: Corriger le tracker pour respecter les limites min/max
    // ═══════════════════════════════════════════════════════════════════════════
    
    // DÉSACTIVÉ - ext_tracker non utilisé pour l'instant
    (void)ext_tracker;  // Éviter warning "unused parameter"
    
    /* ANCIEN CODE TRACKER - DÉSACTIVÉ 27/01/2026
    if (ext_tracker != nullptr) {
        const char* sl_reason = nullptr;
        const char* tp_reason = nullptr;
        
        float tracked_sl = CalculateSLFromTrackedExtLines(
            *ext_tracker, direction, entry_price, config.tick_size,
            config.sl_default_ticks, config.sl_min_ticks, config.sl_max_ticks,
            &sl_reason
        );
        
        float tracked_tp = CalculateTPWithTrackedObstacles(
            *ext_tracker, direction, entry_price, config.tick_size,
            config.tp_default_ticks, &tp_reason
        );
        
        // Si le tracker a trouvé un niveau (pas FIXED), l'utiliser directement
        if (sl_reason && strcmp(sl_reason, "FIXED") != 0) {
            result.sl_price = tracked_sl;
            strncpy(result.sl_based_on, sl_reason, sizeof(result.sl_based_on) - 1);
            result.sl_ticks = (int)(fabs(entry_price - tracked_sl) / config.tick_size);
            
            // TP correspondant
            result.tp_price = tracked_tp;
            strncpy(result.tp_based_on, tp_reason, sizeof(result.tp_based_on) - 1);
            result.tp_ticks = (int)(fabs(tracked_tp - entry_price) / config.tick_size);
            
            // Calculer R:R
            float risk = fabs(entry_price - result.sl_price);
            float reward = fabs(result.tp_price - entry_price);
            result.rr_ratio = (risk > 0) ? reward / risk : 0;
            result.is_valid = (result.rr_ratio >= config.min_rr_ratio);
            
            if (!result.is_valid) {
                snprintf(result.tp_based_on, sizeof(result.tp_based_on), 
                         "VETO_RR %.2f < %.2f", result.rr_ratio, config.min_rr_ratio);
            }
            
            return result;  // Retourner directement le résultat du tracker
        }
    }
    */
    
    // === LOGIQUE EXISTANTE (fallback si tracker non disponible ou FIXED) ===

    float tick_size = config.tick_size;
    float buffer = config.sl_buffer_ticks * tick_size;
    float min_sl = config.sl_min_ticks * tick_size;
    float max_sl = config.sl_max_ticks * tick_size;

    // === Chercher niveau pour SL ===
    float best_sl = 0;
    float best_distance = 999999.0f;
    const char* best_level = "FIXED";

    // Collecter TOUS les niveaux MenthorQ (COMPLET!)
    std::vector<std::pair<float, const char*>> levels;

    // GEX Levels
    for (int i = 0; i < 10; i++) {
        if (mq.gex[i] > 0) {
            levels.push_back({mq.gex[i], "GEX"});
        }
    }

    // HVL
    if (mq.hvl > 0) levels.push_back({mq.hvl, "HVL"});
    if (mq.hvl_0dte > 0) levels.push_back({mq.hvl_0dte, "HVL_0DTE"});

    // Call/Put Walls
    if (mq.put_support > 0) levels.push_back({mq.put_support, "PUT_SUP"});
    if (mq.put_support_0dte > 0) levels.push_back({mq.put_support_0dte, "PUT_0DTE"});
    if (mq.call_resistance > 0) levels.push_back({mq.call_resistance, "CALL_RES"});
    if (mq.call_resistance_0dte > 0) levels.push_back({mq.call_resistance_0dte, "CALL_0DTE"});

    // Gamma Walls (IMPORTANT!)
    if (mq.gamma_wall > 0) levels.push_back({mq.gamma_wall, "GAMMA_WALL"});
    if (mq.gamma_wall_0dte > 0) levels.push_back({mq.gamma_wall_0dte, "GAMMA_0DTE"});

    // Daily Extremes
    if (mq.day_min > 0) levels.push_back({mq.day_min, "1D_MIN"});
    if (mq.day_max > 0) levels.push_back({mq.day_max, "1D_MAX"});

    // Value Area (VAH/VAL)
    if (mq.vah > 0) levels.push_back({mq.vah, "VAH"});
    if (mq.val > 0) levels.push_back({mq.val, "VAL"});

    // VWAP et Bands
    if (mq.vwap > 0) levels.push_back({mq.vwap, "VWAP"});
    if (mq.vwap_up1 > 0) levels.push_back({mq.vwap_up1, "VWAP_UP1"});
    if (mq.vwap_dn1 > 0) levels.push_back({mq.vwap_dn1, "VWAP_DN1"});
    if (mq.vwap_up2 > 0) levels.push_back({mq.vwap_up2, "VWAP_UP2"});
    if (mq.vwap_dn2 > 0) levels.push_back({mq.vwap_dn2, "VWAP_DN2"});

    // Blind Spots
    for (int i = 0; i < 9; i++) {
        if (mq.blind_spots[i] > 0) {
            levels.push_back({mq.blind_spots[i], "BLIND"});
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // AJOUTER LES EXTENSION LINES BN (zones de réaction des gros)
    // ⚠️ NOTE: Ne PAS utiliser COLOR_UP/DOWN (boules) ici - trop nombreuses!
    // On utilise uniquement les REVERSAL bars (LONG_DOWN_UP / LONG_UP_DOWN)
    // ═══════════════════════════════════════════════════════════════════════════
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0) {
            levels.push_back({bn.ext_lines_support[i], "BN_SUPPORT"});
        }
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > 0) {
            levels.push_back({bn.ext_lines_resist[i], "BN_RESIST"});
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR) - PROTECTION ULTRA IMPORTANTE!
    // Ces rectangles sont des zones de défense institutionnelle MAJEURES
    // Le SL doit être placé DERRIÈRE ces niveaux pour une protection maximale
    // ═══════════════════════════════════════════════════════════════════════════
    for (int i = 0; i < bn.num_long_up_bar; i++) {
        if (bn.long_up_bar_ext[i] > 0) {
            levels.push_back({bn.long_up_bar_ext[i], "RECT_VERT_TRADABLE"});  // Support fort
        }
    }
    for (int i = 0; i < bn.num_long_down_bar; i++) {
        if (bn.long_down_bar_ext[i] > 0) {
            levels.push_back({bn.long_down_bar_ext[i], "RECT_ROUGE_TRADABLE"});  // Résistance forte
        }
    }
    
    // 🆕 POC (Point of Control) - Niveau secondaire si proche
    // Le POC est le prix où le plus de volume a été échangé = défense probable
    if (bn.fpbs_poc > 0) {
        levels.push_back({bn.fpbs_poc, "POC"});
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // NOUVELLE LOGIQUE: Détection de CONFLUENCE + Prendre le PLUS LOIN
    // Quand plusieurs niveaux sont proches (< 5 ticks), le SL va AU-DELÀ du plus loin
    // ═══════════════════════════════════════════════════════════════════════════
    const float CONFLUENCE_THRESHOLD = 5.0f * tick_size;  // 5 ticks

    // Collecter les niveaux valides pour SL
    std::vector<std::pair<float, const char*>> valid_sl_levels;

    for (const auto& lvl : levels) {
        float level_price = lvl.first;

        if (direction == 1) {  // LONG - SL sous support
            if (level_price >= entry_price) continue;
            float distance = entry_price - level_price;
            if (distance >= min_sl && distance <= max_sl) {
                valid_sl_levels.push_back(lvl);
            }
        } else {  // SHORT - SL au-dessus résistance
            if (level_price <= entry_price) continue;
            float distance = level_price - entry_price;
            if (distance >= min_sl && distance <= max_sl) {
                valid_sl_levels.push_back(lvl);
            }
        }
    }

    // Trouver le niveau le plus proche ET vérifier confluence
    float closest_level = 0;
    float farthest_in_confluence = 0;
    const char* farthest_name = "FIXED";

    if (!valid_sl_levels.empty()) {
        // Trier par distance au prix
        if (direction == 1) {  // LONG - trier par prix décroissant (plus proche = plus haut)
            std::sort(valid_sl_levels.begin(), valid_sl_levels.end(),
                [](const auto& a, const auto& b) { return a.first > b.first; });
        } else {  // SHORT - trier par prix croissant (plus proche = plus bas)
            std::sort(valid_sl_levels.begin(), valid_sl_levels.end(),
                [](const auto& a, const auto& b) { return a.first < b.first; });
        }

        closest_level = valid_sl_levels[0].first;
        farthest_in_confluence = closest_level;
        farthest_name = valid_sl_levels[0].second;

        // Chercher tous les niveaux dans la zone de confluence
        for (const auto& lvl : valid_sl_levels) {
            float dist_from_closest = std::abs(lvl.first - closest_level);
            if (dist_from_closest <= CONFLUENCE_THRESHOLD) {
                // Ce niveau est en confluence
                if (direction == 1 && lvl.first < farthest_in_confluence) {
                    farthest_in_confluence = lvl.first;  // LONG: plus bas = plus loin
                    farthest_name = lvl.second;
                } else if (direction == -1 && lvl.first > farthest_in_confluence) {
                    farthest_in_confluence = lvl.first;  // SHORT: plus haut = plus loin
                    farthest_name = lvl.second;
                }
            }
        }

        // SL = niveau le plus loin de la confluence + buffer
        if (direction == 1) {
            best_sl = farthest_in_confluence - buffer;
            best_distance = entry_price - best_sl;
        } else {
            best_sl = farthest_in_confluence + buffer;
            best_distance = best_sl - entry_price;
        }
        best_level = farthest_name;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // PROTECTION FINALE: Si Extension Line BN plus proche, utiliser celle-là
    // Les boules/rectangles représentent la VRAIE défense des institutionnels
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == 1 && bn.nearest_ext_support > 0) {
        // LONG: Si support BN plus haut que SL actuel → SL sous le support BN
        float bn_sl = bn.nearest_ext_support - buffer;
        float bn_distance = entry_price - bn_sl;

        if (bn_distance >= min_sl && bn_distance <= max_sl) {
            // Le support BN est plus proche → meilleur protection
            if (bn_sl > best_sl || best_sl == 0) {
                best_sl = bn_sl;
                best_level = "BN_EXT_SUPPORT";
                best_distance = bn_distance;
            }
        }
    }
    else if (direction == -1 && bn.nearest_ext_resist > 0) {
        // SHORT: Si résistance BN plus basse que SL actuel → SL au-dessus de la résistance BN
        float bn_sl = bn.nearest_ext_resist + buffer;
        float bn_distance = bn_sl - entry_price;

        if (bn_distance >= min_sl && bn_distance <= max_sl) {
            // La résistance BN est plus proche → meilleur protection
            if (bn_sl < best_sl || best_sl == 0) {
                best_sl = bn_sl;
                best_level = "BN_EXT_RESIST";
                best_distance = bn_distance;
            }
        }
    }

    // Fallback SL fixe
    if (best_sl == 0) {
        if (direction == 1) {
            best_sl = entry_price - (config.sl_default_ticks * tick_size);
        } else {
            best_sl = entry_price + (config.sl_default_ticks * tick_size);
        }
        best_level = "FIXED";
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: SÉCURITÉ FINALE - FORCER LES LIMITES MIN/MAX SL!
    // Bug découvert: SL de 8 ticks sur NQ au lieu de min 20!
    // ═══════════════════════════════════════════════════════════════════════════
    float sl_distance = fabs(entry_price - best_sl);
    
    if (sl_distance < min_sl) {
        // SL TROP SERRÉ! Forcer au minimum
        if (direction == 1) {
            best_sl = entry_price - min_sl;
        } else {
            best_sl = entry_price + min_sl;
        }
        best_level = "MIN_FORCED";
    } else if (sl_distance > max_sl) {
        // SL TROP LOIN! Forcer au maximum
        if (direction == 1) {
            best_sl = entry_price - max_sl;
        } else {
            best_sl = entry_price + max_sl;
        }
        best_level = "MAX_FORCED";
    }

    result.sl_price = best_sl;
    strncpy(result.sl_based_on, best_level, sizeof(result.sl_based_on) - 1);
    result.sl_ticks = (int)(fabs(entry_price - best_sl) / tick_size);

    // === Calculer TP ===
    float risk = fabs(entry_price - best_sl);
    float min_reward = risk * config.min_rr_ratio;
    const float MIN_OBSTACLE_DIST = 5.0f * tick_size;  // 🆕 Min 5 ticks pour avoir de la marge

    // 🆕 Chercher PREMIER obstacle (le plus proche dans direction du trade)
    float first_obstacle = 0;
    float first_obstacle_dist = 999999.0f;
    const char* obstacle_name = "";

    for (const auto& lvl : levels) {
        float level_price = lvl.first;
        float distance;

        if (direction == 1) {  // LONG - obstacle au-dessus
            if (level_price <= entry_price) continue;
            distance = level_price - entry_price;
        } else {  // SHORT - obstacle en-dessous
            if (level_price >= entry_price) continue;
            distance = entry_price - level_price;
        }

        // 🆕 Prendre le PREMIER obstacle (le plus proche), pas ceux au-delà de min_reward
        if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
            first_obstacle_dist = distance;
            first_obstacle = level_price;
            obstacle_name = lvl.second;  // Déjà const char*
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 VÉRIFIER LES GROS RECTANGLES BLEUS (Edge Zone Rects) COMME OBSTACLES
    // Ces rectangles sont des zones d'absorption/support/résistance MAJEURES
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == -1) {  // SHORT - Rectangle BUY (vert/bleu) = OBSTACLE (support)
        for (int i = 0; i < bn.num_edge_rect_buy; i++) {
            float rect_top = bn.edge_rect_buy_top[i];
            float rect_bottom = bn.edge_rect_buy_bottom[i];

            // Rectangle valide et sous l'entrée?
            if (rect_top > 0 && rect_top < entry_price) {
                float distance = entry_price - rect_top;  // Distance au TOP du rectangle

                // Si ce rectangle est plus proche que l'obstacle actuel
                if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                    first_obstacle_dist = distance;
                    first_obstacle = rect_top;  // TP doit s'arrêter AVANT le top du rectangle
                    obstacle_name = "EDGE_RECT_BUY";
                }
            }
        }
    }
    else if (direction == 1) {  // LONG - Rectangle SELL (rouge) = OBSTACLE (résistance)
        for (int i = 0; i < bn.num_edge_rect_sell; i++) {
            float rect_top = bn.edge_rect_sell_top[i];
            float rect_bottom = bn.edge_rect_sell_bottom[i];

            // Rectangle valide et au-dessus de l'entrée?
            if (rect_bottom > 0 && rect_bottom > entry_price) {
                float distance = rect_bottom - entry_price;  // Distance au BOTTOM du rectangle

                // Si ce rectangle est plus proche que l'obstacle actuel
                if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                    first_obstacle_dist = distance;
                    first_obstacle = rect_bottom;  // TP doit s'arrêter AVANT le bottom du rectangle
                    obstacle_name = "EDGE_RECT_SELL";
                }
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR) COMME OBSTACLES TP
    // Ces sont les VRAIS rectangles visibles sur le chart = OBSTACLES MAJEURS
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == 1) {  // LONG - Rectangle ROUGE (long_down_bar) = OBSTACLE résistance
        for (int i = 0; i < bn.num_long_down_bar; i++) {
            float rect_price = bn.long_down_bar_ext[i];
            
            // Rectangle valide et au-dessus de l'entrée?
            if (rect_price > 0 && rect_price > entry_price) {
                float distance = rect_price - entry_price;
                
                // Si ce rectangle est plus proche que l'obstacle actuel
                if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                    first_obstacle_dist = distance;
                    first_obstacle = rect_price;
                    obstacle_name = "RECT_ROUGE_TRADABLE";
                }
            }
        }
    }
    else if (direction == -1) {  // SHORT - Rectangle VERT (long_up_bar) = OBSTACLE support
        for (int i = 0; i < bn.num_long_up_bar; i++) {
            float rect_price = bn.long_up_bar_ext[i];
            
            // Rectangle valide et en-dessous de l'entrée?
            if (rect_price > 0 && rect_price < entry_price) {
                float distance = entry_price - rect_price;
                
                // Si ce rectangle est plus proche que l'obstacle actuel
                if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                    first_obstacle_dist = distance;
                    first_obstacle = rect_price;
                    obstacle_name = "RECT_VERT_TRADABLE";
                }
            }
        }
    }

    // 🆕 VETO si obstacle trop proche pour avoir un R:R acceptable
    if (first_obstacle > 0 && first_obstacle_dist < min_reward) {
        // Obstacle bloque le chemin - R:R insuffisant!
        result.is_valid = false;
        snprintf(result.tp_based_on, sizeof(result.tp_based_on),
                 "VETO_OBSTACLE_%s@%.2f (R:R<%.1f)", obstacle_name, first_obstacle, config.min_rr_ratio);
        result.tp_price = 0;
        return result;
    }

    // TP avant obstacle ou TP fixe
    if (first_obstacle > 0) {
        if (direction == 1) {
            result.tp_price = first_obstacle - (config.tp_buffer_ticks * tick_size);
        } else {
            result.tp_price = first_obstacle + (config.tp_buffer_ticks * tick_size);
        }
        snprintf(result.tp_based_on, sizeof(result.tp_based_on), "BEFORE_%s", obstacle_name);
    } else {
        if (direction == 1) {
            result.tp_price = entry_price + (config.tp_default_ticks * tick_size);
        } else {
            result.tp_price = entry_price - (config.tp_default_ticks * tick_size);
        }
        strcpy(result.tp_based_on, "FIXED");
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: SÉCURITÉ FINALE - FORCER LES LIMITES MIN/MAX TP!
    // Bug découvert: TP de 70 ticks sur NQ au lieu de max 50!
    // ═══════════════════════════════════════════════════════════════════════════
    float max_tp_distance = config.tp_max_ticks * tick_size;
    float min_tp_distance = config.sl_default_ticks * tick_size;  // TP minimum = SL default (R:R ~1)
    float tp_distance = fabs(result.tp_price - entry_price);
    
    if (tp_distance > max_tp_distance) {
        // TP TROP LOIN! Forcer au maximum
        if (direction == 1) {
            result.tp_price = entry_price + max_tp_distance;
        } else {
            result.tp_price = entry_price - max_tp_distance;
        }
        strcpy(result.tp_based_on, "MAX_LIMITED");
        tp_distance = max_tp_distance;
    } else if (tp_distance < min_tp_distance) {
        // TP TROP PROCHE! Forcer au minimum raisonnable
        if (direction == 1) {
            result.tp_price = entry_price + min_tp_distance;
        } else {
            result.tp_price = entry_price - min_tp_distance;
        }
        strcpy(result.tp_based_on, "MIN_LIMITED");
        tp_distance = min_tp_distance;
    }

    result.tp_ticks = (int)(tp_distance / tick_size);

    // R:R
    float reward = tp_distance;
    result.rr_ratio = (risk > 0) ? reward / risk : 0;

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 12: GESTION DES ORDRES
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// 🔧 27/01/2026: CALCUL ANCRE BN SMART MONEY - VERSION COMPLÈTE
// ═══════════════════════════════════════════════════════════════════════════════
// Cherche le MEILLEUR repère visuel Battle Navale pour entrée LIMIT
// 
// REPÈRES VISUELS INCLUS (tous types):
// - Edge Zone Rectangles (zones absorption massive) ⭐⭐⭐
// - Tradable Rectangles (long_down_up/up_down bars) ⭐⭐⭐
// - Extension Lines (color_up/down, supports/resistances) ⭐⭐
// - Nearest Extension Support/Resist ⭐⭐
// - Absorb zones, Imbalances, Clusters ⭐
//
// LOGIQUE: Trouve le repère LE PLUS PROCHE du prix actuel (en dessous pour LONG)
// ═══════════════════════════════════════════════════════════════════════════════
float CalculateBNAnchor(
    int direction,
    float current_price,
    const BN_Data& bn,
    float tick_size
) {
    // Structure pour stocker les ancres candidates avec leur importance
    struct AnchorCandidate {
        float price;
        int importance;  // 3=majeur, 2=important, 1=mineur
        const char* type;
    };
    
    std::vector<AnchorCandidate> candidates;
    
    // 🔧 30/01/2026: DISTANCES COHÉRENTES PAR SYMBOLE
    // PRINCIPE: Chercher le support/résistance le plus PROCHE et RAISONNABLE
    // Pas trop loin (le prix ne reviendra pas), pas trop proche (autant entrer market)
    bool is_nq = (tick_size == 0.25f && current_price > 10000);  // Heuristique NQ
    
    // ES: Max 20 ticks (5 pts) - pullback typique ES
    // NQ: Max 32 ticks (8 pts) - pullback typique NQ (plus volatil)
    const float MAX_ANCHOR_DISTANCE = is_nq ? 32.0f * tick_size : 20.0f * tick_size;
    const float MIN_ANCHOR_DISTANCE = 2.0f * tick_size;   // Min 2 ticks (pas trop proche)
    
    if (direction == 1) {  // LONG - chercher SUPPORTS (niveaux EN-DESSOUS du prix)
        
        // ═══════════════════════════════════════════════════════════════════
        // 1. EDGE ZONE RECTANGLES (⭐⭐⭐ MAJEUR)
        // ═══════════════════════════════════════════════════════════════════
        if (bn.nearest_edge_rect_support > 0 && bn.nearest_edge_rect_support < current_price) {
            float dist = current_price - bn.nearest_edge_rect_support;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.nearest_edge_rect_support, 3, "EDGE_RECT"});
            }
        }
        for (int i = 0; i < bn.num_edge_rect_buy && i < 5; i++) {
            float level = bn.edge_rect_buy_top[i];
            if (level > 0 && level < current_price) {
                float dist = current_price - level;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 3, "EDGE_RECT_TOP"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 2. TRADABLE RECTANGLES - LONG_DOWN_UP (⭐⭐⭐ MAJEUR - reversal bars)
        // ═══════════════════════════════════════════════════════════════════
        for (int i = 0; i < bn.num_long_up_bar && i < 10; i++) {
            float level = bn.long_up_bar_ext[i];
            if (level > 0 && level < current_price) {
                float dist = current_price - level;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 3, "RECT_VERT"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 3. EXTENSION LINES SUPPORTS (⭐⭐ IMPORTANT - color_up, boules vertes)
        // ═══════════════════════════════════════════════════════════════════
        for (int i = 0; i < bn.num_ext_support && i < 10; i++) {
            float level = bn.ext_lines_support[i];
            if (level > 0 && level < current_price) {
                float dist = current_price - level;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 2, "EXT_SUPPORT"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 4. NEAREST EXTENSION SUPPORT (⭐⭐ IMPORTANT)
        // ═══════════════════════════════════════════════════════════════════
        if (bn.nearest_ext_support > 0 && bn.nearest_ext_support < current_price) {
            float dist = current_price - bn.nearest_ext_support;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.nearest_ext_support, 2, "NEAREST_EXT"});
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 5. 🆕 POC (Point of Control) - ⭐⭐⭐ MAJEUR!
        // Le POC = prix où le plus de volume a été échangé = support naturel
        // ═══════════════════════════════════════════════════════════════════
        if (bn.fpbs_poc > 0 && bn.fpbs_poc < current_price) {
            float dist = current_price - bn.fpbs_poc;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.fpbs_poc, 3, "POC"});  // Haute priorité!
            }
        }
        
    } else {  // SHORT - chercher RÉSISTANCES (niveaux AU-DESSUS du prix)
        
        // ═══════════════════════════════════════════════════════════════════
        // 1. EDGE ZONE RECTANGLES (⭐⭐⭐ MAJEUR)
        // ═══════════════════════════════════════════════════════════════════
        if (bn.nearest_edge_rect_resist > 0 && bn.nearest_edge_rect_resist > current_price) {
            float dist = bn.nearest_edge_rect_resist - current_price;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.nearest_edge_rect_resist, 3, "EDGE_RECT"});
            }
        }
        for (int i = 0; i < bn.num_edge_rect_sell && i < 5; i++) {
            float level = bn.edge_rect_sell_bottom[i];
            if (level > 0 && level > current_price) {
                float dist = level - current_price;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 3, "EDGE_RECT_BOT"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 2. TRADABLE RECTANGLES - LONG_UP_DOWN (⭐⭐⭐ MAJEUR - reversal bars)
        // ═══════════════════════════════════════════════════════════════════
        for (int i = 0; i < bn.num_long_down_bar && i < 10; i++) {
            float level = bn.long_down_bar_ext[i];
            if (level > 0 && level > current_price) {
                float dist = level - current_price;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 3, "RECT_ROUGE"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 3. EXTENSION LINES RESISTANCES (⭐⭐ IMPORTANT - color_down, boules rouges)
        // ═══════════════════════════════════════════════════════════════════
        for (int i = 0; i < bn.num_ext_resist && i < 10; i++) {
            float level = bn.ext_lines_resist[i];
            if (level > 0 && level > current_price) {
                float dist = level - current_price;
                if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                    candidates.push_back({level, 2, "EXT_RESIST"});
                }
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 4. NEAREST EXTENSION RESIST (⭐⭐ IMPORTANT)
        // ═══════════════════════════════════════════════════════════════════
        if (bn.nearest_ext_resist > 0 && bn.nearest_ext_resist > current_price) {
            float dist = bn.nearest_ext_resist - current_price;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.nearest_ext_resist, 2, "NEAREST_EXT"});
            }
        }
        
        // ═══════════════════════════════════════════════════════════════════
        // 5. 🆕 POC (Point of Control) - ⭐⭐⭐ MAJEUR!
        // Le POC = prix où le plus de volume a été échangé = résistance naturelle
        // ═══════════════════════════════════════════════════════════════════
        if (bn.fpbs_poc > 0 && bn.fpbs_poc > current_price) {
            float dist = bn.fpbs_poc - current_price;
            if (dist >= MIN_ANCHOR_DISTANCE && dist <= MAX_ANCHOR_DISTANCE) {
                candidates.push_back({bn.fpbs_poc, 3, "POC"});  // Haute priorité!
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 30/01/2026: SÉLECTION COHÉRENTE - PRIORITÉ = PROXIMITÉ!
    // Le support/résistance le plus PROCHE est le plus pertinent
    // L'importance sert de "bonus" pour départager des niveaux à distance égale
    // ═══════════════════════════════════════════════════════════════════════════
    if (candidates.empty()) {
        return 0;  // Pas d'ancre trouvée
    }
    
    // Trier par DISTANCE D'ABORD (le plus proche gagne!)
    // Importance = tiebreaker seulement si distances très proches (< 3 ticks)
    std::sort(candidates.begin(), candidates.end(), 
        [current_price, direction, tick_size](const AnchorCandidate& a, const AnchorCandidate& b) {
            float dist_a = direction == 1 ? (current_price - a.price) : (a.price - current_price);
            float dist_b = direction == 1 ? (current_price - b.price) : (b.price - current_price);
            
            // Si distances très proches (< 3 ticks de différence), utiliser importance
            float diff = fabs(dist_a - dist_b);
            if (diff < 3.0f * tick_size) {
                return a.importance > b.importance;  // Même zone → prendre le plus important
            }
            
            // Sinon, le plus PROCHE gagne!
            return dist_a < dist_b;
        });
    
    // Retourner l'ancre la PLUS PROCHE
    return candidates[0].price;
}

bool SendBracketOrder(
    SCStudyInterfaceRef sc,
    int direction,
    float entry_price,
    float sl_price,
    float tp_price,
    BotState& state,
    float bn_anchor = 0  // 🆕 Ancre BN (0 = utiliser entry_price)
) {
    s_SCNewOrder order;
    order.Reset();

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: LOGIQUE ENTRÉE SMART MONEY
    // PRINCIPE: Signal OK → Placer LIMIT près du repère visuel et ATTENDRE!
    // On ne chase pas le prix, on le laisse venir à nous
    // ═══════════════════════════════════════════════════════════════════════════
    float final_entry_price = entry_price;
    bool use_market = false;
    
    // 🔧 30/01/2026: PARAMÈTRES COHÉRENTS PAR SYMBOLE (Smart Money Entry)
    // PRINCIPE: Distances RAISONNABLES pour un pullback réaliste
    bool is_nq = (sc.TickSize == 0.25f && entry_price > 10000);  // Heuristique NQ
    
    const float ENTRY_BUFFER_TICKS = 2.0f;  // Buffer fixe 2 ticks (juste au-dessus du niveau)
    
    // ES: Max 15 ticks (3.75 pts) pour placer LIMIT - pullback raisonnable
    // NQ: Max 25 ticks (6.25 pts) pour placer LIMIT - pullback raisonnable NQ
    const float MAX_DIST_FOR_LIMIT = is_nq ? 25.0f : 15.0f;
    
    // Si déjà très proche de l'ancre → MARKET immédiat
    const float IMMEDIATE_DIST = is_nq ? 4.0f : 3.0f;  // NQ: ≤4 ticks, ES: ≤3 ticks

    if (bn_anchor > 0) {
        float tick_size = sc.TickSize;
        float dist_ticks = fabs(entry_price - bn_anchor) / tick_size;

        if (dist_ticks <= IMMEDIATE_DIST) {
            // ═══════════════════════════════════════════════════════════════
            // CAS 1: Prix DÉJÀ à l'ancre (≤3 ticks) → MARKET immédiat
            // Le prix est sur le support/resistance, on entre tout de suite!
            // ═══════════════════════════════════════════════════════════════
            use_market = true;
            final_entry_price = entry_price;
            
        } else if (dist_ticks <= MAX_DIST_FOR_LIMIT) {
            // ═══════════════════════════════════════════════════════════════
            // CAS 2: Prix LOIN de l'ancre → LIMIT sur l'ancre + buffer
            // On place un ordre LIMIT et on ATTEND que le prix revienne!
            // C'est la logique SMART MONEY: ne pas chaser, laisser venir.
            // ═══════════════════════════════════════════════════════════════
            if (direction == 1) {  // LONG - ancre = support
                // Placer LIMIT légèrement AU-DESSUS du support pour être exécuté
                final_entry_price = bn_anchor + (ENTRY_BUFFER_TICKS * tick_size);
            } else {  // SHORT - ancre = résistance
                // Placer LIMIT légèrement EN-DESSOUS de la résistance
                final_entry_price = bn_anchor - (ENTRY_BUFFER_TICKS * tick_size);
            }
            use_market = false;
            
        } else {
            // ═══════════════════════════════════════════════════════════════
            // CAS 3: Prix BEAUCOUP trop loin (>20 ticks) → SKIP
            // L'ancre est trop éloignée, le signal n'est pas actionnable
            // ═══════════════════════════════════════════════════════════════
            snprintf(state.status_message, sizeof(state.status_message),
                     "SKIP: Ancre trop loin (%.0ft > %0.ft) - Attendre meilleur setup",
                     dist_ticks, MAX_DIST_FOR_LIMIT);
            return false;
        }
    } else {
        // Pas d'ancre trouvée → MARKET au prix courant (fallback)
        use_market = true;
        final_entry_price = entry_price;
    }

    // === PARENT ORDER: LIMIT ou MARKET selon distance ===
    order.OrderType = use_market ? SCT_ORDERTYPE_MARKET : SCT_ORDERTYPE_LIMIT;
    order.OrderQuantity = 1;
    order.Price1 = final_entry_price;
    order.TimeInForce = SCT_TIF_GTC;

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: FIX ORDRE ORPHELIN - Utiliser SEULEMENT les OFFSETS!
    // PROBLÈME: Sierra Chart confus si on définit OFFSET + PRICE ensemble
    // SOLUTION: Utiliser UNIQUEMENT les offsets (en ticks) pour les attached orders
    // Sierra Chart calcule automatiquement les prix à partir des offsets
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Calculer offsets en ticks depuis le prix d'entrée
    float tick_size = sc.TickSize;
    double sl_offset_ticks = fabs(final_entry_price - sl_price) / tick_size;
    double tp_offset_ticks = fabs(tp_price - final_entry_price) / tick_size;
    
    // 🔧 28/01/2026: FORCER LES LIMITES MAX ICI AUSSI!
    // Bug: Si final_entry_price != entry_price (Smart Money adjust), 
    // les offsets peuvent dépasser les limites!
    const SymbolConfig& cfg = (strcmp(sc.GetChartSymbol(sc.ChartNumber), "ES") != 0) ? CONFIG_ES : CONFIG_NQ;
    
    if (sl_offset_ticks > cfg.sl_max_ticks) {
        sl_offset_ticks = cfg.sl_max_ticks;
    }
    if (sl_offset_ticks < cfg.sl_min_ticks) {
        sl_offset_ticks = cfg.sl_min_ticks;
    }
    if (tp_offset_ticks > cfg.tp_max_ticks) {
        tp_offset_ticks = cfg.tp_max_ticks;
    }
    
    // Minimum offset de sécurité (au cas où calcul donne 0)
    if (sl_offset_ticks < 4) sl_offset_ticks = 4;  // Min 4 ticks SL
    if (tp_offset_ticks < 4) tp_offset_ticks = 4;  // Min 4 ticks TP
    
    // SL: STOP MARKET - OFFSET UNIQUEMENT
    order.Stop1Offset = sl_offset_ticks;
    // order.Stop1Price = sl_price;  // ❌ NE PAS UTILISER - cause ordres orphelins!
    
    // TP: LIMIT - OFFSET UNIQUEMENT
    order.Target1Offset = tp_offset_ticks;
    // order.Target1Price = tp_price;  // ❌ NE PAS UTILISER - cause ordres orphelins!

    // Types des attached orders (OCO)
    order.AttachedOrderTarget1Type = SCT_ORDERTYPE_LIMIT;
    order.AttachedOrderStop1Type = SCT_ORDERTYPE_STOP;
    
    // 🆕 Force les attached orders à être créés
    order.MoveToBreakEven.Type = MOVETO_BE_ACTION_TYPE_NONE;  // Pas de BE automatique

    // Envoyer l'ordre selon la direction
    int result;
    if (direction == 1) {
        result = sc.BuyEntry(order);
    } else {
        result = sc.SellEntry(order);
    }

    if (result > 0) {
        state.parent_order_id = result;
        state.order_sent_time = sc.CurrentSystemDateTime;
        // 🔧 27/01/2026: Stocker le prix d'entrée RÉEL (LIMIT price, pas current price)
        state.entry_price = final_entry_price;  // Prix où l'ordre sera exécuté
        state.sl_price = sl_price;
        state.tp_price = tp_price;
        state.position_direction = direction;

        // 🔧 27/01/2026: Message clair pour Smart Money Entry
        if (use_market) {
            snprintf(state.status_message, sizeof(state.status_message),
                     "🎯 %s MARKET @ %.2f (SUR l'ancre %.2f) SL=%.2f TP=%.2f",
                     direction == 1 ? "LONG" : "SHORT",
                     final_entry_price, bn_anchor > 0 ? bn_anchor : entry_price,
                     sl_price, tp_price);
        } else {
            snprintf(state.status_message, sizeof(state.status_message),
                     "⏳ %s LIMIT @ %.2f (ancre=%.2f, attente pullback) SL=%.2f TP=%.2f",
                     direction == 1 ? "LONG" : "SHORT",
                     final_entry_price, bn_anchor > 0 ? bn_anchor : entry_price,
                     sl_price, tp_price);
        }

        state.pending_limit_order = !use_market;  // 🆕 Seulement si LIMIT
        if (use_market) {
            strcpy(state.waiting_for, "Fill MARKET (immediat)");
        } else {
            snprintf(state.waiting_for, sizeof(state.waiting_for),
                     "Fill ordre LIMIT (timeout %ds)", LIMIT_ORDER_TIMEOUT_SECONDS);
        }

        // 🆕 27/01/2026: LOG DEBUG pour vérifier les offsets SL/TP
        sc.AddMessageToLog(sc.GraphName, 0);
        char log_msg[256];
        snprintf(log_msg, sizeof(log_msg), 
                 "BRACKET SENT: ID=%d %s @ %.2f | SL_offset=%.0ft (%.2f) | TP_offset=%.0ft (%.2f)",
                 result, direction == 1 ? "LONG" : "SHORT", final_entry_price,
                 sl_offset_ticks, sl_price, tp_offset_ticks, tp_price);
        sc.AddMessageToLog(log_msg, 0);

        return true;
    }

    snprintf(state.status_message, sizeof(state.status_message),
             "ERREUR envoi ordre: code %d", result);

    return false;
}

// ═══════════════════════════════════════════════════════════════════════════════
// GESTION FERMETURE DE POSITION - VERSION CORRIGÉE ET ROBUSTE
// ═══════════════════════════════════════════════════════════════════════════════
// Cette fonction vérifie si une position a été fermée et met à jour les stats
// IMPORTANT: GetTradePosition() retourne SEULEMENT la position du chart actuel
// Donc on ne peut vérifier la fermeture que si le bot est sur le bon chart
// ═══════════════════════════════════════════════════════════════════════════════
void ProcessPositionClosed(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config) {
    if (!state.in_position) return;

    // Récupérer position du chart actuel
    s_SCPositionData posData;
    sc.GetTradePosition(posData);

    // Si position encore ouverte, rien à faire
    if (posData.PositionQuantity != 0) return;

    // ═══════════════════════════════════════════════════════════════════════════
    // POSITION FERMÉE - Calculer P&L et mettre à jour les stats
    // ═══════════════════════════════════════════════════════════════════════════
    int dir_closed = state.position_direction;
    float entry_closed = state.entry_price;
    float exit_closed = 0.0f;
    float pnl = 0.0f;

    // PRIORITÉ 1: Utiliser LastTradeProfitLoss si disponible
    float pnl_from_api = posData.LastTradeProfitLoss;

    if (fabs(pnl_from_api) > 0.01f) {
        pnl = pnl_from_api;
        // Calculer exit_price depuis P&L (formule corrigée)
        float ticks_moved = pnl / config.tick_value;
        if (dir_closed == 1) {  // LONG
            exit_closed = entry_closed + (ticks_moved * config.tick_size);
        } else {  // SHORT
            exit_closed = entry_closed - (ticks_moved * config.tick_size);
        }
    } else {
        // PRIORITÉ 2: Déduire depuis TP/SL stocké
        float current_price = sc.Close[sc.ArraySize - 1];
        float dist_to_tp = fabs(current_price - state.tp_price) / config.tick_size;
        float dist_to_sl = fabs(current_price - state.sl_price) / config.tick_size;

        if (dist_to_tp < dist_to_sl && dist_to_tp < 3.0f) {
            exit_closed = state.tp_price;
        } else if (dist_to_sl < 3.0f) {
            exit_closed = state.sl_price;
        } else {
            exit_closed = current_price;
        }

        // Calculer P&L (formule corrigée: ticks * tick_value)
        float ticks = (exit_closed - entry_closed) / config.tick_size;
        if (dir_closed == -1) ticks = -ticks;  // SHORT: inversion
        pnl = ticks * config.tick_value;

        sc.AddMessageToLog("⚠️ P&L calculé depuis TP/SL (API=0)", 0);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // RESET STATE
    // ═══════════════════════════════════════════════════════════════════════════
    state.in_position = false;
    state.position_direction = 0;
    state.trailing_activated = false;
    state.break_even_activated = false;
    state.parent_order_id = 0;

    // ═══════════════════════════════════════════════════════════════════════════
    // LOG DEBUG
    // ═══════════════════════════════════════════════════════════════════════════
    char pnl_debug[256];
    snprintf(pnl_debug, sizeof(pnl_debug),
             "🔍 %s CLOSED: API_PnL=%.2f, Calc_PnL=%.2f, Entry=%.2f, Exit=%.2f, Dir=%s",
             config.name, pnl_from_api, pnl, entry_closed, exit_closed,
             dir_closed == 1 ? "LONG" : "SHORT");
    sc.AddMessageToLog(pnl_debug, 0);

    // ═══════════════════════════════════════════════════════════════════════════
    // MISE À JOUR STATS
    // ═══════════════════════════════════════════════════════════════════════════
    state.pnl_today += pnl;

    if (pnl >= 0) {
        state.wins_today++;
        state.consecutive_losses = 0;
        state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_win_min);
    } else {
        state.losses_today++;
        state.consecutive_losses++;
        state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_loss_min);
    }

    snprintf(pnl_debug, sizeof(pnl_debug),
             "💰 %s P&L: $%.2f | Total: $%.2f | W:%d L:%d",
             config.name, pnl, state.pnl_today, state.wins_today, state.losses_today);
    sc.AddMessageToLog(pnl_debug, 0);

    // ═══════════════════════════════════════════════════════════════════════════
    // LOG FICHIER
    // ═══════════════════════════════════════════════════════════════════════════
    int y, mo, d, h, mi, s;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(y, mo, d, h, mi, s);
    const char* folder = (pnl >= 0) ? "TRADES_WIN" : "TRADES_LOSS";
    char fn[256];
    snprintf(fn, sizeof(fn), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\%s\\%s_%04d%02d%02d.log",
             folder, config.name, y, mo, d);

    std::ofstream f(fn, std::ios::app);
    if (f.is_open()) {
        f << std::setfill('0') << std::setw(2) << h << ":" << std::setw(2) << mi << ":" << std::setw(2) << s << "|"
          << config.name << "|" << (dir_closed == 1 ? "LONG" : "SHORT") << "|"
          << std::fixed << std::setprecision(2) << entry_closed << "|" << exit_closed << "|"
          << (pnl >= 0 ? "+" : "") << pnl << "|" << (pnl >= 0 ? "WIN" : "LOSS") << "\n";
        f.close();
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // NOTIFICATION DISCORD
    // ═══════════════════════════════════════════════════════════════════════════
    TradeSnapshot snap_closed = {0};
    strncpy(snap_closed.symbol, config.name, sizeof(snap_closed.symbol) - 1);
    snap_closed.direction = dir_closed;
    snap_closed.entry_price = entry_closed;
    snap_closed.exit_price = exit_closed;
    snap_closed.pnl = pnl;
    strncpy(snap_closed.exit_reason, (pnl >= 0 ? "TP" : "SL"), sizeof(snap_closed.exit_reason) - 1);
    snap_closed.entry_time = state.order_sent_time;
    snap_closed.exit_time = sc.CurrentSystemDateTime;
    NotifyDiscordTradeClosed(sc, snap_closed, config);

    snprintf(state.status_message, sizeof(state.status_message),
             "Position fermée: %s $%.2f | Cooldown %d min",
             pnl >= 0 ? "WIN" : "LOSS", pnl,
             pnl >= 0 ? config.cooldown_win_min : config.cooldown_loss_min);
}

void CheckOrderTimeout(SCStudyInterfaceRef sc, BotState& state) {
    if (state.parent_order_id == 0) return;
    if (state.in_position) return;
    if (!state.pending_limit_order) return;  // Seulement si ordre LIMIT en attente

    // 🔧 30/01/2026: FIX RACE CONDITION - Vérifier VRAIMENT s'il y a une position!
    // state.in_position peut être en retard par rapport à la réalité Sierra Chart!
    s_SCPositionData posData;
    sc.GetTradePosition(posData);
    
    if (posData.PositionQuantity != 0) {
        // Position EXISTE! L'ordre a été exécuté, ne PAS annuler!
        // Mettre à jour l'état immédiatement
        state.in_position = true;
        state.pending_limit_order = false;
        state.entry_price = posData.AveragePrice;
        state.position_direction = (posData.PositionQuantity > 0) ? 1 : -1;
        snprintf(state.status_message, sizeof(state.status_message),
                 "FILLED! %s @ %.2f (detecte par timeout check)",
                 state.position_direction == 1 ? "LONG" : "SHORT", state.entry_price);
        sc.AddMessageToLog(state.status_message, 0);
        return;  // NE PAS ANNULER!
    }

    // Calculer temps écoulé
    double elapsed_sec = (sc.CurrentSystemDateTime - state.order_sent_time).GetAsDouble() * 86400.0;

    if (elapsed_sec > LIMIT_ORDER_TIMEOUT_SECONDS) {  // 30 secondes
        // 🔧 30/01/2026: Annuler SEULEMENT le parent order, pas tout!
        // Les ordres attachés seront automatiquement annulés par Sierra Chart
        s_SCNewOrder cancelOrder;
        cancelOrder.Reset();
        sc.CancelOrder(state.parent_order_id);

        snprintf(state.status_message, sizeof(state.status_message),
                 "Ordre LIMIT CANCEL (timeout %ds - marche evolue)", LIMIT_ORDER_TIMEOUT_SECONDS);
        sc.AddMessageToLog(state.status_message, 0);

        // Reset les IDs d'ordres
        state.parent_order_id = 0;
        state.sl_order_id = 0;
        state.tp_order_id = 0;
        state.pending_limit_order = false;
        strcpy(state.waiting_for, "Nouveau signal");
    }
}

// 🆕 Vérifie si l'ordre LIMIT a été exécuté (position ouverte)
void CheckOrderFilled(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config) {
    if (!state.pending_limit_order) return;
    if (state.parent_order_id == 0) return;

    // Vérifier si on a une position maintenant
    s_SCPositionData posData;
    sc.GetTradePosition(posData);

    if (posData.PositionQuantity != 0) {
        // Position ouverte! L'ordre a été exécuté
        state.in_position = true;
        state.pending_limit_order = false;
        state.entry_price = posData.AveragePrice;

        if (posData.PositionQuantity > 0) {
            state.position_direction = 1;  // LONG
        } else {
            state.position_direction = -1; // SHORT
        }

        snprintf(state.status_message, sizeof(state.status_message),
                 "FILLED! %s @ %.2f",
                 state.position_direction == 1 ? "LONG" : "SHORT",
                 state.entry_price);

        strcpy(state.waiting_for, "Gestion position (SL/TP)");

        // Stats
        state.trades_today++;

        // 🆕 NOTIFICATION DISCORD - Trade ouvert
        TradeSnapshot snap_opened = {0};
        snap_opened.symbol[0] = '\0';
        strncpy(snap_opened.symbol, config.name, sizeof(snap_opened.symbol) - 1);
        snap_opened.direction = state.position_direction;
        snap_opened.entry_price = state.entry_price;
        snap_opened.sl_price = state.sl_price;
        snap_opened.tp_price = state.tp_price;
        snap_opened.l1_confidence = state.discord_l1_conf;
        snap_opened.l2_confidence = state.discord_l2_conf;
        snap_opened.l3_confidence = state.discord_l3_conf;
        snap_opened.l4_combo_aligned = state.discord_l4_combo;
        snap_opened.is_rectangle_trade = state.discord_is_rectangle;
        snap_opened.entry_time = sc.CurrentSystemDateTime;
        NotifyDiscordTradeOpened(sc, snap_opened, config, state.discord_bn_score, state.discord_vwap_slope);

        sc.AddMessageToLog(state.status_message, 0);
    }
}

// 🔧 26/01/2026: HELPER pour logger les trades fermés par Trailing/Break-Even
void LogTrailingClose(SCStudyInterfaceRef sc, const SymbolConfig& config, 
                      int direction, float entry_price, float exit_price, 
                      float pnl, const char* exit_reason) {
    int y, mo, d, h, mi, s;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(y, mo, d, h, mi, s);
    
    const char* folder = (pnl >= 0) ? "TRADES_WIN" : "TRADES_LOSS";
    char fn[256];
    snprintf(fn, sizeof(fn), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\%s\\%s_%04d%02d%02d.log",
             folder, config.name, y, mo, d);
    
    std::ofstream f(fn, std::ios::app);
    if (f.is_open()) {
        f << std::setfill('0') << std::setw(2) << h << ":" << std::setw(2) << mi << ":" << std::setw(2) << s << "|"
          << config.name << "|" << (direction == 1 ? "LONG" : "SHORT") << "|"
          << std::fixed << std::setprecision(2) << entry_price << "|" << exit_price << "|"
          << (pnl >= 0 ? "+" : "") << pnl << "|" << exit_reason << "\n";
        f.close();
    }
}

// 🔧 27/01/2026: CORRIGÉ - Ajouter current_price en paramètre pour éviter de lire
// le mauvais prix (sc.Close = prix du chart actuel, pas forcément le bon symbole!)
void UpdateTrailingStop(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config, float current_price) {
    if (!state.in_position) return;
    if (current_price <= 0) return;  // Protection contre prix invalide
    float tick_size = config.tick_size;
    float activation_dist = config.trailing_activation_ticks * tick_size;
    float trailing_dist = config.trailing_distance_ticks * tick_size;
    float be_activation_dist = config.break_even_activation_ticks * tick_size;
    float be_buffer = config.break_even_buffer_ticks * tick_size;

    float profit;
    if (state.position_direction == 1) {  // LONG
        profit = current_price - state.entry_price;
    } else {
        profit = state.entry_price - current_price;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // PHASE 1: BREAK-EVEN AUTO (active avant trailing)
    // Des que le profit atteint le seuil, SL = Entry + buffer (0 risque)
    // ═══════════════════════════════════════════════════════════════════════════
    if (profit >= be_activation_dist && !state.break_even_activated && !state.trailing_activated) {
        state.break_even_activated = true;

        // SL = Entry + petit buffer pour couvrir les fees
        if (state.position_direction == 1) {  // LONG
            state.trailing_sl = state.entry_price + be_buffer;
        } else {  // SHORT
            state.trailing_sl = state.entry_price - be_buffer;
        }

        snprintf(state.status_message, sizeof(state.status_message),
                 "BREAK-EVEN ACTIVE @ +%.0ft, SL=%.2f (0 RISQUE)",
                 profit / tick_size, state.trailing_sl);
        sc.AddMessageToLog(state.status_message, 0);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // PHASE 2: TRAILING STOP (active apres break-even)
    // Quand profit > seuil trailing, le SL commence a suivre le prix
    // ═══════════════════════════════════════════════════════════════════════════
    if (profit >= activation_dist && !state.trailing_activated) {
        state.trailing_activated = true;

        if (state.position_direction == 1) {
            state.trailing_sl = current_price - trailing_dist;
        } else {
            state.trailing_sl = current_price + trailing_dist;
        }

        snprintf(state.status_message, sizeof(state.status_message),
                 "TRAILING ACTIVE @ +%.0ft, SL=%.2f",
                 profit / tick_size, state.trailing_sl);
        sc.AddMessageToLog(state.status_message, 0);
    }

    // Mettre à jour trailing SL (suivre le prix)
    if (state.trailing_activated) {
        float new_sl;
        bool sl_updated = false;

        if (state.position_direction == 1) {  // LONG
            new_sl = current_price - trailing_dist;
            if (new_sl > state.trailing_sl) {
                state.trailing_sl = new_sl;
                sl_updated = true;
            }
            // 🔴 FERMER SI PRIX <= TRAILING SL
            if (current_price <= state.trailing_sl) {
                // 🔧 26/01/2026: CALCUL P&L + STATS + COOLDOWN
                float exit_price = state.trailing_sl;  // Sortie au trailing SL
                float pnl_ticks = (exit_price - state.entry_price) / tick_size;
                float pnl_dollars = pnl_ticks * config.tick_value;
                
                // MISE À JOUR STATS
                state.trades_today++;
                if (pnl_dollars >= 0) {
                    state.wins_today++;
                    if (pnl_dollars > state.best_trade) state.best_trade = pnl_dollars;
                } else {
                    state.losses_today++;
                    if (pnl_dollars < state.worst_trade) state.worst_trade = pnl_dollars;
                    state.consecutive_losses++;
                }
                state.pnl_today += pnl_dollars;
                
                // 🔧 COOLDOWN APRÈS FERMETURE (10 min WIN, 15 min LOSS)
                if (pnl_dollars >= 0) {
                    state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_win_min);
                    state.consecutive_losses = 0;
                } else {
                    state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_loss_min);
                }
                
                // 🔧 LOG FICHIER
                LogTrailingClose(sc, config, 1, state.entry_price, exit_price, pnl_dollars, "TRAILING");
                
                snprintf(state.status_message, sizeof(state.status_message),
                         "🛑 TRAILING SL HIT LONG @ %.2f (entry=%.2f, P&L=$%.2f, +%.0ft) COOLDOWN %dmin",
                         exit_price, state.entry_price, pnl_dollars, pnl_ticks, 
                         pnl_dollars >= 0 ? config.cooldown_win_min : config.cooldown_loss_min);
                sc.AddMessageToLog(state.status_message, 0);
                sc.FlattenAndCancelAllOrders();
                state.in_position = false;
                state.trailing_activated = false;
                state.break_even_activated = false;
                state.parent_order_id = 0;
                return;
            }
        } else {  // SHORT
            new_sl = current_price + trailing_dist;
            if (new_sl < state.trailing_sl) {
                state.trailing_sl = new_sl;
                sl_updated = true;
            }
            // FERMER SI PRIX >= TRAILING SL (SHORT)
            if (current_price >= state.trailing_sl) {
                // 🔧 26/01/2026: CALCUL P&L + STATS + COOLDOWN (SHORT)
                float exit_price = state.trailing_sl;
                float pnl_ticks = (state.entry_price - exit_price) / tick_size;
                float pnl_dollars = pnl_ticks * config.tick_value;
                
                // MISE À JOUR STATS
                state.trades_today++;
                if (pnl_dollars >= 0) {
                    state.wins_today++;
                    if (pnl_dollars > state.best_trade) state.best_trade = pnl_dollars;
                } else {
                    state.losses_today++;
                    if (pnl_dollars < state.worst_trade) state.worst_trade = pnl_dollars;
                    state.consecutive_losses++;
                }
                state.pnl_today += pnl_dollars;
                
                // 🔧 COOLDOWN APRÈS FERMETURE (10 min WIN, 15 min LOSS)
                if (pnl_dollars >= 0) {
                    state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_win_min);
                    state.consecutive_losses = 0;
                } else {
                    state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_loss_min);
                }
                
                // 🔧 LOG FICHIER
                LogTrailingClose(sc, config, -1, state.entry_price, exit_price, pnl_dollars, "TRAILING");
                
                snprintf(state.status_message, sizeof(state.status_message),
                         "🛑 TRAILING SL HIT SHORT @ %.2f (entry=%.2f, P&L=$%.2f, %.0ft) COOLDOWN %dmin",
                         exit_price, state.entry_price, pnl_dollars, pnl_ticks,
                         pnl_dollars >= 0 ? config.cooldown_win_min : config.cooldown_loss_min);
                sc.AddMessageToLog(state.status_message, 0);
                sc.FlattenAndCancelAllOrders();
                state.in_position = false;
                state.trailing_activated = false;
                state.break_even_activated = false;
                state.parent_order_id = 0;
                return;
            }
        }

        // Log mise a jour du trailing
        if (sl_updated) {
            snprintf(state.status_message, sizeof(state.status_message),
                     "TRAILING SL updated: %.2f (profit +%.0ft)",
                     state.trailing_sl, profit / tick_size);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // VERIFIER BREAK-EVEN SL HIT (quand BE active mais pas encore trailing)
    // ═══════════════════════════════════════════════════════════════════════════
    if (state.break_even_activated && !state.trailing_activated) {
        if (state.position_direction == 1) {  // LONG
            if (current_price <= state.trailing_sl) {
                // 🔧 26/01/2026: CALCUL P&L + STATS + COOLDOWN (BREAK-EVEN LONG)
                float exit_price = state.trailing_sl;
                float pnl_ticks = (exit_price - state.entry_price) / tick_size;
                float pnl_dollars = pnl_ticks * config.tick_value;
                
                // MISE À JOUR STATS (généralement ~0 ou petit profit)
                state.trades_today++;
                if (pnl_dollars >= 0) {
                    state.wins_today++;
                } else {
                    state.losses_today++;
                    state.consecutive_losses++;
                }
                state.pnl_today += pnl_dollars;
                
                // 🔧 COOLDOWN APRÈS FERMETURE (10 min - c'est un quasi-win)
                state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_win_min);
                state.consecutive_losses = 0;  // Break-even = pas une vraie loss
                
                // 🔧 LOG FICHIER
                LogTrailingClose(sc, config, 1, state.entry_price, exit_price, pnl_dollars, "BREAK-EVEN");
                
                snprintf(state.status_message, sizeof(state.status_message),
                         "🟡 BREAK-EVEN HIT LONG @ %.2f (entry=%.2f, P&L=$%.2f) COOLDOWN %dmin",
                         exit_price, state.entry_price, pnl_dollars, config.cooldown_win_min);
                sc.AddMessageToLog(state.status_message, 0);
                sc.FlattenAndCancelAllOrders();
                state.in_position = false;
                state.break_even_activated = false;
                state.parent_order_id = 0;
                return;
            }
        } else {  // SHORT
            if (current_price >= state.trailing_sl) {
                // 🔧 26/01/2026: CALCUL P&L + STATS + COOLDOWN (BREAK-EVEN SHORT)
                float exit_price = state.trailing_sl;
                float pnl_ticks = (state.entry_price - exit_price) / tick_size;
                float pnl_dollars = pnl_ticks * config.tick_value;
                
                // MISE À JOUR STATS
                state.trades_today++;
                if (pnl_dollars >= 0) {
                    state.wins_today++;
                } else {
                    state.losses_today++;
                    state.consecutive_losses++;
                }
                state.pnl_today += pnl_dollars;
                
                // 🔧 COOLDOWN APRÈS FERMETURE (10 min - c'est un quasi-win)
                state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_win_min);
                state.consecutive_losses = 0;  // Break-even = pas une vraie loss
                
                // 🔧 LOG FICHIER
                LogTrailingClose(sc, config, -1, state.entry_price, exit_price, pnl_dollars, "BREAK-EVEN");
                
                snprintf(state.status_message, sizeof(state.status_message),
                         "🟡 BREAK-EVEN HIT SHORT @ %.2f (entry=%.2f, P&L=$%.2f) COOLDOWN %dmin",
                         exit_price, state.entry_price, pnl_dollars, config.cooldown_win_min);
                sc.AddMessageToLog(state.status_message, 0);
                sc.FlattenAndCancelAllOrders();
                state.in_position = false;
                state.break_even_activated = false;
                state.parent_order_id = 0;
                return;
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 13: SNAPSHOT ET LOGGING
// ═══════════════════════════════════════════════════════════════════════════════

// Forward declarations
void LogTradeResult(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config);

void SaveTradeSnapshot(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    // Créer nom fichier: MIA_TRADES_ES_20260117.json
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\SNAPSHOTS\\MIA_TRADE_%s_%04d%02d%02d_%06d.json",
             config.name, year, month, day, snap.trade_id);

    std::ofstream file(filename);
    if (!file.is_open()) return;

    file << "{\n";
    file << "  \"trade_id\": " << snap.trade_id << ",\n";
    file << "  \"symbol\": \"" << snap.symbol << "\",\n";
    file << "  \"entry_time\": \"" << FormatTimestamp(snap.entry_time) << "\",\n";
    file << "  \"exit_time\": \"" << FormatTimestamp(snap.exit_time) << "\",\n";
    file << "  \"direction\": \"" << (snap.direction == 1 ? "LONG" : "SHORT") << "\",\n";
    file << "  \"entry_price\": " << std::fixed << std::setprecision(2) << snap.entry_price << ",\n";
    file << "  \"exit_price\": " << snap.exit_price << ",\n";
    file << "  \"sl_price\": " << snap.sl_price << ",\n";
    file << "  \"tp_price\": " << snap.tp_price << ",\n";
    file << "  \"pnl\": " << snap.pnl << ",\n";
    file << "  \"exit_reason\": \"" << snap.exit_reason << "\",\n";

    // Layers avec détails complets
    file << "  \"layers\": {\n";
    file << "    \"l1\": {\"passed\": " << (snap.l1_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l1_confidence
         << ", \"level\": \"" << snap.l1_level_name << "\""
         << ", \"price\": " << snap.l1_level_price
         << ", \"distance_ticks\": " << snap.l1_distance_ticks << "},\n";
    file << "    \"l2\": {\"passed\": " << (snap.l2_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l2_confidence
         << ", \"bn_score\": " << snap.l2_bn_score
         << ", \"visual_signals\": " << snap.l2_visual_signals
         << ", \"correlation\": \"" << snap.l2_correlation << "\"},\n";
    file << "    \"l3\": {\"passed\": " << (snap.l3_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l3_confidence
         << ", \"context\": \"" << snap.l3_context << "\"},\n";
    file << "    \"l4\": {\"passed\": " << (snap.l4_passed ? "true" : "false")
         << ", \"combo\": " << snap.l4_combo_aligned
         << ", \"pct_ok\": " << (snap.l4_pct_ok ? "true" : "false")
         << ", \"delta_ok\": " << (snap.l4_delta_ok ? "true" : "false")
         << ", \"bn_ok\": " << (snap.l4_bn_ok ? "true" : "false")
         << ", \"vwap_ok\": " << (snap.l4_vwap_ok ? "true" : "false") << "}\n";
    file << "  },\n";

    // 🆕 Nouvelles données pour analyse
    file << "  \"trade_analysis\": {\n";
    file << "    \"is_rectangle_trade\": " << (snap.is_rectangle_trade ? "true" : "false") << ",\n";
    file << "    \"extension_line_dist\": " << snap.extension_line_dist << ",\n";
    file << "    \"vwap_slope\": " << std::setprecision(4) << snap.vwap_slope << ",\n";
    file << "    \"confluence_count\": " << snap.confluence_count << ",\n";
    // 🆕 CVD & POC at entry (pour analyser les trades)
    file << "    \"cvd_at_entry\": " << std::setprecision(0) << snap.bn_es.fpbs_cvd << ",\n";
    file << "    \"cvd_slope_at_entry\": " << snap.bn_es.cvd_slope << ",\n";
    file << "    \"cvd_divergence\": " << (snap.bn_es.cvd_divergence ? "true" : "false") << ",\n";
    file << "    \"poc_at_entry\": " << std::setprecision(2) << snap.bn_es.fpbs_poc << ",\n";
    file << "    \"poc_confirm\": " << snap.bn_es.poc_confirm << ",\n";
    file << "    \"poc_confirm_text\": \"" << (snap.bn_es.poc_confirm == 1 ? "BULLISH" : (snap.bn_es.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "  },\n";

    // Bataille Navale COMPLET (toutes les données)
    file << "  \"bataille_navale\": {\n";
    file << "    \"es\": {\n";
    file << "      \"score\": " << snap.bn_es.score << ",\n";
    file << "      \"momentum_score\": " << snap.bn_es.momentum_score << ",\n";
    file << "      \"reversal_score\": " << snap.bn_es.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << snap.bn_es.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << snap.bn_es.edge_buy << ", \"edge_sell\": " << snap.bn_es.edge_sell << ",\n";
    file << "      \"color_up\": " << snap.bn_es.color_up << ", \"color_down\": " << snap.bn_es.color_down << ",\n";
    file << "      \"absorb_ask\": " << snap.bn_es.absorb_ask << ", \"absorb_bid\": " << snap.bn_es.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << snap.bn_es.rotation_up << ", \"rotation_down\": " << snap.bn_es.rotation_down << ",\n";
    file << "      \"long_down_up\": " << snap.bn_es.long_down_up << ", \"long_up_down\": " << snap.bn_es.long_up_down << ",\n";
    file << "      \"double_ask\": " << snap.bn_es.double_ask << ", \"double_bid\": " << snap.bn_es.double_bid << ",\n";
    file << "      \"ask_100\": " << snap.bn_es.ask_100 << ", \"bid_100\": " << snap.bn_es.bid_100 << ",\n";
    file << "      \"ask_400\": " << snap.bn_es.ask_400 << ", \"bid_400\": " << snap.bn_es.bid_400 << ",\n";
    file << "      \"ask_1000\": " << snap.bn_es.ask_1000 << ", \"bid_1000\": " << snap.bn_es.bid_1000 << ",\n";
    file << "      \"fpbs_ask_pct\": " << snap.bn_es.fpbs_ask_pct << ", \"fpbs_bid_pct\": " << snap.bn_es.fpbs_bid_pct << ",\n";
    file << "      \"cluster_vol\": " << snap.bn_es.cluster_vol << ",\n";
    file << "      \"bar_color_up\": " << snap.bn_es.bar_color_up << ", \"bar_color_down\": " << snap.bn_es.bar_color_down << ",\n";
    file << "      \"bar_edge_buy\": " << snap.bn_es.bar_edge_buy << ", \"bar_edge_sell\": " << snap.bn_es.bar_edge_sell << ",\n";
    file << "      \"ext_support\": " << snap.bn_es.nearest_ext_support << ", \"ext_resist\": " << snap.bn_es.nearest_ext_resist << "\n";
    file << "    },\n";
    file << "    \"nq\": {\n";
    file << "      \"score\": " << snap.bn_nq.score << ",\n";
    file << "      \"momentum_score\": " << snap.bn_nq.momentum_score << ",\n";
    file << "      \"reversal_score\": " << snap.bn_nq.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << snap.bn_nq.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << snap.bn_nq.edge_buy << ", \"edge_sell\": " << snap.bn_nq.edge_sell << ",\n";
    file << "      \"color_up\": " << snap.bn_nq.color_up << ", \"color_down\": " << snap.bn_nq.color_down << ",\n";
    file << "      \"absorb_ask\": " << snap.bn_nq.absorb_ask << ", \"absorb_bid\": " << snap.bn_nq.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << snap.bn_nq.rotation_up << ", \"rotation_down\": " << snap.bn_nq.rotation_down << ",\n";
    file << "      \"long_down_up\": " << snap.bn_nq.long_down_up << ", \"long_up_down\": " << snap.bn_nq.long_up_down << ",\n";
    file << "      \"triple_ask\": " << snap.bn_nq.triple_ask << ", \"triple_bid\": " << snap.bn_nq.triple_bid << ",\n";
    file << "      \"volume_up\": " << snap.bn_nq.volume_up << ", \"volume_down\": " << snap.bn_nq.volume_down << ",\n";
    file << "      \"ask_100\": " << snap.bn_nq.ask_100 << ", \"bid_100\": " << snap.bn_nq.bid_100 << ",\n";
    file << "      \"fpbs_ask_pct\": " << snap.bn_nq.fpbs_ask_pct << ", \"fpbs_bid_pct\": " << snap.bn_nq.fpbs_bid_pct << ",\n";
    file << "      \"cluster_vol\": " << snap.bn_nq.cluster_vol << ",\n";
    file << "      \"bar_color_up\": " << snap.bn_nq.bar_color_up << ", \"bar_color_down\": " << snap.bn_nq.bar_color_down << ",\n";
    file << "      \"bar_edge_buy\": " << snap.bn_nq.bar_edge_buy << ", \"bar_edge_sell\": " << snap.bn_nq.bar_edge_sell << ",\n";
    file << "      \"ext_support\": " << snap.bn_nq.nearest_ext_support << ", \"ext_resist\": " << snap.bn_nq.nearest_ext_resist << "\n";
    file << "    }\n";
    file << "  },\n";

    // Market context
    file << "  \"market\": {\n";
    file << "    \"vix\": " << snap.vix << ",\n";
    file << "    \"atr\": " << snap.atr << ",\n";
    file << "    \"spread\": " << snap.spread << ",\n";
    file << "    \"delta\": " << snap.delta << ",\n";
    file << "    \"cum_delta\": " << snap.cum_delta << ",\n";
    file << "    \"buy_pct\": " << snap.buy_pct << ",\n";
    file << "    \"session\": \"" << snap.session << "\"\n";
    file << "  }\n";

    file << "}\n";
    file.close();

    // === LOGGER LE TRADE DANS WIN OU LOSS ===
    LogTradeResult(sc, snap, config);
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOGGING TRADES WIN/LOSS SÉPARÉS PAR JOUR
// ═══════════════════════════════════════════════════════════════════════════════
void LogTradeResult(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    // Déterminer si WIN ou LOSS
    const char* folder = (snap.pnl >= 0) ? "TRADES_WIN" : "TRADES_LOSS";

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\%s\\%s_%04d%02d%02d.log",
             folder, config.name, year, month, day);

    // Ouvrir en mode append
    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    // Format V2: TIME|SYM|DIR|ENTRY|EXIT|PNL|REASON|BN|L1|L2|L3|L4|RECT|VWAP|SIGNALS|EXTDIST
    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << snap.symbol << "|"
         << (snap.direction == 1 ? "LONG" : "SHORT") << "|"
         << std::fixed << std::setprecision(2)
         << snap.entry_price << "|"
         << snap.exit_price << "|"
         << (snap.pnl >= 0 ? "+" : "") << snap.pnl << "|"
         << snap.exit_reason << "|"
         << (strcmp(config.name, "ES") == 0 ? snap.bn_es.score : snap.bn_nq.score) << "|"
         << snap.l1_confidence << "|"
         << snap.l2_confidence << "|"
         << snap.l3_confidence << "|"
         << snap.l4_combo_aligned << "|"
         << (snap.is_rectangle_trade ? "RECT" : "MQ") << "|"          // 🆕 Type de trade
         << std::setprecision(4) << snap.vwap_slope << "|"            // 🆕 Pente VWAP
         << snap.l2_visual_signals << "|"                              // 🆕 Nb signaux visuels
         << std::setprecision(1) << snap.extension_line_dist << "\n";  // 🆕 Dist extension

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOG SYNC POSITION - Log quand une position manuelle est detectee
// ═══════════════════════════════════════════════════════════════════════════════
void LogSyncPosition(SCStudyInterfaceRef sc, const char* symbol, int direction, float entry_price) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\SYNC\\sync_%04d%02d%02d.log",
             year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << symbol << "|"
         << (direction == 1 ? "LONG" : "SHORT") << "|"
         << std::fixed << std::setprecision(2) << entry_price << "|"
         << "MANUAL_OR_SIMPLEBRACKET\n";

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION: DISCORD INTEGRATION - Ecriture evenements pour bridge Python
// ═══════════════════════════════════════════════════════════════════════════════

void WriteDiscordEvent(SCStudyInterfaceRef sc, const char* json_data) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DISCORD_EVENTS\\events_%04d%02d%02d.jsonl",
             year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    file << json_data << "\n";
    file.close();
}

void NotifyDiscordTradeOpened(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config,
    float bn_score,
    float vwap_slope
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    // 🆕 Déterminer le texte POC confirm
    const char* poc_text = (snap.bn_es.poc_confirm == 1) ? "BULL" : 
                           (snap.bn_es.poc_confirm == -1) ? "BEAR" : "NEUT";
    
    // 🆕 Déterminer le texte CVD trend
    const char* cvd_text = (snap.bn_es.cvd_slope > 100) ? "UP" :
                           (snap.bn_es.cvd_slope < -100) ? "DN" : "FLAT";

    char json[1280];  // 🔧 Agrandi pour nouvelles données
    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_OPENED\",\"time\":\"%02d:%02d:%02d\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"pnl\":0,\"l1_conf\":%.2f,\"l2_conf\":%.2f,"
             "\"l3_conf\":%.2f,\"l4_combo\":%d,\"bn_score\":%.3f,\"vwap_slope\":%.4f,\"is_rectangle\":%s,"
             "\"cvd_slope\":%.0f,\"cvd_trend\":\"%s\",\"poc_confirm\":\"%s\"}",
             hour, minute, second, snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.sl_price, snap.tp_price,
             snap.l1_confidence, snap.l2_confidence, snap.l3_confidence,
             snap.l4_combo_aligned, bn_score, vwap_slope,
             snap.is_rectangle_trade ? "true" : "false",
             snap.bn_es.cvd_slope, cvd_text, poc_text);

    WriteDiscordEvent(sc, json);
}

void NotifyDiscordTradeClosed(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    // Calculer durée
    double duration_sec = (snap.exit_time - snap.entry_time).GetAsDouble() * 86400.0;

    char json[1024];
    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_CLOSED\",\"time\":\"%02d:%02d:%02d\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"exit\":%.2f,\"pnl\":%.2f,\"exit_reason\":\"%s\",\"duration_sec\":%.0f}",
             hour, minute, second, snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.exit_price, snap.pnl,
             snap.exit_reason, duration_sec);

    WriteDiscordEvent(sc, json);
}

// ═══════════════════════════════════════════════════════════════════════════════
// TRADE WHY JOURNAL - Journal explicatif de chaque trade/setup
// ═══════════════════════════════════════════════════════════════════════════════

// 🆕 Helper: Construire TradeWhy depuis les données disponibles
TradeWhy BuildTradeWhy(
    SCStudyInterfaceRef sc,
    const char* symbol,
    int direction,
    float current_price,
    const Layer1Result& l1,
    const Layer2Result& l2,
    const Layer3Result& l3,
    const Layer4Result& l4,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    float vix,
    float bn_anchor,
    bool is_rectangle,
    const RectangleSignal& rect_signal,
    const SymbolConfig& config,
    const char* execution_mode,
    const char* reject_reason = nullptr
) {
    TradeWhy why = {0};
    why.trade_id = g_trade_why_id++;
    why.timestamp = sc.CurrentSystemDateTime;
    strncpy(why.symbol, symbol, sizeof(why.symbol) - 1);
    strncpy(why.side, direction == 1 ? "LONG" : "SHORT", sizeof(why.side) - 1);
    strncpy(why.execution_mode, execution_mode ? execution_mode : "PENDING", sizeof(why.execution_mode) - 1);

    // Trigger level
    if (is_rectangle && rect_signal.has_signal) {
        strncpy(why.trigger_level_type, "RECT", sizeof(why.trigger_level_type) - 1);
        why.trigger_level_price = rect_signal.rectangle_price;
    } else {
        strncpy(why.trigger_level_type, l1.level_name, sizeof(why.trigger_level_type) - 1);
        why.trigger_level_price = l1.level_price;
    }

    // Anchor
    why.anchor_final = bn_anchor > 0 ? bn_anchor : current_price;
    why.anchor_ext = (bn.num_ext_support > 0 || bn.num_ext_resist > 0) ? why.anchor_final : 0;
    why.anchor_color = 0;
    why.dist_ticks_to_anchor = fabs(current_price - why.anchor_final) / config.tick_size;

    // Trade info
    why.entry_price = current_price;
    why.qty = 1;

    // Layers
    why.l1_ok = l1.passed ? 1 : 0;
    why.l2_ok = l2.passed ? 1 : 0;
    why.l3_ok = l3.passed ? 1 : 0;
    why.l4_ok = l4.passed ? 1 : 0;
    why.l1_confidence = l1.confidence;
    why.l2_confidence = l2.confidence;
    why.l3_confidence = l3.confidence;
    why.l4_combo = l4.combo_aligned;
    why.bn_score = bn.score;
    why.confluence_score = l2.confidence;
    why.is_rectangle = is_rectangle;

    // Contexte marché
    float vwap_slope = (strcmp(symbol, "ES") == 0) ? g_market_live.vwap_slope_es : g_market_live.vwap_slope_nq;
    why.vwap_slope = vwap_slope;
    why.vwap_dist_ticks = fabs(current_price - mq.vwap) / config.tick_size;
    why.vix_value = vix;
    strncpy(why.vix_regime, GetVIXRegimeName(g_market_live.vix_regime), sizeof(why.vix_regime) - 1);
    why.dom_healthy = 1;
    why.spread_ticks = 1.0f;

    // Veto
    why.veto_triggered = (reject_reason != nullptr) ? 1 : 0;
    if (reject_reason) {
        strncpy(why.veto_reason, reject_reason, sizeof(why.veto_reason) - 1);
    }
    if (l3.veto) {
        strncpy(why.layer_reject_reason, l3.veto_reason, sizeof(why.layer_reject_reason) - 1);
    } else if (!l2.passed) {
        strncpy(why.layer_reject_reason, l2.reason, sizeof(why.layer_reject_reason) - 1);
    } else if (!l3.passed) {
        strncpy(why.layer_reject_reason, l3.context, sizeof(why.layer_reject_reason) - 1);
    }

    // Notes
    snprintf(why.notes, sizeof(why.notes), "L1:%s L4:%d/4", l1.level_name, l4.combo_aligned);

    return why;
}

void LogTradeWhy(
    SCStudyInterfaceRef sc,
    const TradeWhy& why,
    const SymbolConfig& config
) {
    int y, mo, d, h, mi, s;
    why.timestamp.GetDateTimeYMDHMS(y, mo, d, h, mi, s);

    // === SÉPARATION TRADES / REJETS ===
    // Trades (IMMEDIATE, PENDING_LIMIT, SKIP_TOO_FAR) → TRADES_WHY/
    // Rejets (REJECTED) → REJETS_WHY/
    bool is_reject = (strcmp(why.execution_mode, "REJECTED") == 0);

    char csv_file[256];
    if (is_reject) {
        // Rejets: REJETS_WHY/[ES|NQ]/REJET_WHY_[SYM]_YYYYMMDD.csv
        snprintf(csv_file, sizeof(csv_file),
            "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\REJETS_WHY\\%s\\REJET_WHY_%s_%04d%02d%02d.csv",
            why.symbol, why.symbol, y, mo, d);
    } else {
        // Trades: TRADES_WHY/[ES|NQ]/TRADE_WHY_[SYM]_YYYYMMDD.csv
        snprintf(csv_file, sizeof(csv_file),
            "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADES_WHY\\%s\\TRADE_WHY_%s_%04d%02d%02d.csv",
            why.symbol, why.symbol, y, mo, d);
    }

    std::ofstream csv(csv_file, std::ios::app);
    if (!csv.is_open()) return;

    // Header si fichier vide
    csv.seekp(0, std::ios::end);
    bool is_new_file = (csv.tellp() == 0);
    if (is_new_file) {
        csv << "trade_id;timestamp;symbol;side;execution_mode;"
            << "trigger_level_type;trigger_level_price;anchor_ext;anchor_color;anchor_final;dist_ticks_to_anchor;"
            << "entry_price;sl_price;tp_price;qty;"
            << "l1_ok;l2_ok;l3_ok;l4_ok;l1_conf;l2_conf;l3_conf;l4_combo;bn_score;confluence_score;is_rectangle;"
            << "vwap_slope;vwap_dist_ticks;vix_value;vix_regime;dom_healthy;spread_ticks;"
            << "veto_triggered;veto_reason;layer_reject_reason;notes\n";
    }

    // Ligne CSV
    csv << why.trade_id << ";"
        << std::setfill('0') << std::setw(4) << y << "-"
        << std::setw(2) << mo << "-"
        << std::setw(2) << d << " "
        << std::setw(2) << h << ":"
        << std::setw(2) << mi << ":"
        << std::setw(2) << s << ";"
        << why.symbol << ";"
        << why.side << ";"
        << why.execution_mode << ";"
        << why.trigger_level_type << ";"
        << std::fixed << std::setprecision(2) << why.trigger_level_price << ";"
        << why.anchor_ext << ";"
        << why.anchor_color << ";"
        << why.anchor_final << ";"
        << std::setprecision(1) << why.dist_ticks_to_anchor << ";"
        << std::setprecision(2) << why.entry_price << ";"
        << why.sl_price << ";"
        << why.tp_price << ";"
        << why.qty << ";"
        << why.l1_ok << ";"
        << why.l2_ok << ";"
        << why.l3_ok << ";"
        << why.l4_ok << ";"
        << std::setprecision(3) << why.l1_confidence << ";"
        << why.l2_confidence << ";"
        << why.l3_confidence << ";"
        << why.l4_combo << ";"
        << why.bn_score << ";"
        << why.confluence_score << ";"
        << (why.is_rectangle ? 1 : 0) << ";"
        << std::setprecision(4) << why.vwap_slope << ";"
        << std::setprecision(1) << why.vwap_dist_ticks << ";"
        << std::setprecision(2) << why.vix_value << ";"
        << why.vix_regime << ";"
        << why.dom_healthy << ";"
        << std::setprecision(1) << why.spread_ticks << ";"
        << why.veto_triggered << ";"
        << "\"" << why.veto_reason << "\";"
        << "\"" << why.layer_reject_reason << "\";"
        << "\"" << why.notes << "\"\n";

    csv.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOG DES SIGNAUX REJETES - V53 avec VWAP SLOPE
// ═══════════════════════════════════════════════════════════════════════════════
// CRUCIAL: Permet d'etudier les patterns de rejet et optimiser les seuils
// Fichier: LOGS/REJETS/[SYMBOL]_REJETS_[DATE].log
// Format V53: TIME|SYM|DIR|PRICE|LAYER|REASON|LVL|DIST|VIX|BN|VWAP_SLOPE
// ═══════════════════════════════════════════════════════════════════════════════
void LogRejectedSignal(
    SCStudyInterfaceRef sc,
    const SymbolConfig& config,
    const char* direction,
    const char* layer,           // "L1", "L2", "L3", "L3_VETO", "L4"
    const char* reject_reason,
    float current_price,
    float nearest_level,         // Niveau MenthorQ le plus proche (0 si aucun)
    float distance_ticks,        // Distance en ticks
    float vix,
    float bn_score
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\REJETS\\%s_REJETS_%04d%02d%02d.log",
             config.name, year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    // Header si fichier vide/nouveau
    file.seekp(0, std::ios::end);
    if (file.tellp() == 0) {
        file << "# MIA AutoTrader V53 - Log des signaux rejetes\n";
        file << "# Layer 4: 2/4 (pct + delta + bn + vwap_slope)\n";
        file << "# Format: TIME|SYM|DIR|PRICE|LAYER|REASON|LVL|DIST|VIX|BN|VWAP_SLOPE\n";
        file << "# ════════════════════════════════════════════════════════════════════════════\n";
    }

    // Recuperer le VWAP slope selon le symbole
    float vwap_slope = 0;
    if (strcmp(config.name, "ES") == 0) {
        vwap_slope = g_market_live.vwap_slope_es;
    } else {
        vwap_slope = g_market_live.vwap_slope_nq;
    }

    // Ecrire le rejet avec VWAP slope
    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << config.name << "|"
         << direction << "|"
         << std::fixed << std::setprecision(2) << current_price << "|"
         << layer << "|"
         << reject_reason << "|";

    // Nearest level (ou NONE si pas de niveau)
    if (nearest_level > 0) {
        file << std::fixed << std::setprecision(2) << nearest_level;
    } else {
        file << "NONE";
    }
    file << "|"
         << std::setprecision(1) << distance_ticks << "|"
         << vix << "|"
         << std::setprecision(3) << bn_score << "|"
         << std::setprecision(4) << vwap_slope << "\n";

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 AFFICHAGE DASHBOARD SUR LE GRAPHIQUE
// ═══════════════════════════════════════════════════════════════════════════════
void DrawDashboardOnChart(SCStudyInterfaceRef sc) {
    // Supprimer les anciens textes (IDs 9000-9010)
    for (int i = 9000; i <= 9010; i++) {
        sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_CHARTDRAWING, i);
    }

    // Couleurs selon statut
    COLORREF color_ok = RGB(0, 255, 0);       // Vert
    COLORREF color_warn = RGB(255, 255, 0);   // Jaune
    COLORREF color_block = RGB(255, 100, 100); // Rouge clair
    COLORREF color_text = RGB(255, 255, 255); // Blanc

    // Position en haut à droite du graphique
    float x_pos = 70.0f;  // % depuis la gauche (était 95, trop à droite)
    float y_start = 95.0f; // % depuis le bas (était 98)
    float line_height = 2.5f;

    int line = 0;
    s_UseTool tool;

    // === LIGNE 1: STATUT GLOBAL ===
    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("[MIA BOT] %s", g_dashboard.global_status);
    tool.Color = color_ok;
    tool.FontSize = 12;
    tool.FontBold = 1;
    sc.UseTool(tool);
    line++;

    // === LIGNE 2: SESSION ===
    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("Session: %s | VIX: %.2f", g_dashboard.current_session, g_market_live.vix);
    tool.Color = color_text;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 3: ES STATUS ===
    COLORREF es_color = color_ok;
    if (strcmp(g_dashboard.bot_action_es, "NEWS BLOCK") == 0 || strcmp(g_dashboard.bot_action_es, "BLOCKED") == 0) {
        es_color = color_block;
    } else if (strcmp(g_dashboard.bot_action_es, "WAITING") == 0) {
        es_color = color_warn;
    }

    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("ES: %s | T:%d W:%d L:%d | $%.0f",
        g_dashboard.bot_action_es,
        g_es_state.trades_today, g_es_state.wins_today, g_es_state.losses_today,
        g_es_state.pnl_today);
    // 🆕 Couleur P&L: Rouge si négatif, Vert si positif
    COLORREF pnl_color_es = (g_es_state.pnl_today >= 0) ? RGB(0, 255, 0) : RGB(255, 0, 0);
    tool.Color = pnl_color_es;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 4: ES RAISON ===
    if (strlen(g_dashboard.no_trade_reason_es) > 0) {
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = 9000 + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        tool.Text.Format("   -> %s", g_dashboard.no_trade_reason_es);
        tool.Color = RGB(200, 200, 200);
        tool.FontSize = 9;
        sc.UseTool(tool);
        line++;
    }

    // === LIGNE 5: NQ STATUS ===
    COLORREF nq_color = color_ok;
    if (strcmp(g_dashboard.bot_action_nq, "NEWS BLOCK") == 0 || strcmp(g_dashboard.bot_action_nq, "BLOCKED") == 0) {
        nq_color = color_block;
    } else if (strcmp(g_dashboard.bot_action_nq, "WAITING") == 0) {
        nq_color = color_warn;
    }

    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("NQ: %s | T:%d W:%d L:%d | $%.0f",
        g_dashboard.bot_action_nq,
        g_nq_state.trades_today, g_nq_state.wins_today, g_nq_state.losses_today,
        g_nq_state.pnl_today);
    // 🆕 Couleur P&L: Rouge si négatif, Vert si positif
    COLORREF pnl_color_nq = (g_nq_state.pnl_today >= 0) ? RGB(0, 255, 0) : RGB(255, 0, 0);
    tool.Color = pnl_color_nq;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 6: NQ RAISON ===
    if (strlen(g_dashboard.no_trade_reason_nq) > 0) {
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = 9000 + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        tool.Text.Format("   -> %s", g_dashboard.no_trade_reason_nq);
        tool.Color = RGB(200, 200, 200);
        tool.FontSize = 9;
        sc.UseTool(tool);
    }
}

void SaveDashboard(SCStudyInterfaceRef sc) {
    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\DASHBOARD\\MIA_AutoTrader_Dashboard.json");

    std::ofstream file(filename);
    if (!file.is_open()) return;

    file << "{\n";
    file << "  \"bot_status\": {\n";
    file << "    \"running\": " << (g_dashboard.bot_running ? "true" : "false") << ",\n";
    file << "    \"last_heartbeat\": \"" << FormatTimestamp(g_dashboard.last_heartbeat) << "\",\n";
    file << "    \"global_status\": \"" << g_dashboard.global_status << "\"\n";
    file << "  },\n";

    // ES State
    file << "  \"es\": {\n";
    file << "    \"enabled\": " << (g_es_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (g_es_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (g_es_state.in_position ? "true" : "false") << ",\n";
    file << "    \"status\": \"" << g_es_state.status_message << "\",\n";
    file << "    \"waiting_for\": \"" << g_es_state.waiting_for << "\",\n";
    file << "    \"trades_today\": " << g_es_state.trades_today << ",\n";
    file << "    \"wins\": " << g_es_state.wins_today << ",\n";
    file << "    \"losses\": " << g_es_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << std::fixed << std::setprecision(2) << g_es_state.pnl_today << ",\n";
    file << "    \"consecutive_losses\": " << g_es_state.consecutive_losses << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_es << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_es << "\",\n";
    file << "    \"last_rejected\": \"" << g_dashboard.last_rejected_es << "\",\n";
    file << "    \"signals_rejected\": " << g_dashboard.signals_rejected_es << "\n";
    file << "  },\n";

    // NQ State
    file << "  \"nq\": {\n";
    file << "    \"enabled\": " << (g_nq_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (g_nq_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (g_nq_state.in_position ? "true" : "false") << ",\n";
    file << "    \"status\": \"" << g_nq_state.status_message << "\",\n";
    file << "    \"waiting_for\": \"" << g_nq_state.waiting_for << "\",\n";
    file << "    \"trades_today\": " << g_nq_state.trades_today << ",\n";
    file << "    \"wins\": " << g_nq_state.wins_today << ",\n";
    file << "    \"losses\": " << g_nq_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << std::fixed << std::setprecision(2) << g_nq_state.pnl_today << ",\n";
    file << "    \"consecutive_losses\": " << g_nq_state.consecutive_losses << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_nq << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_nq << "\",\n";
    file << "    \"last_rejected\": \"" << g_dashboard.last_rejected_nq << "\",\n";
    file << "    \"signals_rejected\": " << g_dashboard.signals_rejected_nq << "\n";
    file << "  },\n";

    // Schedule
    file << "  \"schedule\": {\n";
    file << "    \"current_session\": \"" << g_dashboard.current_session << "\",\n";
    file << "    \"next_event\": \"" << g_dashboard.next_event << "\"\n";
    file << "  },\n";

    // Warnings
    file << "  \"warnings\": {\n";
    file << "    \"news_detected\": " << (g_dashboard.news_detected ? "true" : "false") << ",\n";
    file << "    \"news_message\": \"" << g_dashboard.news_message << "\"\n";
    file << "  },\n";

    // 🆕 Market Live Data
    file << "  \"market_live\": {\n";
    file << "    \"vix\": " << std::fixed << std::setprecision(2) << g_market_live.vix << ",\n";
    file << "    \"vix_regime\": \"" << GetVIXRegimeName(g_market_live.vix_regime) << "\",\n";
    file << "    \"vix_valid\": " << (g_market_live.vix_valid ? "true" : "false") << ",\n";
    file << "    \"atr_es\": " << g_market_live.atr_es << ",\n";
    file << "    \"atr_nq\": " << g_market_live.atr_nq << ",\n";
    file << "    \"atr_valid\": " << (g_market_live.atr_valid ? "true" : "false") << ",\n";
    file << "    \"vwap_slope_es\": " << std::setprecision(4) << g_market_live.vwap_slope_es << ",\n";
    file << "    \"vwap_slope_nq\": " << g_market_live.vwap_slope_nq << "\n";
    file << "  }\n";

    file << "}\n";
    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 SECTION 13B: DIAGNOSTIC SNAPSHOT (27/01/2026)
// Exporte TOUTES les données que le bot voit pour validation
// ═══════════════════════════════════════════════════════════════════════════════

void WriteDiagnosticSnapshot(
    SCStudyInterfaceRef sc,
    const BN_Data& bn_es,
    const BN_Data& bn_nq,
    const MenthorQ_Data& mq_es,
    const MenthorQ_Data& mq_nq,
    float price_es,
    float price_nq
) {
    // Fichier unique avec timestamp
    std::string path = "D:\\MIA_IA_system\\DIAGNOSTIC_SNAPSHOT.json";
    std::ofstream file(path.c_str());
    if (!file.is_open()) return;

    file << std::fixed;
    file << "{\n";
    
    // === TIMESTAMP ===
    file << "  \"timestamp\": \"" << FormatTimestamp(sc.CurrentSystemDateTime) << "\",\n";
    file << "  \"session\": \"" << g_dashboard.current_session << "\",\n";
    file << "  \"status\": \"" << g_dashboard.global_status << "\",\n";
    
    // === MARKET LIVE ===
    file << "  \"market_live\": {\n";
    file << "    \"vix\": " << std::setprecision(2) << g_market_live.vix << ",\n";
    file << "    \"vix_regime\": \"" << GetVIXRegimeName(g_market_live.vix_regime) << "\",\n";
    file << "    \"vix_valid\": " << (g_market_live.vix_valid ? "true" : "false") << ",\n";
    file << "    \"atr_es\": " << g_market_live.atr_es << ",\n";
    file << "    \"atr_nq\": " << g_market_live.atr_nq << ",\n";
    file << "    \"atr_valid\": " << (g_market_live.atr_valid ? "true" : "false") << ",\n";
    file << "    \"vwap_slope_es\": " << std::setprecision(6) << g_market_live.vwap_slope_es << ",\n";
    file << "    \"vwap_slope_nq\": " << g_market_live.vwap_slope_nq << "\n";
    file << "  },\n";

    // === ES DATA ===
    file << "  \"ES\": {\n";
    file << "    \"price\": " << std::setprecision(2) << price_es << ",\n";
    file << "    \"enabled\": " << (g_es_state.enabled ? "true" : "false") << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_es << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_es << "\",\n";
    
    // MenthorQ ES
    file << "    \"menthorq\": {\n";
    file << "      \"vwap\": " << std::setprecision(2) << mq_es.vwap << ",\n";
    file << "      \"vwap_up1\": " << mq_es.vwap_up1 << ",\n";
    file << "      \"vwap_dn1\": " << mq_es.vwap_dn1 << ",\n";
    file << "      \"vwap_up2\": " << mq_es.vwap_up2 << ",\n";
    file << "      \"vwap_dn2\": " << mq_es.vwap_dn2 << ",\n";
    file << "      \"hvl\": " << mq_es.hvl << ",\n";
    file << "      \"hvl_0dte\": " << mq_es.hvl_0dte << ",\n";
    file << "      \"gamma_wall\": " << mq_es.gamma_wall << ",\n";
    file << "      \"gamma_wall_0dte\": " << mq_es.gamma_wall_0dte << ",\n";
    file << "      \"call_resistance\": " << mq_es.call_resistance << ",\n";
    file << "      \"call_resistance_0dte\": " << mq_es.call_resistance_0dte << ",\n";
    file << "      \"put_support\": " << mq_es.put_support << ",\n";
    file << "      \"put_support_0dte\": " << mq_es.put_support_0dte << ",\n";
    file << "      \"vah\": " << mq_es.vah << ",\n";
    file << "      \"val\": " << mq_es.val << ",\n";
    file << "      \"day_min\": " << mq_es.day_min << ",\n";
    file << "      \"day_max\": " << mq_es.day_max << ",\n";
    file << "      \"next_wall_price\": " << mq_es.next_wall_price << ",\n";
    file << "      \"next_wall_side\": " << mq_es.next_wall_side << "\n";
    file << "    },\n";
    
    // Battle Navale ES
    file << "    \"battle_navale\": {\n";
    file << "      \"score\": " << std::setprecision(4) << bn_es.score << ",\n";
    file << "      \"signal\": " << bn_es.signal << ",\n";
    file << "      \"momentum_score\": " << bn_es.momentum_score << ",\n";
    file << "      \"reversal_score\": " << bn_es.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << bn_es.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << bn_es.edge_buy << ",\n";
    file << "      \"edge_sell\": " << bn_es.edge_sell << ",\n";
    file << "      \"edge_ratio\": " << bn_es.edge_ratio << ",\n";
    file << "      \"edge_dominant_buy\": " << (bn_es.edge_dominant_buy ? "true" : "false") << ",\n";
    file << "      \"edge_dominant_sell\": " << (bn_es.edge_dominant_sell ? "true" : "false") << ",\n";
    file << "      \"color_up\": " << bn_es.color_up << ",\n";
    file << "      \"color_down\": " << bn_es.color_down << ",\n";
    file << "      \"absorb_ask\": " << bn_es.absorb_ask << ",\n";
    file << "      \"absorb_bid\": " << bn_es.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << bn_es.rotation_up << ",\n";
    file << "      \"rotation_down\": " << bn_es.rotation_down << ",\n";
    file << "      \"long_down_up\": " << bn_es.long_down_up << ",\n";
    file << "      \"long_up_down\": " << bn_es.long_up_down << ",\n";
    file << "      \"double_bid\": " << bn_es.double_bid << ",\n";
    file << "      \"double_ask\": " << bn_es.double_ask << ",\n";
    file << "      \"fresh_rectangle_buy\": " << (bn_es.fresh_rectangle_buy ? "true" : "false") << ",\n";
    file << "      \"fresh_rectangle_sell\": " << (bn_es.fresh_rectangle_sell ? "true" : "false") << ",\n";
    file << "      \"num_ext_support\": " << bn_es.num_ext_support << ",\n";
    file << "      \"num_ext_resist\": " << bn_es.num_ext_resist << ",\n";
    file << "      \"nearest_ext_support\": " << std::setprecision(2) << bn_es.nearest_ext_support << ",\n";
    file << "      \"nearest_ext_resist\": " << bn_es.nearest_ext_resist << ",\n";
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR)
    file << "      \"num_long_up_bar\": " << bn_es.num_long_up_bar << ",\n";
    file << "      \"num_long_down_bar\": " << bn_es.num_long_down_bar << ",\n";
    file << "      \"nearest_long_up_bar\": " << bn_es.nearest_long_up_bar << ",\n";
    file << "      \"nearest_long_down_bar\": " << bn_es.nearest_long_down_bar << ",\n";
    file << "      \"has_tradable_support\": " << (bn_es.has_tradable_support ? "true" : "false") << ",\n";
    file << "      \"has_tradable_resist\": " << (bn_es.has_tradable_resist ? "true" : "false") << ",\n";
    file << "      \"num_edge_rect_buy\": " << bn_es.num_edge_rect_buy << ",\n";
    file << "      \"num_edge_rect_sell\": " << bn_es.num_edge_rect_sell << ",\n";
    file << "      \"nearest_edge_rect_support\": " << bn_es.nearest_edge_rect_support << ",\n";
    file << "      \"nearest_edge_rect_resist\": " << bn_es.nearest_edge_rect_resist << ",\n";
    file << "      \"price_in_edge_rect_buy\": " << (bn_es.price_in_edge_rect_buy ? "true" : "false") << ",\n";
    file << "      \"price_in_edge_rect_sell\": " << (bn_es.price_in_edge_rect_sell ? "true" : "false") << ",\n";
    file << "      \"bn_attack_long_valid\": " << (bn_es.bn_attack_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_attack_short_valid\": " << (bn_es.bn_attack_short_valid ? "true" : "false") << ",\n";
    // 🆕 30/01/2026: Règle subtile avec boules
    file << "      \"bn_subtile_long_valid\": " << (bn_es.bn_subtile_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_subtile_short_valid\": " << (bn_es.bn_subtile_short_valid ? "true" : "false") << ",\n";
    file << "      \"green_base_price\": " << std::setprecision(2) << std::fixed << bn_es.green_base_price << ",\n";
    file << "      \"red_base_price\": " << std::setprecision(2) << std::fixed << bn_es.red_base_price << ",\n";
    file << "      \"num_color_up_prices\": " << bn_es.num_color_up_prices << ",\n";
    file << "      \"num_color_down_prices\": " << bn_es.num_color_down_prices << ",\n";
    // 🆕 30/01/2026: Mode RANGE
    file << "      \"is_range\": " << (bn_es.is_range ? "true" : "false") << ",\n";
    file << "      \"range_support\": " << std::setprecision(2) << std::fixed << bn_es.range_support << ",\n";
    file << "      \"range_resistance\": " << std::setprecision(2) << std::fixed << bn_es.range_resistance << ",\n";
    file << "      \"range_size_pts\": " << std::setprecision(1) << std::fixed << bn_es.range_size_pts << ",\n";
    file << "      \"price_position_pct\": " << std::setprecision(1) << std::fixed << bn_es.price_position_pct << ",\n";
    file << "      \"price_position\": " << bn_es.price_position << ",\n";
    file << "      \"directional_coherence\": " << std::setprecision(4) << bn_es.directional_coherence << "\n";
    file << "    },\n";
    
    // Extension Lines ES
    file << "    \"extension_lines\": {\n";
    file << "      \"supports\": [";
    for (int i = 0; i < bn_es.num_ext_support && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.ext_lines_support[i];
    }
    file << "],\n";
    file << "      \"resistances\": [";
    for (int i = 0; i < bn_es.num_ext_resist && i < 10; i++) {
        if (i > 0) file << ", ";
        file << bn_es.ext_lines_resist[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // Edge Rectangles ES
    file << "    \"edge_rectangles\": {\n";
    file << "      \"buy_zones\": [";
    for (int i = 0; i < bn_es.num_edge_rect_buy && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_es.edge_rect_buy_bottom[i] << ", \"top\": " << bn_es.edge_rect_buy_top[i] << "}";
    }
    file << "],\n";
    file << "      \"sell_zones\": [";
    for (int i = 0; i < bn_es.num_edge_rect_sell && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_es.edge_rect_sell_bottom[i] << ", \"top\": " << bn_es.edge_rect_sell_top[i] << "}";
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 Rectangles Tradables ES (LONG UP/DOWN BAR - séparés des boules)
    file << "    \"tradable_rectangles\": {\n";
    file << "      \"green_supports\": [";
    for (int i = 0; i < bn_es.num_long_up_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.long_up_bar_ext[i];
    }
    file << "],\n";
    file << "      \"red_resistances\": [";
    for (int i = 0; i < bn_es.num_long_down_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.long_down_bar_ext[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 FPBS AVANCÉ ES (Delta, CVD, POC)
    file << "    \"fpbs\": {\n";
    file << "      \"delta\": " << std::setprecision(0) << bn_es.fpbs_delta << ",\n";
    file << "      \"delta_day\": " << bn_es.fpbs_delta_day << ",\n";
    file << "      \"cvd\": " << bn_es.fpbs_cvd << ",\n";
    file << "      \"poc\": " << std::setprecision(2) << bn_es.fpbs_poc << ",\n";
    file << "      \"ask_pct\": " << std::setprecision(1) << bn_es.fpbs_ask_pct << ",\n";
    file << "      \"bid_pct\": " << bn_es.fpbs_bid_pct << "\n";
    file << "    },\n";
    
    // 🆕 CVD & POC ANALYSIS ES
    file << "    \"cvd_poc_analysis\": {\n";
    file << "      \"current_cvd\": " << std::setprecision(0) << bn_es.fpbs_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"prev_cvd\": " << std::setprecision(0) << bn_es.prev_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"cvd_slope\": " << std::setprecision(0) << bn_es.cvd_slope << ",\n";
    file << "      \"cvd_trend_score\": " << std::setprecision(2) << bn_es.cvd_trend_score << ",\n";
    file << "      \"cvd_divergence\": " << (bn_es.cvd_divergence ? "true" : "false") << ",\n";
    file << "      \"poc_confirm\": " << bn_es.poc_confirm << ",\n";
    file << "      \"poc_confirm_text\": \"" << (bn_es.poc_confirm == 1 ? "BULLISH" : (bn_es.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "    },\n";
    
    // 🆕 ORDRES INSTITUTIONNELS ES
    file << "    \"institutional_orders\": {\n";
    file << "      \"ask_100\": " << std::setprecision(0) << bn_es.ask_100 << ",\n";
    file << "      \"bid_100\": " << bn_es.bid_100 << ",\n";
    file << "      \"ask_150\": " << bn_es.ask_150 << ",\n";
    file << "      \"bid_150\": " << bn_es.bid_150 << ",\n";
    file << "      \"ask_400\": " << bn_es.ask_400 << ",\n";
    file << "      \"bid_400\": " << bn_es.bid_400 << ",\n";
    file << "      \"ask_1000\": " << bn_es.ask_1000 << ",\n";
    file << "      \"bid_1000\": " << bn_es.bid_1000 << ",\n";
    file << "      \"cluster_vol\": " << bn_es.cluster_vol << "\n";
    file << "    }\n";
    file << "  },\n";

    // === NQ DATA ===
    file << "  \"NQ\": {\n";
    file << "    \"price\": " << std::setprecision(2) << price_nq << ",\n";
    file << "    \"enabled\": " << (g_nq_state.enabled ? "true" : "false") << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_nq << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_nq << "\",\n";
    
    // MenthorQ NQ
    file << "    \"menthorq\": {\n";
    file << "      \"vwap\": " << std::setprecision(2) << mq_nq.vwap << ",\n";
    file << "      \"vwap_up1\": " << mq_nq.vwap_up1 << ",\n";
    file << "      \"vwap_dn1\": " << mq_nq.vwap_dn1 << ",\n";
    file << "      \"vwap_up2\": " << mq_nq.vwap_up2 << ",\n";
    file << "      \"vwap_dn2\": " << mq_nq.vwap_dn2 << ",\n";
    file << "      \"hvl\": " << mq_nq.hvl << ",\n";
    file << "      \"hvl_0dte\": " << mq_nq.hvl_0dte << ",\n";
    file << "      \"gamma_wall\": " << mq_nq.gamma_wall << ",\n";
    file << "      \"gamma_wall_0dte\": " << mq_nq.gamma_wall_0dte << ",\n";
    file << "      \"call_resistance\": " << mq_nq.call_resistance << ",\n";
    file << "      \"call_resistance_0dte\": " << mq_nq.call_resistance_0dte << ",\n";
    file << "      \"put_support\": " << mq_nq.put_support << ",\n";
    file << "      \"put_support_0dte\": " << mq_nq.put_support_0dte << ",\n";
    file << "      \"vah\": " << mq_nq.vah << ",\n";
    file << "      \"val\": " << mq_nq.val << ",\n";
    file << "      \"day_min\": " << mq_nq.day_min << ",\n";
    file << "      \"day_max\": " << mq_nq.day_max << ",\n";
    file << "      \"next_wall_price\": " << mq_nq.next_wall_price << ",\n";
    file << "      \"next_wall_side\": " << mq_nq.next_wall_side << "\n";
    file << "    },\n";
    
    // Battle Navale NQ
    file << "    \"battle_navale\": {\n";
    file << "      \"score\": " << std::setprecision(4) << bn_nq.score << ",\n";
    file << "      \"signal\": " << bn_nq.signal << ",\n";
    file << "      \"momentum_score\": " << bn_nq.momentum_score << ",\n";
    file << "      \"reversal_score\": " << bn_nq.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << bn_nq.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << bn_nq.edge_buy << ",\n";
    file << "      \"edge_sell\": " << bn_nq.edge_sell << ",\n";
    file << "      \"edge_ratio\": " << bn_nq.edge_ratio << ",\n";
    file << "      \"edge_dominant_buy\": " << (bn_nq.edge_dominant_buy ? "true" : "false") << ",\n";
    file << "      \"edge_dominant_sell\": " << (bn_nq.edge_dominant_sell ? "true" : "false") << ",\n";
    file << "      \"color_up\": " << bn_nq.color_up << ",\n";
    file << "      \"color_down\": " << bn_nq.color_down << ",\n";
    file << "      \"absorb_ask\": " << bn_nq.absorb_ask << ",\n";
    file << "      \"absorb_bid\": " << bn_nq.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << bn_nq.rotation_up << ",\n";
    file << "      \"rotation_down\": " << bn_nq.rotation_down << ",\n";
    file << "      \"long_down_up\": " << bn_nq.long_down_up << ",\n";
    file << "      \"long_up_down\": " << bn_nq.long_up_down << ",\n";
    file << "      \"triple_bid\": " << bn_nq.triple_bid << ",\n";
    file << "      \"triple_ask\": " << bn_nq.triple_ask << ",\n";
    file << "      \"fresh_rectangle_buy\": " << (bn_nq.fresh_rectangle_buy ? "true" : "false") << ",\n";
    file << "      \"fresh_rectangle_sell\": " << (bn_nq.fresh_rectangle_sell ? "true" : "false") << ",\n";
    file << "      \"num_ext_support\": " << bn_nq.num_ext_support << ",\n";
    file << "      \"num_ext_resist\": " << bn_nq.num_ext_resist << ",\n";
    file << "      \"nearest_ext_support\": " << std::setprecision(2) << bn_nq.nearest_ext_support << ",\n";
    file << "      \"nearest_ext_resist\": " << bn_nq.nearest_ext_resist << ",\n";
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR)
    file << "      \"num_long_up_bar\": " << bn_nq.num_long_up_bar << ",\n";
    file << "      \"num_long_down_bar\": " << bn_nq.num_long_down_bar << ",\n";
    file << "      \"nearest_long_up_bar\": " << bn_nq.nearest_long_up_bar << ",\n";
    file << "      \"nearest_long_down_bar\": " << bn_nq.nearest_long_down_bar << ",\n";
    file << "      \"has_tradable_support\": " << (bn_nq.has_tradable_support ? "true" : "false") << ",\n";
    file << "      \"has_tradable_resist\": " << (bn_nq.has_tradable_resist ? "true" : "false") << ",\n";
    file << "      \"num_edge_rect_buy\": " << bn_nq.num_edge_rect_buy << ",\n";
    file << "      \"num_edge_rect_sell\": " << bn_nq.num_edge_rect_sell << ",\n";
    file << "      \"nearest_edge_rect_support\": " << bn_nq.nearest_edge_rect_support << ",\n";
    file << "      \"nearest_edge_rect_resist\": " << bn_nq.nearest_edge_rect_resist << ",\n";
    file << "      \"price_in_edge_rect_buy\": " << (bn_nq.price_in_edge_rect_buy ? "true" : "false") << ",\n";
    file << "      \"price_in_edge_rect_sell\": " << (bn_nq.price_in_edge_rect_sell ? "true" : "false") << ",\n";
    file << "      \"bn_attack_long_valid\": " << (bn_nq.bn_attack_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_attack_short_valid\": " << (bn_nq.bn_attack_short_valid ? "true" : "false") << ",\n";
    // 🆕 30/01/2026: Règle subtile avec boules
    file << "      \"bn_subtile_long_valid\": " << (bn_nq.bn_subtile_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_subtile_short_valid\": " << (bn_nq.bn_subtile_short_valid ? "true" : "false") << ",\n";
    file << "      \"green_base_price\": " << std::setprecision(2) << std::fixed << bn_nq.green_base_price << ",\n";
    file << "      \"red_base_price\": " << std::setprecision(2) << std::fixed << bn_nq.red_base_price << ",\n";
    file << "      \"num_color_up_prices\": " << bn_nq.num_color_up_prices << ",\n";
    file << "      \"num_color_down_prices\": " << bn_nq.num_color_down_prices << ",\n";
    // 🆕 30/01/2026: Mode RANGE
    file << "      \"is_range\": " << (bn_nq.is_range ? "true" : "false") << ",\n";
    file << "      \"range_support\": " << std::setprecision(2) << std::fixed << bn_nq.range_support << ",\n";
    file << "      \"range_resistance\": " << std::setprecision(2) << std::fixed << bn_nq.range_resistance << ",\n";
    file << "      \"range_size_pts\": " << std::setprecision(1) << std::fixed << bn_nq.range_size_pts << ",\n";
    file << "      \"price_position_pct\": " << std::setprecision(1) << std::fixed << bn_nq.price_position_pct << ",\n";
    file << "      \"price_position\": " << bn_nq.price_position << ",\n";
    file << "      \"directional_coherence\": " << std::setprecision(4) << bn_nq.directional_coherence << "\n";
    file << "    },\n";
    
    // Extension Lines NQ
    file << "    \"extension_lines\": {\n";
    file << "      \"supports\": [";
    for (int i = 0; i < bn_nq.num_ext_support && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.ext_lines_support[i];
    }
    file << "],\n";
    file << "      \"resistances\": [";
    for (int i = 0; i < bn_nq.num_ext_resist && i < 10; i++) {
        if (i > 0) file << ", ";
        file << bn_nq.ext_lines_resist[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // Edge Rectangles NQ
    file << "    \"edge_rectangles\": {\n";
    file << "      \"buy_zones\": [";
    for (int i = 0; i < bn_nq.num_edge_rect_buy && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_nq.edge_rect_buy_bottom[i] << ", \"top\": " << bn_nq.edge_rect_buy_top[i] << "}";
    }
    file << "],\n";
    file << "      \"sell_zones\": [";
    for (int i = 0; i < bn_nq.num_edge_rect_sell && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_nq.edge_rect_sell_bottom[i] << ", \"top\": " << bn_nq.edge_rect_sell_top[i] << "}";
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 Rectangles Tradables NQ (LONG UP/DOWN BAR - séparés des boules)
    file << "    \"tradable_rectangles\": {\n";
    file << "      \"green_supports\": [";
    for (int i = 0; i < bn_nq.num_long_up_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.long_up_bar_ext[i];
    }
    file << "],\n";
    file << "      \"red_resistances\": [";
    for (int i = 0; i < bn_nq.num_long_down_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.long_down_bar_ext[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 FPBS AVANCÉ NQ (Delta, CVD, POC)
    file << "    \"fpbs\": {\n";
    file << "      \"delta\": " << std::setprecision(0) << bn_nq.fpbs_delta << ",\n";
    file << "      \"delta_day\": " << bn_nq.fpbs_delta_day << ",\n";
    file << "      \"cvd\": " << bn_nq.fpbs_cvd << ",\n";
    file << "      \"poc\": " << std::setprecision(2) << bn_nq.fpbs_poc << ",\n";
    file << "      \"ask_pct\": " << std::setprecision(1) << bn_nq.fpbs_ask_pct << ",\n";
    file << "      \"bid_pct\": " << bn_nq.fpbs_bid_pct << "\n";
    file << "    },\n";
    
    // 🆕 CVD & POC ANALYSIS NQ
    file << "    \"cvd_poc_analysis\": {\n";
    file << "      \"current_cvd\": " << std::setprecision(0) << bn_nq.fpbs_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"prev_cvd\": " << std::setprecision(0) << bn_nq.prev_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"cvd_slope\": " << std::setprecision(0) << bn_nq.cvd_slope << ",\n";
    file << "      \"cvd_trend_score\": " << std::setprecision(2) << bn_nq.cvd_trend_score << ",\n";
    file << "      \"cvd_divergence\": " << (bn_nq.cvd_divergence ? "true" : "false") << ",\n";
    file << "      \"poc_confirm\": " << bn_nq.poc_confirm << ",\n";
    file << "      \"poc_confirm_text\": \"" << (bn_nq.poc_confirm == 1 ? "BULLISH" : (bn_nq.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "    },\n";
    
    // 🆕 ORDRES INSTITUTIONNELS NQ (granularité +10, +30, +100)
    file << "    \"institutional_orders\": {\n";
    file << "      \"ask_10\": " << std::setprecision(0) << bn_nq.ask_10 << ",\n";
    file << "      \"bid_10\": " << bn_nq.bid_10 << ",\n";
    file << "      \"ask_30\": " << bn_nq.ask_30 << ",\n";
    file << "      \"bid_30\": " << bn_nq.bid_30 << ",\n";
    file << "      \"ask_100\": " << bn_nq.ask_100 << ",\n";
    file << "      \"bid_100\": " << bn_nq.bid_100 << ",\n";
    file << "      \"triple_ask\": " << bn_nq.triple_ask << ",\n";
    file << "      \"triple_bid\": " << bn_nq.triple_bid << ",\n";
    file << "      \"cluster_vol\": " << bn_nq.cluster_vol << "\n";
    file << "    }\n";
    file << "  }\n";

    file << "}\n";
    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 14: STUDY PRINCIPALE
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_AutoTrader_BN(SCStudyInterfaceRef sc) {
    // === INPUTS ===
    SCInputRef Input_Enabled = sc.Input[0];
    SCInputRef Input_ES_Enabled = sc.Input[1];
    SCInputRef Input_NQ_Enabled = sc.Input[2];
    SCInputRef Input_ES_Paused = sc.Input[3];
    SCInputRef Input_NQ_Paused = sc.Input[4];
    SCInputRef Input_ES_Footprint_Chart = sc.Input[5];
    SCInputRef Input_ES_Barres_Chart = sc.Input[6];
    SCInputRef Input_NQ_Footprint_Chart = sc.Input[7];
    SCInputRef Input_NQ_Barres_Chart = sc.Input[8];
    SCInputRef Input_ES_Main_Chart = sc.Input[9];
    SCInputRef Input_NQ_Main_Chart = sc.Input[10];

    // 🆕 Charts VIX et Daily ATR
    SCInputRef Input_VIX_Chart = sc.Input[11];
    SCInputRef Input_ES_Daily_Chart = sc.Input[12];
    SCInputRef Input_NQ_Daily_Chart = sc.Input[13];

    // 🆕 MODE TEST/PRODUCTION
    SCInputRef Input_Bot_Mode = sc.Input[14];

    // 🆕 MODE RECTANGLES (Scalp sur rectangles verts/rouges)
    SCInputRef Input_Rectangle_Trading = sc.Input[15];

    // === SETUP ===
    if (sc.SetDefaults) {
        sc.GraphName = "MIA AutoTrader Bataille Navale v1";
        sc.AutoLoop = 0;  // Manual loop
        sc.GraphRegion = 0;
        sc.FreeDLL = 1;

        // Inputs
        Input_Enabled.Name = "Bot Enabled";
        Input_Enabled.SetYesNo(1);

        Input_ES_Enabled.Name = "Trade ES";
        Input_ES_Enabled.SetYesNo(1);

        Input_NQ_Enabled.Name = "Trade NQ";
        Input_NQ_Enabled.SetYesNo(1);

        Input_ES_Paused.Name = "ES Paused";
        Input_ES_Paused.SetYesNo(0);

        Input_NQ_Paused.Name = "NQ Paused";
        Input_NQ_Paused.SetYesNo(0);

        Input_ES_Footprint_Chart.Name = "ES Footprint Chart #";
        Input_ES_Footprint_Chart.SetInt(1);   // Chart 1 = ES Footprint (Bataille Navale)

        Input_ES_Barres_Chart.Name = "ES Barres Chart #";
        Input_ES_Barres_Chart.SetInt(25);     // 🔧 CORRIGÉ: Chart 25 = ES 1min Barres

        Input_NQ_Footprint_Chart.Name = "NQ Footprint Chart #";
        Input_NQ_Footprint_Chart.SetInt(2);   // Chart 2 = NQ Footprint (Bataille Navale)

        Input_NQ_Barres_Chart.Name = "NQ Barres Chart #";
        Input_NQ_Barres_Chart.SetInt(23);     // 🔧 CORRIGÉ: Chart 23 = NQ 1min Barres

        Input_ES_Main_Chart.Name = "ES Main Chart #";
        Input_ES_Main_Chart.SetInt(25);       // 🔧 CORRIGÉ: Chart 25 = ES Main (MenthorQ)

        Input_NQ_Main_Chart.Name = "NQ Main Chart #";
        Input_NQ_Main_Chart.SetInt(23);       // 🔧 CORRIGÉ: Chart 23 = NQ Main (MenthorQ)

        // 🆕 Charts VIX et Daily ATR
        Input_VIX_Chart.Name = "VIX Chart #";
        Input_VIX_Chart.SetInt(15);

        Input_ES_Daily_Chart.Name = "ES Daily Chart # (ATR)";
        Input_ES_Daily_Chart.SetInt(16);

        Input_NQ_Daily_Chart.Name = "NQ Daily Chart # (ATR)";
        Input_NQ_Daily_Chart.SetInt(17);

        // 🆕 MODE TEST/PRODUCTION
        Input_Bot_Mode.Name = "Mode (0=PRODUCTION, 1=TEST)";
        Input_Bot_Mode.SetInt(0);  // Par défaut: PRODUCTION
        Input_Bot_Mode.SetIntLimits(0, 1);

        // 🆕 MODE RECTANGLES (Scalp)
        Input_Rectangle_Trading.Name = "Trade Rectangles (Scalp)";
        Input_Rectangle_Trading.SetYesNo(1);  // Activé par défaut

        // Initialisation états
        memset(&g_es_state, 0, sizeof(BotState));
        memset(&g_nq_state, 0, sizeof(BotState));
        g_es_state.enabled = true;
        g_nq_state.enabled = true;
        strcpy(g_es_state.waiting_for, "Signal");
        strcpy(g_nq_state.waiting_for, "Signal");

        return;
    }

    // === MISE À JOUR ÉTATS DEPUIS INPUTS ===
    g_dashboard.bot_running = Input_Enabled.GetYesNo();
    g_es_state.enabled = Input_ES_Enabled.GetYesNo();
    g_nq_state.enabled = Input_NQ_Enabled.GetYesNo();
    g_es_state.paused = Input_ES_Paused.GetYesNo();
    g_nq_state.paused = Input_NQ_Paused.GetYesNo();

    // Heartbeat
    g_dashboard.last_heartbeat = sc.CurrentSystemDateTime;

    // 🔧 FIX: RÉINITIALISATION QUOTIDIENNE AMÉLIORÉE (avec persistance)
    int y, mo, d, h, mi, s;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(y, mo, d, h, mi, s);

    // Utiliser variable persistante au lieu de globale
    int& g_last_day_persistent = sc.GetPersistentInt(1);  // Index 1 pour g_last_day
    
    // 🔧 30/01/2026: FLAG SÉPARÉ pour initialisation PnL baseline (par chart!)
    // Index 2 = flag init pour ce chart spécifique
    int& pnl_baseline_initialized = sc.GetPersistentInt(2);
    
    // Reset si:
    // 1. Nouveau jour détecté (g_last_day != d)
    // 2. OU premier tick après recompilation (g_last_day == 0 ou -1)
    bool need_reset = (g_last_day_persistent > 0 && g_last_day_persistent != d);  // Nouveau jour
    bool first_tick_today = (g_last_day_persistent <= 0);  // Premier tick après recompilation

    // 🔧 30/01/2026: FIX BUG PnL FANTÔME!
    // Toujours initialiser last_processed_pnl au démarrage du study sur ce chart
    // AVANT le reset des stats, pour éviter de comptabiliser des trades anciens!
    if (pnl_baseline_initialized != d) {  // Pas encore init aujourd'hui sur ce chart
        s_SCPositionData init_posData;
        sc.GetTradePosition(init_posData);
        
        // Déterminer le symbole du chart (défini localement ici car pas encore déclaré)
        bool is_es_chart_local = (strstr(sc.GetChartSymbol(sc.ChartNumber), "ES") != NULL);
        
        if (is_es_chart_local) {
            g_es_state.last_processed_pnl = init_posData.LastTradeProfitLoss;
            sc.AddMessageToLog("🔧 ES: PnL baseline initialisee (ignore anciens trades)", 0);
        } else {
            g_nq_state.last_processed_pnl = init_posData.LastTradeProfitLoss;
            sc.AddMessageToLog("🔧 NQ: PnL baseline initialisee (ignore anciens trades)", 0);
        }
        pnl_baseline_initialized = d;  // Marquer comme initialisé aujourd'hui
    }

    if (need_reset || first_tick_today) {
        // Forcer reset des stats quotidiennes
        g_es_state.trades_today = 0;
        g_es_state.wins_today = 0;
        g_es_state.losses_today = 0;
        g_es_state.pnl_today = 0.0f;
        g_es_state.best_trade = 0.0f;
        g_es_state.worst_trade = 0.0f;
        g_es_state.consecutive_losses = 0;

        g_nq_state.trades_today = 0;
        g_nq_state.wins_today = 0;
        g_nq_state.losses_today = 0;
        g_nq_state.pnl_today = 0.0f;
        g_nq_state.best_trade = 0.0f;
        g_nq_state.worst_trade = 0.0f;
        g_nq_state.consecutive_losses = 0;

        g_dashboard.signals_rejected_es = 0;
        g_dashboard.signals_rejected_nq = 0;

        // 🆕 Reset trade WHY ID au début de journée
        g_trade_why_id = 1;

        if (need_reset) {
            sc.AddMessageToLog("🔄 NOUVEAU JOUR - Stats reinitialisees", 0);
        } else {
            sc.AddMessageToLog("🔄 PREMIER TICK DU JOUR - Stats initialisees a 0", 0);
        }
    }
    g_last_day_persistent = d;  // Sauvegarder le jour actuel (PERSISTANT)

    // === INITIALISER RAISONS ===
    strcpy(g_dashboard.bot_action_es, "Scanning...");
    strcpy(g_dashboard.bot_action_nq, "Scanning...");
    strcpy(g_dashboard.no_trade_reason_es, "");
    strcpy(g_dashboard.no_trade_reason_nq, "");

    // === VÉRIFICATIONS PRÉLIMINAIRES ===
    if (!g_dashboard.bot_running) {
        strcpy(g_dashboard.global_status, "BOT DISABLED");
        strcpy(g_dashboard.bot_action_es, "STOPPED");
        strcpy(g_dashboard.bot_action_nq, "STOPPED");
        strcpy(g_dashboard.no_trade_reason_es, "Bot desactive par l'utilisateur");
        strcpy(g_dashboard.no_trade_reason_nq, "Bot desactive par l'utilisateur");
        SaveDashboard(sc);
        DrawDashboardOnChart(sc);  // 🔧 FIX: Toujours dessiner le dashboard!
        return;
    }

    // 🆕 Lire le mode TEST/PRODUCTION
    int bot_mode = Input_Bot_Mode.GetInt();

    // Vérifier session (selon le mode)
    if (!IsWithinTradingSession(sc, bot_mode)) {
        if (bot_mode == MODE_TEST) {
            strcpy(g_dashboard.global_status, "HORS SESSION [TEST]");
            strcpy(g_dashboard.no_trade_reason_es, "Mode TEST - Hors horaires (00h00-23h00 FR)");
            strcpy(g_dashboard.no_trade_reason_nq, "Mode TEST - Hors horaires (00h00-23h00 FR)");
        } else {
            strcpy(g_dashboard.global_status, "HORS SESSION [PROD]");
            strcpy(g_dashboard.no_trade_reason_es, "Mode PROD - Hors horaires (02h30-21h00 FR)");
            strcpy(g_dashboard.no_trade_reason_nq, "Mode PROD - Hors horaires (02h30-21h00 FR)");
        }
        strcpy(g_dashboard.current_session, GetCurrentSessionName(sc));
        strcpy(g_dashboard.bot_action_es, "WAITING");
        strcpy(g_dashboard.bot_action_nq, "WAITING");
        SaveDashboard(sc);
        DrawDashboardOnChart(sc);  // 🔧 FIX: Toujours dessiner le dashboard!
        return;
    }

    // Afficher le mode actif dans le status
    if (bot_mode == MODE_TEST) {
        strcpy(g_dashboard.global_status, "🧪 RUNNING [TEST MODE]");
    } else {
        strcpy(g_dashboard.global_status, "🚀 RUNNING [PRODUCTION]");
    }

    strcpy(g_dashboard.current_session, GetCurrentSessionName(sc));
    // Note: global_status déjà défini ci-dessus avec le mode

    // === DÉTECTION ANNONCES (Spread écarté / DOM vide) ===
    // 🆕 DÉSACTIVÉ en MODE TEST pour éviter les faux positifs à l'ouverture
    if (bot_mode == MODE_PRODUCTION) {
        bool news_es = IsSpreadAbnormal(sc, CONFIG_ES) || IsDOMEmpty(sc, CONFIG_ES);
        bool news_nq = IsSpreadAbnormal(sc, CONFIG_NQ) || IsDOMEmpty(sc, CONFIG_NQ);

        if (news_es || news_nq) {
            g_dashboard.news_detected = true;
            strcpy(g_dashboard.news_message, "Spread/DOM anormal - possible annonce");

            // Bloquer trading 30 min
            SCDateTime block_until = sc.CurrentSystemDateTime;
            block_until += SCDateTime::MINUTES(NEWS_BLOCK_MINUTES);

            if (news_es) {
                g_es_state.news_block_until = block_until;
                strcpy(g_dashboard.bot_action_es, "NEWS BLOCK");
                strcpy(g_dashboard.no_trade_reason_es, "SPREAD ECARTE/DOM VIDE - Annonce detectee! Block 30 min");
            }
            if (news_nq) {
                g_nq_state.news_block_until = block_until;
                strcpy(g_dashboard.bot_action_nq, "NEWS BLOCK");
                strcpy(g_dashboard.no_trade_reason_nq, "SPREAD ECARTE/DOM VIDE - Annonce detectee! Block 30 min");
            }
        } else {
            g_dashboard.news_detected = false;
            g_dashboard.news_message[0] = '\0';
        }
    } else {
        // MODE TEST: Pas de détection d'annonces - on trade quand même
        g_dashboard.news_detected = false;
        g_dashboard.news_message[0] = '\0';
        // Reset les blocks s'ils existaient
        g_es_state.news_block_until = SCDateTime(0);
        g_nq_state.news_block_until = SCDateTime(0);
    }

    // === COLLECTER DONNÉES ===
    BN_Data bn_es, bn_nq;
    MenthorQ_Data mq_es, mq_nq;

    CollectBN_Data(sc, Input_ES_Footprint_Chart.GetInt(), Input_ES_Barres_Chart.GetInt(), bn_es, false);
    CollectBN_Data(sc, Input_NQ_Footprint_Chart.GetInt(), Input_NQ_Barres_Chart.GetInt(), bn_nq, true);
    CollectMenthorQ_Data(sc, Input_ES_Main_Chart.GetInt(), mq_es, false);  // ES
    CollectMenthorQ_Data(sc, Input_NQ_Main_Chart.GetInt(), mq_nq, true);   // NQ

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 25/01/2026: METTRE À JOUR LES TRACKERS D'EXTENSION LINES PERSISTANTS
    // Les Extension Lines sont trackées entre les snapshots pour:
    // - Détecter quand le prix revient vers une ligne créée il y a longtemps
    // - Placer les SL/TP de manière intelligente
    // ═══════════════════════════════════════════════════════════════════════════
    float current_price_for_tracker = sc.Close[sc.ArraySize - 1];
    SCDateTime current_ts_for_tracker = sc.CurrentSystemDateTime;
    
    UpdateExtensionLinesTracker(g_ext_tracker_es, bn_es, current_price_for_tracker, 
                                current_ts_for_tracker, CONFIG_ES.tick_size);
    UpdateExtensionLinesTracker(g_ext_tracker_nq, bn_nq, current_price_for_tracker, 
                                current_ts_for_tracker, CONFIG_NQ.tick_size);

    // 🆕 Collecter données marché LIVE (VIX, ATR Daily, VWAP Slope)
    CollectMarketLiveData(
        sc,
        Input_VIX_Chart.GetInt(),
        Input_ES_Daily_Chart.GetInt(),
        Input_NQ_Daily_Chart.GetInt(),
        Input_ES_Barres_Chart.GetInt(),
        Input_NQ_Barres_Chart.GetInt()
    );

    // 🆕 27/01/2026: DIAGNOSTIC SNAPSHOT - Exporte toutes les données toutes les 5 secondes
    // Fichier: D:\MIA_IA_system\DIAGNOSTIC_SNAPSHOT.json
    static SCDateTime last_diagnostic_time = 0;
    if (sc.CurrentSystemDateTime - last_diagnostic_time >= SCDateTime::SECONDS(5)) {
        // 🔧 FIX: Lire les prix depuis leurs charts respectifs (pas depuis sc.Close qui est le chart attaché)
        float price_es = 0;
        float price_nq = 0;
        
        // Lire prix ES depuis son chart
        SCGraphData es_chart_data;
        sc.GetChartBaseData(Input_ES_Main_Chart.GetInt(), es_chart_data);
        if (es_chart_data[SC_LAST].GetArraySize() > 0) {
            price_es = es_chart_data[SC_LAST][es_chart_data[SC_LAST].GetArraySize() - 1];
        }
        
        // Lire prix NQ depuis son chart
        SCGraphData nq_chart_data;
        sc.GetChartBaseData(Input_NQ_Main_Chart.GetInt(), nq_chart_data);
        if (nq_chart_data[SC_LAST].GetArraySize() > 0) {
            price_nq = nq_chart_data[SC_LAST][nq_chart_data[SC_LAST].GetArraySize() - 1];
        }
        
        WriteDiagnosticSnapshot(sc, bn_es, bn_nq, mq_es, mq_nq, price_es, price_nq);
        last_diagnostic_time = sc.CurrentSystemDateTime;
    }

    // Utiliser données live
    float vix = g_market_live.vix;
    float atr_es = g_market_live.atr_es > 0 ? g_market_live.atr_es : 15.0f;  // Fallback 15 pts
    float atr_nq = g_market_live.atr_nq > 0 ? g_market_live.atr_nq : 300.0f; // Fallback 300 pts

    // 🔧 FIX 27/01/2026: Lire les prix depuis leurs charts respectifs
    float current_price_es = 0;
    float current_price_nq = 0;
    
    // Prix ES depuis son chart
    SCGraphData es_price_data;
    sc.GetChartBaseData(Input_ES_Main_Chart.GetInt(), es_price_data);
    if (es_price_data[SC_LAST].GetArraySize() > 0) {
        current_price_es = es_price_data[SC_LAST][es_price_data[SC_LAST].GetArraySize() - 1];
    }
    
    // Prix NQ depuis son chart
    SCGraphData nq_price_data;
    sc.GetChartBaseData(Input_NQ_Main_Chart.GetInt(), nq_price_data);
    if (nq_price_data[SC_LAST].GetArraySize() > 0) {
        current_price_nq = nq_price_data[SC_LAST][nq_price_data[SC_LAST].GetArraySize() - 1];
    }

    // === CALCULER NEXT_WALL (PARITÉ PYTHON) ===
    CalculateNextWall(mq_es, current_price_es);
    CalculateNextWall(mq_nq, current_price_nq);

    // === VERIFICATIONS ORDRES/POSITIONS ===
    // Determiner symbole du chart actuel
    bool is_es_chart = (strstr(sc.GetChartSymbol(sc.ChartNumber), "ES") != NULL);
    BotState& active_state = is_es_chart ? g_es_state : g_nq_state;
    const SymbolConfig& active_config = is_es_chart ? CONFIG_ES : CONFIG_NQ;

    // ═══════════════════════════════════════════════════════════════════════════
    // SYNCHRONISATION AUTOMATIQUE DES POSITIONS EXISTANTES
    // (detecte les positions ouvertes manuellement ou via SimpleBracket)
    // ═══════════════════════════════════════════════════════════════════════════
    s_SCPositionData posData;
    sc.GetTradePosition(posData);

    // 🔧 27/01/2026: Ne PAS sync si le bot a un ordre en attente (c'est notre propre trade!)
    if (is_es_chart && !g_es_state.in_position && posData.PositionQuantity != 0 
        && g_es_state.parent_order_id == 0) {  // ← AJOUT: Pas d'ordre en cours
        // Position ES detectee mais pas trackee par le bot (vraiment externe)
        g_es_state.in_position = true;
        g_es_state.entry_price = posData.AveragePrice;
        g_es_state.position_direction = (posData.PositionQuantity > 0) ? 1 : -1;
        g_es_state.trailing_activated = false;
        g_es_state.break_even_activated = false;
        g_es_state.trailing_sl = 0;
        g_es_state.entry_time = sc.CurrentSystemDateTime;
        snprintf(g_es_state.status_message, sizeof(g_es_state.status_message),
                 "[SYNC] Position ES detectee: %s @ %.2f",
                 g_es_state.position_direction == 1 ? "LONG" : "SHORT",
                 g_es_state.entry_price);
        sc.AddMessageToLog(g_es_state.status_message, 0);
        LogSyncPosition(sc, "ES", g_es_state.position_direction, g_es_state.entry_price);
    }

    // 🔧 27/01/2026: Ne PAS sync si le bot a un ordre en attente (c'est notre propre trade!)
    if (!is_es_chart && !g_nq_state.in_position && posData.PositionQuantity != 0
        && g_nq_state.parent_order_id == 0) {  // ← AJOUT: Pas d'ordre en cours
        // Position NQ detectee mais pas trackee par le bot (vraiment externe)
        g_nq_state.in_position = true;
        g_nq_state.entry_price = posData.AveragePrice;
        g_nq_state.position_direction = (posData.PositionQuantity > 0) ? 1 : -1;
        g_nq_state.trailing_activated = false;
        g_nq_state.break_even_activated = false;
        g_nq_state.trailing_sl = 0;
        g_nq_state.entry_time = sc.CurrentSystemDateTime;
        snprintf(g_nq_state.status_message, sizeof(g_nq_state.status_message),
                 "[SYNC] Position NQ detectee: %s @ %.2f",
                 g_nq_state.position_direction == 1 ? "LONG" : "SHORT",
                 g_nq_state.entry_price);
        sc.AddMessageToLog(g_nq_state.status_message, 0);
        LogSyncPosition(sc, "NQ", g_nq_state.position_direction, g_nq_state.entry_price);
    }
    // ═══════════════════════════════════════════════════════════════════════════

    // Verifier si ordre LIMIT execute
    CheckOrderFilled(sc, active_state, active_config);

    // Vérifier timeout ordres LIMIT (60 sec)
    CheckOrderTimeout(sc, active_state);

    // ═══════════════════════════════════════════════════════════════════════════
    // VÉRIFICATION FERMETURE POSITION (SIMPLIFIÉ ET ROBUSTE)
    // ═══════════════════════════════════════════════════════════════════════════
    // GetTradePosition() retourne la position du symbole du chart actuel
    // Donc on vérifie uniquement le symbole correspondant au chart actif
    
    // 🔧 28/01/2026: DÉTECTER AUSSI LES TRADES MANUELS!
    // Même si in_position == false, on surveiller LastTradeProfitLoss
    // pour comptabiliser les trades manuels dans le dashboard
    // Note: posData déjà déclaré ligne 7358 pour SYNC
    
    if (is_es_chart) {
        // ES: Vérifier position bot
        if (g_es_state.in_position) {
            ProcessPositionClosed(sc, g_es_state, CONFIG_ES);
        } 
        // 🆕 ES: Détecter trades manuels
        else if (posData.PositionQuantity == 0 && 
                 fabs(posData.LastTradeProfitLoss) > 0.01f &&
                 fabs(posData.LastTradeProfitLoss - g_es_state.last_processed_pnl) > 0.01f) {
            // Trade manuel ES fermé → ajouter au PNL
            float manual_pnl = posData.LastTradeProfitLoss;
            g_es_state.pnl_today += manual_pnl;
            g_es_state.trades_today++;
            if (manual_pnl >= 0) {
                g_es_state.wins_today++;
                if (manual_pnl > g_es_state.best_trade) g_es_state.best_trade = manual_pnl;
            } else {
                g_es_state.losses_today++;
                if (manual_pnl < g_es_state.worst_trade) g_es_state.worst_trade = manual_pnl;
            }
            
            // Tracker ce PNL pour ne pas le recompter
            g_es_state.last_processed_pnl = manual_pnl;
            
            char msg[128];
            snprintf(msg, sizeof(msg), "💰 ES MANUEL: $%.2f → PnL Today: $%.2f", 
                     manual_pnl, g_es_state.pnl_today);
            sc.AddMessageToLog(msg, 0);
        }
    }
    
    if (!is_es_chart) {
        // NQ: Vérifier position bot
        if (g_nq_state.in_position) {
            ProcessPositionClosed(sc, g_nq_state, CONFIG_NQ);
        }
        // 🆕 NQ: Détecter trades manuels
        else if (posData.PositionQuantity == 0 && 
                 fabs(posData.LastTradeProfitLoss) > 0.01f &&
                 fabs(posData.LastTradeProfitLoss - g_nq_state.last_processed_pnl) > 0.01f) {
            // Trade manuel NQ fermé → ajouter au PNL
            float manual_pnl = posData.LastTradeProfitLoss;
            g_nq_state.pnl_today += manual_pnl;
            g_nq_state.trades_today++;
            if (manual_pnl >= 0) {
                g_nq_state.wins_today++;
                if (manual_pnl > g_nq_state.best_trade) g_nq_state.best_trade = manual_pnl;
            } else {
                g_nq_state.losses_today++;
                if (manual_pnl < g_nq_state.worst_trade) g_nq_state.worst_trade = manual_pnl;
            }
            
            // Tracker ce PNL pour ne pas le recompter
            g_nq_state.last_processed_pnl = manual_pnl;
            
            char msg[128];
            snprintf(msg, sizeof(msg), "💰 NQ MANUEL: $%.2f → PnL Today: $%.2f", 
                     manual_pnl, g_nq_state.pnl_today);
            sc.AddMessageToLog(msg, 0);
        }
    }

    // === TRAITEMENT ES ===
    if (!g_es_state.enabled) {
        strcpy(g_dashboard.bot_action_es, "DISABLED");
        strcpy(g_dashboard.no_trade_reason_es, "ES desactive dans les inputs");
    } else if (g_es_state.paused) {
        strcpy(g_dashboard.bot_action_es, "PAUSED");
        strcpy(g_dashboard.no_trade_reason_es, "ES en pause manuelle");
    } else if (g_es_state.in_position) {
        strcpy(g_dashboard.bot_action_es, "IN POSITION");
        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                 "Position ouverte: %s @ %.2f",
                 g_es_state.position_direction == 1 ? "LONG" : "SHORT",
                 g_es_state.entry_price);
        UpdateTrailingStop(sc, g_es_state, CONFIG_ES, current_price_es);  // 🔧 27/01: Utiliser prix ES correct
    } else {
        // Vérifier cooldowns
        bool can_trade = true;

        if (sc.CurrentSystemDateTime < g_es_state.cooldown_until) {
            can_trade = false;
            strcpy(g_es_state.waiting_for, "Cooldown");
            strcpy(g_dashboard.bot_action_es, "COOLDOWN");
            strcpy(g_dashboard.no_trade_reason_es, "En cooldown apres trade precedent");
        }
        if (sc.CurrentSystemDateTime < g_es_state.news_block_until) {
            can_trade = false;
            strcpy(g_es_state.waiting_for, "News block");
            strcpy(g_dashboard.bot_action_es, "NEWS BLOCK");
            strcpy(g_dashboard.no_trade_reason_es, "SPREAD ECARTE - Bloque 30 min suite annonce");
        }

        if (can_trade) {
            strcpy(g_dashboard.bot_action_es, "SCANNING");
            strcpy(g_dashboard.no_trade_reason_es, "En attente d'opportunite...");

            // === VETO FLAT: slope < seuil = NO TRADE (sauf exception desequilibre) ===
            // 🔧 27/01/2026: Seuil adaptatif par session
            // - Asia: 0.005 (plus permissif, volume faible = slope naturellement bas)
            // - London/US: 0.01 (standard)
            float vwap_slope_es = g_market_live.vwap_slope_es;
            bool is_asia_es = (strcmp(g_dashboard.current_session, "Asia") == 0);
            float flat_threshold_es = is_asia_es ? 0.005f : 0.01f;
            bool is_flat_es = (fabs(vwap_slope_es) < flat_threshold_es);

            if (is_flat_es) {
                // Exception DESEQUILIBRE: FLAT mais d_vwap > 15 ticks = OK
                float d_vwap_es = fabs(current_price_es - mq_es.vwap);
                float d_vwap_ticks_es = d_vwap_es / CONFIG_ES.tick_size;

                if (d_vwap_ticks_es <= 15.0f) {
                    // VETO - FLAT sans desequilibre
                    strcpy(g_dashboard.bot_action_es, "FLAT VETO");
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                             "VWAP FLAT (slope=%.4f < %.3f) - d_vwap=%.0ft <= 15t", vwap_slope_es, flat_threshold_es, d_vwap_ticks_es);
                    can_trade = false;
                }
                // Si d_vwap > 15t → on laisse passer (desequilibre = retour VWAP probable)
            }

            if (!can_trade) {
                // Skip to next iteration (FLAT VETO applied)
            } else {
            // === LAYER 1 (MenthorQ) ===
            Layer1Result l1 = ValidateLayer1(sc, mq_es, current_price_es, CONFIG_ES, bn_es.momentum_score, &bn_es, true);

            // === LAYER 1B (Rectangles) - Alternative si L1 échoue ===
            RectangleSignal rect_signal = {false, 0, 0, 0, 0, ""};
            bool rectangle_trading_enabled = Input_Rectangle_Trading.GetYesNo();
            if (!l1.passed && rectangle_trading_enabled) {
                rect_signal = DetectRectangleConfluence(sc, bn_es, mq_es, current_price_es, CONFIG_ES, false);
                if (rect_signal.has_signal) {
                    // Convertir en Layer1Result pour compatibilité
                    l1.passed = true;
                    l1.direction = rect_signal.direction;
                    l1.confidence = rect_signal.confidence;
                    l1.level_price = rect_signal.rectangle_price;
                    l1.distance_ticks = 0;  // Rectangle = contact direct
                    strncpy(l1.level_name, rect_signal.reason, sizeof(l1.level_name) - 1);
                }
            }

            if (!l1.passed) {
                // Message détaillé: MenthorQ + Rectangles
                if (rectangle_trading_enabled) {
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                        "L1: MQ=NON, RECT=NON (ColorUp=%.0f ColorDn=%.0f LongDnUp=%.0f)",
                        bn_es.color_up, bn_es.color_down, bn_es.long_down_up);
                } else {
                    strcpy(g_dashboard.no_trade_reason_es, "L1: Pas de niveau MenthorQ proche (RECT desactive)");
                }
            } else {
                int direction = l1.direction;

                // === LAYER 2 === 🔧 OPTIMISÉ 25/01/2026
                // Calculer depth_imbalance depuis DOM
                float depth_imbalance_es = 0.0f;
                s_MarketDepthEntry bid_entry, ask_entry;
                sc.GetBidMarketDepthEntryAtLevel(bid_entry, 0);
                sc.GetAskMarketDepthEntryAtLevel(ask_entry, 0);
                int total_dom = bid_entry.Quantity + ask_entry.Quantity;
                if (total_dom > 0) {
                    depth_imbalance_es = (float)(bid_entry.Quantity - ask_entry.Quantity) / total_dom;
                }
                
                // 🔧 30/01/2026: Utiliser FPBS (Order Flow réel) NORMALISÉ
                // Note: fpbs_bid_pct/ask_pct de Sierra ne sont PAS normalisés à 1.0
                // On doit normaliser: buy_pct = fpbs_bid / (fpbs_bid + fpbs_ask)
                float buy_pct_es, sell_pct_es;
                float fpbs_total_es = bn_es.fpbs_bid_pct + bn_es.fpbs_ask_pct;
                if (fpbs_total_es > 0.001f) {
                    // Normaliser les données FPBS pour obtenir de vrais pourcentages
                    buy_pct_es = bn_es.fpbs_bid_pct / fpbs_total_es;
                    sell_pct_es = bn_es.fpbs_ask_pct / fpbs_total_es;
                } else {
                    // Fallback sur color_up/down si FPBS indisponible
                    buy_pct_es = (bn_es.color_up > 0) ? 
                        bn_es.color_up / (bn_es.color_up + bn_es.color_down + 0.001f) : 0.5f;
                    sell_pct_es = 1.0f - buy_pct_es;
                }
                
                // VWAP slope
                float vwap_slope_es = g_market_live.vwap_slope_es;
                
                Layer2Result l2 = ValidateLayer2(direction, bn_es, bn_nq, vix,
                                                  0, buy_pct_es, CONFIG_ES, false,
                                                  depth_imbalance_es, sell_pct_es, vwap_slope_es);

                if (!l2.passed) {
                    snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                             "L2: %s", l2.reason);
                    snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                             "L2 REJETE: BN=%.2f %s", l2.bn_score, l2.reason);
                    g_dashboard.signals_rejected_es++;
                    // 🆕 LOG REJET POUR ANALYSE
                    LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L2",
                                     l2.reason, current_price_es, l1.level_price, l1.distance_ticks,
                                     vix, l2.bn_score);
                } else {
                    // === LAYER 3 ===
                    Layer3Result l3 = ValidateLayer3(direction, bn_es, current_price_es,
                                                      mq_es, vix, atr_es,
                                                      g_dashboard.current_session, false);  // ES

                    if (l3.veto) {
                        snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                 "L3 VETO: %s", l3.veto_reason);
                        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                 "L3 VETO: %s", l3.veto_reason);
                        g_dashboard.signals_rejected_es++;
                        // 🆕 LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3_VETO",
                                         l3.veto_reason, current_price_es, l1.level_price, l1.distance_ticks,
                                         vix, bn_es.score);
                    } else if (!l3.passed) {
                        snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                 "L3: Context=%.2f trop bas", l3.confidence);
                        snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                 "L3 REJETE: Contexte defavorable %s", l3.context);
                        g_dashboard.signals_rejected_es++;
                        // 🆕 LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3",
                                         l3.context, current_price_es, l1.level_price, l1.distance_ticks,
                                         vix, bn_es.score);
                    } else {
                        // === LAYER 4 (V54: 2 REGLES BACKTEST, 1/2 REQUIS) ===
                        // 🔧 25/01/2026: Nouvelles règles validées par backtest rigoureux
                        
                        // Calcul buy_pct depuis BN_Data (signals acheteurs vs vendeurs)
                        float buyer_signals_es = bn_es.color_up + bn_es.rotation_up + bn_es.edge_buy + bn_es.absorb_bid;
                        float seller_signals_es = bn_es.color_down + bn_es.rotation_down + bn_es.edge_sell + bn_es.absorb_ask;
                        float total_signals_es = buyer_signals_es + seller_signals_es;
                        float buy_pct_es = (total_signals_es > 0) ? (buyer_signals_es / total_signals_es) : 0.5f;
                        float sell_pct_es = 1.0f - buy_pct_es;

                        // Edge Buy/Sell pour Edge Dominant
                        float edge_buy_es = bn_es.edge_buy + bn_es.bar_edge_buy;
                        float edge_sell_es = bn_es.edge_sell + bn_es.bar_edge_sell;

                        // Calcul cum_delta proxy depuis rotation (momentum)
                        float cum_delta_proxy_es = bn_es.rotation_up - bn_es.rotation_down;

                        Layer4Result l4 = ValidateLayer4(direction, buy_pct_es, sell_pct_es, 
                                                         edge_buy_es, edge_sell_es,
                                                         cum_delta_proxy_es, bn_es.score,
                                                         g_market_live.vwap_slope_es, CONFIG_ES);

                        if (!l4.passed) {
                            snprintf(g_dashboard.last_rejected_es, sizeof(g_dashboard.last_rejected_es),
                                     "L4: Combo %d/2 < 1/2", l4.combo_aligned);
                            snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                     "L4 REJETE: Combo %d/2 (pct52=%d,edge=%d)",
                                     l4.combo_aligned, l4.pct_ok, l4.edge_ok);
                            g_dashboard.signals_rejected_es++;
                            char l4_reason[64];
                            snprintf(l4_reason, sizeof(l4_reason), "Combo %d/2 < 1/2 required", l4.combo_aligned);
                            LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L4",
                                             l4_reason, current_price_es, l1.level_price, l1.distance_ticks,
                                             vix, bn_es.score);
                        } else {
                            // ═══════════════════════════════════════════════════════════════
                            // 🎯 26/01/2026: QUICK WIN #1 - SEUILS MINIMUM "SWEET SPOT"
                            // Rejeter les 20% signaux les plus faibles (basé sur analyse réelle)
                            // ═══════════════════════════════════════════════════════════════
                            
                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 27/01/2026: FILTRES RENFORCÉS - "MEILLEURS SETUPS ONLY"
                            // Problème identifié: trades à 13% L3 et 41% L2 = MAUVAIS!
                            // Nouveau: exiger des signaux de QUALITÉ pas juste "passables"
                            // ═══════════════════════════════════════════════════════════════
                            
                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 27/01/2026 16h: SEUILS ÉQUILIBRÉS (ni trop strict ni trop lax)
                            // Analyse des rejets: L2=40% et L3=12% rejetés = trop strict!
                            // ═══════════════════════════════════════════════════════════════
                            float min_l1_conf_es = 0.35f;  // ES: 35% minimum (était 38%)
                            float min_l2_conf_es = 0.38f;  // ES: 38% minimum (était 45% = trop strict!)
                            float min_l3_conf_es = 0.14f;  // ES: 14% minimum (était 18% = trop strict!)
                            float min_confluence_es = 0.42f;  // Confluence globale: 42% min (était 50%)
                            
                            // Calcul confluence globale
                            float overall_conf_es = (l1.confidence + l2.confidence + l3.confidence + bn_es.score) / 4.0f;
                            
                            if (l1.confidence < min_l1_conf_es) {
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L1 REJET: Conf=%.1f%% < %.0f%% (signal trop faible)", 
                                         l1.confidence * 100, min_l1_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L1_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price, 
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (l2.confidence < min_l2_conf_es) {
                                // 🆕 27/01/2026: Nouveau filtre L2!
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L2 REJET: Conf=%.1f%% < %.0f%% (BN/corrélation trop faible)", 
                                         l2.confidence * 100, min_l2_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L2_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (l3.confidence < min_l3_conf_es) {
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "L3 REJET: Conf=%.1f%% < %.0f%% (contexte trop faible)", 
                                         l3.confidence * 100, min_l3_conf_es * 100);
                                g_dashboard.signals_rejected_es++;
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "L3_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (bn_es.score < 0.40f) {  // BN: 40% minimum
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "BN REJET: Score=%.1f%% < 40%% (BN trop faible)", bn_es.score * 100);
                                g_dashboard.signals_rejected_es++;
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "BN_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else if (overall_conf_es < min_confluence_es) {
                                // 🆕 27/01/2026: Nouveau filtre confluence globale!
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "CONF REJET: Global=%.1f%% < %.0f%% (L1=%.0f L2=%.0f L3=%.0f BN=%.0f)", 
                                         overall_conf_es * 100, min_confluence_es * 100,
                                         l1.confidence * 100, l2.confidence * 100, 
                                         l3.confidence * 100, bn_es.score * 100);
                                g_dashboard.signals_rejected_es++;
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT", "CONF_MIN",
                                                 g_dashboard.no_trade_reason_es, current_price_es, l1.level_price,
                                                 l1.distance_ticks, vix, bn_es.score);
                            } else {
                            // 🎯 26/01/2026: QUICK WIN #2 - RECTANGLE BONUS +5%
                            // Rectangles ont 70% WR vs 50% boules (analyse trades réels)
                            float l1_confidence_bonus = l1.confidence;
                            bool has_rectangle_es = (direction == 1) ? 
                                (bn_es.price_in_edge_rect_buy || bn_es.num_edge_rect_buy > 0) :
                                (bn_es.price_in_edge_rect_sell || bn_es.num_edge_rect_sell > 0);
                            
                            if (has_rectangle_es) {
                                l1_confidence_bonus *= 1.05f;  // +5% bonus zones institutionnelles
                            }
                            
                            // === SIGNAL VALIDÉ - VERIFIER R:R ===
                            // 🆕 25/01/2026: Passer le tracker persistant pour SL/TP intelligent
                            SLTPResult sltp = CalculateProtectedSLTP(direction, current_price_es, mq_es, bn_es, CONFIG_ES, &g_ext_tracker_es);

                            // 🆕 VETO si obstacle bloque le R:R
                            if (!sltp.is_valid) {
                                strcpy(g_dashboard.bot_action_es, "VETO_RR");
                                snprintf(g_dashboard.no_trade_reason_es, sizeof(g_dashboard.no_trade_reason_es),
                                         "ES: %s", sltp.tp_based_on);
                                LogRejectedSignal(sc, CONFIG_ES, direction == 1 ? "LONG" : "SHORT",
                                                  "SLTP", sltp.tp_based_on, current_price_es, 0, 0, vix, bn_es.score);
                            } else {

                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 28/01/2026: HARD LIMIT SL/TP - TOUJOURS APPLIQUER!
                            // Bug: SL/TP trop loin sans limiter!
                            // ═══════════════════════════════════════════════════════════════
                            float tick_size_es = CONFIG_ES.tick_size;
                            float max_sl_dist_es = CONFIG_ES.sl_max_ticks * tick_size_es;
                            float max_tp_dist_es = CONFIG_ES.tp_max_ticks * tick_size_es;
                            float current_sl_dist_es = fabs(sltp.sl_price - current_price_es);
                            float current_tp_dist_es = fabs(sltp.tp_price - current_price_es);
                            
                            // FORCER SL max
                            if (current_sl_dist_es > max_sl_dist_es) {
                                if (direction == 1) {
                                    sltp.sl_price = current_price_es - max_sl_dist_es;
                                } else {
                                    sltp.sl_price = current_price_es + max_sl_dist_es;
                                }
                                sltp.sl_ticks = CONFIG_ES.sl_max_ticks;
                                strncpy(sltp.sl_based_on, "MAX_HARD_LIMIT", sizeof(sltp.sl_based_on));
                            }
                            
                            // FORCER TP max
                            if (current_tp_dist_es > max_tp_dist_es) {
                                if (direction == 1) {
                                    sltp.tp_price = current_price_es + max_tp_dist_es;
                                } else {
                                    sltp.tp_price = current_price_es - max_tp_dist_es;
                                }
                                sltp.tp_ticks = CONFIG_ES.tp_max_ticks;
                                strncpy(sltp.tp_based_on, "MAX_HARD_LIMIT", sizeof(sltp.tp_based_on));
                            }

                            // ═══════════════════════════════════════════════════════════════
                            // 🆕 DÉTECTION TRADE HAUTE QUALITÉ (risque augmenté)
                            // ═══════════════════════════════════════════════════════════════
                            int visual_count_es = 0;
                            if (bn_es.edge_buy > 0 || bn_es.edge_sell > 0) visual_count_es++;
                            if (bn_es.color_up > 10 || bn_es.color_down > 10) visual_count_es++;
                            if (bn_es.long_down_up > 0 || bn_es.long_up_down > 0) visual_count_es++;
                            if (bn_es.num_edge_rect_buy > 0 || bn_es.num_edge_rect_sell > 0) visual_count_es++;
                            if (bn_es.absorb_bid > 0 || bn_es.absorb_ask > 0) visual_count_es++;

                            HighQualityResult hq_es = DetectHighQualityTrade(
                                direction, bn_es, l1.importance_score,
                                visual_count_es, !sltp.is_valid
                            );

                            // Appliquer les multiplicateurs HQ si trade haute qualité
                            if (hq_es.is_high_quality) {
                                float tick_size_es = CONFIG_ES.tick_size;
                                float old_tp = sltp.tp_price;
                                float old_sl = sltp.sl_price;

                                // TP plus ambitieux
                                float tp_distance = fabs(sltp.tp_price - current_price_es);
                                tp_distance *= hq_es.tp_multiplier;
                                if (direction == 1) {
                                    sltp.tp_price = current_price_es + tp_distance;
                                } else {
                                    sltp.tp_price = current_price_es - tp_distance;
                                }

                                // SL légèrement plus large
                                float sl_distance = fabs(sltp.sl_price - current_price_es);
                                sl_distance *= hq_es.sl_multiplier;
                                if (direction == 1) {
                                    sltp.sl_price = current_price_es - sl_distance;
                                } else {
                                    sltp.sl_price = current_price_es + sl_distance;
                                }

                                // Limiter SL max
                                if (fabs(sltp.sl_price - current_price_es) > CONFIG_ES.sl_max_ticks * tick_size_es) {
                                    if (direction == 1) {
                                        sltp.sl_price = current_price_es - CONFIG_ES.sl_max_ticks * tick_size_es;
                                    } else {
                                        sltp.sl_price = current_price_es + CONFIG_ES.sl_max_ticks * tick_size_es;
                                    }
                                }

                                // 🔧 28/01/2026: FIX - Limiter TP max APRÈS HQ aussi!
                                // Bug: TP pouvait dépasser tp_max_ticks après multiplicateur HQ
                                if (fabs(sltp.tp_price - current_price_es) > CONFIG_ES.tp_max_ticks * tick_size_es) {
                                    if (direction == 1) {
                                        sltp.tp_price = current_price_es + CONFIG_ES.tp_max_ticks * tick_size_es;
                                    } else {
                                        sltp.tp_price = current_price_es - CONFIG_ES.tp_max_ticks * tick_size_es;
                                    }
                                }

                                // Recalculer ticks
                                sltp.tp_ticks = (int)(fabs(sltp.tp_price - current_price_es) / tick_size_es);
                                sltp.sl_ticks = (int)(fabs(sltp.sl_price - current_price_es) / tick_size_es);

                                // Log HQ
                                sc.AddMessageToLog(hq_es.reason, 0);
                            }

                            // 🆕 Calculer ancre BN avant d'entrer
                            float bn_anchor_es = CalculateBNAnchor(direction, current_price_es, bn_es, CONFIG_ES.tick_size);

                            // 🆕 Stocker données Discord pour notification
                            g_es_state.discord_bn_score = bn_es.score;
                            g_es_state.discord_l1_conf = l1.confidence;
                            g_es_state.discord_l2_conf = l2.confidence;
                            g_es_state.discord_l3_conf = l3.confidence;
                            g_es_state.discord_l4_combo = l4.combo_aligned;
                            g_es_state.discord_vwap_slope = g_market_live.vwap_slope_es;
                            g_es_state.discord_is_rectangle = rect_signal.has_signal;

                            // 🆕 TRADE WHY JOURNAL - Log avant envoi ordre
                            TradeWhy why = {0};
                            why.trade_id = g_trade_why_id++;
                            why.timestamp = sc.CurrentSystemDateTime;
                            strncpy(why.symbol, "ES", sizeof(why.symbol) - 1);
                            strncpy(why.side, direction == 1 ? "LONG" : "SHORT", sizeof(why.side) - 1);
                            strncpy(why.execution_mode, "PENDING", sizeof(why.execution_mode) - 1);  // Sera mis à jour après SendBracketOrder

                            // Trigger level
                            if (rect_signal.has_signal) {
                                strncpy(why.trigger_level_type, "RECT", sizeof(why.trigger_level_type) - 1);
                                why.trigger_level_price = rect_signal.rectangle_price;
                            } else {
                                strncpy(why.trigger_level_type, l1.level_name, sizeof(why.trigger_level_type) - 1);
                                why.trigger_level_price = l1.level_price;
                            }

                            // Anchor
                            why.anchor_final = bn_anchor_es > 0 ? bn_anchor_es : current_price_es;
                            why.anchor_ext = (bn_es.num_ext_support > 0 || bn_es.num_ext_resist > 0) ? why.anchor_final : 0;
                            why.anchor_color = 0;  // TODO: extraire depuis extension lines si besoin
                            why.dist_ticks_to_anchor = fabs(current_price_es - why.anchor_final) / CONFIG_ES.tick_size;

                            // Trade info
                            why.entry_price = current_price_es;
                            why.sl_price = sltp.sl_price;
                            why.tp_price = sltp.tp_price;
                            why.qty = 1;

                            // Layers
                            why.l1_ok = l1.passed ? 1 : 0;
                            why.l2_ok = l2.passed ? 1 : 0;
                            why.l3_ok = l3.passed ? 1 : 0;
                            why.l4_ok = l4.passed ? 1 : 0;
                            why.l1_confidence = l1.confidence;
                            why.l2_confidence = l2.confidence;
                            why.l3_confidence = l3.confidence;
                            why.l4_combo = l4.combo_aligned;
                            why.bn_score = bn_es.score;
                            why.confluence_score = l2.confidence;  // Approximatif
                            why.is_rectangle = rect_signal.has_signal;

                            // Contexte marché
                            why.vwap_slope = g_market_live.vwap_slope_es;
                            why.vwap_dist_ticks = fabs(current_price_es - mq_es.vwap) / CONFIG_ES.tick_size;
                            why.vix_value = vix;
                            strncpy(why.vix_regime, GetVIXRegimeName(g_market_live.vix_regime), sizeof(why.vix_regime) - 1);
                            why.dom_healthy = 1;  // TODO: vérifier DOM health
                            why.spread_ticks = 1.0f;  // TODO: récupérer spread réel

                            // Veto
                            why.veto_triggered = 0;
                            why.veto_reason[0] = '\0';
                            why.layer_reject_reason[0] = '\0';

                            // Notes
                            snprintf(why.notes, sizeof(why.notes), "L1:%s L4:%d/4", l1.level_name, l4.combo_aligned);

                            // Log avant envoi (execution_mode sera mis à jour après)
                            LogTradeWhy(sc, why, CONFIG_ES);

                            strcpy(g_dashboard.bot_action_es, "ENTERING");
                            strcpy(g_dashboard.no_trade_reason_es, "SIGNAL VALIDE - Entree en cours!");

                            // Envoyer ordre (va déterminer execution_mode)
                            bool order_sent = SendBracketOrder(sc, direction, current_price_es,
                                           sltp.sl_price, sltp.tp_price, g_es_state, bn_anchor_es);

                            // 🆕 Mettre à jour execution_mode dans TradeWhy
                            if (order_sent) {
                                // Déterminer mode depuis l'état (pending_limit_order indique LIMIT)
                                if (g_es_state.pending_limit_order) {
                                    strncpy(why.execution_mode, "PENDING_LIMIT", sizeof(why.execution_mode) - 1);
                                } else {
                                    strncpy(why.execution_mode, "IMMEDIATE", sizeof(why.execution_mode) - 1);
                                }
                            } else {
                                strncpy(why.execution_mode, "SKIP_TOO_FAR", sizeof(why.execution_mode) - 1);
                            }

                            // Log final avec le bon mode
                            if (order_sent) {
                                LogTradeWhy(sc, why, CONFIG_ES);
                            }

                            // 🆕 Mettre à jour execution_mode dans le log si ordre envoyé
                            if (order_sent) {
                                // Le mode sera déterminé dans SendBracketOrder (MARKET/LIMIT/SKIP)
                                // On pourrait relogger avec le bon mode, mais pour l'instant on garde "PENDING"
                            }
                            }  // Fin else SLTP valid
                            }  // Fin else (L1/L3/BN ok) - Quick Wins
                        }  // Fin else L4.passed
                    }  // Fin else L3 chain (veto/passed/else)
                }  // Fin else L2.passed
            }  // Fin else L1.passed
            }  // Fin else FLAT VETO
        }
        CheckOrderTimeout(sc, g_es_state);
    }

    // === TRAITEMENT NQ ===
    if (!g_nq_state.enabled) {
        strcpy(g_dashboard.bot_action_nq, "DISABLED");
        strcpy(g_dashboard.no_trade_reason_nq, "NQ desactive dans les inputs");
    } else if (g_nq_state.paused) {
        strcpy(g_dashboard.bot_action_nq, "PAUSED");
        strcpy(g_dashboard.no_trade_reason_nq, "NQ en pause manuelle");
    } else if (g_nq_state.in_position) {
        strcpy(g_dashboard.bot_action_nq, "IN POSITION");
        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                 "Position ouverte: %s @ %.2f",
                 g_nq_state.position_direction == 1 ? "LONG" : "SHORT",
                 g_nq_state.entry_price);
        UpdateTrailingStop(sc, g_nq_state, CONFIG_NQ, current_price_nq);  // 🔧 27/01: Utiliser prix NQ correct
    } else {
        bool can_trade_nq = true;

        if (sc.CurrentSystemDateTime < g_nq_state.cooldown_until) {
            can_trade_nq = false;
            strcpy(g_nq_state.waiting_for, "Cooldown");
            strcpy(g_dashboard.bot_action_nq, "COOLDOWN");
            strcpy(g_dashboard.no_trade_reason_nq, "En cooldown apres trade precedent");
        }
        if (sc.CurrentSystemDateTime < g_nq_state.news_block_until) {
            can_trade_nq = false;
            strcpy(g_nq_state.waiting_for, "News block");
            strcpy(g_dashboard.bot_action_nq, "NEWS BLOCK");
            strcpy(g_dashboard.no_trade_reason_nq, "SPREAD ECARTE - Bloque 30 min suite annonce");
        }

        if (can_trade_nq) {
            strcpy(g_dashboard.bot_action_nq, "SCANNING");
            strcpy(g_dashboard.no_trade_reason_nq, "En attente d'opportunite...");

            // === VETO FLAT NQ: slope < seuil = NO TRADE (sauf exception desequilibre) ===
            // 🔧 27/01/2026: Seuil adaptatif par session
            // - Asia: 0.005 (plus permissif, volume faible = slope naturellement bas)
            // - London/US: 0.01 (standard)
            float vwap_slope_nq = g_market_live.vwap_slope_nq;
            bool is_asia_nq = (strcmp(g_dashboard.current_session, "Asia") == 0);
            float flat_threshold_nq = is_asia_nq ? 0.005f : 0.01f;
            bool is_flat_nq = (fabs(vwap_slope_nq) < flat_threshold_nq);

            if (is_flat_nq) {
                // Exception DESEQUILIBRE: FLAT mais d_vwap > 60 ticks NQ = OK
                float d_vwap_nq = fabs(current_price_nq - mq_nq.vwap);
                float d_vwap_ticks_nq = d_vwap_nq / CONFIG_NQ.tick_size;

                if (d_vwap_ticks_nq <= 60.0f) {
                    // VETO - FLAT sans desequilibre
                    strcpy(g_dashboard.bot_action_nq, "FLAT VETO");
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                             "VWAP FLAT (slope=%.4f < %.3f) - d_vwap=%.0ft <= 60t", vwap_slope_nq, flat_threshold_nq, d_vwap_ticks_nq);
                    can_trade_nq = false;
                }
                // Si d_vwap > 60t → on laisse passer (desequilibre = retour VWAP probable)
            }

            if (!can_trade_nq) {
                // Skip (FLAT VETO applied)
            } else {
            // === LAYER 1 (MenthorQ) ===
            Layer1Result l1_nq = ValidateLayer1(sc, mq_nq, current_price_nq, CONFIG_NQ, bn_nq.momentum_score, &bn_nq, false);

            // === LAYER 1B (Rectangles) - Alternative si L1 échoue ===
            RectangleSignal rect_signal_nq = {false, 0, 0, 0, 0, ""};
            bool rectangle_trading_enabled_nq = Input_Rectangle_Trading.GetYesNo();
            if (!l1_nq.passed && rectangle_trading_enabled_nq) {
                rect_signal_nq = DetectRectangleConfluence(sc, bn_nq, mq_nq, current_price_nq, CONFIG_NQ, true);
                if (rect_signal_nq.has_signal) {
                    // Convertir en Layer1Result pour compatibilité
                    l1_nq.passed = true;
                    l1_nq.direction = rect_signal_nq.direction;
                    l1_nq.confidence = rect_signal_nq.confidence;
                    l1_nq.level_price = rect_signal_nq.rectangle_price;
                    l1_nq.distance_ticks = 0;  // Rectangle = contact direct
                    strncpy(l1_nq.level_name, rect_signal_nq.reason, sizeof(l1_nq.level_name) - 1);
                }
            }

            if (!l1_nq.passed) {
                // Message détaillé: MenthorQ + Rectangles
                if (rectangle_trading_enabled_nq) {
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                        "L1: MQ=NON, RECT=NON (ColorUp=%.0f ColorDn=%.0f LongDnUp=%.0f)",
                        bn_nq.color_up, bn_nq.color_down, bn_nq.long_down_up);
                } else {
                    strcpy(g_dashboard.no_trade_reason_nq, "L1: Pas de niveau MenthorQ proche (RECT desactive)");
                }
            } else {
                int direction_nq = l1_nq.direction;

                // 🔧 OPTIMISÉ 25/01/2026: Calculer depth_imbalance et buy/sell % pour NQ
                float depth_imbalance_nq = 0.0f;
                s_MarketDepthEntry bid_entry_nq, ask_entry_nq;
                sc.GetBidMarketDepthEntryAtLevel(bid_entry_nq, 0);
                sc.GetAskMarketDepthEntryAtLevel(ask_entry_nq, 0);
                int total_dom_nq = bid_entry_nq.Quantity + ask_entry_nq.Quantity;
                if (total_dom_nq > 0) {
                    depth_imbalance_nq = (float)(bid_entry_nq.Quantity - ask_entry_nq.Quantity) / total_dom_nq;
                }
                
                // 🔧 30/01/2026: Utiliser FPBS (Order Flow réel) NORMALISÉ
                float buy_pct_nq, sell_pct_nq;
                float fpbs_total_nq = bn_nq.fpbs_bid_pct + bn_nq.fpbs_ask_pct;
                if (fpbs_total_nq > 0.001f) {
                    // Normaliser les données FPBS pour obtenir de vrais pourcentages
                    buy_pct_nq = bn_nq.fpbs_bid_pct / fpbs_total_nq;
                    sell_pct_nq = bn_nq.fpbs_ask_pct / fpbs_total_nq;
                } else {
                    // Fallback sur color_up/down si FPBS indisponible
                    buy_pct_nq = (bn_nq.color_up > 0) ? 
                        bn_nq.color_up / (bn_nq.color_up + bn_nq.color_down + 0.001f) : 0.5f;
                    sell_pct_nq = 1.0f - buy_pct_nq;
                }
                
                float vwap_slope_nq = g_market_live.vwap_slope_nq;
                
                Layer2Result l2_nq = ValidateLayer2(direction_nq, bn_nq, bn_es, vix,
                                                     0, buy_pct_nq, CONFIG_NQ, true,
                                                     depth_imbalance_nq, sell_pct_nq, vwap_slope_nq);

                if (!l2_nq.passed) {
                    snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                             "L2: %s", l2_nq.reason);
                    snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                             "L2 REJETE: BN=%.2f %s", l2_nq.bn_score, l2_nq.reason);
                    g_dashboard.signals_rejected_nq++;
                    // 🆕 LOG REJET POUR ANALYSE
                    LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L2",
                                     l2_nq.reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                     vix, l2_nq.bn_score);
                } else {
                    Layer3Result l3_nq = ValidateLayer3(direction_nq, bn_nq, current_price_nq,
                                                         mq_nq, vix, atr_nq,
                                                         g_dashboard.current_session, true);  // NQ

                    if (l3_nq.veto) {
                        snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                 "L3 VETO: %s", l3_nq.veto_reason);
                        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                 "L3 VETO: %s", l3_nq.veto_reason);
                        g_dashboard.signals_rejected_nq++;
                        // 🆕 LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3_VETO",
                                         l3_nq.veto_reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                         vix, bn_nq.score);
                    } else if (!l3_nq.passed) {
                        snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                 "L3: Context=%.2f trop bas", l3_nq.confidence);
                        snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                 "L3 REJETE: Contexte defavorable %s", l3_nq.context);
                        g_dashboard.signals_rejected_nq++;
                        // 🆕 LOG REJET POUR ANALYSE
                        LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3",
                                         l3_nq.context, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                         vix, bn_nq.score);
                    } else {
                        // === LAYER 4 NQ (V54: 2 REGLES BACKTEST, 1/2 REQUIS) ===
                        // 🔧 25/01/2026: Nouvelles règles validées par backtest rigoureux
                        
                        // Calcul buy_pct depuis BN_Data (signals acheteurs vs vendeurs)
                        float buyer_signals_nq = bn_nq.color_up + bn_nq.rotation_up + bn_nq.edge_buy + bn_nq.absorb_bid;
                        float seller_signals_nq = bn_nq.color_down + bn_nq.rotation_down + bn_nq.edge_sell + bn_nq.absorb_ask;
                        float total_signals_nq = buyer_signals_nq + seller_signals_nq;
                        float buy_pct_nq = (total_signals_nq > 0) ? (buyer_signals_nq / total_signals_nq) : 0.5f;
                        float sell_pct_nq = 1.0f - buy_pct_nq;

                        // Edge Buy/Sell pour Edge Dominant
                        float edge_buy_nq = bn_nq.edge_buy + bn_nq.bar_edge_buy;
                        float edge_sell_nq = bn_nq.edge_sell + bn_nq.bar_edge_sell;

                        // Calcul cum_delta proxy depuis rotation (momentum)
                        float cum_delta_proxy_nq = bn_nq.rotation_up - bn_nq.rotation_down;

                        Layer4Result l4_nq = ValidateLayer4(direction_nq, buy_pct_nq, sell_pct_nq,
                                                            edge_buy_nq, edge_sell_nq,
                                                            cum_delta_proxy_nq, bn_nq.score,
                                                            g_market_live.vwap_slope_nq, CONFIG_NQ);

                        if (!l4_nq.passed) {
                            snprintf(g_dashboard.last_rejected_nq, sizeof(g_dashboard.last_rejected_nq),
                                     "L4: Combo %d/2 < 1/2", l4_nq.combo_aligned);
                            snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                     "L4 REJETE: Combo %d/2 (pct52=%d,edge=%d)",
                                     l4_nq.combo_aligned, l4_nq.pct_ok, l4_nq.edge_ok);
                            g_dashboard.signals_rejected_nq++;
                            char l4_nq_reason[64];
                            snprintf(l4_nq_reason, sizeof(l4_nq_reason), "Combo %d/2 < 1/2 required", l4_nq.combo_aligned);
                            LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L4",
                                             l4_nq_reason, current_price_nq, l1_nq.level_price, l1_nq.distance_ticks,
                                             vix, bn_nq.score);
                        } else {
                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 27/01/2026: FILTRES RENFORCÉS NQ - "MEILLEURS SETUPS ONLY"
                            // Problème identifié: trades à 13% L3 et 41% L2 = MAUVAIS!
                            // Nouveau: exiger des signaux de QUALITÉ pas juste "passables"
                            // ═══════════════════════════════════════════════════════════════
                            
                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 27/01/2026 16h: SEUILS ÉQUILIBRÉS NQ
                            // ═══════════════════════════════════════════════════════════════
                            float min_l1_conf_nq = 0.30f;  // NQ: 30% minimum (était 32%)
                            float min_l2_conf_nq = 0.38f;  // NQ: 38% minimum (était 45% = trop strict!)
                            float min_l3_conf_nq = 0.12f;  // NQ: 12% minimum (était 16%)
                            float min_confluence_nq = 0.40f;  // Confluence globale: 40% min (était 48%)
                            
                            // Calcul confluence globale
                            float overall_conf_nq = (l1_nq.confidence + l2_nq.confidence + l3_nq.confidence + bn_nq.score) / 4.0f;
                            
                            if (l1_nq.confidence < min_l1_conf_nq) {
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L1 REJET: Conf=%.1f%% < %.0f%% (signal trop faible)", 
                                         l1_nq.confidence * 100, min_l1_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L1_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (l2_nq.confidence < min_l2_conf_nq) {
                                // 🆕 27/01/2026: Nouveau filtre L2!
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L2 REJET: Conf=%.1f%% < %.0f%% (BN/corrélation trop faible)", 
                                         l2_nq.confidence * 100, min_l2_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L2_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (l3_nq.confidence < min_l3_conf_nq) {
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "L3 REJET: Conf=%.1f%% < %.0f%% (contexte trop faible)", 
                                         l3_nq.confidence * 100, min_l3_conf_nq * 100);
                                g_dashboard.signals_rejected_nq++;
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "L3_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (bn_nq.score < 0.40f) {  // BN: 40% minimum
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "BN REJET: Score=%.1f%% < 40%% (BN trop faible)", bn_nq.score * 100);
                                g_dashboard.signals_rejected_nq++;
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "BN_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else if (overall_conf_nq < min_confluence_nq) {
                                // 🆕 27/01/2026: Nouveau filtre confluence globale!
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "CONF REJET: Global=%.1f%% < %.0f%% (L1=%.0f L2=%.0f L3=%.0f BN=%.0f)", 
                                         overall_conf_nq * 100, min_confluence_nq * 100,
                                         l1_nq.confidence * 100, l2_nq.confidence * 100, 
                                         l3_nq.confidence * 100, bn_nq.score * 100);
                                g_dashboard.signals_rejected_nq++;
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT", "CONF_MIN",
                                                 g_dashboard.no_trade_reason_nq, current_price_nq, l1_nq.level_price,
                                                 l1_nq.distance_ticks, vix, bn_nq.score);
                            } else {
                            // 🎯 26/01/2026: QUICK WIN #2 - RECTANGLE BONUS +5% NQ
                            float l1_confidence_bonus_nq = l1_nq.confidence;
                            bool has_rectangle_nq = (direction_nq == 1) ?
                                (bn_nq.price_in_edge_rect_buy || bn_nq.num_edge_rect_buy > 0) :
                                (bn_nq.price_in_edge_rect_sell || bn_nq.num_edge_rect_sell > 0);
                            
                            if (has_rectangle_nq) {
                                l1_confidence_bonus_nq *= 1.05f;  // +5% bonus
                            }
                            
                            // === SIGNAL VALIDÉ - VERIFIER R:R ===
                            // 🆕 25/01/2026: Passer le tracker persistant pour SL/TP intelligent
                            SLTPResult sltp_nq = CalculateProtectedSLTP(direction_nq, current_price_nq, mq_nq, bn_nq, CONFIG_NQ, &g_ext_tracker_nq);

                            // 🆕 VETO si obstacle bloque le R:R
                            if (!sltp_nq.is_valid) {
                                strcpy(g_dashboard.bot_action_nq, "VETO_RR");
                                snprintf(g_dashboard.no_trade_reason_nq, sizeof(g_dashboard.no_trade_reason_nq),
                                         "NQ: %s", sltp_nq.tp_based_on);
                                LogRejectedSignal(sc, CONFIG_NQ, direction_nq == 1 ? "LONG" : "SHORT",
                                                  "SLTP", sltp_nq.tp_based_on, current_price_nq, 0, 0, vix, bn_nq.score);
                            } else {

                            // ═══════════════════════════════════════════════════════════════
                            // 🔧 28/01/2026: HARD LIMIT SL/TP - TOUJOURS APPLIQUER!
                            // Bug: SL de 158 ticks au lieu de max 40!
                            // ═══════════════════════════════════════════════════════════════
                            float tick_size_nq = CONFIG_NQ.tick_size;
                            float max_sl_dist_nq = CONFIG_NQ.sl_max_ticks * tick_size_nq;
                            float max_tp_dist_nq = CONFIG_NQ.tp_max_ticks * tick_size_nq;
                            float current_sl_dist_nq = fabs(sltp_nq.sl_price - current_price_nq);
                            float current_tp_dist_nq = fabs(sltp_nq.tp_price - current_price_nq);
                            
                            // FORCER SL max
                            if (current_sl_dist_nq > max_sl_dist_nq) {
                                if (direction_nq == 1) {
                                    sltp_nq.sl_price = current_price_nq - max_sl_dist_nq;
                                } else {
                                    sltp_nq.sl_price = current_price_nq + max_sl_dist_nq;
                                }
                                sltp_nq.sl_ticks = CONFIG_NQ.sl_max_ticks;
                                strncpy(sltp_nq.sl_based_on, "MAX_HARD_LIMIT", sizeof(sltp_nq.sl_based_on));
                            }
                            
                            // FORCER TP max
                            if (current_tp_dist_nq > max_tp_dist_nq) {
                                if (direction_nq == 1) {
                                    sltp_nq.tp_price = current_price_nq + max_tp_dist_nq;
                                } else {
                                    sltp_nq.tp_price = current_price_nq - max_tp_dist_nq;
                                }
                                sltp_nq.tp_ticks = CONFIG_NQ.tp_max_ticks;
                                strncpy(sltp_nq.tp_based_on, "MAX_HARD_LIMIT", sizeof(sltp_nq.tp_based_on));
                            }

                            // ═══════════════════════════════════════════════════════════════
                            // 🆕 DÉTECTION TRADE HAUTE QUALITÉ NQ (risque augmenté)
                            // ═══════════════════════════════════════════════════════════════
                            int visual_count_nq = 0;
                            if (bn_nq.edge_buy > 0 || bn_nq.edge_sell > 0) visual_count_nq++;
                            if (bn_nq.color_up > 10 || bn_nq.color_down > 10) visual_count_nq++;
                            if (bn_nq.long_down_up > 0 || bn_nq.long_up_down > 0) visual_count_nq++;
                            if (bn_nq.num_edge_rect_buy > 0 || bn_nq.num_edge_rect_sell > 0) visual_count_nq++;
                            if (bn_nq.absorb_bid > 0 || bn_nq.absorb_ask > 0) visual_count_nq++;

                            HighQualityResult hq_nq = DetectHighQualityTrade(
                                direction_nq, bn_nq, l1_nq.importance_score,
                                visual_count_nq, !sltp_nq.is_valid
                            );

                            // Appliquer les multiplicateurs HQ si trade haute qualité
                            if (hq_nq.is_high_quality) {
                                float tick_size_nq = CONFIG_NQ.tick_size;

                                // TP plus ambitieux
                                float tp_distance_nq = fabs(sltp_nq.tp_price - current_price_nq);
                                tp_distance_nq *= hq_nq.tp_multiplier;
                                if (direction_nq == 1) {
                                    sltp_nq.tp_price = current_price_nq + tp_distance_nq;
                                } else {
                                    sltp_nq.tp_price = current_price_nq - tp_distance_nq;
                                }

                                // SL légèrement plus large
                                float sl_distance_nq = fabs(sltp_nq.sl_price - current_price_nq);
                                sl_distance_nq *= hq_nq.sl_multiplier;
                                if (direction_nq == 1) {
                                    sltp_nq.sl_price = current_price_nq - sl_distance_nq;
                                } else {
                                    sltp_nq.sl_price = current_price_nq + sl_distance_nq;
                                }

                                // Limiter SL max
                                if (fabs(sltp_nq.sl_price - current_price_nq) > CONFIG_NQ.sl_max_ticks * tick_size_nq) {
                                    if (direction_nq == 1) {
                                        sltp_nq.sl_price = current_price_nq - CONFIG_NQ.sl_max_ticks * tick_size_nq;
                                    } else {
                                        sltp_nq.sl_price = current_price_nq + CONFIG_NQ.sl_max_ticks * tick_size_nq;
                                    }
                                }

                                // 🔧 28/01/2026: FIX - Limiter TP max APRÈS HQ aussi!
                                // Bug: TP pouvait dépasser tp_max_ticks après multiplicateur HQ
                                if (fabs(sltp_nq.tp_price - current_price_nq) > CONFIG_NQ.tp_max_ticks * tick_size_nq) {
                                    if (direction_nq == 1) {
                                        sltp_nq.tp_price = current_price_nq + CONFIG_NQ.tp_max_ticks * tick_size_nq;
                                    } else {
                                        sltp_nq.tp_price = current_price_nq - CONFIG_NQ.tp_max_ticks * tick_size_nq;
                                    }
                                }

                                // Recalculer ticks
                                sltp_nq.tp_ticks = (int)(fabs(sltp_nq.tp_price - current_price_nq) / tick_size_nq);
                                sltp_nq.sl_ticks = (int)(fabs(sltp_nq.sl_price - current_price_nq) / tick_size_nq);

                                // Log HQ
                                sc.AddMessageToLog(hq_nq.reason, 0);
                            }

                            // 🆕 Calculer ancre BN avant d'entrer
                            float bn_anchor_nq = CalculateBNAnchor(direction_nq, current_price_nq, bn_nq, CONFIG_NQ.tick_size);

                            // 🆕 Stocker données Discord pour notification
                            g_nq_state.discord_bn_score = bn_nq.score;
                            g_nq_state.discord_l1_conf = l1_nq.confidence;
                            g_nq_state.discord_l2_conf = l2_nq.confidence;
                            g_nq_state.discord_l3_conf = l3_nq.confidence;
                            g_nq_state.discord_l4_combo = l4_nq.combo_aligned;
                            g_nq_state.discord_vwap_slope = g_market_live.vwap_slope_nq;
                            g_nq_state.discord_is_rectangle = rect_signal_nq.has_signal;

                            // 🆕 TRADE WHY JOURNAL - Log avant envoi ordre NQ
                            TradeWhy why_nq = BuildTradeWhy(sc, "NQ", direction_nq, current_price_nq,
                                                           l1_nq, l2_nq, l3_nq, l4_nq, bn_nq, mq_nq,
                                                           vix, bn_anchor_nq, rect_signal_nq.has_signal,
                                                           rect_signal_nq, CONFIG_NQ, "PENDING");
                            why_nq.sl_price = sltp_nq.sl_price;
                            why_nq.tp_price = sltp_nq.tp_price;
                            LogTradeWhy(sc, why_nq, CONFIG_NQ);

                            strcpy(g_dashboard.bot_action_nq, "ENTERING");
                            strcpy(g_dashboard.no_trade_reason_nq, "SIGNAL VALIDE - Entree en cours!");

                            // Envoyer ordre (va déterminer execution_mode)
                            bool order_sent_nq = SendBracketOrder(sc, direction_nq, current_price_nq,
                                           sltp_nq.sl_price, sltp_nq.tp_price, g_nq_state, bn_anchor_nq);

                            // 🆕 Mettre à jour execution_mode dans TradeWhy NQ
                            if (order_sent_nq) {
                                if (g_nq_state.pending_limit_order) {
                                    strncpy(why_nq.execution_mode, "PENDING_LIMIT", sizeof(why_nq.execution_mode) - 1);
                                } else {
                                    strncpy(why_nq.execution_mode, "IMMEDIATE", sizeof(why_nq.execution_mode) - 1);
                                }
                                LogTradeWhy(sc, why_nq, CONFIG_NQ);
                            }
                            }  // Fin else SLTP valid NQ
                            }  // Fin else (L1/L3/BN ok) - Quick Wins NQ
                        }  // Fin else L4.passed NQ
                    }  // Fin else L3 chain NQ (veto/passed/else)
                }  // Fin else L2.passed NQ
            }  // Fin else L1.passed NQ
            }  // Fin else FLAT VETO NQ
        }
        CheckOrderTimeout(sc, g_nq_state);
    }

    // === SAUVEGARDER DASHBOARD ===
    SaveDashboard(sc);

    // 🆕 AFFICHER DASHBOARD SUR LE GRAPHIQUE
    DrawDashboardOnChart(sc);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DU FICHIER
// ═══════════════════════════════════════════════════════════════════════════════
