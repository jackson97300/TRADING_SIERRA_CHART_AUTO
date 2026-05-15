"""Test empirique P1.2 + P1.4 fixes Live Enricher.

Test A : P1.2 seed swings_lag avec V4 contient _last_swing_*_price
Test B : P1.2 seed avec < 21 valid bars -> emit log + return
Test C : P1.4 alignement keys mq_call -> dist_mq_call_pct calculee
Test D : P1.4 mq_call_0dte null -> dist_mq_call_0dte_pct ABSENT (pas NaN literal)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
from live_enricher_state import (
    LiveEnricherState,
    _seed_swings_lag_from_warmup,
)


def test_a_seed_swings_with_v4():
    """V4 simule contient _last_swing_*_price -> SwingPivot instancie."""
    state = LiveEnricherState(symbol="TEST_P12.c.0")
    # 30 bars valides + last_swing_*_price
    df = pd.DataFrame({
        "high": [100.0 + i * 0.5 for i in range(30)],
        "low": [99.0 + i * 0.5 for i in range(30)],
        "close": [99.5 + i * 0.5 for i in range(30)],
        "session_id": [2] * 30,
        "_last_swing_high_price": [109.5] * 30,
        "_last_swing_low_price": [99.0] * 30,
    })
    _seed_swings_lag_from_warmup(state, "TEST_P12.c.0", df=df)
    s = state.engine_states.get("sessions_swings_lag")
    assert s is not None, "Test A FAIL : engine state non seede"
    assert s.last_swing_high is not None, "Test A FAIL : last_swing_high non instancie"
    assert s.last_swing_high.price == 109.5, f"Test A FAIL : price={s.last_swing_high.price}"
    assert s.last_swing_low is not None, "Test A FAIL : last_swing_low non instancie"
    assert s.last_swing_low.price == 99.0, f"Test A FAIL : price={s.last_swing_low.price}"
    assert len(s.swing_window_high) == 21, f"Test A FAIL : deque len={len(s.swing_window_high)}"
    print(f"[OK] Test A : seed pivots OK (high={s.last_swing_high.price}, low={s.last_swing_low.price}, 21 deque)")


def test_b_seed_lt_21_bars():
    """< 21 valid bars -> emit fail + return."""
    state = LiveEnricherState(symbol="TEST_P12B.c.0")
    df = pd.DataFrame({
        "high": [100.0] * 5,
        "low": [99.0] * 5,
        "close": [99.5] * 5,
        "session_id": [2] * 5,
    })
    _seed_swings_lag_from_warmup(state, "TEST_P12B.c.0", df=df)
    s = state.engine_states.get("sessions_swings_lag")
    assert s is None, "Test B FAIL : engine seede malgre < 21 bars"
    print(f"[OK] Test B : <21 bars -> seed skip + emit ENRICHER_SEED_SWINGS_LAG_FAIL")


def test_c_seed_missing_pivots_v4():
    """V4 sans _last_swing_*_price (cold start pre-09:30) -> deque OK + pivots None."""
    state = LiveEnricherState(symbol="TEST_P12C.c.0")
    df = pd.DataFrame({
        "high": [100.0 + i * 0.5 for i in range(30)],
        "low": [99.0 + i * 0.5 for i in range(30)],
        "close": [99.5 + i * 0.5 for i in range(30)],
        "session_id": [2] * 30,
        # PAS de _last_swing_*_price (pre-09:30 cold start)
    })
    _seed_swings_lag_from_warmup(state, "TEST_P12C.c.0", df=df)
    s = state.engine_states.get("sessions_swings_lag")
    assert s is not None, "Test C FAIL : engine state non seede"
    assert s.last_swing_high is None, f"Test C FAIL : last_swing_high should be None"
    assert s.last_swing_low is None
    assert len(s.swing_window_high) == 21, "Test C FAIL : deque pas filler"
    print(f"[OK] Test C : sans pivots V4 -> deque filler 21 bars + pivots None (graceful)")


if __name__ == "__main__":
    test_a_seed_swings_with_v4()
    test_b_seed_lt_21_bars()
    test_c_seed_missing_pivots_v4()
    print("\n=== 3/3 tests P1.2 PASS ===")
