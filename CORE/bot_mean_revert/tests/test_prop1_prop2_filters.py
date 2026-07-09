"""Tests PROP #1 (momentum_5b filter) + PROP #2 (skip session AH).

REFERENCE :
- Audit market-analyst 24/06/2026 sur 7 jours 16-24/06 (67 trades).
- PROP #1 momentum_5b :
    - mom_5b <= -5 : WR 6.7% (1 TP / 21 SL+MH), n=22
    - mom_5b <= -10: WR 0% (0/7) - catch falling knife garanti
    - mom_5b >= 0  : WR 51.7% - bull bar = signal
    - Backtest : sacrifice 1 win (4.5%), +$1912 retroactif.
- PROP #2 skip AH (21h-24h UTC) :
    - 0/10 TP sur 7 jours (0% WR) - carnage total
    - Backtest : sacrifice 0 win, evite 5 SL, +$875.

CES TESTS PROUVENT :
- LONG bloque si momentum_5b < -5 (default)
- SHORT bloque si momentum_5b > +5 (default)
- AH skip si hour UTC in [21, 24[
- Defaults sains, env override fonctionnel
- Edge case bar ts corrompu = fail-open (pas de block)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ts_us(dt: datetime) -> int:
    """Convert datetime to epoch ms (matches sierra_enriched convention)."""
    return int(dt.timestamp() * 1000)


def _make_bar(
    hour_utc: int = 15,
    momentum_5b: float = 0.0,
    sd3d_pct: float = -0.05,
    sd3u_pct: float = 0.5,
    **overrides,
) -> dict:
    """Bar minimal qui declenche LONG (sd3d proche 0)."""
    bar_dt = datetime(2026, 6, 24, hour_utc, 15, 0, tzinfo=timezone.utc)
    bar = {
        "ts": _ts_us(bar_dt),
        "ts_event": bar_dt.isoformat(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0,
        "bar_low": 5799.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": sd3d_pct,
        "dist_vwap_d_sd3u_pct": sd3u_pct,
        "dist_vwap_d_pct": 0.1,
        "vwap_slope_30": 0.05,
        "delta_bar": -50.0,  # bear bar pour passer ULTRATHINK LONG
        "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "momentum_5b": momentum_5b,
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
# PROP #1 - momentum_5b filter
# ==========================================================================

def test_prop1_long_blocked_when_momentum_too_bear(tmp_path):
    """LONG bloque si momentum_5b < MIN_LONG (default -5)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p1_long_block.json")
    eng = SignalEngine("ES", cfg, store=store)

    # momentum_5b = -10 (tres bear) < -5 -> bloque
    bar = _make_bar(momentum_5b=-10.0, hour_utc=15)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "MOMENTUM_5B_TOO_BEAR_LONG" in sig.skip_reason
    assert "mom_5b=-10.0" in sig.skip_reason


def test_prop1_long_passes_when_momentum_neutral(tmp_path):
    """LONG passe le filtre momentum si mom_5b >= MIN_LONG."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p1_long_pass.json")
    eng = SignalEngine("ES", cfg, store=store)

    # momentum_5b = -2 (neutre faible) >= -5 -> pass momentum
    bar = _make_bar(momentum_5b=-2.0, hour_utc=15)
    sig = eng.evaluate(bar)
    # On peut etre bloque par autre gate, mais pas par momentum
    assert "MOMENTUM_5B_TOO_BEAR_LONG" not in sig.skip_reason


def test_prop1_long_boundary_exact_minus_5(tmp_path):
    """Edge : momentum_5b == MIN_LONG (-5) exact = NOT blocked (strict <)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p1_boundary.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(momentum_5b=-5.0, hour_utc=15)
    sig = eng.evaluate(bar)
    # mom=-5 strict < -5 == False -> pass
    assert "MOMENTUM_5B_TOO_BEAR_LONG" not in sig.skip_reason


