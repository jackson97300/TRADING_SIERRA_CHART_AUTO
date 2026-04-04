#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Transform.h  —  MIA Data Dumper G3 : Section B — FEATURES ML
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle   : Transformer les prix bruts (DMP_RawData) en features ML-ready.
//           Aucune lecture Sierra Chart ici — seulement des mathématiques.
//
//  Principe : JAMAIS de prix bruts dans les features ML.
//             Tout est exprimé en DISTANCE par rapport au prix courant,
//             normalisée en ticks ET en ATR (deux granularités).
//
//  Sortie : DMP_MLFeatures — 142 champs prêts pour Python/sklearn.
//
//  Convention de signe :
//     distance > 0  →  niveau AU-DESSUS du prix courant
//     distance < 0  →  niveau EN-DESSOUS du prix courant
//     Exemple : dist_vwap = +8.5 ticks → prix 8.5 ticks SOUS le VWAP
//
//  Auteur : MIA Trading System
//  Date   : 2026-02-28
//  Build  : G3-Unifier v1.0
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_Reader.h"
#include "DMP_HVN_LVN.h"   // Section C — HVN/LVN via VolumeAtPriceForBars
#include <algorithm>   // std::min, std::max
#include <cmath>       // std::fabs, std::isfinite
#include <fstream>     // std::ofstream (pour DMP_WriteCSVHeader)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES DE NORMALISATION
// ═══════════════════════════════════════════════════════════════════════════════

// Clip ATR normalisé : ±5 ATR max pour éviter les outliers
constexpr float DMP_ATR_CLIP        = 5.0f;

// Distance max en ticks pour déclarer un niveau "proche"
constexpr float DMP_PROXIMITY_ES    = 20.0f;   // 5 points ES
constexpr float DMP_PROXIMITY_NQ    = 30.0f;   // 7.5 points NQ

// Seuils IB (ratio range/ATR)
constexpr float DMP_IB_NARROW_RATIO = 0.40f;   // IB étroite < 40% ATR
constexpr float DMP_IB_WIDE_RATIO   = 0.80f;   // IB large   > 80% ATR

// Seuils delta pour booléens
constexpr float DMP_DELTA_STRONG    = 500.0f;  // Delta fort = conviction
constexpr float DMP_CVD_SLOPE_MIN   = 50.0f;   // CVD slope significative

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURE DMP_MLFeatures (142 champs)
// ═══════════════════════════════════════════════════════════════════════════════

struct DMP_MLFeatures {

    // ─────────────────────────────────────────────────────────────────────────
    // MÉTA (3 champs — non utilisés comme features ML directement)
    // ─────────────────────────────────────────────────────────────────────────
    long long   ts;                    // Timestamp Unix ms
    char        sym[4];                // "ES" ou "NQ"
    float       price;                 // Prix de clôture (référence)
    float       atr;                   // ATR journalier (dénominateur)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 1 — DISTANCES VWAP (13 champs)
    // Convention : positif = niveau au-dessus du prix
    // ─────────────────────────────────────────────────────────────────────────

    // VWAP Journalier
    float dist_vwap_d;                 // Distance au VWAP journalier (ticks)
    float dist_vwap_d_atr;            // Distance normalisée ATR (±5)
    float dist_vwap_d_sd1u;           // Distance au VWAP +1σ (ticks)
    float dist_vwap_d_sd1d;           // Distance au VWAP -1σ (ticks)
    float dist_vwap_d_sd2u;           // Distance au VWAP +2σ (ticks)
    float dist_vwap_d_sd2d;           // Distance au VWAP -2σ (ticks)

    // VWAP Weekly & Monthly
    float dist_vwap_w;                 // Distance au VWAP Weekly (ticks)
    float dist_vwap_w_atr;            // idem normalisé ATR
    float dist_vwap_m;                 // Distance au VWAP Monthly (ticks)
    float dist_vwap_m_atr;            // idem normalisé ATR

    // Position relative VWAP (0.0 = exactement sur, -1.0 = 1 ATR en-dessous, +1.0 = 1 ATR au-dessus)
    float vwap_d_side;                 // -1=sous VWAP_D / +1=dessus (signe pur)
    float vwap_w_side;                 // -1=sous VWAP_W / +1=dessus
    float vwap_m_side;                 // -1=sous VWAP_M / +1=dessus

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 2 — VOLUME PROFILE (14 champs)
    // ─────────────────────────────────────────────────────────────────────────

    // Session Courante
    float dist_cur_vpoc;              // Distance au VPOC courant (ticks)
    float dist_cur_vah;               // Distance au VAH courant (ticks)
    float dist_cur_val;               // Distance au VAL courant (ticks)
    float va_position_pct;            // Position dans VA : 0.0=VAL, 1.0=VAH (-1=hors range)
    float inside_cur_va;              // 1=dans la VA courante, 0=hors VA

    // Session Précédente (J-1) — TRÈS fort pouvoir prédictif
    float dist_prev_vpoc;             // Distance au PVPOC (ticks)
    float dist_prev_vpoc_atr;         // idem normalisé ATR
    float dist_prev_vah;              // Distance au PVAH (ticks)
    float dist_prev_val;              // Distance au PVAL (ticks)
    float dist_prev_vwap;             // Distance au PVWAP (ticks)
    float dist_prev_vwap_sd1u;        // Distance au PVWAP +1σ (ticks)
    float dist_prev_vwap_sd1d;        // Distance au PVWAP -1σ (ticks)
    float inside_prev_va;             // 1=dans la VA J-1, 0=hors VA
    float open_in_prev_va;            // 1=open_cash était dans la VA J-1

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 3 BIS — MENTHORQ DAILY RANGE (2 champs) — du snapshot
    // ─────────────────────────────────────────────────────────────────────────

    float dist_1d_min_ticks;          // Distance au target bas MenthorQ (ticks, négatif=sous prix)
    float dist_1d_max_ticks;          // Distance au target haut MenthorQ (ticks, positif=au-dessus)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 3 TER — NEXT WALL (2 champs) — nearest GEX avec direction
    // ─────────────────────────────────────────────────────────────────────────

    float next_wall_dist_ticks;       // Distance au mur gamma le plus proche (ticks, abs)
    float next_wall_is_call;          // 1=mur est côté Call (au-dessus) / 0=côté Put (en-dessous)

    // Niveaux principaux
    float dist_mq_call;               // Distance au Call Resistance (ticks, + = au-dessus)
    float dist_mq_put;                // Distance au Put Support (ticks)
    float dist_mq_hvl;                // Distance au HVL (ticks)
    float dist_mq_call_0dte;          // Distance au Call 0DTE (ticks)
    float dist_mq_put_0dte;           // Distance au Put 0DTE (ticks)

    // GEX — nearest above/below
    float dist_gex_nearest_up;        // GEX le plus proche au-dessus (ticks)
    float dist_gex_nearest_dn;        // GEX le plus proche en-dessous (ticks, négatif)
    float gex_cluster_count;          // Nb GEX dans un rayon de 30 ticks

    // Blind Spots — nearest above/below
    float dist_blind_nearest_up;      // Blind Spot le plus proche au-dessus
    float dist_blind_nearest_dn;      // Blind Spot le plus proche en-dessous

    // VIX contexte
    float vix_level;                  // VIX courant
    float dist_vix_hvl;               // Distance au HVL VIX (si VIX traverse HVL → flip)
    float vix_regime;                 // 0=calme(<15) / 1=normal(15-25) / 2=volatile(>25) / 3=extrême(>35)
    float vix_above_hvl;              // 1=VIX > HVL (régime incertain)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 4 — SESSION & IB (21 champs)
    // ─────────────────────────────────────────────────────────────────────────

    // Initial Balance
    float dist_ib_high;               // Distance au IB High (ticks)
    float dist_ib_low;                // Distance au IB Low (ticks)
    float ib_range_ticks;             // Taille IB en ticks
    float ib_range_atr;              // IB range / ATR (contexte type de journée)
    float ib_is_narrow;               // 1=IB étroite (<40% ATR) → breakout probable
    float ib_is_wide;                 // 1=IB large   (>80% ATR) → journée normale
    float ib_position_pct;            // Position dans IB : 0.0=bas, 1.0=haut
    float ib_broken_up;               // 1=IB High cassé vers haut
    float ib_broken_down;             // 1=IB Low cassé vers bas
    float ib_complete;                // 1=IB formée (>=10h30 ET)

