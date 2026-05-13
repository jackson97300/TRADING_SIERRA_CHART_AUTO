// =============================================================================
// VIX_Lite.cpp — MIA Trading System V2 — DLL séparée VIX + MenthorQ Gamma VIX
// =============================================================================
//
// Objectif : dump du PRIX VIX courant + 17 niveaux MenthorQ Gamma sur VIX
// à chaque barre fermée (1/min). Permet à terme de supprimer la dépendance
// au DMP C++ full pour les features VIX dans le pipeline V4 / DMP++ Databento.
//
// Différence avec MQ_Lite (ES/NQ/GC = levels-only) :
//   MQ_Lite écrit ~5 lignes/jour quand un niveau MenthorQ change.
//   VIX_Lite écrit 1 ligne/min car vix_level varie en continu (RTH only,
//   figé hors RTH = limite CBOE intrinsèque, pas Sierra).
//
// 20 valeurs dumpées :
//   1 prix     : vix_level (close de la barre courante du chart hôte)
//   19 niveaux MenthorQ Gamma VIX :
//     vix_call (sg0), vix_put (sg1), vix_hvl (sg2),
//     vix_1d_min (sg3), vix_1d_max (sg4),
//     vix_call_0dte (sg5), vix_put_0dte (sg6), vix_hvl_0dte (sg7),
//     vix_gamma_wall_0dte (sg8), vix_gex[10] (sg9..sg18)
//
// Fallback MenthorQ fusion (v1.3) : si HVL_0DTE/Gamma_Wall_0DTE vides ET
// Put_0DTE/Call_0DTE valides → recopier les valeurs (collision MenthorQ qui
// fusionne visuellement les labels et vide le subgraph secondaire).
//
// Trigger d'écriture :
//   Chaque barre fermée du chart hôte (1/min en mode 1-Min). Pas de dedup.
//   Skip si déjà écrit pour cette barre (PersistentInt P_LAST_BAR_IDX).
//
// Output Hive : D:\TRADING_SIERRA_CHART_AUTO\DATA\vix_levels\
//                year=YYYY\month=M\day=D\vix.jsonl
//
// Architecture :
//   - DLL séparée de MQ_Lite et du DMP full (si plante, autres continuent).
//   - 1 seul SCSFExport scsf_MIA_VIX_Lite à attacher sur Chart 15 (VIX_CGI[M])
//   - Helpers VXL_* copies de MQL_* (drift accepté documenté)
//
// Schema : "vix_levels_1.0"
//
// Auteur : MIA Trading System V2
//   v1.0 (2026-05-13) : version initiale + P0 fixes review code-reviewer
//                       (vix_level via GetChartBaseData, VIX_MQ_MAX=150,
//                        timestamp precision ms preservee)
//   v1.1 (2026-05-13) : tentative fix sg7 HVL_0DTE via cross-chart-toujours.
//                       BUG : `GetStudyArrayFromChartUsingID` avec chart_id ==
//                       sc.ChartNumber renvoie tableau vide → l'etude ne dump
//                       plus rien du tout. v1.1 ANNULEE.
//   v1.2 (2026-05-13) : Jackson directive "LIRE EN NORMAL PAS EN CROSS CHART".
//                       Restaure branching v1.0 :
//                         - chart_id == sc.ChartNumber → GetStudyArrayUsingID (host)
//                         - chart_id != sc.ChartNumber → GetStudyArrayFromChartUsingID
//                       Idem vix_level : sc.Close[sc.Index] en host, fallback
//                       GetChartBaseData si Input[1] override different chart.
//                       Le sg7 HVL_0DTE null reste limite acceptee : MenthorQ
//                       a probablement sg7 vide quand HVL_0DTE == Put_0DTE.
//                       Python loader peut deduire via vix_put_0dte fallback.
//   v1.3 (2026-05-13) : ajout sg8 Gamma Wall 0DTE + fallback fusion MenthorQ
//                       cote C++. Quand 2 niveaux 0DTE sont au meme prix :
//                         - sg7 vide & sg6 valide → HVL_0DTE = Put_0DTE
//                         - sg8 vide & sg5 valide → Gamma_Wall_0DTE = Call_0DTE
//                       Quand niveaux differents, on garde la vraie valeur.
//                       Schema bump : vix_levels_1.0 → vix_levels_1.1.
//                       Comprehension MenthorQ : labels combines visuels
//                       ("Put Support 0DTE & HVL 0DTE: 16.00") = sg vidie l'un
//                       des deux subgraphs, le principal conserve la valeur.
// =============================================================================

