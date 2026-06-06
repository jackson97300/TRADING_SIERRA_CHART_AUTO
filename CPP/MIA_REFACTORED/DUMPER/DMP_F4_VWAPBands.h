#pragma once
// =============================================================================
// DMP_F4_VWAPBands.h  —  Batch B2 (F4) : Niveaux VWAP absolus
// =============================================================================
//
//  Role : Exposer les niveaux VWAP daily / weekly / monthly + bandes SD comme
//         features ABSOLUES dans le JSONL. Jusqu'a B1 inclus, seules les
//         distances (ticks, atr, pct) etaient serialisees. B2 ajoute les
//         valeurs brutes pour permettre downstream (bots, ML, dashboard) de
//         reconstruire dist contre n'importe quel niveau de reference (ATR
//         alternative, vol modeling, mid-band lookups).
//
//  Decision Jackson 2026-06-07 — Sierra prime sur 3 familles (prop firms
//  RTH-only, aucun overnight). VWAP est l'une de ces 3 familles. La source
//  C++ Sierra est anchored 09:30 ET (cash open) et fait autorite vs Python
//  pipeline qui ancre 00:00 ET (CME midnight). Cf DMP_F3_DistNormalisees.h
//  pour le bloc decision complet (group A).
//
//  Source des niveaux : tous deja lus dans DMP_RawData par
//    - DMP_ReadVWAPDay     (chart 26/27 Study VWAP_DAY, sg0-6)
//    - DMP_ReadDaily       (chart 16/17 Studies VWAP_WEEKLY/MONTHLY, sg0-2)
//    - DMP_ReadVolumeProfile (chart 26/27 Study VP_PREVIOUS sg4 = prev_vwap,
//                             VP_PREV_WAPS sg12/13 = prev_vwap_sd1u/d)
//  Aucun nouveau read ACSIL requis pour ce header (zero impact perf).
//
//  Convention valeur :
//    * Prix absolu en POINTS (ex: 6087.25 pour ES, 30462.5 pour NQ).
//    * DMP_INVALID si le niveau Sierra n'est pas valide (etude absente,
//      sentinel SC, NaN/Inf).
//
//  Fail-loud :
//    Helper DMP_F4_SafeLevel filtre via DMP_IsPriceValid (rejet 0, NaN, Inf,
//    sentinel SC 1e37+, prix hors plage 100-100000). Si reject -> DMP_INVALID.
//
//  Features exposees (24) :
//    Group A — VWAP Daily : vwap_d, vwap_d_sd1u/d, sd2u/d, sd3u/d (7)
//    Group B — VWAP Weekly : vwap_w + sd1u/d + sd2u/d + sd3u/d (7)
//    Group C — VWAP Monthly : vwap_m + sd1u/d + sd2u/d + sd3u/d (7)
//    Group D — Previous VWAP : pvwap, pvwap_sd1u, pvwap_sd1d (3)
//      Note : nomme "pvwap" (vs prev_vwap dans le Reader) pour aligner avec
//      la convention Python live_enriched + dataset_builder.
//
//  EXTENSION 2026-06-07 — SD2/SD3 Weekly + Monthly portees (+8 fields vs
//  16 initial). Decision Jackson : reconfig Sierra studies VWAP Weekly et
//  Monthly (chart 23 ID:43+41 + chart 25 ID:23+33) :
//    * Band 1 Multiplier (In:13) = 1.0  (etait 0.5, semantique SD1 standard)
//    * Band 2 Multiplier (In:14) = 2.0  (etait 1.0)
//    * Band 3 Multiplier (In:15) = 3.0  (etait 1.5)
//    * Band 4 Multiplier (In:16) = 4.0  (etait 2.0, non utilise B2)
//    * Subgraphs sg3/sg4 (Band 2) DEJA actifs (Dash Solid) → SD2 disponible
//    * Subgraphs sg5/sg6 (Band 3) ACTIVES (Ignore → Dash) → SD3 disponible
//  Sans cette reconfig + reload, vwap_*_sd2u/d retourne sg3/sg4 = +/-1σ
//  (Band 2 ancien multi=1.0) et vwap_*_sd3u/d retourne DMP_INVALID (Band 3
//  Ignore non calculee par Sierra). Verif J+1 obligatoire post-deploy.
//
//  Date    : 2026-06-07
//  Build   : Batch B2 / Schema 3.7.19
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>             // std::isfinite

// =============================================================================
// SECTION 1 — HELPER FILTRE
// =============================================================================

// Filtre un niveau VWAP : renvoie le niveau si valide, sinon DMP_INVALID.
// Centralise la garde pour eviter de repeter DMP_IsPriceValid 15x.
static inline float DMP_F4_SafeLevel(float level) {
    if (!DMP_IsPriceValid(level)) return DMP_INVALID;
    return level;
}

