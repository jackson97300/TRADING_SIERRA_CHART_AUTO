"""cluster_phase_starter_v2.py — Analyse exhaustive clusters niveaux au demarrage phases.

V2 (Jackson 09/05) : combiner TOUS les niveaux structurels (PVWAP, PVAL, PVAH, PVPOC,
VWAP_SD+/-1/2, MenthorQ, GEX, HVL, 1D max/min, etc.) pour identifier systematiquement
les "fingerprints" de demarrage de phase.

Hypothese : tout ce qui se passe au demarrage est lie. Plusieurs niveaux convergent,
laissant une signature exploitable.

Methodologie :
  1. Charger v4 enriched 6 mois
  2. Detecter phases UP / DOWN (mouvement >=25t en 3-15 bars)
  3. Au bar de demarrage : capturer TOUS les niveaux actifs (dist < 0.05%) parmi 30+
  4. Pour chaque combinaison de 2-5 niveaux qui se reproduit (>= 5 fois) :
       - frequency
       - forward move avg (15 bars)
       - PF (forward favorable / forward defavorable)
       - % succes (move >= 8t direction phase)
  5. Top combinaisons par PF + freq

Output : 2 tableaux (UP starters + DOWN starters) ranks par PF * sqrt(n)
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

TICK_SIZE = {"NQ": 0.25, "ES": 0.25}

# === Niveaux SUPPORT (pour UP starters) ===
SUPPORT_LEVELS = {
    # Previous Day
    "PVAL": "dist_prev_val_pct", "PDL": "dist_pdl_pct", "PVPOC_below": "dist_prev_vpoc_pct",
    # PVWAP previous
    "PVWAP_SD1D": "dist_pvwap_sd1d_pct", "PVWAP_SD2D": "dist_pvwap_sd2d_pct",
    # VWAP daily
    "VWAP_SD1D": "dist_vwap_d_sd1d_pct", "VWAP_SD2D": "dist_vwap_d_sd2d_pct",
    # Current MP
    "CUR_VAL": "dist_cur_val_pct",
    # IB
    "IB_LOW": "dist_ib_low_pct",
    # Sessions
    "SESS_LOW": "dist_sess_low_pct", "CASH_LOW": "dist_cash_low_pct",
    "OVN_LOW": "dist_ovn_low_pct", "ASIA_LOW": "dist_asia_low_pct", "LONDON_LOW": "dist_london_low_pct",
    # MenthorQ
    "MQ_PUT": "dist_mq_put_pct", "MQ_PUT_0DTE": "dist_mq_put_0dte_pct",
    "MQ_HVL": "dist_mq_hvl_pct",
    "GEX_DN": "dist_gex_nearest_dn_pct",
    "MQ_1D_MIN": "dist_1d_min_ticks_pct",
    # Open
    "OPEN_830": "dist_open_830_pct", "OPEN_930": "dist_open_930_pct",
    # Structure
    "SWING_LOW": "dist_last_swing_low_pct", "NAKED_POC": "dist_naked_poc_nearest_pct",
    "SINGLE_PRINT": "dist_single_print_nearest_pct",
    "EDGE_BUY": "dist_edge_buy_nearest_pct", "COLOR_UP": "dist_color_up_nearest_pct",
    "TRAPPED_SELL": "dist_trapped_sellers_nearest_pct",
    "DELTA_DIV_BUY": "dist_delta_div_buy_nearest_pct",
}

# === Niveaux RESISTANCE (pour DOWN starters) ===
RESISTANCE_LEVELS = {
    # Previous Day
    "PVAH": "dist_prev_vah_pct", "PDH": "dist_pdh_pct", "PVPOC_above": "dist_prev_vpoc_pct",
    # PVWAP previous
    "PVWAP_SD1U": "dist_pvwap_sd1u_pct",
    # VWAP daily
    "VWAP_SD1U": "dist_vwap_d_sd1u_pct", "VWAP_SD2U": "dist_vwap_d_sd2u_pct",
    # Current MP
    "CUR_VAH": "dist_cur_vah_pct",
    # IB
    "IB_HIGH": "dist_ib_high_pct",
    # Sessions
    "SESS_HIGH": "dist_sess_high_pct", "CASH_HIGH": "dist_cash_high_pct",
    "OVN_HIGH": "dist_ovn_high_pct", "ASIA_HIGH": "dist_asia_high_pct", "LONDON_HIGH": "dist_london_high_pct",
    # MenthorQ
    "MQ_CALL": "dist_mq_call_pct", "MQ_CALL_0DTE": "dist_mq_call_0dte_pct",
    "MQ_HVL": "dist_mq_hvl_pct",
    "GEX_UP": "dist_gex_nearest_up_pct",
    "MQ_1D_MAX": "dist_1d_max_ticks_pct",
    # Open
    "OPEN_830": "dist_open_830_pct", "OPEN_930": "dist_open_930_pct",
    # Structure
    "SWING_HIGH": "dist_last_swing_high_pct",
    "EDGE_SELL": "dist_edge_sell_nearest_pct", "COLOR_DN": "dist_color_dn_nearest_pct",
    "TRAPPED_BUY": "dist_trapped_buyers_nearest_pct",
    "DELTA_DIV_SELL": "dist_delta_div_sell_nearest_pct",
}


def load_v4(symbol: str, max_months: int = 6) -> pd.DataFrame:
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_phases_v2(df: pd.DataFrame, sym: str,
                      min_move_ticks: int = 25,
                      min_bars: int = 3, max_bars: int = 15):
    tick = TICK_SIZE[sym]
    phases = []
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    i = 0
    while i < n - max_bars:
        end_max = min(i + max_bars, n - 1)
        local_low = lows[i]
        local_high = highs[i]
        found = False
        for j in range(i + min_bars, end_max + 1):
            move_up = (highs[j] - local_low) / tick
            move_dn = (local_high - lows[j]) / tick
            back = max(0, i - 3)
            if move_up >= min_move_ticks and lows[i] == np.min(lows[back:j + 1]):
                phases.append({"start_idx": i, "end_idx": j, "direction": "UP",
                               "move_ticks": float(round(move_up, 1)),
                               "dur_bars": j - i, "start_price": float(closes[i])})
                i = j
                found = True
                break
            if move_dn >= min_move_ticks and highs[i] == np.max(highs[back:j + 1]):
                phases.append({"start_idx": i, "end_idx": j, "direction": "DOWN",
                               "move_ticks": float(round(move_dn, 1)),
                               "dur_bars": j - i, "start_price": float(closes[i])})
                i = j
                found = True
                break
        if not found:
            i += 1
    return phases


def get_active_levels_at_bar(bar: pd.Series, levels_map: dict, threshold_pct: float = 0.05):
    """Retourne set des niveaux actifs (|dist_pct| <= threshold)."""
    actives = set()
    for name, col in levels_map.items():
        v = bar.get(col)
        if v is None or pd.isna(v):
            continue
        try:
            if abs(float(v)) <= threshold_pct:
                actives.add(name)
        except (ValueError, TypeError):
            continue
    return actives


def measure_forward(df: pd.DataFrame, idx: int, direction: str, sym: str,
                    fwd_bars: int = 15, threshold_t: int = 8) -> dict:
    """Mesure performance forward apres bar idx.

    Returns: {move_max_t, move_min_t, success (=move_favorable >= threshold_t)}
    """
    n = len(df)
    end = min(idx + fwd_bars, n - 1)
    if end <= idx:
        return {"move_max_t": 0, "move_min_t": 0, "success": False}
    tick = TICK_SIZE[sym]
    close_t = df.iloc[idx]["close"]
    fwd_high = df["high"].iloc[idx + 1:end + 1].max()
    fwd_low = df["low"].iloc[idx + 1:end + 1].min()
    move_up_t = (fwd_high - close_t) / tick
    move_dn_t = (close_t - fwd_low) / tick
    if direction == "UP":
        success = move_up_t >= threshold_t
        return {"move_favorable_t": float(move_up_t), "move_adverse_t": float(move_dn_t),
                "success": success}
    else:
        success = move_dn_t >= threshold_t
        return {"move_favorable_t": float(move_dn_t), "move_adverse_t": float(move_up_t),
                "success": success}


def analyze(symbol: str, months: int = 6):
    print(f"=== Cluster Phase Starter V2 — {symbol} ({months} mois) ===")
    df = load_v4(symbol, max_months=months)
    if df.empty:
        print("  Aucune data")
        return

    print(f"  Loaded {len(df)} bars, {df['ts_event'].min()} -> {df['ts_event'].max()}")

    phases = detect_phases_v2(df, symbol)
    n_up = sum(1 for p in phases if p["direction"] == "UP")
    n_dn = sum(1 for p in phases if p["direction"] == "DOWN")
    print(f"  Phases : {len(phases)} (UP={n_up} / DOWN={n_dn})")

    if not phases:
        return

    # Pour chaque phase : capture niveaux actifs au demarrage + measure forward
    up_starters = []   # list of {levels_set, fwd_metrics}
    down_starters = []

    for p in phases:
        bar = df.iloc[p["start_idx"]]
        if p["direction"] == "UP":
            actives = get_active_levels_at_bar(bar, SUPPORT_LEVELS, 0.05)
            fwd = measure_forward(df, p["start_idx"], "UP", symbol, fwd_bars=15, threshold_t=8)
            up_starters.append({"levels": actives, "fwd": fwd, "phase": p})
        else:
            actives = get_active_levels_at_bar(bar, RESISTANCE_LEVELS, 0.05)
            fwd = measure_forward(df, p["start_idx"], "DOWN", symbol, fwd_bars=15, threshold_t=8)
            down_starters.append({"levels": actives, "fwd": fwd, "phase": p})

    # === Analyse combinaisons 2-3 niveaux qui se reproduisent ===
    def analyze_combos(starters, direction_label, levels_universe):
        """Pour chaque paire/triplet de niveaux, calc freq + forward stats."""
        combo_stats = defaultdict(lambda: {"n": 0, "n_success": 0,
                                            "sum_fav": 0.0, "sum_adv": 0.0})
        for s in starters:
            lvls = s["levels"]
            if len(lvls) < 2:
                continue
            # Toutes paires + triplets
            for size in (2, 3):
                if len(lvls) >= size:
                    for combo in combinations(sorted(lvls), size):
                        combo_stats[combo]["n"] += 1
                        if s["fwd"].get("success"):
                            combo_stats[combo]["n_success"] += 1
                        combo_stats[combo]["sum_fav"] += s["fwd"].get("move_favorable_t", 0)
                        combo_stats[combo]["sum_adv"] += s["fwd"].get("move_adverse_t", 0)

        # Filter combos avec freq >= 5
        rows = []
        for combo, stats in combo_stats.items():
            if stats["n"] < 5:
                continue
            success_rate = stats["n_success"] / stats["n"]
            avg_fav = stats["sum_fav"] / stats["n"]
            avg_adv = stats["sum_adv"] / stats["n"]
            pf = avg_fav / avg_adv if avg_adv > 0 else float("inf")
            score = pf * np.sqrt(stats["n"])  # combinaison freq + PF
            rows.append({
                "combo": combo, "n": stats["n"],
                "success_rate": success_rate,
                "avg_fav_t": avg_fav, "avg_adv_t": avg_adv,
                "pf": pf, "score": score,
            })
        rows.sort(key=lambda r: r["score"], reverse=True)

        print(f"\n--- TOP 15 combinaisons {direction_label} (>= 5 occurrences) ---")
        print(f"{'Combo':<55} {'N':>5} {'Succ%':>6} {'AvgFav':>7} {'AvgAdv':>7} {'PF':>5}")
        print("-" * 95)
        for r in rows[:15]:
            combo_str = " + ".join(r["combo"])[:53]
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
            print(f"  {combo_str:<53} {r['n']:>5} {r['success_rate']*100:>5.0f}% "
                  f"{r['avg_fav_t']:>6.1f}t {r['avg_adv_t']:>6.1f}t {pf_str:>5}")

    analyze_combos(up_starters, "UP starters (SUPPORT cluster)", SUPPORT_LEVELS)
    analyze_combos(down_starters, "DOWN starters (RESISTANCE cluster)", RESISTANCE_LEVELS)

    # === Frequence individuelle des niveaux au demarrage ===
    def analyze_individual(starters, direction_label):
        level_counter = Counter()
        level_success = defaultdict(lambda: {"n": 0, "succ": 0, "sum_fav": 0.0, "sum_adv": 0.0})
        for s in starters:
            for lvl in s["levels"]:
                level_counter[lvl] += 1
                level_success[lvl]["n"] += 1
                if s["fwd"].get("success"):
                    level_success[lvl]["succ"] += 1
                level_success[lvl]["sum_fav"] += s["fwd"].get("move_favorable_t", 0)
                level_success[lvl]["sum_adv"] += s["fwd"].get("move_adverse_t", 0)

        n_phases = len(starters)
        rows = []
        for lvl, n in level_counter.most_common():
            if n < 10:
                continue
            d = level_success[lvl]
            succ_rate = d["succ"] / d["n"]
            avg_fav = d["sum_fav"] / d["n"]
            avg_adv = d["sum_adv"] / d["n"]
            pf = avg_fav / avg_adv if avg_adv > 0 else float("inf")
            rows.append({"lvl": lvl, "n": n, "freq_pct": n / n_phases * 100,
                         "succ_rate": succ_rate, "pf": pf, "avg_fav": avg_fav})

        print(f"\n--- TOP NIVEAUX INDIVIDUELS au demarrage {direction_label} ---")
        print(f"{'Niveau':<22} {'N':>5} {'Freq%':>6} {'Succ%':>6} {'PF':>6} {'AvgFav':>7}")
        print("-" * 65)
        for r in rows[:20]:
            pf_str = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "INF"
            print(f"  {r['lvl']:<20} {r['n']:>5} {r['freq_pct']:>5.0f}% "
                  f"{r['succ_rate']*100:>5.0f}% {pf_str:>6} {r['avg_fav']:>6.1f}t")

    analyze_individual(up_starters, "UP")
    analyze_individual(down_starters, "DOWN")

    # === Distribution n_levels par phase ===
    n_lvls_up = Counter(len(s["levels"]) for s in up_starters)
    n_lvls_dn = Counter(len(s["levels"]) for s in down_starters)
    print(f"\n--- Distribution n_levels au demarrage ---")
    print(f"  UP   : {dict(sorted(n_lvls_up.items()))}")
    print(f"  DOWN : {dict(sorted(n_lvls_dn.items()))}")

    # === Phases avec cluster (>=3) success rate ===
    up_cluster = [s for s in up_starters if len(s["levels"]) >= 3]
    up_no_cluster = [s for s in up_starters if len(s["levels"]) < 3]
    dn_cluster = [s for s in down_starters if len(s["levels"]) >= 3]
    dn_no_cluster = [s for s in down_starters if len(s["levels"]) < 3]

    def succ(lst): return sum(1 for s in lst if s["fwd"].get("success")) / len(lst) * 100 if lst else 0

    print(f"\n--- COMPARAISON CLUSTER (>=3 niveaux) vs SOLO (<3) ---")
    print(f"  UP cluster   : {len(up_cluster)} phases, succ {succ(up_cluster):.0f}%")
    print(f"  UP solo      : {len(up_no_cluster)} phases, succ {succ(up_no_cluster):.0f}%")
    print(f"  DOWN cluster : {len(dn_cluster)} phases, succ {succ(dn_cluster):.0f}%")
    print(f"  DOWN solo    : {len(dn_no_cluster)} phases, succ {succ(dn_no_cluster):.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    analyze(args.symbol, args.months)


if __name__ == "__main__":
    main()
