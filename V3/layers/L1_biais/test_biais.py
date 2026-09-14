"""L1 — quatre cas par composante, la série, et le test qui interdit le score.

    python -X utf8 V3/layers/L1_biais/test_biais.py

Le test le plus important n'est pas un cas : c'est **le grep anti-score**. La
première version de `biais.py` faisait `sum(b1, b5, b5b) >= seuil` avec, dans
sa docstring, « pas de pondération, chaque règle vaut 1 » — la règle citée sur
la ligne qui la violait. Un commentaire ne protège de rien ; un test si.
"""

from __future__ import annotations

import os
import re
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.layers.L1_biais import biais                             # noqa: E402
from V3.layers.L1_biais.composantes import COMPOSANTES           # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
S = {"B1p": {"z1_atr": 0.2}, "B1n": {"z1_atr": 0.2, "tendance_fort": 1.0},
     "B4": {}, "B5": {}, "B5b": {"barres_acceptation": 3}}

# une lecture nominale : au-dessus de la VWAP semaine, tout va bien
LEC = {"d_vwap_w": 1.5, "d_vwap_w_autre": 1.2, "smt_div": False,
       "issue_vwap_w": "tenu", "open_vs_va": 1, "barres_inside_prev_va": 0}

CAS = [
    # --- B1p : les quatre sorties ---------------------------------------
    ("B1p au-dessus -> long", "B1p", {}, 1),
    ("B1p en dessous -> short", "B1p", {"d_vwap_w": -1.5}, -1),
    ("B1p dans la zone morte -> pas d'avis", "B1p", {"d_vwap_w": 0.1}, 0),
    ("B1p donnee absente -> None, JAMAIS 0", "B1p", {"d_vwap_w": None}, None),
    # --- B1n : le narratif ----------------------------------------------
    ("B1n dernier test tenu -> meme cote", "B1n", {}, 1),
    ("B1n reference CASSEE sans regain -> plus d'avis", "B1n",
     {"issue_vwap_w": "casse"}, 0),
    ("B1n regagnee -> le cote revient", "B1n", {"issue_vwap_w": "regagne"}, 1),
    ("B1n sans historique -> None", "B1n", {"issue_vwap_w": None}, None),
    # --- B4 : veto pur ---------------------------------------------------
    ("B4 accord -> 1 (accord, PAS un cote)", "B4", {}, 1),
    ("B4 cotes opposes -> veto", "B4", {"d_vwap_w_autre": -1.2}, 0),
    ("B4 divergence SMT -> veto", "B4", {"smt_div": True}, 0),
    ("B4 autre instrument absent -> None", "B4", {"d_vwap_w_autre": None}, None),
    # --- B5 / B5b ---------------------------------------------------------
    ("B5 ouverture au-dessus de la VA veille", "B5", {}, 1),
    ("B5 en dessous", "B5", {"open_vs_va": -1}, -1),
    ("B5 dans la valeur", "B5", {"open_vs_va": 0}, 0),
    ("B5 absente -> None", "B5", {"open_vs_va": None}, None),
    ("B5b 3 barres dedans -> annule", "B5b", {"barres_inside_prev_va": 3}, 1),
    ("B5b 2 barres -> n'annule pas", "B5b", {"barres_inside_prev_va": 2}, 0),
]

# (nom, ce qui change, cote attendu, force attendue)
SERIE = [
    ("nominal : B1 long, accord, B5 confirme", {}, "LONG", "fort"),
    ("B4 divergent ANNULE le candidat", {"smt_div": True}, "AUCUN", None),
    # LE cas qui distingue une serie d'une somme : B5 contre le candidat ne
    # peut PAS produire un SHORT. Une somme le ferait.
    ("B5 contre -> LONG faible, JAMAIS short", {"open_vs_va": -1},
     "LONG", "faible"),
    ("B5b annule B5 -> la force ne bouge pas", {"open_vs_va": -1,
                                                "barres_inside_prev_va": 3},
     "LONG", "fort"),
    ("B1 dans la zone morte -> AUCUN, meme si tout le reste dit long",
     {"d_vwap_w": 0.1}, "AUCUN", None),
    ("B1 en trou -> AUCUN, jamais un cote par defaut",
     {"d_vwap_w": None}, "AUCUN", None),
    # LE CAS QUI MANQUAIT, ET QUI TIRE 100 % DU TEMPS EN REEL (ajoute le
    # 14/09). `open_vs_va` n'existe pas dans `lecture.lire` : B5 est en trou
    # sur les 1394 barres des deux instruments. La force par defaut disait
    # alors « fort » sur les 2168 avis du lot, sans qu'aucune mesure de force
    # n'ait eu lieu. Un cote peut survivre a un trou de B5 ; une FORCE, non.
    ("B5 en trou -> le cote tient, la force ne s'invente pas",
     {"open_vs_va": None}, "LONG", None),
]


