// ═══════════════════════════════════════════════════════════════════════════════
// MIA_CVD_Divergence.h - Module Avancé de Détection CVD Divergence
// ═══════════════════════════════════════════════════════════════════════════════
// Date: 11/02/2026
// Version: 1.0
// Auteur: MIA Trading System
//
// MODULE ADDITIONNEL - Ne modifie PAS le code existant!
// S'intègre APRÈS CollectBN_Data() et AVANT les Layers.
//
// FONCTIONNALITÉS:
//   1. Divergence Classique (Higher High prix + Lower High CVD, et inverse)
//   2. Divergence Cachée (Higher Low prix + Lower Low CVD → continuation)
//   3. Absorption Detection (prix flat + CVD en forte pente)
//   4. CVD Flip (changement de signe cumulatif)
//   5. Multi-bar analysis (rolling buffer 8 barres)
//
// PERSISTENT VARS UTILISÉES:
//   Float 200-239: ES rolling buffer (8 bars × 5 values)
//   Float 240-279: NQ rolling buffer (8 bars × 5 values)
//   Int 10: ES buffer write index
//   Int 11: NQ buffer write index
//   Int 12: ES bars accumulated count
//   Int 13: NQ bars accumulated count
//   Float 280: ES previous bar timestamp (pour éviter doublons)
//   Float 281: NQ previous bar timestamp
// ═══════════════════════════════════════════════════════════════════════════════

#pragma once

#include "MIA_Config.h"

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════════

inline const int CVD_LOOKBACK = 8;             // Nombre de barres dans le rolling buffer
inline const int CVD_MIN_BARS = 4;             // Minimum de barres pour détecter une divergence
inline const int CVD_VALUES_PER_BAR = 5;       // price_high, price_low, price_close, cvd, delta

// Persistent variable base indices (NE PAS CHANGER sans vérifier les conflits!)
// Existants: Float 100/101 = prev_cvd ES/NQ, Int 1/2 = g_last_day/pnl_baseline
inline const int CVD_PERSIST_BASE_ES = 200;    // Float 200-239
inline const int CVD_PERSIST_BASE_NQ = 240;    // Float 240-279
inline const int CVD_PERSIST_IDX_ES = 10;      // Int 10 = buffer write index ES
inline const int CVD_PERSIST_IDX_NQ = 11;      // Int 11 = buffer write index NQ
inline const int CVD_PERSIST_CNT_ES = 12;      // Int 12 = bars accumulated ES
inline const int CVD_PERSIST_CNT_NQ = 13;      // Int 13 = bars accumulated NQ
inline const int CVD_PERSIST_TS_ES = 280;      // Float 280 = last bar timestamp ES
inline const int CVD_PERSIST_TS_NQ = 281;      // Float 281 = last bar timestamp NQ

// ═══════════════════════════════════════════════════════════════════════════════
// SEUILS (ajustables)
// ═══════════════════════════════════════════════════════════════════════════════

// Divergence classique: le CVD doit diverger d'au moins X% de son range
inline const float CVD_DIV_MIN_RATIO = 0.15f;  // 15% du range CVD minimum

// Absorption: prix range < X ticks mais CVD bouge > Y
inline const float CVD_ABSORB_PRICE_MAX_TICKS_ES = 4.0f;   // ES: range < 4 ticks = flat
inline const float CVD_ABSORB_PRICE_MAX_TICKS_NQ = 6.0f;   // NQ: range < 6 ticks = flat
inline const float CVD_ABSORB_CVD_MIN_MOVE = 300.0f;        // CVD doit bouger > 300

// CVD Flip: seuil de significativité
inline const float CVD_FLIP_THRESHOLD = 50.0f;  // Ignorer les oscillations < 50

// Score weights
inline const float CVD_WEIGHT_CLASSIC = 0.40f;     // Divergence classique
inline const float CVD_WEIGHT_HIDDEN = 0.25f;       // Divergence cachée
inline const float CVD_WEIGHT_ABSORPTION = 0.20f;   // Absorption
inline const float CVD_WEIGHT_FLIP = 0.15f;          // CVD Flip

// ═══════════════════════════════════════════════════════════════════════════════
// STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

// Types de divergence détectés
enum CVD_DivType {
    CVD_DIV_NONE = 0,
    CVD_DIV_CLASSIC_BEARISH = 1,    // Higher High prix + Lower High CVD → essoufflement BUY
    CVD_DIV_CLASSIC_BULLISH = 2,    // Lower Low prix + Higher Low CVD → essoufflement SELL
    CVD_DIV_HIDDEN_BULLISH = 3,     // Higher Low prix + Lower Low CVD → continuation BUY
    CVD_DIV_HIDDEN_BEARISH = 4,     // Lower High prix + Higher High CVD → continuation SELL
    CVD_DIV_ABSORPTION_BUY = 5,     // Prix flat + CVD monte → accumulation
    CVD_DIV_ABSORPTION_SELL = 6,    // Prix flat + CVD baisse → distribution
    CVD_DIV_FLIP_BULLISH = 7,       // CVD passe de négatif à positif
    CVD_DIV_FLIP_BEARISH = 8        // CVD passe de positif à négatif
};

