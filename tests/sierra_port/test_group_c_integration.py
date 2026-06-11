"""Tests Phase 1 Group C - rvol_engine (C1/C2/C3 SKIP footprint_cells)."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _sample_bar(ts_ns: int, close: float, total_vol: float = 100,
                 delta_pct: float = 0.0, finish: float = 50.0, **kw) -> dict:
    base = {
        "ts_event_ns": ts_ns, "close": close, "price": close,
        "open": close - 5, "bar_high": close + 5, "bar_low": close - 5,
        "high": close + 5, "low": close - 5,
        "total_vol": total_vol, "buy_vol": total_vol * 0.6, "sell_vol": total_vol * 0.4,
        "bool_gex_flip_zone": 1, "atr": 692,
        "delta_bar": delta_pct * total_vol, "delta_pct": delta_pct,
        "ask_pct": 0.6, "bid_pct": 0.4,
        "vwap_slope_10": 0.1, "vwap_d": close, "dist_vwap_d": 0.0,
        "cvd_day": 0, "diag_imbalance": 0, "finish_strength": finish,
        "va_position_pct": 0.5, "vwap_d_side": 1,
        "bar_edge_buy": 0, "bar_edge_sell": 0,
        "delta_divergence": 0,
        "large_trader_ratio": 0.3, "cvd_session": 0,
    }
    base.update(kw)
    return base


def test_rvol_warmup_produces_default():
    """C4 - 4 premieres bars : rvol=1.0 (min_periods=5)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    last = None
    for i in range(4):
        last = pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100))
    assert last["rvol"] == 1.0  # warmup default
    assert last["rvol_regime"] in (0, 1, 2, 3, 4)


def test_rvol_spike_triggers_regime_3():
    """C4 - spike volume (3x baseline) -> regime 3 + rvol_buy=1."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # 10 bars baseline volume 100
    for i in range(10):
        pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100, delta_pct=0.0))
    # Spike volume 500 + delta_pct > 0.05
    out = pipe.enrich_bar(_sample_bar(
        1781171160000000000, 28880, total_vol=500, delta_pct=0.15, finish=50))
    assert out["rvol"] > 2.0
    assert out["rvol_regime"] == 3  # spike (>2.5 threshold)
    assert out["rvol_buy"] == 1


def test_rvol_buy_strong_requires_delta_confirm():
    """C4 - rvol_buy_strong : spike + delta_pct > delta_confirm + finish > 0."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    for i in range(10):
        pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100))
    # Spike + delta_pct fort + finish positif
    out = pipe.enrich_bar(_sample_bar(
        1781171160000000000, 28880, total_vol=500, delta_pct=0.15, finish=50))
    assert out["rvol_buy_strong"] == 1


def test_rvol_absorb_buy_contradictory_delta_finish():
    """C4 - rvol_absorb_buy : spike + delta_pct < -0.05 + finish > 20 (acheteurs absorbes)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    for i in range(10):
        pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100))
    # Spike + delta_pct negatif (vendeurs aggressifs) MAIS finish positif (prix tient en haut)
    out = pipe.enrich_bar(_sample_bar(
        1781171160000000000, 28880, total_vol=500, delta_pct=-0.10, finish=30))
    assert out["rvol_absorb_buy"] == 1


def test_rvol_normal_regime_default():
    """C4 - volume normal -> regime 1 (normal)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    for i in range(10):
        pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100))
    out = pipe.enrich_bar(_sample_bar(1781171160000000000, 28880, total_vol=100))
    # rvol ~1.0 -> regime 1 (normal) ou 2 selon SMA
    assert out["rvol_regime"] in (0, 1, 2)


def test_group_c_does_not_break_group_a_b():
    """Regression : Group C n'affecte pas Group A+B features."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    out = pipe.enrich_bar(_sample_bar(1781170560000000000, 28870,
                                        total_vol=100, delta_pct=0.1,
                                        bn_color_up=1, bn_long_up=1))
    # Group A
    assert "cvd_session" in out
    assert "bn_score_raw" in out
    assert "long_up_bar" in out
    # Group B
    assert "bar_edge_buy_fire" in out
    assert "n_edge_buy_active" in out
    # Group C
    assert "rvol" in out
    assert "rvol_regime" in out


def test_big_v2_aliases_setup_engine_compat():
    """C1 partial port via aliases (review MUST #2) : Sierra `n_big_ask_t*` ->
    `n_big_ask_v2_t*` pour compat setup_engine.py:490-491 (PROD consumer)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Sierra natif emet n_big_ask_t1..t4 + max_ask_vol_in_bar
    bar = _sample_bar(1781170560000000000, 28870,
                       **{"n_big_ask_t1": 20, "n_big_ask_t2": 15,
                          "n_big_ask_t3": 5, "n_big_ask_t4": 1,
                          "n_big_bid_t1": 10, "n_big_bid_t2": 8,
                          "n_big_bid_t3": 2, "n_big_bid_t4": 0,
                          "max_ask_vol_in_bar": 26.0,
                          "max_bid_vol_in_bar": 13.0})
    out = pipe.enrich_bar(bar)
    # Aliases _v2 doivent etre presents avec memes valeurs
    assert out["n_big_ask_v2_t1"] == 20
    assert out["n_big_ask_v2_t2"] == 15
    assert out["n_big_ask_v2_t3"] == 5
    assert out["n_big_ask_v2_t4"] == 1
    assert out["n_big_bid_v2_t1"] == 10
    assert out["n_big_bid_v2_t4"] == 0
    assert out["max_big_ask_vol_in_bar"] == 26.0
    assert out["max_big_bid_vol_in_bar"] == 13.0


def test_big_v2_alias_no_override_if_v2_present():
    """Si Sierra emet deja n_big_ask_v2_t1 (cas improbable), alias ne l'ecrase pas."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    bar = _sample_bar(1781170560000000000, 28870,
                       **{"n_big_ask_t1": 20, "n_big_ask_v2_t1": 999})
    out = pipe.enrich_bar(bar)
    assert out["n_big_ask_v2_t1"] == 999  # valeur existante preservee


def test_rvol_preservation_sierra_via_set_diff():
    """Review MUST #1 : Sierra rvol/rvol_zscore preservation via set DIFF."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Sierra natif emet rvol=0.83 (median observed)
    bar = _sample_bar(1781170560000000000, 28870,
                       **{"rvol": 0.83, "rvol_zscore": -0.5,
                          "rvol_buy": 0, "rvol_sell": 0})
    out = pipe.enrich_bar(bar)
    # Sierra natif preserve (PAS ecrase par Python rvol=1.0 warmup default)
    assert out["rvol"] == 0.83
    assert out["rvol_zscore"] == -0.5
    # Python UNIQUES presents (regime, buy_strong, sell_strong, extreme)
    assert "rvol_regime" in out
    assert "rvol_buy_strong" in out
    assert "rvol_sell_strong" in out
    assert "rvol_extreme" in out


def test_cross_day_resets_rvol_state():
    """Cross-day reset doit re-init rvol_state (deque vide)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # J : 10 bars warmup
    for i in range(10):
        pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            total_vol=100))
    rvol_state_id_before = id(pipe._rvol_state)
    # J+1 : timestamp +24h
    pipe.enrich_bar(_sample_bar(
        1781170560000000000 + 86400_000_000_000, 28870, total_vol=100))
    assert id(pipe._rvol_state) != rvol_state_id_before
    # 1 bar dans nouveau state -> deque len = 1
    assert len(pipe._rvol_state.vol_window) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
