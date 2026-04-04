#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Writer.h  —  MIA Data Dumper G3 : Section E — SÉRIALISATION JSONL
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle : Écrire les 195 colonnes de DMP_MLFeatures en format JSONL.
//         Un fichier par jour de trading, rotation automatique à minuit.
//         FLT_MAX (DMP_INVALID) → "null" JSON pour compatibilité pandas/sklearn.
//
//  ── FORMAT DE SORTIE ─────────────────────────────────────────────────────────
//
//  Format : JSON Lines (JSONL) — un objet JSON par ligne
//  Path   : D:\TRADING_SIERRA_CHART_AUTO\DATA\{SYM}\YYYYMMDD_{SYM}.jsonl
//  Exemple: D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\20260303_ES.jsonl
//
//  Lecture Python (pandas) :
//    import pandas as pd
//    df = pd.read_json("20260303_ES.jsonl", lines=True)
//
//  Ligne example :
//    {"ts":1741024201000,"sym":"ES","price":5876.25,"atr":45.3,
//     "dist_vwap_d":-8.5,"dist_vwap_d_atr":-0.187,...,"lvn_between":0}
//
//  Valeurs INVALID → null JSON (NaN-safe pour pandas/sklearn) :
//    {"dist_vwap_w":null,"dist_vwap_m":null,...}  ← VWAP weekly manquant
//
//  ── FICHIERS GÉNÉRÉS ─────────────────────────────────────────────────────────
//
//  Fichier principal : YYYYMMDD_{SYM}.jsonl
//    → 1 ligne JSON par barre 1-min (environ 390 lignes/session RTH)
//    → Toutes les 158 colonnes
//
//  Fichier meta : YYYYMMDD_{SYM}.meta.json
//    → Écrit UNE SEULE FOIS au début de session
//    → Contient : colonnes, version, symbole, date, tick_size
//    → Utile pour validation avant chargement Python
//
//  ── ÉTAT INTERNE (sc.GetPersistentInt / static map) ─────────────────────────
//
//  Problème Sierra Chart ACSIL : les études sont appelées sur chaque barre.
//  → Solution : fopen("a") / fwrite / fclose à CHAQUE barre (pattern ancien dumper)
//               Pas de handle persistant → zéro problème lors des recompilations.
//               fclose() force Windows à mettre à jour les métadonnées (taille).
//               static std::unordered_map<int, DMP_WriterState*>
//               clé = sc.ChartNumber (unique par instance d'étude)
//
//  ── PERFORMANCE ──────────────────────────────────────────────────────────────
//
//  Buffer ligne JSON : char buf[DMP_JSON_BUF_SIZE] = 12288 octets (12 KB)
//    → 158 champs × ~50 chars/champ = ~7900 chars max → 12 KB = marge sécurité
//  Flush explicite tous les DMP_FLUSH_INTERVAL = 5 barres
//    → Données accessibles en Python dans la minute
//    → Protection contre crash Sierra Chart (perte max = 5 barres)
//  Écriture directe (pas de buffer en mémoire) : acceptable car ACSIL monothread
//
//  ── INDICES PERSISTANTS ──────────────────────────────────────────────────────
//
//  sc.GetPersistentInt(90) = jour courant (pour détecter rotation)
//  sc.GetPersistentInt(91) = lignes écrites session courante
//  sc.GetPersistentInt(92) = total lignes écrites all sessions
//  Indices 50-89 réservés par DMP_HVN_LVN.h et DMP_OpenType.h
//
//  Dépendances :
//    ← DMP_OpenType.h (inclut toute la chaîne : Transform ← HVN_LVN ← Reader)
//
//  Auteur : MIA Trading System — v1.0 — 2026-02-28
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_OpenType.h"     // Toute la chaîne d'includes
#include <fstream>
#include <sstream>
#include <unordered_map>
#include <string>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <cfloat>
#include <sys/stat.h>         // mkdir sur Windows (SierraChart compile avec MSVC)

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// ── Buffer de sérialisation JSON ──────────────────────────────────────────────
// 158 champs × ~70 chars/champ = ~11060 chars + clés JSON → 12 KB sécurisé
constexpr int  DMP_JSON_BUF_SIZE   = 16384;  // 16 KB — marge confortable

// ── Flush périodique ──────────────────────────────────────────────────────────
// Flush tous les N barres pour limiter la perte de données en cas de crash SC
constexpr int  DMP_FLUSH_INTERVAL  = 5;      // 5 barres 1-min = 5 min max de perte

// ── Répertoire de base (peut être surchargé via sc.Input dans DMP_Main.cpp) ──
constexpr char DMP_BASE_PATH[]  = "D:\\TRADING_SIERRA_CHART_AUTO\\DATA";

// ── Indices sc.GetPersistentInt ───────────────────────────────────────────────
// Indices 50-89 pris par DMP_HVN_LVN.h (50-74) et DMP_OpenType.h (80-89)
constexpr int DMP_WR_P_DAY          = 90;   // Jour courant (YYYYMMDD) pour détection rotation
constexpr int DMP_WR_P_ROWS_TODAY   = 91;   // Lignes écrites session courante
constexpr int DMP_WR_P_ROWS_TOTAL   = 92;   // Total lignes toutes sessions

// ── Version du format pour le meta.json ──────────────────────────────────────
constexpr int  DMP_FORMAT_VERSION   = 3;    // G3-Unifier v1.0

// ── Répertoire de debug logs ─────────────────────────────────────────────────
constexpr char DMP_DEBUG_PATH[]  = "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DEBUG";

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — ÉTAT INTERNE DU WRITER
// ═══════════════════════════════════════════════════════════════════════════════

// État complet d'un writer (une instance par symbole ES ou NQ)
struct DMP_WriterState {
    // PAS de std::ofstream — on utilise fopen("a")/fwrite/fclose par barre
    // exactement comme l'ancien dumper MIA_Dumper_G3_Unifier.cpp (prouvé fonctionnel).
    // fclose() force Windows à mettre à jour les métadonnées du fichier (taille).
    bool           file_ready;          // true = data_path est valide, prêt à écrire
    std::ofstream  meta_file;           // Fichier .meta.json (écrit 1 fois/session)
    int            current_day;         // YYYYMMDD — détection rotation
    char           current_contract[32]; // Contrat en cours — détection rollover
    int            rows_session;        // Lignes écrites cette session
    int            flush_counter;       // (réservé — plus utilisé avec fopen/fclose)
    bool           meta_written;        // Guard : meta écrit une seule fois
    char           data_path[512];      // Path courant (pour log diagnostic)
    char           meta_path[512];      // Path meta courant
    long long      prev_ts;             // ⚠️ FIX 04/03/2026 : dedup timestamp per-study
                                        //   (static était PARTAGÉ entre ES et NQ → NQ=0Ko)

    DMP_WriterState() :
        file_ready(false), current_day(0), rows_session(0),
        flush_counter(0), meta_written(false), prev_ts(0)
    {
        data_path[0] = '\0';
        meta_path[0] = '\0';
        current_contract[0] = '\0';
    }
};

// Map globale : StudyGraphID → WriterState*
// Clé = sc.ChartNumber (identifiant unique par instance d'étude SC)
// Accès thread-safe : ACSIL est monothread par étude, pas de conflit
static std::unordered_map<int, DMP_WriterState*> s_dmp_writers;