#include "sierrachart.h"
#include <cmath>
#include <cfloat>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <direct.h>  // _mkdir Windows

SCDLLName("MIA_VIX_LITE")

// =============================================================================
// CONSTANTS
// =============================================================================

namespace VXL {

constexpr float INVALID = FLT_MAX;
constexpr float EPSILON_PRICE = 0.0001f;

// Chart ID host (où l'étude est attachée). Override possible via Input[1].
// 15 = VIX_CGI[M] sur le setup Sierra de Jackson (cf DMP_Reader.h:41 VIX_MQ=15).
constexpr int DEFAULT_CHART_VIX = 15;

// Study ID MenthorQ Gamma sur le chart VIX. Override via Input[2].
// 2 = valeur observée dans le DMP_Reader.h struct VIX::MQ_GAMMA.
constexpr int DEFAULT_STUDY_MQ_GAMMA = 2;

// Subgraph IDs MQ_GAMMA (aligne sur DMP_Reader.h DMP_ReadVIX + DMP_Studies::VIX,
// + ajout sg8 Gamma Wall 0DTE absent du DMP — visible sur chart label combine
// "Call Resistance 0DTE & Gamma Wall 0DTE" quand identiques)
constexpr int SG_CALL            = 0;
constexpr int SG_PUT             = 1;
constexpr int SG_HVL             = 2;
constexpr int SG_1D_MIN          = 3;
constexpr int SG_1D_MAX          = 4;
constexpr int SG_CALL_0DTE       = 5;
constexpr int SG_PUT_0DTE        = 6;
constexpr int SG_HVL_0DTE        = 7;
constexpr int SG_GAMMA_WALL_0DTE = 8;
constexpr int SG_GEX_BASE        = 9;   // sg9..sg18

// Indices dans VXL_Levels.fixed[] (= ordre de stockage interne)
constexpr int IDX_CALL            = 0;
constexpr int IDX_PUT             = 1;
constexpr int IDX_HVL             = 2;
constexpr int IDX_1D_MIN          = 3;
constexpr int IDX_1D_MAX          = 4;
constexpr int IDX_CALL_0DTE       = 5;
constexpr int IDX_PUT_0DTE        = 6;
constexpr int IDX_HVL_0DTE        = 7;
constexpr int IDX_GAMMA_WALL_0DTE = 8;

constexpr int N_GEX = 10;
constexpr int N_LEVELS_FIXED = 9;  // call, put, hvl, 1d_min, 1d_max, call_0dte, put_0dte, hvl_0dte, gamma_wall_0dte
constexpr int N_SNAPSHOT = N_LEVELS_FIXED + N_GEX;  // 19 (niveaux uniquement, sans vix_level)

// VIX validity range
//   VIX cash CBOE historique 09/11/2017 low = 9.14, covid 2020 peak = 82.69.
//   FIX P0-2 (review code-reviewer 13/05/2026) : VIX_MQ_MAX = 80.0f hérité DMP
//   rejettait des niveaux MQ Call/Put VIX légitimes pendant un stress event
//   (niveaux MQ peuvent monter à 85-95 quand VIX cash atteint 80+). Élargi à 150
//   pour les niveaux (garde ouverte aux crashs), 200 pour le prix (large).
//   VIX_LEVEL_MIN abaissé à 5.0f acceptable (low historique = 9, garde de sécurité).
constexpr float VIX_LEVEL_MIN  = 5.0f;
constexpr float VIX_LEVEL_MAX  = 200.0f;  // vix_level price guard (large pour ne pas couper crash)
constexpr float VIX_MQ_MIN     = 5.0f;    // niveaux MQ Gamma : rejette 0.0 (subgraph non configuré)
constexpr float VIX_MQ_MAX     = 150.0f;  // ex-DMP 80.0f trop serré (covid 2020 peak 82.69 → MQ ≥85)

// PersistentInt indices (séparés de MQ_Lite 150-159 et DMP) :
//   200..209 réservés VIX_Lite
constexpr int P_INITIALIZED   = 200;
constexpr int P_LAST_BAR_IDX  = 201;  // dedup last_bar (rappel même barre)

} // namespace VXL

