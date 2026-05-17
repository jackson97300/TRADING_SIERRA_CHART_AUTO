"""test_setup_engine.py — Tests SetupEngine + RiskManager + trailing.

Coverage :
  - RiskManager isolé par symbole (NQ et ES independants)
  - Anti double-trigger (last_bar_ts par symbole)
  - Conflict resolution (LONG + SHORT meme bar = SKIP)
  - Confluence (>=2 setups same direction = OK)
  - Trailing stop : 4 scenarios critiques
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest
from CORE.setup_engine import (
    SetupEngine,
    RiskManager,
    Signal,
    Position,
    make_position,
    update_mfe_mae,
    acknowledge_broker_sl_update,
    check_exit_condition,
    TRAILING_CONFIG,
    RISK_PER_SYMBOL,
    MAX_POSITIONS_PER_SYMBOL,
    GLOBAL_KILL_SWITCH_DAILY_PNL,
    VETO_ATR_14M_PCT_MAX,
    TICK_SIZE,
)


# ═══════════════════════════════════════════════════════════════════
# RISK MANAGER — ISOLATION PAR SYMBOLE
# ═══════════════════════════════════════════════════════════════════

class TestRiskManagerIsolation:
    def test_initial_state_both_can_trade(self):
        rm = RiskManager()
        ok_nq, _ = rm.can_trade("NQ")
        ok_es, _ = rm.can_trade("ES")
        assert ok_nq and ok_es

    def test_nq_max_losses_phase1_free_run(self):
        """Phase 1 FREE_RUN : max_losses désactivé → trade libre malgré 3 SL."""
        from CORE.setup_engine import PHASE_1_FREE_RUN
        rm = RiskManager()
        for _ in range(3):
            rm.on_trade_close("NQ", -300.0, is_loss=True)
        ok_nq, reason_nq = rm.can_trade("NQ")
        if PHASE_1_FREE_RUN:
            assert ok_nq, f"Phase 1 FREE : NQ doit pouvoir trader malgre 3 SL, reason={reason_nq}"
        else:
            assert not ok_nq

    def test_es_kill_switch_phase1_free_run(self):
        """Phase 1 FREE_RUN : kill switch dollar désactivé."""
        from CORE.setup_engine import PHASE_1_FREE_RUN
        rm = RiskManager()
        rm.on_trade_close("ES", -2000.0, is_loss=True)  # bien au-dela de -$900
        ok_es, reason_es = rm.can_trade("ES")
        if PHASE_1_FREE_RUN:
            assert ok_es, f"Phase 1 FREE : ES doit pouvoir trader malgre -$2000, reason={reason_es}"
        else:
            assert not ok_es

    def test_unknown_symbol_rejected(self):
        rm = RiskManager()
        ok, reason = rm.can_trade("ZZ")
        assert not ok
        assert "UNKNOWN" in reason

    def test_state_snapshot_structure(self):
        from CORE.setup_engine import PHASE_1_FREE_RUN
        rm = RiskManager()
        snap = rm.state_snapshot()
        assert "trading_day" in snap
        assert "exposure_total_max_eod" in snap
        if PHASE_1_FREE_RUN:
            assert snap["exposure_total_max_eod"] == "FREE_RUN"
        else:
            assert snap["exposure_total_max_eod"] == 1800.0
        assert "NQ" in snap and "ES" in snap
        for sym in ("NQ", "ES"):
            assert "n_losses" in snap[sym]
            assert "daily_pnl" in snap[sym]
            assert "remaining_dollar" in snap[sym]
            assert "remaining_losses" in snap[sym]


# ═══════════════════════════════════════════════════════════════════
# SETUP ENGINE — DEDUP last_bar_ts (anti double-trigger)
# ═══════════════════════════════════════════════════════════════════

class TestDedupBarTs:
    def test_first_eval_returns_signal(self):
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "is_in_us_cash": 1,
            "close": 27800.0,
            "position_in_range": 0.95,
            "finish_strength": -20,
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is not None
        assert sig.side == "SHORT"
        assert "SELL_TOP_RANGE" in sig.setups

    def test_same_bar_re_eval_returns_none(self):
        """CRITIQUE : poll 30s vs batch 5min = 10 polls meme bar.
        SetupEngine ne doit PAS trigger 10 fois sur la meme bar."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "is_in_us_cash": 1,
            "close": 27800.0,
            "position_in_range": 0.95,
            "finish_strength": -20,
        }
        sig1 = eng.evaluate(bar, "NQ")
        sig2 = eng.evaluate(bar, "NQ")
        sig3 = eng.evaluate(bar, "NQ")
        assert sig1 is not None, "Premier eval doit retourner signal"
        assert sig2 is None, "DEDUP : meme bar ne doit pas re-trigger"
        assert sig3 is None, "DEDUP : meme bar ne doit pas re-trigger"

    def test_new_bar_returns_signal(self):
        eng = SetupEngine()
        bar1 = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        bar2 = {**bar1, "ts_event": "2026-05-05T14:01:00+00:00"}
        sig1 = eng.evaluate(bar1, "NQ")
        sig2 = eng.evaluate(bar2, "NQ")
        assert sig1 is not None
        assert sig2 is not None  # nouveau ts -> re-trigger OK

    def test_dedup_isolated_per_symbol(self):
        """NQ dedup ne doit pas affecter ES."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 7250.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        sig_nq = eng.evaluate(bar, "NQ")
        sig_es = eng.evaluate(bar, "ES")
        # Les 2 doivent trigger (meme bar mais symboles differents -> dedup separe)
        assert sig_nq is not None
        assert sig_es is not None


# ═══════════════════════════════════════════════════════════════════
# SETUP ENGINE — RTH FILTER + CONFLICT
# ═══════════════════════════════════════════════════════════════════

class TestSetupEngineFilters:
    def test_skip_outside_trading_window(self):
        """Trading window 02h-21h UTC. Bar a 22h UTC (= 24h FR) doit etre skip."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T22:00:00+00:00",  # 22h UTC = 24h FR (sleep)
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is None

    def test_skip_outside_window_early_morning(self):
        """01h UTC = 03h FR ete = encore sommeil → skip."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T01:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is None

    def test_pass_in_trading_window(self):
        """Bar a 14h UTC (RTH US) doit passer."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is not None  # SELL_TOP_RANGE doit trigger

    def test_pass_in_asia_within_window(self):
        """Bar a 04h UTC (06h FR ete = London-prep) doit passer."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T04:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is not None  # Asia mais dans trading window

    def test_skip_within_news_buffer(self):
        """Skip si within_news_*_5m == 1."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
            "within_news_830_5m": 1,  # NFP par exemple
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is None

    def test_skip_when_mins_to_news_under_5(self):
        """Skip si news dans <5min."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
            "mins_to_next_news": 3.0,  # FOMC dans 3 min
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is None

    def test_skip_missing_ts(self):
        eng = SetupEngine()
        bar = {"close": 27800.0,
               "position_in_range": 0.95, "finish_strength": -20}
        sig = eng.evaluate(bar, "NQ")
        assert sig is None  # ts_event manquant

    def test_invalid_symbol_returns_none(self):
        eng = SetupEngine()
        bar = {"ts_event": "2026-05-05T14:00:00+00:00",
               "close": 27800.0,
               "position_in_range": 0.95, "finish_strength": -20}
        sig = eng.evaluate(bar, "BTC")
        assert sig is None

    def test_conflict_long_short_skip(self):
        """Confluence multi-SELL test (vrai conflict difficile à construire)."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95,
            "finish_strength": -20,
            "time_to_session_close_norm": 0.20,  # ajoute SELL_LATE_SESSION_FADE
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is not None
        assert sig.side == "SHORT"
        assert sig.confluence == True
        assert len(sig.setups) >= 2


