# -*- coding: utf-8 -*-
"""
=============================================================================
MIA IA SYSTEM - CONFIGURATION V17_ULTIMATE FINALE
=============================================================================

RÉSULTATS BACKTEST:
- Win Rate: 89.5% (US_MORNING), 82.3% (POWER_HOUR)
- P&L: +$12,626 (US_MORNING), +$3,464 (POWER_HOUR)
- Total estimé: +$16,090 sur période de test

PROBLÈME RÉSOLU:
Le trailing ne marchait pas car:
1. Il était DÉSACTIVÉ (enable_trailing_stop = False)
2. Activation à 28 ticks (MFE moyen = 13t → JAMAIS atteint!)
3. Système de paliers progressifs au lieu de simple trailing

SOLUTION:
- Activation: 6 ticks (au lieu de 28!)
- Distance: 4 ticks (au lieu de 8!)
- Trailing simple (pas de paliers)

Created: 23/12/2025
Author: Jackson (MIA IA SYSTEM)
=============================================================================
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

# =============================================================================
# CONFIGURATION PRINCIPALE
# =============================================================================

@dataclass
class V17UltimateConfig:
    """Configuration V17_ULTIMATE validée par backtest V18/V19."""
    
    # === IDENTIFIANT ===
    version: str = "V17_ULTIMATE"
    created: str = "2025-12-23"
    
    # === TP/SL (identique pour ES et NQ) ===
    tp_ticks_es: int = 10
    sl_ticks_es: int = 10
    tp_ticks_nq: int = 14  # NQ légèrement plus large
    sl_ticks_nq: int = 14
    
    # === DISTANCE AU NIVEAU ===
    min_distance_ticks: int = 5  # NOUVEAU: évite trades trop proches
    max_distance_ticks: int = 8
    
    # === FILTRES DELTA/MIA ===
    use_delta_filter: bool = True
    delta_threshold: int = 150  # Delta > 150 pour LONG, < -150 pour SHORT
    mia_threshold: float = 0.52  # MIA > 0.52 pour LONG, < 0.48 pour SHORT
    
    # === TRAILING STOP - CORRIGÉ ! ===
    use_trailing_stop: bool = True  # 🔥 ACTIVER !
    trailing_activation_ticks: int = 6  # 🔥 6 au lieu de 28 !
    trailing_distance_ticks: int = 4  # 🔥 4 au lieu de 8 !
    use_progressive_trailing: bool = False  # Désactiver les paliers
    
    # === OBSTACLE DETECTION ===
    use_obstacle_detection: bool = True
    min_obstacle_score: int = 2  # Score S2+ seulement
    obstacle_buffer_ticks: int = 2
    min_rr_after_adjust: float = 0.7
    
    # === NIVEAUX ===
    profitable_levels: List[str] = field(default_factory=lambda: [
        'vwap_dn1',      # 46.8% WR, +$4,875
        'vwap',          # 43.4% WR, +$3,150
        '1d_min',        # 54.5% WR, +$1,800
        '1d_max',        # 71.4% WR, +$1,650
        'put_support',   # 72.7% WR, +$1,350
        'vwap_up1',      # Secondary
        'hvl',           # Secondary
        'call_resistance',  # Secondary
        'vpoc',          # Secondary
    ])
    
    levels_to_avoid: List[str] = field(default_factory=lambda: [
        'gex_2',         # -$1,200 (seul niveau perdant!)
        'gex_1',         # Instable
        'gamma_wall_level',  # Peu fiable
    ])
    
    # === SESSIONS ===
    active_sessions: List[str] = field(default_factory=lambda: [
        'US_MORNING',    # Meilleure session (89.5% WR)
        'POWER_HOUR',    # Bonne session (82.3% WR)
        # 'LONDON',      # Optionnel (moins de données)
    ])
    
    # === COOLDOWN ===
    cooldown_bars: int = 50  # ~50 secondes entre trades


# =============================================================================
# CONFIGURATION TRAILING - DÉTAILLÉE
# =============================================================================

@dataclass  
class TrailingStopConfig:
    """
    Configuration du trailing stop CORRIGÉE.
    
    AVANT (NE MARCHAIT PAS):
    - activation_ticks: 28  → MFE moyen = 13t, JAMAIS atteint!
    - distance_ticks: 8     → Trop large
    - Système de paliers progressifs complexe
    
    APRÈS (VALIDÉ PAR BACKTEST):
    - activation_ticks: 6   → S'active quand profit > 6t
    - distance_ticks: 4     → SL suit à 4t du high
    - Simple trailing (pas de paliers)
    """
    
    # === ACTIVATION ===
    enabled: bool = True
    activation_ticks_es: int = 6  # Active trailing après +6t de profit
    activation_ticks_nq: int = 6  # Idem pour NQ
    
    # === DISTANCE ===
    distance_ticks_es: int = 4  # SL suit le prix à 4t de distance
    distance_ticks_nq: int = 4  # Idem pour NQ
    
    # === MODE ===
    use_progressive: bool = False  # Désactiver paliers progressifs
    only_move_up: bool = True  # SL ne peut que monter (LONG) ou descendre (SHORT)


# =============================================================================
# CONFIGURATION OBSTACLE DETECTION
# =============================================================================

OBSTACLE_LEVELS_BY_SCORE = {
    # SCORE 3 - FORTS (bloquent souvent le prix)
    3: [
        'call_resistance', 'put_support', 'gamma_wall_level',
        'hvl', 'gex_1', 'gex_2', '1d_max', '1d_min', 'vpoc',
    ],
    
    # SCORE 2 - MOYENS (peuvent bloquer)
    2: [
        'hvl_0dte', 'gamma_wall_0dte', 'gex_3', 'gex_4', 'gex_5',
        'vwap', 'vah', 'val', 'ibh', 'ibl', 'vwap_up1', 'vwap_dn1',
    ],
    
    # SCORE 1 - FAIBLES (rarement bloquants)
    1: [
        'blind_spot_1', 'blind_spot_2', 'blind_spot_3',
        'gex_6', 'gex_7', 'gex_8',
    ],
}


# =============================================================================
# FONCTIONS DE VALIDATION
# =============================================================================

def should_take_trade(
    level_name: str,
    distance_ticks: float,
    delta: float,
    mia_score: float,
    direction: str,
    config: V17UltimateConfig = None
) -> tuple:
    """
    Valide si un trade doit être pris selon la config V17_ULTIMATE.
    
    Returns:
        (bool, str): (prendre_trade, raison_si_refus)
    """
    if config is None:
        config = V17UltimateConfig()
    
    # 1. Check niveau
    if level_name in config.levels_to_avoid:
        return False, f"Niveau {level_name} à éviter"
    
    if level_name not in config.profitable_levels:
        return False, f"Niveau {level_name} non profitable"
    
    # 2. Check distance
    if distance_ticks < config.min_distance_ticks:
        return False, f"Distance {distance_ticks:.1f}t < min {config.min_distance_ticks}t"
    
    if distance_ticks > config.max_distance_ticks:
        return False, f"Distance {distance_ticks:.1f}t > max {config.max_distance_ticks}t"
    
    # 3. Check Delta/MIA
    if config.use_delta_filter:
        if direction == 'LONG':
            if delta < config.delta_threshold:
                return False, f"Delta {delta:.0f} < {config.delta_threshold} (LONG)"
            if mia_score < config.mia_threshold:
                return False, f"MIA {mia_score:.2f} < {config.mia_threshold} (LONG)"
        else:  # SHORT
            if delta > -config.delta_threshold:
                return False, f"Delta {delta:.0f} > -{config.delta_threshold} (SHORT)"
            if mia_score > (1 - config.mia_threshold):
                return False, f"MIA {mia_score:.2f} > {1-config.mia_threshold} (SHORT)"
    
    return True, "OK"


def calculate_trailing_sl(
    entry_price: float,
    current_high: float,  # High depuis entry (LONG) ou Low depuis entry (SHORT)
    direction: str,
    current_sl: float,
    tick_size: float,
    config: TrailingStopConfig = None
) -> tuple:
    """
    Calcule le nouveau SL avec trailing stop.
    
    Returns:
        (float, bool): (nouveau_sl, sl_modifié)
    """
    if config is None:
        config = TrailingStopConfig()
    
    if not config.enabled:
        return current_sl, False
    
    activation = config.activation_ticks_es
    distance = config.distance_ticks_es
    
    # Calcul excursion favorable
    if direction == 'LONG':
        excursion = (current_high - entry_price) / tick_size
    else:
        excursion = (entry_price - current_high) / tick_size
    
    # Pas encore activé?
    if excursion < activation:
        return current_sl, False
    
    # Calculer nouveau SL
    if direction == 'LONG':
        new_sl = current_high - (distance * tick_size)
        if config.only_move_up and new_sl <= current_sl:
            return current_sl, False
        return new_sl, True
    else:  # SHORT
        new_sl = current_high + (distance * tick_size)
        if config.only_move_up and new_sl >= current_sl:
            return current_sl, False
        return new_sl, True


# =============================================================================
# CODE À INTÉGRER DANS LE BOT
# =============================================================================

"""
=============================================================================
INTÉGRATION DANS launch_production_CLEAN_v2.py
=============================================================================

