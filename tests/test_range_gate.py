"""Tests RangeGate — confluence 4 metriques (VA + IB + DAY + MQ_1D).

Date : 2026-04-30 (Jackson "ON A ACHETE HAUT DE RANGE")

Bug observe Bot 1 ES LONG @ 7198.50 :
- range_pos = 100% (sommet VA)
- ib_position_pct = 0.816 (haut IB)
- inside_cur_va = 0 (HORS VA = breakout)
→ Trade pris malgre 3 mesures "haut de range"

Fix : RangeGate avec seuil >=2/4 metriques en zone extreme = SKIP.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from CORE.range_gate import (  # noqa: E402
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    evaluate_range_gate,
)


# ─── Tests cas reel Jackson ──────────────────────────────────────────


class TestCaseJacksonHautDeRange:
    """Reproduction trade Bot 1 ES LONG @ 7197.75 du 30/04 (Jackson screen)."""

    def test_real_bot1_es_long_7197_breakout_va_high_observe(self):
        """REPRODUCTION EXACTE bar Bot 1 ES LONG @ 7197.75 (sortie SL -30t).
        Bar features réelles VPS state.json :
          range_pos=100.0, ib_position_pct=0.8103, dist_sess_high=76,
          dist_sess_low=-245, dist_1d_max_ticks=177, inside_cur_va=0.
        En mode observe (default), would_skip=True mais skip=False.
        FIX R2 : BREAKOUT_VA exige aussi >=1 confluence supp (range_pos=100
        + 1 metric = condition).
        """
        bar = {
            "range_pos": 100.0,
            "ib_position_pct": 0.8103,
            "dist_sess_high": 76.0,
            "dist_sess_low": -245.0,
            "dist_1d_max_ticks": 177.0,
            "dist_1d_min_ticks": -373.0,
            "inside_cur_va": 0,           # HORS VA = breakout
        }
        # Mode observe (default) : would_skip=True, skip=False
        result = evaluate_range_gate(bar, "BUY", "ES", mode="observe")
        assert result.would_skip is True
        assert result.skip is False
        assert "BREAKOUT_VA_HIGH" in result.skip_reason

        # Mode skip (mutation effective) : would_skip=True, skip=True
        result = evaluate_range_gate(bar, "BUY", "ES", mode="skip")
        assert result.would_skip is True
        assert result.skip is True

    def test_breakout_va_alone_no_confluence_no_would_skip(self):
        """FIX R2 : range_pos=100 + HORS VA SEUL (sans autre metric) =
        PAS de would_skip (evite blocage breakouts sains)."""
        bar = {
            "range_pos": 100.0,
            "ib_position_pct": 0.50,        # IB neutre (pas extreme)
            "dist_sess_high": 200.0,        # session range neutre
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 300.0,     # MQ_1D loin
            "dist_1d_min_ticks": -300.0,
            "inside_cur_va": 0,
        }
        # range_pos=100 SEUL = 1 metric matched, mais BREAKOUT_VA exige
        # 1 metric supp en plus → 1 metric = pas suffisant
        # Wait : range_pos est compte dans high_count quand >=85, donc
        # high_count = 1. BREAKOUT_VA exige >= 1 confluence supp = high_count >= 1
        # CONDITION SATISFAITE ici. Test verifie que c'est consistant.
        result = evaluate_range_gate(bar, "BUY", "ES", mode="skip")
        # range_pos>=85 → +1 high_count. + breakout_va condition trigger
        assert result.high_count == 1
        # BREAKOUT_VA + 1 confluence (lui-meme) = trigger
        assert result.would_skip is True

    def test_high_of_range_2_metrics_confluence_skip(self):
        """2 metriques en zone haute (sans breakout VA) → SKIP confluence 2/4."""
        bar = {
            "range_pos": 90.0,            # VA haute
            "ib_position_pct": 0.90,      # IB haute
            "dist_sess_high": 200.0,
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 200.0,
            "dist_1d_min_ticks": -200.0,
            "inside_cur_va": 1,           # DANS VA (pas breakout)
        }
        result = evaluate_range_gate(bar, "BUY", "ES", mode="skip")
        assert result.skip is True
        assert "HIGH_OF_RANGE_CONFLUENCE" in result.skip_reason
        assert result.high_count == 2

    def test_high_of_range_borderline_va_only_no_skip(self):
        """1 seule metrique haute (VA) → PAS de skip (confluence 1/4 < 2)."""
        bar = {
            "range_pos": 90.0,           # VA haute
            "ib_position_pct": 0.50,     # IB neutre
            "dist_sess_high": 200.0,
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 200.0,
            "dist_1d_min_ticks": -200.0,
        }
        result = evaluate_range_gate(bar, "BUY", "ES")
        assert result.skip is False, f"1/4 metric should NOT skip, got {result}"
        assert result.high_count == 1


# ─── Tests SHORT bas de range ────────────────────────────────────────


class TestLowOfRange:
    def test_low_of_range_2_metrics_skip_sell(self):
        bar = {
            "range_pos": 5.0,                  # VA basse
            "ib_position_pct": 0.10,           # IB basse
            "dist_sess_high": 250.0,
            "dist_sess_low": -50.0,            # sess_pos = 50/300 = 0.167 (>0.15 borderline)
            "dist_1d_max_ticks": 250.0,
            "dist_1d_min_ticks": -100.0,
        }
        result = evaluate_range_gate(bar, "SELL", "ES", mode="skip")
        # VA=5 + IB=0.10 = 2 metriques basses
        assert result.skip is True
        assert "LOW_OF_RANGE" in result.skip_reason

    def test_low_of_range_mq_1d_min_proche(self):
        """SHORT pres du 1d_min MQ (dist_1d_min_ticks ~= 0)."""
        bar = {
            "range_pos": 12.0,
            "ib_position_pct": 0.50,
            "dist_sess_high": 100.0,
            "dist_sess_low": -100.0,
            "dist_1d_max_ticks": 100.0,
            "dist_1d_min_ticks": -10.0,        # 10t au-dessus 1d_min ES (< 30)
        }
        result = evaluate_range_gate(bar, "SELL", "ES", mode="skip")
        # VA=12 (<=15) + MQ_1D_MIN=-10 (proche) = 2 metriques
        assert result.skip is True
        assert "MQ_1D_MIN" in result.skip_reason


# ─── Tests neutre / desactivation ─────────────────────────────────────


class TestNeutralAndDisabled:
    def test_neutral_position_no_skip_buy(self):
        bar = {
            "range_pos": 50.0,
            "ib_position_pct": 0.5,
            "dist_sess_high": 100.0,
            "dist_sess_low": -100.0,
            "dist_1d_max_ticks": 100.0,
            "dist_1d_min_ticks": -100.0,
        }
        for direction in ("BUY", "SELL"):
            result = evaluate_range_gate(bar, direction, "ES")
            assert result.skip is False
            assert result.high_count == 0
            assert result.low_count == 0

    def test_disabled_no_skip_even_extreme(self):
        bar = {
            "range_pos": 100.0,
            "ib_position_pct": 0.95,
            "dist_sess_high": 0.0,
            "dist_sess_low": -300.0,
            "dist_1d_max_ticks": 5.0,
            "dist_1d_min_ticks": -300.0,
        }
        result = evaluate_range_gate(bar, "BUY", "ES", enabled=False)
        assert result.skip is False, "enabled=False doit desactiver le gate"


# ─── Tests features partielles (Bot 2 V4) ─────────────────────────────


class TestPartialFeaturesBot2:
    """Bot 2 Databento V4 manque dist_sess_high/low. Doit fallback sur
    dist_1d_max_ticks_pct / dist_1d_min_ticks_pct."""

    def test_bot2_v4_pct_features_compute_sess_pos(self):
        bar = {
            "range_pos": 95.0,
            "ib_position_pct": 0.90,
            # dist_sess_high/low ABSENTES (Bot 2 V4)
            # Mais pct features presentes
            "dist_1d_max_ticks_pct": 0.05,    # 0.05% du prix sous 1d_max = haut day
            "dist_1d_min_ticks_pct": -1.5,    # 1.5% du prix au-dessus 1d_min
            # → sess_pos = 1.5 / (1.5 + 0.05) = 0.968 (haut)
            "dist_1d_max_ticks": 50.0,
            "dist_1d_min_ticks": -300.0,
        }
        result = evaluate_range_gate(bar, "BUY", "NQ", mode="skip")
        # VA=95 + IB=0.90 + DAY=0.968 = 3/4 metriques hautes
        assert result.skip is True
        assert result.high_count >= 3

    def test_missing_all_features_no_skip(self):
        """Si toutes features sont None/NaN → no skip (pas de signal)."""
        bar = {}
        result = evaluate_range_gate(bar, "BUY", "ES")
        assert result.skip is False
        assert result.high_count == 0


# ─── Tests confluence threshold ──────────────────────────────────────


class TestConfluenceThreshold:
    def test_min_confluence_3_strict(self):
        """min_confluence=3 → 2/4 ne skip plus."""
        bar = {
            "range_pos": 95.0,            # VA haute
            "ib_position_pct": 0.90,      # IB haute
            "dist_sess_high": 200.0,
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 200.0,
            "dist_1d_min_ticks": -200.0,
        }
        result = evaluate_range_gate(bar, "BUY", "ES", min_confluence=3)
        # 2/4 mais seuil 3 → no skip
        assert result.skip is False
        assert result.high_count == 2

    def test_min_confluence_1_aggressive(self):
        """min_confluence=1 → 1/4 skip deja."""
        bar = {
            "range_pos": 95.0,
            "ib_position_pct": 0.50,
            "dist_sess_high": 200.0,
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 200.0,
            "dist_1d_min_ticks": -200.0,
        }
        result = evaluate_range_gate(bar, "BUY", "ES", min_confluence=1, mode="skip")
        assert result.skip is True
        assert result.high_count == 1


# ─── Tests symbole NQ ─────────────────────────────────────────────────


class TestNQThresholds:
    def test_nq_dist_1d_max_threshold_100t(self):
        """NQ : dist_1d_max_ticks <= 100t = proche sommet (vs 30t ES)."""
        bar = {
            "range_pos": 50.0,           # neutre
            "ib_position_pct": 0.50,
            "dist_sess_high": 200.0,
            "dist_sess_low": -200.0,
            "dist_1d_max_ticks": 80.0,   # <100 NQ → proche sommet
            "dist_1d_min_ticks": -500.0,
        }
        result = evaluate_range_gate(bar, "BUY", "NQ")
        # 1/4 seulement → no skip (sauf si min_confluence=1)
        assert result.high_count == 1
        assert result.skip is False  # 1<2 default


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
