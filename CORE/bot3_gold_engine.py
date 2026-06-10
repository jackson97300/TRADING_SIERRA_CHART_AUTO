"""Bot 3 Gold — Engine orchestrateur (4 couches).

Orchestre :
  Couche 1 — NIVEAUX (detect touch)
  Couche 2 — CONTEXT (build 20 dims)
  Couche 3 — DECISION (8 scenarios via decision_engine)
  Couche 4 — EXECUTION (Sim3 paper via DTC, sizing 3 MGC)

Hedge cross-asset optionnel : LONG MGC si Bot 2 NQ/ES SHORT cluster + macro Gold BULL.

Usage runtime (live) :
    engine = Bot3GoldEngine()
    while True:
        bar = load_last_bar("MGC")
        decision = engine.process_bar(bar)
        if decision["trade"]:
            engine.execute(decision)
"""
from __future__ import annotations
from typing import Optional

try:
    from CORE.bot3_gold_level_definitions import get_all_gold_levels, is_ticks_level, get_proximity
    from CORE.bot3_gold_decision_engine import build_gold_context, evaluate_decision_gold
    from CORE.bot3_gold_config import (
        BOT3G_OBSERVE_ONLY, BOT3G_ENABLE_TIER2, BOT3G_ENABLE_HEDGE_CROSS_ASSET,
        GUARD_RAILS_GOLD, RISK_GOLD, GOLD_TIER1_LEVELS, TRADE_ACCOUNT_BOT3G,
    )
except ImportError:
    from bot3_gold_level_definitions import get_all_gold_levels, is_ticks_level, get_proximity
    from bot3_gold_decision_engine import build_gold_context, evaluate_decision_gold
    from bot3_gold_config import (
        BOT3G_OBSERVE_ONLY, BOT3G_ENABLE_TIER2, BOT3G_ENABLE_HEDGE_CROSS_ASSET,
        GUARD_RAILS_GOLD, RISK_GOLD, GOLD_TIER1_LEVELS, TRADE_ACCOUNT_BOT3G,
    )


# ─────────────────────────────────────────────────────────────────────────────
# HEDGE CROSS-ASSET (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

