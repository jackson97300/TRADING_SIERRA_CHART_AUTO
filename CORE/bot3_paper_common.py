"""bot3_paper_common.py — Helpers partages Bot 3 v3/v4 paper modules.

Refactorisation pour eviter duplication ~800 LOC entre v3 et v4 paper modules.
Pattern BN V4 valide (cf bn_v4_paper.py 1240 LOC) factorisé en helpers.

Contenu :
  - SYMBOL_TO_CONTRACT mapping
  - TICK_BY_SYMBOL / TICK_VALUE_USD
  - TP_CAP_TICKS securite distant
  - DTC constants (BUY/SELL)
  - place_bracket_dtc : helper bracket OCO atomique
  - force_close_market : sequence anti-orphan V2 (9 etapes) generic
  - query_open_orders : Type 300 query
  - modify_sl_via_dtc : cancel-replace SL (utilise par BE/trailing futurs)
  - check_risk_gates_for_trade : risk gates communs (kill switch, cooldown, DD)
  - heartbeat_check : helper periodic

Pattern : helpers stateless ou avec state explicite (passe en argument).
Pas de globals mutables, pas de singletons.

Auteur : MIA Trading V2 v1.0 (2026-05-24)
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))


# ════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════

SYMBOL_TO_CONTRACT: Dict[str, str] = {
    # ════════════════════════════════════════════════════════════════════════
    # 10/06/2026 — DÉCISION JACKSON : DECOUPLING VOLONTAIRE PAPER
    # ════════════════════════════════════════════════════════════════════════
    # Contract envoyé SC = E-mini standard (NQM26, ESM26) → fills affichés sur
    # charts NQM26/ESM26 de Jackson (étude/analyse visuelle).
    # Tick value Python (TICK_VALUE_USD ci-dessous) = micro virtuel ($0.50/$1.25)
    # → dashboard et calculs Python "comme si" on tradait du micro.
    #
    # ⚠️ CONSÉQUENCE : SC affichera P&L réel x10 vs Python (E-mini exec, micro calc).
    # Acceptable en PAPER (compte unlimited credit). BLOQUE migration Live AMP
    # tant que pas reconfigure (Cross Chart Sierra ou changement contract).
    #
    # Trade Activity Log Sim1 10/06 prouve le décalage :
    #   - Bot 3 v3 NQ 06:30 : SC +$750 vs Python +$144 (ratio 5.2x ticks slip)
    #   - Bot 3 v4 NQ 04:05 : SC -$45 vs Python +$18 (signe INVERSE !)
    # MGC reste micro standard (déjà cohérent).
    # Jackson directive : "ticks sont universels (0.25), à nous de décider mini/micro"
    "NQ": "NQM26-CME",           # E-mini NQ (SC) — calcul Python en micro virtuel
    "ES": "ESM26-CME",           # E-mini ES (SC) — calcul Python en micro virtuel
    "MGC": "MGCM26-CMECOMEX",    # Gold micro $1.00/tick (cohérent)
}

TICK_BY_SYMBOL: Dict[str, float] = {
    "NQ": 0.25,
    "ES": 0.25,
    "MGC": 0.10,
}

# Tick value $/pt (1 contract) — MICRO VIRTUEL pour calcul Python + dashboard.
# ⚠️ DECOUPLING avec SC : SC exécute E-mini réel ($5/$12.50/tick), Python calcule
# en micro virtuel ($0.50/$1.25). Ratio x10 sur PnL réel vs Python affiché.
# Accepté en paper (compte unlimited). À ré-aligner avant migration Live AMP.
TICK_VALUE_USD: Dict[str, float] = {
    "NQ": 0.50,    # Micro virtuel Python ($2/pt -> $0.50/tick) — SC réel $5/tick
    "ES": 1.25,    # Micro virtuel Python ($5/pt -> $1.25/tick) — SC réel $12.50/tick
    "MGC": 1.00,   # Gold micro MGCM26 ($10/pt -> $1.00/tick) [cohérent]
}

# DTC constants (BUY=1, SELL=2 ; cf BOT/dtc_connector.py mode JSON)
try:
    from dtc_connector import BUY as DTC_BUY, SELL as DTC_SELL
except ImportError:
    DTC_BUY = 1
    DTC_SELL = 2

# Default risk gates (override per bot si besoin)
# 24/05/2026 PM Jackson directive : seuil 3 SL consec DESACTIVE en paper
# (999 = jamais atteint). Le cooldown inter-trades (post chaque trade
# gain OU perte) reste actif via cooldown_bars dans engine (Bot 3 v4 30 bars,
# Bot 3 v3 cooldown level state machine, BN V4 trail engine).
# DD session ouvert (-5000$ en paper = pas de kill switch DD effectif, max data).
DEFAULT_RISK_MAX_SL_CONSEC = 999
DEFAULT_RISK_COOLDOWN_MIN = 60
DEFAULT_RISK_MAX_DD_USD = -5000.0

# 24/05/2026 PM Jackson directive : cooldown global post-trade per-bot, par sym.
# Empeche back-to-back trades sur memes ou differents niveaux dans un cooldown
# court apres CHAQUE close. Asymetrique : pertes attendent plus que gains.
# (cf incident Bot 3 v4 22:31-22:32 : 2 trades en 30s, 2 SL slippage Asia open).
# Defaults consommes par Bot 1 (Wyckoff), Bot 2 (BN V4), Bot 3 v4 (data-driven).
# NE PAS BUMPER GLOBALEMENT (impact cross-bot). Bot 1 override explicite dans
# bot3_v3_continuation_paper.py:_cd_blocked appel (cooldown 20/30 Jackson 02/06).
DEFAULT_COOLDOWN_AFTER_WIN_MIN = 10
DEFAULT_COOLDOWN_AFTER_LOSS_MIN = 15
DEFAULT_HEARTBEAT_INTERVAL_MIN = 10


# ════════════════════════════════════════════════════════════════════════
# DTC BRACKET HELPER
# ════════════════════════════════════════════════════════════════════════

def place_bracket_dtc(
    dtc: Any,
    symbol: str,
    side: str,                  # "LONG" or "SHORT"
    entry_price: float,
    sl_price: float,
    tp_price: float,
    sl_ticks: int,
    tp_ticks: int,
    trade_account: str,
    qty: int = 1,
    auto_reprice_threshold_ticks: int = 5,
) -> Tuple[str, str, str]:
    """Place bracket OCO atomique via dtc.send_market_order.

    Pattern BN V4 valide (bn_v4_paper.py:_place_bracket_dtc).

    Returns:
        (parent_cid, tp_cid, sl_cid) tuple. Tous "" si parent fill timeout.

    Raises:
        Exception : si dtc.send_market_order raise (caller doit catch + emit).
    """
    contract = SYMBOL_TO_CONTRACT.get(symbol, f"{symbol}M26-CME")
    tick = TICK_BY_SYMBOL.get(symbol, 0.25)
    side_int = DTC_BUY if side == "LONG" else DTC_SELL

    return dtc.send_market_order(
        symbol=contract,
        side=side_int,
        quantity=qty,
        sl_price=sl_price,
        tp_price=tp_price,
        trade_account=trade_account,
        signal_ref_price=entry_price,
        sl_ticks=sl_ticks,
        tp_ticks=tp_ticks,
        tick_size=tick,
        auto_reprice_threshold_ticks=auto_reprice_threshold_ticks,
    )


# ════════════════════════════════════════════════════════════════════════
# DTC QUERY OPEN ORDERS (anti-orphan helper)
# ════════════════════════════════════════════════════════════════════════

def query_open_orders_by_symbol(
    dtc: Any,
    contract: str,
    trade_account: str,
    timeout_sec: float = 2.0,
) -> List[Tuple[str, str]]:
    """Query Type 300 OPEN_ORDERS + filter par symbol.

    Returns:
        list of (client_order_id, server_order_id) tuples pour Working orders.
    Best-effort : retourne [] si DTC API differente.
    """
    try:
        if hasattr(dtc, "query_open_orders_blocking"):
            orders = dtc.query_open_orders_blocking(
                trade_account=trade_account, timeout=timeout_sec,
            ) or []
            return [
                (o.get("ClientOrderID", ""), o.get("ServerOrderID", ""))
                for o in orders
                if o.get("Symbol", "") == contract
                and o.get("OrderStatus") in (2, 4)  # Open/Working
            ]
    except Exception:
        pass
    return []


# ════════════════════════════════════════════════════════════════════════
# ANTI-ORPHAN V2 SEQUENCE (9 etapes) — generic
# ════════════════════════════════════════════════════════════════════════

def force_close_market(
    dtc: Any,
    symbol: str,
    pos: dict,
    trade_account: str,
    reason: str,
    bot_label: str,
    emit_fn: Callable[..., None],
    cid_prefix: str,
    cid_index: dict,
    cid_index_lock: threading.Lock,
    handle_fill_kind_close: str = "sl",
    log_open_orders: bool = True,
) -> bool:
    """Sequence anti-orphan V2 9 etapes generic (cf .claude/rules/orphan-prevention.md).

    Args:
        dtc : DTCConnector instance
        symbol : "NQ" / "ES" / etc.
        pos : dict position {parent_cid, tp_cid, sl_cid, direction, qty, signal_id, ...}
        trade_account : "Sim1" / "Sim3"
        reason : string raison force_close (timeout/kill/etc.)
        bot_label : "BOT3_V3" / "BOT3_V4" prefix logs
        emit_fn : callable(code, **ctx) pour emit log_catalog
        cid_prefix : prefix uuid pour close_cid + flush_cid (ex: "BOT3_V3")
        cid_index : dict {cid: {sym, kind, signal_id}} a mettre a jour
        cid_index_lock : threading.Lock pour cid_index
        handle_fill_kind_close : "sl" (default, close traite comme SL fill)
        log_open_orders : True (etape 6.5 + 9) ou False (skip pour test)

    Returns:
        True si flatten propre, False si DTC down.

    Sequence (9 etapes) :
        1. Cancel TP avec trade_account explicite
        2. Cancel SL idem
        3. Wait 1s propagation
        4. R1 Verify position broker via request_position_blocking
        5. MARKET CLOSE Type 208 OpenCloseTrade=2 si qty != 0
        6. Wait 2s fill
        6.5. CANCEL-ALL-WORKING (query Type 300 + cancel survivants)
        7. Type 209 SUBMIT_FLATTEN (ClientOrderID obligatoire)
        8. SKIP Type 210 (Sim partage potentiellement)
        9. VERIFY POST-CLEANUP (re-query, emit ORPHAN_DETECTED si > 0)
    """
    contract = SYMBOL_TO_CONTRACT.get(symbol, f"{symbol}M26-CME")
    tp_cid = pos.get("tp_cid")
    sl_cid = pos.get("sl_cid")

    if not getattr(dtc, "connected", True):
        emit_fn(f"{bot_label}_DTC_DOWN",
                sym=symbol, action="skip_cycle_until_reconnect")
        return False

    # ETAPE 1 : Cancel TP
    if tp_cid:
        try:
            dtc.cancel_order(tp_cid, trade_account=trade_account)
        except Exception as e:
            emit_fn(f"{bot_label}_LOOP_ERROR",
                    sym=symbol, err=f"force_close_cancel_tp_exc: {type(e).__name__}")

    # ETAPE 2 : Cancel SL
    if sl_cid:
        try:
            dtc.cancel_order(sl_cid, trade_account=trade_account)
        except Exception as e:
            emit_fn(f"{bot_label}_LOOP_ERROR",
                    sym=symbol, err=f"force_close_cancel_sl_exc: {type(e).__name__}")

    # ETAPE 3 : Wait 1s propagation
    time.sleep(1.0)

    # ETAPE 4 : Verify position broker
    qty = None
    try:
        qty = dtc.request_position_blocking(
            contract, trade_account=trade_account, timeout=2.0,
        )
    except Exception as e:
        emit_fn(f"{bot_label}_LOOP_ERROR",
                sym=symbol,
                err=f"force_close_pos_query_exc: {type(e).__name__}: {str(e)[:200]}")
    if qty is None:
        emit_fn(f"{bot_label}_LOOP_ERROR",
                sym=symbol, err="force_close_pos_verify_timeout")
        qty = 0  # proceed with Type 209 anyway

    # ETAPE 5 : MARKET CLOSE si qty != 0
    if qty != 0:
        n_to_close = abs(qty)
        side_close = DTC_SELL if qty > 0 else DTC_BUY
        close_cid = f"{cid_prefix}_CLOSE_{symbol[:2]}_{uuid.uuid4().hex[:8]}"
        try:
            dtc._order_trade_accounts[close_cid] = trade_account
        except Exception:
            pass  # best-effort, _order_trade_accounts may not exist
        # Register pour routage fill
        with cid_index_lock:
            cid_index[close_cid] = {
                "sym": symbol, "kind": handle_fill_kind_close,
                "signal_id": pos.get("signal_id"),
            }
        try:
            dtc._send({
                "Type": 208, "Symbol": contract,
                "ClientOrderID": close_cid, "OrderType": 1,  # MARKET
                "BuySell": side_close, "Quantity": n_to_close,
                "TradeAccount": trade_account, "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2, "TimeInForce": 0,
            })
            emit_fn(f"{bot_label}_TRADE_CLOSE_MANUAL",
                    sym=symbol, level=pos.get("level_name", "?"),
                    side=pos.get("direction", "?"),
                    exit_price=0.0, pnl_R=0.0,
                    reason=f"force_close_{reason}")
        except Exception as e:
            emit_fn(f"{bot_label}_LOOP_ERROR",
                    sym=symbol,
                    err=f"force_close_send_market_exc: {type(e).__name__}: {str(e)[:200]}")
            with cid_index_lock:
                cid_index.pop(close_cid, None)

    # ETAPE 6 : Wait 2s fill
    time.sleep(2.0)

    # ETAPE 6.5 : CANCEL-ALL-WORKING (Type 300 + cancel survivants)
    if log_open_orders:
        try:
            working_orders = query_open_orders_by_symbol(dtc, contract, trade_account)
            for working_cid, _ in working_orders:
                try:
                    dtc.cancel_order(working_cid, trade_account=trade_account)
                except Exception as e:
                    emit_fn(f"{bot_label}_LOOP_ERROR",
                            sym=symbol,
                            err=f"cancel_working_orphan_exc: {type(e).__name__}")
        except Exception as e:
            emit_fn(f"{bot_label}_LOOP_ERROR",
                    sym=symbol,
                    err=f"query_open_orders_exc: {type(e).__name__}: {str(e)[:200]}")

    # ETAPE 7 : Type 209 SUBMIT_FLATTEN (ClientOrderID OBLIGATOIRE)
    flush_cid = f"{cid_prefix}_FLUSH_{symbol[:2]}_{int(time.time()) % 100000}"
    try:
        dtc._send({
            "Type": 209, "ClientOrderID": flush_cid,
            "Symbol": contract, "TradeAccount": trade_account,
            "Exchange": "CME", "IsAutomatedOrder": 1,
        })
    except Exception as e:
        emit_fn(f"{bot_label}_LOOP_ERROR",
                sym=symbol,
                err=f"flush_209_exc: {type(e).__name__}: {str(e)[:200]}")

    # ETAPE 8 : SKIP Type 210 (Sim potentiellement partage avec autres bots)

    # ETAPE 9 : VERIFY POST-CLEANUP (wait 2s + re-query, emit ORPHAN si > 0)
    time.sleep(2.0)
    if log_open_orders:
        try:
            survivors = query_open_orders_by_symbol(dtc, contract, trade_account)
            if survivors:
                for surv_cid, _ in survivors:
                    emit_fn(f"{bot_label}_ORPHAN_DETECTED",
                            sym=symbol, order_cid=surv_cid[:30],
                            order_type=f"working_post_cleanup_{reason}")
                    try:
                        dtc.cancel_order(surv_cid, trade_account=trade_account)
                    except Exception:
                        pass
        except Exception as e:
            emit_fn(f"{bot_label}_LOOP_ERROR",
                    sym=symbol,
                    err=f"verify_post_cleanup_exc: {type(e).__name__}")

    return True


# ════════════════════════════════════════════════════════════════════════
# RISK GATES (kill switch + cooldown + DD)
# ════════════════════════════════════════════════════════════════════════


def check_risk_gates(
    state: dict,
    sym: str,
    direction: str,
    emit_fn: Callable[..., None],
    bot_label: str,
) -> bool:
    """Verifie risk gates AVANT trade. Returns True si autorise, False sinon.

    Args:
        state : dict {kill_switch_active, kill_switch_reason, cooldown_until,
                       pnl_session_usd, n_sl_consec, RISK_MAX_DD_USD, etc.}
        sym : symbol
        direction : "LONG" or "SHORT"
        emit_fn : callable emit log_catalog
        bot_label : "BOT3_V3" / "BOT3_V4"

    Gates :
      1. Kill switch global active → SKIP
      2. Cooldown 3 SL consec actif → SKIP
      3. PnL session < MAX_DD_USD → activate kill switch
    """
    # Gate 1 : kill switch
    if state.get("kill_switch_active", False):
        emit_fn(f"{bot_label}_ENTRY_VETO_KILL_SWITCH",
                sym=sym, level="*", side=direction,
                reason=state.get("kill_switch_reason", "manual"))
        return False

    # Gate 2 : cooldown 3 SL consec
    cooldown_until = state.get("cooldown_until", {}).get(sym)
    if cooldown_until is not None:
        now = datetime.now(timezone.utc)
        if now < cooldown_until:
            remaining_min = (cooldown_until - now).total_seconds() / 60
            emit_fn(f"{bot_label}_ENTRY_VETO_KILL_SWITCH",
                    sym=sym, level="*", side=direction,
                    reason=f"cooldown_3sl_remaining_{remaining_min:.1f}min")
            return False
        else:
            state["cooldown_until"][sym] = None
            state["n_sl_consec"][sym] = 0

    # Gate 3 : PnL session DD (fix R1 review iter1 : emit AVANT return False)
    pnl_session = state.get("pnl_session_usd", 0.0)
    max_dd = state.get("RISK_MAX_DD_USD", DEFAULT_RISK_MAX_DD_USD)
    if pnl_session <= max_dd:
        emit_fn(f"{bot_label}_ENTRY_VETO_KILL_SWITCH",
                sym=sym, level="*", side=direction,
                reason=f"dd_session_exceeded_{pnl_session:.2f}_vs_{max_dd}")
        return False  # caller handle activate_kill_switch via post-check

    return True


# ════════════════════════════════════════════════════════════════════════
# HEARTBEAT
# ════════════════════════════════════════════════════════════════════════

def should_emit_heartbeat(
    last_heartbeat_ts: Optional[datetime],
    interval_min: int = DEFAULT_HEARTBEAT_INTERVAL_MIN,
) -> bool:
    """Check si delta depuis last_heartbeat >= interval_min minutes."""
    now = datetime.now(timezone.utc)
    if last_heartbeat_ts is None:
        return True
    elapsed_min = (now - last_heartbeat_ts).total_seconds() / 60
    return elapsed_min >= interval_min


# ════════════════════════════════════════════════════════════════════════
# UTILS
# ════════════════════════════════════════════════════════════════════════

def check_post_trade_cooldown(
    last_close_ts: Optional[Any],          # datetime ou None
    last_close_pnl_R: Optional[float],
    now: Any,                              # datetime
    cooldown_win_min: int = DEFAULT_COOLDOWN_AFTER_WIN_MIN,
    cooldown_loss_min: int = DEFAULT_COOLDOWN_AFTER_LOSS_MIN,
) -> Tuple[bool, int, str]:
    """Cooldown global post-trade per-bot per-sym.

    Returns (blocked, remaining_sec, reason) :
      - blocked=True si dans la fenetre cooldown post-close
      - remaining_sec : secondes restantes avant fin cooldown
      - reason : "win_cooldown_10min" / "loss_cooldown_15min" / "no_prior_trade" / "expired"

    Logique :
      - last_close_pnl_R > 0 (gain) → cooldown 10min
      - last_close_pnl_R <= 0 (perte/flat) → cooldown 15min
      - Aucun trade prealable → not blocked

    Fix 24/05/2026 PM Jackson directive : empeche back-to-back trades sur
    memes ou differents niveaux apres chaque close. Pertes attendent plus
    pour laisser le marche bouger / digere la volatilite ayant cause le SL.
    """
    if last_close_ts is None or last_close_pnl_R is None:
        return (False, 0, "no_prior_trade")
    try:
        elapsed_sec = (now - last_close_ts).total_seconds()
    except (TypeError, AttributeError):
        return (False, 0, "ts_invalid")
    if last_close_pnl_R > 0:
        cooldown_sec = cooldown_win_min * 60
        reason = f"win_cooldown_{cooldown_win_min}min"
    else:
        cooldown_sec = cooldown_loss_min * 60
        reason = f"loss_cooldown_{cooldown_loss_min}min"
    if elapsed_sec < cooldown_sec:
        return (True, int(cooldown_sec - elapsed_sec), reason)
    return (False, 0, "expired")


def compute_pnl_R_usd(
    direction: str,
    entry_price: float,
    sl_initial: float,
    exit_price: float,
    symbol: str,
    n_contracts: int = 1,
    tick_value_override: Optional[float] = None,
) -> Tuple[float, float]:
    """Compute (pnl_R, pnl_usd) post-trade close.

    Returns:
        (pnl_R, pnl_usd) tuple. pnl_R = pnl_pts / risk_pts.
        pnl_usd inclut n_contracts (sizing per-bot).

    Fix 24/05/2026 PM (incident Bot 3 v4 ghost trade +$59542 / 7939R sur Sim3) :
    guards exit_price + entry_price. Le caller doit passer un fill_price > 0
    (prix broker reel). Si exit_price=0/None (cas DTC ORDER_UPDATE sans
    LastFillPrice/AverageFillPrice valide), on retourne (0, 0) plutot que
    de calculer un PnL aberrant base sur entry - 0 = ~30000 pts. Caller doit
    aussi EMETTRE un code log dedie quand fill_price=0 (cf bot3_v3/v4/bn_v4
    handle_dtc_fill).

    02/06 ARCHI per-bot : param n_contracts (default 1) multiplie pnl_usd.
    Callers (bot3_v3/v4 paper traders + paper_v2) passent leur n_contracts
    depuis GUARD_RAILS_BOT3[sym]["n_contracts"]. Architecture conservée même
    après rollback "TOUT EN MINI" du 02/06 — extensibilité future si un bot
    veut scaler.

    09/06 BUG #5 fix (etape 4 sprint stabilite Bot 3 v3) :
    Le TICK_VALUE_USD[sym] global = $5/tick E-mini NQ. Mais Bot 3 v3 trade en
    Cross Chart Micro (3 MNQM26 a $0.50/tick) cote Sierra Chart. Le calcul
    legacy surestime pnl_usd × 10 (= ratio $5/$0.50). Solution : param
    tick_value_override permet au caller (Bot 3 v3 via GUARD_RAILS_BOT3[sym]
    ["tick_value"]=0.50) de bypass le mapping global. Default None = legacy.

    Args:
        tick_value_override: si fourni (>0), bypass TICK_VALUE_USD[symbol].
            Use case Bot 3 v3 : passe GUARD_RAILS_BOT3[sym]["tick_value"]
            (=0.50 pour NQ micro Cross Chart, 1.25 pour ES micro, etc).
    """
    # GUARD CRITIQUE : exit_price doit etre un prix broker reel (> 0)
    if exit_price is None or exit_price <= 0:
        return (0.0, 0.0)
    # GUARD CRITIQUE : entry_price doit aussi etre valide (symetrie)
    if entry_price is None or entry_price <= 0:
        return (0.0, 0.0)
    risk_pts = abs(entry_price - sl_initial)
    if risk_pts <= 0:
        return (0.0, 0.0)
    if direction == "LONG":
        pnl_pts = exit_price - entry_price
    else:
        pnl_pts = entry_price - exit_price
    pnl_R = pnl_pts / risk_pts
    tick = TICK_BY_SYMBOL.get(symbol, 0.25)
    # 09/06 BUG #5 : tick_value_override prioritaire (bot connait son sizing exact)
    if tick_value_override is not None and tick_value_override > 0:
        tick_value = float(tick_value_override)
    else:
        if symbol not in TICK_VALUE_USD:
            raise ValueError(
                f"compute_pnl_R_usd: unknown symbol '{symbol}' "
                f"(supported: {list(TICK_VALUE_USD.keys())}). "
                "Fail-loud post-rollback 02/06 MINI : ajouter symbole dans TICK_VALUE_USD."
            )
        tick_value = TICK_VALUE_USD[symbol]
    pnl_usd = pnl_pts * tick_value / tick * max(1, int(n_contracts))
    return (pnl_R, pnl_usd)
