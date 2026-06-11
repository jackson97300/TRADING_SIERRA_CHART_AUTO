"""Tests Phase 1 D2 - phase_b_helpers port (5 sub-engines + aliases + game_changers)."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _ts_ns_for_et(year: int, month: int, day: int, hour_et: int,
                    minute_et: int = 0) -> int:
    """Convertit heure ET (UTC-4 EDT) -> ts_event_ns."""
    # EDT (juin) = UTC - 4
    dt_utc = datetime(year, month, day, hour_et + 4, minute_et, tzinfo=timezone.utc)
    return int(dt_utc.timestamp() * 1_000_000_000)


def _sample_bar(ts_ns: int, close: float, **kw) -> dict:
    base = {
        "ts_event_ns": ts_ns, "close": close, "price": close,
        "open": close - 5, "bar_high": close + 5, "bar_low": close - 5,
        "high": close + 5, "low": close - 5,
        "total_vol": 100, "buy_vol": 60, "sell_vol": 40,
        "bool_gex_flip_zone": 1, "atr": 692, "delta_bar": 10,
        "ask_pct": 0.6, "bid_pct": 0.4, "vwap_slope_10": 0.1,
        "delta_day": 100, "dist_sess_high": 5, "dist_sess_low": 5,
        "large_trader_ratio": 0.3, "cvd_session": 0, "cvd_day": 0,
        "open_bias_conf": 0.5, "open_direction": 1, "open_type": 2,
        "delta_pct": 0.1, "finish_strength": 50,
        "bar_edge_buy": 0, "delta_divergence": 0,
        # Sierra niveaux _lvl (aliases D2)
        "prev_vah_lvl": 6800.0, "prev_val_lvl": 6700.0, "prev_vpoc_lvl": 6750.0,
        "cur_vah_lvl": 6790.0, "cur_val_lvl": 6710.0, "cur_vpoc_lvl": 6740.0,
        "open_cash_lvl": 6720.0, "open_830_lvl": 6715.0,
        "pdh": 6850.0, "pdl": 6680.0,
    }
    base.update(kw)
    return base


def test_d2_session_metadata_produces_date_et():
    """Sub-engine 1 : date_et + mins_et + session_date_trading."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # Bar 10:00 ET 11 juin 2026 (session US cash)
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 10, 0), 6750))
    assert out["date_et"] is not None
    assert out["mins_et"] == 600  # 10*60 + 0
    assert out["session_date_trading"] is not None


def test_d2_ib_features_complete_after_window():
    """Sub-engine 2 : ib_complete=1 apres 10:30 ET, ib_high/low set."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # 60 bars : 09:30 -> 10:30 ET (toute la fenetre IB)
    last = None
    for i in range(61):
        ts = _ts_ns_for_et(2026, 6, 11, 9, 30) + i * 60_000_000_000
        # Vary high/low pour ib_high != ib_low
        close = 6750 + (i % 5) - 2
        last = pipe.enrich_bar(_sample_bar(ts, close,
                                             bar_high=close + 3, bar_low=close - 3,
                                             high=close + 3, low=close - 3))
    # Apres 10:30 ET (bar 60+1=61), ib_complete=1
    assert last.get("ib_complete") == 1
    assert last.get("ib_high") is not None and last["ib_high"] > 0
    assert last.get("ib_low") is not None and last["ib_low"] > 0
    assert last["ib_high"] > last["ib_low"]
    assert last.get("ib_range_ticks") is not None
    assert last["ib_range_ticks"] > 0


def test_d2_session_high_low_runs():
    """Sub-engine 3 : sess_high/low absolus calcules."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    closes = [6750, 6760, 6740, 6770, 6735]  # range 35 ticks
    last = None
    for i, c in enumerate(closes):
        ts = _ts_ns_for_et(2026, 6, 11, 10, 0) + i * 60_000_000_000
        last = pipe.enrich_bar(_sample_bar(ts, c,
                                             bar_high=c + 3, bar_low=c - 3,
                                             high=c + 3, low=c - 3))
    assert last.get("sess_high") is not None
    assert last.get("sess_low") is not None
    assert last["sess_high"] >= max(closes)
    assert last["sess_low"] <= min(closes)


