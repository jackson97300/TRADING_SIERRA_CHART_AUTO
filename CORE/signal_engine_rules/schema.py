"""RuleTag dataclass for signal_engine_rules V1.

Reuses pattern from CORE/rule_engine.py:38 (RuleSignal) but simpler — one tag
per rule, no aggregation. Aggregation done by paper_trader if needed.

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md section 2.2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


RULES_SCHEMA_VERSION = "1.0"


@dataclass
class RuleTag:
    """Output of a single rule on a single bar.

    Fields:
        direction: -1 SELL, 0 nothing, +1 BUY
        strength: [0, 1] normalized distance to threshold (0 = at threshold, 1 = far inside)
        version: schema version string ("1.0" for V1)
        fired_at: pd.Timestamp of the bar the rule was evaluated on (ts_event)
        meta: free-form dict for traceability (e.g. {"dist_color_up_pct": 0.0003})
    """
    direction: int
    strength: float
    version: str
    fired_at: pd.Timestamp
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"direction must be -1, 0, or 1 (got {self.direction})")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength must be in [0, 1] (got {self.strength})")

    def to_dict(self) -> dict:
        """Serialize to dict (JSONL-ready). Timestamp -> ISO string."""
        return {
            "direction": int(self.direction),
            "strength": float(self.strength),
            "version": self.version,
            "fired_at": self.fired_at.isoformat() if self.fired_at is not None else None,
            "meta": dict(self.meta),
        }
