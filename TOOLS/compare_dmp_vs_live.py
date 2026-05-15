"""Analyse comparative DMP C++ Sierra Chart vs Live Enricher Databento.

Jackson 15/05/2026 : "COMPARE LES SNAPSHOTS C++ ET DATABENTO. VERIFIER LES
BONNES PRATIQUES DU C++ ET LES INTEGRER."

Compare :
  - DMP C++ : DATA/NQ/20260507_NQ.jsonl (262 cols schema 3.7.2)
  - Live Enricher : DATA/live_enriched/NQ_c_0/20260515.jsonl (430 cols)

Dimensions :
  1. Decimales : C++ utilise format "%.4f" -> 4 decimales fixes. Live = 17 chiffres.
  2. NaN/null encoding : C++ utilise "null" (JSON valid), Live utilise "NaN" (invalid).
  3. Schema stable : C++ schema_version explicite + ENUM domains.
  4. Cols mortes : C++ identifie systematiquement (lessons.md, 16 features 26j).
  5. Validator : C++ a dmp_validator.py 5 checks DMP-style.
  6. Ordering keys : C++ stable ordre alphabetique? Live = dict insertion order.
"""
import json
from pathlib import Path
from collections import Counter
import re

ROOT = Path(__file__).resolve().parents[1]

# === Charger samples ===
dmp_path = ROOT / "DATA" / "NQ" / "20260507_NQ.jsonl"
live_path = ROOT / "DATA" / "live_enriched" / "NQ_c_0" / "20260515.jsonl"

