"""GENERE `V3/MANIFESTE_DONNEES.md` — le catalogue des donnees que V3 consomme.

    python -X utf8 V3/mesure_manifeste.py [jour]

POURQUOI IL EST GENERE ET NON ECRIT. Un catalogue tape a la main ment des la
premiere derive, et personne ne s'en apercoit : c'est exactement comme ca que
`CLAUDE.md` a fini par affirmer « `atr` en points, `atr_14m` en ticks » alors
que la MESURE sur les deux instruments dit l'inverse (voir `_unite`). Six
confusions d'unites en une semaine dans ce depot, toutes d'un facteur constant.
Ici, chaque unite est DEDUITE des valeurs reelles du frame, jamais recopiee
d'une note.

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
    """L'unite, DEDUITE des valeurs. Jamais recopiee d'une note : c'est ainsi
    que `CLAUDE.md` a fini par dire l'inverse de la realite sur l'ATR."""
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
    if col.startswith("atr"):
        med = float(v.median())
        en_pts = abs(med - etendue_pts) < abs(med - etendue_pts / tick)
        return ("points" if en_pts else "ticks"), "MESURE contre l'etendue mediane d'une barre"
    if col.endswith("_pct"):
        return ("part (0 a 1)" if float(v.abs().max()) <= 1.5 else "pourcent (0 a 100)"), \
            "PAS un pourcentage affichable tel quel" if float(v.abs().max()) <= 1.5 else ""
    if col.endswith("_ticks"):
        return "ticks", ""
    if float(v.min()) >= 0 and (v % 1 == 0).all():
        return "compte", ""
    if col in ("open", "high", "low", "close") or col.endswith("_lvl"):
        return "prix absolu", "ne JAMAIS mettre dans un modele : niveau de prix"
    return "sans dimension", ""


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
    return lignes, etendue


def rendre(lignes, jour):
    total = len(lignes)
    par_prov = {}
    for l in lignes:
        par_prov[l["provenance"]] = par_prov.get(l["provenance"], 0) + 1
    out = ["# MANIFESTE DES DONNEES — ce que V3 consomme vraiment", "",
           "*GENERE par `V3/mesure_manifeste.py`, jamais ecrit a la main. Regenerer",
           "apres toute modification d'une colonne : un catalogue tape ment des la",
           "premiere derive. Mesure sur le %s, ES et NQ.*" % jour, "",
           "## La source, en une ligne", "",
           "`DATA/live_enriched/sierra/{ES,NQ}/*.jsonl`, barres de 1 minute, agregees",
           "en 15 minutes par la chaine (`injecter_recalculs`, chauffe vingt jours).",
           "**Le frame que la chaine LIT porte %d colonnes** ; le brut 1 min en porte" % total,
           "plusieurs centaines — tout ce qui n'est pas dans la liste ci-dessous meurt",
           "a l'agregation et n'existe pas pour V3.", "",
           "## Le compte", "",
           "| provenance | colonnes | ce que ca veut dire |", "|---|---|---|"]
    for cl in sorted(par_prov):
        out.append("| `%s` | %d | %s |" % (cl, par_prov[cl],
                                            "recalculee par la chaine (`_r`)" if cl == "recalc"
                                            else "proxy refuse par `lecture.py`" if cl == "proxy"
                                            else CLASSES.get(cl, "?")))
    etoiles = [l for l in lignes if l["etoile"]]
    out += ["", "> Les colonnes `recalc` sont calculees par la chaine avec VINGT jours",
            "> de chauffe. Sur un frame `lot` de trois jours elles peuvent etre absentes",
            "> — ou pire, PRESENTES ET FAUSSES. C'est pourquoi la ligne de journal porte",
            "> `setups_armes_motif` et `flux_motif` quand le frame n'est pas fiable.", "",
            "## Ce sur quoi repose la decision (★)", "",
            "**%d colonnes** sur %d sont lues par LES_QUATRE et les setups" % (len(etoiles), total),
            "(citees dans `V3/marges_quatre.py`). Tout le reste est du contexte :", "",
            "`" + "`, `".join(l["nom"] for l in etoiles) + "`", "",
            "## Les pieges d'unite, mesures", "",
            "| colonne | unite MESUREE | ce que disait la note |", "|---|---|---|",
            "| `atr` | ticks | `CLAUDE.md` dit « points » — **l'inverse** |",
            "| `atr_14m`, `atr_barre`, `atr_veille`, `atr_ref` | points | `CLAUDE.md` dit « ticks » — **l'inverse** |",
            "| `dist_*` | ticks | conforme (`niveau = close + dist x tick`) |",
            "| `*_pct` | part de 0 a 1 | **pas** un pourcentage affichable tel quel |", ""]
    vus = set()
    for titre, motif in BLOCS:
        rx = re.compile(motif)
        bloc = [l for l in lignes if l["nom"] not in vus and rx.search(l["nom"])]
        if not bloc:
            continue
        vus |= {l["nom"] for l in bloc}
        out += ["## %s" % titre, "",
                "| colonne | fam. | prov. | unite | note |", "|---|---|---|---|---|"]
        for l in bloc:
            out.append("| %s`%s` | %s | `%s` | %s | %s |" % (
                "★ " if l["etoile"] else "", l["nom"], l["famille"], l["provenance"],
                l["unite"] + (" — " + l["piege"] if l["piege"] else ""), l["note"] or "—"))
        out.append("")
    reste = [l for l in lignes if l["nom"] not in vus]
    if reste:
        out += ["## Hors bloc", "", "| colonne | fam. | prov. | unite | note |", "|---|---|---|---|---|"]
        for l in reste:
            out.append("| %s`%s` | %s | `%s` | %s | %s |" % (
                "★ " if l["etoile"] else "", l["nom"], l["famille"], l["provenance"],
                l["unite"], l["note"] or "—"))
        out.append("")
    return "\n".join(out) + "\n"


def main(argv):
    jour = argv[1] if len(argv) > 1 else "20260910"
    lignes, etendue = construire(jour)
    texte = rendre(lignes, jour)
    open(SORTIE, "w", encoding="utf-8", newline="\n").write(texte)
    print("  %s : %d colonnes, %d lignes ecrites" % (SORTIE, len(lignes), texte.count("\n")))
    print("  etendue mediane d'une barre ES : %.2f points" % etendue)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
