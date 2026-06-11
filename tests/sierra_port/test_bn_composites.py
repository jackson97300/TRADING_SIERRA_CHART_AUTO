"""Tests Phase 1 Group A - bn_composites_streaming."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_compute_bn_composites_neutral():
    """Inputs neutres -> tous 0."""
    from CORE.bn_composites_streaming import compute_bn_composites
    bar = {"bn_color_up": 0, "bn_color_dn": 0, "bn_long_up": 0,
           "bn_long_dn": 0, "bn_absorb_ask": 0, "bn_absorb_bid": 0}
    out = compute_bn_composites(bar)
    assert out["bn_score_raw"] == 0.0
    assert out["bn_score_bull"] == 0.0
    assert out["bn_score_bear"] == 0.0


def test_compute_bn_composites_bullish_max():
    """Full bullish : tous up -> normalise ~0.857 (3.0/3.5)."""
    from CORE.bn_composites_streaming import compute_bn_composites
    bar = {"bn_color_up": 1, "bn_color_dn": 0, "bn_color_up_2": 1,
           "bn_color_dn_2": 0, "bn_long_up": 1, "bn_long_dn": 0,
           "bn_absorb_ask": 1, "bn_absorb_bid": 0}
    out = compute_bn_composites(bar)
    expected = (1.0 + 0.5 + 1.5 + 0.5) / 3.5
    assert abs(out["bn_score_raw"] - expected) < 1e-6
    assert out["bn_score_bull"] == out["bn_score_raw"]
    assert out["bn_score_bear"] == 0.0


def test_compute_bn_composites_bearish_max():
    """Full bearish : tous dn -> ~-1.0 clamp."""
    from CORE.bn_composites_streaming import compute_bn_composites
    bar = {"bn_color_up": 0, "bn_color_dn": 1, "bn_color_up_2": 0,
           "bn_color_dn_2": 1, "bn_long_up": 0, "bn_long_dn": 1,
           "bn_absorb_ask": 0, "bn_absorb_bid": 1}
    out = compute_bn_composites(bar)
    expected = -(1.0 + 0.5 + 1.5 + 0.5) / 3.5
    assert abs(out["bn_score_raw"] - expected) < 1e-6
    assert out["bn_score_bull"] == 0.0
    assert out["bn_score_bear"] == abs(out["bn_score_raw"])


def test_compute_bn_composites_clamp():
    """Score > 1.0 -> clamp 1.0."""
    from CORE.bn_composites_streaming import compute_bn_composites
    bar = {"bn_color_up": 10, "bn_long_up": 10}
    out = compute_bn_composites(bar)
    assert out["bn_score_raw"] == 1.0


def test_compute_bn_composites_does_not_touch_pressure():
    """CRITIQUE review : bn_pressure_ask/bid VIVANTS Sierra, jamais touches."""
    from CORE.bn_composites_streaming import compute_bn_composites
    bar = {"bn_color_up": 1, "ask_pct": 0.7, "bid_pct": 0.3}
    out = compute_bn_composites(bar)
    # bn_pressure_ask et bn_pressure_bid NE doivent PAS etre dans output
    assert "bn_pressure_ask" not in out
    assert "bn_pressure_bid" not in out


def test_inject_bn_composites_routes_via_safe_update():
    """CRITIQUE review : inject doit utiliser safe_update_fn, pas payload.update brutal."""
    from CORE.bn_composites_streaming import inject_bn_composites
    payload = {"bn_color_up": 1, "bn_long_up": 1}
    called_with = []

    def fake_safe_update(p, new):
        called_with.append((id(p), dict(new)))
        p.update(new)  # simule comportement final

    inject_bn_composites(payload, safe_update_fn=fake_safe_update, sym="NQ")
    assert len(called_with) == 1
    assert called_with[0][0] == id(payload)
    assert "bn_score_raw" in called_with[0][1]
    # Pas bn_pressure_* dans le dict route
    assert "bn_pressure_ask" not in called_with[0][1]


def test_inject_bn_composites_logs_ok():
    """inject emit SIERRA_PORT_BN_COMPOSITES_OK."""
    from CORE.bn_composites_streaming import inject_bn_composites
    logs = []
    inject_bn_composites({}, safe_update_fn=lambda p, n: p.update(n),
                          log_fn=lambda c, **k: logs.append(c), sym="NQ")
    assert "SIERRA_PORT_BN_COMPOSITES_OK" in logs


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
