"""
═══════════════════════════════════════════════════════════════════════════════
mia_session_planner.py — Session Planner MIA Trading System
═══════════════════════════════════════════════════════════════════════════════

PHILOSOPHIE
-----------
Le bot actuel réagit barre par barre sans contexte. Ce module reproduit le rituel
du trader AVANT de trader : analyser les charts, diagnostiquer le type de journée,
identifier les targets, puis attendre le bon setup au bon endroit.

Le Session Planner tourne 1 SEULE FOIS au début de chaque session (Asia, London, US)
et produit un SessionPlan qui CADRE tout le reste du pipeline.

CHANGEMENT DE PARADIGME
------------------------
  AVANT: Biais → Zone → Entry (réactif, barre par barre)
  APRÈS: Target → Biais → Entry (proactif, avec un plan)

Le trader regarde ses charts et pense :
  1. "Quel type de journée ?" (Profile shape, Open Type, gap)
  2. "Où le prix veut aller ?" (Targets = aimants structurels)
  3. "Où est le meilleur point d'entrée ?" (Zone + confirmation)
  4. "Quand ne pas trader ?" (Transitions, no-trade zones)

Ce module digitalise ce raisonnement.

SESSIONS (heure Paris CET / heure ET)
--------------------------------------
  00h00-01h00 / 19h-20h ET   ASIA WARMUP    Volume faible, observation
  01h00-03h00 / 20h-22h ET   ASIA IB        ◀ Range institutionnel asiatique
  03h00-07h00 / 22h-02h ET   ASIA QUIET     Volume faible, scalp léger
  07h00-07h30 / 02h-02h30 ET PRE-LONDON     Premiers flux EU, biais se forme
  07h30-08h15 / 02h30-03h15  LONDON TRANS   ⚠️ NO TRADE — transition volatile
  08h15-09h30 / 03h15-04h30  LONDON ACTIVE  ◀ Trading Europe
  09h30-09h45 / ---          US TRANS        ⚠️ NO TRADE — ouverture US
  09h45-10h30 / ---          US IB FORMING   ◀ Observer, Open Type se forme
  10h30-12h00 / ---          US ACTIVE       ◀ Meilleure session
  12h00-14h00 / ---          MID AM          Mean reversion, consolidation
  14h00-16h00 / ---          US PM           MOC flows, fin de session

DONNÉES UTILISÉES (toutes dans le JSONL 250 colonnes)
-----------------------------------------------------
  Profile veille:     profile_shape, poc_position, is_double_dist, single_print_count
  Value Area:         dist_cur_vpoc, dist_cur_vah, dist_cur_val, va_position_pct
  Previous Day:       dist_prev_vpoc, dist_prev_vah, dist_prev_val, dist_prev_vwap
  IB:                 dist_ib_high, dist_ib_low, ib_range_ticks, ib_complete
  Overnight:          dist_ovn_high, dist_ovn_low, ovn_range_ticks, open_gap_ticks
  Open Type:          open_type, open_zone, open_bias_conf, open_direction
  MenthorQ:           dist_mq_call, dist_mq_put, dist_mq_hvl, dist_mq_call_0dte, dist_mq_put_0dte
  GEX:                dist_gex_nearest_up, dist_gex_nearest_dn
  Session Profile:    dist_session_hvn_above, dist_session_hvn_below, session_hvn_count
  RVOL:               rvol, rvol_buy, rvol_sell, rvol_absorb_buy, rvol_absorb_sell
  BN:                 bn_score_raw, bn_score_bull, bn_score_bear

INTÉGRATION PIPELINE
--------------------
  DMP → Features → SessionPlanner (1x/session) → SessionPlan
                                                      ↓
                                          mia_entry (plan + barre) → mia_sltp (plan) → mia_sim

Schema: 3.6.0 — 250 colonnes
Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_session_planner.py

Auteur : MIA Trading System
Date   : 2026-03-13
Phase  : Architecture complète — implémentation Phase 2
═══════════════════════════════════════════════════════════════════════════════
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from enum import IntEnum


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONSTANTES ET ÉNUMÉRATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class SessionType(IntEnum):
    """Sessions de trading."""
    ASIA_WARMUP = 0
    ASIA_IB = 1
    ASIA_QUIET = 2
    PRE_LONDON = 3
    LONDON_TRANS = 4      # ⚠️ NO TRADE
    LONDON_ACTIVE = 5
    US_TRANS = 6           # ⚠️ NO TRADE
    US_IB_FORMING = 7
    US_ACTIVE = 8
    MID_AM = 9
    US_PM = 10


class Regime(IntEnum):
    """Régime de marché diagnostiqué."""
    UNKNOWN = 0
    RANGE = 1              # Double distribution, jouer les extrêmes
    TREND_UP = 2           # Profile B/P + OD, jouer les pullbacks long
    TREND_DN = 3           # Profile P/B + OD, jouer les pullbacks short
    ROTATION = 4           # Symétrique, mean reversion douce
    BREAKOUT = 5           # IB cassée, expansion en cours


class DayTypeExpected(IntEnum):
    """Type de journée attendu (diagnostic pré-session)."""
    UNKNOWN = 0
    TREND_DAY = 1          # OD + profil directionnel → 1 direction toute la journée
    NORMAL_DAY = 2         # IB tient, rotation autour du POC
    RANGE_DAY = 3          # Double distribution, VA↔VA
    NEUTRAL_DAY = 4        # Pas de conviction, sizing réduit


class TargetTier(IntEnum):
    """Priorité du target."""
    PRIMARY = 1            # Target #1 — destination la plus probable
    SECONDARY = 2          # Target alternatif
    DEFENSIVE = 3          # Target de protection (retour)


# ── Horaires des sessions (en heure ET) ──────────────────────────────────
SESSION_SCHEDULE = {
    SessionType.ASIA_WARMUP:    (19, 0,  20, 0),    # 00h-01h Paris
    SessionType.ASIA_IB:        (20, 0,  22, 0),    # 01h-03h Paris  ◀ IB Asia
    SessionType.ASIA_QUIET:     (22, 0,   2, 0),    # 03h-07h Paris
    SessionType.PRE_LONDON:     ( 2, 0,   2, 30),   # 07h-07h30 Paris
    SessionType.LONDON_TRANS:   ( 2, 30,  3, 15),   # 07h30-08h15 ⚠️
    SessionType.LONDON_ACTIVE:  ( 3, 15,  4, 30),   # 08h15-09h30
    SessionType.US_TRANS:       ( 9, 30,  9, 45),   # 15h30-15h45 ⚠️
    SessionType.US_IB_FORMING:  ( 9, 45, 10, 30),   # 15h45-16h30 ◀ IB US
    SessionType.US_ACTIVE:      (10, 30, 12, 0),    # 16h30-18h
    SessionType.MID_AM:         (12, 0,  14, 0),    # 18h-20h
    SessionType.US_PM:          (14, 0,  16, 0),    # 20h-22h
}

# ── No-trade zones ──────────────────────────────────────────────────────
NO_TRADE_SESSIONS = {
    SessionType.LONDON_TRANS,   # 07h30-08h15 Paris — chaos London open
    SessionType.US_TRANS,       # 15h30-15h45 Paris — chaos US open
}

# ── Zones d'observation (capturer le range, ne pas trader) ──────────────
OBSERVE_ONLY_SESSIONS = {
    SessionType.ASIA_IB,        # Capturer le range, pas trader
    SessionType.US_IB_FORMING,  # Observer l'Open Type se former
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — STRUCTURES DE DONNÉES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IBRange:
    """Range d'une Initial Balance (Asia, London, ou US)."""
    session: str              # 'ASIA', 'LONDON', 'US'
    high: float = 0.0        # Prix le plus haut de l'IB
    low: float = 0.0         # Prix le plus bas de l'IB
    mid: float = 0.0         # Point médian
    range_ticks: float = 0.0 # Taille du range en ticks
    vol_avg: float = 0.0     # Volume moyen pendant l'IB
    is_narrow: bool = False  # Range < 30% de l'ATR → breakout probable
    is_wide: bool = False    # Range > 70% de l'ATR → direction établie
    broken_up: bool = False  # Prix a cassé au-dessus
    broken_dn: bool = False  # Prix a cassé en-dessous
    valid: bool = False      # IB calculée avec succès

    @property
    def direction_bias(self) -> int:
        """Direction indiquée par la cassure de l'IB."""
        if self.broken_up and not self.broken_dn:
            return 1   # Breakout UP → biais LONG
        elif self.broken_dn and not self.broken_up:
            return -1  # Breakout DOWN → biais SHORT
        return 0       # Pas de cassure ou les deux côtés cassés


