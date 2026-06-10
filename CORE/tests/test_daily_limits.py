"""test_daily_limits.py — Tests DailyLimitsGuard (Mark Douglas kill switch 08/06/2026).

Couverture (cf .claude/rules/critical-tasks-review.md critere 1 Trading/Risk) :
  - daily_stop_loss bloque entry quand cumul <= seuil
  - daily_stop_loss allows entry quand cumul > seuil
  - daily_stop_win bloque entry quand cumul >= seuil
  - daily_max_trades bloque entry quand count >= limit
  - reset au rollover date
  - persistance state file (resilience crash)
  - rebuild_from_trades agrege pnl correctement
  - kill switch global enabled=False -> tout passe
  - env vars override defaults
  - on_trade_close trigger one-shot emit
  - thread safety (concurrent on_trade_close + check_allow)
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.daily_limits_guard import (  # noqa: E402
    DailyLimitsConfig,
    DailyLimitsGuard,
    load_config_from_env,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture()
def tmp_state_dir(tmp_path: Path) -> str:
    """Repertoire temporaire isole pour state files."""
    d = tmp_path / "PAPER_TRADES"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@pytest.fixture()
def default_config() -> DailyLimitsConfig:
    """Config defaults Mark Douglas (Bot 1 SIM1)."""
    return DailyLimitsConfig(
        daily_stop_loss_usd=-200.0,
        daily_stop_win_usd=150.0,
        daily_max_trades=5,
        enabled=True,
        stop_win_enabled=True,
        max_trades_enabled=True,
    )


@pytest.fixture()
def guard(default_config: DailyLimitsConfig, tmp_state_dir: str) -> DailyLimitsGuard:
    """Guard fresh, state file vide, date 20260608."""
    return DailyLimitsGuard(
        bot_id="bot_test",
        config=default_config,
        state_dir=tmp_state_dir,
        date_str="20260608",
    )


# -----------------------------------------------------------------------------
# Tests fondamentaux (1 par seuil)
# -----------------------------------------------------------------------------

class TestDailyStopLoss:
    def test_blocks_entry_when_cumul_exceeds_threshold(self, guard: DailyLimitsGuard):
        """cumul=-$250 (seuil -$200) → bloque step 0bis_daily_limits."""
        # Simule 1 trade perdant qui depasse le seuil
        guard.on_trade_close(pnl_usd=-250.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is False, "stop_loss doit bloquer cumul=-$250"
        assert reason == guard.REASON_STOP_LOSS

    def test_allows_entry_below_threshold(self, guard: DailyLimitsGuard):
        """cumul=-$100 → allow."""
        guard.on_trade_close(pnl_usd=-100.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is True
        assert reason == ""

    def test_blocks_exact_threshold(self, guard: DailyLimitsGuard):
        """cumul=-$200 exactement → bloque (<=)."""
        guard.on_trade_close(pnl_usd=-200.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is False
        assert reason == guard.REASON_STOP_LOSS

    def test_blocks_after_multiple_losing_trades(self, guard: DailyLimitsGuard):
        """3 trades -$80 chacun = -$240 -> bloque."""
        for _ in range(3):
            guard.on_trade_close(pnl_usd=-80.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is False
        assert reason == guard.REASON_STOP_LOSS


class TestDailyStopWin:
    def test_blocks_entry_when_profit_target_reached(self, guard: DailyLimitsGuard):
        """cumul=+$200 (seuil +$150) → bloque (lock-in profits)."""
        guard.on_trade_close(pnl_usd=+200.0)
        allow, reason = guard.check_allow("ES")
        assert allow is False
        assert reason == guard.REASON_STOP_WIN

    def test_allows_entry_below_profit_target(self, guard: DailyLimitsGuard):
        """cumul=+$100 → allow (pas encore lock-in)."""
        guard.on_trade_close(pnl_usd=+100.0)
        allow, reason = guard.check_allow("ES")
        assert allow is True

    def test_blocks_exact_threshold(self, guard: DailyLimitsGuard):
        """cumul=+$150 exactement → bloque (>=)."""
        guard.on_trade_close(pnl_usd=+150.0)
        allow, reason = guard.check_allow("ES")
        assert allow is False
        assert reason == guard.REASON_STOP_WIN

    def test_stop_win_disabled_allows_entry(self, tmp_state_dir: str):
        """stop_win_enabled=False -> +$200 ne bloque pas."""
        cfg = DailyLimitsConfig(
            daily_stop_loss_usd=-200.0,
            daily_stop_win_usd=150.0,
            daily_max_trades=5,
            stop_win_enabled=False,
        )
        g = DailyLimitsGuard("bot_test", cfg, tmp_state_dir, "20260608")
        g.on_trade_close(pnl_usd=+200.0)
        allow, reason = g.check_allow("ES")
        assert allow is True


class TestDailyMaxTrades:
    def test_blocks_entry_at_limit(self, guard: DailyLimitsGuard):
        """5 trades atteints → bloque."""
        for _ in range(5):
            guard.on_trade_close(pnl_usd=+10.0)  # petits gains qui n'atteignent pas stop_win
        allow, reason = guard.check_allow("NQ")
        assert allow is False
        assert reason == guard.REASON_MAX_TRADES

    def test_allows_entry_below_limit(self, guard: DailyLimitsGuard):
        """4 trades -> allow encore 1."""
        for _ in range(4):
            guard.on_trade_close(pnl_usd=+5.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is True

    def test_max_trades_disabled_allows_entry(self, tmp_state_dir: str):
        """max_trades_enabled=False -> 10 trades ne bloque pas."""
        cfg = DailyLimitsConfig(
            daily_stop_loss_usd=-200.0,
            daily_stop_win_usd=150.0,
            daily_max_trades=5,
            max_trades_enabled=False,
        )
        g = DailyLimitsGuard("bot_test", cfg, tmp_state_dir, "20260608")
        for _ in range(10):
            g.on_trade_close(pnl_usd=+5.0)
        allow, reason = g.check_allow("NQ")
        assert allow is True


# -----------------------------------------------------------------------------
# Tests rollover + persistence
# -----------------------------------------------------------------------------

class TestRollover:
    def test_reset_midnight_clears_state(self, guard: DailyLimitsGuard):
        """Passage 20260608 -> 20260609 reset cumul/count/triggers."""
        # Simule sequence perdante
        guard.on_trade_close(pnl_usd=-150.0)
        guard.on_trade_close(pnl_usd=-100.0)  # cumul -$250 -> stop_loss triggered
        snap_before = guard.snapshot()
        assert snap_before["cumul_pnl_usd"] == -250.0
        assert snap_before["trade_count"] == 2
        assert snap_before["stop_loss_triggered"] is True

        rolled = guard.rollover_if_needed("20260609")
        assert rolled is True

        snap_after = guard.snapshot()
        assert snap_after["date"] == "20260609"
        assert snap_after["cumul_pnl_usd"] == 0.0
        assert snap_after["trade_count"] == 0
        assert snap_after["stop_loss_triggered"] is False
        # Et le check passe
        allow, _ = guard.check_allow("NQ")
        assert allow is True

    def test_rollover_same_date_noop(self, guard: DailyLimitsGuard):
        guard.on_trade_close(pnl_usd=-50.0)
        rolled = guard.rollover_if_needed("20260608")
        assert rolled is False
        assert guard.snapshot()["cumul_pnl_usd"] == -50.0


class TestStatePersistenceRecovery:
    def test_state_persists_to_disk(
        self, default_config: DailyLimitsConfig, tmp_state_dir: str
    ):
        """on_trade_close persiste; relire le fichier doit donner le meme state."""
        g1 = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        g1.on_trade_close(pnl_usd=-120.0)

        # Verifier fichier disque
        fp = Path(tmp_state_dir) / "20260608_daily_state_bot_test.json"
        assert fp.exists()
        with open(fp) as f:
            data = json.load(f)
        assert data["cumul_pnl_usd"] == -120.0
        assert data["trade_count"] == 1

    def test_state_recovered_on_restart(
        self, default_config: DailyLimitsConfig, tmp_state_dir: str
    ):
        """Apres crash, nouveau guard sur meme date reprend le cumul."""
        # Simule run #1
        g1 = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        g1.on_trade_close(pnl_usd=-150.0)
        g1.on_trade_close(pnl_usd=-100.0)  # cumul -$250 stop_loss
        # "Crash" : on creee nouveau guard sur la meme date
        g2 = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        snap = g2.snapshot()
        assert snap["cumul_pnl_usd"] == -250.0
        assert snap["trade_count"] == 2
        assert snap["stop_loss_triggered"] is True
        # Et bloquera bien
        allow, reason = g2.check_allow("NQ")
        assert allow is False
        assert reason == g2.REASON_STOP_LOSS

    def test_corrupt_state_file_resets(
        self, default_config: DailyLimitsConfig, tmp_state_dir: str
    ):
        """Fichier state corrompu -> reset propre (pas crash)."""
        fp = Path(tmp_state_dir) / "20260608_daily_state_bot_test.json"
        fp.write_text("{not valid json", encoding="utf-8")
        g = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        snap = g.snapshot()
        # Reset clean
        assert snap["cumul_pnl_usd"] == 0.0
        assert snap["trade_count"] == 0

    def test_rebuild_from_trades(
        self, default_config: DailyLimitsConfig, tmp_state_dir: str
    ):
        """Reconstruction depuis pnl_usd iterable (boot fallback)."""
        g = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        # Trades du jour : -50, -100, -75, None (timeout, skip), +25
        g.rebuild_from_trades([-50.0, -100.0, -75.0, None, +25.0])
        snap = g.snapshot()
        # None est skip cumul mais Actuel implementation : on skip count aussi
        # Cf rebuild_from_trades : pnl=None -> continue (skip)
        assert snap["cumul_pnl_usd"] == pytest.approx(-200.0)
        assert snap["trade_count"] == 4  # None skip
        # stop_loss triggered car cumul=-200 <= -200
        assert snap["stop_loss_triggered"] is True


# -----------------------------------------------------------------------------
# Tests kill switch + env vars
# -----------------------------------------------------------------------------

class TestKillSwitch:
    def test_master_disabled_allows_everything(self, tmp_state_dir: str):
        """enabled=False -> meme -$500 cumul passe."""
        cfg = DailyLimitsConfig(
            daily_stop_loss_usd=-200.0,
            daily_stop_win_usd=150.0,
            daily_max_trades=5,
            enabled=False,  # master off
        )
        g = DailyLimitsGuard("bot_test", cfg, tmp_state_dir, "20260608")
        g.on_trade_close(pnl_usd=-500.0)
        allow, reason = g.check_allow("NQ")
        assert allow is True
        assert reason == ""

    def test_env_var_override(self, tmp_state_dir: str, monkeypatch):
        """MIA_DAILY_STOP_LOSS=-500 override default -$200."""
        monkeypatch.setenv("MIA_DAILY_STOP_LOSS", "-500")
        monkeypatch.setenv("MIA_DAILY_STOP_WIN", "300")
        monkeypatch.setenv("MIA_DAILY_MAX_TRADES", "10")
        cfg = load_config_from_env(prefix="MIA")
        assert cfg.daily_stop_loss_usd == -500.0
        assert cfg.daily_stop_win_usd == 300.0
        assert cfg.daily_max_trades == 10

    def test_env_var_disable_master(self, tmp_state_dir: str, monkeypatch):
        monkeypatch.setenv("MIA_DAILY_LIMITS_ENABLED", "0")
        cfg = load_config_from_env(prefix="MIA")
        assert cfg.enabled is False

    def test_env_var_invalid_falls_back_default(self, monkeypatch):
        """Env var invalide -> default, pas crash."""
        monkeypatch.setenv("MIA_DAILY_STOP_LOSS", "not_a_number")
        cfg = load_config_from_env(prefix="MIA")
        assert cfg.daily_stop_loss_usd == -200.0  # default


# -----------------------------------------------------------------------------
# Tests validation (config defensive)
# -----------------------------------------------------------------------------

class TestConfigValidation:
    def test_positive_stop_loss_raises(self):
        with pytest.raises(ValueError):
            DailyLimitsConfig(daily_stop_loss_usd=200.0)  # doit etre <= 0

    def test_negative_stop_win_raises(self):
        with pytest.raises(ValueError):
            DailyLimitsConfig(daily_stop_win_usd=-100.0)  # doit etre >= 0

    def test_negative_max_trades_raises(self):
        with pytest.raises(ValueError):
            DailyLimitsConfig(daily_max_trades=-1)


# -----------------------------------------------------------------------------
# Tests on_trade_close trigger detection
# -----------------------------------------------------------------------------

class TestTriggerDetection:
    def test_stop_loss_one_shot_trigger(self, guard: DailyLimitsGuard):
        """Le flag stop_loss_triggered se met a True UNE FOIS au franchissement."""
        guard.on_trade_close(pnl_usd=-100.0)
        assert guard.snapshot()["stop_loss_triggered"] is False
        guard.on_trade_close(pnl_usd=-150.0)  # cumul -$250
        assert guard.snapshot()["stop_loss_triggered"] is True
        # Et reste True
        guard.on_trade_close(pnl_usd=-50.0)
        assert guard.snapshot()["stop_loss_triggered"] is True

    def test_pnl_none_increments_count_not_cumul(self, guard: DailyLimitsGuard):
        """pnl_usd=None (timeout) -> count +1 mais cumul inchange."""
        guard.on_trade_close(pnl_usd=-50.0)
        guard.on_trade_close(pnl_usd=None)  # timeout
        snap = guard.snapshot()
        assert snap["cumul_pnl_usd"] == -50.0
        assert snap["trade_count"] == 2


# -----------------------------------------------------------------------------
# Tests scenario reel — incident souche 08/06
# -----------------------------------------------------------------------------

class TestIncident08June:
    """Reproduit le scenario souche Bot 1 SIM1 08/06 (-$2010 sur 7 trades).

    Sequence reelle (cf prompt mission) :
      #1 +$137 (cumul +137)
      #2 -$480 (cumul -343)  <- DOIT etre tue ici si seuil -$200
      #3 -$705 (cumul -1048)
      ... (4 trades supp non capture)
    """

    def test_kill_switch_would_have_stopped_bot1_08june(self, guard: DailyLimitsGuard):
        # Trade #1 : +$137
        guard.on_trade_close(pnl_usd=+137.0)
        allow, _ = guard.check_allow("NQ")
        assert allow is True, "Cumul +$137 doit permettre entry #2"

        # Trade #2 : -$480 -> cumul = -343 = au-dela du seuil
        guard.on_trade_close(pnl_usd=-480.0)
        allow, reason = guard.check_allow("NQ")
        assert allow is False, (
            "Kill switch -$200 aurait DU bloquer apres trade #2 (cumul -$343)"
        )
        assert reason == guard.REASON_STOP_LOSS

        # Verification : bot reste bloque pour trades 3-7
        guard.on_trade_close(pnl_usd=-705.0)  # cumul -1048
        allow, _ = guard.check_allow("NQ")
        assert allow is False, "Bot doit rester bloque toute la journee"


# -----------------------------------------------------------------------------
# Test thread safety
# -----------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_on_trade_close_no_lost_update(
        self, default_config: DailyLimitsConfig, tmp_state_dir: str
    ):
        """100 threads on_trade_close(+1) en parallel -> cumul == 100."""
        g = DailyLimitsGuard("bot_test", default_config, tmp_state_dir, "20260608")
        # Desactiver triggers pour ne pas atteindre stop_win avant la fin
        g.config.stop_win_enabled = False
        g.config.max_trades_enabled = False
        N = 100

        def worker():
            g.on_trade_close(pnl_usd=+1.0)

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = g.snapshot()
        assert snap["trade_count"] == N
        assert snap["cumul_pnl_usd"] == pytest.approx(float(N))
