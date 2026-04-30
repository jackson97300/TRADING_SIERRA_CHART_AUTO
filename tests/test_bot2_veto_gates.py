"""Tests gates Bot 2 Plan A_v2 (Gate A color wall + Gate B SHORT no-wall).

FIX 30/04 (audit market-analyst Bot 2 + Phase 0 SHORTs n=8) :
- Gate A : VETO BUY si dist_color_dn_nearest_pct ∈ (0, 0.05]
- Gate B : VETO SHORT si tp_wall=FIXED/STANDARD/NO_WALL OR room < 1.5x SL

Anti Pattern 11 V1 : gates parametrables (cfg.veto_*), reversibles via flag.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import direct du helper module pour pin le contrat (refacto R1 30/04 :
# constante NO_WALL_TP_PATTERNS_* + is_synthetic_tp_wall extraites du flow inline)
from CORE.databento_paper_trader import is_synthetic_tp_wall


def _gate_a_veto_buy(direction, dist_color_dn_pct, veto_threshold):
    """Reproduit Gate A : VETO BUY si color_dn wall proche.

    Returns: True si veto applique (skip trade)
    """
    if direction != "BUY":
        return False
    if not veto_threshold or veto_threshold <= 0:
        return False
    if dist_color_dn_pct is None:
        return False
    if not isinstance(dist_color_dn_pct, (int, float)):
        return False
    return 0 < dist_color_dn_pct <= veto_threshold


def _gate_b_veto_short(direction, tp_wall, sl_ticks, tp_ticks, veto_enabled, room_min_ratio):
    """Reproduit Gate B : VETO SHORT si TP no-wall ou room insuffisant.

    Returns: (veto: bool, reason: str)
    """
    if direction != "SELL" or not veto_enabled:
        return False, ""
    tp_wall_str = str(tp_wall or "")
    is_no_wall = is_synthetic_tp_wall(tp_wall_str)
    room_ratio = (tp_ticks / sl_ticks) if sl_ticks and sl_ticks > 0 else 0
    insufficient_room = room_ratio < room_min_ratio
    if is_no_wall or insufficient_room:
        reasons = []
        if is_no_wall:
            reasons.append(f"tp_wall={tp_wall_str}")
        if insufficient_room:
            reasons.append(f"room={room_ratio:.2f}<{room_min_ratio}")
        return True, "+".join(reasons)
    return False, ""


# ── Gate A — VETO BUY color wall ──


class TestGateAVetoBuyColorWall(unittest.TestCase):
    def test_buy_with_color_dn_close_vetos(self):
        # color_dn at +0.03% = wall ~5 ticks above (NQ @ 27000)
        self.assertTrue(_gate_a_veto_buy("BUY", 0.03, 0.05))

    def test_buy_color_dn_at_threshold_inclusive(self):
        # 0.05 = threshold inclusive
        self.assertTrue(_gate_a_veto_buy("BUY", 0.05, 0.05))

    def test_buy_color_dn_just_above_threshold_no_veto(self):
        self.assertFalse(_gate_a_veto_buy("BUY", 0.06, 0.05))

    def test_buy_color_dn_negative_no_veto(self):
        # color zone in OTHER direction (= below price for BUY) → pas un mur
        self.assertFalse(_gate_a_veto_buy("BUY", -0.03, 0.05))

    def test_buy_color_dn_zero_no_veto(self):
        # 0% pile = pas un mur, deja sur le price
        self.assertFalse(_gate_a_veto_buy("BUY", 0.0, 0.05))

    def test_sell_no_veto_via_gate_a(self):
        # Gate A est SEULEMENT pour BUY
        self.assertFalse(_gate_a_veto_buy("SELL", 0.03, 0.05))

    def test_threshold_zero_disables_gate(self):
        # cfg.veto_buy_color_wall_pct = 0 → desactive
        self.assertFalse(_gate_a_veto_buy("BUY", 0.03, 0))

    def test_color_dn_none_no_veto(self):
        self.assertFalse(_gate_a_veto_buy("BUY", None, 0.05))

    def test_color_dn_string_no_veto(self):
        # Edge case : feature missing → string ou autre
        self.assertFalse(_gate_a_veto_buy("BUY", "N/A", 0.05))


# ── Gate B — VETO SHORT no-wall / insufficient room ──


class TestGateBVetoShortNoWall(unittest.TestCase):
    def test_short_with_fixed_tp_vetos(self):
        veto, reason = _gate_b_veto_short("SELL", "FIXED_40T_RR1.33", 30, 40, True, 1.5)
        self.assertTrue(veto)
        self.assertIn("FIXED_", reason)

    def test_short_with_standard_tp_vetos(self):
        veto, reason = _gate_b_veto_short("SELL", "TP_STANDARD_NO_WALL", 30, 60, True, 1.5)
        self.assertTrue(veto)
        # Pas room (60/30 = 2.0 >= 1.5) mais NO_WALL trigger
        self.assertIn("NO_WALL", reason)

    def test_short_with_real_wall_no_veto(self):
        # tp_wall = mur structurel real (GEX_DN, VWAP-1SD, etc.)
        veto, reason = _gate_b_veto_short("SELL", "GEX_DN", 30, 60, True, 1.5)
        self.assertFalse(veto)

    def test_short_room_below_ratio_vetos(self):
        # room = 30/30 = 1.0 < 1.5 → veto
        veto, reason = _gate_b_veto_short("SELL", "GEX_DN", 30, 30, True, 1.5)
        self.assertTrue(veto)
        self.assertIn("room=", reason)

    def test_short_room_at_threshold_just_passes(self):
        # room = 45/30 = 1.5 = threshold INCLUSIF (not inferior strict)
        veto, _ = _gate_b_veto_short("SELL", "GEX_DN", 30, 45, True, 1.5)
        self.assertFalse(veto)

    def test_short_room_below_threshold_vetos(self):
        # 44/30 = 1.46 < 1.5
        veto, reason = _gate_b_veto_short("SELL", "GEX_DN", 30, 44, True, 1.5)
        self.assertTrue(veto)

    def test_buy_no_veto_via_gate_b(self):
        # Gate B est SEULEMENT pour SELL
        veto, _ = _gate_b_veto_short("BUY", "FIXED_40T", 30, 40, True, 1.5)
        self.assertFalse(veto)

    def test_disabled_via_cfg_no_veto(self):
        # cfg.veto_short_no_wall = False
        veto, _ = _gate_b_veto_short("SELL", "FIXED_40T", 30, 40, False, 1.5)
        self.assertFalse(veto)

    def test_combined_no_wall_and_low_room(self):
        # 2 raisons
        veto, reason = _gate_b_veto_short("SELL", "TP_STANDARD_WALL_FAR", 30, 30, True, 1.5)
        self.assertTrue(veto)
        self.assertIn("STANDARD", reason)
        self.assertIn("room=", reason)


# ── Cas du trade ES SHORT 7197.50 nuit 30/04 (audit Phase 0) ──


class TestPhase0AuditCases(unittest.TestCase):
    """Verifier que Gate B aurait elimine les 3 SHORTs avec TP_NO_WALL identifies
    par audit Phase 0 (28-30/04 Bot 2)."""

    def test_audit_short_1_tp_no_wall_vetoed(self):
        # Trade #1 audit : NQ SHORT 28/04 19:22 with FIXED_40T_RR1.33 TP
        veto, _ = _gate_b_veto_short("SELL", "FIXED_40T_RR1.33", 30, 40, True, 1.5)
        self.assertTrue(veto)

    def test_audit_short_3_sess_high_no_tp_wall_vetoed(self):
        # Trade #3 : tp_wall='NO_WALL' (sl_wall='SESS_HIGH' donc SL OK)
        veto, _ = _gate_b_veto_short("SELL", "NO_WALL", 30, 50, True, 1.5)
        self.assertTrue(veto)

    def test_audit_short_8_vwap_2sd_no_tp_wall_vetoed(self):
        # Trade #8 : NQ SHORT TP NO_WALL
        veto, _ = _gate_b_veto_short("SELL", "TP_STANDARD_NO_WALL", 40, 60, True, 1.5)
        self.assertTrue(veto)

    def test_audit_short_with_tp_wall_passes(self):
        # Hypothetique SHORT avec tp_wall structurel (pas dans les 8 audits)
        # = on garde ce setup, audit confirme signal pas casse
        veto, _ = _gate_b_veto_short("SELL", "VWAP+1SD", 30, 50, True, 1.5)
        self.assertFalse(veto)


# ── Tests directs sur is_synthetic_tp_wall (R1 contrat) ──


class TestIsSyntheticTpWall(unittest.TestCase):
    """Pin le contrat de la fonction helper. Si SLTPEngine evolue, ces tests
    cassent et forcent a mettre a jour NO_WALL_TP_PATTERNS_*."""

    def test_fixed_prefix_is_synthetic(self):
        self.assertTrue(is_synthetic_tp_wall("FIXED_40T_RR1.33"))

    def test_fixed_alone_is_synthetic(self):
        self.assertTrue(is_synthetic_tp_wall("FIXED_30T"))

    def test_standard_substring_is_synthetic(self):
        self.assertTrue(is_synthetic_tp_wall("TP_STANDARD_NO_WALL"))
        self.assertTrue(is_synthetic_tp_wall("TP_STANDARD_WALL_FAR"))

    def test_no_wall_substring_is_synthetic(self):
        self.assertTrue(is_synthetic_tp_wall("NO_WALL"))

    def test_real_wall_not_synthetic(self):
        self.assertFalse(is_synthetic_tp_wall("GEX_DN"))
        self.assertFalse(is_synthetic_tp_wall("VWAP+1SD"))
        self.assertFalse(is_synthetic_tp_wall("HVL"))
        self.assertFalse(is_synthetic_tp_wall("SESS_HIGH"))
        self.assertFalse(is_synthetic_tp_wall("PUT_SUPPORT"))

    def test_empty_string_not_synthetic(self):
        self.assertFalse(is_synthetic_tp_wall(""))

    def test_none_not_synthetic(self):
        self.assertFalse(is_synthetic_tp_wall(None))

    def test_lowercase_fixed_not_matched_strict(self):
        # Convention : tp_wall est UPPER_SNAKE → "fixed_40t" minuscule ne match pas
        self.assertFalse(is_synthetic_tp_wall("fixed_40t"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
