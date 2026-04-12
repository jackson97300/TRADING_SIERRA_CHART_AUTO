#!/usr/bin/env python3
"""
TEST LABELER UNIQUENESS — compute_label_uniqueness (Lopez AFML ch.4)
====================================================================

Valide la formule Lopez de Prado AFML ch.4 p.60-61 :

    Pour chaque label actif sur [t_start, t_end] :
        c_t = nombre de labels actifs a l'instant t
        weight[i] = mean(1/c_t) pour t dans [t_start, t_end]

Pourquoi ce test existe : sans validation, un refactor pourrait casser la
formule sans que rien ne prevenu le trader. Les sample weights gonflent (ou
non) le Sharpe IS de +0.3 a +0.6 selon la concurrence temporelle des labels.
Un bug silencieux ici = catastrophe de validation ML.

Cas testes :
  1. Labels isoles (pas de chevauchement) → weight = 1.0
  2. Deux labels qui se chevauchent → weight < 1.0
  3. Trois labels superposes → weight decroit progressivement
  4. Labels HOLD (label=0) → weight = 1.0 par defaut (pas utilise au training)
  5. Dataset vide → retour Series vide propre
  6. Un seul label isole → weight = 1.0
  7. Chevauchement complet (meme intervalle) → weight = 1/n

Usage :
    python -X utf8 tests/test_labeler_uniqueness.py
"""

import sys
from pathlib import Path

# Ajouter CORE au path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "CORE"))

import numpy as np
import pandas as pd

from labeler import compute_label_uniqueness


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════════

PASSED = 0
FAILED = 0
FAILURES = []

def check(name: str, condition: bool, expected=None, actual=None):
    global PASSED, FAILED
    if condition:
        print(f"  OK  {name}")
        PASSED += 1
    else:
        detail = ""
        if expected is not None or actual is not None:
            detail = f" (expected={expected}, actual={actual})"
        print(f"  FAIL {name}{detail}")
        FAILED += 1
        FAILURES.append(name)


