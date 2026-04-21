// V2_SnapshotWriter.h — JSONL append ML V3-ready (feedback loop)
// ================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.9
// Statut : stub P0, implementation P1+
// LOC cible : ~280

#pragma once
#include "V2_Interfaces.h"
#include <filesystem>
#include <fstream>

namespace v2bis {

// 40+ champs versionnes par trade (design doc section 4.9)
struct TradeSnapshot {
    std::string   snapshot_version;    // "3.0"
    std::string   trade_id;
    std::string   signal_id;
    SymbolId      instrument;
    std::string   contract;

    int64_t       entry_ts_ms;
    double        entry_price;
    int64_t       exit_ts_ms;
    double        exit_price;
    Direction     direction;
    int           size_contracts;

    double        pnl_ticks;
    double        pnl_usd;
    TradeOutcome  outcome;             // TP | SL | TRAIL | BE | MANUAL | KILL | TIMEOUT
    int           duration_sec;

    // Slippage reel (Sim3 ou live)
    double        slippage_ticks_entry;
    double        slippage_ticks_exit;

    // ML scores (snapshot seulement, PAS branch V2-bis)
    double        score_combined;
    double        p_primary;
    double        p_meta;

    double        atr_ticks_at_entry;
    std::string   features_hash_entry;
    std::string   model_version;
    std::string   validator_version;
    std::string   v2bis_version;

    std::string   sc_session_id;       // "London" | "US"
    int           bars_held;

    double        max_favorable_excursion_ticks;
    double        max_adverse_excursion_ticks;

    bool          was_trailing_active;
    bool          was_be_hit;
    bool          kill_switch_triggered;

    std::string   regime;              // trend_up | trend_dn | range | high_vol
    // ... (10+ champs context regime complementaires)
};

// Rejet snapshot (pour trades refuses par Risk/Session/staleness)
struct RejectSnapshot {
    std::string   signal_id;
    int64_t       rejected_ts_ms;
    std::string   rejection_reason;    // out_of_session | kill_switch_X | stale | dedup
    std::string   session_phase;
    double        score_combined;
};

class V2SnapshotWriter {
public:
    V2SnapshotWriter(IConfigProvider& cfg, ITimeProvider& clock);
    ~V2SnapshotWriter();

    void write_trade(const TradeSnapshot& snap);
    void write_reject(const RejectSnapshot& rej);
    void rotate_if_new_day();
    void flush();

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    std::ofstream    trades_out_;
    std::ofstream    rejects_out_;
    std::string      current_date_utc_;

    std::filesystem::path trades_path_for(const std::string& date_utc) const;
    std::filesystem::path rejects_path_for(const std::string& date_utc) const;
};

} // namespace v2bis

// ─── Fichiers ───────────────────────────────────────────────────────
// Trades   : DATA/V2_BIS_SNAPSHOTS/snapshot_trades_YYYYMMDD.jsonl
// Rejects  : DATA/V2_BIS_SNAPSHOTS/snapshot_rejects_YYYYMMDD.jsonl
//
// ─── Garde-fou pattern 11 (Section 8.4 test #4) ─────────────────────
// V2_SnapshotWriter peut LIRE score_combined (pour logging) MAIS PAS
// BRANCHER dessus. Test statique CI :
//   grep -E "if.*score_combined|score_combined\s*[<>=]" V2_SnapshotWriter.h
//   → DOIT etre vide
//
// ─── Usage feedback loop V3 ─────────────────────────────────────────
// Input futur pour script Python CORE/v2bis_feedback.py (NON inclus P0)
// Developpe apres V2-bis paper 14 jours stable
// Re-training LightGBM V3 avec real fills + slippage reel
//
// ─── Tests cibles (6) ──────────────────────────────────────────────
//   trade_win_tp, trade_loss_sl, trail_hit, be_hit,
//   reject_session, reject_risk_kill
