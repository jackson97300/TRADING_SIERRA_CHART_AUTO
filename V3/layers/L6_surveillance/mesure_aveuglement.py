"""L'AUDIT DU MÈTRE — quand le bot est-il aveugle, et par quelle CAUSE NOMMÉE.

    python -X utf8 V3/layers/L6_surveillance/mesure_aveuglement.py

POURQUOI CE FICHIER EXISTE. `L6_surveillance/` ne contenait qu'un README : la
couche qui doit dire « le bot ne voit rien en ce moment » n'avait aucun
producteur. Un audit croisé à deux agents (12/09) l'a classée deuxième priorité
du week-end, et première en sûreté : elle compte des CAUSES, jamais un devenir.

LE PIRE MODE DE PANNE, celui qu'on cherche : une journée entière de silence qui
se lit « journée calme ». Un fichier de 10 Mo qui rend zéro barre cash ne
produit aucun signal, et un compteur de signaux à zéro est indiscernable d'un
marché sans opportunité. Ici les deux se séparent, par cause.

DEUX DÉNOMINATEURS, ANNONCÉS. Les colonnes brutes se lisent sur tous les jours
que `charger_jour` rend ; `atr_ref`, `atr_source` et `rvol_r` n'existent
qu'après `injecter_recalculs`, qui exige `MIN_JOURS_CHAUFFE` jours de chauffe.
Une fréquence sans son dénominateur n'est pas une mesure, c'est un chiffre —
les deux sont écrits, et le second est plus petit.

TROIS PIÈGES ÉVITÉS, chacun mesuré avant d'être évité :
  - `atr_barre` NaN sur ~24 % des barres N'EST PAS un aveuglement : c'est la
    chauffe du `rolling(14, min_periods=7)` qui redémarre chaque journée, et la
    brique 1 la couvre en basculant sur l'ATR de la veille. Le vrai trou du
    mètre est `atr_source == "aucun"`. Compter `atr_barre` annoncerait 24 %
    d'aveuglement là où il n'y en a presque pas.
  - `_mq_gamma_source = "sierra_proxy_v2"` n'aveugle rien : la quarantaine
    (`lecture_colonnes.SOURCES_DECLAREES`) ne gouverne que
    `mq_gamma_condition`, qui n'est dans AUCUNE liste `REQUISES`. Le mécanisme
    est armé et ne vise aucune colonne consommée — c'est le résultat, et il se
    dit tel quel plutôt qu'en 100 % d'alarme.
  - `window_version` partitionne le lot (bascule du 06/09 à 21:00 UTC). Un taux
    moyenné sur deux configurations Sierra ne décrit ni l'une ni l'autre : la
    partition est comptée et affichée.

ATTENDU ÉCRIT AVANT LA PREMIÈRE PASSE (12/09) : une douzaine de jours par
instrument à zéro barre cash, dominés par les dimanches, plus au moins un
fichier sans ligne `stable` et un à collecte tronquée ; le vrai trou d'ATR
quasi nul hors premier jour du lot ; `atr_source = veille` autour d'un quart
des barres ; VIX à zéro sur quelques pourcents dont au moins un jour entier ;
quarantaine effective sur une colonne consommée : ZÉRO ; aucun jour mixte.

AUCUN DEVENIR N'EST LU. Ce module ne touche ni `LOGS/entonnoir/`, ni
`LOGS/barrieres/`, ni `LOGS/reactions/`, et n'appelle ni `campagne.courir`
(qui tronque la mesure officielle) ni aucune barrière.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3 import lecture_colonnes as LC                           # noqa: E402
from V3.campagne import (COLS_RECALC, MIN_JOURS_CHAUFFE,        # noqa: E402
                         N_JOURS_CHAUFFE, jours_disponibles)

PREMIERE_CASH_ET = 570      # 09h30 ET — la premiere bin de 15 min de la seance
DERNIERE_CASH_ET = 945      # 15h45 ET — la derniere qui commence avant 16h00
ABSENTE = "colonne_absente:"


def _cause_jour_vide(sym, jour):
    """Pourquoi ce fichier ne rend AUCUNE barre cash. Une cause nommee, jamais
    un silence — c'est toute la raison d'etre de ce module.

    La derniere branche est `inconnu_a_instruire` et NON « tronquee » : si le
    fichier couvre encore des heures de seance, l'explication par la troncature
    ne tient pas, et un verdict qui se rabat toujours sur une cause plausible
    est un controle qui se verifie contre lui-meme."""
    chemin = os.path.join("DATA", "live_enriched", "sierra", sym,
                          "%s_%s_sierra_enriched.jsonl" % (jour, sym))
    if not os.path.exists(chemin):
        return "fichier_absent", ""
    n = stable = 0
    derniere = None
    for ligne in open(chemin, encoding="utf-8", errors="ignore"):
        if ligne[:1] != "{":
            continue
        n += 1
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        if d.get("data_quality_flag") == "stable":
            stable += 1
        ts = d.get("ts") or d.get("ts_raw_ms")
        if ts:
            derniere = ts
    fin = pd.to_datetime(int(derniere), unit="ms", utc=True) if derniere else None
    detail = "%d lignes, %d stables%s" % (n, stable,
                                          ", fin %s UTC" % fin.strftime("%H:%M")
                                          if fin is not None else "")
    if n == 0:
        return "fichier_vide", detail
    if stable == 0:
        return "aucune_ligne_stable", detail
    if pd.Timestamp(jour).dayofweek == 6:
        return "dimanche_globex_seul", detail
    # EN MINUTES ET, JAMAIS EN HEURES UTC (revue 12/09). `fin.hour < 14`
    # supposait l'ouverture cash a 13:30 UTC, vraie en EDT seulement : des le
    # 1er novembre, DANS la campagne, le cash ouvre a 14:30 UTC et un fichier
    # arrete a 14:10 aurait ete classe « a instruire » tout le dernier mois.
    if fin is not None:
        if int(recalc.minutes_et(pd.Series([fin])).iloc[0]) < PREMIERE_CASH_ET:
            return "collecte_arretee_avant_cash", detail
    return "inconnu_a_instruire", detail


def _causes_brutes(df):
    """Les causes lisibles sur la trame AGREGEE, sans recalcul. Une colonne
    absente rend None — « je ne sais pas » n'est pas « tout va bien »."""
    def num(col):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else None
    v, t = num("vix_level"), num("total_vol")
    h, g = num("dist_mq_hvl"), num("gamma_block_long")
    return {
        "vix_absent_ou_nul": None if v is None else (v.isna() | (v <= 0)),
        "volumetrie_nulle": None if t is None else (t.isna() | (t <= 0)),
        "hvl_absent": None if h is None else h.isna(),
        "gamma_absent": None if g is None else g.isna(),
        "barre_incomplete": (~df["barre_complete"].fillna(False).astype(bool)
                             if "barre_complete" in df.columns else None),
    }


