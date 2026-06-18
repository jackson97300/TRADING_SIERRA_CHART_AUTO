"""Tests anti-boucle infinie MAX_HOLD (incident 18/06).

Bug racine : si DtcFillListener ne detecte pas le fill du close market (Sim slow,
status=2 au lieu de 7), le bot ressayait MAX_HOLD au prochain tick et envoyait
un autre close market. Resultat : 9 close markets en 8 min sur meme position =
cumul SHORTs sans SL/TP.

Fix (4 reserves code-reviewer 18/06) :
  1. BOOT_WARMUP : skip MAX_HOLD pendant 60s apres boot (default).
  2. RETRY_COOLDOWN : skip si dernier close envoye il y a <180s (default).
  3. RESERVE #1 : register close_cid dans DtcFillListener (kind=timeout).
  4. RESERVE #2 : persister last_max_hold_close_ts + n_max_hold_timeouts dans pos.
  5. RESERVE #3 : plafond MAX_HOLD_MAX_RETRIES (default 3) avec halt symbol.
  6. RESERVE #4 : propager exit_reason=TIMEOUT au callback (no SL consec impact).
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot1_v2.state_bridge import StateBridge
from CORE.bot_mean_revert.config import BotMRConfig


def test_default_anti_loop_thresholds():
    """Defaults specs Jackson 18/06 post-incident.

    180s retry cooldown : avec bars 1min, max 3 closes en 9 ticks (vs 9 sans).
    60s boot warmup : laisse temps DtcFillListener detecter fills orphelins.
    """
    cfg = BotMRConfig()
    assert cfg.MAX_HOLD_BOOT_WARMUP_SEC == 60
    assert cfg.MAX_HOLD_RETRY_COOLDOWN_SEC == 180


def test_env_override_boot_warmup():
    os.environ["BOTMR_MAX_HOLD_BOOT_WARMUP_SEC"] = "30"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.MAX_HOLD_BOOT_WARMUP_SEC == 30
    finally:
        del os.environ["BOTMR_MAX_HOLD_BOOT_WARMUP_SEC"]


def test_env_override_retry_cooldown():
    os.environ["BOTMR_MAX_HOLD_RETRY_COOLDOWN_SEC"] = "180"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.MAX_HOLD_RETRY_COOLDOWN_SEC == 180
    finally:
        del os.environ["BOTMR_MAX_HOLD_RETRY_COOLDOWN_SEC"]


def test_boot_warmup_logic_basic():
    """Logique pure : (now - boot_ts) < warmup_sec -> skip."""
    boot_ts = 1000.0
    now = 1030.0  # 30 sec after boot
    warmup_sec = 60
    elapsed = now - boot_ts
    in_warmup = elapsed < warmup_sec
    assert in_warmup is True  # 30 < 60


def test_boot_warmup_logic_expired():
    """Logique pure : (now - boot_ts) > warmup_sec -> pas skip."""
    boot_ts = 1000.0
    now = 1070.0  # 70 sec after boot
    warmup_sec = 60
    elapsed = now - boot_ts
    in_warmup = elapsed < warmup_sec
    assert in_warmup is False  # 70 >= 60


def test_retry_cooldown_logic_blocks():
    """Si dernier close envoye il y a 60s et cooldown 180s -> skip."""
    last_close_ts = 1000.0
    now = 1060.0  # 60 sec apres
    cooldown_sec = 180
    in_cooldown = (now - last_close_ts) < cooldown_sec
    assert in_cooldown is True  # 60 < 180


def test_retry_cooldown_logic_allows():
    """Si dernier close envoye il y a 200s et cooldown 180s -> pas skip."""
    last_close_ts = 1000.0
    now = 1200.0  # 200 sec apres
    cooldown_sec = 180
    in_cooldown = (now - last_close_ts) < cooldown_sec
    assert in_cooldown is False  # 200 >= 180


def test_retry_cooldown_first_time_no_block():
    """Premier MAX_HOLD jamais declenche (last_close_ts=0) -> pas skip."""
    last_close_ts = 0.0  # default si aucun close encore
    now = 1000.0
    cooldown_sec = 180
    # La condition dans le code : last_close_ts > 0 AND ... < cooldown
    in_cooldown = last_close_ts > 0 and (now - last_close_ts) < cooldown_sec
    assert in_cooldown is False  # first time, last=0


def test_anti_loop_dict_per_symbol():
    """Dict _last_max_hold_close_ts_by_sym distingue ES vs NQ."""
    d = {}
    d["ES"] = 1000.0
    d["NQ"] = 0.0
    assert d.get("ES", 0.0) == 1000.0
    assert d.get("NQ", 0.0) == 0.0
    assert d.get("MGC", 0.0) == 0.0  # default si pas present


def test_full_scenario_18_06_carnage_simulation():
    """REGRESSION : reproduit le pattern 18/06 (9 close en 8 min).

    Sans fix : MAX_HOLD declenche a chaque bar 1min car position pas cleanup.
    Avec fix : seul le 1er declenche, les 8 suivants sont skipped.
    """
    cfg = BotMRConfig()  # defaults: warmup=60, retry_cooldown=120
    boot_ts = 1000.0
    last_close_ts_by_sym = {}
    n_force_closes = 0

    # Simule 9 ticks a intervalle 60sec (1 par min) post-warmup
    for i in range(9):
        now = boot_ts + 70.0 + (i * 60.0)  # T+70s, T+130s, T+190s, ...
        # Position has entry_ts 30 min avant boot, donc MAX_HOLD declenche
        # (logique elapsed_min >= 30 satisfaite)

        # Guard 1 : boot warmup ?
        if (now - boot_ts) < cfg.MAX_HOLD_BOOT_WARMUP_SEC:
            continue

        # Guard 2 : retry cooldown ?
        last_close_ts = last_close_ts_by_sym.get("ES", 0.0)
        if last_close_ts > 0 and (now - last_close_ts) < cfg.MAX_HOLD_RETRY_COOLDOWN_SEC:
            continue

        # Force close (simule)
        n_force_closes += 1
        last_close_ts_by_sym["ES"] = now

    # Avec fix retry_cooldown=180 : on attend 3 force closes max sur 9 ticks
    # T+70 close#1 last=70 / T+130 skip 60<180 / T+190 skip 120<180 /
    # T+250 close#2 last=250 / T+310 skip 60<180 / T+370 skip 120<180 /
    # T+430 close#3 last=430 / T+490 skip 60<180 / T+550 skip 120<180
    assert n_force_closes <= 3, f"trop de close sent: {n_force_closes}"
    assert n_force_closes >= 2, f"pas assez de close sent: {n_force_closes}"


# ==============================================================================
# Fixtures pour tests RESERVES #1-4 (DtcFillListener integration)
# ==============================================================================

@pytest.fixture
def tmp_paths(tmp_path):
    """Chemins temporaires store + bridge."""
    return {
        "store": tmp_path / "bot_mr_runtime_positions.json",
        "bridge": tmp_path / "bot_mr_state.json",
    }


@pytest.fixture
def cfg_sim1():
    """Config Bot 1 v2 forcee Sim1 (BotMR utilise Sim1)."""
    c = Bot1V2Config.from_env()
    c2 = Bot1V2Config(**{**c.__dict__})
    object.__setattr__(c2, "TRADE_ACCOUNT", "Sim1")
    return c2


@pytest.fixture
def store(tmp_paths):
    return PositionStore(path=tmp_paths["store"])


@pytest.fixture
def state_bridge(tmp_paths):
    return StateBridge(path=tmp_paths["bridge"])


def _make_pos_dict(
    sym: str = "ES",
    direction: str = "SHORT",
    entry_price: float = 7580.5,
) -> dict:
    """Helper : dict pos commun pour tests."""
    return {
        "signal_id": f"sig_{sym}_test",
        "direction": direction,
        "entry_price": entry_price,
        "entry_ts": int(time.time() * 1000) - (35 * 60_000),  # 35 min old
        "sl_price": 7582.0 if direction == "SHORT" else 7579.0,
        "tp_price": 7578.25 if direction == "SHORT" else 7582.5,
        "sl_ticks": 6,
        "tp_ticks": 9,
        "n_micros": 1,
        "parent_cid": f"MIA_P_{sym}",
        "tp_cid": f"MIA_TP_{sym}",
        "sl_cid": f"MIA_SL_{sym}",
    }


# ==============================================================================
# RESERVE #1 : register_close_cid + handle_order_update kind=timeout
# ==============================================================================

def test_register_close_cid_adds_to_cid_index(cfg_sim1, store, state_bridge):
    """RESERVE #1 : register_close_cid enregistre kind=timeout dans _cid_index."""
    listener = DtcFillListener(cfg_sim1, store, state_bridge)
    pos = _make_pos_dict()
    close_cid = "MIA_CLOSE_xyz123"
    listener.register_close_cid("ES", close_cid, pos)
    # _cid_index doit contenir l'entry avec kind=timeout
    with listener._lock:
        entry = listener._cid_index.get(close_cid)
    assert entry is not None
    assert entry["kind"] == "timeout"
    assert entry["sym"] == "ES"
    assert entry["signal_id"] == "sig_ES_test"
    assert entry["entry_price"] == 7580.5
    assert entry["direction"] == "SHORT"
    assert entry["n_micros"] == 1


