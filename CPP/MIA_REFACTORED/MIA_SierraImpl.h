// ⚠️ DEPRECATED 14/03/2026 — Non inclus dans MIA_Main.cpp
// Implémentation SC des interfaces. Garder pour le futur.
// Ne pas supprimer — sera réutilisé en Phase 3.
#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_SierraImpl.h - IMPLÉMENTATION SIERRA CHART (PRODUCTION)
// ═══════════════════════════════════════════════════════════════════════════════
// 31/01/2026 - Implémentation des interfaces pour Sierra Chart
//
// Cette implémentation utilise l'API Sierra Chart réelle.
// Utilisée en production sur le bot live.
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Interfaces.h"
#include "MIA_DataReader.h"
#include "sierrachart.h"

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: SierraStudyReader
// ═══════════════════════════════════════════════════════════════════════════════

class SierraStudyReader : public IStudyReader {
private:
    SCStudyInterfaceRef& sc;
    
public:
    SierraStudyReader(SCStudyInterfaceRef& sc_ref) : sc(sc_ref) {}
    
    float ReadStudyValue(int chart_number, int study_id, int subgraph, int bar_index = -1) override {
        SCFloatArray study_array;
        sc.GetStudyArrayUsingID(chart_number, study_id, subgraph, study_array);
        
        if (study_array.GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? study_array.GetArraySize() - 1 : bar_index;
        if (idx < 0 || idx >= study_array.GetArraySize()) return 0.0f;
        
        return study_array[idx];
    }
    
    float GetOpen(int chart_number, int bar_index = -1) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        if (chart_data[SC_OPEN].GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? chart_data[SC_OPEN].GetArraySize() - 1 : bar_index;
        return chart_data[SC_OPEN][idx];
    }
    
    float GetHigh(int chart_number, int bar_index = -1) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        if (chart_data[SC_HIGH].GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? chart_data[SC_HIGH].GetArraySize() - 1 : bar_index;
        return chart_data[SC_HIGH][idx];
    }
    
    float GetLow(int chart_number, int bar_index = -1) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        if (chart_data[SC_LOW].GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? chart_data[SC_LOW].GetArraySize() - 1 : bar_index;
        return chart_data[SC_LOW][idx];
    }
    
    float GetClose(int chart_number, int bar_index = -1) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        if (chart_data[SC_LAST].GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? chart_data[SC_LAST].GetArraySize() - 1 : bar_index;
        return chart_data[SC_LAST][idx];
    }
    
    float GetVolume(int chart_number, int bar_index = -1) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        if (chart_data[SC_VOLUME].GetArraySize() == 0) return 0.0f;
        
        int idx = (bar_index < 0) ? chart_data[SC_VOLUME].GetArraySize() - 1 : bar_index;
        return chart_data[SC_VOLUME][idx];
    }
    
    int GetArraySize(int chart_number) override {
        SCGraphData chart_data;
        sc.GetChartBaseData(chart_number, chart_data);
        return chart_data[SC_LAST].GetArraySize();
    }
    
