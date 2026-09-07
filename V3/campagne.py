"""CAMPAGNE — le coureur qui fait EXISTER une journée d'ombre.

    python -X utf8 V3/campagne.py                 # rejoue le dernier fichier
    python -X utf8 V3/campagne.py 20260908        # une journée de trading

Le tag fige les documents ; ce fichier prouve que le jour a eu lieu. Il
enchaîne ce qui existait sans coureur : le fichier du jour → l'agrégation →
les déclencheurs L3 → `chaine.appliquer` → **l'entonnoir officiel du jour**
(`LOGS/entonnoir/entonnoir_<jour>.jsonl`) que `pourquoi.py` lit à 21:01.

DEUX MODES, ET LA DIFFÉRENCE EST ÉCRITE :
- **--rejouer** (défaut) : fin de journée, `strict=False`. L'âge de la barre et
  l'état du connecteur n'existent plus après coup — les trous se journalisent
  sans bloquer. C'est le mode du rythme quotidien.
- **--strict** : réservé au futur coureur LIVE (boucle sur le fichier vivant).
  En l'état, il bloquerait tout par les trous DTC — c'est VOULU (fail-closed),
  et c'est pourquoi la question « le bot a-t-il tourné en strict ? » reste NON
  tant que le coureur live n'est pas la brique suivante.

Ce que `live` porte en rejeu — uniquement ce qui est VRAI après coup :
`contrat_actif` (le contrat du fichier est-il U26), `rollover` (calendrier),
`ferie` (calculé par lecture.py). `age_s`, `dtc`, `l6_alerte` restent None.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE import entonnoir                                       # noqa: E402
from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.research import hypotheses as H                        # noqa: E402
from CORE.research.hypothesis_runner import (                    # noqa: E402
    injecter_recalculs, signaux_par_franchissement)
from V3 import calendrier, chaine, lecture                       # noqa: E402
from V3.layers.L3_declencheurs import ombre16, ombre_c2          # noqa: E402

# Ce que `injecter_recalculs` consomme du 1 min : hlc3 + volume + horodatage
# + delta (cvd_sess_r, prerequis L4).
COLS_RECALC = ["ts", "high", "low", "close", "total_vol", "delta_bar"]
# = `n_jours` de recalc.rvol — les deux bougent ensemble, sinon la chauffe
# devient trop courte en silence. Le plancher 10 = son `min_periods`.
N_JOURS_CHAUFFE, MIN_JOURS_CHAUFFE = 20, 10


def jours_disponibles(sym):
    js = {re.search(r"(\d{8})", os.path.basename(f)).group(1)
          for f in glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)
          if re.search(r"(\d{8})", os.path.basename(f))}
    return sorted(js)


def dernier_jour(sym="ES"):
    js = jours_disponibles(sym)
    return js[-1] if js else None


def chauffe_1min(sym, jour, n_jours=N_JOURS_CHAUFFE):
    """Le 1 min des `n_jours` journées PRÉCÉDANT `jour` — la chauffe de
    `rvol_r`, qui est saisonnier (cette minute de séance contre les 20 jours
    d'avant, strictement passés). Sans elle, la colonne rend NaN sur une
    journée chargée seule, et H8p est structurellement muette : le N=0 de
    colonne vide, pas la rareté annoncée.

    Un fichier HISTORIQUE malformé est écarté avec son motif : un vieux jour ne
    doit pas tuer le run officiel du jour. Le brut du jour courant, lui, doit
    crasher — fail-loud."""
    prev = [j for j in jours_disponibles(sym) if j < jour][-n_jours:]
    morceaux = []
    for j in prev:
        _, b = charger_jour(sym, j, 15, avec_1min=True)
        if b.empty:
            continue
        if not all(c in b.columns for c in COLS_RECALC):
            print("  chauffe : %s %s écarté (colonnes manquantes)" % (sym, j))
            continue
        morceaux.append(b[COLS_RECALC])
    return morceaux


def signaux_l3(df):
    """Les déclencheurs de la SPEC gelée — `LES_QUATRE` pré-enregistrés
    (MISSION_CYCLE2, Bonferroni 0,05/4) : H3-VPOC seule testable, H2p/H6p/H8p
    annoncées non testables. Tous journalisés, dédoublonnés par (barre, sens).

    Comptés par FRANCHISSEMENT (faux → vrai dans la journée, la fonction même
    du cycle 1) : six barres vraies d'affilée font UN signal, pas six — c'est
    sur ce comptage que le critère N ≥ 40 est défini.

    Rend `(signaux, comptes)` : les signaux dédoublonnés par (barre, sens) pour
    la chaîne — son état séquentiel exige UN appel — et les comptes PAR
    HYPOTHÈSE avant dédoublonnage : un chevauchement (i, side) ne doit pas
    sous-compter la seconde hypothèse à l'affichage.

    La première version courait {h3, h6, h7, h8} du cycle 1 — H7 non
    pré-enregistrée, H2p absente, h6/h8 dans leurs variantes disqualifiées —
    et comptait chaque barre vraie. Corrigé AVANT le premier journal officiel :
    le jour 61 lit LES_QUATRE."""
    out, vus = [], set()
    comptes = {n: 0 for n in H.LES_QUATRE}
    for nom, fn in H.LES_QUATRE.items():
        for _c, (cond, side) in fn(df).items():
            for i in signaux_par_franchissement(cond, df["jour"]):
                comptes[nom] += 1
                if (i, side) not in vus:
                    vus.add((i, side))
                    out.append((i, side, nom))
    return sorted(out), comptes


def contrat_ok(sym, jour):
    """Le contrat du fichier est-il LE contrat actif du calendrier ?

    Lu dans le fichier, calcule par `calendrier.contrat_actif` — plus de
    tuple en dur « a mettre a jour au rollover » : le jour du roll, si le
    fichier porte encore l'ancien contrat, la porte L0_CONTRAT_INACTIF le
    dira, et c'est exactement son travail."""
    fs = sorted(glob.glob("DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)))
    if not fs:
        return None
    attendu = calendrier.contrat_actif(jour)
    for ln in open(fs[0], encoding="utf-8", errors="ignore"):
        if ln[:1] == "{":
            try:
                c = json.loads(ln).get("contract", "")
            except ValueError:
                continue
            return attendu in str(c)
    return None


def courir(jour, strict=False, minutes=15):
    chemin = "LOGS/entonnoir/entonnoir_%s.jsonl" % jour
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    # Le jour se rejoue entier, jamais en append — et le fichier EXISTE même
    # sans signal : vide = jour couru muet, absent = jour jamais couru. Sans
    # cette distinction, la majorité des 60 jours (signaux rares par
    # construction) n'aurait AUCUNE preuve d'avoir eu lieu.
    open(chemin, "w").close()
    # Les SEIZE en ombre : leur journal SEPARE, meme politique de rejeu.
    chemin16 = "LOGS/entonnoir/ombre16_%s.jsonl" % jour
    open(chemin16, "w").close()
    # Les C2 actifs (brief OMBRE_C2, regle 15) : troisieme journal.
    chemin_c2 = "LOGS/entonnoir/ombre_c2_%s.jsonl" % jour
    open(chemin_c2, "w").close()
    total = 0
    for sym in ("ES", "NQ"):
        df, brut = charger_jour(sym, jour, minutes, avec_1min=True)
        if df.empty or len(df) < 6:
            print("  %s : pas de barres cash exploitables" % sym)
            continue
        # Les colonnes que LES_QUATRE exigent RECALCULEES (rvol_r, bandes SD2) :
        # sans l'injection, H2p et H8p ne peuvent structurellement jamais
        # déclencher — un N=0 de colonne absente, pas de rareté. La chauffe
        # rvol_r ne regarde que le passé ; le merge ne garde que le jour.
        ch = chauffe_1min(sym, jour)
        if len(ch) < MIN_JOURS_CHAUFFE:
            print("  %s : CHAUFFE INSUFFISANTE (%d j < %d) — rvol_r rendra NaN,"
                  " H8p non évaluable ce jour" % (sym, len(ch), MIN_JOURS_CHAUFFE))
        brut = pd.concat(ch + [brut[COLS_RECALC]], ignore_index=True)
        df = injecter_recalculs(brut, df, minutes=minutes)
        manquantes = lecture.verifier_colonnes(df, ("L0", "L5"))
        if manquantes:
            print("  %s : COLONNES MANQUANTES %s — jour NON couru, incident"
                  % (sym, manquantes))
            continue
        live = {"contrat_actif": contrat_ok(sym, jour), "rollover": False}
        sig, comptes = signaux_l3(df)
        retenus = chaine.appliquer([(i, s) for i, s, _n in sig], df, sym,
                                   journal=chemin, hypothese="ombre1",
                                   strict=strict, live=live)
        total += len(sig)
        detail = " ".join("%s=%d" % (n, comptes[n]) for n in H.LES_QUATRE)
        # Les seize accumulent leur N dans leur propre journal — jamais par
        # la chaine (ils fausseraient la position virtuelle des quatre).
        n16, absentes16 = ombre16.journaliser(df, sym, jour, chemin16)
        if absentes16:
            print("  %s : OMBRE16 AVEUGLE sur %s — colonnes perdues, un setup"
                  " mort en silence" % (sym, absentes16))
        n_c2, muets_c2, absentes_c2 = ombre_c2.journaliser(df, sym, jour,
                                                           chemin_c2)
        if absentes_c2:
            print("  %s : OMBRE_C2 AVEUGLE sur %s — colonnes perdues, un"
                  " setup mort en silence" % (sym, absentes_c2))
        print("  %s : %d signaux L3 (%s), %d retenus par L0/L5, %d ombre16,"
              " %d C2 (+%d lieux muets) -> %s"
              % (sym, len(sig), detail, len(retenus), n16, n_c2, muets_c2,
                 chemin))
    if total == 0:
        print("  AUCUN SIGNAL sur la journee — le journal VIDE est ecrit : la")
        print("  preuve que le jour a ete couru. Verifier avec pourquoi.py que")
        print("  ce n'est pas une couche muette.")
    return chemin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jour", nargs="?", default=None)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    os.chdir(RACINE)
    jour = a.jour or dernier_jour()
    if not jour:
        print("aucun fichier de donnees")
        return 1
    print("CAMPAGNE ombre-1 — journee %s, mode %s"
          % (jour, "STRICT (live)" if a.strict else "rejeu (strict=False)"))
    chemin = courir(jour, strict=a.strict)
    print("\nlecture : python -X utf8 V3/pourquoi.py --journal %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
