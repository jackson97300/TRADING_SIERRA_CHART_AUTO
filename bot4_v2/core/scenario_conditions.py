"""Bot 4 v2 scenario_conditions — FORK CORE/scenario_conditions.py (12/06) + adaptations.

FORK Phase P2 Batch 3 (25/06/2026) :
- Isolation totale bot4_v2 (pas d'import CORE/*)
- Logger via bot4_v2.observability.telemetry (PAS stdlib logging direct)
- Module expose bot4_v2.core.scenario_conditions

Heritage V1 conserve (Phase B.5.2 v2 12/06/2026) :
- DSL ConditionNode = AtomicCondition | CompositeCondition (AND/OR)
- Parser legacy string -> arbre structure
- Anti-PATTERN_11 : chaque AtomicCondition isolee + testable unitairement
- Anti-VALIDATION_MISS : conditions vagues -> is_unparsable=True + log
- Frozen dataclass (immutabilite + hashabilite)
- Tolerance variantes case + trailing description

# Architecture

ConditionNode = AtomicCondition | CompositeCondition

AtomicCondition : feuille, evalue (field op value) sur bar dict
CompositeCondition : noeud, AND/OR sur enfants ConditionNode

# Exemple

Avant (scenario_generator.py legacy) :
    conditions_validation = [
        "BN absorb_bid > 0 OU bn_long_up = 1",
        "Delta_bar > 0 sur la bar du rebond",
        "finish_strength > 0",
    ]

Apres (via parse_legacy_condition) :
    [
        CompositeCondition("OR", [
            AtomicCondition("bn_absorb_bid", ">", 0),
            AtomicCondition("bn_long_up", "==", 1),
        ]),
        AtomicCondition("delta_bar", ">", 0),
        AtomicCondition("finish_strength", ">", 0),
    ]

# Evaluator

evaluate_conditions(nodes, bar) -> (all_pass: bool, matched_descriptions: list[str])
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)  # noqa: F841 (reserve narrative_engine + decision_router)


# ════════════════════════════════════════════════════════════════════════════
# ATOMIC CONDITION (feuille DSL)
# ════════════════════════════════════════════════════════════════════════════

VALID_OPERATORS = frozenset(
    {">", ">=", "<", "<=", "==", "!=", "abs_lt", "abs_gt"}
)

UNPARSABLE_FIELD = "_unparsable"


@dataclass(frozen=True)
class AtomicCondition:
    """Feuille : evalue (field op threshold) sur bar dict.

    field : nom clef bar dict (ex: "bn_absorb_bid", "delta_bar")
    op    : un de VALID_OPERATORS
    threshold : valeur numerique (ou str pour ==/!=)
    description : forme humaine pour UI/log
    is_unparsable : True si parser legacy n'a pas pu structurer
    """
    field: str
    op: str
    threshold: float
    description: str = ""
    is_unparsable: bool = False

    def evaluate(self, bar: dict) -> bool:
        """Retourne True si la condition est satisfaite sur le bar.

        Fail-safe : si bar manque le field OR conversion echoue OR
        is_unparsable=True -> retourne False (cote securite).
        """
        if self.is_unparsable:
            return False
        if self.op not in VALID_OPERATORS:
            return False
        v = bar.get(self.field)
        if v is None:
            return False
        try:
            v_num = float(v)
            t_num = float(self.threshold)
        except (TypeError, ValueError):
            return False
        if self.op == ">":
            return v_num > t_num
        if self.op == ">=":
            return v_num >= t_num
        if self.op == "<":
            return v_num < t_num
        if self.op == "<=":
            return v_num <= t_num
        if self.op == "==":
            return v_num == t_num
        if self.op == "!=":
            return v_num != t_num
        if self.op == "abs_lt":
            return abs(v_num) < t_num
        if self.op == "abs_gt":
            return abs(v_num) > t_num
        return False


# ════════════════════════════════════════════════════════════════════════════
# COMPOSITE CONDITION (noeud DSL)
# ════════════════════════════════════════════════════════════════════════════

VALID_COMPOSITE_OPS = frozenset({"AND", "OR"})


@dataclass(frozen=True)
class CompositeCondition:
    """Noeud : AND/OR sur enfants ConditionNode.

    conditions : tuple[ConditionNode] (frozen pour hashabilite)
    op : "AND" / "OR"
    """
    conditions: tuple
    op: str
    description: str = ""

    def evaluate(self, bar: dict) -> bool:
        """Eval AND = all() / OR = any() sur enfants."""
        if self.op not in VALID_COMPOSITE_OPS:
            return False
        if not self.conditions:
            return False
        if self.op == "AND":
            return all(c.evaluate(bar) for c in self.conditions)
        return any(c.evaluate(bar) for c in self.conditions)


ConditionNode = Union[AtomicCondition, CompositeCondition]


# ════════════════════════════════════════════════════════════════════════════
# EVALUATOR API
# ════════════════════════════════════════════════════════════════════════════


def evaluate_conditions(nodes: list, bar: dict) -> tuple:
    """Evalue une liste de ConditionNode sur un bar.

    Args:
        nodes : list[ConditionNode] (typiquement scenario.conditions_validation)
        bar : dict bar live

    Returns:
        (all_pass: bool, matched_descriptions: list[str])

    Convention : les nodes en racine sont ET-cumules (toutes les conditions
    de validation doivent etre true). Pour OR au niveau racine, encapsuler
    dans un CompositeCondition op="OR".

    matched_descriptions liste les conditions qui ont evalue True (audit).
    """
    matched = []
    all_pass = True
    for node in nodes:
        if node.evaluate(bar):
            matched.append(node.description or _node_repr(node))
        else:
            all_pass = False
    return all_pass, matched


def _node_repr(node: ConditionNode) -> str:
    """Representation courte d'un noeud pour audit/log."""
    if isinstance(node, AtomicCondition):
        return f"{node.field} {node.op} {node.threshold}"
    if isinstance(node, CompositeCondition):
        inner = " {} ".format(node.op).join(_node_repr(c) for c in node.conditions)
        return f"({inner})"
    return "<?>"


