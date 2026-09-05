"""Les seize setups d'`edge_discovery_bot1.py`, portes pour le mode ombre.

Origine : `CORE/research/edge_discovery_bot1.py` (804 lignes, recu le 02/05/2026)
et son mode d'emploi `DOCS/PROMPT_EDGE_DISCOVERY.md`. Le fichier jumeau
`edge_discovery_bot2.py` est mort : il lit des parquets Databento, source
abandonnee.

PRINCIPE DU PORTAGE : garder l'INTENTION, corriger l'UNITE.
------------------------------------------------------------
Les seize setups sont des hypotheses formulees — c'est leur valeur, et elle est
reelle. Mais leurs seuils sont en **ticks absolus**, ce qui les rend
incomparables entre instruments. Mesure du 06/09 sur les 40 jours, barres 5 min :

    seuil du fichier          en ATR-5m ES     % barres ES    % barres NQ
    dist_prev_vah  < -500        18,5 ATR         0,8 %         13,7 %
    dist_cur_vpoc  < -300        11,1 ATR         1,0 %         17,8 %
    dist_cur_vpoc  abs< 100       3,7 ATR        78,4 %         34,2 %

Un facteur **17** entre ES et NQ sur le meme setup : ce ne sont pas deux mesures
du meme phenomene, ce sont deux setups differents sous un seul nom. Et « proche
du VPOC » (`abs< 100`) est vrai **78 % du temps sur ES** — une condition vraie
quatre fois sur cinq ne filtre rien.

Chaque seuil est donc retraduit en multiples d'ATR-5m, avec le plancher en ticks
de `hypotheses.seuil_ticks`. La table de conversion est explicite, setup par
setup, dans les docstrings. **Aucune valeur n'a ete choisie en regardant un
resultat** : les seize n'ont jamais tourne sur les donnees propres.

TROIS SUBSTITUTIONS, chacune motivee
-------------------------------------
    `range_pos`      -> `range_pos_r`, recalcule. La colonne livree est en
                        statut **C** : 15 % de nulls par jour.
    `rvol`           -> `rvol_r`. Le C++ initialise `f.rvol = 1.0f` et 1,0 est
                        une valeur valide : « normal mesure » et « jamais
                        calcule » y sont indistinguables (CONVENTIONS §3.1).
    `delta_bar`      -> `delta_pct`. Le delta brut depend du volume de la barre,
                        donc de l'heure et de l'instrument ; le ratio non.
    `finish_strength`-> `finish_delta_pct`, borne [0,1], statut A.

CE QUE CE MODULE N'EST PAS
---------------------------
Il n'est **pas** destine aux 40 jours de recherche. Ceux-ci ont deja recu trois
lectures ; une quatrieme sur seize setups produirait des gagnants par pure
combinatoire. Ces seize sont pour le **mode ombre**, sur les jours qui
s'ajoutent, ou ils accumulent du N sans consommer de regard sur le passe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from CORE.research.hypotheses import TICK, _f, seuil_ticks


# ---------------------------------------------------------------------------
# Traduction des seuils : ticks absolus -> multiples d'ATR-5m
# ---------------------------------------------------------------------------

def proche(df, tick=TICK):
    """« a » un niveau. Remplace `abs< 80` a `abs< 100` du fichier d'origine."""
    return seuil_ticks(df["atr5"], "P20", tick)          # max(0,20 ATR, 4 t)


def loin(df, n_atr, tick=TICK):
    """« loin de » un niveau, en multiples d'ATR-5m, rendu en TICKS."""
    return n_atr * pd.to_numeric(df["atr5"], errors="coerce") / tick


def range_pos_r(df):
    """Position dans le range de la seance, en %. Remplace `range_pos` (statut C).

    0 = au plus bas de la journee, 100 = au plus haut. Calculee sur les extremes
    courus depuis le debut de la journee — jamais sur les extremes finaux, qui
    seraient du look-ahead pur.
    """
    j = df["jour"].astype(str)
    h = _f(df, "high").groupby(j).cummax()
    b = _f(df, "low").groupby(j).cummin()
    etendue = (h - b).replace(0, np.nan)
    return 100.0 * (_f(df, "close") - b) / etendue


# ---------------------------------------------------------------------------
# Les seize
# ---------------------------------------------------------------------------

def _rvol(df):
    return _f(df, "rvol_r")


