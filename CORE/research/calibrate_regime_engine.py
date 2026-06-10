"""calibrate_regime_engine.py — Calibration empirique seuils regime_engine.

Audit Jackson 03/05 : seuils actuels regime_engine.py donnent actionable_rate
2.8-3.4% (target 15-25%). Distributions features sur 14 jours montrent seuils
mal calibres (sess_range_atr=2.0 capture 50%+ bars).

Approche :
  1. Charge V4 enriched 14 jours data clean (17/04 -> 30/04)
  2. Applique 3 calibrations (current, v2 calibrated, v3 aggressive)
  3. Compare distributions mode/favor/actionable
  4. Cross-validation jours gagnants (22/04, 28/04 NQ TREND BULL/SHORT) vs perdants (29/04 RANGE)
  5. Output rapport
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def compute_regime_calibrated(bar: dict, version: str = "v2") -> dict:
    """Calibration alternative regime_engine."""
    def gf(key, default=0.0):
        v = bar.get(key)
        if v is None: return default
        try:
            f = float(v)
            return default if f != f else f
        except: return default

    def gi(key, default=0):
        v = bar.get(key)
        if v is None: return default
        try:
            f = float(v)
            return default if f != f else int(f)
        except: return default

    if version == "v1_current":
        # Seuils actuels (regime_engine.py production)
        SEUILS = {
            "sp_strong": 10, "sp_weak": 3,
            "vwap_dir": 5.0, "vwap_flat": 1.0,
            "atr_expand": 1.2, "atr_compress": 0.6,
            "poc_distant": 30, "poc_close": 5,
            "va_confine": 60, "va_hors": 30,
            "tdp_strong": 0.65, "tdp_weak": 0.3,
            "vol_extreme": 2.0, "vol_high": 1.2, "vol_normal": 0.5,
            "mode_strong": 5, "mode_lead": 2,
            "conf_actionable": 0.20,
        }
    elif version == "v2_calibrated":
        # Calibration empirique sur quartiles 14 jours NQ RTH
        SEUILS = {
            "sp_strong": 100, "sp_weak": 30,        # was 10/3 (p25=47, p75=170)
            "vwap_dir": 2.5, "vwap_flat": 0.5,      # was 5/1 (p75=3.78)
            "atr_expand": 1.0, "atr_compress": 0.4, # was 1.2/0.6
            "poc_distant": 15, "poc_close": 3,      # was 30/5 (p75=19, p25=4)
            "va_confine": 30, "va_hors": 10,        # was 60/30 (p75=22)
            "tdp_strong": 0.30, "tdp_weak": 0.10,   # was 0.65/0.3 (p75=0.35)
            "vol_extreme": 4.5, "vol_high": 3.0, "vol_normal": 1.5,  # was 2.0/1.2/0.5
            "mode_strong": 4, "mode_lead": 1,       # was 5/2
            "conf_actionable": 0.10,                # was 0.20
        }
    elif version == "v3_aggressive":
        # Calibration plus permissive (target actionable 25-35%)
        SEUILS = {
            "sp_strong": 80, "sp_weak": 40,
            "vwap_dir": 1.5, "vwap_flat": 0.3,
            "atr_expand": 0.8, "atr_compress": 0.3,
            "poc_distant": 10, "poc_close": 2,
            "va_confine": 20, "va_hors": 5,
            "tdp_strong": 0.25, "tdp_weak": 0.05,
            "vol_extreme": 5.5, "vol_high": 3.5, "vol_normal": 1.5,
            "mode_strong": 3, "mode_lead": 1,
            "conf_actionable": 0.05,
        }

    trend_votes = 0
    range_votes = 0

    # 1. IB Breakout (poids 2)
    ib_up = gi("ib_broken_up", 0)
    ib_dn = gi("ib_broken_down", 0)
    ib_range = gf("ib_range_ticks", 0.0)
    if ib_up or ib_dn:
        trend_votes += 2
    elif ib_range > 0:
        range_votes += 1

    # 2. Day Type (poids 2 trend / 1 sinon)
    dt = gi("day_type", 0)
    if dt == 4: trend_votes += 2
    elif dt == 2: trend_votes += 1
    elif dt in (1, 3): range_votes += 1

    # 3. Single Prints
    sp = gi("single_print_count", 0)
    if sp > SEUILS["sp_strong"]: trend_votes += 1
    elif sp < SEUILS["sp_weak"]: range_votes += 1

    # 4. VWAP Slope
    vwap_slope_abs = abs(gf("vwap_slope_10", 0.0))
    if vwap_slope_abs > SEUILS["vwap_dir"]: trend_votes += 1
    elif vwap_slope_abs < SEUILS["vwap_flat"]: range_votes += 1

    # 5. Sess/ATR
    atr_ratio = gf("sess_range_atr", 0.0)
    if atr_ratio > SEUILS["atr_expand"]: trend_votes += 1
    elif atr_ratio < SEUILS["atr_compress"]: range_votes += 1

    # 6. Open Type
    ot = gi("open_type", 0)
    if ot in (1, 2, 3, 4): trend_votes += 1  # OD + OTD
    elif ot in (5, 6): range_votes += 1  # ORR

    # 7. Profile Shape
    ps = gi("profile_shape", -1)
    if ps in (1, 2): trend_votes += 1
    elif ps in (0, 3): range_votes += 1

    # 8. POC distance
    poc_d = gf("poc_bar_dist", 0.0)
    if poc_d > SEUILS["poc_distant"]: trend_votes += 1
    elif poc_d < SEUILS["poc_close"]: range_votes += 1

    # 9. Bars in VA
    bva = gf("bars_in_va", 0.0)
    if bva > SEUILS["va_confine"]: range_votes += 1
    elif bva < SEUILS["va_hors"]: trend_votes += 1

    # 10. Trend Day Probability
    tdp = gf("trend_day_probability", 0.5)
    if tdp > SEUILS["tdp_strong"]: trend_votes += 1
    elif tdp < SEUILS["tdp_weak"]: range_votes += 1

    # Mode verdict
    if trend_votes >= SEUILS["mode_strong"]:
        mode = "TREND"
    elif range_votes >= SEUILS["mode_strong"]:
        mode = "RANGE"
    elif trend_votes >= range_votes + SEUILS["mode_lead"] + 1:
        mode = "TREND"
    elif range_votes >= trend_votes + SEUILS["mode_lead"] + 1:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # Bias proxy
    score = 0.0
    bear = 0; bull = 0
    if gf("vwap_slope_10") > 1.0: score += 0.25; bull += 1
    elif gf("vwap_slope_10") < -1.0: score -= 0.25; bear += 1
    of_dir = gi("delta_day_dir") or gi("cvd_day_dir")
    if of_dir > 0: score += 0.25; bull += 1
    elif of_dir < 0: score -= 0.25; bear += 1
    pos = gf("range_pos", 50.0)
    if pos > 70: score -= 0.20; bear += 1
    elif pos < 30: score += 0.20; bull += 1
    vd = gi("vwap_d_side", 0)
    if vd > 0: score += 0.15; bull += 1
    elif vd < 0: score -= 0.15; bear += 1
    dd = gi("delta_divergence", 0)
    if dd > 0: score += 0.15; bull += 1
    elif dd < 0: score -= 0.15; bear += 1

    score = max(-1.0, min(1.0, score))
    bias_label = "BULLISH" if score > 0.30 else ("BEARISH" if score < -0.30 else "NEUTRE")

    # Direction
    if mode == "RANGE":
        if pos >= 70: favor = "SHORT"
        elif pos <= 30: favor = "LONG"
        else: favor = "NEUTRE"
    elif bias_label == "BULLISH": favor = "LONG"
    elif bias_label == "BEARISH": favor = "SHORT"
    else: favor = "NEUTRE"

    # Override
    if favor == "LONG" and bear >= 3: favor = "NEUTRE"
    elif favor == "SHORT" and bull >= 3: favor = "NEUTRE"

    # Vol regime
    if atr_ratio >= SEUILS["vol_extreme"]: vol = "EXTREME"
    elif atr_ratio >= SEUILS["vol_high"]: vol = "HIGH"
    elif atr_ratio >= SEUILS["vol_normal"]: vol = "NORMAL"
    else: vol = "LOW"

    # Confidence
    confidence = min(1.0, abs(trend_votes - range_votes) / 12.0)

    actionable = (
        mode != "NORMAL"
        and favor != "NEUTRE"
        and vol != "EXTREME"
        and confidence >= SEUILS["conf_actionable"]
    )

    return {
        "mode": mode, "favor": favor, "vol": vol,
        "trend_votes": trend_votes, "range_votes": range_votes,
        "confidence": confidence, "actionable": int(actionable),
        "bias_score": score,
    }


def main():
    print("=== CALIBRATION REGIME_ENGINE — 3 versions sur 14 jours NQ RTH ===\n")

    con = duckdb.connect()
    df = con.execute("""
    SELECT * FROM read_parquet('D:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=04/data.parquet')
    WHERE ts_event >= TIMESTAMP '2026-04-17'
    """).fetchdf()
    print(f"Bars total NQ: {len(df)}")

    # Apply 3 versions
    for version in ["v1_current", "v2_calibrated", "v3_aggressive"]:
        results = []
        for _, row in df.iterrows():
            bar = row.to_dict()
            r = compute_regime_calibrated(bar, version)
            results.append(r)
        rdf = pd.DataFrame(results)
        rdf["ts_event"] = df["ts_event"].values
        rdf["date"] = pd.to_datetime(rdf["ts_event"]).dt.date

        n = len(rdf)
        print(f"\n### {version.upper()} ({n} bars)")
        print(f"  mode    : {rdf['mode'].value_counts().to_dict()}")
        print(f"  favor   : {rdf['favor'].value_counts().to_dict()}")
        print(f"  vol     : {rdf['vol'].value_counts().to_dict()}")
        print(f"  actionable %: {rdf['actionable'].mean()*100:.1f}%")

        # Par jour
        by_day = rdf.groupby("date").agg(
            n=("mode", "count"),
            trend=("mode", lambda x: round((x=="TREND").sum()/len(x)*100, 1)),
            range_=("mode", lambda x: round((x=="RANGE").sum()/len(x)*100, 1)),
            long=("favor", lambda x: round((x=="LONG").sum()/len(x)*100, 1)),
            short=("favor", lambda x: round((x=="SHORT").sum()/len(x)*100, 1)),
            actionable=("actionable", lambda x: round(x.mean()*100, 1)),
        )
        # Mark jours gagnants Bot V1 NQ
        v1_perf = {
            "2026-04-21": "+",  # data
            "2026-04-22": "+",
            "2026-04-23": "+",
            "2026-04-24": "+464$ TREND BULL (data DMP partial)",
            "2026-04-27": "?",
            "2026-04-28": "+422$ mix SHORT-dom",
            "2026-04-29": "-270$ range LONG-forced",
            "2026-04-30": "-230$ range",
        }
        by_day["v1_perf"] = by_day.index.astype(str).map(v1_perf).fillna("")
        print()
        print(by_day.to_string())


if __name__ == "__main__":
    main()
