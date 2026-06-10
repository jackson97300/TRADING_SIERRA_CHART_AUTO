"""Verifier les snapshots v3 ecrits par le bot."""
import json
from pathlib import Path

fp = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES/20260428_databento_paper_snapshots.jsonl")
lines = fp.read_text(encoding="utf-8").splitlines()
print(f"Total lines: {len(lines)}")

v3_lines = [l for l in lines if "snapshot_v3" in l]
v_old_lines = [l for l in lines if "snapshot_v3" not in l]
print(f"  v3 lines: {len(v3_lines)}")
print(f"  old (49 features) lines: {len(v_old_lines)}")

if not v3_lines:
    print("NO v3 snapshot yet")
    raise SystemExit(0)

# Last v3 snapshot
s = json.loads(v3_lines[-1])
print(f"\n=== LAST v3 SNAPSHOT ===")
print(f"  schema_version: {s['schema_version']}")
print(f"  symbol: {s['symbol']}")
print(f"  bar_ts: {s['bar_ts']}")
print(f"  direction: {s['direction']}")
print(f"  bull/bear: {s['bull_pts']}/{s['bear_pts']}")
print(f"  n_features (non-null logged): {s['n_features']}")

feats = s.get("features", {})
# Echantillon par categorie
print(f"\n  Sample features par prefix:")
prefixes = {}
for f, v in feats.items():
    p = f.split('_')[0]
    if p not in prefixes:
        prefixes[p] = (f, v, 1)
    else:
        old_f, old_v, cnt = prefixes[p]
        prefixes[p] = (old_f, old_v, cnt + 1)

for p in sorted(prefixes.keys()):
    f, v, cnt = prefixes[p]
    if isinstance(v, float):
        print(f"    {p:20s} ({cnt:3d} feats) : {f} = {v:.4f}")
    else:
        print(f"    {p:20s} ({cnt:3d} feats) : {f} = {v}")

# Taille fichier
import os
size_kb = fp.stat().st_size / 1024
print(f"\n  Taille fichier total: {size_kb:.0f} KB ({len(lines)} snapshots)")
print(f"  Taille moyenne snapshot v3: {size_kb / len(v3_lines):.1f} KB")
