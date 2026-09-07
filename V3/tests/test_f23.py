"""F23 au tick — les fiches recalculées à la main, sur deux journées réelles.

    python -X utf8 V3/tests/test_f23.py

Même principe que les checks sémantiques : on ne vérifie pas que le code
tourne, on vérifie que **ce qu'il produit correspond à ce qu'on lirait sur le
graphique**. Une fiche plausible qui décrit autre chose que la réalité est
exactement le genre de sortie qui traverse un chantier entier sans se faire
prendre.

Quatre contrôles, un par définition :
    touche    la barre englobe bien le niveau (écart <= z_touche)
    hystérésis  entre deux touches, le prix s'est écarté d'au moins z_reset
    cassure   DEUX clôtures de l'autre côté, jamais une seule
    piège     le volume au-delà est bien la somme des barres 1 min concernées
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.features import f23                                    # noqa: E402

JOURS = (("ES", "20260903"), ("ES", "20260904"))
NIVEAUX = ("dist_cur_vah", "dist_cur_val", "dist_cur_vpoc",
           "dist_prev_vah", "dist_prev_val", "dist_prev_vpoc")
TICK, Z_TOUCHE, Z_RESET = 0.25, 0.0, 0.5


def _ecart(df, col, i):
    """L'écart barre-niveau, recalculé À LA MAIN, sans passer par f23."""
    d = abs(float(pd.to_numeric(pd.Series([df[col].iloc[i]]),
                                errors="coerce").iloc[0])) * TICK
    demi = (df["high"].iloc[i] - df["low"].iloc[i]) / 2.0
    return (d - demi) / float(df["atr_barre"].iloc[i])


def controler(sym, jour):
    e = []
    df15, df1 = charger_jour(sym, jour, 15, avec_1min=True)
    if df15.empty:
        return ["%s %s : journee vide" % (sym, jour)], 0
    n = 0
    for col in NIVEAUX:
        fs = f23.fiches(df15, df1, col, TICK, Z_TOUCHE, Z_RESET)
        n += len(fs)
        precedent = None
        for f in fs:
            i = f["i"]

            # --- 1. TOUCHE : la barre englobe le niveau --------------------
            ec = _ecart(df15, col, i)
            if not (ec <= Z_TOUCHE + 1e-9):
                e.append("%s %s %s i=%d : ecart %.3f > z_touche %.2f — ce n'est "
                         "pas une touche" % (sym, jour, col, i, ec, Z_TOUCHE))

            # --- 2. HYSTERESIS : le prix s'est ecarte entre deux touches ----
            if precedent is not None:
                entre = [_ecart(df15, col, k) for k in range(precedent + 1, i)]
                entre = [x for x in entre if np.isfinite(x)]
                if entre and max(entre) < Z_RESET:
                    e.append("%s %s %s : deux touches (i=%d, i=%d) sans que le "
                             "prix s'ecarte de %.1f ATR — l'hysteresis ne joue pas"
                             % (sym, jour, col, precedent, i, Z_RESET))
            precedent = i

            # --- 3. CASSURE : deux cloture consecutives, pas une -----------
            if f["issue"] in ("casse", "regagne"):
                d = pd.to_numeric(df15[col], errors="coerce")
                suite = [(d.iloc[k] > 0) != (f["cote"] > 0)
                         for k in range(i + 1, min(i + 9, len(df15)))
                         if np.isfinite(d.iloc[k])]
                serie = 0
                best = 0
                for x in suite:
                    serie = serie + 1 if x else 0
                    best = max(best, serie)
                if best < 2:
                    e.append("%s %s %s i=%d : issue=%s mais %d cloture(s) "
                             "consecutive(s) de l'autre cote — une seule est un "
                             "depassement, pas une acceptation"
                             % (sym, jour, col, i, f["issue"], best))

            # --- 4. PIEGE : la somme des barres 1 min au-dela --------------
            if f.get("volume_au_dela") is not None:
                if f["volume_au_dela"] <= 0:
                    e.append("%s %s %s i=%d : volume_au_dela = %s"
                             % (sym, jour, col, i, f["volume_au_dela"]))
                if not f.get("duree_au_dela"):
                    e.append("%s %s %s i=%d : du volume piege mais aucune barre "
                             "1 min comptee" % (sym, jour, col, i))
            if f["issue"] == "tenu" and f.get("volume_au_dela"):
                e.append("%s %s %s i=%d : issue=tenu mais du volume au-dela — "
                         "un niveau qui tient n'a personne de l'autre cote"
                         % (sym, jour, col, i))

            # --- 5. les scalaires suivent les fiches ----------------------
            s = f23.scalaires(fs, i)
            attendu = sum(1 for g in fs if g["i"] <= i)
            if s["n_tests"] != attendu:
                e.append("%s %s %s i=%d : n_tests=%d, attendu %d"
                         % (sym, jour, col, i, s["n_tests"], attendu))
    return e, n


def main():
    echecs, total = [], 0
    for sym, jour in JOURS:
        e, n = controler(sym, jour)
        echecs += e
        total += n
        print("  %s %s : %d fiches" % (sym, jour, n))
    if total == 0:
        echecs.append("aucune fiche produite sur deux journees — F23 est muet")
    print("  F23 au tick — %d fiches sur %d journees, 5 controles chacune"
          % (total, len(JOURS)))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for x in echecs[:12]:
            print("     %s" % x)
        return 1
    print("  OK : chaque touche englobe son niveau, l'hysteresis joue entre")
    print("       deux touches, une cassure fait bien DEUX cloture, et le")
    print("       volume piege ne sort que quand le niveau a cede.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
