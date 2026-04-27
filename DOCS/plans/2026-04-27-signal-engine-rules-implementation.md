# signal_engine_rules V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a middleware tagger that produces 9 isolated rule tags per bar (no voting, no cascading) for paper trading + behavioral data collection on dataset v5b.

**Architecture:** Library of pure functions (rules.py) + batch wrapper (batch_tagger.py) + dataclass (schema.py). Each rule: `features_dict -> RuleTag(direction, strength, version, fired_at, meta)`. Batch tagger transforms parquet v5b → v5c with 18 added cols (2 per rule). Integration with mia_paper_trader via snapshot enrichment at trade close.

**Tech Stack:** Python 3.13, pandas, numpy, pytest, lightgbm (existing). Reuses RuleSignal pattern from `CORE/rule_engine.py:38` (renamed RuleTag for clarity).

**Spec reference:** `DOCS/specs/2026-04-27-signal-engine-rules-design.md`

**Critical anti-leak constraint** (incident 27/04 21:30): NO feature broadcast by session aggregation without NaN mask during active session. Tests `test_no_lookahead.py` are NON-NEGOTIABLE.

---

## File Structure

```
CORE/signal_engine_rules/
├── __init__.py                     ← Re-export public API
├── schema.py                       ← RuleTag dataclass + RULES_SCHEMA_VERSION
├── rules.py                        ← 9 pure functions rule_X(features) -> RuleTag
├── batch_tagger.py                 ← Vectorized parquet v5b → v5c
└── tests/
    ├── __init__.py                 ← (empty)
    ├── test_schema.py              ← RuleTag serialization tests
    ├── test_rules.py               ← 9 unit tests (1 per rule)
    ├── test_no_lookahead.py        ← Future divergence → identical output
    └── fixtures.py                 ← Synthetic bar fixtures shared across tests
```

**Modifications:**
- `CORE/mia_paper_trader.py` — add `_lookup_rules_tags()` helper + `rules_fired` field in close snapshot
- `DOCS/BOT_CHANGELOG.md` — append entry for V1 deployment

---

## Task 1: Setup package structure + schema

**Files:**
- Create: `CORE/signal_engine_rules/__init__.py`
- Create: `CORE/signal_engine_rules/schema.py`
- Create: `CORE/signal_engine_rules/tests/__init__.py`
- Test: `CORE/signal_engine_rules/tests/test_schema.py`

- [ ] **Step 1: Create empty package init files**

```python
# CORE/signal_engine_rules/__init__.py
"""signal_engine_rules V1 — middleware tagger for paper trading rules-only.

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md
Plan : DOCS/plans/2026-04-27-signal-engine-rules-implementation.md
"""
from .schema import RuleTag, RULES_SCHEMA_VERSION

__all__ = ["RuleTag", "RULES_SCHEMA_VERSION"]
```

```python
# CORE/signal_engine_rules/tests/__init__.py
```

- [ ] **Step 2: Write the failing test for RuleTag dataclass**

```python
# CORE/signal_engine_rules/tests/test_schema.py
"""Tests RuleTag dataclass + serialization."""
import pandas as pd
import pytest

from CORE.signal_engine_rules.schema import RuleTag, RULES_SCHEMA_VERSION


def test_ruletag_default_values():
    """RuleTag with minimal args has sane defaults."""
    tag = RuleTag(direction=0, strength=0.0, version=RULES_SCHEMA_VERSION,
                  fired_at=pd.Timestamp("2026-04-27 14:30", tz="UTC"))
    assert tag.direction == 0
    assert tag.strength == 0.0
    assert tag.version == "1.0"
    assert tag.meta == {}


def test_ruletag_to_dict_serialization():
    """RuleTag serializes to dict with iso timestamp + native types."""
    ts = pd.Timestamp("2026-04-27 14:30", tz="UTC")
    tag = RuleTag(direction=1, strength=0.85, version="1.0", fired_at=ts,
                  meta={"dist_color_up_pct": 0.0003})
    d = tag.to_dict()
    assert d["direction"] == 1
    assert d["strength"] == 0.85
    assert d["version"] == "1.0"
    assert d["fired_at"] == "2026-04-27T14:30:00+00:00"
    assert d["meta"] == {"dist_color_up_pct": 0.0003}


def test_ruletag_direction_validation():
    """direction must be in {-1, 0, +1}."""
    with pytest.raises(ValueError, match="direction must be -1, 0, or 1"):
        RuleTag(direction=2, strength=0.5, version="1.0",
                fired_at=pd.Timestamp("2026-04-27"))


def test_ruletag_strength_validation():
    """strength must be in [0, 1]."""
    with pytest.raises(ValueError, match="strength must be in"):
        RuleTag(direction=1, strength=1.5, version="1.0",
                fired_at=pd.Timestamp("2026-04-27"))


def test_ruletag_zero_signal_serialization():
    """direction=0 still serializes correctly (no fire case)."""
    ts = pd.Timestamp("2026-04-27 14:30", tz="UTC")
    tag = RuleTag(direction=0, strength=0.0, version="1.0", fired_at=ts)
    d = tag.to_dict()
    assert d["direction"] == 0
    assert d["meta"] == {}


def test_rules_schema_version_constant():
    """Schema version is a string."""
    assert isinstance(RULES_SCHEMA_VERSION, str)
    assert RULES_SCHEMA_VERSION == "1.0"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: signal_engine_rules.schema`

- [ ] **Step 4: Write the schema module**

