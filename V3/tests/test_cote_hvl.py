"""SCENARIOS — le signe de `cote_hvl` (Fable, 10/09, réponse 10) : prouvé sur
des barres RÉELLES, parce que c'est exactement le genre de signe qui
s'inverse en silence.

    python -X utf8 V3/tests/test_cote_hvl.py

Convention `dist_* = niveau - close` (en ticks, mesurée à 100 % contre les
`_lvl`, CONVENTIONS §8) : `dist_mq_hvl < 0` = le HVL est SOUS le prix = prix
au-dessus du HVL = gamma positif. Le brut porte `bool_above_mq_hvl` (C++) :
les deux doivent dire la même chose sur chaque barre où le HVL existe, sur
les deux instruments — c'est la parité qui prouve le signe, pas un exemple.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from V3.scenarios import scenarios                             # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-70s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def cote_hvl(dist):
    """Version VECTORISEE, pour la parite de masse sur les barres 1 min
    seulement. Elle n'est PAS la reference : la reference est
    `scenarios._cote_hvl`, et les tests [0*] verifient que les deux disent la
    meme chose. Jusqu'au 11/09 ce fichier ne testait que cette copie — la
    fonction de production pouvait deriver sans faire echouer un seul test."""
    d = pd.to_numeric(dist, errors="coerce")
    return np.where(~np.isfinite(d) | (d == 0), 0, np.where(d < 0, 1, -1))


def _frame(valeurs):
    return pd.DataFrame({"dist_mq_hvl": valeurs})


def main():
    for sym in ("ES", "NQ"):
        _, brut = charger_jour(sym, "20260909", 15, avec_1min=True)
        if brut.empty or "bool_above_mq_hvl" not in brut.columns or "dist_mq_hvl" not in brut.columns:
            check("[%s] brut du 09/09 avec dist_mq_hvl et bool_above_mq_hvl" % sym, False)
            continue
        d = pd.to_numeric(brut["dist_mq_hvl"], errors="coerce")
        b = pd.to_numeric(brut["bool_above_mq_hvl"], errors="coerce")
        m = np.isfinite(d) & (d != 0) & np.isfinite(b)
        c = cote_hvl(d[m])
        attendu = np.where(b[m] > 0, 1, -1)
        parite = float((c == attendu).mean()) if m.sum() else 0.0
        check("[%s] cote_hvl (dist < 0 = au-dessus) == bool_above_mq_hvl sur %d barres 1 min : %.1f %%"
              % (sym, int(m.sum()), 100 * parite), m.sum() > 300 and parite == 1.0,
              (int(m.sum()), parite))
        # et le niveau reconstruit est bien d'un seul cote du close
        close = pd.to_numeric(brut["close"], errors="coerce")
        niveau = close + d * 0.25
        au_dessus = (close > niveau)[m]
        check("[%s] close > niveau reconstruit <=> cote +1 (par construction, 100 %%)" % sym,
              bool(((au_dessus.values) == (c == 1)).all()))
    # --- les TROIS etats de la fonction de PRODUCTION (revision 11/09) -------
    # Avant : colonne absente, NaN et prix pile sur le HVL rendaient tous `0`.
    # Un capteur mort etait alors compte comme une mesure, et toute force qui
    # compte les composantes mesurees MONTAIT quand le capteur mourait.
    prod = scenarios._cote_hvl
    check("[0a] colonne absente -> None (on ne SAIT pas)",
          prod(pd.DataFrame({"close": [1.0]}), 0) is None)
    check("[0b] distance NaN -> None (on ne SAIT pas)",
          prod(_frame([np.nan]), 0) is None)
    check("[0c] distance nulle -> 0 (prix SUR le HVL : une mesure, pas un trou)",
          prod(_frame([0.0]), 0) == 0)
    check("[0d] dist < 0 -> +1 au-dessus ; dist > 0 -> -1 en dessous",
          prod(_frame([-3.0]), 0) == 1 and prod(_frame([8.0]), 0) == -1)
    check("[0e] None et 0 ne sont PAS le meme etat",
          prod(_frame([np.nan]), 0) is not prod(_frame([0.0]), 0))
    ref = list(cote_hvl(pd.Series([-3.0, 8.0])))
    check("[0f] production == reference vectorisee sur les cas non degeneres",
          [prod(_frame([-3.0]), 0), prod(_frame([8.0]), 0)] == ref, ref)
    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
