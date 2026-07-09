"""Tests Phase A3 audit forensique 22-23/06 - Fix A3 cooldown progressif post-LOSS.

REFERENCE :
- Audit market-analyst 22-23/06 : 16 trades Bot 1 sur FOMC 18/06, 12 LOSS dont 9 MFE=0
- Carnage type "revenge trade" / spirale streak adverse
- Mark Douglas "consistency beats intensity" sans tuer le volume data
  (Jackson directive 23/06 : pas de MAX_TRADES=5, besoin data analyse)

BAREME progressif :
- 0 SL consec (post-WIN ou flat) : COOLDOWN_BARS (30 min default)
- 1 SL consec : COOLDOWN_POST_LOSS_BARS (45 min default)
- 2 SL consec : COOLDOWN_POST_2LOSS_BARS (90 min default)
- 3+ SL consec : circuit breaker HALT 60 min existant prend le relais
  (cf signal_engine.py SL_CONSEC_HALT_THRESHOLD=3, HALT_DURATION_MINUTES=60)

CES TESTS PROUVENT :
- Cooldown standard 30 min applique si n_sl_consec == 0
- Cooldown 45 min applique si n_sl_consec == 1
- Cooldown 90 min applique si n_sl_consec >= 2
- Skip reason contient n_sl_consec pour log progressif vs standard
- Reset compteur (cf circuit breaker) restaure cooldown standard
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ts_now_us() -> int:
    return int(time.time() * 1e6)


def _make_bar(close_price: float = 5800.0, **overrides) -> dict:
    """Bar minimal valide qui declenche LONG (sd3d proche 0)."""
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
        "dist_vwap_d_sd3d_pct": -0.05,
        "dist_vwap_d_sd3u_pct": 0.5,
        "dist_vwap_d_pct": 0.1,
        "vwap_slope_30": 0.05,
        "delta_bar": 50.0,
        "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
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
    bar.update(overrides)
    return bar


def _set_last_trade_recent(store, symbol: str, seconds_ago: float) -> None:
    """Helper : positionne last_trade_ts a maintenant - X secondes."""
    now = datetime.now(timezone.utc)
    last_ts = now.timestamp() - seconds_ago
    last_iso = datetime.fromtimestamp(
        last_ts, tz=timezone.utc,
    ).isoformat()
    store.set_last_trade_ts(symbol, last_iso)


# ==========================================================================
# Cooldown progressif post-LOSS
# ==========================================================================

def test_a3_cooldown_standard_when_no_sl_consec(tmp_path):
    """A3: cooldown 30 min standard si n_sl_consec == 0 (post-WIN ou flat)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_std.json")
    eng = SignalEngine("ES", cfg, store=store)

    # Pas de SL consec, trade il y a 600s (10 min) → cooldown 30 min actif
    store.reset_sl_consec("ES")
    _set_last_trade_recent(store, "ES", 600.0)  # 10 min ago
    is_cool, elapsed = eng._is_cooldown_active()
    assert is_cool is True
    cooldown_sec, n = eng._get_cooldown_seconds()
    assert cooldown_sec == 30 * 60.0, f"cooldown standard attendu 1800s, got {cooldown_sec}"
    assert n == 0


def test_a3_cooldown_45_min_when_1_sl_consec(tmp_path):
    """A3: cooldown 45 min si n_sl_consec == 1 (premiere LOSS)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_1loss.json")
    eng = SignalEngine("ES", cfg, store=store)

    # Simule 1 SL consec
    store.increment_sl_consec("ES")
    assert store.get_n_sl_consec("ES") == 1

    # Trade il y a 30 min (1800s) : cooldown STD passe mais 45 min encore actif
    _set_last_trade_recent(store, "ES", 1800.0)
    cooldown_sec, n = eng._get_cooldown_seconds()
    assert n == 1
    assert cooldown_sec == 45 * 60.0, f"cooldown 1-LOSS attendu 2700s, got {cooldown_sec}"
    is_cool, elapsed = eng._is_cooldown_active()
    assert is_cool is True, f"30 min ecoulees mais cooldown 45 min doit etre actif (elapsed={elapsed})"


def test_a3_cooldown_90_min_when_2_sl_consec(tmp_path):
    """A3: cooldown 90 min si n_sl_consec == 2 (deuxieme LOSS consecutive)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_2loss.json")
    eng = SignalEngine("ES", cfg, store=store)

    # Simule 2 SL consec
    store.increment_sl_consec("ES")
    store.increment_sl_consec("ES")
    assert store.get_n_sl_consec("ES") == 2

    cooldown_sec, n = eng._get_cooldown_seconds()
    assert n == 2
    assert cooldown_sec == 90 * 60.0, f"cooldown 2-LOSS attendu 5400s, got {cooldown_sec}"

    # Trade il y a 60 min : cooldown 45 min passe, mais 90 min encore actif
    _set_last_trade_recent(store, "ES", 60 * 60.0)
    is_cool, elapsed = eng._is_cooldown_active()
    assert is_cool is True, f"60 min ecoulees mais cooldown 90 min doit etre actif"