def load_first_bar(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                # DMP utilise NaN ? Verifions
                try:
                    return json.loads(line), line
                except json.JSONDecodeError:
                    return json.loads(line.replace("NaN", "null")), line

dmp_bar, dmp_raw = load_first_bar(dmp_path)
live_bar, live_raw = load_first_bar(live_path)

print("="*70)
print(" ANALYSE COMPARATIVE DMP C++ vs LIVE ENRICHER PYTHON")
print("="*70)

# === A. SCHEMA ===
print(f"\n=== A. SCHEMA ===")
print(f"  DMP C++ : {len(dmp_bar)} cols, line size {len(dmp_raw)} bytes")
print(f"  LIVE    : {len(live_bar)} cols, line size {len(live_raw)} bytes")
print(f"  Ratio   : LIVE est {len(live_raw)/len(dmp_raw):.2f}x plus gros")

# === B. NaN ENCODING ===
print(f"\n=== B. ENCODING NaN/NULL ===")
dmp_has_nan = "NaN" in dmp_raw
dmp_has_null = '"null"' in dmp_raw or ":null" in dmp_raw
live_has_nan = "NaN" in live_raw
live_has_null = '"null"' in live_raw or ":null" in live_raw
print(f"  DMP raw contains 'NaN' : {dmp_has_nan}")
print(f"  DMP raw contains 'null': {dmp_has_null}")
print(f"  LIVE raw contains 'NaN': {live_has_nan}")
print(f"  LIVE raw contains 'null': {live_has_null}")
if live_has_nan and not dmp_has_nan:
    print(f"  >>> BUG LIVE : utilise 'NaN' literal = JSON INVALIDE (RFC 8259)")
    print(f"  >>> C++ utilise 'null' qui est JSON-conforme")

# === C. PRECISION FLOATS ===
print(f"\n=== C. PRECISION FLOATS (extrait raw) ===")
# Sample float values from raw
def extract_float_samples(raw, max_n=15):
    # match patterns like "key":12.345 ou "key":-12.345
    matches = re.findall(r'"(\w+)":(-?\d+\.\d+)', raw)
    return matches[:max_n]

dmp_floats = extract_float_samples(dmp_raw, 10)
live_floats = extract_float_samples(live_raw, 10)
print(f"  DMP samples :")
for k, v in dmp_floats[:8]:
    print(f"    {k:30s} = {v:30s}  ({len(v.split('.')[1])} decimales)")
print(f"  LIVE samples :")
for k, v in live_floats[:8]:
    print(f"    {k:30s} = {v:30s}  ({len(v.split('.')[1])} decimales)")

# Count decimales statistique
def count_decimals(raw):
    counts = Counter()
    for v in re.findall(r':(-?\d+\.\d+)', raw):
        n_dec = len(v.split('.')[1])
        counts[n_dec] += 1
    return counts

dmp_dec = count_decimals(dmp_raw)
live_dec = count_decimals(live_raw)
print(f"\n  Distribution decimales DMP : {sorted(dmp_dec.items())}")
print(f"  Distribution decimales LIVE: {sorted(live_dec.items())}")

# === D. CONVENTIONS NOMS COLS ===
print(f"\n=== D. CONVENTIONS NOMS COLS ===")
dmp_keys = set(dmp_bar.keys())
live_keys = set(live_bar.keys())
common = dmp_keys & live_keys
only_dmp = dmp_keys - live_keys
only_live = live_keys - dmp_keys
print(f"  Communes (memes nom) : {len(common)}")
print(f"  DMP-only            : {len(only_dmp)}")
print(f"  LIVE-only           : {len(only_live)}")
print(f"\n  Communes sample (top 10) : {sorted(common)[:10]}")

# === E. NAMING dist_*_pct vs dist_*_atr vs dist_* (ticks) ===
print(f"\n=== E. CONVENTIONS dist_* ===")
dmp_dist = [k for k in dmp_keys if k.startswith("dist_")]
live_dist = [k for k in live_keys if k.startswith("dist_")]
print(f"  DMP dist_* : {len(dmp_dist)} (sample: {dmp_dist[:5]})")
print(f"  LIVE dist_*: {len(live_dist)} (sample: {live_dist[:5]})")
dmp_dist_atr = [k for k in dmp_dist if k.endswith("_atr")]
live_dist_pct = [k for k in live_dist if k.endswith("_pct")]
print(f"  DMP dist_*_atr (normalises ATR) : {len(dmp_dist_atr)} -> {dmp_dist_atr[:5]}")
print(f"  LIVE dist_*_pct (normalises %)  : {len(live_dist_pct)} -> {live_dist_pct[:5]}")

# === F. CHAMP META ===
print(f"\n=== F. CHAMPS META ===")
print(f"  DMP : sym={dmp_bar.get('sym')}, contract={dmp_bar.get('contract')},")
print(f"        session={dmp_bar.get('session')}, session_id={dmp_bar.get('session_id')}")
print(f"  LIVE: symbol={live_bar.get('symbol')}, instrument_id={live_bar.get('instrument_id')},")
print(f"        ts_event_iso={live_bar.get('ts_event_iso')}, schema_version={live_bar.get('schema_version')}")

# === G. KEY ORDER ===
print(f"\n=== G. ORDRE CLES ===")
dmp_first_5 = list(dmp_bar.keys())[:5]
live_first_5 = list(live_bar.keys())[:5]
print(f"  DMP premieres 5 cles : {dmp_first_5}")
print(f"  LIVE premieres 5 cles: {live_first_5}")

# === H. PROPRETE NaN ===
def count_nan_in_bar(bar):
    n_nan = 0
    n_total = 0
    for v in bar.values():
        n_total += 1
        if v is None or (isinstance(v, float) and v != v):
            n_nan += 1
    return n_nan, n_total

dmp_nan, dmp_total = count_nan_in_bar(dmp_bar)
live_nan, live_total = count_nan_in_bar(live_bar)
print(f"\n=== H. NaN/null par bar (1 bar sample) ===")
print(f"  DMP : {dmp_nan}/{dmp_total} = {100*dmp_nan/dmp_total:.1f}% NaN")
print(f"  LIVE: {live_nan}/{live_total} = {100*live_nan/live_total:.1f}% NaN")