// =============================================================================
// SECTION 2 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 24 champs absolus de VWAP dans DMP_MLFeatures depuis les
// niveaux bruts deja lus dans DMP_RawData. Aucun calcul Sierra Chart ici.
//
// Doit etre appelee APRES CalcVWAP() et CalcVolumeProfile() — qui sont eux
// memes appeles dans DMP_Transform() avant ce helper. En pratique l'ordre
// n'a pas d'importance car cette fonction ne depend QUE de r.* (deja
// rempli par DMP_ReadAll en amont du Transform).

inline void DMP_ComputeF4_VWAPBands(DMP_MLFeatures& f, const DMP_RawData& r) {
    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE A — VWAP Daily (7 features)
    // Source : DMP_ReadVWAPDay (chart 26/27 Study VWAP_DAY)
    // ─────────────────────────────────────────────────────────────────────────
    f.vwap_d      = DMP_F4_SafeLevel(r.vwap_day);
    f.vwap_d_sd1u = DMP_F4_SafeLevel(r.vwap_day_sd1u);
    f.vwap_d_sd1d = DMP_F4_SafeLevel(r.vwap_day_sd1d);
    f.vwap_d_sd2u = DMP_F4_SafeLevel(r.vwap_day_sd2u);
    f.vwap_d_sd2d = DMP_F4_SafeLevel(r.vwap_day_sd2d);
    f.vwap_d_sd3u = DMP_F4_SafeLevel(r.vwap_day_sd3u);
    f.vwap_d_sd3d = DMP_F4_SafeLevel(r.vwap_day_sd3d);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE B — VWAP Weekly (7 features)
    // Source : chart 23/25 Study VWAP_WEEKLY (NQ ID:43 / ES ID:23)
    // Multiplicateurs Sierra reconfigures 2026-06-07 : Band 1=1, 2=2, 3=3.
    // SD2/SD3 portees suite extension B2. sg3-sg6 lus dans DMP_Reader.h.
    // ─────────────────────────────────────────────────────────────────────────
    f.vwap_w      = DMP_F4_SafeLevel(r.vwap_weekly);
    f.vwap_w_sd1u = DMP_F4_SafeLevel(r.vwap_weekly_sd1u);
    f.vwap_w_sd1d = DMP_F4_SafeLevel(r.vwap_weekly_sd1d);
    f.vwap_w_sd2u = DMP_F4_SafeLevel(r.vwap_weekly_sd2u);
    f.vwap_w_sd2d = DMP_F4_SafeLevel(r.vwap_weekly_sd2d);
    f.vwap_w_sd3u = DMP_F4_SafeLevel(r.vwap_weekly_sd3u);
    f.vwap_w_sd3d = DMP_F4_SafeLevel(r.vwap_weekly_sd3d);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE C — VWAP Monthly (7 features)
    // Source : chart 23/25 Study VWAP_MONTHLY (NQ ID:41 / ES ID:33)
    // Idem reconfig multiplicateurs std 1/2/3 sigma.
    // ─────────────────────────────────────────────────────────────────────────
    f.vwap_m      = DMP_F4_SafeLevel(r.vwap_monthly);
    f.vwap_m_sd1u = DMP_F4_SafeLevel(r.vwap_monthly_sd1u);
    f.vwap_m_sd1d = DMP_F4_SafeLevel(r.vwap_monthly_sd1d);
    f.vwap_m_sd2u = DMP_F4_SafeLevel(r.vwap_monthly_sd2u);
    f.vwap_m_sd2d = DMP_F4_SafeLevel(r.vwap_monthly_sd2d);
    f.vwap_m_sd3u = DMP_F4_SafeLevel(r.vwap_monthly_sd3u);
    f.vwap_m_sd3d = DMP_F4_SafeLevel(r.vwap_monthly_sd3d);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE D — Previous VWAP daily (3 features)
    // Source : DMP_ReadVolumeProfile (VP_PREVIOUS sg4 = prev_vwap,
    //          VP_PREV_WAPS sg12/13 = prev_vwap_sd1u/d).
    // Alias : pvwap = "previous VWAP daily" (cf Python live_enriched).
    // ─────────────────────────────────────────────────────────────────────────
    f.pvwap      = DMP_F4_SafeLevel(r.prev_vwap);
    f.pvwap_sd1u = DMP_F4_SafeLevel(r.prev_vwap_sd1u);
    f.pvwap_sd1d = DMP_F4_SafeLevel(r.prev_vwap_sd1d);
}

// =============================================================================
// FIN DMP_F4_VWAPBands.h
// =============================================================================
