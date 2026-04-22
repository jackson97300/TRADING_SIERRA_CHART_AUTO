// V2_HealthCheck.h — Liveness + staleness + zombie detection
// ============================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.7 + 5.3
// Statut : stub P0, implementation P1+
// LOC cible : ~80

#pragma once
#include "V2_Interfaces.h"
#include <optional>

namespace v2bis {

class V2HealthCheck {
public:
    // v1.4.3 (22/04 Plan Q1) : ISessionWindow injecte pour zombie RTH detection
    // sans couplage concret V2_SessionGuard (testable mock).
    V2HealthCheck(IConfigProvider& cfg,
                  IPersistence&    persistence,
                  IEventJournal&   journal,
                  ITimeProvider&   clock,
                  ISessionWindow&  session_window);

    // Appele a chaque bar close par V2_Main.
    // v1.4.3 : is_rth lu via session_window_ interne (pas param).
    // last_signal_id_hash ecrit dans v2bis_heartbeat.json pour monitoring externe.
    void tick(int bar_count, int last_signal_id_hash, bool is_killed);

    // V2CLEAN alive check (crash + zombie)
    bool is_v2clean_alive() const;
    bool is_v2clean_blocked() const;         // > 120s crash OR > 30 min zombie (RTH)
    int  seconds_since_v2clean_hb() const;
    int  seconds_since_v2clean_signal() const;  // zombie

    HealthReport status() const;

private:
    IConfigProvider& cfg_;
    IPersistence&    persistence_;
    IEventJournal&   journal_;
    ITimeProvider&   clock_;
    ISessionWindow&  session_window_;  // v1.4.3 RTH detection sans couplage concret

    int64_t last_v2clean_hb_ms_{0};
    int64_t last_v2clean_signal_ms_{0};
    int     last_v2clean_pid_{-1};     // v1.4.3 detecter re-lancement V2CLEAN
    // v1.4.3 (Plan Q3) : reset sur transition re-alive + throttle anti-flap-storm
    bool    warned_stale_{false};
    bool    warned_zombie_{false};
    int64_t last_stale_warning_ms_{0}; // throttle 5 min entre warnings meme type
    int64_t last_zombie_warning_ms_{0};

    void write_v2bis_heartbeat(int bar_count, int last_signal_id_hash, bool is_killed);

    // v1.4.3 (Plan F3 ACCEPT) : retour optional<HeartbeatSnapshot>.
    // Separe I/O (read) + parsing (optional) pour testabilite + gestion explicite
    // failure modes : nullopt si fichier absent OU corrompu OU permissions denied.
    // Caller update last_v2clean_hb_ms_ et last_v2clean_pid_ selon retour.
    std::optional<HeartbeatSnapshot> read_v2clean_heartbeat() const;
};

} // namespace v2bis

// ─── Logique crash detection ────────────────────────────────────────
// Si (now - last_v2clean_hb_ms) > 30s  → journal v2clean_stale_warning (throttle 5min)
// Si (now - last_v2clean_hb_ms) > 120s → block signals, journal v2clean_down
//
// ─── Logique zombie detection (process alive mais muet) ─────────────
// Si (now - last_v2clean_signal_ms) > 15 min ET is_rth_active() → journal v2clean_zombie_warning
// Si (now - last_v2clean_signal_ms) > 30 min ET is_rth_active() → block signals, journal v2clean_zombie_blocking
// RTH lue via session_window_.is_rth_active() (ISessionWindow inject, v1.4.3).
//
// ─── Failure modes (v1.4.3 Plan Q4) ─────────────────────────────────
// - Fichier absent : read_v2clean_heartbeat() retourne nullopt → journal V2CLEAN_HEARTBEAT_MISSING
//   apres 30s grace period boot. Block > 120s comme DOWN.
// - JSON corrompu : nullopt + journal V2CLEAN_STALE_WARNING payload "parse_error"
// - Permissions denied : journal HEARTBEAT_IO_ERROR (CRITICAL, alerte operateur)
// - Clock skew : si ts_ms > now_ms + 500ms (NTP drift V2CLEAN en avance) → V2CLEAN_CLOCK_SKEW
//
// ─── Contrat JSON v2clean_heartbeat.json (v1.4.3 Plan Q2) ──────────
// Format Python ecriture atomic (tmpfile + rename, OBLIGATOIRE cote V2CLEAN) :
//   {
//     "ts_ms": 1776808860000,
//     "last_signal_emitted_ts_ms": 1776808800000,
//     "version": "V2CLEAN-1.4.3",
//     "pid": 12345,
//     "schema_version": 1
//   }
// Freq write : 1 Hz. Rotation : pas de rotation (overwrite atomic).
// Si pid change entre 2 reads → V2CLEAN relance → reset warned_stale_/warned_zombie_.
//
// V2-bis continue de gerer SL/TP/trailing positions OUVERTES meme si V2CLEAN down/zombie.
//
// Tests cibles (6) :
//   heartbeat_ok, v2clean_down_30s_alert, v2clean_down_120s_block,
//   file_missing, heartbeat_corrupted_fallback, pid_change_reset_warned,
//   reboot_recovery, throttle_anti_flap_storm
