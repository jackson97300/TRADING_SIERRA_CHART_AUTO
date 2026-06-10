"""bot3_v4_data_driven_engine.py — Pure logic touch detection Bot 3 v4.

Backtest baseline (130j MenthorQ propre 15/12/2025 - 22/05/2026) :
  n=1110 trades, WR 30%, PF 1.033, DSR 0.13, PF_min_fold=0.51
  Source : `LOGS/bot3_v4/REPORT.md`

Architecture (calquée BN V4) :
  - Bot3V4Engine : 1 instance par symbol, 6 touch detectors internes
  - process_bar(row, bar_ts, bar_day) : appele bar par bar (live ou replay)
  - Maintient etat entre appels (reset auto au changement de jour)
  - PURE LOGIC : pas d'I/O, pas de DTC, pas de logger.emit

6 TRIGGERS ASYMETRIQUES EMPIRIQUES (analyse 54K bounces) :
  LONG :
    - SWING_LOW (81% conditional LONG bounce empirique)
    - VWAP_D_SD2D (72%)
    - CUR_VAL (61%)
  SHORT :
    - SWING_HIGH (76%)
    - VWAP_D_SD2U (72%)
    - CUR_VAH (63%)

Touch detection :
  - First-touch : abs(dist_pct) <= touch_buffer_pct ET prev abs > buffer
  - Cooldown : >= cooldown_bars depuis dernier touch valide ce niveau
  - Daily cap : <= max_per_level_per_day touches/niveau/jour

TP CUR_VPOC MAGNET (edge critique) :
  - Si cur_vpoc valide ET cote correct (LONG: vpoc > entry, SHORT: vpoc < entry)
    ET distance >= 5 ticks → TP = cur_vpoc
  - Sinon fallback : TP = entry +/- target_R * sl_ticks * tick
  - IMPORTANT : R1.5 fixe seul DETRUIT le signal (PF 0.74 vs 1.03 backtest).
    Le magnet VPOC est le vrai edge.

SL swing-based + fallback :
  LONG : _last_swing_low_price - 5t (fallback : entry - 15t NQ / 8t ES)
  SHORT : _last_swing_high_price + 5t (fallback inverse)
  Caps : min 5t (safety), max 30t NQ / 18t ES.

Pas de filter regime (TREND 56% des bounces empirique).
Pas de bonus filter (delta_div CASSE le signal : n 1110 → 294 backtest).

Output :
  EntryDecisionV4 dataclass (side, level_name, level_family, entry_close, sl_price,
    tp_price, sl_ticks, swing_used, tp_mode, vpoc_used, bar_idx, bar_ts,
    asym_prob)

Tests : tests/test_bot3_v4_engine.py (15+ tests TDD).

Auteur : MIA Trading V2
  v1.0 (2026-05-24) : portage backtester `bot3_v4_data_driven.py` valide
  empirique (PF 1.033 sur 1110 trades, 130j MenthorQ).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════

TICK_BY_SYMBOL: Dict[str, float] = {
    "NQ": 0.25,
    "ES": 0.25,
    "MGC": 0.10,
}

SIDE_LONG = "LONG"
SIDE_SHORT = "SHORT"
VALID_SIDES = frozenset({SIDE_LONG, SIDE_SHORT})

TP_MODE_VPOC = "VPOC"
TP_MODE_R15 = "R15"
TP_MODE_VPOC_FALLBACK = "VPOC_FALLBACK"  # tente VPOC, fallback R15 si invalide


# ════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TriggerLevelV4:
    """Definition d'un trigger Bot 3 v4 (level asymetrique + dist_col + cur_vpoc col).

    Frozen : 1 instance partagee, immutable.
    """
    name: str
    side: str               # LONG ou SHORT
    dist_col: str           # colonne dist signed % du niveau
    family: str             # SWING / VWAP / MP
    asym_prob: float        # probabilite empirique conditional bounce (info doc)


@dataclass
class Bot3V4Params:
    """Configuration Bot 3 v4 (defaults = backtester valide empirique)."""
    # Touch detection
    # 24/05/2026 PM Jackson directive : "vision = ZONE de prix, pas pile".
    # touch_buf = 0.05% = ~15 ticks NQ → zone d'acceptance plus large.
    touch_buffer_pct: float = 0.05       # 0.05% = ~15 ticks NQ (= zone)
    # Cooldown / daily cap (anti-overtrading)
    cooldown_bars: int = 30              # min 30 bars entre 2 touches meme niveau
    max_per_level_per_day: int = 2       # cap quotidien
    # TP magnet VPOC
    tp_mode: str = TP_MODE_VPOC_FALLBACK # VPOC / R15 / VPOC_FALLBACK
    vpoc_min_dist_ticks: int = 5         # VPOC ignore si plus proche
    vpoc_max_dist_ticks: int = 200       # VPOC ignore si plus loin (safety cap)
    target_R: float = 1.5                # R-multiple fallback
    # Timeout position (post-entry, gere par paper mais engine doit save info)
    timeout_bars: int = 120
    # SL swing-based + fallback caps
    sl_buffer_ticks: int = 5             # buffer au-dela swing (LONG: - / SHORT: +)
    sl_fallback_ticks_nq: int = 15
    sl_fallback_ticks_es: int = 8
    sl_min_ticks: int = 5
    sl_max_ticks_nq: int = 30
    sl_max_ticks_es: int = 18
    # 24/05/2026 PM Jackson : SL ne doit JAMAIS etre dans zone deja visitee par
    # highs/lows recents (sinon SL touche par respiration normale). Override
    # le SL planned au-dela du max(high_N_bars) + buffer pour SHORT (symetrique LONG).
    sl_recent_extreme_lookback_bars: int = 5  # fenetre de protection recent extreme
    sl_recent_extreme_buffer_ticks: int = 3   # buffer additionnel au-dela extreme

    # 03/06/2026 FIX C Jackson — CAP ABSOLU post-override recent_extreme.
    # Trade Bot 3 v4 14:38:05 NQ LONG SL=191 ticks=$955 risk : override extreme
    # avec recent_low post-cassure violente -> SL catastrophique sans cap.
    # Solution : limite absolue meme apres override (R:R protege).
    # Calibre ~2x sl_max_ticks_legacy (compromis entre vrai swing et respiration).
    # NQ : 60 ticks = $300 max risk / trade (vs 30t legacy = $150).
    # ES : 30 ticks = $375 max risk / trade (vs 18t legacy = $225).
    sl_max_absolute_ticks_nq: int = 60
    sl_max_absolute_ticks_es: int = 30

    # 27/05/2026 ROLLBACK Jackson + code-reviewer : Plan C deploy etait BUG D'UNITES.
    # Backtest utilisait atr14_15min POINTS, code prod lit row["atr"] TICKS
    # (cf enricher_chain.py:819-820). Plan C reactiver UNIQUEMENT apres backtest
    # corrige + tests pytest pass.
    sl_hybrid_atr_enabled_nq: bool = False  # ROLLBACK 27/05 (bug unites atr)
    sl_hybrid_atr_enabled_es: bool = False
    sl_atr_floor_factor: float = 0.4
    sl_atr_cap_factor: float = 1.5
    # 24/05/2026 PM Jackson : filtre trend desactive par defaut (PATTERN 11 admis).
    # Cause : threshold 0.0005 invente sans verifier echelle reelle de vwap_slope_10
    # (qui est en POINTS par bar, observe 0.189 a 0.736, pas en pourcentage).
    # Decision : NE PAS activer ce filtre tant qu'il n'est pas backteste sur n>=100
    # trades. Calibrage proper J+1 (cf .claude/rules/critical-tasks-review.md
    # critere 1 + feedback_data_mining_trap : seuils sans backtest = pattern 11).
    # Si activation future via params override : threshold realiste >= 0.2 points/bar.
    trend_filter_enabled: bool = False
    trend_slope_threshold: float = 0.2  # placeholder en POINTS/bar (= ~0.7% / 10 bars NQ)

    # 25/05/2026 00:30 UTC Jackson : filtre footprint confirmation OR.
    # Decision souveraine MALGRE verdict 2 agents (market-analyst + ml-trainer)
    # NOGO sans backtest n>=100 + DSR Lopez. Pattern 11 risk accepte (paper Sim).
    # Pour SHORT : entry validee si n_long_dn_cluster_within_0_2pct >= 1 OR long_dn_bar == 1
    # Pour LONG  : entry validee si n_long_up_cluster_within_0_2pct >= 1 OR long_up_bar == 1
    # Logique : "ne SHORT que si footprint montre trace vendeuse (cluster bears
    # actifs OR long down bar)". Empirique 9/9 SHORTs Asia 24/05 = 0/9 auraient
    # passe ce filtre. Backtest n>=100 + DSR Lopez requis avant J+30 pour
    # confirmer/infirmer (cf feedback_data_mining_trap).
    footprint_filter_enabled: bool = True
    footprint_min_cluster_count: int = 1  # n_long_X_cluster >= cette valeur

    # 25/05/2026 02:00 UTC Jackson : filtre trend alignment (sign vwap_slope_10).
    # Audit empirique 24-25/05 sur 19 trades Bot 3 v4 : 16 trades vetoed par
    # ce filtre auraient sauve -$202.50 (toutes pertes). 3 trades passants
    # auraient genere +$26.50 (WR 67%, PF ~3.5).
    # Decision philosophique Jackson : "on trade dans le sens de la tendance".
    # Filtre = sign uniquement (PAS de threshold magique), aligne logique BN V4
    # require_long_trend_aligned. Anti pattern 11 car decision philosophique
    # souveraine + validation empirique cross-trades.
    # APPLIQUE UNIQUEMENT sur Bot 3 v4 (Bot 1 state machine garde son edge sans).
    trend_alignment_required: bool = True

    # 29/05/2026 Jackson directive : "TOUCH ne veut pas dire TRADE".
    # Audit forensique 9 trades closed 24-28/05 + sweep buffer/aggressor :
    #   F1 buffer=15t (close cote favorable au niveau) : 4/6 LOSS bloques, 3/3 WINS preserves
    #   F2 aggressor>=0.30 (vendeurs/acheteurs opposites) : +1 LOSS bloque
    #   F3 position_in_range : tue 1 WIN, REJETE.
    # Combo F1=15t + F2=0.30 : PnL backtest -$81.50 -> +$35.50 = delta +$117
    # Kill switch env vars : BOT3_V4_F1_DISABLE / BOT3_V4_F2_DISABLE pour rollback runtime.
    # Sample N=9 closed trades = minimal, monitorer J+7.
    require_close_favorable_side: bool = True       # F1 TOUCH != TRADE
    close_favorable_buffer_ticks: int = 15           # 15t NQ optimal backtest
    aggressor_opposite_filter_enabled: bool = True   # F2 aggressor opposite
    aggressor_opposite_threshold: float = 0.30       # 0.30 optimal backtest

    # 29/05 FIX F3 Jackson "TOUCH != TRADE confirmation" : state machine post-TOUCH.
    # Au lieu d'entrer instantanement au first_touch, attendre bar T+1 et exiger
    # close encore cote favorable du niveau (buffer 0 ticks = simple confirmation).
    # Backtest 51 trades 24-28/05 : 92% wins preserves (11/12), 39% losses bloques
    # (15/38), PnL delta +$266 sur 5 jours. Buffer 30t = 67% wins preserves mais
    # +$344 delta (plus strict, plus restrictif).
    # Anti-pattern 11 : c'est une REDEFINITION du concept TOUCH (= INTENT, ENTRY = CONFIRMATION),
    # equivalent au Wyckoff Spring test. Documentation explicite.
    require_confirmation_next_bar: bool = True
    confirmation_buffer_ticks: int = 0                # 0 = simple cote favorable
    confirmation_max_age_bars: int = 1                # entry max 1 bar apres TOUCH (sinon invalidate)

    # 03/06/2026 Jackson directive "conditionner au lieu de desactiver" :
    # Grid search 37 trades reels (`TMP_ANALYSIS/bot3_v4_combo_search.py`) :
    # - SWING_HIGH/LOW : 0/19 WR (10 + 9 trades, INSAUVABLE meme conditionne)
    # - Non-SWING 4 triggers : WR 56% PF 1.07 sans combo
    # - + combo gagnant LONG/SHORT : PF 5.76 / Net -$251 -> +$116 sur 9 trades
    # ATTENTION : N=9 = sample petit, monitor J+7 pour confirmer edge live.
    #
    # Niveau 1 : SWING family
    enable_swing_triggers: bool = False              # default OFF (data 0/19 WR)

    # Niveau 2 : combo conditions empiriques (4 autres triggers actives)
    # 03/06 SOIR : default OFF apres NOGO market-analyst (Pattern 11 score 9/10,
    # 4 hyperparams optimises sur N=37 -> N=9 = curve-fit textbook).
    # Strategie Option B : SWING off (defendable) + combo off (curve-fit), laisser
    # 4 triggers nus 30j en regime haussier pour mesurer baseline propre. Si PF>=1.0
    # sur N=30+ -> edge structurel confirme, REACTIVER combo apres backtest 60j+ DSR.
    # Code reste pour futur reactivation via env MIA_BOT3_V4_COMBO_ENABLED=1.
    # Conditions LONG (toutes obligatoires):
    #   pre_price_chg_5bars > -30 ticks  (anti falling knife)
    #   slope_p5 (vwap_slope_10 5 bars ago) > -2 (pas en chute persistente)
    #   aggressor_imbalance > -0.3        (vendeurs s'essoufflent)
    # Conditions SHORT miroir:
    #   pre_price_chg_5bars < +30 ticks  (anti rallye persistent)
    #   slope_p5 < +2                     (pas en hausse persistente)
    #   slope_d5 (delta_bar slope 5 bars) < 0 (delta s'inverse, exhaustion acheteurs)
    combo_filter_enabled: bool = False               # 03/06 SOIR : True -> False (Option B)
    combo_pre_price_max_ticks: int = 30              # |pre_price_chg_5| < 30 ticks
    combo_slope_p5_max_abs: float = 2.0              # |slope_p5| < 2 (pts/bar)
    combo_aggressor_long_min: float = -0.3           # LONG : aggressor > -0.3
    combo_slope_d5_short_max: float = 0.0            # SHORT : slope_d5 < 0

    def __post_init__(self):
        assert self.touch_buffer_pct > 0
        assert self.cooldown_bars >= 0
        assert self.max_per_level_per_day >= 1
        assert self.tp_mode in (TP_MODE_VPOC, TP_MODE_R15, TP_MODE_VPOC_FALLBACK)
        assert self.vpoc_min_dist_ticks > 0
        assert self.vpoc_max_dist_ticks > self.vpoc_min_dist_ticks
        assert self.target_R > 0
        assert self.timeout_bars > 0
        assert self.sl_buffer_ticks >= 0
        assert self.sl_min_ticks > 0
        assert self.sl_fallback_ticks_nq >= self.sl_min_ticks
        assert self.sl_fallback_ticks_es >= self.sl_min_ticks
        assert self.sl_max_ticks_nq >= self.sl_fallback_ticks_nq
        assert self.sl_max_ticks_es >= self.sl_fallback_ticks_es


@dataclass
class TriggerState:
    """Etat per-trigger : touch detection + cooldown + daily counter.

    29/05/2026 FIX Jackson : ajout pending_confirmation_bar_idx pour state machine
    confirmation post-TOUCH. Logique :
      - bar T : first_touch detected → set pending_confirmation_bar_idx = i, return None (no entry)
      - bar T+1 : si close encore cote favorable → ENTRY au close T+1 + clear pending
      - bar T+1 : si close cote defavorable OU > N bars apres → invalidate (clear pending)
    Backtest 51 trades 24-28/05 : preserve 92% wins (11/12), bloque 39% losses (15/38),
    PnL delta +$266 sur 5 jours.
    """
    prev_in_zone: bool = False
    last_touch_bar_idx: int = -10_000   # init très bas pour ne pas bloquer 1er touch
    touches_today: int = 0
    # 29/05 FIX : state confirmation post-TOUCH
    pending_confirmation_bar_idx: int = -1   # -1 = pas de pending
    pending_level_price: float = 0.0
    pending_side: str = ""                   # "LONG" / "SHORT"


@dataclass(frozen=True)
class EntryDecisionV4:
    """Decision d'entrée v4 (immutable)."""
    side: str
    level_name: str
    level_family: str
    asym_prob: float                # prob empirique conditional bounce
    entry_close: float
    sl_price: float
    tp_price: float
    sl_ticks: int
    swing_used: bool
    tp_mode: str                    # "VPOC" ou "R15"
    vpoc_value: Optional[float]     # cur_vpoc utilise (None si fallback R15)
    bar_idx: int
    bar_ts: str


