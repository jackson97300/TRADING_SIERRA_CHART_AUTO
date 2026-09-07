"""L1 — les composantes du biais. Trois lignes chacune, `None` possible.

Chaque composante : `(lec, s) -> +1 | -1 | 0 | None`. Aucun nombre dans le
code, tout vient de `seuils.yaml`.

**`None` n'est pas `0`.** Zéro veut dire « je regarde et je n'ai pas d'avis » ;
`None` veut dire « je ne peux pas regarder ». Les confondre invente un avis
neutre là où il y a un trou — le même silent fallback qui a fait rendre `False`
à `L0_VIX_REGIME` pendant qu'elle ne lisait rien.

B1p et B1n sont mesurées CÔTE À CÔTE sur les mêmes jours. Une seule des deux
entre en chaîne, et c'est la séparation qui tranche — pas l'élégance de
l'histoire que raconte le narratif.
"""

from __future__ import annotations

COMPOSANTES: dict = {}


def composante(nom: str):
    """Déclare une composante. Même registre que les portes de L0 : une
    composante qui n'est pas déclarée n'existe pas, et le test le vérifie."""
    def enrober(fn):
        if nom in COMPOSANTES:
            raise ValueError("composante declaree deux fois : %s" % nom)
        COMPOSANTES[nom] = fn
        return fn
    return enrober


@composante("B1p")
def b1_photo(lec, s):
    """VWAP semaine — la PHOTO : où le prix est maintenant.

    Zone morte `z1_atr` : sans elle, le côté bascule dès que le prix effleure
    la référence. C'est ce qui faisait changer le régime gamma dix fois par
    jour avant qu'on lui en donne une.
    """
    d = lec.get("d_vwap_w")
    if d is None or s.get("z1_atr") is None:
        return None
    return 1 if d > s["z1_atr"] else (-1 if d < -s["z1_atr"] else 0)


@composante("B1n")
def b1_narratif(lec, s):
    """VWAP semaine — le NARRATIF : ce que le prix a FAIT de sa référence.

    Même côté que la photo **si le dernier test a tenu**. Zéro si la référence
    a été cassée sans regain : une VWAP cassée n'oriente plus, elle est
    devenue un obstacle de l'autre côté.

    C'est l'hypothèse à mesurer, pas à croire : un desk lit « au-dessus,
    testée trois fois, elle a tenu, les défenses s'affermissent ». Reste à
    savoir si cette histoire sépare mieux que la photo.
    """
    cote = b1_photo(lec, s)
    if cote is None or cote == 0:
        return cote
    issue = lec.get("issue_vwap_w")
    if issue is None:
        return None
    return 0 if issue == "casse" else cote


@composante("B4")
def b4_intermarket(lec, s):
    """Accord ES/NQ — VETO PUR. Elle ne peut qu'annuler, jamais orienter.

    Rend 0 si les deux instruments sont de côtés opposés de leur VWAP semaine,
    ou si le SMT diverge. Sinon +1, qui veut dire « accord », pas « long ».

    Le signe de sortie n'est PAS un côté : cette composante ne participe à
    aucune décision d'orientation. C'est pour ça que la série l'utilise comme
    interrupteur et non comme terme.
    """
    a, b = lec.get("d_vwap_w"), lec.get("d_vwap_w_autre")
    if a is None or b is None:
        return None
    return 0 if (a > 0) != (b > 0) or lec.get("smt_div") else 1


@composante("B5")
def b5_ouverture(lec, s):
    """Ouverture contre la valeur de la veille — QUALIFIE, n'oriente pas.

    Lue une fois, à 10h30 ET : avant, la valeur du jour n'est pas formée et la
    comparer à celle de la veille n'a pas de sens.
    """
    v = lec.get("open_vs_va")
    return None if v is None else int(v)


@composante("B5b")
def b5b_acceptation(lec, s):
    """Acceptation de la valeur veille — ANNULE B5, ne dit rien d'autre.

    Si le prix est resté dans la VA de la veille sur les premières barres,
    l'ouverture hors valeur n'a pas été acceptée : B5 ne qualifie plus rien.
    Rend 1 (annule) ou 0 (n'annule pas), jamais un côté.
    """
    n = lec.get("barres_inside_prev_va")
    if n is None or s.get("barres_acceptation") is None:
        return None
    return 1 if n >= s["barres_acceptation"] else 0
