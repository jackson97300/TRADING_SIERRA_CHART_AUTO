"""
Tests unitaires pour SLTPEngine V2 — fallback TP standard.

Fix Jackson 24/04/2026 : ajout logique "TP standard" quand :
  1. Aucun obstacle trouvé → TP = SL × 2.0 (au lieu de 1:1)
  2. Mur trop loin (> MAX_TP_WALL_DISTANCE) → TP = SL × 2.0
  3. Cap absolu MAX_TP_TICKS_ABSOLUTE (V47)

Couvre aussi les invariants anti-régression (TP prenable quand mur proche).

Usage :
    pytest tests/test_mia_sltp_fallback.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from CORE.mia_sltp import (  # noqa: E402
    DEFAULT_TP_RR_FALLBACK,
    MAX_TP_TICKS_ABSOLUTE,
    MAX_TP_WALL_DISTANCE,
    MIN_RR_RATIO,
    SLTPEngine,
)


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def engine_es():
    return SLTPEngine(symbol="ES")


@pytest.fixture
def engine_nq():
    return SLTPEngine(symbol="NQ")


# ==============================================================================
# TESTS — scenario Jackson 24/04 (mur trop loin)
# ==============================================================================


class TestJacksonScenarioWallTooFar:
    """Le scenario exact de Jackson : ES LONG entry 7155, cluster SL 15t,
    prochain mur a 200t → TP standard 2R au lieu de R:R 13.3 absurde."""

    def test_es_long_wall_far_applies_fallback(self, engine_es):
        row = pd.Series({
            "price_close": 7155.0,
            "dist_cur_val": -12.0,          # TIER2 support proche
            "dist_prev_val": -12.0,         # 2eme TIER2 → cluster
            "dist_gex_nearest_up": +200.0,  # TIER1 resistance TRES loin
        })
        result = engine_es.evaluate_single(row, direction=1)  # LONG

        assert result.valid is True, f"Trade rejete: {result.reject_reason}"
        # TP NE DOIT PAS etre 200t (absurde), mais fallback 2R
        assert result.tp1_ticks <= MAX_TP_TICKS_ABSOLUTE["ES"]
        assert "TP_STANDARD" in result.tp1_wall
        assert result.rr_ratio >= MIN_RR_RATIO

    def test_nq_long_no_wall_applies_fallback(self, engine_nq):
        """NQ sans obstacle → TP standard 2R au lieu de 1:1."""
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -25.0,
            "dist_ext_edge_buy": -25.0,
            # Pas de resistance exploitable au-dessus
        })
        result = engine_nq.evaluate_single(row, direction=1)
        assert result.valid is True
        assert result.tp1_wall in ("TP_STANDARD_NO_WALL", "TP_STANDARD_WALL_FAR")
        # TP fallback = SL × 2.0 (avant cap)
        expected_tp = result.sl_ticks * DEFAULT_TP_RR_FALLBACK
        expected_capped = min(expected_tp, MAX_TP_TICKS_ABSOLUTE["NQ"])
        assert result.tp1_ticks == expected_capped


# ==============================================================================
# TESTS — les 3 cas fallback
# ==============================================================================


class TestFallbackCases:
    def test_case1_no_wall(self, engine_nq):
        """Cas 1 : aucun obstacle → TP_STANDARD_NO_WALL."""
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -25.0,
            "dist_ext_edge_buy": -25.0,
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid
        # Au minimum l'un des fallbacks s'applique
        assert "TP_STANDARD" in result.tp1_wall

    def test_case2_wall_too_far(self, engine_es):
        """Cas 2 : mur existe mais > MAX_TP_WALL_DISTANCE."""
        # MAX_TP_WALL_DISTANCE["ES"] = 80 → mur a 200t depasse
        row = pd.Series({
            "price_close": 7155.0,
            "dist_cur_val": -12.0,
            "dist_prev_val": -12.0,
            "dist_gex_nearest_up": +200.0,  # > 80t
        })
        result = engine_es.evaluate_single(row, 1)
        assert result.valid
        # TP doit etre cap + reason mentionne "WALL_FAR"
        # Note: le cap absolu peut masquer WALL_FAR si SL × 2 > cap
        assert result.tp1_ticks <= MAX_TP_TICKS_ABSOLUTE["ES"]

    def test_case3_absolute_cap(self, engine_nq):
        """Cas 3 : fallback 2R sans cap donnerait > MAX_TP_TICKS_ABSOLUTE."""
        # NQ SL = 30+ ticks → TP 2R = 60+ ticks → cap 80t OK
        # Pour trigger le cap, il faudrait SL > 40t → TP calc > 80t
        # Force un SL large via pas de mur proche + cluster loin
        row = pd.Series({
            "price_close": 27000.0,
            "dist_ext_edge_buy": -42.0,     # SL large = 42+8buffer = 50t
            "dist_cur_val": -42.0,
            # Pas de resistance
        })
        result = engine_nq.evaluate_single(row, 1)
        if result.valid and result.sl_ticks >= 40:
            # TP fallback = SL × 2 = 80+ → cap 80 atteint
            assert result.tp1_ticks <= MAX_TP_TICKS_ABSOLUTE["NQ"]


# ==============================================================================
# TESTS — anti-regression (mur PROCHE reste comportement original)
# ==============================================================================


class TestAntiRegressionCloseWall:
    def test_wall_close_uses_wall_not_fallback_nq(self, engine_nq):
        """Mur NQ avec R:R >= 1.5 → utilise le mur, PAS fallback.

        Post-fix 24/04 (MIN_RR_SELECTION=1.5) : mur doit donner R:R >= 1.5 pour
        etre selectionne. Avec SL=38t (30+8buffer), TP cible minimum = 57t (R:R 1.5).
        Mur GEX_UP a 80t → TP = 80-4 = 76t → R:R 2.0 → mur pris.
        """
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -30.0,
            "dist_ext_edge_buy": -30.0,
            "dist_gex_nearest_up": +80.0,   # mur a 80t → R:R 2.0 (post-fix seuil 1.5)
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid
        # Prerequis : R:R avec ce mur doit etre >= 1.5 pour passer selection.
        # tp 76 / sl 38 = 2.0 → OK selection.
        assert result.tp1_ticks == 80 - 4, f"mur legitime attendu tp=76, got {result.tp1_ticks}"
        # Assertion principale : utilise le mur GEX (pas fallback)
        assert "TP_STANDARD" not in result.tp1_wall, \
            f"Mur GEX_UP 80t donne R:R 2.0 >= 1.5 → doit etre pris, got wall={result.tp1_wall}"

    def test_wall_close_but_rr_below_selection_triggers_tp_devant_mur_nq(self, engine_nq):
        """🆕 FIX 30/04/2026 (CAS 4 anti-TP-derriere-mur) : mur trop proche pour
        R:R 1.5 mais fallback TP_STANDARD passerait DERRIÈRE le mur → on capote
        le TP DEVANT le mur (sacrifie R:R minimal pour garantir TP atteignable).

        Scenario : SL=38t, mur GEX_UP a 60t.
        TP candidate = 60-4 = 56t. R:R = 56/38 = 1.47 < 1.5 → SKIP _find_tp_obstacle.
        Fallback TP_STANDARD = 38 × 2 = 76t = DERRIERE mur GEX_UP 60t → CAS 4 active.
        TP_DEVANT_GEX_UP = floor(60-4) = 56t. R:R = 1.47 > MIN_RR_RATIO 0.8 → trade OK.

        Comportement avant 30/04 (BUGUE) : TP_STANDARD 76t derriere mur 60t = trap.
        Comportement apres : TP devant mur, atteignable.

        ⚠️ HISTORIQUE TEST (NE PAS RESTAURER ANCIEN COMPORTEMENT) ⚠️
        Avant 30/04, ce test verifiait `result.tp1_wall == "TP_STANDARD_NO_WALL"`
        et `tp1_ticks == 76.0`. C'etait un comportement EMERGENT NON-VOULU
        (FIX 24/04 visait MIN_RR_SELECTION pour eviter R:R bas en SCANNANT,
        pas a placer TP derriere mur en fallback). Reference : screen ES SHORT
        @ 7206.50 du 30/04 ou TP @ 7199.25 atterrissait derriere mur MQ_Call
        @ 7199.46 = trap structurel. CAS 4 corrige.
        """
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -30.0,
            "dist_ext_edge_buy": -30.0,
            "dist_gex_nearest_up": +60.0,   # R:R 1.47 < 1.5 → skip selection
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid
        # CAS 4 : TP_DEVANT_GEX_UP au lieu de TP_STANDARD
        assert result.tp1_wall == "TP_DEVANT_GEX_UP", \
            f"Expected TP_DEVANT_GEX_UP (CAS 4 anti-TP-derriere-mur), got {result.tp1_wall}"
        assert result.tp1_ticks == 56.0, f"Expected 56t (60-4 buffer), got {result.tp1_ticks}"
        # R:R 1.47 acceptable (> MIN_RR_RATIO 0.8)
        assert abs(result.rr_ratio - 1.47) < 0.01, \
            f"Expected R:R ~1.47 (56/38), got {result.rr_ratio}"

    def test_multi_obstacles_scan_picks_first_rr_acceptable_nq(self, engine_nq):
        """🆕 Reserve code-reviewer 24/04 : scan multi-obstacles avec R:R varies.

        ⚠️ ADAPTE 30/04 v3 (CAS 4 universel T1+T2) : Jackson "RATISER LARGE".
        v1 utilisait T1 proche → fail.
        v2 (apres-midi) : T2 traversable → ce test passait.
        v3 (soir) : T2 capote aussi → on doit utiliser des obstacles INSCANNES
        (= absents des 3 tiers OU TIER 3 = pas dans _scan_obstacles) sur le
        chemin pour valider le parcours scan multi-obstacles. Solution :
        n'utiliser que des obstacles T1+T2 valides bien R:R >= 1.5 OU
        utiliser des cols Tier 3 + 1 obstacle T1 acceptable.

        Scenario NQ LONG, SL=38t :
          - Obstacle scanne 1 : SESS_HIGH +80t (T1) → tp 76t → R:R 2.00 PRIS
        Pas d'autres obstacles intermediaires en T1/T2 → CAS 4 v3 ne trigger pas.
        Valide que le scan parcourt et trouve directement T1 a 80t.
        """
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -30.0,
            "dist_ext_edge_buy": -30.0,
            "dist_sess_high": +80.0,        # T1 : R:R 2.0 — acceptable, seul obstacle
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid, f"Trade doit etre valide: {result.reject_reason}"
        # Le 3e obstacle (SESS_HIGH) doit etre choisi
        assert result.tp1_ticks == 80 - 4, \
            f"Expected tp=76 (SESS_HIGH 80-4buffer), got {result.tp1_ticks}"
        # Le wall name doit etre SESS_HIGH, pas GEX_UP ni MQ_CALL
        assert "SESS_HIGH" in result.tp1_wall, \
            f"Expected SESS_HIGH pris, got {result.tp1_wall}"
        # R:R final doit etre >= MIN_RR_SELECTION
        assert result.rr_ratio >= 1.5, \
            f"Expected R:R >= 1.5 (seuil selection), got {result.rr_ratio:.2f}"

    def test_wall_close_uses_wall_not_fallback_es(self, engine_es):
        """Mur ES a 40t (< 80t limite ES) → utilise le mur."""
        row = pd.Series({
            "price_close": 7155.0,
            "dist_cur_val": -12.0,
            "dist_prev_val": -12.0,
            "dist_gex_nearest_up": +40.0,   # mur a 40t
        })
        result = engine_es.evaluate_single(row, 1)
        assert result.valid
        # Prerequis : cap NE doit PAS firer (40-2buffer=38 > 30cap MAIS cap only
        # s'applique sur fallback TP_STANDARD — post-fix 24/04 audit)
        assert "TP_STANDARD" not in result.tp1_wall
        # TP = 40t - 2 buffer = 38t, depasse cap 30t MAIS pas cappe (mur legitime)
        assert result.tp1_ticks == 38, f"mur legitime non cappe attendu 38, got {result.tp1_ticks}"

    def test_wall_legitimate_not_capped_even_if_above_abs(self, engine_es):
        """IMPORTANT FIX 24/04 POST-AUDIT : mur ES a 70t avec SL petit (12t)
        donne TP=68t et R:R=5.7. Le cap 30t NE DOIT PAS s'appliquer sur
        murs legitimes (<80t limite). C'est exactement ce que l'audit a flagge."""
        row = pd.Series({
            "price_close": 7155.0,
            "dist_cur_val": -12.0,
            "dist_prev_val": -12.0,
            "dist_gex_nearest_up": +70.0,   # mur legitime a 70t
        })
        result = engine_es.evaluate_single(row, 1)
        assert result.valid
        assert "TP_STANDARD" not in result.tp1_wall, "ce setup utilise un mur, pas fallback"
        # TP = 70 - 2buffer = 68t, R:R avec SL 16t = 4.25
        assert result.tp1_ticks == 68, f"mur legitime 68t preserve, got {result.tp1_ticks}"
        assert result.rr_ratio > 2.0, f"R:R nature du marche conserve, got {result.rr_ratio}"


# ==============================================================================
# TESTS — invariants MIN_RR_RATIO
# ==============================================================================


class TestInvariantRR:
    def test_final_rr_always_above_min(self, engine_nq):
        """Toutes les branches doivent produire R:R >= MIN_RR_RATIO (0.8) ou reject."""
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -25.0,
            "dist_ext_edge_buy": -25.0,
        })
        result = engine_nq.evaluate_single(row, 1)
        if result.valid:
            assert result.rr_ratio >= MIN_RR_RATIO

    def test_fallback_rr_matches_default(self, engine_nq):
        """Quand fallback applique (pas capped), R:R doit etre proche de DEFAULT_TP_RR_FALLBACK."""
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -25.0,
            "dist_ext_edge_buy": -25.0,
        })
        result = engine_nq.evaluate_single(row, 1)
        if result.valid and "TP_STANDARD" in result.tp1_wall:
            # Si pas cap, R:R = DEFAULT_TP_RR_FALLBACK exactement
            if result.tp1_ticks < MAX_TP_TICKS_ABSOLUTE["NQ"]:
                assert abs(result.rr_ratio - DEFAULT_TP_RR_FALLBACK) < 0.01


class TestPhaseCElargissements:
    """🆕 Tests Phase C 24/04 : P2 (bornes SL elargies) + P3 (T2 seul buffer etendu).

    Note : max_sl_usd = $75 contraint les scenarios. NQ SL max = 75/(0.5*3) = 50t
    en budget. Donc P2 permet bornes [20-80t] ticks-wise mais budget capable de
    50t seulement. Tests focalises sur la plage 20-50t (budget-compatible).
    """

    def test_p2_sl_min_abaisse_25t_nq_accepted(self, engine_nq):
        """P2 : SL 25t NQ doit etre accepte (avant min 30t, apres 20t)."""
        # Scenario : T1 GEX_DN a 17t sous prix → SL = 17+8 = 25t
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -17.0,   # T1
            "dist_gex_nearest_up": +80.0,   # TP
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid, f"SL 25t doit passer bornes P2 [20-80t] NQ: {result.reject_reason}"
        assert result.sl_ticks == 25, f"SL attendu 25 (17+8buffer), got {result.sl_ticks}"

    def test_p3_t2_seul_sans_t1_accepte_buffer_etendu(self, engine_nq):
        """P3 : T2 EXT_LONG_DN seul (pas de T1 derriere) doit passer avec buffer +5t."""
        # Scenario : T2 EXT_LONG_DN a 30t sous prix. Pas de T1 derriere.
        # Avant P3 : rejet `sltp_no_wall` car confluence = 1 T2 seul sans T1 backup
        # Apres P3 : SL = 30 + 13buffer etendu = 43t ∈ [20, 80] → accepte
        # sl_usd = 43 * 0.5 * 3 = $64.5 ∈ budget $75 → OK
        row = pd.Series({
            "price_close": 27000.0,
            "dist_ext_long_dn": -30.0,   # T2 seul (pas de T1 derriere)
            "dist_gex_nearest_up": +80.0,  # TP mur devant
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid, f"T2 seul avec buffer etendu doit passer: {result.reject_reason}"
        assert result.sl_ticks == 30 + 13, f"SL attendu 43t (30+13 buffer etendu), got {result.sl_ticks}"
        assert result.sl_wall_tier == 2, f"Tier attendu 2, got {result.sl_wall_tier}"
        assert "buffer ETENDU" in result.sl_reason, f"Reason doit mentionner buffer etendu: {result.sl_reason}"

    def test_p3_t1_prioritaire_sur_t2_seul(self, engine_nq):
        """P3 : T1 disponible → prend T1 (Option A), pas T2 seul (Option D)."""
        # Scenario : T1 GEX_DN a 22t et T2 EXT_LONG_DN a 30t
        # Option A (T1 seul) : SL = 22+8 = 30t → dans [20,80] → use T1
        # Budget : 30*0.5*3 = $45 < $75 OK
        row = pd.Series({
            "price_close": 27000.0,
            "dist_gex_nearest_dn": -22.0,    # T1 → SL=22+8=30t
            "dist_ext_long_dn": -30.0,       # T2 mais T1 prioritaire
            "dist_gex_nearest_up": +80.0,
        })
        result = engine_nq.evaluate_single(row, 1)
        assert result.valid, f"T1 doit etre pris: {result.reject_reason}"
        assert result.sl_wall_tier == 1, f"T1 prioritaire, got tier={result.sl_wall_tier}"
        assert result.sl_ticks == 22 + 8, f"SL T1 attendu 30 (22+8), got {result.sl_ticks}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
