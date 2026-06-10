def load_trades():
    opens, closes = {}, {}
    for d in DATES:
        fp = LOGS_DIR / ("bot3_v3_v1_" + d + ".jsonl")
        if not fp.exists():
            continue
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
                    opens[(d, sid)] = row
                elif ev == "TRADE_CLOSE":
                    closes[(d, sid)] = row
    trades = []
    for k, op in opens.items():
        d, sid = k
        cl = closes.get(k)
        if cl is None:
            continue
        trades.append({
            "date": d,
            "signal_id": sid,
            "ts_open_ns": op.get("ts_event_ns"),
            "ts_open_iso": op.get("ts"),
            "side": op.get("side"),
            "level": op.get("level"),
            "entry_price": op.get("entry_price"),
            "sl_price_orig": op.get("sl_price"),
            "tp_price_orig": op.get("tp_price"),
            "sl_ticks_orig": op.get("sl_ticks"),
            "exit_cause": cl.get("exit_cause"),
            "outcome": cl.get("outcome"),
            "pnl_R": cl.get("pnl_R"),
            "duration_bars": cl.get("duration_bars"),
            "exit_price": cl.get("exit_price"),
        })
    return trades
