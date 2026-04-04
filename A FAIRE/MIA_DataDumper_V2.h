#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_DataDumper_V2.h - SNAPSHOT COMPLET DE TOUT CE QUE LE BOT VOIT
// ═══════════════════════════════════════════════════════════════════════════════
// 06/02/2026 - V2: Capture 100% des données pour:
//   1. Backtesting fidèle (replay exact des conditions)
//   2. ML Pattern Discovery (features complètes)
//   3. Analyse post-session (pourquoi tel trade / rejet)
//   4. Validation des règles (L1→L2→L3→L4 replay)
//
// DIFFÉRENCES vs V1 (MIA_DataDumper.h):
//   - Composite Profiles (5 périodes: 1d, 20d, 50d, 100d, 200d)
//   - Market Regime (score, classification)
//   - Session OHLC + Volume Profile complet
//   - VWAP SD bands (±1σ, ±2σ)
//   - LVN levels array
//   - BN Advanced (stacked zones, attack, directional coherence)
//   - Extension lines + Edge rectangles
//   - Fresh rectangles + Color prices
//   - MenthorQ distances (GEX, Blind, Gamma)
//   - Gros ordres (400, 1000)
//   - Range detection complète
//   - Layers TOUJOURS dumpées (même si rejetées)
//   - SLTP result (quand trade)
//   - Buffer unique pour performance (1 seul fwrite)
//
// Format: JSONL (1 ligne JSON par snapshot)
// Chemin: D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_SNAPSHOTS\YYYY\MM\YYYYMMDD\
//         snapshot_ES_YYYYMMDD.jsonl
//         snapshot_NQ_YYYYMMDD.jsonl
//
// Taille estimée: ~4-5 KB/ligne → ~150 MB/jour à 1/sec (compressible à ~15 MB)
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include <cstdio>
#include <ctime>

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION DU DUMPER V2
// ═══════════════════════════════════════════════════════════════════════════════

// Intervalle entre snapshots (millisecondes)
// 1000  = 1/sec  → précis, ~150 MB/jour
// 2000  = 1/2sec → bon compromis, ~75 MB/jour
// 5000  = 1/5sec → léger, ~30 MB/jour
inline const int SNAPSHOT_INTERVAL_MS = 1000;

// Version du schéma (pour compatibilité Python)
inline const char* SNAPSHOT_SCHEMA_VERSION = "2.0.0";

// Taille du buffer d'écriture (une ligne JSON complète)
inline const int SNAPSHOT_BUFFER_SIZE = 16384;  // 16 KB

// ═══════════════════════════════════════════════════════════════════════════════
// VARIABLES GLOBALES V2
// ═══════════════════════════════════════════════════════════════════════════════

inline long long g_snap_last_ms_es = 0;
inline long long g_snap_last_ms_nq = 0;
inline unsigned int g_snap_seq_es = 0;
inline unsigned int g_snap_seq_nq = 0;
inline bool g_snapshot_enabled = true;