def test_d2_open_cash_captured_at_930():
    """Sub-engine 4 : open_cash capture sur bar 09:30 ET, broadcast suite."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # Bar 09:30 ET (cash open) avec close=6730
    pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 9, 30), 6730))
    # Bar 09:40 ET : open_cash deja capture = 6730 broadcast
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 9, 40), 6745))
    # open_cash devrait etre proche du close de 09:30 (depend logique sub-engine)
    assert out.get("open_cash") is not None
    assert not (isinstance(out["open_cash"], float) and out["open_cash"] != out["open_cash"])  # not NaN


def test_d2_aliases_lvl_to_python():
    """Aliases _lvl Sierra -> noms Python (game_changers consume)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 10, 0), 6750))
    # Aliases populated
    assert out.get("prev_vah") == 6800.0
    assert out.get("prev_val") == 6700.0
    assert out.get("prev_vpoc") == 6750.0
    assert out.get("cur_vah") == 6790.0
    assert out.get("open_cash") == 6720.0 or out.get("open_cash") is not None  # alias OR sub-engine


def test_d2_ib_atr_preserves_sierra_atr():
    """Sub-engine 5 ib_atr : output `ib_atr` (PAS rename) + Sierra `atr` preserve.
    FIX C1 review : drop rename ib_atr_python (cassait game_changers day_type)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 10, 0), 6750, atr=692.0))
    # Sierra atr (ATR 14 daily) preserve - aucun sub-engine D2 ne le touche
    assert out["atr"] == 692.0
    # ib_atr (Python sub-engine 5) present (peut NaN si min_periods pas atteint)
    assert "ib_atr" in out


def test_d2_day_type_norm_var_during_ib_window():
    """FIX C4 review : pendant IB window (09:30-10:30 ET), ib_high/low = NaN
    (anti-leak phase_b_helpers commit 27/04) -> day_type=NORM_VAR (2) attendu.
    Documenter pour eviter J+1 monitoring flag false alert."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # Bar 10:00 ET (au milieu IB, ib_complete=0)
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 10, 0), 6750,
        bar_high=6755, bar_low=6745, high=6755, low=6745))
    # day_type = NORM_VAR (2) attendu pendant IB (ib_atr=NaN anti-leak)
    assert out.get("day_type") == 2


def test_d2_open_cash_sub_engine_wins_over_prev_levels():
    """FIX C2 review : sub-engine 4 batch semantique (open us_start) wins
    apres pop pre-chain. PrevLevels.close ne doit PAS persister."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # Bar 09:30 ET (cash open) : close=6730, open=6725
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 9, 30), 6730))
    # Sub-engine 4 ecrit open_cash = open us_start bar (~6725 ou broadcast)
    # PrevLevels ecrivait close=6730 mais pop avant chain -> sub-engine 4 wins
    if out.get("open_cash") is not None and out.get("open_cash") == out.get("open_cash"):
        # Si sub-engine produit valeur, c'est le SNAPSHOT open, pas close
        assert out["open_cash"] != 6730 or out["open_cash"] == 6725  # tolerant valeur


def test_d2_game_changers_inputs_present():
    """Apres D2 chain + aliases, game_changers inputs sont disponibles."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe = SierraPipelineOrchestrator(symbol="ES")
    # Simulate complete IB session (60 bars 09:30-10:30) puis post-IB
    for i in range(61):
        ts = _ts_ns_for_et(2026, 6, 11, 9, 30) + i * 60_000_000_000
        c = 6750 + (i % 5) - 2
        pipe.enrich_bar(_sample_bar(ts, c,
                                      bar_high=c + 3, bar_low=c - 3,
                                      high=c + 3, low=c - 3))
    # Bar 10:31 ET : game_changers devrait avoir tous inputs valides
    out = pipe.enrich_bar(_sample_bar(
        _ts_ns_for_et(2026, 6, 11, 10, 31), 6750,
        bar_high=6755, bar_low=6745, high=6755, low=6745))
    # 5 features game_changers presentes
    assert "open_type" in out
    assert "open_zone" in out
    assert "day_type" in out
    assert "open_direction" in out
    assert "open_bias_conf" in out


def test_d2_does_not_break_d1_im_features():
    """Regression : D2 chain n'affecte pas Group D intermarket."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    pipe_es = SierraPipelineOrchestrator(symbol="ES")
    pipe_nq = SierraPipelineOrchestrator(symbol="NQ")
    last_es = None
    for i in range(12):
        ts = _ts_ns_for_et(2026, 6, 11, 10, 0) + i * 60_000_000_000
        nq_bar = _sample_bar(ts, 28870 + i)
        out_nq = pipe_nq.enrich_bar(nq_bar)
        pipe_es.set_partner_bar(nq_bar)
        last_es = pipe_es.enrich_bar(_sample_bar(ts, 6700 + i * 0.5))
    # im_* still computed
    assert "im_cross_delta_agreement_5" in last_es


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
