"""Tests Phase 1 Group A - integration sierra_pipeline avec 4 modules."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _sample_bar(ts_ns: int, close: float, delta_bar: float = 0.0, **kwargs) -> dict:
    base = {
        "ts_event_ns": ts_ns, "close": close, "price": close,
        "open": close - 5, "bar_high": close + 5, "bar_low": close - 5,
        "high": close + 5, "low": close - 5,
        "total_vol": 50, "buy_vol": 25, "sell_vol": 25,
        "avg_ask_size": 2.0, "avg_bid_size": 2.0,
        "bool_gex_flip_zone": 1, "atr": 692, "delta_bar": delta_bar,
        "dist_swing_high": 20, "dist_swing_low": 15, "dist_cur_vpoc": 10,
        "ask_pct": 0.5, "bid_pct": 0.5,
        "bn_color_up": 0, "bn_color_dn": 0,
        "bn_long_up": 0, "bn_long_dn": 0,
        "bn_absorb_ask": 0, "bn_absorb_bid": 0,
    }
    base.update(kwargs)
    return base


def test_cvd_session_cumsum_correct():
    """A1 - cvd_session cumsum delta_bar."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    out1 = pipe.enrich_bar(_sample_bar(1781170560000000000, 28869, delta_bar=10.0))
    out2 = pipe.enrich_bar(_sample_bar(1781170620000000000, 28870, delta_bar=-5.0))
    assert out1["cvd_session"] == 10.0
    assert out2["cvd_session"] == 5.0


def test_long_bar_features_present():
    """A2 - long_up_bar, long_dn_bar, bar_body_ticks presents."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    out = pipe.enrich_bar(_sample_bar(1781170560000000000, 28869))
    assert "long_up_bar" in out
    assert "long_dn_bar" in out
    assert "bar_body_ticks" in out


def test_color_bar_features_present():
    """A3 - color features lag-1 presents (None tant que prev pas la)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Process 2 bars pour avoir lag-1 actif
    pipe.enrich_bar(_sample_bar(1781170560000000000, 28869))
    out2 = pipe.enrich_bar(_sample_bar(1781170620000000000, 28890))
    assert "n_color_up_cluster_within_0_2pct" in out2 or "dist_color_up_nearest_pct" in out2


def test_bn_composites_python_override_sierra_zero():
    """B3 - bn_score_raw Python override Sierra=0 via whitelist."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Sierra emet bn_score_raw=0.0 (placeholder), Python recalcule
    bar = _sample_bar(1781170560000000000, 28869,
                       bn_score_raw=0.0,  # Sierra placeholder
                       bn_color_up=1, bn_long_up=1)
    out = pipe.enrich_bar(bar)
    # Python a calcule (1+1.5)/3.5 = 0.7143
    expected = (1.0 + 1.5) / 3.5
    assert abs(out["bn_score_raw"] - expected) < 1e-4


def test_bn_pressure_ask_preserves_sierra_nonzero():
    """CRITIQUE review fix : Sierra bn_pressure_ask=1.0 (Double/Triple Ask) NE doit
    PAS etre ecrase par Python. Whitelist retiree 11/06."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    bar = _sample_bar(1781170560000000000, 28869,
                       bn_pressure_ask=1.0, bn_pressure_bid=0.0,
                       ask_pct=0.55, bid_pct=0.45)
    out = pipe.enrich_bar(bar)
    # Sierra signal 1.0 preserve (PAS ecrase par alias 0.55)
    assert out["bn_pressure_ask"] == 1.0
    # Sierra 0.0 preserve (PAS ecrase par 0.45 - bn_pressure pas dans whitelist)
    assert out["bn_pressure_bid"] == 0.0


def test_bn_score_python_override_preserved():
    """Sierra bn_score_raw=0.0 placeholder -> Python override active (whitelist)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    bar = _sample_bar(1781170560000000000, 28869,
                       bn_score_raw=0.0,  # placeholder Sierra
                       bn_color_up=1, bn_long_up=1)
    out = pipe.enrich_bar(bar)
    expected = (1.0 + 1.5) / 3.5
    assert abs(out["bn_score_raw"] - expected) < 1e-4


def test_cvd_session_cross_day_reset():
    """A1 - cvd_session reset au changement de jour."""
    from datetime import date, timedelta, timezone
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Bar 1 jour J
    bar1 = _sample_bar(1781170560000000000, 28869, delta_bar=50.0)
    pipe.enrich_bar(bar1)
    # Bar 2 jour J+1 (force cross-day via timestamp +1 jour)
    bar2 = _sample_bar(1781170560000000000 + 86400_000_000_000, 28870, delta_bar=10.0)
    out2 = pipe.enrich_bar(bar2)
    # cvd_session devrait etre reset puis +10 = 10.0 (pas 60.0)
    assert out2["cvd_session"] == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
