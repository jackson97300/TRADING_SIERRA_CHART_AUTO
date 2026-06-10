"""bn_v5_engine.py — Bataille Navale V5 (paradigme swing + trailing).

Difference fondamentale vs BN V4 :
  - BN V4 = 5 phases (trend + zone + density + edge + footprint) + entry "bottom"
    direct dans la zone + trail Dow pivots + fenetres open
  - BN V5 = detection PATTERN VISUEL V/W (LONG) + ∧/M (SHORT) + filtre
    confluence niveau institutionnel + bar reversal + filtre range + SL pivot
    direct + trailing Dow pullback

Backtest valide empiriquement (2026-06-02) :
  - ES MAI-JUN V LONG filtre 0.20% : PF 1.58 / Net +$1088 / N=13 / avg $84
  - Max win observe : $1675 (trailing capture le big TP)
  - Cible production : ~0.5-1 trade/jour ES + NQ combine

Architecture :
  - find_pivots : detection pivots low/high sur fenetre +-3 bars
  - detect_{v,w,inv_v,m} : detection des 4 patterns + cassure neckline
  - Filtres : confluence (proximite niveau inst), range (drift min), bar reversal
  - update_trailing : SL monte au low du dernier pullback confirme (3 bars sans new high)
  - check_zone : interface main (compatible avec bn_v4_paper.py poll_cycle)

Auteur : MIA Trading V2 v0.1 (2026-06-02 nuit)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, List, Dict, Tuple

import pandas as pd


# ════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ════════════════════════════════════════════════════════════════════════════

SIDE_LONG = "LONG"
SIDE_SHORT = "SHORT"

PATTERN_V = "V"
PATTERN_W = "W"
PATTERN_INV_V = "INV_V"
PATTERN_M = "M"

TICK_BY_SYMBOL = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
TICK_VAL_USD_BY_SYMBOL = {"NQ": 5.00, "ES": 12.50, "MGC": 1.00}  # ROLLBACK 03/06 : 1 NQ E-mini ($5/tick) + 1 ES E-mini ($12.50) + 1 MGC Micro.

# Colonnes confluence (LONG = proximite support, SHORT = proximite resistance)
# Toutes en _pct (% du prix) pour uniformite cross-symbol.
SUPPORT_COLS_LONG = (
    "dist_blind_nearest_dn_pct",
    "dist_mq_hvl_pct",
    "dist_mq_put_pct",
    "dist_vwap_d_sd1d_pct",
    "dist_gex_nearest_dn_pct",
)
RESIST_COLS_SHORT = (
    "dist_blind_nearest_up_pct",
    "dist_mq_call_pct",
    "dist_mq_call_0dte_pct",
    "dist_vwap_d_sd1u_pct",
    "dist_gex_nearest_up_pct",
)


# ════════════════════════════════════════════════════════════════════════════
# PARAMETRES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class BNV5Params:
    """Configuration BN V5. Defaults = backtest valide 2026-06-02."""

    # Detection pivots
    pivot_window: int = 3                   # +/- N bars pour pivot
    w_tolerance_ticks: int = 30             # tolerance LOW1/LOW2 du W (ou H1/H2 du M)
    lookback_neckline: int = 20             # max bars entre LOW1 et cassure neckline
    # 04/06 RECAL Jackson (sweet spot audit + R1 code-reviewer) :
    # 15 -> 7. Avec fix break->continue, br=15 captait des cassures k=6-7 mediane
    # (= entry tres apres pivot, "trades chers"). br=7 cap k <= 6 = cassures
    # rapides + sweet spot PF backtest 35j (ES 1.25, NQ 2.00, cumul +$21,183).
    breakout_max_bars: int = 7              # max bars apres LOW2 pour chercher cassure

    # Filtre confluence (proximite niveau institutionnel)
    confluence_max_dist_pct: float = 0.20   # pivot must be <= 0.20% d'un support/resistance

    # Filtre range (skip si consolidation)
    # 03/06 RECALIBRATION post-autopsie : 0.20% bloquait 96.6% des candidats
    # (max drift observe 0.199% sur 95K candidats today). Backtest 30j :
    # P75 NQ=0.138%, P75 ES=0.098% -> seuil 0.10% = compromis NQ/ES P75/P85.
    # Backtest D 30j : NQ N=18 PF 1.31 / ES N=21 PF 1.66.
    range_drift_min_pct: float = 0.10       # 0.20 -> 0.10 (compromis NQ/ES, recalibre 03/06)
    range_lookback_bars: int = 30

    # Bar reversal confirmation entry (3 niveaux empile-empilable)
    # Niveau 1 (min, toujours requis) : bar verte/rouge selon side
    # Niveau 2 (BASE, default ON) : delta_bar > 0 (LONG) ou < 0 (SHORT)
    # Niveau 3 (BONUS Jackson 02/06 SOIR) : aggressor_imbalance + long_*_bar
    bar_reversal_required: bool = True
    # 03/06 KILL CASCADE PATTERN 11 V1 :
    # Audit cascade reveler que F5 aggressor passe NQ 125 -> 0 bars (100% rejection)
    # ES 60 -> 2 (96.67%). Ajout 02/06 SOIR sans rebacktest = Pattern 11 V1 reproduit
    # (cf memory feedback_pattern11_repetition_avoided.md). Backtest config A FULL
    # defaults : 0 trades sur 30j. Config D sans aggressor : NQ 18 trades PF 1.31.
    # Disable les 2 bonus jusqu'a backtest post-fix montre PF > 1.5 sur 30j+.
    require_aggressor_confirm: bool = False  # True -> False (03/06 KILLER F5 elimine)
    aggressor_min_abs: float = 0.3           # inchange (inutilise tant que require=False)
    require_long_bar_confirm: bool = False   # True -> False (03/06 KILLER F6 idem)

    # SL / Trailing
    sl_pivot_direct: bool = True            # SL = pivot LOW/HIGH (pas de buffer)
    trail_pullback_bars: int = 3            # 3 bars sans new high = pullback confirme
    timeout_bars: int = 90                  # ~90 min swing

    # 🆕 FIX #A8 (08/06/2026) — DAILY STOP Mark Douglas
    # Source : memoire feedback_douglas_consistency_principles.md (04/06).
    # "Consistency beats intensity" - freeze apres seuil session atteint.
    # FIX B8.4 (code-reviewer 08/06) : threshold initial $150 win / $200 loss
    # trop serres pour 1 NQ E-mini ($5/t, 1 win 60t = $300 = trigger immediat).
    # Calibrage CONSERVATEUR : $300 win / $400 loss (= 1.3 SL typique avant freeze).
    # A backtester sur 30-60j BN V5 pour calibrer (backlog).
    daily_stop_win_usd: float = 300.0       # gain max session (1 win NQ typique)
    daily_stop_loss_usd: float = 400.0      # perte max session (~1.3 SL typiques)
    daily_stop_enabled: bool = True         # toggle desactivable

    # Activation patterns
    enable_v_long: bool = True
    enable_w_long: bool = True
    enable_inv_v_short: bool = False        # OFF par defaut (marginal MAI-JUN haussier)
    enable_m_short: bool = True             # ON (PF 8.00 ES MAI-JUN obs)

    # Min move size entry-pivot (anti-noise)
    min_entry_pivot_ticks: int = 5

    # 04/06 Jackson souverain : VETO proximity_swing symetrique LONG/SHORT.
    # LONG : refuser si dist(entry, last_swing_high) < threshold ET swing au-dessus.
    # SHORT : refuser si dist(entry, last_swing_low) < threshold ET swing en-dessous.
    # Source : feedback_swing_proximity_veto.md (11/05). Trade ES W LONG 04/06
    # @7547.5 vs swing_high 7549.75 = 2.25t (< 12t veto) = trade "par chance".
    # Defaults par symbole : ES 12t, NQ 30t, MGC 5t (calibrage tick spread).
    # Disable via enable_proximity_swing_veto=False pour A/B test backtest.
    enable_proximity_swing_veto: bool = True
    proximity_swing_veto_ticks: Dict[str, int] = field(
        default_factory=lambda: {"ES": 12, "NQ": 30, "MGC": 5}
    )
    # 04/06 R3 code-reviewer : lookback du veto pour limiter aux pivots
    # recents/pertinents. Sans ca, find_pivots() session-wide retourne 30+
    # pivots dont la majorite sont anciens et deja casses → micro-pic
    # ancien (ex: 7547.75 idx 80) masque le vrai swing problematique
    # (ex: 7549.75 idx 580). Limit aux N derniers bars = filtre temporel.
    proximity_swing_veto_lookback_bars: int = 60

    def __post_init__(self) -> None:
        assert self.pivot_window >= 2, "pivot_window doit etre >= 2"
        assert self.w_tolerance_ticks > 0
        assert self.lookback_neckline > 0
        assert self.confluence_max_dist_pct > 0
        assert self.range_drift_min_pct >= 0
        assert self.range_lookback_bars > 0
        assert self.trail_pullback_bars > 0
        assert self.timeout_bars > 0
        assert all(v > 0 for v in self.proximity_swing_veto_ticks.values()), \
            "proximity_swing_veto_ticks doit etre >0 par symbole"


# ════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Setup:
    """Setup BN V5 detecte (pre-execution)."""
    pattern: str            # V / W / INV_V / M
    side: str               # LONG / SHORT
    entry_idx: int          # index dans df de la bar entry
    entry_price: float
    sl_price: float         # SL initial = pivot LOW (LONG) ou HIGH (SHORT)
    pivot_price: float      # le pivot reference (low ou high)
    neckline: float         # niveau de cassure (pour audit)
    confluence_level: Optional[str] = None   # nom du niveau inst proche (debug)
    confluence_dist_pct: Optional[float] = None


@dataclass
class TrailingStateV5:
    """Etat trailing stop Dow pullback."""
    direction: str          # LONG / SHORT
    entry_idx: int
    entry_price: float
    sl_current: float
    sl_initial: float
    pivot_price: float

    # Running extremes
    running_high: float = 0.0    # LONG only
    running_low: float = 0.0     # SHORT only

    # Pullback tracking
    bars_since_new_extreme: int = 0
    candidate_pullback_extreme: Optional[float] = None  # low (LONG) ou high (SHORT) du pullback en cours
    last_confirmed_pullback: Optional[float] = None     # dernier pullback confirme = candidat SL

    # Stats
    mfe_ticks: float = 0.0  # nom legacy : valeurs en POINTS (cf B1.1 review)
    mae_ticks: float = 0.0
    # 🆕 FIX B1.2 (code-reviewer 08/06) - Tracking BE armed pour log audit
    breakeven_armed: bool = False  # True quand SL = entry (Fix A1) declenche


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _row_get(row: Any, col: str) -> Any:
    """Defensive accessor (dict ou pd.Series)."""
    if isinstance(row, dict):
        return row.get(col)
    try:
        return row[col]
    except (KeyError, AttributeError):
        return None


# ════════════════════════════════════════════════════════════════════════════
# DETECTION PIVOTS
# ════════════════════════════════════════════════════════════════════════════

def find_pivots(df: pd.DataFrame, window: int = 3) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Retourne (pivot_lows, pivot_highs) = [(idx, low/high), ...].

    Un pivot LOW i est tel que low[i] <= min(low[i-N:i]) ET low[i] <= min(low[i+1:i+N+1]).
    Idem miroir pour pivot HIGH.

    Args:
        df : DataFrame avec colonnes low, high
        window : N bars de chaque cote pour validation pivot (default 3)

    Returns:
        (pivot_lows, pivot_highs)
    """
    lows = df["low"].values
    highs = df["high"].values
    n = len(df)
    pl: List[Tuple[int, float]] = []
    ph: List[Tuple[int, float]] = []
    for i in range(window, n - window):
        if lows[i] <= lows[i - window:i].min() and lows[i] <= lows[i + 1:i + window + 1].min():
            pl.append((i, float(lows[i])))
        if highs[i] >= highs[i - window:i].max() and highs[i] >= highs[i + 1:i + window + 1].max():
            ph.append((i, float(highs[i])))
    return pl, ph


