#pragma once
// =============================================================================
// DMP_F3_DistNormalisees.h  —  Batch B1 : Distances normalisees _pct
// =============================================================================
//
//  Role : Calcul des features dist_*_pct = (level - close) / close * 100.
//         Signed, sans clamp (contrairement aux _atr qui sont clampes ±20).
//         Pendant Python live_enriched : phase_b_helpers.py:1063-1093 _dist().
//
//  Mode : "Sierra-rich" — port batch B1 du 2026-06-07 (Jackson decision).
//         37 features _pct ajoutees au schema (3.7.17 -> 3.7.18).
//
//  Convention :
//    pct > 0  →  niveau au-dessus du prix courant (cible de hausse)
//    pct < 0  →  niveau en-dessous du prix courant (cible de baisse)
//    pct = 0  →  prix exactement sur le niveau
//
//  Fail-loud :
//    - Si close <= 0 ou !isfinite        → DMP_INVALID (tous les pct nullifies)
//    - Si level invalide (DMP_INVALID/0) → DMP_INVALID pour ce pct precis
//
//  Reference Python (source de la formule) :
//    CORE/phase_b_helpers.py:1069-1078
//      def _dist(level):
//          return (level - cf) / cf * 100 if not pd.isna(level) else np.nan
//
//  Note groupe F (Zones nearest) :
//    Sierra utilise les Extension Lines (ext_color_*_px, ext_long_*_px,
//    ext_edge_*_px) tandis que Python utilise des streams de zones detectees
//    (color_streaming, long_streaming, edge_zones). Les valeurs DIVERGENT en
//    methode mais conservent la meme semantique (distance au niveau le plus
//    proche). Documentes pour Bot ML mais parite non-bit-for-bit sur ces 8.
//
//  DECISION JACKSON 2026-06-07 — Sierra prime sur 3 familles (groups A/B/C)
//  =========================================================================
//  Cause empirique : trading prop firms = AUCUNE position overnight autorisee.
//  Donc convention RTH-only (cash session 09:30-16:00 ET) = standard metier.
//  Sierra prime systematiquement sur Python pour les 3 familles suivantes :
//
//  Group A — VWAP daily (5 features dist_vwap_d_pct + 4 SD bands)
//    Sierra : etude SC standard, anchored 09:30 ET (RTH open)
//    Python : recalc maison `cum_pv/cum_v` anchored 00:00 ET (midnight CME)
//    Sierra prime : convention institutionnelle TradingView / Bloomberg / banques.
//    Bot intraday cash trading = anchor 09:30 ET = signal directionnel propre,
//    pas dilue par Asia/London overnight.
//    Ecart empirique : ~100 points NQ sur certaines bars (audit 02/06 close=30462.5
//    Python=30491.0 vs Sierra=30591.5). NON un bug = convention different.
//
//  Group B — Volume Profile courant (3 features dist_cur_vpoc/vah/val_pct)
//    Sierra : etude SC Volume Profile (source officielle metier)
//    Python : algo Steidlmayer pur (`compute_volume_profile_dict`) avec biais
//             documente VPOC=close si n=1 trade (anti-pattern reviewer #4)
//    Sierra prime : etude SC est la reference institutionnelle. Algo Python
//             a un biais de bord de session connu.
//
//  Group C — Session high/low (2 features dist_sess_high/low_pct)
//    Sierra : etude SC RTH-only par defaut (cash session intraday)
//    Python : `session_date_trading` CME 24h (dim 18:00 ET -> ven 17:00 ET)
//             avec overnight inclus
//    Sierra prime : prop firms = aucun overnight = RTH-only seul pertinent.
//             Python session 24h dilue le signal RTH avec Asia/London.
//
//  Implication operationnelle :
//    Les seuils des regles Bot 2/3 ont ete calibres sur Python live_enriched
//    avant le pivot. Apres deploy 3.7.18, Bot 2/3 doivent etre tests paper
//    A/B sur quelques jours pour recalibrer les seuils (PAS de ML, just regles).
//    Si les decisions Bot post-pivot sont equivalentes ou meilleures qu'avant
//    -> OK adopte. Sinon ajuster seuils manuellement.
//
//  References audit : DOCS/AUDIT_10_NOGO_CAUSES_RACINES.md (2026-06-07)
//                     DOCS/QUALITY_VALIDATION_B1.md (2026-06-07)
//
//  Date    : 2026-06-07
//  Build   : Batch B1 / Schema 3.7.18
// =============================================================================

// Note : ce header est inclu DEPUIS DMP_Transform.h apres la definition de
// DMP_MLFeatures. Ne pas re-inclure DMP_Transform.h ici (cycle d'include).
// Dependances : DMP_RawData (Reader), DMP_MLFeatures (Transform).
#include "DMP_Reader.h"
#include <cmath>             // std::isfinite, std::fabs

