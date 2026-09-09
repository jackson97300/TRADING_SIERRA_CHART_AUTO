# RAPPORT DE SESSION — 09/09/2026, la journée par le prisme des données et de V3

*Rythme du soir lancé à 22h41 (Jackson) = 20h41 UTC, après vérification de
complétude : **390 barres cash ES et NQ** (9h30→15h59 ET), 0 trou interne,
contrat **U26 des deux côtés** (veille du roll). Tout ce qui suit DÉCRIT ce que le
marché a fait et ce que V3 a vu. **Aucun devenir, aucun P&L** — les brackets sont
journalisés, leur issue est scellée jusqu'au jour 61 (METHODE §6). Le journal
MANUEL de Jackson n'est pas là-dedans : la machine ne l'écrit pas.*

---

## 1. La forme de la journée — une BALANCE, avec un flush au milieu

| | ES | NQ |
|---|---|---|
| open → close | 7660.75 → 7644.75 (**−16 pts, −0,21 %**) | 29455.25 → 29455.25 (**+0,00 — flat exact**) |
| high (heure) | 7665.00 à **11h00** | 29593.75 à **10h00** |
| low (heure) | 7628.75 à **11h15** | 29358.00 à **11h15** |
| range | 36.25 pts = **3,4 ATR-15m** (ATR médian 10.80) | 235.75 pts = **3,7 ATR** (ATR médian 64.17) |
| IB 9h30-10h30 | 7644.50 – 7663.75 (19.25 pts) | 29418.25 – 29593.75 (175.50 pts) |
| close vs IB | **DEDANS** (44 % du range) | **DEDANS** (41 % du range) |

**Le fait du jour : ES tombe de 36 pts entre le high de 11h00 et le low de 11h15**
— tout le range de la séance en un quart d'heure (3,4 ATR), puis retour dans l'IB.
NQ fait son low à la même minute. Après, plus rien : une balance jusqu'à la clôture.

## 2. Le récit F23 — ce que le marché a FAIT aux niveaux (deux pièges symétriques)

**ES.** Le VPOC courant (7656.75) est testé à l'ouverture et **cassé à 9h45** ;
**110 449 contrats** (delta +6 507) se retrouvent piégés AU-DESSUS ; le niveau est
**regagné à 11h15 — la minute du low**. Le flush de 11h00→11h15, c'est la
liquidation de ce piège. Puis la VAL (7647) est cassée à midi, **102 633 contrats**
piégés EN-DESSOUS, regagnée à 12h45. L'après-midi tient : VAL 7640 tenue à 14h,
VPOC 7650 tenu à 15h30.

**NQ, en miroir.** La VAL de la veille (29507.5) cassée à l'ouverture, 67 270
piégés au-dessus, regagnée à 11h15 (le low). Puis le VPOC (29535) cassé à 11h,
**79 569 piégés en-dessous**, regagné à 11h45. Clôture flat.

*Caveat : 5 écarts fiche/recomptage, TOUS sur des niveaux mobiles `cur_*` — le
faux négatif connu (dérive du niveau entre test et cassure, backlog). Zéro écart
sur les niveaux FIGÉS `prev_*` : la structure temporelle est sûre, les volumes de
piège des `cur_*` sont à lire à ±.*

## 3. Les réactions — les 17 niveaux, lus par classe (règle 20 : primaires d'abord, le témoin à part)

**Primaires.** L'**overnight a contenu la journée** : ES `ovn_high` tenu 4/4,
`ovn_low` tenu 3 (1 cassé, 1 regagné) ; NQ `ovn_high` 3/3, `ovn_low` 2/2. Le
**PDH n'a jamais été approché** (ES et NQ) — la journée est restée sous le high
de la veille. Le **PDL a été cassé** (ES 1, NQ 2 dont 1 regagné) : le flush de
11h15 est passé sous le low de la veille. `prev_val` ES tenue 3 / cassée 2 ;
NQ `prev_vah` tenue 3/3. `vwap_w` : ES jamais approché, NQ 5 tests mixtes.

**Secondaires.** Le **VPOC est le niveau le plus testé** (ES 5, NQ 7) avec
beaucoup de `regagne` — la signature d'une rotation autour de la valeur, pas
d'une tendance. `mq_hvl` NQ : 5 tests, cassé 2, regagné 1 — il a servi.
`ib_high` NQ et `mq_call` ES jamais approchés.

**Témoin `vwap_d`** : ES tenu 4 / cassé 2 / 1 indét., NQ tenu 3 / cassé 2 /
regagné 1. C'est la base de comparaison : un primaire qui ne fait pas mieux que
ça est une heure, pas un niveau. Aujourd'hui `ovn_high` (7/7 tenu) et `prev_vah`
NQ (3/3) se distinguent nettement du témoin ; le VPOC, lui, se comporte comme
le témoin — cohérent avec une balance.

## 4. Ce que la chaîne a VU — LES_QUATRE muettes, les SEIZE ont tracé la journée

**LES_QUATRE : 0 signal, ES et NQ** (H3-VPOC = H2p = H6p = H8p = 0). Entonnoir
vide, journal écrit : le jour a été couru. Rares par construction — le 61e jour
comptera ces silences.

