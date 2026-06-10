"""bot3_v3_sierra_reader.py - Wrapper SierraLiveReader produisant format LiveEnrichedReader.

CONTEXTE STRATEGIQUE
====================
Architecture 100% Sierra a long terme (decision Jackson 2026-06-07).
Bot 3 v3 Continuation NQ Sim1 (Wyckoff continuation) doit consommer directement
Sierra DMP JSONL au lieu de `live_enriched` (lag 60s + bug delta_bar Databento
INCIDENT_LOG entry 37).

================================================================================
WARNINGS SEMANTIQUES (Fix Review #1 — 2026-06-07)
================================================================================

R2 — `bar["atr"]` est en TICKS (heritage Sierra DMP)
----------------------------------------------------
Le champ `atr` est en TICKS (cf `DMP_Transform.h:880-882` + `:1845` :
`r.atr_daily` est deja en TICKS apres fix 2026-04-15).

⚠️ NE PAS UTILISER `bar["atr"]` POUR CALCULER SL/TP en POINTS.

Incident 27/05/2026 — Plan C SL hybride ATR-based (rollback) :
le code prod faisait `atr_pts = row["atr"]` en croyant lire des POINTS
alors que la valeur etait en TICKS → SL calcule ~4x trop petit → edge
prouve backtest annule mecaniquement.
Reference : `.claude/rules/critical-tasks-review.md` regle SIZING/SL/TP
DEPLOY (lignes 137-179).

Le wrapper expose DEUX cles explicites pour eviter le piege :
  * `bar["atr_ticks"]`  = ATR en TICKS (= `bar["atr"]`, alias semantique)
  * `bar["atr_pts"]`    = ATR en POINTS (= `atr_ticks * tick_size`)

Consumers SL/TP DOIVENT utiliser `bar["atr_ticks"]` OU `bar["atr_pts"]`
de facon explicite. `bar["atr"]` est preserve en TICKS uniquement pour
compat retrocompatible avec le format LiveEnrichedReader natif.

R3 — `load_rolling_window()` : seul `df.iloc[-1]` est garanti coherent
---------------------------------------------------------------------
Le state buffer Phase B+ (`prev_open/high/low/close`, `close_buffer`,
`asia_high/low`, `cash_high/low`) est RESET a chaque appel de
`load_rolling_window()` puis re-construit en re-jouant TOUT le buffer
rolling Sierra (qq centaines de bars).

Consequence : si le buffer Sierra glisse entre 2 polls (Poll 1 = bars
T0..T479, Poll 2 = bars T1..T480), la bar T1 a `prev_bar=bar_T0` en
Poll 1 mais `prev_bar=None` en Poll 2 (premiere bar du buffer Poll 2).
Donc `long_up_bar` / `long_dn_bar` / `ctx_price_slope_5` / niveaux
session peuvent VARIER cross-poll pour les bars intermediaires.

✅ Seule `df.iloc[-1]` est garantie deterministe cross-poll (les
N-1 / N-2 dernieres bars du buffer convergent vers leur valeur "vraie"
puisque leur prev_bar est presente).

Bot 3 v3 engine ne consomme que `df.iloc[-1]` (cf
`bot3_v3_continuation_paper.py:271`) — comportement actuel OK.

Le seul nom canonique a utiliser dans le code engine est
`load_rolling_window_tail_only()` (renommee 2026-06-07 R3 fix).
`load_rolling_window()` est un ALIAS retro-compat qui appelle la meme
methode (Bot 3 v3 paper n'a pas besoin d'etre modifie).

Dette technique R3 (incremental offset propre) : cf
`DOCS/IDEAS_BACKLOG.md` — backlog Sierra wrapper.
================================================================================

Ce module wrap `SierraLiveReader` (`CORE/sierra_live_io.py`, schema 3.7.22,
380 colonnes) et post-process chaque bar pour produire un payload de format
identique a `LiveEnrichedReader` (`CORE/live_enriched_reader.py`), de sorte
que Bot 3 v3 paper (`bot3_v3_continuation_paper.py`) consomme ce wrapper SANS
modification de l'engine.

41 FEATURES PRODUITES
=====================
- 24 NATIVES Sierra : renames triviaux post-3.7.22 (`price`->`close`,
  `bar_high`->`high`, `ts ms`->`ts_event_ns`, 17 distances `_pct` Batch B1, etc.)
- 3 RECONSTRUCTIBLES : `_last_swing_low_price` / `_last_swing_high_price`
  (depuis `dist_swing_*` + tick_size, convention positif=au-dessus confirmee
  ligne 801 DMP_Transform.h), `dist_pvwap_pct` (depuis `dist_prev_vwap` ticks),
  `session_date_trading` (derive `ts_event`).
- 14 PHASE B+ PYTHON PORT :
    long_up_bar / long_dn_bar : threshold per-symbole (NQ=24t, ES=12t, MGC=50t)
        formule : O > prev_close AND H > prev_low + threshold (LONG UP).
    n_long_up_cluster_within_0_2pct / n_long_dn_cluster_within_0_2pct :
        DROP (toujours 0). Engine fait `if long_bar_ok OR cluster_ok`
        (bot3_v3_continuation_engine.py:664) donc DROP cluster = engine se
        rabat sur long_bar seul. Alternative future = porter
        `ExtensionLineBuffer` simplifie (backlog R2).
    ctx_price_slope_5 : np.polyfit deg=1 sur 5 derniers close, return 0.0
        pendant warmup (Bot 3 v3 tolere 0.0 sans veto fail-closed).
    dist_asia_high_pct / dist_asia_low_pct : cummax/cummin sur bar_high/bar_low
        pendant session Asia, reset au rollover trading_day.
    dist_cash_high_pct / dist_cash_low_pct : idem mais sur fenetre RTH 09:30-16:00
        ET via flag natif `is_in_us_cash` (Batch B3.A, DST handled C++).
    dist_ib_low_pct / dist_ib_high_pct : conversion `dist_ib_*` ticks->pct via
        tick_size / close * 100. None si hors fenetre IB (preserve).
    regime_mode : empty string (Bot 3 v3 utilise UNIQUEMENT pour logging,
        cf bot3_v3_continuation_paper.py:271).

CONVENTIONS HERITEES
====================
- LiveEnrichedReader interface : `last_bar()` retourne dict OR None,
  `load_rolling_window()` retourne pd.DataFrame OR None.
  Note : LiveEnrichedReader original n'expose pas `last_bar()` direct
  (cf live_enriched_reader.py) - on l'ajoute ici (Bot 3 v3 utilise
  `df.iloc[-1]` apres `load_rolling_window`).
- FAIL-CLOSED si Sierra bar manque un champ requis : log warning + None.
- Format payload identique au format LiveEnrichedReader (cf
  `bot3_v3_continuation_paper.py:_extract_ts_iso/_extract_day`).
- Cast numerique defensif heritage P0-2 (LiveEnrichedReader 23/05).

Usage :
    from CORE.bot3_v3_sierra_reader import Bot3V3SierraReader

    reader = Bot3V3SierraReader(symbol="NQ", window_bars=480)
    while True:
        df = reader.load_rolling_window()
        if df is None or len(df) < 5:
            time.sleep(10); continue
        # df.iloc[-1] = derniere bar Sierra post-process (lag 5-10s).
        # 41 features Bot 3 v3 prets a etre consommees par engine.
        ...
        time.sleep(10)

Auteur : MIA Trading V2 - migration Sierra Bot 3 v3
    v1.0 (2026-06-07) : initial wrapper Phase 1 cutover Sierra.
"""
from __future__ import annotations

