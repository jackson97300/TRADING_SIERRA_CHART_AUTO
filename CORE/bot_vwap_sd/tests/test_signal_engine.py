"""Tests signal_engine Bot 5 VWAP-SD : 4 setups (A/B/C/D).

Validation comportementale :
- Setup A NQ SHORT fire SSI close ENTRE SD2u et SD3u
- Setup B NQ LONG fire SSI close ENTRE SD2d et SD3d
- Setup C ES LONG fire SSI SD2d/SD3d zone ET vwap_slope_30 >= 0
- Setup D ES SHORT MODE SHADOW (n=13)
- NOT_RTH skip
- MISSING_FEATURES skip (fail-loud)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _make_bar(**overrides) -> dict:
    """Bar template valide (in_us_cash + features present)."""
    bar = {
        "ts_event": "2026-06-19T14:30:00+00:00",
        "close": 30000.0,
        "high": 30005.0,
        "low": 29995.0,
        "is_in_us_cash": True,
        "session_segment": "us_cash",
        "dist_vwap_d_sd2u": 100.0,   # SD2u au-dessus (close en-dessous SD2u)
        "dist_vwap_d_sd3u": 200.0,   # SD3u au-dessus aussi
        "dist_vwap_d_sd2d": -100.0,  # SD2d en-dessous (close au-dessus SD2d)
        "dist_vwap_d_sd3d": -200.0,  # SD3d en-dessous aussi
        "vwap_slope_30": 0.05,
        # Niveau confluence Setup A : par defaut prev_vah au-dessus proche (50 pts)
        "dist_mq_call": 1000.0,    # call resistance loin
        "dist_prev_vah": 50.0,     # VAH au-dessus PROCHE (confluence OK)
        "dist_vwap_w_sd2u": 800.0, # vwap_w_sd2u loin
        "dist_swing_high": -200.0, # swing_high en-dessous
    }
    bar.update(overrides)
    return bar


# ============================================================
# SETUP A : NQ SHORT entre SD2u et SD3u
# ============================================================

def test_setup_a_nq_short_fires_when_in_zone():
    """NQ + close ENTRE SD2u et SD3u -> Setup A SHORT."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    # close ENTRE SD2u et SD3u : dist_sd2u < 0 (au-dessus) ET dist_sd3u > 0 (en-dessous)
    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,  # close > SD2u
        dist_vwap_d_sd3u=100.0,  # close < SD3u
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.direction == "short"
    assert d.setup_id == "A"
    assert d.tp_ticks == 80
    assert d.sl_ticks == 40


def test_setup_a_does_not_fire_below_sd2u():
    """NQ + close en-dessous SD2u -> Setup A ne fire pas."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    # close EN-DESSOUS SD2u : dist_sd2u > 0
    bar = _make_bar(dist_vwap_d_sd2u=50.0)
    d = eng.on_bar(bar)
    # FIX MINEUR #10 : assertion strict (Setup A ne doit jamais fire hors zone)
    assert d.setup_id != "A"


def test_setup_a_does_not_fire_above_sd3u():
    """NQ + close au-dessus SD3u (extreme) -> Setup A ne fire pas."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    # close AU-DESSUS SD3u : dist_sd3u < 0
    bar = _make_bar(
        dist_vwap_d_sd2u=-150.0,
        dist_vwap_d_sd3u=-50.0,  # close > SD3u
    )
    d = eng.on_bar(bar)
    # FIX MINEUR #10 : assertion strict
    assert d.setup_id != "A"


# ============================================================
# SETUP B : NQ LONG entre SD2d et SD3d
# ============================================================

def test_setup_b_nq_long_is_shadow_by_default():
    """Setup B detect zone MAIS shadow par defaut (verdict empirique PF 0.52)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=200.0,
        dist_vwap_d_sd3u=300.0,
        dist_vwap_d_sd2d=50.0,
        dist_vwap_d_sd3d=-100.0,
    )
    d = eng.on_bar(bar)
    assert d.setup_id == "B"
    assert d.direction == "long"
    assert d.shadow is True
    assert d.tradable is False, "Setup B desactive par defaut (edge inverse live)"


def test_setup_b_can_be_enabled_explicitly(monkeypatch):
    """Setup B peut etre force via env si Jackson veut tester."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    monkeypatch.setenv("BOTVWAPSD_SETUP_B_ENABLED", "true")
    monkeypatch.setenv("BOTVWAPSD_SETUP_B_SHADOW", "false")
    cfg = VwapSdConfig.from_env()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=200.0,
        dist_vwap_d_sd3u=300.0,
        dist_vwap_d_sd2d=50.0,
        dist_vwap_d_sd3d=-100.0,
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.setup_id == "B"
    assert d.direction == "long"