def _causes_recalc(dfe):
    """Les causes qui n'existent qu'apres `injecter_recalculs`. La distinction
    entre le VRAI trou et la simple chauffe est faite ici, une fois. Les noms
    prefixes d'un blanc soulignant ne sont PAS des aveuglements."""
    def num(col):
        return pd.to_numeric(dfe[col], errors="coerce") if col in dfe.columns else None
    src = dfe["atr_source"].astype(str) if "atr_source" in dfe.columns else None
    ref, barre, rv = num("atr_ref"), num("atr_barre"), num("rvol_r")
    return {
        "atr_aucune_source": None if src is None else (src == "aucun"),
        "atr_ref_absent": None if ref is None else ref.isna(),
        "_atr_de_la_veille": None if src is None else (src == "veille"),
        "_atr_barre_chauffe": None if barre is None else barre.isna(),
        "rvol_r_absent": None if rv is None else rv.isna(),
    }


def _cumuler(acc, causes, n_barres):
    """Une colonne absente un jour donne ne rend pas le compte incalculable :
    elle verse les barres de CE jour dans une cause explicite. Le total reste
    un entier, et l'absence reste visible."""
    for nom, masque in causes.items():
        if masque is None:
            acc[ABSENTE + nom] = acc.get(ABSENTE + nom, 0) + n_barres
        else:
            acc[nom] = acc.get(nom, 0) + int(masque.sum())