    // Session Extremes
    float dist_sess_high;             // Distance au High session (ticks)
    float dist_sess_low;              // Distance au Low session (ticks)
    float sess_range_ticks;           // Range total session en ticks
    float sess_range_atr;            // Range session / ATR

    // Open & Overnight
    float dist_open_cash;             // Distance à l'Open 9h30 ET (ticks)
    float dist_open_830;              // Distance à l'Open 8h30 ET (ticks)
    float dist_ovn_high;              // Distance au High overnight (ticks)
    float dist_ovn_low;               // Distance au Low overnight (ticks)
    float ovn_range_ticks;            // Range overnight en ticks
    float open_gap_ticks;             // Gap entre Open 9h30 et PVPOC (ticks)
    float open_position;              // -2=far below VAL/-1=below VAL/0=in VA/+1=above VAH/+2=far above VAH

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 5 — COMPOSITE PROFILES (12 champs)
    // ─────────────────────────────────────────────────────────────────────────

    float dist_comp_20d_vpoc;
    float dist_comp_20d_vpoc_atr;
    float dist_comp_20d_vah;
    float dist_comp_20d_val;
    float dist_comp_50d_vpoc;
    float dist_comp_50d_vpoc_atr;
    float dist_comp_50d_vah;
    float dist_comp_50d_val;
    // Confluence composite (prix est dans une VA composite ?)
    float inside_comp_20d_va;         // 1=dans la VA 20J
    float inside_comp_50d_va;         // 1=dans la VA 50J
    float comp_vpoc_align_20_50;      // 1=VPOC 20J et 50J sont proches (<20 ticks)
    float comp_vpoc_align_day_20;     // 1=VPOC courant et 20J sont proches (<15 ticks)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 6 — FPBS / ORDERFLOW (22 champs)
    // ─────────────────────────────────────────────────────────────────────────

    // Delta & Volume
    float delta_bar;                  // Delta barre (ask - bid volume)
    float delta_bar_vol_norm;         // Delta / volume total → [-1, +1] (pas ATR, corrigé Bug #8)
    float delta_day;                  // Delta cumulatif journée
    float delta_day_dir;              // -1/0/+1 direction delta jour
    float ask_pct;                    // % volume Ask (>55% = pression acheteurs)
    float bid_pct;                    // % volume Bid
    float ask_bid_imbalance;          // (ask% - 50%) / 50% → [-1, +1]
    float avg_trade_size;             // Taille moyenne des trades (institution proxy)
    float avg_bid_size;               // Taille moy Bid (vendeurs)
    float avg_ask_size;               // Taille moy Ask (acheteurs)
    float large_trader_ratio;         // avg_ask_size / avg_bid_size → ratio institutionnel
    float vol_per_sec;                // Urgence : volume / seconde
    float bar_duration_sec;           // Durée barre en secondes
    float finish_strength;            // Finish Ask-Bid % (clôture barre)
    float poc_bar_dist;               // Distance entre prix et POC intra-barre (ticks)

    // CVD
    float cvd_day;                    // CVD cumulatif journée
    float cvd_day_dir;                // Direction CVD : -1/0/+1
    float cvd_ohlc_range;             // Range OHLC du CVD (indique amplitude divergence)

    // Rotation
    float rotation_up;                // Signal rotation haussière actif
    float rotation_dn;                // Signal rotation baissière actif
    float rotation_zz_osc;           // Oscillateur ZigZag (amplitude pivot)
    float delta_divergence;           // +1=div buy / -1=div sell / 0=neutre

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 7 — BATAILLE NAVALE SIGNAUX (13 champs)
    // ─────────────────────────────────────────────────────────────────────────

    float bn_color_up;                // Zone bullish active
    float bn_color_dn;                // Zone bearish active
    float bn_absorb_ask;              // Absorption vendeurs (bullish)
    float bn_absorb_bid;              // Absorption acheteurs (bearish)
    float bn_long_up;                 // Longue barre bullish
    float bn_long_dn;                 // Longue barre bearish
    float bn_pressure_ask;            // Double/Triple Ask actif
    float bn_pressure_bid;            // Double/Triple Bid actif
    float bn_score_raw;               // Score BN composite [-1, +1] (brut)
    float bn_score_bull;              // Score bullish [0, 1]
    float bn_score_bear;              // Score bearish [0, 1]
    float dist_big_ask_nearest_up;    // Big Ask le plus proche AU-DESSUS (+ticks)
    float dist_big_ask_nearest_dn;    // Big Ask le plus proche EN-DESSOUS (-ticks)
    float dist_big_bid_nearest_up;    // Big Bid le plus proche AU-DESSUS (+ticks)
    float dist_big_bid_nearest_dn;    // Big Bid le plus proche EN-DESSOUS (-ticks)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 8 — SWING STRUCTURE (6 champs)
    // ─────────────────────────────────────────────────────────────────────────

    float dist_swing_high;            // Distance au dernier Swing High (ticks)
    float dist_swing_low;             // Distance au dernier Swing Low (ticks)
    float swing_range_ticks;          // Range Swing (H-L)
    float price_vs_swing_mid;         // Position vs milieu swing : +1=haut/-1=bas
    float new_swing_high;             // 1=nouveau Swing High cette barre
    float new_swing_low;              // 1=nouveau Swing Low cette barre

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 9 — CONTEXTE MARCHÉ (6 champs)
    // ─────────────────────────────────────────────────────────────────────────

    float open_type;                  // v2: 0=UNKNOWN/1=OD_UP/2=OD_DOWN/3=OTD_UP/4=OTD_DOWN/
                                      //     5=ORR_UP/6=ORR_DOWN/7=OAIR/8=OAOR_UP/9=OAOR_DOWN/
                                      //     10=ODF_UP/11=ODF_DOWN (direction incluse, guide pro)
    float open_zone;                  // Zone d'ouverture vs PDH/PDL/VAH/VAL/POC
                                      //     1=<PDL / 2=VAL-PDL / 3=POC-VAL / 4=≈POC /
                                      //     5=VAH-POC / 6=PDH-VAH / 7=>PDH
    float open_bias_conf;             // Confiance directionnelle de l'open_type [0.0-1.0]
                                      //     OD=0.85 / OTD=0.70 / OAOR=0.65 / ORR=0.60 / OAIR=0.30
    float open_direction;             // Direction encodée explicitement pour ML :
                                      //     +1.0 = biais haussier (OD_UP/OTD_UP/ORR_UP/OAOR_UP)
                                      //      0.0 = neutre (OAIR/ODF/UNKNOWN)
                                      //     -1.0 = biais baissier (OD_DOWN/OTD_DOWN/ORR_DOWN/OAOR_DOWN)
    float day_type;                   // 0=NonTrend / 1=Normal / 2=NormVar / 3=Neutral / 4=Trend
    float rule_80pct;                 // 1=règle 80% active (80% de traverser la VA)
    float trend_day_probability;      // 0.0-1.0 probabilité Trend Day (basé sur IB + OTF)
    float ma_trend;                   // +1=ma_fast>ma_slow / -1=inverse (trend LT)
    float vwap_ma_align;              // 1=VWAP_D et MA_fast du même côté
    // VWAP Slope — CRITIQUE Layer 3 : slope>0 ET delta>0 → filtre directionnel
    float vwap_slope_10;              // Pente VWAP 10 barres (pts/barre) — identique ancien dumper
    float vwap_slope_30;              // Pente VWAP 30 barres (pts/barre)
    float vwap_slope_10_dir;          // -1/0/+1 direction slope 10

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 10 — BOOLÉENS STRUCTURELS (13 champs)
    // ─────────────────────────────────────────────────────────────────────────

