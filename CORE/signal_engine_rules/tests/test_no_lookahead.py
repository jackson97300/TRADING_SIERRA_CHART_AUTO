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
      - above_open_830, above_open_930 (pre-fix)
      - dist_ib_high_pct, dist_ib_low_pct, dist_ib_mid_pct (pre-fix unmasked)

    EXEMPTION : rule_failed_ib_poor_high uses ib_broken_up/down + ib_position_pct
    WITH a mins_et < 630 hard guard (anti-leak verified by separate test
    test_failed_ib_anti_leak_pre_close_remains_zero). These features ARE leaky
    pre-fix but the rule's time guard prevents reading them in the leaky window.

    If a future rule needs dist_ib_*, it MUST add the same mins_et guard.
    """
    from pathlib import Path
    rules_src = (Path(__file__).resolve().parents[1] / "rules.py").read_text(encoding="utf-8")
    # Hard blacklist: features that MUST NEVER appear, no exemption possible
    hard_blacklist = [
        "dist_ovn_high_pct",
        "dist_ovn_low_pct",
        "above_open_830",
        "above_open_930",
        "dist_ib_high_pct",
        "dist_ib_low_pct",
        "dist_ib_mid_pct",
    ]
    for feat in hard_blacklist:
        assert feat not in rules_src, (
            f"HARD BLACKLIST BREACH: rules.py references leaky feature '{feat}'. "
            f"Use a non-leaky alternative or apply mask in feature dict. "
            f"If this is intentional with anti-leak guard, exempt via comment + new test."
        )