# ════════════════════════════════════════════════════════════════════════
# DEFAULT TRIGGER DEFS (6 triggers empiriques)
# ════════════════════════════════════════════════════════════════════════

# 29/05 FIX Jackson : mapping LEVEL NAME -> column live_enriched contenant prix
# du niveau. Permet au filter F1 (close cote favorable) de comparer close vs prix.
LEVEL_NAME_TO_PRICE_COL: dict = {
    "SWING_HIGH": "_last_swing_high_price",
    "SWING_LOW": "_last_swing_low_price",
    "CUR_VAH": "cur_vah",
    "CUR_VAL": "cur_val",
    "CUR_VPOC": "cur_vpoc",
    "PREV_VAH": "prev_vah",
    "PREV_VAL": "prev_val",
    "PREV_VPOC": "prev_vpoc",
    "VWAP_D_SD2U": "vwap_d_sd2u",
    "VWAP_D_SD2D": "vwap_d_sd2d",
    "VWAP_D_SD1U": "vwap_d_sd1u",
    "VWAP_D_SD1D": "vwap_d_sd1d",
}


def build_default_triggers(enable_swing: bool = False) -> List[TriggerLevelV4]:
    """6 triggers asymetriques empiriques (54K bounces 194j analyse).

    Source : `LOGS/reaction_zones_analysis/REPORT_COMPARATIF.md`.

    Args:
        enable_swing : si False (default 03/06), SWING_HIGH/LOW exclus.
                       Backtest 37 trades reels : SWING 0/19 WR insauvable.
    """
    triggers = [
        # LONG triggers
        TriggerLevelV4(
            name="VWAP_D_SD2D", side=SIDE_LONG,
            dist_col="dist_vwap_d_sd2d_pct", family="VWAP", asym_prob=0.72,
        ),
        TriggerLevelV4(
            name="CUR_VAL", side=SIDE_LONG,
            dist_col="dist_cur_val_pct", family="MP", asym_prob=0.61,
        ),
        # SHORT triggers
        TriggerLevelV4(
            name="VWAP_D_SD2U", side=SIDE_SHORT,
            dist_col="dist_vwap_d_sd2u_pct", family="VWAP", asym_prob=0.72,
        ),
        TriggerLevelV4(
            name="CUR_VAH", side=SIDE_SHORT,
            dist_col="dist_cur_vah_pct", family="MP", asym_prob=0.63,
        ),
    ]
    if enable_swing:
        triggers.insert(0, TriggerLevelV4(
            name="SWING_LOW", side=SIDE_LONG,
            dist_col="dist_last_swing_low_pct", family="SWING", asym_prob=0.81,
        ))
        triggers.append(TriggerLevelV4(
            name="SWING_HIGH", side=SIDE_SHORT,
            dist_col="dist_last_swing_high_pct", family="SWING", asym_prob=0.76,
        ))
    return triggers


