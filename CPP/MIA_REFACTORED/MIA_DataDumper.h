#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_DataDumper.h - COLLECTE CONTINUE DES DONNÉES BOT C++
// ═══════════════════════════════════════════════════════════════════════════════
// 31/01/2026 - Dump TOUTES les données vues par le bot pour:
//   1. Backtesting avec données réelles
//   2. Test de nouvelles approches
//   3. Analyse post-session
//   4. Replay des décisions
//
// Format: JSONL (1 ligne JSON par tick/seconde)
// Chemin: D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_DATA\YYYY\MM\YYYYMMDD\
//         bot_data_ES_YYYYMMDD.jsonl
//         bot_data_NQ_YYYYMMDD.jsonl
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include "MIA_Globals.h"  // 🔧 28/02/2026: Pour g_market_live (déclaré dans Globals, pas Indicators)
#include <cstdio>
#include <ctime>

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION DU DUMPER
// ═══════════════════════════════════════════════════════════════════════════════

// Intervalle minimum entre deux dumps (en millisecondes)
// Options:
//   1000  = 1 dump/sec   = ~30,000 lignes/jour (tick-by-tick, précis)
//   5000  = 1 dump/5sec  = ~6,000 lignes/jour  (léger)
//   10000 = 1 dump/10sec = ~3,000 lignes/jour  (très léger)
inline const int DATA_DUMP_INTERVAL_MS = 1000;  // 1 seconde = tick-by-tick pour backtest précis

// ═══════════════════════════════════════════════════════════════════════════════
// STRUCTURE DE DONNÉES COMPLÈTE POUR DUMP
// ═══════════════════════════════════════════════════════════════════════════════

struct BotDataSnapshot {
    // Metadata
    long long timestamp_ms;
    char symbol[8];
    int chart_number;
    char session[16];          // "LONDON", "US", "ASIA"
    
    // Prix
    float price;
    float bid;
    float ask;
    float spread;
    float open;
    float high;
    float low;
    float close;
    
    // Bataille Navale - Signaux Footprint
    float edge_buy;
    float edge_sell;
    float color_up;
    float color_down;
    float absorb_ask;
    float absorb_bid;
    float triple_ask;
    float triple_bid;
    float rotation_up;
    float rotation_down;
    float volume_up;
    float volume_down;
    
    // Bataille Navale - Patterns Barres
    float long_down_up;
    float long_up_down;
    float long_up_bar;
    float long_down_bar;
    float bar_edge_buy;
    float bar_edge_sell;
    float bar_color_up;
    float bar_color_down;
    
    // Bataille Navale - Ordres Granulaires
    float ask_10;
    float bid_10;
    float ask_30;
    float bid_30;
    float ask_100;
    float bid_100;
    float ask_150;
    float bid_150;
    float cluster_vol;
    
    // Bataille Navale - FPBS (Order Flow)
    float fpbs_delta;
    float fpbs_delta_day;
    float fpbs_cvd;
    float fpbs_poc;
    float fpbs_ask_pct;
    float fpbs_bid_pct;
    
    // Bataille Navale - Scores calculés
    float bn_score;
    int bn_signal;
    float momentum_score;
    float reversal_score;
    float institutional_pressure;
    float buyer_strength;
    float seller_strength;
    float cvd_slope;
    bool cvd_divergence;
    int poc_confirm;
    
    // Bataille Navale - Rectangles
    int num_rect_buy;
    int num_rect_sell;
    int num_edge_rect_buy;
    int num_edge_rect_sell;
    float rect_buy_price;
    float rect_sell_price;
    
    // MenthorQ - Niveaux Primaires
    float hvl;
    float hvl_0dte;
    float gamma_wall;
    float gamma_wall_0dte;
    float call_resistance;
    float call_resistance_0dte;
    float put_support;
    float put_support_0dte;
    
    // MenthorQ - Niveaux Secondaires
    float day_min;
    float day_max;
    float vah;
    float val;
    float next_wall;
    float wall_distance_ticks;
    
    // MenthorQ - VWAP
    float vwap;
    float vwap_up1;
    float vwap_dn1;
    float vwap_up2;
    float vwap_dn2;
    float vwap_slope;
    
