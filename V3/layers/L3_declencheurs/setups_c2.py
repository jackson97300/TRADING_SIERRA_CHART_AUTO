"""Les FONCTIONS de setup du brief OMBRE C2 — séparées du coureur.

`ombre_c2.py` porte le registre (LES_C2, ACTIFS), les seuils et le journal ;
ce module porte les fonctions de TEMPS/PROFIL (80PCT, EOD) et le registre
SETUPS ; les setups à NIVEAUX (DIV_DELTA, POOR) et les helpers partagés
vivent dans `setups_c2_niveaux.py` (scindé 08/09, garde des 300 lignes —
sens unique : ce module importe là-bas, jamais l'inverse).

Contrat d'une fonction de setup : `f(df, sym, seuils)` rend
    {"short": (cond, -1), "long": (cond, +1), "_lieu": cond_lieu, "_cibles":
     {side: prix_ou_Serie}, "_extra": {}?, "_sortie": str?, "_muet_jour": ?}
Conditions par FRANCHISSEMENT, `None`/NaN ne signale jamais, anti-fuite :
rien après la barre t n'entre dans la condition de t.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import recalc                                   # noqa: E402
from V3.layers.L3_declencheurs.setups_c2_niveaux import (          # noqa: E402,F401
    TICK, _col, _figes, c2_div_delta, c2_poor)   # re-export : helpers partages

MINUTE_EOD = 15 * 60 + 15   # ouverture 15h15 ET -> cloture 15h30 (DST : recalc)


def c2_80pct(df, sym, s):
    """Règle des 80 % (Dalton) — brief §1, définitions F23.

    Régime B5 : l'ouverture cash HORS de la VA veille (recalculée — jamais
    le flag C++ `rule_80pct`). Lieu ET acceptation sur le MÊME prédicat :
    la VA reconstruite figée (S1 : le flag C++ `inside_prev_va` divergeait
    d'un tick et fragmentait l'épisode ; unifié provenance A). Réaction :
    DEUX clôtures 15 min consécutives dans la VA. Side : vers le bord
    opposé (ouverture au-dessus → SHORT vers VAL ; miroir).

    Journal (audit Fable §3 — journalisé D'ABORD, filtres au cycle 2) :
    `fenetre_reentree_barres` = barres depuis le début de la ré-entrée
    courante (Dalton est une règle d'OUVERTURE — une acceptation à 14h30
    n'est plus son cas) ; `cible_atteinte_short/long` = la barre du signal
    a DÉJÀ touché le bord opposé (barre longue qui traverse la VA : un
    « TP » instantané serait un artefact, jamais un trade)."""
    close = pd.to_numeric(df["close"], errors="coerce")
    vah = close + pd.to_numeric(df.get("dist_prev_vah"), errors="coerce") * TICK
    val = close + pd.to_numeric(df.get("dist_prev_val"), errors="coerce") * TICK
    # niveaux FIGÉS : la reconstruction est constante sur la journée, on
    # prend la première valeur finie — règle F23.
    vah_j = vah.dropna().iloc[0] if vah.notna().any() else None
    val_j = val.dropna().iloc[0] if val.notna().any() else None
    ouverture = pd.to_numeric(df["open"], errors="coerce").iloc[0]
    if vah_j is None or val_j is None or not pd.notna(ouverture):
        vide = pd.Series(False, index=df.index)
        return {"short": (vide, -1), "long": (vide, +1),
                "_lieu": vide, "_cibles": {}}
    dedans = (close >= val_j) & (close <= vah_j)
    acceptation = dedans & dedans.shift(1, fill_value=False)
    pos = pd.Series(np.arange(len(df), dtype=float), index=df.index)
    debut = pos.where(dedans & ~dedans.shift(1, fill_value=False))
    extra = {"fenetre_reentree_barres": (pos - debut.ffill()).where(dedans)}
    bas, haut = _col(df, "low"), _col(df, "high")
    if bas is not None and haut is not None:
        extra["cible_atteinte_short"] = bas <= val_j
        extra["cible_atteinte_long"] = haut >= vah_j
    return {
        "short": (acceptation & (ouverture > vah_j), -1),
        "long": (acceptation & (ouverture < val_j), +1),
        "_lieu": dedans & ((ouverture > vah_j) | (ouverture < val_j)),
        "_cibles": {-1: val_j, +1: vah_j},   # le bord opposé (B-NAT de L5)
        "_extra": extra,
    }


def c2_eod(df, sym, s):
    """Momentum de fin de journée — brief §2 (Baltussen et al., JFE 2021).

    Lieu : la barre 15h15-15h30 ET clôturée — DST géré DE BOUT EN BOUT
    depuis le 08/09 : `est_cash` amont est passé sur `minutes_et` (audit
    Fable §2, parité 0/271 940 barres — la dette qui aurait coupé la barre
    dès le 2/11 est FERMÉE ; résiduel côté recherche : A_FAIRE pt 19).
    Réaction : |rendement_r| ≥ r_min, où rendement_r = (close(15h30) −
    open(9h30)) / range cash du même instant — provenance A pure ; l'écart
    au « ATR-jour » du brief est documenté dans `mesure_c2.py` et
    `seuils_c2.yaml`. Side : le signe. Pas de cible prix : sortie
    `close_1545` (la clôture de la barre 15h45-16h00 ET, dernier print
    cash — audit §2, EXEC ne devine pas). Demi-séance : pas de barre
    15h15 → ligne `jour_muet`, jamais un signal.

    DEUX VERDICTS au jour 61 (arbitrage Fable A, LECTURE_JOUR_61 règle
    13) : `side_pur` + `rend_pts` sont journalisés TOUS les jours (signal
    OU muet) — EOD-pur est le papier (le signe, sans seuil, N ≈ 60),
    EOD-r_min est le filtre (N ≈ 45). Jamais une troisième variante.
    `side_pur = 0` (close == open au tick) = pas de direction : jour
    compté NO-TRADE dans le N d'EOD-pur, jamais un side inventé.
    Anti-fuite : `cummax`/`cummin` n'utilisent que les barres ≤ t."""
    r_min = ((s.get("C2_EOD") or {}).get("r_min") or {}).get(sym)
    if r_min is None:
        raise ValueError("C2_EOD actif sans r_min %s — poser la distribution"
                         " dans seuils_c2.yaml (fail-loud)" % sym)
    vide = pd.Series(False, index=df.index)
    ouv, clo = _col(df, "open"), _col(df, "close")
    haut, bas = _col(df, "high"), _col(df, "low")
    if any(x is None for x in (ouv, clo, haut, bas)):
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "colonne_absente"}
    mn = recalc.minutes_et(pd.to_datetime(df["ts"], unit="ms", utc=True))
    est_eod = pd.Series((mn == MINUTE_EOD).to_numpy(), index=df.index)
    rng = (haut.cummax() - bas.cummin())
    rend_pts = clo - float(ouv.iloc[0])
    rend = rend_pts / rng.where(rng > 0)
    if not est_eod.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "barre_eod_absente"}
    lieu = est_eod & rend.notna()
    if not lieu.any():
        return {"short": (vide, -1), "long": (vide, +1), "_lieu": vide,
                "_cibles": {}, "_muet_jour": "rendement_incalculable"}
    return {"short": (lieu & (rend <= -r_min), -1),
            "long": (lieu & (rend >= r_min), +1),
            "_lieu": lieu, "_cibles": {},
            "_extra": {"rendement_r": rend, "range_pts": rng,
                       "rend_pts": rend_pts, "side_pur": np.sign(rend_pts)},
            "_sortie": str((s.get("C2_EOD") or {}).get("sortie",
                                                       "close_1545"))}


SETUPS = {"C2_80PCT": c2_80pct, "C2_EOD": c2_eod,
          "C2_DIV_DELTA": c2_div_delta, "C2_POOR": c2_poor}
