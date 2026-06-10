"""train_dmp_v2_clean.py — Test ML DMP v2 avec labeler INDEPENDANT + audit leaks.

Created : 2026-05-02 dimanche soir post detection AUC 0.73 suspect run quick.

Probleme identifie precedent : div_forward_return_20b = label generator + perf metric
                                = autocorrelation 1.0 = WR 99% artefact

Approche propre :
  1. Recalcul label INDEPENDANT via Triple Barrier vol-scaled sur close + ATR
     (pt=1.0 ATR, sl=1.0 ATR, horizon=20 bars)
  2. Drop label original + div_forward_return_20b + features derivees suspectes
     (ctx_*, im_*, amd_* = rolling, peut peeker)
  3. Train sur DMP "brut pur" (mq_*, vwap_*, dist_*, vix_*, big_*, bn_*, etc.)
  4. Evaluate via NOUVEAU label (independant du training metric)
  5. Compare 2 scenarios :
     - DMP_BRUT : sans features derivees (exclu ctx_*, im_*, amd_*, rvol_*)
     - DMP_FULL : avec features derivees (inclus tout sauf labels et returns)

Si DMP_BRUT AUC > 0.55 PF >= 1.3 -> VRAI EDGE structurel
Si DMP_FULL >> DMP_BRUT -> leak vient des features derivees
Si les 2 = 0.55 -> pas d'edge, V5 NO-GO confirme
"""
from __future__ import annotations
import sys
import time
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import lightgbm as lgb
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "DATA" / "DATASETS"

# Cols meta + leaks structurels
META_LEAK_COLS = {
    "ts", "sym", "label", "div_forward_return_20b", "price",
}

# Features derivees rolling potentiellement contaminees (a verifier)
DERIVED_PREFIXES = ("ctx_", "im_", "amd_", "rvol")


