"""Le coureur des setups OMBRE C2 — registre, seuils, journal.

Règle 15 de METHODE : un pré-enregistrement sans coureur est un
pré-enregistrement de rien — chaque setup ACTIVÉ ici tourne le soir même de
son activation, journal séparé `LOGS/entonnoir/ombre_c2_<jour>.jsonl`,
JAMAIS par la chaîne, aucun P&L avant N = 40 sur NQ, setup par setup.

Actifs : `C2_80PCT` (07/09 — la règle des 80 %, le trade MANUEL de Jackson),
`C2_EOD` (08/09 — momentum de fin de journée, brief §2), `C2_DIV_DELTA`
(08/09 — divergence delta au niveau, brief §6). `C2_POOR` est PRÉ-CÂBLÉ
mais PAS ACTIF : sa v1 est morte par construction — 0 lieu sur 52 j × 2
(rapport lieu_poor), l'état 15 min ne persiste jamais les 3 barres exigées.
Redesign J+2 (mémoire d'épisode), jamais activé pour faire semblant : un
setup instructurable déclaré actif fabriquerait « testé, N=0 = rare »,
le mensonge exact que la règle 15 interdit. Les FONCTIONS vivent dans
`setups_c2.py` (scindé le 08/09, garde des 300 lignes — un concept par
fichier) ; ici le QUOI courir : registre, activation, seuils, journal.

Un setup ACTIF avec un seuil `null` dans `seuils_c2.yaml` REFUSE de tourner
(fail-loud, la convention L4) : un seuil se pose par sa distribution dans
`rapports/`, jamais par une valeur inventée.

Le journal porte aussi les épisodes de LIEU SANS RÉACTION (`motif =
"lieu_sans_reaction"`, comptés par FRANCHISSEMENT — le brief dit « par
barre », l'épisode préserve l'indépendance du N) : l'entonnoir lieu →
régime → réaction doit être lisible par setup.

RÈGLE DE LECTURE (review 07/09, R2) : la première clôture dans la VA ne
peut jamais être une acceptation (il en faut deux) — chaque signal 80PCT est
donc mécaniquement précédé d'un épisode muet. Au jour 61 : muets RÉELS =
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
from V3.layers.L3_declencheurs.setups_c2 import (                  # noqa: E402,F401
    MINUTE_EOD, SETUPS, TICK)   # re-export : mesure_c2 lit MINUTE_EOD ici

CHEMIN_SEUILS = os.path.join(os.path.dirname(__file__), "seuils_c2.yaml")

# Ce que les setups ACTIFS lisent — une colonne perdue = un setup mort en
# silence pendant 60 jours (le piege ombre16, R1 de la review du 07/09).
# ctx_poor_*/rvol_r y restent VOLONTAIREMENT malgre la non-activation de
# C2_POOR : surveiller le flux 60 jours pour que le redesign herite d'une
# colonne verifiee (review 08/09, suggestion 2 — assume, pas un oubli).
COLONNES_C2 = ("ts", "jour", "open", "high", "low", "close",
               "dist_prev_vah", "dist_prev_val", "dist_pdh", "dist_pdl",
               "dist_mq_call", "dist_mq_put", "vwap_rth_r",
               "cvd_sess_r", "atr_barre", "atr_ref", "atr_source",
               "ctx_poor_high", "ctx_poor_low", "rvol_r")

# Le registre COMPLET du brief (les familles #3 et #12 comptent pour 2 et 3
# setups journalisés). La parité avec OMBRE_C2.md est testée.
LES_C2 = ("C2_80PCT", "C2_EOD", "C2_VWAP_RET", "C2_SD1_RET", "C2_SWEEP_ON",
          "C2_POOR", "C2_DIV_DELTA", "C2_OPEN_DRIVE", "C2_ABS_1M",
          "C2_MUR_REJET", "C2_MUR_CASSE", "C2_PIN_0DTE",
          "C2_GAP", "C2_SINGLE", "C2_MIDI")

# nom -> date d'ombre. Un setup absent d'ici est pré-enregistré, pas couru —
# et DECISIONS.md porte la ligne. On n'active JAMAIS rétroactivement.
ACTIFS = {"C2_80PCT": "20260907", "C2_EOD": "20260908",
          "C2_DIV_DELTA": "20260908"}


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
    requis = {"C2_EOD": "r_min", "C2_POOR": "rvol_min"}
    for nom, cle in requis.items():
        if nom not in ACTIFS:
            continue
        for sym in ("ES", "NQ"):
            if (((s.get(nom) or {}).get(cle) or {}).get(sym)) is None:
                raise ValueError("%s actif sans %s %s — poser la distribution"
                                 " dans seuils_c2.yaml" % (nom, cle, sym))


def _extras(r, i):
    """Les colonnes `_extra` du setup, échantillonnées à la barre i — la
    re-coupe du jour 61 (autre r_min, autre normalisation) part de là."""
    out = {}
    for k, serie in (r.get("_extra") or {}).items():
        v = serie.iloc[i]
        if pd.isna(v):
            out[k] = None
        else:
            try:
                out[k] = round(float(v), 4)
            except (TypeError, ValueError):   # atr_source et autres textes
                out[k] = str(v)
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
            # « On n'active JAMAIS retroactivement » etait une docstring, pas
            # une ligne de code (audit 09/09) : 12 lignes sur 23 deja ecrites
            # HORS ombre — C2_EOD (ombre 08/09) avait des signaux les 03-04.
            # Un grep au jour 61 aurait franchi N>=40 avec du retroactif.
            if jour < ACTIFS[nom]:
                continue
            r = SETUPS[nom](df, sym, seuils)
            if r.get("_muet_jour"):
                # le jour n'a pas pu etre evalue — la raison doit se voir,
                # sinon « rien dans le journal » = « rien a signaler », faux.
                fh.write(json.dumps({
                    "ts": int(df["ts"].iloc[0]), "sym": sym, "setup": nom,
                    "motif": "jour_muet:%s" % r["_muet_jour"], "jour": jour,
                    "date_ombre": ACTIFS[nom],
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
                    if isinstance(cible, pd.Series):   # cible PAR BARRE
                        v = cible.iloc[i]
                        cible = None if pd.isna(v) else float(v)
                    # PREFIXE, jamais suffixe (R4) : un reducteur `[:3]`
                    # rendrait "SYM:i:sens" = l'id OFFICIEL de la meme barre.
                    ligne = {
                        "snapshot_id": "C2:%s:%d:%s" % (
                            sym, i, "L" if side > 0 else "S"),
                        "ts": int(df["ts"].iloc[i]), "sym": sym, "setup": nom,
                        "side": side, "jour": jour, "date_ombre": ACTIFS[nom],
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
                         "motif": "lieu_sans_reaction", "jour": jour,
                         "date_ombre": ACTIFS[nom]}
                ligne.update(_extras(r, i))
                fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                n_muets += 1
    return n_sig, n_muets, absentes
