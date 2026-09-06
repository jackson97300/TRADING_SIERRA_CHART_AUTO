"""ULTRATHINK 2/4 — Test ML refactor Bot3v4 (NQ 8 mois).

Objectif : evaluer si un modele ML peut remplacer / completer les regles
Bot3v4 pour le trading NQ.

3 options testees :
  ML-1 : PRIMARY rules + META ML filter
  ML-3 : Hybride (triggers + ML direction predictor)
  RULES : baseline Bot3v4 actuel (4 triggers nus)

Garde-fous Lopez : WF 8 folds, DSR avec n_trials, costs 5.2t NQ.
"""
from __future__ import annotations

import sys
import time
import glob
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT / "CORE"))

TICK = 0.25
TP_TICKS = 36
SL_TICKS = 20
TP_PTS = TP_TICKS * TICK
SL_PTS = SL_TICKS * TICK
FORWARD_BARS = 60
COOLDOWN_BARS = 30
MAX_PER_LEVEL_DAY = 2
TOUCH_BUFFER_PCT = 0.05
COSTS_TICKS = 5.2

TRIGGERS_LONG = [
    ("VWAP_D_SD2D", "dist_vwap_d_sd2d_pct"),
    ("CUR_VAL", "dist_cur_val_pct"),
]
TRIGGERS_SHORT = [
    ("VWAP_D_SD2U", "dist_vwap_d_sd2u_pct"),
    ("CUR_VAH", "dist_cur_vah_pct"),
]


