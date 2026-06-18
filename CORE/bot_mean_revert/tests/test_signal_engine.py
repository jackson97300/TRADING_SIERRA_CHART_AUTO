"""Tests SignalEngine Bot MR."""
from __future__ import annotations

import time

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


def _ts_now_us() -> int:
    """ts ms en plein milieu RTH US (15:00 UTC = 11:00 ET).

    15:00 UTC pour eviter le pre-open 11:30-13:30 UTC.
    """
    import datetime as _dt
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _ts_asia() -> int:
    """ts ms en pleine session Asia (02:00 UTC)."""
    import datetime as _dt
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=2, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es(direction: str, **overrides) -> dict:
    """Bar ES synthetique en session US RTH avec extension SD3.

    SignalEngine teste d_low <= -thr AVANT d_high >= thr donc avec thr=0.0
    le d_low par defaut (0.0) declenche LONG meme pour SHORT. On met une valeur
    strictement positive sur le cote NON utilise pour garantir le bon side.
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
        # SD3 extensions defaults : valeurs positives strictes pour eviter
        # detection LONG fortuite (d_low <= -0 == True si 0.0 default)
        "dist_vwap_d_sd3d_pct": 0.10,
        "dist_vwap_d_sd3u_pct": -0.10,
        # Phase 4 18/06 defaults neutres pour 3 filtres orderflow / anti-top / momentum :
        #  - delta_bar : valeur coherente avec direction (set ci-dessous)
        #  - bars_since_last_swing_high/low : eleves (>5) -> anti-top bypass
        #  - vwap_slope_10 : faible -> momentum cap bypass
        #  - dist_1d_max/min_ticks : loin du HOD/LOD
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    if direction == "LONG":
        bar["dist_vwap_d_sd3d_pct"] = -0.10  # prix sous SD3d
        bar["dist_vwap_d_sd3u_pct"] = -0.20
        bar["vwap_slope_30"] = 0.05  # trend up (trend_align_es LONG)
        bar["delta_bar"] = 50.0  # acheteurs presents (orderflow OK LONG)
    elif direction == "SHORT":
        bar["dist_vwap_d_sd3u_pct"] = 0.10  # prix au-dessus SD3u
        bar["dist_vwap_d_sd3d_pct"] = 0.20
        bar["vwap_slope_30"] = -0.05  # trend down (trend_align_es SHORT)
        bar["delta_bar"] = -50.0  # vendeurs presents (orderflow OK SHORT)
    bar.update(overrides)
    return bar


def _make_bar_nq(direction: str, **overrides) -> dict:
    """Bar NQ synthetique en session Asia avec extension SD3."""
    bar = {
        "ts": _ts_asia(),
        "session_id": "ASIA",
        "is_in_us_cash": False,
        "close": 21000.0,
        "bar_high": 21002.0,
        "bar_low": 20998.0,
        "vix_level": 18.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": 0.10,
        "dist_vwap_d_sd3u_pct": -0.10,
        # Phase 4 18/06 defaults neutres (cf _make_bar_es)
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    if direction == "LONG":
        bar["dist_vwap_d_sd3d_pct"] = -0.10
        bar["dist_vwap_d_sd3u_pct"] = -0.20
        bar["vwap_slope_30"] = -0.04  # NQ contrarian : LONG si slope<0
        bar["delta_bar"] = 50.0
    elif direction == "SHORT":
        bar["dist_vwap_d_sd3u_pct"] = 0.10
        bar["dist_vwap_d_sd3d_pct"] = 0.20
        bar["vwap_slope_30"] = 0.04  # NQ contrarian : SHORT si slope>0
        bar["delta_bar"] = -50.0
    bar.update(overrides)
    return bar


def test_long_es_sd3_baseline():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG")
    sig = eng.evaluate(bar)
    assert sig.tradable is True
    assert sig.direction == "LONG"
    assert sig.sl_ticks == 20
    assert sig.tp_ticks == 30  # 20 * 1.5
    assert sig.entry_price == 5800.0
    # SL = entry - 20*0.25 = 5795.0
    assert abs(sig.sl_price - 5795.0) < 1e-6
    # TP = entry + 30*0.25 = 5807.5
    assert abs(sig.tp_price - 5807.5) < 1e-6


def test_short_es_sd3_with_vix_floor():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    # VIX < 20 -> blocked
    bar = _make_bar_es("SHORT", vix_level=15.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "VIX_TOO_LOW" in sig.skip_reason
    # VIX >= 20 -> allowed (reset cooldown puisque previous emit a bump compteur)
    eng2 = SignalEngine("ES", cfg)
    bar2 = _make_bar_es("SHORT", vix_level=25.0)
    sig2 = eng2.evaluate(bar2)
    assert sig2.tradable is True
    assert sig2.direction == "SHORT"


def test_rvol_filter_blocks_low_volume():
    cfg = BotMRConfig()
    # Set RVOL_ZSCORE_MIN = 1.5 via monkeypatch dans dataclass via env
    import dataclasses
    cfg2 = dataclasses.replace(cfg, RVOL_ZSCORE_MIN=1.5)
    eng = SignalEngine("ES", cfg2)
    bar = _make_bar_es("LONG", rvol_zscore=0.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "RVOL_TOO_LOW" in sig.skip_reason


def test_regime_blocks_es_long_when_slope_negative():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG", vwap_slope_30=-0.05)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REGIME_TREND_ES_LONG_BLOCKED" in sig.skip_reason


def test_regime_blocks_nq_short_when_trend_day_too_high():
    cfg = BotMRConfig()
    eng = SignalEngine("NQ", cfg)
    bar = _make_bar_nq("SHORT", ctx_trend_day_score=0.9)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "NQ_TREND_DAY_TOO_HIGH" in sig.skip_reason


def test_cooldown_blocks_consecutive_signals():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG")
    sig1 = eng.evaluate(bar)
    assert sig1.tradable is True
    eng.register_trade(sig1.signal_id)
    # Immediate next bar -> cooldown
    sig2 = eng.evaluate(bar)
    assert sig2.tradable is False
    assert "COOLDOWN" in sig2.skip_reason


def test_cooldown_3_releases_after_3_bars():
    """Backtest 5j (18/06) montre cooldown=3 optimal (PF 2.14 vs 0.93 a cooldown=30)."""
    cfg = BotMRConfig()
    object.__setattr__(cfg, "COOLDOWN_BARS", 3)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG")
    sig1 = eng.evaluate(bar)
    assert sig1.tradable is True
    eng.register_trade(sig1.signal_id)
    # Bar 1, 2 : encore cooldown (counter 1, 2 < 3)
    for i in range(2):
        sig_block = eng.evaluate(bar)
        assert sig_block.tradable is False
        assert "COOLDOWN" in sig_block.skip_reason
    # Bar 3 : counter = 3 >= 3 -> liberé
    sig_release = eng.evaluate(bar)
    assert sig_release.tradable is True
    assert "COOLDOWN" not in (sig_release.skip_reason or "")


def test_cooldown_env_var_override():
    """Verifie env var BOTMR_COOLDOWN_BARS override le default 30."""
    import os
    os.environ["BOTMR_COOLDOWN_BARS"] = "3"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.COOLDOWN_BARS == 3
    finally:
        del os.environ["BOTMR_COOLDOWN_BARS"]


# ==========================================================================
# Cooldown TIME-BASED (refactor 18/06 fix bug bypass restart)
# ==========================================================================


def test_cooldown_time_based_with_store():
    """Time-based : register_trade stocke last_trade_ts, cooldown applique."""
    import tempfile
    from pathlib import Path

    from CORE.bot1_v2.state.position_store import PositionStore

    with tempfile.TemporaryDirectory() as tmp:
        store = PositionStore(path=Path(tmp) / "store.json")
        cfg = BotMRConfig()
        object.__setattr__(cfg, "COOLDOWN_BARS", 3)  # = 180 sec time-based
        eng = SignalEngine("ES", cfg, store=store)
        bar = _make_bar_es("LONG")
        sig1 = eng.evaluate(bar)
        assert sig1.tradable is True  # 1ere eval OK (pas de last_trade_ts)
        eng.register_trade(sig1.signal_id)
        # Immediate next : cooldown active
        sig2 = eng.evaluate(bar)
        assert sig2.tradable is False
        assert "COOLDOWN" in sig2.skip_reason
        # Format time-based : "Ns/Ns"
        assert "s/" in sig2.skip_reason, f"format inattendu : {sig2.skip_reason}"


def test_cooldown_persists_across_restart():
    """REGRESSION bug 18/06 : restart ne doit PAS bypass cooldown si dans fenetre.

    Scenario reproduit :
      - 00:55 trade #2 entry -> register_trade -> last_trade_ts persiste
      - 01:11 BOT RESTART (crash/maintenance) -> nouvelle PositionStore + SignalEngine
      - 01:13 ~18 bars apres trade #2 : cooldown DOIT toujours etre actif
        (en counter-based, le restart resettait counter=COOLDOWN_BARS = bypass).
    """
    import tempfile
    from pathlib import Path

    from CORE.bot1_v2.state.position_store import PositionStore

    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "store.json"
        # --- SESSION 1 : entry + register_trade + save ---
        store1 = PositionStore(path=store_path)
        cfg = BotMRConfig()
        object.__setattr__(cfg, "COOLDOWN_BARS", 3)  # = 180 sec
        eng1 = SignalEngine("ES", cfg, store=store1)
        bar = _make_bar_es("LONG")
        sig1 = eng1.evaluate(bar)
        assert sig1.tradable is True
        eng1.register_trade(sig1.signal_id)
        assert store1.save() is True

        # --- SESSION 2 : RESTART -> new store load + new engine ---
        store2 = PositionStore(path=store_path)
        assert store2.load() is True
        # Verif persistence sanity : last_trade_ts loaded
        assert store2.get_last_trade_ts("ES") is not None
        eng2 = SignalEngine("ES", cfg, store=store2)

        # Immediate eval : cooldown DOIT etre actif (time elapsed <<< 180s)
        sig2 = eng2.evaluate(bar)
        assert sig2.tradable is False, (
            f"BUG REGRESSION : restart a bypass le cooldown "
            f"(skip_reason={sig2.skip_reason})"
        )
        assert "COOLDOWN" in sig2.skip_reason


def test_cooldown_releases_after_time_window():
    """Time-based cooldown libere apres time elapse (simule via set_last_trade_ts old)."""
    import tempfile
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from CORE.bot1_v2.state.position_store import PositionStore

    with tempfile.TemporaryDirectory() as tmp:
        store = PositionStore(path=Path(tmp) / "store.json")
        cfg = BotMRConfig()
        object.__setattr__(cfg, "COOLDOWN_BARS", 1)  # = 60 sec
        eng = SignalEngine("ES", cfg, store=store)
        # Simule trade fait il y a 90 sec (> 60 sec cooldown)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        store.set_last_trade_ts("ES", old_ts)
        bar = _make_bar_es("LONG")
        sig = eng.evaluate(bar)
        # 90s > 60s cooldown_sec -> liberation
        assert sig.tradable is True, (
            f"Cooldown aurait du etre libere apres 90s > 60s "
            f"(skip_reason={sig.skip_reason})"
        )


def test_legacy_counter_mode_still_works_without_store():
    """Backward compat : sans store, comportement counter-based legacy preserve."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)  # NO store
    bar = _make_bar_es("LONG")
    sig1 = eng.evaluate(bar)
    assert sig1.tradable is True  # init counter = COOLDOWN_BARS (ready)
    eng.register_trade(sig1.signal_id)
    # Next : counter = 0 + bump = 1, 1 < 30 = block
    sig2 = eng.evaluate(bar)
    assert sig2.tradable is False
    assert "COOLDOWN" in sig2.skip_reason
    # Format legacy : "N/N" sans "s"
    assert "s/" not in sig2.skip_reason, (
        f"Mode legacy doit utiliser format counter-based : {sig2.skip_reason}"
    )


