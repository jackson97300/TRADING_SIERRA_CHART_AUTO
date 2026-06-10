"""bn_v4_engine.py — Moteur BN V4 reutilisable (live paper + backtest).

Port de `MIA_V3/validation/bn_v4_runner.py` vers une API stateful pour usage
live (paper trader Bot 2 / Sim2). Logique de detection setup A++ + state
machine Dow pivots pour trailing SL.

Spec BN V4 Jackson 23/05/2026 :
  1. Trend recent baissier (vwap_slope_10 < -0.005 sur 60 bars) — LONG / inverse SHORT
  2. Bottom zone : >= 2 niveaux institutionnels dans 0.15% du prix
  3. Density clusters defense : n_color_up_cluster + n_long_up_cluster >= grade
     - A++ : >= 8 (cluster fort)
     - A   : >= 5 | B : >= 3 | C : >= 2
  4. Edge buy actif (n_edge_buy_active >= 1)
  5. Confirmation volume (long_up_bar OR delta>50 OR big_buy_dom>=0.6 OR aggressor>=0.5)

Filtres optionnels (recommandes pour A++ NQ) :
  - require_open_window : trade UNIQUEMENT dans fenetres open session
  - require_long_trend_aligned : SHORT exige trend large baissier (asymetrique)

Procedure sortie (Dow pivots Jackson capture 22/05) :
  - SL initial : low(entry_bar) - 6 ticks (LONG) / high + 6 ticks (SHORT)
  - Trail : a chaque cassure du dernier high (close > prev_attack_high),
    SL monte au low du PULLBACK precedent - 6 ticks
  - Detection pullback : 3 bars consecutives sans new high (LONG)
  - Exit : SL hit OU timeout 90 bars

Causalite : aucun lookahead. Toutes les features utilisees sont CAUSAL au close T
(verification 23/05 sur phase_b_plus_color_streaming.py LAG-1 convention).

Usage paper live :
    from CORE.bn_v4_engine import BNV4Engine, BNV4Params, TrailingState

    engine = BNV4Engine(BNV4Params(
        grade_min="A++",
        require_open_window=True,
        require_long_trend_aligned=True,
    ))

    # 1. detection setup sur bar courante (rolling window N bars)
    setup = engine.detect_setup(df_window, idx_courant, direction="long")
    if setup is not None:
        # place bracket DTC
        sl_initial = engine.compute_initial_sl(setup, df_window.iloc[setup["bar_idx"]])
        trail = TrailingState(direction="long", entry_bar=df_window.iloc[setup["bar_idx"]])
        # ... ouvrir position ...

    # 2. update trailing sur chaque nouvelle bar pendant position active
    new_sl = engine.update_trailing(trail, df_window.iloc[-1])
    if new_sl is not None and new_sl != current_sl_broker:
        # cancel-replace SL via DTC
        ...

Auteur : MIA Trading V2
  v1.0 (2026-05-23) : port initial depuis bn_v4_runner.py PF 4.66 NQ A++
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any, Callable

import numpy as np
import pandas as pd


def _default_log_fn(code: str, **ctx) -> None:
    """No-op log_fn par defaut. Caller injecte la vraie fonction emit (paper
    trader / backtest runner). Pattern aligne sur `enricher_chain.py`.

    Fix VALIDATION_MISS code-reviewer 23/05 : sans log_fn, les 9 GATE_*_BLOCK
    du log_catalog n'etaient JAMAIS emis (anti-pattern interdit regle
    souveraine logs). Maintenant le caller peut hook le log via log_fn=_emit.
    """
    pass

# ─── Constantes (alignees bn_v4_runner.py) ─────────────────────────────────

TICK_SIZE = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
COST_POINTS_DEFAULT = 0.5
TIMEOUT_BARS_DEFAULT = 90
SL_INITIAL_BUFFER_TICKS = 6
SL_NEW_PIVOT_BUFFER_TICKS = 6
PULLBACK_DETECT_BARS = 3
ATR_PERIOD = 14

GRADE_THRESHOLDS = {"A++": 8, "A": 5, "B": 3, "C": 2}

# Niveaux institutionnels (positifs au-dessus du prix, negatifs en-dessous)
INSTITUTIONAL_LEVELS_LONG = [
    "dist_pdh_pct", "dist_pdl_pct",
    "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pvwap_pct", "dist_pvwap_sd1d_pct", "dist_pvwap_sd1u_pct",
    "dist_vwap_d_pct",
    "dist_vwap_d_sd1d_pct", "dist_vwap_d_sd1u_pct",
    "dist_vwap_d_sd2d_pct", "dist_vwap_d_sd2u_pct",
    "dist_vwap_w_pct",
    "dist_vwap_w_sd1d_pct", "dist_vwap_w_sd1u_pct",
    "dist_vwap_w_sd2d_pct",
    "dist_cur_vpoc_pct",
    "dist_mq_hvl_pct", "dist_mq_put_pct",
]
INSTITUTIONAL_LEVELS_SHORT = [
    "dist_pdh_pct", "dist_pdl_pct",
    "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pvwap_pct", "dist_pvwap_sd1d_pct", "dist_pvwap_sd1u_pct",
    "dist_vwap_d_pct",
    "dist_vwap_d_sd1d_pct", "dist_vwap_d_sd1u_pct",
    "dist_vwap_d_sd2d_pct", "dist_vwap_d_sd2u_pct",
    "dist_vwap_w_pct",
    "dist_vwap_w_sd1d_pct", "dist_vwap_w_sd1u_pct",
    "dist_vwap_w_sd2u_pct",
    "dist_cur_vpoc_pct",
    "dist_mq_hvl_pct", "dist_mq_call_pct",
]

# Fenetres open session (minutes ET depuis minuit). Empiriquement les setups
# A++ gagnants sont concentres dans ces fenetres (Jackson 23/05).
OPEN_WINDOWS_MIN_ET = (
    (180, 270),     # London open : 03:00-04:30 ET
    (540, 630),     # NY RTH open : 09:00-10:30 ET
    (1140, 1230),   # Asia / Tokyo pre-open : 19:00-20:30 ET
)


# ─── Params (config grid-searchable) ───────────────────────────────────────

@dataclass
class BNV4Params:
    """Parametres detection setup BN V4. Defauts = config optimale 23/05
    (PF 4.66 NQ A++ both directions sur 60 trades / 8 jours)."""
    # Proximite niveau institutionnel (% du prix)
    prox_pct: float = 0.15
    # Nb minimum de niveaux dans la confluence
    n_levels_min: int = 2
    # Grade minimum accepte ("A++" / "A" / "B" / "C")
    grade_min: str = "A++"
    # Volume bar courante / rolling mean min (1.2 = +20%)
    vol_ratio_min: float = 1.2
    # Window trend recent (bars)
    trend_lookback: int = 60
    # Seuil pente VWAP pour confirmer trend (positif/negatif)
    trend_slope_min: float = 0.005
    # Distance max niveau "top" pour entry mode breakout (% du prix)
    top_level_max_dist_pct: float = 0.5
    # FILTRE OPEN SESSION (recommande pour A++)
    require_open_window: bool = True
    # FILTRE TREND LONG asymetrique (SHORT only, recommande pour A++)
    require_long_trend_aligned: bool = True
    # Window trend large (4h en bars 1-min)
    trend_long_lookback: int = 240
    # Cost aller-retour estime (points)
    cost_points: float = COST_POINTS_DEFAULT
    # Timeout max position (bars)
    timeout_bars: int = TIMEOUT_BARS_DEFAULT
    # Footprint seuil min signaux confluents (1-5). Backtest >=1 reste optimal
    # (early bottom). Cf bn_v4_runner.py validation 23/05.
    footprint_min_signals: int = 1
    # Fix P0.2 code-reviewer 23/05 : guard SL initial absurde (wick extreme)
    # 26/05/2026 Jackson : 40t cap trop strict — 2 setups grade A++ density 12
    # rejetes ce matin (SL 61t pour TP 200t = R 3.28, setup valide). Pass 40 -> 80
    # pour couvrir les SL "naturels" sur swing entry_bar large. Reste un cap dur
    # contre les SL absurdes (>20pts NQ = signal mauvais ou bar anormale).
    max_risk_ticks: int = 80       # cap risk en ticks (NQ : 80 = 20 pts)
    min_risk_ticks: int = 4        # plancher risk (eviter SL trop serre)
    # Mode dual A++ TRADE / A OBSERVE (Jackson directive 23/05) :
    # observation_grade_min = grade minimum pour LOGGER setups en observation
    # (sans envoyer ordre DTC). grade_min reste le filtre TRADE actif.
    # Permet de tracker perf comparative A vs A++ sur 30 jours.
    # None = pas d'observation (back-compat). "A" = observer A et A++, trader A++.
    observation_grade_min: Optional[str] = None

    # WINDOW_OBSERVE mode (Jackson directive 27/05, anti-pattern-11 cf
    # `feedback_pattern11_repetition_avoided.md`). Default OFF = comportement
    # historique strictement preserve. Quand True : les setups A++ qui auraient
    # passe TOUS les gates SAUF `open_window` sont detectes ET routes vers
    # mode="OBSERVE_WINDOW" (separe de "OBSERVE" existing). Pas d'ordre DTC,
    # pas de gate eco/cooldown, juste log JSONL dedie + simul PnL. Objectif :
    # collecter 30j de data hors-windows pour decision data-driven d'elargir.
    observe_outside_windows: bool = False

    # 29/05 FIX BETA Jackson : anti stop-hunt momentum 60bars.
    # Backtest 21 setups + 5 trades execute (24-28/05) : gate BETA seul
    # sepere parfaitement 3 gagnants vs 3 perdants. Veto setup si
    # vwap_slope_10 mean sur 60 dernieres bars > +0.20 (SHORT) ou
    # < -0.20 (LONG). Filter momentum contre-trend 1h moyenne.
    # PnL save sur backtest : +$40 (= toutes pertes 28/05 evitees), 0 gagnant tue.
    # Volume : 11/21 setups passent (52%), acceptable.
    # Seuil 0.20 calibre empirique N=5, a monitorer J+7.
    slope_mean_60_veto_threshold: float = 0.20

    def __post_init__(self):
        """Validation fail-loud config (P0 fix code-reviewer 23/05).

        Sans ce check, typo Jackson `grade_min="A+"` ou `observation_grade_min="Z"`
        passe le boot puis crash silencieusement au 1er setup detecte =
        KeyError dans check_zone -> pas de trade lundi.
        """
        if self.grade_min not in GRADE_THRESHOLDS:
            raise ValueError(
                f"BNV4Params.grade_min invalide : {self.grade_min!r}. "
                f"Valeurs admises : {list(GRADE_THRESHOLDS.keys())}"
            )
        if self.observation_grade_min is not None:
            if self.observation_grade_min not in GRADE_THRESHOLDS:
                raise ValueError(
                    f"BNV4Params.observation_grade_min invalide : "
                    f"{self.observation_grade_min!r}. "
                    f"Valeurs admises : {list(GRADE_THRESHOLDS.keys())} ou None"
                )
            # observation_grade_min doit etre STRICTEMENT PLUS PERMISSIF (seuil
            # numerique <) que grade_min, sinon aucun OBSERVE possible.
            if GRADE_THRESHOLDS[self.observation_grade_min] >= GRADE_THRESHOLDS[self.grade_min]:
                raise ValueError(
                    f"BNV4Params.observation_grade_min={self.observation_grade_min!r} "
                    f"(seuil {GRADE_THRESHOLDS[self.observation_grade_min]}) doit etre "
                    f"PLUS PERMISSIF que grade_min={self.grade_min!r} "
                    f"(seuil {GRADE_THRESHOLDS[self.grade_min]}). "
                    f"Sinon aucun OBSERVE possible."
                )
        # Guard footprint seuil
        if not (1 <= self.footprint_min_signals <= 5):
            raise ValueError(
                f"BNV4Params.footprint_min_signals={self.footprint_min_signals} "
                f"hors [1,5]"
            )
        # Guard risk ticks bornes
        if self.max_risk_ticks <= self.min_risk_ticks:
            raise ValueError(
                f"BNV4Params.max_risk_ticks={self.max_risk_ticks} doit etre > "
                f"min_risk_ticks={self.min_risk_ticks}"
            )


# ─── Helpers detection (purs, no I/O) ──────────────────────────────────────

def _safe_int(v: Any) -> int:
    """NaN/None -> 0, sinon int."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _safe_float(v: Any, default: float = 0.0) -> float:
    """NaN/None -> default, sinon float."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _require_float(v: Any, name: str) -> float:
    """Fail-loud helper pour champs CRITIQUES (OHLC). Levee si NaN/None.

    Fix P0.3 code-reviewer 23/05 : si bar entry a `high`/`low`/`close` NaN
    (rare mais possible si JSONL parse fail / pipeline race condition),
    `_safe_float` retournait 0.0 silencieusement -> SL = -1.5 NQ = position
    bloquee sans trail. Solution : OHLC sont OBLIGATOIRES, fail-loud.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        raise ValueError(
            f"Field '{name}' requis mais absent/NaN — bar invalide pour BN V4"
        )
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"Field '{name}' non castable en float ({type(v).__name__}={v!r}): {e}"
        ) from e


