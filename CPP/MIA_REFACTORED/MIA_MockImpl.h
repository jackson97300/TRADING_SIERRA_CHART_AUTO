// ⚠️ DEPRECATED 14/03/2026 — Non inclus dans MIA_Main.cpp
// Mock pour tests unitaires. Garder pour quand on testera MIA_Entry.h en isolation.
// Ne pas supprimer — sera réutilisé en Phase 3.
#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_MockImpl.h - IMPLÉMENTATION MOCK POUR TESTS UNITAIRES
// ═══════════════════════════════════════════════════════════════════════════════
// 31/01/2026 - Implémentation des interfaces pour tests sans Sierra Chart
//
// Permet de:
//   1. Tester les Layers avec des données contrôlées
//   2. Simuler des scénarios de marché
//   3. Vérifier le comportement du bot
//   4. Debugger sans connection live
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Interfaces.h"
#include <vector>
#include <map>
#include <cstdio>

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: MockStudyReader
// ═══════════════════════════════════════════════════════════════════════════════

class MockStudyReader : public IStudyReader {
private:
    // Données simulées: chart_number -> study_id -> subgraph -> values
    std::map<int, std::map<int, std::map<int, std::vector<float>>>> data;
    
    // OHLCV par chart
    std::map<int, std::vector<float>> open_data;
    std::map<int, std::vector<float>> high_data;
    std::map<int, std::vector<float>> low_data;
    std::map<int, std::vector<float>> close_data;
    std::map<int, std::vector<float>> volume_data;
    
    // Temps simulé
    long long current_time_ms;
    int year, month, day, hour, minute, second;
    
public:
    MockStudyReader() : current_time_ms(0), year(2026), month(1), day(31),
                        hour(10), minute(0), second(0) {}
    
    // === CONFIGURATION DES DONNÉES SIMULÉES ===
    
    void SetStudyData(int chart, int study_id, int subgraph, const std::vector<float>& values) {
        data[chart][study_id][subgraph] = values;
    }
    
    void SetOHLCV(int chart, const std::vector<float>& o, const std::vector<float>& h,
                  const std::vector<float>& l, const std::vector<float>& c,
                  const std::vector<float>& v) {
        open_data[chart] = o;
        high_data[chart] = h;
        low_data[chart] = l;
        close_data[chart] = c;
        volume_data[chart] = v;
    }
    
    void SetTime(long long time_ms) { current_time_ms = time_ms; }
    void SetDateTime(int y, int m, int d, int h, int mi, int s) {
        year = y; month = m; day = d; hour = h; minute = mi; second = s;
    }
    
    // === INTERFACE IStudyReader ===
    
    float ReadStudyValue(int chart_number, int study_id, int subgraph, int bar_index = -1) override {
        auto chart_it = data.find(chart_number);
        if (chart_it == data.end()) return 0.0f;
        
        auto study_it = chart_it->second.find(study_id);
        if (study_it == chart_it->second.end()) return 0.0f;
        
        auto sg_it = study_it->second.find(subgraph);
        if (sg_it == study_it->second.end()) return 0.0f;
        
        const auto& values = sg_it->second;
        if (values.empty()) return 0.0f;
        
        int idx = (bar_index < 0) ? (int)values.size() - 1 : bar_index;
        if (idx < 0 || idx >= (int)values.size()) return 0.0f;
        
        return values[idx];
    }
    
    float GetOpen(int chart_number, int bar_index = -1) override {
        auto it = open_data.find(chart_number);
        if (it == open_data.end() || it->second.empty()) return 0.0f;
        int idx = (bar_index < 0) ? (int)it->second.size() - 1 : bar_index;
        return it->second[idx];
    }
    
    float GetHigh(int chart_number, int bar_index = -1) override {
        auto it = high_data.find(chart_number);
        if (it == high_data.end() || it->second.empty()) return 0.0f;
        int idx = (bar_index < 0) ? (int)it->second.size() - 1 : bar_index;
        return it->second[idx];
    }
    
