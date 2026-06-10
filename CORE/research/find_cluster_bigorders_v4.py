"""find_cluster_bigorders_v4.py — Cherche features cluster + big orders dans V4."""
import pyarrow.parquet as pq
from pathlib import Path

V4 = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")
parquet = V4 / "symbol=NQ.c.0/year=2026/month=05/data.parquet"
schema = pq.read_schema(str(parquet))
cols = sorted(schema.names)

groups = {
    "Cluster": [c for c in cols if "cluster" in c.lower()],
    "Big orders": [c for c in cols if "big_" in c.lower() or "big_ask" in c.lower() or "big_bid" in c.lower()],
    "Stack": [c for c in cols if "stack" in c.lower()],
    "Zones active": [c for c in cols if "_zones_active" in c.lower()],
    "Distance nearest": [c for c in cols if "_nearest" in c.lower()],
    "im_ (intermarche)": [c for c in cols if c.startswith("im_")],
    "Smart Money Tool / SMT": [c for c in cols if "smt" in c.lower()],
    "Edge / rejection": [c for c in cols if "edge" in c.lower() or "rejection" in c.lower()],
}
for g, items in groups.items():
    if items:
        print(f"\n[{g}] ({len(items)})")
        for c in sorted(items):
            print(f"  {c}")
