"""
Databento Phase 0 — Smoke test
Verifie connexion API + liste les datasets disponibles + cost estimate.

Aucune donnee telechargee a ce stade. Pure verification.
"""
import os
import sys
from pathlib import Path

# Charger .env
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    print("[FAIL] DATABENTO_API_KEY non trouve dans .env")
    sys.exit(1)

print("=" * 70)
print(" DATABENTO — PHASE 0 SMOKE TEST")
print("=" * 70)
print(f" Cle API: {API_KEY[:12]}...{API_KEY[-4:]}  (longueur {len(API_KEY)})")
print()

import databento as db

client = db.Historical(API_KEY)
print(f"[OK] SDK databento {db.__version__} initialise")
print()

# Liste datasets disponibles
print("-" * 70)
print(" DATASETS DISPONIBLES")
print("-" * 70)
try:
    datasets = client.metadata.list_datasets()
    for d in datasets[:20]:
        print(f"  - {d}")
    print(f"  Total: {len(datasets)} datasets")
except Exception as e:
    print(f"[FAIL] list_datasets: {e}")
    sys.exit(2)
print()

# Liste schemas pour GLBX.MDP3 (CME)
print("-" * 70)
print(" SCHEMAS GLBX.MDP3 (CME Globex)")
print("-" * 70)
try:
    schemas = client.metadata.list_schemas(dataset="GLBX.MDP3")
    for s in schemas:
        print(f"  - {s}")
except Exception as e:
    print(f"[FAIL] list_schemas: {e}")
print()

# Date range disponible pour GLBX.MDP3
print("-" * 70)
print(" PLAGE HISTORIQUE GLBX.MDP3")
print("-" * 70)
try:
    drange = client.metadata.get_dataset_range(dataset="GLBX.MDP3")
    print(f"  Start : {drange.get('start')}")
    print(f"  End   : {drange.get('end')}")
except Exception as e:
    print(f"[FAIL] get_dataset_range: {e}")
print()

# Cost estimate pour 1 jour ES MBP-10 (24/04/2026)
print("-" * 70)
print(" COST ESTIMATE — 1 jour ES MBP-10 (24/04/2026)")
print("-" * 70)
try:
    cost = client.metadata.get_cost(
        dataset="GLBX.MDP3",
        symbols=["ES.c.0"],
        schema="mbp-10",
        start="2026-04-24",
        end="2026-04-25",
        stype_in="continuous",
    )
    print(f"  Cost: ${cost:.4f}")
except Exception as e:
    print(f"[INFO] cost ES MBP-10 1d: {e}")
print()

# Cost estimate pour 1 jour ES Trades
print("-" * 70)
print(" COST ESTIMATE — 1 jour ES Trades (24/04/2026)")
print("-" * 70)
try:
    cost = client.metadata.get_cost(
        dataset="GLBX.MDP3",
        symbols=["ES.c.0"],
        schema="trades",
        start="2026-04-24",
        end="2026-04-25",
        stype_in="continuous",
    )
    print(f"  Cost: ${cost:.4f}")
except Exception as e:
    print(f"[INFO] cost ES Trades 1d: {e}")
print()

# Cost estimate pour 1 jour ES OHLCV-1m
print("-" * 70)
print(" COST ESTIMATE — 1 jour ES OHLCV-1m (24/04/2026)")
print("-" * 70)
try:
    cost = client.metadata.get_cost(
        dataset="GLBX.MDP3",
        symbols=["ES.c.0"],
        schema="ohlcv-1m",
        start="2026-04-24",
        end="2026-04-25",
        stype_in="continuous",
    )
    print(f"  Cost: ${cost:.4f}")
except Exception as e:
    print(f"[INFO] cost ES OHLCV-1m 1d: {e}")
print()

print("=" * 70)
print(" SMOKE TEST OK — pret pour Phase 0 download")
print("=" * 70)
