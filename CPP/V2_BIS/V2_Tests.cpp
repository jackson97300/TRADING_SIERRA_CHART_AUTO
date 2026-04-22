// V2_Tests.cpp — 79 tests narratifs + 4 tests statiques globaux = 83 TEST_CASE
// ==============================================================================
// Design doc : DOCS/V2_BIS_DESIGN_P0.md section 4.13 + 8.4
// Statut : stub P0, implementation P1+
// LOC cible : ~600
//
// Decomposition :
//   79 tests narratifs (distributes dans 10 suites modules metier)
//   +4 tests STATIC globaux pattern 11 (V2_RiskManager, V2_SessionGuard,
//     V2_OrderExec, global scan) declares en section dediee fin de fichier
//   = 83 TEST_CASE total

// Catch2 single-header (a installer P1 via vcpkg ou fichier direct)
// #include <catch2/catch_test_macros.hpp>

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
#include "V2_MockImpl.h"

#include <string>
#include <map>
#include <set>
#include <regex>

using namespace v2bis;
using namespace v2bis::mock;

// ─── Helpers statiques (grep-based pattern 11 tests) ───────────────

namespace helpers {

std::string read_file(const std::string& path);
std::map<std::string, std::string> read_dir_all_files(const std::string& dir);
bool contains(const std::string& haystack, const std::string& needle);
bool contains_pattern(const std::string& haystack, const std::string& regex_pattern);

} // namespace helpers


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_JSONLBridge (8 tests)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("JSONLBridge: fichier absent retourne false") { }
// TEST_CASE("JSONLBridge: ligne malformee skippee + log erreur") { }
// TEST_CASE("JSONLBridge: staleness ts > entry_window_sec reject") { }
// TEST_CASE("JSONLBridge: dedup cross-restart via StatePersistence") { }
// TEST_CASE("JSONLBridge: parsing OK schema 23 champs") { }
// TEST_CASE("JSONLBridge: features_hash log-only (audit-trail)") { }
// TEST_CASE("JSONLBridge: multiple signaux queue FIFO") { }
// TEST_CASE("JSONLBridge: file rotation quotidienne handled") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_OrderExec (15 tests)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("OrderExec: bracket complet place 3 ordres") { }
// TEST_CASE("OrderExec: fill parent declenche attach SL+TP") { }
// TEST_CASE("OrderExec: fill TP cancel SL oppose") { }
// TEST_CASE("OrderExec: fill SL cancel TP oppose") { }
// TEST_CASE("OrderExec: smart entry LIMIT si dist > 3t") { }
// TEST_CASE("OrderExec: smart entry MARKET si dist <= 3t") { }
// TEST_CASE("OrderExec: trailing actif si profit > 0.5*SL") { }
// TEST_CASE("OrderExec: trailing update monotonic") { }
// TEST_CASE("OrderExec: BE hit move SL to entry_price") { }
// TEST_CASE("OrderExec: orphelin detection + cancel") { }
// TEST_CASE("OrderExec: retry 3x sur ACK timeout") { }
// TEST_CASE("OrderExec: flatten_all ferme toutes positions") { }
// TEST_CASE("OrderExec: flatten_all noop si 0 position") { }
// TEST_CASE("OrderExec: exit_manual ferme position par parent_signal_id") { }
// TEST_CASE("OrderExec: exit_manual execute meme durant kill-switch") { }
// v1.4.3 (22/04 Plan STEP 5 Q3) tests ACSIL ordering :
// TEST_CASE("OrderExec: tp_fill_then_bar_close_ordering") {
//   Given: MockOrderExecutor + position LONG ouverte + TP touche en tick T
//   When:  on_sl_tp_hit(tp_order_id) puis bar close → update_on_bar(sym)
//   Then:  cancel SL oppose execute AVANT update_trailing (sequencing)
//          AND update_trailing NE touche PAS position deja closed (skip if !active)
//          AND detect_and_cancel_orphan() verifie apres cancel OK
//   Valide : ACSIL single-thread garantit sequentialite (Plan Q3). Pas de race.
// }
// TEST_CASE("OrderExec: smart_entry_reject_no_quote") {
//   Given: MockMarketDataProvider bid=0 ask=0 (post-connexion, no quote)
//   When:  execute(signal ENTRY) appele
//   Then:  ExecutionResult.ok == false
//          AND error == OrderError::INVALID_PRICE
//          AND journal.has_event(SIGNAL_REJECTED) avec payload reason="no_market_quote"
//          AND MockOrderExecutor.order_log.empty() (aucun MARKET fallback aveugle)
//   Valide : R4 code-reviewer, pas de fallback dangereux.
// }
// TEST_CASE("OrderExec: execute_logs_ORDER_ERROR_on_broker_reject") {
//   Given: MockOrderExecutor.submit_market returns -1 (broker reject)
//   When:  execute(signal ENTRY)
//   Then:  ExecutionResult.ok == false
//          AND journal.has_event(ORDER_ERROR) (log DANS execute(), pas V2_Main)
//   Valide : R5 code-reviewer + Plan Q4 Option B (log in execute()).
// }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_RiskManager (12 tests)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Risk: peak_drop_intraday_dd declenche kill") { }
// TEST_CASE("Risk: loss_only daily_loss declenche kill") { }
// TEST_CASE("Risk: CATASTROPHE priority over DAILY_LOSS") { }
// TEST_CASE("Risk: max_trades > 5 declenche kill") { }
// TEST_CASE("Risk: reset_session zero state") { }
// TEST_CASE("Risk: persistence roundtrip via StatePersistence") { }
// TEST_CASE("Risk: restore after crash OK") { }
// TEST_CASE("Risk: concurrent ES+NQ via named mutex") { }
// TEST_CASE("Risk STATIC: V2_RiskManager.h no score_combined ref") { }
// TEST_CASE("Risk STATIC: V2_RiskManager.h no p_primary ref") { }
// TEST_CASE("Risk STATIC: V2_RiskManager.h no p_meta ref") { }
// TEST_CASE("Risk STATIC: V2_RiskManager.h no features_hash ref") { }

