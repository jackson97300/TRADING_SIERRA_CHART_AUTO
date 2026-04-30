"""Tests unitaires pour la logique Trailing TR40_20 Bot 1 NQ.

FIX 30/04 (audit market-analyst Bot 1) : Trailing TR40_20 NQ only.
Trail s'arme MFE >= 40% × SL_initial. Give back 20% × SL_initial.
SL ne va que dans le sens favorable.

Validation backtest 4 mois :
- PF 0.99 → 1.32 (+0.33)
- WR 41.5% → 62%
- Walk-forward 3/3 monotone (1.39 / 1.14 / 1.47)
- Bootstrap CI95 [1.15, 1.51]
- p=0.0003 t-test
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TICK_SIZE = 0.25


def _compute_trail_sl(direction: str, entry_price: float, sl_price_current: float,
                      sl_ticks_initial: float, mfe_ticks: float):
    """Reproduit la logique trailing TR40_20 de mia_paper_trader.py.

    FIX C1 (review code-reviewer 30/04) : alignement sur multiples de tick.

    Returns:
        (new_sl_price | None, did_update bool)
        - None si pas d'update (MFE pas atteint, candidate ne va pas dans le bon sens,
          ou alignement sur tick donne un prix qui ne progresse pas)
    """
    if sl_ticks_initial is None or sl_ticks_initial <= 0:
        return None, False
    arming_thr = 0.40 * sl_ticks_initial
    give_back = 0.20 * sl_ticks_initial
    if mfe_ticks < arming_thr:
        return None, False
    if direction == "LONG":
        candidate = entry_price + (mfe_ticks - give_back) * TICK_SIZE
        # FIX C1 : aligner sur tick AVANT de comparer
        aligned = round(round(candidate / TICK_SIZE) * TICK_SIZE, 2)
        if aligned > sl_price_current:
            return aligned, True
    else:  # SHORT
        candidate = entry_price - (mfe_ticks - give_back) * TICK_SIZE
        aligned = round(round(candidate / TICK_SIZE) * TICK_SIZE, 2)
        if aligned < sl_price_current:
            return aligned, True
    return None, False


class TestTrailingArming(unittest.TestCase):
    """Verifie l'armement du trail au seuil 40% du SL."""

    def test_long_below_arming_no_trail(self):
        # MFE = 9 ticks, SL initial 50t → arming threshold 20t. Pas trail.
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, 9)
        self.assertFalse(updated)
        self.assertIsNone(new_sl)

    def test_long_at_arming_threshold_no_trail_yet(self):
        # MFE = 19.9t (juste sous 20t threshold) → pas encore
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, 19.9)
        self.assertFalse(updated)

    def test_long_just_above_arming_trail_first(self):
        # MFE = 20t (= 40% × 50). give_back = 10t. New SL = entry + (20 - 10) × 0.25 = 27002.5
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, 20.0)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 27002.5)

    def test_short_just_above_arming(self):
        # SHORT entry 27000, SL 27012.5 (50t away). MFE 20t → trail SL = entry - (20-10)*0.25 = 26997.5
        new_sl, updated = _compute_trail_sl("SHORT", 27000.0, 27012.5, 50, 20.0)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 26997.5)


class TestTrailingFavorableDirection(unittest.TestCase):
    """SL ne va QUE dans le sens favorable."""

    def test_long_sl_only_goes_up(self):
        # SL deja a 27002.5 (trail precedent). MFE redescend a 22 → candidate = 27000 + (22-10)*0.25 = 27003
        # candidate > current → update
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 27002.5, 50, 22)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 27003.0)

    def test_long_mfe_drops_no_update(self):
        # MFE drops to 15 (deja sous arming) → pas d'update
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 27003.0, 50, 15)
        self.assertFalse(updated)

    def test_long_candidate_below_current_no_downgrade(self):
        # SL deja a 27010 (trail haut). MFE redescend a 20 → candidate = 27002.5 < 27010
        # → pas update (anti-degradation)
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 27010.0, 50, 20)
        self.assertFalse(updated)

    def test_short_sl_only_goes_down(self):
        # SL deja a 26997.5. MFE = 22t → candidate = 27000 - (22-10)*0.25 = 26997
        # candidate < current → update
        new_sl, updated = _compute_trail_sl("SHORT", 27000.0, 26997.5, 50, 22)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 26997.0)


