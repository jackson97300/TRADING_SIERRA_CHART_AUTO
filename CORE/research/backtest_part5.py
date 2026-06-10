    print("")
    print("## TRADE 14:36 NQ LONG @30706.5 DETAIL")
    target = None
    for tr in enriched:
        if tr["side"] == "LONG" and tr["entry_price"] and abs(tr["entry_price"] - 30706.5) < 0.5:
            ts_iso = tr["ts_open_iso"] or ""
            if "14:3" in ts_iso or "12:3" in ts_iso or "18:3" in ts_iso:
                target = tr
                break
    if target is None:
        for tr in enriched:
            if tr["date"] == "20260603" and tr["side"] == "LONG" and tr["entry_price"] and abs(tr["entry_price"] - 30706.5) < 3.0:
                target = tr
                break
    if target:
        print("Trade : " + target["signal_id"] + " " + str(target["ts_open_iso"]) + " " + target["side"] + " AT " + str(target["entry_price"]))
        print("  MAE : " + ("%.1f" % target["mae_ticks"]) + "t (bar idx " + str(target["mae_bar_idx"]) + ")")
        print("  MFE : " + ("%.1f" % target["mfe_ticks"]) + "t (bar idx " + str(target["mfe_bar_idx"]) + ")")
        print("  Outcome orig (log) : " + str(target["outcome"]) + " cause=" + str(target["exit_cause"]) + " pnl_R=" + str(target["pnl_R"]))
        for sl in [25, 30, 35]:
            tp = sl * TARGET_R
            bars = bars_by_date.get(target["date"], [])
            pnl, reason = simulate_exit(target["entry_price"], target["side"], sl, tp, bars, target["ts_open_ns"])
            print("  Simu SL=" + str(sl) + "t TP=" + ("%.1f" % tp) + "t -> " + reason + " pnl_g=" + ("%.1f" % pnl) + "t pnl_net=" + ("%.1f" % (pnl-COSTS_TICKS)) + "t")
    else:
        print("Trade non trouve. Candidates 03/06 LONG :")
        d3 = [t for t in enriched if t["date"] == "20260603" and t["side"] == "LONG"]
        for t in d3[:10]:
            print("  " + t["signal_id"] + " AT" + str(t["entry_price"]) + " ts=" + str(t["ts_open_iso"]) + " MAE=" + ("%.1f" % t["mae_ticks"]) + "t MFE=" + ("%.1f" % t["mfe_ticks"]) + "t")

    print("")
    print("## SWEET SPOT")
    best_net = max(matrix.items(), key=lambda kv: kv[1]["pnl_net"])
    best_gross = max(matrix.items(), key=lambda kv: kv[1]["pnl_gross"])
    print("Best NET PnL   : " + best_net[0] + " = " + ("%.1f" % best_net[1]["pnl_net"]) + "t (PF gross " + ("%.2f" % best_net[1]["pf_gross"]) + ", MaxDD " + ("%.1f" % best_net[1]["max_dd"]) + "t)")
    print("Best GROSS PnL : " + best_gross[0] + " = " + ("%.1f" % best_gross[1]["pnl_gross"]) + "t (PF " + ("%.2f" % best_gross[1]["pf_gross"]) + ")")
    valid = {k: v for k, v in matrix.items() if v["pf_gross"] >= 1.2 and v["n"] >= 30}
    if valid:
        best_constraint = max(valid.items(), key=lambda kv: kv[1]["pnl_net"])
        v = best_constraint[1]
        print("Best NET avec PF>=1.2 et N>=30 : " + best_constraint[0] + " = " + ("%.1f" % v["pnl_net"]) + "t (PF " + ("%.2f" % v["pf_gross"]) + ", MaxDD " + ("%.1f" % v["max_dd"]) + "t)")
    else:
        print("Aucune config ne respecte PF>=1.2 et N>=30")

    out_fp = r"D:/TRADING_SIERRA_CHART_AUTO/LOGS/backtest_sl_l2_v3_matrix.json"
    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump({"matrix": matrix, "n_enriched": len(enriched), "no_bars": no_bars_count}, f, indent=2)
    print("Matrix saved : " + out_fp)


if __name__ == "__main__":
    main()
