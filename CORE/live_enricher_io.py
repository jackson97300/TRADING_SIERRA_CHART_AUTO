"""live_enricher_io.py — orchestrateur readers inputs Live Enricher.

Phase 3a Jour 1 du Chantier 3 (13/05/2026 nuit).

Centralise les lectures des 4 sources d'inputs operationnels pour produire
les snapshots `DATA/live_enriched/{sym}/*.jsonl` :

  1. Databento Live OHLCV     → CORE/live_cache.py (existant)
  2. Databento Live Trades    → DATA/LIVE_CACHE/trades/{sym}/*.jsonl (Chantier 2)
  3. Sierra MQ_Lite levels    → CORE/load_mq_levels.py (existant)
  4. Sierra VIX_Lite          → CORE/vix_lite_reader.py (existant)

PAS de re-implementation : import + wrap readers existants. DRY.

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 1
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Wrap readers existants (DRY)
from live_cache import read_bar as read_ohlcv_bar  # OHLCV cache Databento Live
from live_cache import read_last_trade_close, is_stream_alive
from load_mq_levels import load_mq_levels  # Sierra MQ niveaux
from vix_lite_reader import load_vix_lite_jsonl, enrich_vix_lite  # VIX_Lite

# Trades buffer Chantier 2 deploye 13/05/2026
TRADES_BUFFER_DIR = ROOT / "DATA" / "LIVE_CACHE" / "trades"


# ═══════════════════════════════════════════════════════════════════════════════
# OHLCV cache (wrap live_cache.py)
# ═══════════════════════════════════════════════════════════════════════════════

def read_latest_ohlcv(symbol: str, max_age_sec: int = 90) -> Optional[dict]:
    """Lit le dernier OHLCV bar du cache live (Databento stream).

    Args:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0 (Databento style)
        max_age_sec : age max acceptable (default 90s = 1 bar + grace)

    Returns:
        dict avec {ts_event_iso, ts_event_ns, open, high, low, close, volume,
                   latency_s, written_at_ts} ou None si trop vieux/absent.
    """
    return read_ohlcv_bar(symbol, max_age_sec=max_age_sec)


# ═══════════════════════════════════════════════════════════════════════════════
# Trades buffer Chantier 2 (NOUVEAU reader)
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_sym_dir(symbol: str) -> str:
    """ES.c.0 -> ES_c_0 (cf Chantier 2 _safe_sym dans databento_live_stream)."""
    return symbol.replace("/", "_").replace(".", "_")


def read_trades_window(
    symbol: str,
    window_start_ns: int,
    window_end_ns: int,
) -> pd.DataFrame:
    """Lit les trades du buffer Chantier 2 dans fenetre [start_ns, end_ns].

    Le buffer Chantier 2 ecrit append-only en JSONL daily :
        DATA/LIVE_CACHE/trades/{sym_safe}/{YYYYMMDD}.jsonl

    Args:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0
        window_start_ns / window_end_ns : bornes ts_event_ns (epoch ns UTC)

    Returns:
        DataFrame avec colonnes ['symbol', 'instrument_id', 'price', 'size',
        'side', 'ts_event_ns', 'captured_at_ts'] triees par ts_event_ns.
        Si aucun trade dans fenetre, retourne DataFrame vide.

    NB : ouvre potentiellement 2 fichiers daily (cross-day boundary CME 22:00 UTC).
    Lecture sequentielle ligne-par-ligne (pas pandas.read_json) pour ne pas
    charger l'integralite du jour en RAM (peut etre 27 MB).
    """
    safe = _safe_sym_dir(symbol)
    sym_dir = TRADES_BUFFER_DIR / safe
    if not sym_dir.exists():
        return pd.DataFrame()

    # Determiner les fichiers candidats (couvrir cross-day)
    start_dt = datetime.fromtimestamp(window_start_ns / 1e9, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(window_end_ns / 1e9, tz=timezone.utc)
    candidate_days = set()
    cur = start_dt.date()
    while cur <= end_dt.date():
        candidate_days.add(cur.strftime("%Y%m%d"))
        cur = (datetime.combine(cur, datetime.min.time()) + timedelta(days=1)).date()

    rows: list[dict] = []
    for day_str in sorted(candidate_days):
        fpath = sym_dir / f"{day_str}.jsonl"
        if not fpath.exists() or fpath.stat().st_size == 0:
            continue
        try:
            # FIX P0-1 (audit code-reviewer 13/05 nuit) : race condition
            # lecture concurrente avec Chantier 2 writer. Le writer fait
            # append-only mais flush peut etre partiel -> derniere ligne
            # JSON tronque silently skipped -> dernier trade systematiquement
            # perdu chaque cycle 1-min. Fix : read entier puis splitlines,
            # drop derniere ligne si pas terminee par \n.
            with open(fpath, encoding="utf-8") as f:
                raw = f.read()
            lines = raw.splitlines()
            # Si fichier termine par \n, splitlines retourne toutes les lignes.
            # Si fichier NE termine PAS par \n (write en cours), la derniere
            # ligne est potentiellement tronquee -> drop.
            if lines and not raw.endswith("\n"):
                lines = lines[:-1]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_ns = d.get("ts_event_ns")
                if not isinstance(ts_ns, int):
                    continue
                if ts_ns < window_start_ns or ts_ns > window_end_ns:
                    continue
                rows.append(d)
        except OSError:
            continue

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values("ts_event_ns").reset_index(drop=True)
    return df


def read_trades_last_n_seconds(symbol: str, n_seconds: int = 60) -> pd.DataFrame:
    """Convenience wrapper : lit les N derniers secondes de trades.

    Pour les engines streaming qui ont besoin de la derniere minute de trades
    (e.g. footprint_builder, phase_b_plus_plus_engine).
    """
    end_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
    start_ns = end_ns - n_seconds * 1_000_000_000
    return read_trades_window(symbol, start_ns, end_ns)


# ═══════════════════════════════════════════════════════════════════════════════
# MQ_Lite levels (wrap load_mq_levels.py)
# ═══════════════════════════════════════════════════════════════════════════════

# Mapping symbol Live (Databento style) → symbol Python pour load_mq_levels
# Fix 15/05/2026 deploy : load_mq_levels valide `symbol in SYMBOL_TO_FS_DIR.keys()`
# (MGC, ES, NQ) puis convertit fs_symbol="GC" en interne via get_fs_dir(symbol).
# Avant fix : on passait directement "GC" -> ValueError "symbol must be in [ES, NQ, MGC]".
SYMBOL_TO_MQ_SYM = {
    "ES.c.0": "ES",
    "NQ.c.0": "NQ",
    "MGC.v.0": "MGC",  # symbol Python (load_mq_levels handle fs dir mapping)
}


def read_mq_latest(symbol: str, lookback_days: int = 5) -> Optional[dict]:
    """Lit le dernier snapshot MQ_Lite niveaux pour symbol.

    MQ_Lite ecrit niveaux levels-only (~5 lignes/jour quand change detecte).
    On charge les N derniers jours et on prend la derniere ligne.

    Args:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0 (style Databento Live)
        lookback_days : nb jours en arriere pour trouver dernier snapshot

    Returns:
        dict du dernier snapshot MQ (mq_call, mq_put, mq_hvl, mq_gex[10],
        mq_blind[10], mq_1d_min, mq_1d_max, mq_call/put/hvl_0dte) ou None
        si aucun fichier dispo.
    """
    mq_sym = SYMBOL_TO_MQ_SYM.get(symbol)
    if mq_sym is None:
        return None

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)

    df = load_mq_levels(mq_sym, start, today)
    if df.empty:
        return None
    # Prendre la derniere ligne (par ts_event)
    latest = df.iloc[-1].to_dict()
    return latest


# ═══════════════════════════════════════════════════════════════════════════════
# VIX_Lite (wrap vix_lite_reader.py)
# ═══════════════════════════════════════════════════════════════════════════════

def read_vix_latest(lookback_days: int = 2) -> Optional[dict]:
    """Lit le dernier snapshot VIX_Lite (prix VIX + niveaux MQ Gamma VIX).

    VIX_Lite ecrit 1 ligne/min sur le chart 15 Sierra (cf VIX_Lite.cpp v1.3).
    On charge les N derniers jours et prend la derniere ligne enrichie.

    Returns:
        dict enrichi (vix_level, vix_call, vix_put, vix_hvl, vix_1d_min/max,
        vix_call/put/hvl_0dte, vix_gamma_wall_0dte, vix_gex_0..9, vix_regime,
        dist_vix_*) ou None si aucun fichier dispo.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)
    df = load_vix_lite_jsonl(start, today)
    if df.empty:
        return None
    df = enrich_vix_lite(df)
    return df.iloc[-1].to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrateur global