def ed_setups(df, tick=TICK):
    """Rend {nom: (condition, side)} pour les seize setups portes.

    Table de conversion appliquee, identique pour tous — l'intention du fichier
    d'origine est entre guillemets :

        « proche »   abs< 80..100 ticks   ->  abs <= max(0,20 ATR, 4 t)
        « loin »     < -150 ticks         ->  <= -0,5 ATR
                     < -300 ticks         ->  <= -1,0 ATR
                     < -500 ticks         ->  <= -1,5 ATR
                     > 100 ticks          ->  >=  1,0 ATR
        « delta+ »   delta_bar > 20..30   ->  delta_pct >= +0,10
        « delta- »   delta_bar < -20..-30 ->  delta_pct <= -0,10
        « finish faible »  finish_strength < -10  ->  finish_delta_pct < 0,4
    """
    p = proche(df, tick)
    rv = _rvol(df)
    dp = _f(df, "delta_pct")
    fin = _f(df, "finish_delta_pct")
    rp = range_pos_r(df)
    vpoc, vwd = _f(df, "dist_cur_vpoc"), _f(df, "dist_vwap_d")
    pvah = _f(df, "dist_prev_vah")
    j = df["jour"].astype(str)
    # 30 premieres minutes de RTH = les 6 premieres barres 5 min de la journee
    rang = df.groupby(j).cumcount()
    debut = rang < 6

    return {
        # --- Value area de la veille -------------------------------------
        "ED01_SELL_OPEN_ABOVE_PREV_VA": (
            (_f(df, "inside_prev_va") == 0) & (pvah <= -loin(df, 1.5, tick))
            & (_f(df, "cvd_day_dir") == 1) & debut, -1),
        "ED02_BUY_PREV_VA_RECLAIM": (
            (_f(df, "inside_prev_va") == 1) & (_f(df, "cvd_day_dir") == -1)
            & (vwd >= loin(df, 1.0, tick)) & (rv > 0.7), +1),
        # --- VPOC de session ----------------------------------------------
        "ED03_SELL_VPOC_FAR_ABOVE": (
            (vpoc <= -loin(df, 1.0, tick)) & (fin < 0.4) & (rv > 0.5), -1),
        "ED04_BUY_VPOC_RECLAIM": (
            (vpoc.abs() <= p) & (dp >= 0.10) & (rv > 0.8), +1),
        # --- GEX ------------------------------------------------------------
        "ED05_SELL_GEX_REJECTION": (
            (_f(df, "dist_gex_nearest_dn").abs() <= p) & (dp <= -0.10) & (rv > 0.6), -1),
        "ED06_BUY_GEX_SUPPORT": (
            (_f(df, "dist_gex_nearest_up").abs() <= p) & (dp >= 0.10) & (rv > 0.6), +1),
        # --- Mur d'options ---------------------------------------------------
        "ED07_SELL_MQ_CALL_WALL": (
            (_f(df, "dist_mq_call") <= -loin(df, 0.5, tick)) & (fin < 0.4), -1),
        # --- VWAP -------------------------------------------------------------
        "ED08_BUY_VWAP_RECLAIM_TREND": (
            (vwd.abs() <= p) & (_f(df, "vwap_slope_10") > 3) & (rv > 0.5), +1),
        # --- Divergences CVD ---------------------------------------------------
        "ED09_SELL_CVD_DIVERGENCE": (
            (_f(df, "cvd_day_dir") == -1) & (vwd <= -loin(df, 1.0, tick))
            & (rp > 70), -1),
        "ED10_BUY_CVD_DIVERGENCE": (
            (_f(df, "cvd_day_dir") == 1) & (vwd >= loin(df, 1.0, tick))
            & (rp < 30), +1),
        # --- Initial balance ----------------------------------------------------
        "ED11_SELL_IB_BREAK_DOWN": (
            (_f(df, "ib_broken_dn") == 1) & (dp <= -0.10) & (rv > 0.6), -1),
        "ED12_BUY_IB_BREAK_UP": (
            (_f(df, "ib_broken_up") == 1) & (dp >= 0.10) & (rv > 0.6), +1),
        # --- Extremes de range ---------------------------------------------------
        "ED13_BUY_EXTREME_LOW_RANGE": (
            (rp < 10) & (rv > 1.5) & (dp >= 0.10), +1),
        "ED14_SELL_EXTREME_HIGH_RANGE": (
            (rp > 90) & (rv > 1.5) & (dp <= -0.10), -1),
        # --- Bandes VWAP SD2 -------------------------------------------------------
        "ED15_SELL_VWAP_SD2_REJECTION": (
            (_f(df, "dist_vwap_rth_sd2u_r").abs() <= p) & (fin < 0.4) & (rv > 0.5), -1),
        "ED16_BUY_VWAP_SD2_SUPPORT": (
            (_f(df, "dist_vwap_rth_sd2d_r").abs() <= p) & (fin > 0.6) & (rv > 0.5), +1),
    }


LES_SEIZE = tuple(sorted([
    "ED01_SELL_OPEN_ABOVE_PREV_VA", "ED02_BUY_PREV_VA_RECLAIM",
    "ED03_SELL_VPOC_FAR_ABOVE", "ED04_BUY_VPOC_RECLAIM",
    "ED05_SELL_GEX_REJECTION", "ED06_BUY_GEX_SUPPORT",
    "ED07_SELL_MQ_CALL_WALL", "ED08_BUY_VWAP_RECLAIM_TREND",
    "ED09_SELL_CVD_DIVERGENCE", "ED10_BUY_CVD_DIVERGENCE",
    "ED11_SELL_IB_BREAK_DOWN", "ED12_BUY_IB_BREAK_UP",
    "ED13_BUY_EXTREME_LOW_RANGE", "ED14_SELL_EXTREME_HIGH_RANGE",
    "ED15_SELL_VWAP_SD2_REJECTION", "ED16_BUY_VWAP_SD2_SUPPORT",
]))

# Colonnes a charger en plus du socle du runner.
COLONNES_ED = ("inside_prev_va", "dist_prev_vah", "cvd_day_dir",
               "dist_gex_nearest_up", "dist_gex_nearest_dn", "vwap_slope_10",
               "dist_vwap_d", "ib_broken_dn")
