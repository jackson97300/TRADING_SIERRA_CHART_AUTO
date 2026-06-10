"""Tests trailing + BE OBSERVATION Bot 3 (Phase 1, Jackson 07/05).

Mode OBSERVE_ONLY : trigger logs sans modify DTC orders. Audit J+7 puis decide
activation phase 2.

Logique :
  - BE trigger : MFE >= trailing_be_trigger_ticks → log BOT3_TRAILING_BE_OBSERVED (1x par trade)
  - Trailing trigger : MFE >= trailing_active_trigger_ticks → log BOT3_TRAILING_UPDATE_OBSERVED
    a chaque progression MFE >= 25% trailing_distance (anti-spam)
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest


def _make_bot_with_position(side="LONG", entry=7350.0, sym="ES",
                              mfe_ticks=0.0, sl_price=7345.0):
    """Helper : cree un FakeBot avec 1 position trackee + bind _bot3_check_trailing_observation."""
    from CORE.databento_paper_trader_v2 import DatabentoPaperTraderV2

    class _FakeBot:
        def __init__(self):
            self._bot3_pos_lock = threading.RLock()
            self._bot3_positions = {"ES": None, "NQ": None}
            self.emitted_events = []

        def _bot3_check_trailing_observation(self, sym, pos, tick_size, GR):
            return DatabentoPaperTraderV2._bot3_check_trailing_observation.__get__(self)(
                sym, pos, tick_size, GR)

    bot = _FakeBot()
    pos = {
        "side": side,
        "level": "TEST_LEVEL",
        "entry_price": entry,
        "mfe_ticks": mfe_ticks,
        "mae_ticks": 0.0,
        "sl_price": sl_price,
        "ts_open": "2026-05-07T00:00:00Z",
        "signal_id": "test_sig",
        "n_contracts": 3,
    }
    bot._bot3_positions[sym] = pos
    return bot, pos


def _patched_emit_capturing(events_list):
    """Patch _emit pour capturer les events."""
    def _emit(code, **kwargs):
        events_list.append((code, kwargs))
    return _emit


def test_be_trigger_fires_when_mfe_reaches_threshold_long():
    """LONG MFE = 32t (= ES be_trigger) → fire BOT3_TRAILING_BE_OBSERVED."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=32.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    be_events = [e for e in events if e[0] == "BOT3_TRAILING_BE_OBSERVED"]
    assert len(be_events) == 1, f"Attendu 1 BE event, recu {len(be_events)}"
    ctx = be_events[0][1]
    assert ctx["sym"] == "ES"
    assert ctx["side"] == "LONG"
    assert ctx["current_mfe_ticks"] == 32.0
    assert ctx["sl_hypothetical_be"] == 7350.0  # = entry
    assert pos["trailing_be_observed"] is True


def test_be_trigger_idempotent_no_double_log():
    """Re-appel apres BE deja observe → pas de double log."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=35.0)
    pos["trailing_be_observed"] = True  # deja observe
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    be_events = [e for e in events if e[0] == "BOT3_TRAILING_BE_OBSERVED"]
    assert len(be_events) == 0, "BE event ne doit pas se re-emettre"


def test_be_trigger_short_position():
    """SHORT MFE = 32t → fire BE event avec sl_hypothetical = entry."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="SHORT", entry=7350.0, mfe_ticks=32.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    be_events = [e for e in events if e[0] == "BOT3_TRAILING_BE_OBSERVED"]
    assert len(be_events) == 1
    assert be_events[0][1]["side"] == "SHORT"
    assert be_events[0][1]["sl_hypothetical_be"] == 7350.0


def test_trailing_active_fires_at_threshold_long():
    """LONG MFE = 48t (= ES active_trigger) → fire BOT3_TRAILING_UPDATE_OBSERVED."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=48.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    upd_events = [e for e in events if e[0] == "BOT3_TRAILING_UPDATE_OBSERVED"]
    assert len(upd_events) >= 1
    ctx = upd_events[0][1]
    assert ctx["current_mfe_ticks"] == 48.0
    # SL hypothetique = mfe_price - 16t (LONG)
    # mfe_price = 7350 + 48 * 0.25 = 7362, sl = 7362 - 16*0.25 = 7358.0
    assert ctx["sl_hypothetical_trailing"] == 7358.0


def test_trailing_active_short_correct_sl_hypothetical():
    """SHORT MFE 48t → SL hypothetique = mfe_price + trailing_dist*tick (sens inverse)."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="SHORT", entry=7350.0, mfe_ticks=48.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    upd_events = [e for e in events if e[0] == "BOT3_TRAILING_UPDATE_OBSERVED"]
    # SHORT mfe_price = entry - 48t*0.25 = 7350 - 12 = 7338
    # SL trailing = mfe_price + 16t*0.25 = 7338 + 4 = 7342
    assert upd_events[0][1]["mfe_price"] == 7338.0
    assert upd_events[0][1]["sl_hypothetical_trailing"] == 7342.0