import logging
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Heritage : on wrap SierraLiveReader (schema 3.7.22)
try:
    from CORE.sierra_live_io import SierraLiveReader
except ImportError:
    from sierra_live_io import SierraLiveReader  # type: ignore

# Tick size centralise (cf .claude/rules/tick-size-policy.md - source de verite unique)
try:
    from CORE.constants import get_tick_size
except ImportError:
    from constants import get_tick_size  # type: ignore


__version__ = "1.0.0"

_logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Constantes
# ────────────────────────────────────────────────────────────────────────────

# Threshold per-symbole LONG bar (Phase B+ original `LONG_BAR_THRESHOLD_TICKS`).
# Cf `phase_b_plus_engine.py` (NQ=24t soit 6pts, ES=12t soit 3pts).
#
# ⚠️ R1 FIX (2026-06-07) : MGC volontairement EXCLU.
# `SierraLiveReader.SUPPORTED_SYMBOLS = ("ES", "NQ")` (cf sierra_live_io.py:71).
# Tant que SierraLiveReader ne supporte pas MGC, exposer MGC ici creait
# une silent inconsistency (validation Bot3V3SierraReader passe, instanciation
# SierraLiveReader crash avec message trompeur). Cf review #1 R1.
# MGC reviendra ici quand toute la chain Sierra DMP supportera MGC
# (DMP_Config.h, SierraLiveReader, etc.) — backlog Phase 8+ Bot 4 SAFE COLLECT.
THRESHOLD_TICKS_LONG_BAR: Dict[str, int] = {
    "NQ": 24,
    "ES": 12,
}

# Threshold MGC reference (PAS active tant que SierraLiveReader ne supporte
# pas MGC). Documentation only — ne pas reintroduire dans
# THRESHOLD_TICKS_LONG_BAR sans valider la chain Sierra entiere.
_THRESHOLD_TICKS_LONG_BAR_BACKLOG: Dict[str, int] = {
    "MGC": 50,  # backlog Phase 8+ — voir review #1 R1
}

# Fenetre rolling pour ctx_price_slope_5 (5 close consecutifs).
SLOPE_WINDOW: int = 5

# Cluster pct (DROP : on conserve la constante pour reference future si on
# porte ExtensionLineBuffer simplifie. Pour l'instant, clusters = 0).
CLUSTER_PCT: float = 0.2

# Sessions Sierra DMP exposees via session_id string : "Asia" / "London" / "US"
# (cf DMP_Writer.h:928-934).
SESSION_ASIA = "Asia"

# Rollover CME settlement : 17:00 ET = 21:00/22:00 UTC selon DST. Convention
# Sierra DMP : `session_id == "Asia"` couvre approximativement la nuit Asia
# (commence apres CME settlement). Pour le rollover trading_day, on utilise
# l'heure du ts_event en UTC : si l'heure UTC >= 22h, on est sur le jour
# CME suivant. Approximation suffisante (DST ne bouge pas la cassure de plus
# de 1h). Cf .claude/rules/critical-tasks-review.md regle session.
TRADING_DAY_ROLLOVER_UTC_HOUR: int = 22

