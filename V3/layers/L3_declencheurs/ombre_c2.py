"""Les setups du brief OMBRE C2 — coureur (modèle `ombre16.py`).

Règle 15 de METHODE : un pré-enregistrement sans coureur est un
pré-enregistrement de rien — chaque setup ACTIVÉ ici tourne le soir même de
son activation, journal séparé `LOGS/entonnoir/ombre_c2_<jour>.jsonl`,
JAMAIS par la chaîne, aucun P&L avant N = 40 sur NQ, setup par setup.

Actifs : `C2_80PCT` (07/09 — la règle des 80 %, le trade MANUEL de Jackson)
et `C2_EOD` (08/09 — momentum de fin de journée, brief §2). NOTE DE
VÉRIFICATION exigée par le brief : le `h4` tagué exige SIX clôtures
consécutives dans la VA — écrit pour des barres de 5 min (2 × 30 min). La
définition F23 de l'acceptation est DEUX clôtures 15 min : elle est codée
ICI, le code tagué ne se touche pas.

Un setup ACTIF avec un seuil `null` dans `seuils_c2.yaml` REFUSE de tourner
(fail-loud, la convention L4) : un seuil se pose par sa distribution dans
`rapports/`, jamais par une valeur inventée.

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

from CORE.features import recalc                                   # noqa: E402
from CORE.research.hypothesis_runner import (                      # noqa: E402
    signaux_par_franchissement)

TICK = 0.25   # default ES/NQ. MGC=0,10 — hors perimetre du cycle.
MINUTE_EOD = 15 * 60 + 15   # ouverture 15h15 ET -> cloture 15h30 (DST : recalc)
CHEMIN_SEUILS = os.path.join(os.path.dirname(__file__), "seuils_c2.yaml")

# Ce que les setups ACTIFS lisent — une colonne perdue = un setup mort en
# silence pendant 60 jours (le piege ombre16, R1 de la review du 07/09).
COLONNES_C2 = ("ts", "jour", "open", "high", "low", "close",
               "dist_prev_vah", "dist_prev_val")

# Le registre COMPLET du brief (les familles #3 et #12 comptent pour 2 et 3
# setups journalisés). La parité avec OMBRE_C2.md est testée.
LES_C2 = ("C2_80PCT", "C2_EOD", "C2_VWAP_RET", "C2_SD1_RET", "C2_SWEEP_ON",
          "C2_POOR", "C2_DIV_DELTA", "C2_OPEN_DRIVE", "C2_ABS_1M",
          "C2_MUR_REJET", "C2_MUR_CASSE", "C2_PIN_0DTE",
          "C2_GAP", "C2_SINGLE", "C2_MIDI")

# nom -> date d'ombre. Un setup absent d'ici est pré-enregistré, pas couru —
# et DECISIONS.md porte la ligne. On n'active JAMAIS rétroactivement.
ACTIFS = {"C2_80PCT": "20260907", "C2_EOD": "20260908"}


def charger_seuils():
    import yaml
    with open(CHEMIN_SEUILS, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def verifier_seuils():
    """Fail-loud AVANT toute écriture (review 08/09, R2) : un setup ACTIF au
    seuil manquant doit tuer le rejeu AVANT la troncature des journaux —
    jamais après ES et avant NQ, où l'entonnoir officiel PARTIEL passerait
    pour un jour couru (« vide = couru muet »). `campagne.courir` l'appelle
    en tout premier."""
    s = charger_seuils()
    if "C2_EOD" in ACTIFS:
        for sym in ("ES", "NQ"):
            if (((s.get("C2_EOD") or {}).get("r_min") or {}).get(sym)) is None:
                raise ValueError("C2_EOD actif sans r_min %s — poser la"
                                 " distribution dans seuils_c2.yaml" % sym)


def _col(df, nom):
    """Colonne numérique, None si absente — le setup rend alors le jour muet
    au lieu de crasher, et `journaliser` REND l'absence (jamais avalée)."""
    return pd.to_numeric(df[nom], errors="coerce") if nom in df.columns else None


def _c2_80pct(df, sym, s):
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