// Résultat complet de l'analyse CVD
struct CVD_AnalysisResult {
    // === DIVERGENCES DÉTECTÉES ===
    bool has_classic_divergence;     // Divergence classique trouvée
    bool has_hidden_divergence;      // Divergence cachée trouvée
    bool has_absorption;             // Absorption détectée
    bool has_cvd_flip;               // Changement de signe CVD
    
    CVD_DivType primary_signal;      // Signal principal (le plus fort)
    CVD_DivType secondary_signal;    // Signal secondaire (si présent)
    
    // === SCORES ===
    float score;                     // Score global [-1.0, +1.0]
                                     //   > 0 = signal BULLISH
                                     //   < 0 = signal BEARISH
    float confidence;                // Confiance [0.0, 1.0]
    
    // === VETO ===
    bool veto_long;                  // NE PAS acheter (divergence classique bearish forte)
    bool veto_short;                 // NE PAS vendre (divergence classique bullish forte)
    char veto_reason[128];           // Raison du VETO
    
    // === BOOST ===
    float boost_long;                // Bonus pour LONG [0.0, 0.10]
    float boost_short;               // Bonus pour SHORT [0.0, 0.10]
    
    // === DIAGNOSTICS ===
    int bars_in_buffer;              // Nombre de barres valides
    float cvd_range;                 // Range du CVD sur le lookback
    float price_range_ticks;         // Range du prix sur le lookback
    char signal_description[256];    // Description lisible du signal
};

// Données d'une barre dans le rolling buffer
struct CVD_BarData {
    float price_high;
    float price_low;
    float price_close;
    float cvd;          // Cumulative Delta Volume à la clôture de la barre
    float delta;        // Delta de cette barre uniquement
};

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTIONS UTILITAIRES INTERNES
// ═══════════════════════════════════════════════════════════════════════════════

// Lire une barre du rolling buffer persistent
inline CVD_BarData CVD_ReadBar(SCStudyInterfaceRef sc, int base_idx, int bar_offset) {
    CVD_BarData bar;
    int idx = base_idx + (bar_offset * CVD_VALUES_PER_BAR);
    bar.price_high  = sc.GetPersistentFloat(idx + 0);
    bar.price_low   = sc.GetPersistentFloat(idx + 1);
    bar.price_close = sc.GetPersistentFloat(idx + 2);
    bar.cvd         = sc.GetPersistentFloat(idx + 3);
    bar.delta       = sc.GetPersistentFloat(idx + 4);
    return bar;
}

// Écrire une barre dans le rolling buffer persistent
inline void CVD_WriteBar(SCStudyInterfaceRef sc, int base_idx, int bar_offset,
                         float price_high, float price_low, float price_close,
                         float cvd, float delta) {
    int idx = base_idx + (bar_offset * CVD_VALUES_PER_BAR);
    sc.SetPersistentFloat(idx + 0, price_high);
    sc.SetPersistentFloat(idx + 1, price_low);
    sc.SetPersistentFloat(idx + 2, price_close);
    sc.SetPersistentFloat(idx + 3, cvd);
    sc.SetPersistentFloat(idx + 4, delta);
}

// Trouver les swing points (highs/lows locaux) dans le buffer
// Retourne l'index de la barre qui forme le pivot, ou -1 si pas trouvé
inline int CVD_FindSwingHigh(const CVD_BarData bars[], int count, bool use_price) {
    // Cherche le plus haut high dans le buffer (pour les N dernières barres)
    if (count < 3) return -1;
    
    int best_idx = 0;
    float best_val = use_price ? bars[0].price_high : bars[0].cvd;
    
    for (int i = 1; i < count; i++) {
        float val = use_price ? bars[i].price_high : bars[i].cvd;
        if (val > best_val) {
            best_val = val;
            best_idx = i;
        }
    }
    return best_idx;
}

