// =============================================================================
// MQ_Lite.cpp — MIA Trading System V2 — DLL séparée MenthorQ Levels
// =============================================================================
//
// Objectif : dump des NIVEAUX MenthorQ bruts (ES/NQ) uniquement quand ils
// changent. MenthorQ update 1-2 fois par jour → ~5 lignes max/jour/sym.
//
// Pourquoi v2 levels-only :
//   v1 dumpait les distances calculees (price-dependent → 1 ligne/min) =
//   99% redondance car les niveaux ne bougent pas. v2 dump uniquement quand
//   un niveau change. Les distances/bool/gex_count seront calcules cote
//   Python enricher en mergant asof avec les barres Databento (1/min).
//
// 24 niveaux bruts dumpes :
//   mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte, mq_hvl_0dte,
//   mq_1d_min, mq_1d_max, mq_gex[10], mq_blind[10]
//
// VIX exclu volontairement Phase 1 (vix_level change 1/min ≠ levels-only).
// Il sera dump par un module separe ou recupere depuis Databento.
//
// Trigger d'ecriture :
//   1. Premiere barre apres init (pas de snapshot)
//   2. Au moins 1 niveau a change > EPSILON ticks (default = 0.0001)
//   3. Nouveau jour de trading detecte (yyyymmdd different du dernier write)
//
// Output Hive : D:\TRADING_SIERRA_CHART_AUTO\DATA\mq_levels\{ES,NQ}\
//                year=YYYY\month=M\day=D\levels.jsonl
//
// Architecture :
//   - DLL séparée du DMP full (si plante, DMP continue)
//   - 2 SCSFExport (1 ES, 1 NQ) attachés sur leurs charts BARRES
//   - Helpers MQL_* dupliques de DMP (zero coupling, drift accepte documente)
//   - Snapshot 24 floats via PersistentFloat[100..123]
//
// Schema : "mq_levels_1.0" — distinct de DMP "3.7.x" et de "mq_lite_1.0" v1.
//
// Auteur : MIA Trading System V2
//   v1.0 (2026-04-28) : version initiale levels+distances (review NOGO)
//   v1.1 (2026-04-28) : fixes review (chart Blind, VIX validity, ts formula,
//                       fopen logging, base normalize, Input check)
//   v2.0 (2026-04-28) : pivot levels-only + change detection (Jackson direct)
//   v2.1 (2026-04-28) : fix R1 review (AppendLine retourne bool, gate snapshot
//                       save si write fail = anti-perte silencieuse disque plein)
//   v2.2 (2026-04-28) : fix Issue C schema-audit (MQL_ReadLevel filtre 0.0 →
//                       INVALID, aligne sur DMP_IsPriceValid). Niveau a $0 ne
//                       pollue plus downstream JSONL en "0.0000".
//   v2.3 (2026-04-28) : fix default Input[0] path D:\ → C:\ (cible VPS prod).
//                       Sur PC local, override manuel via Study Settings. La
//                       v2.2 deployee VPS n'avait que D:\ default, Jackson a du
//                       corriger 2 fois manuellement a l'attach.
// =============================================================================

#include "sierrachart.h"
#include <cmath>
#include <cfloat>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <direct.h>  // _mkdir Windows

SCDLLName("MIA_MQ_LITE")

// =============================================================================
// CONSTANTS
// =============================================================================

