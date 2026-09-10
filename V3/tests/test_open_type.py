"""SCENARIOS, prérequis 1 — `recalc.open_type_r`, le type d'ouverture Dalton.

    python -X utf8 V3/tests/test_open_type.py

Ce que ça prouve, écrit avant (définition dans la docstring de la fonction) :
  1. DRIVE : deux clôtures du même côté hors bande, O = l'extrême, pas de retour.
  2. TEST_DRIVE : la barre 1 traverse la bande des deux côtés puis clôture d'un
     côté, la barre 2 continue sans retour ; ou barre 1 indécise + barre 2 partie.
  3. REJET_RENVERSEMENT : barre 1 d'un côté, barre 2 clôture de l'autre.
  4. ENCHERE : clôtures dans la bande ; ou parti puis revenu sur O.
  5. Miroir LONG/SHORT ; `open_lvl` l'emporte sur l'open de la barre 0 ; moins
     de deux barres ou atr absent → type None AVEC motif ; la bande est P10
     (0,10 × atr / tick, plancher 2 t) — aucun autre seuil.
  6. Réel : ES et NQ 09/09 rendent un des quatre types, champs cohérents.
"""
import os
import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402

PASSED = FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-64s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def deux(b1, b2):
    """(open, high, low, close) x 2 -> df15 de deux barres."""
    return pd.DataFrame([dict(zip(("open", "high", "low", "close"), b1)),
                         dict(zip(("open", "high", "low", "close"), b2))])


def main():
    atr = 10.0                    # P10 = 4 t = 1,00 pt de bande
    t = lambda df, **k: recalc.open_type_r(df, atr, **k)["type"]   # noqa: E731
    # 1. DRIVE (O = 100 est le bas ; les deux cloturent au-dessus, pas de retour)
    check("[1a] DRIVE haussier", t(deux((100, 103, 99.5, 102.5), (102.5, 105, 102, 104.5))) == "DRIVE")
    check("[1b] DRIVE baissier (miroir)",
          t(deux((100, 100.5, 97, 97.5), (97.5, 98, 95, 95.5))) == "DRIVE")
    # 2. TEST_DRIVE : la barre 1 va d'abord sous O - bande, puis cloture au-dessus
    check("[2a] TEST_DRIVE haussier (traversee barre 1)",
          t(deux((100, 103, 98.5, 102.5), (102.5, 105, 102, 104.5))) == "TEST_DRIVE")
    check("[2b] TEST_DRIVE : barre 1 indecise, barre 2 partie sans retour",
          t(deux((100, 101, 99.2, 100.5), (100.5, 104, 100.4 + 1.0, 103.5))) == "TEST_DRIVE")
    # 3. REJET_RENVERSEMENT : barre 1 au-dessus, barre 2 cloture en dessous
    check("[3a] REJET_RENVERSEMENT (haut puis bas)",
          t(deux((100, 103, 99.5, 102.5), (102.5, 103, 97, 97.5))) == "REJET_RENVERSEMENT")
    check("[3b] REJET_RENVERSEMENT (bas puis haut, miroir)",
          t(deux((100, 100.5, 97, 97.5), (97.5, 103, 97, 102.5))) == "REJET_RENVERSEMENT")
    # 4. ENCHERE
    check("[4a] ENCHERE : clotures dans la bande",
          t(deux((100, 101, 99, 100.5), (100.5, 101.2, 99.3, 99.8))) == "ENCHERE")
    check("[4b] ENCHERE : parti puis revenu sur O (retour barre 2)",
          t(deux((100, 103, 99.5, 102.5), (102.5, 103, 100.5, 102.2))) == "ENCHERE")
    # 5. details
    r = recalc.open_type_r(deux((100, 103, 99.5, 102.5), (102.5, 105, 102, 104.5)), atr)
    check("[5a] champs : direction +1, ext_b1 10 t, ext_b2 18 t, bande 4 t, pas de retour",
          r["direction"] == 1 and r["ext_b1_ticks"] == 10.0 and r["ext_b2_ticks"] == 18.0
          and r["bande_ticks"] == 4.0 and r["retour_ouverture"] is False, r)
    r = recalc.open_type_r(deux((100, 103, 99.5, 102.5), (102.5, 105, 102, 104.5)), atr,
                           open_lvl=99.0)
    check("[5b] open_lvl l'emporte sur l'open de la barre 0 (ext_b1 = 14 t)",
          r["open_cash"] == 99.0 and r["ext_b1_ticks"] == 14.0, r)
    check("[5c] une seule barre -> None + motif",
          recalc.open_type_r(deux((100, 103, 99.5, 102.5), (0, 0, 0, 0)).iloc[:1], atr)["motif"]
          == "moins_de_deux_barres")
    check("[5d] atr absent -> None + motif",
          recalc.open_type_r(deux((100, 103, 99.5, 102.5), (102.5, 105, 102, 104.5)), None)["motif"]
          == "atr_ref_absent")
    check("[5e] bande = P10 avec plancher 2 t (atr 1 pt -> 2 t)",
          recalc.open_type_r(deux((100, 103, 99.5, 102.5), (102.5, 105, 102, 104.5)), 1.0)["bande_ticks"]
          == 2.0)
    # 6. reel
    for sym in ("ES", "NQ"):
        df = charger_jour(sym, "20260909", 15)
        if df.empty:
            check("[6] %s 09/09 indisponible" % sym, False)
            continue
        r = recalc.open_type_r(df, 10.0 if sym == "ES" else 60.0)
        check("[6] %s 09/09 : type %s, direction %s, ext_b1 %s t" % (sym, r["type"], r.get("direction"),
                                                                     r.get("ext_b1_ticks")),
              r["type"] in recalc.OPEN_TYPES and r["motif"] is None, r)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
