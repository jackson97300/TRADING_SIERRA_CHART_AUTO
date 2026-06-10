"""flatten_bot.py — Flatten urgent positions par bot (1/2/3).

Suit sequence anti-orphelin V2 (orphan-prevention.md) :
  1. Query Type 300 OPEN_ORDERS pour chaque symbole + cancel via Type 203
  2. Query Type 305 position + MARKET CLOSE Type 208 si qty != 0
  3. Type 209 SUBMIT_FLATTEN_POSITION_ORDER par symbole avec ClientOrderID
  4. Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (nuclear option)
  5. Verify qty_final == 0

Etape 4 sprint stabilite Bot 3 v3 (09/06 soir BUG #4) :
  6. Apres flatten DTC OK, append event TRADE_CLOSE dans bot logger JSONL
     pour Bot 3 v3 (etape 2 deja deployee, state file persiste signal_id).
     Synchronise dashboard paper_tracker sans intervention manuelle.

Mapping bot -> trade_account (CLAUDE.md + bot3_config) :
  Bot 1 DMP : Sim3
  Bot 2 V6  : Sim2
  Bot 3 MP  : Sim1 (dedie via TRADE_ACCOUNT_BOT3)

Usage :
  python -X utf8 CORE/flatten_bot.py --bot 1
  python -X utf8 CORE/flatten_bot.py --bot 2
  python -X utf8 CORE/flatten_bot.py --bot 3
  python -X utf8 CORE/flatten_bot.py --bot all
  python -X utf8 CORE/flatten_bot.py --bot 3 --symbol ES   # flatten ES sur Sim1 uniquement
  python -X utf8 CORE/flatten_bot.py --bot 3 --symbol NQ   # flatten NQ sur Sim1 uniquement
"""
import argparse
import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BOT_TO_ACCOUNT = {
    # 03/06 FIX MAPPING : alignment avec naming dashboard refacto archi 28/05.
    # Avant ce fix : "1"->Sim3, "3"->Sim1 (legacy avant refacto). Le bouton FLATTEN
    # dashboard "Bot 1" (Sim1) appelait API bot_id="1" -> flatten Sim3 (mauvais Sim).
    # Apres : aligne avec convention dashboard.js _currentBotIdForApi() ("bot1"->"1").
    "1": "Sim1",   # Bot 1 v3 NQ Wyckoff + MP (etait Sim3, mismatch corrige)
    "2": "Sim2",   # Bot 2 BN V5 NQ+ES
    "3": "Sim3",   # Bot 3 v4 NQ data-driven (etait Sim1, mismatch corrige)
    "4": "Sim4",   # Bot 4 MIA Paper Trader (ajoute 03/06 - manquant avant)
}

SYMBOLS = {
    "ES": "ESM26-CME",
    "NQ": "NQM26-CME",    # Rollback 03/06 : 1 NQ E-mini
    "MGC": "MGCM26-CME",
}


def _connect(host="127.0.0.1", port=11099, timeout=10):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def _send(s, m):
    s.sendall(json.dumps(m).encode() + b"\x00")


def _recv(s, t=2):
    msgs, buf, end = [], b"", time.time() + t
    while time.time() < end:
        s.settimeout(max(0.1, end - time.time()))
        try:
            c = s.recv(65536)
            if not c:
                break
            buf += c
            while b"\x00" in buf:
                idx = buf.find(b"\x00")
                raw = buf[:idx]
                buf = buf[idx + 1:]
                if raw:
                    try:
                        msgs.append(json.loads(raw.decode("utf-8", "ignore")))
                    except json.JSONDecodeError:
                        pass
        except socket.timeout:
            break
    return msgs


