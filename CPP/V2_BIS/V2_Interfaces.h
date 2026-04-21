// V2_Interfaces.h — DI pour testabilite
// ========================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.11
// Statut : stub P0, implementation P1+
// LOC cible : ~280

#pragma once
#include "V2_Types.h"
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

// Note : inclure nlohmann/json via ACSIL standard include path P1
namespace nlohmann { class json; }

namespace v2bis {

// ─── IStudyReader : abstraction lecture barres SC ───────────────────
struct BarData {
    int64_t ts_ms;
    double  open, high, low, close;
    long    volume;
};

class IStudyReader {
public:
    virtual ~IStudyReader() = default;
    virtual int         n_bars() const = 0;
    virtual BarData     get_bar(int index) const = 0;
    virtual BarData     get_last_bar() const = 0;
    virtual double      get_atr_ticks() const = 0;
};

// ─── IMarketDataProvider : prix/volume temps reel ──────────────────
// GARDE-FOU pattern 11 : NE PAS injecter dans V2_SessionGuard.
class IMarketDataProvider {
public:
    virtual ~IMarketDataProvider() = default;
    virtual double current_price() const = 0;
    virtual double current_bid() const = 0;
    virtual double current_ask() const = 0;
    virtual long   current_volume() const = 0;
};

// ─── IOrderExecutor : abstraction ACSIL orders ─────────────────────
class IOrderExecutor {
public:
    virtual ~IOrderExecutor() = default;
    virtual int submit_market(SymbolId sym, Direction dir, int size) = 0;
    virtual int submit_limit(SymbolId sym, Direction dir, int size, double price) = 0;
    virtual int submit_stop(int parent_order_id, Direction dir, int size, double price) = 0;
    virtual int submit_limit_tp(int parent_order_id, Direction dir, int size, double price) = 0;
    virtual bool cancel(int order_id) = 0;
    virtual bool is_filled(int order_id) const = 0;
};

// ─── ILogger : abstraction log (console + fichier + Discord futur) ─
enum class LogLevel { DEBUG, INFO, WARNING, ERROR, CRITICAL };

class ILogger {
public:
    virtual ~ILogger() = default;
    virtual void log(LogLevel level, const std::string& msg) = 0;
};

// ─── ITimeProvider : horloge (pour time-travel tests) ──────────────
class ITimeProvider {
public:
    virtual ~ITimeProvider() = default;
    virtual int64_t now_ms() const = 0;
    virtual int     hour_et() const = 0;
    virtual int     minute_et() const = 0;
};

// ─── ISignalSource : lecture signal JSONL ──────────────────────────
// Impl reelle = V2_JSONLBridge.
class ISignalSource {
public:
    virtual ~ISignalSource() = default;
    virtual bool    poll(Signal& out_signal) = 0;  // true si nouveau signal dispo
    virtual bool    is_v2clean_alive() const = 0;
    virtual int     seconds_since_v2clean_hb() const = 0;
};

// ─── IPersistence : atomic file I/O (pour mock tests) ──────────────
class IPersistence {
public:
    virtual ~IPersistence() = default;
    virtual bool write_json(const std::filesystem::path& target, const void* data_ptr) = 0;
    virtual bool read_json(const std::filesystem::path& target, void* out_ptr) = 0;
    virtual bool backup_before_migration(const std::filesystem::path& target) = 0;
};

// ─── IEventJournal : tracer events ─────────────────────────────────
class IEventJournal {
public:
    virtual ~IEventJournal() = default;
    virtual void log_event(EventType type, const std::string& payload_json) = 0;
    virtual void flush() = 0;
};

// ─── IConfigProvider : injection config en test ────────────────────
struct PathConfig {
    std::filesystem::path ml_signal_jsonl;
    std::filesystem::path v2clean_heartbeat_json;
    std::filesystem::path state_dir;
    std::filesystem::path snapshot_dir;
    std::filesystem::path journal_dir;
};

struct RiskConfig {
    double catastrophe_usd;   // -850
    double daily_loss_usd;    // -500
    double intraday_dd_usd;   // -300
    int    max_trades;        // 5
    int    cooldown_sec;
    int    max_hold_bars_default;
};

struct SessionConfig {
    int    london_start_hm_et;  // 800
    int    london_end_hm_et;    // 915
    int    opr_pause_end_et;    // 1000
    int    us_rth_end_et;       // 1600
    int    flatten_window_min;  // 5 (= 15:55)
};

struct ExecutionConfig {
    int    smart_entry_threshold_ticks; // 3 (LIMIT vs MARKET)
    double trailing_activation_ratio;   // 0.5 * SL
    double trailing_distance_atr;       // 0.05 * ATR
    double be_activation_ratio;         // 0.3 * TP
};

struct HealthConfig {
    int    heartbeat_interval_sec;           // 1
    int    v2clean_stale_warning_sec;        // 30
    int    v2clean_stale_block_sec;          // 120
    int    v2clean_zombie_warning_min;       // 15
    int    v2clean_zombie_block_min;         // 30
};

class IConfigProvider {
public:
    virtual ~IConfigProvider() = default;
    virtual const PathConfig&      paths() const = 0;
    virtual const RiskConfig&      risk() const = 0;
    virtual const SessionConfig&   sessions() const = 0;
    virtual const ExecutionConfig& execution() const = 0;
    virtual const HealthConfig&    health() const = 0;
    virtual void                   reload_from_disk() = 0;
};

} // namespace v2bis
