"""Backtest SL 25/30/35t x veto L2 sur Bot 3 V3 NQ trades - v2 (FIFO matching parent_cid)."""
import json
from pathlib import Path

LOGS_DIR = Path(r"C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3")
ENRICHED_DIR = Path(r"C:/TRADING_SIERRA_CHART_AUTO/DATA/LIVE_ENRICHED/NQ")
TICK = 0.25
COSTS_TICKS = 2.0
HOLD_BARS = 30
TARGET_R = 1.5
DATES = ["20260524","20260525","20260526","20260527","20260528","20260529","20260531","20260601","20260602","20260603"]
def load_trades():
    """Parse TRADE_OPEN et TRADE_CLOSE en sequence, match par parent_cid si dispo
    sinon FIFO par signal_id."""
    trades = []
    for d in DATES:
        fp = LOGS_DIR / ("bot3_v3_v1_" + d + ".jsonl")
        if not fp.exists():
            continue
        opens_buffer = []  # ordered list of opens for this date
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                ev = row.get("event")
                sid = row.get("signal_id")
                if not sid:
                    continue
                if ev == "TRADE_OPEN":
                    opens_buffer.append(row)
                elif ev == "TRADE_CLOSE":
                    # match by parent_cid first, then FIFO by signal_id+side
                    matched = None
                    pc = row.get("parent_cid")
                    side = row.get("side")
                    if pc:
                        for i, op in enumerate(opens_buffer):
                            if op.get("parent_cid") == pc:
                                matched = opens_buffer.pop(i)
                                break
                    if matched is None:
                        for i, op in enumerate(opens_buffer):
                            if op.get("signal_id") == sid and op.get("side") == side:
                                matched = opens_buffer.pop(i)
                                break
                    if matched is None:
                        continue
                    trades.append({
                        "date": d,
                        "signal_id": sid,
                        "ts_open_ns": matched.get("ts_event_ns"),
                        "ts_open_iso": matched.get("ts"),
                        "side": matched.get("side"),
                        "level": matched.get("level"),
                        "entry_price": matched.get("entry_price"),
                        "sl_price_orig": matched.get("sl_price"),
                        "tp_price_orig": matched.get("tp_price"),
                        "sl_ticks_orig": matched.get("sl_ticks"),
                        "parent_cid": matched.get("parent_cid"),
                        "exit_cause": row.get("exit_cause"),
                        "outcome": row.get("outcome"),
                        "pnl_R": row.get("pnl_R"),
                        "duration_bars": row.get("duration_bars"),
                        "exit_price": row.get("exit_price"),
                    })
    return trades
def load_bars_for_date(date_str):
    fp = ENRICHED_DIR / (date_str + "_NQ.jsonl")
    if not fp.exists():
        return []
    bars = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts_ns = row.get("ts_event_ns")
            if ts_ns is None:
                continue
            bars.append({
                "ts_ns": int(ts_ns),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "ctx_price_slope_5": row.get("ctx_price_slope_5"),
            })
    bars.sort(key=lambda b: b["ts_ns"])
    return bars


def compute_mae_mfe(trade, bars):
    entry = trade["entry_price"]
    side = trade["side"]
    t0 = trade["ts_open_ns"]
    t_max = t0 + HOLD_BARS * 60 * 1_000_000_000
    mae_ticks = 0.0
    mfe_ticks = 0.0
    mae_bar_idx = -1
    mfe_bar_idx = -1
    bar_count = 0
    for b in bars:
        if b["ts_ns"] < t0:
            continue
        if b["ts_ns"] > t_max:
            break
        hi = b["high"]
        lo = b["low"]
        if hi is None or lo is None:
            continue
        bar_count += 1
        if side == "LONG":
            adv = (entry - lo) / TICK
            fav = (hi - entry) / TICK
        else:
            adv = (hi - entry) / TICK
            fav = (entry - lo) / TICK
        if adv > mae_ticks:
            mae_ticks = adv
            mae_bar_idx = bar_count
        if fav > mfe_ticks:
            mfe_ticks = fav
            mfe_bar_idx = bar_count
    return mae_ticks, mfe_ticks, mae_bar_idx, mfe_bar_idx, bar_count