// =============================================================================
// HELPERS — copies standalone (drift accepté vs MQ_Lite/DMP)
// =============================================================================

static inline bool VXL_IsValid(float v) {
    return (v != VXL::INVALID) && std::isfinite(v) && v < 1e37f;
}

static inline bool VXL_IsVixLevelValid(float v) {
    return VXL_IsValid(v) && v > VXL::VIX_LEVEL_MIN && v < VXL::VIX_LEVEL_MAX;
}

static inline bool VXL_IsMqLevelValid(float v) {
    return VXL_IsValid(v) && v > VXL::VIX_MQ_MIN && v < VXL::VIX_MQ_MAX;
}

// Lecture sécurisée d'un subgraph d'une étude.
// FIX v1.2 (2026-05-13 14:50) : revert v1.1 cross-chart-toujours qui empechait
// completement la lecture quand attache sur chart host (GetStudyArrayFromChartUsingID
// avec chart_id == sc.ChartNumber renvoie tableau vide en pratique).
// Restaure le branching v1.0 :
//   - chart_id == sc.ChartNumber → GetStudyArrayUsingID (host, API directe)
//   - chart_id != sc.ChartNumber → GetStudyArrayFromChartUsingID (cross-chart)
// Le bug observe sg7=null sur HVL_0DTE en v1.0 n'est PAS un bug du pattern host :
// c'est soit (a) MenthorQ a sg7 vide quand HVL_0DTE == Put_0DTE (collision label
// visuel sur chart), soit (b) sg7 retourne 0.0 et notre guard MQ_MIN=5.0f rejette.
// Solution post-v1.2 si critique : fallback cross-chart UNIQUEMENT pour sg7
// quand arr.GetArraySize()==0 en host mode. Pour l'instant, accepte null comme
// limite acceptable (Python loader peut deduire via vix_put_0dte ou DMP fallback).
static inline float VXL_SafeReadLast(SCStudyInterfaceRef sc, int chart_id, int study_id, int sg) {
    if (study_id < 0) return VXL::INVALID;
    SCFloatArray arr;
    if (chart_id == sc.ChartNumber) {
        sc.GetStudyArrayUsingID(study_id, sg, arr);
    } else {
        sc.GetStudyArrayFromChartUsingID(chart_id, study_id, sg, arr);
    }
    int sz = (int)arr.GetArraySize();
    if (sz == 0) return VXL::INVALID;
    float val = arr[sz - 1];
    if (!std::isfinite(val) || val >= 1e37f) return VXL::INVALID;
    return val;
}

// Lit + filtre selon validity range MQ Gamma VIX.
static inline float VXL_ReadMqLevel(SCStudyInterfaceRef sc, int chart_id, int study_id, int sg) {
    float v = VXL_SafeReadLast(sc, chart_id, study_id, sg);
    return VXL_IsMqLevelValid(v) ? v : VXL::INVALID;
}

// =============================================================================
// FILESYSTEM — Hive partitioning + atomic append + crash-safe
// (copie MQ_Lite avec adaptation path = vix_levels/ sans sym sous-dossier)
// =============================================================================