def count_levels_proche(bar: Any, levels: list, prox_pct: float) -> int:
    """Compte niveaux dont |dist_*_pct| < prox_pct au moment de la bar.

    Accepte pd.Series ou dict.
    """
    n = 0
    for f in levels:
        v = bar.get(f) if hasattr(bar, "get") else getattr(bar, f, None)
        if v is None or pd.isna(v):
            continue
        if abs(float(v)) < prox_pct:
            n += 1
    return n


def density_clusters(bar: Any, direction: str) -> int:
    """Densite clusters defense = trace de defense persistente."""
    if direction == "long":
        a = bar.get("n_color_up_cluster_within_0_2pct")
        b = bar.get("n_long_up_cluster_within_0_2pct")
    else:
        a = bar.get("n_color_dn_cluster_within_0_2pct")
        b = bar.get("n_long_dn_cluster_within_0_2pct")
    return _safe_int(a) + _safe_int(b)


def assign_grade(density: int) -> str:
    """Mapping density -> grade. Renvoie 'SKIP' si density < seuil C."""
    for g, seuil in sorted(GRADE_THRESHOLDS.items(), key=lambda x: -x[1]):
        if density >= seuil:
            return g
    return "SKIP"


def edge_buy_active(bar: Any, direction: str) -> bool:
    """Edge buy/sell actif autour du prix."""
    f = "n_edge_buy_active" if direction == "long" else "n_edge_sell_active"
    return _safe_int(bar.get(f)) >= 1