namespace MQL {

constexpr float INVALID = FLT_MAX;
constexpr float TICK_SIZE = 0.25f;        // ES = NQ
constexpr float EPSILON = 0.0001f;        // sensibilite changement (sub-tick)

// Chart IDs (cf study_mapping.json + DMP_Reader.h:41-65, scan 02/03/2026)
constexpr int CHART_ES_GAMMA = 25;  // ES_BARRES — host MQ_GAMMA ES
constexpr int CHART_NQ_GAMMA = 23;  // NQ_BARRES — host MQ_GAMMA NQ
constexpr int CHART_GC_GAMMA = 34;  // GCM26-COMEX[M] — host MQ_GAMMA GC (10/05/2026)
constexpr int CHART_ES_BLIND = 31;  // ES_COMPOSITE — host MQ_BLIND ES
constexpr int CHART_NQ_BLIND = 30;  // NQ_COMPOSITE — host MQ_BLIND NQ
constexpr int CHART_GC_BLIND = 34;  // MEME chart 34 (GC pas de Composite separe)

// Study IDs MenthorQ Gamma
constexpr int STUDY_MQ_GAMMA_ES = 2;
constexpr int STUDY_MQ_GAMMA_NQ = 25;
constexpr int STUDY_MQ_GAMMA_GC = 2;   // ID:2 sur chart 34 (10/05/2026 screenshot)

// Study IDs MenthorQ Blind Spots (sur charts COMPOSITE pour ES/NQ, MEME chart pour GC)
constexpr int STUDY_MQ_BLIND_ES = 7;
constexpr int STUDY_MQ_BLIND_NQ = 7;
constexpr int STUDY_MQ_BLIND_GC = 22;  // ID:22 sur chart 34 (10/05/2026 screenshot)

// Subgraph IDs MQ_GAMMA
constexpr int SG_CALL       = 0;
constexpr int SG_PUT        = 1;
constexpr int SG_HVL        = 2;
constexpr int SG_1D_MIN     = 3;
constexpr int SG_1D_MAX     = 4;
constexpr int SG_CALL_0DTE  = 5;
constexpr int SG_PUT_0DTE   = 6;
constexpr int SG_HVL_0DTE   = 7;
constexpr int SG_GEX_BASE   = 9;   // sg9..sg18

constexpr int N_GEX = 10;
constexpr int N_BLIND = 10;
constexpr int N_LEVELS = 8 + N_GEX + N_BLIND;  // 28 (mais 4 booleens repetes ?)
// Indices fixes du tableau snapshot (0..23 = 24 floats) :
//   [0]  mq_call
//   [1]  mq_put
//   [2]  mq_hvl
//   [3]  mq_call_0dte
//   [4]  mq_put_0dte
//   [5]  mq_hvl_0dte
//   [6]  mq_1d_min
//   [7]  mq_1d_max
//   [8..17]  mq_gex[0..9]
//   [18..27] mq_blind[0..9]
constexpr int N_SNAPSHOT = 28;

// PersistentFloat indices (reserve 100..127 pour MQ_Lite snapshot)
constexpr int P_SNAPSHOT_BASE = 100;  // 100..127 = 28 levels
// PersistentInt indices (reserve 150..159 pour MQ_Lite state)
constexpr int P_INITIALIZED   = 150;
constexpr int P_LAST_DATE_YMD = 151;  // yyyymmdd dernier write
constexpr int P_LAST_BAR_IDX  = 152;  // dedup last_bar (rappel meme barre)

} // namespace MQL

// =============================================================================
// HELPERS — copies standalone des helpers DMP_Reader.h / DMP_Transform.h
// (drift accepte : si tu modifies DMP, REPORTE ici)
// =============================================================================

static inline bool MQL_IsValid(float v) {
    return (v != MQL::INVALID) && std::isfinite(v) && v < 1e37f;
}

static inline bool MQL_IsPriceValid(float p) {
    return MQL_IsValid(p) && p > 100.0f && p < 100000.0f;
}

static inline float MQL_SafeReadLast(SCStudyInterfaceRef sc, int chart, int study, int sg) {
    if (study < 0) return MQL::INVALID;
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study, sg, arr);
    int sz = (int)arr.GetArraySize();
    if (sz == 0) return MQL::INVALID;
    float val = arr[sz - 1];
    if (!std::isfinite(val) || val >= 1e37f) return MQL::INVALID;
    return val;
}

// Lit + filtre par MQL_IsPriceValid (rejette 0.0 et valeurs hors [100, 100000]).
// Fix Issue C review schema : MenthorQ retourne 0.0 pour subgraph non-configure
// (e.g. Blind Spot inutilise). Sans ce filtre, le JSONL emit "0.0000" qui pollue
// downstream Python (faux niveau a $0). Le DMP filtre via DMP_IsPriceValid
// (DMP_Reader.h:2062) — on s'aligne.
static inline float MQL_ReadLevel(SCStudyInterfaceRef sc, int chart, int study, int sg) {
    float v = MQL_SafeReadLast(sc, chart, study, sg);
    return MQL_IsPriceValid(v) ? v : MQL::INVALID;
}

