# 🔧 CHANGELOG — 01/03/2026

## Fichiers modifiés

| Fichier | Lignes modifiées | Risque régression |
|---------|-----------------|-------------------|
| `MIA_Execution.h` | 1 ligne | ❌ Aucun (correction logique pure) |
| `MIA_Main.cpp` | +54 lignes | ⚠️ Faible (garde additif, pas de modif existante) |
| `MIA_Config.h` | +4 lignes | ❌ Aucun (ajout constante, valeur inchangée) |
| `README.md` | 4 lignes corrigées | ❌ Aucun (documentation) |
| `GUIDE_COMPILATION.md` | 1 ligne corrigée | ❌ Aucun (documentation) |

---

## 🔴 FIX #1 — Inversion symbole dans SendBracketOrder [CRITIQUE]

**Fichier**: `MIA_Execution.h:315`

**Problème**: `strcmp(sc.GetChartSymbol(sc.ChartNumber), "ES") != 0` utilisait une comparaison **exacte**. Or le symbole réel est `"ESH26-CME"`, donc `strcmp` retournait toujours `!= 0` (true) → chargeait **toujours CONFIG_ES**, même pour NQ.

**Conséquences avant fix**:
- NQ trades : SL capé à 20-28 ticks au lieu de 20-40, trailing activé +15t au lieu +35t
- ES trades : correct par chance (condition toujours true → CONFIG_ES)

**Correction**: Remplacé `strcmp` par `strstr` (sous-chaîne), aligné avec le pattern `MIA_Main.cpp:570`.

```diff
- const SymbolConfig& cfg = (strcmp(..., "ES") != 0) ? CONFIG_ES : CONFIG_NQ;
+ const SymbolConfig& cfg = (strstr(..., "ES") != NULL) ? CONFIG_ES : CONFIG_NQ;
```

**Risque régression**: Aucun. Le pattern `strstr` est déjà utilisé partout dans `MIA_Main.cpp`. Pas de changement pour ES (sélectionnait déjà CONFIG_ES). NQ recevra enfin CONFIG_NQ.

---

## 🟡 FIX #2 — Revalidation R:R après ajustement HQ [ES + NQ]

**Fichier**: `MIA_Main.cpp` (2 blocs symétriques ES/NQ)

**Problème**: Quand `DetectHighQualityTrade()` élargit le SL via `hq.sl_multiplier`, le ratio R:R (TP/SL) n'était jamais recalculé. Un trade avec R:R initial 1.20 pouvait tomber à 0.80 après HQ.

**Correction**: Architecture en 3 parties (identique ES et NQ):

1. **Flag** `bool es_hq_rr_veto = false;` déclaré avant le bloc HQ
2. **Revalidation** après `sltp.sl_ticks` recalcul : si `rr_ratio < min_rr_ratio` → flag = true, log, compteur
3. **Guard** avant `SendBracketOrder` : si flag true → dashboard "VETO_HQ_RR", pas d'ordre envoyé

**Seuils**:
- ES: `min_rr_ratio = 1.20` (MIA_Config.h:86)
- NQ: `min_rr_ratio = 1.25` (MIA_Config.h:125)

**Risque régression**: Faible. Le code est purement **additif** (nouvelles conditions, pas de modification du flux existant). En cas normal (pas de HQ ou R:R valide), le flag reste false et le `else` exécute le code original inchangé.

**Monitoring**: Logs `"HQ R:R VETO ES/NQ"` + compteur `g_dashboard.sltp_reject_es/nq++` + dashboard `"VETO_HQ_RR"`.

---

## 🟡 FIX #3 — Capital hardcodé → Constante

**Fichiers**: `MIA_Config.h` (déclaration) + `MIA_Main.cpp` (2 remplacements)

**Problème**: `10000.0f` hardcodé pour le calcul drawdown % en ES (ligne 1406) et NQ (ligne 2040).

**Correction**:
- Nouvelle constante `ACCOUNT_CAPITAL_BASE = 10000.0f` dans `MIA_Config.h`
- Remplacé les 2 occurrences dans `MIA_Main.cpp`

**Risque régression**: Aucun. Même valeur, même calcul. Juste un point de modification unique si le capital change.

---

## 🟡 FIX #4 — Study IDs documentation

**Fichiers**: `README.md` + `GUIDE_COMPILATION.md`

**Corrections** (alignées sur `study_mapping.json` v3.0):

| Étude | README avant | JSON correct | Corrigé |
|-------|-------------|-------------|---------|
| ES ROTATION_UP | 20 | 19 | ✅ |
| ES ROTATION_DOWN | 21 | 20 | ✅ |
| ES FPBS | 10 | 31 | ✅ |
| ES CLUSTER_VOL | 50 | 10 | ✅ |

**GUIDE_COMPILATION.md**: ES FPBS corrigé 10 → 31.

**Ajout**: Note source de vérité dans README pointant vers `study_mapping.json`.

---

## ✅ Vérification d'intégrité

| Check | Résultat |
|-------|---------|
| Accolades MIA_Main.cpp | 214 `{` / 214 `}` ✅ (original: 206/206, +8 paires) |
| Accolades MIA_Execution.h | 148 `{` / 148 `}` ✅ (inchangé) |
| `min_rr_ratio` existe dans SymbolConfig | ✅ ligne 47 |
| `rr_ratio` existe dans SLTP struct | ✅ lignes 997, 1035 |
| `sltp_reject_es/nq` dans Dashboard | ✅ lignes 937, 946 |
| `ACCOUNT_CAPITAL_BASE` accessible via includes | ✅ MIA_Config.h → inclus partout |
| `strstr` disponible dans MIA_Execution.h | ✅ via sierrachart.h |

## 📋 Procédure de déploiement

1. **Backup** des 5 fichiers originaux
2. **Copier** les fichiers corrigés dans `D:\TRADING_SIERRA_CHART_AUTO\CPP\MIA_REFACTORED\`
3. **Recompiler** `MIA_Main.cpp` dans Sierra Chart
4. **Tester en MODE_TEST** — vérifier:
   - Dashboard affiche `CONFIG_NQ` quand NQ trade (pas CONFIG_ES)
   - Log `"HQ R:R VETO"` apparaît si HQ élargit SL au-delà du ratio
   - Drawdown % identique (même valeur 10000)
5. **Valider** 1-2 sessions sim avant production
