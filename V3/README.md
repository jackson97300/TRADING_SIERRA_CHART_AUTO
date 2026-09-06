# MIA V3

Un bot de trading construit **couche par couche**, chaque brique mesurée avant
qu'on passe à la suivante. Ce dépôt ne contient que du **code** et des
**rapports agrégés** — aucune donnée de marché, aucun identifiant, aucun niveau
sous licence. Un garde-fou le vérifie avant chaque commit
(`tests/test_structure.py`).

## Pourquoi ce dépôt existe

Trois bots l'ont précédé. Aucun n'a échoué parce qu'il refusait des trades :
ils ont échoué parce que **personne n'a jamais su ce que les refusés seraient
devenus**. V1 embarquait 27 modules dont personne ne savait ce que chacun
filtrait.

D'où la règle du chantier, qui gouverne tout ce dossier :

> Une porte qui ne rejette rien est **inerte** — elle donne l'illusion d'une
> protection. Une porte qui rejette tout est **étrangleuse**. Ni l'une ni
> l'autre ne passe à la couche suivante.

## Où regarder

| fichier | ce qu'il dit |
|---|---|
| [STATUS.md](STATUS.md) | l'état des briques — **à lire en premier** |
| [DECISIONS.md](DECISIONS.md) | les arbitrages, avec leur date et la mesure à l'appui |
| [LISEZ_MOI.md](LISEZ_MOI.md) | la carte du dossier |
| [layers/L0_interrupteur/SPEC.md](layers/L0_interrupteur/SPEC.md) | **L0, la couche à valider** |

Un dossier par couche, et tout ce qui la concerne dedans : sa spec, ses seuils,
son code, ses tests, sa mesure, ses rapports.

## L'état des couches

| couche | rôle | état |
|---|---|---|
| **L0** | a-t-on le **droit** de trader, là, maintenant ? | **mesurée — à valider** |
| REG | quel marché : gamma HVL + largeur IB | mesurée |
| L1 | le biais 1 h / 4 h | écrite |
| L3 | les setups 15 min | écrite |
| L4 | la confirmation order flow 1 min | **absente** |
| L5 | combien, et où est le stop | mesurée |
| L6 | les contrôles quotidiens sur les données | passée |

## Ce qu'on demande, maintenant

**Valider L0, ou dire ce qui manque pour qu'elle soit validable.** Les critères
de scellement sont dans [layers/L0_interrupteur/BRIEF.md](layers/L0_interrupteur/BRIEF.md).
Après scellement, L0 ne se rouvre plus : on passe à L1.

Les points sur lesquels une contradiction serait la plus utile :

1. **`POSITION_OUVERTE` ferme 72,5 % des signaux** et reste appliquée. Ses
   refusés sont simulés en trades fantômes complets — coût mesuré ES
   −0,055 ± 0,118, soit le contrôle négatif aléatoire (−0,057 [−0,210 ; +0,096]).
   Est-ce qu'une porte à 72,5 % peut être « dans sa plage » sous prétexte que ce
   qu'elle ferme ne vaut rien ?
2. **Six portes sont à zéro rejet** (`EOD_LOCKOUT`, `VIX_REGIME`,
   `MAX_TRADES_JOUR`, `STOP_JOURNALIER`, `STOP_PROPFIRM`, `COOLDOWN`). Elles
   restent déclarées. Garder une porte inerte, est-ce de la prudence ou de la
   décoration ?
3. **Cinq portes sont déclarées `absentes`** (spread, horloge VPS, âge MenthorQ,
   volatilité extrême, choc VIX) — donnée non collectée ou seuil non mesuré.
   Est-ce que L0 peut être scellée avec cinq trous déclarés ?
4. **`L0_NEWS` ferme 1,1 % pour un devenir de −4,82 ATR**, sur **quatre
   occurrences**. Trente écarts-types du hasard, mais n = 4. Élargir la fenêtre,
   ou refuser de trancher ?

## Les règles qui gouvernent ce dossier

1. **Aucun seuil dans le code.** Il vit dans le `seuils.yaml` de sa couche, avec
   sa **distribution mesurée écrite à côté**.
2. **Une porte n'existe que si elle est déclarée.** `test_portes.py` échoue si
   une porte du code n'a pas de ligne YAML, **et l'inverse**.
3. **Données collectées ou dérivées uniquement. Aucun proxy.** Une condition non
   collectée n'existe pas.
4. **Toutes les portes sont évaluées indépendamment.** L'évaluation en série
   attribuait chaque rejet à la première porte qui fermait — il n'y a pas de bon
   ordre, il n'y en a aucun.
5. **Un rapport dont le tableau ne correspond pas à son journal n'est pas
   publiable.** Contrôle automatique depuis l'incident du 06/09 : 312 rejets
   annoncés pour 282 réellement journalisés.
