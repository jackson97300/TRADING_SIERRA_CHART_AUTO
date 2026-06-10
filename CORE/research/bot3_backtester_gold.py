"""Bot 3 Backtester GOLD (MGC) — adapte tick=0.10 et 18 levels structurels.

ETAPE 1 du plan Gold (12/05/2026) : valider si edge Bot3-style existe sur Gold
AVANT d'investir dans full integration MIA (DMP C++, dataset, bots).

Source data : DATA/DATASETS/MGC_dataset_v5e_clean.parquet (12 mois, 336K bars).

Differences vs bot3_backtester.py (ES/NQ) :
- tick_size = 0.10 (vs 0.25)
- tick_value = $1 (MGC micro) (vs $0.50 NQ / $1.25 ES)
- 18 levels Gold-compatible (manquent les 6 MQ_* car pipeline MenthorQ Gold pas encore actif)
- Logique simplifiee : side fixe par level (LONG support / SHORT resistance / REJECTION rebond)
  Pas de scenarios neutres complexes (calibres ES/NQ uniquement dans bot3_decision_engine)
- ATR Gold ~17t per-bar (vs 36t NQ, 8t ES)

Anti-triche identique :
- Entry T close
- Slippage par session (RTH 1.5t / Asia 4t)
- News veto (rvol>3 OR range>2*atr_per_bar)
- SL pessimiste si TP+SL meme bar
- 1 position max
- Cost $0.74/RT commission

Usage :
    python -X utf8 CORE/research/bot3_backtester_gold.py [--run-id RUN]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# CONFIG ANTI-TRICHE (cohorte bot3_backtester ES/NQ)
# ============================================================================
TICK_SIZE = 0.10                # Gold tick = 0.10 (vs 0.25 ES/NQ)
TICK_VALUE = 1.0                # MGC micro $1/tick
N_CONTRACTS = 3
COMMISSION_PER_RT = 0.74

SLIPPAGE_RTH_ENTRY = 1.5
SLIPPAGE_RTH_SL = 1.5
SLIPPAGE_RTH_TRAIL = 2.0
SLIPPAGE_RTH_TP = 0.5
SLIPPAGE_ASIA_ENTRY = 4.0
SLIPPAGE_ASIA_SL = 3.0
SLIPPAGE_ASIA_TRAIL = 3.0
SLIPPAGE_ASIA_TP = 1.0

NEWS_RVOL_THRESHOLD = 3.0
NEWS_RANGE_ATR_MULT = 2.0


# ============================================================================
# LEVELS Gold-compatible (18 / 24 levels Bot3 ES/NQ)
# Format : (level_name, dist_col_pct, proximity_pct, side_rule)
# side_rule : 'LONG'=support, 'SHORT'=resistance, 'REJECTION'=rebond direction inverse
# ============================================================================
GOLD_LEVELS = [
    # Tier 1 equivalents (top edges potentiels)
    ("SINGLE_PRINT",   "dist_single_print_nearest_pct",        0.02, "REJECTION"),
    ("IB_LOW",         "dist_ib_low_pct",                       0.05, "LONG"),
    ("IB_HIGH",        "dist_ib_high_pct",                      0.05, "SHORT"),
    ("OPEN_830",       "dist_open_830_pct",                     0.05, "REJECTION"),
    ("OPEN_930",       "dist_open_930_pct",                     0.05, "REJECTION"),
    # Tier 2 equivalents
    ("CUR_VPOC",       "dist_cur_vpoc_pct",                     0.03, "REJECTION"),
    ("CUR_VAH",        "dist_cur_vah_pct",                      0.05, "SHORT"),
    ("CUR_VAL",        "dist_cur_val_pct",                      0.05, "LONG"),
    ("VWAP_W_SD1D",    "dist_vwap_w_sd1d_pct",                  0.05, "LONG"),
    ("VWAP_W_SD1U",    "dist_vwap_w_sd1u_pct",                  0.05, "SHORT"),
    ("PVAL",           "dist_prev_val_pct",                     0.05, "LONG"),
    ("PVAH",           "dist_prev_vah_pct",                     0.05, "SHORT"),
    ("SWING_HIGH",     "dist_last_swing_high_pct",              0.05, "SHORT"),
    ("SWING_LOW",      "dist_last_swing_low_pct",               0.05, "LONG"),
    # Tier 3 contextuels (n potentiellement faible)
    ("TRAPPED_SELL",   "dist_trapped_sellers_nearest_pct",      0.05, "LONG"),
    ("TRAPPED_BUY",    "dist_trapped_buyers_nearest_pct",       0.05, "SHORT"),
    ("CASH_HIGH",      "dist_cash_high_pct",                    0.05, "SHORT"),
    ("CASH_LOW",       "dist_cash_low_pct",                     0.05, "LONG"),
]


# ============================================================================
# GUARD RAILS GOLD (config Bot 3-style adaptee Gold ATR 17t)
# ============================================================================
GUARD_RAILS_GOLD = {
    "sl_ticks_base": 50,           # ~3x ATR_1min Gold (17t)
    "trailing_activation": 30,
    "trailing_distance": 20,
    "timeout_minutes": 30,
    "tp_cap_ticks": 100,           # R:R cible 2.0
}


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Trade:
    trade_id: str
    level_name: str
    side: str
    entry_bar_ts: str
    entry_price: float
    entry_price_with_slip: float
    sl_price: float
    tp_cap_price: float
    sl_ticks: int
    n_contracts: int
    exit_bar_ts: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    duration_bars: int = 0
    pnl_ticks_gross: float = 0.0
    pnl_ticks_net: float = 0.0
    pnl_dollars_net: float = 0.0
    mfe_ticks: float = 0.0
    mae_ticks: float = 0.0
    session_at_entry: str = ""
    rvol_at_entry: float = 0.0


# ============================================================================
# HELPERS
# ============================================================================

def _safe_int(v) -> int:
    if v is None:
        return 0
    try:
        f = float(v)
        if f != f:
            return 0
        return int(f)
    except (TypeError, ValueError):
        return 0


def _is_news_bar(bar: dict) -> bool:
    rvol = float(bar.get("rvol", 1.0) or 1.0)
    if rvol > NEWS_RVOL_THRESHOLD:
        return True
    high = float(bar.get("high", 0) or 0)
    low = float(bar.get("low", 0) or 0)
    atr_ticks = float(bar.get("atr", 17.0) or 17.0)
    atr_pts = atr_ticks * TICK_SIZE
    if atr_pts > 0 and (high - low) > NEWS_RANGE_ATR_MULT * atr_pts:
        return True
    for k in ("within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
              "within_news_845_5m", "within_news_900_5m", "within_news_930_5m"):
        if _safe_int(bar.get(k, 0)) == 1:
            return True
    return False


def _detect_session(bar: dict) -> str:
    if _safe_int(bar.get("is_in_us_cash", 0)) == 1:
        return "US_CASH"
    if _safe_int(bar.get("is_in_us_after", 0)) == 1:
        return "US_AFTER"
    if _safe_int(bar.get("is_in_london", 0)) == 1:
        return "LONDON"
    if _safe_int(bar.get("is_in_asia", 0)) == 1:
        return "ASIA"
    return "OTHER"


def _slippage_for_session(session: str, kind: str) -> float:
    is_rth = (session in ("US_CASH", "US_AFTER"))
    table = {
        "entry": (SLIPPAGE_RTH_ENTRY, SLIPPAGE_ASIA_ENTRY),
        "sl": (SLIPPAGE_RTH_SL, SLIPPAGE_ASIA_SL),
        "trail": (SLIPPAGE_RTH_TRAIL, SLIPPAGE_ASIA_TRAIL),
        "tp": (SLIPPAGE_RTH_TP, SLIPPAGE_ASIA_TP),
    }
    rth, asia = table.get(kind, (1.0, 1.0))
    return rth if is_rth else asia


# ============================================================================
# SIMULATION TRADE
# ============================================================================

def simulate_trade(df: pd.DataFrame, entry_idx: int, level_name: str, side: str,
                   session: str, cfg: dict) -> Optional[Trade]:
    timeout_min = cfg["timeout_minutes"]
    trail_act = cfg["trailing_activation"]
    trail_dist = cfg["trailing_distance"]
    tp_cap_ticks = cfg["tp_cap_ticks"]
    sl_ticks = cfg["sl_ticks_base"]

    if entry_idx >= len(df):
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    entry_bar_ts = str(entry_bar["ts_event"])

    slip_entry = _slippage_for_session(session, "entry")
    direction = 1 if side == "LONG" else -1
    entry_with_slip = entry_price + direction * slip_entry * TICK_SIZE
    sl_price = entry_with_slip - direction * sl_ticks * TICK_SIZE
    tp_cap_price = entry_with_slip + direction * tp_cap_ticks * TICK_SIZE

    rvol_at_entry = float(entry_bar.get("rvol", 1.0) or 1.0)

    trade = Trade(
        trade_id=f"GOLD_{entry_idx}_{level_name}_{side}",
        level_name=level_name, side=side,
        entry_bar_ts=entry_bar_ts,
        entry_price=entry_price,
        entry_price_with_slip=entry_with_slip,
        sl_price=sl_price, tp_cap_price=tp_cap_price,
        sl_ticks=sl_ticks, n_contracts=N_CONTRACTS,
        session_at_entry=session, rvol_at_entry=rvol_at_entry,
    )

    trailing_active = False
    best_price = entry_with_slip

    for j in range(1, timeout_min + 1):
        bar_idx = entry_idx + j
        if bar_idx >= len(df):
            break
        bar = df.iloc[bar_idx]
        h = float(bar["high"])
        l = float(bar["low"])

        sl_at_start = sl_price
        trailing_was_active = trailing_active

        cur_pnl_high = (h - entry_with_slip) / TICK_SIZE * direction
        cur_pnl_low = (l - entry_with_slip) / TICK_SIZE * direction
        trade.mfe_ticks = max(trade.mfe_ticks, max(cur_pnl_high, cur_pnl_low))
        trade.mae_ticks = min(trade.mae_ticks, min(cur_pnl_high, cur_pnl_low))

        sl_hit = (direction == 1 and l <= sl_at_start) or (direction == -1 and h >= sl_at_start)
        tp_hit = (direction == 1 and h >= tp_cap_price) or (direction == -1 and l <= tp_cap_price)

        if sl_hit and tp_hit:
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(session, slip_kind) * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "SL_AMBIGUOUS" if not trailing_was_active else "TRAIL_AMBIGUOUS"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_with_slip) / TICK_SIZE * direction
            return _finalize(trade)

        if sl_hit:
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(session, slip_kind) * TICK_SIZE
            exit_p = sl_at_start - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "TRAIL" if trailing_was_active else "SL"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_with_slip) / TICK_SIZE * direction
            return _finalize(trade)

        if tp_hit:
            slip_pts = _slippage_for_session(session, "tp") * TICK_SIZE
            exit_p = tp_cap_price - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "TP_CAP"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_with_slip) / TICK_SIZE * direction
            return _finalize(trade)

        if direction == 1 and h > best_price:
            best_price = h
        elif direction == -1 and l < best_price:
            best_price = l
        favorable = (best_price - entry_with_slip) / TICK_SIZE * direction
        if not trailing_active and favorable >= trail_act:
            trailing_active = True
        if trailing_active:
            new_sl = best_price - direction * trail_dist * TICK_SIZE
            if direction == 1 and new_sl > sl_price:
                sl_price = new_sl
            elif direction == -1 and new_sl < sl_price:
                sl_price = new_sl

    last_idx = min(entry_idx + timeout_min, len(df) - 1)
    last_bar = df.iloc[last_idx]
    final_price = float(last_bar["close"])
    slip_pts = _slippage_for_session(session, "trail") * TICK_SIZE * 0.5
    exit_p = final_price - direction * slip_pts
    trade.exit_bar_ts = str(last_bar["ts_event"])
    trade.exit_price = exit_p
    trade.exit_reason = "TIMEOUT"
    trade.duration_bars = last_idx - entry_idx
    trade.pnl_ticks_gross = (exit_p - entry_with_slip) / TICK_SIZE * direction
    return _finalize(trade)


def _finalize(trade: Trade) -> Trade:
    commission_total = COMMISSION_PER_RT * N_CONTRACTS
    pnl_d_gross = trade.pnl_ticks_gross * TICK_VALUE * N_CONTRACTS
    pnl_d_net = pnl_d_gross - commission_total
    trade.pnl_dollars_net = round(pnl_d_net, 2)
    trade.pnl_ticks_net = round(pnl_d_net / (TICK_VALUE * N_CONTRACTS), 2)
    return trade


# ============================================================================
# DETECT SIGNAL — touch + side rule simple
# ============================================================================

def detect_signal(bar: dict, level_def: tuple) -> Optional[str]:
    """Retourne 'LONG' / 'SHORT' / None.

    level_def : (level_name, dist_col_pct, proximity_pct, side_rule)
    """
    _, dist_col, proximity, side_rule = level_def
    dist_val = bar.get(dist_col)
    if dist_val is None:
        return None
    try:
        d = float(dist_val)
    except (TypeError, ValueError):
        return None
    if d != d:
        return None
    if abs(d) > proximity:
        return None
    # Touch detecte
    if side_rule in ("LONG", "SHORT"):
        return side_rule
    if side_rule == "REJECTION":
        # Rejet du level dans direction opposee au cote d'approche
        # Si dist > 0 (level au-dessus) -> approche par le bas -> rejection vers le bas (SHORT)
        # Si dist < 0 (level en-dessous) -> approche par le haut -> rejection vers le haut (LONG)
        return "SHORT" if d > 0 else "LONG"
    return None


# ============================================================================
# RUN BACKTEST
# ============================================================================

def run_backtest(df: pd.DataFrame, cfg: dict, out_dir: Path, run_id: str) -> dict:
    print(f"\n=== Backtest Gold MGC : {len(df):,} bars ===", flush=True)
    print(f"  Config : sl={cfg['sl_ticks_base']}t tp_cap={cfg['tp_cap_ticks']}t "
          f"timeout={cfg['timeout_minutes']}m trail_act={cfg['trailing_activation']}t",
          flush=True)
    print(f"  Niveaux : {len(GOLD_LEVELS)} (vs 24 Bot3 ES/NQ - manquent 6 MQ_*)",
          flush=True)

    n_trades = 0
    n_skipped_news = 0
    n_skipped_pos_active = 0
    n_skipped_no_signal = 0
    n_processed = 0

    open_until_idx = -1
    trades_out = []

    for idx in range(len(df)):
        if idx <= open_until_idx:
            n_skipped_pos_active += 1
            continue

        row = df.iloc[idx]
        bar = row.to_dict()
        bar["ts_event"] = str(bar["ts_event"])

        if _is_news_bar(bar):
            n_skipped_news += 1
            continue

        n_processed += 1

        # Iterate levels + detect signal
        candidates = []
        for level_def in GOLD_LEVELS:
            side = detect_signal(bar, level_def)
            if side is not None:
                candidates.append((level_def[0], side, abs(float(bar.get(level_def[1], 0)))))

        if not candidates:
            n_skipped_no_signal += 1
            continue

        # Tie-break : prendre le plus proche (abs dist asc)
        candidates.sort(key=lambda x: x[2])
        level_name, side, _ = candidates[0]
        session = _detect_session(bar)

        trade = simulate_trade(df, idx, level_name, side, session, cfg)
        if trade is None:
            continue

        n_trades += 1
        trades_out.append(asdict(trade))
        open_until_idx = idx + trade.duration_bars

        if n_trades % 100 == 0:
            print(f"  ... {n_trades} trades (idx {idx}/{len(df)} = {idx*100//len(df)}%)",
                  flush=True)

    # Save trades JSONL
    out_trades = out_dir / f"trades_gold_{run_id}.jsonl"
    with out_trades.open("w", encoding="utf-8") as f:
        for t in trades_out:
            f.write(json.dumps(t, default=str) + "\n")

    summary = {
        "n_bars": len(df),
        "n_processed": n_processed,
        "n_trades": n_trades,
        "n_skipped_news": n_skipped_news,
        "n_skipped_pos_active": n_skipped_pos_active,
        "n_skipped_no_signal": n_skipped_no_signal,
        "config": cfg,
    }
    print(f"\n  SUMMARY : {summary}", flush=True)
    return summary, trades_out


def analyze_results(trades: list, out_dir: Path, run_id: str):
    if not trades:
        print("  Aucun trade a analyser", flush=True)
        return

    df = pd.DataFrame(trades)

    # Stats globales
    print(f"\n=== Stats globales Gold ===", flush=True)
    print(f"  Total trades : {len(df)}", flush=True)
    pnl = df["pnl_dollars_net"]
    wins = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    pf = wins / losses if losses > 0 else float("inf")
    wr = (pnl > 0).sum() / len(pnl) * 100
    print(f"  PF net : {pf:.3f}", flush=True)
    print(f"  WR : {wr:.1f}%", flush=True)
    print(f"  EV/trade : ${pnl.mean():.2f}", flush=True)
    print(f"  Total PnL : ${pnl.sum():.2f}", flush=True)
    print(f"  Exit reasons : {dict(df['exit_reason'].value_counts())}", flush=True)

    # Stats per level
    print(f"\n=== Stats per level ===", flush=True)
    rows = []
    for lvl, sub in df.groupby("level_name"):
        n = len(sub)
        sub_pnl = sub["pnl_dollars_net"]
        sub_wins = sub_pnl[sub_pnl > 0].sum()
        sub_losses = abs(sub_pnl[sub_pnl < 0].sum())
        sub_pf = sub_wins / sub_losses if sub_losses > 0 else float("inf")
        sub_wr = (sub_pnl > 0).sum() / n * 100
        timeout_pct = (sub["exit_reason"] == "TIMEOUT").sum() / n * 100
        sl_pct = (sub["exit_reason"].isin(["SL", "SL_AMBIGUOUS"])).sum() / n * 100
        tp_pct = (sub["exit_reason"] == "TP_CAP").sum() / n * 100
        rows.append({
            "level": lvl, "n": n,
            "pf": round(sub_pf, 3) if sub_pf != float("inf") else 999.0,
            "wr": round(sub_wr, 1),
            "ev": round(sub_pnl.mean(), 2),
            "total_pnl": round(sub_pnl.sum(), 2),
            "timeout_pct": round(timeout_pct, 1),
            "sl_pct": round(sl_pct, 1),
            "tp_pct": round(tp_pct, 1),
        })
    stats_df = pd.DataFrame(rows).sort_values("pf", ascending=False)
    print(stats_df.to_string(index=False), flush=True)

    out_csv = out_dir / f"stats_per_level_gold_{run_id}.csv"
    stats_df.to_csv(out_csv, index=False)
    print(f"\n  Stats saved : {out_csv}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit-bars", type=int, default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "DATA" / "BACKTEST" / "GOLD"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}\n  BACKTEST GOLD - run_id={run_id}\n{'='*70}", flush=True)

    parquet_path = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_clean.parquet"
    if not parquet_path.exists():
        print(f"  ERREUR : parquet introuvable {parquet_path}", flush=True)
        return
    print(f"  Loading {parquet_path}...", flush=True)
    df = pd.read_parquet(parquet_path)
    if "ts_event" in df.columns:
        ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
        df["ts_event"] = ts.dt.tz_localize(None)
    df = df.sort_values("ts_event").reset_index(drop=True)
    if args.limit_bars:
        df = df.head(args.limit_bars).copy()
    print(f"  Total bars : {len(df):,} ({df['ts_event'].iloc[0]} -> {df['ts_event'].iloc[-1]})",
          flush=True)

    summary, trades = run_backtest(df, GUARD_RAILS_GOLD, out_dir, run_id)
    analyze_results(trades, out_dir, run_id)

    summary_path = out_dir / f"summary_gold_{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Summary final : {summary_path}", flush=True)


if __name__ == "__main__":
    main()