def _quarantaine_effective():
    """Les colonnes REQUISES reellement gouvernees par une source « proxy »."""
    requises = {c for cols in LC.REQUISES.values() for c in cols}
    return sorted(c for cols in LC.SOURCES_DECLAREES.values()
                  for c in cols if c in requises)


def _passe(sym):
    """Une passe sur le lot, avec le cache incrementiel de la chauffe (sans
    lui, chaque jour rechargerait ses dix jours de chauffe : huit fois le
    cout)."""
    cache, vides, ampute, fenetres = {}, [], [], {}
    brutes, recalcs = {}, {}
    n_brut = n_recalc = n_jours_recalc = 0
    for jour in jours_disponibles(sym):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if not brut.empty and all(c in brut.columns for c in COLS_RECALC):
            cache[jour] = brut[COLS_RECALC]
        if df.empty or len(df) < 2:
            vides.append((jour, ) + _cause_jour_vide(sym, jour))
            continue
        mn = recalc.minutes_et(pd.to_datetime(df["ts"], unit="ms", utc=True))
        d, f = int(mn.min()), int(mn.max())
        if d > PREMIERE_CASH_ET or f < DERNIERE_CASH_ET:
            ampute.append((jour, d, f))
        cle = "+".join(sorted({str(x) for x in df["window_version"].dropna().unique()})
                       ) if "window_version" in df.columns else "absente"
        fenetres[cle or "absente"] = fenetres.get(cle or "absente", 0) + 1
        n_brut += len(df)
        _cumuler(brutes, _causes_brutes(df), len(df))
        prev = [cache[j] for j in sorted(cache) if j < jour][-N_JOURS_CHAUFFE:]
        if jour not in cache or len(prev) < MIN_JOURS_CHAUFFE:
            continue
        dfe = injecter_recalculs(pd.concat(prev + [cache[jour]], ignore_index=True),
                                 df, minutes=15)
        n_recalc += len(dfe)
        n_jours_recalc += 1
        _cumuler(recalcs, _causes_recalc(dfe), len(dfe))
    return {"vides": vides, "ampute": ampute, "fenetres": fenetres,
            "n_brut": n_brut, "n_recalc": n_recalc, "brutes": brutes,
            "recalcs": recalcs, "n_jours": len(jours_disponibles(sym)),
            "n_jours_recalc": n_jours_recalc}


def _table(causes, total, s):
    """UN DENOMINATEUR PAR CAUSE (revue 12/09). Diviser tout par le meme total
    sous-estime mecaniquement une cause dont la colonne a manque certains
    jours : ces barres n'ont jamais pu etre jugees. Le module se reclamait de
    cette discipline en tete et ne l'appliquait pas a sa propre table."""
    s += ["| cause | barres | sur | part | lecture |", "|---|---|---|---|---|"]
    for nom, n in sorted(causes.items()):
        if nom.startswith(ABSENTE):
            lecture, affiche = "colonne ABSENTE de la trame ce jour-là", nom
        elif nom.startswith("_"):
            lecture, affiche = "dépendance déclarée, PAS un aveuglement", nom[1:]
        else:
            lecture, affiche = "aveuglement", nom
        d = total if nom.startswith(ABSENTE) else total - causes.get(ABSENTE + nom, 0)
        part = "—" if not d else "%.2f %%" % (100.0 * n / d)
        s.append("| `%s` | %d | %d | %s | %s |" % (affiche, n, d, part, lecture))
    s.append("")


