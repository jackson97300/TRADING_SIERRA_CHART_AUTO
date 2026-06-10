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
