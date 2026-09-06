"""Tests config Bot 5 VWAP-SD."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_defaults_market_analyst_specs():
    """Defaults conformes specs market-analyst 20/06."""
    from CORE.bot_vwap_sd.config import VwapSdConfig

    cfg = VwapSdConfig()

    # Compte Sim3 (emplacement Bot 3 BN V4 swap)
    assert cfg.TRADE_ACCOUNT == "Sim3"
    assert cfg.N_MICROS_DEFAULT == 1

    # Setup A NQ SHORT (champion)
    assert cfg.SETUP_A_ENABLED is True
    assert cfg.SETUP_A_TP_TICKS == 80
    assert cfg.SETUP_A_SL_TICKS == 40

    # Setup B NQ LONG - DESACTIVE par defaut (verdict empirique PF 0.52)
    assert cfg.SETUP_B_ENABLED is False, "B doit etre disabled (PF 0.52 edge inverse)"
    assert cfg.SETUP_B_SHADOW is True
    assert cfg.SETUP_B_TP_TICKS == 40
    assert cfg.SETUP_B_SL_TICKS == 20

    # Setup C ES LONG - DESACTIVE par defaut (verdict empirique PF 1.18 marginal)
    assert cfg.SETUP_C_ENABLED is False, "C doit etre disabled (PF 1.18 marginal)"
    assert cfg.SETUP_C_SHADOW is True
    assert cfg.SETUP_C_TP_TICKS == 16
    assert cfg.SETUP_C_SL_TICKS == 8
    assert cfg.SETUP_C_MIN_SLOPE == 0.0

    # Setup D ES SHORT - SHADOW (n=13 insuffisant)
    assert cfg.SETUP_D_ENABLED is False, "D doit etre disabled par defaut (n=13 insuffisant)"
    assert cfg.SETUP_D_SHADOW is True

    # Limits Mark Douglas
    assert cfg.MAX_TRADES_PER_DAY == 5
    assert cfg.DAILY_STOP_LOSS_USD == -200.0
    assert cfg.DAILY_STOP_WIN_USD == 150.0

    # Sessions RTH only (pas Asia/London comme Bot 3)
    assert cfg.TRADABLE_SESSIONS == ("US", "us_cash")

    # Anti-volatility open
    assert cfg.SKIP_FIRST_MINUTES_RTH == 15
    assert cfg.COOLDOWN_MINUTES == 5

    # Instruments
    assert cfg.SYMBOLS == ("NQ", "ES")


def test_env_override(monkeypatch):
    """Env override prefix BOTVWAPSD_ fonctionne."""
    from CORE.bot_vwap_sd.config import VwapSdConfig

    monkeypatch.setenv("BOTVWAPSD_SETUP_A_TP_TICKS", "100")
    monkeypatch.setenv("BOTVWAPSD_SETUP_D_ENABLED", "true")
    monkeypatch.setenv("BOTVWAPSD_TRADE_ACCOUNT", "Sim5")
    monkeypatch.setenv("BOTVWAPSD_DAILY_STOP_LOSS_USD", "-150")

    cfg = VwapSdConfig.from_env()
    assert cfg.SETUP_A_TP_TICKS == 100
    assert cfg.SETUP_D_ENABLED is True
    assert cfg.TRADE_ACCOUNT == "Sim5"
    assert cfg.DAILY_STOP_LOSS_USD == -150.0


def test_immutability():
    """Config frozen : modification leve FrozenInstanceError specifique."""
    from dataclasses import FrozenInstanceError
    from CORE.bot_vwap_sd.config import VwapSdConfig

    cfg = VwapSdConfig()
    # FIX MINEUR #13 : exception specifique au lieu de Exception generique
    with pytest.raises(FrozenInstanceError):
        cfg.SETUP_A_TP_TICKS = 999  # type: ignore