// Obtenir ou créer le state pour une étude donnée
static inline DMP_WriterState* DMP_WR_GetState(int study_id) {
    auto it = s_dmp_writers.find(study_id);
    if (it != s_dmp_writers.end()) return it->second;
    DMP_WriterState* st = new DMP_WriterState();
    s_dmp_writers[study_id] = st;
    return st;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — GESTION DES CHEMINS
// ═══════════════════════════════════════════════════════════════════════════════

// Créer les répertoires récursivement (approche prouvée MIA_Dumper_G3_Unifier)
// Prend un chemin de DOSSIER (pas de fichier) et crée chaque niveau.
static inline bool DMP_WR_EnsureDir(const char* path) {
#ifdef _WIN32
    if (!path || !*path) return false;
    std::string p(path);
    // Normaliser les séparateurs
    for (auto& ch : p) if (ch == '/') ch = '\\';
    // Supprimer trailing backslash
    while (!p.empty() && p.back() == '\\') p.pop_back();
    if (p.empty()) return false;

    // Créer chaque niveau du chemin itérativement
    std::string cur;
    for (size_t i = 0; i < p.size(); ++i) {
        cur.push_back(p[i]);
        if (p[i] == '\\') {
            if (cur.size() > 3)  // éviter "D:\"
                CreateDirectoryA(cur.c_str(), NULL);
        }
    }
    // Créer le dernier niveau
    BOOL ok = CreateDirectoryA(p.c_str(), NULL);
    return ok || GetLastError() == ERROR_ALREADY_EXISTS;
#else
    return mkdir(path, 0755) == 0 || errno == EEXIST;
#endif
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3b — DEBUG LOG FICHIER
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Écrit dans : D:\TRADING_SIERRA_CHART_AUTO\LOGS\DEBUG\DMP_debug_YYYYMMDD_SYM.log
//  Avantages vs sc.AddMessageToLog :
//    - Persistant (survit au restart SC)
//    - Pas de limite de lignes
//    - Grep-able PowerShell : Get-Content .\DMP_debug_*.log | Select-String "SKIP"
//    - Horodatage barre précis

static inline void DMP_DebugLog(SCStudyInterfaceRef sc, const char* sym, const char* msg) {
#ifdef _WIN32
    // Créer les dossiers
    DMP_WR_EnsureDir("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS");
    DMP_WR_EnsureDir(DMP_DEBUG_PATH);

    // Fichier journalier : DMP_debug_YYYYMMDD_ES.log
    int y = 0, mo = 0, d = 0;
    sc.CurrentSystemDateTime.GetDateYMD(y, mo, d);
    char path[512];
    snprintf(path, sizeof(path), "%s\\DMP_debug_%04d%02d%02d_%s.log",
             DMP_DEBUG_PATH, y, mo, d, sym);

    // Horodatage HH:MM:SS depuis la barre courante
    int h = 0, m = 0, s = 0;
    if (sc.Index >= 0 && sc.Index < sc.ArraySize) {
        SCDateTime bar_time = sc.BaseDateTimeIn[sc.Index];
        bar_time.GetTimeHMS(h, m, s);
    }

    FILE* f = fopen(path, "a");
    if (f) {
        fprintf(f, "[%02d:%02d:%02d] bar#%d | %s\n", h, m, s, sc.Index, msg);
        fclose(f);
    }
#endif
    // Aussi dans le log SC pour visibilité immédiate
    sc.AddMessageToLog(msg, 0);
}

// Construire le chemin du fichier .jsonl et .meta.json
//   base   : "D:\TRADING_SIERRA_CHART_AUTO\DATA"
//   sym    : "ES" ou "NQ"
//   date   : 20260303 (entier)
//   out_data : buffer de sortie pour le path .jsonl
//   out_meta : buffer de sortie pour le path .meta.json

static inline void DMP_WR_BuildPaths(
    const char* base, const char* sym, int date,
    char* out_data, size_t out_data_size,
    char* out_meta, size_t out_meta_size)
{
    // Dossier : BASE/SYM
    char dir_path[256];

    // D'abord créer le dossier BASE s'il n'existe pas
    DMP_WR_EnsureDir(base);

    // Puis créer BASE\SYM
    snprintf(dir_path, sizeof(dir_path), "%s\\%s", base, sym);
    DMP_WR_EnsureDir(dir_path);

    // Fichier : YYYYMMDD_SYM.jsonl
    snprintf(out_data, out_data_size, "%s\\%08d_%s.jsonl", dir_path, date, sym);
    snprintf(out_meta, out_meta_size, "%s\\%08d_%s.meta.json", dir_path, date, sym);
}

// Obtenir la DATE DE TRADING comme entier YYYYMMDD
// Règle : la journée de trading commence à 18h00 ET (début Asia).
//   - Barre à lundi 18:01 ET → fichier du mardi (US session = mardi)
//   - Barre à lundi 15:30 ET → fichier du lundi (US session = lundi)
//   - Barre à dimanche 18:00 ET → fichier du lundi (globex ouvre dimanche soir)
// Utilise l'heure de la BARRE (pas l'horloge PC) pour cohérence avec les données.
//
// ⚠️ FIX 04/03/2026 : l'ancien code ajoutait +1 jour à la date UTC, pas ET.
//  Entre 00:00 et 04:59 UTC (19h-00h ET), la date UTC est DÉJÀ +1 vs ET.
//  Ajouter encore +1 donnait trading_date = date réelle + 2 jours.
//  Fix : convertir en OLE ET d'abord, puis appliquer la règle >= 18h sur la date ET.
static inline int DMP_WR_GetTradingDateInt(SCStudyInterfaceRef sc) {
    SCDateTime bar_time = sc.BaseDateTimeIn[sc.Index];

    // Convertir en UTC puis en heure ET — même méthode que DMP_Reader.h
    // On ne fait PAS confiance à GetTimeHMS (dépend du timezone du chart)
    long long ts_ms = (long long)((bar_time.GetAsDouble() - 25569.0) * 86400.0) * 1000LL;
    time_t sec = (time_t)(ts_ms / 1000);
#ifdef _WIN32
    struct tm gm_val{};
    gmtime_s(&gm_val, &sec);
    int h_utc = gm_val.tm_hour;
#else
    struct tm gm_buf{};
    gmtime_r(&sec, &gm_buf);
    int h_utc = gm_buf.tm_hour;
#endif
    int h_et = (h_utc - 5 + 24) % 24;

    // ── Convertir bar_time en date ET (OLE) ───────────────────────────────
    //  bar_time est en UTC. On soustrait 5h pour obtenir la date ET.
    //  Exemple : 00:03 UTC le 4 mars → 19:03 ET le 3 mars.
    //  Sans cette conversion, le +1 ci-dessous s'appliquait à la date UTC
    //  (déjà le 4) et donnait le 5 au lieu du 4.
    double bar_et_ole = bar_time.GetAsDouble() - (5.0 / 24.0);  // -5h → ET

    // Si >= 18h ET → avancer au jour suivant (nouvelle journée de trading)
    SCDateTime trading_dt;
    if (h_et >= 18) {
        trading_dt = bar_et_ole + 1.0;  // +1 jour depuis la date ET
    } else {
        trading_dt = bar_et_ole;         // même journée de trading ET
    }

    int y = 0, mo = 0, d = 0;
    trading_dt.GetDateYMD(y, mo, d);
    return y * 10000 + mo * 100 + d;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — OUVERTURE / FERMETURE / ROTATION
// ═══════════════════════════════════════════════════════════════════════════════

// Fermer les fichiers proprement (log + reset)
static inline void DMP_WR_Close(DMP_WriterState* st, SCStudyInterfaceRef sc) {
    if (st->file_ready) {
        char msg[256];
        snprintf(msg, sizeof(msg),
            "FILE CLOSE — %s | %d lignes écrites", st->data_path, st->rows_session);
        DMP_DebugLog(sc, "DMP", msg);
        st->file_ready = false;
    }
    if (st->meta_file.is_open()) {
        st->meta_file.close();
    }
}

// Ouvrir le fichier pour un nouveau jour de trading
static inline bool DMP_WR_Open(
    DMP_WriterState* st, SCStudyInterfaceRef sc,
    const char* base_path, const char* sym, int date)
{
    // Fermer l'ancien fichier si ouvert
    DMP_WR_Close(st, sc);

    // Reset compteurs session
    st->rows_session  = 0;
    st->flush_counter = 0;
    st->meta_written  = false;
    st->prev_ts       = 0;       // Reset dedup pour nouvelle session
    st->current_day   = date;

    // Construire les chemins
    DMP_WR_BuildPaths(base_path, sym, date,
                      st->data_path, sizeof(st->data_path),
                      st->meta_path, sizeof(st->meta_path));

    // Valider que le fichier est accessible en écriture (test fopen/fclose)
    // Pattern identique à l'ancien dumper : pas de handle persistant.
    // Chaque DMP_WriteRow fera son propre fopen("a") / fwrite / fclose.
    {
        FILE* test_fp = fopen(st->data_path, "a");
        if (!test_fp) {
            char msg[384];
            snprintf(msg, sizeof(msg),
                "FILE OPEN FAIL — %s (fopen test echoue)", st->data_path);
            DMP_DebugLog(sc, sym, msg);
            st->file_ready = false;
            return false;
        }
        fclose(test_fp);  // Fermer immédiatement
    }

    st->file_ready = true;

    char msg[384];
    snprintf(msg, sizeof(msg),
        "FILE OPEN OK — %s | date=%d | rth_only=voir Input[2]", st->data_path, date);
    DMP_DebugLog(sc, sym, msg);
    return true;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — FICHIER META.JSON
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Écrit UNE SEULE FOIS par session (première barre RTH).
//  Contient : version, symbole, date, tick_size, noms des colonnes dans l'ordre.
//  Permet au lecteur Python de valider le format sans parser les données.
//
//  Format :
//  {
//    "version": 3,
//    "sym": "ES",
//    "date": "2026-03-03",
//    "tick_size": 0.25,
//    "n_columns": 208,
//    "columns": ["ts","sym","price","atr","dist_vwap_d",...]
//  }

static inline void DMP_WR_WriteMeta(
    DMP_WriterState* st, SCStudyInterfaceRef sc,
    const char* sym, int date, float tick_size)
{
    if (st->meta_written) return;

    std::ofstream meta;
    meta.open(st->meta_path, std::ios::out | std::ios::trunc);
    if (!meta.is_open()) {
        char msg[256];
        snprintf(msg, sizeof(msg),
            "[DMP_Writer] ⚠️ Impossible d'écrire meta : %s", st->meta_path);
        sc.AddMessageToLog(msg, 1);
        return;
    }

    // Date ISO 8601
    char date_str[16];
    snprintf(date_str, sizeof(date_str), "%04d-%02d-%02d",
             date / 10000, (date / 100) % 100, date % 100);

    meta << "{\n";
    meta << "  \"version\": "  << DMP_FORMAT_VERSION << ",\n";
    meta << "  \"sym\": \""    << sym                << "\",\n";
    meta << "  \"date\": \""   << date_str           << "\",\n";
    meta << "  \"tick_size\": "<< tick_size           << ",\n";
    meta << "  \"n_columns\": " << 208               << ",\n";
    meta << "  \"format\": \"jsonl\",\n";
    meta << "  \"invalid_sentinel\": null,\n";
    meta << "  \"columns\": [\n";
    meta << "    \"ts\",\"sym\",\"contract\",\"price\",\"atr\",\"session\",\"session_id\",\n";
    meta << "    \"dist_vwap_d\",\"dist_vwap_d_atr\",\"dist_vwap_d_sd1u\",\"dist_vwap_d_sd1d\",\n";
    meta << "    \"dist_vwap_d_sd2u\",\"dist_vwap_d_sd2d\",\"dist_vwap_w\",\"dist_vwap_w_atr\",\n";
    meta << "    \"dist_vwap_m\",\"dist_vwap_m_atr\",\"vwap_d_side\",\"vwap_w_side\",\"vwap_m_side\",\n";
    meta << "    \"dist_cur_vpoc\",\"dist_cur_vah\",\"dist_cur_val\",\"dist_cur_vwap_vp\",\"va_position_pct\",\"inside_cur_va\",\n";
    meta << "    \"range_pos\",\"range_size_ticks\",\"momentum_3b\",\"momentum_5b\",\"cvd_bar_delta\",\n";
    meta << "    \"vah_touches_20b\",\"val_touches_20b\",\"bars_in_va\",\n";
    meta << "    \"dist_prev_vpoc\",\"dist_prev_vpoc_atr\",\"dist_prev_vah\",\"dist_prev_val\",\n";
    meta << "    \"dist_prev_vwap\",\"dist_prev_vwap_sd1u\",\"dist_prev_vwap_sd1d\",\n";
    meta << "    \"inside_prev_va\",\"open_in_prev_va\",\n";
    meta << "    \"dist_1d_min_ticks\",\"dist_1d_max_ticks\",\n";
    meta << "    \"next_wall_dist_ticks\",\"next_wall_is_call\",\n";
    meta << "    \"dist_mq_call\",\"dist_mq_put\",\"dist_mq_hvl\",\"dist_mq_call_0dte\",\"dist_mq_put_0dte\",\n";
    meta << "    \"dist_gex_nearest_up\",\"dist_gex_nearest_dn\",\"gex_cluster_count\",\n";
    meta << "    \"dist_blind_nearest_up\",\"dist_blind_nearest_dn\",\n";
    meta << "    \"vix_level\",\"dist_vix_hvl\",\"vix_regime\",\"vix_above_hvl\",\n";
    meta << "    \"dist_ib_high\",\"dist_ib_low\",\"ib_range_ticks\",\"ib_range_atr\",\n";
    meta << "    \"ib_is_narrow\",\"ib_is_wide\",\"ib_position_pct\",\n";
    meta << "    \"ib_broken_up\",\"ib_broken_down\",\"ib_complete\",\n";
    meta << "    \"dist_sess_high\",\"dist_sess_low\",\"sess_range_ticks\",\"sess_range_atr\",\n";
    meta << "    \"dist_open_cash\",\"dist_open_830\",\"dist_ovn_high\",\"dist_ovn_low\",\n";
    meta << "    \"ovn_range_ticks\",\"open_gap_ticks\",\"open_position\",\n";
    meta << "    \"dist_comp_20d_vpoc\",\"dist_comp_20d_vpoc_atr\",\"dist_comp_20d_vah\",\"dist_comp_20d_val\",\"dist_comp_20d_vwap\",\n";
    meta << "    \"dist_comp_50d_vpoc\",\"dist_comp_50d_vpoc_atr\",\"dist_comp_50d_vah\",\"dist_comp_50d_val\",\"dist_comp_50d_vwap\",\n";
    meta << "    \"inside_comp_20d_va\",\"inside_comp_50d_va\",\n";
    meta << "    \"comp_vpoc_align_20_50\",\"comp_vpoc_align_day_20\",\n";
    meta << "    \"delta_bar\",\"delta_bar_vol_norm\",\"delta_day\",\"delta_day_dir\",\n";
    meta << "    \"ask_pct\",\"bid_pct\",\"ask_bid_imbalance\",\n";
    meta << "    \"avg_trade_size\",\"avg_bid_size\",\"avg_ask_size\",\n";
    meta << "    \"large_trader_ratio\",\"vol_per_sec\",\"bar_duration_sec\",\n";
    meta << "    \"finish_strength\",\"poc_bar_dist\",\n";
    meta << "    \"cvd_day\",\"cvd_day_dir\",\"cvd_ohlc_range\",\n";
    meta << "    \"rotation_up\",\"rotation_dn\",\"rotation_zz_osc\",\"delta_divergence\",\n";
    meta << "    \"buy_vol\",\"sell_vol\",\"buy_sell_ratio\",\"total_vol\",\n";
    meta << "    \"delta_pct\",\"ticks_count\",\"finish_delta_pct\",\n";
    meta << "    \"high_pullback_delta\",\"low_pullback_delta\",\n";
    meta << "    \"diag_pos_delta\",\"diag_neg_delta\",\"diag_imbalance\",\n";
    meta << "    \"low_bid_vol_pct\",\"high_ask_vol_pct\",\n";
    meta << "    \"bn_color_up\",\"bn_color_dn\",\"bn_color_up_2\",\"bn_color_dn_2\",\"bn_absorb_ask\",\"bn_absorb_bid\",\n";
    meta << "    \"bn_long_up\",\"bn_long_dn\",\"bn_pressure_ask\",\"bn_pressure_bid\",\n";
    meta << "    \"bn_score_raw\",\"bn_score_bull\",\"bn_score_bear\",\n";
    meta << "    \"dist_big_ask_nearest_up\",\"dist_big_ask_nearest_dn\",\n";
    meta << "    \"dist_big_bid_nearest_up\",\"dist_big_bid_nearest_dn\",\n";
    meta << "    \"n_big_ask_t1\",\"n_big_bid_t1\",\n";
    meta << "    \"n_big_ask_t2\",\"n_big_bid_t2\",\n";
    meta << "    \"n_big_ask_t3\",\"n_big_bid_t3\",\n";
    meta << "    \"n_big_ask_t4\",\"n_big_bid_t4\",\n";
    meta << "    \"big_ask_cluster_20t\",\"big_bid_cluster_20t\",\n";
    meta << "    \"big_ask_cluster_50t\",\"big_bid_cluster_50t\",\n";
    meta << "    \"big_ask_cluster_20t_t1\",\"big_bid_cluster_20t_t1\",\n";
    meta << "    \"big_ask_cluster_20t_t2\",\"big_bid_cluster_20t_t2\",\n";
    meta << "    \"big_ask_cluster_20t_t3\",\"big_bid_cluster_20t_t3\",\n";
    meta << "    \"big_ask_cluster_20t_t4\",\"big_bid_cluster_20t_t4\",\n";
    // G7B Bar Signals + Extension Lines (16 champs) — BUG #8
    meta << "    \"bar_color_up\",\"bar_color_dn\",\"bar_long_up_bar\",\"bar_long_dn_bar\",\n";
    meta << "    \"bar_long_dn_up\",\"bar_long_up_dn\",\"bar_edge_buy\",\"bar_edge_sell\",\n";
    meta << "    \"bar_pressure_ask\",\"bar_pressure_bid\",\n";
    meta << "    \"dist_ext_color_up\",\"dist_ext_color_dn\",\n";
    meta << "    \"dist_ext_long_up\",\"dist_ext_long_dn\",\n";
    meta << "    \"dist_ext_edge_buy\",\"dist_ext_edge_sell\",\n";
    // G7C Volume + Edge FP (4) — BUG #10
    meta << "    \"bn_volume_up\",\"bn_volume_dn\",\"fp_edge_buy\",\"fp_edge_sell\",\n";
    meta << "    \"dist_swing_high\",\"dist_swing_low\",\"swing_range_ticks\",\n";
    meta << "    \"price_vs_swing_mid\",\"new_swing_high\",\"new_swing_low\",\n";
    meta << "    \"open_type\",\"open_zone\",\"open_bias_conf\",\"open_direction\",\"day_type\",\"rule_80pct\",\n";
    meta << "    \"trend_day_probability\",\"ma_trend\",\"vwap_ma_align\",\n";
    meta << "    \"vwap_slope_10\",\"vwap_slope_30\",\"vwap_slope_10_dir\",\n";
    meta << "    \"bool_above_cur_vpoc\",\"bool_above_prev_vpoc\",\"bool_above_vwap_d\",\n";
    meta << "    \"bool_above_vwap_w\",\"bool_above_vwap_m\",\"bool_above_mq_hvl\",\"bool_above_mq_call\",\n";
    meta << "    \"bool_near_level\",\"bool_ib_inside\",\"bool_session_early\",\n";
    meta << "    \"vwap_triple_align\",\"bool_va_confluence\",\"bool_gex_flip_zone\",\n";
    meta << "    \"dist_session_hvn_above\",\"dist_session_hvn_below\",\n";
    meta << "    \"dist_session_lvn_above\",\"dist_session_lvn_below\",\n";
    meta << "    \"session_hvn_count\",\"session_lvn_count\",\n";
    meta << "    \"lvn_between\",\"hvn_between\",\"lvn_confluence_count\",\n";
    meta << "    \"profile_shape\",\"profile_skew\",\"poc_position\",\"volume_imbalance\",\n";
    meta << "    \"is_double_dist\",\"poc_separation_ticks\",\n";
    meta << "    \"single_print_mid\",\"single_print_count\",\"profile_hvn_dominant\",\n";
    meta << "    \"retest_high_count\",\"retest_low_count\",\n";
    meta << "    \"retest_high_delta_div\",\"retest_low_delta_div\",\n";
    meta << "    \"bars_since_retest_high\",\"bars_since_retest_low\",\n";
    meta << "    \"rvol\",\"rvol_zscore\",\"rvol_buy\",\"rvol_sell\",\n";
    meta << "    \"rvol_absorb_buy\",\"rvol_absorb_sell\"\n";
    meta << "  ]\n";
    meta << "}\n";
    meta.close();

    st->meta_written = true;
    char log[256];
    snprintf(log, sizeof(log), "[DMP_Writer] Meta écrit : %s", st->meta_path);
    sc.AddMessageToLog(log, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — SÉRIALISATION D'UN CHAMP JSON
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Helpers inline pour écrire chaque type de champ dans le buffer JSON.
//  Principe : construire le JSON en ajoutant des segments dans buf[].
//
//  DMP_INVALID (FLT_MAX) → "null"
//  float normal          → "valeur" avec 4 décimales pour distances, 2 pour prix
//  booléen (0/1)         → "0" ou "1"
//  entier                → entier

// Vérifier si une valeur float est INVALID
static inline bool DMP_WR_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f);
}

// Écrire un float dans le buffer JSON (null si INVALID)
// Retourne le nombre de caractères écrits
static inline int DMP_WR_WriteFloat(char* buf, int pos, float v, int decimals = 4) {
    if (DMP_WR_IsInvalid(v)) {
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "null");
    }
    // Choisir le format selon le nombre de décimales
    if (decimals == 2)
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%.2f", v);
    if (decimals == 1)
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%.1f", v);
    if (decimals == 0)
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%.0f", v);
    return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%.4f", v);
}

// Écrire un entier booléen (0 ou 1)
static inline int DMP_WR_WriteInt01(char* buf, int pos, float v) {
    if (DMP_WR_IsInvalid(v))
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "null");
    return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%d", (v > 0.5f) ? 1 : 0);
}

// Écrire un entier (enum ou compteur)
static inline int DMP_WR_WriteIntEnum(char* buf, int pos, float v) {
    if (DMP_WR_IsInvalid(v))
        return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "null");
    return pos + snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1, "%d", (int)v);
}

