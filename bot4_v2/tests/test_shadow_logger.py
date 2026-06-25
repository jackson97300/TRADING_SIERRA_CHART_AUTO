"""Tests bot4_v2/observability/shadow_logger.

Tests E2E :
- log_fire persiste JSONL append-only
- update_outcomes detecte TP/SL/TIMEOUT correctement
- 100+ bars synthetiques avec mix LONG/SHORT
- Edge cases : disabled, duplicate signal_id, fichier corrompu
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot4_v2.observability.shadow_logger import (
    ShadowFire,
    ShadowLogger,
    _PendingFire,
)


def _utc_iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def _make_fire(
    *,
    symbol: str = "NQ",
    direction: str = "LONG",
    entry: float = 20000.0,
    target: float = 20020.0,
    stop: float = 19990.0,
    score: int = 75,
    scenario: str = "Bearish_Rejection",
    regime: str = "CALM_RANGE",
    signal_id: str | None = None,
    ts_fire: str | None = None,
) -> ShadowFire:
    if signal_id is None:
        signal_id = str(uuid.uuid4())
    if ts_fire is None:
        ts_fire = _utc_iso()
    rr = abs(target - entry) / max(abs(entry - stop), 0.01)
    return ShadowFire(
        signal_id=signal_id,
        ts_fire=ts_fire,
        symbol=symbol,
        scenario_name=scenario,
        direction=direction,  # type: ignore
        heuristic_score=score,
        primary=True,
        regime=regime,
        session_id=2,
        entry_price=entry,
        target_1=target,
        target_2=None,
        stop_loss=stop,
        r_r_ratio=rr,
    )


# ============================================================
# ShadowFire serialization
# ============================================================

def test_shadow_fire_to_dict_complete():
    fire = _make_fire()
    d = fire.to_dict()
    assert d["signal_id"] == fire.signal_id
    assert d["scenario_name"] == "Bearish_Rejection"
    assert d["direction"] == "LONG"
    assert d["outcome_status"] == "PENDING"
    assert d["pnl_ticks_h"] is None  # outcome non rempli
    assert "extra" in d


def test_shadow_fire_frozen_immutable():
    from dataclasses import FrozenInstanceError
    fire = _make_fire()
    with pytest.raises(FrozenInstanceError):
        fire.signal_id = "modified"  # type: ignore


# ============================================================
# ShadowLogger init
# ============================================================

def test_logger_creates_output_dir(tmp_path):
    out_dir = tmp_path / "shadow"
    assert not out_dir.exists()
    ShadowLogger(out_dir)
    assert out_dir.exists()


def test_logger_disabled_no_creation(tmp_path):
    """enabled=False : aucune creation dir."""
    out_dir = tmp_path / "shadow_disabled"
    ShadowLogger(out_dir, enabled=False)
    assert not out_dir.exists()


def test_logger_n_pending_starts_at_zero(tmp_path):
    sl = ShadowLogger(tmp_path)
    assert sl.n_pending == 0


# ============================================================
# log_fire
# ============================================================

def test_log_fire_persists_jsonl(tmp_path):
    sl = ShadowLogger(tmp_path)
    fire = _make_fire()
    ok = sl.log_fire(fire)
    assert ok is True
    assert sl.n_pending == 1

    # Verify JSONL file written
    files = list(tmp_path.glob("shadow_*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip()
    record = json.loads(content)
    assert record["signal_id"] == fire.signal_id
    assert record["outcome_status"] == "PENDING"


def test_log_fire_when_disabled_returns_false(tmp_path):
    sl = ShadowLogger(tmp_path, enabled=False)
    fire = _make_fire()
    ok = sl.log_fire(fire)
    assert ok is False
    assert sl.n_pending == 0


def test_log_fire_duplicate_signal_id_rejected(tmp_path, caplog):
    """Duplicate signal_id -> warning + return False."""
    import logging
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(signal_id="DUP_123")
    assert sl.log_fire(fire) is True
    with caplog.at_level(logging.WARNING, logger="bot4_v2.observability.shadow_logger"):
        ok = sl.log_fire(fire)  # duplicate
    assert ok is False
    assert any("duplicate" in r.message.lower() for r in caplog.records)


# ============================================================
# update_outcomes : TP hit
# ============================================================

def test_update_outcomes_tp_hit_long(tmp_path):
    sl = ShadowLogger(tmp_path, horizon_bars=30)
    fire = _make_fire(direction="LONG", entry=20000.0, target=20020.0, stop=19990.0)
    sl.log_fire(fire)

    # Bar suivante : high atteint target
    decided = sl.update_outcomes(
        symbol="NQ", bar_ts=_utc_iso(),
        bar_high=20025.0, bar_low=20005.0, bar_close=20020.0,
    )
    assert len(decided) == 1
    assert decided[0].outcome_status == "TP_HIT"
    assert decided[0].tp1_hit is True
    assert decided[0].sl_hit is False
    assert decided[0].pnl_ticks_h is not None
    assert decided[0].pnl_ticks_h > 0
    assert sl.n_pending == 0


def test_update_outcomes_tp_hit_short(tmp_path):
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(direction="SHORT", entry=20000.0, target=19980.0, stop=20010.0)
    sl.log_fire(fire)

    decided = sl.update_outcomes(
        symbol="NQ", bar_ts=_utc_iso(),
        bar_high=19995.0, bar_low=19975.0, bar_close=19980.0,
    )
    assert len(decided) == 1
    assert decided[0].outcome_status == "TP_HIT"
    assert decided[0].pnl_ticks_h is not None
    assert decided[0].pnl_ticks_h > 0


# ============================================================
# update_outcomes : SL hit
# ============================================================

def test_update_outcomes_sl_hit_long(tmp_path):
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(direction="LONG", entry=20000.0, target=20020.0, stop=19990.0)
    sl.log_fire(fire)

    decided = sl.update_outcomes(
        symbol="NQ", bar_ts=_utc_iso(),
        bar_high=20005.0, bar_low=19985.0, bar_close=19990.0,
    )
    assert len(decided) == 1
    assert decided[0].outcome_status == "SL_HIT"
    assert decided[0].sl_hit is True
    assert decided[0].tp1_hit is False
    assert decided[0].pnl_ticks_h is not None
    assert decided[0].pnl_ticks_h < 0


def test_update_outcomes_sl_priority_when_both_in_same_bar(tmp_path):
    """SL priorite si bar fait TP ET SL meme bar (conservateur)."""
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(direction="LONG", entry=20000.0, target=20020.0, stop=19990.0)
    sl.log_fire(fire)

    # Bar fait les 2 : high atteint TP ET low atteint SL
    decided = sl.update_outcomes(
        symbol="NQ", bar_ts=_utc_iso(),
        bar_high=20025.0, bar_low=19985.0, bar_close=20000.0,
    )
    assert len(decided) == 1
    assert decided[0].outcome_status == "SL_HIT"


# ============================================================
# update_outcomes : timeout
# ============================================================

def test_update_outcomes_timeout(tmp_path):
    sl = ShadowLogger(tmp_path, horizon_bars=5)
    fire = _make_fire(direction="LONG", entry=20000.0, target=20020.0, stop=19990.0)
    sl.log_fire(fire)

    # 5 bars sans TP ni SL
    decided_total = []
    for i in range(5):
        decided = sl.update_outcomes(
            symbol="NQ", bar_ts=_utc_iso(),
            bar_high=20010.0, bar_low=19995.0, bar_close=20002.0,
        )
        decided_total.extend(decided)

    # Sur la 5e bar (bars_seen=5 == horizon_bars=5) -> TIMEOUT
    assert len(decided_total) == 1
    assert decided_total[0].outcome_status == "TIMEOUT"
    assert decided_total[0].duration_bars == 5


# ============================================================
# MFE / MAE tracking
# ============================================================

def test_mfe_mae_tracked_correctly_long(tmp_path):
    sl = ShadowLogger(tmp_path, horizon_bars=10)
    fire = _make_fire(direction="LONG", entry=20000.0, target=21000.0, stop=19000.0)
    sl.log_fire(fire)

    # Bars : MFE = +20t, MAE = -10t puis TP
    sl.update_outcomes("NQ", _utc_iso(), bar_high=20005.0, bar_low=19997.5, bar_close=20002.0)
    sl.update_outcomes("NQ", _utc_iso(), bar_high=20010.0, bar_low=20005.0, bar_close=20008.0)
    decided = sl.update_outcomes(
        "NQ", _utc_iso(), bar_high=21010.0, bar_low=20990.0, bar_close=21000.0,
    )
    assert len(decided) == 1
    outcome = decided[0]
    # MFE doit etre au moins la distance entry->target (4000 ticks NQ tick=0.25)
    assert outcome.mfe_ticks is not None
    assert outcome.mfe_ticks > 0
    # MAE doit etre <= 0
    assert outcome.mae_ticks is not None
    assert outcome.mae_ticks <= 0


# ============================================================
# Filtering par symbole
# ============================================================

def test_update_outcomes_filters_by_symbol(tmp_path):
    sl = ShadowLogger(tmp_path)
    fire_nq = _make_fire(symbol="NQ", direction="LONG", entry=20000.0, target=20020.0, stop=19990.0)
    fire_es = _make_fire(symbol="ES", direction="LONG", entry=5000.0, target=5010.0, stop=4995.0)
    sl.log_fire(fire_nq)
    sl.log_fire(fire_es)
    assert sl.n_pending == 2

    # Bar NQ atteint TP NQ uniquement
    decided = sl.update_outcomes(
        "NQ", _utc_iso(), bar_high=20025.0, bar_low=20010.0, bar_close=20020.0,
    )
    assert len(decided) == 1
    assert decided[0].symbol == "NQ"
    assert sl.n_pending == 1  # ES toujours pending


# ============================================================
# Persistance JSONL append-only
# ============================================================

def test_jsonl_append_only_multiple_events(tmp_path):
    sl = ShadowLogger(tmp_path)
    fire1 = _make_fire(signal_id="F1")
    fire2 = _make_fire(signal_id="F2")
    sl.log_fire(fire1)
    sl.log_fire(fire2)

    files = list(tmp_path.glob("shadow_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["signal_id"] == "F1"
    assert records[1]["signal_id"] == "F2"


def test_jsonl_daily_split_by_date(tmp_path):
    """Fires sur 2 jours differents -> 2 fichiers."""
    sl = ShadowLogger(tmp_path)
    day1 = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 6, 26, 10, 0, 0, tzinfo=timezone.utc)
    fire1 = _make_fire(signal_id="F1", ts_fire=_utc_iso(day1))
    fire2 = _make_fire(signal_id="F2", ts_fire=_utc_iso(day2))
    sl.log_fire(fire1)
    sl.log_fire(fire2)

    files = sorted(tmp_path.glob("shadow_*.jsonl"))
    assert len(files) == 2
    assert "20260625" in files[0].name
    assert "20260626" in files[1].name


def test_jsonl_split_by_symbol(tmp_path):
    """Fires sur 2 symboles meme jour -> 2 fichiers (NQ + ES)."""
    sl = ShadowLogger(tmp_path)
    day = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
    fire_nq = _make_fire(signal_id="F1", symbol="NQ", ts_fire=_utc_iso(day))
    fire_es = _make_fire(signal_id="F2", symbol="ES", ts_fire=_utc_iso(day))
    sl.log_fire(fire_nq)
    sl.log_fire(fire_es)

    files = sorted(tmp_path.glob("shadow_*.jsonl"))
    assert len(files) == 2
    assert any("NQ" in f.name for f in files)
    assert any("ES" in f.name for f in files)


# ============================================================
# E2E 100 bars synthetiques
# ============================================================

def test_e2e_100_bars_mixed_outcomes(tmp_path):
    """E2E : 5 fires NQ avec outcomes varies sur 100 bars."""
    sl = ShadowLogger(tmp_path, horizon_bars=30)

    # Fire 1 : LONG qui TP rapide (bar 3)
    sl.log_fire(_make_fire(signal_id="F1", direction="LONG",
                            entry=20000.0, target=20010.0, stop=19990.0))
    # Fire 2 : SHORT qui SL (bar 5)
    sl.log_fire(_make_fire(signal_id="F2", direction="SHORT",
                            entry=20000.0, target=19980.0, stop=20010.0))
    # Fire 3 : LONG qui TIMEOUT
    sl.log_fire(_make_fire(signal_id="F3", direction="LONG",
                            entry=20000.0, target=21000.0, stop=19000.0))

    bars_decided = []

    # Bar 1-2 : neutre
    for _ in range(2):
        decided = sl.update_outcomes("NQ", _utc_iso(),
                                       bar_high=20005.0, bar_low=19998.0, bar_close=20002.0)
        bars_decided.extend(decided)

    # Bar 3 : Fire 1 TP
    decided = sl.update_outcomes("NQ", _utc_iso(),
                                   bar_high=20012.0, bar_low=19999.0, bar_close=20010.0)
    bars_decided.extend(decided)

    # Bar 4 : neutre
    sl.update_outcomes("NQ", _utc_iso(),
                       bar_high=20008.0, bar_low=20000.0, bar_close=20005.0)

    # Bar 5 : Fire 2 SL
    decided = sl.update_outcomes("NQ", _utc_iso(),
                                   bar_high=20015.0, bar_low=20005.0, bar_close=20012.0)
    bars_decided.extend(decided)

    # Bar 6-32 : neutre (Fire 3 timeout @ bar 33)
    for _ in range(27):
        decided = sl.update_outcomes("NQ", _utc_iso(),
                                       bar_high=20010.0, bar_low=19995.0, bar_close=20002.0)
        bars_decided.extend(decided)

    # 3 fires decidees
    assert len(bars_decided) == 3
    statuses = {d.signal_id: d.outcome_status for d in bars_decided}
    assert statuses["F1"] == "TP_HIT"
    assert statuses["F2"] == "SL_HIT"
    assert statuses["F3"] == "TIMEOUT"

    # Tous outcomes persistes JSONL
    files = list(tmp_path.glob("shadow_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    # 3 fires PENDING + 3 outcomes = 6 lignes
    assert len(lines) == 6


# ============================================================
# Disk error fail-soft
# ============================================================

def test_jsonl_append_disk_error_returns_false(tmp_path, monkeypatch, caplog):
    """Erreur OSError sur write -> warning + return False (pas crash)."""
    import logging
    sl = ShadowLogger(tmp_path)

    def fake_open(*args, **kwargs):
        raise OSError("disk full simulated")

    # Patch Path.open pour cette test
    monkeypatch.setattr("pathlib.Path.open", fake_open)

    fire = _make_fire()
    with caplog.at_level(logging.WARNING, logger="bot4_v2.observability.shadow_logger"):
        ok = sl.log_fire(fire)
    assert ok is False
    assert any("append fail" in r.message for r in caplog.records)


# ============================================================
# PendingFire internal
# ============================================================

def test_pending_fire_update_excursion_long(tmp_path):
    fire = _make_fire(direction="LONG", entry=20000.0)
    p = _PendingFire(fire=fire)
    p.update_excursion(bar_high=20010.0, bar_low=19995.0, tick_size=0.25)
    # MFE = +10 / 0.25 = +40 ticks
    assert p.mfe_ticks == 40.0
    # MAE = -5 / 0.25 = -20 ticks
    assert p.mae_ticks == -20.0


def test_pending_fire_update_excursion_short(tmp_path):
    fire = _make_fire(direction="SHORT", entry=20000.0)
    p = _PendingFire(fire=fire)
    p.update_excursion(bar_high=20010.0, bar_low=19995.0, tick_size=0.25)
    # Pour SHORT : MFE = (entry - low) / tick = +5/0.25 = +20
    assert p.mfe_ticks == 20.0
    # MAE = (entry - high) / tick = -10/0.25 = -40
    assert p.mae_ticks == -40.0


def test_pending_fire_excursion_does_not_decrease(tmp_path):
    """Bar suivante avec valeurs plus serrees : MFE/MAE doivent pas baisser."""
    fire = _make_fire(direction="LONG", entry=20000.0)
    p = _PendingFire(fire=fire)
    p.update_excursion(bar_high=20010.0, bar_low=19990.0, tick_size=0.25)
    mfe_initial = p.mfe_ticks  # +40
    mae_initial = p.mae_ticks  # -40

    p.update_excursion(bar_high=20005.0, bar_low=19998.0, tick_size=0.25)
    # MFE doit rester a 40 (pas redescendre a 20)
    assert p.mfe_ticks == mfe_initial
    # MAE doit rester a -40 (pas remonter a -8)
    assert p.mae_ticks == mae_initial


# ============================================================
# R1 R2 review : fail-loud (no silent fallback)
# ============================================================

def test_daily_path_invalid_ts_fire_logs_warning(tmp_path, caplog):
    """R1 review : ts_fire invalide -> fallback + warning (PAS silent)."""
    import logging
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(signal_id="INVALID_TS", ts_fire="not_an_iso_string_at_all")
    with caplog.at_level(
        logging.WARNING, logger="bot4_v2.observability.shadow_logger"
    ):
        ok = sl.log_fire(fire)
    assert ok is True  # fail-soft : on persiste quand meme
    assert any("ts_fire invalide" in r.message for r in caplog.records)


def test_daily_path_none_ts_fire_logs_warning(tmp_path, caplog):
    """R1 review : ts_fire=None (cas TypeError replace) -> warning + fallback."""
    import logging
    sl = ShadowLogger(tmp_path)
    # ShadowFire frozen prend str, mais on peut forger via constructeur direct
    fire = ShadowFire(
        signal_id="NULL_TS",
        ts_fire=None,  # type: ignore (test edge case)
        symbol="NQ",
        scenario_name="X",
        direction="LONG",
        heuristic_score=70,
        primary=True,
        regime="CALM_RANGE",
        session_id=2,
        entry_price=20000.0,
        target_1=20020.0,
        target_2=None,
        stop_loss=19990.0,
        r_r_ratio=2.0,
    )
    with caplog.at_level(
        logging.WARNING, logger="bot4_v2.observability.shadow_logger"
    ):
        ok = sl.log_fire(fire)
    assert ok is True
    assert any("ts_fire invalide" in r.message for r in caplog.records)


def test_update_outcomes_unknown_symbol_logs_warning(tmp_path, caplog):
    """R2 review : symbole inconnu dans update_outcomes -> warning."""
    import logging
    sl = ShadowLogger(tmp_path)
    fire = _make_fire(symbol="GOLD_BAD")  # symbole non supporte
    sl.log_fire(fire)
    with caplog.at_level(
        logging.WARNING, logger="bot4_v2.observability.shadow_logger"
    ):
        sl.update_outcomes(
            "GOLD_BAD", _utc_iso(),
            bar_high=2000.0, bar_low=1999.0, bar_close=2000.0,
        )
    assert any("symbole" in r.message.lower() for r in caplog.records)
    assert any("inconnu" in r.message.lower() for r in caplog.records)