# Conversion ms epoch -> ns epoch (ts_event_ns interne attendue par engine).
MS_TO_NS: int = 1_000_000

# Liste features critiques (alignee _NUMERIC_CRITICAL_COLS LiveEnrichedReader
# 23/05 P0-2 + tous champs consommes par bot3_v3_continuation_engine.py).
_NUMERIC_CRITICAL_COLS = (
    # OHLCV
    "close", "open", "high", "low", "total_vol",
    # ATR (Bot 3 v3 lit `atr` cf engine ligne 901 +1026 — ATTENTION TICKS).
    # R2 FIX (2026-06-07) : atr_ticks et atr_pts exposes explicitement.
    "atr", "atr_ticks", "atr_pts", "atr_14m",
    # VWAP slope (engine veto L1 vwap_slope_10 + L2 divergence)
    "vwap_slope_10", "vwap_slope_30",
    # Distances normalisees consommees par level_defs (cf lignes 274-296 engine)
    "dist_1d_min_ticks_pct", "dist_mq_put_pct", "dist_mq_put_0dte_pct",
    "dist_mq_hvl_pct", "dist_cur_val_pct", "dist_cur_vpoc_pct",
    "dist_prev_val_pct", "dist_pvwap_pct", "dist_vwap_d_pct",
    "dist_gex_nearest_dn_pct", "dist_cash_low_pct", "dist_asia_low_pct",
    "dist_ib_low_pct",
    "dist_1d_max_ticks_pct", "dist_mq_call_pct", "dist_mq_call_0dte_pct",
    "dist_cur_vah_pct", "dist_prev_vah_pct", "dist_gex_nearest_up_pct",
    "dist_ib_high_pct", "dist_cash_high_pct", "dist_asia_high_pct",
    # Phase B+ LONG BAR ports
    "long_up_bar", "long_dn_bar",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
    # Reconstructions swing
    "_last_swing_low_price", "_last_swing_high_price",
    "dist_swing_high", "dist_swing_low",
    # Veto L2 slope_5
    "ctx_price_slope_5",
    # News (natif Sierra Batch B3.A)
    "mins_since_news", "mins_to_next_news",
)


# ────────────────────────────────────────────────────────────────────────────
# State streaming wrapper
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class _WrapperState:
    """Etat streaming pour calcul des features Phase B+ et niveaux session.

    Persistant entre appels `last_bar()` / `load_rolling_window()`.
    Reset partiel au rollover trading_day.
    """
    # Phase B+ long bar : prev bar pour formule long_up/dn
    prev_open: Optional[float] = None
    prev_high: Optional[float] = None
    prev_low: Optional[float] = None
    prev_close: Optional[float] = None

    # ctx_price_slope_5 : 5 derniers close
    close_buffer: Deque[float] = field(default_factory=lambda: deque(maxlen=SLOPE_WINDOW))

    # Trading day rollover + niveaux session
    trading_day: Optional[str] = None  # "YYYYMMDD"
    asia_high: Optional[float] = None
    asia_low: Optional[float] = None
    cash_high: Optional[float] = None
    cash_low: Optional[float] = None

    def reset_day(self, new_trading_day: str) -> None:
        """Reset niveaux session au rollover trading_day. Conserve close_buffer
        + prev_bar (continuite slope_5 et long_bar legitime cross-session)."""
        self.trading_day = new_trading_day
        self.asia_high = None
        self.asia_low = None
        self.cash_high = None
        self.cash_low = None


# ────────────────────────────────────────────────────────────────────────────
# Helpers utilitaires
# ────────────────────────────────────────────────────────────────────────────


