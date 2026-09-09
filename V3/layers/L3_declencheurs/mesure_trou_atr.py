"""Mesure du TROU DE CHAUFFE ATR sur LES QUATRE gelées — audit Fable §1,
puis brique 1 (09/09) : le même harnais, le mètre `atr_ref`.

    python -X utf8 V3/layers/L3_declencheurs/mesure_trou_atr.py

ATTENDU DU 08/09 (tenu, rapport daté 20260908) : les lieux des quatre lisent
`seuil_ticks(atr_barre)` et `atr_barre` est NaN les 6 premières barres
(min_periods = 7) → ZÉRO signal des quatre entre 9h30 et 11h00 ET sur tout
le lot ; ~23 % des barres cash dans le trou.

ATTENDU DU 09/09, ÉCRIT AVANT LA RELANCE (DECISIONS, brique 1) : avec
`atr_ref` (= atr_barre si fini, sinon l'ATR de la DERNIÈRE SESSION COMPLÈTE)
les lieux du matin deviennent POSSIBLES : N > 0 signaux 9h30-11h00 attendus,
aucune direction attendue sur leur devenir ; `atr_ref` NaN seulement sans
session complète avant (premier jour du lot) ; les signaux du matin portent
`atr_source = veille` et se lisent À PART (règle 15).

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
MATIN = TRANCHES[0][0]


def _compter(sym):
    """Une passe sur le lot : signaux par hypothèse et tranche, barres sans
    atr_barre / sans atr_ref par tranche, signaux du matin par atr_source,
    jours sans session complète avant (atr_ref = aucun à la barre 0)."""
    cache = {}
    par_h = {n: {t[0]: 0 for t in TRANCHES} for n in H.LES_QUATRE}
    trou = {"atr_barre": {t[0]: 0 for t in TRANCHES},
            "atr_ref": {t[0]: 0 for t in TRANCHES}}
    total = {t[0]: 0 for t in TRANCHES}
    src_matin = {}
    n_jours = jours_sans_veille = 0
    for jour in jours_disponibles(sym):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if brut.empty or not all(c in brut.columns for c in COLS_RECALC):
            continue
        cache[jour] = brut[COLS_RECALC]
        if df.empty or len(df) < 6:
            continue
        prev = [cache[j] for j in sorted(cache) if j < jour][-N_JOURS_CHAUFFE:]
        if len(prev) < MIN_JOURS_CHAUFFE:
            continue
        dfe = injecter_recalculs(pd.concat(prev + [cache[jour]],
                                           ignore_index=True), df, minutes=15)
        n_jours += 1
        jours_sans_veille += str(dfe["atr_source"].iloc[0]) == "aucun"
        mn = recalc.minutes_et(pd.to_datetime(dfe["ts"], unit="ms", utc=True))
        for col in trou:
            nan = pd.to_numeric(dfe[col], errors="coerce").isna()
            for nom_t, a, b in TRANCHES:
                dans = (mn >= a) & (mn < b)
                trou[col][nom_t] += int((dans & nan).sum())
                if col == "atr_barre":
                    total[nom_t] += int(dans.sum())
        for nom, fn in H.LES_QUATRE.items():
            for _c, (cond, _s) in fn(dfe).items():
                for i in signaux_par_franchissement(cond, dfe["jour"]):
                    m = int(mn.iloc[i])
                    for nom_t, a, b in TRANCHES:
                        if a <= m < b:
                            par_h[nom][nom_t] += 1
                    if m < TRANCHES[0][2]:
                        s = str(dfe["atr_source"].iloc[i])
                        src_matin[s] = src_matin.get(s, 0) + 1
    return n_jours, jours_sans_veille, par_h, trou, total, src_matin


def main():
    os.chdir(RACINE)
    sortie = ["# Le trou de chauffe ATR et LES QUATRE — `atr_ref` (brique 1, 09/09)",
              "",
              "*Attendu écrit avant : avec `atr_ref` (atr_barre, sinon ATR de la",
              "dernière session complète), N > 0 signaux des quatre 9h30-11h00,",
              "aucune direction attendue ; `atr_ref` NaN seulement sans session",
              "complète avant ; le matin porte `atr_source = veille` (règle 15).",
              "Aucun devenir lu.*", ""]
    for sym in ("ES", "NQ"):
        n_jours, sans_veille, par_h, trou, total, src = _compter(sym)
        sortie += ["## %s — %d jours évalués (%d sans session complète avant)"
                   % (sym, n_jours, sans_veille),
                   "| | " + " | ".join(t[0] for t in TRANCHES) + " |",
                   "|---|" + "---|" * len(TRANCHES)]
        for nom in H.LES_QUATRE:
            sortie.append("| %s | " % nom + " | ".join(
                str(par_h[nom][t[0]]) for t in TRANCHES) + " |")
        for col in ("atr_barre", "atr_ref"):
            sortie.append("| barres %s NaN / total | " % col + " | ".join(
                "%d/%d" % (trou[col][t[0]], total[t[0]]) for t in TRANCHES) + " |")
        matin = sum(par_h[n][MATIN] for n in H.LES_QUATRE)
        apres = sum(sum(par_h[n][t[0]] for t in TRANCHES[1:]) for n in H.LES_QUATRE)
        nan_ref_ok = trou["atr_ref"][MATIN] <= 6 * sans_veille
        tenu = matin > 0 and apres > 0 and nan_ref_ok and set(src) <= {"veille"}
        sortie += ["", "- signaux 9h30-11h00 : **%d** (atr_source : %s) ; après 11h00 : **%d**"
                   % (matin, ", ".join("%s=%d" % kv for kv in sorted(src.items()))
                      or "aucun", apres),
                   "- attendu (des lieux le matin, atr_ref NaN seulement sans veille,"
                   " matin = veille) : %s"
                   % ("TENU — le matin est MESURABLE, il se lit à part"
                      if tenu else
                      "NON TENU (%d matin / %d après / atr_ref NaN matin %d pour"
                      " %d jour(s) sans veille / sources %s) — relire le mécanisme"
                      % (matin, apres, trou["atr_ref"][MATIN], sans_veille, src)),
                   ""]
    chemin = ("V3/layers/L3_declencheurs/rapports/trou_atr_les_quatre_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    open(chemin, "w", encoding="utf-8").write("\n".join(sortie))
    print("\n".join(sortie))
    print("rapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