def check_gold_hedge(bot2_state: dict, gold_ctx: dict) -> tuple[bool, str]:
    """Vérifie si un hedge Gold LONG est justifié.

    Cas : Bot 2 NQ/ES SHORT cluster simultané + macro Gold bullish
    → LONG MGC (sizing reduit 1-2 micros) comme hedge portfolio.

    Args:
        bot2_state : {"NQ_position": "LONG/SHORT/None", "ES_position": ...}
        gold_ctx : dict contexte Gold (avec macro_bias)

    Returns: (hedge_active, reason)
    """
    nq_short = bot2_state.get("NQ_position") == "SHORT"
    es_short = bot2_state.get("ES_position") == "SHORT"
    macro_bull = gold_ctx.get("macro_bias") == "BULL"

    if nq_short and es_short and macro_bull:
        return True, "HEDGE_NQ_ES_SHORT_GOLD_BULL"
    return False, "no_hedge_setup"


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class Bot3GoldEngine:
    """Orchestrateur Bot 3 Gold (4 couches + hedge optionnel)."""

    def __init__(self):
        all_levels = get_all_gold_levels()
        # Filtre Tier 1 seulement si Phase 2 (BOT3G_ENABLE_TIER2 = False)
        if not BOT3G_ENABLE_TIER2:
            self.levels = {k: v for k, v in all_levels.items() if k in GOLD_TIER1_LEVELS}
        else:
            self.levels = all_levels

        self.trade_account = TRADE_ACCOUNT_BOT3G
        self.observe_only = BOT3G_OBSERVE_ONLY
        self.hedge_enabled = BOT3G_ENABLE_HEDGE_CROSS_ASSET

        # Daily counters (reset chaque jour trading)
        self.daily_counters = {"n_trades": 0, "n_losses": 0, "pnl": 0.0}
        self.current_position: Optional[dict] = None  # {entry_price, side, sl_ticks, ts_entry, level}

    def reset_daily_if_rollover(self, today_date):
        """Reset compteurs si nouveau jour trading."""
        if self.daily_counters.get("date") != today_date:
            self.daily_counters = {"date": today_date, "n_trades": 0, "n_losses": 0, "pnl": 0.0}

    def can_trade(self) -> tuple[bool, str]:
        """Garde-fous risk : caps trades/losses + kill switch."""
        risk = RISK_GOLD["MGC"]
        if self.daily_counters["n_trades"] >= risk["max_trades_per_day"]:
            return False, "CAP_TRADES_REACHED"
        if self.daily_counters["n_losses"] >= risk["max_losses_per_day"]:
            return False, "CAP_LOSSES_REACHED"
        if self.daily_counters["pnl"] <= risk["kill_switch_daily_pnl"]:
            return False, "KILL_SWITCH_DAILY_PNL"
        if self.current_position is not None:
            return False, "POSITION_OPEN"
        return True, "OK"

    def detect_touches(self, bar: dict) -> list[tuple]:
        """Couche 1 — détecte tous niveaux touchés sur cette bar.

        Returns: list of (level_name, level_def, dist_signed)
        """
        touched = []
        for name, lvl in self.levels.items():
            col = lvl["col"]
            val = bar.get(col)
            if val is None:
                continue
            try:
                d = float(val)
            except (TypeError, ValueError):
                continue
            if d != d:  # NaN
                continue
            prox, ticks_based = get_proximity(lvl)
            if abs(d) <= prox:
                touched.append((name, lvl, d))
        # Tie-break : Tier asc, dist asc
        touched.sort(key=lambda x: (x[1].get("tier", 99), abs(x[2])))
        return touched

    def process_bar(self, bar: dict, bot2_state: Optional[dict] = None) -> dict:
        """Workflow complet 4 couches sur 1 bar.

        Returns: dict {trade, level, side, action, scenario, confidence, sl_ticks, reason}
        """
        # Garde-fous risk
        can, can_reason = self.can_trade()
        if not can:
            return {"trade": False, "reason": can_reason}

        # Couche 1 — niveaux
        touched = self.detect_touches(bar)
        if not touched:
            return {"trade": False, "reason": "NO_LEVEL_TOUCH"}
        level_name, level_def, dist = touched[0]

        # Couche 2 — context
        ctx = build_gold_context(bar)

        # Couche 3 — decision (8 scenarios)
        trade, reason, params = evaluate_decision_gold(level_name, level_def, ctx, dist)
        if not trade:
            return {"trade": False, "level": level_name, "reason": reason,
                    "macro_bias": ctx.get("macro_bias"), "dist_signed": dist}

        # Couche 4 — execution (sizing + hedge)
        result = {
            "trade": True, "level": level_name, "dist_signed": dist,
            "side": params["side"], "action": params["action"],
            "scenario": params["scenario"], "confidence": params["confidence"],
            "sl_ticks": params["sl_ticks"], "atr_multiplier": params["atr_multiplier"],
            "macro_bias": ctx.get("macro_bias"),
            "n_contracts": GUARD_RAILS_GOLD["MGC"]["n_contracts"],
            "tp_cap_ticks": GUARD_RAILS_GOLD["MGC"]["tp_cap_ticks"],
            "trailing_activation": GUARD_RAILS_GOLD["MGC"]["trailing_activation"],
            "trailing_distance": GUARD_RAILS_GOLD["MGC"]["trailing_distance"],
            "timeout_minutes": GUARD_RAILS_GOLD["MGC"]["timeout_minutes"],
        }

        # Hedge cross-asset (Phase 3)
        if self.hedge_enabled and bot2_state is not None:
            hedge_active, hedge_reason = check_gold_hedge(bot2_state, ctx)
            if hedge_active and params["side"] == "LONG":
                # Reduce sizing pour hedge (1-2 micros vs 3)
                result["n_contracts"] = 2
                result["hedge_mode"] = True
                result["hedge_reason"] = hedge_reason

        # Mode observe-only : pas d'exécution réelle
        if self.observe_only:
            result["mode"] = "OBSERVE_ONLY"
            result["execute"] = False
        else:
            result["mode"] = "PAPER"
            result["execute"] = True

        return result

    def on_trade_open(self, entry_price: float, side: str, level: str, sl_ticks: int):
        """Hook quand un trade s'ouvre (live engine)."""
        import time
        self.current_position = {
            "entry_price": entry_price, "side": side, "level": level,
            "sl_ticks": sl_ticks, "ts_entry": time.time(),
        }
        self.daily_counters["n_trades"] += 1

    def on_trade_close(self, exit_price: float, exit_reason: str, pnl: float):
        """Hook quand un trade ferme (live engine)."""
        if pnl < 0:
            self.daily_counters["n_losses"] += 1
        self.daily_counters["pnl"] += pnl
        self.current_position = None

    # ─────────────────────────────────────────────────────────────────
    # API compatible Bot3Engine.evaluate() — pour integration directe
    # dans databento_paper_trader_v2._bot3_poll_cycle (12/05/2026)
    # ─────────────────────────────────────────────────────────────────

    def evaluate(self, bar: dict, symbol: str):
        """Adapter API compatible Bot3Engine.evaluate(bar, sym).

        Returns:
            (signal_or_none, decisions_log_list)
            - signal : Bot3Signal si trade GO, None sinon
            - decisions : list[Bot3DecisionLog] pour audit (1 entry par bar)
        """
        try:
            from CORE.bot3_mp_engine import Bot3Signal, Bot3DecisionLog
        except ImportError:
            from bot3_mp_engine import Bot3Signal, Bot3DecisionLog
        import uuid
        from datetime import datetime, timezone

        if symbol != "MGC":
            return None, []

        result = self.process_bar(bar)
        bar_ts = str(bar.get("ts_event", "?"))
        sig_id = uuid.uuid4().hex[:12]
        now_iso = datetime.now(timezone.utc).isoformat()
        level_name = result.get("level", "_NO_LEVEL_")
        ctx_dict = {"macro_bias": result.get("macro_bias")}

        if not result.get("trade"):
            decision_log = Bot3DecisionLog(
                signal_id=sig_id, symbol=symbol, ts_event=now_iso, bar_ts=bar_ts,
                level_name=level_name, level_tier=0,
                decision=f"SKIP_{result.get('reason', 'UNKNOWN')}",
                reason=result.get("reason", "UNKNOWN"), ctx=ctx_dict,
            )
            return None, [decision_log]

        # GO : construire Bot3Signal compatible _bot3_execute_trade
        try:
            close = float(bar.get("close", 0.0))
        except (TypeError, ValueError):
            close = 0.0
        if close <= 0:
            decision_log = Bot3DecisionLog(
                signal_id=sig_id, symbol=symbol, ts_event=now_iso, bar_ts=bar_ts,
                level_name=level_name, level_tier=0,
                decision="SKIP_BAR_CLOSE_INVALID",
                reason="bar close <= 0", ctx=ctx_dict,
            )
            return None, [decision_log]

        # Fix R2 (review code-reviewer 12/05) : dist_pct_at_touch reel
        # depuis dist_signed retourne par process_bar. dist_signed est en %
        # (col dist_*_pct du bar enriched) → directement assignable.
        # Sinon hardcode 0.0 = biais audit (tous signaux MGC apparaitraient
        # a distance zero) + casse eligibilite size-by-distance Phase 2.
        try:
            dist_pct = float(result.get("dist_signed", 0.0))
            if dist_pct != dist_pct:   # NaN
                dist_pct = 0.0
        except (TypeError, ValueError):
            dist_pct = 0.0

        signal = Bot3Signal(
            signal_id=sig_id, symbol=symbol, ts_event=now_iso, bar_ts=bar_ts,
            level_name=level_name, level_tier=1,
            level_baseline_rej=None, level_baseline_pf=None,
            side=result["side"], action=result.get("action", "REJECTION"),
            confidence=int(result.get("confidence", 60)),
            sl_ticks=int(result.get("sl_ticks", 200)),
            atr_multiplier=float(result.get("atr_multiplier", 1.0)),
            n_contracts=int(result.get("n_contracts", 3)),
            price_entry_ref=close, dist_pct_at_touch=dist_pct,
            ctx=ctx_dict, bar_at_touch=dict(bar), bucket="GOLD",
        )
        decision_log = Bot3DecisionLog(
            signal_id=sig_id, symbol=symbol, ts_event=now_iso, bar_ts=bar_ts,
            level_name=level_name, level_tier=1,
            decision="GO", reason=result.get("scenario", "S_GOLD"),
            ctx=ctx_dict,
        )
        return signal, [decision_log]