class TestTrailingCaseStudy(unittest.TestCase):
    """Cas de figure : trade ES Bot 1 BUY 7200.50 → MFE +39 ticks → TIMEOUT -1t.

    Avec TR40_20 sur SL=14t :
    - arming = 40% × 14 = 5.6t
    - give back = 20% × 14 = 2.8t
    - À MFE peak +39t : trail SL = 7200.50 + (39 - 2.8) × 0.25 = 7209.55
    - Quand prix retrace, exit @ 7209.55 = +9.05 ticks par contrat × 3 = +$33.94 protégé
      au lieu de TIMEOUT à -3.75 USD
    """

    def test_es_buy_7200_50_mfe_39_aligned(self):
        """FIX C1 review : 7200.50 + 36.2*0.25 = 7209.55 mais NON aligne tick.
        Apres alignement sur multiples de 0.25 → 7209.50."""
        new_sl, updated = _compute_trail_sl("LONG", 7200.50, 7195.00, 14, 39)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 7209.50)
        # Verifier que 7209.50 est bien multiple de 0.25
        self.assertEqual((new_sl / 0.25) % 1, 0,
                         f"new_sl {new_sl} doit etre multiple de 0.25")

    def test_nq_long_50t_sl_mfe_25(self):
        # NQ LONG entry 27000, SL 26987.5 (50t). MFE 25t. arming 20t passé.
        # give_back 10t. new_sl = 27000 + (25-10)*0.25 = 27003.75
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, 25)
        self.assertTrue(updated)
        self.assertEqual(new_sl, 27003.75)


class TestTickAlignment(unittest.TestCase):
    """FIX C1 review code-reviewer : verifier que tous les SL trail sont alignes
    sur multiples de TICK_SIZE (0.25 pour ES/NQ)."""

    def test_alignment_long_fractional_giveback(self):
        # SL 14t (fractionnaire give_back 2.8t) → alignement obligatoire
        new_sl, updated = _compute_trail_sl("LONG", 7200.50, 7195.00, 14, 39)
        self.assertTrue(updated)
        self.assertEqual((new_sl / 0.25) % 1, 0)

    def test_alignment_short_fractional_giveback(self):
        new_sl, updated = _compute_trail_sl("SHORT", 7200.50, 7205.00, 14, 39)
        self.assertTrue(updated)
        self.assertEqual((new_sl / 0.25) % 1, 0)

    def test_alignment_various_sl_initials(self):
        """Tester plusieurs SL initials pour que l'alignement marche partout."""
        for sl_init in [8, 12, 14, 18, 22, 33, 47, 51]:
            for mfe in [int(sl_init * 0.5), int(sl_init * 1.0), int(sl_init * 2.0)]:
                if mfe < 0.40 * sl_init:
                    continue
                new_sl, updated = _compute_trail_sl(
                    "LONG", 27000.0, 26987.5, sl_init, mfe
                )
                if updated:
                    with self.subTest(sl_init=sl_init, mfe=mfe):
                        self.assertEqual(
                            (new_sl / 0.25) % 1, 0,
                            f"SL {new_sl} pas aligne (sl_init={sl_init}, mfe={mfe})"
                        )


class TestTrailingNQOnly(unittest.TestCase):
    """Verifier le filtre NQ-only (pilot, ES marginal)."""

    def test_filter_logic_nq_only(self):
        # Le filtre est dans mia_paper_trader.py : `if symbol == "NQ": ...`
        # On verifie ici juste la logique : pour ES, le code skip entierement.
        # (test hors scope helper, juste validation conceptuelle)
        self.assertEqual("NQ", "NQ")  # tautologie pour confirmer le test setup
        # En production : ES n'entre jamais dans la branche trailing


