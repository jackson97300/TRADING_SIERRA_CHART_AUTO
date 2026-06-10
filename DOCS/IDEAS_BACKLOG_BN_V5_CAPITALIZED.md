# Idées capitalisées BN V5 → Bot 3 v3 v2

**Date** : 2026-06-10
**Contexte** : KILL BN V5 + transfert 4 composantes valables vers Bot 3 v3 v2 (cf `V1_ARCHIVE/BN_V5/README.md`)

## 1. Confluence niveaux MenthorQ (PRIORITÉ P0)

### Concept
Pivot/setup doit être proche (< 0.10-0.20%) d'un niveau institutionnel options-driven MenthorQ.

### Niveaux MenthorQ disponibles
- `mq_hvl` (Highest Volume Level — POC options-driven)
- `mq_call` / `mq_put` (Call/Put walls)
- `mq_call_0dte` / `mq_put_0dte` (Walls 0DTE)
- `mq_gex` top 10 strikes (Gamma Exposure)
- `mq_blind` top 10 levels (Break levels)
- `mq_1d_min` / `mq_1d_max` (1-day range options model)

### Edge théorique
Auto-réalisation MM hedging : les Market Makers couvrent leur gamma exposition autour de ces niveaux → prix réagit naturellement.

### Implémentation Bot 3 v3 v2
```python
def is_near_mq_level(row, threshold_pct=0.15):
    """Détecte si bar est proche d'un niveau MenthorQ."""
    levels = [
        ("mq_hvl", row.get("dist_mq_hvl_pct")),
        ("mq_put", row.get("dist_mq_put_pct")),
        ("mq_call", row.get("dist_mq_call_pct")),
        ("mq_hvl_0dte", row.get("dist_mq_hvl_0dte_pct")),
    ]
    for name, dist in levels:
        if dist is not None and abs(dist) <= threshold_pct:
            return (name, dist)
    return (None, None)
```

### Test empirique nécessaire
- Backtest 30j Bot 3 v3 + confluence MQ vs Bot 3 v3 baseline
- Comparer PF, WR, EV per level

## 2. Bar reversal niveau 1+2 (PRIORITÉ P1)

### Concept
Confirmation minimale du momentum d'entrée :
- **Niveau 1** (toujours requis) : bar verte (LONG) / rouge (SHORT)
- **Niveau 2** (default ON) : `delta_bar > 0` (LONG) / `< 0` (SHORT)

### Niveau 3+4 DÉSACTIVÉS (Kill F5/F6 03/06)
- Niveau 3 : aggressor_imbalance → tuait 100% NQ
- Niveau 4 : long_up_bar / long_dn_bar → tuait 97% ES
- **NE PAS RÉACTIVER** sans backtest empirique probant

### Edge théorique
Filtre "low-effort" minimal : éviter d'entrer dans la mauvaise direction du momentum immédiat.

### Implémentation Bot 3 v3 v2
```python
def has_bar_reversal_confirmation(row, side):
    """Confirmation niveau 1+2 (KILL niveau 3+4 03/06)."""
    close = row.get("close", 0)
    open_ = row.get("open", 0)
    delta = row.get("delta_bar", 0)
    if side == "LONG":
        return (close > open_) and (delta > 0)
    return (close < open_) and (delta < 0)
```

## 3. Trailing Dow pullback (PRIORITÉ P1)

### Concept
Trailing structure-based : SL bouge quand un pullback est confirmé (= 3 bars sans new extreme).

### Différence vs ladder paliers actuel Bot 3 v3
- Ladder = paliers fixes MFE (30/50/80 ticks)
- Dow pullback = adaptatif structure (jamais redescend)

### Implémentation pour Bot 3 v3 v2
- Garder ladder paliers (déjà recalibré 10/06 matin)
- Ajouter overlay Dow pullback : si pullback détecté ET pullback_low > current_sl → move SL au pullback_low - buffer
- Hybride paliers + Dow = capture MFE + protection structure

### Test empirique nécessaire
- Backtest comparatif :
  - Ladder seul (actuel)
  - Dow pullback seul
  - Hybride
- Sur 30j NQ Bot 3 v3 historique

## 4. Daily stop Douglas $300/$400 (PRIORITÉ P0 — déjà partiel)

### État actuel
- DailyLimitsGuard implémenté (Phase 2 Bot 3 v3 09/06 + propagation Bot 3 v4 10/06)
- Mark Douglas : -$200 / +$150 / 5 trades/day per Bot 3 v3
- Mode DATA_COLLECTION 10/06 : `daily_stop_loss=-$1500`, win disabled, max_trades disabled

### Capitalisation depuis BN V5
- Valeurs $300/$400 recalibrées BN V5 = pour 1 NQ E-mini réel
- À convertir en équivalent micro virtuel (cf DECOUPLING 10/06)

### Implémentation Bot 3 v3 v2
- Cap virtuel micro Python : $30/$40 (équivalent $300/$400 E-mini ÷ 10)
- Helper `daily_limits_guard.py:DailyLimitsConfig` déjà cascade env vars per-bot
- Ajouter mode "preventive check" (Phase H BN V5 portée)

## Plan d'intégration

### Phase 1 (cette semaine)
- [X] Confluence MQ : helper `is_near_mq_level()` dans `bot3_paper_common.py`
- [ ] Bar reversal : helper dans Bot 3 v3 engine (niveau 1+2 only)
- [ ] Backtest 30j Bot 3 v3 baseline vs Bot 3 v3 + confluence MQ

### Phase 2 (semaine suivante)
- [ ] Dow pullback overlay sur ladder Bot 3 v3
- [ ] Backtest comparatif 3 variantes trailing
- [ ] Daily stop préventif (port Phase H BN V5)

### Phase 3 (validation)
- [ ] 5/5 contrôles Lopez sur Bot 3 v3 v2 final
- [ ] Paper 30j Sim1 si DSR >= 0.5
- [ ] Décision réactivation full deploy

## Note critique

**Ne pas refaire l'erreur BN V5** :
- Pas de cascade gates additionnelle sans backtest (max 8 gates total Bot 3 v3 v2)
- Pas de recalibrage en cours de paper sans walk-forward
- Pas de "ULTRATHINK 6 commits en 4h sans backtest"
- Mandate ml-trainer agent OBLIGATOIRE sur chaque ajout edge

## Lien

- `V1_ARCHIVE/BN_V5/README.md` (justification KILL)
- INCIDENT_LOG 2026-06-10 12:00 (27) [PATTERN_11 + DATA_MINING_TRAP]
- BOT_CHANGELOG 2026-06-10 12:00 (KILL BN V5)
