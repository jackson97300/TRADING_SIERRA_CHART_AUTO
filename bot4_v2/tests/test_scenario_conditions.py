"""Tests bot4_v2/core/scenario_conditions."""
from __future__ import annotations

import pytest

from bot4_v2.core.scenario_conditions import (
    KNOWN_FIELDS,
    UNPARSABLE_FIELD,
    VALID_COMPOSITE_OPS,
    VALID_OPERATORS,
    AtomicCondition,
    CompositeCondition,
    _normalize_field_name,
    _node_repr,
    _parse_atomic,
    evaluate_conditions,
    parse_legacy_condition,
    parse_legacy_conditions_list,
)


# ============================================================
# AtomicCondition evaluation
# ============================================================

def test_atomic_gt_passes():
    c = AtomicCondition(field="delta_bar", op=">", threshold=0.0)
    assert c.evaluate({"delta_bar": 5.0}) is True


def test_atomic_gt_fails():
    c = AtomicCondition(field="delta_bar", op=">", threshold=0.0)
    assert c.evaluate({"delta_bar": -1.0}) is False


def test_atomic_gte():
    c = AtomicCondition(field="x", op=">=", threshold=5.0)
    assert c.evaluate({"x": 5.0}) is True
    assert c.evaluate({"x": 4.99}) is False


def test_atomic_lt():
    c = AtomicCondition(field="x", op="<", threshold=10.0)
    assert c.evaluate({"x": 5.0}) is True
    assert c.evaluate({"x": 10.0}) is False


def test_atomic_lte():
    c = AtomicCondition(field="x", op="<=", threshold=10.0)
    assert c.evaluate({"x": 10.0}) is True


def test_atomic_eq():
    c = AtomicCondition(field="x", op="==", threshold=1.0)
    assert c.evaluate({"x": 1.0}) is True
    assert c.evaluate({"x": 1.5}) is False


def test_atomic_neq():
    c = AtomicCondition(field="x", op="!=", threshold=0.0)
    assert c.evaluate({"x": 1.0}) is True
    assert c.evaluate({"x": 0.0}) is False


def test_atomic_abs_lt():
    c = AtomicCondition(field="x", op="abs_lt", threshold=3.0)
    assert c.evaluate({"x": 2.0}) is True
    assert c.evaluate({"x": -2.0}) is True
    assert c.evaluate({"x": 4.0}) is False


def test_atomic_abs_gt():
    c = AtomicCondition(field="x", op="abs_gt", threshold=3.0)
    assert c.evaluate({"x": 4.0}) is True
    assert c.evaluate({"x": -4.0}) is True
    assert c.evaluate({"x": 2.0}) is False


def test_atomic_missing_field_returns_false():
    """Field absent du bar -> False fail-safe."""
    c = AtomicCondition(field="missing", op=">", threshold=0.0)
    assert c.evaluate({"other": 5.0}) is False


def test_atomic_none_value_returns_false():
    c = AtomicCondition(field="x", op=">", threshold=0.0)
    assert c.evaluate({"x": None}) is False


def test_atomic_non_numeric_value_returns_false():
    c = AtomicCondition(field="x", op=">", threshold=0.0)
    assert c.evaluate({"x": "string_not_castable"}) is False


def test_atomic_invalid_op_returns_false():
    c = AtomicCondition(field="x", op="invalid_op", threshold=0.0)
    assert c.evaluate({"x": 5.0}) is False


def test_atomic_unparsable_returns_false():
    """is_unparsable=True -> evaluate=False (anti VALIDATION_MISS)."""
    c = AtomicCondition(
        field=UNPARSABLE_FIELD, op="==", threshold=0.0,
        description="vague string",
        is_unparsable=True,
    )
    assert c.evaluate({"any": 1}) is False


def test_atomic_frozen():
    """Frozen dataclass (immutable)."""
    from dataclasses import FrozenInstanceError
    c = AtomicCondition(field="x", op=">", threshold=0.0)
    with pytest.raises(FrozenInstanceError):
        c.field = "modified"  # type: ignore


