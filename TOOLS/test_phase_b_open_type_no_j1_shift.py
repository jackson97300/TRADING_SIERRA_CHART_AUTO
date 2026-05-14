"""test_phase_b_open_type_no_j1_shift.py

Test regression Fix #1 v2 V4 (audit code-reviewer 14/05/2026).

Le Fix #1 v1 (commit pas merge) introduisait un J-1 shift silencieux :
  groupby("session_date_trading") + filter mins_et >= 630 capturait en PREMIER
  la bar Asia 18:00 ET (mins_et=1080, date_et=jour precedent). Resultat :
  open_cash/ib_high mergees par date_et donnaient les VALEURS DE LA VEILLE.

Fix #1 v2 ajoute 3 conditions cumulees :
  post_ib = grp[
    (grp["mins_et"] >= ib_close_min)      # post IB window
    & (grp["mins_et"] < bounds["asia_start"])  # avant next Asia
    & (grp["date_et"] == date)             # JOUR CASH effectif
  ]

Ce test verifie sur le parquet V4 ES April 2026 (apres Fix v2 applique) :
  Pour 100% des sessions classifiees (open_type != 0) :
    used_open_cash == close de la bar 9:30 ET du JOUR cash
    used_price_1030 == close de la bar 10:30 ET du JOUR cash
    used_ib_high == max(high) bars 9:30-10:29 ET du JOUR cash

Si ce test FAIL en CI : Fix v1 reapparu silencieusement → INCIDENT_LOG.

Usage : python -X utf8 TOOLS/test_phase_b_open_type_no_j1_shift.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")


def reconstruct_temporal_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute date_et + mins_et au DataFrame (drop avant write batch)."""
    df = df.copy()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    ts_et = df["ts_event"].dt.tz_convert(ET)
    df["date_et"] = ts_et.dt.date
    df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute
    return df


def test_no_j1_shift(parquet_path: Path, symbol: str = "ES") -> dict:
    """Verifie absence J-1 shift sur le parquet V4 enriched.

    Returns : dict { matches, mismatches, mismatch_details }
    """
    df = pd.read_parquet(parquet_path)
    df = reconstruct_temporal_cols(df)

    # bounds per-symbole
    us_start = 510 if symbol == "MGC" else 570  # 8:30 ET MGC, 9:30 ET ES/NQ
    ib_close = us_start + 60  # 9:30 MGC, 10:30 ES/NQ

    matches = {"open_cash": 0, "price_1030": 0, "ib_high_low": 0}
    mismatches = {"open_cash": 0, "price_1030": 0, "ib_high_low": 0}
    mismatch_details = []

    for sess_d, grp in df.groupby("session_date_trading", sort=True):
        # Skip sessions UNKNOWN (cause legitime : holiday/partial/data)
        if grp["open_type"].iloc[0] == 0:
            continue

        # Bar open cash : date_et==sess_d AND mins_et==us_start
        cash_open_bar = grp[
            (grp["date_et"] == sess_d) & (grp["mins_et"] == us_start)
        ]
        if cash_open_bar.empty:
            continue

        # Verif 1 : open_cash == close bar 9:30 du jour cash
        real_close_open = float(cash_open_bar.iloc[0]["close"])
        used_open_cash = float(cash_open_bar.iloc[0]["open_cash"])
        if abs(real_close_open - used_open_cash) < 0.01:
            matches["open_cash"] += 1
        else:
            mismatches["open_cash"] += 1
            mismatch_details.append(
                f"{sess_d}: open_cash real={real_close_open} used={used_open_cash}"
            )

        # Verif 2 : price_1030 == close bar 10:30
        bar_1030 = grp[(grp["date_et"] == sess_d) & (grp["mins_et"] == ib_close)]
        if not bar_1030.empty:
            real_close_1030 = float(bar_1030.iloc[0]["close"])
            used_price_1030 = float(bar_1030.iloc[0]["price_1030"])
            if abs(real_close_1030 - used_price_1030) < 0.01:
                matches["price_1030"] += 1
            else:
                mismatches["price_1030"] += 1

        # Verif 3 : ib_high/ib_low == bars IB window du jour cash
        cash_window = grp[
            (grp["date_et"] == sess_d)
            & (grp["mins_et"] >= us_start)
            & (grp["mins_et"] < ib_close)
        ]
        if not bar_1030.empty and not cash_window.empty:
            real_ib_high = float(cash_window["high"].max())
            real_ib_low = float(cash_window["low"].min())
            used_ib_high = float(bar_1030.iloc[0]["ib_high"])
            used_ib_low = float(bar_1030.iloc[0]["ib_low"])
            if (
                abs(real_ib_high - used_ib_high) < 0.01
                and abs(real_ib_low - used_ib_low) < 0.01
            ):
                matches["ib_high_low"] += 1
            else:
                mismatches["ib_high_low"] += 1

    return {
        "matches": matches,
        "mismatches": mismatches,
        "mismatch_details": mismatch_details[:5],
    }


def main():
    print("=" * 70)
    print("TEST REGRESSION Fix #1 v2 V4 - no J-1 shift")
    print("=" * 70)

    ok = True
    for symbol in ("ES", "NQ"):
        parquet = ROOT / f"DATA/DATASETS/v4_enriched/symbol={symbol}.c.0/year=2026/month=04/data.parquet"
        if not parquet.exists():
            print(f"\n[SKIP] {symbol} April 2026 parquet not found")
            continue

        print(f"\n--- {symbol} April 2026 ---")
        result = test_no_j1_shift(parquet, symbol=symbol)

        for metric in ("open_cash", "price_1030", "ib_high_low"):
            m = result["matches"][metric]
            mm = result["mismatches"][metric]
            total = m + mm
            status = "PASS" if mm == 0 else "FAIL"
            print(f"  {metric:15s} : {m}/{total} matches ({status})")
            if mm > 0:
                ok = False

        if result["mismatch_details"]:
            print("  First mismatches :")
            for d in result["mismatch_details"]:
                print(f"    {d}")

    print("\n" + "=" * 70)
    print(f"VERDICT GLOBAL : {'PASS' if ok else 'FAIL - J-1 SHIFT REINTRODUIT'}")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