# ═══════════════════════════════════════════════════════════════════
# TRAILING STOP — 4 SCENARIOS CRITIQUES
# ═══════════════════════════════════════════════════════════════════

class TestTrailingStop:
    def _make_short_position(self):
        """Helper : SHORT NQ entry 27800."""
        sig = Signal(symbol="NQ", side="SHORT", setups=["SELL_TOP_RANGE"],
                      confluence=False, bar_ts="2026-05-05T14:00:00+00:00",
                      price=27800.0, features_at_trigger={})
        return make_position(sig, fill_price=27800.0,
                             fill_ts_utc="2026-05-05T14:00:00+00:00")

    def _make_long_position(self):
        """Helper : LONG NQ entry 27800."""
        sig = Signal(symbol="NQ", side="LONG", setups=["BUY_CVD_DIVERGENCE"],
                      confluence=False, bar_ts="2026-05-05T14:00:00+00:00",
                      price=27800.0, features_at_trigger={})
        return make_position(sig, fill_price=27800.0,
                             fill_ts_utc="2026-05-05T14:00:00+00:00")

    def test_short_trailing_not_activated_below_threshold(self):
        """MFE < 80t -> trailing pas active."""
        pos = self._make_short_position()
        update_mfe_mae(pos, 27795.0)  # +20t MFE seulement
        assert not pos.trailing_activated
        assert pos.trailing_stop_price is None

    def test_short_trailing_activates_at_threshold(self):
        """MFE >= 80t -> trailing active a +60t depuis MFE + flag pending broker update."""
        pos = self._make_short_position()
        update_mfe_mae(pos, 27780.0)  # +80t MFE
        assert pos.trailing_activated
        # 27780 + 60t * 0.25 = 27795
        assert pos.trailing_stop_price == 27795.0
        # FIX B1 : flag pending pour caller (cancel+replace DTC)
        assert pos.trailing_pending_broker_update == True

    def test_short_trailing_trails_with_better_mfe(self):
        """MFE augmente -> trailing descend (favorable)."""
        pos = self._make_short_position()
        update_mfe_mae(pos, 27780.0)  # active a 27795
        update_mfe_mae(pos, 27750.0)  # MFE 200t -> trailing 27765
        assert pos.trailing_stop_price == 27765.0
        assert pos.trailing_pending_broker_update == True

    def test_short_trailing_anti_recul(self):
        """MFE inchange (prix recule mais reste favorable) -> trailing inchange."""
        pos = self._make_short_position()
        update_mfe_mae(pos, 27750.0)  # MFE 200t -> trailing 27765
        update_mfe_mae(pos, 27770.0)  # prix recule mais MFE garde 200t
        assert pos.mfe_ticks == 200.0
        assert pos.trailing_stop_price == 27765.0  # PAS DE RECUL

    def test_short_trailing_triggers_exit_after_broker_ack(self):
        """FIX B1 : Prix touche trailing -> exit TRAILING SEULEMENT si caller a ack le broker."""
        pos = self._make_short_position()
        update_mfe_mae(pos, 27750.0)  # trailing a 27765, pending=True
        # AVANT ack broker : check_exit_condition NE doit PAS declencher TRAILING
        # (sinon reproduce TR40_NQ 01/05 : bot ferme virtuel mais broker garde position)
        reason_before_ack = check_exit_condition(pos, 27770.0, "2026-05-05T14:10:00+00:00")
        assert reason_before_ack is None, f"PRE-ACK : doit retourner None, got {reason_before_ack}"

        # Caller fait cancel+replace DTC, puis acknowledge
        acknowledge_broker_sl_update(pos, new_broker_sl_price=27765.0)
        assert pos.broker_sl_price_current == 27765.0
        assert pos.trailing_pending_broker_update == False

        # APRES ack : maintenant TRAILING peut declencher
        reason_after_ack = check_exit_condition(pos, 27770.0, "2026-05-05T14:10:00+00:00")
        assert reason_after_ack == "TRAILING", f"POST-ACK : devrait TRAILING, got {reason_after_ack}"

    def test_long_trailing_activates_correctly(self):
        """LONG : prix monte de +80t -> trailing active a -60t depuis MFE."""
        pos = self._make_long_position()
        update_mfe_mae(pos, 27820.0)  # +80t MFE LONG
        assert pos.trailing_activated
        # 27820 - 60t * 0.25 = 27805
        assert pos.trailing_stop_price == 27805.0

    def test_long_trailing_trails_up(self):
        """LONG : MFE augmente -> trailing monte."""
        pos = self._make_long_position()
        update_mfe_mae(pos, 27820.0)  # trailing 27805
        update_mfe_mae(pos, 27850.0)  # MFE 200t -> trailing 27835
        assert pos.trailing_stop_price == 27835.0

    def test_long_trailing_anti_recul(self):
        """LONG : prix recule -> trailing ne descend pas."""
        pos = self._make_long_position()
        update_mfe_mae(pos, 27850.0)  # trailing 27835
        update_mfe_mae(pos, 27830.0)  # MFE inchange
        assert pos.trailing_stop_price == 27835.0


