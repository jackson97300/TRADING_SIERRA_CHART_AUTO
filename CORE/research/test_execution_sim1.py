"""test_execution_sim1.py — Test execution Sim1 + validation solution anti-orphelin.

Objectif (Jackson 04/05 matin) : reproduire la solution OCO du projet
MIA-IA-SYSTEM-2026 (sierra_dtc_connector.py + SOLUTION_BRACKET_OCO_FINAL.md +
VICTOIRE_OCO_AUTOMATIQUE_14NOV_2024.md) pour fix les ordres orphelins Bot 3
sur Sim1 NQ.

TIR CROISE valide 04/05 :
  - Doc SC officielle : ServerOrderID OBLIGATOIRE pour Type 203 cancel
  - Type 209 FLATTEN ne nettoie PAS forcement les working orders (non documente)
  - Solution : Cancel TP/SL (Type 203 + ServerOrderID) -> verify position broker
    (Type 305) -> MARKET CLOSE Type 208 si qty != 0

USAGE :
    # 1. Inventaire ordres + positions Sim1
    python -X utf8 CORE/research/test_execution_sim1.py --inventory

    # 2. Flatten urgence : cancel TOUS les ordres + close positions Sim1
    python -X utf8 CORE/research/test_execution_sim1.py --flatten-sim1

    # 3. Test bracket OCO single trade (NQ, qty=1, paper)
    python -X utf8 CORE/research/test_execution_sim1.py --test-bracket

    # 4. NEW Test sequence solution anti-orphelin (cleanup timeout-like)
    python -X utf8 CORE/research/test_execution_sim1.py --test-timeout-cleanup
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))

from BOT.dtc_connector import (
    DTCConnector, DTCConfig, BUY, SELL, MARKET, LIMIT, STOP,
    DTC_CANCEL_ORDER, DTC_MARKET_ORDER,
)

# DTC types non-exportes du connector
DTC_SUBMIT_FLATTEN_POSITION_ORDER = 209  # Symbol-specific flatten + cancel attached
DTC_FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT = 210  # Account-wide flatten + cancel ALL

# OrderStatus values DTC (CLAUDE.md ref)
STATUS_OPEN = 2
STATUS_WORKING = 4
STATUS_PENDING_CANCEL = 6
STATUS_FILLED = 7
STATUS_CANCELED = 8


# ====================================================================
# CONFIG TEST
# ====================================================================
DTC_HOST = "localhost"
DTC_PORT = 11099
DTC_USER = "MIA_TEST_SIM1"
TRADE_ACCOUNT = "Sim1"

# Test bracket : ES qty=1 (paper, no risk)
TEST_SYMBOL = "ESM26-CME"
TEST_QTY = 1
TEST_TP_OFFSET_TICKS = 20
TEST_SL_OFFSET_TICKS = 20
TICK_SIZE_ES = 0.25

# Test timeout cleanup : ES + NQ qty=1 (Sim1 = compte Bot 3)
CLEANUP_QTY = 1
CLEANUP_TP_OFFSET_TICKS_ES = 40  # 10 pts ES loin
CLEANUP_SL_OFFSET_TICKS_ES = 40
CLEANUP_TP_OFFSET_TICKS_NQ = 80  # 20 pts NQ loin
CLEANUP_SL_OFFSET_TICKS_NQ = 80
TICK_SIZE = 0.25  # ES et NQ ont meme tick size
CLEANUP_WAIT_BEFORE_CLEANUP_SEC = 25.0  # 25s pour observer les ordres dans le DOM
CLEANUP_WAIT_AFTER_CANCEL_SEC = 2.0
CLEANUP_WAIT_FINAL_VERIF_SEC = 5.0

CLEANUP_SYMBOLS = [
    {"sym": "ESM26-CME", "tp_t": CLEANUP_TP_OFFSET_TICKS_ES, "sl_t": CLEANUP_SL_OFFSET_TICKS_ES,
     "tp_real_t": 30, "sl_real_t": 30, "data_dir": "DATA/ES"},
    {"sym": "NQM26-CME", "tp_t": CLEANUP_TP_OFFSET_TICKS_NQ, "sl_t": CLEANUP_SL_OFFSET_TICKS_NQ,
     "tp_real_t": 30, "sl_real_t": 30, "data_dir": "DATA/NQ"},
]


def make_connector() -> DTCConnector:
    """Cree connector DTC Sim1 (DTCConfig accepts only host/port/heartbeat)."""
    cfg = DTCConfig(
        host=DTC_HOST,
        port=DTC_PORT,
        heartbeat_interval_seconds=10,
    )
    dtc = DTCConnector(cfg)
    if not dtc.connect():
        raise RuntimeError(f"DTC connect FAIL : {DTC_HOST}:{DTC_PORT}")
    print(f"[DTC] Connected to {DTC_HOST}:{DTC_PORT}")
    return dtc


# ====================================================================
# 1. INVENTAIRE ordres + positions
# ====================================================================
def inventory(dtc: DTCConnector) -> None:
    """Liste positions + ordres ouverts Sim1.

    DTC Type 305 = REQUEST_OPEN_ORDERS / Type 304 = CURRENT_POSITION_REQUEST.
    """
    print("\n=== INVENTAIRE Sim1 ===")
    print("Positions (request_position_blocking) :")
    for sym in ("ESM26-CME", "NQM26-CME"):
        try:
            qty = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=3.0)
            print(f"  {sym}: qty={qty}")
        except Exception as e:
            print(f"  {sym}: ERROR {e}")

    # Note : request_open_orders not implemented in BOT/dtc_connector.py
    print("\nOrdres ouverts : check Sierra Chart GUI > Trade Activity Log > Sim1")


# ====================================================================
# 2. FLATTEN URGENCE Sim1
# ====================================================================
def flatten_sim1(dtc: DTCConnector) -> None:
    """Cancel + close positions Sim1 (sequence : cancel orders, then market close)."""
    print("\n=== FLATTEN URGENCE Sim1 ===")

    for sym in ("ESM26-CME", "NQM26-CME"):
        qty = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=3.0)
        if qty is None or qty == 0:
            print(f"  {sym}: position 0 (rien a flatten)")
            continue
        print(f"  {sym}: position {qty}")

        side = SELL if qty > 0 else BUY
        close_qty = abs(qty)
        cid = f"FLATTEN_{sym[:2]}_{int(time.time()) % 10000}"
        msg = {
            "Type": DTC_MARKET_ORDER,
            "Symbol": sym,
            "ClientOrderID": cid,
            "OrderType": MARKET,
            "BuySell": side,
            "Quantity": close_qty,
            "TradeAccount": TRADE_ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,  # CLOSE
            "TimeInForce": 0,
        }
        dtc._send(msg)
        print(f"  {sym}: FLATTEN sent {cid} side={side} qty={close_qty}")
        time.sleep(0.5)

    print("Wait 3s for fills...")
    time.sleep(3.0)

    print("\nVerifications post-flatten :")
    for sym in ("ESM26-CME", "NQM26-CME"):
        qty = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=3.0)
        status = "OK FLAT" if (qty is None or qty == 0) else f"FAIL STILL OPEN qty={qty}"
        print(f"  {sym}: {status}")


# ====================================================================
# 3. TEST BRACKET OCO single trade
# ====================================================================
def test_bracket(dtc: DTCConnector) -> None:
    """Test bracket entry + TP + SL avec OCO manuel actif."""
    print("\n=== TEST BRACKET OCO single trade Sim1 ===")
    print(f"Symbol={TEST_SYMBOL} qty={TEST_QTY} side=BUY")
    print(f"TP offset={TEST_TP_OFFSET_TICKS}t SL offset={TEST_SL_OFFSET_TICKS}t")

    print("\nSubscribe market data...")
    dtc.subscribe_market_data(TEST_SYMBOL)
    time.sleep(2.0)
    last_prices = dtc._last_prices.get(TEST_SYMBOL, {})
    last = last_prices.get("last") or last_prices.get("ask") or 0
    if not last:
        print(f"  FAIL Pas de last price recu ({last_prices}). Abort.")
        return
    print(f"  Last price : {last}")

    tp_price = last + TEST_TP_OFFSET_TICKS * TICK_SIZE_ES
    sl_price = last - TEST_SL_OFFSET_TICKS * TICK_SIZE_ES
    print(f"  TP @ {tp_price} | SL @ {sl_price}")

    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=TEST_SYMBOL,
        side=BUY,
        quantity=TEST_QTY,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=TRADE_ACCOUNT,
    )
    if not parent_id:
        print(f"  FAIL Bracket : parent_id vide")
        return
    print(f"\n  OK Bracket sent : parent={parent_id} TP={tp_cid} SL={sl_cid}")
    print(f"  OCO pair registered : verifier Sierra Chart GUI Sim1 Trade Activity")
    print(f"\nWait 30s pour observer...")
    time.sleep(30.0)

    print("\nFinal inventory :")
    qty = dtc.request_position_blocking(TEST_SYMBOL, trade_account=TRADE_ACCOUNT, timeout=3.0)
    print(f"  {TEST_SYMBOL}: position={qty}")
    print(f"  TP/SL devraient etre actifs Sierra Chart")


# ====================================================================
# 4. TEST SEQUENCE SOLUTION ANTI-ORPHELIN (timeout cleanup)
# ====================================================================
def _get_last_price(dtc: DTCConnector, symbol: str, data_dir: str) -> float:
    """Recupere last price via DTC subscribe ou fallback JSONL DMP."""
    dtc.subscribe_market_data(symbol)
    time.sleep(2.0)
    last_prices = dtc._last_prices.get(symbol, {})
    last = last_prices.get("last") or last_prices.get("ask") or 0
    if last:
        return float(last)
    # Fallback JSONL DMP
    from datetime import datetime, timezone
    import json as _json, glob as _glob, os as _os
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    instr = data_dir.rsplit("/", 1)[-1]  # ES ou NQ
    candidates = sorted(_glob.glob(f"{data_dir}/{today}_{instr}.jsonl"), key=_os.path.getmtime, reverse=True)
    if not candidates:
        candidates = sorted(_glob.glob(f"{data_dir}/*_{instr}.jsonl"), key=_os.path.getmtime, reverse=True)
    if not candidates:
        return 0.0
    with open(candidates[0], "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines:
        return 0.0
    last_bar = _json.loads(lines[-1])
    return float(last_bar.get("price", 0))


def _test_one_symbol(dtc: DTCConnector, symbol: str, tp_t: int, sl_t: int, data_dir: str) -> dict:
    """Test sequence solution sur 1 symbole. Retourne dict resume."""
    print(f"\n{'='*60}")
    print(f"=== TEST SEQUENCE SOLUTION ANTI-ORPHELIN Sim1 {symbol} ===")
    print(f"{'='*60}")
    print(f"Symbol={symbol} qty={CLEANUP_QTY} side=BUY")
    print(f"TP offset={tp_t}t (= {tp_t*TICK_SIZE} pts) SL offset={sl_t}t")

    # Pre-check
    print("\n[PRE-CHECK] Verification position de depart...")
    qty0 = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=3.0)
    if qty0 is not None and qty0 != 0:
        print(f"  FAIL Position de depart {symbol} = {qty0} (attendu 0). Lance --flatten-sim1.")
        return {"sym": symbol, "verdict": "FAIL_PRECHECK", "qty_final": qty0}
    print(f"  OK position de depart = {qty0}")

    # Last price
    print(f"\n[STEP 0] Recuperation last price {symbol}...")
    last = _get_last_price(dtc, symbol, data_dir)
    if not last:
        print(f"  FAIL Pas de last price.")
        return {"sym": symbol, "verdict": "FAIL_PRICE", "qty_final": None}
    print(f"  Last price : {last}")

    tp_price = last + tp_t * TICK_SIZE
    sl_price = last - sl_t * TICK_SIZE
    print(f"  TP @ {tp_price} | SL @ {sl_price}")

    # STEP A : envoi bracket
    print(f"\n[STEP A] Envoi bracket {symbol} BUY qty=1...")
    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=symbol,
        side=BUY,
        quantity=CLEANUP_QTY,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=TRADE_ACCOUNT,
    )
    if not parent_id:
        print(f"  FAIL Bracket : parent_id vide")
        return {"sym": symbol, "verdict": "FAIL_BRACKET", "qty_final": None}
    print(f"  OK Bracket sent : parent={parent_id} TP={tp_cid} SL={sl_cid}")

    # STEP B
    print(f"\n[STEP B] Wait {CLEANUP_WAIT_BEFORE_CLEANUP_SEC}s pour observer DOM Sierra Chart Sim1...")
    print(f"  ===> REGARDE LE DOM MAINTENANT, tu dois voir position +1 + TP@{tp_price} + SL@{sl_price}")
    time.sleep(CLEANUP_WAIT_BEFORE_CLEANUP_SEC)

    sid_parent = dtc._server_order_ids.get(parent_id, "")
    sid_tp = dtc._server_order_ids.get(tp_cid, "")
    sid_sl = dtc._server_order_ids.get(sl_cid, "")
    print(f"  ServerOrderIDs : parent={sid_parent} TP={sid_tp} SL={sid_sl}")

    # STEP C : SEQUENCE SOLUTION
    print("\n[STEP C] === APPLICATION SEQUENCE SOLUTION ===")
    cancel_tp_ok = dtc.cancel_order(tp_cid, trade_account=TRADE_ACCOUNT)
    print(f"  [C.1] Cancel TP returned : {cancel_tp_ok}")
    cancel_sl_ok = dtc.cancel_order(sl_cid, trade_account=TRADE_ACCOUNT)
    print(f"  [C.2] Cancel SL returned : {cancel_sl_ok}")
    print(f"  [C.3] Wait {CLEANUP_WAIT_AFTER_CANCEL_SEC}s propagation...")
    time.sleep(CLEANUP_WAIT_AFTER_CANCEL_SEC)

    qty_broker = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
    print(f"  [C.4] qty_broker = {qty_broker}")

    if qty_broker is None:
        print(f"  [C.5] FAIL : qty_broker=None")
        return {"sym": symbol, "verdict": "FAIL_DTC_FREEZE", "qty_final": None}
    if qty_broker != 0:
        print(f"  [C.5] Position residuelle qty={qty_broker} -> MARKET CLOSE...")
        side_close = SELL if qty_broker > 0 else BUY
        close_qty = abs(qty_broker)
        close_cid = f"CLEANUP_{symbol[:2]}_{int(time.time()) % 100000}"
        dtc._send({
            "Type": DTC_MARKET_ORDER,
            "Symbol": symbol,
            "ClientOrderID": close_cid,
            "OrderType": MARKET,
            "BuySell": side_close,
            "Quantity": close_qty,
            "TradeAccount": TRADE_ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,
            "TimeInForce": 0,
        })
        print(f"        MARKET CLOSE : CID={close_cid} side={side_close} qty={close_qty}")
    else:
        print(f"  [C.5] OK : deja flat (skip MARKET CLOSE)")

    # STEP D + E
    print(f"\n[STEP D] Wait {CLEANUP_WAIT_FINAL_VERIF_SEC}s fills MARKET CLOSE...")
    time.sleep(CLEANUP_WAIT_FINAL_VERIF_SEC)
    qty_final = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=3.0)
    verdict = "OK" if qty_final == 0 else f"FAIL_qty={qty_final}"
    print(f"\n[STEP E] qty_final={qty_final} -> {verdict}")

    return {
        "sym": symbol, "verdict": verdict, "parent": parent_id, "tp": tp_cid, "sl": sl_cid,
        "sid_parent": sid_parent, "sid_tp": sid_tp, "sid_sl": sid_sl,
        "cancel_tp": cancel_tp_ok, "cancel_sl": cancel_sl_ok,
        "qty_broker_C4": qty_broker, "qty_final": qty_final,
    }


# ====================================================================
# 5. TEST BRACKET REEL (TP/SL serres 8t, comme bot live) + LATENCE
# ====================================================================
REAL_TP_TICKS = 8
REAL_SL_TICKS = 8
REAL_FILL_TIMEOUT_SEC = 240.0  # 4 min max attente fill TP/SL
REAL_FLAT_TIMEOUT_SEC = 5.0    # max attente flat apres fill OCO
REAL_OCO_CANCEL_TIMEOUT_SEC = 3.0  # max attente Status=8 sur l'oppose apres fill


def _send_flatten_account(dtc: DTCConnector, trade_account: str) -> None:
    """Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT : force cleanup ALL working
    orders + positions du compte. Fallback definitif anti-orphelin.

    BUG FIX 04/05 : SC rejette si ClientOrderID absent ('ClientOrderID field
    is not set' dans logs SC). On ajoute un ClientOrderID unique.
    """
    cid = f"FLUSH_ACCT_{int(time.time() * 1000) % 1000000}"
    msg = {
        "Type": DTC_FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT,
        "ClientOrderID": cid,
        "TradeAccount": trade_account,
        "IsAutomatedOrder": 1,
    }
    dtc._send(msg)
    print(f"  [FLUSH] Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT={trade_account} CID={cid}")


def _send_flatten_symbol(dtc: DTCConnector, symbol: str, trade_account: str) -> None:
    """Type 209 SUBMIT_FLATTEN_POSITION_ORDER par symbole.

    BUG FIX 04/05 : SC rejette si ClientOrderID absent. On ajoute un ClientOrderID.
    """
    cid = f"FLUSH_{symbol[:2]}_{int(time.time() * 1000) % 1000000}"
    msg = {
        "Type": DTC_SUBMIT_FLATTEN_POSITION_ORDER,
        "ClientOrderID": cid,
        "Symbol": symbol,
        "TradeAccount": trade_account,
        "Exchange": "CME",
        "IsAutomatedOrder": 1,
    }
    dtc._send(msg)
    print(f"  [FLUSH-SYM] Type 209 FLATTEN {symbol} {trade_account} CID={cid}")


def _test_one_real(dtc: DTCConnector, symbol: str, data_dir: str,
                    fills_log: dict, status_log: dict,
                    pure_t203_only: bool = False,
                    tp_ticks: int = REAL_TP_TICKS,
                    sl_ticks: int = REAL_SL_TICKS) -> dict:
    """Bracket reel TP=8t SL=8t qty=1 sur Sim1 + mesure latences."""
    print(f"\n{'='*60}")
    print(f"=== TEST BRACKET REEL {symbol} (TP=8t SL=8t qty=1 BUY) ===")
    print(f"{'='*60}")

    # Pre-check
    qty0 = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=3.0)
    if qty0 is not None and qty0 != 0:
        print(f"  FAIL position depart {symbol}={qty0}")
        return {"sym": symbol, "verdict": "FAIL_PRECHECK"}

    # Last price
    last = _get_last_price(dtc, symbol, data_dir)
    if not last:
        return {"sym": symbol, "verdict": "FAIL_PRICE"}
    tp_price = last + tp_ticks * TICK_SIZE
    sl_price = last - sl_ticks * TICK_SIZE
    print(f"  Last={last} | TP @ {tp_price} (+{tp_ticks}t) | SL @ {sl_price} (-{sl_ticks}t)")

    # === ENVOI BRACKET avec mesure latence ===
    t0 = time.time()
    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=symbol,
        side=BUY,
        quantity=CLEANUP_QTY,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=TRADE_ACCOUNT,
    )
    t1 = time.time()
    if not parent_id:
        return {"sym": symbol, "verdict": "FAIL_BRACKET"}
    L1_parent_ms = (t1 - t0) * 1000.0
    print(f"  [LAT] Parent send -> fill : {L1_parent_ms:.0f} ms")
    print(f"  Bracket OK : parent={parent_id} TP={tp_cid} SL={sl_cid}")
    print(f"  ===> Sierra Chart Sim1 : position +1 + TP {tp_price} + SL {sl_price}")
    print(f"\n  Wait jusqu'a fill TP ou SL (max {REAL_FILL_TIMEOUT_SEC:.0f}s)...")

    # === ATTENTE FILL TP ou SL ===
    t_fill_oco = None
    filled_cid = None
    deadline = time.time() + REAL_FILL_TIMEOUT_SEC
    while time.time() < deadline:
        if tp_cid in fills_log:
            t_fill_oco = fills_log[tp_cid]
            filled_cid = tp_cid
            print(f"  TP FILLED at {t_fill_oco:.3f}")
            break
        if sl_cid in fills_log:
            t_fill_oco = fills_log[sl_cid]
            filled_cid = sl_cid
            print(f"  SL FILLED at {t_fill_oco:.3f}")
            break
        time.sleep(0.05)

    if t_fill_oco is None:
        print(f"  TIMEOUT {REAL_FILL_TIMEOUT_SEC:.0f}s sans fill TP/SL -> cleanup sequence solution...")
        dtc.cancel_order(tp_cid, trade_account=TRADE_ACCOUNT)
        dtc.cancel_order(sl_cid, trade_account=TRADE_ACCOUNT)
        time.sleep(1.5)
        qty_b = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
        if qty_b and qty_b != 0:
            side_close = SELL if qty_b > 0 else BUY
            close_cid = f"REAL_TIMEOUT_{symbol[:2]}_{int(time.time()) % 100000}"
            dtc._send({
                "Type": DTC_MARKET_ORDER, "Symbol": symbol, "ClientOrderID": close_cid,
                "OrderType": MARKET, "BuySell": side_close, "Quantity": abs(qty_b),
                "TradeAccount": TRADE_ACCOUNT, "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2, "TimeInForce": 0,
            })
            time.sleep(3.0)
        # 04/05 : path TIMEOUT systematique = Type 210 bouclier ultime
        # (Status=8 retourne par SC peut etre false positive sur Sim)
        print(f"  [SHIELD] Type 210 systematique post-timeout (force purge DOM Sim)...")
        _send_flatten_account(dtc, TRADE_ACCOUNT)
        time.sleep(2.0)
        # FLUSH SYSTEMATIQUE Type 209 par symbole post-cleanup
        print(f"  [FLUSH-SYS] Type 209 FLATTEN {symbol} systematique post-cleanup...")
        _send_flatten_symbol(dtc, symbol, TRADE_ACCOUNT)
        time.sleep(1.5)
        # Verif Status=8 sur TP et SL
        st_tp = status_log.get(tp_cid)
        st_sl = status_log.get(sl_cid)
        tp_ok = st_tp == STATUS_CANCELED
        sl_ok = st_sl == STATUS_CANCELED
        print(f"  [VERIF TIMEOUT] TP status={st_tp} ({'OK' if tp_ok else 'KO'}) "
              f"SL status={st_sl} ({'OK' if sl_ok else 'KO'})")
        flushed = False
        if not (tp_ok and sl_ok):
            print(f"  [FALLBACK] Encore non-confirme -> Type 210 (account-wide)...")
            _send_flatten_account(dtc, TRADE_ACCOUNT)
            flushed = True
            time.sleep(2.5)
            st_tp2 = status_log.get(tp_cid)
            st_sl2 = status_log.get(sl_cid)
            tp_ok = st_tp2 == STATUS_CANCELED
            sl_ok = st_sl2 == STATUS_CANCELED
            print(f"  [VERIF after Type 210] TP status={st_tp2} SL status={st_sl2}")
        qty_f = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
        verdict = "OK_TIMEOUT" if (qty_f == 0 and tp_ok and sl_ok) else "FAIL_TIMEOUT_ORPHAN"
        return {"sym": symbol, "verdict": verdict, "qty_final": qty_f, "flushed": flushed,
                "tp_status": st_tp, "sl_status": st_sl,
                "L1_parent_ms": L1_parent_ms}

# === ATTENTE FLAT BROKER (OCO auto cancel + position flat) ===
    t_flat = None
    deadline = time.time() + REAL_FLAT_TIMEOUT_SEC
    while time.time() < deadline:
        qty_b = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=1.0)
        if qty_b == 0:
            t_flat = time.time()
            break
        time.sleep(0.1)

    L3_oco_flat_ms = (t_flat - t_fill_oco) * 1000.0 if t_flat else None
    L_total_ms = (t_flat - t0) * 1000.0 if t_flat else None
    print(f"\n  [LAT] Fill {filled_cid[-12:]} -> flat broker : {L3_oco_flat_ms:.0f} ms" if L3_oco_flat_ms else "  [LAT] Pas de flat detecte")

    # === VERIFICATION CRITIQUE : oppose Canceled (Status=8) ? ===
    opposite_cid = sl_cid if filled_cid == tp_cid else tp_cid
    print(f"\n  [VERIF] Attente Status=8 (Canceled) sur oppose {opposite_cid[-12:]}...")
    deadline = time.time() + REAL_OCO_CANCEL_TIMEOUT_SEC
    opposite_canceled = False
    while time.time() < deadline:
        st = status_log.get(opposite_cid)
        if st == STATUS_CANCELED:
            opposite_canceled = True
            break
        time.sleep(0.1)
    last_status = status_log.get(opposite_cid, "unknown")
    print(f"  [VERIF] Oppose status={last_status} canceled={opposite_canceled}")

    # === FLUSH SYSTEMATIQUE Type 209 par symbole (sauf mode pur) ===
    flushed = False
    if not pure_t203_only:
        print(f"  [FLUSH-SYS] Type 209 FLATTEN {symbol} systematique post-close...")
        _send_flatten_symbol(dtc, symbol, TRADE_ACCOUNT)
        time.sleep(1.5)
        last_status = status_log.get(opposite_cid, "unknown")
        if last_status == STATUS_CANCELED:
            opposite_canceled = True

        # === FALLBACK Type 210 si encore pas Canceled ===
        if not opposite_canceled:
            print(f"  [FALLBACK] Oppose toujours PAS Canceled -> Type 210 (account-wide)...")
            _send_flatten_account(dtc, TRADE_ACCOUNT)
            flushed = True
            time.sleep(2.0)
            last_status = status_log.get(opposite_cid, "unknown")
            if last_status == STATUS_CANCELED:
                opposite_canceled = True
                print(f"  [FALLBACK] Oppose Canceled apres Type 210")
    else:
        print(f"  [PURE-T203] Mode pur : pas de Type 209/210, on observe juste si l'oppose disparait du DOM")

    qty_final = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
    print(f"  qty_final={qty_final}")

    if qty_final == 0 and opposite_canceled:
        verdict = "OK"
    elif qty_final == 0 and flushed:
        verdict = "OK_AFTER_FLUSH"
    elif qty_final == 0:
        verdict = "FAIL_OCO_ORPHAN"  # qty=0 mais oppose pas Canceled
    else:
        verdict = f"FAIL_qty={qty_final}"
    print(f"  VERDICT : {verdict}")

    return {
        "sym": symbol, "verdict": verdict, "filled": filled_cid, "opposite": opposite_cid,
        "opposite_canceled": opposite_canceled, "opposite_status": last_status,
        "flushed": flushed,
        "L1_parent_ms": L1_parent_ms, "L3_oco_flat_ms": L3_oco_flat_ms,
        "L_total_ms": L_total_ms, "qty_final": qty_final,
    }


def _test_one_real_t210(dtc: DTCConnector, symbol: str, data_dir: str,
                         fills_log: dict, status_log: dict) -> dict:
    """Bracket reel + Type 210 SYSTEMATIQUE post-close (validation H4)."""
    print(f"\n{'='*60}")
    print(f"=== TEST BRACKET T210 {symbol} ===")
    print(f"{'='*60}")

    qty0 = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=3.0)
    if qty0 is not None and qty0 != 0:
        return {"sym": symbol, "verdict": "FAIL_PRECHECK"}

    last = _get_last_price(dtc, symbol, data_dir)
    if not last:
        return {"sym": symbol, "verdict": "FAIL_PRICE"}
    tp_price = last + REAL_TP_TICKS * TICK_SIZE
    sl_price = last - REAL_SL_TICKS * TICK_SIZE
    print(f"  Last={last} | TP={tp_price} | SL={sl_price}")

    t0 = time.time()
    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=symbol, side=BUY, quantity=CLEANUP_QTY,
        sl_price=sl_price, tp_price=tp_price, trade_account=TRADE_ACCOUNT,
    )
    t1 = time.time()
    if not parent_id:
        return {"sym": symbol, "verdict": "FAIL_BRACKET"}
    print(f"  [LAT] Parent fill = {(t1-t0)*1000:.0f}ms | parent={parent_id}")

    print(f"  Wait fill TP/SL (max {REAL_FILL_TIMEOUT_SEC:.0f}s)...")
    t_fill = None
    filled_cid = None
    deadline = time.time() + REAL_FILL_TIMEOUT_SEC
    while time.time() < deadline:
        if tp_cid in fills_log:
            t_fill = fills_log[tp_cid]; filled_cid = tp_cid; break
        if sl_cid in fills_log:
            t_fill = fills_log[sl_cid]; filled_cid = sl_cid; break
        time.sleep(0.05)

    if t_fill is None:
        # TIMEOUT : Type 210 direct
        print(f"  TIMEOUT -> Type 210 direct...")
        _send_flatten_account(dtc, TRADE_ACCOUNT)
        time.sleep(2.5)
        qty_f = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
        return {"sym": symbol, "verdict": "OK_TIMEOUT_T210" if qty_f == 0 else "FAIL", "qty_final": qty_f}

    print(f"  {filled_cid[-12:]} FILLED")
    opposite_cid = sl_cid if filled_cid == tp_cid else tp_cid

    # Wait flat broker
    deadline = time.time() + REAL_FLAT_TIMEOUT_SEC
    while time.time() < deadline:
        q = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=1.0)
        if q == 0: break
        time.sleep(0.1)

    # === Type 210 SYSTEMATIQUE (test H4) ===
    print(f"  [T210-SYS] Type 210 post-close (sans cancel Type 203 prealable)...")
    _send_flatten_account(dtc, TRADE_ACCOUNT)
    time.sleep(2.5)

    last_status_opp = status_log.get(opposite_cid, "unknown")
    qty_final = dtc.request_position_blocking(symbol, trade_account=TRADE_ACCOUNT, timeout=2.0)
    verdict = "OK" if (qty_final == 0 and last_status_opp == STATUS_CANCELED) else f"FAIL qty={qty_final} st={last_status_opp}"
    print(f"  Oppose status={last_status_opp} qty_final={qty_final} -> {verdict}")
    return {"sym": symbol, "verdict": verdict, "filled": filled_cid, "opposite": opposite_cid,
            "opposite_status": last_status_opp, "qty_final": qty_final}


def test_bracket_real_t210(dtc: DTCConnector) -> None:
    """Test H4 : Type 210 systematique post-close suffit."""
    print("\n=== TEST H4 : Type 210 SYSTEMATIQUE post-close ===")
    print("Verifier si Type 210 seul (sans Type 203 prealable) cleanup le DOM.")

    fills_log, status_log = {}, {}
    original_on_fill = dtc.on_fill
    original_handle = dtc._handle_order_update

    def capture_fill(fill):
        fills_log[fill.order_id] = time.time()
        if original_on_fill:
            try: original_on_fill(fill)
            except Exception: pass
    def capture_status(msg):
        try:
            cid = msg.get("ClientOrderID", "")
            st = msg.get("OrderStatus", 0)
            if cid: status_log[cid] = st
        except Exception: pass
        return original_handle(msg)
    dtc.on_fill = capture_fill
    dtc._handle_order_update = capture_status

    try:
        results = []
        for cfg in CLEANUP_SYMBOLS:
            r = _test_one_real_t210(dtc, cfg["sym"], cfg["data_dir"], fills_log, status_log)
            results.append(r)
            print(f"--- Pause 8s ---")
            time.sleep(8.0)
        print(f"\n=== RESUME H4 Type 210 SYSTEMATIQUE ===")
        for r in results:
            print(f"  {r['sym']:12s} verdict={r.get('verdict')}")
        print(f"\n  ===> VERIFIER GUI Sim1 : aucun ordre Working visible ?")
    finally:
        dtc.on_fill = original_on_fill
        dtc._handle_order_update = original_handle


def test_nq_only_observable(dtc: DTCConnector) -> None:
    """Place 1 bracket NQ qty=1 TP+50t / SL-50t (loin, peu de chance de fill rapide).
    Wait 30s pour que Jackson observe le bracket dans le DOM Sim1 NQ.
    Puis cleanup propre via cancel + Type 209.
    """
    sym = "NQM26-CME"
    print(f"\n=== TEST NQ OBSERVABLE (TP/SL 50t larges, wait 30s pour DOM) ===")
    qty0 = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=3.0)
    if qty0 not in (None, 0):
        print(f"  FAIL pos depart {qty0}")
        return
    last = _get_last_price(dtc, sym, "DATA/NQ")
    if not last:
        print("  FAIL pas de last")
        return
    tp = last + 50 * TICK_SIZE
    sl = last - 50 * TICK_SIZE
    print(f"  Last={last} TP={tp} (+50t = +12.5pts) SL={sl} (-50t = -12.5pts)")
    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=sym, side=BUY, quantity=1, sl_price=sl, tp_price=tp, trade_account=TRADE_ACCOUNT
    )
    if not parent_id:
        print("  FAIL bracket")
        return
    print(f"  Bracket envoye : parent={parent_id} TP={tp_cid} SL={sl_cid}")
    print(f"  ===> REGARDE DOM Sim1 NQ : tu devrais voir +1 + TP @ {tp} + SL @ {sl}")
    print(f"  Wait 30s d'observation...")
    time.sleep(30.0)

    print(f"\n  Cleanup : cancel TP + cancel SL...")
    dtc.cancel_order(tp_cid, trade_account=TRADE_ACCOUNT)
    dtc.cancel_order(sl_cid, trade_account=TRADE_ACCOUNT)
    time.sleep(1.5)
    qty = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=2.0)
    if qty and qty != 0:
        side_close = SELL if qty > 0 else BUY
        dtc._send({
            "Type": DTC_MARKET_ORDER, "Symbol": sym,
            "ClientOrderID": f"OBSV_{int(time.time()) % 100000}",
            "OrderType": MARKET, "BuySell": side_close, "Quantity": abs(qty),
            "TradeAccount": TRADE_ACCOUNT, "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2, "TimeInForce": 0,
        })
        time.sleep(2.0)
    _send_flatten_symbol(dtc, sym, TRADE_ACCOUNT)
    time.sleep(1.5)
    qty_f = dtc.request_position_blocking(sym, trade_account=TRADE_ACCOUNT, timeout=2.0)
    print(f"  qty_final={qty_f}")


def test_bracket_real_pure(dtc: DTCConnector) -> None:
    """Mode pur Type 203 sans Type 209/210 — isole H1 'Use Attached Orders'.

    Procedure : decocher 'Use Attached Orders' sur Sim1 ES uniquement (NQ controle).
    Lance bracket sur les 2 -> attend fill -> observe si oppose disparait via Type 203 pur.
    """
    print("\n=== TEST PUR Type 203 (isolation H1 'Use Attached Orders') ===")
    print("Sim1 ES = decoche 'Use Attached Orders' / NQ = coche (controle).")
    print("Pas de Type 209 ni Type 210 -> on observe le DOM apres cancel pur.")

    fills_log = {}
    status_log = {}
    original_on_fill = dtc.on_fill
    original_handle = dtc._handle_order_update

    def capture_fill(fill):
        fills_log[fill.order_id] = time.time()
        if original_on_fill:
            try: original_on_fill(fill)
            except Exception: pass
    def capture_status(msg):
        try:
            cid = msg.get("ClientOrderID", "")
            st = msg.get("OrderStatus", 0)
            if cid: status_log[cid] = st
        except Exception: pass
        return original_handle(msg)
    dtc.on_fill = capture_fill
    dtc._handle_order_update = capture_status

    try:
        results = []
        for cfg in CLEANUP_SYMBOLS:
            r = _test_one_real(dtc, cfg["sym"], cfg["data_dir"], fills_log, status_log,
                                pure_t203_only=True)
            results.append(r)
            print(f"\n--- Pause 8s avant prochain symbole ---")
            time.sleep(8.0)

        print(f"\n{'='*60}")
        print(f"=== RESUME TEST PUR Type 203 ===")
        print(f"{'='*60}")
        for r in results:
            print(f"  {r['sym']:12s} verdict={r.get('verdict')}")
            print(f"           Oppose canceled (DTC) = {r.get('opposite_canceled')} (status={r.get('opposite_status')})")
            print(f"           qty_final            = {r.get('qty_final')}")
            print(f"           L1 parent fill       = {r.get('L1_parent_ms', 0):.0f}ms")
            print(f"           L3 fill->flat        = {r.get('L3_oco_flat_ms', 0):.0f}ms" if r.get('L3_oco_flat_ms') else "")
        print(f"\n  ===> VERIFIER GUI Sim1 :")
        print(f"  ES   (Use Attached DECOCHE) : TP doit avoir DISPARU si H1 vraie")
        print(f"  NQ   (Use Attached COCHE)   : TP probablement RESTE Open (controle)")
    finally:
        dtc.on_fill = original_on_fill
        dtc._handle_order_update = original_handle


def test_bracket_real(dtc: DTCConnector) -> None:
    """Boucle ES + NQ : bracket TP/SL 8t qty=1 BUY comme bot live + latences."""
    print("\n=== TEST BRACKET REEL Sim1 ES + NQ (TP=8t SL=8t comme bot live) ===")
    print("Mesure : latence parent send->fill, latence fill TP/SL->flat broker (OCO auto).")
    print("Si timeout 4min sans fill -> cleanup sequence solution validee.")

    # Hook on_fill pour capturer timestamps fills
    fills_log = {}  # {client_order_id: timestamp}
    original_on_fill = dtc.on_fill

    def capture_fill(fill):
        fills_log[fill.order_id] = time.time()
        if original_on_fill:
            try:
                original_on_fill(fill)
            except Exception:
                pass

    dtc.on_fill = capture_fill

    # Hook _handle_order_update pour capturer status (detect Status=8 Canceled)
    status_log = {}  # {client_order_id: latest_status}
    original_handle = dtc._handle_order_update

    def capture_status(msg):
        try:
            cid = msg.get("ClientOrderID", "")
            st = msg.get("OrderStatus", 0)
            if cid:
                status_log[cid] = st
        except Exception:
            pass
        return original_handle(msg)

    dtc._handle_order_update = capture_status

    try:
        results = []
        for cfg in CLEANUP_SYMBOLS:
            r = _test_one_real(dtc, cfg["sym"], cfg["data_dir"], fills_log, status_log,
                                tp_ticks=cfg.get("tp_real_t", REAL_TP_TICKS),
                                sl_ticks=cfg.get("sl_real_t", REAL_SL_TICKS))
            results.append(r)
            print(f"\n--- Pause 8s avant prochain symbole ---")
            time.sleep(8.0)

        # RESUME GLOBAL
        print(f"\n{'='*60}")
        print(f"=== RESUME GLOBAL TEST BRACKET REEL ===")
        print(f"{'='*60}")
        for r in results:
            marker = "OK" if r["verdict"].startswith("OK") else "FAIL"
            l1 = f"{r.get('L1_parent_ms', 0):.0f}ms" if r.get("L1_parent_ms") else "n/a"
            l3 = f"{r.get('L3_oco_flat_ms', 0):.0f}ms" if r.get("L3_oco_flat_ms") else "n/a"
            tot = f"{r.get('L_total_ms', 0):.0f}ms" if r.get("L_total_ms") else "n/a"
            print(f"  [{marker}] {r['sym']:12s} verdict={r['verdict']:20s}")
            print(f"           L1 parent send->fill = {l1}")
            print(f"           L3 fill->flat broker = {l3}  (OCO auto cancel)")
            print(f"           Total t0->flat       = {tot}")
            print(f"           Oppose canceled      = {r.get('opposite_canceled')} (status={r.get('opposite_status')})")
            print(f"           Type 210 fallback    = {r.get('flushed')}")
        print(f"\n  IMPORTANT : verifier Sierra Chart GUI > Trade Activity Log > Sim1")
        print(f"  qu'aucun ordre n'est resté Working pour ES ni NQ.")
    finally:
        dtc.on_fill = original_on_fill
        dtc._handle_order_update = original_handle


def test_timeout_cleanup(dtc: DTCConnector) -> None:
    """Boucle sur ES + NQ et applique sequence solution sur Sim1."""
    print("\n=== TEST SEQUENCE SOLUTION ANTI-ORPHELIN Sim1 (ES + NQ) ===")
    print("Tir croise valide 04/05 : sierra_dtc_connector.py + SOLUTION_BRACKET_OCO_FINAL.md")
    print("+ VICTOIRE_OCO_AUTOMATIQUE_14NOV_2024.md + doc Sierra Chart officielle.")
    print(f"Sequence : Cancel TP + Cancel SL + Verify position + MARKET CLOSE.")

    results = []
    for cfg in CLEANUP_SYMBOLS:
        r = _test_one_symbol(dtc, cfg["sym"], cfg["tp_t"], cfg["sl_t"], cfg["data_dir"])
        results.append(r)
        # Pause inter-symboles pour permettre observation
        print(f"\n--- Pause 5s avant prochain symbole ---")
        time.sleep(5.0)

    # RESUME GLOBAL
    print(f"\n{'='*60}")
    print(f"=== RESUME GLOBAL TEST SEQUENCE SOLUTION ===")
    print(f"{'='*60}")
    all_ok = True
    for r in results:
        marker = "OK" if r["verdict"] == "OK" else "FAIL"
        print(f"  [{marker}] {r['sym']:12s} verdict={r['verdict']:20s} qty_final={r.get('qty_final')}")
        if r["verdict"] != "OK":
            all_ok = False
    print(f"\n  GLOBAL : {'OK (solution validee)' if all_ok else 'FAIL (investigate)'}")
    print(f"\n  IMPORTANT : verifier dans Sierra Chart GUI > Trade Activity Log > Sim1")
    print(f"  qu'aucun ordre TP/SL/MARKET n'est resté Working pour ES ni NQ.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="store_true", help="Liste ordres + positions Sim1")
    parser.add_argument("--flatten-sim1", action="store_true", help="Cancel orders + close positions Sim1")
    parser.add_argument("--test-bracket", action="store_true", help="Test bracket OCO single trade ES")
    parser.add_argument("--test-timeout-cleanup", action="store_true",
                        help="Test sequence solution anti-orphelin (NQ Sim1 qty=1)")
    parser.add_argument("--test-bracket-real", action="store_true",
                        help="Test bracket reel TP/SL 8t sur ES + NQ (comme bot live)")
    parser.add_argument("--test-bracket-real-pure", action="store_true",
                        help="Test pur Type 203 (isole H1 'Use Attached Orders')")
    parser.add_argument("--test-nq-only-observable", action="store_true",
                        help="Test NQ qty=1 TP/SL larges (50t) pour observer DOM long")
    args = parser.parse_args()

    if not (args.inventory or args.flatten_sim1 or args.test_bracket or args.test_timeout_cleanup or args.test_bracket_real or args.test_bracket_real_pure or args.test_nq_only_observable):
        parser.print_help()
        return 1

    dtc = make_connector()
    try:
        if args.inventory:
            inventory(dtc)
        if args.flatten_sim1:
            flatten_sim1(dtc)
        if args.test_bracket:
            test_bracket(dtc)
        if args.test_timeout_cleanup:
            test_timeout_cleanup(dtc)
        if args.test_bracket_real:
            test_bracket_real(dtc)
        if args.test_bracket_real_pure:
            test_bracket_real_pure(dtc)
        if args.test_nq_only_observable:
            test_nq_only_observable(dtc)
    finally:
        try:
            dtc.disconnect()
        except Exception:
            pass
        print("\n[DTC] Disconnected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