# ════════════════════════════════════════════════════════════════════════════
# FILTRES
# ════════════════════════════════════════════════════════════════════════════

def pivot_near_support(df: pd.DataFrame, idx: int, max_dist_pct: float) -> Tuple[bool, Optional[str], Optional[float]]:
    """Verifie si pivot LOW a idx est proche d'un support institutionnel.

    Returns:
        (is_near, col_name, dist_pct) — col_name et dist_pct utiles pour log.
    """
    best_col, best_dist = None, None
    for col in SUPPORT_COLS_LONG:
        if col not in df.columns:
            continue
        v = _safe_float(df[col].iloc[idx])
        if v is None:
            continue
        d = abs(v)
        if d <= max_dist_pct:
            if best_dist is None or d < best_dist:
                best_dist = d
                best_col = col
    return (best_col is not None, best_col, best_dist)


def pivot_near_resistance(df: pd.DataFrame, idx: int, max_dist_pct: float) -> Tuple[bool, Optional[str], Optional[float]]:
    """Idem support mais pour pivot HIGH proche resistance."""
    best_col, best_dist = None, None
    for col in RESIST_COLS_SHORT:
        if col not in df.columns:
            continue
        v = _safe_float(df[col].iloc[idx])
        if v is None:
            continue
        d = abs(v)
        if d <= max_dist_pct:
            if best_dist is None or d < best_dist:
                best_dist = d
                best_col = col
    return (best_col is not None, best_col, best_dist)