// v1.4.3 (22/04) Gap #5+#6 tests :
// TEST_CASE("Risk: kill_switch_logged_once_on_transition") {
//   Given: MockEventJournal + V2RiskManager stub
//   When:  on_trade_close(-$900)  // CATASTROPHE threshold
//   Then:  journal.events[EventType::KILL_SWITCH_TRIGGER].count == 1
//          AND subsequent allow_trade() calls n'ajoutent PAS de KILL_SWITCH_TRIGGER
//          AND dispatcher V2_Main NE LOG PAS depuis sa branche kill path
//   Valide : Gap #5 (spam journal evite via log UNIQUE dans trigger_kill)
// }
//
// TEST_CASE("Risk: kill_escalation_multi_trigger") {
//   Given: V2RiskManager
//   When:  on_trade_close(-$550)  // DAILY_LOSS d'abord
//   Then:  journal.events[KILL_SWITCH_TRIGGER].count == 1 (reason: DAILY_LOSS)
//   When:  on_trade_close(-$400 supplementaire)  // CATASTROPHE escalation
//   Then:  journal.events[KILL_SWITCH_TRIGGER].count == 2 (reason: CATASTROPHE)
//   Valide : escalation multi-reason loggee distinctement, pas dedup trop strict
// }
//
// TEST_CASE("Main: kill_switch_positions_still_trailing") {
//   Given: Mock{Health, Bridge, Session, Risk(killed=true), OrderExec, Journal}
//          + position NQ LONG ouverte via order_exec
//   When:  on_bar_close_dispatcher() avec signal poll=true (entry attempt)
//   Then:  order_exec.execute() JAMAIS appele (risk block)
//          AND order_exec.update_on_bar(ES) count == 1
//          AND order_exec.update_on_bar(NQ) count == 1
//          AND NQ trailing SL a ete recalcule via market_.current_price()
//   Valide : Gap #6 (positions ne perdent pas leur trailing sous kill-switch)
// }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_SnapshotWriter (6 tests)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Snapshot: trade gagnant TP ecrit 40+ champs") { }
// TEST_CASE("Snapshot: trade perdant SL") { }
// TEST_CASE("Snapshot: trailing hit outcome") { }
// TEST_CASE("Snapshot: BE hit outcome") { }
// TEST_CASE("Snapshot: rejet session out_of_session") { }
// TEST_CASE("Snapshot: rejet risk kill-switch") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_SessionGuard (v1.4.3 : 7 tests, London retire cf Plan Q1)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Session: transition Closed → US RTH 09:30") { }
// TEST_CASE("Session: transition US → Flatten Window 15:55") { }
// TEST_CASE("Session: transition Flatten → Closed 16:00") { }
// TEST_CASE("Session: weekend always closed") { }
// TEST_CASE("Session: holiday no trading (Good Friday 2026-04-03)") { }
// TEST_CASE("Session: DST transition handled (2026-03-08 spring forward)") { }
// TEST_CASE("Session STATIC: no IMarketDataProvider injected") { }
// TEST_CASE("Session: is_rth_active() impl ISessionWindow pour V2_HealthCheck") { }
// RETIRES v1.4.3 (London supprime) :
//   transitions_asia_to_london, transitions_london_to_opr_pause


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_Main (5 tests)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Main: bar open no signal → no action") { }
// TEST_CASE("Main: bar close signal present → dispatch chain") { }
// TEST_CASE("Main: signal absent → update positions only") { }
// TEST_CASE("Main: kill-switch triggered → no new trade") { }
// TEST_CASE("Main: chain order = Health → Session → Risk → Execute") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_Config (6 tests) [NEW v1.1]
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Config: load OK from file") { }
// TEST_CASE("Config: missing file fallback defaults") { }
// TEST_CASE("Config: malformed JSON → defaults") { }
// TEST_CASE("Config: partial JSON merge avec defaults") { }
// TEST_CASE("Config: reload_from_disk update live") { }
// TEST_CASE("Config: version mismatch warns") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_StatePersistence (8 tests) [NEW v1.1]
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Persistence: atomic write OK") { }
// TEST_CASE("Persistence: crash mid-write simulated → no partial") { }
// TEST_CASE("Persistence: corruption detected → fallback .bak") { }
// TEST_CASE("Persistence: backup restore OK") { }
// TEST_CASE("Persistence: concurrent write ES+NQ sequenced") { }
// TEST_CASE("Persistence: Windows rename edge case handled") { }
// TEST_CASE("Persistence: disk full returns error") { }
// TEST_CASE("Persistence: permissions denied returns error") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_HealthCheck (6 tests) [NEW v1.1]
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Health: heartbeat OK write each 1s") { }
// TEST_CASE("Health: V2CLEAN down 30s → warning alert") { }
// TEST_CASE("Health: V2CLEAN down 120s → block signals") { }
// TEST_CASE("Health: V2CLEAN zombie 15 min RTH → warning") { }
// TEST_CASE("Health: V2CLEAN zombie 30 min RTH → block") { }
// TEST_CASE("Health: reboot recovery restore last state") { }
// v1.4.3 (22/04 Plan agent Q2-Q4) additional tests :
// TEST_CASE("Health: heartbeat_file_missing_grace_30s") { }
// TEST_CASE("Health: heartbeat_corrupted_json_fallback") { }
// TEST_CASE("Health: pid_change_reset_warned_flags") { }
// TEST_CASE("Health: throttle_5min_anti_flap_storm") { }
// TEST_CASE("Health: clock_skew_detected_V2CLEAN_CLOCK_SKEW_event") { }
// TEST_CASE("Health: zombie_skipped_when_not_RTH (ISessionWindow.is_rth_active=false)") { }


