"""grid_search_regime.py — Grid search seuils optimaux regime_engine.

Objectif : trouver la meilleure calibration via search 4D :
  - vol_extreme : [3.5, 4.0, 4.5, 5.0, 5.5]
  - mode_strong : [3, 4, 5]
  - conf_actionable : [0.05, 0.10, 0.15]
  - vwap_dir : [1.5, 2.0, 2.5, 3.5]

Score multi-objectif :
  +/- 1pt par % d'ecart |actionable - 20%| (target 20%)
  +5pt si 22/04 NQ favor LONG > SHORT (jour BULL connu)
  +5pt si 28/04 NQ favor SHORT > LONG (gain bot V1 SHORT)
  +5pt si 23/04 NQ favor NEUTRE > 50% (range/choppy)
  -10pt si 30/04 NQ favor LONG > SHORT (jour perdant LONG-forced)
  +3pt par jour ou TREND_pct ou RANGE_pct > 50% (signal clair)
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.calibrate_regime_engine import compute_regime_calibrated


def make_compute_fn(seuils):
    """Custom compute regime avec seuils dynamiques."""
    def cf(bar):
        return compute_regime_calibrated(bar, version="custom_dynamic", )
    return cf


def compute_with_custom_seuils(bar, S):
    """Reproduit compute_regime_calibrated avec seuils custom S."""
    def gf(k, d=0.0):
        v = bar.get(k);
        if v is None: return d
        try: f = float(v); return d if f != f else f
        except: return d
    def gi(k, d=0):
        v = bar.get(k)
        if v is None: return d
        try: f = float(v); return d if f != f else int(f)
        except: return d

    trend_votes = 0; range_votes = 0
    if gi("ib_broken_up") or gi("ib_broken_down"): trend_votes += 2
    elif gf("ib_range_ticks") > 0: range_votes += 1

    dt = gi("day_type")
    if dt == 4: trend_votes += 2
    elif dt == 2: trend_votes += 1
    elif dt in (1, 3): range_votes += 1

    sp = gi("single_print_count")
    if sp > S["sp_strong"]: trend_votes += 1
    elif sp < S["sp_weak"]: range_votes += 1

    vw = abs(gf("vwap_slope_10"))
    if vw > S["vwap_dir"]: trend_votes += 1
    elif vw < S["vwap_flat"]: range_votes += 1

    ar = gf("sess_range_atr")
    if ar > S["atr_expand"]: trend_votes += 1
    elif ar < S["atr_compress"]: range_votes += 1

    ot = gi("open_type")
    if ot in (1,2,3,4): trend_votes += 1
    elif ot in (5,6): range_votes += 1

    ps = gi("profile_shape", -1)
    if ps in (1,2): trend_votes += 1
    elif ps in (0,3): range_votes += 1

    pd_dist = gf("poc_bar_dist")
    if pd_dist > S["poc_distant"]: trend_votes += 1
    elif pd_dist < S["poc_close"]: range_votes += 1

    bva = gf("bars_in_va")
    if bva > S["va_confine"]: range_votes += 1
    elif bva < S["va_hors"]: trend_votes += 1

    tdp = gf("trend_day_probability", 0.5)
    if tdp > S["tdp_strong"]: trend_votes += 1
    elif tdp < S["tdp_weak"]: range_votes += 1

    if trend_votes >= S["mode_strong"]: mode = "TREND"
    elif range_votes >= S["mode_strong"]: mode = "RANGE"
    elif trend_votes >= range_votes + S["mode_lead"]: mode = "TREND"
    elif range_votes >= trend_votes + S["mode_lead"]: mode = "RANGE"
    else: mode = "NORMAL"

    score = 0.0; bear = 0; bull = 0
    if gf("vwap_slope_10") > 1.0: score += 0.25; bull += 1
    elif gf("vwap_slope_10") < -1.0: score -= 0.25; bear += 1
    of_dir = gi("delta_day_dir") or gi("cvd_day_dir")
    if of_dir > 0: score += 0.25; bull += 1
    elif of_dir < 0: score -= 0.25; bear += 1
    pos = gf("range_pos", 50.0)
    if pos > 70: score -= 0.20; bear += 1
    elif pos < 30: score += 0.20; bull += 1
    vd = gi("vwap_d_side")
    if vd > 0: score += 0.15; bull += 1
    elif vd < 0: score -= 0.15; bear += 1

    score = max(-1.0, min(1.0, score))
    bias = "BULLISH" if score > 0.30 else ("BEARISH" if score < -0.30 else "NEUTRE")

    if mode == "RANGE":
        favor = "SHORT" if pos >= 70 else ("LONG" if pos <= 30 else "NEUTRE")
    elif bias == "BULLISH": favor = "LONG"
    elif bias == "BEARISH": favor = "SHORT"
    else: favor = "NEUTRE"

    if favor == "LONG" and bear >= 3: favor = "NEUTRE"
    elif favor == "SHORT" and bull >= 3: favor = "NEUTRE"

    if ar >= S["vol_extreme"]: vol = "EXTREME"
    elif ar >= S["vol_high"]: vol = "HIGH"
    elif ar >= S["vol_normal"]: vol = "NORMAL"
    else: vol = "LOW"

    confidence = min(1.0, abs(trend_votes - range_votes) / 12.0)
    actionable = (mode != "NORMAL" and favor != "NEUTRE" and vol != "EXTREME"
                  and confidence >= S["conf_actionable"])

    return {"mode": mode, "favor": favor, "vol": vol, "actionable": int(actionable),
            "trend_votes": trend_votes, "range_votes": range_votes}


def score_calibration(by_day_df, actionable_pct):
    """Score multi-objectif. Plus c'est haut, mieux c'est."""
    score = 0.0

    # 1. Actionable rate close to 20% target
    target = 20.0
    score -= abs(actionable_pct - target) * 0.5

    # 2. Jours connus alignement
    days = by_day_df.set_index("date") if "date" in by_day_df.columns else by_day_df

    def get(date_str, col):
        if date_str in days.index.astype(str):
            return days.loc[days.index.astype(str) == date_str, col].iloc[0]
        return None

    # 22/04 NQ : BULL day -> favor LONG should dominate
    long_22 = get("2026-04-22", "long_pct")
    short_22 = get("2026-04-22", "short_pct")
    if long_22 is not None and short_22 is not None:
        if long_22 > short_22 and long_22 >= 15: score += 5
        elif long_22 > short_22: score += 2

    # 28/04 NQ : SHORT-dominant gagnant -> favor SHORT > LONG
    long_28 = get("2026-04-28", "long_pct")
    short_28 = get("2026-04-28", "short_pct")
    if long_28 is not None and short_28 is not None:
        if short_28 > long_28 and short_28 >= 25: score += 5
        elif short_28 > long_28: score += 2

    # 23/04 NQ : range/choppy -> NEUTRE majority
    long_23 = get("2026-04-23", "long_pct")
    short_23 = get("2026-04-23", "short_pct")
    if long_23 is not None and short_23 is not None:
        neutre_23 = 100 - long_23 - short_23
        if neutre_23 >= 60: score += 3

    # 30/04 NQ : range, bot V1 a perdu LONG -> ne pas favor LONG fort
    long_30 = get("2026-04-30", "long_pct")
    short_30 = get("2026-04-30", "short_pct")
    if long_30 is not None and short_30 is not None:
        if long_30 < 25: score += 3  # OK ne pas favor LONG fort
        if long_30 > 50: score -= 5  # BAD : favor LONG sur jour perdant

    # 29/04 NQ : range, bot V1 a perdu LONG -> ne pas favor LONG fort
    long_29 = get("2026-04-29", "long_pct")
    if long_29 is not None and long_29 > 50: score -= 5

    return score


def main():
    print("=== GRID SEARCH calibration regime_engine (NQ 14 jours) ===\n")

    con = duckdb.connect()
    df = con.execute("""
    SELECT * FROM read_parquet('D:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=04/data.parquet')
    WHERE ts_event >= TIMESTAMP '2026-04-17'
    """).fetchdf()
    bars = [row.to_dict() for _, row in df.iterrows()]
    print(f"Bars: {len(bars)}\n")

    # Grid 4D
    grid = list(itertools.product(
        [3.5, 4.5, 5.5],            # vol_extreme
        [3, 4, 5],                  # mode_strong
        [0.05, 0.10, 0.15],         # conf_actionable
        [1.5, 2.5, 3.5],            # vwap_dir
    ))
    print(f"Combinations: {len(grid)}\n")

    results = []
    for vol_extreme, mode_strong, conf_act, vwap_dir in grid:
        S = {
            "sp_strong": 100, "sp_weak": 30,
            "vwap_dir": vwap_dir, "vwap_flat": 0.5,
            "atr_expand": 1.0, "atr_compress": 0.4,
            "poc_distant": 15, "poc_close": 3,
            "va_confine": 30, "va_hors": 10,
            "tdp_strong": 0.30, "tdp_weak": 0.10,
            "vol_extreme": vol_extreme, "vol_high": vol_extreme - 1.5,
            "vol_normal": max(0.5, vol_extreme - 3.0),
            "mode_strong": mode_strong, "mode_lead": 1,
            "conf_actionable": conf_act,
        }

        rdf = pd.DataFrame([compute_with_custom_seuils(b, S) for b in bars])
        rdf["ts_event"] = df["ts_event"].values
        rdf["date"] = pd.to_datetime(rdf["ts_event"]).dt.date.astype(str)

        actionable_pct = rdf["actionable"].mean() * 100

        by_day = rdf.groupby("date").agg(
            n=("mode", "count"),
            long_pct=("favor", lambda x: round((x == "LONG").sum() / len(x) * 100, 1)),
            short_pct=("favor", lambda x: round((x == "SHORT").sum() / len(x) * 100, 1)),
            trend_pct=("mode", lambda x: round((x == "TREND").sum() / len(x) * 100, 1)),
            actionable_pct=("actionable", lambda x: round(x.mean() * 100, 1)),
        ).reset_index()

        sc = score_calibration(by_day, actionable_pct)
        results.append({
            "vol_extreme": vol_extreme, "mode_strong": mode_strong,
            "conf_act": conf_act, "vwap_dir": vwap_dir,
            "actionable_pct": round(actionable_pct, 1),
            "score": round(sc, 1),
            "by_day": by_day,
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    print("=== TOP 10 calibrations ===")
    print(f"{'rank':>4} | {'vol_ext':>7} {'mode':>4} {'conf':>5} {'vw_dir':>6} | actionable% | score")
    print("-" * 70)
    for i, r in enumerate(results[:10]):
        print(f"{i+1:>4} | {r['vol_extreme']:>7} {r['mode_strong']:>4} {r['conf_act']:>5} {r['vwap_dir']:>6} | "
              f"{r['actionable_pct']:>11} | {r['score']:>5}")

    print()
    print("=== DETAIL BEST CALIBRATION ===")
    best = results[0]
    print(f"vol_extreme={best['vol_extreme']}, mode_strong={best['mode_strong']}, "
          f"conf_actionable={best['conf_act']}, vwap_dir={best['vwap_dir']}")
    print(f"Actionable %: {best['actionable_pct']}%, Score: {best['score']}\n")
    print(best["by_day"].to_string())


if __name__ == "__main__":
    main()
