"""Audit murs eligibles SL/TP dans parquet V4 vs SLTPEngine attendus.

Pour chaque mur T1/T2/T3 du SLTPEngine :
  - Disponible directement (ticks brut) dans V4 ?
  - Disponible via helper _pct (injection) ?
  - Manquant (mur mort) ?

But : repondre a Jackson "lister les murs eligibles a proteger le SL".
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "CORE"))
from mia_sltp import TIER1_WALLS, TIER2_WALLS, TIER3_WALLS

ROOT = Path(__file__).resolve().parents[1]

# Mapping helper : V4 _pct → SLTPEngine name (depuis _inject_dist_ticks_from_pct)
SPECIAL_MAP_PCT_TO_TICKS = {
    "dist_1d_min_ticks_pct": "dist_1d_min_ticks",
    "dist_1d_max_ticks_pct": "dist_1d_max_ticks",
    "dist_last_swing_high_pct": "dist_swing_high",
    "dist_last_swing_low_pct": "dist_swing_low",
}


def check_wall_availability(parquet_path: Path):
    df = pd.read_parquet(parquet_path)
    cols = set(df.columns)

    print(f"\n{'='*80}")
    print(f"  AUDIT MURS SL/TP — {parquet_path.name}")
    print(f"{'='*80}")
    print(f"  Total cols: {len(cols)}\n")

    for tier_name, walls in [("TIER 1 (vrais murs, score >0.35)", TIER1_WALLS),
                              ("TIER 2 (murs solides, score 0.20-0.35)", TIER2_WALLS),
                              ("TIER 3 (murs papier, danger)", TIER3_WALLS)]:
        print(f"\n  ── {tier_name} — {len(walls)} walls ──")
        n_direct = 0
        n_via_pct = 0
        n_missing = 0
        for wall_col, (wall_name, role) in walls.items():
            # Disponible directement ?
            has_brut = wall_col in cols
            # Via _pct ?
            pct_col = wall_col + "_pct"
            via_pct_simple = pct_col in cols
            # Via special_map (reverse lookup)
            via_special = any(sltp_name == wall_col for pct_key, sltp_name in SPECIAL_MAP_PCT_TO_TICKS.items()
                               if pct_key in cols)

            if has_brut:
                status = "✅ DIRECT"
                n_direct += 1
            elif via_pct_simple or via_special:
                status = "🔧 via _pct"
                n_via_pct += 1
            else:
                status = "❌ MANQUANT"
                n_missing += 1
            print(f"    {status:18s} {wall_col:32s} ({wall_name:18s}, {role})")
        print(f"\n  Total {tier_name.split('(')[0].strip()}: "
              f"direct={n_direct}, via_pct={n_via_pct}, missing={n_missing}")


if __name__ == "__main__":
    # V4 enrichi (Bot 2)
    check_wall_availability(ROOT / "DATA" / "datasets" / "ES_dataset_v5e.parquet")
    check_wall_availability(ROOT / "DATA" / "datasets" / "NQ_dataset_v5e.parquet")
