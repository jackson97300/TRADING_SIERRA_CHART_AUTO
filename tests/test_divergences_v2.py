"""Tests Phase 3.8 divergences_v2.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ────────────────────────────────────────────────────────────────────────────
# Tests detection brute divergences
# ────────────────────────────────────────────────────────────────────────────

def test_delta_div_buy_price_down_delta_up():
    """Price descend ET delta monte -> delta_div_buy True."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0)

    # 10 bars : price descend (100 -> 91), delta monte (-1000 -> -100)
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    assert f["delta_div_buy"] is True
    assert f["delta_div_sell"] is False
    assert f["delta_divergence_any"] is True


def test_delta_div_sell_price_up_delta_down():
    """Price monte ET delta descend -> delta_div_sell True."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0)

    prices = [100.0 + i for i in range(10)]
    deltas = [1000.0 - 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    assert f["delta_div_sell"] is True
    assert f["delta_div_buy"] is False


def test_no_divergence_both_aligned():
    """Price ET delta dans meme sens -> aucune divergence."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10)

    prices = [100.0 + i for i in range(10)]
    deltas = [1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    assert f["delta_div_buy"] is False
    assert f["delta_div_sell"] is False
    assert f["delta_divergence_any"] is False


# ────────────────────────────────────────────────────────────────────────────
# Tests delta_div_strength (SIGNED)
# ────────────────────────────────────────────────────────────────────────────

def test_strength_positive_bullish_divergence():
    """Bullish div -> delta_div_strength positif (slope_delta > slope_price)."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10)

    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # slope_delta = 100, slope_price = -1 -> strength = (100 - (-1)) / 2 = 50.5
    assert f["delta_div_strength"] > 0


def test_strength_negative_bearish_divergence():
    """Bearish div -> delta_div_strength negatif."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10)

    prices = [100.0 + i for i in range(10)]
    deltas = [1000.0 - 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # slope_delta = -100, slope_price = +1 -> strength = (-100 - 1) / 2 = -50.5
    assert f["delta_div_strength"] < 0


# ────────────────────────────────────────────────────────────────────────────
# Tests filtre regime clean
# ────────────────────────────────────────────────────────────────────────────

def test_div_buy_clean_passes_threshold():
    """Bullish div avec slope_delta >> MIN_DELTA_SLOPE -> clean True."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=50.0)

    prices = [100.0 - i for i in range(10)]
    # slope_delta = +100 > MIN_DELTA_SLOPE 50
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # Phase 2.2 (12/06 PM) : delta_div_*_clean cast int (0/1) pour coherence
    # JSONL serialise vs datasets historiques v3. Avant: bool. Apres: int.
    assert f["delta_div_buy_clean"] == 1


def test_div_buy_clean_filtered_low_slope():
    """Bullish div mais slope_delta < MIN_DELTA_SLOPE -> clean 0."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=500.0)

    prices = [100.0 - i for i in range(10)]
    # slope_delta = +100 < MIN_DELTA_SLOPE 500
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    assert f["delta_div_buy"] is True  # detection brute reste bool
    # Phase 2.2 fix action #1 cast int
    assert f["delta_div_buy_clean"] == 0  # mais clean filtree (int 0)


# ────────────────────────────────────────────────────────────────────────────
# Tests zones tracking
# ────────────────────────────────────────────────────────────────────────────

def test_zone_tracking_increments_after_div_clean():
    """Apres divergence clean, n_zones_active incremente."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0,
                                    zone_retention=50)

    # Genere une divergence bullish clean
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    assert f["n_delta_div_buy_zones_active"] >= 1


def test_zone_expires_apres_retention():
    """Zone retiree apres bar_idx > zone_retention."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0,
                                    zone_retention=5)

    # Genere divergence
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    for p, d in zip(prices, deltas):
        calc.update(close=p, delta_bar=d, atr=2.0)

    # 10 bars apres sans div -> zone expire
    for i in range(10):
        f = calc.update(close=100.0, delta_bar=0.0, atr=2.0)

    assert f["n_delta_div_buy_zones_active"] == 0


def test_dist_to_nearest_zone_defined_after_div():
    """dist_delta_div_buy_nearest_atr DEFINI (non NaN) apres divergence."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0)

    # Bullish div
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    f = None
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # Zone(s) bullish creee(s) -> dist_buy doit etre non-NaN
    assert f["n_delta_div_buy_zones_active"] >= 1
    assert not math.isnan(f["dist_delta_div_buy_nearest_atr"]), (
        "Apres div_buy_clean, dist_delta_div_buy_nearest_atr doit etre defini"
    )


def test_dist_nearest_zone_helper_signed_directly():
    """Test direct helper _dist_to_nearest_zone : signed positif si zone > close."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    # Zone a 91, close 80 -> dist = (91-80)/2 = 5.5 > 0
    zones = [{"bar_idx": 10, "side": "buy", "price": 91.0}]
    dist = DivergencesV2Calculator._dist_to_nearest_zone(
        close=80.0, zones=zones, atr=2.0
    )
    assert dist > 0
    assert abs(dist - 5.5) < 0.01

    # Zone a 70, close 80 -> dist = (70-80)/2 = -5 < 0
    zones = [{"bar_idx": 10, "side": "buy", "price": 70.0}]
    dist = DivergencesV2Calculator._dist_to_nearest_zone(
        close=80.0, zones=zones, atr=2.0
    )
    assert dist < 0
    assert abs(dist - (-5.0)) < 0.01

    # Aucune zone -> NaN
    dist = DivergencesV2Calculator._dist_to_nearest_zone(
        close=80.0, zones=[], atr=2.0
    )
    assert math.isnan(dist)


# ────────────────────────────────────────────────────────────────────────────
# Tests context rolling
# ────────────────────────────────────────────────────────────────────────────

def test_ctx_bars_since_div_increments():
    """ctx_bars_since_div incremente apres divergence detectee.

    NOTE : difficile a tester proprement avec rolling buffer = on doit
    purger le pattern bullish detecte. Test simplifie : verifier que
    ctx_bars_since_div n'est PAS NaN apres une divergence.
    """
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0)

    # Genere divergence
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # Apres divergence, ctx_bars_since_div doit etre defini (0 si dernier bar)
    assert not math.isnan(f["ctx_bars_since_div"]), (
        "ctx_bars_since_div doit etre defini apres detection divergence"
    )
    assert f["ctx_bars_since_div"] >= 0


