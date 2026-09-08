"""Les huit cas des setups C2 à NIVEAUX (DIV_DELTA, POOR) — module de cas.

Appelé par `test_ombre_c2.py` (le seul point d'entrée : `python -X utf8
V3/layers/L3_declencheurs/test_ombre_c2.py`), qui lui passe son `_run`.
Scindé le 08/09 à l'activation du 4e setup — garde des 300 lignes.
"""

from __future__ import annotations

import pandas as pd


def _frame_div(barres):
    """Journée DIV : (o, h, l, c, cvd). VAH = 105,5 / VAL = 94,5
    reconstruites figées ; ouverture DANS la VA (80PCT hors régime) ; ts
    epoch 1970 (EOD rend jour muet, filtré) ; atr_barre = 10 pts → P10 =
    4 ticks = 1 pt."""
    lignes = []
    for i, (o, h, l, c, cvd) in enumerate(barres):
        lignes.append({"ts": 1_000_000 + i * 900_000, "jour": "2026-09-03",
                       "open": o, "high": h, "low": l, "close": c,
                       "cvd_sess_r": cvd, "atr_barre": 10.0,
                       "vwap_rth_r": 100.0 + i,
                       "dist_prev_vah": (105.5 - c) / 0.25,
                       "dist_prev_val": (94.5 - c) / 0.25})
    return pd.DataFrame(lignes)


DIV_SHORT = [(100.0, 100.0, 99.0, 99.5, 1000.0),
             (99.5, 105.2, 99.0, 104.8, 500.0)]
DIV_LONG = [(100.0, 101.0, 100.0, 100.5, -1000.0),
            (100.5, 101.0, 94.8, 95.2, -500.0)]


def cas_div(e, run):
    # 1. SHORT : nouveau plus haut a 1,2 tick de la VAH, cvd 500 < 1000 au
    #    precedent plus haut, cloture sous le niveau -> 1 signal
    n, m, a, li = run(_frame_div(DIV_SHORT), "C2_DIV_DELTA")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != -1:
        e.append("DIV SHORT : attendu 1 signal side -1 (obtenu %d)" % n)
    # ... cible = vwap_rth_r DE LA BARRE du signal (101.0 a b1)
    if sig and sig[0]["cible_prix"] != 101.0:
        e.append("DIV cible : vwap de la barre attendu 101.0 (%s)"
                 % sig[0]["cible_prix"])
    # 2. SHORT lieu seul : cvd MONTE (pas de divergence) -> 0 signal, muet
    sans_div = [DIV_SHORT[0], DIV_SHORT[1][:4] + (1500.0,)]
    n, m, a, li = run(_frame_div(sans_div), "C2_DIV_DELTA")
    if n != 0 or m != 1:
        e.append("DIV SHORT lieu seul : attendu 0 signal + 1 muet (%d/%d)"
                 % (n, m))
    # 3-4. LONG miroir : signal, puis lieu seul
    n, m, a, li = run(_frame_div(DIV_LONG), "C2_DIV_DELTA")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != 1:
        e.append("DIV LONG : attendu 1 signal side +1 (obtenu %d)" % n)
    sans_div = [DIV_LONG[0], DIV_LONG[1][:4] + (-1500.0,)]
    n, m, a, li = run(_frame_div(sans_div), "C2_DIV_DELTA")
    if n != 0 or m != 1:
        e.append("DIV LONG lieu seul : attendu 0 signal + 1 muet (%d/%d)"
                 % (n, m))
    # 5. PREMIER extreme du jour pres du niveau : pas de precedent -> muet
    n, m, a, li = run(_frame_div([(105.0, 105.3, 104.9, 104.9, 1000.0)]),
                      "C2_DIV_DELTA")
    if n != 0 or m != 1:
        e.append("DIV premier extreme : attendu 0 signal + 1 muet (%d/%d)"
                 % (n, m))
    # 6. LOIN des niveaux -> rien du tout
    n, m, a, li = run(_frame_div([(100.0, 100.0, 99.0, 99.5, 1000.0),
                                  (99.5, 101.0, 99.0, 100.5, 500.0)]),
                      "C2_DIV_DELTA")
    if n != 0 or m != 0:
        e.append("DIV loin des niveaux : attendu 0/0 (%d/%d)" % (n, m))
    # 7. COLONNE ABSENTE (cvd_sess_r) -> jour muet motive + absence RENDUE
    df = _frame_div(DIV_SHORT).drop(columns=["cvd_sess_r"])
    n, m, a, li = run(df, "C2_DIV_DELTA")
    if (n != 0 or "cvd_sess_r" not in a
            or not any("colonne_absente" in str(l.get("motif")) for l in li)):
        e.append("DIV colonne absente : attendu jour_muet + cvd_sess_r RENDUE"
                 " (%d, %s)" % (n, a))
    # 8. ANTI-FUITE : une barre APRES le signal (plus haut loin des niveaux)
    #    ne change pas la ligne du signal — et la ligne PORTE le niveau
    #    choisi + la distance (l'arbitrage du lieu se rejugera sans re-run)
    s1 = [l for l in run(_frame_div(DIV_SHORT), "C2_DIV_DELTA")[3]
          if "snapshot_id" in l]
    apres = DIV_SHORT + [(104.8, 120.0, 104.0, 119.0, 2000.0)]
    s2 = [l for l in run(_frame_div(apres), "C2_DIV_DELTA")[3]
          if "snapshot_id" in l]
    if s1 != s2:
        e.append("DIV anti-fuite : une barre posterieure a change le signal")
    if s1 and (s1[0].get("niveau_prix") != 105.5
               or not isinstance(s1[0].get("dist_niveau_ticks"), float)):
        e.append("DIV extras : niveau_prix=105.5 + dist_niveau_ticks attendus"
                 " (%s)" % s1[0])
    # 9. TROU DE CHAUFFE : atr_barre NaN -> p10 NaN -> jamais un lieu, meme
    #    colle au niveau (documente ; l'arbitrage ATR-veille est ouvert)
    df = _frame_div(DIV_SHORT)
    df["atr_barre"] = float("nan")
    n, m, a, li = run(df, "C2_DIV_DELTA")
    if n != 0 or m != 0:
        e.append("DIV atr NaN : attendu 0/0 — un trou, jamais un signal "
                 "(%d/%d)" % (n, m))
    # 10. JOUR SANS AUCUN NIVEAU : motif dedie, jamais un zero silencieux
    df = _frame_div(DIV_SHORT).drop(columns=["dist_prev_vah", "dist_prev_val"])
    n, m, a, li = run(df, "C2_DIV_DELTA")
    if n != 0 or not any("niveaux_absents" in str(l.get("motif")) for l in li):
        e.append("DIV sans niveaux : attendu jour_muet:niveaux_absents "
                 "(%d/%d)" % (n, m))


