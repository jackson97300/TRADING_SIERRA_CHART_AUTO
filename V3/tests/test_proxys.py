"""Le refus mécanique des proxys — point 7 de la nuit du 08/09.

    python -X utf8 V3/tests/test_proxys.py

Une colonne gouvernée par une `_source` auto-déclarée qui contient « proxy »
se lit None — un TROU, jamais une valeur. Le test vérifie les DEUX sens :
le proxy se refuse, ET une source saine ne refuse rien (sinon un test où tout
se refuse passerait sans rien prouver). Puis il vérifie le chemin RÉEL : sur
une vraie journée agrégée, `gamma_block_long` doit se lire None parce que
`_mq_gamma_source = sierra_proxy_v2` a survécu à l'agrégation — c'est là que
les portes lisent, et c'est là que le refus doit exister.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from V3 import lecture                                        # noqa: E402

JOUR, SYM = "20260903", "ES"     # la meme journee que test_faux_live


def _df(source):
    # un ts REEL sur la grille 15 min (09/09 13:30 UTC = 9h30 ET) : la
    # lecture leve sur une barre hors grille depuis la passe lecture (B3)
    d = {"ts": [1788960600000], "mq_gamma_condition": [2.0],
         "gamma_block_long": [1.0], "rvol_zscore": [0.5]}
    if source is not None:
        d["_mq_gamma_source"] = [source]
    return pd.DataFrame(d)


def main():
    echecs = []
    os.chdir(RACINE)

    # 1. proxy declare -> la colonne GOUVERNEE se refuse en val()
    df = _df("sierra_proxy_v2")
    if lecture.val(df, "mq_gamma_condition", 0) is not None:
        echecs.append("proxy declare : val() rend une valeur au lieu de None")

    # 2. source SAINE -> aucune refusee (sinon le test ne prouve rien)
    df = _df("sierra_direct_v1")
    if lecture.val(df, "mq_gamma_condition", 0) != 2.0:
        echecs.append("source saine : la colonne devrait se lire normalement")

    # 3. pas de champ _source du tout -> comportement historique inchange
    df = _df(None)
    if lecture.val(df, "mq_gamma_condition", 0) != 2.0:
        echecs.append("sans _source : la colonne devrait se lire normalement")

    # 4. les colonnes NON gouvernees ne se refusent jamais, meme proxy
    #    present — gamma_block_long EST le cas d'ecole depuis le 07/09 au
    #    soir : derive de dist_mq_call/put (A) + atr + bool_gex_flip_zone
    #    (DMP natif) par gamma_veto_engine, REPRODUIT 5 275 barres 0 ecart.
    #    La table du matin le condamnait par association de famille.
    df = _df("sierra_proxy_v2")
    if lecture.val(df, "gamma_block_long", 0) != 1.0:
        echecs.append("gamma_block_long refuse a tort — il est derive de "
                      "donnees collectees, pas du proxy")
    if lecture.lire(df, 0, SYM)["gamma_block_long"] is not True:
        echecs.append("lire() devrait rendre True pour gamma_block_long")
    if lecture.val(df, "rvol_zscore", 0) != 0.5:
        echecs.append("colonne non gouvernee refusee a tort")

    # 5. le chemin REEL, dans les DEUX sens : sur le 1 min (qui porte le
    #    label proxy), mq_gamma_condition se refuse ; sur l'agrege (ou les
    #    portes lisent), gamma_block_long se lit.
    reel, brut = charger_jour(SYM, JOUR, 15, avec_1min=True)
    if reel.empty:
        echecs.append("journee %s indisponible — le chemin reel n'est pas prouve"
                      % JOUR)
    else:
        if "_mq_gamma_source" not in reel.columns:
            echecs.append("_mq_gamma_source ne survit pas a l'agregation : le "
                          "refus est aveugle la ou les portes lisent")
        if ("mq_gamma_condition" in brut.columns
                and lecture.val(brut, "mq_gamma_condition", len(brut) // 2)
                is not None):
            echecs.append("journee reelle : mq_gamma_condition se lit encore "
                          "malgre sa source proxy")
        lus = [lecture.val(reel, "gamma_block_long", i)
               for i in range(len(reel))]
        if all(v is None for v in lus):
            echecs.append("journee reelle : gamma_block_long illisible partout"
                          " — le sur-blocage du matin est revenu")

    print("  proxys — 5 controles (refus, source saine, sans source, "
          "non gouvernee, chemin reel)")
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : ce qui vient d'un proxy se lit None — un trou, jamais un "
          "feu vert —\n       et rien d'autre n'est refuse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