// Compare deux levels en tolerant que les deux soient INVALID (= identique).
static inline bool MQL_LevelEqual(float a, float b) {
    bool av = MQL_IsValid(a);
    bool bv = MQL_IsValid(b);
    if (!av && !bv) return true;       // les 2 invalides = pas de change
    if (av != bv) return false;        // l'un valide, l'autre non = change
    return std::fabs(a - b) < MQL::EPSILON;
}

// =============================================================================
// FILESYSTEM — Hive partitioning + atomic append + crash-safe
// =============================================================================

static void MQL_BuildPath(char* out, size_t out_sz,
                          const char* base, const char* sym,
                          int yyyy, int mm, int dd) {
    char base_norm[512];
    snprintf(base_norm, sizeof(base_norm), "%s", base ? base : "");
    size_t bn = strlen(base_norm);
    while (bn > 0 && (base_norm[bn - 1] == '\\' || base_norm[bn - 1] == '/')) {
        base_norm[--bn] = 0;
    }

    char dir[768];
    snprintf(dir, sizeof(dir),
             "%s\\mq_levels\\%s\\year=%d\\month=%d\\day=%d",
             base_norm, sym, yyyy, mm, dd);

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
    snprintf(out, out_sz, "%s\\levels.jsonl", dir);
}

// Retourne true si write reussi (caller peut alors update snapshot/init).
// Si fopen ou write echoue, return false → caller NE met PAS a jour snapshot,
// la prochaine barre re-tentera (anti-perte silencieuse en cas disque plein/perm).
static bool MQL_AppendLine(SCStudyInterfaceRef sc, const char* path, const char* line) {
    FILE* f = fopen(path, "a");
    if (!f) {
        char err[1024];
        snprintf(err, sizeof(err),
                 "MQ_Lite: fopen failed path=%s errno=%d", path, errno);
        sc.AddMessageToLog(err, 1);
        return false;
    }
    char buf_with_nl[2200];
    int n = snprintf(buf_with_nl, sizeof(buf_with_nl), "%s\n", line);
    bool ok = false;
    if (n > 0 && (size_t)n < sizeof(buf_with_nl)) {
        size_t written = fwrite(buf_with_nl, 1, (size_t)n, f);
        ok = (written == (size_t)n);
        if (!ok) sc.AddMessageToLog("MQ_Lite: fwrite partial, retry next bar", 1);
    } else {
        sc.AddMessageToLog("MQ_Lite: line buffer overflow", 1);
    }
    fflush(f);
    fclose(f);
    return ok;
}

// =============================================================================
// JSON SERIALIZATION
// =============================================================================

static int MQL_FormatLevel(char* buf, size_t buf_sz, float v) {
    if (!MQL_IsValid(v)) return snprintf(buf, buf_sz, "null");
    return snprintf(buf, buf_sz, "%.4f", v);
}

