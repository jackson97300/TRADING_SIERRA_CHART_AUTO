"""backtest_bn_v2.py — Backtest empirique BNEngine V2 sur V4 enriched NQ.

Methodologie :
  1. Charge dataset NQ v4_enriched (toutes features dispo)
  2. Walk-forward : pour chaque bar, BNEngine.update(df[:i+1], state)
  3. Si LONG_ENTRY → simule trade : exit = SL hit OU golden rule violation
  4. Si TRAIL_SL → met a jour trail dynamique
  5. Compute : N_trades, WR, PF, EV/trade, max DD, max consecutive losses
  6. Stats par jour : frequence setups (Jackson : "rare mais genial")

Anti-DSR : pas de tuning sur metric. Hyperparams figes :
  - SL_INITIAL_TICKS = 7
  - BASE_MIN_DURATION = 5
  - SWING_MIN_BARS = 3

Usage :
    python -X utf8 CORE/research/backtest_bn_v2.py [--symbol NQ] [--bars 30000]

Date : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CORE.bn_engine import BNEngine, BNState, TICK_SIZE


# ─── Trade tracking ──────────────────────────────────────────────────────

@dataclass
class Trade:
    direction: str
    entry_idx: int
    entry_price: float
    sl_initial: float
    exit_idx: int = -1
    exit_price: float = 0.0
    exit_reason: str = "open"
    pnl_ticks: float = 0.0           # PnL 1 contrat (legacy)
    pnl_dollars: float = 0.0         # PnL 1 contrat (legacy)
    duration_bars: int = 0
    max_trail_sl: float = 0.0
    # Contexte enrichi entry (pour analyse wins vs losses)
    entry_ts: str = ""
    entry_hour_utc: int = -1
    entry_day_of_week: int = -1
    entry_atr_norm: float = 0.0
    entry_session: str = ""
    entry_n_color_up: int = 0
    entry_n_color_dn: int = 0
    entry_n_long_up: int = 0
    entry_n_long_dn: int = 0
    entry_inside_va: int = 0
    entry_aggressor: float = 0.0
    entry_trail_triggered: bool = False
    # Pyramide
    contracts_entry_prices: list = field(default_factory=list)
    n_contracts_max: int = 1
    pnl_pyramid_ticks: float = 0.0   # PnL avec pyramide (somme contrat × (exit-entry))
    pnl_pyramid_dollars: float = 0.0


# ─── Backtest core ───────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, sym: str = "NQ") -> tuple[list[Trade], dict]:
    """Run backtest BN V2 sur df. Retourne trades + stats."""
    eng = BNEngine(sym=sym)
    state = BNState()
    tick = TICK_SIZE[sym]
    # NQ micro tick value = $0.50
    tick_value_dollars = 0.50 if sym == "NQ" else 1.25

    trades: list[Trade] = []
    current_trade: Trade | None = None

    # Compteur rejets (pour debug bottleneck)
    rejection_counts: dict[str, int] = {}

    # Min bars requises
    min_bars = 60

    for i in range(min_bars, len(df)):
        df_window = df.iloc[:i + 1]
        last_bar = df_window.iloc[-1]
        last_close = float(last_bar["close"])

        # Update engine
        result = eng.update(df_window, state)

        # Trade ouvert : track trail / pyramide / exit
        if current_trade is not None:
            # Pyramide : capture chaque add_contract
            if result.action == "ADD_CONTRACT" and result.add_contract_price is not None:
                current_trade.contracts_entry_prices.append(result.add_contract_price)
                current_trade.n_contracts_max = max(current_trade.n_contracts_max, result.n_contracts)
                current_trade.entry_trail_triggered = True
                if result.new_trail_sl is not None:
                    current_trade.max_trail_sl = result.new_trail_sl
                continue

            if result.action == "TRAIL_SL" and result.new_trail_sl is not None:
                current_trade.max_trail_sl = result.new_trail_sl
                current_trade.entry_trail_triggered = True
                continue

            # Exit conditions
            if result.action in ("EXIT_SL_HIT", "INVALIDATE"):
                current_trade.exit_idx = i
                if result.action == "EXIT_SL_HIT":
                    current_trade.exit_price = state.trail_sl if state.trail_sl else current_trade.sl_initial
                    current_trade.exit_reason = "sl_hit"
                else:
                    current_trade.exit_price = last_close
                    current_trade.exit_reason = "golden_rule"

                # PnL 1 contrat (legacy)
                if current_trade.direction == "LONG":
                    current_trade.pnl_ticks = (current_trade.exit_price - current_trade.entry_price) / tick
                else:
                    current_trade.pnl_ticks = (current_trade.entry_price - current_trade.exit_price) / tick
                current_trade.pnl_dollars = current_trade.pnl_ticks * tick_value_dollars

                # PnL avec pyramide : somme sur tous les contrats
                all_entries = [current_trade.entry_price] + current_trade.contracts_entry_prices
                if current_trade.direction == "LONG":
                    pnl_pts = sum(current_trade.exit_price - ep for ep in all_entries)
                else:
                    pnl_pts = sum(ep - current_trade.exit_price for ep in all_entries)
                current_trade.pnl_pyramid_ticks = pnl_pts / tick
                current_trade.pnl_pyramid_dollars = current_trade.pnl_pyramid_ticks * tick_value_dollars

                current_trade.duration_bars = i - current_trade.entry_idx
                trades.append(current_trade)
                current_trade = None
                state = BNState()
                eng = BNEngine(sym=sym)
                continue

            continue  # trade en cours

        # Pas de trade : check entry
        if result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
            # Capture contexte entry
            ts = last_bar.get("ts_event")
            ts_str = str(ts) if ts is not None else ""
            hour = int(pd.Timestamp(ts).hour) if ts is not None else -1
            dow = int(pd.Timestamp(ts).dayofweek) if ts is not None else -1
            # Session (UTC)
            if hour < 0:
                session = "UNK"
            elif 0 <= hour < 7:
                session = "ASIA"
            elif 7 <= hour < 13:
                session = "LONDON"
            elif hour == 13:
                session = "RTH_OPEN"  # 13:30 UTC = 9:30 ET
            elif 14 <= hour < 19:
                session = "RTH_MID"
            elif 19 <= hour < 21:
                session = "RTH_CLOSE"
            else:
                session = "US_AH"
            # Volatility norm (range 5 dernieres bars / ATR)
            r5 = float(df_window.iloc[-5:]["high"].max() - df_window.iloc[-5:]["low"].min())
            atr_norm = r5 / 20.0  # 20 = ~ATR moyen NQ 1min en pts
            current_trade = Trade(
                direction="LONG" if result.signal == "LONG_ENTRY" else "SHORT",
                entry_idx=i,
                entry_price=last_close,
                sl_initial=result.sl,
                entry_ts=ts_str,
                entry_hour_utc=hour,
                entry_day_of_week=dow,
                entry_atr_norm=round(atr_norm, 3),
                entry_session=session,
                entry_n_color_up=int(last_bar.get("n_color_up_zones_active", 0) or 0),
                entry_n_color_dn=int(last_bar.get("n_color_dn_zones_active", 0) or 0),
                entry_n_long_up=int(last_bar.get("long_up_bar", 0) or 0),
                entry_n_long_dn=int(last_bar.get("long_dn_bar", 0) or 0),
                entry_inside_va=int(last_bar.get("inside_value_area", 0) or 0),
                entry_aggressor=float(last_bar.get("aggressor_imbalance", 0.0) or 0.0),
            )
        else:
            # Track rejection reason (debug bottleneck)
            reason = result.reason or "unknown"
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    # Fermeture trades ouverts en fin de backtest (mark to market)
    if current_trade is not None:
        last_close = float(df.iloc[-1]["close"])
        current_trade.exit_idx = len(df) - 1
        current_trade.exit_price = last_close
        current_trade.exit_reason = "eod"
        if current_trade.direction == "LONG":
            current_trade.pnl_ticks = (last_close - current_trade.entry_price) / tick
        else:
            current_trade.pnl_ticks = (current_trade.entry_price - last_close) / tick
        current_trade.pnl_dollars = current_trade.pnl_ticks * tick_value_dollars
        current_trade.duration_bars = current_trade.exit_idx - current_trade.entry_idx
        trades.append(current_trade)

    # Stats
    stats = compute_stats(trades, df, sym)
    # Top rejets pour debug
    sorted_rejections = sorted(rejection_counts.items(), key=lambda x: -x[1])[:10]
    stats["top_rejection_reasons"] = sorted_rejections
    return trades, stats


def compute_stats(trades: list[Trade], df: pd.DataFrame, sym: str) -> dict:
    """Compute backtest stats. Calcule 2 series : 1 contrat fixe ET pyramide."""
    if not trades:
        return {"n_trades": 0, "n_bars": len(df), "frequency_per_day": 0.0, "verdict": "NO_TRADES"}

    # Stats avec PYRAMIDE (Jackson "je recharge")
    pnls_pyr_ticks = np.array([t.pnl_pyramid_ticks for t in trades])
    pnls_pyr_dollars = np.array([t.pnl_pyramid_dollars for t in trades])

    # Stats 1 contrat (reference)
    pnls = np.array([t.pnl_ticks for t in trades])
    pnls_dollars = np.array([t.pnl_dollars for t in trades])

    n_total = len(trades)
    n_wins = int((pnls > 0).sum())
    n_losses = int((pnls < 0).sum())
    n_flat = int((pnls == 0).sum())

    wr = n_wins / n_total if n_total > 0 else 0.0
    sum_wins = float(pnls_dollars[pnls > 0].sum())
    sum_losses = float(abs(pnls_dollars[pnls < 0].sum()))
    pf = sum_wins / sum_losses if sum_losses > 0 else float('inf')
    ev_dollars = float(pnls_dollars.mean())
    ev_ticks = float(pnls.mean())

    # PYRAMIDE
    sum_wins_pyr = float(pnls_pyr_dollars[pnls_pyr_dollars > 0].sum())
    sum_losses_pyr = float(abs(pnls_pyr_dollars[pnls_pyr_dollars < 0].sum()))
    pf_pyr = sum_wins_pyr / sum_losses_pyr if sum_losses_pyr > 0 else float('inf')
    ev_pyr_dollars = float(pnls_pyr_dollars.mean())
    ev_pyr_ticks = float(pnls_pyr_ticks.mean())
    avg_n_contracts = float(np.mean([t.n_contracts_max for t in trades]))
    max_n_contracts = int(max(t.n_contracts_max for t in trades))

    # Max DD (cumulative pnl)
    cum_pnl = np.cumsum(pnls_dollars)
    peak = np.maximum.accumulate(cum_pnl)
    dd = peak - cum_pnl
    max_dd = float(dd.max()) if len(dd) > 0 else 0.0

    # Max consec losses
    max_consec = 0
    cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    # Frequence par jour
    n_bars = len(df)
    n_days = n_bars / (60 * 6.5) if n_bars > 0 else 1  # approx 6.5h RTH par jour
    frequency_per_day = n_total / max(n_days, 1)

    # Avg duration
    avg_duration = float(np.mean([t.duration_bars for t in trades]))

    # By exit reason
    n_sl_hit = sum(1 for t in trades if t.exit_reason == "sl_hit")
    n_golden = sum(1 for t in trades if t.exit_reason == "golden_rule")
    n_eod = sum(1 for t in trades if t.exit_reason == "eod")

    return {
        "n_trades": n_total,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "n_flat": n_flat,
        "win_rate": round(wr, 3),
        # 1 contrat (reference)
        "profit_factor_1c": round(pf, 2) if pf != float('inf') else float('inf'),
        "ev_ticks_1c": round(ev_ticks, 2),
        "total_pnl_dollars_1c": round(float(pnls_dollars.sum()), 2),
        # PYRAMIDE (Jackson)
        "profit_factor_pyramid": round(pf_pyr, 2) if pf_pyr != float('inf') else float('inf'),
        "ev_ticks_pyramid": round(ev_pyr_ticks, 2),
        "ev_dollars_pyramid": round(ev_pyr_dollars, 2),
        "total_pnl_dollars_pyramid": round(float(pnls_pyr_dollars.sum()), 2),
        "avg_n_contracts": round(avg_n_contracts, 2),
        "max_n_contracts": max_n_contracts,
        # Risk metrics (sur pyramide)
        "max_dd_dollars": round(max_dd, 2),
        "max_consec_losses": max_consec,
        "avg_duration_bars": round(avg_duration, 1),
        "frequency_per_day": round(frequency_per_day, 3),
        "n_bars_total": n_bars,
        "exit_reasons": {"sl_hit": n_sl_hit, "golden_rule": n_golden, "eod": n_eod},
    }


# ─── Data loading ────────────────────────────────────────────────────────

def load_data(symbol: str, max_bars: int | None) -> pd.DataFrame:
    import pyarrow.dataset as ds
    sym_mapping = {"NQ": "NQ.c.0", "ES": "ES.c.0"}
    path = Path(f"D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/v4_enriched/symbol={sym_mapping[symbol]}")
    dataset = ds.dataset(path, format="parquet")
    cols_needed = [
        "ts_event", "open", "high", "low", "close",
        "long_up_bar", "long_dn_bar",
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "_last_swing_high_price", "_last_swing_low_price",
    ]
    available = [c for c in cols_needed if c in dataset.schema.names]
    df = dataset.to_table(columns=available).to_pandas()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if max_bars and len(df) > max_bars:
        df = df.iloc[-max_bars:].reset_index(drop=True)
    return df


def main(symbol: str, max_bars: int | None = None) -> None:
    print(f"=== Backtest BN V2 — {symbol} ===")
    df = load_data(symbol, max_bars)
    print(f"Loaded {len(df):,} bars from {df['ts_event'].min()} to {df['ts_event'].max()}")

    t0 = time.time()
    trades, stats = backtest(df, sym=symbol)
    duration = time.time() - t0

    # Dump CSV pour analyse contextuelle
    if trades:
        trade_df = pd.DataFrame([t.__dict__ for t in trades])
        out_csv = Path(f"DATA/RESEARCH/bn_trades_{symbol}_{len(trades)}t.csv")
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        trade_df.to_csv(out_csv, index=False)
        print(f"\nTrades dumped to {out_csv}")

    print(f"\nBacktest ran in {duration:.1f}s")
    print("\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if trades:
        print("\n=== EXEMPLES TRADES (premiers 5) ===")
        for t in trades[:5]:
            print(f"  {t.direction} entry@{t.entry_price:.2f} exit@{t.exit_price:.2f} "
                  f"({t.exit_reason}) → {t.pnl_ticks:+.1f} ticks (${t.pnl_dollars:+.2f}) "
                  f"duration={t.duration_bars} bars")

        print("\n=== EXEMPLES TRADES (derniers 5) ===")
        for t in trades[-5:]:
            print(f"  {t.direction} entry@{t.entry_price:.2f} exit@{t.exit_price:.2f} "
                  f"({t.exit_reason}) → {t.pnl_ticks:+.1f} ticks (${t.pnl_dollars:+.2f}) "
                  f"duration={t.duration_bars} bars")

    # Verdict
    print("\n=== VERDICT ===")
    if stats["n_trades"] == 0:
        verdict = "NOGO — Aucun setup detecte sur la periode"
    elif stats["n_trades"] < 10:
        verdict = f"INSUFFICIENT — n={stats['n_trades']} trop bas pour conclure (Lopez n>=30)"
    else:
        # Verdict sur PF PYRAMIDE (logique Jackson)
        pf_pyr = stats["profit_factor_pyramid"]
        pf_1c = stats["profit_factor_1c"]
        wr = stats["win_rate"]
        avg_c = stats["avg_n_contracts"]
        if pf_pyr >= 2.0 and wr >= 0.30:
            verdict = f"GO Phase 1 OBSERVATION (PF_pyr={pf_pyr:.2f}, PF_1c={pf_1c:.2f}, avg {avg_c:.1f}c)"
        elif pf_pyr >= 1.5:
            verdict = f"GO RESERVE (PF_pyr={pf_pyr:.2f} marginal)"
        else:
            verdict = f"NOGO — PF_pyr={pf_pyr:.2f} insuffisant"
    print(f"  >>> {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--bars", type=int, default=30000)
    args = parser.parse_args()
    max_bars = args.bars if args.bars > 0 else None
    main(args.symbol, max_bars)
