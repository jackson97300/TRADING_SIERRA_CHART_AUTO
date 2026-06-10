"""replay_enricher_batch.py — Replay batch du pipeline enricher sur historique.

REFACTOR Option B (2026-05-16) : reutilise `enricher_chain.compose_enriched_payload`
(meme code que live_enricher) pour produire un dataset 100% identique au live
sur des donnees historiques.

Architecture :
  - Sources :
      * OHLCV : DATA/databento/GLBX.MDP3/ohlcv-1m/symbol={sym}/year=*/month=*/day=*/data_*.parquet
      * Trades : DATA/databento/GLBX.MDP3/trades/symbol={sym}/year=*/month=*/day=*/data_*.parquet
      * MQ levels : DATA/MENTHORQ/{YYYYMMDD}_menthorq_complete.json (daily snapshot)
      * VIX : DATA/vix_levels/year=*/month=*/day=*/vix.jsonl (replay Sierra Chart 15)
  - Output : DATA/live_enriched/{SYM_SAFE}/{YYYYMMDD}.jsonl (meme format que live)
  - State : DATA/LIVE_CACHE/_state/{sym}_state.pkl (resume + isolation par symbole)

Conventions batch (cf DOCS/batch_semantics_decision.md) :
  - `stream_alive = True` constant
  - `ts_read_ns = ts_event_ns + 60_000_000_000` (bar_close + 60s)
  - `latency_s = None` en batch (NaN downstream, OK car non utilise par engines)

Usage :
  python -X utf8 CORE/replay_enricher_batch.py \
    --symbols ES.c.0 NQ.c.0 MGC.v.0 \
    --start 2026-04-14 --end 2026-04-14 \
    [--use-pre-refactor]  # pour test parite (utilise live_enricher_v_pre_refactor)

Couvre :
  - R3 (audit code-reviewer) : checkpoint state.pkl par symbole pour resume safe
  - R2 (audit code-reviewer) : permet test parite multi-jours via run cote-a-cote

Auteur : MIA Trading System V2
  v1.0 (2026-05-16) : version initiale Phase REFACTOR Option B etape 7.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import pickle
import sys
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Imports core (DRY avec live_enricher)
from enricher_chain import compose_enriched_payload
from live_enricher_state import LiveEnricherState, initialize_state, save_state, load_state
from live_enricher_writer import write_enriched_bar
from load_mq_levels import load_mq_levels as load_mq_levels_hive  # Source primaire MQ

# Logging
LOG_DIR = ROOT / "DATA" / "LOGS"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "replay_enricher_batch.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("replay_enricher_batch")

# Symbol mappings (DRY avec live_enricher_io.SYMBOL_TO_MQ_SYM)
SYMBOL_TO_MQ_SYM = {
    "ES.c.0": "ES",
    "NQ.c.0": "NQ",
    "MGC.v.0": "MGC",
}
SYMBOL_TO_MQ_JSON_KEY = {
    "ES.c.0": "ES",
    "NQ.c.0": "NQ",
    "MGC.v.0": "GOLD",  # JSON daily utilise "GOLD" pour MGC
}

# Seuil ns minimum pour fail-loud : 2001-09-08T20:46:40Z = ~1e18 ns
# (toute valeur < 1e18 ns indique un cast us->int64 par erreur car
# datetime64[us] retourne us et non ns. cf code-reviewer NOGO 16/05).
_TS_NS_MIN_GUARD = 10**18


def _to_int64_ns(series: pd.Series) -> pd.Series:
    """Convertit Series datetime64 (any unit, tz-aware OK) en int64 nanoseconds.

    BUG FIX 2026-05-16 (code-reviewer NOGO etape 7) : les parquets Databento
    stockent `ts_event` en `datetime64[us, UTC]`. `.astype("int64")` direct
    retourne des MICROSECONDES, pas des nanosecondes. Sans fix :
      - Trades window filtre sur 60e9 us = 16h40 par bar -> trades 1000x trop
      - VIX as-of `ts_event_ms = us // 1M = ~1.7M ms = epoch 1970` -> jamais match
      - Cascade pollution delta_bar, footprint, big_clusters, VIX features

    Args:
        series : pd.Series datetime64 (unit us/ns/ms/s, tz-aware OK)

    Returns:
        pd.Series int64 en nanoseconds depuis epoch UTC.

    Raises:
        TypeError si series n'est pas datetime64.
        AssertionError si conversion < seuil 1e18 (signal cast error).
    """
    if not pd.api.types.is_datetime64_any_dtype(series):
        raise TypeError(f"series must be datetime64 dtype, got {series.dtype}")
    if series.empty:
        return series.astype("int64")
    # Parse unit du dtype (ex: "datetime64[us, UTC]" -> "us")
    dtype_str = str(series.dtype)
    unit_str = dtype_str.split("[")[1].split("]")[0].split(",")[0].strip()
    multipliers = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}
    mult = multipliers.get(unit_str)
    if mult is None:
        raise ValueError(f"Unknown datetime unit '{unit_str}' in dtype {series.dtype}")
    # Underlying int value in source unit (us for Databento default)
    raw = series.astype("int64")
    ts_ns = raw * mult
    # Fail-loud guard : verifier que la conversion produit bien des ns plausibles
    # (toute valeur < 1e18 ns = avant 2001 ou cast error)
    first = int(ts_ns.iloc[0])
    if first < _TS_NS_MIN_GUARD:
        raise AssertionError(
            f"_to_int64_ns: conversion suspecte (first={first}, dtype={series.dtype}, "
            f"unit={unit_str}, mult={mult}). Expected ts_ns > {_TS_NS_MIN_GUARD} (post-2001)."
        )
    return ts_ns


# ════════════════════════════════════════════════════════════════════════════
# LOADERS — sources historiques
# ════════════════════════════════════════════════════════════════════════════

def _find_databento_parquets(schema: str, symbol: str, target_date: date) -> list[str]:
    """Liste les parquets Databento pour (schema, symbol, target_date).

    Gere les patterns de partitionnement observes :
    - Pattern A (ES/NQ jours anciens) : `year=Y/month=M/day=D/data_0.parquet, data_1.parquet, ...`
    - Pattern A' (jours recents mai 2026) : `year=Y/month=M/day=D/data.parquet` (1 fichier)
    - Pattern B (MGC OHLCV mensuel) : `year=Y/month=MM/data.parquet`
      (zero-padded, 1 parquet mensuel agrege - on chargera puis filtrera)

    Note : glob "data*.parquet" capture A et A' (data.parquet ET data_*.parquet).

    Returns:
        list[str] : fichiers trouves (vide si rien).
    """
    yyyy = target_date.year
    mm = target_date.month
    dd = target_date.day
    base = ROOT / "DATA" / "databento" / "GLBX.MDP3" / schema / f"symbol={symbol}"

    # Pattern A/A' : daily granular - sans zero-padding mois (ES/NQ moderne)
    pat = base / f"year={yyyy}" / f"month={mm}" / f"day={dd}" / "data*.parquet"
    files = sorted(glob.glob(str(pat)))
    if files:
        return files

    # Pattern A/A' bis : zero-padded month
    pat = base / f"year={yyyy}" / f"month={mm:02d}" / f"day={dd}" / "data*.parquet"
    files = sorted(glob.glob(str(pat)))
    if files:
        return files

    # Pattern B : monthly aggregated (zero-padded) - 1 seul "data.parquet" mensuel
    pat = base / f"year={yyyy}" / f"month={mm:02d}" / "data.parquet"
    files = sorted(glob.glob(str(pat)))
    if files:
        return files

    # Pattern B bis : non-zero-padded
    pat = base / f"year={yyyy}" / f"month={mm}" / "data.parquet"
    return sorted(glob.glob(str(pat)))


def _filter_trading_day(df: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """Filtre DataFrame sur trading_day Globex CME.

    CME futures trading_day = [veille 22:00 UTC, target 22:00 UTC).
    (= [veille 18:00 ET, target 18:00 ET))

    Gere ts_event tz-aware (ES/NQ datetime64[us, UTC]) et tz-naive
    (MGC monthly datetime64[ns] sans tz, suppose UTC).
    """
    if df.empty or "ts_event" not in df.columns:
        return df
    from datetime import datetime as _dt

    # Detecter tz-aware ou tz-naive
    ts_dtype = df["ts_event"].dtype
    is_tz_aware = getattr(ts_dtype, "tz", None) is not None

    if is_tz_aware:
        start_bound = _dt.combine(
            target_date - timedelta(days=1),
            _dt.min.time().replace(hour=22),
        ).replace(tzinfo=timezone.utc)
        end_bound = _dt.combine(
            target_date,
            _dt.min.time().replace(hour=22),
        ).replace(tzinfo=timezone.utc)
    else:
        # ts_event sans tz - comparaison tz-naive (suppose UTC)
        start_bound = _dt.combine(
            target_date - timedelta(days=1),
            _dt.min.time().replace(hour=22),
        )
        end_bound = _dt.combine(
            target_date,
            _dt.min.time().replace(hour=22),
        )

    mask = (df["ts_event"] >= start_bound) & (df["ts_event"] < end_bound)
    return df.loc[mask].reset_index(drop=True)


def _ensure_ts_event_col(df: pd.DataFrame) -> pd.DataFrame:
    """Promote ts_event index -> column si necessaire.

    Certains parquets Databento jours recents (mai 2026+) stockent ts_event
    en DatetimeIndex (vs colonne pour les jours anciens). Reset_index uniforme.
    """
    if df.empty:
        return df
    if "ts_event" not in df.columns:
        # Verifier si l'index est ts_event
        idx_name = df.index.name
        if idx_name == "ts_event":
            df = df.reset_index(drop=False)
    return df


def load_databento_ohlcv_day(symbol: str, target_date: date) -> pd.DataFrame:
    """Charge OHLCV-1m parquets pour `symbol` et `target_date`.

    Args:
        symbol : "ES.c.0", "NQ.c.0", "MGC.v.0"
        target_date : date du jour à charger

    Returns:
        DataFrame trie par ts_event (asc), filtre sur trading_day Globex.
    """
    files = _find_databento_parquets("ohlcv-1m", symbol, target_date)
    if not files:
        return pd.DataFrame()

    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs)
    if df.empty:
        return df

    # FIX : ts_event peut etre l'INDEX (parquets recents) au lieu de col.
    df = _ensure_ts_event_col(df)
    df = df.reset_index(drop=True)

    # Si parquet monthly (pattern B, > 1500 bars = >1 jour), filtrer trading_day.
    if len(df) > 1500:
        df = _filter_trading_day(df, target_date)

    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def load_databento_trades_day(symbol: str, target_date: date) -> pd.DataFrame:
    """Charge trades raw parquets pour `symbol` et `target_date`.

    Returns:
        DataFrame trie par ts_event_ns (asc), filtre sur trading_day Globex.
    """
    files = _find_databento_parquets("trades", symbol, target_date)
    if not files:
        return pd.DataFrame()

    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs)
    if df.empty:
        return df

    # FIX : ts_event peut etre l'INDEX (parquets recents) au lieu de col.
    df = _ensure_ts_event_col(df)
    df = df.reset_index(drop=True)

    # FIX BUG us/ns : helper safe (datetime64[us, UTC] -> int64 ns).
    if "ts_event" in df.columns and "ts_event_ns" not in df.columns:
        df["ts_event_ns"] = _to_int64_ns(df["ts_event"])

    # Si parquet monthly (pattern B, > 5M rows), filtrer trading_day.
    if len(df) > 5_000_000:
        df = _filter_trading_day(df, target_date)
        # Re-build ts_event_ns apres filter (re-index)
        if "ts_event" in df.columns:
            df["ts_event_ns"] = _to_int64_ns(df["ts_event"])

    df = df.sort_values("ts_event_ns").reset_index(drop=True)
    return df


def load_mq_hive_window(symbol: str, target_date: date) -> pd.DataFrame:
    """Charge MQ_Lite Hive levels.jsonl pour fenetre [target_date-1, target_date].

    MQ_Lite ecrit 1 ligne par CHANGEMENT de niveau (~5 lignes/jour).
    Pour as-of join intra-bar, on charge veille + courant.

    Source primaire pour le batch (cf live_enricher_io.read_mq_latest).
    Fallback : MenthorQ JSON daily (build_mq_levels_from_json).

    Returns:
        DataFrame trie par ts_event (datetime UTC naive) avec cols
        mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte, mq_hvl_0dte,
        mq_1d_min, mq_1d_max, mq_gex[10], mq_blind[10], trigger.
        DataFrame vide si pas de donnees MQ_Lite Hive pour cette periode.
    """
    mq_sym = SYMBOL_TO_MQ_SYM.get(symbol)
    if mq_sym is None:
        return pd.DataFrame()
    start = target_date - timedelta(days=1)
    end = target_date
    try:
        df = load_mq_levels_hive(mq_sym, start, end)
    except Exception as e:
        logger.warning(f"load_mq_levels_hive({mq_sym}) fail: {e}")
        return pd.DataFrame()
    return df


def build_mq_levels_from_hive(
    mq_hive_df: pd.DataFrame,
    ts_event_ns: int,
    symbol: str,
) -> Optional[dict]:
    """As-of join : retourne la derniere ligne MQ_Lite Hive avec ts <= ts_event_ns.

    Args:
        mq_hive_df : output load_mq_hive_window
        ts_event_ns : timestamp bar courante en ns
        symbol : pour completer mq_sym dans le payload retourne

    Returns:
        dict format aligne MQ_Lite Hive (mq_call/put/hvl, mq_gex[10],
        mq_blind[10], mq_1d_min/max, mq_*_0dte, ts_event, mq_sym, etc.) ou None.
    """
    if mq_hive_df is None or mq_hive_df.empty:
        return None
    # Convertir ts_event_ns en datetime UTC naive (aligne mq_hive_df["ts_event"])
    ts_event = pd.Timestamp(ts_event_ns, unit="ns")  # naive UTC
    mask = mq_hive_df["ts_event"] <= ts_event
    if not mask.any():
        return None
    last_row = mq_hive_df.loc[mask].iloc[-1].to_dict()
    # Aligner format payload (cf SYMBOL_TO_MQ_SYM + ts_event ISO format)
    last_row["mq_sym"] = SYMBOL_TO_MQ_SYM.get(symbol, "")
    last_row["mq_schema_version"] = "mq_levels_1.0"
    last_row["mq_trigger"] = last_row.get("trigger", "hive_asof")
    # ts_event ISO format (vs Timestamp pandas) pour compat live writer
    if isinstance(last_row.get("ts_event"), pd.Timestamp):
        last_row["ts_event"] = last_row["ts_event"].isoformat()
    return last_row


def load_menthorq_daily(target_date: date) -> Optional[dict]:
    """Charge MenthorQ JSON daily pour target_date.

    Returns:
        dict avec keys [date, source, CTA, key_levels, vol_model] ou None
    """
    date_str = target_date.strftime("%Y%m%d")
    fpath = ROOT / "DATA" / "MENTHORQ" / f"{date_str}_menthorq_complete.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"MenthorQ JSON {date_str} load fail: {e}")
        return None


def load_vix_history_day(target_date: date, include_previous_day: bool = True) -> pd.DataFrame:
    """Charge VIX vix.jsonl (1 ligne/min) pour target_date + jour precedent.

    FIX BUG (verif anti-triche 16/05) : les bars Databento overnight Globex
    (22:00-23:59 UTC veille) sont attribuees au trading_day suivant mais en
    wall-clock UTC = veille. Le VIX historique du `target_date` commence
    ~07:15 UTC -> mismatch pour bars overnight -> vix_level=None silencieux.

    Solution : charger target_date - 1 ET target_date, concat. Les bars
    overnight prennent le dernier VIX de la veille (close 20:15 UTC).

    Args:
        target_date : date du trading_day
        include_previous_day : si True, concat veille (default True).

    Returns:
        DataFrame trie par ts asc, colonnes [ts (ms epoch UTC), vix_level, ...]
    """
    def _load_single(d: date) -> pd.DataFrame:
        fpath = (
            ROOT / "DATA" / "vix_levels"
            / f"year={d.year}" / f"month={d.month}" / f"day={d.day}" / "vix.jsonl"
        )
        if not fpath.exists():
            return pd.DataFrame()
        rows = []
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning(f"VIX {d} load fail: {e}")
            return pd.DataFrame()
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    dfs = []
    if include_previous_day:
        prev_day = target_date - timedelta(days=1)
        df_prev = _load_single(prev_day)
        if not df_prev.empty:
            dfs.append(df_prev)
    df_cur = _load_single(target_date)
    if not df_cur.empty:
        dfs.append(df_cur)

    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    if "ts" in df.columns:
        df = df.sort_values("ts").reset_index(drop=True)
        df = df.drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    return df


# ════════════════════════════════════════════════════════════════════════════
# BUILDERS — convert sources -> inputs dict (cf DOCS/batch_semantics_decision.md)
# ════════════════════════════════════════════════════════════════════════════

def build_ohlcv_dict(row: pd.Series, symbol: str) -> dict:
    """Construit ohlcv dict depuis row parquet (convention batch).

    Convention batch : `latency_s=None`, `age_sec=0.0`, `written_at_*=None`.
    """
    ts_event = row["ts_event"]
    if isinstance(ts_event, pd.Timestamp):
        ts_event_ns = int(ts_event.value)
        ts_event_iso = ts_event.isoformat()
    else:
        ts_event_ns = int(ts_event)
        ts_event_iso = pd.Timestamp(ts_event_ns, unit="ns", tz="UTC").isoformat()

    return {
        "symbol": symbol,
        "instrument_id": int(row.get("instrument_id", 0)),
        "ts_event_iso": ts_event_iso,
        "ts_event_ns": ts_event_ns,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": int(row["volume"]),
        "latency_s": None,
        "written_at_iso": None,
        "written_at_ts": None,
        "age_sec": 0.0,
    }


def build_trades_window(
    trades_full: pd.DataFrame,
    bar_start_ns: int,
    bar_end_ns: int,
) -> pd.DataFrame:
    """Filtre trades sur fenetre [bar_start_ns, bar_end_ns] alignee sur bar OHLCV."""
    if trades_full.empty:
        return pd.DataFrame()
    mask = (trades_full["ts_event_ns"] >= bar_start_ns) & (trades_full["ts_event_ns"] < bar_end_ns)
    return trades_full.loc[mask].reset_index(drop=True)


def build_mq_levels_from_json(
    mq_json: Optional[dict],
    symbol: str,
    target_date: date,
) -> Optional[dict]:
    """Construit mq_levels dict depuis MenthorQ JSON daily (broadcast intraday).

    Args:
        mq_json : output de load_menthorq_daily, None si JSON manquant
        symbol : "ES.c.0" / "NQ.c.0" / "MGC.v.0"
        target_date : date du jour

    Returns:
        dict aligne format MQ_Lite Hive (mq_call, mq_put, mq_hvl, mq_*_0dte,
        mq_1d_min/max, mq_gex[10], mq_blind[10], mq_gamma_condition, mq_iv_30d,
        ts_event) ou None si JSON absent.
    """
    if mq_json is None:
        return None

    mq_key = SYMBOL_TO_MQ_JSON_KEY.get(symbol)
    if mq_key is None:
        return None

    kl = mq_json.get("key_levels", {}).get(mq_key, {})
    vm = mq_json.get("vol_model", {}).get(mq_key, {})

    if not kl and not vm:
        return None  # symbole absent du JSON ce jour

    # Build mq dict aligne MQ_Lite schema
    out = {
        "mq_sym": SYMBOL_TO_MQ_SYM.get(symbol, ""),
        "mq_schema_version": "mq_levels_1.0",
        "mq_trigger": "json_daily",  # vs "level_change" en live MQ_Lite
        "ts_event": f"{target_date.isoformat()}T00:00:00",
        # Scalars (key_levels)
        "mq_call": kl.get("call_resistance"),
        "mq_put": kl.get("put_support"),
        "mq_hvl": kl.get("hvl"),
        "mq_call_0dte": kl.get("call_resistance_0dte"),
        "mq_put_0dte": kl.get("put_support_0dte"),
        "mq_hvl_0dte": kl.get("hvl_0dte"),
        "mq_1d_max": kl.get("1d_max"),
        "mq_1d_min": kl.get("1d_min"),
        "mq_iv_30d": kl.get("iv_30d"),
        "mq_gamma_condition": kl.get("gamma_condition"),
        "mq_pc_oi": kl.get("pc_oi"),
        "mq_total_gex": kl.get("total_gex"),
        "mq_net_gex": kl.get("net_gex"),
        "mq_pc_gex": kl.get("pc_gex"),
        "mq_total_dex": kl.get("total_dex"),
        "mq_net_dex": kl.get("net_dex"),
        "mq_pc_dex": kl.get("pc_dex"),
        # Arrays (vol_model)
        "mq_gex": vm.get("top_gex_strikes", [None] * 10),
        "mq_blind": vm.get("bl_levels", [None] * 10),
        "mq_gamma_wall_0dte": vm.get("gamma_wall_0dte"),
    }

    return out


def build_vix_at_ts(vix_df: pd.DataFrame, ts_event_ns: int) -> Optional[dict]:
    """Retourne le dernier VIX row <= ts_event_ns (as-of join).

    Args:
        vix_df : DataFrame from load_vix_history_day (colonne `ts` en ms epoch)
        ts_event_ns : timestamp bar courante en ns

    Returns:
        dict avec keys VIX (vix_level, vix_call/put/hvl, vix_gex, etc.) ou None
        si pas de VIX avant ts_event_ns.
    """
    if vix_df.empty or "ts" not in vix_df.columns:
        return None
    ts_event_ms = ts_event_ns // 1_000_000
    mask = vix_df["ts"] <= ts_event_ms
    if not mask.any():
        return None
    last_row = vix_df.loc[mask].iloc[-1].to_dict()
    return last_row


# ════════════════════════════════════════════════════════════════════════════
# RUNNER — main loop chronologique
# ════════════════════════════════════════════════════════════════════════════

def run_replay(
    symbols: list[str],
    start_date: date,
    end_date: date,
    output_dir: Optional[Path] = None,
    state_dir: Optional[Path] = None,
    use_pre_refactor: bool = False,
    fresh_state: bool = True,
) -> dict:
    """Run replay batch sur [start_date, end_date] x symbols.

    Args:
        symbols : liste ["ES.c.0", "NQ.c.0", "MGC.v.0"]
        start_date, end_date : bornes (inclusives)
        output_dir : repertoire JSONL output (default DATA/live_enriched/)
        state_dir : repertoire state.pkl (default DATA/LIVE_CACHE/_state/)
        use_pre_refactor : si True, utilise live_enricher_v_pre_refactor pour
                           test parité. Default False (= enricher_chain refactore).
        fresh_state : si True, init state cold (ignore .pkl existant)

    Returns:
        dict stats : {symbol: {n_bars, n_fail, n_partial, ...}}
    """
    output_dir = output_dir or (ROOT / "DATA" / "live_enriched")
    state_dir = state_dir or (ROOT / "DATA" / "LIVE_CACHE" / "_state")
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    # Si use_pre_refactor : importer la chain depuis le backup (NotImplementedError
    # pour l'instant — etape 5 test parite ulterieur).
    if use_pre_refactor:
        raise NotImplementedError(
            "use_pre_refactor=True : test parite via backup pas encore implemente. "
            "Etape 5 a faire APRES coding etape 7 stable."
        )

    # Initialize states per-symbol (isole, single-thread batch)
    from collections import Counter
    states: dict[str, LiveEnricherState] = {}
    stats: dict[str, dict] = {}
    for sym in symbols:
        if fresh_state:
            states[sym] = initialize_state(sym)
        else:
            loaded = load_state(sym)
            states[sym] = loaded if loaded is not None else initialize_state(sym)
        stats[sym] = {
            "n_bars": 0,
            "n_fail": 0,
            "n_partial": 0,
            "n_data_quality_flag_set": 0,
            "fail_by_engine": Counter(),  # meta["engine_name"] aggregation
        }

    # Partner state provider (RAM dict, single-thread, no lock)
    def _batch_partner_provider(partner_sym: str) -> Optional[LiveEnricherState]:
        return states.get(partner_sym)

    # No-op log_fn (batch silencieux, log via logger pour diagnostic globaux)
    def _batch_log_fn(code: str, **kwargs) -> None:
        # En batch : log seulement les events MAJEUR+ (ENGINE_FAIL, ENGINE_STATE_FAIL).
        # Les INFO (ENRICHER_BAR_PROCESSED, etc.) sont silencieux.
        if "FAIL" in code or "PARTNER_STALE" in code:
            logger.warning(f"[{code}] {kwargs}")

    # Pre-load all data per symbol per date (memory cost OK pour 1 jour x 3 sym)
    cur_date = start_date
    while cur_date <= end_date:
        date_str = cur_date.strftime("%Y%m%d")
        logger.info(f"=== Processing {date_str} ===")

        # Load sources for this day
        ohlcv_per_sym: dict[str, pd.DataFrame] = {}
        trades_per_sym: dict[str, pd.DataFrame] = {}
        mq_hive_per_sym: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            ohlcv_per_sym[sym] = load_databento_ohlcv_day(sym, cur_date)
            trades_per_sym[sym] = load_databento_trades_day(sym, cur_date)
            mq_hive_per_sym[sym] = load_mq_hive_window(sym, cur_date)
            logger.info(
                f"  {sym} : ohlcv={len(ohlcv_per_sym[sym])} bars, "
                f"trades={len(trades_per_sym[sym])}, "
                f"mq_hive={len(mq_hive_per_sym[sym])} rows"
            )

        mq_json = load_menthorq_daily(cur_date)
        vix_df = load_vix_history_day(cur_date)
        logger.info(
            f"  MQ_json_daily={'OK (filled key_levels)' if mq_json and mq_json.get('key_levels') else 'absent/empty'}, "
            f"VIX={len(vix_df)} rows"
        )

        # Build chronological bar timeline (union across symbols)
        # FIX BUG us/ns : helper _to_int64_ns au lieu de .astype("int64") direct.
        all_ts = set()
        for sym in symbols:
            df_oh = ohlcv_per_sym[sym]
            if not df_oh.empty and "ts_event" in df_oh.columns:
                ts_ns_series = _to_int64_ns(df_oh["ts_event"])
                all_ts.update(ts_ns_series.tolist())
        sorted_ts = sorted(all_ts)
        logger.info(f"  Timeline : {len(sorted_ts)} bar timestamps")
        # Fail-loud : verifier timeline plausible (post-2001 = > 1e18 ns)
        if sorted_ts and sorted_ts[0] < _TS_NS_MIN_GUARD:
            raise AssertionError(
                f"Timeline ts suspect : sorted_ts[0]={sorted_ts[0]} < {_TS_NS_MIN_GUARD} "
                f"(probable cast us->int64 regression)"
            )

        # Build per-symbol indexed dict {ts_ns: row_index} for fast lookup
        sym_ts_idx: dict[str, dict[int, int]] = {}
        for sym in symbols:
            df_oh = ohlcv_per_sym[sym]
            if df_oh.empty:
                sym_ts_idx[sym] = {}
                continue
            ts_arr = _to_int64_ns(df_oh["ts_event"]).values
            sym_ts_idx[sym] = {int(ts): i for i, ts in enumerate(ts_arr)}

        # Iterate chronologically (interleave ES -> NQ -> MGC)
        t_start = time.time()
        for bar_idx, ts_event_ns in enumerate(sorted_ts):
            for sym in symbols:
                row_idx = sym_ts_idx[sym].get(ts_event_ns)
                if row_idx is None:
                    continue  # ce symbole n'a pas de bar a ce ts

                row = ohlcv_per_sym[sym].iloc[row_idx]
                ohlcv_dict = build_ohlcv_dict(row, sym)

                bar_start = ts_event_ns
                bar_end = ts_event_ns + 60_000_000_000
                trades_window = build_trades_window(
                    trades_per_sym[sym], bar_start, bar_end
                )

                # MQ levels : priorite MQ_Lite Hive (as-of join, intraday),
                # fallback MenthorQ JSON daily (broadcast intraday).
                mq_levels = build_mq_levels_from_hive(
                    mq_hive_per_sym[sym], ts_event_ns, sym
                )
                if mq_levels is None:
                    mq_levels = build_mq_levels_from_json(mq_json, sym, cur_date)
                vix_levels = build_vix_at_ts(vix_df, ts_event_ns)

                inputs = {
                    "ohlcv": ohlcv_dict,
                    "trades_df": trades_window,
                    "mq_levels": mq_levels,
                    "vix": vix_levels,
                    "stream_alive": True,  # convention batch
                    "ts_read_ns": ts_event_ns + 60_000_000_000,  # convention batch
                }

                # CHAIN PURE (meme code que live_enricher)
                try:
                    payload, meta = compose_enriched_payload(
                        symbol=sym,
                        state=states[sym],
                        inputs=inputs,
                        log_fn=_batch_log_fn,
                        partner_state_provider=_batch_partner_provider,
                    )
                except Exception as e:
                    logger.exception(f"compose_enriched_payload fail {sym} ts={ts_event_ns}: {e}")
                    stats[sym]["n_fail"] += 1
                    continue

                if meta.get("phase_b_plus_plus_partial"):
                    stats[sym]["n_partial"] += 1
                    eng = meta.get("engine_name")
                    if eng:
                        stats[sym]["fail_by_engine"][eng] += 1
                if meta.get("flag_emit_needed"):
                    stats[sym]["n_data_quality_flag_set"] += 1

                # Write enriched bar (meme writer que live)
                ok = write_enriched_bar(sym, payload)
                if ok:
                    stats[sym]["n_bars"] += 1
                else:
                    stats[sym]["n_fail"] += 1

            # Progress log toutes les 60 bars (1 heure de session)
            if (bar_idx + 1) % 60 == 0:
                elapsed = time.time() - t_start
                rate = (bar_idx + 1) / elapsed if elapsed > 0 else 0
                logger.info(f"  Bar {bar_idx + 1}/{len(sorted_ts)} ({rate:.0f} bars/s)")

        # FIX CRITIQUE 16/05/2026 (Plan agent review) : NE PAS appeler
        # `save_state` en batch ! `save_state` ecrit dans
        # `DATA/LIVE_CACHE/enricher_state/` qui est EXACTEMENT le repertoire du
        # live production (bot V6 paper_trader). Si batch tourne pendant que
        # live tourne (ou sync VPS<->PC), on ECRASE l'etat live -> bot V6
        # peut reboot sur etat batch + perdre rolling buffers actuels.
        # Le `save_state` ne sert qu'au resume mid-run, pas critique pour
        # le run one-shot 8 mois. Si crash : on relance from scratch.
        # Si Jackson veut resume safe : refactor `save_state` pour accepter
        # `state_dir` parametre + utiliser un repertoire isole batch.
        logger.info(f"  Day {date_str} done : {stats}")

        cur_date += timedelta(days=1)

    return stats


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Replay batch enricher historique")
    parser.add_argument(
        "--symbols", nargs="+", default=["ES.c.0", "NQ.c.0", "MGC.v.0"],
        help="Symboles a traiter (default: ES + NQ + MGC)"
    )
    parser.add_argument(
        "--start", required=True,
        help="Date debut YYYY-MM-DD"
    )
    parser.add_argument(
        "--end", required=True,
        help="Date fin YYYY-MM-DD (inclusive)"
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Repertoire output JSONL (default DATA/live_enriched/)"
    )
    parser.add_argument(
        "--state-dir", default=None,
        help="Repertoire state.pkl (default DATA/LIVE_CACHE/_state/)"
    )
    parser.add_argument(
        "--use-pre-refactor", action="store_true",
        help="Utilise live_enricher_v_pre_refactor pour test parite (NOT IMPL)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Reload state.pkl existant (default : fresh state cold)"
    )
    # Plan A Sem 1 (07/06/2026) — Tests parite Sierra vs Databento
    # Setting ENRICHER_SOURCE env var avant import live_enricher_io declenche
    # la branche correspondante (default databento prod). Necessite ensuite
    # un output-dir distinct par source pour pouvoir comparer (sinon ecrase).
    parser.add_argument(
        "--source", choices=["databento", "sierra"], default="databento",
        help="Source data (default databento prod). 'sierra' = SierraLiveReader. "
             "Output-dir distinct recommande (ex: DATA/live_enriched_sierra/) "
             "pour comparer parite vs source databento."
    )

    args = parser.parse_args()

    # Plan A Sem 1 : injection ENRICHER_SOURCE AVANT import live_enricher_io.
    # Le module lit env var en top-level, donc cet ordre est critique
    # (anti silent fallback : si import fait avant set, branche databento appliquee).
    os.environ["ENRICHER_SOURCE"] = args.source
    logger.info(f"ENRICHER_SOURCE = {args.source!r} (Plan A shadow architecture)")

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    output_dir = Path(args.output_dir) if args.output_dir else None
    state_dir = Path(args.state_dir) if args.state_dir else None

    logger.info(f"Replay batch : {args.symbols} {start_date} -> {end_date}")
    t0 = time.time()
    stats = run_replay(
        symbols=args.symbols,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        state_dir=state_dir,
        use_pre_refactor=args.use_pre_refactor,
        fresh_state=not args.resume,
    )
    elapsed = time.time() - t0
    logger.info(f"=== DONE in {elapsed:.1f}s ===")
    # Counter n'est pas JSON-serializable direct, convertir
    stats_serializable = {}
    for sym, s in stats.items():
        s2 = dict(s)
        s2["fail_by_engine"] = dict(s.get("fail_by_engine", {}))
        stats_serializable[sym] = s2
    logger.info(f"Stats : {json.dumps(stats_serializable, indent=2)}")


if __name__ == "__main__":
    main()