def range_filter_pass(df: pd.DataFrame, idx: int, drift_min_pct: float, lookback: int) -> Tuple[bool, float]:
    """True si le marche n'est PAS en range (drift suffisant) avant idx.

    Returns:
        (pass, drift_pct_observed)
    """
    if drift_min_pct <= 0:
        return (True, 0.0)
    start = max(0, idx - lookback)
    if start >= idx:
        return (False, 0.0)
    p0 = _safe_float(df["close"].iloc[start])
    p1 = _safe_float(df["close"].iloc[idx])
    if p0 is None or p1 is None or p0 <= 0:
        return (False, 0.0)
    drift_pct = abs(p1 - p0) / p0 * 100
    return (drift_pct >= drift_min_pct, drift_pct)


def bar_reversal_long(df: pd.DataFrame, idx: int,
                       require_aggressor: bool = False, aggressor_min: float = 0.3,
                       require_long_bar: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Bar entry pour LONG : close>open + delta_bar>0 + BONUS aggressor + long_up_bar.

    Niveaux empile-empilables :
      1. (toujours) close > open
      2. (toujours) delta_bar > 0 si dispo (sinon OK)
      3. (require_aggressor) aggressor_imbalance >= aggressor_min si dispo
      4. (require_long_bar) long_up_bar == 1 si dispo

    Returns:
        (pass, debug_dict)
    """
    o = _safe_float(df["open"].iloc[idx])
    c = _safe_float(df["close"].iloc[idx])
    if o is None or c is None or c <= o:
        return (False, {"close": c, "open": o, "reason": "not_green"})

    # Niveau 2 : delta_bar
    delta_val = None
    if "delta_bar" in df.columns:
        d = _safe_float(df["delta_bar"].iloc[idx])
        if d is not None:
            delta_val = d
            if d <= 0:
                return (False, {"close": c, "open": o, "delta_bar": d, "reason": "delta_negative"})

    # Niveau 3 BONUS : aggressor_imbalance
    aggressor_val = None
    if require_aggressor and "aggressor_imbalance" in df.columns:
        a = _safe_float(df["aggressor_imbalance"].iloc[idx])
        if a is not None:
            aggressor_val = a
            if a < aggressor_min:
                return (False, {"close": c, "open": o, "delta_bar": delta_val,
                                "aggressor_imbalance": a, "aggressor_min": aggressor_min,
                                "reason": "aggressor_weak"})

    # Niveau 4 BONUS : long_up_bar
    long_bar_val = None
    if require_long_bar and "long_up_bar" in df.columns:
        lub = _safe_float(df["long_up_bar"].iloc[idx])
        if lub is not None:
            long_bar_val = int(lub)
            if long_bar_val < 1:
                return (False, {"close": c, "open": o, "delta_bar": delta_val,
                                "aggressor_imbalance": aggressor_val,
                                "long_up_bar": long_bar_val,
                                "reason": "no_long_up_bar"})

    return (True, {"close": c, "open": o, "delta_bar": delta_val,
                   "aggressor_imbalance": aggressor_val,
                   "long_up_bar": long_bar_val})


def proximity_swing_check(df: pd.DataFrame, idx: int, side: str, sym: str,
                          threshold_ticks: int,
                          internal_pivots: Optional[List[Tuple[int, float]]] = None,
                          pivot_window: int = 3,
                          lookback_bars: int = 60,
                          ) -> Tuple[bool, Dict[str, Any]]:
    """Veto symetrique : refuse entry trop proche d'un swing oppose.

    LONG : refuse si UN DES SWING HIGHS suivants est AU-DESSUS de entry et
           dist(entry, swing_high) < threshold_ticks :
             1. `_last_swing_high_price` enricher (session-level)
             2. plus haut des pivot_highs INTERNES find_pivots BN V5 (court terme)
    SHORT : miroir avec swing_lows.

    Returns:
        (passes, ctx_dict). passes=True si OK (pas de veto).

    Le veto est STRICT : si UN seul swing recent est dans la zone, on REJETTE.
    Couvre 2 plages temporelles complementaires :
      - enricher = swings confirmes session (lent mais robuste)
      - internal_pivots = pivots find_pivots window=3 (rapide mais bruite)

    Cas decouvert 04/06 : trade ES 9:47 LONG @7547.5 alors qu'un pic 7549.75
    se formait 1-2 bars avant. L'enricher ne l'avait pas encore reclassifie
    comme `_last_swing_high_price` (toujours 7537.5 = swing precedent casse).
    Les internal_pivots BN V5 le voient car window=3.

    Fail-open : si le swing n'existe pas (None) ou est deja casse (sous entry
    pour LONG / au-dessus pour SHORT), on PASSE pour ce swing.

    Args:
        df : DataFrame OHLC + `_last_swing_high_price` + `_last_swing_low_price`
        idx : index bar entry
        side : SIDE_LONG / SIDE_SHORT
        sym : NQ / ES / MGC
        threshold_ticks : distance min en ticks
        internal_pivots : optionnel, pivots find_pivots BN V5 du window courant.
                          Pour LONG passer ph, pour SHORT passer pl.

    Source : Jackson 11/05 + 04/06 (multi-source).
    """
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    if idx < 0 or idx >= len(df):
        return (True, {"reason": "idx_out_of_bounds"})
    row = df.iloc[idx]
    entry = _safe_float(_row_get(row, "close"))
    if entry is None:
        return (True, {"reason": "entry_none"})

    candidates: List[Tuple[str, float]] = []  # (source_label, price)
    # 04/06 R2 code-reviewer : un pivot a pidx n'est confirme qu'a partir de
    # `pidx + pivot_window + 1` (find_pivots scan bars apres). En live, un
    # pivot a pidx=N-1 n'existe PAS encore pour le bot. Filtre anti look-ahead.
    # 04/06 R3 : lookback temporel pour eviter micro-pics anciens deja casses.
    min_idx_pivot_recent = max(0, idx - lookback_bars)

    if side == SIDE_LONG:
        # Source 1 : enricher
        sh_enricher = _safe_float(_row_get(row, "_last_swing_high_price"))
        if sh_enricher is not None and sh_enricher > entry:
            candidates.append(("enricher", sh_enricher))
        # Source 2 : internal pivots (ph) confirmes ET dans lookback recent,
        # AU-DESSUS de entry.
        if internal_pivots:
            for pidx, pprice in internal_pivots:
                # R2 : pivot pas confirmable si pas assez de bars apres
                if pidx + pivot_window >= idx:
                    continue
                # R3 : pivot trop ancien, deja casse ou non-pertinent
                if pidx < min_idx_pivot_recent:
                    continue
                if pprice > entry:
                    candidates.append((f"internal_idx{pidx}", pprice))

        if not candidates:
            return (True, {"swing_price": None,
                           "reason": "no_swing_high_above_entry"})
        # Le swing le PLUS PROCHE en distance verticale est le plus contraignant
        candidates.sort(key=lambda c: c[1] - entry)
        src, sh = candidates[0]
        dist_pts = sh - entry
        dist_ticks = dist_pts / tick
        ctx = {
            "swing_price": round(sh, 4),
            "swing_source": src,
            "dist_ticks": round(dist_ticks, 2),
            "threshold_ticks": threshold_ticks,
            "n_candidates": len(candidates),
        }
        return (dist_ticks >= threshold_ticks, ctx)

    # SHORT
    sl_enricher = _safe_float(_row_get(row, "_last_swing_low_price"))
    if sl_enricher is not None and sl_enricher < entry:
        candidates.append(("enricher", sl_enricher))
    if internal_pivots:
        for pidx, pprice in internal_pivots:
            # R2 anti look-ahead
            if pidx + pivot_window >= idx:
                continue
            # R3 lookback temporel
            if pidx < min_idx_pivot_recent:
                continue
            if pprice < entry:
                candidates.append((f"internal_idx{pidx}", pprice))

    if not candidates:
        return (True, {"swing_price": None,
                       "reason": "no_swing_low_below_entry"})
    # Le swing le plus proche par dessous = entry - max(price)
    candidates.sort(key=lambda c: entry - c[1])
    src, sl_swing = candidates[0]
    dist_pts = entry - sl_swing
    dist_ticks = dist_pts / tick
    ctx = {
        "swing_price": round(sl_swing, 4),
        "swing_source": src,
        "dist_ticks": round(dist_ticks, 2),
        "threshold_ticks": threshold_ticks,
        "n_candidates": len(candidates),
    }
    return (dist_ticks >= threshold_ticks, ctx)


def bar_reversal_short(df: pd.DataFrame, idx: int,
                        require_aggressor: bool = False, aggressor_min: float = 0.3,
                        require_long_bar: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Miroir pour SHORT : bar rouge + delta<0 + aggressor<=-min + long_dn_bar=1."""
    o = _safe_float(df["open"].iloc[idx])
    c = _safe_float(df["close"].iloc[idx])
    if o is None or c is None or c >= o:
        return (False, {"close": c, "open": o, "reason": "not_red"})

    delta_val = None
    if "delta_bar" in df.columns:
        d = _safe_float(df["delta_bar"].iloc[idx])
        if d is not None:
            delta_val = d
            if d >= 0:
                return (False, {"close": c, "open": o, "delta_bar": d, "reason": "delta_positive"})

    aggressor_val = None
    if require_aggressor and "aggressor_imbalance" in df.columns:
        a = _safe_float(df["aggressor_imbalance"].iloc[idx])
        if a is not None:
            aggressor_val = a
            if a > -aggressor_min:
                return (False, {"close": c, "open": o, "delta_bar": delta_val,
                                "aggressor_imbalance": a, "aggressor_min_neg": -aggressor_min,
                                "reason": "aggressor_weak"})

    long_bar_val = None
    if require_long_bar and "long_dn_bar" in df.columns:
        ldb = _safe_float(df["long_dn_bar"].iloc[idx])
        if ldb is not None:
            long_bar_val = int(ldb)
            if long_bar_val < 1:
                return (False, {"close": c, "open": o, "delta_bar": delta_val,
                                "aggressor_imbalance": aggressor_val,
                                "long_dn_bar": long_bar_val,
                                "reason": "no_long_dn_bar"})

    return (True, {"close": c, "open": o, "delta_bar": delta_val,
                   "aggressor_imbalance": aggressor_val,
                   "long_dn_bar": long_bar_val})


