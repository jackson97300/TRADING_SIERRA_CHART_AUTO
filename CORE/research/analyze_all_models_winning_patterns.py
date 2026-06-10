"""analyze_all_models_winning_patterns.py — Analyse causale 4 modeles ES/NQ x BUY/SELL.

Objectif Jackson 28/04 : trouver les parametres optimaux pour TOUS les modeles
via analyse causale (data-driven) au lieu de grid search aveugle.

Methode :
  - Pour chaque (symbol, side) :
    - Charge dataset v5d
    - Compute PnL proxy (BUY-only ou SELL-only)
    - Pour chaque feature (binaire/continu) : compute PF avec/sans filtre
    - Identifier TOP 5 filtres (edge > 0.3 PF)
    - TOP 5 combinaisons binary x continuous
  - Output : ranking par modele

Usage : python -X utf8 CORE/research/analyze_all_models_winning_patterns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def side_only_pnl_proxy(label: np.ndarray, realized: np.ndarray, side: int,
                         k_tp_ratio: float = 2.0) -> np.ndarray:
    """Convertit (label, realized) en PnL pour entry side-only.

    Pour BUY (side=1) :
      - label==1 → +realized (BUY wins TP)
      - label==-1 → -|realized|/k_tp_ratio (BUY's SL)
      - label==0 → 0 (timeout)

    Pour SELL (side=-1) :
      - label==-1 → +|realized| (SELL wins, mais realized = -tp donc abs)
      - label==1 → -realized/k_tp_ratio (SELL's SL)
      - label==0 → 0
    """
    pnl = np.zeros_like(realized, dtype=np.float64)
    if side == 1:  # BUY
        pnl[label == 1] = realized[label == 1]
        pnl[label == -1] = -np.abs(realized[label == -1]) / k_tp_ratio
    else:  # SELL
        pnl[label == -1] = np.abs(realized[label == -1])
        pnl[label == 1] = -realized[label == 1] / k_tp_ratio
    return pnl


def compute_pf(pnl: np.ndarray) -> dict:
    if len(pnl) == 0:
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "total": 0}
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(pnl)
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else float("inf")
    wr = len(wins) / n if n > 0 else 0
    ev = float(pnl.mean()) if n > 0 else 0
    return {"n": n, "pf": pf, "wr": wr, "ev": ev, "total": float(pnl.sum())}


BINARY_FEATURES = [
    "bool_above_mq_hvl", "bool_above_mq_call",
    "is_in_us_after",
    "ib_complete", "ib_broken_up", "ib_broken_dn",
    "vol_spike_up", "vol_spike_dn",
    "above_open_830", "above_open_930",
    "vwap_d_sd1_above", "vwap_d_sd1_below", "vwap_d_sd2_above",
    "long_dn_up_pattern", "long_up_dn_pattern",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    "spike_detected_lag3",
    "above_asia_open", "above_london_open", "above_ny_open",
    "discount_zone", "inside_value_area", "inside_cur_va", "open_in_prev_va",
    "is_mq_filled",
    "rule_pullback_continuation_buy_dir", "rule_pullback_mq_hvl_buy_dir",
    "rule_color_up_proximity_dir",
    "delta_div_buy", "delta_div_sell",
    "finish_strong_up", "finish_strong_dn",
]

CONTINUOUS_FEATURES = [
    "vix_level",
    "atr_14m_pct", "bar_range_pct", "bar_body_pct",
    "delta_bar", "cvd_session", "delta_pct",
    "n_color_up_zones_active", "n_color_dn_zones_active",
    "n_trapped_sellers_zones_active", "n_trapped_buyers_zones_active",
    "rvol", "rvol_zscore",
    "open_bias_conf",
    "ib_position_pct", "va_position_pct", "pct_in_range",
    "dist_vwap_d_atr",
    "vwap_slope_10_atr",
    "ctx_rotation_factor_20",
    "n_big_buy_t1", "n_big_sell_t1",
    "max_cluster_size",
    "im_cross_delta_agreement_5", "im_cross_delta_weighted_5",
    "im_rolling_correlation_10",
    "n_naked_poc_active", "naked_poc_age_max_days",
    "open_type", "day_type", "open_zone",
]


def analyze_filter_binary(df: pd.DataFrame, pnl: np.ndarray, feature: str,
                           min_n: int = 100) -> dict:
    if feature not in df.columns:
        return None
    feat_vals = df[feature].values
    mask_0 = (feat_vals == 0)
    mask_1 = (feat_vals == 1)
    if mask_0.sum() < min_n or mask_1.sum() < min_n:
        return None
    pf_0 = compute_pf(pnl[mask_0])
    pf_1 = compute_pf(pnl[mask_1])
    edge = abs(pf_1["pf"] - pf_0["pf"])
    direction = "f=1" if pf_1["pf"] > pf_0["pf"] else "f=0"
    pf_keep = pf_1["pf"] if pf_1["pf"] > pf_0["pf"] else pf_0["pf"]
    n_keep = pf_1["n"] if pf_1["pf"] > pf_0["pf"] else pf_0["n"]
    wr_keep = pf_1["wr"] if pf_1["pf"] > pf_0["pf"] else pf_0["wr"]
    ev_keep = pf_1["ev"] if pf_1["pf"] > pf_0["pf"] else pf_0["ev"]
    return {
        "feature": feature, "direction": direction,
        "pf_keep": pf_keep, "edge": edge, "n_keep": n_keep,
        "wr_keep": wr_keep, "ev_keep": ev_keep,
    }


def analyze_filter_continuous(df: pd.DataFrame, pnl: np.ndarray, feature: str,
                                min_n: int = 100) -> dict:
    if feature not in df.columns:
        return None
    feat_vals = df[feature].values
    valid = ~np.isnan(feat_vals)
    if valid.sum() < min_n * 2:
        return None
    q25, q75 = np.nanquantile(feat_vals, [0.25, 0.75])
    mask_low = valid & (feat_vals <= q25)
    mask_high = valid & (feat_vals >= q75)
    if mask_low.sum() < min_n or mask_high.sum() < min_n:
        return None
    pf_low = compute_pf(pnl[mask_low])
    pf_high = compute_pf(pnl[mask_high])
    edge = abs(pf_high["pf"] - pf_low["pf"])
    if pf_high["pf"] > pf_low["pf"]:
        direction = f">={q75:.2f}"
        pf_keep, n_keep, wr_keep, ev_keep = pf_high["pf"], pf_high["n"], pf_high["wr"], pf_high["ev"]
    else:
        direction = f"<={q25:.2f}"
        pf_keep, n_keep, wr_keep, ev_keep = pf_low["pf"], pf_low["n"], pf_low["wr"], pf_low["ev"]
    return {
        "feature": feature, "direction": direction,
        "pf_keep": pf_keep, "edge": edge, "n_keep": n_keep,
        "wr_keep": wr_keep, "ev_keep": ev_keep,
    }


def analyze_model(symbol: str, side: int) -> dict:
    side_str = "BUY" if side == 1 else "SELL"
    print(f"\n{'='*80}")
    print(f"  {symbol} {side_str} — Analyse causale")
    print(f"{'='*80}")

    fp = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
    df = pd.read_parquet(fp)
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()

    label = df["label"].values
    realized = df["realized_pts"].values
    pnl = side_only_pnl_proxy(label, realized, side=side, k_tp_ratio=2.0)

    baseline = compute_pf(pnl)
    print(f"  Baseline {side_str} systematic : N={baseline['n']:,}  PF={baseline['pf']:.2f}  "
          f"WR={baseline['wr']*100:.1f}%  EV={baseline['ev']:+.2f}t  Total={baseline['total']:+.0f}t")

    # Analyse binaires
    binary_results = []
    for feat in BINARY_FEATURES:
        r = analyze_filter_binary(df, pnl, feat)
        if r and r["edge"] > 0.20:
            binary_results.append(r)
    binary_results.sort(key=lambda r: r["edge"], reverse=True)

    # Analyse continues
    cont_results = []
    for feat in CONTINUOUS_FEATURES:
        r = analyze_filter_continuous(df, pnl, feat)
        if r and r["edge"] > 0.15:
            cont_results.append(r)
    cont_results.sort(key=lambda r: r["edge"], reverse=True)

    print(f"\n  TOP 8 FILTRES BINAIRES (edge):")
    print(f"    {'Feature':40s} {'Dir':5s} {'PF':>6s} {'WR%':>5s} {'EV':>6s} {'N':>7s}")
    for r in binary_results[:8]:
        print(f"    {r['feature']:40s} {r['direction']:5s} {r['pf_keep']:>6.2f} "
              f"{r['wr_keep']*100:>5.1f} {r['ev_keep']:>+6.1f} {r['n_keep']:>7,d}")

    print(f"\n  TOP 8 FILTRES CONTINUS (edge):")
    print(f"    {'Feature':40s} {'Dir':10s} {'PF':>6s} {'WR%':>5s} {'EV':>6s} {'N':>7s}")
    for r in cont_results[:8]:
        print(f"    {r['feature']:40s} {r['direction']:10s} {r['pf_keep']:>6.2f} "
              f"{r['wr_keep']*100:>5.1f} {r['ev_keep']:>+6.1f} {r['n_keep']:>7,d}")

    # TOP combos (TOP 3 binaires x TOP 3 continues)
    print(f"\n  TOP COMBOS (top3 binary × top3 continuous):")
    combos = []
    for tb in binary_results[:3]:
        for tc in cont_results[:3]:
            target_b = 1 if tb["direction"] == "f=1" else 0
            op = ">=" if ">=" in tc["direction"] else "<="
            threshold = float(tc["direction"].replace(">=", "").replace("<=", ""))
            if op == ">=":
                mask = (df[tb["feature"]] == target_b) & (df[tc["feature"]] >= threshold)
            else:
                mask = (df[tb["feature"]] == target_b) & (df[tc["feature"]] <= threshold)
            stats = compute_pf(pnl[mask.values])
            if stats["n"] >= 50:
                combos.append({
                    "filter": f"{tb['feature']}={target_b} AND {tc['feature']}{op}{threshold:.2f}",
                    "pf": stats["pf"], "wr": stats["wr"], "ev": stats["ev"],
                    "n": stats["n"], "total": stats["total"],
                })
    combos.sort(key=lambda c: c["pf"], reverse=True)
    for c in combos[:5]:
        print(f"    {c['filter'][:60]:60s} PF={c['pf']:.2f} WR={c['wr']*100:.1f}% "
              f"EV={c['ev']:+.1f}t N={c['n']:,}")

    return {
        "symbol": symbol, "side": side_str,
        "baseline_pf": baseline["pf"],
        "top_binary": binary_results[:5],
        "top_continuous": cont_results[:5],
        "top_combos": combos[:5],
    }


def main():
    print("=" * 80)
    print("  ANALYSE CAUSALE 4 MODELES — ES/NQ × BUY/SELL")
    print("=" * 80)

    results = []
    for symbol in ["ES", "NQ"]:
        for side in [1, -1]:
            r = analyze_model(symbol, side)
            results.append(r)

    # Synthese finale
    print(f"\n\n{'='*80}")
    print(f"  SYNTHESE — Best filter per model")
    print(f"{'='*80}")
    print(f"  {'Model':12s} {'Baseline PF':>11s} {'Best Combo':<60s} {'Combo PF':>9s}")
    for r in results:
        model = f"{r['symbol']} {r['side']}"
        b_pf = r['baseline_pf']
        best = r['top_combos'][0] if r['top_combos'] else None
        if best:
            print(f"  {model:12s} {b_pf:>11.2f}  {best['filter'][:55]:55s}  {best['pf']:>8.2f}")
        else:
            print(f"  {model:12s} {b_pf:>11.2f}  (no significant combo)")


if __name__ == "__main__":
    main()
