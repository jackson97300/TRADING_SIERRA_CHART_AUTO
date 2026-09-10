"""SCENARIOS, prérequis 2 — `recalc.range_r`, la machine à quatre états au TICK.

    python -X utf8 V3/tests/test_range.py

Ce que ça prouve, écrit avant (définition : docstring de `range_r`) :
  1. Séquence synthétique ES-like (bords 100/96, atr 4, tick 0,25) : FORMATION
     tant qu'un bord n'a pas deux tests TENUS et CONNUS ; ETABLI à la barre où
     le second tenu du second bord devient connu (pas avant) ; une clôture SUR
     le bord est dedans, un tick au-delà est dehors ; UNE clôture dehors ne
     casse pas, DEUX cassent (TRANSITION) ; le retest par l'autre côté → RETEST,
     tenu → CONTINUATION ; deux clôtures revenues → REGAIN, état d'avant.
  2. Miroir exact (cassure par le bas) : mêmes états, `casse_par` = -1.
  3. Largeur : w_min au-dessus de la largeur → jamais ETABLI ; `atr_ref`
     l'emporte sur `atr_barre` pour `largeur_atr`.
  4. Rien de révélé avant `i_connu` : à la barre du test, n_tests compte, l'état
     ne bouge pas.
  5. Réel : ES et NQ 09/09, bords = IB (max/min des 4 premières barres — parité
     au tick avec `dist_ib_high/low` livrés à partir de 10h30), invariants :
     toute TRANSITION = deux clôtures au-delà, aucune acceptation avant CASSE.
  6. DIRECT = RÉTROSPECTIF (MISSION, test 6) : l'état à la barre k, calculé sur
     les barres 0..k seules, est celui du rejeu de la journée complète.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402

PASSED = FAILED = 0
TICK = 0.25


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-66s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def frame(barres, atr=4.0):
    df = pd.DataFrame([dict(zip(("open", "high", "low", "close"), b)) for b in barres],
                      columns=["open", "high", "low", "close"])
    df["atr_barre"] = atr
    df["ts"] = 1_700_000_000_000 + np.arange(len(df)) * 900_000
    return df


# la séquence de référence (bords 100 / 96, atr 4 -> z_reset 0,5 ATR = 2 pts)
BASE = [
    (98, 99, 97, 98),                 # 0  milieu, aucun test
    (98, 100.25, 98, 99.5),           # 1  test HAUT n.1 (par le dessous)
    (99.5, 99.75, 98, 98.5),          # 2  clôture sous 100 -> tenu connu à 2
    (98.5, 98.5, 96.25, 96.5),        # 3  test BAS n.1 (par le dessus) ; réarme le haut
    (96.5, 98, 96.5, 97.5),           # 4  clôture au-dessus de 96 -> tenu connu à 4
    (97.5, 100.25, 97.5, 99.75),      # 5  test HAUT n.2 ; réarme le bas
    (99.75, 99.75, 97, 98),           # 6  tenu connu à 6 -> haut : 2 tenus
    (98, 98, 95.75, 96.25),           # 7  test BAS n.2 ; réarme le haut
    (96.25, 98, 96.25, 97.5),         # 8  tenu connu à 8 -> ETABLI ici
]
CASSURE = [
    (97.5, 100.5, 97.5, 100.25),      # 9  UNE clôture 1 tick au-delà : pas cassé
    (100.25, 101, 100, 100.75),       # 10 DEUX clôtures -> CASSE / TRANSITION
    (102.25, 102.75, 102.25, 102.5),  # 11 s'éloigne (réarme le bord par le dessus)
    (102.5, 102.5, 99.75, 100.25),    # 12 retest du bord cassé PAR LE DESSUS -> RETEST
]
CONTINUATION = [(100.25, 101.5, 100.25, 101.25)]                  # 13 tient -> CONTINUATION
HEADFAKE = [(100.25, 100.5, 98, 98.5), (98.5, 99, 97.5, 98)]      # 13-14 deux clôtures dedans -> REGAIN


def miroir(barres, axe=98.0):
    return [(2 * axe - o, 2 * axe - l, 2 * axe - h, 2 * axe - c) for o, h, l, c in barres]


def etats(lignes):
    return [l["etat"] for l in lignes]


def main():
    # 1. séquence de référence
    L = recalc.range_r(frame(BASE + CASSURE + CONTINUATION), 100.0, 96.0, tick=TICK)
    e = etats(L)
    check("[1a] FORMATION jusqu'a la barre 7 incluse", e[:8] == ["FORMATION"] * 8, e[:8])
    check("[1b] ETABLI a la barre 8 (second tenu du bas CONNU), evenement ETABLI",
          e[8] == "ETABLI" and L[8]["evenement"] == "ETABLI" and L[8]["age_barres"] == 0, L[8])
    check("[1c] n_tests haut 2 / bas 2 a la barre 8, largeur 1,0 ATR",
          L[8]["n_tests_haut"] == 2 and L[8]["n_tests_bas"] == 2 and L[8]["largeur_atr"] == 1.0, L[8])
    check("[1d] barre 9 : UNE cloture a 100,25 (1 tick dehors) -> toujours ETABLI",
          e[9] == "ETABLI" and L[9]["evenement"] is None, L[9])
    check("[1e] barre 10 : DEUX clotures dehors -> CASSE, TRANSITION, casse_par +1",
          e[10] == "CASSE" and L[10]["evenement"] == "TRANSITION" and L[10]["casse_par"] == 1, L[10])
    check("[1f] barre 12 : test du bord casse par le dessus -> RETEST",
          e[12] == "RETEST" and L[12]["evenement"] == "RETEST", L[12])
    check("[1g] barre 13 : le bord tient de l'autre cote -> CONTINUATION",
          e[13] == "RETEST" and L[13]["evenement"] == "CONTINUATION", L[13])
    check("[1h] age_barres compte depuis ETABLI (barre 13 -> 5)", L[13]["age_barres"] == 5, L[13])
    b = list(BASE + CASSURE)
    b[9] = (97.5, 100.5, 97.5, 100.0)
    L2 = recalc.range_r(frame(b), 100.0, 96.0, tick=TICK)
    check("[1i] cloture SUR le bord (100,00) = dedans : 10 ETABLI (une seule dehors), CASSE a 11",
          etats(L2)[10] == "ETABLI" and etats(L2)[11] == "CASSE", etats(L2)[8:12])
    L3 = recalc.range_r(frame(BASE + CASSURE + HEADFAKE), 100.0, 96.0, tick=TICK)
    e3 = etats(L3)
    check("[1j] head-fake : une cloture dedans (13) reste RETEST, deux (14) -> REGAIN, etat ETABLI",
          e3[13] == "RETEST" and e3[14] == "ETABLI" and L3[14]["evenement"] == "REGAIN"
          and L3[14]["casse_par"] is None, (e3[12:], L3[14]["evenement"]))
    # compression = moyenne sur les 4 tests de |extreme - milieu| / demi-largeur (demi = 2) :
    # highs 100,25 / 100,25 -> 1,125 ; lows 96,25 -> 0,875 et 95,75 -> 1,125 ; moyenne 1,0625
    check("[1k] compression a la barre 8 = 1,062 (les EXTREMES des 4 tests, pas les clotures)",
          L[8]["compression"] == 1.062, L[8]["compression"])
    check("[1l] barres_depuis_pose : 0 a la barre 0, 8 a la barre 8",
          L[0]["barres_depuis_pose"] == 0 and L[8]["barres_depuis_pose"] == 8)
    # 2. miroir
    M = recalc.range_r(frame(miroir(BASE + CASSURE + CONTINUATION)), 100.0, 96.0, tick=TICK)
    check("[2a] miroir : memes etats barre a barre", etats(M) == e, list(zip(etats(M), e)))
    check("[2b] miroir : casse_par -1, memes evenements",
          M[10]["casse_par"] == -1 and [m["evenement"] for m in M] == [l["evenement"] for l in L])
    # 3. largeur
    W = recalc.range_r(frame(BASE), 100.0, 96.0, tick=TICK, w_min=1.5)
    check("[3a] w_min 1,5 > largeur 1,0 -> jamais ETABLI", set(etats(W)) == {"FORMATION"}, etats(W))
    f = frame(BASE)
    f["atr_ref"] = 8.0
    R = recalc.range_r(f, 100.0, 96.0, tick=TICK)
    check("[3b] atr_ref (8) l'emporte sur atr_barre (4) : largeur 0,5 ATR", R[8]["largeur_atr"] == 0.5, R[8])
    # 4. rien de révélé avant i_connu
    check("[4a] barre 7 : le test BAS n.2 est COMPTE (n_tests_bas 2) mais l'etat reste FORMATION",
          L[7]["n_tests_bas"] == 2 and e[7] == "FORMATION", L[7])
    D4 = recalc.range_r(frame(BASE), 100.0, 96.0, i_debut=4, tick=TICK)
    check("[4b] i_debut 4 : les barres avant ne sont ni journalisees ni testees",
          D4[0]["i"] == 4 and D4[0]["n_tests_haut"] == 0, D4[0])
    check("[4c] bords inverses ou frame vide -> liste vide",
          recalc.range_r(frame(BASE), 96.0, 100.0) == [] and recalc.range_r(frame([]), 100.0, 96.0) == [])
    # 5. réel : IB de deux journées
    for sym in ("ES", "NQ"):
        df = charger_jour(sym, "20260909", 15)
        if len(df) < 8:
            check("[5] %s 09/09 indisponible" % sym, False)
            continue
        haut, bas = float(df["high"].iloc[:4].max()), float(df["low"].iloc[:4].min())
        c = pd.to_numeric(df["close"], errors="coerce")
        livre_h = c + pd.to_numeric(df["dist_ib_high"], errors="coerce") * TICK
        livre_b = c + pd.to_numeric(df["dist_ib_low"], errors="coerce") * TICK
        eh, eb = float((livre_h.iloc[4:] - haut).abs().max()), float((livre_b.iloc[4:] - bas).abs().max())
        check("[5a] %s : IB recalculee = livree AU TICK des 10h30 (haut %.2f / bas %.2f)" % (sym, haut, bas),
              eh < TICK / 2 and eb < TICK / 2, (eh, eb))
        L = recalc.range_r(df, haut, bas, i_debut=4, tick=TICK)
        seq = " ".join("%d:%s%s" % (l["i"], l["etat"][0], "*" if l["evenement"] else "") for l in L)
        print("      %s IB %.2f/%.2f largeur %s ATR - %s" % (sym, haut, bas, L[0]["largeur_atr"], seq))
        ok = True
        for l in L:
            i = l["i"]
            if l["evenement"] == "TRANSITION":
                ok &= bool((c.iloc[i] > haut and c.iloc[i - 1] > haut) or (c.iloc[i] < bas and c.iloc[i - 1] < bas))
        premiere = next((l["i"] for l in L if l["etat"] == "CASSE"), None)
        for l in L:
            if premiere is not None and 4 < l["i"] < premiere:
                ok &= not ((c.iloc[l["i"]] > haut and c.iloc[l["i"] - 1] > haut)
                           or (c.iloc[l["i"]] < bas and c.iloc[l["i"] - 1] < bas))
        check("[5b] %s : toute TRANSITION = deux clotures au-dela ; aucune acceptation avant CASSE" % sym, ok)
        check("[5c] %s : une ligne par barre de 10h30 a 15h45, etats dans ETATS_RANGE" % sym,
              len(L) == len(df) - 4 and all(l["etat"] in recalc.ETATS_RANGE for l in L))
        # 6. direct = retrospectif (MISSION, test 6) : l'etat a la barre k calcule sur
        # les barres 0..k seules est celui du rejeu de la journee complete.
        ecarts = []
        for k in range(5, len(df) + 1):
            Lk = recalc.range_r(df.iloc[:k], haut, bas, i_debut=4, tick=TICK)
            a, b = Lk[-1], L[k - 5]
            if (a["etat"], a["evenement"], a["n_tests_haut"], a["n_tests_bas"]) !=                     (b["etat"], b["evenement"], b["n_tests_haut"], b["n_tests_bas"]):
                ecarts.append((k - 1, a["etat"], b["etat"]))
        check("[6] %s : DIRECT = RETROSPECTIF barre a barre (etat, evenement, n_tests)" % sym,
              not ecarts, ecarts[:4])

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
