"""REACTIONS — ce que le marché a FAIT à nos niveaux, décrit, jamais jugé.

    python -X utf8 V3/reactions.py [YYYYMMDD]

Écrit `LOGS/reactions/reactions_<jour>.jsonl` (hors dépôt, hors miroir) :
trois types de lignes — `entete`, `test` (une par test de niveau), et
`niveau_jour` (une par couple niveau × instrument, **TOUJOURS écrite, même à
zéro test**, avec le motif du zéro).

CE QUE CE FICHIER AJOUTE À `recit.py`, ET POURQUOI IL N'EST PAS UN TUYAU
------------------------------------------------------------------------
1. LE DENOMINATEUR. `f23.fiches` rend `[]` aussi bien pour « colonne absente »
   que pour « niveau jamais approché » (f23.py l.213). Sans `motif_zero`,
   soixante jours de silence se liraient « ce niveau ne marche pas ».
2. LA SYMETRIE. `f23._reaction_atr` ne mesure QUE l'excursion dans le sens du
   rejet : un niveau traversé rend une réaction faible, et rien ne dit de
   combien il a été traversé. Le biais directionnel est DANS le moteur — on
   l'équilibre ici par `exc_poursuite_*`, sans toucher f23.
3. LA DERIVE. `cur_*` bougent en séance ; c'est la mesure que la quarantaine
   F23 attend pour être levée — et la cause des 11 écarts qui rendent
   `recit.py` non publiable les 04 et 07/09.
4. LE TEMOIN. `vwap_d` est le plus testé de tous (6,2 tests/jour-instrument) et
   personne ne prétend que c'est un niveau : il sert de CONTROLE NEGATIF. Un
   niveau primaire qui ne s'en distingue pas n'est pas un niveau, c'est une
   heure.

Règle de lecture au jour 61 : `LECTURE_JOUR_61.md` (règles 19-28, écrites
AVANT la première ligne de données).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import f23                                    # noqa: E402
from V3 import calendrier                                        # noqa: E402
from V3.recit import _charger_session_entiere, _recompter        # noqa: E402

NIVEAUX_VERSION = "2026-09-08"
DOSSIER = "LOGS/reactions"
TICK = {"ES": 0.25, "NQ": 0.25}

AVERTISSEMENT = (
    "DESCRIPTION DE SESSION — MIA V3. Ce fichier dit ce que le marche a FAIT a "
    "des niveaux decides d'avance. Il ne dit JAMAIS ce qu'il aurait fallu "
    "faire. Aucun champ n'est un gain, un R, un tick de profit, un prix "
    "d'entree, de sortie ou un stop, et aucun n'en est deductible : il n'y a "
    "ici ni regle d'entree, ni regle de sortie, ni position. Toute phrase de la "
    "forme « on aurait du », « ca aurait fait », « ce niveau a marche » tiree "
    "de ces lignes est un contresens d'usage. Chaque ligne porte l'instant ou "
    "son contenu etait CONNU (ts_connu) : s'en servir avant, c'est fabriquer "
    "du futur. Lecture agregee au jour 61 seulement, jamais un episode isole. "
    "Le P&L reste ferme jusque-la.")

# LE REGISTRE — les autres listes en sont des SOUS-ENSEMBLES (jamais deux
# listes qui divergent) : barrieres.COLONNES_NIVEAUX (13) et recit.NIVEAUX (6).
# classe : primaire (le coeur) | secondaire (conditionnel/mobile) | temoin.
# fige : le niveau ne bouge pas de la session (contrat de verification b.7).
REGISTRE = {
    "dist_prev_vah": ("primaire", True), "dist_prev_val": ("primaire", True),
    "dist_prev_vpoc": ("primaire", True),
    "dist_pdh": ("primaire", True), "dist_pdl": ("primaire", True),
    # ovn_* : figes seulement APRES 9h30 ET — la nuit, ils DEVELOPPENT (un
    # nouveau plus haut deplace le niveau). Mesure : 1 ecart de 92,7 % sur
    # ES 03/09, en pleine nuit. `fige: False` jusqu'a ce que le conditionnel
    # horaire soit cable ; l'ecart devient alors une mesure du developpement.
    "dist_ovn_high": ("primaire", False), "dist_ovn_low": ("primaire", False),
    "dist_ib_high": ("secondaire", True), "dist_ib_low": ("secondaire", True),
    "dist_cur_vah": ("secondaire", False), "dist_cur_val": ("secondaire", False),
    "dist_cur_vpoc": ("secondaire", False),
    "dist_mq_call": ("secondaire", True), "dist_mq_put": ("secondaire", True),
    "dist_mq_hvl": ("secondaire", True),
    # Ajout Jackson 08/09 : sa seance du jour s'est jouee dans les bandes du
    # VWAP hebdo (73 % ES / 86 % NQ des barres cash dedans, zero au-dessus de
    # SD+1). La ligne centrale a sa colonne ; les BANDES SD1/SD2 n'en ont pas
    # (prix absolu seulement) — elles arrivent avec marges.py, pas ce soir.
    "dist_vwap_w": ("primaire", False),
    "dist_vwap_d": ("temoin", False),
}


def _excursions(df15, i, cote, ref, atr, k):
    """Les DEUX excursions, miroir l'une de l'autre. `cote`=+1 : teste par le
    dessous (niveau au-dessus). Rejet = le prix repart d'ou il venait ;
    poursuite = il va au-dela. Positives vers l'exterieur de leur cote."""
    if ref is None or not atr or atr <= 0:
        return None, None, None
    fin = min(i + k, len(df15) - 1)
    if fin <= i:
        return None, None, None
    hauts = df15["high"].iloc[i + 1:fin + 1]
    bas = df15["low"].iloc[i + 1:fin + 1]
    if cote > 0:
        rejet, poursuite, extreme = ref - bas.min(), hauts.max() - ref, bas
    else:
        rejet, poursuite, extreme = hauts.max() - ref, ref - bas.min(), hauts
    idx = (extreme.idxmin() if cote > 0 else extreme.idxmax())
    return (round(float(rejet) / atr, 3), round(float(poursuite) / atr, 3),
            int(idx) - i)


