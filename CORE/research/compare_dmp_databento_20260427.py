"""
Compare DMP (Sierra Chart) vs Databento ohlcv-1m pour le 27/04/2026.

Charge :
- DMP : DATA/{ES,NQ}/20260427_{ES,NQ}.jsonl (per-bar JSONL, ts en ms epoch UTC)
- Databento : DATA/databento/GLBX.MDP3/ohlcv-1m/symbol={ES,NQ}.c.0/year=2026/month=4/day=27/data.parquet

Aligne sur RTH ET 09:30-16:00 (= UTC 13:30-20:00) puis compare close/high/low/volume.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_dmp(symbol: str) -> pd.DataFrame:
    p = ROOT / "DATA" / symbol / f"20260427_{symbol}.jsonl"
    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append({
                "ts_ms": o.get("ts"),
                "close": o.get("price"),
                "high": o.get("bar_high"),
                "low": o.get("bar_low"),
                "volume": o.get("total_vol"),
                "session_id": o.get("session_id"),
            })
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    # DMP timestamps souvent au start of bar. Floor sur la minute pour join propre.
    df["ts_min"] = df["ts"].dt.floor("min")
    df = df.dropna(subset=["close"]).copy()
    return df


def load_databento(symbol: str) -> pd.DataFrame:
    p = (
        ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"
        / f"symbol={symbol}.c.0" / "year=2026" / "month=4" / "day=27" / "data.parquet"
    )
    df = pd.read_parquet(p)
    # Index = ts_event (start of bar) ; UTC tz-aware
    df = df.reset_index()
    # Detecter colonne ts (databento : 'ts_event')
    ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    df["ts_min"] = df["ts"].dt.floor("min")
    return df[["ts_min", "open", "high", "low", "close", "volume"]].copy()


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """RTH 09:30-16:00 ET = 13:30-20:00 UTC (DST avril => ET = UTC-4)."""
    t = df["ts_min"]
    mask = (
        (t.dt.hour > 13) | ((t.dt.hour == 13) & (t.dt.minute >= 30))
    ) & (
        (t.dt.hour < 20) | ((t.dt.hour == 20) & (t.dt.minute == 0))
    )
    # Note: Databento publie le bar de 16:00 ET (20:00 UTC) ? On exclut strict <20:00
    mask = (
        (t.dt.hour > 13) | ((t.dt.hour == 13) & (t.dt.minute >= 30))
    ) & (
        t.dt.hour < 20
    )
    return df[mask].copy()


def compare_symbol(symbol: str) -> dict:
    print(f"\n{'='*70}\n {symbol}\n{'='*70}")
    dmp = load_dmp(symbol)
    db = load_databento(symbol)
    print(f"  DMP total bars       : {len(dmp)}")
    print(f"  Databento total bars : {len(db)}")

    dmp_rth = filter_rth(dmp)
    db_rth = filter_rth(db)
    print(f"  DMP RTH bars         : {len(dmp_rth)}")
    print(f"  Databento RTH bars   : {len(db_rth)}")

    # Dedup DMP par ts_min (au cas ou plusieurs bars dans la meme minute)
    dmp_rth = dmp_rth.groupby("ts_min", as_index=False).agg(
        close=("close", "last"),
        high=("high", "max"),
        low=("low", "min"),
        volume=("volume", "sum"),
    )

    merged = dmp_rth.merge(
        db_rth, on="ts_min", how="outer", suffixes=("_dmp", "_db"), indicator=True
    )
    only_dmp = (merged["_merge"] == "left_only").sum()
    only_db = (merged["_merge"] == "right_only").sum()
    both = (merged["_merge"] == "both").sum()
    print(f"  Bars matched         : {both}")
    print(f"  Only DMP (Databento manquant) : {only_dmp}")
    print(f"  Only Databento (DMP manquant) : {only_db}")

    m = merged[merged["_merge"] == "both"].copy()
    if m.empty:
        print("  AUCUN MATCH — abort")
        return {"symbol": symbol, "matched": 0}

    # Diffs absolus
    for col in ("close", "high", "low"):
        m[f"diff_{col}"] = (m[f"{col}_dmp"] - m[f"{col}_db"]).abs()
    m["diff_volume"] = (m["volume_dmp"] - m["volume_db"]).abs()
    m["diff_close_pct"] = m["diff_close"] / m["close_db"] * 100.0

    res = {
        "symbol": symbol,
        "matched": both,
        "only_dmp": int(only_dmp),
        "only_db": int(only_db),
        "close_mean_diff": float(m["diff_close"].mean()),
        "close_median_diff": float(m["diff_close"].median()),
        "close_max_diff": float(m["diff_close"].max()),
        "close_max_pct": float(m["diff_close_pct"].max()),
        "high_mean_diff": float(m["diff_high"].mean()),
        "high_max_diff": float(m["diff_high"].max()),
        "low_mean_diff": float(m["diff_low"].mean()),
        "low_max_diff": float(m["diff_low"].max()),
        "vol_mean_diff": float(m["diff_volume"].mean()),
        "vol_median_diff": float(m["diff_volume"].median()),
        "vol_dmp_total": float(m["volume_dmp"].sum()),
        "vol_db_total": float(m["volume_db"].sum()),
    }

    # Top 5 divergences close
    print("\n  Top 5 divergences CLOSE (abs) :")
    top = m.nlargest(5, "diff_close")[
        ["ts_min", "close_dmp", "close_db", "diff_close", "diff_close_pct"]
    ]
    print(top.to_string(index=False))

    # Top 5 divergences volume
    print("\n  Top 5 divergences VOLUME (abs) :")
    topv = m.nlargest(5, "diff_volume")[
        ["ts_min", "volume_dmp", "volume_db", "diff_volume"]
    ]
    print(topv.to_string(index=False))

    # Distribution diffs close
    print(f"\n  CLOSE diff stats : mean={res['close_mean_diff']:.4f} | "
          f"median={res['close_median_diff']:.4f} | max={res['close_max_diff']:.4f} "
          f"({res['close_max_pct']:.4f}%)")
    print(f"  HIGH  diff stats : mean={res['high_mean_diff']:.4f} | "
          f"max={res['high_max_diff']:.4f}")
    print(f"  LOW   diff stats : mean={res['low_mean_diff']:.4f} | "
          f"max={res['low_max_diff']:.4f}")
    print(f"  VOL   diff stats : mean={res['vol_mean_diff']:.1f} | "
          f"median={res['vol_median_diff']:.1f}")
    print(f"  VOL totaux       : DMP={res['vol_dmp_total']:.0f} | DB={res['vol_db_total']:.0f} "
          f"(ratio DMP/DB = {res['vol_dmp_total']/max(res['vol_db_total'],1):.4f})")

    # Verdict
    pct = res["close_max_pct"]
    if pct < 0.01:
        verdict = "OK (sources coherentes)"
    elif pct < 1.0:
        verdict = "WARNING (a investiguer)"
    else:
        verdict = "BUG MAJEUR (DMP probablement casse)"
    res["verdict"] = verdict
    print(f"\n  VERDICT : {verdict} (max pct close = {pct:.4f}%)")
    return res


def main():
    results = []
    for sym in ("ES", "NQ"):
        results.append(compare_symbol(sym))

    print("\n" + "=" * 70)
    print(" SYNTHESE COMPARATIVE")
    print("=" * 70)
    cols = ["symbol", "matched", "only_dmp", "only_db",
            "close_mean_diff", "close_max_diff", "close_max_pct",
            "high_max_diff", "low_max_diff",
            "vol_mean_diff", "verdict"]
    df = pd.DataFrame(results)[cols]
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
