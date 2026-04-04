#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_ExtensionTracker.h - SECTION 3.6: EXTENSION LINES TRACKER
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 702-976)
// Refactoring: 31/01/2026
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

#include "MIA_Config.h"
#include "MIA_Globals.h"

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
inline const int EXT_TRACKER_MAX_LINES = 30;          // Max lignes par type
inline const float EXT_TRACKER_TOUCH_TOLERANCE = 2.0f; // Ticks pour considérer touchée
inline const int EXT_TRACKER_MAX_AGE_MINUTES = 120;    // Durée max de vie (2h)

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
inline ExtensionLinesTracker g_ext_tracker_es;
inline ExtensionLinesTracker g_ext_tracker_nq;

// Met à jour le tracker avec les Extension Lines du snapshot BN
inline void UpdateExtensionLinesTracker(
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