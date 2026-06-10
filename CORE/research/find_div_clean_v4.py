"""find_div_clean_v4.py — Cherche les features dashboard manquantes dans V4 sous tous noms possibles."""
import pyarrow.parquet as pq
from pathlib import Path

V4 = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")
parquet = V4 / "symbol=NQ.c.0/year=2026/month=05/data.parquet"
schema = pq.read_schema(str(parquet))
cols = sorted(schema.names)

print(f"Total colonnes V4 NQ : {len(cols)}\n")

# Cherche par mots-cles toutes les variantes possibles
patterns = {
    "delta_div / divergence": ["div", "delta_div", "_clean", "divergence"],
    "next_wall / mq_call / put": ["wall", "mq_call", "mq_put", "mq_hvl", "next_wall"],
    "absorb / absorption": ["absorb", "absorption", "stack"],
    "near_level / bool": ["near_level", "bool_near", "near_lev"],
    "ib_narrow / ib_wide": ["ib_narrow", "ib_is_narrow", "ib_wide"],
    "swing": ["swing"],
    "vwap_m_side / vwap_slope_dir": ["vwap_m_side", "vwap_slope_10_dir", "slope_dir", "_dir"],
}
for label, pats in patterns.items():
    print(f"\n[{label}]")
    matches = []
    for c in cols:
        if any(p in c.lower() for p in pats):
            matches.append(c)
    if matches:
        for m in sorted(matches)[:25]:
            print(f"  {m}")
        if len(matches) > 25:
            print(f"  ... +{len(matches)-25} autres")
    else:
        print(f"  AUCUN MATCH")
