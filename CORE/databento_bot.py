"""databento_bot.py — Bot pur ML sur dataset enrichi 420 cols.

Architecture (28/04/2026) - replace mia_paper_trader.py.

Sources :
  - Databento Live (databento_dumper.py) → OHLCV+delta JSONL Hive
  - Sierra Chart MQ_Lite (MQ_Lite.cpp) → niveaux MQ JSONL Hive
  - Pipeline batch 5 min (live_pipeline.py) → parquet 420 cols enrichi
  - Modele LightGBM (train_lightgbm.py sur dataset v5e)

Workflow par minute :
  1. Read derniere barre parquet enrichi (DATA/datasets/v4_enriched/...)
  2. Load model ES_buy.pkl + ES_sell.pkl (idem NQ) si pas deja en memoire
  3. Inference : score_buy, score_sell sur les 420 features
  4. Decision : BUY si score_buy > T_BUY (default 0.85), SELL si score_sell > T_SELL
  5. Risk Manager : kill-switch (STOP.flag), cooldown 15 min, exposure max
  6. SLTPEngine : SL/TP via murs Tier 1/2 (fonction reutilisee mia_sltp.py)
  7. Order DTC (paper Sim3 ou live AMP)
  8. State.json pour dashboard

Pas de :
  - Dependance dashboard rules (le ML voit toutes les features lui-meme)
  - Dependance DMP JSONL flat
  - Cascading rules (anti pattern 11 V1)
  - Dependance Sierra Chart sauf pour MQ levels via MQ_Lite + DTC

Anti-pattern 11 V1 : ML purement quantitatif, pas 11 layers de gates.
Si le ML score est > threshold, on trade. Risk Manager = SEULE couche additionnelle.

Usage :
    python -X utf8 CORE/databento_bot.py                  # paper Sim3
    python -X utf8 CORE/databento_bot.py --threshold 0.80 # threshold custom
    python -X utf8 CORE/databento_bot.py --live           # live AMP (DANGER)

Auteur : MIA Trading System V2
Date   : 2026-04-28
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

# Reutilise SLTPEngine eprouve (44 walls Tier 1/2/3, validé empiriquement)
from mia_sltp import SLTPEngine

# DTC connector eprouve (OCO manuel valide 02/04/2026)
try:
    from dtc_connector import DTCConnector, OrderFill, BUY as DTC_BUY, SELL as DTC_SELL
    from bot_config import DTCConfig, INSTRUMENTS as BOT_INSTRUMENTS
    _DTC_OK = True
except ImportError as _e:
    print(f"[WARN] DTC import failed : {_e}")
    _DTC_OK = False
    DTC_BUY = 1
    DTC_SELL = 2

# Logs structures
try:
    from logging_v2 import get_logger
    _log = get_logger("databento_bot", process="databento_bot")
except ImportError:
    _log = None

# ============================================================
# CONFIG
# ============================================================
DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
MODELS_DIR = ROOT / "DATA" / "MODELS"
STATE_FILE = ROOT / "DATA" / "PAPER_TRADES" / "databento_bot_state.json"
STOP_FLAG = ROOT / "DATA" / "BOT_CONTROL" / "STOP.flag"

POLL_INTERVAL_SEC = 30          # check nouvelle barre toutes les 30s
COOLDOWN_MIN = 15               # cooldown post-close par symbol
MAX_TRADES_PER_DAY = 5
MAX_CONSECUTIVE_SL = 3          # circuit breaker
PAUSE_AFTER_BREAKER_MIN = 60

DEFAULT_THRESHOLD_BUY = 0.85
DEFAULT_THRESHOLD_SELL = 0.85
DEFAULT_HORIZON_BARS = 60       # SLTPEngine timeout

TICK_SIZE = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}

# Symbols traded (ES + NQ via Databento c.0)
SYMBOLS = ["ES", "NQ"]


@dataclass
class BotConfig:
    threshold_buy: float = DEFAULT_THRESHOLD_BUY
    threshold_sell: float = DEFAULT_THRESHOLD_SELL
    poll_interval: int = POLL_INTERVAL_SEC
    paper_mode: bool = True   # True = Sim3, False = AMP live (DANGER)
    dry_run: bool = False     # True = log signaux, no orders
    trade_account: str = "Sim3"  # Sim3 = paper, AMP123456 = live (DANGER)
    quantity: int = 1            # micro contracts par trade


# ============================================================
# MODEL LOADER
# ============================================================
class ModelStore:
    """Cache LightGBM models per symbol+side (lazy load)."""

    def __init__(self):
        self._models: dict[str, dict] = {}  # key = f"{symbol}_{side}"

    def get(self, symbol: str, side: str):
        """side = 'buy' or 'sell'. Retourne LGBMClassifier ou dict (selon format pkl)."""
        key = f"{symbol}_{side}"
        if key in self._models:
            return self._models[key]
        path = MODELS_DIR / f"{symbol}_{side}_model.pkl"
        if not path.exists():
            print(f"[WARN] model not found: {path}")
            return None
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            self._models[key] = obj
            # Extraire features count (2 formats supportes : LGBMClassifier direct OU dict)
            if hasattr(obj, "feature_name_"):
                feat_count = len(obj.feature_name_)
            elif isinstance(obj, dict):
                feat_count = len(obj.get("features", []))
            else:
                feat_count = "?"
            print(f"[MODEL] loaded {key} : type={type(obj).__name__} features={feat_count}")
            return obj
        except (pickle.UnpicklingError, OSError) as e:
            print(f"[ERR] failed to load {path}: {e}")
            return None

    def predict(self, symbol: str, side: str, df_row: pd.DataFrame) -> Optional[float]:
        """Single-row inference. df_row = DataFrame avec 1 ligne contenant les features.

        Supporte 2 formats pkl :
          - LGBMClassifier direct (training pipeline actuel) → predict_proba()[:, 1]
          - dict {model, features, threshold} (legacy format)
        """
        obj = self.get(symbol, side)
        if obj is None:
            return None

        # Format 1 : LGBMClassifier direct
        if hasattr(obj, "feature_name_"):
            features = list(obj.feature_name_)
            booster = obj
        # Format 2 : dict
        elif isinstance(obj, dict):
            features = obj.get("features", [])
            booster = obj.get("model") or obj.get("booster")
        else:
            return None

        if not features or booster is None:
            return None

        # Padding cols manquantes avec NaN (LightGBM gere les NaN nativement)
        # Build dict en 1 passe pour eviter PerformanceWarning fragmented frame
        missing = [f for f in features if f not in df_row.columns]
        if missing:
            pad = pd.DataFrame({f: [np.nan] for f in missing}, index=df_row.index)
            df_row = pd.concat([df_row, pad], axis=1)
        # Construit DataFrame avec feature_names pour eviter UserWarning sklearn
        X = df_row[features]

        # predict_proba pour classifier (probabilite classe 1), predict pour regressor
        if hasattr(booster, "predict_proba"):
            proba = booster.predict_proba(X)
            # Class 1 = signal valide (BUY ou SELL selon side du model)
            return float(proba[0, 1]) if proba.shape[1] >= 2 else float(proba[0, 0])
        elif hasattr(booster, "predict"):
            return float(booster.predict(X)[0])
        return None


# ============================================================
# DATA LOADER (parquet enrichi 420 cols)
# ============================================================
def load_last_bar(symbol: str) -> Optional[pd.DataFrame]:
    """Lit la derniere barre du parquet enrichi pour le symbole."""
    today = datetime.now(timezone.utc).date()
    # Cherche partition courante
    partition = (DATASET_ROOT / f"symbol={symbol}.c.0" /
                 f"year={today.year}" / f"month={today.month:02d}" / "data.parquet")
    if not partition.exists():
        # Fallback : derniere partition disponible
        sym_root = DATASET_ROOT / f"symbol={symbol}.c.0"
        if not sym_root.exists():
            return None
        candidates = sorted(sym_root.glob("year=*/month=*/data.parquet"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        partition = candidates[0]
    try:
        df = pd.read_parquet(partition)
        if df.empty:
            return None
        return df.tail(1).reset_index(drop=True)
    except (OSError, ValueError) as e:
        print(f"[ERR] read parquet {partition}: {e}")
        return None


# ============================================================
# RISK MANAGER (minimal — sera etendu)
# ============================================================
class RiskManager:
    def __init__(self):
        self.last_close_time: dict[str, datetime] = {}
        self.consecutive_sl: dict[str, int] = {"ES": 0, "NQ": 0}
        self.breaker_until: dict[str, datetime] = {}
        self.trades_today: dict[str, int] = {"ES": 0, "NQ": 0}

    def can_trade(self, symbol: str) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        now = datetime.now(timezone.utc)
        # Kill-switch global
        if STOP_FLAG.exists():
            return False, "STOP_FLAG_PRESENT"
        # Cooldown post-close
        last = self.last_close_time.get(symbol)
        if last and (now - last) < timedelta(minutes=COOLDOWN_MIN):
            return False, f"COOLDOWN_{COOLDOWN_MIN}MIN"
        # Circuit breaker
        until = self.breaker_until.get(symbol)
        if until and now < until:
            mins_left = int((until - now).total_seconds() / 60)
            return False, f"CIRCUIT_BREAKER_{mins_left}MIN"
        # Max trades/day
        if self.trades_today.get(symbol, 0) >= MAX_TRADES_PER_DAY:
            return False, f"MAX_TRADES_DAY"
        return True, "OK"

    def on_trade_open(self, symbol: str):
        self.trades_today[symbol] = self.trades_today.get(symbol, 0) + 1

    def on_trade_close(self, symbol: str, pnl_ticks: float):
        now = datetime.now(timezone.utc)
        self.last_close_time[symbol] = now
        if pnl_ticks < 0:
            self.consecutive_sl[symbol] = self.consecutive_sl.get(symbol, 0) + 1
            if self.consecutive_sl[symbol] >= MAX_CONSECUTIVE_SL:
                self.breaker_until[symbol] = now + timedelta(minutes=PAUSE_AFTER_BREAKER_MIN)
                print(f"[RISK] {symbol} CIRCUIT BREAKER : {MAX_CONSECUTIVE_SL} SL consec, "
                      f"pause {PAUSE_AFTER_BREAKER_MIN}min")
        else:
            self.consecutive_sl[symbol] = 0


# ============================================================
# MAIN LOOP
# ============================================================
class DatabentoBot:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.models = ModelStore()
        self.risk = RiskManager()
        self.sltp_engines = {sym: SLTPEngine(symbol=sym) for sym in SYMBOLS}
        self.stop_event = threading.Event()
        self.last_bar_ts: dict[str, Optional[pd.Timestamp]] = {sym: None for sym in SYMBOLS}

        # DTC connection (paper Sim3 ou live AMP)
        self.dtc: Optional["DTCConnector"] = None
        # Track active positions par symbol → {symbol: {parent_id, tp_cid, sl_cid, side, entry, sl_ticks, tp_ticks, ts}}
        self.active_positions: dict[str, dict] = {}
        self._pos_lock = threading.Lock()
        # Map order_id → symbol (pour callback fill)
        self._order_to_symbol: dict[str, str] = {}

        if not cfg.dry_run and _DTC_OK:
            self.dtc = DTCConnector(DTCConfig())
            connected = self.dtc.connect()
            if not connected:
                print("[BOT] DTC connect FAILED — fallback dry_run mode")
                self.cfg.dry_run = True
            else:
                print("[BOT] DTC connected (paper Sim3)" if cfg.paper_mode
                      else "[BOT] DTC connected (LIVE AMP — DANGER)")
                # Register fill callback pour close trade
                if hasattr(self.dtc, "register_fill_callback"):
                    self.dtc.register_fill_callback(self._on_dtc_fill)

    def _setup_signals(self):
        def handler(signum, frame):
            print(f"\n[BOT] Signal {signum} recu, arret propre...")
            self.stop_event.set()
        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, handler)

    def _on_dtc_fill(self, fill):
        """Callback DTC quand TP ou SL est rempli (close de trade).

        Thread : daemon `_recv_loop` du DTCConnector. Doit prendre _pos_lock.
        """
        order_id = getattr(fill, "order_id", "")
        fill_price = getattr(fill, "fill_price", 0.0)
        if not order_id or not fill_price:
            return
        with self._pos_lock:
            symbol = self._order_to_symbol.get(order_id)
            if not symbol or symbol not in self.active_positions:
                return  # parent fill, autre bot, ou deja close
            pos = self.active_positions[symbol]

            # Determine TP ou SL
            is_tp = (order_id == pos.get("tp_cid"))
            is_sl = (order_id == pos.get("sl_cid"))
            if not (is_tp or is_sl):
                return  # parent fill, ignore

            # Calcule pnl en ticks
            entry = pos["entry"]
            side = pos["side"]
            if side == "BUY":
                pnl_ticks = (fill_price - entry) / TICK_SIZE
            else:
                pnl_ticks = (entry - fill_price) / TICK_SIZE

            exit_type = "TP" if is_tp else "SL"
            tick_val = TICK_VALUE.get(symbol, 1.0)
            pnl_dollar = pnl_ticks * tick_val * self.cfg.quantity

            print(f"[{symbol}] CLOSE {exit_type} fill={fill_price:.2f} "
                  f"pnl={pnl_ticks:+.0f}t (${pnl_dollar:+.2f})")

            # Cleanup tracking
            del self.active_positions[symbol]
            self._order_to_symbol.pop(pos.get("parent_id"), None)
            self._order_to_symbol.pop(pos.get("tp_cid"), None)
            self._order_to_symbol.pop(pos.get("sl_cid"), None)

        self.risk.on_trade_close(symbol, pnl_ticks)
        self._write_state()

    def _write_state(self):
        """Ecrit state.json pour consommation dashboard."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "bot": "databento_bot",
                "trade_account": self.cfg.trade_account,
                "active_positions": {
                    sym: {
                        **{k: v for k, v in pos.items()
                           if k not in ("ts_open",)},
                        "ts_open": pos["ts_open"].isoformat() if "ts_open" in pos else None,
                    }
                    for sym, pos in self.active_positions.items()
                },
                "risk": {
                    "trades_today": self.risk.trades_today,
                    "consecutive_sl": self.risk.consecutive_sl,
                },
            }
            tmp = STATE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            tmp.replace(STATE_FILE)
        except OSError as e:
            print(f"[STATE] write failed: {e}")

    def _process_symbol(self, symbol: str):
        df = load_last_bar(symbol)
        if df is None or df.empty:
            return

        bar_ts = df["ts_event"].iloc[0]
        if self.last_bar_ts[symbol] is not None and bar_ts == self.last_bar_ts[symbol]:
            return  # already processed
        self.last_bar_ts[symbol] = bar_ts

        # Inference
        score_buy = self.models.predict(symbol, "buy", df.copy())
        score_sell = self.models.predict(symbol, "sell", df.copy())
        if score_buy is None and score_sell is None:
            print(f"[{symbol}] {bar_ts} : no model loaded")
            return

        decision = "HOLD"
        score = 0.0
        if score_buy is not None and score_buy > self.cfg.threshold_buy:
            decision = "BUY"
            score = score_buy
        elif score_sell is not None and score_sell > self.cfg.threshold_sell:
            decision = "SELL"
            score = score_sell

        close = float(df["close"].iloc[0])
        buy_str = f"{score_buy:.3f}" if score_buy is not None else "NA"
        sell_str = f"{score_sell:.3f}" if score_sell is not None else "NA"
        print(f"[{symbol}] {bar_ts} close={close:.2f} "
              f"buy={buy_str} sell={sell_str} -> {decision}")

        if decision == "HOLD":
            return

        # Risk check
        allowed, reason = self.risk.can_trade(symbol)
        if not allowed:
            print(f"[{symbol}] RISK BLOCK : {reason}")
            return

        # SL/TP via SLTPEngine
        try:
            sltp = self.sltp_engines[symbol].evaluate_single(
                df.iloc[0].to_dict(), 1 if decision == "BUY" else -1
            )
            if not sltp.valid:
                print(f"[{symbol}] SLTP invalid : {getattr(sltp, 'reason', 'no reason')}")
                return
            print(f"[{symbol}] {decision} entry={close:.2f} "
                  f"sl_ticks={sltp.sl_ticks} tp_ticks={sltp.tp1_ticks} "
                  f"sl_wall={sltp.sl_wall} tp_wall={sltp.tp1_wall}")
        except (AttributeError, KeyError) as e:
            print(f"[{symbol}] SLTP error : {e}")
            return

        # Order execution
        if self.cfg.dry_run:
            print(f"[{symbol}] DRY RUN — no order sent")
            return

        # Check 1 position active max par symbol
        with self._pos_lock:
            if symbol in self.active_positions:
                print(f"[{symbol}] Already in position, skip")
                return

        # Calcule sl_price, tp_price depuis entry + ticks
        side_dtc = DTC_BUY if decision == "BUY" else DTC_SELL
        if decision == "BUY":
            sl_price = close - sltp.sl_ticks * TICK_SIZE
            tp_price = close + sltp.tp1_ticks * TICK_SIZE
        else:
            sl_price = close + sltp.sl_ticks * TICK_SIZE
            tp_price = close - sltp.tp1_ticks * TICK_SIZE

        # Get DTC contract symbol (ESM26-CME, NQM26-CME)
        if not _DTC_OK or symbol not in BOT_INSTRUMENTS:
            print(f"[{symbol}] DTC not available, skip order")
            return
        contract = BOT_INSTRUMENTS[symbol].contract

        print(f"[{symbol}] SEND ORDER {decision} {self.cfg.quantity}x {contract} "
              f"@ market entry~{close:.2f} sl={sl_price:.2f} tp={tp_price:.2f} "
              f"[{self.cfg.trade_account}]")

        try:
            parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract,
                side=side_dtc,
                quantity=self.cfg.quantity,
                sl_price=sl_price,
                tp_price=tp_price,
                trade_account=self.cfg.trade_account,
            )
        except Exception as e:
            print(f"[{symbol}] DTC send_market_order failed: {type(e).__name__}: {e}")
            return

        if not parent_id:
            print(f"[{symbol}] DTC order rejected (parent_id empty)")
            return

        # Track position
        with self._pos_lock:
            self.active_positions[symbol] = {
                "parent_id": parent_id,
                "tp_cid": tp_cid,
                "sl_cid": sl_cid,
                "side": decision,
                "side_dtc": side_dtc,
                "entry": close,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "sl_ticks": sltp.sl_ticks,
                "tp_ticks": sltp.tp1_ticks,
                "score": score,
                "ts_open": datetime.now(timezone.utc),
            }
            self._order_to_symbol[parent_id] = symbol
            self._order_to_symbol[tp_cid] = symbol
            self._order_to_symbol[sl_cid] = symbol

        self.risk.on_trade_open(symbol)
        self._write_state()
        print(f"[{symbol}] POSITION OPEN parent={parent_id[:12]} tp={tp_cid[:12]} sl={sl_cid[:12]}")

    def run(self):
        self._setup_signals()
        print("=" * 70)
        print(f" DATABENTO BOT (ML pure) — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
        print(f" Threshold buy={self.cfg.threshold_buy} sell={self.cfg.threshold_sell}")
        print(f" Poll interval={self.cfg.poll_interval}s")
        print(f" Mode: {'DRY RUN' if self.cfg.dry_run else 'PAPER (Sim3)' if self.cfg.paper_mode else 'LIVE AMP'}")
        print("=" * 70)

        while not self.stop_event.is_set():
            for sym in SYMBOLS:
                try:
                    self._process_symbol(sym)
                except Exception as e:
                    print(f"[{sym}] EXCEPTION : {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()

            # Sleep with interrupt support
            for _ in range(self.cfg.poll_interval):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        # Cleanup
        if self.dtc:
            with self._pos_lock:
                n_open = len(self.active_positions)
            if n_open > 0:
                print(f"[BOT] WARNING: {n_open} positions still open at shutdown — "
                      f"DTC stays connected for OCO management. Press Ctrl+C again to force.")
            else:
                self.dtc.disconnect()
                print("[BOT] DTC disconnected.")
        print("[BOT] Stopped.")


def main():
    ap = argparse.ArgumentParser(description="Databento ML Bot (pure 420 features)")
    ap.add_argument("--threshold-buy", type=float, default=DEFAULT_THRESHOLD_BUY)
    ap.add_argument("--threshold-sell", type=float, default=DEFAULT_THRESHOLD_SELL)
    ap.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SEC,
                    help="Secondes entre checks (default 30)")
    ap.add_argument("--live", action="store_true",
                    help="LIVE AMP order (default = paper Sim3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Log signaux uniquement, no orders")
    args = ap.parse_args()

    cfg = BotConfig(
        threshold_buy=args.threshold_buy,
        threshold_sell=args.threshold_sell,
        poll_interval=args.poll_interval,
        paper_mode=not args.live,
        dry_run=args.dry_run,
    )

    bot = DatabentoBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
