# BRIEF — Couche L0, l'interrupteur

*À traiter en parallèle par Claude Code et Fable, puis à comparer. Rien n'est
scellé tant que les deux versions n'ont pas été confrontées. Une fois scellée,
L0 ne se rouvre plus : on passe à L1.*

---

## 1. Ce que L0 est, et ce qu'elle n'est pas

**L0 répond à une seule question : « a-t-on le droit de trader, là, maintenant ? »**

Elle ne regarde ni le prix, ni la direction, ni le setup. Elle ne pondère rien,
elle ne score rien. C'est un **interrupteur booléen en série** : une seule
condition vraie suffit à bloquer, et le motif du blocage est journalisé.

Ce qu'elle **n'est pas** : un filtre de qualité (c'est L3), un juge de contexte
(c'est L1), un gestionnaire de risque par trade (c'est L5).

**Règle du chantier** : une porte qui ne rejette rien est *inerte* — elle donne
l'illusion d'une protection. Une porte qui rejette tout est *étrangleuse*.
Ni l'une ni l'autre ne passe à la couche suivante.

---

## 2. Les données disponibles — mesuré le 06/09 sur 20 jours ES, barres `stable`

| colonne | provenance | présente | active |
|---|---|---|---|
| `is_news_60m` | **B** | 100 % | 1,6 % |
| `is_eco_blocked` | R | 100 % | 1,2 % |
| `is_critical_news_60m` | R | 100 % | 1,1 % |
| `is_news_5m` | R | 100 % | 0,1 % |
| `is_in_us_cash` | **B** | 100 % | 27,5 % |
| `is_session_blocked` | **B** | 100 % | 9,6 % |
| `is_blocked_combined` | **B** | 100 % | 10,7 % |
| `is_in_london` / `is_in_asia` | **B** | 100 % | 28,8 % / 39,5 % |
| `gamma_block_long` / `_short` | **B** | 100 % | 2,0 % / 3,9 % |
| `vix_regime` / `vix_level` | **B** | 100 % | — |
| `data_quality_flag` | C | 100 % | filtre de lecture |
| **`atr_14m_hnorm`** | — | **ABSENTE** | — |

**Sources hors JSONL** : `CORE/eco_calendar.py` (26 Ko, calendrier économique
autonome), l'état interne du bot (position ouverte, trades du jour, P&L du jour,
horodatage du dernier trade), et `sessions.yaml` (fériés CME, dimanches,
journées en panne datées) — **ce dernier n'existe pas encore et doit être créé.**

---

## 3. Ce qui est déjà mesuré — ne pas refaire, contester si désaccord

Mesure du 06/09 sur les **57 jours**, tous déclencheurs confondus, devenir signé
dans le sens du trade et à 20 barres. *Positif = la porte a fermé un trade qui
aurait gagné.*

| porte | ferme | devenir des rejetés | lecture |
|---|---|---|---|
| `L0_NEWS` | 1,0 % | **−4,82 ATR (ES)**, −1,18 (NQ) | la meilleure porte du système |
| `L0_MAX_TRADES_JOUR` | **36,4 % ES / 43,4 % NQ** | **+0,178 / +0,251** | étrangleuse **et** coûteuse |
| `L0_SESSION_BLOQUEE` | 2,1 % / 4,3 % | +0,179 / −0,032 | non significatif |
| `L0_EOD_LOCKOUT` | 1,5 % | — | peu actif |
| *(retenus)* | 57,4 % / 51,1 % | +0,161 / +0,176 | référence |

**Contrôle négatif** : un signal aléatoire de même cadence rend **−0,057 sur ES
(IC 95 % [−0,210 ; +0,096])** et **−0,000 sur NQ ([−0,134 ; +0,134])**.
Conséquence : seul `L0_NEWS` sort du bruit — de trente écarts-types. Tout le
reste, y compris `MAX_TRADES`, tombe **dans** l'intervalle du hasard.

---

## 4. Les questions auxquelles il faut répondre

**Q1 — Quelles portes sont APPLIQUÉES, lesquelles sont OBSERVÉES ?**
Une porte observée journalise « aurait bloqué » sans agir. C'est la parade
contre l'erreur de décembre : ouvrir une porte pour avoir des trades. Justifier
chaque classement par une mesure, pas par une intuition.