# ════════════════════════════════════════════════════════════════════════════
# LEGACY PARSER : string -> ConditionNode
# ════════════════════════════════════════════════════════════════════════════

# Whitelist fields connus du bar live_enriched (anti-typo + securite parser)
# Source : audit empirique bar 12/06 13:09 UTC + scenario_generator.py
KNOWN_FIELDS = frozenset({
    # BN signals (Phase A.3)
    "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
    "bn_absorb_ask", "bn_absorb_bid", "bn_score_raw",
    "bn_pressure_ask", "bn_pressure_bid",
    # Order flow
    "delta_bar", "delta_day", "delta_day_dir", "cvd_day", "cvd_session",
    "finish_strength", "delta_divergence", "delta_div_strength",
    # Patterns
    "sweep_high_active", "sweep_low_active",
    "sweep_high_this_bar", "sweep_low_this_bar",
    "judas_swing_active", "judas_swing_direction",
    "fvg_up_active", "fvg_dn_active",
    "has_single_prints", "single_print_above", "single_print_below",
    # VWAP / structure
    "bool_above_vwap_d", "bool_above_cur_vpoc", "bool_above_prev_vpoc",
    "vwap_triple_align", "range_pos_va", "range_extension_completed",
    # IB
    "ib_complete", "ib_broken_up", "ib_broken_down", "ib_broken_dn",
    "ib_is_narrow", "ib_is_wide", "ib_range_atr",
    # Open Type
    "open_type", "open_zone", "open_direction", "open_bias_conf",
    "open_relation_type", "trend_day_probability", "profile_shape",
    # Generic
    "close", "high", "low", "open", "volume", "atr",
})

# Pattern simple AtomicCondition : "field op value [trailing description]"
# Ex: "bn_absorb_bid > 0", "Delta_bar > 0 sur la bar du rebond"
# Phase B.5.2 v2 : trailing description toleree (non-greedy regex sans $).
_RX_ATOMIC = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)",
)

