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


# Les issues de F23, triees par CE QU'ELLES AUTORISENT B1n a dire. Liste
# blanche : une etiquette absente des deux listes — `en_cours`, `None`, ou une
# valeur neuve — est un TROU, jamais un avis.
#
# `en_cours` est le piege, et il etait ouvert : il veut dire « la fenetre n'est
# pas close », et l'ancienne ecriture `0 if issue == "casse" else cote` le
# rangeait avec `tenu`. B1n affirmait donc un cote sur un avenir qu'il ne
# connaissait pas. Mesure du 15/09, 62 jours d'archive, trame de production :
# ES 5,5 % / NQ 3,8 % des barres portent `en_cours`, et le defaut se
# materialisait sur 0,4 % / 0,3 % — la zone morte de B1p absorbait le reste.
# Rare n'est pas nul, et c'est le meme silent fallback qu'en tete de fichier.
#
# `indetermine` est l'INVERSE d'un trou : la fenetre EST close et rien de
# decisif n'y est arrive. On a regarde, on n'a pas d'avis -> 0.
PORTENT_LE_COTE = ("tenu", "regagne")
SANS_AVIS = ("casse", "indetermine")


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
    if issue in PORTENT_LE_COTE:
        return cote
    if issue in SANS_AVIS:
        return 0
    return None


@composante("B4")
def b4_intermarket(lec, s):
    """Accord ES/NQ — VETO PUR. Elle ne peut qu'annuler, jamais orienter.

    Rend 0 si les deux instruments sont de côtés opposés de leur VWAP semaine.
    Sinon +1, qui veut dire « accord », pas « long ».

    Le signe de sortie n'est PAS un côté : cette composante ne participe à
    aucune décision d'orientation. C'est pour ça que la série l'utilise comme
    interrupteur et non comme terme.

    LE SMT A ETE RETIRE LE 15/09, et retiré plutôt que corrigé. L'écriture
    précédente était `0 if (...) or lec.get("smt_div") else 1` : un `smt_div` à
    `None` est **faux** en Python, donc un trou se transformait en « accord ».
    Le retrait supprime le défaut PAR CONSTRUCTION au lieu de le garder et de
    le garder correct. Trois mesures convergentes, 77 jours d'archive :

    - `im_smt_divergence` tire sur 5,70 % des barres ES et 22,32 % des NQ,
      **ratio 3,9×** — son seuil est ±10 ticks pour deux instruments dont
      l'amplitude diffère d'un facteur 4. C'est la faute que `INCIDENT_LOG`
      condamne déjà : un rayon en ticks n'est pas calibrable cross-instrument.
    - c'est la seule des DIX colonnes cross-instrument disponibles qui soit
      quasi muette ; et aucune des dix ne survit à l'agrégation 15 min.
    - quatre invalidations indépendantes en production : 0 fold positif sur 12,
      IC bootstrap traversant zéro, droppée du dataset v4, déjà remplacée.

    Le retrait est INERTE aujourd'hui : `smt_div` n'est produit par aucune
    lecture, donc l'expression valait déjà sa seule jambe VWAP. Ce qui change
    est qu'on ne peut plus la rebrancher par accident.
    """
    a, b = lec.get("d_vwap_w"), lec.get("d_vwap_w_autre")
    if a is None or b is None:
        return None
    return 0 if (a > 0) != (b > 0) else 1


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
