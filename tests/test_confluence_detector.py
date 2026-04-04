#!/usr/bin/env python3
"""
TEST CONFLUENCE DETECTOR v2
===========================
Validation de la logique de detection de confluence MenthorQ

Tests:
1. Cluster simple (2 niveaux proches)
2. Cluster fort (3+ niveaux avec poids eleves)
3. Niveaux disperses (pas de confluence)
4. Niveaux identiques (deduplication)
5. Prix dans/hors zone de confluence
"""

from dataclasses import dataclass
from typing import List, Tuple
import math


@dataclass
class LevelInfo:
    price: float
    weight: int
    level_type: str


@dataclass
class ConfluenceResult:
    num_levels: int = 0
    zone_center: float = 0
    zone_width_ticks: float = 0
    strength: float = 0
    has_confluence: bool = False
    weighted_score: int = 0
    distance_to_price: float = 0
    levels_desc: str = ""


def detect_confluence(
    levels: List[LevelInfo],
    current_price: float,
    tick_size: float,
    cluster_max_ticks: float = 10.0
) -> ConfluenceResult:
    """
    Detecte les zones de confluence (niveaux proches ENTRE EUX)

    Args:
        levels: Liste des niveaux avec poids
        current_price: Prix actuel
        tick_size: Taille du tick
        cluster_max_ticks: Distance max entre niveaux pour former un cluster

    Returns:
        ConfluenceResult avec details de la confluence
    """
    result = ConfluenceResult()

    if len(levels) < 2:
        return result

    # Trier par prix
    sorted_levels = sorted(levels, key=lambda x: x.price)

    # Distance max pour cluster
    cluster_distance = cluster_max_ticks * tick_size

    # Trouver le meilleur cluster
    best_start = 0
    best_end = 0
    best_weight = 0

    for i in range(len(sorted_levels)):
        cluster_weight = sorted_levels[i].weight
        j = i

        # Etendre tant que niveaux proches
        while j + 1 < len(sorted_levels) and \
              (sorted_levels[j + 1].price - sorted_levels[i].price) <= cluster_distance:
            j += 1
            cluster_weight += sorted_levels[j].weight

        # Garder le meilleur (au moins 2 niveaux)
        if j > i and cluster_weight > best_weight:
            best_weight = cluster_weight
            best_start = i
            best_end = j

    # Analyser le meilleur cluster
    if best_weight >= 4 and best_end > best_start:
        result.has_confluence = True
        result.num_levels = best_end - best_start + 1
        result.weighted_score = best_weight

        # Centre pondere
        weighted_sum = 0
        total_weight = 0
        min_price = sorted_levels[best_start].price
        max_price = sorted_levels[best_end].price

        desc_parts = []
        for i in range(best_start, best_end + 1):
            weighted_sum += sorted_levels[i].price * sorted_levels[i].weight
            total_weight += sorted_levels[i].weight
            desc_parts.append(f"{sorted_levels[i].level_type}@{sorted_levels[i].price:.0f}")

        result.zone_center = weighted_sum / total_weight
        result.zone_width_ticks = (max_price - min_price) / tick_size
        result.distance_to_price = abs(current_price - result.zone_center) / tick_size
        result.levels_desc = " ".join(desc_parts)
        result.strength = min(1.0, best_weight / 12.0)

    return result