// ═══════════════════════════════════════════════════════════════════
// SUITE V2_EventJournal (4 tests) [NEW v1.1]
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Journal: append events JSONL") { }
// TEST_CASE("Journal: rotation quotidienne UTC") { }
// TEST_CASE("Journal: flush force fsync") { }
// TEST_CASE("Journal: format JSON valide") { }


// ═══════════════════════════════════════════════════════════════════
// TESTS STATIQUES PATTERN 11 (section 8.4)
// ═══════════════════════════════════════════════════════════════════

// TEST_CASE("Static: V2_RiskManager has no reference to ML scores") {
//   auto src = helpers::read_file("V2_RiskManager.h");
//   REQUIRE_FALSE(helpers::contains(src, "score_combined"));
//   REQUIRE_FALSE(helpers::contains(src, "p_primary"));
//   REQUIRE_FALSE(helpers::contains(src, "p_meta"));
//   REQUIRE_FALSE(helpers::contains(src, "features_hash"));
// }

// TEST_CASE("Static: V2_SessionGuard has no MarketDataProvider") {
//   auto src = helpers::read_file("V2_SessionGuard.h");
//   REQUIRE_FALSE(helpers::contains(src, "IMarketDataProvider"));
//   REQUIRE_FALSE(helpers::contains(src, "vix_level"));
//   REQUIRE_FALSE(helpers::contains(src, "atr_ticks"));
// }

