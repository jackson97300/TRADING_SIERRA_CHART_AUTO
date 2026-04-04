#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Indicators.h - SECTION 6.5: VIX, ATR, VWAP, GOLDEN RULES, CONFLUENCE
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 2607-3207)
// Refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_DataReader.h"
#include "MIA_Globals.h"  // 🔧 28/02/2026: Pour g_market_live (struct déclarée dans Globals depuis ce refactor)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6.5: VIX LIVE, ATR DAILY, VWAP SLOPE, GOLDEN RULES, CONFLUENCE
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION: INDICATEURS LIVE (VIX, ATR, VWAP SLOPE)
// ═══════════════════════════════════════════════════════════════════════════════
// Note: struct MarketLiveData et g_market_live sont déclarés dans MIA_Globals.h
//       (déplacés le 28/02/2026 pour centraliser tous les globals en un point)

// --- Lecture VIX LIVE ---
inline float GetVIX_Live(SCStudyInterfaceRef sc, int vix_chart) {
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
inline float GetATR_Daily(SCStudyInterfaceRef sc, int daily_chart, int study_id) {
    if (daily_chart <= 0) return 0;

    // Utiliser la fonction helper
    return ReadStudyValue(sc, daily_chart, study_id, 0);
}

// --- Déterminer régime VIX ---
inline int GetVIXRegime(float vix) {
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

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: TREND BIAS depuis Swing Structure
// Utilise swing_high et swing_low pour déterminer la tendance:
//   +1 = UPTREND (prix au-dessus des swings, HH/HL pattern)
//   -1 = DOWNTREND (prix en-dessous des swings, LH/LL pattern)
//    0 = RANGE/NEUTRAL (entre les swings ou pas assez de data)
// ═══════════════════════════════════════════════════════════════════════════════
inline int GetTrendBias(float swing_high, float swing_low, float current_price) {
    // Pas assez de données
    if (swing_high <= 0 || swing_low <= 0) return 0;
    
    // Swing High doit être au-dessus de Swing Low (logique)
    if (swing_high <= swing_low) return 0;
    
    // Calcul de la position relative dans la structure
    float range = swing_high - swing_low;
    float position_pct = (current_price - swing_low) / range;
    
    // UPTREND: Prix au-dessus de 70% du range ou au-dessus du swing high
    if (current_price > swing_high || position_pct > 0.70f) {
        return 1;  // BULLISH bias
    }
    // DOWNTREND: Prix en-dessous de 30% du range ou en-dessous du swing low
    else if (current_price < swing_low || position_pct < 0.30f) {
        return -1;  // BEARISH bias
    }
    // RANGE: Prix entre 30% et 70% = zone neutre
    else {
        return 0;  // NEUTRAL
    }
}

inline const char* GetTrendBiasName(int bias) {
    switch (bias) {
        case 1: return "UPTREND";
        case -1: return "DOWNTREND";
        default: return "RANGE";
    }
}

// 🔍 DIAGNOSTIC: Écrire les infos de debug VWAP
inline void WriteDiagnosticVWAP(SCStudyInterfaceRef sc, int chart, int study_id, 
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
inline float CalculateVWAPSlope(SCStudyInterfaceRef sc, int chart, int study_id, int lookback_bars, const char* symbol = "UNKNOWN") {
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
inline bool CheckGoldenRule1_Veto(const BN_Data& bn, int direction) {
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
inline float CheckGoldenRule2_Bonus(const BN_Data& bn, int direction) {
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
inline bool IsPriceInConfluenceZone(
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
inline float GetConfluenceBonus(const ConfluenceResult& conf, float current_price, float tick_size) {
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

inline float GetBNExtensionBonus(
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

inline void CollectMarketLiveData(
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