"""Compare Sierra DMP NQ vs Databento V4 enriched bars autour du trade SL 02:17 UTC."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

print("=" * 80)
print("COMPARAISON Sierra DMP NQ vs Databento V4 enriched")
print("Fenetre : 02:10 -> 02:24 UTC le 12/05/2026")
print("Trade Bot 1 + Bot 2 V6 : SHORT @ 29317.50 a 02:17:11 UTC")
print("=" * 80)
print()

# Sierra DMP
print("=== SIERRA DMP JSONL ===")
sierra_path = ROOT / "DATA" / "NQ" / "20260512_NQ.jsonl"
if not sierra_path.exists():
    print(f"NOT FOUND : {sierra_path}")
else:
    print(f"{'time_UTC':<10}{'price':<12}{'bar_h':<12}{'bar_l':<12}{'range_pos':<11}"
          f"{'d_swH':<10}{'d_swL':<10}{'sess_H':<10}{'sess_L':<10}{'mom_3b':<10}")
    print("-" * 110)
    with open(sierra_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            bar_dt = datetime.fromtimestamp(j["ts"] / 1000, tz=timezone.utc)
            if not (datetime(2026, 5, 12, 2, 10, tzinfo=timezone.utc)
                    <= bar_dt <=
                    datetime(2026, 5, 12, 2, 24, tzinfo=timezone.utc)):
                continue
            print(f"{bar_dt.strftime('%H:%M:%S'):<10}"
                  f"{j.get('price','?'):<12}"
                  f"{j.get('bar_high','?'):<12}"
                  f"{j.get('bar_low','?'):<12}"
                  f"{round(float(j.get('range_pos', 0)), 1):<11}"
                  f"{j.get('dist_swing_high','?'):<10}"
                  f"{j.get('dist_swing_low','?'):<10}"
                  f"{j.get('dist_sess_high','?'):<10}"
                  f"{j.get('dist_sess_low','?'):<10}"
                  f"{j.get('momentum_3b','?'):<10}")

print()
# Databento V4 enriched
print("=== DATABENTO V4 ENRICHED PARQUET ===")
v4_path = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
if not v4_path.exists():
    print(f"NOT FOUND : {v4_path}")
else:
    df = pq.read_table(v4_path).to_pandas()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    lo = pd.Timestamp("2026-05-12T02:10:00Z")
    hi = pd.Timestamp("2026-05-12T02:24:00Z")
    m = df[(df["ts_event"] >= lo) & (df["ts_event"] <= hi)].copy()
    cols_available = [c for c in m.columns if c in (
        "ts_event", "close", "open", "high", "low",
        "range_pos", "dist_swing_high", "dist_swing_low",
        "dist_sess_high", "dist_sess_low", "momentum_3b",
        "vwap_d_side", "volume", "volume_z"
    )]
    print(f"Colonnes dispo : {cols_available}")
    print()
    show_cols = ["ts_event", "close", "high", "low", "range_pos",
                 "dist_swing_high", "dist_swing_low",
                 "dist_sess_high", "dist_sess_low", "momentum_3b"]
    show_cols = [c for c in show_cols if c in m.columns]
    if not m.empty:
        for _, r in m.iterrows():
            t = r["ts_event"].strftime("%H:%M:%S")
            close = round(float(r.get("close", 0)), 2) if pd.notna(r.get("close")) else "?"
            high = round(float(r.get("high", 0)), 2) if pd.notna(r.get("high")) else "?"
            low = round(float(r.get("low", 0)), 2) if pd.notna(r.get("low")) else "?"
            rp = round(float(r.get("range_pos", 0)), 1) if pd.notna(r.get("range_pos")) else "?"
            dsh = round(float(r.get("dist_swing_high", 0)), 1) if pd.notna(r.get("dist_swing_high")) else "?"
            dsl = round(float(r.get("dist_swing_low", 0)), 1) if pd.notna(r.get("dist_swing_low")) else "?"
            sh = round(float(r.get("dist_sess_high", 0)), 1) if pd.notna(r.get("dist_sess_high")) else "?"
            sl = round(float(r.get("dist_sess_low", 0)), 1) if pd.notna(r.get("dist_sess_low")) else "?"
            m3 = round(float(r.get("momentum_3b", 0)), 2) if pd.notna(r.get("momentum_3b")) else "?"
            print(f"{t:<10}close={close:<10}H={high:<10}L={low:<10}"
                  f"rp={rp:<8}d_swH={dsh:<8}d_swL={dsl:<8}"
                  f"sH={sh:<8}sL={sl:<8}m3b={m3}")
    else:
        print(f"V4 enriched : aucune bar dans la fenetre (max ts = {df['ts_event'].max()})")
