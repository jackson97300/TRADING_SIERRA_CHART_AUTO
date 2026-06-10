"""phase_signature_backtest_v3_dbn.py — DATABENTO PUR (zero feature DMP).

Jackson 09/05 directive : "ON DOIT UTILISER EXCLUSIVEMENT LES DONNEES DATABENTO
POUR TOUT BACKTEST". Le DMP a un historique de bug arr[sz-1] qui pollue les
backfills (cf incident 15/04 feedback_bug_arr_sz_1_systemique.md).

Source verifiee :
  - long_up_bar / long_dn_bar : phase_b_plus_engine.py:265 (OHLC Databento pur)
  - n_long_up_cluster_within_0_2pct : phase_b_plus_engine.py:363 (extension lines Python)
  - n_color_up_cluster_within_0_2pct : phase_b_plus_engine.py:222 (Trades Databento agreges)
  - dist_ib_low/high_pct : OHLC Databento + horaires (Python pur)
  - dist_last_swing_low/high_pct : OHLC Databento (Python pur)
  - dist_pdl/pdh_pct : OHLC daily Databento (Python pur)
  - dist_prev_val/vah_pct : Trades Databento + value area (Python pur)
  - dist_cur_val/vah_pct : Phase C running cumsum (Python pur)

EXCLUS (sources DMP suspect) :
  - dist_mq_* (MenthorQ levels via DMP JSONL)
  - dist_gex_* (Gamma exposure via DMP JSONL)
  - mq_* (toutes features MenthorQ)

Variantes :
  A. Retouche LONG seule
  B. Retouche LONG + pressure 5b contraire
  C. B + niveau Databento pur actif (IB, Swing, PDL/H, PVAL/H, CUR_VAL/H)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}

N_LONG_UP_CLUSTER = "n_long_up_cluster_within_0_2pct"
N_LONG_DN_CLUSTER = "n_long_dn_cluster_within_0_2pct"
N_COLOR_UP_CLUSTER = "n_color_up_cluster_within_0_2pct"
N_COLOR_DN_CLUSTER = "n_color_dn_cluster_within_0_2pct"
LONG_UP_BAR = "long_up_bar"
LONG_DN_BAR = "long_dn_bar"

# ─── NIVEAUX DATABENTO PUR (calcules Python depuis OHLCV/Trades) ───
# AUCUN niveau DMP (pas de MQ_*, GEX_*, blind_*)
SUPPORT_LEVELS_DBN = [
    ("dist_ib_low_pct", 0.05),
    ("dist_last_swing_low_pct", 0.05),
    ("dist_pdl_pct", 0.10),
    ("dist_prev_val_pct", 0.10),
    ("dist_cur_val_pct", 0.05),
    ("dist_asia_low_pct", 0.05),
    ("dist_london_low_pct", 0.05),
    ("dist_cash_low_pct", 0.05),
]
RESISTANCE_LEVELS_DBN = [
    ("dist_ib_high_pct", 0.05),
    ("dist_last_swing_high_pct", 0.05),
    ("dist_pdh_pct", 0.10),
    ("dist_prev_vah_pct", 0.10),
    ("dist_cur_vah_pct", 0.05),
    ("dist_asia_high_pct", 0.05),
    ("dist_london_high_pct", 0.05),
    ("dist_cash_high_pct", 0.05),
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def precompute_signals(df, pressure_window=5):
    """Vectorise. Retourne dict de boolean arrays par mode."""
    n = len(df)
    n_long_up = df.get(N_LONG_UP_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_long_dn = df.get(N_LONG_DN_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_color_up = df.get(N_COLOR_UP_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_color_dn = df.get(N_COLOR_DN_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    long_up = (df.get(LONG_UP_BAR, pd.Series(np.zeros(n))).fillna(0).to_numpy() > 0).astype(int)
    long_dn = (df.get(LONG_DN_BAR, pd.Series(np.zeros(n))).fillna(0).to_numpy() > 0).astype(int)
    bin_color_up = (n_color_up > 0).astype(int)
    bin_color_dn = (n_color_dn > 0).astype(int)

    def rolling_sum_lag(arr, w):
        s = pd.Series(arr).rolling(window=w, min_periods=1).sum().shift(1).fillna(0).to_numpy()
        return s

    p_dn = rolling_sum_lag(long_dn + bin_color_dn, pressure_window)
    p_up = rolling_sum_lag(long_up + bin_color_up, pressure_window)

    is_in_long_up = n_long_up >= 1
    is_in_long_dn = n_long_dn >= 1

    return {
        "A_pure":      {"spring": is_in_long_up, "utad": is_in_long_dn},
        "B_pressure":  {"spring": is_in_long_up & (p_dn >= 1),
                         "utad": is_in_long_dn & (p_up >= 1)},
        "B_strong":    {"spring": is_in_long_up & (p_dn >= 2),
                         "utad": is_in_long_dn & (p_up >= 2)},
    }


def precompute_level_active(df, kind="support"):
    """Boolean : au moins 1 niveau DBN actif."""
    n = len(df)
    levels = SUPPORT_LEVELS_DBN if kind == "support" else RESISTANCE_LEVELS_DBN
    active = np.zeros(n, dtype=bool)
    for col, thresh in levels:
        if col in df.columns:
            v = df[col].fillna(99.0).abs().to_numpy()
            active = active | (v <= thresh)
    return active


def simulate_trades_vectorise(df, signal_mask, direction, sym,
                               tp_ticks=24, sl_ticks=12, fwd_bars=30, cooldown=45):
    """Vectorise simulate trades a partir d'un mask de signaux."""
    n = len(df)
    tick = TICK_SIZE[sym]
    cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    trades = []
    last = -cooldown
    signal_idxs = np.where(signal_mask)[0]
    for i in signal_idxs:
        if i - last < cooldown:
            continue
        if i + fwd_bars >= n:
            break
        entry = closes[i]
        if direction == "BUY":
            tp = entry + tp_ticks * tick
            sl = entry - sl_ticks * tick
        else:
            tp = entry - tp_ticks * tick
            sl = entry + sl_ticks * tick
        # Iter intra-bar pour path-dependence
        exit_reason = "TIMEOUT"
        pnl = 0.0
        for k in range(i + 1, min(i + fwd_bars + 1, n)):
            bh = highs[k]; bl = lows[k]
            if direction == "BUY":
                sl_hit = bl <= sl
                tp_hit = bh >= tp
            else:
                sl_hit = bh >= sl
                tp_hit = bl <= tp
            if sl_hit and tp_hit:
                exit_reason = "SL_PESS"; pnl = -float(sl_ticks) - cost; break
            if sl_hit:
                exit_reason = "SL"; pnl = -float(sl_ticks) - cost; break
            if tp_hit:
                exit_reason = "TP"; pnl = float(tp_ticks) - cost; break
        else:
            # Timeout
            final = closes[min(i + fwd_bars, n - 1)]
            pnl = ((final - entry) if direction == "BUY" else (entry - final)) / tick - cost
        trades.append({"entry_idx": i, "direction": direction,
                       "exit": exit_reason, "pnl_ticks": float(pnl)})
        last = i
    return trades