# ════════════════════════════════════════════════════════════════════════════
# DETECTION PATTERNS V / W / ∧ / M
# ════════════════════════════════════════════════════════════════════════════

def detect_v_long(
    df: pd.DataFrame,
    pl: List[Tuple[int, float]],
    sym: str,
    params: BNV5Params,
    log_fn: Optional[Callable] = None,
) -> List[Setup]:
    """V LONG : 1 pivot low + cassure rapide du high local."""
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    setups: List[Setup] = []
    n = len(df)
    used = set()
    for idx_low, low_val in pl:
        if idx_low in used:
            continue
        # Filtre confluence
        is_near, lvl, dist = pivot_near_support(df, idx_low, params.confluence_max_dist_pct)
        if not is_near:
            # 04/06 P1 R2 : emit CONFLUENCE_BLOCK pour tracabilite (avant: silent continue)
            if log_fn is not None:
                try:
                    log_fn("BN_V5_GATE_CONFLUENCE_BLOCK",
                           sym=sym, pattern="V_LONG",
                           dist_pct=round(dist, 4) if dist is not None else None,
                           threshold=params.confluence_max_dist_pct,
                           nearest_level=lvl)
                except Exception:
                    pass
            continue
        # Chercher cassure
        for k in range(idx_low + 1, min(idx_low + params.breakout_max_bars, n)):
            mid_slice = df.iloc[idx_low:k + 1]
            neckline = float(mid_slice["high"].max())
            if k + 1 >= n:
                break
            next_high = _safe_float(df["high"].iloc[k + 1])
            if next_high is None:
                continue
            if next_high > neckline:
                entry_idx = k + 1
                entry_price = _safe_float(df["close"].iloc[entry_idx])
                if entry_price is None or (entry_price - low_val) < params.min_entry_pivot_ticks * tick:
                    break
                # Filtre range
                # 04/06 FIX (market-analyst review) : continue au lieu de break.
                # Si cassure k bloquee par range_filter, tenter cassures k+1, k+2...
                # Neckline grandit avec high cumule -> cassure ulterieure = plus
                # forte. Backtest 35j : ES x2.7 trades, NQ x4.2 trades, PnL+.
                rng_ok, drift = range_filter_pass(df, entry_idx, params.range_drift_min_pct, params.range_lookback_bars)
                if not rng_ok:
                    if log_fn is not None:
                        try:
                            log_fn("BN_V5_GATE_RANGE_BLOCK",
                                   sym=sym, pattern="V_LONG", entry_idx=entry_idx,
                                   drift_pct=round(drift, 3), threshold=params.range_drift_min_pct)
                        except Exception:
                            pass
                    continue
                # Filtre bar reversal
                if params.bar_reversal_required:
                    rev_ok, rev_ctx = bar_reversal_long(df, entry_idx, require_aggressor=params.require_aggressor_confirm, aggressor_min=params.aggressor_min_abs, require_long_bar=params.require_long_bar_confirm)
                    if not rev_ok:
                        if log_fn is not None:
                            try:
                                log_fn("BN_V5_GATE_BAR_REVERSAL_BLOCK",
                                       sym=sym, pattern="V_LONG", entry_idx=entry_idx,
                                       **{k: v for k, v in rev_ctx.items() if v is not None})
                            except Exception:
                                pass
                        continue
                setups.append(Setup(
                    pattern=PATTERN_V, side=SIDE_LONG,
                    entry_idx=entry_idx, entry_price=entry_price,
                    sl_price=low_val, pivot_price=low_val, neckline=neckline,
                    confluence_level=lvl, confluence_dist_pct=dist,
                ))
                used.add(idx_low)
                break
    return setups