    float bool_above_cur_vpoc;        // 1=prix > VPOC courant
    float bool_above_prev_vpoc;       // 1=prix > PVPOC (J-1)
    float bool_above_vwap_d;          // 1=prix > VWAP journalier
    float bool_above_vwap_w;          // 1=prix > VWAP Weekly
    float bool_above_vwap_m;          // 1=prix > VWAP Monthly
    float bool_above_mq_hvl;          // 1=prix > HVL MenthorQ (régime Gamma)
    float bool_above_mq_call;         // 1=prix > Call Resistance (zone courte)
    float bool_near_level;            // 1=prix à moins de PROXIMITY_ES/NQ d'un niveau clé
    float bool_ib_inside;             // 1=prix à l'intérieur de l'IB
    float bool_session_early;         // 1=avant 10h00 ET (marché non stabilisé)
    float vwap_triple_align;          // +1=prix>3VWAPs / -1=prix<3VWAPs / 0=mixte (corrigé Bug #10)
    float bool_va_confluence;         // 1=VPOC courant et J-1 sont proches (<10 ticks)
    float bool_gex_flip_zone;         // 1=prix entre mq_put et mq_call (zone de flip gamma)

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE 11 — HVN / LVN SESSION (9 champs) — Section C
    // Nœuds de volume détectés via VolumeAtPriceForBars (session RTH courante)
    // HVN = zone forte (prix résiste) | LVN = zone faible (prix traverse vite)
    // ─────────────────────────────────────────────────────────────────────────

    float dist_session_hvn_above;      // HVN le plus proche au-dessus (ticks, positif)
    float dist_session_hvn_below;      // HVN le plus proche en-dessous (ticks, positif = distance abs)
    float dist_session_lvn_above;      // LVN le plus proche au-dessus (ticks, positif)
    float dist_session_lvn_below;      // LVN le plus proche en-dessous (ticks, positif = distance abs)
    float session_hvn_count;           // Nb HVN dans ±100 ticks (densité résistances)
    float session_lvn_count;           // Nb LVN dans ±100 ticks (densité zones faibles)
    float lvn_between;                 // 1=LVN entre prix et TP → prix traverse vite (positif)
    float hvn_between;                 // 1=HVN entre prix et TP → obstacle potentiel (négatif)
    float lvn_confluence_count;        // Nb LVN regroupés < 4 ticks du nearest LVN

    // ─────────────────────────────────────────────────────────────────────────
    // G12 PROFILE SHAPE (9 champs) — Forme du profil Volume Profile journalier
    // ─────────────────────────────────────────────────────────────────────────
    float profile_shape;       // Forme globale : 0=D(équilibre) / 1=P(bullish) /
                               //                 2=b(bearish)   / 3=B(double dist)
    float profile_skew;        // Asymétrie volume [-1.0 à +1.0] : >0=upper loaded, <0=lower
    float poc_position;        // Position du POC dans le range [0.0=bas, 0.5=mid, 1.0=haut]
    float volume_imbalance;    // Ratio volume upper half / lower half (1.0=équilibré)
    float is_double_dist;      // 1.0 si double distribution détectée (B-shape)
    float poc_separation_ticks;// Distance entre POC primaire et secondaire (B-shape, sinon 0)
    float single_print_mid;    // Prix médian de la zone de single prints (LVN extrême)
    float single_print_count;  // Nombre de niveaux de single prints dans la session
    float profile_hvn_dominant;// Prix du HVN dominant de la session (nœud le plus fort)

    // ─────────────────────────────────────────────────────────────────────────
    // DIAGNOSTICS (non-features ML — pour debug uniquement)
    // ─────────────────────────────────────────────────────────────────────────
    int     n_valid_fields;           // Nombre de champs valides (surveillance qualité)
    int     n_invalid_fields;         // Nombre de champs DMP_INVALID (données manquantes)
    bool    data_quality_ok;          // false si trop de données manquantes (>30%)

};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — HELPERS MATHÉMATIQUES INTERNES
// ═══════════════════════════════════════════════════════════════════════════════

// Distance signée en ticks : positif = niveau AU-DESSUS du prix
// Retourne DMP_INVALID si l'un des deux est invalide.
static inline float CalcDistTicks(float level, float price, float tick_size) {
    if (!DMP_IsValid(level) || !DMP_IsPriceValid(price) || tick_size <= 0.0f)
        return DMP_INVALID;
    return (level - price) / tick_size;
}

// Distance normalisée ATR, clampée à ±DMP_ATR_CLIP
static inline float CalcDistATR(float dist_ticks, float atr_ticks) {
    if (!DMP_IsValid(dist_ticks) || atr_ticks <= 0.0f)
        return DMP_INVALID;
    float v = dist_ticks / atr_ticks;
    // Clamp ±ATR_CLIP
    if (v >  DMP_ATR_CLIP) v =  DMP_ATR_CLIP;
    if (v < -DMP_ATR_CLIP) v = -DMP_ATR_CLIP;
    return v;
}

// Signe pur : -1.0 / 0.0 / +1.0
static inline float Sign(float v) {
    if (!DMP_IsValid(v)) return 0.0f;
    return (v > 0.0f) ? 1.0f : (v < 0.0f) ? -1.0f : 0.0f;
}

// Booléen sûr (retourne 0.0 si invalide)
static inline float SafeBool(float condition_val) {
    return (DMP_IsValid(condition_val) && condition_val > 0.0f) ? 1.0f : 0.0f;
}

// Position dans un range [low, high] → [0.0, 1.0], -1.0 si hors range
static inline float PosInRange(float price, float low, float high) {
    if (!DMP_IsPriceValid(price) || !DMP_IsPriceValid(low) || !DMP_IsPriceValid(high))
        return -1.0f;
    if (high <= low) return -1.0f;
    if (price < low || price > high) return -1.0f;
    return (price - low) / (high - low);
}

