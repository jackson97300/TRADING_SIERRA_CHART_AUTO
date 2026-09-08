"""MARGES — de combien une condition a manqué. Jamais ce qui serait arrivé.

    python -X utf8 V3/marges.py [YYYYMMDD]

Écrit `LOGS/marges/marges_<jour>.jsonl` (hors dépôt, hors miroir).

POURQUOI CE FICHIER EXISTE
--------------------------
La campagne compte ce qui TIRE. Projection mesurée : C2_EOD ~83 signaux sur
60 j × 2 (exploitable), C2_DIV_DELTA ~23 (inexploitable — le sort de H3 en
juillet, « positive mais N=28 »). Personne ne compte ce qui a FAILLI tirer.
Une ligne par jour-instrument-setup, MÊME LES JOURS MUETS, fait passer le
dénominateur de ~23 à 360 : c'est la PUISSANCE (ai-je un échantillon ?),
jamais l'EDGE (est-ce rentable ?). Les deux questions sont séparées, et les
confondre est le mécanisme exact de l'incident du 28/04.

CE QUE CE FICHIER NE FERA JAMAIS
--------------------------------
Aucun devenir. Pas de gain, pas de R, pas de prix d'entrée, de sortie ou de
stop, et rien dont on puisse les déduire. La seule phrase autorisée au jour
61 a la forme « à seuil × k, N passerait de A à B ». Règles 29-32 de
`LECTURE_JOUR_61.md`, écrites AVANT la première ligne de donnée.

PÉRIMÈTRE : C2_EOD (arbitrage Fable). Sa marge est lisible telle quelle —
`_extra["rendement_r"]` et `r_min` du YAML, vérifiés. Les deux autres setups
ont leur ligne `setup_jour` (le dénominateur existe dès le jour 1) sans
marge : 80PCT est prêt à être branché sans toucher au setup (mesuré :
`_cibles` porte val_j/vah_j, `_extra` porte la longueur de run) ; DIV_DELTA
calcule sa distance puis la JETTE hors seuil — sa marge exige un arbitrage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from V3 import calendrier                                       # noqa: E402
from V3.layers.L3_declencheurs.ombre_c2 import (ACTIFS, SETUPS,  # noqa: E402
                                                charger_seuils)

MARGES_VERSION = "2026-09-09"
DOSSIER = "LOGS/marges"
ENV = {"python": "%d.%d.%d" % sys.version_info[:3], "pandas": pd.__version__}

# Grille GELEE avant toute donnee, sur la marge RELATIVE au seuil : la seule
# unite ou une cellule veut dire la meme chose pour ES et pour NQ. Les bornes
# negatives sont les « x k » qu'une variante du cycle 2 pourrait prendre ; les
# positives sont le CONTROLE SYMETRIQUE, sans lequel la lecture est unilaterale.
TRANCHES = ((1.00, "≥+1.00"), (0.25, "[+0.25;+1.00)"), (0.00, "[0;+0.25)"),
            (-0.10, "[-0.10;0)"), (-0.25, "[-0.25;-0.10)"),
            (-0.50, "[-0.50;-0.25)"), (float("-inf"), "<-0.50"))

# Les cles que chaque setup DOIT rendre. Une clef manquante = signature
# changee = on le dit et on sort en 1, jamais des marges a null en silence.
ATTENDU = {"C2_EOD": ("rendement_r", "rend_pts", "range_pts")}

AVERTISSEMENT = (
    "DISTANCE AU DECLENCHEMENT — MIA V3. Ce fichier compte DE COMBIEN une "
    "condition a manque. Il ne dit JAMAIS ce que le marche a fait ensuite. "
    "Aucun champ n'est un gain, un R, un prix d'entree, de sortie ou un stop, "
    "et aucun n'en est deductible : il n'y a ici ni regle d'entree, ni regle "
    "de sortie, ni position, ni devenir d'aucune sorte. La seule phrase "
    "autorisee au jour 61 a la forme « a seuil x k, N passerait de A a B ». "
    "La phrase « ces episodes manques auraient rapporte X » est le "
    "contrefactuel INTERDIT (incident du 28/04 : audit annoncant +14-19pp, "
    "5/5 NOGO en walk-forward). Ce journal mesure la PUISSANCE, jamais "
    "l'EDGE. Aucune ligne d'ici ne peut justifier de deplacer un seuil "
    "pendant la campagne.")


def _tranche(m_rel):
    if m_rel is None:
        return None
    for borne, nom in TRANCHES:
        if m_rel >= borne:
            return nom
    return TRANCHES[-1][1]


def _heure_et(ts):
    dt = pd.Series([pd.Timestamp(int(ts), unit="ms", tz="UTC")])
    return "%02d:%02d" % divmod(int(recalc.minutes_et(dt).iloc[0]), 60)


def _marges_eod(r, df, sym, seuils, jour):
    """C2_EOD : une condition, |rendement_r| >= r_min. La grandeur est DEJA
    dans `_extra` — on la lit, on ne la recalcule pas (le setup est gele)."""
    extra = r.get("_extra") or {}
    manquantes = [c for c in ATTENDU["C2_EOD"] if c not in extra]
    if manquantes:
        return [], "signature_inattendue:%s" % ",".join(manquantes)
    r_min = float(seuils["C2_EOD"]["r_min"][sym])
    lieu = r.get("_lieu")
    rend = pd.to_numeric(extra["rendement_r"], errors="coerce")
    reagit = (r["short"][0] | r["long"][0]) if r.get("short") else None
    lignes = []
    for i in np.flatnonzero(np.asarray(lieu.fillna(False), dtype=bool)):
        x = rend.iloc[i]
        if pd.isna(x):
            continue
        m = abs(float(x)) - r_min
        declenche = bool(reagit.iloc[i]) if reagit is not None else None
        lignes.append({
            "type": "marge", "setup": "C2_EOD", "condition": "eod_reaction",
            "role": "reaction", "ts": int(df["ts"].iloc[i]),
            "heure_et": _heure_et(df["ts"].iloc[i]), "barre_i": int(i),
            "x_natif": round(abs(float(x)), 4), "seuil_natif": r_min,
            "unite": "r", "seuil_source": "yaml", "marge": round(m, 4),
            "marge_rel": round(m / r_min, 4), "marge_type": "continue",
            "etat": ("LIEU_REAGI" if declenche else
                     "QUASI" if -0.50 <= m / r_min < 0 else
                     "LIEU_SANS_REACTION"),
            "tranche": _tranche(m / r_min), "declenche": declenche,
            # recopies pour re-normaliser au jour 61 SANS re-run (le yaml
            # documente l'ecart « range cash » vs « ATR-jour » du brief)
            "rend_pts": extra["rend_pts"].iloc[i]
            if hasattr(extra["rend_pts"], "iloc") else None,
            "range_pts": extra["range_pts"].iloc[i]
            if hasattr(extra["range_pts"], "iloc") else None})
    return lignes, None


def _ligne_setup_jour(setup, sym, jour, df, r, marges, motif, ferie):
    """LE DENOMINATEUR : ecrite meme a zero marge, avec le motif du zero.
    Sans elle, « pas de ligne » et « le setup n'a pas tourne » sont
    indiscernables — le piege que motif_zero ferme dans reactions.py."""
    lieu = r.get("_lieu") if r else None
    n_lieu = int(np.asarray(lieu.fillna(False), dtype=bool).sum()) if lieu is not None else 0
    reagit = (r["short"][0] | r["long"][0]) if r and r.get("short") else None
    muet = motif or (r or {}).get("_muet_jour")
    if not muet and not marges:
        muet = ("lieu_jamais_produit" if n_lieu == 0 else
                "hors_date_ombre" if jour < ACTIFS.get(setup, "99999999")
                else "marge_non_exposee")
    return {
        "type": "setup_jour", "setup": setup, "sym": sym,
        "date_ombre": ACTIFS.get(setup), "n_barres": int(len(df)),
        "n_lieu": n_lieu,
        "n_declenches": int(np.asarray(reagit.fillna(False), dtype=bool).sum())
        if reagit is not None else 0,
        "n_marges": len(marges), "motif_muet": muet, "ferie": ferie}


def courir(jour):
    os.chdir(RACINE)
    os.makedirs(DOSSIER, exist_ok=True)
    chemin = os.path.join(DOSSIER, "marges_%s.jsonl" % jour)
    open(chemin, "w", encoding="utf-8").close()   # idempotent : jamais append
    seuils = charger_seuils()
    ferie = calendrier.est_ferie(jour)
    lignes, entete, alertes = [], {}, 0
    for sym in ("ES", "NQ"):
        df = charger_jour(sym, jour, 15)
        if df.empty:
            entete[sym] = {"n_barres": 0}
            for setup in ACTIFS:
                lignes.append({"type": "setup_jour", "setup": setup,
                               "sym": sym, "n_barres": 0, "n_lieu": 0,
                               "n_marges": 0, "motif_muet": "jour_sans_donnee",
                               "date_ombre": ACTIFS.get(setup), "ferie": ferie})
            continue
        recalc.ts_plage(df["ts"])        # invariant d'unite, fail-loud
        entete[sym] = {"n_barres": int(len(df)),
                       "ts_debut": int(df["ts"].iloc[0]),
                       "ts_fin": int(df["ts"].iloc[-1])}
        for setup in ACTIFS:
            if jour < ACTIFS[setup]:
                lignes.append(_ligne_setup_jour(setup, sym, jour, df, None, [],
                                                "hors_date_ombre", ferie))
                continue
            r = SETUPS[setup](df, sym, seuils)
            m, motif = ((_marges_eod(r, df, sym, seuils, jour))
                        if setup == "C2_EOD" else ([], "marge_non_exposee"))
            if motif and motif.startswith("signature_inattendue"):
                alertes += 1
                print("  %s %s : %s — marges NULLES, pas un marche calme"
                      % (sym, setup, motif))
            for x in m:
                x.update({"schema": "marges/1", "jour": jour, "sym": sym,
                          "marges_version": MARGES_VERSION})
            lignes.extend(m)
            lignes.append(_ligne_setup_jour(setup, sym, jour, df, r, m,
                                            motif, ferie))
    for o in lignes:
        o.setdefault("schema", "marges/1")
        o.setdefault("jour", jour)
        o.setdefault("marges_version", MARGES_VERSION)
    tete = {"type": "entete", "schema": "marges/1", "jour": jour,
            "marges_version": MARGES_VERSION, "env": ENV, "ferie": ferie,
            "dow": pd.Timestamp(jour).day_name()[:3], "sym": entete,
            "setups": dict(ACTIFS),
            "tranches_declarees": [n for _, n in TRANCHES],
            "avertissement": AVERTISSEMENT}
    with open(chemin, "w", encoding="utf-8") as fh:
        for o in [tete] + lignes:
            fh.write(json.dumps(o, ensure_ascii=False, default=float) + "\n")
    n_m = sum(1 for o in lignes if o["type"] == "marge")
    print("%s — %d marges, %d lignes setup_jour (le denominateur), %d alerte(s)"
          % (jour, n_m, len(lignes) - n_m, alertes))
    print("  -> %s" % chemin)
    return 1 if alertes else 0


def main():
    ap = argparse.ArgumentParser(description="Distance au declenchement")
    ap.add_argument("jour", nargs="?", help="YYYYMMDD (defaut : aujourd'hui)")
    a = ap.parse_args()
    return courir(a.jour or pd.Timestamp.utcnow().strftime("%Y%m%d"))


if __name__ == "__main__":
    sys.exit(main())
