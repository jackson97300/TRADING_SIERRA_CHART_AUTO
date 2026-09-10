"""SCÉNARIOS — la grammaire v0 au tick, sur des journées synthétiques
(MISSION « Tests, minimum »).

    python -X utf8 V3/tests/test_grammaire.py

Ce que ça prouve, écrit avant :
  1. Un état par scénario : validé / invalidé / bascule — TEND validé par
     l'acceptation au-delà de l'IB ; réintégration TENTÉE (une clôture) ne
     bascule pas, ACCEPTÉE (deux) bascule ; PULL (pullback tenu puis nouvel
     extrême) ; TRAV (80 % sans pullback) puis rejet au VPOC → S_AUTRE ;
     reprise (→ TEND) ; POSE validé à la clôture ; CASSURE → CONTINUATION ;
     CASSURE → REGAIN → HEADFAKE → nouvelle CASSURE.
  2. LONG et SHORT en MIROIR : la journée réfléchie autour du VPOC rend le
     scénario miroir, mêmes barres de validation / bascule.
  3. Zone = bande asymétrique : un prix au bord bas est dedans, un tick en
     dessous est dehors ; `dedans` du côté du prix, `dehors` au-delà.
  4. Le rôle change avec le scénario (la même VAL : invalidation / pullback /
     cible).
  5. S_AUTRE produit : IB hors norme sur une ouverture dans la VA ; pas de VA.
  6. Aucun mot conclusif dans le code ni dans les journaux.
  7. ZONE_DEPLACEE journalisé avec la barre quand un mur bouge.
  8. DIRECT = RÉTROSPECTIF barre à barre sur chaque journée synthétique.
"""
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.scenarios import grammaire, scenarios, zones as Z     # noqa: E402

