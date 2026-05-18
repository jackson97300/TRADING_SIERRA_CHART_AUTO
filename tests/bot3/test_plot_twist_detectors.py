"""tests/bot3/test_plot_twist_detectors.py - Tests Phase 2 PlotTwistDetectors.

Tests pytest pour `CORE/bot3_plot_twist_detectors.py`.
Coverage cible >= 90%. Tests par detector + integration scan_all + throttle + pickle.

HISTORY
2026-05-18 PM : creation tests Phase 2 J+1 (4 detectors x ~5 tests + integration)
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import pytest

from CORE.bot3_plot_twist_detectors import (
    BARS_HISTORY_MAXLEN,
    CAPITULATION_BARS_REQUIRED,
    DIVERGENCE_PRICE_LOOKBACK,
    PlotTwist,
    PlotTwistDetectorsState,
    THROTTLE_TWIST_BARS,
    VOL_Z_ANOMALY_MIN,
    VOL_Z_CAPITULATION_MIN,
    detect_capitulation,
    detect_divergence,
    detect_structure_break,
    detect_volume_anomaly,
    scan_all,
)


# ─── Stubs ────────────────────────────────────────────────────────────────


@dataclass
class StubSwingPoint:
    price: float = 0.0
    bar_idx: int = -1


@dataclass
class StubSwingState:
    last_swing_high: StubSwingPoint = field(default_factory=StubSwingPoint)
    last_swing_low: StubSwingPoint = field(default_factory=StubSwingPoint)


def _make_bar(
    ts: str = "2026-05-18T13:30:00Z",
    close: float = 100.0,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    atr: float = 5.0,
    vol_z: float = 0.0,
    cvd: float = 0.0,
) -> dict:
    return {
        "ts_event_iso": ts,
        "close": close,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "atr": atr,
        "vol_zscore_20": vol_z,
        "cvd_5d_rolling_ffd": cvd,
    }


# ════════════════════════════════════════════════════════════════════════════
# STRUCTURE_BREAK (ICT BOS/CHoCH)
# ════════════════════════════════════════════════════════════════════════════


def test_structure_break_bullish_BOS():
    """close > swing_high + 2*tick + vol_z>0 → STRUCTURE_BREAK direction=+1."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 10
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    bar = _make_bar(close=100.6, vol_z=1.0)  # 100.6 > 100 + 2*0.25=100.5
    twist = detect_structure_break(state, bar, swing, tick_size=0.25)
    assert twist is not None
    assert twist.twist_type == "STRUCTURE_BREAK"
    assert twist.direction == +1
    assert twist.severity > 0


def test_structure_break_bearish_BOS():
    """close < swing_low - 2*tick + vol_z>0 → STRUCTURE_BREAK direction=-1."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 10
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    bar = _make_bar(close=99.4, vol_z=1.0)  # 99.4 < 100 - 0.5 = 99.5
    twist = detect_structure_break(state, bar, swing, tick_size=0.25)
    assert twist is not None
    assert twist.direction == -1


def test_structure_break_no_fire_if_vol_z_negative():
    """close casse swing mais vol_z <= 0 = pas de confirmation acceptance."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 10
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    bar = _make_bar(close=101.0, vol_z=-0.5)  # vol_z<=0
    twist = detect_structure_break(state, bar, swing, tick_size=0.25)
    assert twist is None


def test_structure_break_throttle_anti_double_fire():
    """2 BOS bullish consecutifs < 3 bars : seul le 1er fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 10
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    bar1 = _make_bar(close=101.0, vol_z=1.0)
    t1 = detect_structure_break(state, bar1, swing)
    assert t1 is not None
    # Bar suivante (1 bar plus tard) : same direction = throttled
    state.bar_idx_current = 11
    bar2 = _make_bar(close=101.5, vol_z=1.0)
    t2 = detect_structure_break(state, bar2, swing)
    assert t2 is None


def test_structure_break_handles_missing_swing_state():
    """swing_state None : ne fire pas (pas de reference)."""
    state = PlotTwistDetectorsState(symbol="ES")
    bar = _make_bar(close=105.0, vol_z=1.5)
    twist = detect_structure_break(state, bar, None)
    assert twist is None


# ════════════════════════════════════════════════════════════════════════════
# VOLUME_ANOMALY (Wyckoff climax)
# ════════════════════════════════════════════════════════════════════════════


def test_volume_anomaly_fires_at_threshold():
    """vol_z > VOL_Z_ANOMALY_MIN (=2.5) → VOLUME_ANOMALY."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.8)  # > 2.5
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    assert twist.twist_type == "VOLUME_ANOMALY"
    assert twist.severity > 0


