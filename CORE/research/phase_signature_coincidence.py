"""phase_signature_coincidence.py — Audit COINCIDENCE BN <-> phases (numpy vectorise).

Objectif : verifier si signature RETOUCHE BN coincide avec demarrages phases.
  - RECALL    = % phases qui ont signal correspondant dans [start-5, start]
  - PRECISION = % signaux suivis par phase de la bonne direction dans 10b
  - LIFT      = P(phase | signal) / P(phase | random_bar)

6 modes testes :
  pure / full / strong / cluster2 / cluster_bn / cluster_strong
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}

N_LONG_UP_CLUSTER = "n_long_up_cluster_within_0_2pct"
N_LONG_DN_CLUSTER = "n_long_dn_cluster_within_0_2pct"
N_COLOR_UP_CLUSTER = "n_color_up_cluster_within_0_2pct"
N_COLOR_DN_CLUSTER = "n_color_dn_cluster_within_0_2pct"
LONG_UP_BAR = "long_up_bar"
LONG_DN_BAR = "long_dn_bar"


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_phases_strict(df, sym, min_bars=8, max_bars=30, pivot_lookback=5):
    min_move_ticks = 60 if sym == "ES" else 120
    tick = TICK_SIZE[sym]
    phases = []
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    i = 0
    while i < n - max_bars:
        end_max = min(i + max_bars, n - 1)
        local_low = lows[i]
        local_high = highs[i]
        found = False
        back = max(0, i - pivot_lookback)
        if back >= i:
            i += 1
            continue
        is_low = lows[i] < np.min(lows[back:i])
        is_high = highs[i] > np.max(highs[back:i])
        if not (is_low or is_high):
            i += 1
            continue
        for j in range(i + min_bars, end_max + 1):
            move_up = (highs[j] - local_low) / tick
            move_dn = (local_high - lows[j]) / tick
            if move_up >= min_move_ticks and is_low:
                phases.append({"start_idx": i, "direction": "UP"})
                i = j
                found = True
                break
            if move_dn >= min_move_ticks and is_high:
                phases.append({"start_idx": i, "direction": "DOWN"})
                i = j
                found = True
                break
        if not found:
            i += 1
    return phases


def precompute_signals(df, pressure_window=5):
    """Vectorise : compute boolean arrays pour les 6 modes."""
    n = len(df)
    # Cluster features (par-bar values)
    n_long_up = df.get(N_LONG_UP_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_long_dn = df.get(N_LONG_DN_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_color_up = df.get(N_COLOR_UP_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    n_color_dn = df.get(N_COLOR_DN_CLUSTER, pd.Series(np.zeros(n))).fillna(0).to_numpy()
    long_up_bar = (df.get(LONG_UP_BAR, pd.Series(np.zeros(n))).fillna(0).to_numpy() > 0).astype(int)
    long_dn_bar = (df.get(LONG_DN_BAR, pd.Series(np.zeros(n))).fillna(0).to_numpy() > 0).astype(int)
    bin_color_up = (n_color_up > 0).astype(int)
    bin_color_dn = (n_color_dn > 0).astype(int)

    # Rolling sum pressure 5 bars (excluding current i, so [i-5, i-1])
    # = roll forward by 1, then rolling sum of 5
    def rolling_sum_lag(arr, w):
        """sum(arr[i-w : i]) for each i (excluding i)."""
        s = pd.Series(arr).rolling(window=w, min_periods=1).sum().shift(1).fillna(0).to_numpy()
        return s
    p_dn_recent = rolling_sum_lag(long_dn_bar + bin_color_dn, pressure_window)
    p_up_recent = rolling_sum_lag(long_up_bar + bin_color_up, pressure_window)

    is_in_long_up = n_long_up >= 1
    is_in_long_dn = n_long_dn >= 1
    cluster_up_total = n_long_up + n_color_up
    cluster_dn_total = n_long_dn + n_color_dn

    modes = {
        "pure": {
            "spring": is_in_long_up,
            "utad": is_in_long_dn,
        },
        "full": {
            "spring": is_in_long_up & (p_dn_recent >= 1),
            "utad": is_in_long_dn & (p_up_recent >= 1),
        },
        "strong": {
            "spring": is_in_long_up & (p_dn_recent >= 2),
            "utad": is_in_long_dn & (p_up_recent >= 2),
        },
        "cluster2": {
            "spring": n_long_up >= 2,
            "utad": n_long_dn >= 2,
        },
        "cluster_bn": {
            "spring": cluster_up_total >= 2,
            "utad": cluster_dn_total >= 2,
        },
        "cluster_strong": {
            "spring": cluster_up_total >= 3,
            "utad": cluster_dn_total >= 3,
        },
    }
    return modes


def measure_recall(modes, phases, signal_window=5):
    """Pour chaque phase, % qui ont signal dans [start-5, start]."""
    out = {}
    starts_up = [p["start_idx"] for p in phases if p["direction"] == "UP"]
    starts_dn = [p["start_idx"] for p in phases if p["direction"] == "DOWN"]
    for mode_name, sigs in modes.items():
        spring_arr = sigs["spring"]
        utad_arr = sigs["utad"]
        n = len(spring_arr)
        matched_up = 0
        for s in starts_up:
            lo = max(0, s - signal_window)
            hi = min(n, s + 1)
            if spring_arr[lo:hi].any():
                matched_up += 1
        matched_dn = 0
        for s in starts_dn:
            lo = max(0, s - signal_window)
            hi = min(n, s + 1)
            if utad_arr[lo:hi].any():
                matched_dn += 1
        out[mode_name] = {
            "n_up": len(starts_up), "matched_up": matched_up,
            "recall_up": matched_up / len(starts_up) if starts_up else 0,
            "n_dn": len(starts_dn), "matched_dn": matched_dn,
            "recall_dn": matched_dn / len(starts_dn) if starts_dn else 0,
        }
    return out


def measure_precision(modes, phases, fwd_window=10):
    """Pour chaque signal, % suivi par une phase dans [i, i+fwd]."""
    starts_up_set = set(p["start_idx"] for p in phases if p["direction"] == "UP")
    starts_dn_set = set(p["start_idx"] for p in phases if p["direction"] == "DOWN")
    # Boolean arrays pour les starts
    out = {}
    for mode_name, sigs in modes.items():
        spring_arr = sigs["spring"]
        utad_arr = sigs["utad"]
        n = len(spring_arr)
        n_signals_spring = int(spring_arr.sum())
        n_signals_utad = int(utad_arr.sum())
        spring_idxs = np.where(spring_arr)[0]
        utad_idxs = np.where(utad_arr)[0]
        # Filter idx avec fwd window valide
        spring_idxs = spring_idxs[spring_idxs < n - fwd_window]
        utad_idxs = utad_idxs[utad_idxs < n - fwd_window]
        matched_spring = sum(1 for i in spring_idxs
                              if any(k in starts_up_set for k in range(i, i + fwd_window + 1)))
        matched_utad = sum(1 for i in utad_idxs
                            if any(k in starts_dn_set for k in range(i, i + fwd_window + 1)))
        out[mode_name] = {
            "n_signals_spring": int(len(spring_idxs)),
            "matched_spring": matched_spring,
            "precision_spring": matched_spring / len(spring_idxs) if len(spring_idxs) else 0,
            "n_signals_utad": int(len(utad_idxs)),
            "matched_utad": matched_utad,
            "precision_utad": matched_utad / len(utad_idxs) if len(utad_idxs) else 0,
        }
    return out


def measure_baseline(phases, n_bars, fwd_window=10, n_random=5000):
    starts_up_set = set(p["start_idx"] for p in phases if p["direction"] == "UP")
    starts_dn_set = set(p["start_idx"] for p in phases if p["direction"] == "DOWN")
    rng = np.random.default_rng(42)
    if n_bars <= 30:
        return {"baseline_p_up": 0, "baseline_p_dn": 0}
    sample = rng.choice(np.arange(20, n_bars - fwd_window - 5),
                         size=min(n_random, max(1, n_bars - 25)), replace=False)
    n_match_up = sum(1 for i in sample if any(k in starts_up_set for k in range(i, i + fwd_window + 1)))
    n_match_dn = sum(1 for i in sample if any(k in starts_dn_set for k in range(i, i + fwd_window + 1)))
    return {
        "baseline_p_up": n_match_up / len(sample),
        "baseline_p_dn": n_match_dn / len(sample),
    }


def report_all(sym, recall_data, precision_data, baseline):
    bp_up = baseline["baseline_p_up"]
    bp_dn = baseline["baseline_p_dn"]
    print(f"\n=== AUDIT COINCIDENCE BN <-> Phases {sym} ===")
    print(f"Baseline random : P(UP demarre dans 10b)={bp_up*100:.1f}%, P(DOWN)={bp_dn*100:.1f}%")
    print(f"\n{'Mode':<18s} | {'Rec UP':>7s} | {'Rec DN':>7s} | {'Prec SP':>8s} | "
          f"{'Prec UT':>8s} | {'Lift SP':>8s} | {'Lift UT':>8s} | {'n SP':>6s} | {'n UT':>6s}")
    print("-" * 100)
    for mode in ["pure", "full", "strong", "cluster2", "cluster_bn", "cluster_strong"]:
        r = recall_data[mode]
        p = precision_data[mode]
        lift_sp = (p["precision_spring"] / bp_up) if bp_up > 0 else 0
        lift_ut = (p["precision_utad"] / bp_dn) if bp_dn > 0 else 0
        print(f"{mode:<18s} | {r['recall_up']*100:>6.1f}% | {r['recall_dn']*100:>6.1f}% | "
              f"{p['precision_spring']*100:>7.1f}% | {p['precision_utad']*100:>7.1f}% | "
              f"{lift_sp:>7.2f}x | {lift_ut:>7.2f}x | "
              f"{p['n_signals_spring']:>6d} | {p['n_signals_utad']:>6d}")
    print()
    print("Verdict per mode (Lift >= 2.0 et Precision >= 30% et Recall >= 30%) :")
    for mode in ["pure", "full", "strong", "cluster2", "cluster_bn", "cluster_strong"]:
        r = recall_data[mode]
        p = precision_data[mode]
        lift_sp = (p["precision_spring"] / bp_up) if bp_up > 0 else 0
        lift_ut = (p["precision_utad"] / bp_dn) if bp_dn > 0 else 0
        verdict_sp = "GO" if (lift_sp >= 2.0 and p["precision_spring"] >= 0.30 and r["recall_up"] >= 0.30) else "NOGO"
        verdict_ut = "GO" if (lift_ut >= 2.0 and p["precision_utad"] >= 0.30 and r["recall_dn"] >= 0.30) else "NOGO"
        print(f"  {mode:<18s} : SPRING={verdict_sp}  UTAD={verdict_ut}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()

    sym = args.symbol
    df = load_v4(sym, args.months)
    print(f"[{sym}] Loaded {len(df)} bars")

    phases = detect_phases_strict(df, sym)
    n_up = sum(1 for p in phases if p["direction"] == "UP")
    n_dn = sum(1 for p in phases if p["direction"] == "DOWN")
    print(f"[{sym}] Phases : {len(phases)} (UP={n_up} / DOWN={n_dn})")

    print(f"[{sym}] Precomputing signals (vectorise)...")
    modes = precompute_signals(df, pressure_window=5)
    print(f"[{sym}] Computing recall...")
    recall_data = measure_recall(modes, phases, signal_window=5)
    print(f"[{sym}] Computing precision...")
    precision_data = measure_precision(modes, phases, fwd_window=10)
    print(f"[{sym}] Computing baseline...")
    baseline = measure_baseline(phases, len(df), fwd_window=10)

    report_all(sym, recall_data, precision_data, baseline)


if __name__ == "__main__":
    main()
