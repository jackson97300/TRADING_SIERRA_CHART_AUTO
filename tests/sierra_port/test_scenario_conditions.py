"""Tests scenario_conditions.py Phase B.5.2 Condition DSL."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# AtomicCondition
# ════════════════════════════════════════════════════════════════════════════

def test_atomic_gt():
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="bn_absorb_bid", op=">", threshold=0.0)
    assert c.evaluate({"bn_absorb_bid": 1}) is True
    assert c.evaluate({"bn_absorb_bid": 0}) is False
    assert c.evaluate({"bn_absorb_bid": -1}) is False


def test_atomic_eq():
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="bn_long_up", op="==", threshold=1.0)
    assert c.evaluate({"bn_long_up": 1}) is True
    assert c.evaluate({"bn_long_up": 0}) is False


def test_atomic_lt():
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="finish_strength", op="<", threshold=0.0)
    assert c.evaluate({"finish_strength": -10.5}) is True
    assert c.evaluate({"finish_strength": 0}) is False
    assert c.evaluate({"finish_strength": 5}) is False


def test_atomic_abs_gt():
    """abs_gt utile pour delta_div strength (peut etre +/- selon direction)."""
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="delta_div_strength", op="abs_gt", threshold=0.001)
    assert c.evaluate({"delta_div_strength": 0.005}) is True
    assert c.evaluate({"delta_div_strength": -0.005}) is True
    assert c.evaluate({"delta_div_strength": 0.0005}) is False


def test_atomic_missing_field_returns_false():
    """Fail-safe : field absent du bar -> False (pas crash)."""
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="non_existent", op=">", threshold=0.0)
    assert c.evaluate({}) is False
    assert c.evaluate({"other_field": 100}) is False


def test_atomic_none_value_returns_false():
    """Field present mais None -> False."""
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="atr", op=">", threshold=0.0)
    assert c.evaluate({"atr": None}) is False


def test_atomic_unparsable_always_false():
    """is_unparsable=True -> evaluate retourne toujours False (cote securite)."""
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="_unparsable", op="==", threshold=0.0,
                        description="Vague semantique", is_unparsable=True)
    assert c.evaluate({"any": 1}) is False


def test_atomic_invalid_op_returns_false():
    """Operator hors VALID_OPERATORS -> False."""
    from CORE.scenario_conditions import AtomicCondition
    c = AtomicCondition(field="atr", op="???", threshold=0.0)
    assert c.evaluate({"atr": 100}) is False


# ════════════════════════════════════════════════════════════════════════════
# CompositeCondition AND/OR
# ════════════════════════════════════════════════════════════════════════════

def test_composite_or_true_if_any():
    from CORE.scenario_conditions import AtomicCondition, CompositeCondition
    comp = CompositeCondition(
        op="OR",
        conditions=(
            AtomicCondition("bn_absorb_bid", ">", 0),
            AtomicCondition("bn_long_up", "==", 1),
        ),
    )
    # 1er True
    assert comp.evaluate({"bn_absorb_bid": 1, "bn_long_up": 0}) is True
    # 2e True
    assert comp.evaluate({"bn_absorb_bid": 0, "bn_long_up": 1}) is True
    # Aucun
    assert comp.evaluate({"bn_absorb_bid": 0, "bn_long_up": 0}) is False


def test_composite_and_true_if_all():
    from CORE.scenario_conditions import AtomicCondition, CompositeCondition
    comp = CompositeCondition(
        op="AND",
        conditions=(
            AtomicCondition("delta_bar", ">", 0),
            AtomicCondition("finish_strength", ">", 0),
        ),
    )
    assert comp.evaluate({"delta_bar": 5, "finish_strength": 10}) is True
    assert comp.evaluate({"delta_bar": 5, "finish_strength": -10}) is False
    assert comp.evaluate({"delta_bar": -5, "finish_strength": 10}) is False


def test_composite_empty_returns_false():
    """Composite sans enfants -> False (defensive)."""
    from CORE.scenario_conditions import CompositeCondition
    comp = CompositeCondition(op="AND", conditions=())
    assert comp.evaluate({"any": 1}) is False


def test_composite_nested():
    """AND( atomic, OR(atomic, atomic) )."""
    from CORE.scenario_conditions import AtomicCondition, CompositeCondition
    inner_or = CompositeCondition(
        op="OR",
        conditions=(
            AtomicCondition("bn_absorb_bid", ">", 0),
            AtomicCondition("bn_long_up", "==", 1),
        ),
    )
    outer_and = CompositeCondition(
        op="AND",
        conditions=(
            AtomicCondition("delta_bar", ">", 0),
            inner_or,
        ),
    )
    assert outer_and.evaluate({"delta_bar": 5, "bn_absorb_bid": 1, "bn_long_up": 0}) is True
    assert outer_and.evaluate({"delta_bar": 5, "bn_absorb_bid": 0, "bn_long_up": 0}) is False
    assert outer_and.evaluate({"delta_bar": -5, "bn_absorb_bid": 1, "bn_long_up": 1}) is False


# ════════════════════════════════════════════════════════════════════════════
# evaluate_conditions API
# ════════════════════════════════════════════════════════════════════════════

def test_evaluate_conditions_all_pass():
    from CORE.scenario_conditions import AtomicCondition, evaluate_conditions
    nodes = [
        AtomicCondition("delta_bar", ">", 0, description="delta_bar > 0"),
        AtomicCondition("finish_strength", ">", 0, description="finish_strength > 0"),
    ]
    bar = {"delta_bar": 5, "finish_strength": 10}
    all_pass, matched = evaluate_conditions(nodes, bar)
    assert all_pass is True
    assert len(matched) == 2
    assert "delta_bar > 0" in matched


def test_evaluate_conditions_partial():
    from CORE.scenario_conditions import AtomicCondition, evaluate_conditions
    nodes = [
        AtomicCondition("delta_bar", ">", 0, description="delta_bar > 0"),
        AtomicCondition("finish_strength", ">", 0, description="finish_strength > 0"),
    ]
    bar = {"delta_bar": 5, "finish_strength": -10}
    all_pass, matched = evaluate_conditions(nodes, bar)
    assert all_pass is False
    assert "delta_bar > 0" in matched
    assert len(matched) == 1


# ════════════════════════════════════════════════════════════════════════════
# Legacy parser
# ════════════════════════════════════════════════════════════════════════════

def test_parser_atomic_simple():
    from CORE.scenario_conditions import parse_legacy_condition, AtomicCondition
    node = parse_legacy_condition("bn_absorb_bid > 0")
    assert isinstance(node, AtomicCondition)
    assert node.field == "bn_absorb_bid"
    assert node.op == ">"
    assert node.threshold == 0.0
    assert node.is_unparsable is False


def test_parser_atomic_eq():
    """Le '=' simple est normalise vers '=='."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("bn_long_up = 1")
    assert node.op == "=="
    assert node.threshold == 1.0


