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
from V3 import chaine, lecture                                   # noqa: E402

CONTRATS_ATTENDUS = ("U26", "Z26")      # a mettre a jour au rollover


def dernier_jour(sym="ES"):
    js = [re.search(r"(\d{8})", os.path.basename(f)).group(1)
          for f in glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)
          if re.search(r"(\d{8})", os.path.basename(f))]
    return max(js) if js else None


def signaux_l3(df):
    """Les déclencheurs de la SPEC gelée. H3-VPOC seule testable ; les autres
    tournent en ombre — tous journalisés, dédoublonnés par (barre, sens)."""
    out, vus = [], set()
    for nom, fn in {"H3": H.h3, "H6": H.h6, "H7": H.h7, "H8": H.h8}.items():
        for _c, (cond, side) in fn(df).items():
            for i in range(len(df)):
                try:
                    if bool(cond.iloc[i]) and (i, side) not in vus:
                        vus.add((i, side))
                        out.append((i, side, nom))
                except Exception:
                    break
    return sorted(out)


def contrat_ok(sym, jour):
    """Le contrat du fichier est-il un contrat attendu ? Lu, pas suppose."""
    fs = sorted(glob.glob("DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)))
    if not fs:
        return None
    for ln in open(fs[0], encoding="utf-8", errors="ignore"):
        if ln[:1] == "{":
            try:
                c = json.loads(ln).get("contract", "")
            except ValueError:
                continue
            return any(x in str(c) for x in CONTRATS_ATTENDUS)
    return None


def courir(jour, strict=False, minutes=15):
    chemin = "LOGS/entonnoir/entonnoir_%s.jsonl" % jour
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    if os.path.exists(chemin):
        os.remove(chemin)          # le jour se rejoue entier, jamais en append
    total = 0
    for sym in ("ES", "NQ"):
        df = charger_jour(sym, jour, minutes)
        if df.empty or len(df) < 6:
            print("  %s : pas de barres cash exploitables" % sym)
            continue
        manquantes = lecture.verifier_colonnes(df, ("L0", "L5"))
        if manquantes:
            print("  %s : COLONNES MANQUANTES %s — jour NON couru, incident"
                  % (sym, manquantes))
            continue
        live = {"contrat_actif": contrat_ok(sym, jour), "rollover": False}
        sig = signaux_l3(df)
        retenus = chaine.appliquer([(i, s) for i, s, _n in sig], df, sym,
                                   journal=chemin, hypothese="ombre1",
                                   strict=strict, live=live)
        total += len(sig)
        print("  %s : %d signaux L3, %d retenus par L0/L5 -> %s"
              % (sym, len(sig), len(retenus), chemin))
    if total == 0:
        print("  AUCUN SIGNAL sur la journee — verifier avec pourquoi.py que ce")
        print("  n'est pas une couche muette (le journal existe quand meme).")
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