# ============================================================
# CompositeCondition AND/OR
# ============================================================

def test_composite_and_all_pass():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op=">", threshold=0.0)
    comp = CompositeCondition(conditions=(a, b), op="AND")
    assert comp.evaluate({"x": 5.0, "y": 3.0}) is True


def test_composite_and_one_fails():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op=">", threshold=0.0)
    comp = CompositeCondition(conditions=(a, b), op="AND")
    assert comp.evaluate({"x": 5.0, "y": -1.0}) is False


def test_composite_or_one_pass():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op=">", threshold=0.0)
    comp = CompositeCondition(conditions=(a, b), op="OR")
    assert comp.evaluate({"x": 5.0, "y": -1.0}) is True


def test_composite_or_all_fail():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op=">", threshold=0.0)
    comp = CompositeCondition(conditions=(a, b), op="OR")
    assert comp.evaluate({"x": -1.0, "y": -1.0}) is False


def test_composite_invalid_op_returns_false():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    comp = CompositeCondition(conditions=(a,), op="XOR")
    assert comp.evaluate({"x": 5.0}) is False


def test_composite_empty_conditions_returns_false():
    """Pas de conditions -> False fail-safe."""
    comp = CompositeCondition(conditions=(), op="AND")
    assert comp.evaluate({"x": 5.0}) is False


def test_composite_nested():
    """Composite recursif : (a AND (b OR c))."""
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op=">", threshold=0.0)
    c = AtomicCondition(field="z", op=">", threshold=0.0)
    inner = CompositeCondition(conditions=(b, c), op="OR")
    outer = CompositeCondition(conditions=(a, inner), op="AND")
    assert outer.evaluate({"x": 5.0, "y": -1.0, "z": 3.0}) is True
    assert outer.evaluate({"x": 5.0, "y": -1.0, "z": -1.0}) is False


# ============================================================
# evaluate_conditions API
# ============================================================

def test_evaluate_conditions_all_pass():
    nodes = [
        AtomicCondition(field="x", op=">", threshold=0.0, description="x>0"),
        AtomicCondition(field="y", op=">", threshold=0.0, description="y>0"),
    ]
    all_pass, matched = evaluate_conditions(nodes, {"x": 5.0, "y": 3.0})
    assert all_pass is True
    assert len(matched) == 2
    assert "x>0" in matched
    assert "y>0" in matched


def test_evaluate_conditions_partial():
    nodes = [
        AtomicCondition(field="x", op=">", threshold=0.0),
        AtomicCondition(field="y", op=">", threshold=0.0),
    ]
    all_pass, matched = evaluate_conditions(nodes, {"x": 5.0, "y": -1.0})
    assert all_pass is False
    assert len(matched) == 1


def test_evaluate_conditions_empty_list():
    """Empty -> all_pass=True (vide est satisfait par defaut)."""
    all_pass, matched = evaluate_conditions([], {"x": 5.0})
    assert all_pass is True
    assert matched == []


# ============================================================
# _node_repr utility
# ============================================================

def test_node_repr_atomic():
    c = AtomicCondition(field="x", op=">", threshold=0.0)
    assert _node_repr(c) == "x > 0.0"


def test_node_repr_composite():
    a = AtomicCondition(field="x", op=">", threshold=0.0)
    b = AtomicCondition(field="y", op="<", threshold=10.0)
    comp = CompositeCondition(conditions=(a, b), op="AND")
    repr_str = _node_repr(comp)
    assert "AND" in repr_str
    assert "x > 0.0" in repr_str
    assert "y < 10.0" in repr_str


# ============================================================
# Parser legacy strings
# ============================================================

def test_parse_atomic_simple_gt():
    node = parse_legacy_condition("delta_bar > 0")
    assert isinstance(node, AtomicCondition)
    assert node.field == "delta_bar"
    assert node.op == ">"
    assert node.threshold == 0.0
    assert node.is_unparsable is False


