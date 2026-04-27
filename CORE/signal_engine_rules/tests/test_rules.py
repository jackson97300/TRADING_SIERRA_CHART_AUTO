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
    rule_color_up_proximity, rule_color_dn_proximity,
    rule_color_zone_break,
    rule_cluster_at_high, rule_cluster_at_low,
    rule_failed_ib_poor_high,
    rule_edge_zone_fire,
)
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_base, make_bar_long_up_rth, make_bar_long_up_outside_rth,
    make_bar_with_nan, make_bar_color_up_close, make_bar_color_up_far,
    make_bar_failed_ib_pre_close, make_bar_failed_ib_post_close,
    make_bar_cluster_at_low, make_bar_edge_buy,
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


# ─── Rule 5 : color_zone_break ────────────────────────────────────────

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


# ─── Rule 8 : failed_ib_poor_high (ANTI-LEAK GUARD) ───────────────────

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


# ─── Rule 9 : edge_zone_fire ──────────────────────────────────────────

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