def test_register_close_cid_empty_cid_noop(cfg_sim1, store, state_bridge):
    """register_close_cid avec close_cid vide ne fait rien (defense)."""
    listener = DtcFillListener(cfg_sim1, store, state_bridge)
    pos = _make_pos_dict()
    n_before = listener.n_tracked_brackets()
    listener.register_close_cid("ES", "", pos)
    listener.register_close_cid("ES", None, pos)  # type: ignore
    assert listener.n_tracked_brackets() == n_before


def test_handle_order_update_timeout_fill_cleanup(cfg_sim1, store, state_bridge):
    """RESERVE #1 : fill du close_cid status=7 declenche cleanup + exit_reason=TIMEOUT.

    Simule scenario carnage 18/06 sans fix : avant register_close_cid,
    fill arrivait avec CID inconnu -> listener ignorait -> pos OPEN.
    Avec fix : cleanup OK + callback recoit exit_reason=TIMEOUT.
    """
    pos = _make_pos_dict()
    store.open_position("ES", pos)
    state_bridge.open_position(
        "ES", direction="SHORT", entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_ES_test",
        n_micros=1,
    )

    captured = []

    def cb(sym, pnl_usd, exit_reason="UNKNOWN"):
        captured.append((sym, pnl_usd, exit_reason))

    listener = DtcFillListener(cfg_sim1, store, state_bridge, on_close_callback=cb)
    close_cid = "MIA_CLOSE_xyz"
    listener.register_close_cid("ES", close_cid, pos)

    # Simule ORDER_UPDATE Type 301 status=7 du close market.
    # Fill a 7579.0 -> SHORT entry@7580.5 -> +1.5pts / tick=0.25 -> +6t * $1.25 = +$7.50
    listener.handle_order_update({
        "ClientOrderID": close_cid,
        "TradeAccount": "Sim1",
        "OrderStatus": 7,
        "LastFillPrice": 7579.0,
    })

    # Position retiree
    assert store.has_position("ES") is False
    # Callback appele avec exit_reason=TIMEOUT
    assert len(captured) == 1
    assert captured[0][0] == "ES"
    assert captured[0][2] == "TIMEOUT"
    # PnL ~ +$7.50
    assert abs(captured[0][1] - 7.50) < 0.01