def simulate_exit(entry, side, sl_ticks, tp_ticks, bars, t0):
    t_max = t0 + HOLD_BARS * 60 * 1_000_000_000
    last_bar = None
    for b in bars:
        if b["ts_ns"] < t0:
            continue
        if b["ts_ns"] > t_max:
            break
        last_bar = b
        hi = b["high"]
        lo = b["low"]
        if hi is None or lo is None:
            continue
        if side == "LONG":
            sl_price = entry - sl_ticks * TICK
            tp_price = entry + tp_ticks * TICK
            hit_sl = lo <= sl_price
            hit_tp = hi >= tp_price
            if hit_sl and hit_tp:
                return (-sl_ticks, "SL")
            if hit_sl:
                return (-sl_ticks, "SL")
            if hit_tp:
                return (tp_ticks, "TP")
        else:
            sl_price = entry + sl_ticks * TICK
            tp_price = entry - tp_ticks * TICK
            hit_sl = hi >= sl_price
            hit_tp = lo <= tp_price
            if hit_sl and hit_tp:
                return (-sl_ticks, "SL")
            if hit_sl:
                return (-sl_ticks, "SL")
            if hit_tp:
                return (tp_ticks, "TP")
    if last_bar is None:
        return (0.0, "NO_BARS")
    close = last_bar["close"]
    if side == "LONG":
        pnl = (close - entry) / TICK
    else:
        pnl = (entry - close) / TICK
    return (pnl, "TIMEOUT")


def check_l2_veto(trade, bars, thr):
    if trade["side"] != "LONG":
        return False
    t0 = trade["ts_open_ns"]
    slope_at_entry = None
    for b in bars:
        if b["ts_ns"] <= t0:
            slope_at_entry = b.get("ctx_price_slope_5")
        else:
            break
    if slope_at_entry is None:
        return False
    return slope_at_entry > thr


def compute_stats(pnls):
    n = len(pnls)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "pnl": 0, "pf": 0.0, "wr": 0.0, "max_dd": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w = sum(wins)
    gross_l = -sum(losses)
    pf = (gross_w / gross_l) if gross_l > 0 else (float("inf") if gross_w > 0 else 0.0)
    wr = len(wins) / n * 100
    total = sum(pnls)
    eq = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    return {"n": n, "wins": len(wins), "losses": len(losses), "pnl": total, "pf": pf, "wr": wr, "max_dd": max_dd}
