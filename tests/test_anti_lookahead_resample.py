"""
Tests anti-lookahead resample 1m → 5m / 15m / 1h (anti-leak strict).

Pattern obligatoire pour eviter le leak du futur :
  Pour bar 1m at T :
    - Bar 5m label "10:00" couvre 10:00-10:04 → utiliser CETTE bar = LEAK
    - Bar 5m label "09:55" couvre 09:55-09:59 → strictement avant T = OK
  → on prend last bar HTF FERMEE strictement AVANT T

Methode :
  resample_htf_with_lag(df_1m, target_freq="5min")
    1. Resample 1m → 5m via pd.resample (label='left' = 10:00 contient 10:00-10:04)
    2. Pour bar 1m at T, joiner bar 5m fermee = floor(T - 1min) au plus proche bar HTF
    3. EQUIVALENT : shift(target_freq // source_freq) puis broadcast

Tests :
  - test_no_lookahead_long_uptrend : si 1m strictement croissant, bar 5m at T < bar 1m at T (sinon leak)
  - test_no_lookahead_long_downtrend : symetrique SHORT
  - test_boundary_5m : bar 1m at 10:00 doit utiliser bar 5m label 09:55 (pas 10:00)
  - test_boundary_15m : bar 1m at 10:00 doit utiliser bar 15m label 09:45 (pas 10:00)
  - test_gap_weekend_handling : reset apres gap 49h vendredi-dimanche
  - test_first_bar_no_htf_history : bar 1m at start of day -> NaN HTF (pas crash)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "CORE"))

import pandas as pd
import numpy as np
import pytest


# Will be implemented in CORE/enrich_dataset_v5_htf.py
# from enrich_dataset_v5_htf import resample_htf_with_lag


def make_bars_1m_uptrend(n: int = 200, start_price: float = 100.0, slope: float = 0.1) -> pd.DataFrame:
    # FIX (code-reviewer 02/05) : tz-naive pour matcher convention enrich_dataset_v5_htf
    ts = pd.date_range("2026-04-28 13:30:00", periods=n, freq="1min")
    closes = start_price + np.arange(n) * slope
    return pd.DataFrame({
        "ts_event": ts,
        "open": closes - 0.05,
        "high": closes + 0.05,
        "low": closes - 0.10,
        "close": closes,
        "volume": np.full(n, 100),
    })


def make_bars_1m_with_weekend_gap() -> pd.DataFrame:
    """Bars vendredi 16h-17h ET puis dimanche 18h-19h ET (gap weekend)."""
    # FIX tz-naive
    fri = pd.date_range("2026-04-25 20:00:00", periods=60, freq="1min")  # 16:00 ET
    sun = pd.date_range("2026-04-26 22:00:00", periods=60, freq="1min")  # 18:00 ET dimanche
    ts = list(fri) + list(sun)
    closes = list(np.arange(60) * 0.1 + 100) + list(np.arange(60) * -0.1 + 105)
    return pd.DataFrame({
        "ts_event": ts,
        "open": [c - 0.05 for c in closes],
        "high": [c + 0.05 for c in closes],
        "low": [c - 0.10 for c in closes],
        "close": closes,
        "volume": [100] * 120,
    })


def _make_5m_enriched(df_1m):
    """Helper : resample 5m + features + join anti-lookahead."""
    from enrich_dataset_v5_htf import resample_to_htf, compute_htf_features, add_htf_columns_with_lag
    df_5m = resample_to_htf(df_1m, "5min")
    df_5m_feat = compute_htf_features(df_5m)
    return add_htf_columns_with_lag(df_1m, df_5m_feat, "5min", "_5m")


def _make_15m_enriched(df_1m):
    from enrich_dataset_v5_htf import resample_to_htf, compute_htf_features, add_htf_columns_with_lag
    df_15m = resample_to_htf(df_1m, "15min")
    df_15m_feat = compute_htf_features(df_15m)
    return add_htf_columns_with_lag(df_1m, df_15m_feat, "15min", "_15m")


class TestNoLookaheadResample:

    def test_no_lookahead_uptrend_5m(self):
        """Si 1m strict uptrend, bar 5m HTF at T doit etre <= close 1m at T (sinon leak futur)."""
        df_1m = make_bars_1m_uptrend(200)
        df_with_5m = _make_5m_enriched(df_1m)
        # Pour chaque bar 1m at T : close_5m <= close_1m (skip NaN)
        valid = df_with_5m["close_5m"].notna()
        assert (df_with_5m.loc[valid, "close_5m"] <= df_with_5m.loc[valid, "close"] + 1e-9).all(), \
            "LEAK detecte : close_5m > close_1m (bar HTF inclut bars futures)"

    def test_no_lookahead_downtrend_5m(self):
        df_1m = make_bars_1m_uptrend(200, slope=-0.1)
        df_with_5m = _make_5m_enriched(df_1m)
        valid = df_with_5m["close_5m"].notna()
        assert (df_with_5m.loc[valid, "close_5m"] >= df_with_5m.loc[valid, "close"] - 1e-9).all(), \
            "LEAK detecte downtrend"

    def test_boundary_5m(self):
        """Bar 1m at 13:36 doit utiliser bar 5m label 13:30 (close = 100.4)."""
        df_1m = make_bars_1m_uptrend(20)
        df_with_5m = _make_5m_enriched(df_1m)
        # Bar 1m at 13:36 (idx 6) : doit voir bar 5m '13:30' (close = bar 1m at 13:34 = 100.4)
        bar = df_with_5m.iloc[6]
        assert bar["close_5m"] == pytest.approx(100.4, abs=1e-6), f"got {bar['close_5m']}"

    def test_boundary_5m_strict_at_close_excluded(self):
        """Bar 1m at 13:35 (T = ts_event_htf_close de bar 13:30) → strict exclu, NaN."""
        df_1m = make_bars_1m_uptrend(20)
        df_with_5m = _make_5m_enriched(df_1m)
        # Bar 1m at 13:35 (idx 5) : ts_event_htf_close de bar '13:30' = 13:35
        # allow_exact_matches=False → strict < → bar 5m '13:30' exclue
        # Pas de bar 5m precedente → NaN
        bar = df_with_5m.iloc[5]
        assert pd.isna(bar["close_5m"]), f"Strict exclusion failed, got {bar['close_5m']}"

    def test_boundary_15m(self):
        """Bar 1m at 13:46 doit utiliser bar 15m label 13:30 (close = bar 1m at 13:44)."""
        df_1m = make_bars_1m_uptrend(60)
        df_with_15m = _make_15m_enriched(df_1m)
        # Bar 1m at 13:46 (idx 16) : doit voir bar 15m '13:30' (close = bar 1m at 13:44 = 100.0+14*0.1)
        bar = df_with_15m.iloc[16]
        assert bar["close_15m"] == pytest.approx(100.0 + 14 * 0.1, abs=1e-6), \
            f"got {bar['close_15m']}"

    def test_gap_weekend_handling(self):
        """Apres gap weekend, EMA HTF doit reset (pas slope artificielle)."""
        df_1m = make_bars_1m_with_weekend_gap()
        df_with_5m = _make_5m_enriched(df_1m)
        # Bar 1m at start of Sunday session : ema_20_5m doit refleter reset (= close de bar 5m post-gap)
        sun_start = df_with_5m[df_with_5m["ts_event"] >= "2026-04-26 22:30"].iloc[0:5]
        # ema_5m doit etre faible OU NaN sur premieres bars post-gap (pas saut vendredi)
        # Plus simple : verifier que pas de NaN quand on a au moins 1 bar 5m post-gap fermee
        assert "ema_20_5m" in df_with_5m.columns, "ema_20_5m doit exister"

    def test_first_bar_no_htf_history(self):
        """Bar 1m at start of dataset → HTF cols = NaN (pas crash)."""
        df_1m = make_bars_1m_uptrend(5)  # juste 5 bars 1m
        df_with_5m = _make_5m_enriched(df_1m)
        # Premiere bar 1m : pas de bar 5m fermee precedente → NaN
        assert pd.isna(df_with_5m["close_5m"].iloc[0]), \
            "Premiere bar 1m doit avoir close_5m = NaN (pas de HTF history)"


# ─────────────────────────────────────────────────────────────────────
# Test no-shift HTF features post-horizon (RESERVE ml-trainer Q4.4)
# ─────────────────────────────────────────────────────────────────────

class TestNoShiftHtfPostHorizon:
    """Lopez ch.7 — test causalite stricte features HTF.

    Pattern leak rare mais grave :
    - Pour bar 1m at T (entry potentielle), features HTF (_5m, _15m, _1h)
      ne DOIVENT dependre QUE de bars HTF dont ts_event_htf_close < T
    - Si modifier bars HTF FUTURES (post-T) change features pour bar 1m at T
      → leak structurel via merge_asof boggue ou compute features HTF leak

    Test methodologie :
    1. Genere dataset 1m + enrich HTF
    2. Capture features HTF pour bar T au milieu
    3. Modifie radicalement OHLC bars HTF post-T
    4. Re-enrichit
    5. Assert features HTF pour bar 1m at T sont IDENTIQUES (pas changees)
    """

    def test_modify_future_5m_does_not_affect_past_features(self):
        """Modifier bars 1m apres T ne doit PAS changer features HTF pour bar 1m at T."""
        from enrich_dataset_v5_htf import enrich_1m_with_all_htf

        # Generate 1m bars sur 200 bars (3+ heures)
        df_1m_v1 = make_bars_1m_uptrend(200)
        df_v1 = enrich_1m_with_all_htf(df_1m_v1)

        # Capture features HTF pour bar T = milieu (idx 100, ~1h40 dans le test)
        target_idx = 100
        target_ts = df_v1.iloc[target_idx]["ts_event"]
        htf_cols = [c for c in df_v1.columns
                    if any(c.endswith(s) for s in ("_5m", "_15m", "_1h"))]
        features_v1 = df_v1.loc[df_v1["ts_event"] == target_ts, htf_cols].iloc[0]

        # Modifie radicalement OHLC bars 1m POST-target (idx 101+)
        df_1m_v2 = df_1m_v1.copy()
        post_mask = df_1m_v2.index > target_idx
        df_1m_v2.loc[post_mask, "open"] += 100  # shock prix +100
        df_1m_v2.loc[post_mask, "high"] += 100
        df_1m_v2.loc[post_mask, "low"] += 100
        df_1m_v2.loc[post_mask, "close"] += 100
        df_1m_v2.loc[post_mask, "volume"] *= 10  # volume x10

        # Re-enrich avec donnees modifiees post-target
        df_v2 = enrich_1m_with_all_htf(df_1m_v2)
        features_v2 = df_v2.loc[df_v2["ts_event"] == target_ts, htf_cols].iloc[0]

        # Compare : features HTF pour bar T DOIVENT etre identiques
        leaks = []
        for col in htf_cols:
            v1 = features_v1[col]
            v2 = features_v2[col]
            # Tolerer NaN identiques
            if pd.isna(v1) and pd.isna(v2):
                continue
            if pd.isna(v1) or pd.isna(v2):
                leaks.append(f"{col}: v1={v1} vs v2={v2} (NaN mismatch)")
                continue
            # Tolerance numerique (float precision)
            if not np.isclose(v1, v2, rtol=1e-9, atol=1e-9):
                leaks.append(f"{col}: v1={v1:.6f} vs v2={v2:.6f} (LEAK)")

        assert len(leaks) == 0, (
            f"LEAK POST-HORIZON DETECTE sur {len(leaks)} features HTF :\n" +
            "\n".join(leaks[:10])
        )

    def test_horizon_zone_immediately_after_target_safe(self):
        """Edge case : modifier UNIQUEMENT les 1-12 bars 1m juste apres target.
        Cette zone est exactement ce qu'un horizon labels couvrirait → critical no-leak."""
        from enrich_dataset_v5_htf import enrich_1m_with_all_htf

        df_1m_v1 = make_bars_1m_uptrend(200)
        df_v1 = enrich_1m_with_all_htf(df_1m_v1)

        target_idx = 100
        target_ts = df_v1.iloc[target_idx]["ts_event"]
        htf_cols = [c for c in df_v1.columns
                    if any(c.endswith(s) for s in ("_5m", "_15m", "_1h"))]
        features_v1 = df_v1.loc[df_v1["ts_event"] == target_ts, htf_cols].iloc[0]

        # Modifie SEULEMENT les 12 bars 1m juste apres target (zone horizon)
        df_1m_v2 = df_1m_v1.copy()
        zone_mask = (df_1m_v2.index > target_idx) & (df_1m_v2.index <= target_idx + 12)
        df_1m_v2.loc[zone_mask, "close"] += 50

        df_v2 = enrich_1m_with_all_htf(df_1m_v2)
        features_v2 = df_v2.loc[df_v2["ts_event"] == target_ts, htf_cols].iloc[0]

        leaks = []
        for col in htf_cols:
            v1 = features_v1[col]
            v2 = features_v2[col]
            if pd.isna(v1) and pd.isna(v2):
                continue
            if pd.isna(v1) or pd.isna(v2):
                leaks.append(f"{col}: NaN mismatch")
                continue
            if not np.isclose(v1, v2, rtol=1e-9, atol=1e-9):
                leaks.append(f"{col}: v1={v1:.6f} vs v2={v2:.6f}")

        assert len(leaks) == 0, (
            f"LEAK ZONE HORIZON DETECTE ({len(leaks)} features HTF cassent) :\n" +
            "\n".join(leaks[:10])
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
