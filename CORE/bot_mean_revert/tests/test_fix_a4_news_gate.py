"""Tests Phase A4 audit forensique 22-23/06 - Fix A4 gate news/FOMC.

REFERENCE :
- Audit market-analyst 22-23/06 : 18/06 FOMC = Bot 1 a fait 16 trades pendant
  FOMC day 14:00 ET (-12 LOSS dont 9 MFE=0). Pas de news gate = bot tradait
  pendant le carnage.
- Module CORE/eco_calendar.py existant (utilise par Bot 3 v3 24/05) avec
  is_blocked_now() qui retourne (blocked, reason, blocked_until_utc) basee
  sur events FOMC/NFP/CPI/PCE/ECB avec BLOCK_WINDOWS configurees.
- Convention Bot 3 v3 R1 code-reviewer 24/05 : fail-CLOSED si module HS.

CES TESTS PROUVENT :
- Gate news bloque le trade quand event critique actif (mock is_blocked_now)
- Gate news laisse passer quand pas d'event
- Fail-CLOSED si module eco_calendar fail import/runtime
- Fail-OPEN si NEWS_GATE_FAIL_CLOSED=False (debug)
- Gate desactivable via NEWS_GATE_ENABLED=False
- Format skip_reason parsable par dispatcher main.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ts_now_us() -> int:
    return int(time.time() * 1e6)


def _make_bar(close_price: float = 5800.0, **overrides) -> dict:
    """Bar minimal valide qui declenche LONG (sd3d proche 0)."""
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": close_price,
        "bar_high": close_price + 1.0,
        "bar_low": close_price - 1.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.05,
        "dist_vwap_d_sd3u_pct": 0.5,
        "dist_vwap_d_pct": 0.1,
        "vwap_slope_30": 0.05,
        "delta_bar": 50.0,
        "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_mq_hvl_pct": 5.0,
        "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0,
        "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0,
        "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0,
        "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0,
        "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0,
        "dist_vwap_w_sd1d_pct": -3.0,
    }
    bar.update(overrides)
    return bar


# ==========================================================================
# Fix A4 — Gate news/FOMC
# ==========================================================================

def test_a4_news_blocks_when_event_active(tmp_path):
    """A4: gate bloque trade quand is_blocked_now() retourne True (FOMC active)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()  # NEWS_GATE_ENABLED=True default
    store = PositionStore(path=tmp_path / "test_a4_block.json")
    eng = SignalEngine("ES", cfg, store=store)

    # Mock eco_calendar.is_blocked_now() pour simuler FOMC active
    block_end = datetime.now(timezone.utc) + timedelta(minutes=20)
    with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
        mock_news.return_value = (True, "FOMC Rate Decision (US)", block_end)
        sig = eng.evaluate(_make_bar())

    assert sig.tradable is False
    assert "NEWS_BLOCK" in sig.skip_reason, f"got {sig.skip_reason}"
    assert "FOMC" in sig.skip_reason
    assert "buffer_min" in sig.skip_reason


def test_a4_news_passes_when_no_event(tmp_path):
    """A4: gate laisse passer quand pas d'event (is_blocked_now retourne False)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a4_pass.json")
    eng = SignalEngine("ES", cfg, store=store)

    with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
        mock_news.return_value = (False, None, None)
        sig = eng.evaluate(_make_bar())

    # On va plus loin que le gate news (peut etre bloque par autres gates,
    # mais pas par NEWS_BLOCK)
    assert "NEWS_BLOCK" not in sig.skip_reason
    assert "NEWS_GATE_FAIL_CLOSED" not in sig.skip_reason


def test_a4_fail_closed_when_module_fails(tmp_path):
    """A4: fail-CLOSED si eco_calendar leve une exception (convention Bot 3 v3)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()  # NEWS_GATE_FAIL_CLOSED=True default
    store = PositionStore(path=tmp_path / "test_a4_fail_closed.json")
    eng = SignalEngine("ES", cfg, store=store)

    with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
        mock_news.side_effect = RuntimeError("network timeout fetch_events")
        sig = eng.evaluate(_make_bar())

    assert sig.tradable is False
    assert "NEWS_GATE_FAIL_CLOSED" in sig.skip_reason, f"got {sig.skip_reason}"
    assert "network timeout" in sig.skip_reason


