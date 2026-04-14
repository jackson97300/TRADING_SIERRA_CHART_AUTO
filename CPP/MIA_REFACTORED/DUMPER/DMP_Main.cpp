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

#include "DMP_Pipeline.h" // chaine complete : Pipeline -> ProfileShape -> ... -> Reader -> Config

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
    sc.StudyDescription      = "Collecte 266 features ML en JSONL (G1-G14, Schema 3.7.3). "
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
//  En mode LIVE : on ne traite que les 2 dernières barres (fermante + formante).
//  En mode BACKFILL (Full Recalc) : on traite TOUTES les barres pour regenerer
//  l'historique JSONL. sc.IsFullRecalculation est mis a 1 par SC pendant
//  "Studies -> Recalculate -> Full Recalculation" et remis a 0 apres.
//  Fix 2026-04-14 pour permettre le backfill via Full Recalc.
if (!sc.IsFullRecalculation && sc.Index < sc.ArraySize - 2)
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

// ===============================================================================
// SECTION 6 - APPEL PIPELINE (extrait dans DMP_Pipeline.h - refactor 2026-04-14)
// ===============================================================================
//
//   Le pipeline complet (580 lignes) est dans DMP_ProcessBarPipeline().
//   Live et backfill partagent la meme fonction -> zero duplication, zero derive.
//
//   backfill_mode = FALSE (live) : DMP_WriteRow fait append pur, jamais truncate.
//   C'est le caller (ici scsf_MIA_DMP_G3) qui decide, pas le Writer.
DMP_ProcessBarPipeline(sc, is_nq, sym_name, base_path, rth_only, debug_mode, quality_min,
                       /*backfill_mode=*/false);

} // fin scsf_MIA_DMP_G3


// ═══════════════════════════════════════════════════════════════════════════════
// STUDY #2 — MIA BACKFILL DUMPER (rejeu historique via Full Recalc)
// ═══════════════════════════════════════════════════════════════════════════════
//
//   Cette study est independante du DMP live. Elle sert UNIQUEMENT a rejouer
//   l'historique d'un .scid deja present dans Sierra Chart, pour generer
//   retrospectivement des fichiers JSONL equivalents a ceux du live.
//
//   DIFFERENCES vs scsf_MIA_DMP_G3 :
//     - PAS de Garde 1 (sc.Index < ArraySize - 2)  → traite toutes les barres
//     - PAS de Garde 3 (dedup last_bar)            → rejoue tout l'historique
//     - PAS de check ServerConnectionState          → fonctionne offline
//     - SAFETY obligatoire : Input[1] doit contenir "BACKFILL" sinon refus
//     - Meme pipeline (DMP_ProcessBarPipeline) → features strictement identiques
//
//   USAGE :
//     1. Cloner un chart 1-min ES ou NQ avec toutes les etudes dependances
//     2. Sur le clone : supprimer "MIA Data Dumper G3" et ajouter ce study
//     3. Input[1] = chemin SEPARE avec "BACKFILL" dans le nom
//        (defaut: C:\TRADING_SIERRA_CHART_AUTO\DATA_BACKFILL)
//     4. Chart Settings > Data Limiting > Days To Load = 250 (ou plus)
//     5. Apply → SC recalc → la study ecrit JSONL pour chaque jour historique
//     6. Verifier log : "FILE OPEN OK ... mode=TRUNCATE(backfill)"
//     7. Une fois fini, fermer le chart clone (on n'en a plus besoin)
//
//   SAFETY NET :
//     - Double verification du path BACKFILL (ici + dans DMP_WR_Open)
//     - Si path ne contient pas BACKFILL → logge une erreur et return
//     - Si DMP live tourne en parallele sur un autre chart, il n'est pas
//       affecte (chart different = PersistentFloat different = WriterState different)
//
//   Auteur : MIA Trading System — 2026-04-14 (refactor Option B)
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_Backfill_Dumper(SCStudyInterfaceRef sc)
{

// ── SetDefaults ──────────────────────────────────────────────────────────────
if (sc.SetDefaults) {
    sc.GraphName        = "MIA Backfill Dumper — JSONL historique";
    sc.StudyDescription = "Rejoue l'historique du .scid pour generer JSONL retrospectifs. "
                          "A utiliser sur un CHART CLONE dedie. "
                          "Output: DATA_BACKFILL/ES ou DATA_BACKFILL/NQ (chemin DOIT contenir BACKFILL).";
    sc.AutoLoop              = 1;
    sc.GraphRegion           = 0;
    sc.DrawZeros             = 0;
    sc.UpdateAlways          = 1;
    sc.CalculationPrecedence = LOW_PREC_LEVEL;
    sc.MaintainAdditionalChartDataArrays = 1;
    sc.MaintainVolumeAtPriceData         = 1;

    sc.Input[0].Name         = "Symbole (0=ES / 1=NQ)";
    sc.Input[0].SetDescription("0 = ES (E-mini S&P 500) | 1 = NQ (E-mini NASDAQ-100)");
    sc.Input[0].SetInt(0);
    sc.Input[0].SetIntLimits(0, 1);

    sc.Input[1].Name         = "Repertoire sortie (DOIT contenir BACKFILL)";
    sc.Input[1].SetDescription("Safety: le path DOIT contenir 'BACKFILL' pour autoriser "
                               "le truncate. Defaut: C:\\TRADING_SIERRA_CHART_AUTO\\DATA_BACKFILL");
    sc.Input[1].SetString("C:\\TRADING_SIERRA_CHART_AUTO\\DATA_BACKFILL");

    sc.Input[2].Name         = "RTH uniquement (oui=1 / non=0)";
    sc.Input[2].SetDescription("1 = seulement 9h30-16h00 ET. 0 = aussi overnight et pre-market.");
    sc.Input[2].SetInt(1);
    sc.Input[2].SetIntLimits(0, 1);

    sc.Input[3].Name         = "Mode debug verbose (oui=1 / non=0)";
    sc.Input[3].SetDescription("1 = logue chaque 500 barres. 0 = log minimal.");
    sc.Input[3].SetInt(0);
    sc.Input[3].SetIntLimits(0, 1);

    sc.Input[4].Name         = "Qualite min % (0=tout ecrire / 50=au moins 50% champs valides)";
    sc.Input[4].SetDescription("Filtre qualite identique au live. 0 = aucun filtre.");
    sc.Input[4].SetInt(0);
    sc.Input[4].SetIntLimits(0, 100);

    return;
}

// ── Shutdown ─────────────────────────────────────────────────────────────────
if (sc.LastCallToFunction) {
    DMP_WriterClose(sc);
    const char* shutdown_sym = (sc.Input[0].GetInt() == 1) ? "NQ" : "ES";
    DMP_DebugLog(sc, shutdown_sym, "BACKFILL SHUTDOWN");
    return;
}

// ── GARDES (simplifiees vs live) ─────────────────────────────────────────────
//  PAS de Garde 1 : on traite TOUTES les barres (sc.Index 0 → ArraySize-1)
//  PAS de Garde 3 : pas de dedup last_bar (on veut rejouer)
//  PAS de check ServerConnection : fonctionne offline sur .scid local

// Garde 2 : barre fermee (identique au live, sinon on ecrirait des barres partielles)
if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED)
    return;

