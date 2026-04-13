"""Tests gamma gate integration — dashboard builders.py

Valide :
  1. _gamma_gate_check : 5 cas unitaires (None, call proche, put proche,
     GEX flip, combinaison, sentinelle 0.0 bloquante, ATR-scaling)
  2. build_conseil_global : 6 cas integration (cap absolu, retro-compat,
     priorite gate sur MTF, regressions classiques)
  3. build_trade_suggestion : 4 cas integration (check #7, grade 7/7 = A,
     rétro-compat, LONG vs call wall, SHORT vs put support)

Pourquoi ces tests existent :
  - Aucun test existant sur `builders.py` avant cette session
  - Le gate gamma est le filet de securite principal contre le
    contre-trading du flux institutionnel
  - Un bug silencieux dans la formule = perte d'argent pour les users du
    dashboard SaaS
"""
import sys
from pathlib import Path

# Ajouter racine projet au path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from DASHBOARD.api.builders import (
    _gamma_gate_check,
    build_conseil_global,
    build_trade_suggestion,
    _GAMMA_CAP_BULL_BEAR,
    _GAMMA_THRESHOLD_MIN_TICKS,
    _GAMMA_THRESHOLD_MAX_TICKS,
)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

PASSED = 0
FAILED = 0
FAILURES = []


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        print(f"  OK  {name}")
        PASSED += 1
    else:
        print(f"  FAIL {name}{' — ' + detail if detail else ''}")
        FAILED += 1
        FAILURES.append(name)


def make_bar(
    *,
    atr: float = 30.0,
    delta_day_dir: int = 0,
    delta_divergence: int = 0,
    rvol: float = 1.0,
    vix_level: float = 18.0,
    price: float = 6800.0,
    session_id: str = "US",
) -> dict:
    """Construit une barre JSONL synthetique minimale pour les tests."""
    return {
        "atr": atr,
        "delta_day_dir": delta_day_dir,
        "delta_divergence": delta_divergence,
        "rvol": rvol,
        "vix_level": vix_level,
        "price": price,
        "session_id": session_id,
    }


def make_regime(
    *,
    bias: str = "NEUTRAL",
    range_pos: float = 50.0,
    mtf_bulls: int = 0,
    mtf_bears: int = 0,
    mtf_verdict: str = "N/A",
    div_grade: str = "NONE",
    favor: str = "NEUTRE",
    mode: str = "NORMAL",
    vol_regime: str = "NORMAL",
    bias_confidence: float = 0.5,
) -> dict:
    """Regime context synthetique pour les tests."""
    return {
        "bias": bias,
        "range_pos": range_pos,
        "mtf_bulls": mtf_bulls,
        "mtf_bears": mtf_bears,
        "mtf_verdict": mtf_verdict,
        "div_grade": div_grade,
        "favor": favor,
        "mode": mode,
        "vol_regime": vol_regime,
        "bias_confidence": bias_confidence,
    }


def make_options(
    *,
    dist_mq_call: float = 100.0,
    dist_mq_put: float = 100.0,
    call_wall_price: float = 6900.0,
    put_wall_price: float = 6700.0,
    gex_flip_zone: int = 0,
) -> dict:
    """Options levels synthetique (format de build_options_levels)."""
    return {
        "dist_mq_call": dist_mq_call,
        "dist_mq_put": dist_mq_put,
        "call_wall_price": call_wall_price,
        "put_wall_price": put_wall_price,
        "gex_flip_zone": gex_flip_zone,
    }


# ═══════════════════════════════════════════════════════════════
# 1. TESTS UNITAIRES _gamma_gate_check
# ═══════════════════════════════════════════════════════════════

def test_1_1_none_options_no_block():
    """options=None → aucun blocage, liste vide."""
    print("\n[1.1] options=None → no block")
    bar = make_bar()
    bl, bs, w = _gamma_gate_check(bar, None)
    check("block_long = False", bl is False)
    check("block_short = False", bs is False)
    check("warnings vide", w == [])


def test_1_2_call_wall_close_blocks_long():
    """call_dist=5 < seuil 15 → block_long=True."""
    print("\n[1.2] call wall proche bloque LONG")
    bar = make_bar(atr=30.0)  # threshold = 15t
    opts = make_options(dist_mq_call=5.0, dist_mq_put=100.0)
    bl, bs, w = _gamma_gate_check(bar, opts)
    check("block_long = True", bl is True)
    check("block_short = False", bs is False)
    check("1 warning", len(w) == 1)
    check("warning contient CALL WALL", any("CALL WALL" in s for s in w))


