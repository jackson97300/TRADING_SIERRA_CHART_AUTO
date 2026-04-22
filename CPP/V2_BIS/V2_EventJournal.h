// V2_EventJournal.h — Tracer evenements structures
// ==================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.8
// Statut : stub P0, implementation P1+
// LOC cible : ~80

#pragma once
#include "V2_Interfaces.h"
#include <filesystem>
#include <fstream>
#include <string>

namespace v2bis {

class V2EventJournal : public IEventJournal {
public:
    // v1.4.3 (22/04 Plan D6) : constructor prend SymbolId pour fichier par instrument.
    // Chaque instance V2-bis (ES ou NQ) ecrit SON propre fichier — zero race cross-process,
    // grep post-mortem direct par instrument.
    V2EventJournal(IConfigProvider& cfg, ITimeProvider& clock, SymbolId instrument);
    ~V2EventJournal();

    // v1.4.3 (22/04 Plan D1) : payload nlohmann::json (design doc L535).
    // Zero malformed possible, zero double-escape. Serialize centralise.
    void log_event(EventType type, const nlohmann::json& payload) override;

    // v1.4.3 (22/04 Plan R2) : flush() appele par caller AVANT persist critique
    // (trigger_kill → flush → persist_atomic, garantit trace event avant crash possible).
    // PAS appele par log_event interne (perf — events rares : trades, rejets, kill).
    // Contrat : apres flush() return, event durable sur disque (fsync).
    void flush() override;

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    SymbolId         instrument_;        // v1.4.3 pour path per-instrument
    std::ofstream    out_;
    std::string      current_date_utc_;

    // v1.4.3 (22/04 Plan R3) : rotation LAZY atomique (pas rotate_if_new_day() public).
    // log_event check current_date_utc_ vs clock_.now_utc_date(), si different :
    // open new file FIRST, puis close ancien — pattern no-gap (pas window perte event).
    void ensure_current_file_open();

    std::filesystem::path build_path(const std::string& date_utc, SymbolId sym) const;
    std::string event_type_to_str(EventType type) const;
};

} // namespace v2bis

// ─── Format JSONL event (v1.4.3 payload typed) ──────────────────────
// {"ts_ms": 1776..., "type": "trade_open", "payload": {...}}
// payload = nlohmann::json serialize (pas string) → sub-objets typed,
// pas de double-escape "{\"reason\":\"X\"}".
//
// Types supportes (23 apres v1.4.3) :
//   trade_open, trade_close, trade_reject, signal_rejected,
//   kill_switch_trigger, session_transition,
//   v2clean_stale_warning, v2clean_down,
//   v2clean_zombie_warning, v2clean_zombie_blocking,
//   signal_received, signal_deduped, signal_stale,
//   order_error, daily_reset, dll_reload, state_restored,
//   flatten_all_noop, contract_mismatch, manual_exit_during_kill,
//   v2clean_heartbeat_missing, v2clean_clock_skew, heartbeat_io_error (v1.4.3)
//
// ─── Fichiers (v1.4.3 Plan D6 : per-instrument) ─────────────────────
// DATA/V2_BIS_JOURNAL/events_YYYYMMDD_ES.jsonl
// DATA/V2_BIS_JOURNAL/events_YYYYMMDD_NQ.jsonl
// Rotation : 1 fichier par jour UTC PAR instrument (lazy, atomic).
// Archive +30 jours.
//
// ─── Test statique CI (v1.4.3 Plan R4) ──────────────────────────────
// event_type_to_str : switch sans `default:`. Compiler flag -Werror=switch-enum
// sur ce fichier → ajout EventType sans update switch = compile error.
// Test CI : `grep "case EventType::" V2_EventJournal.cpp | wc -l == 23`.
//
// Tests cibles (6) :
//   append, rotation_jour_atomic, flush_fsync_durable, format_valide_json,
//   malformed_json_impossible (trivial avec nlohmann::json),
//   rotation_crash_resistant (pas de window perte event)
