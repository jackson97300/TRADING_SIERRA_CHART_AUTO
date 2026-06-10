"""bot3_v3_continuation_engine.py — Pure logic state machine Bot 3 v3.

Backtest baseline (130j MenthorQ propre 15/12/2025 - 22/05/2026) :
  n=1611 trades, WR 43%, PF 1.045, DSR 0.21, PF_min_fold=0.75
  Source : `LOGS/bot3_continuation/REPORT_CONTINUATION.md`

Architecture (calquée BN V4) :
  - Bot3V3Engine : 1 instance par symbol, 22 state machines internes
  - process_bar(row, bar_ts, bar_day) : appele bar par bar (live ou replay)
  - Maintient etat entre appels (reset auto au changement de jour)
  - PURE LOGIC : pas d'I/O, pas de DTC, pas de logger.emit (deleguer paper module)
  - Logger optionnel injectable pour traceabilite (BOT3_V3_* codes)

State machine 4 etats par level/jour :
  WAITING_TOUCH (initial)
    → ARMED (sur first-touch : abs(dist_pct) <= touch_buffer_pct)
        → BREAKOUT (close > level + 0.025% LONG / < level - 0.025% SHORT)
        → reset WAITING_TOUCH (timeout 60 bars sans breakout)
    → BREAKOUT
        → WAITING_RETEST (prix revient toucher level +/- retest_buffer_pct)
        → reset WAITING_TOUCH (timeout 120 bars sans retest)
    → WAITING_RETEST
        → CONFIRMATION → ENTRY (long_up_bar==1 LONG / long_dn_bar==1 SHORT dans 3 bars)
        → reset WAITING_TOUCH (timeout 3 bars sans confirmation)

Anti-look-ahead structurel :
  - process_bar(row) recoit UNIQUEMENT row courante + state interne
  - Aucun acces row+k, aucune rolling window passe les bornes
  - state.level_price_locked = fige au moment du touch (pas recompute)

SL (swing-based avec fallback) :
  LONG : _last_swing_low_price - sl_buffer_ticks (fallback : entry - sl_fallback_ticks)
  SHORT : _last_swing_high_price + sl_buffer_ticks (fallback inverse)
  Caps : min sl_min_ticks (5), max sl_max_ticks (30 NQ / 18 ES)

TP : entry +/- target_R * sl_ticks * tick (R-multiple fixe, default 1.5R).

Output :
  EntryDecision dataclass (side, level_name, level_family, entry_close, sl_price,
    tp_price, sl_ticks, swing_used, confirm_pattern, bar_idx, bar_ts)
  OU None (pas de signal cette bar)

Tests : tests/test_bot3_v3_engine.py (20+ tests TDD couvrant transitions, edge
cases, anti-look-ahead, day boundary, SL/TP calc).

Auteur : MIA Trading V2
  v1.0 (2026-05-24) : portage backtester `bot3_continuation_backtester.py` valide
  empirique (PF 1.045 sur 1611 trades, 130j MenthorQ).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════

# Tick size par symbol (constants depuis CORE.constants si dispo, fallback inline)
TICK_BY_SYMBOL: Dict[str, float] = {
    "NQ": 0.25,
    "ES": 0.25,
    "MGC": 0.10,
}

# State machine valid states (set ferme pour fail-loud asserts)
STATE_WAITING_TOUCH = "WAITING_TOUCH"
STATE_ARMED = "ARMED"
STATE_BREAKOUT = "BREAKOUT"
STATE_WAITING_RETEST = "WAITING_RETEST"
STATE_CONFIRMATION = "CONFIRMATION"  # transitionnel (n'est jamais persistant)

VALID_STATES = frozenset({
    STATE_WAITING_TOUCH, STATE_ARMED, STATE_BREAKOUT,
    STATE_WAITING_RETEST, STATE_CONFIRMATION,
})

# Sides
SIDE_LONG = "LONG"
SIDE_SHORT = "SHORT"
VALID_SIDES = frozenset({SIDE_LONG, SIDE_SHORT})


# ════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LevelDef:
    """Definition d'un niveau institutionnel (port de bot3_reform_variants.py).

    Frozen : 1 instance partagee entre engine instances, immutable.
    """
    name: str
    tier: int               # 1=majeur, 2=moyen, 3=mineur
    dist_col: str           # colonne parquet/JSONL distance signee en %
    threshold_pct: float    # seuil touch (abs(dist_pct) <= threshold)
    side_default: str       # LONG ou SHORT
    family: str             # MQ / MP / VWAP / IB / GEX / CASH / SWING

    def __post_init__(self):
        assert self.side_default in VALID_SIDES, f"side_default invalid : {self.side_default}"
        assert self.tier in (1, 2, 3), f"tier invalid : {self.tier}"
        assert self.threshold_pct > 0, f"threshold_pct must be > 0 : {self.threshold_pct}"


@dataclass
class Bot3V3Params:
    """Configuration Bot 3 v3 (defaults = backtester valide empirique).

    Tous parametres mutables pour permettre ajustement post-paper validation.
    """
    # 02/06/2026 SOIR Jackson directive "SL/TP fixe + plus selectif" :
    # Backtest 102 trades parquet NQ : nouveau setup (SL=25/TP=50/RR=2 + cooldown
    # 20/30 + min_vwap_slope_abs>=0.10) projete PF 1.86 / Net +$375 / N=27 sur 10j
    # (vs actuel PF 1.07 / Net +$50 / N=105). Trade ×4 plus selectif, PnL ×7.5.
    # Buffers detection (pourcentage du prix)
    # 24/05/2026 PM Jackson directive : "vision trading = ZONE de prix, pas pile".
    # 02/06/2026 SOIR : tightening pour reduire trades 105->27 sur 10j (-74%).
    touch_buffer_pct: float = 0.03      # 02/06 : 0.05 -> 0.03 (zone touch + serree)
    breakout_buffer_pct: float = 0.015  # 02/06 : 0.025 -> 0.015 (cassure + claire)
    retest_buffer_pct: float = 0.015    # 02/06 : 0.025 -> 0.015 (retest + precis)
    # Timeouts state machine (en bars 1-min)
    window_touch_to_breakout: int = 60      # ARMED max 1h sans breakout
    window_breakout_to_retest: int = 120    # BREAKOUT max 2h sans retest
    window_retest_confirm: int = 5          # 02/06 : 3 -> 5 bars (validation + longue)
    # TP R-multiple fixe (legacy mode swing-based)
    target_R: float = 2.0                   # 02/06 : 1.5 -> 2.0 (RR coherent fixe SL/TP)
    # SL swing-based + fallback caps (LEGACY si sl_tp_fixed_mode_nq=False)
    sl_buffer_ticks: int = 3                # buffer au-dela swing (LONG: - / SHORT: +)
    sl_fallback_ticks_nq: int = 15          # fallback si swing absent NQ
    sl_fallback_ticks_es: int = 8           # fallback ES
    sl_min_ticks: int = 5                   # ES legacy floor (NQ utilise mode fixe direct)
    sl_max_ticks_nq: int = 25               # 02/06 : 30 -> 25 (cap + strict, bug 58t observe)
    sl_max_ticks_es: int = 18               # SL max ES

    # 02/06/2026 SOIR Jackson "SL et TP fixe qui laisse le prix respirer" :
    # Mode SL/TP fixe (court-circuite swing-based + fallback + ATR hybrid).
    # Empirique : sl_fallback 15t utilise 95% du temps + 49% slippage > 1.0R sur
    # losers = SL effectif ~23t. Nouveau SL=25t = "respire" sans elargir trop.
    # TP=50t (=$62.50) avec RR 2:1 = breakeven a WR 33% (vs WR 47% actuel) =
    # marge de securite confortable. Backtest projection PF 1.86.
    sl_tp_fixed_mode_nq: bool = True        # 02/06 : ACTIF NQ (defaut)
    sl_tp_fixed_mode_es: bool = False       # ES continue swing-based (config fixe deja via GUARD_RAILS)
    sl_fixed_ticks_nq: int = 25             # SL fixe NQ = $31.25 USD = ~1 ATR
    tp_fixed_ticks_nq: int = 50             # TP fixe NQ = $62.50 USD = RR 2:1 propre

    # 26/05/2026 00:15 UTC Jackson : filtre trend alignment (sign vwap_slope_10).
    # Trade 23:48 LONG CUR_VAL @29895.50 dans downtrend macro (slope -0.107) ->
    # SL -25t -$12.50 en 14 sec. Marche a continue de descendre apres (-13pts).
    # Jackson souverain : "APLIQUE LE MEME FILTRE que Bot 3 v4". Sign-only veto :
    #   - LONG  veto si vwap_slope_10 <= 0 (pas long en downtrend)
    #   - SHORT veto si vwap_slope_10 >= 0 (pas short en uptrend)
    # Justification empirique : audit lundi 25/05 Bot 1 LONGs PF 0.65 vs SHORTs PF 3.79.
    # Le filtre va surtout filter les LONGs aveugles en downtrend Asia.
    trend_alignment_required: bool = True

    # 02/06/2026 SOIR Jackson "Bot 1 plus selectif" : threshold absolu sur vwap_slope_10.
    # Skip si |slope| < threshold (trend trop faible = choppy). Backtest projection :
    # avec threshold 0.10 pts/bar (cf bars 1min) + cooldown, N=27 PF 1.86 Net +$375.
    # 0.0 = filtre absolu desactive (seul le sign-only ci-dessus s'applique).
    # 03/06/2026 Jackson Option B : 0.10 -> 0.05 (Bot 1 silencieux 24h sur seuil 0.10).
    # Diagnostic 03/06 00h : 17/17 retests vetoed (slope obs 0.025-0.045 < 0.10).
    # 0.05 = laisse passer la zone marginale (sessions Asia/consolidation).
    # Backtest valide 0.10 (n=27 PF 1.86) ; 0.05 non testé empirique = monitor 7j.
    min_vwap_slope_abs: float = 0.05        # 03/06 : 0.10 -> 0.05 (Option B Jackson)

    # 27/05/2026 ROLLBACK Jackson + code-reviewer : Plan C deploy etait BUG D'UNITES.
    # Le backtest utilisait `atr14_15min` en POINTS, le code prod lit `row["atr"]`
    # en TICKS (cf enricher_chain.py:819-820). Resultat : SL calcule ~12x trop
    # petit que le backtest. Plan C reactiver UNIQUEMENT apres refait backtest
    # avec bonne unite + bon timeframe ET tests pytest pass.
    sl_hybrid_atr_enabled_nq: bool = False  # ROLLBACK 27/05 (bug unites atr)
    sl_hybrid_atr_enabled_es: bool = False
    sl_atr_floor_factor: float = 0.5
    sl_atr_cap_factor: float = 2.0

    # 03/06/2026 FIX B Jackson — VETO REGIME_CONTRA (post-incident 3 LONG perdants -$922).
    # Bot 3 V3 IGNORAIT son propre signal regime calcule par enricher (regime_favor=SHORT
    # actionable=1 4 min avant entry, jamais consulte). Aujourd'hui : trade 14:36 LONG NQ
    # dans cassure baissiere post-news ISM = perte -$495.
    # Veto : si regime_actionable=1 ET regime_favor != side ET regime_confidence >= threshold,
    # block l'entry. Calibration : seuil 0.20 sur formule V1 cassee /12.0 (max conf observe
    # 0.33). Backtest 172 trades 24/05-03/06 : 2.3% block, +52t economise, PF 1.08 (vs 1.06
    # baseline). Marginal mais sauve les pertes evitables. Cousin du bug range_pos Bot 4
    # fix matin 03/06 (regime_engine.py V1 a meme bug formule documente regime_engine_v2:11-22).
    regime_contra_veto_enabled: bool = False  # POSE : params ajoutes 17:30 mais NON LUS,
    # discussion en attente. Reviewer + market-analyst : V1 marginal +52t (NEUTRAL).
    regime_contra_min_confidence: float = 0.20

    # 03/06/2026 FIX B L2 Jackson — VETO SLOPE_DIVERGENCE (anti-lagging filter).
    # Le filtre vwap_slope_10 actuel a un LAG de 10 bars (10 min). Sur cassure rapide
    # (NQ 13:38 30790->30580 en 30 min post-news ISM), slope_10 reste positif pendant
    # que prix plonge. Trade 14:35 LONG @30706.5 SL=-99t = -$495 (slope_10=+0.134 mais
    # ctx_price_slope_5=-7.48 detecte la cassure 5 min plus tot).
    # Logique : LONG passe le filtre vwap_slope_10 (slope > 0.05 positif) MAIS si
    # ctx_price_slope_5 <= -threshold (cassure rapide detectee par slope court), veto.
    # Backtest 167 trades 24/05-03/06 (divergence + |s5|>=thr) :
    #   thr=2.0 : 41% block, +944t, PF 2.19 (OVERFIT risk + Pattern 11)
    #   thr=3.5 : 27% block, +601t, PF 1.48
    #   thr=5.0 : 17% block, +443t, PF 1.28 (Jackson choice = preserve wins)
    # 2eme backtest (SL/L2 matrix) : thr=5.0 LONG only PF 1.86 sur 168 trades restants.
    # Bloque les 2 LONG perdants 03/06 (14:35 -99t, 14:50 -38t).
    # Default LONG ONLY car SHORT castrate son edge (PF 1.66 → 1.10 sur SHORT seuls).
    # KILL SWITCH ENV : BOT3_V3_SLOPE_L2_DISABLED=1 -> rollback runtime sans redeploy.
    slope_divergence_veto_enabled: bool = True
    slope_divergence_threshold: float = 5.0  # |ctx_price_slope_5| min pour veto (Jackson 04/06)
    slope_divergence_apply_to_short: bool = False  # LONG ONLY par defaut (preserve SHORT edge)

    def __post_init__(self):
        assert self.touch_buffer_pct > 0
        assert self.breakout_buffer_pct > 0
        assert self.retest_buffer_pct > 0
        assert self.window_touch_to_breakout > 0
        assert self.window_breakout_to_retest > 0
        assert self.window_retest_confirm > 0
        assert self.target_R > 0
        assert self.sl_buffer_ticks >= 0
        assert self.sl_min_ticks > 0
        assert self.sl_fallback_ticks_nq >= self.sl_min_ticks
        assert self.sl_fallback_ticks_es >= self.sl_min_ticks
        assert self.sl_max_ticks_nq >= self.sl_fallback_ticks_nq
        assert self.sl_max_ticks_es >= self.sl_fallback_ticks_es
        # 02/06/2026 SOIR validations setup fixe Jackson
        assert self.sl_fixed_ticks_nq > 0, "sl_fixed_ticks_nq doit etre > 0"
        assert self.tp_fixed_ticks_nq > 0, "tp_fixed_ticks_nq doit etre > 0"
        assert self.min_vwap_slope_abs >= 0, "min_vwap_slope_abs doit etre >= 0 (0 = desactive)"


@dataclass
class LevelState:
    """Etat state machine pour 1 level (1 instance par level dans engine)."""
    state: str = STATE_WAITING_TOUCH
    touch_bar_idx: int = -1
    breakout_bar_idx: int = -1
    retest_bar_idx: int = -1
    level_price_locked: float = 0.0
    prev_in_zone: bool = False


@dataclass(frozen=True)
class EntryDecision:
    """Decision d'entrée émise par l'engine (1 instance par signal d'entrée).

    Frozen : immutable, passe au paper module pour execution DTC.
    """
    side: str                # LONG ou SHORT
    level_name: str          # nom du level qui a triggered
    level_family: str        # MQ/MP/VWAP/IB/GEX/CASH/SWING
    entry_close: float       # close de la bar de CONFIRMATION (= entry price brut, avant slip)
    sl_price: float          # SL absolu
    tp_price: float          # TP absolu
    sl_ticks: int            # nb ticks entre entry et SL (pour R-multiple)
    swing_used: bool         # True si SL swing-based, False si fallback
    confirm_pattern: str     # "long_up_bar" ou "long_dn_bar"
    bar_idx: int             # bar_idx interne engine (counter)
    bar_ts: str              # ISO timestamp de la bar de confirmation


# ════════════════════════════════════════════════════════════════════════
# DEFAULT LEVEL DEFS (22 levels : V1_LONG + V4_SHORT)
# ════════════════════════════════════════════════════════════════════════

def build_default_level_defs() -> List[LevelDef]:
    """Construit la liste des 22 niveaux par defaut.

    Source : `CORE/research/bot3_reform_variants.py` (validé backtest).
    13 LONG + 9 SHORT = 22 levels actifs en parallele.
    """
    return [
        # LONG levels (13)
        LevelDef("MQ_1D_MIN",    1, "dist_1d_min_ticks_pct",  0.02, SIDE_LONG, "MQ"),
        LevelDef("MQ_PUT",       1, "dist_mq_put_pct",        0.02, SIDE_LONG, "MQ"),
        LevelDef("MQ_PUT_0DTE",  1, "dist_mq_put_0dte_pct",   0.02, SIDE_LONG, "MQ"),
        LevelDef("MQ_HVL",       2, "dist_mq_hvl_pct",        0.02, SIDE_LONG, "MQ"),
        LevelDef("CUR_VAL",      2, "dist_cur_val_pct",       0.02, SIDE_LONG, "MP"),
        LevelDef("CUR_VPOC",     2, "dist_cur_vpoc_pct",      0.02, SIDE_LONG, "MP"),
        LevelDef("PREV_VAL",     3, "dist_prev_val_pct",      0.02, SIDE_LONG, "MP"),
        LevelDef("PVWAP",        2, "dist_pvwap_pct",         0.02, SIDE_LONG, "VWAP"),
        LevelDef("VWAP_D",       2, "dist_vwap_d_pct",        0.02, SIDE_LONG, "VWAP"),
        LevelDef("GEX_DN",       2, "dist_gex_nearest_dn_pct",0.02, SIDE_LONG, "GEX"),
        LevelDef("CASH_LOW",     3, "dist_cash_low_pct",      0.02, SIDE_LONG, "CASH"),
        LevelDef("ASIA_LOW",     3, "dist_asia_low_pct",      0.02, SIDE_LONG, "CASH"),
        LevelDef("IB_LOW",       2, "dist_ib_low_pct",        0.02, SIDE_LONG, "IB"),
        # SHORT levels (9)
        LevelDef("MQ_1D_MAX",    1, "dist_1d_max_ticks_pct",  0.02, SIDE_SHORT, "MQ"),
        LevelDef("MQ_CALL",      1, "dist_mq_call_pct",       0.02, SIDE_SHORT, "MQ"),
        LevelDef("MQ_CALL_0DTE", 1, "dist_mq_call_0dte_pct",  0.02, SIDE_SHORT, "MQ"),
        LevelDef("CUR_VAH",      2, "dist_cur_vah_pct",       0.02, SIDE_SHORT, "MP"),
        LevelDef("PREV_VAH",     3, "dist_prev_vah_pct",      0.02, SIDE_SHORT, "MP"),
        LevelDef("GEX_UP",       2, "dist_gex_nearest_up_pct",0.02, SIDE_SHORT, "GEX"),
        LevelDef("IB_HIGH",      2, "dist_ib_high_pct",       0.02, SIDE_SHORT, "IB"),
        LevelDef("CASH_HIGH",    3, "dist_cash_high_pct",     0.02, SIDE_SHORT, "CASH"),
        LevelDef("ASIA_HIGH",    3, "dist_asia_high_pct",     0.02, SIDE_SHORT, "CASH"),
    ]


# ════════════════════════════════════════════════════════════════════════
# ENGINE
# ════════════════════════════════════════════════════════════════════════

class Bot3V3Engine:
    """Pure logic state machine 4 etats pour Bot 3 v3 continuation.

    Architecture (calquée BN V4) :
      - 1 instance par symbol (NQ-only en production paper)
      - Maintient 22 state machines internes (1 par level)
      - process_bar(row, bar_ts, bar_day) advance toutes les state machines
      - Retourne EntryDecision si CONFIRMATION_OK atteint, sinon None
      - Reset auto au changement de jour (detection via bar_day != current_day)

    Anti-look-ahead structurel :
      - row courante uniquement, pas de rolling window externe
      - state.level_price_locked fige au moment du touch (anti-drift)
      - bar_idx interne incrémenté par process_bar (pas exposé caller)

    Thread-safety :
      - Pas de threading interne. Caller doit serializer process_bar() si
        appelé depuis plusieurs threads (en pratique : poll_cycle paper module
        single-threaded).

    Usage :
        engine = Bot3V3Engine(symbol="NQ", level_defs=build_default_level_defs())
        for row in jsonl_stream:
            decision = engine.process_bar(row, row["ts_event_iso"], row["session_date"])
            if decision is not None:
                paper.execute(decision)
    """

    def __init__(
        self,
        symbol: str,
        level_defs: List[LevelDef],
        params: Optional[Bot3V3Params] = None,
        log_fn: Optional[Any] = None,
    ):
        """Args:
            log_fn : Optional callable(code: str, **ctx) -> None
              Injection logger pour tracability transitions state machine
              (TOUCH/ARMED/BREAKOUT/RETEST/CONFIRMATION/TIMEOUT). Si None,
              transitions silencieuses (back-compat tests pure logic).
              Permet debug J+1 via grep logs.
        """
        assert symbol in TICK_BY_SYMBOL, \
            f"Symbol {symbol} unsupported (allowed: {list(TICK_BY_SYMBOL.keys())})"
        assert len(level_defs) > 0, "level_defs must contain at least 1 level"

        self.symbol = symbol
        self.level_defs = list(level_defs)  # copy defensive
        self.params = params or Bot3V3Params()
        self.tick_size = TICK_BY_SYMBOL[symbol]
        self.log_fn = log_fn  # injection pour tracability

        # State machine par level
        self._level_states: Dict[str, LevelState] = {
            lv.name: LevelState() for lv in self.level_defs
        }

        # Bar index counter (reset au changement de jour)
        self._bar_idx: int = -1
        self._current_day: Optional[str] = None

        # Stats internes (pour heartbeat)
        self._n_bars_processed: int = 0
        self._n_touches_detected: int = 0
        self._n_breakouts_confirmed: int = 0
        self._n_retests_detected: int = 0
        self._n_entries_emitted: int = 0
        self._n_timeouts: int = 0
        self._n_day_resets: int = 0
        # 26/05 Jackson : counter veto trend_alignment (sign)
        self._n_filtered_trend_misalign: int = 0
        # 04/06 FIX B L2 : counter veto slope_5 divergence
        self._n_filtered_slope_divergence: int = 0

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def reset_day(self, new_day: str) -> int:
        """Reset all level states au changement de jour.

        Args:
            new_day : str (YYYYMMDD) nouveau jour

        Returns:
            int : nb_states_resets (pour log/audit)
        """
        n_non_initial = sum(
            1 for s in self._level_states.values()
            if s.state != STATE_WAITING_TOUCH
        )
        self._level_states = {lv.name: LevelState() for lv in self.level_defs}
        self._bar_idx = -1
        self._current_day = new_day
        self._n_day_resets += 1
        return n_non_initial

    def process_bar(
        self,
        row: Union[Dict[str, Any], Any],
        bar_ts_iso: str,
        bar_day: str,
    ) -> Optional[EntryDecision]:
        """Process une nouvelle bar live. Retourne EntryDecision si CONFIRMATION.

        Args:
            row : dict OR pd.Series avec keys minimum :
                close, high, low, long_up_bar, long_dn_bar,
                _last_swing_low_price, _last_swing_high_price,
                dist_*_pct (pour chaque level dans level_defs)
            bar_ts_iso : ISO timestamp UTC (pour EntryDecision.bar_ts)
            bar_day : YYYYMMDD (pour detection changement de jour)

        Returns:
            EntryDecision si state machine atteint CONFIRMATION_OK pour 1 level
            None sinon (incluant le cas multi-confirmations: retourne le 1er)
        """
        # 1. Day boundary detection + reset (fix R2 review iter1 : skip si boot)
        if self._current_day is None:
            # 1er process_bar : initialise current_day sans reset (no states actifs)
            self._current_day = bar_day
        elif bar_day != self._current_day:
            self.reset_day(bar_day)

        # 2. Increment bar idx
        self._bar_idx += 1
        self._n_bars_processed += 1

        # 3. Extract close defensively
        close = self._safe_float(self._row_get(row, "close"))
        if close is None or close <= 0:
            # Skip bar entire : preserve tous les states
            return None

        # 4. Advance toutes les state machines, retourner 1ere EntryDecision
        for lv in self.level_defs:
            decision = self._advance_state(lv, row, close, bar_ts_iso)
            if decision is not None:
                self._n_entries_emitted += 1
                return decision

        return None

    def get_state_snapshot(self) -> Dict[str, str]:
        """Retourne {level_name: state} pour debug/heartbeat."""
        return {name: s.state for name, s in self._level_states.items()}

    def get_state_counts(self) -> Dict[str, int]:
        """Retourne {state: count} pour stats heartbeat."""
        counts: Dict[str, int] = {}
        for s in self._level_states.values():
            counts[s.state] = counts.get(s.state, 0) + 1
        return counts

    def get_stats(self) -> Dict[str, int]:
        """Retourne stats lifetime pour heartbeat."""
        return {
            "n_bars_processed": self._n_bars_processed,
            "n_touches_detected": self._n_touches_detected,
            "n_breakouts_confirmed": self._n_breakouts_confirmed,
            "n_retests_detected": self._n_retests_detected,
            "n_entries_emitted": self._n_entries_emitted,
            "n_timeouts": self._n_timeouts,
            "n_day_resets": self._n_day_resets,
            "current_bar_idx": self._bar_idx,
        }

    # ─────────────────────────────────────────────────────────────────────
    # State machine core
    # ─────────────────────────────────────────────────────────────────────

    def _advance_state(
        self,
        lv: LevelDef,
        row: Any,
        close: float,
        bar_ts_iso: str,
    ) -> Optional[EntryDecision]:
        """Advance state machine pour 1 level. Logic des 4 etats + transitions.

        Returns EntryDecision si la state machine atteint CONFIRMATION_OK.
        """
        state = self._level_states[lv.name]
        i = self._bar_idx

        # Extract dist_pct
        dist_pct_raw = self._row_get(row, lv.dist_col)
        dist_pct = self._safe_float(dist_pct_raw)
        if dist_pct is None:
            # NaN/missing : preserve state pour ce level, continue autres
            return None

        # Reconstruct level price (signed dist : positif = level au-dessus)
        # level_price = close * (1 + dist_pct / 100)
        level_price = close * (1.0 + dist_pct / 100.0)
        abs_dist_pct = abs(dist_pct)

        # First-touch detection : in_zone & !prev_in_zone
        in_zone = abs_dist_pct <= self.params.touch_buffer_pct
        first_touch = in_zone and not state.prev_in_zone
        # Update prev_in_zone IMMEDIATEMENT (avant transitions) :
        # garantit que first_touch ne re-trigger pas plusieurs bars consec
        state.prev_in_zone = in_zone

        # Fix R3 review tracability iter1 : level_session_id pour correler
        # toutes les transitions du meme touch (TOUCH → ARMED → BREAKOUT → ENTRY).
        # Format : "{SYM}_{LEVEL}_{TOUCH_BAR_IDX}" (unique par touch+jour).
        level_session_id = (
            f"{self.symbol}_{lv.name}_{state.touch_bar_idx}"
            if state.touch_bar_idx >= 0 else f"{self.symbol}_{lv.name}_NEW"
        )

        # ─── STATE: WAITING_TOUCH ───
        if state.state == STATE_WAITING_TOUCH:
            if first_touch:
                state.state = STATE_ARMED
                state.touch_bar_idx = i
                state.level_price_locked = level_price
                self._n_touches_detected += 1
                # Re-compute session_id maintenant que touch_bar_idx est set
                session_id = f"{self.symbol}_{lv.name}_{i}"
                # Tracability log : touch detected + state armed (correle via session_id)
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_TOUCH_DETECTED",
                                    sym=self.symbol, level=lv.name,
                                    side=lv.side_default,
                                    dist_pct=round(dist_pct, 4), touch_idx=i,
                                    session_id=session_id)
                        self.log_fn("BOT3_V3_STATE_ARMED",
                                    sym=self.symbol, level=lv.name,
                                    side=lv.side_default,
                                    level_price=round(level_price, 4),
                                    session_id=session_id)
                    except Exception:
                        pass  # fail-soft log
            return None

        # ─── STATE: ARMED ───
        if state.state == STATE_ARMED:
            # Timeout : reset si > window_touch_to_breakout bars sans breakout
            if i - state.touch_bar_idx > self.params.window_touch_to_breakout:
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_STATE_TIMEOUT",
                                    sym=self.symbol, level=lv.name,
                                    state="ARMED",
                                    bars=i - state.touch_bar_idx,
                                    session_id=level_session_id)
                    except Exception:
                        pass
                self._reset_level_state(state)
                self._n_timeouts += 1
                return None
            # Breakout detection (depasse level_price_locked + buffer)
            if lv.side_default == SIDE_LONG:
                threshold = state.level_price_locked * (
                    1.0 + self.params.breakout_buffer_pct / 100.0
                )
                breakout = close > threshold
            else:  # SHORT
                threshold = state.level_price_locked * (
                    1.0 - self.params.breakout_buffer_pct / 100.0
                )
                breakout = close < threshold
            if breakout:
                state.state = STATE_BREAKOUT
                state.breakout_bar_idx = i
                self._n_breakouts_confirmed += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_BREAKOUT_CONFIRMED",
                                    sym=self.symbol, level=lv.name,
                                    side=lv.side_default,
                                    close=round(close, 4),
                                    threshold=round(threshold, 4),
                                    bars_since_touch=i - state.touch_bar_idx,
                                    session_id=level_session_id)
                    except Exception:
                        pass
            return None

        # ─── STATE: BREAKOUT ───
        if state.state == STATE_BREAKOUT:
            # Timeout
            if i - state.breakout_bar_idx > self.params.window_breakout_to_retest:
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_STATE_TIMEOUT",
                                    sym=self.symbol, level=lv.name,
                                    state="BREAKOUT",
                                    bars=i - state.breakout_bar_idx,
                                    session_id=level_session_id)
                    except Exception:
                        pass
                self._reset_level_state(state)
                self._n_timeouts += 1
                return None
            # Retest detection : prix revient toucher level_locked
            if close > 0:
                dist_to_locked_pct = abs(close - state.level_price_locked) / close * 100.0
                if dist_to_locked_pct <= self.params.retest_buffer_pct:
                    state.state = STATE_WAITING_RETEST
                    state.retest_bar_idx = i
                    self._n_retests_detected += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V3_RETEST_DETECTED",
                                        sym=self.symbol, level=lv.name,
                                        side=lv.side_default,
                                        close=round(close, 4),
                                        bars_since_breakout=i - state.breakout_bar_idx,
                                        session_id=level_session_id)
                        except Exception:
                            pass
            return None

        # ─── STATE: WAITING_RETEST ───
        if state.state == STATE_WAITING_RETEST:
            # Timeout (3 bars apres retest sans confirmation)
            if i - state.retest_bar_idx > self.params.window_retest_confirm:
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_STATE_TIMEOUT",
                                    sym=self.symbol, level=lv.name,
                                    state="WAITING_RETEST",
                                    bars=i - state.retest_bar_idx,
                                    session_id=level_session_id)
                    except Exception:
                        pass
                self._reset_level_state(state)
                self._n_timeouts += 1
                return None
            # Confirmation pattern detection
            # 25/05/2026 Jackson : elargissement OR cluster (decision souveraine).
            # Avant : confirmation strict long_X_bar==1.
            # Apres : long_X_bar==1 OR n_long_X_cluster_within_0_2pct >= 1.
            # Logique : footprint vendeur (SHORT) ou acheteur (LONG) confirme via
            # bar longue OU cluster actif. Permissif = plus de confirmations.
            side = lv.side_default
            if side == SIDE_LONG:
                confirm_col = "long_up_bar"
                cluster_col = "n_long_up_cluster_within_0_2pct"
            else:  # SHORT
                confirm_col = "long_dn_bar"
                cluster_col = "n_long_dn_cluster_within_0_2pct"
            cv_raw = self._row_get(row, confirm_col)
            cl_raw = self._row_get(row, cluster_col)
            long_bar_ok = False
            cluster_ok = False
            try:
                long_bar_ok = (cv_raw is not None and int(cv_raw) == 1)
            except (TypeError, ValueError):
                long_bar_ok = False
            try:
                cluster_val = self._safe_float(cl_raw)
                cluster_ok = (cluster_val is not None and cluster_val >= 1)
            except (TypeError, ValueError):
                cluster_ok = False

            if long_bar_ok or cluster_ok:
                # 26/05 Jackson : filtre trend_alignment (sign vwap_slope_10).
                # Veto LONG en downtrend / SHORT en uptrend. Sign-only, pas threshold.
                # Aligne avec Bot 3 v4 deploye 25/05. Decision souveraine apres trade
                # 23:48 LONG dans downtrend macro = SL immediat + marche continue de baisser.
                if self.params.trend_alignment_required:
                    vwap_slope = self._safe_float(self._row_get(row, "vwap_slope_10"))
                    # 02/06/2026 SOIR R1 fix : fail-CLOSED si slope absent (vs fail-open).
                    # Anti-pattern "Gamma hardcode 0.0" lessons.md : si la donnee n'est
                    # pas dispo, on refuse le trade au lieu de l'accepter aveuglement.
                    if vwap_slope is None:
                        self._n_filtered_trend_misalign += 1
                        if self.log_fn is not None:
                            try:
                                self.log_fn("BOT3_V3_VETO_NO_SLOPE_DATA",
                                            sym=self.symbol, level=lv.name,
                                            side=side)
                            except Exception:
                                pass
                        self._reset_level_state(state)
                        return None
                    veto_trend = False
                    veto_reason = None
                    # Sign-only veto (26/05) : LONG en downtrend / SHORT en uptrend
                    if side == SIDE_LONG and vwap_slope <= 0:
                        veto_trend = True
                        veto_reason = "sign_misalign"
                    elif side == SIDE_SHORT and vwap_slope >= 0:
                        veto_trend = True
                        veto_reason = "sign_misalign"
                    # 02/06/2026 SOIR Jackson : threshold absolu (trend force).
                    elif (self.params.min_vwap_slope_abs > 0
                          and abs(vwap_slope) < self.params.min_vwap_slope_abs):
                        veto_trend = True
                        veto_reason = "trend_too_weak"
                    if veto_trend:
                            self._n_filtered_trend_misalign += 1
                            if self.log_fn is not None:
                                try:
                                    self.log_fn("BOT3_V3_RETEST_FILTERED_TREND_MISALIGN",
                                                sym=self.symbol, level=lv.name,
                                                side=side,
                                                vwap_slope=round(vwap_slope, 4),
                                                veto_reason=veto_reason,
                                                min_slope_abs=self.params.min_vwap_slope_abs,
                                                session_id=level_session_id)
                                except Exception:
                                    pass
                            self._reset_level_state(state)
                            return None

                # 04/06/2026 FIX B L2 Jackson — VETO SLOPE_DIVERGENCE (anti-lagging).
                # KILL SWITCH ENV : BOT3_V3_SLOPE_L2_DISABLED=1 → bypass.
                # LONG ONLY par defaut (preserve SHORT edge PF 1.66).
                # Cf doc params slope_divergence_* + commentaire 03/06.
                # FAIL-CLOSED si ctx_price_slope_5 absent (symetrie R1 02/06 sur vwap_slope_10).
                if self.params.slope_divergence_veto_enabled:
                    import os as _os
                    if _os.environ.get("BOT3_V3_SLOPE_L2_DISABLED", "0").strip() != "1":
                        apply_l2 = (
                            side == SIDE_LONG
                            or self.params.slope_divergence_apply_to_short
                        )
                        if apply_l2:
                            # Re-lire vwap_slope_10 (safe : si trend_alignment_required=False
                            # alors la variable vwap_slope n'a pas ete definie ci-dessus).
                            # Reserve code-reviewer 04/06 : eviter NameError config exotique.
                            vwap_slope_l2 = self._safe_float(
                                self._row_get(row, "vwap_slope_10")
                            )
                            s5 = self._safe_float(self._row_get(row, "ctx_price_slope_5"))
                            thr = self.params.slope_divergence_threshold
                            # FAIL-CLOSED reserve BLOQUANTE code-reviewer 04/06 :
                            # Si ctx_price_slope_5 absent (data manquante) → refuse l'entry
                            # au lieu d'accepter aveuglement (anti-pattern "Gamma 0.0 hardcode"
                            # lessons.md). Sinon le fix laisse passer en silence le scenario
                            # qu'il pretend bloquer.
                            if s5 is None:
                                self._n_filtered_slope_divergence += 1
                                if self.log_fn is not None:
                                    try:
                                        self.log_fn("BOT3_V3_VETO_NO_SLOPE5_DATA",
                                                    sym=self.symbol, level=lv.name,
                                                    side=side,
                                                    session_id=level_session_id)
                                    except Exception:
                                        pass
                                self._reset_level_state(state)
                                return None
                            l2_veto = False
                            if side == SIDE_LONG and s5 <= -thr:
                                l2_veto = True
                            elif side == SIDE_SHORT and s5 >= thr:
                                l2_veto = True
                            if l2_veto:
                                self._n_filtered_slope_divergence += 1
                                if self.log_fn is not None:
                                    try:
                                        self.log_fn("BOT3_V3_VETO_SLOPE_DIVERGENCE",
                                                    sym=self.symbol, level=lv.name,
                                                    side=side,
                                                    slope_10=(round(vwap_slope_l2, 4)
                                                              if vwap_slope_l2 is not None
                                                              else None),
                                                    slope_5=round(s5, 4),
                                                    threshold=thr,
                                                    session_id=level_session_id)
                                    except Exception:
                                        pass
                                self._reset_level_state(state)
                                return None

                # ═══ CONFIRMATION OK → ENTRY ═══
                # Le confirm_pattern indique si long_bar (legacy) ou cluster (Jackson 25/05)
                if long_bar_ok and cluster_ok:
                    confirm_label = f"{confirm_col}+{cluster_col}"
                elif long_bar_ok:
                    confirm_label = confirm_col
                else:
                    confirm_label = cluster_col
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V3_CONFIRMATION_OK",
                                    sym=self.symbol, level=lv.name,
                                    side=side, confirm_bar=i,
                                    entry_close=round(close, 4),
                                    confirm_pattern=confirm_label,
                                    long_bar_ok=long_bar_ok,
                                    cluster_ok=cluster_ok,
                                    session_id=level_session_id)
                    except Exception:
                        pass
                sl_price, tp_price, sl_ticks, swing_used = self._compute_sl_tp(
                    row, close, side
                )
                decision = EntryDecision(
                    side=side,
                    level_name=lv.name,
                    level_family=lv.family,
                    entry_close=close,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    sl_ticks=sl_ticks,
                    swing_used=swing_used,
                    confirm_pattern=confirm_label,
                    bar_idx=i,
                    bar_ts=bar_ts_iso,
                )
                # Reset state apres ENTRY (meme level peut re-trigger meme jour
                # si retouche : cooldown delegue au paper module via position check)
                self._reset_level_state(state)
                return decision
            return None

        # Should not reach here (all states covered)
        return None

    def _reset_level_state(self, state: LevelState) -> None:
        """Reset state to WAITING_TOUCH (preserve prev_in_zone deja set par cette bar).

        NB : prev_in_zone est preserve car deja calcule pour cette bar dans
        _advance_state(). Le re-mettre a False causerait first_touch=True
        a la bar suivante meme si prix toujours dans zone (faux positif).
        """
        state.state = STATE_WAITING_TOUCH
        state.touch_bar_idx = -1
        state.breakout_bar_idx = -1
        state.retest_bar_idx = -1
        state.level_price_locked = 0.0
        # NB : state.prev_in_zone est preserve

    # ─────────────────────────────────────────────────────────────────────
    # SL / TP calc
    # ─────────────────────────────────────────────────────────────────────

    def _compute_sl_tp(
        self,
        row: Any,
        entry_close: float,
        side: str,
    ) -> Tuple[float, float, int, bool]:
        """Calcule SL (swing-based ou fallback) et TP (R-multiple).

        Args:
            row : dict OR pd.Series avec _last_swing_low/high_price
            entry_close : prix d'entree brut (close de la bar de confirmation)
            side : LONG ou SHORT

        Returns:
            (sl_price, tp_price, sl_ticks, swing_used)
            sl_ticks : entier (>= sl_min, <= sl_max)
            swing_used : True si SL swing-based, False si fallback applique
        """
        tick = self.tick_size
        p = self.params

        # ═══ 02/06/2026 SOIR Jackson : MODE FIXE NQ ═══════════════════════════
        # Court-circuite TOUTE la logique swing-based + fallback + ATR hybrid.
        # SL = entry +/- sl_fixed_ticks_nq (= 25t = $31.25 USD = "respire").
        # TP = entry +/- tp_fixed_ticks_nq (= 50t = $62.50 USD = RR 2:1).
        # Empirique backtest 102 trades NQ : PF 1.86 projete (vs 1.07 actuel).
        if self.symbol == "NQ" and p.sl_tp_fixed_mode_nq:
            sl_fixed = p.sl_fixed_ticks_nq
            tp_fixed = p.tp_fixed_ticks_nq
            if side == SIDE_LONG:
                sl_price = entry_close - sl_fixed * tick
                tp_price = entry_close + tp_fixed * tick
            else:
                sl_price = entry_close + sl_fixed * tick
                tp_price = entry_close - tp_fixed * tick
            # Emit log instrumentation
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V3_SL_FIXED_MODE",
                                sym=self.symbol, side=side,
                                sl_ticks=sl_fixed, tp_ticks=tp_fixed,
                                rr=tp_fixed / sl_fixed)
                except Exception:
                    pass
            return (sl_price, tp_price, sl_fixed, False)
        # ═══ FIN MODE FIXE ═════════════════════════════════════════════════════

        sl_fallback = (
            p.sl_fallback_ticks_nq if self.symbol == "NQ" else p.sl_fallback_ticks_es
        )
        sl_max = p.sl_max_ticks_nq if self.symbol == "NQ" else p.sl_max_ticks_es
        sl_min = p.sl_min_ticks
        sl_buf = p.sl_buffer_ticks
        target_R = p.target_R

        # 27/05 Jackson : Plan C SL hybride ATR-based pour NQ (backtest 14j valide).
        # Si NQ ET sl_hybrid_atr_enabled_nq -> SL = max(swing+buf, floor*atr/tick) clip cap*atr/tick.
        # Sinon (ES ou ATR null) -> Config A actuel.
        hybrid_enabled = (
            (self.symbol == "NQ" and p.sl_hybrid_atr_enabled_nq) or
            (self.symbol == "ES" and p.sl_hybrid_atr_enabled_es)
        )
        atr_pts = self._safe_float(self._row_get(row, "atr")) if hybrid_enabled else None

        if hybrid_enabled and atr_pts is not None and atr_pts > 0:
            # Plan C hybride
            atr_floor_ticks = (p.sl_atr_floor_factor * atr_pts) / tick
            atr_cap_ticks = (p.sl_atr_cap_factor * atr_pts) / tick
            fallback_reason = "atr_floor"
            swing_raw_ticks = None

            if side == SIDE_LONG:
                swing_low = self._safe_float(self._row_get(row, "_last_swing_low_price"))
                if swing_low is not None and swing_low > 0 and swing_low < entry_close:
                    swing_dist = (entry_close - swing_low) / tick + sl_buf
                    swing_raw_ticks = swing_dist
                    sl_ticks_raw = max(swing_dist, atr_floor_ticks)
                    fallback_reason = "swing_or_atr_floor" if swing_dist >= atr_floor_ticks else "atr_floor"
                else:
                    sl_ticks_raw = atr_floor_ticks
                    fallback_reason = "atr_floor_no_swing"
                if sl_ticks_raw > atr_cap_ticks:
                    sl_ticks_raw = atr_cap_ticks
                    fallback_reason = "atr_cap"
                sl_ticks = max(int(round(sl_ticks_raw)), sl_min)
                sl_price = entry_close - sl_ticks * tick
                swing_used = (fallback_reason in ("swing_or_atr_floor",))
            else:  # SHORT
                swing_high = self._safe_float(self._row_get(row, "_last_swing_high_price"))
                if swing_high is not None and swing_high > 0 and swing_high > entry_close:
                    swing_dist = (swing_high - entry_close) / tick + sl_buf
                    swing_raw_ticks = swing_dist
                    sl_ticks_raw = max(swing_dist, atr_floor_ticks)
                    fallback_reason = "swing_or_atr_floor" if swing_dist >= atr_floor_ticks else "atr_floor"
                else:
                    sl_ticks_raw = atr_floor_ticks
                    fallback_reason = "atr_floor_no_swing"
                if sl_ticks_raw > atr_cap_ticks:
                    sl_ticks_raw = atr_cap_ticks
                    fallback_reason = "atr_cap"
                sl_ticks = max(int(round(sl_ticks_raw)), sl_min)
                sl_price = entry_close + sl_ticks * tick
                swing_used = (fallback_reason in ("swing_or_atr_floor",))

            tp_price = entry_close + (1 if side == SIDE_LONG else -1) * target_R * sl_ticks * tick

            # Emit log
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V3_SL_FALLBACK_REASON",
                                sym=self.symbol, side=side,
                                reason=fallback_reason,
                                sl_ticks=sl_ticks,
                                swing_raw_ticks=swing_raw_ticks,
                                sl_max=int(round(atr_cap_ticks)),
                                sl_min=sl_min, sl_fallback=int(round(atr_floor_ticks)),
                                atr_pts=atr_pts)
                except Exception:
                    pass

            return (sl_price, tp_price, sl_ticks, swing_used)

        # ───── Sinon : logique legacy Config A (ES ou ATR null) ─────
        # 27/05 Jackson : instrumentation SL_FALLBACK_REASON pour audit J+1
        # Raisons possibles : swing_null / swing_wrong_side / cap_max_hit / cap_min_hit / ok_swing_based
        fallback_reason = "ok_swing_based"
        swing_raw_ticks = None

        if side == SIDE_LONG:
            swing_low = self._safe_float(self._row_get(row, "_last_swing_low_price"))
            swing_used = False
            if swing_low is None or swing_low <= 0:
                fallback_reason = "swing_null"
                sl_ticks = sl_fallback
                sl_price = entry_close - sl_ticks * tick
            elif swing_low >= entry_close:
                fallback_reason = "swing_wrong_side"
                sl_ticks = sl_fallback
                sl_price = entry_close - sl_ticks * tick
            else:
                sl_price = swing_low - sl_buf * tick
                sl_ticks = int(round((entry_close - sl_price) / tick))
                swing_raw_ticks = sl_ticks
                if sl_ticks > sl_max:
                    fallback_reason = "cap_max_hit"
                    sl_ticks = sl_fallback
                    sl_price = entry_close - sl_ticks * tick
                else:
                    swing_used = True
            if sl_ticks < sl_min:
                fallback_reason = "cap_min_hit"
                sl_ticks = sl_min
                sl_price = entry_close - sl_min * tick
                swing_used = False
            tp_price = entry_close + target_R * sl_ticks * tick

        else:  # SHORT
            swing_high = self._safe_float(self._row_get(row, "_last_swing_high_price"))
            swing_used = False
            if swing_high is None or swing_high <= 0:
                fallback_reason = "swing_null"
                sl_ticks = sl_fallback
                sl_price = entry_close + sl_ticks * tick
            elif swing_high <= entry_close:
                fallback_reason = "swing_wrong_side"
                sl_ticks = sl_fallback
                sl_price = entry_close + sl_ticks * tick
            else:
                sl_price = swing_high + sl_buf * tick
                sl_ticks = int(round((sl_price - entry_close) / tick))
                swing_raw_ticks = sl_ticks
                if sl_ticks > sl_max:
                    fallback_reason = "cap_max_hit"
                    sl_ticks = sl_fallback
                    sl_price = entry_close + sl_ticks * tick
                else:
                    swing_used = True
            if sl_ticks < sl_min:
                fallback_reason = "cap_min_hit"
                sl_ticks = sl_min
                sl_price = entry_close + sl_min * tick
                swing_used = False
            tp_price = entry_close - target_R * sl_ticks * tick

        # 27/05 Emit log instrumentation (visible dans events_paper_v2)
        if self.log_fn is not None:
            try:
                atr_pts = self._safe_float(self._row_get(row, "atr"))
                self.log_fn("BOT3_V3_SL_FALLBACK_REASON",
                            sym=self.symbol, side=side,
                            reason=fallback_reason,
                            sl_ticks=sl_ticks,
                            swing_raw_ticks=swing_raw_ticks,
                            sl_max=sl_max, sl_min=sl_min, sl_fallback=sl_fallback,
                            atr_pts=atr_pts)
            except Exception:
                pass

        return (sl_price, tp_price, sl_ticks, swing_used)

    # ─────────────────────────────────────────────────────────────────────
    # Helpers (defensive value extraction)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _row_get(row: Any, key: str) -> Any:
        """Defensive get : supporte dict, pd.Series, ou objet avec .get()."""
        if hasattr(row, "get"):
            try:
                return row.get(key)
            except Exception:
                return None
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        """Cast float defensif : NaN/Inf/None/non-castable → None."""
        if v is None:
            return None
        # pd.NA / pd.NaT detection (avant float() pour eviter exception cryptique)
        try:
            import pandas as _pd
            if _pd.isna(v):
                return None
        except (ImportError, TypeError):
            pass
        try:
            f = float(v)
            if not math.isfinite(f):
                return None
            return f
        except (TypeError, ValueError):
            return None
