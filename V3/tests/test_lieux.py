"""Le lieu dans la ligne PASSE (V1-lesson 4, passe du 10/09).

    python -X utf8 V3/tests/test_lieux.py

Ce que ça prouve, écrit avant :
  1. Synthétique : H3 short → `cur_vah` = close + d·tick ; H3 long → `cur_val`
     = close + d·tick AUSSI (la convention est une, mesurée : review R1) ;
     H6p → bande [−P15 ; +P05] (la borne active est P15) ; H2p → bande
     asymétrique ; H8p → seuls les niveaux à ≤ P20 ; famille hors des quatre
     / df sans recalculs / atr_ref absent / close absent → `lieux: None` AVEC
     motif, jamais sans.
  2. Réel (14/07, ES et NQ) : `close + dist_cur_val·tick == cur_val_lvl` et
     idem VAH sur le brut 1 min (≥ 99,9 %) — la mesure qui aurait attrapé
     R1 ; chaque signal des quatre a un lieu non vide ; pour H3-VPOC,
     |dist| ≤ seuil (le lieu est la bande, par construction).
  3. Sur le vrai chemin : `chaine.appliquer` écrit `lieux`, `seuil_ticks`,
     `bande_ticks`, `close` sur CHAQUE ligne du signal, et `lieux_motif` sur
     un signal hors des quatre. Aucune décision ne change.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3 import chaine, lieux                                  # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min, signaux_l3  # noqa: E402

PASSED = FAILED = 0
JOUR = "20260714"        # ES 2 + NQ 3 signaux des quatre (dont 2 le matin)


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-62s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def synth(**cols):
    base = {"ts": [1788960600000], "jour": ["20260909"], "close": [100.0],
            "atr_barre": [np.nan], "atr_ref": [10.0], "atr_source": ["veille"]}
    base.update({k: [v] for k, v in cols.items()})
    return pd.DataFrame(base)


def main():
    # 1. synthetique (atr_ref 10 pts -> P05 2 t, P10 4 t, P15 6 t, P20 8 t)
    r = lieux.pour_signal(synth(dist_cur_vah=3.0), 0, "H3-VPOC", -1)
    check("[1a] H3 short : cur_vah = close + 3 t = 100.75, seuil 4, bande [-4, 4], close",
          r["lieux"] == [{"nom": "cur_vah", "prix": 100.75, "dist_ticks": 3.0}]
          and r["seuil_ticks"] == 4.0 and r["bande_ticks"] == [-4.0, 4.0]
          and r["close"] == 100.0, r)
    r = lieux.pour_signal(synth(dist_cur_val=2.0), 0, "H3-VPOC", +1)
    check("[1b] H3 long : cur_val = close + 2 t = 100.5 (meme convention, mesuree)",
          r["lieux"] == [{"nom": "cur_val", "prix": 100.5, "dist_ticks": 2.0}], r)
    r = lieux.pour_signal(synth(dist_ib_high=-3.0), 0, "H6p", +1)
    check("[1c] H6p long : ib_high = 99.25, seuil P05 = 2, bande [-6, 2] (P15 active)",
          r["lieux"] == [{"nom": "ib_high", "prix": 99.25, "dist_ticks": -3.0}]
          and r["seuil_ticks"] == 2.0 and r["bande_ticks"] == [-6.0, 2.0], r)
    r = lieux.pour_signal(synth(dist_vwap_rth_sd2u_r=1.0), 0, "H2p", -1)
    check("[1d] H2p short : bande asymetrique [-6, 4]", r["bande_ticks"] == [-6.0, 4.0], r)
    r = lieux.pour_signal(synth(dist_pdh=2.0, dist_ovn_low=-50.0, dist_mq_put=-7.0),
                          0, "H8p", +1)
    noms = sorted(x["nom"] for x in (r["lieux"] or []))
    check("[1e] H8p : seuls les niveaux a <= P20 (pdh 2 t, mq_put -7 t ; ovn_low -50 exclu)",
          noms == ["mq_put", "pdh"] and r["seuil_ticks"] == 8.0
          and r["bande_ticks"] == [-8.0, 8.0], r)
    r = lieux.pour_signal(synth(dist_cur_vah=3.0), 0, "battement", 1)
    check("[1f] famille hors des quatre -> None + motif",
          r["lieux"] is None and r["lieux_motif"] == "famille_hors_quatre", r)
    r = lieux.pour_signal(synth(dist_cur_vah=3.0).drop(columns=["atr_ref"]), 0, "H3-VPOC", -1)
    check("[1g] df sans recalculs -> None + motif sans_recalculs",
          r["lieux"] is None and r["lieux_motif"] == "sans_recalculs", r)
    r = lieux.pour_signal(synth(dist_cur_vah=3.0, atr_ref=np.nan), 0, "H3-VPOC", -1)
    check("[1h] atr_ref absent -> None + motif", r["lieux_motif"] == "atr_ref_absent", r)
    r = lieux.pour_signal(synth(dist_cur_vah=3.0).drop(columns=["close"]), 0, "H3-VPOC", -1)
    check("[1i] close absent -> None + motif close_absent (seuil et bande quand meme)",
          r["lieux_motif"] == "close_absent" and r.get("bande_ticks") == [-4.0, 4.0], r)
    r = lieux.pour_signal(synth(), 0, "H3-VPOC", -1)
    check("[1j] niveau absent -> None + motif niveau_absent",
          r["lieux_motif"] == "niveau_absent" and r.get("seuil_ticks") == 4.0, r)

    # 2. reel : la convention contre les _lvl du brut, puis chaque signal a un lieu
    n_sig = n_lieu = n_h3_ok = n_h3 = 0
    frames, conv = {}, []
    for sym in ("ES", "NQ"):
        df, brut = charger_jour(sym, JOUR, 15, avec_1min=True)
        if df.empty:
            continue
        for col, lvl in (("dist_cur_val", "cur_val_lvl"), ("dist_cur_vah", "cur_vah_lvl")):
            if col in brut.columns and lvl in brut.columns:
                c = pd.to_numeric(brut["close"], errors="coerce")
                d = pd.to_numeric(brut[col], errors="coerce")
                lv = pd.to_numeric(brut[lvl], errors="coerce")
                ok = c.notna() & d.notna() & lv.notna()
                conv.append(float(((c + d * 0.25 - lv).abs() <= 0.01)[ok].mean()))
        df = injecter_recalculs(pd.concat(chauffe_1min(sym, JOUR) + [brut[COLS_RECALC]],
                                          ignore_index=True), df, minutes=15)
        sig, _c = signaux_l3(df)
        frames[sym] = (df, sig)
        for i, side, fam in sig:
            r = lieux.pour_signal(df, i, fam, side)
            n_sig += 1
            n_lieu += r["lieux"] is not None
            if fam == "H3-VPOC" and r["lieux"]:
                n_h3 += 1
                n_h3_ok += abs(r["lieux"][0]["dist_ticks"]) <= r["seuil_ticks"]
    check("[2a] brut %s : close + dist_cur_val/vah x tick == cur_val/vah_lvl (>= 99,9 %%)" % JOUR,
          len(conv) == 4 and min(conv) >= 0.999, ["%.4f" % x for x in conv])
    check("[2b] %s : %d signaux des quatre, tous avec un lieu" % (JOUR, n_sig),
          n_sig > 0 and n_lieu == n_sig, "%d/%d" % (n_lieu, n_sig))
    check("[2c] H3-VPOC : |dist| <= seuil sur les %d (le lieu EST la bande)" % n_h3,
          n_h3 > 0 and n_h3_ok == n_h3, "%d/%d" % (n_h3_ok, n_h3))

    # 3. sur le vrai chemin (chaine) : l'instrument qui a le plus de signaux
    sym = max(frames, key=lambda s: len(frames[s][1]))
    df, sig = frames[sym]
    live = {"contrat_actif": True, "rollover": False}
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(chemin)
    try:
        chaine.appliquer(sig, df, sym, journal=chemin, strict=False, live=live)
        L = [json.loads(ln) for ln in open(chemin, encoding="utf-8") if ln.strip()]
        os.remove(chemin)
        chaine.appliquer([(10, 1)], df, sym, journal=chemin, hypothese="test",
                         strict=False, live=live)
        L2 = [json.loads(ln) for ln in open(chemin, encoding="utf-8") if ln.strip()]
    finally:
        if os.path.exists(chemin):
            os.remove(chemin)
    cles = ("lieux", "seuil_ticks", "bande_ticks", "close")
    check("[3a] chaine %s %s : %d lignes, toutes avec lieux/seuil/bande/close" % (sym, JOUR, len(L)),
          bool(L) and all(all(o.get(k) is not None for k in cles) for o in L),
          [(o["motif"], o.get("lieux_motif")) for o in L if not o.get("lieux")][:3])
    check("[3b] un signal hors des quatre : lieux None + lieux_motif sur chaque ligne",
          bool(L2) and all(o.get("lieux") is None and o.get("lieux_motif") for o in L2),
          [o.get("lieux_motif") for o in L2][:3])
    passes = sorted(o["snapshot_id"] for o in L if o["decision"] == "PASSE")
    check("[3c] les PASSE sont ceux de la campagne (le lieu ne decide rien)",
          len(passes) == len(set(passes)) and len(passes) <= len(sig), passes)

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
