"""LE BIAIS DU JOUR — quatre mesures, quatre emplacements FIXES. Jamais un taux.

    python -X utf8 V3/mon_module/biais.py [jour]

POURQUOI CE FICHIER A ETE REECRIT LE 11/09, LE JOUR MEME OU JE L'AI ECRIT.
La premiere version rendait une force en fraction, `alignees / connues`. Une
composante absente sortait du denominateur. Consequence mesuree sur les 166
lignes de journal existantes : `flux` n'y etait sur AUCUNE, donc deux capteurs
sur quatre etaient morts, et la page annoncait **« BIAIS HAUSSIER, 2 sur 2 »**
— une unanimite, sur la moitie des preuves manquantes. Sur le 10/09, les 26
barres de la seance, les deux instruments : « BAISSIER 2 sur 2 », immobile.

La regle qui en sort, et qui tient tout ce fichier :

    UNE PANNE DE CAPTEUR NE DOIT JAMAIS AUGMENTER LA FORCE AFFICHEE.

Avec un denominateur variable, elle l'augmentait. Mesure sur le 10/09 une fois
le flux branche : « 3 sur 3 » sortait 5 fois — toujours le matin, quand la
pente de la VWAP n'existe pas — et « 3 sur 4 » sortait 9 fois l'apres-midi,
quand les quatre mesures vivent. L'affichage disait exactement le contraire de
la realite. C'est la meme machine que le « Confiance 72 % » du tableau de bord
v1, en typographie sobre.

CE QUI REMPLACE. Quatre compteurs absolus dont la somme vaut TOUJOURS quatre :
`hausse`, `baisse`, `plates`, `absentes`. Aucune fraction, jamais. Et le mot
directionnel est INTERDIT des qu'une mesure manque : on rend `INCOMPLET`, avec
le motif de chaque absence. Une somme nulle sur quatre mesures connues rend
`PARTAGE` — deux contre deux est l'etat le plus informatif d'une seance, et la
premiere version le rendait « 0 sur 4 », c'est-a-dire rien (mesure : 13 barres
d'affilee sur NQ le 10/09).

CE QUE CE N'EST TOUJOURS PAS. Une prevision, une probabilite, un ordre. Le
devenir est ferme jusqu'au jour 61 : aucun taux de reussite n'est calculable,
donc aucun n'est affiche. « Le biais penche a la hausse » veut dire « ces
mesures, maintenant, penchent de ce cote » — pas « ca va monter ».

L'AGE COMPTE AUTANT QUE LE SIGNE. Deux des quatre mesures ne bougent pas de la
journee (mesure 10/09 : `ouverture` et `hvl`, zero changement de signe sur les
deux instruments). Les afficher sans leur age fait passer un constat de 9h30
pour une lecture du present. `chronologie()` rend, pour chaque composante, le
nombre de barres depuis son dernier changement de signe.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

N_COMPOSANTES = 4
FIGEE_BARRES = 8          # au-dela, la composante est annoncee comme figee


def _ouverture(ligne):
    """Ou la seance a OUVERT par rapport a la valeur de la veille. Figee a la
    barre 0 par construction : c'est un fait du matin, pas une lecture du
    present, et l'affichage doit le dire."""
    p = ligne.get("position_ouverture")
    if p == "au_dessus":
        return 1, p, "ouverture au-dessus de la valeur de la veille"
    if p == "sous":
        return -1, p, "ouverture sous la valeur de la veille"
    if p == "dans":
        return 0, p, "ouverture dans la valeur de la veille"
    return None, p, "ouverture inconnue"


def _pente_vwap(ligne):
    """Pente de la VWAP, en unites d'ATR de barre. ABSENTE de 9h30 a 11h00 :
    `atr_barre` n'existe pas avant, par construction (mesure : 6 barres sur 26,
    les deux instruments). Le motif est rendu, jamais un zero a la place."""
    if "flux" not in ligne:
        return None, None, "pente de la VWAP : le journal ne porte pas le flux"
    v = (ligne.get("flux") or {}).get("vwap_slope_r")
    if v is None:
        return None, None, "pente de la VWAP non mesuree (ATR de barre absent avant 11h00)"
    if v == 0:
        return 0, v, "VWAP plate (0,000)"
    return (1 if v > 0 else -1), v, "VWAP %s (%+.3f ATR)" % ("montante" if v > 0 else "descendante", v)


def _cvd(ligne):
    """`cvd_sess_r` cumule DEPUIS 17h ET, pas depuis l'ouverture cash — la nuit
    est dedans. Le nom le dit ici en toutes lettres : l'appeler « CVD de
    session » ferait lire « depuis l'ouverture », et ce serait faux. Le CVD
    borne a 9h30 (`cvd_rth_r`) n'est pas injecte dans le frame aujourd'hui."""
    if "flux" not in ligne:
        return None, None, "CVD : le journal ne porte pas le flux"
    v = (ligne.get("flux") or {}).get("cvd_sess_r")
    if v is None:
        return None, None, "CVD depuis 17h ET non mesure"
    if v == 0:
        return 0, v, "CVD depuis 17h ET a plat"
    return (1 if v > 0 else -1), v, "CVD depuis 17h ET %+.0f (%s)" % (v, "acheteur" if v > 0 else "vendeur")


def _hvl(ligne):
    """`cote_hvl` porte depuis le 11/09 TROIS etats : None inconnu, 0 prix pile
    sur le HVL (un equilibre, donc `plate`), +/-1 au-dessus / en dessous."""
    c = ligne.get("cote_hvl")
    if c is None:
        return None, None, "HVL inconnu (niveau absent du frame)"
    if c == 0:
        return 0, 0, "prix exactement sur le HVL"
    return (1, c, "au-dessus du HVL") if c > 0 else (-1, c, "en dessous du HVL")


