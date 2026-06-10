"""Bot 3 Gold — Context Analyzer (12 standard + 8 Gold-spécifiques).

Re-export de `build_gold_context()` qui vit dans bot3_gold_decision_engine.py
pour respecter l'arborescence du prompt (5 fichiers séparés).

Class wrapper pour usage OO si besoin (live bot).
"""
from __future__ import annotations

try:
    from CORE.bot3_gold_decision_engine import build_gold_context, detect_session
except ImportError:
    from bot3_gold_decision_engine import build_gold_context, detect_session


class GoldContextAnalyzer:
    """Wrapper classe pour build_gold_context (compat OO live engine)."""

    def analyze(self, bar: dict) -> dict:
        """Build context 20 dimensions (12 standard + 8 Gold) depuis 1 bar."""
        return build_gold_context(bar)


__all__ = ["GoldContextAnalyzer", "build_gold_context", "detect_session"]
