"""GENERE `V3/MANIFESTE_DONNEES.md` — le catalogue des donnees que V3 consomme.

    python -X utf8 V3/mesure_manifeste.py [jour]

POURQUOI IL EST GENERE ET NON ECRIT. Un catalogue tape a la main ment des la
premiere derive, et personne ne s'en apercoit. Chaque unite est donc DEDUITE
des valeurs reelles du frame, ou SOURCEE au producteur quand les valeurs seules
ne peuvent pas trancher.

CE QUE LA PREMIERE VERSION A RATE, ET LA LEÇON. Elle devinait l'unite de la
famille ATR en comparant chaque colonne a l'etendue mediane d'une barre de 15
minutes, et concluait triomphalement que `CLAUDE.md` avait tout faux. C'etait
l'inverse : `CLAUDE.md` a raison, `atr` est en POINTS et `atr_14m` en TICKS, et
le C++ le dit noir sur blanc (`DMP_Calc_ATR_14m` rend `atr_price / tick_size`).
L'heuristique comparait un ATR JOURNALIER a une barre de quinze minutes — deux
periodes sans rapport — et `atr_14m` (10,25 ticks) tombait par coincidence pres
de l'etendue en points (9,62). Une proximite de magnitude entre grandeurs de
periodes differentes ne prouve RIEN.

D'ou la regle de ce fichier : ce qui peut se deduire se deduit, ce qui ne le
peut pas se source au producteur — et `verifier_atr()` confronte les unites
declarees a un ATR RECALCULE depuis les barres brutes a chaque generation, pour
qu'une affirmation d'unite ne puisse plus vivre sans preuve.

SOURCES DE VERITE, dans cet ordre :
  1. le frame 15 min REELLEMENT produit par la chaine (`scenarios.charger`, qui
     passe par `injecter_recalculs`, chauffe vingt jours) — la seule liste qui
     compte : ce qui vit dans le brut 1 min et meurt a l'agregation n'y est pas ;
  2. `V3/config/families.yaml` — F1..F23, regles regex, PREMIERE qui matche ;
  3. `V3/config/features_provenance.csv` — A / B / C / N / R / S ;
  4. `V3/lecture_colonnes.py: SOURCES_DECLAREES` — les proxys refuses ;
  5. `V3/marges_quatre.py` — les colonnes que LES_QUATRE lisent vraiment (etoile).

CE QUE LA MESURE A CORRIGE PAR RAPPORT A LA DEMANDE. Les classes de provenance
ne sont PAS « A / B / A' / recalc / proxy » : la table en porte six, A, B, C, N,
R et S, et aucun A'. Le fichier les nomme telles qu'elles sont.
"""

from __future__ import annotations

import csv
import os
import re
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3 import lecture_colonnes                                  # noqa: E402
from V3.scenarios import lot, scenarios                          # noqa: E402

CONFIG = os.path.join(RACINE, "V3", "config")
SORTIE = os.path.join(RACINE, "V3", "MANIFESTE_DONNEES.md")
QUATRE = os.path.join(RACINE, "V3", "marges_quatre.py")

CLASSES = {"A": "reproduite en C++ et verifiee par IDENTITE",
           "B": "colonne C++ NON reproduite (plausibilite seulement)",
           "C": "metadonnee, fuite, ou trop peu de valeurs — ecartee",
           "N": "niveau de prix : entree de recalcul, pas une feature",
           "R": "evenement RARE (le taux d'activite est dans la table)",
           "S": "suspecte, a recalculer",
           "chaine": "produite par la CHAINE, pas par le C++ — absente de la table "
                     "DMP, et c'est normal : la table catalogue les colonnes du dumper"}

