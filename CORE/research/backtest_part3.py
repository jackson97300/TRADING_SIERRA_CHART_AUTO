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
