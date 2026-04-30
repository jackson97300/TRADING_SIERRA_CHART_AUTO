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

import math
import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
from dataclasses import dataclass, field


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════

# Budget SL max par symbole (pour 3 micro-contrats)
# 🆕 FIX 24/04 SLTP P2 (audit market-analyst) : elargir bornes SL pour eviter
#   les 5 rejets `sltp_out_of_range` / jour. Bornes initiales [30-50t] NQ trop
#   serrees en trend. Nouveau : [20-80t] NQ / [10-40t] ES.
#   Justification :
#     - ATR-based recommande par reviewer mais ATR actuel = 420-450 ticks (probable
#       ATR-daily, pas per-bar). Refactor ATR-14-min reporte (backlog) → on
#       elargit les bornes fixes avec marges empiriques.
#     - NQ swing trades 1-min peuvent avoir SL 40-70t en sessions volatiles.
#     - Cap max 80t coherent avec MAX_TP_WALL_DISTANCE NQ (garde-fou budget).
SL_BUDGET = {
    'NQ': {'max_ticks': 80, 'max_usd': 75.0, 'tick_value': 0.50, 'n_micros': 3},  # 50→80 (24/04)
    'ES': {'max_ticks': 40, 'max_usd': 75.0, 'tick_value': 1.25, 'n_micros': 3},  # 20→40 (24/04)
}

# Buffer derrière le mur (le SL est APRÈS le niveau + buffer)
# FIX 07/03: 5→8 ticks NQ (les wicks intra-barre font 8-15t)
SL_BUFFER_TICKS = {'NQ': 8, 'ES': 4}

# Buffer ETENDU quand on accepte un T2 seul sans T1 backup (anti stop-hunt).
# 🆕 FIX 24/04 SLTP P3 (audit market-analyst) : +5t extra pour securite.
SL_BUFFER_EXTENDED_TICKS = {'NQ': 13, 'ES': 8}  # NQ 8+5=13 / ES 4+4=8

# SL minimum (trop près = sorti par le bruit)
# FIX 07/03: 12→30 ticks NQ (4 trades perdants avaient SL 13-17t = bruit)
# 🆕 FIX 24/04 SLTP P2 : NQ 30→20 (les barres NQ 1-min range typique 12-20t,
#   30t trop serre sur conditions calmes. Garde 20 comme plancher anti-bruit).
SL_MIN_TICKS = {'NQ': 20, 'ES': 10}  # NQ 30→20 / ES 12→10 (24/04)

# TP buffer avant l'obstacle (on prend profit AVANT le mur)
TP_BUFFER_TICKS = {'NQ': 4, 'ES': 2}

# Trailing stop (micro #2)
TRAILING_START_TICKS = {'NQ': 20, 'ES': 8}    # Activer après +X ticks
TRAILING_DIST_TICKS = {'NQ': 12, 'ES': 5}     # Suivre à X ticks

# Runner TP (micro #3) = multiple du risque
RUNNER_RR_RATIO = 2.0

# Confluence: 2 Tier 2 dans ce rayon = cluster acceptable
CONFLUENCE_RADIUS_TICKS = 30

# R:R minimum pour prendre le trade (validation finale _evaluate)
MIN_RR_RATIO = 0.8

# R:R minimum pour SELECTION d'un mur comme TP dans _find_tp_obstacle
# 🆕 FIX 24/04/2026 (audit market-analyst) : le code prenait le PREMIER obstacle
#   sans verifier que R:R etait acceptable. Cas empirique NQ 23/04 :
#     SL=49t, TP=55t (GEX_UP premier mur), R:R=1.12 → accepte par MIN_RR_RATIO 0.8
#     → STEP 8 payoff rejette (EV=-$3.3 avec WR 0.45 prior).
#   Fix : scanner TOUS les obstacles, prendre le premier avec R:R >= 1.5.
#   Si aucun n'atteint 1.5 → fallback TP_STANDARD = SL × 2.0 (R:R 2.0 garanti).
#   Seuil 1.5 choisi entre MIN_RR_RATIO (0.8 trop permissif) et
#   DEFAULT_TP_RR_FALLBACK (2.0 qui est le fallback). 1.5 = compromis raisonnable.
#
# TODO V2CLEAN : migrer cette constante (+ MIN_RR_RATIO + DEFAULT_TP_RR_FALLBACK
#   + MAX_TP_WALL_DISTANCE + MAX_TP_TICKS_ABSOLUTE) dans V2CLEAN/config.py quand
#   le port V2CLEAN sera operationnel. Reference : feedback_config_centralise.md
#   (17/04) "Toute config dans V2CLEAN/config.py. Jamais de constantes hardcodees
#   ni de *_params.py locaux. V1 leçon : TICK_SIZE duplique 5x."
#
# TODO post N>=100 trades : revisiter ce seuil via meta-labeler ML qui apprendra
#   la fonction "R:R optimal selon regime marche" au lieu d'un seuil constant.
#   Reference : feedback_lightgbm_no_composite_indicators.md.
MIN_RR_SELECTION = 1.5

