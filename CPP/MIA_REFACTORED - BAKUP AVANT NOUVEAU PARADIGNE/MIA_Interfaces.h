#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Interfaces.h - INTERFACES ABSTRAITES POUR TESTS UNITAIRES
// ═══════════════════════════════════════════════════════════════════════════════
// 31/01/2026 - Découplage du code bot de l'API Sierra Chart
//
// But:
//   1. Permettre les tests unitaires SANS Sierra Chart
//   2. Simuler des scénarios de marché
//   3. Tester les Layers 1-4 en isolation
//   4. Faciliter le debugging
//
// Architecture:
//   IMarketDataProvider  -> Fournit prix, BN, MQ, VIX
//   IOrderExecutor       -> Exécute buy/sell/cancel
//   IStudyReader         -> Lit les données des études
//   ILogger              -> Log les événements
//
// Implémentations:
//   MIA_SierraImpl.h     -> Production (Sierra Chart)
//   MIA_MockImpl.h       -> Tests (données simulées)
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include <string>
#include <functional>

// ═══════════════════════════════════════════════════════════════════════════════
// INTERFACE: IStudyReader
// ═══════════════════════════════════════════════════════════════════════════════
// Lit les données des études Sierra Chart (ou données simulées en test)

class IStudyReader {
public:
    virtual ~IStudyReader() = default;
    
    // Lire une valeur d'étude (Study ID + Subgraph)
    virtual float ReadStudyValue(int chart_number, int study_id, int subgraph, int bar_index = -1) = 0;
    
    // Lire les données de base d'un chart (OHLCV)
    virtual float GetOpen(int chart_number, int bar_index = -1) = 0;
    virtual float GetHigh(int chart_number, int bar_index = -1) = 0;
    virtual float GetLow(int chart_number, int bar_index = -1) = 0;
    virtual float GetClose(int chart_number, int bar_index = -1) = 0;
    virtual float GetVolume(int chart_number, int bar_index = -1) = 0;
    
    // Nombre de barres disponibles
    virtual int GetArraySize(int chart_number) = 0;
    
    // Timestamp courant
    virtual long long GetCurrentTimestampMs() = 0;
    virtual void GetDateTime(int& year, int& month, int& day, int& hour, int& minute, int& second) = 0;
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTERFACE: IMarketDataProvider
// ═══════════════════════════════════════════════════════════════════════════════
// Fournit les données de marché complètes

class IMarketDataProvider {
public:
    virtual ~IMarketDataProvider() = default;
    
    // Prix courant
    virtual float GetCurrentPrice(bool is_nq) = 0;
    virtual float GetBid(bool is_nq) = 0;
    virtual float GetAsk(bool is_nq) = 0;
    virtual float GetSpread(bool is_nq) = 0;
    
    // Données Bataille Navale
    virtual BN_Data GetBatailleNavale(bool is_nq) = 0;
    
    // Données MenthorQ
    virtual MenthorQ_Data GetMenthorQ(bool is_nq) = 0;
    
    // Indicateurs globaux
    virtual float GetVIX() = 0;
    virtual int GetVIXRegime() = 0;
    virtual float GetATR(bool is_nq) = 0;
    virtual float GetCorrelationESNQ() = 0;
    
    // VWAP Slope
    virtual float GetVWAPSlope(bool is_nq) = 0;
    
    // DOM (Depth of Market)
    virtual int GetDOMBidQty(bool is_nq, int level = 0) = 0;
    virtual int GetDOMAskQty(bool is_nq, int level = 0) = 0;
    virtual float GetDepthImbalance(bool is_nq) = 0;
    
    // Session
    virtual const char* GetCurrentSession() = 0;
    virtual bool IsSessionOpen() = 0;
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTERFACE: IOrderExecutor
// ═══════════════════════════════════════════════════════════════════════════════
// Exécute les ordres de trading

struct OrderResult {
    bool success;
    int order_id;
    float fill_price;
    char error_message[128];
    
    OrderResult() : success(false), order_id(0), fill_price(0.0f) {
        error_message[0] = '\0';
    }
};

class IOrderExecutor {
public:
    virtual ~IOrderExecutor() = default;
    
    // Ordres Market
    virtual OrderResult BuyMarket(bool is_nq, int quantity = 1) = 0;
    virtual OrderResult SellMarket(bool is_nq, int quantity = 1) = 0;
    
    // Ordres Limit
    virtual OrderResult BuyLimit(bool is_nq, float price, int quantity = 1) = 0;
    virtual OrderResult SellLimit(bool is_nq, float price, int quantity = 1) = 0;
    
    // Ordres Bracket (Entry + SL + TP)
    virtual OrderResult SendBracketOrder(bool is_nq, int direction, float entry_price,
                                         float sl_price, float tp_price, int quantity = 1) = 0;
    
    // Modification/Annulation
    virtual bool ModifyOrder(int order_id, float new_price) = 0;
    virtual bool CancelOrder(int order_id) = 0;
    virtual bool CancelAllOrders(bool is_nq) = 0;
    