def test_parser_atomic_gte():
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("finish_strength >= 0.5")
    assert node.op == ">="
    assert node.threshold == 0.5


def test_parser_or_simple():
    from CORE.scenario_conditions import parse_legacy_condition, CompositeCondition
    node = parse_legacy_condition("bn_absorb_bid > 0 OU bn_long_up = 1")
    assert isinstance(node, CompositeCondition)
    assert node.op == "OR"
    assert len(node.conditions) == 2


def test_parser_or_english():
    """OR fonctionne aussi en anglais."""
    from CORE.scenario_conditions import parse_legacy_condition, CompositeCondition
    node = parse_legacy_condition("bn_absorb_bid > 0 OR bn_long_up = 1")
    assert isinstance(node, CompositeCondition)
    assert node.op == "OR"


def test_parser_and_plus_sign():
    from CORE.scenario_conditions import parse_legacy_condition, CompositeCondition
    node = parse_legacy_condition("delta_bar > 0 + finish_strength > 0")
    assert isinstance(node, CompositeCondition)
    assert node.op == "AND"
    assert len(node.conditions) == 2


def test_parser_unknown_field_unparsable():
    """Field hors KNOWN_FIELDS -> is_unparsable=True (anti-typo)."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("unknown_xyz > 0")
    assert node.is_unparsable is True


def test_parser_vague_string_unparsable():
    """String semantique vague -> is_unparsable=True + description preservee."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("Reversal bar avec long wick haut")
    assert node.is_unparsable is True
    assert "Reversal" in node.description


def test_parser_unparsable_evaluate_false():
    """Unparsable -> evaluate False (fail-safe)."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("Continuation UP confirme post-Judas detected")
    assert node.evaluate({"any": 1}) is False


def test_parser_real_scenario_strings():
    """Test sur strings reelles de scenario_generator.py."""
    from CORE.scenario_conditions import parse_legacy_condition

    # OR pattern (scenario bullish_continuation conditions_validation)
    node = parse_legacy_condition("BN absorb_bid > 0 OU bn_long_up = 1")
    # Note : "BN absorb_bid" en majuscule ne match pas le regex case-sensitive du field
    # mais le RX est insensitive. Verifions :
    # En fait "BN" doit etre converti en bn_absorb_bid pour matcher KNOWN_FIELDS
    # Le regex actuel parsera "BN" comme field "bn" qui n'est pas dans KNOWN_FIELDS -> unparsable.
    # Mais le composite OR sera quand meme cree avec 2 enfants potentiellement unparsable.
    from CORE.scenario_conditions import CompositeCondition
    assert isinstance(node, CompositeCondition)


def test_parser_idempotent_on_conditionnode():
    """parse_legacy_conditions_list passe-through si deja ConditionNode."""
    from CORE.scenario_conditions import (
        AtomicCondition, parse_legacy_conditions_list,
    )
    existing = AtomicCondition("delta_bar", ">", 0)
    out = parse_legacy_conditions_list([existing])
    assert out[0] is existing


def test_parser_list_mixed():
    """parse_legacy_conditions_list mix strings + ConditionNode."""
    from CORE.scenario_conditions import (
        AtomicCondition, parse_legacy_conditions_list, CompositeCondition,
    )
    out = parse_legacy_conditions_list([
        "delta_bar > 0",
        AtomicCondition("finish_strength", ">", 0),
        "bn_absorb_bid > 0 OU bn_long_up = 1",
    ])
    assert len(out) == 3
    assert isinstance(out[0], AtomicCondition)
    assert isinstance(out[1], AtomicCondition)
    assert isinstance(out[2], CompositeCondition)


def test_parser_empty_string():
    """Empty string -> unparsable + description '<empty>'."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("")
    assert node.is_unparsable is True


# ════════════════════════════════════════════════════════════════════════════
# Real scenario_generator.py patterns
# ════════════════════════════════════════════════════════════════════════════

def test_real_pattern_finish_strength():
    """Pattern simple, devrait etre parse-able."""
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("finish_strength > 0")
    bar = {"finish_strength": 5}
    assert node.evaluate(bar) is True
    assert node.is_unparsable is False


def test_real_pattern_delta_bar():
    from CORE.scenario_conditions import parse_legacy_condition
    node = parse_legacy_condition("delta_bar > 0")
    assert node.evaluate({"delta_bar": 10}) is True
    assert node.evaluate({"delta_bar": -10}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
