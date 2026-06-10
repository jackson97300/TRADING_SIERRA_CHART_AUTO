"""Verifie hypothese finale : DMP emet 1 bar/min, ts soit a :00 (start) soit :59 (mid).

Les 121 :59 sont-ils des minutes UNIQUES (sans :00 jumeau) qui completent le 269 ?
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
    return df

def load_db(symbol):
    p = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m" / f"symbol={symbol}.c.0" / "year=2026" / "month=4" / "day=27" / "data.parquet"
    df = pd.read_parquet(p).reset_index()
    ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
    df["ts"] = pd.to_datetime(df[ts_col], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]

for sym in ("ES", "NQ"):
    print(f"\n{'='*70}\n {sym}\n{'='*70}")
    dmp = load_dmp(sym)
    db = load_db(sym)
    def rth(df):
        t = df["ts"]
        return df[((t.dt.hour>13)|((t.dt.hour==13)&(t.dt.minute>=30))) & (t.dt.hour<20)].copy()

    dmp_rth = rth(dmp)
    db_rth = rth(db)

    # Si :59 sur minute M et :00 sur minute M+1 => couple lie. Si :59 SEUL sur minute M
    # (pas de :00 a M+1), alors :59 est la SEULE bar pour cette minute.
    s00 = dmp_rth[dmp_rth["ts"].dt.second == 0].copy()
    s59 = dmp_rth[dmp_rth["ts"].dt.second == 59].copy()
    s00["minute"] = s00["ts"].dt.floor("min")
    # :59 represente bar de la minute floor (donc 14:00:59 = bar 14:00)
    s59["minute"] = s59["ts"].dt.floor("min")

    minutes_with_00 = set(s00["minute"])
    minutes_with_59 = set(s59["minute"])
    only_59 = minutes_with_59 - minutes_with_00
    both = minutes_with_59 & minutes_with_00
    only_00 = minutes_with_00 - minutes_with_59

    print(f"  Minutes avec :00 seul        : {len(only_00)}")
    print(f"  Minutes avec :59 seul        : {len(only_59)}")
    print(f"  Minutes avec :00 ET :59      : {len(both)}")
    print(f"  Total minutes uniques DMP    : {len(minutes_with_00 | minutes_with_59)}")
    print(f"  Total bars Databento RTH     : {len(db_rth)}")

    # Construire la grille DMP "best" : :00 si dispo, sinon :59
    best = []
    for m in sorted(minutes_with_00 | minutes_with_59):
        if m in minutes_with_00:
            row = s00[s00["minute"] == m].iloc[-1]
        else:
            row = s59[s59["minute"] == m].iloc[-1]
        best.append({"minute": m, "close_dmp": row["close"], "high_dmp": row["high"],
                     "low_dmp": row["low"], "vol_dmp": row["vol"]})
    best_df = pd.DataFrame(best)
    db_rth_aligned = db_rth.copy()
    db_rth_aligned["minute"] = db_rth_aligned["ts"]
    merged = best_df.merge(db_rth_aligned, on="minute", how="outer", indicator=True)
    matched = merged[merged["_merge"]=="both"].copy()
    print(f"\n  Bars matched (best DMP)      : {len(matched)}")
    print(f"  Only DMP                     : {(merged['_merge']=='left_only').sum()}")
    print(f"  Only Databento               : {(merged['_merge']=='right_only').sum()}")

    if len(matched):
        for col in ("close", "high", "low"):
            matched[f"diff_{col}"] = (matched[f"{col}_dmp"] - matched[col]).abs()
        matched["diff_vol"] = (matched["vol_dmp"] - matched["volume"]).abs()
        matched["diff_close_pct"] = matched["diff_close"] / matched["close"] * 100

        print(f"\n  CLOSE diff: mean={matched['diff_close'].mean():.4f} | "
              f"median={matched['diff_close'].median():.4f} | "
              f"max={matched['diff_close'].max():.4f} ({matched['diff_close_pct'].max():.4f}%)")
        print(f"  HIGH  diff: mean={matched['diff_high'].mean():.4f} | "
              f"max={matched['diff_high'].max():.4f}")
        print(f"  LOW   diff: mean={matched['diff_low'].mean():.4f} | "
              f"max={matched['diff_low'].max():.4f}")
        print(f"  VOL   diff: mean={matched['diff_vol'].mean():.1f} | "
              f"median={matched['diff_vol'].median():.1f}")
        print(f"  VOL totaux DMP={matched['vol_dmp'].sum():.0f} | "
              f"DB={matched['volume'].sum():.0f} | "
              f"ratio={matched['vol_dmp'].sum()/max(matched['volume'].sum(),1):.4f}")

        # Top 5 close
        print("\n  Top 5 close diff :")
        top = matched.nlargest(5, "diff_close")[["minute","close_dmp","close","diff_close","diff_close_pct"]]
        print(top.to_string(index=False))

        # Verdict
        pct = matched["diff_close_pct"].max()
        if pct < 0.01: v = "OK"
        elif pct < 1.0: v = "WARNING"
        else: v = "BUG MAJEUR"
        print(f"\n  VERDICT : {v} (max pct close = {pct:.4f}%)")