    // MenthorQ - GEX (10 niveaux)
    float gex[10];
    
    // MenthorQ - Blind Spots
    float blind_spots[9];
    
    // Indicateurs Globaux
    float vix;
    int vix_regime;            // 0=LOW, 1=NORMAL, 2=HIGH, 3=EXTREME
    float atr;
    float correlation_es_nq;
    
    // DOM
    int dom_bid_qty;
    int dom_ask_qty;
    float depth_imbalance;
    
    // État Bot
    bool in_position;
    int position_direction;
    float entry_price;
    float sl_price;
    float tp_price;
    int trades_today;
    int wins_today;
    float pnl_today;
    
    // Layer Results (pour replay)
    bool l1_passed;
    float l1_confidence;
    char l1_level[32];
    float l1_distance;
    
    bool l2_passed;
    float l2_confidence;
    float l2_bn_score;
    char l2_correlation[16];
    
    bool l3_passed;
    float l3_confidence;
    bool l3_veto;
    char l3_context[32];
    
    bool l4_passed;
    int l4_combo;
    bool l4_pct_ok;
    bool l4_edge_ok;
};

// ═══════════════════════════════════════════════════════════════════════════════
// VARIABLES GLOBALES POUR LE DUMPER
// ═══════════════════════════════════════════════════════════════════════════════

// Dernière écriture par symbole (pour limiter fréquence)
inline long long g_last_dump_es_ms = 0;
inline long long g_last_dump_nq_ms = 0;

// Compteur de séquence par symbole
inline unsigned int g_dump_seq_es = 0;
inline unsigned int g_dump_seq_nq = 0;

// Flag pour activer/désactiver le dump
inline bool g_data_dump_enabled = true;

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTION PRINCIPALE: DUMP DES DONNÉES
// ═══════════════════════════════════════════════════════════════════════════════