def in_open_window(bar: Any) -> bool:
    """True si la bar est dans une fenetre d'open session (Asia/London/NY)."""
    ts = bar.get("ts_event")
    if ts is None or pd.isna(ts):
        return False
    if not isinstance(ts, pd.Timestamp):
        ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    et = ts.tz_convert("America/New_York")
    min_et = et.hour * 60 + et.minute
    for win_start, win_end in OPEN_WINDOWS_MIN_ET:
        if win_start <= min_et < win_end:
            return True
    return False


def trend_recent(df: pd.DataFrame, i: int, params: BNV4Params,
                  direction: str) -> bool:
    """Trend recent dans le bon sens (baissier pour LONG, haussier pour SHORT)
    sur les `trend_lookback` dernieres bars."""
    lo = max(0, i - params.trend_lookback)
    if i - lo < 30:
        return False
    sub_slope = df["vwap_slope_10"].iloc[lo:i + 1]
    if sub_slope.isna().all():
        return False
    mean_slope = sub_slope.mean()
    if direction == "long":
        return mean_slope < -params.trend_slope_min   # baissier prealable
    else:
        return mean_slope > params.trend_slope_min    # haussier prealable (rallye correctif)


def trend_long_aligned(df: pd.DataFrame, i: int, params: BNV4Params,
                        direction: str) -> bool:
    """Trend LARGE aligne avec direction (Jackson 23/05 SHORT en tendance SHORT).
    Sur `trend_long_lookback` (4h par defaut)."""
    lo = max(0, i - params.trend_long_lookback)
    if i - lo < 60:
        return False
    sub_slope = df["vwap_slope_10"].iloc[lo:i + 1]
    if sub_slope.isna().all():
        return False
    mean_slope = sub_slope.mean()
    if direction == "long":
        return mean_slope > 0     # trend large UP pour BN long (bottom defensible apres baisse intra)
    else:
        return mean_slope < 0     # trend large DOWN pour BN short (continuation)


