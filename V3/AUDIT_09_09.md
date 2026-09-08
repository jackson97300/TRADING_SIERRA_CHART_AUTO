# AUDIT V3 du 09/09 — deux agents, angles croisés

*Demande Jackson : « on a laissé passer trop d'erreurs ». Périmètre : V3
(8 783 l.) + les 9 fichiers CORE qu'elle importe. Deux agents indépendants —
COUVERTURE (chaque module voit-il tout ce qu'il prétend voir ?) et CALCULS
(les chiffres sont-ils justes ?). Chaque finding est MESURÉ avec sa commande
de reproduction ; les faux positifs écartés sont listés, ils valent autant.*

## Le fil commun — un seul défaut, appliqué neuf fois

> « `campagne.py` a été durci hier soir (R8, fail-loud avant troncature,
> vide ≠ absent) et ses quatre frères de la séquence de 21:01 —
> `barrieres_du_jour`, `reactions`, `marges`, `ombre16` — ne l'ont pas été.
> Le correctif existe ; il n'a été porté qu'à un fichier sur cinq. »

C'est la leçon la plus rentable de l'audit : **il n'y a pas neuf choses à
corriger, il y a un contrôle à propager**. Tronquer sous `try`, écrire le
motif du zéro, compter en épisodes, refuser la date hors ombre.

## URGENT — daté, avant le 10/09

**Le rollover.** `calendrier.contrat_actif('20260910')` rend **Z26** ; le
fichier ES du 08/09 ne contient que **ESU26**. `L0_CONTRAT_INACTIF` est en
mode **appliquée**. Simulation sur le 07/09 (seul jour du lot avec un signal
des QUATRE) : le signal passe de « pas de blocage » à **BLOQUÉ**. Si Sierra
ne bascule pas le 10/09 au matin, **100 % des signaux des QUATRE sont fermés
à L0** dès le jour 3. Aggravant : `campagne.contrat_ok` ne lit que la
PREMIÈRE ligne du premier fichier — un fichier à cheval sur deux contrats
rend un verdict uniforme pour la journée. STATUS dit « à REGARDER » ; c'est
un interrupteur, pas un témoin. **Décision à prendre avant mercredi matin.**

## GRAVE — fausse la mesure du jour 61

| # | Quoi | Mesure |
|---|---|---|
| 1 | **`ombre_c2` n'applique pas la date d'ombre** — la règle « on n'active JAMAIS rétroactivement » est dans sa docstring, pas dans son code | **12 lignes sur 23** déjà écrites hors ombre : C2_EOD (ombre 08/09) a 4 signaux les 03-04/09 |
| 2 | **`rvol_zscore` lu à la DERNIÈRE MINUTE du bloc** — porte L5 appliquée | NQ **64 blocages** contre **0** si la barre est reconstruite : 100 % d'artefact d'agrégation |
| 3 | **`_dist_hvl_atr` : ticks ÷ points** — la zone morte de 1,0 ATR vaut en réalité 0,25 | ES 67 barres bloquées au lieu de 213 ; **le signe du devenir s'inverse** (−0,031 → +0,039) |
| 4 | **`chaine.py` journalise les trous DEUX FOIS** | **210 lignes sur 624** (33,7 %) ; `pourquoi.py` annonce 204 blocages L0 au lieu de 99 |
| 5 | **Les 4 coureurs tronquent avant la boucle sans le `try` de R8** | Un crash laisse un fichier **vide**, lu comme « jour couru muet » |
| 6 | **`ombre16` ne journalise pas son aveuglement** | 16 lignes en nominal → 6 avec 4 colonnes retirées, **zéro ligne muette** : jour aveugle = jour calme |
| 7 | **`reactions` perd les 17 lignes de dénominateur d'un instrument sans données** | Samedi 05/09 : le fichier ne contient que l'en-tête |
| 8 | **`rythme_soir` peut mesurer DEUX journées** (`dernier_jour()` vs `utcnow()`) | Étapes 1,4 → 20260909 / étapes 2,3,5 → 20260908. Après le 25/10, l'étape 1 rejouerait un jour à peine commencé |
| 9 | **`marges.py` : le motif commode écrasait l'aveuglement** | DIV rendait `marge_non_exposee` au lieu de `colonne_absente`. **CORRIGÉ** (0e4bf73) |

## Les portes qui ne peuvent pas s'exprimer

- **`L0_STOP_JOURNALIER`, `L0_STOP_PROPFIRM`, `L0_COOLDOWN`** : `pnl_jour` et
  `fin_cooldown` ne sont écrits **nulle part** dans le dépôt. Ces trois
  portes rendent `False` en toute circonstance — et le YAML affirme le
  contraire depuis ma revue du 08/09 (« MESURABLE, jamais inerte par
  construction »). C'est **mon** affirmation qui est fausse.
- **L4 est classée « observée »** mais aucune couche hors L0/L5 n'écrit dans
  l'entonnoir (`chaine` n'importe que ces deux modules). Au jour 61, il n'y
  aura **pas une ligne L4** à rejuger. Ses seuils, ses tests et son rapport
  existent ; sa trace n'existera pas.
- **L6 n'a aucun producteur quotidien.** `surveillance_l6` vit dans
  `CORE/research/`, n'est dans aucune tâche planifiée ; dernier fichier
  produit le 04/09. Or `L0_DATA_L6_ALERTE` est appliquée : elle a bloqué 84
  battements du jour 1 sur un verdict vieux de 4 jours, puis passera en trou
  permanent — **fail-closed en strict**.

## À recalibrer au cycle 2 (jamais pendant la campagne)

`buffer_sweep_atr` (0,33/0,27 mesuré contre 0,57/0,50 sur la même fenêtre) ;
les `prev_*` **ne sont pas figés en w0** — ils sautent à 13h00 ET sur 94,4 %
des jours, saut médian 55,75 pts, ce qui contamine toute mesure
rétrospective de 80PCT (46 signaux au lieu de 69) ; `L0_EOD_LOCKOUT` en UTC
figé bloquera la barre de C2_EOD à partir du 01/11, **en pleine campagne**.

## Ce que les agents ont écarté — et c'est précieux

Neuf faux positifs mesurés puis abandonnés côté couverture (les trois listes
de niveaux SONT des sous-ensembles ; aucune colonne exigée n'est perdue à
l'agrégation le 08/09 ; le rejeu est déterministe au bit près sur 8 journaux
sur 9). Cinq côté calculs, dont le plus instructif : **le rendement de
C2_EOD recalculé depuis les barres 1 min tombe à 0,00000 d'écart sur 114
jours-instrument** — zéro verdict discordant. Le calcul du seul setup qui
produit de la puissance est juste.

Et une erreur de plus, la mienne : « le chart VIX est mort depuis le 04/09 »
— ma mesure comptait la nuit, un dimanche et un férié. En cash : **0 zéro du
01 au 04/09**. Corrigé, incident écrit ([INCIDENT_LOG](../DOCS/INCIDENT_LOG.md) 09/09).