def detect_w_long(
    df: pd.DataFrame,
    pl: List[Tuple[int, float]],
    sym: str,
    params: BNV5Params,
    log_fn: Optional[Callable] = None,
) -> List[Setup]:
    """W LONG : 2 pivots low dans tolerance + cassure midpoint."""
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    tol_pts = params.w_tolerance_ticks * tick
    setups: List[Setup] = []
    n = len(df)
    for i, (idx1, low1) in enumerate(pl):
        # Filtre confluence sur LOW1
        is_near, lvl, dist = pivot_near_support(df, idx1, params.confluence_max_dist_pct)
        if not is_near:
            if log_fn is not None:
                try:
                    log_fn("BN_V5_GATE_CONFLUENCE_BLOCK",
                           sym=sym, pattern="W_LONG",
                           dist_pct=round(dist, 4) if dist is not None else None,
                           threshold=params.confluence_max_dist_pct,
                           nearest_level=lvl)
                except Exception:
                    pass
            continue
        for j in range(i + 1, len(pl)):
            idx2, low2 = pl[j]
            if idx2 - idx1 > params.lookback_neckline:
                break
            if abs(low2 - low1) > tol_pts:
                continue
            mid_slice = df.iloc[idx1:idx2 + 1]
            neckline = float(mid_slice["high"].max())
            for k in range(idx2 + 1, min(idx2 + params.breakout_max_bars, n)):
                bar_high = _safe_float(df["high"].iloc[k])
                if bar_high is None:
                    continue
                if bar_high > neckline:
                    entry_idx = k
                    entry_price = _safe_float(df["close"].iloc[entry_idx])
                    sl_pivot = min(low1, low2)
                    if entry_price is None or (entry_price - sl_pivot) < params.min_entry_pivot_ticks * tick:
                        break
                    # 04/06 FIX (market-analyst review) : continue au lieu de break.
                    rng_ok, drift = range_filter_pass(df, entry_idx, params.range_drift_min_pct, params.range_lookback_bars)
                    if not rng_ok:
                        if log_fn is not None:
                            try:
                                log_fn("BN_V5_GATE_RANGE_BLOCK",
                                       sym=sym, pattern="W_LONG", entry_idx=entry_idx,
                                       drift_pct=round(drift, 3), threshold=params.range_drift_min_pct)
                            except Exception:
                                pass
                        continue
                    if params.bar_reversal_required:
                        rev_ok, rev_ctx = bar_reversal_long(df, entry_idx, require_aggressor=params.require_aggressor_confirm, aggressor_min=params.aggressor_min_abs, require_long_bar=params.require_long_bar_confirm)
                        if not rev_ok:
                            if log_fn is not None:
                                try:
                                    log_fn("BN_V5_GATE_BAR_REVERSAL_BLOCK",
                                           sym=sym, pattern="W_LONG", entry_idx=entry_idx,
                                           **{k: v for k, v in rev_ctx.items() if v is not None})
                                except Exception:
                                    pass
                            continue
                    setups.append(Setup(
                        pattern=PATTERN_W, side=SIDE_LONG,
                        entry_idx=entry_idx, entry_price=entry_price,
                        sl_price=sl_pivot, pivot_price=sl_pivot, neckline=neckline,
                        confluence_level=lvl, confluence_dist_pct=dist,
                    ))
                    break
            break  # 1 W par LOW1
    return setups


def detect_inv_v_short(
    df: pd.DataFrame,
    ph: List[Tuple[int, float]],
    sym: str,
    params: BNV5Params,
    log_fn: Optional[Callable] = None,
) -> List[Setup]:
    """∧ SHORT : miroir V."""
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    setups: List[Setup] = []
    n = len(df)
    used = set()
    for idx_h, h_val in ph:
        if idx_h in used:
            continue
        is_near, lvl, dist = pivot_near_resistance(df, idx_h, params.confluence_max_dist_pct)
        if not is_near:
            if log_fn is not None:
                try:
                    log_fn("BN_V5_GATE_CONFLUENCE_BLOCK",
                           sym=sym, pattern="INV_V_SHORT",
                           dist_pct=round(dist, 4) if dist is not None else None,
                           threshold=params.confluence_max_dist_pct,
                           nearest_level=lvl)
                except Exception:
                    pass
            continue
        for k in range(idx_h + 1, min(idx_h + params.breakout_max_bars, n)):
            mid_slice = df.iloc[idx_h:k + 1]
            neckline = float(mid_slice["low"].min())
            if k + 1 >= n:
                break
            next_low = _safe_float(df["low"].iloc[k + 1])
            if next_low is None:
                continue
            if next_low < neckline:
                entry_idx = k + 1
                entry_price = _safe_float(df["close"].iloc[entry_idx])
                if entry_price is None or (h_val - entry_price) < params.min_entry_pivot_ticks * tick:
                    break
                # 04/06 FIX (market-analyst review) : continue au lieu de break.
                rng_ok, drift = range_filter_pass(df, entry_idx, params.range_drift_min_pct, params.range_lookback_bars)
                if not rng_ok:
                    if log_fn is not None:
                        try:
                            log_fn("BN_V5_GATE_RANGE_BLOCK",
                                   sym=sym, pattern="INV_V_SHORT", entry_idx=entry_idx,
                                   drift_pct=round(drift, 3), threshold=params.range_drift_min_pct)
                        except Exception:
                            pass
                    continue
                if params.bar_reversal_required:
                    rev_ok, rev_ctx = bar_reversal_short(df, entry_idx, require_aggressor=params.require_aggressor_confirm, aggressor_min=params.aggressor_min_abs, require_long_bar=params.require_long_bar_confirm)
                    if not rev_ok:
                        if log_fn is not None:
                            try:
                                log_fn("BN_V5_GATE_BAR_REVERSAL_BLOCK",
                                       sym=sym, pattern="INV_V_SHORT", entry_idx=entry_idx,
                                       **{k: v for k, v in rev_ctx.items() if v is not None})
                            except Exception:
                                pass
                        continue
                setups.append(Setup(
                    pattern=PATTERN_INV_V, side=SIDE_SHORT,
                    entry_idx=entry_idx, entry_price=entry_price,
                    sl_price=h_val, pivot_price=h_val, neckline=neckline,
                    confluence_level=lvl, confluence_dist_pct=dist,
                ))
                used.add(idx_h)
                break
    return setups