def volume_breakout(df: pd.DataFrame, i: int, params: BNV4Params) -> bool:
    """Volume bar courante > rolling mean (30 bars) x ratio."""
    if "total_vol" not in df.columns:
        return True       # mode degrade : pas de filtre volume si feature absente
    lo = max(0, i - 30)
    if i - lo < 10:
        return False
    baseline = float(df["total_vol"].iloc[lo:i].mean())
    current = float(df["total_vol"].iloc[i])
    return current / max(baseline, 1.0) >= params.vol_ratio_min


def footprint_confirmed(bar: Any, direction: str, strict: bool = False,
                         min_signals: int = 1) -> bool:
    """Confirmation volume directionnel.

    23/05 v2 : pool 5 signaux (ajout long_dn_up_pattern LONG /
    long_up_dn_pattern SHORT). Backtest empirique seuil >=1 reste optimal
    (PF 5.11 vs >=2 PF 1.16) — coherent spec "bottom AVANT l'attaque".

    Args:
        bar : dict-like (pd.Series ou dict)
        direction : "long" / "short"
        strict : True = mode breakout, exige >= max(2, min_signals) + bar
                 de bonne couleur
        min_signals : seuil minimum signaux confluents (1-5, defaut 1).
                       Si strict=True, prend max(2, min_signals).
    """
    assert direction in ("long", "short"), f"direction invalide : {direction}"
    if direction == "long":
        signals = [
            _safe_float(bar.get("long_up_bar")) == 1.0,
            _safe_float(bar.get("aggressor_imbalance")) >= 0.5,
            _safe_float(bar.get("big_buy_dominance")) >= 0.6,
            _safe_float(bar.get("delta_bar")) > 50,
            _safe_float(bar.get("long_dn_up_pattern")) == 1.0,   # NEW 23/05
        ]
        n_ok = sum(signals)
        if not strict:
            return n_ok >= min_signals
        close_v = _safe_float(bar.get("close"))
        open_v = _safe_float(bar.get("open"))
        return n_ok >= max(2, min_signals) and close_v > open_v
    else:
        signals = [
            _safe_float(bar.get("long_dn_bar")) == 1.0,
            _safe_float(bar.get("aggressor_imbalance")) <= -0.5,
            _safe_float(bar.get("big_sell_dominance")) >= 0.6,
            _safe_float(bar.get("delta_bar")) < -50,
            _safe_float(bar.get("long_up_dn_pattern")) == 1.0,   # NEW 23/05
        ]
        n_ok = sum(signals)
        if not strict:
            return n_ok >= min_signals
        close_v = _safe_float(bar.get("close"))
        open_v = _safe_float(bar.get("open"))
        return n_ok >= max(2, min_signals) and close_v < open_v


def find_top_level_price(bar: Any, direction: str,
                          max_dist_pct: float) -> Optional[float]:
    """Trouve prix du niveau institutionnel le plus proche AU-DESSUS du prix
    (LONG) ou EN-DESSOUS (SHORT). Convention dist_*_pct :
      positif = niveau au-dessus du prix
      negatif = niveau en-dessous du prix
    """
    close = _safe_float(bar.get("close"))
    if close <= 0:
        return None
    levels = (INSTITUTIONAL_LEVELS_LONG if direction == "long"
              else INSTITUTIONAL_LEVELS_SHORT)
    best_dist = None
    for f in levels:
        v = bar.get(f)
        if v is None or pd.isna(v):
            continue
        v = float(v)
        if direction == "long":
            if 0 < v < max_dist_pct:
                if best_dist is None or v < best_dist:
                    best_dist = v
        else:
            if -max_dist_pct < v < 0:
                if best_dist is None or v > best_dist:
                    best_dist = v
    if best_dist is None:
        return None
    return close * (1.0 + best_dist / 100.0)


# ─── Trailing state machine Dow pivots (LIVE) ──────────────────────────────

@dataclass
class TrailingState:
    """State machine Dow pivots pour SL trail pendant position active.

    Pickle-safe : primitifs seulement (pour persist crash recovery).

    Architecture :
      - LONG : track la derniere attaque (= peak high) + pullback en cours
        Quand nouveau cycle commence (close > last_attack_high), SL monte
        au low du pullback - 6 ticks.
      - SHORT : symetrique (LH+LL).

    Mise a jour :
      `update(bar)` est appelee a chaque close de bar pendant position active.
      Retourne le nouveau SL si update propose, sinon None.

    Fix P0.1 code-reviewer 23/05 : idempotence via `last_processed_ts_ns`.
    Sans ce guard, double appel sur meme bar (restart/replay) incrementait
    bars_since_new_extreme 2x = pullback detecte 1 bar trop tot = SL avance
    trop vite = 1 R perdu sur bon pivot.

    Fix P1.1 code-reviewer 23/05 : timeout via ts_event diff (pas bar_idx
    rolling window). entry_ts_ns stocke timestamp entry, compare avec bar
    courante ts.
    """
    direction: str                  # "long" / "short"
    entry_bar_idx: int = 0          # index de la bar entry (informatif)
    entry_ts_ns: int = 0            # timestamp entry epoch ns (fix P1.1)
    entry_price: float = 0.0
    sl_current: float = 0.0
    tick: float = 0.25

    # State machine LONG
    last_attack_high: float = 0.0
    pullback_low_running: float = 0.0
    bars_since_new_extreme: int = 0
    in_pullback: bool = False
    n_pivots_confirmed: int = 0

    # State machine SHORT
    last_attack_low: float = 0.0
    pullback_high_running: float = 0.0

    # Fix P0.1 idempotence : derniere bar traitee (epoch ns timestamp)
    last_processed_ts_ns: int = 0


