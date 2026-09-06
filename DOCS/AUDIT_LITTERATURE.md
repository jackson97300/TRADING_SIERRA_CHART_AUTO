# Audit de litterature — ce que les desks et la recherche disent (06/09/2026)

Demande de Jackson : chercher les bonnes pratiques, verifier ce qui fonctionne
reellement, et approfondir l'interpretation des donnees options. Trois resultats,
dont un qui change la direction du projet.

---

## 1. Le resultat le plus important : une etude independante sur MNQ, meme verdict

**« Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A
Systematic Falsification Study »** — Mathias Mesfin, arXiv:2605.04004, mai 2026,
revise juillet 2026.

| | |
|---|---|
| instrument | **MNQ** — exactement le notre |
| periode | **947 jours** de trading, 2021-2025 |
| signaux testes | **14 familles** de momentum OHLCV |
| criteres | walk-forward hors echantillon, t >= 2,0, N >= 30 trades, rendement net positif apres **2 points de friction**, coherence inter-annuelle |
| **resultat** | **aucune strategie ne satisfait l'ensemble des criteres** |
| rendement brut maximal | **0,07 a 1,50 point par trade — sous le cout de friction** |
| meilleur cas isole | gap continuation short, t = 3,23, +14,52 pts, mais **22 trades** seulement |

**Ce que cela nous dit.** Notre cycle 1 (six hypotheses, zero survivante) et notre
cycle 2 (zero) ne sont pas un echec de methode : ils reproduisent, sur 40 jours,
ce qu'une etude independante trouve sur 947. Le mur n'est pas notre mesure, c'est
le cout — 1,50 point de rendement brut maximal contre 2 points de friction.

Convergence remarquable avec nos chiffres. Le papier modelise 2 points de friction
sur MNQ ; nous mesurons 2,82 $, soit ~1,4 point. Notre H3 en 15 min rend +0,018
ATR sur NQ, soit ~0,72 $ net — exactement l'ordre de grandeur du « brut maximal
sous la friction » du papier.

**Consequence directe : les signaux OHLCV intraday sont epuises.** Ce n'est plus
une hypothese a tester, c'est un resultat publie sur vingt-quatre fois plus de
donnees que les notres. Continuer a chercher la est le seul vrai moyen de tourner
en rond.

---

## 2. Ou la litterature dit qu'il reste quelque chose : l'order flow

L'Order Flow Imbalance montre un pouvoir predictif **statistiquement significatif
a horizon court**, avec un coefficient d'information moyen de **+0,0044** et
**+0,0022 hors echantillon**. C'est faible en valeur absolue — mais c'est positif,
et surtout **superieur a l'OHLCV seul** : decomposer les flux d'ordres augmente
significativement le R² ajuste par rapport a l'analyse standard.

Sur les futures E-mini S&P precisement, l'impact prix et l'impact flux sont tous
deux significatifs a l'horizon d'une seconde, avec une variation intrajournaliere
marquee liee a la liquidite et aux spreads. La predictibilite decroit vite —
quelques minutes au plus.

**Ce que nous avons et que le papier MNQ n'avait pas** : `delta_bar`, `cvd_day`,
`ask_pct` / `bid_pct`, les clusters de gros ordres lus dans le VAP, le footprint,
`finish_delta_pct`, les divergences de delta. Ce sont des donnees de flux, pas de
l'OHLCV.

**Et nous ne les avons quasiment pas testees.** Sur les six hypotheses du cycle 1,
une seule reposait vraiment sur le flux — H8 — et elle est morte sur une
conjonction impossible (`rvol >= 2` ET `|delta_pct| >= 0,30` ET finish contraire :
zero occurrence), pas sur une absence d'edge. **La piste est ouverte et non
exploree.**

---

## 3. Les donnees options : le HVL est un regime, pas un lieu

Le mecanisme fait consensus : en **gamma positif**, les dealers vendent la force
et achetent la faiblesse pour rester couverts — la volatilite se comprime, le
marche devient « collant » et revient a la moyenne. En **gamma negatif**, ils
vendent dans la baisse et achetent dans la hausse — les mouvements s'amplifient et
le retour a la moyenne se fait sortir sur stop.

Mise en garde de la litterature, qui vaut pour nous : **« gamma positif = haussier »
est faux**. Le regime decrit un COMPORTEMENT, pas une direction. Le GEX est un
contexte de structure de marche, pas un signal d'entree autonome.