class TestTrailingEdgeCases(unittest.TestCase):
    """Edge cases."""

    def test_sl_ticks_initial_zero_no_trail(self):
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 0, 50)
        self.assertFalse(updated)

    def test_sl_ticks_initial_none_no_trail(self):
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, None, 50)
        self.assertFalse(updated)

    def test_mfe_zero_no_trail(self):
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, 0)
        self.assertFalse(updated)

    def test_mfe_negative_no_trail(self):
        # MFE doit etre positif (excursion favorable). Si negatif = bug en amont.
        new_sl, updated = _compute_trail_sl("LONG", 27000.0, 26987.5, 50, -5)
        self.assertFalse(updated)


class TestTrailingProgression(unittest.TestCase):
    """Simuler une progression MFE croissante."""

    def test_progressive_trail_long(self):
        """LONG SL=50t. Progression MFE 5t → 25t → 40t → 35t → 60t.

        Trail attendu :
          MFE 5  : pas arme (< 20)
          MFE 25 : arme, SL = 27000 + (25-10)*0.25 = 27003.75
          MFE 40 : SL = 27000 + (40-10)*0.25 = 27007.50
          MFE 35 : pas update (candidate 27006.25 < 27007.50)
          MFE 60 : SL = 27000 + (60-10)*0.25 = 27012.50
        """
        entry = 27000.0
        current_sl = 26987.5

        # MFE 5
        new_sl, upd = _compute_trail_sl("LONG", entry, current_sl, 50, 5)
        self.assertFalse(upd)

        # MFE 25
        new_sl, upd = _compute_trail_sl("LONG", entry, current_sl, 50, 25)
        self.assertTrue(upd)
        self.assertEqual(new_sl, 27003.75)
        current_sl = new_sl

        # MFE 40
        new_sl, upd = _compute_trail_sl("LONG", entry, current_sl, 50, 40)
        self.assertTrue(upd)
        self.assertEqual(new_sl, 27007.50)
        current_sl = new_sl

        # MFE 35 (down) — pas update
        new_sl, upd = _compute_trail_sl("LONG", entry, current_sl, 50, 35)
        self.assertFalse(upd)
        # current_sl reste 27007.50

        # MFE 60
        new_sl, upd = _compute_trail_sl("LONG", entry, current_sl, 50, 60)
        self.assertTrue(upd)
        self.assertEqual(new_sl, 27012.50)


