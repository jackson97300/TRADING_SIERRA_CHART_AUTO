"""Calibration empirique seuils slope_30 par decile.

Source de verite : DATA/live_enriched/sierra/{SYM}/{YYYYMMDD}_{SYM}_sierra_enriched.jsonl
Symbol : ES (5 jours) + NQ (4 jours)
Output : tableau decile slope_30 -> P(LONG perdant), EV LONG/SHORT, recommandation seuils.

Methodologie (cf market-analyst reco Bot MR Phase 2) :
  1. Pour chaque bar : slope_30 = bar["vwap_slope_30"]
  2. Calculer return_futur sur horizon_min bars suivants (1 bar = 1 min verifie empiriquement)
  3. Calculer MAE/MFE futur sur la meme fenetre
  4. Bucket par decile slope_30
  5. Pour chaque decile :
     - mean return, mean MAE, mean MFE (en ticks)
     - P(SL_hit) LONG = P(MAE <= -SL_TICKS)
     - P(TP_hit) LONG = P(MFE >= TP_TICKS)
     - EV_LONG = TP * P(TP) - SL * P(SL)
     - EV_SHORT (symetrique) = SL * P(MAE<=-SL_TICKS interprete TP SHORT) - TP * P(MFE>=TP_TICKS interprete SL SHORT)
       (symetrie approchee : on inverse les roles)
  6. Recommander :
     - SLOPE_30_MIN_LONG = slope_max du dernier decile avec EV_LONG < 0 (deciles bas)
     - SLOPE_30_MAX_SHORT = slope_min du premier decile (en partant du haut) avec EV_SHORT < 0

Usage :
  python -X utf8 CORE/research/calibrate_slope_30_buckets.py --symbol ES
  python -X utf8 CORE/research/calibrate_slope_30_buckets.py --symbol NQ
  python -X utf8 CORE/research/calibrate_slope_30_buckets.py --symbol ES --horizon-min 30 --sl-ticks 20 --tp-ticks 30
  python -X utf8 CORE/research/calibrate_slope_30_buckets.py --symbol ES --csv-out OUT.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Optional


def load_jsonl_day(path: Path) -> list[dict]:
    bars = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return bars


def compute_future_returns(bars: list[dict], horizon_min: int) -> list[dict]:
    """Pour chaque bar, calcule return + MAE + MFE futur sur horizon_min bars."""
    results = []
    n = len(bars)
    for i, bar in enumerate(bars):
        if i + horizon_min >= n:
            continue

        close_raw = bar.get("close")
        if close_raw is None:
            continue
        try:
            close_now = float(close_raw)
        except (TypeError, ValueError):
            continue
        if close_now <= 0:
            continue

        slope_raw = bar.get("vwap_slope_30")
        if slope_raw is None:
            continue
        try:
            slope_30 = float(slope_raw)
        except (TypeError, ValueError):
            continue

        # Future window : bars i+1 .. i+horizon_min inclus
        future_window = bars[i + 1 : i + 1 + horizon_min]
        if len(future_window) < horizon_min:
            continue

        future_closes = []
        future_lows = []
        future_highs = []
        for b in future_window:
            c_raw = b.get("close")
            l_raw = b.get("low", c_raw)
            h_raw = b.get("high", c_raw)
            try:
                c = float(c_raw)
                lo = float(l_raw) if l_raw is not None else c
                hi = float(h_raw) if h_raw is not None else c
            except (TypeError, ValueError):
                continue
            future_closes.append(c)
            future_lows.append(lo)
            future_highs.append(hi)

        if not future_closes:
            continue

        return_pts = future_closes[-1] - close_now
        mae_pts = min(future_lows) - close_now  # negatif si baisse intra-fenetre
        mfe_pts = max(future_highs) - close_now  # positif si hausse intra-fenetre

        results.append(
            {
                "bar_idx": i,
                "ts": bar.get("ts"),
                "session_id": bar.get("session_id"),
                "close": close_now,
                "slope_30": slope_30,
                "return_pts": return_pts,
                "mae_pts": mae_pts,
                "mfe_pts": mfe_pts,
            }
        )
    return results


def bucket_by_decile(records: list[dict], field: str = "slope_30") -> dict:
    """Bucket par decile sur le field. Retourne dict {decile: [records]}."""
    sorted_recs = sorted(records, key=lambda r: r[field])
    n = len(sorted_recs)
    if n == 0:
        return {}
    buckets = {i: [] for i in range(10)}
    for idx, rec in enumerate(sorted_recs):
        decile = min(9, int((idx / n) * 10))
        buckets[decile].append(rec)
    return buckets


def analyze_bucket(bucket: list[dict], tick_size: float, sl_ticks: int, tp_ticks: int) -> dict:
    """Stats pour un bucket : returns en ticks, EV LONG et SHORT."""
    if not bucket:
        return {"n": 0}

    slopes = [r["slope_30"] for r in bucket]
    returns_ticks = [r["return_pts"] / tick_size for r in bucket]
    mae_ticks = [r["mae_pts"] / tick_size for r in bucket]
    mfe_ticks = [r["mfe_pts"] / tick_size for r in bucket]

    n = len(bucket)

    # LONG side
    n_long_lose = sum(1 for r in returns_ticks if r < 0)
    n_sl_hit_long = sum(1 for m in mae_ticks if m <= -sl_ticks)  # MAE atteint SL down
    n_tp_hit_long = sum(1 for f in mfe_ticks if f >= tp_ticks)  # MFE atteint TP up
    p_tp_long = n_tp_hit_long / n
    p_sl_long = n_sl_hit_long / n
    ev_long_ticks = tp_ticks * p_tp_long - sl_ticks * p_sl_long

    # SHORT side (symetrique : MFE devient adversaire, MAE devient ami)
    # Trade SHORT : TP touche si MAE <= -TP_TICKS (baisse de TP) ; SL touche si MFE >= SL_TICKS (hausse de SL)
    n_tp_hit_short = sum(1 for m in mae_ticks if m <= -tp_ticks)
    n_sl_hit_short = sum(1 for f in mfe_ticks if f >= sl_ticks)
    p_tp_short = n_tp_hit_short / n
    p_sl_short = n_sl_hit_short / n
    ev_short_ticks = tp_ticks * p_tp_short - sl_ticks * p_sl_short

    return {
        "n": n,
        "slope_min": min(slopes),
        "slope_max": max(slopes),
        "slope_median": statistics.median(slopes),
        "return_mean_t": statistics.mean(returns_ticks),
        "mae_mean_t": statistics.mean(mae_ticks),
        "mfe_mean_t": statistics.mean(mfe_ticks),
        "p_long_lose": n_long_lose / n,
        "p_sl_hit_long": p_sl_long,
        "p_tp_hit_long": p_tp_long,
        "ev_long_ticks": ev_long_ticks,
        "p_sl_hit_short": p_sl_short,
        "p_tp_hit_short": p_tp_short,
        "ev_short_ticks": ev_short_ticks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ES", choices=["ES", "NQ"])
    parser.add_argument("--data-dir", default="DATA/live_enriched/sierra")
    parser.add_argument(
        "--horizon-min",
        type=int,
        default=30,
        help="Horizon futur en minutes (= nb bars, verifie 1 bar = 1 min)",
    )
    parser.add_argument("--sl-ticks", type=int, default=20)
    parser.add_argument("--tp-ticks", type=int, default=30)
    parser.add_argument("--csv-out", type=str, default=None, help="Export CSV stats par decile")
    args = parser.parse_args()

    tick_size = 0.25  # ES + NQ (cf CORE/constants.py)
    data_dir = Path(args.data_dir) / args.symbol
    pattern = f"*_{args.symbol}_sierra_enriched.jsonl"
    files = sorted(data_dir.glob(pattern))

    if not files:
        print(f"ABORT: aucun fichier {pattern} trouve dans {data_dir}")
        return

    print(f"Symbol     : {args.symbol}")
    print(f"Fichiers   : {[f.name for f in files]}")
    print(f"Horizon    : {args.horizon_min} min")
    print(f"SL         : {args.sl_ticks}t ({args.sl_ticks * tick_size:.2f} pts)")
    print(f"TP         : {args.tp_ticks}t ({args.tp_ticks * tick_size:.2f} pts)")
    print(f"RR         : {args.tp_ticks / args.sl_ticks:.2f}")
    print()

    # Charge tous les bars et calcul returns
    all_records = []
    for f in files:
        bars = load_jsonl_day(f)
        recs = compute_future_returns(bars, args.horizon_min)
        print(f"  {f.name}: {len(bars)} bars -> {len(recs)} records valides")
        all_records.extend(recs)

    print(f"\nTotal records : {len(all_records)}")
    if not all_records:
        print("ABORT: pas de records")
        return

    # Stats globales slope_30
    slopes = [r["slope_30"] for r in all_records]
    print("\nDistribution slope_30 (globale):")
    print(f"  min    = {min(slopes):+.4f}")
    print(f"  max    = {max(slopes):+.4f}")
    print(f"  median = {statistics.median(slopes):+.4f}")
    print(f"  mean   = {statistics.mean(slopes):+.4f}")
    print(f"  stdev  = {statistics.stdev(slopes):+.4f}")

    # Repartition par session_id
    from collections import Counter

    sess_counts = Counter(r["session_id"] for r in all_records)
    print(f"\nRecords par session : {dict(sess_counts)}")

    # Bucket par decile
    buckets = bucket_by_decile(all_records, "slope_30")

    print("\n" + "=" * 130)
    header = (
        f"{'Dec':3} {'slope_range':22} {'n':5} "
        f"{'ret_t':>7} {'mae_t':>7} {'mfe_t':>7} "
        f"{'P(lose)':>8} {'P(SLlong)':>9} {'P(TPlong)':>9} {'EVlong_t':>9} "
        f"{'P(SLshort)':>10} {'P(TPshort)':>10} {'EVshort_t':>10}"
    )
    print(header)
    print("=" * 130)

    bucket_stats = {}
    for dec in range(10):
        s = analyze_bucket(buckets[dec], tick_size, args.sl_ticks, args.tp_ticks)
        bucket_stats[dec] = s
        if s["n"] == 0:
            continue
        slope_range = f"[{s['slope_min']:+.3f},{s['slope_max']:+.3f}]"
        print(
            f"{dec:3} {slope_range:22} {s['n']:5} "
            f"{s['return_mean_t']:+7.1f} {s['mae_mean_t']:+7.1f} {s['mfe_mean_t']:+7.1f} "
            f"{s['p_long_lose']:8.1%} {s['p_sl_hit_long']:9.1%} {s['p_tp_hit_long']:9.1%} "
            f"{s['ev_long_ticks']:+9.1f} "
            f"{s['p_sl_hit_short']:10.1%} {s['p_tp_hit_short']:10.1%} "
            f"{s['ev_short_ticks']:+10.1f}"
        )

    # Export CSV
    if args.csv_out:
        out_path = Path(args.csv_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as fout:
            w = csv.writer(fout)
            w.writerow(
                [
                    "decile",
                    "n",
                    "slope_min",
                    "slope_max",
                    "slope_median",
                    "return_mean_t",
                    "mae_mean_t",
                    "mfe_mean_t",
                    "p_long_lose",
                    "p_sl_hit_long",
                    "p_tp_hit_long",
                    "ev_long_ticks",
                    "p_sl_hit_short",
                    "p_tp_hit_short",
                    "ev_short_ticks",
                ]
            )
            for dec in range(10):
                s = bucket_stats[dec]
                if s["n"] == 0:
                    continue
                w.writerow(
                    [
                        dec,
                        s["n"],
                        f"{s['slope_min']:.6f}",
                        f"{s['slope_max']:.6f}",
                        f"{s['slope_median']:.6f}",
                        f"{s['return_mean_t']:.4f}",
                        f"{s['mae_mean_t']:.4f}",
                        f"{s['mfe_mean_t']:.4f}",
                        f"{s['p_long_lose']:.4f}",
                        f"{s['p_sl_hit_long']:.4f}",
                        f"{s['p_tp_hit_long']:.4f}",
                        f"{s['ev_long_ticks']:.4f}",
                        f"{s['p_sl_hit_short']:.4f}",
                        f"{s['p_tp_hit_short']:.4f}",
                        f"{s['ev_short_ticks']:.4f}",
                    ]
                )
        print(f"\nCSV ecrit : {out_path}")

    print("\n" + "=" * 130)
    print("RECOMMANDATIONS SEUILS (data-driven Phase 2):")
    print("=" * 130)

    # LONG : on cherche TOUS les deciles avec EV<0 (non-monotone possible)
    # Strategie : flag deciles negatifs cote LONG, donner 2 options de seuil
    neg_long_deciles = []
    for dec in range(10):
        s = bucket_stats[dec]
        if s["n"] == 0:
            continue
        if s["ev_long_ticks"] < 0:
            neg_long_deciles.append((dec, s["slope_min"], s["slope_max"], s["ev_long_ticks"]))

    print("\nLONG side:")
    if neg_long_deciles:
        print(f"  Deciles EV_LONG<0 detectes : {[d[0] for d in neg_long_deciles]}")
        for dec, smin, smax, ev in neg_long_deciles:
            print(f"    decile {dec}: slope [{smin:+.4f},{smax:+.4f}] EV={ev:+.2f}t")
        # Variante A : seuil min = max slope du plus haut decile negatif consecutif depuis 0
        consecutive_low = []
        for dec, smin, smax, ev in neg_long_deciles:
            if not consecutive_low or dec == consecutive_low[-1][0] + 1:
                consecutive_low.append((dec, smin, smax, ev))
            else:
                break
        if consecutive_low and consecutive_low[0][0] == 0:
            thr_a = consecutive_low[-1][2]  # slope_max du dernier decile bas consecutif
            print(
                f"  Variante A (block deciles bas consecutifs 0..{consecutive_low[-1][0]}):"
                f" SLOPE_30_MIN_LONG = {thr_a:+.4f}"
            )
        else:
            print(
                "  Variante A : aucun decile bas (0..) avec EV<0 - pas de hard threshold bas"
            )

        # Variante B : pas de hard threshold (deciles negatifs disperses)
        print(
            "  Variante B : NoOp filtre hard (deciles EV<0 disperses, prefer ML/score)"
        )
    else:
        print("  Aucun decile EV_LONG<0 detecte - LONG OK sur toute la distribution")
        print("  >>> SLOPE_30_MIN_LONG : None recommande (pas de hard filter)")

    # SHORT : symetrique
    neg_short_deciles = []
    for dec in range(10):
        s = bucket_stats[dec]
        if s["n"] == 0:
            continue
        if s["ev_short_ticks"] < 0:
            neg_short_deciles.append((dec, s["slope_min"], s["slope_max"], s["ev_short_ticks"]))

    print("\nSHORT side:")
    if neg_short_deciles:
        print(f"  Deciles EV_SHORT<0 detectes : {[d[0] for d in neg_short_deciles]}")
        for dec, smin, smax, ev in neg_short_deciles:
            print(f"    decile {dec}: slope [{smin:+.4f},{smax:+.4f}] EV={ev:+.2f}t")
        # Variante A : seuil max = min slope du plus bas decile negatif consecutif depuis 9
        consecutive_high = []
        for dec, smin, smax, ev in reversed(neg_short_deciles):
            if not consecutive_high or dec == consecutive_high[-1][0] - 1:
                consecutive_high.append((dec, smin, smax, ev))
            else:
                break
        if consecutive_high and consecutive_high[0][0] == 9:
            thr_a = consecutive_high[-1][1]
            print(
                f"  Variante A (block deciles hauts consecutifs {consecutive_high[-1][0]}..9):"
                f" SLOPE_30_MAX_SHORT = {thr_a:+.4f}"
            )
        else:
            print(
                "  Variante A : aucun decile haut (..9) avec EV<0 - pas de hard threshold haut"
            )
        print(
            "  Variante B : NoOp filtre hard (deciles EV<0 disperses, prefer ML/score)"
        )
    else:
        print("  Aucun decile EV_SHORT<0 detecte - SHORT OK sur toute la distribution")
        print("  >>> SLOPE_30_MAX_SHORT : None recommande (pas de hard filter)")

    optimal_threshold_long = None
    optimal_threshold_short = None
    # Pour le block "Comparaison Phase 1" ci-dessous, on tente l'utilisation Variante A si applicable
    if neg_long_deciles:
        cons = []
        for dec, smin, smax, ev in neg_long_deciles:
            if not cons or dec == cons[-1][0] + 1:
                cons.append((dec, smin, smax, ev))
            else:
                break
        if cons and cons[0][0] == 0:
            optimal_threshold_long = cons[-1][2]
    if neg_short_deciles:
        cons = []
        for dec, smin, smax, ev in reversed(neg_short_deciles):
            if not cons or dec == cons[-1][0] - 1:
                cons.append((dec, smin, smax, ev))
            else:
                break
        if cons and cons[0][0] == 9:
            optimal_threshold_short = cons[-1][1]

    # Comparaison avec Phase 1 actuelle
    print("\n" + "-" * 80)
    print("Comparaison Phase 1 actuelle (SLOPE_30_MIN_LONG=-0.3, SLOPE_30_MAX_SHORT=+0.3) :")
    n_blocked_long_phase1 = sum(1 for r in all_records if r["slope_30"] < -0.3)
    n_blocked_short_phase1 = sum(1 for r in all_records if r["slope_30"] > 0.3)
    pct_blk_long_p1 = 100.0 * n_blocked_long_phase1 / len(all_records)
    pct_blk_short_p1 = 100.0 * n_blocked_short_phase1 / len(all_records)
    print(f"  Phase 1 block LONG  : {n_blocked_long_phase1}/{len(all_records)} ({pct_blk_long_p1:.1f}%)")
    print(f"  Phase 1 block SHORT : {n_blocked_short_phase1}/{len(all_records)} ({pct_blk_short_p1:.1f}%)")

    if optimal_threshold_long is not None:
        n_blocked_long_phase2 = sum(1 for r in all_records if r["slope_30"] < optimal_threshold_long)
        pct_blk_long_p2 = 100.0 * n_blocked_long_phase2 / len(all_records)
        print(f"  Phase 2 block LONG  : {n_blocked_long_phase2}/{len(all_records)} ({pct_blk_long_p2:.1f}%)")

    if optimal_threshold_short is not None:
        n_blocked_short_phase2 = sum(1 for r in all_records if r["slope_30"] > optimal_threshold_short)
        pct_blk_short_p2 = 100.0 * n_blocked_short_phase2 / len(all_records)
        print(f"  Phase 2 block SHORT : {n_blocked_short_phase2}/{len(all_records)} ({pct_blk_short_p2:.1f}%)")


if __name__ == "__main__":
    main()