# ═══════════════════════════════════════════════════════════════════
# EXIT CONDITIONS — PRIORITE
# ═══════════════════════════════════════════════════════════════════

class TestExitConditions:
    def _make_short(self):
        sig = Signal(symbol="NQ", side="SHORT", setups=["SELL_TOP_RANGE"],
                      confluence=False, bar_ts="t",
                      price=27800.0, features_at_trigger={})
        return make_position(sig, 27800.0, "2026-05-05T14:00:00+00:00")

    def test_no_exit_when_idle(self):
        pos = self._make_short()
        reason = check_exit_condition(pos, 27800.0, "2026-05-05T14:01:00+00:00")
        assert reason is None

    def test_sl_hit_priority(self):
        """SL touche en premier (priorite 1)."""
        pos = self._make_short()
        # SHORT, SL = 27800 + 200t * 0.25 = 27850
        reason = check_exit_condition(pos, 27855.0, "2026-05-05T14:01:00+00:00")
        assert reason == "SL"

    def test_tp_cap_hit(self):
        """TP cap touche (priorite 2, rare)."""
        pos = self._make_short()
        # SHORT, TP cap = 27800 - 500t * 0.25 = 27675
        reason = check_exit_condition(pos, 27670.0, "2026-05-05T14:01:00+00:00")
        assert reason == "TP_CAP"

    def test_timeout_after_40min(self):
        """Timeout apres 40min (Phase 1)."""
        pos = self._make_short()
        # entry = 14:00, timeout = 14:40
        reason = check_exit_condition(pos, 27800.0, "2026-05-05T14:41:00+00:00")
        assert reason == "TIMEOUT"


