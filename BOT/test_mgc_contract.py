"""
Test contract MGC Sim Sierra Chart — Phase 0.3.d (11/05/2026)

Objectif : valider que `MGCM26-CMECOMEX` est le bon contract identifier accepte
par Sierra Chart DTC server. Si le contract est mal nomme, SC retourne
ORDER_REJECT avec message d'erreur lisible.

Methodologie BLINDEE :
  1. Send LIMIT order TRES LOIN du marche (jamais filled)
     - Pour MGC ~4700 prix : on envoie LIMIT BUY @ $1000 (jamais executable)
  2. Attendre ORDER_UPDATE response (~3s)
  3. Verifier OrderStatus :
     - 2 (Open) = contract accepted by SC -> SUCCESS
     - REJECT (typically negative status) = contract rejected -> FAIL avec raison
  4. Cancel immediatement l'ordre (anti-orphan)
  5. Verify cancel propagated (status=8)

Risk minimal :
  - LIMIT $1000 vs prix marche ~$4700 = ecart 80% = jamais filled
  - Cancel immediat 2s apres send
  - TradeAccount = Sim3 par defaut (paper, jamais real money)
  - Pas de bracket SL/TP (juste parent order test)

Usage :
  python -X utf8 BOT/test_mgc_contract.py
  python -X utf8 BOT/test_mgc_contract.py --trade-account Sim2
  python -X utf8 BOT/test_mgc_contract.py --limit-price 1500  # custom limit
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "CORE"))

from dtc_connector import DTCConnector, BUY, LIMIT
from bot_config import INSTRUMENTS, DTCConfig


def test_mgc_contract(limit_price: float = 1000.0,
                       trade_account: str = "Sim3",
                       wait_seconds: float = 3.0) -> dict:
    """Test contract MGC via LIMIT order Sim hors-marche.

    Args:
        limit_price : prix LIMIT (default $1000, far below MGC ~$4700)
        trade_account : Sim3 (Bot 1) / Sim2 (Bot 2) / Sim1 (Bot 3)
        wait_seconds : attente ORDER_UPDATE response

    Returns:
        dict avec result : {success, status, contract, raison?}
    """
    contract = INSTRUMENTS["MGC"].contract  # MGCM26-CMECOMEX
    tick_size = INSTRUMENTS["MGC"].tick_size  # 0.10

    print(f"=== Test contract MGC ===")
    print(f"  Contract: {contract}")
    print(f"  Tick size: {tick_size}")
    print(f"  LIMIT price: ${limit_price} (vs marche ~$4700 -> jamais filled)")
    print(f"  TradeAccount: {trade_account}")
    print()

    # Connect DTC
    cfg = DTCConfig()
    dtc = DTCConnector(cfg)
    if not dtc.connect():
        return {"success": False, "raison": "DTC connect failed"}

    print(f"[OK] DTC connected")

    try:
        # Envoie LIMIT BUY @ $1000 (jamais filled car prix marche ~$4700)
        # Pas de bracket SL/TP (test contract seul, pas execution complete)
        cid = f"MGC_CONTRACT_TEST_{int(time.time()) % 100000}"
        print(f"[SEND] LIMIT BUY 1 contract {contract} @ ${limit_price} cid={cid}")

        # Note : send_market_order envoie un MARKET. Pour LIMIT, faut une autre fonction.
        # On regarde si DTCConnector a une send_limit_order ou similaire.
        # Sinon, fallback : envoie MARKET 1 contract -> fill prix marche -> cancel/flatten
        # MAIS risque position residuelle si cancel timing fail.
        #
        # CHOIX SAFE : envoyer un LIMIT via _send raw DTC message (Type 208 + OrderType=LIMIT).
        # Cf BOT/dtc_connector.py code pour structure attendue.

        # Pour ce test on utilise un _send raw avec OrderType=LIMIT_ORDER (2)
        msg = {
            "Type": 208,  # SUBMIT_NEW_SINGLE_ORDER
            "ClientOrderID": cid,
            "Symbol": contract,
            "Exchange": "COMEX",  # MGC = COMEX, pas CME
            "TradeAccount": trade_account,
            "BuySell": 1,         # 1=BUY, 2=SELL (DTC enum int)
            "OrderType": LIMIT,   # LIMIT=2 (DTC enum int, pas string)
            "Price1": limit_price,
            "Quantity": 1,
            "TimeInForce": 1,     # 1=DAY (DTC enum int)
            "OpenCloseTrade": 1,  # 1=OPEN
            "IsAutomatedOrder": 1,
        }
        send_ok = dtc._send(msg)
        if not send_ok:
            return {"success": False, "raison": "DTC _send failed", "contract": contract}

        print(f"[SENT] Awaiting ORDER_UPDATE response ({wait_seconds}s)...")
        time.sleep(wait_seconds)

        # Check si on a recu une ORDER_UPDATE pour ce cid
        # Le _recv_loop populise dtc._order_updates ou similaire
        order_state = None
        if hasattr(dtc, "_order_updates"):
            order_state = dtc._order_updates.get(cid)
        elif hasattr(dtc, "_orders"):
            order_state = dtc._orders.get(cid)

        if order_state:
            status = order_state.get("OrderStatus") or order_state.get("status")
            print(f"[RESPONSE] OrderStatus={status} for cid={cid}")
            print(f"  Full state: {order_state}")
        else:
            print(f"[WARN] Aucune ORDER_UPDATE recue pour cid={cid} (timeout {wait_seconds}s)")
            print(f"      Possible reject silencieux (check Sierra Chart Trade Activity Log)")
            status = None

        # Cancel immediatement (anti-orphan)
        print(f"[CANCEL] {cid} (anti-orphan)")
        cancel_ok = dtc.cancel_order(cid, trade_account=trade_account)
        print(f"[CANCEL] result: {cancel_ok}")

        # Verify cancel propagated
        time.sleep(1.5)
        if hasattr(dtc, "_order_updates"):
            final_state = dtc._order_updates.get(cid, {})
            final_status = final_state.get("OrderStatus")
            print(f"[FINAL] status={final_status} (8=Cancelled)")

        # Verdict
        if status == 2:
            return {"success": True, "status": "OPEN", "contract": contract,
                    "raison": "Sierra Chart a accepte le contract"}
        elif status == 8:
            return {"success": True, "status": "CANCELLED", "contract": contract,
                    "raison": "Order accepte puis cancelled (contract valide)"}
        elif status is None:
            return {"success": False, "status": "NO_RESPONSE", "contract": contract,
                    "raison": "Pas de ORDER_UPDATE - check SC log"}
        else:
            return {"success": False, "status": status, "contract": contract,
                    "raison": f"Status inattendu {status}"}

    finally:
        # Anti-orphan : retry cancel si pas confirme
        try:
            dtc.cancel_order(cid, trade_account=trade_account)
        except Exception:
            pass
        dtc.disconnect()
        print(f"[OK] DTC disconnected")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-price", type=float, default=1000.0,
                        help="LIMIT price (default $1000, far below market)")
    parser.add_argument("--trade-account", default="Sim3",
                        help="Sim3/Sim2/Sim1 (default Sim3 = Bot 1 paper)")
    parser.add_argument("--wait", type=float, default=3.0,
                        help="Wait seconds for ORDER_UPDATE")
    args = parser.parse_args()

    result = test_mgc_contract(
        limit_price=args.limit_price,
        trade_account=args.trade_account,
        wait_seconds=args.wait,
    )

    print()
    print("=" * 60)
    print(f"=== VERDICT ===")
    print(f"  Success : {result['success']}")
    print(f"  Status  : {result.get('status', 'N/A')}")
    print(f"  Contract: {result.get('contract', 'N/A')}")
    print(f"  Raison  : {result.get('raison', 'N/A')}")
    print("=" * 60)

    if result["success"]:
        print()
        print("[GO] Contract MGC valide. Bot peut envoyer ordres sur MGCM26-CMECOMEX.")
        sys.exit(0)
    else:
        print()
        print("[NOGO] Contract MGC NOT validated. Check Sierra Chart logs :")
        print("  Trade Activity Log (Window > Trade Activity Log)")
        print("  Cherche dernieres minutes les rejet 'Symbol invalid' ou 'Account invalid'")
        print()
        print("Alternatives a tester si NOGO :")
        print("  - MGCM26-COMEX (sans CMECOMEX suffix)")
        print("  - MGCM26 (court)")
        print("  - MGC.M26-CMECOMEX (avec dot)")
        sys.exit(1)


if __name__ == "__main__":
    main()
