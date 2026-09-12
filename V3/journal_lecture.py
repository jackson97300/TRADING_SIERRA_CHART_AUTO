"""LIRE UN JOURNAL DE CAMPAGNE — les deux lecteurs qui doivent resister au temps.

Sortis de `campagne.py` le 12/09 : le fichier passait 300 lignes, et la regle du
chantier est de DECOUPER. La frontiere est nette — `campagne` FAIT courir la
journee, ce fichier sait LIRE ce qui en sort, meme quand la convention a change
ou que le fichier est momentanement verrouille.

Les deux fonctions sont nees d'un defaut reel, chacune le sien, et leurs
docstrings les racontent : une convention de nom qui a derive en quatre jours,
et une course entre la synchro et le rejeu qui a coute une journee de campagne.
"""

from __future__ import annotations

import os
import time


# Le nom du declencheur a porte TROIS noms en quatre jours de campagne :
# `setup` et `famille` du 08 au 10/09, `hypothese` a partir du 11/09. Un lecteur
# du jour 61 qui ne chercherait que `hypothese` compterait ZERO sur les trois
# premiers jours — et il ne planterait PAS, il rendrait un zero credible. C'est
# le defaut le plus dangereux d'une campagne de soixante jours : il est
# silencieux. Tout lecteur de journal passe par ici.
NOMS_DECLENCHEUR = ("hypothese", "setup", "famille")


def declencheur(ligne):
    """Le nom du declencheur d'une ligne de journal, quelle que soit la
    convention du jour ou elle a ete ecrite. None si aucune ne s'applique."""
    for champ in NOMS_DECLENCHEUR:
        v = ligne.get(champ)
        if v:
            return v
    return None


ESSAIS_LECTURE, ATTENTE_S = 6, 5.0


def ouvrir_patient(chemin, essais=ESSAIS_LECTURE, attente=ATTENTE_S):
    """Lit un fichier de donnees en ATTENDANT qu'il se libere.

    NE DE L'INCIDENT DU 11/09 AU SOIR. Le rejeu officiel a plante sur
    `PermissionError: [Errno 13] ... 20260911_NQ_sierra_enriched.jsonl` — la
    synchro depuis le VPS ecrivait le fichier a l'instant ou le rejeu voulait
    le lire. Consequence : `courir` a EFFACE ses trois journaux, par
    conception, pour que le jour compte comme NON COURU plutot que comme muet.
    Une course de quelques secondes a donc coute UNE JOURNEE DE CAMPAGNE sur
    soixante-et-une, et rien n'empechait qu'elle se reproduise chaque soir.

    Le verrou de fichier est TRANSITOIRE : la synchro finit d'ecrire. Attendre
    est la bonne reponse, planter ne l'est pas. Au-dela des essais, on releve
    l'erreur — un verrou qui dure une demi-minute n'est plus une course, c'est
    un probleme qu'il faut voir.
    """

    for n in range(essais):
        try:
            with open(chemin, encoding="utf-8", errors="ignore") as f:
                return f.readlines()
        except PermissionError:
            if n == essais - 1:
                raise
            print("  fichier verrouille (synchro en cours ?), nouvel essai dans %.0f s : %s"
                  % (attente, os.path.basename(chemin)), flush=True)
            time.sleep(attente)
    return []