def load_dataset(symbol: str) -> pd.DataFrame:
    fp = DATA / f"{symbol}_dataset_v2.parquet"
    df = pd.read_parquet(fp)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR simple sur close (proxy car bar_high/bar_low absent)."""
    if "atr" in df.columns:
        return df["atr"].fillna(method="ffill").fillna(0)
    if "atr_14m" in df.columns:
        return df["atr_14m"].fillna(method="ffill").fillna(0)
    # Fallback : rolling abs return
    return df["price"].diff().abs().rolling(period).mean().fillna(0)


def label_triple_barrier_close(df: pd.DataFrame, pt_mult: float = 1.0,
                                  sl_mult: float = 1.0, horizon: int = 20,
                                  side: str = "buy") -> tuple[np.ndarray, np.ndarray]:
    """Triple Barrier path-aware sur close (pas de high/low dispo).

    Pour chaque bar i : look forward H bars sur close. Si close depasse pt -> +1.
    Si close descend < sl -> -1. Sinon : sign(close[i+H] - close[i]).

    Returns:
        labels : 1=win, 0=loss/timeout-loss
        returns : retour realise (en pct prix entry)
    """
    price = df["price"].values
    atr = compute_atr(df).values
    n = len(price)
    labels = np.zeros(n, dtype=int)
    returns = np.zeros(n, dtype=float)
    sign = 1 if side == "buy" else -1

    for i in range(n - horizon):
        entry = price[i]
        a = atr[i]
        if a <= 0 or pd.isna(a) or pd.isna(entry):
            labels[i] = -99
            continue
        # Barriers en pct prix (atr est en ticks pour DMP, convertir)
        # ATR DMP = ticks. Tick size = 0.25. donc ATR pts = atr * 0.25
        atr_pts = a * 0.25
        if side == "buy":
            tp_price = entry + pt_mult * atr_pts
            sl_price = entry - sl_mult * atr_pts
        else:
            tp_price = entry - pt_mult * atr_pts
            sl_price = entry + sl_mult * atr_pts
        # Path forward
        path = price[i+1 : i+1+horizon]
        if len(path) == 0:
            labels[i] = -99
            continue
        if side == "buy":
            hit_tp = np.where(path >= tp_price)[0]
            hit_sl = np.where(path <= sl_price)[0]
        else:
            hit_tp = np.where(path <= tp_price)[0]
            hit_sl = np.where(path >= sl_price)[0]
        first_tp = hit_tp[0] if len(hit_tp) else 999999
        first_sl = hit_sl[0] if len(hit_sl) else 999999
        if first_tp < first_sl:
            labels[i] = 1
            exit_price = tp_price
        elif first_sl < first_tp:
            labels[i] = 0
            exit_price = sl_price
        else:
            # timeout
            exit_price = path[-1]
            r = (exit_price - entry) / entry * sign
            labels[i] = 1 if r > 0 else 0
        returns[i] = (exit_price - entry) / entry * sign

    # Marquer fin et init invalides
    labels[n - horizon:] = -99
    returns[n - horizon:] = np.nan
    return labels, returns


def get_feature_cols(df: pd.DataFrame, exclude_derived: bool = False) -> list[str]:
    cols = []
    for c in df.columns:
        if c in META_LEAK_COLS:
            continue
        if exclude_derived and c.startswith(DERIVED_PREFIXES):
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        if df[c].nunique(dropna=True) < 2:
            continue
        cols.append(c)
    return cols


def purged_kfold_splits(n: int, n_splits: int = 5, embargo: int = 60) -> list[tuple[np.ndarray, np.ndarray]]:
    fold_size = n // (n_splits + 1)
    splits = []
    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        test_start = train_end + embargo
        test_end = min(test_start + fold_size, n)
        if test_end - test_start < 100:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
    return splits


def compute_pf(returns: np.ndarray) -> float:
    pos = returns[returns > 0].sum()
    neg = -returns[returns < 0].sum()
    return float(pos / neg) if neg > 1e-9 else (999.0 if pos > 0 else 0.0)


def train_eval(df: pd.DataFrame, sym: str, side: str, feature_cols: list[str],
                  scenario_label: str, n_splits: int = 5, embargo: int = 60,
                  threshold: float = 0.5) -> dict:
    # Recalcul label independant
    y_all, ret_all = label_triple_barrier_close(df, pt_mult=1.0, sl_mult=1.0,
                                                  horizon=20, side=side)
    valid_mask = (y_all != -99)
    n_valid = valid_mask.sum()
    if n_valid < 1000:
        return {"sym": sym, "side": side, "scenario": scenario_label, "error": "insufficient valid bars"}

    splits = purged_kfold_splits(n_valid, n_splits=n_splits, embargo=embargo)

    df_valid = df[valid_mask].reset_index(drop=True)
    y_valid = y_all[valid_mask]
    ret_valid = ret_all[valid_mask]

    fold_aucs, fold_pfs, fold_wrs, fold_ntrades, fold_ev = [], [], [], [], []

    for fold_idx, (tr, te) in enumerate(splits):
        X_tr = df_valid[feature_cols].iloc[tr].fillna(0).astype(np.float32).values
        y_tr = y_valid[tr]
        X_te = df_valid[feature_cols].iloc[te].fillna(0).astype(np.float32).values
        y_te = y_valid[te]
        ret_te = ret_valid[te]

        if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
            continue

        model = lgb.LGBMClassifier(
            objective="binary", metric="auc",
            learning_rate=0.05, num_leaves=31, max_depth=-1,
            min_data_in_leaf=20, n_estimators=200, n_jobs=-1, verbose=-1,
            force_col_wise=True,
        )
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]

        try:
            auc = roc_auc_score(y_te, proba)
        except ValueError:
            auc = np.nan

        # Trades
        triggers = proba > threshold
        n_trades = int(triggers.sum())
        if n_trades >= 5:
            r = ret_te[triggers]
            r = r[~np.isnan(r)]
            if len(r) >= 5:
                pf = compute_pf(r)
                wr = float((r > 0).mean())
                ev_pct = float(r.mean())  # en pct prix
                fold_pfs.append(pf)
                fold_wrs.append(wr)
                fold_ntrades.append(n_trades)
                fold_ev.append(ev_pct)
        fold_aucs.append(auc)

    return {
        "sym": sym, "side": side, "scenario": scenario_label,
        "n_features": len(feature_cols),
        "n_valid_bars": n_valid,
        "label_dist": {"win": int(y_valid.sum()), "loss": int(len(y_valid) - y_valid.sum())},
        "n_folds": len(fold_aucs),
        "mean_auc": float(np.nanmean(fold_aucs)) if fold_aucs else np.nan,
        "median_pf": float(np.nanmedian(fold_pfs)) if fold_pfs else np.nan,
        "mean_pf": float(np.nanmean(fold_pfs)) if fold_pfs else np.nan,
        "mean_wr": float(np.nanmean(fold_wrs)) if fold_wrs else np.nan,
        "mean_ev_pct": float(np.nanmean(fold_ev)) if fold_ev else np.nan,
        "total_trades": int(sum(fold_ntrades)) if fold_ntrades else 0,
    }


def verdict(r: dict) -> str:
    pf = r.get("median_pf", np.nan)
    auc = r.get("mean_auc", np.nan)
    n_tr = r.get("total_trades", 0)
    if pd.isna(pf) or n_tr < 30:
        return "INSUFFICIENT"
    if pf >= 1.5 and auc >= 0.55 and n_tr >= 100:
        return "GO_STRONG"
    if pf >= 1.3 and auc >= 0.53:
        return "GO_MARGINAL"
    if pf >= 1.1:
        return "MARGINAL"
    if pf >= 1.0:
        return "BREAK_EVEN"
    return "NO-GO"


def print_results(results: list[dict]):
    print(f"\n{'=' * 90}")
    print(f"VERDICT FINAL — labeler Triple Barrier INDEPENDANT (close+ATR)")
    print(f"{'=' * 90}")
    print(f"{'Combo':14} | {'Scen':10} | {'Feats':>5} | {'Folds':>5} | "
          f"{'AUC':>5} | {'PF med':>7} | {'WR':>5} | {'EV%':>6} | {'Trades':>6} | Verdict")
    print("-" * 110)
    for r in results:
        if "error" in r:
            print(f"{r['sym']}_{r['side']:5} | {r['scenario']:10} | ERROR: {r['error']}")
            continue
        v = verdict(r)
        print(f"{r['sym']}_{r['side']:5} | {r['scenario']:10} | "
              f"{r['n_features']:>5} | {r['n_folds']:>5} | "
              f"{r['mean_auc']:>5.3f} | {r['median_pf']:>7.2f} | "
              f"{r['mean_wr']:>5.1%} | {r['mean_ev_pct']*100:>5.3f}% | "
              f"{r['total_trades']:>6} | {v}")


def main():
    print("=" * 90)
    print("TRAIN DMP v2 CLEAN — labeler independant Triple Barrier close+ATR")
    print("=" * 90)

    df_es = load_dataset("ES")
    df_nq = load_dataset("NQ")
    print(f"\n[load] ES : {df_es.shape} | NQ : {df_nq.shape}")

    results = []

    for sym, df in [("ES", df_es), ("NQ", df_nq)]:
        print(f"\n--- {sym} ---")
        # Scenario A : DMP_BRUT (sans ctx/im/amd/rvol)
        feat_brut = get_feature_cols(df, exclude_derived=True)
        # Scenario B : DMP_FULL (tout sauf labels/returns/price)
        feat_full = get_feature_cols(df, exclude_derived=False)
        print(f"  Features DMP_BRUT : {len(feat_brut)}")
        print(f"  Features DMP_FULL : {len(feat_full)}")

        for side in ["buy", "sell"]:
            for scen, fcols in [("DMP_BRUT", feat_brut), ("DMP_FULL", feat_full)]:
                t0 = time.time()
                r = train_eval(df, sym, side, fcols, scenario_label=scen,
                                  n_splits=5, embargo=60)
                elapsed = time.time() - t0
                print(f"  {sym}_{side.upper()} [{scen}]: AUC={r.get('mean_auc', np.nan):.3f} "
                      f"PF_med={r.get('median_pf', np.nan):.2f} "
                      f"WR={r.get('mean_wr', np.nan):.1%} "
                      f"N_tr={r.get('total_trades', 0)} "
                      f"time={elapsed:.0f}s")
                results.append(r)

    print_results(results)

    # ─── INTERPRETATION ────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print("INTERPRETATION")
    print(f"{'=' * 90}")
    brut_results = [r for r in results if r.get("scenario") == "DMP_BRUT" and "error" not in r]
    full_results = [r for r in results if r.get("scenario") == "DMP_FULL" and "error" not in r]
    if brut_results and full_results:
        avg_brut_auc = np.nanmean([r["mean_auc"] for r in brut_results])
        avg_full_auc = np.nanmean([r["mean_auc"] for r in full_results])
        avg_brut_pf = np.nanmean([r["median_pf"] for r in brut_results])
        avg_full_pf = np.nanmean([r["median_pf"] for r in full_results])
        delta = avg_full_auc - avg_brut_auc
        print(f"AUC moyenne DMP_BRUT  : {avg_brut_auc:.3f}")
        print(f"AUC moyenne DMP_FULL  : {avg_full_auc:.3f}")
        print(f"PF moyenne DMP_BRUT   : {avg_brut_pf:.2f}")
        print(f"PF moyenne DMP_FULL   : {avg_full_pf:.2f}")
        print(f"Delta AUC (FULL-BRUT) : {delta:+.3f}")
        if delta > 0.05:
            print(">>> Features derivees (ctx/im/amd/rvol) AJOUTENT signal -> potentielle leak ou vrai edge")
        elif delta < -0.02:
            print(">>> Features derivees DEGRADENT -> noise")
        else:
            print(">>> Features derivees neutres")
        if avg_brut_auc >= 0.55 and avg_brut_pf >= 1.3:
            print(">>> DMP_BRUT seul a un edge -> NOUVELLE PISTE post-V5 NO-GO")
        else:
            print(">>> DMP_BRUT pas mieux que V5 -> confirme V5 NO-GO global")

    print("\nDONE")


if __name__ == "__main__":
    main()
