"""Test range_detector_v3 sur NQ live d'aujourd'hui (11/05/2026).

Jackson observation chart NQ matin 11/05 : range 29275-29360 tient depuis ~10:30 ET.
Question : aurait-on detecte ce range avec range_detector_v3 sur data Databento V4 ?

Usage :
    python -X utf8 CORE/research/test_range_detector_today.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parent.parent.parent
_CORE = _ROOT / "CORE"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from CORE.range_detector_v3 import RangeDetectorV3  # noqa


def main():
    parquet_path = _ROOT / "DATA" / "PAPER_TRADES_V6_AUDIT" / "nq_mai_v4_fresh.parquet"
    if not parquet_path.exists():
        parquet_path = _ROOT / "DATA" / "PAPER_TRADES_V6_AUDIT" / "nq_mai_v4.parquet"
    if not parquet_path.exists():
        print(f"PARQUET ABSENT: {parquet_path}")
        return

    df = pd.read_parquet(parquet_path)
    print(f"Loaded NQ V4 mai 2026 : shape={df.shape}")

    # Filtrer aujourd'hui (11/05 UTC)
    if "ts_utc" in df.columns:
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
        today = pd.Timestamp("2026-05-11", tz="UTC")
        df_today = df[df["ts_utc"] >= today].copy()
    elif "ts_event" in df.columns:
        df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
        today = pd.Timestamp("2026-05-11", tz="UTC")
        df_today = df[df["ts_event"] >= today].copy()
    else:
        print(f"Colonnes : {list(df.columns)[:20]}")
        # Fallback: derniere 240 bars (4h)
        df_today = df.tail(240).copy()
        print("Fallback: derniere 240 bars (4h)")

    print(f"Bars aujourd'hui : {len(df_today)}")
    if len(df_today) < 60:
        print(f"Pas assez de bars pour macro lookback 60. Aborting.")
        return

    if "ts_utc" in df_today.columns:
        ts_col = "ts_utc"
    elif "ts_event" in df_today.columns:
        ts_col = "ts_event"
    else:
        ts_col = None
    if ts_col:
        print(f"Range temporel : {df_today[ts_col].iloc[0]} -> {df_today[ts_col].iloc[-1]}")

    print(f"Stats prix today :")
    print(f"  open  : {df_today['open'].iloc[0]:.2f}")
    print(f"  high  : {df_today['high'].max():.2f}")
    print(f"  low   : {df_today['low'].min():.2f}")
    print(f"  close : {df_today['close'].iloc[-1]:.2f}")
    print()

    # Instancier detecteur NQ
    det = RangeDetectorV3(sym="NQ")
    print(f"Detector config:")
    print(f"  macro_lookback     : {det.macro_lookback}")
    print(f"  buffer_ticks NQ    : {det.buffer_ticks}")
    print(f"  min_macro_criteres : {det.min_macro_criteres}")
    print()

    # Detection sur la derniere bar (= status range actuel)
    result = det.detect(df_today)

    print(f"=== VERDICT RANGE DETECTOR V3 (sur {len(df_today)} bars) ===")
    print(f"is_range          : {result.is_range}")
    print(f"is_range_macro    : {result.is_range_macro}")
    print(f"is_range_micro    : {result.is_range_micro}")
    print(f"n_macro_ok        : {result.n_macro_ok}/7 (seuil {det.min_macro_criteres})")
    print(f"reason            : {result.reason}")
    print()
    print(f"range_high_zone   : {result.range_high_zone}")
    print(f"range_low_zone    : {result.range_low_zone}")
    print(f"range_high_raw    : {result.range_high_raw}")
    print(f"range_low_raw     : {result.range_low_raw}")
    print(f"range_size_ticks  : {result.range_size_ticks}")
    print(f"range_pos         : {result.range_pos:.3f}")
    print()
    print(f"signal_hint       : {result.signal_hint}")
    print(f"range_break_risk  : {result.range_break_risk}")
    print(f"break_risk_conf   : {result.break_risk_confidence}")
    print()

    # Comparer avec ce que Jackson voit visuellement
    print(f"=== COMPARAISON VISUEL JACKSON vs DETECTOR ===")
    visual_high = 29360
    visual_low = 29275
    detected_high = result.range_high_zone or 0
    detected_low = result.range_low_zone or 0
    print(f"Jackson visuel range : [{visual_low}, {visual_high}] ampleur {(visual_high-visual_low)*4:.0f}t")
    print(f"Detector V3 range    : [{detected_low}, {detected_high}] ampleur {(detected_high-detected_low)*4:.0f}t")
    if result.is_range:
        diff_high = abs(detected_high - visual_high)
        diff_low = abs(detected_low - visual_low)
        print(f"Diff high : {diff_high:.2f} pts ({diff_high*4:.0f}t)")
        print(f"Diff low  : {diff_low:.2f} pts ({diff_low*4:.0f}t)")

    # Trade Bot 3 actuel position
    print()
    print(f"=== TRADE BOT 3 ACTUEL ===")
    print(f"Entry         : 29313.50 (NQ LONG REJECTION GEX_DN)")
    print(f"Range_pos actuel selon detector : {result.range_pos:.3f} (1=high, 0=low)")
    if result.is_range:
        if 0.40 <= result.range_pos <= 0.60:
            print(f"VERDICT : Entry @ 29313.50 = MILIEU DE RANGE (range_pos {result.range_pos:.2f})")
            print(f"          → Entry sub-optimale, devait attendre <0.30 (LONG) ou >0.70 (SHORT)")
        elif result.range_pos < 0.30:
            print(f"VERDICT : Entry pres du LOW = bon timing pour LONG_FADE")
        elif result.range_pos > 0.70:
            print(f"VERDICT : Entry pres du HIGH = mauvais timing pour LONG (devrait etre SHORT_FADE)")


if __name__ == "__main__":
    main()
