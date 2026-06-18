"""Tests filtres Phase 4 18/06 : ORDERFLOW + ANTI-TOP + MOMENTUM CAP.

Calibration empirique 6 trades 18/06 :
  LOSS 3/3 : delta_bar negatif + slope_10>0.77 + bars_since_HH<=5 + pres HOD
  WIN 3/3 : delta_bar positif OU rvol_z>=2 (exhaustion vendeur claire)
Variable la + discriminante : delta_bar (ecart WIN-LOSS = +210)

Filtres en cascade DANS SignalEngine.evaluate() apres detection direction.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


# --------------------------------------------------------------------------
# Helpers (RTH US, evite pre-open)
# --------------------------------------------------------------------------


def _ts_now_us() -> int:
    """ts ms en plein milieu RTH US (15:00 UTC = 11:00 ET)."""
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es_long(**overrides) -> dict:
    """Bar ES setup LONG (SD3 down) avec defaults NEUTRES sur les 3 filtres.

    Defaults : delta_bar=50, bars_since_HH=30, slope_10=0.1, dist_1d_max=-100.
    Tous les filtres LAISSENT PASSER avec ces defaults.
    Override via kwargs pour stresser un filtre specifique.
    """
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0,
        "bar_low": 5799.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.10,
        "dist_vwap_d_sd3u_pct": -0.20,
        "vwap_slope_30": 0.05,  # trend_align_es LONG
        # Phase 4 defaults neutres
        "delta_bar": 50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    bar.update(overrides)
    return bar


def _make_bar_es_short(**overrides) -> dict:
    """Bar ES setup SHORT (SD3 up) avec defaults NEUTRES sur les 3 filtres."""
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0,
        "bar_low": 5799.0,
        "vix_level": 25.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3u_pct": 0.10,
        "dist_vwap_d_sd3d_pct": 0.20,
        "vwap_slope_30": -0.05,  # trend_align_es SHORT
        # Phase 4 defaults neutres
        "delta_bar": -50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": -0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    bar.update(overrides)
    return bar


# ==========================================================================
# 1. Config defaults
# ==========================================================================


def test_orderflow_filter_defaults_enabled():
    cfg = BotMRConfig()
    assert cfg.ORDERFLOW_CONFIRM_ENABLED is True
    assert cfg.ORDERFLOW_RVOL_EXHAUSTION_MIN == 2.0


def test_anti_top_defaults():
    cfg = BotMRConfig()
    assert cfg.ANTI_TOP_ENABLED is True
    assert cfg.ANTI_TOP_BARS_SINCE_HH_MAX == 5
    assert cfg.ANTI_TOP_DIST_HOD_MAX_TICKS == 25


def test_momentum_cap_defaults_1_1():
    cfg = BotMRConfig()
    assert cfg.MOMENTUM_CAP_ENABLED is True
    assert cfg.SLOPE_10_MAX_LONG == 1.1


def test_env_override_orderflow(monkeypatch):
    monkeypatch.setenv("BOTMR_ORDERFLOW_CONFIRM_ENABLED", "0")
    monkeypatch.setenv("BOTMR_ORDERFLOW_RVOL_EXHAUSTION_MIN", "3.0")
    monkeypatch.setenv("BOTMR_ANTI_TOP_BARS_SINCE_HH_MAX", "10")
    monkeypatch.setenv("BOTMR_ANTI_TOP_DIST_HOD_MAX_TICKS", "30")
    monkeypatch.setenv("BOTMR_MOMENTUM_CAP_ENABLED", "0")
    monkeypatch.setenv("BOTMR_SLOPE_10_MAX_LONG", "2.0")
    cfg = BotMRConfig.from_env()
    assert cfg.ORDERFLOW_CONFIRM_ENABLED is False
    assert cfg.ORDERFLOW_RVOL_EXHAUSTION_MIN == 3.0
    assert cfg.ANTI_TOP_BARS_SINCE_HH_MAX == 10
    assert cfg.ANTI_TOP_DIST_HOD_MAX_TICKS == 30
    assert cfg.MOMENTUM_CAP_ENABLED is False
    assert cfg.SLOPE_10_MAX_LONG == 2.0


# ==========================================================================
# 2. ORDERFLOW LONG
# ==========================================================================


def test_orderflow_long_delta_negative_blocks():
    """LONG avec delta_bar=-100, pas d'exhaustion, pas d'absorb -> BLOCK."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=-100.0, rvol_zscore=1.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ORDERFLOW_NO_BUYERS_LONG" in sig.skip_reason