def metrics(pnls, label=""):
    if not len(pnls):
        return {"label": label, "n": 0, "wr": 0, "pf": 0, "ev": 0, "psr": 0, "sharpe": 0}
    pnls = np.asarray(pnls)
    n = len(pnls)
    wr = (pnls > 0).mean()
    sw = pnls[pnls > 0].sum()
    sl = abs(pnls[pnls < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = pnls.mean()
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
    if pnls.std() > 0 and n > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(pnls); kt = kurtosis(pnls, fisher=False)
        sr = pnls.mean() / pnls.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n - 1) / denom))
    else:
        psr = 0.5
    return {"label": label, "n": n, "wr": wr, "pf": pf, "ev": ev, "sharpe": sharpe, "psr": psr}


def walk_forward_pf(trades, n_folds=12):
    if len(trades) < n_folds * 5:
        return {"pf_min": 0, "pf_med": 0, "n_pos": 0, "stable": False}
    pnls = [t["pnl_ticks"] for t in trades]
    cuts = np.linspace(0, len(pnls), n_folds + 1, dtype=int)
    pfs = []
    for k in range(n_folds):
        sub = pnls[cuts[k]:cuts[k + 1]]
        sw = sum(p for p in sub if p > 0)
        sl = sum(abs(p) for p in sub if p < 0)
        pf = sw / sl if sl > 0 else 99.0
        pfs.append(pf)
    return {"pf_min": float(min(pfs)), "pf_med": float(np.median(pfs)),
            "n_pos": sum(1 for p in pfs if p >= 1.0),
            "stable": (sum(1 for p in pfs if p >= 1.0) >= 8 and float(np.median(pfs)) >= 1.3)}