def make_trailing_state(direction: str, entry_bar: Any,
                         entry_price: float, tick: float,
                         entry_bar_idx: int = 0,
                         max_risk_ticks: int = 40,
                         min_risk_ticks: int = 4) -> TrailingState:
    """Factory : init state apres ouverture position.

    Fix P0.2 + P0.3 code-reviewer 23/05 :
      - OHLC fail-loud via _require_float (NaN -> ValueError)
      - Guard risk_ticks dans [min_risk_ticks, max_risk_ticks]
    Fix P1.1 : entry_ts_ns stocke pour timeout robust (vs bar_idx rolling).

    Args:
        direction : "long" / "short"
        entry_bar : dict-like avec high/low/ts_event_ns (OBLIGATOIRES)
        entry_price : prix d'entree (au close T)
        tick : taille tick (NQ=0.25)
        entry_bar_idx : index informatif
        max_risk_ticks : guard SL absurde (default 40 NQ = 10 pts)
        min_risk_ticks : guard SL trop serre (default 4 NQ = 1 pt)

    Raises:
        ValueError : si OHLC NaN/None OU risk hors [min, max] ticks.
    """
    assert direction in ("long", "short"), f"direction invalide : {direction}"

    # Fix P0.3 : OHLC fail-loud
    eb_high = _require_float(entry_bar.get("high"), "entry_bar.high")
    eb_low = _require_float(entry_bar.get("low"), "entry_bar.low")
    entry_ts_ns = int(entry_bar.get("ts_event_ns", 0) or 0)

    if direction == "long":
        sl_initial = eb_low - SL_INITIAL_BUFFER_TICKS * tick
    else:
        sl_initial = eb_high + SL_INITIAL_BUFFER_TICKS * tick

    # Fix P0.2 : guard risk
    risk_ticks = abs(entry_price - sl_initial) / tick
    if risk_ticks > max_risk_ticks:
        raise ValueError(
            f"SL initial risk trop large : {risk_ticks:.1f}t > {max_risk_ticks}t "
            f"(entry={entry_price}, sl={sl_initial}, dir={direction})"
        )
    if risk_ticks < min_risk_ticks:
        raise ValueError(
            f"SL initial risk trop serre : {risk_ticks:.1f}t < {min_risk_ticks}t "
            f"(entry={entry_price}, sl={sl_initial}, dir={direction})"
        )

    state = TrailingState(
        direction=direction,
        entry_bar_idx=entry_bar_idx,
        entry_ts_ns=entry_ts_ns,
        entry_price=entry_price,
        sl_current=sl_initial,
        tick=tick,
    )

    if direction == "long":
        state.last_attack_high = eb_high
        state.pullback_low_running = eb_low
    else:
        state.last_attack_low = eb_low
        state.pullback_high_running = eb_high

    return state


def update_trailing(state: TrailingState, bar: Any) -> Optional[float]:
    """Update state machine Dow pivots avec une nouvelle bar (close).

    Fix P0.1 idempotence : verifie ts_event_ns vs last_processed_ts_ns.
    Si meme bar appelee 2x (restart/replay), return None sans muter le state.

    Fix P0.3 fail-loud : OHLC requis (NaN -> ValueError remontee au caller).

    Returns:
        new_sl : float si le SL doit etre deplace, None si pas de changement.
        Ne renvoie PAS None si le prix touche le SL — le bot doit checker
        l'exit via la position broker (DTC OCO se charge du fill SL).

    Raises:
        ValueError : si bar.high/low/close NaN/None.
    """
    # Fix P0.1 idempotence
    cur_ts_ns = int(bar.get("ts_event_ns", 0) or 0)
    if cur_ts_ns > 0 and cur_ts_ns <= state.last_processed_ts_ns:
        return None    # deja traite, no-op
    state.last_processed_ts_ns = cur_ts_ns

    # Fix P0.3 OHLC fail-loud
    hj = _require_float(bar.get("high"), "bar.high")
    lj = _require_float(bar.get("low"), "bar.low")
    cj = _require_float(bar.get("close"), "bar.close")

    if state.direction == "long":
        new_sl = None
        # 1. Nouveau high ?
        if hj > state.last_attack_high:
            state.last_attack_high = hj
            state.bars_since_new_extreme = 0
            # Si on etait en pullback ET cassure confirmee (close > last_attack_high)
            if state.in_pullback and cj > state.last_attack_high - state.tick:
                # CONFIRMATION : SL monte au low du pullback
                candidate_sl = (state.pullback_low_running
                                 - SL_NEW_PIVOT_BUFFER_TICKS * state.tick)
                if candidate_sl > state.sl_current:
                    state.sl_current = candidate_sl
                    state.n_pivots_confirmed += 1
                    new_sl = candidate_sl
                state.in_pullback = False
                state.pullback_low_running = lj
        else:
            state.bars_since_new_extreme += 1
            # Track low du pullback en cours
            if lj < state.pullback_low_running:
                state.pullback_low_running = lj
            # Pullback demarre si N bars sans new high
            if (state.bars_since_new_extreme >= PULLBACK_DETECT_BARS
                    and not state.in_pullback):
                state.in_pullback = True
                state.pullback_low_running = lj
        return new_sl

    else:  # SHORT (symetrique)
        new_sl = None
        if lj < state.last_attack_low:
            state.last_attack_low = lj
            state.bars_since_new_extreme = 0
            if state.in_pullback and cj < state.last_attack_low + state.tick:
                candidate_sl = (state.pullback_high_running
                                 + SL_NEW_PIVOT_BUFFER_TICKS * state.tick)
                if candidate_sl < state.sl_current:
                    state.sl_current = candidate_sl
                    state.n_pivots_confirmed += 1
                    new_sl = candidate_sl
                state.in_pullback = False
                state.pullback_high_running = hj
        else:
            state.bars_since_new_extreme += 1
            if hj > state.pullback_high_running:
                state.pullback_high_running = hj
            if (state.bars_since_new_extreme >= PULLBACK_DETECT_BARS
                    and not state.in_pullback):
                state.in_pullback = True
                state.pullback_high_running = hj
        return new_sl