**Q2 — La fenêtre news doit-elle être élargie ?**
Elle est la meilleure porte (−4,82 ATR) et ne ferme que 1 % des signaux, sur
**4 occurrences seulement**. V1 bloquait −15/+30 min autour des HIGH/CRITICAL.
Élargir coûterait peu — mais 4 occurrences, est-ce assez pour décider ?

**Q3 — Que faire de `MAX_TRADES_JOUR` ?**
La règle Douglas dit 5 trades ; la mesure dit qu'elle ferme 40 % des signaux et
que ses rejetés font *mieux* que les retenus. Mais l'écart tombe dans le bruit.
Observer les trois valeurs (5/10/20) ? Ou trancher autrement ?

**Q4 — Le stop journalier : quel seuil, et est-il mesurable ?**
1 000 $ en SIM demande **31,8 pertes d'affilée sur ES** (SL de 1 ATR = 31,43 $)
contre ~7 signaux par jour. Il est **inerte par construction**. Faut-il un seuil
en ATR plutôt qu'en dollars, pour qu'il morde et se mesure ?

**Q5 — `atr_14m_hnorm` est ABSENTE des JSONL.**
La clause de non-participation de la mission en dépend (`> 1,8`). Elle existe
dans le dataset réduit mais pas dans les données live. Que met-on à la place —
`atr_14m` brut normalisé au vol, ou autre chose ?

**Q6 — `sessions.yaml` n'existe pas.**
Fériés CME, dimanches, journées en panne datées. Qui le produit, à partir de
quoi, et comment on le tient à jour ?

**Q7 — L'ordre des portes compte-t-il ?**
Elles sont en série : la première qui bloque donne le motif. Si `NEWS` et
`MAX_TRADES` sont vraies ensemble, le motif journalisé n'est pas le même selon
l'ordre — et la mesure du devenir par porte s'en trouve faussée.

---

## 5. Le livrable attendu

1. **La liste des portes de L0**, chacune avec : sa source (colonne ou état),
   sa classe (appliquée / observée), son seuil, **la distribution mesurée de ce
   seuil**, et la plage de rejet attendue.
2. **L'ordre d'évaluation**, justifié.
3. **Ce qui manque** et comment le produire (`sessions.yaml`, `atr_14m_hnorm`).
4. **Un test par porte** : une barre qui passe, une barre qui bloque.
5. **Ce qu'on refuse de trancher** et pourquoi — les 4 occurrences de news, par
   exemple, ne suffisent peut-être pas.

---

## 6. Les règles qui s'appliquent, sans exception

- **Aucun seuil sans sa distribution mesurée écrite à côté.** Six confusions
  d'unités en une semaine ; deux hypothèses rendues non testables par des seuils
  hors distribution (`ib_range_atr < 0,40` = 0,13 % des barres ;
  `> 1,2` = 0,00 %).
- **Données collectées ou dérivées uniquement. Aucun proxy.**
  `mq_gamma_condition` a été retiré pour cette raison.
- **Booléens en série, jamais de somme pondérée.** La somme pondérée de janvier
  laissait passer un contexte à 0,12.
- **Une porte qui bouge doit bouger sur une mesure de devenir**, jamais sur
  « on n'a pas assez de trades ».
- **Chaque décision journalisée** dans l'entonnoir avec son motif ; le motif
  d'un BLOQUÉ ne peut pas être vide.

---

## 7. Critère de scellement — réécrit le 06/09

**Une porte a le droit d'entrer dans la chaîne si on sait ce qu'elle ferme, ce
que ça coûte, et pourquoi elle dort quand elle dort.**

*L'ancien critère — une plage de rejet de 15–30 % **par porte** — était
arithmétiquement contradictoire. À dix-neuf portes appliquées fermant chacune
15 %, il resterait **4,56 %** des signaux : il demandait à chaque porte d'être un
étranglement. Il avait été écrit quand L0 en comptait quatre. Mesure du 06/09 :
**zéro porte sur dix-neuf** dans sa plage. Corrigé avant de sceller dessus les
yeux fermés — c'est le premier critère du chantier qu'on répare au lieu de le
déclarer rempli.*