def test_trailing_anti_spam_log_only_on_progression():
    """MFE stagnant = pas de re-log apres premier UPDATE event."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=50.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        # 1ere passe
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)
        # 2eme passe avec meme MFE → pas re-log
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    upd_events = [e for e in events if e[0] == "BOT3_TRAILING_UPDATE_OBSERVED"]
    assert len(upd_events) == 1, f"Attendu 1 UPDATE, recu {len(upd_events)} (anti-spam)"


def test_trailing_relog_when_mfe_progresses_significantly():
    """MFE progresse de >= 25% trailing_distance → re-log autorise."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=50.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)
        # Progression de 5t (>= 25% × 16 = 4t) → log autorise
        pos["mfe_ticks"] = 55.0
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    upd_events = [e for e in events if e[0] == "BOT3_TRAILING_UPDATE_OBSERVED"]
    assert len(upd_events) == 2, f"Attendu 2 UPDATE (progression), recu {len(upd_events)}"


def test_no_trigger_below_threshold():
    """MFE 25t (sous BE 32t) → 0 events."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=25.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    assert len(events) == 0, "Aucun event sous BE threshold"


def test_no_trigger_when_entry_zero():
    """Recovered position avec entry=0 → skip."""
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=0.0, mfe_ticks=50.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    assert len(events) == 0, "Pas d'event si entry_price=0 (recovered)"


def test_real_case_06_05_es_short_7338():
    """Cas reel ES SHORT @7338.25 MFE +35t observe : trailing aurait fire ?

    Avec ES config (BE=32t, active=48t), MFE 35t suffit pour BE mais pas trailing.
    Verdict empirique : si trailing actif, BE aurait verrouille profit a entry.
    """
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="SHORT", entry=7338.25, mfe_ticks=35.0)
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR)

    be_events = [e for e in events if e[0] == "BOT3_TRAILING_BE_OBSERVED"]
    upd_events = [e for e in events if e[0] == "BOT3_TRAILING_UPDATE_OBSERVED"]
    assert len(be_events) == 1, "MFE 35 >= 32 → BE doit fire"
    assert len(upd_events) == 0, "MFE 35 < 48 → trailing pas encore actif"
    # En prod : BE aurait protege le trade. Si marche reverse → exit a entry = $0 net
    # (au lieu de TIMEOUT a +12 vs MAE -22 risque).


def test_real_case_06_05_nq_long_28602_protection_mfe_only_9():
    """NQ LONG @28602.5 MFE +9t (catastrophe MAE -627t) : trailing pas declenche.

    BE_trigger NQ = 80t. MFE 9t loin du seuil → 0 event.
    Verdict : le trade etait mauvais des le depart, trailing ne sauve rien.
    """
    from CORE.bot3_config import GUARD_RAILS_BOT3 as GR

    bot, pos = _make_bot_with_position(side="LONG", entry=28602.5, mfe_ticks=9.0, sym="NQ")
    bot._bot3_positions["NQ"] = pos
    events = []

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("NQ", pos, 0.25, GR)

    assert len(events) == 0, "MFE 9t loin du seuil NQ 80t → pas de trigger"


def test_no_trigger_if_config_missing_keys():
    """Si trailing_be_trigger_ticks absent du GR → silent skip (pas crash)."""
    bot, pos = _make_bot_with_position(side="LONG", entry=7350.0, mfe_ticks=50.0)
    events = []
    GR_no_trailing = {"ES": {"tick_size": 0.25}}  # cles trailing manquantes

    with patch("CORE.databento_paper_trader_v2._emit", _patched_emit_capturing(events)):
        bot._bot3_check_trailing_observation("ES", pos, 0.25, GR_no_trailing)

    assert len(events) == 0, "Config sans trailing → skip silencieux"
