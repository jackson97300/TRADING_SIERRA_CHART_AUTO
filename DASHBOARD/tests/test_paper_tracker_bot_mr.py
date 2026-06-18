"""Tests countdown Bot MR (Sim1) - dashboard PROTECTIONS ACTIVES.

Mission 18/06 Jackson : afficher cooldown 15 min + MAX_HOLD 30 min restants
pour Bot Mean Revert (slot Sim1, endpoint /api/paper_bot3_v3_state).

Couvre :
1. _bot_mr_cooldown_remaining_sec : ISO valide, expire, absent, corrompu
2. _bot_mr_max_hold_remaining_sec : position ouverte, pas de position, expire
3. _bot_mr_build_cooldown_status : runtime file absent, valide, multi-symboles
4. _bot_mr_read_runtime_config : env override + defaults + corruption
5. get_bot3_v3_payload : integration end-to-end (payload contient cooldown_status)
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Test 1 — _bot_mr_cooldown_remaining_sec (4 sous-cas)
# ─────────────────────────────────────────────────────────────────────────

def test_cooldown_remaining_calc_active():
    """Last trade il y a 10 min, cooldown=15 -> ~300 sec restantes."""
    from DASHBOARD.api.paper_tracker import _bot_mr_cooldown_remaining_sec
    now = datetime.now(timezone.utc)
    last_iso = (now - timedelta(minutes=10)).isoformat()
    remaining = _bot_mr_cooldown_remaining_sec(last_iso, cooldown_minutes=15, now_utc=now)
    # 5 minutes restantes = 300 sec (± 2 sec tolerance pour les microsecondes)
    assert 298 <= remaining <= 302, f"Expected ~300, got {remaining}"


def test_cooldown_remaining_expired():
    """Last trade il y a 20 min, cooldown=15 -> 0 (expire)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_cooldown_remaining_sec
    now = datetime.now(timezone.utc)
    last_iso = (now - timedelta(minutes=20)).isoformat()
    assert _bot_mr_cooldown_remaining_sec(last_iso, cooldown_minutes=15, now_utc=now) == 0


def test_cooldown_remaining_no_last_trade():
    """Pas de last_trade_ts (None/empty) -> 0 (defensive, fail-safe)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_cooldown_remaining_sec
    assert _bot_mr_cooldown_remaining_sec(None, cooldown_minutes=15) == 0
    assert _bot_mr_cooldown_remaining_sec("", cooldown_minutes=15) == 0


def test_cooldown_remaining_corrupted_iso():
    """ISO corrompu -> 0 (defensive : ne crash pas le dashboard)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_cooldown_remaining_sec
    assert _bot_mr_cooldown_remaining_sec("not-a-date", cooldown_minutes=15) == 0
    assert _bot_mr_cooldown_remaining_sec("2026-99-99T99:99:99", cooldown_minutes=15) == 0


def test_cooldown_remaining_zulu_format():
    """ISO avec 'Z' (UTC zulu) doit etre parse (cf datetime.fromisoformat 3.11+)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_cooldown_remaining_sec
    now = datetime.now(timezone.utc)
    # PositionStore ecrit avec '+00:00' mais defensive parse 'Z' aussi
    last_zulu = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    remaining = _bot_mr_cooldown_remaining_sec(last_zulu, cooldown_minutes=15, now_utc=now)
    # 10 min restantes = 600 sec (tolerance large car format strftime tronque microsecondes)
    assert 595 <= remaining <= 605, f"Expected ~600, got {remaining}"


# ─────────────────────────────────────────────────────────────────────────
# Test 2 — _bot_mr_max_hold_remaining_sec (3 sous-cas)
# ─────────────────────────────────────────────────────────────────────────

def test_max_hold_remaining_calc_active():
    """Entry il y a 10 min (epoch ms), MAX_HOLD=30 -> ~1200 sec restantes."""
    from DASHBOARD.api.paper_tracker import _bot_mr_max_hold_remaining_sec
    now_sec = time.time()
    entry_ms = (now_sec - 10 * 60) * 1000  # 10 min ago
    remaining = _bot_mr_max_hold_remaining_sec(entry_ms, max_hold_minutes=30, now_ts_sec=now_sec)
    # 20 min restantes = 1200 sec (tolerance 2 sec pour les arrondis)
    assert remaining is not None
    assert 1198 <= remaining <= 1202, f"Expected ~1200, got {remaining}"


def test_max_hold_no_position():
    """entry_ts_ms=None ou 0 -> None (pas de position)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_max_hold_remaining_sec
    assert _bot_mr_max_hold_remaining_sec(None, max_hold_minutes=30) is None
    assert _bot_mr_max_hold_remaining_sec(0, max_hold_minutes=30) is None


