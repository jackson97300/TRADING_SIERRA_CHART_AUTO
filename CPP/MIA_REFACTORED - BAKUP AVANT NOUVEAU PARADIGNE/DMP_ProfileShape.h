#pragma once
#include "DMP_Writer.h"  // Chaîne complète d'includes
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_ProfileShape.h  —  MIA Data Dumper G3 : Analyse Forme du Volume Profile
// Version 1.0 — Classification D / P / b / B + Double Distribution
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Utilise sc.VolumeAtPriceForBars pour analyser la distribution du volume
//  et classifier la forme du profil de la session.
//
//  ── FORMES DE PROFIL (Steidlmayer / Dalton) ──────────────────────────────────
//
//    D-shape (0) : Distribution normale (cloche), volume concentré au milieu
//                  → Marché équilibré, range probable, fader les extrêmes
//
//    P-shape (1) : Volume concentré dans la partie HAUTE du range
//                  → Acheteurs actifs, "new money buying", bullish
//                  → POC proche du HIGH, single prints en bas
//
//    b-shape (2) : Volume concentré dans la partie BASSE du range
//                  → Vendeurs actifs, "long liquidation", bearish
//                  → POC proche du LOW, single prints en haut
//
//    B-shape (3) : Double distribution (deux POC distincts)
//                  → Breakout imminent, deux groupes de participants
//                  → LVN (single prints) entre les deux distributions
//
//  ── MÉTRIQUES CALCULÉES ──────────────────────────────────────────────────────
//
//    profile_shape      : 0=D, 1=P, 2=b, 3=B
//    profile_skew       : Asymétrie (-1.0 à +1.0), >0=bullish, <0=bearish
//    poc_position       : Position POC dans range (0.0=low, 0.5=mid, 1.0=high)
//    volume_imbalance   : Ratio volume haut vs bas (>1=bullish, <1=bearish)
//    is_double_dist     : 1.0 si double distribution détectée
//    dist_separation    : Distance entre les deux POC (en ticks) si B-shape
//    single_print_zone  : Prix milieu de la zone de single prints (LVN)
//
//  ── INDICES PERSISTANTS (90-99) ──────────────────────────────────────────────
//
//    100 = profile_shape_cached   [déplacé de 90 — conflit évité avec DMP_Writer]
//    101 = profile_skew_cached
//    102 = poc_position_cached
//    103 = secondary_poc_cached (pour B-shape)
//    104 = single_print_mid_cached
//    90-99 réservés DMP_Writer (90/91/92) et futurs modules
//
//  Dépendances : Aucune (self-contained, utilise API Sierra Chart native)
//
// ═══════════════════════════════════════════════════════════════════════════════

#include <vector>
#include <algorithm>
#include <cmath>

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// Indices persistants
constexpr int DMP_PS_P_SHAPE      = 100;
constexpr int DMP_PS_P_SKEW       = 101;
constexpr int DMP_PS_P_POC_POS    = 102;
constexpr int DMP_PS_P_SEC_POC    = 103;
constexpr int DMP_PS_P_SP_MID     = 104;

// Valeurs de forme
constexpr float PS_D_SHAPE = 0.0f;  // Distribution normale (équilibre)
constexpr float PS_P_SHAPE = 1.0f;  // Volume en haut (bullish)
constexpr float PS_B_LOWER = 2.0f;  // Volume en bas (bearish) - lowercase b
constexpr float PS_B_DOUBLE = 3.0f; // Double distribution

// Seuils de classification
constexpr float PS_POC_HIGH_THRESH = 0.70f;  // POC > 70% du range = P-shape
constexpr float PS_POC_LOW_THRESH  = 0.30f;  // POC < 30% du range = b-shape
constexpr float PS_SKEW_THRESH     = 0.25f;  // |skew| > 0.25 = asymétrique
constexpr float PS_IMBAL_THRESH    = 1.40f;  // Ratio > 1.4 = déséquilibre
constexpr float PS_BIMODAL_THRESH  = 0.60f;  // Valley < 60% peaks = bimodal
constexpr float PS_SINGLE_PRINT_THRESH = 0.15f; // Volume < 15% moyenne = single print

