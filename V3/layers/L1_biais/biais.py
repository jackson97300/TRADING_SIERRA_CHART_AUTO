"""L1 — la série : quel côté est favorisé, avec quelle force, ou aucun.

**PAS DE SCORE.** Un ordre, et chaque composante n'a qu'un droit :

    1. B1 (photo ou narratif)  donne le CANDIDAT.   AUCUN -> fin.
    2. B4                      peut ANNULER.        Jamais inverser.
    3. B5, sauf si B5b annule  peut QUALIFIER.      Jamais inverser, jamais annuler.

Aucune composante ne peut créer un côté que B1 n'a pas donné.


POURQUOI PAS UNE SOMME — et pourquoi j'en avais écrit une
-----------------------------------------------------------
La première version de ce fichier faisait `sum(b1, b5, b5b) >= seuil`, avec
dans la docstring : « pas de pondération, chaque règle vaut 1 ». Je citais la
règle sur la ligne même qui la violait.

Le danger n'est pas la pondération, c'est **l'addition**. Une somme non
pondérée reste une somme : deux composantes à +1 franchissent un seuil de 2, et
deux presque-riens font un avis. C'est exactement le mécanisme du contexte à
0,12 de janvier — avec des poids de 1 au lieu de poids réglés sur les jours de
test. Le résultat est le même : un côté qui apparaît sans qu'aucune composante
ne l'ait affirmé.

Dans une série, B5 ne peut pas fabriquer un LONG. Elle peut seulement dire que
le LONG de B1 est fort ou faible. C'est structurellement différent, pas
cosmétiquement.


CE QUE L1 NE FAIT PAS
---------------------
Elle **ne bloque rien** pendant la campagne d'ombre : `biais.py` n'a aucun
accès à `chaine.appliquer`, par construction. « Bloquer contre-biais » est une
hypothèse que les fantômes mesurent, pas une règle qu'on applique.
"""

from __future__ import annotations

import os

from V3.layers.L1_biais.composantes import COMPOSANTES

SEUILS_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "seuils.yaml")

AUCUN = {"cote": "AUCUN", "force": None}


def evaluer(lec, cfg):
    """La série. Rend un dict journalisable, jamais un nombre.

    `cfg` porte `b1_actif` ("B1p" ou "B1n") et les seuils par composante. Les
    deux versions de B1 sont mesurées côte à côte ; une seule entre en chaîne,
    et c'est la séparation qui tranche.
    """
    sorties, trous = {}, []

    def lire(nom):
        v = COMPOSANTES[nom](lec, cfg.get(nom, {}))
        sorties[nom] = v
        if v is None:
            trous.append(nom)
        return v

    # --- 1. le candidat -----------------------------------------------------
    b1 = lire(cfg.get("b1_actif", "B1p"))
    if b1 is None or b1 == 0:
        return dict(AUCUN, composantes=sorties, trous=trous,
                    motif="B1_trou" if b1 is None else "B1_zone_morte")

    # --- 2. le veto ---------------------------------------------------------
    # B4 rend 1 pour « accord » et 0 pour « desaccord » — ce n'est PAS un cote.
    # Un trou sur B4 ne vaut pas un veto : ne pas savoir si les instruments
    # s'accordent n'est pas savoir qu'ils divergent.
    if lire("B4") == 0:
        return dict(AUCUN, composantes=sorties, trous=trous, motif="veto_B4")

    # --- 3. la qualification ------------------------------------------------
    b5, b5b = lire("B5"), lire("B5b")
    force = "fort"
    if b5b != 1 and b5 is not None and b5 != 0:
        force = "fort" if b5 == b1 else "faible"

    return {"cote": "LONG" if b1 > 0 else "SHORT", "force": force,
            "composantes": sorties, "trous": trous, "motif": ""}


def relation(biais_du_jour, side):
    """`avec`, `contre` ou `sans` — l'étiquette portée par chaque signal L3.

    C'est par elle que la séparation se mesure : E[devenir | avec] moins
    E[devenir | contre].
    """
    c = (biais_du_jour or {}).get("cote")
    if c not in ("LONG", "SHORT"):
        return "sans"
    return "avec" if (1 if c == "LONG" else -1) == side else "contre"


def charger_seuils(chemin=SEUILS_YAML):
    """Rend la config L1. **Refuse de tourner avec un `null` appliqué.**

    Un seuil `null` est un seuil que la mesure n'a pas encore produit. Le
    laisser passer en mode appliqué, c'est décider avec un nombre qui n'existe
    pas — et le code tournerait sans rien signaler.
    """
    import yaml
    with open(chemin, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    comp = cfg.get("composantes") or {}
    manquants = [
        "%s.%s" % (nom, cle)
        for nom, d in comp.items() if (d or {}).get("mode") == "appliquee"
        for cle, v in ((d or {}).get("seuils") or {}).items() if v is None
    ]
    if manquants:
        raise ValueError(
            "seuils null en mode applique : %s — la distribution n'a pas encore "
            "ete mesuree, la composante ne peut pas s'appliquer"
            % ", ".join(manquants))
    return cfg
