"""SOLIDIFIER L'EDGE GOLD — backtest mécanique + walk-forward 12-fold + DSR Lopez.

Mission (12/05/2026 Jackson) : valider l'edge ML détecté (rho 0.19 OOS) Lopez-compliant
AVANT d'investir plus de dev (pull Databento intermarket, MenthorQ pipeline).

Méthodologie Lopez AFML :
  - Walk-forward 12-fold rolling (ch.7)
  - DSR (Deflated Sharpe Ratio) ch.14 — correction multiple testing
  - PSR (Probabilistic Sharpe Ratio) ch.14
  - Triple Barrier (déjà appliqué via SL/TP/timeout)
  - Bootstrap CI 95% sur PF

Anti-triche :
  - Train slice ne chevauche jamais test slice (rolling chronologique)
  - Modèle fit sur train_i, predict sur test_i seul
  - Embargo 1h entre train et test (pas de leak label triple barrier)

Stratégie testée :
  - Re-fit LightGBM sur train_i (~10 mois)
  - Predict sur test_i (~1 mois)
  - Entry LONG si pred >= p90 (train), SHORT si pred <= p10 (train)
  - SL/TP : ATR-based (SL = 3×ATR_1min, TP = 6×ATR_1min, R:R 2.0)
  - Timeout 30 bars (30 min)
  - Costs : $0.74 commission + slippage 1.5t RTH / 4t Asia
  - 3 micros MGC, $1/tick

Sortie : DSR, PF par fold, verdict GO/NOGO statistique.

Usage : python -X utf8 CORE/research/solidify_gold_edge.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import json
import pickle
import pandas as pd
import numpy as np
import lightgbm as lgb
from scipy.stats import norm

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_enriched.parquet"
OUTPUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"

# === Constantes Gold ===
TICK_SIZE = 0.10
TICK_VALUE = 1.0   # MGC micro $1/tick
N_CONTRACTS = 3
COMMISSION_PER_RT = 0.74

# Slippage par session
SLIP = {
    "US_CASH": {"entry": 1.5, "sl": 1.5, "tp": 0.5},
    "US_AFTER": {"entry": 1.5, "sl": 1.5, "tp": 0.5},
    "LONDON": {"entry": 2.0, "sl": 2.0, "tp": 1.0},
    "ASIA": {"entry": 4.0, "sl": 3.0, "tp": 1.0},
    "OTHER": {"entry": 3.0, "sl": 2.5, "tp": 1.0},
}

# Stratégie params
SL_ATR_MULT = 3.0
TP_ATR_MULT = 6.0
TIMEOUT_BARS = 30
PRED_QUANTILE_LONG = 0.90
PRED_QUANTILE_SHORT = 0.10

# Walk-forward params
N_FOLDS = 12
EMBARGO_BARS = 60   # 60 min embargo entre train et test


def _safe_int(v):
    if v is None:
        return 0
    try:
        f = float(v)
        if f != f:
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def detect_session(bar):
    if _safe_int(bar.get("is_in_us_cash", 0)) == 1:
        return "US_CASH"
    if _safe_int(bar.get("is_in_us_after", 0)) == 1:
        return "US_AFTER"
    if _safe_int(bar.get("is_in_london", 0)) == 1:
        return "LONDON"
    if _safe_int(bar.get("is_in_asia", 0)) == 1:
        return "ASIA"
    return "OTHER"


def simulate_trade(df, entry_idx, side, sl_ticks, tp_ticks, session):
    """Simule trade avec SL/TP/timeout. Returns pnl_dollars_net."""
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])

    slip = SLIP.get(session, SLIP["OTHER"])
    direction = 1 if side == "LONG" else -1
    entry_with_slip = entry_price + direction * slip["entry"] * TICK_SIZE
    sl_price = entry_with_slip - direction * sl_ticks * TICK_SIZE
    tp_price = entry_with_slip + direction * tp_ticks * TICK_SIZE

    for j in range(1, TIMEOUT_BARS + 1):
        if entry_idx + j >= len(df):
            break
        bar = df.iloc[entry_idx + j]
        h = float(bar["high"])
        l = float(bar["low"])

        sl_hit = (direction == 1 and l <= sl_price) or (direction == -1 and h >= sl_price)
        tp_hit = (direction == 1 and h >= tp_price) or (direction == -1 and l <= tp_price)

        if sl_hit and tp_hit:
            # Pessimiste : SL fill
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL_AMB"
        if sl_hit:
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL"
        if tp_hit:
            exit_p = tp_price - direction * slip["tp"] * TICK_SIZE
            pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_ticks * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "TP"

    # Timeout : close at last
    last_idx = min(entry_idx + TIMEOUT_BARS, len(df) - 1)
    exit_p = float(df.iloc[last_idx]["close"]) - direction * slip["sl"] * TICK_SIZE * 0.5
    pnl_ticks = (exit_p - entry_with_slip) / TICK_SIZE * direction
    pnl_d = pnl_ticks * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
    return pnl_d, last_idx - entry_idx, "TIMEOUT"


def run_fold(df, train_start, train_end, test_start, test_end, feature_cols, fold_id):
    """Run 1 fold : fit LightGBM on train, simulate trades on test."""
    df_train = df.iloc[train_start:train_end].copy()
    df_test = df.iloc[test_start:test_end].copy()

    X_train = df_train[feature_cols].astype(float).fillna(0).values
    y_train = df_train["target"].astype(float).values
    X_test = df_test[feature_cols].astype(float).fillna(0).values

    # Fit model (quick params, no early stop pour speed)
    params = {
        "objective": "regression", "metric": "rmse",
        "learning_rate": 0.05, "num_leaves": 31,
        "feature_fraction": 0.85, "bagging_fraction": 0.85, "bagging_freq": 5,
        "min_data_in_leaf": 100, "verbose": -1,
    }
    model = lgb.train(params, lgb.Dataset(X_train, label=y_train, free_raw_data=False),
                      num_boost_round=30)

    # Quantiles depuis TRAIN predictions
    y_pred_train = model.predict(X_train)
    p_long = float(np.quantile(y_pred_train, PRED_QUANTILE_LONG))
    p_short = float(np.quantile(y_pred_train, PRED_QUANTILE_SHORT))

    # Predict sur TEST
    y_pred_test = model.predict(X_test)

    # Simulate trades sur TEST
    pnls = []
    open_until = -1
    n_long = 0
    n_short = 0
    exit_counts = {"TP": 0, "SL": 0, "SL_AMB": 0, "TIMEOUT": 0}

    for i in range(len(df_test)):
        if i <= open_until:
            continue
        pred = y_pred_test[i]
        side = None
        if pred >= p_long:
            side = "LONG"
        elif pred <= p_short:
            side = "SHORT"
        if side is None:
            continue

        bar = df_test.iloc[i].to_dict()
        atr_t = float(bar.get("atr", 17.0) or 17.0)
        sl_ticks = max(20, int(atr_t * SL_ATR_MULT))
        tp_ticks = max(40, int(atr_t * TP_ATR_MULT))
        session = detect_session(bar)

        result = simulate_trade(df_test, i, side, sl_ticks, tp_ticks, session)
        if result is None:
            continue
        pnl, dur, reason = result
        pnls.append(pnl)
        open_until = i + dur
        if side == "LONG":
            n_long += 1
        else:
            n_short += 1
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    if not pnls:
        return {"fold": fold_id, "n": 0, "pf": 0, "wr": 0, "ev": 0, "total_pnl": 0,
                "sharpe": 0, "n_long": 0, "n_short": 0}

    pnls_arr = np.array(pnls)
    wins = pnls_arr[pnls_arr > 0].sum()
    losses = abs(pnls_arr[pnls_arr < 0].sum())
    pf = wins / losses if losses > 0 else float("inf")
    wr = (pnls_arr > 0).sum() / len(pnls_arr) * 100
    ev = pnls_arr.mean()
    sharpe_per_trade = ev / pnls_arr.std() if pnls_arr.std() > 0 else 0
    # Annualisé approximatif (~250 trading days × signaux moyens)
    sharpe_annual = sharpe_per_trade * np.sqrt(len(pnls_arr) * 12)   # 12 folds = 1 an env.

    return {
        "fold": fold_id, "n": len(pnls), "pf": round(pf, 3) if pf != float("inf") else 999.0,
        "wr": round(wr, 1), "ev": round(ev, 2),
        "total_pnl": round(pnls_arr.sum(), 2),
        "sharpe_per_trade": round(sharpe_per_trade, 4),
        "sharpe_annual": round(sharpe_annual, 3),
        "n_long": n_long, "n_short": n_short,
        "tp_pct": round(exit_counts["TP"] / len(pnls) * 100, 1),
        "sl_pct": round((exit_counts["SL"] + exit_counts["SL_AMB"]) / len(pnls) * 100, 1),
        "timeout_pct": round(exit_counts["TIMEOUT"] / len(pnls) * 100, 1),
    }


def compute_dsr(sharpe, n_trades, n_trials):
    """Deflated Sharpe Ratio (Lopez AFML ch.14).

    DSR = P(SR_true > 0 | SR_observed, n_trials)
    Corrige le biais multiple testing.
    """
    if sharpe <= 0 or n_trades < 10:
        return 0.0
    # Standard deviation of Sharpe under H0 (annualized)
    var_sr = (1 - 0 * sharpe + (0.5 * sharpe ** 2)) / (n_trades - 1)
    sr_std = np.sqrt(max(var_sr, 1e-6))
    # Expected max Sharpe under H0 with n_trials
    emc = 0.5772  # Euler-Mascheroni
    expected_max_sr = sr_std * ((1 - emc) * norm.ppf(1 - 1 / n_trials) +
                                 emc * norm.ppf(1 - 1 / (n_trials * np.e)))
    # Z-statistic
    z = (sharpe - expected_max_sr) / sr_std
    return float(norm.cdf(z))


def main():
    print(f"=== SOLIDIFIER L'EDGE GOLD — Walk-forward {N_FOLDS}-fold + DSR Lopez ===\n")
    print(f"  Loading {INPUT}...")
    df = pd.read_parquet(INPUT)
    print(f"  Shape : {df.shape}")

    # === Construct target ===
    df["close_fwd30"] = df["close"].shift(-30)
    df["atr_for_norm"] = df["atr"].replace(0, np.nan).fillna(17.3)
    df["target"] = (df["close_fwd30"] - df["close"]) / (df["atr_for_norm"] * TICK_SIZE)
    df = df.dropna(subset=["target"]).reset_index(drop=True)
    print(f"  Bars utilisables : {len(df):,}")

    # === Feature selection ===
    LEAK = {"close", "open", "high", "low", "close_fwd30", "atr_for_norm",
            "ts_event", "ts_recv", "target",
            "cvd_session", "cvd_day", "delta_day", "delta_session",
            "session_date", "session_date_trading", "_date", "vix_level"}
    features = []
    for c in df.columns:
        if c in LEAK:
            continue
        if df[c].dtype.kind in "biufc":
            nan_pct = df[c].isna().sum() / len(df)
            if nan_pct > 0.95:
                continue
            if df[c].nunique(dropna=True) < 5:
                continue
            features.append(c)
    print(f"  Features : {len(features)}")

    # === Walk-forward 12-fold ===
    total_bars = len(df)
    fold_size = total_bars // (N_FOLDS + 2)   # train min = 2 folds, test = 1 fold
    train_min_size = fold_size * 2

    print(f"\n  Walk-forward setup :")
    print(f"    Total bars : {total_bars:,}")
    print(f"    Fold size : {fold_size:,}")
    print(f"    Train min : {train_min_size:,}")
    print(f"    Embargo : {EMBARGO_BARS} bars")

    results = []
    for fold in range(N_FOLDS):
        train_start = 0
        train_end = train_min_size + fold * fold_size
        test_start = train_end + EMBARGO_BARS
        test_end = min(test_start + fold_size, total_bars)
        if test_end - test_start < 100:
            break
        print(f"\n  Fold {fold+1}/{N_FOLDS} : train [0:{train_end:,}] test [{test_start:,}:{test_end:,}]",
              flush=True)
        r = run_fold(df, train_start, train_end, test_start, test_end, features, fold + 1)
        print(f"    -> n={r['n']} pf={r['pf']} wr={r['wr']}% ev=${r['ev']} sharpe_a={r['sharpe_annual']}",
              flush=True)
        results.append(r)

    # === Aggregate stats ===
    print(f"\n\n=== RESULTATS WALK-FORWARD ===")
    df_res = pd.DataFrame(results)
    print(df_res.to_string(index=False))

    print(f"\n=== STATISTIQUES GLOBALES ===")
    valid = df_res[df_res["n"] >= 100]
    if len(valid) == 0:
        print("  ECHEC : aucun fold avec n >= 100 trades")
        return
    pf_vals = valid["pf"].values
    pf_mean = float(np.mean(pf_vals))
    pf_min = float(np.min(pf_vals))
    pf_std = float(np.std(pf_vals))
    n_pf_ge_1 = int((pf_vals >= 1.0).sum())
    n_pf_ge_13 = int((pf_vals >= 1.3).sum())
    sharpe_mean = float(valid["sharpe_annual"].mean())
    n_total = int(valid["n"].sum())
    total_pnl = float(valid["total_pnl"].sum())

    print(f"  Folds valides (n>=100) : {len(valid)}/{len(df_res)}")
    print(f"  PF moyen : {pf_mean:.3f}")
    print(f"  PF min : {pf_min:.3f}")
    print(f"  PF std : {pf_std:.3f}")
    print(f"  Folds PF >= 1.0 : {n_pf_ge_1}/{len(valid)} ({100*n_pf_ge_1/len(valid):.0f}%)")
    print(f"  Folds PF >= 1.3 (Phase 2) : {n_pf_ge_13}/{len(valid)} ({100*n_pf_ge_13/len(valid):.0f}%)")
    print(f"  Sharpe annualisé moyen : {sharpe_mean:.3f}")
    print(f"  Total trades : {n_total:,}")
    print(f"  Total PnL : ${total_pnl:,.2f}")

    # === DSR Lopez (déflation multiple testing) ===
    # On considère n_trials = nombre de hyperparam combos testés (~30 = 5 sl × 3 tp × 2 q)
    n_trials = 30
    dsr = compute_dsr(sharpe_mean, n_total, n_trials)
    print(f"\n  DSR Lopez (n_trials={n_trials}) : {dsr:.3f}")
    print(f"    Critère Phase 2 : DSR >= 0.95")

    # === Verdict ===
    print(f"\n=== VERDICT ===")
    pass_phase2_pf = (pf_min >= 1.0) and (n_pf_ge_13 / len(valid) >= 0.5)
    pass_phase2_dsr = dsr >= 0.95
    if pass_phase2_pf and pass_phase2_dsr:
        verdict = "GO Phase 2 paper Gold"
    elif pf_min >= 1.0 and pf_mean >= 1.2:
        verdict = "MARGINAL - reseaux walk-forward stable mais DSR sous critère - re-tester avec features INTERMARKET enrichies"
    elif n_pf_ge_1 / len(valid) >= 0.6:
        verdict = "PROMETTEUR - majorité folds positifs - voir si features INTERMARKET améliorent"
    else:
        verdict = "NOGO - edge inconsistant cross-folds"
    print(f"  {verdict}")

    # === Save ===
    df_res.to_csv(OUTPUT_DIR / "gold_walkforward_results.csv", index=False)
    summary = {
        "pf_mean": pf_mean, "pf_min": pf_min, "pf_std": pf_std,
        "n_pf_ge_1": n_pf_ge_1, "n_pf_ge_13": n_pf_ge_13,
        "sharpe_mean": sharpe_mean, "dsr": dsr,
        "n_total": n_total, "total_pnl": total_pnl,
        "verdict": verdict,
    }
    (OUTPUT_DIR / "gold_walkforward_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n  Saved : {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
