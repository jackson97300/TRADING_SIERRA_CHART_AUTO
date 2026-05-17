"""Audit empirique Bot 2 V6 — winners vs losers (Etape 2 Bot 2 V7).

CONTEXTE :
- Bot 2 V6 a tradé 26 trades sur 11-15/05/2026 : WR ~55%, +586t net
- 11/05 BEST DAY : 7 trades +338t (5W 1L) PF~6.7
- 12/05 MARGINAL : 8 trades +15t (4W 4L) PF~1.07
- Edge identifie mais 100% fallback DMP (V4 stale 5 jours)

OBJECTIF :
Identifier les rules/features qui DIFFERENCIENT empiriquement les wins vs losses.
Plus precisement : sur 7 jours, quelles features bias_v6/regime/MTF/SLTP/conseil
ont les meilleures predictives pour le PnL ?

METHODE :
1. Charger trades + snapshots 11-15/05
2. Match par signal_id
3. Calculer stats par groupe (WIN >0t / LOSS <=0t) :
   - mean/median/std des features critiques
   - distributions par bucket (regime_favor, sl_tier, wall type)
4. Identifier top N features avec ecart WIN-LOSS significatif
5. Cross-check avec rules cartographie Etape 1 (62 rules)

OUTPUT : rapport markdown synthese pour Etape 3 (mapping features V4).
"""
from __future__ import annotations

import json
import glob
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DATA_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")


