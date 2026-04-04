"""
mia_entry.py — Couche 3 : Zone de réaction + Timing + Triggers autonomes
=========================================================================

Pont entre le BIAIS (score contextuel des 7 CORE) et le TRADE.
Ne trade que quand le biais est aligné avec un niveau clé proche,
OU quand un trigger autonome fire (RVOL absorption).

Schema 3.6.0 — 250 colonnes
🆕 13/03/2026: Couche 3B — RVOL Trigger (entrée autonome sur absorption)
   rvol_absorb_buy/sell + confirmations range/VA = signal direct sans biais

Architecture:
    Couche 1: Filtre (session, IB, macro)        → peut-on trader?
    Couche 2: Biais (score 7 CORE pondéré)       → quelle direction?
    Couche 3: Zone (niveaux clés proches)         → OÙ entrer?
    Couche 3B: RVOL Trigger (absorption autonome) → ENTRÉE DIRECTE
    Couche 3C: Range Entry (VA extrêmes)          → MEAN REVERSION
    Couche 3D: Double Top/Bottom (boost/pénalité)  → CONFIRMATION
    Couche 3E: Exhaustion Detector (multi-barres)  → REVERSAL
    Couche 3F: Séquence (momentum, vol climax, delta exhaust) → enrichit 3E
    Couche 4: SL/TP                               → quand sortir?

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_entry.py

Auteur : MIA Trading System
Date   : 2026-03-13
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

# 🆕 Module Double Top/Bottom (confirmation booster)
try:
    from mia_double_top import (
        detect_double_top_bottom, apply_retest_boost,
        RetestResult, RetestConfig
    )
    HAS_DOUBLE_TOP = True
except ImportError:
    HAS_DOUBLE_TOP = False


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES (parité C++ MIA_Layers.h avec adaptation barres 1-min)
# ═════════════════════════════════════════════════════════════════════

# Distance max en ticks pour considérer un niveau "proche"
# C++ = 20 ticks (tick-by-tick). Python 1-min = 40 ticks (le prix bouge plus)
ZONE_MAX_DIST_TICKS = 40

# Score 1 nécessite un niveau Score 2/3 dans ce rayon OU 2+ niveaux proches
SCORE1_STRONG_NEARBY_TICKS = 60   # C++ = 25, adapté

# Seuils de biais pour déclencher un signal
BIAS_THRESHOLD_STRONG = 0.15      # Score contextuel fort
BIAS_THRESHOLD_WEAK = 0.08        # Score contextuel minimum

# Confiance basée sur distance (parité C++ MIA_Layers.h)
CONF_CLOSE = 0.45                 # <= 8 ticks
CONF_MID = 0.35                   # 8-20 ticks
CONF_FAR = 0.25                   # 20-40 ticks
CONF_MIN = 0.20                   # En dessous = rejet

# Bonus/malus
IMPORTANCE_BONUS = {3: 0.10, 2: 0.05, 1: 0.00}
CONFLUENCE_BONUS = 0.05           # 2+ niveaux dans la zone

# ── COUCHE 3B : RVOL TRIGGER (entrée autonome) ───────────────────
# L'absorption est le signal le plus puissant en range trading:
#   - Volume spike (rvol >= 2.0x) = activité institutionnelle
#   - Delta contradictoire = un côté absorbé
#   - Finish contradictoire = prix rejette dans l'autre direction
# Ce trigger NE NÉCESSITE PAS de biais CORE — il fire en autonome.
# Confirmations requises: au moins 1 parmi (range_pos, inside_va, BN)

RVOL_TRIGGER_CONF_BASE = 0.55     # Confiance de base (absorption confirmée)
RVOL_TRIGGER_CONF_FULL = 0.75     # Confiance max (absorption + toutes confirmations)
RVOL_RANGE_TOP = 60               # range_pos > 60% = zone haute (SHORT absorb)
RVOL_RANGE_BOT = 40               # range_pos < 40% = zone basse (LONG absorb)
RVOL_MIN_CONFIRMATIONS = 1        # Au moins 1 confirmation requise

# ── COUCHE 3C : RANGE ENTRY (entrée autonome en range) ───────────
# Mean reversion dans la Value Area — prouvé par le bench 13/03:
#   VA TOP (>80%): 58% WR short, avg -1.9 pts
#   VA BOT (<20%): 59% WR long, avg +1.8 pts
# Ce trigger fire quand le prix est aux extrêmes de la VA.
# Confirmations requises: au moins 1 parmi (BN score, diag_imbalance, rvol, retest)

RANGE_ENTRY_CONF_BASE = 0.50      # Confiance de base (extrême VA)
RANGE_ENTRY_CONF_FULL = 0.70      # Confiance max (toutes confirmations)
RANGE_VA_TOP = 0.80               # va_position_pct > 80% = SHORT zone
RANGE_VA_BOT = 0.20               # va_position_pct < 20% = LONG zone
RANGE_MIN_CONFIRMATIONS = 1       # Au moins 1 confirmation requise

# ── COUCHE 3E : EXHAUSTION DETECTOR (reversal multi-barres) ──────
# Détecte l'épuisement d'un mouvement via:
#   - 3+ barres consécutives même direction (momentum épuisé)
#   - Finish strength contradictoire (dernière barre rejette)
#   - Delta ou momentum confirme le retournement
# Prouvé sur NQ 13/03: 3down+finish>20 = 75% WR, avg +3.1 pts

EXHAUST_CONF_BASE = 0.50          # Confiance de base
EXHAUST_CONF_FULL = 0.70          # Confiance max
EXHAUST_N_BARS = 3                # Barres consécutives minimum
EXHAUST_FINISH_MIN = 15           # Finish strength minimum (contradictoire)
EXHAUST_FINISH_STRONG = 25        # Finish strength fort → bonus
EXHAUST_MIN_CONFIRMATIONS = 1     # Au moins 1 confirmation

# ── COUCHE 3F : SÉQUENCE MULTI-BARRES (enrichit l'exhaustion) ────
# Patterns complémentaires qui détectent l'épuisement sans N barres consécutives:
#   - Momentum deceleration: momentum_5b extrême + finish contradictoire (71% WR)
#   - Volume climax: rvol spike (≥2x) sur dernière barre d'un mouvement
#   - Delta exhaustion: delta diminue sur N barres pendant que le prix continue
# Ces patterns enrichissent _precompute_exhaustion — pas un module séparé.

MOMENTUM_DECEL_THRESHOLD = 4.0    # momentum_5b > ±4.0 = mouvement fort
VOLUME_CLIMAX_RVOL = 2.5         # rvol ≥ 2.5x = volume climax
DELTA_EXHAUST_BARS = 3            # Nombre de barres pour divergence delta/prix

# Pondération features NOYAU DUR (7 features, 5 domaines, zéro redondance)
# Tri: 252 cols → 100 vivantes → 15 signal → 10 propres → 7 noyau dur
# Chaque feature a son domaine pour la pondération contextuelle.
CORE_FEATURES = {
    # (weight, domain)
    'profile_skew':              (-0.200, 'PROFIL'),
    'single_print_count':        (+0.205, 'PROFIL'),
    'im_cross_delta_weighted_5': (-0.170, 'INTERMAR'),
    'ctx_mq_put_call_ratio':     (-0.136, 'GAMMA'),
    'dist_gex_nearest_up':       (+0.159, 'GAMMA'),
    'dist_ovn_high':             (-0.125, 'STRUCTURE'),
    'ctx_cvd_recovery_rate':     (+0.072, 'MOMENTUM'),
}

# Pondération contextuelle (prouvée sur 2 jours)
VA_BOOST_INSIDE = 2.0             # PROFIL features × 2.0 quand inside VA
VA_BOOST_OUTSIDE = 0.5            # PROFIL features × 0.5 quand outside VA
IM_BOOST_US = 1.5                 # INTERMAR features × 1.5 en session US
IM_BOOST_OTHER = 0.3              # INTERMAR features × 0.3 en Asia/London


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═════════════════════════════════════════════════════════════════════

@dataclass
class NearbyLevel:
    """Un niveau clé proche du prix."""
    name: str
    dist_ticks: float             # Distance signée en ticks
    abs_dist: float               # |distance|
    importance: int               # 3=majeur, 2=important, 1=base
    role: str                     # 'support', 'resist', 'both'
    direction: int                # +1=LONG (support), -1=SHORT (resist)


@dataclass
class EntrySignal:
    """Résultat de l'évaluation d'entrée."""
    has_signal: bool = False
    direction: int = 0            # +1=LONG, -1=SHORT
    confidence: float = 0.0       # 0.0 → 1.0
    bias_score: float = 0.0       # Score contextuel brut
    zone_name: str = ""           # Niveau principal
    zone_dist: float = 0.0        # Distance au niveau (ticks)
    zone_importance: int = 0      # Score 1-3
    n_levels_nearby: int = 0      # Nombre de niveaux dans la zone
    reason: str = ""


# ═════════════════════════════════════════════════════════════════════
# LEVEL MAP — Colonnes DMP → Niveaux (parité C++ MIA_Layers.h)
# ═════════════════════════════════════════════════════════════════════

LEVEL_MAP = {
    # col_dmp:           (name,        score, role)
    # Score 3 — MAJEUR (C++ : HVL, GAMMA, GEX 1-3)
    'dist_mq_hvl':       ('MQ_HVL',       3, 'both'),
    'dist_mq_call_0dte': ('MQ_CALL0D',    3, 'resist'),
    'dist_mq_put_0dte':  ('MQ_PUT0D',     3, 'support'),

    # Score 2 — IMPORTANT (C++ : PUT/CALL, 1D, VA, IB, SESSION)
    'dist_mq_call':      ('MQ_CALL',      2, 'resist'),
    'dist_mq_put':       ('MQ_PUT',       2, 'support'),
    'dist_1d_max_ticks': ('MQ_1D_MAX',    2, 'resist'),
    'dist_1d_min_ticks': ('MQ_1D_MIN',    2, 'support'),
    'dist_prev_vpoc':    ('PREV_VPOC',    2, 'both'),
    'dist_prev_vah':     ('PREV_VAH',     2, 'resist'),
    'dist_prev_val':     ('PREV_VAL',     2, 'support'),
    'dist_cur_vpoc':     ('CUR_VPOC',     2, 'both'),
    'dist_cur_vah':      ('CUR_VAH',      2, 'resist'),
    'dist_cur_val':      ('CUR_VAL',      2, 'support'),
    'dist_ib_high':      ('IB_HIGH',      2, 'resist'),
    'dist_ib_low':       ('IB_LOW',       2, 'support'),
    'dist_gex_nearest_up': ('GEX_UP',     2, 'resist'),
    'dist_gex_nearest_dn': ('GEX_DN',     2, 'support'),

    # 🆕 Schema 3.5.2 — Edge Zones (imbalance clusters, Extension Lines)
    'dist_ext_edge_buy':  ('EXT_EDGE_BUY',  2, 'support'),
    'dist_ext_edge_sell': ('EXT_EDGE_SELL',  2, 'resist'),

    # Score 1 — BASE (C++ : VWAP, SD, BLIND)
    'dist_vwap_d':       ('VWAP_D',       1, 'both'),
    'dist_open_cash':    ('OPEN_CASH',    1, 'both'),
    'dist_comp_20d_vpoc': ('COMP20_VPOC', 1, 'both'),

    # 🆕 Schema 3.5.2 — COLOR Zones (Extension Lines distances)
    'dist_ext_color_up':  ('EXT_COLOR_UP',  1, 'support'),
    'dist_ext_color_dn':  ('EXT_COLOR_DN',  1, 'resist'),
}


# ═════════════════════════════════════════════════════════════════════
# COUCHE 3 — ENTRY ENGINE
# ═════════════════════════════════════════════════════════════════════

class EntryEngine:
    """
    Évalue si les conditions sont réunies pour entrer en position.

    Combine:
    1. Score contextuel (biais directionnel, Couche 2)
    2. Proximité d'un niveau clé (zone de réaction)
    3. Alignement biais + direction du niveau

    Usage:
        engine = EntryEngine()
        df = engine.compute(df_enriched)
        # df contient maintenant: entry_signal, entry_dir, entry_conf, entry_zone
    """

    def __init__(self,
                 zone_max_dist: int = ZONE_MAX_DIST_TICKS,
                 bias_threshold: float = BIAS_THRESHOLD_WEAK):
        self.zone_max_dist = zone_max_dist
        self.bias_threshold = bias_threshold

    # ─── MAIN ──────────────────────────────────────────────────────

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcule les signaux d'entrée pour chaque barre.

        Args:
            df: DataFrame enrichi (DMP + ctx_* + im_*)
                Doit contenir: les colonnes dist_*, inside_prev_va,
                session_id, et les 4 features BÉTON

        Returns:
            DataFrame avec colonnes ajoutées:
                entry_signal:     1=LONG, -1=SHORT, 0=pas de signal
                entry_conf:       confiance 0.0-1.0
                entry_zone:       nom du niveau principal
                entry_zone_dist:  distance au niveau (ticks)
                entry_zone_score: importance du niveau (1-3)
                entry_n_levels:   nombre de niveaux proches
                entry_bias:       score contextuel brut
        """
        df = df.copy()

        # Pré-calculer le biais contextuel pour toutes les barres
        bias = self._compute_bias(df)

        # Préparer les barres en list[dict] pour mia_double_top
        bars_list = df.to_dict('records') if HAS_DOUBLE_TOP else None

        # Pré-calculer les signaux d'exhaustion (besoin de lookback sur prix)
        exhaust_signals = self._precompute_exhaustion(df)

        # Évaluer barre par barre
        signals = []
        for i in range(len(df)):
            row = df.iloc[i]
            b = bias.iloc[i]
            exhaust = exhaust_signals[i]
            sig = self._evaluate_bar(row, b, exhaust)

            # 🆕 Couche 3D: Double Top/Bottom boost/penalty
            if HAS_DOUBLE_TOP and sig.has_signal and bars_list is not None:
                sig = self._apply_double_top(sig, bars_list, i)

            signals.append(sig)

        # Injecter dans le DataFrame
        df['entry_signal'] = [s.direction if s.has_signal else 0 for s in signals]
        df['entry_conf'] = [s.confidence for s in signals]
        df['entry_zone'] = [s.zone_name for s in signals]
        df['entry_zone_dist'] = [s.zone_dist for s in signals]
        df['entry_zone_score'] = [s.zone_importance for s in signals]
        df['entry_n_levels'] = [s.n_levels_nearby for s in signals]
        df['entry_bias'] = [s.bias_score for s in signals]

        return df

    # ─── COUCHE 2 : BIAIS CONTEXTUEL ──────────────────────────────

    def _compute_bias(self, df: pd.DataFrame) -> pd.Series:
        """
        Score contextuel pondéré par le contexte (inside VA, session).
        Utilise les 7 CORE_FEATURES avec pondération par domaine.
        Retourne une Series de score [-inf, +inf].
        Positif = biais LONG, négatif = biais SHORT.
        """
        inside_va = (df.get('inside_prev_va', pd.Series(0, index=df.index)) == 1)
        is_us = (df.get('session_id', pd.Series('', index=df.index)) == 'US')

        score = pd.Series(0.0, index=df.index)

        for col, (base_w, domain) in CORE_FEATURES.items():
            if col not in df.columns:
                continue

            vals = df[col]
            std = vals.std()
            if std == 0 or pd.isna(std):
                continue
            z = (vals - vals.mean()) / std

            # Pondération contextuelle par domaine
            if domain == 'PROFIL':
                w = np.where(inside_va, base_w * VA_BOOST_INSIDE,
                             base_w * VA_BOOST_OUTSIDE)
            elif domain == 'INTERMAR':
                w = np.where(is_us, base_w * IM_BOOST_US,
                             base_w * IM_BOOST_OTHER)
            else:
                w = base_w

            score += w * z

        return score

    # ─── COUCHE 3 : ÉVALUATION PAR BARRE ─────────────────────────

    def _evaluate_bar(self, row: pd.Series, bias: float, exhaust: dict = None) -> EntrySignal:
        """Évalue une barre individuelle."""

        # ═══ COUCHE 3B: RVOL TRIGGER (prioritaire, autonome) ═══
        rvol_sig = self._evaluate_rvol_trigger(row, bias)
        if rvol_sig is not None:
            return rvol_sig

        # ═══ COUCHE 3C: RANGE ENTRY (autonome, mean reversion VA) ═══
        range_sig = self._evaluate_range_entry(row, bias)
        if range_sig is not None:
            return range_sig

        # ═══ COUCHE 3E: EXHAUSTION DETECTOR (autonome, reversal) ═══
        if exhaust is not None and exhaust.get('active', False):
            exhaust_sig = self._evaluate_exhaustion(row, bias, exhaust)
            if exhaust_sig is not None:
                return exhaust_sig

        # ═══ COUCHE 3: ZONE DE RÉACTION (flow normal) ═══
        # 0. Biais trop faible → pas de signal
        if pd.isna(bias) or abs(bias) < self.bias_threshold:
            return EntrySignal(bias_score=bias if not pd.isna(bias) else 0.0)

        bias_dir = 1 if bias > 0 else -1

        # 1. Scanner tous les niveaux proches
        nearby = self._scan_levels(row)

        if not nearby:
            return EntrySignal(bias_score=bias,
                               reason="Biais OK mais aucun niveau proche")

        # 2. Filtrer: Score 1 nécessite confluence
        has_strong = any(lv.importance >= 2 and lv.abs_dist < SCORE1_STRONG_NEARBY_TICKS
                         for lv in nearby)
        n_in_zone = len(nearby)

        filtered = []
        for lv in nearby:
            if lv.importance >= 2:
                filtered.append(lv)
            elif lv.importance == 1 and (has_strong or n_in_zone >= 2):
                filtered.append(lv)
            # Score 1 seul sans confluence → skip (parité C++)

        if not filtered:
            return EntrySignal(bias_score=bias,
                               reason="Niveaux Score 1 seuls, pas de confluence")

        # 3. Trouver le meilleur niveau ALIGNÉ avec le biais
        best = None
        for lv in filtered:
            # Alignement: biais SHORT + niveau résistance au-dessus = OK
            #             biais LONG  + niveau support en-dessous = OK
            if bias_dir == lv.direction:
                if best is None or lv.importance > best.importance or (
                    lv.importance == best.importance and lv.abs_dist < best.abs_dist):
                    best = lv

        if best is None:
            # Biais et niveaux en conflit → pas de trade
            names = [lv.name for lv in filtered[:3]]
            return EntrySignal(
                bias_score=bias,
                reason=f"Biais {'LONG' if bias_dir>0 else 'SHORT'} "
                       f"mais niveaux opposés: {','.join(names)}")

        # 4. Calculer la confiance
        conf = self._calc_confidence(best, n_in_zone, abs(bias), row)

        if conf < CONF_MIN:
            return EntrySignal(bias_score=bias,
                               reason=f"Confiance trop faible: {conf:.2f}")

        # 5. Signal validé
        return EntrySignal(
            has_signal=True,
            direction=bias_dir,
            confidence=conf,
            bias_score=bias,
            zone_name=best.name,
            zone_dist=best.abs_dist,
            zone_importance=best.importance,
            n_levels_nearby=n_in_zone,
            reason=f"{'LONG' if bias_dir>0 else 'SHORT'} @ {best.name} "
                   f"({best.abs_dist:.0f}t, score={best.importance})"
        )

    # ─── COUCHE 3B : RVOL TRIGGER ────────────────────────────────

    def _evaluate_rvol_trigger(self, row: pd.Series, bias: float) -> 'EntrySignal | None':
        """
        Détecte les entrées autonomes sur absorption RVOL.
        Retourne un EntrySignal si absorption confirmée, None sinon.
        
        Logique:
          1. rvol_absorb_buy/sell == 1 (déjà filtré: rvol≥2x + delta contradictoire + finish)
          2. Au moins 1 confirmation parmi:
             a) Position dans le range (range_pos < 40 pour LONG, > 60 pour SHORT)
             b) Inside Value Area (inside_cur_va == 1)
             c) BN score aligné (bn_score_raw > 0 pour LONG, < 0 pour SHORT)
             d) Biais CORE aligné (même direction)
          3. Confiance = base (0.55) + 0.05 par confirmation supplémentaire (max 0.75)
        """
        abs_buy = row.get('rvol_absorb_buy', 0)
        abs_sell = row.get('rvol_absorb_sell', 0)

        if abs_buy != 1 and abs_sell != 1:
            return None

        # Déterminer la direction
        if abs_buy == 1:
            direction = 1   # LONG — vendeurs absorbés, prix va monter
            trigger_name = 'RVOL_ABS_BUY'
        else:
            direction = -1  # SHORT — acheteurs absorbés, prix va baisser
            trigger_name = 'RVOL_ABS_SELL'

        # Collecter les confirmations
        confirmations = []
        range_pos = row.get('range_pos', 50)
        inside_va = row.get('inside_cur_va', 0)
        bn_raw = row.get('bn_score_raw', 0)
        rvol_dir = row.get('rvol_buy' if direction == 1 else 'rvol_sell', 0)

        # a) Position dans le range
        if direction == 1 and range_pos < RVOL_RANGE_BOT:
            confirmations.append('RANGE_BOT')
        elif direction == -1 and range_pos > RVOL_RANGE_TOP:
            confirmations.append('RANGE_TOP')

        # b) Inside Value Area
        if inside_va == 1:
            confirmations.append('IN_VA')

        # c) BN score aligné
        if direction == 1 and bn_raw > 0.1:
            confirmations.append('BN_BULL')
        elif direction == -1 and bn_raw < -0.1:
            confirmations.append('BN_BEAR')

        # d) Biais CORE aligné (pas requis mais bonus)
        if not pd.isna(bias):
            if direction == 1 and bias > BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_LONG')
            elif direction == -1 and bias < -BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_SHORT')

        # e) RVOL directionnel aussi actif (spike + delta same direction)
        if rvol_dir == 1:
            confirmations.append('RVOL_DIR')

        # Minimum de confirmations
        if len(confirmations) < RVOL_MIN_CONFIRMATIONS:
            return None  # Absorption sans confirmation → trop risqué

        # Calculer confiance
        conf = RVOL_TRIGGER_CONF_BASE
        conf += 0.05 * (len(confirmations) - 1)  # +0.05 par confirmation en plus
        conf = min(conf, RVOL_TRIGGER_CONF_FULL)

        tags = '+'.join([trigger_name] + confirmations)
        return EntrySignal(
            has_signal=True,
            direction=direction,
            confidence=conf,
            bias_score=bias if not pd.isna(bias) else 0.0,
            zone_name=trigger_name,
            zone_dist=0.0,      # Pas de zone — l'absorption EST le signal
            zone_importance=3,   # Score MAJEUR (équivalent GEX/HVL)
            n_levels_nearby=len(confirmations),
            reason=f"{'LONG' if direction>0 else 'SHORT'} RVOL ABSORPTION [{tags}]"
        )

    # ─── COUCHE 3C : RANGE ENTRY ─────────────────────────────────

    def _evaluate_range_entry(self, row: pd.Series, bias: float) -> 'EntrySignal | None':
        """
        Détecte les entrées autonomes en mean reversion dans la Value Area.
        
        Logique:
          1. Prix aux extrêmes de la VA (va_position_pct > 80% ou < 20%)
          2. Doit être inside_cur_va == 1 (pas un breakout)
          3. Au moins 1 confirmation parmi:
             a) BN score aligné (bear au top, bull au bottom)
             b) Diagonal imbalance aligné (sellers au top, buyers au bottom)
             c) RVOL spike directionnel (rvol_buy/sell)
             d) Retest swing (retest_high_count ou retest_low_count > 0)
             e) Biais CORE aligné
          4. Confiance = base (0.50) + 0.05 par confirmation (max 0.70)
        """
        inside_va = row.get('inside_cur_va', 0)
        if inside_va != 1:
            return None

        va_pos = row.get('va_position_pct', 0.5)
        if va_pos is None or pd.isna(va_pos):
            return None

        # Déterminer la direction
        if va_pos > RANGE_VA_TOP:
            direction = -1   # SHORT — prix au top de la VA → mean reversion down
            trigger_name = 'RANGE_VA_TOP'
        elif va_pos < RANGE_VA_BOT:
            direction = 1    # LONG — prix au bottom de la VA → mean reversion up
            trigger_name = 'RANGE_VA_BOT'
        else:
            return None  # Milieu de la VA → pas de signal

        # Collecter les confirmations
        confirmations = []

        # a) BN score aligné
        bn_raw = row.get('bn_score_raw', 0) or 0
        if direction == -1 and bn_raw < -0.1:
            confirmations.append('BN_BEAR')
        elif direction == 1 and bn_raw > 0.1:
            confirmations.append('BN_BULL')

        # b) Diagonal imbalance
        diag = row.get('diag_imbalance', 0) or 0
        if direction == -1 and diag < -0.2:
            confirmations.append('DIAG_SELL')
        elif direction == 1 and diag > 0.2:
            confirmations.append('DIAG_BUY')

        # c) RVOL spike directionnel
        if direction == 1 and row.get('rvol_buy', 0) == 1:
            confirmations.append('RVOL_BUY')
        elif direction == -1 and row.get('rvol_sell', 0) == 1:
            confirmations.append('RVOL_SELL')

        # d) Retest swing
        if direction == -1 and (row.get('retest_high_count', 0) or 0) > 0:
            confirmations.append('RETEST_HIGH')
        elif direction == 1 and (row.get('retest_low_count', 0) or 0) > 0:
            confirmations.append('RETEST_LOW')

        # e) Biais CORE aligné
        if not pd.isna(bias):
            if direction == 1 and bias > BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_LONG')
            elif direction == -1 and bias < -BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_SHORT')

        # Minimum de confirmations
        if len(confirmations) < RANGE_MIN_CONFIRMATIONS:
            return None

        # Calculer confiance
        conf = RANGE_ENTRY_CONF_BASE
        conf += 0.05 * (len(confirmations) - 1)
        conf = min(conf, RANGE_ENTRY_CONF_FULL)

        tags = '+'.join([trigger_name] + confirmations)
        return EntrySignal(
            has_signal=True,
            direction=direction,
            confidence=conf,
            bias_score=bias if not pd.isna(bias) else 0.0,
            zone_name=trigger_name,
            zone_dist=0.0,
            zone_importance=2,   # Score IMPORTANT (équivalent CUR_VA)
            n_levels_nearby=len(confirmations),
            reason=f"{'LONG' if direction>0 else 'SHORT'} RANGE ENTRY [{tags}]"
        )

    # ─── COUCHE 3E : EXHAUSTION DETECTOR ─────────────────────────

    def _precompute_exhaustion(self, df: pd.DataFrame) -> list:
        """
        Pré-calcule les signaux d'exhaustion pour chaque barre.
        Retourne une liste de dicts avec les infos de détection.
        
        Patterns détectés:
          A) N barres consécutives même direction + finish contradictoire
          B) Momentum deceleration: momentum_5b extrême + finish contradictoire
          C) Volume climax: rvol spike sur la dernière barre d'un mouvement directionnel
          D) Delta exhaustion: delta diminue pendant que le prix continue (divergence)
        """
        prices = df['price'].values
        finish = df['finish_strength'].values if 'finish_strength' in df.columns else np.zeros(len(df))
        momentum_5b = df['momentum_5b'].values if 'momentum_5b' in df.columns else np.zeros(len(df))
        rvol_vals = df['rvol'].values if 'rvol' in df.columns else np.ones(len(df))
        delta_bars = df['delta_bar'].values if 'delta_bar' in df.columns else np.zeros(len(df))
        n = len(df)
        results = [{'active': False} for _ in range(n)]

        for i in range(EXHAUST_N_BARS, n):
            # ── Pattern A: N barres consécutives + finish contradictoire ──
            all_down = True
            for j in range(EXHAUST_N_BARS):
                if prices[i - EXHAUST_N_BARS + j + 1] >= prices[i - EXHAUST_N_BARS + j]:
                    all_down = False
                    break

            all_up = True
            for j in range(EXHAUST_N_BARS):
                if prices[i - EXHAUST_N_BARS + j + 1] <= prices[i - EXHAUST_N_BARS + j]:
                    all_up = False
                    break

            f = finish[i] if not np.isnan(finish[i]) else 0.0

            if all_down and f > EXHAUST_FINISH_MIN:
                move_size = abs(prices[i] - prices[i - EXHAUST_N_BARS])
                results[i] = {
                    'active': True,
                    'direction': 1,
                    'type': 'DOWN_EXHAUST',
                    'n_bars': EXHAUST_N_BARS,
                    'finish': f,
                    'move_size': move_size,
                    'strong': f > EXHAUST_FINISH_STRONG,
                }
                continue

            elif all_up and f < -EXHAUST_FINISH_MIN:
                move_size = abs(prices[i] - prices[i - EXHAUST_N_BARS])
                results[i] = {
                    'active': True,
                    'direction': -1,
                    'type': 'UP_EXHAUST',
                    'n_bars': EXHAUST_N_BARS,
                    'finish': f,
                    'move_size': move_size,
                    'strong': f < -EXHAUST_FINISH_STRONG,
                }
                continue

            # ── Pattern B: Momentum deceleration + finish contradictoire ──
            mom = momentum_5b[i] if not np.isnan(momentum_5b[i]) else 0.0
            if mom < -MOMENTUM_DECEL_THRESHOLD and f > EXHAUST_FINISH_MIN:
                results[i] = {
                    'active': True,
                    'direction': 1,
                    'type': 'MOM_DECEL_BUY',
                    'n_bars': 5,
                    'finish': f,
                    'move_size': abs(mom),
                    'strong': f > EXHAUST_FINISH_STRONG,
                }
                continue

            elif mom > MOMENTUM_DECEL_THRESHOLD and f < -EXHAUST_FINISH_MIN:
                results[i] = {
                    'active': True,
                    'direction': -1,
                    'type': 'MOM_DECEL_SELL',
                    'n_bars': 5,
                    'finish': f,
                    'move_size': abs(mom),
                    'strong': f < -EXHAUST_FINISH_STRONG,
                }
                continue

            # ── Pattern C: Volume climax sur mouvement directionnel ──
            rv = rvol_vals[i] if not np.isnan(rvol_vals[i]) else 1.0
            if rv >= VOLUME_CLIMAX_RVOL and i >= 2:
                # Prix montait sur 2+ barres + rvol spike + finish rejette
                if prices[i] > prices[i-1] > prices[i-2] and f < -EXHAUST_FINISH_MIN:
                    results[i] = {
                        'active': True,
                        'direction': -1,
                        'type': 'VOL_CLIMAX_SELL',
                        'n_bars': 2,
                        'finish': f,
                        'move_size': rv,
                        'strong': rv >= 3.0,
                    }
                    continue

                elif prices[i] < prices[i-1] < prices[i-2] and f > EXHAUST_FINISH_MIN:
                    results[i] = {
                        'active': True,
                        'direction': 1,
                        'type': 'VOL_CLIMAX_BUY',
                        'n_bars': 2,
                        'finish': f,
                        'move_size': rv,
                        'strong': rv >= 3.0,
                    }
                    continue

            # ── Pattern D: Delta exhaustion (delta diminue pendant que prix continue) ──
            if i >= DELTA_EXHAUST_BARS:
                deltas = [delta_bars[i-k] for k in range(DELTA_EXHAUST_BARS)]
                # Prix monte mais delta diminue à chaque barre
                price_up = all(prices[i-k] > prices[i-k-1] for k in range(DELTA_EXHAUST_BARS))
                delta_declining = all(deltas[k] < deltas[k+1] for k in range(DELTA_EXHAUST_BARS-1))
                if price_up and delta_declining and deltas[0] < 0:
                    results[i] = {
                        'active': True,
                        'direction': -1,
                        'type': 'DELTA_EXHAUST_SELL',
                        'n_bars': DELTA_EXHAUST_BARS,
                        'finish': f,
                        'move_size': abs(deltas[0]),
                        'strong': abs(deltas[0]) > 20,
                    }
                    continue

                # Prix baisse mais delta augmente (acheteurs reviennent)
                price_dn = all(prices[i-k] < prices[i-k-1] for k in range(DELTA_EXHAUST_BARS))
                delta_rising = all(deltas[k] > deltas[k+1] for k in range(DELTA_EXHAUST_BARS-1))
                if price_dn and delta_rising and deltas[0] > 0:
                    results[i] = {
                        'active': True,
                        'direction': 1,
                        'type': 'DELTA_EXHAUST_BUY',
                        'n_bars': DELTA_EXHAUST_BARS,
                        'finish': f,
                        'move_size': abs(deltas[0]),
                        'strong': abs(deltas[0]) > 20,
                    }
                    continue

        return results

    def _evaluate_exhaustion(self, row: pd.Series, bias: float, exhaust: dict) -> 'EntrySignal | None':
        """
        Évalue un signal d'exhaustion détecté par _precompute_exhaustion.
        
        Confirmations:
          a) Finish strength fort (> EXHAUST_FINISH_STRONG)
          b) Delta contradictoire (acheteurs reviennent après N-down, ou inverse)
          c) BN score aligné avec le reversal
          d) Inside VA (mean reversion plus fiable)
          e) Biais CORE aligné
        """
        direction = exhaust['direction']
        trigger_name = exhaust['type']

        confirmations = []

        # a) Finish fort
        if exhaust.get('strong', False):
            confirmations.append('STRONG_FINISH')

        # b) Delta contradictoire
        delta_pct = row.get('delta_pct', 0) or 0
        if direction == 1 and delta_pct > 0.10:
            confirmations.append('DELTA_BUY')
        elif direction == -1 and delta_pct < -0.10:
            confirmations.append('DELTA_SELL')

        # c) BN score aligné
        bn_raw = row.get('bn_score_raw', 0) or 0
        if direction == 1 and bn_raw > 0.1:
            confirmations.append('BN_BULL')
        elif direction == -1 and bn_raw < -0.1:
            confirmations.append('BN_BEAR')

        # d) Inside VA
        if row.get('inside_cur_va', 0) == 1:
            confirmations.append('IN_VA')

        # e) Biais CORE aligné
        if not pd.isna(bias):
            if direction == 1 and bias > BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_LONG')
            elif direction == -1 and bias < -BIAS_THRESHOLD_WEAK:
                confirmations.append('BIAS_SHORT')

        # Minimum de confirmations
        if len(confirmations) < EXHAUST_MIN_CONFIRMATIONS:
            return None

        # Confiance
        conf = EXHAUST_CONF_BASE
        conf += 0.05 * (len(confirmations) - 1)
        conf = min(conf, EXHAUST_CONF_FULL)

        tags = '+'.join([trigger_name] + confirmations)
        return EntrySignal(
            has_signal=True,
            direction=direction,
            confidence=conf,
            bias_score=bias if not pd.isna(bias) else 0.0,
            zone_name=trigger_name,
            zone_dist=0.0,
            zone_importance=2,
            n_levels_nearby=len(confirmations),
            reason=f"{'LONG' if direction>0 else 'SHORT'} EXHAUSTION [{tags}]"
        )

    # ─── COUCHE 3D : DOUBLE TOP/BOTTOM ──────────────────────────

    def _apply_double_top(self, sig: EntrySignal, bars: list, idx: int) -> EntrySignal:
        """
        Applique le boost/pénalité double top/bottom au signal existant.

        - detect_double_top_bottom() scanne les swings sur fenêtre glissante
        - Retest aligné avec le signal → boost confiance (+0.08 à +0.30)
        - Retest contra le signal → pénalité (-0.25, peut annuler le trade)
        - Pas de retest → signal inchangé
        """
        try:
            sym = bars[idx].get('sym', 'NQ') if idx < len(bars) else 'NQ'
            retest = detect_double_top_bottom(bars, idx, symbol=sym)

            if not retest.is_active():
                return sig  # Pas de retest → inchangé

            # Appliquer le boost/pénalité
            new_conf, reason = apply_retest_boost(
                trigger_score=sig.confidence,
                trade_direction=sig.direction,
                retest=retest
            )

            # Si la pénalité annule le trade (confiance < CONF_MIN)
            if new_conf < CONF_MIN:
                return EntrySignal(
                    bias_score=sig.bias_score,
                    reason=f"ANNULÉ par {reason} (conf={new_conf:.2f} < {CONF_MIN})"
                )

            # Mettre à jour le signal
            sig.confidence = new_conf
            if reason:
                sig.zone_name = f"{sig.zone_name}[{reason}]"
                sig.reason = f"{sig.reason} + {reason}"

            return sig

        except Exception:
            return sig  # Ne pas casser le pipeline

    # ─── SCANNER LES NIVEAUX ─────────────────────────────────────

    def _scan_levels(self, row: pd.Series) -> List[NearbyLevel]:
        """Trouve tous les niveaux à moins de zone_max_dist ticks."""
        nearby = []

        for col, (name, importance, role) in LEVEL_MAP.items():
            if col not in row.index:
                continue

            dist = row[col]
            if pd.isna(dist):
                continue

            abs_d = abs(dist)
            if abs_d > self.zone_max_dist:
                continue

            # Direction du trade selon le rôle et la position
            # Convention dist: positif = niveau AU-DESSUS du prix
            #   Support (niveau en-dessous): dist < 0 → LONG (rebond)
            #   Resist  (niveau au-dessus):  dist > 0 → SHORT (rejet)
            #   Both:   dist > 0 → résistance → SHORT, dist < 0 → support → LONG
            # Parité C++ : dir = (current_price > level) ? 1 : -1
            #   price > level ↔ dist < 0 → dir = +1 (support → LONG)
            if role == 'support':
                direction = 1     # Support → LONG
            elif role == 'resist':
                direction = -1    # Résistance → SHORT
            else:  # both
                direction = 1 if dist < 0 else -1  # sous le prix=support→LONG, dessus=resist→SHORT

            nearby.append(NearbyLevel(
                name=name, dist_ticks=dist, abs_dist=abs_d,
                importance=importance, role=role, direction=direction
            ))

        # Trier: importance desc, puis distance asc
        nearby.sort(key=lambda lv: (-lv.importance, lv.abs_dist))
        return nearby

    # ─── CONFIANCE ────────────────────────────────────────────────

    def _calc_confidence(self, level: NearbyLevel, n_levels: int,
                         bias_strength: float, row: pd.Series = None) -> float:
        """
        Calcule la confiance du signal.
        Parité C++ : distance + importance + confluence.
        🆕 3.5.2: bonus COLOR_2, retest_delta_div, BN score.
        """
        # Base: distance
        d = level.abs_dist
        if d <= 8:
            conf = CONF_CLOSE      # 0.45
        elif d <= 20:
            conf = CONF_MID        # 0.35
        else:
            conf = CONF_FAR        # 0.25

        # Bonus importance (parité C++)
        conf += IMPORTANCE_BONUS.get(level.importance, 0)

        # Bonus confluence
        if n_levels >= 2:
            conf += CONFLUENCE_BONUS

        # Bonus biais fort
        if bias_strength > BIAS_THRESHOLD_STRONG:
            conf += 0.05

        # 🆕 3.5.2: Bonus signaux BN confirmant la direction
        if row is not None:
            direction = level.direction

            # COLOR_2 (double stacké = continuation) dans la direction du trade
            if direction == 1 and row.get('bn_color_up_2', 0) == 1:
                conf += 0.05
            if direction == -1 and row.get('bn_color_dn_2', 0) == 1:
                conf += 0.05

            # Retest swing + divergence delta = setup de retournement fort
            if direction == -1 and row.get('retest_high_delta_div', 0) == 1:
                conf += 0.08
            if direction == 1 and row.get('retest_low_delta_div', 0) == 1:
                conf += 0.08

            # BN score composite fort dans la direction
            bn_raw = row.get('bn_score_raw', 0)
            if direction == 1 and bn_raw > 0.5:
                conf += 0.05
            if direction == -1 and bn_raw < -0.5:
                conf += 0.05

        return min(1.0, conf)

    # ─── RÉSUMÉ ───────────────────────────────────────────────────

    @staticmethod
    def summary(df: pd.DataFrame):
        """Affiche un résumé des signaux d'entrée."""
        if 'entry_signal' not in df.columns:
            print("  Pas de signaux (entry_signal absent)")
            return

        total = len(df)
        longs = (df['entry_signal'] == 1).sum()
        shorts = (df['entry_signal'] == -1).sum()
        neutral = (df['entry_signal'] == 0).sum()

        print(f"  {total} barres: {longs} LONG ({longs/total*100:.0f}%), "
              f"{shorts} SHORT ({shorts/total*100:.0f}%), "
              f"{neutral} neutre ({neutral/total*100:.0f}%)")

        if 'entry_conf' in df.columns:
            active = df[df['entry_signal'] != 0]
            if len(active) > 0:
                print(f"  Confiance moyenne: {active['entry_conf'].mean():.3f}")

        if 'entry_zone' in df.columns:
            zones = df[df['entry_signal'] != 0]['entry_zone'].value_counts()
            print(f"  Zones principales: {dict(zones.head(5))}")

            # RVOL triggers séparés
            rvol_triggers = df[df['entry_zone'].str.startswith('RVOL_', na=False)]
            if len(rvol_triggers) > 0:
                print(f"  🆕 RVOL triggers: {len(rvol_triggers)} "
                      f"({len(rvol_triggers)/max(1,longs+shorts)*100:.0f}% des signaux)")

    # ─── COLONNES DE SORTIE ───────────────────────────────────────

    COLUMNS = [
        'entry_signal',
        'entry_conf',
        'entry_zone',
        'entry_zone_dist',
        'entry_zone_score',
        'entry_n_levels',
        'entry_bias',
        # Le champ entry_zone contient 'RVOL_ABS_BUY' ou 'RVOL_ABS_SELL'
        # quand le trigger autonome fire — pas besoin de colonne séparée.
    ]
