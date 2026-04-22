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
// v1.4.3 (22/04 Plan R2) : ajout set_datetime_utc() pour tests DST/weekend/holiday.
// Sans cela, tests `weekend_always_closed` + `dst_transition_handled` impossibles
// (now_ms_override=0 = 1970-01-01 jeudi, toujours).
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

    // v1.4.3 : set date complete (year, month, day, hour_et, minute_et).
    // Update now_ms_override coherent avec hour_et_override/minute_et_override.
    // Permet tests std::chrono::weekday (weekend) + holidays (2026-04-03 Good Friday).
    // Test usage : mock.set_datetime_utc(2026, 4, 3, 14, 30); // Vendredi Good Friday
    void set_datetime_utc(int year, int month, int day, int hour_et, int minute_et);
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

// ─── MockPersistence (v1.4.3 22/04 Plan D1+D2) ──────────────────────
// In-memory, signatures alignees sur IPersistence nlohmann::json + Result<T>.
// storage map key=path canonical, value=JSON serialize (string pour simplicite test).
class MockPersistence : public IPersistence {
public:
    std::unordered_map<std::string, std::string> storage;
    std::unordered_map<std::string, int>         schema_versions;  // v1.4.3 Plan R4

    // Simulators pour tests destructifs
    bool simulate_corruption{false};
    bool simulate_crash_mid_write{false};
    bool simulate_disk_full{false};
    bool simulate_permission_denied{false};

    Result<void>           write_json(const std::filesystem::path& target,
                                      const nlohmann::json& data) override;
    Result<nlohmann::json> read_json(const std::filesystem::path& target) override;
    Result<void>           backup_before_migration(const std::filesystem::path& target) override;
    Result<int>            read_schema_version(const std::filesystem::path& target) override;
};

// ─── MockEventJournal (v1.4.3 22/04 Plan D1) ────────────────────────
// Signature alignee IEventJournal nlohmann::json (pas string).
// events vector stocke payload serialise en string pour assertion helpers simples.
class MockEventJournal : public IEventJournal {
public:
    std::vector<std::pair<EventType, std::string>> events;
    int flush_count{0};  // v1.4.3 Plan R5 : tester que flush() appele aux moments clefs

    void log_event(EventType type, const nlohmann::json& payload) override;
    void flush() override;

    // Assertion helpers
    bool has_event(EventType type) const;
    int  count_events(EventType type) const;
    bool was_flushed() const { return flush_count > 0; }
};

// ─── MockSessionWindow (v1.4.3 22/04) ───────────────────────────────
// Mock minimal pour tests V2_HealthCheck sans dependance V2_SessionGuard concret.
class MockSessionWindow : public ISessionWindow {
public:
    bool rth_active_override{true};
    bool is_rth_active() const override { return rth_active_override; }
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
