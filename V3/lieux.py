"""LE LIEU dans la ligne PASSE — leçon V1 n° 4 (audit Fable 09/09), passe du 10/09.

Une ligne PASSE disait « H3-VPOC, long, 11h45 » ; elle ne disait pas OÙ. V1
journalisait trigger_level / type / distance par trade — la seule information
qu'on ne peut pas reconstruire au jour 61 sans rejouer. Ici `pour_signal()`
rend la liste des niveaux qui ont fait le LIEU du signal : nom, prix
reconstruit, distance en ticks (la colonne, telle quelle) ; la BANDE du lieu
en ticks (bas, haut — les fonctions gelées ne sont pas toutes symétriques),
le seuil de proximité de la famille, et le `close` de la barre (le lieu est
autoportant : `prix = close + dist × tick`, sans rouvrir la donnée).

COLONNE DE JOURNAL, JAMAIS UNE DÉCISION : la chaîne l'écrit dans `extra` de
chaque ligne du signal (PASSE, BLOQUE, TROU — comme `atr_source`), elle ne lit
rien dedans. Les niveaux sont ceux des fonctions gelées (`hypotheses.py`), un
par hypothèse et par côté ; H8p en lit dix, on rend ceux à ≤ P20.

CONVENTION DE SIGNE, MESURÉE le 10/09 (04/09 et 14/07, ES et NQ, 4 × 390
barres 1 min contre les colonnes `_lvl` du brut) : `niveau = close + dist ×
tick` pour TOUTES les `dist_*` — figées (prev_*, pdh/pdl, ovn_*, mq_*, ib_* :
std 0,000 du niveau reconstruit), bandes recalculées, ET `dist_cur_val` /
`dist_cur_vah` (`close + d × tick == cur_val_lvl` à 100 % ; `inside_cur_va = 1`
→ d < 0). Le code gelé de `h3` reconstruit la VAL avec le signe INVERSE
(`close − dl × tick` = 2·close − VAL) : il fait foi pour la DÉCISION (quand H3
tire, tag mission-phase2-v1), pas pour la DESCRIPTION du niveau — le journal
porte la vraie VAL ; ce que le long de H3 teste vraiment est une lecture pour
NEXT_CYCLE (review du 10/09, R1), jamais une retouche en campagne.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.research import hypotheses as H                       # noqa: E402
from V3.lecture_colonnes import val                             # noqa: E402

# (famille, côté) -> les niveaux du LIEU : (nom, colonne dist)
TABLE = {
    ("H3-VPOC", -1): (("cur_vah", "dist_cur_vah"),),
    ("H3-VPOC", +1): (("cur_val", "dist_cur_val"),),
    ("H2p", -1): (("vwap_rth_sd2u", "dist_vwap_rth_sd2u_r"),),
    ("H2p", +1): (("vwap_rth_sd2d", "dist_vwap_rth_sd2d_r"),),
    ("H6p", +1): (("ib_high", "dist_ib_high"),),
    ("H6p", -1): (("ib_low", "dist_ib_low"),),
}
NIVEAUX_H8 = tuple((c[len("dist_"):], c) for c in H.NIVEAUX_H8)   # a <= P20
# La BANDE du lieu, en planchers (bas, haut), lue dans les fonctions gelées :
# h3 |d| <= P10 ; h2' short [-P15 ; +P10], long [-P10 ; +P15] ; h6' [-P15 ; +P05]
# (avec d < 0 en reaction — la borne active est P15, pas P05) ; h8' |d| <= P20.
BANDE = {("H3-VPOC", -1): ("P10", "P10"), ("H3-VPOC", +1): ("P10", "P10"),
         ("H2p", -1): ("P15", "P10"), ("H2p", +1): ("P10", "P15"),
         ("H6p", +1): ("P15", "P05"), ("H6p", -1): ("P15", "P05"),
         ("H8p", +1): ("P20", "P20"), ("H8p", -1): ("P20", "P20")}
SEUIL = {"H3-VPOC": "P10", "H2p": "P10", "H6p": "P05", "H8p": "P20"}   # la proximite


def _p(a, nom, tick):
    return float(H.seuil_ticks(pd.Series([a]), nom, tick).iloc[0])


def _sans(motif, **plus):
    return dict({"lieux": None, "lieux_motif": motif}, **plus)


def pour_signal(df, i, famille, side, tick=H.TICK):
    """{lieux: [{nom, prix, dist_ticks}, ...], seuil_ticks, bande_ticks, close}
    pour la barre `i` d'un signal des quatre — ou {lieux: None, lieux_motif}
    qui dit pourquoi (famille hors des quatre, df sans recalculs, atr_ref
    absent, close absent, niveau absent). Jamais un `None` sans motif."""
    if famille not in H.LES_QUATRE:
        return _sans("famille_hors_quatre")
    if "atr_ref" not in df.columns:
        return _sans("sans_recalculs")
    a = val(df, "atr_ref", i)
    if a is None or a <= 0:
        return _sans("atr_ref_absent")
    cote = int(side)
    bas, haut = BANDE[(famille, cote)]                      # fail-loud : cote ±1
    p = round(_p(a, SEUIL[famille], tick), 2)
    bande = [round(-_p(a, bas, tick), 2), round(_p(a, haut, tick), 2)]
    close = val(df, "close", i)
    if close is None:
        return _sans("close_absent", seuil_ticks=p, bande_ticks=bande)
    niveaux = NIVEAUX_H8 if famille == "H8p" else TABLE.get((famille, cote), ())
    out = []
    for nom, col in niveaux:
        d = val(df, col, i)
        if d is None or (famille == "H8p" and abs(d) > p):
            continue
        out.append({"nom": nom, "prix": round(close + d * tick, 2),
                    "dist_ticks": round(d, 2)})
    if not out:
        return _sans("niveau_absent", seuil_ticks=p, bande_ticks=bande)
    return {"lieux": out, "seuil_ticks": p, "bande_ticks": bande, "close": close}