    // État position
    virtual bool IsInPosition(bool is_nq) = 0;
    virtual int GetPositionDirection(bool is_nq) = 0;  // 1=LONG, -1=SHORT, 0=FLAT
    virtual float GetPositionEntryPrice(bool is_nq) = 0;
    virtual int GetPositionQuantity(bool is_nq) = 0;
    
    // Fermer position
    virtual OrderResult ClosePosition(bool is_nq) = 0;
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTERFACE: ILogger
// ═══════════════════════════════════════════════════════════════════════════════
// Logging des événements

enum class LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARNING = 2,
    ERROR = 3,
    CRITICAL = 4
};

class ILogger {
public:
    virtual ~ILogger() = default;
    
    // Logging basique
    virtual void Log(LogLevel level, const char* message) = 0;
    virtual void LogFormat(LogLevel level, const char* format, ...) = 0;
    
    // Logging spécialisé trading
    virtual void LogSignal(const char* symbol, int direction, const char* reason) = 0;
    virtual void LogReject(const char* symbol, const char* layer, const char* reason) = 0;
    virtual void LogTrade(const char* symbol, int direction, float entry, float sl, float tp) = 0;
    virtual void LogExit(const char* symbol, float exit_price, float pnl, const char* reason) = 0;
    
    // Logging vers fichier
    virtual void LogToFile(const char* filename, const char* message) = 0;
    
    // Helpers
    void Debug(const char* msg) { Log(LogLevel::DEBUG, msg); }
    void Info(const char* msg) { Log(LogLevel::INFO, msg); }
    void Warning(const char* msg) { Log(LogLevel::WARNING, msg); }
    void Error(const char* msg) { Log(LogLevel::ERROR, msg); }
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTERFACE: ITimeProvider
// ═══════════════════════════════════════════════════════════════════════════════
// Gestion du temps (permet de simuler le temps en tests)

class ITimeProvider {
public:
    virtual ~ITimeProvider() = default;
    
    // Temps courant
    virtual long long GetCurrentTimeMs() = 0;
    virtual void GetCurrentDateTime(int& year, int& month, int& day, 
                                    int& hour, int& minute, int& second) = 0;
    
    // Helpers
    virtual bool IsWithinTradingHours() = 0;
    virtual bool IsNewDay() = 0;
    virtual const char* GetSessionName() = 0;  // "ASIA", "LONDON", "US"
};

// ═══════════════════════════════════════════════════════════════════════════════
// CONTENEUR D'INTERFACES (Dependency Injection)
// ═══════════════════════════════════════════════════════════════════════════════
// Permet d'injecter facilement les dépendances (production ou mock)

struct MIAContext {
    IStudyReader* study_reader;
    IMarketDataProvider* market_data;
    IOrderExecutor* order_executor;
    ILogger* logger;
    ITimeProvider* time_provider;
    
    MIAContext() : study_reader(nullptr), market_data(nullptr), 
                   order_executor(nullptr), logger(nullptr), time_provider(nullptr) {}
    
    bool IsValid() const {
        return study_reader != nullptr && market_data != nullptr && 
               order_executor != nullptr && logger != nullptr && time_provider != nullptr;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// FONCTIONS DE VALIDATION DES LAYERS (DÉCOUPLÉES)
// ═══════════════════════════════════════════════════════════════════════════════
// Ces fonctions peuvent être testées indépendamment avec des données mockées

// Layer 1: Validation niveau MenthorQ
inline Layer1Result ValidateLayer1_Testable(
    const MenthorQ_Data& mq,
    float current_price,
    const SymbolConfig& config,
    float momentum_score = 0.0f,
    const BN_Data* bn = nullptr,
    bool is_es = true
);

// Layer 2: Validation Bataille Navale + Corrélation
inline Layer2Result ValidateLayer2_Testable(
    int direction,
    const BN_Data& bn_primary,
    const BN_Data& bn_secondary,
    float vix,
    float vwap_slope,
    float buy_pct,
    float sell_pct,
    const SymbolConfig& config,
    bool is_nq,
    float depth_imbalance
);

// Layer 3: Validation Contexte
inline Layer3Result ValidateLayer3_Testable(
    int direction,
    const BN_Data& bn,
    float current_price,
    const MenthorQ_Data& mq,
    float vix,
    float atr,
    const char* session,
    bool is_nq
);

// Layer 4: Validation Combo Final
inline Layer4Result ValidateLayer4_Testable(
    int direction,
    float buy_pct,
    float sell_pct,
    float edge_buy,
    float edge_sell,
    float cum_delta,
    float bn_score,
    float vwap_slope,
    const SymbolConfig& config
);

// ═══════════════════════════════════════════════════════════════════════════════
// MACRO POUR FACILITER LES TESTS
// ═══════════════════════════════════════════════════════════════════════════════

#define MIA_TEST_ASSERT(condition, message) \
    if (!(condition)) { \
        printf("[TEST FAILED] %s: %s\n", __FUNCTION__, message); \
        return false; \
    }

#define MIA_TEST_ASSERT_FLOAT_EQ(expected, actual, tolerance, message) \
    if (fabs((expected) - (actual)) > (tolerance)) { \
        printf("[TEST FAILED] %s: %s (expected=%.4f, actual=%.4f)\n", \
               __FUNCTION__, message, (expected), (actual)); \
        return false; \
    }