# Audit Phase 0 — Scaling 3 bots à MGC (ES + NQ + GC)

**Date** : 2026-05-10
**Contexte** : Jackson directive "ajouter GC à chaque bot avec ses rules spécifiques,
chaque bot tradera ES + NQ + GC". Audit hardcode ES/NQ pour identifier tous les
points de friction.

---

## 1. État par module

### 1.1 `BOT/bot_config.py` ✓ PROPRE
- `InstrumentConfig` dataclass paramétrisée (tick_size, tick_value, contract)
- `INSTRUMENTS = {"ES": ES, "NQ": NQ}` registry
- **Action MGC** : ajouter `MGC = InstrumentConfig(symbol="MGC", tick_size=0.10, tick_value=1.00, contract="MGCM26-CMECOMEX")` + `INSTRUMENTS["MGC"] = MGC`
- **Effort** : 5 min

### 1.2 `BOT/risk_manager.py` ✓ PROPRE (instrument-agnostic)
- `can_trade(symbol, direction, instrument: InstrumentConfig)` paramétrisé
- `compute_position_size(instrument: InstrumentConfig, ...)` utilise `instrument.tick_value`
- **Aucun hardcode ES/NQ détecté**
- **Action MGC** : aucune côté code, MGC compatible automatiquement après bot_config
- **Mais** : daily_loss cap est PER-RiskManager. Avec Bot 1+2+3 actifs sur 3 sym :
  - Bot 1 RM cap = $500 → max $500 loss
  - Bot 2 RM cap = $500 → max $500 loss
  - Bot 3 RM cap = $500 → max $500 loss
  - Total possible = $1500 → **Topstep DLL ($1000) breach garanti**
- **Action recommandée** : implémenter un **GlobalRiskCap** singleton lu par les 3 bots,
  cap = $800 partagé (marge sous DLL Topstep)
- **Effort** : 1-2h dev + tests

### 1.3 `CORE/databento_paper_trader_v2.py` (Bot 2 + Bot 3) ⚠️ MODÉRÉ
**41 occurrences "ES"/"NQ" totalisant 20 dans Bot 2/3** :
- Ligne 167 : `SYMBOLS = ["NQ", "ES"]` → ajouter `"MGC"`
- Ligne 168 : `SYMBOL_TO_CONTRACT = {"NQ": "NQM26-CME", "ES": "ESM26-CME"}` → ajouter MGC
- Ligne 246-247 : `consecutive_sl`/`breaker_until` dict `{"NQ": ..., "ES": ...}` → init dynamique depuis SYMBOLS
- Lignes 324-327, 1610-1613 : `bot3_counters_today` `{"NQ": ..., "ES": ...}` → init dynamique
- Lignes 246-247, 311, 313, 331 : positions/brackets dict hardcoded → init dynamique
- `GR[sym]` registry (ligne 808-809, 1068) : déjà paramétrisé, utilise `tick_size`/`tick_value`
- **Action MGC** :
  1. `SYMBOLS = ["NQ", "ES", "MGC"]`
  2. `SYMBOL_TO_CONTRACT["MGC"] = "MGCM26-CMECOMEX"` (à valider contract Sierra Chart)
  3. Refactor dicts init `{sym: ... for sym in SYMBOLS}` au lieu de hardcoded keys
  4. `GR[sym]` à étendre via `bot_config.INSTRUMENTS["MGC"]` (à propager)
  5. Session COMEX gold 08:30-13:30 ET vs NYSE 09:30-16:00 ET déjà géré via `get_session_boundaries(symbol)` (Chantier 4)
- **Effort** : 3-5h dev + tests no-regress ES/NQ obligatoires

### 1.4 `CORE/mia_paper_trader.py` (Bot 1) ⚠️ LOURD
**41 occurrences "ES"/"NQ" + 2 constantes hardcodées + 30+ dicts d'état** :

#### Constantes hardcodées
- Ligne 85 : `TRAILING_TP_MFE_THRESHOLD_TICKS = {"ES": 30, "NQ": 50}` → manque MGC
- Ligne 90 : `TRAILING_TP_OBS_MFE_THRESHOLD_TICKS = {"ES": 40, "NQ": 60}` → manque MGC
- **Ligne 93 : `TICK_SIZE = 0.25`** → CONSTANTE MODULE FAUSSE pour MGC (0.10).
  Utilisée à plusieurs endroits (ligne 1277, 2570). Refactor vers `get_tick_size(sym)`.