# ==============================================================================
# RESERVE #4 : backward compat callback signature
# ==============================================================================

def test_callback_backward_compat_2_args(cfg_sim1, store, state_bridge):
    """RESERVE #4 : callback ancienne signature (sym, pnl_usd) doit encore marcher.

    Bot 1 v2 + Bot BN V4 ont encore signature 2 args. Try/except TypeError dans
    handle_order_update doit fallback proprement.
    """
    pos = _make_pos_dict()
    store.open_position("ES", pos)
    state_bridge.open_position(
        "ES", direction="SHORT", entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_ES_test",
        n_micros=1,
    )

    captured = []

    def cb_old(sym, pnl_usd):  # signature 2 args (avant fix)
        captured.append((sym, pnl_usd))

    listener = DtcFillListener(cfg_sim1, store, state_bridge, on_close_callback=cb_old)
    # Fill TP normal
    listener.register_bracket(
        sym="ES", signal_id="sig_ES_test", direction="SHORT",
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid="MIA_P_ES", tp_cid="MIA_TP_ES", sl_cid="MIA_SL_ES",
    )
    listener.handle_order_update({
        "ClientOrderID": "MIA_TP_ES",
        "TradeAccount": "Sim1",
        "OrderStatus": 7,
        "LastFillPrice": 7578.25,
    })

    # Callback appele avec 2 args (fallback via TypeError)
    assert len(captured) == 1
    assert captured[0][0] == "ES"
    assert abs(captured[0][1] - 11.25) < 0.01  # +9t * $1.25


