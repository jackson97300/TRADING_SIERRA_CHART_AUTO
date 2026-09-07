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
    d = {"ts": [1000], "gamma_block_long": [1.0], "rvol_zscore": [0.5]}
    if source is not None:
        d["_mq_gamma_source"] = [source]
    return pd.DataFrame(d)


def main():
    echecs = []
    os.chdir(RACINE)

    # 1. proxy declare -> refus, en val() ET dans la lecture complete
    df = _df("sierra_proxy_v2")
    if lecture.val(df, "gamma_block_long", 0) is not None:
        echecs.append("proxy declare : val() rend une valeur au lieu de None")
    if lecture.lire(df, 0, SYM)["gamma_block_long"] is not None:
        echecs.append("proxy declare : lire() rend %r au lieu de None (trou)"
                      % lecture.lire(df, 0, SYM)["gamma_block_long"])

    # 2. source SAINE -> aucune refusee (sinon le test ne prouve rien)
    df = _df("sierra_direct_v1")
    if lecture.val(df, "gamma_block_long", 0) != 1.0:
        echecs.append("source saine : la colonne devrait se lire normalement")
    if lecture.lire(df, 0, SYM)["gamma_block_long"] is not True:
        echecs.append("source saine : lire() devrait rendre True")

    # 3. pas de champ _source du tout -> comportement historique inchange
    df = _df(None)
    if lecture.val(df, "gamma_block_long", 0) != 1.0:
        echecs.append("sans _source : la colonne devrait se lire normalement")

    # 4. une colonne NON gouvernee ne se refuse jamais, meme proxy present
    df = _df("sierra_proxy_v2")
    if lecture.val(df, "rvol_zscore", 0) != 0.5:
        echecs.append("colonne non gouvernee refusee a tort")

    # 5. le chemin REEL : journee agregee, la _source doit avoir survecu
    reel = charger_jour(SYM, JOUR, 15)
    if reel.empty:
        echecs.append("journee %s indisponible — le chemin reel n'est pas prouve"
                      % JOUR)
    else:
        if "_mq_gamma_source" not in reel.columns:
            echecs.append("_mq_gamma_source ne survit pas a l'agregation : le "
                          "refus est aveugle la ou les portes lisent")
        elif lecture.val(reel, "gamma_block_long", len(reel) // 2) is not None:
            echecs.append("journee reelle : gamma_block_long se lit encore "
                          "malgre sa source proxy")

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
