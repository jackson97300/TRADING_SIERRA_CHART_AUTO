"""
HTF Alignment Filter (01/05/2026 soir — Jackson "multi-tf alignment")
======================================================================

Filtre les signaux 1-min vs tendance 5-min (EMA slope).

Backtest 78 trades 7 jours :
  ALIGNED       : N=36 WR=27.8% PnL=-$678
  COUNTER-TREND : N=42 WR=21.4% PnL=-$1785
  Si filter ON → +$1785 economises (filtrer 42 counter-trend)

SHORT counter-trend particulierement catastrophique : WR 13.3% vs 35.7% aligned.

🚨 MODE INITIAL : OBSERVE-ONLY TOTAL (anti-pattern 11)
=========================================================
Code-reviewer NOGO 01/05 soir sur deploy VETO :
  - N=15 SHORT counter < seuil 30 trades (regle Jackson 30/04)
  - Pas de walk-forward DSR Lopez
  - Bot 2 instable (fix v2 SLTPEngine en re-review)
  - Bug silencieux possible (buffer 1m bars Bot 2 non verifie)

Plan rollout :
  J+0 (deploy ce soir) : OBSERVE-ONLY total, 0 block, log JSONL dedie
  J+7 : re-audit sur N reel ~50-60 trades production
  Si signal SHORT counter-trend toujours net (PSR>0.95, CI bootstrap [+,+]) :
    → activer veto SHORT seul
  Si signal LONG counter-trend nuance :
    → reste OBSERVE seul

Architecture :
  - Module pur, isole, configurable
  - Calcul EMA 5m slope en live depuis bars 1m disponibles
  - JSONL dedie LOGS/htf_alignment/ pour audit J+7
  - Codes log catalog : HTF_OBSERVE_PASS / HTF_OBSERVE_COUNTER_SHORT /
    HTF_OBSERVE_COUNTER_LONG / HTF_OBSERVE_NO_DATA
"""

from dataclasses import dataclass
from typing import Optional, Literal
from pathlib import Path
import json
import time
from datetime import datetime, timezone
import pandas as pd
import numpy as np

EMA_PERIOD = 20            # EMA 20 sur bars 5m (= ~100 bars 1m de lookback)
SLOPE_LAG = 3              # Diff EMA - EMA[lag 3] = slope sur 15 min
MIN_BARS_5M_REQUIRED = 25  # EMA(20) + 3 lag + marge = 25 bars 5m min

# 🚨 Config par defaut : OBSERVE-ONLY TOTAL (J+0 → J+7)
# Aucun BLOCK actif. Logger JSONL pour audit J+7 puis decision data-driven.
# Toggle individuel possible via veto_short_counter / veto_long_counter mais
# par defaut TOUS A FALSE = pure observation.
DEFAULT_CONFIG = {
    "ES": {
        "enabled": True,                # Module actif (calcul slope + log)
        "veto_short_counter": False,    # 🚨 OBSERVE seul J+0 (active J+7 si robuste)
        "veto_long_counter": False,     # 🚨 OBSERVE seul J+0 (signal moins clair)
        "min_slope_threshold": 0.0,
    },
    "NQ": {
        "enabled": True,
        "veto_short_counter": False,    # 🚨 OBSERVE seul J+0
        "veto_long_counter": False,     # 🚨 OBSERVE seul J+0
        "min_slope_threshold": 0.0,
    },
}


HTFAction = Literal["PASS", "BLOCK_COUNTER_SHORT", "BLOCK_COUNTER_LONG", "OBSERVE_COUNTER", "NO_DATA"]


@dataclass
class HTFDecision:
    action: HTFAction
    slope_5m: float
    aligned: Optional[bool]
    reason: str