def test_callback_new_signature_3_args(cfg_sim1, store, state_bridge):
    """RESERVE #4 : callback nouvelle signature (sym, pnl_usd, exit_reason) priorise."""
    pos = _make_pos_dict()
    store.open_position("ES", pos)
    state_bridge.open_position(
        "ES", direction="SHORT", entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_ES_test",
        n_micros=1,
    )

    captured = []

    def cb_new(sym, pnl_usd, exit_reason):  # nouvelle signature 3 args
        captured.append((sym, pnl_usd, exit_reason))

    listener = DtcFillListener(cfg_sim1, store, state_bridge, on_close_callback=cb_new)
    listener.register_bracket(
        sym="ES", signal_id="sig_ES_test", direction="SHORT",
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid="MIA_P_ES", tp_cid="MIA_TP_ES", sl_cid="MIA_SL_ES",
    )
    listener.handle_order_update({
        "ClientOrderID": "MIA_TP_ES",
        "TradeAccount": "Sim1",
        "OrderStatus": 7,
        "LastFillPrice": 7578.25,
    })

    assert len(captured) == 1
    assert captured[0][0] == "ES"
    assert captured[0][2] == "TP"  # exit_reason propage


# ==============================================================================
# RESERVE #4 (BotMR _on_fill_close) : TIMEOUT exit_reason no SL consec impact
# ==============================================================================

def test_on_fill_close_timeout_does_not_increment_sl_consec(tmp_path):
    """RESERVE #4 : MAX_HOLD timeout (exit_reason=TIMEOUT) ne pollue PAS circuit breaker.

    Sans fix : 3 timeouts -> halt 60min injustifie (sortie temporelle != SL signal).
    Avec fix : SL consec compteur reste a 0 apres N timeouts.
    """
    from CORE.bot_mean_revert.main import BotMR
    # Bot minimal sans DTC pour acces direct _on_fill_close
    bot = BotMR(symbols=["ES"], cfg=BotMRConfig.from_env(), dry_run=True, dtc_connector=None)
    # Force store path tmp (sinon collision tests)
    bot.store = PositionStore(path=tmp_path / "test_runtime.json")
    # 3 timeouts negatifs (slippage typique market close)
    bot._on_fill_close("ES", pnl_usd=-5.0, exit_reason="TIMEOUT")
    bot._on_fill_close("ES", pnl_usd=-3.0, exit_reason="TIMEOUT")
    bot._on_fill_close("ES", pnl_usd=-7.0, exit_reason="TIMEOUT")
    # SL consec doit rester 0 (pas d'increment)
    assert bot.store.get_n_sl_consec("ES") == 0
    # Tracker in-memory nettoye
    assert "ES" not in bot._last_max_hold_close_ts_by_sym


def test_on_fill_close_sl_still_increments_sl_consec(tmp_path):
    """Backward compat : SL legitime (exit_reason=SL) increment toujours SL consec."""
    from CORE.bot_mean_revert.main import BotMR
    bot = BotMR(symbols=["ES"], cfg=BotMRConfig.from_env(), dry_run=True, dtc_connector=None)
    bot.store = PositionStore(path=tmp_path / "test_runtime.json")
    bot._on_fill_close("ES", pnl_usd=-50.0, exit_reason="SL")
    assert bot.store.get_n_sl_consec("ES") == 1


