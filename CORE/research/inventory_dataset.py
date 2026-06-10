"""Inventory complet du dataset Databento + DMP JSONL + V4 enriched."""
from pathlib import Path
from collections import defaultdict
import os

ROOT = Path(__file__).resolve().parents[2]

print("=" * 70)
print("INVENTORY DATASET")
print("=" * 70)

# Databento DBN.zst
print("\n=== DATABENTO DBN.zst (ohlcv-1m) ===")
db_root = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"
for sym_dir in sorted(db_root.iterdir() if db_root.exists() else []):
    if not sym_dir.is_dir():
        continue
    years = sorted(d.name for d in sym_dir.iterdir() if d.name.startswith("year="))
    months_total = 0
    for y_dir in sym_dir.iterdir():
        if not y_dir.name.startswith("year="):
            continue
        for m_dir in y_dir.iterdir():
            if m_dir.name.startswith("month="):
                days = [d for d in m_dir.iterdir() if d.name.startswith("day=") and (d / "data.dbn.zst").exists()]
                months_total += len(days)
    print(f"  {sym_dir.name:<25} years={years} total_days={months_total}")

# DMP JSONL Sierra
print("\n=== DMP JSONL Sierra (DATA/{ES,NQ,MGC}/*.jsonl) ===")
for sym in ["ES", "NQ", "MGC"]:
    d = ROOT / "DATA" / sym
    if d.exists():
        files = sorted(f.name for f in d.glob("*.jsonl"))
        if files:
            print(f"  {sym}: {len(files)} jours ({files[0][:8]} -> {files[-1][:8]})")
        else:
            print(f"  {sym}: 0 fichiers")

# V4 enriched parquet
print("\n=== V4 enriched parquet ===")
v4_root = ROOT / "DATA" / "datasets" / "v4_enriched"
for sym_dir in sorted(v4_root.iterdir() if v4_root.exists() else []):
    if not sym_dir.is_dir():
        continue
    parquets = list(sym_dir.glob("**/data.parquet"))
    if parquets:
        sizes_mb = [round(p.stat().st_size / 1024 / 1024, 1) for p in parquets]
        print(f"  {sym_dir.name:<35} {len(parquets)} months  sizes(MB)={sizes_mb}")

# MenthorQ JSON
print("\n=== MenthorQ JSON ===")
mq_root = ROOT / "DATA" / "MENTHORQ"
if mq_root.exists():
    files = sorted(mq_root.glob("*.json"))
    if files:
        print(f"  Total fichiers : {len(files)}")
        print(f"  First : {files[0].name}")
        print(f"  Last : {files[-1].name}")

# Labels
print("\n=== LABELS ===")
lab_root = ROOT / "DATA" / "LABELS"
if lab_root.exists():
    files = sorted(lab_root.glob("*.csv"))
    if files:
        print(f"  Total labels CSV : {len(files)}")
        print(f"  First : {files[0].name}")
        print(f"  Last : {files[-1].name}")
