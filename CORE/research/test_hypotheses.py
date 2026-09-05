"""Vingt-quatre barres synthetiques : quatre par hypothese, aucune donnee reelle.

C'est le test des factices descendu au niveau de chaque hypothese. Les trois
factices du runner prouvent que l'instrument sait rejeter le bruit et reconnaitre
un edge ; ils ne disent rien de la correspondance entre le texte tague et le code.
Ces vingt-quatre cas la disent, et ils sont tous connus d'avance :

    1. lieu vrai  + reaction vraie   -> signal
    2. lieu vrai  + reaction fausse  -> rien
    3. lieu faux  + reaction vraie   -> rien
    4. le cas du PLANCHER sur ES : une distance hors de la fenetre en ATR mais
       dans le plancher de 2 ticks -> signal.

Le quatrieme est le seul qui teste la correction du 06/09. Sans plancher, ATR-5m
ES ~ 11,3 ticks donne 0,10 ATR = 1,13 tick : une distance de 1,5 tick serait
rejetee alors qu'elle est a un tick et demi du niveau. Sur NQ (ATR-5m ~ 80 ticks)
le plancher ne mord jamais — c'est voulu, et le test le verifie aussi.

Lancer : python -X utf8 CORE/research/test_hypotheses.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.research import hypotheses as H  # noqa: E402

ATR5_ES = 2.83      # points ; = 11,3 ticks. Mediane mesuree le 06/09.
ATR5_NQ = 20.05     # points ; = 80,2 ticks.

_ok = _ko = 0


def cas(nom, attendu, obtenu):
    global _ok, _ko
    bon = bool(attendu) == bool(obtenu)
    _ok, _ko = _ok + bon, _ko + (not bon)
    print("   %-58s %s" % (nom, "OK" if bon else "ECHEC (attendu %s)" % attendu))


def barres(n, atr5=ATR5_ES, jour="2026-07-01", **cols):
    """n barres d'une meme journee, colonnes par defaut neutres."""
    d = pd.DataFrame({
        "jour": [jour] * n, "atr5": [atr5] * n,
        "open": [7000.0] * n, "high": [7000.0] * n,
        "low": [7000.0] * n, "close": [7000.0] * n,
    })
    for k, v in cols.items():
        d[k] = v if isinstance(v, (list, tuple)) else [v] * n
    return d


def sig(res, cote):
    return bool(pd.Series(res[cote][0]).fillna(False).any())


# ---------------------------------------------------------------- H2
print("\nH2 — Fade des bandes VWAP-SD2 avec rejet")
base = dict(dist_vwap_rth_sd2u_r=1.0, ib_range_atr=0.5, delta_bar=-100.0,
            finish_delta_pct=0.2)
cas("lieu + reaction -> signal", True, sig(H.h2(barres(1, **base)), "short"))
cas("lieu, reaction fausse (finish 0,8) -> rien", False,
    sig(H.h2(barres(1, **{**base, "finish_delta_pct": 0.8})), "short"))
cas("lieu faux (20 t du niveau) -> rien", False,
    sig(H.h2(barres(1, **{**base, "dist_vwap_rth_sd2u_r": 20.0})), "short"))
cas("regime faux (ib_range_atr 0,9) -> rien", False,
    sig(H.h2(barres(1, **{**base, "ib_range_atr": 0.9})), "short"))

# ---------------------------------------------------------------- H3
print("\nH3 — Rejet a l'extreme de la VA courante")
#  dist_cur_vah = 1 tick  ->  VAH = close + 0,25 ; high au-dessus, cloture dessous
b3 = dict(dist_cur_vah=1.0, dist_cur_val=50.0, finish_delta_pct=0.2, high=7000.5)
cas("lieu + sortie + retour + finish -> signal", True, sig(H.h3(barres(1, **b3)), "short"))
cas("pas de sortie (high sous le VAH) -> rien", False,
    sig(H.h3(barres(1, **{**b3, "high": 7000.0})), "short"))
cas("lieu faux (30 t du VAH) -> rien", False,
    sig(H.h3(barres(1, **{**b3, "dist_cur_vah": 30.0, "high": 7007.6})), "short"))
#  LE CAS DU PLANCHER : 1,5 tick > 0,10 x 11,3 = 1,13, mais <= 2 ticks
cas("PLANCHER ES : 1,5 t hors fenetre ATR, dans le plancher -> signal", True,
    sig(H.h3(barres(1, atr5=ATR5_ES, **{**b3, "dist_cur_vah": 1.5, "high": 7000.6})), "short"))
cas("   le meme cas sans plancher serait rejete (0,10 ATR = 1,13 t)", True,
    1.5 > 0.10 * (ATR5_ES / H.TICK))
cas("NQ : le plancher ne mord pas (0,10 ATR = 8,0 t > 2)", True,
    float(H.seuil_ticks(pd.Series([ATR5_NQ]), "P10").iloc[0]) > 2.0)

