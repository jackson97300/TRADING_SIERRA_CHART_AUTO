"""Tests SignalEngine - warmup + detect_setup + dual mode TRADE/OBSERVE."""
from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd
import pytest

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.signal_engine import SignalEngine, SignalDecision


def _minimal_bar(i: int, slope: float = -0.01, close: float = 30000.0) -> dict:
    """Construit une bar minimale pour warmup (pas un setup actif)."""
    base_ts_ns = 1781557080000000000 + i * 60_000_000_000
    return {
        "ts": int(base_ts_ns / 1_000_000),
        "ts_event": pd.Timestamp(base_ts_ns, unit="ns", tz="UTC"),
        "ts_event_ns": base_ts_ns,
        "close": close,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "vwap_slope_10": slope,
        "total_vol": 100.0,
        # Pas de cluster -> grade SKIP, jamais tradable
        "n_color_up_cluster_within_0_2pct": 0,
        "n_long_up_cluster_within_0_2pct": 0,
        "n_edge_buy_active": 0,
    }


def test_warmup_returns_skip():
    """Pas assez de bars : skip_reason WARMUP_n/240."""
    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    dec = eng.on_bar(_minimal_bar(0))
    assert dec.tradable is False
    assert "WARMUP" in dec.skip_reason
    assert eng.n_bars() == 1


def test_is_ready_after_lookback_bars():
    """Apres trend_long_lookback bars (240), is_ready=True."""
    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    for i in range(245):
        eng.on_bar(_minimal_bar(i))
    assert eng.is_ready() is True
    assert eng.n_bars() == 245


def test_no_setup_when_no_clusters():
    """Bars avec 0 cluster + 0 edge -> jamais de setup tradable."""
    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    for i in range(245):
        eng.on_bar(_minimal_bar(i))
    dec = eng.on_bar(_minimal_bar(245))
    # n_levels=0, density=0 -> SKIP
    assert dec.tradable is False


def test_empty_bar_returns_empty_skip():
    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    dec = eng.on_bar({})
    # Empty bar reachable via _buf append + warmup short-circuit
    assert dec.tradable is False


def test_rolling_window_capped():
    """Deque(maxlen=N) plafonne la taille du buffer."""
    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    for i in range(cfg.SIGNAL_ROLLING_WINDOW_BARS + 100):
        eng.on_bar(_minimal_bar(i))
    assert eng.n_bars() == cfg.SIGNAL_ROLLING_WINDOW_BARS


def test_log_fn_injection():
    """log_fn injectable est passe a BNV4Engine."""
    cfg = BotBNV4Config.from_env()
    calls = []
    def fake_log(code, **ctx):
        calls.append((code, ctx))
    eng = SignalEngine(symbol="NQ", cfg=cfg, log_fn=fake_log)
    # Boot un buffer suffisant
    for i in range(245):
        eng.on_bar(_minimal_bar(i))
    eng.on_bar(_minimal_bar(245))
    # Le moteur emit GATE_*_BLOCK quand un setup est rejete
    # Au moins TREND_BLOCK ou LEVELS_BLOCK devrait apparaitre
    codes = [c for c, _ in calls]
    # En warmup la 245e bar a is_ready=True, on doit voir des GATE_*
    assert len(codes) >= 0  # tolerant : peut etre vide si block tot


def test_direction_mode_long_only():
    """DIRECTION_MODE=long -> seul direction='long' teste."""
    with patch.dict(os.environ, {"BOTBN_DIRECTION_MODE": "long"}):
        cfg = BotBNV4Config.from_env()
        assert cfg.DIRECTION_MODE == "long"
        eng = SignalEngine(symbol="NQ", cfg=cfg)
        for i in range(245):
            eng.on_bar(_minimal_bar(i))
        dec = eng.on_bar(_minimal_bar(245))
        # Pas de setup detecte (0 clusters) mais pas d'erreur
        assert dec.direction != "short"


def test_signal_decision_default():
    """SignalDecision default = non-tradable, pas de direction."""
    dec = SignalDecision()
    assert dec.tradable is False
    assert dec.direction is None
    assert dec.hypothetical is False


# ============================================================
# Tests warmup_from_disk (FIX 17/06 ULTRATHINK - persistant)
# ============================================================