1. MODIFIER LES FLAGS (ligne ~259):
   
   # AVANT:
   enable_trailing_stop: bool = False  # 🔴 DÉSACTIVÉ
   
   # APRÈS:
   enable_trailing_stop: bool = True  # 🟢 ACTIVÉ !

2. MODIFIER LES PARAMÈTRES TRAILING (trailing_stop_manager.py ligne ~79):
   
   # AVANT:
   trailing_enabled: bool = False
   activation_es: int = 28
   distance_es: int = 8
   
   # APRÈS:
   trailing_enabled: bool = True  # 🟢 ACTIVÉ !
   activation_es: int = 6  # 🔥 6 au lieu de 28 !
   distance_es: int = 4  # 🔥 4 au lieu de 8 !
   use_progressive: bool = False  # Désactiver paliers

3. AJOUTER FILTRE NIVEAUX (signal_generator.py):
   
   from config.v17_ultimate_config import V17UltimateConfig, should_take_trade
   
   config = V17UltimateConfig()
   
   # Dans generate_signal():
   ok, reason = should_take_trade(level_name, distance, delta, mia, direction, config)
   if not ok:
       logger.info(f"Trade rejeté V17: {reason}")
       return None

4. AJOUTER FILTRE DISTANCE (signal_generator.py):
   
   # Vérifier distance 5-8 ticks
   if distance_ticks < 5 or distance_ticks > 8:
       return None

