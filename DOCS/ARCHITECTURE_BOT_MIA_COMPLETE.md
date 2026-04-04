# MIA AUTO-TRADER BOT - GUIDE ARCHITECTURE COMPLET

**Version:** 2.0 (01/02/2026)  
**Plateforme:** Sierra Chart (C++ DLL)  
**Auteur:** MIA Trading System  

---

## TABLE DES MATIÈRES

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture des fichiers](#2-architecture-des-fichiers)
3. [Pipeline de décision (4 Layers)](#3-pipeline-de-décision-4-layers)
4. [Système de régime multi-facteurs](#4-système-de-régime-multi-facteurs)
5. [Position Sizing dynamique](#5-position-sizing-dynamique)
6. [Calcul SL/TP intelligent](#6-calcul-sltp-intelligent)
7. [Trailing Stop conditionnel](#7-trailing-stop-conditionnel)
8. [Circuit Breakers & Risk Management](#8-circuit-breakers--risk-management)
9. [Logging & Debug](#9-logging--debug)
10. [Configuration & Paramètres](#10-configuration--paramètres)
11. [Flux de données](#11-flux-de-données)
12. [FAQ Technique](#12-faq-technique)

---

## 1. VUE D'ENSEMBLE

### 1.1 Qu'est-ce que MIA?

MIA (Market Intelligence Assistant) est un bot de trading automatisé pour futures (ES/NQ) qui:

- Analyse les données orderflow en temps réel (Battle Navale)
- Utilise les niveaux institutionnels (MenthorQ: Gamma Walls, Call/Put, etc.)
- Prend des décisions via un pipeline à 4 couches (L1→L2→L3→L4)
- Ajuste dynamiquement la taille et le TP selon le régime de marché
- Gère le risque avec des circuit breakers et trailing stop intelligent

### 1.2 Symboles supportés

| Symbole | Type | Tick Size | Tick Value |
|---------|------|-----------|------------|
| **MES** | Micro E-mini S&P 500 | 0.25 | $1.25 |
| **MNQ** | Micro E-mini Nasdaq | 0.25 | $0.50 |

### 1.3 Architecture globale

```
┌─────────────────────────────────────────────────────────────────┐
│                    SIERRA CHART (DLL)                           │
├─────────────────────────────────────────────────────────────────┤
│  MIA_Main.cpp (Chef d'orchestre)                                │
│     │                                                           │
│     ├─> MIA_DataReader.h    (Lecture Battle Navale)            │
│     ├─> MIA_MenthorQ.h      (Lecture niveaux institutionnels)   │
│     ├─> MIA_Layers.h        (L1, L2, L3, L4)                   │
│     ├─> MIA_SLTP_Calc.h     (Calcul SL/TP avec obstacles)      │
│     ├─> MIA_Config.h        (Configuration + Régime + Sizing)  │
│     ├─> MIA_Execution.h     (Envoi ordres + Trailing)          │
│     └─> MIA_Logging.h       (Logs + Journal de trades)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. ARCHITECTURE DES FICHIERS

### 2.1 Fichiers principaux

| Fichier | Rôle | Lignes |
|---------|------|--------|
| `MIA_Main.cpp` | Point d'entrée, orchestre tout le pipeline | ~1900 |
| `MIA_Config.h` | Configuration, constantes, régime, sizing | ~750 |
| `MIA_Layers.h` | Logique des 4 layers de validation | ~1700 |
| `MIA_SLTP_Calc.h` | Calcul SL/TP avec obstacles | ~600 |
| `MIA_Execution.h` | Envoi ordres bracket, trailing stop | ~800 |
| `MIA_Logging.h` | Logs, snapshots, journal de trades | ~1600 |
| `MIA_DataReader.h` | Lecture données Battle Navale | ~1200 |
| `MIA_MenthorQ.h` | Lecture niveaux MenthorQ | ~400 |

### 2.2 Arborescence

```
D:\SIERRA CHART TRADING\ACS_Source\
├── MIA_Main.cpp              # Entry point
├── MIA_Config.h              # Config + Régime + Sizing
├── MIA_Layers.h              # L1, L2, L3, L4
├── MIA_SLTP_Calc.h           # SL/TP intelligent
├── MIA_Execution.h           # Ordres + Trailing
├── MIA_Logging.h             # Logs + Journal
├── MIA_DataReader.h          # Battle Navale data
├── MIA_MenthorQ.h            # MenthorQ data
└── MIA_StateManager.h        # État global (ES/NQ)

D:\TRADING_SIERRA_CHART_AUTO\
├── CPP\MIA_REFACTORED\       # Copie de backup
├── LOGS\TRADE_JOURNAL\       # Journal de trades JSONL
└── DOCS\                     # Documentation
```

---

## 3. PIPELINE DE DÉCISION (4 LAYERS)

### 3.1 Vue d'ensemble

```
Signal détecté
      │
      ▼
┌─────────────┐
│   LAYER 1   │  MenthorQ: Niveau institutionnel proche?
│  (Structure)│  → PUT/CALL/GAMMA/HVL/POC à ≤20 ticks?
└──────┬──────┘
       │ PASS
       ▼
┌─────────────┐
│   LAYER 2   │  OrderFlow: Tendance confirmée?
│ (OrderFlow) │  → VWAP slope + Volume + Delta alignés?
└──────┬──────┘
       │ PASS
       ▼
┌─────────────┐
│   LAYER 3   │  Confluence: Score suffisant?
│(Confluence) │  → Session + VIX + Momentum ≥ 0.15?
└──────┬──────┘
       │ PASS
       ▼
┌─────────────┐
│   LAYER 4   │  Qualité: Grade A/B/C/D?
│  (Qualité)  │  → Score ≥ 55? Combo aligné?
└──────┬──────┘
       │ PASS
       ▼
   TRADE EXÉCUTÉ
```

### 3.2 Layer 1 - Structure (MenthorQ)

**Fichier:** `MIA_Layers.h` → `ValidateLayer1()`

**Objectif:** Vérifier qu'on trade près d'un niveau institutionnel significatif.

**Niveaux vérifiés:**
- Gamma Wall (0DTE et standard)
- Put Support / Call Resistance
- HVL (High Volume Level)
- POC (Point of Control)
- Day Min/Max

**Conditions de passage:**
```cpp
// Distance maximale au niveau
float max_dist_ticks = config.l1_distance_max;  // 20 ticks

// Le niveau doit être dans la direction du trade
if (direction == 1) {  // LONG
    // Niveau de support en-dessous
}
```

**Output:**
```cpp
struct Layer1Result {
    bool passed;
    int direction;        // 1=LONG, -1=SHORT
    float confidence;     // 0-1
    float level_price;    // Prix du niveau
    char level_name[32];  // "PUT_SUP", "GAMMA_WALL", etc.
};
```

### 3.3 Layer 2 - OrderFlow Trend

**Fichier:** `MIA_Layers.h` → `ValidateLayer2_OrderFlowTrend()`

**Objectif:** Confirmer que l'orderflow supporte la direction.

**Indicateurs vérifiés:**
- VWAP Slope (tendance de prix)
- Volume profile
- Delta cumulatif
- Momentum score

**Conditions de passage:**
```cpp
// VWAP slope doit être aligné avec la direction
if (direction == 1 && vwap_slope > 0.01f) {
    // Tendance haussière confirmée
}

// Delta doit supporter
if (direction == 1 && delta_net > 0) {
    // Pression acheteuse
}
```

### 3.4 Layer 3 - Confluence

**Fichier:** `MIA_Layers.h` → `ValidateLayer3()`

**Objectif:** Score de confluence multi-facteurs.

**Composants du score:**
- Session (London/US Open bonus)
- VIX regime
- Momentum
- Volume
- VWAP position

**Seuil de passage:** `score >= 0.15f`

**VETO Anti-Trend:**
```cpp
// Si VWAP slope fortement contre nous → VETO!
if (direction == 1 && vwap_slope < -0.012f) {
    return VETO;  // Pas de LONG en tendance baissière forte
}
```

### 3.5 Layer 4 - Qualité (Grade)

**Fichier:** `MIA_Layers.h` → `ValidateLayer4()`

**Objectif:** Score de qualité final et grade.

**Calcul du score (0-100):**
```cpp
quality_score = 
    l1_confidence * 20 +    // Max 20 pts
    l2_confidence * 25 +    // Max 25 pts
    l3_confidence * 20 +    // Max 20 pts
    bn_score * 15 +         // Max 15 pts
    combo_aligned * 20;     // Max 20 pts
```

**Grades:**
| Grade | Score | Action |
|-------|-------|--------|
| **A** | ≥ 80 | Trade + Size ×1.5 + TP ×1.30 |
| **B** | ≥ 70 | Trade normal |
| **C** | ≥ 55 | Trade + Size ×0.75 |
| **D** | < 55 | **REJETÉ** |

---

## 4. SYSTÈME DE RÉGIME MULTI-FACTEURS

### 4.1 Concept

Le régime de marché détermine si on est en TREND ou RANGE, et ajuste automatiquement:
- La taille de position
- Le Take Profit
- L'activation du trailing stop

### 4.2 Calcul du score (0-100)

**Fichier:** `MIA_Config.h` → `CalculateMarketRegime()`

```cpp
REGIME_SCORE = 
    VWAP_SCORE (30 pts max) +     // Tendance de prix
    ATR_SCORE (25 pts max) +      // Volatilité
    VIX_SCORE (20 pts max) +      // Contexte macro
    CVD_SCORE (15 pts max) +      // Momentum orderflow
    STRUCTURE_SCORE (10 pts max)  // Position vs swings
```

### 4.3 Seuils VWAP (adaptés ES vs NQ)

```cpp
// ES (moins volatile)
thresh_strong = 0.05f;   // Fort trending
thresh_med = 0.03f;      // Trending modéré
thresh_weak = 0.015f;    // Faible

// NQ (plus volatile → seuils plus bas)
thresh_strong = 0.035f;
thresh_med = 0.02f;
thresh_weak = 0.01f;
```

### 4.4 Seuils CVD

```cpp
// CVD slope en centaines (100-500)
if (cvd_abs > 500) cvd_score = 15;   // Fort momentum
if (cvd_abs > 300) cvd_score = 12;   // Modéré
if (cvd_abs > 100) cvd_score = 8;    // Faible
```

### 4.5 Classification et ajustements

| Score | Régime | Size | TP | Trailing |
|-------|--------|------|----|---------| 
| **75-100** | `STRONG_TREND` | **×1.30** | **×1.40** | ✅ Agressif |
| **55-74** | `TREND` | ×1.00 | ×1.00 | ✅ Normal |
| **40-54** | `WEAK` | **×0.75** | **×0.85** | ✅ Prudent |
| **0-39** | `RANGE` | **×0.50** | **×0.70** | ❌ **OFF** |

### 4.6 Protection obstacle

**IMPORTANT:** Si le TP est basé sur un obstacle (GAMMA_WALL, PUT_SUP, etc.), le multiplicateur régime n'est **PAS** appliqué pour éviter de pousser le TP après l'obstacle.

```cpp
bool tp_based_on_obstacle = strstr(sltp.tp_based_on, "BEFORE_") != nullptr;

if (!tp_based_on_obstacle) {
    tp_distance *= regime.tp_multiplier;  // Appliquer
} else {
    // Garder TP original (avant l'obstacle)
}
```

---

## 5. POSITION SIZING DYNAMIQUE

### 5.1 Formule

**Fichier:** `MIA_Config.h` → `CalculatePositionSize()`

```cpp
qty = BASE_QTY × GRADE_MULT × VIX_MULT × DD_MULT × REGIME_MULT
```

### 5.2 Base Quantity (Micro)

```cpp
BASE_QTY_MES = 3;  // 3 Micro ES
BASE_QTY_MNQ = 2;  // 2 Micro NQ
```

### 5.3 Multiplicateurs Grade

| Grade | Multiplier |
|-------|------------|
| A | ×1.50 |
| B | ×1.00 |
| C | ×0.75 |
| D | ×0.00 (pas de trade) |

### 5.4 Multiplicateurs VIX

| VIX Regime | Multiplier |
|------------|------------|
| CALM (<15) | ×1.10 |
| NORMAL (15-25) | ×1.00 |
| VOLATILE (>25) | ×0.50 |

### 5.5 Multiplicateurs Drawdown

| Drawdown | Multiplier |
|----------|------------|
| < 3% | ×1.00 |
| 3-5% | ×0.75 |
| 5-8% | ×0.50 |
| > 8% | ×0.25 |

### 5.6 Exemple complet

```
Grade A + VIX Normal + DD 4% + STRONG_TREND
= 3 × 1.50 × 1.00 × 0.75 × 1.30
= 4.39 → 4 contrats MES
```

---

## 6. CALCUL SL/TP INTELLIGENT

### 6.1 Concept

**Fichier:** `MIA_SLTP_Calc.h` → `CalculateSLTP()`

Le SL/TP est calculé en fonction des **obstacles** sur le chemin:
- Gamma Walls
- Put Support / Call Resistance
- Rectangles Battle Navale (absorption zones)
- Single Prints

### 6.2 Logique TP

```
1. Chercher le PREMIER obstacle dans la direction du trade
2. Si obstacle trouvé et distance > min_reward:
   → TP = obstacle - buffer (3 ticks)
3. Si obstacle trop proche (R:R < 1.5):
   → VETO (pas de trade)
4. Si pas d'obstacle:
   → TP = distance par défaut (24 ticks ES, 40 ticks NQ)
```

### 6.3 Logique SL

```
1. SL = distance par défaut derrière le niveau L1
2. Limité par sl_max_ticks (hard limit)
3. Élargi si HQ trade (×1.15)
```

### 6.4 Multiplicateur TP

**Cap unique à ×1.50** pour éviter les TP irréalistes:

```cpp
float tp_mult_total = l4.tp_multiplier × regime.tp_multiplier;
if (tp_mult_total > 1.50f) tp_mult_total = 1.50f;
if (tp_mult_total < 0.70f) tp_mult_total = 0.70f;
```

---

## 7. TRAILING STOP CONDITIONNEL

### 7.1 Concept

**Fichier:** `MIA_Execution.h` → `UpdateTrailingStop()`

Le trailing stop est **désactivé en régime RANGE** pour éviter les whipsaws.

### 7.2 Activation

```cpp
// Condition d'activation
if (profit >= activation_dist && 
    !state.trailing_activated && 
    state.trailing_allowed) {  // ← Contrôlé par régime!
    
    state.trailing_activated = true;
}
```

### 7.3 Comportement par régime

| Régime | Trailing | Raison |
|--------|----------|--------|
| STRONG_TREND | ✅ Agressif | Laisser courir les gains |
| TREND | ✅ Normal | Standard |
| WEAK | ✅ Prudent | Serré |
| RANGE | ❌ **OFF** | Prix oscille, trailing = pertes |

---

## 8. CIRCUIT BREAKERS & RISK MANAGEMENT

### 8.1 Daily Loss Limits

**Fichier:** `MIA_Config.h`

```cpp
MAX_DAILY_LOSS_ES = -500.0f;     // $500 max perte ES
MAX_DAILY_LOSS_NQ = -500.0f;     // $500 max perte NQ
MAX_DAILY_LOSS_TOTAL = -1000.0f; // $1000 max total
```

### 8.2 Vérification

```cpp
if (g_es_state.pnl_today < MAX_DAILY_LOSS_ES) {
    // STOP trading ES pour aujourd'hui
    strcpy(g_dashboard.bot_action_es, "CIRCUIT_BREAKER");
}
```

### 8.3 Cooldown après position

```cpp
MIN_COOLDOWN_MS = 5000;  // 5 secondes entre trades
```

### 8.4 Position limits

```cpp
// Maximum 1 position par symbole
if (state.in_position) {
    return;  // Déjà en position
}
```

---

## 9. LOGGING & DEBUG

### 9.1 Journal de trades (JSONL)

**Chemin:** `D:\TRADING_SIERRA_CHART_AUTO\LOGS\TRADE_JOURNAL\{YYYY}\{MM}\trade_decisions_{YYYYMMDD}.jsonl`

**Format:**
```json
{
  "ts": "2026-02-01 15:30:45",
  "sym": "ES",
  "dir": 1,
  "price": 6050.25,
  "l1": {"ok": true, "conf": 0.85, "why": "PUT_SUP@6048"},
  "l2": {"ok": true, "conf": 0.72, "why": "OFTrend:0.65"},
  "l3": {"ok": true, "veto": false, "conf": 0.45},
  "l4": {"ok": true, "grade": "A", "qual": 82},
  "regime": {"name": "STRONG_TREND", "score": 78, "size_x": 1.30, "tp_x": 1.40},
  "sltp": {"sl": 6042, "tp": 6068, "based": "BEFORE_GAMMA_WALL"},
  "taken": true,
  "reason": "TRADE_TAKEN: L4=A Qty=4",
  "qty": 4
}
```

### 9.2 Logs Sierra Chart

Tous les événements importants sont loggés dans le message log de Sierra Chart:
- Évaluations de signal
- Rejets (avec raison)
- Trades pris
- Trailing activé
- Circuit breakers

### 9.3 Bottleneck Report

Rapport périodique (toutes les 60s) montrant où les signaux sont rejetés:

```
=== BOTTLENECK REPORT ES ===
Total: 150 | L1: 45% | L2: 20% | L3: 15% | L4: 10% | MIN: 10%
BOTTLENECK: L1 (structure)
```

### 9.4 Diagnostic Snapshot

**Fichier:** `DIAGNOSTIC_SNAPSHOT.json`

Export complet de toutes les données que le bot voit à un instant T pour debug.

---

## 10. CONFIGURATION & PARAMÈTRES

### 10.1 Configuration ES

```cpp
SymbolConfig CONFIG_ES = {
    "ES",           // symbol
    0.25f,          // tick_size
    1.25f,          // tick_value (Micro MES)
    20,             // l1_distance_max (ticks)
    0.50f,          // l2_min_confidence
    12,             // sl_default_ticks
    24,             // tp_default_ticks
    28,             // sl_max_ticks
    48,             // tp_max_ticks
    1.5f,           // min_rr_ratio
    3,              // tp_buffer_ticks
    1               // l4_combo_required
};
```

### 10.2 Configuration NQ

```cpp
SymbolConfig CONFIG_NQ = {
    "NQ",           // symbol
    0.25f,          // tick_size
    0.50f,          // tick_value (Micro MNQ)
    25,             // l1_distance_max (ticks)
    0.50f,          // l2_min_confidence
    20,             // sl_default_ticks
    40,             // tp_default_ticks
    35,             // sl_max_ticks
    80,             // tp_max_ticks
    1.5f,           // min_rr_ratio
    5,              // tp_buffer_ticks
    1               // l4_combo_required
};
```

### 10.3 Inputs Sierra Chart

Le bot expose des inputs configurables dans Sierra Chart:
- `Enable_ES_Trading` (Yes/No)
- `Enable_NQ_Trading` (Yes/No)
- `Rectangle_Trading` (Yes/No)
- `Max_Daily_Loss` (montant)

---

## 11. FLUX DE DONNÉES

### 11.1 Sources de données

```
Battle Navale (BN)           MenthorQ (MQ)
      │                            │
      ▼                            ▼
┌─────────────────────────────────────────────┐
│  MIA_DataReader.h    MIA_MenthorQ.h         │
│  (Parse spreadsheet)  (Parse levels)         │
└─────────────────────────────────────────────┘
      │                            │
      ▼                            ▼
┌─────────────────────────────────────────────┐
│  BN_Data struct       MenthorQ_Data struct  │
│  - edge_buy/sell      - gamma_wall          │
│  - cvd_slope          - put_support         │
│  - momentum_score     - call_resistance     │
│  - rectangles         - hvl, poc            │
└─────────────────────────────────────────────┘
                    │
                    ▼
            ┌──────────────┐
            │  MIA_Main    │
            │  (Pipeline)  │
            └──────────────┘
```

### 11.2 Cycle de mise à jour

```
Chaque tick (ou barre selon config):
1. Lire BN_Data (Battle Navale spreadsheet)
2. Lire MenthorQ_Data (niveaux)
3. Calculer régime marché
4. Si pas en position:
   - Évaluer L1 → L2 → L3 → L4
   - Si tous passent: envoyer ordre
5. Si en position:
   - Update trailing stop
   - Check exit conditions
6. Sauvegarder dashboard
```

---

## 12. FAQ TECHNIQUE

### Q: Pourquoi 4 layers au lieu d'un seul score?

**R:** Chaque layer a une fonction spécifique:
- L1: Valide la **structure** (où trader)
- L2: Valide le **momentum** (quand trader)
- L3: Valide le **contexte** (conditions favorables)
- L4: Valide la **qualité** (trade A/B/C/D)

Un filtrage progressif élimine les mauvais trades tôt.

### Q: Pourquoi désactiver le trailing en RANGE?

**R:** En range, le prix oscille. Le trailing se ferait toucher par le bruit, puis le prix reviendrait dans notre direction. Résultat: petits gains au lieu de TP complet.

### Q: Comment le bot évite de trader après les obstacles?

**R:** `CalculateSLTP()` cherche le premier obstacle et place le TP **AVANT**. Si l'obstacle est trop proche (R:R < 1.5), le trade est **VETO**.

### Q: Pourquoi des seuils différents ES vs NQ?

**R:** NQ est ~2x plus volatile. Un slope de 0.03 sur ES = fort trending, mais sur NQ c'est normal. Les seuils sont adaptés via `is_nq`.

### Q: Comment analyser les rejets?

**R:** 
1. Lire le journal JSONL: `D:\TRADING_SIERRA_CHART_AUTO\LOGS\TRADE_JOURNAL\...`
2. Filtrer par `"taken": false`
3. Regarder `"reason"` pour la cause

### Q: Comment modifier les paramètres?

**R:**
1. Éditer `MIA_Config.h`
2. Recompiler la DLL via Sierra Chart Remote Build
3. Recharger le study dans Sierra Chart

---

## ANNEXE A: STRUCTURES DE DONNÉES

### BN_Data (Battle Navale)

```cpp
struct BN_Data {
    float score;              // Score global 0-100
    float edge_buy, edge_sell;
    float color_up, color_down;
    float long_down_up, long_up_down;
    float cvd_slope;
    float momentum_score;
    float swing_high, swing_low;
    // ... 50+ champs
};
```

### MenthorQ_Data

```cpp
struct MenthorQ_Data {
    float gamma_wall, gamma_wall_0dte;
    float put_support, put_support_0dte;
    float call_resistance, call_resistance_0dte;
    float hvl, hvl_0dte;
    float poc, day_min, day_max;
    // ...
};
```

### RegimeResult

```cpp
struct RegimeResult {
    MarketRegime regime;      // STRONG_TREND, TREND, WEAK, RANGE
    float score;              // 0-100
    float size_multiplier;    // Ajustement taille
    float tp_multiplier;      // Ajustement TP
    bool trailing_enabled;    // Trailing ON/OFF
};
```

---

## ANNEXE B: CODES D'ERREUR

| Code | Signification |
|------|---------------|
| `L1_REJECT` | Pas de niveau MenthorQ proche |
| `L2_REJECT` | OrderFlow non aligné |
| `L3_VETO` | VWAP anti-trend fort |
| `L3_REJECT` | Score confluence < 0.15 |
| `L4_REJECT` | Grade D (score < 55) |
| `MIN_REJECT` | Seuils minimum non atteints |
| `SLTP_VETO` | R:R insuffisant (obstacle bloque) |
| `CIRCUIT_BREAKER` | Daily loss limit atteint |

---

## ANNEXE C: CHANGELOG

### v2.0 (01/02/2026)
- Régime multi-facteurs (VWAP+ATR+VIX+CVD+Structure)
- Position sizing dynamique (Grade+VIX+DD+Régime)
- Trailing conditionnel (OFF en RANGE)
- Protection obstacle (TP pas étendu si obstacle)
- Journal de trades JSONL
- Seuils adaptés ES vs NQ

### v1.x
- 4 Layers basiques
- SL/TP avec obstacles
- Circuit breakers

---

**FIN DU DOCUMENT**

*Généré automatiquement par MIA Trading System - 01/02/2026*
