"""
v5_gate_evaluator.py — Orchestre 4 baselines V5 + verdict GATE 17h

Created : 2026-05-02 samedi
Author : Jackson + GATE_17H_METHODOLOGY section 8 livrable

Goal : prendre les 4 modeles fitted (ES_BUY, ES_SELL, NQ_BUY, NQ_SELL),
calculer metrics OOS, appliquer decision tree pre-declare, output verdict
GO / NOGO / MARGINAL.

Conformite Lopez :
- DSR Bailey-Lopez via dsr_calculator.compute_dsr()
- n_trials = 120 minimum (Optuna inclus)
- Walk-forward folds chronologiquement alignes ES/NQ
- Costs inclus : ES 2.3 ticks, NQ 5.2 ticks (round-trip) + slip 1.5t

Critères GO clair (toutes conditions reunies) :
- PF OOS >= 1.40 (mediane folds)
- DSR >= 0.6 (vs 0.95 trop strict pour 1m bars)
- WR OOS >= 45%
- EV/trade >= 1.0t (ES) / 1.5t (NQ)
- Trades/jour >= 3
- Max DD <= 500 ticks (ES) / 300 ticks (NQ symetrie $)
- std(PF)/mean(PF) < 0.4 ET min(PF) > 0.8

Decision tree :
- 4/4 GO clair → deploy paper integral
- 3/4 GO → deploy 3 OK observe-only, investigation 1 NO-GO
- 2/4 GO symetrique SELL → deploy SELL only, archive BUY V6
- 2/4 GO asymetrique → MARGINAL hold-out
- 1/4 GO → MARGINAL strict hold-out
- 0/4 GO → pivot Voie 5
"""

from __future__ import annotations
from typing import Optional, Dict, List
import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsr_calculator import compute_dsr


# ═════════════════════════════════════════════════════════════════════
# SEUILS GO/NO-GO/MARGINAL (cf GATE_17H_METHODOLOGY)
# ═════════════════════════════════════════════════════════════════════

GATE_THRESHOLDS = {
    "PF_GO": 1.40,
    "PF_NOGO": 1.0,
    "DSR_GO": 0.60,         # Revise depuis 0.95 (trop strict 1m bars)
    "DSR_NOGO": 0.0,
    "WR_GO": 0.45,
    "WR_NOGO": 0.35,
    "EV_PER_TRADE_GO_ES": 1.0,    # ticks
    "EV_PER_TRADE_GO_NQ": 1.5,    # ticks
    "EV_PER_TRADE_NOGO": 0.0,
    "TRADES_PER_DAY_GO": 3,
    "MAX_DD_TICKS_ES": 500,
    "MAX_DD_TICKS_NQ": 300,        # symetrie $ vs ES (NQ tick = $0.50, ES = $1.25)
    "MAX_DD_NOGO_ES": 1500,
    "MAX_DD_NOGO_NQ": 900,
    "STD_PF_OVER_MEAN": 0.4,
    "MIN_PF_FOLD": 0.8,
    "MIN_PF_NOGO": 0.5,
    "MIN_CLASS_PCT": 0.10,    # Lopez : 10% min par classe
}

COST_TICKS = {"ES": 2.3, "NQ": 5.2}
SLIP_ENTRY_TICKS = 1.5  # cf market-analyst review Patch R4


# ═════════════════════════════════════════════════════════════════════
# EVALUATE 1 BACKTEST MODEL
# ═════════════════════════════════════════════════════════════════════

