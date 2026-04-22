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

// v1.4.3 (Plan agent STEP 5 Q1) : ARCHITECTURE 2 INSTANCES ES+NQ.
// ═══════════════════════════════════════════════════════════════════
// 2 SC Studies distincts (chart ES + chart NQ) construisent chacun 1 V2RiskManager.
// Partage etat via fichier atomic (V2_StatePersistence → risk_state.json)
// + Named Kernel Mutex Windows (serialisation writes cross-process).
// Design doc sections 7.9 + 11.2.
// Chaque instance = "owner partiel write-through" : modifie etat local, persiste
// sous mutex, re-read etat unifie avant decision allow_trade(). Compte AMP unique
// → daily_pnl AGREGE (ES+NQ closed pnl + open mtm partages).
//
// Intra-thread : ACSIL single-thread callback → pas de race.
// Inter-process ES vs NQ : mutex OBLIGATOIRE.
class V2RiskManager {
public:
    V2RiskManager(IConfigProvider& cfg,
                  IPersistence&    persistence,
                  IEventJournal&   journal,
                  ITimeProvider&   clock);

    // Interface principale : RiskSignal subset (pas Signal) → garde-fou pattern 11
    bool allow_trade(const RiskSignal& r);

    // on_trade_close : appele a fill TP/SL/manual close.
    // v1.4.3 responsabilite : increment trades_today + update daily_pnl realise.
    // NE fait PAS update peak (cf on_bar). NE fait PAS check_intraday_dd direct.
    void on_trade_close(double pnl_usd);

    // on_bar : appele chaque bar close via V2_Main dispatcher.
    // v1.4.3 responsabilite CRITIQUE :
    //   (1) update daily_pnl_peak_usd = max(peak, mtm_pnl_usd)
    //   (2) appeler check_intraday_dd() pour capture DD intra-position
    //   Sinon INTRADAY_DD declenche trop tard (seulement post trade-close),
    //   rate les swings -$300 pendant trade ouvert (cf code-reviewer R2).
    void on_bar(double mtm_pnl_usd);

    bool       is_killed() const;
    KillReason reason() const;

    // reset_session : v1.4.3 appele par V2_SessionGuard au daily_reset 09:30 ET
    // RTH US uniquement. PAS appele Asia/London (V2-bis ne trade pas hors RTH P0+P1,
    // cf memory project_v2clean_multi_session.md). Zero-out : daily_pnl, peak,
    // trades_today, killed_reason=NONE. consecutive_losses reset sur win OR daily_reset.
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

    // Checks individuels (split interne en P1 potentiel → V2_KillSwitch).
    // v1.4.3 ORDRE D'APPEL (priorite design doc 4.4) :
    //   check_catastrophe() → check_daily_loss() → check_intraday_dd() → check_max_trades()
    // Early-return au PREMIER true. KILL_SWITCH_TRIGGER event porte la reason PREDOMINANTE.
    // Escalation (DAILY_LOSS puis CATASTROPHE entre barres) = 2 events distincts
    // (2eme trigger_kill avec reason plus severe, verifier kill_triggered_ts_ms change).
    // Payload snapshot (daily_pnl=-870) capture contexte (implique DAILY_LOSS aussi).
    bool check_catastrophe();
    bool check_daily_loss();
    bool check_intraday_dd();
    bool check_max_trades();

    void persist_atomic();

    // trigger_kill : transition NONE→reason. Appele UNE SEULE FOIS par session
    // (aucun re-trigger tant que reset_session() non appele).
    // v1.4.3 (22/04) : DOIT emettre journal_.log_event(EventType::KILL_SWITCH_TRIGGER, ...)
    // AVANT persist_atomic() (flush journal avant state, sinon crash entre les 2 =
    // kill persiste sans trace event). Zero state dedup separe : la transition
    // elle-meme garantit log unique. V2_Main.cpp NE RELOGUE PAS kill_switch (consomme
    // juste risk.reason() pour skip nouveau trade, cf section 4.1.1 design doc).
    //
    // Escalation multi-reason (ex: DAILY_LOSS puis CATASTROPHE) : trigger_kill appele
    // 2 fois avec reasons differentes → 2 events KILL_SWITCH_TRIGGER distincts logges.
    // Test cible : kill_escalation_multi_trigger.
    void trigger_kill(KillReason reason);

    // Helper kill reason → JSON pour payload event (impl P1)
    static std::string kill_reason_to_json(KillReason reason);
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
