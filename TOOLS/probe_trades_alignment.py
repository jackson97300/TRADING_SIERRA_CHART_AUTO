"""Verifier alignement trades_window_n vs volume bar post fix BUG #3."""
import json
import sys
from pathlib import Path

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO" if __import__("os").name == "nt" else ".")

for sym, sym_fs in [("ES", "ES"), ("NQ", "NQ"), ("MGC", "GC")]:
    p = ROOT / "DATA" / "live_enriched" / sym_fs / "20260515_{}.jsonl".format(sym_fs)
    if not p.exists():
        print(f"{sym}: file missing {p}")
        continue
    with open(p, encoding="utf-8") as f:
        lines = f.readlines()
    print(f"\n=== {sym} {p.name} : total {len(lines)} bars ===")
    n_aligned = 0
    n_above_vol = 0
    for line in lines[-10:]:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        vol = d.get("volume", 0) or 0
        tn = d.get("trades_window_n", 0) or 0
        aligned = d.get("trades_window_aligned", 0)
        ratio = tn / vol if vol else 0
        flag = "OK" if tn <= vol else f"BUG (tn>{vol})"
        if aligned == 1:
            n_aligned += 1
        if tn > vol:
            n_above_vol += 1
        print(f"  ts={d.get('ts_event_iso')[:19] if d.get('ts_event_iso') else 'N/A'} vol={vol} trades_n={tn} ratio={ratio:.2f} aligned={aligned} {flag}")
    print(f"  10 last bars : aligned={n_aligned}/10  above_vol={n_above_vol}/10")
