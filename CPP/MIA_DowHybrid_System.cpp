// ═══════════════════════════════════════════════════════════════════════════════
// MIA DOW HYBRID SYSTEM v1.0
// ═══════════════════════════════════════════════════════════════════════════════
//
// Sierra Chart ACSIL Study - Système Hybride de Trading
//
// ARCHITECTURE:
// ═══════════════════════════════════════════════════════════════════════════════
//
//   🏆 CŒUR = THÉORIE DE DOW (90% de la décision)
//   ─────────────────────────────────────────────
//   • Les 🟢🔴 créent les niveaux (Extension Lines)
//   • Entrée sur les boules (rebond sur HL/LH)
//   • SL/TP basés sur les boules
//   • Sortie si structure Dow cassée
//
//   🔧 FILTRE = MENTHORQ (10% de la décision - BONUS)
//   ─────────────────────────────────────────────────
//   • NE CRÉE PAS de signal
//   • RENFORCE si confluence avec 🟢🔴
//   • Peut ajuster SL/TP si niveau MQ proche
//
// ═══════════════════════════════════════════════════════════════════════════════
//
// DÉTECTION TENDANCE DOW:
// ═══════════════════════════════════════════════════════════════════════════════
//
//   UPTREND CONFIRMÉ = 3+ 🟢 ASCENDANTES
//   ────────────────────────────────────
//   • 🟢1 (Premier support - HL1)
//   • 🟢2 > 🟢1 (Higher Low)
//   • 🟢3 > 🟢2 (CONFIRMATION!) → UPTREND CONFIRMÉ
//
//   DOWNTREND CONFIRMÉ = 3+ 🔴 DESCENDANTES
//   ──────────────────────────────────────
//   • 🔴1 (Première résistance - LH1)
//   • 🔴2 < 🔴1 (Lower High)
//   • 🔴3 < 🔴2 (CONFIRMATION!) → DOWNTREND CONFIRMÉ
//
// ═══════════════════════════════════════════════════════════════════════════════
//
// Author: MIA Trading System
// Date: 2026-01-25
// Version: 1.0 Hybrid
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "sierrachart.h"
#include <vector>
#include <string>
#include <cmath>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <iomanip>

SCDLLName("MIA_DowHybrid_System")

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1: CONFIGURATION ET CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// --- STUDY IDs (identiques au bot principal) ---

// ES FOOTPRINT (Chart 28)
const int ES_FP_EDGE_BUY = 32;
const int ES_FP_EDGE_SELL = 35;
const int ES_FP_COLOR_UP = 56;
const int ES_FP_COLOR_DOWN = 57;
const int ES_FP_ABSORB_ASK = 25;
const int ES_FP_ABSORB_BID = 26;
const int ES_FP_DOUBLE_ASK = 28;
const int ES_FP_DOUBLE_BID = 27;
const int ES_FP_ROTATION_UP = 19;
const int ES_FP_ROTATION_DOWN = 20;

// NQ FOOTPRINT (Chart 39)
const int NQ_FP_EDGE_BUY = 55;
const int NQ_FP_EDGE_SELL = 56;
const int NQ_FP_COLOR_UP = 53;
const int NQ_FP_COLOR_DOWN = 54;
const int NQ_FP_ABSORB_ASK = 29;
const int NQ_FP_ABSORB_BID = 30;
const int NQ_FP_TRIPLE_ASK = 28;
const int NQ_FP_TRIPLE_BID = 27;
const int NQ_FP_ROTATION_UP = 21;
const int NQ_FP_ROTATION_DOWN = 22;
const int NQ_FP_VOLUME_UP = 35;
const int NQ_FP_VOLUME_DOWN = 36;

// ES BARRES (Chart 29)
const int ES_BAR_COLOR_UP = 24;
const int ES_BAR_COLOR_DOWN = 25;
const int ES_BAR_LONG_DOWN_UP = 38;
const int ES_BAR_LONG_UP_DOWN = 39;
const int ES_BAR_EDGE_BUY = 16;
const int ES_BAR_EDGE_SELL = 44;

// NQ BARRES (Chart 40)
const int NQ_BAR_COLOR_UP = 26;
const int NQ_BAR_COLOR_DOWN = 27;
const int NQ_BAR_LONG_DOWN_UP = 23;
const int NQ_BAR_LONG_UP_DOWN = 24;
const int NQ_BAR_EDGE_BUY = 32;
const int NQ_BAR_EDGE_SELL = 33;

// --- SUBGRAPHS ---
const int SG_COUNT_ALERTS = 58;
const int SG_SUM_ALERTS = 2;

// ═══════════════════════════════════════════════════════════════════════════════
// 📊 DOW THEORY V6 - PARAMÈTRES OPTIMAUX AVEC EXTENSION LINES
// ═══════════════════════════════════════════════════════════════════════════════
//
// VALIDÉS LE 25/01/2026 - BACKTEST:
// - TRAIN: $3,907 (108 trades, WR 69.4%, PF 2.63, R:R 1.16)
// - TEST:  $506 (36 trades, WR 63.9%, PF 1.49)
//
// AMÉLIORATIONS V6:
// - SL basé sur Extension Lines actives (-19% risque)
// - TP ajusté pour éviter obstacles (61% des trades)
// - Ratio R:R amélioré: 1.16 (vs 0.80 avant)
// - Avg Loss réduit: $72 (vs $112 avant)
//
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1A: DÉTECTION DE TENDANCE DOW
// ═══════════════════════════════════════════════════════════════════════════════

// NOMBRE MINIMUM DE BOULES POUR CONFIRMER UNE TENDANCE
const int DOW_MIN_POINTS_FORMING = 2;     // 2 boules = EN FORMATION (pas encore tradeable)
const int DOW_MIN_POINTS_CONFIRMED = 3;   // 3 boules = CONFIRMÉE (DÉPART VALIDÉ!)
const int DOW_MIN_POINTS_STRONG = 4;      // 4+ boules = FORTE (tendance mature)

// CRITÈRES DE VALIDITÉ DU DÉPART
const float DOW_MIN_STEP_TICKS_ES = 4.0f;    // ES: Écart min entre 2 🟢/🔴 = 4 ticks (1 pt)
const float DOW_MIN_STEP_TICKS_NQ = 8.0f;    // NQ: Écart min entre 2 🟢/🔴 = 8 ticks (2 pts)
const int DOW_MAX_BARS_BETWEEN_POINTS = 20;   // Max 20 barres entre 2 boules (tendance fraîche)
const int DOW_FRESH_TREND_BARS = 30;          // Tendance "fraîche" si dernière boule < 30 barres

// Lookback pour scanner les boules
const int DOW_LOOKBACK_DEFAULT = 40;      // Défaut: 40 barres
const int DOW_LOOKBACK_MIN = 20;          // Min: 20 barres
const int DOW_LOOKBACK_MAX = 100;         // Max: 100 barres
const int DOW_LOOKBACK_BARS = 40;         // Nombre de barres à scanner (utilisé dans CollectDowPoints)
const float DOW_MIN_DISTANCE_TICKS = 2;   // Distance min entre 2 boules (éviter doublons)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1B: EXTENSION LINES - SL/TP INTELLIGENT (V6)
// ═══════════════════════════════════════════════════════════════════════════════
// Le SL est placé sous la dernière Extension Line ACTIVE (pas un SL fixe)
// Le TP est ajusté si un OBSTACLE (Extension Line adverse) est détecté avant
// ═══════════════════════════════════════════════════════════════════════════════

// Distance max pour chercher Extension Line pour SL
const float EXT_SL_SEARCH_DISTANCE_ES = 15.0f;  // Chercher support dans 15 ticks
const float EXT_SL_SEARCH_DISTANCE_NQ = 25.0f;  // Chercher support dans 25 ticks

// Buffer sous/au-dessus du niveau Extension Line pour SL
const float EXT_SL_BUFFER_ES = 2.0f;            // SL = niveau - 2 ticks (ES)
const float EXT_SL_BUFFER_NQ = 3.0f;            // SL = niveau - 3 ticks (NQ)

// Buffer avant obstacle pour TP
const float EXT_TP_OBSTACLE_BUFFER_ES = 2.0f;   // TP = obstacle - 2 ticks (ES)
const float EXT_TP_OBSTACLE_BUFFER_NQ = 4.0f;   // TP = obstacle - 4 ticks (NQ)

// SL minimum (éviter SL trop serré)
const float EXT_MIN_SL_DISTANCE_ES = 4.0f;      // Min 4 ticks = 1 point
const float EXT_MIN_SL_DISTANCE_NQ = 6.0f;      // Min 6 ticks = 1.5 points

// Tolérance pour considérer une Extension Line touchée
const float EXT_TOUCH_TOLERANCE_ES = 2.0f;      // 2 ticks
const float EXT_TOUCH_TOLERANCE_NQ = 3.0f;      // 3 ticks

// SL/TP de base (fallback si pas d'Extension Line)
const float BASE_SL_ES = 12.0f;                 // SL fallback ES: 3 points
const float BASE_SL_NQ = 20.0f;                 // SL fallback NQ: 5 points
const float BASE_TP_ES = 28.0f;                 // TP cible ES: 7 points
const float BASE_TP_NQ = 50.0f;                 // TP cible NQ: 12.5 points

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1C: TRAILING STOP (71% DES SORTIES EN V6)
// ═══════════════════════════════════════════════════════════════════════════════

// ACTIVATION: Profit minimum pour activer le trailing (OPTIMISÉ V6)
const float TRAILING_ACTIVATION_ES = 10.0f;     // Activer après +10 ticks (2.5 pts)
const float TRAILING_ACTIVATION_NQ = 16.0f;     // Activer après +16 ticks (4 pts)

// DISTANCE: Distance du trailing par rapport au prix favorable (OPTIMISÉ V6)
const float TRAILING_FRESH_TICKS_ES = 6.0f;     // Distance trailing normal ES
const float TRAILING_MATURE_TICKS_ES = 4.0f;    // Trailing serré ES (5 boules)
const float TRAILING_EXTENDED_TICKS_ES = 3.0f;  // Trailing très serré ES (6+ boules)
const float TRAILING_FRESH_TICKS_NQ = 10.0f;    // Distance trailing normal NQ
const float TRAILING_MATURE_TICKS_NQ = 7.0f;    // Trailing serré NQ
const float TRAILING_EXTENDED_TICKS_NQ = 5.0f;  // Trailing très serré NQ

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1D: ENTRÉE SUR PULLBACK (OBLIGATOIRE EN V6)
// ═══════════════════════════════════════════════════════════════════════════════

// Zone de pullback: entrer si prix dans X ticks du dernier HL (LONG) ou LH (SHORT)
const float PULLBACK_ZONE_ES = 6.0f;            // Entrer si dans 6 ticks (1.5 pts)
const float PULLBACK_ZONE_NQ = 10.0f;           // Entrer si dans 10 ticks (2.5 pts)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1E: MATURITÉ DE TENDANCE
// ═══════════════════════════════════════════════════════════════════════════════

const int DOW_MATURITY_FRESH = 3;         // 3 boules = FRAÎCHE (full trade)
const int DOW_MATURITY_MATURE = 5;        // 5 boules = MATURE (trailing serré)
const int DOW_MATURITY_EXTENDED = 6;      // 6+ boules = ÉTENDUE (TP réduit + trailing très serré)
const float DOW_TP_REDUCTION_EXTENDED = 0.70f;  // Réduire TP de 30% si tendance étendue

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1F: CONFIANCE ET RÈGLES D'OR
// ═══════════════════════════════════════════════════════════════════════════════

// Seuils de confiance selon l'état
const float DOW_CONFIDENCE_NONE = 0.0f;        // Pas de tendance
const float DOW_CONFIDENCE_FORMING = 0.40f;    // 40% confiance si 2 boules (ATTENDRE!)
const float DOW_CONFIDENCE_CONFIRMED = 0.75f;  // 75% confiance si 3 boules (DÉPART OK)
const float DOW_CONFIDENCE_STRONG = 0.90f;     // 90% confiance si 4+ boules
const float DOW_CONFIDENCE_WITH_RECT = 0.95f;  // 95% si rectangle présent

// Distance max pour considérer un niveau "proche" (en ticks)
const float DOW_PROXIMITY_TICKS = 10.0f;

// RÈGLE D'OR #1: Ratio domination
const float GOLDEN_RATIO = 1.5f;           // Ratio 1.5x pour RÈGLE D'OR #1
const float STRENGTH_MIN_THRESHOLD = 5.0f; // Force min pour considérer domination

// RÈGLE D'OR ABSOLUE - BUFFER POUR VALIDATION DE TENDANCE
// "Tant qu'AUCUNE 🔴 ne ferme SOUS la BASE des 🟢 (- buffer), UPTREND valide"
// "Tant qu'AUCUNE 🟢 ne ferme AU-DESSUS de la BASE des 🔴 (+ buffer), DOWNTREND valide"
const float GOLDEN_RULE_BUFFER_ES = 3.0f;  // Buffer ES: 3 ticks (0.75 pts)
const float GOLDEN_RULE_BUFFER_NQ = 5.0f;  // Buffer NQ: 5 ticks (1.25 pts)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1G: CONFLUENCE MENTHORQ (BONUS OPTIONNEL)
// ═══════════════════════════════════════════════════════════════════════════════

const float MQ_BONUS_DISTANCE_TICKS = 15.0f;  // Distance max pour bonus MQ
const int MQ_BONUS_SCORE = 10;                // +10 points si confluence MQ

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2: STRUCTURES DE DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════

// --- ÉTAT DE LA TENDANCE DOW ---
enum DowState {
    DOW_NONE = 0,           // Pas assez de données
    DOW_FORMING_UP,         // 2 🟢 ascendantes (en formation UP)
    DOW_CONFIRMED_UP,       // 3+ 🟢 ascendantes (UPTREND CONFIRMÉ)
    DOW_STRONG_UP,          // 4+ 🟢 ascendantes (UPTREND FORT)
    DOW_FORMING_DOWN,       // 2 🔴 descendantes (en formation DOWN)
    DOW_CONFIRMED_DOWN,     // 3+ 🔴 descendantes (DOWNTREND CONFIRMÉ)
    DOW_STRONG_DOWN,        // 4+ 🔴 descendantes (DOWNTREND FORT)
    DOW_RANGE,              // Range/Consolidation (pas de direction)
    DOW_REVERSAL_UP,        // Potentiel retournement haussier
    DOW_REVERSAL_DOWN       // Potentiel retournement baissier
};

// --- POINT (Boule Verte ou Rouge) ---
struct DowPoint {
    float price;            // Prix du point
    int bar_index;          // Index de la barre
    SCDateTime timestamp;   // Timestamp
    bool is_green;          // true = 🟢 (support), false = 🔴 (resist)
    float strength;         // Force du point (basée sur volume/indicateurs)
    bool is_rectangle;      // Rectangle associé (long_down_up / long_up_down)
    bool has_edge;          // Edge zone associée
};

// --- EXTENSION LINE TRACKÉE ---
struct ExtensionLine {
    float price;
    int bar_created;
    SCDateTime time_created;
    bool is_support;        // true = support, false = resist
    bool is_touched;        // A été touché (pour invalidation)
    int touch_count;        // Nombre de fois touché
    float strength_score;   // Score de force (plus de confirmations = plus fort)
};

// --- ANALYSE DOW COMPLÈTE ---
struct DowAnalysis {
    // État
    DowState state;
    float confidence;       // 0.0 - 1.0
    