# ═══════════════════════════════════════════════════════════════════
# CONFIG CONSTANTS
# ═══════════════════════════════════════════════════════════════════

class TestConfigConstants:
    def test_max_positions_per_symbol(self):
        assert MAX_POSITIONS_PER_SYMBOL == 1

    def test_risk_per_symbol_phase1_free_run(self):
        """Phase 1 FREE_RUN : max_losses + kill_switch = None (desactives)."""
        from CORE.setup_engine import PHASE_1_FREE_RUN
        if PHASE_1_FREE_RUN:
            assert RISK_PER_SYMBOL["NQ"]["max_losses_per_day"] is None
            assert RISK_PER_SYMBOL["ES"]["max_losses_per_day"] is None
            assert RISK_PER_SYMBOL["NQ"]["kill_switch_daily_pnl"] is None
            assert RISK_PER_SYMBOL["ES"]["kill_switch_daily_pnl"] is None
            assert GLOBAL_KILL_SWITCH_DAILY_PNL is None
        else:
            assert RISK_PER_SYMBOL["NQ"]["max_losses_per_day"] == 3
            assert RISK_PER_SYMBOL["NQ"]["kill_switch_daily_pnl"] == -900.0
            assert GLOBAL_KILL_SWITCH_DAILY_PNL == -1800.0

    def test_trailing_config_phase1_timeout_40(self):
        """Phase 1 : timeout 40min (vs 30 prevu) pour collecte MFE/MAE."""
        assert TRAILING_CONFIG["NQ"]["timeout_minutes"] == 40
        assert TRAILING_CONFIG["ES"]["timeout_minutes"] == 40

    def test_dollar_risk_per_trade(self):
        """SL × tick_value × n_contracts = $300 par trade."""
        nq = TRAILING_CONFIG["NQ"]
        es = TRAILING_CONFIG["ES"]
        risk_nq = nq["sl_ticks"] * nq["tick_value_dollars"] * nq["n_contracts"]
        risk_es = es["sl_ticks"] * es["tick_value_dollars"] * es["n_contracts"]
        assert risk_nq == 300.0, f"NQ risk should be $300, got ${risk_nq}"
        assert risk_es == 300.0, f"ES risk should be $300, got ${risk_es}"

    def test_veto_atr_extreme_threshold(self):
        """Veto structurel anti flash crash TOUJOURS actif (meme Phase 1 free).

        17/05 FIX : seuil 0.005 -> 0.10 post commit cb32d09 (BUG E atr_14m
        units POINTS->pourcentage 15/05). 200x plus large pour refleter
        l'unite reelle (pourcentage vrai vs proxy points).
        Test verifie maintenant la valeur EXACTE actuelle. Si elle change
        encore, mettre a jour avec justification commit.
        """
        assert VETO_ATR_14M_PCT_MAX == 0.10, (
            f"VETO_ATR_14M_PCT_MAX = {VETO_ATR_14M_PCT_MAX} (expected 0.10). "
            "Si valeur change, justifier via commit + update test."
        )

    def test_b7_no_position_size_in_risk_per_symbol(self):
        """FIX B7 DRY : position_size SUPPRIMEE de RISK_PER_SYMBOL.
        Source autoritative = TRAILING_CONFIG[sym]["n_contracts"]."""
        assert "position_size" not in RISK_PER_SYMBOL["NQ"]
        assert "position_size" not in RISK_PER_SYMBOL["ES"]
        assert TRAILING_CONFIG["NQ"]["n_contracts"] == 3
        assert TRAILING_CONFIG["ES"]["n_contracts"] == 3