@dataclass
class Target:
    """Un target structurel — destination probable du prix."""
    name: str                 # Ex: 'PREV_VPOC', 'PUT_0DTE', 'VAH'
    price: float              # Prix du target
    distance_ticks: float     # Distance actuelle en ticks
    tier: TargetTier          # PRIMARY, SECONDARY, DEFENSIVE
    role: str                 # 'magnet', 'resistance', 'support'
    reason: str               # Pourquoi c'est un target
    conviction: float = 0.0   # 0.0-1.0 — force de l'attraction

    @property
    def direction(self) -> int:
        """Direction pour atteindre ce target."""
        return 1 if self.distance_ticks < 0 else -1  # Négatif = target au-dessus


@dataclass
class SessionPlan:
    """
    Plan de session — produit 1x au début de chaque session.
    
    C'est l'objet central qui cadre TOUT le pipeline en aval:
    - mia_entry consulte le plan pour filtrer les signaux
    - mia_sltp consulte les targets pour calculer les TP
    - mia_sim consulte les no-trade zones et le sizing
    """
    # ── Identité ──
    session: SessionType
    timestamp: str = ""           # Quand le plan a été créé
    symbol: str = "NQ"

    # ── Diagnostic du jour ──
    regime: Regime = Regime.UNKNOWN
    bias: int = 0                 # +1=LONG, -1=SHORT, 0=NEUTRE
    confidence: float = 0.0       # 0.0 → 1.0
    day_type: DayTypeExpected = DayTypeExpected.UNKNOWN

    # ── Contexte structurel ──
    prev_shape: str = ""          # 'B', 'P', 'D', 'SYM' (profile veille)
    prev_poc_position: float = 0.0
    open_type: int = 0            # 1-9 (enum Sierra Chart)
    open_type_name: str = ""      # 'OD_UP', 'ORR', 'OAIR', etc.
    gap_type: str = ""            # 'GAP_UP', 'GAP_DN', 'INSIDE'
    gap_size_ticks: float = 0.0

    # ── IB Stack (toutes les IB actives, par ordre chronologique) ──
    asia_ib: IBRange = field(default_factory=lambda: IBRange(session='ASIA'))
    london_ib: IBRange = field(default_factory=lambda: IBRange(session='LONDON'))
    us_ib: IBRange = field(default_factory=lambda: IBRange(session='US'))

    # ── Targets (ordonnés par priorité) ──
    targets_up: List[Target] = field(default_factory=list)
    targets_dn: List[Target] = field(default_factory=list)
    primary_target: Optional[Target] = None

    # ── Modules activés/désactivés ──
    modules_enabled: List[str] = field(default_factory=list)
    modules_disabled: List[str] = field(default_factory=list)

    # ── Risk Management ──
    sl_mode: str = "NORMAL"       # 'TIGHT' (range), 'WIDE' (trend), 'NORMAL'
    sizing_factor: float = 1.0    # 1.0=normal, 1.25=haute conviction, 0.75=incertain
    max_trades: int = 6           # Ajusté selon conviction

    # ── No-trade ──
    no_trade_zones: List[Tuple[int, int, str]] = field(default_factory=list)
    # Format: [(start_min_et, end_min_et, reason), ...]

    # ── Raison (log) ──
    reason: str = ""
    diagnosis_details: Dict = field(default_factory=dict)

    @property
    def active_ib(self) -> IBRange:
        """Retourne l'IB active la plus récente."""
        if self.us_ib.valid:
            return self.us_ib
        if self.london_ib.valid:
            return self.london_ib
        if self.asia_ib.valid:
            return self.asia_ib
        return IBRange(session='NONE')

    def is_no_trade(self, hour_et: int, minute_et: int) -> Tuple[bool, str]:
        """Vérifie si l'heure actuelle est dans une zone no-trade."""
        t = hour_et * 60 + minute_et
        for start, end, reason in self.no_trade_zones:
            if start <= end:
                if start <= t < end:
                    return True, reason
            else:  # Wrap midnight
                if t >= start or t < end:
                    return True, reason
        return False, ""

    def get_target_for_direction(self, direction: int) -> Optional[Target]:
        """Retourne le primary target pour une direction donnée."""
        targets = self.targets_up if direction == 1 else self.targets_dn
        if targets:
            return targets[0]  # Premier = plus prioritaire
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlannerConfig:
    """Configuration du Session Planner."""
    # Asia IB
    asia_ib_start_et: int = 20    # 20h ET = 1h Paris
    asia_ib_end_et: int = 22      # 22h ET = 3h Paris
    asia_ib_narrow_pct: float = 0.30  # < 30% ATR = narrow
    asia_ib_wide_pct: float = 0.70    # > 70% ATR = wide

    # London IB
    london_ib_start_et: int = 3       # 3h ET = 8h Paris
    london_ib_end_et: int = 4         # 4h ET = 9h Paris (1h)
    london_ib_start_min: int = 15     # 03:15 ET (après transition)

    # US IB
    us_ib_start_et: int = 9           # 9:30 ET
    us_ib_start_min: int = 30
    us_ib_end_et: int = 10            # 10:30 ET (1h)
    us_ib_end_min: int = 30

    # Target detection
    target_max_dist_ticks: int = 200  # Ne pas considérer les targets > 200t
    target_min_dist_ticks: int = 15   # Ignorer si déjà sur le target
    magnet_min_conviction: float = 0.3

    # Profile shape thresholds
    poc_high_threshold: float = 0.65  # POC au-dessus = Profile P
    poc_low_threshold: float = 0.35   # POC en-dessous = Profile B

    # Gap thresholds
    gap_significant_ticks: int = 40   # Gap > 40t = significatif
    gap_large_ticks: int = 80         # Gap > 80t = gap play possible

    # Conviction thresholds
    high_conviction: float = 0.70     # Sizing ×1.25
    low_conviction: float = 0.40      # Sizing ×0.75


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MOTEUR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class SessionPlanner:
    """
    Moteur principal du Session Planner.
    
    Usage:
        planner = SessionPlanner()
        plan = planner.plan_session(df, session=SessionType.LONDON_ACTIVE)
        # Puis passer le plan à mia_entry, mia_sltp, mia_sim
    """

    def __init__(self, config: PlannerConfig = None, symbol: str = "NQ"):
        self.cfg = config or PlannerConfig()
        self.symbol = symbol
        self.tick_size = 0.25

    # ─── POINT D'ENTRÉE PRINCIPAL ─────────────────────────────────

    def plan_session(self, df: pd.DataFrame,
                     session: SessionType = SessionType.LONDON_ACTIVE) -> SessionPlan:
        """
        Produit un SessionPlan pour la session donnée.
        
        Args:
            df: DataFrame complet (toutes les barres disponibles jusqu'à maintenant)
            session: La session pour laquelle on planifie
            
        Returns:
            SessionPlan complet avec diagnostic, targets, modules, risk
        """
        plan = SessionPlan(session=session, symbol=self.symbol)

        # ── 1. Calculer les IB ──
        plan.asia_ib = self._compute_ib(df, 'ASIA')
        if session >= SessionType.LONDON_ACTIVE:
            plan.london_ib = self._compute_ib(df, 'LONDON')
        if session >= SessionType.US_ACTIVE:
            plan.us_ib = self._compute_ib(df, 'US')

        # ── 2. Diagnostic structurel (profile veille, gap, open type) ──
        plan = self._diagnose_structure(df, plan)

        # ── 3. Déterminer le régime et le biais ──
        plan = self._determine_regime(plan)

        # ── 4. Identifier les targets ──
        plan = self._identify_targets(df, plan)

        # ── 5. Activer/désactiver les modules ──
        plan = self._configure_modules(plan)

        # ── 6. Configurer le risk ──
        plan = self._configure_risk(plan)

        # ── 7. Définir les no-trade zones ──
        plan = self._set_no_trade_zones(plan)

        # ── 8. Construire la raison ──
        plan.reason = self._build_reason(plan)

        return plan

    # ─── ÉTAPE 1 : CALCUL DES IB ─────────────────────────────────

    def _compute_ib(self, df: pd.DataFrame, session: str) -> IBRange:
        """
        Calcule le range de l'Initial Balance pour une session donnée.
        
        Asia IB:   20h-22h ET (1h-3h Paris) — institutionnels Tokyo + Hong Kong
        London IB: 03:15-04:15 ET (8h15-9h15 Paris) — après la transition
        US IB:     09:30-10:30 ET (15h30-16h30 Paris) — première heure RTH
        """
        ib = IBRange(session=session)

        if 'datetime_et' in df.columns:
            hours = df['datetime_et'].dt.hour.values
            mins = df['datetime_et'].dt.minute.values
        elif 'ts' in df.columns:
            dts = pd.to_datetime(df['ts'], unit='ms', utc=True)
            hours = ((dts.dt.hour - 4) % 24).values
            mins = dts.dt.minute.values
        else:
            return ib

        # Définir la fenêtre selon la session
        if session == 'ASIA':
            sh, sm = self.cfg.asia_ib_start_et, 0
            eh, em = self.cfg.asia_ib_end_et, 0
        elif session == 'LONDON':
            sh, sm = self.cfg.london_ib_start_et, self.cfg.london_ib_start_min
            eh, em = self.cfg.london_ib_end_et, 0
        elif session == 'US':
            sh, sm = self.cfg.us_ib_start_et, self.cfg.us_ib_start_min
            eh, em = self.cfg.us_ib_end_et, self.cfg.us_ib_end_min
        else:
            return ib

        # Filtrer les barres dans la fenêtre
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        times = hours * 60 + mins

        if end_min > start_min:
            mask = (times >= start_min) & (times < end_min)
        else:  # Wrap midnight (Asia IB: 20h → 22h OK, mais Asia quiet: 22h → 2h)
            mask = (times >= start_min) | (times < end_min)

        ib_bars = df[mask]
        if len(ib_bars) < 5:
            return ib  # Pas assez de barres

        ib.high = float(ib_bars['price'].max())
        ib.low = float(ib_bars['price'].min())
        ib.mid = (ib.high + ib.low) / 2.0
        ib.range_ticks = (ib.high - ib.low) / self.tick_size
        ib.vol_avg = float(ib_bars['total_vol'].mean())
        ib.valid = True

        # Narrow/Wide par rapport à l'ATR
        atr = float(ib_bars['atr'].iloc[-1]) if 'atr' in ib_bars.columns else 100.0
        atr_ticks = atr / self.tick_size
        if atr_ticks > 0:
            ib.is_narrow = ib.range_ticks < atr_ticks * self.cfg.asia_ib_narrow_pct
            ib.is_wide = ib.range_ticks > atr_ticks * self.cfg.asia_ib_wide_pct

        # Vérifier les cassures (barres APRÈS l'IB)
        post_ib = df[~mask & (df.index > ib_bars.index[-1])] if len(ib_bars) > 0 else pd.DataFrame()
        if len(post_ib) > 0:
            ib.broken_up = float(post_ib['price'].max()) > ib.high
            ib.broken_dn = float(post_ib['price'].min()) < ib.low

        return ib

    # ─── ÉTAPE 2 : DIAGNOSTIC STRUCTUREL ──────────────────────────

    def _diagnose_structure(self, df: pd.DataFrame, plan: SessionPlan) -> SessionPlan:
        """
        Analyse la structure : profile veille, gap, open type.
        Correspond au "coup d'œil sur les charts" du trader le matin.
        """
        if df.empty:
            return plan

        last = df.iloc[-1]

        # ── Profile shape de la session ──
        shape = int(last.get('profile_shape', 0))
        poc_pos = float(last.get('poc_position', 0.5))
        is_dd = int(last.get('is_double_dist', 0))

        if is_dd == 1:
            plan.prev_shape = 'D'       # Double distribution → RANGE
        elif poc_pos > self.cfg.poc_high_threshold:
            plan.prev_shape = 'P'       # POC en haut → distribution haute
        elif poc_pos < self.cfg.poc_low_threshold:
            plan.prev_shape = 'B'       # POC en bas → distribution basse
        else:
            plan.prev_shape = 'SYM'     # Symétrique

        plan.prev_poc_position = poc_pos

        # ── Open type ──
        plan.open_type = int(last.get('open_type', 0))
        ot_names = {
            1: 'OD_UP', 2: 'OD_DN', 3: 'ORR_UP', 4: 'ORR_DN',
            5: 'OAOR_UP', 6: 'OAOR_DN', 7: 'OAIR',
            8: 'OTD_UP', 9: 'OTD_DN'
        }
        plan.open_type_name = ot_names.get(plan.open_type, 'UNKNOWN')

        # ── Gap ──
        gap = float(last.get('open_gap_ticks', 0))
        plan.gap_size_ticks = gap
        if abs(gap) > self.cfg.gap_large_ticks:
            plan.gap_type = 'GAP_UP' if gap > 0 else 'GAP_DN'
        elif abs(gap) > self.cfg.gap_significant_ticks:
            plan.gap_type = 'GAP_SMALL_UP' if gap > 0 else 'GAP_SMALL_DN'
        else:
            plan.gap_type = 'INSIDE'

        plan.diagnosis_details = {
            'prev_shape': plan.prev_shape,
            'poc_position': poc_pos,
            'is_double_dist': is_dd,
            'open_type': plan.open_type_name,
            'gap_type': plan.gap_type,
            'gap_ticks': gap,
        }

        # 🆕 14/03/2026: Market Profile avancé — enrichit le diagnostic
        
        # Rotation Factor (Dalton) — combien de rotations autour du POC ?
        # > 4 rotations = range confirmé | < 2 = trend probable
        rotation_f = float(last.get('ctx_rotation_factor_20', 0) or 0)
        plan.diagnosis_details['rotation_factor'] = rotation_f
        if rotation_f >= 4:
            plan.diagnosis_details['rotation_verdict'] = 'RANGE'
        elif rotation_f <= 2:
            plan.diagnosis_details['rotation_verdict'] = 'TREND'
        else:
            plan.diagnosis_details['rotation_verdict'] = 'MIXED'

        # IB Extension Ratio (Steidlmayer) — le prix est à combien de fois l'IB ?
        # < 1.0 = inside IB | 1.0-1.5 = normal | > 2.0 = trend day
        ib_ext = float(last.get('ctx_ib_extension_ratio', 1.0) or 1.0)
        plan.diagnosis_details['ib_extension_ratio'] = ib_ext
        if ib_ext > 2.0:
            plan.diagnosis_details['ib_extension_verdict'] = 'TREND_DAY'
        elif ib_ext > 1.5:
            plan.diagnosis_details['ib_extension_verdict'] = 'EXTENDING'
        else:
            plan.diagnosis_details['ib_extension_verdict'] = 'NORMAL'

        # POC Migration — le POC se déplace dans quelle direction ?
        poc_mig = float(last.get('ctx_poc_migration_10', 0) or 0)
        plan.diagnosis_details['poc_migration'] = poc_mig
        plan.diagnosis_details['poc_migration_dir'] = 'UP' if poc_mig > 0.005 else ('DN' if poc_mig < -0.005 else 'FLAT')

        # Failed Auction récent ?
        fa = int(last.get('ctx_failed_auction', 0) or 0)
        plan.diagnosis_details['failed_auction'] = fa

        return plan

    # ─── ÉTAPE 3 : DÉTERMINATION DU RÉGIME ────────────────────────

    def _determine_regime(self, plan: SessionPlan) -> SessionPlan:
        """
        Détermine le régime et le biais à partir du diagnostic structurel.
        
        Logique du trader :
          - Profile D (double dist) → RANGE, jouer les extrêmes
          - Profile B + gap up → TREND_UP probable
          - Profile P + gap down → TREND_DN probable
          - OD détecté → TREND confirmé (haute conviction)
          - Rien de clair → ROTATION (sizing réduit)
        """
        shape = plan.prev_shape
        ot = plan.open_type_name
        gap = plan.gap_type
        asia_dir = plan.asia_ib.direction_bias

        confidence = 0.0
        reasons = []

        # ── Règle 1 : Double distribution = RANGE ──
        if shape == 'D':
            plan.regime = Regime.RANGE
            plan.day_type = DayTypeExpected.RANGE_DAY
            confidence += 0.40
            reasons.append(f"Profile D → RANGE")

        # ── Règle 2 : Open Drive = TREND (haute conviction) ──
        elif ot in ('OD_UP', 'OTD_UP'):
            plan.regime = Regime.TREND_UP
            plan.bias = 1
            plan.day_type = DayTypeExpected.TREND_DAY
            confidence += 0.60
            reasons.append(f"{ot} → TREND UP")

        elif ot in ('OD_DN', 'OTD_DN'):
            plan.regime = Regime.TREND_DN
            plan.bias = -1
            plan.day_type = DayTypeExpected.TREND_DAY
            confidence += 0.60
            reasons.append(f"{ot} → TREND DN")

        # ── Règle 3 : Profile B/P + gap aligné ──
        elif shape == 'B':
            if gap in ('GAP_UP', 'GAP_SMALL_UP'):
                plan.regime = Regime.TREND_UP
                plan.bias = 1
                confidence += 0.35
                reasons.append("Profile B + Gap UP → biais LONG")
            else:
                plan.regime = Regime.ROTATION
                plan.bias = 1
                confidence += 0.25
                reasons.append("Profile B → biais LONG léger")

        elif shape == 'P':
            if gap in ('GAP_DN', 'GAP_SMALL_DN'):
                plan.regime = Regime.TREND_DN
                plan.bias = -1
                confidence += 0.35
                reasons.append("Profile P + Gap DN → biais SHORT")
            else:
                plan.regime = Regime.ROTATION
                plan.bias = -1
                confidence += 0.25
                reasons.append("Profile P → biais SHORT léger")

        # ── Règle 4 : Symétrique = ROTATION ──
        else:
            plan.regime = Regime.ROTATION
            plan.day_type = DayTypeExpected.NEUTRAL_DAY
            confidence += 0.20
            reasons.append("Profile SYM → ROTATION")

        # ── Bonus conviction : Asia IB confirme ──
        if asia_dir != 0 and plan.bias != 0:
            if asia_dir == plan.bias:
                confidence += 0.10
                reasons.append(f"Asia IB confirme direction ({'+' if asia_dir > 0 else '-'})")
            else:
                confidence -= 0.10
                reasons.append(f"Asia IB contra (divergence)")

        # ── Bonus conviction : IB narrow = breakout imminent ──
        ib = plan.active_ib
        if ib.valid and ib.is_narrow:
            confidence += 0.05
            reasons.append("IB narrow → breakout probable")
        elif ib.valid and ib.is_wide:
            confidence += 0.05
            reasons.append("IB wide → direction déjà établie")

        plan.confidence = max(0.0, min(1.0, confidence))
        plan.diagnosis_details['regime_reasons'] = reasons

        # Si RANGE et pas de biais clair, le biais vient de la position dans le range
        if plan.regime == Regime.RANGE and plan.bias == 0:
            # Le biais sera déterminé dynamiquement barre par barre (va_position)
            pass

        return plan

    # ─── ÉTAPE 4 : IDENTIFICATION DES TARGETS ────────────────────

    def _identify_targets(self, df: pd.DataFrame, plan: SessionPlan) -> SessionPlan:
        """
        Identifie les "aimants" structurels — destinations probables du prix.
        
        Un target c'est un niveau qui ATTIRE le prix :
          - PREV_VPOC non testé → aimant (80% rule : prix revient au VPOC)
          - PREV_VWAP → point d'équilibre de la veille
          - Put/Call 0DTE → magnets options (market makers hedge)
          - IB High/Low → niveaux de breakout/réintégration
          - Session HVN → zone d'accumulation = destination
          
        Les targets sont classés par conviction et donnent la direction.
        """
        if df.empty:
            return plan

        last = df.iloc[-1]
        price = float(last.get('price', 0))

        if price <= 0:
            return plan

        # ── Scanner tous les targets potentiels ──
        target_map = [
            # (col_dist, name, role, base_conviction, condition)
            ('dist_prev_vpoc',       'PREV_VPOC',    'magnet',     0.80, True),
            ('dist_prev_vwap',       'PREV_VWAP',    'magnet',     0.60, True),
            ('dist_prev_vah',        'PREV_VAH',     'resistance', 0.50, True),
            ('dist_prev_val',        'PREV_VAL',     'support',    0.50, True),
            ('dist_cur_vpoc',        'CUR_VPOC',     'magnet',     0.70, True),
            ('dist_cur_vah',         'CUR_VAH',      'resistance', 0.55, True),
            ('dist_cur_val',         'CUR_VAL',      'support',    0.55, True),
            ('dist_mq_hvl',          'MQ_HVL',       'magnet',     0.45, True),
            ('dist_mq_put_0dte',     'PUT_0DTE',     'support',    0.65,
             plan.session >= SessionType.US_IB_FORMING),  # Actif seulement en US
            ('dist_mq_call_0dte',    'CALL_0DTE',    'resistance', 0.65,
             plan.session >= SessionType.US_IB_FORMING),
            ('dist_gex_nearest_up',  'GEX_UP',       'resistance', 0.55, True),
            ('dist_gex_nearest_dn',  'GEX_DN',       'support',    0.55, True),
            ('dist_ovn_high',        'OVN_HIGH',     'resistance', 0.40, True),
            ('dist_ovn_low',         'OVN_LOW',      'support',    0.40, True),
            ('dist_open_cash',       'OPEN_CASH',    'magnet',     0.35, True),
        ]

        # Ajouter les IB comme targets
        if plan.asia_ib.valid:
            asia_high_dist = (plan.asia_ib.high - price) / self.tick_size
            asia_low_dist = (plan.asia_ib.low - price) / self.tick_size
            target_map.append(('_asia_ib_high', 'ASIA_IB_HIGH', 'resistance', 0.50, True))
            target_map.append(('_asia_ib_low', 'ASIA_IB_LOW', 'support', 0.50, True))

        targets_up = []
        targets_dn = []

        for col, name, role, conviction, condition in target_map:
            if not condition:
                continue

            # Récupérer la distance
            if col.startswith('_asia_ib'):
                dist = asia_high_dist if 'high' in col else asia_low_dist
            else:
                dist = last.get(col)

            if dist is None or pd.isna(dist):
                continue

            dist = float(dist)
            abs_dist = abs(dist)

            # Filtrer par distance
            if abs_dist < self.cfg.target_min_dist_ticks:
                continue  # Déjà sur le target
            if abs_dist > self.cfg.target_max_dist_ticks:
                continue  # Trop loin

            # Ajuster conviction selon le régime
            adj_conviction = conviction
            if plan.regime == Regime.RANGE and role == 'magnet':
                adj_conviction += 0.10  # Magnets plus attractifs en range
            elif plan.regime in (Regime.TREND_UP, Regime.TREND_DN):
                if role == 'magnet':
                    adj_conviction -= 0.10  # Magnets moins pertinents en trend
            
            # Plus le target est proche, plus la conviction est haute
            proximity_bonus = max(0, (100 - abs_dist) / 200)  # 0 à +0.5
            adj_conviction = min(1.0, adj_conviction + proximity_bonus)

            if adj_conviction < self.cfg.magnet_min_conviction:
                continue

            # Déterminer le tier
            if adj_conviction >= 0.65:
                tier = TargetTier.PRIMARY
            elif adj_conviction >= 0.45:
                tier = TargetTier.SECONDARY
            else:
                tier = TargetTier.DEFENSIVE

            target = Target(
                name=name,
                price=price + dist * self.tick_size,
                distance_ticks=dist,
                tier=tier,
                role=role,
                reason=f"{name} à {abs_dist:.0f}t",
                conviction=adj_conviction,
            )

            # Classer up vs down
            if dist > 0:  # Target au-dessus du prix
                targets_up.append(target)
            else:
                targets_dn.append(target)

        # Trier par conviction décroissante
        targets_up.sort(key=lambda t: -t.conviction)
        targets_dn.sort(key=lambda t: -t.conviction)

        plan.targets_up = targets_up
        plan.targets_dn = targets_dn

        # Primary target = le plus convaincant dans la direction du biais
        if plan.bias == 1 and targets_up:
            plan.primary_target = targets_up[0]
        elif plan.bias == -1 and targets_dn:
            plan.primary_target = targets_dn[0]
        elif targets_up and targets_dn:
            # Pas de biais clair → le target le plus convaincant donne le biais
            if targets_up[0].conviction > targets_dn[0].conviction:
                plan.primary_target = targets_up[0]
                if plan.bias == 0:
                    plan.bias = 1
            else:
                plan.primary_target = targets_dn[0]
                if plan.bias == 0:
                    plan.bias = -1

        return plan

    # ─── ÉTAPE 5 : CONFIGURATION DES MODULES ─────────────────────

    def _configure_modules(self, plan: SessionPlan) -> SessionPlan:
        """
        Active/désactive les modules d'entrée selon le régime.
        
        Logique du trader:
          RANGE    → Range Entry ON, Double Top ON, Exhaustion ON, Trend OFF
          TREND    → Trend ON, Exhaustion ON (pullbacks), Range OFF
          ROTATION → Tout ON mais sizing réduit
          BREAKOUT → Trend ON, RVOL ON (volume confirme), Range OFF
        """
        all_modules = [
            'RVOL_TRIGGER',      # Absorption volume
            'RANGE_ENTRY',       # VA extrêmes
            'DOUBLE_TOP',        # Confirmation boost/penalty
            'EXHAUSTION',        # Reversal multi-barres
            'ZONE_CLASSIC',      # Flow biais+niveau
        ]

        if plan.regime == Regime.RANGE:
            plan.modules_enabled = ['RANGE_ENTRY', 'DOUBLE_TOP', 'EXHAUSTION',
                                    'RVOL_TRIGGER', 'ZONE_CLASSIC']
            plan.modules_disabled = []
            # En range, Double Top est le signal le plus fort

        elif plan.regime in (Regime.TREND_UP, Regime.TREND_DN):
            plan.modules_enabled = ['RVOL_TRIGGER', 'EXHAUSTION', 'ZONE_CLASSIC']
            plan.modules_disabled = ['RANGE_ENTRY']
            # En trend, Range Entry = contre-tendance = danger
            # Exhaustion détecte les pullbacks épuisés = bon en trend

        elif plan.regime == Regime.BREAKOUT:
            plan.modules_enabled = ['RVOL_TRIGGER', 'ZONE_CLASSIC', 'EXHAUSTION']
            plan.modules_disabled = ['RANGE_ENTRY', 'DOUBLE_TOP']
            # En breakout, ne pas chercher les reversals

        elif plan.regime == Regime.ROTATION:
            plan.modules_enabled = all_modules  # Tout ON
            plan.modules_disabled = []

        else:  # UNKNOWN
            plan.modules_enabled = ['ZONE_CLASSIC']  # Minimum
            plan.modules_disabled = ['RANGE_ENTRY', 'EXHAUSTION']

        return plan

    # ─── ÉTAPE 6 : CONFIGURATION DU RISK ──────────────────────────

    def _configure_risk(self, plan: SessionPlan) -> SessionPlan:
        """
        Configure le SL mode, sizing, et max trades selon le régime et la conviction.
        """
        # SL mode
        if plan.regime == Regime.RANGE:
            plan.sl_mode = 'TIGHT'      # Range = SL serré, murs proches
            plan.max_trades = 8          # Plus d'opportunités en range
        elif plan.regime in (Regime.TREND_UP, Regime.TREND_DN):
            plan.sl_mode = 'WIDE'       # Trend = SL large, laisser respirer
            plan.max_trades = 4          # Moins de trades, plus gros
        elif plan.regime == Regime.BREAKOUT:
            plan.sl_mode = 'WIDE'
            plan.max_trades = 4
        else:
            plan.sl_mode = 'NORMAL'
            plan.max_trades = 6

        # Sizing
        if plan.confidence >= self.cfg.high_conviction:
            plan.sizing_factor = 1.25    # Haute conviction → sizing +25%
        elif plan.confidence <= self.cfg.low_conviction:
            plan.sizing_factor = 0.75    # Faible conviction → sizing -25%
        else:
            plan.sizing_factor = 1.0

        return plan

    # ─── ÉTAPE 7 : NO-TRADE ZONES ────────────────────────────────

    def _set_no_trade_zones(self, plan: SessionPlan) -> SessionPlan:
        """
        Définit les zones horaires où on ne prend pas de nouveau trade.
        
        Basé sur l'analyse du bench Test 15:
          - London transition (2h30-3h15 ET) : chaos institutionnel EU
          - US transition (9h30-9h45 ET) : chaos ouverture US
          - Asia IB (20h-22h ET) : observer seulement
          
        Le bench accumulera les données pour affiner ces zones.
        """
        plan.no_trade_zones = [
            # (start_minutes_ET, end_minutes_ET, reason)
            (2 * 60 + 30,  3 * 60 + 15,  "LONDON_TRANSITION — faux breakouts"),
            (9 * 60 + 30,  9 * 60 + 45,  "US_OPEN — chaos institutionnel"),
        ]

        # Asia IB = observation seulement (pas strictement no-trade mais pas de signaux)
        # Géré par OBSERVE_ONLY_SESSIONS dans mia_entry

        return plan

    # ─── ÉTAPE 8 : RAISON / LOG ───────────────────────────────────

    def _build_reason(self, plan: SessionPlan) -> str:
        """Construit un résumé textuel du plan."""
        parts = [
            f"Session={plan.session.name}",
            f"Regime={plan.regime.name}",
            f"Bias={'LONG' if plan.bias > 0 else ('SHORT' if plan.bias < 0 else 'NEUTRE')}",
            f"Conf={plan.confidence:.0%}",
            f"Shape={plan.prev_shape}",
            f"OT={plan.open_type_name}",
            f"Gap={plan.gap_type}",
        ]

        if plan.primary_target:
            parts.append(f"Target={plan.primary_target.name}@{plan.primary_target.distance_ticks:.0f}t")

        if plan.asia_ib.valid:
            parts.append(f"AsiaIB={plan.asia_ib.range_ticks:.0f}t")
            if plan.asia_ib.broken_up:
                parts.append("AsiaIB_BROKE_UP")
            if plan.asia_ib.broken_dn:
                parts.append("AsiaIB_BROKE_DN")

        parts.append(f"Modules={'+'.join(plan.modules_enabled)}")
        parts.append(f"SL={plan.sl_mode}")
        parts.append(f"Sizing={plan.sizing_factor:.2f}")

        return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — INTRA-SESSION UPDATE