def test_orderflow_long_delta_zero_passes():
    """LONG avec delta_bar=0 (>= 0) -> cond_buyers True -> passe orderflow."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=0.0)
    sig = eng.evaluate(bar)
    # Verifie que orderflow ne bloque pas (le signal peut etre tradable=True OU
    # bloque par un AUTRE filtre downstream, mais pas par orderflow).
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")


def test_orderflow_long_delta_positive_passes():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=100.0)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")


def test_orderflow_long_exhaustion_passes_via_rvol():
    """delta<0 mais rvol_z>=2 -> exhaustion vendeur -> passe."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=-100.0, rvol_zscore=2.5)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")


def test_orderflow_long_exhaustion_passes_via_ctx_flag():
    """delta<0, rvol<2 mais ctx_delta_exhaustion=True -> passe."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        delta_bar=-100.0, rvol_zscore=1.0, ctx_delta_exhaustion=True,
    )
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")


def test_orderflow_long_absorb_bid_passes():
    """delta<0 mais bn_absorb_bid=1 -> absorption bid -> passe."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=-100.0, rvol_zscore=1.0, bn_absorb_bid=1)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")


def test_orderflow_long_delta_none_blocks_fail_loud():
    """delta_bar=None -> ORDERFLOW_NO_DATA fail-loud."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long()
    bar["delta_bar"] = None  # force None
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ORDERFLOW_NO_DATA" in sig.skip_reason


# ==========================================================================
# 3. ORDERFLOW SHORT (mirror)
# ==========================================================================


def test_orderflow_short_delta_positive_blocks():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(delta_bar=100.0, rvol_zscore=1.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ORDERFLOW_NO_SELLERS_SHORT" in sig.skip_reason


def test_orderflow_short_delta_negative_passes():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(delta_bar=-100.0)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_SELLERS" not in (sig.skip_reason or "")


def test_orderflow_short_absorb_ask_passes():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(delta_bar=100.0, rvol_zscore=1.0, bn_absorb_ask=1)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_SELLERS" not in (sig.skip_reason or "")


# ==========================================================================
# 4. ANTI TOP / ANTI BOTTOM
# ==========================================================================


def test_anti_top_long_near_HH_and_near_HOD_blocks():
    """bs_high=2 (<=5) ET dist_1d_max=-10 (>=-25) -> BLOCK ANTI_TOP_LONG."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        bars_since_last_swing_high=2.0,
        dist_1d_max_ticks=-10.0,
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ANTI_TOP_LONG" in sig.skip_reason


def test_anti_top_long_far_from_HH_passes():
    """bs_high=30 (>5) -> anti-top bypass meme si pres HOD."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        bars_since_last_swing_high=30.0,
        dist_1d_max_ticks=-10.0,
    )
    sig = eng.evaluate(bar)
    assert "ANTI_TOP_LONG" not in (sig.skip_reason or "")


def test_anti_top_long_near_HH_far_HOD_passes():
    """bs_high=2 mais dist_1d_max=-50 (<-25) -> anti-top bypass (loin HOD)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        bars_since_last_swing_high=2.0,
        dist_1d_max_ticks=-50.0,
    )
    sig = eng.evaluate(bar)
    assert "ANTI_TOP_LONG" not in (sig.skip_reason or "")


def test_anti_bottom_short_mirror_blocks():
    """SHORT : bs_low=2 ET dist_1d_min=+10 (<=25) -> BLOCK ANTI_BOTTOM."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(
        bars_since_last_swing_low=2.0,
        dist_1d_min_ticks=10.0,
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ANTI_BOTTOM_SHORT" in sig.skip_reason


def test_anti_top_long_bs_none_bypass():
    """bs_high absent du bar -> bypass anti-top (fail-open soft)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long()
    bar["bars_since_last_swing_high"] = None
    bar["dist_1d_max_ticks"] = -10.0  # proche HOD mais bs_high None
    sig = eng.evaluate(bar)
    assert "ANTI_TOP_LONG" not in (sig.skip_reason or "")


# ==========================================================================
# 5. MOMENTUM CAP
# ==========================================================================


def test_momentum_cap_long_slope_excessive_blocks():
    """slope_10=1.5 > 1.1 -> BLOCK MOMENTUM_CAP_LONG."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_10=1.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "MOMENTUM_CAP_LONG" in sig.skip_reason


def test_momentum_cap_long_slope_at_threshold_passes():
    """slope_10=1.1 == seuil (strict >) -> passe."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_10=1.1)
    sig = eng.evaluate(bar)
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")


