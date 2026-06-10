"""Tests Solution D2 — Ladder profit-locking Bot 3.

Tests pure logique (mocks _emit + pos). Pas DTC, pas runtime full bot.
Valide :
  - Palier 1 declenche au seuil MFE
  - Palier 2 declenche au seuil suivant
  - Idempotent (1 emit par palier par trade)
  - Edge cases : entry=0, mfe=0, mfe<seuil, paliers vides
  - SHORT direction (sl_lock dans le bon sens)
  - Kill switch MIA_BOT3_LADDER_ENABLED=0 -> early return

Date : 2026-05-11 (Jackson Solution D2 "pas gourmand")
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ajouter CORE/ au path pour import
_CORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)


GR_FIXTURE = {
    "NQ": {
        "n_contracts": 3,
        "tick_value": 0.50,
        "tick_size": 0.25,
        "ladder_paliers": [
            (60.0, 20.0),
            (100.0, 40.0),
            (150.0, 80.0),
            (200.0, 120.0),
        ],
    },
    "ES": {
        "n_contracts": 3,
        "tick_value": 1.25,
        "tick_size": 0.25,
        "ladder_paliers": [
            (20.0, 8.0),
            (40.0, 16.0),
            (60.0, 30.0),
            (80.0, 50.0),
        ],
    },
}


class FakeBot:
    """Mock minimal pour tester _bot3_check_trailing_ladder en isolation."""

    def __init__(self):
        self.emitted = []

    def _emit(self, code, **ctx):
        self.emitted.append({"code": code, **ctx})

    def _bot3_check_trailing_ladder(self, sym, pos, tick_size, GR):
        """Copie de la methode (au lieu d'import lourd databento_paper_trader_v2)."""
        if os.environ.get("MIA_BOT3_LADDER_ENABLED", "0") != "1":
            return
        try:
            mode = os.environ.get("MIA_BOT3_LADDER_MODE", "OBSERVE").upper()
            cfg = GR.get(sym, {})
            paliers = cfg.get("ladder_paliers", [])

            mfe = float(pos.get("mfe_ticks", 0.0))
            entry = float(pos.get("entry_price", 0.0))
            executed = pos.setdefault("ladder_executed_paliers", set())

            self._emit("BOT3_LADDER_TICK",
                       sym=sym, mfe=round(mfe, 1),
                       entry=round(entry, 2),
                       n_paliers=len(paliers),
                       executed_count=len(executed),
                       mode=mode)

            if not paliers:
                return
            if entry <= 0 or mfe <= 0:
                return

            dir_sign = 1 if pos["side"] == "LONG" else -1
            n_contracts = cfg.get("n_contracts", 3)
            tick_value = cfg.get("tick_value", 0.50)

            for palier_idx, (mfe_seuil, sl_lock_ticks) in enumerate(paliers):
                if palier_idx in executed:
                    continue
                if mfe < mfe_seuil:
                    break
                new_sl_price = entry + dir_sign * sl_lock_ticks * tick_size
                lock_usd = sl_lock_ticks * tick_value * n_contracts

                if mode == "OBSERVE":
                    self._emit("BOT3_LADDER_WOULD_LOCK",
                               sym=sym, palier=palier_idx + 1,
                               side=pos.get("side"),
                               mfe_ticks=round(mfe, 1),
                               mfe_seuil_ticks=mfe_seuil,
                               sl_lock_ticks=sl_lock_ticks,
                               sl_new_price=round(new_sl_price, 2),
                               lock_usd=round(lock_usd, 2))
                    executed.add(palier_idx)
                elif mode == "ACTION":
                    self._emit("BOT3_LADDER_ACTION_NOT_IMPLEMENTED_YET",
                               sym=sym, palier=palier_idx + 1)
                    executed.add(palier_idx)
        except Exception as e:
            self._emit("PY_EXCEPTION_HOT_PATH",
                       sym=sym, fn_name="_bot3_check_trailing_ladder",
                       exc_type=type(e).__name__, exc_msg=str(e))


class TestKillSwitch(unittest.TestCase):
    """Kill switch MIA_BOT3_LADDER_ENABLED."""

    def test_disabled_default_no_emit(self):
        os.environ.pop("MIA_BOT3_LADDER_ENABLED", None)
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 100.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        self.assertEqual(len(bot.emitted), 0,
                         "Kill switch off (default) doit retourner early sans emit")

    def test_enabled_emits_tick(self):
        os.environ["MIA_BOT3_LADDER_ENABLED"] = "1"
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 30.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        # 1 emit diagnostic TICK (mfe < palier 1)
        codes = [e["code"] for e in bot.emitted]
        self.assertIn("BOT3_LADDER_TICK", codes)
        self.assertNotIn("BOT3_LADDER_WOULD_LOCK", codes)


class TestPaliers(unittest.TestCase):
    """Paliers NQ palier 1 (+60t -> +20t) + palier 2 (+100t -> +40t)."""

    def setUp(self):
        os.environ["MIA_BOT3_LADDER_ENABLED"] = "1"
        os.environ["MIA_BOT3_LADDER_MODE"] = "OBSERVE"

    def test_nq_long_palier_1_at_60t(self):
        """NQ LONG entry=29200, MFE=60t -> palier 1 emit BOT3_LADDER_WOULD_LOCK."""
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 60.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0]["palier"], 1)
        self.assertEqual(locks[0]["sl_lock_ticks"], 20.0)
        self.assertEqual(locks[0]["sl_new_price"], 29205.0)  # 29200 + 20*0.25
        self.assertEqual(locks[0]["lock_usd"], 30.0)  # 20 × $0.50 × 3 micros

    def test_nq_long_palier_2_at_100t(self):
        """NQ LONG MFE=100t -> palier 1 + 2 emits."""
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 100.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 2)
        self.assertEqual(locks[0]["palier"], 1)
        self.assertEqual(locks[1]["palier"], 2)
        self.assertEqual(locks[1]["sl_new_price"], 29210.0)  # 29200 + 40*0.25
        self.assertEqual(locks[1]["lock_usd"], 60.0)

    def test_nq_long_below_palier_1(self):
        """NQ LONG MFE=59t -> aucun palier (juste TICK diagnostic)."""
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 59.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 0)
        ticks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_TICK"]
        self.assertEqual(len(ticks), 1)

    def test_nq_short_palier_1(self):
        """NQ SHORT entry=29200, MFE=60t -> SL = entry - 20*0.25 = 29195."""
        bot = FakeBot()
        pos = {"side": "SHORT", "entry_price": 29200, "mfe_ticks": 60.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0]["sl_new_price"], 29195.0)
        self.assertEqual(locks[0]["side"], "SHORT")

    def test_nq_long_palier_4_at_200t(self):
        """NQ LONG MFE=200t -> 4 paliers emis."""
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 200.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 4)
        for i, lock in enumerate(locks):
            self.assertEqual(lock["palier"], i + 1)