def test_ctx_bars_since_div_nan_cold_start():
    """Pas encore de divergence -> ctx_bars_since_div NaN."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10)
    # 5 bars sans div
    for i in range(15):
        f = calc.update(close=100.0, delta_bar=0.0, atr=2.0)

    assert math.isnan(f["ctx_bars_since_div"])


def test_ctx_div_density_20():
    """ctx_div_density_20 compte divergences sur 20 dernieres bars."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, context_window=20,
                                    min_delta_slope=10.0)

    # 1 divergence (10 bars setup)
    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    for p, d in zip(prices, deltas):
        f = calc.update(close=p, delta_bar=d, atr=2.0)

    # density >= 1 (au moins 1 dans 20 dernieres bars)
    assert f["ctx_div_density_20"] >= 1


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive cold-start / NaN / reset
# ────────────────────────────────────────────────────────────────────────────

def test_cold_start_buffer_under_10():
    """Buffer < slope_window -> empty features (NaN propre)."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10)

    for i in range(5):
        f = calc.update(close=100.0 + i, delta_bar=100.0, atr=2.0)
        assert f["delta_div_buy"] is False
        assert math.isnan(f["delta_div_strength"])


def test_nan_inputs_empty_features():
    """NaN inputs -> empty features."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator()
    f = calc.update(close=float("nan"), delta_bar=100.0, atr=2.0)
    assert f["delta_div_buy"] is False
    assert math.isnan(f["delta_div_strength"])


def test_reset_clears_state():
    """calc.reset() vide tout l'etat."""
    from CORE.divergences_v2 import DivergencesV2Calculator

    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=10.0)

    prices = [100.0 - i for i in range(10)]
    deltas = [-1000.0 + 100 * i for i in range(10)]
    for p, d in zip(prices, deltas):
        calc.update(close=p, delta_bar=d, atr=2.0)

    calc.reset()
    f = calc.update(close=100.0, delta_bar=0.0, atr=2.0)
    # Apres reset, cold-start
    assert math.isnan(f["delta_div_strength"])
    assert f["n_delta_div_buy_zones_active"] == 0


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_dataframe():
    """compute_divergences_v2_features batch."""
    from CORE.divergences_v2 import compute_divergences_v2_features

    # Bullish divergence sur 10 bars
    df = pd.DataFrame({
        "close": [100.0 - i for i in range(15)],
        "delta_bar": [-1000.0 + 100 * i for i in range(15)],
        "atr": [2.0] * 15,
    })
    result = compute_divergences_v2_features(df, slope_window=10,
                                              min_delta_slope=10.0)

    assert "delta_div_buy" in result.columns
    assert "ctx_bars_since_div" in result.columns
    # Les 9 premieres lignes en cold-start (NaN)
    assert not bool(result["delta_div_buy"].iloc[5])
    # Apres slope_window, divergence detectee
    assert bool(result["delta_div_buy"].iloc[10]) is True


