"""backtest_rules_pd_attentiste.py — Walk-forward 60j sur rules_trader_pd_attentiste.

Spec : DOCS/specs/2026-04-28-rules-trader-pd-attentiste-design.md section 8.

Logique :
  Pour chaque jour J avec PDLevels J-1 disponible :
    - Charge JSONL DMP du jour J (DATA/{ES,NQ}/YYYYMMDD_*.jsonl)
    - Charge PDLevels J-1 (DATA/PD_LEVELS/YYYYMMDD_{symbol}.json)
    - Pour chaque barre RTH du jour J : evaluate_scenarios(bar, pdl_J-1)
    - Pour chaque RuleSignal fire : simule trade (TP1/TP2/SL/time-stop 90 bars)
    - Cooldown 30 min apres fill / SL hit
    - 1 trade max actif par symbol

Metriques aggregate :
  - PF, Sharpe, MaxDD, n_trades par scenario + global
  - Critere GO : PF >= 1.30, Sharpe >= 1.0, MaxDD <= 300t, N >= 30

Auteur : MIA Trading System V2
Date   : 2026-04-28 01:10 (Voie 2 Bloc 3 — Plan B Rules PD)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.pd_levels_extractor import PDLevels  # noqa: E402
from CORE.rules_trader_pd_attentiste import evaluate_scenarios, RuleSignal  # noqa: E402

TICK_SIZE = 0.25
COOLDOWN_BARS = 30  # 30 bars = 30 min en 1m timeframe
TIME_STOP_BARS = 90  # exit si pas TP1 dans 90 min
COST_TICKS_ES = 1.0
COST_TICKS_NQ = 0.5


@dataclass
class TradeResult:
    scenario: str
    symbol: str
    date: str
    direction: int
    entry: float
    sl: float
    tp1: float
    tp2: float
    exit_price: float
    exit_reason: str   # "TP1", "TP2", "SL", "TIME_STOP", "EOD"
    pnl_ticks: float
    bars_held: int


@dataclass
class BacktestResult:
    symbol: str
    n_days: int
    trades: List[TradeResult] = field(default_factory=list)
    by_scenario: dict = field(default_factory=lambda: defaultdict(list))

    def metrics(self) -> dict:
        """Calcule PF, Sharpe, MaxDD, n_trades, win_rate (global + par scenario)."""
        out = {"global": _compute_metrics(self.trades, self.symbol)}
        for sc, ts in self.by_scenario.items():
            out[sc] = _compute_metrics(ts, self.symbol)
        return out


def _compute_metrics(trades: List[TradeResult], symbol: str) -> dict:
    if not trades:
        return {"n_trades": 0, "win_rate": 0, "pf": 0, "ev": 0, "sharpe": 0,
                "max_dd": 0, "total_pnl": 0}
    pnls = np.array([t.pnl_ticks for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else \
         (float("inf") if len(losses) == 0 else 0)
    sharpe = float(pnls.mean() / pnls.std() * np.sqrt(252)) if pnls.std() > 0 else 0
    cum = np.cumsum(pnls)
    max_dd = float(np.max(np.maximum.accumulate(cum) - cum))
    return {
        "n_trades": len(trades),
        "win_rate": float((pnls > 0).mean()),
        "pf": round(pf, 3) if pf != float("inf") else "inf",
        "ev": round(float(pnls.mean()), 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd, 1),
        "total_pnl": round(float(pnls.sum()), 1),
    }


def _et_min(ts_ms: int) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return ((dt.hour - 4) % 24) * 60 + dt.minute


def _load_pdl(date_str: str, symbol: str) -> Optional[PDLevels]:
    """Charge DATA/PD_LEVELS/YYYYMMDD_{symbol}.json."""
    fp = ROOT / "DATA" / "PD_LEVELS" / f"{date_str}_{symbol}.json"
    if not fp.exists():
        return None
    with open(fp, "r", encoding="utf-8") as f:
        d = json.load(f)
    return PDLevels(**d)


def _load_jsonl_rth(date_str: str, symbol: str) -> List[dict]:
    """[Legacy] Charge JSONL brut d'une journee. Use parquet v5d preferred."""
    fp = ROOT / "DATA" / symbol / f"{date_str}_{symbol}.jsonl"
    if not fp.exists():
        return []
    rows = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    for r in rows:
        r["mins_et"] = _et_min(r["ts"])
    rth = [r for r in rows if 570 <= r["mins_et"] <= 960]
    rth.sort(key=lambda r: r["ts"])
    return rth


