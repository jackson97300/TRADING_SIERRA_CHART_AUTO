// V2_JSONLBridge.h — File watch ml_signal.jsonl + dedup cross-restart
// ====================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.2 + 5.1 + 5.2
// Statut : stub P0, implementation P1+
// LOC cible : ~280

#pragma once
#include "V2_Interfaces.h"
#include <deque>
#include <string>
#include <unordered_set>

namespace v2bis {

class V2JSONLBridge : public ISignalSource {
public:
    V2JSONLBridge(IConfigProvider& cfg,
                  IPersistence&    persistence,
                  IEventJournal&   journal,
                  ITimeProvider&   clock);

    // ISignalSource
    bool poll(Signal& out_signal) override;
    bool is_v2clean_alive() const override;
    int  seconds_since_v2clean_hb() const override;

    // Pour V2_HealthCheck injection de la logique zombie
    void set_health_check(class V2HealthCheck* hc);

private:
    IConfigProvider&     cfg_;
    IPersistence&        persistence_;
    IEventJournal&       journal_;
    ITimeProvider&       clock_;
    class V2HealthCheck* health_check_{nullptr};

    // Dedup cross-restart : ring buffer 300 signal_id (design doc section 5.2)
    // Justification : 2 signaux/min × 60 × 4h worst case = 480, marge x2 = 300 = 2.5h
    // Persiste via V2_StatePersistence → V2_BIS_STATE/signal_dedup.json
    std::deque<std::string>       dedup_buffer_;
    std::unordered_set<std::string> dedup_set_;
    static constexpr int          DEDUP_CAPACITY = 300;

    int64_t last_file_read_offset_{0};

    bool parse_line(const std::string& line, Signal& out);
    bool is_duplicate(const std::string& signal_id) const;
    void add_to_dedup(const std::string& signal_id);
    void persist_dedup();
    void restore_dedup();
    bool is_stale(const Signal& s) const;     // ts + entry_window_sec
};

} // namespace v2bis

// ─── Contrat V2CLEAN Python → V2-bis ────────────────────────────────
// Chemin : ML_SIGNAL/ml_signal.jsonl
// Polling : 100ms
// Rotation quotidienne (ml_signal_YYYYMMDD.jsonl + symlink ml_signal.jsonl)
// Schema : voir V2_Types.h struct Signal (23 champs)
//
// ─── Logique poll() ─────────────────────────────────────────────────
// 1. Check HealthCheck : si V2CLEAN down/zombie → return false (pas de signaux)
// 2. Read tail nouveau du fichier depuis last_file_read_offset_
// 3. Pour chaque ligne : parse JSON → Signal
// 4. Verifier signal_kind ∈ {entry, exit_manual, flatten_all}
// 5. Si ts + entry_window_sec < now → log signal_stale, skip
// 6. Si signal_id in dedup_buffer → log signal_deduped, skip
// 7. Sinon → add_to_dedup + return true avec Signal
//
// Signal types :
//   entry       : nouveau trade (check Session + Risk avant execute)
//   exit_manual : ferme position specifique (kill-switch actif OK)
//   flatten_all : ferme toutes positions symbole (news FOMC, override)
//
// ─── Tests cibles (8) ────────────────────────────────────────────────
//   file_absent, line_malformee, staleness, dedup_cross_restart,
//   parsing_ok, hash_log, multiple_signals, file_rotation