- Ligne 96 : `TICK_VALUE = {"ES": 1.25, "NQ": 0.50}` → manque MGC = 1.00

#### Dicts d'état hardcodés (sample, total ~30)
- `SLTPEngine` × 2 (`{"ES": SLTPEngine(symbol="ES"), "NQ": SLTPEngine(symbol="NQ")}`) → ajouter MGC
- `_consec_losses = {"ES": 0, "NQ": 0}` → init dynamique
- `_sell_trades_today`, `_sell_dd_intraday_ticks`, `_sell_disabled`, `_sell_disable_reason` → idem
- `_v4_obs_counts` `{"ES": {...}, "NQ": {...}}` → init dynamique
- `_menthorq_regime` `{"ES": {"regime": "UNKNOWN"}, "NQ": ...}` → init dynamique
- 6× `for sym in ("ES", "NQ"):` → boucler sur SYMBOLS dynamique

#### Logique cross-instrument
- Ligne 1499 : `other_sym = "ES" if symbol == "NQ" else "NQ"` → cross-pair NQ↔ES (pas valide pour MGC, gold n'a pas de pair naturel)
- Ligne 1503 : SMT divergence ES/NQ → skip pour MGC (no intermarket)

- **Action MGC** :
  1. Remplacer `TICK_SIZE = 0.25` par `from CORE.constants import get_tick_size`
  2. Remplacer `TICK_VALUE` dict par lookup via `bot_config.INSTRUMENTS[sym].tick_value`
  3. Étendre `TRAILING_TP_MFE_THRESHOLD_TICKS["MGC"] = ?` (à calibrer)
  4. Refactor tous dicts d'état `{"ES":, "NQ":}` → init via `{sym: ... for sym in SYMBOLS}`
  5. SMT/cross-instrument : skip si `symbol == "MGC"` (pas de pair naturel)
- **Effort** : 5-8h dev + tests no-regress ES/NQ obligatoires

---

## 2. Cross-cutting concerns

### 2.1 DTC contract resolver
Sierra Chart contract Gold = `MGCM26-CMECOMEX` ou `MGCM26-COMEX` (à valider).
À vérifier dans `BOT/dtc_connector.py` que `send_order` accepte le suffix `-COMEX`.

### 2.2 Sessions per-symbole
Déjà géré via `CORE/constants.py:SESSION_BOUNDARIES_BY_SYMBOL` :
- ES/NQ : us_start=09:30 ET, us_end=16:00 ET
- MGC : us_start=08:30 ET, us_end=13:30 ET (COMEX gold)
- Helper : `get_session_boundaries(symbol)`, `is_in_mgc_rth(ts)`

### 2.3 MenthorQ key levels MGC
- C++ `scsf_MIA_MQ_Lite_GC` déployé 09/05 → dump `DATA/mq_levels/GC/`
- À vérifier J+1 (lundi 11/05) que les niveaux GC sont consommés par les bots
- Fichier JSON `DATA/MENTHORQ/YYYYMMDD_menthorq_complete.json` doit avoir clé `GC` (Bot 1 lit ça)

### 2.4 Rules spécifiques MGC (Jackson directive)
Si rules ES/NQ ne marchent pas sur MGC en backtest, Jackson veut quand même
trader MGC avec **les rules adaptées** (même approche, seuils MGC-spécifiques).

Implication : prévoir des **paramètres per-symbole** dans chaque rule, pas seulement
des constantes globales. Exemple :
```python
# Avant
BN_ABSORPTION_THRESHOLD = 50  # ES-only

# Après
BN_ABSORPTION_THRESHOLD_BY_SYMBOL = {
    "ES": 50, "NQ": 70, "MGC": 25  # MGC seuils + faibles (tick 0.10)
}
```

À auditer : combien de seuils empiriques actuellement hardcodés ES/NQ ?
**Estimation** : 20-40 seuils répartis dans :
- `phase_b_plus_plus_engine.py` (✓ déjà fait Chantier 5bis2)
- `bn_engine.py`, `bn_v3_engine.py`, `rule_engine.py`
- `mia_sltp.py`, `mia_paper_trader.py` rules
- `bot3_config.py` levels Sidak

---

## 3. Plan d'attaque recommandé

### Phase 0.2 : Validation approche par code-reviewer
Dispatcher agent code-reviewer avec ce rapport pour valider :
- L'approche switch constantes module vers helpers `get_tick_size`/`bot_config.INSTRUMENTS`
- L'approche refactor dicts d'état hardcoded → init dynamique
- La nécessité du GlobalRiskCap singleton (anti-DLL Topstep)
- L'ordre Phase 1.1-1.5 séquentiel (Bot 1 → Bot 2 → Bot 3 → Risk → Cap)

### Phase 1.1 : Bot 1 (effort le plus gros, 5-8h)
1. Switch `TICK_SIZE` → `get_tick_size(sym)`
2. Switch `TICK_VALUE` dict → `bot_config.INSTRUMENTS[sym].tick_value`
3. Refactor 30 dicts d'état `{"ES":, "NQ":}` → comprehension
4. SMT/cross-instrument skip MGC
5. Tests no-regress ES/NQ obligatoires
6. **Review code-reviewer obligatoire avant commit**

### Phase 1.2 : Bot 2 (effort modéré, 3-5h)
1. `SYMBOLS = ["NQ", "ES", "MGC"]`
2. `SYMBOL_TO_CONTRACT["MGC"] = "MGCM26-CMECOMEX"`
3. Refactor dicts init dynamiques
4. `GR[sym]` étendre via `bot_config.INSTRUMENTS`
5. Tests no-regress + review

### Phase 1.3 : Bot 3 (faible, 1-2h car partage Bot 2)
1. `bot3_counters_today` init dynamique
2. `_bot3_positions[sym]` init dynamique
3. Tests + review

### Phase 1.4 : Risk + Cap global (2-3h)
1. Ajouter MGC à `bot_config.INSTRUMENTS`
2. Implémenter `GlobalRiskCap` singleton ($800 partagé)
3. Wiring dans Bot 1/2/3
4. Tests + review code-reviewer + market-analyst

### Phase 1.5 : DTC connector validation
1. Vérifier `dtc_connector.py` accepte contract suffix `-COMEX`
2. Test send_order MGC en Sim Sierra Chart (sans vraie position)
3. Validation cancel/OCO sur MGC

---

## 4. Risques identifiés

| # | Risque | Mitigation |
|---|--------|------------|
| R1 | Refactor Bot 1 casse trades ES/NQ live (9 services running) | Tests no-regress obligatoires + déploy après confirmation Jackson, jamais en open market |
| R2 | DLL Topstep breach avec 3 sym sans cap global | GlobalRiskCap obligatoire avant activation MGC |
| R3 | Sierra Chart contract MGC mal résolu → ordre rejeté | Test empirique Sim avant paper live |
| R4 | Seuils empiriques ES inadaptés MGC → 0 signal OR signaux faux | Backtest Phase 2 valide rule-by-rule, recalibration Phase 4 si NOGO |
| R5 | SMT divergence ES/NQ peut interférer avec MGC (read other_sym pour MGC = KeyError) | Skip cross-instrument si symbol == "MGC" |
| R6 | MenthorQ GC absent (clé manquante dans JSON) | Fail-soft : continuer trading sans MQ pour GC (Bot 1 already does that for missing keys) |

---

## 5. Estimation effort total

- Phase 0.2 review : 30 min
- Phase 1.1 Bot 1 : 5-8h dev + 1h tests + 30 min review
- Phase 1.2 Bot 2 : 3-5h dev + 1h tests + 30 min review
- Phase 1.3 Bot 3 : 1-2h dev + 30 min tests + 30 min review
- Phase 1.4 Risk + GlobalCap : 2-3h dev + 1h tests + 1h review (code + market)
- Phase 1.5 DTC validation : 1h test empirique Sim

**Total Phase 1 : 16-22h de dev (3-4 sessions de travail)**

Puis :
- Phase 2 backtests : 10-15h compute + 30 min review ml-trainer
- Phase 3-4 décision + recalibration : variable
- Phase 5 paper trading 3 sym : continu

---

## 6. Décisions ouvertes (à valider Jackson)

1. **GlobalRiskCap** : $800 partagé OK ou autre montant ? (Topstep DLL = $1000, marge $200)
2. **Trailing TP MGC** : seuil MFE équivalent ES=30t/NQ=50t → MGC=? (à backtest)
3. **Contract Sierra Chart MGC** : `MGCM26-CMECOMEX` ou `MGCM26-COMEX` ? (à valider live)
4. **Rules spécifiques MGC** : on commence par seuils ES adaptés tick-scaled (×0.4) ou
   on recalibre directement empiriquement sur historique MGC ?
5. **Phase 1 ordre** : Bot 1 d'abord (le plus lourd) ou Bot 2/3 d'abord (plus simples, plus de feedback) ?

---

**Statut audit** : COMPLET — prêt pour Phase 0.2 review code-reviewer