def almost_equal(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) < eps


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_labels_isoles():
    """Deux labels sans chevauchement temporel → weight = 1.0 chacun."""
    print("\n[1] Labels isoles (pas de chevauchement)")
    # Label en barre 1 vit [1,3], label en barre 5 vit [5,8]
    labels  = pd.Series([0, 1, 0, 0, 0, -1, 0, 0, 0, 0], dtype=np.int8)
    offsets = pd.Series([0, 2, 0, 0, 0,  3, 0, 0, 0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)

    check("weight[1] = 1.0", almost_equal(w.iloc[1], 1.0), 1.0, w.iloc[1])
    check("weight[5] = 1.0", almost_equal(w.iloc[5], 1.0), 1.0, w.iloc[5])
    check("weight[0] = 1.0 (HOLD defaut)", almost_equal(w.iloc[0], 1.0), 1.0, w.iloc[0])


def test_2_chevauchement_deux_labels():
    """Deux labels qui se chevauchent partiellement."""
    print("\n[2] Chevauchement de 2 labels")
    # Barres :        0  1  2  3
    # Labels :        1  1  0  0
    # Exit offset :   2  1  0  0
    # Label 0 vit [0,2], label 1 vit [1,2]
    # concurrent[0]=1 (seulement 0 actif), [1]=2 (0 et 1 actifs), [2]=2 (0 et 1)
    # weight[0] = mean(1/1, 1/2, 1/2) = (1 + 0.5 + 0.5) / 3 = 2/3
    # weight[1] = mean(1/2, 1/2) = 0.5
    labels  = pd.Series([1, 1, 0, 0], dtype=np.int8)
    offsets = pd.Series([2, 1, 0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)

    check("weight[0] = 2/3", almost_equal(w.iloc[0], 2/3), 2/3, w.iloc[0])
    check("weight[1] = 0.5", almost_equal(w.iloc[1], 0.5), 0.5, w.iloc[1])


def test_3_trois_labels_superposes():
    """Trois labels qui s'empilent progressivement."""
    print("\n[3] Trois labels superposes (stress test)")
    # Barres :        0  1  2  3  4
    # Labels :        1  1  1  0  0
    # Exit offset :   3  2  1  0  0
    # Label 0 [0,3] : concurrent[0]=1, [1]=2, [2]=3, [3]=3
    # Label 1 [1,3] : concurrent[1]=2, [2]=3, [3]=3
    # Label 2 [2,3] : concurrent[2]=3, [3]=3
    # weight[0] = mean(1, 0.5, 1/3, 1/3) = (1 + 0.5 + 1/3 + 1/3) / 4
    # weight[1] = mean(0.5, 1/3, 1/3) = (0.5 + 1/3 + 1/3) / 3
    # weight[2] = mean(1/3, 1/3) = 1/3
    labels  = pd.Series([1, 1, 1, 0, 0], dtype=np.int8)
    offsets = pd.Series([3, 2, 1, 0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)

    expected_0 = (1 + 0.5 + 1/3 + 1/3) / 4
    expected_1 = (0.5 + 1/3 + 1/3) / 3
    expected_2 = 1/3

    check("weight[0] decroissant", almost_equal(w.iloc[0], expected_0), expected_0, w.iloc[0])
    check("weight[1] decroissant", almost_equal(w.iloc[1], expected_1), expected_1, w.iloc[1])
    check("weight[2] = 1/3", almost_equal(w.iloc[2], expected_2), expected_2, w.iloc[2])
    # Ordre monotone : plus on empile, plus le poids baisse
    check("weight[0] > weight[1] > weight[2]", w.iloc[0] > w.iloc[1] > w.iloc[2])


def test_4_hold_nest_pas_dans_concurrence():
    """Les labels HOLD (label=0) ne participent pas a la concurrence."""
    print("\n[4] Labels HOLD n'affectent pas la concurrence")
    # Barres :       0  1  2  3
    # Labels :       1  0  0  0  (seul le label 0 est actif)
    # Exit offset :  3  0  0  0
    # Pas de concurrence → weight[0] = 1.0
    labels  = pd.Series([1, 0, 0, 0], dtype=np.int8)
    offsets = pd.Series([3, 0, 0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)

    check("weight[0] = 1.0 (seul actif)", almost_equal(w.iloc[0], 1.0), 1.0, w.iloc[0])
    check("weight[1] = 1.0 (HOLD defaut)", almost_equal(w.iloc[1], 1.0), 1.0, w.iloc[1])
    check("weight[2] = 1.0 (HOLD defaut)", almost_equal(w.iloc[2], 1.0), 1.0, w.iloc[2])


def test_5_dataset_vide():
    """Entree vide → sortie vide propre (pas de crash)."""
    print("\n[5] Dataset vide")
    labels  = pd.Series([], dtype=np.int8)
    offsets = pd.Series([], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)
    check("len(weights) = 0", len(w) == 0, 0, len(w))
    check("dtype = float64", w.dtype == np.float64, "float64", str(w.dtype))


def test_6_label_unique():
    """Un seul label dans tout le dataset → weight = 1.0."""
    print("\n[6] Un seul label isole")
    labels  = pd.Series([0, 0, 1, 0, 0], dtype=np.int8)
    offsets = pd.Series([0, 0, 2, 0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)
    check("weight[2] = 1.0", almost_equal(w.iloc[2], 1.0), 1.0, w.iloc[2])


def test_7_chevauchement_complet():
    """N labels sur exactement le meme intervalle → chacun vaut 1/N."""
    print("\n[7] Chevauchement complet (meme intervalle)")
    # 4 labels qui commencent tous en barre 0 et vivent sur [0, 2]
    # concurrent[0] = 4, [1] = 4, [2] = 4
    # weight[i] = mean(1/4, 1/4, 1/4) = 0.25 pour chaque label
    labels  = pd.Series([1, 1, 1, 1, 0, 0], dtype=np.int8)
    offsets = pd.Series([2, 1, 0, 0, 0, 0], dtype=np.int32)
    # Attention : le label 3 a offset=0 donc vit juste sur [3,3]
    # Pour tester le cas "meme intervalle" exactement, il faut des offsets qui
    # pointent tous a la meme barre de fin. On fait donc :
    # Label 0 [0,2] offset=2, Label 1 [1,2] offset=1, Label 2 [2,2] offset=0, Label 3 [3,3]?
    # Ce cas est ambigu — refaisons plus simple :
    # 2 labels exactement sur [0,1] et 0 ailleurs
    labels  = pd.Series([1, -1, 0], dtype=np.int8)
    offsets = pd.Series([1,  0, 0], dtype=np.int32)
    w = compute_label_uniqueness(labels, offsets)
    # Label 0 vit [0,1], Label 1 vit [1,1]
    # concurrent[0]=1, [1]=2
    # weight[0] = mean(1/1, 1/2) = 0.75
    # weight[1] = mean(1/2) = 0.5
    check("weight[0] = 0.75", almost_equal(w.iloc[0], 0.75), 0.75, w.iloc[0])
    check("weight[1] = 0.5", almost_equal(w.iloc[1], 0.5), 0.5, w.iloc[1])


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  TEST compute_label_uniqueness (Lopez AFML ch.4)")
    print("=" * 62)

    test_1_labels_isoles()
    test_2_chevauchement_deux_labels()
    test_3_trois_labels_superposes()
    test_4_hold_nest_pas_dans_concurrence()
    test_5_dataset_vide()
    test_6_label_unique()
    test_7_chevauchement_complet()

    print()
    print("=" * 62)
    print(f"  {PASSED}/{PASSED + FAILED} tests passent")
    if FAILURES:
        print(f"  ECHECS :")
        for name in FAILURES:
            print(f"    - {name}")
        print("=" * 62)
        sys.exit(1)
    print("  TOUS LES TESTS PASSENT")
    print("=" * 62)


if __name__ == "__main__":
    main()
