"""Tests CIRCUIT BREAKER Bot MR (anti-stubbornness 18/06/2026).

Carnage 18/06 : -$1025 broker E-mini sur 4 SL LONG ES d'affilee.
Bot ne stoppait JAMAIS apres N SL = pas d'auto-correction. Trader pro stoppe
a 3 SL pour reassesser regime. Halt par symbole, reset compteur au prochain TP.

Granularite : ES halt n'affecte PAS NQ (independants).
Persistence : compteur + halt_until_ts dans PositionStore (cross-restart).
"""
from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path

import pytest

from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


# ==========================================================================
# Helpers
# ==========================================================================


def _ts_now_us() -> int:
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
    }


def _fresh_store(tmp_path: Path, name: str = "cb_test.json") -> PositionStore:
    """Cree un PositionStore fresh sur tmp_path (isole par test)."""
    return PositionStore(path=tmp_path / name)


# ==========================================================================
# 1. Config defaults + env override
# ==========================================================================


def test_default_config():
    """Defaults : enabled=True, threshold=3, duration=60min."""
    cfg = BotMRConfig()
    assert cfg.CIRCUIT_BREAKER_ENABLED is True
    assert cfg.SL_CONSEC_HALT_THRESHOLD == 3
    assert cfg.HALT_DURATION_MINUTES == 60


def test_env_override(monkeypatch):
    """Env vars BOTMR_* surchargent les defaults."""
    monkeypatch.setenv("BOTMR_CIRCUIT_BREAKER_ENABLED", "false")
    monkeypatch.setenv("BOTMR_SL_CONSEC_HALT", "5")
    monkeypatch.setenv("BOTMR_HALT_DURATION_MIN", "30")
    cfg = BotMRConfig.from_env()
    assert cfg.CIRCUIT_BREAKER_ENABLED is False
    assert cfg.SL_CONSEC_HALT_THRESHOLD == 5
    assert cfg.HALT_DURATION_MINUTES == 30


# ==========================================================================
# 2. PositionStore helpers
# ==========================================================================


def test_increment_sl_consec(tmp_path):
    """increment_sl_consec retourne valeur incrementee, persiste en memoire."""
    store = _fresh_store(tmp_path)
    assert store.get_n_sl_consec("ES") == 0
    assert store.increment_sl_consec("ES") == 1
    assert store.increment_sl_consec("ES") == 2
    assert store.get_n_sl_consec("ES") == 2
    # Cross-symbol : NQ reste a 0
    assert store.get_n_sl_consec("NQ") == 0


def test_reset_sl_consec_on_tp(tmp_path):
    """reset_sl_consec remet le compteur a 0 (a appeler sur TP)."""
    store = _fresh_store(tmp_path)
    store.increment_sl_consec("ES")
    store.increment_sl_consec("ES")
    assert store.get_n_sl_consec("ES") == 2
    store.reset_sl_consec("ES")
    assert store.get_n_sl_consec("ES") == 0


def test_halt_until_ts_helpers(tmp_path):
    """get/set_halt_until_ts : default 0.0, set persiste."""
    store = _fresh_store(tmp_path)
    assert store.get_halt_until_ts("ES") == 0.0
    target = time.time() + 3600.0
    store.set_halt_until_ts("ES", target)
    assert store.get_halt_until_ts("ES") == target
    # Cross-symbol independance
    assert store.get_halt_until_ts("NQ") == 0.0


def test_halt_triggered_at_threshold(tmp_path):
    """3 SL consec -> n_consec=3 (caller decide halt si >= threshold)."""
    store = _fresh_store(tmp_path)
    for i in range(3):
        n = store.increment_sl_consec("ES")
        assert n == i + 1
    assert store.get_n_sl_consec("ES") == 3


def test_halt_persist_cross_restart(tmp_path):
    """REGRESSION : halt survit a un restart (load apres save).

    Carnage 18/06 cause = pas de persistance halt -> crash Python = bypass.
    """
    store_path = tmp_path / "cb_persist.json"

    # Session 1 : 3 SL ES, halt set
    store1 = PositionStore(path=store_path)
    for _ in range(3):
        store1.increment_sl_consec("ES")
    halt_ts = time.time() + 1800.0  # halt 30 min
    store1.set_halt_until_ts("ES", halt_ts)
    assert store1.save() is True

    # Session 2 : nouveau process (simule restart)
    store2 = PositionStore(path=store_path)
    assert store2.load() is True
    assert store2.get_n_sl_consec("ES") == 3
    assert store2.get_halt_until_ts("ES") == pytest.approx(halt_ts, abs=0.001)


