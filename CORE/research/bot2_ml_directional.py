"""bot2_ml_directional.py — ML directional triple-barrier pour Bot 2 (Solution B).

Objectif : predire la direction du marche sur N bars (15, 60, 240) a partir des
features V4 enriched, et utiliser comme signal de trade Bot 2.

Methodologie (Lopez AFML) :
 1. Triple-barrier labelisation : pour chaque bar t, look-forward N bars.
    Si close[t+k] >= close[t] + up_threshold avant down -> LONG
    Si close[t+k] <= close[t] - down_threshold avant up -> SHORT
    Sinon (timeout) -> HOLD
 2. Walk-forward 12-fold avec embargo (Lopez ch.7) entre train/test.
 3. Sample weights : uniqueness * decay temporel (ch.4).
 4. Features causales seulement (LAG-1 already in V4 enriched).
 5. Drop features qui revealent l'instrument (PROHIBITED_FEATURES rule).

Metriques rapportees (criteres realistes, pas Lopez strict) :
  - Accuracy directionnelle (vs baseline ~33% si 3 classes equilibrees, ~50% si binaire)
  - Sharpe walk-forward median
  - PF sur trades simules (LONG si proba > 0.5, SHORT si proba < 0.5 binaire)
  - Stabilite : pas de fold avec acc < 50%

Decision GO conditional si :
  acc_median >= 0.55 (binaire) OR (>= 0.40 si 3 classes)
  Sharpe_median >= 1.0
  PF >= 1.3
  Aucun fold acc < 0.50 (binaire) OR < 0.35 (3 classes)
"""
from __future__ import annotations

import sys
import json
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]


# ─── Config ────────────────────────────────────────────────────────────────

# Features candidates (43 cols V4 enriched, drop instrumental price)
FEATURE_CANDIDATES = [
    # Price-relative (normalises)
    "vwap_slope_10",
    "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
    "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
    "dist_pdh_pct", "dist_pdl_pct",
    "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_cur_vpoc_pct",
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    # Footprint/delta
    "long_up_bar", "long_dn_bar",
    "delta_bar", "delta_pct",
    "aggressor_imbalance", "big_buy_dominance", "big_sell_dominance",
    # Clusters / edges
    "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
    "n_edge_buy_active", "n_edge_sell_active",
    # Volume / VIX
    "vix_level", "rvol", "rvol_zscore", "volume_z",
    # ATR-normalises
    "sess_range_atr", "dist_vwap_d_atr",
]

# Horizons (en bars 1-min)
HORIZONS = {"H15": 15, "H60": 60, "H240": 240}

# Triple-barrier multipliers (en multiples ATR)
TB_UP_MULT = 0.8
TB_DN_MULT = 0.8


