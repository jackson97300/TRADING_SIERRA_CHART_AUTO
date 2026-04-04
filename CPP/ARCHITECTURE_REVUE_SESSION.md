# 📊 ARCHITECTURE REVUE DE SESSION - BOT C++

## 🎯 OBJECTIF

Générer automatiquement un fichier JSON structuré à la fin de chaque session de trading pour alimenter la revue de session, compatible avec la structure existante `REVUE_DE_SESSION/`.

---

## 📁 STRUCTURE DES FICHIERS GÉNÉRÉS

```
TRADING_SIERRA_CHART_AUTO/
└── LOGS/
    └── REVUE_SESSION/
        └── 2026/
            └── JANVIER/
                └── 20/
                    └── REVUE_SESSION_CPP_20260120.json  ← Fichier généré par le bot C++
```

---

## 📋 DONNÉES À COLLECTER

### 1. Statistiques Globales
- Trades pris (total + par symbole)
- Trades refusés (total + par symbole)
- Ratio rejet (%)
- P&L du jour (total + par symbole)
- Win Rate (global + par symbole)
- Session principale (Asia/London/US)

### 2. Détail des Trades
Pour chaque trade:
- Heure (HH:MM:SS)
- Symbole (ES/NQ)
- Direction (LONG/SHORT)
- Entry price
- Exit price
- P&L
- Exit reason (TP/SL/Trailing/BE)
- Durée (secondes)
- Contexte (VIX, d_vwap, session, etc.)
- Layers (L1/L2/L3/L4 confidence)
- BN score
- Type (MQ/RECT)

### 3. Signaux Refusés
Pour chaque rejet:
- Heure
- Symbole
- Direction
- Prix
- Layer (L1/L2/L3/L4)
- Raison
- Niveau MenthorQ (si applicable)
- Distance (ticks)
- VIX
- BN score
- VWAP slope

### 4. Analyse par Symbole
- P&L
- Win Rate
- Nombre de trades
- Stratégie (LONG/SHORT/BOTH)
- Performance (EXCELLENTE/BONNE/MOYENNE/À ÉVITER)

### 5. Meilleur/Pire Trade
- Meilleur: symbol, direction, P&L, heure, contexte, raison succès
- Pire: symbol, direction, P&L, heure, contexte, raison échec

### 6. Max Drawdown Intraday
- Peak P&L
- Valley P&L
- Max DD en $
- Heure du DD max

### 7. Configuration Active
- Paramètres SL/TP (par symbole)
- Seuils Layer 2/3/4
- Cooldown settings
- Mode (TEST/PRODUCTION)

### 8. Contexte Marché
- VIX (min/max/moyen)
- Régime (CALM/NORMAL/VOLATILE)
- Volatilité (ATR ES/NQ)

---

## 🔧 IMPLÉMENTATION

### Structure de données à ajouter

```cpp
// Stats de session pour revue
struct SessionStats {
    // Global
    int total_trades;
    int total_rejected;
    float total_pnl;
    float win_rate;
    char main_session[16];

    // Par symbole
    int trades_es;
    int trades_nq;
    int rejected_es;
    int rejected_nq;
    float pnl_es;
    float pnl_nq;
    float wr_es;
    float wr_nq;

    // Meilleur/Pire
    float best_trade_pnl;
    float worst_trade_pnl;
    char best_trade_info[256];
    char worst_trade_info[256];

    // Drawdown
    float peak_pnl;
    float valley_pnl;
    float max_dd;
    int dd_hour;
    int dd_minute;

    // Rejets par layer
    int rej_l1;
    int rej_l2;
    int rej_l3;
    int rej_l4;

    // Rejets par raison (top 3)
    char top_reject_reason_1[128];
    int top_reject_count_1;
    char top_reject_reason_2[128];
    int top_reject_count_2;
    char top_reject_reason_3[128];
    int top_reject_count_3;
};

// Stocker les trades de la session
struct TradeRecord {
    int hour, minute, second;
    char symbol[8];
    char direction[8];
    float entry;
    float exit;
    float pnl;
    char exit_reason[32];
    int duration_sec;
    float vix;
    float bn_score;
    float vwap_slope;
    float l1_conf;
    float l2_conf;
    float l3_conf;
    int l4_combo;
    bool is_rectangle;
};

// Stocker les rejets de la session
struct RejectRecord {
    int hour, minute, second;
    char symbol[8];
    char direction[8];
    float price;
    char layer[16];
    char reason[256];
    float level;
    float distance;
    float vix;
    float bn_score;
    float vwap_slope;
};
```

### Fonctions à créer

1. **`InitializeSessionStats()`** - Reset stats au début de session
2. **`UpdateSessionStats()`** - Mettre à jour après chaque trade/rejet
3. **`GenerateSessionReviewJSON()`** - Générer le JSON final
4. **`ExportSessionReview()`** - Sauvegarder dans le bon dossier

