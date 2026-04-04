"""
═══════════════════════════════════════════════════════════════════════════════
mia_double_top.py — Détection Double Top / Double Bottom pour MIA Trading System
═══════════════════════════════════════════════════════════════════════════════

Option B : CONFIRMATION / BOOSTER dans le paradigme existant (pas un régime séparé).

PRINCIPE
--------
Un double top/bottom c'est un TEST DE NIVEAU QUI ÉCHOUE DEUX FOIS.
Le 2ème test est statistiquement plus fiable que le 1er car le niveau est prouvé.

Ce module détecte les retests de swing highs/lows et produit un SCORE DE BOOST
qui s'intègre dans le pipeline Régime → Zone → Trigger du paradigme MIA.

INTÉGRATION PARADIGME
---------------------
  ROTATION  : prix au PVAH → double top + absorption → trigger renforcé, sizing +25%
  REVERSAL  : ODF détecté → prix reteste le high → double top + delta div → confirmation
  BREAKOUT  : prix teste IB High 2x et CASSE au 3ème → breakout validé (plus fort)
  TREND     : double bottom sur pullback = continuation confirmée (achat le dip)

DONNÉES UTILISÉES (toutes disponibles dans le JSONL du Dumper G3)
-----------------------------------------------------------------
  - dist_swing_high / dist_swing_low  (G8) — distance au dernier swing
  - new_swing_high / new_swing_low    (G8) — nouveau swing cette barre
  - delta_bar / delta_bar_vol_norm    (G6) — delta pour divergence
  - bn_score_raw                      (G7) — score BN pour confirmation
  - bn_absorb_ask / bn_absorb_bid    (G7) — absorption au 2ème test
  - cvd_day / cvd_day_dir             (G6) — CVD pour divergence
  - vol_per_sec                       (G6) — volume pour confirmation breakout
  - dist_cur_vah / dist_cur_val       (G2) — VA pour contexte rotation
  - dist_prev_vah / dist_prev_val     (G2) — PV levels pour confluence
  - dist_ib_high / dist_ib_low        (G4) — IB pour contexte breakout
  - dist_vwap_d_sd2u / sd2d           (G1) — VWAP SD±2 pour extrêmes

ALGORITHME
----------
  1. Scanner les swing highs/lows sur fenêtre glissante (N barres)
  2. Détecter si le prix actuel RETESTE un swing précédent (±tolérance ticks)
  3. Compter le nombre de retests
  4. Vérifier la divergence delta (2ème test a moins de force que le 1er)
  5. Vérifier confluence avec niveaux structurels (PVAH, IB High, VWAP SD)
  6. Produire un RetestResult avec score de boost

RÉFÉRENCES
----------
  - Bulkowski : ±2% tolérance pour stocks, distance min 30 jours
  - Quantpedia : double bottom ETFs, 3% SL / 6% TP
  - QuantifiedStrategies : 68% hit rate double bottom, 39% double top (stock bias)
  - Trader Dale : VWAP + Volume Profile confluence = "high-confidence entry"
  - Pour futures intraday ES/NQ : on adapte en ticks (pas en %)

Auteur : MIA Trading System — v1.0 — 2026-03-01
═══════════════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple
import math


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetestConfig:
    """Configuration pour la détection de double top/bottom.
    
    Paramètres adaptés pour futures intraday ES/NQ sur barres 1-min.
    Les valeurs par défaut sont calibrées pour ES ; NQ a des seuils plus larges.
    """
    
    # ── TOLÉRANCE DE RETEST ──────────────────────────────────────────────────
    # Le 2ème sommet doit être dans cette tolérance du 1er pour être un "retest"
    # Trop serré = rate des retests légèrement plus hauts
    # Trop large = faux positifs (simple continuation)
    retest_tolerance_ticks_es: float = 4.0    # ±4 ticks = ±1.00 pt ES
    retest_tolerance_ticks_nq: float = 6.0    # ±6 ticks = ±1.50 pt NQ (plus volatile)
    
    # ── FENÊTRE DE RECHERCHE ─────────────────────────────────────────────────
    # Nombre de barres en arrière pour chercher les swings précédents
    # Sur barres 1-min : 30 barres = 30 min, 60 = 1h, 120 = 2h
    lookback_bars: int = 60                   # 1 heure de lookback
    
    # Distance MINIMALE entre 2 swings pour être un double top (pas un seul pic plat)
    # 🔧 17/03/2026: 5→25 barres (audit: 227 détections/546 barres = trop de micro-oscillations)
    min_bars_between_swings: int = 25          # Au moins 25 min entre les 2 sommets
    
    # Distance MAXIMALE entre 2 swings (au-delà c'est un niveau historique, pas un DT)
    max_bars_between_swings: int = 90         # Max 1h30 entre les 2 sommets
    
    # ── SEUILS DE DIVERGENCE ─────────────────────────────────────────────────
    # Le 2ème test doit avoir MOINS de force que le 1er (= divergence = épuisement)
    # Ratio delta_2nd / delta_1st : < 1.0 = divergence, < 0.70 = forte divergence
    delta_divergence_threshold: float = 0.85  # 2ème test a max 85% du delta du 1er
    
    # ── CONFLUENCE STRUCTURELLE ──────────────────────────────────────────────
    # Distance max à un niveau structurel pour compter comme "confluence"
    # Le retest + confluence = le setup le plus fiable
    confluence_distance_ticks: float = 8.0    # ±8 ticks du niveau = confluence
    
    # ── SCORING ──────────────────────────────────────────────────────────────
    # Boost maximum accordé par un double top/bottom confirmé
    max_boost: float = 0.30                   # +30% boost max sur le trigger score
    
    # Pénalité si on essaie de fader un double top/bottom (trade contraire)
    # Ex: LONG alors qu'il y a un double top confirmé = mauvaise idée
    contra_penalty: float = -0.25             # -25% pénalité


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — TYPES ET ÉNUMS
# ═══════════════════════════════════════════════════════════════════════════════

class RetestType(IntEnum):
    """Type de retest détecté."""
    NONE = 0            # Pas de retest
    DOUBLE_TOP = 1      # Double Top (M-shape) — bearish
    DOUBLE_BOTTOM = 2   # Double Bottom (W-shape) — bullish
    TRIPLE_TOP = 3      # Triple Top — bearish renforcé
    TRIPLE_BOTTOM = 4   # Triple Bottom — bullish renforcé


class RetestQuality(IntEnum):
    """Qualité du retest (de faible à parfait)."""
    NONE = 0            # Pas de retest
    WEAK = 1            # Retest simple sans divergence ni confluence
    MODERATE = 2        # Retest + divergence OU confluence (pas les deux)
    STRONG = 3          # Retest + divergence + confluence
    PERFECT = 4         # Retest + divergence + confluence + absorption BN


class StructuralLevel(IntEnum):
    """Niveau structurel en confluence avec le retest."""
    NONE = 0
    PVAH = 1            # Previous Value Area High
    PVAL = 2            # Previous Value Area Low
    PVPOC = 3           # Previous VPOC
    IB_HIGH = 4         # Initial Balance High
    IB_LOW = 5          # Initial Balance Low
    VWAP_SD2U = 6       # VWAP +2 sigma (surévalué)
    VWAP_SD2D = 7       # VWAP -2 sigma (sous-évalué)
    SESSION_VAH = 8     # Session VAH
    SESSION_VAL = 9     # Session VAL
    GAMMA_WALL = 10     # MenthorQ Gamma Wall
    HVN = 11            # High Volume Node session


@dataclass
class SwingPoint:
    """Un swing high ou low détecté dans l'historique."""
    bar_index: int          # Index de la barre
    price: float            # Prix du swing
    is_high: bool           # True = swing high, False = swing low
    delta_at_swing: float   # Delta à ce swing (pour divergence)
    cvd_at_swing: float     # CVD à ce swing (pour divergence)
    volume_at_swing: float  # Volume à ce swing (pour confirmation)
    bn_score_at_swing: float  # BN score à ce swing