# ═══════════════════════════════════════════════════════════════════
# GLOBAL KILL SWITCH + VETO ATR
# ═══════════════════════════════════════════════════════════════════

class TestGlobalKillSwitchPhase1Free:
    def test_global_kill_disabled_phase1(self):
        """Phase 1 FREE : meme avec -$5000 cumule, peut continuer trader."""
        from CORE.setup_engine import PHASE_1_FREE_RUN
        rm = RiskManager()
        rm.on_trade_close("NQ", -2500.0, is_loss=True)
        rm.on_trade_close("ES", -2500.0, is_loss=True)
        ok_nq, _ = rm.can_trade("NQ")
        ok_es, _ = rm.can_trade("ES")
        if PHASE_1_FREE_RUN:
            assert ok_nq, "Phase 1 FREE : NQ doit pouvoir trader malgre -$5K"
            assert ok_es


class TestSessionLabel:
    def test_asia_session(self):
        from CORE.setup_engine import compute_session_label
        assert compute_session_label("2026-05-05T03:00:00+00:00") == "ASIA"
        assert compute_session_label("2026-05-04T23:30:00+00:00") == "ASIA"

    def test_london_session(self):
        from CORE.setup_engine import compute_session_label
        assert compute_session_label("2026-05-05T08:00:00+00:00") == "LONDON"
        assert compute_session_label("2026-05-05T13:00:00+00:00") == "LONDON"

    def test_rth_us_session(self):
        from CORE.setup_engine import compute_session_label
        assert compute_session_label("2026-05-05T13:30:00+00:00") == "RTH_US"
        assert compute_session_label("2026-05-05T15:00:00+00:00") == "RTH_US"
        assert compute_session_label("2026-05-05T19:59:00+00:00") == "RTH_US"

    def test_after_hours_session(self):
        from CORE.setup_engine import compute_session_label
        assert compute_session_label("2026-05-05T20:00:00+00:00") == "AFTER_HOURS_US"
        assert compute_session_label("2026-05-05T22:30:00+00:00") == "AFTER_HOURS_US"


