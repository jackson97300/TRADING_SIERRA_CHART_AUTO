"""Mesure L4 — k = 1/2/3 sur le lot, SPEC §5. L'attendu, écrit avant :
taux de veto global 20-40 % (hors [10 ; 50] = inerte ou étrangleuse) ;
devenir des vetoés ≤ retenus ; au moins deux vetos sur cinq dans le bruit ;
L4 passe si séparation × taux_veto > glissement.

    python -X utf8 V3/layers/L4_orderflow/mesure_57j.py

Signaux de lecture : H3 et H7 du cycle 1 (écrit tel quel, SPEC §11) — pas
de colonne `_r`, pas de chauffe. Issue : triple barrière B-ATR (TP 1,5 /
SL 1,0 / 20 barres), pnl net en ATR. Par instrument et par déclencheur ;
`stats.py` bloc semaine apparié ; contrôle : veto ALÉATOIRE au même taux,
500 tirages, graine fixe. ~30 comparaisons → l'avertissement de la SPEC §8
est imprimé en bas du rapport.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research import hypotheses as H                     # noqa: E402
from CORE.research.hypothesis_runner import (                 # noqa: E402
    signaux_par_franchissement, triple_barriere)
from V3 import stats                                          # noqa: E402
from V3.campagne import jours_disponibles                     # noqa: E402
from V3.layers.L4_orderflow import confirmation               # noqa: E402

COUTS = {"NQ": (2.82, 2.00), "ES": (4.32, 5.00)}
KS = (1, 2, 3)
N_TIRAGES_HASARD = 500
GRAINE = 7


def signaux_du_jour(df):
    out = []
    for nom, fn in (("H3", H.h3), ("H7", H.h7)):
        for _c, (cond, side) in fn(df).items():
            for i in signaux_par_franchissement(cond, df["jour"]):
                out.append((int(i), int(side), nom))
    return sorted(set(out))


def collecter(sym):
    """[(jour, hyp, side, pnl_atr, {k: resultat_confirmation})]."""
    s = confirmation.charger_seuils(sym)
    lignes = []
    for jour in jours_disponibles(sym):
        df, b1 = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or len(df) < 8 or b1.empty:
            continue
        ts1 = b1["ts"].to_numpy()
        for i, side, hyp in signaux_du_jour(df):
            issue = triple_barriere(df, i, side, COUTS[sym])
            if issue is None or i + 1 >= len(df):
                continue
            pnl = float(issue[1])
            atr = float(pd.to_numeric(df["atr_barre"], errors="coerce").iloc[i])
            i1 = int(np.searchsorted(ts1, int(df["ts"].iloc[i + 1])))
            if i1 >= len(b1) or int(ts1[i1]) != int(df["ts"].iloc[i + 1]):
                continue                      # fenetre 1 min introuvable
            confs = {k: confirmation.confirmer(b1, i1, side, s, k=k, atr=atr)
                     for k in KS}
            lignes.append((jour, hyp, side, pnl, confs))
    return lignes


def _hasard(pnls, taux, n=N_TIRAGES_HASARD, graine=GRAINE):
    """Séparation d'un veto ALÉATOIRE au même taux — l'intervalle du bruit.

    LIMITE ÉCRITE (review 07/09, R1) : le tirage est PAR SIGNAL, pas par
    bloc semaine — l'IC est donc probablement TROP ÉTROIT (les vetos réels
    arrivent groupés). Sans risque pour un verdict « dans le bruit » (un IC
    étroit le renforce) ; **INTERDIT de servir tel quel au jour 61** si une
    séparation en sortait — re-tirer par bloc d'abord."""
    rng = random.Random(graine)
    seps = []
    for _ in range(n):
        marque = [rng.random() < taux for _ in pnls]
        v = [p for p, m in zip(pnls, marque) if m]
        r = [p for p, m in zip(pnls, marque) if not m]
        if v and r:
            seps.append(float(np.mean(r) - np.mean(v)))
    return (float(np.percentile(seps, 2.5)),
            float(np.percentile(seps, 97.5))) if seps else (0.0, 0.0)