def test_cooldown_time_based_corrupted_iso_fails_open():
    """Edge case : ISO corrompu -> fail-open (pas de cooldown) plutot que crash."""
    import tempfile
    from pathlib import Path

    from CORE.bot1_v2.state.position_store import PositionStore

    with tempfile.TemporaryDirectory() as tmp:
        store = PositionStore(path=Path(tmp) / "store.json")
        cfg = BotMRConfig()
        eng = SignalEngine("ES", cfg, store=store)
        # Force ISO corrompu
        store.set_last_trade_ts("ES", "not-an-iso-date")
        bar = _make_bar_es("LONG")
        sig = eng.evaluate(bar)
        # Doit passer (fail-open) plutot que crash
        assert sig.tradable is True


def test_cooldown_resilience_crash_between_register_and_save(tmp_path):
    """REGRESSION R2 code-reviewer 18/06 : si crash apres register_trade SANS
    save(), le bug racine 18/06 reapparait. Apres fix R2, register_trade est
    appele AVANT open_position, donc save() unique en fin de bloc persiste
    forcement le last_trade_ts.

    Ce test verifie le contrat minimum : si register_trade est appele PUIS
    save(), le restart suivant applique bien le cooldown.
    """
    from CORE.bot1_v2.state.position_store import PositionStore

    store_path = tmp_path / "state.json"
    cfg = BotMRConfig()
    object.__setattr__(cfg, "COOLDOWN_BARS", 3)  # = 180 sec

    # --- Session 1 : register puis save (PAS de close_trade entre les deux) ---
    store1 = PositionStore(path=store_path)
    eng1 = SignalEngine("NQ", cfg, store=store1)
    eng1.register_trade(signal_id="sig1")
    # PAS de close_trade ou autre appel - juste register puis save
    assert store1.save() is True

    # --- Session 2 : restart immediat ---
    store2 = PositionStore(path=store_path)
    assert store2.load() is True
    eng2 = SignalEngine("NQ", cfg, store=store2)

    # Cooldown doit etre actif (le last_trade_ts est persiste)
    tradable, elapsed = eng2._is_cooldown_active()
    assert tradable is True, (
        f"cooldown doit etre actif apres restart immediat "
        f"(elapsed={elapsed}, last_ts={store2.get_last_trade_ts('NQ')})"
    )


