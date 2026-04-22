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
// v1.4.2 : ajout max_hold_bars (review code-reviewer 21/04)
RiskSignal strip_to_risk_signal(const Signal& s) {
    RiskSignal r;
    r.sym              = s.sym;
    r.direction        = s.direction;
    r.sl_ticks         = s.sl_ticks;
    r.tp_ticks         = s.tp_ticks;
    r.size_contracts   = s.size_contracts;
    r.risk_budget_usd  = s.risk_budget_usd;
    r.signal_ts_ms     = s.ts_ms;
    r.max_hold_bars    = s.max_hold_bars;
    // NE PAS COPIER : score_combined, p_primary, p_meta, features_hash, atr_ticks
    // PAS COPIER : entry_window_sec (staleness gere par V2_JSONLBridge pre-gate)
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
    // [TODO P1 v1.4.2] last_signal_hash=0 placeholder. En P1, tick APRES
    // consommation signal pour remonter le hash (monitoring externe).
    health.tick(bar_count, /*last_signal_hash*/ 0, risk.is_killed());

    // STEP 1.5 : Update risk mark-to-market (v1.4.3 22/04 fix C1 validateur)
    // CRITIQUE : sans ce cablage, risk.on_bar() n'est jamais appele → peak jamais
    // update → INTRADAY_DD ne trigger JAMAIS pendant trade ouvert (motif de la methode
    // elle-meme, cf code-reviewer V2_RiskManager R2).
    // [TODO P1] mtm_pnl_usd = daily_pnl_realized + unrealized(open_positions × current_prices).
    //          Calcul via order_exec.get_position() + market_.current_price() (cross-module).
    //          Stub P0 : placeholder 0.0 (risk.on_bar update peak = realized only).
    risk.on_bar(/*mtm_pnl_usd placeholder P0*/ 0.0);

    // STEP 1.6 : Daily reset (v1.4.3 22/04 fix C2 validateur)
    // [TODO P1] appeler risk.reset_session() a la transition overnight → RTH open
    // (detection via V2_SessionGuard current_phase() changement CLOSED → US_RTH a 09:30 ET).
    // Stub P0 : pas encore cable. Impl P1 via session_guard.just_opened_rth() getter + test.

    if (!health.is_v2clean_alive() && health.is_v2clean_blocked()) {
        // V2CLEAN down : pas de nouveau signal, mais gere positions ouvertes.
        // v1.4.3 (22/04) : update_on_bar(sym) lit prix via IMarketDataProvider interne.
        // Philosophie : continuer trailing SL/TP > flatten (eviter TP rate force).
        order_exec.update_on_bar(SymbolId::ES);
        order_exec.update_on_bar(SymbolId::NQ);
        return;
    }

    // STEP 2 : Poll signal
    Signal signal;
    if (!bridge.poll(signal)) {
        // Pas de nouveau signal : maintenance positions ouvertes
        order_exec.update_on_bar(SymbolId::ES);
        order_exec.update_on_bar(SymbolId::NQ);
        return;
    }

    // STEP 3 : Session (fast-path rejection si hors heures)
    if (!session_guard.is_trading_window()) {
        journal.log_event(EventType::SIGNAL_REJECTED,
                          "{\"reason\": \"out_of_session\"}");
        // Gap #6 fix (22/04) : maintenir trailing meme si signal rejete hors session
        order_exec.update_on_bar(SymbolId::ES);
        order_exec.update_on_bar(SymbolId::NQ);
        return;
    }

    // STEP 4 : Risk (strip Signal → RiskSignal, compilateur empeche score_*)
    RiskSignal rs = strip_to_risk_signal(signal);
    if (!risk.allow_trade(rs)) {
        // v1.4.3 Gap #5 fix : distinguer rejet kill-switch vs ponctuel.
        //   - Kill-switch : deja logge UNIQUE par V2_RiskManager.trigger_kill()
        //     lors de la transition NONE→reason. Le dispatcher NE RELOGUE PAS
        //     a chaque barre (evite spam 330+ events par session).
        //   - Rejet ponctuel (NONE) : cooldown, ATR bounds, max_trades_future
        //     potentiel, etc. Log normal TRADE_REJECT (1 signal = 1 reject max).
        if (risk.reason() == KillReason::NONE) {
            journal.log_event(EventType::TRADE_REJECT,
                              "{\"reason\": \"pre_trade_check\"}");
        }
        // Gap #6 fix : maintenir trailing sur positions ouvertes AVANT return.
        // Kill-switch = bloquer NOUVEAU trade, PAS abandonner positions existantes.
        // Trailing SL qui bouge vers profit REDUIT le risque, jamais l'augmente.
        order_exec.update_on_bar(SymbolId::ES);
        order_exec.update_on_bar(SymbolId::NQ);
        return;
    }

    // STEP 5 : Execute (seule action irreversible, route selon signal_kind).
    // v1.4.3 (Plan agent STEP 5 V2_OrderExec Q4 Option B) : le log structure
    // ORDER_ERROR est emit PAR V2_OrderExec::execute() (journal_ injecte + contexte
    // riche broker error). Le dispatcher garde juste awareness dispatcher-level
    // (pour debug si ExecutionResult.ok=false revient sans trace journal).
    ExecutionResult result = order_exec.execute(signal);
    if (!result.ok) {
        // Dispatcher-level awareness : impl P1 peut ajouter logger.log(WARN, ...)
        // si ExecutionResult.error != NONE. Journal structure reste execute().
    }
    // TradeSnapshot ecrit quand position fermee (dans V2_OrderExec.on_sl_tp_hit)
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