def test_momentum_cap_short_mirror_blocks():
    """slope_10=-1.5 < -1.1 -> BLOCK MOMENTUM_CAP_SHORT."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(vwap_slope_10=-1.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "MOMENTUM_CAP_SHORT" in sig.skip_reason


# ==========================================================================
# 6. Disable flags bypass
# ==========================================================================


def test_orderflow_disabled_bypass():
    """ORDERFLOW_CONFIRM_ENABLED=False -> delta_bar absent ne bloque PAS."""
    cfg = dataclasses.replace(BotMRConfig(), ORDERFLOW_CONFIRM_ENABLED=False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long()
    bar["delta_bar"] = None  # absent
    sig = eng.evaluate(bar)
    assert "ORDERFLOW" not in (sig.skip_reason or "")


def test_anti_top_disabled_bypass():
    cfg = dataclasses.replace(BotMRConfig(), ANTI_TOP_ENABLED=False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        bars_since_last_swing_high=2.0,
        dist_1d_max_ticks=-10.0,
    )
    sig = eng.evaluate(bar)
    assert "ANTI_TOP" not in (sig.skip_reason or "")


def test_momentum_cap_disabled_bypass():
    cfg = dataclasses.replace(BotMRConfig(), MOMENTUM_CAP_ENABLED=False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_10=5.0)
    sig = eng.evaluate(bar)
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")


def test_all_flags_disabled_bypass_all_filters():
    cfg = dataclasses.replace(
        BotMRConfig(),
        ORDERFLOW_CONFIRM_ENABLED=False,
        ANTI_TOP_ENABLED=False,
        MOMENTUM_CAP_ENABLED=False,
    )
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        delta_bar=-1000.0,
        bars_since_last_swing_high=1.0,
        dist_1d_max_ticks=-1.0,
        vwap_slope_10=10.0,
    )
    sig = eng.evaluate(bar)
    # Aucun des 3 filtres ne doit apparaitre dans skip_reason
    assert "ORDERFLOW" not in (sig.skip_reason or "")
    assert "ANTI_TOP" not in (sig.skip_reason or "")
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")


# ==========================================================================
# 7. Empirique : simulation des 6 trades 18/06
# ==========================================================================
#
# Les valeurs ci-dessous sont une reproduction synthetique des patterns
# observes empiriquement (les valeurs exactes sont reconstruites de memoire
# pour les tests, l'important est que les caracteristiques discriminantes
# soient preservees).


def test_loss_3_blocked_by_filters():
    """LOSS pattern : delta=-109 + slope_10=1.40 (momentum overheated)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        delta_bar=-109.0,
        rvol_zscore=1.0,
        vwap_slope_10=1.40,
        bars_since_last_swing_high=20.0,  # pas anti-top
        dist_1d_max_ticks=-60.0,
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    # 2 filtres peuvent bloquer : orderflow OU momentum cap
    assert (
        "ORDERFLOW_NO_BUYERS_LONG" in sig.skip_reason
        or "MOMENTUM_CAP_LONG" in sig.skip_reason
    )


def test_loss_6_blocked_by_anti_top():
    """LOSS pattern : bs_high=1 + dist_HOD=-10 (proche HOD frais)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(
        delta_bar=10.0,  # neutre (passe orderflow)
        bars_since_last_swing_high=1.0,
        dist_1d_max_ticks=-10.0,
        vwap_slope_10=0.5,  # passe momentum
    )
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ANTI_TOP_LONG" in sig.skip_reason


def test_loss_7_blocked_by_orderflow():
    """LOSS pattern : delta=+2 cote LONG OK mais... configure pour SHORT
    avec delta+2 = pas d'orderflow vendeur."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(delta_bar=2.0, rvol_zscore=1.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "ORDERFLOW_NO_SELLERS_SHORT" in sig.skip_reason


def test_win_1_passes_via_exhaustion():
    """WIN pattern : delta=-50 mais rvol_z=3.67 (exhaustion vendeur claire)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=-50.0, rvol_zscore=3.67)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")
    assert "ANTI_TOP" not in (sig.skip_reason or "")
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")


def test_win_4_passes_via_delta_positive():
    """WIN pattern : delta=+365 (forte conviction acheteurs)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=365.0)
    sig = eng.evaluate(bar)
    # Doit etre tradable ou bloque par autre chose (pas 3 filtres P4)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")
    assert "ANTI_TOP" not in (sig.skip_reason or "")
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")


def test_win_5_passes_normal():
    """WIN pattern : delta=+81 (acheteurs presents, conditions calmes)."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(delta_bar=81.0, vwap_slope_10=0.3)
    sig = eng.evaluate(bar)
    assert "ORDERFLOW_NO_BUYERS" not in (sig.skip_reason or "")
    assert "ANTI_TOP" not in (sig.skip_reason or "")
    assert "MOMENTUM_CAP" not in (sig.skip_reason or "")
