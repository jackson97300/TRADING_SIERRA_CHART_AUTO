"""Tests parite regime_engine.py vs DASHBOARD/api/builders.py:build_regime_context.

S1 reserve code-reviewer (03/05/2026 Plan B). Verifie que regime_engine retourne
des verdicts COHERENTS avec le dashboard sur 5 bars samples reels (4 jours
data clean 27/04 -> 01/05 + 1 bar ES).

Test pas strict ligne-pour-ligne (regime_engine = bias proxy simplifie vs
compute_bias officiel dashboard, drift attendu sur quelques bars). Verifie :
  - Mode (TREND/RANGE/NORMAL) : doit converger >= 80% des bars
  - Direction favor : doit converger sur sens (LONG/SHORT/NEUTRE) >= 70%
  - Vol regime : doit converger 100% (pure ratio sess_range_atr)

Ces seuils servent de filet de securite avant deploy V4 14 mois.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.regime_engine import compute_regime
from DASHBOARD.api.builders import build_regime_context


def load_dmp_bar(symbol: str, date: str, bar_idx: int) -> dict:
    """Charge 1 bar du DMP JSONL VPS (data clean post-17/04)."""
    path = ROOT / "DATA" / symbol / f"{date}_{symbol}.jsonl"
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    return json.loads(lines[bar_idx])


def compare_bar(symbol: str, date: str, bar_idx: int, label: str) -> dict:
    """Compare verdict regime_engine vs dashboard pour 1 bar."""
    bar = load_dmp_bar(symbol, date, bar_idx)
    re_result = compute_regime(bar)
    db_result = build_regime_context(bar)

    return {
        "label": label,
        "symbol": symbol,
        "date": date,
        "bar_idx": bar_idx,
        "engine_mode": re_result.mode,
        "engine_favor": re_result.favor,
        "engine_vol": re_result.vol_regime,
        "engine_trend_votes": re_result.trend_votes,
        "engine_range_votes": re_result.range_votes,
        "dashboard_mode": db_result.get("mode", "?"),
        "dashboard_favor": db_result.get("favor", "?"),
        "dashboard_vol": db_result.get("vol_regime", "?"),
        "dashboard_trend_votes": db_result.get("mode_trend_votes", -1),
        "dashboard_range_votes": db_result.get("mode_range_votes", -1),
    }


def main():
    """Lance comparaison 8 bars samples + verdict global."""
    samples = [
        # (symbol, date, bar_idx, label)
        ("NQ", "20260427", 800, "27/04 NQ early-RTH"),
        ("NQ", "20260428", 1000, "28/04 NQ RTH (jour OK +422$)"),
        ("NQ", "20260429", 1100, "29/04 NQ RTH (perdant -270$)"),
        ("NQ", "20260430", 1100, "30/04 NQ RTH (perdant -230$)"),
        ("NQ", "20260501", 1100, "01/05 NQ RTH (perdant -248$)"),
        ("ES", "20260430", 1100, "30/04 ES RTH"),
        ("ES", "20260501", 1100, "01/05 ES RTH"),
        ("NQ", "20260428", 60, "28/04 NQ early Asia"),
    ]

    results = []
    print(f"{'LABEL':40s} | {'SYM':3s} | engine[mode|favor|vol] | dashboard[mode|favor|vol]")
    print("-" * 120)

    n_mode_match = 0
    n_favor_match = 0
    n_vol_match = 0

    for sym, date, idx, label in samples:
        try:
            r = compare_bar(sym, date, idx, label)
            results.append(r)
            mode_ok = r["engine_mode"] == r["dashboard_mode"]
            favor_ok = r["engine_favor"] == r["dashboard_favor"]
            vol_ok = r["engine_vol"] == r["dashboard_vol"]
            if mode_ok: n_mode_match += 1
            if favor_ok: n_favor_match += 1
            if vol_ok: n_vol_match += 1
            mode_icon = "✓" if mode_ok else "✗"
            favor_icon = "✓" if favor_ok else "✗"
            vol_icon = "✓" if vol_ok else "✗"
            print(f"{label:40s} | {sym:3s} | "
                  f"{r['engine_mode']:7s}|{r['engine_favor']:6s}|{r['engine_vol']:7s} {mode_icon}{favor_icon}{vol_icon} | "
                  f"{r['dashboard_mode']:7s}|{r['dashboard_favor']:6s}|{r['dashboard_vol']:7s} | "
                  f"votes: E={r['engine_trend_votes']}/{r['engine_range_votes']} D={r['dashboard_trend_votes']}/{r['dashboard_range_votes']}")
        except Exception as e:
            print(f"{label:40s} | ERROR: {e}")

    n = len(results)
    if n == 0:
        print("\nAucun test execute.")
        return 1

    pct_mode = n_mode_match / n * 100
    pct_favor = n_favor_match / n * 100
    pct_vol = n_vol_match / n * 100

    print()
    print(f"=== PARITE GLOBALE (8 bars) ===")
    print(f"  Mode match    : {n_mode_match}/{n} ({pct_mode:.0f}%)")
    print(f"  Favor match   : {n_favor_match}/{n} ({pct_favor:.0f}%)")
    print(f"  Vol match     : {n_vol_match}/{n} ({pct_vol:.0f}%)")
    print()
    # Seuils acceptable
    seuils = {"mode": 70, "favor": 60, "vol": 90}
    pass_mode = pct_mode >= seuils["mode"]
    pass_favor = pct_favor >= seuils["favor"]
    pass_vol = pct_vol >= seuils["vol"]
    if pass_mode and pass_favor and pass_vol:
        print(f"VERDICT : ✓ PASS (seuils mode>={seuils['mode']}% / favor>={seuils['favor']}% / vol>={seuils['vol']}%)")
        return 0
    else:
        print(f"VERDICT : ✗ FAIL (seuils mode>={seuils['mode']}% / favor>={seuils['favor']}% / vol>={seuils['vol']}%)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
