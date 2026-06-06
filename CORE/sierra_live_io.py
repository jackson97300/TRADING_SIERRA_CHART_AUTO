"""sierra_live_io.py - Loader incremental JSONL Sierra DMP direct.

Lit les snapshots Sierra DMP ecrits par DMP_Main.cpp (Sierra Chart ACSIL C++) :
  DATA/{SYM}/{YYYYMMDD}_{SYM}.jsonl
  - 1 ligne JSONL par close bar 1-min
  - Lag ~5-10s (Sierra Chart close bar + DMP_Writer flush)
  - Schema : 3.7.14 (268 features) / 3.7.15+ (272) / 3.7.18 (309 +37 _pct Batch B1)
             / 3.7.19 (339 +30 niveaux absolus Sierra Batch B2)

PURPOSE :
  Source de verite UNIQUE pour migration full Sierra (06/06/2026, cf
  DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md).
  Remplace `databento_live_stream.py` (convention delta_bar inverse bugged,
  cf INCIDENT_LOG entry 37 du 2026-06-06).
  Sierra natif a convention saine : delta_bar = AskVolume - BidVolume.

ARCHITECTURE (heritage `LiveEnrichedReader` pattern, eprouve depuis 23/05/2026) :
  - SierraLiveReader(symbol) stateful avec offset persistant par path
  - load_rolling_window(n_bars) charge buffer rolling incremental
  - Auto-detection cross-day boundary (00:00 UTC)
  - Schema versioning detection via meta block (3.7.14 vs 3.7.15+)
  - Fail-loud sur fichier absent (anti silent fallback, cf rule data-quality.md)
  - Whitelist 87+4 features stables (cf Phase 1.2)
  - Skip lignes tronquees JSONDecodeError silencieusement (defense profondeur)
  - Dedup ts_event_ns (DMP fait deja dedup au write, defense profondeur)

USAGE :
    from CORE.sierra_live_io import SierraLiveReader

    reader = SierraLiveReader(symbol='NQ', window_bars=480)

    # Polling loop (recommande 10s, lag Sierra ~5-10s)
    while True:
        df = reader.load_rolling_window()
        if df is None or len(df) < 60:
            time.sleep(10)
            continue
        # df.iloc[-1] = derniere bar Sierra (lag ~5-10s)
        # 268 features Sierra natives + ts_event datetime UTC
        ...
        time.sleep(10)

NB : tail-N derniere ligne probablement OK car DMP_Writer.h flush+close apres
chaque ligne (cf DMP_Writer.h dans CPP/MIA_REFACTORED/DUMPER/). En pratique :
race condition negligeable.

Symboles supportes V1 : ES, NQ (DMP dump uniquement ces 2 sur VPS).
MGC en backlog Phase 8+ (Bot 4 SAFE COLLECT sur Sim4 hors scope V1).

Auteur : MIA Trading V2 (migration Sierra)
  v1.0 (2026-06-06) : initial Phase 1.1 migration full Sierra
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Sierra DMP dump base : DATA/{SYM}/YYYYMMDD_{SYM}.jsonl
DMP_BASE = ROOT / "DATA"

# Symboles supportes V1 (cf VPS check 2026-06-06 : seuls ES + NQ dumpes)
SUPPORTED_SYMBOLS = ("ES", "NQ")

# Schemas Sierra DMP attendus (cf DMP_Config.h)
# NB : 3.7.16 reverte le 06/06 nuit (cf DMP_Config.h). On le garde dans la
# whitelist au cas ou un JSONL pre-revert ait ete dumpe.
ACCEPTED_SCHEMAS = ("3.7.14", "3.7.15", "3.7.16", "3.7.17", "3.7.18", "3.7.19")
# 3.7.17 = CLAMP ATR aligne (2026-06-07, comportemental, 272 cols inchangees)
# 3.7.18 = Batch B1 F3 Distances _pct (309 cols = 272 + 37)
# 3.7.19 = Batch B2 Niveaux ABSOLUS Sierra (339 cols = 309 + 30 : 16 VWAP +
#          8 Prev/Cash/Open/OVN + 6 VP). Decision Jackson 2026-06-07 :
#          Sierra prime sur 3 familles (VWAP/VP/Session) prop firms RTH-only.

# Fail-loud par defaut : raise si fichier absent (anti silent fallback).
# Override avec strict=False pour tests offline.
DEFAULT_STRICT = True

# FIX R3 (code-reviewer 06/06) : n_days=2 insuffisant en week-end / pre-open.
# Verification empirique 06/06 (samedi) : dernier fichier NQ = 20260603 (mercredi),
# 3 jours avant. n_days=4 couvre week-end (vendredi soir -> lundi matin) + holidays
# courts. Au-dela : Jackson doit lancer un backfill explicite.
DEFAULT_N_DAYS_LOOKBACK = 4

# FIX B2 (code-reviewer 06/06) : assertion `ts` plage milliseconds.
# Sierra DMP ecrit `ts` en millisecondes epoch UTC depuis schema 3.7.x.
# Si futur schema bascule en nanosecondes par megarde, silent fallback
# = anti-pattern identique au bug delta_bar Databento qui a motive cette
# migration. Plage ms valide 2001..5138 = 1e12..1e14.
TS_MS_MIN = 10**12  # ~2001-09-09 (sentinel paranoia)
TS_MS_MAX = 10**14  # ~5138-11-16 (sentinel paranoia)

# FIX P0-2 (heritage code-reviewer 23/05 LiveEnrichedReader) : cast defensif
# numeric cols pour eviter DataFrame dtype=object si une bar a une valeur
# en str (bug DMP one-off). Liste des colonnes critiques consommees par bots
# (delta_bar, cvd_day, ATR, distances normalisees, signe direction).
_NUMERIC_CRITICAL_COLS = (
    # OHLCV de base Sierra
    "price", "bar_high", "bar_low",
    # ATR (Sierra a deux : atr daily + atr_14m intraday)
    "atr", "atr_14m",
    # Delta / Aggressor (convention SAINE Sierra - critique migration)
    "delta_bar", "delta_bar_vol_norm", "delta_day", "delta_day_dir",
    "cvd_day", "cvd_day_dir", "cvd_ohlc_range",
    "ask_pct", "bid_pct", "ask_bid_imbalance", "delta_pct",
    "buy_vol", "sell_vol", "buy_sell_ratio", "total_vol",
    "avg_trade_size", "avg_bid_size", "avg_ask_size",
    "large_trader_ratio", "vol_per_sec", "bar_duration_sec",
    "diag_pos_delta", "diag_neg_delta", "diag_imbalance",
    "finish_strength", "finish_delta_pct",
    "high_pullback_delta", "low_pullback_delta",
    "ticks_count", "poc_bar_dist",
    # VWAP D/W/M + SD bands + slopes
    "dist_vwap_d", "dist_vwap_d_atr",
    "dist_vwap_d_sd1u", "dist_vwap_d_sd1d", "dist_vwap_d_sd2u",
    "dist_vwap_d_sd2d", "dist_vwap_d_sd3u", "dist_vwap_d_sd3d",
    "dist_vwap_w", "dist_vwap_w_atr",
    "dist_vwap_m", "dist_vwap_m_atr",
    "vwap_d_side", "vwap_w_side", "vwap_m_side",
    "vwap_slope_10", "vwap_slope_30", "vwap_slope_10_dir",
    # Volume Profile current / prev / composite
    "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",
    "dist_prev_vpoc", "dist_prev_vah", "dist_prev_val",
    "va_position_pct", "range_pos", "range_size_ticks",
    # Session/IB
    "dist_sess_high", "dist_sess_low", "sess_range_ticks", "sess_range_atr",
    "dist_ib_high", "dist_ib_low", "ib_range_ticks", "ib_range_atr",
    "ib_position_pct",
    # Niveaux veille / opens
    "dist_open_cash", "dist_open_830", "open_gap_ticks",
    # MenthorQ levels (saintes 17/04 cf changelog 3.7.x)
    "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
    "dist_mq_call_0dte", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
    "dist_gex_nearest_up", "dist_gex_nearest_dn",
    "next_wall_dist_ticks",
    # VIX
    "vix_level", "dist_vix_hvl",
    "dist_vix_call", "dist_vix_put",
    "dist_vix_call_0dte", "dist_vix_put_0dte", "dist_vix_hvl_0dte",
    # Swings Wyckoff base
    "dist_swing_high", "dist_swing_low", "swing_range_ticks",
    "price_vs_swing_mid",
    # Game Changers Dalton (Sierra GAGNE vs Databento)
    "open_type", "day_type", "profile_shape", "open_bias_conf",
    "open_direction", "profile_skew", "poc_position",
    "volume_imbalance", "is_double_dist",
    # HVN/LVN session
    "dist_session_hvn_above", "dist_session_hvn_below",
    "dist_session_lvn_above", "dist_session_lvn_below",
    # Big orders + clusters
    "dist_big_ask_nearest_up", "dist_big_ask_nearest_dn",
    "dist_big_bid_nearest_up", "dist_big_bid_nearest_dn",
    "dist_cluster_nearest_up", "dist_cluster_nearest_dn",
    "n_clusters_20t", "n_clusters_50t",
    # 4 features ajoutees Phase 0.7 (schema 3.7.15+, tolerees missing en 3.7.14)
    "max_ask_vol_in_bar", "max_bid_vol_in_bar",
    "p99_trade_size_proxy", "large_trader_max_size",
)


# ──────────────────────────────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────────────────────────────


def _validate_symbol(symbol: str) -> str:
    """Valide le symbole et retourne forme canonique pour path filesystem.

    Sierra DMP V1 supporte uniquement ES et NQ (cf VPS check 2026-06-06).
    MGC en backlog Phase 8+ (Bot 4 hors scope).

    Raises:
        ValueError si symbole non supporte.
    """
    pure = symbol.split(".")[0].upper()
    if pure not in SUPPORTED_SYMBOLS:
        raise ValueError(
            f"Symbole non supporte par Sierra DMP V1 : {symbol!r}. "
            f"Symboles autorises : {SUPPORTED_SYMBOLS}. "
            f"MGC en backlog Phase 8+."
        )
    return pure


def _build_daily_path(symbol_fs: str, day_str: str) -> Path:
    """Construit path JSONL daily : DATA/{SYM}/{YYYYMMDD}_{SYM}.jsonl"""
    return DMP_BASE / symbol_fs / f"{day_str}_{symbol_fs}.jsonl"


def _build_meta_path(symbol_fs: str, day_str: str) -> Path:
    """Construit path meta JSON daily : DATA/{SYM}/{YYYYMMDD}_{SYM}.meta.json

    Fix B1 (code-reviewer 06/06) : Sierra DMP ecrit `schema_version` et
    `n_columns` dans `.meta.json` SEPARE, jamais dans les bars JSONL.
    Sans ce fix, la detection schema dans `_read_new_lines` reste None
    en prod (silent fallback).
    """
    return DMP_BASE / symbol_fs / f"{day_str}_{symbol_fs}.meta.json"


def _list_recent_daily_paths(symbol_fs: str,
                              n_days: int = DEFAULT_N_DAYS_LOOKBACK) -> list[Path]:
    """Retourne les paths daily UTC pour les n_days derniers jours
    (ordre chronologique ascending : ancien -> recent). Gere cross-day
    boundary + week-end / pre-open (n_days=4 default fix R3).

    Args:
        n_days : nombre de jours UTC a chercher en remontant depuis maintenant.
                 Default 4 couvre week-end (vendredi -> lundi). Si holiday
                 long (Noel 24-26), passer n_days=7+ explicitement.
    """
    now_utc = datetime.now(timezone.utc)
    paths = []
    for offset in range(n_days - 1, -1, -1):
        d = now_utc - timedelta(days=offset)
        day_str = d.strftime("%Y%m%d")
        p = _build_daily_path(symbol_fs, day_str)
        if p.exists():
            paths.append(p)
    return paths


def _read_meta_schema(symbol_fs: str, day_str: str) -> Optional[str]:
    """Lit `schema_version` depuis le `.meta.json` separe Sierra DMP.

    Fix B1 (code-reviewer 06/06) : Sierra DMP ecrit le schema_version
    UNIQUEMENT dans le `.meta.json`, pas dans les bars individuelles.
    Cette fonction lit le meta au premier appel par day. Si meta absent
    ou parse echec : retourne None (skip detection silencieux, NON
    fail-loud car certains anciens meta JSON peuvent etre incomplets).

    Returns:
        str ('3.7.14' / '3.7.15') si trouve dans le meta, None sinon.

    Raises:
        ValueError si schema_version trouve mais hors ACCEPTED_SCHEMAS
        (fail-loud anti silent desync).
    """
    meta_fp = _build_meta_path(symbol_fs, day_str)
    if not meta_fp.exists():
        return None
    try:
        with open(meta_fp, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    schema = meta.get("schema_version")
    if schema is None:
        return None
    if schema not in ACCEPTED_SCHEMAS:
        raise ValueError(
            f"Schema Sierra DMP non reconnu : {schema!r} "
            f"(dans {meta_fp.name}). Schemas autorises : {ACCEPTED_SCHEMAS}. "
            f"Verifier DMP_Config.h DMP_SCHEMA_VERSION."
        )
    return schema


# ──────────────────────────────────────────────────────────────────────
# Internal state
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _ReaderState:
    """State interne du reader (offsets par path pour incremental load).

    Pattern eprouve LiveEnrichedReader v1.0 (23/05) fix P0-1 code-reviewer :
    offset GLOBAL unique = bug cross-day catastrophique (yesterday+today
    alternaient avec reset offset). Solution : dict[path_str -> offset]
    permet de tracker chaque fichier daily independamment. Garbage collect
    des paths > N_RECENT_DAYS jours au load_rolling_window.
    """
    offsets_by_path: dict = field(default_factory=dict)
    bars_buffer: list = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Schema detection
# ──────────────────────────────────────────────────────────────────────


def _detect_schema_version(bar: dict) -> Optional[str]:
    """Detecte schema_version Sierra DMP depuis bar.

    Le DMP_Writer.h ecrit un champ meta `schema_version` dans certaines
    bars (typiquement la premiere de chaque jour ou periodiquement).
    Fail-loud si schema non reconnu : abort migration plutot que silent
    desync (cf incident bug arr_sz_1 systemique 15/04 - feedback memo).

    Returns:
        str ('3.7.14' / '3.7.15') si trouve, None sinon (silently OK).
    """
    schema = bar.get("schema_version") or bar.get("meta", {}).get("schema_version")
    if schema is None:
        return None
    if schema not in ACCEPTED_SCHEMAS:
        raise ValueError(
            f"Schema Sierra DMP non reconnu : {schema!r}. "
            f"Schemas autorises : {ACCEPTED_SCHEMAS}. "
            f"Verifier DMP_Config.h DMP_SCHEMA_VERSION."
        )
    return schema


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


class SierraLiveReader:
    """Reader incremental JSONL Sierra DMP direct avec buffer rolling.

    Args:
        symbol : "ES" ou "NQ" (V1 ; MGC en backlog Phase 8+).
        window_bars : taille buffer rolling (default 480 = 8h en 1m bars).
                       Suffit pour BN V4 trend_long_lookback=240.
        strict : si True (default), raise si fichier absent (fail-loud).
                  Si False, retourne None (mode test offline).

    State :
        Conserve `bars_buffer` en memoire (deque-like, capped window_bars).
        Incremental : `load_rolling_window()` lit seulement les NOUVELLES
        lignes depuis le dernier appel (via offset file persistant par path).

    Exemple :
        reader = SierraLiveReader(symbol='NQ', window_bars=480)
        while True:
            df = reader.load_rolling_window()
            if df is None or len(df) < 60:
                time.sleep(10); continue
            # df.iloc[-1] = derniere bar Sierra (~5-10s lag, 268 features)
            ...
            time.sleep(10)
    """

    def __init__(self, symbol: str, window_bars: int = 480,
                  strict: bool = DEFAULT_STRICT,
                  n_days_lookback: int = DEFAULT_N_DAYS_LOOKBACK):
        # Fix R4 code-reviewer 06/06 : assertion window_bars suffisant
        # pour les bots downstream (BN V4 trend_long_lookback=240).
        if window_bars < 240:
            raise ValueError(
                f"window_bars={window_bars} < 240. BN V4 (trend_long_lookback)"
                f" et Bot 3 V4 ont besoin de >= 240 bars de contexte."
            )
        self.symbol_fs = _validate_symbol(symbol)
        self.symbol = self.symbol_fs    # alias public
        self.window_bars = window_bars
        self.strict = strict
        self.n_days_lookback = n_days_lookback
        self._state = _ReaderState()
        self._seen_ts: set = set()
        self._last_known_schema: Optional[str] = None
        # Fix B1 code-reviewer 06/06 : cache schema par day_str (lit meta.json
        # une fois par day pour eviter I/O repete).
        self._schema_by_day: dict[str, Optional[str]] = {}

    def _read_new_lines(self, path: Path) -> list[dict]:
        """Read les nouvelles lignes depuis last_byte_offset[path] jusqu'a EOF.

        Skip lignes tronquees / JSONDecodeError silencieusement (defense
        profondeur, DMP fait deja flush+close per ligne).

        Pattern eprouve LiveEnrichedReader fix P0-1 code-reviewer 23/05.
        Fix B1+B2 code-reviewer 06/06 : detection schema via .meta.json
        + assertion ts en ms.
        """
        # Fix B1 : detection schema via .meta.json SEPARE (Sierra DMP n'ecrit
        # pas schema_version dans les bars JSONL). Cache par day_str.
        day_str = path.stem.split("_")[0]    # extrait YYYYMMDD depuis YYYYMMDD_NQ
        if day_str not in self._schema_by_day:
            self._schema_by_day[day_str] = _read_meta_schema(self.symbol_fs, day_str)
            if self._schema_by_day[day_str] is not None:
                self._last_known_schema = self._schema_by_day[day_str]

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

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []

        lines = text.splitlines()
        # Pas de \n final = derniere ligne probablement tronquee : on re-ajuste
        # l'offset pour la re-lire au prochain poll quand elle sera complete.
        if lines and not text.endswith("\n"):
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

            # Detect schema dans la bar elle-meme (fallback B1 : certaines
            # versions futures pourraient l'inclure). Si trouve : update.
            try:
                schema = _detect_schema_version(d)
            except ValueError:
                # Fail-loud propagation si schema bar non reconnu
                raise
            if schema is not None:
                self._last_known_schema = schema

            # Dedup `ts` (Sierra DMP utilise `ts` en millisecondes epoch
            # depuis schema 3.7.x ; pas `ts_event_ns` comme Databento).
            # Cf inspection bar 20260603 : ts=1780437660000 ms (13 chiffres).
            ts = d.get("ts")
            if ts is None or not isinstance(ts, (int, float)):
                continue
            ts_int = int(ts)
            # Fix B2 code-reviewer 06/06 : assertion plage ms anti silent
            # fallback. Si Sierra bascule en ns ou autre unit -> fail-loud.
            if not (TS_MS_MIN <= ts_int < TS_MS_MAX):
                raise ValueError(
                    f"`ts` hors plage millisecondes attendue : {ts_int}. "
                    f"Sierra DMP expose `ts` en ms epoch UTC depuis schema "
                    f"3.7.x. Plage valide : [{TS_MS_MIN}, {TS_MS_MAX}). "
                    f"Anti silent fallback (cf bug delta_bar Databento)."
                )
            if ts_int in self._seen_ts:
                continue
            self._seen_ts.add(ts_int)
            out.append(d)
        return out

    def load_rolling_window(self) -> Optional[pd.DataFrame]:
        """Charge le buffer rolling courant (au plus window_bars dernieres bars).

        Returns:
            pd.DataFrame trie par ts_event ascending, ou None si pas de data.
            Contient :
              - ts_event : pd.Timestamp UTC (converti depuis ts_event_ns)
              - ts_event_ns : int epoch ns (preserve pour dedup)
              - 268 features Sierra DMP natives (3.7.14)
              - + 4 features ajoutees Phase 0.7 (3.7.15+) si schema bumpe

        Raises:
            FileNotFoundError si strict=True et aucun fichier daily trouve
            pour les 2 derniers jours UTC.
            ValueError si schema_version trouve dans une bar mais non reconnu.
        """
        paths = _list_recent_daily_paths(self.symbol_fs,
                                          n_days=self.n_days_lookback)
        if not paths:
            if self.strict:
                raise FileNotFoundError(
                    f"Sierra DMP JSONL absent pour {self.symbol_fs} sur "
                    f"les {self.n_days_lookback} derniers jours. Verifier "
                    f"que Sierra Chart + DMP tournent sur VPS "
                    f"(DATA/{self.symbol_fs}/YYYYMMDD_{self.symbol_fs}"
                    f".jsonl). Mode strict={self.strict}."
                )
            return None

        for path in paths:
            new_lines = self._read_new_lines(path)
            if new_lines:
                self._state.bars_buffer.extend(new_lines)

        # Cap buffer (drop oldest, cleanup _seen_ts)
        if len(self._state.bars_buffer) > self.window_bars:
            dropped = self._state.bars_buffer[:-self.window_bars]
            self._state.bars_buffer = self._state.bars_buffer[-self.window_bars:]
            for d in dropped:
                ts_v = d.get("ts")
                if ts_v is not None:
                    self._seen_ts.discard(int(ts_v))

        if not self._state.bars_buffer:
            return None

        df = pd.DataFrame(self._state.bars_buffer)
        if "ts" not in df.columns:
            return None

        # Sierra DMP `ts` est en millisecondes epoch UTC. Conversion UTC datetime.
        df["ts_event"] = pd.to_datetime(df["ts"], utc=True, unit="ms")
        df = df.sort_values("ts_event").reset_index(drop=True)

        # Cast defensif numeric cols (pattern P0-2 LiveEnrichedReader 23/05)
        for col in _NUMERIC_CRITICAL_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    def get_last_bar_age_seconds(self) -> float:
        """Age en secondes de la derniere bar dans le buffer.

        Returns:
            >= 0 si data dispo, 999999.0 si pas de data.
        """
        if not self._state.bars_buffer:
            return 999999.0
        last_ts = self._state.bars_buffer[-1].get("ts")
        if last_ts is None:
            return 999999.0
        # Sierra DMP `ts` est en millisecondes epoch
        last_dt = datetime.fromtimestamp(int(last_ts) / 1000.0, tz=timezone.utc)
        return (datetime.now(timezone.utc) - last_dt).total_seconds()

    def get_schema_version(self) -> Optional[str]:
        """Retourne le dernier schema_version detecte (3.7.14 ou 3.7.15)."""
        return self._last_known_schema

    def get_buffer_size(self) -> int:
        """Nombre de bars dans le buffer rolling courant."""
        return len(self._state.bars_buffer)


__all__ = ("SierraLiveReader", "SUPPORTED_SYMBOLS", "ACCEPTED_SCHEMAS")