// Nearest niveau parmi un tableau : retourne distance ticks la plus petite au-dessus / en-dessous
static void NearestAboveBelow(
    const float* levels, int n_levels,
    float price, float tick_size,
    float& dist_above, float& dist_below)   // dist_above > 0, dist_below < 0
{
    dist_above =  DMP_INVALID;  // sentinel = pas trouvé
    dist_below =  DMP_INVALID;

    for (int i = 0; i < n_levels; i++) {
        if (!DMP_IsPriceValid(levels[i])) continue;
        float d = CalcDistTicks(levels[i], price, tick_size);
        if (!DMP_IsValid(d)) continue;
        if (d >= 0.0f) {
            if (dist_above == DMP_INVALID || d < dist_above) dist_above = d;
        } else {
            if (dist_below == DMP_INVALID || d > dist_below) dist_below = d;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — SOUS-FONCTIONS DE CALCUL PAR GROUPE
// ═══════════════════════════════════════════════════════════════════════════════

// ─────────────────────────────────────────────────────────────────────────────
// G1 — VWAP
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcVWAP(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts = r.tick_size;
    const float atr_ticks = r.atr_daily / ts;

    // Journalier
    float d_d = CalcDistTicks(r.vwap_day, r.price_close, ts);
    f.dist_vwap_d     = d_d;
    f.dist_vwap_d_atr = CalcDistATR(d_d, atr_ticks);
    f.dist_vwap_d_sd1u = CalcDistTicks(r.vwap_day_sd1u, r.price_close, ts);
    f.dist_vwap_d_sd1d = CalcDistTicks(r.vwap_day_sd1d, r.price_close, ts);
    f.dist_vwap_d_sd2u = CalcDistTicks(r.vwap_day_sd2u, r.price_close, ts);
    f.dist_vwap_d_sd2d = CalcDistTicks(r.vwap_day_sd2d, r.price_close, ts);
    f.vwap_d_side      = DMP_IsValid(d_d) ? Sign(-d_d) : 0.0f;  // -d = prix > VWAP si d<0

    // Weekly
    float d_w = CalcDistTicks(r.vwap_weekly, r.price_close, ts);
    f.dist_vwap_w     = d_w;
    f.dist_vwap_w_atr = CalcDistATR(d_w, atr_ticks);
    f.vwap_w_side     = DMP_IsValid(d_w) ? Sign(-d_w) : 0.0f;

    // Monthly
    float d_m = CalcDistTicks(r.vwap_monthly, r.price_close, ts);
    f.dist_vwap_m     = d_m;
    f.dist_vwap_m_atr = CalcDistATR(d_m, atr_ticks);
    f.vwap_m_side     = DMP_IsValid(d_m) ? Sign(-d_m) : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G2 — VOLUME PROFILE
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcVolumeProfile(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts        = r.tick_size;
    const float atr_ticks = r.atr_daily / ts;
    const float p         = r.price_close;

    // VP courant
    f.dist_cur_vpoc = CalcDistTicks(r.cur_vpoc, p, ts);
    f.dist_cur_vah  = CalcDistTicks(r.cur_vah,  p, ts);
    f.dist_cur_val  = CalcDistTicks(r.cur_val,  p, ts);

    // Position dans VA courante
    f.va_position_pct = PosInRange(p, r.cur_val, r.cur_vah);
    f.inside_cur_va   = (f.va_position_pct >= 0.0f) ? 1.0f : 0.0f;

    // VP précédente (J-1) — Très fort signal
    float d_pvpoc = CalcDistTicks(r.prev_vpoc, p, ts);
    f.dist_prev_vpoc      = d_pvpoc;
    f.dist_prev_vpoc_atr  = CalcDistATR(d_pvpoc, atr_ticks);
    f.dist_prev_vah       = CalcDistTicks(r.prev_vah, p, ts);
    f.dist_prev_val       = CalcDistTicks(r.prev_val, p, ts);
    f.dist_prev_vwap      = CalcDistTicks(r.prev_vwap, p, ts);
    f.dist_prev_vwap_sd1u = CalcDistTicks(r.prev_vwap_sd1u, p, ts);
    f.dist_prev_vwap_sd1d = CalcDistTicks(r.prev_vwap_sd1d, p, ts);

    // Dans la VA précédente ?
    float prev_va_pos = PosInRange(p, r.prev_val, r.prev_vah);
    f.inside_prev_va = (prev_va_pos >= 0.0f) ? 1.0f : 0.0f;

    // Open cash était-il dans la VA précédente ?
    float open_in = PosInRange(r.open_cash, r.prev_val, r.prev_vah);
    f.open_in_prev_va = (open_in >= 0.0f) ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G3 — MENTHORQ + VIX
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcMenthorQ(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts = r.tick_size;
    const float p  = r.price_close;

    // Niveaux principaux
    f.dist_mq_call      = CalcDistTicks(r.mq_call,      p, ts);
    f.dist_mq_put       = CalcDistTicks(r.mq_put,       p, ts);
    f.dist_mq_hvl       = CalcDistTicks(r.mq_hvl,       p, ts);
    f.dist_mq_call_0dte = CalcDistTicks(r.mq_call_0dte, p, ts);
    f.dist_mq_put_0dte  = CalcDistTicks(r.mq_put_0dte,  p, ts);

    // 1D Range MenthorQ — targets de range journalier (sg3=1d_min / sg4=1d_max)
    // Source snapshot : "1d_max":25945,"1d_min":25371 → dist_1d_max:1069 ticks
    f.dist_1d_min_ticks = CalcDistTicks(r.mq_1d_min, p, ts);  // négatif = sous le prix
    f.dist_1d_max_ticks = CalcDistTicks(r.mq_1d_max, p, ts);  // positif = au-dessus du prix

    // GEX : nearest above / below + cluster count
    float gex_above = DMP_INVALID, gex_below = DMP_INVALID;
    NearestAboveBelow(r.mq_gex, 10, p, ts, gex_above, gex_below);
    f.dist_gex_nearest_up = gex_above;
    f.dist_gex_nearest_dn = gex_below;

    // Compter GEX dans rayon de 30 ticks
    int gex_count = 0;
    const float radius = 30.0f;
    for (int i = 0; i < 10; i++) {
        if (!DMP_IsPriceValid(r.mq_gex[i])) continue;
        float d = std::fabs(r.mq_gex[i] - p) / ts;
        if (d <= radius) gex_count++;
    }
    f.gex_cluster_count = (float)gex_count;

    // Next Wall — mur Gamma le plus proche avec direction (comme l'ancien dumper)
    // On prend le nearest entre dist_gex_nearest_up et dist_gex_nearest_dn
    f.next_wall_dist_ticks = DMP_INVALID;
    f.next_wall_is_call    = 0.0f;
    if (DMP_IsValid(gex_above) && DMP_IsValid(gex_below)) {
        if (gex_above <= std::fabs(gex_below)) {
            f.next_wall_dist_ticks = gex_above;    // au-dessus = côté Call
            f.next_wall_is_call    = 1.0f;
        } else {
            f.next_wall_dist_ticks = std::fabs(gex_below);  // en-dessous = côté Put
            f.next_wall_is_call    = 0.0f;
        }
    } else if (DMP_IsValid(gex_above)) {
        f.next_wall_dist_ticks = gex_above;
        f.next_wall_is_call    = 1.0f;
    } else if (DMP_IsValid(gex_below)) {
        f.next_wall_dist_ticks = std::fabs(gex_below);
        f.next_wall_is_call    = 0.0f;
    }

    // Blind Spots : nearest above / below
    float blind_above = DMP_INVALID, blind_below = DMP_INVALID;
    NearestAboveBelow(r.mq_blind, 10, p, ts, blind_above, blind_below);
    f.dist_blind_nearest_up = blind_above;
    f.dist_blind_nearest_dn = blind_below;

    // VIX
    f.vix_level   = DMP_IsValid(r.vix_level) ? r.vix_level : 0.0f;
    f.dist_vix_hvl = (DMP_IsValid(r.vix_level) && DMP_IsValid(r.vix_hvl))
                      ? (r.vix_hvl - r.vix_level)   // en points VIX (pas ticks)
                      : DMP_INVALID;

    // Régime VIX
    if (DMP_IsValid(r.vix_level)) {
        if      (r.vix_level > 35.0f) f.vix_regime = 3.0f;
        else if (r.vix_level > 25.0f) f.vix_regime = 2.0f;
        else if (r.vix_level > 15.0f) f.vix_regime = 1.0f;
        else                           f.vix_regime = 0.0f;
    } else {
        f.vix_regime = 1.0f;  // fallback : régime normal
    }

    f.vix_above_hvl = (DMP_IsValid(r.vix_level) && DMP_IsValid(r.vix_hvl)
                       && r.vix_level > r.vix_hvl) ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G4 — SESSION & IB
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcSession(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts = r.tick_size;
    const float p  = r.price_close;

    // Initial Balance
    float ib_range = DMP_INVALID;
    if (DMP_IsPriceValid(r.ib_high) && DMP_IsPriceValid(r.ib_low)) {
        ib_range = (r.ib_high - r.ib_low) / ts;
    }

    f.dist_ib_high    = CalcDistTicks(r.ib_high, p, ts);
    f.dist_ib_low     = CalcDistTicks(r.ib_low,  p, ts);
    f.ib_range_ticks  = DMP_IsValid(ib_range) ? ib_range : 0.0f;

    float atr_ticks = r.atr_daily / ts;
    f.ib_range_atr = (DMP_IsValid(ib_range) && atr_ticks > 0.0f)
                     ? ib_range / atr_ticks : DMP_INVALID;

    f.ib_is_narrow = (DMP_IsValid(f.ib_range_atr) && f.ib_range_atr < DMP_IB_NARROW_RATIO) ? 1.0f : 0.0f;
    f.ib_is_wide   = (DMP_IsValid(f.ib_range_atr) && f.ib_range_atr > DMP_IB_WIDE_RATIO)   ? 1.0f : 0.0f;
    f.ib_complete  = r.ib_complete ? 1.0f : 0.0f;

    // Position dans IB (0=IB_Low, 1=IB_High)
    f.ib_position_pct = PosInRange(p, r.ib_low, r.ib_high);

    // IB Breakout
    f.ib_broken_up   = (DMP_IsPriceValid(r.ib_high) && p > r.ib_high) ? 1.0f : 0.0f;
    f.ib_broken_down = (DMP_IsPriceValid(r.ib_low)  && p < r.ib_low)  ? 1.0f : 0.0f;

    // Session extremes
    f.dist_sess_high   = CalcDistTicks(r.sess_high, p, ts);
    f.dist_sess_low    = CalcDistTicks(r.sess_low,  p, ts);

    float sess_range = DMP_INVALID;
    if (DMP_IsPriceValid(r.sess_high) && DMP_IsPriceValid(r.sess_low)) {
        sess_range = (r.sess_high - r.sess_low) / ts;
    }
    f.sess_range_ticks = DMP_IsValid(sess_range) ? sess_range : 0.0f;
    f.sess_range_atr   = (DMP_IsValid(sess_range) && atr_ticks > 0.0f)
                         ? sess_range / atr_ticks : DMP_INVALID;

    // Ouvertures & Overnight
    f.dist_open_cash = CalcDistTicks(r.open_cash, p, ts);
    f.dist_open_830  = CalcDistTicks(r.open_830,  p, ts);
    f.dist_ovn_high  = CalcDistTicks(r.ovn_high,  p, ts);
    f.dist_ovn_low   = CalcDistTicks(r.ovn_low,   p, ts);

    float ovn_range = DMP_INVALID;
    if (DMP_IsPriceValid(r.ovn_high) && DMP_IsPriceValid(r.ovn_low)) {
        ovn_range = (r.ovn_high - r.ovn_low) / ts;
    }
    f.ovn_range_ticks = DMP_IsValid(ovn_range) ? ovn_range : 0.0f;

    // Gap : Open 9h30 vs PVPOC
    f.open_gap_ticks = (DMP_IsPriceValid(r.open_cash) && DMP_IsPriceValid(r.prev_vpoc))
                       ? CalcDistTicks(r.prev_vpoc, r.open_cash, ts)
                       : DMP_INVALID;

    // Position open vs VA précédente (enum : -2/-1/0/+1/+2)
    if (!DMP_IsPriceValid(r.open_cash) || !DMP_IsPriceValid(r.prev_vah) || !DMP_IsPriceValid(r.prev_val)) {
        f.open_position = 0.0f;  // inconnu → in_va par défaut
    } else {
        float gap_above = (r.open_cash - r.prev_vah) / ts;  // >0 = au-dessus VAH
        float gap_below = (r.prev_val  - r.open_cash) / ts;  // >0 = en-dessous VAL
        if (gap_above > 20.0f)       f.open_position =  2.0f;  // Far above VAH
        else if (gap_above > 0.0f)   f.open_position =  1.0f;  // Above VAH
        else if (gap_below > 20.0f)  f.open_position = -2.0f;  // Far below VAL
        else if (gap_below > 0.0f)   f.open_position = -1.0f;  // Below VAL
        else                         f.open_position =  0.0f;  // In VA
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// G5 — COMPOSITE PROFILES
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcComposite(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts        = r.tick_size;
    const float atr_ticks = r.atr_daily / ts;
    const float p         = r.price_close;

    float d20 = CalcDistTicks(r.comp_20d_vpoc, p, ts);
    f.dist_comp_20d_vpoc     = d20;
    f.dist_comp_20d_vpoc_atr = CalcDistATR(d20, atr_ticks);
    f.dist_comp_20d_vah      = CalcDistTicks(r.comp_20d_vah, p, ts);
    f.dist_comp_20d_val      = CalcDistTicks(r.comp_20d_val, p, ts);

    float d50 = CalcDistTicks(r.comp_50d_vpoc, p, ts);
    f.dist_comp_50d_vpoc     = d50;
    f.dist_comp_50d_vpoc_atr = CalcDistATR(d50, atr_ticks);
    f.dist_comp_50d_vah      = CalcDistTicks(r.comp_50d_vah, p, ts);
    f.dist_comp_50d_val      = CalcDistTicks(r.comp_50d_val, p, ts);

    // Dans la VA composite ?
    f.inside_comp_20d_va = (PosInRange(p, r.comp_20d_val, r.comp_20d_vah) >= 0.0f) ? 1.0f : 0.0f;
    f.inside_comp_50d_va = (PosInRange(p, r.comp_50d_val, r.comp_50d_vah) >= 0.0f) ? 1.0f : 0.0f;

    // Confluence VPOC
    f.comp_vpoc_align_20_50 = (DMP_IsPriceValid(r.comp_20d_vpoc) && DMP_IsPriceValid(r.comp_50d_vpoc)
                               && std::fabs(r.comp_20d_vpoc - r.comp_50d_vpoc) / ts <= 20.0f) ? 1.0f : 0.0f;

    f.comp_vpoc_align_day_20 = (DMP_IsPriceValid(r.cur_vpoc) && DMP_IsPriceValid(r.comp_20d_vpoc)
                                && std::fabs(r.cur_vpoc - r.comp_20d_vpoc) / ts <= 15.0f) ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G6 — FPBS / ORDERFLOW
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcOrderFlow(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts = r.tick_size;
    const float p  = r.price_close;

    // Delta barre
    f.delta_bar = DMP_IsValid(r.fpbs_delta) ? r.fpbs_delta : 0.0f;

    // Normalisation delta : rapporté au volume total → [-1, +1]
    // Renommé delta_bar_vol_norm (corrigé Bug #8 — ce n'est pas une norm ATR)
    float vol_in_ticks = (DMP_IsValid(r.fpbs_volume) && r.fpbs_volume > 0.0f)
                         ? r.fpbs_volume : 1.0f;
    f.delta_bar_vol_norm = (DMP_IsValid(r.fpbs_delta))
                            ? std::fmax(-1.0f, std::fmin(1.0f, r.fpbs_delta / vol_in_ticks))
                            : 0.0f;

    // Delta journée
    f.delta_day     = DMP_IsValid(r.fpbs_delta_day) ? r.fpbs_delta_day : 0.0f;
    f.delta_day_dir = Sign(f.delta_day);

    // Pression Ask/Bid
    f.ask_pct = DMP_IsValid(r.fpbs_ask_pct) ? r.fpbs_ask_pct : 50.0f;
    f.bid_pct = DMP_IsValid(r.fpbs_bid_pct) ? r.fpbs_bid_pct : 50.0f;
    // Imbalance centré sur 0
    f.ask_bid_imbalance = (f.ask_pct - 50.0f) / 50.0f;  // [-1, +1]

    // Taille des trades
    f.avg_trade_size = DMP_IsValid(r.fpbs_avg_size)    ? r.fpbs_avg_size    : 0.0f;
    f.avg_bid_size   = DMP_IsValid(r.fpbs_avg_bid_size) ? r.fpbs_avg_bid_size : 0.0f;
    f.avg_ask_size   = DMP_IsValid(r.fpbs_avg_ask_size) ? r.fpbs_avg_ask_size : 0.0f;

    // Ratio institutionnel
    f.large_trader_ratio = (f.avg_bid_size > 0.0f)
                           ? std::fmin(5.0f, f.avg_ask_size / f.avg_bid_size)
                           : 1.0f;

    // Urgence
    f.vol_per_sec      = DMP_IsValid(r.fpbs_vol_per_sec)  ? r.fpbs_vol_per_sec  : 0.0f;
    f.bar_duration_sec = DMP_IsValid(r.fpbs_bar_duration) ? r.fpbs_bar_duration : 0.0f;
    f.finish_strength  = DMP_IsValid(r.fpbs_finish)       ? r.fpbs_finish       : 0.0f;

    // POC intra-barre
    f.poc_bar_dist = (DMP_IsPriceValid(r.fpbs_poc_price))
                     ? std::fabs(r.fpbs_poc_price - p) / ts
                     : DMP_INVALID;

    // CVD
    f.cvd_day     = DMP_IsValid(r.fpbs_cvd_day) ? r.fpbs_cvd_day : 0.0f;
    f.cvd_day_dir = Sign(f.cvd_day);

    // CVD OHLC range
    if (DMP_IsValid(r.cvd_ohlc_high) && DMP_IsValid(r.cvd_ohlc_low)) {
        f.cvd_ohlc_range = std::fabs(r.cvd_ohlc_high - r.cvd_ohlc_low);
    } else {
        f.cvd_ohlc_range = 0.0f;
    }

    // Rotation
    f.rotation_up    = SafeBool(r.rotation_up_signal);
    f.rotation_dn    = SafeBool(r.rotation_dn_signal);
    f.rotation_zz_osc = DMP_IsValid(r.rotation_zz_osc) ? r.rotation_zz_osc : 0.0f;

    // Divergence Delta
    if (r.delta_div_buy > 0.0f)       f.delta_divergence =  1.0f;
    else if (r.delta_div_sell > 0.0f) f.delta_divergence = -1.0f;
    else                               f.delta_divergence =  0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G7 — BATAILLE NAVALE
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcBatailleNavale(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float ts = r.tick_size;
    const float p  = r.price_close;

    f.bn_color_up    = SafeBool(r.bn_color_up);
    f.bn_color_dn    = SafeBool(r.bn_color_dn);
    f.bn_absorb_ask  = SafeBool(r.bn_absorb_ask);
    f.bn_absorb_bid  = SafeBool(r.bn_absorb_bid);
    f.bn_long_up     = SafeBool(r.bn_long_up);
    f.bn_long_dn     = SafeBool(r.bn_long_dn);

    // Double/Triple Ask=NQ, Double=ES — unifié dans bn_pressure_ask
    f.bn_pressure_ask = SafeBool(r.is_nq ? r.bn_triple_ask : r.bn_double_ask);
    f.bn_pressure_bid = SafeBool(r.is_nq ? r.bn_triple_bid : r.bn_double_bid);

    // Score BN composite [-1, +1]
    // Poids : Color=0.3 / Absorb=0.3 / LongBar=0.2 / Pressure=0.2
    float bull = f.bn_color_up  * 0.30f + f.bn_absorb_ask  * 0.30f
               + f.bn_long_up   * 0.20f + f.bn_pressure_ask * 0.20f;
    float bear = f.bn_color_dn  * 0.30f + f.bn_absorb_bid  * 0.30f
               + f.bn_long_dn   * 0.20f + f.bn_pressure_bid * 0.20f;

    f.bn_score_bull = std::fmin(1.0f, bull);
    f.bn_score_bear = std::fmin(1.0f, bear);
    f.bn_score_raw  = f.bn_score_bull - f.bn_score_bear;   // [-1, +1]

    // Big Orders : nearest above/below — direction conservée (corrigé Bug #9)
    // Précédent bug : on perdait la direction en prenant min(|above|, |below|)
    NearestAboveBelow(r.bn_ask100, 10, p, ts, f.dist_big_ask_nearest_up, f.dist_big_ask_nearest_dn);
    NearestAboveBelow(r.bn_bid100, 10, p, ts, f.dist_big_bid_nearest_up, f.dist_big_bid_nearest_dn);
}

// ─────────────────────────────────────────────────────────────────────────────
// G8 — SWING STRUCTURE
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcSwing(const DMP_RawData& r, DMP_MLFeatures& f,
                              float prev_swing_high, float prev_swing_low)
{
    const float ts = r.tick_size;
    const float p  = r.price_close;

    f.dist_swing_high = CalcDistTicks(r.swing_high, p, ts);
    f.dist_swing_low  = CalcDistTicks(r.swing_low,  p, ts);

    // Range Swing
    if (DMP_IsPriceValid(r.swing_high) && DMP_IsPriceValid(r.swing_low)) {
        f.swing_range_ticks = (r.swing_high - r.swing_low) / ts;
        // Position vs milieu swing
        float mid = (r.swing_high + r.swing_low) / 2.0f;
        f.price_vs_swing_mid = (p > mid) ? 1.0f : (p < mid) ? -1.0f : 0.0f;
    } else {
        f.swing_range_ticks  = 0.0f;
        f.price_vs_swing_mid = 0.0f;
    }

    // Nouveau Swing (comparaison avec barre précédente)
    f.new_swing_high = (DMP_IsPriceValid(r.swing_high) && DMP_IsPriceValid(prev_swing_high)
                        && r.swing_high > prev_swing_high) ? 1.0f : 0.0f;
    f.new_swing_low  = (DMP_IsPriceValid(r.swing_low)  && DMP_IsPriceValid(prev_swing_low)
                        && r.swing_low < prev_swing_low)   ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// G9 — CONTEXTE MARCHÉ (open_type / day_type sera dans DMP_OpenType.h)
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcContextMarket(const DMP_RawData& r, DMP_MLFeatures& f) {
    // Ces champs seront remplis par DMP_OpenType.h après 10h30 ET.
    // Ici on initialise les dérivés disponibles immédiatement.

    // Probabilité Trend Day (heuristique pré-10h30)
    float p_trend = 0.0f;
    if (DMP_IsValid(f.ib_range_atr)) {
        // IB large → journée normale (pas trend day) → P faible
        // IB étroite → potentiel breakout → P plus élevée
        if (f.ib_is_narrow > 0.5f)       p_trend += 0.30f;
        if (f.open_position != 0.0f)      p_trend += 0.20f;  // Open hors VA → OTF présents
        if (std::fabs(f.open_gap_ticks) > 15.0f && DMP_IsValid(f.open_gap_ticks))
                                          p_trend += 0.15f;  // Gap fort
        if (f.vix_regime >= 2.0f)         p_trend -= 0.10f;  // VIX élevé = contre-trend probable
        p_trend = std::fmax(0.0f, std::fmin(1.0f, p_trend));
    }
    f.trend_day_probability = p_trend;

    // VWAP Slope — lu depuis DMP_RawData (calculé dans DMP_ReadVWAPDay)
    f.vwap_slope_10     = DMP_IsValid(r.vwap_slope_10) ? r.vwap_slope_10 : 0.0f;
    f.vwap_slope_30     = DMP_IsValid(r.vwap_slope_30) ? r.vwap_slope_30 : 0.0f;
    f.vwap_slope_10_dir = Sign(f.vwap_slope_10);

    // MA Trend
    if (DMP_IsValid(r.ma_fast) && DMP_IsValid(r.ma_slow)) {
        f.ma_trend = (r.ma_fast > r.ma_slow) ? 1.0f : -1.0f;
    } else {
        f.ma_trend = 0.0f;
    }

    // VWAP + MA alignés ?
    f.vwap_ma_align = (DMP_IsValid(f.dist_vwap_d) && DMP_IsValid(r.ma_fast) && DMP_IsValid(r.ma_slow))
                      ? ((f.vwap_d_side > 0.0f && r.ma_fast > r.ma_slow)
                      || (f.vwap_d_side < 0.0f && r.ma_fast < r.ma_slow)) ? 1.0f : 0.0f
                      : 0.0f;

    // open_type / day_type / rule_80pct → défaut (sera mis à jour par DMP_OpenType.h)
    // Ne pas les écraser si déjà initialisés par DMP_OpenType
}

// ─────────────────────────────────────────────────────────────────────────────
// G10 — BOOLÉENS STRUCTURELS
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcBooleans(const DMP_RawData& r, DMP_MLFeatures& f) {
    const float p = r.price_close;

    f.bool_above_cur_vpoc  = (DMP_IsPriceValid(r.cur_vpoc)  && p > r.cur_vpoc)  ? 1.0f : 0.0f;
    f.bool_above_prev_vpoc = (DMP_IsPriceValid(r.prev_vpoc) && p > r.prev_vpoc) ? 1.0f : 0.0f;
    f.bool_above_vwap_d    = (DMP_IsPriceValid(r.vwap_day)  && p > r.vwap_day)  ? 1.0f : 0.0f;
    f.bool_above_vwap_w    = (DMP_IsPriceValid(r.vwap_weekly)  && p > r.vwap_weekly)  ? 1.0f : 0.0f;
    f.bool_above_vwap_m    = (DMP_IsPriceValid(r.vwap_monthly) && p > r.vwap_monthly) ? 1.0f : 0.0f;
    f.bool_above_mq_hvl    = (DMP_IsPriceValid(r.mq_hvl) && p > r.mq_hvl) ? 1.0f : 0.0f;
    f.bool_above_mq_call   = (DMP_IsPriceValid(r.mq_call) && p > r.mq_call) ? 1.0f : 0.0f;

    // Near level : distance < seuil de proximité
    const float prox = r.is_nq ? DMP_PROXIMITY_NQ : DMP_PROXIMITY_ES;
    float min_dist = 9999.0f;
    auto check = [&](float dist) {
        if (DMP_IsValid(dist) && std::fabs(dist) < min_dist)
            min_dist = std::fabs(dist);
    };
    check(f.dist_mq_call); check(f.dist_mq_put); check(f.dist_mq_hvl);
    check(f.dist_prev_vpoc); check(f.dist_prev_vah); check(f.dist_prev_val);
    check(f.dist_cur_vpoc);  check(f.dist_gex_nearest_up); check(f.dist_gex_nearest_dn);
    f.bool_near_level = (min_dist <= prox) ? 1.0f : 0.0f;

    // Dans IB ?
    f.bool_ib_inside = (DMP_IsPriceValid(r.ib_high) && DMP_IsPriceValid(r.ib_low)
                        && p <= r.ib_high && p >= r.ib_low) ? 1.0f : 0.0f;

    // Early session : avant 10h00 ET (heure = dans r.is_rth_session / r.ib_complete)
    f.bool_session_early = (!r.ib_complete) ? 1.0f : 0.0f;

    // Triple VWAP alignment — signal trivalent (corrigé Bug #10 : n'est pas un bool)
    f.vwap_triple_align = (f.bool_above_vwap_d > 0.5f
                                  && f.bool_above_vwap_w > 0.5f
                                  && f.bool_above_vwap_m > 0.5f) ? 1.0f
                                 : (f.bool_above_vwap_d < 0.5f
                                  && f.bool_above_vwap_w < 0.5f
                                  && f.bool_above_vwap_m < 0.5f) ? -1.0f : 0.0f;

    // VA confluence : VPOC courant proche de PVPOC
    f.bool_va_confluence = (DMP_IsPriceValid(r.cur_vpoc) && DMP_IsPriceValid(r.prev_vpoc)
                            && std::fabs(r.cur_vpoc - r.prev_vpoc) / r.tick_size <= 10.0f) ? 1.0f : 0.0f;

    // GEX Flip Zone : prix entre mq_put et mq_call
    f.bool_gex_flip_zone = (DMP_IsPriceValid(r.mq_put) && DMP_IsPriceValid(r.mq_call)
                            && p >= r.mq_put && p <= r.mq_call) ? 1.0f : 0.0f;
}

// ─────────────────────────────────────────────────────────────────────────────
// Comptage qualité données
// ─────────────────────────────────────────────────────────────────────────────

static inline void CalcDataQuality(DMP_MLFeatures& f) {
    // Vérification des champs FLOAT les plus critiques
    const float* checks[] = {
        &f.dist_vwap_d, &f.dist_vwap_w, &f.dist_vwap_m,
        &f.dist_prev_vpoc, &f.dist_cur_vpoc,
        &f.dist_mq_call, &f.dist_mq_put, &f.dist_mq_hvl,
        &f.dist_ib_high, &f.dist_ib_low,
        &f.vix_level,
        &f.dist_comp_20d_vpoc, &f.dist_comp_50d_vpoc,
        &f.dist_swing_high, &f.dist_swing_low
    };
    const int n = (int)(sizeof(checks) / sizeof(checks[0]));

    int valid = 0, invalid = 0;
    for (int i = 0; i < n; i++) {
        if (DMP_IsValid(*checks[i])) valid++;
        else invalid++;
    }
    f.n_valid_fields   = valid;
    f.n_invalid_fields = invalid;
    f.data_quality_ok  = (invalid <= n / 3);  // OK si <33% invalides
}

// ─────────────────────────────────────────────────────────────────────────
// G11 — HVN/LVN SESSION
// ─────────────────────────────────────────────────────────────────────────

static inline void CalcHVN_LVN(const DMP_HVN_LVN_Result& h, DMP_MLFeatures& f,
                                float tp_target = DMP_INVALID, int direction = 0,
                                float tick_size = 0.25f)
{
    // Distances nearest — distances absolues (toujours positives) pour le ML
    // Le côté (above/below) est implicite dans le nom du champ
    if (h.valid && DMP_IsValid(h.nearest_hvn_above))
        f.dist_session_hvn_above = h.dist_hvn_above_ticks;
    else
        f.dist_session_hvn_above = DMP_INVALID;

    if (h.valid && DMP_IsValid(h.nearest_hvn_below))
        f.dist_session_hvn_below = h.dist_hvn_below_ticks;
    else
        f.dist_session_hvn_below = DMP_INVALID;

    if (h.valid && DMP_IsValid(h.nearest_lvn_above))
        f.dist_session_lvn_above = h.dist_lvn_above_ticks;
    else
        f.dist_session_lvn_above = DMP_INVALID;

    if (h.valid && DMP_IsValid(h.nearest_lvn_below))
        f.dist_session_lvn_below = h.dist_lvn_below_ticks;
    else
        f.dist_session_lvn_below = DMP_INVALID;

    // Compteurs globaux ±100 ticks
    f.session_hvn_count    = h.valid ? (float)h.session_hvn_count : 0.0f;
    f.session_lvn_count    = h.valid ? (float)h.session_lvn_count : 0.0f;
    f.lvn_confluence_count = h.valid ? (float)h.lvn_confluence_count : 0.0f;

    // LVN/HVN between : calculé seulement si TP target connu
    if (h.valid && DMP_IsPriceValid(tp_target) && (direction == 1 || direction == -1)) {
        float lvn_bet = 0.0f, hvn_bet = 0.0f;
        DMP_HasLVN_Between(h, f.price, tp_target, direction, tick_size, lvn_bet, hvn_bet);
        f.lvn_between = lvn_bet;
        f.hvn_between = hvn_bet;
    } else {
        f.lvn_between = 0.0f;  // Pas de trade actif / données insuffisantes
        f.hvn_between = 0.0f;
    }
}


// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — FONCTION MAÎTRE : DMP_Transform()
// ═══════════════════════════════════════════════════════════════════════════════
// Convertit un DMP_RawData complet en DMP_MLFeatures.
//
// prev_swing_high / prev_swing_low : valeurs de la barre précédente pour
//   détecter les nouveaux pivots (stocker dans sc.GetPersistentFloat).
//
// hvn_lvn : résultat HVN/LVN calculé par DMP_ComputeHVN_LVN() dans DMP_Main.cpp
//   Passé avec pointeur optionnel — si nullptr, le G11 est initialisé à 0/INVALID.
//
// tp_target / direction : pour calculer lvn_between / hvn_between.
//   tp_target = prix cible du trade en cours (ou DMP_INVALID si pas de trade).
//   direction = +1 (LONG) / -1 (SHORT) / 0 (pas de trade).

inline void DMP_Transform(
    const DMP_RawData&         r,
    DMP_MLFeatures&            f,
    float                      prev_swing_high = DMP_INVALID,
    float                      prev_swing_low  = DMP_INVALID,
    const DMP_HVN_LVN_Result*  hvn_lvn         = nullptr,
    float                      tp_target       = DMP_INVALID,
    int                        direction        = 0)
{
    // ── 0. Init méta ─────────────────────────────────────────────────────────
    f.ts     = r.timestamp_ms;
    f.sym[0] = r.is_nq ? 'N' : 'E';
    f.sym[1] = r.is_nq ? 'Q' : 'S';
    f.sym[2] = '\0';
    f.price  = r.price_close;
    f.atr    = r.atr_daily;

    // Valeurs par défaut pour les champs remplis par DMP_OpenType.h
    f.open_type      = 0.0f;   // UNKNOWN — sera mis à jour par DMP_OpenType.h
    f.open_zone      = 4.0f;   // AT_POC = neutre par défaut
    f.open_bias_conf = 0.0f;   // Pas de confiance tant que UNKNOWN
    f.open_direction = 0.0f;   // Neutre tant que UNKNOWN
    f.day_type       = 2.0f;    // NormVar = le type le plus fréquent (42%)
    f.rule_80pct     = 0.0f;

    // Valeurs par défaut G12 — remplis par PS_AnalyzeCurrentSession() dans DMP_Main.cpp
    f.profile_shape        = 0.0f;   // D-shape = équilibre par défaut
    f.profile_skew         = 0.0f;   // Neutre
    f.poc_position         = 0.5f;   // Milieu range
    f.volume_imbalance     = 1.0f;   // Équilibré
    f.is_double_dist       = 0.0f;   // Pas de double distribution
    f.poc_separation_ticks = 0.0f;   // N/A
    f.single_print_mid     = 0.0f;   // N/A
    f.single_print_count   = 0.0f;   // Zéro
    f.profile_hvn_dominant = DMP_INVALID; // Pas encore calculé

    // ── 1. Groupes de calcul (ordre : VWAP → VP → MQ → Session → ...) ──────
    CalcVWAP(r, f);              // G1  — doit précéder CalcBooleans
    CalcVolumeProfile(r, f);     // G2
    CalcMenthorQ(r, f);          // G3
    CalcSession(r, f);           // G4
    CalcComposite(r, f);         // G5
    CalcOrderFlow(r, f);         // G6
    CalcBatailleNavale(r, f);    // G7
    CalcSwing(r, f, prev_swing_high, prev_swing_low);  // G8
    CalcContextMarket(r, f);     // G9
    CalcBooleans(r, f);          // G10 — doit être avant G11

    // G11 — HVN/LVN session (Section C)
    if (hvn_lvn) {
        CalcHVN_LVN(*hvn_lvn, f, tp_target, direction, r.tick_size);
    } else {
        // Pas de données HVN/LVN disponibles : INVALID pour les distances, 0 pour les compteurs
        f.dist_session_hvn_above = DMP_INVALID;
        f.dist_session_hvn_below = DMP_INVALID;
        f.dist_session_lvn_above = DMP_INVALID;
        f.dist_session_lvn_below = DMP_INVALID;
        f.session_hvn_count      = 0.0f;
        f.session_lvn_count      = 0.0f;
        f.lvn_between            = 0.0f;
        f.hvn_between            = 0.0f;
        f.lvn_confluence_count   = 0.0f;
    }

    // ── 2. Qualité données ───────────────────────────────────────────────────
    CalcDataQuality(f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — UTILITAIRE : NOMS DES CHAMPS (pour CSV header Python)
// ═══════════════════════════════════════════════════════════════════════════════

// Écriture du header CSV dans un fichier (à appeler UNE seule fois)
inline void DMP_WriteCSVHeader(std::ofstream& file) {
    file <<
        // Méta
        "ts,sym,price,atr,"
        // G1 VWAP (13 → +2 slopes = 15)
        "dist_vwap_d,dist_vwap_d_atr,dist_vwap_d_sd1u,dist_vwap_d_sd1d,"
        "dist_vwap_d_sd2u,dist_vwap_d_sd2d,dist_vwap_w,dist_vwap_w_atr,"
        "dist_vwap_m,dist_vwap_m_atr,vwap_d_side,vwap_w_side,vwap_m_side,"
        // G2 VP (14)
        "dist_cur_vpoc,dist_cur_vah,dist_cur_val,va_position_pct,inside_cur_va,"
        "dist_prev_vpoc,dist_prev_vpoc_atr,dist_prev_vah,dist_prev_val,"
        "dist_prev_vwap,dist_prev_vwap_sd1u,dist_prev_vwap_sd1d,"
        "inside_prev_va,open_in_prev_va,"
        // G3 MQ (14 + 2 daily range + 2 next_wall = 18)
        "dist_mq_call,dist_mq_put,dist_mq_hvl,dist_mq_call_0dte,dist_mq_put_0dte,"
        "dist_1d_min_ticks,dist_1d_max_ticks,"
        "dist_gex_nearest_up,dist_gex_nearest_dn,gex_cluster_count,"
        "next_wall_dist_ticks,next_wall_is_call,"
        "dist_blind_nearest_up,dist_blind_nearest_dn,"
        "vix_level,dist_vix_hvl,vix_regime,vix_above_hvl,"
        // G4 Session (21)
        "dist_ib_high,dist_ib_low,ib_range_ticks,ib_range_atr,ib_is_narrow,ib_is_wide,"
        "ib_position_pct,ib_broken_up,ib_broken_down,ib_complete,"
        "dist_sess_high,dist_sess_low,sess_range_ticks,sess_range_atr,"
        "dist_open_cash,dist_open_830,dist_ovn_high,dist_ovn_low,"
        "ovn_range_ticks,open_gap_ticks,open_position,"
        // G5 Composite (12)
        "dist_comp_20d_vpoc,dist_comp_20d_vpoc_atr,dist_comp_20d_vah,dist_comp_20d_val,"
        "dist_comp_50d_vpoc,dist_comp_50d_vpoc_atr,dist_comp_50d_vah,dist_comp_50d_val,"
        "inside_comp_20d_va,inside_comp_50d_va,comp_vpoc_align_20_50,comp_vpoc_align_day_20,"
        // G6 OrderFlow (22 — renommé delta_bar_vol_norm)
        "delta_bar,delta_bar_vol_norm,delta_day,delta_day_dir,"
        "ask_pct,bid_pct,ask_bid_imbalance,avg_trade_size,avg_bid_size,avg_ask_size,"
        "large_trader_ratio,vol_per_sec,bar_duration_sec,finish_strength,poc_bar_dist,"
        "cvd_day,cvd_day_dir,cvd_ohlc_range,"
        "rotation_up,rotation_dn,rotation_zz_osc,delta_divergence,"
        // G7 BN (11 + 4 directionnels = 15, corrigé Bug #9)
        "bn_color_up,bn_color_dn,bn_absorb_ask,bn_absorb_bid,"
        "bn_long_up,bn_long_dn,bn_pressure_ask,bn_pressure_bid,"
        "bn_score_raw,bn_score_bull,bn_score_bear,"
        "dist_big_ask_nearest_up,dist_big_ask_nearest_dn,"
        "dist_big_bid_nearest_up,dist_big_bid_nearest_dn,"
        // G8 Swing (6)
        "dist_swing_high,dist_swing_low,swing_range_ticks,"
        "price_vs_swing_mid,new_swing_high,new_swing_low,"
        // G9 Contexte (6 + 3 slopes = 9, corrigé + ajout)
        "open_type,open_zone,open_bias_conf,open_direction,day_type,rule_80pct,trend_day_probability,ma_trend,vwap_ma_align,"
        "vwap_slope_10,vwap_slope_30,vwap_slope_10_dir,"
        // G10 Booléens (12 + vwap_triple_align renommé = 13)
        "bool_above_cur_vpoc,bool_above_prev_vpoc,bool_above_vwap_d,"
        "bool_above_vwap_w,bool_above_vwap_m,bool_above_mq_hvl,bool_above_mq_call,"
        "bool_near_level,bool_ib_inside,bool_session_early,"
        "vwap_triple_align,bool_va_confluence,bool_gex_flip_zone,"
        // G11 HVN/LVN Session (9 champs — Section C)
        "dist_session_hvn_above,dist_session_hvn_below,"
        "dist_session_lvn_above,dist_session_lvn_below,"
        "session_hvn_count,session_lvn_count,"
        "lvn_between,hvn_between,lvn_confluence_count,"
        // G12 Profile Shape (9 champs)
        "profile_shape,profile_skew,poc_position,volume_imbalance,"
        "is_double_dist,poc_separation_ticks,"
        "single_print_mid,single_print_count,profile_hvn_dominant"
        "\n";
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Transform.h
// ═══════════════════════════════════════════════════════════════════════════════
