"""Identifier les 121 minutes Databento absentes du DMP."""
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

for sym in ("ES",):
    dmp = load_dmp(sym)
    db = load_db(sym)
    def rth(df):
        t = df["ts"]
        return df[((t.dt.hour>13)|((t.dt.hour==13)&(t.dt.minute>=30))) & (t.dt.hour<20)].copy()
    dmp_rth = rth(dmp)
    db_rth = rth(db)
    s00 = set(dmp_rth[dmp_rth["ts"].dt.second==0]["ts"].dt.floor("min"))
    db_min = set(db_rth["ts"])
    missing = sorted(db_min - s00)
    print(f"=== {sym} : {len(missing)} bars Databento absentes du DMP (basees sur :00) ===")
    print("Premieres 10:", missing[:10])
    print("Dernieres 10:", missing[-10:])
    # Histogramme par heure
    import collections
    hist = collections.Counter([m.hour for m in missing])
    print("Distribution par heure UTC:", dict(sorted(hist.items())))

    # Pour chaque manquante, est-ce qu'on a un :59 dans la minute precedente ?
    # (e.g. minute 13:32 manquante => :59 a 13:31 ?)
    s59_set = set((dmp_rth[dmp_rth["ts"].dt.second==59]["ts"] + pd.Timedelta(seconds=1)).dt.floor("min"))
    via_59 = [m for m in missing if m in s59_set]
    print(f"\n  Manquantes recuperables via :59 (next minute) = {len(via_59)}")

    # En fait, si :59 a 13:31:59 represente la bar 13:31 (minute floor), c'est PAS la 13:32 manquante
    # Mais si :59 a 13:31:59 represente la fin de bar 13:31, alors le :00 a 13:32:00 serait
    # la BAR 13:32 (start). Hypothese alternative : DMP emit timestamp= BAR_END (close)
    # alors ts=13:31:59 = bar 13:30 (start 13:30, close 13:31) ???
    # On verifie avec valeurs

    # Get sample missing minute say 13:32 (manquant), comparer close DB(13:32) vs DMP :59 a 13:31:59 ?
    if missing:
        m0 = missing[0]
        # Find :59 closest
        prev_minute = m0 - pd.Timedelta(minutes=1)
        # ts=prev_minute + 59s
        cand = dmp_rth[(dmp_rth["ts"].dt.floor("min")==prev_minute) & (dmp_rth["ts"].dt.second==59)]
        db_row = db_rth[db_rth["ts"]==m0]
        print(f"\n  Minute manquante {m0} : DB close={db_row['close'].iloc[0] if len(db_row) else 'N/A'}")
        print(f"  DMP :59 a {prev_minute}:59 : {cand['close'].tolist() if len(cand) else 'aucun'}")
        # Comparer aussi avec next :00
        next_minute = m0 + pd.Timedelta(minutes=1)
        next_dmp = dmp_rth[(dmp_rth["ts"]==next_minute)]
        print(f"  DMP :00 a {next_minute} : {next_dmp['close'].tolist() if len(next_dmp) else 'aucun'}")
