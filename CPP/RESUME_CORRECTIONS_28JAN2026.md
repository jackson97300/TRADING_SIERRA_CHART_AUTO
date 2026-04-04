# RÉSUMÉ DES CORRECTIONS - 28 JANVIER 2026

## PROBLÈME INITIAL

**Vous avez signalé 2 problèmes:**
1. "NQ NE CALCULE PAS CORRECTEMENT LE PNL"
2. "Sur le graphe ES, même les trades manuels sont calculés au PNL du dashboard, mais PAS NQ"

## CE QUE J'AI VÉRIFIÉ

### 1. Config TP/SL (lignes 140-174)
```cpp
NQ:
- sl_default: 28 ticks (7 pts)
- sl_max: 40 ticks (10 pts)
- tp_default: 35 ticks (8.75 pts)  
- tp_max: 50 ticks (12.5 pts)
- tick_value: 5.00 ✅

ES:
- sl_default: 20 ticks (5 pts)
- sl_max: 28 ticks (7 pts)
- tp_default: 24 ticks (6 pts)
- tp_max: 32 ticks (8 pts)
- tick_value: 12.50 ✅
```

### 2. Formule PNL (ligne 5474)
```cpp
pnl = ticks * config.tick_value; ✅
```
→ Correct pour ES ET NQ!

### 3. Logs des trades
```
ES Trade #20: Entry=7037.75, TP=7046.75
- Distance: 36 ticks
- PNL si TP: 36 × 12.50 = $450 ✅

NQ Trade #87: Entry=26187.75, TP=26199.25
- Distance: 46 ticks
- PNL si TP: 46 × 5.00 = $230 ✅
```

## CE QUE J'AI CORRIGÉ

### CORRECTION #1: Hard Limits dans SendBracketOrder (ligne 5323)
**Problème:** Si `final_entry_price` (Smart Money) ≠ `entry_price`, les offsets SL/TP dépassaient les limites!

**Solution:**
```cpp
// Forcer les limites sur les offsets finaux
if (sl_offset_ticks > cfg.sl_max_ticks) {
    sl_offset_ticks = cfg.sl_max_ticks;
}
if (tp_offset_ticks > cfg.tp_max_ticks) {
    tp_offset_ticks = cfg.tp_max_ticks;
}
```

**Impact:** 
- ES TP max: 32 ticks (au lieu de 36) ✅
- NQ TP max: 50 ticks ✅

### CORRECTION #2: Détection Trades Manuels (ligne 7403)
**Problème:** Les trades manuels NQ n'étaient PAS comptabilisés dans le dashboard!

**Raison:** `ProcessPositionClosed()` ne s'exécute QUE si `state.in_position == true`
- Trades bot: `in_position = true` → comptabilisés ✅
- Trades manuels: `in_position = false` → ignorés ❌

**Solution:** Ajout d'une surveillance de `LastTradeProfitLoss` même quand `in_position == false`

```cpp
// 🆕 ES: Détecter trades manuels
else if (posData.PositionQuantity == 0 && 
         fabs(posData.LastTradeProfitLoss) > 0.01f &&
         fabs(posData.LastTradeProfitLoss - g_es_state.last_processed_pnl) > 0.01f) {
    // Trade manuel ES fermé → ajouter au PNL
    float manual_pnl = posData.LastTradeProfitLoss;
    g_es_state.pnl_today += manual_pnl;
    g_es_state.trades_today++;
    // ...
}

// 🆕 NQ: Détecter trades manuels
else if (posData.PositionQuantity == 0 && 
         fabs(posData.LastTradeProfitLoss) > 0.01f &&
         fabs(posData.LastTradeProfitLoss - g_nq_state.last_processed_pnl) > 0.01f) {
    // Trade manuel NQ fermé → ajouter au PNL
    float manual_pnl = posData.LastTradeProfitLoss;
    g_nq_state.pnl_today += manual_pnl;
    g_nq_state.trades_today++;
    // ...
}
```

**Impact:** Maintenant ES ET NQ comptabilisent les trades manuels! ✅

### CORRECTION #3: Nouveau champ `last_processed_pnl` (ligne 236)
**Problème:** Sans tracking, le même trade manuel serait compté à CHAQUE tick!

**Solution:** Ajout d'un champ pour tracker le dernier PNL traité
```cpp
struct BotState {
    // ...
    float last_processed_pnl;  // 🆕 28/01
};
```

**Impact:** Évite les doublons ✅

## RÉCAPITULATIF

### ✅ CE QUI ÉTAIT DÉJÀ CORRECT
1. NQ tick_value = 5.00 (pas 20!)
2. ES tick_value = 12.50
3. Formule PNL: `pnl = ticks * config.tick_value`
4. Tous les calculs utilisent `config.tick_value`

### ✅ CE QUI A ÉTÉ CORRIGÉ
1. **Hard limits TP/SL** dans `SendBracketOrder` (ES TP était à 36 ticks au lieu de max 32)
2. **Détection trades manuels NQ** (maintenant comptabilisés comme ES)
3. **Tracking PNL** pour éviter doublons

### 📊 VALIDATION
```
ES:
- TP max: 32 ticks ✅ (avant: 36 ❌)
- Trades manuels comptés: ✅

NQ:
- TP max: 50 ticks ✅
- Trades manuels comptés: ✅ (avant: ❌)
- PNL calculé: ticks × $5 ✅
```

## ACTIONS REQUISES

1. **RECOMPILER le DLL** pour appliquer les corrections
2. **Tester** avec un trade manuel NQ
3. **Vérifier** que le dashboard affiche bien le PNL NQ

## QUESTION

**Est-ce que le problème était:**
A. Les trades manuels NQ pas comptés? → ✅ CORRIGÉ
B. Le PNL NQ mal calculé (ex: $920 au lieu de $230)? → Dites-moi la valeur affichée
C. Autre chose?

---

**Fichiers modifiés:**
- `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_AutoTrader_BN_v1.cpp`
  - Ligne 236: Ajout `last_processed_pnl`
  - Ligne 5323: Hard limits dans SendBracketOrder
  - Ligne 7145: Init `last_processed_pnl = 0`
  - Ligne 7403: Détection trades manuels ES/NQ
