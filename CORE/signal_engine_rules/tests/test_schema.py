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