# ==========================================================================
# 3. SignalEngine integration
# ==========================================================================


def test_signal_engine_blocks_during_halt(tmp_path):
    """Step 0 evaluate() : si halt actif -> tradable=False CIRCUIT_BREAKER_HALT."""
    store = _fresh_store(tmp_path)
    # Halt actif jusqu'a +1h
    store.set_halt_until_ts("ES", time.time() + 3600.0)
    cfg = BotMRConfig()
    engine = SignalEngine(symbol="ES", cfg=cfg, store=store)

    result = engine.evaluate(_make_bar_es_long())
    assert result.tradable is False
    assert "CIRCUIT_BREAKER_HALT" in result.skip_reason


def test_signal_engine_unblocks_after_halt_expired(tmp_path):
    """Step 0 evaluate() : si halt expire (ts < now) -> check continues normalement."""
    store = _fresh_store(tmp_path)
    # Halt deja expire (10s dans le passe)
    store.set_halt_until_ts("ES", time.time() - 10.0)
    cfg = BotMRConfig()
    engine = SignalEngine(symbol="ES", cfg=cfg, store=store)

    result = engine.evaluate(_make_bar_es_long())
    # Le bar setup LONG doit passer (pas bloque par circuit breaker).
    # tradable depend des autres gates ; on verifie juste que skip_reason
    # n'est PAS CIRCUIT_BREAKER_HALT (le premier check est passe).
    assert "CIRCUIT_BREAKER_HALT" not in result.skip_reason


def test_signal_engine_blocks_independent_per_symbol(tmp_path):
    """Halt ES n'affecte PAS NQ (granularite par symbole)."""
    store = _fresh_store(tmp_path)
    store.set_halt_until_ts("ES", time.time() + 3600.0)
    # NQ : pas de halt
    cfg = BotMRConfig()

    # ES blocked
    engine_es = SignalEngine(symbol="ES", cfg=cfg, store=store)
    res_es = engine_es.evaluate(_make_bar_es_long())
    assert res_es.tradable is False
    assert "CIRCUIT_BREAKER_HALT" in res_es.skip_reason

    # NQ pas de halt : pas de skip CIRCUIT_BREAKER
    engine_nq = SignalEngine(symbol="NQ", cfg=cfg, store=store)
    bar_nq = _make_bar_es_long(close_price=21000.0)  # bar NQ-like
    res_nq = engine_nq.evaluate(bar_nq)
    assert "CIRCUIT_BREAKER_HALT" not in res_nq.skip_reason


def test_signal_engine_skip_when_disabled(tmp_path, monkeypatch):
    """Si CIRCUIT_BREAKER_ENABLED=False, halt est ignore meme si set."""
    monkeypatch.setenv("BOTMR_CIRCUIT_BREAKER_ENABLED", "false")
    cfg = BotMRConfig.from_env()
    store = _fresh_store(tmp_path)
    store.set_halt_until_ts("ES", time.time() + 3600.0)
    engine = SignalEngine(symbol="ES", cfg=cfg, store=store)

    result = engine.evaluate(_make_bar_es_long())
    # Pas de check halt -> skip_reason ne contient pas CIRCUIT_BREAKER
    assert "CIRCUIT_BREAKER_HALT" not in result.skip_reason


def test_signal_engine_legacy_mode_no_store_skip_check(tmp_path):
    """Mode legacy (store=None) : skip check circuit breaker (pas de persistance)."""
    cfg = BotMRConfig()
    # Pas de store fourni -> mode legacy counter-based, circuit breaker inactif
    engine = SignalEngine(symbol="ES", cfg=cfg, store=None)

    result = engine.evaluate(_make_bar_es_long())
    assert "CIRCUIT_BREAKER_HALT" not in result.skip_reason