### Intégration dans le flux

- **Au début de session**: Appeler `InitializeSessionStats()`
- **Après chaque trade**: Appeler `UpdateSessionStats()` avec les données du trade
- **Après chaque rejet**: Appeler `UpdateSessionStats()` avec les données du rejet
- **À la fin de session**: Appeler `GenerateSessionReviewJSON()` et `ExportSessionReview()`

---

## 📄 FORMAT JSON GÉNÉRÉ

```json
{
  "date": "20260120",
  "session_start": "00:00:00",
  "session_end": "23:00:00",
  "bot_mode": "TEST",

  "statistics": {
    "total_trades": 4,
    "total_rejected": 5,
    "rejection_ratio": 0.56,
    "total_pnl": 109.10,
    "win_rate": 0.50,
    "main_session": "US"
  },

  "trades": [
    {
      "time": "03:47:00",
      "symbol": "ES",
      "direction": "SHORT",
      "entry": 7008.38,
      "exit": 7016.50,
      "pnl": 150.00,
      "exit_reason": "TP",
      "duration_sec": 60,
      "context": {
        "vix": 15.4,
        "vwap_slope": -0.0004,
        "session": "US",
        "bn_score": 0.189
      },
      "layers": {
        "l1_confidence": 0.85,
        "l2_confidence": 0.12,
        "l3_confidence": 0.08,
        "l4_combo": 3
      },
      "type": "MQ"
    }
  ],

  "rejected": [
    {
      "time": "15:35:00",
      "symbol": "ES",
      "direction": "SHORT",
      "price": 7018.88,
      "layer": "L1",
      "reason": "Cooldown niveau",
      "level": 7020.00,
      "distance": 1.0,
      "vix": 15.4,
      "bn_score": 0.189,
      "vwap_slope": -0.0004
    }
  ],

  "analysis": {
    "by_symbol": {
      "ES": {
        "trades": 2,
        "pnl": 306.50,
        "win_rate": 1.0,
        "strategy": "SHORT",
        "performance": "EXCELLENTE"
      },
      "NQ": {
        "trades": 2,
        "pnl": -197.40,
        "win_rate": 0.0,
        "strategy": "SHORT",
        "performance": "À ÉVITER"
      }
    },
    "best_trade": {
      "symbol": "ES",
      "direction": "SHORT",
      "pnl": 156.50,
      "time": "15:29:00",
      "context": "US Power Hour",
      "reason": "TP Hit en 49s"
    },
    "worst_trade": {
      "symbol": "NQ",
      "direction": "SHORT",
      "pnl": -152.40,
      "time": "09:34:00",
      "context": "US Open",
      "reason": "Contre-tendance"
    },
    "max_drawdown": {
      "peak": 500.00,
      "valley": -200.00,
      "max_dd": -700.00,
      "time": "16:30:00"
    },
    "top_reject_reasons": [
      {"reason": "Cooldown niveau", "count": 5, "percentage": 100.0}
    ]
  },

  "configuration": {
    "es": {
      "sl_default_ticks": 16,
      "tp_default_ticks": 20,
      "trailing_activation": 16,
      "trailing_distance": 12
    },
    "nq": {
      "sl_default_ticks": 28,
      "tp_default_ticks": 35,
      "trailing_activation": 28,
      "trailing_distance": 16
    },
    "cooldown_win_minutes": 20,
    "cooldown_loss_minutes": 15
  },

  "market_context": {
    "vix": {
      "min": 15.0,
      "max": 16.0,
      "average": 15.5
    },
    "regime": "NORMAL",
    "volatility": {
      "atr_es": 62.0,
      "atr_nq": 355.0
    }
  }
}
```

---

## 🔄 INTÉGRATION AVEC REVUE EXISTANTE

Le fichier JSON généré par le bot C++ peut être:
1. **Lu directement** par un script Python pour générer le markdown
2. **Fusionné** avec les données du bot Python (si les deux tournent)
3. **Analysé** par Claude avec le prompt existant `PROMPT_FIN_SESSION_ULTRA_COMPLET.md`

---

## ✅ AVANTAGES

1. **Automatique** - Pas besoin d'intervention manuelle
2. **Structuré** - Format JSON facile à parser
3. **Complet** - Toutes les données nécessaires
4. **Compatible** - S'intègre avec l'existant
5. **Temps réel** - Peut être généré en continu ou à la fin

---

## 📝 PROCHAINES ÉTAPES

1. ✅ Créer les structures de données
2. ✅ Implémenter les fonctions de collecte
3. ✅ Intégrer dans le flux principal
4. ✅ Tester la génération JSON
5. ✅ Créer script Python pour convertir JSON → Markdown (optionnel)
