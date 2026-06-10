"""Verifie range_pos dans Sierra DMP vs Databento V4 enriched pour les trades 11/05."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# Trades 11/05 avec range_pos=0 vu dans Sierra
TARGETS = [
    ("NQ", "2026-05-11T08:27:00Z"),
    ("NQ", "2026-05-11T14:29:00Z"),
    ("NQ", "2026-05-11T18:59:00Z"),
    ("NQ", "2026-05-12T01:51:00Z"),
    ("NQ", "2026-05-12T02:17:00Z"),
]


def load_sierra_bar(sym: str, target_ts: datetime) -> dict | None:
    date_str = target_ts.strftime("%Y%m%d")
    fp = ROOT / "DATA" / sym / f"{date_str}_{sym}.jsonl"
    if not fp.exists():
        return None
    best, best_dt = None, 99999
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            try:
                bar_ts = datetime.fromtimestamp(int(j.get("ts", 0)) / 1000, tz=timezone.utc)
            except Exception:
                continue
            if bar_ts <= target_ts:
                dt = (target_ts - bar_ts).total_seconds()
                if dt < best_dt and dt < 180:
                    best_dt = dt
                    best = j
    return best


def load_v4_bar(sym: str, target_ts: datetime) -> dict | None:
    year = target_ts.year
    month = target_ts.month
    fp = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    if not fp.exists():
        return None
    df = pq.read_table(fp).to_pandas()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    target_pd = pd.Timestamp(target_ts)
    if target_pd.tz is None:
        target_pd = target_pd.tz_localize("UTC")
    matches = df[df["ts_event"] <= target_pd]
    if matches.empty:
        return None
    last = matches.sort_values("ts_event").iloc[-1]
    return last.to_dict()


print("=" * 100)
print("COMPARAISON range_pos Sierra DMP vs Databento V4 enriched")
print("=" * 100)
print()
print(f"{'Target_ts':<22}{'Sym':<5}{'Sierra rp':<12}{'Sierra d_swL':<14}{'Sierra range_size':<18}"
      f"{'V4 rp':<10}{'V4 d_swL':<11}{'V4 ts_event':<24}{'V4_age_min'}")
print("-" * 130)

for sym, ts_str in TARGETS:
    target_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

    sierra = load_sierra_bar(sym, target_ts)
    v4 = load_v4_bar(sym, target_ts)

    s_rp = sierra.get("range_pos") if sierra else "?"
    s_dsl = sierra.get("dist_swing_low") if sierra else "?"
    s_rsz = sierra.get("range_size_ticks") if sierra else "?"

    if v4:
        v_rp = v4.get("range_pos", "?")
        v_dsl = v4.get("dist_swing_low", "?")
        v_ts = v4.get("ts_event")
        v_age = (target_ts - v_ts.to_pydatetime()).total_seconds() / 60 if v_ts is not None else None
        v_ts_str = v_ts.strftime("%Y-%m-%d %H:%M") if v_ts is not None else "?"
        v_age_str = f"{v_age:.1f}" if v_age is not None else "?"
    else:
        v_rp, v_dsl, v_ts_str, v_age_str = "?", "?", "no file", "?"

    print(f"{ts_str:<22}{sym:<5}"
          f"{str(s_rp):<12}{str(s_dsl):<14}{str(s_rsz):<18}"
          f"{str(v_rp)[:9]:<10}{str(v_dsl)[:10]:<11}{v_ts_str:<24}{v_age_str}")

print()
print("=== Distribution range_pos Sierra DMP 11/05 (NQ) ===")
fp = ROOT / "DATA" / "NQ" / "20260511_NQ.jsonl"
if fp.exists():
    bins = {"=0": 0, "0-10": 0, "10-30": 0, "30-50": 0, "50-70": 0, "70-90": 0, ">=90": 0, "null": 0}
    n_total = 0
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            rp = j.get("range_pos")
            n_total += 1
            if rp is None:
                bins["null"] += 1; continue
            try:
                rp = float(rp)
            except (TypeError, ValueError):
                bins["null"] += 1; continue
            if rp == 0:
                bins["=0"] += 1
            elif rp < 10:
                bins["0-10"] += 1
            elif rp < 30:
                bins["10-30"] += 1
            elif rp < 50:
                bins["30-50"] += 1
            elif rp < 70:
                bins["50-70"] += 1
            elif rp < 90:
                bins["70-90"] += 1
            else:
                bins[">=90"] += 1
    print(f"Total bars : {n_total}")
    for k, v in bins.items():
        pct = round(100 * v / max(n_total, 1), 1)
        print(f"  range_pos {k:<10} : {v:>6} ({pct}%)")

print()
print("=== Distribution range_pos Databento V4 NQ 2026-05 ===")
fp = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
if fp.exists():
    df = pq.read_table(fp).to_pandas()
    if "range_pos" in df.columns:
        bins = {"=0": 0, "0-10": 0, "10-30": 0, "30-50": 0, "50-70": 0, "70-90": 0, ">=90": 0, "null": 0}
        for rp in df["range_pos"]:
            if pd.isna(rp):
                bins["null"] += 1
                continue
            rp = float(rp)
            if rp == 0:
                bins["=0"] += 1
            elif rp < 10:
                bins["0-10"] += 1
            elif rp < 30:
                bins["10-30"] += 1
            elif rp < 50:
                bins["30-50"] += 1
            elif rp < 70:
                bins["50-70"] += 1
            elif rp < 90:
                bins["70-90"] += 1
            else:
                bins[">=90"] += 1
        n_total = len(df)
        print(f"Total bars : {n_total}")
        for k, v in bins.items():
            pct = round(100 * v / max(n_total, 1), 1)
            print(f"  range_pos {k:<10} : {v:>6} ({pct}%)")
    else:
        print("range_pos NOT in V4 enriched columns !")
        print(f"Cols available : {list(df.columns)[:30]}")