### Sur l'agrégat — la seule plage

- **15 à 30 % des signaux retenus** après toute la couche. Mesuré 21,3 % ES /
  21,6 % NQ.
- **Le devenir des retenus doit être au moins celui du contrôle négatif**, sinon
  la couche filtre dans le mauvais sens. Mesuré +0,124 ES contre −0,057
  [−0,210 ; +0,096] ; +0,253 NQ contre −0,000 [−0,134 ; +0,134].

Ajouter une porte se justifie **par la porte**, jamais par l'agrégat qui bouge.

### Par porte — trois verdicts, chacun avec son test

**Elle mord.** Elle ferme au moins un signal, et son devenir est lisible avec son
intervalle — soit par l'effectif (n ≥ 10), soit parce que **l'effet sort de
l'intervalle du contrôle négatif**. *Le seuil d'effectif sert la lisibilité
statistique, pas la vérité : `NEWS` ferme quatre signaux pour un devenir de
−4,82 ATR, trente écarts-types du hasard. Un critère qui la classerait
« dormante » manquerait la meilleure porte du système.*

- Devenir **négatif ou indiscernable du hasard** → elle entre **appliquée** :
  elle protège, ou ne coûte rien de mesurable.
- Rejetés **meilleurs que les retenus, hors de l'intervalle** → elle entre
  **observée, jamais appliquée**. C'est le cas de `MAX_TRADES`, et c'est la
  règle qui empêche de refaire décembre.

**Elle dort, et on sait pourquoi.** Peu ou pas de rejets, avec une raison écrite
parmi quatre, chacune portant sa preuve :

| raison | preuve exigée | exemples |
|---|---|---|
| sécurité élémentaire | elle ne coûte rien en dormant, et un cas de test la réveille | `STOP_JOURNALIER` |
| hors terrain | le faux live la fait fermer | les sept muettes |
| redondante par une **autre** source | les deux voies lisent des sources différentes | `EOD_LOCKOUT` (horloge) vs `SESSION_BLOQUEE` (colonne) |
| le cas ne s'est pas présenté | **la distribution de la grandeur**, qui montre que le seuil n'a jamais été approché | `VIX_REGIME` (VIX plafonné à 22,01), `DATA_FENETRE_MELANGEE`, `PREMIERE_BARRE` |

*La quatrième raison est la plus exigeante à prouver, et c'est voulu : un seuil
jamais approché peut être hors distribution — quatre fois cette semaine. La
distribution départage « elle dort » de « elle est mal réglée ».*

Une redondance qui lit la **même** source qu'une autre porte se retire.

**Elle se retire.** Zéro rejet sans raison écrite, ou une raison que rien ne
prouve. *Une porte à zéro n'est pas un échec ; une porte à zéro dont personne ne
sait pourquoi en est un.*

### Deux exigences transversales

Ce sont celles qui ont cédé cette semaine.

1. **Aucun seuil sans sa distribution datée dans `rapports/`.**
2. **Toute porte appliquée doit fermer quelque chose quelque part** : un signal
   du lot, un scénario de faux live, **ou un cas de test**. Une porte qui n'a
   jamais rien fermé, nulle part, n'a pas le droit d'être appliquée. *Cette
   exigence est déjà mécanique : `couverture()` dans `test_portes.py` échoue si
   une porte n'a pas sa barre qui passe **et** sa barre qui bloque.*

### L0 sous ce critère

L'agrégat est dans la plage et les retenus battent le contrôle négatif. `NEWS`,
`VETO_GAMMA` mordent et protègent. `POSITION_OUVERTE` mord, et son coût est
indiscernable de zéro — les fantômes le prouvent. `MAX_TRADES` est observée pour
la bonne raison. Les douze dormantes ont chacune sa raison et sa preuve.

**Rien à changer au code.**

---

*Écrit par Fable, amendé sur trois points par Claude Code après mesure : le
seuil d'effectif qui manquait `NEWS`, la quatrième raison de dormance, et la
preuve par cas de test là où le faux live ne couvre que six portes sur
vingt-cinq.*
