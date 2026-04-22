"""Smoke test DUAL Phase 0 : envoi 2 brackets simultanes ES + NQ Sim3.

Rejoue le test valide 02/04/2026 (test_oco_dual.py) mais via DTCConnector
(API unifiee, reutilisee par paper_trader). Teste :
- 2 brackets simultanes (ES + NQ)
- OCO manuel par instrument independant
- Threading : le recv_loop gere les 2 flux sans melange
- Fills asynchrones + cancel auto des opposites

Validations visuelles Sierra Chart :
- Trade > Trade Activity Log : 2 Parent MARKET (ES + NQ) status Filled
- Open Orders Sim3 : 4 ordres ouverts (ES TP, ES SL, NQ TP, NQ SL)
- Apres fill de l'un : son OCO oppose passe Cancelled auto

Usage :
    python -u -X utf8 CORE/research/smoke_dtc_dual_es_nq.py
    python -u -X utf8 CORE/research/smoke_dtc_dual_es_nq.py --sell   # SELL ES + SELL NQ
    python -u -X utf8 CORE/research/smoke_dtc_dual_es_nq.py --mixed  # BUY ES + SELL NQ
"""
import argparse
import os
import sys
import time
from pathlib import Path

BOT_DIR = str(Path(__file__).resolve().parent.parent.parent / "BOT")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from dtc_connector import DTCConnector, BUY, SELL
from bot_config import DTCConfig, INSTRUMENTS

TICK_SIZE = 0.25