// Macro helper : écrire une clé + valeur float dans le buffer
// Utilisation : DMP_WR_KV(buf, pos, "dist_vwap_d", f.dist_vwap_d);
#define DMP_WR_KV(buf, pos, key, val) \
    pos += snprintf((buf) + (pos), DMP_JSON_BUF_SIZE - (pos) - 1, "\"" key "\":"); \
    pos  = DMP_WR_WriteFloat((buf), (pos), (val))

#define DMP_WR_KV2(buf, pos, key, val) \
    pos += snprintf((buf) + (pos), DMP_JSON_BUF_SIZE - (pos) - 1, "\"" key "\":"); \
    pos  = DMP_WR_WriteFloat((buf), (pos), (val), 2)

#define DMP_WR_KV0(buf, pos, key, val) \
    pos += snprintf((buf) + (pos), DMP_JSON_BUF_SIZE - (pos) - 1, "\"" key "\":"); \
    pos  = DMP_WR_WriteFloat((buf), (pos), (val), 0)

#define DMP_WR_KVB(buf, pos, key, val) \
    pos += snprintf((buf) + (pos), DMP_JSON_BUF_SIZE - (pos) - 1, "\"" key "\":"); \
    pos  = DMP_WR_WriteInt01((buf), (pos), (val))

#define DMP_WR_KVE(buf, pos, key, val) \
    pos += snprintf((buf) + (pos), DMP_JSON_BUF_SIZE - (pos) - 1, "\"" key "\":"); \
    pos  = DMP_WR_WriteIntEnum((buf), (pos), (val))