def to_jsonable(obj):
    """Convert numpy/bool types to native Python types for JSON."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def load_nq_8m() -> pd.DataFrame:
    paths = sorted(glob.glob(
        str(ROOT / "DATA/DATASETS/v4_pure/symbol=NQ.c.0/year=*/month=*/data.parquet")
    ))
    print(f"[LOAD] {len(paths)} partitions NQ")
    dfs = [pd.read_parquet(p) for p in paths]
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"[LOAD] {len(df):,} bars total, range {df['ts_event'].min()} -> {df['ts_event'].max()}")
    return df


def detect_bot3v4_signals(df: pd.DataFrame) -> pd.DataFrame:
    print("[BOT3V4] Detection signaux 4 triggers (no SWING)...")
    n = len(df)
    signals = []
    state = {name: {"prev_in_zone": False, "last_signal_idx": -10000, "signals_today": 0}
             for name, _ in TRIGGERS_LONG + TRIGGERS_SHORT}
    day_arr = pd.to_datetime(df["ts_event"]).dt.date.values
    current_day = None

    for i in range(n):
        if day_arr[i] != current_day:
            current_day = day_arr[i]
            for name in state:
                state[name]["signals_today"] = 0
                state[name]["prev_in_zone"] = False

        for name, dist_col in TRIGGERS_LONG:
            if dist_col not in df.columns:
                continue
            dist_pct = df[dist_col].iloc[i]
            if pd.isna(dist_pct):
                state[name]["prev_in_zone"] = False
                continue
            in_zone = abs(dist_pct) <= TOUCH_BUFFER_PCT
            entered = (in_zone and not state[name]["prev_in_zone"])
            state[name]["prev_in_zone"] = in_zone
            if not entered:
                continue
            if i - state[name]["last_signal_idx"] < COOLDOWN_BARS:
                continue
            if state[name]["signals_today"] >= MAX_PER_LEVEL_DAY:
                continue
            state[name]["last_signal_idx"] = i
            state[name]["signals_today"] += 1
            signals.append({"bar_idx": i, "side": "LONG", "trigger": name,
                            "level_dist_pct": float(dist_pct)})

        for name, dist_col in TRIGGERS_SHORT:
            if dist_col not in df.columns:
                continue
            dist_pct = df[dist_col].iloc[i]
            if pd.isna(dist_pct):
                state[name]["prev_in_zone"] = False
                continue
            in_zone = abs(dist_pct) <= TOUCH_BUFFER_PCT
            entered = (in_zone and not state[name]["prev_in_zone"])
            state[name]["prev_in_zone"] = in_zone
            if not entered:
                continue
            if i - state[name]["last_signal_idx"] < COOLDOWN_BARS:
                continue
            if state[name]["signals_today"] >= MAX_PER_LEVEL_DAY:
                continue
            state[name]["last_signal_idx"] = i
            state[name]["signals_today"] += 1
            signals.append({"bar_idx": i, "side": "SHORT", "trigger": name,
                            "level_dist_pct": float(dist_pct)})

    sig_df = pd.DataFrame(signals)
    print(f"[BOT3V4] {len(sig_df)} signaux detectes "
          f"({(sig_df['side']=='LONG').sum()} LONG, {(sig_df['side']=='SHORT').sum()} SHORT)")
    return sig_df


def simulate_trades(df: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    print("[SIM] Simulation trades TP=36t SL=20t H=60bars...")
    highs = df["high"].values; lows = df["low"].values; closes = df["close"].values
    ts = df["ts_event"].values; n = len(df)
    outcomes, pnls, exit_idxs, holding = [], [], [], []
    for _, sig in signals.iterrows():
        i = sig["bar_idx"]; side = sig["side"]; entry = closes[i]
        if side == "LONG":
            tp_price, sl_price = entry + TP_PTS, entry - SL_PTS
        else:
            tp_price, sl_price = entry - TP_PTS, entry + SL_PTS
        outcome, pnl, exit_idx, h_bars = "TIMEOUT", 0.0, i + FORWARD_BARS, FORWARD_BARS
        for k in range(1, FORWARD_BARS + 1):
            if i + k >= n:
                break
            h, l = highs[i + k], lows[i + k]
            if side == "LONG":
                if l <= sl_price: outcome, pnl, exit_idx, h_bars = "SL", -SL_TICKS, i+k, k; break
                if h >= tp_price: outcome, pnl, exit_idx, h_bars = "TP", TP_TICKS, i+k, k; break
            else:
                if h >= sl_price: outcome, pnl, exit_idx, h_bars = "SL", -SL_TICKS, i+k, k; break
                if l <= tp_price: outcome, pnl, exit_idx, h_bars = "TP", TP_TICKS, i+k, k; break
        outcomes.append(outcome); pnls.append(pnl); exit_idxs.append(exit_idx); holding.append(h_bars)

    out = signals.copy()
    out["outcome"] = outcomes
    out["pnl_ticks_gross"] = pnls
    out["pnl_ticks_net"] = [p - COSTS_TICKS for p in pnls]
    out["exit_idx"] = exit_idxs
    out["holding_bars"] = holding
    out["entry_ts"] = ts[signals["bar_idx"].values]
    n_tp = (out["outcome"] == "TP").sum()
    n_sl = (out["outcome"] == "SL").sum()
    n_to = (out["outcome"] == "TIMEOUT").sum()
    print(f"[SIM] {len(out)} trades : TP={n_tp} SL={n_sl} TIMEOUT={n_to} "
          f"(WR={n_tp/max(1,len(out))*100:.1f}%)")
    print(f"[SIM] PnL gross : {out['pnl_ticks_gross'].sum():.0f}t "
          f"({out['pnl_ticks_gross'].mean():.2f}/trade)")
    print(f"[SIM] PnL net : {out['pnl_ticks_net'].sum():.0f}t "
          f"({out['pnl_ticks_net'].mean():.2f}/trade)")
    return out


def compute_metrics(trades: pd.DataFrame, fold_label: str = "all") -> Dict:
    if len(trades) == 0:
        return {"fold": fold_label, "n": 0, "wr": 0.0, "pf": 0.0, "ev_net": 0.0,
                "maxdd": 0.0, "sharpe": 0.0, "hhi_top5": 0.0, "pnl_total_net": 0.0}
    pnl_net = trades["pnl_ticks_net"].values.astype(float)
    n = len(pnl_net)
    wr = float((pnl_net > 0).mean() * 100)
    gross_win = float(pnl_net[pnl_net > 0].sum())
    gross_loss = float(-pnl_net[pnl_net < 0].sum())
    pf = gross_win / max(0.01, gross_loss)
    ev_net = float(pnl_net.mean())
    cumpnl = pnl_net.cumsum()
    maxdd = float((np.maximum.accumulate(cumpnl) - cumpnl).max())
    sharpe = float(pnl_net.mean() / max(0.01, pnl_net.std()) * np.sqrt(252))
    abs_pnl = np.abs(pnl_net)
    top5_share = float(np.sort(abs_pnl)[-5:].sum() / max(0.01, abs_pnl.sum()))
    return {
        "fold": fold_label, "n": int(n), "wr": round(wr, 1), "pf": round(pf, 2),
        "ev_net": round(ev_net, 2), "maxdd": round(maxdd, 0),
        "sharpe": round(sharpe, 2), "hhi_top5": round(top5_share, 3),
        "pnl_total_net": round(float(pnl_net.sum()), 0),
    }


def walk_forward_8folds(trades: pd.DataFrame) -> List[Dict]:
    trades = trades.copy()
    trades["ts"] = pd.to_datetime(trades["entry_ts"])
    trades["year_month"] = trades["ts"].dt.strftime("%Y-%m")
    folds = sorted(trades["year_month"].unique())
    print(f"[FOLDS] {len(folds)} folds : {folds}")
    return [compute_metrics(trades[trades["year_month"] == f], fold_label=f) for f in folds]


CANDIDATE_FEATS = [
    "atr_14m_pct", "vwap_slope_30", "im_rolling_correlation_10",
    "vix_level", "n_trades_z", "volume_z",
    "delta_bar", "vwap_offset_pct", "bar_range_pct", "session_id",
    "im_smt_divergence", "im_cross_delta_agreement_5",
    "ctx_poc_migration_10", "bars_since_last_spike",
    "dist_color_dn_nearest_pct", "dist_color_up_nearest_pct",
    "finish_pct_up", "finish_strength", "bar_body_pct",
    "bar_upper_wick_pct", "bar_lower_wick_pct",
    "position_in_range", "roll_phase", "pct_in_range",
]


def build_meta_feature_matrix(df, trades, feats_avail):
    rows = []
    for _, tr in trades.iterrows():
        i = tr["bar_idx"]
        fv = {}
        for f in feats_avail:
            v = df[f].iloc[i]
            try:
                fv[f] = float(v) if pd.notna(v) else np.nan
            except (TypeError, ValueError):
                fv[f] = np.nan
        fv["level_dist_pct"] = float(tr["level_dist_pct"])
        for t in ["VWAP_D_SD2D", "CUR_VAL", "VWAP_D_SD2U", "CUR_VAH"]:
            fv[f"trigger_{t}"] = 1.0 if tr["trigger"] == t else 0.0
        fv["side_LONG"] = 1.0 if tr["side"] == "LONG" else 0.0
        rows.append(fv)
    return pd.DataFrame(rows)


def train_meta_lightgbm(df, trades, train_months):
    try:
        import lightgbm as lgb
    except ImportError:
        return None, [], []
    feats_avail = [c for c in CANDIDATE_FEATS if c in df.columns]
    train_trades = trades[trades["year_month"].isin(train_months)].copy()
    if len(train_trades) < 30:
        return None, [], []
    X = build_meta_feature_matrix(df, train_trades, feats_avail)
    y = (train_trades["outcome"] == "TP").astype(int).values
    feat_cols = list(X.columns)
    X = X.astype(np.float64)
    if y.sum() < 5 or (y == 0).sum() < 5:
        return None, [], []
    model = lgb.LGBMClassifier(num_leaves=15, max_depth=4, learning_rate=0.05,
                                n_estimators=200, min_child_samples=10,
                                reg_alpha=0.1, reg_lambda=0.1, verbose=-1)
    model.fit(X, y)
    fi = model.feature_importances_
    top_feats = [feat_cols[i] for i in np.argsort(fi)[::-1][:10]]
    return model, feat_cols, top_feats


def predict_meta(model, feat_cols, df, trades):
    feats_in_df = [c for c in feat_cols if c in df.columns]
    X = build_meta_feature_matrix(df, trades, feats_in_df)
    for c in feat_cols:
        if c not in X.columns:
            X[c] = 0.0
    X = X[feat_cols].astype(np.float64)
    return model.predict_proba(X)[:, 1]


def walk_forward_meta(df, trades, threshold=0.55):
    trades = trades.copy()
    trades["ts"] = pd.to_datetime(trades["entry_ts"])
    trades["year_month"] = trades["ts"].dt.strftime("%Y-%m")
    months = sorted(trades["year_month"].unique())
    fold_metrics, all_top_feats = [], []
    for i, test_m in enumerate(months):
        train_m = months[:i]
        if len(train_m) < 2:
            continue
        model, feat_cols, top_feats = train_meta_lightgbm(df, trades, train_m)
        if model is None:
            continue
        all_top_feats.append(top_feats)
        test_trades = trades[trades["year_month"] == test_m].copy()
        if len(test_trades) == 0:
            continue
        proba = predict_meta(model, feat_cols, df, test_trades)
        test_trades["proba_meta"] = proba
        filtered = test_trades[test_trades["proba_meta"] >= threshold].copy()
        m = compute_metrics(filtered, fold_label=f"{test_m}_meta>={threshold:.2f}")
        m["n_signals_before"] = int(len(test_trades))
        m["pct_kept"] = round(len(filtered) / max(1, len(test_trades)) * 100, 1)
        fold_metrics.append(m)
    feat_counts = {}
    for tf in all_top_feats:
        for f in tf:
            feat_counts[f] = feat_counts.get(f, 0) + 1
    top10 = sorted(feat_counts.items(), key=lambda x: -x[1])[:10]
    return fold_metrics, {"top10_feats_freq": top10}


def dsr_lopez(metrics_list, n_trials=3):
    sharpes = [m["sharpe"] for m in metrics_list if m["n"] >= 5]
    if len(sharpes) < 3:
        return 0.0
    sr_mean = float(np.mean(sharpes))
    sr_std = float(np.std(sharpes, ddof=1))
    if sr_std == 0:
        return 1.0 if sr_mean > 0 else 0.0
    try:
        from scipy.stats import norm
        z = sr_mean / (sr_std / np.sqrt(len(sharpes)))
        haircut = float(np.sqrt(2 * np.log(n_trials)) * 0.5)
        return float(norm.cdf(z - haircut))
    except ImportError:
        return float(0.5 + 0.5 * np.tanh(sr_mean / max(sr_std, 0.01)))


def verdict_option(name, fold_metrics, n_trials=3):
    valid = [m for m in fold_metrics if m["n"] >= 5]
    n_total = sum(m["n"] for m in fold_metrics)
    if n_total == 0 or len(valid) == 0:
        return {"option": name, "verdict": "NOGO_NO_TRADES", "n_total": 0,
                "pf_agg": 0, "wr_agg": 0, "ev_agg_ticks": 0, "dsr_lopez": 0,
                "pct_folds_pf_above_13": 0, "n_folds_valid": 0,
                "hhi_top5_avg": 0, "pnl_total_net_ticks": 0,
                "criteria": {}, "n_pass_criteria": "0/6"}
    pnl_agg = sum(m["ev_net"] * m["n"] for m in fold_metrics)
    ev_agg = pnl_agg / max(1, n_total)
    wr_agg = sum(m["wr"] * m["n"] for m in fold_metrics) / max(1, n_total)
    pf_agg = sum(m["pf"] * m["n"] for m in fold_metrics) / max(1, n_total)
    n_above = sum(1 for m in valid if m["pf"] >= 1.3)
    pct_stable = n_above / max(1, len(valid)) * 100
    dsr = dsr_lopez(fold_metrics, n_trials=n_trials)
    avg_hhi = float(np.mean([m["hhi_top5"] for m in valid]))
    criteria = {
        "PF_agg>=1.3": bool(pf_agg >= 1.3),
        "WR_agg>=45": bool(wr_agg >= 45),
        "EV_agg>=1.0t": bool(ev_agg >= 1.0),
        "DSR>=0.5": bool(dsr >= 0.5),
        "stab>=50pct": bool(pct_stable >= 50),
        "concentration<33pct": bool(avg_hhi < 0.33),
    }
    n_pass = int(sum(criteria.values()))
    if n_pass == 6:
        verdict = "GO"
    elif n_pass >= 4:
        verdict = "GO_RESERVES"
    else:
        verdict = "NOGO"
    return {
        "option": name, "verdict": verdict, "n_pass_criteria": f"{n_pass}/6",
        "criteria": criteria, "n_total": int(n_total), "pf_agg": round(pf_agg, 2),
        "wr_agg": round(wr_agg, 1), "ev_agg_ticks": round(ev_agg, 2),
        "dsr_lopez": round(dsr, 3), "pct_folds_pf_above_13": round(pct_stable, 1),
        "n_folds_valid": int(len(valid)), "hhi_top5_avg": round(avg_hhi, 3),
        "pnl_total_net_ticks": round(float(pnl_agg), 0),
    }


def walk_forward_ml3_hybrid(df, trades, threshold=0.55, bar_labels_long=None, bar_labels_short=None):
    """ML-3 hybride : signal Bot3v4 + ML direction predictor proba >= seuil."""
    try:
        import lightgbm as lgb
    except ImportError:
        return [], []
    trades = trades.copy()
    trades["ts"] = pd.to_datetime(trades["entry_ts"])
    trades["year_month"] = trades["ts"].dt.strftime("%Y-%m")
    months = sorted(trades["year_month"].unique())
    feats_avail = [c for c in CANDIDATE_FEATS if c in df.columns]
    df_ts = pd.to_datetime(df["ts_event"]).dt.strftime("%Y-%m").values
    fold_metrics, all_top_feats = [], []
    for i_m, test_m in enumerate(months):
        train_m = months[:i_m]
        if len(train_m) < 2:
            continue
        train_mask = np.isin(df_ts, train_m)
        if train_mask.sum() < 1000:
            continue
        X_train = df.loc[train_mask, feats_avail].astype(np.float64).fillna(0.0)
        y_long = (bar_labels_long[train_mask] == 1).astype(int)
        y_short = (bar_labels_short[train_mask] == 1).astype(int)
        if y_long.sum() < 50 or y_short.sum() < 50:
            continue
        m_long = lgb.LGBMClassifier(num_leaves=15, max_depth=4, learning_rate=0.05,
                                     n_estimators=200, verbose=-1)
        m_long.fit(X_train, y_long)
        m_short = lgb.LGBMClassifier(num_leaves=15, max_depth=4, learning_rate=0.05,
                                      n_estimators=200, verbose=-1)
        m_short.fit(X_train, y_short)
        # Track top feats LONG
        fi = m_long.feature_importances_
        all_top_feats.append([feats_avail[i] for i in np.argsort(fi)[::-1][:10]])

        test_trades = trades[trades["year_month"] == test_m].copy()
        if len(test_trades) == 0:
            continue
        idxs = test_trades["bar_idx"].values
        X_test = df.loc[idxs, feats_avail].astype(np.float64).fillna(0.0)
        proba_long = m_long.predict_proba(X_test)[:, 1]
        proba_short = m_short.predict_proba(X_test)[:, 1]
        test_trades["proba_ml_long"] = proba_long
        test_trades["proba_ml_short"] = proba_short
        keep = np.where(test_trades["side"].values == "LONG",
                        proba_long >= threshold, proba_short >= threshold)
        filtered = test_trades[keep].copy()
        mm = compute_metrics(filtered, fold_label=f"{test_m}_ml3>={threshold:.2f}")
        mm["n_signals_before"] = int(len(test_trades))
        mm["pct_kept"] = round(len(filtered) / max(1, len(test_trades)) * 100, 1)
        fold_metrics.append(mm)
    feat_counts = {}
    for tf in all_top_feats:
        for f in tf:
            feat_counts[f] = feat_counts.get(f, 0) + 1
    top10 = sorted(feat_counts.items(), key=lambda x: -x[1])[:10]
    return fold_metrics, top10


def precompute_bar_labels(df):
    print("[ML3] Pre-computing bar-level Triple Barrier labels...")
    n = len(df)
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    bll = np.zeros(n, dtype=np.int8)
    bls = np.zeros(n, dtype=np.int8)
    for i in range(n - FORWARD_BARS):
        entry = closes[i]
        tp_l, sl_l = entry + TP_PTS, entry - SL_PTS
        tp_s, sl_s = entry - TP_PTS, entry + SL_PTS
        for k in range(1, FORWARD_BARS + 1):
            h, l = highs[i + k], lows[i + k]
            if bll[i] == 0:
                if l <= sl_l: bll[i] = -1
                elif h >= tp_l: bll[i] = 1
            if bls[i] == 0:
                if h >= sl_s: bls[i] = -1
                elif l <= tp_s: bls[i] = 1
            if bll[i] != 0 and bls[i] != 0:
                break
    print(f"[ML3] LONG : {(bll==1).sum()} TP, {(bll==-1).sum()} SL")
    print(f"[ML3] SHORT : {(bls==1).sum()} TP, {(bls==-1).sum()} SL")
    return bll, bls


def main():
    t0 = time.perf_counter()
    print("=" * 70)
    print("ULTRATHINK 2/4 — Bot3v4 ML refactor evaluation")
    print("=" * 70)
    df = load_nq_8m()
    signals = detect_bot3v4_signals(df)
    if len(signals) == 0:
        print("[FATAL] Aucun signal"); return
    trades = simulate_trades(df, signals)
    trades["ts"] = pd.to_datetime(trades["entry_ts"])
    trades["year_month"] = trades["ts"].dt.strftime("%Y-%m")

    # RULES baseline
    print("\n" + "=" * 70)
    print("OPTION RULES (Bot3v4 actuel)")
    print("=" * 70)
    rules_folds = walk_forward_8folds(trades)
    for m in rules_folds:
        print(f"  {m['fold']} : n={m['n']} WR={m['wr']:.1f}% PF={m['pf']:.2f} "
              f"EV={m['ev_net']:.1f}t MaxDD={m['maxdd']:.0f} Sharpe={m['sharpe']:.2f}")
    rules_verdict = verdict_option("RULES", rules_folds)

    # ML-1 meta filter
    print("\n" + "=" * 70)
    print("OPTION ML-1 : PRIMARY rules + META LightGBM filter")
    print("=" * 70)
    ml1_verdicts, ml1_top_feats = {}, {}
    for thr in [0.50, 0.55, 0.60]:
        print(f"\n  --- Threshold = {thr} ---")
        f, info = walk_forward_meta(df, trades, threshold=thr)
        for m in f:
            print(f"    {m['fold']} : n={m['n']}/{m.get('n_signals_before',0)} "
                  f"({m.get('pct_kept',0)}%) WR={m['wr']:.1f}% PF={m['pf']:.2f} "
                  f"EV={m['ev_net']:.1f}t")
        ml1_verdicts[thr] = verdict_option(f"ML1_thr{thr}", f)
        ml1_top_feats[thr] = info["top10_feats_freq"]

    # ML-3 hybrid
    print("\n" + "=" * 70)
    print("OPTION ML-3 : Hybride triggers + ML direction predictor")
    print("=" * 70)
    bll, bls = precompute_bar_labels(df)
    ml3_verdicts, ml3_top_feats = {}, {}
    for thr in [0.40, 0.50, 0.55]:
        print(f"\n  --- Threshold ML direction = {thr} ---")
        f, top = walk_forward_ml3_hybrid(df, trades, threshold=thr,
                                          bar_labels_long=bll, bar_labels_short=bls)
        for m in f:
            print(f"    {m['fold']} : n={m['n']}/{m.get('n_signals_before',0)} "
                  f"({m.get('pct_kept',0)}%) WR={m['wr']:.1f}% PF={m['pf']:.2f} "
                  f"EV={m['ev_net']:.1f}t")
        ml3_verdicts[thr] = verdict_option(f"ML3_thr{thr}", f)
        ml3_top_feats[thr] = top

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY VERDICTS")
    print("=" * 70)
    print(json.dumps(to_jsonable(rules_verdict), indent=2))
    for thr, v in ml1_verdicts.items():
        print(f"\n--- ML-1 thr={thr} ---")
        print(json.dumps(to_jsonable(v), indent=2))
    for thr, v in ml3_verdicts.items():
        print(f"\n--- ML-3 thr={thr} ---")
        print(json.dumps(to_jsonable(v), indent=2))

    out = {
        "rules": {"verdict": rules_verdict, "folds": rules_folds},
        "ml1": {str(thr): {"verdict": ml1_verdicts[thr], "top_feats": ml1_top_feats[thr]}
                for thr in ml1_verdicts},
        "ml3": {str(thr): {"verdict": ml3_verdicts[thr], "top_feats": ml3_top_feats[thr]}
                for thr in ml3_verdicts},
        "metadata": {
            "n_signals_total": int(len(trades)),
            "n_bars_total": int(len(df)),
            "tp_ticks": TP_TICKS, "sl_ticks": SL_TICKS,
            "forward_bars": FORWARD_BARS, "costs_ticks": COSTS_TICKS,
            "n_trials": 3,
        },
    }
    out_path = ROOT / "DOCS" / "ULTRATHINK_2_BOT3V4_ML_REFACTOR.json"
    out_path.write_text(json.dumps(to_jsonable(out), indent=2, default=str))
    print(f"\n[SAVED] {out_path}")
    print(f"\n[TIME] {time.perf_counter()-t0:.1f}s")


if __name__ == "__main__":
    main()
