"""tests/bot3/test_level_definitions_phase4.py - Tests Phase 4 nature + mirror SHORT.

Tests pytest pour `CORE/bot3_level_definitions.py` Phase 4 additions :
- `derive_nature_from_side()` mapping legacy_side → nature (NEUTRAL → None)
- `get_level_nature()` lookup _ALL_LEVEL_DICTS cache O(1)
- `MIRROR_SHORT_OBSERVE` 2 levels OBSERVE-ONLY (post-review market-analyst)
- `level_supports_symbol()` fix Bug 12 lookup MIRROR + NEUTRAL

HISTORY
2026-05-18 PM : creation Phase 4abc J+4 - nature mapping + mirror SHORT
"""
from __future__ import annotations

import pytest

from CORE.bot3_level_definitions import (
    MIRROR_SHORT_OBSERVE,
    TIER1,
    TIER2,
    TIER3,
    TIER2_LEVELS_NEUTRAL,
    _LEVEL_NATURE_OVERRIDES,
    derive_nature_from_side,
    get_level_nature,
    level_supports_symbol,
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


def test_derive_nature_NEUTRAL_returns_None():
    """Bug 10 fix : NEUTRAL = orderflow decide via legacy 7 scenarios.
    derive_nature_from_side('NEUTRAL') retourne None (PAS structural).
    Sinon castrate 8 TIER2_NEUTRAL levels en DirectionResolver."""
    assert derive_nature_from_side("NEUTRAL") is None


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


def test_get_level_nature_REJECTION_derives_structural_auto():
    """Bug 10 fix : REJECTION auto-derive → structural (sans override redondant).
    SINGLE_PRINT/CUR_VPOC/MQ_HVL/OPEN_830/OPEN_930 sont tous side=REJECTION."""
    assert get_level_nature("SINGLE_PRINT") == "structural"
    assert get_level_nature("OPEN_830") == "structural"
    assert get_level_nature("OPEN_930") == "structural"
    assert get_level_nature("CUR_VPOC") == "structural"
    assert get_level_nature("MQ_HVL") == "structural"


def test_get_level_nature_TIER2_NEUTRAL_returns_None():
    """Bug 10 fix : PVAH TIER2_NEUTRAL side=NEUTRAL → None.
    Route legacy 7 scenarios (bot3_decision_engine), PAS DirectionResolver."""
    assert get_level_nature("PVAH") is None
    assert get_level_nature("CUR_VAH") is None
    assert get_level_nature("MQ_CALL") is None
    assert get_level_nature("IB_HIGH") is None
    assert get_level_nature("SWING_HIGH") is None


def test_get_level_nature_unknown_returns_None():
    """Level pas dans aucun tier → None (caller decide)."""
    assert get_level_nature("UNKNOWN_LEVEL_XYZ") is None


# ════════════════════════════════════════════════════════════════════════════
# MIRROR_SHORT_OBSERVE - 2 levels OBSERVE-ONLY post-review market-analyst
# (3 originaux supprimes : MQ_CALL_0DTE asymetrie 33%/57%, IB_HIGH_SHORT
#  + PVAH_SHORT doublons physiques dist_col)
# ════════════════════════════════════════════════════════════════════════════


def test_mirror_short_has_2_observe_levels_only():
    """Post-review : 2 mirrors valides (GEX_UP gamma flip, VWAP_W_SD1U
    bilateral institutionnel). 3 supprimes (MQ_CALL_0DTE asymetrie + 2 doublons)."""
    expected = {"GEX_UP", "VWAP_W_SD1U"}
    assert set(MIRROR_SHORT_OBSERVE.keys()) == expected


def test_mirror_short_all_tier_3_observe_only():
    """Bug 5 fix : tier=3 observe-only (sans baseline N>=5000)."""
    for name, level in MIRROR_SHORT_OBSERVE.items():
        assert level["tier"] == 3, f"{name} tier != 3 observe-only"


def test_mirror_short_all_have_required_context_phase_5():
    """Bug 5 fix : gate explicit required_context.phase_5_dsr_validated."""
    for name, level in MIRROR_SHORT_OBSERVE.items():
        assert "required_context" in level
        assert level["required_context"].get("phase_5_dsr_validated") is True


def test_mirror_short_all_have_SHORT_side():
    """Tous les mirror DOIVENT etre side=SHORT (sinon perd la symetrie)."""
    for name, level in MIRROR_SHORT_OBSERVE.items():
        assert level["side"] == "SHORT", f"{name} side != SHORT"


def test_mirror_short_no_dist_col_duplication_with_neutral():
    """Bug 4 fix : MIRROR ne doit PAS avoir dist_col dans TIER2_NEUTRAL.
    Sinon double-fire mp_engine. Verifie absence collision."""
    mirror_dist_cols = {level["dist_col"] for level in MIRROR_SHORT_OBSERVE.values()}
    neutral_dist_cols = {level["dist_col"] for level in TIER2_LEVELS_NEUTRAL.values()}
    overlap = mirror_dist_cols & neutral_dist_cols
    assert not overlap, f"dist_col duplication MIRROR vs NEUTRAL: {overlap}"


def test_mirror_short_resolves_to_resistance_nature():
    """get_level_nature des mirror SHORT → resistance."""
    for name in MIRROR_SHORT_OBSERVE.keys():
        assert get_level_nature(name) == "resistance", (
            f"{name} nature != resistance"
        )


def test_mirror_short_supports_both_symbols():
    """Tous les mirror supportent NQ + ES (bidirectional cross-symbol)."""
    for name, level in MIRROR_SHORT_OBSERVE.items():
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
    """MIRROR_SHORT_OBSERVE levels distinct de TIER2_NEUTRAL (no overlap)."""
    mirror_keys = set(MIRROR_SHORT_OBSERVE.keys())
    neutral_keys = set(TIER2_LEVELS_NEUTRAL.keys())
    assert mirror_keys.isdisjoint(neutral_keys)


# ════════════════════════════════════════════════════════════════════════════
# Bug 12 fix : level_supports_symbol itere _ALL_LEVEL_DICTS (incl MIRROR)
# ════════════════════════════════════════════════════════════════════════════


def test_bug12_level_supports_symbol_lookup_MIRROR():
    """Bug 12 fix : level_supports_symbol DOIT lookup MIRROR_SHORT_OBSERVE."""
    assert level_supports_symbol("GEX_UP", "ES") is True
    assert level_supports_symbol("GEX_UP", "NQ") is True
    assert level_supports_symbol("VWAP_W_SD1U", "ES") is True


def test_bug12_level_supports_symbol_lookup_TIER2_NEUTRAL():
    """Bug 12 fix : doit aussi lookup TIER2_NEUTRAL (asymetrie API pre-fix)."""
    assert level_supports_symbol("PVAH", "ES") is True
    assert level_supports_symbol("IB_HIGH", "NQ") is True


def test_bug12_level_supports_symbol_unknown_returns_False():
    """Unknown level still returns False (defensif)."""
    assert level_supports_symbol("FAKE_LEVEL_XYZ", "ES") is False


# ════════════════════════════════════════════════════════════════════════════
# Bug 6 fix : _LEVEL_NATURE_CACHE pre-computed O(1) lookup
# ════════════════════════════════════════════════════════════════════════════


def test_bug6_cache_built_at_module_load():
    """Cache pre-computed contient tous les levels non-NEUTRAL."""
    from CORE.bot3_level_definitions import _LEVEL_NATURE_CACHE
    # TIER1 LONG levels au moins : IB_LOW, MQ_PUT_0DTE
    assert "IB_LOW" in _LEVEL_NATURE_CACHE
    assert _LEVEL_NATURE_CACHE["IB_LOW"] == "support"
    # MIRROR observe-only
    assert "GEX_UP" in _LEVEL_NATURE_CACHE
    assert _LEVEL_NATURE_CACHE["GEX_UP"] == "resistance"
    # NEUTRAL ne doit PAS etre dans cache (Bug 10)
    assert "PVAH" not in _LEVEL_NATURE_CACHE


# ════════════════════════════════════════════════════════════════════════════
# Bug 10 fix : OVERRIDES dict vide (5 originales redondantes verifie)
# ════════════════════════════════════════════════════════════════════════════


def test_bug10_overrides_dict_empty_post_review():
    """Post-review : 5 overrides originaux (SINGLE_PRINT/CUR_VPOC/MQ_HVL/
    OPEN_830/OPEN_930) tous redondants avec derive REJECTION→structural.
    Dict garde comme placeholder vide pour futures exceptions."""
    assert _LEVEL_NATURE_OVERRIDES == {}


# ════════════════════════════════════════════════════════════════════════════
# P1 fix code-reviewer re-review : enable_mirror_observe wire dans get_active_levels
# ════════════════════════════════════════════════════════════════════════════


def test_P1_get_active_levels_excludes_mirror_by_default():
    """P1 fix : enable_mirror_observe=False (default) -> MIRROR pas dans actives."""
    from CORE.bot3_level_definitions import get_active_levels
    actives = get_active_levels(enable_tier2=True, enable_tier3=True,
                                 enable_tier2_neutral=True)
    # Default enable_mirror_observe=False
    assert "GEX_UP" not in actives
    assert "VWAP_W_SD1U" not in actives


def test_P1_get_active_levels_includes_mirror_when_enabled():
    """P1 fix : enable_mirror_observe=True wire MIRROR_SHORT_OBSERVE in."""
    from CORE.bot3_level_definitions import get_active_levels
    actives = get_active_levels(enable_tier2=True, enable_tier3=True,
                                 enable_tier2_neutral=True,
                                 enable_mirror_observe=True)
    # Quand active : MIRROR levels presents
    assert "GEX_UP" in actives
    assert "VWAP_W_SD1U" in actives
