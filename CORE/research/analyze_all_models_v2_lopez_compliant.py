"""analyze_all_models_v2_lopez_compliant.py — Analyse causale rigoureuse Lopez.

Correction des 4 problemes ml-trainer (28/04 NO-GO de v1) +
3 corrections ULTRATHINK ml-trainer (28/04 GO-AVEC-RESERVES) :
  1. PnL proxy OHLC-real BUY-only / SELL-only (sans reconciliation labeler)
  2. Walk-forward 70/30 chronologique + PURGE GAP Lopez ch.7 (60 bars excludent)
  3. Bootstrap CI 95% sur PF des combos retenus (1000 resamples)
  4. DSR Lopez ch.14 corrige pour multiple testing (n_tests = 560) +
     skewness/kurtosis empiriques (PnL bimodal R:R 2.0)

Critere GO combo :
  - PF train >= 1.5
  - PF test >= 0.7 × PF train (degradation < 30%)
  - CI 95% inferieur > 1.3
  - DSR > 0.95
  - N_test trades >= 30

USAGE LEGITIME DES COMBOS GO (regle souveraine 18/04 anti-pattern 11) :
  ✅ Voie A : creer feature derivee ML, laisser LightGBM juger via MDA
  ✅ Voie B : booster sample_weight sur bars matchant (Lopez ch.4-5)
  ✅ Voie C : meta-labeling Lopez ch.3 (modele secondaire learn-to-filter)
  ✅ Voie D : input Rules Trader PD attentiste (parallele ML, pas filtre)

USAGE INTERDIT (PATTERN 11 V1) :
  ❌ Filtrer post-prediction LightGBM en HARD (--apply-edge-filter)
  ❌ Hardcoder seuils dans signal_engine
  ❌ Cascader plusieurs combos en AND avec ML score

Reference : memory feedback_lightgbm_no_composite_indicators.md

Usage : python -X utf8 CORE/research/analyze_all_models_v2_lopez_compliant.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

K_SL = 1.5
K_TP_RATIO = 2.0
HORIZON = 60
TICK = 0.25
COST_TICKS = {"ES": 1.0, "NQ": 0.5}
N_BOOTSTRAP = 1000
N_TESTS_TOTAL = 560  # 35 binary x 2 + 31 cont x 2 = 132 par modele x 4 = 528 + 32 combos


# ==============================================================================
# Action 1 — PnL OHLC-real (BUY-only / SELL-only) via numba
# ==============================================================================


@numba.njit(cache=True)
def _simulate_buy_only_pnl(highs, lows, closes, atrs, k_sl, k_tp_ratio,
                            horizon, tick_size, cost_ticks):
    """Pour chaque bar i, simule un BUY trade independant.

    Retourne pnl_ticks par bar (taille n).
    """
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    for i in range(n - horizon - 1):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_ticks = k_sl * atr_t
        tp_ticks = k_tp_ratio * sl_ticks
        entry = closes[i]
        sl_lvl = entry - sl_ticks * tick_size
        tp_lvl = entry + tp_ticks * tick_size
        outcome = 0.0
        hit = False
        for k in range(1, horizon + 1):
            j = i + k
            if j >= n:
                break
            if lows[j] <= sl_lvl:
                outcome = -sl_ticks - cost_ticks
                hit = True
                break
            if highs[j] >= tp_lvl:
                outcome = tp_ticks - cost_ticks
                hit = True
                break
        if not hit:
            # timeout : marked-to-market sur close[i+horizon]
            j = i + horizon
            if j < n:
                outcome = (closes[j] - entry) / tick_size - cost_ticks
            else:
                outcome = -cost_ticks
        pnl[i] = outcome
    return pnl


@numba.njit(cache=True)
def _simulate_sell_only_pnl(highs, lows, closes, atrs, k_sl, k_tp_ratio,
                             horizon, tick_size, cost_ticks):
    """Pour chaque bar i, simule un SELL trade independant."""
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    for i in range(n - horizon - 1):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_ticks = k_sl * atr_t
        tp_ticks = k_tp_ratio * sl_ticks
        entry = closes[i]
        sl_lvl = entry + sl_ticks * tick_size
        tp_lvl = entry - tp_ticks * tick_size
        outcome = 0.0
        hit = False
        for k in range(1, horizon + 1):
            j = i + k
            if j >= n:
                break
            if highs[j] >= sl_lvl:
                outcome = -sl_ticks - cost_ticks
                hit = True
                break
            if lows[j] <= tp_lvl:
                outcome = tp_ticks - cost_ticks
                hit = True
                break
        if not hit:
            j = i + horizon
            if j < n:
                outcome = (entry - closes[j]) / tick_size - cost_ticks
            else:
                outcome = -cost_ticks
        pnl[i] = outcome
    return pnl


# ==============================================================================
# Metriques
# ==============================================================================


def compute_pf(pnl: np.ndarray) -> dict:
    if len(pnl) == 0 or np.all(pnl == 0):
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "total": 0, "sharpe": 0}
    nonzero = pnl[pnl != 0]  # filter out bars where simulation didn't fire (atr nan)
    if len(nonzero) == 0:
        return {"n": 0, "pf": 0, "wr": 0, "ev": 0, "total": 0, "sharpe": 0}
    wins = nonzero[nonzero > 0]
    losses = nonzero[nonzero < 0]
    n = len(nonzero)
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else float("inf")
    wr = len(wins) / n if n > 0 else 0
    ev = float(nonzero.mean())
    sharpe = float(nonzero.mean() / nonzero.std() * np.sqrt(252)) if nonzero.std() > 0 else 0
    return {"n": n, "pf": pf, "wr": wr, "ev": ev, "total": float(nonzero.sum()), "sharpe": sharpe}


def bootstrap_pf_ci(pnl: np.ndarray, n_resample: int = N_BOOTSTRAP,
                     ci: float = 0.95) -> dict:
    """Bootstrap PF distribution via resampling with replacement."""
    if len(pnl) < 30:
        return {"pf_mean": 0, "pf_lo": 0, "pf_hi": 0, "n_resample": 0}
    pfs = []
    rng = np.random.default_rng(seed=42)
    n = len(pnl)
    for _ in range(n_resample):
        idx = rng.integers(0, n, size=n)
        sample = pnl[idx]
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        if len(losses) == 0 or losses.sum() >= 0:
            continue  # skip pathological
        pfs.append(wins.sum() / -losses.sum())
    if not pfs:
        return {"pf_mean": 0, "pf_lo": 0, "pf_hi": 0, "n_resample": 0}
    pfs_arr = np.array(pfs)
    alpha = (1 - ci) / 2
    return {
        "pf_mean": float(pfs_arr.mean()),
        "pf_lo": float(np.quantile(pfs_arr, alpha)),
        "pf_hi": float(np.quantile(pfs_arr, 1 - alpha)),
        "n_resample": len(pfs),
    }


def deflated_sharpe_ratio(sharpe: float, n_trials: int, n_obs: int,
                           skewness: float = 0, kurtosis: float = 3) -> float:
    """DSR Lopez AFML ch.14 sec 14.5.

    Corrige Sharpe pour multiple testing (selection bias).
    Returns probability that true Sharpe > 0.

    Args:
        sharpe: Sharpe Ratio observe (annualise).
        n_trials: nombre de strategies testees.
        n_obs: nombre d'observations.
        skewness: skewness des returns (default 0 = normal).
        kurtosis: kurtosis (default 3 = normal).
    """
    from scipy.stats import norm

    # Expected max Sharpe under H0 (Lopez eq 14.4)
    if n_trials <= 1:
        return 1.0
    emc = 0.5772156649  # Euler-Mascheroni
    e_max_sr = (1 - emc) * norm.ppf(1 - 1/n_trials) + emc * norm.ppf(1 - 1/(n_trials * np.e))

    # Variance of Sharpe (Mertens 2002 — eq 14.5)
    var_sr = (1 - skewness * sharpe + (kurtosis - 1) / 4 * sharpe ** 2) / (n_obs - 1)
    if var_sr <= 0:
        return 0.5

    # DSR = P(SR > 0 | n_trials, observed Sharpe)
    z = (sharpe - e_max_sr) / np.sqrt(var_sr)
    dsr = norm.cdf(z)
    return float(dsr)


# ==============================================================================
# Analyse causale + train/test split
# ==============================================================================


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


def _filter_combo(df: pd.DataFrame, feat_b: str, target_b: int,
                   feat_c: str, op: str, threshold: float) -> np.ndarray:
    """Compute mask for combo (binary AND continuous)."""
    if op == ">=":
        return ((df[feat_b].fillna(-1).values == target_b) &
                (df[feat_c].fillna(-1e9).values >= threshold))
    else:
        return ((df[feat_b].fillna(-1).values == target_b) &
                (df[feat_c].fillna(1e9).values <= threshold))


def find_top_combos_train(df_train: pd.DataFrame, pnl_train: np.ndarray,
                           top_k: int = 5) -> list:
    """Identifie les TOP combos sur train set."""
    # Etape 1 : ranking binaires
    binary_results = []
    for feat in BINARY_FEATURES:
        if feat not in df_train.columns:
            continue
        vals = df_train[feat].fillna(-1).values
        m0 = vals == 0
        m1 = vals == 1
        if m0.sum() < 100 or m1.sum() < 100:
            continue
        pf0 = compute_pf(pnl_train[m0])
        pf1 = compute_pf(pnl_train[m1])
        better_target = 1 if pf1["pf"] > pf0["pf"] else 0
        better_pf = max(pf1["pf"], pf0["pf"])
        edge = abs(pf1["pf"] - pf0["pf"])
        binary_results.append({
            "feature": feat, "target": better_target, "pf": better_pf, "edge": edge,
        })
    binary_results.sort(key=lambda r: r["pf"], reverse=True)

    # Etape 2 : ranking continues
    cont_results = []
    for feat in CONTINUOUS_FEATURES:
        if feat not in df_train.columns:
            continue
        vals = df_train[feat].values
        valid = ~np.isnan(vals)
        if valid.sum() < 200:
            continue
        q25, q75 = np.nanquantile(vals, [0.25, 0.75])
        m_low = valid & (vals <= q25)
        m_high = valid & (vals >= q75)
        if m_low.sum() < 100 or m_high.sum() < 100:
            continue
        pf_low = compute_pf(pnl_train[m_low])
        pf_high = compute_pf(pnl_train[m_high])
        if pf_high["pf"] > pf_low["pf"]:
            op, thr, pf_v = ">=", q75, pf_high["pf"]
        else:
            op, thr, pf_v = "<=", q25, pf_low["pf"]
        edge = abs(pf_high["pf"] - pf_low["pf"])
        cont_results.append({
            "feature": feat, "op": op, "threshold": thr, "pf": pf_v, "edge": edge,
        })
    cont_results.sort(key=lambda r: r["pf"], reverse=True)

    # Etape 3 : combinaisons top3 binary x top3 continuous
    combos = []
    for tb in binary_results[:5]:
        for tc in cont_results[:5]:
            mask = _filter_combo(df_train, tb["feature"], tb["target"],
                                  tc["feature"], tc["op"], tc["threshold"])
            sample = pnl_train[mask]
            if len(sample) < 30:
                continue
            stats = compute_pf(sample)
            combos.append({
                "feat_b": tb["feature"], "target_b": tb["target"],
                "feat_c": tc["feature"], "op_c": tc["op"], "thr_c": tc["threshold"],
                "pf_train": stats["pf"], "n_train": stats["n"],
                "wr_train": stats["wr"], "ev_train": stats["ev"],
                "sharpe_train": stats["sharpe"],
            })
    combos.sort(key=lambda c: c["pf_train"], reverse=True)
    return combos[:top_k]


def validate_combo_test(combo: dict, df_test: pd.DataFrame,
                          pnl_test: np.ndarray) -> dict:
    """Valide un combo sur le test set."""
    mask = _filter_combo(df_test, combo["feat_b"], combo["target_b"],
                          combo["feat_c"], combo["op_c"], combo["thr_c"])
    sample_test = pnl_test[mask]
    stats = compute_pf(sample_test)
    return {
        "pf": stats["pf"], "n": stats["n"],  # pour acces facile dans loop
        "pf_test": stats["pf"], "n_test": stats["n"],
        "wr_test": stats["wr"], "ev_test": stats["ev"],
        "sharpe_test": stats["sharpe"],
    }


def analyze_model_v2(symbol: str, side: int, train_ratio: float = 0.7) -> dict:
    side_str = "BUY" if side == 1 else "SELL"
    print(f"\n{'='*100}")
    print(f"  {symbol} {side_str} — Analyse Lopez compliant (Action 1+2+3+4)")
    print(f"{'='*100}")

    fp = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
    df = pd.read_parquet(fp)
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)

    # Action 1 : PnL OHLC-real
    print(f"  [Action 1] Compute PnL OHLC-real {side_str}-only via numba...")
    t0 = time.perf_counter()
    highs = df["high"].values.astype(np.float64) if "high" in df.columns else df["bar_high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64) if "low" in df.columns else df["bar_low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)
    cost = COST_TICKS[symbol]
    if side == 1:
        pnl = _simulate_buy_only_pnl(highs, lows, closes, atrs,
                                      K_SL, K_TP_RATIO, HORIZON, TICK, cost)
    else:
        pnl = _simulate_sell_only_pnl(highs, lows, closes, atrs,
                                       K_SL, K_TP_RATIO, HORIZON, TICK, cost)
    print(f"             Done in {time.perf_counter()-t0:.1f}s, n_bars={len(pnl):,}")

    # Action 2 : Train/Test split chronologique 70/30 + PURGE GAP Lopez ch.7
    # FIX ULTRATHINK ml-trainer : leak temporel detecte empiriquement.
    # Le PnL OHLC-real des derniers HORIZON bars du train depend de OHLC futurs
    # qui sont dans le test set. Solution Lopez ch.7 : purger horizon bars en
    # fin du train (les n'incluent pas dans l'analyse).
    print(f"  [Action 2] Walk-forward 70/30 chronologique + Purge gap Lopez...")
    n = len(df)
    split_idx = int(n * train_ratio)
    purge_train_end = split_idx - HORIZON  # PURGE GAP = HORIZON bars
    df_train = df.iloc[:purge_train_end]
    df_test = df.iloc[split_idx:]
    pnl_train = pnl[:purge_train_end]
    pnl_test = pnl[split_idx:]
    train_dates = pd.to_datetime(df_train["ts"], unit="ms")
    test_dates = pd.to_datetime(df_test["ts"], unit="ms")
    print(f"             Train: {train_dates.min()} → {train_dates.max()} ({len(df_train):,} bars)")
    print(f"             Test : {test_dates.min()} → {test_dates.max()} ({len(df_test):,} bars)")
    print(f"             Purge gap : {HORIZON} bars exclus pour anti-leak temporel")

    # Baseline
    base_train = compute_pf(pnl_train)
    base_test = compute_pf(pnl_test)
    print(f"  Baseline {side_str} systematic :")
    print(f"             TRAIN PF={base_train['pf']:.2f} N={base_train['n']:,} WR={base_train['wr']*100:.1f}% EV={base_train['ev']:+.1f}t")
    print(f"             TEST  PF={base_test['pf']:.2f} N={base_test['n']:,} WR={base_test['wr']*100:.1f}% EV={base_test['ev']:+.1f}t")

    # Etape 3 : Identify TOP combos sur train
    print(f"  [Step 3] Identifying TOP 5 combos on TRAIN...")
    combos = find_top_combos_train(df_train, pnl_train, top_k=5)

    # Etape 4 : Valider sur test + Bootstrap CI + DSR
    print(f"\n  TOP 5 combos validation TEST + Bootstrap CI + DSR :")
    print(f"  {'Combo':<70s} {'PF_tr':>5s} {'PF_te':>5s} {'CI95_lo':>7s} {'CI95_hi':>7s} {'DSR':>5s} {'GO':>3s}")
    print(f"  {'-'*112}")

    results = []
    for c in combos:
        # Action 3 : Bootstrap CI sur train
        mask_tr = _filter_combo(df_train, c["feat_b"], c["target_b"],
                                 c["feat_c"], c["op_c"], c["thr_c"])
        ci = bootstrap_pf_ci(pnl_train[mask_tr])

        # Validate test
        test_stats = validate_combo_test(c, df_test, pnl_test)

        # Action 4 : DSR avec skewness/kurtosis EMPIRIQUES (PnL R:R 2.0 bimodal)
        # FIX ULTRATHINK ml-trainer : defaults normaux (skew=0, kurt=3) faussent DSR.
        from scipy.stats import skew as _skew, kurtosis as _kurt
        combo_pnl = pnl_train[mask_tr]
        nonzero_pnl = combo_pnl[combo_pnl != 0]
        if len(nonzero_pnl) >= 30:
            sk = float(_skew(nonzero_pnl))
            ku = float(_kurt(nonzero_pnl, fisher=False))  # Pearson kurtosis
        else:
            sk, ku = 0.0, 3.0
        n_obs = mask_tr.sum()
        dsr = deflated_sharpe_ratio(c["sharpe_train"], n_trials=N_TESTS_TOTAL,
                                      n_obs=n_obs, skewness=sk, kurtosis=ku)

        # Critere GO
        pf_te = test_stats["pf"]
        is_pf_test_ok = pf_te >= 0.7 * c["pf_train"]
        is_ci_ok = ci["pf_lo"] > 1.3
        is_dsr_ok = dsr > 0.95
        is_n_test_ok = test_stats["n_test"] >= 30
        is_go = is_pf_test_ok and is_ci_ok and is_dsr_ok and is_n_test_ok
        go_str = "GO" if is_go else "NO"

        combo_str = f"{c['feat_b']}={c['target_b']} AND {c['feat_c']}{c['op_c']}{c['thr_c']:.2f}"[:65]
        print(f"  {combo_str:<70s} {c['pf_train']:>5.2f} {pf_te:>5.2f} {ci['pf_lo']:>7.2f} {ci['pf_hi']:>7.2f} {dsr:>5.2f} {go_str:>3s}")

        results.append({
            **c, **test_stats,
            "ci_lo": ci["pf_lo"], "ci_hi": ci["pf_hi"],
            "dsr": dsr, "is_go": is_go,
        })

    # Recap GO/NO-GO
    n_go = sum(1 for r in results if r["is_go"])
    print(f"\n  {symbol} {side_str} : {n_go}/{len(results)} combos passent GO")

    return {
        "symbol": symbol, "side": side_str,
        "baseline_train": base_train, "baseline_test": base_test,
        "combos": results,
    }


def main():
    print("=" * 100)
    print("  ANALYSE CAUSALE LOPEZ-COMPLIANT — 4 modeles ES/NQ × BUY/SELL")
    print("  Actions 1-4 ml-trainer (28/04 NO-GO de v1)")
    print("=" * 100)
    print(f"  K_SL={K_SL} K_TP_ratio={K_TP_RATIO} H={HORIZON} bars")
    print(f"  Train/Test split : 70/30 chronologique")
    print(f"  Bootstrap : {N_BOOTSTRAP} resamples, CI 95%")
    print(f"  DSR n_trials = {N_TESTS_TOTAL}")
    print(f"  Critere GO : PF_test >= 0.7 × PF_train AND CI95_lo > 1.3 AND DSR > 0.95 AND N_test >= 30")

    all_results = []
    for symbol in ["ES", "NQ"]:
        for side in [1, -1]:
            r = analyze_model_v2(symbol, side)
            all_results.append(r)

    # Synthese
    print(f"\n\n{'='*100}")
    print(f"  SYNTHESE FINALE — Combos valides Lopez-compliant")
    print(f"{'='*100}")
    n_go_total = 0
    for r in all_results:
        go_combos = [c for c in r["combos"] if c["is_go"]]
        n_go_total += len(go_combos)
        print(f"\n  {r['symbol']} {r['side']} : {len(go_combos)} combo(s) GO")
        for c in go_combos:
            print(f"    {c['feat_b']}={c['target_b']} AND {c['feat_c']}{c['op_c']}{c['thr_c']:.2f}")
            print(f"      PF train={c['pf_train']:.2f} test={c['pf_test']:.2f} | CI95=[{c['ci_lo']:.2f}, {c['ci_hi']:.2f}] | DSR={c['dsr']:.2f}")
            print(f"      N test={c['n_test']} WR test={c['wr_test']*100:.1f}% EV test={c['ev_test']:+.1f}t")
    print(f"\n  TOTAL : {n_go_total} combos valides Lopez sur tous modeles")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
