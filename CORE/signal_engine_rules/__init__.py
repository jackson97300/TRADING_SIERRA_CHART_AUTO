"""signal_engine_rules V1 — middleware tagger for paper trading rules-only.

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md
Plan : DOCS/plans/2026-04-27-signal-engine-rules-implementation.md
"""
from .schema import RuleTag, RULES_SCHEMA_VERSION

__all__ = ["RuleTag", "RULES_SCHEMA_VERSION"]