def detect_m_short(
    df: pd.DataFrame,
    ph: List[Tuple[int, float]],
    sym: str,
    params: BNV5Params,
    log_fn: Optional[Callable] = None,
) -> List[Setup]:
    """M SHORT : miroir W."""
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    tol_pts = params.w_tolerance_ticks * tick
    setups: List[Setup] = []
    n = len(df)
    for i, (idx1, h1) in enumerate(ph):
        is_near, lvl, dist = pivot_near_resistance(df, idx1, params.confluence_max_dist_pct)
        if not is_near:
            if log_fn is not None:
                try:
                    log_fn("BN_V5_GATE_CONFLUENCE_BLOCK",
                           sym=sym, pattern="M_SHORT",
                           dist_pct=round(dist, 4) if dist is not None else None,
                           threshold=params.confluence_max_dist_pct,
                           nearest_level=lvl)
                except Exception:
                    pass
            continue
        for j in range(i + 1, len(ph)):
            idx2, h2 = ph[j]
            if idx2 - idx1 > params.lookback_neckline:
                break
            if abs(h2 - h1) > tol_pts:
                continue
            mid_slice = df.iloc[idx1:idx2 + 1]
            neckline = float(mid_slice["low"].min())
            for k in range(idx2 + 1, min(idx2 + params.breakout_max_bars, n)):
                bar_low = _safe_float(df["low"].iloc[k])
                if bar_low is None:
                    continue
                if bar_low < neckline:
                    entry_idx = k
                    entry_price = _safe_float(df["close"].iloc[entry_idx])
                    sl_pivot = max(h1, h2)
                    if entry_price is None or (sl_pivot - entry_price) < params.min_entry_pivot_ticks * tick:
                        break
                    # 04/06 FIX (market-analyst review) : continue au lieu de break.
                    rng_ok, drift = range_filter_pass(df, entry_idx, params.range_drift_min_pct, params.range_lookback_bars)
                    if not rng_ok:
                        if log_fn is not None:
                            try:
                                log_fn("BN_V5_GATE_RANGE_BLOCK",
                                       sym=sym, pattern="M_SHORT", entry_idx=entry_idx,
                                       drift_pct=round(drift, 3), threshold=params.range_drift_min_pct)
                            except Exception:
                                pass
                        continue
                    if params.bar_reversal_required:
                        rev_ok, rev_ctx = bar_reversal_short(df, entry_idx, require_aggressor=params.require_aggressor_confirm, aggressor_min=params.aggressor_min_abs, require_long_bar=params.require_long_bar_confirm)
                        if not rev_ok:
                            if log_fn is not None:
                                try:
                                    log_fn("BN_V5_GATE_BAR_REVERSAL_BLOCK",
                                           sym=sym, pattern="M_SHORT", entry_idx=entry_idx,
                                           **{k: v for k, v in rev_ctx.items() if v is not None})
                                except Exception:
                                    pass
                            continue
                    setups.append(Setup(
                        pattern=PATTERN_M, side=SIDE_SHORT,
                        entry_idx=entry_idx, entry_price=entry_price,
                        sl_price=sl_pivot, pivot_price=sl_pivot, neckline=neckline,
                        confluence_level=lvl, confluence_dist_pct=dist,
                    ))
                    break
            break
    return setups


# ════════════════════════════════════════════════════════════════════════════
# TRAILING STOP (Dow style)
# ════════════════════════════════════════════════════════════════════════════

def init_trailing(setup: Setup) -> TrailingStateV5:
    """Crée l'etat trailing initial."""
    state = TrailingStateV5(
        direction=setup.side,
        entry_idx=setup.entry_idx,
        entry_price=setup.entry_price,
        sl_current=setup.sl_price,
        sl_initial=setup.sl_price,
        pivot_price=setup.pivot_price,
    )
    if setup.side == SIDE_LONG:
        state.running_high = setup.entry_price
    else:
        state.running_low = setup.entry_price
    return state


