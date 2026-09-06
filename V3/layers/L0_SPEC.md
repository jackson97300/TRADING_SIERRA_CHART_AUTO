# L0 — SPEC : les conditions sont-elles réunies pour trader ?

*Écrit le 06/09/2026, Claude Code + Fable. Chaque porte porte sa source, sa
classe et sa mesure. Ce document est la source de vérité de L0 ; le code en
découle, jamais l'inverse.*

---

## Ce que L0 répond, et ce qu'elle ne répond pas

**L0 ne cherche pas de trade et n'a pas d'avis sur le marché.** Elle dit si une
décision a le **droit d'exister** maintenant.

Elle ne lit pas le sens du trade : `gamma_block_long/short` et les murs dans le
sens du TP appartiennent à **L5**. Elle ne devine pas : **une condition non
collectée n'existe pas.**

---

## Les six règles de construction

1. **Une porte est une fonction pure.** Elle lit une barre et un état, elle rend
   un booléen. Aucun seuil dans le code — tout vient du YAML.
2. **Toutes les portes sont évaluées sur chaque signal, indépendamment.** Un
   booléen par porte. *Corrigé le 06/09* : l'évaluation en série attribuait
   chaque rejet à la première porte qui fermait, et `MAX_TRADES` « volait » les
   rejets des autres — `SESSION_BLOQUEE` mesurée à 8 rejets en série contre
   **39** en indépendant, `VETO_RVOL_EXTREME` à 1 contre **30**.
3. **Deux modes** — appliqué ou observé — déclarés dans `campagne.yaml`, changés
   par commit, jamais dans le code.
4. **Une plage de rejet attendue par porte.** Hors plage = la porte ne passe pas
   à la couche suivante.
5. **Aucun proxy.** Une donnée absente reste absente.
6. **Deux tests par porte** — une barre qui passe, une barre qui bloque — plus
   un test « rien de caché » qui échoue si une porte existe dans le code sans
   ligne YAML.

---

## Famille 1 — QUALITÉ DES DONNÉES : *ce que je lis est-il vrai ?*

| porte | source | classe | mesure |
|---|---|---|---|
| `data_quality_flag != stable` | JSONL | **appliquée** | filtre de lecture, pas de devenir à mesurer |
| `window_version != w1` | `recalc.window_version` | **appliquée** | bascule w0→w1 le 06/09 21:00 UTC |
| barre 15 min incomplète | agrégation | **appliquée** | une barre partielle en fin de session fausse l'ATR |
| fraîcheur > 90 s | `ts` vs horloge | **appliquée** | règle héritée : pas de trade sur une barre morte |
| colonne dans `stale.csv` | 1 080 couples (col, jour) | **appliquée** | 63 colonnes du noyau touchées, 18 jours |
| verdict L6 du jour = ALERTE | `surveillance/l6.py` | **appliquée** | une alerte bloque l'intégration du jour |
| âge des niveaux MenthorQ | `mq_levels_1.0` | **observée** | le dump Sierra est vivant, l'âge reste à mesurer |
| horloge du VPS dérivée | à construire | **absente** | rien ne la mesure aujourd'hui |

---

## Famille 2 — TEMPS ET CALENDRIER : *est-ce un moment où décider ?*

| porte | source | classe | mesure |
|---|---|---|---|
| hors session cash | `is_in_us_cash` | **appliquée** | 27,5 % des barres en cash |
| `is_session_blocked` | `eco_calendar.py` | **appliquée** | ferme **10,1 % ES / 14,0 % NQ**, devenir +0,07 / +0,04 |
| news CRITIQUE −15/+30 | FOMC, NFP, CPI, PCE, PPI | **appliquée** | **−4,82 ATR ES, −1,18 NQ.** Trente écarts-types du hasard. Née d'une perte de 1 156 $ |
| news ÉLEVÉE −5 min | PIB, ISM, Retail Sales | **appliquée** | non mesurée séparément |
| fenêtre news élargie | −15/+30 → plus large | **observée** | 4 occurrences seulement : trop peu pour élargir sans mesure |
| férié CME | `sessions.yaml` | **appliquée** | **déclarée, jamais déductible des données** : Juneteenth avait 841 barres et 12 % du volume |
| demi-séance (clôture 13:00 ET) | `sessions.yaml` | **appliquée** | le CME ferme plus tôt, le marché reste ouvert |
| dimanche / week-end | vendredi 15:30 → dimanche 18:15 ET | **appliquée** | déjà dans `eco_calendar` |
| rollover en cours | `roll_calendar.py` | **appliquée** | jeudi 10/09 : premier test |
| EOD lockout −10 min | horaire | **appliquée** | 20h UTC : 100 % bloqué |
| première barre de 9h30 | rang dans la journée | **appliquée** | aucune décision avant que le régime soit lu à 10h30 |

---

## Famille 3 — CONDITIONS DE MARCHÉ : *le marché est-il tradable ?*

