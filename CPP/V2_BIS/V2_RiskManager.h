// V2_RiskManager.h — Port V2CLEAN/risk/risk_manager.py (716 LOC)
// ================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.4
// Statut : stub P0, implementation P1+
// LOC cible : ~450
//
// GARDE-FOU PATTERN 11 (CRITIQUE v1.1) :
// ═══════════════════════════════════════
// allow_trade() recoit RiskSignal (subset) PAS Signal complet.
// Compilateur EMPECHE lecture score_combined, p_primary, p_meta, features_hash.
// Test statique CI verifie absence de ces champs dans ce fichier.

#pragma once
#include "V2_Interfaces.h"

namespace v2bis {

// Kill-switch hierarchie 4 niveaux (design doc section 4.4) :
//   1. CATASTROPHE : P&L journee < -$850 → flatten all + stop trading
//   2. DAILY_LOSS  : P&L journee < -$500 → stop trading jour
//   3. INTRADAY_DD : peak-to-trough < -$300 → stop trading jour
//   4. MAX_TRADES  : > 5 trades/jour → stop trading jour

struct RiskState {
    double    daily_pnl_usd;
    double    daily_pnl_peak_usd;        // pour intraday DD
    int       trades_today;
    KillReason killed_reason;
    int64_t   session_start_ts_ms;
    int       consecutive_losses;
};

class V2RiskManager {
public:
    V2RiskManager(IConfigProvider& cfg,
                  IPersistence&    persistence,
                  IEventJournal&   journal,
                  ITimeProvider&   clock);

    // Interface principale : RiskSignal subset (pas Signal) → garde-fou pattern 11
    bool allow_trade(const RiskSignal& r);

    // Appele a chaque trade ferme
    void on_trade_close(double pnl_usd);

    // Appele a chaque bar (update mark-to-market peak/trough)
    void on_bar(double mtm_pnl_usd);

    bool       is_killed() const;
    KillReason reason() const;

    // Reset daily (appele a daily_reset debut RTH)
    void reset_session();

    // Snapshot pour persistence
    RiskState state() const;
    void      restore(const RiskState& s);

private:
    IConfigProvider& cfg_;
    IPersistence&    persistence_;
    IEventJournal&   journal_;
    ITimeProvider&   clock_;

    RiskState state_{};

    // Checks individuels (split interne en P1 potentiel → V2_KillSwitch)
    bool check_catastrophe();
    bool check_daily_loss();
    bool check_intraday_dd();
    bool check_max_trades();

    void persist_atomic();
    void trigger_kill(KillReason reason);
};

} // namespace v2bis

// ─── Persistance ────────────────────────────────────────────────────
// Etat via V2_StatePersistence → V2_BIS_STATE/risk_state.json (atomic)
// Restore au demarrage V2-bis (survie restart SC)
//
// ─── Named Kernel Mutex (Windows) pour race ES vs NQ ────────────────
// Design doc section 7.9 : mutex + fichier co-existent
// ES et NQ partagent kill-switch (compte unique AMP)
// Pattern : mutex.lock() → StatePersistence.write_json() → mutex.unlock()
//
// ─── Tests cibles (12) ──────────────────────────────────────────────
//   peak_drop_intraday_dd, loss_only_daily, catastrophe_priority,
//   max_trades_hit, reset_session, persistence_roundtrip,
//   restore_after_crash, concurrent_es_nq_mutex,
//   STATIC: no_score_combined, STATIC: no_p_primary,
//   STATIC: no_p_meta, STATIC: no_features_hash