class TestIdempotence(unittest.TestCase):
    """1 emit par palier par trade : 2 appels successifs ne doublent pas."""

    def setUp(self):
        os.environ["MIA_BOT3_LADDER_ENABLED"] = "1"
        os.environ["MIA_BOT3_LADDER_MODE"] = "OBSERVE"

    def test_no_double_emit_same_palier(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 60.0}
        # 1er call : palier 1 emis
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        # 2eme call (meme pos) : palier 1 deja executed, pas re-emit
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 1, "Palier 1 ne doit etre emis qu'une fois")
        ticks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_TICK"]
        self.assertEqual(len(ticks), 2, "2 calls = 2 TICK diagnostic emits")

    def test_progressive_paliers(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 60.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        # Trade evolue MFE +60 -> +100t
        pos["mfe_ticks"] = 100.0
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 2)
        self.assertEqual(locks[0]["palier"], 1)
        self.assertEqual(locks[1]["palier"], 2)


class TestEdgeCases(unittest.TestCase):
    """Edge cases : entry=0, mfe=0, paliers vides."""

    def setUp(self):
        os.environ["MIA_BOT3_LADDER_ENABLED"] = "1"
        os.environ["MIA_BOT3_LADDER_MODE"] = "OBSERVE"

    def test_entry_zero_skip(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 0, "mfe_ticks": 60.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 0)
        # TICK diagnostic emis quand meme (debugability)
        ticks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_TICK"]
        self.assertEqual(len(ticks), 1)

    def test_mfe_zero_skip(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 0.0}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 0)

    def test_empty_paliers(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 100.0}
        gr_empty = {"NQ": {"n_contracts": 3, "tick_value": 0.50, "ladder_paliers": []}}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, gr_empty)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 0)

    def test_missing_paliers_key(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 29200, "mfe_ticks": 100.0}
        gr_no_key = {"NQ": {"n_contracts": 3, "tick_value": 0.50}}
        bot._bot3_check_trailing_ladder("NQ", pos, 0.25, gr_no_key)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 0)


class TestES(unittest.TestCase):
    """ES tick_value=1.25 + paliers different."""

    def setUp(self):
        os.environ["MIA_BOT3_LADDER_ENABLED"] = "1"
        os.environ["MIA_BOT3_LADDER_MODE"] = "OBSERVE"

    def test_es_long_palier_1_at_20t(self):
        bot = FakeBot()
        pos = {"side": "LONG", "entry_price": 7400, "mfe_ticks": 20.0}
        bot._bot3_check_trailing_ladder("ES", pos, 0.25, GR_FIXTURE)
        locks = [e for e in bot.emitted if e["code"] == "BOT3_LADDER_WOULD_LOCK"]
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0]["palier"], 1)
        self.assertEqual(locks[0]["sl_lock_ticks"], 8.0)
        self.assertEqual(locks[0]["sl_new_price"], 7402.0)  # 7400 + 8*0.25
        self.assertEqual(locks[0]["lock_usd"], 30.0)  # 8 × $1.25 × 3 micros


if __name__ == "__main__":
    unittest.main()