    // Compteurs de boules
    int total_green_points;       // Total 🟢
    int total_red_points;         // Total 🔴
    int ascending_greens;         // 🟢 en séquence ascendante
    int descending_reds;          // 🔴 en séquence descendante
    
    // Derniers niveaux significatifs
    float last_hl;          // Dernier Higher Low (dernière 🟢 si uptrend)
    float last_lh;          // Dernier Lower High (dernière 🔴 si downtrend)
    float last_hh;          // Dernier Higher High (plus haut sommet)
    float last_ll;          // Dernier Lower Low (plus bas creux)
    
    // Points pour SL/TP
    float sl_reference;     // Niveau de référence pour SL (sous dernière 🟢 ou au-dessus dernière 🔴)
    float tp_reference;     // Niveau de référence pour TP (prochaine 🔴 ou 🟢 adverse)
    
    // Direction recommandée
    int recommended_direction;  // 1=LONG, -1=SHORT, 0=NEUTRE
    
    // Raison détaillée
    char reason[512];
};

// --- SNAPSHOT VISUEL ---
struct VisualSnapshot {
    // Indicateurs bruts
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
    float long_down_up;     // Rectangle VERT
    float long_up_down;     // Rectangle ROUGE
    float bar_color_up;
    float bar_color_down;
    float bar_edge_buy;
    float bar_edge_sell;
    
    // Prix
    float high;
    float low;
    float close;
    float mid;
    
    // Scores calculés
    int total_green;        // Score acheteurs total
    int total_red;          // Score vendeurs total
    float balance;          // Balance [-1, +1]
    bool dominant_buy;
    bool dominant_sell;
};

// --- RÈGLE D'OR ABSOLUE - VALIDATION CONTINUE DE LA TENDANCE ---
struct GoldenRuleAbsolute {
    bool trend_valid;           // Tendance encore valide
    bool trend_broken;          // Tendance vient d'être cassée
    int trend_direction;        // 1=UP, -1=DOWN, 0=NONE
    
    // Base de référence (niveau à ne pas casser)
    float green_base_level;     // Niveau le plus bas des 🟢 (support de la tendance UP)
    float red_base_level;       // Niveau le plus haut des 🔴 (résistance de la tendance DOWN)
    
    // Violation détectée
    float violation_price;      // Prix où la violation a eu lieu
    int violation_bar;          // Barre où la violation a eu lieu
    
    // Buffer appliqué
    float buffer_used;          // Buffer en ticks utilisé
    
    char status[256];
};

// --- 🔄 ALERTE RETOURNEMENT (DOW_REVERSAL) ---
struct ReversalAlert {
    bool is_active;             // Alerte de retournement active
    int potential_direction;    // Direction potentielle du reversal (1=UP, -1=DOWN)
    int opposing_points;        // Nombre de boules opposées détectées (2 = alerte, 3 = confirmé)
    bool is_confirmed;          // Reversal confirmé (3 boules opposées)
    bool block_old_direction;   // Bloquer les trades dans l'ancien sens
    float first_opposing_price; // Prix de la première boule opposée
    float last_opposing_price;  // Prix de la dernière boule opposée
    int bars_since_alert;       // Barres depuis l'alerte
    char alert_message[256];
};

// --- 🔄 MATURITÉ DE TENDANCE ---
enum TrendMaturity {
    MATURITY_NONE = 0,      // Pas de tendance
    MATURITY_FORMING,       // 2 boules - en formation
    MATURITY_FRESH,         // 3 boules - fraîche (OPTIMAL POUR ENTRER)
    MATURITY_MATURE,        // 4-5 boules - mature (trailing serré)
    MATURITY_EXTENDED       // 6+ boules - étendue (TP réduit + trailing très serré)
};

struct TrendMaturityInfo {
    TrendMaturity level;
    int point_count;            // Nombre de boules dans la séquence
    float tp_multiplier;        // Multiplicateur TP (1.0 = normal, 0.7 = réduit)
    float trailing_ticks;       // Distance trailing en ticks
    bool should_enter;          // Recommandation d'entrer ou pas
    char description[128];
};

// --- 🕐 FILTRE SESSION ---
struct SessionFilter {
    bool is_enabled;            // Filtre activé
    bool is_high_quality;       // Session de haute qualité
    float confidence_modifier;  // Modificateur de confiance (1.0 = normal, 0.8 = réduit)
    char session_name[32];
};

// ═══════════════════════════════════════════════════════════════════════════════
// 📦 DÉTECTION INTELLIGENTE DU RANGE / BASE
// ═══════════════════════════════════════════════════════════════════════════════
//
// RANGE = Zone où les 🟢 et 🔴 sont REGROUPÉES au même niveau de prix
// → Pas de séquence ascendante ou descendante claire
// → Écart vertical faible (< seuil)
// → Mélange de couleurs (ni que des 🟢, ni que des 🔴)
//
// APRÈS UNE ATTAQUE → Possible RANGE = NE PAS TRADER, attendre BREAKOUT
//
// ═══════════════════════════════════════════════════════════════════════════════

// Constantes pour la détection de RANGE
const float RANGE_MAX_SIZE_ES = 15.0f;   // 15 ticks max pour considérer un range ES
const float RANGE_MAX_SIZE_NQ = 30.0f;   // 30 ticks max pour NQ
const int RANGE_MIN_POINTS = 3;          // Min 3 boules pour un range
const float RANGE_MIX_RATIO_MIN = 0.25f; // Min 25% de chaque couleur
const float RANGE_MIX_RATIO_MAX = 0.75f; // Max 75% de chaque couleur
const int RANGE_LOOKBACK_BARS = 30;      // Scanner les 30 dernières barres pour le range

struct RangeDetection {
    bool is_range;              // Range détecté
    bool is_after_attack;       // Range après une attaque (plus significatif)
    
    // Dimensions du range
    float range_high;           // Haut du range (🔴 la plus haute)
    float range_low;            // Bas du range (🟢 la plus basse)
    float range_size_ticks;     // Taille en ticks
    float range_mid;            // Milieu du range
    
    // Composition du range
    int total_points;           // Total de boules dans le range
    int green_count;            // Nombre de 🟢
    int red_count;              // Nombre de 🔴
    float green_ratio;          // Ratio de 🟢 (0.0 - 1.0)
    
    // Volume/Force dans le range
    float absorb_bid_total;     // Absorptions BID (acheteurs)
    float absorb_ask_total;     // Absorptions ASK (vendeurs)
    float volume_bias;          // +1 = acheteurs dominent, -1 = vendeurs
    int rectangles_green;       // Rectangles verts dans le range
    int rectangles_red;         // Rectangles rouges dans le range
    
    // Prédiction breakout
    bool breakout_up_likely;    // Breakout UP probable (basé sur volume)
    bool breakout_down_likely;  // Breakout DOWN probable
    
    // Action
    bool should_block_trades;   // Bloquer les trades pendant ce range
    
    char description[256];
};

// --- SIGNAL DE TRADING ---
struct TradeSignal {
    bool is_valid;
    int direction;              // 1=LONG, -1=SHORT
    float entry_price;
    float sl_price;
    float tp_price;
    float trailing_distance;    // Distance trailing recommandée
    float trailing_activation;  // Profit requis pour activer le trailing
    
    // Scores
    int dow_score;              // Score Théorie de Dow (0-100)
    int visual_score;           // Score indicateurs visuels (0-100)
    int rules_score;            // Score règles d'or (0-100)
    int mq_bonus;               // Bonus MenthorQ (0-10)
    int total_score;            // Score total (0-100)
    
    // Confiance
    float confidence;
    
    // Règle d'or absolue
    GoldenRuleAbsolute golden_rule;
    
    // 🔄 NOUVELLES INFOS
    ReversalAlert reversal;         // Alerte de retournement
    TrendMaturityInfo maturity;     // Maturité de la tendance
    SessionFilter session;          // Qualité de la session
    RangeDetection range;           // Détection de range/BASE
    
    // Raison
    char reason[1024];
};

// --- HISTORIQUE GLOBAL ---
struct DowHybridHistory {
    // Points trackés
    std::vector<DowPoint> green_points;    // Toutes les 🟢
    std::vector<DowPoint> red_points;      // Toutes les 🔴
    
    // Extension Lines
    std::vector<ExtensionLine> ext_lines;
    
    // Dernière analyse
    DowAnalysis last_analysis;
    
    // Stats
    int signals_generated;
    int signals_valid;
    int signals_blocked;
};

// Variables globales
DowHybridHistory g_es_history;
DowHybridHistory g_nq_history;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3: FONCTIONS UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════════

inline float ReadStudyValue(SCStudyInterfaceRef sc, int chart, int study_id, int subgraph, int bar_offset = 0) {
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study_id, subgraph, arr);
    int size = arr.GetArraySize();
    if (size > bar_offset) {
        return arr[size - 1 - bar_offset];
    }
    return 0.0f;
}

