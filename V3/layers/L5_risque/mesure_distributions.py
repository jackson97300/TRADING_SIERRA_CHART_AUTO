"""Distributions pour la barrière par niveaux (H-L5-NIVEAUX) — la mesure J1.

    python -X utf8 V3/layers/L5_risque/mesure_distributions.py

ATTENDU, écrit avant : la fenêtre SL [0,5 ; 1,5] ATR contient la médiane de
la distance au premier niveau contre ; `tp_min` ~0,5 ATR ; le buffer de
balayage est de l'ordre de quelques ticks (V1 utilisait 8 t NQ / 4 t ES —
mesuré sur du 1 min de mars, PAS recopiable, d'où cette mesure).

Trois mesures, par instrument, sur les 20 dernières journées disponibles :
  1. distance (ATR) de chaque barre cash 15 min au PREMIER niveau au-dessus
     et au-dessous — quantiles → `sl_fenetre_atr` et `tp_min_atr` ;
  2. BUFFER DE BALAYAGE : sur le 1 min, excursion maximale au-delà d'un
     niveau `prev_*` pendant un épisode qui REGAGNE (clôture revenue du bon
     côté le même jour) — p75 → `buffer_sweep_atr`. Chemin de repli du brief :
     les fiches F23 `regagné` sont en quarantaine pour les `cur_*`, les
     `prev_*` recalculés directement sont fiables ;
  3. STABILITÉ des `cur_*` : dérive médiane |Δ cur_vah| par heure UTC —
     l'heure à partir de laquelle le niveau du jour cesse de bouger
     matériellement → `stabilite_cur_barres`.

Sortie : `rapports/distributions_niveaux_<date>.md`. Aucun seuil choisi ici —
les nombres partent dans `seuils.yaml` avec leur origine.
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
from V3.campagne import jours_disponibles                     # noqa: E402

TICK = 0.25
N_JOURS = 20
NIVEAUX = ("dist_prev_vah", "dist_prev_val", "dist_prev_vpoc",
           "dist_cur_vah", "dist_cur_val", "dist_cur_vpoc",
           "dist_ib_high", "dist_ib_low", "dist_pdh", "dist_pdl",
           "dist_ovn_high", "dist_ovn_low",
           "dist_mq_call", "dist_mq_put", "dist_mq_hvl")
PREV_FIABLES = ("dist_prev_vah", "dist_prev_val", "dist_prev_vpoc",
                "dist_pdh", "dist_pdl")


def _dists_atr(df):
    """(dessus, dessous) : distance en ATR au premier niveau de chaque côté,
    par barre. Convention `dist = niveau − close` en TICKS : positif = niveau
    au-dessus."""
    atr = pd.to_numeric(df["atr_barre"], errors="coerce")
    dessus, dessous = [], []
    mat = {c: pd.to_numeric(df[c], errors="coerce") for c in NIVEAUX
           if c in df.columns}
    for i in range(len(df)):
        a = atr.iloc[i]
        if not np.isfinite(a) or a <= 0:
            dessus.append(np.nan)
            dessous.append(np.nan)
            continue
        hauts = [v.iloc[i] * TICK / a for v in mat.values()
                 if np.isfinite(v.iloc[i]) and v.iloc[i] > 0]
        bas = [-v.iloc[i] * TICK / a for v in mat.values()
               if np.isfinite(v.iloc[i]) and v.iloc[i] < 0]
        dessus.append(min(hauts) if hauts else np.nan)
        dessous.append(min(bas) if bas else np.nan)
    return pd.Series(dessus), pd.Series(dessous)


def _excursions_regagnees(b, col):
    """Excursions (ticks) au-delà du niveau `col` pendant les épisodes qui
    REGAGNENT le même jour. Le niveau est reconstruit par barre
    (`close + dist × tick`) — pour les `prev_*` il est constant sur la
    journée, c'est ce qui les rend fiables."""
    d = pd.to_numeric(b[col], errors="coerce")
    close = pd.to_numeric(b["close"], errors="coerce")
    high = pd.to_numeric(b["high"], errors="coerce")
    low = pd.to_numeric(b["low"], errors="coerce")
    niveau = (close + d * TICK).median()
    if not np.isfinite(niveau):
        return []
    au_dela = close > niveau if (close - niveau).median() < 0 else close < niveau
    # sens : on mesure les percées CONTRE le côté habituel du prix ce jour-là
    out, en_cours, pic, duree = [], False, 0.0, 0
    for i in range(len(b)):
        if not np.isfinite(close.iloc[i]):
            continue
        if au_dela.iloc[i]:
            en_cours = True
            duree += 1
            ext = max(high.iloc[i] - niveau, niveau - low.iloc[i])
            pic = max(pic, ext / TICK)
        elif en_cours:
            out.append((pic, duree))    # l'episode a regagne : le pic compte
            en_cours, pic, duree = False, 0.0, 0
    return out                          # un episode jamais regagne ne compte pas


