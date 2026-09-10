"""Le lot des 57 jours, tel que les mesures du module SCÉNARIOS le lisent.

    from V3.scenarios import lot
    for jour, df15, brut in lot.journees("ES"):
        ...

`df15` est la journée cash en 15 min (`charger_jour`) avec le mètre de la
chaîne ajouté : `atr_ref` = `atr_barre` si fini, sinon `atr_veille` (médiane
ATR de la dernière session complète — brique 1), et `atr_source`. Sans lui,
les journées à trou d'ATR (09/09) rendent des largeurs `None` et des fiches
F23 vides — le silence de colonne vide, pas une mesure.

La chauffe 1 min est limitée à trois journées : `atr_veille` ne lit que la
dernière session complète, la chauffe de vingt jours de `rvol_r` n'a rien à
faire ici (et c'est elle qui rend `mesure_open_type` lent). Les MESURES lisent
ce frame-ci (les trois mesures de la grammaire ne lisent pas `setups_armes`) ;
l'écrivain et le rejeu du soir lisent `scenarios.charger`, le frame de la
chaîne avec `rvol_r` et les bandes SD2 injectées.
"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                      # noqa: E402
from CORE.features import recalc                                # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min, jours_disponibles  # noqa: E402

TICK = 0.25
N_JOURS_CHAUFFE_ATR = 3
BARRES_MIN = 20          # une journée cash qui n'a pas ses 20 barres 15 min ne compte pas


def atr_veille(sym, jour, brut):
    b = pd.concat(chauffe_1min(sym, jour, N_JOURS_CHAUFFE_ATR) + [brut[COLS_RECALC]],
                  ignore_index=True)
    v = recalc.atr_veille_15(b, pd.to_datetime(b["ts"], unit="ms", utc=True), minutes=15)
    x = v.get(date(int(jour[:4]), int(jour[4:6]), int(jour[6:8])), float("nan"))
    return float(x) if x == x else None


def avec_metre(df15, veille):
    """`atr_ref` / `atr_source` comme la chaîne (lecture.py) les lit."""
    a = pd.to_numeric(df15.get("atr_barre"), errors="coerce") if "atr_barre" in df15 else \
        pd.Series(np.nan, index=df15.index)
    ref = a.where(np.isfinite(a), veille if veille is not None else np.nan)
    src = np.where(np.isfinite(a), "barre", "veille" if veille is not None else "aucun")
    return df15.assign(atr_ref=ref, atr_source=src)


def journees(sym, jours=None):
    """Itère (jour, df15 avec atr_ref, brut 1 min) sur le lot ; saute et
    signale les journées trop courtes."""
    os.chdir(RACINE)
    for jour in (jours or jours_disponibles(sym)):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or brut.empty or len(df) < BARRES_MIN:
            print("   %s %s : %d barres, ignoree" % (sym, jour, len(df)))
            continue
        yield jour, avec_metre(df, atr_veille(sym, jour, brut)), brut


def seuils():
    """`scenarios/seuils.yaml`, tel quel — la seule source des nombres du module
    (règle dure : aucun seuil dans le code ; `null` = pas fixé = None)."""
    import yaml
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seuils.yaml"),
              encoding="utf-8") as f:
        return yaml.safe_load(f)


def quantiles(valeurs, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    v = np.asarray([x for x in valeurs if x is not None and np.isfinite(x)], dtype=float)
    if len(v) == 0:
        return {q: None for q in qs}
    return {q: float(np.quantile(v, q)) for q in qs}


def fmt(x, nd=2):
    return "—" if x is None else ("%.*f" % (nd, x))