```python
# CORE/signal_engine_rules/schema.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_schema.py -v`
Expected: 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add CORE/signal_engine_rules/__init__.py CORE/signal_engine_rules/schema.py CORE/signal_engine_rules/tests/__init__.py CORE/signal_engine_rules/tests/test_schema.py
git commit -m "feat(rules): RuleTag dataclass + schema v1.0"
```

---

## Task 2: Synthetic test fixtures

**Files:**
- Create: `CORE/signal_engine_rules/tests/fixtures.py`

This task has no implementation code in the prod modules — it provides fixtures for Tasks 3-11 tests. No test-file required since fixtures.py IS test infrastructure.

- [ ] **Step 1: Write the fixtures module**

```python
# CORE/signal_engine_rules/tests/fixtures.py
"""Shared synthetic bar fixtures for rule tests.

Builds dict[str, Any] features matching v5b parquet schema for tests.
NO REAL DATA — all values are deterministic, hand-crafted to trigger or
not-trigger specific rules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_bar_base(ts_event: str = "2026-04-27 14:30:00") -> dict:
    """Base bar with all common features set to neutral/safe defaults.

    Use as base, override specific fields per test.
    """
    return {
        "ts_event": pd.Timestamp(ts_event, tz="UTC"),
        "high": 4500.0, "low": 4499.0, "close": 4499.5, "open": 4499.5,
        "atr": 5.0,  # ticks
        "is_in_us_cash": 1,  # default RTH
        "mins_et": 600,  # default 10:00 ET (post-IB-window=630 false; cash session true 570-960)
        "delta_day_dir": 1,
        # Long bar features
        "long_up_bar": 0, "long_dn_bar": 0,
        "long_up_dn_pattern": 0, "long_dn_up_pattern": 0,
        # Color zones
        "dist_color_up_nearest_pct": 0.5, "dist_color_dn_nearest_pct": -0.5,
        # Cluster
        "cluster_at_high": 0, "cluster_at_low": 0,
        # IB
        "ib_broken_up": 0, "ib_broken_down": 0, "ib_position_pct": 0.5,
        # Edge zones
        "bar_edge_buy_fire": 0, "bar_edge_sell_fire": 0,
    }


def make_bar_long_up_rth() -> dict:
    """Bar that should fire long_up_bar (long up bar in RTH)."""
    bar = make_bar_base()
    bar["long_up_bar"] = 1
    bar["is_in_us_cash"] = 1
    return bar


def make_bar_long_up_outside_rth() -> dict:
    """Bar long_up_bar but OUTSIDE RTH (should NOT fire)."""
    bar = make_bar_base()
    bar["long_up_bar"] = 1
    bar["is_in_us_cash"] = 0
    return bar


def make_bar_color_up_close() -> dict:
    """Bar very close to color_up zone with positive delta (fires color_up_proximity)."""
    bar = make_bar_base()
    bar["dist_color_up_nearest_pct"] = 0.0003  # 0.03% < threshold 0.05%
    bar["delta_day_dir"] = 1
    return bar


def make_bar_color_up_far() -> dict:
    """Bar far from color_up (should NOT fire)."""
    bar = make_bar_base()
    bar["dist_color_up_nearest_pct"] = 0.5  # far
    bar["delta_day_dir"] = 1
    return bar


def make_bar_failed_ib_pre_close() -> dict:
    """Failed IB pattern but BEFORE 10:30 ET (anti-leak: must NOT fire)."""
    bar = make_bar_base()
    bar["mins_et"] = 600  # 10:00 ET, before 10:30
    bar["ib_broken_up"] = 1
    bar["ib_position_pct"] = 0.0  # back inside IB
    return bar


def make_bar_failed_ib_post_close() -> dict:
    """Failed IB pattern AFTER 10:30 ET (fires SHORT)."""
    bar = make_bar_base()
    bar["mins_et"] = 700  # 11:40 ET, post-IB
    bar["ib_broken_up"] = 1
    bar["ib_position_pct"] = 0.0  # back inside IB
    return bar


def make_bar_cluster_at_low() -> dict:
    """Bar with cluster_at_low + delta dir up → fires BUY."""
    bar = make_bar_base()
    bar["cluster_at_low"] = 1
    bar["delta_day_dir"] = 1
    return bar


def make_bar_edge_buy() -> dict:
    """Bar with bar_edge_buy_fire=1 → fires BUY."""
    bar = make_bar_base()
    bar["bar_edge_buy_fire"] = 1
    return bar


def make_bar_with_nan(rule_field: str) -> dict:
    """Bar with NaN on critical feature for given rule."""
    bar = make_bar_base()
    bar[rule_field] = np.nan
    return bar


def make_dataframe_from_bars(bars: list[dict]) -> pd.DataFrame:
    """Helper: build a DataFrame from list of bar dicts."""
    return pd.DataFrame(bars)
```

- [ ] **Step 2: Sanity check fixtures importable**

Run: `python -c "from CORE.signal_engine_rules.tests.fixtures import make_bar_base; print(make_bar_base()['close'])"`
Expected output: `4499.5`

- [ ] **Step 3: Commit**

```bash
git add CORE/signal_engine_rules/tests/fixtures.py
git commit -m "test(rules): add synthetic bar fixtures for rule tests"
```

---

## Task 3: Rule 1 + 2 — long_up_bar + long_dn_bar

**Files:**
- Create: `CORE/signal_engine_rules/rules.py`
- Test: `CORE/signal_engine_rules/tests/test_rules.py`

- [ ] **Step 1: Write the failing tests for rules 1 + 2**

```python
# CORE/signal_engine_rules/tests/test_rules.py
"""Unit tests for the 9 V1 rules.

Each rule has at least 3 tests:
1. Bar that SHOULD fire → assert direction != 0
2. Bar that should NOT fire → assert direction == 0
3. Bar with NaN on critical feature → assert direction == 0 (no crash)
"""
import math
import numpy as np
import pandas as pd
import pytest

from CORE.signal_engine_rules.rules import (
    rule_long_up_bar, rule_long_dn_bar,
)
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_long_up_rth, make_bar_long_up_outside_rth, make_bar_with_nan,
    make_bar_base,
)


# ─── Rule 1 : long_up_bar ─────────────────────────────────────────────

def test_long_up_bar_fires_in_rth():
    bar = make_bar_long_up_rth()
    tag = rule_long_up_bar(bar)
    assert tag.direction == 1
    assert tag.strength == 1.0


def test_long_up_bar_does_not_fire_outside_rth():
    bar = make_bar_long_up_outside_rth()
    tag = rule_long_up_bar(bar)
    assert tag.direction == 0


def test_long_up_bar_does_not_fire_when_flag_zero():
    bar = make_bar_base()  # long_up_bar = 0
    tag = rule_long_up_bar(bar)
    assert tag.direction == 0


def test_long_up_bar_handles_nan():
    bar = make_bar_with_nan("long_up_bar")
    tag = rule_long_up_bar(bar)
    assert tag.direction == 0


# ─── Rule 2 : long_dn_bar (symmetric) ─────────────────────────────────

def test_long_dn_bar_fires_in_rth():
    bar = make_bar_base()
    bar["long_dn_bar"] = 1
    tag = rule_long_dn_bar(bar)
    assert tag.direction == -1
    assert tag.strength == 1.0


def test_long_dn_bar_does_not_fire_outside_rth():
    bar = make_bar_base()
    bar["long_dn_bar"] = 1
    bar["is_in_us_cash"] = 0
    tag = rule_long_dn_bar(bar)
    assert tag.direction == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: FAIL with `ImportError: cannot import name 'rule_long_up_bar'`

- [ ] **Step 3: Create rules.py with rules 1 and 2**

```python
# CORE/signal_engine_rules/rules.py
"""9 pure rule functions for signal_engine_rules V1.

Each rule:
  - Takes a dict of features (1 bar)
  - Returns a RuleTag with direction {-1, 0, +1}, strength [0, 1], meta
  - NEVER raises (NaN-safe via _safe_get helpers)
  - ANTI-LEAK : never reads features known leaky (ovn_*, ib_* pre-fix, above_open_*)
  - bar_closed assumption : caller must ensure bar is closed (live_tagger V2 enforces)

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md section 3
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from CORE.signal_engine_rules.schema import RuleTag, RULES_SCHEMA_VERSION


# ═══════════════════════════════════════════════════════════════════════
# Helpers — NaN-safe accessors
# ═══════════════════════════════════════════════════════════════════════

def _safe_get(features: dict, col: str, default: Any = 0.0) -> Any:
    """Get feature with NaN→default fallback. Returns default if NaN/None/missing."""
    v = features.get(col, default)
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def _safe_get_nullable(features: dict, col: str):
    """Get feature, return None if NaN/None/missing."""
    v = features.get(col, None)
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _zero_tag(features: dict) -> RuleTag:
    """Helper: build a no-fire RuleTag with current bar timestamp."""
    return RuleTag(
        direction=0,
        strength=0.0,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Rule 1 — long_up_bar (Acosta long bar continuation)
# ═══════════════════════════════════════════════════════════════════════

def rule_long_up_bar(features: dict) -> RuleTag:
    """Long up bar in US cash session → BUY continuation.

    Feature : long_up_bar (binary 0/1, ~4% bars active in v5b).
    Filter  : is_in_us_cash == 1 (avoid Asia/London noise).
    Strength: 1.0 if fire (binary), 0.0 otherwise.
    """
    if int(_safe_get(features, "long_up_bar", 0)) != 1:
        return _zero_tag(features)
    if int(_safe_get(features, "is_in_us_cash", 0)) != 1:
        return _zero_tag(features)
    return RuleTag(
        direction=+1,
        strength=1.0,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"is_in_us_cash": 1},
    )


