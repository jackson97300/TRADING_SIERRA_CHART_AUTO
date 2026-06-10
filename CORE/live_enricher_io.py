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
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# ═══════════════════════════════════════════════════════════════════════════════
# ENRICHER_SOURCE env var (Plan A Sem 1 — 07/06/2026)
# ═══════════════════════════════════════════════════════════════════════════════
# Architecture shadow : default `databento` preserve la prod 24/7 (MIA-Live-Enricher
# Running sur VPS). Bascule `sierra` reservee aux tests parite + cutover progressif.
#
# CONTRAINTE SOUVERAINE Jackson 07/06 : "on branche en parallele du systeme actuel,
# on doit etre full Sierra". Sequence C (hybride) : bars/delta/swings/IB/VP via
# Sierra natif, MAIS garde game_changers Python pour open_type/open_zone
# (divergence empirique 100% sur 03/06 NQ - audit parite a faire Sem 2-3).
#
# Rollback : ENRICHER_SOURCE=databento (default) restaure le pipeline Databento.
# ═══════════════════════════════════════════════════════════════════════════════
ENRICHER_SOURCE = os.environ.get("ENRICHER_SOURCE", "databento").lower()
if ENRICHER_SOURCE not in ("databento", "sierra"):
    raise ValueError(
        f"ENRICHER_SOURCE invalide : {ENRICHER_SOURCE!r}. "
        f"Valeurs autorisees : 'databento' (default, prod) ou 'sierra' (Plan A shadow)."
    )

# Wrap readers existants (DRY)
from live_cache import read_bar as read_ohlcv_bar  # OHLCV cache Databento Live
from live_cache import read_last_trade_close, is_stream_alive
from load_mq_levels import load_mq_levels  # Sierra MQ niveaux
from vix_lite_reader import load_vix_lite_jsonl, enrich_vix_lite  # VIX_Lite

# Import conditionnel Sierra reader (Plan A Sem 1)
if ENRICHER_SOURCE == "sierra":
    from sierra_live_io import SierraLiveReader
    # Cache des readers par symbol (instanciation paresseuse, 1 per symbol)
    _sierra_readers: dict[str, "SierraLiveReader"] = {}

# Mapping Databento ticker (ES.c.0) -> Sierra filesystem symbol (ES)
# MGC pas supporte Sierra V1 (cf sierra_live_io.SUPPORTED_SYMBOLS = ("ES", "NQ"))
# -> en mode sierra, MGC fallback Databento (duplication temporaire Phase 8+).
SYMBOL_TO_SIERRA_FS = {"ES.c.0": "ES", "NQ.c.0": "NQ"}

# Trades buffer Chantier 2 deploye 13/05/2026 (consume uniquement mode databento)
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

# ═══════════════════════════════════════════════════════════════════════════════
# Sierra OHLCV reader (Plan A Sem 1 — 07/06/2026)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_sierra_reader(symbol_fs: str) -> "SierraLiveReader":
    """Cache paresseux 1 SierraLiveReader par symbol filesystem (ES, NQ).

    Reutilise le buffer rolling entre appels successifs (anti re-lecture
    disk full daily JSONL a chaque poll).
    """
    if symbol_fs not in _sierra_readers:
        # window_bars=480 = 8h de bars 1min, suffisant pour Phase B+/Wyckoff context
        _sierra_readers[symbol_fs] = SierraLiveReader(
            symbol=symbol_fs, window_bars=480, strict=False
        )
    return _sierra_readers[symbol_fs]


