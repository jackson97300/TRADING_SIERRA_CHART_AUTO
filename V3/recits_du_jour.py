"""LES RECITS DU JOUR — un fichier par journee, rangés, relisibles.

    python -X utf8 V3/recits_du_jour.py                  toutes les journees
    python -X utf8 V3/recits_du_jour.py --jour 20260904  une seule
    python -X utf8 V3/recits_du_jour.py --depuis 20260901

Ecrit `LOGS/recits/recit_<jour>.md` — un document par journee, ES puis NQ.
`LOGS/` est hors depot et hors miroir : ces fichiers ne partent nulle part.

CE MODULE NE RACONTE RIEN LUI-MEME. Il appelle `recit.raconter` et capture ce
qu'elle imprime. Ecrire une seconde narration serait garantir que les deux
divergent — c'est exactement ce qui est arrive entre `recit.py` et
`reactions.py` avant que le REGISTRE de niveaux devienne une source unique.

CE QUE CES FICHIERS SONT, ET CE QU'ILS NE SONT PAS
--------------------------------------------------
Ils decrivent ce que le MARCHE a fait a des niveaux decides d'avance. Ils ne
disent jamais ce que NOUS aurions du faire : aucun gain, aucun R, aucun prix
d'entree ni de sortie, et rien qui permette de les deduire. Une memoire du
marche est licite avant le jour 61 ; une memoire de nos resultats ne l'est pas.

UN RECIT AVEC UN ECART N'EST PAS PUBLIABLE. `recit.raconter` recompte chaque
volume depuis les barres 1 min et rend le nombre de desaccords. Quand il y en
a, le fichier est ecrit QUAND MEME — on ne cache pas une journee — mais il
porte un bandeau en tete et le lanceur le compte a part.

ATTENTION AUX FICHIERS D'AVANT LE 15/09 : la garde de causalite de F23 etait
`ts_connu`, trop precoce pour trois etiquettes sur quatre. Tout recit genere
avant cette date doit etre regenere. C'est la raison d'etre du mode « toutes
les journees » : un lot de recits se REFAIT, il ne se rattrape pas.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from contextlib import redirect_stdout

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.campagne import jours_disponibles                        # noqa: E402
from V3.recit import raconter                                    # noqa: E402

DOSSIER = os.path.join("LOGS", "recits")

BANDEAU = (
    "> **Description de seance — MIA V3.** Ce document dit ce que le marche a\n"
    "> FAIT a des niveaux decides d'avance. Il ne dit JAMAIS ce qu'il aurait\n"
    "> fallu faire : aucun gain, aucun R, aucun prix d'entree, de sortie ou de\n"
    "> stop, et aucun n'en est deductible. Toute phrase de la forme « on aurait\n"
    "> du » ou « ce niveau a marche » tiree d'ici est un contresens d'usage.\n"
    "> Chaque volume a ete recompte depuis les barres 1 min.\n")

ALERTE_ECART = (
    "> **CE RECIT N'EST PAS PUBLIABLE — %d ECART(S) fiche/recomptage.**\n"
    "> Un volume annonce par la fiche F23 ne correspond pas au recomptage\n"
    "> independant sur les barres 1 min. Le fichier est conserve pour que\n"
    "> l'ecart soit examinable, pas pour etre lu comme un fait.\n")


def _un_jour(jour, syms):
    """Rend (texte markdown, nombre d'ecarts). Capture `recit.raconter`."""
    tampon = io.StringIO()
    ecarts = 0
    with redirect_stdout(tampon):
        for sym in syms:
            ecarts += raconter(sym, jour)
            print()
    corps = tampon.getvalue().rstrip()
    if not corps:
        return None, 0
    tete = ["# Recit du %s-%s-%s" % (jour[:4], jour[4:6], jour[6:]), ""]
    if ecarts:
        tete += [ALERTE_ECART % ecarts, ""]
    tete += [BANDEAU, "", "```", corps, "```", ""]
    return "\n".join(tete), ecarts


def _ecrire(chemin, texte):
    """Ecriture ATOMIQUE et idempotente : jamais d'append, jamais de fichier
    a moitie ecrit si le processus meurt au milieu."""
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(texte)
    os.replace(tmp, chemin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jour", default=None, help="une seule journee")
    ap.add_argument("--depuis", default=None, help="borne basse incluse")
    ap.add_argument("--jusqu-a", dest="jusqu_a", default=None)
    ap.add_argument("--sym", default=None, help="ES ou NQ ; defaut : les deux")
    a = ap.parse_args()
    os.chdir(RACINE)
    os.makedirs(DOSSIER, exist_ok=True)

    syms = [a.sym] if a.sym else ["ES", "NQ"]
    if a.jour:
        jours = [a.jour]
    else:
        jours = sorted(set(jours_disponibles("ES")) | set(jours_disponibles("NQ")))
        if a.depuis:
            jours = [j for j in jours if j >= a.depuis]
        if a.jusqu_a:
            jours = [j for j in jours if j <= a.jusqu_a]

    ecrits, vides, avec_ecart = 0, [], []
    print("  %d journee(s) a raconter -> %s/" % (len(jours), DOSSIER))
    for jour in jours:
        try:
            texte, ecarts = _un_jour(jour, syms)
        except Exception as exc:                        # noqa: BLE001
            # On ne laisse PAS une journee casser le lot, mais on ne la
            # passe pas sous silence non plus : elle est nommee a la fin.
            vides.append("%s (%s: %s)" % (jour, type(exc).__name__, exc))
            continue
        if texte is None:
            vides.append("%s (aucune barre)" % jour)
            continue
        _ecrire(os.path.join(DOSSIER, "recit_%s.md" % jour), texte)
        ecrits += 1
        if ecarts:
            avec_ecart.append("%s (%d)" % (jour, ecarts))

    print("\n  %d recit(s) ecrit(s)" % ecrits)
    if avec_ecart:
        print("  %d AVEC ECART fiche/recomptage — non publiables : %s"
              % (len(avec_ecart), ", ".join(avec_ecart)))
    if vides:
        print("  %d journee(s) sans recit : %s"
              % (len(vides), ", ".join(vides[:8])))
    return 1 if avec_ecart else 0


if __name__ == "__main__":
    sys.exit(main())