    float GetLow(int chart_number, int bar_index = -1) override {
        auto it = low_data.find(chart_number);
        if (it == low_data.end() || it->second.empty()) return 0.0f;
        int idx = (bar_index < 0) ? (int)it->second.size() - 1 : bar_index;
        return it->second[idx];
    }
    
    float GetClose(int chart_number, int bar_index = -1) override {
        auto it = close_data.find(chart_number);
        if (it == close_data.end() || it->second.empty()) return 0.0f;
        int idx = (bar_index < 0) ? (int)it->second.size() - 1 : bar_index;
        return it->second[idx];
    }
    
    float GetVolume(int chart_number, int bar_index = -1) override {
        auto it = volume_data.find(chart_number);
        if (it == volume_data.end() || it->second.empty()) return 0.0f;
        int idx = (bar_index < 0) ? (int)it->second.size() - 1 : bar_index;
        return it->second[idx];
    }
    
    int GetArraySize(int chart_number) override {
        auto it = close_data.find(chart_number);
        return (it != close_data.end()) ? (int)it->second.size() : 0;
    }
    
    long long GetCurrentTimestampMs() override { return current_time_ms; }
    
    void GetDateTime(int& y, int& m, int& d, int& h, int& mi, int& s) override {
        y = year; m = month; d = day; h = hour; mi = minute; s = second;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: MockMarketDataProvider
// ═══════════════════════════════════════════════════════════════════════════════

class MockMarketDataProvider : public IMarketDataProvider {
private:
    float es_price, nq_price;
    float es_bid, es_ask, nq_bid, nq_ask;
    BN_Data bn_es, bn_nq;
    MenthorQ_Data mq_es, mq_nq;
    float vix;
    int vix_regime;
    float atr_es, atr_nq;
    float corr_es_nq;
    float vwap_slope_es, vwap_slope_nq;
    int dom_bid_es, dom_ask_es, dom_bid_nq, dom_ask_nq;
    char session[16];
    bool session_open;
    
public:
    MockMarketDataProvider() : es_price(6000.0f), nq_price(21000.0f),
                               es_bid(5999.75f), es_ask(6000.25f),
                               nq_bid(20999.75f), nq_ask(21000.25f),
                               vix(15.0f), vix_regime(1), 
                               atr_es(15.0f), atr_nq(300.0f),
                               corr_es_nq(0.85f),
                               vwap_slope_es(0.001f), vwap_slope_nq(0.001f),
                               dom_bid_es(100), dom_ask_es(100),
                               dom_bid_nq(50), dom_ask_nq(50),
                               session_open(true) {
        memset(&bn_es, 0, sizeof(BN_Data));
        memset(&bn_nq, 0, sizeof(BN_Data));
        memset(&mq_es, 0, sizeof(MenthorQ_Data));
        memset(&mq_nq, 0, sizeof(MenthorQ_Data));
        strcpy(session, "US");
    }
    
    // === CONFIGURATION ===
    
    void SetPrice(bool is_nq, float price, float bid, float ask) {
        if (is_nq) { nq_price = price; nq_bid = bid; nq_ask = ask; }
        else { es_price = price; es_bid = bid; es_ask = ask; }
    }
    
    void SetBN(bool is_nq, const BN_Data& bn) {
        if (is_nq) bn_nq = bn; else bn_es = bn;
    }
    
    void SetMQ(bool is_nq, const MenthorQ_Data& mq) {
        if (is_nq) mq_nq = mq; else mq_es = mq;
    }
    
    void SetVIX(float v, int regime) { vix = v; vix_regime = regime; }
    void SetATR(bool is_nq, float atr) { if (is_nq) atr_nq = atr; else atr_es = atr; }
    void SetCorrelation(float corr) { corr_es_nq = corr; }
    void SetVWAPSlope(bool is_nq, float slope) { 
        if (is_nq) vwap_slope_nq = slope; else vwap_slope_es = slope; 
    }
    void SetDOM(bool is_nq, int bid_qty, int ask_qty) {
        if (is_nq) { dom_bid_nq = bid_qty; dom_ask_nq = ask_qty; }
        else { dom_bid_es = bid_qty; dom_ask_es = ask_qty; }
    }
    void SetSession(const char* sess, bool is_open) { 
        strncpy(session, sess, sizeof(session) - 1);
        session_open = is_open;
    }
    
    // === INTERFACE IMarketDataProvider ===
    
    float GetCurrentPrice(bool is_nq) override { return is_nq ? nq_price : es_price; }
    float GetBid(bool is_nq) override { return is_nq ? nq_bid : es_bid; }
    float GetAsk(bool is_nq) override { return is_nq ? nq_ask : es_ask; }
    float GetSpread(bool is_nq) override { return GetAsk(is_nq) - GetBid(is_nq); }
    BN_Data GetBatailleNavale(bool is_nq) override { return is_nq ? bn_nq : bn_es; }
    MenthorQ_Data GetMenthorQ(bool is_nq) override { return is_nq ? mq_nq : mq_es; }
    float GetVIX() override { return vix; }
    int GetVIXRegime() override { return vix_regime; }
    float GetATR(bool is_nq) override { return is_nq ? atr_nq : atr_es; }
    float GetCorrelationESNQ() override { return corr_es_nq; }
    float GetVWAPSlope(bool is_nq) override { return is_nq ? vwap_slope_nq : vwap_slope_es; }
    int GetDOMBidQty(bool is_nq, int level = 0) override { return is_nq ? dom_bid_nq : dom_bid_es; }
    int GetDOMAskQty(bool is_nq, int level = 0) override { return is_nq ? dom_ask_nq : dom_ask_es; }
    float GetDepthImbalance(bool is_nq) override {
        int bid = is_nq ? dom_bid_nq : dom_bid_es;
        int ask = is_nq ? dom_ask_nq : dom_ask_es;
        int total = bid + ask;
        return total > 0 ? (float)(bid - ask) / total : 0.0f;
    }
    const char* GetCurrentSession() override { return session; }
    bool IsSessionOpen() override { return session_open; }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: MockOrderExecutor
// ═══════════════════════════════════════════════════════════════════════════════

struct MockOrder {
    int order_id;
    bool is_nq;
    int direction;  // 1=BUY, -1=SELL
    float price;
    float sl;
    float tp;
    int quantity;
    bool filled;
    bool cancelled;
};

class MockOrderExecutor : public IOrderExecutor {
private:
    std::vector<MockOrder> orders;
    int next_order_id;
    
    // Position simulée
    bool es_in_position, nq_in_position;
    int es_direction, nq_direction;
    float es_entry, nq_entry;
    int es_qty, nq_qty;
    
public:
    MockOrderExecutor() : next_order_id(1000),
                          es_in_position(false), nq_in_position(false),
                          es_direction(0), nq_direction(0),
                          es_entry(0), nq_entry(0),
                          es_qty(0), nq_qty(0) {}
    
    // === ACCÈS AUX ORDRES (pour vérification dans les tests) ===
    
    const std::vector<MockOrder>& GetOrders() const { return orders; }
    void ClearOrders() { orders.clear(); }
    
    void SetPosition(bool is_nq, int direction, float entry, int qty) {
        if (is_nq) {
            nq_in_position = (direction != 0);
            nq_direction = direction;
            nq_entry = entry;
            nq_qty = qty;
        } else {
            es_in_position = (direction != 0);
            es_direction = direction;
            es_entry = entry;
            es_qty = qty;
        }
    }
    
    // === INTERFACE IOrderExecutor ===
    
    OrderResult BuyMarket(bool is_nq, int quantity = 1) override {
        OrderResult result;
        result.success = true;
        result.order_id = next_order_id++;
        result.fill_price = is_nq ? 21000.25f : 6000.25f;  // Simuler fill au ask
        
        MockOrder order = {result.order_id, is_nq, 1, result.fill_price, 0, 0, quantity, true, false};
        orders.push_back(order);
        
        // Mettre à jour position
        SetPosition(is_nq, 1, result.fill_price, quantity);
        
        return result;
    }
    
    OrderResult SellMarket(bool is_nq, int quantity = 1) override {
        OrderResult result;
        result.success = true;
        result.order_id = next_order_id++;
        result.fill_price = is_nq ? 20999.75f : 5999.75f;  // Simuler fill au bid
        
        MockOrder order = {result.order_id, is_nq, -1, result.fill_price, 0, 0, quantity, true, false};
        orders.push_back(order);
        
        // Mettre à jour position
        SetPosition(is_nq, -1, result.fill_price, quantity);
        
        return result;
    }
    
    OrderResult BuyLimit(bool is_nq, float price, int quantity = 1) override {
        OrderResult result;
        result.success = true;
        result.order_id = next_order_id++;
        result.fill_price = 0;  // Pas encore rempli
        
        MockOrder order = {result.order_id, is_nq, 1, price, 0, 0, quantity, false, false};
        orders.push_back(order);
        
        return result;
    }
    
    OrderResult SellLimit(bool is_nq, float price, int quantity = 1) override {
        OrderResult result;
        result.success = true;
        result.order_id = next_order_id++;
        result.fill_price = 0;
        
        MockOrder order = {result.order_id, is_nq, -1, price, 0, 0, quantity, false, false};
        orders.push_back(order);
        
        return result;
    }
    
    OrderResult SendBracketOrder(bool is_nq, int direction, float entry_price,
                                 float sl_price, float tp_price, int quantity = 1) override {
        OrderResult result;
        result.success = true;
        result.order_id = next_order_id++;
        result.fill_price = entry_price;  // Simuler fill immédiat
        
        MockOrder order = {result.order_id, is_nq, direction, entry_price, sl_price, tp_price, quantity, true, false};
        orders.push_back(order);
        
        // Mettre à jour position
        SetPosition(is_nq, direction, entry_price, quantity);
        
        return result;
    }
    
    bool ModifyOrder(int order_id, float new_price) override {
        for (auto& order : orders) {
            if (order.order_id == order_id && !order.cancelled) {
                order.price = new_price;
                return true;
            }
        }
        return false;
    }
    
    bool CancelOrder(int order_id) override {
        for (auto& order : orders) {
            if (order.order_id == order_id && !order.filled) {
                order.cancelled = true;
                return true;
            }
        }
        return false;
    }
    
    bool CancelAllOrders(bool is_nq) override {
        for (auto& order : orders) {
            if (order.is_nq == is_nq && !order.filled) {
                order.cancelled = true;
            }
        }
        return true;
    }
    
    bool IsInPosition(bool is_nq) override { return is_nq ? nq_in_position : es_in_position; }
    int GetPositionDirection(bool is_nq) override { return is_nq ? nq_direction : es_direction; }
    float GetPositionEntryPrice(bool is_nq) override { return is_nq ? nq_entry : es_entry; }
    int GetPositionQuantity(bool is_nq) override { return is_nq ? nq_qty : es_qty; }
    
    OrderResult ClosePosition(bool is_nq) override {
        if (!IsInPosition(is_nq)) {
            OrderResult result;
            result.success = false;
            strncpy(result.error_message, "Not in position", sizeof(result.error_message) - 1);
            return result;
        }
        
        OrderResult result;
        if (GetPositionDirection(is_nq) == 1) {
            result = SellMarket(is_nq, GetPositionQuantity(is_nq));
        } else {
            result = BuyMarket(is_nq, GetPositionQuantity(is_nq));
        }
        
        SetPosition(is_nq, 0, 0, 0);
        return result;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: MockLogger
// ═══════════════════════════════════════════════════════════════════════════════

class MockLogger : public ILogger {
private:
    std::vector<std::string> logs;
    bool verbose;
    
public:
    MockLogger(bool verbose_mode = false) : verbose(verbose_mode) {}
    
    const std::vector<std::string>& GetLogs() const { return logs; }
    void ClearLogs() { logs.clear(); }
    void SetVerbose(bool v) { verbose = v; }
    
    void Log(LogLevel level, const char* message) override {
        const char* level_str[] = {"DEBUG", "INFO", "WARN", "ERROR", "CRIT"};
        char buffer[512];
        snprintf(buffer, sizeof(buffer), "[%s] %s", level_str[(int)level], message);
        logs.push_back(buffer);
        
        if (verbose) {
            printf("%s\n", buffer);
        }
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
        snprintf(buffer, sizeof(buffer), "SIGNAL %s %s: %s",
                symbol, direction == 1 ? "LONG" : "SHORT", reason);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogReject(const char* symbol, const char* layer, const char* reason) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "REJECT %s %s: %s", symbol, layer, reason);
        Log(LogLevel::DEBUG, buffer);
    }
    
    void LogTrade(const char* symbol, int direction, float entry, float sl, float tp) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "TRADE %s %s E=%.2f SL=%.2f TP=%.2f",
                symbol, direction == 1 ? "LONG" : "SHORT", entry, sl, tp);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogExit(const char* symbol, float exit_price, float pnl, const char* reason) override {
        char buffer[256];
        snprintf(buffer, sizeof(buffer), "EXIT %s @%.2f PnL=%.2f (%s)",
                symbol, exit_price, pnl, reason);
        Log(LogLevel::INFO, buffer);
    }
    
    void LogToFile(const char* filename, const char* message) override {
        // En mode mock, on ne fait rien avec les fichiers
        Log(LogLevel::DEBUG, message);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// IMPLÉMENTATION: MockTimeProvider
// ═══════════════════════════════════════════════════════════════════════════════

class MockTimeProvider : public ITimeProvider {
private:
    long long current_time_ms;
    int year, month, day, hour, minute, second;
    char session[16];
    bool trading_hours;
    int last_day;
    
public:
    MockTimeProvider() : current_time_ms(0), year(2026), month(1), day(31),
                         hour(10), minute(30), second(0),
                         trading_hours(true), last_day(-1) {
        strcpy(session, "US");
    }
    
    void SetTime(long long time_ms) { current_time_ms = time_ms; }
    void SetDateTime(int y, int m, int d, int h, int mi, int s) {
        year = y; month = m; day = d; hour = h; minute = mi; second = s;
    }
    void SetSession(const char* sess) { strncpy(session, sess, sizeof(session) - 1); }
    void SetTradingHours(bool is_open) { trading_hours = is_open; }
    
    // Avancer le temps de X millisecondes
    void AdvanceTime(long long ms) { current_time_ms += ms; }
    
    long long GetCurrentTimeMs() override { return current_time_ms; }
    
    void GetCurrentDateTime(int& y, int& m, int& d, int& h, int& mi, int& s) override {
        y = year; m = month; d = day; h = hour; mi = minute; s = second;
    }
    
    bool IsWithinTradingHours() override { return trading_hours; }
    
    bool IsNewDay() override {
        bool is_new = (day != last_day && last_day >= 0);
        last_day = day;
        return is_new;
    }
    
    const char* GetSessionName() override { return session; }
};

// ═══════════════════════════════════════════════════════════════════════════════
// FACTORY: Créer le contexte Mock
// ═══════════════════════════════════════════════════════════════════════════════

inline MIAContext CreateMockContext(bool verbose = false) {
    static MockStudyReader study_reader;
    static MockMarketDataProvider market_data;
    static MockOrderExecutor order_executor;
    static MockLogger logger(verbose);
    static MockTimeProvider time_provider;
    
    MIAContext ctx;
    ctx.study_reader = &study_reader;
    ctx.market_data = &market_data;
    ctx.order_executor = &order_executor;
    ctx.logger = &logger;
    ctx.time_provider = &time_provider;
    
    return ctx;
}

// Accès aux mocks pour configuration
inline MockMarketDataProvider* GetMockMarketData(MIAContext& ctx) {
    return dynamic_cast<MockMarketDataProvider*>(ctx.market_data);
}

inline MockOrderExecutor* GetMockOrderExecutor(MIAContext& ctx) {
    return dynamic_cast<MockOrderExecutor*>(ctx.order_executor);
}

inline MockLogger* GetMockLogger(MIAContext& ctx) {
    return dynamic_cast<MockLogger*>(ctx.logger);
}

inline MockTimeProvider* GetMockTimeProvider(MIAContext& ctx) {
    return dynamic_cast<MockTimeProvider*>(ctx.time_provider);
}