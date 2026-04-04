#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_SLTP.h - SECTION 3.7: SL/TP DYNAMIQUE BASÉ SUR EXTENSION LINES TRACKÉES
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 977-1110)
// Refactoring: 31/01/2026
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

#include "MIA_ExtensionTracker.h"

inline const int EXT_SL_BUFFER_TICKS = 2;      // Buffer sous/au-dessus du niveau pour SL
inline const int EXT_TP_BUFFER_TICKS = 2;      // Buffer avant l'obstacle pour TP
inline const int EXT_MAX_DIST_FOR_SL = 50;     // Distance max pour chercher un niveau pour SL

// Calcule SL basé sur les Extension Lines trackées
inline float CalculateSLFromTrackedExtLines(
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
inline float CalculateTPWithTrackedObstacles(
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