def test_volume_anomaly_direction_from_close_vs_open():
    """close < open + vol_z>VOL_Z_ANOMALY_MIN = selling climax direction=-1."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=98.0, open_=102.0, vol_z=3.0)
    twist = detect_volume_anomaly(state, bar)
    assert twist is not None
    assert twist.direction == -1


def test_volume_anomaly_no_fire_below_threshold():
    """vol_z < VOL_Z_ANOMALY_MIN (=2.5) : no fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.0)  # < 2.5
    twist = detect_volume_anomaly(state, bar)
    assert twist is None


def test_volume_anomaly_throttle():
    """2 fires consecutifs < 3 bars apart : seul le 1er fire."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    bar = _make_bar(close=100.0, vol_z=2.8)
    t1 = detect_volume_anomaly(state, bar)
    assert t1 is not None
    state.bar_idx_current = 6
    t2 = detect_volume_anomaly(state, bar)
    assert t2 is None


# ════════════════════════════════════════════════════════════════════════════
# DIVERGENCE (price vs CVD - Wyckoff effort/result)
# ════════════════════════════════════════════════════════════════════════════


def test_divergence_requires_min_history():
    """< DIVERGENCE_PRICE_LOOKBACK bars : pas de divergence."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 1
    bar = _make_bar(close=100.0, cvd=1000.0)
    twist = detect_divergence(state, bar)
    assert twist is None


def test_divergence_bearish_price_HH_cvd_DOWN():
    """high actuel > high(N) ET cvd actuel < cvd(N) → divergence -1."""
    state = PlotTwistDetectorsState(symbol="ES")
    # Fill bars_history avec high decroissant + cvd croissant (reference de base)
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": 2000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    # bar actuelle : new HH mais CVD descend = bearish divergence
    bar = _make_bar(close=110.0, high=110.5, cvd=1000.0)  # high>105, cvd<2000
    twist = detect_divergence(state, bar)
    assert twist is not None
    assert twist.direction == -1


def test_divergence_bullish_price_LL_cvd_UP():
    """low actuel < low(N) ET cvd actuel > cvd(N) → divergence +1."""
    state = PlotTwistDetectorsState(symbol="ES")
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": -1000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    bar = _make_bar(close=90.0, low=89.5, cvd=500.0)  # low<95, cvd>-1000
    twist = detect_divergence(state, bar)
    assert twist is not None
    assert twist.direction == +1


def test_divergence_no_fire_if_price_and_cvd_aligned():
    """Price + CVD vont meme direction : pas de divergence."""
    state = PlotTwistDetectorsState(symbol="ES")
    for i in range(DIVERGENCE_PRICE_LOOKBACK + 1):
        state.bars_history.append({
            "high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0,
            "vol_z": 0.0, "atr": 5.0, "cvd": 1000.0, "bar_idx": i,
        })
    state.bar_idx_current = 10
    bar = _make_bar(close=110.0, high=110.5, cvd=3000.0)  # HH + CVD up = aligne
    twist = detect_divergence(state, bar)
    assert twist is None


# ════════════════════════════════════════════════════════════════════════════
# CAPITULATION (3+ bars climax consecutifs)
# ════════════════════════════════════════════════════════════════════════════