def _c2_eod(df, sym, s):
    """Momentum de fin de journée — brief §2 (Baltussen et al., JFE 2021).

    Lieu : la barre 15h15-15h30 ET clôturée. `recalc.minutes_et` gère
    EDT/EST ICI, mais la garantie ne tient PAS de bout en bout (review
    08/09, R1) : `est_cash` amont est figé EDT (dette CONVENTIONS §2) et
    couperait la barre 20:15 UTC dès le 2/11 — motif `barre_eod_absente`
    FAUX chaque jour, open cash glissé à 8h30 ET, N plafonné sous 40.
    DEADLINE DURE 31/10 : réécrire `est_cash` sur `minutes_et` (tâche
    séparée, review + parité — DECISIONS + A_FAIRE). Réaction :
    |rendement_r| ≥ r_min,
    où rendement_r = (close(15h30) − open(9h30)) / range cash du même
    instant — provenance A pure ; l'écart au « ATR-jour » du brief est
    documenté dans `mesure_c2.py` et `seuils_c2.yaml`, les points bruts sont
    journalisés pour re-normalisation au jour 61. Side : le signe. Pas de
    cible prix : sortie HORAIRE 16h00 ET. Demi-séance : pas de barre 15h15 →
    ligne `jour_muet`, jamais un signal. Anti-fuite : `cummax`/`cummin`
    n'utilisent que les barres ≤ t, rien après la clôture 15h30 n'est lu."""
    r_min = ((s.get("C2_EOD") or {}).get("r_min") or {}).get(sym)
    if r_min is None:
        raise ValueError("C2_EOD actif sans r_min %s — poser la distribution"
                         " dans seuils_c2.yaml (fail-loud)" % sym)
    vide = pd.Series(False, index=df.index)
    ouv, clo = _col(df, "open"), _col(df, "close")
    haut, bas = _col(df, "high"), _col(df, "low")
    if any(x is None for x in (ouv, clo, haut, bas)):
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "colonne_absente"}
    mn = recalc.minutes_et(pd.to_datetime(df["ts"], unit="ms", utc=True))
    est_eod = pd.Series((mn == MINUTE_EOD).to_numpy(), index=df.index)
    rng = (haut.cummax() - bas.cummin())
    rend = (clo - float(ouv.iloc[0])) / rng.where(rng > 0)
    if not est_eod.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "barre_eod_absente"}
    lieu = est_eod & rend.notna()
    if not lieu.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "rendement_incalculable"}
    return {"short": (lieu & (rend <= -r_min), -1),
            "long": (lieu & (rend >= r_min), +1),
            "_lieu": lieu, "_cibles": {},
            "_extra": {"rendement_r": rend, "range_pts": rng},
            "_sortie": str((s.get("C2_EOD") or {}).get("sortie", "1600_ET"))}


SETUPS = {"C2_80PCT": _c2_80pct, "C2_EOD": _c2_eod}


def _extras(r, i):
    """Les colonnes `_extra` du setup, échantillonnées à la barre i — la
    re-coupe du jour 61 (autre r_min, autre normalisation) part de là."""
    out = {}
    for k, serie in (r.get("_extra") or {}).items():
        v = serie.iloc[i]
        out[k] = None if pd.isna(v) else round(float(v), 4)
    return out


def journaliser(df, sym, jour, chemin):
    """Append : une ligne par signal, une par épisode de lieu sans réaction,
    une par jour muet motivé (`jour_muet` : barre absente, colonne perdue).
    Rend (n_signaux, n_lieux_muets, colonnes_absentes) — les absentes sont
    RENDUES, jamais avalées."""
    absentes = [c for c in COLONNES_C2 if c not in df.columns]
    if df.empty:                     # contrat autonome — l'appelant garde
        return 0, 0, absentes        # len>=6, mais pas de pari dessus
    seuils = charger_seuils()
    n_sig, n_muets = 0, 0
    with open(chemin, "a", encoding="utf-8") as fh:
        for nom in ACTIFS:
            r = SETUPS[nom](df, sym, seuils)
            if r.get("_muet_jour"):
                # le jour n'a pas pu etre evalue — la raison doit se voir,
                # sinon « rien dans le journal » = « rien a signaler », faux.
                fh.write(json.dumps({
                    "ts": int(df["ts"].iloc[0]), "sym": sym, "setup": nom,
                    "motif": "jour_muet:%s" % r["_muet_jour"], "jour": jour,
                }, ensure_ascii=False) + "\n")
                n_muets += 1
                continue
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
                    ligne = {
                        "snapshot_id": "C2:%s:%d:%s" % (
                            sym, i, "L" if side > 0 else "S"),
                        "ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                        "side": side, "jour": jour,
                        "cible_prix": cible if cible is None else float(cible),
                    }
                    if r.get("_sortie"):     # cible_prix None MOTIVE : horaire
                        ligne["sortie"] = r["_sortie"]
                    ligne.update(_extras(r, i))
                    fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                    n_sig += 1
            # le lieu qui n'a pas reagi — l'etage vide doit se voir
            reagit = (r["short"][0] | r["long"][0])
            muets = r["_lieu"] & ~reagit
            for i in signaux_par_franchissement(muets, df["jour"]):
                ligne = {"ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                         "motif": "lieu_sans_reaction", "jour": jour}
                ligne.update(_extras(r, i))
                fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                n_muets += 1
    return n_sig, n_muets, absentes
