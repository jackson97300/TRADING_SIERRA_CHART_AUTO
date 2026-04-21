// V2_Types.h — Structs et enums partages V2-bis
// ================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.4, 5.1
// Statut : stub P0, implementation P1+

#pragma once
#include <cstdint>
#include <string>

namespace v2bis {

// ─── Enums ──────────────────────────────────────────────────────────

enum class SymbolId {
    ES,
    NQ,
};

enum class Direction {
    BUY,
    SELL,
};

enum class SignalKind {
    ENTRY,         // nouvelle position
    EXIT_MANUAL,   // fermeture position specifique (referenced by parent_signal_id)
    FLATTEN_ALL,   // flatten toutes positions symbole (news FOMC, override)
};

enum class SessionPhase {
    ASIA,          // 18:00-03:00 ET
    LONDON_EARLY,  // 08:00-09:15 ET (MenthorQ levels publies)
    OPR_PAUSE,     // 09:15-10:00 ET (Opening Range Pause)
    US_RTH,        // 10:00-16:00 ET
    FLATTEN_WINDOW,// 15:55-16:00 ET (fermeture forcee positions ouvertes)
    CLOSED,
};

enum class KillReason {
    NONE,
    CATASTROPHE,   // P&L < -$850
    DAILY_LOSS,    // P&L < -$500
    INTRADAY_DD,   // peak-to-trough < -$300
    MAX_TRADES,    // > 5 trades/jour
};

enum class OrderError {
    NONE,
    ACK_TIMEOUT,
    BROKER_REJECT,
    POSITION_EXISTS,
    INVALID_PRICE,
};

// ─── Signal : contrat V2CLEAN Python → V2-bis C++ ──────────────────
// Schema JSONL v1.1 — 23 champs (design doc section 5.1)
struct Signal {
    int64_t     ts_ms;
    SymbolId    sym;
    std::string contract;                // ex: "NQM26-CME"
    double      bar_close_price;
    double      atr_ticks;

    SignalKind  signal_kind;             // entry | exit_manual | flatten_all

    double      score_combined;          // ML output (V2-bis ne branche PAS dessus)
    double      p_primary;
    double      p_meta;
    Direction   direction;
    int         sl_ticks;
    int         tp_ticks;
    int         size_contracts;          // sizing par V2CLEAN
    double      risk_budget_usd;         // budget max trade
    int         max_hold_bars;           // flatten zombie
    int         entry_window_sec;        // staleness threshold

    std::string regime;                  // pour snapshot (pas decision)
    std::string features_hash;           // audit-trail
    std::string model_version;
    std::string validator_version;
    std::string validator_baseline_version;
    std::string v2clean_version;
    std::string signal_id;               // UUID monotonic
    std::string parent_signal_id;        // pour exit_manual (optionnel)
};

// ─── RiskSignal : subset strippe pour V2_RiskManager ───────────────
// GARDE-FOU pattern 11 v1.1 : compilateur EMPECHE lecture score_* dans RiskManager.
// Strip par V2_Main avant appel allow_trade(RiskSignal).
// Design doc section 4.4 + 8.3
struct RiskSignal {
    SymbolId    sym;
    Direction   direction;
    int         sl_ticks;
    int         tp_ticks;
    int         size_contracts;
    double      risk_budget_usd;
    int64_t     signal_ts_ms;
    // PAS DE : score_combined, p_primary, p_meta, features_hash, atr_ticks
};

// ─── ExecutionResult ───────────────────────────────────────────────
struct ExecutionResult {
    bool          ok;
    int           parent_order_id;
    int           sl_order_id;
    int           tp_order_id;
    OrderError    error;
    std::string   error_message;
};

// ─── Position tracking ─────────────────────────────────────────────
struct Position {
    SymbolId     sym;
    Direction    direction;
    int          size_contracts;
    double       entry_price;
    int64_t      entry_ts_ms;
    int          bars_held;
    double       max_favorable_excursion_ticks;
    double       max_adverse_excursion_ticks;
    std::string  signal_id;
};

enum class TradeOutcome {
    TP,
    SL,
    TRAIL,
    BE,
    MANUAL,
    KILL,
    TIMEOUT,   // max_hold_bars atteint
};

// ─── HealthReport ──────────────────────────────────────────────────
struct HealthReport {
    bool        v2bis_alive;
    bool        v2clean_alive;
    int         seconds_since_v2clean_hb;
    int         seconds_since_v2clean_signal; // zombie detect
    double      cpu_pct;
    double      memory_mb;
};

// ─── EventType (journal structure) ─────────────────────────────────
enum class EventType {
    TRADE_OPEN,
    TRADE_CLOSE,
    TRADE_REJECT,
    SIGNAL_REJECTED,               // rejet pre-trade (session, staleness, dedup)
    KILL_SWITCH_TRIGGER,
    SESSION_TRANSITION,
    V2CLEAN_STALE_WARNING,
    V2CLEAN_DOWN,
    V2CLEAN_ZOMBIE_WARNING,
    V2CLEAN_ZOMBIE_BLOCKING,
    SIGNAL_RECEIVED,
    SIGNAL_DEDUPED,
    SIGNAL_STALE,
    ORDER_ERROR,
    DAILY_RESET,
    DLL_RELOAD,
    STATE_RESTORED,
    FLATTEN_ALL_NOOP,
    CONTRACT_MISMATCH,
    MANUAL_EXIT_DURING_KILL,
};

} // namespace v2bis
