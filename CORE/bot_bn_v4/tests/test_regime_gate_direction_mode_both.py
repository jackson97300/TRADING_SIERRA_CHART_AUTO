"""Tests FIX BUG #4 BLOQUANT review code-reviewer 19/06.

Avant fix : main.py:445 appelait RegimeGate avec proposed_dir='long' meme
quand DIRECTION_MODE='both'. Si regime bearish, RegimeGate refusait LONG ->
return immediat -> SHORT jamais evalue par SignalEngine. Sabote B.4.

Apres fix : si DIRECTION_MODE='both', skip check eager + deferred check
post-SignalEngine avec la direction reellement proposee (long ou short).

Bugs trouves par code-reviewer ce vendredi soir :
- BLOQUANT bug #4 : trade -$967 15/06 scenario manque silencieusement
- Pattern VALIDATION_MISS (cf memory feedback_validation_miss_pre_deploy.md)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_log_code_regime_block_post_signal_registered():
    """Code log BOTBN_GATE_REGIME_BLOCK_POST_SIGNAL doit etre dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    from CORE.logging_v2 import LogLevel

    assert "BOTBN_GATE_REGIME_BLOCK_POST_SIGNAL" in LOG_CODES, \
        "Fix BUG #4 absent : code log POST_SIGNAL non defini"
    level, category, template = LOG_CODES["BOTBN_GATE_REGIME_BLOCK_POST_SIGNAL"]
    assert category == "risk"


def test_source_main_uses_deferred_regime_check_when_both():
    """main.py doit avoir le pattern deferred regime check si DIRECTION_MODE='both'."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")

    # Pattern 1 : skip eager check si "both"
    assert 'if self.cfg.DIRECTION_MODE != "both":' in content, \
        "Fix BUG #4 absent : check eager doit etre conditionnel sur DIRECTION_MODE != 'both'"

    # Pattern 2 : deferred check post-SignalEngine
    assert 'self.cfg.DIRECTION_MODE == "both"' in content
    assert "decision.direction is not None" in content
    assert "BOTBN_GATE_REGIME_BLOCK_POST_SIGNAL" in content


def test_source_no_more_hardcoded_long_fallback():
    """main.py ne doit PLUS contenir le fallback hardcode 'long' biaise."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")

    # L'ancienne ligne buggee : proposed_dir = DIRECTION_MODE if != "both" else "long"
    # ne doit plus etre presente en code actif (commentaire OK).
    # On verifie que la ligne EXACTE n'apparait pas comme code actif
    bug_pattern = 'proposed_dir = self.cfg.DIRECTION_MODE if self.cfg.DIRECTION_MODE != "both" else "long"'
    active_lines = "\n".join(
        line for line in content.split("\n")
        if not line.lstrip().startswith("#")
    )
    assert bug_pattern not in active_lines, \
        "BUG #4 toujours present : fallback hardcode 'long' biaise toujours dans le code actif"


def test_signal_decision_can_be_rebuilt_with_skip_reason():
    """SignalDecision dataclass doit supporter rebuild avec skip_reason POST_SIGNAL."""
    from CORE.bot_bn_v4.signal_engine import SignalDecision

    # Simule rebuild apres regime block post-signal
    decision = SignalDecision(
        tradable=False,
        direction="short",
        setup={"grade": "A++", "mode": "TRADE"},
        skip_reason="REGIME_POST_SIGNAL:gamma_bearish_long_only",
        hypothetical=False,
        grade="A++",
    )
    assert decision.tradable is False
    assert decision.direction == "short"
    assert decision.skip_reason.startswith("REGIME_POST_SIGNAL:")
    assert decision.grade == "A++"
