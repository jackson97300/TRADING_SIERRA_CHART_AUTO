"""Tests NO_REENTRY_DISTANCE Bot MR (anti-clustering spatial 18/06/2026).

Pattern observe 18/06 : 5 LONGs ES dans 13 ticks (7547.25 -> 7560.75) sur Sim1.
Entry @ 7558.25 dans zone deja over-tradee = -$237.50 broker.
3e garde-fou en plus de COOLDOWN_BARS (temporel) et MAX_HOLD_MINUTES.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

import pytest

from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


# ==========================================================================
# Helpers (alignes test_signal_engine.py)
# ==========================================================================


def _ts_now_us() -> int:
    """ts ms en plein milieu RTH US (15:00 UTC = 11:00 ET)."""
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es_long(close_price: float = 5800.0) -> dict:
    """Bar ES synthetique RTH avec extension SD3 down -> setup LONG."""
    return {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": close_price,
        "bar_high": close_price + 1.0,
        "bar_low": close_price - 1.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.10,
        "dist_vwap_d_sd3u_pct": -0.20,
        "vwap_slope_30": 0.05,  # trend_align_es LONG
        # Phase 4 18/06 defaults neutres pour orderflow/anti-top/momentum
        "delta_bar": 50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }


# ==========================================================================
# 1. Config (defaults + env override + helper)
# ==========================================================================


def test_default_no_reentry_ticks():
    """Defaults NO_REENTRY_TICKS : ES=20, NQ=50, MGC=30."""
    cfg = BotMRConfig()
    assert cfg.NO_REENTRY_TICKS_ES == 20
    assert cfg.NO_REENTRY_TICKS_NQ == 50
    assert cfg.NO_REENTRY_TICKS_MGC == 30


def test_env_override_no_reentry_ticks(monkeypatch):
    """Env vars BOTMR_NO_REENTRY_TICKS_* override les defaults."""
    monkeypatch.setenv("BOTMR_NO_REENTRY_TICKS_ES", "15")
    monkeypatch.setenv("BOTMR_NO_REENTRY_TICKS_NQ", "40")
    monkeypatch.setenv("BOTMR_NO_REENTRY_TICKS_MGC", "25")
    cfg = BotMRConfig.from_env()
    assert cfg.NO_REENTRY_TICKS_ES == 15
    assert cfg.NO_REENTRY_TICKS_NQ == 40
    assert cfg.NO_REENTRY_TICKS_MGC == 25


def test_no_reentry_ticks_helper():
    """Helper cfg.no_reentry_ticks(symbol) retourne seuil correct par sym."""
    cfg = BotMRConfig()
    assert cfg.no_reentry_ticks("ES") == 20
    assert cfg.no_reentry_ticks("es") == 20  # case insensitive
    assert cfg.no_reentry_ticks("NQ") == 50
    assert cfg.no_reentry_ticks("MGC") == 30
    assert cfg.no_reentry_ticks("ZZ") == 20  # default raisonnable


# ==========================================================================
# 2. PositionStore (set/get + persistence cross-restart)
# ==========================================================================


def test_position_store_set_get_entry_price(tmp_path):
    """set_last_entry_price puis get_last_entry_price round-trip OK."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "LONG", 7547.25)
    assert store.get_last_entry_price("ES", "LONG") == 7547.25
    # Direction opposee = None
    assert store.get_last_entry_price("ES", "SHORT") is None
    # Symbole different = None
    assert store.get_last_entry_price("NQ", "LONG") is None


def test_position_store_case_insensitive(tmp_path):
    """Keys (symbol, direction) doivent etre case-insensitive."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("es", "long", 5800.0)
    assert store.get_last_entry_price("ES", "LONG") == 5800.0
    assert store.get_last_entry_price("Es", "Long") == 5800.0


def test_position_store_overwrites_previous(tmp_path):
    """Nouveau set_last_entry_price ecrase l'ancien pour meme (sym, dir)."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "LONG", 7547.25)
    store.set_last_entry_price("ES", "LONG", 7553.75)
    assert store.get_last_entry_price("ES", "LONG") == 7553.75


