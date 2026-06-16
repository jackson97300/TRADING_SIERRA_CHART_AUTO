"""Tests TrailingManager - Dow pivots SL trail."""
from __future__ import annotations

import pandas as pd

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.trailing import TrailingManager


def _bar(ts_ns: int, high: float, low: float, close: float) -> dict:
    return {
        "ts_event_ns": ts_ns,
        "ts_event": pd.Timestamp(ts_ns, unit="ns", tz="UTC"),
        "high": high,
        "low": low,
        "close": close,
        "open": (high + low) / 2,
    }


def test_initial_sl_long():
    """SL initial LONG = low(entry_bar) - 6 ticks (NQ tick=0.25)."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry = _bar(1_000_000_000_000_000_000, high=30000.0, low=29994.0, close=29998.0)
    err = mgr.start(direction="long", entry_bar=entry, entry_price=29998.0)
    assert err is None
    # SL = 29994 - 6*0.25 = 29994 - 1.5 = 29992.5
    assert abs(mgr.get_current_sl() - 29992.5) < 1e-6


def test_initial_sl_short():
    """SL initial SHORT = high(entry_bar) + 6 ticks."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry = _bar(1_000_000_000_000_000_000, high=30006.0, low=30000.0, close=30002.0)
    err = mgr.start(direction="short", entry_bar=entry, entry_price=30002.0)
    assert err is None
    # SL = 30006 + 6*0.25 = 30007.5
    assert abs(mgr.get_current_sl() - 30007.5) < 1e-6


def test_no_trail_update_on_no_new_high_short_lookback():
    """Apres entry, 1 bar sans new high : pas d'update SL (pullback pas detecte)."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry = _bar(1_000_000_000_000_000_000, high=30010.0, low=30000.0, close=30005.0)
    mgr.start(direction="long", entry_bar=entry, entry_price=30005.0)
    initial_sl = mgr.get_current_sl()
    # 1 bar sans new high (60 secondes apres entry)
    upd = mgr.on_bar(_bar(1_000_000_000_000_000_000 + 60 * 1_000_000_000, high=30009.0, low=30003.0, close=30005.0))
    assert upd.new_sl is None
    assert mgr.get_current_sl() == initial_sl


def test_idempotence_double_call_same_bar():
    """Fix P0.1 bn_v4_engine : double call meme ts_event_ns = no-op."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry = _bar(1_000_000_000_000_000_000, high=30010.0, low=30000.0, close=30005.0)
    mgr.start(direction="long", entry_bar=entry, entry_price=30005.0)
    same_bar = _bar(1_000_000_000_000_000_000 + 60_000_000_000, high=30020.0, low=30005.0, close=30015.0)
    upd1 = mgr.on_bar(same_bar)
    # Replay meme bar
    upd2 = mgr.on_bar(same_bar)
    # 2eme appel return None (idempotent)
    assert upd2.new_sl is None


def test_timeout_after_90_bars():
    """Apres timeout_bars * 60s = 5400 secondes (= 90 min), is_timeout=True."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry_ts = 1_000_000_000_000_000_000
    entry = _bar(entry_ts, high=30010.0, low=30000.0, close=30005.0)
    mgr.start(direction="long", entry_bar=entry, entry_price=30005.0)
    # bar a 91 minutes apres entry
    far_ts = entry_ts + 91 * 60 * 1_000_000_000
    upd = mgr.on_bar(_bar(far_ts, high=30015.0, low=30008.0, close=30012.0))
    assert upd.is_timeout is True


def test_inactive_returns_error():
    """on_bar sans start() prealable -> error TRAILING_INACTIVE."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    upd = mgr.on_bar(_bar(1_000_000_000_000_000_000, high=30010, low=30000, close=30005))
    assert upd.error == "TRAILING_INACTIVE"
    assert mgr.is_active() is False


def test_stop_resets_state():
    """stop() reset state pour reutilisation."""
    cfg = BotBNV4Config.from_env()
    mgr = TrailingManager(symbol="NQ", cfg=cfg)
    entry = _bar(1_000_000_000_000_000_000, high=30010, low=30000, close=30005)
    mgr.start(direction="long", entry_bar=entry, entry_price=30005)
    assert mgr.is_active() is True
    mgr.stop()
    assert mgr.is_active() is False
    assert mgr.get_current_sl() is None