def main():
    print("=" * 80)
    print("BACKTEST v2 SL 25/30/35 x VETO L2 OFF/3.5/5.0 sur Bot 3 V3 NQ")
    print("=" * 80)

    trades = load_trades()
    print("Total trades matches (FIFO) : " + str(len(trades)))

    by_cause = {}
    for tr in trades:
        c = tr.get("exit_cause") or "?"
        by_cause[c] = by_cause.get(c, 0) + 1
    print("Exit causes original : " + str(by_cause))

    # Baseline reel from pnl_R
    pnl_R_sum_in_R = sum((tr.get("pnl_R") or 0.0) for tr in trades)
    pnl_R_sum_ticks = sum((tr.get("pnl_R") or 0.0) * (tr.get("sl_ticks_orig") or 25) for tr in trades)
    n_win_real = sum(1 for tr in trades if (tr.get("pnl_R") or 0) > 0)
    n_loss_real = sum(1 for tr in trades if (tr.get("pnl_R") or 0) < 0)
    n_be_real = sum(1 for tr in trades if (tr.get("pnl_R") or 0) == 0)
    print("Baseline REEL (pnl_R from logs) : N=" + str(len(trades)) + " WIN=" + str(n_win_real) + " LOSS=" + str(n_loss_real) + " BE=" + str(n_be_real))
    print("  Sum pnl_R = " + ("%.2f" % pnl_R_sum_in_R) + " R-multiples")
    print("  Sum pnl_R ticks (assuming SL=25 fixe) = " + ("%.1f" % pnl_R_sum_ticks) + "t (gross, sans costs)")

    bars_by_date = {}
    for d in DATES:
        bars_by_date[d] = load_bars_for_date(d)

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
    print("## DISTRIBUTION MAE (30 min look-ahead post entry)")
    print("Median MAE LONG  (" + str(len(long_maes)) + ") : " + ("%.1f" % median(long_maes)) + "t")
    print("Median MAE SHORT (" + str(len(short_maes)) + ") : " + ("%.1f" % median(short_maes)) + "t")
    all_maes = [t["mae_ticks"] for t in enriched]
    if all_maes:
        pct_25 = sum(1 for m in all_maes if m >= 25) / len(all_maes) * 100
        pct_30 = sum(1 for m in all_maes if m >= 30) / len(all_maes) * 100
        pct_35 = sum(1 for m in all_maes if m >= 35) / len(all_maes) * 100
        pct_b_25_30 = sum(1 for m in all_maes if 25 <= m < 30) / len(all_maes) * 100
        pct_b_25_35 = sum(1 for m in all_maes if 25 <= m < 35) / len(all_maes) * 100
        print("PCT MAE GE 25t : " + ("%.1f" % pct_25))
        print("PCT MAE GE 30t : " + ("%.1f" % pct_30))
        print("PCT MAE GE 35t : " + ("%.1f" % pct_35))
        print("PCT 25 LE MAE LT 30 : " + ("%.1f" % pct_b_25_30) + " (sauves par SL30 vs SL25)")
        print("PCT 25 LE MAE LT 35 : " + ("%.1f" % pct_b_25_35) + " (sauves par SL35 vs SL25)")

    configs = []
    for sl in [25, 30, 35]:
        for veto in [None, 3.5, 5.0]:
            configs.append((sl, veto))

    print("")
    print("## MATRICE RESULTATS (simulation bar-par-bar, costs " + str(int(COSTS_TICKS)) + "t/trade)")
    print("NOTE : simu suppose fill au SL/TP price exact, sans slippage. PF est OPTIMISTE.")
    print("")
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
    print("")
    print("## TRADE 14:36 NQ LONG @30706.5 DETAIL")
    target = None
    for tr in enriched:
        if tr["side"] == "LONG" and tr["entry_price"] and abs(tr["entry_price"] - 30706.5) < 0.5:
            ts_iso = tr["ts_open_iso"] or ""
            if "14:3" in ts_iso:
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
        print("Trade non trouve. Candidates 03/06 LONG entry pres 30706.5:")
        d3 = [t for t in enriched if t["date"] == "20260603" and t["side"] == "LONG"]
        for t in d3[:10]:
            print("  " + t["signal_id"] + " entry=" + str(t["entry_price"]) + " ts=" + str(t["ts_open_iso"]) + " MAE=" + ("%.1f" % t["mae_ticks"]) + "t MFE=" + ("%.1f" % t["mfe_ticks"]) + "t cause=" + str(t.get("exit_cause")))

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

    out_fp = r"C:/TRADING_SIERRA_CHART_AUTO/LOGS/backtest_sl_l2_v3_matrix.json"
    try:
        with open(out_fp, "w", encoding="utf-8") as f:
            json.dump({"matrix": matrix, "n_enriched": len(enriched), "no_bars": no_bars_count, "baseline_pnl_R": pnl_R_sum_in_R, "baseline_pnl_ticks": pnl_R_sum_ticks}, f, indent=2)
        print("Matrix saved : " + out_fp)
    except Exception as e:
        print("Save failed: " + str(e))


if __name__ == "__main__":
    main()
