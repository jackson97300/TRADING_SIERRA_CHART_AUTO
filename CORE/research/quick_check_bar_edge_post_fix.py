"""Quick check post-fix config EDGE ZONES IMBALANCE 600%DIAG sur NQ.

Apres harmonisation NQ (activation 600%DIAG + hide rev8 0DIAG), ce script
verifie empiriquement que bar_edge_buy/sell NQ passe de 75% fire a ~15%
(comme ES).

Usage : dès que 30+ barres sont arrivees post-fix (ouverture Asia 18:00 ET)
  python -X utf8 CORE/research/quick_check_bar_edge_post_fix.py

Outputs :
  - Fire rate bar_edge_buy/sell par sym sur les N dernieres barres
  - XOR / BOTH ratio (discriminance)
  - Verdict : GREEN (fix reussi), YELLOW (partiel), RED (fix rate)
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "DATA"


def load_recent_bars(symbol: str, n_bars: int = 100):
    """Charge les N dernieres barres JSONL disponibles."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    fp = DATA_DIR / symbol / f"{date_str}_{symbol}.jsonl"
    if not fp.exists():
        # Fallback derniere date disponible
        import glob
        files = sorted(glob.glob(str(DATA_DIR / symbol / f"*_{symbol}.jsonl")))
        if not files:
            return []
        fp = Path(files[-1])
    rows = []
    with fp.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return rows[-n_bars:]


def audit(bars, symbol, label=""):
    n = len(bars)
    if n == 0:
        print(f"  [{symbol} {label}] Aucune barre disponible")
        return None

    # Extract features
    edge_buy = [b.get("bar_edge_buy", 0) or 0 for b in bars]
    edge_sell = [b.get("bar_edge_sell", 0) or 0 for b in bars]

    fire_buy = sum(1 for v in edge_buy if v == 1)
    fire_sell = sum(1 for v in edge_sell if v == 1)
    both = sum(1 for b, s in zip(edge_buy, edge_sell) if b == 1 and s == 1)
    xor = sum(1 for b, s in zip(edge_buy, edge_sell) if (b == 1) != (s == 1))
    neither = sum(1 for b, s in zip(edge_buy, edge_sell) if b == 0 and s == 0)

    # Timestamps
    ts_first = bars[0].get("ts", 0) / 1000
    ts_last = bars[-1].get("ts", 0) / 1000
    dt_first = datetime.fromtimestamp(ts_first, tz=timezone.utc)
    dt_last = datetime.fromtimestamp(ts_last, tz=timezone.utc)

    print(f"  [{symbol} {label}] N={n} bars | {dt_first.strftime('%H:%M')}-{dt_last.strftime('%H:%M')} UTC")
    print(f"    bar_edge_buy  fire : {100*fire_buy/n:5.1f}% ({fire_buy}/{n})")
    print(f"    bar_edge_sell fire : {100*fire_sell/n:5.1f}% ({fire_sell}/{n})")
    print(f"    BOTH simultane     : {100*both/n:5.1f}% ({both}/{n})  <- devrait etre < 10%")
    print(f"    XOR discriminant   : {100*xor/n:5.1f}% ({xor}/{n})")
    print(f"    NEITHER            : {100*neither/n:5.1f}% ({neither}/{n})")

    return {
        "n": n,
        "fire_buy_pct": 100 * fire_buy / n,
        "fire_sell_pct": 100 * fire_sell / n,
        "both_pct": 100 * both / n,
        "xor_pct": 100 * xor / n,
    }


def verdict(nq_stats):
    """Verdict GREEN/YELLOW/RED selon fire rate NQ post-fix."""
    if nq_stats is None:
        return "UNKNOWN"
    fire = (nq_stats["fire_buy_pct"] + nq_stats["fire_sell_pct"]) / 2
    both = nq_stats["both_pct"]

    if fire < 30 and both < 15:
        return "GREEN"  # Fix reussi, NQ comportement comme ES
    elif fire < 50 and both < 30:
        return "YELLOW"  # Amelioration partielle, a surveiller 24h
    else:
        return "RED"  # Pas d'effet, bug ailleurs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-bars", type=int, default=100, help="Derniers N bars (default 100)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"QUICK CHECK — bar_edge_buy/sell post-fix NQ 600%DIAG")
    print(f"Fenetre : {args.n_bars} dernieres barres live")
    print("=" * 70)

    es_bars = load_recent_bars("ES", args.n_bars)
    nq_bars = load_recent_bars("NQ", args.n_bars)

    print("\n=== ES (controle, inchange) ===")
    es_stats = audit(es_bars, "ES", "controle")

    print("\n=== NQ (test post-fix) ===")
    nq_stats = audit(nq_bars, "NQ", "test")

    v = verdict(nq_stats)
    print(f"\n{'=' * 70}")
    print(f"VERDICT : {v}")
    print(f"{'=' * 70}")
    if v == "GREEN":
        print("  NQ comportement aligne sur ES. Fix valide.")
        print("  Action suivante : laisser tourner 7 jours + re-audit complet.")
    elif v == "YELLOW":
        print("  Amelioration visible mais pas complete.")
        print("  Check : Short Name etude NQ = 'EDGE_BUY' exact ?")
    else:
        print("  Pas d'effet. Bug probable :")
        print("    1. DMP C++ cache les vieux IDs (restart DMP requis ?)")
        print("    2. Short Name ne matche pas 'EDGE_BUY' sur NQ")
        print("    3. Autre etude prend la priorite (ambiguite matching)")


if __name__ == "__main__":
    main()
