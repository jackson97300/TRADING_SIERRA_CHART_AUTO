# =============================================================================
# PATCH V17_ULTIMATE - CORRECTIONS À APPLIQUER
# =============================================================================
#
# Ce fichier liste les modifications EXACTES à faire dans ton code
# pour passer de V10.3 à V17_ULTIMATE.
#
# =============================================================================

"""
=============================================================================
FICHIER 1: launch_production_CLEAN_v2.py
=============================================================================

### MODIFICATION 1: Activer le trailing stop (ligne ~259)

CHERCHER:
```python
enable_trailing_stop: bool = False  # 🔴 DÉSACTIVÉ 09/12
```

REMPLACER PAR:
```python
enable_trailing_stop: bool = True  # 🟢 V17_ULTIMATE - ACTIVÉ !
```

---

### MODIFICATION 2: Ajouter filtre distance minimum (dans generate_signal ou équivalent)

AJOUTER:
```python
# V17_ULTIMATE: Distance minimum 5 ticks
MIN_DISTANCE_TICKS = 5
MAX_DISTANCE_TICKS = 8

if distance_ticks < MIN_DISTANCE_TICKS:
    logger.debug(f"Trade rejeté: distance {distance_ticks:.1f}t < min {MIN_DISTANCE_TICKS}t")
    continue  # ou return None
```

---

### MODIFICATION 3: Ajouter filtre Delta/MIA strict

AJOUTER:
```python
# V17_ULTIMATE: Filtre Delta + MIA
DELTA_THRESHOLD = 150
MIA_THRESHOLD = 0.52

def check_delta_mia_filter(delta: float, mia_score: float, direction: str) -> bool:
    if direction == 'LONG':
        return delta > DELTA_THRESHOLD and mia_score > MIA_THRESHOLD
    else:  # SHORT
        return delta < -DELTA_THRESHOLD and mia_score < (1 - MIA_THRESHOLD)

# Dans la logique de génération de signal:
if not check_delta_mia_filter(delta, mia_score, direction):
    logger.debug(f"Trade rejeté: Delta/MIA filter failed")
    continue  # ou return None
```

---

### MODIFICATION 4: Blacklister les niveaux perdants

AJOUTER:
```python
# V17_ULTIMATE: Niveaux à éviter
LEVELS_TO_AVOID = ['gex_2', 'gex_1', 'gamma_wall_level']

# Dans la logique de sélection de niveau:
if trigger_level_name in LEVELS_TO_AVOID:
    logger.debug(f"Trade rejeté: niveau {trigger_level_name} blacklisté")
    continue  # ou return None
```

=============================================================================
FICHIER 2: trailing_stop_manager.py (ou équivalent)
=============================================================================

### MODIFICATION 5: Corriger les paramètres trailing (CRITIQUE!)

CHERCHER:
```python
trailing_enabled: bool = False   # 🔴 DÉSACTIVÉ 09/12
progressive_enabled: bool = False  # 🔴 DÉSACTIVÉ 09/12

# Paramètres par symbole
'ES': {
    'activation_ticks': 28,  # Activer après +28 ticks
    'trailing_distance': 8,  # Suivre à 8 ticks
    ...
}
```

REMPLACER PAR:
```python
trailing_enabled: bool = True   # 🟢 V17_ULTIMATE - ACTIVÉ !
progressive_enabled: bool = False  # Désactiver les paliers

# Paramètres V17_ULTIMATE (CORRIGÉS!)
'ES': {
    'activation_ticks': 6,   # 🔥 6 au lieu de 28 !
    'trailing_distance': 4,  # 🔥 4 au lieu de 8 !
}

'NQ': {
    'activation_ticks': 6,   # 🔥 6 au lieu de 35 !
    'trailing_distance': 4,  # 🔥 4 au lieu de 10 !
}
```

---

### MODIFICATION 6: Simplifier la logique trailing

CHERCHER le système de paliers progressifs:
```python
# Ancien système avec paliers
TRAILING_LEVELS_ES = [
    (8, 2),    # +8t profit  → SL à +2t
    (10, 4),   # +10t profit → SL à +4t
    (12, 6),   # etc.
    ...
]
```

REMPLACER PAR:
```python
# V17_ULTIMATE: Trailing simple
def calculate_trailing_sl(entry_price, current_price, direction, 
                          current_sl, tick_size, symbol='ES'):
    '''
    Trailing simple V17_ULTIMATE.
    - Activation: +6 ticks de profit
    - Distance: 4 ticks du prix actuel
    '''
    ACTIVATION = 6
    DISTANCE = 4
    
    # Calculer excursion favorable
    if direction == 'LONG':
        excursion = (current_price - entry_price) / tick_size
    else:
        excursion = (entry_price - current_price) / tick_size
    
    # Pas encore activé?
    if excursion < ACTIVATION:
        return current_sl, False
    
    # Calculer nouveau SL
    if direction == 'LONG':
        new_sl = current_price - (DISTANCE * tick_size)
        # Ne jamais baisser le SL
        if new_sl > current_sl:
            return new_sl, True
    else:  # SHORT
        new_sl = current_price + (DISTANCE * tick_size)
        # Ne jamais monter le SL (pour short)
        if new_sl < current_sl:
            return new_sl, True
    
    return current_sl, False
```

=============================================================================
FICHIER 3: config.py ou équivalent
=============================================================================

### MODIFICATION 7: Réduire TP/SL

CHERCHER:
```python
TP_TICKS_ES = 12
SL_TICKS_ES = 12
TP_TICKS_NQ = 25
SL_TICKS_NQ = 20
```

REMPLACER PAR:
```python
# V17_ULTIMATE: TP/SL réduits
TP_TICKS_ES = 10  # Réduit de 12 → 10
SL_TICKS_ES = 10
TP_TICKS_NQ = 14  # Réduit de 25 → 14
SL_TICKS_NQ = 14
```

=============================================================================
RÉSUMÉ DES CHANGEMENTS
=============================================================================

| Paramètre | AVANT (V10.3) | APRÈS (V17_ULTIMATE) |
|-----------|---------------|----------------------|
| enable_trailing_stop | False | **True** |
| activation_ticks ES | 28 | **6** |
| trailing_distance ES | 8 | **4** |
| activation_ticks NQ | 35 | **6** |
| trailing_distance NQ | 10 | **4** |
| TP ES | 12 | **10** |
| SL ES | 12 | **10** |
| TP NQ | 25 | **14** |
| SL NQ | 20 | **14** |
| min_distance | 0 | **5** |
| delta_threshold | multi | **150** |
| mia_threshold | non | **0.52** |
| gex_2 | tradé | **blacklisté** |

=============================================================================
TEST APRÈS MODIFICATIONS
=============================================================================

1. Lancer en PAPER TRADING pendant 1 semaine
2. Vérifier les logs:
   - "Trailing activé" doit apparaître après +6t de profit
   - "Trailing SL" doit apparaître comme raison de sortie
   - Pas de "Trade rejeté: niveau gex_2"
   
3. Métriques attendues:
   - Win Rate: 80-90%
   - Sorties Trailing SL: ~80% des sorties
   - Sorties TP: ~10% des sorties
   - Sorties SL: ~10% des sorties

=============================================================================
"""

print(__doc__)
