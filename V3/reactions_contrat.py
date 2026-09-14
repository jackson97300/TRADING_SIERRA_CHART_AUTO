"""Le CONTRAT du fichier `LOGS/reactions/reactions_<jour>.jsonl`.

Extrait de `reactions.py` le 15/09 : le fichier etait a 299 lignes sur 300, et
le contrat n'a pas fini de grandir. Meme geste que `lecture_colonnes.py` le
10/09 — quand un fichier touche le plafond, on sort la piece coherente, on ne
leve pas le plafond.

Ce module ne contient AUCUNE logique. Il porte ce que le fichier de sortie
promet a celui qui le lira au jour 61 — et ce qu'il lui INTERDIT.
"""

from __future__ import annotations

# Ecrit en tete de chaque fichier, dans la ligne `entete`. Il est la pour etre
# lu par quelqu'un qui aura oublie le contexte — moi dans six semaines compris.
AVERTISSEMENT = (
    "DESCRIPTION DE SESSION — MIA V3. Ce fichier dit ce que le marche a FAIT a "
    "des niveaux decides d'avance. Il ne dit JAMAIS ce qu'il aurait fallu "
    "faire. Aucun champ n'est un gain, un R, un tick de profit, un prix "
    "d'entree, de sortie ou un stop, et aucun n'en est deductible : il n'y a "
    "ici ni regle d'entree, ni regle de sortie, ni position. Toute phrase de la "
    "forme « on aurait du », « ca aurait fait », « ce niveau a marche » tiree "
    "de ces lignes est un contresens d'usage. "
    "LA GARDE DE CAUSALITE EST `ts_sur`, PAS `ts_connu`, et la confusion des "
    "deux a ete le defaut corrige le 15/09. `ts_connu` date l'EVENEMENT — la "
    "seconde cloture au-dela, la seconde revenue — et c'est ce qu'on raconte. "
    "Mais trois etiquettes sur quatre sont des verdicts sur la FENETRE "
    "ENTIERE : « tenu » veut dire « et rien n'a casse dans les huit barres "
    "suivantes », « casse » veut dire « et rien n'a regagne ensuite ». Un "
    "observateur place a `ts_connu` ne sait aucune de ces deux choses ; s'en "
    "servir la, c'est fabriquer du futur. Mesure : 26 ecarts entre rejeu et "
    "direct, 26 DANS LE MEME SENS, le rejeu voyant toujours la reaction plus "
    "forte, jusqu'a +1,22 ATR. "
    "`ts_sur` a `null` veut dire que la fenetre debordait la seance : cette "
    "ligne n'est JAMAIS devenue un fait, et se lit comme absente. "
    "LES FICHIERS ECRITS AVANT LE 15/09 PORTENT LE DEFAUT et doivent etre "
    "regeneres avant toute lecture. "
    "Lecture agregee au jour 61 seulement, jamais un episode isole. Le P&L "
    "reste ferme jusque-la.")