def load_v6_trades(days: list[str]) -> list[dict]:
    """Charge les trades V6 ferme pour les jours donnes."""
    trades = []
    for day in days:
        fp = DATA_DIR / f"{day}_v6_trades.jsonl"
        if not fp.exists():
            continue
        with fp.open(encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                    t["_day"] = day
                    trades.append(t)
                except json.JSONDecodeError:
                    pass
    return trades


def load_v6_snapshots(days: list[str]) -> dict:
    """Charge les snapshots V6 (a l'entry) indexe par signal_id."""
    by_signal_id = {}
    for day in days:
        fp = DATA_DIR / f"{day}_v6_snapshots.jsonl"
        if not fp.exists():
            continue
        with fp.open(encoding="utf-8") as f:
            for line in f:
                try:
                    s = json.loads(line)
                    by_signal_id[s["signal_id"]] = s
                except (json.JSONDecodeError, KeyError):
                    pass
    return by_signal_id


def join_trades_with_snapshots(trades: list[dict], snapshots: dict) -> list[dict]:
    """Joint chaque trade avec son snapshot (signal_id matching) + tag W/L."""
    joined = []
    missing_snap = 0
    for t in trades:
        sid = t.get("signal_id")
        snap = snapshots.get(sid)
        if not snap:
            missing_snap += 1
            continue
        # Tag outcome
        pnl_t = t.get("pnl_ticks") or 0
        outcome = "WIN" if pnl_t > 0 else "LOSS"
        # Merge
        merged = {**t}
        merged["_snap"] = snap
        merged["_outcome"] = outcome
        merged["_pnl_ticks"] = pnl_t
        joined.append(merged)
    if missing_snap:
        print(f"  WARN: {missing_snap} trades sans snapshot match")
    return joined


def extract_feature(snap: dict, key: str, default: Any = None) -> Any:
    """Extrait feature : 1er essai top-level, sinon dmp_bar nested."""
    if key in snap:
        return snap[key]
    return snap.get("dmp_bar", {}).get(key, default)


# Features critiques a auditer (extraites de la cartographie Etape 1)
FEATURES_AUDIT = {
    # Signal source
    "confidence": "top",
    "mtf_bulls": "top",
    "mtf_bears": "top",
    "freshness": "top",
    "conseil_action": "top",
    "conseil_bull_pts": "top",
    "conseil_bear_pts": "top",
    # SLTP wall-aware
    "sl_tier": "top",
    "sl_wall": "top",
    "tp_wall": "top",
    "rr_ratio": "top",
    "sl_ticks": "top",
    "tp_ticks": "top",
    "expected_payoff_usd": "top",
    "wr_dynamic_used": "top",
    # DMP bar features (regime + bias raw inputs)
    "range_pos": "bar",
    "dist_vwap_d": "bar",
    "dist_vwap_d_atr": "bar",
    "vwap_d_side": "bar",
    "vwap_w_side": "bar",
    "vwap_m_side": "bar",
    "vwap_slope_10": "bar",
    "delta_day_dir": "bar",
    "delta_pct": "bar",
    "cvd_day_dir": "bar",
    "bars_in_va": "bar",
    "inside_cur_va": "bar",
    "vix_level": "bar",
    "vix_regime": "bar",
    "momentum_3b": "bar",
    "momentum_5b": "bar",
    "cvd_bar_delta": "bar",
    "atr_14m": "bar",
    "next_wall_dist_ticks": "bar",
    "ib_position_pct": "bar",
    "session_id": "bar",
    "day_type": "bar",
    "open_type": "bar",
    "profile_shape": "bar",
    "trend_day_probability": "bar",
}


def compute_stats(joined: list[dict]) -> dict:
    """Calcule stats par outcome (WIN/LOSS) pour chaque feature audite."""
    wins = [j for j in joined if j["_outcome"] == "WIN"]
    losses = [j for j in joined if j["_outcome"] == "LOSS"]

    print(f"\nTotal trades joinable: {len(joined)}")
    print(f"  WINS : {len(wins)}")
    print(f"  LOSSES: {len(losses)}")
    print(f"  WR    : {len(wins)/max(1,len(joined))*100:.1f}%")
    print(f"  PnL_t : WINS={sum(j['_pnl_ticks'] for j in wins):+.0f}t, LOSSES={sum(j['_pnl_ticks'] for j in losses):+.0f}t")

    stats = {}
    for feat, loc in FEATURES_AUDIT.items():
        win_vals = []
        loss_vals = []
        for j in joined:
            snap = j["_snap"]
            v = extract_feature(snap, feat)
            if v is None:
                continue
            if j["_outcome"] == "WIN":
                win_vals.append(v)
            else:
                loss_vals.append(v)

        if not win_vals and not loss_vals:
            continue

        # Numerical features
        if win_vals and isinstance(win_vals[0], (int, float)) and not isinstance(win_vals[0], bool):
            win_arr = [float(v) for v in win_vals]
            loss_arr = [float(v) for v in loss_vals]
            stats[feat] = {
                "type": "numeric",
                "win_n": len(win_arr),
                "win_mean": round(sum(win_arr) / len(win_arr), 3) if win_arr else None,
                "win_median": round(sorted(win_arr)[len(win_arr) // 2], 3) if win_arr else None,
                "loss_n": len(loss_arr),
                "loss_mean": round(sum(loss_arr) / len(loss_arr), 3) if loss_arr else None,
                "loss_median": round(sorted(loss_arr)[len(loss_arr) // 2], 3) if loss_arr else None,
            }
            if stats[feat]["win_mean"] is not None and stats[feat]["loss_mean"] is not None:
                stats[feat]["delta_mean"] = round(stats[feat]["win_mean"] - stats[feat]["loss_mean"], 3)
        else:
            # Categorical features
            win_dist = Counter(win_vals)
            loss_dist = Counter(loss_vals)
            stats[feat] = {
                "type": "categorical",
                "win_n": len(win_vals),
                "win_top": win_dist.most_common(3),
                "loss_n": len(loss_vals),
                "loss_top": loss_dist.most_common(3),
            }

    return stats


def print_top_differentiators(stats: dict, top_n: int = 15):
    """Affiche le top N features avec ecart WIN-LOSS le plus significatif."""
    # Pour les numeric, score = |delta_mean| / (max(|win_mean|, 1) ou |loss_mean|)
    numeric_scores = []
    for feat, s in stats.items():
        if s["type"] != "numeric":
            continue
        delta = s.get("delta_mean")
        if delta is None or s["win_mean"] is None or s["loss_mean"] is None:
            continue
        # Score relatif : ecart normalise par max absolu
        denom = max(abs(s["win_mean"]), abs(s["loss_mean"]), 0.1)
        score = abs(delta) / denom
        numeric_scores.append((feat, score, delta, s["win_mean"], s["loss_mean"]))

    numeric_scores.sort(key=lambda x: x[1], reverse=True)
    print(f"\n{'=' * 90}\n  TOP {top_n} FEATURES DIFFERENCIATING WIN vs LOSS (numeric)\n{'=' * 90}")
    print(f"{'Feature':30s} {'Score%':>8s} {'Delta':>9s} {'Win_mean':>11s} {'Loss_mean':>11s}")
    for feat, score, delta, wm, lm in numeric_scores[:top_n]:
        print(f"{feat:30s} {score*100:>7.1f}% {delta:>+9.3f} {wm:>11.3f} {lm:>11.3f}")

    # Categorical : distribution top
    print(f"\n{'=' * 90}\n  CATEGORICAL FEATURES (top distributions)\n{'=' * 90}")
    for feat, s in stats.items():
        if s["type"] != "categorical":
            continue
        wt = s["win_top"]
        lt = s["loss_top"]
        if not wt or not lt:
            continue
        print(f"\n{feat:30s}")
        print(f"  WINS  ({s['win_n']:3d}): {wt}")
        print(f"  LOSSES({s['loss_n']:3d}): {lt}")


def main():
    days = ["20260511", "20260512", "20260513", "20260514", "20260515"]
    print(f"=== AUDIT Bot 2 V6 — winners vs losers ===")
    print(f"Days: {days}")

    trades = load_v6_trades(days)
    snapshots = load_v6_snapshots(days)
    print(f"\nLoaded: {len(trades)} trades, {len(snapshots)} snapshots")

    joined = join_trades_with_snapshots(trades, snapshots)

    stats = compute_stats(joined)
    print_top_differentiators(stats)

    # PnL par jour breakdown
    print(f"\n{'=' * 90}\n  PnL PAR JOUR (cross-check vs analyse precedente)\n{'=' * 90}")
    by_day = defaultdict(list)
    for j in joined:
        by_day[j["_day"]].append(j)
    for day in sorted(by_day.keys()):
        ts = by_day[day]
        wins = [t for t in ts if t["_outcome"] == "WIN"]
        losses = [t for t in ts if t["_outcome"] == "LOSS"]
        pnl = sum(t["_pnl_ticks"] for t in ts)
        print(f"  {day}  N={len(ts):3d}  W={len(wins)} L={len(losses)}  PnL={pnl:+7.1f}t  WR={len(wins)/max(1,len(ts))*100:5.1f}%")


if __name__ == "__main__":
    main()
