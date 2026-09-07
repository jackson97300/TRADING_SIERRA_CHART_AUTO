"""Les colonnes `_r` dans l'agrégation — prérequis L4 J2 + brief OMBRE_C2 §3.

    python -X utf8 V3/tests/test_recalc_agg.py

ATTENDU, écrit avant la mesure : sur une journée réelle, le frame agrégé que
la campagne nourrit à la chaîne porte les colonnes recalculées exigées, et
chacune se REPROUVE : `cvd_sess_r` = cumul du `delta_bar` 1 min de la
session (17h ET → 17h ET) à la fin de chaque fenêtre, mismatch = 0 (jamais
`cvd_day`, qui repart de zéro au redémarrage) ; `finish_r` = (close−low)/
(high−low) de la BARRE AGRÉGÉE (jamais `finish_delta_pct`, qui lit la
dernière minute — VALIDATION_MISS 07/09) ; `vwap_slope_r` = (vwap_rth_r −
vwap_rth_r[-4]) / atr_barre ; `dist_vwap_rth_r` signée `niveau − close` en
ticks, la convention de toutes les `dist_*`.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min             # noqa: E402

JOUR, SYM = "20260903", "NQ"


def main():
    os.chdir(RACINE)
    df, brut = charger_jour(SYM, JOUR, 15, avec_1min=True)
    if df.empty:
        print("  journee %s indisponible — test impossible" % JOUR)
        return 1
    complet = pd.concat(chauffe_1min(SYM, JOUR) + [brut[COLS_RECALC]],
                        ignore_index=True)
    agg = injecter_recalculs(complet, df, minutes=15)

    echecs = []

    # 1. les colonnes existent et sont renseignees
    for c in ("rvol_r", "cvd_sess_r", "finish_r", "vwap_slope_r",
              "vwap_rth_r", "dist_vwap_rth_r"):
        if c not in agg.columns:
            echecs.append("%s ABSENTE de l'agregation" % c)
        elif agg[c].notna().sum() == 0:
            echecs.append("%s presente mais entierement NaN" % c)

    # 1b. finish_r se reprouve depuis l'OHLC de la barre AGREGEE
    if "finish_r" in agg.columns:
        rng = agg["high"] - agg["low"]
        att = ((agg["close"] - agg["low"]) / rng.where(rng > 0))
        ecarts = ((agg["finish_r"] - att).abs() > 1e-9) & att.notna()
        if int(ecarts.sum()):
            echecs.append("finish_r : %d barre(s) ne reproduisent pas "
                          "(close-low)/(high-low) de la barre agregee"
                          % int(ecarts.sum()))
        if bool((agg["finish_r"].notna() & (rng <= 0)).any()):
            echecs.append("finish_r : valeur inventee sur une barre plate")

    # 1c. vwap_slope_r se reprouve depuis vwap_rth_r et atr_barre, et les
    #     4 premieres barres sont des TROUS, jamais des zeros
    if {"vwap_slope_r", "vwap_rth_r", "atr_barre"} <= set(agg.columns):
        atr_b = pd.to_numeric(agg["atr_barre"], errors="coerce")
        att = ((agg["vwap_rth_r"] - agg["vwap_rth_r"].shift(4))
               / atr_b.where(atr_b > 0))
        ecarts = ((agg["vwap_slope_r"] - att).abs() > 1e-9) & att.notna()
        if int(ecarts.sum()):
            echecs.append("vwap_slope_r : %d barre(s) hors parite pente/ATR"
                          % int(ecarts.sum()))
        if agg["vwap_slope_r"].iloc[:4].notna().any():
            echecs.append("vwap_slope_r : renseignee avant 4 barres (zero "
                          "invente au lieu d'un trou)")

    # 1d. dist_vwap_rth_r : convention signee `niveau - close`, en ticks
    if {"dist_vwap_rth_r", "vwap_rth_r"} <= set(agg.columns):
        att = (agg["vwap_rth_r"] - agg["close"]) / 0.25
        ecarts = ((agg["dist_vwap_rth_r"] - att).abs() > 1e-6) & att.notna()
        if int(ecarts.sum()):
            echecs.append("dist_vwap_rth_r : %d barre(s) hors convention "
                          "(niveau - close)/tick" % int(ecarts.sum()))

    # 2. cvd_sess_r se reprouve depuis le 1 min : cumul du delta de la
    #    session jusqu'a la fin de chaque fenetre agregee
    if "cvd_sess_r" in agg.columns:
        b = brut.copy()
        b["dt"] = pd.to_datetime(b["ts"], unit="ms", utc=True)
        attendu = recalc.cumul_delta(b, recalc.session_sess(b["dt"]))
        fin_fenetre = {}
        for i in range(len(b)):
            # label left : la fenetre de la barre agregee `t` couvre
            # [t ; t + 15 min) — la barre 1 min appartient a sa fenetre
            fen = (b["ts"].iloc[i] // (15 * 60_000)) * (15 * 60_000)
            fin_fenetre[fen] = float(attendu.iloc[i])
        n_ecarts = 0
        for _, ligne in agg.iterrows():
            att = fin_fenetre.get(int(ligne["ts"]))
            lu = ligne["cvd_sess_r"]
            if att is None or pd.isna(lu):
                continue
            if abs(float(lu) - att) > 1e-6:
                n_ecarts += 1
        if n_ecarts:
            echecs.append("cvd_sess_r : %d fenetre(s) ne reproduisent pas le "
                          "cumul 1 min de la session" % n_ecarts)

    print("  recalc dans l'agregation — rvol_r, cvd_sess_r, finish_r,"
          " vwap_slope_r,\n       dist_vwap_rth_r — journee %s %s"
          % (JOUR, SYM))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    print("  OK : chaque colonne recalculee de l'agregation se REPROUVE — "
          "cvd depuis\n       le 1 min, finish sur la barre AGREGEE, pente "
          "en ATR, dist signee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
