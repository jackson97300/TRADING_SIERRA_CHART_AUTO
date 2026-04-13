// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Main.cpp  —  MIA Data Dumper G3 : Point d'entrée ACSIL
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Ce fichier est le SEUL à compiler dans Sierra Chart.
//  Il orchestre les 5 modules DMP dans cet ordre fixe à chaque barre :
//
//    1. DMP_ReadAll()              ← Lecture des 13 charts liés
//    2. DMP_ComputeHVN_LVN()       ← HVN/LVN session (AVANT Transform pour G11)
//    3. DMP_Transform()            ← 168 features ML (G1-G12, hvn passé en arg)
//    4. DMP_UpdateOpenType()       ← Open type / day type / rule_80pct (G9)
//    5. PS_AnalyzeCurrentSession() ← Forme profil D/P/b/B (G12)
//    6. DMP_WriteRow()             ← Sérialisation JSONL sur disque
//
//  ── EMPLACEMENT ────────────────────────────────────────────────────────────────
//
//    D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER\DMP_Main.cpp
//
//    Tous les fichiers DMP_*.h sont dans le MÊME dossier DUMPER\.
//    Les #include "DMP_*.h" utilisent des chemins RELATIFS — aucun changement
//    nécessaire tant que les .h sont au même niveau que le .cpp.
//
//  ── INPUTS SIERRA CHART (sc.Input[]) ─────────────────────────────────────────
//
//    Input[0] : Symbole (ES=0 / NQ=1)        — sélecteur ES ou NQ
//    Input[1] : Répertoire de sortie          — chemin base données
//    Input[2] : RTH uniquement (Yes/No)       — filtrer hors-marché
//    Input[3] : Mode debug verbose (Yes/No)   — log chaque barre
//    Input[4] : Data Quality minimum %        — rejeter si trop de nulls
//
//  ── COMPILATION DANS SIERRA CHART ────────────────────────────────────────────
//
//    1. Tous les fichiers DMP_*.h + DMP_Main.cpp sont dans :
//       D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER
//
//    2. Dans Sierra Chart : Analysis → Studies → Edit Study Data Files
//       → Cliquer "Add" → Naviguer vers :
//         D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER\DMP_Main.cpp
//       → ⚠️ NE PAS ajouter les .h — Sierra Chart les inclut automatiquement
//
//    3. Compiler (Build → Build All) :
//       Le study "MIA Data Dumper G3 — JSONL" apparaît dans la liste
//
//    4. Attacher l'étude à un chart 1-min ES ou NQ (footprint requis)
//
//    ⚠️ NOTE : Le bot MIA_Main.cpp reste dans le dossier parent
//       D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\MIA_Main.cpp
//       Les deux compilent INDÉPENDAMMENT — aucune dépendance croisée.
//
//  ── ARCHITECTURE ACSIL ───────────────────────────────────────────────────────
//
//  Sierra Chart appelle la fonction SCSFExport à chaque barre.
//  2 modes d'appel :
//    → sc.SetDefaults = true  : initialisation (sc.LastCallToFunction = 0)
//    → sc.SetDefaults = false : traitement normal barre par barre
//    → sc.LastCallToFunction  : fermeture / shutdown de l'étude
//
//  ACSIL est monothread par étude — pas de synchronisation nécessaire.
//  2 instances (ES + NQ) tournent en parallèle sur 2 charts différents.
//
//  ── FICHIERS GÉNÉRÉS ─────────────────────────────────────────────────────────
//
//    D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\YYYYMMDD_ES.jsonl
//    D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\YYYYMMDD_ES.meta.json
//    D:\TRADING_SIERRA_CHART_AUTO\DATA\NQ\YYYYMMDD_NQ.jsonl
//    D:\TRADING_SIERRA_CHART_AUTO\DATA\NQ\YYYYMMDD_NQ.meta.json
//
//  ── STRUCTURE INCLUDES ───────────────────────────────────────────────────────
//
//    DMP_Main.cpp                          (ce fichier)
//      └── DMP_ProfileShape.h              (G12 — forme profil)
//            └── DMP_Writer.h              (sérialisation JSONL)
//                  └── DMP_OpenType.h      (G9 — open type / day type)
//                        └── DMP_Transform.h   (G1-G10 — 168 features)
//                              └── DMP_HVN_LVN.h   (G11 — HVN/LVN session)
//                                    └── DMP_Reader.h   (lecture Sierra Chart)
//                                          └── DMP_Config.h   (constantes)
//                                                └── sierrachart.h
//
//  Auteur : MIA Trading System — v1.2 — 2026-03-01
//           v1.0 : version initiale (2026-02-28)
//           v1.1 : corrections bugs critiques (pipeline HVN, signature Transform)
//           v1.2 : relocalisation DUMPER/ — aucun changement de logique
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_ProfileShape.h" // Chaîne complète : ProfileShape→Writer→OpenType→Transform→HVN_LVN→Reader

