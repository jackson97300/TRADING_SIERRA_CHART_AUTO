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
//    1. Copier ce fichier et tous les DMP_*.h dans le même dossier
//    2. Dans Sierra Chart : Analysis → Studies → Edit Study Data Files
//    3. Ajouter DMP_Main.cpp à la liste des fichiers à compiler
//    4. Compiler : le symbole "MIA_DMP_G3" apparaît dans la liste des études
//    5. Attacher l'étude à un chart 1-min ES ou NQ
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
//    DMP_Main.cpp
//      └── DMP_ProfileShape.h
//            └── DMP_Writer.h
//                  └── DMP_OpenType.h
//                        └── DMP_Transform.h
//                              └── DMP_HVN_LVN.h
//                                    └── DMP_Reader.h
//                                          └── DMP_Config.h
//                                                └── sierrachart.h
//
//  Auteur : MIA Trading System — v1.1 — 2026-02-28 (corrections bugs critiques)
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_ProfileShape.h" // Chaîne complète : ProfileShape→Writer→OpenType→Transform→HVN_LVN→Reader

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — DÉCLARATION ACSIL (requis par Sierra Chart)
// ═══════════════════════════════════════════════════════════════════════════════

SCSFExport scsf_MIA_DMP_G3(SCStudyInterfaceRef sc)
{

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — SETDEFAULTS (initialisation une seule fois)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Sierra Chart appelle avec sc.SetDefaults = true en premier.
//  On définit ici les paramètres visibles dans l'interface Sierra Chart.

if (sc.SetDefaults) {
    sc.GraphName             = "MIA Data Dumper G3 — JSONL";
    sc.StudyDescription      = "Collecte 168 features ML en JSONL (G1-G12). "
                               "Attacher sur chart 1-min ES ou NQ (footprint requis).";
    sc.AutoLoop              = 1;   // Sierra Chart appelle à chaque nouvelle barre
    sc.GraphRegion           = 0;   // Affichage dans la même région que le prix
    sc.DrawZeros             = 0;   // Ne pas dessiner les zéros
    sc.UpdateAlways          = 1;   // Mettre à jour sur chaque barre (pas seulement nouvelles)
    sc.MaintainAdditionalChartDataArrays = 1; // Accès GetStudyArrayFromChartUsingID
    sc.MaintainVolumeAtPriceData         = 1; // 01/03/2026: REQUIS pour sc.VolumeAtPriceForBars
                                              // Sans ce flag : G11 (HVN/LVN) et G12 (ProfileShape) = INVALID

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

    return; // Fin SetDefaults — Sierra Chart appellera ensuite normalement
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — SHUTDOWN (fermeture propre)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Sierra Chart appelle avec sc.LastCallToFunction = 1 à la fermeture.
//  On flush et ferme le fichier JSONL proprement.

if (sc.LastCallToFunction) {
    DMP_WriterClose(sc);
    sc.AddMessageToLog("[DMP_Main] Étude fermée proprement.", 0);
    return;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — GARDE-FOUS AVANT TRAITEMENT
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Sierra Chart peut appeler sur des barres historiques (recalcul).
//  On saute tout sauf la DERNIÈRE barre pour éviter de réécrire l'historique.
//
//  ⚠️  CRITIQUE : sc.Index != sc.ArraySize - 1 → barre historique → SKIP
//                 sc.GetBarHasClosedStatus() → 1 si barre clôturée

// Sauter les barres historiques (recalcul) — n'écrire que la barre en cours
if (sc.Index < sc.ArraySize - 1)
    return;

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

// Nom du symbole pour le writer et les logs
const char* sym_name = is_nq ? "NQ" : "ES";

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — PIPELINE DE TRAITEMENT (6 étapes)
// ═══════════════════════════════════════════════════════════════════════════════

// Structures de données — allouées en local (stack) — ACSIL est monothread
// sizeof(DMP_RawData) ≈ 2 KB, sizeof(DMP_MLFeatures) ≈ 680 B → pas de problème stack
DMP_RawData     r;
DMP_MLFeatures  f;

// ── ÉTAPE 1 : Lecture des charts liés ─────────────────────────────────────────
//  DMP_ReadAll() lit les 13 charts Sierra Chart via GetStudyArrayFromChartUsingID.
//  Initialise tous les champs DMP_INVALID avant lecture.
DMP_ReadAll(sc, r, is_nq);

// Injecter le symbole dans DMP_MLFeatures (DMP_ReadAll ne connaît pas sym_name)
static_assert(sizeof(f.sym) >= 3, "f.sym trop petit");
f.sym[0] = sym_name[0];  // 'E' ou 'N'
f.sym[1] = sym_name[1];  // 'S' ou 'Q'
f.sym[2] = '\0';

// ── ÉTAPE 2 : HVN/LVN session (G11) — AVANT DMP_Transform ────────────────────
//  ⚠️  ORDRE CRITIQUE : DMP_ComputeHVN_LVN() doit précéder DMP_Transform() pour
//  que les champs G11 soient remplis via le paramètre hvn_lvn (pointeur optionnel).
//  Si appelé après, DMP_Transform reçoit nullptr et G11 reste à INVALID.
//
//  Détection nouvelle barre fermée : sc.GetBarHasClosedStatus() retourne
//  BHCS_BAR_HAS_CLOSED sur la dernière barre complète.
DMP_HVN_LVN_Result hvn_result;
DMP_HVN_LVN_Init(hvn_result);  // Initialiser à INVALID (sécurité)

{
    const bool is_new_bar = (sc.GetBarHasClosedStatus(sc.Index) == BHCS_BAR_HAS_CLOSED);
    DMP_ComputeHVN_LVN(
        sc,
        r.price_close,      // Prix courant
        r.tick_size,        // Tick size du symbole
        is_new_bar,         // Recalcul seulement sur barre fermée
        r.is_rth_session,   // RTH uniquement
        hvn_result          // Résultat — sera passé à DMP_Transform
    );
}

// ── ÉTAPE 3 : Calcul des 168 features ML ──────────────────────────────────────
//  ✅  CORRIGÉ : signature correcte DMP_Transform(r, f, ...) — pas DMP_Transform(sc, r, f)
//  ✅  CORRIGÉ : &hvn_result passé en paramètre pour remplir G11 correctement
//
//  Paramètres optionnels :
//    prev_swing_high / prev_swing_low → DMP_INVALID (pas de trade actif)
//    hvn_lvn                          → &hvn_result (calculé à l'étape 2)
//    tp_target / direction            → DMP_INVALID / 0 (pas de trade actif)
DMP_Transform(r, f, DMP_INVALID, DMP_INVALID, &hvn_result, DMP_INVALID, 0);

// ── ÉTAPE 4 : Open Type / Day Type / Rule 80% (G9) ────────────────────────────
//  DMP_UpdateOpenType() classe l'ouverture, la journée, et surveille ODF.
//  Utilise des persistants sc.GetPersistentFloat(80-89) inter-barres.
DMP_UpdateOpenType(sc, r, f);

// ── ÉTAPE 5 : Forme du profil Volume Profile (G12) ────────────────────────────
//  PS_AnalyzeCurrentSession() classifie la forme D/P/b/B depuis le début de session.
//  Utilise sc.VolumeAtPriceForBars pour l'histogramme complet.
//  ✅  CORRIGÉ : GetPersistentInt(105) au lieu de static (évite partage ES↔NQ)
//               static serait partagé entre les 2 instances sur 2 charts différents.
{
    constexpr int DMP_PS_LAST_CALC = 105;  // Index libre — hors plages HVN(50-74)
                                            // OpenType(80-89) Writer(90-92) PS(100-104)
    int last_calc = sc.GetPersistentInt(DMP_PS_LAST_CALC);

    // Recalculer seulement toutes les 5 barres (performance — histogramme coûteux)
    if (sc.Index - last_calc >= 5 || last_calc <= 0) {
        PS_ProfileAnalysis ps = PS_AnalyzeCurrentSession(sc);

        // Injecter les 9 features G12 dans DMP_MLFeatures
        f.profile_shape        = ps.shape;
        f.profile_skew         = ps.skewness;
        f.poc_position         = ps.poc_position;
        f.volume_imbalance     = ps.volume_imbalance;
        f.is_double_dist       = (ps.shape == PS_B_DOUBLE) ? 1.0f : 0.0f;
        f.poc_separation_ticks = ps.poc_separation_ticks;
        f.single_print_mid     = (ps.single_print_mid > 0.0f) ? ps.single_print_mid : 0.0f;
        f.single_print_count   = (float)ps.single_print_count;
        f.profile_hvn_dominant = (ps.hvn_count > 0) ? ps.hvn_levels[0] : DMP_INVALID;

        if (debug_mode) PS_LogAnalysis(sc, ps);

        // ✅  CORRIGÉ : sauvegarder dans PersistentInt (isolé par instance)
        sc.GetPersistentInt(DMP_PS_LAST_CALC) = sc.Index;
    }
    // Entre les recalculs : f.profile_* garde les valeurs du dernier calcul.
    // Comportement correct — la forme du profil ne change pas en 1-5 minutes.
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — FILTRE QUALITÉ DE DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rejeter les barres avec trop de champs INVALID.
//  Ex : si les charts liés ne sont pas chargés, 90% des champs sont null.
//  quality_min=0 → pas de filtre (tout écrire, y compris barres dégradées).

if (quality_min > 0) {
    // CalcDataQuality() est appelé dans DMP_Transform → f.n_valid_fields est peuplé
    const int total_fields  = 168;  // 159 + 9 G12 ProfileShape
    const int valid_pct = (f.n_valid_fields * 100) / total_fields;
    if (valid_pct < quality_min) {
        if (debug_mode) {
            char msg[128];
            snprintf(msg, sizeof(msg),
                "[DMP_Main] Skip barre #%d — qualité %d%% < min %d%%",
                sc.Index, valid_pct, quality_min);
            sc.AddMessageToLog(msg, 0);
        }
        return; // Barre rejetée — pas d'écriture
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — ÉCRITURE JSONL
// ═══════════════════════════════════════════════════════════════════════════════
//
//  DMP_WriteRow() gère :
//    - Rotation automatique du fichier par jour
//    - Écriture du meta.json (une fois par session)
//    - Filtre RTH si rth_only=true
//    - Flush tous les 5 barres (protection crash)

bool write_ok = DMP_WriteRow(sc, f, base_path, rth_only);

if (!write_ok) {
    // Erreur d'écriture — loggée dans DMP_WriteRow, on ne loggue pas deux fois
    return;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — DEBUG LOG (si activé)
// ═══════════════════════════════════════════════════════════════════════════════

if (debug_mode) {
    // Log résumé de la barre : barre#, prix, open_type, n_nulls
    const int nulls = 168 - f.n_valid_fields;
    char msg[256];
    snprintf(msg, sizeof(msg),
        "[DMP_Main] %s | bar#%d | prix=%.2f | %s | day=%s | r80=%.0f | nulls=%d/%d",
        sym_name, sc.Index,
        DMP_IsValid((float)r.price_close) ? r.price_close : 0.0f,
        DMP_OT_Name(f.open_type),
        (int)f.day_type==0?"NonTrend":(int)f.day_type==1?"Normal":
        (int)f.day_type==2?"NormVar":(int)f.day_type==3?"Neutral":"Trend",
        f.rule_80pct,
        nulls, 168);
    sc.AddMessageToLog(msg, 0);
}

// ── Fin du cycle pour cette barre ─────────────────────────────────────────────
// Sierra Chart appellera à nouveau pour la prochaine barre.

} // fin scsf_MIA_DMP_G3

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Main.cpp — v1.1 (corrections: DMP_Config.h, pipeline HVN avant Transform,
//                           signature DMP_Transform, PersistentInt PS_LAST_CALC)
// ═══════════════════════════════════════════════════════════════════════════════
