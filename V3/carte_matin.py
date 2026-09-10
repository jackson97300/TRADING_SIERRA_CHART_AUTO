"""LA CARTE DU MATIN — brique 3 (Fable 09/09, protocole pré-enregistré 10/09).

    python -X utf8 V3/carte_matin.py [YYYYMMDD] [--forcer]

À 9h25 ET, pour chaque instrument : les PRIX exacts où chaque hypothèse des
quatre tirerait aujourd'hui — le niveau et sa bande (`lieux.BANDE`, en prix,
sur le mètre que la chaîne utilisera à 9h30 : `atr_veille`, la dernière
session complète), les dix niveaux de H8p avec leur bande, et les repères de
la veille avec leur source. Une page texte, lecture seule. ELLE DÉCRIT, ELLE
N'ORDONNE PAS. Même mètre que `lieux.py` et `marges_quatre.exposer()`.

L'ALTERNANCE EN AVEUGLE (DECISIONS 10/09, Q8) : tirage par BLOCS D'UNE
SEMAINE, 50/50, générateur seedé (`SEED`, écrite dans DECISIONS), calendrier
tiré pour HUIT semaines d'un coup ; les jours « sans carte » la carte est
GÉNÉRÉE ET STOCKÉE (`LOGS/carte/aveugle/`), pas affichée ; le journal manuel du
jour porte `carte_visible: true|false` ; AUCUNE lecture avant huit blocs ; au
jour 61+ : les trades manuels avec / sans, et l'ÉCART trader-machine avec /
sans. `--forcer` affiche quand même — pour un test, jamais en séance — et
N'ÉCRIT PAS dans le journal manuel.

GARDE (review 10/09, R2) : si le brut porte déjà une barre CASH, la carte est
TARDIVE — l'ouverture l'a contaminée — elle s'écrit étiquetée, le journal ne
reçoit pas `carte_visible`, le code retour vaut 2. La garde est sur la
DONNÉE, pas sur l'horloge : elle survit au changement d'heure.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from CORE.research import hypotheses as H                       # noqa: E402
from V3 import lieux                                            # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min               # noqa: E402
from V3.lecture_colonnes import val                             # noqa: E402

SEED = 20260910               # ecrite dans DECISIONS le 10/09 — jamais retiree
DEBUT = date(2026, 9, 7)      # lundi de la semaine 1 du tirage (ISO 37)
BLOCS = 8                     # huit semaines d'un coup, 4 visibles / 4 non
DOSSIER = "LOGS/carte"
JOURNAL = "V3/journal_manuel"
REPERES = ("prev_vah", "prev_val", "prev_vpoc", "pdh", "pdl", "ovn_high",
           "ovn_low", "mq_call", "mq_put", "mq_hvl")


def _date(jour):
    return date(int(jour[:4]), int(jour[4:6]), int(jour[6:8]))


def carte_visible(jour):
    """True / False pour `jour`, par blocs d'une semaine : la semaine k lit
    le k-ieme element d'une permutation seedee de [4 x True, 4 x False],
    redessinee tous les 8 blocs avec le MEME generateur (deterministe :
    deux appels rendent la meme chose, personne ne tire a la main)."""
    k = (_date(jour) - DEBUT).days // 7
    if k < 0:
        return False
    rng = np.random.default_rng(SEED)
    for _ in range(k // BLOCS + 1):
        perm = rng.permutation([True] * (BLOCS // 2) + [False] * (BLOCS // 2))
    return bool(perm[k % BLOCS])


def _niveau(brut, i, col, tick=H.TICK):
    d, c = val(brut, col, i), val(brut, "close", i)
    return None if d is None or c is None else (round(c + d * tick, 2), d)


def _bande_prix(a, fam, cote, tick=H.TICK):
    bas, haut = lieux.BANDE[(fam, cote)]
    return (round(-lieux.seuil_p(a, bas, tick) * tick, 2),
            round(lieux.seuil_p(a, haut, tick) * tick, 2))


def _heure(ts):
    m = int(recalc.minutes_et(pd.Series([pd.Timestamp(int(ts), unit="ms",
                                                      tz="UTC")])).iloc[0])
    return "%02d:%02d" % divmod(m, 60)


def dessiner(sym, jour, brut, atr_v):
    """Les lignes de la carte pour un instrument. `brut` : le 1 min de la
    journee (la nuit Globex a 9h25) ; `atr_v` : atr_veille en points."""
    i = len(brut) - 1
    L = ["== %s — %s — derniere barre %s ET, close %.2f, mètre atr_veille %.2f pts (P10 = %.1f t)"
         % (sym, jour, _heure(brut["ts"].iloc[i]), val(brut, "close", i) or float("nan"),
            atr_v, lieux.seuil_p(atr_v, "P10"))]
    L.append("  LES QUATRE — le niveau, et la bande ou le lieu existe (en prix) :")
    for (fam, cote), niveaux in lieux.TABLE.items():
        for nom, col in niveaux:
            n, b = _niveau(brut, i, col), _bande_prix(atr_v, fam, cote)
            if n is None:
                L.append("    %-8s %-5s %-14s : pas encore (%s absent avant l'ouverture)"
                         % (fam, "long" if cote > 0 else "short", nom, col))
            else:
                L.append("    %-8s %-5s %-14s : %9.2f   bande [%+.2f ; %+.2f] -> [%.2f ; %.2f]"
                         % (fam, "long" if cote > 0 else "short", nom, n[0], b[0], b[1],
                            n[0] + b[0], n[0] + b[1]))
    b20 = _bande_prix(atr_v, "H8p", 1)
    L.append("  H8p — les dix niveaux ; le lieu = a moins de P20 (%.2f pts) de l'un d'eux :"
             % b20[1])
    for nom, col in lieux.NIVEAUX_H8:
        n = _niveau(brut, i, col)
        L.append("    %-14s : %s" % (nom, "%.2f" % n[0] if n else "absent"))
    L.append("  REPERES de la veille (source : colonnes `_lvl` du brut, sinon close + dist) :")
    for nom in REPERES:
        lv, n = val(brut, nom + "_lvl", i), _niveau(brut, i, "dist_" + nom)
        src = "lvl" if lv is not None else ("dist" if n else "absent")
        prix = lv if lv is not None else (n[0] if n else None)
        L.append("    %-10s : %s  (%s)" % (nom, "%.2f" % prix if prix is not None else "-", src))
    return L


def _atr_veille(sym, jour, brut):
    b = pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]], ignore_index=True)
    v = recalc.atr_veille_15(b, pd.to_datetime(b["ts"], unit="ms", utc=True), minutes=15)
    x = v.get(_date(jour), np.nan)
    return float(x) if pd.notna(x) else None


def _journal(jour, visible):
    """Le journal manuel du jour porte `carte_visible` — cree le gabarit si
    Jackson ne l'a pas encore ouvert. La machine n'ecrit que SA ligne (celle
    qui commence par le litteral) ; tout le reste du fichier est a lui."""
    os.makedirs(JOURNAL, exist_ok=True)
    p = os.path.join(JOURNAL, "%s.md" % jour)
    ligne = "`carte_visible` : %s" % str(visible).lower()
    if not os.path.exists(p):
        open(p, "w", encoding="utf-8", newline="\n").write(
            "# JOURNAL MANUEL — %s/%s/%s (Jackson)\n\n## Les clics (sept champs)\n\n"
            "| heure_et | sym | side | prix_entree | prix_sortie | issue | pourquoi (≤ 10 mots) |\n"
            "|---|---|---|---|---|---|---|\n| | | | | | | |\n\n"
            "Fin de journée — `ce_que_j_ai_vu` (une phrase) :\n\n%s\n"
            % (jour[6:8], jour[4:6], jour[:4], ligne))
        return p
    txt = open(p, encoding="utf-8").read()
    if "`carte_visible`" in txt:
        txt = "\n".join(ligne if ln.startswith("`carte_visible`") else ln
                        for ln in txt.split("\n"))
    else:
        txt = txt.rstrip("\n") + "\n\n" + ligne + "\n"
    open(p, "w", encoding="utf-8", newline="\n").write(txt)
    return p


def courir(jour, forcer=False, bruts=None):
    """Rend 0 ; 2 si la carte est TARDIVE (une barre cash est deja la).
    `bruts` : {sym: frame 1 min} pour les tests, sinon charger_jour."""
    os.chdir(RACINE)
    visible = carte_visible(jour)
    frames = {}
    for sym in ("ES", "NQ"):
        frames[sym] = (bruts[sym] if bruts is not None else
                       charger_jour(sym, jour, 15, avec_1min=True, cash_only=False)[1])
    tardive = any(not b.empty and bool(recalc.est_cash(
        pd.to_datetime(b["ts"], unit="ms", utc=True)).any()) for b in frames.values())
    page = ["CARTE DU MATIN — %s — tirage bloc %d : %s%s%s" % (
        jour, (_date(jour) - DEBUT).days // 7 + 1,
        "VISIBLE" if visible else "NON VISIBLE (generee, stockee)",
        " — FORCEE" if forcer else "",
        " — TARDIVE (une barre cash est deja la : l'ouverture a contamine la carte)"
        if tardive else ""),
        "Elle decrit, elle n'ordonne pas. Meme metre que la chaine a 9h30 (atr_veille).", ""]
    for sym, brut in frames.items():
        if brut.empty:
            page.append("== %s — %s : aucune barre" % (sym, jour))
            continue
        atr_v = _atr_veille(sym, jour, brut)
        if atr_v is None:
            page.append("== %s — %s : pas de session complete avant, pas de metre" % (sym, jour))
            continue
        page += dessiner(sym, jour, brut, atr_v) + [""]
    dossier = DOSSIER if (visible or forcer or tardive) else os.path.join(DOSSIER, "aveugle")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, "carte_%s.txt" % jour)
    open(chemin, "w", encoding="utf-8", newline="\n").write("\n".join(page) + "\n")
    if visible or forcer or tardive:
        print("\n".join(page))               # la carte d'abord, le journal apres
    else:
        print("CARTE %s : NON VISIBLE ce bloc — generee et stockee (%s)" % (jour, chemin))
    if forcer or tardive:                    # ni test ni retard n'ecrivent au journal
        return 2 if tardive else 0
    try:
        print("journal : %s" % _journal(jour, visible))
    except OSError as e:                     # un journal illisible ne cache pas la carte
        print("  ATTENTION journal manuel non ecrit : %s" % e)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jour", nargs="?", default=pd.Timestamp.utcnow().strftime("%Y%m%d"))
    ap.add_argument("--forcer", action="store_true")
    a = ap.parse_args()
    return courir(a.jour, forcer=a.forcer)


if __name__ == "__main__":
    sys.exit(main())
