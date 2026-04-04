#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Layers.h - SECTIONS 7-10: LAYERS 1-4 VALIDATION
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 3208-4978)
// Refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Indicators.h"

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7: LAYER 1 - MENTHORQ LEVELS
// ═══════════════════════════════════════════════════════════════════════════════
// Note: Layer1Result défini dans MIA_Config.h

inline Layer1Result ValidateLayer1(
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
    // 🆕 31/01/2026: PREVIOUS DAY LEVELS - Niveaux J-1 très importants!
    // Le VPOC et VAH/VAL du jour précédent sont des niveaux magnétiques.
    // ═══════════════════════════════════════════════════════════════════════════
    // Previous VPOC - MAJEUR (Score 3) - Niveau magnet très fort
    if (mq.prev_vpoc > 0) {
        int dir = (current_price > mq.prev_vpoc) ? 1 : -1;
        candidates.push_back({"PREV_VPOC", mq.prev_vpoc, dir, 3});  // Score 3 = MAJEUR!
    }
    // Previous VAH - IMPORTANT (Score 2)
    if (mq.prev_vah > 0) {
        int dir = (current_price > mq.prev_vah) ? 1 : -1;
        candidates.push_back({"PREV_VAH", mq.prev_vah, dir, 2});
    }
    // Previous VAL - IMPORTANT (Score 2)
    if (mq.prev_val > 0) {
        int dir = (current_price > mq.prev_val) ? 1 : -1;
        candidates.push_back({"PREV_VAL", mq.prev_val, dir, 2});
    }
    // Previous VWAP - MINEUR (Score 1)
    if (mq.prev_vwap > 0) {
        int dir = (current_price > mq.prev_vwap) ? 1 : -1;
        candidates.push_back({"PREV_VWAP", mq.prev_vwap, dir, 1});
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // 🆕 31/01/2026: SESSION POC/VAH/VAL - Niveaux intraday de la session actuelle
    // Ces niveaux évoluent en temps réel et sont très pertinents pour l'intraday.
    // ═══════════════════════════════════════════════════════════════════════════
    // Session POC - IMPORTANT (Score 2) - Point de control de la session
    if (bn != nullptr && bn->session_poc > 0) {
        int dir = (current_price > bn->session_poc) ? 1 : -1;
        candidates.push_back({"SESSION_POC", bn->session_poc, dir, 2});
    }
    // Session VAH - IMPORTANT (Score 2) - Résistance intraday
    if (bn != nullptr && bn->session_vah > 0) {
        int dir = (current_price > bn->session_vah) ? 1 : -1;
        candidates.push_back({"SESSION_VAH", bn->session_vah, dir, 2});
    }
    // Session VAL - IMPORTANT (Score 2) - Support intraday
    if (bn != nullptr && bn->session_val > 0) {
        int dir = (current_price > bn->session_val) ? 1 : -1;
        candidates.push_back({"SESSION_VAL", bn->session_val, dir, 2});
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
        
        // 🆕 30/01/2026: BONUS BLIND SPOT PROCHE (zone aveugle = niveau explosif!)
        // Les Blind Spots sont des zones de faible liquidité d'options
        // → Prix traverse rapidement OU rebondit fort
        // → Setup + Blind Spot = CONFLUENCE EXCEPTIONNELLE
        char blind_info[32] = "";
        if (mq.dist_blind_ticks > 0 && mq.dist_blind_ticks <= 30.0f) {
            confluence += 0.12f;  // BONUS MAJEUR: Blind Spot proche!
            snprintf(blind_info, sizeof(blind_info), "+BLIND@%.0ft", mq.dist_blind_ticks);
        } else if (mq.dist_blind_ticks > 0 && mq.dist_blind_ticks <= 50.0f) {
            confluence += 0.08f;  // Bonus Blind Spot moyennement proche
            snprintf(blind_info, sizeof(blind_info), "+BL@%.0ft", mq.dist_blind_ticks);
        }

        // Valider si confluence >= 0.60 (qualité!)
        if (confluence >= 0.60f) {
            result.has_signal = true;
            result.direction = 1;  // LONG
            result.confidence = confluence;
            result.rectangle_price = near_support_ext ? nearest_support : (has_green_rect ? bn.long_down_up : current_price);
            result.confluence_score = confluence;
            snprintf(result.reason, sizeof(result.reason),
                "RECT_LONG: %s@%.0ft Boules+%d%% Rect=%d%s Conf=%.0f%%",
                nearest_option_name, nearest_option_dist,
                green_bonus_pct, has_green_rect?1:0, blind_info, confluence * 100);
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
        
        // 🆕 30/01/2026: BONUS BLIND SPOT PROCHE (zone aveugle = niveau explosif!)
        char blind_info[32] = "";
        if (mq.dist_blind_ticks > 0 && mq.dist_blind_ticks <= 30.0f) {
            confluence += 0.12f;  // BONUS MAJEUR: Blind Spot proche!
            snprintf(blind_info, sizeof(blind_info), "+BLIND@%.0ft", mq.dist_blind_ticks);
        } else if (mq.dist_blind_ticks > 0 && mq.dist_blind_ticks <= 50.0f) {
            confluence += 0.08f;  // Bonus Blind Spot moyennement proche
            snprintf(blind_info, sizeof(blind_info), "+BL@%.0ft", mq.dist_blind_ticks);
        }

        // Valider si confluence >= 0.60 (qualité!)
        if (confluence >= 0.60f) {
            result.has_signal = true;
            result.direction = -1;  // SHORT
            result.confidence = confluence;
            result.rectangle_price = near_resist_ext ? nearest_resist : (has_red_rect ? bn.long_up_down : current_price);
            result.confluence_score = confluence;
            snprintf(result.reason, sizeof(result.reason),
                "RECT_SHORT: %s@%.0ft Boules+%d%% Rect=%d%s Conf=%.0f%%",
                nearest_option_name, nearest_option_dist,
                red_bonus_pct, has_red_rect?1:0, blind_info, confluence * 100);
        }
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8: LAYER 2 - ORDERFLOW + BATAILLE NAVALE
// ═══════════════════════════════════════════════════════════════════════════════
// Note: Layer2Result défini dans MIA_Config.h

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

// ═══════════════════════════════════════════════════════════════════════════════
// 🔧 01/02/2026: Renommé pour clarifier - Cette fonction fait L2 + partie de L3
// Contient: Depth Check + VWAP Threshold + L3 Simplifié + Signaux Visuels + VETOs
// ═══════════════════════════════════════════════════════════════════════════════
inline Layer2Result ValidateLayer2_OrderFlowTrend(
    int direction,
    const BN_Data& bn_primary,
    const BN_Data& bn_secondary,
    float vix,
    float delta,
    float buy_pct,
    const SymbolConfig& config,
    bool is_nq,
    float depth_imbalance = 0.0f,
    float sell_pct = 0.5f,
    float vwap_slope = 0.0f
) {
    // 🔧 01/02/2026: Ajout 0 pour visual_count (évite valeur indéterminée si retour précoce)
    Layer2Result result = {false, 0, 0, "", "", 0};

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
    
    // 🗑️ 01/02/2026: Code EDGE DOMINANT supprimé (données incorrectes)
    // Edge Dominant maintenant géré dans Layer 4 Score Qualité
    
    // 1. DEPTH IMBALANCE (ASSOUPLI - 28/01/2026)
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
    // ES (is_nq=false): ±0.05 (standard)
    // NQ/RTY (is_nq=true): ±0.07 (🔧 01/02/2026: NQ plus volatile = seuil PLUS permissif!)
    // Avant: NQ 0.03 était trop strict pour sa volatilité
    float vwap_threshold = is_nq ? 0.07f : 0.05f;
    
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
        // 🆕 31/01/2026: DELTA DIVERGENCE BULLISH - Signal fort de retournement!
        if (bn_primary.delta_div_buy && bn_primary.delta_div_strength > 0.5f) { 
            has_visual_signal = true; 
            visual_count += 2;  // Divergence = signal FORT, compte double!
        }
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
        // 🆕 31/01/2026: DELTA DIVERGENCE BEARISH - Signal fort de retournement!
        if (bn_primary.delta_div_sell && bn_primary.delta_div_strength > 0.5f) { 
            has_visual_signal = true; 
            visual_count += 2;  // Divergence = signal FORT, compte double!
        }
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
    // 🆕 31/01/2026: VETO DELTA DIVERGENCE CONTRAIRE
    // Si on veut SHORT mais qu'il y a une forte divergence BULLISH → VETO!
    // Si on veut LONG mais qu'il y a une forte divergence BEARISH → VETO!
    // ═══════════════════════════════════════════════════════════════════════
    if (direction == -1 && bn_primary.delta_div_buy && bn_primary.delta_div_strength > 0.7f) {
        snprintf(result.reason, sizeof(result.reason),
                 "VETO DELTA DIV: Divergence BULLISH forte (%.0f%%) contre SHORT!",
                 bn_primary.delta_div_strength * 100);
        return result;
    }
    if (direction == 1 && bn_primary.delta_div_sell && bn_primary.delta_div_strength > 0.7f) {
        snprintf(result.reason, sizeof(result.reason),
                 "VETO DELTA DIV: Divergence BEARISH forte (%.0f%%) contre LONG!",
                 bn_primary.delta_div_strength * 100);
        return result;
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

    // 🆕 01/02/2026: Stocker visual_count pour Layer 4 Score Qualité
    result.visual_count = visual_count;

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
// Note: Layer3Result défini dans MIA_Config.h

inline Layer3Result ValidateLayer3(
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

    // === BLOC A2: VWAP VETO ANTI-TENDANCE ===
    // 🔧 01/02/2026: Bonus/Malus supprimés (déjà dans L2), VETO GARDÉ (seuil différent!)
    // L2 utilise seuil 0.05/0.07, L3 utilise seuil STRICT 0.012
    float vwap_slope = is_nq ? g_market_live.vwap_slope_nq : g_market_live.vwap_slope_es;
    const float VWAP_SLOPE_VETO_THRESHOLD = 0.012f;

    if (direction == 1 && vwap_slope < -VWAP_SLOPE_VETO_THRESHOLD) {
        result.veto = true;
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "VETO Anti-Trend: LONG interdit - VWAP descend (%.4f < -%.3f)",
                 vwap_slope, VWAP_SLOPE_VETO_THRESHOLD);
        return result;
    }
    if (direction == -1 && vwap_slope > VWAP_SLOPE_VETO_THRESHOLD) {
        result.veto = true;
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "VETO Anti-Trend: SHORT interdit - VWAP monte (%.4f > +%.3f)",
                 vwap_slope, VWAP_SLOPE_VETO_THRESHOLD);
        return result;
    }
    // Note: Bonus/malus VWAP slope supprimés - déjà gérés dans L2

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

    // 🔧 01/02/2026: BLOC A5 Institutional supprimé (déjà dans L2 "L3 simplifié" pour NQ)
    
    // ═══════════════════════════════════════════════════════════════════════
    // 🆕 31/01/2026: BLOC A5: SWING TREND BIAS (renuméroté de A5.5)
    // Trade avec la tendance = bonus, contre la tendance = malus
    // Utilise swing_high/low pour déterminer si UPTREND/DOWNTREND/RANGE
    // ═══════════════════════════════════════════════════════════════════════
    int trend_bias = GetTrendBias(bn.swing_high, bn.swing_low, current_price);
    if (trend_bias != 0) {
        if (direction == trend_bias) {
            // Trade AVEC la tendance = BONUS
            score += 0.04f;
            snprintf(result.context, sizeof(result.context),
                     "TREND_ALIGNED: %s avec %s",
                     direction == 1 ? "LONG" : "SHORT",
                     GetTrendBiasName(trend_bias));
        } else {
            // Trade CONTRE la tendance = MALUS (mais pas VETO)
            score -= 0.03f;
            snprintf(result.context, sizeof(result.context),
                     "COUNTER_TREND: %s contre %s",
                     direction == 1 ? "LONG" : "SHORT",
                     GetTrendBiasName(trend_bias));
        }
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
    // 🔧 01/02/2026: Seuil augmenté 0.10 → 0.15 (plus sélectif après suppression bonus)
    result.confidence = score;
    result.passed = score >= 0.15f;  // Seuil AJUSTÉ

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
// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 01/02/2026: LAYER 4 REFONDÉ - SCORE QUALITÉ GLOBALE (0-100)
// ═══════════════════════════════════════════════════════════════════════════════
// Le Layer 4 calcule un score de qualité globale du setup:
//   - Grade A (80+): Premium setup → TP x1.30
//   - Grade B (70-79): Bon setup → TP x1.15
//   - Grade C (55-69): Acceptable → TP x1.00
//   - Grade D (<55): Rejeté
// ═══════════════════════════════════════════════════════════════════════════════
// Note: Layer4Result défini dans MIA_Config.h

inline Layer4Result ValidateLayer4(
    int direction,
    float buy_pct,
    float sell_pct,
    float edge_buy,
    float edge_sell,
    float cum_delta,
    float bn_score,
    float vwap_slope,
    const SymbolConfig& config,
    // 🆕 Nouveaux paramètres pour Score Qualité
    float l1_importance = 2.0f,     // Score importance L1 (1-3)
    float l1_confidence = 0.5f,     // Confiance L1 (0-1)
    float l2_confidence = 0.5f,     // Confiance L2 (0-1)
    float l3_confidence = 0.5f,     // Confiance L3 (0-1)
    int visual_signals = 1,         // Nombre signaux visuels BN
    float vix = 20.0f,              // VIX actuel
    int trend_bias = 0              // -1=DOWN, 0=RANGE, +1=UP
) {
    Layer4Result result = {false, 0, false, false, false, false, false, 0.0f, 'D', 1.0f};
    float score = 0.0f;
    int combo_count = 0;

    // ═══════════════════════════════════════════════════════════════════════════
    // COMPOSANT 1: IMPORTANCE NIVEAU L1 (0-25 pts)
    // Score 3 (MAJEUR) = 25 pts, Score 2 = 16 pts, Score 1 = 8 pts
    // ═══════════════════════════════════════════════════════════════════════════
    score += l1_importance * 8.33f;
    if (score > 25.0f) score = 25.0f;

    // ═══════════════════════════════════════════════════════════════════════════
    // COMPOSANT 2: CONFLUENCE SIGNAUX BN (0-25 pts)
    // Chaque signal visuel = 5 pts, max 25 pts (5 signaux)
    // ═══════════════════════════════════════════════════════════════════════════
    float signal_pts = visual_signals * 5.0f;
    if (signal_pts > 25.0f) signal_pts = 25.0f;
    score += signal_pts;

    // ═══════════════════════════════════════════════════════════════════════════
    // COMPOSANT 3: TENDANCE ALIGNÉE (0-20 pts)
    // Direction alignée avec trend = 20 pts, Range = 10 pts, Contre = 0 pts
    // ═══════════════════════════════════════════════════════════════════════════
    if (direction == trend_bias) {
        score += 20.0f;  // Aligné avec la tendance
    } else if (trend_bias == 0) {
        score += 10.0f;  // Range = neutre
    }
    // Contre-tendance = 0 pts (pas de malus, juste pas de bonus)

    // ═══════════════════════════════════════════════════════════════════════════
    // COMPOSANT 4: CONFIANCE MOYENNE L1/L2/L3 (0-20 pts)
    // Moyenne des 3 confidences * 40 (car confiance 0-0.5 typique)
    // ═══════════════════════════════════════════════════════════════════════════
    float avg_confidence = (l1_confidence + l2_confidence + l3_confidence) / 3.0f;
    float conf_pts = avg_confidence * 40.0f;
    if (conf_pts > 20.0f) conf_pts = 20.0f;
    score += conf_pts;

    // ═══════════════════════════════════════════════════════════════════════════
    // COMPOSANT 5: VIX OPTIMAL (0-10 pts)
    // VIX 15-25 = optimal (10 pts), VIX 12-30 = acceptable (5 pts)
    // ═══════════════════════════════════════════════════════════════════════════
    if (vix >= 15.0f && vix <= 25.0f) {
        score += 10.0f;  // Zone optimale
    } else if (vix >= 12.0f && vix <= 30.0f) {
        score += 5.0f;   // Zone acceptable
    }
    // VIX extrême (<12 ou >30) = 0 pts

    // ═══════════════════════════════════════════════════════════════════════════
    // INDICATEURS INDIVIDUELS (pour info et combo count)
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Buy/Sell % (seuil 52% du backtest +863%)
    const float PCT_THRESHOLD = 0.52f;
    if (direction == 1) {
        result.pct_ok = (buy_pct > PCT_THRESHOLD);
    } else {
        result.pct_ok = (sell_pct > PCT_THRESHOLD);
    }
    if (result.pct_ok) combo_count++;

    // Delta aligné
    if (direction == 1) {
        result.delta_ok = (cum_delta > 0);
    } else {
        result.delta_ok = (cum_delta < 0);
    }
    if (result.delta_ok) combo_count++;

    // BN Score aligné
    if (direction == 1) {
        result.bn_ok = (bn_score > 0);
    } else {
        result.bn_ok = (bn_score < 0);
    }
    if (result.bn_ok) combo_count++;

    // VWAP aligné
    if (direction == 1) {
        result.vwap_ok = (vwap_slope > 0);
    } else {
        result.vwap_ok = (vwap_slope < 0);
    }
    if (result.vwap_ok) combo_count++;

    // Edge/Rectangle (utiliser les données disponibles)
    // Note: edge_buy/sell sont parfois des PRIX, donc on utilise la comparaison relative
    if (edge_buy > 0 || edge_sell > 0) {
        if (direction == 1) {
            result.edge_ok = (edge_buy >= edge_sell);
        } else {
            result.edge_ok = (edge_sell >= edge_buy);
        }
    } else {
        result.edge_ok = true;  // Pas de data = neutre
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // VALIDATION: GRADES ET MULTIPLICATEURS
    // ═══════════════════════════════════════════════════════════════════════════
    result.quality_score = score;
    result.combo_aligned = combo_count;

    if (score >= 80.0f) {
        result.grade = 'A';
        result.tp_multiplier = 1.30f;  // TP +30% pour setup premium
        result.passed = true;
    } else if (score >= 70.0f) {
        result.grade = 'B';
        result.tp_multiplier = 1.15f;  // TP +15% pour bon setup
        result.passed = true;
    } else if (score >= 62.0f) {
        result.grade = 'C';
        result.tp_multiplier = 1.00f;  // TP standard
        result.passed = true;
        // 🔧 01/03/2026: Relevé de 55 → 62 (55 trop permissif, trades médiocres passaient)
    } else {
        result.grade = 'D';
        result.tp_multiplier = 1.00f;
        result.passed = false;  // REJETÉ!
    }

    // Override: Si l4_combo_required = 0, toujours passer (backward compatible)
    if (config.l4_combo_required == 0) {
        result.passed = true;
        result.grade = 'C';  // Grade par défaut si désactivé
    }

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11: CALCUL SL/TP PROTÉGÉ
// ═══════════════════════════════════════════════════════════════════════════════


