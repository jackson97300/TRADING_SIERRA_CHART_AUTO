# Pré-enregistrement — mesure d'ALIGNEMENT du biais

**Écrit le 14/09/2026, AVANT toute mesure.** Aucun chiffre de résultat ne
figure ici. Ce document existe pour qu'on ne puisse pas, après coup, choisir
l'hypothèse qui a gagné et raconter qu'on la visait.

## La question, telle que Jackson l'a posée

> « Le biais ne dit pas si on gagne ou si on perd. Il détermine juste si on est
> aligné au sens. C'est une chose différente de si on gagne. »

Donc : **le côté annoncé par un biais s'accorde-t-il au signe du déplacement
du prix qui suit, plus souvent que ce que le marché donne gratuitement ?**

Pas de stop, pas de cible, pas de coûts. Ce n'est pas une mesure de
rentabilité, et elle ne doit jamais être présentée comme telle.

## Périmètre des données

`DATA/live_enriched/sierra/{ES,NQ}` **uniquement** (décision Jackson, règle
souveraine du 16/06/2026). Les 129 jours de `DATA/live_enriched/{ES,NQ}`
(déc. 2025 – mai 2026) sont ÉCARTÉS : mesure du 14/09 sur les 2 jours de
chevauchement — `close` identique sur 408/412, mais `dist_vwap_w` et `atr_14m`
**différents sur 100 % des barres**. Même marché, définitions différentes.

Jours de campagne (>= 20260908) **exclus** : leur devenir est fermé jusqu'au
jour 61. Lot attendu : ~52 sessions par instrument après chauffe.

## Unité d'analyse : LA SESSION

Pas la barre. Pas le trade. C'est la leçon du 04/07/2026, payée une fois :
un modèle affichait PF 1,81 / DSR 0,99 en comptant les trades, et **aucun
t-stat > 2,0** une fois ramené à la session — les barres d'une même journée ne
sont pas des observations indépendantes.

Corollaire mesuré aujourd'hui : B1p garde le même côté 15 à 23 barres sur 26.
Compter en barres multiplierait le N par ~25 et rétrécirait l'intervalle d'un
facteur 5 pour rien.

## Les biais candidats — liste fermée, arrêtée avant mesure

1. `B1p` — position vs VWAP **semaine** (la couche L1 actuelle)
2. `vwap_d` — position vs VWAP **du jour**
3. `pente_vwap` — pente de la VWAP du jour
4. `cvd` — CVD de session
5. `hvl` — côté du HVL
6. `mon_module` — les quatre capteurs à la majorité

## Les horizons — grille fermée

K = 1, 2, 4, 8 barres de 15 min (15 min, 30 min, 1 h, 2 h).

**6 candidats x 4 horizons = 24 tests.** Ce nombre est déclaré ici pour le
haircut de tests multiples. Tous les résultats seront rapportés, y compris les
mauvais : sélectionner après coup est exactement ce que ce document interdit.

## Les deux étalons — et pourquoi il en faut DEUX

1. **Hasard**, tiré une fois par jour, à couverture égale. Le `seuils.yaml` le
   prescrit déjà : « un faux biais qui changerait à chaque barre serait plus
   facile à battre, et l'étalon trop clément ».
2. **Toujours LONG** (et toujours SHORT). C'est l'étalon qui compte le plus.
   La période 2026 est majoritairement haussière — un biais qui dit souvent
   LONG sera aligné plus souvent **par la seule dérive**, sans rien savoir.
   Un candidat qui ne bat pas « toujours LONG » n'apporte rien.

## Attendu, écrit avant

1. **B1p sera proche de « toujours LONG »**, à quelques points près, et ne le
   battra pas de façon significative. Raison : c'est un indicateur quasi
   constant dans la journée (un avis par jour), donc il ne peut pas distinguer
   deux moments d'une même séance.
2. **Si quelque chose marche à K court (1-2 barres), ce sera un indicateur de
   flux** — pente de VWAP ou CVD — pas un indicateur de position.
3. **Au niveau session, la majorité des 24 tests n'atteindra pas |t| > 2,0.**
   Cohérent avec le 04/07. Si TOUS passent, je soupçonne un bug avant de
   soupçonner un edge.
4. **L'alignement de B1p sera symétrique entre ES et NQ** (ils s'accordent à
   96 %) : ce n'est pas une confirmation indépendante, c'est la même mesure
   deux fois.

## Ce que cette mesure ne dira JAMAIS

- Si le bot gagnerait de l'argent. Être aligné 60 % du temps ne suffit pas si
  les 40 % à contresens portent des déplacements plus amples.
- Si ça continuera de marcher.
- Rien sur les jours de campagne : ils ne sont pas dans le lot.

## AMENDEMENT du 14/09, écrit AVANT d'avoir vu le moindre résultat

Jackson a précisé le travail du biais : *« donner la direction que le trader
devrait prendre pour avoir le plus de chances d'être aligné à la tendance —
s'il dit acheteur, les futures données devraient être acheteuses plus de
fois »*. Deux corrections en découlent, et elles améliorent le protocole :

**1. La métrique devient un ÉCART ENTRE GROUPES, pas un taux.**

    P(aligné | le biais dit LONG) − P(aligné | le biais dit SHORT)

« Plus de fois » ne veut rien dire sans référence. La période 2026 est
majoritairement haussière : un biais qui dirait toujours LONG serait « aligné »
bien plus de 50 % du temps sans rien savoir. L'écart entre les deux groupes
annule la dérive, qui les touche identiquement. Un biais sans information rend
zéro. L'étalon « toujours LONG » reste rapporté, mais il n'est plus le juge.

**2. DEUX métriques d'alignement, pas une.**

  - `prix` : `close(t+k) − close(t) > 0`
  - `flux` : somme de `delta_bar` sur `t+1..t+k` > 0 — c'est le sens littéral
    de « données acheteuses », et ce n'est pas la même question que le prix.

Un biais qui prédit le flux mais pas le prix, ou l'inverse, est un fait qu'on
veut voir. Les rapporter séparément.

**Conséquence sur les tests multiples** : 6 candidats x 4 horizons x 2
métriques = **48 tests**, et non 24. Le nombre est redéclaré ici pour le
haircut. Tous les résultats seront rapportés.

**Colonnes utilisées, toutes au registre** (règle du 14/09) : `dist_vwap_w`,
`dist_vwap_d`, `vwap_slope_r`, `cvd_sess_r`, `dist_mq_hvl`, `dist_prev_vah`,
`dist_prev_val`, `delta_bar`, `close`.

## Règle d'arrêt

Si un candidat bat les deux étalons avec |t| > 2,0 au niveau session, il est
**candidat**, pas retenu. Il devra ensuite passer le hors-échantillon et la
vérification des coûts avant d'entrer dans une décision de bot.