def test_position_store_persist_entry_price(tmp_path):
    """REGRESSION : last_entry_price persiste cross-restart (save + load)."""
    store_path = tmp_path / "state.json"

    # Session 1
    store1 = PositionStore(path=store_path)
    store1.set_last_entry_price("ES", "LONG", 7547.25)
    store1.set_last_entry_price("ES", "SHORT", 7600.0)
    store1.set_last_entry_price("NQ", "LONG", 21000.0)
    assert store1.save() is True

    # Session 2 : restart
    store2 = PositionStore(path=store_path)
    assert store2.load() is True
    assert store2.get_last_entry_price("ES", "LONG") == 7547.25
    assert store2.get_last_entry_price("ES", "SHORT") == 7600.0
    assert store2.get_last_entry_price("NQ", "LONG") == 21000.0


def test_position_store_empty_on_fresh_load(tmp_path):
    """Si fichier inexistant, get_last_entry_price retourne None."""
    store = PositionStore(path=tmp_path / "fresh.json")
    assert store.load() is False
    assert store.get_last_entry_price("ES", "LONG") is None


# ==========================================================================
# 3. SignalEngine - check NO_REENTRY dans evaluate()
# ==========================================================================


def test_signal_engine_no_reentry_blocks_too_close_long(tmp_path):
    """Setup observe 18/06 : last LONG ES @ 7547.25, new candidate @ 7548.00 (3t).
    Seuil ES = 20t -> skip avec REENTRY_TOO_CLOSE."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "LONG", 7547.25)
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    # candidate price 7548.00 = 3 ticks au-dessus du last entry (tick ES = 0.25)
    bar = _make_bar_es_long(close_price=7548.00)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REENTRY_TOO_CLOSE" in sig.skip_reason
    assert sig.direction == "LONG"
    # Verif format skip_reason : contient dist + threshold + last
    assert "3t" in sig.skip_reason
    assert "20t" in sig.skip_reason
    assert "7547.25" in sig.skip_reason


def test_signal_engine_no_reentry_allows_far_long(tmp_path):
    """Si candidate > seuil ticks du last entry, pas de block (autres gates s'appliquent)."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "LONG", 7547.25)
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    # candidate price 7560.00 = 51 ticks au-dessus (> 20t seuil ES)
    bar = _make_bar_es_long(close_price=7560.00)
    sig = eng.evaluate(bar)
    # Pas bloque par REENTRY (peut etre tradable ou bloque autre gate)
    assert "REENTRY_TOO_CLOSE" not in (sig.skip_reason or "")


def test_signal_engine_no_reentry_ignores_opposite_direction(tmp_path):
    """LONG candidate ne doit pas etre bloque par un SHORT precedent."""
    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "SHORT", 7547.25)  # SHORT history
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(close_price=7548.00)  # LONG candidate 3t away
    sig = eng.evaluate(bar)
    assert "REENTRY_TOO_CLOSE" not in (sig.skip_reason or "")


def test_signal_engine_no_reentry_no_block_without_history(tmp_path):
    """Premier trade : pas de last_entry_price -> pas de block."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    bar = _make_bar_es_long(close_price=5800.0)
    sig = eng.evaluate(bar)
    assert "REENTRY_TOO_CLOSE" not in (sig.skip_reason or "")


def test_signal_engine_no_reentry_skip_without_store(tmp_path):
    """Mode legacy (store=None) : NO_REENTRY ignore (pas de persist possible)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)  # NO store
    bar = _make_bar_es_long(close_price=5800.0)
    sig = eng.evaluate(bar)
    # Pas de crash, pas de REENTRY check
    assert "REENTRY_TOO_CLOSE" not in (sig.skip_reason or "")