// Serialise un tableau de N levels en JSON array : [12.5, null, 13.0, ...]
static int MQL_FormatLevelArray(char* buf, size_t buf_sz, const float* lvls, int n) {
    int written = 0;
    int r = snprintf(buf, buf_sz, "[");
    if (r < 0 || (size_t)r >= buf_sz) return -1;
    written += r;
    for (int i = 0; i < n; i++) {
        const char* sep = (i == 0) ? "" : ",";
        char val_buf[24];
        MQL_FormatLevel(val_buf, sizeof(val_buf), lvls[i]);
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
// CORE — read levels, detect change, emit JSONL si change
// =============================================================================

struct MQL_SymContext {
    int          chart_gamma;
    int          chart_blind;
    int          study_gamma;
    int          study_blind;
    const char*  sym_name;
};

// Lit les 28 niveaux dans un tableau ordonne (ordre snapshot).
static void MQL_ReadAllLevels(SCStudyInterfaceRef sc, const MQL_SymContext& ctx,
                               float out[MQL::N_SNAPSHOT]) {
    const int CG = ctx.chart_gamma;
    const int SG = ctx.study_gamma;
    out[0] = MQL_ReadLevel(sc, CG, SG, MQL::SG_CALL);
    out[1] = MQL_ReadLevel(sc, CG, SG, MQL::SG_PUT);
    out[2] = MQL_ReadLevel(sc, CG, SG, MQL::SG_HVL);
    out[3] = MQL_ReadLevel(sc, CG, SG, MQL::SG_CALL_0DTE);
    out[4] = MQL_ReadLevel(sc, CG, SG, MQL::SG_PUT_0DTE);
    out[5] = MQL_ReadLevel(sc, CG, SG, MQL::SG_HVL_0DTE);
    out[6] = MQL_ReadLevel(sc, CG, SG, MQL::SG_1D_MIN);
    out[7] = MQL_ReadLevel(sc, CG, SG, MQL::SG_1D_MAX);
    for (int i = 0; i < MQL::N_GEX; i++) {
        out[8 + i] = MQL_ReadLevel(sc, CG, SG, MQL::SG_GEX_BASE + i);
    }
    for (int i = 0; i < MQL::N_BLIND; i++) {
        out[18 + i] = MQL_ReadLevel(sc, ctx.chart_blind, ctx.study_blind, i);
    }
}

// Compare 28 levels actuels vs snapshot precedent. Retourne true si changement.
static bool MQL_LevelsChanged(const float* current, const float* snapshot) {
    for (int i = 0; i < MQL::N_SNAPSHOT; i++) {
        if (!MQL_LevelEqual(current[i], snapshot[i])) return true;
    }
    return false;
}

// Sauvegarde snapshot dans PersistentFloat[100..127].
static void MQL_SaveSnapshot(SCStudyInterfaceRef sc, const float* current) {
    for (int i = 0; i < MQL::N_SNAPSHOT; i++) {
        sc.GetPersistentFloat(MQL::P_SNAPSHOT_BASE + i) = current[i];
    }
}

// Lit snapshot depuis PersistentFloat. Si jamais initialise, retourne INVALID.
static void MQL_LoadSnapshot(SCStudyInterfaceRef sc, float* out) {
    for (int i = 0; i < MQL::N_SNAPSHOT; i++) {
        out[i] = sc.GetPersistentFloat(MQL::P_SNAPSHOT_BASE + i);
        if (!std::isfinite(out[i]) || out[i] >= 1e37f) out[i] = MQL::INVALID;
    }
}

static void MQL_ProcessBar(SCStudyInterfaceRef sc, const MQL_SymContext& ctx,
                            const char* base_path) {
    // ── 1. Read 28 levels ─────────────────────────────────────────────────────
    float levels[MQL::N_SNAPSHOT];
    MQL_ReadAllLevels(sc, ctx, levels);

    // ── 2. Load previous snapshot ─────────────────────────────────────────────
    int& initialized = sc.GetPersistentInt(MQL::P_INITIALIZED);
    int& last_ymd    = sc.GetPersistentInt(MQL::P_LAST_DATE_YMD);

    bool first_write = (initialized == 0);
    bool levels_changed = false;
    if (!first_write) {
        float snapshot[MQL::N_SNAPSHOT];
        MQL_LoadSnapshot(sc, snapshot);
        levels_changed = MQL_LevelsChanged(levels, snapshot);
    }

    // ── 3. Determine date for path Hive + nouveau jour detection ─────────────
    SCDateTime bar_dt = sc.BaseDateTimeIn[sc.Index];
    int yyyy, mm, dd, hh, mi, ss, msv;
    bar_dt.GetDateTimeYMDHMS_MS(yyyy, mm, dd, hh, mi, ss, msv);
    (void)hh; (void)mi; (void)ss; (void)msv;
    int curr_ymd = yyyy * 10000 + mm * 100 + dd;
    bool new_day = (last_ymd != curr_ymd);

    // ── 4. Decision : write only if first / change / new day ─────────────────
    bool should_write = first_write || levels_changed || new_day;
    if (!should_write) return;

    // ── 5. Timestamp epoch ms UTC (parite avec DMP_Reader.h:2493) ─────────────
    long long ts_ms = (long long)((bar_dt.GetAsDouble() - 25569.0) * 86400.0) * 1000LL;

    // ── 6. Build path Hive ────────────────────────────────────────────────────
    char path[1024];
    MQL_BuildPath(path, sizeof(path), base_path, ctx.sym_name, yyyy, mm, dd);

    // ── 7. Build JSON line ────────────────────────────────────────────────────
    char buf_call[24], buf_put[24], buf_hvl[24];
    char buf_call0[24], buf_put0[24], buf_hvl0[24];
    char buf_1dmin[24], buf_1dmax[24];
    char buf_gex[256], buf_blind[256];
    char trigger_str[32];

    MQL_FormatLevel(buf_call,  sizeof(buf_call),  levels[0]);
    MQL_FormatLevel(buf_put,   sizeof(buf_put),   levels[1]);
    MQL_FormatLevel(buf_hvl,   sizeof(buf_hvl),   levels[2]);
    MQL_FormatLevel(buf_call0, sizeof(buf_call0), levels[3]);
    MQL_FormatLevel(buf_put0,  sizeof(buf_put0),  levels[4]);
    MQL_FormatLevel(buf_hvl0,  sizeof(buf_hvl0),  levels[5]);
    MQL_FormatLevel(buf_1dmin, sizeof(buf_1dmin), levels[6]);
    MQL_FormatLevel(buf_1dmax, sizeof(buf_1dmax), levels[7]);
    MQL_FormatLevelArray(buf_gex,   sizeof(buf_gex),   &levels[8],  MQL::N_GEX);
    MQL_FormatLevelArray(buf_blind, sizeof(buf_blind), &levels[18], MQL::N_BLIND);

    if (first_write)         snprintf(trigger_str, sizeof(trigger_str), "init");
    else if (new_day)        snprintf(trigger_str, sizeof(trigger_str), "new_day");
    else                     snprintf(trigger_str, sizeof(trigger_str), "level_change");

    char line[1536];
    int line_n = snprintf(line, sizeof(line),
        "{\"ts\":%lld,\"sym\":\"%s\",\"schema_version\":\"mq_levels_1.0\","
        "\"trigger\":\"%s\","
        "\"mq_call\":%s,\"mq_put\":%s,\"mq_hvl\":%s,"
        "\"mq_call_0dte\":%s,\"mq_put_0dte\":%s,\"mq_hvl_0dte\":%s,"
        "\"mq_1d_min\":%s,\"mq_1d_max\":%s,"
        "\"mq_gex\":%s,\"mq_blind\":%s}",
        ts_ms, ctx.sym_name, trigger_str,
        buf_call, buf_put, buf_hvl,
        buf_call0, buf_put0, buf_hvl0,
        buf_1dmin, buf_1dmax,
        buf_gex, buf_blind);

    if (line_n < 0 || (size_t)line_n >= sizeof(line)) {
        sc.AddMessageToLog("MQ_Lite: JSON line truncated, skipping write", 1);
        return;
    }

    // ── 8. Append + update snapshot UNIQUEMENT si write reussi ───────────────
    //  Si write echoue (disque plein, permission, lock antivirus) → snapshot
    //  pas mis a jour, la prochaine barre re-tentera. Anti-perte silencieuse.
    bool write_ok = MQL_AppendLine(sc, path, line);
    if (!write_ok) return;

    MQL_SaveSnapshot(sc, levels);
    initialized = 1;
    last_ymd = curr_ymd;

    // Log info trigger (visible Sierra journal pour debug)
    char info[256];
    snprintf(info, sizeof(info), "MQ_Lite %s: write trigger=%s ts=%lld",
             ctx.sym_name, trigger_str, ts_ms);
    sc.AddMessageToLog(info, 0);
}

// =============================================================================
// SCSFExport ES (a attacher sur Chart 25)
// =============================================================================

SCSFExport scsf_MIA_MQ_Lite_ES(SCStudyInterfaceRef sc) {

    if (sc.SetDefaults) {
        sc.GraphName             = "MIA MQ Lite — ES (levels JSONL)";
        sc.StudyDescription      = "Dump 24 niveaux MenthorQ ES quand changement detecte. "
                                   "Output: DATA/mq_levels/ES/year=YYYY/month=M/day=D/levels.jsonl. "
                                   "Schema mq_levels_1.0. ~5 lignes/jour. Chart hote: 25 (ES_BARRES). "
                                   "Lecture cross-chart: 31 (ES_COMPOSITE) pour Blind Spots.";
        sc.AutoLoop              = 1;
        sc.GraphRegion           = 0;
        sc.DrawZeros             = 0;
        sc.UpdateAlways          = 1;
        sc.CalculationPrecedence = LOW_PREC_LEVEL;
        sc.MaintainAdditionalChartDataArrays = 1;

        sc.Input[0].Name = "Repertoire de sortie";
        sc.Input[0].SetDescription("Chemin base. Sous-dossier mq_levels/ES/year=.../ "
                                    "cree automatiquement.");
        sc.Input[0].SetString("C:\\TRADING_SIERRA_CHART_AUTO\\DATA");
        return;
    }

    if (sc.LastCallToFunction) return;
    if (sc.ServerConnectionState != SCS_CONNECTED) return;
    if (sc.Index < sc.ArraySize - 2) return;
    if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED) return;
    if (sc.Index < 10) return;

    int& last_bar = sc.GetPersistentInt(MQL::P_LAST_BAR_IDX);
    if (sc.Index <= last_bar) return;
    last_bar = sc.Index;

    const char* base_path = sc.Input[0].GetString();
    if (!base_path || base_path[0] == '\0') {
        static bool s_warned = false;
        if (!s_warned) {
            sc.AddMessageToLog("MQ_Lite ES: Input[0] base path vide", 1);
            s_warned = true;
        }
        return;
    }

    MQL_SymContext ctx;
    ctx.chart_gamma = MQL::CHART_ES_GAMMA;   // 25
    ctx.chart_blind = MQL::CHART_ES_BLIND;   // 31
    ctx.study_gamma = MQL::STUDY_MQ_GAMMA_ES;
    ctx.study_blind = MQL::STUDY_MQ_BLIND_ES;
    ctx.sym_name    = "ES";

    MQL_ProcessBar(sc, ctx, base_path);
}

// =============================================================================
// SCSFExport NQ (a attacher sur Chart 23)
// =============================================================================

SCSFExport scsf_MIA_MQ_Lite_NQ(SCStudyInterfaceRef sc) {

    if (sc.SetDefaults) {
        sc.GraphName             = "MIA MQ Lite — NQ (levels JSONL)";
        sc.StudyDescription      = "Dump 24 niveaux MenthorQ NQ quand changement detecte. "
                                   "Output: DATA/mq_levels/NQ/year=YYYY/month=M/day=D/levels.jsonl. "
                                   "Schema mq_levels_1.0. ~5 lignes/jour. Chart hote: 23 (NQ_BARRES). "
                                   "Lecture cross-chart: 30 (NQ_COMPOSITE) pour Blind Spots.";
        sc.AutoLoop              = 1;
        sc.GraphRegion           = 0;
        sc.DrawZeros             = 0;
        sc.UpdateAlways          = 1;
        sc.CalculationPrecedence = LOW_PREC_LEVEL;
        sc.MaintainAdditionalChartDataArrays = 1;

        sc.Input[0].Name = "Repertoire de sortie";
        sc.Input[0].SetDescription("Chemin base. Sous-dossier mq_levels/NQ/year=.../ "
                                    "cree automatiquement.");
        sc.Input[0].SetString("C:\\TRADING_SIERRA_CHART_AUTO\\DATA");
        return;
    }

    if (sc.LastCallToFunction) return;
    if (sc.ServerConnectionState != SCS_CONNECTED) return;
    if (sc.Index < sc.ArraySize - 2) return;
    if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED) return;
    if (sc.Index < 10) return;

    int& last_bar = sc.GetPersistentInt(MQL::P_LAST_BAR_IDX);
    if (sc.Index <= last_bar) return;
    last_bar = sc.Index;

    const char* base_path = sc.Input[0].GetString();
    if (!base_path || base_path[0] == '\0') {
        static bool s_warned = false;
        if (!s_warned) {
            sc.AddMessageToLog("MQ_Lite NQ: Input[0] base path vide", 1);
            s_warned = true;
        }
        return;
    }

    MQL_SymContext ctx;
    ctx.chart_gamma = MQL::CHART_NQ_GAMMA;   // 23
    ctx.chart_blind = MQL::CHART_NQ_BLIND;   // 30
    ctx.study_gamma = MQL::STUDY_MQ_GAMMA_NQ;
    ctx.study_blind = MQL::STUDY_MQ_BLIND_NQ;
    ctx.sym_name    = "NQ";

    MQL_ProcessBar(sc, ctx, base_path);
}

