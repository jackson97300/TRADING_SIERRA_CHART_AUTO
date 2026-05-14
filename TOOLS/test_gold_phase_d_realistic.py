"""test_gold_phase_d_realistic.py

Test gold_phase_d avec series synthetiques realistes :
  - MGC vs 6E : correlation negative typique (~-0.6) -> apres sign-flip = positive
  - ZN+ZB : momentum typique -0.005 a +0.005 -> proxy * 1000 = -5 a +5
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "CORE"))

from gold_phase_d_streaming import (  # noqa: E402
    GoldPhaseDState,
    add_gold_phase_d_streaming,
)


def test_dxy_corr_realistic():
    """MGC et 6E avec correlation imposee = -0.6 (negative typique gold/euro).

    Apres sign-flip dans gold_phase_d (proxy DXY = -corr(MGC, 6E)),
    on attend une valeur positive ~0.3-0.7.
    """
    np.random.seed(42)
    n = 100
    base_returns = np.random.randn(n) * 0.002
    noise = np.random.randn(n) * 0.001
    mgc_returns = base_returns + noise
    eur_returns = -base_returns * 0.6 + noise * 0.5  # corr negative ~-0.6

    mgc_prices = 2000 * np.exp(np.cumsum(mgc_returns))
    eur_prices = 1.10 * np.exp(np.cumsum(eur_returns))

    state = GoldPhaseDState()
    corrs = []
    for i in range(n):
        ts = pd.Timestamp("2026-04-01 14:00:00", tz="UTC") + pd.Timedelta(minutes=i)
        row = {
            "ts_event": ts,
            "close": float(mgc_prices[i]),
            "high": float(mgc_prices[i]) + 0.5,
            "low": float(mgc_prices[i]) - 0.5,
            "volume": 100.0,
        }
        out = add_gold_phase_d_streaming(
            row, state, close_6e=float(eur_prices[i]),
            close_zn=None, close_zb=None,
        )
        corrs.append(out.get("im_dxy_corr_60d", np.nan))

    last_corr = corrs[-1]
    print(
        f"Last im_dxy_corr_60d : {last_corr:.3f} "
        f"(attendu : 0.2 a 0.8 apres sign-flip de -0.6)"
    )
    assert 0.2 < last_corr < 0.8, (
        f"Corr attendue 0.3-0.7 (sign-flip de -0.6), recu {last_corr}"
    )
    print("PASS : im_dxy_corr_60d realistic OK")


def test_real_yields_realistic():
    """ZN/ZB momentum 0.3% sur 20 bars (= 0.15% sur 10 bars) -> proxy ~1.5."""
    state = GoldPhaseDState()
    zn_prices = np.linspace(110.0, 110.33, 20)  # +0.3% sur 20 bars
    zb_prices = np.linspace(140.0, 140.42, 20)  # +0.3% sur 20 bars
    proxies = []
    for i in range(20):
        ts = pd.Timestamp("2026-04-01 14:00:00", tz="UTC") + pd.Timedelta(minutes=i)
        row = {
            "ts_event": ts, "close": 2000.0,
            "high": 2000.5, "low": 1999.5, "volume": 100.0,
        }
        out = add_gold_phase_d_streaming(
            row, state, close_6e=None,
            close_zn=float(zn_prices[i]), close_zb=float(zb_prices[i]),
        )
        proxies.append(out.get("im_real_yields_proxy", np.nan))

    last = proxies[-1]
    print(
        f"Last im_real_yields_proxy : {last:.2f} "
        f"(attendu ~1.5 pour 0.15% momentum 10-bar)"
    )
    assert 0.5 < last < 3.0, f"Proxy attendu 0.5-3.0, recu {last}"
    print("PASS : im_real_yields_proxy realistic OK")


if __name__ == "__main__":
    test_dxy_corr_realistic()
    test_real_yields_realistic()
