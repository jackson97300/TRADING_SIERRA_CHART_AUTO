"""Les SEIZE setups d'edge_discovery en OMBRE — le coureur qui manquait.

Le pré-enregistrement (`DOCS/OMBRE_ED16.md`, 06/09, dépôt privé) promettait
« ils tournent dès le 08/09 » ; l'audit Fable du 07/09 a constaté qu'AUCUN
coureur ne les exécutait. Sans ce module, les seize auraient passé 60 jours
à N = 0 — un zéro de câblage manquant, lu comme de la rareté.

Ce qu'ils font, et ne font PAS :
  - leurs signaux se comptent par FRANCHISSEMENT (la fonction même des
    quatre) et s'écrivent dans un fichier SÉPARÉ de l'entonnoir officiel :
    `LOGS/entonnoir/ombre16_<jour>.jsonl` ;
  - ils ne passent JAMAIS par la chaîne : ils occuperaient la position
    virtuelle et fausseraient les compteurs du jour des QUATRE ;
  - aucun P&L, aucun devenir : ils accumulent du N, rien d'autre.
    Lecture : N = 40 sur NQ, PAR setup, jamais en groupe (une lecture
    combinée produirait des gagnants par combinatoire — la règle du
    pré-enregistrement).

La liste des seize visible au miroir : `OMBRE.md` de ce dossier, tenue en
parité avec `LES_SEIZE` par `test_spec_l3.py`.
"""

from __future__ import annotations

import json
import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.research.hypotheses_ed import LES_SEIZE, ed_setups      # noqa: E402
from CORE.research.hypothesis_runner import (                      # noqa: E402
    signaux_par_franchissement)

# Ce que les seize lisent et que l'agregation doit porter — verifie a chaque
# run : une colonne perdue = un setup silencieusement mort (le piege H2p/H8p,
# deja paye une fois).
COLONNES_SEIZE = ("dist_cur_vpoc", "dist_vwap_d", "dist_prev_vah",
                  "dist_mq_call", "dist_gex_nearest_up", "dist_gex_nearest_dn",
                  "dist_vwap_rth_sd2u_r", "dist_vwap_rth_sd2d_r", "rvol_r",
                  "delta_pct", "finish_delta_pct", "cvd_day_dir",
                  "vwap_slope_10", "inside_prev_va", "ib_broken_up",
                  "ib_broken_dn", "high", "low", "close", "atr_barre")


def signaux_seize(df):
    """{setup: [(i, side), ...]} par franchissement — même comptage que les
    quatre, aucun dédoublonnage inter-setups : chaque setup accumule SON N."""
    out = {}
    for nom, (cond, side) in ed_setups(df).items():
        out[nom] = [(int(i), int(side))
                    for i in signaux_par_franchissement(cond, df["jour"])]
    return out


def journaliser(df, sym, jour, chemin):
    """Append une ligne JSON par signal. Rend (n_signaux, colonnes_absentes).

    Les colonnes absentes sont RENDUES, jamais avalées : un setup qui ne
    peut pas lire son lieu doit se voir au premier run, pas au jour 61."""
    absentes = [c for c in COLONNES_SEIZE if c not in df.columns]
    n = 0
    with open(chemin, "a", encoding="utf-8") as fh:
        for nom, sigs in signaux_seize(df).items():
            for i, side in sigs:
                fh.write(json.dumps(
                    {"ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                     "side": side, "jour": jour}, ensure_ascii=False) + "\n")
                n += 1
    return n, absentes