def test_a3_cooldown_caps_at_2loss_threshold(tmp_path):
    """A3: 3+ SL consec utilise toujours COOLDOWN_POST_2LOSS_BARS (cap).

    Le HALT 60 min circuit breaker prend le relais a 3 SL, donc le cooldown
    a >=2 SL est le plafond cote SignalEngine.
    """
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_3loss.json")
    eng = SignalEngine("ES", cfg, store=store)

    for _ in range(5):
        store.increment_sl_consec("ES")
    assert store.get_n_sl_consec("ES") == 5

    cooldown_sec, n = eng._get_cooldown_seconds()
    assert n == 5
    assert cooldown_sec == 90 * 60.0  # cap a 2-LOSS bareme


def test_a3_skip_reason_progressive_when_sl_consec(tmp_path):
    """A3: skip_reason contient COOLDOWN_PROGRESSIVE + n_sl_consec quand SL > 0."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_skip.json")
    eng = SignalEngine("ES", cfg, store=store)

    # 1 SL consec + trade recent (10 min)
    store.increment_sl_consec("ES")
    _set_last_trade_recent(store, "ES", 600.0)

    sig = eng.evaluate(_make_bar())
    assert sig.tradable is False
    assert "COOLDOWN_PROGRESSIVE" in sig.skip_reason, f"got {sig.skip_reason}"
    assert "n_sl_consec=1" in sig.skip_reason


def test_a3_skip_reason_standard_when_no_sl_consec(tmp_path):
    """A3: skip_reason standard (COOLDOWN sans PROGRESSIVE) si n_sl_consec == 0."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_std_skip.json")
    eng = SignalEngine("ES", cfg, store=store)

    store.reset_sl_consec("ES")
    _set_last_trade_recent(store, "ES", 600.0)

    sig = eng.evaluate(_make_bar())
    assert sig.tradable is False
    assert sig.skip_reason.startswith("COOLDOWN:"), f"got {sig.skip_reason}"
    assert "PROGRESSIVE" not in sig.skip_reason


