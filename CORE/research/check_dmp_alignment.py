"""Test alignement DMP/Databento avec hypotheses sur ts."""
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
    # RTH UTC 13:30-20:00
    def rth(df):
        t = df["ts"]
        return df[((t.dt.hour>13)|((t.dt.hour==13)&(t.dt.minute>=30))) & (t.dt.hour<20)]

    dmp_rth = rth(dmp).copy()
    db_rth = rth(db).copy()
    print(f"DMP RTH        : {len(dmp_rth)}")
    print(f"Databento RTH  : {len(db_rth)}")

    # H1 : DMP :00 = bar STARTING at that minute (Databento convention)
    dmp_h1 = dmp_rth[dmp_rth["ts"].dt.second == 0].copy()
    dmp_h1["ts_min"] = dmp_h1["ts"].dt.floor("min")
    print(f"\nH1 (s=0, ts=start of bar) : {len(dmp_h1)} bars DMP")
    m = dmp_h1.merge(db_rth.assign(ts_min=db_rth["ts"]), on="ts_min", how="inner", suffixes=("_dmp","_db"))
    if len(m):
        d = (m["close_dmp"] - m["close_db"]).abs()
        print(f"  matched={len(m)} | close diff mean={d.mean():.4f} max={d.max():.4f}")

    # H2 : DMP :00 = bar ENDING at that minute (close ts = end)
    dmp_h2 = dmp_rth[dmp_rth["ts"].dt.second == 0].copy()
    # ts_min = ts - 1 minute (start of bar)
    dmp_h2["ts_min"] = (dmp_h2["ts"] - pd.Timedelta(minutes=1)).dt.floor("min")
    print(f"\nH2 (s=0, ts=end of bar -> start = ts-1min) : {len(dmp_h2)} bars DMP")
    m = dmp_h2.merge(db_rth.assign(ts_min=db_rth["ts"]), on="ts_min", how="inner", suffixes=("_dmp","_db"))
    if len(m):
        d = (m["close_dmp"] - m["close_db"]).abs()
        print(f"  matched={len(m)} | close diff mean={d.mean():.4f} max={d.max():.4f}")

    # H3 : :59 = mid-bar snapshot (writing 1 sec before ts:00 next), keep only :00 = close of previous minute
    dmp_h3 = dmp_rth[dmp_rth["ts"].dt.second == 0].copy()
    dmp_h3["ts_min"] = dmp_h3["ts"].dt.floor("min")
    print(f"\nH3 (s=0 only, ts=start, same as H1) : {len(dmp_h3)} bars DMP")

    # H4 : keep :59 (treat as bar that just closed at next minute)
    dmp_h4 = dmp_rth[dmp_rth["ts"].dt.second == 59].copy()
    dmp_h4["ts_min"] = (dmp_h4["ts"] + pd.Timedelta(seconds=1)).dt.floor("min")
    # Cette ts_min represente la minute apres laquelle la bar :59 ferme. Si bar = minute precedente:
    dmp_h4["ts_min_start"] = dmp_h4["ts_min"] - pd.Timedelta(minutes=1)
    print(f"\nH4 (s=59 only, treated as close of previous minute) : {len(dmp_h4)}")
    m = dmp_h4.merge(db_rth.assign(ts_min=db_rth["ts"]), left_on="ts_min_start", right_on="ts_min", how="inner", suffixes=("_dmp","_db"))
    if len(m):
        d = (m["close_dmp"] - m["close_db"]).abs()
        print(f"  matched={len(m)} | close diff mean={d.mean():.4f} max={d.max():.4f}")

    # H5 : keep :00 only and shift so ts_min = ts - 1 min (close timestamp)
    print(f"\nH5 (s=0, ts=close timestamp -> start = ts-1min) : meme que H2")

    # Showcase : pour les minutes avec 2 bars (s=0 et s=59), comparer les valeurs
    print("\n--- Echantillon doublons :59 vs :00 suivant ---")
    dmp_rth_sorted = dmp_rth.sort_values("ts").reset_index(drop=True)
    for i in range(min(5, len(dmp_rth_sorted)-1)):
        a = dmp_rth_sorted.iloc[i]
        b = dmp_rth_sorted.iloc[i+1]
        if a["ts"].second == 59 and b["ts"].second == 0:
            print(f"  {a['ts']} close={a['close']} | {b['ts']} close={b['close']} (diff={b['close']-a['close']})")
