"""Ce que « une position par instrument » coute — lecture des trades fantomes.

    python -X utf8 V3/layers/L0_interrupteur/lire_fantomes.py [journal.jsonl]

Chaque signal ferme par `L0_POSITION_OUVERTE` a ete simule en entier : triple
barriere, couts deduits, un `fantome_pnl_atr` comme un trade reel. Ce script
repond aux trois questions que la porte pose, et a AUCUNE autre.

  1. LE COUT DE LA REGLE — somme des pnl fantomes. Nettement positive, le
     pyramidage devient une hypothese mesuree ; negative, la regle protege.
  2. LES CONTRAIRES COMME SORTIE — si les fantomes `meme_sens = false` sont
     profitables ET que la position finit en SL dans ces cas-la, un signal
     contraire est une regle de sortie. La meilleure facon d'en trouver une
     sans l'inventer.
  3. LES MEME SENS COMME RENFORT — tot et la position finit en TP, c'est un
     argument ; tard, pour rien.

**Rien ici ne change l'execution.** Une position par instrument reste appliquee
pendant toute la campagne : on mesure, on ne pyramide pas.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np


def charger(chemin):
    out = []
    if not os.path.exists(chemin):
        return out
    for ln in open(chemin, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if o.get("fantome") and o.get("fantome_pnl_atr") is not None:
            out.append(o)
    return out


def _bloc(titre, lignes, cle=None):
    v = [x["fantome_pnl_atr"] for x in lignes]
    if not v:
        print("  %-34s %s" % (titre, "aucun"))
        return
    a = np.array(v, dtype=float)
    # l'intervalle a 95 % : sans lui, une moyenne sur peu de trades se lit
    # comme un resultat alors qu'elle est dans le bruit
    ic = 1.96 * a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else float("nan")
    print("  %-34s n=%5d   moyenne %+.3f  +/- %.3f   somme %+8.1f"
          % (titre, len(a), a.mean(), ic, a.sum()))


def rapport(lignes, sym):
    lignes = [x for x in lignes if x["sym"] == sym]
    if not lignes:
        return
    print("\n%s — %d signaux refuses par POSITION_OUVERTE, tous simules" % (sym, len(lignes)))
    print("-" * 96)
    _bloc("1. COUT DE LA REGLE (tous)", lignes)

    contre = [x for x in lignes if not x.get("meme_sens")]
    meme = [x for x in lignes if x.get("meme_sens")]
    print()
    _bloc("2. contraires a la position", contre)
    for issue in ("SL", "TP", "EXPIRATION"):
        _bloc("     ... quand la position finit %s" % issue,
              [x for x in contre if x.get("issue_position_ouverte") == issue])
    print()
    _bloc("3. meme sens que la position", meme)
    for lo, hi, nom in ((0, 3, "arrive tot (<= 3 barres)"),
                        (4, 10, "arrive au milieu (4-10)"),
                        (11, 10**6, "arrive tard (> 10)")):
        _bloc("     ... %s" % nom,
              [x for x in meme
               if x.get("barres_depuis_entree") is not None
               and lo <= x["barres_depuis_entree"] <= hi])


def main():
    defaut = "LOGS/entonnoir/portes57_15min.jsonl"
    chemin = sys.argv[1] if len(sys.argv) > 1 else defaut
    lignes = charger(chemin)
    if not lignes:
        print("aucun trade fantome dans %s" % chemin)
        print("lancer d'abord : python -X utf8 V3/layers/L0_interrupteur/mesure_57j.py")
        return 1
    print("TRADES FANTOMES — ce que « une position par instrument » coute")
    print("source : %s" % chemin)
    for sym in ("ES", "NQ"):
        rapport(lignes, sym)
    print("\nLecture : une somme nettement positive en (1) dit que la regle coute.")
    print("Un (2) profitable AVEC des positions qui finissent SL dit qu'un signal")
    print("contraire est une SORTIE.")
    print()
    print("VINGT COMPARAISONS SONT AFFICHEES CI-DESSUS. A 5 %, UNE SORT PAR HASARD.")
    print("Un seul intervalle qui ne contient pas zero n'est donc PAS un resultat :")
    print("c'est exactement ce qu'on attend du bruit. Comparer au controle negatif")
    print("(ES -0,057 [-0,210 ; +0,096] ; NQ -0,000 [-0,134 ; +0,134]) avant de lire")
    print("quoi que ce soit. Ces lectures ne se tranchent pas avant 60 jours.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
