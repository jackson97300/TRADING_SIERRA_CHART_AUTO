"""LA CONVENTION DE SIGNE DES `dist_*` — celle qui a retourne B1p le 14/09.

    python -X utf8 V3/tests/test_convention_signe.py

CE QUI S'EST PASSE. `lecture.lire` a recu une cle `d_vwap_w` construite par
`dist_vwap_w x 0,25 / atr_ref`, sans negation. Or la convention du depot est
`dist_X = (X - prix) / tick` : un prix AU-DESSUS du niveau rend un nombre
NEGATIF. B1p a donc dit SHORT quand le prix etait au-dessus de sa VWAP semaine,
sur 100 % des barres — et la couche a tourne une demi-journee dans cet etat.

POURQUOI AUCUN CONTROLE NE L'A VU. La verification ecrite le meme matin
comparait la distribution de `|dist_vwap_w|` en ATR a celle publiee le 07/09 :
mediane 2,28 contre 2,13 sur ES. Une VALEUR ABSOLUE. Un controle d'amplitude
ne peut pas voir une direction. C'est la faute que
`test_biais._signe_change_le_verdict` existe pour interdire un etage plus haut,
commise a l'etage d'en dessous — donc le test le plus important ici n'est pas
sur `d_vwap_w` : c'est le BALAYAGE de toutes les colonnes `dist_*`, pour que la
prochaine conversion ne puisse plus etre ecrite a l'aveugle.

CE QUE CE FICHIER N'EST PAS. Il ne lit aucun devenir, n'ouvre aucun journal, ne
calcule aucune barriere. Il compare des colonnes d'entree entre elles.
"""
from __future__ import annotations

import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
os.chdir(RACINE)

import pandas as pd                                              # noqa: E402

from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs   # noqa: E402
from V3 import lecture                                           # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min, jours_disponibles  # noqa: E402

PASSED = FAILED = 0

# Les distances dont un NIVEAU jumeau existe dans le frame : seules celles-la
# permettent de trancher le signe sans rien supposer.
JUMEAUX = (("dist_vwap_w", "vwap_w"), ("dist_vwap_d", "vwap_d"),
           ("dist_vwap_m", "vwap_m"), ("dist_pdh", "pdh"), ("dist_pdl", "pdl"),
           ("dist_prev_vah", "prev_vah"), ("dist_prev_val", "prev_val"),
           ("dist_prev_vpoc", "prev_vpoc"), ("dist_cur_vah", "cur_vah"),
           ("dist_cur_val", "cur_val"), ("dist_sess_high", "sess_high"),
           ("dist_sess_low", "sess_low"), ("dist_ib_high", "ib_high"),
           ("dist_ib_low", "ib_low"), ("dist_ovn_high", "ovn_high"),
           ("dist_ovn_low", "ovn_low"))

# Tolerance : le niveau et la cloture peuvent etre EGAUX sur quelques barres,
# et « close > niveau » est alors faux des deux cotes sans que la convention
# soit en cause. On exige donc une quasi-unanimite, pas une unanimite.
PART_MIN = 0.98


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-74s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def _un_jour(sym):
    """Le dernier jour du lot qui porte a la fois le brut et les recalculs."""
    for jour in reversed(jours_disponibles(sym)):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or brut.empty or "vwap_w" not in brut.columns:
            continue
        if not all(c in brut.columns for c in COLS_RECALC):
            continue
        return jour, df, brut
    return None, None, None


def _balayage(sym, brut):
    """Pour chaque distance a niveau jumeau : « close > niveau » coincide-t-il
    avec « dist > 0 » ? La reponse doit etre NON partout — c'est la convention.
    Une colonne qui repondrait OUI serait une SECONDE convention, et le depot
    dit que c'est le cas normal : on la nomme au lieu de la supposer absente.
    """
    inversees, directes, absentes = [], [], []
    for dist, niveau in JUMEAUX:
        if dist not in brut.columns or niveau not in brut.columns:
            absentes.append(dist)
            continue
        sub = brut.dropna(subset=["close", dist, niveau])
        sub = sub[sub["close"] != sub[niveau]]
        if len(sub) < 50:
            absentes.append(dist)
            continue
        acc = float(((sub["close"] > sub[niveau]) == (sub[dist] > 0)).mean())
        (directes if acc >= PART_MIN else inversees if acc <= 1 - PART_MIN
         else absentes).append(dist)
    return inversees, directes, absentes


def main():
    for sym in ("ES", "NQ"):
        jour, df, brut = _un_jour(sym)
        print("\n[%s] jour %s" % (sym, jour))
        if jour is None:
            check("[%s] un jour lisible existe — sinon ce test ne garde RIEN" % sym,
                  False, "aucun jour avec brut + vwap_w")
            continue

        # --- 1. la convention, sur toutes les distances a niveau jumeau -----
        inversees, directes, absentes = _balayage(sym, brut)
        check("[1a-%s] `dist_vwap_w` suit la convention INVERSEE du depot" % sym,
              "dist_vwap_w" in inversees,
              "inversees=%s directes=%s" % (inversees, directes))
        check("[1b-%s] AUCUNE distance ne suit la convention directe — si une"
              " apparait, la nommer avant de convertir" % sym,
              not directes, directes)
        check("[1c-%s] le balayage a vraiment mesure quelque chose" % sym,
              len(inversees) >= 8, "inversees=%d absentes=%s"
              % (len(inversees), absentes))

        # --- 2. ce que le LECTEUR rend, sur le vrai chemin ------------------
        prev = chauffe_1min(sym, jour)
        dfe = injecter_recalculs(
            pd.concat(prev + [brut[COLS_RECALC]], ignore_index=True), df,
            minutes=15)
        # ALIGNEMENT — mesure du 14/09 : la barre de 15 min porte la valeur de
        # sa DERNIERE minute (26 sur 26), pas de la premiere. La premiere
        # version de ce controle comparait a la minute d'OUVERTURE et rendait
        # 6 barres « a l'envers » sur NQ le 11/09, jour ou le prix oscillait
        # pile sur sa VWAP semaine (-0,98 a +0,91 ATR) : le cote basculait
        # DANS la barre. Le defaut etait dans le controle, pas dans le code.
        une_min = brut.dropna(subset=["close", "vwap_w", "ts"]).sort_values("ts")
        bien = mal = 0
        for i in range(len(dfe)):
            d = lecture.lire(dfe, i, sym=sym).get("d_vwap_w")
            t0 = int(dfe["ts"].iloc[i])
            f = une_min[(une_min["ts"] >= t0) & (une_min["ts"] < t0 + 900000)]
            if d is None or f.empty:
                continue
            r = f.iloc[-1]
            if float(r["close"]) == float(r["vwap_w"]):
                continue
            if (d > 0) == (float(r["close"]) > float(r["vwap_w"])):
                bien += 1
            else:
                mal += 1
        check("[2a-%s] `d_vwap_w` POSITIF veut dire prix AU-DESSUS de la VWAP"
              " semaine" % sym, mal == 0 and bien > 0,
              "%d barres correctes, %d a l'envers" % (bien, mal))
        check("[2b-%s] et le controle a vu assez de barres pour valoir" % sym,
              bien + mal >= 10, "%d barres confrontees" % (bien + mal))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
