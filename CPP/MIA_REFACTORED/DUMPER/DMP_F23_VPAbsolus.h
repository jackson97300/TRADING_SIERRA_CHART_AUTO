#pragma once
// =============================================================================
// DMP_F23_VPAbsolus.h  —  Batch B2 (F23) : Volume Profile niveaux absolus
// =============================================================================
//
//  Role : Exposer les niveaux VPOC/VAH/VAL absolus (session courante + J-1)
//         comme features dans le JSONL. Jusqu'a B1, seules les distances
//         (ticks, atr, pct) etaient serialisees. B2 ajoute les valeurs
//         brutes pour permettre reconstruction downstream + cross-source
//         (Sierra vs Python algo Steidlmayer).
//
//  Decision Jackson 2026-06-07 — Sierra prime sur 3 familles (prop firms
//  RTH-only). Volume Profile est l'une de ces 3 familles : Sierra utilise
//  l'etude SC officielle anchored cash session, alors que Python utilise
//  un algo Steidlmayer pur ("compute_volume_profile_dict") qui a un biais
//  documente (VPOC = close si n=1 trade). Sierra prime. Cf bloc decision
//  DMP_F3_DistNormalisees.h group B.
//
//  Source des niveaux (deja lus dans DMP_RawData) :
//    * cur_vpoc / cur_vah / cur_val : DMP_ReadVolumeProfile (chart 26/27
//      Study VP_CURRENT sg1/2/3). Niveau de la session courante.
//    * prev_vpoc / prev_vah / prev_val : meme fonction Reader (VP_PREVIOUS
//      sg1/2/3). Niveau de la session precedente (J-1).
//
//  Aucun nouveau read ACSIL requis (zero impact perf, juste exposition).
//
//  Convention valeur :
//    * Prix absolu en POINTS (ex: 6087.25 pour ES, 30462.5 pour NQ).
//    * DMP_INVALID si l'etude VP n'a pas de donnees (debut de session,
//      avant que le profil n'ait accumule assez de volume).
//
//  Fail-loud :
//    Helper DMP_F23_SafeLevel filtre via DMP_IsPriceValid (rejet 0, NaN,
//    Inf, sentinel SC 1e37+, prix hors plage 100-100000).
//
//  Features exposees (6) :
//    Group A — VP Current : cur_vpoc, cur_vah, cur_val (3)
//    Group B — VP Previous : prev_vpoc, prev_vah, prev_val (3)
//
//  Date    : 2026-06-07
//  Build   : Batch B2 / Schema 3.7.19
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>             // std::isfinite

// =============================================================================
// SECTION 1 — HELPER FILTRE
// =============================================================================

// Filtre un niveau VP : renvoie le niveau si valide, sinon DMP_INVALID.
// Centralise la garde DMP_IsPriceValid.
static inline float DMP_F23_SafeLevel(float level) {
    if (!DMP_IsPriceValid(level)) return DMP_INVALID;
    return level;
}

// =============================================================================
// SECTION 2 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 6 champs absolus de VP dans DMP_MLFeatures depuis les niveaux
// bruts deja lus dans DMP_RawData. Aucun calcul Sierra Chart ici.

inline void DMP_ComputeF23_VPAbsolus(DMP_MLFeatures& f, const DMP_RawData& r) {
    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE A — Volume Profile Session courante (3 features)
    // Source : DMP_ReadVolumeProfile (VP_CURRENT sg1/2/3, SafeReadLast).
    // ─────────────────────────────────────────────────────────────────────────
    f.cur_vpoc_lvl = DMP_F23_SafeLevel(r.cur_vpoc);
    f.cur_vah_lvl  = DMP_F23_SafeLevel(r.cur_vah);
    f.cur_val_lvl  = DMP_F23_SafeLevel(r.cur_val);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE B — Volume Profile Session precedente (3 features)
    // Source : DMP_ReadVolumeProfile (VP_PREVIOUS sg1/2/3, SafeReadLast).
    // ─────────────────────────────────────────────────────────────────────────
    f.prev_vpoc_lvl = DMP_F23_SafeLevel(r.prev_vpoc);
    f.prev_vah_lvl  = DMP_F23_SafeLevel(r.prev_vah);
    f.prev_val_lvl  = DMP_F23_SafeLevel(r.prev_val);
}

// =============================================================================
// FIN DMP_F23_VPAbsolus.h
// =============================================================================
