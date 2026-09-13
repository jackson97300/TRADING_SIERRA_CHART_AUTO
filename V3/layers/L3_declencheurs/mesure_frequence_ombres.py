"""LES SEIZE EN OMBRE — leur fréquence sur tout le lot, et rien d'autre.

    python -X utf8 V3/layers/L3_declencheurs/mesure_frequence_ombres.py

POURQUOI CETTE MESURE. Sur les quatre jours de campagne, deux déclencheurs
d'ombre tirent huit et sept fois — contre UNE seule ligne PASSE pour les quatre
gelées. La tentation est immédiate : « la puissance est là, prenons-les ». Mais
quatre jours ne distinguent pas un rythme d'un accident de fenêtre, et treize
déclencheurs se partagent ces tirs. Cette mesure répond à la seule question
qu'on peut poser sans tricher : **à quelle fréquence tirent-ils vraiment, et
ce rythme est-il réparti ou concentré ?**

CE QU'ELLE NE DIT PAS, ET NE DIRA JAMAIS. Rien sur ce que ces tirs ont donné.
Les journaux des seize ne portent aucun champ de résultat — par conception —
et ce module ne calcule aucun devenir, n'ouvre aucun journal de barrières, ne
touche pas `LOGS/`. Un déclencheur fréquent à espérance négative ruine plus
vite qu'un déclencheur rare : la fréquence est une condition nécessaire de
testabilité, jamais un signe de qualité.

LA CONCENTRATION EST LE VRAI CONTRÔLE. L'incident du 28/04 (`INCIDENT_LOG`,
DATA_MINING_TRAP) a produit un « edge » dont les 30 tirs tombaient tous dans un
seul mois : un artefact de disponibilité de la donnée, lu comme un signal. Un N
élevé mais concentré ne vaut rien. On mesure donc, pour chaque déclencheur,
l'EXCÈS de son mois le plus chargé — ses tirs rapportés à ce que ce mois
porterait si les tirs suivaient les jours —, la part de son jour le plus chargé,
et la part de jours où il tire au moins une fois. L'excès, pas la part brute :
sur un lot de deux mois et demi, le mois le plus chargé porte déjà 40 % des
jours sans qu'aucun déclencheur n'y soit pour rien.

LECTURE PAR SETUP, JAMAIS EN GROUPE. `ombre16.py` le dit : « N = 40 par setup,
jamais en groupe — une lecture combinée produirait des gagnants par
combinatoire ». Additionner les treize pour annoncer « cinquante tirs » est
exactement la faute que cette règle interdit.

ATTENDU ÉCRIT AVANT LA PASSE (13/09) : si les quatre jours de campagne étaient
représentatifs, ED09 tirerait ~112 fois sur le lot et ED10 ~98. Un écart net
vers le bas dirait que la fenêtre de quatre jours était un accident ; un écart
vers le haut, que la campagne est tombée sur une période calme.
"""

from __future__ import annotations

import collections
import os
import sys
from datetime import datetime, timezone

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3.campagne import (COLS_RECALC, MIN_JOURS_CHAUFFE,        # noqa: E402
                         N_JOURS_CHAUFFE, jours_disponibles)
from V3.layers.L3_declencheurs.ombre16 import signaux_seize     # noqa: E402

N_VISE = 40              # le seuil du pre-enregistrement, PAR setup
TRANCHES = (("09h30-11h00", 570, 660), ("11h00-13h00", 660, 780),
            ("13h00-15h00", 780, 900), ("15h00-16h00", 900, 960))


def _passe(sym):
    """Une passe sur le lot, cache incrementiel de chauffe. Rend, par setup :
    le total, les tirs par jour, et les tirs par tranche horaire."""
    cache = {}
    par_jour = collections.defaultdict(collections.Counter)   # setup -> jour -> n
    par_tranche = collections.defaultdict(collections.Counter)
    jours_evalues = []
    absentes = set()
    for jour in jours_disponibles(sym):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if not brut.empty and all(c in brut.columns for c in COLS_RECALC):
            cache[jour] = brut[COLS_RECALC]
        if df.empty or len(df) < 6 or jour not in cache:
            continue
        prev = [cache[j] for j in sorted(cache) if j < jour][-N_JOURS_CHAUFFE:]
        if len(prev) < MIN_JOURS_CHAUFFE:
            continue
        dfe = injecter_recalculs(pd.concat(prev + [cache[jour]], ignore_index=True),
                                 df, minutes=15)
        jours_evalues.append(jour)
        mn = recalc.minutes_et(pd.to_datetime(dfe["ts"], unit="ms", utc=True))
        try:
            sig = signaux_seize(dfe)
        except KeyError as e:            # une colonne manque : on le DIT
            absentes.add(str(e))
            continue
        for setup, tirs in sig.items():
            par_jour[setup][jour] += len(tirs)
            for i, _side in tirs:
                m = int(mn.iloc[i])
                for nom_t, a, b in TRANCHES:
                    if a <= m < b:
                        par_tranche[setup][nom_t] += 1
    return jours_evalues, par_jour, par_tranche, sorted(absentes)


