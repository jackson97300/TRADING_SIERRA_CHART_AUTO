"""CAUSALITE — le rejeu doit rendre exactement ce que le direct aurait lu.

    python -X utf8 V3/tests/test_causalite.py

Le contrat, et il n'admet aucune nuance :

    lire(df[:i+1], i)  ==  lire(df, i)     pour tout i

A gauche, la journee TRONQUEE a la barre `i` — ce qu'un observateur place la
possede reellement. A droite, la journee ENTIERE — ce que le rejeu possede.
Toute difference est une information venue du futur, quel que soit le nom
qu'on lui donne.

POURQUOI CE FICHIER EXISTE
--------------------------
Le 15/09, une fuite a ete trouvee dans F23 : la garde de `scalaires` etait
`i_connu`, la fenetre de `reaction_atr` allait a `i+4`, et rien ne liait les
deux. 26 ecarts entre rejeu et direct, **26 dans le meme sens** — le rejeu
voyait toujours la reaction plus forte, jusqu'a +1,22 ATR. Le controle qui
aurait du l'attraper n'evaluait qu'a la barre du test ; la fuite commencait une
barre plus tard. Un controle qui regarde au mauvais endroit est un controle qui
rassure.

Une campagne d'ombre n'a qu'un seul produit : la preuve que ce qu'elle a
journalise, un bot live l'aurait fait. Cette preuve ne vaut rien si le rejeu
sait des choses que le live ignore.

LA TRAME FORGEE, ET POURQUOI ELLE N'EST PAS UNE COMMODITE
----------------------------------------------------------
`_fenetre_melangee` lisait `nunique()` sur la journee entiere : a la barre 5,
elle savait ce que faisait la barre 20. Mesure du 15/09 sur les 132
jours-instruments du lot : `window_version` vaut `w0` sur 122 et `w1` sur 10,
et **aucun jour ne melange les deux**. Le defaut etait donc invisible sur
donnees reelles — il ne se declenche que le jour ou la porte servirait.

Un test qui n'aurait que des journees reelles serait vert AVANT et APRES le
correctif : il ne prouverait rien. C'est exactement le piege trouve le 14/09
dans mes propres tests de B5 (« la fixture avait des niveaux constants, donc
elle ne pouvait pas prouver la lecture de la barre 0 »). D'ou la trame forgee.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                       # noqa: E402
from V3 import lecture                                           # noqa: E402

JOURS = (("ES", "20260903"), ("ES", "20260904"), ("NQ", "20260904"))


def _comparer(df, sym, etiquette):
    """Rend la liste des ecarts entre direct et rejeu, barre par barre."""
    e = []
    for i in range(len(df)):
        direct = lecture.lire(df.iloc[:i + 1].copy(), i, sym=sym)
        rejeu = lecture.lire(df, i, sym=sym)
        for cle in sorted(set(direct) | set(rejeu)):
            a, b = direct.get(cle), rejeu.get(cle)
            if repr(a) != repr(b):
                e.append("%s barre %d : %s direct=%r rejeu=%r"
                         % (etiquette, i, cle, a, b))
    return e


def _trame_melangee(df):
    """La MEME journee, mais dont la seconde moitie change de version.

    C'est la seule forme sous laquelle `_fenetre_melangee` peut mentir : tant
    que la colonne est constante, tronquer ou non ne change rien et le defaut
    dort. On force donc le cas que le lot ne contient pas.
    """
    if "window_version" not in df.columns or len(df) < 4:
        return None
    d = df.copy()
    milieu = len(d) // 2
    d.loc[d.index[:milieu], "window_version"] = "w0"
    d.loc[d.index[milieu:], "window_version"] = "w1"
    return d


def main():
    echecs, barres, n_cles = [], 0, 0

    # --- 1. les journees reelles -------------------------------------------
    for sym, jour in JOURS:
        df = charger_jour(sym, jour, 15)
        if df.empty:
            echecs.append("%s %s : journee vide" % (sym, jour))
            continue
        barres += len(df)
        n_cles = max(n_cles, len(lecture.lire(df, 0, sym=sym)))
        echecs += _comparer(df, sym, "%s %s" % (sym, jour))
        print("  %s %s : %d barres" % (sym, jour, len(df)))

    # --- 2. LA TRAME FORGEE : deux versions de fenetre dans la journee ------
    # Sans elle, ce fichier serait vert meme avec le defaut en place.
    forgees = 0
    for sym, jour in JOURS:
        df = charger_jour(sym, jour, 15)
        if df.empty:
            continue
        d = _trame_melangee(df)
        if d is None:
            echecs.append("%s %s : window_version absente — la trame forgee "
                          "ne peut pas etre construite, le controle est BORGNE"
                          % (sym, jour))
            continue
        forgees += 1
        barres += len(d)
        echecs += _comparer(d, sym, "%s %s FORGEE" % (sym, jour))
    print("  trames forgees (window_version melangee) : %d" % forgees)

    if barres == 0:
        echecs.append("aucune barre comparee — le controle n'a rien lu")
    if forgees == 0:
        echecs.append("aucune trame forgee — le controle ne peut pas echouer")

    print("  CAUSALITE — %d barres, %d cles par barre, direct contre rejeu"
          % (barres, n_cles))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for x in echecs[:12]:
            print("     %s" % x)
        return 1
    print("  OK : sur chaque barre, ce que la lecture rend avec la journee")
    print("       tronquee est IDENTIQUE a ce qu'elle rend avec la journee")
    print("       entiere — y compris sur une trame qui melange deux versions")
    print("       de fenetre, le seul cas ou le defaut du 15/09 se voyait.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