def _frame_poor(barres):
    """Journée POOR : (h, l, c, poor_h, poor_l, rvol). VAH = 110 / VAL = 90
    figées (cibles) ; ouverture 99 DANS la VA (80PCT silencieux) ; ts epoch
    1970 (EOD muet) ; pas de cvd_sess_r (DIV muet) ; atr_barre = 10 →
    P10 = 4 ticks = 1 pt."""
    lignes = []
    for i, (h, l, c, ph, pl, rv) in enumerate(barres):
        lignes.append({"ts": 1_000_000 + i * 900_000, "jour": "2026-09-03",
                       "open": 99.0 if i == 0 else c,
                       "high": h, "low": l, "close": c,
                       "ctx_poor_high": ph, "ctx_poor_low": pl,
                       "rvol_r": rv, "atr_barre": 10.0,
                       "dist_prev_vah": (110.0 - c) / 0.25,
                       "dist_prev_val": (90.0 - c) / 0.25})
    return pd.DataFrame(lignes)


#              h      l     c      ph   pl   rvol
POOR_LONG = [(100.0, 98.0, 99.0, 1.0, 0.0, 1.0),     # formation, px=100
             (99.5, 98.5, 99.0, 1.0, 0.0, 1.0),
             (99.5, 98.5, 99.0, 1.0, 0.0, 1.0),
             (99.8, 98.8, 99.5, 1.0, 0.0, 1.0),
             (100.6, 99.0, 100.4, 1.0, 0.0, 2.0)]    # repare : close > 100
POOR_SHORT = [(102.0, 100.0, 101.0, 0.0, 1.0, 1.0),  # px_b = 100
              (101.5, 100.5, 101.0, 0.0, 1.0, 1.0),
              (101.5, 100.5, 101.0, 0.0, 1.0, 1.0),
              (101.2, 100.2, 100.5, 0.0, 1.0, 1.0),
              (101.0, 99.4, 99.6, 0.0, 1.0, 2.0)]    # repare : close < 100