def read_last_price_from_jsonl(symbol: str) -> float:
    """Lit le dernier prix depuis le JSONL DMP du jour (bypass DTC market data
    subscribe qui peut etre refuse par SC selon config 'Allow Market Data')."""
    import glob, json
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    data_dir = Path(__file__).resolve().parent.parent.parent / "DATA" / symbol
    pattern = str(data_dir / f"{date_str}_{symbol}.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        # Fallback : dernier JSONL disponible
        files = sorted(glob.glob(str(data_dir / f"*_{symbol}.jsonl")))
    if not files:
        return 0.0
    latest = files[-1]
    try:
        # Lire les dernieres lignes complete (seek + read newline-terminated)
        with open(latest, "rb") as f:
            f.seek(0, 2)
            filesize = f.tell()
            # Read last 16KB, suffisant pour >= 1 ligne JSON complete
            start = max(0, filesize - 16384)
            f.seek(start)
            tail_bytes = f.read()
        # Skip premiere ligne tronquee (peut couper au milieu)
        lines = tail_bytes.decode("utf-8", errors="ignore").splitlines()
        # On cherche la derniere ligne parseable
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                bar = json.loads(line)
                price = float(bar.get("price") or bar.get("bar_close") or 0)
                if price > 0:
                    return price
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return 0.0
    except Exception as e:
        print(f"  warn read_last_price({symbol}): {e}")
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL", "MIXED"],
                        help="BUY = BUY ES + BUY NQ | SELL = SELL ES + SELL NQ | MIXED = BUY ES + SELL NQ")
    parser.add_argument("--qty", type=int, default=1, help="Qty par instrument (default 1 micro)")
    parser.add_argument("--es-sl", type=int, default=5)
    parser.add_argument("--es-tp", type=int, default=10)
    parser.add_argument("--nq-sl", type=int, default=10)
    parser.add_argument("--nq-tp", type=int, default=20)
    parser.add_argument("--trade-account", default=os.environ.get("MIA_TRADE_ACCOUNT", "Sim3"))
    parser.add_argument("--wait", type=int, default=60)
    args = parser.parse_args()

    if not args.trade_account.lower().startswith("sim"):
        raise RuntimeError(f"trade_account={args.trade_account} doit commencer par Sim")

    # Sides selon mode
    if args.side == "BUY":
        es_side, nq_side = BUY, BUY
    elif args.side == "SELL":
        es_side, nq_side = SELL, SELL
    else:  # MIXED
        es_side, nq_side = BUY, SELL

    es_label = "BUY" if es_side == BUY else "SELL"
    nq_label = "BUY" if nq_side == BUY else "SELL"

    print("=" * 60)
    print(f"SMOKE TEST DUAL : {es_label} ES + {nq_label} NQ")
    print("=" * 60)
    print(f"  trade_account : {args.trade_account}")
    print(f"  qty/instrument: {args.qty} micro")
    print(f"  ES SL/TP      : -{args.es_sl}t / +{args.es_tp}t")
    print(f"  NQ SL/TP      : -{args.nq_sl}t / +{args.nq_tp}t (plus large car plus volatile)")
    print()

    # Connect
    dtc = DTCConnector(DTCConfig())
    fills = {"received": [], "timings": {}}
    t_start = time.time()

    def ts_ms():
        return f"{(time.time() - t_start)*1000:.0f}ms"

    def on_fill(fill):
        now = time.time()
        fills["timings"][fill.order_id] = now
        print(f"  [{ts_ms():>7}] >>> ON_FILL order={fill.order_id} sym={fill.symbol} "
              f"price={fill.fill_price:.2f} is_filled={fill.is_filled}")
        fills["received"].append(fill)

    dtc.on_fill = on_fill

    print(f"[{ts_ms():>7}] [1] Connect DTC ...")
    t_connect_start = time.time()
    if not dtc.connect():
        raise RuntimeError("DTC connect failed")
    connect_ms = (time.time() - t_connect_start) * 1000
    print(f"    connected OK ({connect_ms:.0f}ms) host={dtc.cfg.host}:{dtc.cfg.port}")

    # Prix via JSONL DMP (SC DTC refuse parfois subscribe_market_data, on utilise
    # la meme source que paper_trader en prod)
    print("\n[2] Lecture prix depuis JSONL DMP ...")
    es_last = read_last_price_from_jsonl("ES")
    nq_last = read_last_price_from_jsonl("NQ")
    print(f"    ES last = {es_last} | NQ last = {nq_last}")
    if not es_last or not nq_last:
        print("    !!! Pas de prix dans JSONL — DMP pas demarre ou fichier vide")
        dtc.disconnect()
        return 1

    # Calcul SL/TP par instrument
    def prices_for(side, last, sl_ticks, tp_ticks):
        if side == BUY:
            return (round(last - sl_ticks * TICK_SIZE, 2),
                    round(last + tp_ticks * TICK_SIZE, 2))
        else:
            return (round(last + sl_ticks * TICK_SIZE, 2),
                    round(last - tp_ticks * TICK_SIZE, 2))

    es_sl, es_tp = prices_for(es_side, es_last, args.es_sl, args.es_tp)
    nq_sl, nq_tp = prices_for(nq_side, nq_last, args.nq_sl, args.nq_tp)
    print(f"    ES {es_label}: entry~{es_last} SL={es_sl} TP={es_tp}")
    print(f"    NQ {nq_label}: entry~{nq_last} SL={nq_sl} TP={nq_tp}")

    # Submit 2 brackets
    print(f"\n[{ts_ms():>7}] [3] Submit bracket ES ...")
    t_es_submit = time.time()
    es_parent, es_tp_cid, es_sl_cid = dtc.send_market_order(
        symbol=INSTRUMENTS["ES"].contract,
        side=es_side,
        quantity=args.qty,
        sl_price=es_sl, tp_price=es_tp,
        trade_account=args.trade_account,
    )
    es_submit_ms = (time.time() - t_es_submit) * 1000
    if not es_parent:
        print(f"    !!! ES bracket FAILED ({es_submit_ms:.0f}ms)")
        dtc.disconnect()
        return 1
    print(f"    ES submitted total={es_submit_ms:.0f}ms (parent fill+TP+SL inclus)")
    print(f"    ES CIDs: parent={es_parent} tp={es_tp_cid} sl={es_sl_cid}")

    print(f"\n[{ts_ms():>7}] [4] Submit bracket NQ ...")
    t_nq_submit = time.time()
    nq_parent, nq_tp_cid, nq_sl_cid = dtc.send_market_order(
        symbol=INSTRUMENTS["NQ"].contract,
        side=nq_side,
        quantity=args.qty,
        sl_price=nq_sl, tp_price=nq_tp,
        trade_account=args.trade_account,
    )
    nq_submit_ms = (time.time() - t_nq_submit) * 1000
    if not nq_parent:
        print(f"    !!! NQ bracket FAILED ({nq_submit_ms:.0f}ms) — cleanup ES")
        for cid in (es_tp_cid, es_sl_cid):
            try:
                dtc.cancel_order(cid, trade_account=args.trade_account)
            except Exception:
                pass
        dtc.disconnect()
        return 1
    print(f"    NQ submitted total={nq_submit_ms:.0f}ms (parent fill+TP+SL inclus)")
    print(f"    NQ CIDs: parent={nq_parent} tp={nq_tp_cid} sl={nq_sl_cid}")

    # Resume latences
    print(f"\n[{ts_ms():>7}] === LATENCES RESUME ===")
    print(f"    ES submit -> fill complet : {es_submit_ms:.0f}ms")
    print(f"    NQ submit -> fill complet : {nq_submit_ms:.0f}ms")
    print(f"    Total 2 brackets          : {(es_submit_ms + nq_submit_ms):.0f}ms")

    print(f"\n[{ts_ms():>7}] [5] Monitoring {args.wait}s ...")
    print(f"    VALIDATION VISUELLE : ouvre Sierra Chart Trade > Open Orders (Sim3)")
    print(f"    Tu dois voir 4 ordres ouverts :")
    print(f"      ES {es_label} TP @ {es_tp} | SL @ {es_sl}")
    print(f"      NQ {nq_label} TP @ {nq_tp} | SL @ {nq_sl}")

    t0 = time.time()
    last_check = 0
    while time.time() - t0 < args.wait:
        time.sleep(1)
        if time.time() - last_check > 5:
            last_check = time.time()
            elapsed = int(time.time() - t0)
            print(f"    [{elapsed:>2}s] fills={len(fills['received'])}")
        if len(fills["received"]) >= 4:
            time.sleep(2)
            break

    print(f"\n[{ts_ms():>7}] [6] Cleanup : flatten positions + cancel brackets ...")
    # IMPORTANT : si positions encore ouvertes, envoyer un close market pour flatten
    # (sinon elles restent fantomes sur Sim3 apres script end)
    # On envoie close reverse AVANT cancel brackets (les cancels liberent ensuite)
    close_sides = {
        "ES": (SELL if es_side == BUY else BUY),
        "NQ": (SELL if nq_side == BUY else BUY),
    }
    close_cids = {}
    for sym, rev_side in close_sides.items():
        # Skip close si au moins 1 fill TP/SL deja recu pour ce symbol (OCO a fermé)
        prefix_tp = "MIA_TP_" + (es_tp_cid if sym == "ES" else nq_tp_cid).replace("MIA_TP_", "")
        prefix_sl = "MIA_SL_" + (es_sl_cid if sym == "ES" else nq_sl_cid).replace("MIA_SL_", "")
        has_close = any(f.order_id in (prefix_tp, prefix_sl) for f in fills["received"])
        if has_close:
            print(f"    {sym} deja ferme par OCO (TP ou SL fill), skip close market")
            continue
        try:
            cid, _, _ = dtc.send_market_order(
                symbol=INSTRUMENTS[sym].contract,
                side=rev_side,
                quantity=args.qty,
                sl_price=0, tp_price=0,
                trade_account=args.trade_account,
            )
            close_cids[sym] = cid
            print(f"    {sym} close market envoye : cid={cid}")
        except Exception as e:
            print(f"    !!! {sym} close FAIL: {e}")

    time.sleep(1)

    # Cancel brackets residuels
    for cid in (es_tp_cid, es_sl_cid, nq_tp_cid, nq_sl_cid):
        if cid:
            try:
                dtc.cancel_order(cid, trade_account=args.trade_account)
            except Exception as e:
                print(f"    warn cancel {cid}: {e}")
    time.sleep(2)

    print(f"\n[{ts_ms():>7}] [7] Shutdown DTC ...")
    dtc.disconnect()

    total_elapsed = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"RESULTAT")
    print(f"  Duree totale test      : {total_elapsed:.1f}s")
    print(f"  Fills total recus      : {len(fills['received'])}")
    print(f"  ES submit -> fill brackets : {es_submit_ms:.0f}ms")
    print(f"  NQ submit -> fill brackets : {nq_submit_ms:.0f}ms")
    print(f"  Close market envoyes   : {list(close_cids.keys())}")
    print(f"")
    print(f"  VALIDATIONS attendues Sierra Chart Sim3 :")
    print(f"    1. Trade Activity Log : 2 parents MARKET Filled + closes (si envoyes)")
    print(f"    2. Open Orders : 0 ordre residuel")
    print(f"    3. Positions Sim3 : FLAT (pas de LONG residuel)")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
