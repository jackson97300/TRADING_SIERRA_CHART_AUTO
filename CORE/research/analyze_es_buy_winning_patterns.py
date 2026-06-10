"""analyze_es_buy_winning_patterns.py — Analyse causale ES BUY.

Objectif : trouver les filtres/regimes ou ES BUY a un edge structurel,
PUIS calibrer les parametres optimaux pour backtest final.

Approche inverse Jackson :
  1. Analyser data → identifier patterns gagnants
  2. Calibrer parametres avec ces filtres
  3. Backtest validation

Methode :
  - Charge dataset v5d (351K bars ES)
  - Pour chaque feature categorical/binaire/continu :
      PF(label=1 | filter ON) vs PF(label=1 | filter OFF)
  - Identifier les TOP filtres (edge > +0.3 PF)
  - Combinaisons des TOP 3 filtres
  - Output : ranking des regimes ES BUY profitables

Usage : python -X utf8 CORE/research/analyze_es_buy_winning_patterns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def buy_only_pnl_proxy(label: np.ndarray, realized: np.ndarray,
                        k_tp_ratio: float = 2.0) -> np.ndarray:
    """Convertit (label, realized_pts) en PnL BUY-only (chaque bar = entry BUY).

    Logique :
      - label == 1 (BUY wins TP first) → PnL = +realized (= +tp_ticks)
      - label == -1 (SELL wins, BUY's SL hit first) → PnL = -|realized|/k_tp_ratio = -sl_ticks
      - label == 0 (timeout) → PnL ~0 (marked-to-market neutre, approx)

    Returns: PnL array (ticks).
    """
    pnl = np.zeros_like(realized, dtype=np.float64)
    pnl[label == 1] = realized[label == 1]  # BUY wins
    # Pour label==-1 (SELL win), BUY's SL = -tp_ticks/k_tp_ratio
    sell_wins = (label == -1)
    pnl[sell_wins] = -np.abs(realized[sell_wins]) / k_tp_ratio
    # label == 0 stays 0 (timeout)
    return pnl


def compute_pf_from_pnl(pnl: np.ndarray) -> dict:
    """Compute PF, WR, EV, n_trades from BUY-only PnL array."""
    if len(pnl) == 0:
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "total": 0}
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(pnl)
    n_win = len(wins)
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else float("inf")
    wr = n_win / n if n > 0 else 0
    ev = float(pnl.mean()) if n > 0 else 0
    return {
        "n": n, "pf": pf, "wr": wr, "ev": ev, "total": float(pnl.sum()),
    }


def analyze_filter_binary(df: pd.DataFrame, side: int, feature: str,
                           min_n: int = 100) -> dict:
    """Pour feature binaire (0/1), compare PF(filter=0) vs PF(filter=1)."""
    if feature not in df.columns:
        return None
    # Pour ES BUY analysis : on regarde TOUTES les bars (pas filtre label)
    # parce qu'on veut savoir : si on rentre BUY systematique sur ce regime,
    # quel PnL ?
    pnl_col = df["_buy_pnl"].values
    feat_vals = df[feature].values

    # Filter = 0 / 1
    mask_0 = (feat_vals == 0)
    mask_1 = (feat_vals == 1)
    if mask_0.sum() < min_n or mask_1.sum() < min_n:
        return None

    pf_0 = compute_pf_from_pnl(pnl_col[mask_0])
    pf_1 = compute_pf_from_pnl(pnl_col[mask_1])

    # Edge = écart absolu
    edge = abs(pf_1["pf"] - pf_0["pf"])
    direction = "feature=1" if pf_1["pf"] > pf_0["pf"] else "feature=0"

    return {
        "feature": feature, "type": "binary",
        "n_0": pf_0["n"], "n_1": pf_1["n"],
        "pf_0": pf_0["pf"], "pf_1": pf_1["pf"],
        "wr_0": pf_0["wr"], "wr_1": pf_1["wr"],
        "ev_0": pf_0["ev"], "ev_1": pf_1["ev"],
        "edge": edge, "best_filter": direction,
    }


def analyze_filter_continuous(df: pd.DataFrame, side: int, feature: str,
                               min_n: int = 100) -> dict:
    """Pour feature continu, compare PF(< q25) vs PF(> q75) (bord vs bord)."""
    if feature not in df.columns:
        return None
    # Pour ES BUY analysis : on regarde TOUTES les bars (pas filtre label)
    # parce qu'on veut savoir : si on rentre BUY systematique sur ce regime,
    # quel PnL ?
    pnl_col = df["_buy_pnl"].values
    feat_vals = df[feature].values
    valid = ~np.isnan(feat_vals)
    if valid.sum() < min_n * 2:
        return None
    q25, q75 = np.nanquantile(feat_vals, [0.25, 0.75])

    mask_low = valid & (feat_vals <= q25)
    mask_high = valid & (feat_vals >= q75)
    if mask_low.sum() < min_n or mask_high.sum() < min_n:
        return None

    pf_low = compute_pf_from_pnl(pnl_col[mask_low])
    pf_high = compute_pf_from_pnl(pnl_col[mask_high])
    edge = abs(pf_high["pf"] - pf_low["pf"])
    direction = f"feature>={q75:.2f}" if pf_high["pf"] > pf_low["pf"] else f"feature<={q25:.2f}"

    return {
        "feature": feature, "type": "continuous",
        "q25": q25, "q75": q75,
        "n_low": pf_low["n"], "n_high": pf_high["n"],
        "pf_low": pf_low["pf"], "pf_high": pf_high["pf"],
        "wr_low": pf_low["wr"], "wr_high": pf_high["wr"],
        "edge": edge, "best_filter": direction,
    }


def main():
    print("=" * 80)
    print("  ANALYSE CAUSALE ES BUY — Recherche regimes profitables")
    print("=" * 80)

    fp = ROOT / "DATA" / "datasets" / "ES_dataset_v5d.parquet"
    print(f"\n  Loading {fp.name}...")
    df = pd.read_parquet(fp)
    print(f"  Total bars : {len(df):,}")

    # Filter RTH only
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    print(f"  RTH bars   : {len(df):,}")

    n_buy = (df["label"] == 1).sum()
    n_sell = (df["label"] == -1).sum()
    n_hold = (df["label"] == 0).sum()
    print(f"  Labels     : BUY={n_buy:,} ({n_buy/len(df)*100:.1f}%), "
          f"SELL={n_sell:,} ({n_sell/len(df)*100:.1f}%), HOLD={n_hold:,}")

    # Calcule PnL BUY-only proxy (chaque bar = simulation entree BUY)
    label = df["label"].values
    realized = df["realized_pts"].values
    df["_buy_pnl"] = buy_only_pnl_proxy(label, realized, k_tp_ratio=2.0)
    pnl = df["_buy_pnl"].values

    # Baseline : si on rentre BUY a CHAQUE bar
    baseline = compute_pf_from_pnl(pnl)
    print(f"\n  BASELINE BUY systematic (chaque bar = entry BUY) :")
    print(f"    N={baseline['n']:,}  PF={baseline['pf']:.2f}  WR={baseline['wr']*100:.1f}%  "
          f"EV={baseline['ev']:+.2f}t  Total={baseline['total']:+.0f}t")

    # Features candidates (binaires + continues)
    BINARY_FEATURES = [
        "bool_above_mq_hvl", "bool_above_mq_call",
        "is_in_us_after",  # session
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

    print(f"\n  Analyse {len(BINARY_FEATURES)} binaires + {len(CONTINUOUS_FEATURES)} continues...")

    results_binary = []
    for feat in BINARY_FEATURES:
        r = analyze_filter_binary(df, side=1, feature=feat)
        if r and r["edge"] > 0.05:
            results_binary.append(r)

    results_continuous = []
    for feat in CONTINUOUS_FEATURES:
        r = analyze_filter_continuous(df, side=1, feature=feat)
        if r and r["edge"] > 0.05:
            results_continuous.append(r)

    # Trier par edge decroissant
    results_binary.sort(key=lambda r: r["edge"], reverse=True)
    results_continuous.sort(key=lambda r: r["edge"], reverse=True)

    print("\n" + "=" * 80)
    print(f"  TOP {min(15, len(results_binary))} FILTRES BINAIRES (edge PF)")
    print("=" * 80)
    print(f"  {'Feature':40s} {'best_filter':18s} {'PF_keep':>8s} {'PF_drop':>8s} {'edge':>6s} {'N_keep':>7s}")
    print("  " + "-" * 78)
    for r in results_binary[:15]:
        is_one = (r["best_filter"] == "feature=1")
        pf_keep = r["pf_1"] if is_one else r["pf_0"]
        pf_drop = r["pf_0"] if is_one else r["pf_1"]
        n_keep = r["n_1"] if is_one else r["n_0"]
        print(f"  {r['feature']:40s} {r['best_filter']:18s} {pf_keep:>8.2f} {pf_drop:>8.2f} "
              f"{r['edge']:>6.2f} {n_keep:>7,d}")

    print("\n" + "=" * 80)
    print(f"  TOP {min(15, len(results_continuous))} FILTRES CONTINUS (edge PF)")
    print("=" * 80)
    print(f"  {'Feature':40s} {'best_filter':22s} {'PF_keep':>8s} {'PF_drop':>8s} {'edge':>6s} {'N_keep':>7s}")
    print("  " + "-" * 82)
    for r in results_continuous[:15]:
        is_high = ">=" in r["best_filter"]
        pf_keep = r["pf_high"] if is_high else r["pf_low"]
        pf_drop = r["pf_low"] if is_high else r["pf_high"]
        n_keep = r["n_high"] if is_high else r["n_low"]
        print(f"  {r['feature']:40s} {r['best_filter']:22s} {pf_keep:>8.2f} {pf_drop:>8.2f} "
              f"{r['edge']:>6.2f} {n_keep:>7,d}")

    # Combinaisons TOP 3 binaires + TOP 3 continues
    top_binary = results_binary[:3]
    top_continuous = results_continuous[:3]

    print("\n" + "=" * 80)
    print(f"  COMBINAISONS TOP 3 BINAIRES + TOP 3 CONTINUES")
    print("=" * 80)
    if top_binary and top_continuous:
        for tb in top_binary:
            for tc in top_continuous:
                # Build combined mask
                feat_b = tb["feature"]
                feat_c = tc["feature"]
                target_b = 1 if "feature=1" in tb["best_filter"] else 0
                threshold_c = tc["q75"] if ">=" in tc["best_filter"] else tc["q25"]
                op_c = ">=" if ">=" in tc["best_filter"] else "<="

                # Use full df (not filtered by label) — BUY systematic
                if op_c == ">=":
                    mask = (df[feat_b] == target_b) & (df[feat_c] >= threshold_c)
                else:
                    mask = (df[feat_b] == target_b) & (df[feat_c] <= threshold_c)
                pnl_arr = df.loc[mask, "_buy_pnl"].values
                if len(pnl_arr) < 50:
                    continue
                stats = compute_pf_from_pnl(pnl_arr)
                print(f"  {feat_b}={target_b} AND {feat_c}{op_c}{threshold_c:.2f} : "
                      f"N={stats['n']:,} PF={stats['pf']:.2f} WR={stats['wr']*100:.1f}% "
                      f"EV={stats['ev']:+.1f}t Total={stats['total']:+.0f}t")

    print("\n" + "=" * 80)
    print(f"  RECOMMANDATIONS PRE-BACKTEST")
    print("=" * 80)
    print(f"  Baseline ES BUY all bars : PF={baseline['pf']:.2f} N={baseline['n']:,}")
    if results_binary:
        best_b = results_binary[0]
        gain = max(best_b["pf_0"], best_b["pf_1"]) / baseline['pf'] - 1
        print(f"  Best filter binaire : {best_b['feature']} = {best_b['best_filter']}")
        print(f"    PF gain : +{gain*100:.0f}% vs baseline")
    if results_continuous:
        best_c = results_continuous[0]
        gain = max(best_c["pf_high"], best_c["pf_low"]) / baseline['pf'] - 1
        print(f"  Best filter continu : {best_c['feature']} {best_c['best_filter']}")
        print(f"    PF gain : +{gain*100:.0f}% vs baseline")


if __name__ == "__main__":
    main()