def main():
    os.chdir(RACINE)
    quarantaine = _quarantaine_effective()
    s = ["# L'audit du mètre — l'aveuglement par cause nommée (L6)", "",
         "*Attendu écrit avant la passe : une douzaine de jours par instrument à",
         "zéro barre cash (dimanches, un fichier sans ligne `stable`, une collecte",
         "tronquée) ; vrai trou d'ATR quasi nul ; `atr_source = veille` ≈ un quart",
         "des barres ; VIX à zéro sur quelques pourcents dont un jour entier ;",
         "quarantaine effective ZÉRO ; aucun jour mixte. Aucun devenir lu.*", ""]
    verdicts = []
    for sym in ("ES", "NQ"):
        r = _passe(sym)
        s += ["## %s" % sym, "",
              "- fichiers listés : **%d** — rendant ≥ 2 barres cash : **%d** — "
              "avec assez de chauffe pour `atr_ref` : **%d**"
              % (r["n_jours"], r["n_jours"] - len(r["vides"]), r["n_jours_recalc"]),
              "- dénominateur 1 (colonnes brutes) : **%d barres**" % r["n_brut"],
              "- dénominateur 2 (colonnes recalculées) : **%d barres**" % r["n_recalc"],
              "- configuration Sierra : %s"
              % ", ".join("`%s` %d jour(s)" % kv for kv in sorted(r["fenetres"].items())),
              "",
              "### Journées entièrement aveugles — %d" % len(r["vides"]), "",
              "| jour | cause | détail |", "|---|---|---|"]
        for jour, cause, detail in r["vides"]:
            s.append("| %s | `%s` | %s |" % (jour, cause, detail))
        s += ["", "### Séances amputées — %d" % len(r["ampute"]), "",
              "| jour | première barre (min ET) | dernière |", "|---|---|---|"]
        for jour, d, f in r["ampute"]:
            s.append("| %s | %d%s | %d%s |"
                     % (jour, d, " ⚠ attendu 570" if d > PREMIERE_CASH_ET else "",
                        f, " ⚠ attendu 945" if f < DERNIERE_CASH_ET else ""))
        s += ["", "### Barres — causes lisibles sans recalcul", ""]
        _table(r["brutes"], r["n_brut"], s)
        s += ["### Barres — causes qui exigent la chauffe", ""]
        _table(r["recalcs"], r["n_recalc"], s)
        verdicts.append((sym, [c for _j, c, _d in r["vides"] if c == "inconnu_a_instruire"],
                         [k for k in r["fenetres"] if "+" in k],
                         r["recalcs"].get("atr_aucune_source"),
                         r["brutes"].get("vix_absent_ou_nul"),
                         [k for k in list(r["brutes"]) + list(r["recalcs"])
                          if k.startswith(ABSENTE)]))
    s += ["## Ce que la passe a tenu", "",
          "- quarantaine effective sur une colonne `REQUISES` : **%s**"
          % (", ".join(quarantaine) if quarantaine else
             "AUCUNE — le mécanisme est armé mais ne gouverne aucune colonne que "
             "la chaîne lit (`mq_gamma_condition` n'est dans aucune `REQUISES`)"),
          ""]
    for sym, inconnus, mixtes, atr_aucun, vix, absentes in verdicts:
        s.append("- **%s** : journées vides sans cause instruite : **%s** ; jours "
                 "mélangeant deux configurations Sierra : **%s** ; vrai trou d'ATR "
                 "(`atr_source = aucun`) : **%s** barre(s) ; VIX absent ou nul : "
                 "**%s** barre(s) ; colonnes absentes rencontrées : %s"
                 % (sym, ", ".join(inconnus) if inconnus else "aucune",
                    ", ".join(mixtes) if mixtes else "aucun",
                    atr_aucun if atr_aucun is not None else "colonne jamais vue",
                    vix if vix is not None else "colonne jamais vue",
                    ", ".join(k[len(ABSENTE):] for k in absentes) or "aucune"))
    s += ["", "*Aucun champ de devenir n'a été lu ni écrit : ce module ne touche",
          "ni l'entonnoir, ni les barrières, ni les réactions.*"]
    chemin = ("V3/layers/L6_surveillance/rapports/aveuglement_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    # Le module cree son propre dossier : sans ca, une passe de cinq minutes
    # meurt a la derniere ligne et tout le travail est perdu (vecu le 12/09).
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    open(chemin, "w", encoding="utf-8").write("\n".join(s))
    print("\n".join(s))
    print("\nrapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
