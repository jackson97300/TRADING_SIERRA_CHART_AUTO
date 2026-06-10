def main():
    print("=" * 80)
    print("BACKTEST SL 25/30/35t x VETO L2 OFF/3.5/5.0 sur Bot 3 V3 NQ trades")
    print("=" * 80)

    trades = load_trades()
    print("Total trades parses (open+close matches) : " + str(len(trades)))

    bars_by_date = {}
    for d in DATES:
        bars_by_date[d] = load_bars_for_date(d)
        print("  Bars " + d + " : " + str(len(bars_by_date[d])))

    enriched = []
    no_bars_count = 0
    for tr in trades:
        bars = bars_by_date.get(tr["date"], [])
        if not bars:
            no_bars_count += 1
            continue
        mae, mfe, mae_idx, mfe_idx, bar_n = compute_mae_mfe(tr, bars)
        tr["mae_ticks"] = mae
        tr["mfe_ticks"] = mfe
        tr["mae_bar_idx"] = mae_idx
        tr["mfe_bar_idx"] = mfe_idx
        tr["bars_held"] = bar_n
        enriched.append(tr)
    print("Trades with MAE/MFE : " + str(len(enriched)) + " (no_bars: " + str(no_bars_count) + ")")

    long_maes = [t["mae_ticks"] for t in enriched if t["side"] == "LONG"]
    short_maes = [t["mae_ticks"] for t in enriched if t["side"] == "SHORT"]

    def median(lst):
        if not lst:
            return 0
        s = sorted(lst)
        n = len(s)
        return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    print("")
    print("## DISTRIBUTION MAE")
    print("Median MAE LONG  (" + str(len(long_maes)) + ") : " + ("%.1f" % median(long_maes)) + "t")
    print("Median MAE SHORT (" + str(len(short_maes)) + ") : " + ("%.1f" % median(short_maes)) + "t")
    all_maes = [t["mae_ticks"] for t in enriched]
    if all_maes:
        pct_25 = sum(1 for m in all_maes if m >= 25) / len(all_maes) * 100
        pct_30 = sum(1 for m in all_maes if m >= 30) / len(all_maes) * 100
        pct_35 = sum(1 for m in all_maes if m >= 35) / len(all_maes) * 100
        pct_b_25_30 = sum(1 for m in all_maes if 25 <= m < 30) / len(all_maes) * 100
        pct_b_25_35 = sum(1 for m in all_maes if 25 <= m < 35) / len(all_maes) * 100
        print("PCT MAE GE 25t : " + ("%.1f" % pct_25) + "PCT")
        print("PCT MAE GE 30t : " + ("%.1f" % pct_30) + "PCT")
        print("PCT MAE GE 35t : " + ("%.1f" % pct_35) + "PCT")
        print("PCT 25 LE MAE LT 30 : " + ("%.1f" % pct_b_25_30) + "PCT (sauves par SL30 vs SL25)")
        print("PCT 25 LE MAE LT 35 : " + ("%.1f" % pct_b_25_35) + "PCT (sauves par SL35 vs SL25)")

    configs = []
    for sl in [25, 30, 35]:
        for veto in [None, 3.5, 5.0]:
            configs.append((sl, veto))

    print("")
    print("## MATRICE RESULTATS")
    header = "%-12s %-4s %-8s %-5s %-5s %-4s %-5s %-4s %-6s %-10s %-9s %-7s" % (
        "Config", "SL", "VetoL2", "N", "Filt", "WIN", "LOSS", "TO", "PF", "PnL_g", "PnL_NET", "MaxDD"
    )
    print(header)
    print("-" * 95)
    matrix = {}
    for sl, veto in configs:
        tp = sl * TARGET_R
        pnls = []
        n_win = n_loss = n_to = n_filtered = 0
        for tr in enriched:
            bars = bars_by_date.get(tr["date"], [])
            if veto is not None and check_l2_veto(tr, bars, veto):
                n_filtered += 1
                continue
            pnl_gross, reason = simulate_exit(
                tr["entry_price"], tr["side"], sl, tp, bars, tr["ts_open_ns"]
            )
            if reason == "TP":
                n_win += 1
            elif reason == "SL":
                n_loss += 1
            else:
                n_to += 1
            pnls.append(pnl_gross)
        net_pnls = [p - COSTS_TICKS for p in pnls]
        stats = compute_stats(pnls)
        net_stats = compute_stats(net_pnls)
        veto_lab = "OFF" if veto is None else str(veto)
        cfg_name = "SL" + str(sl) + "_V" + veto_lab
        matrix[cfg_name] = {
            "sl": sl, "veto": veto, "n": stats["n"], "n_filtered": n_filtered,
            "wins": n_win, "losses": n_loss, "timeouts": n_to,
            "pf_gross": stats["pf"], "pnl_gross": stats["pnl"],
            "pnl_net": net_stats["pnl"], "max_dd": stats["max_dd"]
        }
        pf_str = ("%.2f" % stats["pf"]) if stats["pf"] != float("inf") else "inf"
        row = "%-12s %-4d %-8s %-5d %-5d %-4d %-5d %-4d %-6s %-10.1f %-9.1f %-7.1f" % (
            cfg_name, sl, veto_lab, stats["n"], n_filtered, n_win, n_loss, n_to, pf_str,
            stats["pnl"], net_stats["pnl"], stats["max_dd"]
        )
        print(row)
