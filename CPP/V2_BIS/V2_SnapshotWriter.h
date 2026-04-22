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

    // Slippage reel (Sim3 ou live).
    // v1.4.3 (22/04 Plan R4) : calcule en AMONT par V2_OrderExec lors send ordre,
    // capture bid/ask mid comme expected_price puis diff avec fill_price :
    //   slippage_ticks = abs(fill_price - expected_mid_at_send) / tick_size
    double        expected_entry_price;  // mid bid/ask au moment send ordre entry
    double        expected_exit_price;   // mid bid/ask au moment send ordre exit
    double        slippage_ticks_entry;
    double        slippage_ticks_exit;

    // ML scores (snapshot seulement, PAS branch V2-bis).
    // v1.4.3 (22/04 Plan D3) : LogOnlyDouble wrapper compile-time safety pattern 11.
    // Impossible de faire `if (snap.score_combined < 0.5)` — compile error (pas d'operator<).
    // Serialize via `score_combined.value_for_log()` explicite (grep-able).
    LogOnlyDouble score_combined;
    LogOnlyDouble p_primary;
    LogOnlyDouble p_meta;

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

// Rejet snapshot (pour trades refuses par Risk/Session/staleness).
// v1.4.3 (22/04 Plan D5) : etendu 5 → 10 champs pour training negatives V3
// feedback loop : direction + sl_ticks + tp_ticks (distinguer refused SELL vs BUY
// avec contexte complet marche). features_hash_entry = reproductibilite signal.
struct RejectSnapshot {
    std::string   snapshot_version;      // "3.0" (parite TradeSnapshot)
    std::string   signal_id;
    int64_t       rejected_ts_ms;
    SymbolId      instrument;            // separer ES/NQ dans training V3
    std::string   rejection_reason;      // out_of_session | kill_switch_X | stale | dedup
    std::string   session_phase;

    // Signal intention (pour tagger "refused SELL NQ 20t SL")
    Direction     direction;
    int           sl_ticks;
    int           tp_ticks;

    // Contexte reproductibilite V3 retraining
    LogOnlyDouble score_combined;        // LOG ONLY (pattern 11 safe)
    double        atr_ticks_at_reject;
    std::string   features_hash_entry;
    std::string   model_version;
    std::string   v2bis_version;
    std::string   regime;                // trend_up | trend_dn | range | high_vol
};

// v1.4.3 (22/04 Plan D4) CONTRAT ROTATION TRANSACTIONNELLE :
// Si rotation minuit UTC echoue sur un des 2 fichiers (trades_out_ ou rejects_out_),
// ROLLBACK atomic : garder les 2 anciens handles ouverts. Sinon etat incoherent
// (trades_20260423 existe + rejects_20260422 ouvert) = rejets misrouted dans
// mauvaise date = dataset V3 pollue (viole data-quality.md regle souveraine).
// Pattern : ouvrir 2 NOUVEAUX fichiers AVANT fermer 2 anciens. Si open echoue
// sur l'un, close nouveau OK + garder anciens + log ERROR. Test :
// rotation_transactional_rollback_on_failure.
class V2SnapshotWriter {
public:
    V2SnapshotWriter(IConfigProvider& cfg, ITimeProvider& clock);
    ~V2SnapshotWriter();

    void write_trade(const TradeSnapshot& snap);
    void write_reject(const RejectSnapshot& rej);
    void flush();

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    std::ofstream    trades_out_;
    std::ofstream    rejects_out_;
    std::string      current_date_utc_;

    // v1.4.3 (Plan D4) : rotation lazy interne, transactionnelle (pas public).
    void ensure_files_open_for_today();

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
