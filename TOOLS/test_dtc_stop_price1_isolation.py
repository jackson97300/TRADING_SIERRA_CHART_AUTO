"""Test isolation VERBOSE post-revert Price1 (10/06/2026 v2).

Envoie 1 bracket NQ Sim1 qty=1 minimal puis :
  - Query Type 300 OPEN_ORDERS pour voir ce que SC enregistre
  - Affiche Price1 / Price2 / StopPrice / OrderType pour chaque ordre Working
  - Garde 30s pour observation manuelle Trade Orders Window
  - Auto cleanup : cancel TP + SL + MARKET CLOSE position

PREUVE DEFINITIVE :
  - Si SL STOP retourne Price1 == sl_price -> FIX VALIDE
  - Si SL STOP retourne Price1 == 0 ou absent -> bug persiste

Usage VPS :
  python -X utf8 C:\\TRADING_SIERRA_CHART_AUTO\\tools\\test_dtc_stop_price1_isolation.py
"""
from __future__ import annotations
import sys
import time
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "BOT"))

from BOT.dtc_connector import DTCConnector, BUY, SELL
from BOT.bot_config import DTCConfig

# Config test minimal
TRADE_ACCOUNT = "Sim1"
SYMBOL = "NQM26-CME"
QUANTITY = 1
SL_OFFSET_TICKS = 50
TP_OFFSET_TICKS = 100
TICK_SIZE = 0.25


def main():
    print("=" * 75)
    print("TEST ISOLATION VERBOSE SL Price1 REVERT (10/06/2026 v2)")
    print("=" * 75)

    cfg = DTCConfig(client_name="MIA_Bot_V2_ISOLATION_TEST_V2")
    dtc = DTCConnector(config=cfg)

    print("\n[1/6] Connexion DTC ...")
    try:
        ok = dtc.connect()
        if not ok:
            print("[FAIL] DTC connect impossible")
            return 1
    except Exception as e:
        print(f"[FAIL] DTC connect exception : {e}")
        return 1

    print("[OK] DTC connecte port 11099")
    time.sleep(1)

    ref_price = 28980.0
    sl_price = ref_price - SL_OFFSET_TICKS * TICK_SIZE
    tp_price = ref_price + TP_OFFSET_TICKS * TICK_SIZE

    print(f"\n[2/6] Envoi bracket BUY NQ Sim1 qty={QUANTITY} :")
    print(f"      Entry MARKET (signal_ref={ref_price})")
    print(f"      TP LIMIT  @ {tp_price} (+{TP_OFFSET_TICKS}t)")
    print(f"      SL STOP   @ {sl_price} (-{SL_OFFSET_TICKS}t)")

    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=SYMBOL,
        side=BUY,
        quantity=QUANTITY,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=TRADE_ACCOUNT,
        signal_ref_price=ref_price,
        sl_ticks=SL_OFFSET_TICKS,
        tp_ticks=TP_OFFSET_TICKS,
        tick_size=TICK_SIZE,
    )

    if not parent_id:
        print("[FAIL] Parent NOT FILLED en 2s")
        dtc.disconnect()
        return 2

    print(f"\n[3/6] Bracket envoye :")
    print(f"      parent_cid = {parent_id}")
    print(f"      tp_cid     = {tp_cid}")
    print(f"      sl_cid     = {sl_cid}")
    print(f"\n      WAIT 3s pour propagation SC...")
    time.sleep(3)

    print("\n[4/6] QUERY Type 300 OPEN_ORDERS Sim1 -> ce que SC enregistre :")
    orders = dtc.request_open_orders_blocking(
        trade_account=TRADE_ACCOUNT,
        timeout=5.0,
    )

    if orders is None:
        print("[WARN] Query Type 300 timeout ou pas connecte")
    elif not orders:
        print("[WARN] Aucun ordre Working retourne par SC (cleanup en cours ?)")
    else:
        print(f"[OK] {len(orders)} ordre(s) Working trouve(s) :\n")
        for i, o in enumerate(orders, 1):
            ot = o.get("OrderType", "?")
            ot_label = {1: "MARKET", 2: "LIMIT", 3: "STOP", 4: "STOP_LIMIT"}.get(ot, f"?({ot})")
            print(f"  Ordre #{i} : ClientOrderID={o.get('ClientOrderID', '?')}")
            print(f"    OrderType    : {ot_label}")
            print(f"    BuySell      : {o.get('BuySell', '?')} (1=BUY 2=SELL)")
            print(f"    Symbol       : {o.get('Symbol', '?')}")
            print(f"    Price1       : {o.get('Price1', '?')}   <- LIMIT price OU STOP trigger")
            print(f"    Price2       : {o.get('Price2', '?')}   <- STOP_LIMIT limit price")
            print(f"    StopPrice    : {o.get('StopPrice', '?')} <- alias defensif")
            print(f"    Quantity     : {o.get('Quantity', '?')}")
            print(f"    OrderStatus  : {o.get('OrderStatus', '?')} (2=Open 4=Working)")
            print()

        # VERDICT FIX
        sl_order = next(
            (o for o in orders if o.get("ClientOrderID") == sl_cid), None
        )
        if sl_order:
            sl_price_sc = sl_order.get("Price1", 0)
            print("=" * 75)
            print("VERDICT FIX Price1 :")
            print(f"  Envoye  : Price1 = {sl_price}")
            print(f"  SC voit : Price1 = {sl_price_sc}")
            if abs(float(sl_price_sc) - sl_price) < 0.01:
                print("  >>> FIX VALIDE EMPIRIQUEMENT <<<")
            else:
                print("  >>> BUG PERSISTE - investiguer <<<")
            print("=" * 75)

    print("\n[5/6] Garde connexion 30s pour observation manuelle Trade Orders SC...")
    print("      Jackson : ouvre Trade Orders Window Sim1 + colonne Price")
    time.sleep(30)

    print("\n[6/6] CLEANUP auto : cancel TP + SL + flatten position")
    try:
        dtc.cancel_order(tp_cid, trade_account=TRADE_ACCOUNT)
        time.sleep(0.5)
        dtc.cancel_order(sl_cid, trade_account=TRADE_ACCOUNT)
        time.sleep(0.5)

        # MARKET CLOSE: SELL +1 (LONG fermeture)
        close_cid = f"MIA_CLOSE_TEST_{int(time.time())}"
        dtc._send({
            "Type": 208,
            "Symbol": SYMBOL,
            "ClientOrderID": close_cid,
            "OrderType": 1,  # MARKET
            "BuySell": SELL,
            "Quantity": QUANTITY,
            "TradeAccount": TRADE_ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,
            "TimeInForce": 0,
        })
        print(f"[OK] MARKET CLOSE envoye cid={close_cid}")
        time.sleep(2)
    except Exception as e:
        print(f"[WARN] Cleanup exception : {e}")

    print("\nDeconnexion DTC")
    dtc.disconnect()
    print("\n[FIN] Test termine. Verifier que position Sim1 NQM26 = 0 dans SC GUI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
