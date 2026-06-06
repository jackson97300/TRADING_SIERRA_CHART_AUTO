# SIM4/research/narrative_engine_v1.py
"""Narrative classifiers v1 for Phase A.0 backtest.

3 narratives MVP (see design doc section 6) :
- TREND_DAY (up/down by sign)
- RANGE_REJECTION
- FAILED_BREAKOUT_REVERSAL

Each classifier is a PURE FUNCTION (bar dict -> (label, confidence)).
NO side effects, NO state.
"""

from typing import Any


NARRATIVE_NONE = "NONE"
NARRATIVE_TREND_DAY_UP = "TREND_DAY_UP"
NARRATIVE_TREND_DAY_DOWN = "TREND_DAY_DOWN"
NARRATIVE_RANGE_REJECTION = "RANGE_REJECTION"
NARRATIVE_FAILED_BREAKOUT_REVERSAL = "FAILED_BREAKOUT_REVERSAL"

# Open types triggering TREND_DAY (from CORE/game_changers.py)
TREND_DAY_OPEN_TYPES = {1, 2}  # Open Drive, Open Range Reject

# Profile shapes triggering TREND_DAY (P-shape, ascending)
TREND_DAY_PROFILE_SHAPES = {1, 2}

# Minimum |cvd_session| to claim clear directional buyers/sellers
TREND_DAY_CVD_MIN = 200.0

TREND_DAY_INITIAL_CONFIDENCE = 0.7


def classify_trend_day(bar: dict[str, Any]) -> tuple[str, float]:
    """Classify a bar as TREND_DAY_UP / TREND_DAY_DOWN / NONE.

    Triggers (ALL required) :
        open_type in {1, 2}
        profile_shape in {1, 2}
        |cvd_session| >= TREND_DAY_CVD_MIN

    Direction by cvd_session sign.
    """
    open_type = bar.get("open_type")
    profile_shape = bar.get("profile_shape")
    cvd = bar.get("cvd_session")

    if open_type not in TREND_DAY_OPEN_TYPES:
        return NARRATIVE_NONE, 0.0
    if profile_shape not in TREND_DAY_PROFILE_SHAPES:
        return NARRATIVE_NONE, 0.0
    if cvd is None:
        return NARRATIVE_NONE, 0.0
    try:
        cvd_f = float(cvd)
    except (TypeError, ValueError):
        return NARRATIVE_NONE, 0.0
    if abs(cvd_f) < TREND_DAY_CVD_MIN:
        return NARRATIVE_NONE, 0.0

    if cvd_f > 0:
        return NARRATIVE_TREND_DAY_UP, TREND_DAY_INITIAL_CONFIDENCE
    return NARRATIVE_TREND_DAY_DOWN, TREND_DAY_INITIAL_CONFIDENCE


# Profile shapes triggering RANGE_REJECTION (balanced, b-shape)
RANGE_PROFILE_SHAPES = {0, 3}

# day_type Normal = 0 (Dalton)
RANGE_DAY_TYPE_NORMAL = 0

# Max |cvd_session| to consider mean-reverting
RANGE_CVD_MAX = 200.0

RANGE_REJECTION_INITIAL_CONFIDENCE = 0.6


def classify_range_rejection(bar: dict[str, Any]) -> tuple[str, float]:
    """Classify a bar as RANGE_REJECTION / NONE.

    Triggers (ALL required) :
        profile_shape in {0, 3}
        inside_value_area == 1
        day_type == 0 (Normal Dalton)
        |cvd_session| < RANGE_CVD_MAX
    """
    profile_shape = bar.get("profile_shape")
    inside_va = bar.get("inside_value_area")
    day_type = bar.get("day_type")
    cvd = bar.get("cvd_session")

    if profile_shape not in RANGE_PROFILE_SHAPES:
        return NARRATIVE_NONE, 0.0
    if inside_va != 1:
        return NARRATIVE_NONE, 0.0
    if day_type != RANGE_DAY_TYPE_NORMAL:
        return NARRATIVE_NONE, 0.0
    if cvd is None:
        return NARRATIVE_NONE, 0.0
    try:
        cvd_f = float(cvd)
    except (TypeError, ValueError):
        return NARRATIVE_NONE, 0.0
    if abs(cvd_f) >= RANGE_CVD_MAX:
        return NARRATIVE_NONE, 0.0

    return NARRATIVE_RANGE_REJECTION, RANGE_REJECTION_INITIAL_CONFIDENCE