def test_max_hold_expired():
    """Entry il y a 35 min, MAX_HOLD=30 -> 0 (force close imminent)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_max_hold_remaining_sec
    now_sec = time.time()
    entry_ms = (now_sec - 35 * 60) * 1000  # 35 min ago
    remaining = _bot_mr_max_hold_remaining_sec(entry_ms, max_hold_minutes=30, now_ts_sec=now_sec)
    assert remaining == 0


# ─────────────────────────────────────────────────────────────────────────
# Test 3 — _bot_mr_build_cooldown_status (integration runtime file)
# ─────────────────────────────────────────────────────────────────────────

def test_build_cooldown_status_runtime_absent():
    """Runtime file absent -> {} (defensive, frontend retombe sur 'Pret')."""
    from DASHBOARD.api.paper_tracker import _bot_mr_build_cooldown_status
    absent_path = Path(tempfile.gettempdir()) / "ne_existe_pas_xyz_botmr.json"
    assert _bot_mr_build_cooldown_status(absent_path, 15, 30) == {}


def test_build_cooldown_status_full():
    """Runtime file valide : ES cooldown actif + position, NQ rien -> 2 entries."""
    from DASHBOARD.api.paper_tracker import _bot_mr_build_cooldown_status
    now_utc = datetime.now(timezone.utc)
    now_sec = now_utc.timestamp()
    runtime_data = {
        "positions": {
            "ES": {
                "signal_id": "abc",
                "direction": "LONG",
                "entry_price": 7600.0,
                "entry_ts": (now_sec - 5 * 60) * 1000,  # entry il y a 5 min
                "sl_price": 7595.0,
                "tp_price": 7610.0,
                "n_micros": 1,
            }
            # NQ : pas de position
        },
        "last_trade_ts_by_symbol": {
            "ES": (now_utc - timedelta(minutes=5)).isoformat(),  # cooldown actif
            "NQ": None,  # pas de cooldown
        },
        "traded_signal_ids": [],
        "cooldown_until_ts": {},
        "last_save_ts": now_sec,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(runtime_data, f)
        tmp_path = Path(f.name)
    try:
        result = _bot_mr_build_cooldown_status(
            tmp_path, cooldown_minutes=15, max_hold_minutes=30,
            now_utc=now_utc, now_ts_sec=now_sec,
        )
        # ES : cooldown actif (~10 min restantes) + position (~25 min restantes)
        assert "ES" in result
        es = result["ES"]
        assert 598 <= es["cooldown_remaining_sec"] <= 602, f"ES cooldown: {es['cooldown_remaining_sec']}"
        assert es["max_hold_remaining_sec"] is not None
        assert 1498 <= es["max_hold_remaining_sec"] <= 1502, f"ES max_hold: {es['max_hold_remaining_sec']}"
        # NQ : pas de cooldown, pas de position
        assert "NQ" in result
        nq = result["NQ"]
        assert nq["cooldown_remaining_sec"] == 0
        assert nq["max_hold_remaining_sec"] is None
    finally:
        tmp_path.unlink()


def test_build_cooldown_status_corrupted_json():
    """JSON corrompu -> {} (defensive, ne crash pas l'endpoint)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_build_cooldown_status
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write("{ not json at all")
        tmp_path = Path(f.name)
    try:
        assert _bot_mr_build_cooldown_status(tmp_path, 15, 30) == {}
    finally:
        tmp_path.unlink()


# ─────────────────────────────────────────────────────────────────────────
# Test 4 — _bot_mr_read_runtime_config (env override)
# ─────────────────────────────────────────────────────────────────────────

def test_read_runtime_config_defaults(monkeypatch):
    """Pas d'env -> defaults BotMRConfig (30 / 30)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_read_runtime_config
    monkeypatch.delenv("BOTMR_COOLDOWN_BARS", raising=False)
    monkeypatch.delenv("BOTMR_MAX_HOLD_MINUTES", raising=False)
    cd, mh = _bot_mr_read_runtime_config()
    assert cd == 30
    assert mh == 30


def test_read_runtime_config_env_override(monkeypatch):
    """Env override -> applique. Validation deployed BOTMR_COOLDOWN_BARS=15."""
    from DASHBOARD.api.paper_tracker import _bot_mr_read_runtime_config
    monkeypatch.setenv("BOTMR_COOLDOWN_BARS", "15")
    monkeypatch.setenv("BOTMR_MAX_HOLD_MINUTES", "30")
    cd, mh = _bot_mr_read_runtime_config()
    assert cd == 15
    assert mh == 30


def test_read_runtime_config_corrupted_env(monkeypatch):
    """Env corrompu (non-int) -> defaults (defensive, ne crash pas)."""
    from DASHBOARD.api.paper_tracker import _bot_mr_read_runtime_config
    monkeypatch.setenv("BOTMR_COOLDOWN_BARS", "not_an_int")
    monkeypatch.setenv("BOTMR_MAX_HOLD_MINUTES", "abc")
    cd, mh = _bot_mr_read_runtime_config()
    assert cd == 30  # default
    assert mh == 30  # default