def test_batch_missing_column_raises():
    """Colonne manquante -> ValueError."""
    from CORE.divergences_v2 import compute_divergences_v2_features

    df = pd.DataFrame({"close": [1.0]})
    with pytest.raises(ValueError, match="manquantes"):
        compute_divergences_v2_features(df)


# ────────────────────────────────────────────────────────────────────────────
# Tests fix INCIDENT_LOG #57 — MIN_DELTA_SLOPE recalibration
# ────────────────────────────────────────────────────────────────────────────

def test_min_delta_slope_constant_value():
    """Sentinel : MIN_DELTA_SLOPE doit etre 8.0 (calibration empirique 15/06).

    Si quelqu'un change la valeur sans test fire rate empirique, ce test
    flag la regression. Voir INCIDENT_LOG #57 pour contexte.
    """
    from CORE.divergences_v2 import MIN_DELTA_SLOPE

    assert MIN_DELTA_SLOPE == 8.0, (
        f"MIN_DELTA_SLOPE = {MIN_DELTA_SLOPE} != 8.0 attendu. "
        f"Tout changement de cette constante doit passer un test fire rate "
        f"empirique sur sierra_enriched JSONL (cible 5-40% clean/raw). "
        f"Cf INCIDENT_LOG #57 + DOCS/AUDIT_DEAD_FEATURES_20260615.md."
    )


def test_min_delta_slope_fire_rate_guaranteed_divergence():
    """Fix R1 code-reviewer : test fire rate avec divergence GARANTIE.

    Le test precedent acceptait fire_rate=0% = exactement le bug que ce fix
    corrige. Refactor : injecte une vraie divergence (price down + delta up)
    sur 50 bars consecutives au milieu d'un sample stochastique, puis assert
    fire rate >= 1.0% (au moins 1 declenchement sur 200 bars = preuve que
    MIN_DELTA_SLOPE filtre actif mais pas bloquant).
    """
    import random
    from CORE.divergences_v2 import DivergencesV2Calculator, MIN_DELTA_SLOPE

    random.seed(42)
    calc = DivergencesV2Calculator(slope_window=10, min_delta_slope=MIN_DELTA_SLOPE)

    n_buy_clean = 0
    n_sell_clean = 0
    n_total = 0

    # 50 bars warmup random
    for i in range(50):
        close = 100.0 + random.gauss(0, 1)
        delta_bar = random.gauss(0, 5)
        calc.update(close=close, delta_bar=delta_bar, atr=2.0)

    # 50 bars divergence GARANTIE bullish : price descend, delta monte forte
    # Pente delta_bar de -100 -> +400 sur 50 bars = slope ~10/bar > seuil 8.0
    for i in range(50):
        close = 95.0 - i * 0.5  # descend de 95 a 70
        delta_bar = -100.0 + 10 * i  # monte de -100 a +400 (slope ~+10/bar)
        result = calc.update(close=close, delta_bar=delta_bar, atr=2.0)
        if result.get("delta_div_buy_clean", 0): n_buy_clean += 1
        if result.get("delta_div_sell_clean", 0): n_sell_clean += 1
        n_total += 1

    # 100 bars cooldown random
    for i in range(100):
        close = 70.0 + random.gauss(0, 0.5)
        delta_bar = random.gauss(0, 3)
        result = calc.update(close=close, delta_bar=delta_bar, atr=2.0)
        if result.get("delta_div_buy_clean", 0): n_buy_clean += 1
        if result.get("delta_div_sell_clean", 0): n_sell_clean += 1
        n_total += 1

    fire_rate = (n_buy_clean + n_sell_clean) / n_total * 100
    # Avec divergence garantie + seuil 8.0, on doit avoir > 1% fire rate
    # (au moins quelques bars sur les 50 de divergence active).
    # Anti regression : si MIN_DELTA_SLOPE remonte a 100, fire_rate retombe 0 -> assert echoue.
    assert fire_rate >= 1.0, (
        f"Fire rate clean {fire_rate:.1f}% < 1.0% sur sample avec divergence "
        f"garantie. MIN_DELTA_SLOPE={MIN_DELTA_SLOPE} probablement trop haut "
        f"(bug INCIDENT #57 reproduit)."
    )
    # Borne haute : ne doit pas tout passer
    assert fire_rate < 50.0, (
        f"Fire rate clean {fire_rate:.1f}% > 50% : MIN_DELTA_SLOPE trop bas, "
        f"filtre bruit inefficace."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