**Les SEIZE (ED) : 8 signaux**, et ils tombent sur les tournants du jour :

| heure ET | sym | signal | sens | où dans la journée |
|---|---|---|---|---|
| 11h00 | ES | `ED10_BUY_CVD_DIVERGENCE` | +1 | à la clôture de la barre du flush |
| 11h15 | NQ | `ED10_BUY_CVD_DIVERGENCE` | +1 | **sur la barre du low** |
| 11h30 | ES | `ED11_SELL_IB_BREAK_DOWN` | −1 | l'IB low cède après le flush |
| 12h00 | ES | `ED10_BUY_CVD_DIVERGENCE` | +1 | pendant le 2e piège (VAL) |
| 12h00 | NQ | `ED11_SELL_IB_BREAK_DOWN` | −1 | idem |
| 12h15 | NQ | `ED10_BUY_CVD_DIVERGENCE` | +1 | au regain |
| 12h15 | NQ | `ED04_BUY_VPOC_RECLAIM` | +1 | **le regain du VPOC** |
| 14h45 | NQ | `ED03_SELL_VPOC_FAR_ABOVE` | −1 | fade de l'après-midi |

Lecture descriptive, pas de devenir : les divergences delta ont tiré aux
**deux extrêmes** (le flush, le regain), les cassures d'IB **après** le flush, le
reclaim **au** regain. La chaîne a vu les tournants. Ce qu'ils ont donné = jour 61.

**Les brackets B-ATR sont journalisés** (SL 1,0 ATR / TP 1,5 ATR, ATR de la
barre) : 8 sur 9. Le 9e — **NQ `C2_80PCT` à 10h00 — porte `atr_invalide`** : avant
11h00 la chaîne est aveugle (trou ATR), et l'ombre l'est aussi. C'est le trou
`atr_ref` (A_FAIRE) qui mord ici, sur un vrai signal.

## 5. Les C2 — un signal, trois lieux muets, et une MARGE qui compte

- **NQ `C2_80PCT` : 1 signal à 10h00** (+1, cible 29630.5), bracket sans ATR (cf ci-dessus).
- **`C2_EOD` : muet sur les deux**, mais pas de la même façon. **ES : rendement
  −0,2621 r pour un seuil de 0,273 — raté de 0,011**, 4 % du seuil, sur une
  dernière demi-heure à −9,5 pts. NQ : 0,016 (flat, loin). Le denominateur
  (`setup_jour`) dit : lieu présent, réaction absente, marge écrite. C'est la
  **puissance, pas l'edge** : le setup a presque tiré sur un jour de balance.
- `C2_DIV_DELTA` : `colonne_absente` (connu).

## 6. L6 — trois alertes, une qui parle à la journée

- **Volumétrie 90 %** (1240/1380) sur les deux — **cash complet** (390/390,
  0 trou). L'after-hours n'était pas fini à 20h41 UTC : attendu, pas un incident.
  *(Question : ce contrôle devrait-il compter le cash seul ?)*
- **NQ dérive : F15 `Divergences delta` ×44,05, F3 `Relation à la veille` ×0,27.**
  ES : 21 familles, aucune dérive. **Et F15 est LA famille de `ED10_BUY_CVD_
  DIVERGENCE`, qui a tiré 2× sur NQ aujourd'hui.** Les deux signaux de divergence
  NQ se lisent avec ce caveat : la feature qui les porte était hors de son échelle.
  F3 ×0,27 est cohérent avec une ouverture sous la VAL de la veille.
- Rollover : contrat inchangé U26 (attendu — le roll est demain).

## 7. La confrontation `triple_barriere` — vide aujourd'hui, par construction

0 signal des quatre → rien à confronter sur le 09/09. Le résultat de lot (22/70
EOD, 0 écart de prix) reste celui du 79 jours.

## 8. Ce que ce rapport NE dit PAS — et ce qui manque

Ni gain, ni R, ni « ça aurait marché ». Les 9 brackets attendent le jour 61.
Le **journal MANUEL** (le clic de Jackson) n'est pas ici — c'est la pièce que la
machine ne peut pas écrire, et demain elle aura un rollover à raconter.

## 9. Pour Fable — les quatre questions que la journée pose

1. **F15 ×44 sur NQ** le jour où `ED10` tire 2× sur NQ : la dérive est-elle dans la
   feature (collecte) ou dans le jour (un vrai régime de divergence) ? L6 ne
   tranche pas, il signale.
2. **`C2_EOD` ES à 0,011 du seuil** (p25 = 0,273) : une balance à −0,26 r en
   dernière demi-heure — le p25 coupe-t-il au bon endroit, ou au bord du bruit ?
3. **Le bracket `atr_invalide` du `C2_80PCT` à 10h00** : l'ombre hérite du trou ATR
   d'avant 11h. `atr_ref` (ATR-veille) le boucherait — avant ou après le gel ?
4. **Volumétrie L6 à 90 %** sur un cash complet : le contrôle compte l'after-hours
   qu'il ne peut pas encore avoir à 20h41. Cash-only, ou décaler l'attendu ?