@dataclass
class RetestResult:
    """Résultat de la détection de double top/bottom.
    
    C'est l'OUTPUT du module, consommé par le pipeline Trigger.
    """
    # ── DÉTECTION ────────────────────────────────────────────────────────────
    retest_type: RetestType = RetestType.NONE
    quality: RetestQuality = RetestQuality.NONE
    
    # ── COMPTAGE ─────────────────────────────────────────────────────────────
    retest_count: int = 0               # Nb de tests du même niveau (2=DT, 3=TT)
    bars_since_first_swing: int = 0     # Distance en barres depuis le 1er swing
    
    # ── PRIX ─────────────────────────────────────────────────────────────────
    first_swing_price: float = 0.0      # Prix du 1er sommet/creux
    second_swing_price: float = 0.0     # Prix du 2ème sommet/creux
    neckline_price: float = 0.0         # Neckline (creux entre 2 sommets / sommet entre 2 creux)
    
    # ── DIVERGENCE ───────────────────────────────────────────────────────────
    has_delta_divergence: bool = False   # 2ème test a moins de delta
    delta_ratio: float = 1.0            # delta_2nd / delta_1st (< 1.0 = divergence)
    has_cvd_divergence: bool = False     # CVD diverge du prix
    
    # ── CONFLUENCE ───────────────────────────────────────────────────────────
    has_structural_confluence: bool = False
    structural_level: StructuralLevel = StructuralLevel.NONE
    structural_level_name: str = ""     # Nom lisible ("PVAH", "IB_HIGH", etc.)
    confluence_distance_ticks: float = 0.0
    
    # ── ABSORPTION BN ────────────────────────────────────────────────────────
    has_absorption: bool = False         # Absorption détectée au 2ème test
    
    # ── SCORE DE BOOST ───────────────────────────────────────────────────────
    boost_score: float = 0.0            # [-0.25, +0.30] — multiplicateur trigger
    # Positif = renforce le trigger dans le SENS du retest
    #   Double Top confirmé → boost SHORT, pénalité LONG
    #   Double Bottom confirmé → boost LONG, pénalité SHORT
    
    # Direction du boost : +1 = bullish (double bottom), -1 = bearish (double top)
    boost_direction: int = 0            # -1 / 0 / +1
    
    def is_active(self) -> bool:
        """Y a-t-il un retest actif ?"""
        return self.retest_type != RetestType.NONE
    
    def is_contra(self, trade_direction: int) -> bool:
        """Le trade envisagé est-il CONTRAIRE au retest ?
        
        trade_direction: +1 = LONG, -1 = SHORT
        Retourne True si le trade va à l'encontre du retest (mauvaise idée).
        """
        if not self.is_active():
            return False
        # Double Top (bearish) + LONG = contra
        # Double Bottom (bullish) + SHORT = contra
        return (self.boost_direction * trade_direction) < 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — DÉTECTION DES SWINGS SUR FENÊTRE GLISSANTE
# ═══════════════════════════════════════════════════════════════════════════════