def test_parse_atomic_with_trailing_description():
    """Phase B.5.2 v2 : tolere description apres pattern (regex non-greedy)."""
    node = parse_legacy_condition("delta_bar > 0 sur la bar du rebond")
    assert isinstance(node, AtomicCondition)
    assert node.field == "delta_bar"
    assert node.op == ">"
    assert node.threshold == 0.0


def test_parse_atomic_case_insensitive_field():
    """Jackson ecrit Delta_bar, pipeline JSONL lowercase."""
    node = parse_legacy_condition("Delta_bar > 0")
    assert isinstance(node, AtomicCondition)
    assert node.field == "delta_bar"


def test_parse_atomic_multi_word_field_unparsable():
    """'BN absorb_bid' regex capture 'BN' seul (premier mot).
    'bn' non dans KNOWN_FIELDS -> is_unparsable=True (anti-typo).

    Pour multi-word, utiliser snake_case direct : 'bn_absorb_bid > 0'.
    """
    node = parse_legacy_condition("BN absorb_bid > 0")
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True


def test_parse_atomic_snake_case_field_works():
    """snake_case direct -> match KNOWN_FIELDS."""
    node = parse_legacy_condition("bn_absorb_bid > 0")
    assert isinstance(node, AtomicCondition)
    assert node.field == "bn_absorb_bid"
    assert node.is_unparsable is False


def test_parse_atomic_eq_normalized():
    """Operateur '=' -> '=='."""
    node = parse_legacy_condition("bn_long_up = 1")
    assert isinstance(node, AtomicCondition)
    assert node.op == "=="


def test_parse_atomic_negative_threshold():
    node = parse_legacy_condition("delta_bar > -5")
    assert isinstance(node, AtomicCondition)
    assert node.threshold == -5.0


def test_parse_atomic_decimal_threshold():
    node = parse_legacy_condition("range_pos_va > 0.7")
    assert isinstance(node, AtomicCondition)
    assert node.threshold == 0.7


def test_parse_or_composite():
    node = parse_legacy_condition("bn_absorb_bid > 0 OU bn_long_up = 1")
    assert isinstance(node, CompositeCondition)
    assert node.op == "OR"
    assert len(node.conditions) == 2


def test_parse_and_composite_with_et():
    node = parse_legacy_condition("delta_bar > 0 ET finish_strength > 0")
    assert isinstance(node, CompositeCondition)
    assert node.op == "AND"


def test_parse_and_composite_with_plus():
    """'+' (entoure espaces) = ET (Jackson notation)."""
    node = parse_legacy_condition("delta_bar > 0 + finish_strength > 0")
    assert isinstance(node, CompositeCondition)
    assert node.op == "AND"


def test_parse_and_composite_with_and_english():
    node = parse_legacy_condition("delta_bar > 0 AND finish_strength > 0")
    assert isinstance(node, CompositeCondition)
    assert node.op == "AND"


def test_parse_or_priority_over_and():
    """OR a priorite sur AND au split racine."""
    node = parse_legacy_condition("a > 0 ET b > 0 OU c > 0")
    # Le split OR est prioritaire -> on a OR au top
    assert isinstance(node, CompositeCondition)
    assert node.op == "OR"


# ============================================================
# Parser unparsable cases (anti VALIDATION_MISS)
# ============================================================

def test_parse_unparsable_vague_string():
    """String vague non-parsable -> AtomicCondition is_unparsable=True."""
    node = parse_legacy_condition("Le marche est haussier")
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True
    assert node.field == UNPARSABLE_FIELD


def test_parse_unparsable_unknown_field():
    """Field hors KNOWN_FIELDS -> is_unparsable (anti-typo)."""
    node = parse_legacy_condition("unknown_typo_field > 0")
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True


def test_parse_unparsable_empty_string():
    node = parse_legacy_condition("")
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True


def test_parse_unparsable_none():
    node = parse_legacy_condition(None)  # type: ignore
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True


