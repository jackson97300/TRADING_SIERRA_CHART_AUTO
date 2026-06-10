"""backtest_signatures_bot2.py — Backtest empirique 12 signatures sur trades passes Bot 2.

Usage : python -X utf8 CORE/backtest_signatures_bot2.py

Pour chaque trade dans `DATA/PAPER_TRADES/*_databento_trades.jsonl` :
  1. Extract `features_at_entry` (366 features capturees au moment du trade)
  2. Compute les 12 signatures via signatures.compute_all()
  3. Stocker resultat avec outcome (TP/SL/TIMEOUT) + pnl_ticks

Output :
  1. Console : table WIN vs LOSS pour chaque signature (presence %)
  2. CSV : DATA/BACKTEST/signatures_bot2_{date}.csv (trace complete)
  3. JSONL : DATA/BACKTEST/signatures_bot2_{date}.jsonl (logs structures)
  4. Recommendations Tier A/B/C basees sur le power discriminant

POC sur 13 trades du 29/04 (n=13 = limite). Si pattern visible meme avec
n petit, on aura une indication. Validation walk-forward sur trades futurs.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from CORE import signatures

PAPER_DIR = ROOT / "DATA" / "PAPER_TRADES"
OUTPUT_DIR = ROOT / "DATA" / "BACKTEST"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_trades_bot2() -> list[dict]:
    """Load tous les trades.jsonl Bot 2 (databento_paper)."""
    trades = []
    for fp in sorted(PAPER_DIR.glob("*_databento_trades.jsonl")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        trades.append(json.loads(s))
                    except json.JSONDecodeError:
                        pass
        except OSError as e:
            print(f"WARN read {fp} : {e}")
    return trades


def categorize_outcome(trade: dict) -> str:
    """Categorize trade outcome : WIN / LOSS / FLAT."""
    pnl = trade.get("pnl_ticks", 0) or 0
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "FLAT"


def main():
    print("=" * 80)
    print("  BACKTEST SIGNATURES BOT 2 — 12 game changers vs trades reels")
    print("=" * 80)

    trades = load_trades_bot2()
    print(f"\nN trades charges : {len(trades)}")
    if not trades:
        print("FATAL : aucun trade trouve")
        sys.exit(1)

    # Filter trades with features_at_entry
    trades_with_feat = [t for t in trades if isinstance(t.get("features_at_entry"), dict)]
    print(f"N trades avec features_at_entry : {len(trades_with_feat)}")
    if not trades_with_feat:
        print("FATAL : aucun trade avec features_at_entry (probable trades pre-instrumentation)")
        sys.exit(2)

    # Aggregate stats per signature
    # Format : sig_name → {WIN: count, LOSS: count, total_WIN: count, total_LOSS: count}
    stats = defaultdict(lambda: {"present_WIN": 0, "present_LOSS": 0,
                                  "total_WIN": 0, "total_LOSS": 0})

    detail_rows = []  # pour CSV detail
    log_lines = []    # pour JSONL trace

    for t in trades_with_feat:
        feat = t["features_at_entry"]
        outcome = categorize_outcome(t)
        if outcome == "FLAT":
            continue  # ignore les pnl=0 (rare)

        direction = (t.get("direction") or "").upper()
        sig_dir = "LONG" if "LONG" in direction or direction == "BUY" else "SHORT"

        signals = signatures.compute_all(feat, direction=sig_dir)
        score = signatures.overall_score(signals)

        # Update stats
        for sig_name, present in signals.items():
            stats[sig_name][f"total_{outcome}"] += 1
            if present:
                stats[sig_name][f"present_{outcome}"] += 1

        # Detail row
        row = {
            "entry_time": t.get("entry_time", ""),
            "symbol": t.get("symbol", ""),
            "direction": direction,
            "outcome": outcome,
            "pnl_ticks": t.get("pnl_ticks", 0),
            "pnl_usd": t.get("pnl_usd", 0),
            "tier1": score["tier1"],
            "tier2": score["tier2"],
            "tier3": score["tier3"],
            "total_score": score["total"],
        }
        for sig_name, present in signals.items():
            row[sig_name] = int(present)
        detail_rows.append(row)

        # JSONL log line
        log_lines.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "code": "SIGNATURES_BACKTEST_TRADE",
            "trade_id": t.get("parent_id", "?"),
            "entry_time": t.get("entry_time", ""),
            "symbol": t.get("symbol", ""),
            "direction": direction,
            "outcome": outcome,
            "pnl_ticks": t.get("pnl_ticks", 0),
            "signals": signals,
            "score": score,
        })

    # ── PRINT REPORT ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  STATS PAR SIGNATURE — % presence WIN vs LOSS")
    print("=" * 80)
    print(f"{'Signature':<20s} {'WIN':>10s} {'LOSS':>10s} {'Diff (pp)':>12s} {'Discriminant':>15s}")
    print("-" * 80)

    rankings = []  # (sig, win%, loss%, diff)
    for sig_name in signatures.ALL_SIGNATURES:
        s = stats[sig_name]
        win_pct = (s["present_WIN"] / s["total_WIN"] * 100) if s["total_WIN"] else 0
        loss_pct = (s["present_LOSS"] / s["total_LOSS"] * 100) if s["total_LOSS"] else 0
        diff = win_pct - loss_pct
        # Discriminant : favorable WIN >= +30pp, defavorable WIN <= -30pp
        if diff >= 30:
            verdict = "✓ TIER A?"
        elif diff >= 15:
            verdict = "~ TIER B?"
        elif diff <= -30:
            verdict = "✗ INVERSER"
        elif diff <= -15:
            verdict = "✗ FAIBLE"
        else:
            verdict = "  bruit"
        print(f"{sig_name:<20s} {win_pct:>9.1f}% {loss_pct:>9.1f}% {diff:>+11.1f}pp {verdict:>15s}")
        rankings.append((sig_name, win_pct, loss_pct, diff, verdict))

    # ── TOP TIER A candidats ──────────────────────────────────────
    print("\n" + "=" * 80)
    print("  RECOMMANDATION Tier A (signatures discriminantes WIN > LOSS +30pp)")
    print("=" * 80)
    tier_a = [r for r in rankings if r[3] >= 30]
    if tier_a:
        for sig, win, loss, diff, _ in sorted(tier_a, key=lambda x: -x[3]):
            print(f"  {sig:<20s} : WIN {win:.1f}% / LOSS {loss:.1f}% (diff {diff:+.1f}pp)")
    else:
        print("  AUCUNE signature avec >30pp de discrimination (n trop petit ou formules a revoir)")

    print("\n  Tier B candidates (WIN > LOSS +15pp) :")
    tier_b = [r for r in rankings if 15 <= r[3] < 30]
    for sig, win, loss, diff, _ in sorted(tier_b, key=lambda x: -x[3]):
        print(f"  {sig:<20s} : WIN {win:.1f}% / LOSS {loss:.1f}% (diff {diff:+.1f}pp)")

    print("\n  ✗ Signatures defavorables (presence sur LOSS > WIN) :")
    inverse = [r for r in rankings if r[3] < -15]
    for sig, win, loss, diff, _ in sorted(inverse, key=lambda x: x[3]):
        print(f"  {sig:<20s} : WIN {win:.1f}% / LOSS {loss:.1f}% (diff {diff:+.1f}pp)")

    # ── DISTRIBUTION SCORES TOTAL ─────────────────────────────────
    print("\n" + "=" * 80)
    print("  DISTRIBUTION SCORE TOTAL (somme 12 signatures)")
    print("=" * 80)
    score_dist = defaultdict(lambda: {"WIN": 0, "LOSS": 0})
    for row in detail_rows:
        score_dist[row["total_score"]][row["outcome"]] += 1
    print(f"{'Score':>6s} {'WIN':>6s} {'LOSS':>6s} {'WR%':>8s}")
    for score in sorted(score_dist.keys()):
        w = score_dist[score]["WIN"]
        l = score_dist[score]["LOSS"]
        wr = (w / (w + l) * 100) if (w + l) else 0
        print(f"{score:>6d} {w:>6d} {l:>6d} {wr:>7.1f}%")

    # ── EXPORT CSV + JSONL ────────────────────────────────────────
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    csv_path = OUTPUT_DIR / f"signatures_bot2_{today_str}.csv"
    if detail_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
            writer.writeheader()
            writer.writerows(detail_rows)
        print(f"\n  CSV detail   : {csv_path}")

    jsonl_path = OUTPUT_DIR / f"signatures_bot2_{today_str}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in log_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"  JSONL trace  : {jsonl_path}")

    # Verdict empirique global
    print("\n" + "=" * 80)
    print("  VERDICT EMPIRIQUE")
    print("=" * 80)
    n_trades = len(detail_rows)
    n_win = sum(1 for r in detail_rows if r["outcome"] == "WIN")
    n_loss = sum(1 for r in detail_rows if r["outcome"] == "LOSS")
    print(f"  N trades total    : {n_trades}")
    print(f"  N WIN / N LOSS    : {n_win} / {n_loss}")
    print(f"  WR global actuel  : {n_win/n_trades*100:.1f}%" if n_trades else "  N/A")
    if n_trades < 30:
        print(f"  ⚠️  n={n_trades} = LIMITE STATISTIQUE. Pattern detecte = INDICATIF, pas conclusif.")
        print(f"  → Walk-forward 30+ trades requis pour validation robuste.")
    print(f"\n  Tier A candidats  : {len(tier_a)}")
    print(f"  Tier B candidats  : {len(tier_b)}")
    print(f"  Inverses          : {len(inverse)}")


if __name__ == "__main__":
    main()