PASSED = FAILED = 0
TICK, ATR = 0.25, 8.0
T0 = int(pd.Timestamp("2026-09-09 13:30", tz="UTC").value // 1_000_000)     # 9h30 ET, EDT
SEUILS = {"zones": {"dedans": "P10", "zone_deplacee_ticks": 1, "zero_dte_minutes_et": 840,
                    "dehors_ticks": {"VA_veille": {"ES": 28}, "IB": {"ES": 8}, "PDH_PDL": {"ES": 19},
                                     "OVN": {"ES": 21}, "MUR_call_put": {"ES": 16}},
                    "provenance": {"VA_veille": "w0"}},
          "range": {"w_min_atr": {"ES": 0.5}, "w_max_atr": {"ES": 5.0}}}
VA = {"dist_prev_vah": 110.0, "dist_prev_val": 100.0, "dist_prev_vpoc": 105.0}


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def journee(barres, niveaux=VA, murs=None, n=26):
    """26 barres 15 min (les manquantes prolongent la dernière, plates) + un
    brut d'une ligne portant les niveaux EN PRIX (convertis en dist)."""
    b = list(barres)
    while len(b) < n:
        c = b[-1][3]
        b.append((c, c + 0.25, c - 0.25, c))
    df = pd.DataFrame(b[:n], columns=["open", "high", "low", "close"]).astype(float)
    df["ts"] = [T0 + k * 900_000 for k in range(len(df))]
    df["atr_barre"] = ATR
    df["atr_ref"] = ATR
    df["dist_mq_hvl"] = -8.0
    o = float(df["open"].iloc[0])
    brut = {"ts": [T0], "close": [o], "open_cash_lvl": [o]}
    for col, prix in {**niveaux, **(murs or {})}.items():
        brut[col] = [(prix - o) / TICK]
    return df, pd.DataFrame(brut)


def miroir(df, brut, axe=105.0):
    d = df.copy()
    d["open"], d["close"] = 2 * axe - df["open"], 2 * axe - df["close"]
    d["high"], d["low"] = 2 * axe - df["low"], 2 * axe - df["high"]
    b = brut.copy()
    b["close"], b["open_cash_lvl"] = 2 * axe - brut["close"], 2 * axe - brut["open_cash_lvl"]
    for col in b.columns:
        if col.startswith("dist_"):
            b[col] = -brut[col]
    # un miroir echange les roles : le VAH devient la VAL, le PDH le PDL...
    for a_, b_ in (("dist_prev_vah", "dist_prev_val"), ("dist_pdh", "dist_pdl"),
                   ("dist_ovn_high", "dist_ovn_low"), ("dist_mq_call", "dist_mq_put")):
        if a_ in b.columns and b_ in b.columns:
            b[a_], b[b_] = b[b_].copy(), b[a_].copy()
    return d, b


def derniere(df, brut):
    return scenarios.derouler(df, brut, "ES", SEUILS)[-1]


def fin(lignes):
    return [(l["scenario_en_cours"], l["precision"], l["valide"]) for l in lignes]


# --- les journées synthétiques (VA 100 / 110, VPOC 105, atr 8 -> P10 3,2 t, z_reset 4 pts)
TEND_HAUT = [(115, 116, 114, 115.5), (115.5, 118, 113, 117), (117, 117.5, 112, 116), (116, 117, 114, 115),
             (115, 117, 114.5, 116), (116, 119, 115.5, 118.5), (118.5, 121, 118, 120.5)]          # IB 112/118, casse a 6
REJET_PULL = [(115, 116, 114, 115.5), (115.5, 115.5, 107.5, 108), (108, 107, 104, 104.5),
              (104.5, 110.75, 108, 109), (109, 109.5, 106, 107), (107, 107.5, 102.5, 103)]
REINT_TRAV = [(95, 96, 94, 95.5), (95.5, 101.5, 95, 101), (101, 103, 100.5, 102), (102, 109, 101.5, 108.5),
              (108.5, 109, 103.5, 104), (104, 104.5, 102.5, 103)]
REPRISE = [(95, 96, 94, 95.5), (95.5, 101.5, 95, 101), (101, 103, 100.5, 102), (102, 102.5, 97.5, 98),
           (98, 98.5, 96.5, 97)]
POSE = [(105, 109, 101, 106), (106, 108, 103, 104), (104, 107, 102, 106), (106, 108, 104, 105)] + \
       [(105, 106, 104, 105.5)] * 22
CASSURE = [(105, 109, 101, 106), (106, 108, 103, 104), (104, 107, 102, 106), (106, 108, 104, 105),
           (105, 106, 104, 105.5), (105.5, 110.5, 105, 110), (110, 111.5, 109.5, 111),
           (111, 114.5, 113.5, 114), (114, 111, 108.5, 110), (110, 112, 109.5, 111)]
HEADFAKE = CASSURE[:7] + [(111, 111.5, 107.5, 108), (108, 108.5, 106.5, 107), (107, 110.5, 106.5, 110),
                          (110, 111.5, 109.5, 111)]
IB_ETROITE = [(105, 106, 104, 105.5)] * 26


def main():
    # 1. les états
    L = scenarios.derouler(*journee(TEND_HAUT), "ES", SEUILS)
    check("[1a] ouvre > VAH -> S_OUV_HAUT_TEND, valide a la barre 6 (deux clotures > IB high)",
          L[5]["scenario_en_cours"] == "S_OUV_HAUT_TEND" and not L[5]["valide"] and L[6]["valide"]
          and L[6]["validations"][0]["quoi"] == "acceptation_au_dela_IB_high", fin(L)[:7])
    L = scenarios.derouler(*journee(REJET_PULL), "ES", SEUILS)
    check("[1b] une cloture dans la VA = TENTEE, pas de bascule ; deux = ACCEPTEE -> S_OUV_HAUT_REINT valide",
          L[1]["scenario_en_cours"] == "S_OUV_HAUT_TEND" and L[1]["reintegration"]["tentee_i"] == 1
          and L[2]["scenario_en_cours"] == "S_OUV_HAUT_REINT" and L[2]["valide"]
          and L[2]["bascules"][0]["cause"] == "reintegration_acceptee", fin(L)[:4])
    check("[1c] pullback sur le VAH tenu a la barre 4 -> precision PULL (code inchange)",
          L[3]["precision"] is None and L[4]["precision"] == "PULL"
          and L[4]["scenario_en_cours"] == "S_OUV_HAUT_REINT", fin(L)[3:6])
    check("[1c bis] etat_scenario / titre : en cours non valide a la barre 1, valide 10h00 a la barre 2, invalide sur la barre de bascule",
          L[1]["etat_scenario"] == "en_cours" and "non valide" in L[1]["titre"] and not L[1]["arme"]
          and L[2]["etat_scenario"] == "invalide" and L[2]["invalide"]["de"] == "S_OUV_HAUT_TEND"
          and L[3]["etat_scenario"] == "valide" and "valide 10h00" in L[3]["titre"] and L[3]["arme"],
          [(l["etat_scenario"], l["titre"]) for l in L[1:4]])
    L = scenarios.derouler(*journee(REINT_TRAV), "ES", SEUILS)
    check("[1d] ouvre < VAL, reint acceptee -> S_OUV_BAS_REINT valide a la barre 2, precision null",
          L[2]["scenario_en_cours"] == "S_OUV_BAS_REINT" and L[2]["precision"] is None and L[2]["valide"], fin(L)[:4])
    check("[1e] 80 % franchi sans pullback -> precision TRAV a la barre 3, meme famille, pas de bascule",
          L[3]["scenario_en_cours"] == "S_OUV_BAS_REINT" and L[3]["precision"] == "TRAV"
          and len(L[3]["bascules"]) == 1, fin(L)[3:5])
    check("[1f] rejet au VPOC accepte (deux clotures < VPOC apres l'avoir franchi) -> S_AUTRE(rejet_vpoc)",
          L[5]["scenario_en_cours"] == "S_AUTRE" and L[5]["bascules"][-1]["cause"] == "rejet_vpoc", fin(L)[4:7])
    L = scenarios.derouler(*journee(REPRISE), "ES", SEUILS)
    check("[1g] reprise : deux clotures de nouveau < VAL -> retour S_OUV_BAS_TEND (cause reprise)",
          L[4]["scenario_en_cours"] == "S_OUV_BAS_TEND" and L[4]["bascules"][-1]["cause"] == "reprise", fin(L)[2:6])
    L = scenarios.derouler(*journee(POSE), "ES", SEUILS)
    check("[1h] ouvre dans la VA, IB posee, aucune acceptation dehors -> S_DANS_POSE, valide a 15h45 seulement",
          L[10]["scenario_en_cours"] == "S_DANS_POSE" and not L[24]["valide"] and L[25]["valide"], fin(L)[23:])
    L = scenarios.derouler(*journee(CASSURE), "ES", SEUILS)
    check("[1i] CASSE de l'IB a la barre 6 -> S_DANS_CASSURE_HAUT ; retest tenu (9) -> CONTINUATION = valide",
          L[6]["scenario_en_cours"] == "S_DANS_CASSURE_HAUT" and not L[8]["valide"] and L[9]["valide"]
          and L[9]["validations"][-1]["quoi"] == "retest_tenu", fin(L)[5:10])
    L = scenarios.derouler(*journee(HEADFAKE), "ES", SEUILS)
    check("[1j] REGAIN (8) -> S_DANS_HEADFAKE valide ; nouvelle CASSE (10) -> S_DANS_CASSURE_HAUT",
          L[8]["scenario_en_cours"] == "S_DANS_HEADFAKE" and L[8]["valide"]
          and L[10]["scenario_en_cours"] == "S_DANS_CASSURE_HAUT", fin(L)[7:11])
    # 2. miroir
    for nom, jour, attendu in (("TEND", TEND_HAUT, "S_OUV_BAS_TEND"), ("REINT", REJET_PULL, "S_OUV_BAS_REINT")):
        A = scenarios.derouler(*journee(jour), "ES", SEUILS)
        M = scenarios.derouler(*miroir(*journee(jour)), "ES", SEUILS)
        va, vm = A[-1]["valide_a_i"], M[-1]["valide_a_i"]
        check("[2] miroir EXACT %s -> %s, meme barre de validation (%s), meme precision, memes bascules" % (nom, attendu, vm),
              M[-1]["scenario_en_cours"] == attendu and va == vm and M[-1]["precision"] == A[-1]["precision"]
              and [b["i"] for b in M[-1]["bascules"]] == [b["i"] for b in A[-1]["bascules"]],
              (fin(A)[-1], fin(M)[-1], va, vm))
    # 3. la bande
    z = {"prix": 100.0, "dedans_ticks": 4, "dehors_ticks": 20}
    check("[3a] prix en dessous : bande [prix - dedans, prix + dehors] = [99, 105]", Z.bande(z, 98.0) == (99.0, 105.0))
    check("[3b] prix au-dessus : bande [prix - dehors, prix + dedans] = [95, 101]", Z.bande(z, 102.0) == (95.0, 101.0))
    bas, haut = Z.bande(z, 98.0)
    check("[3c] un prix AU bord bas est dedans, un tick en dessous est dehors",
          bas <= 99.0 <= haut and not (bas <= 98.75 <= haut))
    # 4. le role change avec le scenario
    roles = {s: grammaire.ROLES[s].get("prev_val") for s in ("S_OUV_BAS_TEND", "S_OUV_BAS_REINT", "S_OUV_HAUT_REINT")}
    check("[4] prev_val : invalidation / pullback / cible selon le scenario",
          roles == {"S_OUV_BAS_TEND": "invalidation", "S_OUV_BAS_REINT": "pullback", "S_OUV_HAUT_REINT": "cible"}, roles)
    # 5. S_AUTRE
    S2 = {"zones": SEUILS["zones"], "range": {"w_min_atr": {"ES": 1.72}, "w_max_atr": {"ES": 5.03}}}
    L = scenarios.derouler(*journee(IB_ETROITE), "ES", S2)
    check("[5a] IB 0,25 ATR < w_min sur une ouverture dans la VA -> S_AUTRE(IB_hors_norme) a 10h30",
          L[3]["scenario_en_cours"] == "S_DANS_POSE" and L[4]["scenario_en_cours"] == "S_AUTRE"
          and L[4]["bascules"][0]["cause"] == "IB_hors_norme", fin(L)[3:5])
    L = scenarios.derouler(*journee(POSE, niveaux={"dist_pdh": 120.0}), "ES", SEUILS)
    check("[5b] pas de VA -> S_AUTRE(pas_de_VA) des l'ouverture", L[0]["scenario_en_cours"] == "S_AUTRE"
          and L[0]["sequence_etats"][0].get("raison") == "pas_de_VA")
    # 6. aucun mot conclusif
    conclusifs = re.compile(r"\b(va monter|va baisser|devrait|doit monter|doit baisser|cible atteinte garantie|"
                            r"will rise|will fall)\b", re.I)
    src = "".join(open(RACINE / "V3" / "scenarios" / f, encoding="utf-8").read()
                  for f in ("grammaire.py", "zones.py", "scenarios.py"))
    dump = str(scenarios.derouler(*journee(HEADFAKE), "ES", SEUILS))
    check("[6] aucun mot conclusif dans le code ni dans le journal", not conclusifs.search(src) and not conclusifs.search(dump))
    # 7. ZONE_DEPLACEE
    df, brut = journee(POSE, murs={"dist_mq_call": 130.0})
    b2 = pd.concat([brut, brut.assign(ts=[T0 + 5 * 900_000 + 60_000], dist_mq_call=[(133.0 - float(brut["close"].iloc[0])) / TICK])],
                   ignore_index=True)
    L = scenarios.derouler(df, b2, "ES", SEUILS)
    ev = [e for l in L for e in l["evenements_zones"] if e["quoi"] == "ZONE_DEPLACEE"]
    check("[7] un mur qui bouge (130 -> 133) a la barre 5 = ZONE_DEPLACEE, barre 5, jamais une correction",
          len(ev) == 1 and ev[0]["i"] == 5 and ev[0]["de"] == 130.0 and ev[0]["vers"] == 133.0
          and any(z["nom"] == "mq_call" and z["prix"] == 133.0 for z in L[5]["zones"]), ev)
    # 8. direct = retrospectif
    for nom, jour in (("REJET_PULL", REJET_PULL), ("REINT_TRAV", REINT_TRAV), ("HEADFAKE", HEADFAKE), ("POSE", POSE)):
        df, brut = journee(jour)
        R = scenarios.derouler(df, brut, "ES", SEUILS)
        ecarts = []
        for k in range(1, len(df) + 1):
            D = scenarios.derouler(df.iloc[:k], brut, "ES", SEUILS)[-1]
            r = R[k - 1]
            cle = lambda x: (x["scenario_en_cours"], x["precision"], x["valide"], len(x["bascules"]),  # noqa: E731
                             [(z["nom"], z["fiche"]["etat"], z["role"]) for z in x["zones"]])
            if cle(D) != cle(r):
                ecarts.append(k - 1)
        check("[8] DIRECT = RETROSPECTIF barre a barre (%s)" % nom, not ecarts, ecarts[:5])

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