// Warmup minimal (identique au live)
if (sc.Index < 10)
    return;

// ── LECTURE INPUTS ───────────────────────────────────────────────────────────
const bool is_nq       = (sc.Input[0].GetInt() == 1);
const char* base_path  = sc.Input[1].GetString();
const bool rth_only    = (sc.Input[2].GetInt() == 1);
const bool debug_mode  = (sc.Input[3].GetInt() == 1);
const int  quality_min = sc.Input[4].GetInt();
const char* sym_name   = is_nq ? "NQ" : "ES";

// ── SAFETY CHECK : base_path DOIT contenir "BACKFILL" ────────────────────────
//  Protection stricte contre ecrasement du DATA/ live.
//  Si l'utilisateur pointe par erreur Input[1] vers DATA/ES/, on refuse tout write.
if (base_path == nullptr || base_path[0] == '\0') {
    static bool s_warned_empty = false;
    if (!s_warned_empty) {
        sc.AddMessageToLog("[Backfill] ERREUR: base_path vide, refus d'ecrire", 1);
        s_warned_empty = true;
    }
    return;
}
if (strstr(base_path, "BACKFILL") == nullptr &&
    strstr(base_path, "backfill") == nullptr) {
    static bool s_warned_path = false;
    if (!s_warned_path) {
        char msg[384];
        snprintf(msg, sizeof(msg),
            "[Backfill] SAFETY REFUS: base_path '%s' ne contient pas 'BACKFILL'. "
            "Corrigez Input[1] pour proteger DATA/ live.", base_path);
        sc.AddMessageToLog(msg, 1);
        s_warned_path = true;
    }
    return;
}

// ── LOG STARTUP (une seule fois par session) ─────────────────────────────────
{
    static bool s_backfill_startup_logged = false;
    if (!s_backfill_startup_logged) {
        char msg[512];
        snprintf(msg, sizeof(msg),
            "BACKFILL STARTUP — sym=%s | base=%s | rth_only=%d | debug=%d | quality=%d | chart#%d | ArraySize=%d",
            sym_name, base_path, (int)rth_only, (int)debug_mode, quality_min,
            sc.ChartNumber, sc.ArraySize);
        DMP_DebugLog(sc, sym_name, msg);
        s_backfill_startup_logged = true;
    }
}

// ── APPEL PIPELINE PARTAGE (meme code que le live) ───────────────────────────
// Les features calculees par cette fonction sont STRICTEMENT IDENTIQUES a
// celles du live, car c'est le meme code source (DMP_Pipeline.h).
//
// backfill_mode = TRUE : DMP_WriteRow va tronquer le fichier au 1er write de
// chaque jour (fopen "w"), ce qui rend le backfill idempotent. Le Writer
// verifie en plus que base_path contient "BACKFILL" (defense niveau 2).
DMP_ProcessBarPipeline(sc, is_nq, sym_name, base_path, rth_only, debug_mode, quality_min,
                       /*backfill_mode=*/true);

} // fin scsf_MIA_Backfill_Dumper


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
