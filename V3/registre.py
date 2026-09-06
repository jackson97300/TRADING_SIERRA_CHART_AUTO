"""Le registre des portes — une porte n'existe que si elle est declaree ici.

Chaque couche declare ses portes avec `@porte("NOM", "L0")`. Le registre est
partage : la chaine les evalue toutes, sans savoir d'ou elles viennent.

POURQUOI UN REGISTRE, ET PAS UN DICTIONNAIRE ECRIT A LA MAIN
--------------------------------------------------------------
Une porte ecrite dans le code sans sa ligne de seuils est une porte que
personne ne relit et que personne ne mesure. Le registre rend le controle
possible dans les DEUX SENS : `test_portes.py` echoue si une porte du code
n'a pas de seuils, ET si des seuils declarent une porte que le code n'a pas.

C'est la seule protection contre la derive silencieuse : V1 embarquait
27 modules dont personne ne savait ce que chacun filtrait.
"""

from __future__ import annotations

REGISTRE: dict = {}          # nom -> {"fn", "couche"}


def porte(nom: str, couche: str):
    """Declare une porte. `fn(lecture, etat, seuils) -> bool` : True = bloque."""
    if couche not in ("L0", "L5"):
        raise ValueError("couche inconnue : %r" % couche)

    def enrober(fn):
        if nom in REGISTRE:
            raise ValueError("porte declaree deux fois : %s" % nom)
        REGISTRE[nom] = {"fn": fn, "couche": couche}
        return fn
    return enrober


def evaluer_toutes(lecture, etat, seuils, absentes=()):
    """Rend {nom: True si la porte bloquerait, None si la porte est ABSENTE}.

    TOUTES les portes sont evaluees sur CHAQUE signal, independamment.
    Corrige le 06/09 (Q7) : l'evaluation en serie attribuait chaque rejet a la
    PREMIERE porte qui fermait, et les suivantes ne voyaient jamais ce signal.
    `max_trades` evaluee avant `news` « volait » les rejets de news — et le
    -4,82 ATR de news etait alors mesure sur ce que `max_trades` avait laisse
    passer. Le remede n'est pas de trouver le bon ordre : IL N'Y EN A PAS.

    Effet mesure de la correction : `SESSION_BLOQUEE` passe de 8 rejets a 39,
    `VETO_RVOL_EXTREME` de 1 a 30.

    Une porte ABSENTE — donnee non collectee, seuil non mesure — rend `None`,
    jamais `False`. Un manque qui se lit comme un feu vert est un manque qu'on
    oublie.

    UNE PORTE PEUT AUSSI RENDRE `None` D'ELLE-MEME : « je ne peux pas
    repondre ». C'est le cas des portes de qualite des donnees quand la donnee
    dont elles ont besoin est elle-meme absente — l'age d'une barre hors ligne,
    l'etat du connecteur en backtest. Ce n'est ni un blocage ni un feu vert :
    c'est un TROU, et il se journalise comme tel. Ce que la chaine en fait
    depend du mode, cf `chaine.appliquer(strict=...)` : bloquant en live,
    trace-mais-neutre hors ligne.
    """
    out = {}
    for nom, p in REGISTRE.items():
        if nom in absentes:
            out[nom] = None
            continue
        r = p["fn"](lecture, etat, seuils.get(nom, {}))
        out[nom] = None if r is None else bool(r)
    return out
