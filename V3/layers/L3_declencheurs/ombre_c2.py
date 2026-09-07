"""Les setups du brief OMBRE C2 — coureur (modèle `ombre16.py`).

Règle 15 de METHODE : un pré-enregistrement sans coureur est un
pré-enregistrement de rien — chaque setup ACTIVÉ ici tourne le soir même de
son activation, journal séparé `LOGS/entonnoir/ombre_c2_<jour>.jsonl`,
JAMAIS par la chaîne, aucun P&L avant N = 40 sur NQ, setup par setup.

Ce soir un seul actif : `C2_80PCT` (la règle des 80 %, le trade MANUEL de
Jackson du 07/09). NOTE DE VÉRIFICATION exigée par le brief : le `h4` tagué
exige SIX clôtures consécutives dans la VA — écrit pour des barres de
5 min (2 × 30 min). La définition F23 de l'acceptation est DEUX clôtures
15 min : elle est codée ICI, le code tagué ne se touche pas.

Le journal porte aussi les épisodes de LIEU SANS RÉACTION (`motif =
"lieu_sans_reaction"`, comptés par FRANCHISSEMENT — le brief dit « par
barre », l'épisode préserve l'indépendance du N) : l'entonnoir lieu →
régime → réaction doit être lisible par setup.

RÈGLE DE LECTURE (review 07/09, R2) : la première clôture dans la VA ne
peut jamais être une acceptation (il en faut deux) — chaque signal est donc
mécaniquement précédé d'un épisode muet. Au jour 61 : muets RÉELS =
muets journalisés − signaux.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.research.hypothesis_runner import (                      # noqa: E402
    signaux_par_franchissement)

TICK = 0.25   # default ES/NQ. MGC=0,10 — hors perimetre du cycle.

# Ce que les setups ACTIFS lisent — une colonne perdue = un setup mort en
# silence pendant 60 jours (le piege ombre16, R1 de la review du 07/09).
COLONNES_C2 = ("ts", "open", "close", "dist_prev_vah", "dist_prev_val")

# Le registre COMPLET du brief (les familles #3 et #12 comptent pour 2 et 3
# setups journalisés). La parité avec OMBRE_C2.md est testée.
LES_C2 = ("C2_80PCT", "C2_EOD", "C2_VWAP_RET", "C2_SD1_RET", "C2_SWEEP_ON",
          "C2_POOR", "C2_DIV_DELTA", "C2_OPEN_DRIVE", "C2_ABS_1M",
          "C2_MUR_REJET", "C2_MUR_CASSE", "C2_PIN_0DTE",
          "C2_GAP", "C2_SINGLE", "C2_MIDI")

# nom -> date d'ombre. Un setup absent d'ici est pré-enregistré, pas couru —
# et DECISIONS.md porte la ligne. On n'active JAMAIS rétroactivement.
ACTIFS = {"C2_80PCT": "20260907"}


def _c2_80pct(df):
    """Règle des 80 % (Dalton) — brief §1, définitions F23.

    Régime B5 : l'ouverture cash HORS de la VA veille (recalculé depuis
    l'open de la première barre cash vs les niveaux reconstruits — jamais le
    flag C++ `rule_80pct`). Lieu ET acceptation sur le MÊME prédicat : la VA
    reconstruite figée (S1 de la review — le brief lisait le flag C++
    `inside_prev_va` pour le lieu : deux définitions de « dedans », un
    désaccord d'un tick fragmentait l'épisode et gonflait N ; unifié sur la
    provenance A, l'écart est documenté ici). Réaction : DEUX clôtures
    15 min consécutives dans la VA. Side : vers le bord opposé (ouverture
    au-dessus → SHORT vers VAL ; miroir).

    Rend {"short": (cond, -1), "long": (cond, +1), "_lieu": cond_lieu,
    "_cibles": {...}} — le lieu sert aux lignes `lieu_sans_reaction`."""
    close = pd.to_numeric(df["close"], errors="coerce")
    vah = close + pd.to_numeric(df.get("dist_prev_vah"), errors="coerce") * TICK
    val = close + pd.to_numeric(df.get("dist_prev_val"), errors="coerce") * TICK
    # niveaux FIGÉS : la reconstruction est constante sur la journée, on
    # prend la première valeur finie — règle F23.
    vah_j = vah.dropna().iloc[0] if vah.notna().any() else None
    val_j = val.dropna().iloc[0] if val.notna().any() else None
    ouverture = pd.to_numeric(df["open"], errors="coerce").iloc[0]
    if vah_j is None or val_j is None or not pd.notna(ouverture):
        vide = pd.Series(False, index=df.index)
        return {"short": (vide, -1), "long": (vide, +1),
                "_lieu": vide, "_cibles": {}}
    dedans = (close >= val_j) & (close <= vah_j)
    acceptation = dedans & dedans.shift(1, fill_value=False)
    return {
        "short": (acceptation & (ouverture > vah_j), -1),
        "long": (acceptation & (ouverture < val_j), +1),
        "_lieu": dedans & ((ouverture > vah_j) | (ouverture < val_j)),
        "_cibles": {-1: val_j, +1: vah_j},   # le bord opposé (B-NAT de L5)
    }


SETUPS = {"C2_80PCT": _c2_80pct}


def journaliser(df, sym, jour, chemin):
    """Append : une ligne par signal, une par épisode de lieu sans réaction.
    Rend (n_signaux, n_lieux_muets, colonnes_absentes) — les absentes sont
    RENDUES, jamais avalées."""
    absentes = [c for c in COLONNES_C2 if c not in df.columns]
    n_sig, n_muets = 0, 0
    with open(chemin, "a", encoding="utf-8") as fh:
        for nom in ACTIFS:
            r = SETUPS[nom](df)
            vus = set()
            for cote in ("short", "long"):
                cond, side = r[cote]
                for i in signaux_par_franchissement(cond, df["jour"]):
                    if (i, side) in vus:
                        continue
                    vus.add((i, side))
                    cible = r["_cibles"].get(side)
                    # PREFIXE, jamais suffixe (R4) : un reducteur `[:3]`
                    # rendrait "SYM:i:sens" = l'id OFFICIEL de la meme barre.
                    fh.write(json.dumps({
                        "snapshot_id": "C2:%s:%d:%s" % (
                            sym, i, "L" if side > 0 else "S"),
                        "ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                        "side": side, "jour": jour,
                        "cible_prix": cible if cible is None else float(cible),
                    }, ensure_ascii=False) + "\n")
                    n_sig += 1
            # le lieu qui n'a pas reagi — l'etage vide doit se voir
            reagit = (r["short"][0] | r["long"][0])
            muets = r["_lieu"] & ~reagit
            for i in signaux_par_franchissement(muets, df["jour"]):
                fh.write(json.dumps({
                    "ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                    "motif": "lieu_sans_reaction", "jour": jour,
                }, ensure_ascii=False) + "\n")
                n_muets += 1
    return n_sig, n_muets, absentes
