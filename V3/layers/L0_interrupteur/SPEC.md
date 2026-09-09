# L0 — SPEC : les conditions sont-elles réunies pour trader ?

*Écrit le 06/09/2026, Claude Code + Fable, révisé après revue. Chaque porte
porte sa source et sa classe. Ce document est la source de vérité de L0 ; le
code en découle, jamais l'inverse.*

**Les taux mesurés ne sont pas dans ce document.** Ils vivent dans
[`rapports/`](rapports/), datés, produits par `mesure_57j.py`. Un chiffre
recopié dans une prose survit au run qui l'a invalidé : la version précédente
annonçait 93,5 % pour `POSITION_OUVERTE` quand le CSV disait 72,5 %, et 41,6 %
pour `MAX_TRADES` quand il disait 0. Ce qui reste ici, c'est **la question à
laquelle chaque porte répond** — pas sa réponse du jour.

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

## Famille A — QUALITÉ DES DONNÉES : *ce que je lis est-il vrai ?*

| porte | source | classe | mesure |
|---|---|---|---|
| porte | source | classe | ce qu'elle demande |
|---|---|---|---|
| `L0_DATA_INSTABLE` | `data_quality_flag` | **appliquée** | la barre est-elle `stable` — ni warmup, ni degraded ? |
| `L0_DATA_FENETRE_MELANGEE` | `window_version` | **appliquée** | la journée mélange-t-elle `w0` et `w1` ? Exiger `w1` fermerait tout l'historique — le danger est le mélange, pas la valeur |
| `L0_DATA_INCOMPLETE` | agrégation | **appliquée** | la barre agrégée est-elle entière ? |
| `L0_DATA_PERIMEE` | `age_s` (live) | **appliquée** | la barre a-t-elle moins de 90 s ? |
| `L0_DATA_COLONNE_MORTE` | `stale.csv` | **appliquée** | une colonne que je lis est-elle figée ce jour-là ? |
| `L0_DATA_L6_ALERTE` | `surveillance_l6.py` | **appliquée** | la surveillance a-t-elle levé une alerte ? |
| âge des niveaux MenthorQ | `mq_levels_1.0` | **absente** | le dump est vivant, sa fraîcheur n'est pas contrôlée |
| horloge du VPS dérivée | à construire | **absente** | rien ne la mesure aujourd'hui |

**Ces six portes ne rejettent presque rien hors ligne, et ce n'est pas un
défaut.** `charger_jour` filtre les barres instables en amont : tout ce qui
arrive à la décision est déjà propre. **En live, rien ne garantit ça** — le bot
lit la dernière barre du fichier, et sans ces portes personne ne vérifie
qu'elle est saine, fraîche, complète, dans la bonne fenêtre. Une porte de la
famille A qui mesure 0 en backtest n'est pas inerte : elle est **hors de son
terrain**, et son terrain est mardi 9h30.