5. AJOUTER FILTRE DELTA (signal_generator.py):
   
   if direction == 'LONG':
       if delta < 150 or mia_score < 0.52:
           return None
   else:
       if delta > -150 or mia_score > 0.48:
           return None
"""


# =============================================================================
# AFFICHAGE CONFIG
# =============================================================================

if __name__ == "__main__":
    config = V17UltimateConfig()
    trailing = TrailingStopConfig()
    
    print("=" * 80)
    print("   MIA IA SYSTEM - V17_ULTIMATE CONFIGURATION")
    print("=" * 80)
    
    print(f"""
   📊 RÉSULTATS ATTENDUS:
   ├─ Win Rate: 85-90%
   ├─ P&L: +$12,000-16,000 par période de test
   └─ Sessions: US_MORNING (89.5% WR), POWER_HOUR (82.3% WR)
   
   🎯 TP/SL:
   ├─ ES: TP={config.tp_ticks_es}t, SL={config.sl_ticks_es}t
   └─ NQ: TP={config.tp_ticks_nq}t, SL={config.sl_ticks_nq}t
   
   📏 DISTANCE:
   └─ {config.min_distance_ticks}-{config.max_distance_ticks} ticks du niveau
   
   🔒 FILTRES:
   ├─ Delta: > {config.delta_threshold} (LONG), < -{config.delta_threshold} (SHORT)
   └─ MIA: > {config.mia_threshold} (LONG), < {1-config.mia_threshold} (SHORT)
   
   📈 TRAILING STOP (CORRIGÉ!):
   ├─ Activé: {trailing.enabled}
   ├─ Activation: +{trailing.activation_ticks_es}t (au lieu de 28t!)
   ├─ Distance: {trailing.distance_ticks_es}t (au lieu de 8t!)
   └─ Progressif: {trailing.use_progressive}
   
   📍 OBSTACLE DETECTION:
   ├─ Activé: {config.use_obstacle_detection}
   ├─ Score min: {config.min_obstacle_score}
   └─ Buffer: {config.obstacle_buffer_ticks}t
   
   ✅ NIVEAUX PROFITABLES:
   {', '.join(config.profitable_levels)}
   
   🔴 NIVEAUX À ÉVITER:
   {', '.join(config.levels_to_avoid)}
    """)
    
    print("=" * 80)
    
    # Test validation
    print("\n   🧪 TEST VALIDATION:")
    test_cases = [
        ('vwap_dn1', 6.5, 200, 0.58, 'LONG'),
        ('gex_2', 7.0, 300, 0.60, 'LONG'),
        ('vwap', 3.0, 200, 0.58, 'LONG'),
        ('1d_max', 7.0, 50, 0.58, 'LONG'),
        ('put_support', 6.0, -200, 0.42, 'SHORT'),
    ]
    
    for level, dist, delta, mia, direction in test_cases:
        ok, reason = should_take_trade(level, dist, delta, mia, direction, config)
        emoji = "✅" if ok else "❌"
        print(f"   {emoji} {level} @ {dist}t, Δ={delta}, MIA={mia}, {direction} → {reason}")
    
    print("\n" + "=" * 80)