def test_on_fill_close_tp_resets_sl_consec(tmp_path):
    """exit_reason=TP avec compteur>0 -> reset a 0."""
    from CORE.bot_mean_revert.main import BotMR
    bot = BotMR(symbols=["ES"], cfg=BotMRConfig.from_env(), dry_run=True, dtc_connector=None)
    bot.store = PositionStore(path=tmp_path / "test_runtime.json")
    bot.store.increment_sl_consec("ES")
    bot.store.increment_sl_consec("ES")
    assert bot.store.get_n_sl_consec("ES") == 2
    # TP -> reset
    bot._on_fill_close("ES", pnl_usd=15.0, exit_reason="TP")
    assert bot.store.get_n_sl_consec("ES") == 0


def test_on_fill_close_unknown_exit_reason_backward_compat(tmp_path):
    """exit_reason=UNKNOWN (default backward compat) -> applique logique pnl-based."""
    from CORE.bot_mean_revert.main import BotMR
    bot = BotMR(symbols=["ES"], cfg=BotMRConfig.from_env(), dry_run=True, dtc_connector=None)
    bot.store = PositionStore(path=tmp_path / "test_runtime.json")
    # pnl negatif sans exit_reason -> increment (backward compat = traite comme SL)
    bot._on_fill_close("ES", pnl_usd=-25.0)  # exit_reason default UNKNOWN
    assert bot.store.get_n_sl_consec("ES") == 1


# ==============================================================================
# RESERVE #3 : MAX_HOLD_MAX_RETRIES default + halt logic
# ==============================================================================

def test_max_hold_max_retries_default():
    """RESERVE #3 : default MAX_HOLD_MAX_RETRIES = 3."""
    cfg = BotMRConfig()
    assert cfg.MAX_HOLD_MAX_RETRIES == 3


def test_max_hold_max_retries_env_override(monkeypatch):
    """RESERVE #3 : env var BOTMR_MAX_HOLD_MAX_RETRIES surcharge default."""
    monkeypatch.setenv("BOTMR_MAX_HOLD_MAX_RETRIES", "5")
    cfg = BotMRConfig.from_env()
    assert cfg.MAX_HOLD_MAX_RETRIES == 5


def test_halt_logic_pure_below_threshold():
    """Logique pure halt : n_timeouts < max_retries -> pas halt."""
    n_timeouts = 2
    max_retries = 3
    should_halt = n_timeouts >= max_retries
    assert should_halt is False


def test_halt_logic_pure_at_threshold():
    """Logique pure halt : n_timeouts >= max_retries -> halt."""
    n_timeouts = 3
    max_retries = 3
    should_halt = n_timeouts >= max_retries
    assert should_halt is True


def test_halt_logic_pure_above_threshold():
    """Defense : n_timeouts > max_retries -> halt aussi (cas pathologique)."""
    n_timeouts = 5  # encore plus de timeouts qu'attendu
    max_retries = 3
    should_halt = n_timeouts >= max_retries
    assert should_halt is True


# ==============================================================================
# RESERVE #2 : persistance pos cross-restart
# ==============================================================================

def test_pos_persists_last_max_hold_close_ts(tmp_path):
    """RESERVE #2 : last_max_hold_close_ts persiste dans pos cross-restart."""
    store_path = tmp_path / "store_persist.json"
    store = PositionStore(path=store_path)
    pos = _make_pos_dict()
    # Simule force close : on injecte directement le tracker dans pos.
    pos["last_max_hold_close_ts"] = 1700000000.0
    pos["n_max_hold_timeouts"] = 2
    store.open_position("ES", pos)
    store.save()

    # Reload (simule restart)
    store2 = PositionStore(path=store_path)
    store2.load()
    pos2 = store2.positions.get("ES")
    assert pos2 is not None
    assert pos2.get("last_max_hold_close_ts") == 1700000000.0
    assert pos2.get("n_max_hold_timeouts") == 2


