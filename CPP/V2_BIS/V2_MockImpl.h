// V2_MockImpl.h — Mocks 9 interfaces pour tests Catch2
// =======================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.12
// Statut : stub P0, implementation P1+
// LOC cible : ~350
// DNA V1 : scaffolding MIA_MockImpl.h V1_refactored adapte

#pragma once
#include "V2_Interfaces.h"
#include <vector>
#include <string>
#include <unordered_map>

namespace v2bis {
namespace mock {

// ─── MockStudyReader ────────────────────────────────────────────────
class MockStudyReader : public IStudyReader {
public:
    std::vector<BarData> bars;
    double               atr_ticks_override{100.0};

    int      n_bars() const override;
    BarData  get_bar(int index) const override;
    BarData  get_last_bar() const override;
    double   get_atr_ticks() const override;
};

// ─── MockMarketDataProvider ─────────────────────────────────────────
class MockMarketDataProvider : public IMarketDataProvider {
public:
    double price_override{0.0};
    double bid_override{0.0};
    double ask_override{0.0};
    long   volume_override{0};

    double current_price() const override;
    double current_bid() const override;
    double current_ask() const override;
    long   current_volume() const override;
};

// ─── MockOrderExecutor ──────────────────────────────────────────────
class MockOrderExecutor : public IOrderExecutor {
public:
    struct OrderLog {
        int         order_id;
        SymbolId    sym;
        Direction   dir;
        int         size;
        double      price;
        std::string type; // "MARKET" | "LIMIT" | "STOP"
        bool        is_filled;
    };
    std::vector<OrderLog> order_log;
    int                   next_order_id{1000};

    int  submit_market(SymbolId sym, Direction dir, int size) override;
    int  submit_limit(SymbolId sym, Direction dir, int size, double price) override;
    int  submit_stop(int parent, Direction dir, int size, double price) override;
    int  submit_limit_tp(int parent, Direction dir, int size, double price) override;
    bool cancel(int order_id) override;
    bool is_filled(int order_id) const override;

    // Assertion helpers tests
    bool has_order_with_type(const std::string& type) const;
    int  count_orders_for(SymbolId sym) const;
};

// ─── MockLogger ─────────────────────────────────────────────────────
class MockLogger : public ILogger {
public:
    std::vector<std::pair<LogLevel, std::string>> logs;
    void log(LogLevel level, const std::string& msg) override;

    bool has_log_containing(const std::string& substring) const;
    int  count_logs(LogLevel level) const;
};

// ─── MockTimeProvider ───────────────────────────────────────────────
class MockTimeProvider : public ITimeProvider {
public:
    int64_t now_ms_override{0};
    int     hour_et_override{0};
    int     minute_et_override{0};

    int64_t now_ms() const override;
    int     hour_et() const override;
    int     minute_et() const override;

    // Time travel deterministe
    void advance_ms(int64_t delta_ms);
    void set_et_time(int hour, int minute);
};

// ─── MockSignalSource ───────────────────────────────────────────────
class MockSignalSource : public ISignalSource {
public:
    std::vector<Signal> pending_signals;
    bool                v2clean_alive_override{true};
    int                 seconds_since_hb_override{0};

    bool poll(Signal& out_signal) override;
    bool is_v2clean_alive() const override;
    int  seconds_since_v2clean_hb() const override;
};

// ─── MockPersistence (NEW v1.1) ─────────────────────────────────────
class MockPersistence : public IPersistence {
public:
    // In-memory storage (pas I/O reel)
    std::unordered_map<std::string, std::string> storage;
    bool simulate_corruption{false};
    bool simulate_crash_mid_write{false};

    bool write_json(const std::filesystem::path& target, const void* data_ptr) override;
    bool read_json(const std::filesystem::path& target, void* out_ptr) override;
    bool backup_before_migration(const std::filesystem::path& target) override;
};

// ─── MockEventJournal (NEW v1.1) ────────────────────────────────────
class MockEventJournal : public IEventJournal {
public:
    std::vector<std::pair<EventType, std::string>> events;

    void log_event(EventType type, const std::string& payload_json) override;
    void flush() override;

    // Assertion helpers
    bool has_event(EventType type) const;
    int  count_events(EventType type) const;
};

// ─── MockConfigProvider (NEW v1.1) ──────────────────────────────────
class MockConfigProvider : public IConfigProvider {
public:
    PathConfig      paths_override;
    RiskConfig      risk_override;
    SessionConfig   sessions_override;
    ExecutionConfig execution_override;
    HealthConfig    health_override;

    const PathConfig&      paths() const override;
    const RiskConfig&      risk() const override;
    const SessionConfig&   sessions() const override;
    const ExecutionConfig& execution() const override;
    const HealthConfig&    health() const override;
    void                   reload_from_disk() override;
};

} // namespace mock
} // namespace v2bis

// ─── Pattern usage tests ────────────────────────────────────────────
// auto cfg = v2bis::mock::MockConfigProvider{};
// cfg.risk_override.catastrophe_usd = -850;
// auto clock = v2bis::mock::MockTimeProvider{};
// clock.set_et_time(10, 30);
// ...
// V2RiskManager rm(cfg, persistence, journal, clock);
// REQUIRE(rm.allow_trade(signal_mock) == true);
//
// ─── Tests mocks cibles ────────────────────────────────────────────
// (inclus dans comptes modules metier)