def read_latest_ohlcv_sierra(symbol: str, max_age_sec: int = 90) -> Optional[dict]:
    """Lit la derniere bar Sierra DMP et la mappe au contrat OHLCV expected.

    Contrat de sortie identique a `read_latest_ohlcv` mode Databento :
      ts_event_ns, ts_event_iso, open, high, low, close, volume

    PLUS un passthrough `_sierra_bar` contenant la bar Sierra complete (380 cols)
    pour que enricher_chain puisse lire les features natives Sierra (delta_bar,
    swing_high, dist_ib_*, open_type, etc.) au lieu de les recalculer.

    Returns:
        dict | None si bar fraiche absente (age > max_age_sec) ou MGC (non
        supporte Sierra V1).
    """
    if symbol not in SYMBOL_TO_SIERRA_FS:
        # MGC : fallback transparent vers Databento (le caller doit gerer)
        return None

    symbol_fs = SYMBOL_TO_SIERRA_FS[symbol]
    reader = _get_sierra_reader(symbol_fs)
    df = reader.load_rolling_window()
    if df is None or df.empty:
        return None

    # Check freshness via age dernier ts
    age = reader.get_last_bar_age_seconds()
    if age > max_age_sec:
        return None

    last = df.iloc[-1]
    ts_ms = int(last["ts"])  # Sierra DMP : ts en millisecondes epoch UTC
    ts_ns = ts_ms * 1_000_000  # Conversion ms -> ns (contrat enricher_chain)

    # Mapping Sierra DMP -> contrat OHLCV
    # Note B4.5 deploye 07/06 matin : `open` natif via r.price_open. Pre-deploy
    # fichiers historiques (avant B4.5) n'ont pas `open` -> fallback close prev
    # bar (degradation acceptable, audit empirique post-Asia open).
    open_val = last.get("open")
    if open_val is None or pd.isna(open_val):
        # Fallback : close de la bar precedente (pre-B4.5 backward compat)
        if len(df) >= 2:
            open_val = float(df.iloc[-2]["price"])
        else:
            open_val = float(last["price"])

    return {
        "ts_event_ns": ts_ns,
        "ts_event_iso": last["ts_event"].isoformat(),
        "open": float(open_val),
        "high": float(last["bar_high"]),
        "low": float(last["bar_low"]),
        "close": float(last["price"]),
        "volume": float(last.get("total_vol", 0.0) or 0.0),
        # Passthrough pour enricher_chain : permet lecture native Sierra
        # (delta_bar, swing_*, dist_ib_*, open_type, day_type, dist_mq_*, etc.)
        "_sierra_bar": last.to_dict(),
        "_source": "sierra",
    }


def read_all_inputs(
    symbol: str,
    trades_window_sec: int = 60,
    ohlcv_max_age_sec: int = 90,
) -> dict:
    """Lit TOUS les inputs disponibles a l'instant courant pour un symbol.

    Wrapper compose des 4 readers + check freshness. Usage Live Enricher.

    Mode `databento` (default, prod) :
      OHLCV via live_cache Databento + trades_df 60s + MQ Sierra + VIX Sierra.

    Mode `sierra` (Plan A shadow, Sem 1 07/06) :
      OHLCV via SierraLiveReader (380 cols natif C++ : delta_bar, swing, IB, etc.)
      + trades_df vide (Sierra fournit delta_bar agrege) + MQ Sierra + VIX Sierra.
      Le _sierra_bar passthrough permet a enricher_chain de skip recalcul Python
      pour LOT 1-6 (trades aggregates), game_changers (day_type), Pass 4c-prereq
      (IB/sess/VP), sessions_swings (lookahead bug).

    Returns:
        dict avec keys:
          ohlcv : dict | None  (derniere bar OHLCV close, +_sierra_bar si mode sierra)
          trades_df : pd.DataFrame  (vide en mode sierra)
          mq_levels : dict | None  (latest MQ snapshot Sierra)
          vix : dict | None  (latest VIX enrichi Sierra)
          stream_alive : bool  (state stream actif)
          ts_read_ns : int  (timestamp lecture)
          source : str  ("databento" | "sierra" pour audit)
    """
    ts_read_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)

    if ENRICHER_SOURCE == "sierra":
        ohlcv = read_latest_ohlcv_sierra(symbol, max_age_sec=ohlcv_max_age_sec)
        # Fallback Databento pour MGC (Sierra V1 ne supporte pas)
        if ohlcv is None and symbol not in SYMBOL_TO_SIERRA_FS:
            ohlcv = read_latest_ohlcv(symbol, max_age_sec=ohlcv_max_age_sec)
        # trades_df vide en mode Sierra : delta_bar deja agrege natif C++.
        # enricher_chain detecte _source=="sierra" et skip LOT 1-6.
        trades_df = pd.DataFrame()
        stream_alive = ohlcv is not None  # heuristique : bar fraiche = alive
    else:
        # Mode databento (default, prod 24/7 inchange)
        ohlcv = read_latest_ohlcv(symbol, max_age_sec=ohlcv_max_age_sec)
        trades_df = read_trades_last_n_seconds(symbol, n_seconds=trades_window_sec)
        stream_alive, _ = is_stream_alive()

    mq_levels = read_mq_latest(symbol)
    vix = read_vix_latest()

    return {
        "ohlcv": ohlcv,
        "trades_df": trades_df,
        "mq_levels": mq_levels,
        "vix": vix,
        "stream_alive": stream_alive,
        "ts_read_ns": ts_read_ns,
        "source": ENRICHER_SOURCE,
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
