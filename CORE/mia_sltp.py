"""
mia_sltp.py — Couche 4 : SL/TP + Money Management (3 micros)
=============================================================

Place le SL derrière un MUR prouvé, le TP avant le premier obstacle.
3 micro-contrats: TP1 (sécurité) + Trailing + Runner.

Audit murs (07/03/2026, 44 niveaux, 1349 barres):
  Tier 1 (score>0.35): GEX, SESSION HVN/LVN, EXT_EDGE, SESS_HIGH
  Tier 2 (score 0.20-0.35): CUR_VAH, VWAP±SD, PREV_VAL, SWING, OVN_HIGH
  Tier 3 (score<0.20): VWAP_D, MQ_HVL, IB_LOW, PREV_VWAP → PIÈGE

Règles SL:
  - DERRIÈRE un Tier 1 seul, OU 2+ Tier 2 en confluence (<30t)
  - JAMAIS derrière un Tier 3 seul
  - JAMAIS dans le vide (aucun mur)
  - Budget max: $75 = 50 ticks NQ / 20 ticks ES (pour 3 micros)

Règles TP:
  - TP1: premier obstacle Tier 1/2 (micro #1, sécurise le trade)
  - TP2: trailing stop sur micro #2 (capte le momentum)
  - TP3: runner = 2× risque ou 2ème obstacle (micro #3, gros gains)
  - NE PAS traverser un Tier 1 avec le TP

Emplacement: D:\\TRADING_SIERRA_CHART_AUTO\\CORE\\mia_sltp.py

Auteur : MIA Trading System
Date   : 2026-03-13
Schema : 3.6.0 — 250 colonnes
🆕 13/03: +dist_ext_long_up/dn (Tier 2, momentum support/resist)
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
from dataclasses import dataclass, field


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════

# Budget SL max par symbole (pour 3 micro-contrats)
SL_BUDGET = {
    'NQ': {'max_ticks': 50, 'max_usd': 75.0, 'tick_value': 0.50, 'n_micros': 3},
    'ES': {'max_ticks': 20, 'max_usd': 75.0, 'tick_value': 1.25, 'n_micros': 3},
}

# Buffer derrière le mur (le SL est APRÈS le niveau + buffer)
# FIX 07/03: 5→8 ticks NQ (les wicks intra-barre font 8-15t)
SL_BUFFER_TICKS = {'NQ': 8, 'ES': 4}

# SL minimum (trop près = sorti par le bruit)
# FIX 07/03: 12→30 ticks NQ (4 trades perdants avaient SL 13-17t = bruit)
SL_MIN_TICKS = {'NQ': 30, 'ES': 12}

# TP buffer avant l'obstacle (on prend profit AVANT le mur)
TP_BUFFER_TICKS = {'NQ': 4, 'ES': 2}

# Trailing stop (micro #2)
TRAILING_START_TICKS = {'NQ': 20, 'ES': 8}    # Activer après +X ticks
TRAILING_DIST_TICKS = {'NQ': 12, 'ES': 5}     # Suivre à X ticks

# Runner TP (micro #3) = multiple du risque
RUNNER_RR_RATIO = 2.0

# Confluence: 2 Tier 2 dans ce rayon = cluster acceptable
CONFLUENCE_RADIUS_TICKS = 30

# R:R minimum pour prendre le trade
MIN_RR_RATIO = 0.8


# ═════════════════════════════════════════════════════════════════════
# WALL TIERS — Classement prouvé par audit (44 niveaux, 1349 barres)
# ═════════════════════════════════════════════════════════════════════

# Tier 1: VRAIS MURS (score > 0.35, jamais ou rarement cassés)
# SL derrière = PROTÉGÉ
TIER1_WALLS = {
    # col_dmp                    name              role
    'dist_gex_nearest_up':      ('GEX_UP',         'resist'),
    'dist_gex_nearest_dn':      ('GEX_DN',         'support'),
    'dist_session_hvn_above':   ('SESS_HVN_UP',    'resist'),
    'dist_session_hvn_below':   ('SESS_HVN_DN',    'support'),
    'dist_session_lvn_above':   ('SESS_LVN_UP',    'resist'),
    'dist_session_lvn_below':   ('SESS_LVN_DN',    'support'),
    'dist_ext_edge_buy':        ('EXT_EDGE_BUY',   'support'),
    'dist_ext_edge_sell':       ('EXT_EDGE_SELL',   'resist'),
    'dist_sess_high':           ('SESS_HIGH',       'resist'),
}

# Tier 2: MURS SOLIDES (score 0.20-0.35)
# SL derrière = OK si confluence (2+ niveaux dans 30 ticks)
TIER2_WALLS = {
    'dist_cur_vah':             ('CUR_VAH',        'resist'),
    'dist_cur_vpoc':            ('CUR_VPOC',       'both'),
    'dist_cur_val':             ('CUR_VAL',        'support'),
    'dist_prev_val':            ('PREV_VAL',       'support'),
    'dist_prev_vah':            ('PREV_VAH',       'resist'),
    'dist_vwap_d_sd1u':         ('VWAP+1SD',       'resist'),
    'dist_vwap_d_sd1d':         ('VWAP-1SD',       'support'),
    'dist_vwap_d_sd2u':         ('VWAP+2SD',       'resist'),
    'dist_vwap_d_sd2d':         ('VWAP-2SD',       'support'),
    'dist_ovn_high':            ('OVN_HIGH',       'resist'),
    'dist_swing_high':          ('SWING_HIGH',     'resist'),
    'dist_swing_low':           ('SWING_LOW',      'support'),
    'dist_1d_min_ticks':        ('1D_MIN',         'support'),
    'dist_1d_max_ticks':        ('1D_MAX',         'resist'),
    'dist_open_cash':           ('OPEN_CASH',      'both'),
    'dist_comp_20d_val':        ('COMP20_VAL',     'support'),
    'dist_prev_vwap_sd1u':      ('PREV_VWAP+1SD',  'resist'),
    'dist_prev_vwap_sd1d':      ('PREV_VWAP-1SD',  'support'),
    # 🆕 3.6.0: Extension Lines LONG BAR (momentum support/resist, fix 13/03)
    'dist_ext_long_up':         ('EXT_LONG_UP',    'resist'),
    'dist_ext_long_dn':         ('EXT_LONG_DN',    'support'),
}

# Tier 3: MURS PAPIER — PIÈGE (rebondent souvent mais pénétration 40-80 pts)
# SL derrière = DANGER. TP avant = optionnel.
TIER3_WALLS = {
    'dist_vwap_d':              ('VWAP_D',         'both'),
    'dist_prev_vpoc':           ('PREV_VPOC',      'both'),
    'dist_prev_vwap':           ('PREV_VWAP',      'both'),
    'dist_mq_hvl':              ('MQ_HVL',         'both'),
    'dist_ib_low':              ('IB_LOW',         'support'),
    'dist_ib_high':             ('IB_HIGH',        'resist'),
    'dist_ovn_low':             ('OVN_LOW',        'support'),
    'dist_mq_put_0dte':         ('MQ_PUT_0DTE',    'support'),
    'dist_mq_call_0dte':        ('MQ_CALL_0DTE',   'resist'),
    'dist_sess_low':            ('SESS_LOW',       'support'),
}


# ═════════════════════════════════════════════════════════════════════
# STRUCTURES
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Wall:
    """Un mur détecté."""
    name: str
    col: str
    dist_ticks: float         # Distance signée (positif = au-dessus)
    abs_dist: float           # |distance|
    tier: int                 # 1, 2, 3
    role: str                 # support, resist, both


@dataclass
class SLTPResult:
    """Résultat du calcul SL/TP pour une barre."""
    valid: bool = False
    direction: int = 0        # +1=LONG, -1=SHORT

    # SL
    sl_ticks: float = 0.0     # Distance SL en ticks
    sl_wall: str = ""         # Nom du mur protecteur
    sl_wall_tier: int = 0     # Tier du mur (1, 2, 3)
    sl_n_walls: int = 0       # Nombre de murs derrière le SL
    sl_reason: str = ""       # Explication

    # TP1 (micro #1 — sécurité, 1:1)
    tp1_ticks: float = 0.0
    tp1_wall: str = ""
    tp1_reason: str = ""

    # TP2 (micro #2 — trailing)
    trailing_start: float = 0.0
    trailing_dist: float = 0.0

    # TP3 (micro #3 — runner)
    tp3_ticks: float = 0.0
    tp3_wall: str = ""
    tp3_reason: str = ""

    # Money
    rr_ratio: float = 0.0     # TP1/SL
    sl_usd: float = 0.0       # Perte max en $
    reject_reason: str = ""


# ═════════════════════════════════════════════════════════════════════
# MOTEUR SL/TP
# ═════════════════════════════════════════════════════════════════════

class SLTPEngine:
    """
    Calcule SL/TP adaptatif basé sur les murs prouvés.

    Usage:
        engine = SLTPEngine(symbol="NQ")
        df = engine.compute(df_with_entry_signals)
    """

    def __init__(self, symbol: str = "NQ"):
        self.symbol = symbol
        cfg = SL_BUDGET.get(symbol, SL_BUDGET['NQ'])
        self.max_sl_ticks = cfg['max_ticks']
        self.tick_value = cfg['tick_value']
        self.n_micros = cfg['n_micros']
        self.max_sl_usd = cfg['max_usd']
        self.sl_buffer = SL_BUFFER_TICKS.get(symbol, 5)
        self.sl_min = SL_MIN_TICKS.get(symbol, 12)
        self.tp_buffer = TP_BUFFER_TICKS.get(symbol, 4)
        self.trail_start = TRAILING_START_TICKS.get(symbol, 20)
        self.trail_dist = TRAILING_DIST_TICKS.get(symbol, 12)

    # ─── MAIN ──────────────────────────────────────────────────────

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ajoute les colonnes SL/TP à un DataFrame avec entry_signal.

        Colonnes ajoutées:
            sltp_valid:       True si le trade est prenable
            sltp_sl_ticks:    Distance SL en ticks
            sltp_sl_wall:     Nom du mur protecteur
            sltp_sl_tier:     Tier du mur (1 ou 2)
            sltp_tp1_ticks:   TP micro #1 (sécurité)
            sltp_tp3_ticks:   TP micro #3 (runner)
            sltp_rr:          R:R ratio (TP1/SL)
            sltp_sl_usd:      Perte max en $
            sltp_reject:      Raison du rejet (vide si valid)
        """
        df = df.copy()
        results = []

        for i in range(len(df)):
            row = df.iloc[i]
            sig = int(row.get('entry_signal', 0))

            if sig == 0:
                results.append(SLTPResult())
                continue

            res = self._evaluate(row, sig)
            results.append(res)

        df['sltp_valid'] = [r.valid for r in results]
        df['sltp_sl_ticks'] = [r.sl_ticks for r in results]
        df['sltp_sl_wall'] = [r.sl_wall for r in results]
        df['sltp_sl_tier'] = [r.sl_wall_tier for r in results]
        df['sltp_sl_n_walls'] = [r.sl_n_walls for r in results]
        df['sltp_tp1_ticks'] = [r.tp1_ticks for r in results]
        df['sltp_tp1_wall'] = [r.tp1_wall for r in results]
        df['sltp_tp3_ticks'] = [r.tp3_ticks for r in results]
        df['sltp_rr'] = [r.rr_ratio for r in results]
        df['sltp_sl_usd'] = [r.sl_usd for r in results]
        df['sltp_reject'] = [r.reject_reason for r in results]

        return df

    # ─── API PUBLIQUE LIVE (v2 22/04 review code-reviewer R5) ─────

    def evaluate_single(self, row, direction: int) -> SLTPResult:
        """API publique stable pour calcul SL/TP sur une barre unique (mode live).

        Wrapper autour de _evaluate() pour usage externe (paper_trader, bot live).
        Accepte dict ou pd.Series, retourne SLTPResult.
        """
        if isinstance(row, dict):
            row = pd.Series(row)
        return self._evaluate(row, direction)

    # ─── ÉVALUATION PAR BARRE (interne) ────────────────────────────

    def _evaluate(self, row: pd.Series, direction: int) -> SLTPResult:
        """Calcule SL/TP pour une barre avec signal."""

        res = SLTPResult(direction=direction)

        # ═══ ÉTAPE 1: TROUVER LE MUR POUR LE SL ═══
        sl_ticks, sl_wall, sl_tier, sl_n_walls, sl_reason = \
            self._find_sl_wall(row, direction)

        if sl_ticks == 0:
            res.reject_reason = sl_reason
            return res

        # Vérifier le budget
        sl_usd = sl_ticks * self.tick_value * self.n_micros
        if sl_usd > self.max_sl_usd:
            res.reject_reason = f"SL ${sl_usd:.0f} > budget ${self.max_sl_usd:.0f}"
            return res

        res.sl_ticks = sl_ticks
        res.sl_wall = sl_wall
        res.sl_wall_tier = sl_tier
        res.sl_n_walls = sl_n_walls
        res.sl_reason = sl_reason
        res.sl_usd = sl_usd

        # ═══ ÉTAPE 2: TROUVER LE TP1 (premier obstacle) ═══
        tp1_ticks, tp1_wall, tp1_reason = \
            self._find_tp_obstacle(row, direction, sl_ticks)

        if tp1_ticks == 0:
            # Pas d'obstacle → TP fixe = 1:1
            tp1_ticks = sl_ticks
            tp1_wall = ""
            tp1_reason = "TP1 fixe 1:1 (pas d'obstacle)"

        res.tp1_ticks = tp1_ticks
        res.tp1_wall = tp1_wall
        res.tp1_reason = tp1_reason

        # ═══ ÉTAPE 3: R:R CHECK ═══
        rr = tp1_ticks / sl_ticks if sl_ticks > 0 else 0
        if rr < MIN_RR_RATIO:
            res.reject_reason = f"R:R {rr:.2f} < {MIN_RR_RATIO} ({tp1_wall} trop proche)"
            return res

        res.rr_ratio = rr

        # ═══ ÉTAPE 4: TRAILING (micro #2) ═══
        res.trailing_start = self.trail_start
        res.trailing_dist = self.trail_dist

        # ═══ ÉTAPE 5: RUNNER TP3 (micro #3) ═══
        tp3_target = sl_ticks * RUNNER_RR_RATIO

        # Chercher le 2ème obstacle pour le runner
        obstacles = self._scan_obstacles(row, direction)
        # Filtrer: au-delà du TP1
        far_obstacles = [o for o in obstacles if o.abs_dist > tp1_ticks + 5]

        if far_obstacles:
            # Runner TP = 2ème obstacle ou 2:1, le plus proche
            second_wall = far_obstacles[0]
            runner_at_wall = second_wall.abs_dist - self.tp_buffer
            tp3_ticks = min(runner_at_wall, tp3_target)
            tp3_wall = second_wall.name
            tp3_reason = f"Runner avant {second_wall.name}"
        else:
            tp3_ticks = tp3_target
            tp3_wall = ""
            tp3_reason = f"Runner {RUNNER_RR_RATIO:.0f}:1"

        # Runner doit être > TP1
        if tp3_ticks <= tp1_ticks:
            tp3_ticks = tp1_ticks * 1.5  # Au moins 1.5× TP1

        res.tp3_ticks = tp3_ticks
        res.tp3_wall = tp3_wall
        res.tp3_reason = tp3_reason

        res.valid = True
        return res

    # ─── FIND SL WALL ──────────────────────────────────────────────

    def _find_sl_wall(self, row: pd.Series, direction: int
                      ) -> Tuple[float, str, int, int, str]:
        """
        Trouve le meilleur mur pour placer le SL.

        Logique:
        1. Scanner Tier 1 d'abord → SL derrière le plus proche
        2. Si rien en Tier 1 → chercher cluster Tier 2 (2+ dans 30t)
        3. Si rien → REJET (pas de trade sans protection)

        Returns: (sl_ticks, wall_name, tier, n_walls, reason)
        """

        # Scanner tous les murs DERRIÈRE le prix
        # LONG → murs EN-DESSOUS (dist < 0, ou support avec dist positif petit)
        # SHORT → murs AU-DESSUS (dist > 0, ou resist avec dist négatif petit)

        behind_t1 = []
        behind_t2 = []

        # Tier 1
        for col, (name, role) in TIER1_WALLS.items():
            wall = self._check_wall_behind(row, col, name, role, direction, tier=1)
            if wall:
                behind_t1.append(wall)

        # Tier 2
        for col, (name, role) in TIER2_WALLS.items():
            wall = self._check_wall_behind(row, col, name, role, direction, tier=2)
            if wall:
                behind_t2.append(wall)

        # Trier par distance (le plus proche = SL le plus serré)
        behind_t1.sort(key=lambda w: w.abs_dist)
        behind_t2.sort(key=lambda w: w.abs_dist)

        # ─── OPTION A: Tier 1 seul ───
        for wall in behind_t1:
            sl_ticks = wall.abs_dist + self.sl_buffer
            if self.sl_min <= sl_ticks <= self.max_sl_ticks:
                # Compter combien de murs sont entre le prix et le SL
                n_walls = sum(1 for w in behind_t1 + behind_t2
                              if w.abs_dist <= sl_ticks)
                return sl_ticks, wall.name, 1, n_walls, \
                    f"SL derrière {wall.name} (T1, {sl_ticks:.0f}t)"

        # ─── OPTION B: Cluster Tier 2 (2+ dans 30 ticks) ───
        if len(behind_t2) >= 2:
            # Chercher un cluster (2+ murs proches l'un de l'autre)
            for i, w1 in enumerate(behind_t2):
                cluster = [w1]
                for w2 in behind_t2[i+1:]:
                    if abs(w2.abs_dist - w1.abs_dist) <= CONFLUENCE_RADIUS_TICKS:
                        cluster.append(w2)

                if len(cluster) >= 2:
                    # SL derrière le mur le plus loin du cluster
                    farthest = max(cluster, key=lambda w: w.abs_dist)
                    sl_ticks = farthest.abs_dist + self.sl_buffer

                    if self.sl_min <= sl_ticks <= self.max_sl_ticks:
                        names = "+".join(w.name for w in cluster[:3])
                        n_walls = len(cluster)
                        return sl_ticks, names, 2, n_walls, \
                            f"SL derrière cluster T2 [{names}] ({sl_ticks:.0f}t)"

        # ─── OPTION C: Tier 1 trop loin mais Tier 2 seul acceptable si T1 pas loin ───
        # Si un T2 est à portée ET un T1 existe (même loin), on accepte
        if behind_t2 and behind_t1:
            best_t2 = behind_t2[0]
            sl_ticks = best_t2.abs_dist + self.sl_buffer
            if self.sl_min <= sl_ticks <= self.max_sl_ticks:
                return sl_ticks, best_t2.name, 2, 1, \
                    f"SL derrière {best_t2.name} (T2 + T1 backup)"

        # ─── REJET ───
        n_t1 = len(behind_t1)
        n_t2 = len(behind_t2)
        if n_t1 == 0 and n_t2 == 0:
            return 0, "", 0, 0, "Aucun mur T1/T2 derrière le prix"
        elif behind_t1 and behind_t1[0].abs_dist + self.sl_buffer > self.max_sl_ticks:
            return 0, "", 0, 0, \
                f"T1 {behind_t1[0].name} trop loin ({behind_t1[0].abs_dist:.0f}t > {self.max_sl_ticks}t)"
        elif behind_t2 and len(behind_t2) < 2:
            return 0, "", 0, 0, \
                f"T2 {behind_t2[0].name} seul (pas de confluence)"
        else:
            return 0, "", 0, 0, f"SL hors limites ({self.sl_min}-{self.max_sl_ticks}t)"

    # ─── FIND TP OBSTACLE ──────────────────────────────────────────

    def _find_tp_obstacle(self, row: pd.Series, direction: int,
                          sl_ticks: float) -> Tuple[float, str, str]:
        """
        Trouve le premier obstacle Tier 1 ou Tier 2 dans la direction du trade.
        Le TP est placé AVANT cet obstacle.

        Returns: (tp_ticks, wall_name, reason)
        """
        obstacles = self._scan_obstacles(row, direction)

        if not obstacles:
            return 0, "", "Aucun obstacle"

        first = obstacles[0]

        # TP = avant l'obstacle
        tp_ticks = first.abs_dist - self.tp_buffer

        if tp_ticks < sl_ticks * MIN_RR_RATIO:
            # Obstacle trop proche → R:R insuffisant
            # Chercher le suivant
            if len(obstacles) > 1:
                second = obstacles[1]
                tp_ticks = second.abs_dist - self.tp_buffer
                return tp_ticks, second.name, \
                    f"TP avant {second.name} (T{second.tier}, {first.name} trop proche)"
            return tp_ticks, first.name, f"TP avant {first.name} (R:R faible)"

        return tp_ticks, first.name, f"TP avant {first.name} (T{first.tier})"

    # ─── SCAN OBSTACLES ────────────────────────────────────────────

    def _scan_obstacles(self, row: pd.Series, direction: int) -> List[Wall]:
        """
        Scanne tous les murs Tier 1 et Tier 2 DEVANT le prix (dans la direction du trade).
        LONG → obstacles AU-DESSUS | SHORT → obstacles EN-DESSOUS
        """
        obstacles = []

        for walls_dict, tier in [(TIER1_WALLS, 1), (TIER2_WALLS, 2)]:
            for col, (name, role) in walls_dict.items():
                wall = self._check_wall_ahead(row, col, name, role, direction, tier)
                if wall:
                    obstacles.append(wall)

        obstacles.sort(key=lambda w: w.abs_dist)
        return obstacles

    # ─── HELPERS ───────────────────────────────────────────────────

    def _check_wall_behind(self, row, col, name, role, direction, tier) -> Optional[Wall]:
        """Vérifie si un mur est DERRIÈRE le prix (côté SL)."""
        if col not in row.index:
            return None
        dist = row[col]
        if pd.isna(dist):
            return None

        abs_d = abs(dist)
        if abs_d > self.max_sl_ticks + 10:  # Marge
            return None

        # LONG → SL en bas → chercher murs EN-DESSOUS (dist négatif ou support)
        # SHORT → SL en haut → chercher murs AU-DESSUS (dist positif ou resist)
        if direction == 1:  # LONG
            # Mur en-dessous: dist < 0 (niveau sous le prix)
            # Pour support: toujours OK si dist < 0
            # Pour resist: pas pertinent comme SL d'un LONG
            # Pour both: OK si dist < 0
            if role == 'resist':
                return None  # Résistance ne protège pas un LONG en bas
            if dist > 0:
                return None  # Le mur est au-dessus, pas derrière pour un LONG
        else:  # SHORT
            if role == 'support':
                return None
            if dist < 0:
                return None  # Le mur est en-dessous, pas derrière pour un SHORT

        return Wall(name=name, col=col, dist_ticks=dist,
                    abs_dist=abs_d, tier=tier, role=role)

    def _check_wall_ahead(self, row, col, name, role, direction, tier) -> Optional[Wall]:
        """Vérifie si un mur est DEVANT le prix (côté TP / obstacle)."""
        if col not in row.index:
            return None
        dist = row[col]
        if pd.isna(dist):
            return None

        abs_d = abs(dist)
        if abs_d < 3:  # Trop proche = on est déjà dessus
            return None
        if abs_d > 200:  # Trop loin = pas pertinent
            return None

        # LONG → obstacles AU-DESSUS (dist > 0)
        # SHORT → obstacles EN-DESSOUS (dist < 0)
        if direction == 1:  # LONG
            if role == 'support':
                return None  # Support ne bloque pas un LONG qui monte
            if dist < 0:
                return None
        else:  # SHORT
            if role == 'resist':
                return None
            if dist > 0:
                return None

        return Wall(name=name, col=col, dist_ticks=dist,
                    abs_dist=abs_d, tier=tier, role=role)

    # ─── RÉSUMÉ ───────────────────────────────────────────────────

    @staticmethod
    def summary(df: pd.DataFrame):
        """Affiche un résumé des SL/TP."""
        if 'sltp_valid' not in df.columns:
            print("  Pas de données SLTP")
            return

        has_signal = df['entry_signal'] != 0 if 'entry_signal' in df.columns \
            else pd.Series(False, index=df.index)
        valid = df['sltp_valid'] == True
        rejected = has_signal & ~valid

        n_sig = has_signal.sum()
        n_valid = valid.sum()
        n_reject = rejected.sum()

        print(f"  {n_sig} signaux entrée → {n_valid} validés SLTP "
              f"({n_reject} rejetés)")

        if n_valid > 0:
            v = df[valid]
            print(f"  SL moyen: {v['sltp_sl_ticks'].mean():.0f}t "
                  f"(${v['sltp_sl_usd'].mean():.0f})")
            print(f"  TP1 moyen: {v['sltp_tp1_ticks'].mean():.0f}t")
            print(f"  TP3 moyen: {v['sltp_tp3_ticks'].mean():.0f}t")
            print(f"  R:R moyen: {v['sltp_rr'].mean():.2f}")
            print(f"  Murs SL: {dict(v['sltp_sl_wall'].value_counts().head(5))}")

        if n_reject > 0:
            rej = df[rejected]
            print(f"  Rejets: {dict(rej['sltp_reject'].value_counts().head(5))}")

    # ─── COLONNES ─────────────────────────────────────────────────

    COLUMNS = [
        'sltp_valid', 'sltp_sl_ticks', 'sltp_sl_wall', 'sltp_sl_tier',
        'sltp_sl_n_walls', 'sltp_tp1_ticks', 'sltp_tp1_wall',
        'sltp_tp3_ticks', 'sltp_rr', 'sltp_sl_usd', 'sltp_reject',
    ]
