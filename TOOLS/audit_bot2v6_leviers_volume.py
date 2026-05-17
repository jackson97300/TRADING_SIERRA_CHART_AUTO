"""Backtest empirique 2 leviers volume Bot 2 V6 (Jackson 17/05).

OBJECTIF :
Valider/invalider l'impact des 2 leviers sur l'EDGE actuel :
- Lever 1 : freshness_required NEW -> NEW + PERSISTENT
- Lever 2 : min_confidence 0.50 -> 0.45

METHODE :
Sur les 26 trades V6 existants (11-15/05), bucket par freshness + confidence
et mesurer PnL/PF/WR. Pas un vrai backtest forward (besoin signaux rejected
pour cela) mais analyse retrospective des trades effectivement pris.

LIMITES (importantes) :
- N=26 = ECHANTILLON FAIBLE pour conclusions statistiques (cf market-analyst
  Etape 3 : recommande N>=100 + walk-forward 12-fold + DSR Lopez Bonferroni).
- Pas de visibilite sur signaux rejected = on peut SEULEMENT mesurer le bucket
  des trades pris, pas le PnL des trades qui auraient ete pris en plus.
- Resultats = INDICATION, pas validation. Decision finale = backtest 4 sem
  apres collecte V4 fresh.

OUTPUT : tableaux markdown pour Jackson, identification edge/dilution.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
DAYS = ["20260511", "20260512", "20260513", "20260514", "20260515"]


def load_v6_trades_with_snapshots() -> list[dict]:
    """Joint trades V6 fermes avec snapshots entry pour features."""
    snapshots = {}
    for day in DAYS:
        fp = DATA_DIR / f"{day}_v6_snapshots.jsonl"
        if not fp.exists():
            continue
        with fp.open(encoding="utf-8") as f:
            for line in f:
                try:
                    s = json.loads(line)
                    snapshots[s["signal_id"]] = s
                except Exception:
                    pass

    joined = []
    for day in DAYS:
        fp = DATA_DIR / f"{day}_v6_trades.jsonl"
        if not fp.exists():
            continue
        with fp.open(encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                    snap = snapshots.get(t.get("signal_id"))
                    if not snap:
                        continue
                    pnl = t.get("pnl_ticks") or 0
                    joined.append({
                        "day": day,
                        "trade_id": t.get("trade_id"),
                        "signal_id": t.get("signal_id"),
                        "symbol": t.get("symbol"),
                        "direction": t.get("direction"),
                        "pnl_ticks": pnl,
                        "pnl_usd": t.get("pnl_usd"),
                        "outcome": "WIN" if pnl > 0 else "LOSS",
                        "freshness": snap.get("freshness"),
                        "confidence": snap.get("confidence"),
                        "mtf_bulls": snap.get("mtf_bulls"),
                        "mtf_bears": snap.get("mtf_bears"),
                    })
                except Exception:
                    pass
    return joined


def compute_pf(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses == 0:
        return float("inf") if wins > 0 else 0
    return round(wins / losses, 2)


def stat(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    pnls = [t["pnl_ticks"] for t in trades]
    wins = [t for t in trades if t["outcome"] == "WIN"]
    return {
        "label": label,
        "n": len(trades),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "pnl_sum": round(sum(pnls), 1),
        "pnl_mean": round(sum(pnls) / len(trades), 2),
        "pf": compute_pf(pnls),
    }


def main():
    trades = load_v6_trades_with_snapshots()
    print(f"=== BACKTEST 2 LEVIERS VOLUME Bot 2 V6 (17/05) ===")
    print(f"Trades V6 11-15/05 : {len(trades)}")
    print()

    # -----------------------------------------------------
    # LEVER 1 : freshness NEW vs PERSISTENT vs other
    # -----------------------------------------------------
    print("=" * 70)
    print("LEVER 1 — freshness NEW vs PERSISTENT")
    print("=" * 70)
    by_fresh = defaultdict(list)
    for t in trades:
        by_fresh[t["freshness"] or "MISSING"].append(t)

    rows = []
    for fresh in ["NEW", "PERSISTENT"]:
        ts = by_fresh.get(fresh, [])
        s = stat(ts, fresh)
        rows.append(s)
    # Combined NEW+PERSISTENT vs all
    combined = by_fresh.get("NEW", []) + by_fresh.get("PERSISTENT", [])
    rows.append(stat(combined, "NEW+PERSISTENT (lever 1 ON)"))
    rows.append(stat(by_fresh.get("NEW", []), "NEW seul (actuel)"))

    print(f"{'Bucket':35s} {'N':>4s} {'WR%':>7s} {'PnL_sum':>9s} {'PnL_mean':>9s} {'PF':>6s}")
    for s in rows:
        if s["n"] == 0:
            continue
        print(f"{s['label']:35s} {s['n']:>4d} {s['wr']:>6.1f}% {s['pnl_sum']:>+9.1f} {s['pnl_mean']:>+9.2f} {s['pf']:>6}")

    # Compare delta WR / PF / PnL/trade entre NEW seul vs NEW+PERSISTENT
    new_only = stat(by_fresh.get("NEW", []), "NEW")
    combined_s = stat(combined, "COMBINED")
    if new_only["n"] > 0 and combined_s["n"] > 0:
        print()
        print(f"DELTA (combined vs NEW seul):")
        print(f"  N x{combined_s['n']/new_only['n']:.2f}  WR {combined_s['wr']-new_only['wr']:+.1f}pp  "
              f"PnL/trade {combined_s['pnl_mean']-new_only['pnl_mean']:+.2f}t  "
              f"PF {combined_s['pf']-new_only['pf']:+.2f}")

    # -----------------------------------------------------
    # LEVER 2 : confidence buckets
    # -----------------------------------------------------
    print()
    print("=" * 70)
    print("LEVER 2 — confidence buckets (threshold actuel 0.50, proposed 0.45)")
    print("=" * 70)
    # Buckets : [0.40-0.45), [0.45-0.50), [0.50-0.60), [0.60-0.75), [0.75+)
    buckets = {
        "<0.45": (0, 0.45),
        "0.45-0.50 (NEW si lever 2 ON)": (0.45, 0.50),
        "0.50-0.60": (0.50, 0.60),
        "0.60-0.75": (0.60, 0.75),
        ">=0.75": (0.75, 999),
    }
    print(f"{'Bucket':40s} {'N':>4s} {'WR%':>7s} {'PnL_sum':>9s} {'PnL_mean':>9s} {'PF':>6s}")
    for label, (lo, hi) in buckets.items():
        ts = [t for t in trades if t["confidence"] is not None and lo <= t["confidence"] < hi]
        s = stat(ts, label)
        if s["n"] == 0:
            print(f"{label:40s} {s['n']:>4d}   N/A")
        else:
            print(f"{label:40s} {s['n']:>4d} {s['wr']:>6.1f}% {s['pnl_sum']:>+9.1f} {s['pnl_mean']:>+9.2f} {s['pf']:>6}")

    # Cumul : >= 0.45 (lever 2 ON) vs >= 0.50 (actuel)
    print()
    lever_on = [t for t in trades if t["confidence"] is not None and t["confidence"] >= 0.45]
    lever_off = [t for t in trades if t["confidence"] is not None and t["confidence"] >= 0.50]
    s_on = stat(lever_on, ">=0.45 (lever 2 ON)")
    s_off = stat(lever_off, ">=0.50 (actuel)")
    print(f"{s_on['label']:40s} N={s_on['n']:3d} WR={s_on['wr']:5.1f}% PnL_sum={s_on['pnl_sum']:+7.1f} PnL_mean={s_on['pnl_mean']:+6.2f} PF={s_on['pf']}")
    print(f"{s_off['label']:40s} N={s_off['n']:3d} WR={s_off['wr']:5.1f}% PnL_sum={s_off['pnl_sum']:+7.1f} PnL_mean={s_off['pnl_mean']:+6.2f} PF={s_off['pf']}")
    if s_on["n"] > s_off["n"]:
        marginal_n = s_on["n"] - s_off["n"]
        marginal_pnl = s_on["pnl_sum"] - s_off["pnl_sum"]
        marginal_pnl_mean = marginal_pnl / marginal_n if marginal_n > 0 else 0
        print(f"\nMARGINAL [0.45-0.50) : N={marginal_n}  PnL={marginal_pnl:+.1f}t  PnL_mean={marginal_pnl_mean:+.2f}t/trade")

    # -----------------------------------------------------
    # COMBINE LEVER 1 + LEVER 2
    # -----------------------------------------------------
    print()
    print("=" * 70)
    print("COMBINE LEVER 1 + LEVER 2")
    print("=" * 70)
    actuel = [t for t in trades if t["freshness"] == "NEW" and t["confidence"] and t["confidence"] >= 0.50]
    plus_lever1 = [t for t in trades if t["freshness"] in ("NEW", "PERSISTENT") and t["confidence"] and t["confidence"] >= 0.50]
    plus_lever2 = [t for t in trades if t["freshness"] == "NEW" and t["confidence"] and t["confidence"] >= 0.45]
    plus_both = [t for t in trades if t["freshness"] in ("NEW", "PERSISTENT") and t["confidence"] and t["confidence"] >= 0.45]
    rows = [
        stat(actuel, "Actuel (NEW + conf>=0.50)"),
        stat(plus_lever1, "+Lever1 (NEW+PERSISTENT + conf>=0.50)"),
        stat(plus_lever2, "+Lever2 (NEW + conf>=0.45)"),
        stat(plus_both,   "+Lever1+2 (NEW+PERSISTENT + conf>=0.45)"),
    ]
    print(f"{'Scenario':45s} {'N':>4s} {'WR%':>7s} {'PnL_sum':>9s} {'PnL_mean':>9s} {'PF':>6s}")
    for s in rows:
        if s["n"] == 0:
            print(f"{s['label']:45s} N=0")
            continue
        print(f"{s['label']:45s} {s['n']:>4d} {s['wr']:>6.1f}% {s['pnl_sum']:>+9.1f} {s['pnl_mean']:>+9.2f} {s['pf']:>6}")

    # -----------------------------------------------------
    # VERDICT
    # -----------------------------------------------------
    print()
    print("=" * 70)
    print("VERDICT (limites : N=26 = INDICATION uniquement, pas validation stat)")
    print("=" * 70)
    actuel_s = stat(actuel, "")
    both_s = stat(plus_both, "")
    if actuel_s["n"] > 0 and both_s["n"] > actuel_s["n"]:
        delta_n = both_s["n"] - actuel_s["n"]
        delta_pf = both_s["pf"] - actuel_s["pf"]
        delta_pnl = both_s["pnl_sum"] - actuel_s["pnl_sum"]
        print(f"+Lever1+2 vs Actuel : N+{delta_n} (+{delta_n/max(1,actuel_s['n'])*100:.0f}%) "
              f"PF {delta_pf:+.2f}  PnL_total {delta_pnl:+.1f}t")
        if delta_pf < 0:
            print(f"  ⚠ DILUTION : PF baisse {delta_pf:+.2f}. RISQUE edge degrade.")
        else:
            print(f"  ✓ Pas de dilution edge (PF stable ou augmente)")


if __name__ == "__main__":
    main()
