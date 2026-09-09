"""Les trois barrières de chaque signal du jour — le script d'après-21:01.

    python -X utf8 V3/layers/L5_risque/barrieres_du_jour.py [YYYYMMDD]

SÉPARÉ du rejeu (`campagne.py` ne bouge pas) : il RECALCULE les signaux du
jour avec les fonctions mêmes du rejeu (déterministe — l'entonnoir ne porte
pas la famille, la re-dérivation la donne), puis écrit une ligne par signal
et par barrière dans `LOGS/barrieres/barrieres_<jour>.jsonl`. Le jour se
rejoue entier (truncate), le fichier existe même sans signal. RÈGLE : aucun
`null` sans motif à côté.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3 import lecture                                        # noqa: E402
from V3.campagne import (COLS_RECALC, chauffe_1min,           # noqa: E402
                         dernier_jour, signaux_l3)
from V3.layers.L5_risque import barrieres as B                # noqa: E402


def courir(jour):
    chemin = "LOGS/barrieres/barrieres_%s.jsonl" % jour
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    # vide = jour couru muet, absent = pas couru. Ecrit en .tmp puis replace
    # (moitie restante de R8) : un kill dur ne laisse plus d'ampute.
    # R8 propage (audit 09/09) : crash entre ES et NQ = fichier vide/partiel
    # lu « couru muet ». Efface + re-eleve : absent = incident lisible.
    try:
        return _courir(jour, chemin)
    except BaseException:
        for c in (chemin, chemin + ".tmp"):
            if os.path.exists(c):
                os.remove(c)
        print("  ECHEC en cours de route — %s EFFACE : jour NON couru." % chemin)
        raise


def _courir(jour, chemin):
    s = B.charger_seuils()
    n = 0
    incidents = []
    with open(chemin + ".tmp", "w", encoding="utf-8") as fh:
        for sym in ("ES", "NQ"):
            df, brut = charger_jour(sym, jour, 15, avec_1min=True)
            if df.empty or len(df) < 6:
                print("  %s : pas de barres cash exploitables" % sym)
                continue
            brut = pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                             ignore_index=True)
            df = injecter_recalculs(brut, df, minutes=15)
            manquantes = lecture.verifier_colonnes(df, ("L0", "L5"))
            if manquantes:
                print("  %s : COLONNES MANQUANTES %s — jour NON couru,"
                      " incident" % (sym, manquantes))
                incidents.append(sym)     # R7 : et le code retour le DIT
                continue
            sig, _c = signaux_l3(df)
            n_sym = 0
            for i, side, famille in sig:
                atr = float(pd.to_numeric(df["atr_barre"],
                                          errors="coerce").iloc[i])
                # un signal ne disparait JAMAIS sans trace (review R5)
                probleme = ("fenetre_absente" if i + 1 >= len(df) else
                            "atr_invalide" if (pd.isna(atr) or atr <= 0)
                            else None)
                if probleme:
                    for b_nom in ("B-ATR", "B-NIV", "B-NAT"):
                        fh.write(json.dumps({
                            "snapshot_id": "%s:%d:%s" % (
                                sym, i, "L" if side > 0 else "S"),
                            "ts": int(df["ts"].iloc[i]), "sym": sym,
                            "hypothese": famille, "side": side,
                            "barriere": b_nom, "sl_prix": None,
                            "tp_prix": None, "issue": None, "pnl_atr": None,
                            "motif_ligne": probleme,
                        }, ensure_ascii=False) + "\n")
                        n += 1
                        n_sym += 1
                    continue
                entree = float(df["open"].iloc[i + 1])
                trois = (B.b_atr(entree, atr, side, s["B-ATR"]),
                         B.b_niv(df, i, side, sym, s["B-NIV"], entree, atr),
                         B.b_nat(df, i, side, sym, s["B-NAT"], entree, atr,
                                 famille))
                for r in trois:
                    res = B.issue(df, i, side, r["sl_prix"], r["tp_prix"], sym)
                    ligne = {
                        "snapshot_id": "%s:%d:%s" % (sym, i,
                                                     "L" if side > 0 else "S"),
                        "ts": int(df["ts"].iloc[i]), "sym": sym,
                        "hypothese": famille, "side": side,
                        "entree": entree, "atr_pts": round(atr, 2),
                        **r,
                        "sl_atr": round((r["sl_prix"] - entree) / atr * -side, 3),
                        "tp_atr": round((r["tp_prix"] - entree) / atr * side, 3),
                        "issue": res[0] if res else None,
                        "pnl_atr": round(res[1], 4) if res else None,
                        "i_connu": res[2] if res else None,
                        "motif_issue": None if res else "fenetre_absente",
                    }
                    fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                    n += 1
                    n_sym += 1
            print("  %s : %d lignes de barrieres" % (sym, n_sym))
    os.replace(chemin + ".tmp", chemin)
    print("journal : %s" % chemin)
    # R7 (revue 09/09) : un instrument declare « jour NON couru, incident »
    # rendait quand meme 0, et `rythme_soir._etape` y voyait un succes. Le
    # code retour doit porter l'aveuglement, jamais le nombre de lignes.
    if incidents:
        print("  INCIDENT sur %s — code retour 1." % ", ".join(incidents))
    return 1 if incidents else 0


def main():
    os.chdir(RACINE)
    jour = sys.argv[1] if len(sys.argv) > 1 else dernier_jour()
    if not jour:
        print("aucun fichier de donnees")
        return 1
    print("BARRIERES — journee %s (B-ATR / B-NIV / B-NAT par signal)" % jour)
    return courir(jour)


if __name__ == "__main__":
    sys.exit(main())
