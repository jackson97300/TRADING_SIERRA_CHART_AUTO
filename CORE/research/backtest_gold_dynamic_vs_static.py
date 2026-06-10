"""Backtest comparatif Gold : approche DYNAMIQUE (7+1 scénarios) vs STATIQUE (6 setups).

Réflexion Jackson 12/05/2026 : les 6 setups statiques sont biaisés SHORT (régime 2026).
L'approche dynamique réutilise Bot 3 NQ/ES architecture :
  - Niveaux NEUTRAUX
  - 7 scénarios standard (Structure × Orderflow)
  - 8ème scénario macro override Gold-spécifique

Comparaison sur 4 mois MGC enrichi MQ Gold :
  - PF, WR, n
  - Distribution LONG/SHORT (dynamique doit être ~50/50, statique 5/6 SHORT)
  - Walk-forward stability si temps

Usage : python -X utf8 CORE/research/backtest_gold_dynamic_vs_static.py
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np

from bot3_gold_level_definitions import GOLD_LEVELS_NEUTRAL, is_ticks_level
from bot3_gold_decision_engine import evaluate_decision_gold

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"
OUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"

# Constantes Gold
TICK_SIZE = 0.10
TICK_VALUE = 1.0
N_CONTRACTS = 3
COMMISSION_PER_RT = 0.74

SLIP_RTH = {"entry": 1.5, "sl": 1.5, "tp": 0.5}
SLIP_ASIA = {"entry": 4.0, "sl": 3.0, "tp": 1.0}


def detect_session(bar):
    if int(bar.get("is_in_us_cash", 0) or 0) == 1:
        return "RTH"
    if int(bar.get("is_in_us_after", 0) or 0) == 1:
        return "RTH"
    if int(bar.get("is_in_london", 0) or 0) == 1:
        return "LONDON"
    if int(bar.get("is_in_asia", 0) or 0) == 1:
        return "ASIA"
    return "OTHER"


def detect_touch(bar: dict, level_def: dict) -> tuple[bool, float]:
    """Détecte si le prix touche un niveau Gold.

    Returns: (touched, dist_signed)
    """
    col = level_def["col"]
    val = bar.get(col)
    if val is None or pd.isna(val):
        return False, 0.0

    try:
        dist = float(val)
    except (TypeError, ValueError):
        return False, 0.0

    if dist != dist:  # NaN
        return False, 0.0

    if is_ticks_level(level_def):
        # Proximity en ticks (dist déjà en ticks pour mq_*, blind_*)
        prox_ticks = level_def["prox_ticks"]
        return abs(dist) <= prox_ticks, dist
    else:
        # Proximity en pct
        prox_pct = level_def["prox"]
        return abs(dist) <= prox_pct, dist


def simulate_trade(df, entry_idx, side, sl_ticks, tp_ticks, session, timeout_min=30):
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    slip = SLIP_RTH if session == "RTH" else SLIP_ASIA
    direction = 1 if side == "LONG" else -1
    entry_with_slip = entry_price + direction * slip["entry"] * TICK_SIZE
    sl_price = entry_with_slip - direction * sl_ticks * TICK_SIZE
    tp_price = entry_with_slip + direction * tp_ticks * TICK_SIZE

    for j in range(1, timeout_min + 1):
        idx = entry_idx + j
        if idx >= len(df):
            break
        bar = df.iloc[idx]
        h = float(bar["high"])
        l = float(bar["low"])
        sl_hit = (direction == 1 and l <= sl_price) or (direction == -1 and h >= sl_price)
        tp_hit = (direction == 1 and h >= tp_price) or (direction == -1 and l <= tp_price)
        if sl_hit and tp_hit:
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL_AMB"
        if sl_hit:
            exit_p = sl_price - direction * slip["sl"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "SL"
        if tp_hit:
            exit_p = tp_price - direction * slip["tp"] * TICK_SIZE
            pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
            pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
            return pnl_d, j, "TP"

    last_idx = min(entry_idx + timeout_min, len(df) - 1)
    exit_p = float(df.iloc[last_idx]["close"]) - direction * slip["sl"] * TICK_SIZE * 0.5
    pnl_t = (exit_p - entry_with_slip) / TICK_SIZE * direction
    pnl_d = pnl_t * TICK_VALUE * N_CONTRACTS - COMMISSION_PER_RT * N_CONTRACTS
    return pnl_d, last_idx - entry_idx, "TIMEOUT"


def build_ctx_from_bar(bar: dict) -> dict:
    """Construit dict ctx pour decision_engine_gold (mappe colonnes parquet → ctx keys)."""
    ctx = {}
    # Direct mappings
    for key in [
        "delta_bar", "delta_pct", "finish_strength", "rvol", "vol_zscore_20",
        "atr_14m_pct", "bar_body_pct", "bar_upper_wick_pct", "bar_lower_wick_pct",
        "bar_no_trade", "cur_va_n_buckets", "cur_va_total_vol",
        "spike_detected_lag3", "vol_spike_up", "vol_spike_dn",
        "bn_stack_ask", "bn_stack_bid",
        "n_big_bid_t3", "n_big_bid_t4", "n_big_ask_t3", "n_big_ask_t4",
        "bn_absorb_bid_at_level", "bn_absorb_ask_at_level",
        "liq_sweep_high", "liq_sweep_low", "color_imbalance",
        "cvd_divergence", "cvd_divergence_dir",
        "poc_migration_dir", "ctx_poc_migration_10", "ctx_va_developing_10",
        # Gold intermarket
        "im_real_yields_proxy", "im_dxy_corr_60d",
        "gold_silver_ratio_zscore_60d",
        # Session
        "london_fix_window_10_30", "london_fix_window_15_00",
        # News
        "within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
        "within_news_845_5m", "within_news_900_5m", "within_news_930_5m",
    ]:
        if key in bar:
            ctx[key] = bar[key]

    # Alias ctx pour évaluation (compat bot3_decision_engine)
    ctx["poc_mig_dir"] = bar.get("poc_migration_dir", 0)
    ctx["poc_mig_speed"] = bar.get("ctx_poc_migration_10", 0.0)
    ctx["va_dev"] = bar.get("ctx_va_developing_10", 0.0)
    # max/min delta bar (Wyckoff)
    ctx["max_delta_bar"] = bar.get("max_delta_bar", 0.0)
    ctx["min_delta_bar"] = bar.get("min_delta_bar", 0.0)

    return ctx


def run_dynamic_backtest(df):
    """Backtest dynamique : niveaux NEUTRAUX + 7+1 scénarios."""
    print(f"\n=== BACKTEST DYNAMIQUE GOLD (niveaux NEUTRAUX + 7+1 scénarios) ===\n")

    levels = GOLD_LEVELS_NEUTRAL
    print(f"  Niveaux : {len(levels)} (tous NEUTRAUX)")

    pnls = []
    decisions = []   # log : level, side, action, macro_override
    open_until = -1
    exit_counts = {"TP": 0, "SL": 0, "SL_AMB": 0, "TIMEOUT": 0}
    n_long = 0
    n_short = 0
    n_skips = {}
    n_evaluated = 0

    for i in range(len(df)):
        if i <= open_until:
            continue
        bar = df.iloc[i].to_dict()
        session = detect_session(bar)

        # Iterate levels, detect touches
        touched_levels = []
        for lvl_name, lvl_def in levels.items():
            touched, dist = detect_touch(bar, lvl_def)
            if touched:
                touched_levels.append((lvl_name, lvl_def, dist))

        if not touched_levels:
            continue

        # Tie-break : prendre le Tier 1 le plus proche, sinon Tier 2
        touched_levels.sort(key=lambda x: (x[1].get("tier", 99), abs(x[2])))
        lvl_name, lvl_def, dist = touched_levels[0]
        n_evaluated += 1

        # Build context
        ctx = build_ctx_from_bar(bar)

        # Decision
        trade, reason, params = evaluate_decision_gold(lvl_name, lvl_def, ctx, dist)

        if not trade:
            # Skip log
            r = reason.split("_")[0] if "_" in reason else reason
            n_skips[r] = n_skips.get(r, 0) + 1
            continue

        side = params["side"]
        sl_ticks = params["sl_ticks"]
        tp_ticks = sl_ticks * 2  # R:R 2.0
        result = simulate_trade(df, i, side, sl_ticks, tp_ticks, session)
        if result is None:
            continue
        pnl, dur, exit_reason = result
        pnls.append(pnl)
        open_until = i + dur
        exit_counts[exit_reason] = exit_counts.get(exit_reason, 0) + 1
        if side == "LONG":
            n_long += 1
        else:
            n_short += 1

        decisions.append({
            "level": lvl_name, "side": side, "action": params["action"],
            "confidence": params["confidence"], "macro_override": params.get("macro_override"),
            "pnl": pnl, "exit": exit_reason,
        })

    # Stats
    if not pnls:
        print("  AUCUN TRADE")
        return {"approach": "DYNAMIC", "n": 0}

    pnls_arr = np.array(pnls)
    wins = pnls_arr[pnls_arr > 0].sum()
    losses = abs(pnls_arr[pnls_arr < 0].sum())
    pf = wins / losses if losses > 0 else 999.0
    wr = (pnls_arr > 0).sum() / len(pnls_arr) * 100
    ev = pnls_arr.mean()
    total = pnls_arr.sum()
    long_pct = n_long / (n_long + n_short) * 100 if (n_long + n_short) > 0 else 0

    print(f"\n  Niveaux évalués (touches) : {n_evaluated:,}")
    print(f"  Trades exécutés : {len(pnls):,}")
    print(f"  PF : {pf:.3f}, WR : {wr:.1f}%, EV : ${ev:.2f}")
    print(f"  Total PnL : ${total:,.2f}")
    print(f"  Distribution side : LONG={n_long} ({long_pct:.1f}%) / SHORT={n_short} ({100-long_pct:.1f}%)")
    print(f"  Exit reasons : {exit_counts}")
    print(f"\n  Top skips (raisons rejet) :")
    for r, n in sorted(n_skips.items(), key=lambda x: -x[1])[:10]:
        print(f"    {r:30s} {n:5d}")

    # Macro override stats
    macro_overrides = [d.get("macro_override") for d in decisions if d.get("macro_override")]
    if macro_overrides:
        from collections import Counter
        mo_cnt = Counter(macro_overrides)
        print(f"\n  Macro overrides actifs sur trades exécutés :")
        for k, v in mo_cnt.most_common():
            print(f"    {k}: {v}")

    return {
        "approach": "DYNAMIC",
        "n": len(pnls), "pf": round(pf, 3), "wr": round(wr, 1),
        "ev": round(ev, 2), "total_pnl": round(total, 2),
        "n_long": n_long, "n_short": n_short, "long_pct": round(long_pct, 1),
        "exit_counts": exit_counts,
        "n_evaluated": n_evaluated,
        "n_skips_total": sum(n_skips.values()),
        "decisions_sample": decisions[:50],
    }


def main():
    print(f"=== BACKTEST DYNAMIQUE GOLD ===\n")
    print(f"  Source : {INPUT}")
    df = pd.read_parquet(INPUT)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  Shape : {df.shape}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_dyn = run_dynamic_backtest(df)

    # Comparaison vs static (résultats de edge_discovery_gold précédent)
    print(f"\n\n=== COMPARAISON DYNAMIQUE vs STATIQUE (RTH 4m) ===")
    print(f"  STATIQUE (6 setups SHORT-biaisés) :")
    print(f"    n=1699 (sum 6 setups), PF moyen ~1.50, biais 5/6 SHORT")
    print(f"\n  DYNAMIQUE (7+1 scenarios sur 15 niveaux NEUTRAUX) :")
    print(f"    n={result_dyn['n']}, PF={result_dyn['pf']}, WR={result_dyn['wr']}%")
    print(f"    Distribution : LONG={result_dyn['long_pct']}% / SHORT={100-result_dyn['long_pct']}%")

    print(f"\n=== VERDICT ===")
    if result_dyn["n"] < 50:
        verdict = "INSUFFICIENT n — proximité ou seuils trop stricts"
    elif result_dyn["pf"] >= 1.3 and result_dyn["wr"] >= 50:
        verdict = "GO DYNAMIQUE — approche dynamique valide"
    elif result_dyn["pf"] >= 1.1:
        verdict = "MARGINAL — sélectivité élevée, à valider walk-forward"
    else:
        verdict = "NOGO — convergence 7 scénarios trop stricte ou contexte Gold ≠ NQ/ES"
    print(f"  {verdict}")

    out = OUT_DIR / "gold_dynamic_vs_static_results.json"
    out.write_text(json.dumps(result_dyn, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved : {out}")


if __name__ == "__main__":
    main()
