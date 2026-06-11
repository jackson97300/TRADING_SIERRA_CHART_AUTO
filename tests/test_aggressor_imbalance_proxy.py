"""Tests Phase 5.0.B aggressor_imbalance_proxy."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_proxy_balanced_returns_zero():
    """Cas equilibre : buy_vol == sell_vol AND avg_sizes egales -> 0.0."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    assert compute_aggressor_imbalance_proxy(100.0, 100.0, 2.0, 2.0) == 0.0


def test_proxy_buyers_dominate_positive():
    """Real sample NQ 11/06 : buy=138 sell=74 avg_ask=2.22 avg_bid=1.90 -> ~0.228."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    val = compute_aggressor_imbalance_proxy(138.0, 74.0, 2.2258, 1.8974)
    assert val is not None
    assert 0.20 < val < 0.30  # ~0.228


def test_proxy_sellers_dominate_negative():
    """Sellers : buy=50 sell=200 -> proxy < 0."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    val = compute_aggressor_imbalance_proxy(50.0, 200.0, 2.0, 2.0)
    assert val is not None
    assert val < 0.0
    # n_buy=25, n_sell=100, total=125 -> (25-100)/125 = -0.6
    assert abs(val - (-0.6)) < 0.001


def test_proxy_zero_total_returns_zero():
    """Cas bar muette : tous les vols a 0 -> 0.0 (fail-safe)."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    assert compute_aggressor_imbalance_proxy(0.0, 0.0, 0.0, 0.0) == 0.0


def test_proxy_none_inputs_returns_none():
    """Si un input None -> None (fail-closed downstream)."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    assert compute_aggressor_imbalance_proxy(None, 100.0, 2.0, 2.0) is None
    assert compute_aggressor_imbalance_proxy(100.0, None, 2.0, 2.0) is None
    assert compute_aggressor_imbalance_proxy(100.0, 100.0, None, 2.0) is None
    assert compute_aggressor_imbalance_proxy(100.0, 100.0, 2.0, None) is None


def test_proxy_invalid_string_returns_none():
    """Inputs invalides type -> None."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    assert compute_aggressor_imbalance_proxy("invalid", 100.0, 2.0, 2.0) is None
    assert compute_aggressor_imbalance_proxy(100.0, [1], 2.0, 2.0) is None


def test_proxy_nan_inputs_returns_none():
    """Inputs NaN -> None."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    nan = float('nan')
    assert compute_aggressor_imbalance_proxy(nan, 100.0, 2.0, 2.0) is None
    assert compute_aggressor_imbalance_proxy(100.0, 100.0, nan, 2.0) is None


def test_proxy_avg_size_negative_treated_as_zero():
    """avg_size < 0 (anomalie Sierra) : traite comme zero, no negative count."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    val = compute_aggressor_imbalance_proxy(100.0, 100.0, -1.0, -1.0)
    assert val == 0.0  # avg_ask<=0 AND avg_bid<=0 -> bar muette


def test_proxy_one_side_avg_zero_partial_estimation():
    """Si avg_ask=0 mais avg_bid>0 : n_buy=0, n_sell estime, ratio negatif."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    val = compute_aggressor_imbalance_proxy(100.0, 100.0, 0.0, 2.0)
    # n_buy=0, n_sell=50, total=50, ratio=(0-50)/50=-1.0
    assert val == -1.0


def test_proxy_clamp_to_minus_one_plus_one():
    """Verifier clamp [-1, +1] meme dans cas extremes."""
    from CORE.aggressor_imbalance_proxy import compute_aggressor_imbalance_proxy
    val = compute_aggressor_imbalance_proxy(1e9, 0.0, 1.0, 1.0)
    assert val == 1.0  # tout ask, sell=0 -> clamp +1.0
    val = compute_aggressor_imbalance_proxy(0.0, 1e9, 1.0, 1.0)
    assert val == -1.0


def test_inject_payload_without_existing():
    """Injection si aggressor_imbalance absent."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    payload = {
        "buy_vol": 100.0, "sell_vol": 100.0,
        "avg_ask_size": 2.0, "avg_bid_size": 2.0,
    }
    result = inject_aggressor_imbalance_proxy(payload)
    assert result["aggressor_imbalance"] == 0.0
    assert result["_aggressor_source"] == "sierra_proxy_count"


def test_inject_payload_with_existing_preserves():
    """Si aggressor_imbalance deja present non-None : NE PAS overwrite."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    payload = {
        "aggressor_imbalance": 0.42,  # source Databento Phase B+
        "buy_vol": 100.0, "sell_vol": 200.0,
        "avg_ask_size": 2.0, "avg_bid_size": 2.0,
    }
    result = inject_aggressor_imbalance_proxy(payload)
    assert result["aggressor_imbalance"] == 0.42  # source originale preservee
    assert "_aggressor_source" not in result


def test_inject_payload_with_none_existing_injects():
    """Si aggressor_imbalance = None : injection."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    payload = {
        "aggressor_imbalance": None,
        "buy_vol": 138.0, "sell_vol": 74.0,
        "avg_ask_size": 2.2258, "avg_bid_size": 1.8974,
    }
    result = inject_aggressor_imbalance_proxy(payload)
    assert result["aggressor_imbalance"] is not None
    assert 0.20 < result["aggressor_imbalance"] < 0.30


def test_inject_no_inputs_no_injection():
    """Si inputs manquants : pas d'injection (fail-closed downstream)."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    payload = {"close": 100.0}
    result = inject_aggressor_imbalance_proxy(payload)
    assert "aggressor_imbalance" not in result
    assert "_aggressor_source" not in result


def test_inject_logs_when_injected():
    """Verifier emit AGGRESSOR_PROXY_INJECTED."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    logs = []
    payload = {
        "buy_vol": 138.0, "sell_vol": 74.0,
        "avg_ask_size": 2.2258, "avg_bid_size": 1.8974,
    }
    inject_aggressor_imbalance_proxy(payload, log_fn=lambda c, **k: logs.append((c, k)), sym="NQ")
    assert len(logs) == 1
    assert logs[0][0] == "AGGRESSOR_PROXY_INJECTED"
    assert logs[0][1]["sym"] == "NQ"


def test_inject_logs_when_skipped():
    """Verifier emit AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    logs = []
    payload = {"close": 100.0}
    inject_aggressor_imbalance_proxy(payload, log_fn=lambda c, **k: logs.append((c, k)), sym="ES")
    assert len(logs) == 1
    assert logs[0][0] == "AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS"


def test_inject_logs_when_preserved():
    """Verifier emit AGGRESSOR_PROXY_PRESERVED_ORIGINAL."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    logs = []
    payload = {
        "aggressor_imbalance": 0.42,
        "buy_vol": 100.0, "sell_vol": 100.0,
        "avg_ask_size": 2.0, "avg_bid_size": 2.0,
    }
    inject_aggressor_imbalance_proxy(payload, log_fn=lambda c, **k: logs.append((c, k)), sym="MGC")
    assert len(logs) == 1
    assert logs[0][0] == "AGGRESSOR_PROXY_PRESERVED_ORIGINAL"


def test_inject_log_fn_exception_does_not_crash():
    """Si log_fn raise, l'injection reste fonctionnelle."""
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy

    def bad_log(code, **kwargs):
        raise RuntimeError("simulated log failure")

    payload = {
        "buy_vol": 100.0, "sell_vol": 100.0,
        "avg_ask_size": 2.0, "avg_bid_size": 2.0,
    }
    result = inject_aggressor_imbalance_proxy(payload, log_fn=bad_log, sym="NQ")
    assert result["aggressor_imbalance"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
