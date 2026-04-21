// V2_Main.cpp — Dispatcher ACSIL + Chain of Gates
// ==================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.1 + 4.1.1
// Statut : stub P0, implementation P1+
// LOC cible : ~200

#include "V2_Types.h"
#include "V2_Interfaces.h"
#include "V2_Config.h"
#include "V2_StatePersistence.h"
#include "V2_HealthCheck.h"
#include "V2_EventJournal.h"
#include "V2_SessionGuard.h"
#include "V2_RiskManager.h"
#include "V2_JSONLBridge.h"
#include "V2_OrderExec.h"
#include "V2_SnapshotWriter.h"

// Sierra Chart ACSIL header (std in SC projects)
// #include "sierrachart.h"  // available in VPS SC build env

namespace v2bis {

// ─── Strip Signal → RiskSignal (garde-fou pattern 11) ──────────────
// Design doc section 4.4 + 8.3
RiskSignal strip_to_risk_signal(const Signal& s) {
    RiskSignal r;
    r.sym              = s.sym;
    r.direction        = s.direction;
    r.sl_ticks         = s.sl_ticks;
    r.tp_ticks         = s.tp_ticks;
    r.size_contracts   = s.size_contracts;
    r.risk_budget_usd  = s.risk_budget_usd;
    r.signal_ts_ms     = s.ts_ms;
    // NE PAS COPIER : score_combined, p_primary, p_meta, features_hash, atr_ticks
    return r;
}

// ─── Chain of Gates (section 4.1.1) ─────────────────────────────────
// Ordre NON-NEGOCIABLE :
//   1. HealthCheck V2CLEAN (block si down/zombie, mais garde positions ouvertes)
//   2. Poll signal (dedup + staleness)
//   3. Session (time-based pure, pas market data)
//   4. Risk (RiskSignal subset, pas de score visible)
//   5. Execute (seule action irreversible)

void on_bar_close_dispatcher(V2HealthCheck&      health,
                             V2JSONLBridge&      bridge,
                             V2SessionGuard&     session_guard,
                             V2RiskManager&      risk,
                             V2OrderExec&        order_exec,
                             V2SnapshotWriter&   snapshot,
                             V2EventJournal&     journal,
                             int                 bar_count) {

    // STEP 1 : HealthCheck tick (update heartbeat V2-bis + read V2CLEAN hb)
    health.tick(bar_count, /*last_signal_hash*/ 0, risk.is_killed());

    if (!health.is_v2clean_alive() && health.is_v2clean_blocked()) {
        // V2CLEAN down : pas de nouveau signal, mais gere positions ouvertes
        order_exec.update_on_bar(SymbolId::ES, /*current_price*/ 0.0);
        order_exec.update_on_bar(SymbolId::NQ, /*current_price*/ 0.0);
        return;
    }

    // STEP 2 : Poll signal
    Signal signal;
    if (!bridge.poll(signal)) {
        // Pas de nouveau signal : juste update positions ouvertes
        order_exec.update_on_bar(SymbolId::ES, /*current_price*/ 0.0);
        order_exec.update_on_bar(SymbolId::NQ, /*current_price*/ 0.0);
        return;
    }

    // STEP 3 : Session (fast-path rejection si hors heures)
    if (!session_guard.is_trading_window()) {
        journal.log_event(EventType::SIGNAL_REJECTED,
                          "{\"reason\": \"out_of_session\"}");
        return;
    }

    // STEP 4 : Risk (strip Signal → RiskSignal, compilateur empeche score_*)
    RiskSignal rs = strip_to_risk_signal(signal);
    if (!risk.allow_trade(rs)) {
        journal.log_event(EventType::TRADE_REJECT,
                          "{\"reason\": \"risk_killed\"}");
        // Snapshot reject pour feedback loop V3
        // snapshot.write_reject(...)
        return;
    }

    // STEP 5 : Execute (seule action irreversible, route selon signal_kind)
    ExecutionResult result = order_exec.execute(signal);
    // TradeSnapshot ecrit quand position fermee (dans V2_OrderExec.on_sl_tp_hit)
    (void)result;
}

} // namespace v2bis

// ─── ACSIL Study entry point (Sierra Chart convention) ─────────────
// SCSFExport void scsf_V2_Bis(SCStudyInterfaceRef sc) {
//   ... initialization (first run)
//   ... bar close detection
//   ... dispatch to v2bis::on_bar_close_dispatcher(...)
// }
//
// ─── Tests cibles (5) ──────────────────────────────────────────────
//   bar_open_no_signal, bar_close_signal_present,
//   signal_absent_manage_positions, kill_switch_triggered,
//   chain_of_gates_order_respected
