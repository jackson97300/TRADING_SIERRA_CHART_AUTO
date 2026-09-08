"""Mesure du TROU DE CHAUFFE ATR sur LES QUATRE gelées — audit Fable §1.

    python -X utf8 V3/layers/L3_declencheurs/mesure_trou_atr.py

ATTENDU, ÉCRIT AVANT LA MESURE : les lieux des quatre lisent tous
`seuil_ticks(atr_barre)` et `atr_barre` est NaN les 6 premières barres
(min_periods = 7) → **ZÉRO signal des quatre entre 9h30 et 11h00 ET** sur
tout le lot, alors que l'après-midi en porte. ~23 % des barres cash
(6/26) sont dans le trou. Si l'attendu tient, la campagne gelée est
AVEUGLE pendant l'IB et la première heure — rien à changer au gelé, tout
à écrire : SPEC L3 (limitation gelée n° 2) + LECTURE_JOUR_61.

Comptage de signaux par franchissement et d'heures seulement — aucun
devenir, aucun P&L.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402
from CORE.research import hypotheses as H                     # noqa: E402
from CORE.research.hypothesis_runner import (                 # noqa: E402
    injecter_recalculs, signaux_par_franchissement)
from V3.campagne import (COLS_RECALC, MIN_JOURS_CHAUFFE,      # noqa: E402
                         N_JOURS_CHAUFFE, jours_disponibles)

TRANCHES = (("09h30-11h00", 570, 660), ("11h00-13h00", 660, 780),
            ("13h00-15h00", 780, 900), ("15h00-16h00", 900, 960))


def main():
    os.chdir(RACINE)
    sortie = ["# Le trou de chauffe ATR et LES QUATRE gelées (audit 08/09)",
              "",
              "*Attendu écrit avant : ZÉRO signal 9h30-11h00 (atr_barre NaN",
              "6 barres, min_periods=7) alors que l'après-midi en porte ;",
              "~23 % des barres cash dans le trou. Aucun devenir lu.*", ""]
    for sym in ("ES", "NQ"):
        cache = {}
        par_h = {n: {t[0]: 0 for t in TRANCHES} for n in H.LES_QUATRE}
        trou_nan = {t[0]: [0, 0] for t in TRANCHES}   # [nan, total]
        n_jours = 0
        for jour in jours_disponibles(sym):
            df, brut = charger_jour(sym, jour, 15, avec_1min=True)
            if brut.empty or not all(c in brut.columns for c in COLS_RECALC):
                continue
            cache[jour] = brut[COLS_RECALC]
            if df.empty or len(df) < 6:
                continue
            prev = [cache[j] for j in sorted(cache)
                    if j < jour][-N_JOURS_CHAUFFE:]
            if len(prev) < MIN_JOURS_CHAUFFE:
                continue
            dfe = injecter_recalculs(pd.concat(prev + [cache[jour]],
                                               ignore_index=True), df,
                                     minutes=15)
            n_jours += 1
            mn = recalc.minutes_et(pd.to_datetime(dfe["ts"], unit="ms",
                                                  utc=True))
            atr_nan = pd.to_numeric(dfe["atr_barre"], errors="coerce").isna()
            for nom_t, a, b in TRANCHES:
                dans = (mn >= a) & (mn < b)
                trou_nan[nom_t][0] += int((dans & atr_nan).sum())
                trou_nan[nom_t][1] += int(dans.sum())
            for nom, fn in H.LES_QUATRE.items():
                for _c, (cond, _s) in fn(dfe).items():
                    for i in signaux_par_franchissement(cond, dfe["jour"]):
                        m = int(mn.iloc[i])
                        for nom_t, a, b in TRANCHES:
                            if a <= m < b:
                                par_h[nom][nom_t] += 1
        sortie += ["## %s — %d jours évalués" % (sym, n_jours),
                   "| | " + " | ".join(t[0] for t in TRANCHES) + " |",
                   "|---|" + "---|" * len(TRANCHES)]
        for nom in H.LES_QUATRE:
            sortie.append("| %s | " % nom + " | ".join(
                str(par_h[nom][t[0]]) for t in TRANCHES) + " |")
        sortie.append("| barres atr NaN / total | " + " | ".join(
            "%d/%d" % tuple(trou_nan[t[0]]) for t in TRANCHES) + " |")
        matin = sum(par_h[n]["09h30-11h00"] for n in H.LES_QUATRE)
        apres = sum(sum(par_h[n][t[0]] for t in TRANCHES[1:])
                    for n in H.LES_QUATRE)
        sortie += ["", "- signaux 9h30-11h00 : **%d** ; après 11h00 : **%d**"
                   % (matin, apres),
                   "- attendu (zéro le matin, du monde après) : %s"
                   % ("TENU — la campagne gelée est AVEUGLE avant 11h00"
                      if matin == 0 and apres > 0 else
                      "NON TENU (%d matin / %d après) — relire le mécanisme"
                      % (matin, apres)), ""]
    chemin = ("V3/layers/L3_declencheurs/rapports/trou_atr_les_quatre_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    open(chemin, "w", encoding="utf-8").write("\n".join(sortie))
    print("\n".join(sortie))
    print("rapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