def test_parse_unparsable_non_string():
    node = parse_legacy_condition(123)  # type: ignore
    assert isinstance(node, AtomicCondition)
    assert node.is_unparsable is True


# ============================================================
# parse_legacy_conditions_list idempotence
# ============================================================

def test_parse_list_idempotent_with_existing_nodes():
    """Si nodes deja parsees, retourne tel quel."""
    existing = AtomicCondition(field="delta_bar", op=">", threshold=0.0)
    out = parse_legacy_conditions_list([existing])
    assert out[0] is existing


def test_parse_list_mixed_strings_and_nodes():
    existing = AtomicCondition(field="delta_bar", op=">", threshold=0.0)
    out = parse_legacy_conditions_list([existing, "finish_strength > 0"])
    assert len(out) == 2
    assert out[0] is existing
    assert isinstance(out[1], AtomicCondition)


def test_parse_list_non_string_non_node():
    """Type inattendu -> is_unparsable wrapped."""
    out = parse_legacy_conditions_list([123, None, "delta_bar > 0"])
    assert all(isinstance(c, (AtomicCondition, CompositeCondition)) for c in out)
    assert out[0].is_unparsable is True
    assert out[1].is_unparsable is True
    assert out[2].is_unparsable is False


# ============================================================
# Normalize field name utility
# ============================================================

def test_normalize_field_name_simple():
    assert _normalize_field_name("Delta_bar") == "delta_bar"


def test_normalize_field_name_multi_word():
    assert _normalize_field_name("BN absorb_bid") == "bn_absorb_bid"


def test_normalize_field_name_extra_whitespace():
    assert _normalize_field_name("  delta_bar  ") == "delta_bar"


# ============================================================
# Constants / metadata
# ============================================================

def test_valid_operators_set():
    expected = {">", ">=", "<", "<=", "==", "!=", "abs_lt", "abs_gt"}
    assert VALID_OPERATORS == expected


def test_valid_composite_ops_set():
    assert VALID_COMPOSITE_OPS == {"AND", "OR"}


def test_known_fields_non_empty_and_consistent():
    """KNOWN_FIELDS doit contenir fields BN, orderflow, structure."""
    assert "bn_absorb_bid" in KNOWN_FIELDS
    assert "delta_bar" in KNOWN_FIELDS
    assert "finish_strength" in KNOWN_FIELDS
    assert "ib_complete" in KNOWN_FIELDS
    assert "open_type" in KNOWN_FIELDS
    assert "close" in KNOWN_FIELDS


def test_unparsable_field_constant():
    assert UNPARSABLE_FIELD == "_unparsable"


# ============================================================
# E2E : simulation scenario_generator legacy use case
# ============================================================

def test_e2e_scenario_validation_pattern():
    """E2E : reproduction pattern Phase B.5.2 _scenario_bullish_continuation."""
    legacy = [
        "bn_absorb_bid > 0 OU bn_long_up = 1",
        "delta_bar > 0",
        "finish_strength > 0",
    ]
    nodes = parse_legacy_conditions_list(legacy)
    assert len(nodes) == 3
    assert isinstance(nodes[0], CompositeCondition)
    assert nodes[0].op == "OR"

    # Bar avec OU=match + AND=match
    bar_all_ok = {
        "bn_absorb_bid": 1.0, "bn_long_up": 0.0,
        "delta_bar": 5.0, "finish_strength": 3.0,
    }
    all_pass, matched = evaluate_conditions(nodes, bar_all_ok)
    assert all_pass is True
    assert len(matched) == 3

    # Bar avec OU=match mais AND=fail
    bar_partial = {
        "bn_absorb_bid": 1.0, "bn_long_up": 0.0,
        "delta_bar": -1.0, "finish_strength": 3.0,
    }
    all_pass, matched = evaluate_conditions(nodes, bar_partial)
    assert all_pass is False
    assert len(matched) == 2  # OR + finish_strength only
