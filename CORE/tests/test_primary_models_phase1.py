"""
Tests unitaires Phase 1 — VWAP Reversion + Expected Move Reversion.

Phase 1 = seules strategies codees sans crash sur le dataset reel.
Reference : review round 3 code-reviewer + _validate_features.py.

Lancer : python -X utf8 -m pytest CORE/tests/test_primary_models_phase1.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from CORE.primary_models.base import SignalType
from CORE.primary_models.expected_move_reversion import ExpectedMoveReversionModel
from CORE.primary_models.vwap_reversion import VwapReversionModel


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def row_vwap(sd2u_atr=0.0, sd2d_pts=0.0, slope=0.0):
    return pd.Series({
        "dist_vwap_d_sd2u_atr": sd2u_atr,
        "dist_vwap_d_sd2d": sd2d_pts,
        "ctx_delta_slope_5": slope,
    })


def row_em(d_max=1.0, d_min=-1.0, vwap_dist=0.0):
    return pd.Series({
        "mq_dist_1d_max_atr": d_max,
        "mq_dist_1d_min_atr": d_min,
        "dist_vwap_d_atr": vwap_dist,
    })


# ═══════════════════════════════════════════════════════════════════════
# VWAP REVERSION
# ═══════════════════════════════════════════════════════════════════════

class TestVwapReversion:
    """Convention DMP : dist_sd2u_atr < 0 = prix AU-DESSUS SD2u (breakout).
    dist_sd2d > 0 = prix SOUS SD2d (breakout bas)."""

    def test_short_when_above_sd2_and_slope_down(self):
        """sd2u_atr negatif = prix au-dessus SD2u → SHORT vers VWAP."""
        model = VwapReversionModel()
        sig = model.generate_signal(row_vwap(sd2u_atr=-0.5, slope=-0.5))
        assert sig.type == SignalType.SELL
        assert sig.sl_ticks == 20
        assert sig.tp_ticks == 36

    def test_long_when_below_sd2_and_slope_up(self):
        """sd2d_pts positif = prix sous SD2d → LONG vers VWAP."""
        model = VwapReversionModel()
        sig = model.generate_signal(row_vwap(sd2d_pts=5.0, slope=0.5))
        assert sig.type == SignalType.BUY

    def test_hold_when_inside_bands(self):
        """sd2u_atr positif + sd2d_pts negatif = prix entre bandes → HOLD."""
        model = VwapReversionModel()
        sig = model.generate_signal(row_vwap(sd2u_atr=0.5, sd2d_pts=-5.0, slope=0.0))
        assert sig.type == SignalType.HOLD

    def test_hold_when_above_sd2_but_slope_still_up(self):
        """Breakout SD2u mais momentum haussier → pas de short."""
        model = VwapReversionModel()
        sig = model.generate_signal(row_vwap(sd2u_atr=-0.5, slope=0.2))
        assert sig.type == SignalType.HOLD

    def test_hold_when_slope_below_threshold(self):
        model = VwapReversionModel()
        sig = model.generate_signal(row_vwap(sd2u_atr=-0.5, slope=-0.1))
        assert sig.type == SignalType.HOLD

    def test_nan_inputs_return_hold(self):
        model = VwapReversionModel()
        row = pd.Series({
            "dist_vwap_d_sd2u_atr": np.nan,
            "dist_vwap_d_sd2d": np.nan,
            "ctx_delta_slope_5": np.nan,
        })
        sig = model.generate_signal(row)
        assert sig.type == SignalType.HOLD

    def test_inf_inputs_return_hold(self):
        model = VwapReversionModel()
        row = pd.Series({
            "dist_vwap_d_sd2u_atr": np.inf,
            "dist_vwap_d_sd2d": 0.0,
            "ctx_delta_slope_5": 0.0,
        })
        sig = model.generate_signal(row)
        assert sig.type == SignalType.HOLD

    def test_missing_feature_raises(self):
        model = VwapReversionModel()
        df = pd.DataFrame({"dist_vwap_d_sd2u_atr": [0.5]})
        with pytest.raises(ValueError, match="ctx_delta_slope_5|dist_vwap_d_sd2d"):
            model.check_features(df)

    def test_runs_on_real_dataset_without_crash(self):
        """Integration : vwap_reversion doit tourner sur le parquet reel sans crash."""
        from pathlib import Path
        parquet = Path("DATA/DATASETS/ES_dataset_v2.parquet")
        if not parquet.exists():
            pytest.skip("ES dataset not available")
        df = pd.read_parquet(parquet)
        model = VwapReversionModel()
        model.check_features(df)
        signals = model.run(df.head(200))
        assert len(signals) == 200


# ═══════════════════════════════════════════════════════════════════════
# EXPECTED MOVE REVERSION
# ═══════════════════════════════════════════════════════════════════════

class TestExpectedMoveReversion:

    def test_short_at_1d_max(self):
        """Convention DMP : prix au-dessus VWAP → vwap_dist < 0.
        Prix proche 1d_max + au-dessus VWAP → SHORT."""
        model = ExpectedMoveReversionModel(proximity_atr=0.2, min_vwap_dist_atr=0.3)
        sig = model.generate_signal(row_em(d_max=0.1, vwap_dist=-0.5))
        assert sig.type == SignalType.SELL

    def test_long_at_1d_min(self):
        """Convention DMP : prix en-dessous VWAP → vwap_dist > 0.
        Prix proche 1d_min + en-dessous VWAP → LONG."""
        model = ExpectedMoveReversionModel(proximity_atr=0.2, min_vwap_dist_atr=0.3)
        sig = model.generate_signal(row_em(d_min=0.1, vwap_dist=0.5))
        assert sig.type == SignalType.BUY

    def test_hold_away_from_levels(self):
        model = ExpectedMoveReversionModel(proximity_atr=0.2)
        sig = model.generate_signal(row_em(d_max=1.0, d_min=-1.0, vwap_dist=-0.5))
        assert sig.type == SignalType.HOLD

    def test_hold_at_max_but_below_vwap(self):
        """Prix proche 1d_max mais vwap_dist > 0 (VWAP au-dessus prix = prix SOUS VWAP)
        → pas de short (edge perdu, le prix est en-dessous du VWAP tout en etant
        proche du 1d_max — structure incoherente)."""
        model = ExpectedMoveReversionModel(proximity_atr=0.2, min_vwap_dist_atr=0.3)
        sig = model.generate_signal(row_em(d_max=0.1, vwap_dist=0.5))
        assert sig.type == SignalType.HOLD

    def test_nan_inputs_return_hold(self):
        model = ExpectedMoveReversionModel()
        row = pd.Series({
            "mq_dist_1d_max_atr": np.nan,
            "mq_dist_1d_min_atr": np.nan,
            "dist_vwap_d_atr": np.nan,
        })
        sig = model.generate_signal(row)
        assert sig.type == SignalType.HOLD

    def test_inf_inputs_return_hold(self):
        model = ExpectedMoveReversionModel()
        row = pd.Series({
            "mq_dist_1d_max_atr": np.inf,
            "mq_dist_1d_min_atr": -np.inf,
            "dist_vwap_d_atr": 0.5,
        })
        sig = model.generate_signal(row)
        assert sig.type == SignalType.HOLD

    def test_missing_feature_raises(self):
        model = ExpectedMoveReversionModel()
        df = pd.DataFrame({"mq_dist_1d_max_atr": [0.1]})
        with pytest.raises(ValueError, match="mq_dist_1d_min_atr|dist_vwap_d_atr"):
            model.check_features(df)

    def test_runs_on_real_dataset_without_crash(self):
        """Integration : EM reversion doit tourner sur le parquet reel sans crash."""
        from pathlib import Path
        parquet = Path("DATA/DATASETS/ES_dataset_v2.parquet")
        if not parquet.exists():
            pytest.skip("ES dataset not available")
        df = pd.read_parquet(parquet)
        model = ExpectedMoveReversionModel()
        model.check_features(df)
        signals = model.run(df.head(200))
        assert len(signals) == 200
