"""La carte du matin (brique 3) et son tirage en aveugle.

    python -X utf8 V3/tests/test_carte_matin.py

Ce que ça prouve, écrit avant :
  1. Le tirage est DÉTERMINISTE (deux appels, même réponse), par BLOCS d'une
     semaine (les 7 jours d'une semaine ont la même réponse), 50/50 sur huit
     blocs (4 visibles / 4 non), et avant DEBUT → jamais visible.
  2. À 9h25 — un brut qui n'a que sa NUIT Globex (la condition réelle, review
     R1) : la carte se génère avec un mètre (atr_veille de la dernière session
     complète, lue malgré l'absence de cash), porte les quatre avec prix et
     bande, les dix de H8p, les repères ; le journal manuel reçoit
     `carte_visible` (gabarit créé si absent) et rien d'autre ne bouge.
  3. Un brut qui porte déjà une barre CASH → carte TARDIVE, rc 2, rien au
     journal (review R2) ; `--forcer` n'écrit rien au journal non plus ; la
     bande en prix = bande en ticks × 0,25.
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3 import carte_matin as CM                              # noqa: E402

PASSED = FAILED = 0
JOUR = "20260910"


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-64s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def brut(debut_utc, n, close=7650.0):
    """Un brut 1 min du 10/09 avec ce que la carte lit : OHLC, COLS_RECALC,
    les dist_* des quatre et des reperes, un `_lvl`."""
    t0 = pd.Timestamp("2026-09-10 %s" % debut_utc, tz="UTC")
    ts = [int((t0 + pd.Timedelta(minutes=k)).value // 1_000_000) for k in range(n)]
    rng = np.random.default_rng(1)
    c = close + np.cumsum(rng.normal(0, 0.25, n))
    d = pd.DataFrame({"ts": ts, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c,
                      "total_vol": 100, "delta_bar": 0.0, "contract": "ESU26-CME",
                      "dist_cur_vah": 12.0, "dist_cur_val": -20.0, "dist_prev_vah": 40.0,
                      "dist_prev_val": -36.0, "dist_prev_vpoc": 8.0, "dist_pdh": 300.0,
                      "dist_pdl": -90.0, "dist_ovn_high": 60.0, "dist_ovn_low": -14.0,
                      "dist_mq_call": 600.0, "dist_mq_put": 0.0, "dist_mq_hvl": 40.0})
    d["prev_vah_lvl"] = 7658.5
    return d


def main():
    check("[1a] deterministe", CM.carte_visible(JOUR) == CM.carte_visible(JOUR))
    sem = [CM.carte_visible((CM.DEBUT + timedelta(days=k)).strftime("%Y%m%d")) for k in range(7)]
    check("[1b] les 7 jours d'une semaine ont la meme reponse", len(set(sem)) == 1, sem)
    blocs = [CM.carte_visible((CM.DEBUT + timedelta(days=7 * k)).strftime("%Y%m%d"))
             for k in range(CM.BLOCS)]
    check("[1c] 4 visibles / 4 non sur les 8 premiers blocs", sum(blocs) == 4, blocs)
    blocs2 = [CM.carte_visible((CM.DEBUT + timedelta(days=7 * k)).strftime("%Y%m%d"))
              for k in range(CM.BLOCS, 2 * CM.BLOCS)]
    check("[1d] 4 / 4 aussi sur les 8 suivants (meme generateur)", sum(blocs2) == 4, blocs2)
    check("[1e] avant DEBUT -> jamais visible",
          CM.carte_visible((CM.DEBUT - timedelta(days=1)).strftime("%Y%m%d")) is False)

    ancien_j, ancien_d = CM.JOURNAL, CM.DOSSIER
    nuit = {"ES": brut("04:00", 240), "NQ": brut("04:00", 240, close=29400.0)}
    cash = {"ES": brut("14:00", 30), "NQ": brut("14:00", 30, close=29400.0)}
    with tempfile.TemporaryDirectory() as tmp:
        CM.JOURNAL, CM.DOSSIER = os.path.join(tmp, "journal"), os.path.join(tmp, "carte")
        try:
            # 2. nuit seule = 9h25
            rc = CM.courir(JOUR, bruts=nuit)
            vis = CM.carte_visible(JOUR)
            p = os.path.join(CM.DOSSIER, "" if vis else "aveugle", "carte_%s.txt" % JOUR)
            txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            check("[2a] nuit seule : rc 0, carte ecrite (%s)" % ("visible" if vis else "aveugle/"),
                  rc == 0 and bool(txt), (rc, p))
            check("[2b] un METRE existe pour ES et NQ (atr_veille lue sans cash)",
                  txt.count("mètre atr_veille") == 2 and "pas de metre" not in txt, txt[:300])
            check("[2c] les quatre avec prix + bande, H8p, reperes (prev_vah via _lvl)",
                  all(k in txt for k in ("H3-VPOC", "cur_vah", "bande [", "H8p", "REPERES",
                                          "prev_vah   : 7658.50  (lvl)")), txt[:600])
            check("[2d] pas TARDIVE", "TARDIVE" not in txt)
            pj = os.path.join(CM.JOURNAL, "%s.md" % JOUR)
            tj = open(pj, encoding="utf-8").read() if os.path.exists(pj) else ""
            check("[2e] journal : gabarit cree, `carte_visible` = le tirage (%s)" % vis,
                  ("`carte_visible` : %s" % str(vis).lower()) in tj and "heure_et" in tj)
            open(pj, "a", encoding="utf-8").write("\n| 11:15 | ES | long | 7630 | 7640 | TP | test |\n")
            CM.courir(JOUR, bruts=nuit)
            tj2 = open(pj, encoding="utf-8").read()
            check("[2f] relance : une seule ligne carte_visible, la ligne du trader intacte",
                  tj2.count("`carte_visible`") == 1 and "| 11:15 | ES |" in tj2)
            # 3. tardive / forcee
            os.remove(pj)
            rc = CM.courir(JOUR, bruts=cash)
            pt = os.path.join(CM.DOSSIER, "carte_%s.txt" % JOUR)
            tt = open(pt, encoding="utf-8").read() if os.path.exists(pt) else ""
            check("[3a] une barre CASH deja la -> TARDIVE, rc 2, carte etiquetee, journal intact",
                  rc == 2 and "TARDIVE" in tt and not os.path.exists(pj), (rc, tt[:120]))
            rc = CM.courir(JOUR, forcer=True, bruts=nuit)
            check("[3b] --forcer : rc 0, affiche, n'ecrit RIEN au journal",
                  rc == 0 and not os.path.exists(pj))
        finally:
            CM.JOURNAL, CM.DOSSIER = ancien_j, ancien_d
    check("[3c] bande en prix = ticks x tick (P10 sur atr 10 = ±1.00)",
          CM._bande_prix(10.0, "H3-VPOC", 1) == (-1.0, 1.0), CM._bande_prix(10.0, "H3-VPOC", 1))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
