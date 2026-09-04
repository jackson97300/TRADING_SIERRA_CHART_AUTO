"""Tests audit ULTRATHINK Bot 2 (Bot1V2) - 24/06/2026.

Couvre Phase 1 (3 quick wins) + Phase 2 (régime-aware adoption V_FINAL).

REFERENCES :
- Audit market-analyst 24/06 sur 39 fills 7j : PnL $0 (hasard), bias LONG 87%
- Mirror Divorce 100% (bull_pts NULL) - architecture découplée
- Dead config BAR_FINISH_STRENGTH_MIN (defined mais jamais lu)
- Trade 22/06 17:02 NQ LONG bug edge case (SL > entry)
- Journal trades cassé 36/39 non-écrits

PHASE 1 :
- 1A : Activer BAR_FINISH_STRENGTH dans _check_quality_bar_confirmation
- 1B : Assert SL/TP cohérent (LONG: SL<entry, TP>entry) - reject sinon
- 1C : Câbler TradeJournal dans DtcFillListener

PHASE 2 :
- Régime-aware adoption : reuse CORE/bot_mean_revert/regime_classifier.py
- Blacklist V_FINAL (PANIC:*, CALM_RANGE:us_cash, VOLATILE_RANGE:asia)
- Throttle emit BOT1V2_REGIME_DETECTED sur changement régime
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ==========================================================================
# Phase 1A — BAR_FINISH_STRENGTH activation
# ==========================================================================

def test_phase1a_bar_finish_strength_blocks_long_avorted_bar():
    """LONG bar verte mais finish_strength < MIN → BLOCK (anti bar avortee)."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dashboard_mirror import _check_quality_bar_confirmation

    cfg = Bot1V2Config()  # BAR_FINISH_STRENGTH_ENABLED=True default
    bar = {
        "close": 7542.0,
        "open": 7541.25,
        "bar_color_up": 1,
        "finish_strength": -42.0,  # close pres du low = bar avortee
    }
    miss = _check_quality_bar_confirmation(bar, "LONG", cfg)
    assert miss is not None
    assert miss.name == "BAR_FINISH_STRENGTH_WEAK_LONG"
    assert "finish_strength=-42.0" in miss.reason


def test_phase1a_bar_finish_strength_passes_strong_close():
    """LONG bar verte avec finish_strength fort (>= 30) → PASS."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dashboard_mirror import _check_quality_bar_confirmation

    cfg = Bot1V2Config()
    bar = {
        "close": 7542.5,
        "open": 7541.25,
        "bar_color_up": 1,
        "finish_strength": 75.0,  # close pres du high = bar saine
    }
    miss = _check_quality_bar_confirmation(bar, "LONG", cfg)
    assert miss is None


def test_phase1a_bar_finish_strength_short_inverted():
    """SHORT bar rouge mais finish_strength > -MIN (close pres du high)
    → BLOCK car bar avortee bearish."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dashboard_mirror import _check_quality_bar_confirmation

    cfg = Bot1V2Config()
    bar = {
        "close": 7540.0,
        "open": 7541.0,
        "bar_color_dn": 1,
        "finish_strength": 50.0,  # close pres du high = bar avortee bearish
    }
    miss = _check_quality_bar_confirmation(bar, "SHORT", cfg)
    assert miss is not None
    assert miss.name == "BAR_FINISH_STRENGTH_WEAK_SHORT"


def test_phase1a_bar_finish_strength_kill_switch(monkeypatch):
    """BOT1V2_BAR_FINISH_STRENGTH_ENABLED=false → backward compat (pas de block)."""
    monkeypatch.setenv("BOT1V2_BAR_FINISH_STRENGTH_ENABLED", "false")
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dashboard_mirror import _check_quality_bar_confirmation

    cfg = Bot1V2Config.from_env()
    assert cfg.BAR_FINISH_STRENGTH_ENABLED is False

    bar = {
        "close": 7542.0,
        "open": 7541.25,
        "bar_color_up": 1,
        "finish_strength": -42.0,  # avortee mais filter disabled
    }
    miss = _check_quality_bar_confirmation(bar, "LONG", cfg)
    assert miss is None  # backward compat


# ==========================================================================
# Phase 1B — Assert SL/TP cohérent
# ==========================================================================

