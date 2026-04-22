"""Smoke test Phase 0 : envoi 1 bracket ES Sim3 + fill + OCO + close.

Test isole : n'importe PAS mia_paper_trader.py, teste juste la plomberie
BOT/dtc_connector.py contre Sierra Chart Sim3 en live.

Validations attendues :
- Connect DTC OK
- Subscribe ES market data
- Bracket BUY 1 micro ES (SL -5t, TP +10t)
- Parent fill status=7 recu via _parent_fill_events wait(timeout=2s)
- TP + SL envoyes avec SUCCESS visible dans SC Trade > Open Orders
- Fill TP ou SL -> OCO cancel auto via _handle_order_update
- Zero ordre residuel apres

Usage :
    python -u -X utf8 CORE/research/smoke_dtc_paper_integration.py --symbol ES --qty 1 --sl 5 --tp 10 --side BUY
"""
import argparse
import os
import sys
import time
import threading
from pathlib import Path

# BOT/ path + import
BOT_DIR = str(Path(__file__).resolve().parent.parent.parent / "BOT")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from dtc_connector import DTCConnector, BUY, SELL
from bot_config import DTCConfig, INSTRUMENTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ES", choices=["ES", "NQ"])
    parser.add_argument("--qty", type=int, default=1)
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--sl", type=int, default=5, help="SL en ticks depuis prix actuel")
    parser.add_argument("--tp", type=int, default=10, help="TP en ticks depuis prix actuel")
    parser.add_argument("--trade-account", default=os.environ.get("MIA_TRADE_ACCOUNT", "Sim3"))
    parser.add_argument("--wait", type=int, default=60, help="Timeout total avant cancel (sec)")
    args = parser.parse_args()

    if not args.trade_account.lower().startswith("sim"):
        raise RuntimeError(f"trade_account={args.trade_account} doit commencer par Sim")

    contract = INSTRUMENTS[args.symbol].contract
    tick_size = 0.25
    print(f"=== SMOKE TEST DTC PAPER ===")
    print(f"  contract     : {contract}")
    print(f"  side         : {args.side}")
    print(f"  qty          : {args.qty} micro")
    print(f"  trade_account: {args.trade_account}")
    print(f"  SL / TP      : -{args.sl}t / +{args.tp}t (depuis bid/ask)")

    dtc = DTCConnector(DTCConfig())
    fill_events = {"received": []}

    def on_fill(fill):
        print(f"  >>> ON_FILL received : order_id={fill.order_id} "
              f"price={fill.fill_price:.2f} symbol={fill.symbol} "
              f"side={fill.side} is_filled={fill.is_filled}")
        fill_events["received"].append(fill)

    dtc.on_fill = on_fill

    print("\n[1] Connect DTC ...")
    if not dtc.connect():
        raise RuntimeError("DTC connect failed")
    print(f"    connected={dtc.connected} host={dtc.cfg.host}:{dtc.cfg.port}")

    print("\n[2] Subscribe market data ...")
    dtc.subscribe_market_data(contract)
    time.sleep(2)  # laisser le prix arriver
    last_prices = dtc._last_prices.get(contract, {})
    last = last_prices.get("last") or last_prices.get("bid") or 0
    print(f"    last_price {contract} = {last}")
    if not last or last <= 0:
        print("    !!! Pas de prix recu -> impossible de placer le bracket (need SC market open)")
        dtc.disconnect()
        return 1

    # Calcul SL/TP
    if args.side == "BUY":
        sl_price = round(last - args.sl * tick_size, 2)
        tp_price = round(last + args.tp * tick_size, 2)
        side_int = BUY
    else:
        sl_price = round(last + args.sl * tick_size, 2)
        tp_price = round(last - args.tp * tick_size, 2)
        side_int = SELL
    print(f"    target: entry~{last} SL={sl_price} TP={tp_price}")

    print("\n[3] Submit bracket ...")
    parent_id, tp_cid, sl_cid = dtc.send_market_order(
        symbol=contract,
        side=side_int,
        quantity=args.qty,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=args.trade_account,
    )
    if not parent_id:
        print("    !!! Bracket FAILED (parent timeout ou reject)")
        dtc.disconnect()
        return 1
    print(f"    parent={parent_id} tp={tp_cid} sl={sl_cid}")

    print(f"\n[4] Attendre {args.wait}s pour fill TP/SL (ou cancel manuel via SC)...")
    print(f"    Validation VISUELLE : ouvre Sierra Chart Trade > Trade Activity Log + Open Orders")
    print(f"    Tu dois voir : Parent MARKET filled, TP LIMIT @ {tp_price}, SL STOP @ {sl_price}")

    t0 = time.time()
    last_check = 0
    while time.time() - t0 < args.wait:
        time.sleep(2)
        # Status check toutes les 10s
        if time.time() - last_check > 10:
            last_check = time.time()
            fills = len(fill_events["received"])
            elapsed = int(time.time() - t0)
            print(f"    [{elapsed}s] fills_received={fills} ...")
        # Stop si >= 2 fills (parent + close) OU >= 3 (parent + TP + SL qui se cancel)
        if len(fill_events["received"]) >= 2:
            time.sleep(3)  # laisser OCO cancel propager
            break

    print(f"\n[5] Cleanup ...")
    # Cancel residuals au cas ou
    for cid in (tp_cid, sl_cid):
        if cid:
            try:
                dtc.cancel_order(cid, trade_account=args.trade_account)
            except Exception as e:
                print(f"    warn cancel {cid}: {e}")
    time.sleep(2)

    print(f"\n[6] Shutdown DTC ...")
    dtc.disconnect()
    print(f"\n=== TEST DONE === fills_total={len(fill_events['received'])}")
    print(f"    VERIF VISUELLE SC : Open Orders Sim3 = 0 ordre residuel ?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
