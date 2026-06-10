"""Bot 3 Backtester — sur V4 enriched 14 mois (avril 2025 → mai 2026).

REGLE SOUVERAINE (Jackson 03/05) : PAS DE TRICHE.
Cf DOCS/BOT3_BACKTEST_METHODOLOGY.md "PAS DE TRICHE" section.

Anti-triche enforces :
- Entry T close (pas T+1, pas mid)
- Slippage par regime : RTH 1.5t, Asia 4t, news bar EXCLU
- News bars (rvol>3 OR range>2*ATR) → veto, pas trade
- SL pessimiste si TP+SL meme bar (assume SL fill)
- Costs : $0.74/RT commission + slippages reels
- Tie-breaking : 1 trade par bar (priorite Tier 1 > 2 > 3 > NEUTRAL)
- Pas de cherry-pick : config Bot 3 round 5 figee, hot-loadee
- Pas de lookahead : evalue bar @ T close avec features T (deja dans V4)

Usage :
    python -X utf8 CORE/research/bot3_backtester.py [--symbol NQ|ES] [--month YYYY-MM] [--all]

Output :
    DATA/BACKTEST/BOT3/trades_<run_id>.jsonl       (1 ligne par trade execute)
    DATA/BACKTEST/BOT3/skipped_<run_id>.jsonl      (1 ligne par trigger skip pour audit)
    DATA/BACKTEST/BOT3/summary_<run_id>.json       (stats globales)
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.bot3_mp_engine import Bot3Engine  # noqa: E402
from CORE.bot3_decision_engine import evaluate_decision  # noqa: E402
from CORE.bot3_level_definitions import get_active_levels  # noqa: E402
from CORE.bot3_context_analyzer import analyze_context  # noqa: E402
from CORE.bot3_config import (  # noqa: E402
    BOT3_ENABLE_TIER2,
    BOT3_ENABLE_TIER2_NEUTRAL,
    BOT3_ENABLE_TIER3,
    GUARD_RAILS_BOT3,
    ATR_BASELINE,
    ATR_MULTIPLIER_CLAMP,
)


# ════════════════════════════════════════════════════════════════════════
# CONFIG ANTI-TRICHE (Jackson 03/05)
# ════════════════════════════════════════════════════════════════════════
TICK_SIZE = 0.25
COMMISSION_PER_RT = 0.74      # AMP micros

# Slippage par regime (en ticks, par cote)
SLIPPAGE_RTH_ENTRY = 1.5
SLIPPAGE_RTH_SL = 1.5
SLIPPAGE_RTH_TRAIL = 2.0
SLIPPAGE_RTH_TP = 0.5

SLIPPAGE_ASIA_ENTRY = 4.0
SLIPPAGE_ASIA_SL = 3.0
SLIPPAGE_ASIA_TRAIL = 3.0
SLIPPAGE_ASIA_TP = 1.0

# News bar veto (anti fills mensongers)
NEWS_RVOL_THRESHOLD = 3.0
NEWS_RANGE_ATR_MULT = 2.0

# Priority tie-breaking : Tier 1 > Tier 2 > Tier 3 > NEUTRAL (tier 99 si avait existé)
TIER_PRIORITY = {1: 1, 2: 2, 3: 3, 99: 99}


# ════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """1 trade simulé. Sérialisé en JSONL."""
    trade_id: str
    symbol: str
    level_name: str
    level_tier: int
    side: str
    action: str                    # REJECTION / BREAKOUT / BREAKOUT_RETEST
    confidence: int
    entry_bar_ts: str
    entry_price: float
    entry_price_with_slip: float
    sl_price: float
    tp_cap_price: float
    sl_ticks: int
    atr_multiplier: float
    n_contracts: int
    # Resolution
    exit_bar_ts: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""           # SL / TP_CAP / TRAILING / TIMEOUT / NEWS_VETO
    duration_bars: int = 0
    pnl_ticks_gross: float = 0.0
    pnl_ticks_net: float = 0.0
    pnl_dollars_net: float = 0.0
    mfe_ticks: float = 0.0
    mae_ticks: float = 0.0
    # Regime & meta
    session_at_entry: str = ""
    rvol_at_entry: float = 0.0
    vix_at_entry: float = 0.0
    # Acceptance breakout_retest snapshot
    acceptance_score: float = 0.0
    n_bars_touch_to_retest: int = 0


def _is_news_bar(bar: dict, atr_baseline_pts: float = None) -> bool:
    """Veto news bar : rvol > 3 OR range > 2*ATR_per_bar OR within_news_*.

    FIX CRITIQUE #3 (review code-reviewer 03/05) : utilise atr_14 (per-bar V4)
    en ticks, pas atr_baseline_pct (daily). atr_baseline_pct * close = ATR daily,
    pas per-bar → seuil 2x = 5160 ticks → JAMAIS triggered. Bug silencieux.
    """
    rvol = float(bar.get("rvol", 1.0) or 1.0)
    if rvol > NEWS_RVOL_THRESHOLD:
        return True
    high = float(bar.get("high", 0) or 0)
    low = float(bar.get("low", 0) or 0)
    # ATR_14 dans V4 enriched est en ticks per-bar (pas pct daily)
    atr_14_ticks = float(bar.get("atr", 20.0) or 20.0)
    atr_per_bar_pts = atr_14_ticks * TICK_SIZE
    if atr_per_bar_pts > 0 and (high - low) > NEWS_RANGE_ATR_MULT * atr_per_bar_pts:
        return True
    # Veto explicite si feature within_news_*_5m=1 (NaN-safe)
    for k in ("within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
              "within_news_845_5m", "within_news_900_5m", "within_news_930_5m"):
        v = bar.get(k, 0)
        try:
            fv = float(v) if v is not None else 0.0
            if fv != fv:    # NaN
                continue
            if int(fv) == 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _slippage_for_session(session: str, kind: str) -> float:
    """Retourne slippage en ticks pour (session, kind)."""
    is_rth = (session in ("US_CASH", "US_AFTER"))
    if kind == "entry":
        return SLIPPAGE_RTH_ENTRY if is_rth else SLIPPAGE_ASIA_ENTRY
    if kind == "sl":
        return SLIPPAGE_RTH_SL if is_rth else SLIPPAGE_ASIA_SL
    if kind == "trail":
        return SLIPPAGE_RTH_TRAIL if is_rth else SLIPPAGE_ASIA_TRAIL
    if kind == "tp":
        return SLIPPAGE_RTH_TP if is_rth else SLIPPAGE_ASIA_TP
    return 1.0


def _detect_session(bar: dict) -> str:
    """Detecte session depuis features V4."""
    if int(bar.get("is_in_us_cash", 0) or 0) == 1:
        return "US_CASH"
    if int(bar.get("is_in_us_after", 0) or 0) == 1:
        return "US_AFTER"
    if int(bar.get("is_in_london", 0) or 0) == 1:
        return "LONDON"
    if int(bar.get("is_in_asia", 0) or 0) == 1:
        return "ASIA"
    return "OTHER"


def _select_top_priority_signal(signals_dict: dict) -> tuple:
    """Tie-breaking : sur 1 bar, garde 1 seul trade (priorite Tier 1>2>3>NEUTRAL).

    signals_dict : {level_name : (level_def, dist_signed, ctx, signal_or_None)}
    Returns (level_name, level_def, dist_signed, ctx) du gagnant ou None.
    """
    candidates = []
    for level_name, (level_def, dist_signed, ctx, sig) in signals_dict.items():
        if sig is None:
            continue
        tier = level_def.get("tier", 99)
        candidates.append((TIER_PRIORITY.get(tier, 99), level_name, level_def, dist_signed, ctx, sig))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])  # tier ascending
    _, level_name, level_def, dist_signed, ctx, sig = candidates[0]
    return level_name, level_def, dist_signed, ctx, sig


# ════════════════════════════════════════════════════════════════════════
# SIMULATION TRADE
# ════════════════════════════════════════════════════════════════════════

def simulate_trade(
    df: pd.DataFrame, entry_idx: int, sym: str,
    level_name: str, level_tier: int, side: str, action: str, confidence: int,
    sl_ticks: int, atr_multiplier: float, n_contracts: int,
    session_at_entry: str,
) -> Optional[Trade]:
    """Simule entry @ T close + SL/TP/trailing/timeout. Anti-triche enforces.

    Convention : entry_idx = idx de la barre du touch. Entry @ close de cette bar
    (pas T+1 — aligne sur Bot 3 reel envoi DTC instant).
    """
    cfg = GUARD_RAILS_BOT3[sym]
    timeout_min = cfg["timeout_minutes"]
    trail_act_ticks = cfg["trailing_activation"]
    trail_dist_ticks = cfg["trailing_distance"]
    tp_cap_ticks = cfg["tp_cap_ticks"]

    if entry_idx >= len(df):
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    entry_bar_ts = str(entry_bar["ts_event"])

    # Anti-triche : entry slippage par regime
    slip_entry = _slippage_for_session(session_at_entry, "entry")
    direction = 1 if side == "LONG" else -1
    entry_price_with_slip = entry_price + direction * slip_entry * TICK_SIZE
    sl_price = entry_price_with_slip - direction * sl_ticks * TICK_SIZE
    tp_cap_price = entry_price_with_slip + direction * tp_cap_ticks * TICK_SIZE

    rvol_at_entry = float(entry_bar.get("rvol", 1.0) or 1.0)
    vix_at_entry = float(entry_bar.get("vix_level", 0) or 0)

    trade = Trade(
        trade_id=f"{sym}_{entry_idx}_{level_name}_{side}",
        symbol=sym, level_name=level_name, level_tier=level_tier,
        side=side, action=action, confidence=confidence,
        entry_bar_ts=entry_bar_ts,
        entry_price=entry_price,
        entry_price_with_slip=entry_price_with_slip,
        sl_price=sl_price, tp_cap_price=tp_cap_price,
        sl_ticks=sl_ticks, atr_multiplier=atr_multiplier,
        n_contracts=n_contracts,
        session_at_entry=session_at_entry,
        rvol_at_entry=rvol_at_entry,
        vix_at_entry=vix_at_entry,
    )

    trailing_active = False
    best_price = entry_price_with_slip

    for j in range(1, timeout_min + 1):
        bar_idx = entry_idx + j
        if bar_idx >= len(df):
            break
        bar = df.iloc[bar_idx]
        h = float(bar["high"])
        l = float(bar["low"])

        # FIX CRITIQUE #1 + #2 (review code-reviewer 03/05) :
        # Snapshot SL au DEBUT de la bar AVANT update trailing.
        # Anti cherry-pick : check sl_hit contre sl_at_bar_start (pas SL releve)
        # + trail activation defere a T+1 (pas activable dans la bar du touch high).
        sl_at_bar_start = sl_price
        trailing_was_active = trailing_active

        # MFE/MAE tracking (avant updates)
        cur_pnl_high = (h - entry_price_with_slip) / TICK_SIZE * direction
        cur_pnl_low = (l - entry_price_with_slip) / TICK_SIZE * direction
        mfe = max(cur_pnl_high, cur_pnl_low)
        mae = min(cur_pnl_high, cur_pnl_low)
        trade.mfe_ticks = max(trade.mfe_ticks, mfe)
        trade.mae_ticks = min(trade.mae_ticks, mae)

        # Anti-triche : si TP et SL touches dans MEME bar → assume SL (pessimiste)
        # CHECK CONTRE sl_at_bar_start, pas SL releve dans cette meme bar.
        sl_hit = (direction == 1 and l <= sl_at_bar_start) or (direction == -1 and h >= sl_at_bar_start)
        tp_hit = (direction == 1 and h >= tp_cap_price) or (direction == -1 and l <= tp_cap_price)
        if sl_hit and tp_hit:
            # ANTI-TRICHE : SL fill au sl_at_bar_start, pas TP (pessimiste)
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(session_at_entry, slip_kind) * TICK_SIZE
            exit_p = sl_at_bar_start - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "SL_AMBIGUOUS_BAR" if not trailing_was_active else "TRAILING_AMBIGUOUS_BAR"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_price_with_slip) / TICK_SIZE * direction
            return _finalize(trade, n_contracts, sym)

        if sl_hit:
            slip_kind = "trail" if trailing_was_active else "sl"
            slip_pts = _slippage_for_session(session_at_entry, slip_kind) * TICK_SIZE
            # Slippage adverse : prix execute pire que SL au bar start
            exit_p = sl_at_bar_start - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "TRAILING" if trailing_was_active else "SL"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_price_with_slip) / TICK_SIZE * direction
            return _finalize(trade, n_contracts, sym)

        if tp_hit:
            slip_pts = _slippage_for_session(session_at_entry, "tp") * TICK_SIZE
            exit_p = tp_cap_price - direction * slip_pts
            trade.exit_bar_ts = str(bar["ts_event"])
            trade.exit_price = exit_p
            trade.exit_reason = "TP_CAP"
            trade.duration_bars = j
            trade.pnl_ticks_gross = (exit_p - entry_price_with_slip) / TICK_SIZE * direction
            return _finalize(trade, n_contracts, sym)

        # FIX CRITIQUE #1 : update best_price + trailing APRES les hit checks.
        # Le trail activation se DEFERE a la prochaine bar (T+1), pas activable
        # dans la bar de touch du high (path ambiguity intra-bar).
        if direction == 1 and h > best_price:
            best_price = h
        elif direction == -1 and l < best_price:
            best_price = l
        favorable_ticks = (best_price - entry_price_with_slip) / TICK_SIZE * direction
        if not trailing_active and favorable_ticks >= trail_act_ticks:
            trailing_active = True   # actif a partir de bar SUIVANTE (T+1)
        if trailing_active:
            new_sl = best_price - direction * trail_dist_ticks * TICK_SIZE
            if direction == 1 and new_sl > sl_price:
                sl_price = new_sl
            elif direction == -1 and new_sl < sl_price:
                sl_price = new_sl

    # Timeout : close au close de la derniere bar
    last_idx = min(entry_idx + timeout_min, len(df) - 1)
    last_bar = df.iloc[last_idx]
    final_price = float(last_bar["close"])
    slip_pts = _slippage_for_session(session_at_entry, "trail") * TICK_SIZE * 0.5
    exit_p = final_price - direction * slip_pts
    trade.exit_bar_ts = str(last_bar["ts_event"])
    trade.exit_price = exit_p
    trade.exit_reason = "TIMEOUT"
    trade.duration_bars = last_idx - entry_idx
    trade.pnl_ticks_gross = (exit_p - entry_price_with_slip) / TICK_SIZE * direction
    return _finalize(trade, n_contracts, sym)


def _finalize(trade: Trade, n_contracts: int, sym: str) -> Trade:
    cfg = GUARD_RAILS_BOT3[sym]
    tick_value = cfg["tick_value"]
    # Costs : commission par RT + slippage deja inclus dans pnl_ticks_gross
    commission_total_dollars = COMMISSION_PER_RT * n_contracts   # 1 RT = open + close
    pnl_dollars_gross = trade.pnl_ticks_gross * tick_value * n_contracts
    pnl_dollars_net = pnl_dollars_gross - commission_total_dollars
    trade.pnl_dollars_net = round(pnl_dollars_net, 2)
    trade.pnl_ticks_net = round(pnl_dollars_net / (tick_value * n_contracts), 2)
    return trade


# ════════════════════════════════════════════════════════════════════════
# RUN BACKTEST
# ════════════════════════════════════════════════════════════════════════

def run_backtest_symbol(symbol: str, df: pd.DataFrame,
                        out_trades_path: Path,
                        out_skipped_path: Path) -> dict:
    """Run backtest sur 1 symbole. df = parquet sorted by ts_event."""
    print(f"\n=== Backtest {symbol} : {len(df):,} bars ===", flush=True)

    bot3_engine = Bot3Engine()
    active_levels = get_active_levels(
        enable_tier2=BOT3_ENABLE_TIER2,
        enable_tier3=BOT3_ENABLE_TIER3,
        symbol=symbol,
        enable_tier2_neutral=BOT3_ENABLE_TIER2_NEUTRAL,
    )
    print(f"  Niveaux actifs : {len(active_levels)} ({list(active_levels.keys())[:6]}...)", flush=True)

    # ATR baseline en pts (pour news veto range > 2*ATR)
    atr_baseline_pct = ATR_BASELINE.get(symbol, 0.030)

    n_trades = 0
    n_skipped_news = 0
    n_skipped_position_active = 0
    n_skipped_no_signal = 0
    n_processed = 0

    open_trade_exit_idx: int = -1   # 1 position max simultanee

    trades_out = []
    skipped_out = []

    for idx in range(len(df)):
        row = df.iloc[idx]
        bar = row.to_dict()
        bar["ts_event"] = str(bar["ts_event"])

        # 1 position max : skip si trade en cours
        # FIX MAJEUR #4 (review code-reviewer 03/05) : tracker les niveaux
        # sacrifies pour quantifier biais selection (sinon stats per-level
        # sous-representent les niveaux a touch frequent).
        if idx <= open_trade_exit_idx:
            n_skipped_position_active += 1
            # Quick check niveaux qui auraient touche (sans evaluate decision_engine)
            for level_name, level_def in active_levels.items():
                dist_col = level_def.get("dist_col")
                dist_val = bar.get(dist_col)
                if dist_val is None: continue
                try:
                    dist_signed = float(dist_val)
                    if abs(dist_signed) <= level_def.get("proximity_pct", 0.05):
                        skipped_out.append({
                            "ts_event": str(bar.get("ts_event", "?")),
                            "symbol": symbol, "level_name": level_name,
                            "tier": level_def.get("tier", 99),
                            "reason": "position_active",
                        })
                except (TypeError, ValueError):
                    pass
            continue

        # Anti-triche : news bar → veto
        avg_close = float(bar.get("close", 0) or 0)
        atr_baseline_pts_val = atr_baseline_pct * avg_close
        if _is_news_bar(bar, atr_baseline_pts_val):
            n_skipped_news += 1
            continue

        n_processed += 1

        # Eval Bot 3 : on n'utilise PAS bot3_engine.evaluate (besoin acces direct ctx + dist)
        # On reproduit la logique pour avoir tous les niveaux candidats sur la bar.
        ctx = analyze_context(bar)

        # Iterate niveaux + collect candidates avec leur signal evaluation
        candidates: dict = {}
        for level_name, level_def in active_levels.items():
            dist_col = level_def.get("dist_col")
            dist_val = bar.get(dist_col)
            if dist_val is None:
                continue
            try:
                dist_signed = float(dist_val)
            except (TypeError, ValueError):
                continue
            if dist_signed != dist_signed:  # NaN
                continue
            if abs(dist_signed) > level_def.get("proximity_pct", 0.05):
                continue
            # Touch detected, check decision_engine
            trade_ok, reason, params = evaluate_decision(
                level_name=level_name, level_def=level_def,
                ctx=ctx, symbol=symbol, dist_signed=dist_signed,
            )
            if trade_ok:
                candidates[level_name] = (level_def, dist_signed, ctx, params)

        if not candidates:
            n_skipped_no_signal += 1
            continue

        # FIX MAJEUR #5 : tie-break explicite (Tier asc, confidence desc, dist asc).
        # Anti-bias ordre source code (insertion order Python 3.7+).
        sorted_cands = sorted(
            candidates.items(),
            key=lambda kv: (
                TIER_PRIORITY.get(kv[1][0].get("tier", 99), 99),
                -int(kv[1][3].get("confidence", 0)),
                abs(kv[1][1]),
            )
        )
        level_name, (level_def, dist_signed, ctx, params) = sorted_cands[0]

        side = params["side"]
        action = params.get("action", "REJECTION")
        confidence = int(params.get("confidence", 50))
        sl_ticks = int(params.get("sl_ticks", 400))
        atr_mult = float(params.get("atr_multiplier", 1.0))
        cfg = GUARD_RAILS_BOT3[symbol]
        n_contracts = cfg["n_contracts"]
        session_at_entry = ctx.get("session", "OTHER")

        # Simulate trade
        trade = simulate_trade(
            df=df, entry_idx=idx, sym=symbol,
            level_name=level_name, level_tier=level_def.get("tier", 99),
            side=side, action=action, confidence=confidence,
            sl_ticks=sl_ticks, atr_multiplier=atr_mult, n_contracts=n_contracts,
            session_at_entry=session_at_entry,
        )
        if trade is None:
            continue

        n_trades += 1
        trades_out.append(asdict(trade))
        open_trade_exit_idx = idx + trade.duration_bars

        if n_trades % 50 == 0:
            print(f"  ... {n_trades} trades, idx {idx}/{len(df)} ({idx*100//len(df)}%)",
                  flush=True)

    # Flush JSONL
    with out_trades_path.open("w", encoding="utf-8") as f:
        for t in trades_out:
            f.write(json.dumps(t, default=str) + "\n")
    with out_skipped_path.open("w", encoding="utf-8") as f:
        for s in skipped_out:
            f.write(json.dumps(s, default=str) + "\n")

    summary = {
        "symbol": symbol,
        "n_bars_total": len(df),
        "n_processed": n_processed,
        "n_trades": n_trades,
        "n_skipped_news": n_skipped_news,
        "n_skipped_position_active": n_skipped_position_active,
        "n_skipped_no_signal": n_skipped_no_signal,
        "n_active_levels": len(active_levels),
    }
    print(f"\n  SUMMARY {symbol} : {summary}", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["NQ", "ES", "ALL"], default="ALL")
    parser.add_argument("--month", default=None,
                        help="YYYY-MM (default: tous les mois 2025-04 → 2026-05)")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "DATA" / "BACKTEST" / "BOT3"
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["NQ", "ES"] if args.symbol == "ALL" else [args.symbol]

    all_summaries = {}
    for sym in symbols:
        print(f"\n{'='*70}\nBacktest {sym} - run_id={run_id}\n{'='*70}", flush=True)

        # Load all V4 enriched parquet for symbol
        sym_dir = ROOT / "DATA" / "DATASETS" / "v4_enriched" / f"symbol={sym}.c.0"
        if args.month:
            year, month = args.month.split("-")
            files = list(sym_dir.glob(f"year={year}/month={month}/data.parquet"))
        else:
            files = sorted(sym_dir.glob("year=*/month=*/data.parquet"))
        if not files:
            print(f"  ERREUR : aucun parquet trouve pour {sym}", flush=True)
            continue
        print(f"  Loading {len(files)} parquet files...", flush=True)
        dfs = []
        for f in files:
            df = pd.read_parquet(f)
            if "ts_event" in df.columns:
                ts = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
                df["ts_event"] = ts.dt.tz_localize(None)
            dfs.append(df)
        df = pd.concat(dfs, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
        print(f"  Total bars : {len(df):,} ({df['ts_event'].iloc[0]} → {df['ts_event'].iloc[-1]})",
              flush=True)

        out_trades = out_dir / f"trades_{sym}_{run_id}.jsonl"
        out_skipped = out_dir / f"skipped_{sym}_{run_id}.jsonl"
        summary = run_backtest_symbol(sym, df, out_trades, out_skipped)
        all_summaries[sym] = summary

    # Save global summary
    summary_path = out_dir / f"summary_{run_id}.json"
    summary_path.write_text(
        json.dumps({"run_id": run_id, "symbols": all_summaries}, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"\nSummary final : {summary_path}", flush=True)


if __name__ == "__main__":
    main()