# ─── Detection setup (facade) ──────────────────────────────────────────────

def check_zone(df: pd.DataFrame, i: int, params: BNV4Params,
                direction: str,
                log_fn: Optional[Callable] = None,
                symbol: str = "NQ") -> Optional[dict]:
    """Detecte la ZONE bottom (5 phases sans entry direct).

    Mode dual 23/05 : si `observation_grade_min` defini ET inferieur a
    grade_min, accepte les grades >= observation_grade_min mais marque
    `mode="OBSERVE"` (vs `mode="TRADE"` si grade >= grade_min).

    Args:
        log_fn : Callable(code: str, **ctx) -> None pour emit GATE_*_BLOCK.
                  Default = no-op. Caller (paper trader) injecte la vraie
                  fonction emit. Fix VALIDATION_MISS code-reviewer 23/05.
        symbol : symbole pour les emits log

    Returns:
        Zone dict si conditions 1-4 OK, None sinon. Inclut champ `mode`
        ("TRADE" / "OBSERVE").
    """
    if log_fn is None:
        log_fn = _default_log_fn

    if i < max(params.trend_lookback, params.trend_long_lookback):
        return None
    bar = df.iloc[i]

    # 0. Filtre OPEN SESSION
    # WINDOW_OBSERVE (27/05) : si `observe_outside_windows=True`, NE PAS skip
    # quand hors-fenetre. On marque `outside_window=True` pour forcer mode
    # OBSERVE_WINDOW en fin de check_zone. Default OFF = comportement identique
    # a avant le 27/05 (skip strict hors fenetre).
    outside_window = False
    if params.require_open_window and not in_open_window(bar):
        ts = bar.get("ts_event")
        if not params.observe_outside_windows:
            # Comportement historique : skip immediat
            log_fn("BN_V4_GATE_OPEN_WINDOW_BLOCK", sym=symbol,
                    ts_et=str(ts), mins_et="hors_fenetre")
            return None
        else:
            # WINDOW_OBSERVE : continue evaluation, route vers OBSERVE_WINDOW
            outside_window = True
            log_fn("BN_V4_OUTSIDE_WINDOW_CANDIDATE", sym=symbol,
                    ts_et=str(ts))

    # 0bis. Filtre TREND LARGE aligne (SHORT only, asymetrique)
    if params.require_long_trend_aligned and direction == "short":
        if not trend_long_aligned(df, i, params, direction):
            lo = max(0, i - params.trend_long_lookback)
            sub_slope = df["vwap_slope_10"].iloc[lo:i + 1]
            slope_240 = float(sub_slope.mean()) if not sub_slope.isna().all() else None
            log_fn("BN_V4_GATE_TREND_LONG_ALIGN_BLOCK", sym=symbol,
                    direction=direction, slope_240=slope_240)
            return None

    # 1. Trend recent dans le bon sens
    if not trend_recent(df, i, params, direction):
        lo = max(0, i - params.trend_lookback)
        sub_slope = df["vwap_slope_10"].iloc[lo:i + 1]
        slope_mean = float(sub_slope.mean()) if not sub_slope.isna().all() else None
        threshold = -params.trend_slope_min if direction == "long" else params.trend_slope_min
        log_fn("BN_V4_GATE_TREND_BLOCK", sym=symbol, direction=direction,
                slope_mean=slope_mean, threshold=threshold)
        return None

    # 2. Niveaux institutionnels proches
    levels = (INSTITUTIONAL_LEVELS_LONG if direction == "long"
              else INSTITUTIONAL_LEVELS_SHORT)
    n_lvls = count_levels_proche(bar, levels, params.prox_pct)
    if n_lvls < params.n_levels_min:
        log_fn("BN_V4_GATE_LEVELS_BLOCK", sym=symbol, direction=direction,
                n_levels=n_lvls)
        return None

    # 3. Density clusters defense
    density = density_clusters(bar, direction)
    grade = assign_grade(density)
    if grade == "SKIP":
        log_fn("BN_V4_GATE_DENSITY_BLOCK", sym=symbol, direction=direction,
                density=density, grade="SKIP")
        return None

    # Mode dual : determine TRADE vs OBSERVE selon grade
    trade_threshold = GRADE_THRESHOLDS[params.grade_min]
    grade_value = GRADE_THRESHOLDS[grade]
    if params.observation_grade_min is not None:
        observe_threshold = GRADE_THRESHOLDS[params.observation_grade_min]
        if grade_value < observe_threshold:
            log_fn("BN_V4_GATE_DENSITY_BLOCK", sym=symbol, direction=direction,
                    density=density, grade=grade)
            return None
        mode = "TRADE" if grade_value >= trade_threshold else "OBSERVE"
    else:
        if grade_value < trade_threshold:
            log_fn("BN_V4_GATE_DENSITY_BLOCK", sym=symbol, direction=direction,
                    density=density, grade=grade)
            return None
        mode = "TRADE"

    # 4. Edge buy/sell active
    if not edge_buy_active(bar, direction):
        feature = "n_edge_buy_active" if direction == "long" else "n_edge_sell_active"
        log_fn("BN_V4_GATE_EDGE_BLOCK", sym=symbol, direction=direction,
                feature=feature)
        return None

    # 5. Top level identifie
    top_level = find_top_level_price(bar, direction,
                                       params.top_level_max_dist_pct)
    if top_level is None:
        close_v = _safe_float(bar.get("close"))
        log_fn("BN_V4_GATE_TOP_LEVEL_BLOCK", sym=symbol, direction=direction,
                close=close_v, max_dist_pct=params.top_level_max_dist_pct)
        return None

    # WINDOW_OBSERVE override : si hors-fenetre et feature ON, force mode
    # OBSERVE_WINDOW pour route vers logger dedie (pas de DTC, pas de gates
    # post-detection). Conserve la classification grade pour analyse 30j.
    if outside_window:
        mode = "OBSERVE_WINDOW"

    return dict(
        zone_bar_idx=i,
        bottom_zone=float(bar["low"]) if direction == "long"
                     else float(bar["high"]),
        top_level=top_level,
        direction=direction,
        grade=grade,
        density=density,
        n_levels=n_lvls,
        mode=mode,                   # NEW 23/05 : "TRADE" / "OBSERVE" / "OBSERVE_WINDOW" (27/05)
        outside_window=outside_window,  # NEW 27/05 : flag pour bn_v4_paper routing
    )


