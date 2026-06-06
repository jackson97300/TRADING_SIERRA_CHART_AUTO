#pragma once
// =============================================================================
// DMP_F2_PrevLevels.h  —  Batch B2 (F2) : Previous & Open Levels absolus
// =============================================================================
//
//  Role : Exposer les niveaux absolus de reference J-1 (PDH/PDL), de cash
//         session (cash_high/low + open_cash + open_830), et d'overnight
//         (ovn_high/low) comme features dans le JSONL. Jusqu'a B1, ces
//         valeurs n'etaient disponibles qu'au format dist (ticks/atr/pct).
//         B2 ajoute les niveaux bruts pour reconstruire les distances cote
//         downstream avec n'importe quel referentiel.
//
//  Decision Jackson 2026-06-07 — Sierra prime sur 3 familles (prop firms
//  RTH-only, aucun overnight). Session high/low (= cash_high/cash_low ici)
//  est l'une de ces 3 familles. Sierra prime pour les memes raisons :
//    * Sierra HH_SESSION/LL_SESSION : RTH-only (cash 09:30-16:00 ET)
//    * Python session_date_trading : CME 24h (dim 18:00 -> ven 17:00 ET
//      avec overnight inclus, dilue le signal RTH)
//  Le bot prop firm ne trade jamais hors RTH -> RTH-only cash session est
//  la convention metier coherente. Cf DMP_F3_DistNormalisees.h group C
//  pour le bloc decision complet.
//
//  Sources des niveaux :
//    * pdh / pdl : accumulateur PersistVars dans DMP_ReadDeltaDivergenceClean
//      (DMP_Reader.h:2354). Snapshot du daily_high/low du jour SORTANT
//      capture au moment du reset trading_day. Cf section "B. Plan port"
//      du Reader pour la mecanique complete.
//    * cur_pdh / cur_pdl : running daily_high/low (jour COURANT) extrait
//      des memes PersistVars (200/201). Necessite une legere extension du
//      Reader (ou re-derivation a partir de sess_high/low + ovn_high/low).
//      DECISION : ne PAS exposer cur_pdh/cur_pdl dans ce batch B2.
//                  Raison : le jour CME va de 18:00 ET jusqu'a 17:00 ET.
//                  Le "current PDH" pour le bot RTH-only est en fait
//                  max(sess_high, ovn_high). Mais on n'a pas besoin d'un
//                  champ derive ici : le bot peut le faire au besoin (sa
//                  semantique RTH vs CME varie selon strategie).
//                  Si Jackson demande cur_pdh/cur_pdl explicitement plus
//                  tard, on les ajoutera en batch C.
//    * cash_high / cash_low : alias semantique de sess_high / sess_low
//      (deja lus par DMP_ReadSession depuis HH_SESSION/LL_SESSION). Sierra
//      HH_SESSION reflète "highest cash session price observed" depuis
//      l'ouverture RTH. Cf decision Jackson : Sierra prime.
//    * open_cash : alias de open_cash (deja lu = sg0 OHLC_SESSION
//      chart 26/27, qui est l'open exact 09:30 ET).
//    * open_830 : deja lu par DMP_ReadSession depuis OPEN_830 chart 23/25
//      (Open 08:30 ET pour rapports macro pre-cash-open).
//    * ovn_high / ovn_low : deja lus par DMP_ReadOVN depuis OVN_HL chart
//      30/31 (window 18:00-09:29 ET).
//
//  Convention valeur :
//    * Prix absolu en POINTS. DMP_INVALID si le niveau Sierra n'est pas
//      valide (etude absente, sentinel, ou 1ere session du backfill
//      pour pdh/pdl).
//
//  Cas particulier — 1ere session backfill :
//    pdh/pdl restent DMP_INVALID jusqu'a ce que le premier reset session
//    soit detecte. C'est par construction : il n'y a pas de J-1 connu pour
//    la toute premiere session du dataset. Le validator Python doit
//    tolerer ces nulls sur la 1ere date du JSONL multi-jour.
//
//  Date    : 2026-06-07
//  Build   : Batch B2 / Schema 3.7.19
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>             // std::isfinite

// =============================================================================
// SECTION 1 — HELPER FILTRE
// =============================================================================

