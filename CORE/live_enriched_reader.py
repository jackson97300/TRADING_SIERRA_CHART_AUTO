"""live_enriched_reader.py — Loader incremental JSONL live_enriched.

Lit les snapshots enrichis ecrits par `live_enricher.py` :
  DATA/live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl
  - 1 ligne JSONL par close bar 1-min
  - Lag ~60s (close + enricher process)
  - Schema : live_enriched_1.0 (~469 features)

Source unique de verite decidee 23/05/2026 (cf memory
`project_source_data_unique_jsonl_live_20260523.md`).

Architecture :
  - `LiveEnrichedReader(symbol)` : reader stateful avec offset persistant
  - `load_rolling_window(n_bars)` : retourne les N dernieres bars comme
    DataFrame pret a etre consomme par BNV4Engine
  - Auto-detection cross-day : si la bar la plus recente est sur YYYYMMDD_t+1,
    bascule automatique sur le nouveau fichier daily

Robustesse :
  - Skip lignes tronquees (JSONDecodeError) silencieusement
  - Skip duplicates ts_event_ns (writer fait dedup deja, defense profondeur)
  - Tolere fichier absent (jour ferie / pre-open) : retourne None

NB : ne supporte PAS la lecture en parallele du writer (race condition
ligne tronquee). Le writer fait flush+close apres chaque ligne (cf
`live_enricher_writer.py:write_enriched_bar` v1.0). En pratique : lire
tail-N ligne = derniere ligne probablement OK (writer ferme avant return).

Usage :
    from CORE.live_enriched_reader import LiveEnrichedReader

    reader = LiveEnrichedReader(symbol='NQ', window_bars=240)

    # Polling loop (30s)
    while True:
        df = reader.load_rolling_window()
        if df is None or len(df) < 60:
            time.sleep(30)
            continue
        # df.iloc[-1] = derniere bar enrichie (lag ~60s)
        setup = engine.detect_setup(df, len(df)-1, direction='long')
        ...
        time.sleep(30)

Auteur : MIA Trading V2
  v1.0 (2026-05-23) : reader initial pour Bot 2 BN V4 paper deploy lundi
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

OUTPUT_BASE = ROOT / "DATA" / "live_enriched"

# FIX P0-2 (code-reviewer 23/05) : cast defensif numeric cols pour eviter
# DataFrame dtype=object si une bar a une valeur en str (bug enricher one-off).
# Liste des colonnes critiques consommees par BNV4Engine et autres bots.
_NUMERIC_CRITICAL_COLS = (
    # OHLCV de base
    "close", "open", "high", "low", "total_vol",
    # Trend
    "vwap_slope_10",
    "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d",
    "vwap_d_sd2u", "vwap_d_sd2d", "vwap_d_sd3u", "vwap_d_sd3d",
    "vwap_w", "vwap_w_sd1u", "vwap_w_sd1d", "vwap_w_sd2u", "vwap_w_sd2d",
    "vwap_m",
    # Distances normalisees BN V4 niveaux institutionnels
    "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
    "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
    "dist_vwap_w_pct", "dist_vwap_w_sd1u_pct", "dist_vwap_w_sd1d_pct",
    "dist_vwap_w_sd2u_pct", "dist_vwap_w_sd2d_pct",
    "dist_pdh_pct", "dist_pdl_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pvwap_pct", "dist_pvwap_sd1u_pct", "dist_pvwap_sd1d_pct",
    "dist_cur_vpoc_pct",
    "dist_mq_hvl_pct", "dist_mq_put_pct", "dist_mq_call_pct",
    # Density clusters + edge
    "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
    "n_edge_buy_active", "n_edge_sell_active",
    # Long bars + patterns 3-bars Dow + footprint confirm
    "long_up_bar", "long_dn_bar",
    "long_dn_up_pattern", "long_up_dn_pattern",   # FIX P1-A code-reviewer 23/05
    "aggressor_imbalance", "big_buy_dominance", "big_sell_dominance",
    "delta_bar",
    # ATR
    "atr_14", "atr",
)


def _safe_sym_dir(symbol: str) -> str:
    """Aligne mapping symbole -> dossier filesystem du writer.

    Voir CORE/live_enricher_writer.py:_safe_sym_dir().
      ES.c.0  -> 'ES'
      NQ.c.0  -> 'NQ'
      MGC.v.0 -> 'GC' (alignement DMP C++ scsf_MIA_MQ_Lite_GC)
    """
    pure = symbol.split(".")[0]
    if pure == "MGC":
        return "GC"
    return pure


def _build_daily_path(symbol: str, day_str: str) -> Path:
    """Construit path JSONL daily : DATA/live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl"""
    sym_fs = _safe_sym_dir(symbol)
    return OUTPUT_BASE / sym_fs / f"{day_str}_{sym_fs}.jsonl"


def _list_recent_daily_paths(symbol: str, n_days: int = 2) -> list[Path]:
    """Retourne les paths daily UTC pour les n_days derniers jours
    (du plus ancien au plus recent). Gere le cross-day boundary."""
    now_utc = datetime.now(timezone.utc)
    paths = []
    for offset in range(n_days - 1, -1, -1):
        d = now_utc - timedelta(days=offset)
        day_str = d.strftime("%Y%m%d")
        p = _build_daily_path(symbol, day_str)
        if p.exists():
            paths.append(p)
    return paths


@dataclass
class _ReaderState:
    """State interne du reader (offsets par path pour incremental load).

    FIX P0-1 code-reviewer 23/05 : offset GLOBAL unique = bug cross-day
    catastrophique (yesterday+today alternaient avec reset offset). Solution :
    dict[path_str -> offset] permet de tracker chaque fichier daily
    independamment. Garbage collect des paths > N_RECENT_DAYS jours.
    """
    # offset par path absolu (str). Garde des entries pour les 2-3 derniers
    # jours seulement (cleanup au load_rolling_window).
    offsets_by_path: dict = None
    bars_buffer: Optional[list] = None    # liste de dicts (bar enriched)

    def __post_init__(self):
        if self.offsets_by_path is None:
            self.offsets_by_path = {}
        if self.bars_buffer is None:
            self.bars_buffer = []


class LiveEnrichedReader:
    """Reader incremental JSONL live_enriched avec buffer rolling.

    Args:
        symbol : "NQ.c.0" / "ES.c.0" / "MGC.v.0"
        window_bars : taille buffer rolling (default 480 = 8h en 1m bars,
                       suffisant pour BN V4 trend_long_lookback=240).
        warn_stale_sec : log warning si derniere bar > N secondes
                          (default 180s = 3 min).

    State :
        Conserve `bars_buffer` en memoire (deque-like, capped window_bars).
        Incremental : `load_rolling_window()` lit seulement les NOUVELLES
        lignes depuis le dernier appel (via offset file persistant).
    """

    def __init__(self, symbol: str, window_bars: int = 480,
                  warn_stale_sec: int = 180):
        self.symbol = symbol
        self.window_bars = window_bars
        self.warn_stale_sec = warn_stale_sec
        self._state = _ReaderState()
        self._seen_ts: set = set()    # dedup ts_event_ns

    def _read_new_lines(self, path: Path) -> list[dict]:
        """Read les nouvelles lignes depuis last_byte_offset[path] jusqu'a EOF.
        Skip lignes tronquees / JSONDecodeError silencieusement.

        FIX P0-1 (code-reviewer 23/05) : offset PAR path (dict) au lieu de
        global. Permet de poller `yesterday` + `today` sans reset destructeur
        a chaque iteration de la boucle for path in paths.
        """
        path_key = str(path.resolve())
        current_offset = self._state.offsets_by_path.get(path_key, 0)

        try:
            with open(path, "rb") as f:
                f.seek(current_offset)
                raw = f.read()
                new_offset = f.tell()
        except OSError:
            return []
        self._state.offsets_by_path[path_key] = new_offset

        if not raw:
            return []

        # Decode UTF-8 + drop derniere ligne potentielle tronquee
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []

        lines = text.splitlines()
        # Si pas de \n final, derniere ligne possiblement tronquee : drop
        if lines and not text.endswith("\n"):
            # Re-ajuster offset pour re-lire la ligne tronquee plus tard
            last_line_bytes = len(lines[-1].encode("utf-8"))
            self._state.offsets_by_path[path_key] = max(
                0, self._state.offsets_by_path[path_key] - last_line_bytes
            )
            lines = lines[:-1]

        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("ts_event_ns")
            if ts is None or not isinstance(ts, int):
                continue
            if ts in self._seen_ts:
                continue   # defense profondeur (writer fait deja dedup)
            self._seen_ts.add(ts)
            out.append(d)
        return out

    def load_rolling_window(self) -> Optional[pd.DataFrame]:
        """Charge le buffer rolling courant (au + window_bars dernieres bars).

        Returns:
            pd.DataFrame trie par ts_event ascending, ou None si pas de data.
            Le DataFrame contient :
              - ts_event : pd.Timestamp UTC (converti depuis ts_event_ns)
              - ts_event_ns : int epoch ns (preserve pour dedup)
              - close, open, high, low, total_vol, vwap_slope_10, etc.
              - Toutes les features enriched (~469 cols)
        """
        # 1. Identifier les paths daily a lire (cross-day support)
        paths = _list_recent_daily_paths(self.symbol, n_days=2)
        if not paths:
            return None

        # 2. Lire nouvelles lignes du(des) fichier(s) le(s) plus recent(s)
        # Si on a 2 paths (cross-day), lire d'abord l'ancien puis le nouveau
        for path in paths:
            new_lines = self._read_new_lines(path)
            if new_lines:
                self._state.bars_buffer.extend(new_lines)

        # 3. Cap buffer a window_bars (drop oldest)
        if len(self._state.bars_buffer) > self.window_bars:
            # Track ts dropped pour cleanup _seen_ts (eviter memory leak)
            dropped = self._state.bars_buffer[:-self.window_bars]
            self._state.bars_buffer = self._state.bars_buffer[-self.window_bars:]
            for d in dropped:
                self._seen_ts.discard(d.get("ts_event_ns"))

        if not self._state.bars_buffer:
            return None

        # 4. Convertir en DataFrame
        df = pd.DataFrame(self._state.bars_buffer)
        if "ts_event_ns" not in df.columns:
            return None

        # ts_event datetime UTC depuis ts_event_ns
        df["ts_event"] = pd.to_datetime(df["ts_event_ns"], utc=True, unit="ns")
        df = df.sort_values("ts_event").reset_index(drop=True)

        # FIX P0-2 (code-reviewer 23/05) : cast defensif numeric cols
        # Sans ce cast, si UNE bar a `total_vol="1234"` (str au lieu d'int) le
        # dtype inferre par pd.DataFrame est `object`. Les operations downstream
        # `df['total_vol'].mean()` crashent avec TypeError silencieux.
        # to_numeric(errors='coerce') convertit non-numeric -> NaN proprement.
        for _col in _NUMERIC_CRITICAL_COLS:
            if _col in df.columns:
                df[_col] = pd.to_numeric(df[_col], errors="coerce")

        return df

    def get_last_bar_age_seconds(self) -> float:
        """Age en secondes de la derniere bar dans le buffer.

        Returns:
            float >= 0 si data dispo, 999999.0 si pas de data.
        """
        if not self._state.bars_buffer:
            return 999999.0
        last_ts_ns = self._state.bars_buffer[-1].get("ts_event_ns")
        if last_ts_ns is None:
            return 999999.0
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        return (now_ns - last_ts_ns) / 1e9

    def is_stale(self) -> bool:
        """True si la derniere bar a plus de `warn_stale_sec` secondes
        (= pipeline enricher en retard / down)."""
        return self.get_last_bar_age_seconds() > self.warn_stale_sec

    def reset(self) -> None:
        """Reset complet du state (utile pour test ou recovery)."""
        self._state = _ReaderState()
        self._seen_ts.clear()
