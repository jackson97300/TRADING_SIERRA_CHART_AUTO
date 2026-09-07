"""Les HUIT CAS par setup C2 actif — règle 15 complétée : « actif = coureur
le soir même ET huit cas verts ».

    python -X utf8 V3/layers/L3_declencheurs/test_ombre_c2.py

Par setup actif, LONG/SHORT en miroir × {lieu + réaction → signal, lieu seul
→ épisode muet, hors régime → rien, colonne absente → rien ET rendue}.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.layers.L3_declencheurs import ombre_c2 as OC2         # noqa: E402


def _frame(ouverture, closes, vah_ticks=40.0, val_ticks=-40.0):
    """Journée synthétique : VA veille reconstruite = close + dist × 0,25.
    On pose dist tel que VAH = 110 et VAL = 90 quel que soit le close."""
    lignes = []
    for i, c in enumerate(closes):
        lignes.append({"ts": 1_000_000 + i * 900_000, "jour": "2026-09-03",
                       "open": ouverture if i == 0 else c,
                       "close": c,
                       "dist_prev_vah": (110.0 - c) / 0.25,
                       "dist_prev_val": (90.0 - c) / 0.25})
    return pd.DataFrame(lignes)


def _run(df):
    import tempfile
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        open(chemin, "w").close()
        return OC2.journaliser(df, "ES", "20260903", chemin)
    finally:
        os.remove(chemin)


def main():
    e = []

    # --- registre : un actif est declare, code, et dans le brief ------------
    for nom in OC2.ACTIFS:
        if nom not in OC2.LES_C2:
            e.append("ACTIF %s hors du registre LES_C2" % nom)
        if nom not in OC2.SETUPS:
            e.append("ACTIF %s sans fonction — regle 15" % nom)

    # --- les huit cas de C2_80PCT -------------------------------------------
    # 1. SHORT : ouverture au-dessus (120), deux clotures dedans -> 1 signal
    n, m, a = _run(_frame(120.0, [115.0, 105.0, 104.0]))
    if n != 1:
        e.append("SHORT lieu+reaction : attendu 1 signal, obtenu %d" % n)
    # 2. SHORT lieu seul : UNE cloture dedans puis ressort -> 0 signal, muet
    n, m, a = _run(_frame(120.0, [115.0, 105.0, 115.0]))
    if n != 0 or m < 1:
        e.append("SHORT lieu seul : attendu 0 signal + episode muet (%d/%d)"
                 % (n, m))
    # 3. LONG : ouverture en dessous (80), deux clotures dedans -> 1 signal
    n, m, a = _run(_frame(80.0, [85.0, 95.0, 96.0]))
    if n != 1:
        e.append("LONG lieu+reaction : attendu 1 signal, obtenu %d" % n)
    # 4. LONG lieu seul -> 0 signal, muet
    n, m, a = _run(_frame(80.0, [85.0, 95.0, 85.0]))
    if n != 0 or m < 1:
        e.append("LONG lieu seul : attendu 0 signal + episode muet (%d/%d)"
                 % (n, m))
    # 5-6. HORS REGIME : ouverture DANS la VA -> rien, meme avec clotures dedans
    for ouv, nom in ((100.0, "ouverture dans la VA"),):
        n, m, a = _run(_frame(ouv, [105.0, 104.0, 103.0]))
        if n != 0 or m != 0:
            e.append("%s : attendu 0 signal 0 muet (%d/%d)" % (nom, n, m))
    # 7. COLONNE ABSENTE : dist_prev_vah retiree -> rien, et RENDUE
    df = _frame(120.0, [115.0, 105.0, 104.0]).drop(columns=["dist_prev_vah"])
    n, m, a = _run(df)
    if n != 0 or "dist_prev_vah" not in a:
        e.append("colonne absente : attendu 0 signal + absence RENDUE "
                 "(%d, %s)" % (n, a))
    # 8. CIBLE = le bord oppose, en prix
    import json
    import tempfile
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        open(chemin, "w").close()
        OC2.journaliser(_frame(120.0, [115.0, 105.0, 104.0]), "ES",
                        "20260903", chemin)
        lignes = [json.loads(l) for l in open(chemin, encoding="utf-8")]
        sig = [l for l in lignes if "snapshot_id" in l][0]
        if sig["cible_prix"] != 90.0 or not sig["snapshot_id"].startswith("C2:"):
            e.append("signal : cible attendue 90.0 (VAL) et prefixe C2: "
                     "(obtenu %s / %s)" % (sig["cible_prix"], sig["snapshot_id"]))
    finally:
        os.remove(chemin)

    print("  ombre C2 — huit cas par setup actif (%d actif) : miroir, lieu "
          "seul,\n       hors regime, colonne absente rendue, cible, prefixe"
          % len(OC2.ACTIFS))
    if e:
        print("  %d ECHEC(S) :" % len(e))
        for x in e:
            print("     %s" % x)
        return 1
    print("  OK : un setup actif a sa preuve — regle 15 completee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