// File handles persistants (évite open/close chaque seconde)
inline FILE* g_snap_file_es = nullptr;
inline FILE* g_snap_file_nq = nullptr;
inline int g_snap_current_day_es = -1;
inline int g_snap_current_day_nq = -1;

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER: Écrire un bool JSON sans guillemets
// ═══════════════════════════════════════════════════════════════════════════════
inline const char* JB(bool v) { return v ? "true" : "false"; }

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER: Ouvrir/Gérer le fichier avec rotation journalière
// ═══════════════════════════════════════════════════════════════════════════════
inline FILE* GetSnapshotFile(
    SCStudyInterfaceRef sc,
    bool is_nq,
    int year, int month, int day
) {
    FILE*& file_handle = is_nq ? g_snap_file_nq : g_snap_file_es;
    int& current_day = is_nq ? g_snap_current_day_nq : g_snap_current_day_es;
    
    int today = year * 10000 + month * 100 + day;
    
    // Si même jour et fichier ouvert → réutiliser
    if (file_handle != nullptr && current_day == today) {
        return file_handle;
    }
    
    // Fermer ancien fichier si ouvert
    if (file_handle != nullptr) {
        fclose(file_handle);
        file_handle = nullptr;
    }
    
    const char* sym = is_nq ? "NQ" : "ES";
    
    // Créer arborescence de répertoires
    char tmp[512];
    CreateDirectoryA("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_SNAPSHOTS", NULL);
    snprintf(tmp, sizeof(tmp), "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_SNAPSHOTS\\%04d", year);
    CreateDirectoryA(tmp, NULL);
    snprintf(tmp, sizeof(tmp), "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_SNAPSHOTS\\%04d\\%02d", year, month);
    CreateDirectoryA(tmp, NULL);
    char dir_path[512];
    snprintf(dir_path, sizeof(dir_path),
        "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_SNAPSHOTS\\%04d\\%02d\\%04d%02d%02d",
        year, month, year, month, day);
    CreateDirectoryA(dir_path, NULL);
    
    // Ouvrir fichier en append
    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "%s\\snapshot_%s_%04d%02d%02d.jsonl",
        dir_path, sym, year, month, day);
    
    file_handle = fopen(filepath, "a");
    if (file_handle) {
        current_day = today;
        // Log première ouverture
        char msg[256];
        snprintf(msg, sizeof(msg), "📸 SNAPSHOT V2 %s: Fichier ouvert → %s", sym, filepath);
        sc.AddMessageToLog(msg, 0);
    } else {
        char err[256];
        snprintf(err, sizeof(err), "❌ SNAPSHOT V2: Cannot open %s", filepath);
        sc.AddMessageToLog(err, 1);
    }
    
    return file_handle;
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER: Écrire un SingleProfile dans le buffer
// ═══════════════════════════════════════════════════════════════════════════════
inline int WriteProfile(char* buf, int pos, int max, const char* key, const SingleProfile& p) {
    if (!p.valid) {
        pos += snprintf(buf + pos, max - pos, "\"%s\":null,", key);
        return pos;
    }
    pos += snprintf(buf + pos, max - pos,
        "\"%s\":{\"vpoc\":%.2f,\"vah\":%.2f,\"val\":%.2f,\"vwap\":%.2f,"
        "\"hvn\":%.2f,\"lvn\":%.2f,"
        "\"d_vpoc\":%.1f,\"d_vah\":%.1f,\"d_val\":%.1f,\"d_hvn\":%.1f,\"d_lvn\":%.1f},",
        key,
        p.vpoc, p.vah, p.val, p.vwap,
        p.hvn, p.lvn,
        p.dist_vpoc_ticks, p.dist_vah_ticks, p.dist_val_ticks,
        p.dist_hvn_ticks, p.dist_lvn_ticks
    );
    return pos;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE V2: SNAPSHOT COMPLET
// ═══════════════════════════════════════════════════════════════════════════════
//
// Capture 100% de ce que le bot voit à cet instant.
// Appelé depuis la boucle principale de MIA_Main.cpp
//
// Paramètres ajoutés vs V1:
//   - cp:      Composite Profiles (5 périodes)
//   - regime:  Market Regime calculé
//   - sltp:    SL/TP result (nullptr si pas de trade)
//   - vwap_slope: VWAP slope du symbole
//   - smart_money: Smart money score (NQ L3)
//   - delta_pct:   Delta percent (ES L3)
//
// ═══════════════════════════════════════════════════════════════════════════════

inline void WriteFullSnapshot(
    SCStudyInterfaceRef sc,
    bool is_nq,
    // Données de marché
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const CompositeProfile_Data& cp,
    // État bot
    const BotState& state,
    float current_price,
    // Indicateurs globaux
    float vix,
    int vix_regime,
    float atr,
    float correlation,
    float vwap_slope,
    const char* session,
    // Market Regime (peut être nullptr si pas calculé)
    const RegimeResult* regime,
    // Layers (nullptr si pas évalués ce tick)
    const Layer1Result* l1,
    const Layer2Result* l2,
    const Layer3Result* l3,
    const Layer4Result* l4,
    // SL/TP (nullptr si pas de trade)
    const SLTPResult* sltp
) {
    if (!g_snapshot_enabled) return;
    
    // ─── Throttle par intervalle ───
    long long current_ms = (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    long long& last_ms = is_nq ? g_snap_last_ms_nq : g_snap_last_ms_es;
    
    if (current_ms - last_ms < SNAPSHOT_INTERVAL_MS) return;
    last_ms = current_ms;
    
    // ─── Séquence ───
    unsigned int& seq = is_nq ? g_snap_seq_nq : g_snap_seq_es;
    seq++;
    
    // ─── Date/Heure ───
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    const char* sym = is_nq ? "NQ" : "ES";
    float tick_size = is_nq ? 0.25f : 0.25f;
    
    // ─── Obtenir fichier (handle persistant) ───
    FILE* f = GetSnapshotFile(sc, is_nq, year, month, day);
    if (!f) return;
    
    // ─── Log périodique (toutes les 5 minutes = 300 lignes à 1/sec) ───
    static int snap_log_es = 0, snap_log_nq = 0;
    int& snap_log = is_nq ? snap_log_nq : snap_log_es;
    if (++snap_log >= 300) {
        snap_log = 0;
        char msg[256];
        snprintf(msg, sizeof(msg),
            "📸 SNAP %s #%u: price=%.2f bn=%.4f regime=%s layers=%s",
            sym, seq, current_price, bn.score,
            regime ? regime->description : "N/A",
            (l1 && l2 && l3 && l4) ? "YES" : "data_only");
        sc.AddMessageToLog(msg, 0);
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CONSTRUIRE LE JSON DANS UN BUFFER UNIQUE (performance)
    // ═══════════════════════════════════════════════════════════════════════════
    
    char buf[SNAPSHOT_BUFFER_SIZE];
    int pos = 0;
    int max = SNAPSHOT_BUFFER_SIZE - 2;  // Réserver pour }\n
    
    // ─── 1. HEADER ───
    pos += snprintf(buf + pos, max - pos,
        "{\"_v\":\"%s\",\"t\":%lld,\"seq\":%u,\"sym\":\"%s\","
        "\"session\":\"%s\",\"hms\":\"%02d:%02d:%02d\",",
        SNAPSHOT_SCHEMA_VERSION, current_ms, seq, sym,
        session, hour, minute, second
    );
    
    // ─── 2. PRIX ───
    pos += snprintf(buf + pos, max - pos,
        "\"px\":%.2f,",
        current_price
    );
    
    // ─── 3. BATAILLE NAVALE - FOOTPRINT (signaux tick) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_fp\":{\"eb\":%.0f,\"es\":%.0f,\"cu\":%.0f,\"cd\":%.0f,"
        "\"aa\":%.0f,\"ab\":%.0f,\"da\":%.0f,\"db\":%.0f,"
        "\"ta\":%.0f,\"tb\":%.0f,"
        "\"ru\":%.0f,\"rd\":%.0f,\"vu\":%.0f,\"vd\":%.0f},",
        bn.edge_buy, bn.edge_sell, bn.color_up, bn.color_down,
        bn.absorb_ask, bn.absorb_bid, bn.double_ask, bn.double_bid,
        bn.triple_ask, bn.triple_bid,
        bn.rotation_up, bn.rotation_down, bn.volume_up, bn.volume_down
    );
    
    // ─── 4. BN - BARRES ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_bar\":{\"ldu\":%.0f,\"lud\":%.0f,"
        "\"beb\":%.0f,\"bes\":%.0f,\"bcu\":%.0f,\"bcd\":%.0f},",
        bn.long_down_up, bn.long_up_down,
        bn.bar_edge_buy, bn.bar_edge_sell, bn.bar_color_up, bn.bar_color_down
    );
    
    // ─── 5. BN - ORDRES (tous niveaux) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_ord\":{\"a10\":%.0f,\"b10\":%.0f,\"a30\":%.0f,\"b30\":%.0f,"
        "\"a100\":%.0f,\"b100\":%.0f,\"a150\":%.0f,\"b150\":%.0f,"
        "\"a400\":%.0f,\"b400\":%.0f,\"a1k\":%.0f,\"b1k\":%.0f,"
        "\"clust\":%.0f},",
        bn.ask_10, bn.bid_10, bn.ask_30, bn.bid_30,
        bn.ask_100, bn.bid_100, bn.ask_150, bn.bid_150,
        bn.ask_400, bn.bid_400, bn.ask_1000, bn.bid_1000,
        bn.cluster_vol
    );
    
    // ─── 6. BN - FPBS (Order Flow) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_of\":{\"delta\":%.0f,\"delta_d\":%.0f,\"cvd\":%.0f,\"poc\":%.2f,"
        "\"ask_pct\":%.2f,\"bid_pct\":%.2f,"
        "\"cvd_slope\":%.1f,\"cvd_div\":%s,\"cvd_trend\":%.4f,\"poc_conf\":%d},",
        bn.fpbs_delta, bn.fpbs_delta_day, bn.fpbs_cvd, bn.fpbs_poc,
        bn.fpbs_ask_pct, bn.fpbs_bid_pct,
        bn.cvd_slope, JB(bn.cvd_divergence), bn.cvd_trend_score, bn.poc_confirm
    );
    
    // ─── 7. BN - SCORES CALCULÉS ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_sc\":{\"score\":%.4f,\"sig\":%.0f,\"mom\":%.4f,\"rev\":%.4f,"
        "\"inst\":%.4f,\"buy_str\":%.4f,\"sell_str\":%.4f,"
        "\"mom_shift\":%.4f,\"dir_coh\":%.4f,\"dir\":%d},",
        bn.score, bn.signal, bn.momentum_score, bn.reversal_score,
        bn.institutional_pressure, bn.buyer_strength, bn.seller_strength,
        bn.momentum_shift, bn.directional_coherence, bn.direction
    );
    
    // ─── 8. BN - RECTANGLES & EDGE ZONES ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_rect\":{\"buy\":%d,\"sell\":%d,\"e_buy\":%d,\"e_sell\":%d,"
        "\"buy_px\":%.2f,\"sell_px\":%.2f,"
        "\"fresh_buy\":%s,\"fresh_sell\":%s,\"fresh_age\":%d,"
        "\"in_e_buy\":%s,\"in_e_sell\":%s,"
        "\"e_ratio\":%.4f,\"e_dom_buy\":%s,\"e_dom_sell\":%s},",
        bn.num_rect_buy, bn.num_rect_sell, bn.num_edge_rect_buy, bn.num_edge_rect_sell,
        bn.rect_buy_price, bn.rect_sell_price,
        JB(bn.fresh_rectangle_buy), JB(bn.fresh_rectangle_sell), bn.fresh_rect_age_bars,
        JB(bn.price_in_edge_rect_buy), JB(bn.price_in_edge_rect_sell),
        bn.edge_ratio, JB(bn.edge_dominant_buy), JB(bn.edge_dominant_sell)
    );
    
    // ─── 9. BN - AVANCÉ (attack, stacked, subtile) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_adv\":{\"atk_long\":%s,\"atk_short\":%s,"
        "\"stk_buy\":%d,\"stk_sell\":%d,"
        "\"atk_str_buy\":%.4f,\"atk_str_sell\":%.4f,"
        "\"all_bull\":%s,\"all_bear\":%s,"
        "\"sub_long\":%s,\"sub_short\":%s},",
        JB(bn.bn_attack_long_valid), JB(bn.bn_attack_short_valid),
        bn.stacked_buy_zones, bn.stacked_sell_zones,
        bn.attack_strength_buy, bn.attack_strength_sell,
        JB(bn.all_signals_bullish), JB(bn.all_signals_bearish),
        JB(bn.bn_subtile_long_valid), JB(bn.bn_subtile_short_valid)
    );
    
    // ─── 10. BN - DELTA DIVERGENCE ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_ddiv\":{\"buy\":%s,\"sell\":%s,\"str\":%.2f},",
        JB(bn.delta_div_buy), JB(bn.delta_div_sell), bn.delta_div_strength
    );
    
    // ─── 11. BN - SWING STRUCTURE + SINGLE PRINTS ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_swing\":{\"hi\":%.2f,\"lo\":%.2f,"
        "\"d_bull\":%s,\"d_bear\":%s,"
        "\"sp_hi\":%.2f,\"sp_lo\":%.2f,\"near_sp\":%s,\"d_sp\":%.1f},",
        bn.swing_high, bn.swing_low,
        JB(bn.delta_bar_bullish), JB(bn.delta_bar_bearish),
        bn.single_print_high, bn.single_print_low,
        JB(bn.near_single_print), bn.dist_single_print_ticks
    );
    
    // ─── 12. BN - SESSION (OHLC + Volume Profile) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_sess\":{\"o\":%.2f,\"h\":%.2f,\"l\":%.2f,\"c\":%.2f,"
        "\"d_hi\":%.1f,\"d_lo\":%.1f,"
        "\"vpoc\":%.2f,\"vah\":%.2f,\"val\":%.2f,"
        "\"hvn\":%.2f,\"lvn\":%.2f,"
        "\"d_vpoc\":%.1f,\"d_vah\":%.1f,\"d_val\":%.1f},",
        bn.session_open, bn.session_high, bn.session_low, bn.session_close,
        bn.dist_session_high_ticks, bn.dist_session_low_ticks,
        bn.session_vpoc, bn.session_vah, bn.session_val,
        bn.session_hvn, bn.session_lvn,
        bn.dist_session_poc_ticks, bn.dist_session_vah_ticks, bn.dist_session_val_ticks
    );
    
    // ─── 13. BN - VWAP + SD BANDS ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_vwap\":{\"v\":%.2f,\"sd1u\":%.2f,\"sd1d\":%.2f,"
        "\"sd2u\":%.2f,\"sd2d\":%.2f},",
        bn.vwap, bn.vwap_sd1_up, bn.vwap_sd1_dn,
        bn.vwap_sd2_up, bn.vwap_sd2_dn
    );
    
    // ─── 14. BN - EXTENSION LINES (nearest) ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_ext\":{\"sup\":%.2f,\"res\":%.2f,"
        "\"d_sup\":%.1f,\"d_res\":%.1f,"
        "\"n_sup\":%d,\"n_res\":%d,"
        "\"trd_sup\":%s,\"trd_res\":%s},",
        bn.nearest_ext_support, bn.nearest_ext_resist,
        bn.dist_nearest_support_ticks, bn.dist_nearest_resist_ticks,
        bn.num_ext_support, bn.num_ext_resist,
        JB(bn.has_tradable_support), JB(bn.has_tradable_resist)
    );
    
    // ─── 15. BN - RANGE DETECTION ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_range\":{\"is\":%s,\"sup\":%.2f,\"res\":%.2f,"
        "\"mid\":%.2f,\"size\":%.1f,\"pos_pct\":%.2f,\"pos\":%d},",
        JB(bn.is_range), bn.range_support, bn.range_resistance,
        bn.range_midpoint, bn.range_size_pts, bn.price_position_pct, bn.price_position
    );
    
    // ─── 16. BN - LVN LEVELS ───
    pos += snprintf(buf + pos, max - pos,
        "\"bn_lvn\":{\"n\":%d,\"above\":%.2f,\"below\":%.2f,"
        "\"d_above\":%.1f,\"d_below\":%.1f},",
        bn.num_lvn, bn.nearest_lvn_above, bn.nearest_lvn_below,
        bn.dist_lvn_above_ticks, bn.dist_lvn_below_ticks
    );
    
    // ─── 17. MENTHORQ - NIVEAUX PRIMAIRES ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq\":{\"hvl\":%.2f,\"hvl0\":%.2f,\"gamma\":%.2f,\"gamma0\":%.2f,"
        "\"call\":%.2f,\"call0\":%.2f,\"put\":%.2f,\"put0\":%.2f,"
        "\"dmin\":%.2f,\"dmax\":%.2f,\"vah\":%.2f,\"val\":%.2f,"
        "\"wall\":%.2f,\"wall_d\":%.1f},",
        mq.hvl, mq.hvl_0dte, mq.gamma_wall, mq.gamma_wall_0dte,
        mq.call_resistance, mq.call_resistance_0dte, mq.put_support, mq.put_support_0dte,
        mq.day_min, mq.day_max, mq.vah, mq.val,
        mq.next_wall, mq.wall_distance_ticks
    );
    
    // ─── 18. MENTHORQ - VWAP ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq_vwap\":{\"v\":%.2f,\"u1\":%.2f,\"d1\":%.2f,"
        "\"u2\":%.2f,\"d2\":%.2f,\"slope\":%.6f},",
        mq.vwap, mq.vwap_up1, mq.vwap_dn1,
        mq.vwap_up2, mq.vwap_dn2, vwap_slope
    );
    
    // ─── 19. MENTHORQ - GEX (10 niveaux) ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq_gex\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],",
        mq.gex[0], mq.gex[1], mq.gex[2], mq.gex[3], mq.gex[4],
        mq.gex[5], mq.gex[6], mq.gex[7], mq.gex[8], mq.gex[9]
    );
    
    // ─── 20. MENTHORQ - BLIND SPOTS (9 niveaux) ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq_blind\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],",
        mq.blind_spots[0], mq.blind_spots[1], mq.blind_spots[2],
        mq.blind_spots[3], mq.blind_spots[4], mq.blind_spots[5],
        mq.blind_spots[6], mq.blind_spots[7], mq.blind_spots[8]
    );
    
    // ─── 21. MENTHORQ - DISTANCES (pour ML features) ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq_dist\":{\"gex_up\":%.1f,\"gex_dn\":%.1f,\"blind\":%.1f,"
        "\"gamma\":%.1f,\"call\":%.1f,\"put\":%.1f,"
        "\"gex_up_px\":%.2f,\"gex_dn_px\":%.2f,\"blind_px\":%.2f},",
        mq.dist_gex_up_ticks, mq.dist_gex_dn_ticks, mq.dist_blind_ticks,
        mq.dist_gamma_ticks, mq.dist_call_ticks, mq.dist_put_ticks,
        mq.nearest_gex_up, mq.nearest_gex_dn, mq.nearest_blind
    );
    
    // ─── 22. MENTHORQ - PREVIOUS DAY LEVELS ───
    pos += snprintf(buf + pos, max - pos,
        "\"mq_prev\":{\"vah\":%.2f,\"val\":%.2f,\"vpoc\":%.2f,"
        "\"vwap\":%.2f,\"sd1u\":%.2f,\"sd1d\":%.2f},",
        mq.prev_vah, mq.prev_val, mq.prev_vpoc,
        mq.prev_vwap, mq.prev_vwap_sd1_up, mq.prev_vwap_sd1_dn
    );
    
    // ─── 23. COMPOSITE PROFILES (5 périodes) ───
    pos += snprintf(buf + pos, max - pos, "\"cp\":{");
    pos = WriteProfile(buf, pos, max, "1d", cp.p1d);
    pos = WriteProfile(buf, pos, max, "20d", cp.p20d);
    pos = WriteProfile(buf, pos, max, "50d", cp.p50d);
    pos = WriteProfile(buf, pos, max, "100d", cp.p100d);
    pos = WriteProfile(buf, pos, max, "200d", cp.p200d);
    // Niveaux agrégés
    pos += snprintf(buf + pos, max - pos,
        "\"agg\":{\"lvn_up\":%.2f,\"lvn_dn\":%.2f,\"hvn_up\":%.2f,\"hvn_dn\":%.2f,"
        "\"d_lvn_up\":%.1f,\"d_lvn_dn\":%.1f,\"d_hvn_up\":%.1f,\"d_hvn_dn\":%.1f,"
        "\"lvn_up_p\":%d,\"lvn_dn_p\":%d,\"hvn_up_p\":%d,\"hvn_dn_p\":%d,"
        "\"lvn_conf\":%d,\"hvn_conf\":%d,"
        "\"str_lvn\":%.2f,\"str_hvn\":%.2f}},",
        cp.nearest_lvn_above, cp.nearest_lvn_below,
        cp.nearest_hvn_above, cp.nearest_hvn_below,
        cp.dist_nearest_lvn_above_ticks, cp.dist_nearest_lvn_below_ticks,
        cp.dist_nearest_hvn_above_ticks, cp.dist_nearest_hvn_below_ticks,
        cp.nearest_lvn_above_period, cp.nearest_lvn_below_period,
        cp.nearest_hvn_above_period, cp.nearest_hvn_below_period,
        cp.lvn_confluence_count, cp.hvn_confluence_count,
        cp.strongest_lvn, cp.strongest_hvn
    );
    
    // ─── 24. INDICATEURS GLOBAUX ───
    pos += snprintf(buf + pos, max - pos,
        "\"global\":{\"vix\":%.2f,\"vix_r\":%d,\"atr\":%.2f,"
        "\"corr\":%.4f,\"vwap_slope\":%.6f},",
        vix, vix_regime, atr, correlation, vwap_slope
    );
    
    // ─── 25. MARKET REGIME ───
    if (regime) {
        pos += snprintf(buf + pos, max - pos,
            "\"regime\":{\"score\":%.1f,\"type\":%d,"
            "\"size_m\":%.2f,\"tp_m\":%.2f,\"trail\":%s},",
            regime->score, (int)regime->regime,
            regime->size_multiplier, regime->tp_multiplier,
            JB(regime->trailing_enabled)
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"regime\":null,");
    }
    
    // ─── 26. ÉTAT DU BOT ───
    pos += snprintf(buf + pos, max - pos,
        "\"state\":{\"in_pos\":%s,\"dir\":%d,\"entry\":%.2f,"
        "\"sl\":%.2f,\"tp\":%.2f,\"trail_sl\":%.2f,"
        "\"trail_on\":%s,\"be_on\":%s,"
        "\"trades\":%d,\"wins\":%d,\"losses\":%d,"
        "\"pnl\":%.2f,\"consec_loss\":%d,"
        "\"paused\":%s,\"cb\":%s},",
        JB(state.in_position), state.direction,
        state.entry_price, state.sl_price, state.tp_price,
        state.trailing_sl,
        JB(state.trailing_activated), JB(state.break_even_activated),
        state.trades_today, state.wins_today, state.losses_today,
        state.pnl_today, state.consecutive_losses,
        JB(state.paused), JB(state.circuit_breaker_active)
    );
    
    // ─── 27. LAYERS (TOUJOURS inclus, même partiels) ───
    pos += snprintf(buf + pos, max - pos, "\"layers\":{");
    
    if (l1) {
        pos += snprintf(buf + pos, max - pos,
            "\"l1\":{\"pass\":%s,\"conf\":%.2f,\"dir\":%d,"
            "\"level\":\"%s\",\"px\":%.2f,\"dist\":%.1f,\"imp\":%d},",
            JB(l1->passed), l1->confidence, l1->direction,
            l1->level_name, l1->level_price, l1->distance_ticks, l1->importance_score
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"l1\":null,");
    }
    
    if (l2) {
        pos += snprintf(buf + pos, max - pos,
            "\"l2\":{\"pass\":%s,\"conf\":%.2f,\"bn\":%.4f,"
            "\"vis\":%d},",
            JB(l2->passed), l2->confidence, l2->bn_score,
            l2->visual_count
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"l2\":null,");
    }
    
    if (l3) {
        pos += snprintf(buf + pos, max - pos,
            "\"l3\":{\"pass\":%s,\"conf\":%.2f,\"veto\":%s,"
            "\"ctx\":\"%s\"},",
            JB(l3->passed), l3->confidence, JB(l3->veto),
            l3->context
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"l3\":null,");
    }
    
    if (l4) {
        pos += snprintf(buf + pos, max - pos,
            "\"l4\":{\"pass\":%s,\"combo\":%d,"
            "\"pct\":%s,\"edge\":%s,\"delta\":%s,\"bn\":%s,\"vwap\":%s,"
            "\"qscore\":%.1f,\"grade\":\"%c\",\"tp_m\":%.2f}",
            JB(l4->passed), l4->combo_aligned,
            JB(l4->pct_ok), JB(l4->edge_ok), JB(l4->delta_ok),
            JB(l4->bn_ok), JB(l4->vwap_ok),
            l4->quality_score, l4->grade, l4->tp_multiplier
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"l4\":null");
    }
    
    pos += snprintf(buf + pos, max - pos, "},");
    
    // ─── 28. SLTP (si trade en cours ou trade ce tick) ───
    if (sltp && sltp->is_valid) {
        pos += snprintf(buf + pos, max - pos,
            "\"sltp\":{\"sl\":%.2f,\"tp\":%.2f,\"sl_t\":%d,\"tp_t\":%d,"
            "\"rr\":%.2f,\"sl_on\":\"%s\",\"tp_on\":\"%s\"}",
            sltp->sl_price, sltp->tp_price, sltp->sl_ticks, sltp->tp_ticks,
            sltp->rr_ratio, sltp->sl_based_on, sltp->tp_based_on
        );
    } else {
        pos += snprintf(buf + pos, max - pos, "\"sltp\":null");
    }
    
    // ─── FERMER JSON ───
    pos += snprintf(buf + pos, max - pos, "}\n");
    
    // ─── ÉCRITURE ATOMIQUE (un seul appel) ───
    fwrite(buf, 1, pos, f);
    fflush(f);  // Flush pour éviter perte en cas de crash
}