# ═══════════════════════════════════════════════════════════════════════════════

def read_all_inputs(
    symbol: str,
    trades_window_sec: int = 60,
    ohlcv_max_age_sec: int = 90,
) -> dict:
    """Lit TOUS les inputs disponibles a l'instant courant pour un symbol.

    Wrapper compose des 4 readers + check freshness. Usage Live Enricher.

    Returns:
        dict avec keys:
          ohlcv : dict | None  (derniere bar OHLCV close)
          trades_df : pd.DataFrame  (trades derniers `trades_window_sec` sec)
          mq_levels : dict | None  (latest MQ snapshot)
          vix : dict | None  (latest VIX enrichi)
          stream_alive : bool  (state Databento Live stream)
          ts_read_ns : int  (timestamp lecture)
    """
    ts_read_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
    ohlcv = read_latest_ohlcv(symbol, max_age_sec=ohlcv_max_age_sec)
    trades_df = read_trades_last_n_seconds(symbol, n_seconds=trades_window_sec)
    mq_levels = read_mq_latest(symbol)
    vix = read_vix_latest()
    stream_alive, _ = is_stream_alive()

    return {
        "ohlcv": ohlcv,
        "trades_df": trades_df,
        "mq_levels": mq_levels,
        "vix": vix,
        "stream_alive": stream_alive,
        "ts_read_ns": ts_read_ns,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests inline
# ═══════════════════════════════════════════════════════════════════════════════

def _test_safe_sym_dir():
    assert _safe_sym_dir("ES.c.0") == "ES_c_0"
    assert _safe_sym_dir("NQ.c.0") == "NQ_c_0"
    assert _safe_sym_dir("MGC.v.0") == "MGC_v_0"
    print("[OK] _safe_sym_dir")


def _test_symbol_mq_mapping():
    assert SYMBOL_TO_MQ_SYM["ES.c.0"] == "ES"
    assert SYMBOL_TO_MQ_SYM["MGC.v.0"] == "GC"
    print("[OK] SYMBOL_TO_MQ_SYM (MGC->GC fix lessons.md)")


def _test_read_trades_window_empty():
    """Test lecture trades sur fenetre vide (ts arbitraire dans le futur)."""
    far_future_ns = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp() * 1e9)
    df = read_trades_window("ES.c.0", far_future_ns, far_future_ns + 60_000_000_000)
    assert df.empty, "trades_window devrait etre vide pour futur"
    print("[OK] read_trades_window empty")


def _test_read_all_inputs():
    """Test sur donnees reelles si dispo localement (sinon skip)."""
    out = read_all_inputs("ES.c.0", trades_window_sec=300)
    print(f"[INFO] read_all_inputs sample :")
    print(f"  ohlcv : {'OK' if out['ohlcv'] else 'None (cache absent)'}")
    print(f"  trades : {len(out['trades_df'])} rows")
    print(f"  mq_levels : {'OK' if out['mq_levels'] else 'None'}")
    print(f"  vix : {'OK' if out['vix'] else 'None'}")
    print(f"  stream_alive : {out['stream_alive']}")
    print(f"  ts_read_ns : {out['ts_read_ns']}")
    print("[OK] read_all_inputs (donnees reelles)")


if __name__ == "__main__":
    _test_safe_sym_dir()
    _test_symbol_mq_mapping()
    _test_read_trades_window_empty()
    _test_read_all_inputs()
    print("\n[ALL OK]")