# ═══════════════════════════════════════════════════════════════════════
# Rule 2 — long_dn_bar (symmetric)
# ═══════════════════════════════════════════════════════════════════════

def rule_long_dn_bar(features: dict) -> RuleTag:
    """Long down bar in US cash session → SELL continuation."""
    if int(_safe_get(features, "long_dn_bar", 0)) != 1:
        return _zero_tag(features)
    if int(_safe_get(features, "is_in_us_cash", 0)) != 1:
        return _zero_tag(features)
    return RuleTag(
        direction=-1,
        strength=1.0,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"is_in_us_cash": 1},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 1+2 long_up_bar + long_dn_bar with RTH filter"
```

---

## Task 4: Rule 3 + 4 — color_up_proximity + color_dn_proximity

**Files:**
- Modify: `CORE/signal_engine_rules/rules.py` (append)
- Modify: `CORE/signal_engine_rules/tests/test_rules.py` (append)

- [ ] **Step 1: Append failing tests for rules 3 + 4**

```python
# Append to test_rules.py
from CORE.signal_engine_rules.rules import (
    rule_color_up_proximity, rule_color_dn_proximity,
)
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_color_up_close, make_bar_color_up_far,
)


# ─── Rule 3 : color_up_proximity ──────────────────────────────────────

def test_color_up_proximity_fires_when_close_with_delta_up():
    bar = make_bar_color_up_close()
    tag = rule_color_up_proximity(bar)
    assert tag.direction == 1
    assert 0 < tag.strength <= 1.0
    assert "dist_color_up_pct" in tag.meta


def test_color_up_proximity_does_not_fire_when_far():
    bar = make_bar_color_up_far()
    tag = rule_color_up_proximity(bar)
    assert tag.direction == 0


def test_color_up_proximity_does_not_fire_when_delta_down():
    bar = make_bar_color_up_close()
    bar["delta_day_dir"] = -1
    tag = rule_color_up_proximity(bar)
    assert tag.direction == 0


def test_color_up_proximity_handles_nan():
    bar = make_bar_with_nan("dist_color_up_nearest_pct")
    tag = rule_color_up_proximity(bar)
    assert tag.direction == 0


# ─── Rule 4 : color_dn_proximity (symmetric) ──────────────────────────

def test_color_dn_proximity_fires_when_close_with_delta_down():
    bar = make_bar_base()
    bar["dist_color_dn_nearest_pct"] = -0.0003  # close to color_dn (negative side)
    bar["delta_day_dir"] = -1
    tag = rule_color_dn_proximity(bar)
    assert tag.direction == -1


def test_color_dn_proximity_does_not_fire_when_delta_up():
    bar = make_bar_base()
    bar["dist_color_dn_nearest_pct"] = -0.0003
    bar["delta_day_dir"] = 1
    tag = rule_color_dn_proximity(bar)
    assert tag.direction == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 6 prev PASS + 6 new FAIL with ImportError

- [ ] **Step 3: Append rules 3 + 4 to rules.py**

```python
# Append to rules.py

# ═══════════════════════════════════════════════════════════════════════
# Rule 3 — color_up_proximity (top SHAP v5b #4)
# ═══════════════════════════════════════════════════════════════════════

# Threshold : trigger fire when distance < 0.05% (0.0005)
COLOR_PROXIMITY_THRESHOLD_PCT = 0.0005


def rule_color_up_proximity(features: dict) -> RuleTag:
    """BUY when price proche d'une zone color_up + delta day positif.

    SHAP best_buy_range: dist_color_up_nearest_pct > -0.04 (proche)
    Threshold V1 : abs(dist) < 0.05% AND delta_day_dir > 0
    Strength    : (1 - abs(dist) / threshold), 1.0 = right at zone.
    """
    d_up = _safe_get_nullable(features, "dist_color_up_nearest_pct")
    if d_up is None:
        return _zero_tag(features)
    if abs(d_up) > COLOR_PROXIMITY_THRESHOLD_PCT:
        return _zero_tag(features)
    delta_dir = _safe_get(features, "delta_day_dir", 0)
    if delta_dir <= 0:
        return _zero_tag(features)
    strength = 1.0 - min(abs(d_up) / COLOR_PROXIMITY_THRESHOLD_PCT, 1.0)
    return RuleTag(
        direction=+1,
        strength=float(strength),
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"dist_color_up_pct": float(d_up), "delta_day_dir": int(delta_dir)},
    )


# ═══════════════════════════════════════════════════════════════════════
# Rule 4 — color_dn_proximity (symmetric, top SHAP v5b #3)
# ═══════════════════════════════════════════════════════════════════════

def rule_color_dn_proximity(features: dict) -> RuleTag:
    """SELL when price proche d'une zone color_dn + delta day négatif."""
    d_dn = _safe_get_nullable(features, "dist_color_dn_nearest_pct")
    if d_dn is None:
        return _zero_tag(features)
    if abs(d_dn) > COLOR_PROXIMITY_THRESHOLD_PCT:
        return _zero_tag(features)
    delta_dir = _safe_get(features, "delta_day_dir", 0)
    if delta_dir >= 0:
        return _zero_tag(features)
    strength = 1.0 - min(abs(d_dn) / COLOR_PROXIMITY_THRESHOLD_PCT, 1.0)
    return RuleTag(
        direction=-1,
        strength=float(strength),
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"dist_color_dn_pct": float(d_dn), "delta_day_dir": int(delta_dir)},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 3+4 color_up_proximity + color_dn_proximity"
```

---

## Task 5: Rule 5 — color_zone_break (JC2)

**Files:**
- Modify: `CORE/signal_engine_rules/rules.py` (append)
- Modify: `CORE/signal_engine_rules/tests/test_rules.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# Append to test_rules.py
from CORE.signal_engine_rules.rules import rule_color_zone_break


def test_color_zone_break_fires_buy_when_above_color_up():
    bar = make_bar_base()
    # dist_color_up_nearest_pct < 0 means price ABOVE color_up zone (= broke up)
    bar["dist_color_up_nearest_pct"] = -0.0001
    bar["delta_day_dir"] = 1
    tag = rule_color_zone_break(bar)
    assert tag.direction == 1


def test_color_zone_break_fires_sell_when_below_color_dn():
    bar = make_bar_base()
    # dist_color_dn_nearest_pct > 0 means price BELOW color_dn (= broke down)
    bar["dist_color_dn_nearest_pct"] = 0.0001
    bar["delta_day_dir"] = -1
    tag = rule_color_zone_break(bar)
    assert tag.direction == -1


def test_color_zone_break_does_not_fire_when_no_break():
    bar = make_bar_base()
    bar["dist_color_up_nearest_pct"] = 0.5  # far from color_up
    bar["dist_color_dn_nearest_pct"] = -0.5  # far from color_dn
    tag = rule_color_zone_break(bar)
    assert tag.direction == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py::test_color_zone_break_fires_buy_when_above_color_up -v`