def update_trailing(state: TrailingStateV5, bar: Any, trail_pullback_bars: int = 3) -> Optional[float]:
    """Met a jour le trailing en lisant 1 bar.

    Args:
        state : TrailingStateV5 (mute en place)
        bar : dict ou pd.Series avec high, low, close
        trail_pullback_bars : N bars sans new extreme = pullback confirme

    Returns:
        nouveau sl_current si update OR None si SL inchange.
    """
    h = _safe_float(_row_get(bar, "high"))
    l = _safe_float(_row_get(bar, "low"))
    if h is None or l is None:
        return None

    # MFE/MAE tracking
    if state.direction == SIDE_LONG:
        excursion_up = h - state.entry_price
        excursion_dn = l - state.entry_price
        if excursion_up > state.mfe_ticks:
            state.mfe_ticks = excursion_up
        if excursion_dn < state.mae_ticks:
            state.mae_ticks = excursion_dn
    else:
        excursion_up = state.entry_price - l   # SHORT mfe = mvt baisse
        excursion_dn = state.entry_price - h
        if excursion_up > state.mfe_ticks:
            state.mfe_ticks = excursion_up
        if excursion_dn < state.mae_ticks:
            state.mae_ticks = excursion_dn

    # 🆕 FIX #A1 (08/06/2026) — BREAKEVEN A +1R
    # Audit BN V5 4 SL ce matin 08/06 : 100% avec MFE >= risk initial puis rendu.
    # T1 MFE 58t / R 51t = 114%, T2 MFE 78t / R 42t = 186%, T3 MFE 67t / R 86t = 78%.
    # Trail Dow pullback ne protege que sur new_high apres pullback confirme. Sur
    # V-reversal post-MFE, le trail reste fige et rend tout.
    # Fix : des que MFE >= risk_initial atteint (= +1R), locker SL = entry.
    # Risque pattern 11 = FAIBLE (regle universelle pro).
    # Note : mfe_ticks et risk_pts sont tous deux en POINTS (excursion = h - entry).
    risk_pts = abs(state.entry_price - state.sl_initial)
    if risk_pts > 0 and state.mfe_ticks >= risk_pts and not state.breakeven_armed:
        if state.direction == SIDE_LONG and state.entry_price > state.sl_current:
            state.sl_current = state.entry_price
            state.breakeven_armed = True
            return state.entry_price  # signal SL update vers BE
        elif state.direction == SIDE_SHORT and state.entry_price < state.sl_current:
            state.sl_current = state.entry_price
            state.breakeven_armed = True
            return state.entry_price

    if state.direction == SIDE_LONG:
        if h > state.running_high:
            # New high : on update SL au dernier pullback confirme (s'il existe)
            new_sl = None
            if state.last_confirmed_pullback is not None and state.last_confirmed_pullback > state.sl_current:
                state.sl_current = state.last_confirmed_pullback
                new_sl = state.sl_current
            state.running_high = h
            state.bars_since_new_extreme = 0
            state.candidate_pullback_extreme = None
            return new_sl
        else:
            state.bars_since_new_extreme += 1
            if state.candidate_pullback_extreme is None or l < state.candidate_pullback_extreme:
                state.candidate_pullback_extreme = l
            if (state.bars_since_new_extreme >= trail_pullback_bars
                    and state.candidate_pullback_extreme is not None):
                state.last_confirmed_pullback = state.candidate_pullback_extreme
            return None
    else:  # SHORT
        if l < state.running_low:
            new_sl = None
            if state.last_confirmed_pullback is not None and state.last_confirmed_pullback < state.sl_current:
                state.sl_current = state.last_confirmed_pullback
                new_sl = state.sl_current
            state.running_low = l
            state.bars_since_new_extreme = 0
            state.candidate_pullback_extreme = None
            return new_sl
        else:
            state.bars_since_new_extreme += 1
            if state.candidate_pullback_extreme is None or h > state.candidate_pullback_extreme:
                state.candidate_pullback_extreme = h
            if (state.bars_since_new_extreme >= trail_pullback_bars
                    and state.candidate_pullback_extreme is not None):
                state.last_confirmed_pullback = state.candidate_pullback_extreme
            return None


def is_sl_hit(state: TrailingStateV5, bar: Any) -> bool:
    """True si la bar courante a touche le SL."""
    h = _safe_float(_row_get(bar, "high"))
    l = _safe_float(_row_get(bar, "low"))
    if h is None or l is None:
        return False
    if state.direction == SIDE_LONG:
        return l <= state.sl_current
    return h >= state.sl_current


def is_timeout(state: TrailingStateV5, current_idx: int, timeout_bars: int) -> bool:
    return (current_idx - state.entry_idx) >= timeout_bars


# ════════════════════════════════════════════════════════════════════════════
# INTERFACE PRINCIPALE
# ════════════════════════════════════════════════════════════════════════════