# ============================================================
# SETUP C : ES LONG slope >= 0
# ============================================================

def test_setup_c_es_long_is_shadow_by_default():
    """Setup C detect zone+slope MAIS shadow par defaut (verdict empirique PF 1.18)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="ES", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=200.0,
        dist_vwap_d_sd3u=300.0,
        dist_vwap_d_sd2d=50.0,
        dist_vwap_d_sd3d=-100.0,
        vwap_slope_30=0.02,  # positif
    )
    d = eng.on_bar(bar)
    assert d.setup_id == "C"
    assert d.direction == "long"
    assert d.shadow is True
    assert d.tradable is False, "Setup C desactive par defaut (edge marginal)"


def test_setup_c_blocked_by_negative_slope():
    """Setup C : filtre slope >= 0 enforce meme en SHADOW."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="ES", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=200.0,
        dist_vwap_d_sd3u=300.0,
        dist_vwap_d_sd2d=50.0,
        dist_vwap_d_sd3d=-100.0,
        vwap_slope_30=-0.02,  # negatif = downtrend
    )
    d = eng.on_bar(bar)
    assert d.setup_id != "C", "Slope negatif doit bloquer Setup C meme en SHADOW"


# ============================================================
# SETUP D : ES SHORT - MODE SHADOW (n=13 insuffisant)
# ============================================================

def test_setup_d_es_short_is_shadow_by_default():
    """ES + zone SD2u/SD3u -> Setup D mais SHADOW (pas trade)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="ES", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
    )
    d = eng.on_bar(bar)
    assert d.setup_id == "D"
    assert d.shadow is True
    assert d.tradable is False, "Setup D ne doit PAS trade par defaut (n=13 insuffisant)"


def test_setup_d_can_be_enabled_explicitly(monkeypatch):
    """Setup D peut etre force via env BOTVWAPSD_SETUP_D_ENABLED=true."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    monkeypatch.setenv("BOTVWAPSD_SETUP_D_ENABLED", "true")
    monkeypatch.setenv("BOTVWAPSD_SETUP_D_SHADOW", "false")
    cfg = VwapSdConfig.from_env()
    eng = VwapSdSignalEngine(symbol="ES", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.setup_id == "D"


# ============================================================
# GARDE-FOUS
# ============================================================

def test_not_rth_skipped():
    """Bar hors RTH US (Asia, London) -> skip immediat."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        is_in_us_cash=False,
        session_segment="asia",
        dist_vwap_d_sd2u=-50.0,  # condition Setup A satisfaite
        dist_vwap_d_sd3u=100.0,
    )
    d = eng.on_bar(bar)
    assert d.tradable is False
    assert d.skip_reason == "NOT_RTH"


def test_missing_features_fail_loud():
    """Features VWAP-SD manquantes -> skip explicite (PAS fallback silencieux)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar()
    del bar["dist_vwap_d_sd2u"]  # feature manquante
    d = eng.on_bar(bar)
    assert d.tradable is False
    assert d.skip_reason == "MISSING_VWAP_SD_FEATURES"


def test_empty_bar_skipped():
    """Bar vide -> skip immediat."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    d = eng.on_bar({})
    assert d.tradable is False
    assert d.skip_reason == "EMPTY_BAR"


def test_setup_a_skipped_on_trend_day_ib_expansion():
    """Anti-trend-day : si ib_range_atr >= 2.0 -> skip Setup A (volatility expansion)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        ib_range_atr=2.5,  # trend day signal
    )
    d = eng.on_bar(bar)
    assert d.tradable is False
    assert d.setup_id == "A"
    assert d.skip_reason.startswith("TREND_DAY_IB_EXPANSION")