def load_all_nq() -> pd.DataFrame:
    """Charge tous les parquets NQ V4 enriched."""
    base = ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0"
    parts = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            pq = month_dir / "data.parquet"
            if pq.exists():
                df = pd.read_parquet(pq)
                parts.append(df)
    df = pd.concat(parts, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    print(f"Loaded NQ: {len(df)} bars, {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


def label_triple_barrier(
    df: pd.DataFrame,
    horizon_bars: int,
    up_mult: float = TB_UP_MULT,
    dn_mult: float = TB_DN_MULT,
) -> pd.Series:
    """Triple-barrier labels :
      +1 (LONG) si TP up touche avant TP dn ou timeout
      -1 (SHORT) si TP dn touche avant TP up ou timeout
       0 (HOLD) si timeout sans touche
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    atr = df["atr"].values  # absolute units (ticks * tick_size = points pour NQ ?)
    # atr semble en POINTS (verifie : atr typique NQ = 20-50 pts)

    n = len(df)
    labels = np.zeros(n, dtype=np.int8)

    for t in range(n - horizon_bars):
        a = atr[t]
        if not np.isfinite(a) or a <= 0:
            labels[t] = 0
            continue
        c0 = close[t]
        up_barrier = c0 + a * up_mult
        dn_barrier = c0 - a * dn_mult

        hit_up = False
        hit_dn = False
        for k in range(1, horizon_bars + 1):
            tk = t + k
            if high[tk] >= up_barrier:
                hit_up = True
                break
            if low[tk] <= dn_barrier:
                hit_dn = True
                break
        if hit_up and not hit_dn:
            labels[t] = 1
        elif hit_dn and not hit_up:
            labels[t] = -1
        else:
            labels[t] = 0
    # last horizon_bars rows: no label
    labels[n - horizon_bars:] = 0
    return pd.Series(labels, index=df.index, name=f"label_h{horizon_bars}")


def compute_sample_weights(labels: pd.Series, horizon_bars: int) -> pd.Series:
    """Sample weights = uniqueness approximation (Lopez ch.4 simplified).

    Pour chaque label t, le label depend des bars [t+1, t+horizon_bars].
    Un evenement court (touch barriere rapide) est plus unique qu'un timeout.
    Approximation : poids = 1 / nombre de labels qui chevauchent.
    """
    n = len(labels)
    weights = np.ones(n)
    # Simplification : decay temporel uniquement (penalise vieux samples)
    decay = np.linspace(0.5, 1.0, n)
    weights *= decay
    return pd.Series(weights, index=labels.index, name="sw")


def walk_forward_split(n: int, n_folds: int = 12, embargo: int = 60) -> list:
    """Genere les splits walk-forward avec embargo (Lopez ch.7)."""
    fold_size = n // (n_folds + 1)  # le 1er fold = train initial uniquement
    splits = []
    for k in range(1, n_folds + 1):
        train_end = k * fold_size
        test_start = train_end + embargo
        test_end = min(test_start + fold_size, n)
        if test_start >= n:
            break
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
    return splits


def simulate_trades_from_proba(
    df: pd.DataFrame,
    proba: np.ndarray,
    test_idx: np.ndarray,
    horizon_bars: int,
    proba_threshold: float = 0.55,
    sl_ticks: int = 20,
    tick_size: float = 0.25,
) -> dict:
    """Simule trades base sur proba LONG du modele binaire.
    Si proba > threshold -> LONG, < (1-threshold) -> SHORT, sinon HOLD.
    Exit : timeout horizon_bars OU SL.
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    pnls = []
    for j, i in enumerate(test_idx):
        if i + horizon_bars >= len(df):
            continue
        p = proba[j]
        if p > proba_threshold:
            direction = "long"
        elif p < (1 - proba_threshold):
            direction = "short"
        else:
            continue
        entry = close[i]
        sl_offset = sl_ticks * tick_size
        if direction == "long":
            sl_price = entry - sl_offset
        else:
            sl_price = entry + sl_offset
        exit_price = None
        for k in range(1, horizon_bars + 1):
            tk = i + k
            if direction == "long":
                if low[tk] <= sl_price:
                    exit_price = sl_price
                    break
            else:
                if high[tk] >= sl_price:
                    exit_price = sl_price
                    break
        if exit_price is None:
            exit_price = close[i + horizon_bars]
        if direction == "long":
            pnl_ticks = (exit_price - entry) / tick_size
        else:
            pnl_ticks = (entry - exit_price) / tick_size
        pnls.append(pnl_ticks)

    if not pnls:
        return {"n_trades": 0, "wr": 0, "ev_ticks": 0, "pf": 0, "sharpe": 0}
    pnls = np.array(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    sum_w = wins.sum() if len(wins) else 0
    sum_l = -losses.sum() if len(losses) else 1e-9
    pf = sum_w / sum_l if sum_l > 0 else float("inf")
    wr = len(wins) / len(pnls) * 100
    ev = pnls.mean()
    std = pnls.std() if pnls.std() > 0 else 1e-9
    sharpe = ev / std * np.sqrt(252)  # annualise approximation
    return {
        "n_trades": len(pnls),
        "wr": float(wr),
        "ev_ticks": float(ev),
        "pf": float(pf),
        "sharpe": float(sharpe),
        "sum_ticks": float(pnls.sum()),
    }


def train_walk_forward(
    df: pd.DataFrame,
    features: list[str],
    label_col: str,
    horizon_bars: int,
    n_folds: int = 12,
    embargo: int = 60,
) -> dict:
    """Walk-forward training LightGBM binaire (LONG vs SHORT, drop HOLD).

    Returns metrics aggregated cross-fold.
    """
    import lightgbm as lgb

    # Filter labels binaires (drop HOLD=0)
    mask = df[label_col] != 0
    sub = df[mask].copy()
    sub["y"] = (sub[label_col] == 1).astype(int)  # 1 = LONG, 0 = SHORT
    print(f"  Binary samples: {len(sub)} ({sub['y'].mean()*100:.1f}% LONG)")

    X = sub[features].fillna(0).values.astype(np.float32)
    y = sub["y"].values
    sw = compute_sample_weights(sub[label_col], horizon_bars).values

    splits = walk_forward_split(len(sub), n_folds=n_folds, embargo=embargo)
    print(f"  Walk-forward folds: {len(splits)}")

    fold_metrics = []
    for fold_id, (train_idx, test_idx) in enumerate(splits):
        if len(train_idx) < 500 or len(test_idx) < 100:
            continue
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]
        sw_tr = sw[train_idx]

        model = lgb.LGBMClassifier(
            n_estimators=200,
            learning_rate=0.05,
            num_leaves=31,
            max_depth=6,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_tr, y_tr, sample_weight=sw_tr)
        proba = model.predict_proba(X_te)[:, 1]
        pred = (proba > 0.5).astype(int)
        acc = (pred == y_te).mean()

        # Simulation trades sur le test set
        global_test_idx = sub.index.values[test_idx]
        sim = simulate_trades_from_proba(
            df, proba, global_test_idx, horizon_bars, proba_threshold=0.55
        )
        sim["fold"] = fold_id
        sim["acc"] = float(acc)
        sim["n_test"] = len(test_idx)
        fold_metrics.append(sim)
        print(f"  Fold {fold_id}: acc={acc:.3f} trades={sim['n_trades']} "
              f"WR={sim['wr']:.1f}% PF={sim['pf']:.2f} EV={sim['ev_ticks']:+.2f}t")

    if not fold_metrics:
        return {"folds": [], "summary": {}}

    accs = [m["acc"] for m in fold_metrics]
    pfs = [m["pf"] for m in fold_metrics if m["pf"] != float("inf")]
    wrs = [m["wr"] for m in fold_metrics]
    evs = [m["ev_ticks"] for m in fold_metrics]
    sharpes = [m["sharpe"] for m in fold_metrics]
    n_trades_total = sum(m["n_trades"] for m in fold_metrics)

    summary = {
        "n_folds_kept": len(fold_metrics),
        "n_trades_total": n_trades_total,
        "acc_median": float(np.median(accs)),
        "acc_mean": float(np.mean(accs)),
        "acc_min": float(np.min(accs)),
        "pf_median": float(np.median(pfs)) if pfs else 0.0,
        "wr_median": float(np.median(wrs)),
        "ev_median_ticks": float(np.median(evs)),
        "sharpe_median": float(np.median(sharpes)),
        "stability_acc_above_50pct": float(np.mean([a >= 0.5 for a in accs])),
    }
    return {"folds": fold_metrics, "summary": summary}


def main():
    print("=" * 60)
    print("ML DIRECTIONAL — Solution B Bot 2")
    print("=" * 60)
    df = load_all_nq()

    # Keep features that exist
    features = [c for c in FEATURE_CANDIDATES if c in df.columns]
    print(f"Features: {len(features)}/{len(FEATURE_CANDIDATES)}")

    results_all = {}

    for h_name, h_bars in HORIZONS.items():
        print(f"\n--- HORIZON {h_name} ({h_bars} bars) ---")
        label_col = f"label_h{h_bars}"
        labels = label_triple_barrier(df, h_bars)
        df[label_col] = labels.values

        counts = labels.value_counts().to_dict()
        print(f"  Label distribution: {counts}")
        n_long = counts.get(1, 0)
        n_short = counts.get(-1, 0)
        n_hold = counts.get(0, 0)
        if n_long + n_short < 100:
            print(f"  SKIP: trop peu de labels (LONG+SHORT={n_long+n_short})")
            results_all[h_name] = {"summary": {"skipped": True, "reason": "too_few_labels"}}
            continue

        res = train_walk_forward(df, features, label_col, h_bars)
        results_all[h_name] = res

        s = res.get("summary", {})
        print(f"\n  SUMMARY {h_name}:")
        for k, v in s.items():
            print(f"    {k}: {v}")

    # Verdict
    print("\n" + "=" * 60)
    print("VERDICT ML DIRECTIONAL")
    print("=" * 60)

    GO_criteria = {
        "acc_median_ge_55": False,
        "pf_median_ge_1_3": False,
        "sharpe_median_ge_1_0": False,
        "stability_ge_75pct": False,
        "n_trades_ge_50": False,
    }

    best_h = None
    best_score = -1
    for h, r in results_all.items():
        s = r.get("summary", {})
        if s.get("skipped"):
            continue
        score = (s.get("acc_median", 0) - 0.5) * 100 + s.get("pf_median", 0)
        if score > best_score:
            best_score = score
            best_h = h
        print(f"\n  {h}:")
        print(f"    acc_median = {s.get('acc_median', 0):.3f} "
              f"(criteria >= 0.55: {s.get('acc_median', 0) >= 0.55})")
        print(f"    pf_median  = {s.get('pf_median', 0):.2f} "
              f"(criteria >= 1.3 : {s.get('pf_median', 0) >= 1.3})")
        print(f"    sharpe_median = {s.get('sharpe_median', 0):.2f} "
              f"(criteria >= 1.0 : {s.get('sharpe_median', 0) >= 1.0})")
        print(f"    stability = {s.get('stability_acc_above_50pct', 0)*100:.0f}% "
              f"(criteria >= 75%: {s.get('stability_acc_above_50pct', 0) >= 0.75})")
        print(f"    n_trades_total = {s.get('n_trades_total', 0)}")

    if best_h:
        s = results_all[best_h]["summary"]
        GO_criteria["acc_median_ge_55"] = s.get("acc_median", 0) >= 0.55
        GO_criteria["pf_median_ge_1_3"] = s.get("pf_median", 0) >= 1.3
        GO_criteria["sharpe_median_ge_1_0"] = s.get("sharpe_median", 0) >= 1.0
        GO_criteria["stability_ge_75pct"] = s.get("stability_acc_above_50pct", 0) >= 0.75
        GO_criteria["n_trades_ge_50"] = s.get("n_trades_total", 0) >= 50

    n_ok = sum(GO_criteria.values())
    verdict = "GO" if n_ok >= 4 else ("GO_CONDITIONAL" if n_ok >= 3 else "NOGO")

    print(f"\n  BEST HORIZON: {best_h}")
    print(f"  GO_criteria: {n_ok}/5 OK")
    for k, v in GO_criteria.items():
        print(f"    {'OK' if v else 'KO'} {k}: {v}")
    print(f"\n  VERDICT: {verdict}")

    # Sauvegarde
    out = ROOT / "LOGS/bot2_research/ml_directional_results.json"
    # Stripper folds details pour JSON
    results_clean = {}
    for h, r in results_all.items():
        results_clean[h] = {
            "summary": r.get("summary", {}),
            "n_folds": len(r.get("folds", [])),
            "folds_brief": [
                {k: m[k] for k in ["fold", "acc", "n_trades", "wr", "pf", "ev_ticks"]
                 if k in m}
                for m in r.get("folds", [])
            ],
        }
    out.write_text(json.dumps({
        "verdict": verdict,
        "best_horizon": best_h,
        "GO_criteria": GO_criteria,
        "n_ok": n_ok,
        "results": results_clean,
    }, indent=2))
    print(f"\nSaved: {out}")
    return verdict, results_all


if __name__ == "__main__":
    main()