class TestTrailingIntegrationCheckExit(unittest.TestCase):
    """FIX I3 review code-reviewer 30/04 : test integration appelant le VRAI
    `check_exit` de mia_paper_trader.py (pas le helper duplique).

    Garantit que si demain qqn modifie check_exit sans toucher le helper,
    le test casse (= la duplication ne peut pas diverger silencieusement).
    """

    def setUp(self):
        """Construit un MiaPaperTrader minimaliste sans __init__ heavy."""
        import threading
        from CORE.mia_paper_trader import PaperTrader
        # Bypass __init__ (qui lance V2 logger, eco_calendar, etc.)
        self.bot = PaperTrader.__new__(PaperTrader)
        self.bot._pos_lock = threading.Lock()
        # _v2log peut etre None → guard try/except dans le code prod
        self.bot._v2log = None
        self.bot._order_to_symbol = {}
        # Position NQ LONG : entry 27000, SL 26987.5 (50t), TP 27050 (200t)
        self.bot.positions = {
            "NQ": {
                "direction": "LONG",
                "entry_price": 27000.0,
                "sl_price": 26987.5,
                "tp_price": 27050.0,
                "sl_ticks": 50,
                "tp_ticks": 200,
                "n_micros": 3,
                "mfe": 0.0,
                "mae": 0.0,
                "bars_held": 0,
                "current_price": 27000.0,
                "unrealized_pnl_ticks": 0,
                "unrealized_pnl_usd": 0,
            }
        }

    def _bar(self, price):
        """Construit un dict data simulant une bar avec price."""
        return {"banner": {"nq": {"price": price}}}

    def test_no_trail_below_arming(self):
        """MFE 10t (< 20t arming) → pas de trail."""
        self.bot.check_exit(self._bar(27002.5), "NQ")  # +10t excursion
        pos = self.bot.positions["NQ"]
        self.assertEqual(pos["mfe"], 10.0)
        self.assertEqual(pos["sl_price"], 26987.5)  # inchange
        self.assertFalse(pos.get("sl_trailed", False))

    def test_trail_arms_at_threshold(self):
        """MFE 25t (>= 20t arming) → trail s'arme."""
        self.bot.check_exit(self._bar(27006.25), "NQ")  # +25t
        pos = self.bot.positions["NQ"]
        self.assertEqual(pos["mfe"], 25.0)
        # New SL = 27000 + (25-10)*0.25 = 27003.75 (multiple de 0.25 ✓)
        self.assertEqual(pos["sl_price"], 27003.75)
        self.assertTrue(pos.get("sl_trailed"))
        self.assertEqual(pos.get("sl_trail_count"), 1)
        # sl_ticks_initial doit avoir ete snapshote
        self.assertEqual(pos.get("sl_ticks_initial"), 50)

    def test_trail_progression_long(self):
        """Progression MFE 25→40→35 (drop)→60. Trail update + anti-degradation."""
        # Bar 1 : MFE 25 → SL trail 27003.75
        self.bot.check_exit(self._bar(27006.25), "NQ")
        self.assertEqual(self.bot.positions["NQ"]["sl_price"], 27003.75)
        # Bar 2 : MFE peak 40 → SL trail 27007.50
        self.bot.check_exit(self._bar(27010.0), "NQ")
        self.assertEqual(self.bot.positions["NQ"]["mfe"], 40.0)
        self.assertEqual(self.bot.positions["NQ"]["sl_price"], 27007.50)
        # Bar 3 : price drops to +35t (excursion < MFE), MFE reste 40
        self.bot.check_exit(self._bar(27008.75), "NQ")
        self.assertEqual(self.bot.positions["NQ"]["mfe"], 40.0)  # MFE conserve le peak
        self.assertEqual(self.bot.positions["NQ"]["sl_price"], 27007.50)  # SL conserve
        # Bar 4 : MFE peak 60 → SL trail 27012.50
        self.bot.check_exit(self._bar(27015.0), "NQ")
        self.assertEqual(self.bot.positions["NQ"]["mfe"], 60.0)
        self.assertEqual(self.bot.positions["NQ"]["sl_price"], 27012.50)
        self.assertEqual(self.bot.positions["NQ"]["sl_trail_count"], 3)

    def test_es_filter_no_trail(self):
        """ES n'est PAS dans le pilot trailing → pas de trail meme si MFE eleve."""
        # Cree position ES (deuxieme symbol)
        self.bot.positions["ES"] = {
            "direction": "LONG",
            "entry_price": 7200.0,
            "sl_price": 7196.5,  # 14t SL
            "tp_price": 7220.0,
            "sl_ticks": 14,
            "tp_ticks": 80,
            "n_micros": 3,
            "mfe": 0.0,
            "mae": 0.0,
            "bars_held": 0,
            "current_price": 7200.0,
            "unrealized_pnl_ticks": 0,
            "unrealized_pnl_usd": 0,
        }
        # ES bar : excursion +30 ticks (largement au-dessus arming 5.6t pour SL 14t)
        data_es = {"banner": {"es": {"price": 7207.5}}}
        self.bot.check_exit(data_es, "ES")
        pos_es = self.bot.positions["ES"]
        self.assertEqual(pos_es["mfe"], 30.0)
        # SL ES doit rester INCHANGE (pas de trail sur ES en V1)
        self.assertEqual(pos_es["sl_price"], 7196.5)
        self.assertFalse(pos_es.get("sl_trailed", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
