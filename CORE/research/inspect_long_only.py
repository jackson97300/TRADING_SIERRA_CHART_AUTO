"""LONG-only analysis pour SL/Veto matrix."""
import json
import sys
sys.path.insert(0, r"C:/TRADING_SIERRA_CHART_AUTO/CORE/research")
from backtest_sl_l2_v3_v2 import load_trades, load_bars_for_date, compute_mae_mfe, simulate_exit, check_l2_veto, compute_stats, DATES, TICK, COSTS_TICKS, TARGET_R, HOLD_BARS

trades = load_trades()
bars_by_date = {d: load_bars_for_date(d) for d in DATES}
enriched = []
for tr in trades:
    bars = bars_by_date.get(tr["date"], [])
    if not bars:
        continue
    mae, mfe, mae_idx, mfe_idx, bar_n = compute_mae_mfe(tr, bars)
    tr["mae_ticks"] = mae
    tr["mfe_ticks"] = mfe
    enriched.append(tr)

# LONG-only
longs = [t for t in enriched if t["side"] == "LONG"]
shorts = [t for t in enriched if t["side"] == "SHORT"]
print("Subset LONG : " + str(len(longs)) + "   SHORT : " + str(len(shorts)))

print("")
print("## SUBSET LONG-only")
print("%-12s %-4s %-8s %-5s %-5s %-4s %-5s %-4s %-6s %-10s %-9s" % ("Config","SL","Veto","N","Filt","WIN","LOSS","TO","PF","PnL_g","PnL_NET"))
print("-"*85)
for sl in [25, 30, 35]:
    for veto in [None, 3.5, 5.0]:
        tp = sl * TARGET_R
        pnls = []
        n_win = n_loss = n_to = n_filt = 0
        for tr in longs:
            bars = bars_by_date.get(tr["date"], [])
            if veto is not None and check_l2_veto(tr, bars, veto):
                n_filt += 1
                continue
            pnl, reason = simulate_exit(tr["entry_price"], tr["side"], sl, tp, bars, tr["ts_open_ns"])
            if reason == "TP": n_win += 1
            elif reason == "SL": n_loss += 1
            else: n_to += 1
            pnls.append(pnl)
        net = [p - COSTS_TICKS for p in pnls]
        st = compute_stats(pnls)
        ns = compute_stats(net)
        veto_lab = "OFF" if veto is None else str(veto)
        cfg = "L_SL" + str(sl) + "_V" + veto_lab
        pf = ("%.2f" % st["pf"]) if st["pf"] != float("inf") else "inf"
        print("%-12s %-4d %-8s %-5d %-5d %-4d %-5d %-4d %-6s %-10.1f %-9.1f" % (cfg, sl, veto_lab, st["n"], n_filt, n_win, n_loss, n_to, pf, st["pnl"], ns["pnl"]))

print("")
print("## SUBSET SHORT-only (veto L2 OFF par definition, ne s'applique pas aux SHORTs)")
print("%-12s %-4s %-5s %-4s %-5s %-4s %-6s %-10s %-9s" % ("Config","SL","N","WIN","LOSS","TO","PF","PnL_g","PnL_NET"))
print("-"*70)
for sl in [25, 30, 35]:
    tp = sl * TARGET_R
    pnls = []
    n_win = n_loss = n_to = 0
    for tr in shorts:
        bars = bars_by_date.get(tr["date"], [])
        pnl, reason = simulate_exit(tr["entry_price"], tr["side"], sl, tp, bars, tr["ts_open_ns"])
        if reason == "TP": n_win += 1
        elif reason == "SL": n_loss += 1
        else: n_to += 1
        pnls.append(pnl)
    net = [p - COSTS_TICKS for p in pnls]
    st = compute_stats(pnls)
    ns = compute_stats(net)
    cfg = "S_SL" + str(sl)
    pf = ("%.2f" % st["pf"]) if st["pf"] != float("inf") else "inf"
    print("%-12s %-4d %-5d %-4d %-5d %-4d %-6s %-10.1f %-9.1f" % (cfg, sl, st["n"], n_win, n_loss, n_to, pf, st["pnl"], ns["pnl"]))