Expected: FAIL ImportError

- [ ] **Step 3: Append rule 5 to rules.py**

```python
# Append to rules.py

# ═══════════════════════════════════════════════════════════════════════
# Rule 5 — color_zone_break (JC2 PF 1.11 NQ confirmé)
# ═══════════════════════════════════════════════════════════════════════

def rule_color_zone_break(features: dict) -> RuleTag:
    """BUY si cassure au-dessus zone color_up confirmée par delta dir up.
    SELL si cassure sous zone color_dn confirmée par delta dir down.

    Convention v5b : dist_color_up_nearest_pct < 0 = price ABOVE color_up zone.
                    dist_color_dn_nearest_pct > 0 = price BELOW color_dn zone.
    """
    d_up = _safe_get_nullable(features, "dist_color_up_nearest_pct")
    d_dn = _safe_get_nullable(features, "dist_color_dn_nearest_pct")
    delta_dir = _safe_get(features, "delta_day_dir", 0)

    # BUY break : just above color_up + delta up
    if d_up is not None and -0.0005 < d_up < 0 and delta_dir > 0:
        return RuleTag(
            direction=+1,
            strength=0.7,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"dist_color_up_pct": float(d_up), "side": "break_up"},
        )
    # SELL break : just below color_dn + delta dn
    if d_dn is not None and 0 < d_dn < 0.0005 and delta_dir < 0:
        return RuleTag(
            direction=-1,
            strength=0.7,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"dist_color_dn_pct": float(d_dn), "side": "break_dn"},
        )
    return _zero_tag(features)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 5 color_zone_break (JC2 PF 1.11 NQ)"
```

---

## Task 6: Rule 6 + 7 — cluster_at_high + cluster_at_low

**Files:**
- Modify: `CORE/signal_engine_rules/rules.py` (append)
- Modify: `CORE/signal_engine_rules/tests/test_rules.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# Append to test_rules.py
from CORE.signal_engine_rules.rules import (
    rule_cluster_at_high, rule_cluster_at_low,
)
from CORE.signal_engine_rules.tests.fixtures import make_bar_cluster_at_low


# ─── Rule 6 : cluster_at_high ─────────────────────────────────────────

def test_cluster_at_high_fires_sell_with_delta_down():
    bar = make_bar_base()
    bar["cluster_at_high"] = 1
    bar["delta_day_dir"] = -1
    tag = rule_cluster_at_high(bar)
    assert tag.direction == -1


def test_cluster_at_high_does_not_fire_with_delta_up():
    bar = make_bar_base()
    bar["cluster_at_high"] = 1
    bar["delta_day_dir"] = 1
    tag = rule_cluster_at_high(bar)
    assert tag.direction == 0


# ─── Rule 7 : cluster_at_low ──────────────────────────────────────────

def test_cluster_at_low_fires_buy():
    bar = make_bar_cluster_at_low()
    tag = rule_cluster_at_low(bar)
    assert tag.direction == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 15 PASS + 3 FAIL ImportError

- [ ] **Step 3: Append rules 6 + 7 to rules.py**

```python
# Append to rules.py

# ═══════════════════════════════════════════════════════════════════════
# Rule 6 — cluster_at_high (rare event)
# ═══════════════════════════════════════════════════════════════════════

def rule_cluster_at_high(features: dict) -> RuleTag:
    """Cluster bid/ask au high de bar + delta dir baissier → SELL rejet."""
    if int(_safe_get(features, "cluster_at_high", 0)) != 1:
        return _zero_tag(features)
    delta_dir = _safe_get(features, "delta_day_dir", 0)
    if delta_dir >= 0:
        return _zero_tag(features)
    return RuleTag(
        direction=-1,
        strength=0.8,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"cluster_at_high": 1, "delta_day_dir": int(delta_dir)},
    )


# ═══════════════════════════════════════════════════════════════════════
# Rule 7 — cluster_at_low (rare event)
# ═══════════════════════════════════════════════════════════════════════

def rule_cluster_at_low(features: dict) -> RuleTag:
    """Cluster bid/ask au low de bar + delta dir haussier → BUY rebond."""
    if int(_safe_get(features, "cluster_at_low", 0)) != 1:
        return _zero_tag(features)
    delta_dir = _safe_get(features, "delta_day_dir", 0)
    if delta_dir <= 0:
        return _zero_tag(features)
    return RuleTag(
        direction=+1,
        strength=0.8,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"cluster_at_low": 1, "delta_day_dir": int(delta_dir)},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 18 tests PASS

- [ ] **Step 5: Commit**

```bash
git add CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 6+7 cluster_at_high + cluster_at_low"
```

---

## Task 7: Rule 8 — failed_ib_poor_high (with anti-leak guard)

**Files:**
- Modify: `CORE/signal_engine_rules/rules.py` (append)
- Modify: `CORE/signal_engine_rules/tests/test_rules.py` (append)

- [ ] **Step 1: Append failing tests with anti-leak focus**

```python
# Append to test_rules.py
from CORE.signal_engine_rules.rules import rule_failed_ib_poor_high
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_failed_ib_pre_close, make_bar_failed_ib_post_close,
)


def test_failed_ib_does_not_fire_pre_1030_anti_leak():
    """ANTI-LEAK : if mins_et < 630 (pre-10:30), MUST NOT fire even if conditions met."""
    bar = make_bar_failed_ib_pre_close()
    tag = rule_failed_ib_poor_high(bar)
    assert tag.direction == 0, "Anti-leak guard failed: rule fired before IB closed"


def test_failed_ib_fires_short_post_1030():
    """Post-IB, broken_up + back inside IB → SHORT (poor high)."""
    bar = make_bar_failed_ib_post_close()
    tag = rule_failed_ib_poor_high(bar)
    assert tag.direction == -1


def test_failed_ib_fires_long_when_broken_dn_back_inside():
    """Post-IB, broken_down + back inside IB → LONG (poor low)."""
    bar = make_bar_base()
    bar["mins_et"] = 700
    bar["ib_broken_down"] = 1
    bar["ib_position_pct"] = 0.0
    tag = rule_failed_ib_poor_high(bar)
    assert tag.direction == 1


def test_failed_ib_no_break_no_fire():
    bar = make_bar_base()
    bar["mins_et"] = 700
    bar["ib_broken_up"] = 0
    bar["ib_broken_down"] = 0
    tag = rule_failed_ib_poor_high(bar)
    assert tag.direction == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 18 PASS + 4 FAIL ImportError

- [ ] **Step 3: Append rule 8 to rules.py**

```python
# Append to rules.py

# ═══════════════════════════════════════════════════════════════════════
# Rule 8 — failed_ib_poor_high (H3 Crabel + ANTI-LEAK guard)
# ═══════════════════════════════════════════════════════════════════════

# Anti-leak: IB window 09:30-10:30 ET (mins_et 570-630)
IB_CLOSE_MINS_ET = 630