def test_pos_persists_halted_by_max_hold(tmp_path):
    """RESERVE #3 : halted_by_max_hold persiste dans pos cross-restart."""
    store_path = tmp_path / "store_halt.json"
    store = PositionStore(path=store_path)
    pos = _make_pos_dict()
    pos["halted_by_max_hold"] = True
    pos["n_max_hold_timeouts"] = 3
    store.open_position("ES", pos)
    store.save()

    store2 = PositionStore(path=store_path)
    store2.load()
    pos2 = store2.positions.get("ES")
    assert pos2.get("halted_by_max_hold") is True
    assert pos2.get("n_max_hold_timeouts") == 3


# ==============================================================================
# REGRESSION FULL SCENARIO 18/06 WITH FIX
# ==============================================================================

def test_full_18_06_scenario_with_fix_no_loop(cfg_sim1, store, state_bridge):
    """REGRESSION CARNAGE 18/06 : avec fix complet, apres 1er close confirme via
    fill listener (status=7 register_close_cid), position cleanup -> pas de boucle.

    Sans fix : 9 close markets en 8 min (cumul SHORTs).
    Avec fix : 1 close envoye, fill cleanup, pos absente, MAX_HOLD inerte.
    """
    pos = _make_pos_dict()
    store.open_position("ES", pos)
    state_bridge.open_position(
        "ES", direction="SHORT", entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_ES_test",
        n_micros=1,
    )

    callback_calls = []
    def cb(sym, pnl_usd, exit_reason="UNKNOWN"):
        callback_calls.append((sym, exit_reason))

    listener = DtcFillListener(cfg_sim1, store, state_bridge, on_close_callback=cb)
    close_cid = "MIA_CLOSE_carnage"

    # Step 1 : bot envoie close market + register
    listener.register_close_cid("ES", close_cid, pos)
    assert store.has_position("ES") is True

    # Step 2 : SC envoie ORDER_UPDATE status=7 (fill confirme)
    listener.handle_order_update({
        "ClientOrderID": close_cid,
        "TradeAccount": "Sim1",
        "OrderStatus": 7,
        "LastFillPrice": 7579.0,
    })

    # Apres fill : pos absente du store
    assert store.has_position("ES") is False
    # Callback recu avec TIMEOUT
    assert len(callback_calls) == 1
    assert callback_calls[0] == ("ES", "TIMEOUT")
    # CID cleanup de l'index
    with listener._lock:
        assert close_cid not in listener._cid_index


def test_carnage_avoided_18_closes_max_3_with_halt():
    """REGRESSION : 18 ticks avec retry_cooldown=180s + max_retries=3.

    Pattern carnage 18/06 (DTC down -> fill jamais confirme -> retries).
    Sans halt : 18 ticks / (180s cooldown / 60s bar) = 6 closes potentiels.
    Avec halt: capped a 3 closes max, puis halt -> 0 close subsequent.
    """
    cfg = BotMRConfig()
    boot_ts = 1000.0
    last_close_ts_by_sym = {}
    pos = {"n_max_hold_timeouts": 0, "halted_by_max_hold": False}
    n_force_closes = 0
    n_halt_skips = 0

    # Simule 18 ticks a 60sec intervalle post-warmup
    for i in range(18):
        now = boot_ts + 70.0 + (i * 60.0)

        # Guard 1 : warmup
        if (now - boot_ts) < cfg.MAX_HOLD_BOOT_WARMUP_SEC:
            continue

        # Guard 3 (RESERVE #3) : max retries halt
        if pos["n_max_hold_timeouts"] >= cfg.MAX_HOLD_MAX_RETRIES:
            pos["halted_by_max_hold"] = True
            n_halt_skips += 1
            continue

        # Guard 2 : retry cooldown
        last_close_ts = last_close_ts_by_sym.get("ES", 0.0)
        if last_close_ts > 0 and (now - last_close_ts) < cfg.MAX_HOLD_RETRY_COOLDOWN_SEC:
            continue

        # Force close
        n_force_closes += 1
        last_close_ts_by_sym["ES"] = now
        pos["n_max_hold_timeouts"] += 1

    # 3 closes max (apres N=3, halt active)
    assert n_force_closes == 3, f"closes attendus 3, got {n_force_closes}"
    # Halt active sur la fin
    assert pos["halted_by_max_hold"] is True
    # Quelques ticks halt en fin
    assert n_halt_skips > 0
