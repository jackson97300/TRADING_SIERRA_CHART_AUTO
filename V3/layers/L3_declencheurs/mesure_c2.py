"""Mesure C2_EOD — la distribution qui pose `r_min` (brief OMBRE_C2 §2).

    python -X utf8 V3/layers/L3_declencheurs/mesure_c2.py

ATTENDU, ÉCRIT AVANT LA MESURE : |rendement_r| — le rendement du jour à la
clôture de la barre 15h15-15h30 ET, normalisé par le range cash du même
instant — a p25 ≈ 0,2-0,3 et p50 ≈ 0,4 par instrument. `r_min` = **p25, par
instrument** (pré-déclaré : garde ~3 jours sur 4, cohérent avec le N ≈ 60
du brief ; le quart le plus plat est du bruit, pas du momentum).

POURQUOI LE RANGE ET PAS L'« ATR-jour » DU BRIEF : le coureur de 21:01
travaille UNE journée à la fois — un ATR quotidien exige un historique
multi-jours, et la colonne C++ `atr` n'est pas reproduite (provenance B).
Le range cash jusqu'à 15h30 est OHLC pur (provenance A), borné, et
|close-open|/range est le finish du JOUR — la même grandeur que `finish_r`
à l'échelle au-dessus. Les points bruts sont journalisés avec chaque
signal : le jour 61 peut re-normaliser par ce qu'il veut. Écart au brief
FLAGGÉ dans DECISIONS.md, arbitrage Fable possible.

Cette mesure ne lit AUCUNE issue, aucun P&L, aucun devenir — elle pose un
seuil de réaction (brief §13 : « les distributions servent à poser les
seuils, jamais à lire un devenir »).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.features import recalc                              # noqa: E402
from V3.campagne import jours_disponibles                     # noqa: E402
from V3.layers.L3_declencheurs.ombre_c2 import MINUTE_EOD     # noqa: E402
# LA constante du setup, jamais recopiée : deux copies divergeraient.


def rendement_du_jour(df):
    """(rendement_r, rendement_pts, range_pts) a la cloture 15h30, ou None
    avec son motif : (None, motif). Ne regarde RIEN apres la barre EOD."""
    mn = recalc.minutes_et(pd.to_datetime(df["ts"], unit="ms", utc=True))
    idx = df.index[mn == MINUTE_EOD]
    if len(idx) == 0:
        return None, "barre_eod_absente"
    i = int(idx[0])
    ouv = float(pd.to_numeric(df["open"], errors="coerce").iloc[0])
    clo = float(pd.to_numeric(df["close"], errors="coerce").iloc[i])
    haut = pd.to_numeric(df["high"], errors="coerce").iloc[:i + 1].max()
    bas = pd.to_numeric(df["low"], errors="coerce").iloc[:i + 1].min()
    rng = float(haut - bas)
    if not np.isfinite(ouv) or not np.isfinite(clo) or not np.isfinite(rng):
        return None, "ohlc_invalide"
    if rng <= 0:
        return None, "range_nul"
    return ((clo - ouv) / rng, clo - ouv, rng), None


def main():
    os.chdir(RACINE)
    sortie = ["# Mesure C2_EOD — distribution de |rendement_r| (pose r_min)",
              "",
              "*Attendu écrit avant : p25 ≈ 0,2-0,3 ; p50 ≈ 0,4 ; r_min = p25",
              "par instrument. Normalisation par le range cash à 15h30 (OHLC,",
              "provenance A) — écart au « ATR-jour » du brief documenté dans",
              "la docstring de `mesure_c2.py` et flaggé dans DECISIONS.md.",
              "Aucun devenir lu.*", ""]
    for sym in ("ES", "NQ"):
        vals, motifs = [], {}
        for jour in jours_disponibles(sym):
            df = charger_jour(sym, jour, 15)
            if df.empty or len(df) < 6:
                motifs["jour_vide"] = motifs.get("jour_vide", 0) + 1
                continue
            r, motif = rendement_du_jour(df)
            if r is None:
                motifs[motif] = motifs.get(motif, 0) + 1
                continue
            vals.append(abs(r[0]))
        if not vals:
            sortie.append("## %s : AUCUNE journée mesurable (%s)" % (sym, motifs))
            continue
        v = np.array(vals)
        q = {p: float(np.percentile(v, p)) for p in (10, 25, 50, 75, 90)}
        sortie += [
            "## %s — %d journées mesurées (écartées : %s)"
            % (sym, len(v), motifs or "aucune"),
            "- |rendement_r| : p10 %.3f | **p25 %.3f** | p50 %.3f | p75 %.3f"
            " | p90 %.3f" % (q[10], q[25], q[50], q[75], q[90]),
            "- **r_min retenu (p25, pré-déclaré) : %.3f** — garde %d/%d jours"
            % (q[25], int((v >= q[25]).sum()), len(v)),
            "- attendu tenu ? p25 dans [0,2 ; 0,3] : %s ; p50 ≈ 0,4 : %s"
            % ("OUI" if 0.2 <= q[25] <= 0.3 else "NON (%.3f)" % q[25],
               "OUI" if 0.3 <= q[50] <= 0.5 else "NON (%.3f)" % q[50]),
            "",
        ]
    chemin = ("V3/layers/L3_declencheurs/rapports/mesure_c2_eod_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    open(chemin, "w", encoding="utf-8").write("\n".join(sortie))
    print("\n".join(sortie))
    print("rapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