def load_parquet_v5d_by_date(symbol: str) -> dict:
    """Charge parquet v5d et regroupe par date (YYYYMMDD).

    Returns: dict {date_str: list of bar dicts (RTH only, sorted by ts)}.
    """
    import pandas as pd
    fp = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
    if not fp.exists():
        return {}
    df = pd.read_parquet(fp)
    # ts est en ms epoch
    df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["date_str"] = df["ts_dt"].dt.strftime("%Y%m%d")
    # Filtre RTH si mins_et present
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    by_date = {}
    for date_str, group in df.groupby("date_str"):
        bars = group.sort_values("ts").to_dict(orient="records")
        by_date[date_str] = bars
    return by_date


def _simulate_trade(signal: RuleSignal, bars: List[dict], i_entry: int,
                     symbol: str) -> Optional[TradeResult]:
    """Simule un trade : entry au close[i_entry], suivi TP1/TP2/SL/time-stop."""
    cost = COST_TICKS_NQ if symbol == "NQ" else COST_TICKS_ES
    entry = signal.entry
    sl = signal.sl
    tp1 = signal.tp1
    tp2 = signal.tp2
    direction = signal.direction

    # Distance ticks
    sl_ticks = abs(entry - sl) / TICK_SIZE
    tp1_ticks = abs(tp1 - entry) / TICK_SIZE
    tp2_ticks = abs(tp2 - entry) / TICK_SIZE

    # Suivi bar-par-bar (TP1 sortie 50%, suite jusqu'a TP2 ou SL ou time-stop)
    tp1_hit = False
    pnl_ticks = 0.0
    bars_held = 0
    exit_reason = "TIME_STOP"
    exit_price = entry

    max_bars = min(TIME_STOP_BARS, len(bars) - i_entry - 1)

    for k in range(1, max_bars + 1):
        j = i_entry + k
        if j >= len(bars):
            break
        bj = bars[j]
        h = float(bj.get("high") or bj.get("bar_high") or bj.get("price") or bj.get("close"))
        l = float(bj.get("low") or bj.get("bar_low") or bj.get("price") or bj.get("close"))
        bars_held = k

        if direction == 1:  # BUY
            if l <= sl:
                if not tp1_hit:
                    pnl_ticks = -sl_ticks - cost
                    exit_reason = "SL"
                else:
                    # TP1 deja hit, BE move : SL = entry → exit a entry
                    pnl_ticks = (tp1_ticks - 0) / 2 - cost  # 50% TP1 + 50% BE
                    exit_reason = "BE_AFTER_TP1"
                exit_price = sl
                break
            if h >= tp2:
                # TP1 (50%) + TP2 (50%)
                pnl_ticks = (tp1_ticks + tp2_ticks) / 2 - cost
                exit_reason = "TP2"
                exit_price = tp2
                break
            if not tp1_hit and h >= tp1:
                tp1_hit = True
                # SL move au break-even (entry)
                sl = entry
        else:  # SELL
            if h >= sl:
                if not tp1_hit:
                    pnl_ticks = -sl_ticks - cost
                    exit_reason = "SL"
                else:
                    pnl_ticks = (tp1_ticks - 0) / 2 - cost
                    exit_reason = "BE_AFTER_TP1"
                exit_price = sl
                break
            if l <= tp2:
                pnl_ticks = (tp1_ticks + tp2_ticks) / 2 - cost
                exit_reason = "TP2"
                exit_price = tp2
                break
            if not tp1_hit and l <= tp1:
                tp1_hit = True
                sl = entry

    if exit_reason == "TIME_STOP":
        # Marked-to-market au close de la derniere barre
        b_last = bars[min(i_entry + bars_held, len(bars) - 1)]
        last_close = float(b_last.get("price") or b_last.get("close"))
        if direction == 1:
            pnl_ticks = (last_close - entry) / TICK_SIZE - cost
        else:
            pnl_ticks = (entry - last_close) / TICK_SIZE - cost
        exit_price = last_close
        if tp1_hit:
            exit_reason = "TIME_STOP_AFTER_TP1"

    return TradeResult(
        scenario=signal.scenario, symbol=symbol, date="",
        direction=direction, entry=entry, sl=signal.sl,
        tp1=signal.tp1, tp2=signal.tp2,
        exit_price=exit_price, exit_reason=exit_reason,
        pnl_ticks=pnl_ticks, bars_held=bars_held,
    )