def cas_poor(e, run):
    # C2_POOR est PRE-CABLE, pas actif (v1 morte par construction, rapport
    # lieu_poor) : les huit cas restent VERTS AVANT l'activation — le jour
    # ou le redesign s'active, sa preuve existe deja (regle 15). Activation
    # LE TEMPS DU TEST seulement.
    from V3.layers.L3_declencheurs import ombre_c2 as OC2
    # RESTAURER l'etat anterieur, jamais pop aveugle (review R1) : le jour
    # ou le redesign posera une VRAIE date d'ombre, ce test ne doit pas
    # l'ecraser puis la supprimer.
    ancien = OC2.ACTIFS.get("C2_POOR")
    OC2.ACTIFS["C2_POOR"] = ancien or "test_seulement"
    try:
        _cas_poor(e, run)
    finally:
        if ancien is None:
            OC2.ACTIFS.pop("C2_POOR", None)
        else:
            OC2.ACTIFS["C2_POOR"] = ancien


def _cas_poor(e, run):
    # 1. LONG : poor forme depuis 4 barres, retour + cloture au-dessus avec
    #    rvol 2.0 -> 1 signal ; extras poor_prix + cible = VAH figee
    n, m, a, li = run(_frame_poor(POOR_LONG), "C2_POOR")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != 1:
        e.append("POOR LONG : attendu 1 signal side +1 (obtenu %d)" % n)
    if sig and (sig[0].get("poor_prix_h") != 100.0
                or sig[0].get("cible_prix") != 110.0):
        e.append("POOR LONG : poor_prix_h=100.0 + cible=110.0 attendus (%s)"
                 % sig[0])
    # 2. LONG lieu seul : rvol 0.5 sous le p50 -> 0 signal + muet
    faible = POOR_LONG[:4] + [POOR_LONG[4][:5] + (0.5,)]
    n, m, a, li = run(_frame_poor(faible), "C2_POOR")
    if n != 0 or m < 1:
        e.append("POOR LONG rvol faible : attendu 0 signal + muet (%d/%d)"
                 % (n, m))
    # 3. PAS ASSEZ FORME (repare a i-idx=2 < 3) -> rien du tout
    n, m, a, li = run(_frame_poor(POOR_LONG[:2] + [POOR_LONG[4]]), "C2_POOR")
    if n != 0 or m != 0:
        e.append("POOR formation <3 barres : attendu 0/0 (%d/%d)" % (n, m))
    # 4-5. SHORT miroir : signal, puis rvol faible -> muet
    n, m, a, li = run(_frame_poor(POOR_SHORT), "C2_POOR")
    sig = [l for l in li if "snapshot_id" in l]
    if n != 1 or sig[0]["side"] != -1 or (sig and sig[0].get("cible_prix") != 90.0):
        e.append("POOR SHORT : attendu 1 signal side -1 cible 90.0 (obtenu "
                 "%d, %s)" % (n, sig and sig[0].get("cible_prix")))
    faible = POOR_SHORT[:4] + [POOR_SHORT[4][:5] + (0.5,)]
    n, m, a, li = run(_frame_poor(faible), "C2_POOR")
    if n != 0 or m < 1:
        e.append("POOR SHORT rvol faible : attendu 0 signal + muet (%d/%d)"
                 % (n, m))
    # 6. COLONNE ABSENTE (ctx_poor_high) -> jour muet motive + RENDUE
    df = _frame_poor(POOR_LONG).drop(columns=["ctx_poor_high"])
    n, m, a, li = run(df, "C2_POOR")
    if (n != 0 or "ctx_poor_high" not in a
            or not any("colonne_absente" in str(l.get("motif")) for l in li)):
        e.append("POOR colonne absente : attendu jour_muet + RENDUE (%d, %s)"
                 % (n, a))
    # 7. RE-FORMATION : nouveau plus haut poor toujours actif -> le prix se
    #    RE-FIGE et l'age repart — la cloture au-dessus du VIEUX prix ne
    #    signale plus
    refor = [POOR_LONG[0], POOR_LONG[1],
             (101.0, 99.0, 99.5, 1.0, 0.0, 1.0),     # nouveau px=101, idx=2
             POOR_LONG[3],
             (100.6, 99.0, 100.4, 1.0, 0.0, 2.0)]    # > vieux 100, < 101
    n, m, a, li = run(_frame_poor(refor), "C2_POOR")
    if n != 0:
        e.append("POOR re-formation : le vieux prix ne doit plus signaler "
                 "(obtenu %d)" % n)
    # 8. ANTI-FUITE : une barre posterieure ne change pas le signal
    s1 = [l for l in run(_frame_poor(POOR_LONG), "C2_POOR")[3]
          if "snapshot_id" in l]
    apres = POOR_LONG + [(150.0, 90.0, 120.0, 0.0, 0.0, 9.0)]
    s2 = [l for l in run(_frame_poor(apres), "C2_POOR")[3]
          if "snapshot_id" in l]
    if s1 != s2:
        e.append("POOR anti-fuite : une barre posterieure a change le signal")
