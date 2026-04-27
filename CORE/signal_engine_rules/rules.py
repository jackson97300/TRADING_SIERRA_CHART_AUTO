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


# Threshold constants
COLOR_PROXIMITY_THRESHOLD_PCT = 0.0005  # 0.05% threshold for color_up/dn proximity
IB_CLOSE_MINS_ET = 630  # IB window 09:30-10:30 ET → 630 = 10:30 ET

# Strength constants per rule (for ML traceability + tunable in V2)
STRENGTH_COLOR_BREAK = 0.7    # rule_color_zone_break
STRENGTH_FAILED_IB = 0.7      # rule_failed_ib_poor_high
STRENGTH_CLUSTER = 0.8        # rule_cluster_at_high / rule_cluster_at_low


# ═══════════════════════════════════════════════════════════════════════
# Rule 1 — long_up_bar (Acosta long bar continuation)
# ═══════════════════════════════════════════════════════════════════════

def rule_long_up_bar(features: dict) -> RuleTag:
    """Long up bar in US cash session → BUY continuation."""
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


# ═══════════════════════════════════════════════════════════════════════
# Rule 3 — color_up_proximity (top SHAP v5b #4)
# ═══════════════════════════════════════════════════════════════════════

def rule_color_up_proximity(features: dict) -> RuleTag:
    """BUY when price proche d'une zone color_up + delta day positif."""
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

    # BUY break : just above color_up + delta up (priority over SELL if both fire)
    if d_up is not None and -0.0005 < d_up < 0 and delta_dir > 0:
        return RuleTag(
            direction=+1,
            strength=STRENGTH_COLOR_BREAK,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"dist_color_up_pct": float(d_up), "side": "break_up"},
        )
    # SELL break : just below color_dn + delta dn
    if d_dn is not None and 0 < d_dn < 0.0005 and delta_dir < 0:
        return RuleTag(
            direction=-1,
            strength=STRENGTH_COLOR_BREAK,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"dist_color_dn_pct": float(d_dn), "side": "break_dn"},
        )
    return _zero_tag(features)


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
        strength=STRENGTH_CLUSTER,
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
        strength=STRENGTH_CLUSTER,
        version=RULES_SCHEMA_VERSION,
        fired_at=features.get("ts_event"),
        meta={"cluster_at_low": 1, "delta_day_dir": int(delta_dir)},
    )


# ═══════════════════════════════════════════════════════════════════════
# Rule 8 — failed_ib_poor_high (H3 Crabel + ANTI-LEAK guard)
# ═══════════════════════════════════════════════════════════════════════

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
            strength=STRENGTH_FAILED_IB,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "poor_high", "ib_position_pct": float(pos)},
        )
    if br_dn == 1 and -0.5 < pos < 0.5:
        return RuleTag(
            direction=+1,
            strength=STRENGTH_FAILED_IB,
            version=RULES_SCHEMA_VERSION,
            fired_at=features.get("ts_event"),
            meta={"side": "poor_low", "ib_position_pct": float(pos)},
        )
    return _zero_tag(features)


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
