# 📸 MIA DataDumper V2 — Guide d'Intégration

## 🎯 Objectif

Capturer **100% des données** que le bot voit à chaque seconde pour :
1. **Backtesting fidèle** — rejouer exactement les conditions de marché
2. **ML Pattern Discovery** — trouver des patterns cachés avec Python/sklearn
3. **Analyse post-session** — comprendre chaque trade/rejet
4. **Optimisation** — tester de nouveaux paramètres sans risque

## 📊 Comparatif V1 vs V2

| Données | V1 (DataDumper) | V2 (Snapshot) |
|---------|:-:|:-:|
| BN Footprint (edge, color, absorb...) | ✅ | ✅ |
| BN Barres | ✅ | ✅ |
| BN Ordres 10/30/100/150 | ✅ | ✅ |
| **BN Ordres 400/1000** | ❌ | ✅ |
| **BN Double Ask/Bid** | ❌ | ✅ |
| BN FPBS (delta, CVD, POC) | ✅ | ✅ |
| BN Scores calculés | ✅ | ✅ |
| **BN Momentum Shift + Dir. Coherence** | ❌ | ✅ |
| BN Rectangles (count/price) | ✅ | ✅ |
| **BN Fresh Rectangles** | ❌ | ✅ |
| **BN Edge Zone Rectangles (in/ratio)** | ❌ | ✅ |
| **BN Advanced (attack, stacked, subtile)** | ❌ | ✅ |
| BN Delta Divergence | ✅ | ✅ |
| BN Swing + Single Prints | ✅ | ✅ |
| **BN Session OHLC** | ❌ | ✅ |
| **BN Session Volume Profile (VPOC/VAH/VAL/HVN/LVN)** | ❌ | ✅ |
| **BN VWAP + SD Bands (±1σ, ±2σ)** | ❌ | ✅ |
| **BN Extension Lines (nearest, distances)** | ❌ | ✅ |
| **BN Range Detection** | ❌ | ✅ |
| **BN LVN Levels (nearest above/below)** | ❌ | ✅ |
| MenthorQ Niveaux Primaires | ✅ | ✅ |
| MenthorQ VWAP | ✅ | ✅ |
| MenthorQ GEX (10) | ✅ | ✅ |
| MenthorQ Blind Spots (9) | ✅ | ✅ |
| **MenthorQ Distances (GEX/Blind/Gamma/Call/Put)** | ❌ | ✅ |
| MenthorQ Previous Day | ✅ | ✅ |
| **Composite Profiles (5 périodes × 6 niveaux)** | ❌ | ✅ |
| **CP Agrégés (nearest LVN/HVN + confluence)** | ❌ | ✅ |
| Indicateurs Globaux | ✅ | ✅ |
| **Market Regime (score + classification)** | ❌ | ✅ |
| État Bot (basique) | ✅ | ✅ |
| **État Bot (trailing, BE, consec_losses, CB)** | ❌ | ✅ |
| Layers (L1-L4) | ⚠️ Jamais appelé | ✅ |
| **SLTP Result** | ❌ | ✅ |
| **File handle persistant** | ❌ | ✅ |
| **Buffer unique (performance)** | ❌ | ✅ |

**V1 : ~50 champs → V2 : ~180+ champs**

## 🔧 Intégration dans MIA_Main.cpp

### Étape 1 : Ajouter le #include

Dans `MIA_Main.cpp`, après les autres includes :

```cpp
#include "MIA_DataDumper.h"      // V1 existant (garder pour compatibilité)
#include "MIA_DataDumper_V2.h"   // V2 snapshot complet
```

### Étape 2 : Remplacer les appels DumpBotDataSimple

**AVANT** (lignes ~515-520) :
```cpp
DumpBotDataSimple(sc, false, bn_es, mq_es, g_es_state, current_price_es,
                  vix, g_market_live.vix_regime, atr_es, g_dashboard.current_session);
DumpBotDataSimple(sc, true, bn_nq, mq_nq, g_nq_state, current_price_nq,
                  vix, g_market_live.vix_regime, atr_nq, g_dashboard.current_session);
```

**APRÈS** :
```cpp
// ─── SNAPSHOT V2: Données complètes (sans layers, appelé chaque seconde) ───
WriteSnapshotDataOnly(sc, false, bn_es, mq_es, cp_es, g_es_state, current_price_es,
                      vix, g_market_live.vix_regime, atr_es, 0.0f,
                      g_market_live.vwap_slope_es, g_dashboard.current_session,
                      nullptr);  // regime sera ajouté quand calculé
WriteSnapshotDataOnly(sc, true, bn_nq, mq_nq, cp_nq, g_nq_state, current_price_nq,
                      vix, g_market_live.vix_regime, atr_nq, 0.0f,
                      g_market_live.vwap_slope_nq, g_dashboard.current_session,
                      nullptr);
```

### Étape 3 : Snapshot COMPLET avec Layers (quand un signal est évalué)

Après l'évaluation des layers (dans les blocs ES et NQ), ajouter :

```cpp
// ─── SNAPSHOT V2: Avec layers (quand signal évalué) ───
WriteFullSnapshot(sc, false /*is_nq*/, bn_es, mq_es, cp_es, g_es_state,
    current_price_es, vix, g_market_live.vix_regime, atr_es, 0.0f,
    g_market_live.vwap_slope_es, g_dashboard.current_session,
    &regime_es,  // Market regime
    &l1, &l2, &l3, &l4,  // Layers
    &sltp  // SL/TP si trade, nullptr sinon
);
```