# ==========================================================================
# 4. register_trade : maj set_last_entry_price
# ==========================================================================


def test_register_trade_sets_last_entry_price(tmp_path):
    """register_trade(direction=X, entry_price=Y) memorise via store."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    eng.register_trade(signal_id="sig1", direction="LONG", entry_price=7547.25)
    assert store.get_last_entry_price("ES", "LONG") == 7547.25


def test_register_trade_no_entry_price_doesnt_update(tmp_path):
    """register_trade SANS direction/entry_price (backward compat) : pas d'update."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    # Premiere fois (signature legacy)
    eng.register_trade(signal_id="sig1")
    assert store.get_last_entry_price("ES", "LONG") is None
    assert store.get_last_entry_price("ES", "SHORT") is None


def test_register_trade_ignores_invalid_entry_price(tmp_path):
    """entry_price <= 0 : pas d'update (defense)."""
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)
    eng.register_trade(signal_id="sig1", direction="LONG", entry_price=0.0)
    assert store.get_last_entry_price("ES", "LONG") is None


# ==========================================================================
# 5. Integration scenario : flow 18/06 observe (5 LONGs clustering)
# ==========================================================================


def test_clustering_scenario_18_06_blocked_after_first(tmp_path):
    """Reproduit le pattern 18/06 : 5 LONGs ES dans 13 ticks.

    Flow attendu :
      - 1er LONG @ 7547.25 : OK, register
      - 2eme LONG @ 7553.75 (26t plus haut) : OK (> 20t threshold)
      - 3eme LONG @ 7548.00 (1t du 1er) : BLOCK REENTRY (mais le LAST devient 2eme @ 7553.75)
      - en fait : check = abs(candidate - LAST_entry), donc 7548 vs 7553.75 = 23t -> OK
    Pour vraiment tester le block du pattern, on simule consecutive LONG trop proches.
    """
    store = PositionStore(path=tmp_path / "state.json")
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)

    # 1er trade : pas d'historique -> register OK
    eng.register_trade(signal_id="sig1", direction="LONG", entry_price=7547.25)
    assert store.get_last_entry_price("ES", "LONG") == 7547.25

    # 2eme trade : 7548.00 = 3 ticks au-dessus
    bar2 = _make_bar_es_long(close_price=7548.00)
    sig2 = eng.evaluate(bar2)
    # IMPORTANT : cooldown sera prob actif (1er register juste avant). Verif que
    # REGARDLESS du cooldown, le NO_REENTRY aurait bloque AUSSI.
    # Le check NO_REENTRY est evalue APRES cooldown dans evaluate(), donc on
    # peut juste verifier que le skip_reason contient cooldown OU reentry.
    # Pour test de regression precise, on bypass cooldown via direct check.
    assert sig2.tradable is False
    assert (
        "COOLDOWN" in sig2.skip_reason
        or "REENTRY_TOO_CLOSE" in sig2.skip_reason
    ), f"Doit etre bloque (cooldown OU reentry) : {sig2.skip_reason}"


def test_clustering_scenario_bypass_cooldown_to_isolate_reentry(tmp_path):
    """Isole le NO_REENTRY en bypassant le cooldown (last_trade_ts ancien).

    On force la situation : last_entry_price = 7547.25, last_trade_ts ancien
    (> COOLDOWN_BARS minutes) -> seul NO_REENTRY peut bloquer.
    """
    from datetime import datetime, timedelta, timezone

    store = PositionStore(path=tmp_path / "state.json")
    store.set_last_entry_price("ES", "LONG", 7547.25)
    # Force last_trade_ts ancien pour bypass cooldown
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.set_last_trade_ts("ES", old_ts)

    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg, store=store)

    # Candidate price 7548.00 = 3 ticks > seuil 20t -> BLOCK NO_REENTRY
    bar = _make_bar_es_long(close_price=7548.00)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REENTRY_TOO_CLOSE" in sig.skip_reason