def is_price_in_confluence_zone(
    conf: ConfluenceResult,
    current_price: float,
    tick_size: float,
    tolerance_ticks: float = 5.0
) -> bool:
    """Verifie si le prix est dans la zone de confluence"""
    if not conf.has_confluence:
        return False

    tolerance = tolerance_ticks * tick_size
    zone_half_width = (conf.zone_width_ticks / 2.0) * tick_size

    zone_low = conf.zone_center - zone_half_width - tolerance
    zone_high = conf.zone_center + zone_half_width + tolerance

    return zone_low <= current_price <= zone_high


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_cluster_simple():
    """TEST 1: Cluster simple avec 2 niveaux proches"""
    print("\n" + "="*60)
    print("TEST 1: Cluster simple (HVL + GEX proches)")
    print("="*60)

    levels = [
        LevelInfo(6000.00, 3, "HVL"),      # Poids 3
        LevelInfo(6002.00, 2, "GEX_TOP"),  # Poids 2 - 8 ticks de distance
        LevelInfo(6050.00, 1, "BLIND"),    # Trop loin
    ]

    result = detect_confluence(levels, 6001.00, 0.25, 10.0)

    print(f"  Niveaux: HVL@6000, GEX@6002, BLIND@6050")
    print(f"  Prix actuel: 6001.00")
    print(f"  Confluence detectee: {result.has_confluence}")
    print(f"  Niveaux dans cluster: {result.num_levels}")
    print(f"  Score pondere: {result.weighted_score}")
    print(f"  Centre zone: {result.zone_center:.2f}")
    print(f"  Description: {result.levels_desc}")

    assert result.has_confluence == True, "ECHEC: Devrait detecter confluence"
    assert result.num_levels == 2, "ECHEC: Devrait avoir 2 niveaux"
    assert result.weighted_score == 5, "ECHEC: Score devrait etre 5 (3+2)"
    print("  PASSE!")
    return True


def test_cluster_fort():
    """TEST 2: Cluster fort avec 4 niveaux"""
    print("\n" + "="*60)
    print("TEST 2: Cluster fort (HVL + GEX + PUT + VWAP)")
    print("="*60)

    levels = [
        LevelInfo(6000.00, 3, "HVL"),      # Poids 3
        LevelInfo(6001.00, 2, "GEX_TOP"),  # Poids 2
        LevelInfo(6001.50, 2, "PUT"),      # Poids 2
        LevelInfo(6002.00, 2, "VWAP"),     # Poids 2
        LevelInfo(6100.00, 1, "GEX"),      # Trop loin
    ]

    result = detect_confluence(levels, 6001.00, 0.25, 10.0)

    print(f"  Niveaux: HVL@6000, GEX@6001, PUT@6001.5, VWAP@6002")
    print(f"  Prix actuel: 6001.00")
    print(f"  Confluence detectee: {result.has_confluence}")
    print(f"  Niveaux dans cluster: {result.num_levels}")
    print(f"  Score pondere: {result.weighted_score}")
    print(f"  Force: {result.strength:.2f}")
    print(f"  Centre zone: {result.zone_center:.2f}")

    assert result.has_confluence == True, "ECHEC: Devrait detecter confluence"
    assert result.num_levels == 4, "ECHEC: Devrait avoir 4 niveaux"
    assert result.weighted_score == 9, "ECHEC: Score devrait etre 9 (3+2+2+2)"
    assert result.strength >= 0.7, "ECHEC: Force devrait etre >= 0.7"
    print("  PASSE!")
    return True


def test_niveaux_disperses():
    """TEST 3: Niveaux trop disperses (pas de confluence)"""
    print("\n" + "="*60)
    print("TEST 3: Niveaux disperses (pas de confluence)")
    print("="*60)

    levels = [
        LevelInfo(6000.00, 3, "HVL"),
        LevelInfo(6020.00, 2, "GEX_TOP"),  # 80 ticks - trop loin
        LevelInfo(6050.00, 2, "PUT"),      # 200 ticks - trop loin
    ]

    result = detect_confluence(levels, 6010.00, 0.25, 10.0)

    print(f"  Niveaux: HVL@6000, GEX@6020, PUT@6050")
    print(f"  Distance entre niveaux: > 10 ticks")
    print(f"  Confluence detectee: {result.has_confluence}")

    assert result.has_confluence == False, "ECHEC: Ne devrait PAS detecter confluence"
    print("  PASSE!")
    return True