def _derive(df15, col, i, i_connu, tick, atr):
    """De combien le niveau lui-meme a bouge entre le test et l'issue."""
    if not atr or atr <= 0 or col not in df15.columns:
        return None
    j = min(i_connu, len(df15) - 1)
    a, b = f23._val(df15, col, i), f23._val(df15, col, j)
    if a is None or b is None:
        return None
    n_a = float(df15["close"].iloc[i]) + a * tick
    n_b = float(df15["close"].iloc[j]) + b * tick
    return round((n_b - n_a) / atr, 3)


def _ligne_test(fiche, df15, df1, sym, jour, col, tick):
    """La fiche f23 telle quelle, PLUS ce qui manque : symetrie, derive,
    censure, et le recomptage independant du volume au-dela."""
    classe, fige = REGISTRE[col]
    i, i_connu = fiche["i"], fiche["i_connu"]
    atr = f23._val(df15, "atr_barre", i)
    rej4, pour4, t_ext = _excursions(df15, i, fiche["cote"],
                                     fiche["niveau_prix"], atr, 4)
    rej8, pour8, _ = _excursions(df15, i, fiche["cote"],
                                 fiche["niveau_prix"], atr, 8)
    vol_f = fiche.get("volume_au_dela")
    rec = _recompter(df1, fiche) if fiche.get("ts_casse") else None
    vol_r = rec["vol"] if isinstance(rec, dict) else None
    ecart = (round(100.0 * abs(vol_f - vol_r) / max(vol_f, 1), 1)
             if vol_f and vol_r is not None else None)
    delta, vol = fiche.get("delta_au_dela"), vol_f
    ligne = dict(fiche)
    ligne.update({
        "type": "test", "schema": "reactions/1", "jour": jour, "sym": sym,
        "niveaux_version": NIVEAUX_VERSION, "classe": classe, "fige": fige,
        "atr_barre": atr, "barres_restantes": len(df15) - 1 - i_connu,
        "ecart_touche_atr": (round(float(df15["close"].iloc[i]
                                          - fiche["niveau_prix"]) / atr, 3)
                             if fiche["niveau_prix"] and atr else None),
        "exc_rejet_atr_4": rej4, "exc_poursuite_atr_4": pour4,
        "exc_rejet_atr_8": rej8, "exc_poursuite_atr_8": pour8,
        "t_extreme_barres": t_ext,
        "derive_niveau_atr": _derive(df15, col, i, i_connu, tick, atr),
        # Le mot « piege » n'existe pas ici : ES 04/09 prev_vah, 200 538
        # contrats pour un delta de -534 (0,27 %) etait une ROTATION.
        "desequilibre_au_dela": (round(abs(delta) / vol, 4)
                                 if delta is not None and vol else None),
        "recompte_vol": vol_r, "ecart_vol_pct": ecart,
        "recompte_ok": (ecart is None or ecart <= 5.0),
    })
    return ligne


