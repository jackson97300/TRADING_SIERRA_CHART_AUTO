"""L0 famille A — QUALITE DES DONNEES : ce que je lis est-il vrai ?

C'est la PREMIERE question de L0, et elle etait absente du code jusqu'au 06/09.
Hors ligne on ne la voyait pas : `charger_jour` filtre les barres instables en
amont, donc tout ce qui arrive a la decision est deja propre. **En live, rien
ne garantit ca.** Le bot lit la derniere barre du fichier ; sans ces portes,
personne ne verifie qu'elle est saine, fraiche, complete, dans la bonne fenetre,
et que la surveillance L6 n'a pas leve d'alerte sur la journee.

C'est la moitie que le mode hors ligne ne peut pas montrer — et c'est celle qui
compte a 9h30.


POURQUOI CES PORTES RENDENT `None` HORS LIGNE
----------------------------------------------
L'age d'une barre et l'etat du connecteur n'existent pas dans un backtest. Une
porte qui repondrait `False` (« tout va bien ») sur une information absente
serait un feu vert invente — exactement le silent fallback qui a coute deux
regressions au chantier. Elle rend donc `None` : « je ne peux pas repondre ».

La chaine en fait ce qu'il faut selon le mode : en LIVE elle bloque
(fail-closed), hors ligne elle journalise le trou sans bloquer. Cf
`chaine.appliquer(strict=...)`.
"""

from __future__ import annotations

from V3.registre import porte


@porte("L0_DATA_INSTABLE", "L0")
def _instable(lec, etat, s):
    """`data_quality_flag` doit valoir `stable` — warmup et degraded exclus."""
    q = lec["qualite"]
    return None if q is None else q != s["attendu"]


@porte("L0_DATA_PERIMEE", "L0")
def _perimee(lec, etat, s):
    """Regle heritee : pas de trade sur une barre morte.

    Le bot a deja tourne sur des barres vieilles de plusieurs minutes sans
    s'en apercevoir — le fichier ne dit pas qu'il a cesse d'etre alimente, il
    dit juste ce qu'il contient.
    """
    a = lec["age_s"]
    return None if a is None else a > s["age_max_s"]


@porte("L0_DATA_INCOMPLETE", "L0")
def _incomplete(lec, etat, s):
    """Une barre agregee partielle fausse l'ATR, donc le SL et le TP."""
    c = lec["barre_complete"]
    return None if c is None else not c


@porte("L0_DATA_FENETRE_MELANGEE", "L0")
def _fenetre(lec, etat, s):
    """La journee melange-t-elle deux versions de fenetre glissante ?

    Les fenetres ont bascule w0 -> w1 le 06/09 a 21:00 UTC. Le danger n'est pas
    d'etre en `w0` : tout l'historique l'est. C'est de melanger les deux dans
    un meme calcul de session — « un lot qui melange les deux doit etre refuse,
    pas moyenne ».

    Une premiere version exigeait `w1` : elle fermait 100 % du lot historique,
    ce qui est vrai et parfaitement inutile. Une porte etrangleuse qui a
    raison reste une porte etrangleuse.
    """
    m = lec["fenetre_melangee"]
    return None if m is None else bool(m)


@porte("L0_DATA_L6_ALERTE", "L0")
def _l6(lec, etat, s):
    """Le verdict de la surveillance quotidienne. Une alerte bloque le jour."""
    a = lec["l6_alerte"]
    return None if a is None else bool(a)


@porte("L0_DATA_COLONNE_MORTE", "L0")
def _colonne_morte(lec, etat, s):
    """Une colonne figee ce jour-la ne doit pas alimenter une decision.

    1 080 couples (colonne, jour) sont recenses dans `stale.csv`, dont 63
    colonnes du noyau sur 18 jours. Le danger n'est pas la valeur manquante —
    on la verrait — c'est la valeur qui ne bouge plus et qu'on lit comme
    stable.
    """
    c = lec["colonnes_mortes"]
    return None if c is None else bool(c)
