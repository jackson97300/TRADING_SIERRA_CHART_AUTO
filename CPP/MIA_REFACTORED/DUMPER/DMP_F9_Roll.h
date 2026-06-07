#pragma once
// =============================================================================
// DMP_F9_Roll.h  —  Batch B3 (F9) : Contract roll detection
// =============================================================================
//
//  Role : Exposer 1 feature `is_roll_day` qui flag 1 pendant TOUT le trading
//         day ou un roll de contrat a ete detecte (= changement de sc.Symbol
//         entre 2 bars consecutives, MAIS root identique pour exclure les
//         manual switches operateur).
//
//  Audit B3 2026-06-07 : 1 feature GO PORT (`is_roll_day`), 1 DEFER
//  (`days_since_roll` cold-start probleme), 1 DROP (`roll_phase` LEAK
//  INSTRUMENT ks=1.0 audit 28/04). Cf DOCS/AUDIT_B3_F8_F9_F12_F22.md
//  section F9.
//
//  Logique :
//    1. Au boot premier bar : last_contract = d.contract, is_roll_day = 0.
//    2. Chaque bar : compare d.contract avec last_contract_hash persistant.
//       - Si different ET meme root (ex: ESH26 -> ESM26) : roll vrai
//         -> is_roll_day = 1, persiste 1 toute la session.
//       - Si different ET root different (ex: ESM26 -> NQM26) : manual_switch
//         -> NE PAS flagger (Jackson a change manuellement de chart, pas un roll).
//    3. Au prochain changement de date_et (trading_day) : reset is_roll_day = 0.
//
//  PersistVars (R3 review) :
//    * DMP_PERSIST_F9_LAST_CONTRACT_HASH (207) : hash 32-bit djb2 du
//      d.contract precedent. Compact storage 1 float.
//    * DMP_PERSIST_F9_LAST_CONTRACT_ROOT (208) : 2-letter root code en
//      int (ex: "ES" -> 'E'*256 + 'S' = 17747). Detecte manual_switch.
//    * DMP_PERSIST_F9_ROLL_DAY_FLAG    (209) : 1.0 si on est dans un roll day,
//      0.0 sinon. Reset au changement de trading_day.
//    * DMP_PERSIST_F9_ROLL_DAY_DATE    (210) : trading_day (YYYYMMDD) ou
//      le flag a ete leve. Reset si bar courante a trading_day different.
//
//  ATTENTION manual_switch :
//    sc.Symbol peut changer si Jackson edit le chart (ex: passe de ESM26
//    a NQM26). Ce ne sont PAS des rolls, ce sont des switches operateur.
//    Mitigation : extraire les 2 premieres lettres du ticker, si root
//    different = manual_switch (NE PAS flagger is_roll_day=1). Sinon
//    le faux positif fait Bot RiskManager refuser les trades pendant
//    toute la session (impact prod).
//
//  Date    : 2026-06-07
//  Build   : Batch B3 / Schema 3.7.20
// =============================================================================

#include "DMP_Reader.h"
#include <cstring>           // strncmp, strlen
#include <cmath>

// =============================================================================
// SECTION 1 — CONSTANTES
// =============================================================================

// Indices PersistVars (libres : 207-210, le scan 200-206 sont utilises).
constexpr int DMP_PERSIST_F9_LAST_CONTRACT_HASH = 207;
constexpr int DMP_PERSIST_F9_LAST_CONTRACT_ROOT = 208;
constexpr int DMP_PERSIST_F9_ROLL_DAY_FLAG      = 209;
constexpr int DMP_PERSIST_F9_ROLL_DAY_DATE      = 210;

// =============================================================================
// SECTION 2 — HELPERS
// =============================================================================

// Hash compact 32-bit (djb2) d'un C-string. Permet de comparer 2 contracts
// avec un seul float persisté plutôt que de stocker tout le string.
// Source : http://www.cse.yorku.ca/~oz/hash.html
static inline uint32_t DMP_F9_HashContract(const char* str) {
    if (!str) return 0u;
    uint32_t hash = 5381u;
    int c;
    while ((c = *str++) != 0) {
        // hash * 33 + c
        hash = ((hash << 5) + hash) + (uint32_t)c;
    }
    return hash;
}

// Extrait le "root code" du ticker (2 premieres lettres uppercase).
// "ESH26-CME" -> 'E'*256 + 'S' = 17747
// "NQM26"      -> 'N'*256 + 'Q' = 20305
// "MGCM26"     -> 'M'*256 + 'G' = 19783
// Cas dégénéré (string trop court ou non-ASCII) -> 0.
static inline int DMP_F9_GetRoot(const char* str) {
    if (!str || str[0] == '\0' || str[1] == '\0') return 0;
    unsigned char c0 = (unsigned char)str[0];
    unsigned char c1 = (unsigned char)str[1];
    // Sanity : caracteres ASCII imprimables uniquement
    if (c0 < 0x20 || c0 > 0x7E || c1 < 0x20 || c1 > 0x7E) return 0;
    return ((int)c0 << 8) | (int)c1;
}

// Helper "INVALID-like" local (legacy float — conserve pour si reuse externe).
// Le code F9 utilise GetPersistentInt depuis fix R1 review-code 2026-06-07.
static inline bool DMP_F9_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f) || !std::isfinite(v);
}

