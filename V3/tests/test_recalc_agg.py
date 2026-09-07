"""`rvol_r` et `cvd_sess_r` dans l'agrégation — le dernier prérequis de L4 J2.

    python -X utf8 V3/tests/test_recalc_agg.py

ATTENDU, écrit avant la mesure : sur une journée réelle, le frame agrégé que
la campagne nourrit à la chaîne porte les deux colonnes recalculées que la
SPEC L4 exige, et `cvd_sess_r` se REPROUVE depuis le 1 min — à chaque barre
agrégée, sa valeur égale le cumul du `delta_bar` 1 min de la session
(17h ET → 17h ET) jusqu'à la fin de la fenêtre, mismatch = 0. Jamais la
colonne livrée `cvd_day`, qui repart de zéro au redémarrage du processus.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min             # noqa: E402

JOUR, SYM = "20260903", "NQ"


def main():
    os.chdir(RACINE)
    df, brut = charger_jour(SYM, JOUR, 15, avec_1min=True)
    if df.empty:
        print("  journee %s indisponible — test impossible" % JOUR)
        return 1
    complet = pd.concat(chauffe_1min(SYM, JOUR) + [brut[COLS_RECALC]],
                        ignore_index=True)
    agg = injecter_recalculs(complet, df, minutes=15)

    echecs = []

    # 1. les deux colonnes existent et sont renseignees
    for c in ("rvol_r", "cvd_sess_r"):
        if c not in agg.columns:
            echecs.append("%s ABSENTE de l'agregation" % c)
        elif agg[c].notna().sum() == 0:
            echecs.append("%s presente mais entierement NaN" % c)

    # 2. cvd_sess_r se reprouve depuis le 1 min : cumul du delta de la
    #    session jusqu'a la fin de chaque fenetre agregee
    if "cvd_sess_r" in agg.columns:
        b = brut.copy()
        b["dt"] = pd.to_datetime(b["ts"], unit="ms", utc=True)
        attendu = recalc.cumul_delta(b, recalc.session_sess(b["dt"]))
        fin_fenetre = {}
        for i in range(len(b)):
            # label left : la fenetre de la barre agregee `t` couvre
            # [t ; t + 15 min) — la barre 1 min appartient a sa fenetre
            fen = (b["ts"].iloc[i] // (15 * 60_000)) * (15 * 60_000)
            fin_fenetre[fen] = float(attendu.iloc[i])
        n_ecarts = 0
        for _, ligne in agg.iterrows():
            att = fin_fenetre.get(int(ligne["ts"]))
            lu = ligne["cvd_sess_r"]
            if att is None or pd.isna(lu):
                continue
            if abs(float(lu) - att) > 1e-6:
                n_ecarts += 1
        if n_ecarts:
            echecs.append("cvd_sess_r : %d fenetre(s) ne reproduisent pas le "
                          "cumul 1 min de la session" % n_ecarts)

    print("  recalc dans l'agregation — rvol_r + cvd_sess_r, journee %s %s"
          % (JOUR, SYM))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : les deux colonnes recalculees que la SPEC L4 exige sont "
          "dans\n       l'agregation, et cvd_sess_r se reprouve depuis le "
          "1 min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
