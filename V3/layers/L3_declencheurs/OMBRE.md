# LES SEIZE EN OMBRE — la liste que le miroir ne portait pas

*Pré-enregistrés le 06/09/2026 (document complet au dépôt privé,
`DOCS/OMBRE_ED16.md` : origine edge_discovery, table de conversion des
unités, dimensionnement sur 40 jours SANS lecture de P&L). Câblés le 07/09
— l'audit Fable a constaté qu'aucun coureur ne les exécutait : ils auraient
passé 60 jours à N = 0, un zéro de câblage lu comme de la rareté.*

Exécution : `ombre16.py` de ce dossier, appelé par le rejeu quotidien de
`campagne.py`. Signaux par franchissement, journal séparé
(`ombre16_<jour>.jsonl`), JAMAIS par la chaîne, aucun P&L.
**Grain : le frame 15 min du rejeu** — le dimensionnement du
pré-enregistrement était en barres 5 min (~14 signaux/jour) ; en 15 min les
N s'accumulent plus lentement (~7/jour mesuré le 04/09), la projection
« premiers lisibles mi-octobre » glisse d'autant. Écrit ici plutôt que
découvert au jour 40.
**Lecture : N = 40 sur NQ, PAR setup, jamais en groupe** — une lecture
combinée de seize produirait des gagnants par combinatoire.

Les seize, tenus en parité avec `LES_SEIZE` du code par `test_spec_l3.py` :

1. ED01_SELL_OPEN_ABOVE_PREV_VA
2. ED02_BUY_PREV_VA_RECLAIM
3. ED03_SELL_VPOC_FAR_ABOVE
4. ED04_BUY_VPOC_RECLAIM
5. ED05_SELL_GEX_REJECTION
6. ED06_BUY_GEX_SUPPORT
7. ED07_SELL_MQ_CALL_WALL
8. ED08_BUY_VWAP_RECLAIM_TREND
9. ED09_SELL_CVD_DIVERGENCE
10. ED10_BUY_CVD_DIVERGENCE
11. ED11_SELL_IB_BREAK_DOWN
12. ED12_BUY_IB_BREAK_UP
13. ED13_BUY_EXTREME_LOW_RANGE
14. ED14_SELL_EXTREME_HIGH_RANGE
15. ED15_SELL_VWAP_SD2_REJECTION
16. ED16_BUY_VWAP_SD2_SUPPORT

Ce qui N'y est PAS, et qui n'y est plus par défaut mais par décision écrite
(`NEXT_CYCLE.md` §4) : S-1 (momentum de fin de journée, JFE — premier
candidat du cycle 2) et S-4 (règle des 80 %, = H4 du cycle 1, en attente
d'effectif).