def test_prop1_short_blocked_when_momentum_too_bull(tmp_path):
    """SHORT bloque si momentum_5b > MAX_SHORT (default +5)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p1_short_block.json")
    eng = SignalEngine("ES", cfg, store=store)

    # Setup pour SHORT trigger : sd3u proche 0, sd3d loin
    # momentum_5b = +10 (tres bull) > +5 -> bloque SHORT
    bar = _make_bar(
        momentum_5b=+10.0, hour_utc=15,
        sd3d_pct=-0.5, sd3u_pct=0.05,
        delta_bar=+50.0,  # bull bar pour passer ULTRATHINK SHORT
        finish_strength=-1.0,
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "MOMENTUM_5B_TOO_BULL_SHORT" in sig.skip_reason


def test_prop1_filter_disabled_via_env(tmp_path, monkeypatch):
    """Disable filter via env MOMENTUM_5B_FILTER_ENABLED=false."""
    monkeypatch.setenv("BOTMR_MOMENTUM_5B_FILTER_ENABLED", "false")
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig.from_env()
    assert cfg.MOMENTUM_5B_FILTER_ENABLED is False

    store = PositionStore(path=tmp_path / "test_p1_disabled.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(momentum_5b=-20.0)  # tres bear
    sig = eng.evaluate(bar)
    # Filter disabled -> pas de block momentum
    assert "MOMENTUM_5B_TOO_BEAR_LONG" not in sig.skip_reason


def test_prop1_thresholds_env_override(monkeypatch):
    """Env override MIN_LONG / MAX_SHORT fonctionnel."""
    monkeypatch.setenv("BOTMR_MOMENTUM_5B_MIN_LONG", "-3.0")
    monkeypatch.setenv("BOTMR_MOMENTUM_5B_MAX_SHORT", "7.5")
    from CORE.bot_mean_revert.config import BotMRConfig

    cfg = BotMRConfig.from_env()
    assert cfg.MOMENTUM_5B_MIN_LONG == -3.0
    assert cfg.MOMENTUM_5B_MAX_SHORT == 7.5


# ==========================================================================
# PROP #2 - Skip session AH (21h-24h UTC)
# ==========================================================================

@pytest.mark.parametrize("hour", [21, 22, 23])
def test_prop2_ah_blocks_during_session(tmp_path, hour):
    """Block toute heure UTC dans [21h, 24h[."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / f"test_p2_ah_{hour}.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(hour_utc=hour)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SESSION_AH_BLOCK" in sig.skip_reason
    assert f"hour={hour}h" in sig.skip_reason


@pytest.mark.parametrize("hour", [0, 5, 13, 20])
def test_prop2_non_ah_passes(tmp_path, hour):
    """Heures hors AH passent le gate."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / f"test_p2_non_ah_{hour}.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(hour_utc=hour)
    sig = eng.evaluate(bar)
    assert "SESSION_AH_BLOCK" not in sig.skip_reason


def test_prop2_ah_boundary_21h_exact(tmp_path):
    """21h00 UTC exact = AH start = blocked."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p2_21h.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(hour_utc=21)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SESSION_AH_BLOCK" in sig.skip_reason


def test_prop2_ah_filter_disabled_via_env(tmp_path, monkeypatch):
    """Disable via env."""
    monkeypatch.setenv("BOTMR_SKIP_AH_SESSION_ENABLED", "false")
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig.from_env()
    assert cfg.SKIP_AH_SESSION_ENABLED is False

    store = PositionStore(path=tmp_path / "test_p2_disabled.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(hour_utc=22)  # AH
    sig = eng.evaluate(bar)
    # Filter disabled -> ne block pas par AH
    assert "SESSION_AH_BLOCK" not in sig.skip_reason


def test_prop2_ah_hours_env_override(monkeypatch):
    """Customize AH hours via env."""
    monkeypatch.setenv("BOTMR_AH_SESSION_START_UTC_HOUR", "22")
    monkeypatch.setenv("BOTMR_AH_SESSION_END_UTC_HOUR", "23")
    from CORE.bot_mean_revert.config import BotMRConfig

    cfg = BotMRConfig.from_env()
    assert cfg.AH_SESSION_START_UTC_HOUR == 22
    assert cfg.AH_SESSION_END_UTC_HOUR == 23


def test_prop2_corrupted_bar_ts_fail_open(tmp_path):
    """Bar ts corrompu = pas de block (fail-open, ne casse pas le trading)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_p2_corrupted.json")
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(hour_utc=15)
    bar["ts"] = "not_a_number"  # corruption
    sig = eng.evaluate(bar)
    # Fail-open : ne block pas par AH (ne casse pas le trading)
    assert "SESSION_AH_BLOCK" not in sig.skip_reason