// =============================================================================
// SECTION 1 — HELPER NIVEAU MATHEMATIQUE
// =============================================================================

// Calcul dist_*_pct = (level - close) / close * 100.
//
// IMPORTANT : la formule est SIGNEE (pas |...|). Convention identique a Python
// (level - close) / close * 100 :
//   * level > close  → pct > 0  (niveau au-dessus)
//   * level < close  → pct < 0  (niveau en-dessous)
//
// Renvoie DMP_INVALID si :
//   * level invalide (DMP_INVALID, NaN, Inf, ou <= 0)
//   * close invalide (DMP_INVALID, NaN, Inf, ou <= 0)
//
// Note : pas de clamp. Les _pct n'ont pas le probleme du train-serve skew des
// _atr (cf DMP_Config.h CLAMP_ATR 5.0 -> 20.0). Si Jackson voit un pct > 5%
// c'est un signal trader (niveau tres lointain), pas un bug a masquer.
static inline float DMP_CalcDistPct(float close, float level) {
    if (!DMP_IsPriceValid(level)) return DMP_INVALID;
    if (!DMP_IsPriceValid(close)) return DMP_INVALID;
    if (close <= 0.0f)            return DMP_INVALID;   // garde anti division
    float pct = (level - close) / close * 100.0f;
    if (!std::isfinite(pct))      return DMP_INVALID;
    return pct;
}

// Helper convenience : convertir distance en TICKS en _pct via tick_size.
// Utilise pour Group F (Extension Lines) ou Sierra stocke deja dist_*_ticks
// mais pas le niveau brut.
//
//   pct = (level - close) / close * 100
//       = (dist_ticks * tick_size) / close * 100
//
// Ce chemin est equivalent au DMP_CalcDistPct(close, level) quand on connait
// level = close + dist_ticks * tick_size, mais evite de recalculer level.
static inline float DMP_CalcDistPctFromTicks(float dist_ticks, float close, float tick_size) {
    if (!DMP_IsValid(dist_ticks))   return DMP_INVALID;
    if (!DMP_IsPriceValid(close))   return DMP_INVALID;
    if (close <= 0.0f)              return DMP_INVALID;
    if (tick_size <= 0.0f)          return DMP_INVALID;
    float pct = (dist_ticks * tick_size) / close * 100.0f;
    if (!std::isfinite(pct))        return DMP_INVALID;
    return pct;
}

// =============================================================================
// SECTION 2 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 37 champs dist_*_pct de DMP_MLFeatures depuis les niveaux bruts
// disponibles dans DMP_RawData.
//
// Doit etre appelee APRES CalcVWAP, CalcVolumeProfile, CalcMenthorQ, CalcSession
// car certains pct dependent indirectement de leur initialisation (zero-out
// par defaut). En pratique, l'appel est independant car la formule lit
// directement r.* (niveaux bruts) et f.dist_*_ticks (deja calcules pour group F).
//
// Convention de signe : positif = niveau AU-DESSUS du prix courant.