def test_cooldown_iso_corrupted_triggers_callback(tmp_path):
    """REGRESSION R1 code-reviewer 18/06 : si ISO corrompu, callback doit
    etre appele pour tracer le bypass (anti-pattern silent fallback 19/04
    meta-labeler documente .claude/rules/critical-tasks-review.md)."""
    from CORE.bot1_v2.state.position_store import PositionStore

    store_path = tmp_path / "state.json"
    cfg = BotMRConfig()

    store = PositionStore(path=store_path)
    store.set_last_trade_ts("NQ", "garbage-not-iso")

    captured: list[tuple[str, str]] = []

    def on_corrupted(sym: str, iso: str) -> None:
        captured.append((sym, iso))

    eng = SignalEngine("NQ", cfg, store=store, on_corrupted_state=on_corrupted)
    bar = _make_bar_nq("LONG")
    sig = eng.evaluate(bar)

    # fail-open = pas bloque par cooldown (mais peut etre bloque autrement)
    # On verifie SEULEMENT que le cooldown gate a fail-open + callback fire
    assert "COOLDOWN" not in (sig.skip_reason or ""), (
        f"ISO corrompu doit fail-open le cooldown : {sig.skip_reason}"
    )
    assert len(captured) == 1, f"callback doit etre appele 1x : captured={captured}"
    assert captured[0] == ("NQ", "garbage-not-iso")