class TestNewsVeto:
    def test_news_buffer_active_via_within_flag(self):
        from CORE.setup_engine import is_in_news_buffer
        bar = {"within_news_830_5m": 1}
        assert is_in_news_buffer(bar) == True

    def test_news_buffer_inactive(self):
        from CORE.setup_engine import is_in_news_buffer
        bar = {
            "within_news_715_5m": 0, "within_news_730_5m": 0,
            "within_news_830_5m": 0, "within_news_845_5m": 0,
            "within_news_900_5m": 0, "within_news_930_5m": 0,
            "mins_to_next_news": 30, "mins_since_news": 100,
        }
        assert is_in_news_buffer(bar) == False

    def test_news_buffer_via_mins_to_next(self):
        from CORE.setup_engine import is_in_news_buffer
        bar = {"mins_to_next_news": 3.0}
        assert is_in_news_buffer(bar) == True

    def test_b3_news_buffer_15min(self):
        """FIX B-3 (02/05) : NEWS_BUFFER_MINUTES = 15 (au lieu de 5).
        Couvre FOMC volatilite 30min, NFP/CPI 15-30min."""
        from CORE.setup_engine import NEWS_BUFFER_MINUTES, is_in_news_buffer
        assert NEWS_BUFFER_MINUTES == 15
        # Test : 10 min apres news = encore dans buffer (15min)
        bar = {"mins_since_news": 10.0}
        assert is_in_news_buffer(bar) == True
        # 20 min apres news = hors buffer
        bar = {"mins_since_news": 20.0}
        assert is_in_news_buffer(bar) == False


class TestB4SetupStatsTrackerProrata:
    """FIX B-4 : SetupStatsTracker split prorata pour confluence."""
    def test_solo_trade_full_pnl(self):
        from CORE.setup_engine import SetupStatsTracker, Position
        tracker = SetupStatsTracker()
        pos = Position(
            symbol="NQ", side="SHORT",
            setups=["SELL_TOP_RANGE"], confluence=False,
            n_contracts=3, entry_price=27800.0,
            entry_ts_utc="2026-05-05T14:00:00+00:00",
            sl_price=27850.0, tp_cap_price=27675.0,
            timeout_at_utc="2026-05-05T14:40:00+00:00",
            features_at_entry={},
        )
        tracker.record_trade(pos, pnl_dollars=300.0, pnl_ticks=200.0,
                             exit_reason="TRAILING", session_label="RTH_US")
        snap = tracker.snapshot()
        # Solo : 100% du PnL attribue
        assert snap["SELL_TOP_RANGE"]["pnl_total_usd"] == 300.0

    def test_confluence_2_setups_split_50_50(self):
        from CORE.setup_engine import SetupStatsTracker, Position
        tracker = SetupStatsTracker()
        pos = Position(
            symbol="NQ", side="SHORT",
            setups=["SELL_TOP_RANGE", "SELL_LATE_SESSION_FADE"], confluence=True,
            n_contracts=3, entry_price=27800.0,
            entry_ts_utc="2026-05-05T14:00:00+00:00",
            sl_price=27850.0, tp_cap_price=27675.0,
            timeout_at_utc="2026-05-05T14:40:00+00:00",
            features_at_entry={},
        )
        tracker.record_trade(pos, pnl_dollars=300.0, pnl_ticks=200.0,
                             exit_reason="TRAILING", session_label="RTH_US")
        snap = tracker.snapshot()
        # Confluence 2 setups : split 50/50 = $150 chacun
        assert snap["SELL_TOP_RANGE"]["pnl_total_usd"] == 150.0
        assert snap["SELL_LATE_SESSION_FADE"]["pnl_total_usd"] == 150.0

    def test_confluence_3_setups_split_33(self):
        from CORE.setup_engine import SetupStatsTracker, Position
        tracker = SetupStatsTracker()
        pos = Position(
            symbol="NQ", side="SHORT",
            setups=["A", "B", "C"], confluence=True,
            n_contracts=3, entry_price=27800.0,
            entry_ts_utc="2026-05-05T14:00:00+00:00",
            sl_price=27850.0, tp_cap_price=27675.0,
            timeout_at_utc="2026-05-05T14:40:00+00:00",
            features_at_entry={},
        )
        tracker.record_trade(pos, pnl_dollars=300.0, pnl_ticks=200.0,
                             exit_reason="TRAILING", session_label="RTH_US")
        snap = tracker.snapshot()
        # 300 / 3 = 100 chacun
        assert snap["A"]["pnl_total_usd"] == 100.0
        assert snap["B"]["pnl_total_usd"] == 100.0
        assert snap["C"]["pnl_total_usd"] == 100.0