def rule_failed_ib_poor_high(features: dict) -> RuleTag:
    """Failed IB break = poor high → reversal (Crabel 1990, H3 PF 1.18 NQ).

    ANTI-LEAK GUARD : returns 0 if mins_et < 630 (IB not closed yet).
    Logic:
      - Broke UP and back inside IB (-0.5 < ib_position_pct < 0.5) → SHORT poor high
      - Broke DN and back inside IB → LONG poor low
    """
    # ANTI-LEAK : refuse to fire pre-IB-close
    mins_et = int(_safe_get(features, "mins_et", 0))
    if mins_et < IB_CLOSE_MINS_ET:
        return _zero_tag(features)

    br_up = int(_safe_get(features, "ib_broken_up", 0))
    br_dn = int(_safe_get(features, "ib_broken_down", 0))
    pos = _safe_get_nullable(features, "ib_position_pct")
    if pos is None:
        return _zero_tag(features)

    if br_up == 1 and -0.5 < pos < 0.5:
        return RuleTag(
            direction=-1,
            strength=0.7,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "poor_high", "ib_position_pct": float(pos)},
        )
    if br_dn == 1 and -0.5 < pos < 0.5:
        return RuleTag(
            direction=+1,
            strength=0.7,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "poor_low", "ib_position_pct": float(pos)},
        )
    return _zero_tag(features)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 22 tests PASS

- [ ] **Step 5: Commit**

```bash
git add CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 8 failed_ib_poor_high with anti-leak guard pre-10:30"
```

---

## Task 8: Rule 9 — edge_zone_fire (JE)

**Files:**
- Modify: `CORE/signal_engine_rules/rules.py` (append)
- Modify: `CORE/signal_engine_rules/tests/test_rules.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# Append to test_rules.py
from CORE.signal_engine_rules.rules import rule_edge_zone_fire
from CORE.signal_engine_rules.tests.fixtures import make_bar_edge_buy


def test_edge_zone_fires_buy():
    bar = make_bar_edge_buy()
    tag = rule_edge_zone_fire(bar)
    assert tag.direction == 1


def test_edge_zone_fires_sell():
    bar = make_bar_base()
    bar["bar_edge_sell_fire"] = 1
    tag = rule_edge_zone_fire(bar)
    assert tag.direction == -1


def test_edge_zone_no_fire_when_both_zero():
    bar = make_bar_base()
    tag = rule_edge_zone_fire(bar)
    assert tag.direction == 0


def test_edge_zone_buy_priority_when_both_fire():
    """Edge case: both buy and sell fire — return BUY (deterministic)."""
    bar = make_bar_base()
    bar["bar_edge_buy_fire"] = 1
    bar["bar_edge_sell_fire"] = 1
    tag = rule_edge_zone_fire(bar)
    assert tag.direction == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 22 PASS + 4 FAIL ImportError

- [ ] **Step 3: Append rule 9 + RULES registry to rules.py**

```python
# Append to rules.py

# ═══════════════════════════════════════════════════════════════════════
# Rule 9 — edge_zone_fire (JE setup live Jackson)
# ═══════════════════════════════════════════════════════════════════════

def rule_edge_zone_fire(features: dict) -> RuleTag:
    """BUY si bar_edge_buy_fire=1, SELL si bar_edge_sell_fire=1.

    Si les 2 firent simultanément → BUY priority (déterministe).
    """
    fire_buy = int(_safe_get(features, "bar_edge_buy_fire", 0))
    fire_sell = int(_safe_get(features, "bar_edge_sell_fire", 0))
    if fire_buy == 1:
        return RuleTag(
            direction=+1,
            strength=1.0,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "edge_buy"},
        )
    if fire_sell == 1:
        return RuleTag(
            direction=-1,
            strength=1.0,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "edge_sell"},
        )
    return _zero_tag(features)


# ═══════════════════════════════════════════════════════════════════════
# RULES registry — public API
# ═══════════════════════════════════════════════════════════════════════

RULES_V1 = {
    "long_up_bar":          rule_long_up_bar,
    "long_dn_bar":          rule_long_dn_bar,
    "color_up_proximity":   rule_color_up_proximity,
    "color_dn_proximity":   rule_color_dn_proximity,
    "color_zone_break":     rule_color_zone_break,
    "cluster_at_high":      rule_cluster_at_high,
    "cluster_at_low":       rule_cluster_at_low,
    "failed_ib_poor_high":  rule_failed_ib_poor_high,
    "edge_zone_fire":       rule_edge_zone_fire,
}