// Sentinel
constexpr float PS_INVALID = -999.0f;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

// Niveau de prix avec volume
struct PS_PriceLevel {
    float price;
    unsigned int volume;
    float normalized_vol;  // Volume normalisé (0-1)
    bool is_hvn;
    bool is_lvn;
    bool is_single_print;
};

// Résultat de l'analyse de forme
struct PS_ProfileAnalysis {
    // Classification principale
    float shape;           // 0=D, 1=P, 2=b, 3=B
    const char* shape_name;
    
    // Métriques détaillées
    float skewness;        // Asymétrie (-1 à +1)
    float poc_position;    // Position POC (0=low, 1=high)
    float volume_imbalance; // Ratio upper/lower volume
    
    // POC et distributions
    float primary_poc;     // POC principal
    float secondary_poc;   // POC secondaire (si B-shape)
    float poc_separation_ticks; // Distance entre POC
    
    // Single prints / LVN
    float single_print_high;
    float single_print_low;
    float single_print_mid;
    int   single_print_count;
    
    // HVN détectés
    float hvn_levels[5];
    int   hvn_count;
    
    // Validité
    bool is_valid;
    int  total_levels;
};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — COLLECTE DU VOLUME PAR PRIX
// ═══════════════════════════════════════════════════════════════════════════════

inline bool PS_CollectVolumeLevels(
    SCStudyInterfaceRef sc,
    int start_bar,
    int end_bar,
    float tick_size,
    std::vector<PS_PriceLevel>& levels,
    unsigned int& total_volume,
    float& range_high,
    float& range_low)
{
    levels.clear();
    total_volume = 0;
    range_high = -1e9f;
    range_low = 1e9f;

    if (start_bar < 0 || end_bar < start_bar) return false;
    if (sc.VolumeAtPriceForBars == nullptr) return false;

    // Parcourir toutes les barres de la période
    for (int bar = start_bar; bar <= end_bar; bar++) {
        int num_levels = sc.VolumeAtPriceForBars->GetNumberOfPriceLevelsForBar(bar);
        
        for (int i = 0; i < num_levels; i++) {
            const s_VolumeAtPriceV2* vap = nullptr;
            if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(bar, i, &vap))
                continue;
            if (vap == nullptr) continue;

            float price = vap->PriceInTicks * tick_size;
            unsigned int vol = vap->Volume;

            if (vol == 0) continue;

            // Mettre à jour range
            if (price > range_high) range_high = price;
            if (price < range_low) range_low = price;

            // Chercher si ce niveau existe déjà
            bool found = false;
            for (auto& lvl : levels) {
                if (std::fabs(lvl.price - price) < tick_size * 0.5f) {
                    lvl.volume += vol;
                    found = true;
                    break;
                }
            }
            
            if (!found) {
                PS_PriceLevel new_level = {};
                new_level.price = price;
                new_level.volume = vol;
                levels.push_back(new_level);
            }

            total_volume += vol;
        }
    }

    if (levels.empty() || total_volume == 0) return false;

    // Trier par prix croissant
    std::sort(levels.begin(), levels.end(),
        [](const PS_PriceLevel& a, const PS_PriceLevel& b) {
            return a.price < b.price;
        });

    // Normaliser les volumes (0-1)
    unsigned int max_vol = 0;
    for (const auto& lvl : levels) {
        if (lvl.volume > max_vol) max_vol = lvl.volume;
    }
    
    if (max_vol > 0) {
        for (auto& lvl : levels) {
            lvl.normalized_vol = (float)lvl.volume / (float)max_vol;
        }
    }

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — CALCUL DU POC ET POSITION
// ═══════════════════════════════════════════════════════════════════════════════

