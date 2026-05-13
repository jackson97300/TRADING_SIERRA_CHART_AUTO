"""databento_live_stream.py — stream Live OHLCV-1m → cache JSON pour Bot 2 entry.

CONTEXTE : Bot 2 (databento_paper_trader.py) lit un parquet enrichi alimente
par live_pipeline.py qui utilise Databento Historical API. Cette API impose
un delay reel de ~30 min (mesure empirique 29/04). Slippage entry observe :
~23 ticks systematiques sur ES.

SOLUTION (5e voie validee Plan agent + Jackson 29/04 soir) :
- Service nssm dedie qui maintient un cache LIVE OHLCV (latence ~1 min)
- Bot 2 lit ce cache au moment du send order pour avoir le prix REEL actuel
- Le pipeline Historical reste pour les 420 features ML (inchange)
- Slippage attendu post-fix : ~1-3 ticks au lieu de 23

ARCHITECTURE :
  [db.Live() subscribe ohlcv-1m]
       ↓ callback (1 record par bar reçue)
  [parse OHLCVMsg]
       ↓
  [write atomic DATA/LIVE_CACHE/{ES,NQ}_last.json]
       ↓ lecture par Bot 2 au moment du send order
  Bot 2 utilise close du cache pour entry_price + recalc TP/SL

USAGE :
  python -X utf8 CORE/databento_live_stream.py

Tourne en boucle infinie via service nssm `MIA-Live-OHLCV`.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import databento as db

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "DATA" / "LIVE_CACHE"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Symbols suivis (continuous = front-month auto-roll)
# 🆕 09/05 (Phase A2 GC) : ajout MGC (Micro Gold COMEX, tick=$1, safer Topstep)
# 🆕 10/05 (Chantier 5bis) : MGC.c.0 -> MGC.v.0 (volume-based rollover)
#    Cause : MGC.c.0 (date-based) tronquait 50-99% des bars sur mois
#    d'expiration GC futures (jun, aug, oct, dec, fev, avr). Verification
#    empirique 02/06/2025 : MGC.c.0 = 49 bars vs MGC.v.0 = 1380 bars.
#    ES/NQ : MGC.c.0 fonctionne (rollover quarterly mar/jun/sep/dec).
SYMBOLS = ["ES.c.0", "NQ.c.0", "MGC.v.0"]

# Logging
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
logger = logging.getLogger("live_stream")

# Etat global
_running = True
_inst_to_sym: dict[int, str] = {}
_bars_received: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_last_bar_ts: dict[str, str] = {sym: "?" for sym in SYMBOLS}

# FIX 30/04 nuit : in-memory cache TradeMsg pour latence ms.
# Le callback maintient _last_trade_by_sym (no I/O).
# Un thread separe flush sur disque toutes les 0.5s (eviter explose I/O sur
# >100 trades/sec en heures actives).
import threading
from collections import deque
_last_trade_by_sym: dict[str, dict] = {}
_trades_received: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_trade_lock = threading.Lock()

# Chantier 2 (13/05/2026 nuit) : BUFFER ROLLING TRADES pour Chantier 3 Live Enricher.
# Plan strategique migration Bot 2 V6 full Databento : on persiste TOUS les trades
# (pas juste le dernier) dans un buffer rolling JSONL pour permettre :
#   1. Replay historique 7j (debug + audit)
#   2. Calcul streaming footprint/big_orders/edge_zones (Chantier 3)
#
# Architecture (anti-degradation latence ms _last_trade_by_sym) :
#   - Callback TradeMsg : append trade au deque thread-safe (zero I/O)
#   - Thread separe _flush_trade_buffer_loop : drain deques + append JSONL toutes 5s
#   - Thread separe _purge_old_trades_loop : delete files > 7 jours quotidien
#
# Volume estime : ES ~50k + NQ ~80k + MGC ~5k = ~135k trades/jour x ~200 bytes
#   = ~27 MB/jour x 7 jours = ~190 MB (acceptable, configurable).
TRADE_BUFFER_FLUSH_INTERVAL_SEC = 5
TRADE_BUFFER_PURGE_DAYS = 7
TRADE_BUFFER_DIR = CACHE_DIR / "trades"
TRADE_BUFFER_DIR.mkdir(parents=True, exist_ok=True)
# FIX P1.1 code-reviewer 13/05 nuit : maxlen plafond memoire (anti-OOM si flush
# thread plante / disque plein). 500K trades ≈ ~3-4h worst-case ES open active,
# ~100 MB plafond total 3 syms (500K x 200 bytes x 3 = 300 MB). Si maxlen atteint
# deque evict silencieusement le plus ancien (FIFO), un log WARN est emis.
TRADE_BUFFER_MAXLEN = 500_000
_trade_buffer_by_sym: dict[str, deque] = {
    sym: deque(maxlen=TRADE_BUFFER_MAXLEN) for sym in SYMBOLS
}
_trade_buffer_lock = threading.Lock()
_trades_persisted_count: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_trade_buffer_dropped: dict[str, int] = {sym: 0 for sym in SYMBOLS}  # FIX P1.3
# FIX P1.3 : tracker echecs consecutifs write par symbol pour eviter accumulation
# infinie en cas de disque plein. Drop trades apres 3 echecs consecutifs.
_trade_buffer_write_fails: dict[str, int] = {sym: 0 for sym in SYMBOLS}
TRADE_BUFFER_MAX_WRITE_FAILS = 3

# 04/05 watchdog auto-reconnect : timestamp dernier callback recu (TOUS types)
# Sert a detecter websocket dead (ack/system messages updaten ce ts).
# Cause root du bug 01/05 : BentoError Gateway timeout 41s, websocket dead silencieux.
_last_msg_ts: float = 0.0
_msg_lock = threading.Lock()

# 04/05 SOIR fix #1 (audit code-reviewer NOGO) : timestamp data marche per-symbol.
# UNIQUEMENT update sur OHLCVMsg + TradeMsg (PAS SymbolMappingMsg/system messages).
# Le watchdog precedent etait masque par les SymbolMappingMsg refresh -> websocket
# vivant mais 0 data marche reelle pendant 6 jours. Le fix #1 force watchdog a
# regarder le flux marche reel, pas le flux meta.
_last_data_ts: dict[str, float] = {sym: 0.0 for sym in SYMBOLS}
_data_lock = threading.Lock()

WATCHDOG_TIMEOUT_SEC = 90  # > gateway timeout 41s + marge
WATCHDOG_BOOT_GRACE_SEC = 60  # 04/05 SOIR fix #2 : grace au boot avant 1er fire
FORCE_RECONNECT_INTERVAL_SEC = 4 * 3600  # 04/05 SOIR fix #4 : reconnect periodique 4h
HEARTBEAT_INTERVAL_SEC = 5  # ecriture _stream_heartbeat.json
THREAD_HEALTH_CHECK_SEC = 30  # 04/05 SOIR fix #3 : check threads daemon vivants

# 04/05 SOIR fix #7 : Discord alerte sur transition subscribe_alive: true -> false
DISCORD_WEBHOOK_PATH = ROOT / "BOT" / "alert_config.json"

# Heartbeat file pour distinguer "service running" vs "subscribe vivant"
HEARTBEAT_FILE = CACHE_DIR / "_stream_heartbeat.json"


def _signal_handler(signum, frame):
    global _running
    logger.info(f"Signal {signum} received, stopping...")
    _running = False


def _atomic_write_cache(symbol: str, payload: dict) -> None:
    """Write payload to LIVE_CACHE/{symbol}_last.json atomically.

    Atomic = write to .tmp then os.replace. Bot 2 lecture est garantie
    de voir un fichier complet (jamais une lecture partielle).
    """
    safe_sym = symbol.replace("/", "_").replace(".", "_")
    target = CACHE_DIR / f"{safe_sym}_last.json"
    tmp = target.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, target)
    except OSError as e:
        logger.warning(f"write cache fail {symbol}: {e}")


def _build_callback(client_ref):
    """Closure pour acces _inst_to_sym + _bars_received + client (pour stop)."""

    def callback(record):
        # 04/05 watchdog : update last msg ts a chaque callback (TOUS types)
        # pour detecter silence websocket avant gateway timeout.
        global _last_msg_ts
        with _msg_lock:
            _last_msg_ts = time.time()

        # SDK databento 0.76.0 : attributs directs
        # 1. SymbolMappingMsg : initial mapping instrument_id → symbol
        if isinstance(record, db.SymbolMappingMsg):
            try:
                inst_id = record.instrument_id
                sym = record.stype_in_symbol
                _inst_to_sym[inst_id] = sym
                logger.info(f"MAPPING instrument_id={inst_id} -> {sym}")
            except AttributeError as e:
                logger.warning(f"SymbolMappingMsg parse fail: {e}")
            return

        # 2. ErrorMsg : log + continue (pas de crash)
        if isinstance(record, db.ErrorMsg):
            logger.error(f"Databento ErrorMsg: {getattr(record, 'err', record)}")
            return

        # 3. OHLCVMsg : core handler
        if isinstance(record, db.OHLCVMsg):
            try:
                inst_id = record.instrument_id
                sym = _inst_to_sym.get(inst_id)
                if sym is None:
                    # Mapping pas encore reçu, skip cette bar
                    return

                # Databento prices : fixed-point integer * 1e9
                # Volume : integer
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
                # 04/05 SOIR fix #1 : watchdog ne regarde QUE data marche reelle
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

        # 4. TradeMsg : core handler tick par tick (latence ms)
        # FIX 30/04 nuit : utilise par Bot 2 _check_exit_dtc pour anticiper
        # le hit SL/TP avant que SC ne fille les 2 brackets.
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
                # Side est un enum databento Side (Ask/Bid/None) → cast str pour JSON
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
                # Chantier 2 (13/05/2026 nuit) : append au buffer rolling
                # pour persistance JSONL (Chantier 3 Live Enricher input).
                # deque thread-safe, zero I/O cost dans callback.
                with _trade_buffer_lock:
                    _trade_buffer_by_sym[sym].append(trade_dict)
                # 04/05 SOIR fix #1 : watchdog ne regarde QUE data marche reelle
                with _data_lock:
                    _last_data_ts[sym] = time.time()
                # No log per trade (>100/sec) — log via heartbeat thread
            except Exception as e:
                logger.exception(f"TradeMsg handler fail: {e}")
            return

        # 5. Autres types : ignore silencieusement (system/heartbeat)

    return callback


def _flush_trade_cache_loop(interval_s: float = 0.5):
    """Thread daemon qui flush _last_trade_by_sym sur disque toutes les 0.5s.

    Evite I/O par trade (>100 trades/sec en heures actives = explose disque).
    Bot 2 lit ce fichier avec latence acceptable ~0.5s.
    """
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
            # Heartbeat log toutes les 60s
            if time.time() - last_log > 60:
                with _trade_lock:
                    counts = dict(_trades_received)
                logger.info(f"trade flush heartbeat : counts={counts}")
                last_log = time.time()
        except Exception as e:
            logger.exception(f"flush_trade_cache_loop error: {e}")


def _flush_trade_buffer_loop(interval_s: float = TRADE_BUFFER_FLUSH_INTERVAL_SEC):
    """Thread daemon : drain _trade_buffer_by_sym et append JSONL.

    Chantier 2 (13/05/2026 nuit) : persistance Trades pour Chantier 3
    Live Enricher input. Format JSONL append-only, rotation quotidienne.

    Output path :
        DATA/LIVE_CACHE/trades/{sym_safe}/{YYYYMMDD}.jsonl

    Critique : ne PAS bloquer le callback principal. Drain rapide via
    deque pop + I/O batchee (regroupe trades par jour avant write).
    """
    last_log = time.time()
    while _running:
        try:
            time.sleep(interval_s)
            # 1. Drain tous les deques (rapide, sous lock court)
            drained: dict[str, list[dict]] = {}
            with _trade_buffer_lock:
                for sym, buf in _trade_buffer_by_sym.items():
                    if not buf:
                        continue
                    drained[sym] = []
                    while buf:
                        drained[sym].append(buf.popleft())

            if not drained:
                # Heartbeat log toutes les 60s meme si rien
                if time.time() - last_log > 60:
                    with _trade_buffer_lock:
                        counts = dict(_trades_persisted_count)
                    logger.info(f"trade_buffer flush idle, persisted_total={counts}")
                    last_log = time.time()
                continue

            # 2. Group par jour UTC + append JSONL atomic
            #    (open/write/close par batch -> reduit overhead syscall)
            for sym, trades in drained.items():
                safe_sym = sym.replace("/", "_").replace(".", "_")
                sym_dir = TRADE_BUFFER_DIR / safe_sym
                sym_dir.mkdir(parents=True, exist_ok=True)

                # Bucket par YYYYMMDD UTC (rare cross-day boundary, mais possible)
                bucket: dict[str, list[dict]] = {}
                for t in trades:
                    ts_ns = t.get("ts_event_ns", 0)
                    if ts_ns <= 0:
                        continue
                    day_str = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y%m%d")
                    bucket.setdefault(day_str, []).append(t)

                # Write par bucket
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
                            _trade_buffer_write_fails[sym] = 0  # reset apres succes
                    except OSError as e:
                        # FIX P1.3 (audit code-reviewer 13/05 nuit) : cap retries
                        # appendleft pour eviter accumulation infinie si disque plein.
                        # Apres TRADE_BUFFER_MAX_WRITE_FAILS echecs consecutifs, on
                        # DROP les trades pour eviter OOM du service.
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
                                f"DROP {len(day_trades)} trades (cap retries atteint, "
                                f"anti-OOM service). Disque plein ? AV scan ?"
                            )
                            with _trade_buffer_lock:
                                _trade_buffer_dropped[sym] = (
                                    _trade_buffer_dropped.get(sym, 0) + len(day_trades)
                                )

            # Heartbeat 60s
            if time.time() - last_log > 60:
                with _trade_buffer_lock:
                    counts = dict(_trades_persisted_count)
                logger.info(f"trade_buffer flush persisted_total={counts}")
                last_log = time.time()
        except Exception as e:
            logger.exception(f"flush_trade_buffer_loop error: {e}")


def _purge_old_trades_loop(retention_days: int = TRADE_BUFFER_PURGE_DAYS):
    """Thread daemon : delete trade buffer files > retention_days jours.

    Tourne 1x par jour (sleep 24h). Au boot, run immediat pour cleanup
    eventuel accumule.
    """
    first_run = True
    while _running:
        try:
            if not first_run:
                time.sleep(24 * 3600)
            first_run = False

            # Calcul cutoff YYYYMMDD (sans pandas pour eviter dep additionnelle)
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
                logger.info(f"trade_buffer purge: deleted {deleted_count} files > {retention_days}j old")
        except Exception as e:
            logger.exception(f"purge_old_trades_loop error: {e}")


def _post_discord_alert(message: str, channel: str = "alertes") -> None:
    """Post une alerte Discord (best-effort, swallow exceptions).

    04/05 SOIR fix #7 : alerter sur transition subscribe_alive: true -> false.
    Utilise stdlib urllib pour eviter dependance requests dans ce module critique.
    """
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
    """Ecrit _stream_heartbeat.json toutes les HEARTBEAT_INTERVAL_SEC secondes.

    Permet au dashboard de distinguer :
      - Service nssm running (file mtime change toutes les 5s)
      - Subscribe Databento vivant (last_msg_ts < 60s)
      - Data marche reelle vivante (last_data_ts per-symbol < 90s) — fix #1

    Avant 04/05 : seul mtime LIVE_CACHE/_last.json checke -> bug 01/05 silencieux
    (counts figes a 338758 pendant 67h, file mtime change car flush thread tourne).

    04/05 SOIR fix #7 : detecte transition subscribe_alive: true -> false et
    post Discord webhook 'alertes'. Idem transition false -> true (recovery).
    """
    prev_subscribe_alive: bool | None = None  # premier tick = pas de transition
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
            # subscribe_alive base sur data marche (pas message generique).
            # Cas 1 : aucune data jamais recue (ts=0) -> alive=False
            # Cas 2 : >=1 symbol avec age > WATCHDOG_TIMEOUT_SEC -> alive=False
            ages_valid = [now_ts - ts for ts in last_data_ts_snapshot.values() if ts > 0]
            if not ages_valid or len(ages_valid) < len(SYMBOLS):
                subscribe_alive = False
            else:
                subscribe_alive = max(ages_valid) < WATCHDOG_TIMEOUT_SEC
            payload = {
                "ts_now": datetime.now(timezone.utc).isoformat(),
                "last_msg_ts": last_ts,
                "silence_sec": round(silence_sec, 1) if silence_sec is not None else None,
                "bars_received": dict(_bars_received),
                "trades_received": dict(_trades_received),
                "data_silence_per_sym": data_silence_per_sym,
                "subscribe_alive": subscribe_alive,
            }
            tmp = HEARTBEAT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(HEARTBEAT_FILE)
            # Fix #7 : detection transition subscribe_alive
            if prev_subscribe_alive is not None and prev_subscribe_alive != subscribe_alive:
                if subscribe_alive:
                    _post_discord_alert(
                        f"OK MIA-Live-OHLCV stream RECOVERED — "
                        f"data_silence={data_silence_per_sym}",
                        channel="monitoring",
                    )
                else:
                    _post_discord_alert(
                        f"WARN MIA-Live-OHLCV stream DOWN — "
                        f"data_silence={data_silence_per_sym} bars={dict(_bars_received)} "
                        f"trades={dict(_trades_received)}",
                        channel="alertes",
                    )
            prev_subscribe_alive = subscribe_alive
        except Exception as e:
            logger.warning(f"heartbeat write fail: {e}")
        time.sleep(HEARTBEAT_INTERVAL_SEC)


def _watchdog_loop(client_ref_holder):
    """Surveille _last_data_ts (per-symbol, OHLCV+Trade only).

    04/05 SOIR FIX #2 (audit code-reviewer) : la version precedente regardait
    _last_msg_ts (mis a jour sur TOUS types y compris SymbolMappingMsg) et
    skippait si last_ts <= 0. Resultat : si Databento push uniquement des
    SymbolMappingMsg/heartbeats sans data marche pendant 6 jours, le watchdog
    dort. Bug reproduit le 04/05 (6h figes en prod).

    Nouvelle logique :
      - Boot grace WATCHDOG_BOOT_GRACE_SEC (60s) : skip checks pendant la
        connexion initiale (le 1er OHLCV peut tarder jusqu'a 60s = bar close).
      - Apres grace : prendre `max(now - _last_data_ts[sym] for sym in SYMBOLS)`.
        Si > WATCHDOG_TIMEOUT_SEC -> force client.stop() pour declencher reconnect.
      - Couvre le cas "websocket vivant + 0 data marche" qui etait le bug 01/05+04/05.

    client_ref_holder : dict {"client": db.Live} mute par main(). On peut pas
    closure direct car le client est recree dans la boucle de reconnexion.
    """
    boot_ts = time.time()
    while _running:
        time.sleep(15)  # check toutes 15s
        try:
            # Boot grace : skip pendant 60s pour laisser le 1er bar arriver
            if time.time() - boot_ts < WATCHDOG_BOOT_GRACE_SEC:
                continue
            # Compute max age across symbols sur DATA marche uniquement
            now = time.time()
            with _data_lock:
                ages = [(sym, now - ts) for sym, ts in _last_data_ts.items() if ts > 0]
                # Symbols sans aucune data depuis le boot : age = uptime (force fire si > timeout)
                no_data_syms = [sym for sym, ts in _last_data_ts.items() if ts <= 0]
            if no_data_syms:
                # Au moins un symbole n'a JAMAIS recu de data depuis boot
                uptime = now - boot_ts
                if uptime > WATCHDOG_TIMEOUT_SEC:
                    client = client_ref_holder.get("client")
                    logger.error(
                        f"WATCHDOG no market data depuis boot ({uptime:.0f}s) "
                        f"sur symbols={no_data_syms} -> force client.stop() pour reconnect"
                    )
                    if client is not None:
                        try:
                            client.stop()
                        except Exception as e:
                            logger.warning(f"watchdog client.stop fail: {e}")
                continue
            if not ages:
                continue  # defensive : pas de symbol tracke
            worst_sym, worst_age = max(ages, key=lambda x: x[1])
            if worst_age > WATCHDOG_TIMEOUT_SEC:
                client = client_ref_holder.get("client")
                logger.error(
                    f"WATCHDOG silence data {worst_sym}={worst_age:.0f}s > "
                    f"{WATCHDOG_TIMEOUT_SEC}s -> force client.stop() pour reconnect"
                )
                if client is not None:
                    try:
                        client.stop()  # provoque break boucle interne -> reconnect
                    except Exception as e:
                        logger.warning(f"watchdog client.stop fail: {e}")
        except Exception as e:
            logger.warning(f"watchdog loop error: {e}")


def main():
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        logger.critical("DATABENTO_API_KEY missing")
        sys.exit(1)

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)

    logger.info(f"START databento_live_stream — symbols={SYMBOLS}")
    logger.info(f"CACHE_DIR : {CACHE_DIR}")
    logger.info(f"API key   : {api_key[:8]}...{api_key[-4:]}")

    # Boucle de reconnexion : si la connexion tombe, on retry apres un delai
    backoff_s = 5
    max_backoff_s = 300

    # FIX 30/04 nuit : start flush_trade_cache thread daemon
    flush_thread = threading.Thread(target=_flush_trade_cache_loop, daemon=True)
    flush_thread.start()
    logger.info("Trade cache flush thread started (interval 0.5s)")

    # Chantier 2 (13/05/2026 nuit) : threads buffer rolling Trades pour Chantier 3.
    # Persiste tous les Trades en JSONL daily (drain 5s, purge 7j retention).
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

    # 04/05 : watchdog auto-reconnect + heartbeat threads (Etape 0)
    client_holder: dict = {"client": None}  # mute par boucle reconnect
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    logger.info(f"Heartbeat thread started (interval {HEARTBEAT_INTERVAL_SEC}s)")
    watchdog_thread = threading.Thread(target=_watchdog_loop, args=(client_holder,), daemon=True)
    watchdog_thread.start()
    logger.info(f"Watchdog thread started (timeout {WATCHDOG_TIMEOUT_SEC}s)")

    last_thread_health_check = time.time()
    while _running:
        try:
            client = db.Live(key=api_key)
            client_holder["client"] = client  # 04/05 : expose au watchdog
            # 1. Subscribe ohlcv-1m (pour Bot 2 entry price - latence 60s)
            client.subscribe(
                dataset="GLBX.MDP3",
                schema="ohlcv-1m",
                stype_in="continuous",
                symbols=SYMBOLS,
            )
            # 2. Subscribe trades (pour Bot 2 check_exit proactif - latence ms)
            # FIX 30/04 nuit : 2e schema sur meme client = double stream sur
            # meme connexion DTC. Necessaire pour anticiper hit SL/TP avant
            # que SC fille les 2 brackets simultanes.
            client.subscribe(
                dataset="GLBX.MDP3",
                schema="trades",
                stype_in="continuous",
                symbols=SYMBOLS,
            )
            client.add_callback(_build_callback(client))
            client.start()
            # 04/05 : reset _last_msg_ts au connect pour eviter watchdog premature
            with _msg_lock:
                _last_msg_ts = time.time()
            # 04/05 SOIR fix #1 : reset _last_data_ts a 0 pour que le watchdog
            # detecte "no data depuis le nouveau connect"
            with _data_lock:
                for sym in SYMBOLS:
                    _last_data_ts[sym] = 0.0
            connect_ts = time.time()  # 04/05 SOIR fix #4 : timer reconnect 4h
            logger.info("Connection started, streaming ohlcv-1m + trades...")
            backoff_s = 5  # reset backoff sur connexion reussie

            # Boucle principale : check _running tous les 5s
            # + fix #3 surveillance threads daemon
            # + fix #4 force reconnect periodique 4h
            while _running:
                time.sleep(5)

                # Fix #3 : check threads daemon vivants (toutes 30s)
                if time.time() - last_thread_health_check > THREAD_HEALTH_CHECK_SEC:
                    last_thread_health_check = time.time()
                    dead = []
                    if not flush_thread.is_alive():
                        dead.append("flush_thread")
                    if not heartbeat_thread.is_alive():
                        dead.append("heartbeat_thread")
                    if not watchdog_thread.is_alive():
                        dead.append("watchdog_thread")
                    # FIX P1.2 code-reviewer 13/05 nuit : surveiller les nouveaux
                    # threads Chantier 2 (buffer rolling Trades) sinon mort
                    # silencieuse -> buffer accumule -> OOM service.
                    if not flush_buffer_thread.is_alive():
                        dead.append("flush_buffer_thread")
                    if not purge_buffer_thread.is_alive():
                        dead.append("purge_buffer_thread")
                    if dead:
                        logger.critical(
                            f"DAEMON THREAD DEAD: {dead} -> sys.exit(3) pour nssm relance"
                        )
                        try:
                            client.stop()
                        except Exception:
                            pass
                        sys.exit(3)

                # Fix #4 : force reconnect periodique apres 4h d'uptime
                # Defense en profondeur contre silent stale websocket cote Databento.
                if time.time() - connect_ts > FORCE_RECONNECT_INTERVAL_SEC:
                    logger.info(
                        f"FORCE_RECONNECT periodique apres "
                        f"{FORCE_RECONNECT_INTERVAL_SEC // 3600}h d'uptime "
                        f"-> client.stop() pour rotation propre"
                    )
                    try:
                        client.stop()
                    except Exception:
                        pass
                    break  # exit boucle interne -> reconnect via boucle externe

            # Stop propre (signal SIGTERM ou rotation 4h)
            if _running:
                # Sortie via fix #4 (rotation 4h) -> reconnect immediat
                logger.info("Reconnecting after force_reconnect 4h...")
                continue
            # Sinon shutdown signal -> stop client propre + break
            logger.info("Stopping client...")
            try:
                client.stop()
            except Exception:
                pass
            break

        except db.common.error.BentoAuthenticationError as e:
            logger.critical(f"AUTH ERROR : Live tier not active. {e}")
            sys.exit(2)

        except Exception as e:
            logger.exception(f"Connection error: {e}")
            if not _running:
                break
            logger.info(f"Reconnecting in {backoff_s}s...")
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, max_backoff_s)

    logger.info(f"Stopped. Total bars : {_bars_received}")


if __name__ == "__main__":
    main()
