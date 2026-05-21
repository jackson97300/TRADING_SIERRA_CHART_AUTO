# Bot 1 — Améliorations du funnel de décision (document de préparation)

**Date** : 2026-05-21
**Statut** : PRÉPARATION — à implémenter APRÈS le chantier Bot 2 (focus actuel = Bot 2 SetupEngine).
**Source** : audit croisé du 20-21/05 — agent `market-analyst` (audit indépendant, 176 trades joints)
+ analyse Claude des 6 derniers perdants. Données : `DATA/_bot1_full.json` (audit joint 180 trades).
**Ne pas implémenter sans** : review `code-reviewer` + backtest préservation des gains + entrée `BOT_CHANGELOG.md` (protocole `.claude/rules/critical-tasks-review.md`).

---

## 1. Contexte

Bot 1 = `CORE/mia_paper_trader.py`, paper trading advisory ES/NQ (compte Sim3, moteur
`build_conseil_global`). Baseline historique paper : **79 W / 97 L, WR 44.9 %, +59 ticks net**.
100 trades perdants, tous sortis en SL. Objectif : éliminer les pertes **évitables** sans
sacrifier les gagnants (règle souveraine de préservation des wins).

## 2. Funnel actuel — 13 gates (`check_entry()`, ~l.1407-1980)

STEP 0 Regime (skip si non-actionable / favor NEUTRE / signal contraire favor) → 1 position + max
trades/jour → 2 cooldown + circuit breaker + calendrier éco → 3 Conseil Global (`executable_action`
≠ ATTENDRE/CONFLIT) → 4 freshness NEW → 5 dedup signal_id → 6 confidence ≥ 0.40-0.55 + MTF →
6bis bar DMP présente → 6ter RangeGate (observe) → 6quart RegimeGate → 6cinq EntryQualityGate →
6six ChaseTopGate → 7 SLTPEngine → 8 expected payoff.

## 3. Diagnostic — pourquoi les perdants passent

- **Le MTF n'est pas un filtre de trade** : aligné dans 4 des 6 derniers perdants. Filtre macro,
  pas micro. Ne pas compter dessus pour Bot 1.
- **Bug `ChaseTopGate` (STEP 6six)** : lit `range_pos` depuis le dashboard alors que la vraie
  valeur est dans le `dmp_bar`. Gate inopérant — couvre 56 perdants ET 36 gagnants (indiscriminant).
  C'est pourquoi le NQ LONG −116t (range_pos réel 91) est passé.
- **STEP 0 Regime suspect** — cas live 20/05 22:32 + 22:52 : Bot 1 a shorté NQ 2× (−86t, −41t)
  alors que sur les données propres (live_enriched Databento) `regime_favor = LONG` sur 100 % des
  barres, prix au-dessus VWAP, position 0.81-0.82, marché en hausse. STEP 0 est censé skip un
  signal contraire au favor. À VÉRIFIER : lit-il le bon `regime_favor` (même type de bug source
  que ChaseTopGate) OU le régime DMP Sierra divergeait-il du régime Databento ?
- **4 des 6 derniers perdants (SHORT ES, SL 10-41t)** n'ont AUCUN discriminateur à l'entrée :
  bruit + SL trop serrés. Aucun gate ne les attrapera → voir §6 (SLTPEngine).

## 4. Règles GO — validées empiriquement (bloquent perdants, préservent gains)

Chiffres **in-sample** sur 176 trades — gain réel attendu plus modeste (cf §7).

| Règle | Définition | Où l'insérer | Bloque (L/W) | Net |
|---|---|---|---|---|
| **B** | Interdire LONG si aucun mur TP à moins de 90 ticks (TP irréaliste) | STEP 7 SLTPEngine | 31 L / 12 W | +708 t |
| **F2** | Interdire SHORT si `delta_bar ≥ 0` (vente à flux acheteur) | nouveau gate post-STEP 6 | 12 L / 5 W | +276 t |
| **R8** | Interdire LONG si `momentum5 ≤ −3` (achat sans momentum) | nouveau gate post-STEP 6 | 11 L / 4 W | +140 t |
| A (option) | Interdire LONG si `ib_pos ≥ 0.55` | STEP 6six | 4 L / 1 W | +123 t (n faible) |

Ratio bloqué B∪F2∪R8∪A : 51 L / 20 W (2.5:1). Toutes respectent la préservation des gains.

## 5. Règles NOGO — ne PAS re-tenter

| Règle rejetée | Pourquoi |
|---|---|
| Interdire SHORT en bas de range (`range_pos ≤ 15`) | Tue 26 gagnants pour 23 perdants (−433 t). Les SHORT bas de range sont globalement profitables (+230 t). Intuition fausse sur Bot 1. |
| Filtre confidence basse (`conf ≤ 0.45`) | Tue 23 gagnants pour 11 perdants (−862 t). |
| `ChaseTopGate` en l'état (`range_pos ≥ 60`) | Indiscriminant (56 L / 36 W). À corriger (bug source), pas à durcir. |

## 6. Sujet résiduel — SLTPEngine (STEP 7)

4 des 6 derniers perdants = SHORT ES avec SL 10-41 ticks, mae faible. Le bruit normal touche le
SL. Aucun gate n'aide. Piste à instruire séparément : **élargir / recalibrer le SL** dans le
SLTPEngine. À traiter comme un sujet distinct des gates (ne pas mélanger).

## 7. Caveats

- Les chiffres sont **in-sample** : règles dérivées ET testées sur les mêmes 176 trades.
  Le gain combiné annoncé (+59 t → +1119 t) est **optimiste** — overfit probable.
- La préservation des gains est respectée par construction (ratio ≥ 2:1) → même dégradé, net positif.
- Règle B « favorable 10/11 jours » = seule règle avec un début de validation temporelle.

## 8. Protocole d'implémentation (quand on reprendra)

1. Corriger d'abord le **bug `ChaseTopGate`** (source `range_pos` → `dmp_bar`) — c'est un fix, pas une feature.
2. Implémenter B, F2, R8 **une règle à la fois** (anti pattern 11 : pas de cascade en bloc).
3. Pour chaque règle : backtest préservation (les wins historiques restent wins) AVANT commit.
4. Review `code-reviewer` obligatoire (modif du moteur de décision = tâche critique).
5. Entrée `DOCS/BOT_CHANGELOG.md` + nouveaux codes log (`CORE/log_catalog.py`).
6. Shadow / observe-only avant activation si possible.

## 9. Fichiers concernés

- `CORE/mia_paper_trader.py` — funnel `check_entry()` ~l.1407-1980
- `DASHBOARD/api/builders.py` — `build_conseil_global`, `build_advisory`
- `DATA/_bot1_full.json` — audit joint 180 trades (référence chiffrée)
- `CORE/mia_sltp.py` — SLTPEngine (sujet §6)