static void VXL_BuildPath(char* out, size_t out_sz,
                          const char* base, int yyyy, int mm, int dd) {
    char base_norm[512];
    snprintf(base_norm, sizeof(base_norm), "%s", base ? base : "");
    size_t bn = strlen(base_norm);
    while (bn > 0 && (base_norm[bn - 1] == '\\' || base_norm[bn - 1] == '/')) {
        base_norm[--bn] = 0;
    }

    char dir[768];
    snprintf(dir, sizeof(dir),
             "%s\\vix_levels\\year=%d\\month=%d\\day=%d",
             base_norm, yyyy, mm, dd);

    char tmp[768];
    snprintf(tmp, sizeof(tmp), "%s", dir);
    size_t tmp_len = strlen(tmp);
    for (size_t i = bn + 1; i < tmp_len; i++) {
        if (tmp[i] == '\\') {
            tmp[i] = 0;
            _mkdir(tmp);
            tmp[i] = '\\';
        }
    }
    _mkdir(tmp);
    snprintf(out, out_sz, "%s\\vix.jsonl", dir);
}

// Retourne true si write réussi. Si fopen ou write échoue, return false →
// caller log + retry prochaine barre.
static bool VXL_AppendLine(SCStudyInterfaceRef sc, const char* path, const char* line) {
    FILE* f = fopen(path, "a");
    if (!f) {
        char err[1024];
        snprintf(err, sizeof(err),
                 "VIX_Lite: fopen failed path=%s errno=%d", path, errno);
        sc.AddMessageToLog(err, 1);
        return false;
    }
    char buf_with_nl[2200];
    int n = snprintf(buf_with_nl, sizeof(buf_with_nl), "%s\n", line);
    bool ok = false;
    if (n > 0 && (size_t)n < sizeof(buf_with_nl)) {
        size_t written = fwrite(buf_with_nl, 1, (size_t)n, f);
        ok = (written == (size_t)n);
        if (!ok) sc.AddMessageToLog("VIX_Lite: fwrite partial, retry next bar", 1);
    } else {
        sc.AddMessageToLog("VIX_Lite: line buffer overflow", 1);
    }
    fflush(f);
    fclose(f);
    return ok;
}

// =============================================================================
// JSON SERIALIZATION
// =============================================================================

static int VXL_FormatFloat(char* buf, size_t buf_sz, float v) {
    if (!VXL_IsValid(v)) return snprintf(buf, buf_sz, "null");
    return snprintf(buf, buf_sz, "%.4f", v);
}

// Serialise tableau N floats en JSON array.
static int VXL_FormatFloatArray(char* buf, size_t buf_sz, const float* lvls, int n) {
    int written = 0;
    int r = snprintf(buf, buf_sz, "[");
    if (r < 0 || (size_t)r >= buf_sz) return -1;
    written += r;
    for (int i = 0; i < n; i++) {
        const char* sep = (i == 0) ? "" : ",";
        char val_buf[24];
        VXL_FormatFloat(val_buf, sizeof(val_buf), lvls[i]);
        r = snprintf(buf + written, buf_sz - written, "%s%s", sep, val_buf);
        if (r < 0 || (size_t)(written + r) >= buf_sz) return -1;
        written += r;
    }
    r = snprintf(buf + written, buf_sz - written, "]");
    if (r < 0 || (size_t)(written + r) >= buf_sz) return -1;
    written += r;
    return written;
}

// =============================================================================
// CORE — read VIX price + 17 levels, emit JSONL 1/bar
// =============================================================================

struct VXL_Levels {
    float vix_level;           // prix VIX courant
    float fixed[VXL::N_LEVELS_FIXED];  // call, put, hvl, 1d_min, 1d_max, call_0dte, put_0dte, hvl_0dte
    float gex[VXL::N_GEX];     // GEX 1..10
};