# ═══════════════════════════════════════════════════════════════════════════════

    def update_plan(self, plan: SessionPlan, df: pd.DataFrame) -> SessionPlan:
        """
        Mise à jour intra-session (optionnel, toutes les 30 min).
        
        Met à jour:
          - IB cassées (Asia → London → US)
          - Targets atteints (retirer de la liste)
          - Régime qui change (IB cassée → BREAKOUT)
          - Rule of 80% (prix revient dans prev VA → target PREV_VPOC)
        """
        last = df.iloc[-1]
        price = float(last.get('price', 0))

        # ── Vérifier cassures IB ──
        for ib in [plan.asia_ib, plan.london_ib, plan.us_ib]:
            if not ib.valid:
                continue
            if price > ib.high and not ib.broken_up:
                ib.broken_up = True
                # Upgrade vers BREAKOUT si IB US cassée
                if ib.session == 'US' and plan.regime != Regime.BREAKOUT:
                    plan.regime = Regime.BREAKOUT
                    plan.bias = 1
                    plan.confidence = min(1.0, plan.confidence + 0.15)
            if price < ib.low and not ib.broken_dn:
                ib.broken_dn = True
                if ib.session == 'US' and plan.regime != Regime.BREAKOUT:
                    plan.regime = Regime.BREAKOUT
                    plan.bias = -1
                    plan.confidence = min(1.0, plan.confidence + 0.15)

        # ── Rule of 80% ──
        # Si le prix était hors de la prev VA et revient dedans → 80% chance d'aller au VPOC
        inside_prev = int(last.get('inside_prev_va', 0))
        if inside_prev == 1:
            prev_vpoc_dist = last.get('dist_prev_vpoc')
            if prev_vpoc_dist is not None and abs(float(prev_vpoc_dist)) > 15:
                # Ajouter PREV_VPOC comme target PRIMARY avec haute conviction
                rule80_target = Target(
                    name='PREV_VPOC_80PCT',
                    price=price + float(prev_vpoc_dist) * self.tick_size,
                    distance_ticks=float(prev_vpoc_dist),
                    tier=TargetTier.PRIMARY,
                    role='magnet',
                    reason='Rule of 80% — prix revenu dans prev VA',
                    conviction=0.80,
                )
                if float(prev_vpoc_dist) > 0:
                    plan.targets_up.insert(0, rule80_target)
                else:
                    plan.targets_dn.insert(0, rule80_target)
                plan.primary_target = rule80_target

        # ── Retirer les targets atteints ──
        plan.targets_up = [t for t in plan.targets_up if abs(t.distance_ticks) > 5]
        plan.targets_dn = [t for t in plan.targets_dn if abs(t.distance_ticks) > 5]

        # ── Re-configurer les modules si régime a changé ──
        plan = self._configure_modules(plan)

        return plan


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — HELPERS & RÉSUMÉ
# ═══════════════════════════════════════════════════════════════════════════════

    # ─── 🆕 14/03/2026: NAKED POC (VPOC jamais revisité) ─────────
    
    @staticmethod
    def find_naked_pocs(daily_vpocs: list, daily_ranges: list) -> list:
        """
        Trouve les Naked POC — VPOC des jours passés jamais revisités.
        
        L'aimant le plus puissant du Market Profile. Un VPOC non touché
        "tire" le prix vers lui.
        
        Args:
            daily_vpocs: [(date, vpoc_price), ...] trié chronologiquement
            daily_ranges: [(date, low, high), ...] trié chronologiquement
            
        Returns:
            Liste de {date, price, days_ago, conviction, name}
            
        Nécessite 3+ jours. Retourne [] si insuffisant.
        """
        if len(daily_vpocs) < 3 or len(daily_ranges) < 2:
            return []
        
        naked = []
        
        for i in range(len(daily_vpocs) - 1):
            date_vpoc, vpoc_price = daily_vpocs[i]
            if vpoc_price <= 0:
                continue
            
            was_touched = False
            for j in range(i + 1, len(daily_ranges)):
                _, day_low, day_high = daily_ranges[j]
                if day_low <= vpoc_price <= day_high:
                    was_touched = True
                    break
            
            if not was_touched:
                days_ago = len(daily_vpocs) - 1 - i
                conviction = min(0.95, 0.60 + days_ago * 0.08)
                naked.append({
                    'date': date_vpoc,
                    'price': vpoc_price,
                    'days_ago': days_ago,
                    'conviction': conviction,
                    'name': f'NAKED_POC_J-{days_ago}',
                })
        
        return naked

    # ─── 🆕 14/03/2026: PROFIL ROLLING 5 JOURS ───────────────────
    
    @staticmethod
    def compute_rolling_profile(daily_profiles: list) -> dict:
        """
        Calcule le profil moyen des 5 derniers jours — le timeframe réel du trader.
        
        Le composite 20/50j = bruit (prouvé r<0.04). Le rolling 5j capture
        la mémoire court terme : fair value, direction dominante, supports récents.
        
        Args:
            daily_profiles: [{date, vpoc, vah, val, high, low, close}, ...]
            
        Returns:
            {r5_vpoc_mean, r5_vah_mean, r5_val_mean, r5_va_width_mean,
             r5_direction (+1/0/-1), r5_direction_pct, r5_range_mean, valid}
        """
        if len(daily_profiles) < 3:
            return {'valid': False}
        
        import numpy as np
        recent = daily_profiles[-5:]
        
        vpocs = [d['vpoc'] for d in recent if d.get('vpoc', 0) > 0]
        vahs = [d['vah'] for d in recent if d.get('vah', 0) > 0]
        vals = [d['val'] for d in recent if d.get('val', 0) > 0]
        
        if len(vpocs) < 3:
            return {'valid': False}
        
        ups = sum(1 for d in recent if d.get('close', 0) > d.get('vpoc', 0))
        dir_pct = ups / len(recent)
        direction = 1 if dir_pct > 0.6 else (-1 if dir_pct < 0.4 else 0)
        
        ranges = [d['high'] - d['low'] for d in recent 
                  if d.get('high', 0) > 0 and d.get('low', 0) > 0]
        va_widths = [d['vah'] - d['val'] for d in recent
                     if d.get('vah', 0) > 0 and d.get('val', 0) > 0]
        
        return {
            'r5_vpoc_mean': float(np.mean(vpocs)),
            'r5_vah_mean': float(np.mean(vahs)) if vahs else 0,
            'r5_val_mean': float(np.mean(vals)) if vals else 0,
            'r5_va_width_mean': float(np.mean(va_widths)) if va_widths else 0,
            'r5_direction': direction,
            'r5_direction_pct': dir_pct,
            'r5_range_mean': float(np.mean(ranges)) if ranges else 0,
            'valid': True,
        }

    @staticmethod
    def summary(plan: SessionPlan):
        """Affiche un résumé du plan."""
        print(f"\n  ═══ SESSION PLAN — {plan.session.name} ═══")
        print(f"  Régime:     {plan.regime.name}")
        print(f"  Biais:      {'LONG' if plan.bias > 0 else ('SHORT' if plan.bias < 0 else 'NEUTRE')}")
        print(f"  Conviction: {plan.confidence:.0%}")
        print(f"  Type jour:  {plan.day_type.name}")
        print(f"  Profile:    {plan.prev_shape} | OT: {plan.open_type_name} | Gap: {plan.gap_type}")

        if plan.asia_ib.valid:
            ib = plan.asia_ib
            broke = ""
            if ib.broken_up: broke += " BROKE_UP"
            if ib.broken_dn: broke += " BROKE_DN"
            print(f"  Asia IB:    {ib.low:.2f}—{ib.high:.2f} ({ib.range_ticks:.0f}t){broke}")

        if plan.primary_target:
            t = plan.primary_target
            print(f"  Target #1:  {t.name} @ {t.distance_ticks:+.0f}t (conv={t.conviction:.0%})")

        if plan.targets_up:
            print(f"  Targets UP: {', '.join(f'{t.name}({t.distance_ticks:+.0f}t)' for t in plan.targets_up[:3])}")
        if plan.targets_dn:
            print(f"  Targets DN: {', '.join(f'{t.name}({t.distance_ticks:+.0f}t)' for t in plan.targets_dn[:3])}")

        print(f"  Modules ON: {', '.join(plan.modules_enabled)}")
        if plan.modules_disabled:
            print(f"  Modules OFF:{', '.join(plan.modules_disabled)}")
        print(f"  SL mode:    {plan.sl_mode} | Sizing: {plan.sizing_factor:.2f} | Max trades: {plan.max_trades}")
        print(f"  No-trade:   {len(plan.no_trade_zones)} zones")
        print(f"  Raison:     {plan.reason}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — INTÉGRATION mia_entry / mia_sltp / mia_sim
# ═══════════════════════════════════════════════════════════════════════════════
#
# Le SessionPlan s'intègre dans le pipeline existant de 3 façons :
#
# 1. mia_entry.py — Filtrage des signaux
#    ```python
#    def compute(self, df, plan: SessionPlan = None):
#        for i, row in df.iterrows():
#            # Vérifier no-trade zone
#            if plan and plan.is_no_trade(hour_et, min_et)[0]:
#                signals.append(EntrySignal())  # Pas de signal
#                continue
#
#            # Vérifier si le module est activé
#            if plan and 'RANGE_ENTRY' not in plan.modules_enabled:
#                range_sig = None  # Skip Range Entry
#
#            # Utiliser le biais du plan au lieu du biais CORE seul
#            if plan and plan.bias != 0:
#                combined_bias = 0.7 * plan.bias_from_plan + 0.3 * core_bias
#    ```
#
# 2. mia_sltp.py — Targets comme TP
#    ```python
#    def compute(self, df, plan: SessionPlan = None):
#        if plan and plan.primary_target:
#            # TP1 = premier obstacle avant le target
#            # TP3 = le target lui-même
#            tp3 = plan.primary_target.distance_ticks
#    ```
#
# 3. mia_sim.py — No-trade zones et sizing
#    ```python
#    def run(self, date, nq_raw, es_raw, plan: SessionPlan = None):
#        if plan:
#            self.cfg.max_trades_per_day = plan.max_trades
#            self.cfg.sizing_factor = plan.sizing_factor
#
#        for i in range(len(df)):
#            if plan and plan.is_no_trade(h, m)[0]:
#                continue  # Skip cette barre
#    ```
#
# L'intégration se fait de manière OPTIONNELLE — si plan=None, le pipeline
# fonctionne comme avant (rétro-compatible).


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def run_tests():
    """Tests unitaires du Session Planner."""
    passed = 0
    failed = 0

    def assert_eq(name, actual, expected):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
        else:
            failed += 1
            print(f"  ❌ {name}: got {actual}, expected {expected}")

    def assert_true(name, condition):
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"  ❌ {name}: condition False")

    print("=" * 60)
    print("  TESTS mia_session_planner.py")
    print("=" * 60)
    print()

    # ── Test 1: IBRange ──
    ib = IBRange(session='ASIA', high=24650, low=24500, mid=24575,
                 range_ticks=600, valid=True, broken_up=True)
    assert_eq("T01 - IB direction broken_up", ib.direction_bias, 1)

    ib2 = IBRange(session='ASIA', high=24650, low=24500, valid=True, broken_dn=True)
    assert_eq("T02 - IB direction broken_dn", ib2.direction_bias, -1)

    ib3 = IBRange(session='ASIA', valid=True)
    assert_eq("T03 - IB direction none", ib3.direction_bias, 0)

    # ── Test 2: SessionPlan no-trade ──
    plan = SessionPlan(session=SessionType.LONDON_ACTIVE)
    plan.no_trade_zones = [(150, 195, "LONDON_TRANS")]
    is_nt, reason = plan.is_no_trade(2, 35)
    assert_true("T04 - no-trade inside zone", is_nt)
    is_nt2, _ = plan.is_no_trade(3, 30)
    assert_true("T05 - no-trade outside zone", not is_nt2)

    # ── Test 3: SessionPlan active_ib ──
    plan2 = SessionPlan(session=SessionType.US_ACTIVE)
    plan2.asia_ib = IBRange(session='ASIA', valid=True, range_ticks=100)
    plan2.us_ib = IBRange(session='US', valid=True, range_ticks=200)
    assert_eq("T06 - active_ib = US when both valid", plan2.active_ib.session, 'US')

    plan3 = SessionPlan(session=SessionType.LONDON_ACTIVE)
    plan3.asia_ib = IBRange(session='ASIA', valid=True)
    assert_eq("T07 - active_ib = ASIA when only Asia", plan3.active_ib.session, 'ASIA')

    # ── Test 4: Target ──
    t = Target(name='PREV_VPOC', price=24600, distance_ticks=-50,
               tier=TargetTier.PRIMARY, role='magnet', reason='test')
    assert_eq("T08 - target direction positive dist", t.direction, 1)

    t2 = Target(name='PREV_VAL', price=24400, distance_ticks=50,
                tier=TargetTier.SECONDARY, role='support', reason='test')
    assert_eq("T09 - target direction negative dist", t2.direction, -1)

    # ── Test 5: Regime determination ──
    planner = SessionPlanner()

    # D shape → RANGE
    plan_d = SessionPlan(session=SessionType.LONDON_ACTIVE)
    plan_d.prev_shape = 'D'
    plan_d.open_type_name = 'OAIR'
    plan_d.gap_type = 'INSIDE'
    plan_d.asia_ib = IBRange(session='ASIA', valid=False)
    plan_d = planner._determine_regime(plan_d)
    assert_eq("T10 - D shape → RANGE", plan_d.regime, Regime.RANGE)

    # OD_UP → TREND_UP
    plan_od = SessionPlan(session=SessionType.US_ACTIVE)
    plan_od.prev_shape = 'B'
    plan_od.open_type_name = 'OD_UP'
    plan_od.gap_type = 'GAP_UP'
    plan_od.asia_ib = IBRange(session='ASIA', valid=False)
    plan_od = planner._determine_regime(plan_od)
    assert_eq("T11 - OD_UP → TREND_UP", plan_od.regime, Regime.TREND_UP)
    assert_eq("T12 - OD_UP → bias +1", plan_od.bias, 1)

    # P shape → bias SHORT
    plan_p = SessionPlan(session=SessionType.LONDON_ACTIVE)
    plan_p.prev_shape = 'P'
    plan_p.open_type_name = 'OAIR'
    plan_p.gap_type = 'INSIDE'
    plan_p.asia_ib = IBRange(session='ASIA', valid=False)
    plan_p = planner._determine_regime(plan_p)
    assert_eq("T13 - P shape → bias SHORT", plan_p.bias, -1)

    # ── Test 6: Module configuration ──
    plan_range = SessionPlan(session=SessionType.LONDON_ACTIVE, regime=Regime.RANGE)
    plan_range = planner._configure_modules(plan_range)
    assert_true("T14 - RANGE enables RANGE_ENTRY", 'RANGE_ENTRY' in plan_range.modules_enabled)
    assert_true("T15 - RANGE enables DOUBLE_TOP", 'DOUBLE_TOP' in plan_range.modules_enabled)

    plan_trend = SessionPlan(session=SessionType.US_ACTIVE, regime=Regime.TREND_UP)
    plan_trend = planner._configure_modules(plan_trend)
    assert_true("T16 - TREND disables RANGE_ENTRY", 'RANGE_ENTRY' in plan_trend.modules_disabled)

    # ── Test 7: Risk configuration ──
    plan_range_r = SessionPlan(session=SessionType.LONDON_ACTIVE, regime=Regime.RANGE, confidence=0.75)
    plan_range_r = planner._configure_risk(plan_range_r)
    assert_eq("T17 - RANGE → SL TIGHT", plan_range_r.sl_mode, 'TIGHT')
    assert_eq("T18 - RANGE → max 8 trades", plan_range_r.max_trades, 8)
    assert_true("T19 - high conv → sizing 1.25", plan_range_r.sizing_factor == 1.25)

    plan_trend_r = SessionPlan(session=SessionType.US_ACTIVE, regime=Regime.TREND_UP, confidence=0.30)
    plan_trend_r = planner._configure_risk(plan_trend_r)
    assert_eq("T20 - TREND → SL WIDE", plan_trend_r.sl_mode, 'WIDE')
    assert_true("T21 - low conv → sizing 0.75", plan_trend_r.sizing_factor == 0.75)

    # ── Test 8: No-trade zones ──
    plan_nt = SessionPlan(session=SessionType.LONDON_ACTIVE)
    plan_nt = planner._set_no_trade_zones(plan_nt)
    assert_true("T22 - has no-trade zones", len(plan_nt.no_trade_zones) >= 2)

    # ── Résumé ──
    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"  RÉSULTATS : {passed}/{total} tests passés", end="")
    if failed > 0:
        print(f" — {failed} ÉCHECS ❌")
    else:
        print(f" ✅ ALL PASS")
    print(f"{'=' * 60}")

    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_tests()
