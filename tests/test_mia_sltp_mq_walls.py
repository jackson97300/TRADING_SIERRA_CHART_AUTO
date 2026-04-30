"""Tests SLTPEngine — niveaux MenthorQ promus en TIER1/TIER2 + garde CAS 4
anti-TP-derriere-mur.

Date : 2026-04-30 (Jackson : "ON DOIS LISTER LES NIVEAU MENTHORQ COMME MUR")

Bug observe screen ES SHORT 30/04 :
- Entry @ 7206.50, prix 7203.75, mur "Call Resistance + Call Resistance 0DTE +
  Gamma Wall 0DTE" empile @ 7199.46, TP @ 7199.25 = 1 tick DERRIERE le mur.
- Cause racine : niveaux MenthorQ classiques (dist_mq_call/put) absents de
  TIER1+TIER2 + 0DTE en TIER3 non scanne (rollback 28/04).
- Cause secondaire : meme avec MQ_CALL detecte, R:R 0.93 < MIN_RR_SELECTION
  (1.5) → fallback TP_STANDARD 30t qui passait DERRIERE le mur 28t.

Fix 30/04 :
1. dist_mq_call_0dte / dist_mq_put_0dte / dist_mq_hvl_0dte → TIER1
2. dist_mq_call / dist_mq_put / dist_mq_hvl → TIER2
3. CAS 4 dans _evaluate : si TP_STANDARD passerait DERRIERE un mur scanne,
   capote TP DEVANT le mur (sacrifie R:R minimum pour TP atteignable).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from CORE.mia_sltp import (  # noqa: E402
    MIN_RR_RATIO,
    SLTPEngine,
    TIER1_WALLS,
    TIER2_WALLS,
    TIER3_WALLS,
)


# ── Tests TIER1/TIER2 contiennent les niveaux MQ ─────────────────────


class TestMqLevelsInTiers:
    """Pin que les niveaux MenthorQ sont bien presents dans TIER1/TIER2."""

    def test_tier1_contains_mq_0dte_levels(self):
        """3 niveaux 0DTE en TIER1 (vrais murs, expiration jour J)."""
        assert "dist_mq_call_0dte" in TIER1_WALLS
        assert "dist_mq_put_0dte" in TIER1_WALLS
        assert "dist_mq_hvl_0dte" in TIER1_WALLS

    def test_tier1_mq_levels_role_both(self):
        """role='both' obligatoire pour scanner dans les 2 directions."""
        for col in ("dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte"):
            _, role = TIER1_WALLS[col]
            assert role == "both", f"{col} role={role}, attendu 'both'"

    def test_tier2_contains_mq_classic_levels(self):
        """3 niveaux MQ classiques en TIER2 (call/put/hvl non-0DTE)."""
        assert "dist_mq_call" in TIER2_WALLS
        assert "dist_mq_put" in TIER2_WALLS
        assert "dist_mq_hvl" in TIER2_WALLS

    def test_tier3_no_mq_levels_anymore(self):
        """Anti-doublon : les MQ ne doivent PAS rester dans TIER3."""
        mq_cols_in_t3 = [k for k in TIER3_WALLS if k.startswith("dist_mq_")]
        assert mq_cols_in_t3 == [], \
            f"MQ levels promus en T1/T2 doivent disparaitre de T3, trouve : {mq_cols_in_t3}"

    def test_no_overlap_between_tiers(self):
        """Aucun col ne doit etre dans 2 tiers (sinon double-scan)."""
        t1 = set(TIER1_WALLS)
        t2 = set(TIER2_WALLS)
        t3 = set(TIER3_WALLS)
        assert t1 & t2 == set(), f"Overlap T1-T2 : {t1 & t2}"
        assert t1 & t3 == set(), f"Overlap T1-T3 : {t1 & t3}"
        assert t2 & t3 == set(), f"Overlap T2-T3 : {t2 & t3}"


# ── Tests scan obstacles inclut MQ levels ────────────────────────────


def _build_row_with_mq(direction: int, **mq_distances) -> pd.Series:
    """Helper : construit une row avec NaN pour toutes les colonnes T1+T2
    sauf celles fournies dans **mq_distances."""
    row = pd.Series({"close": 7200.0, "atr_14_ticks": 22.0, "entry_signal": direction})
    for col in list(TIER1_WALLS) + list(TIER2_WALLS):
        row[col] = np.nan
    for col, val in mq_distances.items():
        row[col] = val
    return row


class TestMqLevelsScanned:
    """Verifie que les niveaux MQ sont effectivement vus par _scan_obstacles."""

    def test_short_scans_mq_call_0dte_below(self):
        """SHORT : MQ_Call 0DTE EN-DESSOUS = obstacle (support pour SHORT)."""
        engine = SLTPEngine(symbol="ES")
        row = _build_row_with_mq(direction=-1, dist_mq_call_0dte=-25.0)
        obstacles = engine._scan_obstacles(row, direction=-1)
        names = [o.name for o in obstacles]
        assert "MQ_CALL_0DTE" in names, \
            f"MQ_CALL_0DTE attendu pour SHORT avec dist=-25, got {names}"

    def test_long_scans_mq_call_0dte_above(self):
        """LONG : MQ_Call 0DTE AU-DESSUS = obstacle (resistance)."""
        engine = SLTPEngine(symbol="ES")
        row = _build_row_with_mq(direction=1, dist_mq_call_0dte=+30.0)
        obstacles = engine._scan_obstacles(row, direction=1)
        names = [o.name for o in obstacles]
        assert "MQ_CALL_0DTE" in names, \
            f"MQ_CALL_0DTE attendu pour LONG avec dist=+30, got {names}"

    def test_short_scans_mq_put_classic(self):
        """SHORT : MQ_Put classique TIER2 en-dessous = obstacle."""
        engine = SLTPEngine(symbol="ES")
        row = _build_row_with_mq(direction=-1, dist_mq_put=-40.0)
        obstacles = engine._scan_obstacles(row, direction=-1)
        names = [o.name for o in obstacles]
        assert "MQ_PUT" in names

    def test_short_scans_mq_hvl_above_filtered(self):
        """SHORT : MQ_HVL AU-DESSUS doit etre FILTRE (pas devant un SHORT)."""
        engine = SLTPEngine(symbol="ES")
        # Pour SHORT, on cherche obstacles EN BAS (dist < 0)
        # Si dist_mq_hvl > 0 (au dessus), il doit etre filtre
        row = _build_row_with_mq(direction=-1, dist_mq_hvl=+50.0)
        obstacles = engine._scan_obstacles(row, direction=-1)
        names = [o.name for o in obstacles]
        assert "MQ_HVL" not in names

    def test_obstacles_sorted_by_distance(self):
        """Confluence MQ : obstacles trie par abs_dist croissant."""
        engine = SLTPEngine(symbol="ES")
        # 3 niveaux empiles sous le prix pour SHORT
        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-28.0,  # T1 plus proche
            dist_mq_call=-28.0,        # T2 meme niveau
            dist_mq_hvl=-50.0,         # T2 plus loin
        )
        obstacles = engine._scan_obstacles(row, direction=-1)
        # Les 2 premiers sont a 28t (MQ_CALL_0DTE T1 + MQ_CALL T2)
        # Le 3eme est a 50t (MQ_HVL)
        assert len(obstacles) == 3
        # Premier groupe (28t) avant 50t
        assert obstacles[0].abs_dist == 28.0
        assert obstacles[1].abs_dist == 28.0
        assert obstacles[2].abs_dist == 50.0


# ── Tests CAS 4 anti-TP-derriere-mur ─────────────────────────────────


class TestCas4AntiTpBehindWall:
    """Verifie que le fallback TP_STANDARD ne traverse JAMAIS un mur scanne."""

    def test_es_short_screen_case_30042026(self):
        """Cas representatif du screen 30/04 : ES SHORT, mur MQ_Call empile
        TRES proche (~28t sous le prix). Bug AVANT : TP fallback 30t passait
        derriere le mur. Apres fix : CAS 4 capote TP DEVANT mur.

        Note : SL adapte a 18t (budget ES $75 = 20t max). Le scenario reste
        equivalent : mur a 28.16t et fallback TP_STANDARD a 30t (cap V47),
        donc le mur est SUR LE CHEMIN du TP fallback → CAS 4 active.
        """
        engine = SLTPEngine(symbol="ES")
        TICK = 0.25
        entry = 7200.0
        mur_price = entry - 28.16 * TICK  # 7192.96, mur fractionnaire
        dist_signed = (mur_price - entry) / TICK  # -28.16t

        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=dist_signed,
            dist_mq_call=dist_signed,
        )
        # SL via dist_gex_up=14t + buffer ES 4 = SL final 18t * 1.25 * 3 = $67.50 OK
        row["dist_gex_nearest_up"] = 14.0
        row["close"] = entry

        result = engine.evaluate_single(row, direction=-1)
        assert result.valid, f"Trade rejete : {result.reject_reason}"

        # SL final = 18t. Fallback TP_STANDARD = 18*2 = 36t → cap V47 ES = 30t
        # Mur MQ a 28.16t < 30 → CAS 4 trigger → TP_DEVANT_MQ_CALL_0DTE
        # floor(28.16 - 2) = 26t
        assert result.tp1_ticks == 26.0, \
            f"Expected floor(28.16-2)=26t, got {result.tp1_ticks}"
        assert result.tp1_wall == "TP_DEVANT_MQ_CALL_0DTE", \
            f"Expected TP_DEVANT_MQ_CALL_0DTE, got {result.tp1_wall}"
        # TP price tick-aligned ET DEVANT le mur (au-dessus pour SHORT)
        tp_price = entry - result.tp1_ticks * TICK
        assert tp_price == 7193.50, f"TP price expected 7193.50, got {tp_price}"
        assert tp_price > mur_price, \
            f"TP {tp_price} doit etre AU-DESSUS de mur {mur_price} pour SHORT"

    def test_long_no_wall_in_path_uses_standard(self):
        """Sanity : si AUCUN mur sur le chemin, TP_STANDARD non capote (CAS 4
        ne se declenche pas). LONG sans obstacle au-dessus → fallback 2R OK."""
        engine = SLTPEngine(symbol="NQ")
        # SL via murs en bas (LONG)
        row = _build_row_with_mq(
            direction=1,
            dist_gex_nearest_dn=-25.0,
            dist_ext_edge_buy=-25.0,
        )
        result = engine.evaluate_single(row, direction=1)
        assert result.valid
        # Aucun mur au-dessus → TP_STANDARD_NO_WALL standard (cap V47)
        assert "TP_STANDARD" in result.tp1_wall
        assert result.tp1_wall != "TP_DEVANT_"  # pas de capot CAS 4

    def test_cas4_does_not_trigger_when_obstacle_far(self):
        """Si fallback TP_STANDARD ne traverse PAS le mur (mur plus loin),
        CAS 4 ne s'active pas, on garde TP_STANDARD."""
        engine = SLTPEngine(symbol="ES")
        # SL=12t via cluster en bas, mur en haut TRES loin (200t)
        # → TP_STANDARD = 12*2 = 24t, mur a 200t, 24 < 200 → CAS 4 pas active
        row = _build_row_with_mq(
            direction=1,
            dist_cur_val=-10.0,
            dist_prev_val=-10.0,
            dist_gex_nearest_up=+200.0,  # tres loin
        )
        result = engine.evaluate_single(row, direction=1)
        assert result.valid
        # TP_STANDARD ou TP_STANDARD_WALL_FAR (mur > MAX_TP_WALL_DISTANCE), pas TP_DEVANT
        assert "TP_DEVANT" not in result.tp1_wall, \
            f"CAS 4 ne devrait pas trigger, got {result.tp1_wall}"

    def test_cas4_floor_keeps_tick_alignement(self):
        """floor() garantit tick-alignment meme si distance fractionnaire."""
        engine = SLTPEngine(symbol="ES")
        # mur @ 25.7t (fractionnaire) avec tp_buffer ES = 2
        # CAS 4 : tp_devant = floor(25.7 - 2) = 23t (entier)
        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-25.7,  # fractionnaire
        )
        row["dist_gex_nearest_up"] = 30.0  # SL=30t
        result = engine.evaluate_single(row, direction=-1)
        if result.valid:
            # Si CAS 4 trigger, tp_ticks doit etre entier (floor)
            assert result.tp1_ticks == int(result.tp1_ticks), \
                f"tp_ticks {result.tp1_ticks} non-entier (floor casse)"

    def test_cas4_respects_min_rr_ratio(self):
        """Si CAS 4 donne R:R < MIN_RR_RATIO (0.8), trade doit etre REJETE."""
        engine = SLTPEngine(symbol="ES")
        # SL=30t, mur a 5t (tres pres) → tp_devant = floor(5-2)=3t
        # R:R = 3/30 = 0.1 < 0.8 → reject
        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-5.0,  # mur tres pres
        )
        row["dist_gex_nearest_up"] = 30.0
        result = engine.evaluate_single(row, direction=-1)
        # Soit reject_reason rempli, soit obstacle filtre par abs_d<3 dans _check_wall_ahead
        # Dans tous les cas, on doit pas avoir un trade valide avec R:R 0.1
        if result.valid:
            assert result.rr_ratio >= MIN_RR_RATIO, \
                f"trade valid avec R:R {result.rr_ratio} < MIN_RR_RATIO {MIN_RR_RATIO}"

    def test_cas4_observability_flag_set(self):
        """R2 code-reviewer : verifier que cas4_triggered=True et
        cas4_blocked_wall renseigne sur trade ou CAS 4 capote."""
        engine = SLTPEngine(symbol="ES")
        TICK = 0.25
        entry = 7200.0

        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-28.0,
            dist_mq_call=-28.0,
        )
        row["dist_gex_nearest_up"] = 14.0
        row["close"] = entry

        result = engine.evaluate_single(row, direction=-1)
        assert result.valid
        assert result.cas4_triggered is True, \
            "cas4_triggered doit etre True quand TP_STANDARD est capote"
        assert result.cas4_blocked_wall == "MQ_CALL_0DTE", \
            f"cas4_blocked_wall doit etre MQ_CALL_0DTE, got {result.cas4_blocked_wall}"

    def test_cas4_exposes_exact_wall_dist_and_tp_pre(self):
        """R1+R2 code-reviewer review 2 : cas4_blocked_wall_dist +
        cas4_tp_standard_pre exposent les valeurs EXACTES (pas d'approximation
        cote caller). Avant fix, le caller utilisait `tp_ticks_use + 2`
        (hardcode tp_buffer ES=2 mais NQ=4) et `sl_ticks * 2.0` (faux
        car cap V47 applique avant CAS 4)."""
        engine = SLTPEngine(symbol="ES")
        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-28.0,
            dist_mq_call=-28.0,
        )
        row["dist_gex_nearest_up"] = 14.0
        row["close"] = 7200.0

        result = engine.evaluate_single(row, direction=-1)
        assert result.valid
        assert result.cas4_triggered is True

        # Distance exacte du mur (pas approx)
        assert result.cas4_blocked_wall_dist == 28.0, \
            f"wall_dist exact attendu 28t, got {result.cas4_blocked_wall_dist}"

        # tp_standard_pre = valeur APRES CAS 1/2/3 mais AVANT CAS 4 capot
        # Avec SL=18t (14 GEX + 4 buffer) → CAS 1 fallback = 36t → cap V47 ES = 30t
        assert result.cas4_tp_standard_pre == 30.0, \
            f"tp_standard_pre attendu 30t (cap V47 ES), got {result.cas4_tp_standard_pre}"

        # tp1_ticks final apres capot = floor(28-2) = 26
        assert result.tp1_ticks == 26.0

    def test_cas4_observability_flag_not_set_when_no_trigger(self):
        """Cas nominal sans CAS 4 : flags doivent rester False/empty."""
        engine = SLTPEngine(symbol="ES")
        # SL=12t avec confluence, mur a 80t (legitime, R:R 6.5) → _find_tp_obstacle
        # accepte, pas de fallback TP_STANDARD → CAS 4 jamais teste
        row = _build_row_with_mq(
            direction=1,
            dist_cur_val=-10.0,
            dist_prev_val=-10.0,
            dist_gex_nearest_up=+50.0,
        )
        result = engine.evaluate_single(row, direction=1)
        # Si trade valide via mur scanne, cas4_triggered doit etre False
        if result.valid and "TP_STANDARD" not in result.tp1_wall:
            assert result.cas4_triggered is False
            assert result.cas4_blocked_wall == ""

    def test_cas4_runner_tp3_coherent(self):
        """Reco code-reviewer : verifier tp3 (runner) reste coherent quand
        tp1 est capote par CAS 4. tp3 doit etre > tp1 (sinon fallback 1.5x)."""
        engine = SLTPEngine(symbol="ES")
        TICK = 0.25
        entry = 7200.0

        row = _build_row_with_mq(
            direction=-1,
            dist_mq_call_0dte=-28.0,
            dist_mq_call=-28.0,
        )
        row["dist_gex_nearest_up"] = 14.0
        row["close"] = entry

        result = engine.evaluate_single(row, direction=-1)
        if result.valid and result.cas4_triggered:
            # Coherence : tp3 (runner) doit etre >= tp1 (sinon non-sens runner)
            assert result.tp3_ticks >= result.tp1_ticks, \
                f"tp3 {result.tp3_ticks}t < tp1 {result.tp1_ticks}t (incoherent)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