def evaluate_backtest_oos(returns_per_trade: np.ndarray,
                            symbol: str,
                            side: str,
                            n_trials: int = 120,
                            n_days: int = 250,
                            pf_per_fold: Optional[List[float]] = None) -> Dict:
    """
    Evaluate metrics OOS pour 1 modele (ex: ES_BUY).

    Args:
        returns_per_trade : array returns trade-par-trade (en pct ou ticks).
                            Recommande : ticks (PF se calcule directement).
        symbol : 'ES' ou 'NQ'
        side : 'buy' ou 'sell'
        n_trials : declaration trials Optuna pour DSR (default 120)
        n_days : nb jours periode OOS pour calc trades/jour
        pf_per_fold : list of PF par fold walk-forward (pour stabilite std/mean)

    Returns:
        Dict metrics + verdict per-combo (GO/NOGO/MARGINAL).
    """
    if len(returns_per_trade) < 10:
        return {"verdict": "INSUFFICIENT_DATA", "n_trades": len(returns_per_trade)}

    rets = np.asarray(returns_per_trade, dtype=float)
    n_trades = len(rets)

    # PF (gross profits / gross losses)
    gross_profit = rets[rets > 0].sum()
    gross_loss = -rets[rets < 0].sum()
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    wr = (rets > 0).mean()
    ev_per_trade = rets.mean()

    # Equity curve + max DD (en ticks ou $)
    equity = np.cumsum(rets)
    running_max = np.maximum.accumulate(equity)
    dd = running_max - equity
    max_dd = dd.max() if len(dd) > 0 else 0

    trades_per_day = n_trades / max(n_days, 1)

    # Stabilite folds
    if pf_per_fold and len(pf_per_fold) >= 2:
        pf_arr = np.array(pf_per_fold)
        std_over_mean = pf_arr.std() / pf_arr.mean() if pf_arr.mean() > 0 else 99
        min_pf_fold = pf_arr.min()
    else:
        std_over_mean = 0
        min_pf_fold = pf

    # DSR Bailey-Lopez
    dsr_res = compute_dsr(rets, n_trials=n_trials)
    dsr = dsr_res.get("dsr", 0)

    # Decision per-combo
    ev_threshold = GATE_THRESHOLDS["EV_PER_TRADE_GO_NQ"] if symbol == "NQ" \
        else GATE_THRESHOLDS["EV_PER_TRADE_GO_ES"]
    dd_threshold = GATE_THRESHOLDS["MAX_DD_TICKS_NQ"] if symbol == "NQ" \
        else GATE_THRESHOLDS["MAX_DD_TICKS_ES"]
    dd_nogo = GATE_THRESHOLDS["MAX_DD_NOGO_NQ"] if symbol == "NQ" \
        else GATE_THRESHOLDS["MAX_DD_NOGO_ES"]

    # NO-GO conditions (1 seule suffit)
    is_nogo = (
        pf < GATE_THRESHOLDS["PF_NOGO"] or
        dsr < GATE_THRESHOLDS["DSR_NOGO"] or
        wr < GATE_THRESHOLDS["WR_NOGO"] or
        ev_per_trade < GATE_THRESHOLDS["EV_PER_TRADE_NOGO"] or
        max_dd > dd_nogo or
        min_pf_fold < GATE_THRESHOLDS["MIN_PF_NOGO"]
    )

    # GO clair conditions (toutes reunies)
    is_go = (
        pf >= GATE_THRESHOLDS["PF_GO"] and
        dsr >= GATE_THRESHOLDS["DSR_GO"] and
        wr >= GATE_THRESHOLDS["WR_GO"] and
        ev_per_trade >= ev_threshold and
        trades_per_day >= GATE_THRESHOLDS["TRADES_PER_DAY_GO"] and
        max_dd <= dd_threshold and
        std_over_mean < GATE_THRESHOLDS["STD_PF_OVER_MEAN"] and
        min_pf_fold > GATE_THRESHOLDS["MIN_PF_FOLD"]
    )

    if is_nogo:
        verdict = "NOGO"
    elif is_go:
        verdict = "GO"
    else:
        verdict = "MARGINAL"

    return {
        "symbol": symbol, "side": side, "verdict": verdict,
        "pf": float(pf), "dsr": float(dsr), "wr": float(wr),
        "ev_per_trade": float(ev_per_trade),
        "max_dd": float(max_dd),
        "n_trades": int(n_trades), "trades_per_day": float(trades_per_day),
        "std_over_mean": float(std_over_mean),
        "min_pf_fold": float(min_pf_fold),
        "n_trials": n_trials,
    }


# ═════════════════════════════════════════════════════════════════════
# DECISION TREE FINAL — orchestre les 4 verdicts
# ═════════════════════════════════════════════════════════════════════