class HTFAlignmentFilter:
    """Filtre alignement multi-timeframe (1m signal vs 5m EMA slope)."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config if config is not None else DEFAULT_CONFIG

    def compute_5m_slope(self, bars_1m: pd.DataFrame) -> Optional[float]:
        """
        Calcule slope EMA 5m a partir des bars 1m.

        Args:
            bars_1m : DataFrame avec columns ['ts_event', 'open', 'high', 'low', 'close', 'volume']
                       trie par ts_event ascendant. Au moins 100 bars recommandes.

        Returns:
            slope_5m (float) ou None si pas assez de data.
        """
        if bars_1m is None or len(bars_1m) < MIN_BARS_5M_REQUIRED * 5:
            return None
        df = bars_1m.copy()
        if "ts_event" not in df.columns:
            return None
        # Set index ts_event pour resample
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index("ts_event")
        # Resample 1m → 5m
        df_5m = df.resample("5min").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna()
        if len(df_5m) < MIN_BARS_5M_REQUIRED:
            return None
        # EMA + slope (close - close lag SLOPE_LAG)
        ema = df_5m["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
        if len(ema) < SLOPE_LAG + 1:
            return None
        slope = ema.iloc[-1] - ema.iloc[-1 - SLOPE_LAG]
        return float(slope)

    def evaluate(self, symbol: str, direction: str, bars_1m: pd.DataFrame) -> HTFDecision:
        """
        Evalue alignement HTF pour un signal.

        Args:
            symbol : "ES" ou "NQ"
            direction : "LONG" ou "SHORT"
            bars_1m : DataFrame des bars 1m recentes (au moins 100 bars)

        Returns:
            HTFDecision avec action et raison.
        """
        cfg = self.config.get(symbol, {})
        if not cfg.get("enabled", False):
            return HTFDecision(action="PASS", slope_5m=float("nan"),
                                 aligned=None, reason="htf_disabled")

        slope = self.compute_5m_slope(bars_1m)
        if slope is None:
            return HTFDecision(action="NO_DATA", slope_5m=float("nan"),
                                 aligned=None, reason="insufficient_bars_1m")

        threshold = cfg.get("min_slope_threshold", 0.0)
        # Aligned LONG : slope > threshold
        # Aligned SHORT : slope < -threshold
        if direction == "LONG":
            aligned = slope > threshold
        else:  # SHORT
            aligned = slope < -threshold

        if aligned:
            return HTFDecision(action="PASS", slope_5m=slope, aligned=True,
                                reason=f"aligned_slope_{slope:+.2f}")

        # Counter-trend
        if direction == "SHORT" and cfg.get("veto_short_counter", False):
            return HTFDecision(action="BLOCK_COUNTER_SHORT", slope_5m=slope,
                                 aligned=False,
                                 reason=f"short_counter_uptrend_slope_{slope:+.2f}")
        if direction == "LONG" and cfg.get("veto_long_counter", False):
            return HTFDecision(action="BLOCK_COUNTER_LONG", slope_5m=slope,
                                 aligned=False,
                                 reason=f"long_counter_downtrend_slope_{slope:+.2f}")

        # Observe-only (counter-trend mais pas de veto pour cette direction)
        return HTFDecision(action="OBSERVE_COUNTER", slope_5m=slope, aligned=False,
                             reason=f"counter_trend_observe_slope_{slope:+.2f}")


# ═════════════════════════════════════════════════════════════════════
# JSONL LOGGER DEDIE pour audit J+7 (regle souveraine logs 01/05)
# Filter rate ~50% > 30% → JSONL dedie obligatoire
# ═════════════════════════════════════════════════════════════════════

def log_htf_decision(decision: HTFDecision, signal_id: str, symbol: str,
                       direction: str, signal_price: float,
                       executed: bool = True, jsonl_dir: Optional[Path] = None) -> None:
    """Append HTF decision a un JSONL dedie pour audit J+7.

    Format : 1 ligne JSON par decision avec ts, signal_id, symbol, direction,
    slope_5m, action, aligned, executed, signal_price.

    Append-only safe (pas de lock, multi-thread OK).
    Si jsonl_dir is None : ROOT/LOGS/htf_alignment/htf_v1_{date}.jsonl
    """
    if jsonl_dir is None:
        root = Path(__file__).resolve().parents[1]
        jsonl_dir = root / "LOGS" / "htf_alignment"
    try:
        jsonl_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = jsonl_dir / f"htf_v1_{date_str}.jsonl"
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction,
            "signal_price": signal_price,
            "action": decision.action,
            "slope_5m": (None if pd.isna(decision.slope_5m) else float(decision.slope_5m)),
            "aligned": decision.aligned,
            "executed": executed,
            "reason": decision.reason,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        # Logger ne doit jamais casser le bot. Silent fail.
        pass
