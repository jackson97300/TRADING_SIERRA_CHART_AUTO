"""databento_live_stream_v2.py — V2 : reconnect natif SDK Databento.

REFACTOR 28/05/2026 (cause racine 54 restarts/jour) :
  Le SDK Databento expose `reconnect_policy=ReconnectPolicy.RECONNECT` qui gere :
    - Reconnexion automatique exponential backoff 1s,2s,4s,8s...60s (+jitter)
    - Resubscription automatique apres reconnect (toutes les subscriptions)
    - 10 min timeout par defaut (couvre Sunday gateway restart Databento)

  Le V1 (databento_live_stream.py) utilisait reconnect_policy=NONE (defaut SDK)
  + un watchdog manuel qui appelait `client.stop()` a 90s silence. `stop()` ne
  recreait jamais le client -> process zombie -> watchdog `mia_watchdog.py`
  finissait par restart le service (54 fires en 27/05).

  Le V2 utilise UNIQUEMENT le SDK reconnect natif + add_reconnect_callback
  pour observer les gaps. Suppression complete du watchdog manuel + boucle
  externe + FORCE_RECONNECT 4h. Le SDK fait tout cela mieux et nativement.

IO PRESERVEE (compat consumers existants) :
  - DATA/LIVE_CACHE/{ES_c_0,NQ_c_0,MGC_v_0}_last.json         (OHLCV bar close)
  - DATA/LIVE_CACHE/{ES_c_0,NQ_c_0,MGC_v_0}_last_trade.json   (last trade ms)
  - DATA/LIVE_CACHE/_stream_heartbeat.json                    (alive + silence)
  - DATA/LIVE_CACHE/trades/{sym}/YYYYMMDD.jsonl               (buffer rolling 7j)
  - DATA/LOGS/databento_live_stream.log                       (log meme nom)

USAGE :
  python -X utf8 CORE/databento_live_stream_v2.py

Tourne en boucle infinie via service nssm `MIA-Live-OHLCV` (en remplacement V1).
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import databento as db

# Import ReconnectPolicy. Verifie empiriquement SDK 0.75.0 : exposé via `databento`
# (PAS `databento.live`). Defaut SDK = ReconnectPolicy.NONE (cause racine V1).
try:
    from databento import ReconnectPolicy  # SDK >=0.50
except ImportError:
    try:
        from databento.live import ReconnectPolicy  # fallback ancien path
    except ImportError:
        ReconnectPolicy = None  # fallback: passer string "reconnect"

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "DATA" / "LIVE_CACHE"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 29/05/2026 FIX Jackson : MGC.v.0 ne flow JAMAIS de bars (audit 23:55-03:00 UTC),
# donc subscribe_alive global = False perpetuel (force True == len(SYMBOLS) ages valid).
# Cela declenche le watchdog externe + spam alertes + reach restart cap nssm 3/h.
# Kill switch env var STREAM_SKIP_MGC=1 pour drop MGC subscription (Asia / overnight
# stabilisation). Defaut = MGC inclus (back-compat). A re-investiguer pourquoi MGC
# ne stream pas (peut-etre ticker change, ou volume-based seulement actif RTH GC).
if os.environ.get("STREAM_SKIP_MGC", "0") == "1":
    SYMBOLS = ["ES.c.0", "NQ.c.0"]
else:
    SYMBOLS = ["ES.c.0", "NQ.c.0", "MGC.v.0"]

# Logging (meme path que V1 pour compat tail/grep operationnel)
LOG_DIR = ROOT / "DATA" / "LOGS"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "databento_live_stream.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("live_stream_v2")

# Etat global
_running = True
_inst_to_sym: dict[int, str] = {}
_bars_received: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_last_bar_ts: dict[str, str] = {sym: "?" for sym in SYMBOLS}

# Trade caches (latence ms)
_last_trade_by_sym: dict[str, dict] = {}
_trades_received: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_trade_lock = threading.Lock()

# Buffer rolling Trades JSONL daily (input Chantier 3 Live Enricher)
TRADE_BUFFER_FLUSH_INTERVAL_SEC = 5
TRADE_BUFFER_PURGE_DAYS = 7
TRADE_BUFFER_DIR = CACHE_DIR / "trades"
TRADE_BUFFER_DIR.mkdir(parents=True, exist_ok=True)
TRADE_BUFFER_MAXLEN = 500_000
TRADE_BUFFER_MAX_WRITE_FAILS = 3
_trade_buffer_by_sym: dict[str, deque] = {
    sym: deque(maxlen=TRADE_BUFFER_MAXLEN) for sym in SYMBOLS
}
_trade_buffer_lock = threading.Lock()
_trades_persisted_count: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_trade_buffer_dropped: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_trade_buffer_write_fails: dict[str, int] = {sym: 0 for sym in SYMBOLS}

# Heartbeat / observability
HEARTBEAT_INTERVAL_SEC = 5
HEARTBEAT_FILE = CACHE_DIR / "_stream_heartbeat.json"
# Seuil GLOBAL pour subscribe_alive (compat V1 stricte) — consume par
# `BOT/mia_watchdog.check_stream_subscribe_alive`. Garder 90s pour ne pas
# changer la semantique cote watchdog (PATCH 1 code-reviewer 28/05).
WATCHDOG_TIMEOUT_SEC = 90
# Per-symbol thresholds = utilises UNIQUEMENT pour logs WARN granulaire dans
# data_silence_per_sym (info dashboard), pas pour subscribe_alive boolean.
DATA_FRESHNESS_THRESHOLD_SEC = {
    "ES.c.0": 90,
    "NQ.c.0": 90,
    "MGC.v.0": 600,  # MGC tolere trous overnight (volume-based)
}

# Discord alerting
DISCORD_WEBHOOK_PATH = ROOT / "BOT" / "alert_config.json"

# Watchdog ts par symbole (uniquement pour heartbeat dashboard)
_last_data_ts: dict[str, float] = {sym: 0.0 for sym in SYMBOLS}
_data_lock = threading.Lock()
_last_msg_ts: float = 0.0
_msg_lock = threading.Lock()

# Reconnect events (observabilite)
_reconnect_count: int = 0
_reconnect_last_gap_sec: float = 0.0
_reconnect_lock = threading.Lock()
# Dedup Discord : cooldown alert reconnect + alert transition subscribe_alive (anti-flood)
_last_reconnect_alert_ts: float = 0.0
_last_subscribe_alive_alert_ts: float = 0.0
_DISCORD_COOLDOWN_SEC = 900  # 15 min entre alertes meme type

# 29/05 FIX V2 : variable globale pour permettre signal handler de debloquer
# block_for_close(timeout=None) via client.stop() propre.
# Cf diagnostic complet : timeout=60 forcait SDK terminate() → boucle restart 1314x.
_client_global = None


def _signal_handler(signum, frame):
    global _running, _client_global
    logger.info(f"Signal {signum} received, stopping...")
    _running = False
    # Debloque block_for_close en cours via SDK Live.stop() (close propre,
    # PAS terminate brutal). Sans cet appel, block_for_close(timeout=None)
    # ne se debloque pas → process Python hang sur SIGTERM nssm.
    try:
        if _client_global is not None:
            _client_global.stop()
    except Exception as e:
        logger.warning(f"_client_global.stop() failed in signal handler: {e}")


def _atomic_write_cache(symbol: str, payload: dict) -> None:
    safe_sym = symbol.replace("/", "_").replace(".", "_")
    target = CACHE_DIR / f"{safe_sym}_last.json"
    tmp = target.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, target)
    except OSError as e:
        logger.warning(f"write cache fail {symbol}: {e}")


def _build_callback():
    """Closure callback principal pour records OHLCV/Trade/SymbolMapping/Error."""

    def callback(record):
        global _last_msg_ts
        with _msg_lock:
            _last_msg_ts = time.time()

        if isinstance(record, db.SymbolMappingMsg):
            try:
                inst_id = record.instrument_id
                sym = record.stype_in_symbol
                _inst_to_sym[inst_id] = sym
                logger.info(f"MAPPING instrument_id={inst_id} -> {sym}")
            except AttributeError as e:
                logger.warning(f"SymbolMappingMsg parse fail: {e}")
            return

        if isinstance(record, db.ErrorMsg):
            logger.error(f"Databento ErrorMsg: {getattr(record, 'err', record)}")
            return

        if isinstance(record, db.OHLCVMsg):
            try:
                inst_id = record.instrument_id
                sym = _inst_to_sym.get(inst_id)
                if sym is None:
                    return
                ts_event_ns = record.ts_event
                ts_event_dt = datetime.fromtimestamp(ts_event_ns / 1e9, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                latency_s = (now - ts_event_dt).total_seconds()
                payload = {
                    "symbol": sym,
                    "instrument_id": inst_id,
                    "ts_event_iso": ts_event_dt.isoformat(),
                    "ts_event_ns": ts_event_ns,
                    "open": record.open / 1e9 if record.open else None,
                    "high": record.high / 1e9 if record.high else None,
                    "low": record.low / 1e9 if record.low else None,
                    "close": record.close / 1e9 if record.close else None,
                    "volume": int(record.volume) if record.volume else 0,
                    "latency_s": round(latency_s, 1),
                    "written_at_iso": now.isoformat(),
                    "written_at_ts": now.timestamp(),
                }
                _atomic_write_cache(sym, payload)
                _bars_received[sym] = _bars_received.get(sym, 0) + 1
                _last_bar_ts[sym] = ts_event_dt.strftime("%H:%M:%S")
                with _data_lock:
                    _last_data_ts[sym] = time.time()
                logger.info(
                    f"[{sym}] {ts_event_dt:%H:%M:%S} close={payload['close']} "
                    f"vol={payload['volume']} lat={latency_s:.1f}s "
                    f"(bars: {_bars_received[sym]})"
                )
            except Exception as e:
                logger.exception(f"OHLCVMsg handler fail: {e}")
            return

        if isinstance(record, db.TradeMsg):
            try:
                inst_id = record.instrument_id
                sym = _inst_to_sym.get(inst_id)
                if sym is None:
                    return
                price = record.price / 1e9 if record.price else None
                if price is None or price <= 0:
                    return
                ts_event_ns = record.ts_event
                side_raw = getattr(record, "side", None)
                side_str = str(side_raw) if side_raw is not None else "?"
                trade_dict = {
                    "symbol": sym,
                    "instrument_id": inst_id,
                    "price": price,
                    "size": int(record.size) if record.size else 0,
                    "side": side_str,
                    "ts_event_ns": ts_event_ns,
                    "captured_at_ts": time.time(),
                }
                with _trade_lock:
                    _last_trade_by_sym[sym] = trade_dict
                    _trades_received[sym] = _trades_received.get(sym, 0) + 1
                with _trade_buffer_lock:
                    _trade_buffer_by_sym[sym].append(trade_dict)
                with _data_lock:
                    _last_data_ts[sym] = time.time()
            except Exception as e:
                logger.exception(f"TradeMsg handler fail: {e}")
            return

    return callback


def _on_reconnect(gap_start, gap_end):
    """Callback SDK quand reconnexion automatique reussit.

    Appelle par le SDK uniquement si reconnect_policy != NONE.
    Args :
      - gap_start : pd.Timestamp UTC du dernier ts_event de la session perdue
      - gap_end   : pd.Timestamp UTC du Metadata.start de la nouvelle session
    """
    global _reconnect_count, _reconnect_last_gap_sec
    try:
        gap_sec = (gap_end - gap_start).total_seconds()
    except Exception:
        gap_sec = -1.0
    with _reconnect_lock:
        _reconnect_count += 1
        _reconnect_last_gap_sec = gap_sec
        n = _reconnect_count
    # PATCH 2 code-reviewer 28/05 : purger _inst_to_sym avant resubscribe.
    # Databento peut re-emettre instrument_id different apres reconnect
    # (rollover front-month, re-mapping serveur). SymbolMappingMsg sera re-emis
    # automatiquement sur la nouvelle session, peuplant a nouveau _inst_to_sym.
    n_purged = len(_inst_to_sym)
    _inst_to_sym.clear()
    logger.warning(
        f"STREAM_RECONNECTED #{n} gap_start={gap_start} gap_end={gap_end} "
        f"gap_sec={gap_sec:.1f} (mapping purged: {n_purged} entries)"
    )
    # Emit event structure JSONL (PATCH 3 - cf log_catalog.STREAM_RECONNECTED)
    _emit_event_safe(
        "STREAM_RECONNECTED",
        ctx={
            "count": n,
            "gap_sec": gap_sec,
            "gap_start": str(gap_start),
            "gap_end": str(gap_end),
            "mapping_purged": n_purged,
        },
    )
    # Alerte Discord proportionnelle au gap + dedup anti-flood (cap 1/15 min via state).
    # Gap < 60s : juste event JSONL + log warn (pas Discord, le SDK fait son job).
    # Gap 60-300s : channel monitoring (info).
    # Gap > 300s : channel alertes (critique : approche timeout 10min SDK = vraie panne gateway).
    global _last_reconnect_alert_ts
    if time.time() - _last_reconnect_alert_ts > _DISCORD_COOLDOWN_SEC:
        if gap_sec > 300:
            _post_discord_alert(
                f"CRIT Databento stream reconnect #{n} long gap {gap_sec:.0f}s (approche timeout 10min)",
                channel="alertes",
            )
            _last_reconnect_alert_ts = time.time()
        elif gap_sec > 60:
            _post_discord_alert(
                f"INFO Databento stream reconnect #{n} gap {gap_sec:.0f}s (SDK auto-recovery)",
                channel="monitoring",
            )
            _last_reconnect_alert_ts = time.time()


def _on_reconnect_exception(exc):
    """Callback SDK si _on_reconnect leve. Best-effort log."""
    logger.error(f"reconnect callback exception: {exc}")
    _emit_event_safe(
        "STREAM_RECONNECT_EXCEPTION",
        ctx={"exc": str(exc)[:300]},
    )


_event_logger = None


def _emit_event_safe(code: str, ctx: dict | None = None) -> None:
    """Helper : emit JSONL event structure via logging_v2 si dispo.

    PATCH 3 code-reviewer 28/05 : observability structuree pour audit J+1 grep.
    Cache le Logger pour eviter re-import a chaque appel. Best-effort.
    """
    global _event_logger
    try:
        if _event_logger is None:
            try:
                from CORE.logging_v2 import get_logger
            except ImportError:
                import sys as _sys
                from pathlib import Path as _P
                _root = _P(__file__).parent
                if str(_root) not in _sys.path:
                    _sys.path.insert(0, str(_root))
                from logging_v2 import get_logger  # type: ignore
            _event_logger = get_logger("databento_live_stream_v2", process="live_stream")
        # Logger.emit signature : emit(code, *, signal_id, exc, **ctx)
        _event_logger.emit(code, **(ctx or {}))
    except Exception as e:
        logger.warning(f"emit_event_safe({code}) fail: {e}")


def _flush_trade_cache_loop(interval_s: float = 0.5):
    """Flush _last_trade_by_sym vers disque toutes 0.5s. Identique V1."""
    last_log = time.time()
    while _running:
        try:
            time.sleep(interval_s)
            with _trade_lock:
                snapshot = dict(_last_trade_by_sym)
            for sym, data in snapshot.items():
                safe_sym = sym.replace("/", "_").replace(".", "_")
                target = CACHE_DIR / f"{safe_sym}_last_trade.json"
                tmp = target.with_suffix(".json.tmp")
                payload = dict(data)
                payload["written_at_ts"] = time.time()
                payload["written_at_iso"] = datetime.now(timezone.utc).isoformat()
                payload["latency_s"] = round(
                    payload["written_at_ts"] - payload["ts_event_ns"] / 1e9, 3
                )
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    os.replace(tmp, target)
                except OSError:
                    pass
            if time.time() - last_log > 60:
                with _trade_lock:
                    counts = dict(_trades_received)
                logger.info(f"trade flush heartbeat : counts={counts}")
                last_log = time.time()
        except Exception as e:
            logger.exception(f"flush_trade_cache_loop error: {e}")


def _flush_trade_buffer_loop(interval_s: float = TRADE_BUFFER_FLUSH_INTERVAL_SEC):
    """Drain deques + append JSONL daily. Identique V1."""
    last_log = time.time()
    while _running:
        try:
            time.sleep(interval_s)
            drained: dict[str, list[dict]] = {}
            with _trade_buffer_lock:
                for sym, buf in _trade_buffer_by_sym.items():
                    if not buf:
                        continue
                    drained[sym] = []
                    while buf:
                        drained[sym].append(buf.popleft())

            if not drained:
                if time.time() - last_log > 60:
                    with _trade_buffer_lock:
                        counts = dict(_trades_persisted_count)
                    logger.info(f"trade_buffer flush idle, persisted_total={counts}")
                    last_log = time.time()
                continue

            for sym, trades in drained.items():
                safe_sym = sym.replace("/", "_").replace(".", "_")
                sym_dir = TRADE_BUFFER_DIR / safe_sym
                sym_dir.mkdir(parents=True, exist_ok=True)
                bucket: dict[str, list[dict]] = {}
                for t in trades:
                    ts_ns = t.get("ts_event_ns", 0)
                    if ts_ns <= 0:
                        continue
                    day_str = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y%m%d")
                    bucket.setdefault(day_str, []).append(t)
                for day_str, day_trades in bucket.items():
                    fpath = sym_dir / f"{day_str}.jsonl"
                    try:
                        with open(fpath, "a", encoding="utf-8") as f:
                            for t in day_trades:
                                f.write(json.dumps(t, ensure_ascii=False, separators=(",", ":")))
                                f.write("\n")
                        with _trade_buffer_lock:
                            _trades_persisted_count[sym] = (
                                _trades_persisted_count.get(sym, 0) + len(day_trades)
                            )
                            _trade_buffer_write_fails[sym] = 0
                    except OSError as e:
                        with _trade_buffer_lock:
                            _trade_buffer_write_fails[sym] = _trade_buffer_write_fails.get(sym, 0) + 1
                            fails = _trade_buffer_write_fails[sym]
                        if fails <= TRADE_BUFFER_MAX_WRITE_FAILS:
                            logger.warning(
                                f"trade_buffer write fail #{fails}/{TRADE_BUFFER_MAX_WRITE_FAILS} "
                                f"{fpath.name}: {e} -> re-enqueue {len(day_trades)} trades"
                            )
                            with _trade_buffer_lock:
                                for t in day_trades:
                                    _trade_buffer_by_sym[sym].appendleft(t)
                        else:
                            logger.error(
                                f"trade_buffer write fail #{fails} {fpath.name}: {e} -> "
                                f"DROP {len(day_trades)} trades (cap retries atteint)"
                            )
                            with _trade_buffer_lock:
                                _trade_buffer_dropped[sym] = (
                                    _trade_buffer_dropped.get(sym, 0) + len(day_trades)
                                )

            if time.time() - last_log > 60:
                with _trade_buffer_lock:
                    counts = dict(_trades_persisted_count)
                logger.info(f"trade_buffer flush persisted_total={counts}")
                last_log = time.time()
        except Exception as e:
            logger.exception(f"flush_trade_buffer_loop error: {e}")


def _purge_old_trades_loop(retention_days: int = TRADE_BUFFER_PURGE_DAYS):
    """Purge files > retention_days. Identique V1."""
    first_run = True
    while _running:
        try:
            if not first_run:
                time.sleep(24 * 3600)
            first_run = False
            from datetime import timedelta as _td
            cutoff = datetime.now(timezone.utc) - _td(days=retention_days)
            cutoff_ymd = int(cutoff.strftime("%Y%m%d"))
            deleted_count = 0
            for sym_dir in TRADE_BUFFER_DIR.iterdir():
                if not sym_dir.is_dir():
                    continue
                for fpath in sym_dir.glob("*.jsonl"):
                    try:
                        ymd = int(fpath.stem)
                    except ValueError:
                        continue
                    if ymd < cutoff_ymd:
                        try:
                            fpath.unlink()
                            deleted_count += 1
                        except OSError as e:
                            logger.warning(f"purge {fpath.name} fail: {e}")
            if deleted_count > 0:
                logger.info(f"trade_buffer purge: deleted {deleted_count} files > {retention_days}j")
        except Exception as e:
            logger.exception(f"purge_old_trades_loop error: {e}")


def _post_discord_alert(message: str, channel: str = "alertes") -> None:
    """Best-effort Discord webhook. Identique V1."""
    try:
        if not DISCORD_WEBHOOK_PATH.exists():
            return
        cfg = json.loads(DISCORD_WEBHOOK_PATH.read_text(encoding="utf-8"))
        url = cfg.get("webhooks", {}).get(channel)
        if not url:
            return
        import urllib.request
        data = json.dumps({"content": message}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            _ = resp.read()
    except Exception as e:
        logger.warning(f"discord alert fail: {e}")


def _heartbeat_loop():
    """Ecrit _stream_heartbeat.json toutes les HEARTBEAT_INTERVAL_SEC.

    subscribe_alive = data fraiche selon DATA_FRESHNESS_THRESHOLD_SEC per-symbol.
    MGC.v.0 tolere 600s (volume-based), ES/NQ.c.0 tolere 90s.
    PAS d'action ici - juste observability pour dashboard et mia_watchdog.
    """
    prev_subscribe_alive: bool | None = None
    while _running:
        try:
            with _msg_lock:
                last_ts = _last_msg_ts
            silence_sec = (time.time() - last_ts) if last_ts > 0 else None
            with _data_lock:
                last_data_ts_snapshot = dict(_last_data_ts)
            now_ts = time.time()
            data_silence_per_sym = {
                sym: round(now_ts - ts, 1) if ts > 0 else None
                for sym, ts in last_data_ts_snapshot.items()
            }
            # subscribe_alive : compat V1 stricte = max(ages) < WATCHDOG_TIMEOUT_SEC(90s).
            # Necessaire pour ne pas casser `mia_watchdog.check_stream_subscribe_alive`
            # qui consomme cette boolean + max(data_silence_per_sym) pour decider restart.
            # PATCH 1 code-reviewer 28/05 : revert per-symbol thresholds pour preserver
            # semantique V1 cote watchdog externe.
            ages_valid = [now_ts - ts for ts in last_data_ts_snapshot.values() if ts > 0]
            if not ages_valid or len(ages_valid) < len(SYMBOLS):
                subscribe_alive = False
            else:
                subscribe_alive = max(ages_valid) < WATCHDOG_TIMEOUT_SEC

            # Champ additif (non breaking) : subscribe_alive_per_sym pour permettre
            # au mia_watchdog d'ignorer MGC overnight silencieux (vol-based normal).
            # Les consumers existants utilisent encore le boolean global (compat V1).
            subscribe_alive_per_sym: dict[str, bool] = {}
            for sym in SYMBOLS:
                ts = last_data_ts_snapshot.get(sym, 0)
                threshold = DATA_FRESHNESS_THRESHOLD_SEC.get(sym, WATCHDOG_TIMEOUT_SEC)
                if ts <= 0:
                    subscribe_alive_per_sym[sym] = False
                else:
                    subscribe_alive_per_sym[sym] = (now_ts - ts) < threshold
            with _reconnect_lock:
                reconnect_count = _reconnect_count
                last_gap_sec = _reconnect_last_gap_sec
            payload = {
                "ts_now": datetime.now(timezone.utc).isoformat(),
                "last_msg_ts": last_ts,
                "silence_sec": round(silence_sec, 1) if silence_sec is not None else None,
                "bars_received": dict(_bars_received),
                "trades_received": dict(_trades_received),
                "data_silence_per_sym": data_silence_per_sym,
                "subscribe_alive": subscribe_alive,
                # Additive (V2) : permet a mia_watchdog d'ignorer MGC overnight
                # tout en restant strict sur ES/NQ. Consumers V1 ignorent ce champ.
                "subscribe_alive_per_sym": subscribe_alive_per_sym,
                "reconnect_count": reconnect_count,
                "last_reconnect_gap_sec": last_gap_sec,
                "stream_version": "v2_native_reconnect",
            }
            tmp = HEARTBEAT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(HEARTBEAT_FILE)
            # Alerte Discord transition subscribe_alive avec cooldown anti-flood.
            # Le SDK reconnect gere les drops courts (< 60s) sans intervention -> on
            # alerte uniquement les transitions persistantes. Dedup 15 min entre alerts.
            global _last_subscribe_alive_alert_ts
            if prev_subscribe_alive is not None and prev_subscribe_alive != subscribe_alive:
                now_alert = time.time()
                if now_alert - _last_subscribe_alive_alert_ts > _DISCORD_COOLDOWN_SEC:
                    if subscribe_alive:
                        _post_discord_alert(
                            f"OK MIA-Live-OHLCV stream RECOVERED — "
                            f"data_silence={data_silence_per_sym} "
                            f"per_sym_alive={subscribe_alive_per_sym}",
                            channel="monitoring",
                        )
                    else:
                        # Identifier les sym fautifs pour debug rapide
                        dead_syms = [s for s, alive in subscribe_alive_per_sym.items() if not alive]
                        _post_discord_alert(
                            f"WARN MIA-Live-OHLCV stream DOWN — dead_syms={dead_syms} "
                            f"data_silence={data_silence_per_sym} bars={dict(_bars_received)} "
                            f"trades={dict(_trades_received)}",
                            channel="alertes",
                        )
                    _last_subscribe_alive_alert_ts = now_alert
            prev_subscribe_alive = subscribe_alive
        except Exception as e:
            logger.warning(f"heartbeat write fail: {e}")
        time.sleep(HEARTBEAT_INTERVAL_SEC)


def main():
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        logger.critical("DATABENTO_API_KEY missing")
        sys.exit(1)

    # Signal handlers : install seulement si main() est appele depuis le main thread.
    # En test harness daemon (testing), signal.signal() leve ValueError -> skip propre.
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _signal_handler)
    except ValueError as e:
        logger.warning(f"signal handlers skipped (not main thread): {e}")

    logger.info(f"START databento_live_stream_v2 — symbols={SYMBOLS}")
    logger.info(f"CACHE_DIR : {CACHE_DIR}")
    logger.info(f"API key   : {api_key[:8]}...{api_key[-4:]}")

    # Threads daemon
    flush_thread = threading.Thread(target=_flush_trade_cache_loop, daemon=True)
    flush_thread.start()
    logger.info("Trade cache flush thread started (interval 0.5s)")

    flush_buffer_thread = threading.Thread(
        target=_flush_trade_buffer_loop, daemon=True, name="TradeBufferFlush"
    )
    flush_buffer_thread.start()
    logger.info(
        f"Trade buffer flush thread started (interval {TRADE_BUFFER_FLUSH_INTERVAL_SEC}s, "
        f"output {TRADE_BUFFER_DIR})"
    )

    purge_buffer_thread = threading.Thread(
        target=_purge_old_trades_loop, daemon=True, name="TradeBufferPurge"
    )
    purge_buffer_thread.start()
    logger.info(f"Trade buffer purge thread started (retention {TRADE_BUFFER_PURGE_DAYS}j)")

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="Heartbeat")
    heartbeat_thread.start()
    logger.info(f"Heartbeat thread started (interval {HEARTBEAT_INTERVAL_SEC}s)")

    # Construction du client AVEC reconnect_policy natif.
    # heartbeat_interval_s=30 = le gateway Databento envoie un heartbeat toutes 30s.
    # reconnect_policy=RECONNECT = backoff exponential 1s,2s...60s + resubscribe auto.
    try:
        if ReconnectPolicy is not None:
            client = db.Live(
                key=api_key,
                heartbeat_interval_s=30,
                reconnect_policy=ReconnectPolicy.RECONNECT,
            )
        else:
            # Fallback string (SDK accepte string aussi)
            client = db.Live(
                key=api_key,
                heartbeat_interval_s=30,
                reconnect_policy="reconnect",
            )
    except TypeError as e:
        logger.critical(
            f"db.Live() ne supporte pas reconnect_policy ou heartbeat_interval_s : {e}. "
            f"Verifier version databento-python (>=0.50 requise)"
        )
        sys.exit(2)
    except db.common.error.BentoClientError as e:
        err_str = str(e).lower()
        if any(k in err_str for k in ("auth", "unauthorized", "403", "401")):
            logger.critical(f"AUTH ERROR : Live tier not active. {e}")
            sys.exit(2)
        raise

    # Subscribe ohlcv-1m + trades
    client.subscribe(
        dataset="GLBX.MDP3",
        schema="ohlcv-1m",
        stype_in="continuous",
        symbols=SYMBOLS,
    )
    client.subscribe(
        dataset="GLBX.MDP3",
        schema="trades",
        stype_in="continuous",
        symbols=SYMBOLS,
    )

    # Callbacks data + reconnect observability
    client.add_callback(_build_callback())
    try:
        client.add_reconnect_callback(_on_reconnect, _on_reconnect_exception)
        logger.info("add_reconnect_callback registered (SDK native reconnect)")
    except AttributeError:
        logger.warning(
            "SDK n'expose pas add_reconnect_callback. Reconnect natif sans observability gap."
        )

    # Register client en global pour permettre signal handler appeler stop()
    global _client_global
    _client_global = client

    client.start()
    logger.info("Streaming started (ohlcv-1m + trades) with native auto-reconnect")

    # block_for_close = blocking, SDK gere tout (reconnect, resubscribe, heartbeat).
    # Sortie possible : SIGTERM/SIGINT via _signal_handler (qui appelle client.stop()),
    # ou remote gateway disconnect definitif apres timeout reconnect (10 min SDK).
    #
    # 29/05 FIX V2 (root cause analysis vs FIX V1 surface) :
    # FIX V1 (timeout=60s + check silence) ne marchait pas. SDK source montre que
    # `block_for_close(timeout=60.0)` au timeout appelle `self.terminate()` qui :
    #  - kill brutal session via `_transport.abort()`
    #  - `_cleanup()` clear callbacks + subscriptions
    #  - `is_streaming() = False` → reconnect SDK ne fait pas `start()` apres
    #    reconnect → callback `_on_reconnect` JAMAIS appele → reconnect_count=0
    #    perpetuel (verifie heartbeat snapshots Jackson).
    # Consequence : session morte toutes les 60s + watchdog 99999 (ES/NQ silence > 90s
    # threshold) → restart cascade. 1314 restarts en 30 jours.
    #
    # FIX V2 : block_for_close(timeout=None) = wait forever. SDK gere reconnect_policy
    # natif sans terminate intermediaire. Signal handler appelle client.stop() (close
    # propre via _transport.close, PAS abort) qui debloque wait_for_close → return
    # propre de block_for_close.
    try:
        # Wait jusqu'au stop() user (signal handler) OR gateway disconnect permanent
        # (SDK reconnect_policy=RECONNECT tente 10 min avant raise BentoError).
        client.block_for_close(timeout=None)
        # Si on arrive ici sans exception :
        #   - _running=True : vraie fermeture session (gateway down 10min ou SDK abandon)
        #   - _running=False : SIGTERM/SIGINT recu, signal handler a appele stop()
        if _running:
            logger.error(
                "block_for_close returned without exception : "
                "SDK reconnect timeout 10min exhausted OR gateway disconnect permanent. "
                "Exiting for nssm restart."
            )
            _emit_event_safe(
                "STREAM_SESSION_CLOSED_PERMANENT",
                ctx={
                    "bars_received": dict(_bars_received),
                    "trades_received": dict(_trades_received),
                    "reconnect_count": _reconnect_count,
                },
            )
            sys.exit(3)
        else:
            logger.info("block_for_close returned after user stop signal (clean shutdown)")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt")
    except Exception as e:
        logger.exception(f"main loop unexpected error: {e}")
        sys.exit(3)
    finally:
        try:
            client.stop()
        except Exception:
            pass
        logger.info(
            f"Stopped. Total bars : {_bars_received}, reconnects : {_reconnect_count}"
        )


if __name__ == "__main__":
    main()
