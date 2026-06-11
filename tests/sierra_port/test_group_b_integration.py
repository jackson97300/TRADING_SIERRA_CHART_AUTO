"""Tests Phase 1 Group B - rolling_features + edge_zones + delta_div_ext."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _sample_bar(ts_ns: int, close: float, delta: float = 0.0, **kw) -> dict:
    base = {
        "ts_event_ns": ts_ns, "close": close, "price": close,
        "open": close - 5, "bar_high": close + 5, "bar_low": close - 5,
        "high": close + 5, "low": close - 5,
        "total_vol": 100, "buy_vol": 60, "sell_vol": 40,
        "bool_gex_flip_zone": 1, "atr": 692, "delta_bar": delta,
        "dist_swing_high": 20, "dist_swing_low": 15, "dist_cur_vpoc": 10,
        "ask_pct": 0.6, "bid_pct": 0.4,
        "vwap_slope_10": 0.1, "vwap_d": close, "dist_vwap_d": 0.0,
        "cvd_day": delta, "diag_imbalance": 0, "finish_strength": 0.5,
        "va_position_pct": 0.5, "vwap_d_side": 1,
        "bar_edge_buy": 0, "bar_edge_sell": 0,
        "delta_divergence": 0,
        "bn_color_up": 0, "bn_color_dn": 0,
        "bn_long_up": 0, "bn_long_dn": 0,
        "bn_absorb_ask": 0, "bn_absorb_bid": 0,
        "large_trader_ratio": 0.3, "cvd_session": delta,
    }
    base.update(kw)
    return base


def test_rolling_features_ctx_present_after_warmup():
    """B1 - features ctx_* presentes apres warmup 12 bars."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    last = None
    for i in range(12):
        last = pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            delta=10.0 if i % 2 == 0 else -5.0))
    # Au moins ces 4 features doivent etre presentes (verifie par Bot 3)
    assert "ctx_poc_migration_10" in last
    assert "ctx_va_developing_10" in last
    assert "ctx_rotation_factor_20" in last
    assert "ctx_ib_extension_ratio" in last
    assert "ctx_rvol_session" in last
    assert "ctx_cvd_recovery_rate" in last


def test_edge_zones_n_active_after_fire():
    """B2 - n_edge_buy_active = 1 apres Sierra fire bar_edge_buy=1."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Bar 1 : pas de fire -> n_active = 0
    pipe.enrich_bar(_sample_bar(1781170560000000000, 28870))
    # Bar 2 : Sierra fire bar_edge_buy=1 -> n_active = 1
    out = pipe.enrich_bar(_sample_bar(1781170620000000000, 28880,
                                        bar_edge_buy=1))
    assert out["bar_edge_buy_fire"] == 1
    assert out["n_edge_buy_active"] == 1
    assert out["bar_edge_sell_fire"] == 0
    assert out["n_edge_sell_active"] == 0


def test_edge_zones_deactivated_by_bar_touch():
    """B2 - zone edge desactivee quand bar high/low traverse le prix."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # Bar 1 fire buy a close=28870
    pipe.enrich_bar(_sample_bar(1781170560000000000, 28870, bar_edge_buy=1))
    # Bar 2 sans fire mais bar high=28880 et bar low=28860 traverse 28870
    out = pipe.enrich_bar(_sample_bar(1781170620000000000, 28875,
                                        bar_high=28880, bar_low=28860,
                                        high=28880, low=28860))
    # Zone 28870 traversee -> deactivee
    assert out["n_edge_buy_active"] == 0


def test_divergences_v2_calculator_emits_delta_div():
    """B3 NOT-PORTED : divergences_v2 Calculator Phase 3 emet deja 14 features
    delta_div_*. Pas de portage add_delta_div_ext_streaming (doublon)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # 10 bars warmup (slope_window divergences_v2 default 5)
    out = None
    for i in range(10):
        out = pipe.enrich_bar(_sample_bar(
            1781170560000000000 + i * 60_000_000_000, 28870 + i,
            delta=10.0 if i % 2 == 0 else -5.0))
    # 14 features delta_div_* presentes via divergences_v2
    assert "delta_div_buy" in out
    assert "delta_div_sell" in out
    assert "delta_div_strength" in out
    assert "n_delta_div_buy_zones_active" in out
    assert "ctx_div_density_20" in out


def test_group_b_does_not_break_group_a():
    """Regression : Group B added doesn't break Group A features."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    out = pipe.enrich_bar(_sample_bar(1781170560000000000, 28870,
                                        delta=15.0, bn_color_up=1, bn_long_up=1))
    # Group A still works
    assert out["cvd_session"] == 15.0
    assert out["bn_score_raw"] > 0
    assert "long_up_bar" in out


def test_cross_day_resets_group_b_state():
    """Cross-day reset doit re-init rolling/edge states (fix N2 review).
    Test strict : verifie zones LIST reset (pas juste count_active=0 qui peut
    arriver naturellement par deactivation)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="NQ")
    # J : warmup + fire buy a t=2 (close=28872)
    # Bars 3,4 ont high=28877+i, donc 28872 dans range -> deactive
    # On utilise prix tres different pour eviter deactivation naturelle
    pipe.enrich_bar(_sample_bar(1781170560000000000, 100,
                                  bar_high=105, bar_low=95, high=105, low=95,
                                  bar_edge_buy=1))
    pipe.enrich_bar(_sample_bar(1781170620000000000, 200,
                                  bar_high=205, bar_low=195, high=205, low=195))
    pipe.enrich_bar(_sample_bar(1781170680000000000, 300,
                                  bar_high=305, bar_low=295, high=305, low=295))
    # Zone bar 0 a close=100 reste active (bar 1,2 sont a 200/300)
    buffer_before = pipe._edge_buy_buffer
    assert len(buffer_before.zones) > 0
    buffer_id_before = id(buffer_before)
    # J+1 : timestamp +24h
    pipe.enrich_bar(_sample_bar(
        1781170560000000000 + 86400_000_000_000, 28870))
    # Buffer recree (id different)
    assert id(pipe._edge_buy_buffer) != buffer_id_before
    assert len(pipe._edge_buy_buffer.zones) == 0
    # bar_idx reset
    assert pipe._edge_bar_idx <= 1  # incremented 1x apres le 1er bar J+1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