std::string GetDowStateString(DowState state) {
    switch (state) {
        case DOW_NONE: return "AUCUNE_TENDANCE";
        case DOW_FORMING_UP: return "UPTREND_EN_FORMATION (2🟢)";
        case DOW_CONFIRMED_UP: return "UPTREND_CONFIRME (3🟢)";
        case DOW_STRONG_UP: return "UPTREND_FORT (4+🟢)";
        case DOW_FORMING_DOWN: return "DOWNTREND_EN_FORMATION (2🔴)";
        case DOW_CONFIRMED_DOWN: return "DOWNTREND_CONFIRME (3🔴)";
        case DOW_STRONG_DOWN: return "DOWNTREND_FORT (4+🔴)";
        case DOW_RANGE: return "RANGE/CONSOLIDATION";
        case DOW_REVERSAL_UP: return "REVERSAL_HAUSSIER";
        case DOW_REVERSAL_DOWN: return "REVERSAL_BAISSIER";
        default: return "UNKNOWN";
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4: COLLECTE DES INDICATEURS VISUELS
// ═══════════════════════════════════════════════════════════════════════════════

void CollectVisualSnapshot(SCStudyInterfaceRef sc, int chart_fp, int chart_bar, 
                          VisualSnapshot& snap, bool is_nq, int bar_offset = 0) {
    
    // Reset
    memset(&snap, 0, sizeof(VisualSnapshot));
    
    // --- FOOTPRINT ---
    if (is_nq) {
        snap.edge_buy = ReadStudyValue(sc, chart_fp, NQ_FP_EDGE_BUY, SG_COUNT_ALERTS, bar_offset);
        snap.edge_sell = ReadStudyValue(sc, chart_fp, NQ_FP_EDGE_SELL, SG_COUNT_ALERTS, bar_offset);
        snap.color_up = ReadStudyValue(sc, chart_fp, NQ_FP_COLOR_UP, SG_SUM_ALERTS, bar_offset);
        snap.color_down = ReadStudyValue(sc, chart_fp, NQ_FP_COLOR_DOWN, SG_SUM_ALERTS, bar_offset);
        snap.absorb_ask = ReadStudyValue(sc, chart_fp, NQ_FP_ABSORB_ASK, SG_SUM_ALERTS, bar_offset);
        snap.absorb_bid = ReadStudyValue(sc, chart_fp, NQ_FP_ABSORB_BID, SG_SUM_ALERTS, bar_offset);
        snap.triple_ask = ReadStudyValue(sc, chart_fp, NQ_FP_TRIPLE_ASK, 0, bar_offset);
        snap.triple_bid = ReadStudyValue(sc, chart_fp, NQ_FP_TRIPLE_BID, 0, bar_offset);
        snap.rotation_up = ReadStudyValue(sc, chart_fp, NQ_FP_ROTATION_UP, 0, bar_offset);
        snap.rotation_down = ReadStudyValue(sc, chart_fp, NQ_FP_ROTATION_DOWN, 0, bar_offset);
        
        // Barres NQ
        snap.long_down_up = ReadStudyValue(sc, chart_bar, NQ_BAR_LONG_DOWN_UP, 0, bar_offset);
        snap.long_up_down = ReadStudyValue(sc, chart_bar, NQ_BAR_LONG_UP_DOWN, 0, bar_offset);
        snap.bar_color_up = ReadStudyValue(sc, chart_bar, NQ_BAR_COLOR_UP, 0, bar_offset);
        snap.bar_color_down = ReadStudyValue(sc, chart_bar, NQ_BAR_COLOR_DOWN, 0, bar_offset);
        snap.bar_edge_buy = ReadStudyValue(sc, chart_bar, NQ_BAR_EDGE_BUY, 0, bar_offset);
        snap.bar_edge_sell = ReadStudyValue(sc, chart_bar, NQ_BAR_EDGE_SELL, 0, bar_offset);
    } else {
        snap.edge_buy = ReadStudyValue(sc, chart_fp, ES_FP_EDGE_BUY, SG_COUNT_ALERTS, bar_offset);
        snap.edge_sell = ReadStudyValue(sc, chart_fp, ES_FP_EDGE_SELL, SG_COUNT_ALERTS, bar_offset);
        snap.color_up = ReadStudyValue(sc, chart_fp, ES_FP_COLOR_UP, SG_SUM_ALERTS, bar_offset);
        snap.color_down = ReadStudyValue(sc, chart_fp, ES_FP_COLOR_DOWN, SG_SUM_ALERTS, bar_offset);
        snap.absorb_ask = ReadStudyValue(sc, chart_fp, ES_FP_ABSORB_ASK, SG_SUM_ALERTS, bar_offset);
        snap.absorb_bid = ReadStudyValue(sc, chart_fp, ES_FP_ABSORB_BID, SG_SUM_ALERTS, bar_offset);
        snap.double_ask = ReadStudyValue(sc, chart_fp, ES_FP_DOUBLE_ASK, 0, bar_offset);
        snap.double_bid = ReadStudyValue(sc, chart_fp, ES_FP_DOUBLE_BID, 0, bar_offset);
        snap.rotation_up = ReadStudyValue(sc, chart_fp, ES_FP_ROTATION_UP, 0, bar_offset);
        snap.rotation_down = ReadStudyValue(sc, chart_fp, ES_FP_ROTATION_DOWN, 0, bar_offset);
        
        // Barres ES
        snap.long_down_up = ReadStudyValue(sc, chart_bar, ES_BAR_LONG_DOWN_UP, 0, bar_offset);
        snap.long_up_down = ReadStudyValue(sc, chart_bar, ES_BAR_LONG_UP_DOWN, 0, bar_offset);
        snap.bar_color_up = ReadStudyValue(sc, chart_bar, ES_BAR_COLOR_UP, 0, bar_offset);
        snap.bar_color_down = ReadStudyValue(sc, chart_bar, ES_BAR_COLOR_DOWN, 0, bar_offset);
        snap.bar_edge_buy = ReadStudyValue(sc, chart_bar, ES_BAR_EDGE_BUY, 0, bar_offset);
        snap.bar_edge_sell = ReadStudyValue(sc, chart_bar, ES_BAR_EDGE_SELL, 0, bar_offset);
    }
    
    // Calculer les scores totaux
    // Points avec pondération: edge x3, rectangle x5, rotation x2
    snap.total_green = (int)snap.color_up + (int)snap.bar_color_up +
                       (int)snap.edge_buy * 3 + (int)snap.bar_edge_buy * 3 +
                       (int)snap.long_down_up * 5 +  // Rectangle VERT = très bullish
                       (int)snap.rotation_up * 2 +
                       (int)snap.absorb_bid * 2 +
                       (int)snap.double_bid + (int)snap.triple_bid;
    
    snap.total_red = (int)snap.color_down + (int)snap.bar_color_down +
                     (int)snap.edge_sell * 3 + (int)snap.bar_edge_sell * 3 +
                     (int)snap.long_up_down * 5 +  // Rectangle ROUGE = très bearish
                     (int)snap.rotation_down * 2 +
                     (int)snap.absorb_ask * 2 +
                     (int)snap.double_ask + (int)snap.triple_ask;
    
    // Balance
    int total = snap.total_green + snap.total_red;
    if (total > 0) {
        snap.balance = (float)(snap.total_green - snap.total_red) / total;
    } else {
        snap.balance = 0.0f;
    }
    
    // Dominance
    snap.dominant_buy = (snap.balance > 0.3f && snap.total_green >= 5);
    snap.dominant_sell = (snap.balance < -0.3f && snap.total_red >= 5);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5: COLLECTE DES POINTS (BOULES 🟢🔴) - LE CŒUR DU SYSTÈME
// ═══════════════════════════════════════════════════════════════════════════════

void CollectDowPoints(SCStudyInterfaceRef sc, int chart_fp, int chart_bar,
                      DowHybridHistory& history, float tick_size, bool is_nq, bool debug_mode) {
    
    // Clear les anciens points (garder seulement les X derniers)
    history.green_points.clear();
    history.red_points.clear();
    
    // 🆕 DEBUG FILE
    std::ofstream debug_file;
    if (debug_mode) {
        debug_file.open("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DOW_DEBUG.txt", std::ios::app);
        if (debug_file.is_open()) {
            int y, mo, d, h, mi, s;
            sc.CurrentSystemDateTime.GetDateTimeYMDHMS(y, mo, d, h, mi, s);
            debug_file << "\n═══════════════════════════════════════════════════════════\n";
            debug_file << "DEBUG DOW " << (is_nq ? "NQ" : "ES") << " - " 
                      << y << "-" << mo << "-" << d << " " << h << ":" << mi << ":" << s << "\n";
            debug_file << "═══════════════════════════════════════════════════════════\n";
            debug_file << "Chart FP: " << chart_fp << " | Chart BAR: " << chart_bar << "\n";
        }
    }
    
    // 🔧 Récupérer les données OHLC depuis le chart BARRES (pas Footprint!)
    // Le Footprint n'a pas de données OHLC classiques
    SCGraphData chart_data;
    sc.GetChartBaseData(chart_bar, chart_data);  // 🔧 chart_bar au lieu de chart_fp!
    int size = chart_data[SC_CLOSE].GetArraySize();
    
    if (debug_mode && debug_file.is_open()) {
        debug_file << "Chart Data Size: " << size << " | Lookback: " << DOW_LOOKBACK_BARS << "\n";
    }
    
    if (size < DOW_LOOKBACK_BARS) {
        if (debug_mode && debug_file.is_open()) {
            debug_file << "❌ ERREUR: Size trop petit (" << size << " < " << DOW_LOOKBACK_BARS << ")\n";
            debug_file.close();
        }
        return;
    }
    
    // Arrays pour les indicateurs visuels
    SCFloatArray color_up_arr, color_down_arr;
    SCFloatArray long_down_up_arr, long_up_down_arr;
    SCFloatArray edge_buy_arr, edge_sell_arr;
    
    // 🔧 CORRIGÉ: Subgraph 1 = POSITIONS/PRIX des boules (pas subgraph 2 = count)
    // C'est IDENTIQUE à MIA_AutoTrader_BN_v1.cpp ligne 1399
    if (is_nq) {
        sc.GetStudyArrayFromChartUsingID(chart_fp, NQ_FP_COLOR_UP, 1, color_up_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, NQ_FP_COLOR_DOWN, 1, color_down_arr);
        sc.GetStudyArrayFromChartUsingID(chart_bar, NQ_BAR_LONG_DOWN_UP, 1, long_down_up_arr);
        sc.GetStudyArrayFromChartUsingID(chart_bar, NQ_BAR_LONG_UP_DOWN, 1, long_up_down_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, NQ_FP_EDGE_BUY, 1, edge_buy_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, NQ_FP_EDGE_SELL, 1, edge_sell_arr);
        
        if (debug_mode && debug_file.is_open()) {
            debug_file << "\nStudy IDs NQ:\n";
            debug_file << "  COLOR_UP   (ID=" << NQ_FP_COLOR_UP << "): size=" << color_up_arr.GetArraySize() << "\n";
            debug_file << "  COLOR_DOWN (ID=" << NQ_FP_COLOR_DOWN << "): size=" << color_down_arr.GetArraySize() << "\n";
            debug_file << "  LONG_DN_UP (ID=" << NQ_BAR_LONG_DOWN_UP << "): size=" << long_down_up_arr.GetArraySize() << "\n";
            debug_file << "  LONG_UP_DN (ID=" << NQ_BAR_LONG_UP_DOWN << "): size=" << long_up_down_arr.GetArraySize() << "\n";
            debug_file << "  EDGE_BUY   (ID=" << NQ_FP_EDGE_BUY << "): size=" << edge_buy_arr.GetArraySize() << "\n";
            debug_file << "  EDGE_SELL  (ID=" << NQ_FP_EDGE_SELL << "): size=" << edge_sell_arr.GetArraySize() << "\n";
        }
    } else {
        sc.GetStudyArrayFromChartUsingID(chart_fp, ES_FP_COLOR_UP, 1, color_up_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, ES_FP_COLOR_DOWN, 1, color_down_arr);
        sc.GetStudyArrayFromChartUsingID(chart_bar, ES_BAR_LONG_DOWN_UP, 1, long_down_up_arr);
        sc.GetStudyArrayFromChartUsingID(chart_bar, ES_BAR_LONG_UP_DOWN, 1, long_up_down_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, ES_FP_EDGE_BUY, 1, edge_buy_arr);
        sc.GetStudyArrayFromChartUsingID(chart_fp, ES_FP_EDGE_SELL, 1, edge_sell_arr);
        
        if (debug_mode && debug_file.is_open()) {
            debug_file << "\nStudy IDs ES:\n";
            debug_file << "  COLOR_UP   (ID=" << ES_FP_COLOR_UP << "): size=" << color_up_arr.GetArraySize() << "\n";
            debug_file << "  COLOR_DOWN (ID=" << ES_FP_COLOR_DOWN << "): size=" << color_down_arr.GetArraySize() << "\n";
            debug_file << "  LONG_DN_UP (ID=" << ES_BAR_LONG_DOWN_UP << "): size=" << long_down_up_arr.GetArraySize() << "\n";
            debug_file << "  LONG_UP_DN (ID=" << ES_BAR_LONG_UP_DOWN << "): size=" << long_up_down_arr.GetArraySize() << "\n";
            debug_file << "  EDGE_BUY   (ID=" << ES_FP_EDGE_BUY << "): size=" << edge_buy_arr.GetArraySize() << "\n";
            debug_file << "  EDGE_SELL  (ID=" << ES_FP_EDGE_SELL << "): size=" << edge_sell_arr.GetArraySize() << "\n";
        }
    }
    
    if (debug_mode && debug_file.is_open()) {
        debug_file << "\nScan des " << DOW_LOOKBACK_BARS << " dernières barres:\n";
    }
    
    // Scanner les barres pour trouver les POINTS
    int green_found = 0;
    int red_found = 0;
    
    for (int i = 0; i < DOW_LOOKBACK_BARS && i < size; i++) {
        int idx = size - 1 - i;
        if (idx < 0) break;
        
        float bar_low = chart_data[SC_LOW][idx];
        float bar_high = chart_data[SC_HIGH][idx];
        
        bool has_color_up = (color_up_arr.GetArraySize() > idx && color_up_arr[idx] > 0);
        bool has_color_down = (color_down_arr.GetArraySize() > idx && color_down_arr[idx] > 0);
        bool has_rect_green = (long_down_up_arr.GetArraySize() > idx && long_down_up_arr[idx] > 0);
        bool has_rect_red = (long_up_down_arr.GetArraySize() > idx && long_up_down_arr[idx] > 0);
        bool has_edge_buy = (edge_buy_arr.GetArraySize() > idx && edge_buy_arr[idx] > 0);
        bool has_edge_sell = (edge_sell_arr.GetArraySize() > idx && edge_sell_arr[idx] > 0);
        
        // 🆕 DEBUG: Log les premières 5 barres avec données
        if (debug_mode && debug_file.is_open() && i < 5 && (has_color_up || has_color_down || has_rect_green || has_rect_red)) {
            debug_file << "  Bar[" << idx << "]: ";
            if (has_color_up) debug_file << "ColorUp=" << color_up_arr[idx] << " ";
            if (has_color_down) debug_file << "ColorDn=" << color_down_arr[idx] << " ";
            if (has_rect_green) debug_file << "RectGreen=" << long_down_up_arr[idx] << " ";
            if (has_rect_red) debug_file << "RectRed=" << long_up_down_arr[idx] << " ";
            debug_file << "\n";
        }
        
        // 🟢 POINT VERT (Support / Higher Low)
        if (has_color_up || has_rect_green) {
            DowPoint point;
            // 🔧 CORRIGÉ: Utiliser le prix RÉEL de la boule (dans le array) au lieu de bar_low
            if (has_color_up && color_up_arr[idx] > 0) {
                point.price = color_up_arr[idx];  // Prix réel de la boule verte
            } else if (has_rect_green && long_down_up_arr[idx] > 0) {
                point.price = long_down_up_arr[idx];  // Prix du rectangle vert
            } else {
                point.price = bar_low;  // Fallback
            }
            point.bar_index = idx;
            point.timestamp = sc.BaseDateTimeIn[idx];
            point.is_green = true;
            point.is_rectangle = has_rect_green;
            point.has_edge = has_edge_buy;
            
            // Calculer la force du point
            point.strength = 1.0f;
            if (has_rect_green) point.strength += 2.0f;  // Rectangle = très fort
            if (has_edge_buy) point.strength += 1.5f;    // Edge = fort
            
            // Vérifier qu'on n'a pas déjà un point très proche
            bool too_close = false;
            for (const auto& existing : history.green_points) {
                if (fabs(existing.price - point.price) < DOW_MIN_DISTANCE_TICKS * tick_size) {
                    too_close = true;
                    break;
                }
            }
            
            if (!too_close) {
                history.green_points.push_back(point);
                green_found++;
            }
        }
        
        // 🔴 POINT ROUGE (Résistance / Lower High)
        if (has_color_down || has_rect_red) {
            DowPoint point;
            // 🔧 CORRIGÉ: Utiliser le prix RÉEL de la boule (dans le array) au lieu de bar_high
            if (has_color_down && color_down_arr[idx] > 0) {
                point.price = color_down_arr[idx];  // Prix réel de la boule rouge
            } else if (has_rect_red && long_up_down_arr[idx] > 0) {
                point.price = long_up_down_arr[idx];  // Prix du rectangle rouge
            } else {
                point.price = bar_high;  // Fallback
            }
            point.bar_index = idx;
            point.timestamp = sc.BaseDateTimeIn[idx];
            point.is_green = false;
            point.is_rectangle = has_rect_red;
            point.has_edge = has_edge_sell;
            
            // Calculer la force du point
            point.strength = 1.0f;
            if (has_rect_red) point.strength += 2.0f;
            if (has_edge_sell) point.strength += 1.5f;
            
            // Vérifier qu'on n'a pas déjà un point très proche
            bool too_close = false;
            for (const auto& existing : history.red_points) {
                if (fabs(existing.price - point.price) < DOW_MIN_DISTANCE_TICKS * tick_size) {
                    too_close = true;
                    break;
                }
            }
            
            if (!too_close) {
                history.red_points.push_back(point);
                red_found++;
            }
        }
    }
    
    // 🆕 DEBUG: Résumé final
    if (debug_mode && debug_file.is_open()) {
        debug_file << "\n✅ RÉSULTATS:\n";
        debug_file << "  Boules VERTES trouvées: " << green_found << "\n";
        debug_file << "  Boules ROUGES trouvées: " << red_found << "\n";
        debug_file << "  Total stocké: 🟢" << history.green_points.size() 
                  << " 🔴" << history.red_points.size() << "\n";
        
        // Afficher les 3 premières boules de chaque type
        if (history.green_points.size() > 0) {
            debug_file << "\n  Premières boules VERTES:\n";
            size_t max_green = (history.green_points.size() < 3) ? history.green_points.size() : 3;
            for (size_t i = 0; i < max_green; i++) {
                debug_file << "    🟢 " << history.green_points[i].price 
                          << (history.green_points[i].is_rectangle ? " [RECT]" : "")
                          << (history.green_points[i].has_edge ? " [EDGE]" : "") << "\n";
            }
        }
        
        if (history.red_points.size() > 0) {
            debug_file << "\n  Premières boules ROUGES:\n";
            size_t max_red = (history.red_points.size() < 3) ? history.red_points.size() : 3;
            for (size_t i = 0; i < max_red; i++) {
                debug_file << "    🔴 " << history.red_points[i].price 
                          << (history.red_points[i].is_rectangle ? " [RECT]" : "")
                          << (history.red_points[i].has_edge ? " [EDGE]" : "") << "\n";
            }
        }
        
        debug_file.close();
    }
    
    // Trier les points par prix (du plus bas au plus haut pour les verts, inverse pour les rouges)
    std::sort(history.green_points.begin(), history.green_points.end(),
              [](const DowPoint& a, const DowPoint& b) { return a.price < b.price; });
    std::sort(history.red_points.begin(), history.red_points.end(),
              [](const DowPoint& a, const DowPoint& b) { return a.price > b.price; });
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6: ANALYSE THÉORIE DE DOW - DÉTECTION DE TENDANCE
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// 🚀 DÉTECTION DU DÉPART - FONCTION CRITIQUE
// ═══════════════════════════════════════════════════════════════════════════════
// 
// Cette fonction détecte précisément QUAND une tendance DÉMARRE
// basée sur la séquence de boules et leurs critères de validité
//
// ═══════════════════════════════════════════════════════════════════════════════

struct TrendStartInfo {
    bool is_valid_start;        // Départ valide détecté
    int sequence_length;        // Nombre de boules dans la séquence
    float step_quality;         // Qualité des écarts entre boules (0-1)
    bool is_fresh;              // Tendance fraîche (< DOW_FRESH_TREND_BARS)
    bool has_rectangle;         // Rectangle présent = confirmation forte
    int bars_since_start;       // Barres depuis le début de la séquence
    float first_point_price;    // Prix de la première boule
    float last_point_price;     // Prix de la dernière boule
    int first_bar_index;        // Index de la première barre
    int last_bar_index;         // Index de la dernière barre
    char details[256];
};

TrendStartInfo DetectTrendStart_UP(const std::vector<DowPoint>& greens, 
                                    int current_bar, float tick_size, bool is_nq) {
    TrendStartInfo info;
    memset(&info, 0, sizeof(TrendStartInfo));
    
    if (greens.size() < DOW_MIN_POINTS_FORMING) {
        snprintf(info.details, sizeof(info.details), "Pas assez de 🟢 (%zu)", greens.size());
        return info;
    }
    
    // Trier par bar_index (du plus ancien au plus récent)
    std::vector<DowPoint> sorted = greens;
    std::sort(sorted.begin(), sorted.end(),
              [](const DowPoint& a, const DowPoint& b) { return a.bar_index < b.bar_index; });
    
    float min_step = is_nq ? DOW_MIN_STEP_TICKS_NQ : DOW_MIN_STEP_TICKS_ES;
    
    // Chercher la plus longue séquence ASCENDANTE valide
    int best_seq_start = -1;
    int best_seq_length = 0;
    float best_step_quality = 0;
    bool best_has_rect = false;
    
    for (size_t start_idx = 0; start_idx < sorted.size(); start_idx++) {
        int seq_length = 1;
        float total_step_quality = 0;
        bool has_rect = sorted[start_idx].is_rectangle;
        int valid_steps = 0;
        
        for (size_t j = start_idx + 1; j < sorted.size(); j++) {
            float price_diff = sorted[j].price - sorted[j-1].price;
            float step_ticks = price_diff / tick_size;
            int bar_diff = sorted[j].bar_index - sorted[j-1].bar_index;
            
            // Vérifier si cette boule continue la séquence ascendante
            if (step_ticks >= min_step && bar_diff <= DOW_MAX_BARS_BETWEEN_POINTS) {
                seq_length++;
                valid_steps++;
                
                // Qualité de l'écart (1.0 = parfait, 0.5 = acceptable)
                float step_ratio = step_ticks / (min_step * 3);  // Idéal = 3x le minimum
                if (step_ratio > 1.0f) step_ratio = 1.0f;
                total_step_quality += step_ratio;
                
                if (sorted[j].is_rectangle) has_rect = true;
            } else if (step_ticks > 0 && step_ticks < min_step) {
                // Écart trop petit mais positif = continue mais pas idéal
                seq_length++;
                total_step_quality += 0.3f;  // Pénalité
            } else {
                // Séquence cassée
                break;
            }
        }
        
        float avg_quality = valid_steps > 0 ? total_step_quality / valid_steps : 0;
        
        // Garder la meilleure séquence
        if (seq_length > best_seq_length || 
            (seq_length == best_seq_length && avg_quality > best_step_quality)) {
            best_seq_start = start_idx;
            best_seq_length = seq_length;
            best_step_quality = avg_quality;
            best_has_rect = has_rect;
        }
    }
    
    // Remplir le résultat
    if (best_seq_length >= DOW_MIN_POINTS_FORMING && best_seq_start >= 0) {
        info.is_valid_start = (best_seq_length >= DOW_MIN_POINTS_CONFIRMED);
        info.sequence_length = best_seq_length;
        info.step_quality = best_step_quality;
        info.has_rectangle = best_has_rect;
        info.first_point_price = sorted[best_seq_start].price;
        info.last_point_price = sorted[best_seq_start + best_seq_length - 1].price;
        info.first_bar_index = sorted[best_seq_start].bar_index;
        info.last_bar_index = sorted[best_seq_start + best_seq_length - 1].bar_index;
        info.bars_since_start = current_bar - info.first_bar_index;
        info.is_fresh = (current_bar - info.last_bar_index) <= DOW_FRESH_TREND_BARS;
        
        snprintf(info.details, sizeof(info.details),
                 "UPTREND: %d🟢 asc (%.2f→%.2f) | Qualité=%.0f%% | %s | %s",
                 best_seq_length, info.first_point_price, info.last_point_price,
                 best_step_quality * 100,
                 best_has_rect ? "RECT✓" : "NoRect",
                 info.is_fresh ? "FRAIS" : "Mature");
    } else {
        snprintf(info.details, sizeof(info.details), "Pas de séquence UP valide");
    }
    
    return info;
}

TrendStartInfo DetectTrendStart_DOWN(const std::vector<DowPoint>& reds, 
                                      int current_bar, float tick_size, bool is_nq) {
    TrendStartInfo info;
    memset(&info, 0, sizeof(TrendStartInfo));
    
    if (reds.size() < DOW_MIN_POINTS_FORMING) {
        snprintf(info.details, sizeof(info.details), "Pas assez de 🔴 (%zu)", reds.size());
        return info;
    }
    
    // Trier par bar_index (du plus ancien au plus récent)
    std::vector<DowPoint> sorted = reds;
    std::sort(sorted.begin(), sorted.end(),
              [](const DowPoint& a, const DowPoint& b) { return a.bar_index < b.bar_index; });
    
    float min_step = is_nq ? DOW_MIN_STEP_TICKS_NQ : DOW_MIN_STEP_TICKS_ES;
    
    // Chercher la plus longue séquence DESCENDANTE valide
    int best_seq_start = -1;
    int best_seq_length = 0;
    float best_step_quality = 0;
    bool best_has_rect = false;
    
    for (size_t start_idx = 0; start_idx < sorted.size(); start_idx++) {
        int seq_length = 1;
        float total_step_quality = 0;
        bool has_rect = sorted[start_idx].is_rectangle;
        int valid_steps = 0;
        
        for (size_t j = start_idx + 1; j < sorted.size(); j++) {
            float price_diff = sorted[j-1].price - sorted[j].price;  // Inversé pour descendant
            float step_ticks = price_diff / tick_size;
            int bar_diff = sorted[j].bar_index - sorted[j-1].bar_index;
            
            // Vérifier si cette boule continue la séquence descendante
            if (step_ticks >= min_step && bar_diff <= DOW_MAX_BARS_BETWEEN_POINTS) {
                seq_length++;
                valid_steps++;
                
                float step_ratio = step_ticks / (min_step * 3);
                if (step_ratio > 1.0f) step_ratio = 1.0f;
                total_step_quality += step_ratio;
                
                if (sorted[j].is_rectangle) has_rect = true;
            } else if (step_ticks > 0 && step_ticks < min_step) {
                seq_length++;
                total_step_quality += 0.3f;
            } else {
                break;
            }
        }
        
        float avg_quality = valid_steps > 0 ? total_step_quality / valid_steps : 0;
        
        if (seq_length > best_seq_length || 
            (seq_length == best_seq_length && avg_quality > best_step_quality)) {
            best_seq_start = start_idx;
            best_seq_length = seq_length;
            best_step_quality = avg_quality;
            best_has_rect = has_rect;
        }
    }
    
    // Remplir le résultat
    if (best_seq_length >= DOW_MIN_POINTS_FORMING && best_seq_start >= 0) {
        info.is_valid_start = (best_seq_length >= DOW_MIN_POINTS_CONFIRMED);
        info.sequence_length = best_seq_length;
        info.step_quality = best_step_quality;
        info.has_rectangle = best_has_rect;
        info.first_point_price = sorted[best_seq_start].price;
        info.last_point_price = sorted[best_seq_start + best_seq_length - 1].price;
        info.first_bar_index = sorted[best_seq_start].bar_index;
        info.last_bar_index = sorted[best_seq_start + best_seq_length - 1].bar_index;
        info.bars_since_start = current_bar - info.first_bar_index;
        info.is_fresh = (current_bar - info.last_bar_index) <= DOW_FRESH_TREND_BARS;
        
        snprintf(info.details, sizeof(info.details),
                 "DOWNTREND: %d🔴 desc (%.2f→%.2f) | Qualité=%.0f%% | %s | %s",
                 best_seq_length, info.first_point_price, info.last_point_price,
                 best_step_quality * 100,
                 best_has_rect ? "RECT✓" : "NoRect",
                 info.is_fresh ? "FRAIS" : "Mature");
    } else {
        snprintf(info.details, sizeof(info.details), "Pas de séquence DOWN valide");
    }
    
    return info;
}

DowAnalysis AnalyzeDowTrend(const DowHybridHistory& history, float current_price, 
                            float tick_size, bool is_nq, int current_bar) {
    
    DowAnalysis result;
    memset(&result, 0, sizeof(DowAnalysis));
    result.state = DOW_NONE;
    result.confidence = DOW_CONFIDENCE_NONE;
    result.recommended_direction = 0;
    
    int n_greens = history.green_points.size();
    int n_reds = history.red_points.size();
    
    result.total_green_points = n_greens;
    result.total_red_points = n_reds;
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🚀 DÉTECTION DU DÉPART - UPTREND
    // ═══════════════════════════════════════════════════════════════════════════
    
    TrendStartInfo up_start = DetectTrendStart_UP(history.green_points, current_bar, tick_size, is_nq);
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🚀 DÉTECTION DU DÉPART - DOWNTREND
    // ═══════════════════════════════════════════════════════════════════════════
    
    TrendStartInfo down_start = DetectTrendStart_DOWN(history.red_points, current_bar, tick_size, is_nq);
    
    // ═══════════════════════════════════════════════════════════════════════════
    // DÉTERMINER QUELLE TENDANCE EST DOMINANTE
    // ═══════════════════════════════════════════════════════════════════════════
    
    result.ascending_greens = up_start.sequence_length;
    result.descending_reds = down_start.sequence_length;
    result.last_hl = up_start.last_point_price;
    result.last_lh = down_start.last_point_price;
    
    std::ostringstream reason;
    
    // Comparer les deux tendances
    bool prefer_up = false;
    bool prefer_down = false;
    
    if (up_start.is_valid_start && down_start.is_valid_start) {
        // Les deux sont valides - choisir la plus forte/fraîche
        if (up_start.sequence_length > down_start.sequence_length) {
            prefer_up = true;
        } else if (down_start.sequence_length > up_start.sequence_length) {
            prefer_down = true;
        } else {
            // Même longueur - prendre la plus fraîche
            prefer_up = up_start.is_fresh && !down_start.is_fresh;
            prefer_down = down_start.is_fresh && !up_start.is_fresh;
            if (!prefer_up && !prefer_down) {
                // Prendre celle avec meilleure qualité
                prefer_up = up_start.step_quality > down_start.step_quality;
                prefer_down = !prefer_up;
            }
        }
    } else {
        prefer_up = up_start.is_valid_start;
        prefer_down = down_start.is_valid_start;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // ASSIGNER L'ÉTAT FINAL
    // ═══════════════════════════════════════════════════════════════════════════
    
    if (prefer_up) {
        result.recommended_direction = 1;
        result.sl_reference = up_start.first_point_price;  // SL sous la BASE (première 🟢)
        
        if (up_start.sequence_length >= DOW_MIN_POINTS_STRONG) {
            result.state = DOW_STRONG_UP;
            result.confidence = up_start.has_rectangle ? DOW_CONFIDENCE_WITH_RECT : DOW_CONFIDENCE_STRONG;
            reason << "🚀 UPTREND FORT DÉMARRÉ! ";
        } else if (up_start.sequence_length >= DOW_MIN_POINTS_CONFIRMED) {
            result.state = DOW_CONFIRMED_UP;
            result.confidence = up_start.has_rectangle ? DOW_CONFIDENCE_WITH_RECT : DOW_CONFIDENCE_CONFIRMED;
            reason << "🚀 UPTREND CONFIRMÉ (DÉPART OK)! ";
        } else {
            result.state = DOW_FORMING_UP;
            result.confidence = DOW_CONFIDENCE_FORMING;
            reason << "⏳ UPTREND EN FORMATION (ATTENDRE 3ème 🟢)! ";
        }
        
        reason << up_start.details;
        
        if (up_start.is_fresh) {
            reason << " | 🔥 TENDANCE FRAÎCHE";
            result.confidence += 0.05f;
        }
    }
    else if (prefer_down) {
        result.recommended_direction = -1;
        result.sl_reference = down_start.first_point_price;  // SL au-dessus de la BASE (première 🔴)
        
        if (down_start.sequence_length >= DOW_MIN_POINTS_STRONG) {
            result.state = DOW_STRONG_DOWN;
            result.confidence = down_start.has_rectangle ? DOW_CONFIDENCE_WITH_RECT : DOW_CONFIDENCE_STRONG;
            reason << "🚀 DOWNTREND FORT DÉMARRÉ! ";
        } else if (down_start.sequence_length >= DOW_MIN_POINTS_CONFIRMED) {
            result.state = DOW_CONFIRMED_DOWN;
            result.confidence = down_start.has_rectangle ? DOW_CONFIDENCE_WITH_RECT : DOW_CONFIDENCE_CONFIRMED;
            reason << "🚀 DOWNTREND CONFIRMÉ (DÉPART OK)! ";
        } else {
            result.state = DOW_FORMING_DOWN;
            result.confidence = DOW_CONFIDENCE_FORMING;
            reason << "⏳ DOWNTREND EN FORMATION (ATTENDRE 3ème 🔴)! ";
        }
        
        reason << down_start.details;
        
        if (down_start.is_fresh) {
            reason << " | 🔥 TENDANCE FRAÎCHE";
            result.confidence += 0.05f;
        }
    }
    else {
        // Pas de tendance valide
        if (up_start.sequence_length == DOW_MIN_POINTS_FORMING) {
            result.state = DOW_FORMING_UP;
            result.confidence = DOW_CONFIDENCE_FORMING;
            reason << "⏳ " << up_start.details << " | ATTENDRE CONFIRMATION";
        } else if (down_start.sequence_length == DOW_MIN_POINTS_FORMING) {
            result.state = DOW_FORMING_DOWN;
            result.confidence = DOW_CONFIDENCE_FORMING;
            reason << "⏳ " << down_start.details << " | ATTENDRE CONFIRMATION";
        } else if (n_greens > 0 || n_reds > 0) {
            result.state = DOW_RANGE;
            result.confidence = 0.2f;
            reason << "📊 RANGE/CONSOLIDATION: 🟢=" << n_greens << " 🔴=" << n_reds;
            reason << " | Pas de séquence valide détectée";
        } else {
            reason << "❌ PAS DE DONNÉES: Aucune boule détectée";
        }
    }
    
    // Ajouter info sur proximité du prix
    if (result.last_hl > 0) {
        float dist = fabs(current_price - result.last_hl) / tick_size;
        reason << " | Prix à " << std::fixed << std::setprecision(1) << dist << "t du dernier HL";
    }
    
    // Limiter la confiance à 1.0
    if (result.confidence > 1.0f) result.confidence = 1.0f;
    
    snprintf(result.reason, sizeof(result.reason), "%s", reason.str().c_str());
    
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7: RÈGLES D'OR
// ═══════════════════════════════════════════════════════════════════════════════

struct GoldenRuleResult {
    bool blocked;           // Signal bloqué
    bool has_bonus;         // Bonus (voie libre)
    float buyer_strength;
    float seller_strength;
    char reason[256];
};

// ═══════════════════════════════════════════════════════════════════════════════
// 🏆 RÈGLE D'OR ABSOLUE - VÉRIFICATION CONTINUE DE LA TENDANCE
// ═══════════════════════════════════════════════════════════════════════════════
//
// RÈGLE FONDAMENTALE DE DOW:
// ─────────────────────────────────────────────────────────────────────────────
// UPTREND VALIDE tant qu'AUCUNE 🔴 ne ferme SOUS la BASE des 🟢 (- buffer)
// → Si 🔴 apparaît à un prix < (dernière_🟢 - buffer) = TENDANCE CASSÉE!
//
// DOWNTREND VALIDE tant qu'AUCUNE 🟢 ne ferme AU-DESSUS de la BASE des 🔴 (+ buffer)  
// → Si 🟢 apparaît à un prix > (dernière_🔴 + buffer) = TENDANCE CASSÉE!
//
// Le BUFFER évite les faux signaux (bruit de marché)
// ═══════════════════════════════════════════════════════════════════════════════

GoldenRuleAbsolute CheckGoldenRuleAbsolute(const DowHybridHistory& history, 
                                            const DowAnalysis& dow,
                                            float current_price,
                                            float tick_size, 
                                            bool is_nq) {
    
    GoldenRuleAbsolute result;
    memset(&result, 0, sizeof(GoldenRuleAbsolute));
    result.trend_valid = true;
    result.trend_broken = false;
    result.trend_direction = dow.recommended_direction;
    
    // Buffer selon le symbole
    float buffer = is_nq ? GOLDEN_RULE_BUFFER_NQ : GOLDEN_RULE_BUFFER_ES;
    result.buffer_used = buffer;
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CAS 1: UPTREND - Vérifier qu'aucune 🔴 n'est sous la base des 🟢
    // ═══════════════════════════════════════════════════════════════════════════
    
    if (dow.state == DOW_FORMING_UP || dow.state == DOW_CONFIRMED_UP || dow.state == DOW_STRONG_UP) {
        
        // Trouver le niveau le plus bas des 🟢 (la BASE)
        float green_base = 999999.0f;
        for (const auto& green : history.green_points) {
            if (green.price < green_base) {
                green_base = green.price;
            }
        }
        result.green_base_level = green_base;
        
        // Niveau critique: BASE - buffer
        float critical_level = green_base - (buffer * tick_size);
        
        // Vérifier si une 🔴 est apparue SOUS ce niveau critique
        for (const auto& red : history.red_points) {
            if (red.price < critical_level) {
                // 🚨 VIOLATION DE LA RÈGLE D'OR!
                result.trend_valid = false;
                result.trend_broken = true;
                result.violation_price = red.price;
                result.violation_bar = red.bar_index;
                
                snprintf(result.status, sizeof(result.status),
                         "🚨 UPTREND CASSE! 🔴 à %.2f < BASE_VERTE %.2f - buffer %.0ft = %.2f",
                         red.price, green_base, buffer, critical_level);
                return result;
            }
        }
        
        // Tendance intacte
        snprintf(result.status, sizeof(result.status),
                 "✅ UPTREND VALIDE: Aucune 🔴 sous BASE_VERTE %.2f (seuil=%.2f)",
                 green_base, critical_level);
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CAS 2: DOWNTREND - Vérifier qu'aucune 🟢 n'est au-dessus de la base des 🔴
    // ═══════════════════════════════════════════════════════════════════════════
    
    else if (dow.state == DOW_FORMING_DOWN || dow.state == DOW_CONFIRMED_DOWN || dow.state == DOW_STRONG_DOWN) {
        
        // Trouver le niveau le plus haut des 🔴 (la BASE)
        float red_base = 0.0f;
        for (const auto& red : history.red_points) {
            if (red.price > red_base) {
                red_base = red.price;
            }
        }
        result.red_base_level = red_base;
        
        // Niveau critique: BASE + buffer
        float critical_level = red_base + (buffer * tick_size);
        
        // Vérifier si une 🟢 est apparue AU-DESSUS de ce niveau critique
        for (const auto& green : history.green_points) {
            if (green.price > critical_level) {
                // 🚨 VIOLATION DE LA RÈGLE D'OR!
                result.trend_valid = false;
                result.trend_broken = true;
                result.violation_price = green.price;
                result.violation_bar = green.bar_index;
                
                snprintf(result.status, sizeof(result.status),
                         "🚨 DOWNTREND CASSE! 🟢 à %.2f > BASE_ROUGE %.2f + buffer %.0ft = %.2f",
                         green.price, red_base, buffer, critical_level);
                return result;
            }
        }
        
        // Tendance intacte
        snprintf(result.status, sizeof(result.status),
                 "✅ DOWNTREND VALIDE: Aucune 🟢 au-dessus BASE_ROUGE %.2f (seuil=%.2f)",
                 red_base, critical_level);
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CAS 3: PAS DE TENDANCE
    // ═══════════════════════════════════════════════════════════════════════════
    
    else {
        result.trend_direction = 0;
        snprintf(result.status, sizeof(result.status),
                 "⚠️ PAS DE TENDANCE ÉTABLIE - Règle d'or non applicable");
    }
    
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🔄 DÉTECTION DE RETOURNEMENT (DOW_REVERSAL)
// ═══════════════════════════════════════════════════════════════════════════════
//
// Principe: Si tendance DOWN active et apparition de 2+ 🟢 ascendantes
//           → Alerte de retournement potentiel UP
//           → Bloquer les nouveaux SHORT
//           → Si 3ème 🟢 arrive → Reversal CONFIRMÉ
//
// ═══════════════════════════════════════════════════════════════════════════════

ReversalAlert DetectReversal(const DowHybridHistory& history, 
                              DowState current_state,
                              int current_bar, float tick_size, bool is_nq) {
    
    ReversalAlert alert;
    memset(&alert, 0, sizeof(ReversalAlert));
    
    float min_step = is_nq ? DOW_MIN_STEP_TICKS_NQ : DOW_MIN_STEP_TICKS_ES;
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CAS 1: DOWNTREND actif → Chercher reversal UP (🟢 ascendantes)
    // ═══════════════════════════════════════════════════════════════════════════
    
    if (current_state == DOW_CONFIRMED_DOWN || current_state == DOW_STRONG_DOWN) {
        
        // Chercher les 🟢 récentes
        std::vector<DowPoint> recent_greens;
        for (const auto& green : history.green_points) {
            if (current_bar - green.bar_index <= DOW_MAX_BARS_BETWEEN_POINTS * 2) {
                recent_greens.push_back(green);
            }
        }
        
        // Trier par bar_index
        std::sort(recent_greens.begin(), recent_greens.end(),
                  [](const DowPoint& a, const DowPoint& b) { return a.bar_index < b.bar_index; });
        
        // Compter les 🟢 ascendantes
        int ascending_count = 0;
        float last_price = 0;
        float first_price = 0;
        
        for (size_t i = 0; i < recent_greens.size(); i++) {
            if (i == 0) {
                first_price = recent_greens[i].price;
                last_price = recent_greens[i].price;
                ascending_count = 1;
            } else {
                float step = (recent_greens[i].price - last_price) / tick_size;
                if (step >= min_step * 0.5f) {  // Seuil réduit pour détecter tôt
                    ascending_count++;
                    last_price = recent_greens[i].price;
                }
            }
        }
        
        if (ascending_count >= 2) {
            alert.is_active = true;
            alert.potential_direction = 1;  // Potentiel UP
            alert.opposing_points = ascending_count;
            alert.is_confirmed = (ascending_count >= 3);
            alert.block_old_direction = true;  // Bloquer les SHORT
            alert.first_opposing_price = first_price;
            alert.last_opposing_price = last_price;
            
            if (alert.is_confirmed) {
                snprintf(alert.alert_message, sizeof(alert.alert_message),
                         "🔄 REVERSAL UP CONFIRMÉ! %d🟢 ascendantes (%.2f→%.2f) | SHORT BLOQUÉ + Préparer LONG",
                         ascending_count, first_price, last_price);
            } else {
                snprintf(alert.alert_message, sizeof(alert.alert_message),
                         "⚠️ ALERTE REVERSAL UP: %d🟢 détectées | SHORT BLOQUÉ | Attendre 3ème 🟢",
                         ascending_count);
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CAS 2: UPTREND actif → Chercher reversal DOWN (🔴 descendantes)
    // ═══════════════════════════════════════════════════════════════════════════
    
    else if (current_state == DOW_CONFIRMED_UP || current_state == DOW_STRONG_UP) {
        
        // Chercher les 🔴 récentes
        std::vector<DowPoint> recent_reds;
        for (const auto& red : history.red_points) {
            if (current_bar - red.bar_index <= DOW_MAX_BARS_BETWEEN_POINTS * 2) {
                recent_reds.push_back(red);
            }
        }
        
        // Trier par bar_index
        std::sort(recent_reds.begin(), recent_reds.end(),
                  [](const DowPoint& a, const DowPoint& b) { return a.bar_index < b.bar_index; });
        
        // Compter les 🔴 descendantes
        int descending_count = 0;
        float last_price = 0;
        float first_price = 0;
        
        for (size_t i = 0; i < recent_reds.size(); i++) {
            if (i == 0) {
                first_price = recent_reds[i].price;
                last_price = recent_reds[i].price;
                descending_count = 1;
            } else {
                float step = (last_price - recent_reds[i].price) / tick_size;
                if (step >= min_step * 0.5f) {
                    descending_count++;
                    last_price = recent_reds[i].price;
                }
            }
        }
        
        if (descending_count >= 2) {
            alert.is_active = true;
            alert.potential_direction = -1;  // Potentiel DOWN
            alert.opposing_points = descending_count;
            alert.is_confirmed = (descending_count >= 3);
            alert.block_old_direction = true;  // Bloquer les LONG
            alert.first_opposing_price = first_price;
            alert.last_opposing_price = last_price;
            
            if (alert.is_confirmed) {
                snprintf(alert.alert_message, sizeof(alert.alert_message),
                         "🔄 REVERSAL DOWN CONFIRMÉ! %d🔴 descendantes (%.2f→%.2f) | LONG BLOQUÉ + Préparer SHORT",
                         descending_count, first_price, last_price);
            } else {
                snprintf(alert.alert_message, sizeof(alert.alert_message),
                         "⚠️ ALERTE REVERSAL DOWN: %d🔴 détectées | LONG BLOQUÉ | Attendre 3ème 🔴",
                         descending_count);
            }
        }
    }
    
    return alert;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🔄 CALCUL DE LA MATURITÉ DE TENDANCE
// ═══════════════════════════════════════════════════════════════════════════════

TrendMaturityInfo CalculateTrendMaturity(int sequence_length, bool is_nq) {
    
    TrendMaturityInfo info;
    memset(&info, 0, sizeof(TrendMaturityInfo));
    info.point_count = sequence_length;
    
    if (sequence_length < DOW_MIN_POINTS_FORMING) {
        info.level = MATURITY_NONE;
        info.tp_multiplier = 1.0f;
        info.trailing_ticks = is_nq ? TRAILING_FRESH_TICKS_NQ : TRAILING_FRESH_TICKS_ES;
        info.should_enter = false;
        snprintf(info.description, sizeof(info.description), "Pas de tendance (<2 boules)");
    }
    else if (sequence_length == DOW_MIN_POINTS_FORMING) {
        info.level = MATURITY_FORMING;
        info.tp_multiplier = 1.0f;
        info.trailing_ticks = is_nq ? TRAILING_FRESH_TICKS_NQ : TRAILING_FRESH_TICKS_ES;
        info.should_enter = false;  // NE PAS ENTRER - attendre confirmation
        snprintf(info.description, sizeof(info.description), "EN FORMATION (2 boules) - ATTENDRE");
    }
    else if (sequence_length >= DOW_MIN_POINTS_CONFIRMED && sequence_length < DOW_MATURITY_MATURE) {
        info.level = MATURITY_FRESH;
        info.tp_multiplier = 1.0f;
        info.trailing_ticks = is_nq ? TRAILING_FRESH_TICKS_NQ : TRAILING_FRESH_TICKS_ES;
        info.should_enter = true;  // OPTIMAL POUR ENTRER
        snprintf(info.description, sizeof(info.description), "FRAÎCHE (%d boules) - OPTIMAL!", sequence_length);
    }
    else if (sequence_length >= DOW_MATURITY_MATURE && sequence_length < DOW_MATURITY_EXTENDED) {
        info.level = MATURITY_MATURE;
        info.tp_multiplier = 1.0f;
        info.trailing_ticks = is_nq ? TRAILING_MATURE_TICKS_NQ : TRAILING_MATURE_TICKS_ES;
        info.should_enter = true;  // Peut entrer mais trailing serré
        snprintf(info.description, sizeof(info.description), "MATURE (%d boules) - Trailing SERRÉ", sequence_length);
    }
    else {  // >= DOW_MATURITY_EXTENDED
        info.level = MATURITY_EXTENDED;
        info.tp_multiplier = DOW_TP_REDUCTION_EXTENDED;  // Réduire TP de 30%
        info.trailing_ticks = is_nq ? TRAILING_EXTENDED_TICKS_NQ : TRAILING_EXTENDED_TICKS_ES;
        info.should_enter = true;  // Peut entrer mais TP réduit
        snprintf(info.description, sizeof(info.description), 
                 "ÉTENDUE (%d boules) - TP réduit 30%% + Trailing TRÈS SERRÉ", sequence_length);
    }
    
    return info;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🕐 FILTRE SESSION
// ═══════════════════════════════════════════════════════════════════════════════

SessionFilter CheckSessionQuality(SCStudyInterfaceRef sc, bool filter_enabled) {
    
    SessionFilter filter;
    memset(&filter, 0, sizeof(SessionFilter));
    filter.is_enabled = filter_enabled;
    
    if (!filter_enabled) {
        filter.is_high_quality = true;
        filter.confidence_modifier = 1.0f;
        snprintf(filter.session_name, sizeof(filter.session_name), "FILTER_OFF");
        return filter;
    }
    
    // Obtenir l'heure actuelle (ET - Eastern Time, défaut Sierra Chart)
    SCDateTime current_time = sc.CurrentSystemDateTime;
    int hour = current_time.GetHour();
    int minute = current_time.GetMinute();
    int time_minutes = hour * 60 + minute;
    
    // Définir les sessions (en minutes depuis minuit ET)
    const int US_PREMARKET_START = 8 * 60;      // 08:00 ET
    const int US_OPEN = 9 * 60 + 30;            // 09:30 ET
    const int US_MORNING_END = 11 * 60 + 30;    // 11:30 ET
    const int US_LUNCH_END = 14 * 60;           // 14:00 ET
    const int US_CLOSE = 16 * 60;               // 16:00 ET
    const int OVERNIGHT_START = 18 * 60;        // 18:00 ET
    const int ASIAN_END = 3 * 60;               // 03:00 ET
    const int EUROPE_START = 3 * 60;            // 03:00 ET
    const int EUROPE_END = 8 * 60;              // 08:00 ET
    
    // Évaluer la qualité de la session
    if (time_minutes >= US_OPEN && time_minutes < US_MORNING_END) {
        // US Open + Morning = MEILLEURE session
        filter.is_high_quality = true;
        filter.confidence_modifier = 1.0f;
        snprintf(filter.session_name, sizeof(filter.session_name), "US_OPEN (BEST)");
    }
    else if (time_minutes >= US_LUNCH_END && time_minutes < US_CLOSE) {
        // US Afternoon = Bonne session
        filter.is_high_quality = true;
        filter.confidence_modifier = 1.0f;
        snprintf(filter.session_name, sizeof(filter.session_name), "US_AFTERNOON");
    }
    else if (time_minutes >= US_PREMARKET_START && time_minutes < US_OPEN) {
        // US Pre-Market = Session moyenne
        filter.is_high_quality = false;
        filter.confidence_modifier = 0.9f;  // -10%
        snprintf(filter.session_name, sizeof(filter.session_name), "US_PREMARKET");
    }
    else if (time_minutes >= EUROPE_START && time_minutes < EUROPE_END) {
        // European = Session moyenne
        filter.is_high_quality = false;
        filter.confidence_modifier = 0.85f;  // -15%
        snprintf(filter.session_name, sizeof(filter.session_name), "EUROPEAN");
    }
    else if (time_minutes >= US_MORNING_END && time_minutes < US_LUNCH_END) {
        // US Lunch = ÉVITER
        filter.is_high_quality = false;
        filter.confidence_modifier = 0.7f;  // -30%
        snprintf(filter.session_name, sizeof(filter.session_name), "US_LUNCH (AVOID)");
    }
    else {
        // Overnight/Asian = Faible volume
        filter.is_high_quality = false;
        filter.confidence_modifier = 0.8f;  // -20%
        snprintf(filter.session_name, sizeof(filter.session_name), "OVERNIGHT/ASIAN");
    }
    
    return filter;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 📦 DÉTECTION INTELLIGENTE DU RANGE - FONCTION PRINCIPALE
// ═══════════════════════════════════════════════════════════════════════════════

RangeDetection DetectRange(SCStudyInterfaceRef sc, int chart_fp, int chart_bar,
                           const DowHybridHistory& history,
                           const DowAnalysis& dow,
                           float current_price, float tick_size, bool is_nq) {
    
    RangeDetection range;
    memset(&range, 0, sizeof(RangeDetection));
    
    float max_range_size = is_nq ? RANGE_MAX_SIZE_NQ : RANGE_MAX_SIZE_ES;
    
    // Collecter toutes les boules récentes (dans les X dernières barres)
    int current_bar = sc.ArraySize - 1;
    std::vector<DowPoint> recent_greens;
    std::vector<DowPoint> recent_reds;
    
    for (const auto& green : history.green_points) {
        if (current_bar - green.bar_index <= RANGE_LOOKBACK_BARS) {
            recent_greens.push_back(green);
        }
    }
    for (const auto& red : history.red_points) {
        if (current_bar - red.bar_index <= RANGE_LOOKBACK_BARS) {
            recent_reds.push_back(red);
        }
    }
    
    int total_greens = recent_greens.size();
    int total_reds = recent_reds.size();
    int total_points = total_greens + total_reds;
    
    // Pas assez de points pour un range
    if (total_points < RANGE_MIN_POINTS) {
        snprintf(range.description, sizeof(range.description),
                 "Pas assez de points récents (%d < %d)", total_points, RANGE_MIN_POINTS);
        return range;
    }
    
    // Calculer les bornes du range (min/max de TOUTES les boules)
    float all_min = 999999.0f;
    float all_max = 0.0f;
    
    for (const auto& g : recent_greens) {
        if (g.price < all_min) all_min = g.price;
        if (g.price > all_max) all_max = g.price;
    }
    for (const auto& r : recent_reds) {
        if (r.price < all_min) all_min = r.price;
        if (r.price > all_max) all_max = r.price;
    }
    
    float range_size = (all_max - all_min) / tick_size;
    
    // Vérifier si l'écart vertical est assez petit pour un RANGE
    if (range_size > max_range_size) {
        snprintf(range.description, sizeof(range.description),
                 "Écart trop grand pour range (%.1ft > %.1ft max)", range_size, max_range_size);
        return range;
    }
    
    // Vérifier le mélange 🟢🔴
    float green_ratio = (float)total_greens / total_points;
    
    bool is_mixed = (green_ratio >= RANGE_MIX_RATIO_MIN && green_ratio <= RANGE_MIX_RATIO_MAX);
    
    if (!is_mixed && total_points >= 4) {
        // Pas un vrai range si une couleur domine trop (c'est une tendance)
        snprintf(range.description, sizeof(range.description),
                 "Pas un range: ratio 🟢=%.0f%% (doit être 25-75%%)", green_ratio * 100);
        return range;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // RANGE DÉTECTÉ!
    // ═══════════════════════════════════════════════════════════════════════════
    
    range.is_range = true;
    range.range_high = all_max;
    range.range_low = all_min;
    range.range_size_ticks = range_size;
    range.range_mid = (all_max + all_min) / 2.0f;
    range.total_points = total_points;
    range.green_count = total_greens;
    range.red_count = total_reds;
    range.green_ratio = green_ratio;
    
    // Vérifier si c'est après une attaque (plus significatif)
    range.is_after_attack = (dow.state == DOW_CONFIRMED_UP || dow.state == DOW_STRONG_UP ||
                             dow.state == DOW_CONFIRMED_DOWN || dow.state == DOW_STRONG_DOWN);
    
    // ═══════════════════════════════════════════════════════════════════════════
    // ANALYSER LE VOLUME DANS LE RANGE
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Collecter le volume sur les barres récentes
    float total_absorb_bid = 0;
    float total_absorb_ask = 0;
    int rect_green = 0;
    int rect_red = 0;
    
    // Scanner les barres du range pour le volume
    VisualSnapshot snap;
    for (int i = 0; i < RANGE_LOOKBACK_BARS && i < sc.ArraySize; i++) {
        CollectVisualSnapshot(sc, chart_fp, chart_bar, snap, is_nq, i);
        total_absorb_bid += snap.absorb_bid;
        total_absorb_ask += snap.absorb_ask;
        if (snap.long_down_up > 0) rect_green++;
        if (snap.long_up_down > 0) rect_red++;
    }
    
    range.absorb_bid_total = total_absorb_bid;
    range.absorb_ask_total = total_absorb_ask;
    range.rectangles_green = rect_green;
    range.rectangles_red = rect_red;
    
    // Calculer le biais de volume
    float total_absorb = total_absorb_bid + total_absorb_ask;
    if (total_absorb > 0) {
        range.volume_bias = (total_absorb_bid - total_absorb_ask) / total_absorb;
    } else {
        range.volume_bias = 0;
    }
    
    // Prédire la direction du breakout basée sur le volume
    // Plus d'absorptions BID = acheteurs accumulent = breakout UP probable
    // Plus d'absorptions ASK = vendeurs distribuent = breakout DOWN probable
    
    if (range.volume_bias > 0.2f || rect_green > rect_red) {
        range.breakout_up_likely = true;
    }
    if (range.volume_bias < -0.2f || rect_red > rect_green) {
        range.breakout_down_likely = true;
    }
    
    // Bloquer les trades si c'est un range après une attaque
    range.should_block_trades = range.is_after_attack || (range.is_range && total_points >= 4);
    
    // Construire la description
    std::ostringstream desc;
    desc << "📦 RANGE DÉTECTÉ: " << std::fixed << std::setprecision(2);
    desc << range.range_low << " - " << range.range_high;
    desc << " (" << std::setprecision(1) << range.range_size_ticks << "t)";
    desc << " | 🟢" << total_greens << " 🔴" << total_reds;
    
    if (range.breakout_up_likely && !range.breakout_down_likely) {
        desc << " | BREAKOUT UP probable (vol=" << std::setprecision(2) << range.volume_bias << ")";
    } else if (range.breakout_down_likely && !range.breakout_up_likely) {
        desc << " | BREAKOUT DOWN probable (vol=" << std::setprecision(2) << range.volume_bias << ")";
    } else {
        desc << " | Direction incertaine";
    }
    
    if (range.should_block_trades) {
        desc << " | ⛔ TRADES BLOQUÉS";
    }
    
    snprintf(range.description, sizeof(range.description), "%s", desc.str().c_str());
    
    return range;
}

// 🏆 RÈGLE D'OR #1: RATIO 1.5x - Bloquer si adversaire trop fort
GoldenRuleResult CheckGoldenRule1_Ratio(const VisualSnapshot& snap, int direction) {
    GoldenRuleResult result = {false, false, 0, 0, ""};
    
    result.buyer_strength = (float)snap.total_green;
    result.seller_strength = (float)snap.total_red;
    
    if (direction == 1) {  // LONG
        if (result.buyer_strength > 0 && result.seller_strength > result.buyer_strength * GOLDEN_RATIO) {
            result.blocked = true;
            snprintf(result.reason, sizeof(result.reason),
                     "REGLE OR #1 BLOQUE: Vendeurs trop forts (%.0f > %.0f x 1.5)",
                     result.seller_strength, result.buyer_strength);
        }
    } else if (direction == -1) {  // SHORT
        if (result.seller_strength > 0 && result.buyer_strength > result.seller_strength * GOLDEN_RATIO) {
            result.blocked = true;
            snprintf(result.reason, sizeof(result.reason),
                     "REGLE OR #1 BLOQUE: Acheteurs trop forts (%.0f > %.0f x 1.5)",
                     result.buyer_strength, result.seller_strength);
        }
    }
    
    return result;
}

// 🏆 RÈGLE D'OR #2: ABSENCE = CONFIRMATION - Bonus si voie libre
GoldenRuleResult CheckGoldenRule2_Absence(const VisualSnapshot& snap, int direction) {
    GoldenRuleResult result = {false, false, 0, 0, ""};
    
    float edge_buy = snap.edge_buy + snap.bar_edge_buy;
    float edge_sell = snap.edge_sell + snap.bar_edge_sell;
    
    if (direction == 1 && edge_sell == 0 && snap.long_up_down == 0) {
        result.has_bonus = true;
        snprintf(result.reason, sizeof(result.reason),
                 "REGLE OR #2 BONUS: Voie libre (edge_sell=0, pas de rectangle rouge)");
    } else if (direction == -1 && edge_buy == 0 && snap.long_down_up == 0) {
        result.has_bonus = true;
        snprintf(result.reason, sizeof(result.reason),
                 "REGLE OR #2 BONUS: Voie libre (edge_buy=0, pas de rectangle vert)");
    }
    
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8: GÉNÉRATION DE SIGNAL
// ═══════════════════════════════════════════════════════════════════════════════

TradeSignal GenerateSignal(SCStudyInterfaceRef sc, int chart_fp, int chart_bar,
                           DowHybridHistory& history, float current_price, 
                           float tick_size, bool is_nq,
                           int lookback_bars, bool session_filter_enabled,
                           bool reversal_detection_enabled, bool debug_mode,
                           float mq_nearest_level = 0) {
    
    TradeSignal signal;
    memset(&signal, 0, sizeof(TradeSignal));
    signal.is_valid = false;
    
    // 🕐 VÉRIFIER LA SESSION
    signal.session = CheckSessionQuality(sc, session_filter_enabled);
    
    // 1. COLLECTER LES POINTS (BOULES)
    CollectDowPoints(sc, chart_fp, chart_bar, history, tick_size, is_nq, debug_mode);
    
    // 2. ANALYSER LA TENDANCE DOW (CŒUR DU SYSTÈME)
    int current_bar = sc.ArraySize - 1;
    DowAnalysis dow = AnalyzeDowTrend(history, current_price, tick_size, is_nq, current_bar);
    history.last_analysis = dow;
    
    // 🔄 CALCULER LA MATURITÉ
    int seq_length = (dow.recommended_direction == 1) ? dow.ascending_greens : dow.descending_reds;
    signal.maturity = CalculateTrendMaturity(seq_length, is_nq);
    
    // 🔄 DÉTECTER LES RETOURNEMENTS
    if (reversal_detection_enabled) {
        signal.reversal = DetectReversal(history, dow.state, current_bar, tick_size, is_nq);
    }
    
    // 📦 DÉTECTER LES RANGES / BASES
    signal.range = DetectRange(sc, chart_fp, chart_bar, history, dow, current_price, tick_size, is_nq);
    
    // 3. COLLECTER LES INDICATEURS VISUELS
    VisualSnapshot snap;
    CollectVisualSnapshot(sc, chart_fp, chart_bar, snap, is_nq, 0);
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CONDITIONS D'ENTRÉE
    // ═══════════════════════════════════════════════════════════════════════════
    
    std::ostringstream reason;
    int dow_score = 0;
    int visual_score = 0;
    int rules_score = 0;
    int mq_bonus = 0;
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 0: RÈGLE D'OR ABSOLUE - VÉRIFIER SI TENDANCE ENCORE VALIDE
    // ─────────────────────────────────────────────────────────────────────────
    
    GoldenRuleAbsolute golden_rule = CheckGoldenRuleAbsolute(history, dow, current_price, tick_size, is_nq);
    signal.golden_rule = golden_rule;
    
    if (golden_rule.trend_broken) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason), 
                 "🚨 BLOQUE PAR RÈGLE D'OR ABSOLUE: %s", golden_rule.status);
        return signal;
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 0.5: REVERSAL DÉTECTÉ - BLOQUER L'ANCIEN SENS
    // ─────────────────────────────────────────────────────────────────────────
    
    if (signal.reversal.is_active && signal.reversal.block_old_direction) {
        // Si reversal UP détecté pendant un DOWNTREND → Bloquer les SHORT
        if (signal.reversal.potential_direction == 1 && dow.recommended_direction == -1) {
            history.signals_blocked++;
            snprintf(signal.reason, sizeof(signal.reason), 
                     "🔄 BLOQUE: %s", signal.reversal.alert_message);
            return signal;
        }
        // Si reversal DOWN détecté pendant un UPTREND → Bloquer les LONG
        if (signal.reversal.potential_direction == -1 && dow.recommended_direction == 1) {
            history.signals_blocked++;
            snprintf(signal.reason, sizeof(signal.reason), 
                     "🔄 BLOQUE: %s", signal.reversal.alert_message);
            return signal;
        }
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 0.6: RANGE DÉTECTÉ - BLOQUER TOUS LES TRADES
    // ─────────────────────────────────────────────────────────────────────────
    // Après une ATTAQUE, si les boules sont REGROUPÉES (range), on attend le BREAKOUT
    // ─────────────────────────────────────────────────────────────────────────
    
    if (signal.range.is_range && signal.range.should_block_trades) {
        history.signals_blocked++;
        
        // Indiquer la direction probable du breakout
        std::ostringstream range_msg;
        range_msg << "📦 BLOQUE - RANGE DÉTECTÉ: " << signal.range.description;
        
        if (signal.range.breakout_up_likely && !signal.range.breakout_down_likely) {
            range_msg << " | Préparer LONG au breakout";
        } else if (signal.range.breakout_down_likely && !signal.range.breakout_up_likely) {
            range_msg << " | Préparer SHORT au breakout";
        } else {
            range_msg << " | Attendre breakout clair";
        }
        
        snprintf(signal.reason, sizeof(signal.reason), "%s", range_msg.str().c_str());
        return signal;
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 1: TENDANCE DOW CONFIRMÉE (OBLIGATOIRE)
    // ─────────────────────────────────────────────────────────────────────────
    
    if (dow.state == DOW_NONE || dow.state == DOW_RANGE) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason), 
                 "BLOQUE: Pas de tendance Dow confirmee. %s", dow.reason);
        return signal;
    }
    
    // Score Dow
    if (dow.state == DOW_STRONG_UP || dow.state == DOW_STRONG_DOWN) {
        dow_score = 50;
        reason << "DOW FORT (50pts) | ";
    } else if (dow.state == DOW_CONFIRMED_UP || dow.state == DOW_CONFIRMED_DOWN) {
        dow_score = 40;
        reason << "DOW CONFIRME (40pts) | ";
    } else if (dow.state == DOW_FORMING_UP || dow.state == DOW_FORMING_DOWN) {
        dow_score = 25;
        reason << "DOW EN FORMATION (25pts) | ";
    }
    
    // Bonus si règle d'or absolue valide avec une belle marge
    if (golden_rule.trend_valid) {
        rules_score += 5;  // Bonus tendance saine
        reason << "TENDANCE_SAINE +5pts | ";
    }
    
    int direction = dow.recommended_direction;
    signal.direction = direction;
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 2: PRIX PROCHE D'UN NIVEAU DOW (OBLIGATOIRE)
    // ─────────────────────────────────────────────────────────────────────────
    
    float nearest_level = 0;
    float distance_ticks = 999;
    
    if (direction == 1) {  // LONG
        // Chercher la 🟢 la plus proche SOUS le prix
        for (const auto& green : history.green_points) {
            if (green.price < current_price) {
                float dist = (current_price - green.price) / tick_size;
                if (dist < distance_ticks) {
                    distance_ticks = dist;
                    nearest_level = green.price;
                }
            }
        }
    } else {  // SHORT
        // Chercher la 🔴 la plus proche AU-DESSUS du prix
        for (const auto& red : history.red_points) {
            if (red.price > current_price) {
                float dist = (red.price - current_price) / tick_size;
                if (dist < distance_ticks) {
                    distance_ticks = dist;
                    nearest_level = red.price;
                }
            }
        }
    }
    
    if (distance_ticks > DOW_PROXIMITY_TICKS) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason),
                 "BLOQUE: Prix trop loin du niveau Dow (%.1ft > %.1ft max). Niveau=%.2f",
                 distance_ticks, DOW_PROXIMITY_TICKS, nearest_level);
        return signal;
    }
    
    // Bonus si très proche
    if (distance_ticks <= 5) {
        dow_score += 10;
        reason << "PROCHE (<5t) +10pts | ";
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 3: CONFIRMATION VISUELLE (OBLIGATOIRE: au moins 1 indicateur)
    // ─────────────────────────────────────────────────────────────────────────
    
    bool has_visual_confirm = false;
    
    if (direction == 1) {  // LONG
        has_visual_confirm = (snap.color_up > 0 || snap.bar_color_up > 0 ||
                             snap.long_down_up > 0 ||  // Rectangle VERT
                             snap.edge_buy > 0 || snap.bar_edge_buy > 0);
        
        if (snap.long_down_up > 0) {
            visual_score += 30;  // Rectangle = très fort
            reason << "RECT_VERT +30pts | ";
        } else if (snap.edge_buy > 0 || snap.bar_edge_buy > 0) {
            visual_score += 20;
            reason << "EDGE_BUY +20pts | ";
        } else if (snap.color_up > 0 || snap.bar_color_up > 0) {
            visual_score += 15;
            reason << "COLOR_UP +15pts | ";
        }
    } else {  // SHORT
        has_visual_confirm = (snap.color_down > 0 || snap.bar_color_down > 0 ||
                             snap.long_up_down > 0 ||  // Rectangle ROUGE
                             snap.edge_sell > 0 || snap.bar_edge_sell > 0);
        
        if (snap.long_up_down > 0) {
            visual_score += 30;
            reason << "RECT_ROUGE +30pts | ";
        } else if (snap.edge_sell > 0 || snap.bar_edge_sell > 0) {
            visual_score += 20;
            reason << "EDGE_SELL +20pts | ";
        } else if (snap.color_down > 0 || snap.bar_color_down > 0) {
            visual_score += 15;
            reason << "COLOR_DOWN +15pts | ";
        }
    }
    
    if (!has_visual_confirm) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason),
                 "BLOQUE: Pas de confirmation visuelle dans le sens %s",
                 direction == 1 ? "LONG" : "SHORT");
        return signal;
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // CONDITION 4: RÈGLES D'OR
    // ─────────────────────────────────────────────────────────────────────────
    
    // Règle #1: Ratio 1.5x
    GoldenRuleResult rule1 = CheckGoldenRule1_Ratio(snap, direction);
    if (rule1.blocked) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason), "BLOQUE: %s", rule1.reason);
        return signal;
    }
    rules_score += 10;  // Règle #1 OK
    
    // Règle #2: Absence = Bonus
    GoldenRuleResult rule2 = CheckGoldenRule2_Absence(snap, direction);
    if (rule2.has_bonus) {
        rules_score += 10;
        reason << "VOIE_LIBRE +10pts | ";
    }
    
    // ─────────────────────────────────────────────────────────────────────────
    // BONUS: CONFLUENCE MENTHORQ (OPTIONNEL)
    // ─────────────────────────────────────────────────────────────────────────
    
    if (mq_nearest_level > 0) {
        float mq_distance = fabs(current_price - mq_nearest_level) / tick_size;
        if (mq_distance <= MQ_BONUS_DISTANCE_TICKS) {
            mq_bonus = MQ_BONUS_SCORE;
            reason << "MQ_CONFLUENCE +10pts | ";
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CALCUL DU SCORE TOTAL
    // ═══════════════════════════════════════════════════════════════════════════
    
    int total_score = dow_score + visual_score + rules_score + mq_bonus;
    
    // Seuil minimum pour trader
    const int MIN_SCORE_TRADE = 60;
    const int MIN_SCORE_STRONG = 80;
    
    if (total_score < MIN_SCORE_TRADE) {
        history.signals_blocked++;
        snprintf(signal.reason, sizeof(signal.reason),
                 "BLOQUE: Score insuffisant (%d < %d). %s",
                 total_score, MIN_SCORE_TRADE, reason.str().c_str());
        return signal;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // SIGNAL VALIDE - CALCULER SL/TP
    // ═══════════════════════════════════════════════════════════════════════════
    
    signal.is_valid = true;
    signal.dow_score = dow_score;
    signal.visual_score = visual_score;
    signal.rules_score = rules_score;
    signal.mq_bonus = mq_bonus;
    signal.total_score = total_score;
    signal.confidence = dow.confidence;
    
    signal.entry_price = current_price;
    
    // SL basé sur le dernier niveau Dow
    float sl_reference = dow.sl_reference;
    int sl_buffer_ticks = is_nq ? 5 : 3;
    
    // 🔄 TRAILING SELON LA MATURITÉ (PARAMÈTRES OPTIMAUX 25JAN2026)
    signal.trailing_distance = signal.maturity.trailing_ticks;
    signal.trailing_activation = is_nq ? TRAILING_ACTIVATION_NQ : TRAILING_ACTIVATION_ES;
    
    if (direction == 1) {  // LONG
        // SL sous la dernière 🟢 (Higher Low)
        signal.sl_price = sl_reference - (sl_buffer_ticks * tick_size);
        
        // TP: chercher la prochaine 🔴 (résistance) ou TP par défaut
        float nearest_resist = 0;
        for (const auto& red : history.red_points) {
            if (red.price > current_price) {
                if (nearest_resist == 0 || red.price < nearest_resist) {
                    nearest_resist = red.price;
                }
            }
        }
        
        if (nearest_resist > 0) {
            signal.tp_price = nearest_resist - (2 * tick_size);  // TP avant la 🔴
        } else {
            // TP par défaut (ES: 20 ticks, NQ: 35 ticks)
            int tp_default = is_nq ? 35 : 20;
            signal.tp_price = current_price + (tp_default * tick_size);
        }
        
        // 🔄 APPLIQUER RÉDUCTION TP SI TENDANCE ÉTENDUE
        if (signal.maturity.level == MATURITY_EXTENDED) {
            float tp_distance = signal.tp_price - current_price;
            tp_distance *= signal.maturity.tp_multiplier;  // Réduire de 30%
            signal.tp_price = current_price + tp_distance;
        }
    } else {  // SHORT
        // SL au-dessus de la dernière 🔴 (Lower High)
        signal.sl_price = sl_reference + (sl_buffer_ticks * tick_size);
        
        // TP: chercher la prochaine 🟢 (support) ou TP par défaut
        float nearest_support = 0;
        for (const auto& green : history.green_points) {
            if (green.price < current_price) {
                if (nearest_support == 0 || green.price > nearest_support) {
                    nearest_support = green.price;
                }
            }
        }
        
        if (nearest_support > 0) {
            signal.tp_price = nearest_support + (2 * tick_size);  // TP avant la 🟢
        } else {
            int tp_default = is_nq ? 35 : 20;
            signal.tp_price = current_price - (tp_default * tick_size);
        }
        
        // 🔄 APPLIQUER RÉDUCTION TP SI TENDANCE ÉTENDUE
        if (signal.maturity.level == MATURITY_EXTENDED) {
            float tp_distance = current_price - signal.tp_price;
            tp_distance *= signal.maturity.tp_multiplier;
            signal.tp_price = current_price - tp_distance;
        }
    }
    
    // 🕐 APPLIQUER MODIFICATEUR SESSION À LA CONFIANCE
    signal.confidence *= signal.session.confidence_modifier;
    
    // Construire la raison finale
    reason << "SCORE=" << total_score;
    if (total_score >= MIN_SCORE_STRONG) {
        reason << " [SIGNAL FORT]";
    }
    reason << " | SL=" << std::fixed << std::setprecision(2) << signal.sl_price;
    reason << " TP=" << signal.tp_price;
    
    snprintf(signal.reason, sizeof(signal.reason), "%s", reason.str().c_str());
    
    history.signals_generated++;
    history.signals_valid++;
    
    return signal;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9: STUDY PRINCIPALE
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_DowHybrid_System(SCStudyInterfaceRef sc) {
    
    // === INPUTS ===
    SCInputRef Input_ES_Footprint_Chart = sc.Input[0];
    SCInputRef Input_ES_Barres_Chart = sc.Input[1];
    SCInputRef Input_NQ_Footprint_Chart = sc.Input[2];
    SCInputRef Input_NQ_Barres_Chart = sc.Input[3];
    SCInputRef Input_ES_Enabled = sc.Input[4];          // 🆕 ES ON/OFF
    SCInputRef Input_NQ_Enabled = sc.Input[5];          // 🆕 NQ ON/OFF
    SCInputRef Input_Show_Dashboard = sc.Input[6];
    SCInputRef Input_Enable_Signals = sc.Input[7];
    SCInputRef Input_Lookback_Bars = sc.Input[8];       // Lookback configurable
    SCInputRef Input_Session_Filter = sc.Input[9];      // Filtre session ON/OFF
    SCInputRef Input_Reversal_Detection = sc.Input[10]; // Détection reversal ON/OFF
    SCInputRef Input_Debug_Mode = sc.Input[11];         // 🆕 DEBUG ON/OFF
    
    // === SUBGRAPHS ===
    SCSubgraphRef Subgraph_BuySignal = sc.Subgraph[0];
    SCSubgraphRef Subgraph_SellSignal = sc.Subgraph[1];
    SCSubgraphRef Subgraph_DowScore = sc.Subgraph[2];
    SCSubgraphRef Subgraph_TotalScore = sc.Subgraph[3];
    
    // === SETUP ===
    if (sc.SetDefaults) {
        sc.GraphName = "MIA Dow Hybrid System";
        sc.GraphRegion = 0;
        sc.AutoLoop = 0;  // 🔧 Manual loop (comme MIA_AutoTrader_BN) pour lire autres charts
        sc.UpdateAlways = 1;
        sc.FreeDLL = 1;   // 🔧 AJOUTÉ: Permet rechargement correct des données études
        
        // Inputs - MÊMES VALEURS PAR DÉFAUT QUE MIA_AutoTrader_BN
        Input_ES_Footprint_Chart.Name = "ES Footprint Chart #";
        Input_ES_Footprint_Chart.SetInt(1);   // Chart 1 = ES Footprint (Bataille Navale)
        
        Input_ES_Barres_Chart.Name = "ES Barres Chart #";
        Input_ES_Barres_Chart.SetInt(25);     // Chart 25 = ES 1min Barres
        
        Input_NQ_Footprint_Chart.Name = "NQ Footprint Chart #";
        Input_NQ_Footprint_Chart.SetInt(2);   // Chart 2 = NQ Footprint (Bataille Navale)
        
        Input_NQ_Barres_Chart.Name = "NQ Barres Chart #";
        Input_NQ_Barres_Chart.SetInt(23);     // Chart 23 = NQ 1min Barres
        
        // 🆕 ES/NQ Enabled (comme MIA_AutoTrader_BN)
        Input_ES_Enabled.Name = "ES Enabled";
        Input_ES_Enabled.SetYesNo(1);  // ON par défaut
        
        Input_NQ_Enabled.Name = "NQ Enabled";
        Input_NQ_Enabled.SetYesNo(0);  // OFF par défaut
        
        Input_Show_Dashboard.Name = "Show Dashboard";
        Input_Show_Dashboard.SetYesNo(1);
        
        Input_Enable_Signals.Name = "Enable Signals";
        Input_Enable_Signals.SetYesNo(1);
        
        // 🆕 Lookback configurable
        Input_Lookback_Bars.Name = "Lookback Bars (20-100)";
        Input_Lookback_Bars.SetInt(DOW_LOOKBACK_DEFAULT);
        Input_Lookback_Bars.SetIntLimits(DOW_LOOKBACK_MIN, DOW_LOOKBACK_MAX);
        
        // 🆕 Filtre session
        Input_Session_Filter.Name = "Session Filter (ON/OFF)";
        Input_Session_Filter.SetYesNo(1);  // Activé par défaut
        
        // 🆕 Détection reversal
        Input_Reversal_Detection.Name = "Reversal Detection (ON/OFF)";
        Input_Reversal_Detection.SetYesNo(1);  // Activé par défaut
        
        // 🆕 Debug Mode
        Input_Debug_Mode.Name = "Debug Mode (Write to File)";
        Input_Debug_Mode.SetYesNo(0);  // OFF par défaut
        
        // Subgraphs
        Subgraph_BuySignal.Name = "Buy Signal";
        Subgraph_BuySignal.DrawStyle = DRAWSTYLE_ARROW_UP;
        Subgraph_BuySignal.PrimaryColor = RGB(0, 255, 0);
        Subgraph_BuySignal.LineWidth = 3;
        
        Subgraph_SellSignal.Name = "Sell Signal";
        Subgraph_SellSignal.DrawStyle = DRAWSTYLE_ARROW_DOWN;
        Subgraph_SellSignal.PrimaryColor = RGB(255, 0, 0);
        Subgraph_SellSignal.LineWidth = 3;
        
        Subgraph_DowScore.Name = "Dow Score";
        Subgraph_DowScore.DrawStyle = DRAWSTYLE_LINE;
        Subgraph_DowScore.PrimaryColor = RGB(0, 200, 255);
        Subgraph_DowScore.LineWidth = 2;
        
        Subgraph_TotalScore.Name = "Total Score";
        Subgraph_TotalScore.DrawStyle = DRAWSTYLE_LINE;
        Subgraph_TotalScore.PrimaryColor = RGB(255, 200, 0);
        Subgraph_TotalScore.LineWidth = 2;
        
        return;
    }
    
    // 🔧 MANUAL LOOP (comme MIA_AutoTrader_BN)
    if (sc.Index < sc.ArraySize - 1) return;  // Ne traiter que la dernière barre
    
    // === LIRE LES INPUTS ES/NQ ENABLED ===
    bool es_enabled = Input_ES_Enabled.GetYesNo() != 0;
    bool nq_enabled = Input_NQ_Enabled.GetYesNo() != 0;
    bool debug_mode = Input_Debug_Mode.GetYesNo() != 0;  // 🆕 Lire le debug mode
    int lookback_bars = Input_Lookback_Bars.GetInt();
    bool session_filter_enabled = Input_Session_Filter.GetYesNo() != 0;
    bool reversal_detection_enabled = Input_Reversal_Detection.GetYesNo() != 0;
    
    // === PRIX ACTUEL ===
    float current_price = sc.Close[sc.ArraySize - 1];
    
    // === SIGNAUX ES ET NQ ===
    TradeSignal signal_es, signal_nq;
    memset(&signal_es, 0, sizeof(TradeSignal));
    memset(&signal_nq, 0, sizeof(TradeSignal));
    
    // Traiter ES si activé
    if (es_enabled) {
        int chart_fp_es = Input_ES_Footprint_Chart.GetInt();
        int chart_bar_es = Input_ES_Barres_Chart.GetInt();
        signal_es = GenerateSignal(sc, chart_fp_es, chart_bar_es, g_es_history, 
                                   current_price, 0.25f, false,
                                   lookback_bars, session_filter_enabled,
                                   reversal_detection_enabled, debug_mode, 0);  // 🔧 Ajout debug_mode
    }
    
    // Traiter NQ si activé
    if (nq_enabled) {
        int chart_fp_nq = Input_NQ_Footprint_Chart.GetInt();
        int chart_bar_nq = Input_NQ_Barres_Chart.GetInt();
        signal_nq = GenerateSignal(sc, chart_fp_nq, chart_bar_nq, g_nq_history, 
                                   current_price, 0.25f, true,
                                   lookback_bars, session_filter_enabled,
                                   reversal_detection_enabled, debug_mode, 0);  // 🔧 Ajout debug_mode
    }
    
    // Utiliser le signal prioritaire (ES si activé, sinon NQ)
    bool is_nq = !es_enabled && nq_enabled;
    TradeSignal& signal = es_enabled ? signal_es : signal_nq;
    DowHybridHistory& history = is_nq ? g_nq_history : g_es_history;
    
    // === AFFICHAGE DASHBOARD ===
    if (Input_Show_Dashboard.GetYesNo()) {
        std::ostringstream oss;
        
        oss << "═══════════════════════════════════════════════════════════════\n";
        oss << "  MIA DOW HYBRID SYSTEM - " << (is_nq ? "NQ" : "ES") << "\n";
        oss << "═══════════════════════════════════════════════════════════════\n\n";
        
        // Analyse Dow
        DowAnalysis& dow = history.last_analysis;
        oss << "📊 THÉORIE DE DOW (CŒUR)\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << "État: " << GetDowStateString(dow.state) << "\n";
        oss << "Confiance: " << std::fixed << std::setprecision(0) << (dow.confidence * 100) << "%\n\n";
        
        oss << "🚀 DÉTECTION DÉPART:\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << "🟢 Séquence UP: " << dow.ascending_greens << " boules ascendantes";
        if (dow.ascending_greens >= DOW_MIN_POINTS_CONFIRMED) {
            oss << " ✅ DÉPART CONFIRMÉ!";
        } else if (dow.ascending_greens >= DOW_MIN_POINTS_FORMING) {
            oss << " ⏳ En formation (attendre 3ème)";
        }
        oss << "\n";
        
        oss << "🔴 Séquence DOWN: " << dow.descending_reds << " boules descendantes";
        if (dow.descending_reds >= DOW_MIN_POINTS_CONFIRMED) {
            oss << " ✅ DÉPART CONFIRMÉ!";
        } else if (dow.descending_reds >= DOW_MIN_POINTS_FORMING) {
            oss << " ⏳ En formation (attendre 3ème)";
        }
        oss << "\n\n";
        
        oss << "📍 NIVEAUX DE RÉFÉRENCE:\n";
        if (dow.last_hl > 0) {
            oss << "  Dernier HL (🟢): " << std::fixed << std::setprecision(2) << dow.last_hl << "\n";
        }
        if (dow.last_lh > 0) {
            oss << "  Dernier LH (🔴): " << std::fixed << std::setprecision(2) << dow.last_lh << "\n";
        }
        if (dow.sl_reference > 0) {
            oss << "  BASE (pour SL): " << std::fixed << std::setprecision(2) << dow.sl_reference << "\n";
        }
        oss << "\n";
        
        // Règle d'Or Absolue
        oss << "🏆 RÈGLE D'OR ABSOLUE\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << signal.golden_rule.status << "\n";
        if (signal.golden_rule.green_base_level > 0) {
            oss << "BASE 🟢 (Support): " << std::fixed << std::setprecision(2) << signal.golden_rule.green_base_level << "\n";
        }
        if (signal.golden_rule.red_base_level > 0) {
            oss << "BASE 🔴 (Resist): " << std::fixed << std::setprecision(2) << signal.golden_rule.red_base_level << "\n";
        }
        oss << "Buffer utilisé: " << std::fixed << std::setprecision(0) << signal.golden_rule.buffer_used << " ticks\n\n";
        
        // 🔄 Alerte Reversal
        if (signal.reversal.is_active) {
            oss << "🔄 ALERTE REVERSAL\n";
            oss << "───────────────────────────────────────────────────────────────\n";
            oss << signal.reversal.alert_message << "\n";
            oss << "Points opposés: " << signal.reversal.opposing_points;
            if (signal.reversal.is_confirmed) {
                oss << " ✅ CONFIRMÉ";
            } else {
                oss << " ⏳ En attente 3ème boule";
            }
            oss << "\n\n";
        }
        
        // 🔄 Maturité
        oss << "🔄 MATURITÉ TENDANCE\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << signal.maturity.description << "\n";
        oss << "Trailing recommandé: " << std::fixed << std::setprecision(0) << signal.maturity.trailing_ticks << " ticks\n";
        if (signal.maturity.tp_multiplier < 1.0f) {
            oss << "⚠️ TP réduit de " << std::setprecision(0) << ((1.0f - signal.maturity.tp_multiplier) * 100) << "%\n";
        }
        oss << "\n";
        
        // 🕐 Session
        oss << "🕐 SESSION\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << "Session: " << signal.session.session_name << "\n";
        if (signal.session.is_enabled) {
            oss << "Qualité: " << (signal.session.is_high_quality ? "✅ HAUTE" : "⚠️ Moyenne/Faible") << "\n";
            if (signal.session.confidence_modifier < 1.0f) {
                oss << "Confiance ajustée: -" << std::setprecision(0) << ((1.0f - signal.session.confidence_modifier) * 100) << "%\n";
            }
        } else {
            oss << "Filtre: DÉSACTIVÉ\n";
        }
        oss << "\n";
        
        // 📦 Range / BASE
        oss << "📦 RANGE / BASE\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        if (signal.range.is_range) {
            oss << "⚠️ RANGE DÉTECTÉ!\n";
            oss << "Zone: " << std::fixed << std::setprecision(2) << signal.range.range_low;
            oss << " - " << signal.range.range_high;
            oss << " (" << std::setprecision(1) << signal.range.range_size_ticks << " ticks)\n";
            oss << "Composition: 🟢" << signal.range.green_count << " 🔴" << signal.range.red_count;
            oss << " (ratio 🟢 = " << std::setprecision(0) << (signal.range.green_ratio * 100) << "%)\n";
            oss << "Volume: AbsorbBID=" << std::setprecision(0) << signal.range.absorb_bid_total;
            oss << " AbsorbASK=" << signal.range.absorb_ask_total;
            oss << " (biais=" << std::setprecision(2) << signal.range.volume_bias << ")\n";
            oss << "Rectangles: 🟩" << signal.range.rectangles_green << " 🟥" << signal.range.rectangles_red << "\n";
            
            if (signal.range.breakout_up_likely && !signal.range.breakout_down_likely) {
                oss << "📈 BREAKOUT UP PROBABLE (volume acheteur dominant)\n";
            } else if (signal.range.breakout_down_likely && !signal.range.breakout_up_likely) {
                oss << "📉 BREAKOUT DOWN PROBABLE (volume vendeur dominant)\n";
            } else {
                oss << "⏳ Direction incertaine - Attendre breakout clair\n";
            }
            
            if (signal.range.should_block_trades) {
                oss << "⛔ TRADES BLOQUÉS - Attendre le BREAKOUT!\n";
            }
        } else {
            oss << "✅ Pas de range détecté - Tendance claire\n";
            oss << signal.range.description << "\n";
        }
        oss << "\n";
        
        // Signal
        oss << "🎯 SIGNAL\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        
        if (signal.is_valid) {
            oss << "✅ SIGNAL VALIDE: " << (signal.direction == 1 ? "LONG" : "SHORT") << "\n";
            oss << "Scores: DOW=" << signal.dow_score;
            oss << " | VISUEL=" << signal.visual_score;
            oss << " | RÈGLES=" << signal.rules_score;
            oss << " | MQ=" << signal.mq_bonus;
            oss << " | TOTAL=" << signal.total_score << "\n";
            oss << "Confiance: " << std::fixed << std::setprecision(0) << (signal.confidence * 100) << "%\n";
            oss << "Entry: " << std::fixed << std::setprecision(2) << signal.entry_price << "\n";
            oss << "SL: " << signal.sl_price << " | TP: " << signal.tp_price << "\n";
            oss << "Trailing: activer à +" << std::setprecision(0) << signal.trailing_activation;
            oss << "t, distance " << signal.trailing_distance << " ticks\n";
        } else {
            oss << "❌ PAS DE SIGNAL\n";
        }
        oss << "Raison: " << signal.reason << "\n\n";
        
        // Stats
        oss << "📈 STATISTIQUES\n";
        oss << "───────────────────────────────────────────────────────────────\n";
        oss << "Signaux générés: " << history.signals_generated << "\n";
        oss << "Signaux valides: " << history.signals_valid << "\n";
        oss << "Signaux bloqués: " << history.signals_blocked << "\n";
        
        sc.AddMessageToLog(oss.str().c_str(), 0);
    }
    
    // === TICK SIZE ===
    float tick_size = 0.25f;
    
    // === AFFICHER SIGNAUX SUR LE CHART ===
    if (Input_Enable_Signals.GetYesNo()) {
        // ES Signal
        if (es_enabled && signal_es.is_valid) {
            if (signal_es.direction == 1) {
                Subgraph_BuySignal[sc.ArraySize - 1] = sc.Low[sc.ArraySize - 1] - (10 * tick_size);
            } else {
                Subgraph_SellSignal[sc.ArraySize - 1] = sc.High[sc.ArraySize - 1] + (10 * tick_size);
            }
        }
        // NQ Signal
        if (nq_enabled && signal_nq.is_valid) {
            if (signal_nq.direction == 1) {
                Subgraph_BuySignal[sc.ArraySize - 1] = sc.Low[sc.ArraySize - 1] - (15 * tick_size);
            } else {
                Subgraph_SellSignal[sc.ArraySize - 1] = sc.High[sc.ArraySize - 1] + (15 * tick_size);
            }
        }
    }
    
    // === AFFICHER SCORES ===
    Subgraph_DowScore[sc.ArraySize - 1] = (float)signal.dow_score;
    Subgraph_TotalScore[sc.ArraySize - 1] = (float)signal.total_score;
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 26/01/2026: DASHBOARD GRAPHIQUE (comme MIA_AutoTrader_BN)
    // ═══════════════════════════════════════════════════════════════════════════════
    if (Input_Show_Dashboard.GetYesNo()) {
        s_UseTool tool;
        
        // Couleurs
        COLORREF color_ok = RGB(0, 255, 0);      // Vert
        COLORREF color_warn = RGB(255, 255, 0);  // Jaune
        COLORREF color_bad = RGB(255, 0, 0);     // Rouge
        COLORREF color_text = RGB(255, 255, 255); // Blanc
        COLORREF color_disabled = RGB(128, 128, 128); // Gris
        
        // Position en haut à droite
        float x_pos = 70.0f;
        float y_start = 95.0f;
        float line_height = 2.5f;
        int line = 0;
        int base_line_num = 8000;
        
        // === LIGNE 1: TITRE ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        tool.Text.Format("[MIA DOW HYBRID] ES:%s NQ:%s", 
            es_enabled ? "ON" : "OFF", nq_enabled ? "ON" : "OFF");
        tool.Color = color_ok;
        tool.FontSize = 12;
        tool.FontBold = 1;
        sc.UseTool(tool);
        line++;
        
        // ═══════════════════════════════════════════════════════════════════
        // ES STATUS
        // ═══════════════════════════════════════════════════════════════════
        DowAnalysis& dow_es = g_es_history.last_analysis;
        
        // === LIGNE 2: ES STATUS ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        if (es_enabled) {
            COLORREF es_state_color = color_warn;
            if (dow_es.state == DOW_CONFIRMED_UP || dow_es.state == DOW_STRONG_UP) es_state_color = color_ok;
            else if (dow_es.state == DOW_CONFIRMED_DOWN || dow_es.state == DOW_STRONG_DOWN) es_state_color = color_bad;
            tool.Text.Format("ES: %s | 🟢%d 🔴%d", 
                GetDowStateString(dow_es.state).c_str(), dow_es.ascending_greens, dow_es.descending_reds);
            tool.Color = es_state_color;
        } else {
            tool.Text.Format("ES: DISABLED");
            tool.Color = color_disabled;
        }
        tool.FontSize = 10;
        sc.UseTool(tool);
        line++;
        
        // === LIGNE 3: ES SIGNAL ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        if (es_enabled) {
            if (signal_es.is_valid) {
                tool.Text.Format("   -> %s Score=%d | SL=%.2f TP=%.2f",
                    signal_es.direction == 1 ? "LONG" : "SHORT",
                    signal_es.total_score, signal_es.sl_price, signal_es.tp_price);
                tool.Color = (signal_es.direction == 1) ? color_ok : color_bad;
            } else {
                char es_reason[60];
                strncpy(es_reason, signal_es.reason, 59);
                es_reason[59] = '\0';
                tool.Text.Format("   -> %s", es_reason);
                tool.Color = RGB(200, 200, 200);
            }
        } else {
            tool.Text.Format("   -> ES desactive dans les inputs");
            tool.Color = color_disabled;
        }
        tool.FontSize = 9;
        sc.UseTool(tool);
        line++;
        
        // ═══════════════════════════════════════════════════════════════════
        // NQ STATUS
        // ═══════════════════════════════════════════════════════════════════
        DowAnalysis& dow_nq = g_nq_history.last_analysis;
        
        // === LIGNE 4: NQ STATUS ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        if (nq_enabled) {
            COLORREF nq_state_color = color_warn;
            if (dow_nq.state == DOW_CONFIRMED_UP || dow_nq.state == DOW_STRONG_UP) nq_state_color = color_ok;
            else if (dow_nq.state == DOW_CONFIRMED_DOWN || dow_nq.state == DOW_STRONG_DOWN) nq_state_color = color_bad;
            tool.Text.Format("NQ: %s | 🟢%d 🔴%d", 
                GetDowStateString(dow_nq.state).c_str(), dow_nq.ascending_greens, dow_nq.descending_reds);
            tool.Color = nq_state_color;
        } else {
            tool.Text.Format("NQ: DISABLED");
            tool.Color = color_disabled;
        }
        tool.FontSize = 10;
        sc.UseTool(tool);
        line++;
        
        // === LIGNE 5: NQ SIGNAL ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        if (nq_enabled) {
            if (signal_nq.is_valid) {
                tool.Text.Format("   -> %s Score=%d | SL=%.2f TP=%.2f",
                    signal_nq.direction == 1 ? "LONG" : "SHORT",
                    signal_nq.total_score, signal_nq.sl_price, signal_nq.tp_price);
                tool.Color = (signal_nq.direction == 1) ? color_ok : color_bad;
            } else {
                char nq_reason[60];
                strncpy(nq_reason, signal_nq.reason, 59);
                nq_reason[59] = '\0';
                tool.Text.Format("   -> %s", nq_reason);
                tool.Color = RGB(200, 200, 200);
            }
        } else {
            tool.Text.Format("   -> NQ desactive dans les inputs");
            tool.Color = color_disabled;
        }
        tool.FontSize = 9;
        sc.UseTool(tool);
        line++;
        
        // === LIGNE 6: SESSION ===
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = base_line_num + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        SessionFilter session = es_enabled ? signal_es.session : signal_nq.session;
        tool.Text.Format("Session: %s", session.session_name);
        tool.Color = session.is_high_quality ? color_ok : color_warn;
        tool.FontSize = 9;
        sc.UseTool(tool);
    }
}
