"""tests/bot3/test_level_definitions_phase4.py - Tests Phase 4 nature + mirror SHORT.

Tests pytest pour `CORE/bot3_level_definitions.py` Phase 4 additions :
- `derive_nature_from_side()` mapping legacy_side → nature
- `get_level_nature()` lookup multi-tier + overrides
- `MIRROR_SHORT_TIER1` 5 levels symetrie LONG/SHORT

HISTORY
2026-05-18 PM : creation Phase 4abc J+4 - nature mapping + mirror SHORT
"""
from __future__ import annotations

import pytest

from CORE.bot3_level_definitions import (
    MIRROR_SHORT_TIER1,
    TIER1,
    TIER2,
    TIER3,
    TIER2_LEVELS_NEUTRAL,
    _LEVEL_NATURE_OVERRIDES,
    derive_nature_from_side,
    get_level_nature,
)


# ════════════════════════════════════════════════════════════════════════════
# derive_nature_from_side (pure mapping)
# ════════════════════════════════════════════════════════════════════════════


def test_derive_nature_LONG_to_support():
    assert derive_nature_from_side("LONG") == "support"


def test_derive_nature_SHORT_to_resistance():
    assert derive_nature_from_side("SHORT") == "resistance"


def test_derive_nature_REJECTION_to_structural():
    assert derive_nature_from_side("REJECTION") == "structural"


def test_derive_nature_NEUTRAL_to_structural():
    """NEUTRAL = orderflow decide = structural pivot."""
    assert derive_nature_from_side("NEUTRAL") == "structural"


def test_derive_nature_case_insensitive():
    """Robuste casse : 'long' → 'support' (defensif)."""
    assert derive_nature_from_side("long") == "support"
    assert derive_nature_from_side("Short") == "resistance"


def test_derive_nature_unknown_side_raises():
    """Fail-loud anti silent fallback : side inconnu = ValueError."""
    with pytest.raises(ValueError):
        derive_nature_from_side("INVALID_SIDE")


def test_derive_nature_empty_side_raises():
    with pytest.raises(ValueError):
        derive_nature_from_side("")


# ════════════════════════════════════════════════════════════════════════════
# get_level_nature lookup multi-tier
# ════════════════════════════════════════════════════════════════════════════


def test_get_level_nature_TIER1_LONG_returns_support():
    """IB_LOW est LONG dans TIER1 → support."""
    assert get_level_nature("IB_LOW") == "support"


def test_get_level_nature_TIER1_LONG_MQ_PUT_0DTE():
    """MQ_PUT_0DTE LONG → support."""
    assert get_level_nature("MQ_PUT_0DTE") == "support"


def test_get_level_nature_TIER2_LONG_GEX_DN():
    """GEX_DN LONG TIER2 → support."""
    assert get_level_nature("GEX_DN") == "support"


def test_get_level_nature_TIER3_SHORT_to_resistance():
    """CASH_HIGH_CVD_FLAT SHORT TIER3 → resistance."""
    assert get_level_nature("CASH_HIGH_CVD_FLAT") == "resistance"


def test_get_level_nature_REJECTION_overridden_to_structural():
    """SINGLE_PRINT REJECTION → _LEVEL_NATURE_OVERRIDES → structural.
    OPEN_830/930 REJECTION → override structural (niveau temporel pivot)."""
    assert get_level_nature("SINGLE_PRINT") == "structural"
    assert get_level_nature("OPEN_830") == "structural"
    assert get_level_nature("OPEN_930") == "structural"


def test_get_level_nature_CUR_VPOC_overridden_to_structural():
    """CUR_VPOC REJECTION (TIER2) override → structural (magnet developing POC)."""
    assert get_level_nature("CUR_VPOC") == "structural"


def test_get_level_nature_TIER2_NEUTRAL_to_structural():
    """PVAH TIER2_NEUTRAL side=NEUTRAL → structural."""
    assert get_level_nature("PVAH") == "structural"


def test_get_level_nature_unknown_returns_None():
    """Level pas dans aucun tier → None (caller decide)."""
    assert get_level_nature("UNKNOWN_LEVEL_XYZ") is None


# ════════════════════════════════════════════════════════════════════════════
# MIRROR_SHORT_TIER1 - 5 levels symetrie LONG/SHORT (Phase 4c)
# ════════════════════════════════════════════════════════════════════════════


def test_mirror_short_has_5_levels():
    """Master plan exige 5 mirror SHORT : MQ_CALL_0DTE, IB_HIGH_SHORT,
    GEX_UP, VWAP_W_SD1U, PVAH_SHORT."""
    expected = {"MQ_CALL_0DTE", "IB_HIGH_SHORT", "GEX_UP",
                "VWAP_W_SD1U", "PVAH_SHORT"}
    assert set(MIRROR_SHORT_TIER1.keys()) == expected


def test_mirror_short_all_have_SHORT_side():
    """Tous les mirror DOIVENT etre side=SHORT (sinon perd la symetrie)."""
    for name, level in MIRROR_SHORT_TIER1.items():
        assert level["side"] == "SHORT", f"{name} side != SHORT"


def test_mirror_short_all_have_mirror_of_field():
    """Chaque mirror reference son LONG d'origine (audit traceability)."""
    for name, level in MIRROR_SHORT_TIER1.items():
        assert "_mirror_of" in level, f"{name} manque _mirror_of"
        assert level["_mirror_of"] in (
            "MQ_PUT_0DTE", "IB_LOW", "GEX_DN", "VWAP_W_SD1D", "PVAL"
        )


def test_mirror_short_resolves_to_resistance_nature():
    """get_level_nature des mirror SHORT → resistance (SHORT → resistance)."""
    for name in MIRROR_SHORT_TIER1.keys():
        assert get_level_nature(name) == "resistance", (
            f"{name} nature != resistance"
        )


def test_mirror_short_supports_both_symbols():
    """Tous les mirror supportent NQ + ES (bidirectional cross-symbol)."""
    for name, level in MIRROR_SHORT_TIER1.items():
        symbols = level.get("symbols", [])
        assert "NQ" in symbols and "ES" in symbols, (
            f"{name} missing NQ or ES"
        )


# ════════════════════════════════════════════════════════════════════════════
# Coherence cross-tier (no level present in multiple primary tiers)
# ════════════════════════════════════════════════════════════════════════════


def test_no_level_duplicated_across_primary_tiers():
    """Un level ne devrait pas etre dans 2 tiers primaires (TIER1/2/3) en meme
    temps. TIER2_NEUTRAL et MIRROR_SHORT sont par design separes."""
    keys1 = set(TIER1.keys())
    keys2 = set(TIER2.keys())
    keys3 = set(TIER3.keys())
    assert keys1.isdisjoint(keys2)
    assert keys1.isdisjoint(keys3)
    assert keys2.isdisjoint(keys3)


def test_mirror_short_isolated_from_legacy_neutral():
    """MIRROR_SHORT levels nouveau set, distinct de TIER2_NEUTRAL (no overlap).
    Backwards-compat : modifier MIRROR n'impacte pas legacy NEUTRAL trades."""
    mirror_keys = set(MIRROR_SHORT_TIER1.keys())
    neutral_keys = set(TIER2_LEVELS_NEUTRAL.keys())
    # IB_HIGH existe dans NEUTRAL (side=NEUTRAL), pas IB_HIGH_SHORT dans MIRROR
    # PVAH existe dans NEUTRAL (side=NEUTRAL), pas PVAH_SHORT dans MIRROR
    # Donc les sets sont disjoint par design (suffixe _SHORT distinguer)
    assert mirror_keys.isdisjoint(neutral_keys)