def test_1_3_put_support_close_blocks_short():
    """put_dist=5 < seuil 15 → block_short=True."""
    print("\n[1.3] put support proche bloque SHORT")
    bar = make_bar(atr=30.0)
    opts = make_options(dist_mq_call=100.0, dist_mq_put=5.0)
    bl, bs, w = _gamma_gate_check(bar, opts)
    check("block_long = False", bl is False)
    check("block_short = True", bs is True)
    check("1 warning", len(w) == 1)
    check("warning contient PUT SUPPORT", any("PUT SUPPORT" in s for s in w))


def test_1_4_gex_flip_blocks_both():
    """gex_flip_zone=1 → block_long ET block_short."""
    print("\n[1.4] GEX flip zone bloque les 2 cotes")
    bar = make_bar(atr=30.0)
    opts = make_options(dist_mq_call=100.0, dist_mq_put=100.0, gex_flip_zone=1)
    bl, bs, w = _gamma_gate_check(bar, opts)
    check("block_long = True", bl is True)
    check("block_short = True", bs is True)
    check("warning contient FLIP", any("FLIP" in s for s in w))


def test_1_5_combined_all_three():
    """call + put + gex_flip simultanes."""
    print("\n[1.5] combinaison call + put + flip")
    bar = make_bar(atr=30.0)
    opts = make_options(dist_mq_call=3.0, dist_mq_put=3.0, gex_flip_zone=1)
    bl, bs, w = _gamma_gate_check(bar, opts)
    check("block_long = True", bl is True)
    check("block_short = True", bs is True)
    check("3 warnings", len(w) == 3)


def test_1_6_dist_zero_with_wall_price_is_block():
    """dist=0.0 + wall_price present → prix PILE sur le mur → block.

    C'est le cas CRITIQUE : le DMP retourne 0.0 quand le prix est
    exactement sur le mur, notre logique doit traiter ca comme le plus
    dangereux, pas l'ignorer.
    """
    print("\n[1.6] dist=0 avec wall_price → block (cas PILE dessus)")
    bar = make_bar(atr=30.0)
    opts = make_options(
        dist_mq_call=0.0,
        call_wall_price=6800.0,  # present → on est sur le mur
        dist_mq_put=100.0,
    )
    bl, bs, w = _gamma_gate_check(bar, opts)
    check("block_long = True (prix sur mur)", bl is True)
    check("warning 'PILE' present", any("PILE" in s for s in w))


def test_1_7_threshold_scales_with_atr():
    """Seuil proportionnel a ATR : NQ (ATR=120) doit bloquer a 30t, ES (ATR=30) a 10t."""
    print("\n[1.7] seuil adaptatif ATR")
    # ATR 30 → seuil 15 → 20t ne bloque pas (hors zone)
    bar_es = make_bar(atr=30.0)
    opts_20t = make_options(dist_mq_call=20.0)
    bl_es, _, _ = _gamma_gate_check(bar_es, opts_20t)
    check("ES ATR=30 : call 20t NE bloque PAS (seuil 15)", bl_es is False)

    # ATR 120 → seuil 60 → 20t bloque (dans la zone)
    bar_nq = make_bar(atr=120.0)
    bl_nq, _, _ = _gamma_gate_check(bar_nq, opts_20t)
    check("NQ ATR=120 : call 20t bloque (seuil 60)", bl_nq is True)


# ═══════════════════════════════════════════════════════════════
# 2. TESTS INTEGRATION build_conseil_global
# ═══════════════════════════════════════════════════════════════

def test_2_1_bullish_with_call_wall_is_capped():
    """Setup BULLISH fort + call wall proche → PAS d'ACHAT (cap absolu)."""
    print("\n[2.1] BULLISH fort + call wall → cap → pas ACHAT")
    bar = make_bar(atr=30.0, delta_day_dir=1)
    regime = make_regime(
        bias="BULLISH",
        range_pos=10.0,
        mtf_bulls=4,
        mtf_verdict="ACHAT FORT (4/4)",
    )
    opts = make_options(dist_mq_call=5.0)  # bloque LONG
    result = build_conseil_global(bar, regime, opts)
    check(
        "action != ACHAT",
        result["action"] not in ("ACHAT", "ACHAT PRUDENT"),
        detail=f"got: {result['action']}",
    )
    check(
        "bull_pts cape a 3 max",
        result["bull_points"] <= _GAMMA_CAP_BULL_BEAR,
        detail=f"got: {result['bull_points']}",
    )
    check("gamma_block_long = True", result.get("gamma_block_long") is True)


