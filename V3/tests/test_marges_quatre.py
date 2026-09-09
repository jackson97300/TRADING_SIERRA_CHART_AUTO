"""Brique 2 (Fable 09/09) — les marges des quatre : l'exposition ne décide rien.

    python -X utf8 V3/tests/test_marges_quatre.py

Ce que ça prouve, écrit avant :
  1. PARITÉ barre à barre, journées RÉELLES, ES et NQ, les quatre, les deux
     côtés : (lieu & porte & régime & réactions) recomposé == la fonction
     GELÉE. Zéro écart, sinon l'exposition ment.
  2. Les ÉTATS sur du synthétique H3 : QUASI (3 t hors d'une bande de 4 t),
     LIEU_REAGI (tout y est), LIEU_SANS_REACTION avec le manque nommé
     (« finish »), et H6p LIEU_IMPOSSIBLE(porte_jamais_ouverte).
  3. Le DÉNOMINATEUR : une journée muette réelle rend une ligne par
     hypothèse × instrument (8), aucune LIEU_REAGI, aucune clé de devenir.
  4. IDEMPOTENCE : deux runs, un seul hash.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research import hypotheses as H                     # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3 import marges_quatre as MQ                            # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min             # noqa: E402

PASSED = FAILED = 0
INTERDITES = ("pnl", "issue", "prix_entree", "prix_sortie", "sl_prix", "tp_prix",
              "devenir", "gain", "rendement")


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-52s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def synth(**cols):
    base = {"ts": [1_788_960_600_000], "jour": ["20260909"], "close": [100.0],
            "high": [100.0], "low": [100.0], "finish_delta_pct": [0.5],
            "atr_barre": [np.nan], "atr_ref": [10.0], "atr_source": ["veille"],
            "dist_cur_vah": [200.0], "dist_cur_val": [200.0],
            "ib_broken_up": [0], "ib_broken_dn": [0]}
    base.update({k: [v] for k, v in cols.items()})
    return pd.DataFrame(base)


def main():
    # 1. parité réelle
    ecarts, barres = 0, 0
    for jour in ("20260903", "20260904", "20260909"):
        for sym in ("ES", "NQ"):
            df, brut = charger_jour(sym, jour, 15, avec_1min=True)
            if df.empty:
                continue
            df = injecter_recalculs(pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                                              ignore_index=True), df, minutes=15)
            expo = MQ.exposer(df)
            for hyp, fn in H.LES_QUATRE.items():
                gelee = fn(df)
                for cote, e in expo[hyp].items():
                    a = MQ.recomposer(e).to_numpy()
                    b = gelee[cote][0].fillna(False).astype(bool).to_numpy()
                    ecarts += int((a != b).sum())
                    barres += len(a)
    check("[1] parité recomposé == gelé (%d barres x côtés)" % barres,
          barres > 0 and ecarts == 0, "%d écarts" % ecarts)

    # 2. états synthétiques H3 (atr_ref 10 pts -> P10 = 4 ticks)
    df = synth(dist_cur_vah=7.0)
    r = MQ.resumer(df, "H3-VPOC", MQ.exposer(df)["H3-VPOC"], H.h3)
    check("[2a] 3 t hors bande 4 t -> QUASI, marge 3, seuil 4, côté short",
          r["etat"] == "QUASI" and r["lieu_min_ticks"] == 3.0 and r["seuil_ticks"] == 4.0
          and r["cote"] == "short" and r["atr_source"] == "veille", r)
    df = synth(dist_cur_vah=2.0, high=101.0, finish_delta_pct=0.2)
    r = MQ.resumer(df, "H3-VPOC", MQ.exposer(df)["H3-VPOC"], H.h3)
    check("[2b] lieu + mèche + clôture dedans + finish -> LIEU_REAGI, 1 signal",
          r["etat"] == "LIEU_REAGI" and r["n_signaux"] == 1, r)
    df = synth(dist_cur_vah=2.0, high=101.0, finish_delta_pct=0.5)
    r = MQ.resumer(df, "H3-VPOC", MQ.exposer(df)["H3-VPOC"], H.h3)
    check("[2c] lieu sans finish -> LIEU_SANS_REACTION, manque = finish",
          r["etat"] == "LIEU_SANS_REACTION" and r["reaction_manquante"] == "finish"
          and r["n_barres_lieu"] == 1 and r["lieu_atteint"], r)
    df = synth(dist_ib_high=0.0)
    r = MQ.resumer(df, "H6p", MQ.exposer(df)["H6p"], H.h6_prime)
    check("[2d] H6p sans cassure d'IB -> LIEU_IMPOSSIBLE(porte_jamais_ouverte)",
          r["etat"] == "LIEU_IMPOSSIBLE" and r["motif"] == "porte_jamais_ouverte", r)
    df = synth(dist_cur_vah=100.0)
    r = MQ.resumer(df, "H3-VPOC", MQ.exposer(df)["H3-VPOC"], H.h3)
    check("[2e] 96 t hors bande -> JOUR_MUET(lieu_loin)",
          r["etat"] == "JOUR_MUET" and r["motif"] == "lieu_loin", r)
    df = synth(atr_ref=np.nan, atr_source="aucun")
    r = MQ.resumer(df, "H3-VPOC", MQ.exposer(df)["H3-VPOC"], H.h3)
    check("[2f] atr_ref NaN -> LIEU_IMPOSSIBLE(atr_ref_absent)",
          r["etat"] == "LIEU_IMPOSSIBLE" and r["motif"] == "atr_ref_absent", r)

    # 3. dénominateur sur la journée muette réelle + 4. idempotence
    jour = "20260909"
    MQ.courir(jour)
    p = "LOGS/marges/marges_quatre_%s.jsonl" % jour
    h1 = hashlib.sha256(open(p, "rb").read()).hexdigest()
    lignes = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    corps = [o for o in lignes if o["type"] == "marge_quatre"]
    check("[3a] 1 entête + 8 lignes (4 hypothèses x 2 instruments)",
          lignes[0]["type"] == "entete" and len(corps) == 8, len(corps))
    check("[3b] aucune LIEU_REAGI le 09/09 (0 signal des quatre ce jour)",
          all(o["etat"] != "LIEU_REAGI" for o in corps),
          [(o["sym"], o["hypothese"], o["etat"]) for o in corps])
    check("[3c] états dans la liste déclarée",
          all(o["etat"] in MQ.ETATS for o in corps))
    cles = {k for o in corps for k in o}
    check("[3d] aucune clé de devenir",
          not any(any(m in k for m in INTERDITES) for k in cles), sorted(cles))
    MQ.courir(jour)
    h2 = hashlib.sha256(open(p, "rb").read()).hexdigest()
    check("[4] idempotent (deux runs, un hash)", h1 == h2)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