def main():
    os.chdir(RACINE)
    lignes = ["# Distributions pour la barriere par niveaux — mesure J1",
              "", "*%d dernieres journees par instrument. Aucun seuil choisi"
              " ici.*" % N_JOURS, ""]
    for sym in ("ES", "NQ"):
        jours = jours_disponibles(sym)[-N_JOURS:]
        dessus_t, dessous_t, excursions, derive_h = [], [], [], {}
        for j in jours:
            df, brut = charger_jour(sym, j, 15, avec_1min=True)
            if df.empty or len(df) < 6:
                continue
            h, b_ = _dists_atr(df)
            dessus_t.append(h)
            dessous_t.append(b_)
            for col in PREV_FIABLES:
                if col in brut.columns:
                    excursions += _excursions_regagnees(brut, col)
            cv = pd.to_numeric(df.get("dist_cur_vah"), errors="coerce")
            close = pd.to_numeric(df["close"], errors="coerce")
            vah = close + cv * TICK
            heures = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.hour
            for hr, delta in zip(heures.iloc[1:], vah.diff().abs().iloc[1:]):
                if np.isfinite(delta):
                    derive_h.setdefault(int(hr), []).append(delta / TICK)
        haut = pd.concat(dessus_t).dropna()
        bas = pd.concat(dessous_t).dropna()
        proche = pd.concat([haut, bas]).dropna()
        # Un BALAYAGE dure des minutes, pas des heures : l'excursion d'un
        # aller-retour de trois heures au-dela d'un niveau n'est pas un sweep.
        # Les deux se rapportent ; le buffer prend la version bornee (<= 15
        # min, le grain d'une barre de decision), et c'est ecrit.
        exc = pd.Series([p for p, _d in excursions])
        exc_sweep = pd.Series([p for p, d in excursions if d <= 15])
        lignes += ["## %s — %d jours, %d barres cash" % (sym, len(jours), len(haut)),
                   "",
                   "### 1. Premier niveau, distance en ATR (les deux cotes)",
                   "| quantile | au-dessus | au-dessous | confondu |",
                   "|---|---|---|---|"]
        for q in (.10, .25, .50, .75, .90):
            lignes.append("| p%02d | %.3f | %.3f | %.3f |"
                          % (int(q * 100), haut.quantile(q), bas.quantile(q),
                             proche.quantile(q)))
        lignes += ["",
                   "### 2. Buffer de balayage (prev_* regagnes, 1 min, ticks)",
                   ("tous episodes : n = %d | p50 %.1f | p75 %.1f | p90 %.1f"
                    % (len(exc), exc.quantile(.5), exc.quantile(.75),
                       exc.quantile(.9))) if len(exc) else "AUCUN episode",
                   ("**SWEEPS (<= 15 min)** : n = %d | p50 %.1f | **p75 %.1f**"
                    " | p90 %.1f — le buffer prend celui-ci"
                    % (len(exc_sweep), exc_sweep.quantile(.5),
                       exc_sweep.quantile(.75), exc_sweep.quantile(.9)))
                   if len(exc_sweep) else "AUCUN sweep <= 15 min",
                   "",
                   "### 3. Derive mediane de cur_vah par heure UTC (ticks/barre)",
                   "| heure | derive p50 | n |", "|---|---|---|"]
        for hr in sorted(derive_h):
            v = pd.Series(derive_h[hr])
            lignes.append("| %02d | %.1f | %d |" % (hr, v.median(), len(v)))
        lignes.append("")
    chemin = ("V3/layers/L5_risque/rapports/distributions_niveaux_%s.md"
              % datetime.now(timezone.utc).strftime("%Y%m%d"))
    open(chemin, "w", encoding="utf-8").write("\n".join(lignes))
    print("rapport : %s" % chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
