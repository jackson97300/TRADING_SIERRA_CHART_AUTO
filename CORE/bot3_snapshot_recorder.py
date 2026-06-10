"""Bot 3 — Snapshot Recorder (ultra riche).

Capture l'integralite de l'horizon d'un trade :
  - Snapshot a l'entry (toutes features cles)
  - Snapshot bar-par-bar pendant le trade (60 bars max)
  - Snapshot a l'exit
  - MFE/MAE tracking
  - Key events (trailing activated, sl moved, level retest, etc.)

Format JSONL : 1 ligne par trade, structure imbriquee.
Permet post-mortem fin : on peut rejouer le trade bar-par-bar pour audit.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

# Liste des features critiques a snapshoter (les 77 du Bot 2 V2 + extras MP)
# Cette liste est plus courte que les 418 du V4 pour ne pas exploser le JSONL
SNAPSHOT_FEATURE_LIST: tuple[str, ...] = (
    # Base prix / vol
    "open", "high", "low", "close",
    "rvol", "rvol_zscore", "vol_zscore_20",
    "atr", "atr_14m_pct", "atr_regime_zscore_60d",
    # Position dans le range / VWAP
    "position_in_range", "finish_strength",
    "dist_vwap_d_pct", "vwap_slope_10",
    "dist_vwap_w_sd1d_pct",
    # Delta / CVD
    "delta_bar", "delta_pct", "cvd_session", "cvd_day", "delta_day_dir",
    # Niveaux MQ
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct",
    # Niveaux structurels
    "dist_ib_low_pct", "dist_ib_high_pct",
    "dist_open_830_pct", "dist_open_930_pct",
    "dist_single_print_nearest_pct", "n_single_prints_pct",
    "dist_naked_poc_nearest_pct", "naked_poc_age_max_days",
    "dist_cur_vpoc_pct", "dist_prev_val_pct", "dist_prev_vah_pct",
    "dist_cash_high_pct", "dist_cash_low_pct",
    # Game changers (Dalton)
    "open_type", "day_type",
    # POC migration
    "poc_migration_dir", "ctx_poc_migration_10",
    "ctx_va_developing_10", "ctx_va_width",
    # Structure Dalton
    "ctx_failed_auction", "ctx_rotation_factor_20",
    "ctx_ib_extension_ratio",
    # Big traders / whales
    "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
    "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
    "max_big_bid_vol_in_bar", "max_big_ask_vol_in_bar", "p99_trade_size",
    # Trapped
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
    # ICT / liquidity
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    "equal_highs_detected", "equal_lows_detected",
    # GEX
    "bool_gex_flip_zone", "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct",
    # Spike origin
    "dist_last_spike_origin_pct", "bars_since_last_spike",
    # Cross instrument
    "im_smt_divergence", "im_cross_delta_agreement_5", "im_volume_lead",
    # Session
    "is_in_asia", "is_in_london", "is_in_us_cash", "is_in_us_after",
    "session_segment", "time_to_session_close_norm",
    # News (creneaux reels V4 : 715, 730, 830, 845, 900, 930 ET)
    "mins_since_news", "mins_to_next_news",
    "within_news_715_5m", "within_news_730_5m",
    "within_news_830_5m", "within_news_845_5m",
    "within_news_900_5m", "within_news_930_5m",
    "is_news_715", "is_news_730", "is_news_830",
    "is_news_845", "is_news_900", "is_news_930",
    # Roll
    "is_roll_day", "roll_phase", "days_since_roll",
    # VIX / regime
    "vix_level",
)


def _safe(v: Any) -> Any:
    """Convert pour serialisation JSON."""
    if v is None:
        return None
    if isinstance(v, (int, str, bool)):
        return v
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return None
        return round(f, 6)
    except (TypeError, ValueError):
        try:
            return str(v)
        except Exception:
            return None


def snapshot_bar(bar: dict, fields: tuple[str, ...] = SNAPSHOT_FEATURE_LIST) -> dict:
    """Snapshot une barre sur les features critiques."""
    snap: dict[str, Any] = {}
    for f in fields:
        if hasattr(bar, "get"):
            v = bar.get(f)
        else:
            v = None
        if v is not None:
            snap[f] = _safe(v)
    return snap


class TradeSnapshotRecorder:
    """Enregistreur de snapshots pour un trade Bot 3."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def open_trade_record(
        self,
        signal_id: str,
        symbol: str,
        ts_entry: str,
        level_name: str,
        level_tier: int,
        level_baseline_rej: float,
        side: str,
        action: str,
        confidence: int,
        sl_ticks: int,
        atr_multiplier: float,
        entry_price: float,
        n_contracts: int,
        ctx_at_touch: dict,
        bar_at_touch: dict,
    ) -> dict:
        """Cree le record initial du trade. Retourne le dict trade."""
        return {
            "bot_id": "BOT3_MP",
            "signal_id": signal_id,
            "symbol": symbol,
            "ts_entry": ts_entry,
            "ts_exit": None,

            # Niveau
            "level_name": level_name,
            "level_tier": level_tier,
            "level_baseline_rej": level_baseline_rej,
            "level_side_def": ctx_at_touch.get("_level_side_def"),

            # Decision
            "decision": "GO",
            "side": side,
            "action": action,
            "confidence": confidence,
            "sl_ticks": sl_ticks,
            "atr_multiplier": atr_multiplier,

            # Execution
            "n_contracts": n_contracts,
            "price_entry": entry_price,
            "price_exit": None,
            "exit_reason": None,
            "pnl_ticks": None,
            "pnl_dollars": None,
            "mfe_ticks": 0.0,
            "mae_ticks": 0.0,
            "duration_seconds": None,

            # Context complet au touch (12 dimensions)
            "context_at_touch": ctx_at_touch,
            # Snapshot features completes au touch
            "features_at_touch": snapshot_bar(bar_at_touch),

            # Bar-by-bar snapshots durant le trade (cap 60)
            "bars_during_trade": [],

            # Key events (trailing_activated, sl_moved, etc.)
            "events": [],
        }

    def record_bar(
        self,
        trade: dict,
        bar: dict,
        bar_idx_relative: int,
        running_pnl_ticks: float,
        sl_price_current: float,
        trailing_active: bool,
    ) -> None:
        """Ajoute snapshot bar-by-bar au trade."""
        if len(trade["bars_during_trade"]) >= 60:
            return  # cap atteint
        snap = snapshot_bar(bar)
        snap["_bar_idx"] = bar_idx_relative
        snap["_running_pnl_ticks"] = round(running_pnl_ticks, 1)
        snap["_sl_price"] = round(sl_price_current, 4)
        snap["_trailing_active"] = bool(trailing_active)
        trade["bars_during_trade"].append(snap)

    def record_event(self, trade: dict, event_type: str, **payload) -> None:
        """Ajoute un event au trade (TRAILING_ACTIVATED, SL_MOVED, etc.)."""
        evt = {"type": event_type, "ts": time.time(), **payload}
        trade["events"].append(evt)

    def update_mfe_mae(self, trade: dict, current_pnl_ticks: float) -> None:
        """Met a jour le max favorable/adverse excursion."""
        if current_pnl_ticks > trade.get("mfe_ticks", 0):
            trade["mfe_ticks"] = round(current_pnl_ticks, 1)
        if current_pnl_ticks < trade.get("mae_ticks", 0):
            trade["mae_ticks"] = round(current_pnl_ticks, 1)

    def close_trade_record(
        self,
        trade: dict,
        ts_exit: str,
        exit_price: float,
        exit_reason: str,
        pnl_ticks: float,
        pnl_dollars: float,
        duration_seconds: float,
        bar_at_exit: dict,
    ) -> None:
        """Finalise + flush JSONL."""
        trade["ts_exit"] = ts_exit
        trade["price_exit"] = exit_price
        trade["exit_reason"] = exit_reason
        trade["pnl_ticks"] = round(pnl_ticks, 1)
        trade["pnl_dollars"] = round(pnl_dollars, 2)
        trade["duration_seconds"] = round(duration_seconds, 1)
        trade["features_at_exit"] = snapshot_bar(bar_at_exit)
        self._flush(trade)

    def _flush(self, trade: dict) -> None:
        """Append JSONL ligne au fichier du jour."""
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.log_dir / f"bot3_trades_{date_str}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False, default=str) + "\n")
