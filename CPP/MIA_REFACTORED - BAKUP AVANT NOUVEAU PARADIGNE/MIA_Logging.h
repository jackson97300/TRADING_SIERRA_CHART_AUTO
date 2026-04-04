#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Logging.h - SECTION 13: SaveSnapshot, LogWhy, Discord, JSON
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 6368-7514)
// Refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Execution.h"

// Forward declarations
inline void LogTradeResult(SCStudyInterfaceRef sc, const TradeSnapshot& snap, const SymbolConfig& config);

inline void SaveTradeSnapshot(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    // Créer nom fichier: MIA_TRADES_ES_20260117.json
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\SNAPSHOTS\\MIA_TRADE_%s_%04d%02d%02d_%06d.json",
             config.name, year, month, day, snap.trade_id);

    std::ofstream file(filename);
    if (!file.is_open()) return;

    file << "{\n";
    
    // 🆕 31/01/2026: HEADER VERSIONNÉ pour compatibilité Python/C++
    file << "  \"_schema\": {\n";
    file << "    \"version\": \"" << MIA_SCHEMA_VERSION << "\",\n";
    file << "    \"type\": \"trade_snapshot\",\n";
    file << "    \"build\": \"" << MIA_BUILD_REFACTORED << "\",\n";
    file << "    \"generated_at\": \"" << FormatTimestamp(sc.CurrentSystemDateTime) << "\"\n";
    file << "  },\n";
    
    file << "  \"trade_id\": " << snap.trade_id << ",\n";
    file << "  \"symbol\": \"" << snap.symbol << "\",\n";
    file << "  \"entry_time\": \"" << FormatTimestamp(snap.entry_time) << "\",\n";
    file << "  \"exit_time\": \"" << FormatTimestamp(snap.exit_time) << "\",\n";
    file << "  \"direction\": \"" << (snap.direction == 1 ? "LONG" : "SHORT") << "\",\n";
    file << "  \"entry_price\": " << std::fixed << std::setprecision(2) << snap.entry_price << ",\n";
    file << "  \"exit_price\": " << snap.exit_price << ",\n";
    file << "  \"sl_price\": " << snap.sl_price << ",\n";
    file << "  \"tp_price\": " << snap.tp_price << ",\n";
    file << "  \"pnl\": " << snap.pnl << ",\n";
    file << "  \"exit_reason\": \"" << snap.exit_reason << "\",\n";

    // Layers avec détails complets
    file << "  \"layers\": {\n";
    file << "    \"l1\": {\"passed\": " << (snap.l1_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l1_confidence
         << ", \"level\": \"" << snap.l1_level_name << "\""
         << ", \"price\": " << snap.l1_level_price
         << ", \"distance_ticks\": " << snap.l1_distance_ticks << "},\n";
    file << "    \"l2\": {\"passed\": " << (snap.l2_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l2_confidence
         << ", \"bn_score\": " << snap.l2_bn_score
         << ", \"visual_signals\": " << snap.l2_visual_signals
         << ", \"correlation\": \"" << snap.l2_correlation << "\"},\n";
    file << "    \"l3\": {\"passed\": " << (snap.l3_passed ? "true" : "false")
         << ", \"confidence\": " << snap.l3_confidence
         << ", \"context\": \"" << snap.l3_context << "\"},\n";
    file << "    \"l4\": {\"passed\": " << (snap.l4_passed ? "true" : "false")
         << ", \"combo\": " << snap.l4_combo_aligned
         << ", \"pct_ok\": " << (snap.l4_pct_ok ? "true" : "false")
         << ", \"delta_ok\": " << (snap.l4_delta_ok ? "true" : "false")
         << ", \"bn_ok\": " << (snap.l4_bn_ok ? "true" : "false")
         << ", \"vwap_ok\": " << (snap.l4_vwap_ok ? "true" : "false") << "}\n";
    file << "  },\n";

    // 🆕 Nouvelles données pour analyse
    file << "  \"trade_analysis\": {\n";
    file << "    \"is_rectangle_trade\": " << (snap.is_rectangle_trade ? "true" : "false") << ",\n";
    file << "    \"extension_line_dist\": " << snap.extension_line_dist << ",\n";
    file << "    \"vwap_slope\": " << std::setprecision(4) << snap.vwap_slope << ",\n";
    file << "    \"confluence_count\": " << snap.confluence_count << ",\n";
    // 🆕 CVD & POC at entry (pour analyser les trades)
    file << "    \"cvd_at_entry\": " << std::setprecision(0) << snap.bn_es.fpbs_cvd << ",\n";
    file << "    \"cvd_slope_at_entry\": " << snap.bn_es.cvd_slope << ",\n";
    file << "    \"cvd_divergence\": " << (snap.bn_es.cvd_divergence ? "true" : "false") << ",\n";
    file << "    \"poc_at_entry\": " << std::setprecision(2) << snap.bn_es.fpbs_poc << ",\n";
    file << "    \"poc_confirm\": " << snap.bn_es.poc_confirm << ",\n";
    file << "    \"poc_confirm_text\": \"" << (snap.bn_es.poc_confirm == 1 ? "BULLISH" : (snap.bn_es.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "  },\n";

    // Bataille Navale COMPLET (toutes les données)
    file << "  \"bataille_navale\": {\n";
    file << "    \"es\": {\n";
    file << "      \"score\": " << snap.bn_es.score << ",\n";
    file << "      \"momentum_score\": " << snap.bn_es.momentum_score << ",\n";
    file << "      \"reversal_score\": " << snap.bn_es.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << snap.bn_es.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << snap.bn_es.edge_buy << ", \"edge_sell\": " << snap.bn_es.edge_sell << ",\n";
    file << "      \"color_up\": " << snap.bn_es.color_up << ", \"color_down\": " << snap.bn_es.color_down << ",\n";
    file << "      \"absorb_ask\": " << snap.bn_es.absorb_ask << ", \"absorb_bid\": " << snap.bn_es.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << snap.bn_es.rotation_up << ", \"rotation_down\": " << snap.bn_es.rotation_down << ",\n";
    file << "      \"long_down_up\": " << snap.bn_es.long_down_up << ", \"long_up_down\": " << snap.bn_es.long_up_down << ",\n";
    file << "      \"double_ask\": " << snap.bn_es.double_ask << ", \"double_bid\": " << snap.bn_es.double_bid << ",\n";
    file << "      \"ask_100\": " << snap.bn_es.ask_100 << ", \"bid_100\": " << snap.bn_es.bid_100 << ",\n";
    file << "      \"ask_400\": " << snap.bn_es.ask_400 << ", \"bid_400\": " << snap.bn_es.bid_400 << ",\n";
    file << "      \"ask_1000\": " << snap.bn_es.ask_1000 << ", \"bid_1000\": " << snap.bn_es.bid_1000 << ",\n";
    file << "      \"fpbs_ask_pct\": " << snap.bn_es.fpbs_ask_pct << ", \"fpbs_bid_pct\": " << snap.bn_es.fpbs_bid_pct << ",\n";
    file << "      \"cluster_vol\": " << snap.bn_es.cluster_vol << ",\n";
    file << "      \"bar_color_up\": " << snap.bn_es.bar_color_up << ", \"bar_color_down\": " << snap.bn_es.bar_color_down << ",\n";
    file << "      \"bar_edge_buy\": " << snap.bn_es.bar_edge_buy << ", \"bar_edge_sell\": " << snap.bn_es.bar_edge_sell << ",\n";
    file << "      \"ext_support\": " << snap.bn_es.nearest_ext_support << ", \"ext_resist\": " << snap.bn_es.nearest_ext_resist << "\n";
    file << "    },\n";
    file << "    \"nq\": {\n";
    file << "      \"score\": " << snap.bn_nq.score << ",\n";
    file << "      \"momentum_score\": " << snap.bn_nq.momentum_score << ",\n";
    file << "      \"reversal_score\": " << snap.bn_nq.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << snap.bn_nq.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << snap.bn_nq.edge_buy << ", \"edge_sell\": " << snap.bn_nq.edge_sell << ",\n";
    file << "      \"color_up\": " << snap.bn_nq.color_up << ", \"color_down\": " << snap.bn_nq.color_down << ",\n";
    file << "      \"absorb_ask\": " << snap.bn_nq.absorb_ask << ", \"absorb_bid\": " << snap.bn_nq.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << snap.bn_nq.rotation_up << ", \"rotation_down\": " << snap.bn_nq.rotation_down << ",\n";
    file << "      \"long_down_up\": " << snap.bn_nq.long_down_up << ", \"long_up_down\": " << snap.bn_nq.long_up_down << ",\n";
    file << "      \"triple_ask\": " << snap.bn_nq.triple_ask << ", \"triple_bid\": " << snap.bn_nq.triple_bid << ",\n";
    file << "      \"volume_up\": " << snap.bn_nq.volume_up << ", \"volume_down\": " << snap.bn_nq.volume_down << ",\n";
    file << "      \"ask_100\": " << snap.bn_nq.ask_100 << ", \"bid_100\": " << snap.bn_nq.bid_100 << ",\n";
    file << "      \"fpbs_ask_pct\": " << snap.bn_nq.fpbs_ask_pct << ", \"fpbs_bid_pct\": " << snap.bn_nq.fpbs_bid_pct << ",\n";
    file << "      \"cluster_vol\": " << snap.bn_nq.cluster_vol << ",\n";
    file << "      \"bar_color_up\": " << snap.bn_nq.bar_color_up << ", \"bar_color_down\": " << snap.bn_nq.bar_color_down << ",\n";
    file << "      \"bar_edge_buy\": " << snap.bn_nq.bar_edge_buy << ", \"bar_edge_sell\": " << snap.bn_nq.bar_edge_sell << ",\n";
    file << "      \"ext_support\": " << snap.bn_nq.nearest_ext_support << ", \"ext_resist\": " << snap.bn_nq.nearest_ext_resist << "\n";
    file << "    }\n";
    file << "  },\n";

    // Market context
    file << "  \"market\": {\n";
    file << "    \"vix\": " << snap.vix << ",\n";
    file << "    \"atr\": " << snap.atr << ",\n";
    file << "    \"spread\": " << snap.spread << ",\n";
    file << "    \"delta\": " << snap.delta << ",\n";
    file << "    \"cum_delta\": " << snap.cum_delta << ",\n";
    file << "    \"buy_pct\": " << snap.buy_pct << ",\n";
    file << "    \"session\": \"" << snap.session << "\"\n";
    file << "  }\n";

    file << "}\n";
    file.close();

    // === LOGGER LE TRADE DANS WIN OU LOSS ===
    LogTradeResult(sc, snap, config);
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOGGING TRADES WIN/LOSS SÉPARÉS PAR JOUR
// ═══════════════════════════════════════════════════════════════════════════════
inline void LogTradeResult(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    // Déterminer si WIN ou LOSS
    const char* folder = (snap.pnl >= 0) ? "TRADES_WIN" : "TRADES_LOSS";

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\%s\\%s_%04d%02d%02d.log",
             folder, config.name, year, month, day);

    // Ouvrir en mode append
    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    // Format V2: TIME|SYM|DIR|ENTRY|EXIT|PNL|REASON|BN|L1|L2|L3|L4|RECT|VWAP|SIGNALS|EXTDIST
    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << snap.symbol << "|"
         << (snap.direction == 1 ? "LONG" : "SHORT") << "|"
         << std::fixed << std::setprecision(2)
         << snap.entry_price << "|"
         << snap.exit_price << "|"
         << (snap.pnl >= 0 ? "+" : "") << snap.pnl << "|"
         << snap.exit_reason << "|"
         << (strcmp(config.name, "ES") == 0 ? snap.bn_es.score : snap.bn_nq.score) << "|"
         << snap.l1_confidence << "|"
         << snap.l2_confidence << "|"
         << snap.l3_confidence << "|"
         << snap.l4_combo_aligned << "|"
         << (snap.is_rectangle_trade ? "RECT" : "MQ") << "|"          // 🆕 Type de trade
         << std::setprecision(4) << snap.vwap_slope << "|"            // 🆕 Pente VWAP
         << snap.l2_visual_signals << "|"                              // 🆕 Nb signaux visuels
         << std::setprecision(1) << snap.extension_line_dist << "\n";  // 🆕 Dist extension

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOG SYNC POSITION - Log quand une position manuelle est detectee
// ═══════════════════════════════════════════════════════════════════════════════
inline void LogSyncPosition(SCStudyInterfaceRef sc, const char* symbol, int direction, float entry_price) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\SYNC\\sync_%04d%02d%02d.log",
             year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << symbol << "|"
         << (direction == 1 ? "LONG" : "SHORT") << "|"
         << std::fixed << std::setprecision(2) << entry_price << "|"
         << "MANUAL_OR_SIMPLEBRACKET\n";

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION: DISCORD INTEGRATION - Ecriture evenements pour bridge Python
// ═══════════════════════════════════════════════════════════════════════════════

inline void WriteDiscordEvent(SCStudyInterfaceRef sc, const char* json_data) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\DISCORD_EVENTS\\events_%04d%02d%02d.jsonl",
             year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    file << json_data << "\n";
    file.close();
}

inline void NotifyDiscordTradeOpened(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config,
    float bn_score,
    float vwap_slope
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    // 🆕 Déterminer le texte POC confirm
    const char* poc_text = (snap.bn_es.poc_confirm == 1) ? "BULL" : 
                           (snap.bn_es.poc_confirm == -1) ? "BEAR" : "NEUT";
    
    // 🆕 Déterminer le texte CVD trend
    const char* cvd_text = (snap.bn_es.cvd_slope > 100) ? "UP" :
                           (snap.bn_es.cvd_slope < -100) ? "DN" : "FLAT";

    char json[1280];  // 🔧 Agrandi pour nouvelles données
    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_OPENED\",\"time\":\"%02d:%02d:%02d\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"pnl\":0,\"l1_conf\":%.2f,\"l2_conf\":%.2f,"
             "\"l3_conf\":%.2f,\"l4_combo\":%d,\"bn_score\":%.3f,\"vwap_slope\":%.4f,\"is_rectangle\":%s,"
             "\"cvd_slope\":%.0f,\"cvd_trend\":\"%s\",\"poc_confirm\":\"%s\"}",
             hour, minute, second, snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.sl_price, snap.tp_price,
             snap.l1_confidence, snap.l2_confidence, snap.l3_confidence,
             snap.l4_combo_aligned, bn_score, vwap_slope,
             snap.is_rectangle_trade ? "true" : "false",
             snap.bn_es.cvd_slope, cvd_text, poc_text);

    WriteDiscordEvent(sc, json);
}

inline void NotifyDiscordTradeClosed(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    // Calculer durée
    double duration_sec = (snap.exit_time - snap.entry_time).GetAsDouble() * 86400.0;

    char json[1024];
    snprintf(json, sizeof(json),
             "{\"type\":\"TRADE_CLOSED\",\"time\":\"%02d:%02d:%02d\",\"symbol\":\"%s\",\"direction\":\"%s\","
             "\"entry\":%.2f,\"exit\":%.2f,\"pnl\":%.2f,\"exit_reason\":\"%s\",\"duration_sec\":%.0f}",
             hour, minute, second, snap.symbol,
             snap.direction == 1 ? "LONG" : "SHORT",
             snap.entry_price, snap.exit_price, snap.pnl,
             snap.exit_reason, duration_sec);

    WriteDiscordEvent(sc, json);
}

// ═══════════════════════════════════════════════════════════════════════════════
// TRADE WHY JOURNAL - Journal explicatif de chaque trade/setup
// ═══════════════════════════════════════════════════════════════════════════════

// 🆕 Helper: Construire TradeWhy depuis les données disponibles
TradeWhy BuildTradeWhy(
    SCStudyInterfaceRef sc,
    const char* symbol,
    int direction,
    float current_price,
    const Layer1Result& l1,
    const Layer2Result& l2,
    const Layer3Result& l3,
    const Layer4Result& l4,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    float vix,
    float bn_anchor,
    bool is_rectangle,
    const RectangleSignal& rect_signal,
    const SymbolConfig& config,
    const char* execution_mode,
    const char* reject_reason = nullptr
) {
    TradeWhy why = {0};
    why.trade_id = g_trade_why_id++;
    why.timestamp = sc.CurrentSystemDateTime;
    strncpy(why.symbol, symbol, sizeof(why.symbol) - 1);
    strncpy(why.side, direction == 1 ? "LONG" : "SHORT", sizeof(why.side) - 1);
    strncpy(why.execution_mode, execution_mode ? execution_mode : "PENDING", sizeof(why.execution_mode) - 1);

    // Trigger level
    if (is_rectangle && rect_signal.has_signal) {
        strncpy(why.trigger_level_type, "RECT", sizeof(why.trigger_level_type) - 1);
        why.trigger_level_price = rect_signal.rectangle_price;
    } else {
        strncpy(why.trigger_level_type, l1.level_name, sizeof(why.trigger_level_type) - 1);
        why.trigger_level_price = l1.level_price;
    }

    // Anchor
    why.anchor_final = bn_anchor > 0 ? bn_anchor : current_price;
    why.anchor_ext = (bn.num_ext_support > 0 || bn.num_ext_resist > 0) ? why.anchor_final : 0;
    why.anchor_color = 0;
    why.dist_ticks_to_anchor = fabs(current_price - why.anchor_final) / config.tick_size;

    // Trade info
    why.entry_price = current_price;
    why.qty = 1;

    // Layers
    why.l1_ok = l1.passed ? 1 : 0;
    why.l2_ok = l2.passed ? 1 : 0;
    why.l3_ok = l3.passed ? 1 : 0;
    why.l4_ok = l4.passed ? 1 : 0;
    why.l1_confidence = l1.confidence;
    why.l2_confidence = l2.confidence;
    why.l3_confidence = l3.confidence;
    why.l4_combo = l4.combo_aligned;
    why.bn_score = bn.score;
    why.confluence_score = l2.confidence;
    why.is_rectangle = is_rectangle;

    // Contexte marché
    float vwap_slope = (strcmp(symbol, "ES") == 0) ? g_market_live.vwap_slope_es : g_market_live.vwap_slope_nq;
    why.vwap_slope = vwap_slope;
    why.vwap_dist_ticks = fabs(current_price - mq.vwap) / config.tick_size;
    why.vix_value = vix;
    strncpy(why.vix_regime, GetVIXRegimeName(g_market_live.vix_regime), sizeof(why.vix_regime) - 1);
    why.dom_healthy = 1;
    why.spread_ticks = 1.0f;

    // Veto
    why.veto_triggered = (reject_reason != nullptr) ? 1 : 0;
    if (reject_reason) {
        strncpy(why.veto_reason, reject_reason, sizeof(why.veto_reason) - 1);
    }
    if (l3.veto) {
        strncpy(why.layer_reject_reason, l3.veto_reason, sizeof(why.layer_reject_reason) - 1);
    } else if (!l2.passed) {
        strncpy(why.layer_reject_reason, l2.reason, sizeof(why.layer_reject_reason) - 1);
    } else if (!l3.passed) {
        strncpy(why.layer_reject_reason, l3.context, sizeof(why.layer_reject_reason) - 1);
    }

    // Notes
    snprintf(why.notes, sizeof(why.notes), "L1:%s L4:%d/4", l1.level_name, l4.combo_aligned);

    return why;
}

inline void LogTradeWhy(
    SCStudyInterfaceRef sc,
    const TradeWhy& why,
    const SymbolConfig& config
) {
    int y, mo, d, h, mi, s;
    why.timestamp.GetDateTimeYMDHMS(y, mo, d, h, mi, s);

    // === SÉPARATION TRADES / REJETS ===
    // Trades (IMMEDIATE, PENDING_LIMIT, SKIP_TOO_FAR) → TRADES_WHY/
    // Rejets (REJECTED) → REJETS_WHY/
    bool is_reject = (strcmp(why.execution_mode, "REJECTED") == 0);

    char csv_file[256];
    if (is_reject) {
        // Rejets: REJETS_WHY/[ES|NQ]/REJET_WHY_[SYM]_YYYYMMDD.csv
        snprintf(csv_file, sizeof(csv_file),
            "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\REJETS_WHY\\%s\\REJET_WHY_%s_%04d%02d%02d.csv",
            why.symbol, why.symbol, y, mo, d);
    } else {
        // Trades: TRADES_WHY/[ES|NQ]/TRADE_WHY_[SYM]_YYYYMMDD.csv
        snprintf(csv_file, sizeof(csv_file),
            "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADES_WHY\\%s\\TRADE_WHY_%s_%04d%02d%02d.csv",
            why.symbol, why.symbol, y, mo, d);
    }

    std::ofstream csv(csv_file, std::ios::app);
    if (!csv.is_open()) return;

    // Header si fichier vide
    csv.seekp(0, std::ios::end);
    bool is_new_file = (csv.tellp() == 0);
    if (is_new_file) {
        csv << "trade_id;timestamp;symbol;side;execution_mode;"
            << "trigger_level_type;trigger_level_price;anchor_ext;anchor_color;anchor_final;dist_ticks_to_anchor;"
            << "entry_price;sl_price;tp_price;qty;"
            << "l1_ok;l2_ok;l3_ok;l4_ok;l1_conf;l2_conf;l3_conf;l4_combo;bn_score;confluence_score;is_rectangle;"
            << "vwap_slope;vwap_dist_ticks;vix_value;vix_regime;dom_healthy;spread_ticks;"
            << "veto_triggered;veto_reason;layer_reject_reason;notes\n";
    }

    // Ligne CSV
    csv << why.trade_id << ";"
        << std::setfill('0') << std::setw(4) << y << "-"
        << std::setw(2) << mo << "-"
        << std::setw(2) << d << " "
        << std::setw(2) << h << ":"
        << std::setw(2) << mi << ":"
        << std::setw(2) << s << ";"
        << why.symbol << ";"
        << why.side << ";"
        << why.execution_mode << ";"
        << why.trigger_level_type << ";"
        << std::fixed << std::setprecision(2) << why.trigger_level_price << ";"
        << why.anchor_ext << ";"
        << why.anchor_color << ";"
        << why.anchor_final << ";"
        << std::setprecision(1) << why.dist_ticks_to_anchor << ";"
        << std::setprecision(2) << why.entry_price << ";"
        << why.sl_price << ";"
        << why.tp_price << ";"
        << why.qty << ";"
        << why.l1_ok << ";"
        << why.l2_ok << ";"
        << why.l3_ok << ";"
        << why.l4_ok << ";"
        << std::setprecision(3) << why.l1_confidence << ";"
        << why.l2_confidence << ";"
        << why.l3_confidence << ";"
        << why.l4_combo << ";"
        << why.bn_score << ";"
        << why.confluence_score << ";"
        << (why.is_rectangle ? 1 : 0) << ";"
        << std::setprecision(4) << why.vwap_slope << ";"
        << std::setprecision(1) << why.vwap_dist_ticks << ";"
        << std::setprecision(2) << why.vix_value << ";"
        << why.vix_regime << ";"
        << why.dom_healthy << ";"
        << std::setprecision(1) << why.spread_ticks << ";"
        << why.veto_triggered << ";"
        << "\"" << why.veto_reason << "\";"
        << "\"" << why.layer_reject_reason << "\";"
        << "\"" << why.notes << "\"\n";

    csv.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOG DES SIGNAUX REJETES - V53 avec VWAP SLOPE
// ═══════════════════════════════════════════════════════════════════════════════
// CRUCIAL: Permet d'etudier les patterns de rejet et optimiser les seuils
// Fichier: LOGS/REJETS/[SYMBOL]_REJETS_[DATE].log
// Format V53: TIME|SYM|DIR|PRICE|LAYER|REASON|LVL|DIST|VIX|BN|VWAP_SLOPE
// ═══════════════════════════════════════════════════════════════════════════════
inline void LogRejectedSignal(
    SCStudyInterfaceRef sc,
    const SymbolConfig& config,
    const char* direction,
    const char* layer,           // "L1", "L2", "L3", "L3_VETO", "L4"
    const char* reject_reason,
    float current_price,
    float nearest_level,         // Niveau MenthorQ le plus proche (0 si aucun)
    float distance_ticks,        // Distance en ticks
    float vix,
    float bn_score
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\REJETS\\%s_REJETS_%04d%02d%02d.log",
             config.name, year, month, day);

    std::ofstream file(filename, std::ios::app);
    if (!file.is_open()) return;

    // Header si fichier vide/nouveau
    file.seekp(0, std::ios::end);
    if (file.tellp() == 0) {
        file << "# MIA AutoTrader V53 - Log des signaux rejetes\n";
        file << "# Layer 4: 2/4 (pct + delta + bn + vwap_slope)\n";
        file << "# Format: TIME|SYM|DIR|PRICE|LAYER|REASON|LVL|DIST|VIX|BN|VWAP_SLOPE\n";
        file << "# ════════════════════════════════════════════════════════════════════════════\n";
    }

    // Recuperer le VWAP slope selon le symbole
    float vwap_slope = 0;
    if (strcmp(config.name, "ES") == 0) {
        vwap_slope = g_market_live.vwap_slope_es;
    } else {
        vwap_slope = g_market_live.vwap_slope_nq;
    }

    // Ecrire le rejet avec VWAP slope
    file << std::setfill('0') << std::setw(2) << hour << ":"
         << std::setw(2) << minute << ":"
         << std::setw(2) << second << "|"
         << config.name << "|"
         << direction << "|"
         << std::fixed << std::setprecision(2) << current_price << "|"
         << layer << "|"
         << reject_reason << "|";

    // Nearest level (ou NONE si pas de niveau)
    if (nearest_level > 0) {
        file << std::fixed << std::setprecision(2) << nearest_level;
    } else {
        file << "NONE";
    }
    file << "|"
         << std::setprecision(1) << distance_ticks << "|"
         << vix << "|"
         << std::setprecision(3) << bn_score << "|"
         << std::setprecision(4) << vwap_slope << "\n";

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 AFFICHAGE DASHBOARD SUR LE GRAPHIQUE
// ═══════════════════════════════════════════════════════════════════════════════
inline void DrawDashboardOnChart(SCStudyInterfaceRef sc) {
    // Supprimer les anciens textes (IDs 9000-9010)
    for (int i = 9000; i <= 9010; i++) {
        sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_CHARTDRAWING, i);
    }

    // Couleurs selon statut
    COLORREF color_ok = RGB(0, 255, 0);       // Vert
    COLORREF color_warn = RGB(255, 255, 0);   // Jaune
    COLORREF color_block = RGB(255, 100, 100); // Rouge clair
    COLORREF color_text = RGB(255, 255, 255); // Blanc

    // Position en haut à droite du graphique
    float x_pos = 70.0f;  // % depuis la gauche (était 95, trop à droite)
    float y_start = 95.0f; // % depuis le bas (était 98)
    float line_height = 2.5f;

    int line = 0;
    s_UseTool tool;

    // === LIGNE 1: STATUT GLOBAL ===
    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("[MIA BOT] %s", g_dashboard.global_status);
    tool.Color = color_ok;
    tool.FontSize = 12;
    tool.FontBold = 1;
    sc.UseTool(tool);
    line++;

    // === LIGNE 2: SESSION ===
    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("Session: %s | VIX: %.2f", g_dashboard.current_session, g_market_live.vix);
    tool.Color = color_text;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 3: ES STATUS ===
    COLORREF es_color = color_ok;
    if (strcmp(g_dashboard.bot_action_es, "NEWS BLOCK") == 0 || strcmp(g_dashboard.bot_action_es, "BLOCKED") == 0) {
        es_color = color_block;
    } else if (strcmp(g_dashboard.bot_action_es, "WAITING") == 0) {
        es_color = color_warn;
    }

    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("ES: %s | T:%d W:%d L:%d | $%.0f",
        g_dashboard.bot_action_es,
        g_es_state.trades_today, g_es_state.wins_today, g_es_state.losses_today,
        g_es_state.pnl_today);
    // 🆕 Couleur P&L: Rouge si négatif, Vert si positif
    COLORREF pnl_color_es = (g_es_state.pnl_today >= 0) ? RGB(0, 255, 0) : RGB(255, 0, 0);
    tool.Color = pnl_color_es;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 4: ES RAISON ===
    if (strlen(g_dashboard.no_trade_reason_es) > 0) {
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = 9000 + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        tool.Text.Format("   -> %s", g_dashboard.no_trade_reason_es);
        tool.Color = RGB(200, 200, 200);
        tool.FontSize = 9;
        sc.UseTool(tool);
        line++;
    }

    // === LIGNE 5: NQ STATUS ===
    COLORREF nq_color = color_ok;
    if (strcmp(g_dashboard.bot_action_nq, "NEWS BLOCK") == 0 || strcmp(g_dashboard.bot_action_nq, "BLOCKED") == 0) {
        nq_color = color_block;
    } else if (strcmp(g_dashboard.bot_action_nq, "WAITING") == 0) {
        nq_color = color_warn;
    }

    tool.Clear();
    tool.ChartNumber = sc.ChartNumber;
    tool.DrawingType = DRAWING_TEXT;
    tool.LineNumber = 9000 + line;
    tool.AddAsUserDrawnDrawing = 0;
    tool.BeginDateTime = x_pos;
    tool.BeginValue = y_start - (line * line_height);
    tool.UseRelativeVerticalValues = 1;
    tool.Text.Format("NQ: %s | T:%d W:%d L:%d | $%.0f",
        g_dashboard.bot_action_nq,
        g_nq_state.trades_today, g_nq_state.wins_today, g_nq_state.losses_today,
        g_nq_state.pnl_today);
    // 🆕 Couleur P&L: Rouge si négatif, Vert si positif
    COLORREF pnl_color_nq = (g_nq_state.pnl_today >= 0) ? RGB(0, 255, 0) : RGB(255, 0, 0);
    tool.Color = pnl_color_nq;
    tool.FontSize = 10;
    sc.UseTool(tool);
    line++;

    // === LIGNE 6: NQ RAISON ===
    if (strlen(g_dashboard.no_trade_reason_nq) > 0) {
        tool.Clear();
        tool.ChartNumber = sc.ChartNumber;
        tool.DrawingType = DRAWING_TEXT;
        tool.LineNumber = 9000 + line;
        tool.AddAsUserDrawnDrawing = 0;
        tool.BeginDateTime = x_pos;
        tool.BeginValue = y_start - (line * line_height);
        tool.UseRelativeVerticalValues = 1;
        tool.Text.Format("   -> %s", g_dashboard.no_trade_reason_nq);
        tool.Color = RGB(200, 200, 200);
        tool.FontSize = 9;
        sc.UseTool(tool);
    }
}

inline void SaveDashboard(SCStudyInterfaceRef sc) {
    char filename[256];
    snprintf(filename, sizeof(filename),
             "D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\DASHBOARD\\MIA_AutoTrader_Dashboard.json");

    std::ofstream file(filename);
    if (!file.is_open()) return;

    file << "{\n";
    file << "  \"bot_status\": {\n";
    file << "    \"running\": " << (g_dashboard.bot_running ? "true" : "false") << ",\n";
    file << "    \"last_heartbeat\": \"" << FormatTimestamp(g_dashboard.last_heartbeat) << "\",\n";
    file << "    \"global_status\": \"" << g_dashboard.global_status << "\"\n";
    file << "  },\n";

    // ES State
    file << "  \"es\": {\n";
    file << "    \"enabled\": " << (g_es_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (g_es_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (g_es_state.in_position ? "true" : "false") << ",\n";
    file << "    \"status\": \"" << g_es_state.status_message << "\",\n";
    file << "    \"waiting_for\": \"" << g_es_state.waiting_for << "\",\n";
    file << "    \"trades_today\": " << g_es_state.trades_today << ",\n";
    file << "    \"wins\": " << g_es_state.wins_today << ",\n";
    file << "    \"losses\": " << g_es_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << std::fixed << std::setprecision(2) << g_es_state.pnl_today << ",\n";
    file << "    \"consecutive_losses\": " << g_es_state.consecutive_losses << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_es << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_es << "\",\n";
    file << "    \"last_rejected\": \"" << g_dashboard.last_rejected_es << "\",\n";
    file << "    \"signals_rejected\": " << g_dashboard.signals_rejected_es << "\n";
    file << "  },\n";

    // NQ State
    file << "  \"nq\": {\n";
    file << "    \"enabled\": " << (g_nq_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (g_nq_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (g_nq_state.in_position ? "true" : "false") << ",\n";
    file << "    \"status\": \"" << g_nq_state.status_message << "\",\n";
    file << "    \"waiting_for\": \"" << g_nq_state.waiting_for << "\",\n";
    file << "    \"trades_today\": " << g_nq_state.trades_today << ",\n";
    file << "    \"wins\": " << g_nq_state.wins_today << ",\n";
    file << "    \"losses\": " << g_nq_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << std::fixed << std::setprecision(2) << g_nq_state.pnl_today << ",\n";
    file << "    \"consecutive_losses\": " << g_nq_state.consecutive_losses << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_nq << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_nq << "\",\n";
    file << "    \"last_rejected\": \"" << g_dashboard.last_rejected_nq << "\",\n";
    file << "    \"signals_rejected\": " << g_dashboard.signals_rejected_nq << "\n";
    file << "  },\n";

    // Schedule
    file << "  \"schedule\": {\n";
    file << "    \"current_session\": \"" << g_dashboard.current_session << "\",\n";
    file << "    \"next_event\": \"" << g_dashboard.next_event << "\"\n";
    file << "  },\n";

    // Warnings
    file << "  \"warnings\": {\n";
    file << "    \"news_detected\": " << (g_dashboard.news_detected ? "true" : "false") << ",\n";
    file << "    \"news_message\": \"" << g_dashboard.news_message << "\"\n";
    file << "  },\n";

    // 🆕 Market Live Data
    file << "  \"market_live\": {\n";
    file << "    \"vix\": " << std::fixed << std::setprecision(2) << g_market_live.vix << ",\n";
    file << "    \"vix_regime\": \"" << GetVIXRegimeName(g_market_live.vix_regime) << "\",\n";
    file << "    \"vix_valid\": " << (g_market_live.vix_valid ? "true" : "false") << ",\n";
    file << "    \"atr_es\": " << g_market_live.atr_es << ",\n";
    file << "    \"atr_nq\": " << g_market_live.atr_nq << ",\n";
    file << "    \"atr_valid\": " << (g_market_live.atr_valid ? "true" : "false") << ",\n";
    file << "    \"vwap_slope_es\": " << std::setprecision(4) << g_market_live.vwap_slope_es << ",\n";
    file << "    \"vwap_slope_nq\": " << g_market_live.vwap_slope_nq << "\n";
    file << "  }\n";

    file << "}\n";
    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 SECTION 13A: BOTTLENECK REPORT (01/02/2026)
// Affiche visuellement où les signaux sont bloqués par Layer
// ═══════════════════════════════════════════════════════════════════════════════

inline void GetBottleneckReport(SCStudyInterfaceRef sc, bool is_nq = false) {
    int total, l1_rej, l2_rej, l3_veto, l3_rej, l4_rej, min_rej;
    
    if (is_nq) {
        total = g_dashboard.total_evals_nq;
        l1_rej = g_dashboard.l1_reject_nq;
        l2_rej = g_dashboard.l2_reject_nq;
        l3_veto = g_dashboard.l3_veto_nq;
        l3_rej = g_dashboard.l3_reject_nq;
        l4_rej = g_dashboard.l4_reject_nq;
        min_rej = g_dashboard.min_reject_nq;
    } else {
        total = g_dashboard.total_evals_es;
        l1_rej = g_dashboard.l1_reject_es;
        l2_rej = g_dashboard.l2_reject_es;
        l3_veto = g_dashboard.l3_veto_es;
        l3_rej = g_dashboard.l3_reject_es;
        l4_rej = g_dashboard.l4_reject_es;
        min_rej = g_dashboard.min_reject_es;
    }
    
    if (total == 0) {
        sc.AddMessageToLog(is_nq ? "[NQ] Aucune evaluation" : "[ES] Aucune evaluation", 0);
        return;
    }
    
    // Calcul des pourcentages
    float pct_l1 = (l1_rej * 100.0f) / total;
    float pct_l2 = (l2_rej * 100.0f) / total;
    float pct_l3v = (l3_veto * 100.0f) / total;
    float pct_l3 = (l3_rej * 100.0f) / total;
    float pct_l4 = (l4_rej * 100.0f) / total;
    float pct_min = (min_rej * 100.0f) / total;
    
    // Trouver le goulot (max %)
    const char* bottleneck = "?";
    float max_pct = 0;
    if (pct_l1 > max_pct) { max_pct = pct_l1; bottleneck = "L1"; }
    if (pct_l2 > max_pct) { max_pct = pct_l2; bottleneck = "L2"; }
    if (pct_l3v > max_pct) { max_pct = pct_l3v; bottleneck = "L3-VETO"; }
    if (pct_l3 > max_pct) { max_pct = pct_l3; bottleneck = "L3"; }
    if (pct_l4 > max_pct) { max_pct = pct_l4; bottleneck = "L4"; }
    if (pct_min > max_pct) { max_pct = pct_min; bottleneck = "MIN"; }
    
    // Affichage
    char msg[512];
    snprintf(msg, sizeof(msg), 
        "[%s DEBUG] %d evals | L1:%.0f%% L2:%.0f%% L3v:%.0f%% L3:%.0f%% L4:%.0f%% MIN:%.0f%% | GOULOT: %s (%.0f%%)",
        is_nq ? "NQ" : "ES", total,
        pct_l1, pct_l2, pct_l3v, pct_l3, pct_l4, pct_min,
        bottleneck, max_pct);
    
    sc.AddMessageToLog(msg, 0);
}

// Fonction pour réinitialiser les compteurs (à appeler en début de session)
inline void ResetBottleneckCounters() {
    g_dashboard.l1_reject_es = 0;
    g_dashboard.l2_reject_es = 0;
    g_dashboard.l3_veto_es = 0;
    g_dashboard.l3_reject_es = 0;
    g_dashboard.l4_reject_es = 0;
    g_dashboard.min_reject_es = 0;
    g_dashboard.total_evals_es = 0;
    
    g_dashboard.l1_reject_nq = 0;
    g_dashboard.l2_reject_nq = 0;
    g_dashboard.l3_veto_nq = 0;
    g_dashboard.l3_reject_nq = 0;
    g_dashboard.l4_reject_nq = 0;
    g_dashboard.min_reject_nq = 0;
    g_dashboard.total_evals_nq = 0;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 SECTION 13A-BIS: JOURNAL DE TRADES COMPLET (01/02/2026)
// Log POURQUOI chaque trade est pris ou rejeté - Analyse post-session
// Format: JSONL (une ligne JSON par décision)
// ═══════════════════════════════════════════════════════════════════════════════

struct TradeDecisionLog {
    // Identification
    char timestamp[32];
    char symbol[8];
    int direction;           // 1=LONG, -1=SHORT
    float price;
    
    // Layers results
    bool l1_passed;
    float l1_confidence;
    char l1_reason[64];
    
    bool l2_passed;
    float l2_confidence;
    char l2_reason[64];
    
    bool l3_passed;
    bool l3_veto;
    float l3_confidence;
    char l3_reason[64];
    
    bool l4_passed;
    char l4_grade;
    float l4_quality;
    char l4_reason[64];
    
    // Régime
    char regime[24];
    float regime_score;
    float size_mult;
    float tp_mult;
    bool trailing_allowed;
    
    // SLTP
    float sl_price;
    float tp_price;
    int sl_ticks;
    int tp_ticks;
    char tp_based_on[32];
    
    // Final decision
    bool trade_taken;
    char final_reason[128];
    int qty;
};

inline void LogTradeDecision(
    SCStudyInterfaceRef sc,
    const TradeDecisionLog& log
) {
    // Chemin du fichier journal - D:\TRADING_SIERRA_CHART_AUTO\LOGS
    SCDateTime now = sc.CurrentSystemDateTime;
    int year, month, day;
    now.GetDateYMD(year, month, day);
    
    char filepath[256];
    snprintf(filepath, sizeof(filepath),
             "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADE_JOURNAL\\%04d\\%02d\\trade_decisions_%04d%02d%02d.jsonl",
             year, month, year, month, day);
    
    // Créer les dossiers si nécessaire
    char dir0[128], dir1[128], dir2[128];
    snprintf(dir0, sizeof(dir0), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADE_JOURNAL");
    snprintf(dir1, sizeof(dir1), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADE_JOURNAL\\%04d", year);
    snprintf(dir2, sizeof(dir2), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\TRADE_JOURNAL\\%04d\\%02d", year, month);
    CreateDirectoryA(dir0, NULL);
    CreateDirectoryA(dir1, NULL);
    CreateDirectoryA(dir2, NULL);
    
    // Ouvrir en append
    std::ofstream file(filepath, std::ios::app);
    if (!file.is_open()) return;
    
    // Écrire une ligne JSON
    file << "{";
    file << "\"ts\":\"" << log.timestamp << "\",";
    file << "\"sym\":\"" << log.symbol << "\",";
    file << "\"dir\":" << log.direction << ",";
    file << "\"price\":" << std::fixed << std::setprecision(2) << log.price << ",";
    
    // Layers
    file << "\"l1\":{\"ok\":" << (log.l1_passed ? "true" : "false");
    file << ",\"conf\":" << std::setprecision(2) << log.l1_confidence;
    file << ",\"why\":\"" << log.l1_reason << "\"},";
    
    file << "\"l2\":{\"ok\":" << (log.l2_passed ? "true" : "false");
    file << ",\"conf\":" << std::setprecision(2) << log.l2_confidence;
    file << ",\"why\":\"" << log.l2_reason << "\"},";
    
    file << "\"l3\":{\"ok\":" << (log.l3_passed ? "true" : "false");
    file << ",\"veto\":" << (log.l3_veto ? "true" : "false");
    file << ",\"conf\":" << std::setprecision(2) << log.l3_confidence;
    file << ",\"why\":\"" << log.l3_reason << "\"},";
    
    file << "\"l4\":{\"ok\":" << (log.l4_passed ? "true" : "false");
    file << ",\"grade\":\"" << log.l4_grade << "\"";
    file << ",\"qual\":" << std::setprecision(1) << log.l4_quality;
    file << ",\"why\":\"" << log.l4_reason << "\"},";
    
    // Régime
    file << "\"regime\":{\"name\":\"" << log.regime << "\"";
    file << ",\"score\":" << std::setprecision(0) << log.regime_score;
    file << ",\"size_x\":" << std::setprecision(2) << log.size_mult;
    file << ",\"tp_x\":" << std::setprecision(2) << log.tp_mult;
    file << ",\"trail\":" << (log.trailing_allowed ? "true" : "false") << "},";
    
    // SLTP
    file << "\"sltp\":{\"sl\":" << std::setprecision(2) << log.sl_price;
    file << ",\"tp\":" << log.tp_price;
    file << ",\"sl_t\":" << log.sl_ticks;
    file << ",\"tp_t\":" << log.tp_ticks;
    file << ",\"based\":\"" << log.tp_based_on << "\"},";
    
    // Décision finale
    file << "\"taken\":" << (log.trade_taken ? "true" : "false") << ",";
    file << "\"reason\":\"" << log.final_reason << "\",";
    file << "\"qty\":" << log.qty;
    
    file << "}" << std::endl;
    file.close();
}

// Helper: Créer un log de décision rapidement
inline TradeDecisionLog CreateDecisionLog(
    SCStudyInterfaceRef sc,
    bool is_nq,
    int direction,
    float price
) {
    TradeDecisionLog log = {};
    
    // Timestamp
    SCDateTime now = sc.CurrentSystemDateTime;
    int year, month, day, hour, minute, second;
    now.GetDateYMD(year, month, day);
    now.GetTimeHMS(hour, minute, second);
    snprintf(log.timestamp, sizeof(log.timestamp), 
             "%04d-%02d-%02d %02d:%02d:%02d", year, month, day, hour, minute, second);
    
    // Symbol
    strncpy(log.symbol, is_nq ? "NQ" : "ES", sizeof(log.symbol));
    log.direction = direction;
    log.price = price;
    
    // Initialiser les raisons vides
    log.l1_reason[0] = '\0';
    log.l2_reason[0] = '\0';
    log.l3_reason[0] = '\0';
    log.l4_reason[0] = '\0';
    log.final_reason[0] = '\0';
    log.tp_based_on[0] = '\0';
    log.regime[0] = '\0';
    log.l4_grade = '-';
    
    return log;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 SECTION 13B: DIAGNOSTIC SNAPSHOT (27/01/2026)
// Exporte TOUTES les données que le bot voit pour validation
// ═══════════════════════════════════════════════════════════════════════════════

inline void WriteDiagnosticSnapshot(
    SCStudyInterfaceRef sc,
    const BN_Data& bn_es,
    const BN_Data& bn_nq,
    const MenthorQ_Data& mq_es,
    const MenthorQ_Data& mq_nq,
    float price_es,
    float price_nq
) {
    // Fichier unique avec timestamp
    std::string path = "D:\\MIA_IA_system\\DIAGNOSTIC_SNAPSHOT.json";
    std::ofstream file(path.c_str());
    if (!file.is_open()) return;

    file << std::fixed;
    file << "{\n";
    
    // === TIMESTAMP ===
    file << "  \"timestamp\": \"" << FormatTimestamp(sc.CurrentSystemDateTime) << "\",\n";
    file << "  \"session\": \"" << g_dashboard.current_session << "\",\n";
    file << "  \"status\": \"" << g_dashboard.global_status << "\",\n";
    
    // === MARKET LIVE ===
    file << "  \"market_live\": {\n";
    file << "    \"vix\": " << std::setprecision(2) << g_market_live.vix << ",\n";
    file << "    \"vix_regime\": \"" << GetVIXRegimeName(g_market_live.vix_regime) << "\",\n";
    file << "    \"vix_valid\": " << (g_market_live.vix_valid ? "true" : "false") << ",\n";
    file << "    \"atr_es\": " << g_market_live.atr_es << ",\n";
    file << "    \"atr_nq\": " << g_market_live.atr_nq << ",\n";
    file << "    \"atr_valid\": " << (g_market_live.atr_valid ? "true" : "false") << ",\n";
    file << "    \"vwap_slope_es\": " << std::setprecision(6) << g_market_live.vwap_slope_es << ",\n";
    file << "    \"vwap_slope_nq\": " << g_market_live.vwap_slope_nq << "\n";
    file << "  },\n";

    // === ES DATA ===
    file << "  \"ES\": {\n";
    file << "    \"price\": " << std::setprecision(2) << price_es << ",\n";
    file << "    \"enabled\": " << (g_es_state.enabled ? "true" : "false") << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_es << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_es << "\",\n";
    
    // MenthorQ ES
    file << "    \"menthorq\": {\n";
    file << "      \"vwap\": " << std::setprecision(2) << mq_es.vwap << ",\n";
    file << "      \"vwap_up1\": " << mq_es.vwap_up1 << ",\n";
    file << "      \"vwap_dn1\": " << mq_es.vwap_dn1 << ",\n";
    file << "      \"vwap_up2\": " << mq_es.vwap_up2 << ",\n";
    file << "      \"vwap_dn2\": " << mq_es.vwap_dn2 << ",\n";
    file << "      \"hvl\": " << mq_es.hvl << ",\n";
    file << "      \"hvl_0dte\": " << mq_es.hvl_0dte << ",\n";
    file << "      \"gamma_wall\": " << mq_es.gamma_wall << ",\n";
    file << "      \"gamma_wall_0dte\": " << mq_es.gamma_wall_0dte << ",\n";
    file << "      \"call_resistance\": " << mq_es.call_resistance << ",\n";
    file << "      \"call_resistance_0dte\": " << mq_es.call_resistance_0dte << ",\n";
    file << "      \"put_support\": " << mq_es.put_support << ",\n";
    file << "      \"put_support_0dte\": " << mq_es.put_support_0dte << ",\n";
    file << "      \"vah\": " << mq_es.vah << ",\n";
    file << "      \"val\": " << mq_es.val << ",\n";
    file << "      \"day_min\": " << mq_es.day_min << ",\n";
    file << "      \"day_max\": " << mq_es.day_max << ",\n";
    file << "      \"next_wall_price\": " << mq_es.next_wall_price << ",\n";
    file << "      \"next_wall_side\": " << mq_es.next_wall_side << "\n";
    file << "    },\n";
    
    // Battle Navale ES
    file << "    \"battle_navale\": {\n";
    file << "      \"score\": " << std::setprecision(4) << bn_es.score << ",\n";
    file << "      \"signal\": " << bn_es.signal << ",\n";
    file << "      \"momentum_score\": " << bn_es.momentum_score << ",\n";
    file << "      \"reversal_score\": " << bn_es.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << bn_es.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << bn_es.edge_buy << ",\n";
    file << "      \"edge_sell\": " << bn_es.edge_sell << ",\n";
    file << "      \"edge_ratio\": " << bn_es.edge_ratio << ",\n";
    file << "      \"edge_dominant_buy\": " << (bn_es.edge_dominant_buy ? "true" : "false") << ",\n";
    file << "      \"edge_dominant_sell\": " << (bn_es.edge_dominant_sell ? "true" : "false") << ",\n";
    file << "      \"color_up\": " << bn_es.color_up << ",\n";
    file << "      \"color_down\": " << bn_es.color_down << ",\n";
    file << "      \"absorb_ask\": " << bn_es.absorb_ask << ",\n";
    file << "      \"absorb_bid\": " << bn_es.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << bn_es.rotation_up << ",\n";
    file << "      \"rotation_down\": " << bn_es.rotation_down << ",\n";
    file << "      \"long_down_up\": " << bn_es.long_down_up << ",\n";
    file << "      \"long_up_down\": " << bn_es.long_up_down << ",\n";
    file << "      \"double_bid\": " << bn_es.double_bid << ",\n";
    file << "      \"double_ask\": " << bn_es.double_ask << ",\n";
    file << "      \"fresh_rectangle_buy\": " << (bn_es.fresh_rectangle_buy ? "true" : "false") << ",\n";
    file << "      \"fresh_rectangle_sell\": " << (bn_es.fresh_rectangle_sell ? "true" : "false") << ",\n";
    file << "      \"num_ext_support\": " << bn_es.num_ext_support << ",\n";
    file << "      \"num_ext_resist\": " << bn_es.num_ext_resist << ",\n";
    file << "      \"nearest_ext_support\": " << std::setprecision(2) << bn_es.nearest_ext_support << ",\n";
    file << "      \"nearest_ext_resist\": " << bn_es.nearest_ext_resist << ",\n";
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR)
    file << "      \"num_long_up_bar\": " << bn_es.num_long_up_bar << ",\n";
    file << "      \"num_long_down_bar\": " << bn_es.num_long_down_bar << ",\n";
    file << "      \"nearest_long_up_bar\": " << bn_es.nearest_long_up_bar << ",\n";
    file << "      \"nearest_long_down_bar\": " << bn_es.nearest_long_down_bar << ",\n";
    file << "      \"has_tradable_support\": " << (bn_es.has_tradable_support ? "true" : "false") << ",\n";
    file << "      \"has_tradable_resist\": " << (bn_es.has_tradable_resist ? "true" : "false") << ",\n";
    file << "      \"num_edge_rect_buy\": " << bn_es.num_edge_rect_buy << ",\n";
    file << "      \"num_edge_rect_sell\": " << bn_es.num_edge_rect_sell << ",\n";
    file << "      \"nearest_edge_rect_support\": " << bn_es.nearest_edge_rect_support << ",\n";
    file << "      \"nearest_edge_rect_resist\": " << bn_es.nearest_edge_rect_resist << ",\n";
    file << "      \"price_in_edge_rect_buy\": " << (bn_es.price_in_edge_rect_buy ? "true" : "false") << ",\n";
    file << "      \"price_in_edge_rect_sell\": " << (bn_es.price_in_edge_rect_sell ? "true" : "false") << ",\n";
    file << "      \"bn_attack_long_valid\": " << (bn_es.bn_attack_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_attack_short_valid\": " << (bn_es.bn_attack_short_valid ? "true" : "false") << ",\n";
    // 🆕 30/01/2026: Règle subtile avec boules
    file << "      \"bn_subtile_long_valid\": " << (bn_es.bn_subtile_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_subtile_short_valid\": " << (bn_es.bn_subtile_short_valid ? "true" : "false") << ",\n";
    file << "      \"green_base_price\": " << std::setprecision(2) << std::fixed << bn_es.green_base_price << ",\n";
    file << "      \"red_base_price\": " << std::setprecision(2) << std::fixed << bn_es.red_base_price << ",\n";
    file << "      \"num_color_up_prices\": " << bn_es.num_color_up_prices << ",\n";
    file << "      \"num_color_down_prices\": " << bn_es.num_color_down_prices << ",\n";
    // 🆕 30/01/2026: Mode RANGE
    file << "      \"is_range\": " << (bn_es.is_range ? "true" : "false") << ",\n";
    file << "      \"range_support\": " << std::setprecision(2) << std::fixed << bn_es.range_support << ",\n";
    file << "      \"range_resistance\": " << std::setprecision(2) << std::fixed << bn_es.range_resistance << ",\n";
    file << "      \"range_size_pts\": " << std::setprecision(1) << std::fixed << bn_es.range_size_pts << ",\n";
    file << "      \"price_position_pct\": " << std::setprecision(1) << std::fixed << bn_es.price_position_pct << ",\n";
    file << "      \"price_position\": " << bn_es.price_position << ",\n";
    file << "      \"directional_coherence\": " << std::setprecision(4) << bn_es.directional_coherence << "\n";
    file << "    },\n";
    
    // Extension Lines ES
    file << "    \"extension_lines\": {\n";
    file << "      \"supports\": [";
    for (int i = 0; i < bn_es.num_ext_support && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.ext_lines_support[i];
    }
    file << "],\n";
    file << "      \"resistances\": [";
    for (int i = 0; i < bn_es.num_ext_resist && i < 10; i++) {
        if (i > 0) file << ", ";
        file << bn_es.ext_lines_resist[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // Edge Rectangles ES
    file << "    \"edge_rectangles\": {\n";
    file << "      \"buy_zones\": [";
    for (int i = 0; i < bn_es.num_edge_rect_buy && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_es.edge_rect_buy_bottom[i] << ", \"top\": " << bn_es.edge_rect_buy_top[i] << "}";
    }
    file << "],\n";
    file << "      \"sell_zones\": [";
    for (int i = 0; i < bn_es.num_edge_rect_sell && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_es.edge_rect_sell_bottom[i] << ", \"top\": " << bn_es.edge_rect_sell_top[i] << "}";
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 Rectangles Tradables ES (LONG UP/DOWN BAR - séparés des boules)
    file << "    \"tradable_rectangles\": {\n";
    file << "      \"green_supports\": [";
    for (int i = 0; i < bn_es.num_long_up_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.long_up_bar_ext[i];
    }
    file << "],\n";
    file << "      \"red_resistances\": [";
    for (int i = 0; i < bn_es.num_long_down_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_es.long_down_bar_ext[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 FPBS AVANCÉ ES (Delta, CVD, POC)
    file << "    \"fpbs\": {\n";
    file << "      \"delta\": " << std::setprecision(0) << bn_es.fpbs_delta << ",\n";
    file << "      \"delta_day\": " << bn_es.fpbs_delta_day << ",\n";
    file << "      \"cvd\": " << bn_es.fpbs_cvd << ",\n";
    file << "      \"poc\": " << std::setprecision(2) << bn_es.fpbs_poc << ",\n";
    file << "      \"ask_pct\": " << std::setprecision(1) << bn_es.fpbs_ask_pct << ",\n";
    file << "      \"bid_pct\": " << bn_es.fpbs_bid_pct << "\n";
    file << "    },\n";
    
    // 🆕 CVD & POC ANALYSIS ES
    file << "    \"cvd_poc_analysis\": {\n";
    file << "      \"current_cvd\": " << std::setprecision(0) << bn_es.fpbs_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"prev_cvd\": " << std::setprecision(0) << bn_es.prev_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"cvd_slope\": " << std::setprecision(0) << bn_es.cvd_slope << ",\n";
    file << "      \"cvd_trend_score\": " << std::setprecision(2) << bn_es.cvd_trend_score << ",\n";
    file << "      \"cvd_divergence\": " << (bn_es.cvd_divergence ? "true" : "false") << ",\n";
    file << "      \"poc_confirm\": " << bn_es.poc_confirm << ",\n";
    file << "      \"poc_confirm_text\": \"" << (bn_es.poc_confirm == 1 ? "BULLISH" : (bn_es.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "    },\n";
    
    // 🆕 ORDRES INSTITUTIONNELS ES
    file << "    \"institutional_orders\": {\n";
    file << "      \"ask_100\": " << std::setprecision(0) << bn_es.ask_100 << ",\n";
    file << "      \"bid_100\": " << bn_es.bid_100 << ",\n";
    file << "      \"ask_150\": " << bn_es.ask_150 << ",\n";
    file << "      \"bid_150\": " << bn_es.bid_150 << ",\n";
    file << "      \"ask_400\": " << bn_es.ask_400 << ",\n";
    file << "      \"bid_400\": " << bn_es.bid_400 << ",\n";
    file << "      \"ask_1000\": " << bn_es.ask_1000 << ",\n";
    file << "      \"bid_1000\": " << bn_es.bid_1000 << ",\n";
    file << "      \"cluster_vol\": " << bn_es.cluster_vol << "\n";
    file << "    }\n";
    file << "  },\n";

    // === NQ DATA ===
    file << "  \"NQ\": {\n";
    file << "    \"price\": " << std::setprecision(2) << price_nq << ",\n";
    file << "    \"enabled\": " << (g_nq_state.enabled ? "true" : "false") << ",\n";
    file << "    \"bot_action\": \"" << g_dashboard.bot_action_nq << "\",\n";
    file << "    \"no_trade_reason\": \"" << g_dashboard.no_trade_reason_nq << "\",\n";
    
    // MenthorQ NQ
    file << "    \"menthorq\": {\n";
    file << "      \"vwap\": " << std::setprecision(2) << mq_nq.vwap << ",\n";
    file << "      \"vwap_up1\": " << mq_nq.vwap_up1 << ",\n";
    file << "      \"vwap_dn1\": " << mq_nq.vwap_dn1 << ",\n";
    file << "      \"vwap_up2\": " << mq_nq.vwap_up2 << ",\n";
    file << "      \"vwap_dn2\": " << mq_nq.vwap_dn2 << ",\n";
    file << "      \"hvl\": " << mq_nq.hvl << ",\n";
    file << "      \"hvl_0dte\": " << mq_nq.hvl_0dte << ",\n";
    file << "      \"gamma_wall\": " << mq_nq.gamma_wall << ",\n";
    file << "      \"gamma_wall_0dte\": " << mq_nq.gamma_wall_0dte << ",\n";
    file << "      \"call_resistance\": " << mq_nq.call_resistance << ",\n";
    file << "      \"call_resistance_0dte\": " << mq_nq.call_resistance_0dte << ",\n";
    file << "      \"put_support\": " << mq_nq.put_support << ",\n";
    file << "      \"put_support_0dte\": " << mq_nq.put_support_0dte << ",\n";
    file << "      \"vah\": " << mq_nq.vah << ",\n";
    file << "      \"val\": " << mq_nq.val << ",\n";
    file << "      \"day_min\": " << mq_nq.day_min << ",\n";
    file << "      \"day_max\": " << mq_nq.day_max << ",\n";
    file << "      \"next_wall_price\": " << mq_nq.next_wall_price << ",\n";
    file << "      \"next_wall_side\": " << mq_nq.next_wall_side << "\n";
    file << "    },\n";
    
    // Battle Navale NQ
    file << "    \"battle_navale\": {\n";
    file << "      \"score\": " << std::setprecision(4) << bn_nq.score << ",\n";
    file << "      \"signal\": " << bn_nq.signal << ",\n";
    file << "      \"momentum_score\": " << bn_nq.momentum_score << ",\n";
    file << "      \"reversal_score\": " << bn_nq.reversal_score << ",\n";
    file << "      \"institutional_pressure\": " << bn_nq.institutional_pressure << ",\n";
    file << "      \"edge_buy\": " << bn_nq.edge_buy << ",\n";
    file << "      \"edge_sell\": " << bn_nq.edge_sell << ",\n";
    file << "      \"edge_ratio\": " << bn_nq.edge_ratio << ",\n";
    file << "      \"edge_dominant_buy\": " << (bn_nq.edge_dominant_buy ? "true" : "false") << ",\n";
    file << "      \"edge_dominant_sell\": " << (bn_nq.edge_dominant_sell ? "true" : "false") << ",\n";
    file << "      \"color_up\": " << bn_nq.color_up << ",\n";
    file << "      \"color_down\": " << bn_nq.color_down << ",\n";
    file << "      \"absorb_ask\": " << bn_nq.absorb_ask << ",\n";
    file << "      \"absorb_bid\": " << bn_nq.absorb_bid << ",\n";
    file << "      \"rotation_up\": " << bn_nq.rotation_up << ",\n";
    file << "      \"rotation_down\": " << bn_nq.rotation_down << ",\n";
    file << "      \"long_down_up\": " << bn_nq.long_down_up << ",\n";
    file << "      \"long_up_down\": " << bn_nq.long_up_down << ",\n";
    file << "      \"triple_bid\": " << bn_nq.triple_bid << ",\n";
    file << "      \"triple_ask\": " << bn_nq.triple_ask << ",\n";
    file << "      \"fresh_rectangle_buy\": " << (bn_nq.fresh_rectangle_buy ? "true" : "false") << ",\n";
    file << "      \"fresh_rectangle_sell\": " << (bn_nq.fresh_rectangle_sell ? "true" : "false") << ",\n";
    file << "      \"num_ext_support\": " << bn_nq.num_ext_support << ",\n";
    file << "      \"num_ext_resist\": " << bn_nq.num_ext_resist << ",\n";
    file << "      \"nearest_ext_support\": " << std::setprecision(2) << bn_nq.nearest_ext_support << ",\n";
    file << "      \"nearest_ext_resist\": " << bn_nq.nearest_ext_resist << ",\n";
    // 🆕 RECTANGLES TRADABLES (LONG UP/DOWN BAR)
    file << "      \"num_long_up_bar\": " << bn_nq.num_long_up_bar << ",\n";
    file << "      \"num_long_down_bar\": " << bn_nq.num_long_down_bar << ",\n";
    file << "      \"nearest_long_up_bar\": " << bn_nq.nearest_long_up_bar << ",\n";
    file << "      \"nearest_long_down_bar\": " << bn_nq.nearest_long_down_bar << ",\n";
    file << "      \"has_tradable_support\": " << (bn_nq.has_tradable_support ? "true" : "false") << ",\n";
    file << "      \"has_tradable_resist\": " << (bn_nq.has_tradable_resist ? "true" : "false") << ",\n";
    file << "      \"num_edge_rect_buy\": " << bn_nq.num_edge_rect_buy << ",\n";
    file << "      \"num_edge_rect_sell\": " << bn_nq.num_edge_rect_sell << ",\n";
    file << "      \"nearest_edge_rect_support\": " << bn_nq.nearest_edge_rect_support << ",\n";
    file << "      \"nearest_edge_rect_resist\": " << bn_nq.nearest_edge_rect_resist << ",\n";
    file << "      \"price_in_edge_rect_buy\": " << (bn_nq.price_in_edge_rect_buy ? "true" : "false") << ",\n";
    file << "      \"price_in_edge_rect_sell\": " << (bn_nq.price_in_edge_rect_sell ? "true" : "false") << ",\n";
    file << "      \"bn_attack_long_valid\": " << (bn_nq.bn_attack_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_attack_short_valid\": " << (bn_nq.bn_attack_short_valid ? "true" : "false") << ",\n";
    // 🆕 30/01/2026: Règle subtile avec boules
    file << "      \"bn_subtile_long_valid\": " << (bn_nq.bn_subtile_long_valid ? "true" : "false") << ",\n";
    file << "      \"bn_subtile_short_valid\": " << (bn_nq.bn_subtile_short_valid ? "true" : "false") << ",\n";
    file << "      \"green_base_price\": " << std::setprecision(2) << std::fixed << bn_nq.green_base_price << ",\n";
    file << "      \"red_base_price\": " << std::setprecision(2) << std::fixed << bn_nq.red_base_price << ",\n";
    file << "      \"num_color_up_prices\": " << bn_nq.num_color_up_prices << ",\n";
    file << "      \"num_color_down_prices\": " << bn_nq.num_color_down_prices << ",\n";
    // 🆕 30/01/2026: Mode RANGE
    file << "      \"is_range\": " << (bn_nq.is_range ? "true" : "false") << ",\n";
    file << "      \"range_support\": " << std::setprecision(2) << std::fixed << bn_nq.range_support << ",\n";
    file << "      \"range_resistance\": " << std::setprecision(2) << std::fixed << bn_nq.range_resistance << ",\n";
    file << "      \"range_size_pts\": " << std::setprecision(1) << std::fixed << bn_nq.range_size_pts << ",\n";
    file << "      \"price_position_pct\": " << std::setprecision(1) << std::fixed << bn_nq.price_position_pct << ",\n";
    file << "      \"price_position\": " << bn_nq.price_position << ",\n";
    file << "      \"directional_coherence\": " << std::setprecision(4) << bn_nq.directional_coherence << "\n";
    file << "    },\n";
    
    // Extension Lines NQ
    file << "    \"extension_lines\": {\n";
    file << "      \"supports\": [";
    for (int i = 0; i < bn_nq.num_ext_support && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.ext_lines_support[i];
    }
    file << "],\n";
    file << "      \"resistances\": [";
    for (int i = 0; i < bn_nq.num_ext_resist && i < 10; i++) {
        if (i > 0) file << ", ";
        file << bn_nq.ext_lines_resist[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // Edge Rectangles NQ
    file << "    \"edge_rectangles\": {\n";
    file << "      \"buy_zones\": [";
    for (int i = 0; i < bn_nq.num_edge_rect_buy && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_nq.edge_rect_buy_bottom[i] << ", \"top\": " << bn_nq.edge_rect_buy_top[i] << "}";
    }
    file << "],\n";
    file << "      \"sell_zones\": [";
    for (int i = 0; i < bn_nq.num_edge_rect_sell && i < 5; i++) {
        if (i > 0) file << ", ";
        file << "{\"bottom\": " << bn_nq.edge_rect_sell_bottom[i] << ", \"top\": " << bn_nq.edge_rect_sell_top[i] << "}";
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 Rectangles Tradables NQ (LONG UP/DOWN BAR - séparés des boules)
    file << "    \"tradable_rectangles\": {\n";
    file << "      \"green_supports\": [";
    for (int i = 0; i < bn_nq.num_long_up_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.long_up_bar_ext[i];
    }
    file << "],\n";
    file << "      \"red_resistances\": [";
    for (int i = 0; i < bn_nq.num_long_down_bar && i < 10; i++) {
        if (i > 0) file << ", ";
        file << std::setprecision(2) << bn_nq.long_down_bar_ext[i];
    }
    file << "]\n";
    file << "    },\n";
    
    // 🆕 FPBS AVANCÉ NQ (Delta, CVD, POC)
    file << "    \"fpbs\": {\n";
    file << "      \"delta\": " << std::setprecision(0) << bn_nq.fpbs_delta << ",\n";
    file << "      \"delta_day\": " << bn_nq.fpbs_delta_day << ",\n";
    file << "      \"cvd\": " << bn_nq.fpbs_cvd << ",\n";
    file << "      \"poc\": " << std::setprecision(2) << bn_nq.fpbs_poc << ",\n";
    file << "      \"ask_pct\": " << std::setprecision(1) << bn_nq.fpbs_ask_pct << ",\n";
    file << "      \"bid_pct\": " << bn_nq.fpbs_bid_pct << "\n";
    file << "    },\n";
    
    // 🆕 CVD & POC ANALYSIS NQ
    file << "    \"cvd_poc_analysis\": {\n";
    file << "      \"current_cvd\": " << std::setprecision(0) << bn_nq.fpbs_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"prev_cvd\": " << std::setprecision(0) << bn_nq.prev_cvd << ",\n";  // 🔧 DEBUG
    file << "      \"cvd_slope\": " << std::setprecision(0) << bn_nq.cvd_slope << ",\n";
    file << "      \"cvd_trend_score\": " << std::setprecision(2) << bn_nq.cvd_trend_score << ",\n";
    file << "      \"cvd_divergence\": " << (bn_nq.cvd_divergence ? "true" : "false") << ",\n";
    file << "      \"poc_confirm\": " << bn_nq.poc_confirm << ",\n";
    file << "      \"poc_confirm_text\": \"" << (bn_nq.poc_confirm == 1 ? "BULLISH" : (bn_nq.poc_confirm == -1 ? "BEARISH" : "NEUTRAL")) << "\"\n";
    file << "    },\n";
    
    // 🆕 ORDRES INSTITUTIONNELS NQ (granularité +10, +30, +100)
    file << "    \"institutional_orders\": {\n";
    file << "      \"ask_10\": " << std::setprecision(0) << bn_nq.ask_10 << ",\n";
    file << "      \"bid_10\": " << bn_nq.bid_10 << ",\n";
    file << "      \"ask_30\": " << bn_nq.ask_30 << ",\n";
    file << "      \"bid_30\": " << bn_nq.bid_30 << ",\n";
    file << "      \"ask_100\": " << bn_nq.ask_100 << ",\n";
    file << "      \"bid_100\": " << bn_nq.bid_100 << ",\n";
    file << "      \"triple_ask\": " << bn_nq.triple_ask << ",\n";
    file << "      \"triple_bid\": " << bn_nq.triple_bid << ",\n";
    file << "      \"cluster_vol\": " << bn_nq.cluster_vol << "\n";
    file << "    }\n";
    file << "  }\n";

    file << "}\n";
    file.close();
}



// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: DASHBOARD JSON TEMPS RÉEL
// ═══════════════════════════════════════════════════════════════════════════════
// Écrit un dashboard JSON temps réel pour monitoring externe
// À appeler toutes les 5 secondes depuis MIA_Main.cpp

inline void WriteDashboardJSON(
    SCStudyInterfaceRef sc,
    const BotState& es_state,
    const BotState& nq_state,
    const DashboardData& dashboard
) {
    const char* filepath = "D:\\LOGS\\MIA\\dashboard_realtime.json";
    
    std::ofstream file(filepath);
    if (!file.is_open()) return;
    
    file << std::fixed << std::setprecision(2);
    
    file << "{\n";
    
    // 🆕 Header versionné
    file << "  \"_schema\": {\n";
    file << "    \"version\": \"" << MIA_SCHEMA_VERSION << "\",\n";
    file << "    \"type\": \"dashboard\",\n";
    file << "    \"build\": \"" << MIA_BUILD_REFACTORED << "\",\n";
    file << "    \"generated_at\": \"" << FormatTimestamp(sc.CurrentSystemDateTime) << "\"\n";
    file << "  },\n";
    
    // Bot Status
    file << "  \"bot_status\": {\n";
    file << "    \"running\": " << (dashboard.bot_running ? "true" : "false") << ",\n";
    file << "    \"last_heartbeat\": \"" << FormatTimestamp(dashboard.last_heartbeat) << "\",\n";
    file << "    \"session\": \"" << GetCurrentSessionName(sc) << "\",\n";
    file << "    \"in_session\": " << (IsWithinTradingSession(sc) ? "true" : "false") << "\n";
    file << "  },\n";
    
    // ES State
    file << "  \"es\": {\n";
    file << "    \"enabled\": " << (es_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (es_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (es_state.in_position ? "true" : "false") << ",\n";
    file << "    \"direction\": \"" << (es_state.direction == 1 ? "LONG" : (es_state.direction == -1 ? "SHORT" : "FLAT")) << "\",\n";
    file << "    \"entry_price\": " << es_state.entry_price << ",\n";
    file << "    \"sl_price\": " << es_state.sl_price << ",\n";
    file << "    \"tp_price\": " << es_state.tp_price << ",\n";
    file << "    \"waiting_for\": \"" << es_state.waiting_for << "\",\n";
    file << "    \"last_reject_reason\": \"" << es_state.last_reject_reason << "\",\n";
    file << "    \"trades_today\": " << es_state.trades_today << ",\n";
    file << "    \"wins_today\": " << es_state.wins_today << ",\n";
    file << "    \"losses_today\": " << es_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << es_state.pnl_today << ",\n";
    file << "    \"winrate\": " << (es_state.trades_today > 0 ? (es_state.wins_today * 100.0f / es_state.trades_today) : 0.0f) << ",\n";
    file << "    \"best_trade\": " << es_state.best_trade << ",\n";
    file << "    \"worst_trade\": " << es_state.worst_trade << ",\n";
    file << "    \"consecutive_losses\": " << es_state.consecutive_losses << ",\n";
    file << "    \"last_trade_time\": \"" << FormatTimestamp(es_state.last_trade_time) << "\"\n";
    file << "  },\n";
    
    // NQ State
    file << "  \"nq\": {\n";
    file << "    \"enabled\": " << (nq_state.enabled ? "true" : "false") << ",\n";
    file << "    \"paused\": " << (nq_state.paused ? "true" : "false") << ",\n";
    file << "    \"in_position\": " << (nq_state.in_position ? "true" : "false") << ",\n";
    file << "    \"direction\": \"" << (nq_state.direction == 1 ? "LONG" : (nq_state.direction == -1 ? "SHORT" : "FLAT")) << "\",\n";
    file << "    \"entry_price\": " << nq_state.entry_price << ",\n";
    file << "    \"sl_price\": " << nq_state.sl_price << ",\n";
    file << "    \"tp_price\": " << nq_state.tp_price << ",\n";
    file << "    \"waiting_for\": \"" << nq_state.waiting_for << "\",\n";
    file << "    \"last_reject_reason\": \"" << nq_state.last_reject_reason << "\",\n";
    file << "    \"trades_today\": " << nq_state.trades_today << ",\n";
    file << "    \"wins_today\": " << nq_state.wins_today << ",\n";
    file << "    \"losses_today\": " << nq_state.losses_today << ",\n";
    file << "    \"pnl_today\": " << nq_state.pnl_today << ",\n";
    file << "    \"winrate\": " << (nq_state.trades_today > 0 ? (nq_state.wins_today * 100.0f / nq_state.trades_today) : 0.0f) << ",\n";
    file << "    \"best_trade\": " << nq_state.best_trade << ",\n";
    file << "    \"worst_trade\": " << nq_state.worst_trade << ",\n";
    file << "    \"consecutive_losses\": " << nq_state.consecutive_losses << ",\n";
    file << "    \"last_trade_time\": \"" << FormatTimestamp(nq_state.last_trade_time) << "\"\n";
    file << "  },\n";
    
    // Global Stats
    file << "  \"stats\": {\n";
    file << "    \"total_trades_today\": " << (es_state.trades_today + nq_state.trades_today) << ",\n";
    file << "    \"total_wins_today\": " << (es_state.wins_today + nq_state.wins_today) << ",\n";
    file << "    \"total_pnl_today\": " << (es_state.pnl_today + nq_state.pnl_today) << ",\n";
    file << "    \"signals_rejected_es\": " << dashboard.signals_rejected_es << ",\n";
    file << "    \"signals_rejected_nq\": " << dashboard.signals_rejected_nq << ",\n";
    file << "    \"global_winrate\": " << ((es_state.trades_today + nq_state.trades_today) > 0 ? 
                                           ((es_state.wins_today + nq_state.wins_today) * 100.0f / (es_state.trades_today + nq_state.trades_today)) : 0.0f) << "\n";
    file << "  }\n";
    
    file << "}\n";

    file.close();
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 13.5: BOT DECISION LOGS (Option A) - DEBUGGING 100% REJETS
// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: Système de logs pour comprendre POURQUOI les trades sont rejetés
// Fichier: D:\LOGS\MIA\bot_decisions_YYYYMMDD.jsonl (1 ligne JSON par décision)
// ═══════════════════════════════════════════════════════════════════════════════

// Structure pour capturer l'état de chaque Layer au moment de la décision
struct LayerDecision {
    bool passed;
    float confidence;
    float score;
    char level_name[32];
    char reason[128];
    
    LayerDecision() : passed(false), confidence(0.0f), score(0.0f) {
        level_name[0] = '\0';
        reason[0] = '\0';
    }
};

struct BotDecisionLog {
    long long timestamp_ms;
    char symbol[16];
    char action[32];         // SCAN, L1_EVAL, L1_PASS, L1_REJECT, L2_PASS, L2_REJECT, L3_PASS, L3_REJECT, L4_PASS, L4_REJECT, ORDER_SENT
    float current_price;
    
    // Layers
    LayerDecision l1;
    LayerDecision l2;
    LayerDecision l3;
    LayerDecision l4;
    
    // Context critique
    float hvl_price;
    float hvl_distance_ticks;
    float gamma_wall;
    float vwap;
    float vwap_slope;
    float bn_score;
    int bn_signal;
    float cvd;
    float delta;
    
    // Correlation ES/NQ
    char correlation[16];    // ALIGNED, DIVERGENT, UNKNOWN
    
    BotDecisionLog() : timestamp_ms(0), current_price(0.0f), hvl_price(0.0f),
                       hvl_distance_ticks(0.0f), gamma_wall(0.0f), vwap(0.0f),
                       vwap_slope(0.0f), bn_score(0.0f), bn_signal(0), cvd(0.0f), delta(0.0f) {
        symbol[0] = '\0';
        action[0] = '\0';
        correlation[0] = '\0';
    }
};

inline void LogBotDecision(
    SCStudyInterfaceRef sc,
    const BotDecisionLog& log
) {
    // Créer chemin avec date
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "D:\\LOGS\\MIA\\bot_decisions_%04d%02d%02d.jsonl",
        year, month, day
    );
    
    // Assurer le répertoire existe
    CreateDirectoryA("D:\\LOGS", NULL);
    CreateDirectoryA("D:\\LOGS\\MIA", NULL);
    
    FILE* f = fopen(filepath, "a");
    if (!f) return;
    
    // JSON compact (1 ligne) - Ultra-détaillé pour debugging
    fprintf(f, "{\"t_ms\":%lld,\"sym\":\"%s\",\"action\":\"%s\",\"price\":%.2f,"
               "\"l1\":{\"passed\":%s,\"conf\":%.2f,\"score\":%.2f,\"level\":\"%s\",\"reason\":\"%s\"},"
               "\"l2\":{\"passed\":%s,\"conf\":%.2f,\"score\":%.4f,\"reason\":\"%s\"},"
               "\"l3\":{\"passed\":%s,\"conf\":%.2f,\"reason\":\"%s\"},"
               "\"l4\":{\"passed\":%s,\"conf\":%.2f,\"reason\":\"%s\"},"
               "\"ctx\":{\"hvl\":%.2f,\"hvl_dist\":%.1f,\"gamma\":%.2f,\"vwap\":%.2f,\"vwap_slope\":%.4f,"
               "\"bn_score\":%.4f,\"bn_signal\":%d,\"cvd\":%.0f,\"delta\":%.0f,\"corr\":\"%s\"}}\n",
            log.timestamp_ms,
            log.symbol,
            log.action,
            log.current_price,
            // L1
            log.l1.passed ? "true" : "false", log.l1.confidence, log.l1.score, log.l1.level_name, log.l1.reason,
            // L2
            log.l2.passed ? "true" : "false", log.l2.confidence, log.l2.score, log.l2.reason,
            // L3
            log.l3.passed ? "true" : "false", log.l3.confidence, log.l3.reason,
            // L4
            log.l4.passed ? "true" : "false", log.l4.confidence, log.l4.reason,
            // Context
            log.hvl_price, log.hvl_distance_ticks, log.gamma_wall, log.vwap, log.vwap_slope,
            log.bn_score, log.bn_signal, log.cvd, log.delta, log.correlation
    );
    
    fclose(f);
}

// Helper simplifié pour logs rapides
inline void LogBotDecisionSimple(
    SCStudyInterfaceRef sc,
    const char* symbol,
    const char* action,
    const char* reason,
    float price = 0.0f,
    float score = 0.0f
) {
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "D:\\LOGS\\MIA\\bot_decisions_%04d%02d%02d.jsonl",
        year, month, day
    );
    
    CreateDirectoryA("D:\\LOGS", NULL);
    CreateDirectoryA("D:\\LOGS\\MIA", NULL);
    
    FILE* f = fopen(filepath, "a");
    if (!f) return;
    
    long long t_ms = (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    
    fprintf(f, "{\"t_ms\":%lld,\"sym\":\"%s\",\"action\":\"%s\",\"reason\":\"%s\",\"price\":%.2f,\"score\":%.4f}\n",
            t_ms, symbol, action, reason, price, score);
    
    fclose(f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 13.6: BOT SNAPSHOT COMPLET (Option B) - COMME LE DUMPER
// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: Snapshot complet avec TOUTES les données (BN, MQ, Layers, State)
// Structure: D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_CPP\YYYY\MM\YYYYMMDD\bot_snapshot_YYYYMMDD.jsonl
// ═══════════════════════════════════════════════════════════════════════════════

inline void DumpBotSnapshot(
    SCStudyInterfaceRef sc,
    bool is_nq,
    const BN_Data& bn_primary,       // ES ou NQ selon is_nq
    const BN_Data& bn_secondary,     // L'autre (pour corrélation)
    const MenthorQ_Data& mq_primary,
    const MenthorQ_Data& mq_secondary,
    const BotState& state,
    const char* action,
    const char* reject_reason = ""
) {
    // Créer chemin avec structure date - DANS TRADING_SIERRA_CHART_AUTO
    int year, month, day, hour, minute, second;
    sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    
    char dir_path[512];
    snprintf(dir_path, sizeof(dir_path),
        "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\BOT_SNAPSHOTS\\%04d\\%02d\\%04d%02d%02d",
        year, month, year, month, day
    );
    
    // Créer répertoires
    char tmp[512];
    CreateDirectoryA("D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\BOT_SNAPSHOTS", NULL);
    snprintf(tmp, sizeof(tmp), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\BOT_SNAPSHOTS\\%04d", year);
    CreateDirectoryA(tmp, NULL);
    snprintf(tmp, sizeof(tmp), "D:\\TRADING_SIERRA_CHART_AUTO\\LOGS\\BOT_SNAPSHOTS\\%04d\\%02d", year, month);
    CreateDirectoryA(tmp, NULL);
    CreateDirectoryA(dir_path, NULL);
    
    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "%s\\bot_snapshot_%04d%02d%02d.jsonl",
        dir_path, year, month, day
    );
    
    FILE* f = fopen(filepath, "a");
    if (!f) return;
    
    long long t_ms = (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    const char* sym = is_nq ? "NQ" : "ES";
    float price = (float)sc.Close[sc.ArraySize - 1];
    
    // ═══════════════════════════════════════════════════════════════════════════════
    // 🆕 01/02/2026: SNAPSHOT ULTRA COMPLET - TOUTES LES DONNÉES DISPONIBLES
    // Format: JSONL avec toutes les features pour backtest/ML
    // ═══════════════════════════════════════════════════════════════════════════════
    
    fprintf(f, "{\"_schema\":{\"v\":\"%s\",\"type\":\"bot_snapshot_v3_full\"},"
               "\"t_ms\":%lld,\"ts\":\"%04d-%02d-%02d %02d:%02d:%02d\",\"sym\":\"%s\",\"price\":%.2f,"
               "\"action\":\"%s\",\"reject\":\"%s\",",
            MIA_SCHEMA_VERSION,
            t_ms, year, month, day, hour, minute, second, sym, price,
            action, reject_reason);
    
    // ═══ MARKET CONTEXT ═══
    fprintf(f, "\"market\":{\"vix\":%.2f,\"vix_regime\":%d,\"vix_valid\":%s,"
               "\"atr_es\":%.2f,\"atr_nq\":%.2f,\"atr_valid\":%s,"
               "\"vwap_slope_es\":%.6f,\"vwap_slope_nq\":%.6f,\"session\":\"%s\"},",
            g_market_live.vix, g_market_live.vix_regime, g_market_live.vix_valid ? "true" : "false",
            g_market_live.atr_es, g_market_live.atr_nq, g_market_live.atr_valid ? "true" : "false",
            g_market_live.vwap_slope_es, g_market_live.vwap_slope_nq, g_dashboard.current_session);
    
    // ═══ BATAILLE NAVALE PRIMARY - COMPLET ═══
    fprintf(f, "\"bn\":{"
               // Signaux footprint
               "\"score\":%.4f,\"signal\":%d,\"momentum\":%.4f,\"reversal\":%.4f,"
               "\"edge_buy\":%.0f,\"edge_sell\":%.0f,\"color_up\":%.0f,\"color_down\":%.0f,"
               "\"absorb_ask\":%.0f,\"absorb_bid\":%.0f,\"double_ask\":%.0f,\"double_bid\":%.0f,"
               "\"triple_ask\":%.0f,\"triple_bid\":%.0f,"
               "\"rotation_up\":%.0f,\"rotation_down\":%.0f,\"volume_up\":%.0f,\"volume_down\":%.0f,"
               // Gros ordres
               "\"ask_10\":%.0f,\"bid_10\":%.0f,\"ask_30\":%.0f,\"bid_30\":%.0f,"
               "\"ask_100\":%.0f,\"bid_100\":%.0f,\"ask_150\":%.0f,\"bid_150\":%.0f,"
               "\"ask_400\":%.0f,\"bid_400\":%.0f,\"ask_1000\":%.0f,\"bid_1000\":%.0f,"
               "\"cluster_vol\":%.0f,"
               // Signaux barres
               "\"long_down_up\":%.0f,\"long_up_down\":%.0f,"
               "\"bar_color_up\":%.0f,\"bar_color_down\":%.0f,"
               "\"bar_edge_buy\":%.0f,\"bar_edge_sell\":%.0f,",
            bn_primary.score, bn_primary.signal, bn_primary.momentum_score, bn_primary.reversal_score,
            bn_primary.edge_buy, bn_primary.edge_sell, bn_primary.color_up, bn_primary.color_down,
            bn_primary.absorb_ask, bn_primary.absorb_bid, bn_primary.double_ask, bn_primary.double_bid,
            bn_primary.triple_ask, bn_primary.triple_bid,
            bn_primary.rotation_up, bn_primary.rotation_down, bn_primary.volume_up, bn_primary.volume_down,
            bn_primary.ask_10, bn_primary.bid_10, bn_primary.ask_30, bn_primary.bid_30,
            bn_primary.ask_100, bn_primary.bid_100, bn_primary.ask_150, bn_primary.bid_150,
            bn_primary.ask_400, bn_primary.bid_400, bn_primary.ask_1000, bn_primary.bid_1000,
            bn_primary.cluster_vol,
            bn_primary.long_down_up, bn_primary.long_up_down,
            bn_primary.bar_color_up, bn_primary.bar_color_down,
            bn_primary.bar_edge_buy, bn_primary.bar_edge_sell);
    
    // FPBS & CVD
    fprintf(f, "\"fpbs_ask_pct\":%.4f,\"fpbs_bid_pct\":%.4f,\"fpbs_delta\":%.0f,\"fpbs_delta_day\":%.0f,"
               "\"fpbs_cvd\":%.0f,\"fpbs_poc\":%.2f,"
               "\"cvd_slope\":%.4f,\"cvd_div\":%s,\"cvd_trend_score\":%.4f,\"poc_confirm\":%d,"
               // Momentum
               "\"color_momentum\":%.4f,\"momentum_shift\":%.4f,"
               "\"buyer_strength\":%.4f,\"seller_strength\":%.4f,\"institutional_pressure\":%.4f,",
            bn_primary.fpbs_ask_pct, bn_primary.fpbs_bid_pct, bn_primary.fpbs_delta, bn_primary.fpbs_delta_day,
            bn_primary.fpbs_cvd, bn_primary.fpbs_poc,
            bn_primary.cvd_slope, bn_primary.cvd_divergence ? "true" : "false", bn_primary.cvd_trend_score, bn_primary.poc_confirm,
            bn_primary.color_momentum, bn_primary.momentum_shift,
            bn_primary.buyer_strength, bn_primary.seller_strength, bn_primary.institutional_pressure);
    
    // Rectangles & Structure
    fprintf(f, "\"fresh_rect_buy\":%s,\"fresh_rect_sell\":%s,\"fresh_rect_age\":%d,"
               "\"edge_ratio\":%.4f,\"edge_dom_buy\":%s,\"edge_dom_sell\":%s,"
               "\"num_ext_support\":%d,\"num_ext_resist\":%d,"
               "\"nearest_ext_support\":%.2f,\"nearest_ext_resist\":%.2f,"
               "\"dist_support_ticks\":%.1f,\"dist_resist_ticks\":%.1f,"
               "\"num_long_up_bar\":%d,\"num_long_down_bar\":%d,"
               "\"nearest_long_up\":%.2f,\"nearest_long_down\":%.2f,"
               "\"has_trad_support\":%s,\"has_trad_resist\":%s,",
            bn_primary.fresh_rectangle_buy ? "true" : "false", bn_primary.fresh_rectangle_sell ? "true" : "false", bn_primary.fresh_rect_age_bars,
            bn_primary.edge_ratio, bn_primary.edge_dominant_buy ? "true" : "false", bn_primary.edge_dominant_sell ? "true" : "false",
            bn_primary.num_ext_support, bn_primary.num_ext_resist,
            bn_primary.nearest_ext_support, bn_primary.nearest_ext_resist,
            bn_primary.dist_nearest_support_ticks, bn_primary.dist_nearest_resist_ticks,
            bn_primary.num_long_up_bar, bn_primary.num_long_down_bar,
            bn_primary.nearest_long_up_bar, bn_primary.nearest_long_down_bar,
            bn_primary.has_tradable_support ? "true" : "false", bn_primary.has_tradable_resist ? "true" : "false");
    
    // Edge Rects
    fprintf(f, "\"num_edge_rect_buy\":%d,\"num_edge_rect_sell\":%d,"
               "\"nearest_edge_support\":%.2f,\"nearest_edge_resist\":%.2f,"
               "\"in_edge_rect_buy\":%s,\"in_edge_rect_sell\":%s,",
            bn_primary.num_edge_rect_buy, bn_primary.num_edge_rect_sell,
            bn_primary.nearest_edge_rect_support, bn_primary.nearest_edge_rect_resist,
            bn_primary.price_in_edge_rect_buy ? "true" : "false", bn_primary.price_in_edge_rect_sell ? "true" : "false");
    
    // Bataille Navale Avancée
    fprintf(f, "\"lowest_edge_buy\":%.2f,\"highest_edge_sell\":%.2f,"
               "\"bn_attack_long\":%s,\"bn_attack_short\":%s,"
               "\"stacked_buy\":%d,\"stacked_sell\":%d,"
               "\"attack_str_buy\":%.4f,\"attack_str_sell\":%.4f,"
               "\"all_bullish\":%s,\"all_bearish\":%s,\"dir_coherence\":%.4f,",
            bn_primary.lowest_edge_buy, bn_primary.highest_edge_sell,
            bn_primary.bn_attack_long_valid ? "true" : "false", bn_primary.bn_attack_short_valid ? "true" : "false",
            bn_primary.stacked_buy_zones, bn_primary.stacked_sell_zones,
            bn_primary.attack_strength_buy, bn_primary.attack_strength_sell,
            bn_primary.all_signals_bullish ? "true" : "false", bn_primary.all_signals_bearish ? "true" : "false", bn_primary.directional_coherence);
    
    // Bases & Subtile
    fprintf(f, "\"green_base\":%.2f,\"red_base\":%.2f,"
               "\"subtile_long\":%s,\"subtile_short\":%s,",
            bn_primary.green_base_price, bn_primary.red_base_price,
            bn_primary.bn_subtile_long_valid ? "true" : "false", bn_primary.bn_subtile_short_valid ? "true" : "false");
    
    // Mode Range
    fprintf(f, "\"is_range\":%s,\"range_support\":%.2f,\"range_resist\":%.2f,"
               "\"range_mid\":%.2f,\"range_size\":%.2f,\"price_pos_pct\":%.4f,"
               // Swings & Delta
               "\"swing_high\":%.2f,\"swing_low\":%.2f,"
               "\"delta_div_buy\":%s,\"delta_div_sell\":%s,\"delta_div_str\":%.4f,"
               "\"delta_bar_bull\":%s,\"delta_bar_bear\":%s,"
               "\"single_print_high\":%.2f,\"single_print_low\":%.2f,\"near_single_print\":%s,"
               "\"num_lvn\":%d,\"nearest_lvn_above\":%.2f,\"nearest_lvn_below\":%.2f,"
               "\"lvn_levels\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"session_poc\":%.2f,\"session_vah\":%.2f,\"session_val\":%.2f,"
               // 🆕 DISTANCES aux LVN/POC
               "\"dist_single_print\":%.1f,\"dist_lvn_above\":%.1f,\"dist_lvn_below\":%.1f,"
               "\"dist_poc\":%.1f,\"dist_vah\":%.1f,\"dist_val\":%.1f,"
               "\"buy_pct\":%.4f,\"sell_pct\":%.4f},",
            bn_primary.is_range ? "true" : "false", bn_primary.range_support, bn_primary.range_resistance,
            bn_primary.range_midpoint, bn_primary.range_size_pts, bn_primary.price_position_pct,
            bn_primary.swing_high, bn_primary.swing_low,
            bn_primary.delta_div_buy ? "true" : "false", bn_primary.delta_div_sell ? "true" : "false", bn_primary.delta_div_strength,
            bn_primary.delta_bar_bullish ? "true" : "false", bn_primary.delta_bar_bearish ? "true" : "false",
            bn_primary.single_print_high, bn_primary.single_print_low, bn_primary.near_single_print ? "true" : "false",
            bn_primary.num_lvn, bn_primary.nearest_lvn_above, bn_primary.nearest_lvn_below,
            // Tous les LVN proches (10 max)
            bn_primary.lvn_levels[0], bn_primary.lvn_levels[1], bn_primary.lvn_levels[2], bn_primary.lvn_levels[3], bn_primary.lvn_levels[4],
            bn_primary.lvn_levels[5], bn_primary.lvn_levels[6], bn_primary.lvn_levels[7], bn_primary.lvn_levels[8], bn_primary.lvn_levels[9],
            bn_primary.session_poc, bn_primary.session_vah, bn_primary.session_val,
            bn_primary.dist_single_print_ticks, bn_primary.dist_lvn_above_ticks, bn_primary.dist_lvn_below_ticks,
            bn_primary.dist_session_poc_ticks, bn_primary.dist_session_vah_ticks, bn_primary.dist_session_val_ticks,
            bn_primary.buy_pct, bn_primary.sell_pct);
    
    // ═══ ARRAYS BN - COMPLET (comme Python) ═══
    // Extension Lines (jusqu'à 10)
    fprintf(f, "\"bn_arrays\":{"
               "\"ext_support\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"ext_resist\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
               // Long bars (jusqu'à 10)
               "\"long_up_ext\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"long_down_ext\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],"
               // Edge Rects Buy (jusqu'à 5)
               "\"edge_rect_buy_bot\":[%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"edge_rect_buy_top\":[%.2f,%.2f,%.2f,%.2f,%.2f],"
               // Edge Rects Sell (jusqu'à 5)
               "\"edge_rect_sell_bot\":[%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"edge_rect_sell_top\":[%.2f,%.2f,%.2f,%.2f,%.2f],"
               // Color prices (premiers 5 de chaque)
               "\"color_up_prices\":[%.2f,%.2f,%.2f,%.2f,%.2f],"
               "\"color_down_prices\":[%.2f,%.2f,%.2f,%.2f,%.2f]},",
            // ext_support[10]
            bn_primary.ext_lines_support[0], bn_primary.ext_lines_support[1], bn_primary.ext_lines_support[2],
            bn_primary.ext_lines_support[3], bn_primary.ext_lines_support[4], bn_primary.ext_lines_support[5],
            bn_primary.ext_lines_support[6], bn_primary.ext_lines_support[7], bn_primary.ext_lines_support[8],
            bn_primary.ext_lines_support[9],
            // ext_resist[10]
            bn_primary.ext_lines_resist[0], bn_primary.ext_lines_resist[1], bn_primary.ext_lines_resist[2],
            bn_primary.ext_lines_resist[3], bn_primary.ext_lines_resist[4], bn_primary.ext_lines_resist[5],
            bn_primary.ext_lines_resist[6], bn_primary.ext_lines_resist[7], bn_primary.ext_lines_resist[8],
            bn_primary.ext_lines_resist[9],
            // long_up_bar_ext[10]
            bn_primary.long_up_bar_ext[0], bn_primary.long_up_bar_ext[1], bn_primary.long_up_bar_ext[2],
            bn_primary.long_up_bar_ext[3], bn_primary.long_up_bar_ext[4], bn_primary.long_up_bar_ext[5],
            bn_primary.long_up_bar_ext[6], bn_primary.long_up_bar_ext[7], bn_primary.long_up_bar_ext[8],
            bn_primary.long_up_bar_ext[9],
            // long_down_bar_ext[10]
            bn_primary.long_down_bar_ext[0], bn_primary.long_down_bar_ext[1], bn_primary.long_down_bar_ext[2],
            bn_primary.long_down_bar_ext[3], bn_primary.long_down_bar_ext[4], bn_primary.long_down_bar_ext[5],
            bn_primary.long_down_bar_ext[6], bn_primary.long_down_bar_ext[7], bn_primary.long_down_bar_ext[8],
            bn_primary.long_down_bar_ext[9],
            // edge_rect_buy_bottom[5]
            bn_primary.edge_rect_buy_bottom[0], bn_primary.edge_rect_buy_bottom[1], bn_primary.edge_rect_buy_bottom[2],
            bn_primary.edge_rect_buy_bottom[3], bn_primary.edge_rect_buy_bottom[4],
            // edge_rect_buy_top[5]
            bn_primary.edge_rect_buy_top[0], bn_primary.edge_rect_buy_top[1], bn_primary.edge_rect_buy_top[2],
            bn_primary.edge_rect_buy_top[3], bn_primary.edge_rect_buy_top[4],
            // edge_rect_sell_bottom[5]
            bn_primary.edge_rect_sell_bottom[0], bn_primary.edge_rect_sell_bottom[1], bn_primary.edge_rect_sell_bottom[2],
            bn_primary.edge_rect_sell_bottom[3], bn_primary.edge_rect_sell_bottom[4],
            // edge_rect_sell_top[5]
            bn_primary.edge_rect_sell_top[0], bn_primary.edge_rect_sell_top[1], bn_primary.edge_rect_sell_top[2],
            bn_primary.edge_rect_sell_top[3], bn_primary.edge_rect_sell_top[4],
            // color_up_prices[5]
            bn_primary.color_up_prices[0], bn_primary.color_up_prices[1], bn_primary.color_up_prices[2],
            bn_primary.color_up_prices[3], bn_primary.color_up_prices[4],
            // color_down_prices[5]
            bn_primary.color_down_prices[0], bn_primary.color_down_prices[1], bn_primary.color_down_prices[2],
            bn_primary.color_down_prices[3], bn_primary.color_down_prices[4]);
    
    // ═══ BN SECONDARY ═══
    fprintf(f, "\"bn2\":{\"score\":%.4f,\"signal\":%d,\"cvd_slope\":%.4f,\"momentum\":%.4f},",
            bn_secondary.score, bn_secondary.signal, bn_secondary.cvd_slope, bn_secondary.momentum_score);
    
    // ═══ MENTHORQ PRIMARY - COMPLET (TOUS les GEX et Blind Spots!) ═══
    fprintf(f, "\"mq\":{"
               "\"hvl\":%.2f,\"hvl_0dte\":%.2f,"
               "\"gamma_wall\":%.2f,\"gamma_wall_0dte\":%.2f,"
               "\"call_res\":%.2f,\"call_res_0dte\":%.2f,"
               "\"put_sup\":%.2f,\"put_sup_0dte\":%.2f,"
               "\"vwap\":%.2f,\"vwap_up1\":%.2f,\"vwap_dn1\":%.2f,\"vwap_up2\":%.2f,\"vwap_dn2\":%.2f,"
               "\"day_min\":%.2f,\"day_max\":%.2f,"
               "\"vah\":%.2f,\"val\":%.2f,"
               "\"next_wall\":%.2f,\"wall_dist\":%.1f,\"wall_str\":%.4f,\"wall_side\":%d,"
               // Previous levels
               "\"prev_vah\":%.2f,\"prev_val\":%.2f,\"prev_vpoc\":%.2f,"
               "\"prev_vwap\":%.2f,\"prev_vwap_up1\":%.2f,\"prev_vwap_dn1\":%.2f,"
               // GEX COMPLET (10 niveaux comme Python)
               "\"gex_1\":%.2f,\"gex_2\":%.2f,\"gex_3\":%.2f,\"gex_4\":%.2f,\"gex_5\":%.2f,"
               "\"gex_6\":%.2f,\"gex_7\":%.2f,\"gex_8\":%.2f,\"gex_9\":%.2f,\"gex_10\":%.2f,"
               // Blind spots COMPLET (BL 1-9 comme MenthorQ - pas de BL 0!)
               "\"blind_spot_1\":%.2f,\"blind_spot_2\":%.2f,\"blind_spot_3\":%.2f,"
               "\"blind_spot_4\":%.2f,\"blind_spot_5\":%.2f,\"blind_spot_6\":%.2f,"
               "\"blind_spot_7\":%.2f,\"blind_spot_8\":%.2f,\"blind_spot_9\":%.2f,"
               // 🆕 DISTANCES (comme Python: menthor_distances)
               "\"dist_gex_up\":%.1f,\"dist_gex_dn\":%.1f,\"dist_blind\":%.1f,"
               "\"dist_gamma\":%.1f,\"dist_call\":%.1f,\"dist_put\":%.1f,"
               "\"nearest_gex_up\":%.2f,\"nearest_gex_dn\":%.2f,\"nearest_blind\":%.2f},",
            mq_primary.hvl, mq_primary.hvl_0dte,
            mq_primary.gamma_wall, mq_primary.gamma_wall_0dte,
            mq_primary.call_resistance, mq_primary.call_resistance_0dte,
            mq_primary.put_support, mq_primary.put_support_0dte,
            mq_primary.vwap, mq_primary.vwap_up1, mq_primary.vwap_dn1, mq_primary.vwap_up2, mq_primary.vwap_dn2,
            mq_primary.day_min, mq_primary.day_max,
            mq_primary.vah, mq_primary.val,
            mq_primary.next_wall, mq_primary.wall_distance_ticks, mq_primary.next_wall_strength, mq_primary.next_wall_side,
            mq_primary.prev_vah, mq_primary.prev_val, mq_primary.prev_vpoc,
            mq_primary.prev_vwap, mq_primary.prev_vwap_sd1_up, mq_primary.prev_vwap_sd1_dn,
            // GEX 1-10 (index 0-9)
            mq_primary.gex[0], mq_primary.gex[1], mq_primary.gex[2], mq_primary.gex[3], mq_primary.gex[4],
            mq_primary.gex[5], mq_primary.gex[6], mq_primary.gex[7], mq_primary.gex[8], mq_primary.gex[9],
            // Blind spots 0-8
            mq_primary.blind_spots[0], mq_primary.blind_spots[1], mq_primary.blind_spots[2],
            mq_primary.blind_spots[3], mq_primary.blind_spots[4], mq_primary.blind_spots[5],
            mq_primary.blind_spots[6], mq_primary.blind_spots[7], mq_primary.blind_spots[8],
            // Distances en ticks (comme Python: menthor_distances)
            mq_primary.dist_gex_up_ticks, mq_primary.dist_gex_dn_ticks, mq_primary.dist_blind_ticks,
            mq_primary.dist_gamma_ticks, mq_primary.dist_call_ticks, mq_primary.dist_put_ticks,
            mq_primary.nearest_gex_up, mq_primary.nearest_gex_dn, mq_primary.nearest_blind);
    
    // ═══ MQ SECONDARY ═══
    fprintf(f, "\"mq2\":{\"hvl\":%.2f,\"gamma_wall\":%.2f,\"vwap\":%.2f,\"call\":%.2f,\"put\":%.2f},",
            mq_secondary.hvl, mq_secondary.gamma_wall_0dte, mq_secondary.vwap,
            mq_secondary.call_resistance, mq_secondary.put_support);
    
    // ═══ BOT STATE - COMPLET ═══
    fprintf(f, "\"state\":{\"in_pos\":%s,\"dir\":%d,\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,"
               "\"trailing_active\":%s,\"trailing_allowed\":%s,"
               "\"trades\":%d,\"wins\":%d,\"losses\":%d,\"pnl\":%.2f,\"cons_loss\":%d,"
               "\"waiting\":\"%s\",\"last_reject\":\"%s\"}}\n",
            state.in_position ? "true" : "false", state.direction, state.entry_price, state.sl_price, state.tp_price,
            state.trailing_activated ? "true" : "false", state.trailing_allowed ? "true" : "false",
            state.trades_today, state.wins_today, state.trades_today - state.wins_today, state.pnl_today, state.consecutive_losses,
            state.waiting_for, state.last_reject_reason);
    
    fclose(f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 14: STUDY PRINCIPALE
// ═══════════════════════════════════════════════════════════════════════════════