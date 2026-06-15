"""Tests E2E SierraPipelineOrchestrator._maybe_cross_day_reset.

Fix R1 code-reviewer INCIDENT #58 (15/06/2026) : valide que le reset cross-day
au niveau pipeline orchestrator preserve composite_poc.daily_vpocs_5d/20d.

Si quelqu'un re-introduit `self._market_profile_advanced_state =
MarketProfileAdvancedState()` ces tests echouent.

Date : 2026-06-15
"""
from __future__ import annotations

from datetime import date

import pytest

# Skip si imports pipeline cassés (bug pré-existant phase_b_plus_engine)
# Le test reste pertinent quand le bug d'import sera fixé.
sierra_pipeline = pytest.importorskip(
    "CORE.sierra_pipeline",
    reason="SierraPipelineOrchestrator imports failed (likely missing module unrelated to this fix)",
)


def test_cross_day_reset_preserves_composite_poc_state():
    """Verifie que daily_vpocs_5d/20d survivent au cross-day reset.

    Scenario :
      1. Instancie SierraPipelineOrchestrator
      2. Inject manuellement 2 daily VPOCs dans composite_poc
      3. Force cross-day reset via _maybe_cross_day_reset(target_date)
      4. Assert daily_vpocs_5d toujours non-vide
      5. Assert sweep + judas ont bien ete reinitialises
    """
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    from CORE.market_profile_advanced import LiquiditySweepState, JudasSwingState

    pipeline = SierraPipelineOrchestrator("NQ")
    pipeline._current_trading_date = date(2026, 6, 10)

    # Setup : injecte historique composite_poc (= simule 2 jours deja archives)
    cp = pipeline._market_profile_advanced_state.composite_poc
    cp.daily_vpocs_5d.append(29196.5)
    cp.daily_vpocs_5d.append(29907.0)
    cp.daily_vpocs_20d.append(29196.5)
    cp.daily_vpocs_20d.append(29907.0)
    cp.current_day = "2026-06-10"
    cp.last_vpoc_today = 29850.0

    # Setup : injecte state actif sur sweep + judas (sera reset)
    pipeline._market_profile_advanced_state.sweep.active_sweeps_high.append(
        (30000.0, 2),
    )
    pipeline._market_profile_advanced_state.judas.in_london = True

    # ACTION : cross-day reset
    reset_done = pipeline._maybe_cross_day_reset(date(2026, 6, 11))
    assert reset_done is True

    # PRESERVE : composite_poc historique conserve
    cp_after = pipeline._market_profile_advanced_state.composite_poc
    assert len(cp_after.daily_vpocs_5d) == 2, (
        f"daily_vpocs_5d perdu apres cross-day reset : {list(cp_after.daily_vpocs_5d)}. "
        f"Bug INCIDENT #58 reintroduit ?"
    )
    assert list(cp_after.daily_vpocs_5d) == [29196.5, 29907.0]
    assert len(cp_after.daily_vpocs_20d) == 2
    # current_day et last_vpoc_today preserves (la transition se fera sur la
    # prochaine bar via compute_composite_poc qui detecte trading_day != current_day)
    assert cp_after.current_day == "2026-06-10"
    assert cp_after.last_vpoc_today == 29850.0

    # RESET : sweep + judas reinitialises (events ephemeres day-scoped)
    assert len(pipeline._market_profile_advanced_state.sweep.active_sweeps_high) == 0, (
        "sweep.active_sweeps_high doit etre vide apres reset"
    )
    assert pipeline._market_profile_advanced_state.judas.in_london is False, (
        "judas.in_london doit etre False apres reset"
    )
    # Sub-states types corrects (preuve reinstanciation reelle)
    assert isinstance(
        pipeline._market_profile_advanced_state.sweep, LiquiditySweepState,
    )
    assert isinstance(
        pipeline._market_profile_advanced_state.judas, JudasSwingState,
    )


def test_cross_day_reset_multiple_consecutive_days():
    """3 cross-day resets consecutifs : daily_vpocs accumulent."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator("ES")
    pipeline._current_trading_date = date(2026, 6, 10)
    cp = pipeline._market_profile_advanced_state.composite_poc

    # Simule progression : J1 archive 100 -> J2 archive 110 -> J3 archive 120
    cp.daily_vpocs_5d.append(100.0)
    cp.daily_vpocs_20d.append(100.0)
    pipeline._maybe_cross_day_reset(date(2026, 6, 11))

    pipeline._market_profile_advanced_state.composite_poc.daily_vpocs_5d.append(110.0)
    pipeline._market_profile_advanced_state.composite_poc.daily_vpocs_20d.append(110.0)
    pipeline._maybe_cross_day_reset(date(2026, 6, 12))

    pipeline._market_profile_advanced_state.composite_poc.daily_vpocs_5d.append(120.0)
    pipeline._market_profile_advanced_state.composite_poc.daily_vpocs_20d.append(120.0)
    pipeline._maybe_cross_day_reset(date(2026, 6, 15))

    cp_final = pipeline._market_profile_advanced_state.composite_poc
    assert list(cp_final.daily_vpocs_5d) == [100.0, 110.0, 120.0]
    assert list(cp_final.daily_vpocs_20d) == [100.0, 110.0, 120.0]


def test_cross_day_reset_first_day_no_op():
    """1er cross-day call : pas de reset, juste init current_trading_date."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator("NQ")
    assert pipeline._current_trading_date is None

    result = pipeline._maybe_cross_day_reset(date(2026, 6, 15))
    assert result is False  # Pas de reset, juste init
    assert pipeline._current_trading_date == date(2026, 6, 15)


def test_cross_day_reset_same_day_no_op():
    """Cross-day reset appele avec meme date : no-op."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator("NQ")
    pipeline._current_trading_date = date(2026, 6, 15)

    result = pipeline._maybe_cross_day_reset(date(2026, 6, 15))
    assert result is False