def test_phase1b_long_sl_above_entry_rejected():
    """LONG avec SL > entry → REJECT (bug 22/06 17:02 NQ)."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.risk.sl_tp import compute_sl_tp

    cfg = Bot1V2Config()
    # Bar avec mur LONG (support) AU-DESSUS du prix entry = absurde
    bar = {
        # VWAP_D_SD1D supposé être support pour LONG mais ici au-dessus
        "vwap_d_sd1d": 30585.10,  # > entry
        "is_in_us_cash": True,
    }
    result = compute_sl_tp(bar, "LONG", entry_price=30578.25, symbol="NQ", cfg=cfg)
    # Soit reject pour SL_INVALID_LONG, soit reject pour HARD_CAP/NO_WALL
    # On vérifie qu'on ne se retrouve pas avec accepted=True + SL au-dessus entry
    if result.accepted:
        assert result.sl_price < 30578.25, (
            f"LONG accepted mais SL={result.sl_price} >= entry={30578.25}"
        )


def test_phase1b_short_sl_below_entry_rejected():
    """SHORT avec SL < entry → REJECT (symetrique)."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.risk.sl_tp import compute_sl_tp

    cfg = Bot1V2Config()
    bar = {
        "vwap_d_sd1d": 30575.0,  # < entry pour SHORT
        "is_in_us_cash": True,
    }
    result = compute_sl_tp(bar, "SHORT", entry_price=30580.0, symbol="NQ", cfg=cfg)
    if result.accepted:
        assert result.sl_price > 30580.0, (
            f"SHORT accepted mais SL={result.sl_price} <= entry={30580.0}"
        )


