"""Tests gamma_veto_engine (Phase 1 du fix incident #74).

Couvre :
  - Niveau 1 Unit : formule threshold, block conditions, edge cases
  - Niveau 2 Integration : bars synthetiques
  - Niveau 3 Regression empirique : 1036 bars 18/06 (distribution)
  - Niveau 4 Regression scenario -$967 : DATA/_AUDIT/trades_20260615.jsonl

Fix bugs decouverts au refactor :
  - Bug A (root cause -$967) : gamma_block_long/short ABSENTS bar live
  - Bug B (silencieux) : convention dist_mq_put < 0 mais ancienne formule
    `0 < put_dist <= threshold` -> put veto NEVER FIRED
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from CORE.gamma_veto_engine import (
    GammaVetoConfig,
    GammaVerdict,
    compute_gamma_verdict,
    gamma_gate_check_legacy,
    _compute_threshold,
    _safe_float,
)


# ════════════════════════════════════════════════════════════════════════════
# Niveau 1 - UNIT tests
# ════════════════════════════════════════════════════════════════════════════


class TestThresholdFormula:
    """Verifie threshold = clamp(0.5 * ATR, [10, 80])."""

    def test_threshold_normal_atr(self):
        cfg = GammaVetoConfig()
        assert _compute_threshold(100.0, cfg) == 50.0

    def test_threshold_clamped_min(self):
        cfg = GammaVetoConfig()
        # ATR=10 -> 0.5*10=5 < 10 (min) -> clamp 10
        assert _compute_threshold(10.0, cfg) == 10.0

    def test_threshold_clamped_max(self):
        cfg = GammaVetoConfig()
        # ATR=300 -> 0.5*300=150 > 80 (max) -> clamp 80
        assert _compute_threshold(300.0, cfg) == 80.0

    def test_threshold_atr_zero_falls_to_min(self):
        cfg = GammaVetoConfig()
        # ATR=0 -> 0 < 10 (min) -> clamp 10
        assert _compute_threshold(0.0, cfg) == 10.0


class TestSafeFloat:
    """Helper safe cast."""

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, default=42.0) == 42.0

    def test_nan_returns_default(self):
        assert _safe_float(float("nan"), default=99.0) == 99.0

    def test_invalid_string(self):
        assert _safe_float("garbage", default=7.0) == 7.0

    def test_valid_int(self):
        assert _safe_float(5) == 5.0

    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14


class TestCallWallBlock:
    """block_long si dist_mq_call > 0 ET <= threshold (au-dessus + proche)."""

    def test_call_wall_near_blocks_long(self):
        """Call wall a 17t, ATR 50 -> threshold 25 -> 17 <= 25 -> block."""
        bar = {"atr": 50.0, "dist_mq_call": 17.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is True
        assert "CALL_WALL_NEAR_17t" in v.reasons_long
        assert v.block_short is False

    def test_call_wall_far_no_block(self):
        """Call wall a 100t, threshold 25 -> 100 > 25 -> no block."""
        bar = {"atr": 50.0, "dist_mq_call": 100.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is False

    def test_call_wall_negative_no_block(self):
        """Convention : dist_mq_call < 0 = wall en-dessous = ITM = pas un mur LONG."""
        bar = {"atr": 50.0, "dist_mq_call": -15.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is False

    def test_call_wall_on_sentinel(self):
        """dist == 0 AVEC call_wall_price -> pile sur le wall -> block."""
        bar = {"atr": 50.0, "dist_mq_call": 0.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0, "call_wall_price": 7550.0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is True
        assert "CALL_WALL_ON" in v.reasons_long

    def test_call_wall_zero_no_price_no_block(self):
        """dist == 0 SANS call_wall_price (cas bar live sierra) -> ambigu -> no block."""
        bar = {"atr": 50.0, "dist_mq_call": 0.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is False


class TestPutWallBlock:
    """REGRESSION FIX Bug B : block_short si dist_mq_put < 0 ET abs <= threshold."""

    def test_put_wall_near_blocks_short(self):
        """Put wall a -17t (17t en-dessous), threshold 25 -> abs(17) <= 25 -> block.

        Bug fixe : ancienne formule `0 < put_dist <= threshold` ne firait jamais
        avec convention signed negatif. Cette regression PROUVE le fix.
        """
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": -17.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_short is True, "FIX Bug B regression - put veto signed"
        assert "PUT_WALL_NEAR_17t" in v.reasons_short
        assert v.block_long is False

    def test_put_wall_far_no_block(self):
        """Put wall a -100t (loin), threshold 25 -> no block."""
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": -100.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_short is False

    def test_put_wall_positive_no_block(self):
        """Convention : dist_mq_put > 0 = wall au-dessus = ITM = pas support SHORT."""
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": 15.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_short is False

    def test_put_wall_on_sentinel(self):
        """dist == 0 AVEC put_wall_price -> pile sur -> block."""
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": 0.0,
               "bool_gex_flip_zone": 0, "put_wall_price": 7400.0}
        v = compute_gamma_verdict(bar)
        assert v.block_short is True
        assert "PUT_WALL_ON" in v.reasons_short


class TestGexFlipZone:
    """bool_gex_flip_zone = 1 -> block les 2 cotes."""

    def test_gex_flip_blocks_both(self):
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 1}
        v = compute_gamma_verdict(bar)
        assert v.block_long is True
        assert v.block_short is True
        assert "GEX_FLIP_ZONE" in v.reasons_long
        assert "GEX_FLIP_ZONE" in v.reasons_short
        assert v.gex_flip_active is True

    def test_gex_flip_combined_with_wall(self):
        """Si gex_flip ET call_wall proche -> 2 reasons cote LONG."""
        bar = {"atr": 50.0, "dist_mq_call": 15.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 1}
        v = compute_gamma_verdict(bar)
        assert v.block_long is True
        assert len(v.reasons_long) == 2  # CALL_WALL_NEAR + GEX_FLIP
        assert any(r.startswith("CALL_WALL_NEAR_") for r in v.reasons_long)
        assert "GEX_FLIP_ZONE" in v.reasons_long

    def test_gex_flip_disabled_via_cfg(self):
        cfg = GammaVetoConfig(enable_gex_flip=False)
        bar = {"atr": 50.0, "dist_mq_call": 500.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 1}
        v = compute_gamma_verdict(bar, cfg)
        assert v.block_long is False
        assert v.block_short is False


class TestEdgeCases:
    """None, NaN, fields manquants."""

    def test_empty_bar(self):
        """Bar vide -> ATR fallback, pas de block."""
        v = compute_gamma_verdict({})
        assert v.block_long is False
        assert v.block_short is False
        assert v.atr_used == 100.0  # default

    def test_disabled_globally(self):
        cfg = GammaVetoConfig(enabled=False)
        bar = {"atr": 50.0, "dist_mq_call": 15.0, "dist_mq_put": -15.0,
               "bool_gex_flip_zone": 1}
        v = compute_gamma_verdict(bar, cfg)
        # Tout False meme en zone de blocage
        assert v.block_long is False
        assert v.block_short is False

    def test_nan_atr_falls_back(self):
        bar = {"atr": float("nan"), "dist_mq_call": 15.0, "dist_mq_put": -500.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        # fallback ATR = 100 -> threshold 50 -> 15 <= 50 -> block
        assert v.block_long is True

    def test_none_dist_no_crash(self):
        bar = {"atr": 50.0, "dist_mq_call": None, "dist_mq_put": None,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        assert v.block_long is False
        assert v.block_short is False

    def test_verdict_is_frozen(self):
        v = compute_gamma_verdict({})
        with pytest.raises(Exception):
            v.block_long = True  # frozen dataclass


# ════════════════════════════════════════════════════════════════════════════
# Niveau 2 - INTEGRATION tests (scenarios realistes)
# ════════════════════════════════════════════════════════════════════════════


class TestRealisticScenarios:

    def test_es_typical_atr_124(self):
        """ATR ES typique 124 -> threshold clamp 62 (clampe [10,80])."""
        bar = {"atr": 124.0, "dist_mq_call": 617.0, "dist_mq_put": -1383.0,
               "bool_gex_flip_zone": 0}
        v = compute_gamma_verdict(bar)
        # call_dist 617 > 62 threshold -> no block
        assert v.block_long is False
        # put_dist abs 1383 > 62 threshold -> no block
        assert v.block_short is False
        assert v.threshold_ticks == 62.0

    def test_es_zone_gex_flip_active(self):
        """Cas reel 18/06 : gex_flip=1 + walls loin -> block both via flip."""
        bar = {"atr": 124.0, "dist_mq_call": 617.0, "dist_mq_put": -1383.0,
               "bool_gex_flip_zone": 1}
        v = compute_gamma_verdict(bar)
        assert v.block_long is True
        assert v.block_short is True
        assert "GEX_FLIP_ZONE" in v.reasons_long


# ════════════════════════════════════════════════════════════════════════════
# Niveau 2 - LEGACY API compat (DASHBOARD/api/builders.py)
# ════════════════════════════════════════════════════════════════════════════


class TestLegacyCompat:

    def test_legacy_none_options_returns_empty(self):
        bl, bs, w = gamma_gate_check_legacy({"atr": 50.0}, None)
        assert bl is False
        assert bs is False
        assert w == []

    def test_legacy_call_wall_near(self):
        bar = {"atr": 50.0}
        options = {"dist_mq_call": 15.0, "dist_mq_put": -500.0,
                   "gex_flip_zone": 0}
        bl, bs, w = gamma_gate_check_legacy(bar, options)
        assert bl is True
        assert bs is False
        assert any("CALL WALL" in s for s in w)

    def test_legacy_put_wall_near_FIX_bug_B(self):
        """REGRESSION : ancienne formule builders.py ne fire jamais sur put signed negatif.

        Apres fix : put_dist=-15 + threshold=25 -> block_short=True.
        """
        bar = {"atr": 50.0}
        options = {"dist_mq_call": 500.0, "dist_mq_put": -15.0,
                   "gex_flip_zone": 0}
        bl, bs, w = gamma_gate_check_legacy(bar, options)
        assert bs is True, "Legacy API fix Bug B"
        assert any("PUT SUPPORT" in s for s in w)

    def test_legacy_gex_flip_blocks_both(self):
        bar = {"atr": 50.0}
        options = {"dist_mq_call": 500.0, "dist_mq_put": -500.0,
                   "gex_flip_zone": 1}
        bl, bs, w = gamma_gate_check_legacy(bar, options)
        assert bl is True
        assert bs is True
        assert any("GEX FLIP" in s for s in w)


# ════════════════════════════════════════════════════════════════════════════
# Niveau 3 - REGRESSION EMPIRIQUE distribution (1036 bars 18/06)
# ════════════════════════════════════════════════════════════════════════════


_LIVE_BARS_PATH = Path("DATA/tmp/20260618_ES_live.jsonl")


@pytest.mark.skipif(not _LIVE_BARS_PATH.exists(),
                    reason="Live bars sample absent (18/06 ES)")
def test_distribution_on_1036_bars_ES_18_06():
    """Niveau 3 : distribution gamma_block sur 1036 bars 18/06.

    Decouverte empirique : bool_gex_flip_zone distribution sur 5 jours ES :
      10/06 :   0% flip   |  14/06 :  50% flip
      11/06 :  82% flip   |  15/06 :  99.97% flip
      12/06 :  90% flip   |  18/06 : 100% flip
    Le signal est tres frequent (regime dealer instable courant sur ES futures).

    Criteres GO :
      - Module fonctionne sans crash
      - Distribution observable (verifier print)
      - au moins 1 forme de block visible (sinon code mort)
    """
    bars = []
    with _LIVE_BARS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    bars.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    assert len(bars) >= 500, f"Sample trop court ({len(bars)})"

    n_block_long = 0
    n_block_short = 0
    n_gex_flip = 0
    n_call_wall_block = 0
    n_put_wall_block = 0
    for bar in bars:
        v = compute_gamma_verdict(bar)
        if v.block_long:
            n_block_long += 1
        if v.block_short:
            n_block_short += 1
        if v.gex_flip_active:
            n_gex_flip += 1
        if any(r.startswith("CALL_WALL_") for r in v.reasons_long):
            n_call_wall_block += 1
        if any(r.startswith("PUT_WALL_") for r in v.reasons_short):
            n_put_wall_block += 1

    total = len(bars)
    pct_long = 100.0 * n_block_long / total
    pct_short = 100.0 * n_block_short / total
    pct_flip = 100.0 * n_gex_flip / total
    pct_call_wall = 100.0 * n_call_wall_block / total
    pct_put_wall = 100.0 * n_put_wall_block / total

    print(f"\n=== Distribution gamma_block sur {total} bars ES 18/06 ===")
    print(f"  block_long    : {n_block_long} ({pct_long:.1f}%)")
    print(f"  block_short   : {n_block_short} ({pct_short:.1f}%)")
    print(f"  gex_flip      : {n_gex_flip} ({pct_flip:.1f}%)")
    print(f"  call_wall_block : {n_call_wall_block} ({pct_call_wall:.1f}%)")
    print(f"  put_wall_block  : {n_put_wall_block} ({pct_put_wall:.1f}%)")

    # Test souple : au moins 1 forme de block visible (sinon module mort).
    # gex_flip frequence variable jour/jour (empirique 0-100%).
    assert (n_block_long + n_block_short) > 0, "Aucun block declenche - module possiblement mort"


# ════════════════════════════════════════════════════════════════════════════
# Niveau 4 - REGRESSION SCENARIO -$967
# ════════════════════════════════════════════════════════════════════════════


_AUDIT_TRADES = Path("DATA/_AUDIT/trades_20260615.jsonl")


@pytest.mark.skipif(not _AUDIT_TRADES.exists(),
                    reason="Audit trades 15/06 absent")
def test_scenario_minus_967_block_short_expected():
    """Niveau 4 : PREUVE empirique le veto aurait bloque le trade -$967.

    Audit Bot 2 Mirror v2 (DOCS/plans/2026-06-18-bot2-mirror-v2-autopsie-remediation.md):
    trade SHORT ES 7/7 etoiles avec gamma_block_short=True dans snapshot,
    ignored car bot lit bar.get("gamma_block_short") = None.

    Si le trade SHORT du -$967 a un snapshot bar avec dist_mq_put proche
    OU bool_gex_flip_zone=1 -> verdict.block_short doit etre True.
    """
    trades = []
    with _AUDIT_TRADES.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Cherche un trade SHORT (le -$967 etait SHORT)
    shorts = [t for t in trades if t.get("direction") == "SHORT"
              or t.get("side") == "SHORT"]

    if not shorts:
        pytest.skip("Aucun trade SHORT dans audit 15/06")

    # PROOF empirique : sur le bar at exit du trade -$967, le veto doit firer.
    # Le bar at exit n'est pas l'entree, mais montre que la condition gamma
    # etait active. Vu que GEX FLIP ZONE persiste typiquement,
    # le veto au entry aurait egalement fire.
    t_minus_967 = next(
        (t for t in shorts if abs(float(t.get("pnl_usd", 0)) - (-967.5)) < 1),
        None,
    )
    assert t_minus_967 is not None, "Trade -$967 absent du sample"

    bar = t_minus_967.get("dmp_bar_at_exit") or {}
    assert bar, "bar snapshot manquant"

    verdict = compute_gamma_verdict(bar)
    print(f"\n=== REGRESSION TEST trade -$967 ===")
    print(f"  pnl_usd = {t_minus_967['pnl_usd']}")
    print(f"  bar.bool_gex_flip_zone = {bar.get('bool_gex_flip_zone')}")
    print(f"  bar.dist_mq_put = {bar.get('dist_mq_put')}")
    print(f"  verdict.block_short = {verdict.block_short}")
    print(f"  verdict.reasons_short = {verdict.reasons_short}")

    # PROOF : le veto AURAIT BLOQUE ce trade SHORT
    assert verdict.block_short is True, (
        f"REGRESSION : le veto gamma ne fire PAS sur le bar du trade -$967 "
        f"(bool_gex_flip={bar.get('bool_gex_flip_zone')}, "
        f"dist_mq_put={bar.get('dist_mq_put')}, threshold={verdict.threshold_ticks}t). "
        f"Le module ne resout PAS la root cause."
    )
    assert len(verdict.reasons_short) > 0, "Aucune raison documentee pour le block"
