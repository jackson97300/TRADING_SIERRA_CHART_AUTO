// V2_HealthCheck.h — Liveness + staleness + zombie detection
// ============================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.7 + 5.3
// Statut : stub P0, implementation P1+
// LOC cible : ~80

#pragma once
#include "V2_Interfaces.h"

namespace v2bis {

class V2HealthCheck {
public:
    V2HealthCheck(IConfigProvider& cfg,
                  IPersistence&    persistence,
                  IEventJournal&   journal,
                  ITimeProvider&   clock);

    // Appele a chaque bar close par V2_Main
    void tick(int bar_count, int last_signal_id_hash, bool is_killed);

    // V2CLEAN alive check (crash + zombie)
    bool is_v2clean_alive() const;
    bool is_v2clean_blocked() const;         // > 120s crash OR > 30 min zombie
    int  seconds_since_v2clean_hb() const;
    int  seconds_since_v2clean_signal() const;  // zombie

    HealthReport status() const;

private:
    IConfigProvider& cfg_;
    IPersistence&    persistence_;
    IEventJournal&   journal_;
    ITimeProvider&   clock_;

    int64_t last_v2clean_hb_ms_{0};
    int64_t last_v2clean_signal_ms_{0};
    bool    warned_stale_{false};
    bool    warned_zombie_{false};

    void write_v2bis_heartbeat(int bar_count, int last_signal_id_hash, bool is_killed);
    void read_v2clean_heartbeat();           // update last_v2clean_hb_ms_
};

} // namespace v2bis

// ─── Logique crash detection ────────────────────────────────────────
// Si (now - last_v2clean_hb_ms) > 30s  → journal v2clean_stale_warning
// Si (now - last_v2clean_hb_ms) > 120s → block signals, journal v2clean_down
//
// ─── Logique zombie detection (process alive mais muet) ─────────────
// Si (now - last_v2clean_signal_ms) > 15 min ET RTH active → journal v2clean_zombie_warning
// Si (now - last_v2clean_signal_ms) > 30 min en RTH       → block signals, journal v2clean_zombie_blocking
//
// V2-bis continue de gerer SL/TP/trailing positions OUVERTES meme si V2CLEAN down/zombie.
//
// Tests cibles (6) :
//   heartbeat_ok, v2clean_down_30s_alert, v2clean_down_120s_block,
//   file_missing, telemetry_overflow, reboot_recovery