inline float PS_FindPOC(const std::vector<PS_PriceLevel>& levels) {
    if (levels.empty()) return PS_INVALID;
    
    unsigned int max_vol = 0;
    float poc = levels[0].price;
    
    for (const auto& lvl : levels) {
        if (lvl.volume > max_vol) {
            max_vol = lvl.volume;
            poc = lvl.price;
        }
    }
    
    return poc;
}

inline float PS_CalcPOCPosition(float poc, float range_high, float range_low) {
    if (range_high <= range_low) return 0.5f;
    float range = range_high - range_low;
    return (poc - range_low) / range;  // 0 = low, 1 = high
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — CALCUL DE L'ASYMÉTRIE (SKEWNESS)
// ═══════════════════════════════════════════════════════════════════════════════

inline float PS_CalcSkewness(
    const std::vector<PS_PriceLevel>& levels,
    float range_high,
    float range_low,
    unsigned int total_volume)
{
    if (levels.empty() || total_volume == 0) return 0.0f;
    if (range_high <= range_low) return 0.0f;

    float range = range_high - range_low;
    float mid_price = (range_high + range_low) / 2.0f;

    // Volume-weighted average price
    double vwap = 0.0;
    for (const auto& lvl : levels) {
        vwap += (double)lvl.price * (double)lvl.volume;
    }
    vwap /= (double)total_volume;

    // Skewness = (VWAP - mid) / (range/2)
    // Positif = volume concentré en haut (bullish)
    // Négatif = volume concentré en bas (bearish)
    float skew = ((float)vwap - mid_price) / (range / 2.0f);
    
    // Clamp entre -1 et +1
    if (skew > 1.0f) skew = 1.0f;
    if (skew < -1.0f) skew = -1.0f;
    
    return skew;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — CALCUL DU RATIO VOLUME HAUT/BAS
// ═══════════════════════════════════════════════════════════════════════════════

inline float PS_CalcVolumeImbalance(
    const std::vector<PS_PriceLevel>& levels,
    float mid_price)
{
    if (levels.empty()) return 1.0f;

    unsigned int vol_upper = 0;
    unsigned int vol_lower = 0;

    for (const auto& lvl : levels) {
        if (lvl.price >= mid_price) {
            vol_upper += lvl.volume;
        } else {
            vol_lower += lvl.volume;
        }
    }

    if (vol_lower == 0) return 10.0f;  // Très bullish
    if (vol_upper == 0) return 0.1f;   // Très bearish
    
    return (float)vol_upper / (float)vol_lower;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — DÉTECTION BIMODALITÉ (B-SHAPE / DOUBLE DISTRIBUTION)
// ═══════════════════════════════════════════════════════════════════════════════

struct PS_BimodalResult {
    bool is_bimodal;
    float peak1_price;      // POC du pic inférieur
    float peak2_price;      // POC du pic supérieur
    unsigned int peak1_vol;
    unsigned int peak2_vol;
    float valley_price;     // Prix du creux entre les pics
    unsigned int valley_vol;
    float separation_ticks;
};

inline PS_BimodalResult PS_DetectBimodality(
    const std::vector<PS_PriceLevel>& levels,
    float tick_size)
{
    PS_BimodalResult result = {};
    result.is_bimodal = false;

    if (levels.size() < 10) return result;  // Besoin d'assez de niveaux

    // Trouver le POC global
    int poc_idx = 0;
    unsigned int max_vol = 0;
    for (size_t i = 0; i < levels.size(); i++) {
        if (levels[i].volume > max_vol) {
            max_vol = levels[i].volume;
            poc_idx = (int)i;
        }
    }

    // Chercher un second pic significatif (au moins 70% du POC)
    const float secondary_thresh = 0.70f;
    const unsigned int min_secondary_vol = (unsigned int)(max_vol * secondary_thresh);

    int secondary_idx = -1;
    unsigned int secondary_vol = 0;

    // Chercher dans la partie inférieure (avant POC)
    for (int i = 0; i < poc_idx - 3; i++) {  // Au moins 3 niveaux d'écart
        if (levels[i].volume > secondary_vol && levels[i].volume >= min_secondary_vol) {
            // Vérifier qu'il y a un creux entre ce pic et le POC
            unsigned int min_between = levels[i].volume;
            for (int j = i + 1; j < poc_idx; j++) {
                if (levels[j].volume < min_between) {
                    min_between = levels[j].volume;
                }
            }
            // Le creux doit être < 60% des pics
            if (min_between < levels[i].volume * PS_BIMODAL_THRESH &&
                min_between < max_vol * PS_BIMODAL_THRESH) {
                secondary_vol = levels[i].volume;
                secondary_idx = i;
            }
        }
    }

    // Chercher aussi dans la partie supérieure (après POC)
    for (int i = poc_idx + 3; i < (int)levels.size(); i++) {
        if (levels[i].volume > secondary_vol && levels[i].volume >= min_secondary_vol) {
            unsigned int min_between = levels[i].volume;
            for (int j = poc_idx + 1; j < i; j++) {
                if (levels[j].volume < min_between) {
                    min_between = levels[j].volume;
                }
            }
            if (min_between < levels[i].volume * PS_BIMODAL_THRESH &&
                min_between < max_vol * PS_BIMODAL_THRESH) {
                secondary_vol = levels[i].volume;
                secondary_idx = i;
            }
        }
    }

    if (secondary_idx < 0) return result;  // Pas de second pic

    // Organiser les pics (lower vs upper)
    int lower_idx = (secondary_idx < poc_idx) ? secondary_idx : poc_idx;
    int upper_idx = (secondary_idx < poc_idx) ? poc_idx : secondary_idx;

    // Trouver le creux (valley) entre les deux pics
    int valley_idx = lower_idx;
    unsigned int valley_min = levels[lower_idx].volume;
    for (int i = lower_idx + 1; i < upper_idx; i++) {
        if (levels[i].volume < valley_min) {
            valley_min = levels[i].volume;
            valley_idx = i;
        }
    }

    // Vérifier que le creux est vraiment significatif
    unsigned int peak_avg = (levels[lower_idx].volume + levels[upper_idx].volume) / 2;
    if (valley_min > peak_avg * PS_BIMODAL_THRESH) {
        return result;  // Creux pas assez profond
    }

    // Double distribution confirmée !
    result.is_bimodal = true;
    result.peak1_price = levels[lower_idx].price;
    result.peak2_price = levels[upper_idx].price;
    result.peak1_vol = levels[lower_idx].volume;
    result.peak2_vol = levels[upper_idx].volume;
    result.valley_price = levels[valley_idx].price;
    result.valley_vol = valley_min;
    result.separation_ticks = (levels[upper_idx].price - levels[lower_idx].price) / tick_size;

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — DÉTECTION DES SINGLE PRINTS (LVN EXTRÊMES)
// ═══════════════════════════════════════════════════════════════════════════════

inline void PS_DetectSinglePrints(
    std::vector<PS_PriceLevel>& levels,
    unsigned int total_volume,
    float& sp_high,
    float& sp_low,
    int& sp_count)
{
    sp_high = PS_INVALID;
    sp_low = PS_INVALID;
    sp_count = 0;

    if (levels.empty() || total_volume == 0) return;

    float avg_vol = (float)total_volume / levels.size();
    float sp_threshold = avg_vol * PS_SINGLE_PRINT_THRESH;

    for (auto& lvl : levels) {
        if (lvl.volume < sp_threshold) {
            lvl.is_single_print = true;
            sp_count++;
            
            if (sp_high == PS_INVALID || lvl.price > sp_high) {
                sp_high = lvl.price;
            }
            if (sp_low == PS_INVALID || lvl.price < sp_low) {
                sp_low = lvl.price;
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — CLASSIFICATION DE LA FORME
// ═══════════════════════════════════════════════════════════════════════════════

inline float PS_ClassifyShape(
    float poc_position,
    float skewness,
    float volume_imbalance,
    bool is_bimodal)
{
    // Priorité 1 : Double distribution (B-shape)
    if (is_bimodal) {
        return PS_B_DOUBLE;
    }

    // Priorité 2 : P-shape (volume en haut, bullish)
    // POC en haut du range OU forte asymétrie positive OU fort ratio upper/lower
    if (poc_position >= PS_POC_HIGH_THRESH ||
        skewness >= PS_SKEW_THRESH ||
        volume_imbalance >= PS_IMBAL_THRESH) {
        return PS_P_SHAPE;
    }

    // Priorité 3 : b-shape (volume en bas, bearish)
    if (poc_position <= PS_POC_LOW_THRESH ||
        skewness <= -PS_SKEW_THRESH ||
        volume_imbalance <= (1.0f / PS_IMBAL_THRESH)) {
        return PS_B_LOWER;
    }

    // Défaut : D-shape (équilibre)
    return PS_D_SHAPE;
}

inline const char* PS_ShapeName(float shape) {
    int s = (int)shape;
    switch (s) {
        case 0: return "D";
        case 1: return "P";
        case 2: return "b";
        case 3: return "B";
        default: return "?";
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 10 — FONCTION MAÎTRE : PS_AnalyzeProfile()
// ═══════════════════════════════════════════════════════════════════════════════

inline PS_ProfileAnalysis PS_AnalyzeProfile(
    SCStudyInterfaceRef sc,
    int start_bar,
    int end_bar,
    float tick_size)
{
    PS_ProfileAnalysis result = {};
    result.is_valid = false;
    result.shape = PS_D_SHAPE;
    result.shape_name = "?";

    // 1. Collecter les volumes
    std::vector<PS_PriceLevel> levels;
    unsigned int total_volume = 0;
    float range_high = 0, range_low = 0;

    if (!PS_CollectVolumeLevels(sc, start_bar, end_bar, tick_size,
                                 levels, total_volume, range_high, range_low)) {
        return result;
    }

    if (levels.size() < 5) return result;  // Pas assez de données

    result.total_levels = (int)levels.size();
    result.is_valid = true;

    // 2. Trouver le POC principal
    result.primary_poc = PS_FindPOC(levels);
    result.poc_position = PS_CalcPOCPosition(result.primary_poc, range_high, range_low);

    // 3. Calculer l'asymétrie
    result.skewness = PS_CalcSkewness(levels, range_high, range_low, total_volume);

    // 4. Calculer le ratio volume haut/bas
    float mid_price = (range_high + range_low) / 2.0f;
    result.volume_imbalance = PS_CalcVolumeImbalance(levels, mid_price);

    // 5. Détecter la bimodalité (double distribution)
    PS_BimodalResult bimodal = PS_DetectBimodality(levels, tick_size);
    if (bimodal.is_bimodal) {
        result.secondary_poc = (bimodal.peak1_price != result.primary_poc) ?
                                bimodal.peak1_price : bimodal.peak2_price;
        result.poc_separation_ticks = bimodal.separation_ticks;
        result.single_print_mid = bimodal.valley_price;
    }

    // 6. Détecter les single prints
    PS_DetectSinglePrints(levels, total_volume,
                           result.single_print_high,
                           result.single_print_low,
                           result.single_print_count);
    
    if (result.single_print_high != PS_INVALID && result.single_print_low != PS_INVALID) {
        result.single_print_mid = (result.single_print_high + result.single_print_low) / 2.0f;
    }

    // 7. Collecter les HVN (top 5)
    // Trier par volume décroissant
    std::vector<PS_PriceLevel> sorted_levels = levels;
    std::sort(sorted_levels.begin(), sorted_levels.end(),
        [](const PS_PriceLevel& a, const PS_PriceLevel& b) {
            return a.volume > b.volume;
        });

    result.hvn_count = 0;
    for (int i = 0; i < 5 && i < (int)sorted_levels.size(); i++) {
        result.hvn_levels[i] = sorted_levels[i].price;
        result.hvn_count++;
    }

    // 8. Classification finale
    result.shape = PS_ClassifyShape(
        result.poc_position,
        result.skewness,
        result.volume_imbalance,
        bimodal.is_bimodal);
    result.shape_name = PS_ShapeName(result.shape);

    return result;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11 — INTÉGRATION AVEC DMP (features ML)
// ═══════════════════════════════════════════════════════════════════════════════

// Structure pour les features ML
struct PS_MLFeatures {
    float profile_shape;        // 0=D, 1=P, 2=b, 3=B
    float profile_skew;         // -1.0 à +1.0
    float poc_position;         // 0.0 à 1.0
    float volume_imbalance;     // ratio (typiquement 0.5 à 2.0)
    float is_double_dist;       // 0.0 ou 1.0
    float poc_separation_ticks; // distance entre POC si B-shape
    float single_print_mid;     // prix milieu zone single prints
    float single_print_count;   // nombre de niveaux single print
    float hvn_dominant;         // prix du HVN principal
};

inline void PS_FillMLFeatures(const PS_ProfileAnalysis& analysis, PS_MLFeatures& f) {
    f.profile_shape = analysis.shape;
    f.profile_skew = analysis.skewness;
    f.poc_position = analysis.poc_position;
    f.volume_imbalance = analysis.volume_imbalance;
    f.is_double_dist = (analysis.shape == PS_B_DOUBLE) ? 1.0f : 0.0f;
    f.poc_separation_ticks = analysis.poc_separation_ticks;
    f.single_print_mid = (analysis.single_print_mid != PS_INVALID) ? 
                          analysis.single_print_mid : 0.0f;
    f.single_print_count = (float)analysis.single_print_count;
    f.hvn_dominant = (analysis.hvn_count > 0) ? analysis.hvn_levels[0] : 0.0f;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 12 — INTERPRÉTATION TRADING (Guide Pro)
// ═══════════════════════════════════════════════════════════════════════════════

struct PS_TradingContext {
    const char* bias;           // "BULLISH" / "BEARISH" / "NEUTRAL" / "BREAKOUT"
    const char* expected_day;   // Type de journée probable
    const char* action;         // Action recommandée
    float confidence;           // 0.0 à 1.0
    bool avoid_fading;          // Ne pas fader la direction
    bool watch_breakout;        // Surveiller breakout imminent
};

inline PS_TradingContext PS_GetTradingContext(const PS_ProfileAnalysis& analysis) {
    PS_TradingContext ctx = {};
    
    switch ((int)analysis.shape) {
        case 0:  // D-shape
            ctx.bias = "NEUTRAL";
            ctx.expected_day = "RANGE";
            ctx.action = "Fader VAH/VAL, mean-revert vers POC";
            ctx.confidence = 0.65f;
            ctx.avoid_fading = false;
            ctx.watch_breakout = false;
            break;
            
        case 1:  // P-shape
            ctx.bias = "BULLISH";
            ctx.expected_day = "CONTINUATION_UP";
            ctx.action = "Acheter dips, single prints = support";
            ctx.confidence = 0.70f;
            ctx.avoid_fading = true;  // Ne pas shorter
            ctx.watch_breakout = false;
            break;
            
        case 2:  // b-shape
            ctx.bias = "BEARISH";
            ctx.expected_day = "CONTINUATION_DOWN";
            ctx.action = "Vendre rallies, single prints = résistance";
            ctx.confidence = 0.70f;
            ctx.avoid_fading = true;  // Ne pas longer
            ctx.watch_breakout = false;
            break;
            
        case 3:  // B-shape (double distribution)
            ctx.bias = "BREAKOUT";
            ctx.expected_day = "TREND_IMMINENT";
            ctx.action = "Attendre breakout, trader dans direction du break";
            ctx.confidence = 0.75f;
            ctx.avoid_fading = true;
            ctx.watch_breakout = true;  // ⚠️ Breakout imminent
            break;
            
        default:
            ctx.bias = "UNKNOWN";
            ctx.expected_day = "?";
            ctx.action = "Attendre plus de données";
            ctx.confidence = 0.0f;
            break;
    }
    
    return ctx;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 13 — LOGGING / DIAGNOSTIC
// ═══════════════════════════════════════════════════════════════════════════════

inline void PS_LogAnalysis(SCStudyInterfaceRef sc, const PS_ProfileAnalysis& a) {
    if (!a.is_valid) {
        sc.AddMessageToLog("[ProfileShape] Analyse invalide - données insuffisantes", 1);
        return;
    }

    char msg[512];
    snprintf(msg, sizeof(msg),
        "[ProfileShape] Shape=%s | POC=%.2f (pos=%.0f%%) | Skew=%.2f | "
        "Imbal=%.2f | DoubleDist=%s | Levels=%d",
        a.shape_name,
        a.primary_poc,
        a.poc_position * 100.0f,
        a.skewness,
        a.volume_imbalance,
        (a.shape == PS_B_DOUBLE) ? "YES" : "NO",
        a.total_levels);
    sc.AddMessageToLog(msg, 0);

    if (a.shape == PS_B_DOUBLE) {
        snprintf(msg, sizeof(msg),
            "[ProfileShape] B-Shape Details: POC1=%.2f POC2=%.2f Sep=%.0f ticks Valley=%.2f",
            a.primary_poc, a.secondary_poc,
            a.poc_separation_ticks,
            a.single_print_mid);
        sc.AddMessageToLog(msg, 0);
    }

    if (a.single_print_count > 0) {
        snprintf(msg, sizeof(msg),
            "[ProfileShape] Single Prints: %d levels [%.2f - %.2f]",
            a.single_print_count,
            a.single_print_low,
            a.single_print_high);
        sc.AddMessageToLog(msg, 0);
    }

    PS_TradingContext ctx = PS_GetTradingContext(a);
    snprintf(msg, sizeof(msg),
        "[ProfileShape] Trading: %s | Day=%s | Action=%s | Conf=%.0f%%",
        ctx.bias, ctx.expected_day, ctx.action, ctx.confidence * 100.0f);
    sc.AddMessageToLog(msg, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 14 — HELPER : Trouver la première barre de la session
// ═══════════════════════════════════════════════════════════════════════════════

inline int PS_FindSessionStartBar(SCStudyInterfaceRef sc, int current_bar) {
    // Remonter jusqu'au début de la session (IsNewTradingDay)
    for (int bar = current_bar; bar >= 0; bar--) {
        if (sc.IsNewTradingDay(bar)) {
            return bar;
        }
    }
    return 0;  // Fallback au début du chart
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 15 — FONCTION WRAPPER SIMPLE
// ═══════════════════════════════════════════════════════════════════════════════

// Analyse le profil de la session courante
inline PS_ProfileAnalysis PS_AnalyzeCurrentSession(SCStudyInterfaceRef sc) {
    int session_start = PS_FindSessionStartBar(sc, sc.Index);
    return PS_AnalyzeProfile(sc, session_start, sc.Index, sc.TickSize);
}

// Analyse le profil d'une période fixe (ex: dernières N barres)
inline PS_ProfileAnalysis PS_AnalyzeLastNBars(SCStudyInterfaceRef sc, int n_bars) {
    int start = sc.Index - n_bars;
    if (start < 0) start = 0;
    return PS_AnalyzeProfile(sc, start, sc.Index, sc.TickSize);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_ProfileShape.h  —  v1.0
// ═══════════════════════════════════════════════════════════════════════════════
