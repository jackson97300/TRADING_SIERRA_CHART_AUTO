"""test_bot2_check_exit_inline.py — Test live check_exit_dtc Bot 2 sur Sim2 NQ.

Stratégie :
1. Stop service Bot 2 (sinon conflit DTC + state)
2. Instance DatabentoPaperTrader inline (mêmes classes)
3. Send BUY MARKET 1 NQ + bracket TP serré (+2t) SL plus large (-10t)
4. Inject position dans active_positions Bot 2 inline
5. Boucle check_exit_dtc + observe les fills via callback _on_dtc_fill
6. Si live price touche TP (haut probable car TP +2t) → check_exit_dtc cancel les 2 brackets AVANT que SC fille → 1 seul fill
7. Si SC fille en parallèle → on voit dans logs

Observable sur Sierra Chart Sim2 NQ :
- B|Stop|... apparaît au bracket
- S|Lmt|... apparaît au bracket
- Quand check_exit_dtc déclenche → les 2 disparaissent

Usage : python -X utf8 CORE/test_bot2_check_exit_inline.py
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

from CORE.databento_paper_trader import DatabentoPaperTrader, BotConfig, TICK_SIZE
from BOT.dtc_connector import BUY as DTC_BUY

print("=" * 70)
print("  TEST INLINE BOT 2 check_exit_dtc — NQ Sim2 1 micro")
print("=" * 70)

# Instance Bot 2 inline
cfg = BotConfig()
cfg.quantity = 1  # 1 micro test seulement
cfg.trade_account = "Sim2"
cfg.dry_run = False
print(f"  account={cfg.trade_account} qty={cfg.quantity}")

bot = DatabentoPaperTrader(cfg)
if bot.dtc is None:
    print("FATAL : DTC connection failed")
    sys.exit(1)
print("  DTC connected")

# Read live price
live_price = bot._read_live_trade_price("NQ")
if live_price is None or live_price <= 0:
    print(f"FATAL : live price unavailable ({live_price})")
    sys.exit(2)

print(f"  Live NQ price : {live_price}")

# Bracket : TP serre (+2t) pour qu'il soit touche rapidement / SL +10t plus loin
tp_price = live_price + 2 * TICK_SIZE
sl_price = live_price - 10 * TICK_SIZE
print(f"  TP={tp_price:.2f} (+2t) SL={sl_price:.2f} (-10t)")
print(f"  → TP serre : si NQ monte de 0.50pt → check_exit_dtc devrait declencher")

# Send order via dtc connector
print(f"\n[1] BUY MARKET 1 NQM26-CME + bracket via dtc.send_market_order...")
parent_id, tp_cid, sl_cid = bot.dtc.send_market_order(
    symbol="NQM26-CME",
    side=DTC_BUY,
    quantity=1,
    sl_price=sl_price,
    tp_price=tp_price,
    trade_account="Sim2",
)
if not parent_id:
    print("FATAL : send_market_order returned no parent_id (probable parent fill timeout)")
    sys.exit(3)
print(f"  parent_id={parent_id}")
print(f"  tp_cid={tp_cid}")
print(f"  sl_cid={sl_cid}")

# Inject position in active_positions
print(f"\n[2] Inject position dans bot.active_positions...")
with bot._pos_lock:
    bot.active_positions["NQ"] = {
        "parent_id": parent_id,
        "tp_cid": tp_cid,
        "sl_cid": sl_cid,
        "side": "BUY",
        "entry": live_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "sl_ticks": 10,
        "tp_ticks": 2,
        "sl_wall": "TEST",
        "tp_wall": "TEST",
        "bull_pts": 4,
        "bear_pts": 1,
        "checks": ["TEST_INLINE"],
        "ts_open": datetime.now(timezone.utc),
        "bar_ts_entry": "TEST",
        "features_at_entry": {},
        "n_micros": 1,
    }
    bot._order_to_symbol[parent_id] = "NQ"
    bot._order_to_symbol[tp_cid] = "NQ"
    bot._order_to_symbol[sl_cid] = "NQ"
print(f"  Position injected. Wait 5s pour que SC enregistre les brackets (mitigation)...")
time.sleep(5)

# Boucle check_exit_dtc + observation
print(f"\n[3] Boucle check_exit_dtc (max 5 min, sortie si position close)...")
start = time.time()
last_log = 0
n_checks = 0
while time.time() - start < 300:  # 5 min max
    try:
        bot._check_exit_dtc("NQ")
        n_checks += 1
    except Exception as e:
        print(f"  check_exit_dtc exception: {e}")

    # Position closed ?
    with bot._pos_lock:
        if "NQ" not in bot.active_positions:
            print(f"  ✅ Position closed by callback _on_dtc_fill (clean)")
            break

    # Heartbeat log toutes les 10s
    now = time.time()
    if now - last_log > 10:
        live = bot._read_live_trade_price("NQ")
        elapsed = now - start
        print(f"  t+{elapsed:.0f}s | live={live} sl={sl_price} tp={tp_price} | n_checks={n_checks}")
        last_log = now

    time.sleep(1)

# Final
print(f"\n[4] Final state...")
with bot._pos_lock:
    has_pos = "NQ" in bot.active_positions
print(f"  Position NQ in active_positions : {has_pos}")
print(f"  Total checks executed : {n_checks}")

# Cleanup : flatten si encore position
if has_pos:
    print(f"  ⚠️  Position non fermee — cancel manuel + flatten")
    try:
        bot.dtc.cancel_order(tp_cid, trade_account="Sim2")
        bot.dtc.cancel_order(sl_cid, trade_account="Sim2")
    except Exception as e:
        print(f"  cancel fail: {e}")

# Verify position via DTC
time.sleep(2)
print(f"\n[5] Verify final via dtc.send POSITION_REQUEST...")
import json
import socket
s = socket.socket()
s.settimeout(5)
try:
    s.connect(("127.0.0.1", 11099))
    s.sendall(json.dumps({"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10,
                           "ClientName": "VERIFY"}).encode() + b"\x00")
    time.sleep(1)
    s.recv(4096)
    s.sendall(json.dumps({"Type": 305, "RequestID": 99, "TradeAccount": "Sim2"}).encode() + b"\x00")
    time.sleep(2)
    buf = b""
    end = time.time() + 3
    while time.time() < end:
        try:
            s.settimeout(0.3)
            c = s.recv(8192)
            if c:
                buf += c
        except socket.timeout:
            break
    msgs = []
    while b"\x00" in buf:
        idx = buf.find(b"\x00")
        try:
            msgs.append(json.loads(buf[:idx].decode("utf-8", "ignore")))
        except json.JSONDecodeError:
            pass
        buf = buf[idx + 1:]
    for m in msgs:
        if m.get("Type") == 306 and "NQ" in str(m.get("Symbol", "")):
            print(f"  Position NQ Sim2 : qty={m.get('Quantity', 0)}")
    s.close()
except Exception as e:
    print(f"  verify fail: {e}")

print("\n" + "=" * 70)
print("  TEST DONE")
print("=" * 70)