#define DMP_WR_COMMA(buf, pos) \
    (buf)[(pos)++] = ','

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — SÉRIALISATION D'UNE LIGNE JSONL
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Construit la représentation JSON complète de DMP_MLFeatures.
//  Les 158 champs sont écrits dans l'ordre exact du header CSV (Section 6 Transform).
//
//  ⚠️  L'ORDRE DOIT ÊTRE IDENTIQUE à DMP_WriteCSVHeader() dans DMP_Transform.h
//      pour garantir la cohérence avec les outils Python de lecture.
//
//  Conventions de précision :
//    - prix / prix bruts     → 2 décimales (ex: 5876.25)
//    - distances en ticks    → 2 décimales (ex: -8.50)
//    - distances en ATR      → 4 décimales (ex: -0.1875)
//    - ratios / pcts         → 4 décimales (ex: 0.6250)
//    - booléens              → 0 / 1 (int)
//    - enums                 → entier (ex: 2 pour NormVar)
//    - compteurs             → entier (ex: 3 HVN au-dessus)

static inline int DMP_FormatJSONL(const DMP_MLFeatures& f, char* buf) {
    int pos = 0;
    buf[pos++] = '{';

    // ── META (6 champs) ───────────────────────────────────────────────────────
    pos += snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1,
        "\"ts\":%lld,", f.ts);
    pos += snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1,
        "\"sym\":\"%s\",", f.sym);
    // ⚠️ FIX 11/03/2026 : f.contract peut contenir du garbage après le string
    //  valide si DMP_Transform ne null-termine pas à la bonne position (bug
    //  DMP_Transform.h L1335-1337 : null-termine pos 31 au lieu de pos i).
    //  On copie dans un buffer local et on force \0 au premier char non-ASCII.
    {
        char safe_contract[32];
        int k = 0;
        for (; k < 31 && f.contract[k] != '\0'; ++k) {
            unsigned char ch = (unsigned char)f.contract[k];
            if (ch < 0x20 || ch > 0x7E) break;  // Stop au premier garbage
            safe_contract[k] = f.contract[k];
        }
        safe_contract[k] = '\0';
        pos += snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1,
            "\"contract\":\"%s\",", safe_contract);
    }
    DMP_WR_KV2(buf, pos, "price", f.price);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV2(buf, pos, "atr",   f.atr);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "session", f.session); DMP_WR_COMMA(buf, pos);

    // session_id string (comme ancien dumper : "Asia"/"London"/"US")
    {
        const char* sid = "US";
        if (f.session < 0.5f) sid = "Asia";
        else if (f.session < 1.5f) sid = "London";
        pos += snprintf(buf + pos, DMP_JSON_BUF_SIZE - pos - 1,
            "\"session_id\":\"%s\",", sid);
    }

    // ── G1 VWAP (17 champs) ───────────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_vwap_d",      f.dist_vwap_d);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_d_atr",  f.dist_vwap_d_atr);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_d_sd1u", f.dist_vwap_d_sd1u); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_d_sd1d", f.dist_vwap_d_sd1d); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_d_sd2u", f.dist_vwap_d_sd2u); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_d_sd2d", f.dist_vwap_d_sd2d); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_w",      f.dist_vwap_w);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_w_atr",  f.dist_vwap_w_atr);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_m",      f.dist_vwap_m);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vwap_m_atr",  f.dist_vwap_m_atr);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_d_side",     f.vwap_d_side);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_w_side",     f.vwap_w_side);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_m_side",     f.vwap_m_side);      DMP_WR_COMMA(buf, pos);

    // ── G2 VP (14 champs) ────────────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_cur_vpoc",    f.dist_cur_vpoc);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_cur_vah",     f.dist_cur_vah);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_cur_val",     f.dist_cur_val);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_cur_vwap_vp", f.dist_cur_vwap_vp); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "va_position_pct",  f.va_position_pct);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "inside_cur_va",   f.inside_cur_va);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "range_pos",         f.range_pos);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "range_size_ticks",  f.range_size_ticks); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "momentum_3b",       f.momentum_3b);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "momentum_5b",       f.momentum_5b);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "cvd_bar_delta",     f.cvd_bar_delta);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "vah_touches_20b",   f.vah_touches_20b);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "val_touches_20b",   f.val_touches_20b);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bars_in_va",        f.bars_in_va);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vpoc",   f.dist_prev_vpoc);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vpoc_atr",f.dist_prev_vpoc_atr);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vah",    f.dist_prev_vah);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_val",    f.dist_prev_val);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vwap",   f.dist_prev_vwap);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vwap_sd1u",f.dist_prev_vwap_sd1u);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_prev_vwap_sd1d",f.dist_prev_vwap_sd1d);DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "inside_prev_va",  f.inside_prev_va);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "open_in_prev_va", f.open_in_prev_va);  DMP_WR_COMMA(buf, pos);

    // ── G3 MQ (18 champs) ────────────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_1d_min_ticks",    f.dist_1d_min_ticks);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_1d_max_ticks",    f.dist_1d_max_ticks);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "next_wall_dist_ticks",  f.next_wall_dist_ticks); DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "next_wall_is_call",    f.next_wall_is_call);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_mq_call",          f.dist_mq_call);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_mq_put",           f.dist_mq_put);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_mq_hvl",           f.dist_mq_hvl);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_mq_call_0dte",     f.dist_mq_call_0dte);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_mq_put_0dte",      f.dist_mq_put_0dte);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_gex_nearest_up",   f.dist_gex_nearest_up);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_gex_nearest_dn",   f.dist_gex_nearest_dn);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "gex_cluster_count",      f.gex_cluster_count);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_blind_nearest_up",  f.dist_blind_nearest_up);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_blind_nearest_dn",  f.dist_blind_nearest_dn);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV2(buf, pos, "vix_level",             f.vix_level);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_vix_hvl",           f.dist_vix_hvl);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vix_regime",            f.vix_regime);           DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "vix_above_hvl",         f.vix_above_hvl);        DMP_WR_COMMA(buf, pos);

    // ── G4 Session (21 champs) ────────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_ib_high",    f.dist_ib_high);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_ib_low",     f.dist_ib_low);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ib_range_ticks",  f.ib_range_ticks);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ib_range_atr",    f.ib_range_atr);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "ib_is_narrow",   f.ib_is_narrow);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "ib_is_wide",     f.ib_is_wide);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ib_position_pct", f.ib_position_pct); DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "ib_broken_up",   f.ib_broken_up);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "ib_broken_down", f.ib_broken_down);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "ib_complete",    f.ib_complete);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_sess_high",  f.dist_sess_high);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_sess_low",   f.dist_sess_low);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "sess_range_ticks",f.sess_range_ticks); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "sess_range_atr",  f.sess_range_atr);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_open_cash",  f.dist_open_cash);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_open_830",   f.dist_open_830);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_ovn_high",   f.dist_ovn_high);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_ovn_low",    f.dist_ovn_low);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ovn_range_ticks", f.ovn_range_ticks);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "open_gap_ticks",  f.open_gap_ticks);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "open_position",  f.open_position);    DMP_WR_COMMA(buf, pos);

    // ── G5 Composite (12 champs) ──────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_comp_20d_vpoc",    f.dist_comp_20d_vpoc);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_20d_vpoc_atr",f.dist_comp_20d_vpoc_atr);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_20d_vah",     f.dist_comp_20d_vah);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_20d_val",     f.dist_comp_20d_val);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_20d_vwap",    f.dist_comp_20d_vwap);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_50d_vpoc",    f.dist_comp_50d_vpoc);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_50d_vpoc_atr",f.dist_comp_50d_vpoc_atr);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_50d_vah",     f.dist_comp_50d_vah);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_50d_val",     f.dist_comp_50d_val);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_comp_50d_vwap",    f.dist_comp_50d_vwap);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "inside_comp_20d_va",   f.inside_comp_20d_va);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "inside_comp_50d_va",   f.inside_comp_50d_va);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "comp_vpoc_align_20_50",f.comp_vpoc_align_20_50);DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "comp_vpoc_align_day_20",f.comp_vpoc_align_day_20);DMP_WR_COMMA(buf, pos);

    // ── G6 OrderFlow (22 champs) ──────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "delta_bar",          f.delta_bar);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "delta_bar_vol_norm", f.delta_bar_vol_norm); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "delta_day",          f.delta_day);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "delta_day_dir",     f.delta_day_dir);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ask_pct",            f.ask_pct);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bid_pct",            f.bid_pct);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "ask_bid_imbalance",  f.ask_bid_imbalance);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "avg_trade_size",     f.avg_trade_size);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "avg_bid_size",       f.avg_bid_size);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "avg_ask_size",       f.avg_ask_size);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "large_trader_ratio", f.large_trader_ratio); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "vol_per_sec",        f.vol_per_sec);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bar_duration_sec",   f.bar_duration_sec);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "finish_strength",    f.finish_strength);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "poc_bar_dist",       f.poc_bar_dist);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "cvd_day",            f.cvd_day);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "cvd_day_dir",       f.cvd_day_dir);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "cvd_ohlc_range",     f.cvd_ohlc_range);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "rotation_up",        f.rotation_up);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "rotation_dn",        f.rotation_dn);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "rotation_zz_osc",    f.rotation_zz_osc);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "delta_divergence",  f.delta_divergence);   DMP_WR_COMMA(buf, pos);

    // ── G6B FPBS Extended (14 champs — ajouté 02/03/2026) ───────────────────
    DMP_WR_KV(buf, pos, "buy_vol",             f.buy_vol);             DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "sell_vol",            f.sell_vol);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "buy_sell_ratio",      f.buy_sell_ratio);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "total_vol",           f.total_vol);           DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "delta_pct",           f.delta_pct);           DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "ticks_count",        f.ticks_count);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "finish_delta_pct",    f.finish_delta_pct);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "high_pullback_delta", f.high_pullback_delta); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "low_pullback_delta",  f.low_pullback_delta);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "diag_pos_delta",      f.diag_pos_delta);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "diag_neg_delta",      f.diag_neg_delta);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "diag_imbalance",      f.diag_imbalance);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "low_bid_vol_pct",     f.low_bid_vol_pct);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "high_ask_vol_pct",    f.high_ask_vol_pct);    DMP_WR_COMMA(buf, pos);

    // ── G7 BN (15 champs) ────────────────────────────────────────────────────
    DMP_WR_KVB(buf, pos, "bn_color_up",            f.bn_color_up);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_color_dn",            f.bn_color_dn);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_color_up_2",          f.bn_color_up_2);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_color_dn_2",          f.bn_color_dn_2);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_absorb_ask",          f.bn_absorb_ask);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_absorb_bid",          f.bn_absorb_bid);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_long_up",             f.bn_long_up);             DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_long_dn",             f.bn_long_dn);             DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bn_pressure_ask",         f.bn_pressure_ask);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bn_pressure_bid",         f.bn_pressure_bid);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bn_score_raw",            f.bn_score_raw);           DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bn_score_bull",           f.bn_score_bull);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "bn_score_bear",           f.bn_score_bear);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_big_ask_nearest_up", f.dist_big_ask_nearest_up);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_big_ask_nearest_dn", f.dist_big_ask_nearest_dn);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_big_bid_nearest_up", f.dist_big_bid_nearest_up);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_big_bid_nearest_dn", f.dist_big_bid_nearest_dn);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_ask_t1", f.n_big_ask_t1);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_bid_t1", f.n_big_bid_t1);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_ask_t2", f.n_big_ask_t2);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_bid_t2", f.n_big_bid_t2);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_ask_t3", f.n_big_ask_t3);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_bid_t3", f.n_big_bid_t3);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_ask_t4", f.n_big_ask_t4);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "n_big_bid_t4", f.n_big_bid_t4);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_20t", f.big_ask_cluster_20t);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_20t", f.big_bid_cluster_20t);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_50t", f.big_ask_cluster_50t);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_50t", f.big_bid_cluster_50t);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_20t_t1", f.big_ask_cluster_20t_t1);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_20t_t1", f.big_bid_cluster_20t_t1);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_20t_t2", f.big_ask_cluster_20t_t2);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_20t_t2", f.big_bid_cluster_20t_t2);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_20t_t3", f.big_ask_cluster_20t_t3);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_20t_t3", f.big_bid_cluster_20t_t3);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_ask_cluster_20t_t4", f.big_ask_cluster_20t_t4);DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "big_bid_cluster_20t_t4", f.big_bid_cluster_20t_t4);DMP_WR_COMMA(buf, pos);

    // ── G7B Bar Signals + Extension Lines (16 champs) — BUG #8 ──────────────
    DMP_WR_KVB(buf, pos, "bar_color_up",       f.bar_color_up);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_color_dn",       f.bar_color_dn);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_long_up_bar",    f.bar_long_up_bar);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_long_dn_bar",    f.bar_long_dn_bar);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_long_dn_up",     f.bar_long_dn_up);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_long_up_dn",     f.bar_long_up_dn);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_edge_buy",       f.bar_edge_buy);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_edge_sell",      f.bar_edge_sell);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_pressure_ask",   f.bar_pressure_ask);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bar_pressure_bid",   f.bar_pressure_bid);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_color_up",  f.dist_ext_color_up);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_color_dn",  f.dist_ext_color_dn);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_long_up",   f.dist_ext_long_up);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_long_dn",   f.dist_ext_long_dn);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_edge_buy",  f.dist_ext_edge_buy);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "dist_ext_edge_sell", f.dist_ext_edge_sell); DMP_WR_COMMA(buf, pos);

    // ── G7C Volume + Edge FP (4 champs) — BUG #10 ──────────────────────────
    DMP_WR_KVB(buf, pos, "bn_volume_up",      f.bn_volume_up);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bn_volume_dn",      f.bn_volume_dn);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "fp_edge_buy",       f.fp_edge_buy);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "fp_edge_sell",      f.fp_edge_sell);      DMP_WR_COMMA(buf, pos);

    // ── G8 Swing (6 champs) ───────────────────────────────────────────────────
    DMP_WR_KV(buf, pos, "dist_swing_high",    f.dist_swing_high);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_swing_low",     f.dist_swing_low);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "swing_range_ticks",  f.swing_range_ticks); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "price_vs_swing_mid", f.price_vs_swing_mid);DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "new_swing_high",    f.new_swing_high);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "new_swing_low",     f.new_swing_low);     DMP_WR_COMMA(buf, pos);

    // ── G9 Contexte (11 champs) ───────────────────────────────────────────────
    DMP_WR_KVE(buf, pos, "open_type",              f.open_type);             DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "open_zone",              f.open_zone);             DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "open_bias_conf",         f.open_bias_conf);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "open_direction",         f.open_direction);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "day_type",               f.day_type);              DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "rule_80pct",             f.rule_80pct);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "trend_day_probability",  f.trend_day_probability); DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "ma_trend",               f.ma_trend);              DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_ma_align",          f.vwap_ma_align);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "vwap_slope_10",          f.vwap_slope_10);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "vwap_slope_30",          f.vwap_slope_30);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_slope_10_dir",      f.vwap_slope_10_dir);     DMP_WR_COMMA(buf, pos);

    // ── G10 Booléens (13 champs) ──────────────────────────────────────────────
    DMP_WR_KVB(buf, pos, "bool_above_cur_vpoc",   f.bool_above_cur_vpoc);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_prev_vpoc",  f.bool_above_prev_vpoc);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_vwap_d",     f.bool_above_vwap_d);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_vwap_w",     f.bool_above_vwap_w);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_vwap_m",     f.bool_above_vwap_m);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_mq_hvl",     f.bool_above_mq_hvl);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_above_mq_call",    f.bool_above_mq_call);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_near_level",       f.bool_near_level);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_ib_inside",        f.bool_ib_inside);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_session_early",    f.bool_session_early);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "vwap_triple_align",     f.vwap_triple_align);     DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_va_confluence",    f.bool_va_confluence);    DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "bool_gex_flip_zone",    f.bool_gex_flip_zone);    DMP_WR_COMMA(buf, pos);

    // ── G11 HVN/LVN (9 champs — DERNIER, pas de virgule finale) ─────────────
    DMP_WR_KV(buf, pos, "dist_session_hvn_above", f.dist_session_hvn_above); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_session_hvn_below", f.dist_session_hvn_below); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_session_lvn_above", f.dist_session_lvn_above); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos, "dist_session_lvn_below", f.dist_session_lvn_below); DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "session_hvn_count",     f.session_hvn_count);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "session_lvn_count",     f.session_lvn_count);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "lvn_between",           f.lvn_between);            DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "hvn_between",           f.hvn_between);            DMP_WR_COMMA(buf, pos);
    // Dernier champ G11
    DMP_WR_KVE(buf, pos, "lvn_confluence_count",  f.lvn_confluence_count); DMP_WR_COMMA(buf, pos);

    // ── G12 Profile Shape (9 champs — DERNIER, dernier champ sans virgule) ────
    DMP_WR_KVE(buf, pos, "profile_shape",         f.profile_shape);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "profile_skew",          f.profile_skew);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "poc_position",          f.poc_position);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "volume_imbalance",      f.volume_imbalance);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "is_double_dist",        f.is_double_dist);        DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "poc_separation_ticks",  f.poc_separation_ticks);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KV2(buf, pos, "single_print_mid",      f.single_print_mid);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "single_print_count",    f.single_print_count);    DMP_WR_COMMA(buf, pos);
    // Ancien dernier G12 — MAINTENANT avec virgule
    DMP_WR_KV2(buf, pos, "profile_hvn_dominant",  f.profile_hvn_dominant); DMP_WR_COMMA(buf, pos);

    // ── G13 Retest / Double Top-Bottom (6 champs — DERNIER) ─────────────────
    DMP_WR_KVE(buf, pos, "retest_high_count",      f.retest_high_count);      DMP_WR_COMMA(buf, pos);
    DMP_WR_KVE(buf, pos, "retest_low_count",       f.retest_low_count);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "retest_high_delta_div",  f.retest_high_delta_div);  DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "retest_low_delta_div",   f.retest_low_delta_div);   DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "bars_since_retest_high", f.bars_since_retest_high); DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "bars_since_retest_low",  f.bars_since_retest_low);  DMP_WR_COMMA(buf, pos);

    // ── G14 RVOL — Relative Volume (6 champs — DERNIER) ─────────────────────
    DMP_WR_KV(buf, pos,  "rvol",              f.rvol);              DMP_WR_COMMA(buf, pos);
    DMP_WR_KV(buf, pos,  "rvol_zscore",       f.rvol_zscore);       DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "rvol_buy",          f.rvol_buy);          DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "rvol_sell",         f.rvol_sell);         DMP_WR_COMMA(buf, pos);
    DMP_WR_KVB(buf, pos, "rvol_absorb_buy",   f.rvol_absorb_buy);  DMP_WR_COMMA(buf, pos);
    // Dernier champ — PAS de virgule finale
    DMP_WR_KVB(buf, pos, "rvol_absorb_sell",  f.rvol_absorb_sell);

    // Fermer l'objet JSON + newline
    buf[pos++] = '}';
    buf[pos++] = '\n';
    buf[pos]   = '\0';  // null-terminate (sécurité)

    return pos;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — FILTRE D'ÉCRITURE
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Conditions pour écrire une ligne :
//    1. Session RTH active (9h30-16h00 ET) — uniquement les données de marché
//    2. Nouvelle barre (éviter les doublons si IsNewBar non respecté en amont)
//    3. Données minimales valides (price et ts non nuls)
//
//  Note : On écrit AUSSI hors RTH si demandé (overnight data).
//         Par défaut : RTH uniquement (recommandé pour ML).

