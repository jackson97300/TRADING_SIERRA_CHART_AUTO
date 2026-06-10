"""
Debug : pourquoi DMP-only=697 et DBN-only=1092 dans la fenetre commune ?
Hypotheses :
  H1 : DMP n'ecrit pas les bars sans volume
  H2 : DMP timestamps decales (sec/microsec)
  H3 : DMP filtre des periodes (pause maintenance ?)
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_dmp(jsonl_path):
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                rows.append({"ts_ms": d.get("ts"), "vol": d.get("total_vol")})
            except Exception:
                pass
    df = pd.DataFrame(rows)
    df["ts_utc"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df.set_index("ts_utc").sort_index()


def main():
    dmp_23 = load_dmp(ROOT / "DATA" / "ES" / "20260423_ES.jsonl")
    dmp_24 = load_dmp(ROOT / "DATA" / "ES" / "20260424_ES.jsonl")
    dmp = pd.concat([dmp_23, dmp_24]).sort_index()

    dbn_23 = pd.read_parquet(ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m" / "symbol=ES.c.0" / "year=2026" / "month=04" / "day=23" / "data.parquet")
    dbn_24 = pd.read_parquet(ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m" / "symbol=ES.c.0" / "year=2026" / "month=04" / "day=24" / "data.parquet")
    dbn = pd.concat([dbn_23, dbn_24]).sort_index()
    if dbn.index.tz is None:
        dbn.index = dbn.index.tz_localize("UTC")

    # Fenetre commune
    win_start = max(dmp.index.min(), dbn.index.min())
    win_end = min(dmp.index.max(), dbn.index.max())
    dmp_w = dmp.loc[win_start:win_end]
    dbn_w = dbn.loc[win_start:win_end]
    print(f"Fenetre: {win_start} -> {win_end}")
    print(f"DMP in win: {len(dmp_w)} | DBN in win: {len(dbn_w)}")

    # Timestamps DMP-only et DBN-only
    dmp_set = set(dmp_w.index)
    dbn_set = set(dbn_w.index)
    dmp_only = sorted(dmp_set - dbn_set)
    dbn_only = sorted(dbn_set - dmp_set)
    print(f"DMP-only: {len(dmp_only)} | DBN-only: {len(dbn_only)}")

    # Check H1 : DBN-only ont vol=0 cote DBN ?
    dbn_only_vols = dbn_w.loc[dbn_only]["volume"]
    print(f"\nH1 — DBN-only volumes (les bars que DMP a rate) :")
    print(f"  vol min/max/mean : {dbn_only_vols.min()}/{dbn_only_vols.max()}/{dbn_only_vols.mean():.1f}")
    print(f"  vol == 0 count   : {(dbn_only_vols == 0).sum()}")
    print(f"  vol > 0 count    : {(dbn_only_vols > 0).sum()}")

    # Sample 10 bars DBN-only avec leur volume
    print(f"\n  10 premiers DBN-only :")
    for ts in dbn_only[:10]:
        v = dbn_w.loc[ts]["volume"]
        # Voisin DMP le plus proche
        nearest_dmp_idx = dmp_w.index.get_indexer([ts], method="nearest")[0]
        nearest_dmp = dmp_w.index[nearest_dmp_idx]
        delta_sec = (nearest_dmp - ts).total_seconds()
        print(f"    {ts} vol_dbn={int(v):5d}  -> nearest DMP {nearest_dmp} (delta {delta_sec:+.0f}s)")

    # Check pattern temporel des DMP-only
    print(f"\nH3 — DMP-only timestamps (10 premiers) :")
    for ts in dmp_only[:10]:
        v = dmp_w.loc[ts]["vol"]
        print(f"    {ts} vol_dmp={int(v):5d}")

    # Histogramme par heure UTC des DBN-only
    print(f"\nH3 — Distribution DBN-only par heure UTC :")
    dbn_only_hours = pd.Series([t.hour for t in dbn_only])
    hourly = dbn_only_hours.value_counts().sort_index()
    for h, c in hourly.items():
        print(f"    {h:02d}h UTC : {c} bars")


if __name__ == "__main__":
    main()