def test_setup_a_passes_on_range_day():
    """Anti-trend-day : ib_range_atr < 2.0 -> Setup A fire (range day OK)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        ib_range_atr=1.0,  # range day OK
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.setup_id == "A"


def test_setup_a_antitrend_disabled_via_env(monkeypatch):
    """Anti-trend-day desactivable via env (test override)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    monkeypatch.setenv("BOTVWAPSD_SETUP_A_ANTITREND_ENABLED", "false")
    cfg = VwapSdConfig.from_env()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        ib_range_atr=3.0,  # trend day mais filtre off
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.setup_id == "A"


def test_setup_a_antitrend_handles_missing_ib():
    """Anti-trend-day : si ib_range_atr None -> ne bloque pas (fail-open)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
    )
    if "ib_range_atr" in bar:
        del bar["ib_range_atr"]
    d = eng.on_bar(bar)
    # Sans ib_range_atr : filtre fail-open (laisse passer, confluence prend le relais)
    assert d.setup_id == "A"
    # Tradable car confluence prev_vah=50pts par defaut dans _make_bar
    assert d.tradable is True


def test_setup_a_skipped_when_no_confluence():
    """Setup A : zone SD2u-SD3u MAIS aucun niveau resistance au-dessus -> skip."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    # close ENTRE SD2u et SD3u MAIS tous niveaux institutionnels loin / au-dessous
    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        # Tous les niveaux LOIN au-dessus (> 500 ticks = 125 pts) ou EN-DESSOUS
        dist_mq_call=2000.0,       # call resistance tres loin
        dist_prev_vah=-300.0,      # VAH en-dessous (close above VAH = breakout au-dessus)
        dist_vwap_w_sd2u=1500.0,   # vwap_w_sd2u loin
        dist_swing_high=-500.0,    # swing_high tres en-dessous
    )
    d = eng.on_bar(bar)
    assert d.tradable is False
    assert d.setup_id == "A"
    assert d.skip_reason == "NO_RESISTANCE_CONFLUENCE"


def test_setup_a_confluence_can_be_disabled(monkeypatch):
    """Setup A : filtre confluence desactivable via env."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    monkeypatch.setenv("BOTVWAPSD_SETUP_A_CONFLUENCE_ENABLED", "false")
    cfg = VwapSdConfig.from_env()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        # Pas de confluence mais filtre desactive
        dist_mq_call=2000.0,
        dist_prev_vah=-300.0,
        dist_vwap_w_sd2u=1500.0,
        dist_swing_high=-500.0,
    )
    d = eng.on_bar(bar)
    assert d.tradable is True
    assert d.setup_id == "A"


def test_setup_a_confluence_all_features_none_emits_majeur():
    """FIX #3 : si TOUTES candidates confluence sont None -> emit CONFLUENCE_FEATURES_ALL_NONE."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    emits = []
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg, log_fn=lambda code, **ctx: emits.append((code, ctx)))

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        dist_mq_call=None,
        dist_prev_vah=None,
        dist_vwap_w_sd2u=None,
        dist_swing_high=None,
    )
    # Remove keys completely
    for k in list(bar.keys()):
        if bar[k] is None:
            del bar[k]
    d = eng.on_bar(bar)
    assert d.tradable is False
    assert d.skip_reason == "CONFLUENCE_FEATURES_ALL_NONE"
    # Verify emit MAJEUR
    confluence_emits = [e for e in emits if e[0] == "BOTVWAPSD_CONFLUENCE_FEATURES_ALL_NONE"]
    assert len(confluence_emits) == 1
    assert confluence_emits[0][1]["sym"] == "NQ"


def test_setup_a_boundary_sd2u_exact():
    """FIX #7 : close exactement = SD2u (dist=0) -> Setup A ne fire pas (strict <)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=0.0,  # boundary exact
        dist_vwap_d_sd3u=100.0,
    )
    d = eng.on_bar(bar)
    assert d.setup_id != "A", "Boundary exact SD2u doit etre exclu (strict <)"


def test_setup_a_boundary_sd3u_exact():
    """FIX #7 : close exactement = SD3u (dist=0) -> Setup A ne fire pas (strict >)."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=0.0,  # boundary exact
    )
    d = eng.on_bar(bar)
    assert d.setup_id != "A", "Boundary exact SD3u doit etre exclu (strict >)"