### Étape 4 : Reset quotidien

Dans la fonction de reset quotidien :
```cpp
ResetSnapshotCounters();  // Ferme les fichiers et remet les compteurs à 0
```

### Étape 5 : MarketLiveData dans un header

⚠️ `MarketLiveData` et `g_market_live` sont actuellement dans `MIA_AutoTrader_BN_v1.cpp`.
Pour que V2 compile, il faut soit :
- **Option A** : Les déplacer dans `MIA_Config.h` (recommandé)
- **Option B** : Passer `vwap_slope` en paramètre (déjà fait dans V2)

V2 utilise l'option B — `vwap_slope` est passé en paramètre, pas besoin de toucher `MarketLiveData`.

## 📁 Structure des fichiers générés

```
D:\MIA_IA_system\DATA_SIERRA_CHART\BOT_SNAPSHOTS\
├── 2026\
│   └── 02\
│       ├── 20260206\
│       │   ├── snapshot_ES_20260206.jsonl   ← ~75 MB/jour
│       │   └── snapshot_NQ_20260206.jsonl
│       └── 20260207\
│           ├── snapshot_ES_20260207.jsonl
│           └── snapshot_NQ_20260207.jsonl
```

## 📐 Structure JSON d'une ligne

```json
{
  "_v": "2.0.0",
  "t": 1738886400000,
  "seq": 1234,
  "sym": "ES",
  "session": "US",
  "hms": "10:30:15",
  "px": 6050.25,
  
  "bn_fp": { "eb":5, "es":2, "cu":12, "cd":3, ... },
  "bn_bar": { "ldu":1, "lud":0, ... },
  "bn_ord": { "a10":45, "b10":38, ..., "a400":2, "b400":1, "a1k":0, "b1k":0 },
  "bn_of": { "delta":150, "cvd":8500, "cvd_slope":125.5, ... },
  "bn_sc": { "score":0.65, "mom":0.42, "dir_coh":0.78, ... },
  "bn_rect": { "buy":3, "sell":1, "fresh_buy":true, ... },
  "bn_adv": { "atk_long":true, "stk_buy":3, ... },
  "bn_ddiv": { "buy":false, "sell":false, "str":0.0 },
  "bn_swing": { "hi":6055.0, "lo":6040.0, "near_sp":false, ... },
  "bn_sess": { "o":6045.0, "h":6058.0, "l":6038.0, "vpoc":6048.0, ... },
  "bn_vwap": { "v":6047.5, "sd1u":6053.0, "sd1d":6042.0, ... },
  "bn_ext": { "sup":6042.0, "res":6055.0, "d_sup":33.0, ... },
  "bn_range": { "is":false, "sup":0.0, ... },
  "bn_lvn": { "n":3, "above":6060.0, "below":6035.0, ... },
  
  "mq": { "hvl":6045.0, "gamma":6080.0, "call":6100.0, "put":6000.0, ... },
  "mq_vwap": { "v":6047.0, "slope":0.032, ... },
  "mq_gex": [6020.0, 6040.0, ...],
  "mq_blind": [6015.0, ...],
  "mq_dist": { "gex_up":12.0, "gex_dn":8.0, "blind":20.0, ... },
  "mq_prev": { "vah":6055.0, "val":6030.0, "vpoc":6042.0, ... },
  
  "cp": {
    "1d": { "vpoc":6048.0, "vah":6055.0, "val":6040.0, ... },
    "20d": { "vpoc":6020.0, ... },
    "50d": null,
    "100d": { "vpoc":5980.0, ... },
    "200d": null,
    "agg": { "lvn_up":6060.0, "lvn_dn":6035.0, "lvn_conf":2, ... }
  },
  
  "global": { "vix":18.5, "vix_r":1, "atr":14.5, "corr":0.92, "vwap_slope":0.032 },
  "regime": { "score":68.0, "type":1, "size_m":1.0, "tp_m":1.0, "trail":true },
  
  "state": { "in_pos":false, "trades":2, "wins":1, "pnl":125.0, ... },
  
  "layers": {
    "l1": { "pass":true, "conf":0.72, "dir":1, "level":"HVL", "dist":8.0, "imp":3 },
    "l2": { "pass":true, "conf":0.58, "bn":0.65, "vis":4 },
    "l3": { "pass":true, "conf":0.45, "veto":false, "ctx":"TREND_BULLISH" },
    "l4": { "pass":true, "combo":3, "qscore":72.0, "grade":"B", "tp_m":1.1 }
  },
  
  "sltp": { "sl":6045.25, "tp":6056.25, "sl_t":20, "tp_t":24, "rr":1.2 }
}
```

## ⚠️ Notes Importantes

1. **V1 reste actif** — V2 écrit dans un répertoire **différent** (`BOT_SNAPSHOTS` vs `BOT_DATA`). Les deux peuvent coexister sans conflit.

2. **Performance** — V2 utilise un buffer unique `char[16384]` + un seul `fwrite` au lieu de 20+ `fprintf`. Le file handle reste ouvert (rotation journalière). Impact CPU négligeable.

3. **Taille disque** — À 1 snapshot/sec pendant ~8h de trading :
   - ~28,800 lignes/jour × ~4.5 KB = **~130 MB/jour/symbole**
   - Avec gzip : **~13 MB/jour/symbole**
   - 1 mois : ~4 GB brut → ~400 MB compressé

4. **Pas de `MarketLiveData` requis** — `vwap_slope` est passé en paramètre pour éviter toute dépendance sur la struct qui est dans le .cpp principal.