inline void DMP_ComputeF3_DistNormalisees(DMP_MLFeatures& f, const DMP_RawData& r) {
    const float close = r.price_close;
    const float ts    = r.tick_size;

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE A — VWAP _pct (13 features)
    // Source : niveaux VWAP bruts deja lus dans DMP_RawData (Chart 26/27, 16/17)
    // Note : Sierra ne fournit pas vwap_w_sd2/3 ni vwap_m_sd2/3 → non portees.
    // ─────────────────────────────────────────────────────────────────────────
    // VWAP Daily (7)
    f.dist_vwap_d_pct      = DMP_CalcDistPct(close, r.vwap_day);
    f.dist_vwap_d_sd1u_pct = DMP_CalcDistPct(close, r.vwap_day_sd1u);
    f.dist_vwap_d_sd1d_pct = DMP_CalcDistPct(close, r.vwap_day_sd1d);
    f.dist_vwap_d_sd2u_pct = DMP_CalcDistPct(close, r.vwap_day_sd2u);
    f.dist_vwap_d_sd2d_pct = DMP_CalcDistPct(close, r.vwap_day_sd2d);
    f.dist_vwap_d_sd3u_pct = DMP_CalcDistPct(close, r.vwap_day_sd3u);
    f.dist_vwap_d_sd3d_pct = DMP_CalcDistPct(close, r.vwap_day_sd3d);

    // VWAP Weekly (3 — SD1 only, pas SD2/3 dans Sierra)
    f.dist_vwap_w_pct      = DMP_CalcDistPct(close, r.vwap_weekly);
    f.dist_vwap_w_sd1u_pct = DMP_CalcDistPct(close, r.vwap_weekly_sd1u);
    f.dist_vwap_w_sd1d_pct = DMP_CalcDistPct(close, r.vwap_weekly_sd1d);

    // VWAP Monthly (3 — SD1 only)
    f.dist_vwap_m_pct      = DMP_CalcDistPct(close, r.vwap_monthly);
    f.dist_vwap_m_sd1u_pct = DMP_CalcDistPct(close, r.vwap_monthly_sd1u);
    f.dist_vwap_m_sd1d_pct = DMP_CalcDistPct(close, r.vwap_monthly_sd1d);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE B — Volume Profile _pct (6 features)
    // Source : VP session courante + J-1 (Chart 26/27 Study 1/2)
    // ─────────────────────────────────────────────────────────────────────────
    f.dist_cur_vpoc_pct  = DMP_CalcDistPct(close, r.cur_vpoc);
    f.dist_cur_vah_pct   = DMP_CalcDistPct(close, r.cur_vah);
    f.dist_cur_val_pct   = DMP_CalcDistPct(close, r.cur_val);
    f.dist_prev_vpoc_pct = DMP_CalcDistPct(close, r.prev_vpoc);
    f.dist_prev_vah_pct  = DMP_CalcDistPct(close, r.prev_vah);
    f.dist_prev_val_pct  = DMP_CalcDistPct(close, r.prev_val);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE C — Session High/Low _pct (2 features)
    // ─────────────────────────────────────────────────────────────────────────
    f.dist_sess_high_pct = DMP_CalcDistPct(close, r.sess_high);
    f.dist_sess_low_pct  = DMP_CalcDistPct(close, r.sess_low);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE D — MenthorQ Options-driven _pct (6 features)
    // Source : niveaux MQ_GAMMA (call/put/hvl + 0DTE) deja lus
    // ─────────────────────────────────────────────────────────────────────────
    f.dist_mq_call_pct      = DMP_CalcDistPct(close, r.mq_call);
    f.dist_mq_put_pct       = DMP_CalcDistPct(close, r.mq_put);
    f.dist_mq_hvl_pct       = DMP_CalcDistPct(close, r.mq_hvl);
    f.dist_mq_call_0dte_pct = DMP_CalcDistPct(close, r.mq_call_0dte);
    f.dist_mq_put_0dte_pct  = DMP_CalcDistPct(close, r.mq_put_0dte);
    f.dist_mq_hvl_0dte_pct  = DMP_CalcDistPct(close, r.mq_hvl_0dte);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE E — 1D Extremes (Daily MenthorQ targets) _pct (2 features)
    // ─────────────────────────────────────────────────────────────────────────
    f.dist_1d_max_ticks_pct = DMP_CalcDistPct(close, r.mq_1d_max);
    f.dist_1d_min_ticks_pct = DMP_CalcDistPct(close, r.mq_1d_min);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE F — Zones nearest _pct via Extension Lines + GEX (8 features)
    // ATTENTION : DIVERGENCE METHODE vs Python.
    //   Sierra : Extension Lines (LineUntilFutureIntersection, niveaux S/R
    //            historiques persistants — depuis ext_*_px de DMP_RawData)
    //   Python : streams zones detectees per-bar (n_*_active live)
    // Les valeurs DIVERGENT par construction mais conservent la semantique
    // "distance au niveau le plus proche". Documentees pour ML, parite non
    // bit-for-bit sur ces 8 features.
    // ─────────────────────────────────────────────────────────────────────────

    // Long Up/Dn via Extension Lines
    f.dist_long_up_nearest_pct = DMP_CalcDistPct(close, r.ext_long_up_px);
    f.dist_long_dn_nearest_pct = DMP_CalcDistPct(close, r.ext_long_dn_px);

    // Color Up/Dn via Extension Lines
    f.dist_color_up_nearest_pct = DMP_CalcDistPct(close, r.ext_color_up_px);
    f.dist_color_dn_nearest_pct = DMP_CalcDistPct(close, r.ext_color_dn_px);

    // Edge Buy/Sell via Extension Lines
    f.dist_edge_buy_nearest_pct  = DMP_CalcDistPct(close, r.ext_edge_buy_px);
    f.dist_edge_sell_nearest_pct = DMP_CalcDistPct(close, r.ext_edge_sell_px);

    // GEX nearest up/dn : Sierra n'a pas le PRIX nearest, juste dist_ticks.
    // On convertit dist_ticks -> pct via tick_size.
    // f.dist_gex_nearest_up/dn sont calcules par CalcMenthorQ AVANT cet appel.
    f.dist_gex_nearest_up_pct = DMP_CalcDistPctFromTicks(f.dist_gex_nearest_up, close, ts);
    f.dist_gex_nearest_dn_pct = DMP_CalcDistPctFromTicks(f.dist_gex_nearest_dn, close, ts);
}

// =============================================================================
// FIN DMP_F3_DistNormalisees.h
// =============================================================================
