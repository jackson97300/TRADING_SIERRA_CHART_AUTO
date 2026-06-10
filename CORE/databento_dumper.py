"""databento_dumper.py — Dumper Databento Live equivalent au DMP C++.

Architecture :
  Databento Live WebSocket → trades stream
  → Aggregator 1m bars (OHLCV + delta + neutral_vol)
  → Writer JSONL avec partitioning year/month/day

Structure dossiers (Hive partitioning) :
  DATA/databento_live/
    ES.c.0/year=2026/month=4/day=28/data.jsonl
    NQ.c.0/year=2026/month=4/day=28/data.jsonl

Phase 1 (ce fichier) : OHLCV + delta + total_vol + buy_vol + sell_vol + neutral_vol primitives.
Phase 2 (TODO) : VWAP, IB, profile, MQ levels (lus DMP allege en parallele).
Phase 3 (TODO) : BN, Game Changers, delta_divergence (logic Python).

Resilience :
- ReconnectPolicy.RECONNECT (auto-retry sur disconnect WebSocket).
- isinstance() pour record dispatch (TradeMsg, SymbolMappingMsg, ErrorMsg, SystemMsg).
- side='N' (neutral, auction/cross) compte en total_vol mais PAS en buy/sell/delta (anti-pollution ML).
- Crash en cours de barre 1m → barre courante perdue (acceptable granularite 1min).
- Restart append : si schema_version different, rotation du fichier en .bak_HHMMSS.

Usage :
    python -X utf8 CORE/databento_dumper.py --symbols ES.c.0 NQ.c.0
    python -X utf8 CORE/databento_dumper.py --symbols ES.c.0 NQ.c.0 --duration 3600

Auteur : MIA Trading System V2
Date   : 2026-04-28 14:00 (Phase 1 + fixes review C1-C5)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    print("[FATAL] DATABENTO_API_KEY manquant dans .env", file=sys.stderr)
    sys.exit(1)

import databento as db
from databento import ReconnectPolicy
from databento_dbn import TradeMsg, SymbolMappingMsg, ErrorMsg, SystemMsg

DATASET = "GLBX.MDP3"
DATA_ROOT = ROOT / "DATA" / "databento_live"
SCHEMA_VERSION = "1.0"
TICK_SIZE = 0.25
PRICE_SCALE = 1_000_000_000  # Databento int64 fixed-point with 9 decimals

# Aggregation 1-minute bars
BAR_INTERVAL_NS = 60 * 1_000_000_000  # 60s in nanoseconds

# Stats / heartbeat
STATS_INTERVAL_SEC = 30
STATS_THREAD_TICK_SEC = 5


class Bar1m:
    """Barre 1 minute en construction.

    side='A' (ASK) → buy, 'B' (BID) → sell, 'N' (NONE) → neutral (auction/cross/inferred).
    Les trades 'N' incrementent total_vol et n_trades mais NE polluent PAS buy/sell/delta.
    """
    __slots__ = ("symbol", "ts_start", "ts_end", "open", "high", "low", "close",
                 "total_vol", "buy_vol", "sell_vol", "neutral_vol",
                 "n_trades", "max_trade_size", "delta_bar")

    def __init__(self, symbol: str, ts_start_ns: int):
        self.symbol = symbol
        self.ts_start = ts_start_ns
        self.ts_end = ts_start_ns + BAR_INTERVAL_NS
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.total_vol = 0
        self.buy_vol = 0
        self.sell_vol = 0
        self.neutral_vol = 0
        self.n_trades = 0
        self.max_trade_size = 0
        self.delta_bar = 0

    def add_trade(self, price: float, size: int, side: str):
        """side: 'A' (buy aggressor), 'B' (sell aggressor), 'N' (neutral)."""
        if self.open is None:
            self.open = price
            self.high = price
            self.low = price
        else:
            if price > self.high:
                self.high = price
            if price < self.low:
                self.low = price
        self.close = price
        self.total_vol += size
        self.n_trades += 1
        if size > self.max_trade_size:
            self.max_trade_size = size
        # FIX 07/06/2026 (verif empirique 268 bars NQ 03/06) : convention Databento
        # side='A' = action sur ASK = SELLER aggressif -> sell_vol, delta -=
        # side='B' = action sur BID = BUYER aggressif -> buy_vol, delta +=
        # Bug pre-fix : signe inverse (bars baissieres delta moyen +89.9).
        if side == "A":
            self.sell_vol += size
            self.delta_bar -= size
        elif side == "B":
            self.buy_vol += size
            self.delta_bar += size
        else:  # 'N' ou inconnu : compte volume mais pas direction
            self.neutral_vol += size

    def to_dict(self) -> dict:
        """Serialise barre fermee en dict JSONL (compatible format DMP)."""
        ts_start_ms = self.ts_start // 1_000_000
        directional_vol = self.buy_vol + self.sell_vol  # exclut neutral pour ratios
        return {
            "ts": ts_start_ms,
            "sym": self.symbol,
            "source": "databento_live",
            "schema_version": SCHEMA_VERSION,
            # OHLCV primitives
            "open": self.open,
            "bar_high": self.high,
            "bar_low": self.low,
            "close": self.close,
            "price": self.close,  # alias compat DMP
            # Volume + delta
            "total_vol": self.total_vol,
            "buy_vol": self.buy_vol,
            "sell_vol": self.sell_vol,
            "neutral_vol": self.neutral_vol,
            "delta_bar": self.delta_bar,
            "n_trades": self.n_trades,
            "max_trade_size": self.max_trade_size,
            # Ratios calcules sur volume directionnel (exclut neutral) → pas de pollution ML
            "delta_pct": round(self.delta_bar / directional_vol, 4) if directional_vol > 0 else 0,
            "ask_pct": round(self.buy_vol / directional_vol, 4) if directional_vol > 0 else 0,
        }


class Databento1mAggregator:
    """Agrege trades en barres 1 minute par symbol et flush vers JSONL."""

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.current_bars: dict[str, Bar1m] = {}
        self.writers: dict[str, "JsonlWriter"] = {}
        self.lock = threading.Lock()
        self.n_bars_written = 0
        self.n_trades_total = 0
        self.start_time = time.time()

    def _get_writer(self, symbol: str, ts_ns: int) -> "JsonlWriter":
        """Returne writer pour symbol+date courant. Cree partition si besoin."""
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
        key = f"{symbol}_{dt:%Y%m%d}"
        if key not in self.writers:
            partition = (DATA_ROOT / symbol /
                         f"year={dt.year}" / f"month={dt.month}" / f"day={dt.day}")
            partition.mkdir(parents=True, exist_ok=True)
            fp = partition / "data.jsonl"
            self.writers[key] = JsonlWriter(fp)
        return self.writers[key]

    def on_trade(self, symbol: str, ts_ns: int, price: float, size: int, side: str):
        """Accumule trade dans la barre courante. Flush si nouvelle minute.

        side : 'A' (buy aggressor), 'B' (sell aggressor), 'N' (neutral).
        """
        with self.lock:
            self.n_trades_total += 1
            bar_start_ns = (ts_ns // BAR_INTERVAL_NS) * BAR_INTERVAL_NS
            cur = self.current_bars.get(symbol)

            if cur is None or cur.ts_start != bar_start_ns:
                # Flush previous bar (si elle existe)
                if cur is not None:
                    self._flush_bar(cur)
                # New bar
                cur = Bar1m(symbol, bar_start_ns)
                self.current_bars[symbol] = cur

            cur.add_trade(price, size, side)

    def _flush_bar(self, bar: Bar1m):
        """Ecrit barre fermee dans JSONL partition correspondante."""
        if bar.close is None:
            return  # barre vide, skip
        writer = self._get_writer(bar.symbol, bar.ts_start)
        writer.write_dict(bar.to_dict())
        self.n_bars_written += 1

    def flush_all(self):
        """Ferme toutes les barres en cours (appel a l'arret)."""
        with self.lock:
            for bar in list(self.current_bars.values()):
                self._flush_bar(bar)
            self.current_bars.clear()
            for w in self.writers.values():
                w.close()

    def stats(self) -> str:
        elapsed = time.time() - self.start_time
        return (f"trades={self.n_trades_total:,} bars_written={self.n_bars_written:,} "
                f"elapsed={elapsed:.0f}s rate={self.n_trades_total/elapsed:.1f} t/s")


class JsonlWriter:
    """Writer JSONL append-only avec flush automatique.

    Si le fichier existe deja avec un schema_version different, rotation
    en .bak_HHMMSS pour eviter de melanger 2 schemas dans un meme parquet day.
    """

    def __init__(self, fp: Path):
        self.fp = fp
        self._rotate_if_schema_mismatch(fp)
        # Append mode (resilient aux restarts)
        self._file = open(fp, "a", encoding="utf-8")

    @staticmethod
    def _rotate_if_schema_mismatch(fp: Path) -> None:
        """Rote le fichier si la 1ere ligne a un schema_version != SCHEMA_VERSION."""
        if not fp.exists() or fp.stat().st_size == 0:
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            if not first_line:
                return
            d = json.loads(first_line)
            existing = d.get("schema_version")
            if existing and existing != SCHEMA_VERSION:
                stamp = datetime.now(tz=timezone.utc).strftime("%H%M%S")
                bak = fp.with_suffix(f".jsonl.bak_{stamp}")
                fp.rename(bak)
                print(f"[DATABENTO DUMPER] Schema mismatch ({existing} != {SCHEMA_VERSION}), "
                      f"rotated existing file to {bak.name}", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[DATABENTO DUMPER] Schema check failed for {fp.name}: {e}", file=sys.stderr)

    def write_dict(self, d: dict):
        self._file.write(json.dumps(d, default=str) + "\n")
        self._file.flush()  # flush imediat pour resilience crash

    def close(self):
        try:
            self._file.close()
        except OSError as e:
            print(f"[DATABENTO DUMPER] Writer close failed: {e}", file=sys.stderr)


def _normalize_side(raw_side) -> str:
    """Convertit raw side (int ou str) en char 'A' / 'B' / 'N'."""
    if isinstance(raw_side, int):
        return chr(raw_side)
    if isinstance(raw_side, str):
        return raw_side
    return str(raw_side)


def _setup_signals(stop_event: threading.Event) -> None:
    """Installe handlers SIGINT (toujours) et SIGTERM (Unix + Windows si dispo)."""
    def handler(signum, frame):
        print(f"\n[DATABENTO DUMPER] Signal {signum} recu, arret propre...")
        stop_event.set()
    signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handler)
    if hasattr(signal, "SIGBREAK"):  # Windows CTRL+BREAK
        signal.signal(signal.SIGBREAK, handler)


def _start_stats_thread(aggregator: "Databento1mAggregator",
                         stop_event: threading.Event,
                         duration_sec: Optional[int]) -> threading.Thread:
    """Demarre thread daemon pour stats periodiques + duration timeout.

    NB: ne fait que set stop_event ; le thread principal s'arrete naturellement
    via le check `if stop_event.is_set(): break`. Pas d'appel client.stop()
    cross-thread (race condition documentee par review).
    """
    def loop():
        last_print = time.time()
        while not stop_event.is_set():
            time.sleep(STATS_THREAD_TICK_SEC)
            now = time.time()
            if now - last_print >= STATS_INTERVAL_SEC:
                print(f"[STATS] {aggregator.stats()}")
                last_print = now
            if duration_sec and (now - aggregator.start_time) >= duration_sec:
                print(f"[DATABENTO DUMPER] Duration {duration_sec}s atteinte, arret.")
                stop_event.set()
                break
    t = threading.Thread(target=loop, daemon=True, name="dumper_stats")
    t.start()
    return t


def _process_trade(record: TradeMsg,
                    aggregator: "Databento1mAggregator",
                    symbology: dict) -> None:
    """Convertit un TradeMsg en appel aggregator.on_trade."""
    inst_id = record.instrument_id
    symbol = symbology.get(inst_id, f"UNKNOWN_{inst_id}")
    price = float(record.price) / PRICE_SCALE
    size = int(record.size)
    side = _normalize_side(record.side)
    ts_ns = int(record.ts_event)
    aggregator.on_trade(symbol, ts_ns, price, size, side)


def _stream_records(client: "db.Live",
                     aggregator: "Databento1mAggregator",
                     stop_event: threading.Event) -> None:
    """Boucle principale : iter records, dispatch par isinstance."""
    n_errors = 0
    for record in client:
        if stop_event.is_set():
            break
        if isinstance(record, TradeMsg):
            _process_trade(record, aggregator, client.symbology_map)
        elif isinstance(record, SymbolMappingMsg):
            # client.symbology_map est mis a jour automatiquement par la lib,
            # on n'a rien a faire ici. Log pour audit.
            pass
        elif isinstance(record, ErrorMsg):
            n_errors += 1
            print(f"[DATABENTO ERROR #{n_errors}] {getattr(record, 'err', record)}",
                  file=sys.stderr)
        elif isinstance(record, SystemMsg):
            if not getattr(record, "is_heartbeat", False):
                print(f"[DATABENTO SYS] {getattr(record, 'msg', record)}")
        # Autres types ignores silencieusement (futurs schemas Databento)


def run_dumper(symbols: list[str], duration_sec: Optional[int] = None) -> None:
    """Run dumper Databento Live."""
    print(f"[DATABENTO DUMPER] Starting...")
    print(f"  Dataset : {DATASET}")
    print(f"  Symbols : {symbols}")
    print(f"  Output  : {DATA_ROOT}")
    if duration_sec:
        print(f"  Duration: {duration_sec}s")

    aggregator = Databento1mAggregator(symbols)

    # Connexion Databento Live avec auto-reconnect (resilience 24h+)
    client = db.Live(key=API_KEY, reconnect_policy=ReconnectPolicy.RECONNECT)

    def _on_reconnect(gap_start, gap_end):
        print(f"[DATABENTO DUMPER] Reconnect detected, gap=[{gap_start}, {gap_end}]. "
              f"Flushing barre courante pour eviter delta_bar pollue...",
              file=sys.stderr)
        aggregator.flush_all()

    if hasattr(client, "add_reconnect_callback"):
        client.add_reconnect_callback(_on_reconnect)

    client.subscribe(
        dataset=DATASET,
        schema="trades",
        symbols=symbols,
        stype_in="continuous",
    )

    stop_event = threading.Event()
    _setup_signals(stop_event)
    _start_stats_thread(aggregator, stop_event, duration_sec)

    print(f"[DATABENTO DUMPER] Connecte. En attente de trades...")

    try:
        _stream_records(client, aggregator, stop_event)
    except KeyboardInterrupt:
        print(f"\n[DATABENTO DUMPER] Interrompu par utilisateur")
    except Exception as e:
        print(f"[DATABENTO DUMPER] Erreur: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        print(f"[DATABENTO DUMPER] Flush final...")
        aggregator.flush_all()
        print(f"[DATABENTO DUMPER] {aggregator.stats()}")
        try:
            client.stop()
        except (OSError, RuntimeError) as e:
            print(f"[DATABENTO DUMPER] client.stop() warn: {e}", file=sys.stderr)
        print(f"[DATABENTO DUMPER] Termine.")


def main():
    parser = argparse.ArgumentParser(description="Databento Live Dumper")
    parser.add_argument("--symbols", nargs="+", default=["ES.c.0", "NQ.c.0"],
                        help="Symboles a subscriber (default: ES.c.0 NQ.c.0)")
    parser.add_argument("--duration", type=int, default=None,
                        help="Duration max secondes (default: infini)")
    args = parser.parse_args()

    run_dumper(args.symbols, args.duration)


if __name__ == "__main__":
    main()
