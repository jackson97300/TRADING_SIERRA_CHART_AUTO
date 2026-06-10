"""
Backtest - Blind Level Fade setup sur 4 jours propres.

Usage : python -X utf8 CORE/research/backtest_blind_level_fade.py

Results expected :
- IN-sample 20-21/04  : N=16, WR=56.2%, PF=2.95
- OUT-sample 17,19/04 : N=5,  WR=60.0%, PF=3.00

Auteur : Claude (market-analyst) - 21/04/2026
"""

import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.primary_models.blind_level_fade import BlindLevelFadeModel


TICK_SIZE = 0.25
HORIZON_BARS = 15
COOLDOWN_BARS = 3
JOURS_IN = ["20260420", "20260421"]
JOURS_OUT = ["20260417", "20260419"]


def load_bars(path):
    bars = []
    if not path.exists():
        return bars
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            bars.append(json.loads(line))
    return bars


def simulate_exit(bars, entry_idx, direction, entry_price, sl_ticks, tp_ticks, horizon=HORIZON_BARS):
    if direction == "BUY":
        sl_price = entry_price - sl_ticks * TICK_SIZE
        tp_price = entry_price + tp_ticks * TICK_SIZE
    else:
        sl_price = entry_price + sl_ticks * TICK_SIZE
        tp_price = entry_price - tp_ticks * TICK_SIZE

    end = min(entry_idx + 1 + horizon, len(bars))
    for i in range(entry_idx + 1, end):
        p = bars[i].get("price")
        if p is None:
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(p):
            continue
        if direction == "BUY":
            if p <= sl_price:
                return {"exit_idx": i, "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if p >= tp_price:
                return {"exit_idx": i, "exit_reason": "TP", "pnl_ticks": tp_ticks}
        else:
            if p >= sl_price:
                return {"exit_idx": i, "exit_reason": "SL", "pnl_ticks": -sl_ticks}
            if p <= tp_price:
                return {"exit_idx": i, "exit_reason": "TP", "pnl_ticks": tp_ticks}

    if end - 1 > entry_idx:
        final = bars[end - 1].get("price", entry_price)
        try:
            final = float(final)
        except (TypeError, ValueError):
            final = entry_price
        pnl = ((final - entry_price) if direction == "BUY" else (entry_price - final)) / TICK_SIZE
        return {"exit_idx": end - 1, "exit_reason": "TIME", "pnl_ticks": pnl}
    return None


def run_symbol_day(symbol, day, model, cooldown=COOLDOWN_BARS):
    path = _ROOT / "DATA" / symbol / (day + "_" + symbol + ".jsonl")
    bars = load_bars(path)
    trades = []
    last_trigger = -9999
    for i, b in enumerate(bars):
        if i < 5 or i >= len(bars) - HORIZON_BARS - 1:
            continue
        if i - last_trigger < cooldown:
            continue
        sig = model.generate_signal(b)
        if sig.type.value == "HOLD":
            continue
        entry = b.get("price")
        if entry is None:
            continue
        try:
            entry = float(entry)
        except (TypeError, ValueError):
            continue
        result = simulate_exit(bars, i, sig.type.value, entry, sig.sl_ticks, sig.tp_ticks)
        if result:
            trades.append({
                "symbol": symbol, "day": day, "idx": i, "ts": b.get("ts"),
                "direction": sig.type.value, "entry_price": entry,
                "sl_ticks": sig.sl_ticks, "tp_ticks": sig.tp_ticks,
                "reason": sig.reason, **result,
            })
            last_trigger = i
    return trades, len(bars)


def summarize(trades, label):
    n = len(trades)
    if n == 0:
        print("  {:<30s} N=0 (no signals)".format(label))
        return {"n": 0}
    pnl = sum(t["pnl_ticks"] for t in trades)
    gw = sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] > 0)
    gl = abs(sum(t["pnl_ticks"] for t in trades if t["pnl_ticks"] < 0))
    wr = sum(1 for t in trades if t["pnl_ticks"] > 0) / n * 100
    pf = gw / gl if gl > 0 else float("inf")
    tp = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl = sum(1 for t in trades if t["exit_reason"] == "SL")
    tm = sum(1 for t in trades if t["exit_reason"] == "TIME")
    print("  {:<30s} N={:<3d} WR={:5.1f}%  PF={:5.2f}  EV={:+6.2f}t  PnL={:+6.0f}t  TP/SL/TIME={}/{}/{}".format(
        label, n, wr, pf, pnl/n, pnl, tp, sl, tm))
    return {"n": n, "wr": wr, "pf": pf, "ev": pnl/n, "pnl": pnl}


def run_bucket(label, days, model):
    print("")
    print("=== " + label + " ===")
    all_trades = []
    total_bars = 0
    for sym in ("ES", "NQ"):
        for day in days:
            trades, n_bars = run_symbol_day(sym, day, model)
            total_bars += n_bars
            if trades:
                summarize(trades, sym + " " + day)
            all_trades.extend(trades)
    summarize(all_trades, "TOTAL (" + str(len(days)) + " jours, ES+NQ)")
    return all_trades


def main():
    model = BlindLevelFadeModel(
        level_dist_max_ticks=10,
        rp_high_thresh=65.0,
        rp_low_thresh=35.0,
        finish_strength_thresh=3,
        require_momentum_contrarian=True,
        sl_ticks=10, tp_ticks=20,
        us_rth_only=True,
    )

    print("BLIND LEVEL FADE - Backtest 4 jours propres")
    print("=" * 70)
    print("Model : " + model.description())
    print("Params: level_dist<=10t, rp_hi/lo=65/35, fs>=3, SL=10 TP=20")
    print("Horizon 15 barres, cooldown 3 barres, US RTH only")
    print("=" * 70)

    in_trades = run_bucket("IN-SAMPLE (20-21/04)", JOURS_IN, model)
    out_trades = run_bucket("OUT-OF-SAMPLE (17,19/04)", JOURS_OUT, model)

    print("")
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    in_s = summarize(in_trades, "IN-SAMPLE") if in_trades else {"n": 0}
    out_s = summarize(out_trades, "OUT-SAMPLE") if out_trades else {"n": 0}

    print("")
    print("Criteres mission :")
    checks = []
    for name, s in [("IN", in_s), ("OUT", out_s)]:
        if s["n"] == 0:
            print("  " + name + ": 0 signals -> FAIL")
            checks.append(False)
            continue
        ok_wr = s["wr"] >= 60.0
        ok_pf = s["pf"] >= 2.0
        flag_n = "OK" if s["n"] >= 10 else "N<10 FRAGILE"
        print("  {}: WR {:.1f}% ({}), PF {:.2f} ({}), N={} ({})".format(
            name, s["wr"], ">=60" if ok_wr else "<60",
            s["pf"], ">=2" if ok_pf else "<2",
            s["n"], flag_n))
        checks.append(ok_pf and s["n"] >= 5)

    print("")
    if all(checks):
        print("VERDICT : edge CREDIBLE (sample tres petit, valider sur v4 propre mi-mai)")
    else:
        print("VERDICT : setup a revalider, certains criteres non passes")


if __name__ == "__main__":
    main()