def decision_tree_final(results: Dict[str, Dict]) -> Dict:
    """
    Applique decision tree GATE 17h pre-declare.

    Args:
        results : dict {('ES','buy'): {...}, ('ES','sell'): {...}, ...}

    Returns:
        Dict verdict global + action recommandee.
    """
    verdicts = {k: v.get("verdict", "?") for k, v in results.items()}
    n_go = sum(1 for v in verdicts.values() if v == "GO")
    n_nogo = sum(1 for v in verdicts.values() if v == "NOGO")
    n_marg = sum(1 for v in verdicts.values() if v == "MARGINAL")

    # SELL only symetrique
    es_sell_go = verdicts.get(("ES", "sell")) == "GO"
    nq_sell_go = verdicts.get(("NQ", "sell")) == "GO"
    es_buy_nogo = verdicts.get(("ES", "buy")) == "NOGO"
    nq_buy_nogo = verdicts.get(("NQ", "buy")) == "NOGO"
    sym_sell_only = es_sell_go and nq_sell_go and es_buy_nogo and nq_buy_nogo

    if n_go == 4:
        decision = "DEPLOY_PAPER_INTEGRAL"
    elif n_go == 3:
        decision = "DEPLOY_3_OBSERVE_INVESTIGATE_1_NOGO"
    elif n_go == 2 and sym_sell_only:
        decision = "DEPLOY_SELL_ONLY_ARCHIVE_BUY"
    elif n_go == 2:
        decision = "MARGINAL_HOLDOUT_DECIDE"
    elif n_go == 1:
        decision = "MARGINAL_STRICT_HOLDOUT"
    else:  # n_go == 0
        decision = "PIVOT_VOIE_5"

    return {
        "n_go": n_go,
        "n_nogo": n_nogo,
        "n_marginal": n_marg,
        "decision": decision,
        "verdicts": verdicts,
        "details": results,
    }


# ═════════════════════════════════════════════════════════════════════
# REPORT FORMAT
# ═════════════════════════════════════════════════════════════════════

def print_report(final: Dict, n_trials_declared: int = 120) -> str:
    """Print verdict format reproduit le template DOCS/V5_GATE_17H_RESULTS.md."""
    lines = []
    lines.append("=" * 80)
    lines.append("V5 GATE 17h Results")
    lines.append("=" * 80)
    lines.append(f"\nSetup : n_trials={n_trials_declared}, "
                 f"costs ES={COST_TICKS['ES']}t, NQ={COST_TICKS['NQ']}t, "
                 f"slip={SLIP_ENTRY_TICKS}t\n")

    # Table par combo
    lines.append(f"{'Combo':10} | {'PF':>6} | {'DSR':>6} | {'WR':>6} | "
                 f"{'EV/t':>6} | {'Td/j':>6} | {'MaxDD':>6} | {'Verdict':>10}")
    lines.append("-" * 80)
    for (sym, side), m in final["details"].items():
        if "pf" not in m:
            lines.append(f"{sym}_{side:5}: {m.get('verdict', '?')}")
            continue
        lines.append(
            f"{sym}_{side:5} | "
            f"{m['pf']:6.2f} | {m['dsr']:6.3f} | {m['wr']:6.1%} | "
            f"{m['ev_per_trade']:6.2f} | {m['trades_per_day']:6.1f} | "
            f"{m['max_dd']:6.0f} | {m['verdict']:>10}"
        )

    lines.append("\n" + "=" * 80)
    lines.append(f"DECISION TREE : {final['decision']}")
    lines.append(f"  N_GO={final['n_go']}/4, N_MARGINAL={final['n_marginal']}, "
                 f"N_NOGO={final['n_nogo']}")
    lines.append("=" * 80)

    text = "\n".join(lines)
    print(text)
    return text


# ═════════════════════════════════════════════════════════════════════
# CLI / Tests synthetiques
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    np.random.seed(42)

    # Simuler 4 backtests
    fake_results = {
        ("ES", "buy"): evaluate_backtest_oos(
            returns_per_trade=np.random.normal(0.5, 3, 800),  # SR ~0.16
            symbol="ES", side="buy", n_trials=120, n_days=200,
            pf_per_fold=[1.3, 1.5, 1.4, 1.6, 1.45]
        ),
        ("ES", "sell"): evaluate_backtest_oos(
            returns_per_trade=np.random.normal(0.8, 3, 700),  # SR ~0.27
            symbol="ES", side="sell", n_trials=120, n_days=200,
            pf_per_fold=[1.5, 1.6, 1.55, 1.7, 1.5]
        ),
        ("NQ", "buy"): evaluate_backtest_oos(
            returns_per_trade=np.random.normal(0.2, 4, 600),
            symbol="NQ", side="buy", n_trials=120, n_days=200,
            pf_per_fold=[1.1, 0.9, 1.2, 1.05, 1.0]
        ),
        ("NQ", "sell"): evaluate_backtest_oos(
            returns_per_trade=np.random.normal(1.2, 4, 750),  # SR ~0.30
            symbol="NQ", side="sell", n_trials=120, n_days=200,
            pf_per_fold=[1.6, 1.7, 1.5, 1.65, 1.7]
        ),
    }

    final = decision_tree_final(fake_results)
    print_report(final, n_trials_declared=120)
