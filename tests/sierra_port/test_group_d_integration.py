"""Tests Phase 1 Group D - intermarket + D2/D3 SKIP."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _sample_bar(ts_ns: int, close: float, delta: float = 10.0, **kw) -> dict:
    base = {
        "ts_event_ns": ts_ns, "close": close, "price": close,
        "open": close - 5, "bar_high": close + 5, "bar_low": close - 5,
        "high": close + 5, "low": close - 5,
        "total_vol": 100, "buy_vol": 60, "sell_vol": 40,
        "bool_gex_flip_zone": 1, "atr": 692, "delta_bar": delta,
        "ask_pct": 0.6, "bid_pct": 0.4,
        "vwap_slope_10": 0.1, "vwap_d": close, "dist_vwap_d": 0.0,
        "cvd_day": 0, "diag_imbalance": 0, "finish_strength": 0.5,
        "va_position_pct": 0.5, "vwap_d_side": 1,
        "bar_edge_buy": 0, "bar_edge_sell": 0,
        "delta_divergence": 0,
        "bn_color_up": 0, "bn_color_dn": 0,
        "bn_long_up": 0, "bn_long_dn": 0,
        "bn_absorb_ask": 0, "bn_absorb_bid": 0,
        "large_trader_ratio": 0.3, "cvd_session": 0,
        "delta_pct": 0.1, "delta_day": 100,
        "dist_sess_high": 5, "dist_sess_low": 5,
        "open_bias_conf": 0.5, "open_direction": 1, "open_type": 2,
    }
    base.update(kw)
    return base


def test_intermarket_no_partner_returns_nan():
    """D1 - sans set_partner_bar : 10 features im_* = NaN."""
    import math
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    out = pipe.enrich_bar(_sample_bar(1781170560000000000, 6700))
    assert math.isnan(out.get("im_smt_divergence"))
    assert math.isnan(out.get("im_cross_delta_agreement_5"))
    assert math.isnan(out.get("im_rolling_correlation_10"))


def test_intermarket_with_partner_computes_features():
    """D1 - avec partner correle (delta meme signe) : agreement_5=1.0."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    pipe_nq = SierraPipelineOrchestrator(symbol="NQ")

    # 12 bars correles (delta meme signe)
    last_es = None
    for i in range(12):
        ts = 1781170560000000000 + i * 60_000_000_000
        out_nq = pipe_nq.enrich_bar(_sample_bar(ts, 28870 + i, delta=10.0))
        pipe_es.set_partner_bar(out_nq)
        last_es = pipe_es.enrich_bar(_sample_bar(ts, 6700 + i * 0.5, delta=10.0))

    assert last_es["im_cross_delta_agreement_5"] == 1.0
    assert last_es["im_open_type_agreement"] == 1.0


def test_intermarket_partner_stale_rejected():
    """D1 - partner bar > 120s old : rejected -> features NaN."""
    import math
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    # Partner bar t=0
    pipe_es.set_partner_bar(_sample_bar(1781170560000000000, 28870))
    # Target bar t = partner + 121s (au-dela 120s threshold)
    out = pipe_es.enrich_bar(_sample_bar(
        1781170560000000000 + 121 * 1_000_000_000, 6700))
    # Partner rejected -> features NaN
    assert math.isnan(out.get("im_smt_divergence"))


def test_intermarket_partner_future_rejected():
    """D1 - partner bar future : rejected -> features NaN."""
    import math
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    # Partner bar t+60s (future vs target t=0)
    pipe_es.set_partner_bar(_sample_bar(
        1781170560000000000 + 60 * 1_000_000_000, 28870))
    out = pipe_es.enrich_bar(_sample_bar(1781170560000000000, 6700))
    assert math.isnan(out.get("im_smt_divergence"))


def test_intermarket_set_partner_bar_none():
    """D1 - set_partner_bar(None) : reset -> features NaN cycle suivant."""
    import math
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    pipe_es.set_partner_bar(_sample_bar(1781170560000000000, 28870))
    pipe_es.set_partner_bar(None)
    out = pipe_es.enrich_bar(_sample_bar(1781170620000000000, 6700))
    assert math.isnan(out.get("im_smt_divergence"))


def test_intermarket_only_es_nq_supported():
    """D1 - MGC pipeline ignore intermarket (sym hors {ES, NQ})."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_mgc = SierraPipelineOrchestrator(symbol="MGC")
    pipe_mgc.set_partner_bar(_sample_bar(1781170560000000000, 28870))
    out = pipe_mgc.enrich_bar(_sample_bar(1781170560000000000, 3500))
    # Pas de features im_* (skip car symbole != ES/NQ)
    assert "im_smt_divergence" not in out


def test_group_d_does_not_break_a_b_c():
    """Regression : Group D n'affecte pas Group A+B+C."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    out = pipe.enrich_bar(_sample_bar(1781170560000000000, 28870,
                                        bn_color_up=1, bn_long_up=1))
    # Group A
    assert "cvd_session" in out
    assert "bn_score_raw" in out
    # Group B
    assert "n_edge_buy_active" in out
    # Group C
    assert "rvol" in out


def test_cross_day_resets_intermarket_state():
    """Cross-day reset doit re-init intermarket_state (deques vide)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    pipe_nq = SierraPipelineOrchestrator(symbol="NQ")
    for i in range(5):
        ts = 1781170560000000000 + i * 60_000_000_000
        out_nq = pipe_nq.enrich_bar(_sample_bar(ts, 28870 + i))
        pipe_es.set_partner_bar(out_nq)
        pipe_es.enrich_bar(_sample_bar(ts, 6700 + i))
    state_id_before = id(pipe_es._intermarket_state)
    # J+1
    out_nq = pipe_nq.enrich_bar(_sample_bar(
        1781170560000000000 + 86400_000_000_000, 28870))
    pipe_es.set_partner_bar(out_nq)
    pipe_es.enrich_bar(_sample_bar(
        1781170560000000000 + 86400_000_000_000, 6700))
    assert id(pipe_es._intermarket_state) != state_id_before


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
