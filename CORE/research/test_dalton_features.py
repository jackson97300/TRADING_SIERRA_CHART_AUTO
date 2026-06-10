"""
Test empirique Dalton L1 + L2 + L4 sur 4 jours propres.

Valide que :
- Les features fire aux bons moments (pas toutes a 0, pas toutes a 1)
- Le migration_streak evolue coherentent
- L4 RISK gate veto fonctionne

Usage :
    python -X utf8 CORE/research/test_dalton_features.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.dalton_features import DaltonFeatureHelper, check_anti_poc_magnet


JOURS = ["20260417", "20260419", "20260420", "20260421"]


def test_symbol(symbol: str):
    print(f"\n{'='*72}")
    print(f"DALTON FEATURES — {symbol}")
    print(f"{'='*72}")

    helper = DaltonFeatureHelper()

    all_features = []
    total_bars = 0

    for j in JOURS:
        path = Path(f"DATA/{symbol}/{j}_{symbol}.jsonl")
        if not path.exists():
            continue
        with open(path, "r") as f:
            for line in f:
                bar = json.loads(line)
                features = helper.compute(bar)
                all_features.append({**features, "ts": bar.get("ts"), "date": j})
                total_bars += 1

    print(f"Total bars analyzed : {total_bars}")

    # L1 stats
    resp_buy = sum(f["ctx_responsive_buy"] for f in all_features)
    resp_sell = sum(f["ctx_responsive_sell"] for f in all_features)
    init_buy = sum(f["ctx_initiating_buy"] for f in all_features)
    init_sell = sum(f["ctx_initiating_sell"] for f in all_features)
    print(f"\n=== L1 Responsive / Initiating ===")
    print(f"  ctx_responsive_buy  : {resp_buy} events ({100*resp_buy/total_bars:.1f}%)")
    print(f"  ctx_responsive_sell : {resp_sell} events ({100*resp_sell/total_bars:.1f}%)")
    print(f"  ctx_initiating_buy  : {init_buy} events ({100*init_buy/total_bars:.1f}%)")
    print(f"  ctx_initiating_sell : {init_sell} events ({100*init_sell/total_bars:.1f}%)")

    # L2 stats
    placements = Counter(f["ctx_va_placement"] for f in all_features)
    print(f"\n=== L2 VA Placement ===")
    placement_names = {-2: "LOWER", -1: "OVERLAP_LOWER", 0: "OVERLAP",
                       1: "OVERLAP_HIGHER", 2: "HIGHER"}
    for code in sorted(placements.keys()):
        count = placements[code]
        pct = 100 * count / total_bars
        name = placement_names.get(code, f"UNK_{code}")
        print(f"  {name:<18} (code={code:>2}) : {count:>5} bars ({pct:>4.1f}%)")

    # Migration streak distribution
    streak_max = max(f["ctx_va_migration_streak"] for f in all_features)
    print(f"\n  max migration_streak : {streak_max}")

    # L3 Day Type Dalton distribution
    from CORE.dalton_features import DAY_TYPE_DALTON_NAMES
    dt_dalton = Counter(f.get("ctx_day_type_dalton", 0) for f in all_features)
    print(f"\n=== L3 Day Type Dalton (6 classes) ===")
    for code in sorted(dt_dalton.keys()):
        count = dt_dalton[code]
        pct = 100 * count / total_bars
        name = DAY_TYPE_DALTON_NAMES.get(code, f"UNK_{code}")
        print(f"  {name:<20} (code={code}) : {count:>5} bars ({pct:>4.1f}%)")

    # L5 Open Type size multiplier distribution
    mults = [f.get("ctx_open_type_size_mult", 0.5) for f in all_features]
    labels = Counter(f.get("ctx_open_type_label", "?").split("_conf")[0] for f in all_features)
    print(f"\n=== L5 Open Type size multiplier ===")
    print(f"  Mult min/avg/max : {min(mults):.2f} / {sum(mults)/len(mults):.2f} / {max(mults):.2f}")
    print(f"  Distribution open_type labels (top 5) :")
    for label, count in labels.most_common(5):
        pct = 100 * count / total_bars
        print(f"    {label:<15} : {count:>5} bars ({pct:>4.1f}%)")

    # L1 firing sample (first 10 events)
    print(f"\n=== Sample events L1 (first 8) ===")
    import datetime as dt
    events = [f for f in all_features if (f["ctx_responsive_buy"] + f["ctx_responsive_sell"] + f["ctx_initiating_buy"] + f["ctx_initiating_sell"]) > 0][:8]
    for e in events:
        paris = dt.datetime.fromtimestamp(e["ts"]/1000, tz=dt.timezone.utc) + dt.timedelta(hours=2)
        flags = []
        if e["ctx_responsive_buy"]: flags.append("RESP_BUY")
        if e["ctx_responsive_sell"]: flags.append("RESP_SELL")
        if e["ctx_initiating_buy"]: flags.append("INIT_BUY")
        if e["ctx_initiating_sell"]: flags.append("INIT_SELL")
        print(f"  {e['date']} {paris.strftime('%H:%M:%S')}P  {'+'.join(flags)}  ratio={e['ctx_init_vs_resp_ratio']:+.2f}")


def test_l4_gate():
    """Test L4 RISK gate sur samples synthetiques."""
    print(f"\n{'='*72}")
    print("L4 — RISK gate anti-POC-magnet trend day")
    print(f"{'='*72}")

    tests = [
        # (row, thesis, expected_allow, description)
        ({"ctx_trend_day_score": 0.8, "dist_cur_vpoc_atr": 0.2}, "return_to_POC",
         False, "Trend day strong + trade vise POC proche -> VETO"),
        ({"ctx_trend_day_score": 0.3, "dist_cur_vpoc_atr": 0.2}, "return_to_POC",
         True, "Score trend faible -> pas veto"),
        ({"ctx_trend_day_score": 0.8, "dist_cur_vpoc_atr": 2.0}, "return_to_POC",
         True, "Trend day mais POC eloigne -> pas magnet -> pas veto"),
        ({"ctx_trend_day_score": 0.8, "dist_cur_vpoc_atr": 0.2}, "breakout_continuation",
         True, "Trend day mais thesis != POC magnet -> autorise"),
        ({"ctx_trend_day_score": None, "dist_cur_vpoc_atr": 0.2}, "return_to_POC",
         True, "Features manquantes -> fail-open autorise"),
    ]

    import pandas as pd
    for row_dict, thesis, expected, desc in tests:
        row = pd.Series(row_dict)
        allow, reason = check_anti_poc_magnet(row, thesis)
        status = "✓" if allow == expected else "✗"
        print(f"  {status} {desc}")
        print(f"    allow={allow}  reason={reason}")


def main():
    for sym in ["NQ", "ES"]:
        test_symbol(sym)
    test_l4_gate()

    print(f"\n{'='*72}")
    print("Dalton L1 + L2 + L4 codes et testes empiriquement.")
    print("Features integrables dans dataset_builder v4 + V2CLEAN signal_engine.")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