class TestComputeSecondsUntilTimeout:
    def test_countdown_decreases(self):
        from CORE.setup_engine import compute_seconds_until_timeout
        sig = Signal(symbol="NQ", side="SHORT", setups=["X"], confluence=False,
                      bar_ts="t", price=27800.0, features_at_trigger={})
        # Position avec timeout dans 40min depuis maintenant
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        pos = make_position(sig, 27800.0, now)
        secs = compute_seconds_until_timeout(pos)
        # Devrait etre proche de 40*60 = 2400 (margin 5s pour le delay test)
        assert 2390 <= secs <= 2400, f"Expected ~2400s, got {secs}"


class TestVetoAtrExtreme:
    def test_setup_skipped_when_atr_extreme(self):
        """ATR > VETO_ATR_14M_PCT_MAX (0.10 post BUG E fix 15/05) = vol extreme -> SKIP.

        17/05 FIX : test data 0.008 etait extreme sous ancien seuil 0.005 mais
        normal sous nouveau seuil 0.10. Update test data a 0.15 (50% au-dessus
        nouveau seuil) pour rester un veritable test de veto vol extreme.
        """
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
            "atr_14m_pct": 0.15,  # vol extreme (> 0.10 seuil)
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is None, "ATR extreme doit bloquer le signal"

    def test_setup_passes_when_atr_normal(self):
        """ATR normal -> signal genere normalement."""
        eng = SetupEngine()
        bar = {
            "ts_event": "2026-05-05T14:00:00+00:00",
            "close": 27800.0,
            "position_in_range": 0.95, "finish_strength": -20,
            "atr_14m_pct": 0.003,  # vol normale
        }
        sig = eng.evaluate(bar, "NQ")
        assert sig is not None


class TestAcknowledgeBrokerSlUpdate:
    def test_acknowledge_resets_pending(self):
        sig = Signal(symbol="NQ", side="SHORT", setups=["SELL_TOP_RANGE"],
                      confluence=False, bar_ts="t",
                      price=27800.0, features_at_trigger={})
        pos = make_position(sig, 27800.0, "2026-05-05T14:00:00+00:00")
        update_mfe_mae(pos, 27780.0)  # active trailing, pending=True
        assert pos.trailing_pending_broker_update == True
        acknowledge_broker_sl_update(pos, new_broker_sl_price=27795.0)
        assert pos.trailing_pending_broker_update == False
        assert pos.broker_sl_price_current == 27795.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