def detect_swing_points(
    highs: List[float],
    lows: List[float],
    deltas: List[float],
    cvds: List[float],
    volumes: List[float],
    bn_scores: List[float],
    pivot_period: int = 3
) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """Détecte les swing highs et swing lows sur une série de barres.
    
    Méthode : Un swing high est un bar dont le high est supérieur aux
    `pivot_period` barres de chaque côté. Idem pour swing low.
    
    Args:
        highs: Liste des highs par barre
        lows: Liste des lows par barre
        deltas: Liste des deltas par barre
        cvds: Liste des CVD par barre
        volumes: Liste des volumes par barre
        bn_scores: Liste des BN scores par barre
        pivot_period: Nombre de barres de chaque côté pour confirmer un pivot
        
    Returns:
        (swing_highs, swing_lows) — listes triées par bar_index
    """
    n = len(highs)
    swing_highs: List[SwingPoint] = []
    swing_lows: List[SwingPoint] = []
    
    if n < (2 * pivot_period + 1):
        return swing_highs, swing_lows
    
    for i in range(pivot_period, n - pivot_period):
        # ── Swing High ──
        is_sh = True
        for j in range(1, pivot_period + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_sh = False
                break
        if is_sh:
            swing_highs.append(SwingPoint(
                bar_index=i,
                price=highs[i],
                is_high=True,
                delta_at_swing=deltas[i] if i < len(deltas) else 0.0,
                cvd_at_swing=cvds[i] if i < len(cvds) else 0.0,
                volume_at_swing=volumes[i] if i < len(volumes) else 0.0,
                bn_score_at_swing=bn_scores[i] if i < len(bn_scores) else 0.0,
            ))
        
        # ── Swing Low ──
        is_sl = True
        for j in range(1, pivot_period + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_sl = False
                break
        if is_sl:
            swing_lows.append(SwingPoint(
                bar_index=i,
                price=lows[i],
                is_high=False,
                delta_at_swing=deltas[i] if i < len(deltas) else 0.0,
                cvd_at_swing=cvds[i] if i < len(cvds) else 0.0,
                volume_at_swing=volumes[i] if i < len(volumes) else 0.0,
                bn_score_at_swing=bn_scores[i] if i < len(bn_scores) else 0.0,
            ))
    
    return swing_highs, swing_lows


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DÉTECTION DE RETEST (DOUBLE TOP / DOUBLE BOTTOM)
# ═══════════════════════════════════════════════════════════════════════════════

def find_retest(
    current_price: float,
    current_high: float,
    current_low: float,
    current_bar_index: int,
    swing_points: List[SwingPoint],
    tolerance_ticks: float,
    tick_size: float,
    config: RetestConfig,
    check_high: bool = True
) -> Optional[Tuple[SwingPoint, int]]:
    """Cherche si le prix actuel reteste un swing précédent.
    
    Args:
        current_price: Prix courant
        current_high/low: High/Low de la barre courante
        current_bar_index: Index de la barre courante
        swing_points: Liste des swings détectés (highs ou lows)
        tolerance_ticks: Tolérance en ticks pour le retest
        tick_size: Taille d'un tick (0.25 pour ES/NQ)
        config: Configuration
        check_high: True = cherche double top (vs swing highs), False = double bottom
        
    Returns:
        (swing_retesté, nombre_de_retests) ou None si pas de retest
    """
    tolerance_pts = tolerance_ticks * tick_size
    test_price = current_high if check_high else current_low
    
    # Chercher les swings dans la fenêtre
    candidates: List[SwingPoint] = []
    for sp in swing_points:
        bars_diff = current_bar_index - sp.bar_index
        if bars_diff < config.min_bars_between_swings:
            continue  # Trop récent, probablement le même pic
        if bars_diff > config.max_bars_between_swings:
            continue  # Trop ancien
        
        # Le prix actuel est-il dans la tolérance du swing ?
        price_diff = abs(test_price - sp.price)
        if price_diff <= tolerance_pts:
            candidates.append(sp)
    
    if not candidates:
        return None
    
    # Prendre le swing le plus récent (le plus pertinent)
    candidates.sort(key=lambda s: s.bar_index, reverse=True)
    best = candidates[0]
    
    # Compter le nombre total de retests à ce niveau (pour triple top/bottom)
    retest_count = 1  # Le swing original
    for sp in swing_points:
        if sp.bar_index == best.bar_index:
            continue
        if abs(sp.price - best.price) <= tolerance_pts:
            if config.min_bars_between_swings <= abs(sp.bar_index - best.bar_index):
                retest_count += 1
    
    retest_count += 1  # +1 pour le test actuel
    
    return (best, retest_count)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — VÉRIFICATION CONFLUENCE STRUCTURELLE
# ═══════════════════════════════════════════════════════════════════════════════

def check_structural_confluence(
    swing_price: float,
    bar_data: dict,
    config: RetestConfig,
    tick_size: float = 0.25
) -> Tuple[bool, StructuralLevel, str, float]:
    """Vérifie si le swing est en confluence avec un niveau structurel.
    
    Args:
        swing_price: Prix du swing testé
        bar_data: Dictionnaire avec les colonnes JSONL de la barre courante
        config: Configuration
        tick_size: Taille d'un tick
        
    Returns:
        (has_confluence, level_type, level_name, distance_ticks)
    """
    tolerance_pts = config.confluence_distance_ticks * tick_size
    price = bar_data.get("price", 0.0)
    
    # Liste des niveaux à vérifier (prix = price + dist_ticks * tick_size)
    # Convention dumper : dist positif = niveau au-dessus du prix
    levels = []
    
    # ── PV Levels (les plus importants) ──
    if _valid(bar_data.get("dist_prev_vah")):
        pvah_price = price + bar_data["dist_prev_vah"] * tick_size
        levels.append((pvah_price, StructuralLevel.PVAH, "PVAH"))
    
    if _valid(bar_data.get("dist_prev_val")):
        pval_price = price + bar_data["dist_prev_val"] * tick_size
        levels.append((pval_price, StructuralLevel.PVAL, "PVAL"))
    
    if _valid(bar_data.get("dist_prev_vpoc")):
        pvpoc_price = price + bar_data["dist_prev_vpoc"] * tick_size
        levels.append((pvpoc_price, StructuralLevel.PVPOC, "PVPOC"))
    
    # ── IB Levels ──
    if _valid(bar_data.get("dist_ib_high")):
        ib_h_price = price + bar_data["dist_ib_high"] * tick_size
        levels.append((ib_h_price, StructuralLevel.IB_HIGH, "IB_HIGH"))
    
    if _valid(bar_data.get("dist_ib_low")):
        ib_l_price = price + bar_data["dist_ib_low"] * tick_size
        levels.append((ib_l_price, StructuralLevel.IB_LOW, "IB_LOW"))
    
    # ── VWAP SD±2 (extrêmes) ──
    if _valid(bar_data.get("dist_vwap_d_sd2u")):
        sd2u_price = price + bar_data["dist_vwap_d_sd2u"] * tick_size
        levels.append((sd2u_price, StructuralLevel.VWAP_SD2U, "VWAP_SD+2"))
    
    if _valid(bar_data.get("dist_vwap_d_sd2d")):
        sd2d_price = price + bar_data["dist_vwap_d_sd2d"] * tick_size
        levels.append((sd2d_price, StructuralLevel.VWAP_SD2D, "VWAP_SD-2"))
    
    # ── Session VA ──
    if _valid(bar_data.get("dist_cur_vah")):
        svah_price = price + bar_data["dist_cur_vah"] * tick_size
        levels.append((svah_price, StructuralLevel.SESSION_VAH, "SESSION_VAH"))
    
    if _valid(bar_data.get("dist_cur_val")):
        sval_price = price + bar_data["dist_cur_val"] * tick_size
        levels.append((sval_price, StructuralLevel.SESSION_VAL, "SESSION_VAL"))
    
    # ── Gamma Wall MenthorQ ──
    if _valid(bar_data.get("next_wall_dist_ticks")):
        wall_dist = bar_data["next_wall_dist_ticks"]
        is_call = bar_data.get("next_wall_is_call", 0)
        wall_price = price + (wall_dist if is_call else -wall_dist) * tick_size
        levels.append((wall_price, StructuralLevel.GAMMA_WALL, "GAMMA_WALL"))
    
    # ── HVN Session ──
    if _valid(bar_data.get("dist_session_hvn_above")):
        hvn_price = price + bar_data["dist_session_hvn_above"] * tick_size
        levels.append((hvn_price, StructuralLevel.HVN, "HVN_ABOVE"))
    if _valid(bar_data.get("dist_session_hvn_below")):
        hvn_price = price - bar_data["dist_session_hvn_below"] * tick_size
        levels.append((hvn_price, StructuralLevel.HVN, "HVN_BELOW"))
    
    # ── Chercher la meilleure confluence ──
    best_dist = float("inf")
    best_level = StructuralLevel.NONE
    best_name = ""
    
    for level_price, level_type, level_name in levels:
        dist = abs(swing_price - level_price)
        if dist <= tolerance_pts and dist < best_dist:
            best_dist = dist
            best_level = level_type
            best_name = level_name
    
    if best_level != StructuralLevel.NONE:
        dist_ticks = best_dist / tick_size
        return (True, best_level, best_name, dist_ticks)
    
    return (False, StructuralLevel.NONE, "", 0.0)


def _valid(val) -> bool:
    """Vérifie qu'une valeur n'est pas None, NaN, ou DMP_INVALID."""
    if val is None:
        return False
    try:
        return math.isfinite(val)
    except (TypeError, ValueError):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SCORING DU BOOST
# ═══════════════════════════════════════════════════════════════════════════════

def compute_boost_score(
    retest_count: int,
    has_delta_div: bool,
    delta_ratio: float,
    has_cvd_div: bool,
    has_confluence: bool,
    has_absorption: bool,
    structural_level: StructuralLevel,
    config: RetestConfig
) -> Tuple[float, RetestQuality]:
    """Calcule le score de boost et la qualité du retest.
    
    Le boost est ADDITIF sur le trigger score existant.
    
    Composantes :
        Base retest          : +0.08  (le simple fait d'avoir un retest)
        Divergence delta     : +0.07  (2ème test plus faible)
        Divergence CVD       : +0.03  (CVD confirme l'épuisement)
        Confluence struct.   : +0.07  (retest à un niveau important)
        Absorption BN        : +0.05  (vendeurs/acheteurs cachés au 2ème test)
        Triple test bonus    : +0.03  (3ème test = encore plus fiable)
        Niveau fort bonus    : +0.02  (PVAH/PVAL/IB = niveaux les plus forts)
        
    Total max : 0.30 (avec tout aligné)
    Pénalité contra : -0.25 (appliquée par l'appelant via is_contra())
    
    Returns:
        (boost_score, quality)
    """
    score = 0.0
    quality_points = 0
    
    # ── Base : un retest existe ──
    score += 0.08
    
    # ── Divergence delta ──
    if has_delta_div:
        score += 0.07
        quality_points += 1
    
    # ── Divergence CVD ──
    if has_cvd_div:
        score += 0.03
    
    # ── Confluence structurelle ──
    if has_confluence:
        score += 0.07
        quality_points += 1
        
        # Bonus pour niveaux FORTS (PV levels, IB, Gamma Wall)
        strong_levels = {
            StructuralLevel.PVAH, StructuralLevel.PVAL, StructuralLevel.PVPOC,
            StructuralLevel.IB_HIGH, StructuralLevel.IB_LOW,
            StructuralLevel.GAMMA_WALL
        }
        if structural_level in strong_levels:
            score += 0.02
    
    # ── Absorption BN ──
    if has_absorption:
        score += 0.05
        quality_points += 1
    
    # ── Triple test bonus ──
    if retest_count >= 3:
        score += 0.03
    
    # ── Clamp ──
    score = min(score, config.max_boost)
    
    # ── Qualité ──
    if quality_points >= 3:
        quality = RetestQuality.PERFECT    # Div + Confluence + Absorption
    elif quality_points >= 2:
        quality = RetestQuality.STRONG     # 2 sur 3
    elif quality_points >= 1:
        quality = RetestQuality.MODERATE   # 1 sur 3
    else:
        quality = RetestQuality.WEAK       # Retest simple
    
    # 🔧 17/03/2026: Exiger minimum 1 confirmation pour fire
    # AVANT: WEAK retests (0 confirmations) firaient avec score 0.08 → 227 détections/546 barres
    # APRÈS: WEAK = score 0 → le retest existe mais ne booste rien
    # Seuls MODERATE+ (delta_div OU confluence OU absorption) produisent un boost
    if quality_points == 0:
        score = 0.0
    
    return (score, quality)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — FONCTION PRINCIPALE : detect_double_top_bottom()
# ═══════════════════════════════════════════════════════════════════════════════

def detect_double_top_bottom(
    bars: List[dict],
    current_index: int,
    symbol: str = "ES",
    config: Optional[RetestConfig] = None
) -> RetestResult:
    """Détecte un double top ou double bottom sur la barre courante.
    
    C'est la FONCTION PRINCIPALE du module. Appelée à chaque barre.
    
    Args:
        bars: Liste de dicts (chaque dict = 1 ligne JSONL du dumper)
              Doit contenir au minimum :
              - "price", "dist_swing_high", "dist_swing_low"
              - "new_swing_high", "new_swing_low"
              - "delta_bar", "delta_bar_vol_norm", "cvd_day"
              - "bn_score_raw", "bn_absorb_ask", "bn_absorb_bid"
              - "vol_per_sec"
              + les dist_* pour la confluence structurelle
        current_index: Index de la barre courante dans `bars`
        symbol: "ES" ou "NQ" (pour la tolérance)
        config: Configuration (défaut si None)
        
    Returns:
        RetestResult avec le type, la qualité, et le score de boost
    """
    if config is None:
        config = RetestConfig()
    
    result = RetestResult()
    
    # ── Paramètres symbole ──
    tick_size = 0.25  # ES et NQ
    tolerance = (config.retest_tolerance_ticks_es if symbol == "ES"
                 else config.retest_tolerance_ticks_nq)
    
    # ── Extraire les données de la fenêtre ──
    start = max(0, current_index - config.lookback_bars)
    window = bars[start:current_index + 1]
    
    if len(window) < config.min_bars_between_swings + 5:
        return result  # Pas assez de données
    
    # ── Construire les séries pour detect_swing_points ──
    # On utilise le prix + distance swing pour reconstruire les highs/lows approximatifs
    # Alternative : si on a les vrais OHLC, c'est mieux
    prices = []
    highs = []
    lows = []
    deltas = []
    cvds = []
    volumes = []
    bn_scores = []
    
    for b in window:
        p = b.get("price", 0.0)
        prices.append(p)
        
        # 🔧 17/03/2026: Meilleur calcul high/low
        # AVANT: price ± 5% ATR = même valeur partout = swings fictifs
        # APRÈS: utiliser momentum inter-barres comme proxy du range
        # Le high/low d'une barre 1-min ≈ prix ± (|changement depuis barre précédente| / 2)
        if len(prices) >= 2:
            bar_move = abs(prices[-1] - prices[-2])
            bar_range_approx = max(bar_move * 0.6, 0.50)  # Min 2 ticks
        else:
            bar_range_approx = 1.0  # Fallback 4 ticks
        highs.append(p + bar_range_approx)
        lows.append(p - bar_range_approx)
        
        deltas.append(b.get("delta_bar", 0.0))
        cvds.append(b.get("cvd_day", 0.0))
        volumes.append(b.get("vol_per_sec", 0.0))
        bn_scores.append(b.get("bn_score_raw", 0.0))
    
    # ── Détecter les swings ──
    swing_highs, swing_lows = detect_swing_points(
        highs, lows, deltas, cvds, volumes, bn_scores, pivot_period=3
    )
    
    current_bar = bars[current_index]
    current_price = current_bar.get("price", 0.0)
    current_high = highs[-1] if highs else current_price
    current_low = lows[-1] if lows else current_price
    local_index = len(window) - 1  # Index local dans la fenêtre
    
    # ── Chercher un double top ──
    dt_result = find_retest(
        current_price, current_high, current_low,
        local_index, swing_highs, tolerance, tick_size,
        config, check_high=True
    )
    
    # ── Chercher un double bottom ──
    db_result = find_retest(
        current_price, current_high, current_low,
        local_index, swing_lows, tolerance, tick_size,
        config, check_high=False
    )
    
    # ── Choisir le meilleur (prioriser celui avec plus de retests) ──
    chosen_swing: Optional[SwingPoint] = None
    chosen_count = 0
    is_top = False
    
    if dt_result and db_result:
        # Les deux existent → prendre celui avec plus de retests
        if dt_result[1] >= db_result[1]:
            chosen_swing, chosen_count = dt_result
            is_top = True
        else:
            chosen_swing, chosen_count = db_result
            is_top = False
    elif dt_result:
        chosen_swing, chosen_count = dt_result
        is_top = True
    elif db_result:
        chosen_swing, chosen_count = db_result
        is_top = False
    
    if chosen_swing is None:
        return result  # Pas de retest détecté
    
    # ── Type de retest ──
    if is_top:
        if chosen_count >= 3:
            result.retest_type = RetestType.TRIPLE_TOP
        else:
            result.retest_type = RetestType.DOUBLE_TOP
        result.boost_direction = -1  # Bearish
    else:
        if chosen_count >= 3:
            result.retest_type = RetestType.TRIPLE_BOTTOM
        else:
            result.retest_type = RetestType.DOUBLE_BOTTOM
        result.boost_direction = +1  # Bullish
    
    result.retest_count = chosen_count
    result.first_swing_price = chosen_swing.price
    result.second_swing_price = current_high if is_top else current_low
    result.bars_since_first_swing = local_index - chosen_swing.bar_index
    
    # ── Neckline (creux/sommet entre les 2 swings) ──
    swing_start = chosen_swing.bar_index
    if is_top:
        # Neckline = plus bas low entre les 2 sommets
        neckline_lows = lows[swing_start:local_index]
        result.neckline_price = min(neckline_lows) if neckline_lows else current_low
    else:
        # Neckline = plus haut high entre les 2 creux
        neckline_highs = highs[swing_start:local_index]
        result.neckline_price = max(neckline_highs) if neckline_highs else current_high
    
    # ── Divergence delta ──
    current_delta = current_bar.get("delta_bar", 0.0)
    first_delta = chosen_swing.delta_at_swing
    
    if is_top:
        # Double top : delta au 2ème sommet devrait être MOINS positif
        if first_delta > 0 and current_delta > 0:
            result.delta_ratio = current_delta / first_delta if first_delta != 0 else 1.0
        elif first_delta > 0 and current_delta <= 0:
            result.delta_ratio = 0.0  # Parfaite divergence : delta négatif au 2ème top
        else:
            result.delta_ratio = 1.0
    else:
        # Double bottom : delta au 2ème creux devrait être MOINS négatif
        if first_delta < 0 and current_delta < 0:
            result.delta_ratio = abs(current_delta / first_delta) if first_delta != 0 else 1.0
        elif first_delta < 0 and current_delta >= 0:
            result.delta_ratio = 0.0  # Parfaite divergence : delta positif au 2ème bottom
        else:
            result.delta_ratio = 1.0
    
    result.has_delta_divergence = result.delta_ratio < config.delta_divergence_threshold
    
    # ── Divergence CVD ──
    current_cvd = current_bar.get("cvd_day", 0.0)
    first_cvd = chosen_swing.cvd_at_swing
    if is_top:
        # Prix fait un double top mais CVD fait un lower high
        result.has_cvd_divergence = (current_cvd < first_cvd * 0.95)
    else:
        # Prix fait un double bottom mais CVD fait un higher low
        result.has_cvd_divergence = (current_cvd > first_cvd * 1.05)
    
    # ── Absorption BN ──
    if is_top:
        # Au 2ème top, on veut voir de l'absorption ASK (vendeurs absorbent les acheteurs)
        result.has_absorption = bool(current_bar.get("bn_absorb_ask", 0))
    else:
        # Au 2ème bottom, absorption BID (acheteurs absorbent les vendeurs)
        result.has_absorption = bool(current_bar.get("bn_absorb_bid", 0))
    
    # ── Confluence structurelle ──
    (result.has_structural_confluence,
     result.structural_level,
     result.structural_level_name,
     result.confluence_distance_ticks) = check_structural_confluence(
        chosen_swing.price, current_bar, config, tick_size
    )
    
    # ── Score de boost ──
    result.boost_score, result.quality = compute_boost_score(
        retest_count=result.retest_count,
        has_delta_div=result.has_delta_divergence,
        delta_ratio=result.delta_ratio,
        has_cvd_div=result.has_cvd_divergence,
        has_confluence=result.has_structural_confluence,
        has_absorption=result.has_absorption,
        structural_level=result.structural_level,
        config=config
    )
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — HELPER : APPLICATION DU BOOST AU TRIGGER
# ═══════════════════════════════════════════════════════════════════════════════

def apply_retest_boost(
    trigger_score: float,
    trade_direction: int,
    retest: RetestResult,
    config: Optional[RetestConfig] = None
) -> Tuple[float, str]:
    """Applique le boost du retest au score trigger existant.
    
    Args:
        trigger_score: Score du trigger actuel [0, 1] du pipeline MIA
        trade_direction: +1 = LONG, -1 = SHORT
        retest: Résultat de detect_double_top_bottom()
        config: Configuration
        
    Returns:
        (adjusted_score, reason_string)
        
    Exemples:
        # Double top confirmé + SHORT → trigger renforcé
        apply_retest_boost(0.60, -1, retest_dt)  # → (0.78, "DT@PVAH+div")
        
        # Double top confirmé + LONG → trigger pénalisé
        apply_retest_boost(0.60, +1, retest_dt)  # → (0.35, "CONTRA_DT@PVAH")
        
        # Pas de retest → inchangé
        apply_retest_boost(0.60, +1, no_retest)  # → (0.60, "")
    """
    if config is None:
        config = RetestConfig()
    
    if not retest.is_active():
        return (trigger_score, "")
    
    # ── Le trade est-il dans le sens du retest ? ──
    if retest.is_contra(trade_direction):
        # CONTRE le retest → pénalité
        adjusted = trigger_score + config.contra_penalty  # contra_penalty est négatif
        adjusted = max(0.0, adjusted)
        
        type_name = "DT" if retest.boost_direction < 0 else "DB"
        level = f"@{retest.structural_level_name}" if retest.has_structural_confluence else ""
        reason = f"CONTRA_{type_name}{level}"
        return (adjusted, reason)
    else:
        # DANS le sens du retest → boost
        adjusted = trigger_score + retest.boost_score
        adjusted = min(1.0, adjusted)
        
        type_name = "DT" if retest.boost_direction < 0 else "DB"
        level = f"@{retest.structural_level_name}" if retest.has_structural_confluence else ""
        div = "+div" if retest.has_delta_divergence else ""
        abs_str = "+abs" if retest.has_absorption else ""
        quality_str = f"[{retest.quality.name}]"
        reason = f"{type_name}{level}{div}{abs_str}{quality_str}"
        return (adjusted, reason)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — ADAPTATION PAR RÉGIME
# ═══════════════════════════════════════════════════════════════════════════════

def get_regime_adjusted_config(regime: int, base_config: Optional[RetestConfig] = None) -> RetestConfig:
    """Ajuste la configuration de retest selon le régime MIA.
    
    Le même double top n'a pas le même poids selon le contexte.
    
    Args:
        regime: 0=INCERTAIN, 1=TREND, 2=ROTATION, 3=REVERSAL, 4=BREAKOUT
        base_config: Config de base (défaut si None)
        
    Returns:
        Config ajustée pour le régime
    """
    cfg = base_config if base_config else RetestConfig()
    
    # Créer une copie
    adjusted = RetestConfig(
        retest_tolerance_ticks_es=cfg.retest_tolerance_ticks_es,
        retest_tolerance_ticks_nq=cfg.retest_tolerance_ticks_nq,
        lookback_bars=cfg.lookback_bars,
        min_bars_between_swings=cfg.min_bars_between_swings,
        max_bars_between_swings=cfg.max_bars_between_swings,
        delta_divergence_threshold=cfg.delta_divergence_threshold,
        confluence_distance_ticks=cfg.confluence_distance_ticks,
        max_boost=cfg.max_boost,
        contra_penalty=cfg.contra_penalty,
    )
    
    if regime == 1:  # TREND
        # En TREND, un double bottom sur pullback = continuation (très fiable)
        # Un double top CONTRE le trend = ignoré (le trend gagne)
        adjusted.max_boost = 0.20           # Boost modéré (le trend fait le travail)
        adjusted.contra_penalty = -0.35     # Forte pénalité si on fade le trend
        adjusted.lookback_bars = 45         # Fenêtre plus courte (swings rapides en trend)
    
    elif regime == 2:  # ROTATION
        # En ROTATION, le double top/bottom aux extrêmes VA = LE setup idéal
        adjusted.max_boost = 0.30           # Boost max (c'est exactement ce qu'on cherche)
        adjusted.contra_penalty = -0.20     # Pénalité modérée
        adjusted.lookback_bars = 90         # Fenêtre plus large (rotations lentes)
        adjusted.confluence_distance_ticks = 10.0  # Tolérance confluence plus large
    
    elif regime == 3:  # REVERSAL
        # En REVERSAL, le double top/bottom CONFIRME le retournement
        adjusted.max_boost = 0.25           # Bon boost
        adjusted.contra_penalty = -0.30     # Forte pénalité si on fight le reversal
        adjusted.delta_divergence_threshold = 0.90  # Divergence moins exigeante (le reversal fait le travail)
    
    elif regime == 4:  # BREAKOUT
        # En BREAKOUT, un double test de l'IB qui CASSE = breakout validé
        # Un double top À l'IB qui NE casse PAS = rotation (pas breakout)
        adjusted.max_boost = 0.20           # Boost modéré
        adjusted.contra_penalty = -0.15     # Pénalité faible (breakout peut réussir au 3ème test)
        adjusted.min_bars_between_swings = 3  # Tests rapides sur IB
        adjusted.lookback_bars = 60         # Fenêtre standard
    
    else:  # INCERTAIN (0)
        # En INCERTAIN, exiger plus de preuves
        adjusted.max_boost = 0.15           # Boost faible
        adjusted.contra_penalty = -0.25     # Pénalité standard
        adjusted.delta_divergence_threshold = 0.75  # Divergence plus exigeante
    
    return adjusted


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def run_tests():
    """Tests unitaires du module."""
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
            print(f"  ❌ {name}: condition is False")
    
    def assert_near(name, actual, expected, tol=0.01):
        nonlocal passed, failed
        if abs(actual - expected) <= tol:
            passed += 1
        else:
            failed += 1
            print(f"  ❌ {name}: got {actual:.4f}, expected {expected:.4f}")
    
    print("=" * 60)
    print("TESTS mia_double_top.py")
    print("=" * 60)
    
    # ── Test 1: RetestResult.is_active() ──
    r = RetestResult()
    assert_eq("T01 - no retest is_active", r.is_active(), False)
    r.retest_type = RetestType.DOUBLE_TOP
    assert_eq("T02 - DT is_active", r.is_active(), True)
    
    # ── Test 2: RetestResult.is_contra() ──
    r = RetestResult(retest_type=RetestType.DOUBLE_TOP, boost_direction=-1)
    assert_eq("T03 - DT + LONG = contra", r.is_contra(+1), True)
    assert_eq("T04 - DT + SHORT = aligned", r.is_contra(-1), False)
    
    r = RetestResult(retest_type=RetestType.DOUBLE_BOTTOM, boost_direction=+1)
    assert_eq("T05 - DB + SHORT = contra", r.is_contra(-1), True)
    assert_eq("T06 - DB + LONG = aligned", r.is_contra(+1), False)
    
    r = RetestResult()
    assert_eq("T07 - no retest = not contra", r.is_contra(+1), False)
    
    # ── Test 3: detect_swing_points ──
    # Créer une série avec un swing high évident au bar 5
    h = [100, 101, 102, 103, 104, 108, 104, 103, 102, 101, 100]
    l = [99, 100, 101, 102, 103, 106, 103, 102, 101, 100, 99]
    d = [0.0] * 11
    c = [0.0] * 11
    v = [1.0] * 11
    b = [0.0] * 11
    
    sh, sl = detect_swing_points(h, l, d, c, v, b, pivot_period=3)
    assert_eq("T08 - 1 swing high detected", len(sh), 1)
    assert_eq("T09 - swing high at index 5", sh[0].bar_index, 5)
    assert_eq("T10 - swing high price", sh[0].price, 108)
    
    # Swing low
    h2 = [108, 104, 103, 102, 101, 98, 101, 102, 103, 104, 108]
    l2 = [106, 103, 102, 101, 100, 96, 100, 101, 102, 103, 106]
    sh2, sl2 = detect_swing_points(h2, l2, d, c, v, b, pivot_period=3)
    assert_eq("T11 - 1 swing low detected", len(sl2), 1)
    assert_eq("T12 - swing low at index 5", sl2[0].bar_index, 5)
    assert_eq("T13 - swing low price", sl2[0].price, 96)
    
    # ── Test 4: compute_boost_score ──
    cfg = RetestConfig()
    
    # Retest simple (rien d'autre)
    # 🔧 17/03/2026: WEAK retests → score 0 (exige min 1 confirmation)
    score, quality = compute_boost_score(2, False, 1.0, False, False, False, StructuralLevel.NONE, cfg)
    assert_near("T14 - weak boost (no confirmation = 0)", score, 0.00)
    assert_eq("T15 - weak quality", quality, RetestQuality.WEAK)
    
    # Retest + divergence
    score, quality = compute_boost_score(2, True, 0.60, False, False, False, StructuralLevel.NONE, cfg)
    assert_near("T16 - moderate boost (div)", score, 0.15)
    assert_eq("T17 - moderate quality", quality, RetestQuality.MODERATE)
    
    # Retest + divergence + confluence PVAH
    score, quality = compute_boost_score(2, True, 0.60, False, True, False, StructuralLevel.PVAH, cfg)
    assert_near("T18 - strong boost (div+conf)", score, 0.24)
    assert_eq("T19 - strong quality", quality, RetestQuality.STRONG)
    
    # Retest + tout (PERFECT)
    score, quality = compute_boost_score(2, True, 0.40, True, True, True, StructuralLevel.PVAH, cfg)
    assert_near("T20 - perfect boost", score, 0.30)  # Capped at max_boost
    assert_eq("T21 - perfect quality", quality, RetestQuality.PERFECT)
    
    # Triple test bonus
    score, _ = compute_boost_score(3, True, 0.50, False, True, False, StructuralLevel.IB_HIGH, cfg)
    assert_true("T22 - triple test > double test", score > 0.24)
    
    # ── Test 5: apply_retest_boost ──
    retest_dt = RetestResult(
        retest_type=RetestType.DOUBLE_TOP,
        boost_direction=-1,
        boost_score=0.20,
        quality=RetestQuality.STRONG,
        has_structural_confluence=True,
        structural_level_name="PVAH",
        has_delta_divergence=True,
    )
    
    # SHORT aligné avec DT → boost
    adj, reason = apply_retest_boost(0.60, -1, retest_dt)
    assert_near("T23 - SHORT + DT = boosted", adj, 0.80)
    assert_true("T24 - reason contains DT", "DT" in reason)
    assert_true("T25 - reason contains PVAH", "PVAH" in reason)
    
    # LONG contra DT → pénalité
    adj, reason = apply_retest_boost(0.60, +1, retest_dt)
    assert_near("T26 - LONG + DT = penalized", adj, 0.35)
    assert_true("T27 - reason contains CONTRA", "CONTRA" in reason)
    
    # Pas de retest → inchangé
    adj, reason = apply_retest_boost(0.60, +1, RetestResult())
    assert_near("T28 - no retest = unchanged", adj, 0.60)
    assert_eq("T29 - no reason", reason, "")
    
    # ── Test 6: get_regime_adjusted_config ──
    cfg_trend = get_regime_adjusted_config(1)
    cfg_rotation = get_regime_adjusted_config(2)
    
    assert_true("T30 - TREND max_boost < ROTATION", cfg_trend.max_boost < cfg_rotation.max_boost)
    assert_true("T31 - TREND contra penalty stronger", cfg_trend.contra_penalty < cfg_rotation.contra_penalty)
    assert_true("T32 - ROTATION lookback > TREND", cfg_rotation.lookback_bars > cfg_trend.lookback_bars)
    
    cfg_breakout = get_regime_adjusted_config(4)
    assert_true("T33 - BREAKOUT min_bars shorter", cfg_breakout.min_bars_between_swings < cfg_rotation.min_bars_between_swings)
    
    cfg_uncertain = get_regime_adjusted_config(0)
    assert_true("T34 - UNCERTAIN max_boost smallest", cfg_uncertain.max_boost <= cfg_trend.max_boost)
    assert_true("T35 - UNCERTAIN div threshold strictest",
                cfg_uncertain.delta_divergence_threshold < cfg_trend.delta_divergence_threshold)
    
    # ── Test 7: _valid helper ──
    assert_eq("T36 - valid float", _valid(1.0), True)
    assert_eq("T37 - invalid None", _valid(None), False)
    assert_eq("T38 - invalid NaN", _valid(float("nan")), False)
    assert_eq("T39 - invalid inf", _valid(float("inf")), False)
    assert_eq("T40 - valid zero", _valid(0.0), True)
    assert_eq("T41 - valid negative", _valid(-5.0), True)
    
    # ── Test 8: Clamp et edge cases ──
    # Score ne dépasse pas max_boost
    score, _ = compute_boost_score(4, True, 0.1, True, True, True, StructuralLevel.PVAH, cfg)
    assert_true("T42 - score capped at max_boost", score <= cfg.max_boost)
    
    # Contra penalty ne descend pas sous 0
    adj, _ = apply_retest_boost(0.10, +1, retest_dt)
    assert_true("T43 - penalized score >= 0", adj >= 0.0)
    
    # Boosted score ne dépasse pas 1.0
    retest_big = RetestResult(
        retest_type=RetestType.DOUBLE_BOTTOM,
        boost_direction=+1,
        boost_score=0.30,
    )
    adj, _ = apply_retest_boost(0.90, +1, retest_big)
    assert_true("T44 - boosted score <= 1.0", adj <= 1.0)
    
    # ── Résumé ──
    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"RÉSULTATS : {passed}/{total} tests passés", end="")
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