def test_signal_decision_is_frozen():
    """FIX #6 : SignalDecision doit etre frozen (immutable)."""
    from dataclasses import FrozenInstanceError
    from CORE.bot_vwap_sd.signal_engine import SignalDecision

    d = SignalDecision(tradable=True, setup_id="A")
    with pytest.raises(FrozenInstanceError):
        d.tradable = False  # type: ignore


def test_setup_b_disabled_emits_distinct_skip_reason(monkeypatch):
    """FIX #2 : log distinct SETUP_B_DISABLED vs SHADOW_EDGE_INVERSE_LIVE."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    # Default : SETUP_B_ENABLED=False -> skip_reason="SETUP_B_DISABLED"
    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)
    bar = _make_bar(
        dist_vwap_d_sd2u=200.0,
        dist_vwap_d_sd3u=300.0,
        dist_vwap_d_sd2d=50.0,
        dist_vwap_d_sd3d=-100.0,
    )
    d = eng.on_bar(bar)
    assert d.setup_id == "B"
    assert d.skip_reason == "SETUP_B_DISABLED"

    # Enabled mais shadow=true -> "SHADOW_EDGE_INVERSE_LIVE"
    monkeypatch.setenv("BOTVWAPSD_SETUP_B_ENABLED", "true")
    monkeypatch.setenv("BOTVWAPSD_SETUP_B_SHADOW", "true")
    cfg2 = VwapSdConfig.from_env()
    eng2 = VwapSdSignalEngine(symbol="NQ", cfg=cfg2)
    d2 = eng2.on_bar(bar)
    assert d2.skip_reason == "SHADOW_EDGE_INVERSE_LIVE"


def test_emit_decision_log_calls_log_decision_jsonl(tmp_path, monkeypatch):
    """FIX #5 : emit_decision_log doit appeler log_decision_jsonl quand setup detecte."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine
    import CORE.bot_vwap_sd.logger as logger_module

    calls = []
    def mock_log(**kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(logger_module, "log_decision_jsonl", mock_log)

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)
    bar = _make_bar(dist_vwap_d_sd2u=-50.0, dist_vwap_d_sd3u=100.0)
    d = eng.on_bar(bar)
    eng.emit_decision_log(d, bar)
    assert len(calls) == 1
    assert calls[0]["symbol"] == "NQ"
    assert calls[0]["setup_id"] == "A"
    assert calls[0]["tradable"] is True


def test_setup_a_confluence_threshold_adjustable(monkeypatch):
    """Threshold confluence ajustable. Avec 100 ticks (25 pts), VAH a 50pts passe pas."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    monkeypatch.setenv("BOTVWAPSD_SETUP_A_CONFLUENCE_THRESHOLD_TICKS", "100")
    cfg = VwapSdConfig.from_env()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    # VAH au-dessus a 50 points = 200 ticks > 100 ticks (rejected)
    # Mais swing_high si on le mettait a 10 pts = 40 ticks < 100 -> OK
    bar = _make_bar(
        dist_vwap_d_sd2u=-50.0,
        dist_vwap_d_sd3u=100.0,
        dist_mq_call=2000.0,
        dist_prev_vah=50.0,       # 50 pts = 200 ticks > 100 ticks threshold
        dist_vwap_w_sd2u=1500.0,
        dist_swing_high=-500.0,
    )
    d = eng.on_bar(bar)
    assert d.tradable is False, "VAH a 200 ticks doit etre rejected avec threshold 100"


def test_describe_setups():
    """describe_setups() retourne dict avec 4 setups."""
    from CORE.bot_vwap_sd.config import VwapSdConfig
    from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine

    cfg = VwapSdConfig()
    eng = VwapSdSignalEngine(symbol="NQ", cfg=cfg)

    desc = eng.describe_setups()
    assert set(desc.keys()) == {"A", "B", "C", "D"}
    assert desc["A"]["symbol"] == "NQ"
    assert desc["A"]["direction"] == "short"
    assert desc["D"]["shadow"] is True