def flatten_account(trade_account: str, only_symbol: str | None = None) -> dict:
    """Flatten toutes positions + working orders pour un compte donne.

    Args:
        trade_account: Sim1 / Sim2 / Sim3
        only_symbol: si specifie (ES/NQ/MGC), flatten uniquement ce symbole.
                     Sinon flatten les 3.

    Returns: {symbol: {qty_init, qty_final, working_canceled, status}}
    """
    s = _connect()
    _send(s, {"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10,
              "ClientName": f"FLAT_{trade_account}"})
    time.sleep(1)
    _recv(s, 2)

    results = {}
    scope = f"sym={only_symbol}" if only_symbol else "ALL_SYMBOLS"
    print(f"\n=== FLATTEN {trade_account} ({scope}) ===\n")

    target_symbols = SYMBOLS if only_symbol is None else {
        only_symbol: SYMBOLS[only_symbol]
    } if only_symbol in SYMBOLS else {}

    if only_symbol is not None and not target_symbols:
        raise ValueError(f"Symbol '{only_symbol}' invalid (expected one of {list(SYMBOLS)})")

    for sym, contract in target_symbols.items():
        print(f"--- {sym} ({contract}) ---")
        res = {"qty_init": 0, "qty_final": 0, "working_canceled": 0, "status": "OK"}

        # 1. Query open orders Type 300 + cancel Type 203
        _send(s, {"Type": 300, "RequestID": 100 + hash(sym) % 100,
                  "TradeAccount": trade_account})
        time.sleep(1)
        working = []
        for m in _recv(s, 2):
            if m.get("Type") == 301:
                sym_msg = str(m.get("Symbol", ""))
                status = m.get("OrderStatus")
                if sym in sym_msg and status in (2, 4):
                    working.append({
                        "client_order_id": m.get("ClientOrderID"),
                        "server_order_id": m.get("ServerOrderID"),
                    })
        for w in working:
            _send(s, {
                "Type": 203,
                "ClientOrderID": w["client_order_id"],
                "ServerOrderID": w["server_order_id"],
                "TradeAccount": trade_account,
            })
        res["working_canceled"] = len(working)
        print(f"  Working orders canceled: {len(working)}")
        if working:
            time.sleep(1)

        # 2. Query position Type 305 + flatten via Type 208 si qty != 0
        _send(s, {"Type": 305, "RequestID": 200 + hash(sym) % 100,
                  "TradeAccount": trade_account})
        time.sleep(1)
        qty = 0
        for m in _recv(s, 2):
            if m.get("Type") == 306 and sym in str(m.get("Symbol", "")):
                qty = m.get("Quantity", 0)
        res["qty_init"] = qty
        print(f"  Position {sym}: qty={qty}")

        if qty != 0:
            side = 1 if qty < 0 else 2  # SHORT->BUY, LONG->SELL
            abs_qty = abs(qty)
            flat_id = f"FLAT_{trade_account}_{sym}_{uuid.uuid4().hex[:6]}"
            print(f"  Sending {'BUY' if side == 1 else 'SELL'} MARKET {abs_qty} {contract}")
            _send(s, {
                "Type": 208, "Symbol": contract,
                "ClientOrderID": flat_id, "OrderType": 1,
                "BuySell": side, "Quantity": abs_qty,
                "TradeAccount": trade_account, "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2, "TimeInForce": 0,
            })
            time.sleep(2)

        # 3. Type 209 SUBMIT_FLATTEN_POSITION_ORDER avec ClientOrderID (defense)
        flush_cid = f"FLAT_{trade_account}_FLUSH_{sym}_{int(time.time()) % 100000}"
        _send(s, {
            "Type": 209, "ClientOrderID": flush_cid,
            "Symbol": contract, "TradeAccount": trade_account,
            "Exchange": "CME", "IsAutomatedOrder": 1,
        })
        time.sleep(1)

        # 4. Verify qty_final == 0
        _send(s, {"Type": 305, "RequestID": 300 + hash(sym) % 100,
                  "TradeAccount": trade_account})
        time.sleep(1)
        final_qty = 0
        for m in _recv(s, 2):
            if m.get("Type") == 306 and sym in str(m.get("Symbol", "")):
                final_qty = m.get("Quantity", 0)
        res["qty_final"] = final_qty
        res["status"] = "OK_FLAT" if final_qty == 0 else f"FAIL_qty={final_qty}"
        print(f"  Final {sym}: {res['status']}\n")
        results[sym] = res

    # 5. Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (nuclear)
    # Skip si only_symbol specifie (on touche pas aux autres positions du compte)
    if only_symbol is None:
        acct_cid = f"FLAT_{trade_account}_ACCT_{int(time.time()) % 100000}"
        _send(s, {
            "Type": 210, "ClientOrderID": acct_cid,
            "TradeAccount": trade_account, "IsAutomatedOrder": 1,
        })
        time.sleep(2)
        print(f"=== Type 210 sent (TradeAccount flush {trade_account}) ===")
    else:
        print(f"=== Type 210 skipped (symbol scope only) ===")

    s.close()
    return results


# ════════════════════════════════════════════════════════════════════════════
# ETAPE 4 SPRINT STABILITE BOT 3 V3 (09/06 soir) - BUG #4
# Auto-append TRADE_CLOSE dans bot logger JSONL apres flatten DTC OK
# pour synchroniser dashboard paper_tracker.
# ════════════════════════════════════════════════════════════════════════════

# Path racine pour state files + LOGS (calcule a partir de ce fichier).
ROOT_DIR = Path(__file__).resolve().parent.parent