COMPOSANTES = (("ouverture", _ouverture), ("vwap", _pente_vwap),
               ("cvd", _cvd), ("hvl", _hvl))
ETAT = {1: "hausse", -1: "baisse", 0: "plate", None: "absente"}


def composer(ligne):
    """Rend un contrat a CARDINALITE FIXE :

        {sens, hausse, baisse, plates, absentes, composantes}

    `hausse + baisse + plates + absentes == N_COMPOSANTES`, toujours, quoi qu'il
    arrive. `composantes` a toujours quatre entrees. Aucune fraction n'est
    rendue : une fraction dont le denominateur bouge se lit comme un taux, et
    un taux se lit comme une frequence de reussite — dont il n'existe aucune
    mesure avant le jour 61.
    """
    detail = []
    for cle, f in COMPOSANTES:
        signe, brut, phrase = f(ligne)
        detail.append({"cle": cle, "signe": signe, "etat": ETAT[signe],
                       "valeur": brut, "phrase": phrase})
    compte = {e: sum(1 for d in detail if d["etat"] == e)
              for e in ("hausse", "baisse", "plate", "absente")}
    hausse, baisse = compte["hausse"], compte["baisse"]
    if compte["absente"]:
        sens = "INCOMPLET"          # le mot directionnel est interdit sur preuves manquantes
    elif hausse > baisse:
        sens = "HAUSSIER"
    elif baisse > hausse:
        sens = "BAISSIER"
    else:
        sens = "PARTAGE"            # deux contre deux, ou quatre plates : un etat, pas un vide
    return {"sens": sens, "hausse": hausse, "baisse": baisse,
            "plates": compte["plate"], "absentes": compte["absente"],
            "composantes": detail}


def signe_du_sens(b):
    """+1 / -1 quand le biais est directionnel, 0 sinon. Un seul endroit decide."""
    return {"HAUSSIER": 1, "BAISSIER": -1}.get((b or {}).get("sens"), 0)


def alignement(side, b):
    """QUATRE valeurs distinctes, jamais confondues :

      aligne / contre     le biais est directionnel et le sens du setup le suit ou non
      biais_partage       les mesures se partagent — ce n'est PAS « non mesure »
      biais_non_mesure    au moins une mesure manque : on ne peut rien dire
      non_applicable      le setup n'a pas de sens (ni long ni short)

    La premiere version rendait « neutre » pour les quatre. La colonne qui doit
    dire « ce short est CONTRE la pente du jour » etait alors muette la moitie
    d'une seance, avec le meme mot que « je ne sais pas ».
    """
    if side not in ("long", "short"):
        return "non_applicable"
    sens = (b or {}).get("sens")
    if sens == "INCOMPLET" or not b:
        return "biais_non_mesure"
    if sens == "PARTAGE":
        return "biais_partage"
    return "aligne" if (1 if side == "long" else -1) == signe_du_sens(b) else "contre"


def chronologie(lignes):
    """Pour une journee et UN instrument, l'age de chaque composante : le nombre
    de barres depuis son dernier changement de signe, et `figee` au-dela de
    FIGEE_BARRES. Mesure du 10/09 : `ouverture` et `hvl` ne changent jamais de
    la journee sur les deux instruments — les afficher sans age fait passer un
    constat de 9h30 pour une lecture du present."""
    suivi = {cle: {"dernier": None, "depuis": 0} for cle, _ in COMPOSANTES}
    for n, ligne in enumerate(lignes):
        for d in composer(ligne)["composantes"]:
            s = suivi[d["cle"]]
            if n and d["signe"] != s["dernier"]:
                s["depuis"] = 0
            else:
                s["depuis"] += 1
            s["dernier"] = d["signe"]
    return {cle: {"barres_depuis_changement": s["depuis"],
                  "figee": s["depuis"] >= FIGEE_BARRES} for cle, s in suivi.items()}


def phrase_courte(b):
    """Le titre, sans fraction et sans mot directionnel sur preuves manquantes."""
    if b["sens"] == "INCOMPLET":
        return "BIAIS INCOMPLET — %d mesure(s) sur %d manquante(s)" % (b["absentes"], N_COMPOSANTES)
    return "%s — %d en hausse, %d en baisse, %d plate(s)" % (b["sens"], b["hausse"], b["baisse"], b["plates"])


def main(argv):
    import time
    from V3.scenarios import boucle, scenarios
    jour = argv[1] if len(argv) > 1 else boucle.maintenant_et()[0]
    source = "direct"
    lignes = scenarios.lire(scenarios.chemin_direct(jour))
    if not lignes:
        source, lignes = "rejeu", scenarios.lire(scenarios.chemin_rejeu(jour))
    if not lignes:
        print("  aucune ligne pour %s" % jour)
        return 1
    print("\n  jour %s   source %s   (%s)" % (jour, source, time.strftime("%H:%M:%S")))
    for sym in sorted({l["sym"] for l in lignes}):
        a_lui = sorted((l for l in lignes if l["sym"] == sym), key=lambda x: x["i"])
        d, b = a_lui[-1], composer(a_lui[-1])
        ages = chronologie(a_lui)
        print("\n  %s %s   %s" % (sym, d.get("heure_et"), phrase_courte(b)))
        for c in b["composantes"]:
            age = ages[c["cle"]]
            marque = {"hausse": "+", "baisse": "-", "plate": "=", "absente": "?"}[c["etat"]]
            print("     %s %-58s %s" % (marque, c["phrase"],
                                        "figee depuis %d barres" % age["barres_depuis_changement"]
                                        if age["figee"] else ""))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