static void VXL_ReadAll(SCStudyInterfaceRef sc, int chart_vix, int study_mq,
                        VXL_Levels& out) {
    // 1. Prix VIX courant
    //    FIX v1.2 (2026-05-13 14:50) : Jackson directive "LIRE EN NORMAL PAS EN
    //    CROSS CHART". L'etude est attachee sur chart 15 (host = chart VIX), on
    //    lit donc directement sc.Close[sc.Index] (API host normale).
    //    Si l'utilisateur override Input[1] pour pointer un AUTRE chart VIX
    //    (chart_vix != sc.ChartNumber), fallback cross-chart via GetChartBaseData.
    //    Le risque AutoLoop revisit / cross-TF flag par code-reviewer (P0-1) est
    //    mitige par guard `BHCS_BAR_HAS_CLOSED` + dedup `P_LAST_BAR_IDX` deja en place.
    if (chart_vix == sc.ChartNumber) {
        float vix_last = sc.Close[sc.Index];
        out.vix_level = VXL_IsVixLevelValid(vix_last) ? vix_last : VXL::INVALID;
    } else {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_vix, chart_data);
        SCFloatArray close_arr = chart_data[SC_LAST];
        int sz = (int)close_arr.GetArraySize();
        if (sz > 0) {
            float v = close_arr[sz - 1];
            out.vix_level = VXL_IsVixLevelValid(v) ? v : VXL::INVALID;
        } else {
            out.vix_level = VXL::INVALID;
        }
    }

    // 2. 9 niveaux fixes (8 standard + Gamma Wall 0DTE)
    out.fixed[VXL::IDX_CALL]            = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_CALL);
    out.fixed[VXL::IDX_PUT]             = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_PUT);
    out.fixed[VXL::IDX_HVL]             = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_HVL);
    out.fixed[VXL::IDX_1D_MIN]          = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_1D_MIN);
    out.fixed[VXL::IDX_1D_MAX]          = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_1D_MAX);
    out.fixed[VXL::IDX_CALL_0DTE]       = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_CALL_0DTE);
    out.fixed[VXL::IDX_PUT_0DTE]        = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_PUT_0DTE);
    out.fixed[VXL::IDX_HVL_0DTE]        = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_HVL_0DTE);
    out.fixed[VXL::IDX_GAMMA_WALL_0DTE] = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_GAMMA_WALL_0DTE);

    // 3. 10 niveaux GEX
    for (int i = 0; i < VXL::N_GEX; i++) {
        out.gex[i] = VXL_ReadMqLevel(sc, chart_vix, study_mq, VXL::SG_GEX_BASE + i);
    }

    // 4. FALLBACK FUSION MenthorQ (v1.3 — directive Jackson 2026-05-13) :
    //    Quand 2 niveaux 0DTE sont au meme prix, MenthorQ fusionne les labels
    //    visuellement ("Put Support 0DTE & HVL 0DTE: 16.00") ET vide le subgraph
    //    secondaire (HVL_0DTE / Gamma_Wall_0DTE). Le subgraph principal
    //    (Put_0DTE / Call_0DTE) conserve la valeur.
    //    Quand les niveaux sont DIFFERENTS, MenthorQ remplit les 2 subgraphs
    //    → on garde la vraie valeur lue.
    //    Pattern : si secondaire vide ET principal valide → recopier la valeur.
    //
    //    Cas 1 : HVL_0DTE (sg7) vide & Put_0DTE (sg6) valide
    //            → fusion "Put Support 0DTE & HVL 0DTE: X" → HVL_0DTE = Put_0DTE
    //    Cas 2 : Gamma_Wall_0DTE (sg8) vide & Call_0DTE (sg5) valide
    //            → fusion "Call Resistance 0DTE & Gamma Wall 0DTE: X" → Gamma_Wall = Call_0DTE
    if (!VXL_IsValid(out.fixed[VXL::IDX_HVL_0DTE])
        && VXL_IsValid(out.fixed[VXL::IDX_PUT_0DTE])) {
        out.fixed[VXL::IDX_HVL_0DTE] = out.fixed[VXL::IDX_PUT_0DTE];
    }
    if (!VXL_IsValid(out.fixed[VXL::IDX_GAMMA_WALL_0DTE])
        && VXL_IsValid(out.fixed[VXL::IDX_CALL_0DTE])) {
        out.fixed[VXL::IDX_GAMMA_WALL_0DTE] = out.fixed[VXL::IDX_CALL_0DTE];
    }
}