# LES UNITES SOURCEES — celles que les valeurs seules ne peuvent pas trancher.
# Chaque entree cite le fichier qui PRODUIT la colonne. Elles sont ici parce que
# la premiere version de ce manifeste les DEVINAIT : elle comparait chaque
# colonne `atr*` a l'etendue mediane d'une barre de 15 minutes et concluait que
# `CLAUDE.md` avait tout faux. C'etait l'inverse — `atr` est un ATR JOURNALIER,
# incomparable a une barre de quinze minutes, et `atr_14m` (10,25 TICKS)
# tombait par coincidence pres de l'etendue en POINTS (9,62).
# Une proximite de magnitude entre grandeurs de PERIODES DIFFERENTES ne prouve
# rien. `verifier_atr()` confronte ces declarations a un ATR recalcule depuis
# les barres brutes, a chaque generation.
UNITES_SOURCEES = {
    "atr": ("points", "ATR JOURNALIER, lu sur le chart daily de Sierra en PRIX "
                      "(`DMP_Reader.h`, `DMP_ReadDaily` -> `atr_daily`)"),
    "atr_14m": ("ticks", "ATR(14) sur barres 1 min : `DMP_Calc_ATR_14m` rend "
                         "`atr_price / tick_size` — le C++ le dit en toutes lettres"),
    "atr_barre": ("points", "ATR de la barre agregee 15 min, recalcule par la chaine"),
    "atr_veille": ("points", "ATR de la veille, meme famille qu'`atr_barre`"),
    "atr_ref": ("points", "= `atr_barre` si fini, sinon `atr_veille` ; `atr_source` dit lequel"),
    "atr_source": ("etiquette", "barre / veille / aucun"),
    # Sourcees le 11/09 apres l'episode ATR : elles tombaient dans le repli
    # « sans dimension », qui n'est pas une mesure mais une AFFIRMATION sans
    # preuve — la meme faute en plus petit. Le C++ les declare toutes.
    "vix_level": ("points d'indice", "« Prix courant du VIX » (`DMP_Reader.h`)"),
    "delta_bar": ("contrats (signe)", "« Delta barre (ask - bid volume) » (`DMP_Transform.h`)"),
    "cvd_day": ("contrats", "« CVD cumulatif journee » (`DMP_Transform.h`)"),
    "cvd_day_dir": ("signe -1 / 0 / +1", "« Direction CVD » (`DMP_Transform.h`)"),
    "cvd_session": ("contrats", "`cvd_day` moins le snapshot a l'ouverture RTH ; "
                                "INVALIDE hors RTH. A ne PAS confondre avec `cvd_sess_r`, "
                                "qui cumule depuis 17h ET — la nuit comprise"),
    "vwap_slope_10": ("points par barre", "« Pente VWAP 10 barres (pts/barre) » (`DMP_Transform.h`). "
                                          "PIEGE : `vwap_slope_r` est en ATR sur 4 barres — "
                                          "deux pentes, deux unites, deux fenetres"),
    "rvol": ("ratio", "« Volume relatif (1.0 = normal, >2.0 = spike) » (`DMP_Transform.h`)"),
    "rvol_zscore": ("ecarts-types", "« Z-Score volume » (`DMP_Transform.h`)"),
    "rvol_r": ("ratio", "volume de la barre / mediane de la MEME MINUTE de session sur "
                        "20 jours (`recalc.rvol`) ; 1,0 = volume habituel. Toujours positif"),
    "poc_migration_dir": ("signe -1 / 0 / +1", "sens de migration du POC (`DMP_Transform.h`)"),
}

BLOCS = (("VWAP et bandes", r"vwap"),
         ("Valeur : VA, VPOC, composite", r"(prev_v|cur_v|va_|vpoc|poc_|inside_prev)"),
         ("Initial Balance", r"^(ib_|dist_ib)"),
         ("Overnight, PDH / PDL", r"(ovn|pdh|pdl)"),
         ("Delta, CVD, flux d'ordres", r"(delta|cvd|ask|bid|big_|sweep|retest|rvol|total_vol)"),
         ("MenthorQ, GEX, 0DTE", r"(mq_|gex|gamma)"),
         ("VIX", r"vix"),
         ("ATR", r"^atr"),
         ("Barre courante et meches", r"(^bar_|^open$|^high$|^low$|^close$|finish)"),
         ("Contexte ctx_*", r"^ctx_"),
         ("Intermarket im_*", r"^im_"),
         ("Calendrier, news, session", r"(news|session|blocked|jour|minutes_reelles|^ts$)"),
         ("Technique et qualite", r"(window_version|barre_complete|data_quality|_source$)"))