# ═════════════════════════════════════════════════════════════════════
# TP STANDARD — fallback quand mur absent OU trop loin (V1 adaptive_sltp_calculator)
# Jackson validation 24/04/2026 — evite les TP absurdes genre R:R 13.3
# ═════════════════════════════════════════════════════════════════════
# Cible R:R du TP standard (quand pas d'obstacle exploitable)
DEFAULT_TP_RR_FALLBACK = 2.0  # TP = SL × 2 = R:R 2.0

# Distance max d'un mur pour le considerer comme TP. Au-dela, TP standard applique.
# Si un mur legitime existe en dessous de cette distance, on l'utilise SANS cap
# (car il donne un R:R naturel pris du marche, meme si > MAX_TP_TICKS_ABSOLUTE).
MAX_TP_WALL_DISTANCE = {
    'ES': 80,   # 20pts max distance mur. Mur entre 30-80t donne R:R eleve prenable.
    'NQ': 250,  # 62.5pts max distance mur. Au-dela = mouvement improbable intraday.
}

# Cap absolu du TP (V47) — applique UNIQUEMENT sur fallback TP_STANDARD (pas murs).
# Evite qu'un SL large (ex 40t NQ) avec fallback 2R donne un TP 80t ambitieux.
# Les murs legitimes < MAX_TP_WALL_DISTANCE ne sont PAS cappes (R:R nature marche).
MAX_TP_TICKS_ABSOLUTE = {
    'ES': 30,   # 7.5pts max pour fallback
    'NQ': 80,   # 20pts max pour fallback
}


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
    # 🆕 30/04/2026 (Jackson "ON DOIS LISTER LES NIVEAU MENTHORQ COMME MUR")
    # Bug observé : ES SHORT @ 7206.50, mur Call Resistance + Call Resistance 0DTE +
    # Gamma Wall 0DTE empilés @ 7199.46. SLTPEngine ne voyait aucun de ces niveaux
    # (rollback 28/04 a retiré TIER3 du scan TP). TP placé @ 7199.25 = 1 tick DERRIÈRE
    # le mur empilé → besoin de casser le mur pour TP. Pattern recurrent.
    # Niveaux 0DTE = expiration jour J = très structurants empiriquement, role='both'
    # car fonctionnent dans les 2 sens (au-dessus = résistance, en-dessous = support
    # inversé que le prix doit casser). Reference : memoire reference_timezone_convention.md
    # MQ levels updated daily via API SC.
    'dist_mq_call_0dte':        ('MQ_CALL_0DTE',   'both'),
    'dist_mq_put_0dte':         ('MQ_PUT_0DTE',    'both'),
    'dist_mq_hvl_0dte':         ('MQ_HVL_0DTE',    'both'),
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
    # 🆕 30/04/2026 — MenthorQ classiques (non-0DTE) : robustes mais moins
    # immédiats que 0DTE → TIER2. role='both' (cf justification TIER1).
    'dist_mq_call':             ('MQ_CALL',        'both'),
    'dist_mq_put':              ('MQ_PUT',         'both'),
    'dist_mq_hvl':              ('MQ_HVL',         'both'),
    # 🆕 30/04/2026 v3 (Jackson "OPEN US VWAP NIVEAU DE LA VEILLE DOIVENT Y ETRE,
    # ON DOIS RATISER LARGE"). Screen Bot 2 ES SHORT @ 7174 → SD-1 W + Open US
    # (T2) conjointement bloque TP.
    # R1 code-reviewer 30/04 soir BLOQUANT : pas de promotion T3→T2 (pattern
    # PRIO V1 incident `feedback_pattern11_repetition_avoided.md`). VWAP_D et
    # PREV_VWAP avaient commentaire explicite "MURS PAPIER PIEGE" → on ne
    # contredit pas une analyse historique sur n=1 screen.
    # GARDE uniquement les ajouts vraiment nouveaux (pas de contradiction) :
    'dist_vwap_w':              ('VWAP_W',         'both'),  # nouveau (Weekly VWAP nu)
    'dist_open_830':            ('OPEN_830',       'both'),  # nouveau (pre-market open 09:30 ET)
}