static void VXL_ProcessBar(SCStudyInterfaceRef sc, int chart_vix, int study_mq,
                            const char* base_path) {
    // ── 1. Read all values ────────────────────────────────────────────────────
    VXL_Levels lvls;
    VXL_ReadAll(sc, chart_vix, study_mq, lvls);

    // ── 2. Date pour path Hive ────────────────────────────────────────────────
    SCDateTime bar_dt = sc.BaseDateTimeIn[sc.Index];
    int yyyy, mm, dd, hh, mi, ss, msv;
    bar_dt.GetDateTimeYMDHMS_MS(yyyy, mm, dd, hh, mi, ss, msv);
    (void)hh; (void)mi; (void)ss; (void)msv;

    // ── 3. Timestamp epoch ms UTC ─────────────────────────────────────────────
    //   FIX P0-3 (review code-reviewer 13/05/2026) : multiplication directe par
    //   86400000.0 préserve la précision sub-seconde (vs cast prematuré (long long)
    //   * 1000LL qui tronquait à la seconde). Sans impact 1/min RTH (close toujours
    //   seconde pleine) mais correct si bar timestamp porte un offset ms.
    long long ts_ms = (long long)((bar_dt.GetAsDouble() - 25569.0) * 86400000.0);

    // ── 4. Build path ─────────────────────────────────────────────────────────
    char path[1024];
    VXL_BuildPath(path, sizeof(path), base_path, yyyy, mm, dd);

    // ── 5. Build JSON line (schema v1.1 : +vix_gamma_wall_0dte) ──────────────
    char buf_vix[24];
    char buf_call[24], buf_put[24], buf_hvl[24];
    char buf_1dmin[24], buf_1dmax[24];
    char buf_call0[24], buf_put0[24], buf_hvl0[24], buf_gwall0[24];
    char buf_gex[256];

    VXL_FormatFloat(buf_vix,    sizeof(buf_vix),    lvls.vix_level);
    VXL_FormatFloat(buf_call,   sizeof(buf_call),   lvls.fixed[VXL::IDX_CALL]);
    VXL_FormatFloat(buf_put,    sizeof(buf_put),    lvls.fixed[VXL::IDX_PUT]);
    VXL_FormatFloat(buf_hvl,    sizeof(buf_hvl),    lvls.fixed[VXL::IDX_HVL]);
    VXL_FormatFloat(buf_1dmin,  sizeof(buf_1dmin),  lvls.fixed[VXL::IDX_1D_MIN]);
    VXL_FormatFloat(buf_1dmax,  sizeof(buf_1dmax),  lvls.fixed[VXL::IDX_1D_MAX]);
    VXL_FormatFloat(buf_call0,  sizeof(buf_call0),  lvls.fixed[VXL::IDX_CALL_0DTE]);
    VXL_FormatFloat(buf_put0,   sizeof(buf_put0),   lvls.fixed[VXL::IDX_PUT_0DTE]);
    VXL_FormatFloat(buf_hvl0,   sizeof(buf_hvl0),   lvls.fixed[VXL::IDX_HVL_0DTE]);
    VXL_FormatFloat(buf_gwall0, sizeof(buf_gwall0), lvls.fixed[VXL::IDX_GAMMA_WALL_0DTE]);
    VXL_FormatFloatArray(buf_gex, sizeof(buf_gex), lvls.gex, VXL::N_GEX);

    char line[1536];
    int line_n = snprintf(line, sizeof(line),
        "{\"ts\":%lld,\"schema_version\":\"vix_levels_1.1\","
        "\"vix_level\":%s,"
        "\"vix_call\":%s,\"vix_put\":%s,\"vix_hvl\":%s,"
        "\"vix_1d_min\":%s,\"vix_1d_max\":%s,"
        "\"vix_call_0dte\":%s,\"vix_gamma_wall_0dte\":%s,"
        "\"vix_put_0dte\":%s,\"vix_hvl_0dte\":%s,"
        "\"vix_gex\":%s}",
        ts_ms,
        buf_vix,
        buf_call, buf_put, buf_hvl,
        buf_1dmin, buf_1dmax,
        buf_call0, buf_gwall0,
        buf_put0, buf_hvl0,
        buf_gex);

    if (line_n < 0 || (size_t)line_n >= sizeof(line)) {
        sc.AddMessageToLog("VIX_Lite: JSON line truncated, skipping write", 1);
        return;
    }

    // ── 6. Append (best-effort, retry prochaine barre si échec) ───────────────
    (void)VXL_AppendLine(sc, path, line);
}