inline void DumpBotData(
    SCStudyInterfaceRef sc,
    bool is_nq,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const BotState& state,
    float current_price,
    float vix,
    int vix_regime,
    float atr,
    float correlation,
    const char* session,
    // Optionnel: Résultats Layers (nullptr si pas calculés)
    const Layer1Result* l1 = nullptr,
    const Layer2Result* l2 = nullptr,
    const Layer3Result* l3 = nullptr,
    const Layer4Result* l4 = nullptr
) {
    if (!g_data_dump_enabled) return;
    
    // Vérifier intervalle minimum
    long long current_ms = (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    long long& last_dump = is_nq ? g_last_dump_nq_ms : g_last_dump_es_ms;
    
    if (current_ms - last_dump < DATA_DUMP_INTERVAL_MS) {
        return;  // Pas assez de temps depuis le dernier dump
    }
    last_dump = current_ms;
    
    // Incrémenter séquence
    unsigned int& seq = is_nq ? g_dump_seq_nq : g_dump_seq_es;
    seq++;
    
    // Créer chemin avec structure date
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    const char* sym = is_nq ? "NQ" : "ES";
    
    // Créer répertoires
    char dir_path[512];
    snprintf(dir_path, sizeof(dir_path),
        "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_DATA\\%04d\\%02d\\%04d%02d%02d",
        year, month, year, month, day
    );
    
    char tmp[512];
    CreateDirectoryA("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_DATA", NULL);
    snprintf(tmp, sizeof(tmp), "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_DATA\\%04d", year);
    CreateDirectoryA(tmp, NULL);
    snprintf(tmp, sizeof(tmp), "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\BOT_DATA\\%04d\\%02d", year, month);
    CreateDirectoryA(tmp, NULL);
    CreateDirectoryA(dir_path, NULL);
    
    // Fichier
    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "%s\\bot_data_%s_%04d%02d%02d.jsonl",
        dir_path, sym, year, month, day
    );
    
    FILE* f = fopen(filepath, "a");
    if (!f) {
        // 🔧 01/02/2026: Log erreur si fichier non ouvert
        char err_msg[256];
        snprintf(err_msg, sizeof(err_msg), "❌ DUMP ERROR: Cannot open %s", filepath);
        sc.AddMessageToLog(err_msg, 1);
        return;
    }
    
    // 🔧 01/02/2026: Log périodique pour confirmer que le dump fonctionne
    static int dump_log_counter = 0;
    if (++dump_log_counter >= 60) {  // Log toutes les 60 lignes (1 minute)
        dump_log_counter = 0;
        char dump_msg[256];
        snprintf(dump_msg, sizeof(dump_msg), 
                 "📊 DUMP %s: seq=%u bn_score=%.2f color_up=%.0f color_dn=%.0f → %s",
                 sym, seq, bn.score, bn.color_up, bn.color_down, filepath);
        sc.AddMessageToLog(dump_msg, 0);
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CONSTRUIRE LE JSON COMPLET
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Header + Prix
    fprintf(f, "{\"_schema\":{\"v\":\"%s\",\"type\":\"bot_data\"},"
               "\"t_ms\":%lld,\"seq\":%u,\"sym\":\"%s\",\"session\":\"%s\","
               "\"price\":{\"last\":%.2f,\"bid\":%.2f,\"ask\":%.2f,\"spread\":%.2f},"
            ,
            MIA_SCHEMA_VERSION,
            current_ms, seq, sym, session,
            current_price, current_price - 0.25f, current_price + 0.25f, 0.5f  // Approximation spread
    );
    
    // Bataille Navale - Footprint
    fprintf(f, "\"bn_fp\":{\"edge_buy\":%.0f,\"edge_sell\":%.0f,\"color_up\":%.0f,\"color_down\":%.0f,"
               "\"absorb_ask\":%.0f,\"absorb_bid\":%.0f,\"triple_ask\":%.0f,\"triple_bid\":%.0f,"
               "\"rotation_up\":%.0f,\"rotation_down\":%.0f,\"volume_up\":%.0f,\"volume_down\":%.0f},"
            ,
            bn.edge_buy, bn.edge_sell, bn.color_up, bn.color_down,
            bn.absorb_ask, bn.absorb_bid, bn.triple_ask, bn.triple_bid,
            bn.rotation_up, bn.rotation_down, bn.volume_up, bn.volume_down
    );
    
    // Bataille Navale - Barres
    fprintf(f, "\"bn_bar\":{\"long_dn_up\":%.0f,\"long_up_dn\":%.0f,\"long_up\":%.0f,\"long_dn\":%.0f,"
               "\"edge_buy\":%.0f,\"edge_sell\":%.0f,\"color_up\":%.0f,\"color_down\":%.0f},"
            ,
            bn.long_down_up, bn.long_up_down, bn.long_up_bar, bn.long_down_bar,
            bn.bar_edge_buy, bn.bar_edge_sell, bn.bar_color_up, bn.bar_color_down
    );
    
    // Bataille Navale - Ordres
    fprintf(f, "\"bn_orders\":{\"ask_10\":%.0f,\"bid_10\":%.0f,\"ask_30\":%.0f,\"bid_30\":%.0f,"
               "\"ask_100\":%.0f,\"bid_100\":%.0f,\"ask_150\":%.0f,\"bid_150\":%.0f,\"cluster\":%.0f},"
            ,
            bn.ask_10, bn.bid_10, bn.ask_30, bn.bid_30,
            bn.ask_100, bn.bid_100, bn.ask_150, bn.bid_150, bn.cluster_vol
    );
    
    // Bataille Navale - FPBS
    fprintf(f, "\"bn_fpbs\":{\"delta\":%.0f,\"delta_day\":%.0f,\"cvd\":%.0f,\"poc\":%.2f,"
               "\"ask_pct\":%.2f,\"bid_pct\":%.2f},"
            ,
            bn.fpbs_delta, bn.fpbs_delta_day, bn.fpbs_cvd, bn.fpbs_poc,
            bn.fpbs_ask_pct, bn.fpbs_bid_pct
    );
    
    // Bataille Navale - Scores
    fprintf(f, "\"bn_scores\":{\"score\":%.4f,\"signal\":%d,\"momentum\":%.4f,\"reversal\":%.4f,"
               "\"inst_pressure\":%.4f,\"buyer_str\":%.4f,\"seller_str\":%.4f,"
               "\"cvd_slope\":%.4f,\"cvd_div\":%s,\"poc_confirm\":%d},"
            ,
            bn.score, bn.signal, bn.momentum_score, bn.reversal_score,
            bn.institutional_pressure, bn.buyer_strength, bn.seller_strength,
            bn.cvd_slope, bn.cvd_divergence ? "true" : "false", bn.poc_confirm
    );
    
    // Bataille Navale - Rectangles
    fprintf(f, "\"bn_rect\":{\"buy_count\":%d,\"sell_count\":%d,\"edge_buy_count\":%d,\"edge_sell_count\":%d,"
               "\"buy_price\":%.2f,\"sell_price\":%.2f},"
            ,
            bn.num_rect_buy, bn.num_rect_sell, bn.num_edge_rect_buy, bn.num_edge_rect_sell,
            bn.rect_buy_price, bn.rect_sell_price
    );
    
    // 🆕 31/01/2026: Bataille Navale - Delta Divergence (signal de retournement)
    fprintf(f, "\"bn_delta_div\":{\"buy\":%s,\"sell\":%s,\"strength\":%.2f},"
            ,
            bn.delta_div_buy ? "true" : "false",
            bn.delta_div_sell ? "true" : "false",
            bn.delta_div_strength
    );
    
    // 🆕 31/01/2026: Swing Structure + Single Prints (Charts 28/29)
    // Points pivots + zones de faiblesse (creux volume = traits bleus)
    fprintf(f, "\"bn_swing\":{\"high\":%.2f,\"low\":%.2f,"
               "\"delta_bar_bull\":%s,\"delta_bar_bear\":%s,"
               "\"sp_high\":%.2f,\"sp_low\":%.2f,\"near_sp\":%s,"
               "\"session_poc\":%.2f,\"session_vah\":%.2f,\"session_val\":%.2f},"
            ,
            bn.swing_high, bn.swing_low,
            bn.delta_bar_bullish ? "true" : "false",
            bn.delta_bar_bearish ? "true" : "false",
            bn.single_print_high, bn.single_print_low,
            bn.near_single_print ? "true" : "false",
            bn.session_poc, bn.session_vah, bn.session_val
    );
    
    // MenthorQ - Niveaux
    fprintf(f, "\"mq_levels\":{\"hvl\":%.2f,\"hvl_0dte\":%.2f,\"gamma\":%.2f,\"gamma_0dte\":%.2f,"
               "\"call_res\":%.2f,\"call_0dte\":%.2f,\"put_sup\":%.2f,\"put_0dte\":%.2f,"
               "\"day_min\":%.2f,\"day_max\":%.2f,\"vah\":%.2f,\"val\":%.2f,"
               "\"next_wall\":%.2f,\"wall_dist\":%.1f},"
            ,
            mq.hvl, mq.hvl_0dte, mq.gamma_wall, mq.gamma_wall_0dte,
            mq.call_resistance, mq.call_resistance_0dte, mq.put_support, mq.put_support_0dte,
            mq.day_min, mq.day_max, mq.vah, mq.val,
            mq.next_wall, mq.wall_distance_ticks
    );
    
    // MenthorQ - VWAP
    fprintf(f, "\"mq_vwap\":{\"v\":%.2f,\"up1\":%.2f,\"dn1\":%.2f,\"up2\":%.2f,\"dn2\":%.2f,\"slope\":%.6f},"
            ,
            mq.vwap, mq.vwap_up1, mq.vwap_dn1, mq.vwap_up2, mq.vwap_dn2,
            is_nq ? g_market_live.vwap_slope_nq : g_market_live.vwap_slope_es
    );
    
    // MenthorQ - GEX (compact array)
    fprintf(f, "\"mq_gex\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
            ,
            mq.gex[0], mq.gex[1], mq.gex[2], mq.gex[3], mq.gex[4],
            mq.gex[5], mq.gex[6], mq.gex[7], mq.gex[8], mq.gex[9]
    );
    
    // MenthorQ - Blind Spots (compact array)
    fprintf(f, "\"mq_blind\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
            ,
            mq.blind_spots[0], mq.blind_spots[1], mq.blind_spots[2],
            mq.blind_spots[3], mq.blind_spots[4], mq.blind_spots[5],
            mq.blind_spots[6], mq.blind_spots[7], mq.blind_spots[8]
    );
    
    // 🆕 31/01/2026: MenthorQ - Previous Levels (niveaux de la veille)
    fprintf(f, "\"mq_prev\":{\"vah\":%.2f,\"val\":%.2f,\"vpoc\":%.2f,"
               "\"vwap\":%.2f,\"vwap_sd1_up\":%.2f,\"vwap_sd1_dn\":%.2f},"
            ,
            mq.prev_vah, mq.prev_val, mq.prev_vpoc,
            mq.prev_vwap, mq.prev_vwap_sd1_up, mq.prev_vwap_sd1_dn
    );
    
    // Indicateurs Globaux
    fprintf(f, "\"global\":{\"vix\":%.2f,\"vix_regime\":%d,\"atr\":%.2f,\"corr_es_nq\":%.4f},"
            ,
            vix, vix_regime, atr, correlation
    );
    
    // État Bot
    fprintf(f, "\"state\":{\"in_pos\":%s,\"dir\":%d,\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,"
               "\"trades\":%d,\"wins\":%d,\"pnl\":%.2f},"
            ,
            state.in_position ? "true" : "false", state.direction,
            state.entry_price, state.sl_price, state.tp_price,
            state.trades_today, state.wins_today, state.pnl_today
    );
    
    // Layer Results (si disponibles)
    if (l1 && l2 && l3 && l4) {
        fprintf(f, "\"layers\":{"
                   "\"l1\":{\"pass\":%s,\"conf\":%.2f,\"level\":\"%s\",\"dist\":%.1f},"
                   "\"l2\":{\"pass\":%s,\"conf\":%.2f,\"bn\":%.4f,\"corr\":\"%s\"},"
                   "\"l3\":{\"pass\":%s,\"conf\":%.2f,\"veto\":%s,\"ctx\":\"%s\"},"
                   "\"l4\":{\"pass\":%s,\"combo\":%d,\"pct\":%s,\"edge\":%s}}"
                ,
                l1->passed ? "true" : "false", l1->confidence, l1->level_name, l1->distance_ticks,
                l2->passed ? "true" : "false", l2->confidence, l2->bn_score, l2->correlation,
                l3->passed ? "true" : "false", l3->confidence, l3->veto ? "true" : "false", l3->context,
                l4->passed ? "true" : "false", l4->combo_aligned, l4->pct_ok ? "true" : "false", l4->edge_ok ? "true" : "false"
        );
    } else {
        // Pas de layers calculés
        fprintf(f, "\"layers\":null");
    }
    
    // Fermer JSON
    fprintf(f, "}\n");
    
    fclose(f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// VERSION SIMPLIFIÉE: DUMP SANS LAYERS (pour appel fréquent)
// ═══════════════════════════════════════════════════════════════════════════════

inline void DumpBotDataSimple(
    SCStudyInterfaceRef sc,
    bool is_nq,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    const BotState& state,
    float current_price,
    float vix,
    int vix_regime,
    float atr,
    const char* session
) {
    DumpBotData(sc, is_nq, bn, mq, state, current_price, vix, vix_regime, atr, 0.0f, session,
                nullptr, nullptr, nullptr, nullptr);
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONTRÔLE DU DUMPER
// ═══════════════════════════════════════════════════════════════════════════════

inline void EnableDataDump(bool enable) {
    g_data_dump_enabled = enable;
}

inline bool IsDataDumpEnabled() {
    return g_data_dump_enabled;
}

// Réinitialiser les compteurs (appelé au reset quotidien)
inline void ResetDataDumpCounters() {
    g_dump_seq_es = 0;
    g_dump_seq_nq = 0;
    g_last_dump_es_ms = 0;
    g_last_dump_nq_ms = 0;
}