SCDLLName("MIA_DMP_G3")

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — DÉCLARATION ACSIL (requis par Sierra Chart)
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_DMP_G3(SCStudyInterfaceRef sc)
{

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — SETDEFAULTS (initialisation une seule fois)
// ═══════════════════════════════════════════════════════════════════════════════

if (sc.SetDefaults) {
    sc.GraphName             = "MIA Data Dumper G3 — JSONL";
    sc.StudyDescription      = "Collecte 262 features ML en JSONL (G1-G14, Schema 3.7.2). "
                               "Attacher sur chart 1-min ES ou NQ (footprint requis). "
                               "Source: MIA_REFACTORED\\DUMPER\\";
    sc.AutoLoop              = 1;
    sc.GraphRegion           = 0;
    sc.DrawZeros             = 0;
    sc.UpdateAlways          = 1;

    // ⚠️ CRITIQUE — Copié de l'ancien dumper qui marchait :
    sc.CalculationPrecedence = LOW_PREC_LEVEL;  // Attendre que TOUTES les autres études soient calculées AVANT nous
    sc.MaintainAdditionalChartDataArrays = 1;   // Requis pour lire les charts liés (cross-chart)
    sc.MaintainVolumeAtPriceData         = 1;   // REQUIS pour G11 (HVN/LVN) et G12 (ProfileShape)

    // ── Input[0] : Symbole ────────────────────────────────────────────────────
    sc.Input[0].Name         = "Symbole (0=ES / 1=NQ)";
    sc.Input[0].SetDescription("0 = ES (E-mini S&P 500) | 1 = NQ (E-mini NASDAQ-100)");
    sc.Input[0].SetInt(0);
    sc.Input[0].SetIntLimits(0, 1);

    // ── Input[1] : Répertoire de sortie ───────────────────────────────────────
    sc.Input[1].Name         = "Repertoire de sortie";
    sc.Input[1].SetDescription("Chemin base des fichiers JSONL. "
                               "Sous-dossier ES\\ ou NQ\\ cree automatiquement.");
    sc.Input[1].SetString("D:\\TRADING_SIERRA_CHART_AUTO\\DATA");

    // ── Input[2] : RTH uniquement ─────────────────────────────────────────────
    sc.Input[2].Name         = "RTH uniquement (oui=1 / non=0)";
    sc.Input[2].SetDescription("1 = Ecrire seulement les barres 9h30-16h00 ET. "
                               "0 = Ecrire aussi overnight et pre-market.");
    sc.Input[2].SetInt(1);
    sc.Input[2].SetIntLimits(0, 1);

    // ── Input[3] : Mode debug ─────────────────────────────────────────────────
    sc.Input[3].Name         = "Mode debug verbose (oui=1 / non=0)";
    sc.Input[3].SetDescription("1 = Log chaque barre dans le journal Sierra Chart. "
                               "0 = Log uniquement les événements importants.");
    sc.Input[3].SetInt(0);
    sc.Input[3].SetIntLimits(0, 1);

    // ── Input[4] : Qualité de données minimum ─────────────────────────────────
    sc.Input[4].Name         = "Qualite min % (0=tout ecrire / 50=50% champs valides)";
    sc.Input[4].SetDescription("Rejeter les barres avec trop de champs invalides. "
                               "0 = pas de filtre. 50 = au moins 50% des 168 champs valides.");
    sc.Input[4].SetInt(0);
    sc.Input[4].SetIntLimits(0, 100);

    return;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — SHUTDOWN (fermeture propre)
// ═══════════════════════════════════════════════════════════════════════════════

if (sc.LastCallToFunction) {
    DMP_WriterClose(sc);
    const char* shutdown_sym = (sc.Input[0].GetInt() == 1) ? "NQ" : "ES";
    DMP_DebugLog(sc, shutdown_sym, "SHUTDOWN — Étude fermée proprement");
    return;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — GARDE-FOUS AVANT TRAITEMENT
// ═══════════════════════════════════════════════════════════════════════════════

// Pas connecté au serveur → rien à faire (copié de l'ancien dumper)
if (sc.ServerConnectionState != SCS_CONNECTED)
    return;

// ── GUARD 1 : Ignorer les barres historiques lors du chargement initial ──────
//  Avec AutoLoop=1 + UpdateAlways=1, SC itère sur TOUTES les barres à chaque tick.
//  On ne veut traiter que les 2 dernières barres (la fermante + la formante).
if (sc.Index < sc.ArraySize - 2)
    return;

// ── GUARD 2 : Écrire UNIQUEMENT quand une barre FERME ──────────────────────
//  C'est le mécanisme central de l'ancien dumper :
//    bar_closed = (sc.GetBarHasClosedStatus(i) == BHCS_BAR_HAS_CLOSED)
//
//  POURQUOI C'EST CRITIQUE :
//  Avec AutoLoop=1, quand barre N ferme → SC crée barre N+1 → ArraySize augmente.
//  Si on garde juste "sc.Index < sc.ArraySize - 1", la barre N fermée est SKIPPÉE
//  et la barre N+1 (formante, incomplète) est écrite x100 par minute.
//
//  Avec GetBarHasClosedStatus :
//    - Barre formante → BHCS_BAR_HAS_NOT_CLOSED → skip
//    - Barre fermée   → BHCS_BAR_HAS_CLOSED → on écrit 1 ligne = 1 barre 1-min
if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED)
    return;

// ── GUARD 3 : Déduplication par index de barre ─────────────────────────────
//  Même après bar close, SC peut rappeler la fonction pour la même barre.
//  On utilise PersistentInt pour tracker le dernier index écrit.
constexpr int DMP_P_LAST_BAR_WRITTEN = 93;  // Index PersistentInt (après 90-92 du Writer)
{
    int& last_bar = sc.GetPersistentInt(DMP_P_LAST_BAR_WRITTEN);
    if (sc.Index <= last_bar)
        return;
    last_bar = sc.Index;
}

// Barre minimale : au moins 10 barres pour avoir des données valides
if (sc.Index < 10)
    return;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — LECTURE DES PARAMÈTRES INPUTS
// ═══════════════════════════════════════════════════════════════════════════════

const bool is_nq        = (sc.Input[0].GetInt() == 1);
const char* base_path   = sc.Input[1].GetString();
const bool rth_only     = (sc.Input[2].GetInt() == 1);
const bool debug_mode   = (sc.Input[3].GetInt() == 1);
const int  quality_min  = sc.Input[4].GetInt();

const char* sym_name = is_nq ? "NQ" : "ES";

// ── LOG STARTUP (une seule fois) ─────────────────────────────────────────────
{
    static bool s_startup_logged = false;
    if (!s_startup_logged) {
        char msg[512];
        snprintf(msg, sizeof(msg),
            "STARTUP — sym=%s | Input[0]=%d | base=%s | rth_only=%d | debug=%d | quality=%d | chart#%d | sc.Symbol=%s | ArraySize=%d",
            sym_name, sc.Input[0].GetInt(), base_path, (int)rth_only,
            (int)debug_mode, quality_min, sc.ChartNumber, sc.Symbol.GetChars(), sc.ArraySize);
        DMP_DebugLog(sc, sym_name, msg);
        s_startup_logged = true;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — PIPELINE DE TRAITEMENT (6 étapes)
// ═══════════════════════════════════════════════════════════════════════════════

// Structures de données — allouées en local (stack) — ACSIL est monothread
DMP_RawData     r;
DMP_MLFeatures  f;

// ── ÉTAPE 1 : Lecture des charts liés ─────────────────────────────────────────
DMP_ReadAll(sc, r, is_nq);

// 🆕 FIX IB PROGRESSIF (30/03/2026) — Remplace scan backward + freeze
//   PROBLÈME : sc.High[i] pour barres passées cassé sur charts footprint.
//   FIX : Accumuler IB high/low progressivement via PersistentFloat.
//   A chaque barre fermée dans [09:30, 10:30] ET, on met à jour le running
//   max(high) / min(low) depuis sc.High[sc.Index] (barre courante = toujours OK).
//   Après 10:30, les valeurs sont figées automatiquement (plus de barres IB).
//
//   PersistentFloat slots: 117=ib_high, 118=ib_low, 119=ib_active
//   ib_active: 0=hors session / 1=IB en cours ou figé
{
    constexpr int DMP_PS_IB_HIGH   = 117;
    constexpr int DMP_PS_IB_LOW    = 118;
    constexpr int DMP_PS_IB_ACTIVE = 119;

    float& ib_h    = sc.GetPersistentFloat(DMP_PS_IB_HIGH);
    float& ib_l    = sc.GetPersistentFloat(DMP_PS_IB_LOW);
    float& ib_act  = sc.GetPersistentFloat(DMP_PS_IB_ACTIVE);

    // Reset quand on passe hors RTH (nouvelle journée)
    if (!r.is_rth_session) {
        if (ib_act != 0.0f) {
            ib_act = 0.0f;
            ib_h = DMP_INVALID;
            ib_l = DMP_INVALID;
        }
    }
    // Barre dans fenêtre IB [09:30, 10:30] ET → accumuler
    else if (r.is_rth_session && !r.ib_complete) {
        float bar_h = (float)sc.High[sc.Index];
        float bar_l = (float)sc.Low[sc.Index];
        if (std::isfinite(bar_h) && bar_h > 10.0f) {
            if (!DMP_IsPriceValid(ib_h) || bar_h > ib_h) ib_h = bar_h;
        }
        if (std::isfinite(bar_l) && bar_l > 10.0f) {
            if (!DMP_IsPriceValid(ib_l) || bar_l < ib_l) ib_l = bar_l;
        }
        ib_act = 1.0f;
    }
    // Après 10:30 ET, ib_act reste 1.0 → valeurs figées

    // Injecter dans r pour le reste du pipeline (Transform + OpenType)
    if (ib_act == 1.0f && DMP_IsPriceValid(ib_h) && DMP_IsPriceValid(ib_l)) {
        r.ib_high = ib_h;
        r.ib_low  = ib_l;
    }
}

// 🆕 BUG #14 FIX (05/03/2026) : open_cash = premier prix RTH, pas overnight
//   Le fix session VP (18:00 ET) a corrigé prev_vah/val mais cassé open_cash :
//   OHLC_SESSION.sg0 retourne maintenant l'open overnight (18:00) au lieu du 9:30.
//   Fix : capturer le premier prix quand is_rth_session passe à true.
{
    constexpr int DMP_PS_RTH_OPEN  = 120;
    constexpr int DMP_PS_RTH_SET   = 121;

    float& rth_open = sc.GetPersistentFloat(DMP_PS_RTH_OPEN);
    float& rth_set  = sc.GetPersistentFloat(DMP_PS_RTH_SET);

    if (r.is_rth_session && rth_set != 1.0f && DMP_IsPriceValid(r.price_close)) {
        // Premier tick RTH → capturer comme open cash
        rth_open = r.price_close;
        rth_set  = 1.0f;
    }

    if (rth_set == 1.0f) {
        // Écraser open_cash avec le vrai open RTH
        r.open_cash = rth_open;
    }

    // Reset hors RTH
    if (!r.is_rth_session && rth_set == 1.0f) {
        rth_set  = 0.0f;
        rth_open = DMP_INVALID;
    }
}

// Injecter le symbole dans DMP_MLFeatures
static_assert(sizeof(f.sym) >= 3, "f.sym trop petit");
f.sym[0] = sym_name[0];
f.sym[1] = sym_name[1];
f.sym[2] = '\0';

// ── ÉTAPE 2 : HVN/LVN session (G11) — AVANT DMP_Transform ────────────────────
//  ⚠️ ORDRE CRITIQUE : DMP_ComputeHVN_LVN() DOIT précéder DMP_Transform()
DMP_HVN_LVN_Result hvn_result;
DMP_HVN_LVN_Init(hvn_result);

{
    const bool is_new_bar = (sc.GetBarHasClosedStatus(sc.Index) == BHCS_BAR_HAS_CLOSED);
    DMP_ComputeHVN_LVN(
        sc,
        r.price_close,
        r.tick_size,
        is_new_bar,
        r.is_rth_session,
        hvn_result
    );
}

// ── ÉTAPE 3 : Calcul des 168 features ML ──────────────────────────────────────
// 🆕 BUG #12 FIX (05/03/2026) : prev_swing via PersistentFloat
//   Avant : DMP_INVALID passé → new_swing_high/low toujours 0
//   Après : swing_high/low stocké entre barres → détection changement
constexpr int DMP_PS_PREV_SWING_H = 115;
constexpr int DMP_PS_PREV_SWING_L = 116;
float prev_sh = sc.GetPersistentFloat(DMP_PS_PREV_SWING_H);
float prev_sl = sc.GetPersistentFloat(DMP_PS_PREV_SWING_L);

DMP_Transform(r, f, prev_sh, prev_sl, &hvn_result, DMP_INVALID, 0);

// Sauvegarder swing actuel pour la prochaine barre
if (DMP_IsPriceValid(r.swing_high))
    sc.GetPersistentFloat(DMP_PS_PREV_SWING_H) = r.swing_high;
if (DMP_IsPriceValid(r.swing_low))
    sc.GetPersistentFloat(DMP_PS_PREV_SWING_L) = r.swing_low;

// ── ÉTAPE 4 : Open Type / Day Type / Rule 80% (G9) ────────────────────────────
DMP_UpdateOpenType(sc, r, f);

// ── ÉTAPE 5 : Forme du profil Volume Profile (G12) ────────────────────────────
{
    constexpr int DMP_PS_LAST_CALC = 105;
    int last_calc = sc.GetPersistentInt(DMP_PS_LAST_CALC);

    // ⚠️ FIX 03/03/2026 : Cache persistant pour ProfileShape
    //   AVANT : seule 1 barre/5 avait les vraies valeurs, les 4 autres
    //   recevaient les defaults (shape=0, skew=0, poc=0.5, imbalance=1.0).
    //   Le ML voyait 80% de données corrompues sur ces 9 features.
    //   MAINTENANT : on recalcule toutes les 5 barres ET on persiste les
    //   résultats. Les barres intermédiaires lisent le cache.
    constexpr int DMP_PS_SHAPE       = 106;  // PersistentFloat indices 106-114
    constexpr int DMP_PS_SKEW        = 107;
    constexpr int DMP_PS_POC_POS     = 108;
    constexpr int DMP_PS_VOL_IMB     = 109;
    constexpr int DMP_PS_IS_DOUBLE   = 110;
    constexpr int DMP_PS_POC_SEP     = 111;
    constexpr int DMP_PS_SP_MID      = 112;
    constexpr int DMP_PS_SP_COUNT    = 113;
    constexpr int DMP_PS_HVN_DOM     = 114;

    // Recalculer toutes les 5 barres (histogramme coûteux)
    if (sc.Index - last_calc >= 5 || last_calc <= 0) {
        PS_ProfileAnalysis ps = PS_AnalyzeCurrentSession(sc);

        f.profile_shape        = ps.shape;
        f.profile_skew         = ps.skewness;
        f.poc_position         = ps.poc_position;
        f.volume_imbalance     = ps.volume_imbalance;
        f.is_double_dist       = (ps.shape == PS_B_DOUBLE) ? 1.0f : 0.0f;
        f.poc_separation_ticks = ps.poc_separation_ticks;
        f.single_print_mid     = (ps.single_print_mid > 0.0f) ? ps.single_print_mid : 0.0f;
        f.single_print_count   = (float)ps.single_print_count;
        f.profile_hvn_dominant = (ps.hvn_count > 0) ? ps.hvn_levels[0] : DMP_INVALID;

        // Persister dans le cache pour les barres intermédiaires
        sc.GetPersistentFloat(DMP_PS_SHAPE)     = f.profile_shape;
        sc.GetPersistentFloat(DMP_PS_SKEW)      = f.profile_skew;
        sc.GetPersistentFloat(DMP_PS_POC_POS)   = f.poc_position;
        sc.GetPersistentFloat(DMP_PS_VOL_IMB)   = f.volume_imbalance;
        sc.GetPersistentFloat(DMP_PS_IS_DOUBLE)  = f.is_double_dist;
        sc.GetPersistentFloat(DMP_PS_POC_SEP)   = f.poc_separation_ticks;
        sc.GetPersistentFloat(DMP_PS_SP_MID)    = f.single_print_mid;
        sc.GetPersistentFloat(DMP_PS_SP_COUNT)  = f.single_print_count;
        sc.GetPersistentFloat(DMP_PS_HVN_DOM)   = f.profile_hvn_dominant;

        if (debug_mode) PS_LogAnalysis(sc, ps);

        sc.GetPersistentInt(DMP_PS_LAST_CALC) = sc.Index;
    }
    else if (last_calc > 0) {
        // Barres intermédiaires : lire le cache au lieu des defaults
        f.profile_shape        = sc.GetPersistentFloat(DMP_PS_SHAPE);
        f.profile_skew         = sc.GetPersistentFloat(DMP_PS_SKEW);
        f.poc_position         = sc.GetPersistentFloat(DMP_PS_POC_POS);
        f.volume_imbalance     = sc.GetPersistentFloat(DMP_PS_VOL_IMB);
        f.is_double_dist       = sc.GetPersistentFloat(DMP_PS_IS_DOUBLE);
        f.poc_separation_ticks = sc.GetPersistentFloat(DMP_PS_POC_SEP);
        f.single_print_mid     = sc.GetPersistentFloat(DMP_PS_SP_MID);
        f.single_print_count   = sc.GetPersistentFloat(DMP_PS_SP_COUNT);
        f.profile_hvn_dominant = sc.GetPersistentFloat(DMP_PS_HVN_DOM);
    }
    // else: last_calc <= 0 = première barre → garder les defaults de DMP_Transform
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6B — RANGE TRADING FEATURES (07/03/2026)
// ═══════════════════════════════════════════════════════════════════════════════
//   momentum_3b/5b: prix - prix(i-3 / i-5) = filtre momentum prouvé +10% WR
//   cvd_bar_delta: variation CVD per-bar = divergence temps réel
//   vah/val_touches: nombre de touches des bornes VA dans les 20 dernières barres
//   bars_in_va: combien de barres consécutives le prix est dans la VA
{
    constexpr int DMP_PS_PREV_PRICE_3   = 128;
    constexpr int DMP_PS_PREV_PRICE_5   = 129;
    constexpr int DMP_PS_PREV_CVD       = 130;
    constexpr int DMP_PS_BARS_IN_VA     = 131;
    constexpr int DMP_PS_VAH_TOUCH_MASK = 94;   // PersistentInt
    constexpr int DMP_PS_VAL_TOUCH_MASK = 95;   // PersistentInt

    // ── MOMENTUM ──
    float prev_p3 = sc.GetPersistentFloat(DMP_PS_PREV_PRICE_3);
    float prev_p5 = sc.GetPersistentFloat(DMP_PS_PREV_PRICE_5);

    if (DMP_IsPriceValid(prev_p3) && DMP_IsPriceValid(r.price_close)) {
        f.momentum_3b = r.price_close - prev_p3;
    }
    if (DMP_IsPriceValid(prev_p5) && DMP_IsPriceValid(r.price_close)) {
        f.momentum_5b = r.price_close - prev_p5;
    }

    // Shift: p5 ← ancien p3, p3 ← prix courant
    sc.GetPersistentFloat(DMP_PS_PREV_PRICE_5) = prev_p3;
    sc.GetPersistentFloat(DMP_PS_PREV_PRICE_3) = r.price_close;

    // ── CVD BAR DELTA ──
    float prev_cvd = sc.GetPersistentFloat(DMP_PS_PREV_CVD);
    if (prev_cvd != 0.0f && DMP_IsValid(r.fpbs_cvd_day)) {
        f.cvd_bar_delta = r.fpbs_cvd_day - prev_cvd;
    }
    if (DMP_IsValid(r.fpbs_cvd_day)) {
        sc.GetPersistentFloat(DMP_PS_PREV_CVD) = r.fpbs_cvd_day;
    }

    // ── BARS IN VA ──
    float& bia = sc.GetPersistentFloat(DMP_PS_BARS_IN_VA);
    if (f.inside_cur_va > 0.5f) {
        bia += 1.0f;
    } else {
        bia = 0.0f;
    }
    f.bars_in_va = bia;

    // ── VAH / VAL TOUCHES (bitmask 20 bits) ──
    {
        int& vah_mask = sc.GetPersistentInt(DMP_PS_VAH_TOUCH_MASK);
        int& val_mask = sc.GetPersistentInt(DMP_PS_VAL_TOUCH_MASK);

        vah_mask = (vah_mask << 1) & 0xFFFFF;  // garder 20 bits
        val_mask = (val_mask << 1) & 0xFFFFF;

        if (DMP_IsValid(f.dist_cur_vah) && std::fabs(f.dist_cur_vah) < 15.0f) {
            vah_mask |= 1;
        }
        if (DMP_IsValid(f.dist_cur_val) && std::fabs(f.dist_cur_val) < 15.0f) {
            val_mask |= 1;
        }

        int vah_count = 0, val_count = 0;
        for (int b = 0; b < 20; b++) {
            if (vah_mask & (1 << b)) vah_count++;
            if (val_mask & (1 << b)) val_count++;
        }
        f.vah_touches_20b = (float)vah_count;
        f.val_touches_20b = (float)val_count;
    }

    // 🆕 FIX 09/03/2026 : PAS de reset hors RTH.
    // Le momentum, CVD delta, touches et bars_in_va doivent fonctionner
    // sur TOUTES les sessions (Asia, London, US).
    // Le bitmask touches se purge naturellement par le shift left (20 bits).
    // Le bars_in_va reset quand le prix sort de la VA (déjà codé ci-dessus).
    // Le momentum se calcule entre barres consécutives, peu importe la session.
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6C — RETEST TRACKING (10/03/2026)
// ═══════════════════════════════════════════════════════════════════════════════
//   Détecte les retests du swing high/low (double top/bottom).
//   Un retest = prix revient à ≤10 ticks du swing sans faire un nouveau swing.
//   Compte les retests, détecte la divergence delta, et tracks bars_since_retest.
{
    constexpr int DMP_PS_RETEST_H_COUNT = 132;  // Nb retests du swing high
    constexpr int DMP_PS_RETEST_L_COUNT = 133;  // Nb retests du swing low
    constexpr int DMP_PS_BARS_SINCE_RT_H = 134; // Barres depuis dernier retest high
    constexpr int DMP_PS_BARS_SINCE_RT_L = 135; // Barres depuis dernier retest low
    constexpr int DMP_PS_DELTA_AT_SH     = 136; // Delta cumulé quand swing high a été posé
    constexpr int DMP_PS_DELTA_AT_SL     = 137; // Delta cumulé quand swing low a été posé
    constexpr float RETEST_THRESHOLD     = 10.0f; // Ticks de proximité pour considérer un retest

    float& rt_h_count     = sc.GetPersistentFloat(DMP_PS_RETEST_H_COUNT);
    float& rt_l_count     = sc.GetPersistentFloat(DMP_PS_RETEST_L_COUNT);
    float& bars_since_rt_h = sc.GetPersistentFloat(DMP_PS_BARS_SINCE_RT_H);
    float& bars_since_rt_l = sc.GetPersistentFloat(DMP_PS_BARS_SINCE_RT_L);
    float& delta_at_sh    = sc.GetPersistentFloat(DMP_PS_DELTA_AT_SH);
    float& delta_at_sl    = sc.GetPersistentFloat(DMP_PS_DELTA_AT_SL);

    // ── SWING HIGH RETEST ──
    if (f.new_swing_high > 0.5f) {
        // Nouveau swing high → reset compteur, stocker delta
        rt_h_count = 0.0f;
        bars_since_rt_h = 0.0f;
        if (DMP_IsValid(r.fpbs_cvd_day)) delta_at_sh = r.fpbs_cvd_day;
    } else if (DMP_IsValid(f.dist_swing_high) && std::fabs(f.dist_swing_high) <= RETEST_THRESHOLD) {
        // Prix proche du swing high sans nouveau high = RETEST
        // Incrémenter seulement si on vient de loin (bars_since > 3)
        if (bars_since_rt_h > 3.0f || rt_h_count == 0.0f) {
            rt_h_count += 1.0f;
            bars_since_rt_h = 0.0f;
            // Delta divergence: CVD au retest < CVD au swing original = bearish divergence
            if (DMP_IsValid(r.fpbs_cvd_day) && delta_at_sh != 0.0f) {
                f.retest_high_delta_div = (r.fpbs_cvd_day < delta_at_sh) ? 1.0f : 0.0f;
            }
        }
    }
    bars_since_rt_h += 1.0f;

    // ── SWING LOW RETEST ──
    if (f.new_swing_low > 0.5f) {
        // Nouveau swing low → reset compteur, stocker delta
        rt_l_count = 0.0f;
        bars_since_rt_l = 0.0f;
        if (DMP_IsValid(r.fpbs_cvd_day)) delta_at_sl = r.fpbs_cvd_day;
    } else if (DMP_IsValid(f.dist_swing_low) && std::fabs(f.dist_swing_low) <= RETEST_THRESHOLD) {
        // Prix proche du swing low sans nouveau low = RETEST
        if (bars_since_rt_l > 3.0f || rt_l_count == 0.0f) {
            rt_l_count += 1.0f;
            bars_since_rt_l = 0.0f;
            // Delta divergence: CVD au retest > CVD au swing original = bullish divergence
            if (DMP_IsValid(r.fpbs_cvd_day) && delta_at_sl != 0.0f) {
                f.retest_low_delta_div = (r.fpbs_cvd_day > delta_at_sl) ? 1.0f : 0.0f;
            }
        }
    }
    bars_since_rt_l += 1.0f;

    // Écrire dans les features
    f.retest_high_count = rt_h_count;
    f.retest_low_count  = rt_l_count;
    f.bars_since_retest_high = (rt_h_count > 0.0f) ? bars_since_rt_h : DMP_INVALID;
    f.bars_since_retest_low  = (rt_l_count > 0.0f) ? bars_since_rt_l : DMP_INVALID;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6D — EDGE ZONE EXTENSION LINES TRACKER (10/03/2026)
// ═══════════════════════════════════════════════════════════════════════════════
//   L'API GetStudyLineUntilFutureIntersection ne fonctionne PAS pour les études
//   "Volume At Price Threshold Alert V2" (EDGE ZONES). Elle ne fonctionne que
//   pour "Color Bar Based On Alert Condition" (COLOR/ABSORB/TRIPLE).
//
//   Fix : on lit directement les subgraphs sg0-sg9 des EDGE studies.
//   Quand un sg contient un prix valide = nouvelle zone détectée.
//   On stocke les prix dans un buffer circulaire PersistentFloat.
//   Chaque barre, on invalide les zones traversées et on calcule la distance.
{
    constexpr int DMP_PS_EDGE_BUY_BASE  = 140;  // PersistentFloat 140-149: 10 EDGE BUY prices
    constexpr int DMP_PS_EDGE_SELL_BASE = 150;  // PersistentFloat 150-159: 10 EDGE SELL prices
    constexpr int DMP_PS_EDGE_BUY_IDX   = 160;  // PersistentFloat: write index BUY (0-9)
    constexpr int DMP_PS_EDGE_SELL_IDX  = 161;  // PersistentFloat: write index SELL (0-9)
    constexpr int N_EDGE_SLOTS = 10;

    const int chart_b = r.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int edge_buy_id  = r.is_nq ? DMP_Studies::NQ_BARRES::EDGE_BUY  : DMP_Studies::ES_BARRES::EDGE_BUY;
    const int edge_sell_id = r.is_nq ? DMP_Studies::NQ_BARRES::EDGE_SELL : DMP_Studies::ES_BARRES::EDGE_SELL;
    const float ts = 0.25f;  // tick size NQ et ES
    const float p  = r.price_close;

    float& buy_idx  = sc.GetPersistentFloat(DMP_PS_EDGE_BUY_IDX);
    float& sell_idx = sc.GetPersistentFloat(DMP_PS_EDGE_SELL_IDX);

    // ── A. Détecter nouvelles zones EDGE (scanner sg0-sg9) ──
    // Quand l'étude VAPAT V2 fire, les subgraphs contiennent les prix des zones.
    // On scanne les 10 premiers subgraphs pour trouver des prix valides.
    // BUY zones :
    for (int sg = 0; sg < 10; sg++) {
        SCFloatArray arr;
        sc.GetStudyArrayFromChartUsingID(chart_b, edge_buy_id, sg, arr);
        int sz = (int)arr.GetArraySize();
        if (sz == 0) continue;
        float v = arr[sz - 1];
        if (!std::isfinite(v) || v < 1000.0f) continue;
        bool already = false;
        for (int s = 0; s < N_EDGE_SLOTS; s++) {
            if (std::fabs(sc.GetPersistentFloat(DMP_PS_EDGE_BUY_BASE + s) - v) < 1.0f) { already = true; break; }
        }
        if (!already) {
            int idx = (int)buy_idx % N_EDGE_SLOTS;
            sc.GetPersistentFloat(DMP_PS_EDGE_BUY_BASE + idx) = v;
            buy_idx += 1.0f;
        }
    }
    // SELL zones :
    for (int sg = 0; sg < 10; sg++) {
        SCFloatArray arr;
        sc.GetStudyArrayFromChartUsingID(chart_b, edge_sell_id, sg, arr);
        int sz = (int)arr.GetArraySize();
        if (sz == 0) continue;
        float v = arr[sz - 1];
        if (!std::isfinite(v) || v < 1000.0f) continue;
        bool already = false;
        for (int s = 0; s < N_EDGE_SLOTS; s++) {
            if (std::fabs(sc.GetPersistentFloat(DMP_PS_EDGE_SELL_BASE + s) - v) < 1.0f) { already = true; break; }
        }
        if (!already) {
            int idx = (int)sell_idx % N_EDGE_SLOTS;
            sc.GetPersistentFloat(DMP_PS_EDGE_SELL_BASE + idx) = v;
            sell_idx += 1.0f;
        }
    }

    // ── B. Invalider les zones traversées ──
    // BUY zone (support) : invalidée quand prix passe AU-DESSOUS (-10 ticks de marge)
    // SELL zone (résistance) : invalidée quand prix passe AU-DESSUS (+10 ticks de marge)
    constexpr float CROSS_MARGIN = 10.0f;  // ticks de marge avant invalidation
    for (int s = 0; s < N_EDGE_SLOTS; s++) {
        float& buy_px = sc.GetPersistentFloat(DMP_PS_EDGE_BUY_BASE + s);
        if (buy_px > 1000.0f && p < buy_px - CROSS_MARGIN * ts) {
            buy_px = 0.0f;  // Support cassé
        }
        float& sell_px = sc.GetPersistentFloat(DMP_PS_EDGE_SELL_BASE + s);
        if (sell_px > 1000.0f && p > sell_px + CROSS_MARGIN * ts) {
            sell_px = 0.0f;  // Résistance cassée
        }
    }

    // ── C. Trouver la zone la plus proche ──
    float nearest_buy  = DMP_INVALID;
    float min_dist_buy = 1e30f;
    float nearest_sell = DMP_INVALID;
    float min_dist_sell = 1e30f;

    for (int s = 0; s < N_EDGE_SLOTS; s++) {
        float buy_px = sc.GetPersistentFloat(DMP_PS_EDGE_BUY_BASE + s);
        if (buy_px > 1000.0f) {
            float d_abs = std::fabs(buy_px - p);
            if (d_abs < min_dist_buy) {
                min_dist_buy = d_abs;
                nearest_buy = buy_px;
            }
        }
        float sell_px = sc.GetPersistentFloat(DMP_PS_EDGE_SELL_BASE + s);
        if (sell_px > 1000.0f) {
            float d_abs = std::fabs(sell_px - p);
            if (d_abs < min_dist_sell) {
                min_dist_sell = d_abs;
                nearest_sell = sell_px;
            }
        }
    }

    // Écrire la distance en ticks (écrase le résultat de DMP_ReadNearestExtensionLine qui retourne DMP_INVALID)
    if (DMP_IsPriceValid(nearest_buy)) {
        f.dist_ext_edge_buy = (nearest_buy - p) / ts;
    }
    if (DMP_IsPriceValid(nearest_sell)) {
        f.dist_ext_edge_sell = (nearest_sell - p) / ts;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6E — RVOL (Relative Volume) — 12/03/2026
// ═══════════════════════════════════════════════════════════════════════════════
//   PersistentFloat slots 170-192 : ring buffer 20 barres + stats.
//   Confirmé: PersistentFloat = STL map interne, pas de limite de slots.
//   Validé 17/03/2026: 470 valeurs uniques, min=0.088, max=7.125.
{
    constexpr int DMP_RVOL_SUM       = 170;
    constexpr int DMP_RVOL_SUM_SQ    = 171;
    constexpr int DMP_RVOL_COUNT     = 172;
    constexpr int DMP_RVOL_RING_BASE = 173;
    constexpr int DMP_RVOL_LOOKBACK  = 20;
    constexpr float DMP_RVOL_SPIKE   = 2.0f;

    float total_vol = f.total_vol;
    if (total_vol <= 0.0f || total_vol > 1e8f) total_vol = 0.0f;

    float vol_sum    = sc.GetPersistentFloat(DMP_RVOL_SUM);
    float vol_sum_sq = sc.GetPersistentFloat(DMP_RVOL_SUM_SQ);
    float vol_count  = sc.GetPersistentFloat(DMP_RVOL_COUNT);

    int idx = ((int)vol_count) % DMP_RVOL_LOOKBACK;

    float old_val = sc.GetPersistentFloat(DMP_RVOL_RING_BASE + idx);

    if (vol_count >= DMP_RVOL_LOOKBACK) {
        vol_sum    -= old_val;
        vol_sum_sq -= old_val * old_val;
    }

    vol_sum    += total_vol;
    vol_sum_sq += total_vol * total_vol;
    sc.GetPersistentFloat(DMP_RVOL_RING_BASE + idx) = total_vol;

    vol_count += 1.0f;
    sc.GetPersistentFloat(DMP_RVOL_SUM)    = vol_sum;
    sc.GetPersistentFloat(DMP_RVOL_SUM_SQ) = vol_sum_sq;
    sc.GetPersistentFloat(DMP_RVOL_COUNT)  = vol_count;

    int n = (vol_count < (float)DMP_RVOL_LOOKBACK) ? (int)vol_count : DMP_RVOL_LOOKBACK;
    if (n >= 5) {
        float vol_avg = vol_sum / (float)n;
        if (vol_avg > 0.0f) {
            f.rvol = total_vol / vol_avg;

            float variance = (vol_sum_sq / (float)n) - (vol_avg * vol_avg);
            if (variance > 0.0f) {
                float vol_std = (float)sqrt((double)variance);
                f.rvol_zscore = (total_vol - vol_avg) / vol_std;
            }
        }

        if (f.rvol >= DMP_RVOL_SPIKE) {
            float delta_pct = f.delta_pct;
            float finish    = f.finish_strength;

            if (delta_pct > 0.05f)  f.rvol_buy  = 1.0f;
            if (delta_pct < -0.05f) f.rvol_sell = 1.0f;

            if (delta_pct < -0.05f && finish > 20.0f)
                f.rvol_absorb_buy = 1.0f;
            if (delta_pct > 0.05f && finish < -20.0f)
                f.rvol_absorb_sell = 1.0f;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — FILTRE QUALITÉ DE DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════

if (quality_min > 0) {
    // Fix audit 09/04 : 262 cols dans schema 3.7.2 (etait 168, quality_filter inactif)
    const int total_fields  = 262;
    const int valid_pct = (f.n_valid_fields * 100) / total_fields;
    if (valid_pct < quality_min) {
        if (debug_mode) {
            char msg[128];
            snprintf(msg, sizeof(msg),
                "QUALITY SKIP — barre #%d qualité %d%% < min %d%%",
                sc.Index, valid_pct, quality_min);
            DMP_DebugLog(sc, sym_name, msg);
        }
        return;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — ÉCRITURE JSONL
// ═══════════════════════════════════════════════════════════════════════════════

bool write_ok = DMP_WriteRow(sc, f, base_path, rth_only);

if (!write_ok) {
    DMP_DebugLog(sc, sym_name, "WRITE FAIL — DMP_WriteRow a retourné false");
    return;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — DEBUG LOG (si activé)
// ═══════════════════════════════════════════════════════════════════════════════

if (debug_mode) {
    // Log toutes les 10 barres (éviter flood)
    static int s_write_count = 0;
    s_write_count++;
    if (s_write_count % 10 == 1) {
        const int nulls = 262 - f.n_valid_fields;
        char msg[384];
        snprintf(msg, sizeof(msg),
            "WRITE OK #%d — %s | bar#%d | prix=%.2f | ts=%lld | session=%.0f(%s) | contract=%s | %s | nulls=%d/%d",
            s_write_count, sym_name, sc.Index,
            DMP_IsValid((float)r.price_close) ? r.price_close : 0.0f,
            f.ts, f.session,
            f.session < 0.5f ? "Asia" : f.session < 1.5f ? "London" : "US",
            f.contract,
            DMP_OT_Name(f.open_type),
            nulls, 168);
        DMP_DebugLog(sc, sym_name, msg);
    }
}

} // fin scsf_MIA_DMP_G3

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Main.cpp — v1.2 (2026-03-01)
//
//   Historique :
//     v1.0 (2026-02-28) : version initiale
//     v1.1 (2026-02-28) : corrections bugs critiques — pipeline HVN avant
//                          Transform, signature DMP_Transform, PersistentInt
//     v1.2 (2026-03-01) : relocalisation vers DUMPER/
//                          Nouveau chemin: MIA_REFACTORED\DUMPER\DMP_Main.cpp
//                          Aucun changement de logique — documentation mise à jour
//
//   Compilation Sierra Chart :
//     Analysis → Studies → Edit Study Data Files → Add :
//     D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\DUMPER\DMP_Main.cpp
// ═══════════════════════════════════════════════════════════════════════════════