def _anti_score():
    """Aucune addition ni multiplication entre sorties de composantes."""
    e = []
    for f in ("biais.py", "composantes.py"):
        src = open(os.path.join(ICI, f), encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        code = re.sub(r'""".*?"""', "", code, flags=re.S)
        for motif, quoi in ((r"\bsum\s*\(", "sum()"),
                            (r"\bscore\b", "une variable `score`"),
                            (r"b1\s*[+*]\s*b5", "b1 + b5")):
            if re.search(motif, code):
                e.append("%s contient %s — L1 est une SERIE, pas un score. "
                         "Deux presque-riens ne doivent pas faire un avis."
                         % (f, quoi))
    return e


def _seuils_null():
    """Un `null` en mode applique doit faire LEVER, pas passer."""
    import yaml
    cfg = yaml.safe_load(open(os.path.join(ICI, "seuils.yaml"),
                              encoding="utf-8"))
    cfg["composantes"]["B1p"]["mode"] = "appliquee"
    cfg["composantes"]["B1p"]["seuils"]["z1_atr"] = None
    tmp = os.path.join(ICI, "_seuils_test.yaml")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh)
    try:
        biais.charger_seuils(tmp)
        return ["charger_seuils accepte un seuil null en mode applique — "
                "le code deciderait avec un nombre qui n'existe pas"]
    except ValueError:
        return []
    finally:
        os.remove(tmp)


def _signe_change_le_verdict():
    """« Meme magnitude, signe oppose » DOIT changer le verdict.

    Ajoute apres la troisieme occurrence de la meme faute : un controle qui
    valide l'amplitude en oubliant la direction. La v1 de la mesure declarait
    ORIENTE une separation de -0,78, ou les signaux CONTRE le biais faisaient
    mieux que ceux qui le suivaient.

    Meme famille que `pas_de_feu_vert_invente` : deux lignes, et cette forme de
    bug ne repasse plus.
    """
    from V3.layers.L1_biais import mesure_57j as M
    base = {"n_avec": 100, "n_contre": 100, "ic": 0.2,
            "hasard_p5": -0.1, "hasard_p50": 0.0, "hasard_p95": 0.1}
    plus = M.verdict(dict(base, separation=+0.78))
    moins = M.verdict(dict(base, separation=-0.78))
    if plus == moins:
        return ["verdict() rend le meme texte pour +0,78 et -0,78 : il valide "
                "la magnitude et oublie la direction"]
    if "ENVERS" not in moins:
        return ["verdict(-0,78) devrait dire ORIENTE A L'ENVERS, il dit : %s"
                % moins]
    return []


# CE QUE `lecture.lire` NE PRODUIT PAS AUJOURD'HUI.
# Une composante dont la cle n'existe pas rend `None` a chaque barre : elle est
# declaree, testee, et morte. Elles etaient CINQ le 14/09 au matin — B1n, B4,
# B5 et B5b n'avaient JAMAIS rien rendu d'autre que `None` sur les 1394 barres.
#
# DEUX ONT ETE REVEILLEES le 14/09 : `open_vs_va` et `barres_inside_prev_va`,
# donc B5 et B5b vivent. Le cliquet a fait exactement son travail — il a REFUSE
# le changement tant que cette liste n'etait pas mise a jour, avec le message
# « retirer la de TROUS_CONNUS et mesurer la composante qu'elle reveille ».
#
# Cette liste est une DETTE DECLAREE, pas une permission. Le controle echoue
# dans les deux sens : si une nouvelle cle disparait du lecteur, et aussi si
# l'une des trois restantes est enfin produite sans mise a jour.
TROUS_CONNUS = {"d_vwap_w_autre", "issue_vwap_w", "smt_div"}


