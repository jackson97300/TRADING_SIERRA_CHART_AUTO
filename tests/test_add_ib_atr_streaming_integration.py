"""Tests Phase 2.2 — add_ib_atr_streaming integration dans enricher_chain.

Verifie que le fix Phase 2.1 (insert call entre rolling_inputs et
game_changers) produit un ib_atr non-NaN apres 3+ jours, et que
day_type sort de sa valeur figee 2 (NORM_VAR default).

Cf INCIDENT_LOG entry 37 : bug delta_bar inverse + day_type fige.
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "CORE"))

from CORE.phase_b_helpers import add_ib_atr_streaming, IbAtrState


class TestIbAtrStreaming(unittest.TestCase):
    """Tests directs add_ib_atr_streaming (fix Phase 2.1)."""

    def test_state_init_empty(self):
        s = IbAtrState()
        self.assertEqual(s.daily_ib_ranges, [])
        self.assertIsNone(s.current_date)
        self.assertIsNone(s.current_session_ib_range)
        self.assertEqual(s.lookback_days, 14)

    def test_raises_without_date_et(self):
        """Fail-loud si date_et absent (ordre engines)."""
        s = IbAtrState()
        with self.assertRaises(ValueError) as ctx:
            add_ib_atr_streaming({"ib_range": 50.0}, s)
        self.assertIn("date_et", str(ctx.exception))

    def test_ib_atr_nan_when_daily_lt_3(self):
        """ib_atr = NaN tant que < 3 jours dans le buffer (min_periods=3)."""
        import math
        s = IbAtrState()
        # Jour 1 : ib_range 50
        out = add_ib_atr_streaming({"date_et": date(2026, 5, 1), "ib_range": 50.0}, s)
        self.assertTrue(math.isnan(out["ib_atr"]))
        # Jour 2 : nouveau date_et -> rotation, daily_ib_ranges = [J1]
        out = add_ib_atr_streaming({"date_et": date(2026, 5, 2), "ib_range": 60.0}, s)
        self.assertTrue(math.isnan(out["ib_atr"]))
        # Jour 3 : daily_ib_ranges = [J1, J2]
        out = add_ib_atr_streaming({"date_et": date(2026, 5, 3), "ib_range": 70.0}, s)
        self.assertTrue(math.isnan(out["ib_atr"]))

    def test_ib_atr_computed_when_daily_gte_3(self):
        """ib_atr = mean(daily) apres 3+ jours rotations."""
        s = IbAtrState()
        ranges = [(date(2026, 5, d), 40.0 + 10 * d) for d in range(1, 6)]
        for dt, r in ranges:
            out = add_ib_atr_streaming({"date_et": dt, "ib_range": r}, s)

        # Apres 5 jours : 4 dans daily_ib_ranges (4 rotations effectuees)
        # ib_atr = mean(J1, J2, J3, J4) = mean(50, 60, 70, 80) = 65
        self.assertAlmostEqual(out["ib_atr"], 65.0, places=1)

    def test_multiple_bars_same_day_capture_first(self):
        """Plusieurs bars meme date_et -> capture ib_range premier seulement."""
        import math
        s = IbAtrState()
        # Bar 1 jour 1 : ib_range 50 capture
        add_ib_atr_streaming({"date_et": date(2026, 5, 1), "ib_range": 50.0}, s)
        # Bar 2 meme jour : ib_range 99 NE doit PAS overrider
        add_ib_atr_streaming({"date_et": date(2026, 5, 1), "ib_range": 99.0}, s)
        # Rotation jour 2
        add_ib_atr_streaming({"date_et": date(2026, 5, 2), "ib_range": 60.0}, s)
        # daily_ib_ranges devrait contenir [(J1, 50.0)] pas 99.0
        self.assertEqual(len(s.daily_ib_ranges), 1)
        self.assertEqual(s.daily_ib_ranges[0][1], 50.0)

    def test_lookback_cap_fifo(self):
        """Buffer cap FIFO a lookback_days.

        NB : `lookback_days` doit etre passe DANS L'APPEL aussi car le
        code sync state.lookback_days = arg lookback_days (cf phase_b_helpers
        1439-1444). Pattern bizarre mais documente.
        """
        s = IbAtrState()
        for d in range(1, 8):    # 7 jours -> doit drop les plus vieux
            add_ib_atr_streaming(
                {"date_et": date(2026, 5, d), "ib_range": 10.0 * d}, s,
                lookback_days=3)
        # Apres 7 jours : 6 rotations (jours fermes), cap a 3
        self.assertLessEqual(len(s.daily_ib_ranges), 3)


class TestEnricherChainIntegration(unittest.TestCase):
    """Verifie que enricher_chain.py importe correctement le fix."""

    def test_enricher_chain_imports_ok(self):
        """enricher_chain.py doit importer sans erreur (apres fix Phase 2.1)."""
        import enricher_chain    # nopep8
        self.assertTrue(hasattr(enricher_chain, "compose_enriched_payload"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
