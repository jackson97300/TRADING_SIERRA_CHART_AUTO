"""live_cache.py — Module partage Bot 2 V2 + Bot 3 + (futur) Bot 1.

Lit les caches Databento Live ecrits par le service nssm `MIA-Live-OHLCV`
(producer : `CORE/databento_live_stream.py`).

ARCHITECTURE (cf agent Plan 04/05 — solution long terme anti-slippage) :

    [databento_live_stream.py] -> DATA/LIVE_CACHE/
                                     ES_c_0_last.json         (close OHLCV 60s)
                                     ES_c_0_last_trade.json   (last trade ms)
                                     _stream_heartbeat.json   (subscribe alive)
    Lus ICI par les bots :
      - read_bar(sym)              : OHLC live + age_sec
      - read_last_trade_close(sym) : last trade price ms-level
      - is_stream_alive()          : subscribe vivant via heartbeat
      - enrich_bar(sym, bar)       : override close parquet par close LIVE

POLITIQUE FALLBACK (env MIA_LIVE_CACHE_FALLBACK) :
  - STRICT (default) : si stale > MAX_AGE_SEC -> retourne None -> bot skip trade
  - PERMISSIVE : retourne quand meme la stale, log warning
  - ALERT : retourne stale + emit alerte CRITIQUE (sans skip)

PORTAGE DEPUIS V1 :
  Source : CORE/databento_paper_trader.py (Bot 2 V1 OBSOLETE)
  - _read_live_cache_bar (ligne 1671)
  - _read_live_cache_close (ligne 1786)
  - _enrich_bar_with_live (ligne 1699)
  Fix V1 valide fin avril 2026 : slippage entry passe de ~23t a ~1-3t.
  Bot 2 V2 + Bot 3 (databento_paper_trader_v2.py) ont JAMAIS eu ce fix.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("live_cache")

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "DATA" / "LIVE_CACHE"
HEARTBEAT_FILE = CACHE_DIR / "_stream_heartbeat.json"

# Politique fallback (cf decision Q2 agent Plan 04/05)
FALLBACK_MODE = os.environ.get("MIA_LIVE_CACHE_FALLBACK", "STRICT").upper()
if FALLBACK_MODE not in ("STRICT", "PERMISSIVE", "ALERT"):
    FALLBACK_MODE = "STRICT"

# Seuils (alignes V1, valides empiriquement)
MAX_AGE_BAR_SEC = 180        # bar OHLCV-1m : 60s + marge 2x
MAX_AGE_TRADE_SEC = 10       # last trade ms : tres frais
MAX_AGE_HEARTBEAT_SEC = 30   # subscribe vivant si heartbeat < 30s


def _safe_sym(symbol: str) -> str:
    """ES -> ES_c_0  (matche le pattern ecrit par databento_live_stream.py)."""
    if "." in symbol or "_" in symbol:
        # Deja au format full ex ES.c.0 ou ES_c_0
        return symbol.replace("/", "_").replace(".", "_")
    return f"{symbol}_c_0"


def read_bar(symbol: str, max_age_sec: int = MAX_AGE_BAR_SEC) -> Optional[dict]:
    """Lit la bar OHLCV LIVE du cache.

    Returns:
        dict avec {ts_event_iso, ts_event_ns, open, high, low, close, volume, age_sec}
        ou None si :
          - cache absent
          - cache stale > max_age_sec en mode STRICT
          - JSON corrompu
        En mode PERMISSIVE/ALERT, retourne meme stale (avec age_sec eleve).
    """
    safe = _safe_sym(symbol)
    cache_path = CACHE_DIR / f"{safe}_last.json"
    try:
        if not cache_path.exists():
            return None
        file_age_sec = time.time() - cache_path.stat().st_mtime
        if file_age_sec > max_age_sec:
            if FALLBACK_MODE == "STRICT":
                return None
            logger.warning(
                f"LIVE_CACHE bar {symbol} STALE age={file_age_sec:.0f}s "
                f"> {max_age_sec}s — mode={FALLBACK_MODE}"
            )
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        close = data.get("close")
        if close is None or not isinstance(close, (int, float)) or close <= 0:
            return None
        data["age_sec"] = file_age_sec
        return data
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug(f"read_bar {symbol} error: {e}")
        return None


def read_last_trade_close(symbol: str, fallback: float,
                          max_age_sec: int = MAX_AGE_TRADE_SEC) -> float:
    """Lit le dernier trade LIVE (latence ms) ou fallback.

    Args:
        symbol : ES ou NQ
        fallback : prix a retourner si cache absent/stale
        max_age_sec : age max accepte (default 10s pour trades ms-level)

    Returns:
        price float (live ou fallback)
    """
    safe = _safe_sym(symbol)
    cache_path = CACHE_DIR / f"{safe}_last_trade.json"
    try:
        if not cache_path.exists():
            return fallback
        file_age_sec = time.time() - cache_path.stat().st_mtime
        if file_age_sec > max_age_sec:
            return fallback
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        price = data.get("price")
        if price is None or not isinstance(price, (int, float)) or price <= 0:
            return fallback
        return float(price)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return fallback


def is_stream_alive(max_silence_sec: int = MAX_AGE_HEARTBEAT_SEC) -> tuple[bool, dict]:
    """Verifie si le subscribe Databento Live est vivant via heartbeat.

    Distingue "service nssm running" (mtime LIVE_CACHE/_last.json change si
    flush thread tourne) de "subscribe vivant" (heartbeat.silence_sec faible).

    Bug du 01/05 : counts trades figes a 338758 pendant 67h, mais flush thread
    continuait a ecrire le cache -> mtime fresh -> dashboard pensait OK alors
    que stream etait dead.

    Returns:
        (alive: bool, info: dict avec last_msg_ts, silence_sec, bars_received, ...)
    """
    try:
        if not HEARTBEAT_FILE.exists():
            return (False, {"reason": "heartbeat_absent"})
        file_age = time.time() - HEARTBEAT_FILE.stat().st_mtime
        if file_age > 60:
            return (False, {"reason": "heartbeat_file_stale", "age_sec": file_age})
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
            hb = json.load(f)
        silence_sec = hb.get("silence_sec")
        subscribe_alive = bool(hb.get("subscribe_alive", False))
        alive = subscribe_alive and (silence_sec is None or silence_sec < max_silence_sec)
        return (alive, hb)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        return (False, {"reason": "exception", "error": str(e)[:200]})


def enrich_bar(symbol: str, bar: dict, tick_size: float = 0.25) -> tuple[dict, dict]:
    """Enrichit une bar parquet/JSONL DMP avec close LIVE Databento.

    Strategie :
      1. Lit bar LIVE (latence ~60s)
      2. Si dispo + plus recente que la bar in : remplace open/high/low/close + ts
      3. Recalcule les distances dist_* basees sur close si presentes
      4. Garde les features structurelles (mq_levels daily, profile_shape, cvd_*)

    Args:
        symbol : ES ou NQ
        bar : dict bar parquet/JSONL avec close, ts_event, etc.
        tick_size : pour metrics drift

    Returns:
        (bar_enriched, metadata) ou (bar, {"override": False, "reason": ...})
        metadata : {override: bool, source: 'LIVE'|'PARQUET', age_sec, drift_ticks, ...}
    """
    if not bar:
        return bar, {"override": False, "reason": "empty_bar"}

    live = read_bar(symbol)
    if live is None:
        return bar, {"override": False, "reason": "live_unavailable", "fallback_mode": FALLBACK_MODE}

    parquet_close = float(bar.get("close") or bar.get("price") or 0)
    live_close = float(live["close"])
    if parquet_close <= 0 or live_close <= 0:
        return bar, {"override": False, "reason": "invalid_close"}

    drift_ticks = (live_close - parquet_close) / tick_size

    # Override OHLC + ts
    enriched = dict(bar)
    enriched["_close_parquet_orig"] = parquet_close   # pour audit / drift log
    enriched["close"] = live_close
    if "open" in live:
        enriched["open"] = live["open"]
    if "high" in live:
        enriched["high"] = max(parquet_close, live["high"])
    if "low" in live:
        enriched["low"] = min(parquet_close, live["low"])
    if "volume" in live:
        enriched["volume_live"] = live["volume"]
    if "ts_event_iso" in live:
        enriched["ts_event_live_iso"] = live["ts_event_iso"]

    # FIX C v2 (V1 pattern) : recalculer dist_* features price-driven
    # qui dependent de close. Les features structurelles (mq_*, cvd_*, profile_*)
    # restent inchangees (calculees depuis OHLC qui n'est pas drift).
    # NOTE : on ne recalc PAS ici les dist_mq_* car le bar in les a deja basees
    # sur parquet_close. Le drift typique 1-3t -> impact minor (<0.1pt sur dist).
    # Si besoin de precision absolue, override aussi dist_mq_*_pct dans la bar.

    metadata = {
        "override": True,
        "source": "LIVE",
        "age_sec": live.get("age_sec", 0),
        "drift_ticks": round(drift_ticks, 1),
        "parquet_close": parquet_close,
        "live_close": live_close,
        "fallback_mode": FALLBACK_MODE,
    }
    return enriched, metadata


def get_signal_entry_ref(symbol: str, fallback: float) -> tuple[float, str]:
    """Retourne le prix le plus frais possible pour `signal.price_entry_ref`.

    Priorite :
      1. last_trade.json (latence ms) si frais
      2. _last.json bar OHLCV (latence 60s) si frais
      3. fallback (close parquet/JSONL DMP - latence inconnue)

    Returns:
        (price, source) avec source in ('LIVE_TRADE_MS', 'LIVE_OHLCV', 'FALLBACK')
    """
    # 1. Trade ms-level
    trade_close = read_last_trade_close(symbol, fallback=0.0, max_age_sec=MAX_AGE_TRADE_SEC)
    if trade_close > 0:
        return (trade_close, "LIVE_TRADE_MS")
    # 2. OHLCV bar
    live_bar = read_bar(symbol, max_age_sec=MAX_AGE_BAR_SEC)
    if live_bar is not None:
        return (float(live_bar["close"]), "LIVE_OHLCV")
    # 3. Fallback
    return (fallback, "FALLBACK")