| porte | source | classe | mesure |
|---|---|---|---|
| `vix_regime >= 2` | C++, bornes 0<15 / 1≤25 / 2>25 / 3>35 | **appliquée** | **DORMANTE** : le VIX a plafonné à 22,01 sur 57 jours, les codes 2 et 3 n'ont jamais existé |
| choc VIX intrajour | `vix_level` / valeur à 9h30 > 1,10 | **observée** | à mesurer : un VIX de 16 à 18 en une heure change le régime, même sous 25 |
| **spread > 1 tick** | — | **ABSENTE** | **non collecté.** Aucune colonne de carnet dans le C++ ; `avg_bid_size` / `avg_ask_size` sont des tailles VAP, pas des cotations. **Pas de proxy** → `NEXT_CYCLE` |
| volume mort | `total_vol` vs médiane horaire | **observée** | distribution à mesurer |
| volatilité extrême | `atr_hnorm_r` à recalculer | **observée** | `atr_14m_hnorm` n'existe pas dans les JSONL — créée par `feature_reduction`, jamais collectée |
| régime indéterminé | zone morte HVL 1,0 ATR | **observée** | 7 à 10 % des barres |

**Pourquoi VIX et spread vont ensemble** : ce sont les deux portes de *liquidité*,
celles qui protègent d'un fill sans rapport avec le prix affiché. **En SIM, un
fill se fait au touché** — ni le spread ni le VIX n'apparaissent dans le P&L
simulé, alors qu'ils seraient la première chose à faire mal en réel. Les deux en
observation : à la lecture, on saura combien de trades SIM auraient été exécutés
dans des conditions où le réel ne les aurait pas remplis au même prix.

---

## Famille 4 — ÉTAT DU RISQUE : *ai-je encore le droit de perdre ?*

| porte | seuil | classe | mesure |
|---|---|---|---|
| stop journalier SIM | −1 000 $ | **appliquée** | **inerte par construction** : 31,8 pertes d'affilée sur ES contre ~7 signaux/jour. Assumé |
| stop prop firm réel | −200 $ | **observée** | « aurait bloqué ici » — à la lecture, combien de jours coupés |
| `max_trades/jour` | 5 / 10 / 20 | **observée** | **ferme 41,6 % ES / 47,9 % NQ**, devenir des rejetés **+0,196 / +0,253** — meilleur que les retenus |
| rang du trade dans la journée | — | **observée** | le 15ᵉ est-il pire que le 3ᵉ ? |
| pertes consécutives | ES 3 / NQ 2 | **observée** | jamais atteint sur 57 jours |
| cooldown gain / perte | 60 / 90 min | **observée** | jamais atteint en 15 min |
| drawdown | à définir | **observée** | seuil non mesuré |

---

## Famille 5 — ÉTAT DE L'EXÉCUTION : *puis-je physiquement passer l'ordre ?*

| porte | source | classe | mesure |
|---|---|---|---|
| position déjà ouverte | état interne | **appliquée** | **journalisée depuis le 06/09.** Avec des trades de 20 barres, c'est probablement la porte la plus fermée — et elle n'apparaissait dans aucune mesure |
| DTC déconnecté | connecteur | **appliquée** | repli PAPER, jamais d'ordre à l'aveugle |
| contrat JSONL ≠ contrat du compte | `contrats.py` | **appliquée** | à brancher avant le rollover du 10/09 |
| marge insuffisante | compte | **appliquée** | sans objet en SIM |

---

## Ce qui manque, et qui ne se devine pas

1. **Le spread** — à ajouter au dumper. Le DMP a accès au carnet, c'est une
   ligne de C++. Sans lui, L0 vit avec une porte de liquidité en moins.
2. **`atr_hnorm_r`** — à recalculer dans `recalc.py` : `atr_14m` / médiane de
   `atr_14m` à la même minute sur les 20 jours précédents. Même logique que
   `rvol_r`, jours passés uniquement, chauffe de 20 jours.
3. **L'horloge du VPS** — aucune mesure de dérive aujourd'hui.
4. **L'âge des niveaux MenthorQ** — le dump est vivant, sa fraîcheur n'est pas
   contrôlée.

---

## Ce que la mesure a établi, et qu'il ne faut pas réouvrir

- **`L0_NEWS` est la meilleure porte du système** : −4,82 ATR, et c'est le seul
  chiffre qui **n'a pas bougé** entre l'évaluation en série et l'évaluation
  indépendante. Aucune autre porte ne fermait ces quatre signaux : sa mesure
  était déjà propre.
- **`MAX_TRADES` coûte de l'argent** : ses rejetés font mieux que les retenus,
  sur les deux instruments. Elle passe en observation.
- **L5 n'est pas inerte** — c'était ma mesure qui l'était. Trois vétos sur quatre
  se déclenchent une fois l'ordre éliminé. Seul le véto SL reste à zéro.
- **La porte VIX n'est pas mesurable sur ce lot.** Période sans épisode de
  volatilité. Le jour où elle ferme quelque chose, ce sera la première fois — et
  il faudra le lire comme tel, pas comme une anomalie.

---

## Calendrier

**Lundi 07/09 — Labor Day.** Séance raccourcie, clôture 13:00 ET, réouverture
18:00 ET = **22:00 UTC**. La barre de 21:00 UTC n'existe pas : le test L6 de
21:01 ne peut pas réussir, et ce n'est pas un bug. **Le premier vrai test de
bout en bout est mardi 08/09 à 21:01 UTC.**

**Jeudi 10/09 — rollover.** Premier passage du contrôle.