def _ligne_niveau_jour(df15, col, sym, jour, fiches, tick):
    """LE DENOMINATEUR : ecrite meme a zero test, avec le motif du zero."""
    classe, fige = REGISTRE[col]
    n = len(df15)
    present = col in df15.columns
    couv = (float(f23._num(df15[col]).notna().mean()) if present else 0.0)
    atr_ok = int(f23._num(df15["atr_barre"]).notna().sum()) if n else 0
    ecart = f23._ecart_atr(df15, col, tick) if present else None
    proches = (int((ecart.abs() <= 0.5).sum()) if ecart is not None else 0)
    issues = [f["issue"] for f in fiches]
    motif = None
    if not fiches:
        motif = ("colonne_absente" if not present else
                 "jamais_couverte" if couv == 0 else
                 "atr_indisponible" if atr_ok == 0 else "jamais_approche")
    return {
        "type": "niveau_jour", "schema": "reactions/1", "jour": jour,
        "sym": sym, "niveau": col, "classe": classe, "fige": fige,
        "niveaux_version": NIVEAUX_VERSION,
        "couverture_barres": round(couv, 3), "n_barres_atr_ok": atr_ok,
        "n_approches_05atr": proches, "n_tests": len(fiches),
        "n_tenu": issues.count("tenu"), "n_casse": issues.count("casse"),
        "n_regagne": issues.count("regagne"),
        "n_indetermine": sum(1 for x in issues
                             if x not in ("tenu", "casse", "regagne")),
        "n_censure": sum(1 for f in fiches
                         if len(df15) - 1 - f["i_connu"] < 8),
        "motif_zero": motif,
    }


def courir(jour):
    os.makedirs(DOSSIER, exist_ok=True)
    chemin = os.path.join(DOSSIER, "reactions_%s.jsonl" % jour)
    open(chemin, "w", encoding="utf-8").close()   # idempotent : jamais append
    lignes, entete, alertes = [], {}, 0
    for sym in ("ES", "NQ"):
        df15, df1 = _charger_session_entiere(sym, jour)
        if df15.empty:
            entete[sym] = {"n_barres_15m": 0}
            continue
        tick = TICK[sym]
        entete[sym] = {
            "n_barres_15m": len(df15),
            "ts_debut": int(df15["ts"].iloc[0]),
            "ts_fin": int(df15["ts"].iloc[-1]),
            "n_barres_atr_nan": int(f23._num(df15["atr_barre"]).isna().sum())}
        for col in REGISTRE:
            fs = f23.fiches(df15, df1, col, tick=tick)
            for f in fs:
                ligne = _ligne_test(f, df15, df1, sym, jour, col, tick)
                # Contrat corrige : un ecart de recomptage sur un niveau MOBILE
                # est attendu (il MESURE la derive) ; sur un niveau FIGE, c'est
                # un vrai desaccord et il arrete la publication.
                if REGISTRE[col][1] and not ligne["recompte_ok"]:
                    alertes += 1
                    print("  ECART %s %s %s : fiche %s vs recompte %s (%.1f %%)"
                          % (sym, col, ligne["ts"], ligne.get("volume_au_dela"),
                             ligne["recompte_vol"], ligne["ecart_vol_pct"]))
                lignes.append(ligne)
            lignes.append(_ligne_niveau_jour(df15, col, sym, jour, fs, tick))
    tete = {"type": "entete", "schema": "reactions/1", "jour": jour,
            "niveaux_version": NIVEAUX_VERSION,
            "ferie": calendrier.est_ferie(jour),
            "dow": pd.Timestamp(jour).day_name()[:3],
            "sym": entete, "avertissement": AVERTISSEMENT}
    with open(chemin, "w", encoding="utf-8") as fh:
        for o in [tete] + lignes:
            fh.write(json.dumps(o, ensure_ascii=False, default=float) + "\n")
    tests = sum(1 for o in lignes if o["type"] == "test")
    print("%s — %d tests, %d lignes niveau_jour, %d ecart(s) sur niveau fige"
          % (jour, tests, len(lignes) - tests, alertes))
    print("  -> %s" % chemin)
    return 1 if alertes else 0


def main():
    ap = argparse.ArgumentParser(description="Reactions aux niveaux — descriptif")
    ap.add_argument("jour", nargs="?", help="YYYYMMDD (defaut : aujourd'hui UTC)")
    a = ap.parse_args()
    jour = a.jour or pd.Timestamp.utcnow().strftime("%Y%m%d")
    return courir(jour)


if __name__ == "__main__":
    sys.exit(main())