def test_2_2_bearish_with_put_support_is_capped():
    """Setup BEARISH fort + put support proche → PAS de VENTE."""
    print("\n[2.2] BEARISH fort + put support → cap → pas VENTE")
    bar = make_bar(atr=30.0, delta_day_dir=-1)
    regime = make_regime(
        bias="BEARISH",
        range_pos=90.0,
        mtf_bears=4,
        mtf_verdict="VENTE FORT (4/4)",
    )
    opts = make_options(dist_mq_put=5.0)  # bloque SHORT
    result = build_conseil_global(bar, regime, opts)
    check(
        "action != VENTE",
        result["action"] not in ("VENTE", "VENTE PRUDENTE"),
        detail=f"got: {result['action']}",
    )
    check("bear_pts cape a 3 max", result["bear_points"] <= _GAMMA_CAP_BULL_BEAR)
    check("gamma_block_short = True", result.get("gamma_block_short") is True)


def test_2_3_bullish_gamma_clear_keeps_achat():
    """REGRESSION : setup BULLISH fort + gamma clear → ACHAT conserve."""
    print("\n[2.3] regression : BULLISH + gamma clear → ACHAT")
    bar = make_bar(atr=30.0, delta_day_dir=1)
    regime = make_regime(
        bias="BULLISH",
        range_pos=10.0,
        mtf_bulls=4,
        mtf_verdict="ACHAT FORT (4/4)",
    )
    opts = make_options()  # tout loin
    result = build_conseil_global(bar, regime, opts)
    check(
        "action contient ACHAT",
        "ACHAT" in result["action"],
        detail=f"got: {result['action']}",
    )


def test_2_4_options_none_retro_compat():
    """REGRESSION : options=None → comportement pre-fix strict."""
    print("\n[2.4] rétro-compat : options=None → comportement historique")
    bar = make_bar(atr=30.0, delta_day_dir=1)
    regime = make_regime(
        bias="BULLISH",
        range_pos=10.0,
        mtf_bulls=4,
        mtf_verdict="ACHAT FORT (4/4)",
    )
    result_none = build_conseil_global(bar, regime, None)
    result_no_arg = build_conseil_global(bar, regime)  # appel sans 3e arg
    check("options=None → ACHAT", "ACHAT" in result_none["action"])
    check("appel 2 args idem", result_none["action"] == result_no_arg["action"])
    check("gamma_block_long = False", result_none.get("gamma_block_long") is False)


def test_2_5_mtf_perfect_bull_with_call_block_forces_attendre():
    """Priorite gate sur MTF : MTF 4/4 + gamma block → ATTENDRE (pas override)."""
    print("\n[2.5] MTF 4/4 + gamma block → priorite au gate (pas ACHAT)")
    bar = make_bar(atr=30.0, delta_day_dir=1)
    regime = make_regime(
        bias="BULLISH",
        range_pos=10.0,
        mtf_bulls=4,
        mtf_verdict="ACHAT FORT (4/4)",
    )
    opts = make_options(dist_mq_call=5.0)
    result = build_conseil_global(bar, regime, opts)
    # Avec cap a 3 sur bull_pts, on ne peut pas atteindre 4+ → pas d'ACHAT
    check(
        "action pas ACHAT malgre MTF 4/4",
        result["action"] not in ("ACHAT", "ACHAT PRUDENT"),
        detail=f"got: {result['action']}",
    )


def test_2_6_empty_bar_or_regime_returns_attendre():
    """REGRESSION : bar vide → ATTENDRE + structure coherente."""
    print("\n[2.6] bar/regime vides → ATTENDRE")
    result = build_conseil_global({}, {})
    check("action = ATTENDRE", result["action"] == "ATTENDRE")
    check("bull_points = 0", result["bull_points"] == 0)


# ═══════════════════════════════════════════════════════════════
# 3. TESTS INTEGRATION build_trade_suggestion
# ═══════════════════════════════════════════════════════════════