// =============================================================================
// SCSFExport — à attacher sur Chart 15 (VIX_CGI[M])
// =============================================================================

SCSFExport scsf_MIA_VIX_Lite(SCStudyInterfaceRef sc) {

    if (sc.SetDefaults) {
        sc.GraphName             = "MIA VIX Lite — VIX + MQ Gamma (JSONL 1/min)";
        sc.StudyDescription      = "Dump prix VIX + 17 niveaux MenthorQ Gamma sur VIX a chaque "
                                   "barre fermee (1/min). Output : "
                                   "DATA/vix_levels/year=YYYY/month=M/day=D/vix.jsonl. "
                                   "Schema vix_levels_1.0. Attache sur Chart 15 (VIX_CGI[M]). "
                                   "Si attache sur autre chart, override Input[1] = chart VIX cible.";
        sc.AutoLoop              = 1;
        sc.GraphRegion           = 0;
        sc.DrawZeros             = 0;
        sc.UpdateAlways          = 1;
        sc.CalculationPrecedence = LOW_PREC_LEVEL;
        sc.MaintainAdditionalChartDataArrays = 1;

        sc.Input[0].Name = "Repertoire de sortie";
        sc.Input[0].SetDescription("Chemin base. Sous-dossier vix_levels/year=.../ cree auto.");
        sc.Input[0].SetString("C:\\TRADING_SIERRA_CHART_AUTO\\DATA");

        sc.Input[1].Name = "Chart VIX (0 = host courant)";
        sc.Input[1].SetDescription("Chart Sierra qui contient le VIX + etude MQ Gamma. "
                                    "0 = chart sur lequel cette etude est attachee. "
                                    "Sinon ex: 15 pour cross-chart depuis un autre chart.");
        sc.Input[1].SetInt(0);

        sc.Input[2].Name = "Study ID MQ Gamma VIX";
        sc.Input[2].SetDescription("Study ID de MenthorQ Gamma Levels sur le chart VIX. "
                                    "Visible dans Sierra : Chart Studies > liste, colonne ID.");
        sc.Input[2].SetInt(VXL::DEFAULT_STUDY_MQ_GAMMA);
        return;
    }

    if (sc.LastCallToFunction) return;
    if (sc.ServerConnectionState != SCS_CONNECTED) return;
    if (sc.Index < sc.ArraySize - 2) return;
    if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED) return;
    if (sc.Index < 10) return;

    // Dedup : 1 write max par bar_index (anti rappel meme barre Sierra).
    int& last_bar = sc.GetPersistentInt(VXL::P_LAST_BAR_IDX);
    if (sc.Index <= last_bar) return;
    last_bar = sc.Index;

    const char* base_path = sc.Input[0].GetString();
    if (!base_path || base_path[0] == '\0') {
        static bool s_warned = false;
        if (!s_warned) {
            sc.AddMessageToLog("VIX_Lite: Input[0] base path vide", 1);
            s_warned = true;
        }
        return;
    }

    int chart_vix = sc.Input[1].GetInt();
    if (chart_vix == 0) chart_vix = sc.ChartNumber;  // host courant

    int study_mq = sc.Input[2].GetInt();
    if (study_mq < 0) {
        static bool s_warned2 = false;
        if (!s_warned2) {
            sc.AddMessageToLog("VIX_Lite: Input[2] study_mq invalide", 1);
            s_warned2 = true;
        }
        return;
    }

    VXL_ProcessBar(sc, chart_vix, study_mq, base_path);
}

// =============================================================================
// FIN VIX_Lite.cpp v1.3 — schema vix_levels_1.1 — 2026-05-13
// v1.3 : +sg8 Gamma Wall 0DTE + fallback fusion MenthorQ (HVL_0DTE=Put_0DTE,
//        Gamma_Wall_0DTE=Call_0DTE quand sg secondaire vide).
// =============================================================================
