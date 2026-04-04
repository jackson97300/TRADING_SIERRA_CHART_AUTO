# 📊 MIA AUTO-TRADER BATAILLE NAVALE v1.0
## Documentation Complète du Système de Trading Automatique

**Version:** 1.0
**Date:** 21 Janvier 2026
**Auteur:** MIA Trading System

---

# 📋 TABLE DES MATIÈRES

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du Système](#2-architecture-du-système)
3. [Configuration](#3-configuration)
4. [Collecte des Données](#4-collecte-des-données)
5. [Système de Validation (Layers 1-4)](#5-système-de-validation-layers-1-4)
6. [Bataille Navale Avancée](#6-bataille-navale-avancée)
7. [Trade Haute Qualité](#7-trade-haute-qualité)
8. [Gestion des Ordres](#8-gestion-des-ordres)
9. [Protection et Risk Management](#9-protection-et-risk-management)
10. [Logging et Monitoring](#10-logging-et-monitoring)
11. [Flux de Décision Complet](#11-flux-de-décision-complet)

---

# 1. VUE D'ENSEMBLE

## 1.1 Description

MIA Auto-Trader est un système de trading automatique pour Sierra Chart qui combine:
- **MenthorQ**: Niveaux d'options (GEX, HVL, Gamma Wall, etc.)
- **Bataille Navale**: Order flow et visuels (Edge Zones, Color Up/Down, Rectangles)
- **Architecture 4 Layers**: Validation multi-niveaux des signaux

## 1.2 Symboles Supportés

| Symbole | Tick Size | Tick Value | Description |
|---------|-----------|------------|-------------|
| **ES** | 0.25 pts | $12.50 | E-mini S&P 500 |
| **NQ** | 0.25 pts | $5.00 | E-mini Nasdaq 100 |

## 1.3 Modes de Fonctionnement

| Mode | Session | Description |
|------|---------|-------------|
| **PRODUCTION** | 00:00 - 21:00 FR | Horaires stricts avec pause US Open |
| **TEST** | 00:00 - 23:00 FR | Session étendue pour tests |

---

# 2. ARCHITECTURE DU SYSTÈME

## 2.1 Structure du Code (14 Sections)

```
┌─────────────────────────────────────────────────────────────────┐
│ SECTION 1: CONFIGURATION ET CONSTANTES                          │
│   - SymbolConfig (ES/NQ)                                        │
│   - Sessions, Modes, Timeouts                                   │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 2: STRUCTURES DE DONNÉES                                │
│   - BotState (état du bot par symbole)                          │
│   - BN_Data (données Bataille Navale)                           │
│   - MenthorQ_Data (niveaux options)                             │
│   - TradeSnapshot (enregistrement trades)                       │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 3: VARIABLES GLOBALES                                   │
│   - g_es_state, g_nq_state                                      │
│   - g_dashboard                                                 │
│   - g_market_live                                               │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 4: FONCTIONS UTILITAIRES                                │
│   - GetMinutesSinceMidnightET()                                 │
│   - IsWithinTradingSession()                                    │
│   - ReadStudyValue()                                            │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 5: COLLECTE DONNÉES BATAILLE NAVALE                     │
│   - CollectBN_Data()                                            │
│   - Calcul score BN                                             │
│   - Extension Lines, Gros Rectangles                            │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 6: COLLECTE DONNÉES MENTHORQ                            │
│   - CollectMenthorQ_Data()                                      │
│   - GEX 1-10, HVL, Gamma Wall, etc.                             │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 7: LAYER 1 - MENTHORQ LEVELS                            │
│   - ValidateLayer1()                                            │
│   - DetectRectangleConfluence()                                 │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 8: LAYER 2 - ORDERFLOW + BATAILLE NAVALE                │
│   - DetectHighQualityTrade()                                    │
│   - ValidateLayer2()                                            │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 9: LAYER 3 - CONTEXT                                    │
│   - ValidateLayer3()                                            │
│   - VWAP Slope, Distance checks                                 │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 10: LAYER 4 - COMBO FILTER                              │
│   - ValidateLayer4()                                            │
│   - 2/4 alignement requis                                       │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 11: CALCUL SL/TP PROTÉGÉ                                │
│   - CalculateProtectedSLTP()                                    │
│   - CalculateBNAnchor()                                         │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 12: GESTION DES ORDRES                                  │
│   - SendBracketOrder()                                          │
│   - UpdateTrailingStop()                                        │
│   - ProcessPositionClosed()                                     │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 13: SNAPSHOT ET LOGGING                                 │
│   - LogTradeSnapshot()                                          │
│   - LogTradeWhy()                                               │
│   - WriteDiscordEvent()                                         │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 14: STUDY PRINCIPALE                                    │
│   - scsf_MIA_AutoTrader_BN()                                    │
│   - Boucle principale de trading                                │
└─────────────────────────────────────────────────────────────────┘
```

## 2.2 Charts Sierra Chart Utilisés

### Instance "MIA IA SYSTEM" (Execution)

| Chart | Symbole | Type | Usage |
|-------|---------|------|-------|
| 1 | ES | Footprint | Signaux BN (Edge, Color, etc.) |
| 2 | NQ | Footprint | Signaux BN NQ |
| 3 | ES | Barres | MenthorQ + Reversals |
| 4 | NQ | Barres | MenthorQ + Reversals NQ |
| 23 | ES | Execution | Bot ES |
| 25 | NQ | Execution | Bot NQ |

---

# 3. CONFIGURATION

## 3.1 Configuration ES

```cpp
const SymbolConfig CONFIG_ES = {
    "ES",
    0.25f,      // tick_size
    12.50f,     // tick_value

    // SL/TP
    16,         // sl_default_ticks (4 pts)
    12,         // sl_min_ticks (3 pts)
    24,         // sl_max_ticks (6 pts)
    3,          // sl_buffer_ticks
    20,         // tp_default_ticks (5 pts)
    30,         // tp_max_ticks (7.5 pts)
    2,          // tp_buffer_ticks
    1.25f,      // min_rr_ratio

    // Trailing (DÉSACTIVÉ)
    9999,       // trailing_activation_ticks
    12,         // trailing_distance_ticks

    // Cooldown
    3,          // max_consecutive_losses
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min
};
```

## 3.2 Configuration NQ

```cpp
const SymbolConfig CONFIG_NQ = {
    "NQ",
    0.25f,      // tick_size
    5.00f,      // tick_value

    // SL/TP (plus large car volatil)
    28,         // sl_default_ticks (7 pts)
    20,         // sl_min_ticks (5 pts)
    40,         // sl_max_ticks (10 pts)
    5,          // sl_buffer_ticks
    35,         // tp_default_ticks (8.75 pts)
    50,         // tp_max_ticks (12.5 pts)
    3,          // tp_buffer_ticks
    1.25f,      // min_rr_ratio

    // Trailing (DÉSACTIVÉ)
    9999,       // trailing_activation_ticks
    16,         // trailing_distance_ticks

    // Cooldown
    4,          // max_consecutive_losses
    45,         // cooldown_after_losses_min
    10,         // cooldown_win_min
    15,         // cooldown_loss_min
};
```

## 3.3 Sessions de Trading

| Session | Heure FR | Heure ET | Action |
|---------|----------|----------|--------|
| **Asia Open** | 00:00 | 18:00 | Début trading |
| **London** | 08:00 | 02:00 | Trading normal |
| **Pre-US Pause** | 15:00 | 09:00 | Pause 30 min |
| **US Open** | 15:30 | 09:30 | Reprise trading |
| **US OPR End** | 15:45 | 09:45 | Fin Opening Range |
| **Session End** | 21:00 | 15:00 | Fin trading |

---

# 4. COLLECTE DES DONNÉES

## 4.1 Données Bataille Navale (BN_Data)

### 4.1.1 Signaux Footprint

| Champ | Description | Interprétation |
|-------|-------------|----------------|
| `edge_buy` | Boules vertes (imbalance acheteur) | BULLISH si > edge_sell |
| `edge_sell` | Boules rouges (imbalance vendeur) | BEARISH si > edge_buy |
| `color_up` | Momentum haussier | BULLISH |
| `color_down` | Momentum baissier | BEARISH |
| `absorb_bid` | Absorption acheteurs | Support défendu |
| `absorb_ask` | Absorption vendeurs | Résistance défendue |
| `rotation_up` | Pivot haussier | Retournement BULL |
| `rotation_down` | Pivot baissier | Retournement BEAR |

### 4.1.2 Signaux Barres

| Champ | Description | Interprétation |
|-------|-------------|----------------|
| `long_down_up` | Rectangle vert (reversal haussier) | LONG signal |
| `long_up_down` | Rectangle rouge (reversal baissier) | SHORT signal |
| `double_bid` | Zone achat touchée (ES) | Support confirmé |
| `double_ask` | Zone vente touchée (ES) | Résistance confirmée |

### 4.1.3 Gros Rectangles Edge Zone (NOUVEAU)

```cpp
// Subgraphs 48-57 des Edge Zone Imbalance studies
float edge_rect_buy_bottom[5];   // Bottom des rectangles BUY
float edge_rect_buy_top[5];      // Top des rectangles BUY
float edge_rect_sell_bottom[5];  // Bottom des rectangles SELL
float edge_rect_sell_top[5];     // Top des rectangles SELL
bool price_in_edge_rect_buy;     // Prix DANS un rectangle vert
bool price_in_edge_rect_sell;    // Prix DANS un rectangle rouge
```

### 4.1.4 Bataille Navale Avancée (NOUVEAU)

```cpp
// Règle "Pas de boule opposée sous/dessus"
float lowest_edge_buy;           // Plus bas de tous les edge_buy
float highest_edge_sell;         // Plus haut de tous les edge_sell
bool bn_attack_long_valid;       // LONG: pas de rouge sous le vert
bool bn_attack_short_valid;      // SHORT: pas de vert au-dessus du rouge

// Empilement (force de l'attaque)
int stacked_buy_zones;           // Rectangles verts empilés
int stacked_sell_zones;          // Rectangles rouges empilés
float attack_strength_buy;       // Force attaque acheteurs (0-1)
float attack_strength_sell;      // Force attaque vendeurs (0-1)

// Cohérence directionnelle
bool all_signals_bullish;        // TOUS signaux bullish
bool all_signals_bearish;        // TOUS signaux bearish
float directional_coherence;     // Score cohérence (-1 à +1)
```

## 4.2 Données MenthorQ

| Champ | Score | Description |
|-------|-------|-------------|
| `hvl` | 3 | High Volume Level |
| `hvl_0dte` | 3 | HVL 0DTE |
| `gamma_wall` | 3 | Mur Gamma |
| `gex[0-2]` | 3 | GEX 1-3 (majeurs) |
| `gex[3-4]` | 2 | GEX 4-5 (importants) |
| `gex[5-9]` | 1 | GEX 6-10 (mineurs) |
| `put_support` | 2 | Support Put |
| `call_resistance` | 2 | Résistance Call |
| `vah` / `val` | 2 | Value Area High/Low |
| `blind_spots[0-8]` | 1 | Blind Spots |
| `vwap` | - | VWAP Daily |
| `vwap_up1/dn1` | - | VWAP ±1 SD |

## 4.3 Calcul du Score BN

```cpp
// Force acheteuse
buyer_strength = edge_buy + color_up + absorb_bid + rotation_up * 0.5f
               + long_down_up * 2.0f + double_bid + inst_buy * 0.3f;

// Force vendeuse
seller_strength = edge_sell + color_down + absorb_ask + rotation_down * 0.5f
                + long_up_down * 2.0f + double_ask + inst_sell * 0.3f;

// Score normalisé [-1, +1]
bn.score = (buyer_strength - seller_strength) / (buyer_strength + seller_strength);

// Signal discret
bn.signal = (bn.score > 0.15f) ? +1 : (bn.score < -0.15f) ? -1 : 0;
```

---

# 5. SYSTÈME DE VALIDATION (LAYERS 1-4)

## 5.1 LAYER 1 - MenthorQ Levels

### 5.1.1 Fonction

```cpp
Layer1Result ValidateLayer1(
    SCStudyInterfaceRef sc,
    const MenthorQ_Data& mq,
    float current_price,
    const SymbolConfig& config,
    float momentum_score,
    const BN_Data* bn,
    bool is_es
);
```

### 5.1.2 Logique

1. **Collecter tous les niveaux MenthorQ** avec leur score (1-3)
2. **Trouver le niveau le plus proche** dans une fenêtre de distance
3. **Vérifier confluence BN** si score = 1 (mineur)
4. **Déterminer direction** basée sur position du prix vs niveau

### 5.1.3 Scores des Niveaux

| Score | Niveaux | Comportement |
|-------|---------|--------------|
| **3 (Majeur)** | HVL, Gamma, GEX 1-3 | Accepté directement |
| **2 (Important)** | Put/Call, VAH/VAL, GEX 4-5 | Accepté directement |
| **1 (Mineur)** | GEX 6-10, Blind Spots | Requiert confluence BN |

### 5.1.4 Layer 1B - Rectangle Confluence

Si aucun niveau MenthorQ proche, chercher des rectangles BN avec confluence:

```cpp
RectangleSignal DetectRectangleConfluence(
    SCStudyInterfaceRef sc,
    const BN_Data& bn,
    const MenthorQ_Data& mq,
    float current_price,
    const SymbolConfig& config,
    bool is_nq
);
```

**Conditions:**
- Rectangle vert (long_down_up) proche → LONG
- Rectangle rouge (long_up_down) proche → SHORT
- Niveau MenthorQ score ≥ 1 à proximité (< 15 ticks)

## 5.2 LAYER 2 - OrderFlow + Bataille Navale

### 5.2.1 Fonction

```cpp
Layer2Result ValidateLayer2(
    int direction,
    const BN_Data& bn_primary,
    const BN_Data& bn_secondary,
    float vix,
    float delta,
    float buy_pct,
    const SymbolConfig& config,
    bool is_nq
);
```

### 5.2.2 Validations

1. **BN Score dans la direction**
   - LONG: bn_score >= seuil (adaptatif VIX)
   - SHORT: bn_score <= seuil

2. **Signal visuel requis**
   - Au moins 1 parmi: color_up/down, edge_buy/sell, rectangle, absorb, price_in_edge_rect

3. **VETO Signal Opposé**

| Direction | VETO si... |
|-----------|------------|
| **LONG** | `price_in_edge_rect_sell`, `edge_sell > 0`, `absorb_ask > 5`, `!bn_attack_long_valid` |
| **SHORT** | `price_in_edge_rect_buy`, `edge_buy > 0`, `absorb_bid > 5`, `!bn_attack_short_valid` |

4. **Corrélation ES/NQ** (pour NQ)
   - Vérifie que ES confirme ou lead
   - VETO si forte divergence

### 5.2.3 Bonus Bataille Navale Avancée

```cpp
if (direction == 1 && bn.bn_attack_long_valid) {
    bn_attack_bonus += bn.attack_strength_buy * 0.10f;
    if (bn.all_signals_bullish) bn_attack_bonus += 0.08f;
}
```

## 5.3 LAYER 3 - Context

### 5.3.1 Fonction

```cpp
Layer3Result ValidateLayer3(
    int direction,
    const BN_Data& bn,
    float current_price,
    const MenthorQ_Data& mq,
    float vix,
    float atr,
    const char* session,
    bool is_nq
);
```

### 5.3.2 Vérifications

1. **Distance VWAP**
   - Trop loin du VWAP = risque élevé
   - Seuils adaptatifs selon VIX

2. **VWAP Slope VETO**
   ```cpp
   if (direction == 1 && vwap_slope < -0.012f) {
       // VETO LONG en tendance baissière forte
   }
   if (direction == -1 && vwap_slope > 0.012f) {
       // VETO SHORT en tendance haussière forte
   }
   ```

3. **Session Context**
   - Asia: seuils plus stricts
   - US: seuils normaux

## 5.4 LAYER 4 - Combo Filter

### 5.4.1 Fonction

```cpp
Layer4Result ValidateLayer4(
    int direction,
    float buy_pct,
    float cum_delta,
    float bn_score,
    float vwap_slope,
    const SymbolConfig& config
);
```

### 5.4.2 Critères (4 points)

| Critère | LONG OK si... | SHORT OK si... |
|---------|---------------|----------------|
| **buy_pct** | > 0.52 | < 0.48 |
| **cum_delta** | > 0 | < 0 |
| **bn_score** | > 0 | < 0 |
| **vwap_slope** | > -0.005 | < 0.005 |

**Requis: 2/4 critères alignés minimum**

---

# 6. BATAILLE NAVALE AVANCÉE

## 6.1 Règle "Pas de Boule Opposée"

### Pour LONG:
```
✅ VALIDE:
   Boule verte ────
   Boule verte ────
   Boule verte ────  ← Plus bas vert
   (rien en dessous)

❌ INVALIDE:
   Boule verte ────
   Boule verte ────
   Boule ROUGE ────  ← Rouge SOUS le vert!
```

### Pour SHORT:
```
✅ VALIDE:
   (rien au dessus)
   Boule rouge ────  ← Plus haut rouge
   Boule rouge ────
   Boule rouge ────

❌ INVALIDE:
   Boule VERTE ────  ← Vert AU-DESSUS du rouge!
   Boule rouge ────
   Boule rouge ────
```

## 6.2 Empilement (Attaque Coordonnée)

| Rectangles Empilés | Force Attaque | Interprétation |
|--------------------|---------------|----------------|
| 1 | 0.4 | Zone isolée |
| 2 | 0.7 | Attaque forte |
| 3+ | 1.0 | Attaque MASSIVE |

## 6.3 Cohérence Directionnelle

Compte les signaux dans chaque direction:
- `edge_buy > edge_sell` → +1 bullish
- `color_up > color_down` → +1 bullish
- `rotation_up > rotation_down` → +1 bullish
- etc.

**`all_signals_bullish` = 4+ signaux bullish ET 0 bearish**

---

# 7. TRADE HAUTE QUALITÉ

## 7.1 Critères HQ

| Critère | Points | Obligatoire? |
|---------|--------|--------------|
| Niveau Score ≥ 2 | +20% | ✅ OUI |
| visual_count ≥ 2 | +15% | Non |
| stacked_zones ≥ 2 OU attack_strength ≥ 0.6 | +20% | Non |
| bn_attack_valid = true | +15% | Non |
| Cohérence directionnelle > 0.5 | +10% | Non |
| TP sans obstacle | +10% | Non |

**Seuil HQ: ≥ 4 critères ET score ≥ 60%**

## 7.2 Multiplicateurs de Risque

| Type | TP Multiplier | SL Multiplier |
|------|---------------|---------------|
| **Standard** | 1.0x | 1.0x |
| **Haute Qualité** | 1.5x | 1.2x |
| **HQ Premium** (cohérence totale) | 2.0x | 1.2x |

---

# 8. GESTION DES ORDRES

## 8.1 Type d'Ordres

Le bot utilise des **Bracket Orders** (Parent + Enfants):

```
PARENT: Market Order (entrée)
├── ENFANT 1: Stop Market (SL)
└── ENFANT 2: Limit Order (TP)
```

## 8.2 Entrée avec Ancre BN

```cpp
float anchor = CalculateBNAnchor(direction, current_price, bn, tick_size);

// Si proche de l'ancre (< 2 ticks) → MARKET
// Sinon → LIMIT à l'ancre (si < 5 ticks) ou REJET
```

## 8.3 Trailing Stop (DÉSACTIVÉ actuellement)

```cpp
// Activation si profit >= activation_ticks
if (profit >= activation_dist && !trailing_activated) {
    trailing_activated = true;
    trailing_sl = current_price - trailing_dist;  // LONG
}

// Mise à jour (suit le prix)
if (trailing_activated) {
    new_sl = current_price - trailing_dist;
    if (new_sl > trailing_sl) trailing_sl = new_sl;

    // Exit si prix <= trailing_sl
    if (current_price <= trailing_sl) {
        FlattenAndCancelAllOrders();
    }
}
```

---

# 9. PROTECTION ET RISK MANAGEMENT

## 9.1 Calcul SL Protégé

Le SL est placé derrière le niveau le plus proche:

```cpp
// Chercher niveau pour SL
for (niveau in [GEX, HVL, VWAP, Extension Lines, Rectangles]) {
    if (direction == LONG && niveau < entry_price) {
        // Niveau sous l'entrée = support potentiel
        sl_price = niveau - buffer;
    }
}

// Limites
sl_price = clamp(sl_price, sl_min, sl_max);
```

## 9.2 Vérification R:R

```cpp
float risk = |entry - sl|;
float reward = |tp - entry|;
float rr = reward / risk;

if (rr < min_rr_ratio) {
    // VETO - R:R insuffisant
}
```

## 9.3 Détection d'Obstacles

Avant de valider le TP, vérifie qu'il n'y a pas d'obstacle:

```cpp
for (niveau in niveaux_entre_entry_et_tp) {
    if (distance < min_reward) {
        // VETO - obstacle bloque le R:R
        return INVALID;
    }
}
```

## 9.4 Cooldowns

| Événement | Durée |
|-----------|-------|
| Après WIN | 10 min |
| Après LOSS | 15 min |
| Après 3 losses consécutifs | 45 min |
| Détection news/spread | 30 min |

## 9.5 Flat Forcé

Le bot se flat automatiquement si:
- Hors session de trading
- Détection de news (spread anormal)
- Cooldown actif

---

# 10. LOGGING ET MONITORING

## 10.1 Fichiers de Log

### Trades WIN
```
TRADING_SIERRA_CHART_AUTO/LOGS/TRADES_WIN/ES_WIN_20260121.log
```

### Trades LOSS
```
TRADING_SIERRA_CHART_AUTO/LOGS/TRADES_LOSS/ES_LOSS_20260121.log
```

### Rejets
```
TRADING_SIERRA_CHART_AUTO/LOGS/REJETS/ES_REJETS_20260121.log
```

### Trade WHY Journal
```
TRADING_SIERRA_CHART_AUTO/LOGS/TRADES_WHY/ES/ES_WHY_20260121.csv
```

## 10.2 Dashboard JSON

```json
{
  "timestamp": "2026-01-21T16:30:00",
  "bot_status": "RUNNING",
  "mode": "TEST",
  "es": {
    "status": "SCANNING",
    "trades_today": 2,
    "wins_today": 1,
    "losses_today": 1,
    "pnl_today": -25.00
  },
  "nq": { ... }
}
```

## 10.3 Discord Notifications

Le bot écrit des événements JSON pour un bridge Python:
- `TRADE_OPENED`: Nouvelle position
- `TRADE_CLOSED`: Position fermée avec P&L

---

# 11. FLUX DE DÉCISION COMPLET

```
┌─────────────────────────────────────────────────────────────────┐
│                    BOUCLE PRINCIPALE                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. VÉRIFICATIONS PRÉLIMINAIRES                                  │
│    ├── IsWithinTradingSession? → Non → FLAT                     │
│    ├── Cooldown actif? → Oui → ATTENDRE                         │
│    ├── Déjà en position? → Oui → Gérer position                 │
│    └── News/Spread anormal? → Oui → BLOQUER                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. COLLECTE DONNÉES                                             │
│    ├── CollectBN_Data(ES/NQ)                                    │
│    ├── CollectMenthorQ_Data(ES/NQ)                              │
│    ├── GetVIX_Live()                                            │
│    └── CalculateVWAPSlope()                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. LAYER 1 - NIVEAU MENTHORQ                                    │
│    ├── ValidateLayer1() → Niveau proche?                        │
│    └── DetectRectangleConfluence() → Rectangle BN?              │
│                                                                 │
│    RÉSULTAT: direction, level_name, confidence, importance_score│
│                                                                 │
│    ❌ REJET si: Aucun niveau proche                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. LAYER 2 - ORDERFLOW                                          │
│    ├── ValidateLayer2() → BN score OK?                          │
│    ├── Signal visuel présent?                                   │
│    ├── VETO signal opposé?                                      │
│    └── Corrélation ES/NQ OK?                                    │
│                                                                 │
│    ❌ VETO si: edge_sell > 0 pour LONG                          │
│    ❌ VETO si: edge_buy > 0 pour SHORT                          │
│    ❌ VETO si: price_in_edge_rect opposé                        │
│    ❌ VETO si: bn_attack_*_valid = false                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. LAYER 3 - CONTEXT                                            │
│    ├── ValidateLayer3() → Context OK?                           │
│    ├── Distance VWAP acceptable?                                │
│    └── VWAP Slope compatible?                                   │
│                                                                 │
│    ❌ VETO si: LONG avec VWAP slope < -0.012 (bearish)          │
│    ❌ VETO si: SHORT avec VWAP slope > 0.012 (bullish)          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. LAYER 4 - COMBO FILTER                                       │
│    └── ValidateLayer4() → 2/4 alignés?                          │
│                                                                 │
│    ❌ REJET si: combo_aligned < 2                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. CALCUL SL/TP                                                 │
│    ├── CalculateProtectedSLTP()                                 │
│    └── Vérifier R:R et obstacles                                │
│                                                                 │
│    ❌ VETO si: Obstacle bloque R:R                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. DÉTECTION TRADE HAUTE QUALITÉ                                │
│    ├── DetectHighQualityTrade()                                 │
│    └── Si HQ → Ajuster TP×1.5 ou TP×2.0                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. ENTRÉE                                                       │
│    ├── CalculateBNAnchor() → Prix optimal                       │
│    ├── LogTradeWhy() → Journal décision                         │
│    └── SendBracketOrder() → TRADE!                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 10. GESTION POSITION                                            │
│    ├── UpdateTrailingStop() (si activé)                         │
│    ├── ProcessPositionClosed() → Détecter TP/SL hit             │
│    ├── Calculer P&L                                             │
│    ├── LogTradeSnapshot()                                       │
│    ├── NotifyDiscordTradeClosed()                               │
│    └── Appliquer Cooldown                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

# 📊 RÉSUMÉ

Le système MIA Auto-Trader est un bot de trading sophistiqué qui:

1. **Collecte** les données MenthorQ (options) et Bataille Navale (order flow)
2. **Valide** chaque signal à travers 4 layers de filtrage
3. **Applique** des règles avancées de Bataille Navale (empilement, cohérence, pas de signal opposé)
4. **Détecte** les trades haute qualité pour augmenter le risque
5. **Calcule** des SL/TP protégés avec vérification d'obstacles
6. **Exécute** des bracket orders avec gestion de position
7. **Log** toutes les décisions pour analyse post-trade

**Points forts:**
- Multi-layer validation (4 filtres)
- Bataille Navale avancée avec analyse spatiale
- Trade Haute Qualité avec risque adaptatif
- Protection robuste (SL protégé, R:R check, obstacles)
- Logging complet pour audit

---

*Document généré le 21/01/2026 - Version 1.0*