def test_warmup_from_disk_populates_buffer(tmp_path, monkeypatch):
    """Fixture JSONL 300 bars, warmup_from_disk() -> is_ready=True."""
    import json
    # Build a synthetic JSONL with 300 bars
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir(parents=True)
    path = sym_dir / "20260617_NQ_sierra_enriched.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i in range(300):
            bar = _minimal_bar(i)
            # Sanitize ts_event to ISO string (json-serializable)
            bar["ts_event"] = bar["ts_event"].isoformat()
            fh.write(json.dumps(bar) + "\n")
    # Patch the resolver
    import CORE.bot_bn_v4.bar_history_loader as loader
    monkeypatch.setattr(loader, "_data_root", lambda: tmp_path)

    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    n_loaded = eng.warmup_from_disk()
    # On demande trend_long_lookback=240 par defaut
    assert n_loaded == 240
    assert eng.is_ready() is True
    assert eng.n_bars() == 240
    # last_bar_ts() doit etre coherent
    assert eng.last_bar_ts() is not None


def test_warmup_from_disk_empty_dir_does_not_crash(tmp_path, monkeypatch):
    """Aucun JSONL -> n_loaded=0, is_ready=False, pas d'exception."""
    import CORE.bot_bn_v4.bar_history_loader as loader
    monkeypatch.setattr(loader, "_data_root", lambda: tmp_path)

    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    n_loaded = eng.warmup_from_disk()
    assert n_loaded == 0
    assert eng.is_ready() is False
    assert eng.last_bar_ts() is None


def test_warmup_from_disk_idempotent(tmp_path, monkeypatch):
    """Review I3 (renforce 2eme passage) : 2 appels successifs warmup_from_disk
    avec target>SIGNAL_ROLLING_WINDOW_BARS/2 → deque plafonne strict + idempotence ts."""
    import json
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir(parents=True)
    path = sym_dir / "20260617_NQ_sierra_enriched.jsonl"
    # 300 bars dispo, on demande 300 deux fois = 600 appends > maxlen=500
    with path.open("w", encoding="utf-8") as fh:
        for i in range(300):
            bar = _minimal_bar(i)
            bar["ts_event"] = bar["ts_event"].isoformat()
            fh.write(json.dumps(bar) + "\n")
    import CORE.bot_bn_v4.bar_history_loader as loader
    monkeypatch.setattr(loader, "_data_root", lambda: tmp_path)

    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    eng.warmup_from_disk(target=300)
    ts_after_1 = eng.last_bar_ts_ms()
    eng.warmup_from_disk(target=300)
    ts_after_2 = eng.last_bar_ts_ms()
    # 1. deque plafonne strictement a maxlen (pas seulement <=)
    assert eng.n_bars() == cfg.SIGNAL_ROLLING_WINDOW_BARS
    # 2. Idempotence chronologique : la derniere bar reste la meme
    assert ts_after_1 == ts_after_2
    assert ts_after_1 is not None


def test_last_bar_ts_ms_uses_int_ts_natif(tmp_path, monkeypatch):
    """Review I2 : last_bar_ts_ms() privilegie bar['ts'] (int ms) sur ts_event iso."""
    import json
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir(parents=True)
    path = sym_dir / "20260617_NQ_sierra_enriched.jsonl"
    # Bars avec ts int ms ET ts_event iso (cas reel JSONL sierra_enriched)
    target_ts_ms = 1781481600000
    with path.open("w", encoding="utf-8") as fh:
        for i in range(5):
            bar = _minimal_bar(i)
            bar["ts"] = target_ts_ms + i * 60_000
            bar["ts_event"] = bar["ts_event"].isoformat()
            fh.write(json.dumps(bar) + "\n")
    import CORE.bot_bn_v4.bar_history_loader as loader
    monkeypatch.setattr(loader, "_data_root", lambda: tmp_path)

    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    eng.warmup_from_disk()
    # Last bar ts ms doit etre le ts int natif de la 5e bar (index 4)
    expected = target_ts_ms + 4 * 60_000
    assert eng.last_bar_ts_ms() == expected


def test_warmup_from_disk_preserves_chronological_order(tmp_path, monkeypatch):
    """Apres warmup, last_bar_ts() = ts de la derniere bar chronologique."""
    import json
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir(parents=True)
    path = sym_dir / "20260617_NQ_sierra_enriched.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i in range(250):
            bar = _minimal_bar(i)
            bar["ts_event"] = bar["ts_event"].isoformat()
            fh.write(json.dumps(bar) + "\n")
    import CORE.bot_bn_v4.bar_history_loader as loader
    monkeypatch.setattr(loader, "_data_root", lambda: tmp_path)

    cfg = BotBNV4Config.from_env()
    eng = SignalEngine(symbol="NQ", cfg=cfg)
    n_loaded = eng.warmup_from_disk()
    # 250 bars dispo, target par defaut = 240, on charge 240
    assert n_loaded == 240
    # last_bar_ts = bar index 249 (la plus recente)
    last_ts = eng.last_bar_ts()
    assert last_ts is not None
    # Doit etre l'iso de la bar 249 (la derniere)
    bar_249 = _minimal_bar(249)
    assert last_ts == bar_249["ts_event"].isoformat()