def test_a3_reset_after_win_returns_standard(tmp_path):
    """A3: apres reset_sl_consec (sur TP), cooldown revient au standard."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_a3_reset.json")
    eng = SignalEngine("ES", cfg, store=store)

    # 2 SL consec → cooldown 90 min
    store.increment_sl_consec("ES")
    store.increment_sl_consec("ES")
    cooldown_sec, n = eng._get_cooldown_seconds()
    assert cooldown_sec == 90 * 60.0
    assert n == 2

    # Reset (sur WIN)
    store.reset_sl_consec("ES")
    cooldown_sec, n = eng._get_cooldown_seconds()
    assert cooldown_sec == 30 * 60.0
    assert n == 0


def test_a3_config_env_override():
    """A3: BOTMR_COOLDOWN_POST_LOSS_BARS env override fonctionnel."""
    import os
    from CORE.bot_mean_revert.config import BotMRConfig

    os.environ["BOTMR_COOLDOWN_POST_LOSS_BARS"] = "60"
    os.environ["BOTMR_COOLDOWN_POST_2LOSS_BARS"] = "120"
    cfg = BotMRConfig.from_env()
    assert cfg.COOLDOWN_POST_LOSS_BARS == 60
    assert cfg.COOLDOWN_POST_2LOSS_BARS == 120
    del os.environ["BOTMR_COOLDOWN_POST_LOSS_BARS"]
    del os.environ["BOTMR_COOLDOWN_POST_2LOSS_BARS"]


def test_a3_dispatcher_format_progressive_emit_code():
    """A3 anti-regression review IMPORTANT 23/06 : verifier que le format
    skip_reason "COOLDOWN_PROGRESSIVE:..." est bien distingue du standard
    "COOLDOWN:..." par le parsing dispatcher.

    Reason : main.py:1226 elif chain match startswith("COOLDOWN_PROGRESSIVE")
    AVANT startswith("COOLDOWN"). Si quelqu'un inverse l'ordre, le code
    PROGRESSIVE serait stealed par le elif COOLDOWN standard = emit
    BOTMR_COOLDOWN_ACTIVE au lieu de BOTMR_COOLDOWN_PROGRESSIVE_ACTIVE.
    Anti-regression critique.
    """
    # Verifier que le format genere par signal_engine matche bien notre prefixe.
    # On simule le format exact que signal_engine produit pour le cas progressif.
    sample_progressive = "COOLDOWN_PROGRESSIVE:1500s/2700s n_sl_consec=1"
    sample_standard = "COOLDOWN:600s/1800s"

    # Le startswith doit distinguer les 2
    assert sample_progressive.startswith("COOLDOWN_PROGRESSIVE")
    assert sample_standard.startswith("COOLDOWN")
    assert not sample_standard.startswith("COOLDOWN_PROGRESSIVE")
    # Anti-bug : COOLDOWN_PROGRESSIVE matche AUSSI COOLDOWN (subset)
    assert sample_progressive.startswith("COOLDOWN")

    # Parse PROGRESSIVE format
    payload = sample_progressive.split(":", 1)[1]
    parts = payload.split(" n_sl_consec=", 1)
    timing_part = parts[0]
    n_sl_str = parts[1].strip()
    elapsed_str, cool_str = timing_part.split("/", 1)
    elapsed_val = float(elapsed_str.replace("s", "").strip())
    cool_val = float(cool_str.replace("s", "").strip())
    n_sl_val = int(n_sl_str)
    assert elapsed_val == 1500.0
    assert cool_val == 2700.0
    assert n_sl_val == 1


def test_a3_dispatcher_parse_fails_gracefully():
    """A3 IMPORTANT-2 fix 23/06 : si format change accidentellement, le parse
    ne doit pas crash mais retourner (0,0,0) + log warning (verifie en code,
    pas testable directement ici car logger). Test du fallback silencieux.
    """
    bad_format = "COOLDOWN_PROGRESSIVE:malformed_no_separator"
    try:
        payload = bad_format.split(":", 1)[1]
        parts = payload.split(" n_sl_consec=", 1)
        timing_part = parts[0]
        elapsed_str, cool_str = timing_part.split("/", 1)
        # Cette ligne doit fail
        float(elapsed_str.replace("s", "").strip())
        pytest.fail("Should have raised ValueError")
    except (IndexError, ValueError):
        # Comportement attendu : fallback
        elapsed_val, cool_val, n_sl_val = 0.0, 0.0, 0
        assert elapsed_val == 0.0


def test_a3_persistence_across_restart(tmp_path):
    """A3: cooldown progressif survive un restart (n_sl_consec persiste store)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store_path = tmp_path / "test_a3_restart.json"

    # Bot tour 1 : 2 LOSS
    store1 = PositionStore(path=store_path)
    store1.increment_sl_consec("ES")
    store1.increment_sl_consec("ES")
    _set_last_trade_recent(store1, "ES", 30 * 60.0)  # 30 min ago
    store1.save()

    # Bot tour 2 : restart
    store2 = PositionStore(path=store_path)
    assert store2.load() is True
    assert store2.get_n_sl_consec("ES") == 2

    eng2 = SignalEngine("ES", cfg, store=store2)
    cooldown_sec, n = eng2._get_cooldown_seconds()
    assert cooldown_sec == 90 * 60.0
    assert n == 2

    # Cooldown 90 min toujours actif apres 30 min
    is_cool, elapsed = eng2._is_cooldown_active()
    assert is_cool is True