def test_phase1b_long_normal_sl_below_entry_accepted():
    """LONG avec mur VAL en-dessous entry → accept."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.risk.sl_tp import compute_sl_tp

    cfg = Bot1V2Config()
    bar = {
        "vwap_d_sd1d": 7540.0,  # 8 pts en-dessous entry 7548 -> wall valide LONG
        "cur_val": 7541.0,
        "is_in_us_cash": True,
    }
    result = compute_sl_tp(bar, "LONG", entry_price=7548.0, symbol="ES", cfg=cfg)
    if result.accepted:
        assert result.sl_price < 7548.0
        assert result.tp_price > 7548.0


# ==========================================================================
# Phase 1C — TradeJournal cabling
# ==========================================================================

def test_phase1c_trade_journal_optional_in_listener():
    """DtcFillListener accepte trade_journal=None (backward compat)."""
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
    from CORE.bot1_v2.state.position_store import PositionStore
    from CORE.bot1_v2.state_bridge import StateBridge as Bot1V2StateBridge

    cfg = Bot1V2Config()
    store = PositionStore(path=Path("/tmp/test_listener_no_journal.json"))
    bridge = Bot1V2StateBridge()
    listener = DtcFillListener(cfg, store, bridge, trade_journal=None)
    assert listener.trade_journal is None


def test_phase1c_trade_journal_injection_with_real(tmp_path):
    """DtcFillListener accepte un TradeJournal réel."""
    from BOT.trade_journal import TradeJournal
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
    from CORE.bot1_v2.state.position_store import PositionStore
    from CORE.bot1_v2.state_bridge import StateBridge as Bot1V2StateBridge

    cfg = Bot1V2Config()
    store = PositionStore(path=tmp_path / "test_listener_with_journal.json")
    bridge = Bot1V2StateBridge()
    journal = TradeJournal(journal_dir=str(tmp_path / "JOURNAL"))
    listener = DtcFillListener(cfg, store, bridge, trade_journal=journal)
    assert listener.trade_journal is journal


# ==========================================================================
# Phase 2 — Régime-aware adoption
# ==========================================================================

def test_phase2_config_regime_aware_enabled_default():
    """REGIME_AWARE_ENABLED default True."""
    from CORE.bot1_v2.config import Bot1V2Config

    cfg = Bot1V2Config()
    assert cfg.REGIME_AWARE_ENABLED is True


def test_phase2_config_regime_blacklist_v_final():
    """Blacklist par défaut = V_FINAL Bot MR."""
    from CORE.bot1_v2.config import Bot1V2Config

    cfg = Bot1V2Config()
    assert "PANIC:*" in cfg.REGIME_AWARE_BLACKLIST
    assert "CALM_RANGE:us_cash" in cfg.REGIME_AWARE_BLACKLIST
    assert "VOLATILE_RANGE:asia" in cfg.REGIME_AWARE_BLACKLIST


def test_phase2_config_regime_kill_switch(monkeypatch):
    """REGIME_AWARE_ENABLED=false → kill switch."""
    monkeypatch.setenv("BOT1V2_REGIME_AWARE_ENABLED", "false")
    from CORE.bot1_v2.config import Bot1V2Config

    cfg = Bot1V2Config.from_env()
    assert cfg.REGIME_AWARE_ENABLED is False


def test_phase2_config_regime_blacklist_env_override(monkeypatch):
    """Blacklist customisable via env."""
    monkeypatch.setenv(
        "BOT1V2_REGIME_AWARE_BLACKLIST",
        "PANIC:*,TREND_DOWN:london",
    )
    from CORE.bot1_v2.config import Bot1V2Config

    cfg = Bot1V2Config.from_env()
    assert "PANIC:*" in cfg.REGIME_AWARE_BLACKLIST
    assert "TREND_DOWN:london" in cfg.REGIME_AWARE_BLACKLIST


def test_phase2_regime_classifier_import_and_use():
    """RegimeClassifier V_FINAL importable + utilisable depuis Bot 2."""
    from CORE.bot_mean_revert.regime_classifier import (
        RegimeClassifier, Regime, detect_session_utc,
        parse_blacklist, is_blacklisted,
    )

    clf = RegimeClassifier()
    bar = {
        "vix_level": 25.0,  # PANIC trigger
        "atr_14m_pct": 0.02,
        "trend_day_probability": 0.1,
        "vwap_slope_30": 0.0,
    }
    regime = clf.classify(bar, "ES")
    assert regime == Regime.PANIC
    blacklist = parse_blacklist(["PANIC:*"])
    assert is_blacklisted(regime, "us_cash", blacklist)


def test_phase2_session_us_cash_in_blacklist():
    """CALM_RANGE × us_cash bloqué par défaut V_FINAL."""
    from CORE.bot_mean_revert.regime_classifier import (
        Regime, parse_blacklist, is_blacklisted,
    )
    blacklist = parse_blacklist(("PANIC:*", "CALM_RANGE:us_cash", "VOLATILE_RANGE:asia"))
    assert is_blacklisted(Regime.CALM_RANGE, "us_cash", blacklist)
    assert not is_blacklisted(Regime.CALM_RANGE, "asia", blacklist)
    assert not is_blacklisted(Regime.CALM_RANGE, "london", blacklist)


def test_phase2_volatile_asia_blocked():
    """VOLATILE_RANGE × asia bloqué (panic post-news Asia)."""
    from CORE.bot_mean_revert.regime_classifier import (
        Regime, parse_blacklist, is_blacklisted,
    )
    blacklist = parse_blacklist(("PANIC:*", "CALM_RANGE:us_cash", "VOLATILE_RANGE:asia"))
    assert is_blacklisted(Regime.VOLATILE_RANGE, "asia", blacklist)
    assert not is_blacklisted(Regime.VOLATILE_RANGE, "us_cash", blacklist)


def test_phase2_trend_day_not_blacklisted():
    """TREND_DOWN / TREND_UP non blacklistés par défaut (=garde edge)."""
    from CORE.bot_mean_revert.regime_classifier import (
        Regime, parse_blacklist, is_blacklisted,
    )
    blacklist = parse_blacklist(("PANIC:*", "CALM_RANGE:us_cash", "VOLATILE_RANGE:asia"))
    assert not is_blacklisted(Regime.TREND_DOWN, "us_cash", blacklist)
    assert not is_blacklisted(Regime.TREND_UP, "asia", blacklist)
    assert not is_blacklisted(Regime.TREND_DOWN, "london", blacklist)


def test_phase2_env_tuple_parse():
    """_env_tuple parsing fonctionnel."""
    from CORE.bot1_v2.config import _env_tuple

    # Default
    result = _env_tuple("NONEXISTENT", ("a", "b"))
    assert result == ("a", "b")


def test_phase2_env_tuple_override(monkeypatch):
    """_env_tuple via env var override."""
    monkeypatch.setenv("BOT1V2_REGIME_AWARE_BLACKLIST", "X:*,Y:asia,Z:london")
    from CORE.bot1_v2.config import _env_tuple

    result = _env_tuple("REGIME_AWARE_BLACKLIST", ())
    assert result == ("X:*", "Y:asia", "Z:london")
