#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Execution.h - SECTION 12: SendBracketOrder, Trailing, Break-Even
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 5471-6367)
// Refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_SLTP_Calc.h"

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
inline float CalculateBNAnchor(
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

inline bool SendBracketOrder(
    SCStudyInterfaceRef sc,
    int direction,
    float entry_price,
    float sl_price,
    float tp_price,
    BotState& state,
    float bn_anchor = 0,  // 🆕 Ancre BN (0 = utiliser entry_price)
    int qty = 1           // 🆕 01/02/2026: Quantité dynamique (MICRO)
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
    order.OrderQuantity = qty;  // 🆕 01/02/2026: Quantité dynamique
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
    // 🔧 01/03/2026: FIX CRITIQUE — strcmp("ESH26-CME","ES")!=0 était TOUJOURS true
    //   → chargeait CONFIG_ES même pour NQ. Utiliser strstr (sous-chaîne) comme MIA_Main.cpp:570
    const SymbolConfig& cfg = (strstr(sc.GetChartSymbol(sc.ChartNumber), "ES") != NULL) ? CONFIG_ES : CONFIG_NQ;
    
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
// 🆕 01/02/2026: WRAPPERS THREAD-SAFE AVEC STATEMANAGER
// ═══════════════════════════════════════════════════════════════════════════════
// Ces wrappers permettent d'appeler SendBracketOrder de manière thread-safe
// en utilisant le StateManager au lieu d'accéder directement aux globales
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_StateManager.h"

// Wrapper thread-safe pour ES
inline bool SendBracketOrder_ES(
    SCStudyInterfaceRef sc,
    int direction,
    float entry_price,
    float sl_price,
    float tp_price,
    float bn_anchor = 0
) {
    bool result = false;
    UPDATE_ES_STATE([&](BotState& state) {
        result = SendBracketOrder(sc, direction, entry_price, sl_price, tp_price, state, bn_anchor);
    });
    return result;
}

// Wrapper thread-safe pour NQ
inline bool SendBracketOrder_NQ(
    SCStudyInterfaceRef sc,
    int direction,
    float entry_price,
    float sl_price,
    float tp_price,
    float bn_anchor = 0
) {
    bool result = false;
    UPDATE_NQ_STATE([&](BotState& state) {
        result = SendBracketOrder(sc, direction, entry_price, sl_price, tp_price, state, bn_anchor);
    });
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// GESTION FERMETURE DE POSITION - VERSION CORRIGÉE ET ROBUSTE
// ═══════════════════════════════════════════════════════════════════════════════
// Cette fonction vérifie si une position a été fermée et met à jour les stats
// IMPORTANT: GetTradePosition() retourne SEULEMENT la position du chart actuel
// Donc on ne peut vérifier la fermeture que si le bot est sur le bon chart
// ═══════════════════════════════════════════════════════════════════════════════
inline void ProcessPositionClosed(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config) {
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

inline void CheckOrderTimeout(SCStudyInterfaceRef sc, BotState& state) {
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
inline void CheckOrderFilled(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config) {
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
inline void LogTrailingClose(SCStudyInterfaceRef sc, const SymbolConfig& config, 
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
inline void UpdateTrailingStop(SCStudyInterfaceRef sc, BotState& state, const SymbolConfig& config, float current_price) {
    if (!state.in_position) return;
    if (current_price <= 0) return;  // Protection contre prix invalide
    float tick_size = config.tick_size;
    float activation_dist = config.trailing_activation_ticks * tick_size;
    float trailing_dist = config.trailing_distance_ticks * tick_size;
    float be_activation_dist = config.break_even_activation_ticks * tick_size;
    float be_buffer = config.break_even_buffer_ticks * tick_size;

    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 01/02/2026: SOFTWARE STOP LOSS DE SÉCURITÉ
    // Vérifie si le prix a atteint le SL initial (au cas où attached order échoue)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Si sl_price = 0 (position synchronisée sans SL), calculer un SL par défaut
    if (state.sl_price <= 0 && state.entry_price > 0) {
        float default_sl_dist = config.sl_default_ticks * tick_size;
        if (state.position_direction == 1) {  // LONG
            state.sl_price = state.entry_price - default_sl_dist;
        } else {  // SHORT
            state.sl_price = state.entry_price + default_sl_dist;
        }
        char sl_msg[128];
        snprintf(sl_msg, sizeof(sl_msg), "⚠️ %s: SL AUTO-CALCULÉ @ %.2f (position sync)", 
                 config.name, state.sl_price);
        sc.AddMessageToLog(sl_msg, 0);
    }
    
    // Vérifier si le prix a touché le SL initial (SÉCURITÉ CRITIQUE!)
    if (state.sl_price > 0 && !state.trailing_activated && !state.break_even_activated) {
        bool sl_hit = false;
        
        if (state.position_direction == 1) {  // LONG - SL en-dessous
            if (current_price <= state.sl_price) {
                sl_hit = true;
            }
        } else {  // SHORT - SL au-dessus
            if (current_price >= state.sl_price) {
                sl_hit = true;
            }
        }
        
        if (sl_hit) {
            // 🔴 SL TOUCHÉ! FERMER LA POSITION IMMÉDIATEMENT
            float exit_price = state.sl_price;
            float pnl_ticks = (state.position_direction == 1) ? 
                              (exit_price - state.entry_price) / tick_size :
                              (state.entry_price - exit_price) / tick_size;
            float pnl_dollars = pnl_ticks * config.tick_value;
            
            // Fermer via Flatten
            sc.FlattenPosition();
            
            // MISE À JOUR STATS
            state.trades_today++;
            state.losses_today++;
            state.consecutive_losses++;
            state.pnl_today += pnl_dollars;
            if (pnl_dollars < state.worst_trade) state.worst_trade = pnl_dollars;
            
            // COOLDOWN
            state.cooldown_until = sc.CurrentSystemDateTime + SCDateTime::MINUTES(config.cooldown_loss_min);
            
            // LOG
            char sl_close_msg[256];
            snprintf(sl_close_msg, sizeof(sl_close_msg),
                     "🛑 %s SL SOFTWARE HIT! Entry=%.2f Exit=%.2f PnL=$%.2f (%.0ft)",
                     config.name, state.entry_price, exit_price, pnl_dollars, pnl_ticks);
            sc.AddMessageToLog(sl_close_msg, 0);
            LogTrailingClose(sc, config, state.position_direction, state.entry_price, exit_price, pnl_dollars, "SL_SOFTWARE");
            
            // RESET STATE
            state.in_position = false;
            state.position_direction = 0;
            state.trailing_activated = false;
            state.break_even_activated = false;
            state.parent_order_id = 0;
            state.sl_price = 0;
            state.tp_price = 0;
            strcpy(state.waiting_for, "Signal");
            
            return;  // Sortir de la fonction
        }
    }

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
    // 🆕 01/02/2026: Vérifier trailing_allowed (désactivé en REGIME_RANGE!)
    // ═══════════════════════════════════════════════════════════════════════════
    if (profit >= activation_dist && !state.trailing_activated && state.trailing_allowed) {
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
// 🆕 01/02/2026: WRAPPERS THREAD-SAFE POUR TRAILING/TIMEOUT/POSITION
// ═══════════════════════════════════════════════════════════════════════════════

// Wrapper thread-safe UpdateTrailingStop pour ES
inline void UpdateTrailingStop_ES(SCStudyInterfaceRef sc, const SymbolConfig& config, float current_price) {
    UPDATE_ES_STATE([&](BotState& state) {
        UpdateTrailingStop(sc, state, config, current_price);
    });
}

// Wrapper thread-safe UpdateTrailingStop pour NQ
inline void UpdateTrailingStop_NQ(SCStudyInterfaceRef sc, const SymbolConfig& config, float current_price) {
    UPDATE_NQ_STATE([&](BotState& state) {
        UpdateTrailingStop(sc, state, config, current_price);
    });
}

// Wrapper thread-safe CheckOrderTimeout pour ES
inline void CheckOrderTimeout_ES(SCStudyInterfaceRef sc) {
    UPDATE_ES_STATE([&](BotState& state) {
        CheckOrderTimeout(sc, state);
    });
}

// Wrapper thread-safe CheckOrderTimeout pour NQ
inline void CheckOrderTimeout_NQ(SCStudyInterfaceRef sc) {
    UPDATE_NQ_STATE([&](BotState& state) {
        CheckOrderTimeout(sc, state);
    });
}

// Wrapper thread-safe ProcessPositionClosed pour ES
inline void ProcessPositionClosed_ES(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    UPDATE_ES_STATE([&](BotState& state) {
        ProcessPositionClosed(sc, state, config);
    });
}

// Wrapper thread-safe ProcessPositionClosed pour NQ
inline void ProcessPositionClosed_NQ(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    UPDATE_NQ_STATE([&](BotState& state) {
        ProcessPositionClosed(sc, state, config);
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 13: SNAPSHOT ET LOGGING
// ═══════════════════════════════════════════════════════════════════════════════