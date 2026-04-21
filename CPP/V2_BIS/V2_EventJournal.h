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
    explicit V2EventJournal(IConfigProvider& cfg, ITimeProvider& clock);
    ~V2EventJournal();

    void log_event(EventType type, const std::string& payload_json) override;
    void flush() override;

    // Rotation quotidienne UTC
    void rotate_if_new_day();

private:
    IConfigProvider& cfg_;
    ITimeProvider&   clock_;
    std::ofstream    out_;
    std::string      current_date_utc_;

    std::filesystem::path build_path(const std::string& date_utc) const;
    std::string event_type_to_str(EventType type) const;
};

} // namespace v2bis

// ─── Format JSONL event ─────────────────────────────────────────────
// {"ts_ms": 1776..., "type": "trade_open", "payload": {...}}
//
// Types supportes (20) :
//   trade_open, trade_close, trade_reject, signal_rejected,
//   kill_switch_trigger, session_transition,
//   v2clean_stale_warning, v2clean_down,
//   v2clean_zombie_warning, v2clean_zombie_blocking,
//   signal_received, signal_deduped, signal_stale,
//   order_error, daily_reset, dll_reload, state_restored,
//   flatten_all_noop, contract_mismatch, manual_exit_during_kill
//
// Fichiers : DATA/V2_BIS_JOURNAL/events_YYYYMMDD.jsonl
// Rotation : 1 fichier par jour UTC. Archive +30 jours.
//
// Tests cibles (4) : append, rotation_jour, flush, format_valide
