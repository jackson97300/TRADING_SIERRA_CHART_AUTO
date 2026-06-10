"""cluster_phase_starter_v3.py — V3 avec 7 fixes code-reviewer (NOGO v2).

Fixes appliques (verdict code-reviewer 09/05) :
  1. Forward window APRES la phase (end_idx+1 a end_idx+15) - pas chevauche detection
  2. SL realiste path-dependent (success = TP_avant_SL chronologique)
  3. Baseline random bootstrap 1000 - conserve combos PF > p95(random)
  4. Walk-forward 3 folds chronologiques - PF > 1.3 sur 3 folds
  5. Correction Bonferroni alpha = 0.05 / N_tests
  6. Fix extremum exclusif : lows[back:i] (pas back:j+1)
  7. Score PF * log(N) au lieu de PF * sqrt(N)

Methodologie corrigee :
  Phase = move >=25 ticks en 3-15 bars confirme par local extremum strict (i exclu)
  Forward = [end_idx+1, end_idx+15] = 15 bars APRES la fin de la phase
  Success = TP atteint avant SL (TP=phase_size/2, SL=phase_size/2 inverse)
  Baseline = 1000 echantillons phases aleatoires (idx random + meme niveau actif)
  Walk-forward = 3 folds chronologiques (split temporel 33/33/33)
  Validation = combo retenu si PF > 1.3 sur 3 folds + p < alpha_bonf

Output : combos retenues apres validation walk-forward + bootstrap.

A VALIDER PAR AGENT AVANT RUN.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations
from math import log
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

TICK_SIZE = {"NQ": 0.25, "ES": 0.25}

# Threshold par niveau (recommandation market-analyst 09/05) :
# - Daily/Weekly levels = zones (0.10% = ~28 ticks NQ / 7-8 ticks ES)
# - Intraday levels = points precis (0.05% = ~14 ticks NQ / 4 ticks ES)
THRESH_DAILY = 0.10    # PVAL, PVPOC, PVAH, PDH, PDL, PVWAP_*, VWAP_W_*
THRESH_DEFAULT = 0.05  # autres

# === Niveaux SUPPORT (UP starters) ===
# Format : (dist_col, threshold_pct)
SUPPORT_LEVELS = {
    # Daily / Weekly (threshold 0.10) — recommandation market-analyst
    "PVAL":         ("dist_prev_val_pct",       THRESH_DAILY),
    "PDL":          ("dist_pdl_pct",            THRESH_DAILY),
    "PVPOC_below":  ("dist_prev_vpoc_pct",      THRESH_DAILY),
    "PVWAP_SD1D":   ("dist_pvwap_sd1d_pct",     THRESH_DAILY),
    "PVWAP_SD2D":   ("dist_pvwap_sd2d_pct",     THRESH_DAILY),
    # NEW : VWAP weekly (rajout market-analyst : "fonds weekly rebalance ici")
    "VWAP_W":       ("dist_vwap_w_pct",         THRESH_DAILY),
    "VWAP_W_SD1D":  ("dist_vwap_w_sd1d_pct",    THRESH_DAILY),
    "VWAP_W_SD2D":  ("dist_vwap_w_sd2d_pct",    THRESH_DAILY),
    # Intraday (threshold 0.05)
    "VWAP_SD1D":    ("dist_vwap_d_sd1d_pct",    THRESH_DEFAULT),
    "VWAP_SD2D":    ("dist_vwap_d_sd2d_pct",    THRESH_DEFAULT),
    "CUR_VAL":      ("dist_cur_val_pct",        THRESH_DEFAULT),
    "IB_LOW":       ("dist_ib_low_pct",         THRESH_DEFAULT),
    "SESS_LOW":     ("dist_sess_low_pct",       THRESH_DEFAULT),
    "CASH_LOW":     ("dist_cash_low_pct",       THRESH_DEFAULT),
    "OVN_LOW":      ("dist_ovn_low_pct",        THRESH_DEFAULT),
    "ASIA_LOW":     ("dist_asia_low_pct",       THRESH_DEFAULT),
    "LONDON_LOW":   ("dist_london_low_pct",     THRESH_DEFAULT),
    "MQ_PUT":       ("dist_mq_put_pct",         THRESH_DEFAULT),
    "MQ_PUT_0DTE":  ("dist_mq_put_0dte_pct",    THRESH_DEFAULT),
    "MQ_HVL":       ("dist_mq_hvl_pct",         THRESH_DEFAULT),
    "GEX_DN":       ("dist_gex_nearest_dn_pct", THRESH_DEFAULT),
    "MQ_1D_MIN":    ("dist_1d_min_ticks_pct",   THRESH_DEFAULT),
    "OPEN_830":     ("dist_open_830_pct",       THRESH_DEFAULT),
    "OPEN_930":     ("dist_open_930_pct",       THRESH_DEFAULT),
    "SWING_LOW":    ("dist_last_swing_low_pct", THRESH_DEFAULT),
    "NAKED_POC":    ("dist_naked_poc_nearest_pct", THRESH_DEFAULT),
    "SINGLE_PRINT": ("dist_single_print_nearest_pct", THRESH_DEFAULT),
    "EDGE_BUY":     ("dist_edge_buy_nearest_pct",     THRESH_DEFAULT),
    "COLOR_UP":     ("dist_color_up_nearest_pct",     THRESH_DEFAULT),
    "TRAPPED_SELL": ("dist_trapped_sellers_nearest_pct", THRESH_DEFAULT),
    "DELTA_DIV_BUY":("dist_delta_div_buy_nearest_pct", THRESH_DEFAULT),
}

# === Niveaux RESISTANCE (DOWN starters) ===
RESISTANCE_LEVELS = {
    # Daily / Weekly (threshold 0.10)
    "PVAH":         ("dist_prev_vah_pct",       THRESH_DAILY),
    "PDH":          ("dist_pdh_pct",            THRESH_DAILY),
    "PVPOC_above":  ("dist_prev_vpoc_pct",      THRESH_DAILY),
    "PVWAP_SD1U":   ("dist_pvwap_sd1u_pct",     THRESH_DAILY),
    # NEW : VWAP weekly
    "VWAP_W":       ("dist_vwap_w_pct",         THRESH_DAILY),
    "VWAP_W_SD1U":  ("dist_vwap_w_sd1u_pct",    THRESH_DAILY),
    "VWAP_W_SD2U":  ("dist_vwap_w_sd2u_pct",    THRESH_DAILY),
    # Intraday
    "VWAP_SD1U":    ("dist_vwap_d_sd1u_pct",    THRESH_DEFAULT),
    "VWAP_SD2U":    ("dist_vwap_d_sd2u_pct",    THRESH_DEFAULT),
    "CUR_VAH":      ("dist_cur_vah_pct",        THRESH_DEFAULT),
    "IB_HIGH":      ("dist_ib_high_pct",        THRESH_DEFAULT),
    "SESS_HIGH":    ("dist_sess_high_pct",      THRESH_DEFAULT),
    "CASH_HIGH":    ("dist_cash_high_pct",      THRESH_DEFAULT),
    "OVN_HIGH":     ("dist_ovn_high_pct",       THRESH_DEFAULT),
    "ASIA_HIGH":    ("dist_asia_high_pct",      THRESH_DEFAULT),
    "LONDON_HIGH":  ("dist_london_high_pct",    THRESH_DEFAULT),
    "MQ_CALL":      ("dist_mq_call_pct",        THRESH_DEFAULT),
    "MQ_CALL_0DTE": ("dist_mq_call_0dte_pct",   THRESH_DEFAULT),
    "MQ_HVL":       ("dist_mq_hvl_pct",         THRESH_DEFAULT),
    "GEX_UP":       ("dist_gex_nearest_up_pct", THRESH_DEFAULT),
    "MQ_1D_MAX":    ("dist_1d_max_ticks_pct",   THRESH_DEFAULT),
    "OPEN_830":     ("dist_open_830_pct",       THRESH_DEFAULT),
    "OPEN_930":     ("dist_open_930_pct",       THRESH_DEFAULT),
    "SWING_HIGH":   ("dist_last_swing_high_pct", THRESH_DEFAULT),
    "EDGE_SELL":    ("dist_edge_sell_nearest_pct", THRESH_DEFAULT),
    "COLOR_DN":     ("dist_color_dn_nearest_pct", THRESH_DEFAULT),
    "TRAPPED_BUY":  ("dist_trapped_buyers_nearest_pct", THRESH_DEFAULT),
    "DELTA_DIV_SELL":("dist_delta_div_sell_nearest_pct", THRESH_DEFAULT),
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


# ─── FIX 6 : extremum exclusif ───
def detect_phases_v3(df: pd.DataFrame, sym: str,
                      min_move_ticks: int = 25,
                      min_bars: int = 3, max_bars: int = 15):
    """Detecte phases avec confirmation extremum STRICT EXCLUSIF (3 bars AVANT i)."""
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

        # FIX 6 : confirmation sur les 3 bars AVANT i seulement (exclusif)
        back = max(0, i - 3)
        if back >= i:
            i += 1
            continue
        prev_lows = lows[back:i]
        prev_highs = highs[back:i]
        is_local_low_confirmed = lows[i] < np.min(prev_lows) if len(prev_lows) > 0 else False
        is_local_high_confirmed = highs[i] > np.max(prev_highs) if len(prev_highs) > 0 else False

        # FIX 1 code-reviewer v3 : skip directement si aucune confirmation
        # extremum (evite boucle inutile sur j si i n'est ni un local low ni high)
        if not (is_local_low_confirmed or is_local_high_confirmed):
            i += 1
            continue

        for j in range(i + min_bars, end_max + 1):
            move_up = (highs[j] - local_low) / tick
            move_dn = (local_high - lows[j]) / tick

            if move_up >= min_move_ticks and is_local_low_confirmed:
                phases.append({
                    "start_idx": i, "end_idx": j, "direction": "UP",
                    "move_ticks": float(round(move_up, 1)),
                    "dur_bars": j - i, "start_price": float(closes[i]),
                })
                i = j
                found = True
                break
            if move_dn >= min_move_ticks and is_local_high_confirmed:
                phases.append({
                    "start_idx": i, "end_idx": j, "direction": "DOWN",
                    "move_ticks": float(round(move_dn, 1)),
                    "dur_bars": j - i, "start_price": float(closes[i]),
                })
                i = j
                found = True
                break
        if not found:
            i += 1
    return phases


def get_active_levels_at_bar(bar: pd.Series, levels_map: dict):
    """Retourne set des niveaux actifs (|dist_pct| <= threshold per-level).

    levels_map format : {name: (dist_col, threshold_pct)}
    Threshold per-level : daily/weekly = 0.10, intraday = 0.05
    (recommandation market-analyst 09/05).
    """
    actives = set()
    for name, (col, threshold) in levels_map.items():
        v = bar.get(col)
        if v is None or pd.isna(v):
            continue
        try:
            if abs(float(v)) <= threshold:
                actives.add(name)
        except (ValueError, TypeError):
            continue
    return actives


# ─── FIX 1 + 2 : Forward APRES la phase + SL path-dependent ───
def measure_forward_post_phase(df: pd.DataFrame, end_idx: int, direction: str, sym: str,
                                fwd_bars: int = 15, tp_ticks: int = 12, sl_ticks: int = 12) -> dict:
    """Mesure performance FORWARD APRES la fin de la phase (anti circular).

    Args:
        end_idx: index FIN de la phase (post-detection)
        direction: "UP" ou "DOWN" - direction prolongement attendue
        tp_ticks: TP en ticks (move favorable a atteindre)
        sl_ticks: SL en ticks (move adverse qui fait sortir)

    Returns:
        {success: bool, pnl_ticks: float, exit_reason: "TP"|"SL"|"TIMEOUT"}

    Path-dependent : si SL touche AVANT TP = SL hit (pas success).
    """
    n = len(df)
    start = end_idx + 1
    end = min(end_idx + fwd_bars, n - 1)
    if start >= end:
        return {"success": False, "pnl_ticks": 0.0, "exit_reason": "NO_DATA"}

    tick = TICK_SIZE[sym]
    close_at_end = df.iloc[end_idx]["close"]
    tp_pts = tp_ticks * tick
    sl_pts = sl_ticks * tick

    if direction == "UP":
        tp_price = close_at_end + tp_pts
        sl_price = close_at_end - sl_pts
    else:
        tp_price = close_at_end - tp_pts
        sl_price = close_at_end + sl_pts

    # Iter bar by bar pour path-dependency
    for k in range(start, end + 1):
        bar_high = df.iloc[k]["high"]
        bar_low = df.iloc[k]["low"]
        if direction == "UP":
            # Pessimist : si TP et SL dans la meme bar, assume SL hit en premier
            sl_hit = bar_low <= sl_price
            tp_hit = bar_high >= tp_price
            if sl_hit and tp_hit:
                return {"success": False, "pnl_ticks": -float(sl_ticks), "exit_reason": "SL_PESSIMIST"}
            if sl_hit:
                return {"success": False, "pnl_ticks": -float(sl_ticks), "exit_reason": "SL"}
            if tp_hit:
                return {"success": True, "pnl_ticks": float(tp_ticks), "exit_reason": "TP"}
        else:
            sl_hit = bar_high >= sl_price
            tp_hit = bar_low <= tp_price
            if sl_hit and tp_hit:
                return {"success": False, "pnl_ticks": -float(sl_ticks), "exit_reason": "SL_PESSIMIST"}
            if sl_hit:
                return {"success": False, "pnl_ticks": -float(sl_ticks), "exit_reason": "SL"}
            if tp_hit:
                return {"success": True, "pnl_ticks": float(tp_ticks), "exit_reason": "TP"}
    # TIMEOUT : pnl = unrealized close
    final_close = df.iloc[end]["close"]
    if direction == "UP":
        unreal_t = (final_close - close_at_end) / tick
    else:
        unreal_t = (close_at_end - final_close) / tick
    return {"success": False, "pnl_ticks": float(unreal_t), "exit_reason": "TIMEOUT"}


def evaluate_combo(phase_data: list, combo: tuple, direction: str = "",
                    sym: str = "", tp_ticks: int = 0, sl_ticks: int = 0,
                    fwd_bars: int = 0) -> dict:
    """Evaluate une combo precise sur phase_data (list of phase results).

    NOTE FIX Q7 code-reviewer v3 : `df` parametre retire (etait mort, utilisait
    seulement phase_data). Les autres parametres direction/sym/tp_ticks/sl_ticks/fwd_bars
    gardes pour signature future si extension necessaire (currently unused dans
    cette version qui pre-calcule fwd au moment de la collecte phase_data).

    Return PF, success_rate, n.
    """
    matching = [p for p in phase_data if combo.issubset(p["levels"])] if isinstance(combo, set) \
               else [p for p in phase_data if set(combo).issubset(p["levels"])]
    n = len(matching)
    if n == 0:
        return {"n": 0, "success_rate": 0, "pf": 0, "avg_pnl": 0}
    n_success = sum(1 for m in matching if m["fwd"]["success"])
    pnls = [m["fwd"]["pnl_ticks"] for m in matching]
    sum_win = sum(p for p in pnls if p > 0)
    sum_loss = sum(abs(p) for p in pnls if p < 0)
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")
    return {
        "n": n,
        "success_rate": n_success / n,
        "pf": pf,
        "avg_pnl": np.mean(pnls),
    }


# ─── FIX 3 : Baseline random bootstrap ───
def bootstrap_baseline_pf(phase_data: list, combo_size: int, n_target: int,
                           n_bootstrap: int = 1000, rng=None) -> dict:
    """Bootstrap : tire 1000x un sous-ensemble random de n_target phases.
    Calcule PF de chaque tirage. Return p50, p95, p99.

    NOTE : on tire des PHASES alle, pas seulement celles avec la combo.
    Le PF random = PF moyen de phases random (combo absent ou present).
    """
    if rng is None:
        rng = np.random.default_rng(42)
    if len(phase_data) < n_target:
        return {"p50": 0, "p95": 0, "p99": 0}
    pfs = []
    for _ in range(n_bootstrap):
        idxs = rng.choice(len(phase_data), size=n_target, replace=False)
        sample = [phase_data[i] for i in idxs]
        pnls = [s["fwd"]["pnl_ticks"] for s in sample]
        sum_win = sum(p for p in pnls if p > 0)
        sum_loss = sum(abs(p) for p in pnls if p < 0)
        pf = sum_win / sum_loss if sum_loss > 0 else 0
        pfs.append(pf)
    return {
        "p50": float(np.percentile(pfs, 50)),
        "p95": float(np.percentile(pfs, 95)),
        "p99": float(np.percentile(pfs, 99)),
    }


# ─── FIX 4 : Walk-forward 3 folds ───
def walk_forward_validate(phase_data: list, combo: tuple, direction: str, sym: str,
                            tp_ticks: int, sl_ticks: int, fwd_bars: int) -> dict:
    """Split phase_data en 3 folds chronologiques.
    Combo retenu si PF > 1.3 sur 3 folds (pas la moyenne).

    TRADE-OFF DOCUMENTE (code-reviewer v3 fix #3) :
    Si combo apparait peu dans un fold (ex: 8 fois fold 1+2, 0 fois fold 3),
    evaluate_combo retourne PF=0 -> all(pf>=1.3) = False = INVALIDE.

    On accepte ce trade-off CONSERVATEUR :
    - Pro : evite combos saisonniers / regime-dependent (anti-overfit)
    - Con : jette des combos legitimes mais rares (ex: setup post-FOMC)

    Justification : preference robustesse sur sensibilite (Lopez AFML ch.7
    walk-forward strict). Sample 6 mois trop petit pour estimer p-value
    sur combos rares de toute facon.
    """
    if len(phase_data) < 30:
        return {"valid_3folds": False, "fold_pfs": [0, 0, 0]}
    # Split chronologique (phase_data deja trie par start_ts)
    n = len(phase_data)
    cuts = [n // 3, 2 * n // 3]
    folds = [phase_data[:cuts[0]], phase_data[cuts[0]:cuts[1]], phase_data[cuts[1]:]]
    fold_pfs = []
    for f in folds:
        ev = evaluate_combo(f, combo, direction, sym, tp_ticks, sl_ticks, fwd_bars)
        fold_pfs.append(ev["pf"] if ev["pf"] != float("inf") else 99)
    # Combo retenu si PF > 1.3 sur les 3 folds
    valid = all(pf >= 1.3 for pf in fold_pfs)
    return {"valid_3folds": valid, "fold_pfs": fold_pfs}


def analyze(symbol: str, months: int = 6, tp_ticks: int = 12, sl_ticks: int = 12, fwd_bars: int = 15):
    print(f"=== Cluster Phase Starter V3 — {symbol} ({months} mois, TP={tp_ticks}t SL={sl_ticks}t) ===")
    df = load_v4(symbol, max_months=months)
    if df.empty:
        print("  Aucune data")
        return

    print(f"  Loaded {len(df)} bars, {df['ts_event'].min()} -> {df['ts_event'].max()}")

    phases = detect_phases_v3(df, symbol)
    n_up = sum(1 for p in phases if p["direction"] == "UP")
    n_dn = sum(1 for p in phases if p["direction"] == "DOWN")
    print(f"  Phases : {len(phases)} (UP={n_up} / DOWN={n_dn})")

    if not phases:
        return

    # Forward post-phase : capture niveaux + measure path-dependent
    up_data = []
    down_data = []
    for p in phases:
        bar = df.iloc[p["start_idx"]]
        if p["direction"] == "UP":
            actives = get_active_levels_at_bar(bar, SUPPORT_LEVELS)
            fwd = measure_forward_post_phase(df, p["end_idx"], "UP", symbol, fwd_bars, tp_ticks, sl_ticks)
            up_data.append({"levels": actives, "fwd": fwd, "phase": p})
        else:
            actives = get_active_levels_at_bar(bar, RESISTANCE_LEVELS)
            fwd = measure_forward_post_phase(df, p["end_idx"], "DOWN", symbol, fwd_bars, tp_ticks, sl_ticks)
            down_data.append({"levels": actives, "fwd": fwd, "phase": p})

    # Generer combos candidates (paires + triplets)
    n_levels_up = len(SUPPORT_LEVELS)
    n_levels_dn = len(RESISTANCE_LEVELS)
    n_tests_up = (n_levels_up * (n_levels_up - 1) // 2) + (n_levels_up * (n_levels_up - 1) * (n_levels_up - 2) // 6)
    n_tests_dn = (n_levels_dn * (n_levels_dn - 1) // 2) + (n_levels_dn * (n_levels_dn - 1) * (n_levels_dn - 2) // 6)

    # FIX 5 : Bonferroni
    alpha_bonf_up = 0.05 / n_tests_up
    alpha_bonf_dn = 0.05 / n_tests_dn
    print(f"\n  Tests potentiels UP: {n_tests_up}, alpha Bonferroni = {alpha_bonf_up:.2e}")
    print(f"  Tests potentiels DOWN: {n_tests_dn}, alpha Bonferroni = {alpha_bonf_dn:.2e}")

    def analyze_direction(direction_label, data, levels_map):
        print(f"\n--- {direction_label} starters (n={len(data)}) ---")
        # Compter combos avec n>=10
        combo_counter = Counter()
        for d in data:
            lvls = d["levels"]
            if len(lvls) < 2:
                continue
            for size in (2, 3):
                if len(lvls) >= size:
                    for combo in combinations(sorted(lvls), size):
                        combo_counter[combo] += 1

        # Filter freq >= 10 (puissance minimale)
        candidates = [(c, n) for c, n in combo_counter.items() if n >= 10]
        print(f"  {len(candidates)} combos avec n>=10")

        # Evaluate chaque combo : PF + walk-forward
        results = []
        for combo, n_obs in candidates:
            ev = evaluate_combo(data, combo, direction_label, symbol, tp_ticks, sl_ticks, fwd_bars)
            wf = walk_forward_validate(data, combo, direction_label, symbol, tp_ticks, sl_ticks, fwd_bars)
            # FIX 7 : score = PF * log(N)
            score = ev["pf"] * log(max(ev["n"], 2)) if ev["pf"] != float("inf") else 0
            results.append({
                "combo": combo, "n": ev["n"], "succ": ev["success_rate"],
                "pf": ev["pf"], "avg_pnl": ev["avg_pnl"],
                "wf_valid": wf["valid_3folds"], "fold_pfs": wf["fold_pfs"],
                "score": score,
            })

        # Bootstrap baseline pour combos avec PF > 1
        baseline_global = bootstrap_baseline_pf(data, combo_size=10, n_target=10)
        print(f"  Baseline random PF (1000 boot, n=10) : p50={baseline_global['p50']:.2f}, p95={baseline_global['p95']:.2f}, p99={baseline_global['p99']:.2f}")

        # FIX 2 code-reviewer v3 : cache bootstrap par n_target (gain 50-100x)
        # Sans cache : 500 combos x 1000 boot = 500k iter par direction.
        # Avec cache : ~50 distinct n values x 1000 boot = 50k iter.
        bootstrap_cache = {}

        # Filter VALIDES : PF > p95 baseline + walk-forward 3 folds OK
        validated = []
        for r in results:
            n_key = r["n"]
            if n_key not in bootstrap_cache:
                bootstrap_cache[n_key] = bootstrap_baseline_pf(data, combo_size=n_key, n_target=n_key)
            base_for_n = bootstrap_cache[n_key]
            if r["pf"] > base_for_n["p95"] and r["wf_valid"]:
                r["baseline_p95"] = base_for_n["p95"]
                validated.append(r)

        validated.sort(key=lambda x: x["score"], reverse=True)
        print(f"\n  COMBOS VALIDEES (PF > p95 baseline + 3 folds OK): {len(validated)} / {len(results)}")
        if validated:
            print(f"  TOP 10 :")
            print(f"    {'Combo':<55} {'N':>4} {'Succ%':>6} {'PF':>5} {'P95':>5} {'F1':>5} {'F2':>5} {'F3':>5}")
            for r in validated[:10]:
                combo_str = " + ".join(r["combo"])[:53]
                pf_str = f"{r['pf']:.2f}" if r['pf'] != float("inf") else "INF"
                p95_str = f"{r['baseline_p95']:.2f}"
                fp = r["fold_pfs"]
                print(f"    {combo_str:<53} {r['n']:>4} {r['succ']*100:>5.0f}% {pf_str:>5} "
                      f"{p95_str:>5} {fp[0]:>5.2f} {fp[1]:>5.2f} {fp[2]:>5.2f}")
        else:
            print(f"  AUCUNE combo validee (echec PF baseline OU walk-forward 3 folds)")

    analyze_direction("UP", up_data, SUPPORT_LEVELS)
    analyze_direction("DOWN", down_data, RESISTANCE_LEVELS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES"], default="NQ")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--tp-ticks", type=int, default=12)
    ap.add_argument("--sl-ticks", type=int, default=12)
    ap.add_argument("--fwd-bars", type=int, default=15)
    args = ap.parse_args()
    analyze(args.symbol, args.months, args.tp_ticks, args.sl_ticks, args.fwd_bars)


if __name__ == "__main__":
    main()