def _le_lecteur_produit_ce_que_L1_consomme():
    """LA QUESTION QU'AUCUN TEST NE POSAIT — et qui a coute la couche entiere.

    `LEC`, plus haut, est ecrit a la main avec les six cles presentes. Il
    prouve que les composantes fonctionnent SI on leur donne une lecture
    complete. Il ne dit rien de la lecture reelle. Resultat : `d_vwap_w`
    n'existait pas dans `lecture.lire`, B1p rendait un trou sur 208 barres sur
    208, L1 disait AUCUN sur 156 barres sur 156 — et ce fichier passait au
    vert. C'est la meme famille que les deux faux temoins du 12/09 : un
    controle qui ne peut pas echouer sur ce qu'il garde.

    On confronte donc la source des composantes a la source du lecteur.
    """
    import ast

    def _cles_lues(chemin):
        arbre = ast.parse(open(chemin, encoding="utf-8").read())
        return {n.args[0].value for n in ast.walk(arbre)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "lec" and n.args
                and isinstance(n.args[0], ast.Constant)}

    def _cles_produites(chemin):
        arbre = ast.parse(open(chemin, encoding="utf-8").read())
        for n in ast.walk(arbre):
            if isinstance(n, ast.FunctionDef) and n.name == "lire":
                return {c.value for d in ast.walk(n)
                        if isinstance(d, ast.Dict) for c in d.keys
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        return set()

    consommees = _cles_lues(os.path.join(ICI, "composantes.py"))
    produites = _cles_produites(os.path.join(RACINE, "V3", "lecture.py"))
    if not consommees or not produites:
        return ["le meta-controle n'a rien lu (%d consommees, %d produites) :"
                " il ne garde plus rien" % (len(consommees), len(produites))]
    manquantes = consommees - produites
    if manquantes == TROUS_CONNUS:
        return []
    e = []
    for k in sorted(manquantes - TROUS_CONNUS):
        e.append("`%s` est consommee par une composante L1 et n'est produite "
                 "par AUCUNE ligne de lecture.lire : la composante rendra "
                 "None a chaque barre" % k)
    for k in sorted(TROUS_CONNUS - manquantes):
        e.append("`%s` est enfin produite par lecture.lire : retirer la de "
                 "TROUS_CONNUS et mesurer la composante qu'elle reveille" % k)
    return e


def _seuil_b5b_coherent():
    """`N_ACCEPTATION` du lecteur == `B5b.barres_acceptation` du YAML.

    Le lecteur doit compter les N premieres barres SANS dependre de la config
    d'une couche — d'ou une constante chez lui. Mais une copie non gardee derive
    en silence : si le YAML passe a 4 et pas le lecteur, B5b jugerait sur trois
    barres en croyant en juger quatre, et rien ne le dirait. Meme geste que les
    constantes DTC du pont d'execution.
    """
    from V3 import lecture
    attendu = (biais.charger_seuils().get("B5b") or {}).get("barres_acceptation")
    if attendu is None:
        return ["seuils.yaml : B5b.barres_acceptation absent — le lecteur compte"
                " sur un nombre que la config ne declare plus"]
    if lecture.N_ACCEPTATION != attendu:
        return ["lecture.N_ACCEPTATION = %r mais seuils.yaml dit %r — B5b"
                " jugerait sur un nombre de barres different de celui declare"
                % (lecture.N_ACCEPTATION, attendu)]
    return []


def main():
    echecs = []
    for nom, comp, mod, attendu in CAS:
        obtenu = COMPOSANTES[comp](dict(LEC, **mod), S[comp])
        if obtenu != attendu or (obtenu is None) != (attendu is None):
            echecs.append("%s : attendu %r, obtenu %r" % (nom, attendu, obtenu))

    cfg = dict(S, b1_actif="B1p")
    for nom, mod, cote, force in SERIE:
        r = biais.evaluer(dict(LEC, **mod), cfg)
        if r["cote"] != cote or r["force"] != force:
            echecs.append("%s : attendu %s/%s, obtenu %s/%s"
                          % (nom, cote, force, r["cote"], r["force"]))

    echecs += (_anti_score() + _seuils_null()
               + _signe_change_le_verdict() + _seuil_b5b_coherent()
               + _le_lecteur_produit_ce_que_L1_consomme())

    # la relation portee par chaque signal L3
    if biais.relation({"cote": "LONG"}, 1) != "avec":
        echecs.append("relation : LONG + signal long devrait etre `avec`")
    if biais.relation({"cote": "AUCUN"}, 1) != "sans":
        echecs.append("relation : AUCUN devrait etre `sans`, pas `contre`")

    print("  L1 — %d cas de composante, %d cas de serie, %d composantes"
          % (len(CAS), len(SERIE), len(COMPOSANTES)))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : aucune composante n'invente d'avis sur une donnee absente,")
    print("       un signe oppose change le verdict,")
    print("       B5 contre le candidat rend FAIBLE et jamais l'autre cote,")
    print("       et il n'y a pas une seule addition entre composantes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