def _regles():
    """Les regles de `families.yaml`, dans l'ordre — la premiere qui matche
    gagne. Lues en texte : le fichier est du YAML simple et une dependance de
    plus dans V3 devrait passer le manifeste des dependances."""
    out = []
    for ln in open(os.path.join(CONFIG, "families.yaml"), encoding="utf-8"):
        m = re.search(r'motif:\s*"([^"]+)".*?famille:\s*(F\d+)', ln)
        if m:
            out.append((re.compile(m.group(1)), m.group(2)))
    return out


def _noms_familles():
    out = {}
    for ln in open(os.path.join(CONFIG, "families.yaml"), encoding="utf-8"):
        m = re.match(r'\s*(F\d+):\s*\{nom:\s*"([^"]+)"', ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _provenances():
    with open(os.path.join(CONFIG, "features_provenance.csv"), encoding="utf-8") as f:
        return {r["colonne"]: (r["provenance"], r["motif"]) for r in csv.DictReader(f)}


def _etoiles(colonnes):
    """Les colonnes que LES_QUATRE lisent — citees dans `marges_quatre.py`."""
    src = open(QUATRE, encoding="utf-8").read()
    return {c for c in colonnes if re.search(r"\b%s\b" % re.escape(c), src)}


def _proxys():
    out = set()
    for cols in lecture_colonnes.SOURCES_DECLAREES.values():
        out |= set(cols)
    return out


def _unite(col, s, etendue_pts, tick):
    """L'unite : DEDUITE des valeurs quand elles suffisent, SOURCEE au
    producteur quand elles ne suffisent pas (famille ATR, cf UNITES_SOURCEES)."""
    v = pd.to_numeric(s, errors="coerce").dropna()
    if v.empty:
        return "—", "aucune valeur finie sur la journee mesuree"
    uniques = set(np.unique(v.values))
    if uniques <= {0.0, 1.0}:
        return "booleen", ""
    if col.startswith("dist_"):
        return "ticks", "convention `niveau = close + dist x tick` (CONVENTIONS §8)"
    # Unites SUES par le code, pas devinables des valeurs — chacune tracee a sa
    # source dans `hypothesis_runner.injecter_recalculs`.
    if col == "vwap_slope_r":
        return "ATR par 4 barres", "pente de `vwap_rth_r` sur 4 barres, normalisee par `atr_barre`"
    if col == "finish_r":
        return "part (0 a 1)", "position de la cloture dans le range de la barre AGREGEE"
    if col == "cvd_sess_r":
        return "contrats", "cumul du delta depuis 17h ET — la NUIT est dedans, ce n'est PAS depuis 9h30"
    if col.startswith("vwap") and not col.startswith("vwap_slope"):
        return "prix absolu", "un niveau, pas une distance"
    if col in UNITES_SOURCEES:
        return UNITES_SOURCEES[col]
    if col.endswith("_pct"):
        return ("part (0 a 1)" if float(v.abs().max()) <= 1.5 else "pourcent (0 a 100)"), \
            "PAS un pourcentage affichable tel quel" if float(v.abs().max()) <= 1.5 else ""
    if col.endswith("_ticks"):
        return "ticks", ""
    if float(v.min()) >= 0 and (v % 1 == 0).all():
        return "compte", ""
    if col in ("open", "high", "low", "close") or col.endswith("_lvl"):
        return "prix absolu", "ne JAMAIS mettre dans un modele : niveau de prix"
    # REPLI. Ne JAMAIS affirmer « sans dimension » ici : c'est une affirmation
    # sans preuve, et c'est la meme faute que l'ATR en plus discret. Une unite
    # qu'on n'a pas etablie se dit NON DETERMINEE, et se source au producteur
    # le jour ou une colonne en a besoin.
    return "non determinee", "unite non etablie : ni deduite des valeurs, ni sourcee au producteur"


def verifier_atr(df, brut, tick):
    """CONFRONTE les unites declarees a un ATR recalcule depuis les barres.

    C'est le garde-fou ne de l'erreur du 11/09 : une unite affirmee doit etre
    verifiable, sinon elle se perime comme n'importe quelle note. On recalcule
    le vrai ATR(14) sur les barres 1 min et sur les barres 15 min, et on exige
    que la colonne colle a la lecture DECLAREE, pas a l'autre.
    """
    def _atr(d, h, l, c, n=14, mini=None):
        H, L, C = (pd.to_numeric(d[x], errors="coerce") for x in (h, l, c))
        P = C.shift(1)
        tr = pd.concat([H - L, (H - P).abs(), (L - P).abs()], axis=1).max(axis=1)
        return float(tr.rolling(n, min_periods=mini or n).mean().median())

    out = []
    vrai_1m = _atr(brut, "bar_high", "bar_low", "close")
    vrai_15 = _atr(df, "high", "low", "close", mini=5)
    for col, vrai_pts in (("atr_14m", vrai_1m), ("atr_barre", vrai_15)):
        if col not in df.columns:
            continue
        med = float(pd.to_numeric(df[col], errors="coerce").median())
        declare = UNITES_SOURCEES[col][0]
        attendu = vrai_pts if declare == "points" else vrai_pts / tick
        autre = vrai_pts / tick if declare == "points" else vrai_pts
        ok = abs(med - attendu) < abs(med - autre)
        out.append((col, declare, med, attendu, ok))
    return out


def _note(col, prov, motif, proxy, recalc, dans_brut):
    bouts = []
    if proxy:
        bouts.append("PROXY refuse par `lecture.py`")
    if recalc:
        bouts.append("recalc (chauffe 20 j)")
    if not dans_brut and not recalc:
        bouts.append("nee a l'agregation 15 min")
    if prov in ("C", "S", "R") and motif:
        bouts.append(motif)
    if col == "atr_ref":
        bouts.append("= `atr_barre` si fini, sinon `atr_veille` ; `atr_source` dit lequel")
    return " ; ".join(bouts)


def construire(jour):
    df, brut = scenarios.charger("ES", jour)
    df_nq, _ = scenarios.charger("NQ", jour)
    if df.empty:
        raise SystemExit("aucune donnee pour %s" % jour)
    tick = lot.TICK
    etendue = float((pd.to_numeric(df["high"]) - pd.to_numeric(df["low"])).median())
    regles, noms = _regles(), _noms_familles()
    prov, proxys = _provenances(), _proxys()
    etoiles = _etoiles(df.columns)
    cols_brut = set(brut.columns)
    lignes = []
    for col in sorted(df.columns):
        fam = next((f for rx, f in regles if rx.search(col)), None)
        # Une colonne absente de la table n'est pas une anomalie : la table
        # catalogue le DUMPER C++, et la chaine produit ses propres colonnes.
        p, motif = prov.get(col, ("chaine", "produite par la chaine"))
        recalc = col.endswith("_r")
        u, piege = _unite(col, df[col], etendue, tick)
        u_nq = _unite(col, df_nq[col], float((pd.to_numeric(df_nq["high"]) -
                                              pd.to_numeric(df_nq["low"])).median()), tick)[0] \
            if col in df_nq.columns else u
        if u_nq != u:
            piege = (piege + " ; " if piege else "") + "unite DIFFERENTE sur NQ (%s)" % u_nq
        lignes.append({
            "nom": col, "etoile": col in etoiles,
            "famille": ("recalc" if recalc and not fam else (fam or "hors famille")),
            "famille_nom": noms.get(fam, ""),
            "provenance": "recalc" if recalc else ("proxy" if col in proxys else p),
            "unite": u, "piege": piege,
            "survit": "oui" if col in df.columns else "non",
            "dans_brut": col in cols_brut,
            "note": _note(col, p, motif, col in proxys, recalc, col in cols_brut),
        })
    return lignes, etendue, verifier_atr(df, brut, tick)


def main(argv):
    jour = argv[1] if len(argv) > 1 else "20260910"
    lignes, etendue, verif = construire(jour)
    for col, declare, med, attendu, ok in verif:
        print("  %-11s declare %-7s mediane %8.2f  attendu %8.2f  %s"
              % (col, declare, med, attendu, "OK" if ok else "INCOHERENT <<<"))
    from V3.manifeste_rendu import rendre       # importe ICI : le rendu importe ce module
    texte = rendre(lignes, jour, verif)
    open(SORTIE, "w", encoding="utf-8", newline="\n").write(texte)
    print("  %s : %d colonnes, %d lignes ecrites" % (SORTIE, len(lignes), texte.count("\n")))
    print("  etendue mediane d'une barre ES : %.2f points" % etendue)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