static inline bool DMP_WR_ShouldWrite(
    const DMP_MLFeatures& f,
    bool rth_only = true)
{
    // Timestamp valide
    if (f.ts <= 0) return false;

    // Prix valide
    if (DMP_WR_IsInvalid(f.price) || f.price <= 0.0f) return false;

    // Filtre RTH uniquement (paramétrable)
    // session: 0=Asia (18h-03h ET), 1=London (03h-09h30 ET), 2=US (09h30-18h ET)
    if (rth_only) {
        // RTH = session US uniquement (session == 2)
        if (f.session < 1.5f)  // 0=Asia ou 1=London → skip
            return false;
    }

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — VALIDATION POST-ÉCRITURE (DEBUG MODE)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Compte le nombre de champs null dans la ligne JSON pour détecter
//  les sources de données défaillantes.
//  Appelé uniquement si sc.Input debug mode est activé.

static inline int DMP_WR_CountNullFields(const char* json_line) {
    int count = 0;
    const char* p = json_line;
    while ((p = strstr(p, ":null")) != nullptr) {
        count++;
        p += 5; // sauter ":null"
    }
    return count;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 10 — FONCTION MAÎTRE : DMP_WriteRow()
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Point d'entrée unique du writer.
//  Appelé depuis DMP_Main.cpp après TOUTES les mises à jour :
//    DMP_ReadAll() → DMP_Transform() → DMP_UpdateOpenType() → DMP_WriteRow()
//
//  Responsabilités :
//    1. Détecter rotation de jour → ouvrir nouveau fichier
//    2. Écrire le fichier meta.json (une fois par session)
//    3. Filtrer les barres non-RTH si rth_only=true
//    4. Formater la ligne JSON (DMP_FormatJSONL)
//    5. Écrire dans le fichier
//    6. Flush périodique
//    7. Mettre à jour les compteurs

inline bool DMP_WriteRow(
    SCStudyInterfaceRef     sc,
    const DMP_MLFeatures&   f,
    const char*             base_path = DMP_BASE_PATH,
    bool                    rth_only  = true)
{
    // ── 0. Obtenir l'état du writer pour cette étude ──────────────────────────
    DMP_WriterState* st = DMP_WR_GetState(sc.ChartNumber);

    // ── 1. Détection rotation de jour ─────────────────────────────────────────
    const int today = DMP_WR_GetTradingDateInt(sc);
    if (today != st->current_day || !st->file_ready) {
        bool ok = DMP_WR_Open(st, sc, base_path, f.sym, today);
        if (!ok) return false; // Erreur d'ouverture → on n'écrit pas
        sc.GetPersistentInt(DMP_WR_P_DAY) = today;
        // Enregistrer le contrat initial
        snprintf(st->current_contract, sizeof(st->current_contract), "%s", f.contract);
    }

    // ── 1b. Détection rollover contrat ────────────────────────────────────────
    if (st->current_contract[0] != '\0' && f.contract[0] != '\0') {
        if (strcmp(st->current_contract, f.contract) != 0) {
            char msg[384];
            snprintf(msg, sizeof(msg),
                "ROLLOVER détecté : %s → %s (fichier continue)",
                st->current_contract, f.contract);
            DMP_DebugLog(sc, f.sym, msg);
            snprintf(st->current_contract, sizeof(st->current_contract), "%s", f.contract);
        }
    }

    // ── 2. Écriture meta.json (une seule fois par session) ────────────────────
    if (!st->meta_written) {
        // tick_size stocké dans DMP_RawData mais pas dans DMP_MLFeatures
        // → récupéré depuis sc.TickSize directement
        DMP_WR_WriteMeta(st, sc, f.sym, today, (float)sc.TickSize);
    }

    // ── 3. Filtre écriture ──────────────────────────────────────────────────
    if (!DMP_WR_ShouldWrite(f, rth_only)) {
        // Log diagnostic (toutes les 60 barres pour ne pas flooder)
        static int s_skip_counter = 0;
        if (++s_skip_counter % 60 == 1) {
            char msg[384];
            snprintf(msg, sizeof(msg),
                "SKIP #%d — ts=%lld price=%.2f session=%.0f bool_early=%.0f rth_only=%d",
                s_skip_counter, f.ts, f.price, f.session,
                f.bool_session_early, (int)rth_only);
            DMP_DebugLog(sc, f.sym, msg);
        }
        return true;
    }

    // ── 3b. Déduplication timestamp ─────────────────────────────────────────
    //  ⚠️ FIX 04/03/2026 : CORRIGÉ — utilise st->prev_ts (per-study via ChartNumber)
    //  au lieu de static (qui était PARTAGÉ entre ES et NQ dans le même DLL,
    //  causant NQ = 0 Ko car ES écrivait en premier avec le même ts 1-min).
    if (f.ts == st->prev_ts && f.ts != 0) {
        return true;  // Même timestamp que la barre précédente de CE symbole → skip
    }
    st->prev_ts = f.ts;

    // ── 4. Formater la ligne JSON ─────────────────────────────────────────────
    static char s_json_buf[DMP_JSON_BUF_SIZE]; // static = évite stack overflow (16 KB)
    int len = DMP_FormatJSONL(f, s_json_buf);

    if (len <= 2 || len >= DMP_JSON_BUF_SIZE - 1) {
        char emsg[128];
        snprintf(emsg, sizeof(emsg), "JSON FORMAT FAIL — len=%d (min 3, max %d)", len, DMP_JSON_BUF_SIZE - 1);
        DMP_DebugLog(sc, f.sym, emsg);
        return false;
    }

    // ── 5. Écrire dans le fichier ─────────────────────────────────────────────
    //  Pattern IDENTIQUE à l'ancien dumper MIA_Dumper_G3_Unifier.cpp :
    //    FILE* f = fopen(path, "a");
    //    fwrite(data, 1, len, f);
    //    fclose(f);
    //
    //  POURQUOI fopen/fclose et pas ofstream :
    //  - fclose() LIBÈRE le handle Windows → NTFS met à jour la taille
    //    dans le répertoire → Explorer affiche la bonne taille
    //  - Pas d'état persistant entre les barres → zéro problème lors
    //    des recompilations SC (pas de handle orphelin)
    //  - Coût : ~1ms par barre (1 écriture/min) = négligeable
    {
        FILE* fp = fopen(st->data_path, "a");
        if (!fp) {
            char emsg[384];
            snprintf(emsg, sizeof(emsg),
                "WRITE FAIL — fopen('%s') retourne NULL", st->data_path);
            DMP_DebugLog(sc, f.sym, emsg);
            st->file_ready = false;  // Forcer réouverture au prochain appel
            return false;
        }
        size_t written = fwrite(s_json_buf, 1, (size_t)len, fp);
        fclose(fp);  // ← Force Windows à mettre à jour la taille du fichier

        if ((int)written != len) {
            char emsg[256];
            snprintf(emsg, sizeof(emsg),
                "WRITE PARTIAL — %d/%d octets écrits", (int)written, len);
            DMP_DebugLog(sc, f.sym, emsg);
            return false;
        }
    }

    // ── 7. Compteurs ──────────────────────────────────────────────────────────
    st->rows_session++;
    sc.GetPersistentInt(DMP_WR_P_ROWS_TODAY) = st->rows_session;
    sc.GetPersistentInt(DMP_WR_P_ROWS_TOTAL)++;

    // ── 8. Log stats périodique (toutes les 60 lignes = 1h de session) ────────
    if (st->rows_session % 60 == 0) {
        // Compter les nulls pour détecter sources défaillantes
        int nulls = DMP_WR_CountNullFields(s_json_buf);
        char msg[256];
        snprintf(msg, sizeof(msg),
            "STATS — %d lignes | %d nulls cette barre | %s",
            st->rows_session, nulls, st->data_path);
        DMP_DebugLog(sc, f.sym, msg);
    }

    return true;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 11 — FERMETURE PROPRE (fin de session / shutdown)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Appelé depuis DMP_Main.cpp dans sc.LastCallToFunction = 1 (shutdown Sierra Chart)
//  OU sur détection fin de session RTH (16h00 ET).

inline void DMP_WriterClose(SCStudyInterfaceRef sc) {
    DMP_WriterState* st = DMP_WR_GetState(sc.ChartNumber);
    DMP_WR_Close(st, sc);

    char msg[256];
    snprintf(msg, sizeof(msg),
        "[DMP_Writer] Session terminée | Total session : %d lignes | Total all sessions : %d",
        st->rows_session,
        sc.GetPersistentInt(DMP_WR_P_ROWS_TOTAL));
    sc.AddMessageToLog(msg, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 12 — DIAGNOSTIC : DMP_WriterStatus()
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Affiche l'état complet du writer dans le log Sierra Chart.
//  Utile pour vérifier que l'enregistrement est bien actif.

inline void DMP_WriterStatus(SCStudyInterfaceRef sc) {
    DMP_WriterState* st = DMP_WR_GetState(sc.ChartNumber);
    char msg[512];
    snprintf(msg, sizeof(msg),
        "[DMP_Writer] STATUS | file=%s | ready=%s | rows=%d",
        st->data_path[0] ? st->data_path : "(none)",
        st->file_ready ? "OUI" : "NON",
        st->rows_session);
    sc.AddMessageToLog(msg, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Writer.h — v1.0
// ═══════════════════════════════════════════════════════════════════════════════