def report_variant(trades, label, sym, n_tests=6):
    pnls = [t["pnl_ticks"] for t in trades]
    m = metrics(pnls, label)
    wf = walk_forward_pf(trades)
    print(f"\n--- {label} ({sym}) ---")
    if not trades:
        print("  No trades"); return
    spring = [t["pnl_ticks"] for t in trades if t["direction"] == "BUY"]
    utad = [t["pnl_ticks"] for t in trades if t["direction"] == "SELL"]
    print(f"  N : {m['n']} (SPRING={len(spring)}, UTAD={len(utad)})")
    print(f"  WR={m['wr']*100:.1f}%, PF={m['pf']:.2f}, EV={m['ev']:+.2f}t, "
          f"Sharpe={m['sharpe']:.2f}, PSR={m['psr']:.3f}")
    psr_th = 1 - (1 - (1 - 0.05)**(1/n_tests))
    print(f"  Sidak threshold (n={n_tests}) : {psr_th:.4f} -> {'GO' if m['psr'] >= psr_th else 'NOGO'}")
    print(f"  WF 12f : pf_min={wf['pf_min']:.2f}, pf_med={wf['pf_med']:.2f}, "
          f"pos_folds={wf['n_pos']}/12, stable={wf['stable']}")
    if spring:
        ms = metrics(spring, "SPRING")
        print(f"  SPRING : n={ms['n']}, WR={ms['wr']*100:.0f}%, PF={ms['pf']:.2f}, EV={ms['ev']:+.2f}t")
    if utad:
        mu = metrics(utad, "UTAD")
        print(f"  UTAD   : n={mu['n']}, WR={mu['wr']*100:.0f}%, PF={mu['pf']:.2f}, EV={mu['ev']:+.2f}t")
    exits = pd.Series([t["exit"] for t in trades]).value_counts()
    print(f"  Exits : {dict(exits)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--tp", type=int, default=24)
    parser.add_argument("--sl", type=int, default=12)
    parser.add_argument("--fwd", type=int, default=30)
    parser.add_argument("--cooldown", type=int, default=45)
    args = parser.parse_args()

    sym = args.symbol
    print(f"\n{'='*70}")
    print(f"=== BACKTEST V3 DATABENTO PUR — {sym} ({args.months} mois) ===")
    print(f"=== TP={args.tp}t SL={args.sl}t fwd={args.fwd}b cooldown={args.cooldown}b ===")
    print(f"=== Costs : {COSTS_TICKS[sym]}t round-trip ===")
    print(f"=== AUCUN feature DMP (no MQ_*, GEX_*, blind_*) ===")
    print(f"{'='*70}")

    df = load_v4(sym, args.months)
    if df.empty:
        print("No data"); return
    print(f"  Loaded {len(df)} bars : {df['ts_event'].min()} -> {df['ts_event'].max()}")

    sigs = precompute_signals(df, pressure_window=5)
    sup_active = precompute_level_active(df, "support")
    res_active = precompute_level_active(df, "resistance")
    print(f"  Niveaux DBN actifs : SUPPORT in {sup_active.sum()/len(df)*100:.1f}% bars, "
          f"RESISTANCE in {res_active.sum()/len(df)*100:.1f}% bars")

    # 6 variantes : 3 modes signal x (no_level | with_level)
    variantes = []
    for mode_name, masks in sigs.items():
        # No level
        spring_mask = masks["spring"]
        utad_mask = masks["utad"]
        trades_buy = simulate_trades_vectorise(df, spring_mask, "BUY", sym,
                                                args.tp, args.sl, args.fwd, args.cooldown)
        trades_sell = simulate_trades_vectorise(df, utad_mask, "SELL", sym,
                                                 args.tp, args.sl, args.fwd, args.cooldown)
        all_trades = sorted(trades_buy + trades_sell, key=lambda t: t["entry_idx"])
        # Re-enforce cooldown sur l'union
        filtered = []
        last = -args.cooldown
        for t in all_trades:
            if t["entry_idx"] - last >= args.cooldown:
                filtered.append(t); last = t["entry_idx"]
        report_variant(filtered, f"{mode_name}_NO_LEVEL", sym)
        # With level
        spring_mask_lv = masks["spring"] & sup_active
        utad_mask_lv = masks["utad"] & res_active
        tb2 = simulate_trades_vectorise(df, spring_mask_lv, "BUY", sym,
                                         args.tp, args.sl, args.fwd, args.cooldown)
        ts2 = simulate_trades_vectorise(df, utad_mask_lv, "SELL", sym,
                                         args.tp, args.sl, args.fwd, args.cooldown)
        all_trades_lv = sorted(tb2 + ts2, key=lambda t: t["entry_idx"])
        filtered_lv = []
        last = -args.cooldown
        for t in all_trades_lv:
            if t["entry_idx"] - last >= args.cooldown:
                filtered_lv.append(t); last = t["entry_idx"]
        report_variant(filtered_lv, f"{mode_name}_WITH_LEVEL_DBN", sym)


if __name__ == "__main__":
    main()
