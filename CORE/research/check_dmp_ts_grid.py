"""Diagnostic alignement timestamp DMP vs Databento."""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_dmp_ts(symbol):
    p = ROOT / "DATA" / symbol / f"20260427_{symbol}.jsonl"
    ts = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            ts.append(o["ts"])
    s = pd.to_datetime(pd.Series(ts), unit="ms", utc=True)
    return s


for sym in ("ES", "NQ"):
    print(f"\n=== {sym} ===")
    s = load_dmp_ts(sym)
    print(f"Total ts DMP     : {len(s)}")
    print(f"Unique ts DMP    : {s.nunique()}")
    # Modulo 60s : combien sont sur la grid minute exacte ?
    sec = s.dt.second + s.dt.microsecond / 1e6
    print(f"On-the-minute (s=0) : {(sec == 0).sum()}")
    print(f"Off-grid            : {(sec != 0).sum()}")
    # Distribution des secondes
    print("Secondes distribution (top 10):")
    print(s.dt.second.value_counts().head(10).to_string())
    # Ex : premieres ts
    print("\nFirst 5 ts:")
    for x in s.head(5):
        print(" ", x)
    print("RTH bars (13:30-20:00 UTC):")
    rth = s[(s.dt.hour > 13) | ((s.dt.hour == 13) & (s.dt.minute >= 30))]
    rth = rth[rth.dt.hour < 20]
    print(f"  Total RTH ts        : {len(rth)}")
    print(f"  Unique floor minute : {rth.dt.floor('min').nunique()}")
    # Bars par minute (max collisions)
    counts = rth.dt.floor("min").value_counts()
    print(f"  Bars/min max        : {counts.max()}")
    print(f"  Bars/min mean       : {counts.mean():.2f}")
    print(f"  Minutes avec > 1 bar : {(counts > 1).sum()}")