// =============================================================================
// SCSFExport GC (a attacher sur Chart 34 = GCM26-COMEX[M])
// =============================================================================
// Architecture differente d'ES/NQ : MQ_BLIND est sur la MEME chart (34) que
// MQ_GAMMA, pas sur une chart Composite separee. C'est suffisant pour Gold
// car MenthorQ ne fournit pas de chart Composite pour GC. Les PersistentInt
// (P_LAST_BAR_IDX=152 etc.) sont par-chart dans Sierra Chart, donc reutiliser
// les memes indices que ES/NQ ne pose aucun conflit.
// Verifie 10/05/2026 sur screenshot Jackson :
//   - Chart 34 study ID:2  = MenthorQ Gamma Levels (102 ms)
//   - Chart 34 study ID:22 = MenthorQ Blind Spots Levels (118 ms)
// =============================================================================

SCSFExport scsf_MIA_MQ_Lite_GC(SCStudyInterfaceRef sc) {

    if (sc.SetDefaults) {
        sc.GraphName             = "MIA MQ Lite — GC (levels JSONL)";
        sc.StudyDescription      = "Dump 24 niveaux MenthorQ GC (Gold) quand changement detecte. "
                                   "Output: DATA/mq_levels/GC/year=YYYY/month=M/day=D/levels.jsonl. "
                                   "Schema mq_levels_1.0. ~5 lignes/jour. Chart hote: 34 (GCM26-COMEX). "
                                   "MQ_BLIND lu sur la MEME chart 34 (pas de Composite separe pour Gold).";
        sc.AutoLoop              = 1;
        sc.GraphRegion           = 0;
        sc.DrawZeros             = 0;
        sc.UpdateAlways          = 1;
        sc.CalculationPrecedence = LOW_PREC_LEVEL;
        sc.MaintainAdditionalChartDataArrays = 1;

        sc.Input[0].Name = "Repertoire de sortie";
        sc.Input[0].SetDescription("Chemin base. Sous-dossier mq_levels/GC/year=.../ "
                                    "cree automatiquement.");
        sc.Input[0].SetString("C:\\TRADING_SIERRA_CHART_AUTO\\DATA");
        return;
    }

    if (sc.LastCallToFunction) return;
    if (sc.ServerConnectionState != SCS_CONNECTED) return;
    if (sc.Index < sc.ArraySize - 2) return;
    if (sc.GetBarHasClosedStatus(sc.Index) != BHCS_BAR_HAS_CLOSED) return;
    if (sc.Index < 10) return;

    int& last_bar = sc.GetPersistentInt(MQL::P_LAST_BAR_IDX);
    if (sc.Index <= last_bar) return;
    last_bar = sc.Index;

    const char* base_path = sc.Input[0].GetString();
    if (!base_path || base_path[0] == '\0') {
        static bool s_warned = false;
        if (!s_warned) {
            sc.AddMessageToLog("MQ_Lite GC: Input[0] base path vide", 1);
            s_warned = true;
        }
        return;
    }

    MQL_SymContext ctx;
    ctx.chart_gamma = MQL::CHART_GC_GAMMA;   // 34
    ctx.chart_blind = MQL::CHART_GC_BLIND;   // 34 (meme chart que Gamma)
    ctx.study_gamma = MQL::STUDY_MQ_GAMMA_GC;
    ctx.study_blind = MQL::STUDY_MQ_BLIND_GC;
    ctx.sym_name    = "GC";

    MQL_ProcessBar(sc, ctx, base_path);
}

// =============================================================================
// FIN MQ_Lite.cpp v2.4 — schema mq_levels_1.0 — 2026-05-10
// v2.4 (2026-05-10) : ajout scsf_MIA_MQ_Lite_GC pour Gold (GCM26-COMEX, chart 34)
//                     architecture simplifiee : MQ_BLIND sur meme chart 34
//                     que MQ_GAMMA (pas de Composite separe pour Gold).
//                     A attacher sur chart 34 + retirer "MIA MQ Lite – ES" qui
//                     y a ete attache par erreur (visible screenshot ID:45).
// v2.3 (2026-04-28) : fix default Input[0] path D:\ → C:\ (cible VPS prod).
// =============================================================================
