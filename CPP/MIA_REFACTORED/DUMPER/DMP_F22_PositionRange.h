#pragma once
// =============================================================================
// DMP_F22_PositionRange.h  —  Batch B3 (F22) : Position dans les ranges
// =============================================================================
//
//  Role : Exposer 3 features qui mesurent la position du close dans
//         differents ranges (session, MQ daily). Distinctes du
//         `range_pos_va` C++ existant (ex-`range_pos` renomme B4 Phase 0
//         2026-06-08 pour fix collision Python) qui mesure la position dans la Value
//         Area courante (3 metriques semantiquement differentes).
//
//  Cas d'usage downstream :
//    * pct_in_range / premium_zone : detecter si le marche est en haut ou
//      en bas de la session courante (mean reversion vs continuation).
//    * position_in_range : detecter si on touche bientot les extremes
//      MQ daily (1d_max ou 1d_min calcule par MenthorQ via gamma profile).
//
//  Audit B3 2026-06-07 : 3 features GO PORT initialement, mais Jackson a
//  rectifie (2026-06-07 22:50) : on garde aussi `discount_zone` malgre la
//  redondance arithmetique stricte avec premium_zone (corr -0.989). Raison :
//  mode FULL REGLES (pas ML), convention trading "Buy the dip" =
//  `if discount_zone == 1 then BUY`. Lisibilite code regles + dashboard 2
//  labels distincts > cout marginal (1 ligne, 4 octets, 1 KV2 field).
//  Total F22 = 4 features. Cf DOCS/AUDIT_B3_F8_F9_F12_F22.md section F22.
//
//  Sources C++ deja disponibles :
//    * `r.price_close` : close de la bar courante (BaseData OHLC)
//    * `r.sess_high` / `r.sess_low` : RTH session high/low (Sierra
//      HH_SESSION/LL_SESSION) - lus par DMP_ReadSession
//    * `r.mq_1d_min` / `r.mq_1d_max` : daily range MQ (sg3/sg4 de
//      MQ_GAMMA) - lus par DMP_ReadMenthorQ
//
//  Pendant Python : CORE/sessions_swings_simple_streaming.py:332-339 +
//                   CORE/enricher_chain.py:1373-1381
//
//  Convention valeurs :
//    * pct_in_range      : [0, 100] (clamp), DMP_INVALID si range degenere
//    * premium_zone      : 0 ou 1 (event boolean), DMP_INVALID si parent null
//    * position_in_range : [0, 1] (clamp), DMP_INVALID si range degenere
//
//  Edge cases :
//    * sess_high == sess_low (premier tick session, range = 0) -> INVALID
//    * mq_1d_max == mq_1d_min (cas extreme MQ degenere) -> INVALID
//    * Niveau invalide en amont (DMP_INVALID) -> INVALID propage
//
//  ATTENTION : `position_in_range` est tagge HIGH_CORR_INSTRUMENT par
//  audit 28/04 (ks=1.044) car les inputs MQ daily sont instrument-specific
//  par design. Flagger NATURALLY_DIFFERENT cote quality_validator.py
//  (input MQ legitime, pas un leak).
//
//  Date    : 2026-06-07
//  Build   : Batch B3 / Schema 3.7.20
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>             // std::isfinite

// =============================================================================
// SECTION 1 — HELPERS FILTRES
// =============================================================================

// Helper local : test "DMP_INVALID-like" sur un float. Duplique la logique
// de DMP_WR_IsInvalid (defini dans DMP_Writer.h, inclu APRES Transform.h donc
// indisponible ici). Suffix `_local` pour eviter conflit ODR si reinclus.
static inline bool DMP_F22_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f) || !std::isfinite(v);
}

