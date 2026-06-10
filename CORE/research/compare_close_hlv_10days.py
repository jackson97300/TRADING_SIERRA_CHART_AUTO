"""
Comparaison DMP vs Databento sur 10 jours.
Aggregation des stats + analyse par regime (Asia/London/RTH).
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DBN_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3"
TICK = 0.25
TOL = TICK / 2

# 10 jours ciblés
DATES = [
    "2026-03-31",  # lundi
    "2026-04-03",  # vendredi (potentiel NFP)
    "2026-04-08",  # mercredi
    "2026-04-10",  # vendredi
    "2026-04-13",  # lundi (Sunday open)
    "2026-04-15",  # mercredi
    "2026-04-17",  # vendredi (OPEX)
    "2026-04-20",  # lundi
    "2026-04-23",  # jeudi
    "2026-04-24",  # vendredi
]


def load_dmp(jsonl_path):
    if not jsonl_path.exists():
        return pd.DataFrame()
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                rows.append({
                    "ts_ms": d.get("ts"),
                    "close": d.get("price"),
                    "high": d.get("bar_high"),
                    "low": d.get("bar_low"),
                    "vol": d.get("total_vol"),
                })
            except Exception:
                pass
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts_raw"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["ts_utc"] = df["ts_raw"].dt.round("min")
    df = df.groupby("ts_utc").agg(
        close=("close", "last"),
        high=("high", "max"),
        low=("low", "min"),
        vol=("vol", "sum"),
    ).sort_index()
    return df


def load_dbn(symbol, day):
    y, m, d = day.split("-")
    p = DBN_ROOT / "ohlcv-1m" / f"symbol={symbol}.c.0" / f"year={y}" / f"month={m}" / f"day={d}" / "data.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def regime_of(ts):
    """Asia | London | RTH | post-RTH (UTC)"""
    h = ts.hour
    if 0 <= h < 7:
        return "Asia"
    if 7 <= h < 13:
        return "London"
    if 13 <= h < 21:
        return "RTH"
    return "Post-RTH"


def compare_day(symbol, target_day):
    """Compare 1 jour : charge DMP de target_day + DBN de target_day et J-1."""
    ymd = target_day.replace("-", "")
    dmp_day = load_dmp(ROOT / "DATA" / symbol / f"{ymd}_{symbol}.jsonl")
    if dmp_day.empty:
        return None

    # DBN : target_day + J-1 (pour couvrir la session DMP complete)
    prev = (datetime.strptime(target_day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    dbn_target = load_dbn(symbol, target_day)
    dbn_prev = load_dbn(symbol, prev)
    dbn_all = pd.concat([dbn_prev, dbn_target]).sort_index() if not dbn_prev.empty else dbn_target

    if dbn_all.empty:
        return None

    # Fenetre commune
    ws = max(dmp_day.index.min(), dbn_all.index.min())
    we = min(dmp_day.index.max(), dbn_all.index.max())
    dmp_w = dmp_day.loc[ws:we]
    dbn_w = dbn_all.loc[ws:we]

    joined = dmp_w[["close", "high", "low", "vol"]].add_suffix("_dmp").join(
        dbn_w[["high", "low", "close", "volume"]].add_suffix("_dbn"),
        how="inner",
    )

    if joined.empty:
        return None

    joined["regime"] = [regime_of(ts) for ts in joined.index]

    # Mismatches
    joined["close_diff"] = (joined["close_dmp"] - joined["close_dbn"]).abs()
    close_match_exact = (joined["close_diff"] < 1e-9).sum()
    close_match_tol = (joined["close_diff"] <= TOL).sum()
    close_mismatch = (joined["close_diff"] > TOL).sum()
    close_max_diff = joined["close_diff"].max()
    close_max_diff_ts = joined["close_diff"].idxmax() if close_mismatch > 0 else None

    high_match = (joined["high_dmp"] - joined["high_dbn"]).abs() < 1e-9
    low_match = (joined["low_dmp"] - joined["low_dbn"]).abs() < 1e-9

    sum_dmp = int(joined["vol_dmp"].sum())
    sum_dbn = int(joined["volume_dbn"].sum())
    vol_diff_pct = abs(sum_dbn - sum_dmp) / sum_dmp * 100 if sum_dmp else 0

    # Par regime
    by_reg = {}
    for reg, group in joined.groupby("regime"):
        n = len(group)
        m = (group["close_diff"] > TOL).sum()
        by_reg[reg] = {"n": n, "mismatch": int(m), "pct": round(100 * m / n, 4) if n else 0}

    return {
        "symbol": symbol,
        "day": target_day,
        "common_bars": len(joined),
        "dmp_only": len(dmp_w) - len(joined),
        "dbn_only": len(dbn_w) - len(joined),
        "close_exact_pct": round(100 * close_match_exact / len(joined), 4),
        "close_within_tol_pct": round(100 * close_match_tol / len(joined), 4),
        "close_mismatch_n": int(close_mismatch),
        "close_mismatch_pct": round(100 * close_mismatch / len(joined), 4),
        "close_max_diff": float(close_max_diff),
        "close_max_diff_ts": str(close_max_diff_ts) if close_max_diff_ts is not None else None,
        "high_exact_pct": round(100 * high_match.sum() / len(joined), 4),
        "low_exact_pct": round(100 * low_match.sum() / len(joined), 4),
        "vol_sum_dmp": sum_dmp,
        "vol_sum_dbn": sum_dbn,
        "vol_diff_pct": round(vol_diff_pct, 4),
        "by_regime": by_reg,
    }


def main():
    print("=" * 110)
    print(" COMPARAISON DATABENTO vs DMP — 10 jours")
    print("=" * 110)

    all_reports = {"ES": [], "NQ": []}
    for symbol in ["ES", "NQ"]:
        print(f"\n{'='*110}\n {symbol}\n{'='*110}")
        print(f"  {'Date':<12} {'Common':>7} {'DBN-only':>9} {'CloseExact':>10} {'CloseMiss':>10} {'MaxDiff':>9} {'High%':>8} {'Low%':>8} {'VolDiff%':>10}")
        print("  " + "-" * 100)
        for day in DATES:
            r = compare_day(symbol, day)
            if r is None:
                print(f"  {day:<12} [SKIP — fichier absent]")
                continue
            all_reports[symbol].append(r)
            print(f"  {r['day']:<12} {r['common_bars']:>7} {r['dbn_only']:>9} "
                  f"{r['close_exact_pct']:>9.4f}% {r['close_mismatch_n']:>4d} ({r['close_mismatch_pct']:>5.3f}%) "
                  f"{r['close_max_diff']:>8.2f} {r['high_exact_pct']:>7.3f}% {r['low_exact_pct']:>7.3f}% {r['vol_diff_pct']:>9.4f}%")

        # Aggregate
        if all_reports[symbol]:
            total_common = sum(r["common_bars"] for r in all_reports[symbol])
            total_mismatch = sum(r["close_mismatch_n"] for r in all_reports[symbol])
            total_dbn_only = sum(r["dbn_only"] for r in all_reports[symbol])
            global_pct = 100 * total_mismatch / total_common if total_common else 0
            print(f"  {'TOTAL':<12} {total_common:>7} {total_dbn_only:>9} "
                  f"{'(agg)':>10} {total_mismatch:>4d} ({global_pct:>5.3f}%)")

            # Aggregate par regime
            print(f"\n  Mismatch rate par regime ({symbol}):")
            reg_agg = {}
            for r in all_reports[symbol]:
                for reg, stats in r["by_regime"].items():
                    if reg not in reg_agg:
                        reg_agg[reg] = {"n": 0, "m": 0}
                    reg_agg[reg]["n"] += stats["n"]
                    reg_agg[reg]["m"] += stats["mismatch"]
            for reg, s in sorted(reg_agg.items()):
                pct = 100 * s["m"] / s["n"] if s["n"] else 0
                print(f"    {reg:<12} bars={s['n']:>5d}  mismatch={s['m']:>3d}  pct={pct:.4f}%")

    # Save JSON
    out = ROOT / "DATA" / "databento" / "_metadata" / "compare_10days.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"timestamp": datetime.utcnow().isoformat(), "reports": all_reports}, f, indent=2)
    print(f"\n[OK] Rapport JSON: {out}")


if __name__ == "__main__":
    main()
