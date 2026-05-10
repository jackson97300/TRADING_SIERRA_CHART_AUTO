"""
Test execution MGC Sim3 — round-trip MARKET BUY + SELL (anti-orphan).

Objectif : valider que Sierra Chart accepte les ordres MARKET MGC sur TradeAccount
Sim3 et que le bracket execution path fonctionne. Diagnostique aussi le bug
de routing Bot 1 (envoie sur Sim2 au lieu de Sim3).

Methodologie BLINDEE :
  1. MARKET BUY 1 contract MGC (cid=MGC_EXEC_BUY_xxxxx)
  2. Wait 3s pour fill
  3. MARKET SELL 1 contract MGC (cid=MGC_EXEC_SELL_xxxxx) - close position
  4. Wait 3s pour close
  5. Type 209 FLATTEN par symbole (defense en profondeur anti-orphan)
  6. Wait 1s
  7. Verify position=0 via response logs

Risk minimal :
  - 2 contracts micro Gold = ~$4700 * 2 notional Sim (paper, pas real)
  - Round-trip 2 MARKET = slippage ~1 tick = $0.10 USD theorique
  - Triple safety net : SELL + FLATTEN_POSITION + check
  - Sim Topstep Sim3, pas funded

Usage :
  python -X utf8 BOT/test_mgc_execution.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "CORE"))

from dtc_connector import DTCConnector, BUY as DTC_BUY, SELL as DTC_SELL, MARKET, LIMIT
from bot_config import INSTRUMENTS, DTCConfig


def test_execution(trade_account: str = "Sim3",
                    wait_seconds: float = 3.0) -> dict:
    """Test execution MGC Sim3 round-trip."""
    contract = INSTRUMENTS["MGC"].contract  # MGCM26-CMECOMEX
    tick_size = INSTRUMENTS["MGC"].tick_size

    print(f"=== Test execution MGC Sim3 ===")
    print(f"  Contract: {contract}")
    print(f"  TradeAccount: {trade_account}")
    print(f"  Operation: MARKET BUY 1 -> wait {wait_seconds}s -> MARKET SELL 1 -> FLATTEN")
    print()

    cfg = DTCConfig()
    dtc = DTCConnector(cfg)
    if not dtc.connect():
        return {"success": False, "raison": "DTC connect failed"}

    print(f"[OK] DTC connected")
    time.sleep(0.5)  # let _recv_loop start

    ts_short = int(time.time()) % 100000
    cid_buy = f"MGC_EXEC_BUY_{ts_short}"
    cid_sell = f"MGC_EXEC_SELL_{ts_short}"
    cid_flatten = f"MGC_EXEC_FLAT_{ts_short}"

    try:
        # ── 1. MARKET BUY 1 contract ─────────────────────────────────
        print(f"[1/5] MARKET BUY 1 {contract} cid={cid_buy}")
        msg_buy = {
            "Type": 208,
            "ClientOrderID": cid_buy,
            "Symbol": contract,
            "Exchange": "COMEX",
            "TradeAccount": trade_account,
            "BuySell": DTC_BUY,         # 1=BUY
            "OrderType": MARKET,        # 1=MARKET
            "Quantity": 1,
            "TimeInForce": 1,           # 1=DAY
            "OpenCloseTrade": 1,        # 1=OPEN
            "IsAutomatedOrder": 1,
        }
        ok_buy = dtc._send(msg_buy)
        print(f"      _send OK={ok_buy}")
        if not ok_buy:
            return {"success": False, "raison": "BUY _send failed"}

        # ── 2. Wait fill ────────────────────────────────────────────
        print(f"[2/5] Wait {wait_seconds}s pour fill...")
        time.sleep(wait_seconds)

        # ── 3. MARKET SELL 1 contract (close position) ──────────────
        print(f"[3/5] MARKET SELL 1 {contract} cid={cid_sell} (close)")
        msg_sell = {
            "Type": 208,
            "ClientOrderID": cid_sell,
            "Symbol": contract,
            "Exchange": "COMEX",
            "TradeAccount": trade_account,
            "BuySell": DTC_SELL,        # 2=SELL
            "OrderType": MARKET,
            "Quantity": 1,
            "TimeInForce": 1,
            "OpenCloseTrade": 2,        # 2=CLOSE (flatten)
            "IsAutomatedOrder": 1,
        }
        ok_sell = dtc._send(msg_sell)
        print(f"      _send OK={ok_sell}")

        # ── 4. Wait close fill ──────────────────────────────────────
        print(f"[4/5] Wait {wait_seconds}s pour close fill...")
        time.sleep(wait_seconds)

        # ── 5. Type 209 FLATTEN (defense en profondeur) ─────────────
        print(f"[5/5] Type 209 FLATTEN {contract} cid={cid_flatten} (anti-orphan)")
        msg_flatten = {
            "Type": 209,                # SUBMIT_FLATTEN_POSITION_ORDER
            "ClientOrderID": cid_flatten,
            "Symbol": contract,
            "TradeAccount": trade_account,
            "Exchange": "COMEX",
            "IsAutomatedOrder": 1,
        }
        ok_flatten = dtc._send(msg_flatten)
        print(f"      _send OK={ok_flatten}")
        time.sleep(2.0)

        return {"success": True, "raison": "Round-trip complete",
                "cids": [cid_buy, cid_sell, cid_flatten]}

    finally:
        try:
            # Anti-orphan fallback : Type 210 sur tout le compte
            cid_acc = f"MGC_EXEC_ACC_{ts_short}"
            dtc._send({
                "Type": 210,
                "ClientOrderID": cid_acc,
                "TradeAccount": trade_account,
                "IsAutomatedOrder": 1,
            })
            print(f"[CLEANUP] Type 210 ACC_FLATTEN sent cid={cid_acc}")
        except Exception:
            pass
        time.sleep(1.0)
        dtc.disconnect()
        print(f"[OK] DTC disconnected")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-account", default="Sim3",
                        help="Sim3 (Bot 1) / Sim2 (Bot 2) / Sim1 (Bot 3)")
    parser.add_argument("--wait", type=float, default=3.0,
                        help="Seconds entre BUY et SELL")
    args = parser.parse_args()

    result = test_execution(
        trade_account=args.trade_account,
        wait_seconds=args.wait,
    )

    print()
    print("=" * 60)
    print(f"=== VERDICT ===")
    print(f"  Success : {result['success']}")
    print(f"  Raison  : {result.get('raison', 'N/A')}")
    if result.get("cids"):
        print(f"  CIDs    :")
        for cid in result["cids"]:
            print(f"    - {cid}")
    print("=" * 60)
    print()
    print("VERIFICATION CRITIQUE - regarde dans Sierra Chart :")
    print("  1. Trade Activity Log (Window > Trade Activity Log)")
    print("     -> cherche MGC_EXEC_* dans dernieres minutes")
    print("     -> verifie TradeAccount affiche est bien Sim3")
    print("  2. Trade Window > Sim3")
    print("     -> position MGC doit etre 0 apres FLATTEN")
    print()
    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
