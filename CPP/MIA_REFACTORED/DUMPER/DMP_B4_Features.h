#pragma once
// =============================================================================
// DMP_B4_Features.h  —  Batch B4 : Features Python supplementaires (7 total)
// =============================================================================
//
//  Role : Porter 7 features Python live_enriched additionnelles dans le JSONL
//         C++ Sierra DMP. Phase 1 = 5 triviaux + Phase 2 = 2 easy.
//
//  Decisions Jackson 2026-06-08 :
//    - Phase 1 (5 trivial) : mins_et, is_in_us_cash, dist_pdh_pct, dist_pdl_pct,
//      atr_14m_pct. Formules triviales (1 ligne chacune), sources C++ deja
//      disponibles (B2/B3.A).
//    - Phase 2 (2 easy) : cvd_session (RTH-filter cvd_day), ctx_day_type_intensity
//      (formule SAINE ib_broken_up/dn * |dist_vwap_d_atr|, PAS day_type pollue
//      par incident #39 06/06).
//    - DROP : delta_persistence_20, big_spawn_rate_20 (rejetes walk-forward
//      A3 raffinement : rho=0.144 noise, V3 non concluant ; V4_with_cvd
//      rho=0.199 BAT).
//    - DEFER : ctx_trend_day_score (depend ctx_vol_slope_5 absent).
//    - SEPARE : A3_v4_with_cvd_session = STRATEGIE de scoring, code Python live +
//      dashboard widget (PAS C++ DMP).
//
//  Sources C++ deja disponibles :
//    * r.mins_et         : DMP_Reader.h:706 (deja calcule, mais pas expose B3.A)
//    * r.session         : 0=Asia, 1=London, 2=US (DMP_Reader.h)
//    * r.atr_14m         : ATR 14min en TICKS (DMP_Reader.h)
//    * r.tick_size       : 0.25 ES/NQ, 0.10 MGC (DMP_Reader.h)
//    * r.price_close     : close de la bar courante
//    * f.pdh / f.pdl     : Previous Day High/Low POINTS (B2 absolus)
//    * r.cvd_day         : cumul delta session 00:00 (CME 24h, alias cvd_day_dir)
//    * r.ib_broken_up    : boolean IB broken upside (DMP_Reader.h)
//    * r.ib_broken_dn    : boolean IB broken downside
//    * r.dist_vwap_d_atr : distance close-VWAP normalisee ATR (B1/B2)
//
//  Audit B4 (DOCS/AUDIT_B4_10_FEATURES.md 2026-06-08) :
//    Verdict : 5 GO trivial + 2 GO-easy + 2 DROP + 2 DEFER + 1 SEPARE.
//    Pas de leak documente. ctx_day_type_intensity formule saine confirmee
//    streaming (rolling_features_streaming.py:719-734).
//
//  Convention valeurs :
//    * mins_et          : scalar [0, 1440), DMP_INVALID si calcul timezone echoue
//    * is_in_us_cash    : boolean 0 ou 1 (DMP_INVALID si session/mins_et invalid)
//    * dist_pdh_pct     : signed pct (pdh - close) / close * 100, DMP_INVALID si pdh invalid
//    * dist_pdl_pct     : signed pct (pdl - close) / close * 100, DMP_INVALID si pdl invalid
//    * atr_14m_pct      : pct positif (atr_14m_points / close * 100), DMP_INVALID si invalid
//    * cvd_session      : RTH-filter cvd_day (reset 09:30 ET), float, DMP_INVALID hors RTH
//    * ctx_day_type_intensity : signed [-1, +1], formule dir * mag clip
//
//  Date    : 2026-06-08
//  Build   : Batch B4 / Schema 3.7.21
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>             // std::isfinite, std::fabs

// =============================================================================
// SECTION 1 — CONSTANTES B4
// =============================================================================

// PersistVars indices B4 (libres : 211 et au-dela, 200-210 deja utilises B2/B3.A)
constexpr int DMP_PERSIST_B4_CVD_SESSION_BASE = 211;  // cvd_day a l'open RTH (09:30 ET)
constexpr int DMP_PERSIST_B4_CVD_SESSION_DATE = 212;  // trading_day du snapshot

