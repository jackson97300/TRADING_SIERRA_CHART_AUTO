# 🤖 MIA AUTO-TRADER SIERRA CHART

## 📁 Structure des Dossiers

```
TRADING_SIERRA_CHART_AUTO/
├── CPP/                          # Code source C++ (ACSIL)
│   ├── MIA_AutoTrader_BN_v1.cpp  # Auto-trader principal
│   └── TEST_Scan_All.cpp         # Utilitaire scan études
│
├── LOGS/                         # Logs de trading
│   ├── TRADES_WIN/               # Trades gagnants
│   │   ├── ES_20260118.log       # Format: ES_YYYYMMDD.log
│   │   └── NQ_20260118.log
│   └── TRADES_LOSS/              # Trades perdants
│       ├── ES_20260118.log
│       └── NQ_20260118.log
│
├── SNAPSHOTS/                    # Snapshots détaillés par trade
│   └── MIA_TRADE_ES_20260118_000001.json
│
├── DASHBOARD/                    # Dashboard en temps réel
│   └── MIA_AutoTrader_Dashboard.json
│
├── CONFIG/                       # Fichiers de configuration
│   └── (réservé pour configs futures)
│
└── DOCS/                         # Documentation
    └── README.md
```

---

## 📊 Format des Logs

### TRADES_WIN / TRADES_LOSS
Un fichier par symbole par jour, format texte:
```
HH:MM:SS|SYMBOL|DIR|ENTRY|EXIT|PNL|REASON|BN_SCORE|L1|L2|L3|L4
14:35:22|ES|LONG|6025.50|6028.25|+34.38|TP|0.15|0.25|0.18|0.12|2
```

### SNAPSHOTS
JSON ultra-complet avec toutes les données au moment du trade:
- Layers (L1-L4) avec confidence
- Bataille Navale (ES + NQ)
- Market context (VIX, ATR, Delta, etc.)

### DASHBOARD
JSON mis à jour en temps réel:
- État du bot
- Performance ES/NQ
- Alertes et warnings
- Session actuelle

---

## 🔧 Compilation

1. Copier `MIA_AutoTrader_BN_v1.cpp` dans le dossier ACS_Source de Sierra Chart
2. Dans Sierra Chart: **File** → **Build Custom Studies DLL**
3. Appliquer l'étude sur le Chart principal (ES Barres recommandé)

---

## ⚙️ Configuration des Inputs

| Input | Description | Défaut |
|-------|-------------|--------|
| Enable Bot | Active/désactive le bot | Yes |
| Enable ES | Active trading ES | Yes |
| Enable NQ | Active trading NQ | Yes |
| Pause ES | Pause manuelle ES | No |
| Pause NQ | Pause manuelle NQ | No |
| ES Footprint Chart | Numéro du chart ES Footprint | 1 |
| ES Barres Chart | Numéro du chart ES Barres | 3 |
| NQ Footprint Chart | Numéro du chart NQ Footprint | 2 |
| NQ Barres Chart | Numéro du chart NQ Barres | 4 |
| VIX Chart | Numéro du chart VIX | 15 |
| ES Daily Chart | Numéro du chart ES Daily (ATR) | 16 |
| NQ Daily Chart | Numéro du chart NQ Daily (ATR) | 17 |

---

## 🆕 Charts Additionnels (VIX + ATR Daily)

| Chart | Symbole | Période | Études | Study IDs |
|-------|---------|---------|--------|-----------|
| 15 | VIX | Daily | (pas d'étude) | Prix Close = VIX |
| 16 | ES | Daily | ATR | study_id=1, subgraph=0 |
| 17 | NQ | Daily | ATR | study_id=1, subgraph=0 |

---

## 🎯 Fonctionnalités Avancées

### VIX Adaptatif
```
VIX < 15  → CALM (seuils stricts)
VIX 15-25 → NORMAL (seuils standards)
VIX > 25  → VOLATILE (seuils permissifs)
```

### Golden Rules Bataille Navale
1. **Règle d'Or #1 (Ratio 1.5x)**: VETO si l'adversaire a 1.5x+ de force
2. **Règle d'Or #2 (Absence)**: Bonus si pas de signal adverse (voie libre)

### Confluence Detector
Détecte les zones où plusieurs niveaux MenthorQ convergent (GEX, HVL, VWAP, etc.)

### VWAP Slope
Calcule la pente du VWAP sur 20 bars pour détecter la tendance intraday

---

## 📈 Study IDs Utilisés

### Chart 1 - ES Footprint
| Étude | ID |
|-------|-----|
| EDGE BUY | 52 |
| EDGE SELL | 53 |
| COLOR UP | 56 |
| COLOR DOWN | 57 |
| ABSORB ASK | 25 |
| ABSORB BID | 26 |
| DOUBLE ASK | 28 |
| DOUBLE BID | 27 |
| ROTATION UP | 19 |
| ROTATION DOWN | 20 |

### Chart 2 - NQ Footprint
| Étude | ID |
|-------|-----|
| EDGE BUY | 55 |
| EDGE SELL | 56 |
| COLOR UP | 53 |
| COLOR DOWN | 54 |
| ABSORB ASK | 29 |
| ABSORB BID | 30 |
| TRIPLE ASK | 28 |
| TRIPLE BID | 27 |
| ROTATION UP | 21 |
| ROTATION DOWN | 22 |
| VOLUME UP | 35 |
| VOLUME DOWN | 36 |

### Chart 3 - ES Barres
| Étude | ID |
|-------|-----|
| LONG DOWN UP | 38 |
| LONG UP DOWN | 39 |
| MenthorQ Gamma | 2 |
| MenthorQ Blind | 22 |
| VWAP | 1 |

### Chart 4 - NQ Barres
| Étude | ID |
|-------|-----|
| LONG DOWN UP | 23 |
| LONG UP DOWN | 24 |
| MenthorQ Gamma | 25 |
| MenthorQ Blind | 2 |
| VWAP | 1 |

---

## 📅 Sessions de Trading

| Session | Heure FR | Heure ET |
|---------|----------|----------|
| Début | 02:30 | 20:30 |
| Pause pré-US | 15:00 | 09:00 |
| Open US | 15:30 | 09:30 |
| Fin OPR | 15:45 | 09:45 |
| Fin | 21:00 | 15:00 |

---

## ⚡ Cooldowns

| Événement | ES | NQ |
|-----------|----|----|
| Après win | 10 min | 10 min |
| Après loss | 15 min | 15 min |
| 3 losses consécutifs | 45 min | - |
| 4 losses consécutifs | - | 45 min |
| Annonce détectée | 30 min | 30 min |

---

## 📝 Dernière mise à jour
- **Date**: 2026-01-18
- **Version**: 1.1
- **Auteur**: MIA Trading System
- **Changelog v1.1**:
  - Ajout VIX LIVE (Chart 15)
  - Ajout ATR Daily ES/NQ (Charts 16, 17)
  - Ajout Golden Rules #1 et #2
  - Ajout VWAP Slope
  - Ajout Confluence Detector
  - Dashboard enrichi avec market_live
