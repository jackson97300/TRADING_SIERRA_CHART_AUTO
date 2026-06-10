# backtest_sl_hybrid.py - Backtest Plan C SL hybride
from __future__ import annotations
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from CORE.bot3_v3_continuation_engine import (
    Bot3V3Engine, Bot3V3Params, build_default_level_defs,
)
from CORE.bot3_v4_data_driven_engine import (
    Bot3V4Engine, Bot3V4Params, build_default_triggers,
)

DATA_ROOT = Path("DATA/datasets/v4_enriched")
OUT_ROOT = Path("LOGS/sl_research")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

TICK_NQ = 0.25
TICK_ES = 0.25
DOLLAR_PER_TICK_NQ = 0.50
DOLLAR_PER_TICK_ES = 1.25
TIMEOUT_BARS = 120
SL_CONFIGS = ["A_current", "B_plan_c", "C_variant"]


def load_data(symbol_dir):
    paths = [
        DATA_ROOT / ("symbol=" + symbol_dir) / "year=2026" / "month=04" / "data.parquet",
        DATA_ROOT / ("symbol=" + symbol_dir) / "year=2026" / "month=05" / "data.parquet",
    ]
    dfs = []
    for p in paths:
        if p.exists():
            dfs.append(pd.read_parquet(p))
    if not dfs:
        raise FileNotFoundError("No data for " + symbol_dir)
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["session_date"] = df["session_date"].astype(str)
    df["ts_event_dt"] = pd.to_datetime(df["ts_event"], utc=True)
    df_idx = df.set_index("ts_event_dt")
    df_15 = (df_idx[["open", "high", "low", "close"]].resample("15min")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    df_15["prev_close"] = df_15["close"].shift(1)

    def _tr(r):
        if pd.isna(r["prev_close"]):
            return r["high"] - r["low"]
        return max(r["high"] - r["low"],
                   abs(r["high"] - r["prev_close"]),
                   abs(r["low"] - r["prev_close"]))

    df_15["tr"] = df_15.apply(_tr, axis=1)
    df_15["atr14_15min"] = df_15["tr"].rolling(14).mean()
    df_15_reset = df_15[["atr14_15min"]].reset_index()
    df = pd.merge_asof(df.sort_values("ts_event_dt"),
                       df_15_reset.sort_values("ts_event_dt"),
                       on="ts_event_dt", direction="backward")
    df = df.dropna(subset=["atr14_15min"]).reset_index(drop=True)
    return df


def compute_sl_config(config, side, entry_close, atr_15_pts, swing_price,
                      swing_buf_ticks, tick, sl_fallback_ticks, sl_max_ticks,
                      sl_min_ticks=5):
    if config == "A_current":
        if side == "LONG":
            if swing_price is None or swing_price <= 0 or swing_price >= entry_close:
                sl_ticks = sl_fallback_ticks
                sl_price = entry_close - sl_ticks * tick
                mode = "fallback"
            else:
                sl_price = swing_price - swing_buf_ticks * tick
                sl_ticks = int(round((entry_close - sl_price) / tick))
                if sl_ticks > sl_max_ticks:
                    sl_ticks = sl_fallback_ticks
                    sl_price = entry_close - sl_ticks * tick
                    mode = "cap_max"
                else:
                    mode = "swing_based"
            if sl_ticks < sl_min_ticks:
                sl_ticks = sl_min_ticks
                sl_price = entry_close - sl_min_ticks * tick
                mode = "cap_min"
        else:
            if swing_price is None or swing_price <= 0 or swing_price <= entry_close:
                sl_ticks = sl_fallback_ticks
                sl_price = entry_close + sl_ticks * tick
                mode = "fallback"
            else:
                sl_price = swing_price + swing_buf_ticks * tick
                sl_ticks = int(round((sl_price - entry_close) / tick))
                if sl_ticks > sl_max_ticks:
                    sl_ticks = sl_fallback_ticks
                    sl_price = entry_close + sl_ticks * tick
                    mode = "cap_max"
                else:
                    mode = "swing_based"
            if sl_ticks < sl_min_ticks:
                sl_ticks = sl_min_ticks
                sl_price = entry_close + sl_min_ticks * tick
                mode = "cap_min"
        return sl_price, sl_ticks, mode

    if config == "B_plan_c":
        floor_mult = 0.4
        cap_mult = 1.5
    elif config == "C_variant":
        floor_mult = 0.5
        cap_mult = 2.0
    else:
        raise ValueError("Unknown config: " + config)

    atr_floor_ticks = (floor_mult * atr_15_pts) / tick
    atr_cap_ticks = (cap_mult * atr_15_pts) / tick

    swing_dist_ticks = None
    if swing_price is not None and swing_price > 0:
        if side == "LONG" and swing_price < entry_close:
            swing_dist_ticks = (entry_close - swing_price) / tick + swing_buf_ticks
        elif side == "SHORT" and swing_price > entry_close:
            swing_dist_ticks = (swing_price - entry_close) / tick + swing_buf_ticks

    if swing_dist_ticks is not None:
        sl_ticks_raw = max(swing_dist_ticks, atr_floor_ticks)
        mode_raw = "swing_or_atr_floor"
    else:
        sl_ticks_raw = atr_floor_ticks
        mode_raw = "atr_floor"

    if sl_ticks_raw > atr_cap_ticks:
        sl_ticks_raw = atr_cap_ticks
        mode_raw = "atr_cap"

    sl_ticks = max(int(round(sl_ticks_raw)), sl_min_ticks)
    if side == "LONG":
        sl_price = entry_close - sl_ticks * tick
    else:
        sl_price = entry_close + sl_ticks * tick

    return sl_price, sl_ticks, mode_raw


@dataclass
class TradeResult:
    bot: str
    config: str
    symbol: str
    side: str
    level_name: str
    entry_bar_idx: int
    entry_ts: str
    entry_price: float
    sl_price: float
    tp_price: float
    sl_ticks: int
    sl_mode: str
    exit_bar_idx: int
    exit_ts: str
    exit_price: float
    exit_cause: str
    pnl_ticks: float
    pnl_R: float
    pnl_usd: float
    mae_ticks: float
    mfe_ticks: float
    bars_held: int


def simulate_trade(highs, lows, closes, entry_idx, side, entry_price, sl_price,
                   tp_price, sl_ticks, tick, dollar_per_tick, n_bars,
                   timeout_bars=TIMEOUT_BARS):
    end_idx = min(entry_idx + timeout_bars, n_bars - 1)
    mae_ticks = 0.0
    mfe_ticks = 0.0
    for j in range(entry_idx + 1, end_idx + 1):
        bar_high = highs[j]
        bar_low = lows[j]
        if side == "LONG":
            dd_ticks = (entry_price - bar_low) / tick
            up_ticks = (bar_high - entry_price) / tick
            if dd_ticks > mae_ticks:
                mae_ticks = dd_ticks
            if up_ticks > mfe_ticks:
                mfe_ticks = up_ticks
            if bar_low <= sl_price:
                exit_price = sl_price
                pnl_ticks = (exit_price - entry_price) / tick
                return (j, "SL", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx)
            if bar_high >= tp_price:
                exit_price = tp_price
                pnl_ticks = (exit_price - entry_price) / tick
                return (j, "TP", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx)
        else:
            dd_ticks = (bar_high - entry_price) / tick
            up_ticks = (entry_price - bar_low) / tick
            if dd_ticks > mae_ticks:
                mae_ticks = dd_ticks
            if up_ticks > mfe_ticks:
                mfe_ticks = up_ticks
            if bar_high >= sl_price:
                exit_price = sl_price
                pnl_ticks = (entry_price - exit_price) / tick
                return (j, "SL", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx)
            if bar_low <= tp_price:
                exit_price = tp_price
                pnl_ticks = (entry_price - exit_price) / tick
                return (j, "TP", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx)

    exit_price = closes[end_idx]
    if side == "LONG":
        pnl_ticks = (exit_price - entry_price) / tick
    else:
        pnl_ticks = (entry_price - exit_price) / tick
    return (end_idx, "TIMEOUT", exit_price, pnl_ticks, mae_ticks, mfe_ticks, end_idx - entry_idx)


def _run_bot(engine, df, symbol, bot_label):
    tick = TICK_NQ if symbol == "NQ" else TICK_ES
    dol = DOLLAR_PER_TICK_NQ if symbol == "NQ" else DOLLAR_PER_TICK_ES
    params = engine.params

    entries = []
    n = len(df)
    for i in range(n):
        row = df.iloc[i].to_dict()
        bar_ts_iso = str(row.get("ts_event"))
        bar_day = str(row.get("session_date"))
        decision = engine.process_bar(row, bar_ts_iso, bar_day)
        if decision is not None:
            entries.append((i, decision))

    print("[" + bot_label + " " + symbol + "] " + str(len(entries)) + " entries detected")

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    ts_arr = df["ts_event"].astype(str).values

    results = []
    for idx, dec in entries:
        row = df.iloc[idx]
        atr_15 = row["atr14_15min"]
        if pd.isna(atr_15) or atr_15 <= 0:
            continue
        swing_col = "_last_swing_low_price" if dec.side == "LONG" else "_last_swing_high_price"
        swing_price = row.get(swing_col)
        swing_price = float(swing_price) if pd.notna(swing_price) else None
        swing_buf_ticks = params.sl_buffer_ticks
        sl_fallback = params.sl_fallback_ticks_nq if symbol == "NQ" else params.sl_fallback_ticks_es
        sl_max = params.sl_max_ticks_nq if symbol == "NQ" else params.sl_max_ticks_es

        for cfg in SL_CONFIGS:
            sl_price, sl_ticks, sl_mode = compute_sl_config(
                cfg, dec.side, dec.entry_close, atr_15, swing_price,
                swing_buf_ticks, tick, sl_fallback, sl_max)
            tp_R = 1.5
            if dec.side == "LONG":
                tp_price = dec.entry_close + tp_R * sl_ticks * tick
            else:
                tp_price = dec.entry_close - tp_R * sl_ticks * tick
            exit_idx, cause, exit_price, pnl_ticks, mae, mfe, bars = simulate_trade(
                highs, lows, closes, idx, dec.side, dec.entry_close, sl_price, tp_price,
                sl_ticks, tick, dol, n_bars=n)
            pnl_R = pnl_ticks / sl_ticks if sl_ticks > 0 else 0
            pnl_usd = pnl_ticks * dol
            results.append(TradeResult(
                bot=bot_label, config=cfg, symbol=symbol, side=dec.side,
                level_name=dec.level_name, entry_bar_idx=idx,
                entry_ts=ts_arr[idx],
                entry_price=dec.entry_close, sl_price=sl_price, tp_price=tp_price,
                sl_ticks=sl_ticks, sl_mode=sl_mode,
                exit_bar_idx=exit_idx, exit_ts=ts_arr[exit_idx],
                exit_price=exit_price, exit_cause=cause,
                pnl_ticks=pnl_ticks, pnl_R=pnl_R, pnl_usd=pnl_usd,
                mae_ticks=mae, mfe_ticks=mfe, bars_held=bars,
            ))
    return results


def compute_metrics(trades):
    if not trades:
        return {"n": 0}
    df = pd.DataFrame([asdict(t) for t in trades])
    wins = df[df["pnl_ticks"] > 0]
    losses = df[df["pnl_ticks"] <= 0]
    gross_win = wins["pnl_usd"].sum() if len(wins) > 0 else 0
    gross_loss = -losses["pnl_usd"].sum() if len(losses) > 0 else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    wr = len(wins) / len(df) if len(df) > 0 else 0
    return {
        "n": int(len(df)),
        "WR": round(wr * 100, 2),
        "PF": round(pf, 3) if pf != float("inf") else 999,
        "sum_pnl_R": round(float(df["pnl_R"].sum()), 2),
        "sum_pnl_usd": round(float(df["pnl_usd"].sum()), 2),
        "avg_pnl_R": round(float(df["pnl_R"].mean()), 3),
        "median_pnl_R": round(float(df["pnl_R"].median()), 3),
        "MAE_median_ticks": round(float(df["mae_ticks"].median()), 1),
        "MAE_p95_ticks": round(float(df["mae_ticks"].quantile(0.95)), 1),
        "MAE_max_ticks": round(float(df["mae_ticks"].max()), 1),
        "MFE_median_ticks": round(float(df["mfe_ticks"].median()), 1),
        "exit_SL_pct": round(float((df["exit_cause"] == "SL").mean() * 100), 1),
        "exit_TP_pct": round(float((df["exit_cause"] == "TP").mean() * 100), 1),
        "exit_TIMEOUT_pct": round(float((df["exit_cause"] == "TIMEOUT").mean() * 100), 1),
        "avg_sl_ticks": round(float(df["sl_ticks"].mean()), 1),
        "avg_bars_held": round(float(df["bars_held"].mean()), 1),
    }


def compute_walkforward_folds(trades, n_folds=3):
    if not trades:
        return []
    df = pd.DataFrame([asdict(t) for t in trades])
    df["entry_ts_dt"] = pd.to_datetime(df["entry_ts"], utc=True)
    df = df.sort_values("entry_ts_dt").reset_index(drop=True)
    folds = []
    n = len(df)
    if n < n_folds:
        return [{"fold": 1, "n": n, **compute_metrics(trades)}]
    fold_size = n // n_folds
    for k in range(n_folds):
        start = k * fold_size
        end = n if k == n_folds - 1 else (k + 1) * fold_size
        idxs = list(df.index[start:end])
        fold_trades = [trades[i] for i in idxs]
        m = compute_metrics(fold_trades)
        m["fold"] = k + 1
        m["start"] = str(df.iloc[start]["entry_ts_dt"])
        m["end"] = str(df.iloc[end - 1]["entry_ts_dt"])
        folds.append(m)
    return folds


def main():
    all_trades = []
    all_metrics = {}

    for symbol, symdir in [("NQ", "NQ.c.0"), ("ES", "ES.c.0")]:
        print("")
        print("=== Loading " + symbol + " (" + symdir + ") ===")
        df = load_data(symdir)
        print("Shape: " + str(df.shape) + ", days: " + str(df["session_date"].nunique()))
        print("Period: " + str(df["ts_event"].min()) + " -> " + str(df["ts_event"].max()))
        atr_med = df["atr14_15min"].median()
        print("ATR_15min median: " + str(round(atr_med, 2)) + " pts (" + str(round(atr_med/0.25, 1)) + " ticks)")

        eng1 = Bot3V3Engine(symbol=symbol, level_defs=build_default_level_defs(), params=Bot3V3Params())
        bot1_results = _run_bot(eng1, df, symbol, "BOT1")
        all_trades.extend(bot1_results)
        for cfg in SL_CONFIGS:
            sub = [t for t in bot1_results if t.config == cfg]
            metrics = compute_metrics(sub)
            metrics["folds"] = compute_walkforward_folds(sub, n_folds=3)
            all_metrics["BOT1_" + symbol + "_" + cfg] = metrics
            print("  BOT1 " + symbol + " " + cfg + ": n=" + str(metrics["n"]) + ", WR=" + str(metrics.get("WR", 0)) + "%, PF=" + str(metrics.get("PF", 0)) + ", USD=" + str(metrics.get("sum_pnl_usd", 0)) + ", MAE_p95=" + str(metrics.get("MAE_p95_ticks", 0)) + "t")

        eng2 = Bot3V4Engine(symbol=symbol, triggers=build_default_triggers(), params=Bot3V4Params())
        bot3v4_results = _run_bot(eng2, df, symbol, "BOT3V4")
        all_trades.extend(bot3v4_results)
        for cfg in SL_CONFIGS:
            sub = [t for t in bot3v4_results if t.config == cfg]
            metrics = compute_metrics(sub)
            metrics["folds"] = compute_walkforward_folds(sub, n_folds=3)
            all_metrics["BOT3V4_" + symbol + "_" + cfg] = metrics
            print("  BOT3V4 " + symbol + " " + cfg + ": n=" + str(metrics["n"]) + ", WR=" + str(metrics.get("WR", 0)) + "%, PF=" + str(metrics.get("PF", 0)) + ", USD=" + str(metrics.get("sum_pnl_usd", 0)) + ", MAE_p95=" + str(metrics.get("MAE_p95_ticks", 0)) + "t")

    csv_path = OUT_ROOT / "sl_research_trades.csv"
    if all_trades:
        df_out = pd.DataFrame([asdict(t) for t in all_trades])
        df_out.to_csv(csv_path, index=False)
        print("")
        print("CSV trades: " + str(csv_path) + " (" + str(len(all_trades)) + " rows)")

    metrics_path = OUT_ROOT / "sl_research_metrics.json"
    def convert(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, dict):
            return {k: convert(v) for k, v in o.items()}
        if isinstance(o, list):
            return [convert(x) for x in o]
        return o
    with open(metrics_path, "w") as f:
        json.dump(convert(all_metrics), f, indent=2, default=str)
    print("Metrics JSON: " + str(metrics_path))
    return all_metrics, all_trades


if __name__ == "__main__":
    main()