// Heures RTH cash session (deja en DMP_Config.h : DMP_RTH_START = 570, DMP_RTH_END = 960)
// On reutilise ces constantes pour eviter duplication.

// =============================================================================
// SECTION 2 — HELPERS
// =============================================================================

// Helper "INVALID-like" local pour float
static inline bool DMP_B4_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f) || !std::isfinite(v);
}

// Helper : pct signed depuis level absolu et close
//   = (level - close) / close * 100
// Retourne DMP_INVALID si level/close invalid ou close <= 0.
static inline float DMP_B4_CalcDistPct(float level, float close) {
    if (DMP_B4_IsInvalid(level) || DMP_B4_IsInvalid(close) || close <= 0.0f) {
        return DMP_INVALID;
    }
    return (level - close) / close * 100.0f;
}

// =============================================================================
// SECTION 3 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 7 features B4 dans DMP_MLFeatures depuis r.* + f.* deja remplis
// par les helpers B1/B2/B3.A en amont.
//
// `sc` requis pour cvd_session (PersistVars 211-212).
// Doit etre appelee APRES DMP_ReadAll() + DMP_ComputeF2_PrevLevels (besoin
// de f.pdh / f.pdl).

inline void DMP_ComputeB4_Features(
    SCStudyInterfaceRef sc,
    DMP_MLFeatures& f,
    const DMP_RawData& r)
{
    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 1 — 5 features triviales
    // ─────────────────────────────────────────────────────────────────────────

    // FEATURE 1 — mins_et : minutes depuis minuit ET, DST-aware
    //   Deja calcule en C++ (r.mins_et). Sentinelle si calcul timezone a foire.
    if (r.mins_et < 0 || r.mins_et >= 1440) {
        f.mins_et = DMP_INVALID;
    } else {
        f.mins_et = (float)r.mins_et;
    }

    // FEATURE 2 — is_in_us_cash : boolean 1 si session=US ET mins_et in [RTH_START, RTH_END)
    //   RTH cash = 09:30-16:00 ET = mins_et [570, 960).
    //   Equivalent Python : (session_id == "US") AND (570 <= mins_et < 960).
    if (DMP_B4_IsInvalid(f.mins_et)) {
        f.is_in_us_cash = DMP_INVALID;
    } else {
        // r.session : 0=Asia, 1=London, 2=US
        bool in_rth = (r.session == 2)
                   && (r.mins_et >= DMP_RTH_START)
                   && (r.mins_et <  DMP_RTH_END);
        f.is_in_us_cash = in_rth ? 1.0f : 0.0f;
    }

    // FEATURE 3 — dist_pdh_pct : (pdh - close) / close * 100, signed
    //   pdh deja en C++ B2 (DMP_F2_PrevLevels.h, snapshot session J-1).
    //   DMP_INVALID si pdh pas encore connu (1ere session backfill).
    f.dist_pdh_pct = DMP_B4_CalcDistPct(f.pdh, r.price_close);

    // FEATURE 4 — dist_pdl_pct : (pdl - close) / close * 100, signed
    f.dist_pdl_pct = DMP_B4_CalcDistPct(f.pdl, r.price_close);

    // FEATURE 5 — atr_14m_pct : atr_14m_points / close * 100, positif
    //   atr_14m est en TICKS, on multiplie par tick_size pour avoir POINTS.
    //   Equivalent Python : atr_14m * tick / close * 100.
    if (DMP_B4_IsInvalid(r.atr_14m) || DMP_B4_IsInvalid(r.price_close)
        || r.price_close <= 0.0f || r.tick_size <= 0.0f) {
        f.atr_14m_pct = DMP_INVALID;
    } else {
        float atr_points = r.atr_14m * r.tick_size;
        f.atr_14m_pct = (atr_points / r.price_close) * 100.0f;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // PHASE 2 — 2 features easy
    // ─────────────────────────────────────────────────────────────────────────

    // FEATURE 6 — cvd_session : RTH-filter cvd_day
    //   Snapshot cvd_day a l'open RTH (09:30 ET), puis cvd_session = cvd_day - snapshot.
    //   Hors RTH (mins_et < 570 ou >= 960) ou session != US : DMP_INVALID.
    //   PersistVars 211 (snapshot value) + 212 (trading_day du snapshot).
    int& cvd_snapshot = sc.GetPersistentInt(DMP_PERSIST_B4_CVD_SESSION_BASE);
    int& cvd_snap_date = sc.GetPersistentInt(DMP_PERSIST_B4_CVD_SESSION_DATE);

    // Reset Full Recalc
    if (sc.IsFullRecalculation && sc.Index == 0) {
        cvd_snapshot = 0;
        cvd_snap_date = 0;
    }

    bool in_cash_session = (r.session == 2)
                        && (r.mins_et >= DMP_RTH_START)
                        && (r.mins_et < DMP_RTH_END);

    // Fix compile B4 (2026-06-08) : cvd_day est dans struct DMP_MLFeatures (f)
    // pas DMP_RawData (r). Idem ib_broken_up/down (cf feature 7 plus bas).
    // L'ordre des helpers dans DMP_Transform garantit que f.cvd_day est rempli
    // avant l'appel de DMP_ComputeB4_Features.
    if (!in_cash_session
        || DMP_B4_IsInvalid(f.cvd_day)
        || r.trading_day <= 0) {
        f.cvd_session = DMP_INVALID;
    } else {
        // Premiere bar RTH du trading_day : snapshot cvd_day actuel
        if (cvd_snap_date != r.trading_day) {
            cvd_snapshot = (int)f.cvd_day;
            cvd_snap_date = r.trading_day;
        }
        f.cvd_session = f.cvd_day - (float)cvd_snapshot;
    }

    // FEATURE 7 — ctx_day_type_intensity : signed [-1, +1]
    //   Formule Python (rolling_features_streaming.py:719-734) :
    //     dir = +1 si ib_broken_up only, -1 si ib_broken_dn only, 0 sinon
    //     mag = |dist_vwap_d_atr|
    //     intensity = (dir * mag).clip(-1, +1)
    //
    //   ⚠️ ANTI-PATTERN 11 : formule SAINE confirmee audit B4 + grep code Python :
    //     - PAS de [+1] futur
    //     - PAS de day_type (immunise vs incident #39 06/06)
    //     - Sources : ib_broken_up/dn + dist_vwap_d_atr, toutes deja en C++.
    //   Rho documente : -0.156 NQ / -0.101 ES (PAS +0.83 du brief Jackson).
    {
        // Fix compile B4 : ib_broken_up/down sont dans struct DMP_MLFeatures
        // (f), pas DMP_RawData (r). Note nom Sierra : `ib_broken_down`
        // (Transform.h:207) PAS `ib_broken_dn`.
        float dir_val;
        bool ib_up = (!DMP_B4_IsInvalid(f.ib_broken_up) && f.ib_broken_up > 0.5f);
        bool ib_dn = (!DMP_B4_IsInvalid(f.ib_broken_down) && f.ib_broken_down > 0.5f);
        if (ib_up && !ib_dn) {
            dir_val = 1.0f;
        } else if (ib_dn && !ib_up) {
            dir_val = -1.0f;
        } else {
            dir_val = 0.0f;
        }

        if (DMP_B4_IsInvalid(f.dist_vwap_d_atr)) {
            f.ctx_day_type_intensity = 0.0f;  // convention Python : 0.0 si VWAP atr invalide
        } else {
            float mag = std::fabs(f.dist_vwap_d_atr);
            float intensity = dir_val * mag;
            // Clip strict [-1, +1]
            if (intensity > 1.0f) intensity = 1.0f;
            if (intensity < -1.0f) intensity = -1.0f;
            f.ctx_day_type_intensity = intensity;
        }
    }
}

// =============================================================================
// FIN DMP_B4_Features.h
// =============================================================================
