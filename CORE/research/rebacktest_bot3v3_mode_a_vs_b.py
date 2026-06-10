"""
Rebacktest Bot 3 v3 Continuation - Mode A vs Mode B.

Mode A : code prod actuel (long_bar OR cluster, OR ligne 664 souvent inactif)
Mode B : simulation wrapper Sierra (cluster force a 0, long_bar requis)

Source data : DATA/datasets/v4_enriched (5 mois 2026-01 a 2026-05)
NE TOUCHE PAS au moteur prod (monkey-patch row au lieu).
"""
from __future__ import annotations
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from CORE.bot3_v3_continuation_engine import (
    Bot3V3Engine, Bot3V3Params, build_default_level_defs,
)

DATA_ROOT = Path("DATA/datasets/v4_enriched")
OUT_ROOT = Path("LOGS/rebacktest_bot3v3_mode_a_vs_b")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

TICK_NQ = 0.25
TICK_ES = 0.25
DOLLAR_PER_TICK_NQ = 0.50
DOLLAR_PER_TICK_ES = 1.25
SLIPPAGE_TICKS = 1
TIMEOUT_BARS = 120
TP_R_MULT = 1.5

MONTHS = [(2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]

CLUSTER_COLS_TO_ZERO = [
    "n_long_up_cluster_within_0_2pct",
    "n_long_dn_cluster_within_0_2pct",
]

def load_data(symbol_dir):
    paths = []
    for (y, m) in MONTHS:
        p = DATA_ROOT / ("symbol=" + symbol_dir) / ("year=" + str(y)) / ("month=" + ("%02d" % m)) / "data.parquet"
        if p.exists():
            paths.append(p)
    if not paths:
        raise FileNotFoundError("No data for " + symbol_dir)
    dfs = [pd.read_parquet(p) for p in paths]
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


def classify_session(ts_utc):
    h = ts_utc.hour
    m = ts_utc.minute
    hm = h * 60 + m
    if 13 * 60 + 30 <= hm < 21 * 60:
        return "RTH"
    if 7 * 60 <= hm < 13 * 60 + 30:
        return "London"
    if hm >= 22 * 60 or hm < 7 * 60:
        return "Asia"
    return "OVN"


def compute_sl_swing_based(side, entry_close, atr_15_pts, swing_price,
                           swing_buf_ticks, tick, sl_fallback_ticks,
                           sl_max_ticks, sl_min_ticks=5):
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


@dataclass
class TradeResult:
    mode: str
    symbol: str
    side: str
    level_name: str
    session: str
    regime_mode: str
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
    pnl_ticks_net: float
    pnl_R: float
    pnl_usd: float
    mae_ticks: float
    mfe_ticks: float
    bars_held: int


def simulate_trade(highs, lows, closes, entry_idx, side, entry_price,
                   sl_price, tp_price, sl_ticks, tick, n_bars,
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
                return j, "SL", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx
            if bar_high >= tp_price:
                exit_price = tp_price
                pnl_ticks = (exit_price - entry_price) / tick
                return j, "TP", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx
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
                return j, "SL", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx
            if bar_low <= tp_price:
                exit_price = tp_price
                pnl_ticks = (entry_price - exit_price) / tick
                return j, "TP", exit_price, pnl_ticks, mae_ticks, mfe_ticks, j - entry_idx
    exit_price = closes[end_idx]
    if side == "LONG":
        pnl_ticks = (exit_price - entry_price) / tick
    else:
        pnl_ticks = (entry_price - exit_price) / tick
    return end_idx, "TIMEOUT", exit_price, pnl_ticks, mae_ticks, mfe_ticks, end_idx - entry_idx


def run_engine_dual_mode(df, symbol, mode):
    assert mode in ("A", "B")
    tick = TICK_NQ if symbol == "NQ" else TICK_ES
    eng = Bot3V3Engine(symbol=symbol, level_defs=build_default_level_defs(),
                       params=Bot3V3Params())
    params = eng.params

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    ts_arr = df["ts_event"].astype(str).values
    ts_dt_arr = df["ts_event_dt"].values
    regime_arr = df["regime_mode"].fillna("UNKNOWN").values
    n_bars = len(df)

    entries = []
    t0 = time.time()
    for i in range(n_bars):
        row = df.iloc[i].to_dict()
        if mode == "B":
            for col in CLUSTER_COLS_TO_ZERO:
                if col in row:
                    row[col] = 0.0
        bar_ts_iso = str(row.get("ts_event"))
        bar_day = str(row.get("session_date"))
        decision = eng.process_bar(row, bar_ts_iso, bar_day)
        if decision is not None:
            entries.append((i, decision))
    elapsed = time.time() - t0
    print("  [" + symbol + " Mode " + mode + "] " + str(len(entries))
          + " entries detected in " + ("%.1f" % elapsed) + "s")

    results = []
    sl_fallback = (params.sl_fallback_ticks_nq if symbol == "NQ"
                   else params.sl_fallback_ticks_es)
    sl_max = (params.sl_max_ticks_nq if symbol == "NQ"
              else params.sl_max_ticks_es)
    swing_buf = params.sl_buffer_ticks

    for idx, dec in entries:
        # FIX 07/06 : utiliser SL/TP du moteur (respecte sl_tp_fixed_mode_nq + swing-based ES)
        # au lieu de recalculer. Aligne 100% avec setup prod 02/06/2026.
        sl_price = dec.sl_price
        tp_price = dec.tp_price
        sl_ticks = dec.sl_ticks
        if symbol == "NQ" and params.sl_tp_fixed_mode_nq:
            sl_mode = "moteur_fixed_nq"
        elif dec.swing_used:
            sl_mode = "moteur_swing"
        else:
            sl_mode = "moteur_fallback"

        exit_idx, cause, exit_price, pnl_ticks, mae, mfe, bars = simulate_trade(
            highs, lows, closes, idx, dec.side, dec.entry_close,
            sl_price, tp_price, sl_ticks, tick, n_bars,
        )

        pnl_ticks_net = pnl_ticks - SLIPPAGE_TICKS
        pnl_R = pnl_ticks_net / sl_ticks if sl_ticks > 0 else 0
        dol = DOLLAR_PER_TICK_NQ if symbol == "NQ" else DOLLAR_PER_TICK_ES
        pnl_usd = pnl_ticks_net * dol

        ts_dt = pd.Timestamp(ts_dt_arr[idx])
        session = classify_session(ts_dt)
        regime = str(regime_arr[idx])

        results.append(TradeResult(
            mode=mode, symbol=symbol, side=dec.side,
            level_name=dec.level_name, session=session, regime_mode=regime,
            entry_bar_idx=idx, entry_ts=ts_arr[idx],
            entry_price=dec.entry_close, sl_price=sl_price, tp_price=tp_price,
            sl_ticks=sl_ticks, sl_mode=sl_mode,
            exit_bar_idx=exit_idx, exit_ts=ts_arr[exit_idx],
            exit_price=exit_price, exit_cause=cause,
            pnl_ticks=pnl_ticks, pnl_ticks_net=pnl_ticks_net,
            pnl_R=pnl_R, pnl_usd=pnl_usd,
            mae_ticks=mae, mfe_ticks=mfe, bars_held=bars,
        ))
    return results


def compute_metrics(trades):
    if not trades:
        return {"n": 0, "WR": 0, "PF": 0, "EV_ticks": 0, "EV_usd": 0,
                "sum_pnl_usd": 0, "max_dd_usd": 0, "sharpe_like": 0}
    df = pd.DataFrame([asdict(t) for t in trades])
    df = df.sort_values("entry_bar_idx").reset_index(drop=True)
    wins = df[df["pnl_ticks_net"] > 0]
    losses = df[df["pnl_ticks_net"] <= 0]
    gross_win = wins["pnl_usd"].sum() if len(wins) > 0 else 0.0
    gross_loss = -losses["pnl_usd"].sum() if len(losses) > 0 else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999 if gross_win > 0 else 0)
    wr = len(wins) / len(df) if len(df) > 0 else 0
    ev_ticks = float(df["pnl_ticks_net"].mean())
    ev_usd = float(df["pnl_usd"].mean())
    sum_usd = float(df["pnl_usd"].sum())
    eq = df["pnl_usd"].cumsum().values
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = float(dd.max()) if len(dd) > 0 else 0.0
    std_usd = float(df["pnl_usd"].std()) if len(df) > 1 else 0
    sharpe_like = (ev_usd / std_usd) if std_usd > 0 else 0
    return {
        "n": int(len(df)),
        "WR": round(wr * 100, 2),
        "PF": round(pf, 3),
        "EV_ticks": round(ev_ticks, 3),
        "EV_usd": round(ev_usd, 3),
        "sum_pnl_usd": round(sum_usd, 2),
        "max_dd_usd": round(max_dd, 2),
        "sharpe_like": round(sharpe_like, 3),
        "avg_sl_ticks": round(float(df["sl_ticks"].mean()), 1),
        "avg_bars_held": round(float(df["bars_held"].mean()), 1),
        "avg_mae_ticks": round(float(df["mae_ticks"].mean()), 1),
        "avg_mfe_ticks": round(float(df["mfe_ticks"].mean()), 1),
        "exit_SL_pct": round(float((df["exit_cause"] == "SL").mean() * 100), 1),
        "exit_TP_pct": round(float((df["exit_cause"] == "TP").mean() * 100), 1),
        "exit_TIMEOUT_pct": round(float((df["exit_cause"] == "TIMEOUT").mean() * 100), 1),
    }


def stratify(trades, key):
    if not trades:
        return {}
    df = pd.DataFrame([asdict(t) for t in trades])
    out = {}
    for val, sub in df.groupby(key):
        idxs = sub.index.tolist()
        sub_trades = [trades[i] for i in idxs]
        out[str(val)] = compute_metrics(sub_trades)
    return out


def main():
    print("=" * 80)
    print("REBACKTEST Bot 3 v3 - Mode A vs Mode B")
    print("=" * 80)

    all_trades = {}
    summary = {}

    for symbol, symdir in [("NQ", "NQ.c.0"), ("ES", "ES.c.0")]:
        print("")
        print("=== Loading " + symbol + " (" + symdir + ") ===")
        df = load_data(symdir)
        n_days = df["session_date"].nunique()
        print("  Shape: " + str(df.shape) + ", days: " + str(n_days))
        print("  Period: " + str(df["ts_event"].min()) + " -> " + str(df["ts_event"].max()))
        atr_med = df["atr14_15min"].median()
        print("  ATR_15min median: " + ("%.2f" % atr_med) + " pts")

        cup = (df["n_long_up_cluster_within_0_2pct"].fillna(0) >= 1).mean()
        cdn = (df["n_long_dn_cluster_within_0_2pct"].fillna(0) >= 1).mean()
        lup = (df["long_up_bar"].fillna(0) == 1).mean()
        ldn = (df["long_dn_bar"].fillna(0) == 1).mean()
        print("  Prevalence cluster_up>=1: " + ("%.2f" % (cup * 100)) + "%, "
              + "cluster_dn>=1: " + ("%.2f" % (cdn * 100)) + "%")
        print("  Prevalence long_up_bar=1: " + ("%.2f" % (lup * 100)) + "%, "
              + "long_dn_bar=1: " + ("%.2f" % (ldn * 100)) + "%")

        for mode in ("A", "B"):
            print("")
            print("  --- Run " + symbol + " Mode " + mode + " ---")
            trades = run_engine_dual_mode(df, symbol, mode)
            key = symbol + "_" + mode
            all_trades[key] = trades
            global_m = compute_metrics(trades)
            per_session = stratify(trades, "session")
            per_regime = stratify(trades, "regime_mode")
            per_side = stratify(trades, "side")
            summary[key] = {
                "global": global_m,
                "by_session": per_session,
                "by_regime": per_regime,
                "by_side": per_side,
            }
            print("  -> n=" + str(global_m["n"]) + ", WR=" + str(global_m["WR"])
                  + "%, PF=" + str(global_m["PF"]) + ", EV_ticks=" + str(global_m["EV_ticks"])
                  + ", sum_USD=" + str(global_m["sum_pnl_usd"])
                  + ", MaxDD=" + str(global_m["max_dd_usd"]))

    print("")
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    verdict_table = []
    for symbol in ("NQ", "ES"):
        a = summary[symbol + "_A"]["global"]
        b = summary[symbol + "_B"]["global"]
        pf_a, pf_b = a["PF"], b["PF"]
        ev_a, ev_b = a["EV_ticks"], b["EV_ticks"]
        ratio_pf = pf_b / pf_a if pf_a > 0 else 0
        ratio_ev = ev_b / ev_a if ev_a != 0 else 0
        n_drop_pct = (1 - b["n"] / a["n"]) * 100 if a["n"] > 0 else 0
        go_pf = ratio_pf >= 0.9
        go_ev = ev_b >= ev_a * 0.85
        if go_pf and go_ev:
            verdict = "GO"
        elif ratio_pf >= 0.7:
            verdict = "RESERVES"
        else:
            verdict = "NOGO"
        if pf_b > pf_a and ev_b > ev_a:
            verdict += " (PF_B>PF_A : qualite confirmee)"
        verdict_table.append({
            "symbol": symbol,
            "n_A": a["n"], "n_B": b["n"], "n_drop_pct": round(n_drop_pct, 1),
            "PF_A": pf_a, "PF_B": pf_b, "ratio_PF": round(ratio_pf, 3),
            "EV_A": ev_a, "EV_B": ev_b, "ratio_EV": round(ratio_ev, 3),
            "WR_A": a["WR"], "WR_B": b["WR"],
            "sum_USD_A": a["sum_pnl_usd"], "sum_USD_B": b["sum_pnl_usd"],
            "verdict": verdict,
        })
        print("")
        print(symbol + ": n A->B " + str(a["n"]) + "->" + str(b["n"])
              + " (" + ("%.1f" % n_drop_pct) + "% drop) | PF "
              + str(pf_a) + "->" + str(pf_b) + " (ratio "
              + ("%.3f" % ratio_pf) + ") | EV_ticks "
              + str(ev_a) + "->" + str(ev_b)
              + " | Verdict: " + verdict)

    print("")
    print("=== Saving outputs ===")
    all_trade_rows = []
    for key, trades in all_trades.items():
        for t in trades:
            all_trade_rows.append(asdict(t))
    if all_trade_rows:
        df_all = pd.DataFrame(all_trade_rows)
        csv_path = OUT_ROOT / "trades_all.csv"
        df_all.to_csv(csv_path, index=False)
        print("  CSV trades: " + str(csv_path) + " (" + str(len(df_all)) + " rows)")

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
    json_path = OUT_ROOT / "summary.json"
    out_obj = {
        "verdicts": verdict_table,
        "summary": convert(summary),
        "config": {
            "months": [str(y) + "-" + ("%02d" % m) for (y, m) in MONTHS],
            "tp_R_mult": TP_R_MULT,
            "timeout_bars": TIMEOUT_BARS,
            "slippage_ticks": SLIPPAGE_TICKS,
            "cluster_cols_zeroed_in_B": CLUSTER_COLS_TO_ZERO,
        },
    }
    with open(json_path, "w") as f:
        json.dump(out_obj, f, indent=2, default=str)
    print("  Summary JSON: " + str(json_path))
    print("")
    print("DONE.")
    return summary, verdict_table


if __name__ == "__main__":
    main()