inline int CVD_FindSwingLow(const CVD_BarData bars[], int count, bool use_price) {
    if (count < 3) return -1;
    
    int best_idx = 0;
    float best_val = use_price ? bars[0].price_low : bars[0].cvd;
    
    for (int i = 1; i < count; i++) {
        float val = use_price ? bars[i].price_low : bars[i].cvd;
        if (val < best_val) {
            best_val = val;
            best_idx = i;
        }
    }
    return best_idx;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE: UpdateCVD_History()
// ═══════════════════════════════════════════════════════════════════════════════
// Appeler APRÈS CollectBN_Data() pour mettre à jour le rolling buffer
// Utilise le prix OHLC du chart et le CVD du footprint
//
// IMPORTANT: Cette fonction doit être appelée UNE SEULE FOIS par nouvelle barre!
// Elle utilise le timestamp pour éviter les mises à jour redondantes.
// ═══════════════════════════════════════════════════════════════════════════════

inline void UpdateCVD_History(SCStudyInterfaceRef sc, const BN_Data& bn,
                              float price_high, float price_low, float price_close,
                              bool is_nq) {
    // --- Indices persistent vars ---
    int base_idx = is_nq ? CVD_PERSIST_BASE_NQ : CVD_PERSIST_BASE_ES;
    int idx_key  = is_nq ? CVD_PERSIST_IDX_NQ : CVD_PERSIST_IDX_ES;
    int cnt_key  = is_nq ? CVD_PERSIST_CNT_NQ : CVD_PERSIST_CNT_ES;
    int ts_key   = is_nq ? CVD_PERSIST_TS_NQ : CVD_PERSIST_TS_ES;
    
    // --- Vérifier qu'on a des données CVD valides ---
    if (bn.fpbs_cvd == 0 && bn.fpbs_delta == 0) {
        return;  // Pas de données CVD, on skip
    }
    
    // --- Éviter les doublons (même barre) ---
    // FIX 11/02/2026: Utiliser un hash combiné (high+low+close+cvd) au lieu de close*1000+cvd
    // L'ancien fingerprint créait des collisions (ex: close=6000,cvd=500 vs close=6000.5,cvd=0)
    // Le nouveau hash combine 4 valeurs pour minimiser les collisions
    float current_fingerprint = price_high * 7.0f + price_low * 13.0f + price_close * 31.0f + bn.fpbs_cvd * 0.1f;
    float last_fingerprint = sc.GetPersistentFloat(ts_key);
    
    // Tolérance de comparaison float (éviter les faux positifs)
    if (fabs(current_fingerprint - last_fingerprint) < 0.001f && last_fingerprint != 0) {
        return;  // Même barre, pas de mise à jour
    }
    sc.SetPersistentFloat(ts_key, current_fingerprint);
    
    // --- Écrire dans le buffer circulaire ---
    int& write_idx = sc.GetPersistentInt(idx_key);
    int& bar_count = sc.GetPersistentInt(cnt_key);
    
    // Position d'écriture (modulo LOOKBACK)
    int pos = write_idx % CVD_LOOKBACK;
    
    CVD_WriteBar(sc, base_idx, pos,
                 price_high, price_low, price_close,
                 bn.fpbs_cvd, bn.fpbs_delta);
    
    write_idx = (write_idx + 1) % CVD_LOOKBACK;
    if (bar_count < CVD_LOOKBACK) {
        bar_count++;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE: AnalyzeCVD_Divergence()
// ═══════════════════════════════════════════════════════════════════════════════
// Analyse le rolling buffer pour détecter les divergences multi-barres.
// Appeler APRÈS UpdateCVD_History() et AVANT les Layers.
//
// Retourne un CVD_AnalysisResult avec tous les signaux détectés.
// ═══════════════════════════════════════════════════════════════════════════════

inline CVD_AnalysisResult AnalyzeCVD_Divergence(SCStudyInterfaceRef sc,
                                                  const BN_Data& bn,
                                                  float current_price,
                                                  bool is_nq) {
    CVD_AnalysisResult result;
    memset(&result, 0, sizeof(result));
    result.primary_signal = CVD_DIV_NONE;
    result.secondary_signal = CVD_DIV_NONE;
    
    // --- Indices persistent vars ---
    int base_idx = is_nq ? CVD_PERSIST_BASE_NQ : CVD_PERSIST_BASE_ES;
    int idx_key  = is_nq ? CVD_PERSIST_IDX_NQ : CVD_PERSIST_IDX_ES;
    int cnt_key  = is_nq ? CVD_PERSIST_CNT_NQ : CVD_PERSIST_CNT_ES;
    
    int write_idx = sc.GetPersistentInt(idx_key);
    int bar_count = sc.GetPersistentInt(cnt_key);
    result.bars_in_buffer = bar_count;
    
    // --- Pas assez de données ---
    if (bar_count < CVD_MIN_BARS) {
        snprintf(result.signal_description, sizeof(result.signal_description),
                 "CVD: Buffer en remplissage (%d/%d barres)", bar_count, CVD_MIN_BARS);
        return result;
    }
    
    // --- Reconstituer le buffer en ordre chronologique ---
    // bars[0] = la plus ancienne, bars[count-1] = la plus récente
    CVD_BarData bars[CVD_LOOKBACK];
    int actual_count = (bar_count < CVD_LOOKBACK) ? bar_count : CVD_LOOKBACK;
    
    for (int i = 0; i < actual_count; i++) {
        // Lire en ordre chronologique depuis le buffer circulaire
        int read_pos;
        if (bar_count < CVD_LOOKBACK) {
            read_pos = i;  // Buffer pas encore plein → lecture directe
        } else {
            read_pos = (write_idx + i) % CVD_LOOKBACK;  // Buffer plein → depuis le plus ancien
        }
        bars[i] = CVD_ReadBar(sc, base_idx, read_pos);
    }
    
    // --- Calculer les ranges ---
    float price_highest = bars[0].price_high;
    float price_lowest = bars[0].price_low;
    float cvd_highest = bars[0].cvd;
    float cvd_lowest = bars[0].cvd;
    
    for (int i = 1; i < actual_count; i++) {
        if (bars[i].price_high > price_highest) price_highest = bars[i].price_high;
        if (bars[i].price_low < price_lowest) price_lowest = bars[i].price_low;
        if (bars[i].cvd > cvd_highest) cvd_highest = bars[i].cvd;
        if (bars[i].cvd < cvd_lowest) cvd_lowest = bars[i].cvd;
    }
    
    float tick_size = is_nq ? 0.25f : 0.25f;  // Les deux sont 0.25 pour les micro
    result.cvd_range = cvd_highest - cvd_lowest;
    result.price_range_ticks = (price_highest - price_lowest) / tick_size;
    
    // =====================================================================
    // DÉTECTION 1: DIVERGENCES CLASSIQUES (multi-barres)
    // =====================================================================
    // Logique: Comparer la première moitié du buffer avec la seconde moitié
    // pour détecter des swing points divergents.
    //
    // On divise le buffer en 2 fenêtres:
    //   Fenêtre A = barres [0, mid)     → "avant"
    //   Fenêtre B = barres [mid, count) → "récent"
    //
    // Divergence Classique Bearish:
    //   Prix: High(B) > High(A) → Higher High
    //   CVD:  Max(B)  < Max(A)  → Lower High CVD
    //   = Essoufflement des acheteurs!
    //
    // Divergence Classique Bullish:
    //   Prix: Low(B)  < Low(A)  → Lower Low
    //   CVD:  Min(B)  > Min(A)  → Higher Low CVD
    //   = Essoufflement des vendeurs!
    // =====================================================================
    
    int mid = actual_count / 2;
    
    // Trouver les extremes de chaque fenêtre
    float priceHigh_A = bars[0].price_high, priceHigh_B = bars[mid].price_high;
    float priceLow_A = bars[0].price_low, priceLow_B = bars[mid].price_low;
    float cvdMax_A = bars[0].cvd, cvdMax_B = bars[mid].cvd;
    float cvdMin_A = bars[0].cvd, cvdMin_B = bars[mid].cvd;
    
    for (int i = 0; i < mid; i++) {
        if (bars[i].price_high > priceHigh_A) priceHigh_A = bars[i].price_high;
        if (bars[i].price_low < priceLow_A) priceLow_A = bars[i].price_low;
        if (bars[i].cvd > cvdMax_A) cvdMax_A = bars[i].cvd;
        if (bars[i].cvd < cvdMin_A) cvdMin_A = bars[i].cvd;
    }
    for (int i = mid; i < actual_count; i++) {
        if (bars[i].price_high > priceHigh_B) priceHigh_B = bars[i].price_high;
        if (bars[i].price_low < priceLow_B) priceLow_B = bars[i].price_low;
        if (bars[i].cvd > cvdMax_B) cvdMax_B = bars[i].cvd;
        if (bars[i].cvd < cvdMin_B) cvdMin_B = bars[i].cvd;
    }
    
    // Seuil minimum de divergence CVD (éviter le bruit)
    float cvd_div_threshold = result.cvd_range * CVD_DIV_MIN_RATIO;
    if (cvd_div_threshold < 20.0f) cvd_div_threshold = 20.0f;  // Plancher absolu
    
    // --- Divergence Classique Bearish ---
    // Prix fait Higher High MAIS CVD fait Lower High
    if (priceHigh_B > priceHigh_A && cvdMax_B < (cvdMax_A - cvd_div_threshold)) {
        result.has_classic_divergence = true;
        float div_strength = (cvdMax_A - cvdMax_B) / fmax(result.cvd_range, 1.0f);
        
        result.veto_long = true;
        result.score -= div_strength * CVD_WEIGHT_CLASSIC;
        result.primary_signal = CVD_DIV_CLASSIC_BEARISH;
        
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "DIV CLASSIQUE BEARISH: Prix HH (+%.1f pts) mais CVD LH (%.0f→%.0f) sur %d barres",
                 (priceHigh_B - priceHigh_A), cvdMax_A, cvdMax_B, actual_count);
    }
    
    // --- Divergence Classique Bullish ---
    // Prix fait Lower Low MAIS CVD fait Higher Low
    if (priceLow_B < priceLow_A && cvdMin_B > (cvdMin_A + cvd_div_threshold)) {
        result.has_classic_divergence = true;
        float div_strength = (cvdMin_B - cvdMin_A) / fmax(result.cvd_range, 1.0f);
        
        result.veto_short = true;
        result.score += div_strength * CVD_WEIGHT_CLASSIC;
        
        if (result.primary_signal == CVD_DIV_NONE) {
            result.primary_signal = CVD_DIV_CLASSIC_BULLISH;
        } else {
            result.secondary_signal = CVD_DIV_CLASSIC_BULLISH;
        }
        
        snprintf(result.veto_reason, sizeof(result.veto_reason),
                 "DIV CLASSIQUE BULLISH: Prix LL (-%.1f pts) mais CVD HL (%.0f→%.0f) sur %d barres",
                 (priceLow_A - priceLow_B), cvdMin_A, cvdMin_B, actual_count);
    }
    
    // =====================================================================
    // DÉTECTION 2: DIVERGENCES CACHÉES (Hidden Divergences)
    // =====================================================================
    // Plus subtiles mais souvent plus profitables car elles confirment la tendance.
    //
    // Hidden Bullish: Higher Low prix + Lower Low CVD
    //   → Le prix tient ses supports malgré la pression vendeuse = acheteurs forts
    //   → Signal de CONTINUATION haussière
    //
    // Hidden Bearish: Lower High prix + Higher High CVD
    //   → Le prix n'arrive pas à remonter malgré la pression acheteuse = vendeurs forts
    //   → Signal de CONTINUATION baissière
    //
    // FIX 11/02/2026: EXCLUSION MUTUELLE
    // Une divergence classique BEARISH et une cachée BULLISH ne peuvent pas coexister
    // logiquement. La classique (signal de retournement) a priorité sur la cachée
    // (signal de continuation) car elles sont contradictoires.
    // Règle: Si classique bearish → pas de hidden bullish (et inversement)
    // =====================================================================
    
    bool classic_bearish_active = (result.primary_signal == CVD_DIV_CLASSIC_BEARISH);
    bool classic_bullish_active = (result.primary_signal == CVD_DIV_CLASSIC_BULLISH)
                               || (result.secondary_signal == CVD_DIV_CLASSIC_BULLISH);
    
    // --- Hidden Bullish --- (SKIP si classique bearish actif → conflit)
    if (!classic_bearish_active &&
        priceLow_B > priceLow_A && cvdMin_B < (cvdMin_A - cvd_div_threshold)) {
        result.has_hidden_divergence = true;
        float strength = (cvdMin_A - cvdMin_B) / fmax(result.cvd_range, 1.0f);
        
        result.boost_long = fmin(strength * 0.08f, 0.10f);  // Max +10%
        result.score += strength * CVD_WEIGHT_HIDDEN;
        
        if (result.primary_signal == CVD_DIV_NONE) {
            result.primary_signal = CVD_DIV_HIDDEN_BULLISH;
        } else {
            result.secondary_signal = CVD_DIV_HIDDEN_BULLISH;
        }
    }
    
    // --- Hidden Bearish --- (SKIP si classique bullish actif → conflit)
    if (!classic_bullish_active &&
        priceHigh_B < priceHigh_A && cvdMax_B > (cvdMax_A + cvd_div_threshold)) {
        result.has_hidden_divergence = true;
        float strength = (cvdMax_B - cvdMax_A) / fmax(result.cvd_range, 1.0f);
        
        result.boost_short = fmin(strength * 0.08f, 0.10f);  // Max +10%
        result.score -= strength * CVD_WEIGHT_HIDDEN;
        
        if (result.primary_signal == CVD_DIV_NONE) {
            result.primary_signal = CVD_DIV_HIDDEN_BEARISH;
        } else {
            result.secondary_signal = CVD_DIV_HIDDEN_BEARISH;
        }
    }
    
    // =====================================================================
    // DÉTECTION 3: ABSORPTION
    // =====================================================================
    // Le prix reste dans un range serré (< N ticks) MAIS le CVD bouge
    // significativement → quelqu'un absorbe les ordres sans laisser le prix bouger.
    //
    // C'est un signal PRÉ-BREAKOUT très puissant, surtout quand détecté
    // à proximité d'un niveau clé (MenthorQ, VPOC, etc.)
    //
    // On regarde les 3 dernières barres uniquement (signal court terme).
    //
    // FIX 11/02/2026: RÉSOLUTION DE CONFLIT
    // Si absorption détectée dans une direction ET hidden divergence dans l'autre,
    // l'absorption prime (signal récent > signal structurel).
    // On neutralise la hidden divergence conflictuelle.
    // =====================================================================
    
    if (actual_count >= 3) {
        // Calculer le range prix et CVD sur les 3 dernières barres
        float recent_price_high = bars[actual_count - 1].price_high;
        float recent_price_low = bars[actual_count - 1].price_low;
        float recent_cvd_start = bars[actual_count - 3].cvd;
        float recent_cvd_end = bars[actual_count - 1].cvd;
        
        for (int i = actual_count - 3; i < actual_count; i++) {
            if (bars[i].price_high > recent_price_high) recent_price_high = bars[i].price_high;
            if (bars[i].price_low < recent_price_low) recent_price_low = bars[i].price_low;
        }
        
        float recent_price_range = (recent_price_high - recent_price_low) / tick_size;
        float recent_cvd_move = recent_cvd_end - recent_cvd_start;
        float absorb_price_max = is_nq ? CVD_ABSORB_PRICE_MAX_TICKS_NQ : CVD_ABSORB_PRICE_MAX_TICKS_ES;
        
        // Prix flat ET CVD bouge beaucoup
        if (recent_price_range < absorb_price_max && 
            fabs(recent_cvd_move) > CVD_ABSORB_CVD_MIN_MOVE) {
            
            result.has_absorption = true;
            float absorb_strength = fmin(fabs(recent_cvd_move) / 1000.0f, 1.0f);
            
            if (recent_cvd_move > 0) {
                // CVD monte pendant prix flat → ACCUMULATION → pré-breakout HAUSSIER
                result.score += absorb_strength * CVD_WEIGHT_ABSORPTION;
                result.boost_long += fmin(absorb_strength * 0.05f, 0.08f);
                
                if (result.primary_signal == CVD_DIV_NONE) {
                    result.primary_signal = CVD_DIV_ABSORPTION_BUY;
                } else {
                    result.secondary_signal = CVD_DIV_ABSORPTION_BUY;
                }
            } else {
                // CVD baisse pendant prix flat → DISTRIBUTION → pré-breakout BAISSIER
                result.score -= absorb_strength * CVD_WEIGHT_ABSORPTION;
                result.boost_short += fmin(absorb_strength * 0.05f, 0.08f);
                
                if (result.primary_signal == CVD_DIV_NONE) {
                    result.primary_signal = CVD_DIV_ABSORPTION_SELL;
                } else {
                    result.secondary_signal = CVD_DIV_ABSORPTION_SELL;
                }
            }
        }
    }
    
    // --- FIX 11/02/2026: Résolution de conflit absorption vs hidden ---
    // Si absorption BUY détectée mais hidden BEARISH aussi → neutraliser hidden bearish
    // Si absorption SELL détectée mais hidden BULLISH aussi → neutraliser hidden bullish
    // L'absorption (signal court terme sur 3 barres) prime sur la structure long terme
    if (result.has_absorption && result.has_hidden_divergence) {
        bool absorb_is_buy = (result.primary_signal == CVD_DIV_ABSORPTION_BUY || 
                              result.secondary_signal == CVD_DIV_ABSORPTION_BUY);
        bool absorb_is_sell = (result.primary_signal == CVD_DIV_ABSORPTION_SELL || 
                               result.secondary_signal == CVD_DIV_ABSORPTION_SELL);
        bool hidden_is_bearish = (result.primary_signal == CVD_DIV_HIDDEN_BEARISH || 
                                  result.secondary_signal == CVD_DIV_HIDDEN_BEARISH);
        bool hidden_is_bullish = (result.primary_signal == CVD_DIV_HIDDEN_BULLISH || 
                                  result.secondary_signal == CVD_DIV_HIDDEN_BULLISH);
        
        if ((absorb_is_buy && hidden_is_bearish) || (absorb_is_sell && hidden_is_bullish)) {
            // Conflit détecté → retirer la contribution hidden divergence du score
            // et promouvoir l'absorption comme signal principal
            result.has_hidden_divergence = false;
            
            if (absorb_is_buy && hidden_is_bearish) {
                // Annuler le malus hidden bearish, garder le bonus absorption
                float hidden_str = (cvdMax_B - cvdMax_A) / fmax(result.cvd_range, 1.0f);
                result.score += hidden_str * CVD_WEIGHT_HIDDEN;  // Annule le -= précédent
                result.boost_short = 0.0f;  // Retirer le boost short de hidden
            } else {
                // Annuler le bonus hidden bullish, garder le malus absorption
                float hidden_str = (cvdMin_A - cvdMin_B) / fmax(result.cvd_range, 1.0f);
                result.score -= hidden_str * CVD_WEIGHT_HIDDEN;  // Annule le += précédent
                result.boost_long = 0.0f;  // Retirer le boost long de hidden (sauf absorption)
            }
            
            // Remettre l'absorption comme primary si hidden l'avait pris
            if (result.primary_signal == CVD_DIV_HIDDEN_BEARISH || 
                result.primary_signal == CVD_DIV_HIDDEN_BULLISH) {
                result.primary_signal = absorb_is_buy ? CVD_DIV_ABSORPTION_BUY : CVD_DIV_ABSORPTION_SELL;
                result.secondary_signal = CVD_DIV_NONE;
            } else {
                result.secondary_signal = CVD_DIV_NONE;
            }
        }
    }
    
    // =====================================================================
    // DÉTECTION 4: CVD FLIP (changement de régime)
    // =====================================================================
    // Le CVD passe de négatif à positif (ou inverse) sur le lookback.
    // C'est un changement de main entre acheteurs et vendeurs.
    //
    // On compare le CVD de la première barre vs la dernière.
    // Le flip doit être significatif (> seuil).
    // =====================================================================
    
    float cvd_oldest = bars[0].cvd;
    float cvd_newest = bars[actual_count - 1].cvd;
    
    // CVD passe de négatif à positif (ou de très bas à très haut)
    if (cvd_oldest < -CVD_FLIP_THRESHOLD && cvd_newest > CVD_FLIP_THRESHOLD) {
        result.has_cvd_flip = true;
        float flip_magnitude = (cvd_newest - cvd_oldest) / fmax(result.cvd_range, 1.0f);
        
        result.score += flip_magnitude * CVD_WEIGHT_FLIP;
        result.boost_long += fmin(flip_magnitude * 0.03f, 0.05f);
        
        if (result.primary_signal == CVD_DIV_NONE) {
            result.primary_signal = CVD_DIV_FLIP_BULLISH;
        } else {
            result.secondary_signal = CVD_DIV_FLIP_BULLISH;
        }
    }
    // CVD passe de positif à négatif
    else if (cvd_oldest > CVD_FLIP_THRESHOLD && cvd_newest < -CVD_FLIP_THRESHOLD) {
        result.has_cvd_flip = true;
        float flip_magnitude = (cvd_oldest - cvd_newest) / fmax(result.cvd_range, 1.0f);
        
        result.score -= flip_magnitude * CVD_WEIGHT_FLIP;
        result.boost_short += fmin(flip_magnitude * 0.03f, 0.05f);
        
        if (result.primary_signal == CVD_DIV_NONE) {
            result.primary_signal = CVD_DIV_FLIP_BEARISH;
        } else {
            result.secondary_signal = CVD_DIV_FLIP_BEARISH;
        }
    }
    
    // =====================================================================
    // CALCUL FINAL: Score et Confiance
    // =====================================================================
    
    // Clamp le score à [-1.0, +1.0]
    if (result.score > 1.0f) result.score = 1.0f;
    if (result.score < -1.0f) result.score = -1.0f;
    
    // Confiance = basée sur le nombre de signaux convergents + force
    int signal_count = (result.has_classic_divergence ? 1 : 0)
                     + (result.has_hidden_divergence ? 1 : 0)
                     + (result.has_absorption ? 1 : 0)
                     + (result.has_cvd_flip ? 1 : 0);
    
    result.confidence = fmin(fabs(result.score) + (signal_count * 0.15f), 1.0f);
    
    // --- Renforcer les VETO si confiance forte ---
    // Si divergence classique + un autre signal dans la même direction → VETO confirmé
    if (result.has_classic_divergence && signal_count >= 2 && result.confidence > 0.5f) {
        // Le VETO est déjà set, on renforce juste la raison
        char extra[64];
        snprintf(extra, sizeof(extra), " [CONFIRMÉ par %d signaux, conf=%.0f%%]",
                 signal_count, result.confidence * 100.0f);
        
        // Append à veto_reason si pas trop long
        size_t current_len = strlen(result.veto_reason);
        if (current_len + strlen(extra) < sizeof(result.veto_reason)) {
            strcat(result.veto_reason, extra);
        }
    }
    
    // --- Description du signal pour les logs ---
    if (result.primary_signal != CVD_DIV_NONE) {
        const char* signal_names[] = {
            "NONE", "CLASSIC_BEARISH", "CLASSIC_BULLISH",
            "HIDDEN_BULLISH", "HIDDEN_BEARISH",
            "ABSORPTION_BUY", "ABSORPTION_SELL",
            "FLIP_BULLISH", "FLIP_BEARISH"
        };
        
        const char* sym = is_nq ? "NQ" : "ES";
        
        if (result.secondary_signal != CVD_DIV_NONE) {
            snprintf(result.signal_description, sizeof(result.signal_description),
                     "[%s CVD] %s + %s | score=%.3f conf=%.0f%% | %d barres | CVD_range=%.0f",
                     sym,
                     signal_names[result.primary_signal],
                     signal_names[result.secondary_signal],
                     result.score, result.confidence * 100.0f,
                     actual_count, result.cvd_range);
        } else {
            snprintf(result.signal_description, sizeof(result.signal_description),
                     "[%s CVD] %s | score=%.3f conf=%.0f%% | %d barres | CVD_range=%.0f",
                     sym,
                     signal_names[result.primary_signal],
                     result.score, result.confidence * 100.0f,
                     actual_count, result.cvd_range);
        }
    } else {
        snprintf(result.signal_description, sizeof(result.signal_description),
                 "[%s CVD] Aucune divergence détectée | %d barres | CVD_range=%.0f",
                 is_nq ? "NQ" : "ES", actual_count, result.cvd_range);
    }
    
    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION D'INTÉGRATION: GetCVD_LayerAdjustment()
// ═══════════════════════════════════════════════════════════════════════════════
// Fonction simplifiée pour intégrer dans les Layers existants.
// Retourne un score d'ajustement à AJOUTER au score Layer 3 (bloc A7).
//
// Usage dans MIA_Layers.h:
//   float cvd_adj = GetCVD_LayerAdjustment(cvd_result, direction);
//   score += cvd_adj;
// ═══════════════════════════════════════════════════════════════════════════════

inline float GetCVD_LayerAdjustment(const CVD_AnalysisResult& cvd, int direction) {
    float adjustment = 0.0f;
    
    if (direction == 1) {  // LONG
        // Boost si signaux bullish
        adjustment += cvd.boost_long;
        // Malus si signaux bearish (hors VETO qui est géré séparément)
        if (cvd.score < -0.2f && !cvd.veto_long) {
            adjustment += cvd.score * 0.03f;  // Malus proportionnel
        }
    } else if (direction == -1) {  // SHORT
        // Boost si signaux bearish
        adjustment += cvd.boost_short;
        // Malus si signaux bullish (hors VETO)
        if (cvd.score > 0.2f && !cvd.veto_short) {
            adjustment += -cvd.score * 0.03f;  // Malus proportionnel
        }
    }
    
    // Clamp à [-0.10, +0.10] pour ne pas dominer le Layer 3
    if (adjustment > 0.10f) adjustment = 0.10f;
    if (adjustment < -0.10f) adjustment = -0.10f;
    
    return adjustment;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION D'INTÉGRATION: CheckCVD_Veto()
// ═══════════════════════════════════════════════════════════════════════════════
// Fonction simplifiée pour intégrer dans Layer 2 (VETO system).
// Retourne true si le trade devrait être bloqué.
//
// Usage dans MIA_Layers.h (Layer 2, section VETO CVD):
//   if (CheckCVD_Veto(cvd_result, direction)) {
//       snprintf(result.reason, ..., "%s", cvd_result.veto_reason);
//       return result;
//   }
// ═══════════════════════════════════════════════════════════════════════════════

inline bool CheckCVD_Veto(const CVD_AnalysisResult& cvd, int direction) {
    if (direction == 1 && cvd.veto_long) return true;
    if (direction == -1 && cvd.veto_short) return true;
    return false;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION DEBUG: LogCVD_Analysis()
// ═══════════════════════════════════════════════════════════════════════════════
// Log détaillé de l'analyse CVD pour diagnostic.
// Appeler avec sc.AddMessageToLog() dans la boucle principale.
// ═══════════════════════════════════════════════════════════════════════════════

inline void LogCVD_Analysis(SCStudyInterfaceRef sc, const CVD_AnalysisResult& cvd,
                             const char* symbol) {
    // Ne logger que si un signal est détecté (éviter le spam)
    if (cvd.primary_signal == CVD_DIV_NONE) return;
    
    char log_msg[512];
    snprintf(log_msg, sizeof(log_msg),
             "📊 CVD_DIV [%s] %s | veto_L=%d veto_S=%d | boost_L=%.3f boost_S=%.3f | bars=%d",
             symbol,
             cvd.signal_description,
             cvd.veto_long ? 1 : 0,
             cvd.veto_short ? 1 : 0,
             cvd.boost_long,
             cvd.boost_short,
             cvd.bars_in_buffer);
    
    sc.AddMessageToLog(log_msg, 0);
}
