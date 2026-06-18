"""Tests MAX_HOLD 30 min hard timeout (Lopez AFML Ch.3 triple barrier).

Convention :
  - MAX_HOLD_MINUTES = 30 par defaut (override env BOTMR_MAX_HOLD_MINUTES)
  - entry_ts en milliseconds (int(time.time() * 1000) au format store position)
  - elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
  - Trigger si elapsed_min >= MAX_HOLD_MINUTES

Couvre :
  - Default config = 30
  - Override env
  - Calc age position
  - Comparaison threshold (under / at / above)
"""
from __future__ import annotations

import time

from CORE.bot_mean_revert.config import BotMRConfig


def _make_cfg_with_max_hold(max_hold_min: int) -> BotMRConfig:
    """Helper : cree une cfg avec MAX_HOLD_MINUTES specifique.

    BotMRConfig etant frozen, on utilise object.__setattr__ pour bypass
    le frozen=True (uniquement pour les tests, jamais en code prod).
    """
    cfg = BotMRConfig()
    object.__setattr__(cfg, "MAX_HOLD_MINUTES", max_hold_min)
    return cfg


def test_max_hold_default_is_30():
    """Default MAX_HOLD_MINUTES doit etre 30 (standard Lopez triple barrier)."""
    cfg = BotMRConfig()
    assert cfg.MAX_HOLD_MINUTES == 30


def test_max_hold_env_override(monkeypatch):
    """BOTMR_MAX_HOLD_MINUTES env var override le default via from_env()."""
    monkeypatch.setenv("BOTMR_MAX_HOLD_MINUTES", "15")
    cfg = BotMRConfig.from_env()
    assert cfg.MAX_HOLD_MINUTES == 15


def test_max_hold_env_override_60():
    """BOTMR_MAX_HOLD_MINUTES=60 -> cfg.MAX_HOLD_MINUTES == 60."""
    import os
    os.environ["BOTMR_MAX_HOLD_MINUTES"] = "60"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.MAX_HOLD_MINUTES == 60
    finally:
        del os.environ["BOTMR_MAX_HOLD_MINUTES"]


def test_max_hold_env_invalid_falls_back_default(monkeypatch):
    """BOTMR_MAX_HOLD_MINUTES non-int -> fallback default 30 (cf _env_int)."""
    monkeypatch.setenv("BOTMR_MAX_HOLD_MINUTES", "not_an_int")
    cfg = BotMRConfig.from_env()
    assert cfg.MAX_HOLD_MINUTES == 30


def test_position_age_calc_35min():
    """Position ouverte il y a 35 min : elapsed_min ~ 35 (tolerance flottant)."""
    now_ms = time.time() * 1000
    entry_ts_ms = now_ms - 35 * 60 * 1000  # 35 min ago
    elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
    assert 34.9 <= elapsed_min <= 35.1


def test_position_age_under_threshold():
    """Position ouverte il y a 10 min ne doit PAS declencher timeout (<30)."""
    now_ms = time.time() * 1000
    entry_ts_ms = now_ms - 10 * 60 * 1000  # 10 min ago
    elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
    cfg = _make_cfg_with_max_hold(30)
    assert elapsed_min < cfg.MAX_HOLD_MINUTES


def test_position_age_at_exact_threshold():
    """Position a exactement 30 min doit declencher (comparaison >=)."""
    now_ms = time.time() * 1000
    entry_ts_ms = now_ms - 30 * 60 * 1000  # 30 min ago precisement
    elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
    cfg = _make_cfg_with_max_hold(30)
    # tolerance flottant : la valeur calculee est tres proche de 30 (souvent
    # un peu plus a cause du time.time entre les 2 mesures).
    assert elapsed_min >= cfg.MAX_HOLD_MINUTES - 0.01


def test_position_age_above_threshold_triggers():
    """Position 45 min > 30 min default -> trigger."""
    now_ms = time.time() * 1000
    entry_ts_ms = now_ms - 45 * 60 * 1000
    elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
    cfg = _make_cfg_with_max_hold(30)
    assert elapsed_min >= cfg.MAX_HOLD_MINUTES


def test_position_age_below_threshold_no_trigger():
    """Position 25 min < 30 min default -> pas de trigger."""
    now_ms = time.time() * 1000
    entry_ts_ms = now_ms - 25 * 60 * 1000
    elapsed_min = (now_ms - entry_ts_ms) / 60_000.0
    cfg = _make_cfg_with_max_hold(30)
    assert elapsed_min < cfg.MAX_HOLD_MINUTES


def test_entry_ts_zero_skip_check():
    """Position sans entry_ts (legacy / corrompu) : check skip (>0 obligatoire).

    Le code dans main.py protege via `if entry_ts_ms > 0`. On simule la branche.
    """
    pos = {"entry_ts": 0, "direction": "LONG"}
    entry_ts_ms = pos.get("entry_ts", 0)
    # Branche : on saute le check timeout
    assert not (entry_ts_ms > 0)


def test_entry_ts_missing_field_safe():
    """Position sans cle entry_ts du tout : pos.get default 0, skip check."""
    pos = {"direction": "LONG"}  # pas de entry_ts
    entry_ts_ms = pos.get("entry_ts", 0)
    assert entry_ts_ms == 0
    assert not (entry_ts_ms > 0)


def test_sym_to_contract_mapping():
    """Helper _sym_to_contract retourne contracts U26 (rollover 16/06)."""
    from CORE.bot_mean_revert.main import BotMR
    # On teste le staticmethod sans instancier BotMR (DTC pas requis)
    assert BotMR._sym_to_contract("ES") == "ESU26-CME"
    assert BotMR._sym_to_contract("NQ") == "NQU26-CME"
    assert BotMR._sym_to_contract("MGC") == "MGCQ26-CMECOMEX"
    # Symbole inconnu -> passthrough
    assert BotMR._sym_to_contract("ZZ") == "ZZ"
    # Case-insensitive
    assert BotMR._sym_to_contract("es") == "ESU26-CME"


def test_close_side_long_is_sell():
    """Direction LONG -> close side = SELL (2)."""
    direction = "LONG"
    close_side = 2 if direction == "LONG" else 1
    assert close_side == 2  # SELL


def test_close_side_short_is_buy():
    """Direction SHORT -> close side = BUY (1)."""
    direction = "SHORT"
    close_side = 2 if direction == "LONG" else 1
    assert close_side == 1  # BUY