# Detect connecteur OR ("OU") - case insensitive, autour de "OU"
_RX_OR_SPLIT = re.compile(r"\s+(?:OU|OR)\s+", re.IGNORECASE)

# Detect connecteur AND ("ET" ou "+" entoure d'espaces)
_RX_AND_SPLIT = re.compile(r"\s+(?:ET|AND)\s+|\s+\+\s+", re.IGNORECASE)


def _normalize_field_name(name: str) -> str:
    """Normalise field name (Delta_bar -> delta_bar, BN absorb_bid -> bn_absorb_bid).

    Phase B.5.2 v2 : Jackson ecrit en mixed case dans scenario_generator.py.
    Le pipeline JSONL utilise tout lowercase. On harmonise.
    """
    s = name.strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s


def _make_unparsable(desc: str) -> AtomicCondition:
    """Factory AtomicCondition is_unparsable=True (factorisation DRY)."""
    return AtomicCondition(
        field=UNPARSABLE_FIELD, op="==", threshold=0.0,
        description=desc, is_unparsable=True,
    )


def _parse_atomic(s: str, original: Optional[str] = None) -> ConditionNode:
    """Parse une string atomique (sans connecteur OR/AND) en AtomicCondition.

    Tolerant aux variantes case + trailing description (Phase B.5.2 v2).
    Si pattern non reconnu OR field hors KNOWN_FIELDS -> AtomicCondition
    is_unparsable=True (eval = False).
    """
    desc = original if original else s.strip()
    m = _RX_ATOMIC.match(s.strip())
    if not m:
        return _make_unparsable(desc)
    raw_field, op, value_str = m.group(1), m.group(2), m.group(3)
    # Normaliser "=" -> "=="
    if op == "=":
        op = "=="
    # Normaliser field name (case-insensitive + multi-word)
    field_name = _normalize_field_name(raw_field)
    # Whitelist field (anti typo + securite)
    if field_name not in KNOWN_FIELDS:
        return _make_unparsable(desc)
    try:
        value = float(value_str)
    except ValueError:
        return _make_unparsable(desc)
    return AtomicCondition(
        field=field_name, op=op, threshold=value, description=desc,
    )


def parse_legacy_condition(s: str) -> ConditionNode:
    """Parse une string legacy en ConditionNode.

    Patterns supportes :
    - Atomic : "field op value" (ex: "bn_absorb_bid > 0")
    - OR     : "A OU B" (ou "A OR B") -> CompositeCondition OR
    - AND    : "A ET B" (ou "A AND B", "A + B") -> CompositeCondition AND
    - Unparsable : fallback AtomicCondition is_unparsable=True

    Args:
        s : string legacy

    Returns:
        ConditionNode (AtomicCondition ou CompositeCondition)
    """
    if not s or not isinstance(s, str):
        return _make_unparsable(str(s) if s else "<empty>")

    raw = s.strip()
    # OR a la racine : split prioritaire
    or_parts = _RX_OR_SPLIT.split(raw)
    if len(or_parts) > 1:
        children = tuple(parse_legacy_condition(p) for p in or_parts)
        return CompositeCondition(conditions=children, op="OR", description=raw)

    # AND a la racine : split secondaire
    and_parts = _RX_AND_SPLIT.split(raw)
    if len(and_parts) > 1:
        children = tuple(parse_legacy_condition(p) for p in and_parts)
        return CompositeCondition(conditions=children, op="AND", description=raw)

    # Atomique simple
    return _parse_atomic(raw, original=raw)


def parse_legacy_conditions_list(conditions: list) -> list:
    """Parse une list[str] legacy en list[ConditionNode].

    Si l'entree contient deja des ConditionNode, ils sont retournes tels quels
    (idempotence).
    """
    out = []
    for c in conditions:
        if isinstance(c, (AtomicCondition, CompositeCondition)):
            out.append(c)
        elif isinstance(c, str):
            out.append(parse_legacy_condition(c))
        else:
            out.append(_make_unparsable(str(c)))
    return out
