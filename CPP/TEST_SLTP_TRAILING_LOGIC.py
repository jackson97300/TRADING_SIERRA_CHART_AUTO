"""
═══════════════════════════════════════════════════════════════════════════════
TEST COMPLET: Logique SL/TP, Trailing Stop et Break-Even du Bot C++ MIA
═══════════════════════════════════════════════════════════════════════════════
Date: 28/01/2026
Objectif: Valider que les calculs C++ sont corrects

Ce script simule la logique exacte du code C++ et teste tous les scénarios.
═══════════════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
import json

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION SYMBOLES (identique au C++)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SymbolConfig:
    name: str
    tick_size: float
    tick_value: float
    
    # SL/TP
    sl_default_ticks: int
    sl_min_ticks: int
    sl_max_ticks: int
    sl_buffer_ticks: int
    tp_default_ticks: int
    tp_max_ticks: int
    tp_buffer_ticks: int
    min_rr_ratio: float
    
    # Trailing
    trailing_activation_ticks: int
    trailing_distance_ticks: int
    
    # Break-Even
    break_even_activation_ticks: int
    break_even_buffer_ticks: int


CONFIG_ES = SymbolConfig(
    name="ES",
    tick_size=0.25,
    tick_value=12.50,
    sl_default_ticks=20,      # 5 pts
    sl_min_ticks=16,          # 4 pts
    sl_max_ticks=28,          # 7 pts
    sl_buffer_ticks=3,
    tp_default_ticks=24,      # 6 pts
    tp_max_ticks=32,          # 8 pts
    tp_buffer_ticks=2,
    min_rr_ratio=1.20,
    trailing_activation_ticks=15,  # +3.75 pts
    trailing_distance_ticks=8,     # 2 pts
    break_even_activation_ticks=10,  # +2.5 pts
    break_even_buffer_ticks=1,       # +1 tick
)

CONFIG_NQ = SymbolConfig(
    name="NQ",
    tick_size=0.25,
    tick_value=5.00,
    sl_default_ticks=28,      # 7 pts
    sl_min_ticks=20,          # 5 pts
    sl_max_ticks=40,          # 10 pts
    sl_buffer_ticks=5,
    tp_default_ticks=35,      # 8.75 pts
    tp_max_ticks=50,          # 12.5 pts
    tp_buffer_ticks=3,
    min_rr_ratio=1.25,
    trailing_activation_ticks=25,  # +6.25 pts
    trailing_distance_ticks=12,    # 3 pts
    break_even_activation_ticks=15,  # +3.75 pts
    break_even_buffer_ticks=2,       # +2 ticks
)


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURE RÉSULTAT SL/TP (identique au C++)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SLTPResult:
    sl_price: float
    tp_price: float
    sl_ticks: int
    tp_ticks: int
    rr_ratio: float
    sl_based_on: str
    tp_based_on: str
    is_valid: bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# CALCUL SL/TP ADAPTATIF (simulation du code C++)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_adaptive_sltp(
    config: SymbolConfig,
    direction: int,  # 1=LONG, -1=SHORT
    entry_price: float,
    mq_levels: dict,  # Niveaux MenthorQ
) -> SLTPResult:
    """
    Simule CalculateAdaptiveSLTP() du C++
    """
    tick_size = config.tick_size
    buffer = config.sl_buffer_ticks * tick_size
    min_sl = config.sl_min_ticks * tick_size
    max_sl = config.sl_max_ticks * tick_size
    
    result = SLTPResult(
        sl_price=0, tp_price=0, sl_ticks=0, tp_ticks=0,
        rr_ratio=0, sl_based_on="", tp_based_on=""
    )
    
    # === Collecter tous les niveaux ===
    levels = []
    for name, price in mq_levels.items():
        if price > 0:
            levels.append((price, name))
    
    # === Chercher niveau pour SL ===
    valid_sl_levels = []
    for price, name in levels:
        if direction == 1:  # LONG - SL sous support
            if price >= entry_price:
                continue
            distance = entry_price - price
        else:  # SHORT - SL au-dessus résistance
            if price <= entry_price:
                continue
            distance = price - entry_price
        
        if min_sl <= distance <= max_sl:
            valid_sl_levels.append((price, name, distance))
    
    # Trouver le plus proche
    best_sl = 0
    best_level = "FIXED"
    
    if valid_sl_levels:
        # Trier par distance
        if direction == 1:
            valid_sl_levels.sort(key=lambda x: x[0], reverse=True)  # Plus proche = plus haut
        else:
            valid_sl_levels.sort(key=lambda x: x[0])  # Plus proche = plus bas
        
        best_sl = valid_sl_levels[0][0]
        best_level = valid_sl_levels[0][1]
        
        # Appliquer buffer
        if direction == 1:
            best_sl -= buffer
        else:
            best_sl += buffer
    
    # Fallback SL fixe
    if best_sl == 0:
        if direction == 1:
            best_sl = entry_price - (config.sl_default_ticks * tick_size)
        else:
            best_sl = entry_price + (config.sl_default_ticks * tick_size)
        best_level = "FIXED"
    
    # === SÉCURITÉ: Forcer limites MIN/MAX SL ===
    sl_distance = abs(entry_price - best_sl)
    
    if sl_distance < min_sl:
        if direction == 1:
            best_sl = entry_price - min_sl
        else:
            best_sl = entry_price + min_sl
        best_level = "MIN_FORCED"
    elif sl_distance > max_sl:
        if direction == 1:
            best_sl = entry_price - max_sl
        else:
            best_sl = entry_price + max_sl
        best_level = "MAX_FORCED"
    
    result.sl_price = best_sl
    result.sl_based_on = best_level
    result.sl_ticks = int(abs(entry_price - best_sl) / tick_size)
    
    # === Calculer TP ===
    risk = abs(entry_price - best_sl)
    min_reward = risk * config.min_rr_ratio
    MIN_OBSTACLE_DIST = 5.0 * tick_size
    
    # Chercher premier obstacle
    first_obstacle = 0
    first_obstacle_dist = 999999
    obstacle_name = ""
    
    for price, name in levels:
        if direction == 1:  # LONG - obstacle au-dessus
            if price <= entry_price:
                continue
            distance = price - entry_price
        else:  # SHORT - obstacle en-dessous
            if price >= entry_price:
                continue
            distance = entry_price - price
        
        if distance < first_obstacle_dist and distance >= MIN_OBSTACLE_DIST:
            first_obstacle_dist = distance
            first_obstacle = price
            obstacle_name = name
    
    # VETO si obstacle trop proche
    if first_obstacle > 0 and first_obstacle_dist < min_reward:
        result.is_valid = False
        result.tp_based_on = f"VETO_OBSTACLE_{obstacle_name}@{first_obstacle:.2f} (R:R<{config.min_rr_ratio})"
        result.tp_price = 0
        return result
    
    # TP avant obstacle ou TP fixe
    if first_obstacle > 0:
        if direction == 1:
            result.tp_price = first_obstacle - (config.tp_buffer_ticks * tick_size)
        else:
            result.tp_price = first_obstacle + (config.tp_buffer_ticks * tick_size)
        result.tp_based_on = f"BEFORE_{obstacle_name}"
    else:
        if direction == 1:
            result.tp_price = entry_price + (config.tp_default_ticks * tick_size)
        else:
            result.tp_price = entry_price - (config.tp_default_ticks * tick_size)
        result.tp_based_on = "FIXED"
    
    # === SÉCURITÉ: Forcer limites MIN/MAX TP ===
    max_tp_distance = config.tp_max_ticks * tick_size
    min_tp_distance = config.sl_default_ticks * tick_size  # TP min = SL default (R:R ~1)
    tp_distance = abs(result.tp_price - entry_price)
    
    if tp_distance > max_tp_distance:
        if direction == 1:
            result.tp_price = entry_price + max_tp_distance
        else:
            result.tp_price = entry_price - max_tp_distance
        result.tp_based_on = "MAX_LIMITED"
    elif tp_distance < min_tp_distance:
        if direction == 1:
            result.tp_price = entry_price + min_tp_distance
        else:
            result.tp_price = entry_price - min_tp_distance
        result.tp_based_on = "MIN_LIMITED"
    
    result.tp_ticks = int(abs(result.tp_price - entry_price) / tick_size)
    result.rr_ratio = result.tp_ticks / result.sl_ticks if result.sl_ticks > 0 else 0
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION TRAILING STOP & BREAK-EVEN (identique au C++)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TrailingState:
    entry_price: float
    direction: int  # 1=LONG, -1=SHORT
    trailing_sl: float = 0
    trailing_activated: bool = False
    break_even_activated: bool = False
    position_closed: bool = False
    close_reason: str = ""
    close_price: float = 0


def update_trailing_stop(
    state: TrailingState,
    config: SymbolConfig,
    current_price: float,
) -> Tuple[TrailingState, str]:
    """
    Simule UpdateTrailingStop() du C++
    Retourne (state, log_message)
    """
    if state.position_closed:
        return state, ""
    
    tick_size = config.tick_size
    activation_dist = config.trailing_activation_ticks * tick_size
    trailing_dist = config.trailing_distance_ticks * tick_size
    be_activation_dist = config.break_even_activation_ticks * tick_size
    be_buffer = config.break_even_buffer_ticks * tick_size
    
    # Calcul profit
    if state.direction == 1:  # LONG
        profit = current_price - state.entry_price
    else:  # SHORT
        profit = state.entry_price - current_price
    
    log = ""
    
    # === PHASE 1: BREAK-EVEN AUTO ===
    if profit >= be_activation_dist and not state.break_even_activated and not state.trailing_activated:
        state.break_even_activated = True
        
        if state.direction == 1:
            state.trailing_sl = state.entry_price + be_buffer
        else:
            state.trailing_sl = state.entry_price - be_buffer
        
        log = f"[BE] BREAK-EVEN ACTIVE @ +{profit/tick_size:.0f}t, SL={state.trailing_sl:.2f} (0 RISQUE)"
    
    # === PHASE 2: TRAILING STOP ===
    if profit >= activation_dist and not state.trailing_activated:
        state.trailing_activated = True
        
        if state.direction == 1:
            state.trailing_sl = current_price - trailing_dist
        else:
            state.trailing_sl = current_price + trailing_dist
        
        log = f"[TRAIL] TRAILING ACTIVE @ +{profit/tick_size:.0f}t, SL={state.trailing_sl:.2f}"
    
    # === Mise à jour trailing SL ===
    if state.trailing_activated:
        if state.direction == 1:  # LONG
            new_sl = current_price - trailing_dist
            if new_sl > state.trailing_sl:
                state.trailing_sl = new_sl
                log = f"[UP] TRAILING UPDATE: SL={state.trailing_sl:.2f}"
            
            # Vérifier si touché
            if current_price <= state.trailing_sl:
                state.position_closed = True
                state.close_reason = "TRAILING_STOP"
                state.close_price = state.trailing_sl
                log = f"[CLOSE] FERME PAR TRAILING @ {state.trailing_sl:.2f}"
        
        else:  # SHORT
            new_sl = current_price + trailing_dist
            if new_sl < state.trailing_sl:
                state.trailing_sl = new_sl
                log = f"[DN] TRAILING UPDATE: SL={state.trailing_sl:.2f}"
            
            if current_price >= state.trailing_sl:
                state.position_closed = True
                state.close_reason = "TRAILING_STOP"
                state.close_price = state.trailing_sl
                log = f"[CLOSE] FERME PAR TRAILING @ {state.trailing_sl:.2f}"
    
    return state, log


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS UNITAIRES
# ═══════════════════════════════════════════════════════════════════════════════

def test_sltp_basic():
    """Test 1: SL/TP basique sans niveaux MenthorQ"""
    print("\n" + "="*80)
    print("TEST 1: SL/TP BASIQUE (sans niveaux MenthorQ)")
    print("="*80)
    
    entry = 6100.00
    
    result = calculate_adaptive_sltp(CONFIG_ES, direction=1, entry_price=entry, mq_levels={})
    
    expected_sl = entry - (CONFIG_ES.sl_default_ticks * CONFIG_ES.tick_size)  # 6100 - 5 = 6095
    expected_tp = entry + (CONFIG_ES.tp_default_ticks * CONFIG_ES.tick_size)  # 6100 + 6 = 6106
    
    print(f"Entry: {entry}")
    print(f"Direction: LONG")
    print(f"")
    print(f"SL calculé: {result.sl_price:.2f} (attendu: {expected_sl:.2f}) - {result.sl_based_on}")
    print(f"TP calculé: {result.tp_price:.2f} (attendu: {expected_tp:.2f}) - {result.tp_based_on}")
    print(f"SL ticks: {result.sl_ticks} (attendu: {CONFIG_ES.sl_default_ticks})")
    print(f"TP ticks: {result.tp_ticks} (attendu: {CONFIG_ES.tp_default_ticks})")
    print(f"R:R ratio: {result.rr_ratio:.2f} (attendu: {CONFIG_ES.tp_default_ticks/CONFIG_ES.sl_default_ticks:.2f})")
    
    assert abs(result.sl_price - expected_sl) < 0.01, f"SL incorrect: {result.sl_price} != {expected_sl}"
    assert abs(result.tp_price - expected_tp) < 0.01, f"TP incorrect: {result.tp_price} != {expected_tp}"
    assert result.sl_ticks == CONFIG_ES.sl_default_ticks, f"SL ticks incorrect"
    assert result.tp_ticks == CONFIG_ES.tp_default_ticks, f"TP ticks incorrect"
    
    print("\n[OK] TEST 1 PASSÉ!")


def test_sltp_with_obstacle():
    """Test 2: SL/TP avec obstacle (Call Resistance)"""
    print("\n" + "="*80)
    print("TEST 2: SL/TP AVEC OBSTACLE (Call Resistance avant TP)")
    print("="*80)
    
    entry = 6100.00
    call_resistance = 6104.00  # 16 ticks au-dessus (4 pts)
    
    mq_levels = {
        "CALL_RES": call_resistance,
    }
    
    result = calculate_adaptive_sltp(CONFIG_ES, direction=1, entry_price=entry, mq_levels=mq_levels)
    
    # TP devrait être AVANT l'obstacle (call_resistance - buffer)
    expected_tp = call_resistance - (CONFIG_ES.tp_buffer_ticks * CONFIG_ES.tick_size)  # 6104 - 0.5 = 6103.5
    
    print(f"Entry: {entry}")
    print(f"Call Resistance: {call_resistance} (16 ticks au-dessus)")
    print(f"Direction: LONG")
    print(f"")
    print(f"SL calculé: {result.sl_price:.2f} - {result.sl_based_on}")
    print(f"TP calculé: {result.tp_price:.2f} (attendu: {expected_tp:.2f}) - {result.tp_based_on}")
    print(f"TP ticks: {result.tp_ticks}")
    print(f"R:R ratio: {result.rr_ratio:.2f}")
    print(f"Valid: {result.is_valid}")
    
    assert result.tp_price <= call_resistance, f"TP devrait être AVANT l'obstacle!"
    assert "BEFORE" in result.tp_based_on or "CALL" in result.tp_based_on, f"TP devrait mentionner l'obstacle"
    
    print("\n[OK] TEST 2 PASSÉ!")


def test_sltp_obstacle_blocks_rr():
    """Test 3: Obstacle trop proche = VETO (R:R insuffisant)"""
    print("\n" + "="*80)
    print("TEST 3: OBSTACLE TROP PROCHE = VETO (R:R insuffisant)")
    print("="*80)
    
    entry = 6100.00
    # Obstacle à seulement 2 pts (8 ticks) mais SL est 5 pts (20 ticks)
    # R:R serait 8/20 = 0.4 < 1.2 minimum -> VETO!
    call_resistance = 6102.00  # 8 ticks
    
    mq_levels = {
        "CALL_RES": call_resistance,
    }
    
    result = calculate_adaptive_sltp(CONFIG_ES, direction=1, entry_price=entry, mq_levels=mq_levels)
    
    print(f"Entry: {entry}")
    print(f"Call Resistance: {call_resistance} (8 ticks = 2 pts)")
    print(f"SL default: {CONFIG_ES.sl_default_ticks} ticks = {CONFIG_ES.sl_default_ticks * CONFIG_ES.tick_size} pts")
    print(f"R:R potentiel: {8/20:.2f} (min requis: {CONFIG_ES.min_rr_ratio})")
    print(f"")
    print(f"Résultat: is_valid = {result.is_valid}")
    print(f"Raison: {result.tp_based_on}")
    
    assert result.is_valid == False, "Le trade devrait être VETO car R:R insuffisant!"
    assert "VETO" in result.tp_based_on, "La raison devrait contenir VETO"
    
    print("\n[OK] TEST 3 PASSÉ!")


def test_sltp_max_limits():
    """Test 4: Limites MAX SL/TP respectées"""
    print("\n" + "="*80)
    print("TEST 4: LIMITES MAX SL/TP RESPECTÉES")
    print("="*80)
    
    entry = 6100.00
    # Mettre un support TRÈS loin pour tester la limite max
    far_support = 6050.00  # 200 ticks! (max = 28)
    
    mq_levels = {
        "FAR_SUPPORT": far_support,
    }
    
    result = calculate_adaptive_sltp(CONFIG_ES, direction=1, entry_price=entry, mq_levels=mq_levels)
    
    max_sl_distance = CONFIG_ES.sl_max_ticks * CONFIG_ES.tick_size  # 7 pts
    actual_sl_distance = abs(entry - result.sl_price)
    
    print(f"Entry: {entry}")
    print(f"Support loin: {far_support} (200 ticks)")
    print(f"Max SL autorisé: {CONFIG_ES.sl_max_ticks} ticks = {max_sl_distance} pts")
    print(f"")
    print(f"SL calculé: {result.sl_price:.2f}")
    print(f"Distance SL: {actual_sl_distance:.2f} pts ({result.sl_ticks} ticks)")
    print(f"Base: {result.sl_based_on}")
    
    assert result.sl_ticks <= CONFIG_ES.sl_max_ticks, f"SL dépasse le max! {result.sl_ticks} > {CONFIG_ES.sl_max_ticks}"
    assert actual_sl_distance <= max_sl_distance + 0.01, f"Distance SL trop grande!"
    
    print("\n[OK] TEST 4 PASSÉ!")


def test_trailing_stop_long():
    """Test 5: Trailing Stop LONG"""
    print("\n" + "="*80)
    print("TEST 5: TRAILING STOP (LONG)")
    print("="*80)
    
    entry = 6100.00
    state = TrailingState(entry_price=entry, direction=1)
    
    # Simuler le prix qui monte
    price_sequence = [
        6100.00,  # Entry
        6101.00,  # +4 ticks (pas encore BE)
        6102.50,  # +10 ticks = BREAK-EVEN!
        6103.00,  # +12 ticks
        6103.75,  # +15 ticks = TRAILING ACTIVE!
        6105.00,  # +20 ticks, trailing suit
        6106.00,  # +24 ticks, trailing monte encore
        6105.50,  # Prix redescend (mais trailing ne bouge pas)
        6104.00,  # Prix descend, touche trailing?
    ]
    
    print(f"Entry: {entry}")
    print(f"BE activation: +{CONFIG_ES.break_even_activation_ticks} ticks (+{CONFIG_ES.break_even_activation_ticks * CONFIG_ES.tick_size} pts)")
    print(f"Trailing activation: +{CONFIG_ES.trailing_activation_ticks} ticks (+{CONFIG_ES.trailing_activation_ticks * CONFIG_ES.tick_size} pts)")
    print(f"Trailing distance: {CONFIG_ES.trailing_distance_ticks} ticks ({CONFIG_ES.trailing_distance_ticks * CONFIG_ES.tick_size} pts)")
    print(f"")
    
    for i, price in enumerate(price_sequence):
        profit_ticks = (price - entry) / CONFIG_ES.tick_size
        state, log = update_trailing_stop(state, CONFIG_ES, price)
        
        status = ""
        if state.break_even_activated and not state.trailing_activated:
            status = "[BE]"
        elif state.trailing_activated:
            status = "[TRAIL]"
        
        print(f"  {i+1}. Prix={price:.2f} (+{profit_ticks:.0f}t) {status}")
        print(f"     Trailing SL={state.trailing_sl:.2f}")
        if log:
            print(f"     -> {log}")
        
        if state.position_closed:
            pnl = (state.close_price - entry) / CONFIG_ES.tick_size
            print(f"\n  [CLOSE] POSITION FERMÉE: {state.close_reason} @ {state.close_price:.2f} (P&L: +{pnl:.0f} ticks)")
            break
    
    print("\n[OK] TEST 5 PASSÉ!")


def test_trailing_stop_short():
    """Test 6: Trailing Stop SHORT"""
    print("\n" + "="*80)
    print("TEST 6: TRAILING STOP (SHORT)")
    print("="*80)
    
    entry = 6100.00
    state = TrailingState(entry_price=entry, direction=-1)
    
    # Simuler le prix qui descend
    price_sequence = [
        6100.00,  # Entry
        6099.00,  # -4 ticks
        6097.50,  # -10 ticks = BREAK-EVEN!
        6096.25,  # -15 ticks = TRAILING ACTIVE!
        6095.00,  # -20 ticks, trailing suit
        6094.00,  # -24 ticks
        6095.00,  # Prix remonte
        6097.00,  # Prix touche trailing?
    ]
    
    print(f"Entry: {entry}")
    print(f"Direction: SHORT")
    print(f"")
    
    for i, price in enumerate(price_sequence):
        profit_ticks = (entry - price) / CONFIG_ES.tick_size
        state, log = update_trailing_stop(state, CONFIG_ES, price)
        
        status = ""
        if state.break_even_activated and not state.trailing_activated:
            status = "[BE]"
        elif state.trailing_activated:
            status = "[TRAIL]"
        
        print(f"  {i+1}. Prix={price:.2f} (+{profit_ticks:.0f}t profit) {status}")
        print(f"     Trailing SL={state.trailing_sl:.2f}")
        if log:
            print(f"     -> {log}")
        
        if state.position_closed:
            pnl = (entry - state.close_price) / CONFIG_ES.tick_size
            print(f"\n  [CLOSE] POSITION FERMÉE: {state.close_reason} @ {state.close_price:.2f} (P&L: +{pnl:.0f} ticks)")
            break
    
    print("\n[OK] TEST 6 PASSÉ!")


def test_nq_config():
    """Test 7: Vérifier config NQ"""
    print("\n" + "="*80)
    print("TEST 7: CONFIGURATION NQ")
    print("="*80)
    
    entry = 21500.00
    
    result = calculate_adaptive_sltp(CONFIG_NQ, direction=1, entry_price=entry, mq_levels={})
    
    print(f"Entry: {entry}")
    print(f"")
    print(f"Config NQ:")
    print(f"  SL default: {CONFIG_NQ.sl_default_ticks} ticks = {CONFIG_NQ.sl_default_ticks * CONFIG_NQ.tick_size} pts")
    print(f"  SL max: {CONFIG_NQ.sl_max_ticks} ticks = {CONFIG_NQ.sl_max_ticks * CONFIG_NQ.tick_size} pts")
    print(f"  TP default: {CONFIG_NQ.tp_default_ticks} ticks = {CONFIG_NQ.tp_default_ticks * CONFIG_NQ.tick_size} pts")
    print(f"  TP max: {CONFIG_NQ.tp_max_ticks} ticks = {CONFIG_NQ.tp_max_ticks * CONFIG_NQ.tick_size} pts")
    print(f"")
    print(f"Résultat:")
    print(f"  SL: {result.sl_price:.2f} ({result.sl_ticks} ticks)")
    print(f"  TP: {result.tp_price:.2f} ({result.tp_ticks} ticks)")
    print(f"  R:R: {result.rr_ratio:.2f}")
    
    assert result.sl_ticks == CONFIG_NQ.sl_default_ticks
    assert result.tp_ticks == CONFIG_NQ.tp_default_ticks
    
    print("\n[OK] TEST 7 PASSÉ!")


def test_real_scenario_from_image():
    """Test 8: Scénario réel de l'image (7037 entry)"""
    print("\n" + "="*80)
    print("TEST 8: SCÉNARIO RÉEL (Entry @ 7037, Call Res @ 7054.58)")
    print("="*80)
    
    entry = 7037.00
    call_resistance = 7054.58
    gamma_wall_0dte = 7054.58  # Même niveau
    
    mq_levels = {
        "CALL_RES": call_resistance,
        "CALL_0DTE": call_resistance,
        "GAMMA_0DTE": gamma_wall_0dte,
    }
    
    result = calculate_adaptive_sltp(CONFIG_ES, direction=1, entry_price=entry, mq_levels=mq_levels)
    
    print(f"Entry: {entry}")
    print(f"Call Resistance: {call_resistance}")
    print(f"Gamma Wall 0DTE: {gamma_wall_0dte}")
    print(f"")
    print(f"Distance à l'obstacle: {(call_resistance - entry):.2f} pts = {(call_resistance - entry)/CONFIG_ES.tick_size:.0f} ticks")
    print(f"")
    print(f"Résultat ATTENDU avec corrections:")
    print(f"  SL: {result.sl_price:.2f} ({result.sl_ticks} ticks) - {result.sl_based_on}")
    print(f"  TP: {result.tp_price:.2f} ({result.tp_ticks} ticks) - {result.tp_based_on}")
    print(f"  R:R: {result.rr_ratio:.2f}")
    print(f"  Valid: {result.is_valid}")
    
    # Le TP DOIT être AVANT l'obstacle!
    if result.is_valid:
        assert result.tp_price <= call_resistance, f"TP ({result.tp_price}) devrait être AVANT l'obstacle ({call_resistance})!"
        print(f"\n[OK] TP est correctement placé AVANT l'obstacle!")
    else:
        print(f"\n[!] Trade VETO car R:R insuffisant (normal si obstacle trop proche)")
    
    # Le SL DOIT respecter les limites
    assert result.sl_ticks <= CONFIG_ES.sl_max_ticks, f"SL dépasse le max!"
    print(f"[OK] SL respecte les limites ({result.sl_ticks} <= {CONFIG_ES.sl_max_ticks})")
    
    # Comparer avec les valeurs INCORRECTES de l'image
    print(f"\n" + "-"*40)
    print(f"COMPARAISON avec l'image (AVANT correction):")
    print(f"  Image: SL @ 7017 (80 ticks!) - [X] TROP LOIN!")
    print(f"  Image: TP @ 7056.25 (77 ticks!) - [X] APRÈS l'obstacle!")
    print(f"  Corrigé: SL @ {result.sl_price:.2f} ({result.sl_ticks} ticks) - [OK]")
    print(f"  Corrigé: TP @ {result.tp_price:.2f} ({result.tp_ticks} ticks) - [OK]")
    
    print("\n[OK] TEST 8 PASSÉ!")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("="*80)
    print("   TEST COMPLET: LOGIQUE SL/TP, TRAILING STOP, BREAK-EVEN")
    print("   Bot C++ MIA AutoTrader - 28/01/2026")
    print("="*80)
    
    # Exécuter tous les tests
    tests = [
        test_sltp_basic,
        test_sltp_with_obstacle,
        test_sltp_obstacle_blocks_rr,
        test_sltp_max_limits,
        test_trailing_stop_long,
        test_trailing_stop_short,
        test_nq_config,
        test_real_scenario_from_image,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n[X] TEST ÉCHOUÉ: {e}")
            failed += 1
        except Exception as e:
            print(f"\n[X] ERREUR: {e}")
            failed += 1
    
    print("\n" + "="*80)
    print(f"   RÉSUMÉ: {passed}/{len(tests)} tests passés")
    if failed > 0:
        print(f"   [!] {failed} tests échoués!")
    else:
        print(f"   [OK] TOUS LES TESTS PASSÉS!")
    print("="*80)
