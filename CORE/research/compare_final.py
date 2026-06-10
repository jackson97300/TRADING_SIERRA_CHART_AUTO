"""Comparaison FINALE DMP vs Databento avec alignement correct.

Convention DMP confirmee :
- ts:HH:MM:00 = bar de minute MM (start of bar at HH:MM)
- ts:HH:MM:59 = bar de minute MM+1 (timestamp = end of bar - 1s)

Donc pour aligner sur Databento (ts_event = start of bar) :
- garder les :00 tels quels
- shifter les :59 de +1 seconde puis floor minute => bar suivante
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_dmp(symbol):
    p = ROOT / "DATA" / symbol / f"20260427_{symbol}.jsonl"
    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            rows.append({"ts": o["ts"], "close": o.get("price"),
                         "high": o.get("bar_high"), "low": o.get("bar_low"),
                         "vol": o.get("total_vol")})
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    # Alignement bar-start
    sec = df["ts"].dt.second
    bar_start = df["ts"].copy()
    bar_start.loc[sec == 0] = df.loc[sec == 0, "ts"]
    bar_start.loc[sec == 59] = (df.loc[sec == 59, "ts"] + pd.Timedelta(seconds=1)).dt.floor("min")
    df["bar_start"] = bar_start.dt.floor("min")
    return df


def load_db(symbol):
    p = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m" / f"symbol={symbol}.c.0" / "year=2026" / "month=4" / "day=27" / "data.parquet"
    df = pd.read_parquet(p).reset_index()
    ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    df["bar_start"] = df["ts"]
    return df[["bar_start", "open", "high", "low", "close", "volume"]]


results = []
for sym in ("ES", "NQ"):
    print(f"\n{'='*70}\n {sym}\n{'='*70}")
    dmp = load_dmp(sym)
    db = load_db(sym)

    def rth(df, col="bar_start"):
        t = df[col]
        return df[((t.dt.hour > 13) | ((t.dt.hour == 13) & (t.dt.minute >= 30))) & (t.dt.hour < 20)].copy()

    dmp_rth = rth(dmp)
    db_rth = rth(db)
    print(f"  DMP RTH bars (apres alignement)  : {len(dmp_rth)}")
    print(f"  Databento RTH bars               : {len(db_rth)}")

    # Dedup defensive
    dmp_rth = dmp_rth.sort_values("ts").drop_duplicates("bar_start", keep="last")

    # Renommer cotes pour eviter ambiguite suffixes
    dmp_r = dmp_rth.rename(columns={"close": "close_dmp", "high": "high_dmp", "low": "low_dmp", "vol": "vol_dmp"})
    db_r = db_rth.rename(columns={"close": "close_db", "high": "high_db", "low": "low_db", "volume": "vol_db", "open": "open_db"})
    merged = dmp_r.merge(db_r, on="bar_start", how="outer", indicator=True)
    matched = (merged["_merge"] == "both").sum()
    only_dmp = (merged["_merge"] == "left_only").sum()
    only_db = (merged["_merge"] == "right_only").sum()
    print(f"  Bars matched      : {matched}")
    print(f"  Only DMP          : {only_dmp}")
    print(f"  Only Databento    : {only_db}")

    m = merged[merged["_merge"] == "both"].copy()
    for col in ("close", "high", "low"):
        m[f"diff_{col}"] = (m[f"{col}_dmp"] - m[f"{col}_db"]).abs()
    m["diff_close_pct"] = m["diff_close"] / m["close_db"] * 100
    m["diff_vol"] = (m["vol_dmp"] - m["vol_db"]).abs()

    print(f"\n  CLOSE diff : mean={m['diff_close'].mean():.4f} | "
          f"median={m['diff_close'].median():.4f} | "
          f"max={m['diff_close'].max():.4f} ({m['diff_close_pct'].max():.4f}%)")
    print(f"  HIGH  diff : mean={m['diff_high'].mean():.4f} | max={m['diff_high'].max():.4f}")
    print(f"  LOW   diff : mean={m['diff_low'].mean():.4f} | max={m['diff_low'].max():.4f}")
    print(f"  VOL   diff : mean={m['diff_vol'].mean():.1f} | median={m['diff_vol'].median():.1f}")
    print(f"  VOL totaux : DMP={m['vol_dmp'].sum():.0f} | DB={m['vol_db'].sum():.0f} | "
          f"ratio={m['vol_dmp'].sum()/max(m['vol_db'].sum(),1):.4f}")

    # Top 5 close
    print("\n  Top 5 divergences CLOSE :")
    top = m.nlargest(5, "diff_close")[["bar_start", "close_dmp", "close_db", "diff_close", "diff_close_pct"]]
    if not top.empty:
        print(top.to_string(index=False))
    print("\n  Top 5 divergences VOLUME :")
    topv = m.nlargest(5, "diff_vol")[["bar_start", "vol_dmp", "vol_db", "diff_vol"]]
    if not topv.empty:
        print(topv.to_string(index=False))

    pct = m["diff_close_pct"].max() if len(m) else 0
    if pct < 0.01: v = "OK"
    elif pct < 1.0: v = "WARNING"
    else: v = "BUG MAJEUR"
    print(f"\n  VERDICT close : {v} (max pct = {pct:.4f}%)")
    results.append({"symbol": sym, "matched": int(matched), "only_dmp": int(only_dmp),
                    "only_db": int(only_db), "close_max": float(m['diff_close'].max() if len(m) else 0),
                    "close_max_pct": float(pct),
                    "high_max": float(m['diff_high'].max() if len(m) else 0),
                    "low_max": float(m['diff_low'].max() if len(m) else 0),
                    "vol_dmp": float(m['vol_dmp'].sum()), "vol_db": float(m['vol_db'].sum()),
                    "verdict": v})

print("\n" + "="*70)
print(" SYNTHESE FINALE")
print("="*70)
print(pd.DataFrame(results).to_string(index=False))