# ════════════════════════════════════════════════════════════════════════
# ENGINE
# ════════════════════════════════════════════════════════════════════════

class Bot3V4Engine:
    """Pure logic touch detection Bot 3 v4 data-driven.

    Architecture :
      - 1 instance par symbol
      - 6 trigger detectors internes (touch + cooldown + daily cap)
      - process_bar(row, bar_ts, bar_day) → EntryDecisionV4 ou None
      - Reset day boundary auto

    Anti-look-ahead :
      - row courante uniquement
      - TriggerState maintient prev_in_zone, last_touch_bar_idx, touches_today
      - bar_idx interne (reset day)

    TP MAGNET CRITIQUE :
      - Si cur_vpoc valide ET cote correct ET dist [5-200t] → TP = cur_vpoc
      - Sinon TP = entry +/- 1.5 * sl_ticks * tick (fallback R-multiple)
      - R1.5 fixe seul = PF 0.74 backtest (cassé)
      - VPOC magnet = PF 1.033 backtest (signal)

    Usage :
        engine = Bot3V4Engine(symbol="NQ", triggers=build_default_triggers())
        for row in jsonl_stream:
            decision = engine.process_bar(row, row["ts_event_iso"], row["session_date"])
            if decision is not None:
                paper.execute(decision)
    """

    def __init__(
        self,
        symbol: str,
        triggers: List[TriggerLevelV4],
        params: Optional[Bot3V4Params] = None,
        log_fn: Optional[Any] = None,
    ):
        """log_fn : injection logger pour tracability (TOUCH_FILTERED_COOLDOWN /
        DAILY_CAP). Si None, transitions silencieuses (back-compat tests).
        """
        assert symbol in TICK_BY_SYMBOL, \
            f"Symbol {symbol} unsupported (allowed: {list(TICK_BY_SYMBOL.keys())})"
        assert len(triggers) > 0, "triggers must contain at least 1 trigger"

        self.symbol = symbol
        self.triggers = list(triggers)
        self.params = params or Bot3V4Params()
        self.tick_size = TICK_BY_SYMBOL[symbol]
        self.log_fn = log_fn  # injection tracability filters

        # State per trigger
        self._trigger_states: Dict[str, TriggerState] = {
            t.name: TriggerState() for t in self.triggers
        }

        # Bar idx counter (reset day)
        self._bar_idx: int = -1
        self._current_day: Optional[str] = None

        # 24/05/2026 PM Jackson : rolling buffer recent highs/lows pour override SL.
        # Lookback configurable via params.sl_recent_extreme_lookback_bars (default 5).
        from collections import deque
        _lookback = self.params.sl_recent_extreme_lookback_bars
        self._recent_highs: deque = deque(maxlen=_lookback)
        self._recent_lows: deque = deque(maxlen=_lookback)

        # Stats lifetime
        self._n_bars_processed: int = 0
        self._n_touches_raw: int = 0
        # 24/05/2026 PM Jackson : counters new filters
        self._n_touches_filtered_trend: int = 0
        self._n_sl_overrides_recent_extreme: int = 0
        # 25/05/2026 Jackson : counter filter footprint confirmation
        self._n_touches_filtered_footprint: int = 0
        # 25/05/2026 02:00 UTC Jackson : counter filter trend alignment (sign)
        self._n_touches_filtered_trend_misalign: int = 0
        self._n_touches_filtered_cooldown: int = 0
        self._n_touches_filtered_daily_cap: int = 0
        # 29/05/2026 Jackson : counters fix F1 (TOUCH != TRADE) + F2 (aggro opposite)
        self._n_touches_filtered_close_unfavorable: int = 0
        self._n_touches_filtered_aggressor_opposite: int = 0
        # R3+R4 review code-reviewer : compteurs bypass silent (level_price None / aggro None)
        # = anti VALIDATION_MISS (si fallback declenche, on doit le voir J+1).
        self._n_touches_f1_bypassed_no_level_price: int = 0
        self._n_touches_f2_bypassed_no_aggressor: int = 0
        # 03/06 Jackson : combo filter counters (anti curve-fit observ)
        self._n_filtered_combo_pre_price: int = 0
        self._n_filtered_combo_slope_p5: int = 0
        self._n_filtered_combo_aggressor: int = 0
        self._n_filtered_combo_slope_d5: int = 0
        # 03/06 : buffer rolling close pour pre_price_chg_5bars
        self._close_buffer: List[float] = []
        self._n_entries_emitted: int = 0
        self._n_tp_vpoc_used: int = 0
        self._n_tp_r15_fallback: int = 0
        self._n_day_resets: int = 0

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def reset_day(self, new_day: str) -> int:
        """Reset all trigger states au changement de jour.

        Returns : nb_states_resets (touches_today != 0 ou prev_in_zone True)
        """
        n_active = sum(
            1 for s in self._trigger_states.values()
            if s.touches_today > 0 or s.prev_in_zone
        )
        # Reset compteurs daily mais PAS prev_in_zone (recalcule a la bar courante)
        for s in self._trigger_states.values():
            s.touches_today = 0
            s.last_touch_bar_idx = -10_000
            s.prev_in_zone = False  # safe : recalcule au prochain process_bar
            # 29/05/2026 FIX BLOQUANT 1 code-reviewer F3 : clear pending state au
            # day boundary, sinon bug fantome entry (age=neg gros, branche check
            # confirmation passe a la 1ere bar du nouveau jour avec level_price
            # d'hier → fausse ENTRY sur niveau obsolete). Detected pre-deploy.
            s.pending_confirmation_bar_idx = -1
            s.pending_level_price = 0.0
            s.pending_side = ""
        self._bar_idx = -1
        self._current_day = new_day
        self._n_day_resets += 1
        return n_active

    def process_bar(
        self,
        row: Union[Dict[str, Any], Any],
        bar_ts_iso: str,
        bar_day: str,
    ) -> Optional[EntryDecisionV4]:
        """Process une nouvelle bar live. Retourne EntryDecisionV4 si touch valide.

        Args:
            row : dict OR pd.Series avec keys minimum :
                close, _last_swing_low/high_price, cur_vpoc,
                dist_*_pct (pour chaque trigger.dist_col)
            bar_ts_iso : ISO timestamp UTC
            bar_day : YYYYMMDD pour day boundary detection

        Returns:
            EntryDecisionV4 si touch valide passe les filtres (cooldown + daily cap)
            None sinon. Si multi-touches meme bar : retourne le 1er (FIFO triggers).
        """
        # 1. Day boundary
        if bar_day != self._current_day:
            self.reset_day(bar_day)

        # 2. Bar idx counter
        self._bar_idx += 1
        self._n_bars_processed += 1

        # 3. Extract close defensively
        close = self._safe_float(self._row_get(row, "close"))
        if close is None or close <= 0:
            return None

        # 3a. 03/06/2026 : Maintenir buffer rolling close (10 bars) pour
        # calcul pre_price_chg_5bars (combo filter).
        self._close_buffer.append(close)
        if len(self._close_buffer) > 10:
            self._close_buffer.pop(0)

        # 3bis. 24/05/2026 PM Jackson : push high/low dans rolling buffer pour
        # override SL (eviter SL place dans zone recemment visitee).
        high = self._safe_float(self._row_get(row, "high"))
        low = self._safe_float(self._row_get(row, "low"))
        if high is not None and high > 0:
            self._recent_highs.append(high)
        if low is not None and low > 0:
            self._recent_lows.append(low)

        # 4. Iterate triggers, retourner 1ere EntryDecisionV4 valide
        for trig in self.triggers:
            decision = self._evaluate_trigger(trig, row, close, bar_ts_iso)
            if decision is not None:
                self._n_entries_emitted += 1
                return decision

        return None

    def get_trigger_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Retourne {trigger_name: {prev_in_zone, last_touch, touches_today}}."""
        return {
            name: {
                "prev_in_zone": s.prev_in_zone,
                "last_touch_bar_idx": s.last_touch_bar_idx,
                "touches_today": s.touches_today,
            }
            for name, s in self._trigger_states.items()
        }

    def get_stats(self) -> Dict[str, int]:
        return {
            "n_bars_processed": self._n_bars_processed,
            "n_touches_raw": self._n_touches_raw,
            "n_touches_filtered_cooldown": self._n_touches_filtered_cooldown,
            "n_touches_filtered_daily_cap": self._n_touches_filtered_daily_cap,
            "n_entries_emitted": self._n_entries_emitted,
            "n_tp_vpoc_used": self._n_tp_vpoc_used,
            "n_tp_r15_fallback": self._n_tp_r15_fallback,
            "n_day_resets": self._n_day_resets,
            "current_bar_idx": self._bar_idx,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 03/06/2026 Jackson : combo filter pre-entry (anti falling knife / rallye persistent)
    # ─────────────────────────────────────────────────────────────────────

    def _combo_filter_pass(self, row: Any, side: str, level_name: str) -> bool:
        """Verifie conditions combo empirique avant emission EntryDecisionV4.

        Conditions LONG :
          - pre_price_chg_5bars > -30 ticks  (anti falling knife)
          - |vwap_slope_10| < 2.0            (pas trend violent)
          - aggressor_imbalance > -0.3       (vendeurs s'essoufflent)
        Conditions SHORT miroir :
          - pre_price_chg_5bars < +30 ticks  (anti rallye persistent)
          - |vwap_slope_10| < 2.0
          - delta_bar < 0 (delta s'inverse, proxy slope_d5 < 0)

        Backtest 37 trades reels : combo + SWING desactives -> PF 0.40 -> 5.76, Net +$116.
        Sample N=9 = fragile, monitorer J+7.
        """
        if not self.params.combo_filter_enabled:
            return True

        p = self.params
        tick = self.tick_size

        # 1. pre_price_chg_5bars (= close[-1] - close[-6] / tick)
        if len(self._close_buffer) >= 6:
            close_now = self._close_buffer[-1]
            close_5_ago = self._close_buffer[-6]
            pre_price_chg_t = (close_now - close_5_ago) / tick
            if side == SIDE_LONG and pre_price_chg_t <= -p.combo_pre_price_max_ticks:
                self._n_filtered_combo_pre_price += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_PRE_PRICE",
                                    sym=self.symbol, level=level_name, side=side,
                                    pre_price_chg_t=round(pre_price_chg_t, 1),
                                    threshold=-p.combo_pre_price_max_ticks)
                    except Exception:
                        pass
                return False
            elif side == SIDE_SHORT and pre_price_chg_t >= p.combo_pre_price_max_ticks:
                self._n_filtered_combo_pre_price += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_PRE_PRICE",
                                    sym=self.symbol, level=level_name, side=side,
                                    pre_price_chg_t=round(pre_price_chg_t, 1),
                                    threshold=p.combo_pre_price_max_ticks)
                    except Exception:
                        pass
                return False

        # 2. |vwap_slope_10| < 2.0 (pas trend violent dans le sens contraire)
        slope = self._safe_float(self._row_get(row, "vwap_slope_10"))
        if slope is not None:
            if side == SIDE_LONG and slope < -p.combo_slope_p5_max_abs:
                self._n_filtered_combo_slope_p5 += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_SLOPE",
                                    sym=self.symbol, level=level_name, side=side,
                                    slope=round(slope, 3),
                                    threshold=-p.combo_slope_p5_max_abs)
                    except Exception:
                        pass
                return False
            elif side == SIDE_SHORT and slope > p.combo_slope_p5_max_abs:
                self._n_filtered_combo_slope_p5 += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_SLOPE",
                                    sym=self.symbol, level=level_name, side=side,
                                    slope=round(slope, 3),
                                    threshold=p.combo_slope_p5_max_abs)
                    except Exception:
                        pass
                return False

        # 3. aggressor (LONG) ou delta_bar (SHORT)
        if side == SIDE_LONG:
            aggro = self._safe_float(self._row_get(row, "aggressor_imbalance"))
            if aggro is not None and aggro <= p.combo_aggressor_long_min:
                self._n_filtered_combo_aggressor += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_AGGRESSOR",
                                    sym=self.symbol, level=level_name, side=side,
                                    aggressor=round(aggro, 3),
                                    threshold=p.combo_aggressor_long_min)
                    except Exception:
                        pass
                return False
        else:  # SHORT : delta_bar < 0 (proxy slope_d5 < 0)
            delta_bar = self._safe_float(self._row_get(row, "delta_bar"))
            if delta_bar is not None and delta_bar >= p.combo_slope_d5_short_max:
                self._n_filtered_combo_slope_d5 += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_VETO_COMBO_DELTA_SHORT",
                                    sym=self.symbol, level=level_name, side=side,
                                    delta_bar=round(delta_bar, 1),
                                    threshold=p.combo_slope_d5_short_max)
                    except Exception:
                        pass
                return False

        return True

    # ─────────────────────────────────────────────────────────────────────
    # Trigger evaluation
    # ─────────────────────────────────────────────────────────────────────

    def _evaluate_trigger(
        self,
        trig: TriggerLevelV4,
        row: Any,
        close: float,
        bar_ts_iso: str,
    ) -> Optional[EntryDecisionV4]:
        """Evalue 1 trigger : detect touch + filters + emit EntryDecisionV4."""
        state = self._trigger_states[trig.name]
        i = self._bar_idx

        # 29/05/2026 FIX F3 Jackson : check PENDING CONFIRMATION en premier.
        # Si touche detectee a bar T precedente, on est maintenant a T+1 et on
        # decide ENTRY (close cote favorable) OR INVALIDATE.
        # Backtest 51 trades : 92% wins preserves, +$266 delta.
        if state.pending_confirmation_bar_idx >= 0:
            age = i - state.pending_confirmation_bar_idx
            session_id_pending = f"{self.symbol}_{trig.name}_pending_{state.pending_confirmation_bar_idx}"

            if age > self.params.confirmation_max_age_bars:
                # Pending stale → invalidate sans entry
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_TOUCH_CONFIRMATION_TIMEOUT",
                                    sym=self.symbol, level=trig.name,
                                    side=state.pending_side, age_bars=age,
                                    max_age=self.params.confirmation_max_age_bars,
                                    session_id=session_id_pending)
                    except Exception:
                        pass
                state.pending_confirmation_bar_idx = -1
                state.pending_level_price = 0.0
                state.pending_side = ""
                # Continue normal flow ci-dessous (peut-etre new touch)
            else:
                # Check close favorable cote
                buf = self.params.confirmation_buffer_ticks * self.tick_size
                confirmed = False
                if state.pending_side == SIDE_SHORT and close < state.pending_level_price - buf:
                    confirmed = True
                elif state.pending_side == SIDE_LONG and close > state.pending_level_price + buf:
                    confirmed = True

                if confirmed:
                    # ENTRY confirmee a close courant (T+1)
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_CONFIRMED_ENTRY",
                                        sym=self.symbol, level=trig.name,
                                        side=state.pending_side,
                                        close=round(close, 4),
                                        level_price=round(state.pending_level_price, 4),
                                        age_bars=age,
                                        session_id=session_id_pending)
                        except Exception:
                            pass
                    # Recompute SL/TP avec close T+1 (different de close T)
                    sl_price, tp_price, sl_ticks, swing_used, tp_mode, vpoc_value = self._compute_sl_tp(
                        row, close, state.pending_side
                    )
                    sl_price, sl_ticks = self._override_sl_recent_extreme(
                        close, state.pending_side, sl_price, sl_ticks, trig.name, session_id_pending,
                    )
                    if tp_mode == TP_MODE_VPOC:
                        self._n_tp_vpoc_used += 1
                    else:
                        self._n_tp_r15_fallback += 1
                    # 03/06 Jackson : combo filter pre-entry
                    if not self._combo_filter_pass(row, state.pending_side, trig.name):
                        # Veto combo : clear pending + skip (log emitted dans helper)
                        state.pending_confirmation_bar_idx = -1
                        state.pending_level_price = 0.0
                        state.pending_side = ""
                        return None
                    # Update state pour eviter re-touch immediat
                    state.last_touch_bar_idx = i
                    state.touches_today += 1
                    # Stocker side avant clear pour le return
                    confirmed_side = state.pending_side
                    state.pending_confirmation_bar_idx = -1
                    state.pending_level_price = 0.0
                    state.pending_side = ""
                    self._n_entries_emitted += 1
                    return EntryDecisionV4(
                        side=confirmed_side,
                        level_name=trig.name,
                        level_family=trig.family,
                        asym_prob=trig.asym_prob,
                        entry_close=close,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        sl_ticks=sl_ticks,
                        swing_used=swing_used,
                        tp_mode=tp_mode,
                        vpoc_value=vpoc_value,
                        bar_idx=i,
                        bar_ts=bar_ts_iso,
                    )
                else:
                    # Close cote defavorable → invalidate
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_CONFIRMATION_INVALIDATED",
                                        sym=self.symbol, level=trig.name,
                                        side=state.pending_side,
                                        close=round(close, 4),
                                        level_price=round(state.pending_level_price, 4),
                                        buffer_ticks=self.params.confirmation_buffer_ticks,
                                        session_id=session_id_pending)
                        except Exception:
                            pass
                    state.pending_confirmation_bar_idx = -1
                    state.pending_level_price = 0.0
                    state.pending_side = ""
                    # Continue normal flow ci-dessous (peut-etre new touch)

        # Extract dist_pct
        dist_pct_raw = self._row_get(row, trig.dist_col)
        dist_pct = self._safe_float(dist_pct_raw)
        if dist_pct is None:
            return None

        abs_dist = abs(dist_pct)
        in_zone = abs_dist <= self.params.touch_buffer_pct
        first_touch = in_zone and not state.prev_in_zone
        # Update prev_in_zone immediat
        state.prev_in_zone = in_zone

        if not first_touch:
            return None

        # Raw touch detected
        self._n_touches_raw += 1
        # Fix R3 review tracability iter1 : level_session_id pour correler
        # touch raw → filtered OR entry. Bar_idx du touch = unique.
        session_id = f"{self.symbol}_{trig.name}_{i}"

        # Filter 1 : cooldown
        if i - state.last_touch_bar_idx < self.params.cooldown_bars:
            self._n_touches_filtered_cooldown += 1
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V4_TOUCH_FILTERED_COOLDOWN",
                                sym=self.symbol, level=trig.name,
                                bars_since_last=i - state.last_touch_bar_idx,
                                cooldown=self.params.cooldown_bars,
                                session_id=session_id)
                except Exception:
                    pass
            return None

        # Filter 2 : daily cap
        if state.touches_today >= self.params.max_per_level_per_day:
            self._n_touches_filtered_daily_cap += 1
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V4_TOUCH_FILTERED_DAILY_CAP",
                                sym=self.symbol, level=trig.name,
                                count_today=state.touches_today,
                                cap=self.params.max_per_level_per_day,
                                session_id=session_id)
                except Exception:
                    pass
            return None

        # Touch valide → entry signal

        # 25/05/2026 Jackson : filtre footprint confirmation OR.
        # SHORT autorise si n_long_dn_cluster >= 1 OR long_dn_bar == 1
        # LONG autorise si n_long_up_cluster >= 1 OR long_up_bar == 1
        # Decision souveraine malgre 2 agents NOGO sans backtest. Pattern 11
        # risk accepte (paper Sim, traceability totale).
        if self.params.footprint_filter_enabled:
            min_cluster = self.params.footprint_min_cluster_count
            if trig.side == SIDE_SHORT:
                cluster_dn = self._safe_float(
                    self._row_get(row, "n_long_dn_cluster_within_0_2pct")
                )
                long_dn = self._safe_float(self._row_get(row, "long_dn_bar"))
                clusters_present = (cluster_dn is not None and cluster_dn >= min_cluster)
                long_bar_present = (long_dn is not None and long_dn == 1.0)
                if not (clusters_present or long_bar_present):
                    self._n_touches_filtered_footprint += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_FOOTPRINT",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side,
                                        n_cluster_dn=cluster_dn,
                                        long_dn_bar=long_dn,
                                        min_cluster=min_cluster,
                                        session_id=session_id)
                        except Exception:
                            pass
                    return None
            elif trig.side == SIDE_LONG:
                cluster_up = self._safe_float(
                    self._row_get(row, "n_long_up_cluster_within_0_2pct")
                )
                long_up = self._safe_float(self._row_get(row, "long_up_bar"))
                clusters_present = (cluster_up is not None and cluster_up >= min_cluster)
                long_bar_present = (long_up is not None and long_up == 1.0)
                if not (clusters_present or long_bar_present):
                    self._n_touches_filtered_footprint += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_FOOTPRINT",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side,
                                        n_cluster_up=cluster_up,
                                        long_up_bar=long_up,
                                        min_cluster=min_cluster,
                                        session_id=session_id)
                        except Exception:
                            pass
                    return None

        # 25/05/2026 02:00 UTC Jackson : filtre trend alignment (SIGN ONLY).
        # Cumul avec filter footprint (logique AND). Apres footprint OK,
        # verifier que la tendance VWAP est ALIGNE avec le side du trade.
        # SHORT autorise uniquement si vwap_slope_10 < 0 (downtrend).
        # LONG  autorise uniquement si vwap_slope_10 > 0 (uptrend).
        # PAS de threshold magique : juste le sign (aligne BN V4 require_long_trend_aligned).
        # Audit empirique 24-25/05 sur 19 trades : 16 vetoed (toutes pertes -$202.50),
        # 3 passants (WR 67%, PF ~3.5). Decision philosophique Jackson souveraine.
        # APPLIQUE UNIQUEMENT Bot 3 v4 (Bot 1 state machine garde son edge sans).
        if self.params.trend_alignment_required:
            vwap_slope = self._safe_float(self._row_get(row, "vwap_slope_10"))
            if vwap_slope is not None:
                veto_align = False
                if trig.side == SIDE_SHORT and vwap_slope >= 0:
                    veto_align = True
                elif trig.side == SIDE_LONG and vwap_slope <= 0:
                    veto_align = True
                if veto_align:
                    self._n_touches_filtered_trend_misalign += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_TREND_MISALIGN",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side,
                                        vwap_slope=round(vwap_slope, 4),
                                        session_id=session_id)
                        except Exception:
                            pass
                    return None

        # 24/05/2026 PM Jackson : trend filter avant entry. Ne pas SHORT en
        # uptrend (vwap_slope_10 > threshold positif) ni LONG en downtrend.
        # Audit empirique 24/05 : 10/11 trades SL hit = 100% contre-trend Asia.
        if self.params.trend_filter_enabled:
            vwap_slope = self._safe_float(self._row_get(row, "vwap_slope_10"))
            if vwap_slope is not None:
                thr = self.params.trend_slope_threshold
                veto_trend = False
                if trig.side == SIDE_SHORT and vwap_slope > thr:
                    veto_trend = True
                elif trig.side == SIDE_LONG and vwap_slope < -thr:
                    veto_trend = True
                if veto_trend:
                    self._n_touches_filtered_trend += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_TREND",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side, vwap_slope=round(vwap_slope, 6),
                                        threshold=thr, session_id=session_id)
                        except Exception:
                            pass
                    return None

        # 29/05/2026 FIX F1 Jackson : TOUCH != TRADE.
        # Exiger close de la bar TOUCH du cote FAVORABLE au niveau (anti-breakout).
        # SHORT : close < level_price - buffer (respect, pas breakout)
        # LONG  : close > level_price + buffer (respect, pas falling knife)
        # Sauve 4/6 LOSS sur backtest 9 trades 24-28/05, 0 WIN tue. Delta +$92.50.
        # Tick: NQ/ES=0.25, MGC=0.10 → factor universal via self.tick_size.
        if self.params.require_close_favorable_side:
            level_col = LEVEL_NAME_TO_PRICE_COL.get(trig.name)
            level_price = None
            if level_col:
                level_price = self._safe_float(self._row_get(row, level_col))
            if level_price is not None and level_price > 0:
                buf = self.params.close_favorable_buffer_ticks * self.tick_size
                veto_close = False
                if trig.side == SIDE_SHORT and close >= level_price - buf:
                    veto_close = True   # close au-dessus / pile sous = breakout risk
                elif trig.side == SIDE_LONG and close <= level_price + buf:
                    veto_close = True
                if veto_close:
                    self._n_touches_filtered_close_unfavorable += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_CLOSE_UNFAVORABLE",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side,
                                        close=round(close, 4),
                                        level_price=round(level_price, 4),
                                        buffer_ticks=self.params.close_favorable_buffer_ticks,
                                        session_id=session_id)
                        except Exception:
                            pass
                    return None
            else:
                # R3 review : bypass silent traçé (anti VALIDATION_MISS).
                self._n_touches_f1_bypassed_no_level_price += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_TOUCH_F1_BYPASSED_NO_LEVEL_PRICE",
                                    sym=self.symbol, level=trig.name,
                                    side=trig.side, level_col=level_col,
                                    session_id=session_id)
                    except Exception:
                        pass

        # 29/05/2026 FIX F2 Jackson : aggressor opposite veto.
        # Exiger que aggressor_imbalance ne soit pas extreme dans le sens INVERSE
        # de la direction du trade. Permet d'eviter "LONG contre vendeurs agressifs"
        # ou "SHORT contre acheteurs agressifs" = setups souvent stop hunts.
        # Sauve 1 LOSS additionnel sur backtest 9 trades. Delta cumul F1+F2 +$117.
        if self.params.aggressor_opposite_filter_enabled:
            aggro = self._safe_float(self._row_get(row, "aggressor_imbalance"))
            if aggro is not None:
                thr = self.params.aggressor_opposite_threshold
                veto_aggro = False
                if trig.side == SIDE_LONG and aggro < -thr:
                    veto_aggro = True   # vendeurs agressifs vs LONG
                elif trig.side == SIDE_SHORT and aggro > thr:
                    veto_aggro = True   # acheteurs agressifs vs SHORT
                if veto_aggro:
                    self._n_touches_filtered_aggressor_opposite += 1
                    if self.log_fn is not None:
                        try:
                            self.log_fn("BOT3_V4_TOUCH_FILTERED_AGGRESSOR_OPPOSITE",
                                        sym=self.symbol, level=trig.name,
                                        side=trig.side,
                                        aggressor_imbalance=round(aggro, 4),
                                        threshold=thr, session_id=session_id)
                        except Exception:
                            pass
                    return None
            else:
                # R4 review : bypass silent traçé (anti VALIDATION_MISS).
                self._n_touches_f2_bypassed_no_aggressor += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_TOUCH_F2_BYPASSED_NO_AGGRESSOR",
                                    sym=self.symbol, level=trig.name,
                                    side=trig.side, session_id=session_id)
                    except Exception:
                        pass

        state.last_touch_bar_idx = i
        state.touches_today += 1

        # 29/05/2026 FIX F3 Jackson : require_confirmation_next_bar.
        # Au lieu d'entry direct au TOUCH, SET pending + return None.
        # Bar T+1 sera evaluee via le check pending au debut de _evaluate_trigger.
        # Permet de filtrer breakouts/breakdowns sur la bar du touch lui-meme.
        if self.params.require_confirmation_next_bar:
            # Recuperer level_price pour le pending
            level_col = LEVEL_NAME_TO_PRICE_COL.get(trig.name)
            level_price = None
            if level_col:
                level_price = self._safe_float(self._row_get(row, level_col))
            if level_price is not None and level_price > 0:
                state.pending_confirmation_bar_idx = i
                state.pending_level_price = float(level_price)
                state.pending_side = trig.side
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_TOUCH_PENDING_CONFIRMATION",
                                    sym=self.symbol, level=trig.name,
                                    side=trig.side,
                                    close=round(close, 4),
                                    level_price=round(level_price, 4),
                                    bar_idx=i, session_id=session_id)
                    except Exception:
                        pass
                return None
            # Si pas de level_price : continue avec entry direct (bypass confirmation)

        # Compute SL / TP
        sl_price, tp_price, sl_ticks, swing_used, tp_mode, vpoc_value = self._compute_sl_tp(
            row, close, trig.side
        )

        # 24/05/2026 PM Jackson : override SL si dans zone deja visitee par
        # recent highs/lows (incident 10/11 trades SL hit en uptrend Asia).
        sl_price, sl_ticks = self._override_sl_recent_extreme(
            close, trig.side, sl_price, sl_ticks, trig.name, session_id,
        )

        # Stats TP mode
        if tp_mode == TP_MODE_VPOC:
            self._n_tp_vpoc_used += 1
        else:
            self._n_tp_r15_fallback += 1

        # 03/06 Jackson : combo filter pre-entry (path direct sans pending confirmation)
        if not self._combo_filter_pass(row, trig.side, trig.name):
            return None  # log emitted dans helper

        return EntryDecisionV4(
            side=trig.side,
            level_name=trig.name,
            level_family=trig.family,
            asym_prob=trig.asym_prob,
            entry_close=close,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_ticks=sl_ticks,
            swing_used=swing_used,
            tp_mode=tp_mode,
            vpoc_value=vpoc_value,
            bar_idx=i,
            bar_ts=bar_ts_iso,
        )

    # ─────────────────────────────────────────────────────────────────────
    # SL / TP calc avec VPOC magnet
    # ─────────────────────────────────────────────────────────────────────

    def _compute_sl_tp(
        self,
        row: Any,
        entry_close: float,
        side: str,
    ) -> Tuple[float, float, int, bool, str, Optional[float]]:
        """Compute SL (swing-based) + TP (VPOC magnet ou R-multiple fallback).

        Returns (sl_price, tp_price, sl_ticks, swing_used, tp_mode, vpoc_value)
        """
        tick = self.tick_size
        p = self.params
        sl_fallback = (
            p.sl_fallback_ticks_nq if self.symbol == "NQ" else p.sl_fallback_ticks_es
        )
        sl_max = p.sl_max_ticks_nq if self.symbol == "NQ" else p.sl_max_ticks_es
        sl_min = p.sl_min_ticks
        sl_buf = p.sl_buffer_ticks

        # 27/05 Jackson : Plan C SL hybride ATR-based pour NQ (backtest 14j valide).
        # Si NQ ET sl_hybrid_atr_enabled_nq -> SL = max(swing+buf, floor*atr/tick) clip cap*atr/tick.
        # Sinon (ES ou ATR null) -> Config A actuel.
        hybrid_enabled = (
            (self.symbol == "NQ" and p.sl_hybrid_atr_enabled_nq) or
            (self.symbol == "ES" and p.sl_hybrid_atr_enabled_es)
        )
        atr_pts = self._safe_float(self._row_get(row, "atr")) if hybrid_enabled else None

        if hybrid_enabled and atr_pts is not None and atr_pts > 0:
            # Plan C hybride variante B (floor=0.4, cap=1.5)
            atr_floor_ticks = (p.sl_atr_floor_factor * atr_pts) / tick
            atr_cap_ticks = (p.sl_atr_cap_factor * atr_pts) / tick
            fallback_reason_hybrid = "atr_floor"
            swing_raw_ticks = None

            if side == SIDE_LONG:
                swing_low = self._safe_float(self._row_get(row, "_last_swing_low_price"))
                if swing_low is not None and swing_low > 0 and swing_low < entry_close:
                    swing_dist = (entry_close - swing_low) / tick + sl_buf
                    swing_raw_ticks = swing_dist
                    sl_ticks_raw = max(swing_dist, atr_floor_ticks)
                    fallback_reason_hybrid = "swing_or_atr_floor" if swing_dist >= atr_floor_ticks else "atr_floor"
                else:
                    sl_ticks_raw = atr_floor_ticks
                    fallback_reason_hybrid = "atr_floor_no_swing"
                if sl_ticks_raw > atr_cap_ticks:
                    sl_ticks_raw = atr_cap_ticks
                    fallback_reason_hybrid = "atr_cap"
                sl_ticks = max(int(round(sl_ticks_raw)), sl_min)
                sl_price = entry_close - sl_ticks * tick
                swing_used = (fallback_reason_hybrid == "swing_or_atr_floor")
            else:  # SHORT
                swing_high = self._safe_float(self._row_get(row, "_last_swing_high_price"))
                if swing_high is not None and swing_high > 0 and swing_high > entry_close:
                    swing_dist = (swing_high - entry_close) / tick + sl_buf
                    swing_raw_ticks = swing_dist
                    sl_ticks_raw = max(swing_dist, atr_floor_ticks)
                    fallback_reason_hybrid = "swing_or_atr_floor" if swing_dist >= atr_floor_ticks else "atr_floor"
                else:
                    sl_ticks_raw = atr_floor_ticks
                    fallback_reason_hybrid = "atr_floor_no_swing"
                if sl_ticks_raw > atr_cap_ticks:
                    sl_ticks_raw = atr_cap_ticks
                    fallback_reason_hybrid = "atr_cap"
                sl_ticks = max(int(round(sl_ticks_raw)), sl_min)
                sl_price = entry_close + sl_ticks * tick
                swing_used = (fallback_reason_hybrid == "swing_or_atr_floor")

            # Emit log
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V4_SL_FALLBACK_REASON",
                                sym=self.symbol, side=side,
                                reason=fallback_reason_hybrid,
                                sl_ticks=sl_ticks,
                                swing_raw_ticks=swing_raw_ticks,
                                sl_max=int(round(atr_cap_ticks)),
                                sl_min=sl_min, sl_fallback=int(round(atr_floor_ticks)),
                                atr_pts=atr_pts)
                except Exception:
                    pass

            # Compute TP : VPOC magnet (priorite) OU R-multiple fallback
            tp_price, tp_mode, vpoc_value = self._compute_tp(
                row, entry_close, side, sl_ticks, tick
            )
            return (sl_price, tp_price, sl_ticks, swing_used, tp_mode, vpoc_value)

        # ───── Sinon : logique legacy Config A (ES ou ATR null) ─────
        # 27/05 Jackson : instrumentation SL_FALLBACK_REASON pour audit J+1
        fallback_reason = "ok_swing_based"
        swing_raw_ticks = None

        # Compute SL (fix coherence v3 : swing_used=False quand cap min/max applique)
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

        # 27/05 Emit log instrumentation (visible dans events_paper_v2)
        if self.log_fn is not None:
            try:
                atr_pts = self._safe_float(self._row_get(row, "atr"))
                self.log_fn("BOT3_V4_SL_FALLBACK_REASON",
                            sym=self.symbol, side=side,
                            reason=fallback_reason,
                            sl_ticks=sl_ticks,
                            swing_raw_ticks=swing_raw_ticks,
                            sl_max=sl_max, sl_min=sl_min, sl_fallback=sl_fallback,
                            atr_pts=atr_pts)
            except Exception:
                pass

        # Compute TP : VPOC magnet (priorite) OU R-multiple fallback
        tp_price, tp_mode, vpoc_value = self._compute_tp(
            row, entry_close, side, sl_ticks, tick
        )

        return (sl_price, tp_price, sl_ticks, swing_used, tp_mode, vpoc_value)

    def _override_sl_recent_extreme(
        self,
        entry_close: float,
        side: str,
        sl_price: float,
        sl_ticks: int,
        level_name: str,
        session_id: str,
    ) -> Tuple[float, int]:
        """24/05/2026 PM Jackson : override SL si dans zone recemment visitee.

        Pour SHORT : si max(high des N bars recents) >= sl_price (planned),
        le SL est dans une zone que le marche vient de balayer → touche par
        respiration normale. Override sl_price = recent_high + buffer_ticks.

        Symetrique LONG : recent_low <= sl_price → override sl_price = recent_low - buffer.

        Returns (sl_price, sl_ticks) potentiellement override.
        """
        if not self._recent_highs and not self._recent_lows:
            return sl_price, sl_ticks  # buffer vide (cold start), pas override
        tick = self.tick_size
        buf_ticks = self.params.sl_recent_extreme_buffer_ticks
        if side == SIDE_SHORT and self._recent_highs:
            recent_high = max(self._recent_highs)
            sl_min_safe = recent_high + buf_ticks * tick
            if sl_price < sl_min_safe:
                old_sl = sl_price
                sl_price = sl_min_safe
                sl_ticks = int(round((sl_price - entry_close) / tick))
                self._n_sl_overrides_recent_extreme += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_SL_OVERRIDE_RECENT_EXTREME",
                                    sym=self.symbol, level=level_name,
                                    side=side, sl_old=round(old_sl, 4),
                                    sl_new=round(sl_price, 4),
                                    recent_high=round(recent_high, 4),
                                    new_sl_ticks=sl_ticks,
                                    session_id=session_id)
                    except Exception:
                        pass
        elif side == SIDE_LONG and self._recent_lows:
            recent_low = min(self._recent_lows)
            sl_max_safe = recent_low - buf_ticks * tick
            if sl_price > sl_max_safe:
                old_sl = sl_price
                sl_price = sl_max_safe
                sl_ticks = int(round((entry_close - sl_price) / tick))
                self._n_sl_overrides_recent_extreme += 1
                if self.log_fn is not None:
                    try:
                        self.log_fn("BOT3_V4_SL_OVERRIDE_RECENT_EXTREME",
                                    sym=self.symbol, level=level_name,
                                    side=side, sl_old=round(old_sl, 4),
                                    sl_new=round(sl_price, 4),
                                    recent_low=round(recent_low, 4),
                                    new_sl_ticks=sl_ticks,
                                    session_id=session_id)
                    except Exception:
                        pass

        # 03/06/2026 FIX C — Cap absolu post-override (anti SL catastrophique).
        # Trade 14:38:05 NQ LONG SL=191t=$955 risk a montre que recent_low post-cassure
        # violente peut faire exploser sl_ticks sans limite. Applique un cap dur :
        # NQ 60 ticks = $300 max / ES 30 ticks = $375 max.
        absolute_cap = (
            self.params.sl_max_absolute_ticks_nq if self.symbol == "NQ"
            else self.params.sl_max_absolute_ticks_es
        )
        if sl_ticks > absolute_cap:
            old_sl_capped = sl_price
            old_sl_ticks_capped = sl_ticks
            sl_ticks = absolute_cap
            if side == SIDE_LONG:
                sl_price = entry_close - sl_ticks * tick
            else:
                sl_price = entry_close + sl_ticks * tick
            if self.log_fn is not None:
                try:
                    self.log_fn("BOT3_V4_SL_ABSOLUTE_CAP_HIT",
                                sym=self.symbol, level=level_name,
                                side=side, sl_old=round(old_sl_capped, 4),
                                sl_new=round(sl_price, 4),
                                old_sl_ticks=old_sl_ticks_capped,
                                new_sl_ticks=sl_ticks,
                                absolute_cap=absolute_cap,
                                session_id=session_id)
                except Exception:
                    pass

        return sl_price, sl_ticks

    def _compute_tp(
        self,
        row: Any,
        entry_close: float,
        side: str,
        sl_ticks: int,
        tick: float,
    ) -> Tuple[float, str, Optional[float]]:
        """Calcule TP : VPOC magnet si valide, sinon R-multiple fallback.

        VPOC magnet conditions (LONG, miroir SHORT) :
          1. cur_vpoc valide (non-NaN, > 0)
          2. cote correct : vpoc > entry pour LONG (cible au-dessus)
          3. distance ticks : vpoc_min_dist_ticks <= |entry - vpoc|/tick <= vpoc_max_dist_ticks

        Si tp_mode = R15 force, ignore VPOC.
        Si tp_mode = VPOC force, retourne VPOC meme si invalide (caller responsable).
        Si tp_mode = VPOC_FALLBACK : essaie VPOC, fallback R15 si invalide.
        """
        p = self.params
        r15_distance = p.target_R * sl_ticks * tick

        if p.tp_mode == TP_MODE_R15:
            tp_price = (
                entry_close + r15_distance if side == SIDE_LONG
                else entry_close - r15_distance
            )
            return (tp_price, TP_MODE_R15, None)

        # VPOC magnet evaluation
        vpoc = self._safe_float(self._row_get(row, "cur_vpoc"))
        vpoc_valid = False
        if vpoc is not None and vpoc > 0:
            dist_ticks_abs = abs(entry_close - vpoc) / tick
            if (p.vpoc_min_dist_ticks <= dist_ticks_abs <= p.vpoc_max_dist_ticks):
                if side == SIDE_LONG and vpoc > entry_close:
                    vpoc_valid = True
                elif side == SIDE_SHORT and vpoc < entry_close:
                    vpoc_valid = True

        if vpoc_valid:
            return (vpoc, TP_MODE_VPOC, vpoc)

        # Fallback R15
        tp_price = (
            entry_close + r15_distance if side == SIDE_LONG
            else entry_close - r15_distance
        )
        return (tp_price, TP_MODE_R15, vpoc)  # vpoc retourne pour debug audit

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _row_get(row: Any, key: str) -> Any:
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
        if v is None:
            return None
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