def _safe_float(v: Any) -> Optional[float]:
    """Cast defensif. None / non-numerique -> None."""
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _derive_trading_day(ts_event_ns: Optional[int]) -> Optional[str]:
    """Derive trading_day YYYYMMDD depuis ts_event_ns UTC.

    Convention CME : rollover settlement 17:00 ET ~= 22:00 UTC (approx DST).
    Si ts UTC >= 22h, on est sur le jour CME suivant. Sinon meme jour calendrier.

    Returns:
        "YYYYMMDD" str ou None si ts_event_ns invalide.
    """
    if ts_event_ns is None:
        return None
    try:
        dt = datetime.fromtimestamp(int(ts_event_ns) / 1e9, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    if dt.hour >= TRADING_DAY_ROLLOVER_UTC_HOUR:
        dt = dt + timedelta(days=1)
    return dt.strftime("%Y%m%d")


# ────────────────────────────────────────────────────────────────────────────
# Wrapper public
# ────────────────────────────────────────────────────────────────────────────


class Bot3V3SierraReader:
    """Wrapper SierraLiveReader produisant format LiveEnrichedReader.

    Architecture :
        - Wrap `SierraLiveReader` (lag 5-10s Sierra DMP).
        - Maintient `_WrapperState` entre appels (Phase B+ + niveaux session).
        - Transform chaque bar Sierra -> dict format LiveEnrichedReader.
        - `last_bar()` retourne le dict transforme de la derniere bar buffer.
        - `load_rolling_window()` retourne DataFrame TOUTE la fenetre rolling
          transformee (utilise par Bot 3 v3 paper qui fait `df.iloc[-1]`).

    Thread-safety :
        Pas de threading interne. Single-thread consume pattern paper_v2.

    Args:
        symbol : "NQ", "ES" (V1 ; MGC en backlog Phase 8+).
        window_bars : taille buffer rolling Sierra (default 480 = 8h en 1-min).
                       MUST >= 240 (cf SierraLiveReader fix R4 code-reviewer).
        warn_stale_sec : age max bar avant log staleness (default 180s).
        strict : fail-loud si Sierra DMP absent (default True).

    Exemple :
        reader = Bot3V3SierraReader(symbol="NQ")
        while True:
            df = reader.load_rolling_window()
            if df is None or len(df) < 5:
                time.sleep(10); continue
            last = df.iloc[-1]
            # last["close"] / last["long_up_bar"] / last["dist_asia_low_pct"]
            # / last["_last_swing_low_price"] / etc. prets pour Bot 3 v3.
            engine.process_bar(last, last_bar_ts_iso, bar_day)
            time.sleep(10)
    """

    def __init__(
        self,
        symbol: str,
        window_bars: int = 480,
        warn_stale_sec: int = 180,
        strict: bool = True,
    ):
        pure_sym = symbol.split(".")[0].upper()
        # R1 FIX (2026-06-07) : message clair selon le cas (MGC backlog explicite
        # vs symbole inconnu) — evite la silent inconsistency "validation ici OK
        # mais SierraLiveReader crash apres" identifiee review #1.
        if pure_sym in _THRESHOLD_TICKS_LONG_BAR_BACKLOG:
            raise ValueError(
                f"Symbole {pure_sym!r} en backlog Phase 8+ pour Bot3V3SierraReader. "
                f"SierraLiveReader (CORE/sierra_live_io.py:71) ne supporte que "
                f"('ES', 'NQ'). MGC necessite extension chain Sierra DMP "
                f"complete (DMP_Config.h, SierraLiveReader, etc.) avant activation. "
                f"Cf review #1 R1."
            )
        if pure_sym not in THRESHOLD_TICKS_LONG_BAR:
            raise ValueError(
                f"Symbole non supporte par Bot3V3SierraReader : {symbol!r}. "
                f"Supportes : {tuple(THRESHOLD_TICKS_LONG_BAR.keys())}."
            )

        self.symbol = pure_sym
        self.window_bars = window_bars
        self.warn_stale_sec = warn_stale_sec  # expose pour Bot 3 v3 paper compat
        self.tick_size = get_tick_size(pure_sym)
        self.threshold_long_pts = (
            THRESHOLD_TICKS_LONG_BAR[pure_sym] * self.tick_size
        )

        # Wrappee : SierraLiveReader stateful
        self._sierra_reader = SierraLiveReader(
            symbol=pure_sym,
            window_bars=window_bars,
            strict=strict,
        )

        # State streaming per-instance (1 instance par symbole)
        self._state = _WrapperState()

        # Cache derniere DataFrame transformee (anti retransform si polling
        # plus rapide que reception nouvelle bar Sierra). Cle = ts_event_ns
        # derniere bar buffer Sierra.
        self._last_processed_ts_ns: Optional[int] = None
        self._cached_df: Optional[pd.DataFrame] = None

    # ────────────────────────────────────────────────────────────────────
    # Public API (mimique LiveEnrichedReader)
    # ────────────────────────────────────────────────────────────────────

    def load_rolling_window_tail_only(self) -> Optional[pd.DataFrame]:
        """Charge la fenetre rolling Sierra + post-process en format Bot 3 v3.

        ⚠️ R3 FIX (2026-06-07) — CROSS-POLL DRIFT DOCUMENTE ⚠️
        ─────────────────────────────────────────────────────
        ATTENTION : seul `df.iloc[-1]` est garanti COHERENT cross-poll.

        Le state buffer Phase B+ (`prev_open/high/low/close`, `close_buffer`,
        `asia_high/low`, `cash_high/low`) est RESET a chaque appel puis
        reconstruit FROM SCRATCH en re-jouant TOUT le buffer rolling Sierra.

        Consequence : si le buffer Sierra glisse entre 2 polls (Poll 1 =
        bars T0..T479, Poll 2 = bars T1..T480), les features Phase B+ des
        bars INTERMEDIAIRES (df.iloc[0:-1]) peuvent VARIER cross-poll
        car leur `prev_bar` change (premiere bar du buffer n'a jamais de
        prev_bar). Exemple : bar T1 a `prev_bar=bar_T0` en Poll 1 mais
        `prev_bar=None` en Poll 2 → `long_up_bar(T1)` peut differer.

        Cross-poll drift = COMPORTEMENT ATTENDU pour les bars
        intermediaires. Bot 3 v3 engine ne consomme que `df.iloc[-1]`
        (cf `bot3_v3_continuation_paper.py:271`) → OK.

        Pour un rolling 100% deterministe cross-poll → implementer
        incremental offset (cache `_last_ts_seen`, ne re-transformer que
        nouvelles bars). Dette technique R3 backlog
        (`DOCS/IDEAS_BACKLOG.md`).

        Returns:
            pd.DataFrame trie ts_event ascending avec colonnes Bot 3 v3
            (close, high, low, open, dist_*_pct, long_up_bar, swings, etc.),
            ou None si pas de data dispo.

            ⚠️ Utiliser UNIQUEMENT `df.iloc[-1]` pour les features
            Phase B+ (long_up_bar, ctx_price_slope_5, dist_asia_*_pct,
            dist_cash_*_pct). Les features natives Sierra (close, high,
            low, open, dist_*_pct Batch B1, swings) sont stateless et
            cross-poll stables.
        """
        sierra_df = self._sierra_reader.load_rolling_window()
        if sierra_df is None or len(sierra_df) == 0:
            return None

        # Anti retransform : si la derniere bar Sierra a le meme ts que
        # la derniere bar deja transformee, on renvoie le cache.
        if "ts" in sierra_df.columns:
            last_ts_ms = sierra_df["ts"].iloc[-1]
            try:
                last_ts_ns = int(last_ts_ms) * MS_TO_NS
            except (TypeError, ValueError):
                last_ts_ns = None
            if (
                last_ts_ns is not None
                and last_ts_ns == self._last_processed_ts_ns
                and self._cached_df is not None
            ):
                return self._cached_df

        # Transform bar par bar dans l'ordre chronologique (state buffers
        # streaming). NB : si on a deja transforme certaines bars du buffer
        # rolling sur un appel precedent, on les RE-transforme (state buffer
        # idempotent : prev_bar et close_buffer sont overwrites).
        # Note : on RESET le state au debut pour avoir transformation
        # deterministe vs streaming. Trade-off OK car buffer rolling = quelques
        # centaines de bars, transform = qq ms.
        self._reset_state_for_full_replay()

        transformed_rows: List[Dict[str, Any]] = []
        for _, row in sierra_df.iterrows():
            sierra_bar = row.to_dict()
            try:
                bar = self._transform(sierra_bar)
            except Exception as e:
                _logger.warning(
                    "Bot3V3SierraReader transform fail bar ts=%s : %s",
                    sierra_bar.get("ts"), e,
                )
                continue
            transformed_rows.append(bar)

        if not transformed_rows:
            return None

        df = pd.DataFrame(transformed_rows)

        # ts_event datetime UTC (LiveEnrichedReader convention)
        if "ts_event_ns" in df.columns:
            df["ts_event"] = pd.to_datetime(
                df["ts_event_ns"], utc=True, unit="ns", errors="coerce"
            )

        # Cast defensif numerique (heritage P0-2)
        for col in _NUMERIC_CRITICAL_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Update cache
        if "ts_event_ns" in df.columns and len(df) > 0:
            try:
                self._last_processed_ts_ns = int(df["ts_event_ns"].iloc[-1])
            except (TypeError, ValueError):
                self._last_processed_ts_ns = None
        self._cached_df = df

        return df

    def load_rolling_window(self) -> Optional[pd.DataFrame]:
        """Alias retro-compat de `load_rolling_window_tail_only()`.

        R3 FIX (2026-06-07) : meme nom que LiveEnrichedReader pour
        compatibilite descendante avec Bot 3 v3 paper actuel et toute
        couche consumer existante. Comportement identique.

        ⚠️ ATTENTION : meme caveat cross-poll drift (cf docstring
        `load_rolling_window_tail_only`). Utiliser UNIQUEMENT
        `df.iloc[-1]` pour les features Phase B+.
        """
        return self.load_rolling_window_tail_only()

    def last_bar(self) -> Optional[Dict[str, Any]]:
        """Retourne la derniere bar transformee (dict), ou None.

        Helper non present sur LiveEnrichedReader original, ajoute ici
        pour debug / inspection. Le paper module utilise `load_rolling_window`
        + `df.iloc[-1]`.

        R3 FIX (2026-06-07) : utilise `load_rolling_window_tail_only` en
        interne (les 2 sont equivalents — alias). Seule `df.iloc[-1]` est
        garanti coherent cross-poll.
        """
        df = self.load_rolling_window_tail_only()
        if df is None or len(df) == 0:
            return None
        return df.iloc[-1].to_dict()

    def get_last_bar_age_seconds(self) -> float:
        """Age en secondes derniere bar wrappee (delegue SierraLiveReader)."""
        return self._sierra_reader.get_last_bar_age_seconds()

    def is_stale(self) -> bool:
        """True si derniere bar > warn_stale_sec (LiveEnrichedReader compat)."""
        return self.get_last_bar_age_seconds() > self.warn_stale_sec

    def reset(self) -> None:
        """Reset complet (utile pour tests). NB : ne reset PAS SierraLiveReader
        offsets fichiers (on garde le pointeur de lecture incremental)."""
        self._state = _WrapperState()
        self._last_processed_ts_ns = None
        self._cached_df = None

    # ────────────────────────────────────────────────────────────────────
    # Transform Sierra bar -> LiveEnrichedReader format
    # ────────────────────────────────────────────────────────────────────

    def _reset_state_for_full_replay(self) -> None:
        """Reset state buffers Phase B+ avant re-transform du buffer rolling.

        Reasoning : `load_rolling_window` rejoue toutes les bars du buffer
        (qq centaines max) a chaque appel. Pour avoir transform deterministe,
        on reset les buffers internes a chaque cycle. Couts qq ms, gain =
        absence de bug "drift d'etat" si le buffer change taille entre appels.
        """
        self._state = _WrapperState()

    def _transform(self, sierra_bar: Dict[str, Any]) -> Dict[str, Any]:
        """Transform 1 bar Sierra DMP -> format LiveEnrichedReader Bot 3 v3.

        Args:
            sierra_bar : dict bar Sierra DMP (380 cols schema 3.7.22).

        Returns:
            dict avec les 41 features Bot 3 v3 + champs natifs preserves.
            Champs natifs Sierra preserves (autres consommateurs futurs).
        """
        bar: Dict[str, Any] = dict(sierra_bar)  # preserve natifs + ajoute Bot 3 v3

        # 1. Renames natifs (24 features)
        self._apply_renames(sierra_bar, bar)

        # 2. Reconstructions triviales swings + pvwap (3 features)
        self._apply_swing_recons(sierra_bar, bar)
        self._apply_pvwap_pct(sierra_bar, bar)

        # 3. session_date_trading + rollover detection
        ts_event_ns = bar.get("ts_event_ns")
        trading_day = _derive_trading_day(ts_event_ns)
        bar["session_date_trading"] = trading_day or ""
        if trading_day is not None and trading_day != self._state.trading_day:
            self._state.reset_day(trading_day)

        # 4. Phase B+ Python ports (state-dependent)
        self._compute_long_bars(bar)
        self._compute_ctx_price_slope_5(bar)
        self._compute_asia_levels(bar)
        self._compute_cash_levels(bar)
        self._compute_ib_pct(bar)

        # 5. Clusters DROP (toujours 0). Documentation : engine fait
        # `if long_bar_ok OR cluster_ok` => engine se base sur long_bar seul.
        # Alternative future : porter ExtensionLineBuffer simplifie (backlog R2).
        bar["n_long_up_cluster_within_0_2pct"] = 0
        bar["n_long_dn_cluster_within_0_2pct"] = 0

        # 6. regime_mode : empty string (Bot 3 v3 utilise UNIQUEMENT pour logging
        # cf bot3_v3_continuation_paper.py:271).
        bar["regime_mode"] = ""

        # 7. Update prev_bar state (CRITIQUE pour next bar long_up/dn formule)
        o_now = _safe_float(bar.get("open"))
        h_now = _safe_float(bar.get("high"))
        l_now = _safe_float(bar.get("low"))
        c_now = _safe_float(bar.get("close"))
        self._state.prev_open = o_now
        self._state.prev_high = h_now
        self._state.prev_low = l_now
        self._state.prev_close = c_now

        return bar

    # ────────────────────────────────────────────────────────────────────
    # Categorie 1 - Renames natifs Sierra -> Bot 3 v3
    # ────────────────────────────────────────────────────────────────────

    def _apply_renames(
        self, sierra: Dict[str, Any], bar: Dict[str, Any]
    ) -> None:
        """Renames triviaux Sierra DMP -> format LiveEnrichedReader.

        Rules (cf audit DOCS/AUDIT_BOT3_V3_SIERRA_FEEDABILITY.md) :
        - price -> close
        - bar_high -> high, bar_low -> low
        - open -> open (deja natif Batch B4.5 schema 3.7.22)
        - ts (ms) -> ts_event_ns (* 1_000_000)
        - 17 distances `_pct` Batch B1 : memes noms, copies (deja dans bar)
        - vwap_slope_10 / atr : deja natifs, conserves
        - atr_ticks / atr_pts : R2 fix — exposition unite EXPLICITE (cf
          warnings semantiques en tete de fichier).
        """
        # OHLC renames
        price = _safe_float(sierra.get("price"))
        if price is not None:
            bar["close"] = price
        bh = _safe_float(sierra.get("bar_high"))
        if bh is not None:
            bar["high"] = bh
        bl = _safe_float(sierra.get("bar_low"))
        if bl is not None:
            bar["low"] = bl
        # open : Batch B4.5 (schema 3.7.22) Sierra expose `open` directement
        # (cf DMP_Writer.h:922). Preserve si present, sinon None.
        op = _safe_float(sierra.get("open"))
        if op is not None:
            bar["open"] = op
        else:
            # Fallback explicite (anti silent fallback) : None si Sierra n'a
            # pas open. Bot 3 v3 long_up_bar exige open : sera 0 si None.
            bar["open"] = None

        # ts ms epoch -> ts_event_ns int. Sierra DMP `ts` en millisecondes
        # (cf sierra_live_io.py:451 - schema 3.7.x).
        ts_ms = sierra.get("ts")
        try:
            if ts_ms is not None:
                bar["ts_event_ns"] = int(ts_ms) * MS_TO_NS
        except (TypeError, ValueError):
            bar["ts_event_ns"] = None

        # ────────────────────────────────────────────────────────────────
        # R2 FIX (2026-06-07) — Exposition EXPLICITE de l'unite de l'ATR.
        # ────────────────────────────────────────────────────────────────
        # Sierra DMP : `r.atr_daily` est en TICKS (cf DMP_Transform.h:880-882
        # + :1845). Le wrapper expose 2 cles dediees + garde `atr` pour compat
        # retrocompatible avec format LiveEnrichedReader natif.
        #
        # ⚠️ INCIDENT 27/05/2026 — `row["atr"]` (ambigu TICKS vs POINTS)
        # a cause un SL ~4x trop petit → edge backtest annule mecaniquement.
        # Cf .claude/rules/critical-tasks-review.md ligne 137-179 +
        # warnings semantiques tete de fichier.
        # ────────────────────────────────────────────────────────────────
        atr_ticks = _safe_float(sierra.get("atr"))
        bar["atr_ticks"] = atr_ticks  # TICKS — source Sierra DMP
        if atr_ticks is not None:
            bar["atr_pts"] = atr_ticks * self.tick_size  # POINTS — derive
        else:
            bar["atr_pts"] = None
        # Compat retrocompatible : bar["atr"] === bar["atr_ticks"] (TICKS).
        # NE PAS UTILISER pour SL/TP (consumers SL/TP doivent utiliser
        # bar["atr_ticks"] ou bar["atr_pts"] explicites).
        bar["atr"] = atr_ticks

        # Note : les 17 distances _pct natives Batch B1 (dist_vwap_d_pct,
        # dist_cur_vah_pct, dist_mq_call_pct, dist_1d_max_ticks_pct,
        # dist_long_up_nearest_pct, etc.) sont deja dans `sierra` -> deja dans
        # `bar` via dict(sierra). Pas besoin de renames explicites.
        # Idem pour `vwap_slope_10`, `is_in_us_cash`, `mins_since_news`,
        # `mins_to_next_news`, `session_id` - tous deja preserves.

    # ────────────────────────────────────────────────────────────────────
    # Categorie 2 - Reconstructions triviales
    # ────────────────────────────────────────────────────────────────────

    def _apply_swing_recons(
        self, sierra: Dict[str, Any], bar: Dict[str, Any]
    ) -> None:
        """Reconstruit `_last_swing_low_price` / `_last_swing_high_price`.

        Convention DMP confirmee (DMP_Transform.h:801) :
            CalcDistTicks(level, price) = (level - price) / tick_size
            => dist > 0 = level au-dessus du prix.

        Donc :
            swing_high_price = close + dist_swing_high * tick   (dist_high > 0)
            swing_low_price  = close + dist_swing_low * tick    (dist_low < 0)
        """
        close = _safe_float(sierra.get("price"))
        if close is None or close <= 0:
            bar["_last_swing_low_price"] = None
            bar["_last_swing_high_price"] = None
            return

        d_high = _safe_float(sierra.get("dist_swing_high"))
        d_low = _safe_float(sierra.get("dist_swing_low"))

        if d_high is not None:
            bar["_last_swing_high_price"] = close + d_high * self.tick_size
        else:
            bar["_last_swing_high_price"] = None

        if d_low is not None:
            bar["_last_swing_low_price"] = close + d_low * self.tick_size
        else:
            bar["_last_swing_low_price"] = None

    def _apply_pvwap_pct(
        self, sierra: Dict[str, Any], bar: Dict[str, Any]
    ) -> None:
        """Reconstruit `dist_pvwap_pct` depuis `dist_prev_vwap` (ticks).

        Sierra DMP expose `dist_prev_vwap` en TICKS (cf DMP_Writer.h:973).
        Bot 3 v3 attend `dist_pvwap_pct` en POURCENTAGE signe :
            dist_pvwap_pct = (prev_vwap - close) / close * 100
                           = (dist_prev_vwap * tick) / close * 100
        """
        close = _safe_float(sierra.get("price"))
        d_pvwap_ticks = _safe_float(sierra.get("dist_prev_vwap"))

        if close is None or close <= 0 or d_pvwap_ticks is None:
            bar["dist_pvwap_pct"] = None
            return
        bar["dist_pvwap_pct"] = (d_pvwap_ticks * self.tick_size) / close * 100.0

    # ────────────────────────────────────────────────────────────────────
    # Categorie 3 - Phase B+ Python ports
    # ────────────────────────────────────────────────────────────────────

    def _compute_long_bars(self, bar: Dict[str, Any]) -> None:
        """Compute long_up_bar / long_dn_bar via formule Phase B+ original.

        Formule (cf phase_b_plus_long_streaming.py:129-133) :
            LONG UP : O > prev_close AND H > prev_low + threshold_pts
            LONG DN : O < prev_close AND prev_high > L + threshold_pts
        Threshold per-symbole (NQ=24t=6pts, ES=12t=3pts, MGC=50t=5pts).

        Premiere bar (prev_bar None) -> 0 / 0.
        """
        o = _safe_float(bar.get("open"))
        h = _safe_float(bar.get("high"))
        l = _safe_float(bar.get("low"))

        long_up = 0
        long_dn = 0

        prev = self._state
        if (
            prev.prev_close is not None
            and prev.prev_low is not None
            and prev.prev_high is not None
        ):
            thr = self.threshold_long_pts
            if (
                o is not None and h is not None
                and o > prev.prev_close
                and h > prev.prev_low + thr
            ):
                long_up = 1
            if (
                o is not None and l is not None
                and o < prev.prev_close
                and prev.prev_high > l + thr
            ):
                long_dn = 1

        bar["long_up_bar"] = long_up
        bar["long_dn_bar"] = long_dn

    def _compute_ctx_price_slope_5(self, bar: Dict[str, Any]) -> None:
        """Compute ctx_price_slope_5 = pente regression lineaire 5 derniers close.

        Bot 3 v3 utilise pour veto L2 SLOPE_DIVERGENCE (engine ligne 734).
        Veto fail-CLOSED si absent (None) : on retourne 0.0 pendant warmup
        (Bot 3 v3 tolere 0.0 sans veto les premieres bars car veto applique
        |s5| >= threshold, donc 0.0 < threshold = pas de veto).
        """
        close = _safe_float(bar.get("close"))
        if close is None:
            # Ne pas push None dans deque (corrompt polyfit). Skip update.
            bar["ctx_price_slope_5"] = 0.0
            return

        self._state.close_buffer.append(close)

        if len(self._state.close_buffer) < SLOPE_WINDOW:
            # Warmup : 0.0 pour passer veto L2 sans crash (engine tolere 0.0).
            bar["ctx_price_slope_5"] = 0.0
            return

        ys = np.asarray(list(self._state.close_buffer), dtype=float)
        xs = np.arange(SLOPE_WINDOW, dtype=float)
        try:
            slope = float(np.polyfit(xs, ys, 1)[0])
        except (np.linalg.LinAlgError, ValueError):
            slope = 0.0
        bar["ctx_price_slope_5"] = slope

    def _compute_asia_levels(self, bar: Dict[str, Any]) -> None:
        """Compute dist_asia_high_pct / dist_asia_low_pct.

        Sierra expose `session_id` string : "Asia" / "London" / "US"
        (cf DMP_Writer.h:928-934). Pendant Asia : cummax/cummin sur
        bar_high/bar_low. Reset asia_high/low au rollover trading_day.

        Convention : dist = (level - close) / close * 100 (positif = au-dessus).
        """
        h = _safe_float(bar.get("high"))
        l = _safe_float(bar.get("low"))
        close = _safe_float(bar.get("close"))
        session = bar.get("session_id") or bar.get("session")

        if session == SESSION_ASIA and h is not None and l is not None:
            if self._state.asia_high is None or h > self._state.asia_high:
                self._state.asia_high = h
            if self._state.asia_low is None or l < self._state.asia_low:
                self._state.asia_low = l

        if close is None or close <= 0:
            bar["dist_asia_high_pct"] = None
            bar["dist_asia_low_pct"] = None
            return

        if self._state.asia_high is not None:
            bar["dist_asia_high_pct"] = (
                (self._state.asia_high - close) / close * 100.0
            )
        else:
            bar["dist_asia_high_pct"] = None

        if self._state.asia_low is not None:
            bar["dist_asia_low_pct"] = (
                (self._state.asia_low - close) / close * 100.0
            )
        else:
            bar["dist_asia_low_pct"] = None

    def _compute_cash_levels(self, bar: Dict[str, Any]) -> None:
        """Compute dist_cash_high_pct / dist_cash_low_pct.

        Sierra expose `is_in_us_cash` boolean (Batch B3.A schema 3.7.21,
        cf DMP_Writer.h:1406). Vrai dans la fenetre RTH 09:30-16:00 ET
        (DST handled C++ via mins_et).
        """
        h = _safe_float(bar.get("high"))
        l = _safe_float(bar.get("low"))
        close = _safe_float(bar.get("close"))
        in_cash_raw = bar.get("is_in_us_cash")
        try:
            in_cash = (in_cash_raw is not None and int(in_cash_raw) == 1)
        except (TypeError, ValueError):
            in_cash = False

        if in_cash and h is not None and l is not None:
            if self._state.cash_high is None or h > self._state.cash_high:
                self._state.cash_high = h
            if self._state.cash_low is None or l < self._state.cash_low:
                self._state.cash_low = l

        if close is None or close <= 0:
            bar["dist_cash_high_pct"] = None
            bar["dist_cash_low_pct"] = None
            return

        if self._state.cash_high is not None:
            bar["dist_cash_high_pct"] = (
                (self._state.cash_high - close) / close * 100.0
            )
        else:
            bar["dist_cash_high_pct"] = None

        if self._state.cash_low is not None:
            bar["dist_cash_low_pct"] = (
                (self._state.cash_low - close) / close * 100.0
            )
        else:
            bar["dist_cash_low_pct"] = None

    def _compute_ib_pct(self, bar: Dict[str, Any]) -> None:
        """Compute dist_ib_low_pct / dist_ib_high_pct depuis ticks Sierra.

        Sierra DMP expose `dist_ib_low` / `dist_ib_high` en TICKS (None hors IB).
        Conversion : pct = dist_ib_X * tick / close * 100.

        IB = Initial Balance (60 premieres min RTH 09:30-10:30 ET).
        Si None (hors IB ou IB pas encore complete) : conserve None (Bot 3 v3
        skip ces levels via `dist_pct is None` check engine ligne 491).
        """
        close = _safe_float(bar.get("close"))
        d_ib_low = _safe_float(bar.get("dist_ib_low"))
        d_ib_high = _safe_float(bar.get("dist_ib_high"))

        if close is None or close <= 0:
            bar["dist_ib_low_pct"] = None
            bar["dist_ib_high_pct"] = None
            return

        if d_ib_low is not None:
            bar["dist_ib_low_pct"] = (d_ib_low * self.tick_size) / close * 100.0
        else:
            bar["dist_ib_low_pct"] = None

        if d_ib_high is not None:
            bar["dist_ib_high_pct"] = (
                (d_ib_high * self.tick_size) / close * 100.0
            )
        else:
            bar["dist_ib_high_pct"] = None


__all__ = ("Bot3V3SierraReader",)