# Tier 3: MURS PAPIER — PIÈGE (rebondent souvent mais pénétration 40-80 pts)
# SL derrière = DANGER. TP avant = optionnel.
# 🆕 30/04/2026 : MQ_HVL, MQ_PUT_0DTE, MQ_CALL_0DTE PROMUS en TIER1 (cf TIER1_WALLS).
# Anti-doublon : un meme dist_* ne peut etre que dans UN tier (sinon double-scan).
TIER3_WALLS = {
    'dist_vwap_d':              ('VWAP_D',         'both'),
    'dist_prev_vpoc':           ('PREV_VPOC',      'both'),
    'dist_prev_vwap':           ('PREV_VWAP',      'both'),
    'dist_ib_low':              ('IB_LOW',         'support'),
    'dist_ib_high':             ('IB_HIGH',        'resist'),
    'dist_ovn_low':             ('OVN_LOW',        'support'),
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

    # CAS 4 anti-TP-derriere-mur (30/04/2026) — observability prod
    # T1 = MUTATION active (capote tp1_ticks). T2 = observability-only 5j.
    cas4_triggered: bool = False         # True si T1 capot active (mutation)
    cas4_blocked_wall: str = ""          # Nom du mur T1 qui a force le capot
    cas4_blocked_wall_dist: float = 0.0  # Distance exacte du mur (avant tp_buffer)
    cas4_blocked_wall_tier: int = 0      # Tier du mur capote (1 = mutation)
    cas4_tp_standard_pre: float = 0.0    # Valeur tp1_ticks AVANT capot
    cas4_source_pre: str = ""            # tp1_wall AVANT capot
    # v3 split observability-only T2 (R2 code-reviewer 30/04) :
    cas4_observed_tier2: bool = False    # True si capot T2 AURAIT trigger (sans mutation)
    cas4_observed_wall_t2: str = ""      # Nom mur T2 qui aurait capote
    cas4_observed_wall_t2_dist: float = 0.0  # Dist exacte
    cas4_observed_tp_devant: float = 0.0     # tp_ticks calcule HYPOTHETIQUE


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

        # ─── FALLBACK TP STANDARD (V1 adaptive_sltp_calculator — Jackson 24/04) ───
        # 3 cas où on utilise le TP standard (fallback) au lieu du mur observé :
        #   1) Aucun obstacle trouvé (tp1_ticks == 0) → TP = SL × 2.0 (au lieu de 1:1)
        #   2) Mur trop loin (> MAX_TP_WALL_DISTANCE[symbol]) → TP = SL × 2.0
        #      Evite les TP absurdes genre R:R 13.3 (exemple Jackson ES SL=15 mur=200)
        #   3) Cap absolu MAX_TP_TICKS_ABSOLUTE (V47 — evite TP > 30t ES / 80t NQ)
        max_tp_dist = MAX_TP_WALL_DISTANCE.get(self.symbol, 200)
        max_tp_abs = MAX_TP_TICKS_ABSOLUTE.get(self.symbol, 100)

        if tp1_ticks == 0:
            # CAS 1 : aucun obstacle trouve
            tp1_ticks = sl_ticks * DEFAULT_TP_RR_FALLBACK
            tp1_wall = "TP_STANDARD_NO_WALL"
            tp1_reason = (
                f"TP standard {DEFAULT_TP_RR_FALLBACK:.1f}R "
                f"({tp1_ticks:.0f}t = SL × {DEFAULT_TP_RR_FALLBACK}, aucun obstacle)"
            )
        elif tp1_ticks > max_tp_dist:
            # CAS 2 : mur trop loin → TP standard au lieu du mur
            far_wall_name = tp1_wall
            tp1_ticks = sl_ticks * DEFAULT_TP_RR_FALLBACK
            tp1_wall = "TP_STANDARD_WALL_FAR"
            tp1_reason = (
                f"TP standard {DEFAULT_TP_RR_FALLBACK:.1f}R "
                f"(mur {far_wall_name} trop loin > {max_tp_dist}t, fallback SL × {DEFAULT_TP_RR_FALLBACK})"
            )

        # CAS 3 : cap absolu UNIQUEMENT pour fallback TP_STANDARD
        # (corrigé 24/04 post-audit : un mur légitime à 75t ES avec SL 12t donne
        # R:R 5.1 — on le conserve. Le cap ne concerne que les fallbacks x2R
        # pour éviter TP ambitieux après un SL large.)
        if tp1_wall.startswith("TP_STANDARD") and tp1_ticks > max_tp_abs:
            tp1_ticks = max_tp_abs
            tp1_reason += f" [cap {max_tp_abs}t V47]"

        # ─── CAS 4 v3 (30/04/2026 soir) : T1 MUTATION + T2 OBSERVABILITY-ONLY ──
        # Historique :
        #   v1 (matin) : capote uniquement sur fallback TP_STANDARD passant
        #     derriere un mur scanne.
        #   v2 (apres-midi) : etend a TOUT TP, capote uniquement sur T1.
        #   v3 (soir, Jackson "RATISER LARGE") : etend a T1+T2.
        #   v3 split (R2 code-reviewer 30/04 soir) : compromis backtest
        #     - T1 garde mutation (validee v2 sur cas screen Bot 1)
        #     - T2 OBSERVABILITY-ONLY 5 jours : log les capots HYPOTHETIQUES
        #       sans muter tp1_ticks (cas4_observed_tier2=True). Si fire rate
        #       <15% et coherent sur 5j → activer mutation T2 v4.
        # Justification compromis : R2 BLOQUANT codereviewer = "passer de
        # T1-only a T1+T2 ajoute ~24 niveaux scannes. Risque mecanique : capot
        # proche → R:R<0.8 → reject massif. Aucun backtest sur historique propre".
        # → Compromis : monitorer 5j avant mutation T2.
        obstacles_in_path = self._scan_obstacles(row, direction)
        walls_in_path = [o for o in obstacles_in_path if o.tier in (1, 2)]
        if walls_in_path:
            first_wall = walls_in_path[0]  # deja trie par dist (asc)
            already_at_first_wall = (
                first_wall.name == tp1_wall
                or tp1_wall == f"TP_DEVANT_{first_wall.name}"
            )
            if not already_at_first_wall and first_wall.abs_dist < tp1_ticks:
                tp_devant_mur = math.floor(
                    first_wall.abs_dist - self.tp_buffer
                )
                if tp_devant_mur > 0:
                    if first_wall.tier == 1:
                        # T1 : MUTATION (validee v2)
                        tp_pre_capot = tp1_ticks
                        wall_pre_capot = tp1_wall

                        tp1_ticks = float(tp_devant_mur)
                        tp1_wall = f"TP_DEVANT_{first_wall.name}"
                        tp1_reason = (
                            f"TP devant {first_wall.name} (T1) a {tp_devant_mur}t — "
                            f"TP precedent ({wall_pre_capot} a {tp_pre_capot:.0f}t) "
                            f"aurait traverse le mur T1 a {first_wall.abs_dist:.1f}t"
                        )
                        res.cas4_triggered = True
                        res.cas4_blocked_wall = first_wall.name
                        res.cas4_blocked_wall_dist = float(first_wall.abs_dist)
                        res.cas4_tp_standard_pre = float(tp_pre_capot)
                        res.cas4_source_pre = wall_pre_capot
                        res.cas4_blocked_wall_tier = 1
                    else:
                        # T2 : OBSERVABILITY-ONLY (5j backlog R2 code-reviewer)
                        # Log le capot HYPOTHETIQUE sans muter tp1_ticks. Permet
                        # de mesurer fire rate et coherence sur 5 jours avant
                        # d'activer mutation T2 en v4.
                        res.cas4_observed_tier2 = True
                        res.cas4_observed_wall_t2 = first_wall.name
                        res.cas4_observed_wall_t2_dist = float(first_wall.abs_dist)
                        res.cas4_observed_tp_devant = float(tp_devant_mur)
                        # Pas de mutation tp1_ticks/tp1_wall ici (observability)

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

        # ─── OPTION D: Tier 2 seul sans T1 backup avec buffer ETENDU ───
        # 🆕 FIX 24/04 SLTP P3 (audit market-analyst) : accept T2 seul mais avec
        #   buffer +5t (13t total NQ / 8t total ES) pour mitiger stop-hunt.
        #   Avant : 10 rejets `sltp_no_wall` / jour NQ (T2 EXT_LONG_DN seul).
        #   Apres : SL derriere T2 unique, placement plus large = plus d'espace
        #   au prix pour bouger sans hit le SL sur un spike ponctuel.
        if behind_t2 and not behind_t1:
            best_t2 = behind_t2[0]
            sl_ticks_extended = best_t2.abs_dist + SL_BUFFER_EXTENDED_TICKS.get(self.symbol, self.sl_buffer + 5)
            if self.sl_min <= sl_ticks_extended <= self.max_sl_ticks:
                return sl_ticks_extended, best_t2.name, 2, 1, \
                    f"SL derrière {best_t2.name} (T2 seul, buffer ETENDU anti stop-hunt)"

        # ─── REJET ───
        n_t1 = len(behind_t1)
        n_t2 = len(behind_t2)
        if n_t1 == 0 and n_t2 == 0:
            return 0, "", 0, 0, "Aucun mur T1/T2 derrière le prix"
        elif behind_t1 and behind_t1[0].abs_dist + self.sl_buffer > self.max_sl_ticks:
            return 0, "", 0, 0, \
                f"T1 {behind_t1[0].name} trop loin ({behind_t1[0].abs_dist:.0f}t > {self.max_sl_ticks}t)"
        elif behind_t2 and len(behind_t2) < 2:
            # Cas rare post-fix P3 : T2 seul mais SL extended hors bornes
            return 0, "", 0, 0, \
                f"T2 {behind_t2[0].name} seul + SL extended hors bornes ({self.sl_min}-{self.max_sl_ticks}t)"
        else:
            return 0, "", 0, 0, f"SL hors limites ({self.sl_min}-{self.max_sl_ticks}t)"

    # ─── FIND TP OBSTACLE ──────────────────────────────────────────

    def _find_tp_obstacle(self, row: pd.Series, direction: int,
                          sl_ticks: float) -> Tuple[float, str, str]:
        """
        Trouve le premier obstacle Tier 1 ou Tier 2 qui donne un R:R acceptable
        dans la direction du trade. Le TP est placé AVANT cet obstacle.

        🆕 FIX 24/04/2026 (audit market-analyst) :
          AVANT : prenait le PREMIER obstacle sans verifier R:R. Bug empirique
            NQ 23/04 : premier obstacle GEX_UP donnait R:R 1.12 → STEP 8 rejette.
          APRES : scanne TOUS les obstacles, prend le premier avec R:R >= 1.5.
            Si aucun → return 0, caller applique fallback TP_STANDARD = SL × 2.

        Returns: (tp_ticks, wall_name, reason)
          - tp_ticks > 0 : obstacle valide trouve (R:R >= MIN_RR_SELECTION)
          - tp_ticks == 0 : aucun obstacle acceptable, caller doit fallback
        """
        obstacles = self._scan_obstacles(row, direction)

        if not obstacles:
            return 0, "", "Aucun obstacle"

        # Scanner tous les obstacles dans l'ordre (distance croissante),
        # prendre le premier qui donne un R:R >= MIN_RR_SELECTION.
        skipped: List[str] = []
        for obs in obstacles:
            tp_cand = obs.abs_dist - self.tp_buffer
            if tp_cand <= 0:
                # Obstacle trop proche, mange entierement par le buffer
                skipped.append(f"{obs.name}@too_close")
                continue
            rr = tp_cand / sl_ticks if sl_ticks > 0 else 0
            if rr >= MIN_RR_SELECTION:
                return tp_cand, obs.name, \
                    f"TP avant {obs.name} (T{obs.tier}, R:R {rr:.2f})"
            skipped.append(f"{obs.name}@R:R{rr:.2f}")

        # Aucun obstacle n'atteint MIN_RR_SELECTION → caller applique fallback
        return 0, "", (f"Aucun obstacle R:R>={MIN_RR_SELECTION} "
                       f"(skipped: {', '.join(skipped[:3])})")

    # ─── SCAN OBSTACLES ────────────────────────────────────────────

    def _scan_obstacles(self, row: pd.Series, direction: int) -> List[Wall]:
        """
        Scanne tous les murs Tier 1 et Tier 2 DEVANT le prix (dans la direction du trade).
        LONG → obstacles AU-DESSUS | SHORT → obstacles EN-DESSOUS

        FIX/ROLLBACK 28/04/2026 13:30 (Jackson "TP a hit quand meme") :
          Reaction initiale : inclure TIER3 dans scan TP (Put_0DTE, IB, OVN, etc.)
          parce qu'observation "TP derriere 3 murs" sur ES SHORT @ 7174.
          MAIS empiriquement le trade a TP +30t (TP_STANDARD_WALL_FAR R:R 2.0)
          alors que TIER3 inclusion aurait donne +13t (TP devant Put_0DTE).
          Lecon : TIER3 = murs papier qui se traversent. Lecture humaine "danger"
          != decision bot. R:R 2.0 mecanique > lecture visuelle prudente.
          ROLLBACK : revenir a TIER1+TIER2 seulement.
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
