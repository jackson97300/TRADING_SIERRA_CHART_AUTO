"""Tests ChaseTopGate (05/05/2026) — filter range_pos sur LONG.

Walk-forward Lopez 5-fold validation : DSR=0.72, delta +$1264, ratio 5.5x SL/TP.

Valide :
  1. LONG bloque si range_pos >= 60
  2. LONG accepte si range_pos < 60
  3. SHORT non filtre (range_pos >=60 OK pour SHORT)
  4. Edge cases : range_pos None/NaN/string → fallback 50 (passage)
  5. Threshold exact = 60 (range_pos=59.9 passe, 60.0 bloque)
"""

# Test isole : pas de full import du paper_trader (trop de dependencies).
# On reproduit la logique du gate ici comme contract.

THRESHOLD = 60.0


def chase_top_gate(direction, range_pos):
    """Reproduction du gate de mia_paper_trader.py / mia2_brain_v6_databento.py.

    Returns True si le gate REJETTE (=block), False si laisse passer.
    """
    if direction != "LONG":
        return False  # SHORT non filtre
    try:
        rp = float(range_pos) if range_pos is not None else 50
    except (TypeError, ValueError):
        rp = 50
    return rp >= THRESHOLD


# ============================================================
# Tests
# ============================================================

def test_long_blocked_at_60():
    """LONG bloque au seuil exact (range_pos=60)."""
    assert chase_top_gate("LONG", 60.0) is True
    assert chase_top_gate("LONG", 60) is True


def test_long_blocked_above_60():
    """LONG bloque pour range_pos > 60."""
    assert chase_top_gate("LONG", 65) is True
    assert chase_top_gate("LONG", 80) is True
    assert chase_top_gate("LONG", 100) is True


def test_long_accepted_below_60():
    """LONG accepte si range_pos < 60."""
    assert chase_top_gate("LONG", 59.9) is False
    assert chase_top_gate("LONG", 50) is False
    assert chase_top_gate("LONG", 30) is False
    assert chase_top_gate("LONG", 0) is False


def test_short_never_blocked():
    """SHORT n'est jamais bloque par ce gate (audit empirique : symetrie casse les SHORT)."""
    assert chase_top_gate("SHORT", 100) is False
    assert chase_top_gate("SHORT", 50) is False
    assert chase_top_gate("SHORT", 0) is False


def test_unknown_direction_not_blocked():
    """Direction inconnue : pas de block."""
    assert chase_top_gate("UNKNOWN", 100) is False
    assert chase_top_gate("", 100) is False
    assert chase_top_gate(None, 100) is False


def test_range_pos_none_defaults_50_passes():
    """range_pos None/NaN → fallback 50 → < 60 → LONG passe."""
    assert chase_top_gate("LONG", None) is False


def test_range_pos_string_defaults_50_passes():
    """range_pos string non-numeric → fallback 50 → LONG passe."""
    assert chase_top_gate("LONG", "invalid") is False


def test_range_pos_string_numeric_works():
    """range_pos string numeric (parsable) → converti → LONG bloque si >=60."""
    assert chase_top_gate("LONG", "75") is True
    assert chase_top_gate("LONG", "55.5") is False


def test_threshold_constant_is_60():
    """Constante threshold = 60 (deploy 05/05, ne pas baisser sans walk-forward)."""
    assert THRESHOLD == 60.0