class BNV5Engine:
    """Moteur BN V5 — detection patterns V/W/∧/M sur fenetre rolling.

    Usage paper trader :
        engine = BNV5Engine(symbol="NQ", params=BNV5Params())
        for chaque cycle :
            setup = engine.check_zone(df_window, idx_courant)
            if setup is not None : execute trade
    """

    def __init__(self, symbol: str, params: Optional[BNV5Params] = None,
                 log_fn: Optional[Callable] = None) -> None:
        assert symbol in TICK_BY_SYMBOL, f"Symbol non supporte : {symbol}"
        self.symbol = symbol
        self.params = params or BNV5Params()
        # FIX BUG CRITIQUE 04/06 : wrapper log_fn qui incremente _n_filtered_*
        # AVANT : les counters etaient declares + reset mais JAMAIS incrementes.
        # CYCLE_SUMMARY rapportait n_filt_range=0 alors que 39629 GATE_RANGE_BLOCK
        # emit / 04/06. Le wrapper compte les emit BN_V5_GATE_*_BLOCK et alimente
        # les counters utilises dans CYCLE_SUMMARY (qui devient maintenant honnete).
        self._raw_log_fn = log_fn

        # Stats (incremente via _counting_log_fn wrapper)
        self._n_bars_processed = 0
        self._n_setups_detected = 0
        self._n_filtered_range = 0
        self._n_filtered_confluence = 0
        self._n_filtered_bar_reversal = 0
        self._n_filtered_proximity_swing = 0  # 04/06 veto Jackson

        # 04/06 R1 code-reviewer : TOUJOURS wrap (meme si log_fn=None) sinon
        # les counters seraient muets et CYCLE_SUMMARY mentirait quand un caller
        # (test, dev script) instancie sans log_fn externe. La compatibilite
        # avec la prod est preservee (raw_log_fn peut etre None, _emit en prod).
        def _counting_log_fn(code: str, **ctx) -> None:
            if code == "BN_V5_GATE_RANGE_BLOCK":
                self._n_filtered_range += 1
            elif code == "BN_V5_GATE_BAR_REVERSAL_BLOCK":
                self._n_filtered_bar_reversal += 1
            elif code == "BN_V5_GATE_CONFLUENCE_BLOCK":
                self._n_filtered_confluence += 1
            elif code == "BN_V5_GATE_PROXIMITY_SWING_BLOCK":
                self._n_filtered_proximity_swing += 1
            # Forward au raw log_fn original (peut etre None)
            if self._raw_log_fn is not None:
                try:
                    self._raw_log_fn(code, **ctx)
                except Exception:
                    pass

        self.log_fn = _counting_log_fn  # R1 : toujours wrap (counters honnetes)

    def check_zone(self, df: pd.DataFrame, current_idx: int) -> Optional[Setup]:
        """Detecte si la bar courante (current_idx) declenche un setup BN V5.

        Args:
            df : DataFrame avec OHLC + colonnes _pct confluence + delta_bar
            current_idx : index de la bar courante (= last bar du window)

        Returns:
            Setup detecte (entry_idx == current_idx) ou None.
        """
        self._n_bars_processed += 1

        pl, ph = find_pivots(df, window=self.params.pivot_window)

        # 04/06 P1 — BAR_PROCESSED + PIVOT_DETECTED pour tracking granulaire.
        # Permet a Jackson de tail decisions et voir drift_pct par bar (cassure
        # potentielle) + pivots fraichement detectes.
        if self.log_fn is not None:
            try:
                close_val = _safe_float(df["close"].iloc[current_idx]) if current_idx < len(df) else None
                # drift_pct calcule pour le filtre range : (high-low)/close sur lookback
                _, drift_curr = range_filter_pass(
                    df, current_idx, 0.0, self.params.range_lookback_bars
                )
                atr_val = None
                try:
                    if "atr" in df.columns and current_idx < len(df):
                        atr_val = _safe_float(df["atr"].iloc[current_idx])
                except Exception:
                    atr_val = None
                self.log_fn("BN_V5_BAR_PROCESSED",
                            sym=self.symbol, idx=current_idx,
                            close=round(close_val, 4) if close_val is not None else None,
                            drift_pct=round(drift_curr, 4) if drift_curr is not None else None,
                            atr=round(atr_val, 2) if atr_val is not None else None)
            except Exception:
                pass

        all_setups: List[Setup] = []
        n_cand_v = n_cand_w = n_cand_inv_v = n_cand_m = 0
        if self.params.enable_v_long and pl:
            v_setups = detect_v_long(df, pl, self.symbol, self.params, self.log_fn)
            n_cand_v = len(v_setups)
            all_setups.extend(v_setups)
        if self.params.enable_w_long and pl:
            w_setups = detect_w_long(df, pl, self.symbol, self.params, self.log_fn)
            n_cand_w = len(w_setups)
            all_setups.extend(w_setups)
        if self.params.enable_inv_v_short and ph:
            iv_setups = detect_inv_v_short(df, ph, self.symbol, self.params, self.log_fn)
            n_cand_inv_v = len(iv_setups)
            all_setups.extend(iv_setups)
        if self.params.enable_m_short and ph:
            m_setups = detect_m_short(df, ph, self.symbol, self.params, self.log_fn)
            n_cand_m = len(m_setups)
            all_setups.extend(m_setups)

        # Cycle summary (Jackson 02/06 SOIR : "on doit tout tracker")
        # Emit toutes les 10 bars pour ne pas spammer
        if self.log_fn is not None and self._n_bars_processed % 10 == 0:
            try:
                self.log_fn("BN_V5_CYCLE_SUMMARY",
                            sym=self.symbol,
                            n_bars_in_window=len(df),
                            n_pivot_lows=len(pl), n_pivot_highs=len(ph),
                            n_cand_v=n_cand_v, n_cand_w=n_cand_w,
                            n_cand_inv_v=n_cand_inv_v, n_cand_m=n_cand_m,
                            n_filt_conf=self._n_filtered_confluence,
                            n_filt_range=self._n_filtered_range,
                            n_filt_bar=self._n_filtered_bar_reversal,
                            n_filt_prox=self._n_filtered_proximity_swing,
                            n_setups=self._n_setups_detected)
            except Exception:
                pass

        # Filtre : seulement setups avec entry_idx == current_idx (= cassure NOW)
        for s in all_setups:
            if s.entry_idx != current_idx:
                continue

            # 04/06 VETO proximity_swing (Jackson souverain) — symetrique LONG/SHORT.
            # LONG : refuse si swing_high recent < entry + threshold ticks.
            # SHORT : refuse si swing_low recent > entry - threshold ticks.
            # 2 sources verifiees : `_last_swing_high_price` enricher (lent)
            # + internal pivots find_pivots() BN V5 (rapide window=3).
            # Source : feedback_swing_proximity_veto.md (11/05) + trade ES 04/06.
            if self.params.enable_proximity_swing_veto:
                thr = self.params.proximity_swing_veto_ticks.get(self.symbol, 12)
                # LONG check vs swing highs (ph), SHORT check vs swing lows (pl)
                internal_for_check = ph if s.side == SIDE_LONG else pl
                ok, ctx = proximity_swing_check(
                    df, s.entry_idx, s.side, self.symbol, thr,
                    internal_pivots=internal_for_check,
                    pivot_window=self.params.pivot_window,
                    lookback_bars=self.params.proximity_swing_veto_lookback_bars,
                )
                if not ok:
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BN_V5_GATE_PROXIMITY_SWING_BLOCK",
                                        sym=self.symbol, pattern=s.pattern,
                                        side=s.side, entry_price=s.entry_price,
                                        **ctx)
                        except Exception:
                            pass
                    # 04/06 R4 code-reviewer : `continue` cosmetique 99% des cas
                    # (tous les setups d'une bar partagent entry_idx + entry_price
                    # donc memes coordonnees pour le veto). Mais defendable :
                    # une bar peut produire LONG (V/W) ET SHORT (INV_V/M)
                    # simultanement -> le LONG vetoye laisse passer un SHORT
                    # potentiel teste contre swing oppose.
                    continue

            self._n_setups_detected += 1
            if self.log_fn is not None:
                try:
                    self.log_fn("BN_V5_SETUP_DETECTED",
                                sym=self.symbol, pattern=s.pattern, side=s.side,
                                entry_price=s.entry_price, sl_price=s.sl_price,
                                pivot_price=s.pivot_price, neckline=s.neckline,
                                conf_level=s.confluence_level,
                                conf_dist_pct=s.confluence_dist_pct)
                except Exception:
                    pass
            return s
        return None

    def get_stats(self) -> Dict[str, int]:
        return {
            "n_bars_processed": self._n_bars_processed,
            "n_setups_detected": self._n_setups_detected,
            "n_filtered_range": self._n_filtered_range,
            "n_filtered_confluence": self._n_filtered_confluence,
            "n_filtered_bar_reversal": self._n_filtered_bar_reversal,
            "n_filtered_proximity_swing": self._n_filtered_proximity_swing,
        }


__all__ = [
    "BNV5Engine", "BNV5Params", "Setup", "TrailingStateV5",
    "SIDE_LONG", "SIDE_SHORT",
    "PATTERN_V", "PATTERN_W", "PATTERN_INV_V", "PATTERN_M",
    "TICK_BY_SYMBOL", "TICK_VAL_USD_BY_SYMBOL",
    "find_pivots", "init_trailing", "update_trailing", "is_sl_hit", "is_timeout",
    "detect_v_long", "detect_w_long", "detect_inv_v_short", "detect_m_short",
    "proximity_swing_check",
]