    long long GetCurrentTimestampMs() override {
        return (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    }
    
    void GetDateTime(int& year, int& month, int& day, int& hour, int& minute, int& second) override {
        sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: SierraMarketDataProvider
// ═══════════════════════════════════════════════════════════════════════════════

class SierraMarketDataProvider : public IMarketDataProvider {
private:
    SCStudyInterfaceRef& sc;
    int es_footprint_chart;
    int es_barres_chart;
    int nq_footprint_chart;
    int nq_barres_chart;
    int es_main_chart;
    int nq_main_chart;
    int vix_chart;
    
    // Cache des données (mis à jour à chaque appel)
    BN_Data cached_bn_es;
    BN_Data cached_bn_nq;
    MenthorQ_Data cached_mq_es;
    MenthorQ_Data cached_mq_nq;
    bool cache_valid;
    
public:
    SierraMarketDataProvider(SCStudyInterfaceRef& sc_ref,
                             int es_fp, int es_bar, int nq_fp, int nq_bar,
                             int es_main, int nq_main, int vix)
        : sc(sc_ref), 
          es_footprint_chart(es_fp), es_barres_chart(es_bar),
          nq_footprint_chart(nq_fp), nq_barres_chart(nq_bar),
          es_main_chart(es_main), nq_main_chart(nq_main),
          vix_chart(vix), cache_valid(false) {}
    
    void RefreshData() {
        CollectBN_Data(sc, es_footprint_chart, es_barres_chart, cached_bn_es, false);
        CollectBN_Data(sc, nq_footprint_chart, nq_barres_chart, cached_bn_nq, true);
        CollectMenthorQ_Data(sc, es_main_chart, cached_mq_es, false);
        CollectMenthorQ_Data(sc, nq_main_chart, cached_mq_nq, true);
        cache_valid = true;
    }
    
    float GetCurrentPrice(bool is_nq) override {
        int chart = is_nq ? nq_main_chart : es_main_chart;
        SCGraphData chart_data;
        sc.GetChartBaseData(chart, chart_data);
        if (chart_data[SC_LAST].GetArraySize() == 0) return 0.0f;
        return chart_data[SC_LAST][chart_data[SC_LAST].GetArraySize() - 1];
    }
    
    float GetBid(bool is_nq) override {
        s_MarketDepthEntry entry;
        sc.GetBidMarketDepthEntryAtLevel(entry, 0);
        return entry.Price;
    }
    
    float GetAsk(bool is_nq) override {
        s_MarketDepthEntry entry;
        sc.GetAskMarketDepthEntryAtLevel(entry, 0);
        return entry.Price;
    }
    
    float GetSpread(bool is_nq) override {
        return GetAsk(is_nq) - GetBid(is_nq);
    }
    
    BN_Data GetBatailleNavale(bool is_nq) override {
        if (!cache_valid) RefreshData();
        return is_nq ? cached_bn_nq : cached_bn_es;
    }
    
    MenthorQ_Data GetMenthorQ(bool is_nq) override {
        if (!cache_valid) RefreshData();
        return is_nq ? cached_mq_nq : cached_mq_es;
    }
    
    float GetVIX() override {
        return g_market_live.vix;
    }
    
    int GetVIXRegime() override {
        return g_market_live.vix_regime;
    }
    
    float GetATR(bool is_nq) override {
        return is_nq ? g_market_live.atr_nq : g_market_live.atr_es;
    }
    
    float GetCorrelationESNQ() override {
        // TODO: Calculer corrélation réelle
        return 0.85f;  // Valeur par défaut
    }
    
    float GetVWAPSlope(bool is_nq) override {
        return is_nq ? g_market_live.vwap_slope_nq : g_market_live.vwap_slope_es;
    }
    
    int GetDOMBidQty(bool is_nq, int level = 0) override {
        s_MarketDepthEntry entry;
        sc.GetBidMarketDepthEntryAtLevel(entry, level);
        return entry.Quantity;
    }
    
    int GetDOMAskQty(bool is_nq, int level = 0) override {
        s_MarketDepthEntry entry;
        sc.GetAskMarketDepthEntryAtLevel(entry, level);
        return entry.Quantity;
    }
    
    float GetDepthImbalance(bool is_nq) override {
        int bid_qty = GetDOMBidQty(is_nq, 0);
        int ask_qty = GetDOMAskQty(is_nq, 0);
        int total = bid_qty + ask_qty;
        if (total == 0) return 0.0f;
        return (float)(bid_qty - ask_qty) / total;
    }
    
    const char* GetCurrentSession() override {
        return g_dashboard.current_session;
    }
    
    bool IsSessionOpen() override {
        // Vérifier si on est dans les heures de trading
        int year, month, day, hour, minute, second;
        sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
        
        // US Session: 9:30 - 16:00 ET (approximatif)
        return (hour >= 9 && hour < 16);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: SierraOrderExecutor
// ═══════════════════════════════════════════════════════════════════════════════

class SierraOrderExecutor : public IOrderExecutor {
private:
    SCStudyInterfaceRef& sc;
    BotState& es_state;
    BotState& nq_state;
    
public:
    SierraOrderExecutor(SCStudyInterfaceRef& sc_ref, BotState& es, BotState& nq)
        : sc(sc_ref), es_state(es), nq_state(nq) {}
    
    OrderResult BuyMarket(bool is_nq, int quantity = 1) override {
        OrderResult result;
        // Utiliser l'API Sierra Chart pour envoyer un ordre market
        s_SCNewOrder order;
        order.OrderType = SCT_ORDERTYPE_MARKET;
        order.OrderQuantity = quantity;
        
        int order_id = sc.BuyEntry(order);
        result.success = (order_id > 0);
        result.order_id = order_id;
        
        if (!result.success) {
            strncpy(result.error_message, "BuyMarket failed", sizeof(result.error_message) - 1);
        }
        
        return result;
    }
    
    OrderResult SellMarket(bool is_nq, int quantity = 1) override {
        OrderResult result;
        s_SCNewOrder order;
        order.OrderType = SCT_ORDERTYPE_MARKET;
        order.OrderQuantity = quantity;
        
        int order_id = sc.SellEntry(order);
        result.success = (order_id > 0);
        result.order_id = order_id;
        
        if (!result.success) {
            strncpy(result.error_message, "SellMarket failed", sizeof(result.error_message) - 1);
        }
        
        return result;
    }
    
    OrderResult BuyLimit(bool is_nq, float price, int quantity = 1) override {
        OrderResult result;
        s_SCNewOrder order;
        order.OrderType = SCT_ORDERTYPE_LIMIT;
        order.OrderQuantity = quantity;
        order.Price1 = price;
        
        int order_id = sc.BuyEntry(order);
        result.success = (order_id > 0);
        result.order_id = order_id;
        
        return result;
    }
    
    OrderResult SellLimit(bool is_nq, float price, int quantity = 1) override {
        OrderResult result;
        s_SCNewOrder order;
        order.OrderType = SCT_ORDERTYPE_LIMIT;
        order.OrderQuantity = quantity;
        order.Price1 = price;
        
        int order_id = sc.SellEntry(order);
        result.success = (order_id > 0);
        result.order_id = order_id;
        
        return result;
    }
    
    OrderResult SendBracketOrder(bool is_nq, int direction, float entry_price,
                                 float sl_price, float tp_price, int quantity = 1) override {
        OrderResult result;
        
        // Utiliser la fonction existante SendBracketOrder du bot
        BotState& state = is_nq ? nq_state : es_state;
        float bn_anchor = entry_price;  // Simplified
        
        bool success = ::SendBracketOrder(sc, direction, entry_price, sl_price, tp_price, state, bn_anchor);
        result.success = success;
        
        if (success) {
            result.fill_price = entry_price;
        } else {
            strncpy(result.error_message, "SendBracketOrder failed", sizeof(result.error_message) - 1);
        }
        
        return result;
    }
    
    bool ModifyOrder(int order_id, float new_price) override {
        s_SCTradeOrder existing_order;
        if (sc.GetOrderByOrderID(order_id, existing_order) == SCTRADING_ORDER_ERROR) {
            return false;
        }
        
        s_SCNewOrder modify_order;
        modify_order.InternalOrderID = order_id;
        modify_order.Price1 = new_price;
        
        return (sc.ModifyOrder(modify_order) != SCTRADING_ORDER_ERROR);
    }
    
    bool CancelOrder(int order_id) override {
        return (sc.CancelOrder(order_id) != SCTRADING_ORDER_ERROR);
    }
    
    bool CancelAllOrders(bool is_nq) override {
        sc.CancelAllOrders();
        return true;
    }
    
    bool IsInPosition(bool is_nq) override {
        BotState& state = is_nq ? nq_state : es_state;
        return state.in_position;
    }
    
    int GetPositionDirection(bool is_nq) override {
        BotState& state = is_nq ? nq_state : es_state;
        return state.direction;
    }
    
    float GetPositionEntryPrice(bool is_nq) override {
        BotState& state = is_nq ? nq_state : es_state;
        return state.entry_price;
    }
    
    int GetPositionQuantity(bool is_nq) override {
        s_SCPositionData pos;
        sc.GetTradePosition(pos);
        return (int)pos.PositionQuantity;
    }
    
    OrderResult ClosePosition(bool is_nq) override {
        OrderResult result;
        
        BotState& state = is_nq ? nq_state : es_state;
        if (!state.in_position) {
            result.success = false;
            strncpy(result.error_message, "Not in position", sizeof(result.error_message) - 1);
            return result;
        }
        
        // Fermer avec ordre market opposé
        if (state.direction == 1) {
            return SellMarket(is_nq, 1);
        } else {
            return BuyMarket(is_nq, 1);
        }
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: SierraLogger
// ═══════════════════════════════════════════════════════════════════════════════

class SierraLogger : public ILogger {
private:
    SCStudyInterfaceRef& sc;
    
public:
    SierraLogger(SCStudyInterfaceRef& sc_ref) : sc(sc_ref) {}
    
    void Log(LogLevel level, const char* message) override {
        int sc_level = 0;  // 0 = normal message
        if (level >= LogLevel::WARNING) sc_level = 1;  // 1 = warning
        if (level >= LogLevel::ERROR) sc_level = 2;    // 2 = error
        
        sc.AddMessageToLog(message, sc_level);
    }
    
    void LogFormat(LogLevel level, const char* format, ...) override {
        char buffer[512];
        va_list args;
        va_start(args, format);
        vsnprintf(buffer, sizeof(buffer), format, args);
        va_end(args);
        
        Log(level, buffer);
    }
    
    void LogSignal(const char* symbol, int direction, const char* reason) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "[SIGNAL] %s %s: %s",
                symbol, direction == 1 ? "LONG" : "SHORT", reason);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogReject(const char* symbol, const char* layer, const char* reason) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "[REJECT] %s %s: %s", symbol, layer, reason);
        Log(LogLevel::DEBUG, buffer);
    }
    
    void LogTrade(const char* symbol, int direction, float entry, float sl, float tp) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "[TRADE] %s %s Entry=%.2f SL=%.2f TP=%.2f",
                symbol, direction == 1 ? "LONG" : "SHORT", entry, sl, tp);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogExit(const char* symbol, float exit_price, float pnl, const char* reason) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "[EXIT] %s @ %.2f PnL=%.2f (%s)",
                symbol, exit_price, pnl, reason);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogToFile(const char* filename, const char* message) override {
        std::ofstream file(filename, std::ios::app);
        if (file.is_open()) {
            file << message << "\n";
            file.close();
        }
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: SierraTimeProvider
// ═══════════════════════════════════════════════════════════════════════════════

class SierraTimeProvider : public ITimeProvider {
private:
    SCStudyInterfaceRef& sc;
    int last_day;
    
public:
    SierraTimeProvider(SCStudyInterfaceRef& sc_ref) : sc(sc_ref), last_day(-1) {}
    
    long long GetCurrentTimeMs() override {
        return (long long)(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
    }
    
    void GetCurrentDateTime(int& year, int& month, int& day, 
                           int& hour, int& minute, int& second) override {
        sc.CurrentSystemDateTime.GetDateTimeYMDHMS(year, month, day, hour, minute, second);
    }
    
    bool IsWithinTradingHours() override {
        int year, month, day, hour, minute, second;
        GetCurrentDateTime(year, month, day, hour, minute, second);
        
        // Trading hours: 6:00 - 17:00 ET (approximatif)
        return (hour >= 6 && hour < 17);
    }
    
    bool IsNewDay() override {
        int year, month, day, hour, minute, second;
        GetCurrentDateTime(year, month, day, hour, minute, second);
        
        bool is_new = (day != last_day && last_day >= 0);
        last_day = day;
        return is_new;
    }
    
    const char* GetSessionName() override {
        return g_dashboard.current_session;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// FACTORY: Créer le contexte Sierra Chart
// ═══════════════════════════════════════════════════════════════════════════════

inline MIAContext CreateSierraContext(
    SCStudyInterfaceRef& sc,
    int es_fp, int es_bar, int nq_fp, int nq_bar,
    int es_main, int nq_main, int vix_chart,
    BotState& es_state, BotState& nq_state
) {
    static SierraStudyReader study_reader(sc);
    static SierraMarketDataProvider market_data(sc, es_fp, es_bar, nq_fp, nq_bar, es_main, nq_main, vix_chart);
    static SierraOrderExecutor order_executor(sc, es_state, nq_state);
    static SierraLogger logger(sc);
    static SierraTimeProvider time_provider(sc);
    
    MIAContext ctx;
    ctx.study_reader = &study_reader;
    ctx.market_data = &market_data;
    ctx.order_executor = &order_executor;
    ctx.logger = &logger;
    ctx.time_provider = &time_provider;
    
    return ctx;
}