def check_momentum_slope_60(df: pd.DataFrame, i: int, direction: str,
                              threshold: float = 0.20) -> tuple[bool, Optional[float]]:
    """Anti stop-hunt : veto setup si vwap_slope_10 mean 60 bars contre-trend fort.

    Backtest 5 trades execute 24-28/05/2026 (Jackson 29/05) :
      - Gagnants (2) : slope_mean_60 = +0.14 (SHORT) / -0.09 (LONG) PASS
      - Perdants (3) : slope_mean_60 = +0.44, +0.39, +0.37 (SHORT) BLOCK

    Identifie le piege "bounce dans downtrend" / "pullback dans uptrend" qui
    aspire les setups bottom counter-trend.

    Args:
        df : DataFrame avec colonne vwap_slope_10
        i : index bar courante
        direction : "long" / "short"
        threshold : seuil veto (default 0.20, calibre N=5)

    Returns:
        (allow, slope_mean_60) : allow=False si veto, slope pour ctx log.
        Si < 30 valeurs valides dans les 60 bars → laisse passer (manque contexte).
    """
    if i < 60 or "vwap_slope_10" not in df.columns:
        return True, None
    window = df["vwap_slope_10"].iloc[i - 60:i]
    valid = window.dropna()
    if len(valid) < 30:
        return True, None
    mean_slope = float(valid.mean())
    if direction == "short" and mean_slope > threshold:
        return False, mean_slope
    if direction == "long" and mean_slope < -threshold:
        return False, mean_slope
    return True, mean_slope


def check_setup(df: pd.DataFrame, i: int, params: BNV4Params,
                 direction: str,
                 log_fn: Optional[Callable] = None,
                 symbol: str = "NQ") -> Optional[dict]:
    """Detection setup BN V4 mode 'bottom' (entry direct).

    Args:
        log_fn : Callable injectable pour emit GATE_*_BLOCK (caller paper
                  trader). Default no-op.
        symbol : symbole pour les emits log

    Returns:
        Setup dict avec entry_price + zone info, None sinon.

    NOTE : la version 'breakout' (entry sur cassure) du runner standalone
    n'est pas portee ici — config Jackson 23/05 = bottom mode (PF 4.66).
    """
    if log_fn is None:
        log_fn = _default_log_fn

    zone = check_zone(df, i, params, direction, log_fn=log_fn, symbol=symbol)
    if zone is None:
        return None

    bar = df.iloc[i]

    # Mode bottom : entry direct au close + confirmation volume + footprint
    if not volume_breakout(df, i, params):
        lo = max(0, i - 30)
        baseline = float(df["total_vol"].iloc[lo:i].mean()) if "total_vol" in df.columns else None
        current = float(df["total_vol"].iloc[i]) if "total_vol" in df.columns else None
        ratio = (current / max(baseline, 1.0)) if (current is not None and baseline is not None) else None
        log_fn("BN_V4_GATE_VOLUME_BLOCK", sym=symbol, direction=direction,
                current_vol=current, baseline=baseline, ratio=ratio)
        return None
    if not footprint_confirmed(bar, direction, strict=False,
                                 min_signals=params.footprint_min_signals):
        # Compter n_signals fired pour le log (sans re-implementer la logique)
        if direction == "long":
            signals = [
                _safe_float(bar.get("long_up_bar")) == 1.0,
                _safe_float(bar.get("aggressor_imbalance")) >= 0.5,
                _safe_float(bar.get("big_buy_dominance")) >= 0.6,
                _safe_float(bar.get("delta_bar")) > 50,
                _safe_float(bar.get("long_dn_up_pattern")) == 1.0,
            ]
        else:
            signals = [
                _safe_float(bar.get("long_dn_bar")) == 1.0,
                _safe_float(bar.get("aggressor_imbalance")) <= -0.5,
                _safe_float(bar.get("big_sell_dominance")) >= 0.6,
                _safe_float(bar.get("delta_bar")) < -50,
                _safe_float(bar.get("long_up_dn_pattern")) == 1.0,
            ]
        n_signals = sum(signals)
        log_fn("BN_V4_GATE_FOOTPRINT_BLOCK", sym=symbol, direction=direction,
                n_signals=n_signals)
        return None

    # 29/05 FIX BETA Jackson : anti stop-hunt momentum 60bars.
    # Apres tous les gates structurels (zone + volume + footprint), check
    # momentum 1h moyenne. Veto setup si slope contre-trend forte (pattern
    # "bounce dans downtrend" / "pullback dans uptrend").
    allow_momentum, slope_mean_60 = check_momentum_slope_60(
        df, i, direction, threshold=params.slope_mean_60_veto_threshold,
    )
    if not allow_momentum:
        log_fn("BN_V4_GATE_MOMENTUM_SLOPE_60_BLOCK", sym=symbol,
                direction=direction,
                slope_mean_60=round(slope_mean_60, 4) if slope_mean_60 is not None else None,
                threshold=params.slope_mean_60_veto_threshold)
        return None

    return dict(
        bar_idx=i,
        entry_price=float(bar["close"]),
        direction=direction,
        grade=zone["grade"],
        density=zone["density"],
        n_levels=zone["n_levels"],
        zone_bottom=zone["bottom_zone"],
        zone_top=zone["top_level"],
        ts_event=bar.get("ts_event"),
        mode=zone.get("mode", "TRADE"),    # NEW 23/05 : propage mode TRADE/OBSERVE
        slope_mean_60=round(slope_mean_60, 4) if slope_mean_60 is not None else None,  # 29/05 BETA
    )


