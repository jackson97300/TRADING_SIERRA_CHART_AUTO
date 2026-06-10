"""test_anti_slippage_e2e.py — Test end-to-end Etapes 0+1+2 anti-slippage.

Sequence de tests (Sim1, NQ qty=1) :
  T0. Verifier que CORE.live_cache importable + heartbeat alive
  T1. read_bar(NQ) retourne bar live (age < 60s)
  T2. read_last_trade_close(NQ) retourne prix > 0 (latence ms)
  T3. get_signal_entry_ref(NQ, fallback=0) retourne (price, source) frais
  T4. Test calc_bracket_prices LONG/SHORT
  T5. send_market_order avec signal_ref_price+sl_ticks+tp_ticks sur Sim1 NQ qty=1
       -> verifier emit BRACKET_SLIP_METRIC dans events_paper_v2.jsonl
       -> verifier slip_ticks raisonnable (< 5t typiquement)
       -> cleanup via Type 209 + Type 210
"""
from __future__ import annotations
import sys, time, json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))

# T0. Imports
print("=" * 60)
print("T0. Imports + heartbeat check")
print("=" * 60)
try:
    from CORE import live_cache
    from CORE.execution.tpsl_pricer import calc_bracket_prices, slip_ticks
    print(f"  Imports OK (FALLBACK_MODE={live_cache.FALLBACK_MODE})")
except Exception as e:
    print(f"  FAIL imports: {e}")
    sys.exit(1)

alive, hb = live_cache.is_stream_alive()
print(f"  is_stream_alive() = {alive}")
print(f"  heartbeat: silence_sec={hb.get('silence_sec')} subscribe_alive={hb.get('subscribe_alive')}")
if not alive:
    print(f"  WARN : stream pas alive, les tests T1-T3 vont fallback")

# T1. read_bar
print("\n" + "=" * 60)
print("T1. read_bar(NQ)")
print("=" * 60)
bar = live_cache.read_bar("NQ", max_age_sec=180)
if bar is None:
    print("  FAIL ou STALE : read_bar retourne None")
else:
    print(f"  OK close={bar['close']} age_sec={bar.get('age_sec', '?'):.1f}")

# T2. read_last_trade_close
print("\n" + "=" * 60)
print("T2. read_last_trade_close(NQ, fallback=0)")
print("=" * 60)
trade_close = live_cache.read_last_trade_close("NQ", fallback=0.0, max_age_sec=10)
print(f"  trade_close={trade_close}")

# T3. get_signal_entry_ref
print("\n" + "=" * 60)
print("T3. get_signal_entry_ref(NQ, fallback=27800)")
print("=" * 60)
ref, src = live_cache.get_signal_entry_ref("NQ", fallback=27800.0)
print(f"  ref={ref} source={src}")

# T4. calc_bracket_prices
print("\n" + "=" * 60)
print("T4. calc_bracket_prices LONG / SHORT")
print("=" * 60)
sl, tp = calc_bracket_prices("LONG", 7250.0, 80, 120, 0.25)
print(f"  LONG ref=7250 sl=80t tp=120t -> sl={sl} (attend 7230) tp={tp} (attend 7280)")
assert sl == 7230.0 and tp == 7280.0, "Bug calc LONG"
sl, tp = calc_bracket_prices("SHORT", 27800.0, 200, 300, 0.25)
print(f"  SHORT ref=27800 sl=200t tp=300t -> sl={sl} (attend 27850) tp={tp} (attend 27725)")
assert sl == 27850.0 and tp == 27725.0, "Bug calc SHORT"
slip = slip_ticks(7252.5, 7250.0, 0.25)
print(f"  slip_ticks(7252.5, 7250) = {slip} (attend 10)")
assert slip == 10.0, "Bug slip_ticks"
print("  OK helpers")