// Filtre un niveau de prix : renvoie le niveau si valide, sinon DMP_INVALID.
// Centralise la garde DMP_IsPriceValid (rejet 0, NaN, Inf, sentinel SC, hors
// plage 100-100000) pour eviter les copier-coller dans la section 2.
static inline float DMP_F2_SafeLevel(float level) {
    if (!DMP_IsPriceValid(level)) return DMP_INVALID;
    return level;
}

// =============================================================================
// SECTION 2 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 7 champs absolus de previous levels dans DMP_MLFeatures depuis
// les niveaux deja lus dans DMP_RawData. Aucun calcul Sierra Chart ici.
//
// Doit etre appelee APRES DMP_ReadAll() (donc dans DMP_Transform comme les
// autres helpers F*). DMP_ReadDeltaDivergenceClean (appele par DMP_ReadCVD)
// remplit r.prev_daily_high/low avant l'arrivee ici.

inline void DMP_ComputeF2_PrevLevels(DMP_MLFeatures& f, const DMP_RawData& r) {
    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE A — Previous Day High/Low (2 features)
    // Source : accumulateur PersistVars (DMP_PERSIST_DIV_PREV_HIGH/LOW)
    //          mis a jour par DMP_ReadDeltaDivergenceClean au reset session.
    // Note : DMP_INVALID pour la 1ere session du backfill (pas de J-1 connu).
    // ─────────────────────────────────────────────────────────────────────────
    f.pdh = DMP_F2_SafeLevel(r.prev_daily_high);
    f.pdl = DMP_F2_SafeLevel(r.prev_daily_low);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE B — Cash Session High/Low (2 features)
    // Sierra prime (Jackson decision 2026-06-07) : Sierra HH_SESSION /
    // LL_SESSION sont RTH-only par defaut, alors que Python session_*
    // inclut overnight. Le bot prop firm RTH-only -> Sierra coherent.
    //
    // Convention : cash_high/cash_low = sess_high/sess_low du Reader
    // (alias). Pas de calcul, juste un re-nommage explicite pour Python
    // downstream (qui peut chercher "cash_*" plutot que "sess_*").
    // ─────────────────────────────────────────────────────────────────────────
    f.cash_high = DMP_F2_SafeLevel(r.sess_high);
    f.cash_low  = DMP_F2_SafeLevel(r.sess_low);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE C — Open Cash + Open 8h30 (2 features)
    // Source :
    //   open_cash = OHLC_SESSION sg0 (chart 26/27) = open 09:30 ET exact
    //               Alias semantique : open_930_et (cf Python live_enriched).
    //   open_830  = OPEN_830 sg0 (chart 23/25) = open 08:30 ET (rapports
    //               macro pre-cash, ex: NFP, CPI, Powell).
    //
    // Exposes en absolu pour permettre :
    //   1. Reconstruire dist_open_*_pct contre nimporte quel close (live ou
    //      replay) sans dependre des dist_open_* C++ calcules a l'origine.
    //   2. Detecter open_gap = open_cash - pvwap (deja calcule, mais utile
    //      pour cross-check Sierra vs Python).
    // ─────────────────────────────────────────────────────────────────────────
    f.open_cash_lvl = DMP_F2_SafeLevel(r.open_cash);
    f.open_830_lvl  = DMP_F2_SafeLevel(r.open_830);

    // ─────────────────────────────────────────────────────────────────────────
    // GROUPE D — Overnight High/Low (2 features)
    // Source : DMP_ReadOVN (chart 30/31 Studies OVN_HL = High/Low for Time
    // Period 18:00-09:29 ET). Lit via SafeReadLastValid (scan arriere)
    // car l'etude ne peint QUE pendant la fenetre overnight; SafeReadLast
    // recupere la derniere valeur peinte (= la barre 09:29 ET) qui reste
    // le high/low fige pour le reste de la session RTH.
    //
    // Note : DMP_ReadOVN inclut deja une garde de coherence (ratio < 0.8
    // ou > 1.2 vs prix courant -> invalider). Donc ovn_high/low ici sont
    // soit valides + raisonnables, soit DMP_INVALID.
    // ─────────────────────────────────────────────────────────────────────────
    f.ovn_high_lvl = DMP_F2_SafeLevel(r.ovn_high);
    f.ovn_low_lvl  = DMP_F2_SafeLevel(r.ovn_low);
}

// =============================================================================
// FIN DMP_F2_PrevLevels.h
// =============================================================================