// Filtre pourcentage [0, 100] : clamp aux bornes, INVALID si denominateur 0.
// Logique : pos_pct = (close - low) / (high - low) * 100, sans negatif/>100.
static inline float DMP_F22_PctInRange(float close, float low, float high) {
    if (!DMP_IsPriceValid(close) || !DMP_IsPriceValid(low) || !DMP_IsPriceValid(high))
        return DMP_INVALID;
    float range = high - low;
    // Range degenere (premier tick session) ou aberrant (high < low) -> INVALID.
    // Garde 0.01 point (= 4 ticks ES/NQ) : evite division par valeurs < tick.
    if (range < 0.01f) return DMP_INVALID;
    float pct = (close - low) / range * 100.0f;
    if (pct <   0.0f) pct =   0.0f;
    if (pct > 100.0f) pct = 100.0f;
    return pct;
}

// Filtre position [0, 1] : meme logique que PctInRange mais sans x100.
// Convention 0=tout en bas, 1=tout en haut du range MQ daily.
static inline float DMP_F22_PositionInRange(float close, float low, float high) {
    if (!DMP_IsPriceValid(close) || !DMP_IsPriceValid(low) || !DMP_IsPriceValid(high))
        return DMP_INVALID;
    float range = high - low;
    if (range < 0.01f) return DMP_INVALID;
    float pos = (close - low) / range;
    if (pos < 0.0f) pos = 0.0f;
    if (pos > 1.0f) pos = 1.0f;
    return pos;
}

// =============================================================================
// SECTION 2 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 3 champs F22 dans DMP_MLFeatures depuis r.price_close +
// r.sess_high/low + r.mq_1d_min/max.
//
// A appeler APRES DMP_ReadAll() (sess_high/low et mq_1d_* doivent etre
// remplis). Pas de dependance vs les CalcXXX du Transform (lecture brute).

inline void DMP_ComputeF22_PositionRange(DMP_MLFeatures& f, const DMP_RawData& r) {
    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 1 — pct_in_range : position du close dans le range session [0, 100]
    // Source : (close - sess_low) / (sess_high - sess_low) * 100
    // INVALID si premier tick session (sess_high == sess_low) ou nulls amont.
    // ─────────────────────────────────────────────────────────────────────────
    f.pct_in_range = DMP_F22_PctInRange(r.price_close, r.sess_low, r.sess_high);

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 2 — premium_zone : 1 si pct_in_range > 50, 0 sinon (boolean)
    // Convention : "premium" = au-dessus du milieu de la session courante
    // (interprete comme zone vendeurs / mean reversion bearish probable).
    // INVALID si parent pct_in_range invalide.
    // ─────────────────────────────────────────────────────────────────────────
    if (DMP_F22_IsInvalid(f.pct_in_range)) {
        f.premium_zone = DMP_INVALID;
    } else {
        f.premium_zone = (f.pct_in_range > 50.0f) ? 1.0f : 0.0f;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 3 — discount_zone : 1 si pct_in_range < 50, 0 sinon (boolean)
    // Convention "Buy the dip" : `if discount_zone == 1 then BUY` plus lisible
    // que `if premium_zone == 0 then BUY` en mode FULL REGLES. Dashboard 2
    // labels distincts (premium / discount) = standard trader. Strict mirror
    // de premium_zone : discount = 1 - premium quand parent valide.
    // INVALID si parent pct_in_range invalide.
    // ─────────────────────────────────────────────────────────────────────────
    if (DMP_F22_IsInvalid(f.pct_in_range)) {
        f.discount_zone = DMP_INVALID;
    } else {
        f.discount_zone = (f.pct_in_range < 50.0f) ? 1.0f : 0.0f;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 4 — position_in_range : position dans le range MQ daily [0, 1]
    // Source : (close - mq_1d_min) / (mq_1d_max - mq_1d_min)
    // Utilise par Bot 3 (test_211 dans bot3_decision_engine.py).
    //
    // HIGH_CORR_INSTRUMENT (audit 28/04 ks=1.044) : OK par design (inputs MQ
    // instrument-specific). Flagger NATURALLY_DIFFERENT cote quality_validator.
    // INVALID si premier tick session (mq_1d_max == mq_1d_min) ou nulls amont.
    // ─────────────────────────────────────────────────────────────────────────
    f.position_in_range = DMP_F22_PositionInRange(r.price_close, r.mq_1d_min, r.mq_1d_max);
}

// =============================================================================
// FIN DMP_F22_PositionRange.h
// =============================================================================
