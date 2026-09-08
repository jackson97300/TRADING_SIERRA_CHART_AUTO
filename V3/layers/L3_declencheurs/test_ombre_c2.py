"""Les HUIT CAS par setup C2 actif — règle 15 complétée : « actif = coureur
le soir même ET huit cas verts ».

    python -X utf8 V3/layers/L3_declencheurs/test_ombre_c2.py

Par setup actif, LONG/SHORT en miroir × {lieu + réaction → signal, lieu seul
→ épisode muet, hors régime / jour muet → motif, colonne absente → rien ET
rendue}. Chaque cas filtre le journal PAR SETUP : les actifs tournent tous à
chaque appel, un cas ne doit compter que les lignes du setup qu'il teste.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.layers.L3_declencheurs import ombre_c2 as OC2         # noqa: E402
from V3.layers.L3_declencheurs.cas_c2_niveaux import (        # noqa: E402
    cas_div, cas_poor)   # les cas DIV/POOR — scindes, garde des 300 lignes


def _frame(ouverture, closes, lows=None):
    """Journée 80 % : VA veille reconstruite = close + dist × 0,25, posée
    telle que VAH = 110 et VAL = 90. Les ts (epoch 1970) n'ont JAMAIS de
    barre 15h15 ET — C2_EOD y rend un jour muet, filtré par setup.
    `lows` : bas explicites (cas « la barre traverse la VA entière »)."""
    lignes = []
    for i, c in enumerate(closes):
        lignes.append({"ts": 1_000_000 + i * 900_000, "jour": "2026-09-03",
                       "open": ouverture if i == 0 else c,
                       "high": c, "low": lows[i] if lows else c, "close": c,
                       "dist_prev_vah": (110.0 - c) / 0.25,
                       "dist_prev_val": (90.0 - c) / 0.25})
    return pd.DataFrame(lignes)


def _frame_eod(barres, date="2026-09-03"):
    """Journée EOD : barres explicites (h_utc, m_utc, o, h, l, c). En EDT le
    cash ouvre 13:30 UTC et la barre EOD est 19:15 ; en EST (novembre),
    14:30 et 20:15. La VA est posée hors d'atteinte : C2_80PCT reste hors
    régime (ouverture dans la VA), zéro interférence entre setups."""
    lignes = []
    for (hh, mm, o, hi, lo, c) in barres:
        ts = int(pd.Timestamp("%s %02d:%02d" % (date, hh, mm),
                              tz="UTC").value // 1_000_000)
        lignes.append({"ts": ts, "jour": date, "open": o, "high": hi,
                       "low": lo, "close": c,
                       "dist_prev_vah": 4_000_000.0,
                       "dist_prev_val": -4_000_000.0})
    return pd.DataFrame(lignes)


def _run(df, setup):
    """(n_signaux, n_muets, absentes, lignes) — lignes du SEUL setup vise."""
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        open(chemin, "w").close()
        *_x, absentes = OC2.journaliser(df, "ES", "20260903", chemin)
        lignes = [json.loads(l) for l in open(chemin, encoding="utf-8")]
        lignes = [l for l in lignes if l.get("setup") == setup]
        n = sum(1 for l in lignes if "snapshot_id" in l)
        m = sum(1 for l in lignes if l.get("motif"))
        return n, m, absentes, lignes
    finally:
        os.remove(chemin)


JOUR_UP = [(13, 30, 100.0, 101.0, 99.5, 100.5), (17, 0, 101.0, 105.0, 100.0, 104.0),
           (19, 15, 105.0, 108.5, 104.5, 108.0), (19, 45, 108.0, 109.0, 107.0, 108.5)]
JOUR_DN = [(13, 30, 100.0, 100.5, 99.0, 99.5), (17, 0, 99.0, 100.0, 95.0, 96.0),
           (19, 15, 95.5, 95.5, 91.5, 92.0), (19, 45, 92.0, 93.0, 91.0, 92.5)]
JOUR_PLAT = [(13, 30, 100.0, 103.0, 97.0, 100.5), (17, 0, 101.0, 103.0, 97.0, 99.0),
             (19, 15, 99.5, 101.0, 99.0, 100.2), (19, 45, 100.2, 101.0, 99.0, 100.0)]


def cas_80pct(e):
    n, m, a, li = _run(_frame(120.0, [115.0, 105.0, 104.0]), "C2_80PCT")
    if n != 1:
        e.append("80PCT SHORT lieu+reaction : attendu 1 signal, obtenu %d" % n)
    n, m, a, li = _run(_frame(120.0, [115.0, 105.0, 115.0]), "C2_80PCT")
    if n != 0 or m < 1:
        e.append("80PCT SHORT lieu seul : attendu 0 signal + muet (%d/%d)" % (n, m))
    n, m, a, li = _run(_frame(80.0, [85.0, 95.0, 96.0]), "C2_80PCT")
    if n != 1:
        e.append("80PCT LONG lieu+reaction : attendu 1 signal, obtenu %d" % n)
    n, m, a, li = _run(_frame(80.0, [85.0, 95.0, 85.0]), "C2_80PCT")
    if n != 0 or m < 1:
        e.append("80PCT LONG lieu seul : attendu 0 signal + muet (%d/%d)" % (n, m))
    n, m, a, li = _run(_frame(100.0, [105.0, 104.0, 103.0]), "C2_80PCT")
    if n != 0 or m != 0:
        e.append("80PCT ouverture dans la VA : attendu 0/0 (%d/%d)" % (n, m))
    df = _frame(120.0, [115.0, 105.0, 104.0]).drop(columns=["dist_prev_vah"])
    n, m, a, li = _run(df, "C2_80PCT")
    if n != 0 or "dist_prev_vah" not in a:
        e.append("80PCT colonne absente : attendu 0 + absence RENDUE (%d, %s)"
                 % (n, a))
    n, m, a, li = _run(_frame(120.0, [115.0, 105.0, 104.0]), "C2_80PCT")
    sig = [l for l in li if "snapshot_id" in l][0]
    if sig["cible_prix"] != 90.0 or not sig["snapshot_id"].startswith("C2:"):
        e.append("80PCT signal : cible 90.0 (VAL) et prefixe C2: attendus "
                 "(%s / %s)" % (sig["cible_prix"], sig["snapshot_id"]))
    # audit Fable §3 : la ligne porte la fenetre de re-entree (dedans depuis
    # la barre 1, signal barre 2 -> 1.0) et « cible deja atteinte » a 0
    if (sig.get("fenetre_reentree_barres") != 1.0
            or sig.get("cible_atteinte_short") != 0.0):
        e.append("80PCT extras : fenetre=1.0 + cible_atteinte_short=0.0 "
                 "attendus (%s)" % sig)
    # ... et quand la barre du signal TRAVERSE la VA entiere (low 89 < VAL),
    # le flag cible_atteinte_short passe a 1 — journalise, jamais un trade
    n, m, a, li = _run(_frame(120.0, [115.0, 105.0, 104.0],
                              lows=[115.0, 105.0, 89.0]), "C2_80PCT")
    sig = [l for l in li if "snapshot_id" in l]
    if not sig or sig[0].get("cible_atteinte_short") != 1.0:
        e.append("80PCT traversee : cible_atteinte_short=1.0 attendu (%s)"
                 % (sig and sig[0]))


def cas_eod(e):
    # 1. LONG : journee en tendance haussiere -> 1 signal, side +1
    n, m, a, li = _run(_frame_eod(JOUR_UP), "C2_EOD")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != 1:
        e.append("EOD LONG : attendu 1 signal side +1 (obtenu %d)" % n)
    # ... et la ligne porte sortie + rendement_r + les DEUX verdicts
    # (side_pur/rend_pts — arbitrage Fable A, LECTURE_JOUR_61 regle 13)
    if sig and (sig[0].get("sortie") != "close_1545"
                or not isinstance(sig[0].get("rendement_r"), float)
                or sig[0].get("side_pur") != 1.0
                or sig[0].get("rend_pts") != 8.0
                or sig[0]["cible_prix"] is not None):
        e.append("EOD LONG : sortie=close_1545 + rendement_r + side_pur=1 +"
                 " rend_pts=8 + cible None attendus (%s)" % sig[0])
    # 2. SHORT miroir
    n, m, a, li = _run(_frame_eod(JOUR_DN), "C2_EOD")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != -1:
        e.append("EOD SHORT : attendu 1 signal side -1 (obtenu %d)" % n)
    # 3. jour plat -> 0 signal, 1 muet AVEC rendement_r ET side_pur/rend_pts
    #    (le verdict EOD-pur se lit TOUS les jours, meme sous r_min)
    n, m, a, li = _run(_frame_eod(JOUR_PLAT), "C2_EOD")
    muet = [l for l in li if l.get("motif") == "lieu_sans_reaction"]
    if (n != 0 or len(muet) != 1 or "rendement_r" not in muet[0]
            or "side_pur" not in muet[0] or "rend_pts" not in muet[0]):
        e.append("EOD plat : attendu 0 signal + 1 muet portant rendement_r "
                 "et side_pur/rend_pts (%d/%d)" % (n, m))
    # 4. demi-seance : pas de barre 15h15 -> jour muet motive
    n, m, a, li = _run(_frame_eod(JOUR_UP[:2]), "C2_EOD")
    if n != 0 or not any("barre_eod_absente" in str(l.get("motif")) for l in li):
        e.append("EOD demi-seance : attendu jour_muet:barre_eod_absente (%d/%d)"
                 % (n, m))
    # 5. ANTI-FUITE : la barre APRES 15h30 change du tout au tout -> journal
    #    de signal IDENTIQUE (rien apres la cloture EOD n'est lu)
    apres = JOUR_UP[:3] + [(19, 45, 108.0, 200.0, 50.0, 60.0)]
    _n, _m, _a, li2 = _run(_frame_eod(apres), "C2_EOD")
    s1 = [l for l in _run(_frame_eod(JOUR_UP), "C2_EOD")[3] if "snapshot_id" in l]
    s2 = [l for l in li2 if "snapshot_id" in l]
    if s1 != s2:
        e.append("EOD anti-fuite : modifier la barre 15h45 a change le signal")
    # 6. colonne absente (high) -> 0 signal, jour muet, absence RENDUE
    df = _frame_eod(JOUR_UP).drop(columns=["high"])
    n, m, a, li = _run(df, "C2_EOD")
    if (n != 0 or "high" not in a
            or not any("colonne_absente" in str(l.get("motif")) for l in li)):
        e.append("EOD colonne absente : attendu 0 + high RENDUE + jour_muet "
                 "(%d, %s)" % (n, a))
    # 7. DST : en novembre (EST) la barre EOD est 20:15 UTC -> signal quand
    #    meme. Une constante EDT en dur raterait la fin de campagne.
    novembre = [(hh + 1, mm, o, hi, lo, c) for (hh, mm, o, hi, lo, c) in JOUR_UP]
    n, m, a, li = _run(_frame_eod(novembre, date="2026-11-05"), "C2_EOD")
    if n != 1:
        e.append("EOD DST/EST : attendu 1 signal a 20:15 UTC (obtenu %d)" % n)
    # 8. ... et ce meme jour EST, 19:15 UTC (= 14:15 ET) n'est PAS la barre EOD
    n, m, a, li = _run(_frame_eod(JOUR_UP, date="2026-11-05"), "C2_EOD")
    if n != 0:
        e.append("EOD DST/EST : 19:15 UTC ne doit PAS signaler en novembre"
                 " (obtenu %d)" % n)


# les frames et cas DIV/POOR vivent dans cas_c2_niveaux.py


def main():
    e = []
    for nom in OC2.ACTIFS:
        if nom not in OC2.LES_C2:
            e.append("ACTIF %s hors du registre LES_C2" % nom)
        if nom not in OC2.SETUPS:
            e.append("ACTIF %s sans fonction — regle 15" % nom)
    cas_80pct(e)
    cas_eod(e)
    cas_div(e, _run)
    cas_poor(e, _run)
    print("  ombre C2 — huit cas par setup actif (%d actifs) : miroir, lieu"
          " seul,\n       jour muet motive, colonne absente rendue, anti-fuite,"
          " DST" % len(OC2.ACTIFS))
    if e:
        print("  %d ECHEC(S) :" % len(e))
        for x in e:
            print("     %s" % x)
        return 1
    print("  OK : un setup actif a sa preuve — regle 15 completee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