# ---------------------------------------------------------------- H4
print("\nH4 — Regle des 80 % (Dalton)")
#  ouverture au-dessus de la VA, puis six barres dedans -> short
b4 = dict(prev_vah_lvl=7010.0, prev_val_lvl=6990.0, open_within_prev_va=0)
d4 = barres(7, **b4); d4.loc[:, "close"] = [7020.0] + [7000.0] * 6
cas("ouverture hors VA + 6 barres dedans -> signal", True, sig(H.h4(d4), "short"))
d5 = barres(7, **b4); d5.loc[:, "close"] = [7020.0] + [7000.0] * 4 + [7020.0, 7000.0]
cas("seulement 5 barres consecutives -> rien", False, sig(H.h4(d5), "short"))
d6 = barres(7, **{**b4, "open_within_prev_va": 1}); d6.loc[:, "close"] = [7000.0] * 7
cas("ouverture DANS la VA -> rien", False, sig(H.h4(d6), "short"))
d7 = barres(7, **b4); d7.loc[:, "close"] = [6980.0] + [7000.0] * 6
cas("ouverture sous la VA -> long, pas short", True,
    sig(H.h4(d7), "long") and not sig(H.h4(d7), "short"))

# ---------------------------------------------------------------- H6
print("\nH6 — Retest de l'IB apres cassure acceptee")
b6 = dict(ib_broken_up=1, ib_broken_dn=0, dist_ib_high=-1.0, dist_ib_low=50.0,
          ib_range_atr=0.3, finish_delta_pct=0.8)
cas("cassure + retest + finish -> signal", True, sig(H.h6(barres(1, **b6)), "long"))
cas("finish faible (0,3) -> rien", False,
    sig(H.h6(barres(1, **{**b6, "finish_delta_pct": 0.3})), "long"))
cas("cloture SOUS l'IB (dist > 0) -> rien", False,
    sig(H.h6(barres(1, **{**b6, "dist_ib_high": 1.0})), "long"))
cas("IB large (ib_range_atr 0,6) -> rien", False,
    sig(H.h6(barres(1, **{**b6, "ib_range_atr": 0.6})), "long"))

# ---------------------------------------------------------------- H7
print("\nH7 — Sweep de liquidite + reclaim N+1")
#  barre 0 : sweep sous l'ONL de 3 ticks (>= P10 = 2 t) ; barre 1 : reclaim
b7 = barres(2, sweep_low_this_bar=[1, 0], sweep_high_this_bar=0,
            dist_ovn_low=[0.0, 0.0], dist_pdl=-999.0, dist_ib_low=-999.0)
b7.loc[:, "low"] = [6999.25, 7000.0]        # 3 ticks sous le niveau (= close)
b7.loc[:, "close"] = [7000.0, 7000.5]       # t+1 cloture au-dessus du low de t
cas("sweep 3 t sous l'ONL + reclaim en t+1 -> signal", True, sig(H.h7(b7), "long"))
b8 = b7.copy(); b8.loc[1, "close"] = 6999.0
cas("pas de reclaim (t+1 sous le low de t) -> rien", False, sig(H.h7(b8), "long"))
b9 = b7.copy(); b9.loc[0, "low"] = 6999.875   # 0,5 tick : sous le plancher de 2 t
cas("sweep trop court (0,5 t < plancher 2 t) -> rien", False, sig(H.h7(b9), "long"))
b10 = b7.copy(); b10.loc[:, "jour"] = ["2026-07-01", "2026-07-02"]
cas("le reclaim ne traverse pas la nuit -> rien", False, sig(H.h7(b10), "long"))

# ---------------------------------------------------------------- H8
print("\nH8 — Absorption a un niveau")
b11 = dict(dist_cur_vah=2.0, rvol_r=2.5, delta_pct=-0.5, finish_delta_pct=0.8)
cas("niveau + rvol + delta + finish contraire -> signal", True,
    sig(H.h8(barres(1, **b11)), "long"))
cas("rvol insuffisant (1,5) -> rien", False,
    sig(H.h8(barres(1, **{**b11, "rvol_r": 1.5})), "long"))
cas("loin de tout niveau (60 t) -> rien", False,
    sig(H.h8(barres(1, **{**b11, "dist_cur_vah": 60.0})), "long"))
cas("finish dans le sens du delta (0,2) -> rien", False,
    sig(H.h8(barres(1, **{**b11, "finish_delta_pct": 0.2})), "long"))

# ---------------------------------------------------------------- unites
print("\nUnites — la conversion points -> ticks")
cas("P10 sur ES = max(1,13 ; 2) = 2,00 t", True,
    abs(float(H.seuil_ticks(pd.Series([ATR5_ES]), "P10").iloc[0]) - 2.0) < 1e-9)
cas("P10 sur NQ = max(8,02 ; 2) = 8,02 t", True,
    abs(float(H.seuil_ticks(pd.Series([ATR5_NQ]), "P10").iloc[0]) - 8.02) < 0.01)
cas("P15 sur ES = max(1,70 ; 3) = 3,00 t", True,
    abs(float(H.seuil_ticks(pd.Series([ATR5_ES]), "P15").iloc[0]) - 3.0) < 1e-9)

print("\n%s" % ("-" * 70))
print("  %d cas passes, %d echecs" % (_ok, _ko))
print("  RESULTAT : %s" % ("TOUS LES CAS PASSENT" if _ko == 0 else "ECHEC"))
sys.exit(1 if _ko else 0)
