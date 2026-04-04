#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_SLTP_Calc.h - SECTION 11: CalculateProtectedSLTP()
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 4979-5470)
// Refactoring: 31/01/2026
// 🆕 31/01/2026: VIX Adaptive SL/TP - Ajuste les distances selon volatilité
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Layers.h"
#include "MIA_Globals.h"  // 🆕 Pour g_market_live.vix_regime

// Note: SLTPResult défini dans MIA_Config.h

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: VIX ADAPTIVE MULTIPLIERS
// Ajuste les SL/TP selon la volatilité du marché
// ═══════════════════════════════════════════════════════════════════════════════
inline float GetVIXMultiplier(int vix_regime) {
    switch (vix_regime) {
        case 0:  // CALM (VIX < 15)
            return 0.85f;  // SL/TP plus serrés
        case 2:  // VOLATILE (VIX > 25)
            return 1.25f;  // SL/TP plus larges
        default: // NORMAL (VIX 15-25)
            return 1.0f;   // Standard
    }
}

inline SLTPResult CalculateProtectedSLTP(
    int direction,
    float entry_price,
    const MenthorQ_Data& mq,
    const BN_Data& bn,  // AJOUT: Extension Lines BN
    const SymbolConfig& config,
    const ExtensionLinesTracker* ext_tracker = nullptr,  // 🆕 25/01/2026: Tracker persistant
    const CompositeProfile_Data* cp = nullptr  // 🆕 01/02/2026: COMPOSITE PROFILES multi-périodes
) {
    SLTPResult result = {0, 0, 0, 0, 0, "", "", true};
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 31/01/2026: VIX ADAPTIVE - Ajuster SL/TP selon volatilité
    // CALM (VIX<15): x0.85 = plus serré, VOLATILE (VIX>25): x1.25 = plus large
    // ═══════════════════════════════════════════════════════════════════════════
    float vix_mult = GetVIXMultiplier(g_market_live.vix_regime);
    
    // Valeurs ajustées selon VIX
    float adjusted_sl_default = config.sl_default_ticks * vix_mult;
    float adjusted_sl_min = config.sl_min_ticks * vix_mult;
    float adjusted_sl_max = config.sl_max_ticks * vix_mult;
    float adjusted_tp_default = config.tp_default_ticks * vix_mult;
    float adjusted_tp_max = config.tp_max_ticks * vix_mult;
    
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
    float min_sl = adjusted_sl_min * tick_size;  // 🆕 VIX Adaptive
    float max_sl = adjusted_sl_max * tick_size;  // 🆕 VIX Adaptive

    // === Chercher niveau pour SL ===
    float best_sl = 0;
    float best_distance = 999999.0f;
    const char* best_level = "FIXED";

    // 🆕 14/03/2026: Tier classification (prouvé par Wall Tracker bench Test 11)
    //   Tier 1: GEX, SESSION HVN/LVN, EDGE_RECT, SESS_HIGH → SL PROTÉGÉ
    //   Tier 2: VAH/VAL, VWAP±SD, PREV_VAL, SWING, 1D → OK si confluence
    //   Tier 3: VWAP_D, BLIND, POC, BN_SUPPORT → DANGER seul
    struct SLLevel {
        float price;
        const char* name;
        int tier;  // 1=FORT, 2=SOLIDE, 3=FAIBLE
    };
    std::vector<SLLevel> levels;

    // ── TIER 1: VRAIS MURS (67-86% rebond prouvé) ──
    for (int i = 0; i < 10; i++) {
        if (mq.gex[i] > 0) levels.push_back({mq.gex[i], "GEX", 1});
    }
    if (mq.hvl > 0) levels.push_back({mq.hvl, "HVL", 1});
    if (mq.hvl_0dte > 0) levels.push_back({mq.hvl_0dte, "HVL_0DTE", 1});
    if (mq.gamma_wall > 0) levels.push_back({mq.gamma_wall, "GAMMA_WALL", 1});
    if (mq.gamma_wall_0dte > 0) levels.push_back({mq.gamma_wall_0dte, "GAMMA_0DTE", 1});
    if (bn.session_high > 0) levels.push_back({bn.session_high, "SESSION_HIGH", 1});
    if (bn.session_low > 0) levels.push_back({bn.session_low, "SESSION_LOW", 1});

    // Session HVN/LVN (Tier 1 — 67% rebond)
    if (bn.session_hvn > 0) levels.push_back({bn.session_hvn, "SESSION_HVN", 1});

    // Edge Rectangles (Tier 1 — zones institutionnelles)
    for (int i = 0; i < bn.num_edge_rect_buy; i++) {
        if (bn.edge_rect_buy_top[i] > 0) levels.push_back({bn.edge_rect_buy_top[i], "EDGE_RECT_BUY", 1});
    }
    for (int i = 0; i < bn.num_edge_rect_sell; i++) {
        if (bn.edge_rect_sell_bottom[i] > 0) levels.push_back({bn.edge_rect_sell_bottom[i], "EDGE_RECT_SELL", 1});
    }

    // ── TIER 2: MURS SOLIDES (50-65% rebond) ──
    if (mq.vah > 0) levels.push_back({mq.vah, "VAH", 2});
    if (mq.val > 0) levels.push_back({mq.val, "VAL", 2});
    if (mq.put_support > 0) levels.push_back({mq.put_support, "PUT_SUP", 2});
    if (mq.put_support_0dte > 0) levels.push_back({mq.put_support_0dte, "PUT_0DTE", 2});
    if (mq.call_resistance > 0) levels.push_back({mq.call_resistance, "CALL_RES", 2});
    if (mq.call_resistance_0dte > 0) levels.push_back({mq.call_resistance_0dte, "CALL_0DTE", 2});
    if (mq.day_min > 0) levels.push_back({mq.day_min, "1D_MIN", 2});
    if (mq.day_max > 0) levels.push_back({mq.day_max, "1D_MAX", 2});
    if (mq.vwap_up1 > 0) levels.push_back({mq.vwap_up1, "VWAP_UP1", 2});
    if (mq.vwap_dn1 > 0) levels.push_back({mq.vwap_dn1, "VWAP_DN1", 2});
    if (mq.vwap_up2 > 0) levels.push_back({mq.vwap_up2, "VWAP_UP2", 2});
    if (mq.vwap_dn2 > 0) levels.push_back({mq.vwap_dn2, "VWAP_DN2", 2});
    if (mq.prev_vpoc > 0) levels.push_back({mq.prev_vpoc, "PREV_VPOC", 2});
    if (mq.prev_vah > 0) levels.push_back({mq.prev_vah, "PREV_VAH", 2});
    if (mq.prev_val > 0) levels.push_back({mq.prev_val, "PREV_VAL", 2});
    if (bn.swing_high > 0) levels.push_back({bn.swing_high, "SWING_HIGH", 2});
    if (bn.swing_low > 0) levels.push_back({bn.swing_low, "SWING_LOW", 2});
    if (bn.session_poc > 0) levels.push_back({bn.session_poc, "SESSION_POC", 2});
    if (bn.session_vah > 0) levels.push_back({bn.session_vah, "SESSION_VAH", 2});
    if (bn.session_val > 0) levels.push_back({bn.session_val, "SESSION_VAL", 2});

    // Rectangles tradables (Tier 2)
    for (int i = 0; i < bn.num_long_up_bar; i++) {
        if (bn.long_up_bar_ext[i] > 0) levels.push_back({bn.long_up_bar_ext[i], "RECT_TRADABLE", 2});
    }
    for (int i = 0; i < bn.num_long_down_bar; i++) {
        if (bn.long_down_bar_ext[i] > 0) levels.push_back({bn.long_down_bar_ext[i], "RECT_TRADABLE", 2});
    }

    // ── TIER 3: MURS PAPIER (30-45% rebond — piège) ──
    if (mq.vwap > 0) levels.push_back({mq.vwap, "VWAP", 3});
    for (int i = 0; i < 9; i++) {
        if (mq.blind_spots[i] > 0) levels.push_back({mq.blind_spots[i], "BLIND", 3});
    }
    if (bn.fpbs_poc > 0) levels.push_back({bn.fpbs_poc, "POC", 3});
    for (int i = 0; i < bn.num_ext_support; i++) {
        if (bn.ext_lines_support[i] > 0) levels.push_back({bn.ext_lines_support[i], "BN_SUPPORT", 3});
    }
    for (int i = 0; i < bn.num_ext_resist; i++) {
        if (bn.ext_lines_resist[i] > 0) levels.push_back({bn.ext_lines_resist[i], "BN_RESIST", 3});
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // NOUVELLE LOGIQUE: Tier validation + Confluence + Plus loin
    // 🆕 14/03/2026: Tier 3 seul = REJETÉ (piège), Tier 2 seul = OK si confluence
    // ═══════════════════════════════════════════════════════════════════════════
    const float CONFLUENCE_THRESHOLD = 5.0f * tick_size;  // 5 ticks

    // Collecter les niveaux valides pour SL
    std::vector<SLLevel> valid_sl_levels;

    for (const auto& lvl : levels) {
        float level_price = lvl.price;

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

    // Trouver le niveau le plus proche ET vérifier confluence + tier
    float closest_level = 0;
    float farthest_in_confluence = 0;
    const char* farthest_name = "FIXED";
    int best_tier = 99;  // 🆕 Track le meilleur tier trouvé
    int n_levels_in_confluence = 0;  // 🆕 Compteur confluence

    if (!valid_sl_levels.empty()) {
        // Trier par distance au prix
        if (direction == 1) {  // LONG - trier par prix décroissant
            std::sort(valid_sl_levels.begin(), valid_sl_levels.end(),
                [](const SLLevel& a, const SLLevel& b) { return a.price > b.price; });
        } else {  // SHORT - trier par prix croissant
            std::sort(valid_sl_levels.begin(), valid_sl_levels.end(),
                [](const SLLevel& a, const SLLevel& b) { return a.price < b.price; });
        }

        closest_level = valid_sl_levels[0].price;
        farthest_in_confluence = closest_level;
        farthest_name = valid_sl_levels[0].name;
        best_tier = valid_sl_levels[0].tier;

        // Chercher tous les niveaux dans la zone de confluence
        for (const auto& lvl : valid_sl_levels) {
            float dist_from_closest = std::abs(lvl.price - closest_level);
            if (dist_from_closest <= CONFLUENCE_THRESHOLD) {
                n_levels_in_confluence++;
                if (lvl.tier < best_tier) best_tier = lvl.tier;  // Garder le meilleur tier
                if (direction == 1 && lvl.price < farthest_in_confluence) {
                    farthest_in_confluence = lvl.price;
                    farthest_name = lvl.name;
                } else if (direction == -1 && lvl.price > farthest_in_confluence) {
                    farthest_in_confluence = lvl.price;
                    farthest_name = lvl.name;
                }
            }
        }

        // 🆕 14/03/2026: VALIDATION TIER
        // Tier 1 seul = OK
        // Tier 2 seul = OK (mais on préfère confluence)
        // Tier 3 seul = REJETÉ (piège — 30-45% rebond seulement)
        // Tier 2 ou 3 en confluence (2+ niveaux) = OK
        bool tier_valid = false;
        if (best_tier == 1) {
            tier_valid = true;  // Tier 1 = toujours OK
        } else if (best_tier == 2) {
            tier_valid = true;  // Tier 2 seul = OK
        } else if (best_tier == 3 && n_levels_in_confluence >= 2) {
            tier_valid = true;  // Tier 3 en confluence = OK
        }
        // Tier 3 seul → tier_valid reste false → fallback SL fixe

        if (tier_valid) {
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

    // Fallback SL fixe (🆕 VIX Adaptive)
    if (best_sl == 0) {
        if (direction == 1) {
            best_sl = entry_price - (adjusted_sl_default * tick_size);
        } else {
            best_sl = entry_price + (adjusted_sl_default * tick_size);
        }
        best_level = "FIXED_VIX";
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
        float level_price = lvl.price;
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
            obstacle_name = lvl.name;
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
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 31/01/2026: SINGLE PRINTS = Zones de faiblesse → TP RAPIDE!
    // Les Single Prints sont des Low Volume Nodes où le prix traverse VITE.
    // IDÉAL pour TP car le prix va probablement atteindre cette zone.
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == 1 && bn.single_print_high > 0) {  // LONG - Single Print HIGH = TP rapide
        float sp_price = bn.single_print_high;
        if (sp_price > entry_price) {
            float distance = sp_price - entry_price;
            // Single Print = zone de faiblesse, prix traverse vite = TP optimal!
            if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                first_obstacle_dist = distance;
                first_obstacle = sp_price;
                obstacle_name = "SINGLE_PRINT_HIGH";
            }
        }
    }
    else if (direction == -1 && bn.single_print_low > 0) {  // SHORT - Single Print LOW = TP rapide
        float sp_price = bn.single_print_low;
        if (sp_price < entry_price) {
            float distance = entry_price - sp_price;
            // Single Print = zone de faiblesse, prix traverse vite = TP optimal!
            if (distance < first_obstacle_dist && distance >= MIN_OBSTACLE_DIST) {
                first_obstacle_dist = distance;
                first_obstacle = sp_price;
                obstacle_name = "SINGLE_PRINT_LOW";
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 02/02/2026: SESSION LVN = Zone de faiblesse INTRADAY (PRIORITÉ HAUTE)
    // Le LVN de session est plus FRAIS que les LVN composites (1j-200j)
    // Le prix traverse les LVN rapidement → excellent pour TP
    // ═══════════════════════════════════════════════════════════════════════════════
    if (direction == 1 && bn.session_lvn > 0 && bn.session_lvn > entry_price) {
        float distance = bn.session_lvn - entry_price;
        
        // Session LVN entre 10 et 50 ticks = cible optimale intraday
        if (distance >= MIN_OBSTACLE_DIST && distance < 50.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.session_lvn;
                obstacle_name = "LVN_SESSION";
            }
        }
    }
    else if (direction == -1 && bn.session_lvn > 0 && bn.session_lvn < entry_price) {
        float distance = entry_price - bn.session_lvn;
        
        if (distance >= MIN_OBSTACLE_DIST && distance < 50.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.session_lvn;
                obstacle_name = "LVN_SESSION";
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 02/02/2026: SESSION HIGH/LOW COMME TP TARGETS
    // Niveaux psychologiques que TOUS les traders surveillent = haute probabilité
    // ═══════════════════════════════════════════════════════════════════════════════
    if (direction == 1 && bn.session_high > entry_price && bn.session_high > 0) {
        float distance = bn.session_high - entry_price;
        
        // Session High entre 15 et 60 ticks = TP raisonnable
        if (distance >= 15.0f * tick_size && distance < 60.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.session_high - (2 * tick_size);  // Buffer avant le niveau
                obstacle_name = "SESSION_HIGH";
            }
        }
    }
    else if (direction == -1 && bn.session_low < entry_price && bn.session_low > 0) {
        float distance = entry_price - bn.session_low;
        
        if (distance >= 15.0f * tick_size && distance < 60.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.session_low + (2 * tick_size);  // Buffer avant le niveau
                obstacle_name = "SESSION_LOW";
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 02/02/2026: SWING HIGH/LOW COMME TP TARGETS (si proche)
    // Niveaux de structure Dow Theory = le prix teste souvent ces niveaux
    // ═══════════════════════════════════════════════════════════════════════════════
    if (direction == 1 && bn.swing_high > entry_price && bn.swing_high > 0) {
        float distance = bn.swing_high - entry_price;
        
        // Swing High entre 15 et 50 ticks = TP structurel
        if (distance >= 15.0f * tick_size && distance < 50.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.swing_high - (2 * tick_size);
                obstacle_name = "SWING_HIGH";
            }
        }
    }
    else if (direction == -1 && bn.swing_low < entry_price && bn.swing_low > 0) {
        float distance = entry_price - bn.swing_low;
        
        if (distance >= 15.0f * tick_size && distance < 50.0f * tick_size) {
            if (distance < first_obstacle_dist) {
                first_obstacle_dist = distance;
                first_obstacle = bn.swing_low + (2 * tick_size);
                obstacle_name = "SWING_LOW";
            }
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 01/02/2026: LVN DES COMPOSITE PROFILES = Zones de faiblesse multi-périodes
    // Les LVN (Low Volume Nodes) sont des zones où le prix traverse VITE.
    // On utilise le LVN le plus proche (toutes périodes confondues) comme cible TP.
    // Priorité: LVN < 50 ticks = excellent TP (zone de faiblesse = prix traverse vite)
    // ═══════════════════════════════════════════════════════════════════════════════
    if (cp != nullptr) {
        if (direction == 1 && cp->nearest_lvn_above > 0) {  // LONG - LVN au-dessus = TP rapide
            float lvn_price = cp->nearest_lvn_above;
            float distance = lvn_price - entry_price;
            
            // LVN entre 5 et 60 ticks = zone de faiblesse optimale pour TP
            if (distance >= MIN_OBSTACLE_DIST && distance < 60.0f * tick_size) {
                // Si LVN plus proche que l'obstacle actuel → utiliser LVN comme TP
                if (distance < first_obstacle_dist) {
                    first_obstacle_dist = distance;
                    first_obstacle = lvn_price;
                    // Indiquer la période du LVN (1j, 20j, 50j, etc.)
                    if (cp->nearest_lvn_above_period == 1) obstacle_name = "LVN_1D";
                    else if (cp->nearest_lvn_above_period == 20) obstacle_name = "LVN_20D";
                    else if (cp->nearest_lvn_above_period == 50) obstacle_name = "LVN_50D";
                    else if (cp->nearest_lvn_above_period == 100) obstacle_name = "LVN_100D";
                    else obstacle_name = "LVN_200D";
                }
            }
        }
        else if (direction == -1 && cp->nearest_lvn_below > 0) {  // SHORT - LVN en-dessous = TP rapide
            float lvn_price = cp->nearest_lvn_below;
            float distance = entry_price - lvn_price;
            
            // LVN entre 5 et 60 ticks = zone de faiblesse optimale pour TP
            if (distance >= MIN_OBSTACLE_DIST && distance < 60.0f * tick_size) {
                // Si LVN plus proche que l'obstacle actuel → utiliser LVN comme TP
                if (distance < first_obstacle_dist) {
                    first_obstacle_dist = distance;
                    first_obstacle = lvn_price;
                    // Indiquer la période du LVN
                    if (cp->nearest_lvn_below_period == 1) obstacle_name = "LVN_1D";
                    else if (cp->nearest_lvn_below_period == 20) obstacle_name = "LVN_20D";
                    else if (cp->nearest_lvn_below_period == 50) obstacle_name = "LVN_50D";
                    else if (cp->nearest_lvn_below_period == 100) obstacle_name = "LVN_100D";
                    else obstacle_name = "LVN_200D";
                }
            }
        }
        
        // 🆕 01/02/2026: HVN DES COMPOSITE PROFILES = Zones de HAUTE STABILITÉ
        // Les HVN (High Volume Nodes) sont des zones où le prix reste STABLE (absorption).
        // On utilise le HVN pour AMÉLIORER le placement SL (zone de protection).
        // Si un HVN est proche du SL actuel mais plus serré → utiliser HVN comme SL
        if (direction == 1 && cp->nearest_hvn_below > 0) {  // LONG - HVN en-dessous = protection SL
            float hvn_price = cp->nearest_hvn_below;
            float hvn_sl = hvn_price - (2.0f * tick_size);  // SL sous le HVN avec buffer
            float hvn_distance = entry_price - hvn_sl;
            
            // HVN valide si entre min_sl et SL actuel (amélioration)
            if (hvn_distance >= min_sl && hvn_distance <= max_sl) {
                // Si HVN permet un SL plus serré que l'actuel → utiliser HVN
                float current_sl_distance = entry_price - best_sl;
                if (hvn_sl > best_sl && hvn_distance < current_sl_distance) {
                    best_sl = hvn_sl;
                    best_level = "HVN_PROTECTED";
                }
            }
        }
        else if (direction == -1 && cp->nearest_hvn_above > 0) {  // SHORT - HVN au-dessus = protection SL
            float hvn_price = cp->nearest_hvn_above;
            float hvn_sl = hvn_price + (2.0f * tick_size);  // SL au-dessus du HVN avec buffer
            float hvn_distance = hvn_sl - entry_price;
            
            // HVN valide si entre min_sl et SL actuel (amélioration)
            if (hvn_distance >= min_sl && hvn_distance <= max_sl) {
                // Si HVN permet un SL plus serré que l'actuel → utiliser HVN
                float current_sl_distance = best_sl - entry_price;
                if (hvn_sl < best_sl && hvn_distance < current_sl_distance) {
                    best_sl = hvn_sl;
                    best_level = "HVN_PROTECTED";
                }
            }
        }
        
        // Mettre à jour result.sl si HVN a amélioré le SL
        if (strcmp(best_level, "HVN_PROTECTED") == 0) {
            result.sl_price = best_sl;
            strncpy(result.sl_based_on, best_level, sizeof(result.sl_based_on) - 1);
            result.sl_ticks = (int)(fabs(entry_price - best_sl) / tick_size);
        }
    }
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 02/02/2026: SESSION HVN = Zone de HAUTE STABILITÉ INTRADAY
    // Le HVN de session est une zone où le volume s'est accumulé AUJOURD'HUI
    // Le prix a tendance à rebondir sur ces zones → excellent pour protection SL
    // ═══════════════════════════════════════════════════════════════════════════════
    if (bn.session_hvn > 0) {
        if (direction == 1 && bn.session_hvn < entry_price) {  // LONG - HVN en-dessous
            float hvn_sl = bn.session_hvn - (2.0f * tick_size);
            float hvn_distance = entry_price - hvn_sl;
            
            // Session HVN valide si dans range SL et améliore l'actuel
            if (hvn_distance >= min_sl && hvn_distance <= max_sl) {
                float current_sl_distance = entry_price - best_sl;
                // Si HVN permet un SL plus serré → utiliser
                if (best_sl == 0 || (hvn_sl > best_sl && hvn_distance < current_sl_distance)) {
                    best_sl = hvn_sl;
                    best_level = "HVN_SESSION";
                    result.sl_price = best_sl;
                    strncpy(result.sl_based_on, best_level, sizeof(result.sl_based_on) - 1);
                    result.sl_ticks = (int)(hvn_distance / tick_size);
                }
            }
        }
        else if (direction == -1 && bn.session_hvn > entry_price) {  // SHORT - HVN au-dessus
            float hvn_sl = bn.session_hvn + (2.0f * tick_size);
            float hvn_distance = hvn_sl - entry_price;
            
            if (hvn_distance >= min_sl && hvn_distance <= max_sl) {
                float current_sl_distance = best_sl - entry_price;
                if (best_sl == 0 || (hvn_sl < best_sl && hvn_distance < current_sl_distance)) {
                    best_sl = hvn_sl;
                    best_level = "HVN_SESSION";
                    result.sl_price = best_sl;
                    strncpy(result.sl_based_on, best_level, sizeof(result.sl_based_on) - 1);
                    result.sl_ticks = (int)(hvn_distance / tick_size);
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
        // 🆕 VIX Adaptive TP default
        if (direction == 1) {
            result.tp_price = entry_price + (adjusted_tp_default * tick_size);
        } else {
            result.tp_price = entry_price - (adjusted_tp_default * tick_size);
        }
        strcpy(result.tp_based_on, "FIXED_VIX");
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // 🔧 27/01/2026: SÉCURITÉ FINALE - FORCER LES LIMITES MIN/MAX TP!
    // Bug découvert: TP de 70 ticks sur NQ au lieu de max 50!
    // 🆕 31/01/2026: Limites ajustées selon VIX
    // ═══════════════════════════════════════════════════════════════════════════
    float max_tp_distance = adjusted_tp_max * tick_size;  // 🆕 VIX Adaptive
    float min_tp_distance = adjusted_sl_default * tick_size;  // 🆕 VIX Adaptive - TP minimum = SL default (R:R ~1)
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