# 09/06 SOIR Backlog R1 etape 4 : import logging_v2 best-effort pour emit
# FLATTEN_SYNC_APPENDED / FLATTEN_SYNC_SKIPPED (tracabilite audit J+1).
# Si import echoue (script standalone hors paper_v2 context) -> fallback no-op.
_v2log = None
try:
    sys.path.insert(0, str(ROOT_DIR / "CORE"))
    from logging_v2 import get_logger  # type: ignore
    _v2log = get_logger("flatten_bot", process="bot_legacy")
except Exception:
    pass  # silent fallback : emit deviendra no-op


def _emit(code: str, **ctx) -> None:
    """Helper emit best-effort via logging_v2 (no-op si module absent)."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception:
            pass

# Mapping trade_account -> {bot_name, log_dir, jsonl_prefix, state_file}.
# Etape 4 09/06 : focus Bot 3 v3 (Sim1, etape 2 deployee state persiste).
# Autres bots (Sim2/Sim3/Sim4) : pas encore de state file persistant
# = sync manuel via dashboard reste necessaire.
ACCOUNT_TO_BOT = {
    "Sim1": {
        "bot_name": "bot3_v3",
        "log_subdir": "bot3_v3",
        "jsonl_prefix": "bot3_v3_v1",
        "bot_version": "v3",
        "state_file": ROOT_DIR / "DATA" / "PAPER_TRADES" / "bot3_v3_state.json",
    },
    # Sim2/Sim3/Sim4 : a ajouter quand les bots Bot 1 PAPER / BN V5 / Bot 3 v4
    # auront leur PositionPersistance (sprint stabilite phase ulterieure).
}


def _load_open_positions_from_state(state_file: Path) -> dict:
    """Lit le state file Bot 3 v3 (cf. etape 2) pour extraire positions ouvertes.

    Return dict[sym, position_dict] ou {} si state file absent/corrompu.
    Best-effort : pas de raise (script standalone, tolerance maximale).
    """
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        positions = data.get("positions", {})
        return positions if isinstance(positions, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _append_trade_close_external(
    trade_account: str,
    symbol_scope: str,
    flatten_results: dict,
) -> dict:
    """Apres flatten DTC OK, append TRADE_CLOSE dans bot logger JSONL.

    Permet au dashboard paper_tracker de synchroniser sans intervention manuelle
    (BUG #4 09/06).

    Args:
        trade_account: ex "Sim1"
        symbol_scope: "NQ" / "ES" / "MGC" / "ALL"
        flatten_results: output flatten_account (dict {sym: {qty_init, qty_final, status, ...}})

    Return: dict {appended: list[signal_id], skipped: list[reason], errors: list[str]}
    """
    result = {"appended": [], "skipped": [], "errors": []}

    if trade_account not in ACCOUNT_TO_BOT:
        reason = f"trade_account_{trade_account}_not_in_ACCOUNT_TO_BOT_mapping"
        result["skipped"].append(reason)
        _emit("FLATTEN_SYNC_SKIPPED",
              trade_account=trade_account, symbol=symbol_scope, reason=reason)
        return result

    bot_cfg = ACCOUNT_TO_BOT[trade_account]
    state_file = bot_cfg["state_file"]
    positions = _load_open_positions_from_state(state_file)
    if not positions:
        reason = f"no_open_positions_in_state_file_{state_file.name}"
        result["skipped"].append(reason)
        _emit("FLATTEN_SYNC_SKIPPED",
              trade_account=trade_account, symbol=symbol_scope, reason=reason)
        return result

    # Determine quels symboles ont ete reellement flatten
    if symbol_scope == "ALL":
        target_symbols = list(positions.keys())
    else:
        target_symbols = [symbol_scope] if symbol_scope in positions else []

    if not target_symbols:
        reason = f"no_open_positions_match_scope_{symbol_scope}"
        result["skipped"].append(reason)
        _emit("FLATTEN_SYNC_SKIPPED",
              trade_account=trade_account, symbol=symbol_scope, reason=reason)
        return result

    log_dir = ROOT_DIR / "LOGS" / bot_cfg["log_subdir"]
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_path = log_dir / f"{bot_cfg['jsonl_prefix']}_{date_str}.jsonl"

    # Verify flatten reussi (qty_final == 0) pour chaque symbole avant d'append
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)

    for sym in target_symbols:
        pos = positions.get(sym, {})
        signal_id = pos.get("signal_id")
        if not signal_id:
            reason = f"{sym}_no_signal_id_in_state"
            result["skipped"].append(reason)
            _emit("FLATTEN_SYNC_SKIPPED",
                  trade_account=trade_account, symbol=sym, reason=reason)
            continue

        flatten_status = (flatten_results.get(sym, {}).get("status") or "").upper()
        if "OK_FLAT" not in flatten_status:
            reason = f"{sym}_flatten_status_not_ok_flat:{flatten_status}"
            result["skipped"].append(reason)
            _emit("FLATTEN_SYNC_SKIPPED",
                  trade_account=trade_account, symbol=sym, reason=reason)
            continue

        # Compose TRADE_CLOSE event conforme au format Bot3V3Logger
        close_event = {
            "ts": now_iso,
            "ts_event_ns": now_ns,
            "bot": bot_cfg["bot_version"],
            "event": "TRADE_CLOSE",
            "signal_id": signal_id,
            "symbol": sym,
            "side": pos.get("direction", ""),
            "level": pos.get("level_name", "?"),
            "exit_price": None,  # inconnu (MARKET CLOSE prix variable)
            "exit_cause": "MANUAL",
            "pnl_R": None,
            "pnl_usd": None,
            "duration_bars": None,
            "reason": "FLATTEN_BOT_EXTERNAL_DASHBOARD",
            "synthetic": True,
            "ctx": {
                "source": "flatten_bot.py",
                "trade_account": trade_account,
                "qty_init": flatten_results.get(sym, {}).get("qty_init"),
                "qty_final": flatten_results.get(sym, {}).get("qty_final"),
            },
        }

        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(close_event) + "\n")
            result["appended"].append({
                "symbol": sym, "signal_id": signal_id,
                "log_path": str(log_path),
            })
            _emit("FLATTEN_SYNC_APPENDED",
                  trade_account=trade_account, symbol=sym,
                  signal_id=signal_id, log_path=str(log_path))
        except OSError as e:
            err = f"{sym}_write_jsonl_failed: {type(e).__name__}: {e}"
            result["errors"].append(err)
            _emit("FLATTEN_SYNC_SKIPPED",
                  trade_account=trade_account, symbol=sym, reason=err)

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True, choices=["1", "2", "3", "4", "all"],
                    help="Bot a flatten : 1=v3+MP/Sim1, 2=BN V5/Sim2, 3=v4/Sim3, 4=Paper/Sim4, all=tous")
    ap.add_argument("--symbol", default=None, choices=[None, "ES", "NQ", "MGC"],
                    help="Si specifie, flatten uniquement ce symbole (per-trade flatten). "
                         "Incompatible avec --bot all.")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON pour API")
    args = ap.parse_args()

    if args.symbol is not None and args.bot == "all":
        print("[ERROR] --symbol incompatible avec --bot all", file=sys.stderr)
        return 2

    # 03/06 FIX P1.review BUG #2 : "4" ajoute dans choices + dans liste "all"
    bots = ["1", "2", "3", "4"] if args.bot == "all" else [args.bot]
    all_results = {}
    for bot in bots:
        ta = BOT_TO_ACCOUNT[bot]
        try:
            flatten_res = flatten_account(ta, only_symbol=args.symbol)
            all_results[f"bot{bot}"] = {
                "trade_account": ta,
                "symbol_scope": args.symbol or "ALL",
                "symbols": flatten_res,
                "status": "OK",
            }
            # Etape 4 09/06 BUG #4 : append TRADE_CLOSE dans bot logger JSONL
            # pour synchroniser dashboard paper_tracker.
            try:
                append_res = _append_trade_close_external(
                    trade_account=ta,
                    symbol_scope=args.symbol or "ALL",
                    flatten_results=flatten_res,
                )
                all_results[f"bot{bot}"]["dashboard_sync"] = append_res
                if append_res["appended"]:
                    print(f"\n[BUG #4 fix] {ta}: append TRADE_CLOSE for "
                          f"{len(append_res['appended'])} position(s) -> "
                          f"dashboard sync OK")
                elif append_res["skipped"]:
                    print(f"\n[BUG #4 fix] {ta}: skipped "
                          f"({', '.join(append_res['skipped'][:3])})")
            except Exception as e:
                # Best-effort : ne casse JAMAIS le flatten_bot pour cause sync
                all_results[f"bot{bot}"]["dashboard_sync"] = {
                    "error": f"{type(e).__name__}: {str(e)[:200]}",
                }
                print(f"\n[BUG #4 fix WARN] {ta}: sync failed: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
        except Exception as e:
            all_results[f"bot{bot}"] = {
                "trade_account": ta,
                "symbol_scope": args.symbol or "ALL",
                "error": str(e),
                "status": "FAIL",
            }
            print(f"\n[ERROR] Bot {bot} ({ta}): {e}", file=sys.stderr)

    if args.json:
        # Marker explicite pour parse cote API (anti-collision avec output log)
        print("===JSON_OUTPUT_START===")
        print(json.dumps(all_results, indent=2))
        print("===JSON_OUTPUT_END===")
    else:
        print(f"\nDONE. {len(bots)} bot(s) flattened.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
