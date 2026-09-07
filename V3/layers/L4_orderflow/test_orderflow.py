"""Tests L4 — SPEC §7 : 30 cas de vetos, série, anti-somme, anti-fuite,
glissement, forme, miroir V3, g1 par instrument.

    python -X utf8 V3/layers/L4_orderflow/test_orderflow.py

Le test au tick (deux journées, trois signaux lus à la main) appartient au
critère de scellement et viendra avec la mesure — pas ici.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.layers.L4_orderflow import confirmation, vetos as V   # noqa: E402
from V3 import lecture                                        # noqa: E402

# Seuils SYNTHETIQUES : les vetos sont des fonctions pures, on les teste avec
# des nombres ronds. Les seuils REELS sont testes a part (g1 par instrument).
S = {"k": None,
     "V1": {"a1": 0.462}, "V2": {"d1": 0.126}, "V3": {"g1": 100.0},
     "V4": {"vol_p99": 5000.0, "range_p95": 4.0},
     "V5": {"f1": None, "m1": None},
     "info": {"delta_vol_min": 0.3, "rvol_r_min": 2.0}}
V5_POSE = {"f1": 0.4, "m1": 0.6}          # pour tester V5 comme fonction pure


def _frame(barres):
    """Un frame 1 min synthétique. `barres` : liste de dicts partiels."""
    defauts = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
               "total_vol": 1000.0, "delta_bar": 0.0, "ask_pct": 0.5,
               "bid_pct": 0.5, "finish_delta_pct": 0.8,
               "max_big_ask_vol_in_bar": 10.0, "max_big_bid_vol_in_bar": 10.0}
    lignes = []
    for i, b in enumerate(barres):
        ligne = dict(defauts, **b)
        ligne["ts"] = 1_000_000 + i * 60_000
        ligne["jour"] = "2026-09-03"
        lignes.append(ligne)
    return pd.DataFrame(lignes)


def _lec(barres, k=None, sans=()):
    df = _frame(barres)
    for col in sans:
        df = df.drop(columns=[col])
    return lecture.lire_l4(df, 0, k or len(barres))


def main():
    e = []

    def cas(nom, obtenu, attendu):
        if obtenu is not attendu and obtenu != attendu:
            e.append("%-44s attendu %r, obtenu %r" % (nom, attendu, obtenu))

    # ------ 30 cas : 3 par veto x LONG/SHORT --------------------------------
    achats_faibles = _lec([{"ask_pct": 0.30, "bid_pct": 0.70}])
    achats_forts = _lec([{"ask_pct": 0.60, "bid_pct": 0.40}])
    sans_pct = _lec([{}], sans=("ask_pct", "bid_pct"))
    cas("V1 LONG personne n'achete -> True",
        V.v1_personne_n_achete(achats_faibles, +1, S["V1"]), True)
    cas("V1 LONG on achete -> False",
        V.v1_personne_n_achete(achats_forts, +1, S["V1"]), False)
    cas("V1 LONG colonne absente -> None",
        V.v1_personne_n_achete(sans_pct, +1, S["V1"]), None)
    cas("V1 SHORT personne ne vend -> True",
        V.v1_personne_n_achete(achats_forts, -1, S["V1"]), True)
    cas("V1 SHORT on vend -> False",
        V.v1_personne_n_achete(achats_faibles, -1, S["V1"]), False)
    cas("V1 SHORT colonne absente -> None",
        V.v1_personne_n_achete(sans_pct, -1, S["V1"]), None)

    contre = _lec([{"delta_bar": -200.0}])          # delta_k = -0.2
    avec = _lec([{"delta_bar": +200.0}])
    sans_delta = _lec([{}], sans=("delta_bar",))
    cas("V2 LONG flux contre -> True", V.v2_flux_contre(contre, +1, S["V2"]), True)
    cas("V2 LONG flux avec -> False", V.v2_flux_contre(avec, +1, S["V2"]), False)
    cas("V2 LONG delta absent -> None", V.v2_flux_contre(sans_delta, +1, S["V2"]), None)
    cas("V2 SHORT flux contre -> True", V.v2_flux_contre(avec, -1, S["V2"]), True)
    cas("V2 SHORT flux avec -> False", V.v2_flux_contre(contre, -1, S["V2"]), False)
    cas("V2 SHORT delta absent -> None", V.v2_flux_contre(sans_delta, -1, S["V2"]), None)

    print_bid = _lec([{"max_big_bid_vol_in_bar": 150.0}])
    print_ask = _lec([{"max_big_ask_vol_in_bar": 150.0}])
    petit = _lec([{}])
    sans_big = _lec([{}], sans=("max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar"))
    cas("V3 LONG print au BID -> True", V.v3_print_adverse(print_bid, +1, S["V3"]), True)
    cas("V3 LONG petits prints -> False", V.v3_print_adverse(petit, +1, S["V3"]), False)
    cas("V3 LONG colonne absente -> None", V.v3_print_adverse(sans_big, +1, S["V3"]), None)
    cas("V3 SHORT print au ASK -> True", V.v3_print_adverse(print_ask, -1, S["V3"]), True)
    cas("V3 SHORT petits prints -> False", V.v3_print_adverse(petit, -1, S["V3"]), False)
    cas("V3 SHORT colonne absente -> None", V.v3_print_adverse(sans_big, -1, S["V3"]), None)
    # le MIROIR du sens (revue du 07/09) : un print au ASK n'est PAS adverse a un LONG
    cas("V3 LONG print au ASK -> False (sens!)",
        V.v3_print_adverse(print_ask, +1, S["V3"]), False)

    climax_haut = _lec([{"total_vol": 6000.0, "high": 105.0, "low": 100.0,
                         "open": 100.5, "close": 100.8}])   # pos 0.16, contraire LONG
    calme = _lec([{}])
    sans_ohlc = _lec([{}], sans=("high",))
    cas("V4 LONG climax finish bas -> True", V.v4_epuisement(climax_haut, +1, S["V4"]), True)
    cas("V4 LONG fenetre calme -> False", V.v4_epuisement(calme, +1, S["V4"]), False)
    cas("V4 LONG OHLC absent -> None", V.v4_epuisement(sans_ohlc, +1, S["V4"]), None)
    climax_bas = _lec([{"total_vol": 6000.0, "high": 105.0, "low": 100.0,
                        "open": 104.5, "close": 104.2}])    # pos 0.84, contraire SHORT
    cas("V4 SHORT climax finish haut -> True", V.v4_epuisement(climax_bas, -1, S["V4"]), True)
    cas("V4 SHORT fenetre calme -> False", V.v4_epuisement(calme, -1, S["V4"]), False)
    cas("V4 SHORT OHLC absent -> None", V.v4_epuisement(sans_ohlc, -1, S["V4"]), None)

    renie = _lec([{"finish_delta_pct": 0.2, "high": 103.0, "low": 100.0,
                   "open": 100.2, "close": 100.4}])   # meche haute 2.6/3
    tenu = _lec([{"finish_delta_pct": 0.9, "high": 101.0, "low": 100.0,
                  "open": 100.1, "close": 100.9}])
    cas("V5 LONG reniement -> True", V.v5_reniement(renie, +1, V5_POSE), True)
    cas("V5 LONG tenue -> False", V.v5_reniement(tenu, +1, V5_POSE), False)
    cas("V5 LONG seuils null -> None", V.v5_reniement(renie, +1, S["V5"]), None)
    renie_s = _lec([{"finish_delta_pct": 0.8, "high": 103.0, "low": 100.0,
                     "open": 102.8, "close": 102.6}])  # meche basse + finish haut
    # la tenue d'un SHORT est le MIROIR : finish BAS (vendeurs concluent),
    # cloture pres du bas, meche basse courte — pas la meme barre qu'un LONG
    tenu_s = _lec([{"finish_delta_pct": 0.15, "high": 101.0, "low": 100.0,
                    "open": 100.9, "close": 100.1}])
    cas("V5 SHORT reniement -> True", V.v5_reniement(renie_s, -1, V5_POSE), True)
    cas("V5 SHORT tenue -> False", V.v5_reniement(tenu_s, -1, V5_POSE), False)
    cas("V5 SHORT seuils null -> None", V.v5_reniement(renie_s, -1, S["V5"]), None)

    # ------ la serie : UN motif, CINQ booleens ------------------------------
    b = _frame([{"ask_pct": 0.30, "bid_pct": 0.70, "delta_bar": -200.0,
                 "max_big_bid_vol_in_bar": 150.0}])
    r = confirmation.confirmer(b, 0, +1, S, k=1)
    if r["decision"] != "VETO" or r["motif"] != "V1":
        e.append("serie : motif attendu V1 (premier vrai), obtenu %s/%s"
                 % (r["decision"], r["motif"]))
    if len(r["vetos"]) != 5:
        e.append("serie : %d verdicts au lieu de 5 — l'attribution exige tous"
                 % len(r["vetos"]))
    if r["vetos"]["V2"] is not True or r["vetos"]["V3"] is not True:
        e.append("serie : V2/V3 doivent etre evalues MEME apres le motif V1")

    # ------ anti-somme : sur les TOKENS DE CODE, pas la prose ---------------
    # Les docstrings ont le droit de dire « jamais un score » ; le code n'a
    # pas le droit d'en calculer un.
    import tokenize
    for nom_f in ("confirmation.py", "vetos.py"):
        with open(os.path.join(os.path.dirname(__file__), nom_f),
                  encoding="utf-8") as fh:
            noms = {t.string for t in tokenize.generate_tokens(fh.readline)
                    if t.type == tokenize.NAME}
        for interdit in ("sum", "score", "count", "Counter"):
            if interdit in noms:
                e.append("anti-somme : identifiant « %s » dans %s — un compte "
                         "est un score" % (interdit, nom_f))

    # ------ anti-fuite : les barres APRES la confirmation ne comptent pas ---
    jour = [{"close": 100.0 + i * 0.1} for i in range(10)]
    avant = confirmation.confirmer(_frame(jour), 2, +1, S, k=2)
    apres_mod = list(jour)
    for i in range(4, 10):                       # tout ce qui suit la fenetre
        apres_mod[i] = {"close": 500.0, "delta_bar": -9999.0,
                        "total_vol": 99999.0, "ask_pct": 0.01}
    apres = confirmation.confirmer(_frame(apres_mod), 2, +1, S, k=2)
    if (avant["decision"] != apres["decision"]
            or avant["prix_entree_l4"] != apres["prix_entree_l4"]
            or avant["vetos"] != apres["vetos"]
            or avant["glissement_atr"] != apres["glissement_atr"]):
        e.append("ANTI-FUITE : modifier les barres apres la confirmation a "
                 "change la decision, un veto, le prix ou le glissement")

    # ------ glissement : LONG, open 100, confirmation 102, ATR 10 -> +0,2 ---
    g = confirmation.confirmer(
        _frame([{"open": 100.0, "close": 101.0}, {"close": 102.0}]),
        0, +1, S, k=2, atr=10.0)
    if g["glissement_atr"] is None or abs(g["glissement_atr"] - 0.2) > 1e-9:
        e.append("glissement : attendu +0,2, obtenu %r" % g["glissement_atr"])

    # ------ forme : signe oppose -> verdict different -----------------------
    vendeur = _frame([{"ask_pct": 0.30, "bid_pct": 0.70, "delta_bar": -200.0}])
    long_ = confirmation.confirmer(vendeur, 0, +1, S, k=1)
    short_ = confirmation.confirmer(vendeur, 0, -1, S, k=1)
    if long_["decision"] == short_["decision"]:
        e.append("forme : un flux vendeur doit veto le LONG et pas le SHORT "
                 "(obtenu %s / %s)" % (long_["decision"], short_["decision"]))

    # ------ l'absorption ne decide JAMAIS -----------------------------------
    gros_delta = _frame([{"delta_bar": 400.0}])
    sans_abs = confirmation.confirmer(gros_delta, 0, +1, S, k=1, rvol_r=None)
    avec_abs = confirmation.confirmer(gros_delta, 0, +1, S, k=1, rvol_r=5.0)
    if sans_abs["decision"] != avec_abs["decision"]:
        e.append("absorption : l'info a change la decision — interdit")
    if avec_abs["info"]["absorption_sens"] != 1:
        e.append("absorption : sens attendu +1, obtenu %r"
                 % avec_abs["info"]["absorption_sens"])

    # ------ fenetre absente -> INDISPONIBLE ---------------------------------
    trop_court = confirmation.confirmer(_frame([{}]), 0, +1, S, k=3)
    if trop_court["decision"] != "INDISPONIBLE":
        e.append("fenetre absente : attendu INDISPONIBLE, obtenu %s"
                 % trop_court["decision"])

    # ------ fenetre TROUEE = trou, jamais un calcul partiel (R1) ------------
    troue = _frame([{"ask_pct": np.nan}, {"ask_pct": 0.60}])
    lec_troue = lecture.lire_l4(troue, 0, 2)
    if lec_troue["ask_pct_k"] is not None:
        e.append("fenetre trouee : ask_pct_k devrait etre None, obtenu %r — "
                 "un NaN cache fabrique un faux veto" % lec_troue["ask_pct_k"])
    troue_d = _frame([{"delta_bar": np.nan}, {"delta_bar": 0.0}])
    if lecture.lire_l4(troue_d, 0, 2)["delta_k"] is not None:
        e.append("fenetre trouee : delta_k devrait etre None — le flux "
                 "contraire cache par un NaN devenait un feu vert")

    # ------ la fenetre ne traverse pas la nuit (22:00 UTC, lu du ts) --------
    nuit = _frame([{}, {}])
    ts_2159 = int(pd.Timestamp("2026-09-03 21:59", tz="UTC").value // 1_000_000)
    nuit.loc[0, "ts"], nuit.loc[1, "ts"] = ts_2159, ts_2159 + 60_000
    if lecture.lire_l4(nuit, 0, 2) is not None:
        e.append("nuit : une fenetre 21:59->22:00 traverse la journee de "
                 "trading et devrait rendre None")

    # ------ strict : seul un trou de veto APPLIQUE rend indisponible --------
    s_strict = dict(S, modes={"V1": "observee", "V2": "observee",
                              "V3": "observee", "V4": "observee",
                              "V5": "observee"})
    r_obs = confirmation.confirmer(_frame([{}]), 0, +1, s_strict, k=1,
                                   strict=True)
    if r_obs["decision"] != "CONFIRME":       # V5 en trou mais observe
        e.append("strict : un trou de veto OBSERVE ne doit pas rendre "
                 "indisponible (obtenu %s)" % r_obs["decision"])
    s_app = dict(s_strict, modes=dict(s_strict["modes"], V5="appliquee"))
    r_app = confirmation.confirmer(_frame([{}]), 0, +1, s_app, k=1,
                                   strict=True)
    if r_app["decision"] != "INDISPONIBLE" or r_app["motif"] != "TROU_V5":
        e.append("strict : un trou de veto APPLIQUE doit rendre INDISPONIBLE "
                 "TROU_V5 (obtenu %s/%s)" % (r_app["decision"], r_app["motif"]))

    # ------ la regle dure du yaml : null + appliquee refuse de tourner ------
    try:
        s_reel = confirmation.charger_seuils("ES")
        if s_reel["modes"].get("V5") == "appliquee":
            e.append("yaml : V5 appliquee avec seuils null aurait du lever")
    except ValueError:
        e.append("yaml reel : charger_seuils ne doit PAS lever tant que tout "
                 "est observee")
    try:
        confirmation.charger_seuils("MGC")
        e.append("instrument inconnu : MGC devrait lever, pas se taire")
    except ValueError:
        pass

    # ------ g1 PAR INSTRUMENT, sur le yaml reel (SPEC §8) -------------------
    g_es = confirmation.charger_seuils("ES")["V3"].get("g1")
    g_nq = confirmation.charger_seuils("NQ")["V3"].get("g1")
    if g_es is None or g_nq is None or g_es == g_nq:
        e.append("g1 : ES (%r) et NQ (%r) doivent exister et differer "
                 "(rapport mesure 7,6)" % (g_es, g_nq))

    print("  L4 — 31 cas de vetos (5 x 3 x 2 sens + miroir V3), serie, "
          "anti-somme,\n       anti-fuite, glissement, forme, absorption, "
          "fenetres (absente, trouee,\n       nuit), strict par mode, regle "
          "dure du yaml, g1 par instrument")
    if e:
        print("  %d ECHEC(S) :" % len(e))
        for x in e:
            print("     %s" % x)
        return 1
    print("  OK : cinq vetos en SERIE — un seul droit, annuler ; rien ne "
          "renforce,\n       rien ne fuit, et le glissement se mesure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
