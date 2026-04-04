# 📱 INTÉGRATION DISCORD - BOT C++

## 🎯 OBJECTIF

Recevoir des notifications Discord en temps réel pour suivre le P&L et les trades du bot C++ depuis Discord (même au travail).

---

## 🚀 INSTALLATION

### 1. Installer les dépendances Python

```bash
pip install requests
```

### 2. Lancer le bridge Discord

**Option A - Fichier batch:**
```
Double-cliquer sur: LANCER_DISCORD_BRIDGE.bat
```

**Option B - Ligne de commande:**
```bash
cd D:\MIA_IA_system\TRADING_SIERRA_CHART_AUTO
python discord_cpp_bridge.py
```

**Option C - En arrière-plan (recommandé):**
```bash
start /B python discord_cpp_bridge.py
```

---

## 📊 NOTIFICATIONS ENVOYÉES

### 1. Trade Ouvert
- Symbole, Direction, Entry, SL, TP
- BN Score, L4 Combo, Type (MQ/RECT)
- Distances TP/SL en ticks, R:R

### 2. Trade Fermé
- Entry → Exit
- P&L ($)
- Points/Ticks
- Durée
- Raison (TP/SL/Trailing)

### 3. Résumé Quotidien (à venir)
- Total trades, P&L, Win Rate
- Stats par symbole (ES/NQ)

---

## 🔧 CONFIGURATION

### Webhook Discord

Le webhook est configuré dans `discord_cpp_bridge.py`:
```python
CPP_WEBHOOK_URL = "https://discord.com/api/webhooks/1463310218493432024/..."
```

Pour changer le webhook, modifier cette ligne dans le fichier Python.

---

## 📁 FICHIERS GÉNÉRÉS

Le bot C++ écrit les événements dans:
```
TRADING_SIERRA_CHART_AUTO/LOGS/DISCORD_EVENTS/events_YYYYMMDD.jsonl
```

Le script Python surveille ce fichier et envoie vers Discord.

---

## ✅ VÉRIFICATION

1. **Vérifier que le bridge tourne:**
   - Console Python ouverte
   - Messages "✅ Discord: Trade ouvert..." dans la console

2. **Vérifier Discord:**
   - Messages apparaissent dans le salon Discord
   - Embeds colorés selon résultat

3. **En cas de problème:**
   - Vérifier que le fichier `events_YYYYMMDD.jsonl` est créé
   - Vérifier les erreurs dans la console Python
   - Vérifier que le webhook Discord est valide

---

## 🔄 MAINTENANCE

Le bridge tourne en continu et surveille les nouveaux événements toutes les 2 secondes.

**Pour redémarrer:**
1. Fermer la console Python (Ctrl+C)
2. Relancer `LANCER_DISCORD_BRIDGE.bat`

---

## 📝 NOTES

- Le bridge lit les événements **une seule fois** (évite les doublons)
- Les événements sont traités dans l'ordre chronologique
- En cas d'erreur Discord, le bridge continue (pas de crash)

---

## 🎯 PROCHAINES AMÉLIORATIONS

- [ ] Résumé quotidien automatique (23:00)
- [ ] Notifications de rejets importants
- [ ] Alertes P&L (seuils personnalisables)
- [ ] Graphiques P&L cumulé dans Discord