def test_a4_fail_open_when_disabled_config(tmp_path):
    """A4: fail-OPEN debug si NEWS_GATE_FAIL_CLOSED=False et module fail."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    os.environ["BOTMR_NEWS_GATE_FAIL_CLOSED"] = "false"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.NEWS_GATE_FAIL_CLOSED is False
        store = PositionStore(path=tmp_path / "test_a4_fail_open.json")
        eng = SignalEngine("ES", cfg, store=store)

        with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
            mock_news.side_effect = RuntimeError("module HS")
            sig = eng.evaluate(_make_bar())

        # En mode fail-open, la decision continue (peut etre bloque ailleurs)
        assert "NEWS_GATE_FAIL_CLOSED" not in sig.skip_reason
        assert "NEWS_BLOCK" not in sig.skip_reason
    finally:
        del os.environ["BOTMR_NEWS_GATE_FAIL_CLOSED"]


def test_a4_gate_disabled_skips_check(tmp_path):
    """A4: NEWS_GATE_ENABLED=False desactive completement le check."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    os.environ["BOTMR_NEWS_GATE_ENABLED"] = "false"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.NEWS_GATE_ENABLED is False
        store = PositionStore(path=tmp_path / "test_a4_disabled.json")
        eng = SignalEngine("ES", cfg, store=store)

        # Meme avec mock disant "FOMC active", le gate ne devrait pas etre check
        with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
            mock_news.return_value = (True, "FOMC active", None)
            sig = eng.evaluate(_make_bar())
            # Le mock ne doit PAS etre appele car gate disabled
            assert not mock_news.called, "is_blocked_now ne doit PAS etre appele si gate disabled"
    finally:
        del os.environ["BOTMR_NEWS_GATE_ENABLED"]


def test_a4_skip_reason_parsable_by_dispatcher(tmp_path):
    """A4: format skip_reason robuste pour parsing dispatcher main.py.

    Anti-regression : si quelqu'un change le format, dispatcher casse silencieux.
    """
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a4_parse.json")
    eng = SignalEngine("ES", cfg, store=store)

    block_end = datetime(2026, 6, 23, 14, 30, 0, tzinfo=timezone.utc)
    with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
        mock_news.return_value = (True, "FOMC Statement (US)", block_end)
        sig = eng.evaluate(_make_bar())

    # Verifier format strict attendu par dispatcher
    skip = sig.skip_reason
    assert skip.startswith("NEWS_BLOCK:")
    assert "event=" in skip
    assert "until=" in skip
    assert "buffer_min=" in skip

    # Reproduire parsing dispatcher
    payload = skip.split(":", 1)[1]
    event_val = payload.split("event=", 1)[1].split(" until=", 1)[0]
    until_val = payload.split("until=", 1)[1].split(" buffer_min=", 1)[0]
    buffer_val = payload.split("buffer_min=", 1)[1].strip()
    assert "FOMC" in event_val
    assert "2026-06-23" in until_val
    # buffer_val est un int parsable
    int(buffer_val)


def test_a4_config_env_override():
    """A4: env vars NEWS_GATE_ENABLED / FAIL_CLOSED fonctionnels."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig

    os.environ["BOTMR_NEWS_GATE_ENABLED"] = "false"
    os.environ["BOTMR_NEWS_GATE_FAIL_CLOSED"] = "false"
    cfg = BotMRConfig.from_env()
    assert cfg.NEWS_GATE_ENABLED is False
    assert cfg.NEWS_GATE_FAIL_CLOSED is False
    del os.environ["BOTMR_NEWS_GATE_ENABLED"]
    del os.environ["BOTMR_NEWS_GATE_FAIL_CLOSED"]


def test_a4_block_end_none_buffer_zero(tmp_path):
    """A4: si block_end is None (event sans fin definie), buffer_min=0."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a4_no_end.json")
    eng = SignalEngine("ES", cfg, store=store)

    with patch("CORE.eco_calendar.is_blocked_now") as mock_news:
        mock_news.return_value = (True, "Generic event", None)
        sig = eng.evaluate(_make_bar())

    assert sig.tradable is False
    assert "NEWS_BLOCK" in sig.skip_reason
    assert "buffer_min=0" in sig.skip_reason
    assert "until=?" in sig.skip_reason