def test_capitulation_requires_3_consecutive_climax():
    """1 bar climax = pas de capitulation (besoin 3 consecutifs)."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 1
    # Bar climax : vol_z>2.5 + range>1.5*atr
    bar = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                    atr=5.0, vol_z=3.0)  # range=13 > 1.5*5=7.5
    twist = detect_capitulation(state, bar)
    assert twist is None  # 1 seule bar


def test_capitulation_fires_after_3_consecutive():
    """3 bars consecutifs climax → CAPITULATION."""
    state = PlotTwistDetectorsState(symbol="ES")
    bar_template = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                              atr=5.0, vol_z=3.5)  # > VOL_Z_CAPITULATION_MIN=3.0
    state.bar_idx_current = 1
    detect_capitulation(state, bar_template)
    state.bar_idx_current = 2
    detect_capitulation(state, bar_template)
    state.bar_idx_current = 3
    twist = detect_capitulation(state, bar_template)
    assert twist is not None
    assert twist.twist_type == "CAPITULATION"
    assert twist.direction == -1  # close<open = selling capitulation


def test_capitulation_reset_on_non_climax_bar():
    """climax-climax-NORMAL-climax = pas 3 consecutifs."""
    state = PlotTwistDetectorsState(symbol="ES")
    climax = _make_bar(close=98.0, open_=102.0, high=105.0, low=92.0,
                       atr=5.0, vol_z=3.0)
    normal = _make_bar(close=100.0, vol_z=1.0)  # pas climax
    state.bar_idx_current = 1
    detect_capitulation(state, climax)
    state.bar_idx_current = 2
    detect_capitulation(state, climax)
    state.bar_idx_current = 3
    detect_capitulation(state, normal)  # reset buffer
    assert len(state.climax_buffer) == 0
    state.bar_idx_current = 4
    twist = detect_capitulation(state, climax)
    assert twist is None  # buffer juste reset, 1 bar


def test_capitulation_direction_bullish():
    """3 bars close>open + climax → CAPITULATION direction=+1 (buying climax)."""
    state = PlotTwistDetectorsState(symbol="ES")
    bar = _make_bar(close=102.0, open_=98.0, high=105.0, low=92.0,
                    atr=5.0, vol_z=3.5)  # > VOL_Z_CAPITULATION_MIN=3.0
    for i in range(1, 4):
        state.bar_idx_current = i
        result = detect_capitulation(state, bar)
    assert result is not None
    assert result.direction == +1


# ════════════════════════════════════════════════════════════════════════════
# scan_all integration
# ════════════════════════════════════════════════════════════════════════════


def test_scan_all_increments_bar_idx():
    """Chaque scan_all increment bar_idx_current."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(5):
        scan_all(state, _make_bar(close=100.0), swing)
    assert state.bar_idx_current == 5


def test_scan_all_appends_bars_history():
    """bars_history.append apres detection (preserve lookback CVD)."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(15):
        scan_all(state, _make_bar(close=100.0 + i, cvd=1000.0 + i * 100), swing)
    assert len(state.bars_history) == BARS_HISTORY_MAXLEN  # ring buffer FIFO


def test_scan_all_multiple_twists_same_bar():
    """STRUCTURE_BREAK + VOLUME_ANOMALY peuvent fire ensemble sur 1 bar."""
    state = PlotTwistDetectorsState(symbol="ES")
    state.bar_idx_current = 5
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    # Bar BOS + climax volume + close<open (bearish)
    bar = _make_bar(close=101.0, open_=99.5, high=105.0, low=95.0,
                    atr=5.0, vol_z=3.0)  # > VOL_Z_ANOMALY_MIN=2.5
    # bar.close 101 > swing 100 + 0.5 + vol_z 3 > 0 → BOS+ fire
    # vol_z>2 → VOLUME_ANOMALY fire
    twists = scan_all(state, bar, swing)
    twist_types = {t.twist_type for t in twists}
    assert "STRUCTURE_BREAK" in twist_types
    assert "VOLUME_ANOMALY" in twist_types


def test_pickle_roundtrip_preserves_state():
    """Pickle dump/load preserve bars_history + climax_buffer + last_twist_bar_idx."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    for i in range(8):
        scan_all(state, _make_bar(close=100.0 + i, cvd=1000.0 + i * 100), swing)
    state.last_twist_bar_idx["TEST"] = 42

    blob = pickle.dumps(state)
    loaded = pickle.loads(blob)
    assert loaded.symbol == "ES"
    assert len(loaded.bars_history) == 8
    assert loaded.bar_idx_current == 8
    assert loaded.last_twist_bar_idx["TEST"] == 42
    # _lock recreee au load
    with loaded.lock:
        pass


def test_scan_all_handles_nan_gracefully():
    """Bars avec NaN ne crashent pas."""
    state = PlotTwistDetectorsState(symbol="ES")
    swing = StubSwingState()
    bar = {
        "ts_event_iso": "x",
        "close": float("nan"), "open": float("nan"),
        "high": float("nan"), "low": float("nan"),
        "atr": float("nan"), "vol_zscore_20": float("nan"),
        "cvd_5d_rolling_ffd": float("nan"),
    }
    twists = scan_all(state, bar, swing)
    assert isinstance(twists, list)  # pas de crash