def test_3_1_long_with_call_wall_no_signal():
    """LONG + call wall proche → has_signal=False (regle Jackson : pas de GO contre le flux)."""
    print("\n[3.1] LONG + call wall → has_signal=False + action != GO")
    bar = make_bar(atr=30.0, session_id="US")
    regime = make_regime(favor="LONG", bias_confidence=0.7)
    opts = make_options(dist_mq_call=5.0)
    result = build_trade_suggestion(bar, "ES", regime, opts)
    gamma_check = next(
        (c for c in result["checks"] if "CALL" in c["name"]), None
    )
    check("gamma check present", gamma_check is not None)
    check("gamma check = False", gamma_check and gamma_check["ok"] is False)
    check("passed < total", result["passed"] < result["total"])
    # Hard-fail gamma : meme si grade B, has_signal doit etre False
    check(
        "has_signal = False (hard-fail gamma)",
        result["has_signal"] is False,
        detail=f"got: has_signal={result['has_signal']}, grade={result['grade']}",
    )
    check(
        "action != GO",
        result["action"] != "GO",
        detail=f"got action: {result['action']}",
    )


def test_3_2_short_with_put_support_no_signal():
    """SHORT + put support proche → has_signal=False (hard-fail gamma)."""
    print("\n[3.2] SHORT + put support → has_signal=False + action != GO")
    bar = make_bar(atr=30.0, session_id="US")
    regime = make_regime(favor="SHORT", bias_confidence=0.7)
    opts = make_options(dist_mq_put=5.0)
    result = build_trade_suggestion(bar, "ES", regime, opts)
    gamma_check = next(
        (c for c in result["checks"] if "PUT" in c["name"]), None
    )
    check("gamma check present", gamma_check is not None)
    check("gamma check = False", gamma_check and gamma_check["ok"] is False)
    check(
        "has_signal = False (hard-fail gamma)",
        result["has_signal"] is False,
    )
    check(
        "action != GO",
        result["action"] != "GO",
    )


def test_3_3_long_with_gamma_clear_grade_A_possible():
    """LONG + gamma clear + tous checks OK → grade A (7/7)."""
    print("\n[3.3] LONG + gamma clear + tout ok → grade A 7/7")
    bar = make_bar(
        atr=30.0,
        session_id="US",
        delta_divergence=0,
        vix_level=18.0,
    )
    regime = make_regime(
        favor="LONG",
        bias_confidence=0.8,
        vol_regime="NORMAL",
    )
    opts = make_options()
    result = build_trade_suggestion(bar, "ES", regime, opts)
    # Tous les checks doivent etre OK → grade A
    check("total = 7", result["total"] == 7)
    check("passed = 7", result["passed"] == 7, detail=f"got: {result['passed']}")
    check("grade = A", result["grade"] == "A", detail=f"got: {result['grade']}")
    check("has_signal = True", result["has_signal"] is True)


def test_3_4_options_none_backward_compat():
    """REGRESSION : options=None/absent → 6 checks, grade A si 6/6."""
    print("\n[3.4] options={} → 6 checks, regression check")
    bar = make_bar(atr=30.0, session_id="US")
    regime = make_regime(favor="LONG", bias_confidence=0.8)
    result = build_trade_suggestion(bar, "ES", regime, {})
    # options={} → if options: False → pas de check #7
    check("total = 6 (pas de check gamma)", result["total"] == 6)
    check("passed = 6", result["passed"] == 6)
    check("grade = A", result["grade"] == "A")


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  TESTS GAMMA GATE — dashboard builders.py")
    print("=" * 62)

    # 1. Unitaires _gamma_gate_check (7 cas)
    test_1_1_none_options_no_block()
    test_1_2_call_wall_close_blocks_long()
    test_1_3_put_support_close_blocks_short()
    test_1_4_gex_flip_blocks_both()
    test_1_5_combined_all_three()
    test_1_6_dist_zero_with_wall_price_is_block()
    test_1_7_threshold_scales_with_atr()

    # 2. Integration build_conseil_global (6 cas)
    test_2_1_bullish_with_call_wall_is_capped()
    test_2_2_bearish_with_put_support_is_capped()
    test_2_3_bullish_gamma_clear_keeps_achat()
    test_2_4_options_none_retro_compat()
    test_2_5_mtf_perfect_bull_with_call_block_forces_attendre()
    test_2_6_empty_bar_or_regime_returns_attendre()

    # 3. Integration build_trade_suggestion (4 cas)
    test_3_1_long_with_call_wall_no_signal()
    test_3_2_short_with_put_support_no_signal()
    test_3_3_long_with_gamma_clear_grade_A_possible()
    test_3_4_options_none_backward_compat()

    print()
    print("=" * 62)
    print(f"  {PASSED}/{PASSED + FAILED} tests passent")
    if FAILURES:
        print("  ECHECS :")
        for name in FAILURES:
            print(f"    - {name}")
        print("=" * 62)
        sys.exit(1)
    print("  TOUS LES TESTS PASSENT")
    print("=" * 62)


if __name__ == "__main__":
    main()
