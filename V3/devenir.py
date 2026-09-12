"""LE VERROU DU DEVENIR — on ne PEUT pas lire avant le jour 61.

    python -X utf8 V3/devenir.py            # dit ou on en est, sans rien ouvrir

POURQUOI CE FICHIER EXISTE. Jusqu'au 11/09, « on ne regarde pas le devenir
avant le jour 61 » etait une REGLE, ecrite dans `LECTURE_JOUR_61.md`, respectee
par discipline. L'audit du 11/09 au soir a montre que le journal des barrieres
porte desormais `pnl_atr` et `issue` SUR DISQUE : le devenir du premier signal
gele y est deja. Rien, techniquement, n'empechait de l'ouvrir.

Une porte fermee et une porte verrouillee ne se valent pas. Une regle se
contourne un dimanche a 23h, dans un moment de doute, exactement quand elle
compte le plus. Ce fichier transforme « je ne regarde pas » en « je ne PEUX pas
regarder » : tout acces a un champ de devenir passe par `lire_devenir`, qui
LEVE tant que la campagne n'est pas finie.

CE QUE LE VERROU NE FAIT PAS. Il n'empeche pas d'ouvrir un JSONL a la main —
rien ne le peut. Il empeche qu'un rapport, un tableau de bord ou un script
d'analyse le fasse sans qu'on l'ait voulu, et il rend le contournement VISIBLE :
il faut ecrire `force=True` et le justifier, ce qui laisse une trace dans le
code plutot que dans une memoire.

LE COMPTE DES JOURS. Le jour 1 est le 08/09/2026. Un jour de campagne est un
jour ou la campagne a COURU — on les compte sur les journaux presents, jamais
sur le calendrier : un ferie ou un jour muet ne consomme pas un jour de
campagne, et supposer le contraire ouvrirait le dossier trop tot.
"""

from __future__ import annotations

import glob
import os
import re
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

JOUR_1 = "20260908"
N_JOURS = 61
# Les champs qui portent un devenir. Tout acces a l'un d'eux passe par ici.
CHAMPS_DEVENIR = ("pnl_atr", "issue", "motif_issue", "rendement_r", "rend_pts",
                  "devenir_atr", "devenir", "gain", "pnl")


class DevenirFerme(Exception):
    """Levee quand on tente de lire un devenir avant la fin de la campagne."""


# UN jour de campagne = une journee dont LA MESURE OFFICIELLE existe, et rien
# d'autre. Cette mesure est `LOGS/entonnoir/entonnoir_<jour>.jsonl`, ecrit par
# `campagne.courir` : present et vide = jour couru MUET, ABSENT = jour NON
# couru. `campagne` efface d'ailleurs ses trois journaux s'il echoue, par
# conception, precisement pour qu'un incident ne passe pas pour un jour muet.
#
# DEUX ERREURS CORRIGEES, dans cet ordre :
#   1. adosse au seul journal du narrateur, le compteur annoncait 3 jours au
#      lieu de 4 — le narrateur n'existait pas au jour 1 ;
#   2. adosse a l'UNION de quatre journaux, il comptait le 11/09 alors que le
#      rejeu officiel de ce jour-la avait PLANTE (verrou de fichier) et s'etait
#      efface. Compter un jour que la mesure ne couvre pas, c'est ouvrir le
#      dossier trop tot — la faute exactement inverse de la premiere.
# La bonne source n'est ni un producteur commode ni une union : c'est celle qui
# DEFINIT la mesure.
JOURNAUX = (("entonnoir", "entonnoir"),)


def jours_courus():
    """Les jours de campagne REELLEMENT courus, lus sur les journaux presents.

    On compte ce qui existe, jamais ce que le calendrier promet : un jour
    ferie, un week-end ou un jour muet ne consomme pas un jour de campagne.
    Compter sur le calendrier ouvrirait le dossier avant l'heure.
    """
    jours = set()
    for dossier, prefixe in JOURNAUX:
        motif = os.path.join(RACINE, "LOGS", dossier, "%s_2026*.jsonl" % prefixe)
        for f in glob.glob(motif):
            base = os.path.basename(f)
            if "_avant_" in base:                     # une sauvegarde n'est pas un jour
                continue
            m = re.search(r"(\d{8})", base)
            if m and m.group(1) >= JOUR_1:
                jours.add(m.group(1))
    return sorted(jours)


def jour_campagne():
    """Le numero du dernier jour couru : 1 le 08/09, 61 au terme."""
    return len(jours_courus())


def ouvert():
    """Le dossier est-il ouvert ? Faux tant que les 61 jours ne sont pas courus."""
    return jour_campagne() >= N_JOURS


def etat():
    """Ce qu'on a le droit de savoir aujourd'hui : un COMPTE, jamais un resultat."""
    n = jour_campagne()
    return {"jour_1": JOUR_1, "jours_courus": n, "n_jours": N_JOURS,
            "reste": max(0, N_JOURS - n), "ouvert": n >= N_JOURS}


def lire_devenir(lignes, force=False, motif=None):
    """Rend les champs de devenir des `lignes` — ou LEVE si le dossier est ferme.

    `force=True` est le seul contournement, et il exige un `motif` : le
    contournement devient une ligne de code qu'on relit, pas un souvenir.
    Il n'existe que pour le jour 61 lui-meme et pour les tests.
    """
    if not ouvert() and not force:
        e = etat()
        raise DevenirFerme(
            "DOSSIER FERME — jour %d sur %d, il reste %d jour(s). Le devenir ne "
            "se lit qu'au terme (LECTURE_JOUR_61). Aucun P&L, aucune issue, "
            "aucun taux avant. Si tu crois avoir une raison, elle doit s'ecrire "
            "dans le code : lire_devenir(..., force=True, motif=\"...\")."
            % (e["jours_courus"], e["n_jours"], e["reste"]))
    if force and not motif:
        raise ValueError("force=True exige un motif ecrit — un contournement se justifie")
    return [{c: l.get(c) for c in CHAMPS_DEVENIR if c in l} for l in lignes]


def sans_devenir(ligne):
    """La ligne PRIVEE de ses champs de devenir — a utiliser partout ou un
    rapport, une page ou un journal de lecture manipule une ligne avant le
    jour 61. Ce qui n'est pas dans la structure ne peut pas fuiter a l'ecran."""
    return {k: v for k, v in ligne.items() if k not in CHAMPS_DEVENIR}


def main():
    e = etat()
    print("\n  CAMPAGNE — jour %d sur %d (jour 1 : %s)" % (e["jours_courus"], e["n_jours"], e["jour_1"]))
    print("  dossier : %s" % ("OUVERT" if e["ouvert"] else "FERME, il reste %d jour(s)" % e["reste"]))
    print("  jours courus : %s" % ", ".join(jours_courus()))
    try:
        lire_devenir([{"pnl_atr": 1.0}])
        print("  ATTENTION : le verrou n'a PAS leve — le dossier serait ouvert.")
    except DevenirFerme as ex:
        print("\n  le verrou repond :\n    %s" % str(ex)[:120])
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