def test_score_insuffisant():
    """TEST 4: 2 niveaux mais score trop bas"""
    print("\n" + "="*60)
    print("TEST 4: Score insuffisant (2 BLIND proches)")
    print("="*60)

    levels = [
        LevelInfo(6000.00, 1, "BLIND"),  # Poids 1
        LevelInfo(6001.00, 1, "BLIND"),  # Poids 1
    ]

    result = detect_confluence(levels, 6000.50, 0.25, 10.0)

    print(f"  Niveaux: BLIND@6000, BLIND@6001")
    print(f"  Score total: 2 (minimum requis: 4)")
    print(f"  Confluence detectee: {result.has_confluence}")

    assert result.has_confluence == False, "ECHEC: Score 2 < 4, pas de confluence"
    print("  PASSE!")
    return True


def test_prix_dans_zone():
    """TEST 5: Verifier si prix dans zone de confluence"""
    print("\n" + "="*60)
    print("TEST 5: Prix dans/hors zone de confluence")
    print("="*60)

    levels = [
        LevelInfo(6000.00, 3, "HVL"),
        LevelInfo(6002.00, 2, "GEX_TOP"),
    ]

    result = detect_confluence(levels, 6001.00, 0.25, 10.0)

    # Test prix dans zone
    in_zone_1 = is_price_in_confluence_zone(result, 6001.00, 0.25, 5.0)
    in_zone_2 = is_price_in_confluence_zone(result, 6000.00, 0.25, 5.0)

    # Test prix hors zone
    out_zone = is_price_in_confluence_zone(result, 6010.00, 0.25, 5.0)

    print(f"  Zone centre: {result.zone_center:.2f}")
    print(f"  Zone largeur: {result.zone_width_ticks:.1f} ticks")
    print(f"  Prix 6001.00 dans zone: {in_zone_1}")
    print(f"  Prix 6000.00 dans zone: {in_zone_2}")
    print(f"  Prix 6010.00 dans zone: {out_zone}")

    assert in_zone_1 == True, "ECHEC: 6001 devrait etre dans zone"
    assert in_zone_2 == True, "ECHEC: 6000 devrait etre dans zone"
    assert out_zone == False, "ECHEC: 6010 devrait etre hors zone"
    print("  PASSE!")
    return True


def test_nq_realistic():
    """TEST 6: Scenario realiste NQ"""
    print("\n" + "="*60)
    print("TEST 6: Scenario realiste NQ")
    print("="*60)

    # Simulation niveaux NQ reels
    levels = [
        LevelInfo(21500.00, 3, "HVL"),
        LevelInfo(21502.50, 2, "GEX_TOP"),  # 10 ticks
        LevelInfo(21505.00, 2, "VWAP"),     # 20 ticks
        LevelInfo(21450.00, 2, "PUT"),      # 200 ticks - trop loin
        LevelInfo(21600.00, 2, "CALL"),     # 400 ticks - trop loin
        LevelInfo(21480.00, 1, "BLIND"),    # 80 ticks - trop loin
    ]

    result = detect_confluence(levels, 21503.00, 0.25, 25.0)  # 25 ticks max pour NQ

    print(f"  Prix actuel: 21503.00")
    print(f"  Confluence detectee: {result.has_confluence}")
    print(f"  Niveaux: {result.num_levels}")
    print(f"  Score: {result.weighted_score}")
    print(f"  Centre: {result.zone_center:.2f}")
    print(f"  Force: {result.strength:.2f}")
    print(f"  Description: {result.levels_desc}")

    assert result.has_confluence == True, "ECHEC: Devrait detecter confluence"
    assert result.num_levels == 3, "ECHEC: HVL+GEX+VWAP = 3 niveaux"
    print("  PASSE!")
    return True


def run_all_tests():
    """Execute tous les tests"""
    print("\n" + "="*70)
    print(" TESTS CONFLUENCE DETECTOR v2")
    print("="*70)

    tests = [
        test_cluster_simple,
        test_cluster_fort,
        test_niveaux_disperses,
        test_score_insuffisant,
        test_prix_dans_zone,
        test_nq_realistic,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  ECHEC: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERREUR: {e}")
            failed += 1

    print("\n" + "="*70)
    print(f" RESULTATS: {passed}/{len(tests)} tests passes")
    print("="*70)

    if failed == 0:
        print(" TOUS LES TESTS PASSES!")
    else:
        print(f" {failed} TEST(S) ECHOUE(S)")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