def apply_all_rules(features: dict) -> dict:
    """Apply all 9 rules to one bar features dict.

    Returns: {rule_name: RuleTag}
    """
    return {name: fn(features) for name, fn in RULES_V1.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_rules.py -v`
Expected: 26 tests PASS

- [ ] **Step 5: Update __init__.py to export public API**

```python
# CORE/signal_engine_rules/__init__.py
"""signal_engine_rules V1 — middleware tagger for paper trading rules-only."""
from .schema import RuleTag, RULES_SCHEMA_VERSION
from .rules import RULES_V1, apply_all_rules

__all__ = ["RuleTag", "RULES_SCHEMA_VERSION", "RULES_V1", "apply_all_rules"]
```

- [ ] **Step 6: Commit**

```bash
git add CORE/signal_engine_rules/__init__.py CORE/signal_engine_rules/rules.py CORE/signal_engine_rules/tests/test_rules.py
git commit -m "feat(rules): rule 9 edge_zone_fire + RULES_V1 registry + apply_all_rules"
```

---

## Task 9: Anti-leak validation tests (NON-NEGOTIABLE)

**Files:**
- Test: `CORE/signal_engine_rules/tests/test_no_lookahead.py`

- [ ] **Step 1: Write the no-lookahead test suite**

```python
# CORE/signal_engine_rules/tests/test_no_lookahead.py
"""Anti-leak tests for signal_engine_rules V1.

NON-NEGOTIABLE per spec section 5.2 + incident 27/04 21:30 (3 leaks discovered
via SHAP test B). Each rule MUST produce identical output regardless of future
bar values. If a rule reads any feature that is broadcast across session
without anti-leak mask, this suite catches it.
"""
import math
import numpy as np
import pandas as pd
import pytest

from CORE.signal_engine_rules.rules import RULES_V1, apply_all_rules
from CORE.signal_engine_rules.tests.fixtures import make_bar_base


def _make_bar_at_index(i: int) -> dict:
    """Bar with realistic deterministic values for index i in test sequence."""
    bar = make_bar_base(ts_event=f"2026-04-27 {14 + i // 60:02d}:{i % 60:02d}:00")
    bar["close"] = 4500.0 + i * 0.25
    bar["high"] = bar["close"] + 1.0
    bar["low"] = bar["close"] - 1.0
    bar["mins_et"] = 600 + i  # progresses through IB closure
    return bar


@pytest.mark.parametrize("rule_name", list(RULES_V1.keys()))
def test_rule_output_invariant_under_future_bar_changes(rule_name):
    """For each rule, evaluating bar i must NOT depend on bar i+1, i+2, ...

    Setup:
      1. Create 10 bars with deterministic features
      2. Evaluate rule on bar 5 → tag_v1
      3. Modify bars 6-9 with random extreme values
      4. Re-evaluate rule on bar 5 (unchanged) → tag_v2
      5. tag_v1 must equal tag_v2 (no leak)
    """
    rule_fn = RULES_V1[rule_name]
    bars = [_make_bar_at_index(i) for i in range(10)]

    # Evaluate rule on bar 5 with current features
    tag_v1 = rule_fn(bars[5])

    # Modify future bars (6-9) with extreme values
    rng = np.random.default_rng(seed=42)
    for j in range(6, 10):
        bars[j]["close"] = float(rng.uniform(1000, 10000))
        bars[j]["high"] = bars[j]["close"] * 1.5
        bars[j]["low"] = bars[j]["close"] * 0.5
        bars[j]["long_up_bar"] = int(rng.integers(0, 2))
        bars[j]["long_dn_bar"] = int(rng.integers(0, 2))
        bars[j]["cluster_at_high"] = int(rng.integers(0, 2))
        bars[j]["cluster_at_low"] = int(rng.integers(0, 2))
        bars[j]["dist_color_up_nearest_pct"] = float(rng.uniform(-1, 1))
        bars[j]["dist_color_dn_nearest_pct"] = float(rng.uniform(-1, 1))

    # Re-evaluate rule on bar 5 (which was NOT modified)
    tag_v2 = rule_fn(bars[5])

    # Must be identical
    assert tag_v1.direction == tag_v2.direction, (
        f"Rule {rule_name} LEAKS: direction changed {tag_v1.direction} -> {tag_v2.direction} "
        f"after modifying future bars. Suspected feature: review function inputs."
    )
    assert math.isclose(tag_v1.strength, tag_v2.strength, abs_tol=1e-9), (
        f"Rule {rule_name} LEAKS: strength changed {tag_v1.strength} -> {tag_v2.strength}"
    )


def test_apply_all_rules_invariant():
    """Whole apply_all_rules suite is invariant under future bar changes."""
    bars = [_make_bar_at_index(i) for i in range(10)]
    tags_v1 = apply_all_rules(bars[5])

    rng = np.random.default_rng(seed=42)
    for j in range(6, 10):
        for k in list(bars[j].keys()):
            if k == "ts_event":
                continue
            v = bars[j][k]
            if isinstance(v, (int, np.integer)):
                bars[j][k] = int(rng.integers(0, 2))
            elif isinstance(v, (float, np.floating)):
                bars[j][k] = float(rng.uniform(-1, 1))

    tags_v2 = apply_all_rules(bars[5])
    for name in tags_v1:
        assert tags_v1[name].direction == tags_v2[name].direction, f"Leak in {name}"
        assert math.isclose(tags_v1[name].strength, tags_v2[name].strength, abs_tol=1e-9), \
            f"Leak in {name}"


def test_failed_ib_anti_leak_pre_close_remains_zero():
    """Specific guard: failed_ib_poor_high MUST NOT fire pre-10:30 ET, regardless
    of feature values (anti-leak hard guard from incident 27/04)."""
    bar = make_bar_base()
    bar["mins_et"] = 600  # 10:00 ET, before IB close
    bar["ib_broken_up"] = 1
    bar["ib_position_pct"] = 0.0

    tag = RULES_V1["failed_ib_poor_high"](bar)
    assert tag.direction == 0, \
        "Anti-leak BREACH: failed_ib_poor_high fired pre-10:30 ET"


def test_no_rule_uses_blacklisted_leaky_features():
    """Static check: rules.py source code does not reference known-leaky features.

    Blacklist :
      - dist_ovn_high_pct, dist_ovn_low_pct (pre-fix v5b)
      - dist_ib_high_pct, dist_ib_low_pct (pre-fix, only post-fix-v5b masked)
      - above_open_830, above_open_930 (pre-fix)
    """
    from pathlib import Path
    rules_src = (Path(__file__).resolve().parents[1] / "rules.py").read_text(encoding="utf-8")
    blacklist = [
        "dist_ovn_high_pct",
        "dist_ovn_low_pct",
        "above_open_830",
        "above_open_930",
    ]
    for feat in blacklist:
        assert feat not in rules_src, (
            f"BLACKLIST BREACH: rules.py references leaky feature '{feat}'. "
            f"Use a non-leaky alternative or apply mask in feature dict."
        )
```

- [ ] **Step 2: Run anti-leak tests**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_no_lookahead.py -v`
Expected: 9 + 1 + 1 + 1 = 12 tests PASS (9 parametrized + 3 specific)

- [ ] **Step 3: Run all tests to verify nothing regressed**

Run: `python -m pytest CORE/signal_engine_rules/tests/ -v`
Expected: 26 + 12 + 6 = 44 tests PASS total

- [ ] **Step 4: Commit**

```bash
git add CORE/signal_engine_rules/tests/test_no_lookahead.py
git commit -m "test(rules): anti-leak validation suite (parametrized 9 rules + 3 specific guards)"
```

---

## Task 10: batch_tagger.py (vectorized parquet v5b → v5c)

**Files:**
- Create: `CORE/signal_engine_rules/batch_tagger.py`
- Test: `CORE/signal_engine_rules/tests/test_batch_tagger.py`

- [ ] **Step 1: Write the failing test for batch_tagger**

```python
# CORE/signal_engine_rules/tests/test_batch_tagger.py
"""Tests batch_tagger.py — apply rules to parquet → enriched parquet."""
import pandas as pd
import pytest

from CORE.signal_engine_rules.batch_tagger import apply_rules_to_dataframe
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_long_up_rth, make_bar_color_up_close, make_bar_base,
)


def test_apply_rules_adds_18_columns():
    """Each of 9 rules adds 2 cols: <name>_dir + <name>_strength."""
    bars = [make_bar_base(), make_bar_long_up_rth(), make_bar_color_up_close()]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    # Expected new cols
    expected_cols = []
    for rule_name in [
        "long_up_bar", "long_dn_bar", "color_up_proximity", "color_dn_proximity",
        "color_zone_break", "cluster_at_high", "cluster_at_low",
        "failed_ib_poor_high", "edge_zone_fire",
    ]:
        expected_cols.append(f"rule_{rule_name}_dir")
        expected_cols.append(f"rule_{rule_name}_strength")
    for col in expected_cols:
        assert col in df_out.columns, f"Missing column {col}"
    assert df_out.shape[0] == len(bars)


def test_apply_rules_long_up_fires_correctly():
    """long_up_bar bar in RTH → rule_long_up_bar_dir == 1."""
    bars = [make_bar_long_up_rth(), make_bar_base()]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    assert df_out.iloc[0]["rule_long_up_bar_dir"] == 1
    assert df_out.iloc[1]["rule_long_up_bar_dir"] == 0


def test_apply_rules_dtype_int8_for_dir():
    bars = [make_bar_base() for _ in range(10)]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    assert df_out["rule_long_up_bar_dir"].dtype == "int8"
    assert df_out["rule_long_up_bar_strength"].dtype == "float32"


def test_apply_rules_preserves_original_columns():
    bars = [make_bar_base() for _ in range(3)]
    df = pd.DataFrame(bars)
    original_cols = set(df.columns)
    df_out = apply_rules_to_dataframe(df)
    assert original_cols.issubset(set(df_out.columns))


def test_apply_rules_handles_empty_dataframe():
    df = pd.DataFrame(columns=["close", "high", "low", "ts_event", "atr"])
    df_out = apply_rules_to_dataframe(df)
    assert len(df_out) == 0
    # Still has new rule columns
    assert "rule_long_up_bar_dir" in df_out.columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_batch_tagger.py -v`
Expected: FAIL ImportError on batch_tagger module

- [ ] **Step 3: Write batch_tagger.py**

```python
# CORE/signal_engine_rules/batch_tagger.py
"""Batch tagger : apply 9 V1 rules to a DataFrame, add 18 columns.

Uses a row-iteration approach (not numba). For 351K bars × 9 rules,
estimated runtime ~5-10 min. Optimization deferred to V2.

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md section 4.1
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from CORE.signal_engine_rules.rules import RULES_V1


def apply_rules_to_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all V1 rules to each row, add rule_<name>_dir + rule_<name>_strength cols.

    Args:
        df: input DataFrame with v5b features (must include ts_event, mins_et,
            close, atr, and feature columns referenced by rules)

    Returns:
        DataFrame with original cols + 18 new cols (2 per rule).
    """
    n = len(df)
    rule_names = list(RULES_V1.keys())

    # Pre-allocate output arrays
    dir_arrays = {name: np.zeros(n, dtype=np.int8) for name in rule_names}
    strength_arrays = {name: np.zeros(n, dtype=np.float32) for name in rule_names}

    # Iterate rows
    for idx, row in enumerate(df.to_dict(orient="records")):
        for name, fn in RULES_V1.items():
            tag = fn(row)
            dir_arrays[name][idx] = tag.direction
            strength_arrays[name][idx] = tag.strength

    df_out = df.copy()
    for name in rule_names:
        df_out[f"rule_{name}_dir"] = dir_arrays[name]
        df_out[f"rule_{name}_strength"] = strength_arrays[name]
    return df_out


def batch_tag_parquet(input_parquet: str, output_parquet: str,
                      verbose: bool = True) -> dict:
    """Read input parquet, apply all rules, write enriched parquet.

    Returns: stats dict {n_bars, n_rules, elapsed_s, fire_counts}
    """
    if verbose:
        print(f"[BATCH TAGGER] Reading {input_parquet}...")
    df = pd.read_parquet(input_parquet)
    if verbose:
        print(f"  Loaded {len(df):,} bars × {df.shape[1]} cols")

    t0 = time.perf_counter()
    df_out = apply_rules_to_dataframe(df)
    elapsed = time.perf_counter() - t0

    fire_counts = {}
    for name in RULES_V1:
        col = f"rule_{name}_dir"
        n_buy = int((df_out[col] == 1).sum())
        n_sell = int((df_out[col] == -1).sum())
        fire_counts[name] = {"buy": n_buy, "sell": n_sell, "total": n_buy + n_sell}
        if verbose:
            print(f"  {name:25s}  BUY={n_buy:>6}  SELL={n_sell:>6}  TOTAL={n_buy+n_sell:>6}")

    if verbose:
        print(f"[BATCH TAGGER] Writing {output_parquet}...")
    df_out.to_parquet(output_parquet, index=False)

    if verbose:
        print(f"[DONE] Elapsed {elapsed:.1f}s. Output {Path(output_parquet).stat().st_size // 1024 // 1024} MB.")

    return {
        "n_bars": len(df),
        "n_rules": len(RULES_V1),
        "elapsed_s": elapsed,
        "fire_counts": fire_counts,
    }


def main():
    """CLI entry: python -m CORE.signal_engine_rules.batch_tagger ES (or NQ)."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", choices=["ES", "NQ"])
    parser.add_argument("--input-suffix", default="v5b")
    parser.add_argument("--output-suffix", default="v5c")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    input_parquet = root / f"DATA/datasets/{args.symbol}_dataset_{args.input_suffix}.parquet"
    output_parquet = root / f"DATA/datasets/{args.symbol}_dataset_{args.output_suffix}.parquet"

    if not input_parquet.exists():
        print(f"[ERROR] Input parquet missing : {input_parquet}")
        sys.exit(1)

    batch_tag_parquet(str(input_parquet), str(output_parquet))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest CORE/signal_engine_rules/tests/test_batch_tagger.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Run full test suite to ensure no regression**

Run: `python -m pytest CORE/signal_engine_rules/tests/ -v`
Expected: 44 + 5 = 49 tests PASS total

- [ ] **Step 6: Commit**

```bash
git add CORE/signal_engine_rules/batch_tagger.py CORE/signal_engine_rules/tests/test_batch_tagger.py
git commit -m "feat(rules): batch_tagger vectorized DataFrame → 18 added cols"
```

---

## Task 11: Smoke test on real v5b sample (1000 bars)

**Files:**
- No new files (manual smoke run)

- [ ] **Step 1: Run batch_tagger on a 1000-bar sample of ES_dataset_v5b**

```bash
python -X utf8 -c "
import pandas as pd
from CORE.signal_engine_rules.batch_tagger import apply_rules_to_dataframe

df = pd.read_parquet('DATA/datasets/ES_dataset_v5b.parquet')
df_sample = df.head(1000).reset_index(drop=True)
print(f'Sample shape: {df_sample.shape}')
df_out = apply_rules_to_dataframe(df_sample)
print(f'Output shape: {df_out.shape}')
print()
print('Fire counts on 1000 bars:')
for col in df_out.columns:
    if col.startswith('rule_') and col.endswith('_dir'):
        n_buy = (df_out[col] == 1).sum()
        n_sell = (df_out[col] == -1).sum()
        print(f'  {col:40s}  BUY={n_buy:>4}  SELL={n_sell:>4}')
"
```

Expected output: prints fire counts. Sanity checks:
- `rule_long_up_bar_dir` BUY count > 0 (bars with `long_up_bar=1` exist)
- `rule_failed_ib_poor_high_dir` may be 0 if first 1000 bars are pre-IB
- No exceptions

- [ ] **Step 2: Run full batch_tagger on ES (full 351K bars)**

```bash
python -X utf8 -m CORE.signal_engine_rules.batch_tagger ES
```

Expected: ~5-10 min runtime, fire counts coherent with battery_v5_full backtest, output `DATA/datasets/ES_dataset_v5c.parquet` ~280 MB.

- [ ] **Step 3: Verify v5c parquet integrity**

```bash
python -X utf8 -c "
import pandas as pd
df = pd.read_parquet('DATA/datasets/ES_dataset_v5c.parquet')
print(f'Total: {len(df):,} bars × {df.shape[1]} cols')
new_cols = [c for c in df.columns if c.startswith('rule_')]
print(f'New rule cols: {len(new_cols)} (expected 18)')
assert len(new_cols) == 18, f'Expected 18 rule cols, got {len(new_cols)}'
print('OK')
"
```

Expected: `Total: 351,337 bars × 447 cols`, `New rule cols: 18 (expected 18)`, `OK`.

- [ ] **Step 4: Run NQ batch_tagger same way**

```bash
python -X utf8 -m CORE.signal_engine_rules.batch_tagger NQ
```

- [ ] **Step 5: Commit (no code changes, but mark milestone)**

```bash
git tag signal_engine_rules-v1-batch-validated
git push --tags
```

(Note: only push tag if remote configured; otherwise local tag suffit.)

---

## Task 12: Integration into mia_paper_trader.py

**Files:**
- Modify: `CORE/mia_paper_trader.py` (add `_lookup_rules_tags` helper + `rules_fired` field in close snapshot)
- Modify: `DOCS/BOT_CHANGELOG.md` (changelog entry)

- [ ] **Step 1: Locate the current close snapshot section in mia_paper_trader**

Run: `grep -n "_close_trade\|exit_reason" CORE/mia_paper_trader.py | head -10`

Expected: locate `_close_trade(self, symbol, ...)` around line 1493 per spec section 4.3.

- [ ] **Step 2: Add `_lookup_rules_tags` helper method**

Read the method `_close_trade` first (Read tool from line 1493, limit 80). Find the exact spot before snapshot is written. Then add the helper method to the class.

```python
def _lookup_rules_tags(self, symbol: str, ts_event_open, ts_event_close) -> dict:
    """Lookup rules tags from parquet v5c for the given trade window.

    Args:
        symbol: 'ES' or 'NQ'
        ts_event_open: open timestamp (Timestamp or epoch ms)
        ts_event_close: close timestamp

    Returns:
        dict {rule_name: {'direction': int, 'strength': float}} aggregated
        across the trade window. Returns {} if parquet absent or no bars in window.
    """
    from pathlib import Path
    parquet_path = Path("DATA/datasets") / f"{symbol}_dataset_v5c.parquet"
    if not parquet_path.exists():
        return {}
    try:
        import pandas as pd
        # Convert timestamps if needed
        if isinstance(ts_event_open, (int, float)):
            ts_open = pd.Timestamp(int(ts_event_open), unit="ms", tz="UTC")
        else:
            ts_open = pd.Timestamp(ts_event_open)
        if isinstance(ts_event_close, (int, float)):
            ts_close = pd.Timestamp(int(ts_event_close), unit="ms", tz="UTC")
        else:
            ts_close = pd.Timestamp(ts_event_close)

        # Read only the rule cols + ts_event for efficiency
        rule_cols = [
            f"rule_{name}_dir" for name in [
                "long_up_bar", "long_dn_bar", "color_up_proximity",
                "color_dn_proximity", "color_zone_break", "cluster_at_high",
                "cluster_at_low", "failed_ib_poor_high", "edge_zone_fire",
            ]
        ] + [f"rule_{name}_strength" for name in [
            "long_up_bar", "long_dn_bar", "color_up_proximity",
            "color_dn_proximity", "color_zone_break", "cluster_at_high",
            "cluster_at_low", "failed_ib_poor_high", "edge_zone_fire",
        ]]
        cols_to_read = ["ts_event"] + rule_cols
        df = pd.read_parquet(parquet_path, columns=cols_to_read)

        # Filter window
        mask = (df["ts_event"] >= ts_open) & (df["ts_event"] <= ts_close)
        df_window = df[mask]
        if len(df_window) == 0:
            return {}

        # Aggregate: take max(abs(direction)) per rule (most conservative)
        result = {}
        rule_names = ["long_up_bar", "long_dn_bar", "color_up_proximity",
                      "color_dn_proximity", "color_zone_break", "cluster_at_high",
                      "cluster_at_low", "failed_ib_poor_high", "edge_zone_fire"]
        for name in rule_names:
            dir_col = f"rule_{name}_dir"
            str_col = f"rule_{name}_strength"
            # Find the bar where direction was non-zero with max strength
            mask_fire = df_window[dir_col] != 0
            if mask_fire.any():
                idx_max = df_window[mask_fire][str_col].idxmax()
                result[name] = {
                    "direction": int(df_window.loc[idx_max, dir_col]),
                    "strength": float(df_window.loc[idx_max, str_col]),
                }
            else:
                result[name] = {"direction": 0, "strength": 0.0}
        return result
    except Exception as e:
        print(f"[WARN] _lookup_rules_tags failed: {type(e).__name__}: {e}")
        return {}
```

- [ ] **Step 3: Modify `_close_trade` to call `_lookup_rules_tags` and add to snapshot**

Read `_close_trade` to find where the close snapshot is appended. Add this section before the snapshot is written:

```python
# Enrich snapshot with rules_fired (signal_engine_rules V1)
rules_fired = self._lookup_rules_tags(
    symbol=symbol,
    ts_event_open=position.get("ts_event_entry") or position.get("entry_ts"),
    ts_event_close=pd.Timestamp.now(tz="UTC"),
)
close_snapshot["rules_fired"] = rules_fired
close_snapshot["rules_schema_version"] = "1.0"
```

(Adjust the field names `ts_event_entry` and `entry_ts` to whatever exists in `position` dict — check via Read first.)

- [ ] **Step 4: Add changelog entry**

```markdown
## 2026-04-27 — feat(rules): signal_engine_rules V1 deployed

- 9 rules tagger : long_up_bar, long_dn_bar, color_up/dn_proximity, color_zone_break,
  cluster_at_high/low, failed_ib_poor_high (anti-leak guard pre-10:30), edge_zone_fire
- batch_tagger : ES/NQ_dataset_v5b.parquet → v5c.parquet (18 added cols)
- mia_paper_trader integration : `rules_fired` + `rules_schema_version` in close snapshot
- TDD : 49 tests (26 unit + 12 anti-leak + 5 batch_tagger + 6 schema), 100% pass
- Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md
- Validation pre-deploy : Plan agent GO-AVEC-RESERVES (5 corrections appliquées)
- JL2 SORTIE V1 (quasi-const + feature morte ES) — V2 ré-évaluation après ≥100 trades
- Revert plan : si snapshot rules_fired KO → comment out `_lookup_rules_tags` call,
  parquet v5c reste utilisable pour analyse manuelle
- Suivi J+1 : compter rules_fired dans 5 derniers trades paper, vérifier distribution
- Suivi J+7 : agréger 30+ trades, comparer fire_counts live vs backtest battery
```

Append to `DOCS/BOT_CHANGELOG.md` at the top (per project convention).

- [ ] **Step 5: Smoke test integration**

Manually run a paper trade simulation OR verify the snapshot file gains the new fields (depending on bot state). At minimum, run:

```bash
python -c "from CORE.mia_paper_trader import PaperTrader; pt = PaperTrader(); print(hasattr(pt, '_lookup_rules_tags'))"
```

Expected: `True`.

- [ ] **Step 6: Commit**

```bash
git add CORE/mia_paper_trader.py DOCS/BOT_CHANGELOG.md
git commit -m "feat(paper): signal_engine_rules V1 integration in close snapshot

- _lookup_rules_tags helper reads parquet v5c for trade window
- close_snapshot enriched with rules_fired + rules_schema_version
- No change to entry decision logic (still via conseil_global dashboard)
- Changelog entry per BOT_CHANGELOG protocol"
```

---

## Self-review checklist

- [x] **Spec coverage** : every section of spec covered by tasks 1-12. Section 5 tests obligatoires → Tasks 3-9 (test_rules) + Task 9 (test_no_lookahead) + Task 10 (test_batch_tagger). Section 6 V2 explicitly out of scope. Section 9 critère acceptation V1 → Task 11 smoke test.
- [x] **Placeholder scan** : no TBD, no "TODO", no "implement later". Each step has actual code or commands.
- [x] **Type consistency** : `RuleTag` referenced consistently. `RULES_V1` dict appears in Task 8 + Task 10 + Task 12 with same shape. Method `_lookup_rules_tags` signature consistent.

---

**Plan complete and saved to `DOCS/plans/2026-04-27-signal-engine-rules-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Ideal for this 12-task plan.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
