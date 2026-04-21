// V2_OrderExec.h — OCO + Trailing + BE + Smart entry ACSIL natif
// ================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.3
// Statut : stub P0, implementation P1+
// LOC cible : ~450
// DNA V1 : OCO manuel valide 02/04/2026 (Type 208 x3 + cancel ServerOrderID)

#pragma once
#include "V2_Interfaces.h"
#include <unordered_map>

namespace v2bis {

struct TrailingState {
    bool    activated;
    double  best_price_since_entry;
    double  current_sl_price;
    bool    be_hit;
};

class V2OrderExec {
public:
    V2OrderExec(IConfigProvider&    cfg,
                IOrderExecutor&     executor,
                IMarketDataProvider& market,
                IEventJournal&      journal,
                ILogger&            logger,
                ITimeProvider&      clock);

    // Entry principal : route selon signal.signal_kind
    ExecutionResult execute(const Signal& s);

    // Callbacks fill/break
    void on_fill(int order_id, double fill_price);
    void on_sl_tp_hit(int order_id);

    // Update par bar : trailing + BE + orphelin detection
    void update_on_bar(SymbolId sym, double current_price);

    // Commands speciales
    void flatten_all(SymbolId sym);                         // signal_kind: flatten_all
    void close_position(const std::string& parent_signal_id); // signal_kind: exit_manual

    // Get positions pour V2_SnapshotWriter
    const Position* get_position(SymbolId sym) const;

private:
    IConfigProvider&     cfg_;
    IOrderExecutor&      executor_;
    IMarketDataProvider& market_;
    IEventJournal&       journal_;
    ILogger&             logger_;
    ITimeProvider&       clock_;

    std::unordered_map<int, Position>       positions_by_parent_id_;
    std::unordered_map<int, TrailingState>  trailing_by_parent_id_;

    // Smart entry (V1-inspired)
    ExecutionResult execute_entry(const Signal& s);
    bool            should_use_market(double entry_bid, double entry_ask) const;

    // OCO attach (ACSIL natif, pas DTC)
    ExecutionResult attach_oco(int parent_order_id, const Signal& s);

    // Trailing + BE
    void update_trailing(int parent_order_id, double current_price);
    bool should_activate_trailing(const Position& pos, double current_price) const;
    bool should_hit_be(const Position& pos, double current_price) const;

    // Orphelin detection (SL/TP hit sans cancel oppose)
    void detect_and_cancel_orphan(int parent_order_id);

    // Retry logic (erreur transient)
    ExecutionResult retry_with_backoff(int max_retries);
};

} // namespace v2bis

// ─── Logique smart entry (design doc section 4.3) ───────────────────
// Si dist_entry_bid > 3 ticks → LIMIT order
// Sinon                        → MARKET order
//
// ─── Logique OCO ACSIL (NOT DTC !) ──────────────────────────────────
// 1. Parent MARKET/LIMIT via sc.BuyEntry / sc.SellEntry
// 2. Attach SL STOP via sc.AddOCOOrderSubmitExtendedResponse
// 3. Attach TP LIMIT idem
// 4. Sierra Chart gere OCO natif (pas bug DTC OCOGroup1 V1)
// 5. on_sl_tp_hit cancel oppose auto
//
// ─── Trailing (V1 DNA) ──────────────────────────────────────────────
// Activation : profit > 0.5 * SL_ticks
// Distance   : ATR * 0.05
// BE hit     : profit > 0.3 * TP_ticks → SL moved to entry_price
//
// ─── Tests cibles (15) ──────────────────────────────────────────────
//   bracket_complet, fill_parent, fill_tp, fill_sl,
//   cancel_oppose_on_fill, trailing_update_monotonic,
//   be_hit_at_threshold, orphelin_detection,
//   smart_entry_limit_vs_market, retry_on_ack_timeout,
//   flatten_all_with_positions, flatten_all_no_positions (noop),
//   exit_manual_by_signal_id, exit_manual_during_kill,
//   STATIC: no_score_branching  ← grep CI pattern 11
