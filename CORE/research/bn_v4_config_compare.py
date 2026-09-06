# bn_v4_config_compare.py - Backtest comparatif C0/C1/C2/C3 BN V4 (detection moteur PROD)
from __future__ import annotations
import glob, math, sys
import numpy as np
import pandas as pd
sys.path.insert(0, ".")
from CORE.bn_v4_engine import (
    BNV4Params, check_setup, TICK_SIZE,
    SL_INITIAL_BUFFER_TICKS, SL_NEW_PIVOT_BUFFER_TICKS,
    PULLBACK_DETECT_BARS, TIMEOUT_BARS_DEFAULT,
)
COST_POINTS = 0.5

def load_v4(symbol):
    pat = "DATA/datasets/v4_enriched/symbol=" + symbol + ".c.0/year=*/month=*/data.parquet"
    files = sorted(glob.glob(pat))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    if df.index.name == "ts_event":
        df = df.reset_index()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    return df

def simulate_trade(df, setup, tick):
    entry_i = setup["bar_idx"]; direction = setup["direction"]; entry_price = setup["entry_price"]
    end_i = min(len(df), entry_i + 1 + TIMEOUT_BARS_DEFAULT)
    eb = df.iloc[entry_i]
    if direction == "long":
        sl = float(eb["low"]) - SL_INITIAL_BUFFER_TICKS * tick; risk = entry_price - sl
    else:
        sl = float(eb["high"]) + SL_INITIAL_BUFFER_TICKS * tick; risk = sl - entry_price
    if risk <= 0:
        return None
    if direction == "long":
        last_attack_high = float(eb["high"]); pullback_low = float(eb["low"])
    else:
        last_attack_low = float(eb["low"]); pullback_high = float(eb["high"])
    bars_since = 0; in_pb = False; n_piv = 0
    exit_i = None; exit_price = None; exit_cause = None
    for j in range(entry_i + 1, end_i):
        bj = df.iloc[j]; cj = float(bj["close"]); hj = float(bj["high"]); lj = float(bj["low"])
        if direction == "long":
            if lj <= sl:
                exit_i, exit_price = j, sl; exit_cause = "sl_pivot" if n_piv else "sl_initial"; break
            if hj > last_attack_high:
                last_attack_high = hj; bars_since = 0
                if in_pb and cj > last_attack_high - tick:
                    new_sl = pullback_low - SL_NEW_PIVOT_BUFFER_TICKS * tick
                    if new_sl > sl: sl = new_sl; n_piv += 1
                    in_pb = False; pullback_low = lj
            else:
                bars_since += 1
                if lj < pullback_low: pullback_low = lj
                if bars_since >= PULLBACK_DETECT_BARS and not in_pb:
                    in_pb = True; pullback_low = lj
        else:
            if hj >= sl:
                exit_i, exit_price = j, sl; exit_cause = "sl_pivot" if n_piv else "sl_initial"; break
            if lj < last_attack_low:
                last_attack_low = lj; bars_since = 0
                if in_pb and cj < last_attack_low + tick:
                    new_sl = pullback_high + SL_NEW_PIVOT_BUFFER_TICKS * tick
                    if new_sl < sl: sl = new_sl; n_piv += 1
                    in_pb = False; pullback_high = hj
            else:
                bars_since += 1
                if hj > pullback_high: pullback_high = hj
                if bars_since >= PULLBACK_DETECT_BARS and not in_pb:
                    in_pb = True; pullback_high = hj
    if exit_i is None:
        exit_i = end_i - 1; exit_price = float(df.iloc[exit_i]["close"]); exit_cause = "timeout"
    pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    pnl_pts_net = pnl_pts - COST_POINTS
    return dict(date=df.iloc[entry_i]["date"], bar_index=entry_i, exit_index=exit_i,
        dir=direction, risk=float(risk), pnl_pts_net=float(pnl_pts_net),
        pnl_ticks_net=float(pnl_pts_net / tick), exit_cause=exit_cause, grade=setup["grade"])

def run_config(df, symbol, params, directions):
    tick = TICK_SIZE.get(symbol, 0.25); trades = []
    start = max(params.trend_lookback, params.trend_long_lookback)
    for d in directions:
        active_until = -1
        for i in range(start, len(df) - 1):
            if i < active_until: continue
            setup = check_setup(df, i, params, d, symbol=symbol)
            if setup is None: continue
            tr = simulate_trade(df, setup, tick)
            if tr is None: continue
            trades.append(tr); active_until = tr["exit_index"] + 1
    return pd.DataFrame(trades)

def metrics(trades, n_days_total):
    if trades.empty: return dict(n=0)
    pnl = trades["pnl_ticks_net"].values
    gross_w = pnl[pnl > 0].sum(); gross_l = -pnl[pnl < 0].sum()
    pf = (gross_w / gross_l) if gross_l > 0 else float("inf")
    ev = pnl.mean()
    eq = np.cumsum(pnl); peak = np.maximum.accumulate(eq); max_dd = (peak - eq).max()
    n_days = trades["date"].nunique(); tpd = len(trades) / max(n_days_total, 1)
    sd = pnl.std(ddof=1); sharpe = (ev / sd * math.sqrt(252 * tpd)) if sd > 0 else float("nan")
    return dict(n=len(trades), n_days_active=n_days,
        pct_days_active=100 * n_days / max(n_days_total, 1), trades_per_day=tpd,
        pf=pf, wr=100 * (pnl > 0).mean(), ev_ticks=ev, max_dd_ticks=max_dd,
        sharpe=sharpe, gross_w=gross_w, gross_l=gross_l, by_dir=dict(trades["dir"].value_counts()))