// =============================================================================
// SECTION 3 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit le champ f.is_roll_day depuis r.contract + r.trading_day.
//
// REQUIRES : r.contract null-terminated, r.trading_day = YYYYMMDD int valid.
// Si l'un des deux est invalid (cas degenere boot) -> f.is_roll_day = DMP_INVALID.

inline void DMP_ComputeF9_Roll(
    SCStudyInterfaceRef sc,
    DMP_MLFeatures& f,
    const DMP_RawData& r)
{
    // ─────────────────────────────────────────────────────────────────────────
    // PREP : PersistVars + sanity check inputs
    //   FIX R1 review-code B3 2026-06-07 : passe en GetPersistentInt pour
    //   eviter la perte de precision float au-dela de 2^24 (16M). Le hash
    //   djb2 d'un contract peut depasser 2^24, et trading_day YYYYMMDD
    //   (ex: 20260607 = 2.0e7) depasse aussi 2^24. Le roundtrip float
    //   uint32_t -> float -> uint32_t etait casse silencieusement -> prev_hash
    //   != cur_hash sur chaque bar -> is_roll_day=1 faux positif permanent.
    //   Convention : sentinelle 0 = boot non-initialise (hash djb2 != 0 par
    //   construction sauf string vide qui est filtree par sanity check).
    // ─────────────────────────────────────────────────────────────────────────
    int& last_hash_persist = sc.GetPersistentInt(DMP_PERSIST_F9_LAST_CONTRACT_HASH);
    int& last_root_persist = sc.GetPersistentInt(DMP_PERSIST_F9_LAST_CONTRACT_ROOT);
    int& roll_flag_persist = sc.GetPersistentInt(DMP_PERSIST_F9_ROLL_DAY_FLAG);
    int& roll_date_persist = sc.GetPersistentInt(DMP_PERSIST_F9_ROLL_DAY_DATE);

    // Reset sur Full Recalc Index 0 (eviter pollution DLL reload)
    if (sc.IsFullRecalculation && sc.Index == 0) {
        last_hash_persist = 0;
        last_root_persist = 0;
        roll_flag_persist = 0;
        roll_date_persist = 0;
    }

    // Validate inputs : si contract vide ou trading_day = 0 -> INVALID
    if (r.contract[0] == '\0' || r.trading_day <= 0) {
        f.is_roll_day = DMP_INVALID;
        return;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 1 — Calcul hash + root du contract courant
    // ─────────────────────────────────────────────────────────────────────────
    uint32_t cur_hash = DMP_F9_HashContract(r.contract);
    int cur_root = DMP_F9_GetRoot(r.contract);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 2 — Reset flag si trading_day a change depuis le flag
    //   roll_flag persiste TOUT le trading_day du roll, puis reset au lendemain.
    // ─────────────────────────────────────────────────────────────────────────
    if (roll_date_persist <= 0) {
        // Etat init (boot ou reset) -> flag inactif
        roll_flag_persist = 0;
    } else {
        if (roll_date_persist != r.trading_day) {
            // Trading day a change -> le flag du jour SORTANT n'est plus
            // applicable. Reset.
            roll_flag_persist = 0;
            roll_date_persist = 0;
        }
        // Sinon : on garde le flag actuel (peut etre 0 ou 1).
    }

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 3 — Detection de changement de contract
    // ─────────────────────────────────────────────────────────────────────────
    bool first_bar = (last_hash_persist == 0);

    if (first_bar) {
        // 1er bar boot : pas de comparaison possible, on initialise.
        // Cast int -> uint32_t : binary pattern preserve, recuperable.
        last_hash_persist = (int)cur_hash;
        last_root_persist = cur_root;
        // flag deja 0 -> rien a faire.
    } else {
        // Recupere binary pattern stocke. int -> uint32_t preserve bits.
        uint32_t prev_hash = (uint32_t)last_hash_persist;
        int prev_root = last_root_persist;

        if (cur_hash != prev_hash) {
            // Changement detecte. Vrai roll OU manual_switch ?
            if (cur_root == prev_root && cur_root != 0 && prev_root != 0) {
                // VRAI ROLL (ex: ESH26 -> ESM26) -> flag 1 pour TOUT le trading_day.
                roll_flag_persist = 1;
                roll_date_persist = r.trading_day;
            } else {
                // MANUAL_SWITCH (ex: ES -> NQ ou autre).
                // FIX R3 review-code B3 2026-06-07 : reset le flag du JOUR
                // SORTANT car le contexte change. Si l'utilisateur etait sur
                // ESH26 (vrai roll day flagge=1) et switch manuellement vers
                // NQ, le flag=1 herite ne reflete PAS un vrai roll de NQ.
                // Forcer 0 evite ce faux positif cross-instrument.
                roll_flag_persist = 0;
                roll_date_persist = 0;
            }

            // Update last contract hash + root pour les prochaines bars.
            last_hash_persist = (int)cur_hash;
            last_root_persist = cur_root;
        }
        // Sinon : meme contract -> rien a faire, flag persiste.
    }

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 4 — Exposer la feature (cast int 0/1 -> float pour struct DMP_MLFeatures)
    // ─────────────────────────────────────────────────────────────────────────
    f.is_roll_day = (float)roll_flag_persist;
}

// =============================================================================
// FIN DMP_F9_Roll.h
// =============================================================================
