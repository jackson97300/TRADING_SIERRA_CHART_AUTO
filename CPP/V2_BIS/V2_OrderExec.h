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

    // Entry principal : route selon signal.signal_kind UNIQUEMENT.
    // GARDE-FOU PATTERN 11 (v1.4.3 22/04) :
    //   execute() NE LIT JAMAIS s.score_combined / p_primary / p_meta.
    //   Route par switch(signal_kind) : ENTRY | EXIT_MANUAL | FLATTEN_ALL.
    //   Test statique CI (V2_Tests.cpp L107) : grep "score_combined\|p_primary\|p_meta" doit etre vide.
    //   Responsabilite log : execute() DOIT emettre journal_.log_event(ORDER_ERROR, payload)
    //   si result.ok=false (broker reject, ACK timeout). V2_Main ne re-log pas.
    //   (Plan agent STEP 5 Q4 Option B : journal_ deja injecte ligne 51, contexte riche ici).
    ExecutionResult execute(const Signal& s);

    // Callbacks fill/break
    void on_fill(int order_id, double fill_price);
    void on_sl_tp_hit(int order_id);

    // Update par bar : trailing + BE + orphelin detection
    // v1.4.3 (22/04) : prix lu en interne via market_ (IMarketDataProvider).
    // noexcept garantit que ES update ne peut PAS empecher NQ update (cf V2_Main dispatcher).
    // Gap #6 fix : DOIT etre appele meme si risk.allow_trade()=false (maintenance
    // positions ouvertes != nouveau trade). Chain of Gates filtre NOUVEAUX signaux,
    // pas maintenance (design doc section 4.1.1).
    void update_on_bar(SymbolId sym) noexcept;

    // Commands speciales (v1.4.3 22/04 : autorises MEME si risk.is_killed()=true).
    // Design doc section 7.8 (flatten=urgence news override) + 7.13 (exit_manual=
    // fermeture protective hors ML loop). Kill-switch bloque NOUVEAUX signaux entry,
    // PAS fermeture de positions existantes.
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
    // v1.4.3 22/04 : should_use_market() RETURN FALSE si bid<=0 OR ask<=0 (no quote).
    // Dans ce cas execute_entry() DOIT reject signal + log SIGNAL_REJECTED reason="no_market_quote".
    // PAS de fallback MARKET aveugle (risque fill 10+ ticks du last).
    ExecutionResult execute_entry(const Signal& s);
    bool            should_use_market(double entry_bid, double entry_ask) const;

    // OCO attach (ACSIL natif, pas DTC).
    // v1.4.3 (Plan agent STEP 5 Q1) : OCO ACSIL = 1 SEUL appel atomique
    // `sc.AddOCOOrderSubmitExtendedResponse` avec s_SCNewOrder contenant
    // Target1Price + Stop1Price. PAS 2 submit_limit_tp + submit_stop separes
    // (risque de 2 reponses desynchronisees → orphelin). IOrderExecutor
    // expose submit_stop/submit_limit_tp conceptuels, l'impl prod PACKE en 1 appel.
    ExecutionResult attach_oco(int parent_order_id, const Signal& s);

    // Trailing + BE
    // INVARIANT MONOTONIC (v1.4.3 22/04) : current_sl_price ne RECULE JAMAIS vers perte.
    //   LONG  : new_sl_price = max(trailing_state.current_sl_price, computed_sl)
    //   SHORT : new_sl_price = min(trailing_state.current_sl_price, computed_sl)
    // Test cible : trailing_update_monotonic (V2_Tests.cpp L97).
    // Assertion runtime dans impl P1 : assert(new_sl_better_or_equal_to_current).
    void update_trailing(int parent_order_id, double current_price);
    bool should_activate_trailing(const Position& pos, double current_price) const;
    bool should_hit_be(const Position& pos, double current_price) const;

    // Orphelin detection (SL/TP hit sans cancel oppose).
    // v1.4.3 22/04 : double call-site OBLIGATOIRE
    //   (1) dans on_sl_tp_hit() APRES cancel oppose (verification immediate post-cancel)
    //   (2) dans update_on_bar() periodique (rattrapage si on_sl_tp_hit callback rate)
    // Sans les 2 call-sites, ghost positions (1 cote ouvert, autre ferme) possibles.
    void detect_and_cancel_orphan(int parent_order_id);

    // Retry logic (erreur transient broker).
    // [TODO P1 specs] exponential backoff 100/200/400ms + max_retries config + jitter ±10%.
    // max_retries = runtime param via ExecutionConfig (pas template, cf Plan Q5 F3 REJECT).
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