**Reserve de methode** : aucune source academique avec magnitude chiffree n'est
ressortie sur l'effet gamma intraday. Ce qui existe est du blog et du vendeur de
donnees. Le mecanisme est plausible et largement decrit ; **son ampleur n'est pas
etablie**. A traiter comme une hypothese de regime, pas comme un fait.

### La correction de lecture, verifiee dans nos donnees

`mq_hvl` — le gamma flip — est le prix ou le gamma net des dealers croise zero :
la frontiere entre regime stabilisant et regime amplificateur. Nous l'avions
traite comme un LIEU (1,65 % des barres a portee, donc inutilisable). C'est un
**separateur de regime**, et `signe(dist_mq_hvl)` est une donnee **collectee**,
pas un proxy — contrairement a `mq_gamma_condition`, retire a juste titre.

Mesure du 06/09 sur les 57 jours :

| | ES | NQ |
|---|---|---|
| `dist_mq_hvl` renseigne | **99,7 %** | 96,3 % |
| prix au-dessus du HVL | 66,8 % | 57,6 % |
| bascules de regime, sans zone morte | 10,2 / jour | 8,2 / jour |
| **avec zone morte de 1,0 ATR-5m** | **1,8 / jour** | **1,5 / jour** |
| barres couvertes avec zone morte | 93 % | 90 % |

**Un regime qui change dix fois par jour n'est pas un regime.** Avec une zone
morte de 1,0 ATR-5m, il change une a deux fois par jour et couvre 90 % des barres.
C'est exploitable, et c'est une donnee collectee.

Deux reserves a inscrire si on l'utilise : le flip **migre en seance** (a
reverifier apres tout mouvement de plus de 1 %), et l'inclusion ou non des 0DTE
change les resultats — d'ou l'interet de comparer `mq_hvl` et `mq_hvl_0dte`.

---

## 4. La VWAP : pourquoi elle tient, et ce qui la tue

Ce n'est pas un indicateur, c'est un **benchmark d'execution**. Les desks sont
juges contre la VWAP de seance ; leurs ordres la poursuivent toute la journee.
C'est ce flux reel qui ramene le prix, pas une propriete technique.

Nos propres donnees le confirment sans qu'on l'ait cherche : dans la reduction,
`dist_vwap_d` resume **19 colonnes** et `dist_prev_vwap_rth_r` en resume **39** sur
NQ. La VWAP est deja le squelette du noyau.

Ce que la pratique dit et qui nous concerne :

- **Le filtre de tendance n'est pas optionnel.** Sauter les jours de tendance est
  ce qui garde la strategie en vie ; sans filtre, le taux de reussite tombe vers
  45 %, et les echecs des jours de tendance dominent.
- **Les commissions comptent** : 2 $ d'aller-retour sur ES pesent quand les gains
  moyens font 75 a 150 $. Sur micro, c'est pire d'un facteur trois — exactement
  notre mesure.
- Les chiffres de taux de retour qui circulent (« 63 % depuis 2 SD », « 75-80 % »)
  **ne sont sources nulle part**. A ne pas reprendre.

---

## Ce que cet audit change

**1. Arreter de chercher dans l'OHLCV.** C'est documente comme vide sur 947 jours
de MNQ. Nos deux cycles le confirment sur 40.

**2. La piste non exploree est l'order flow**, la ou la litterature mesure un
avantage reel sur l'OHLCV — et c'est precisement ce que nos donnees contiennent et
que le papier MNQ n'avait pas.

**3. Le regime gamma devient utilisable** — `signe(dist_mq_hvl)` avec zone morte
de 1,0 ATR, donnee collectee, 90 % de couverture. C'est le filtre balance/tendance
que la VWAP ne sait pas produire seule.

**4. Ce que cela ne change pas : le prior.** Simplifier et mieux cibler rend le
resultat plus lisible et plus robuste, **pas plus probable**. Le papier MNQ n'a
rien trouve sur 947 jours ; il n'y a aucune raison de croire que 40 jours en
donneront plus. Ce qui change, c'est l'endroit ou l'on cherche.

---

## Sources

- Mesfin, M. — *Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures:
  A Systematic Falsification Study*, arXiv:2605.04004 (mai 2026, rev. juillet 2026)
- *Returns and Order Flow Imbalances: Intraday Dynamics and Macroeconomic News
  Effects*, arXiv:2508.06788
- *Predictive Order Flow Imbalance: Cross-Asset Microstructure Alpha*, SSRN 7053198
- *Cross-impact of order flow imbalance in equity markets*, Quantitative Finance
- SpotGamma, MenthorQ, Mott Capital — documentation GEX (**sources non
  academiques, magnitude non etablie**)