def _concentration(compte_par_jour):
    """(exces du mois le plus charge, part du jour le plus charge, part de
    jours actifs).

    L'EXCES, PAS LA PART BRUTE — corrige le 14/09. La premiere version
    comparait la part du mois le plus charge a un seuil fixe de 33 %, repris de
    l'incident du 28/04. Resultat : elle signalait 16 declencheurs sur 16, donc
    elle ne discriminait rien — un detecteur qui flague tout est pire qu'aucun
    detecteur. La cause est arithmetique : le lot couvre deux mois et demi, donc
    le mois le plus charge porte DEJA 40 % des jours sous une repartition
    parfaitement uniforme. Le 33 % du 28/04 visait un lot de DOUZE mois.

    On compare donc chaque mois a ce qu'il porterait si les tirs suivaient les
    JOURS : l'exces est le rapport part_des_tirs / part_des_jours. Un rapport
    de 1,0 est une repartition parfaite ; au-dela de 1,5, le declencheur tire
    nettement plus dans ce mois-la que le lot ne l'explique."""
    total = sum(compte_par_jour.values())
    if not total:
        return 0.0, 0.0, 0.0
    tirs_mois, jours_mois = collections.Counter(), collections.Counter()
    for jour, n in compte_par_jour.items():
        tirs_mois[jour[:6]] += n
        jours_mois[jour[:6]] += 1
    n_jours = len(compte_par_jour)
    exces = max((tirs_mois[m] / total) / (jours_mois[m] / n_jours)
                for m in tirs_mois if jours_mois[m])
    actifs = sum(1 for n in compte_par_jour.values() if n)
    return exces, max(compte_par_jour.values()) / total, actifs / n_jours


def _tableau(sym, jours, par_jour, par_tranche, s):
    n_j = len(jours)
    s += ["## %s — %d jours évalués (%s → %s)" % (sym, n_j, jours[0], jours[-1]), "",
          "| déclencheur | N | par jour | jours pour N=%d | jours actifs |"
          " excès mensuel | jour le + chargé |" % N_VISE,
          "|---|---|---|---|---|---|---|"]
    lignes = []
    for setup in sorted(par_jour, key=lambda k: -sum(par_jour[k].values())):
        compte = {j: par_jour[setup].get(j, 0) for j in jours}
        n = sum(compte.values())
        mois, pire_jour, actifs = _concentration(compte)
        jours_n40 = ("%.0f" % (N_VISE / (n / n_j))) if n else "jamais"
        lignes.append((setup, n, n / n_j, jours_n40, actifs, mois, pire_jour))
        s.append("| `%s` | %d | %.2f | %s | %.0f %% | x%.2f | %.0f %% |"
                 % (setup, n, n / n_j, jours_n40, 100 * actifs, mois,
                    100 * pire_jour))
    s.append("")
    s += ["### Répartition horaire", "",
          "| déclencheur | " + " | ".join(t[0] for t in TRANCHES) + " |",
          "|---|" + "---|" * len(TRANCHES)]
    for setup, n, *_ in lignes:
        if not n:
            continue
        s.append("| `%s` | " % setup + " | ".join(
            str(par_tranche[setup].get(t[0], 0)) for t in TRANCHES) + " |")
    s.append("")
    return lignes


def main():
    os.chdir(RACINE)
    s = ["# Les seize en ombre — fréquence sur le lot (aucun devenir lu)", "",
         "*Attendu écrit avant la passe : si les quatre jours de campagne étaient",
         "représentatifs, ED09 tirerait ~112 fois et ED10 ~98 sur le lot. Un écart",
         "net vers le bas dirait que la fenêtre de quatre jours était un accident.*",
         "",
         "**Ce tableau ne dit RIEN de la qualité de ces déclencheurs.** La fréquence",
         "est une condition nécessaire de testabilité, jamais un signe de valeur : un",
         "déclencheur fréquent à espérance négative ruine plus vite qu'un rare.",
         "Lecture PAR SETUP, jamais en groupe — additionner les treize produirait",
         "des gagnants par combinatoire (règle du pré-enregistrement).", ""]
    verdicts = []
    for sym in ("ES", "NQ"):
        jours, par_jour, par_tranche, absentes = _passe(sym)
        if not jours:
            s += ["## %s — aucun jour évalué" % sym, ""]
            continue
        lignes = _tableau(sym, jours, par_jour, par_tranche, s)
        if absentes:
            s += ["> colonnes absentes rencontrées : %s" % ", ".join(absentes), ""]
        verdicts.append((sym, len(jours), lignes))
    s += ["## Ce que la passe permet de dire", ""]
    for sym, n_j, lignes in verdicts:
        # atteignables dans les 57 jours qui restent, au rythme MESURE
        ok = [(nom, n) for nom, n, par_j, *_ in lignes if par_j and N_VISE / par_j <= 57]
        concentres = [nom for nom, n, _pj, _n40, _act, mois, _pire in lignes
                      if n and mois > 1.5]
        s += ["- **%s** (%d jours) : %d déclencheur(s) atteindraient N=%d dans les"
              " 57 jours restants au rythme mesuré — %s"
              % (sym, n_j, len(ok), N_VISE,
                 ", ".join("`%s`" % n for n, _ in ok) if ok else "aucun"),
              "- **%s** : déclencheur(s) tirant plus de 1,5 fois ce qu'un mois"
              " porterait a repartition uniforme (artefact probable, cf 28/04) — %s"
              % (sym, ", ".join("`%s`" % n for n in concentres) if concentres
                 else "aucun")]
    s += ["", "*Aucun devenir n'a été lu ni écrit : ce module ne touche pas",
          "`LOGS/`, ne calcule aucune barrière et n'ouvre aucun journal.*"]
    chemin = ("V3/layers/L3_declencheurs/rapports/frequence_ombres_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    open(chemin, "w", encoding="utf-8").write("\n".join(s))
    print("\n".join(s))
    print("\nrapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
