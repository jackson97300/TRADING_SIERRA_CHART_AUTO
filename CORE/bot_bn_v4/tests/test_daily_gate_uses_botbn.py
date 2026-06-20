"""Tests FIX BUG #6 silent fallback Mark Douglas audit ULTRATHINK 19/06.

Le bug : main.py ligne 167 fait `DailyLimitsGate(self.bot1v2_cfg)`. Le
DailyLimitsGate lit `cfg.MAX_TRADES_PER_DAY/DAILY_STOP_LOSS_USD/
DAILY_STOP_WIN_USD` -> donc Bot1V2Config seuils, jamais BotBNV4Config.
Si env BOTBN_DAILY_STOP_LOSS_USD=-300 est set, **silencieusement ignore**.

Apres fix : adapter SimpleNamespace force les 3 seuils BotBNV4Config.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_source_uses_simplenamespace_adapter_for_daily_gate():
    """Verifier main.py utilise SimpleNamespace adapter pour DailyLimitsGate."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Pattern fixe : _daily_cfg = SimpleNamespace(...)
    assert "_daily_cfg = SimpleNamespace(" in content, \
        "Fix BUG #6 absent : _daily_cfg SimpleNamespace adapter manquant"
    # Verifier DailyLimitsGate(_daily_cfg) au lieu de (self.bot1v2_cfg)
    assert "DailyLimitsGate(_daily_cfg)" in content, \
        "Fix BUG #6 absent : DailyLimitsGate doit recevoir _daily_cfg, pas bot1v2_cfg"
    # Anti-regression : DailyLimitsGate(self.bot1v2_cfg) NE DOIT PLUS exister
    # dans le code ACTIF (ligne non-commentee). Filtrage par lignes "#".
    active_lines = "\n".join(
        line for line in content.split("\n")
        if not line.lstrip().startswith("#")
    )
    assert "DailyLimitsGate(self.bot1v2_cfg)" not in active_lines, \
        "Regression BUG #6 : DailyLimitsGate(self.bot1v2_cfg) detecte dans code actif"


def test_source_passes_3_botbn_seuils():
    """Le SimpleNamespace doit contenir les 3 seuils Mark Douglas."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # 3 seuils passes depuis self.cfg (BotBNV4Config)
    assert "MAX_TRADES_PER_DAY=self.cfg.MAX_TRADES_PER_DAY" in content
    assert "DAILY_STOP_LOSS_USD=self.cfg.DAILY_STOP_LOSS_USD" in content
    assert "DAILY_STOP_WIN_USD=self.cfg.DAILY_STOP_WIN_USD" in content


def test_botbn_config_exposes_3_seuils():
    """Verifier BotBNV4Config a bien les 3 champs (anti-regression)."""
    from CORE.bot_bn_v4.config import BotBNV4Config
    cfg = BotBNV4Config()
    assert hasattr(cfg, "MAX_TRADES_PER_DAY")
    assert hasattr(cfg, "DAILY_STOP_LOSS_USD")
    assert hasattr(cfg, "DAILY_STOP_WIN_USD")
    # Defaults Mark Douglas (cf memory feedback_douglas_consistency)
    assert cfg.MAX_TRADES_PER_DAY == 5
    assert cfg.DAILY_STOP_LOSS_USD == -200.0
    assert cfg.DAILY_STOP_WIN_USD == 150.0


def test_env_override_botbn_seuils(monkeypatch):
    """Verifier env BOTBN_DAILY_STOP_LOSS_USD prend effet (anti silent fallback)."""
    monkeypatch.setenv("BOTBN_DAILY_STOP_LOSS_USD", "-300.0")
    monkeypatch.setenv("BOTBN_DAILY_STOP_WIN_USD", "+250.0")
    monkeypatch.setenv("BOTBN_MAX_TRADES_PER_DAY", "10")
    # Reload module pour re-evaluer field defaults
    import importlib
    from CORE.bot_bn_v4 import config as _cfg_mod
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.BotBNV4Config()
    assert cfg.DAILY_STOP_LOSS_USD == -300.0, \
        f"env BOTBN_DAILY_STOP_LOSS_USD ignore (got {cfg.DAILY_STOP_LOSS_USD})"
    assert cfg.DAILY_STOP_WIN_USD == 250.0
    assert cfg.MAX_TRADES_PER_DAY == 10


def test_daily_gate_constructor_accepts_simplenamespace():
    """DailyLimitsGate doit accepter SimpleNamespace adapter (duck-typing)."""
    from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
    adapter = SimpleNamespace(
        MAX_TRADES_PER_DAY=10,
        DAILY_STOP_LOSS_USD=-500.0,
        DAILY_STOP_WIN_USD=300.0,
    )
    gate = DailyLimitsGate(adapter)
    # Verifier que le gate utilise bien les seuils du SimpleNamespace
    assert gate.cfg.MAX_TRADES_PER_DAY == 10
    assert gate.cfg.DAILY_STOP_LOSS_USD == -500.0
    assert gate.cfg.DAILY_STOP_WIN_USD == 300.0


def test_scenario_empirique_botbn_300_pas_silent_ignore(monkeypatch):
    """Scenario empirique : Jackson set BOTBN_DAILY_STOP_LOSS_USD=-300 mais le bot
    LISAIT Bot1V2Config -200 (silent fallback). Apres fix : -300 prend effet."""
    monkeypatch.setenv("BOTBN_DAILY_STOP_LOSS_USD", "-300.0")
    import importlib
    from CORE.bot_bn_v4 import config as _cfg_mod
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.BotBNV4Config()
    # Reproduire le SimpleNamespace adapter du fix
    adapter = SimpleNamespace(
        MAX_TRADES_PER_DAY=cfg.MAX_TRADES_PER_DAY,
        DAILY_STOP_LOSS_USD=cfg.DAILY_STOP_LOSS_USD,
        DAILY_STOP_WIN_USD=cfg.DAILY_STOP_WIN_USD,
    )
    from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
    gate = DailyLimitsGate(adapter)
    # Verdict : DSL doit etre -300 (BotBN env), pas -200 (Bot1V2 default)
    assert gate.cfg.DAILY_STOP_LOSS_USD == -300.0, \
        "REGRESSION SILENT FALLBACK : BotBN env n'est pas applique au DailyLimitsGate"