// TEST_CASE("Static: V2_OrderExec does not modify signal direction/SL/TP") {
//   auto src = helpers::read_file("V2_OrderExec.h");
//   REQUIRE_FALSE(helpers::contains(src, "signal.direction ="));
//   REQUIRE_FALSE(helpers::contains(src, "signal.sl_ticks ="));
//   REQUIRE_FALSE(helpers::contains(src, "signal.tp_ticks ="));
// }

// TEST_CASE("Static: no score branching outside explicit log-only zones") {
//   auto src = helpers::read_dir_all_files("V2_BIS/");
//   std::set<std::string> log_only = {"V2_SnapshotWriter.h", "V2_Main.cpp"};
//   for (auto& [file, content] : src) {
//     if (log_only.count(file)) {
//       REQUIRE_FALSE(helpers::contains_pattern(content, R"(if\s*\(\s*\w*\.score_combined)"));
//       REQUIRE_FALSE(helpers::contains_pattern(content, R"(if\s*\(\s*\w*\.p_primary)"));
//       REQUIRE_FALSE(helpers::contains_pattern(content, R"(if\s*\(\s*\w*\.p_meta)"));
//       REQUIRE_FALSE(helpers::contains_pattern(content, R"(score_combined\s*[<>=])"));
//       continue;
//     }
//     REQUIRE_FALSE(helpers::contains(content, "score_combined"));
//     REQUIRE_FALSE(helpers::contains(content, "p_primary"));
//     REQUIRE_FALSE(helpers::contains(content, "p_meta"));
//   }
// }


// ═══════════════════════════════════════════════════════════════════
// TOTAL : 83 TEST_CASE (79 narratifs + 4 statiques globaux)
// ═══════════════════════════════════════════════════════════════════
//
// Repartition 79 narratifs :
//   JSONLBridge     : 8
//   OrderExec       : 15
//   RiskManager     : 12 (dont 4 statiques INTERNES module)
//   SnapshotWriter  : 6
//   SessionGuard    : 9 (dont 1 statique INTERNE module)
//   Main            : 5
//   Config          : 6
//   StatePersistence: 8
//   HealthCheck     : 6
//   EventJournal    : 4
//   ────────────────────
//   Sous-total      : 79
//
// + 4 tests STATIC globaux pattern 11 (section "TESTS STATIQUES PATTERN 11")
//   → scan grep multi-fichiers : RiskManager, SessionGuard, OrderExec, global
//
// TOTAL GRAND : 83 TEST_CASE
//
// Helpers (~30-50 LOC additionnels) :
//   read_file, read_dir_all_files, contains, contains_pattern (std::regex)
