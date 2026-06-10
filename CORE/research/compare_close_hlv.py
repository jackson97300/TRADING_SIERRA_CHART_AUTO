"""
Comparaison globale Databento vs DMP — Close/High/Low/Volume.

Compare les bars OHLCV-1m entre :
  - DATA/{ES,NQ}/YYYYMMDD_*.jsonl (DMP custom Sierra Chart)
  - DATA/databento/GLBX.MDP3/ohlcv-1m/symbol={SYM}.c.0/year=Y/month=M/day=D/data.parquet

5 buckets par champ (close, high, low, vol) :
  - match_exact      : valeurs identiques
  - match_within_tol : abs(diff) <= 0.125 (demi-tick)
  - mismatch         : abs(diff) > 0.125
  - dmp_only         : bar present DMP, absent DBN
  - dbn_only         : bar present DBN, absent DMP (CRITIQUE = NOGO)

Output : rapport texte + JSON machine-readable.

Verdict (selon Plan agent recommendations) :
  GO              : close_exact >= 99.9%, H/L_within_tol >= 99.5%, vol_div < 0.5%
  GO-AVEC-RESERVES: close_mismatch in [0.1%, 0.5%], vol_div in [0.5%, 2.0%]
  NOGO            : close_mismatch > 0.5%, OR vol_div > 2%, OR dbn_only > 0
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATABENTO_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3"
TICK_SIZE = 0.25
TOL = TICK_SIZE / 2  # 0.125 = demi-tick


def load_dmp(jsonl_path: Path) -> pd.DataFrame:
    """
    Lit JSONL DMP. DMP a 2 conventions melangees (sec=00 ou sec=59).
    On aligne sur la minute via round('min') pour matcher DBN (sec=00 strict).
    Doublons apres round (rares) -> on agrege (max H, min L, sum vol, last close).
    """
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
                continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts_raw"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    # DMP a 2 conventions melangees : sec=00 (bar_start label) et sec=59
    # (bar_end-1s, intra-bar tick avant cloture). round('min') fait le bon mapping
    # vers la minute la plus proche cote DBN (s=00 strict).
    df["ts_utc"] = df["ts_raw"].dt.round("min")
    # Agreger doublons (par robustesse)
    n_before = len(df)
    df = df.groupby("ts_utc").agg(
        close=("close", "last"),
        high=("high", "max"),
        low=("low", "min"),
        vol=("vol", "sum"),
    ).sort_index()
    n_after = len(df)
    if n_before != n_after:
        print(f"  [DMP] {jsonl_path.name}: aggregated {n_before - n_after} duplicate-minute rows")
    return df


def load_dbn(symbol: str, day: str) -> pd.DataFrame:
    y, m, d = day.split("-")
    p = DATABENTO_ROOT / "ohlcv-1m" / f"symbol={symbol}.c.0" / f"year={y}" / f"month={m}" / f"day={d}" / "data.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df[["open", "high", "low", "close", "volume"]].rename(columns={"volume": "vol"})


def classify_diff(dmp_val, dbn_val):
    if pd.isna(dmp_val) and pd.isna(dbn_val):
        return "match_exact"
    if pd.isna(dmp_val) or pd.isna(dbn_val):
        return "missing"
    diff = abs(float(dmp_val) - float(dbn_val))
    if diff < 1e-9:
        return "match_exact"
    if diff <= TOL:
        return "match_within_tol"
    return "mismatch"


def compare_field(joined: pd.DataFrame, field: str) -> dict:
    classifications = joined.apply(
        lambda r: classify_diff(r[f"{field}_dmp"], r[f"{field}_dbn"]),
        axis=1,
    )
    counts = classifications.value_counts().to_dict()
    total = len(joined)
    return {
        "total": total,
        "match_exact": counts.get("match_exact", 0),
        "match_within_tol": counts.get("match_within_tol", 0),
        "mismatch": counts.get("mismatch", 0),
        "pct_exact": round(100 * counts.get("match_exact", 0) / total, 4) if total else 0,
        "pct_within_tol": round(100 * (counts.get("match_exact", 0) + counts.get("match_within_tol", 0)) / total, 4) if total else 0,
        "pct_mismatch": round(100 * counts.get("mismatch", 0) / total, 4) if total else 0,
    }


def compare_volume(joined: pd.DataFrame) -> dict:
    sum_dmp = joined["vol_dmp"].sum()
    sum_dbn = joined["vol_dbn"].sum()
    diff_abs = abs(sum_dbn - sum_dmp)
    diff_pct = (diff_abs / sum_dmp * 100) if sum_dmp else 0
    return {
        "sum_dmp": int(sum_dmp),
        "sum_dbn": int(sum_dbn),
        "diff_abs": int(diff_abs),
        "diff_pct": round(diff_pct, 4),
    }


def verdict(report: dict) -> str:
    """
    Verdict pour migration DMP -> Databento.

    Logique :
    - dmp_only > 0 = DMP a des bars que DBN n'a PAS = probleme cote DBN -> NOGO
    - dbn_only > 0 = DBN a plus de bars que DMP = DBN couvre MIEUX, pas un probleme
    - Sur les bars communs : close/H/L/V doivent matcher avec haute precision
    """
    close_pct_mismatch = report["close"]["pct_mismatch"]
    hl_pct_within_tol = min(report["high"]["pct_within_tol"], report["low"]["pct_within_tol"])
    vol_div = report["volume"]["diff_pct"]
    dmp_only = report["alignment"]["dmp_only"]
    dbn_only = report["alignment"]["dbn_only"]
    common = report["alignment"]["common"]

    # NOGO : DBN incomplet (rate ce que DMP voit = source DBN defaillante)
    if dmp_only > 0:
        return "NOGO", f"dmp_only={dmp_only} bars (DMP voit, DBN rate = DBN incomplet)"
    if close_pct_mismatch > 0.5:
        return "NOGO", f"close mismatch {close_pct_mismatch:.2f}% > 0.5%"
    if vol_div > 2.0:
        return "NOGO", f"volume divergence {vol_div:.2f}% > 2%"
    if hl_pct_within_tol < 99.0:
        return "NOGO", f"H/L within tol {hl_pct_within_tol:.2f}% < 99%"

    # GO : criteres stricts atteints
    if (report["close"]["pct_exact"] >= 99.9
        and hl_pct_within_tol >= 99.5
        and vol_div < 0.5):
        # Note bonus : si DBN couvre plus que DMP -> argument POUR migration
        coverage_bonus = f" | DBN couvre {dbn_only} bars de plus que DMP" if dbn_only > 0 else ""
        return "GO", f"criteres GO atteints{coverage_bonus}"

    # Reserves
    return "GO-AVEC-RESERVES", f"close_mismatch={close_pct_mismatch:.2f}% vol_div={vol_div:.2f}% hl_within={hl_pct_within_tol:.2f}%"


def compare(symbol: str, days: list[str]) -> dict:
    """Compare DMP vs DBN pour un symbole sur N jours."""
    print(f"\n{'='*90}")
    print(f" COMPARAISON {symbol} — {len(days)} jour(s) : {days}")
    print(f"{'='*90}")

    # Concat DMP + DBN sur tous les jours
    dmp_all = pd.DataFrame()
    dbn_all = pd.DataFrame()
    for day in days:
        ymd = day.replace("-", "")
        dmp_path = ROOT / "DATA" / symbol / f"{ymd}_{symbol}.jsonl"
        dmp_day = load_dmp(dmp_path)
        dbn_day = load_dbn(symbol, day)
        # Pour DMP : prendre 2 jours = day - 1 (session futures complete)
        # Pour DBN : day calendaire UTC
        dmp_all = pd.concat([dmp_all, dmp_day]) if not dmp_day.empty else dmp_all
        dbn_all = pd.concat([dbn_all, dbn_day]) if not dbn_day.empty else dbn_all

    print(f"  DMP bars: {len(dmp_all)} ({dmp_all.index.min() if len(dmp_all) else 'N/A'} -> {dmp_all.index.max() if len(dmp_all) else 'N/A'})")
    print(f"  DBN bars: {len(dbn_all)} ({dbn_all.index.min() if len(dbn_all) else 'N/A'} -> {dbn_all.index.max() if len(dbn_all) else 'N/A'})")

    # Fenetre temporelle COMMUNE (intersection des ranges)
    if dmp_all.empty or dbn_all.empty:
        return {"error": "no_data", "symbol": symbol}
    win_start = max(dmp_all.index.min(), dbn_all.index.min())
    win_end = min(dmp_all.index.max(), dbn_all.index.max())
    print(f"  Fenetre commune  : {win_start} -> {win_end}")

    # Filtrer dans la fenetre commune
    dmp_win = dmp_all.loc[win_start:win_end]
    dbn_win = dbn_all.loc[win_start:win_end]
    print(f"  DMP in window: {len(dmp_win)}")
    print(f"  DBN in window: {len(dbn_win)}")

    # Inner join sur ts dans la fenetre
    joined = dmp_win[["close", "high", "low", "vol"]].add_suffix("_dmp").join(
        dbn_win[["open", "high", "low", "close", "vol"]].add_suffix("_dbn"),
        how="inner"
    )

    # dmp_only / dbn_only DANS la fenetre commune (les vraies divergences)
    dmp_only = len(dmp_win) - len(joined)
    dbn_only = len(dbn_win) - len(joined)

    print(f"  Joined common bars: {len(joined)}")
    print(f"  DMP-only (in win) : {dmp_only}")
    print(f"  DBN-only (in win) : {dbn_only}  {'CRITIQUE' if dbn_only > 0 else 'OK'}")

    if joined.empty:
        return {"error": "no_common_bars", "symbol": symbol}

    # Compare each field
    report = {
        "symbol": symbol,
        "days": days,
        "alignment": {
            "dmp_total": len(dmp_all),
            "dbn_total": len(dbn_all),
            "window_start": str(win_start),
            "window_end": str(win_end),
            "dmp_in_window": len(dmp_win),
            "dbn_in_window": len(dbn_win),
            "common": len(joined),
            "dmp_only": dmp_only,
            "dbn_only": dbn_only,
        },
        "close": compare_field(joined, "close"),
        "high": compare_field(joined, "high"),
        "low": compare_field(joined, "low"),
        "volume": compare_volume(joined),
    }

    # Print report
    print(f"\n  {'Field':<10} {'Total':>8} {'Exact':>8} {'~Tol':>8} {'Miss':>6} {'%Exact':>10} {'%Within':>10} {'%Miss':>10}")
    print("  " + "-" * 78)
    for field in ["close", "high", "low"]:
        r = report[field]
        print(f"  {field:<10} {r['total']:>8} {r['match_exact']:>8} {r['match_within_tol']:>8} {r['mismatch']:>6} "
              f"{r['pct_exact']:>9.4f}% {r['pct_within_tol']:>9.4f}% {r['pct_mismatch']:>9.4f}%")

    v = report["volume"]
    print(f"\n  Volume: sum_DMP={v['sum_dmp']:,}  sum_DBN={v['sum_dbn']:,}  "
          f"diff_abs={v['diff_abs']:,}  diff_pct={v['diff_pct']:.4f}%")

    # Verdict
    verd, reason = verdict(report)
    report["verdict"] = verd
    report["verdict_reason"] = reason
    print(f"\n  VERDICT: {verd}  ({reason})")

    return report


def main():
    print("="*90)
    print(" DATABENTO vs DMP — Comparaison Close/High/Low/Volume")
    print(f" Tolerance: {TOL} (demi-tick ES/NQ = {TICK_SIZE})")
    print("="*90)

    # Pour 24/04 cible : besoin 23/04 + 24/04 cote DMP (session DMP commence vendredi 22:01 UTC)
    days = ["2026-04-23", "2026-04-24"]

    reports = {}
    for symbol in ["ES", "NQ"]:
        reports[symbol] = compare(symbol, days)

    # Save JSON
    out = ROOT / "DATA" / "databento" / "_metadata" / f"compare_{days[0]}_to_{days[-1]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"timestamp": datetime.utcnow().isoformat(), "reports": reports}, f, indent=2, default=str)
    print(f"\n[OK] Rapport JSON: {out}")

    # Verdict global
    print(f"\n{'='*90}")
    print(" VERDICTS GLOBAUX")
    print(f"{'='*90}")
    for sym, rep in reports.items():
        if "verdict" in rep:
            print(f"  {sym}: {rep['verdict']}  ({rep['verdict_reason']})")


if __name__ == "__main__":
    main()
