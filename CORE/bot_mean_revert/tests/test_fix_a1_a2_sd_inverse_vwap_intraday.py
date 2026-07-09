"""Tests Phase A audit forensique 22-23/06 - Fix A1 (condition SD inversee)
+ Fix A2 (gate VWAP intraday).

REFERENCE :
- Audit market-analyst 22-23/06 : 1030 LONG / 0 SHORT le 18/06 = bug structurel
- Convention DMP empirique : sd3d_pct ∈ [-1.80, 0.00], sd3u_pct ∈ [0.01, 1.18]
- Backtest validation A0 : SHORT ES = +430 ticks WR 42.1% (vs 0 SHORT avant)
- Fix A2 backed up par : 9/12 LOSS Bot 1 18/06 ont MFE=0 (75% fade immediat)

CES TESTS PROUVENT :
- A1 permet SHORTs (impossible avant le fix)
- A1 LONG fonctionne quand sd3d_pct proche 0 (vraie extension down)
- A1 NO_EXTENSION quand prix au milieu (entre SD3 bands)
- A2 bloque LONG si prix sous VWAP-d intraday de > seuil
- A2 bloque SHORT si prix au-dessus VWAP-d de > seuil
- A2 passe-through si dist_vwap_d_pct absent (fail-open backward compat)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ts_now_us() -> int:
    return int(time.time() * 1e6)


def _make_bar(close_price: float = 5800.0, sd3d_pct=-0.05, sd3u_pct=0.5,
              dist_vwap_d_pct=None, **overrides) -> dict:
    """Bar minimal pour tests A1+A2.

    sd3d_pct default -0.05 = LONG trigger (proche SD3 down, extension valide).
    sd3u_pct default 0.5 = SHORT bloque (loin SD3 up).
    """
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": close_price,
        "bar_high": close_price + 1.0,
        "bar_low": close_price - 1.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": sd3d_pct,
        "dist_vwap_d_sd3u_pct": sd3u_pct,
        "vwap_slope_30": 0.05,
        "delta_bar": 50.0,
        "finish_strength": 1.0,  # pour passer ULTRATHINK
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        # Niveaux loin pour eviter confluence/orderflow noise
        "dist_mq_hvl_pct": 5.0,
        "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0,
        "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0,
        "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0,
        "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0,
        "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0,
        "dist_vwap_w_sd1d_pct": -3.0,
    }
    if dist_vwap_d_pct is not None:
        bar["dist_vwap_d_pct"] = dist_vwap_d_pct
    bar.update(overrides)
    return bar


# ==========================================================================
# Fix A1 — Condition SD inversee
# ==========================================================================

def test_a1_long_triggers_when_sd3d_close_to_zero():
    """A1: LONG trigger quand sd3d_pct >= -thr (proche SD3 down = vraie extension)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()  # SD_THRESHOLD_PCT=0.1 par defaut
    store = PositionStore(path=Path("/tmp/test_a1_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # sd3d_pct = -0.05, >= -0.1 (-thr) → LONG trigger
    bar = _make_bar(sd3d_pct=-0.05, sd3u_pct=0.5)
    sig = eng.evaluate(bar)
    assert sig.direction == "LONG", f"sd3d_pct=-0.05 doit declencher LONG, got direction={sig.direction} reason={sig.skip_reason}"


def test_a1_short_triggers_when_sd3u_close_to_zero():
    """A1: SHORT trigger quand sd3u_pct <= thr (proche SD3 up = vraie extension)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_a1_short_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # sd3d_pct=-0.5 (loin SD3 down) + sd3u_pct=0.05 (proche SD3 up) → SHORT
    bar = _make_bar(sd3d_pct=-0.5, sd3u_pct=0.05)
    sig = eng.evaluate(bar)
    assert sig.direction == "SHORT", f"sd3u_pct=0.05 doit declencher SHORT, got direction={sig.direction} reason={sig.skip_reason}"


def test_a1_no_extension_when_price_mid_bands():
    """A1: NO_EXTENSION si prix au milieu entre SD3 bands (ni LONG ni SHORT)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_a1_noext_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # sd3d_pct=-0.5 (loin SD3 down) + sd3u_pct=0.5 (loin SD3 up) → NO_EXTENSION
    bar = _make_bar(sd3d_pct=-0.5, sd3u_pct=0.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "NO_EXTENSION" in sig.skip_reason


def test_a1_threshold_env_override():
    """A1: SD_THRESHOLD_PCT env override modifie le seuil."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig

    os.environ["BOTMR_SD_THRESHOLD_PCT"] = "0.2"
    cfg = BotMRConfig.from_env()
    assert cfg.SD_THRESHOLD_PCT == 0.2
    del os.environ["BOTMR_SD_THRESHOLD_PCT"]


# ==========================================================================
# Fix A2 — Gate VWAP intraday
# ==========================================================================

def test_a2_long_blocked_below_vwap():
    """A2: LONG bloque si dist_vwap_d_pct < -thr (prix sous VWAP-d intraday)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()  # VWAP_INTRADAY_LONG_BLOCK_PCT=0.3
    store = PositionStore(path=Path("/tmp/test_a2_long_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # LONG trigger valide (sd3d proche 0) MAIS dist_vwap_d_pct = -0.5 (sous VWAP)
    bar = _make_bar(sd3d_pct=-0.05, sd3u_pct=0.5, dist_vwap_d_pct=-0.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "LONG_BELOW_VWAP_INTRADAY" in sig.skip_reason


def test_a2_short_blocked_above_vwap():
    """A2: SHORT bloque si dist_vwap_d_pct > thr (prix au-dessus VWAP-d)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_a2_short_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(sd3d_pct=-0.5, sd3u_pct=0.05, dist_vwap_d_pct=0.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SHORT_ABOVE_VWAP_INTRADAY" in sig.skip_reason


def test_a2_long_allowed_above_vwap_no_block():
    """A2: LONG OK si prix proche/au-dessus VWAP-d (pas de trend down clair)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_a2_longok_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(sd3d_pct=-0.05, sd3u_pct=0.5, dist_vwap_d_pct=0.1)  # prix proche VWAP
    sig = eng.evaluate(bar)
    assert sig.direction == "LONG"
    # On va plus loin que A2 (peut etre bloque par autres gates, mais pas par A2)
    assert "LONG_BELOW_VWAP" not in sig.skip_reason


def test_a2_fail_open_no_dist_vwap_d_pct():
    """A2: si dist_vwap_d_pct absent du bar, gate fail-open (backward compat)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_a2_failopen_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # Pas de dist_vwap_d_pct dans le bar → A2 fail-open
    bar = _make_bar(sd3d_pct=-0.05, sd3u_pct=0.5)  # dist_vwap_d_pct=None
    sig = eng.evaluate(bar)
    assert sig.direction == "LONG"
    assert "LONG_BELOW_VWAP" not in sig.skip_reason


def test_a2_thresholds_env_override():
    """A2: VWAP_INTRADAY_LONG_BLOCK_PCT/SHORT env override fonctionnel."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig

    os.environ["BOTMR_VWAP_INTRADAY_LONG_BLOCK_PCT"] = "0.5"
    os.environ["BOTMR_VWAP_INTRADAY_SHORT_BLOCK_PCT"] = "0.4"
    cfg = BotMRConfig.from_env()
    assert cfg.VWAP_INTRADAY_LONG_BLOCK_PCT == 0.5
    assert cfg.VWAP_INTRADAY_SHORT_BLOCK_PCT == 0.4
    del os.environ["BOTMR_VWAP_INTRADAY_LONG_BLOCK_PCT"]
    del os.environ["BOTMR_VWAP_INTRADAY_SHORT_BLOCK_PCT"]


# ==========================================================================
# EDGE CASES post-review code-reviewer 23/06 (BUG #1 + #3)
# ==========================================================================

def test_bug1_a2_dist_vwap_d_pct_exactly_zero_passes():
    """BUG #1 fix : dist_vwap_d_pct=0.0 exact (close==VWAP) ne bloque PAS.

    Avant fix : `_f(None)=0.0` + `is not None` toujours True. Aucun moyen de
    distinguer 0.0 legitime (close exactement sur VWAP) de feature absente.
    Apres fix : valeur brute recuperee, 0.0 explicite = pass through legitime
    (gate compare a -0.3 et +0.3, donc 0.0 OK des deux cotes).
    """
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_bug1_zero_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # LONG trigger valide (sd3d proche 0) + dist_vwap_d_pct = 0.0 exact
    bar = _make_bar(sd3d_pct=-0.05, sd3u_pct=0.5, dist_vwap_d_pct=0.0)
    sig = eng.evaluate(bar)
    assert sig.direction == "LONG", f"dist=0.0 doit passer LONG, got {sig.direction} reason={sig.skip_reason}"
    assert "LONG_BELOW_VWAP" not in sig.skip_reason
    assert "SHORT_ABOVE_VWAP" not in sig.skip_reason


def test_bug3_a1_fail_loud_when_sd_features_absent():
    """BUG #3 fix : si sd3d_pct OU sd3u_pct absent du bar, NO trade fail-loud.

    Avant fix : `_f(None)=0.0` + `0.0 >= -0.1 = True` → LONG fantome silencieux
    (anti-pattern V1 Gamma=0.0 lessons.md). Le bot tradait sur "feature corrompue"
    croyant qu'elle valait 0.0 = bord du SD3 inferieur.
    Apres fix : detection des None bruts -> SD_FEATURE_MISSING skip explicite
    + emit code BOTMR_SD_FEATURE_MISSING (MAJEUR).
    """
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=Path("/tmp/test_bug3_absent_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    # Cas 1 : sd3d_pct absent
    bar = _make_bar()
    bar.pop("dist_vwap_d_sd3d_pct", None)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SD_FEATURE_MISSING" in sig.skip_reason, f"sd3d absent doit fail-loud, got {sig.skip_reason}"

    # Cas 2 : sd3u_pct absent
    bar = _make_bar()
    bar.pop("dist_vwap_d_sd3u_pct", None)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SD_FEATURE_MISSING" in sig.skip_reason, f"sd3u absent doit fail-loud, got {sig.skip_reason}"

    # Cas 3 : les deux absents
    bar = _make_bar()
    bar.pop("dist_vwap_d_sd3d_pct", None)
    bar.pop("dist_vwap_d_sd3u_pct", None)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "SD_FEATURE_MISSING" in sig.skip_reason


def test_a1_boundary_sd3d_exactly_minus_threshold():
    """A1 edge case : sd3d_pct == -thr EXACT doit declencher LONG (`>=` inclusif).

    Si SD_THRESHOLD_PCT=0.1, sd3d_pct=-0.1 est la frontiere exacte.
    Convention : `>= -thr` = inclusif. Documente pour eviter regression future
    si quelqu'un change `>=` -> `>` (1030 LONG redeviennent 0 LONG).
    """
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()  # SD_THRESHOLD_PCT=0.1
    store = PositionStore(path=Path("/tmp/test_boundary_store.json"))
    eng = SignalEngine("ES", cfg, store=store)

    bar = _make_bar(sd3d_pct=-0.1, sd3u_pct=0.5, dist_vwap_d_pct=0.1)
    sig = eng.evaluate(bar)
    assert sig.direction == "LONG", f"sd3d_pct=-thr exact doit declencher LONG (inclusif), got {sig.direction} reason={sig.skip_reason}"
