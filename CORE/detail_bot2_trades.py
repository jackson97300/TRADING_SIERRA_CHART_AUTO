"""Detail 4 trades Bot 2 DB Sim2."""
import json
from pathlib import Path

fp = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES/20260428_databento_trades.jsonl")
lines = fp.read_text(encoding="utf-8").splitlines()
print(f"Lines: {len(lines)}\n")

for i, line in enumerate(lines):
    t = json.loads(line)
    bull = t.get('bull_pts_entry') or t.get('bull_pts')
    bear = t.get('bear_pts_entry') or t.get('bear_pts')
    checks = t.get('checks_entry') or t.get('checks', [])
    print(f"--- Trade #{i+1} ---")
    print(f"  Symbol: {t['symbol']}  Direction: {t['direction']}")
    print(f"  Entry:  {t['entry_time'][:19]}  @ {t['entry_price']}")
    print(f"  Exit:   {t['exit_time'][:19]}  @ {t['exit_price']}")
    print(f"  Outcome: {t['outcome']}  PnL: {t['pnl_ticks']:+.0f}t (${t.get('pnl_usd', 0):+.2f})")
    print(f"  Duration: {t.get('duration_sec', 0):.0f}s")
    print(f"  SL: {t['sl_ticks']}t ({t.get('sl_wall', 'FIXED')})  TP: {t['tp_ticks']}t ({t.get('tp_wall', 'FIXED')})")
    print(f"  Score: bull={bull}/bear={bear}")
    print(f"  Checks: {checks[:5]}")
    print()
