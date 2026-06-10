"""
regime_decomposition_3_candidates.py — Decompose les fires des 3 candidats GO_STRONG_NONSTAT
issus de audit_confluence_long_color_levels.py par mois + VIX bucket pour
distinguer "edge structurel" vs "accident regime".

Recommandation ml-trainer 06/05 (validation finale) :
> "Concentration top2 50%+ veut dire 2 mois sur 4 dominent. Identifier QUELS mois
> et VIX/regime associe = preuve ou non d'edge structurel vs accident regime.
> A faire AVANT GO integration."

Output : tableau {candidat x mois} avec n_fires + WR + mean_net + Sharpe.
+ {candidat x VIX_bucket} si dispo.

Usage : python -X utf8 CORE/research/regime_decomposition_3_candidates.py
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"

TICK_SIZE = 0.25
SLIPPAGE_TICKS_ROUND_TRIP = 2.0

# Les 3 candidats validers ml-trainer
CANDIDATES = [
    {
        "id": 1,
        "symbol": "NQ",
        "direction": "LONG",
        "name": "MQ_put_0dte + long_up_zones",
        "level_col": "dist_mq_put_0dte_pct",
        "near_pct": 0.04,
        "zone_col": "n_long_up_zones_active",
        "zone_min": 2,
    },
    {
        "id": 2,
        "symbol": "NQ",
        "direction": "LONG",
        "name": "MQ_put_0dte + color_up_zones",
        "level_col": "dist_mq_put_0dte_pct",
        "near_pct": 0.04,
        "zone_col": "n_color_up_zones_active",
        "zone_min": 2,
    },
    {
        "id": 3,
        "symbol": "ES",
        "direction": "SHORT",
        "name": "pVWAP + color_dn_cluster",
        "level_col": "dist_pvwap_pct",
        "near_pct": 0.07,
        "zone_col": "n_color_dn_cluster_within_0_2pct",
        "zone_min": 2,
    },
]


def load_all_months(symbol):
    sym_root = DATA_ROOT / f"symbol={symbol}.c.0" / "year=2026"
    if not sym_root.exists():
        return pd.DataFrame()
    months = sorted(p for p in sym_root.glob("month=*") if p.is_dir())
    dfs = []
    for m in months:
        f = m / "data.parquet"
        if f.exists():
            dfs.append(pd.read_parquet(f))
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df.sort_values("ts_event").reset_index(drop=True)


def filter_rth(df):
    ts_utc = pd.to_datetime(df["ts_event"], utc=True)
    h = ts_utc.dt.hour
    m = ts_utc.dt.minute
    minutes_utc = h * 60 + m
    mask = (minutes_utc >= 13 * 60 + 30) & (minutes_utc < 20 * 60)
    return df[mask].reset_index(drop=True)


def decompose_candidate(cand):
    print(f"\n{'=' * 80}")
    print(f"  CANDIDAT {cand['id']} : {cand['symbol']} {cand['direction']} — {cand['name']}")
    print(f"{'=' * 80}")

    df = load_all_months(cand["symbol"])
    if df.empty:
        print("  Pas de data")
        return
    df = filter_rth(df)
    print(f"  Total bars RTH: {len(df)} ({df['ts_event'].min().date()} -> {df['ts_event'].max().date()})")

    # Build signal
    if cand["level_col"] not in df.columns or cand["zone_col"] not in df.columns:
        print(f"  Cols manquantes : {cand['level_col']}={cand['level_col'] in df.columns}, "
              f"{cand['zone_col']}={cand['zone_col'] in df.columns}")
        return
    near = df[cand["level_col"]].abs() <= cand["near_pct"]
    zones = df[cand["zone_col"]] >= cand["zone_min"]
    df["_sig"] = (near & zones).fillna(False).astype(int)

    # Forward return signed
    sign = +1 if cand["direction"] == "LONG" else -1
    df["_fwd5"] = sign * (df["close"].shift(-5) - df["close"]) / TICK_SIZE
    df["_pnl_net"] = df["_fwd5"] - SLIPPAGE_TICKS_ROUND_TRIP

    fires = df[df["_sig"] == 1].dropna(subset=["_fwd5"]).copy()
    if fires.empty:
        print("  0 fires")
        return

    fires["month"] = fires["ts_event"].dt.to_period("M").astype(str)

    # Decompose par mois
    print(f"\n  --- Distribution par mois ---")
    by_month = fires.groupby("month").agg(
        n_fires=("_pnl_net", "size"),
        wr=("_fwd5", lambda x: (x > 0).mean()),
        mean_ticks_net=("_pnl_net", "mean"),
        median_ticks_net=("_pnl_net", "median"),
        std_ticks=("_pnl_net", "std"),
    ).reset_index()
    by_month["sharpe"] = by_month["mean_ticks_net"] / by_month["std_ticks"].replace(0, np.nan)
    by_month["share_total"] = by_month["n_fires"] / by_month["n_fires"].sum()
    by_month = by_month.round({"wr": 3, "mean_ticks_net": 2, "median_ticks_net": 2,
                                "std_ticks": 2, "sharpe": 3, "share_total": 3})
    print(by_month.to_string(index=False))

    n_months = len(by_month)
    top2_share = float(by_month.nlargest(2, "n_fires")["share_total"].sum())
    print(f"\n  Mois actifs: {n_months} / Top 2 mois share: {top2_share*100:.1f}%")

    # Verdict regime
    consistent_months = (by_month["mean_ticks_net"] > 0).sum()
    print(f"  Mois positifs (mean_net>0): {consistent_months}/{n_months}")
    if consistent_months / n_months >= 0.75 and top2_share <= 0.50:
        verdict = "EDGE_STRUCTUREL_PROBABLE"
    elif consistent_months / n_months >= 0.50 and top2_share <= 0.60:
        verdict = "EDGE_STRUCTUREL_FRAGILE"
    elif top2_share > 0.60:
        verdict = "ACCIDENT_REGIME (concentration excessive)"
    else:
        verdict = "INDETERMINE"
    print(f"  >>> VERDICT REGIME : {verdict}")

    # Distribution par jour de la semaine (controle additionnel)
    fires["day_of_week"] = fires["ts_event"].dt.day_name()
    print(f"\n  --- Distribution par jour ---")
    by_dow = fires.groupby("day_of_week").agg(
        n_fires=("_pnl_net", "size"),
        wr=("_fwd5", lambda x: (x > 0).mean()),
        mean_net=("_pnl_net", "mean"),
    ).round({"wr": 3, "mean_net": 2})
    print(by_dow.to_string())

    # Distribution heure UTC (effet session intra-RTH)
    fires["hour_utc"] = fires["ts_event"].dt.hour
    print(f"\n  --- Distribution par heure UTC ---")
    by_hour = fires.groupby("hour_utc").agg(
        n_fires=("_pnl_net", "size"),
        wr=("_fwd5", lambda x: (x > 0).mean()),
        mean_net=("_pnl_net", "mean"),
    ).round({"wr": 3, "mean_net": 2})
    print(by_hour.to_string())

    return verdict


def main():
    verdicts = {}
    for cand in CANDIDATES:
        v = decompose_candidate(cand)
        verdicts[cand["id"]] = v

    print(f"\n{'=' * 80}")
    print(f"  SYNTHESE")
    print(f"{'=' * 80}")
    for cid, v in verdicts.items():
        cand = next(c for c in CANDIDATES if c["id"] == cid)
        print(f"  Candidat {cid} ({cand['symbol']} {cand['direction']} {cand['name']}): {v}")


if __name__ == "__main__":
    main()