def compute_initial_sl(setup: dict, entry_bar: Any, tick: float) -> float:
    """Calcule SL initial selon mode bottom (sous low/high bar entry).

    LONG : low(entry_bar) - 6 ticks
    SHORT : high(entry_bar) + 6 ticks
    """
    direction = setup["direction"]
    if direction == "long":
        return _safe_float(entry_bar.get("low")) - SL_INITIAL_BUFFER_TICKS * tick
    else:
        return _safe_float(entry_bar.get("high")) + SL_INITIAL_BUFFER_TICKS * tick


# ─── Engine facade ──────────────────────────────────────────────────────────

class BNV4Engine:
    """Facade unifiee pour usage paper live + backtest.

    Methodes principales :
      detect_setup(df_window, i, direction) -> Optional[Setup]
      compute_initial_sl(setup, entry_bar) -> float (SL price)
      make_trailing_state(direction, entry_bar, entry_price) -> TrailingState
      update_trailing(state, bar) -> Optional[float] (new SL price)
    """

    def __init__(self, params: Optional[BNV4Params] = None,
                  symbol: str = "NQ",
                  log_fn: Optional[Callable] = None):
        """
        Args:
            log_fn : Callable(code, **ctx) pour emit GATE_*_BLOCK / SETUP_DETECTED.
                     Default no-op. Caller paper trader injecte la vraie fonction
                     emit (via log_catalog). Fix VALIDATION_MISS code-reviewer 23/05.
        """
        self.params = params if params is not None else BNV4Params()
        self.symbol = symbol
        self.tick = TICK_SIZE.get(symbol, 0.25)
        self.log_fn = log_fn if log_fn is not None else _default_log_fn

    def detect_setup(self, df: pd.DataFrame, i: int,
                      direction: str) -> Optional[dict]:
        """Detecte un setup BN V4 a l'index i. df = rolling window.

        Args:
            df : DataFrame OHLCV + features (ts_event UTC, close, high, low,
                 vwap_slope_10, n_color_up_cluster_within_0_2pct,
                 n_long_up_cluster_within_0_2pct, n_edge_buy_active,
                 dist_*_pct, total_vol, long_up_bar, aggressor_imbalance,
                 big_buy_dominance, delta_bar)
            i : index courant dans df
            direction : "long" / "short"

        Returns:
            Setup dict si fire, None sinon. Emit GATE_*_BLOCK via log_fn
            sur chaque rejet.
        """
        if direction not in ("long", "short"):
            raise ValueError(f"direction invalide : {direction}")
        return check_setup(df, i, self.params, direction,
                            log_fn=self.log_fn, symbol=self.symbol)

    def compute_initial_sl(self, setup: dict, entry_bar: Any) -> float:
        """Calcule SL initial selon mode bottom."""
        return compute_initial_sl(setup, entry_bar, self.tick)

    def make_trailing_state(self, direction: str, entry_bar: Any,
                              entry_price: float,
                              entry_bar_idx: int = 0) -> TrailingState:
        """Init state machine trailing apres ouverture position.

        Raises:
            ValueError : OHLC NaN ou risk hors [min_risk_ticks, max_risk_ticks].
        """
        return make_trailing_state(direction, entry_bar, entry_price,
                                    self.tick, entry_bar_idx,
                                    max_risk_ticks=self.params.max_risk_ticks,
                                    min_risk_ticks=self.params.min_risk_ticks)

    def update_trailing(self, state: TrailingState,
                          bar: Any) -> Optional[float]:
        """Update state machine sur nouvelle bar. Returns new_sl si update.

        Raises:
            ValueError : OHLC NaN/None.
        """
        return update_trailing(state, bar)

    def is_timeout(self, state: TrailingState,
                    current_bar_ts_ns: int) -> bool:
        """True si position depasse timeout_bars (= 90 min en 1m bars).

        Fix P1.1 code-reviewer 23/05 : compare ts_event_ns (timestamp absolu)
        pas bar_idx (incompatible rolling window live).

        Args:
            state : TrailingState (entry_ts_ns set par make_trailing_state)
            current_bar_ts_ns : timestamp epoch ns de la bar courante.
        """
        if state.entry_ts_ns <= 0 or current_bar_ts_ns <= 0:
            # Fallback degraded : pas de ts -> jamais timeout (caller doit
            # gerer via duration explicite ou bar_idx).
            return False
        delta_min = (current_bar_ts_ns - state.entry_ts_ns) / 60_000_000_000
        return delta_min >= self.params.timeout_bars
