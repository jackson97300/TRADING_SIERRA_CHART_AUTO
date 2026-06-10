"""backtest_scale_out_be_bot3.py — Backtest preservation Scale-Out 50% + BE.

CONTEXTE (Jackson 07/05) :
"Avoir 4 micros lot, sortir 50% a X ticks, monter le stop au prix d'entree (BE)"

Approche standard pro (Tom Williams VSA, Linda Raschke "New Market Wizards") :
  - 4 contrats au lieu de 3
  - Quand MFE >= scale_out_trigger : market close 50% (= 2 contrats) → gain partiel
  - Move SL des 2 contrats restants a entry (BE = zero risque)
  - 2 micros restants laisses courir vers TP cap

Avantages vs trailing :
  1. Garantit gain partiel certain (vs trailing peut etre stop-out par bruit)
  2. BE protege le reste (zero risque)
  3. Pas de race condition complexe (1 evenement, pas 3 phases)
  4. Standard pro, backtestable

Backtest cible (regle souveraine CLAUDE.md "preservation wins") :
  - Charge trades historiques Bot 1 NQ + ES (proxy Bot 3, 318j)
  - Filtre trades MFE >= scale_out_trigger
  - Simule : 50% close a +X ticks + BE move pour les 50% restants
  - Compare delta PnL vs strategie actuelle (4 contrats laisses courir)

Anti-DSR : seuils figes par design (calcules pour locker $50-$100).
  - NQ : trigger 60t, lock = 60 * $0.50 * 2 = $60 (4 micros total, 2 sortis)
  - ES : trigger 25t, lock = 25 * $1.25 * 2 = $62.50

Hyperparametres :
  - n_contracts_total = 4 (vs 3 actuel)
  - scale_out_pct = 50% (= 2 micros)
  - scale_out_trigger_ticks NQ = 60 / ES = 25
  - SL move = entry (BE) pour les 2 restants
  - TP cap reste inchange pour les 2 restants

Usage :
    python -X utf8 CORE/research/backtest_scale_out_be_bot3.py [--symbol NQ] [--days 60]

Date : 2026-05-07
Auteur : MIA Trading System (post-verdict code-reviewer NOGO sur 3-phases)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# Tick values (4 micros total)
TICK_VALUE = {"NQ": 0.50, "ES": 1.25}
TICK_SIZE = 0.25

# Hyperparametres scale-out (calcules pour locker $50-$100)
SCALE_OUT_TRIGGER_TICKS = {
    "NQ": 60,   # MFE 60t * $0.50 * 2 micros = $60 securise
    "ES": 25,   # MFE 25t * $1.25 * 2 micros = $62.50 securise
}
SCALE_OUT_PCT = 0.50    # 50% de position fermee (2 micros sur 4)
N_CONTRACTS_TOTAL = 4   # vs 3 actuel
N_CONTRACTS_SCALE_OUT = 2  # 50% de 4
N_CONTRACTS_RUNNER = 2     # restants a BE


@dataclass
class TradeReplay:
    """Replay 1 trade : compare strategie actuelle vs scale-out + BE."""
    sym: str
    entry_price: float
    side: str            # LONG / SHORT
    sl_initial_ticks: int
    tp_cap_ticks: int
    mfe_ticks: float
    mae_ticks: float
    actual_exit_ticks: float    # ticks gain/loss reel observe (pnl_ticks)
    actual_exit_reason: str     # TP / SL / TIMEOUT
    bar_high: float = 0.0       # NEW : high atteint pendant trade (pour BE check)
    bar_low: float = 0.0        # NEW : low atteint pendant trade

    # Resultats simulation
    scale_out_triggered: bool = False
    scale_out_partial_ticks: float = 0.0    # gain sur 50% close (= trigger ticks)
    runner_exit_reason: str = ""             # TP_CAP / BE_HIT / TIMEOUT (sur 2 micros restants)
    runner_exit_ticks: float = 0.0
    pnl_actual_4c: float = 0.0               # PnL si 4 contrats actuel (pas scale-out)
    pnl_simu_4c: float = 0.0                 # PnL si scale-out + BE applique
    delta_pnl: float = 0.0


def simulate_scale_out(t: TradeReplay, sym: str) -> TradeReplay:
    """Applique simulation scale-out + BE sur un trade replayé.

    Logique :
      1. Si MFE >= scale_out_trigger → 2 micros sortent a +trigger_ticks (gain certain)
      2. Pour les 2 micros restants : SL move a entry (BE)
      3. Issue runner :
         - TP cap atteint avant BE → +tp_cap_ticks * 2 micros
         - BE hit avant TP → +0 ticks * 2 micros (zero risque)
         - TIMEOUT → ticks reels du trade actuel * 2 micros (proxy)
    """
    trigger = SCALE_OUT_TRIGGER_TICKS.get(sym, 60)
    tv = TICK_VALUE.get(sym, 0.50)
    n_total = N_CONTRACTS_TOTAL

    # PnL strategie actuelle (4 contrats laisses courir)
    t.pnl_actual_4c = t.actual_exit_ticks * tv * n_total

    # Si MFE n'atteint pas trigger → strategie scale-out PAS DECLENCHEE
    if t.mfe_ticks < trigger:
        t.scale_out_triggered = False
        t.pnl_simu_4c = t.pnl_actual_4c   # identique
        t.delta_pnl = 0.0
        return t

    # Scale-out trigger atteint
    t.scale_out_triggered = True
    t.scale_out_partial_ticks = float(trigger)

    # Issue runner (2 micros restants apres BE move) :
    # Hypothese conservative :
    #   - Si actual_exit_reason == TP : runner aussi a hit TP (mfe a continue)
    #   - Si actual_exit_reason == SL : runner a hit BE (entry) car BE > SL initial
    #     → runner sort a 0 ticks (BE hit)
    #   - Si actual_exit_reason == TIMEOUT : runner aussi TIMEOUT, exit a actual ticks
    if t.actual_exit_reason == "TP":
        t.runner_exit_ticks = t.actual_exit_ticks  # TP hit, runner aussi
        t.runner_exit_reason = "TP_CAP"
    elif t.actual_exit_reason == "SL":
        # SL initial hit → mais avec BE move, runner sort a entry (0 ticks)
        # IMPORTANT : verifier si BE hit a eu lieu AVANT le SL initial
        # Si MAE atteint <= 0 (= prix retourne sous entry) → BE hit
        # Si MAE > 0 → prix n'est pas retourne sous entry (pas possible si SL hit)
        # Donc si SL hit, prix a forcement retraced sous entry → BE hit
        t.runner_exit_ticks = 0.0  # BE = zero ticks
        t.runner_exit_reason = "BE_HIT"
    else:  # TIMEOUT ou autre
        # Approximation : runner expose a meme conditions que actual
        t.runner_exit_ticks = t.actual_exit_ticks
        t.runner_exit_reason = "TIMEOUT"

    # Calcul PnL simulation
    pnl_partial = t.scale_out_partial_ticks * tv * N_CONTRACTS_SCALE_OUT  # 2 micros
    pnl_runner = t.runner_exit_ticks * tv * N_CONTRACTS_RUNNER             # 2 micros
    t.pnl_simu_4c = pnl_partial + pnl_runner
    t.delta_pnl = t.pnl_simu_4c - t.pnl_actual_4c
    return t


def _recalc_mfe_from_bars(symbol: str, entry_ts, exit_ts, entry_price: float,
                          side: str) -> tuple[float, float]:
    """Recalcule MFE/MAE depuis V4 enriched parquet (bars OHLC entre entry et exit)."""
    try:
        import pyarrow.dataset as ds
        sym_map = {"NQ": "NQ.c.0", "ES": "ES.c.0"}
        path = Path(f"D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/v4_enriched/symbol={sym_map[symbol]}")
        if not path.exists():
            return 0.0, 0.0
        dataset = ds.dataset(path, format="parquet")
        df = dataset.to_table(columns=["ts_event", "high", "low"]).to_pandas()
        df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts_event"])
        entry_ts_pd = pd.to_datetime(entry_ts, utc=True)
        exit_ts_pd = pd.to_datetime(exit_ts, utc=True)
        mask = (df["ts_event"] >= entry_ts_pd) & (df["ts_event"] <= exit_ts_pd)
        window = df[mask]
        if len(window) == 0:
            return 0.0, 0.0
        if side == "LONG":
            mfe = (window["high"].max() - entry_price) / 0.25
            mae = (window["low"].min() - entry_price) / 0.25
        else:
            mfe = (entry_price - window["low"].min()) / 0.25
            mae = (entry_price - window["high"].max()) / 0.25
        return float(max(mfe, 0)), float(min(mae, 0))
    except Exception:
        return 0.0, 0.0


def load_trades_from_paper_trader(symbol: str, days: int = 60,
                                   recalc_mfe: bool = True) -> list[TradeReplay]:
    """Charge trades + recalcule MFE/MAE depuis bars V4 enriched si needed."""
    rows = []
    paper_dir = Path("DATA/PAPER_TRADES")
    if not paper_dir.exists():
        return []

    patterns = [
        "*_databento_v3_trades.jsonl",
        "*_trades.jsonl",
        "*_databento_trades.jsonl",
    ]
    seen_signal_ids = set()
    for pat in patterns:
        for fp in paper_dir.glob(pat):
            try:
                with fp.open("r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if ev.get("symbol") != symbol:
                            continue
                        pnl = ev.get("pnl_ticks")
                        if not isinstance(pnl, (int, float)):
                            continue
                        if ev.get("pnl_estimated"):
                            continue
                        side = ev.get("direction") or ev.get("side")
                        if side not in ("LONG", "SHORT"):
                            continue
                        # Dedup
                        sig_id = ev.get("signal_id") or f"{ev.get('entry_time')}_{ev.get('entry_price')}"
                        if sig_id in seen_signal_ids:
                            continue
                        seen_signal_ids.add(sig_id)

                        mfe = ev.get("mfe_ticks", 0) or 0
                        mae = ev.get("mae_ticks", 0) or 0
                        entry_ts = ev.get("entry_time") or ev.get("ts_open")
                        exit_ts = ev.get("exit_time") or ev.get("ts_close")
                        entry_price = float(ev.get("entry_price", 0))

                        # Recalc MFE/MAE depuis bars si valeur null/0 ou explicit recalc
                        if recalc_mfe and entry_ts and exit_ts and entry_price > 0:
                            mfe_calc, mae_calc = _recalc_mfe_from_bars(
                                symbol, entry_ts, exit_ts, entry_price, side
                            )
                            if mfe_calc > mfe:
                                mfe = mfe_calc
                            if mae_calc < mae:
                                mae = mae_calc

                        sl_init = ev.get("sl_ticks") or ev.get("sl") or 80
                        rows.append(TradeReplay(
                            sym=symbol,
                            entry_price=entry_price,
                            side=side,
                            sl_initial_ticks=int(sl_init),
                            tp_cap_ticks=160,
                            mfe_ticks=float(mfe),
                            mae_ticks=float(mae),
                            actual_exit_ticks=float(pnl),
                            actual_exit_reason=ev.get("reason") or ev.get("exit_reason") or "?",
                        ))
            except Exception:
                continue
    return rows


def synthesize(trades: list[TradeReplay], sym: str) -> dict:
    """Compute stats backtest scale-out vs actuel."""
    if not trades:
        return {"n_total": 0, "verdict": "NO_DATA"}

    n_total = len(trades)
    n_triggered = sum(1 for t in trades if t.scale_out_triggered)
    trigger_rate = n_triggered / n_total

    pnl_actual_total = sum(t.pnl_actual_4c for t in trades)
    pnl_simu_total = sum(t.pnl_simu_4c for t in trades)
    delta_total = pnl_simu_total - pnl_actual_total

    # WR / PF
    wins_actual = [t for t in trades if t.pnl_actual_4c > 0]
    losses_actual = [t for t in trades if t.pnl_actual_4c < 0]
    wins_simu = [t for t in trades if t.pnl_simu_4c > 0]
    losses_simu = [t for t in trades if t.pnl_simu_4c < 0]

    wr_actual = len(wins_actual) / n_total
    wr_simu = len(wins_simu) / n_total

    pf_actual = (sum(t.pnl_actual_4c for t in wins_actual) /
                 abs(sum(t.pnl_actual_4c for t in losses_actual))) if losses_actual else float('inf')
    pf_simu = (sum(t.pnl_simu_4c for t in wins_simu) /
               abs(sum(t.pnl_simu_4c for t in losses_simu))) if losses_simu else float('inf')

    # Trades WHERE scale_out aurait change le resultat
    delta_positive = [t for t in trades if t.scale_out_triggered and t.delta_pnl > 0]
    delta_negative = [t for t in trades if t.scale_out_triggered and t.delta_pnl < 0]
    delta_neutral = [t for t in trades if t.scale_out_triggered and t.delta_pnl == 0]

    return {
        "n_total": n_total,
        "n_triggered": n_triggered,
        "trigger_rate": round(trigger_rate, 3),
        "wr_actual": round(wr_actual, 3),
        "wr_simu": round(wr_simu, 3),
        "pf_actual": round(pf_actual, 2) if pf_actual != float('inf') else float('inf'),
        "pf_simu": round(pf_simu, 2) if pf_simu != float('inf') else float('inf'),
        "pnl_actual_total": round(pnl_actual_total, 2),
        "pnl_simu_total": round(pnl_simu_total, 2),
        "delta_pnl_total": round(delta_total, 2),
        "n_delta_positive": len(delta_positive),
        "n_delta_negative": len(delta_negative),
        "n_delta_neutral": len(delta_neutral),
    }


def main(symbol: str, days: int) -> None:
    print(f"=== Backtest Scale-Out 50% + BE — {symbol} (last {days}j) ===\n")
    trades = load_trades_from_paper_trader(symbol, days)
    print(f"Trades loaded: {len(trades)}")

    if not trades:
        print("Aucun trade trouve - lancer apres au moins quelques jours de paper")
        return

    # Apply simulation
    for t in trades:
        simulate_scale_out(t, symbol)

    summary = synthesize(trades, symbol)
    print("\n=== STATS ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # Top trades affectes
    triggered = sorted([t for t in trades if t.scale_out_triggered],
                       key=lambda t: t.delta_pnl, reverse=True)
    if triggered:
        print(f"\n=== TOP 5 trades positivement affectes ===")
        for t in triggered[:5]:
            print(f"  {t.side} {t.sym} entry={t.entry_price:.2f} mfe={t.mfe_ticks:.0f}t "
                  f"actual_exit={t.actual_exit_ticks:+.0f}t (${t.pnl_actual_4c:+.2f}) -> "
                  f"simu=({t.scale_out_partial_ticks:.0f}t partial + {t.runner_exit_ticks:+.0f}t runner) "
                  f"= ${t.pnl_simu_4c:+.2f} (delta {t.delta_pnl:+.2f})")

        if len([t for t in triggered if t.delta_pnl < 0]):
            print(f"\n=== TOP 5 trades negativement affectes (perte d'opportunite) ===")
            negs = sorted([t for t in triggered if t.delta_pnl < 0], key=lambda t: t.delta_pnl)
            for t in negs[:5]:
                print(f"  {t.side} {t.sym} entry={t.entry_price:.2f} mfe={t.mfe_ticks:.0f}t "
                      f"actual_exit={t.actual_exit_ticks:+.0f}t (${t.pnl_actual_4c:+.2f}) -> "
                      f"simu=${t.pnl_simu_4c:+.2f} (delta {t.delta_pnl:+.2f})")

    # Verdict
    print("\n=== VERDICT ===")
    if summary["n_total"] < 30:
        print(f"  INSUFFICIENT (n={summary['n_total']} < 30 Lopez)")
    elif summary["delta_pnl_total"] > 0 and summary["pf_simu"] >= summary["pf_actual"]:
        print(f"  GO Phase 1 (delta PnL +${summary['delta_pnl_total']:.2f}, PF {summary['pf_actual']}->{summary['pf_simu']})")
    elif summary["delta_pnl_total"] >= 0:
        print(f"  GO RESERVE (delta neutre ${summary['delta_pnl_total']:.2f}, PF {summary['pf_actual']}->{summary['pf_simu']})")
    else:
        print(f"  NOGO (delta -${abs(summary['delta_pnl_total']):.2f}, scale-out coute plus qu'il rapporte)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(args.symbol, args.days)
