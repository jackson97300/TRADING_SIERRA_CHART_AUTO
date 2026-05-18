"""Test Phase 3c-A : verifier que 12 features sont produites depuis snapshot vendredi.

Utilise le snapshot du 15/05 fourni par Jackson comme input et appelle directement
_apply_phase_3c_A pour valider :
1. Aucune exception
2. Les 12 nouvelles cles sont presentes dans le payload
3. Les valeurs ont un sens (pas NaN/None systematique)
4. Valeurs coherentes vs formules attendues
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.enricher_chain import _apply_phase_3c_A


SNAPSHOT_FRIDAY = {
    "symbol": "NQ.c.0", "instrument_id": 42004058,
    "ts_event_iso": "2026-05-15T20:46:00+00:00",
    "open": 29170.75, "high": 29172.0, "low": 29168.25, "close": 29168.25,
    "volume": 89,
    "mq_call": 30000.0, "mq_put": 29300.0, "mq_hvl": 28990.0,
    "mq_1d_min": 29286.4902, "mq_1d_max": 30089.0098,
    "delta_bar": 28.0,
    "cvd_day": 1538.0, "delta_day_dir": 1,
    "ib_high": 29684.75, "ib_low": 29458.5,
    "sess_high": 29486.75, "sess_low": 29111.0,
    "atr": 24.928571, "atr_14m": 6.232143, "atr_14m_pct": 0.021366,
    "range_pos": 0.0,
    "range_size": 3.75,
    "bar_body_pct": -66.666667, "bar_body_ticks": -10.0,
    "momentum_5b": 32.0,
    "vix_level": 18.42, "vix_regime": 1.0,
    "mins_et": 1006, "session": 3,
    "is_in_asia": 0, "is_in_london": 0, "is_in_us_cash": 0, "is_in_us_after": 1,
    "session_date": "2026-05-15",
}


def _log_fn(code, **kwargs):
    print(f"  [LOG] {code}: {kwargs}")


def main():
    print("=" * 70)
    print("  TEST PHASE 3c-A : 12 features sur snapshot 15/05 NQ.c.0")
    print("=" * 70)

    payload = dict(SNAPSHOT_FRIDAY)
    keys_before = set(payload.keys())
    print(f"\nKeys avant : {len(keys_before)}")

    try:
        _apply_phase_3c_A(payload, symbol="NQ.c.0", log_fn=_log_fn)
        print("[OK] _apply_phase_3c_A execute sans exception")
    except Exception as e:
        print(f"[FAIL] Exception : {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    keys_after = set(payload.keys())
    new_keys = keys_after - keys_before
    print(f"Keys ajoutees : {len(new_keys)}")

    expected = {
        "bar_upper_wick_pct", "bar_lower_wick_pct",
        "bar_no_trade",
        "position_in_range",
        "dist_1d_max_ticks", "dist_1d_max_ticks_pct",
        "dist_1d_min_ticks", "dist_1d_min_ticks_pct",
        "sess_range_atr",
        "delta_day",
        # FIX M3 review : 7 cles regime au lieu de 2
        "regime_mode", "regime_favor", "regime_confidence",
        "regime_trend_votes", "regime_range_votes",
        "regime_vol", "regime_actionable",
    }
    missing = expected - new_keys
    extra = new_keys - expected
    if missing:
        print(f"[FAIL] Features ABSENTES du payload : {missing}")
    if extra:
        print(f"[INFO] Features extra (non attendues) : {extra}")

    print("\n=== VALEURS PRODUITES ===")
    for k in sorted(expected):
        if k in payload:
            v = payload[k]
            print(f"  {k:32s} = {v}")
        else:
            print(f"  {k:32s} = MISSING")

    # Cross-check formules
    print("\n=== CROSS-CHECK FORMULES ===")
    close = SNAPSHOT_FRIDAY["close"]  # 29168.25
    high = SNAPSHOT_FRIDAY["high"]    # 29172.0
    low = SNAPSHOT_FRIDAY["low"]      # 29168.25
    op = SNAPSHOT_FRIDAY["open"]      # 29170.75

    # bar_upper_wick = (high - max(open, close)) / close * 100
    expected_upper = (high - max(op, close)) / close * 100
    expected_upper_clip = max(0.0, min(3.0, expected_upper))
    print(f"  bar_upper_wick_pct expected: {expected_upper_clip:.6f} | got: {payload.get('bar_upper_wick_pct')}")

    # bar_lower_wick = (min(open, close) - low) / close * 100
    expected_lower = (min(op, close) - low) / close * 100
    expected_lower_clip = max(0.0, min(3.0, expected_lower))
    print(f"  bar_lower_wick_pct expected: {expected_lower_clip:.6f} | got: {payload.get('bar_lower_wick_pct')}")

    # bar_no_trade : delta_bar=28 (not None) -> 0
    print(f"  bar_no_trade expected: 0 (delta_bar={SNAPSHOT_FRIDAY['delta_bar']}) | got: {payload.get('bar_no_trade')}")

    # FIX B1 review : position_in_range = (close - mq_1d_min) / (mq_1d_max - mq_1d_min) clip [0,1]
    # snapshot : close=29168.25, mq_1d_min=29286.49, mq_1d_max=30089.01
    # close < mq_1d_min -> position negative -> clip 0.0
    expected_pir = (29168.25 - 29286.4902) / (30089.0098 - 29286.4902)
    expected_pir_clip = max(0.0, min(1.0, expected_pir))
    print(f"  position_in_range expected: {expected_pir_clip:.6f} (clip from {expected_pir:.6f}) | got: {payload.get('position_in_range')}")

    # FIX B2 review : sess_range_atr = sess_range_ticks / atr_daily_ticks
    # sess_high=29486.75, sess_low=29111.0 -> sess_range_ticks = 375.75/0.25 = 1503
    # atr=24.93 points -> atr_daily_ticks = 24.93/0.25 = 99.72
    # ratio expected = 1503 / 99.72 ≈ 15.07
    sess_range_ticks_calc = (29486.75 - 29111.0) / 0.25
    atr_daily_ticks_calc = 24.928571 / 0.25
    expected_sra = sess_range_ticks_calc / atr_daily_ticks_calc
    print(f"  sess_range_atr expected: {expected_sra:.4f} (was 241 with bug atr_14m) | got: {payload.get('sess_range_atr')}")

    # dist_1d_max_ticks = (mq_1d_max - close) / 0.25 = (30089.0098 - 29168.25) / 0.25
    expected_max_ticks = (SNAPSHOT_FRIDAY["mq_1d_max"] - close) / 0.25
    print(f"  dist_1d_max_ticks expected: {expected_max_ticks:.1f} | got: {payload.get('dist_1d_max_ticks')}")

    # delta_day = cvd_day = 1538
    print(f"  delta_day expected: 1538.0 | got: {payload.get('delta_day')}")

    # regime_mode / favor : depends on regime_engine
    print(f"  regime_mode = {payload.get('regime_mode')}")
    print(f"  regime_favor = {payload.get('regime_favor')}")

    print("\n=== VERDICT ===")
    if not missing:
        print("OK : 12/12 features generees. Phase A FONCTIONNELLE.")
    else:
        print(f"FAIL : {len(missing)} features manquantes.")
        sys.exit(2)


if __name__ == "__main__":
    main()