def dsr(trades, n_configs_tried=4):
    if trades.empty or len(trades) < 20: return None
    from scipy import stats
    r = trades["pnl_ticks_net"].values; sd = r.std(ddof=1)
    if sd <= 0: return None
    sr = r.mean() / sd; sk = float(stats.skew(r)); ku = float(stats.kurtosis(r, fisher=False)); n = len(r)
    denom = math.sqrt(max(1 - sk * sr + (ku - 1) / 4.0 * sr * sr, 1e-9))
    z = sr * math.sqrt(n - 1) / denom
    return float(stats.norm.cdf(z))

def folds_pf(trades, n_folds=3):
    if trades.empty: return []
    days = sorted(trades["date"].unique())
    if len(days) < n_folds: return []
    out = []
    for ch in np.array_split(days, n_folds):
        sub = trades[trades["date"].isin(set(ch))]
        if sub.empty: out.append(None); continue
        pnl = sub["pnl_ticks_net"].values; gl = -pnl[pnl < 0].sum()
        pf = (pnl[pnl > 0].sum() / gl) if gl > 0 else float("inf")
        out.append((ch[0], ch[-1], len(sub), pf, pnl.sum()))
    return out

CONFIGS = {
    "C0_baseline_live": dict(direction_mode="long", require_open_window=True),
    "C1_both":          dict(direction_mode="both", require_open_window=True),
    "C2_rth_wide":      dict(direction_mode="long", require_open_window=False),
    "C3_both_rth":      dict(direction_mode="both", require_open_window=False),
}

def base_params(require_open_window):
    return BNV4Params(grade_min="A++", require_open_window=require_open_window,
        require_long_trend_aligned=True, slope_mean_60_veto_threshold=0.20)

def fmt_dsr(d): return ("%.3f" % d) if d is not None else "n<20 non-calc"
def fmt_pf(p): return "inf" if p == float("inf") else ("%.2f" % p)

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols", nargs="+", default=["NQ", "ES"])
    args = ap.parse_args()
    for sym in args.symbols:
        df = load_v4(sym); mask = df["total_vol"].notna()
        n_days_total = df.loc[mask, "date"].nunique() if mask.any() else df["date"].nunique()
        line = "=" * 70
        print("\n%s\n%s : %d bars, %dj total, %dj avec total_vol (data exploitable)\n%s" % (
            line, sym, len(df), df["date"].nunique(), n_days_total, line))
        all_trades = {}
        for name, cfg in CONFIGS.items():
            p = base_params(cfg["require_open_window"])
            directions = ["long", "short"] if cfg["direction_mode"] == "both" else ["long"]
            tr = run_config(df, sym, p, directions); all_trades[name] = tr
            m = metrics(tr, n_days_total); d = dsr(tr)
            print("\n--- %s ---" % name)
            if m["n"] == 0:
                print("  AUCUN TRADE"); continue
            print("  n=%d | %.2f tr/j | %dj actifs (%.0f%%) | dir=%s" % (
                m["n"], m["trades_per_day"], m["n_days_active"], m["pct_days_active"], m["by_dir"]))
            print("  PF=%s | WR=%.1f%% | EV=%+.2ft | Sharpe=%.2f | maxDD=%.0ft" % (
                fmt_pf(m["pf"]), m["wr"], m["ev_ticks"], m["sharpe"], m["max_dd_ticks"]))
            print("  grossW=%.0ft grossL=%.0ft | DSR=%s" % (m["gross_w"], m["gross_l"], fmt_dsr(d)))
            fp = folds_pf(tr, 3)
            if fp:
                parts = []
                for x in fp:
                    if x is None: parts.append("vide"); continue
                    parts.append("%s-%s:n%d PF%s (%+.0ft)" % (x[0], x[1], x[2], fmt_pf(x[3]), x[4]))
                print("  folds: " + " | ".join(parts))
        c0 = all_trades["C0_baseline_live"]; c3 = all_trades["C3_both_rth"]
        if c0.empty:
            print("\n  [PRESERVATION %s] C0 vide -> aucun trade baseline" % sym); continue
        c0_keys = set(zip(c0["date"], c0["dir"], c0["bar_index"]))
        c3_keys = set(zip(c3["date"], c3["dir"], c3["bar_index"])) if not c3.empty else set()
        kept = c0_keys & c3_keys; pct = 100 * len(kept) / max(len(c0_keys), 1)
        print("\n  [PRESERVATION %s] trades C0=%d -> presents dans C3=%d (%.0f%%)" % (
            sym, len(c0_keys), len(kept), pct))
        c3_pnl = c3["pnl_ticks_net"].sum() if not c3.empty else 0.0
        print("  C0 PnL=%+.0ft | C3 PnL=%+.0ft" % (c0["pnl_ticks_net"].sum(), c3_pnl))

if __name__ == "__main__":
    main()