Trois d'entre elles lisent une information qui **n'existe pas hors ligne**
(l'âge de la barre, le verdict L6, les colonnes figées). Elles répondent alors
`None` — « je ne peux pas répondre » — jamais `False`. La chaîne journalise le
trou sous `TROU_<porte>` ; en live (`strict=True`) le trou **bloque**.

---

## Famille B — TEMPS ET CALENDRIER : *est-ce un moment où décider ?*

| porte | source | classe | mesure |
|---|---|---|---|
| hors session cash | `is_in_us_cash` | **appliquée** | 27,5 % des barres en cash |
| `is_session_blocked` | `eco_calendar.py` | **appliquée** | ferme **10,1 % ES / 14,0 % NQ**, devenir +0,07 / +0,04 |
| `L0_NEWS` : ±60 min, TOUS niveaux | `is_news_60m` | **appliquée** | **−4,82 ATR ES, −1,18 NQ.** Trente écarts-types du hasard. Née d'une perte de 1 156 $. **A3 (Fable 09/09)** : le code lit `is_news_60m` (±60 min, tous niveaux) — la distinction CRITIQUE/ÉLEVÉE ci-dessous N'EST PAS appliquée |
| news par niveau : CRITIQUE −15/+30, ÉLEVÉE −5 | FOMC/NFP/CPI vs PIB/ISM | **NEXT_CYCLE** | exige le NIVEAU dans le JSONL ; la fenêtre élargie n'a que 4 occurrences, trop peu sans mesure |
| férié CME | `sessions.yaml` | **appliquée** | **déclarée, jamais déductible des données** : Juneteenth avait 841 barres et 12 % du volume |
| demi-séance (clôture 13:00 ET) | `sessions.yaml` | **appliquée** | le CME ferme plus tôt, le marché reste ouvert |
| dimanche / week-end | vendredi 15:30 → dimanche 18:15 ET | **appliquée** | déjà dans `eco_calendar` |
| rollover en cours | `roll_calendar.py` | **appliquée** | jeudi 10/09 : premier test |
| EOD lockout −10 min | horaire | **appliquée** | 20h UTC : 100 % bloqué |
| première barre de 9h30 | rang dans la journée | **appliquée** | aucune décision avant que le régime soit lu à 10h30 |

---

## Famille C — CONDITIONS DE MARCHÉ : *le marché est-il tradable ?*

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

## Famille D — ÉTAT DU RISQUE : *ai-je encore le droit de perdre ?*

| porte | seuil | classe | mesure |
|---|---|---|---|
| stop journalier SIM | −1 000 $ | **appliquée** | **peu probable sur NQ, improbable sur ES, MESURABLE** — jamais « inerte par construction » (revue 08/09, A2 : 13,2 pertes de 1 ATR sur ES, **4,9 sur NQ** — base SL médians 75,55 $/202,28 $, qui corrige aussi le vieux « 31,8 » calculé sur 31,43 $). Séance fermée dessus = LECTURE règle 16, lue à part |
| stop prop firm réel | −200 $ | **observée** | « aurait bloqué ici » — à la lecture, combien de jours coupés |
| `max_trades/jour` | 5 | **observée** | **devenue INERTE** : 0 rejet une fois `POSITION_OUVERTE` appliquée. Les 41,6 % mesurés le 06/09 venaient d'un état où la position n'était pas suivie — à ~1,5 trade retenu par jour, la limite de 5 n'est jamais atteinte |
| rang du trade dans la journée | — | **observée** | le 15ᵉ est-il pire que le 3ᵉ ? |
| pertes consécutives | ES 3 / NQ 2 | **observée** | jamais atteint sur 57 jours |
| cooldown gain / perte | 60 / 90 min | **observée** | jamais atteint en 15 min |
| drawdown | à définir | **observée** | seuil non mesuré |

---

## Famille E — ÉTAT DE L'EXÉCUTION : *puis-je physiquement passer l'ordre ?*

| porte | source | classe | mesure |
|---|---|---|---|
| position déjà ouverte | état interne | **appliquée** | **ferme 72,5 % ES / 73,6 % NQ** — de loin la plus fermée, et elle n'apparaissait dans aucune mesure avant le 06/09. *Bloque l'entrée, ne bloque pas la mesure* |
| DTC déconnecté | connecteur | **appliquée** | repli PAPER, jamais d'ordre à l'aveugle |
| contrat JSONL ≠ contrat du compte | `contrats.py` | **appliquée** | à brancher avant le rollover du 10/09 |
| marge insuffisante | compte | **appliquée** | sans objet en SIM |

### « Bloque l'entrée, ne bloque pas la mesure »

C'est la phrase qui résume tout l'esprit de L0, et elle s'applique d'abord à
`POSITION_OUVERTE`. **Chaque signal qu'elle bloque est simulé en trade fantôme
complet** — pas un devenir à 20 barres, la triple barrière entière : entrée à
l'ouverture de t+1, TP +1,5 / SL −1,0 ATR, expiration, coûts déduits. Il produit
un `pnl_atr` exactement comme un trade réel, étiqueté `fantome` dans l'entonnoir.

Trois champs de plus, parce que c'est là qu'est l'information : `meme_sens`
(le signal allait-il dans le sens de la position, ou contre ?),
`barres_depuis_entree` (à quel moment de sa vie il arrive) et
`issue_position_ouverte` (ce que la position en cours a finalement fait).

Ce que ça permettra de lire à soixante jours, et qu'aucune campagne n'a su :
- **le coût de « une position par instrument »** — somme des `pnl_atr` fantômes.
  Si elle est nettement positive, le pyramidage devient une hypothèse mesurée,
  pas une envie ;
- **les signaux contraires comme sortie** — s'ils sont profitables *et* que la
  position finit en SL dans ces cas-là, un signal contraire est une règle de
  sortie. La meilleure façon d'en trouver une sans l'inventer ;
- **les signaux même sens comme renfort** — tôt et la position finit en TP,
  c'est un argument ; tard, pour rien.

**Ce que ça ne fait pas** : ça ne change rien à l'exécution. Une position par
instrument reste appliquée pendant toute la campagne. On mesure, on ne pyramide
pas — la décision viendra de la lecture.

**La position se ferme quand le trade se ferme, pas au bout de 20 barres.**
Première version : `libre_a = i + 20`, un forfait. Or un trade qui touche son TP
en trois barres libère la place en trois barres — le forfait fermait dix-sept
barres pour rien. Corrigé le 06/09 : `libre_a` est l'indice de sortie **réel**
de la triple barrière. Effet mesuré : `POSITION_OUVERTE` passe de **93,5 % à 72,5 %** et les signaux
retenus de **13,2 % à 22,1 %** — l'écart venait d'un forfait, pas du marché.
(Deux corrections sont dans ce chiffre : la sortie réelle, et la déduplication
par (barre, sens) — deux déclencheurs qui tirent LONG sur la même barre ne font
qu'un seul trade.)

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
- **`MAX_TRADES` ne mesure plus rien** : elle fermait 41,6 % tant que la position
  ouverte n'était pas suivie. Une fois `POSITION_OUVERTE` appliquée, elle tombe à
  **zéro rejet** — la vraie contrainte de cadence, c'est la place occupée, pas le
  compteur. Elle reste observée pour le jour où plusieurs positions coexisteront.
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