def backtest_day(date_str: str, symbol: str, pdl_prev: PDLevels,
                  bars: Optional[List[dict]] = None) -> List[TradeResult]:
    """Backtest une journee : eval scenarios bar-par-bar + simule trades.

    Args:
        bars: si None, charge depuis JSONL legacy. Sinon utilise les bars passes
              (preferre : parquet v5d via load_parquet_v5d_by_date).
    """
    if bars is None:
        bars = _load_jsonl_rth(date_str, symbol)
    if not bars:
        return []

    trades = []
    last_exit_bar = -COOLDOWN_BARS - 1
    in_trade = False
    trade_exit_idx = -1

    for i, bar in enumerate(bars):
        # Cooldown apres dernier exit
        if i - last_exit_bar < COOLDOWN_BARS:
            continue
        if in_trade and i <= trade_exit_idx:
            continue
        in_trade = False

        signals = evaluate_scenarios(bar, pdl_prev)
        if not signals:
            continue

        # Prendre le 1er signal par priorite (A > B > C > D ordre dans SCENARIO_FNS)
        signal = signals[0]
        tr = _simulate_trade(signal, bars, i, symbol)
        if tr is None:
            continue
        tr.date = date_str
        trades.append(tr)
        last_exit_bar = i + tr.bars_held
        trade_exit_idx = i + tr.bars_held
        in_trade = True

    return trades


def main():
    print("=" * 70)
    print("BACKTEST Rules PD Attentiste — Voie 2 Bloc 3")
    print("=" * 70)

    pd_levels_dir = ROOT / "DATA" / "PD_LEVELS"
    if not pd_levels_dir.exists():
        print("[FAIL] DATA/PD_LEVELS/ absent. Run CORE/backfill_pd_levels.py first.")
        sys.exit(1)

    # Charge parquet v5d (toutes features) plutot que JSONL brut (raw output C++)
    for symbol in ["ES", "NQ"]:
        print(f"\n{'='*70}\n  {symbol} — Backtest Rules PD (parquet v5d)\n{'='*70}")
        bars_by_date = load_parquet_v5d_by_date(symbol)
        if not bars_by_date:
            print(f"  [{symbol}] No parquet v5d found, skip.")
            continue
        dates = sorted(bars_by_date.keys())
        print(f"  Loaded {len(dates)} dates from parquet")

        result = BacktestResult(symbol=symbol, n_days=0)
        for i in range(1, len(dates)):  # commence a 1 (besoin de J-1)
            date_j = dates[i]
            date_jm1 = dates[i - 1]
            pdl_prev = _load_pdl(date_jm1, symbol)
            if pdl_prev is None:
                continue
            bars_j = bars_by_date[date_j]
            trades = backtest_day(date_j, symbol, pdl_prev, bars=bars_j)
            for t in trades:
                result.trades.append(t)
                result.by_scenario[t.scenario].append(t)
            result.n_days += 1

        # Print metrics
        m = result.metrics()
        print(f"\n[RECAP {symbol}] n_days={result.n_days}, n_trades={len(result.trades)}")
        print(f"\n  -- GLOBAL --")
        for k, v in m["global"].items():
            print(f"    {k:12s}: {v}")
        for sc, met in m.items():
            if sc == "global":
                continue
            print(f"\n  -- {sc} --")
            for k, v in met.items():
                print(f"    {k:12s}: {v}")

        # GO/NO-GO criteria (spec section 8)
        g = m["global"]
        critical = []
        if g["n_trades"] < 30:
            critical.append(f"n_trades {g['n_trades']} < 30")
        if isinstance(g["pf"], (int, float)) and g["pf"] < 1.30:
            critical.append(f"pf {g['pf']} < 1.30")
        if g["sharpe"] < 1.0:
            critical.append(f"sharpe {g['sharpe']} < 1.0")
        if g["max_dd"] > 300:
            critical.append(f"max_dd {g['max_dd']} > 300")

        if not critical:
            print(f"\n  [{symbol}] VERDICT : ✅ GO PAPER TRADING (5 micro)")
        else:
            print(f"\n  [{symbol}] VERDICT : ❌ NO-GO ({', '.join(critical)})")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