// ═══════════════════════════════════════════════════════════════════════════════
// VERSION SIMPLIFIÉE: SNAPSHOT DONNÉES SEULES (sans Layers ni SLTP)
// Pour appels haute fréquence quand aucun signal n'est évalué
// ═══════════════════════════════════════════════════════════════════════════════

inline void WriteSnapshotDataOnly(
    SCStudyInterfaceRef sc,
    bool is_nq,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const CompositeProfile_Data& cp,
    const BotState& state,
    float current_price,
    float vix, int vix_regime, float atr,
    float correlation, float vwap_slope,
    const char* session,
    const RegimeResult* regime
) {
    WriteFullSnapshot(sc, is_nq, bn, mq, cp, state, current_price,
                      vix, vix_regime, atr, correlation, vwap_slope, session,
                      regime, nullptr, nullptr, nullptr, nullptr, nullptr);
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONTRÔLE DU DUMPER V2
// ═══════════════════════════════════════════════════════════════════════════════

inline void EnableSnapshot(bool enable) {
    g_snapshot_enabled = enable;
}

inline bool IsSnapshotEnabled() {
    return g_snapshot_enabled;
}

// Fermer les fichiers proprement (appel au shutdown)
inline void CloseSnapshotFiles() {
    if (g_snap_file_es) { fclose(g_snap_file_es); g_snap_file_es = nullptr; }
    if (g_snap_file_nq) { fclose(g_snap_file_nq); g_snap_file_nq = nullptr; }
    g_snap_current_day_es = -1;
    g_snap_current_day_nq = -1;
}

// Réinitialiser compteurs (reset quotidien)
inline void ResetSnapshotCounters() {
    g_snap_seq_es = 0;
    g_snap_seq_nq = 0;
    g_snap_last_ms_es = 0;
    g_snap_last_ms_nq = 0;
    // Forcer ré-ouverture des fichiers pour le nouveau jour
    CloseSnapshotFiles();
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN MIA_DataDumper_V2.h
// ═══════════════════════════════════════════════════════════════════════════════