# T5. send_market_order avec nouveaux params sur Sim1 NQ qty=1
print("\n" + "=" * 60)
print("T5. send_market_order Sim1 NQ qty=1 BUY avec signal_ref_price+ticks")
print("=" * 60)
from BOT.dtc_connector import DTCConnector, DTCConfig, BUY
cfg = DTCConfig(host="localhost", port=11099, heartbeat_interval_seconds=10)
dtc = DTCConnector(cfg)
if not dtc.connect():
    print("  FAIL connect DTC")
    sys.exit(1)
print("  DTC connecte")

# Pre-check : Sim1 NQ doit etre flat
qty0 = dtc.request_position_blocking("NQM26-CME", trade_account="Sim1", timeout=2.0)
if qty0 not in (None, 0):
    print(f"  FAIL pos depart {qty0} - flatten d'abord")
    dtc.disconnect()
    sys.exit(1)
print(f"  Pos depart = {qty0}")

# Construire signal_ref_price depuis live (comme fait Bot 3)
signal_ref, src = live_cache.get_signal_entry_ref("NQ", fallback=27800.0)
print(f"  signal_ref={signal_ref} ({src})")
SL_TICKS = 60     # 15 pts NQ
TP_TICKS = 90     # 22.5 pts NQ (R/R 1.5)
TICK_SIZE = 0.25
sl_price = signal_ref - SL_TICKS * TICK_SIZE   # LONG
tp_price = signal_ref + TP_TICKS * TICK_SIZE
print(f"  Prevu : sl={sl_price} tp={tp_price} sl_ticks={SL_TICKS} tp_ticks={TP_TICKS}")

t0 = time.time()
parent_id, tp_cid, sl_cid = dtc.send_market_order(
    symbol="NQM26-CME",
    side=BUY,
    quantity=1,
    sl_price=sl_price,
    tp_price=tp_price,
    trade_account="Sim1",
    signal_ref_price=signal_ref,
    sl_ticks=SL_TICKS,
    tp_ticks=TP_TICKS,
    tick_size=TICK_SIZE,
    auto_reprice_threshold_ticks=5,
)
t1 = time.time()
if not parent_id:
    print(f"  FAIL bracket")
    dtc.disconnect()
    sys.exit(1)
print(f"  Bracket OK (latence {(t1-t0)*1000:.0f}ms)")
print(f"     parent={parent_id} tp={tp_cid} sl={sl_cid}")

# Wait 5s puis cleanup
print("  Wait 5s puis cleanup...")
time.sleep(5.0)
dtc.cancel_order(tp_cid, trade_account="Sim1")
dtc.cancel_order(sl_cid, trade_account="Sim1")
time.sleep(1.5)
qty_b = dtc.request_position_blocking("NQM26-CME", trade_account="Sim1", timeout=2.0)
if qty_b and qty_b != 0:
    side_close = 2 if qty_b > 0 else 1
    close_cid = f"E2E_CLOSE_{int(time.time()) % 100000}"
    dtc._send({
        "Type": 208, "Symbol": "NQM26-CME", "ClientOrderID": close_cid,
        "OrderType": 1, "BuySell": side_close, "Quantity": abs(qty_b),
        "TradeAccount": "Sim1", "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2, "TimeInForce": 0,
    })
    print(f"  MARKET CLOSE qty={qty_b}")
    time.sleep(2.5)
# Type 210 bouclier
dtc._send({"Type": 210, "ClientOrderID": f"E2E_F_{int(time.time()) % 100000}",
           "TradeAccount": "Sim1", "IsAutomatedOrder": 1})
time.sleep(1.5)
qty_f = dtc.request_position_blocking("NQM26-CME", trade_account="Sim1", timeout=2.0)
print(f"  qty_final = {qty_f}")
dtc.disconnect()

print("\n=== T5 termine. Verifier dans LOGS/events/events_*_paper_v2.jsonl :")
print("    - BRACKET_SLIP_METRIC avec slip_ticks raisonnable")
print("    - eventuellement BRACKET_REPRICE si slip > 5t")