def rapport_pour(sym, lignes, sortie):
    sortie.append("## %s — %d signaux (H3+H7) sur %d jours"
                  % (sym, len(lignes),
                     len({j for j, *_ in lignes})))
    blocs = stats.blocs_semaine(sorted({j for j, *_ in lignes}))
    for k in KS:
        confirmes = [(j, p) for j, _h, _s, p, c in lignes
                     if c[k]["decision"] == "CONFIRME"]
        vetoes = [(j, p) for j, _h, _s, p, c in lignes
                  if c[k]["decision"] == "VETO"]
        indispo = sum(1 for *_x, c in lignes
                      if c[KS[0]] and c[k]["decision"] == "INDISPONIBLE")
        n = len(confirmes) + len(vetoes)
        if n == 0:
            sortie.append("### k=%d : aucune fenetre disponible" % k)
            continue
        taux = len(vetoes) / n
        a = {}
        b = {}
        for j, p in confirmes:
            a.setdefault(j, []).append(p)
        for j, p in vetoes:
            b.setdefault(j, []).append(p)
        if a and b:
            sep, demi, n_blocs = stats.difference_appariee(a, b, blocs)
        else:
            sep, demi, n_blocs = float("nan"), float("nan"), 0
        bas, haut = _hasard([p for _j, p in confirmes + vetoes], taux)
        gliss = [c[k]["glissement_atr"] for *_x, c in lignes
                 if c[k]["decision"] == "CONFIRME"
                 and c[k]["glissement_atr"] is not None]
        g = float(np.mean(gliss)) if gliss else float("nan")
        par_veto = {}
        for vid in ("V1", "V2", "V3", "V4", "V5"):
            vrais = sum(1 for *_x, c in lignes if c[k]["vetos"].get(vid) is True)
            trous = sum(1 for *_x, c in lignes if c[k]["vetos"].get(vid) is None)
            par_veto[vid] = (vrais, trous)
        gain = (sep * taux) if np.isfinite(sep) else float("nan")
        sortie += [
            "### k=%d — %d confirmes / %d vetoes (taux %.1f %%), %d indisponibles"
            % (k, len(confirmes), len(vetoes), 100 * taux, indispo),
            "- separation retenus − vetoes : **%+.3f ± %.3f ATR** (%d blocs)"
            % (sep, demi, n_blocs),
            "- controle veto ALEATOIRE au meme taux : IC 95 %% [%+.3f ; %+.3f]"
            % (bas, haut),
            "- glissement moyen des confirmes : **%+.3f ATR**" % g,
            "- gain net attendu = separation x taux − glissement : %+.4f ATR"
            % (gain - g if np.isfinite(gain) and np.isfinite(g) else float("nan")),
            "- par veto (vrais / trous sur %d signaux) : %s"
            % (n, " ".join("%s=%d/%d" % (v, x[0], x[1])
                           for v, x in par_veto.items())),
            "",
        ]
    # par declencheur, k=2 (le milieu) — jamais agrege sans le detail
    for hyp in ("H3", "H7"):
        sous = [(j, p, c) for j, h, _s, p, c in lignes if h == hyp]
        if not sous:
            continue
        v = [p for _j, p, c in sous if c[2]["decision"] == "VETO"]
        r = [p for _j, p, c in sous if c[2]["decision"] == "CONFIRME"]
        sortie.append("- %s (k=2) : %d signaux, %d vetoes ; devenir retenus "
                      "%+.3f / vetoes %+.3f"
                      % (hyp, len(sous), len(v),
                         float(np.mean(r)) if r else float("nan"),
                         float(np.mean(v)) if v else float("nan")))
    sortie.append("")


def main():
    os.chdir(RACINE)
    sortie = ["# Mesure L4 — k = 1/2/3 sur le lot (SPEC §5)",
              "", "*Attendu ecrit avant : taux 20-40 %, vetoes <= retenus,",
              "au moins deux vetos dans le bruit, passage si separation x",
              "taux > glissement. V5 est en trou (seuils null) : ses",
              "compteurs disent combien de fois il n'a pas pu repondre.*", ""]
    for sym in ("ES", "NQ"):
        rapport_pour(sym, collecter(sym), sortie)
    sortie += ["---", "AVERTISSEMENT (SPEC §8) : ~30 comparaisons dans ce",
               "rapport — un seuil de significativite nominal y fabrique des",
               "faux positifs. ES et NQ comptent pour UN test (SPEC §5)."]
    chemin = ("V3/layers/L4_orderflow/rapports/mesure_l4_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    open(chemin, "w", encoding="utf-8").write("\n".join(sortie))
    print("rapport : %s" % chemin)
    print("\n".join(sortie[-30:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
