"""SCENARIOS, prérequis 3 et 3 bis — la largeur des réactions PAR NATURE de
niveau, sur le lot (spec §2 : « la largeur dépend de la nature » ; complément
Fable : murs `mq_call` / `mq_put`, `gex_nearest`).

    python -X utf8 V3/scenarios/mesure_reactions.py

Pour chaque nature et chaque instrument, les fiches F23 (touche + hystérésis
de L1, `z_touche` 0 / `z_reset` 0,5 ATR) sur les niveaux FIGÉS de la journée :
  - `depassement` : de combien la barre du test a dépassé le niveau — la mèche
    au-delà, en ticks et en ATR (`atr_ref`) ; 0 si elle s'est arrêtée avant.
    C'est la largeur DEHORS qu'une zone doit avoir pour CONTENIR la réaction
    (Fable, 10/09, réponse 4 : zone asymétrique, `dehors` = p80 des
    dépassements SUR LES TESTS TENUS, `dedans` = P10 `seuil_ticks`) : la
    distribution sur les tests tenus (p50 / p80 / p90) est ce que
    `seuils.yaml` attend, null avant ; celle sur tous les tests est à côté.
  - `reagit` : la barre suivante clôture du côté d'où le prix venait (tenue
    causale, la même que `range_r`) — « part des murs touchés qui réagissent ».
  - `casse` : l'issue F23 finale (deux clôtures au-delà dans les huit barres).
  - `reaction_atr` : l'excursion dans le sens du rejet sur quatre barres (F23).
Un test dont le niveau a BOUGÉ entre la barre précédente et la barre du test
(> 1 tick — un mur déplacé à midi, un `gex_nearest` qui change de strike) est
compté à part et exclu des distributions : ce n'est pas une réaction, c'est
un `ZONE_DEPLACEE` — journalisé avec son HEURE (Fable, réponse 5 : un saut à
12h00-12h15 est la mise à jour MenthorQ, un saut à 10h17 est peut-être un
défaut de collecte ; les deux sont `ZONE_DEPLACEE`, le jour 61 les sépare
par heure). Le rapport compte les sauts de niveau par heure ET et par nature.
L'IB n'est lu qu'à partir de 10h30 ; les `cur_*` restent en quarantaine ; le
HVL n'est pas une zone (Fable) et n'est pas mesuré ici.
Écrit `V3/scenarios/rapports/reactions_niveaux_57j.md`. Aucun devenir de trade.
"""

from __future__ import annotations

import collections
import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import f23, recalc                           # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

RAPPORT = os.path.join(RACINE, "V3", "scenarios", "rapports", "reactions_niveaux_57j.md")
Z_TOUCHE, Z_RESET = 0.0, 0.5           # L1 seuils.yaml (mesurés le 06/09), pas des seuils nouveaux
I_DEBUT_IB = 4
HEURES = tuple(range(9, 16))
NATURES = collections.OrderedDict([
    ("VA_veille", ("dist_prev_vah", "dist_prev_val", "dist_prev_vpoc")),
    ("VWAP_jour", ("dist_vwap_d",)),
    ("IB", ("dist_ib_high", "dist_ib_low")),
    ("PDH_PDL", ("dist_pdh", "dist_pdl")),
    ("OVN", ("dist_ovn_high", "dist_ovn_low")),
    ("MUR_call_put", ("dist_mq_call", "dist_mq_put")),
    ("GEX_nearest", ("dist_gex_nearest_up", "dist_gex_nearest_dn")),
])
# FIGES A L'OUVERTURE. Les `prev_*_lvl` du brut ne sont pas figes sur le lot :
# en fenetre `w0` (avant le 05/09, CONVENTIONS §9) ils BASCULENT a 17:00 UTC
# = 13h00 ET, en pleine seance, et portent un profil anterieur jusque-la
# (INCIDENT_LOG 04/09 : « bascule a 17:00 UTC, porte le profil de
# l'avant-veille jusque-la, ecart median 111 points ») ; en `w1` (depuis le
# 05/09, la fenetre de la campagne) la session est a 17h ET et ils ne bougent
# plus (verifie 08/09 et 09/09). Le module ne lit que des niveaux figes :
# pour ces natures, le niveau de la journee est celui de la PREMIERE barre
# cash (9h30), recalcule ensuite en `dist` contre chaque cloture ; l'IB est
# fige a 10h30. La VA est ventilee w0 / w1 (`recalc.window_version`) : sur le
# lot, « VA_veille » w0 = un profil anterieur fige a 9h30, pas J-1 — la
# largeur de reaction a un niveau de profil fige, pas a LA veille. Les murs
# restent tels que livres (leur mise a jour de midi est un ZONE_DEPLACEE, pas
# un defaut). VWAP et GEX_nearest ne sont PAS des niveaux figes (ils bougent
# a chaque barre) : mesures pour information, jamais des zones.
FIGES_A = {"VA_veille": 0, "VA_veille_w1": 0, "PDH_PDL": 0, "OVN": 0, "IB": I_DEBUT_IB}
NON_FIGES = ("VWAP_jour", "GEX_nearest")
NATURES["VA_veille_w1"] = NATURES["VA_veille"]      # J-1 vraie : fenetre w1 seulement


def _fiches_niveau(df, col, fige_a=None):
    """(fiches enrichies, heures ET des sauts du niveau) pour une colonne.
    `fige_a` = indice de la barre dont le niveau vaut pour toute la journee."""
    if col not in df.columns:
        return [], []
    d = df.copy()
    d["atr_barre"] = d["atr_ref"]                       # le mètre de la chaîne
    close = pd.to_numeric(d["close"], errors="coerce")
    if fige_a is not None:
        d0 = pd.to_numeric(d[col], errors="coerce").iloc[fige_a]
        niv0 = float(close.iloc[fige_a]) + float(d0) * lot.TICK if np.isfinite(d0) else np.nan
        d[col] = (niv0 - close) / lot.TICK
        d.loc[d.index[:fige_a], col] = np.nan
    dist = pd.to_numeric(d[col], errors="coerce")
    niveau = close + dist * lot.TICK
    heures = recalc.minutes_et(pd.to_datetime(d["ts"], unit="ms", utc=True)) // 60
    bouge = [False] + [bool(np.isfinite(niveau.iloc[i]) and np.isfinite(niveau.iloc[i - 1])
                            and abs(niveau.iloc[i] - niveau.iloc[i - 1]) > lot.TICK)
                       for i in range(1, len(d))]
    sauts = [int(heures.iloc[i]) for i in range(len(d)) if bouge[i]]
    out = []
    for f in f23.fiches(d, None, col, lot.TICK, Z_TOUCHE, Z_RESET):
        i, cote = f["i"], f["cote"]
        h, l_, a = float(d["high"].iloc[i]), float(d["low"].iloc[i]), float(d["atr_ref"].iloc[i])
        dep = max(0.0, (h - niveau.iloc[i]) if cote > 0 else (niveau.iloc[i] - l_)) / lot.TICK
        j = i + 1
        v = dist.iloc[j] if j < len(dist) else np.nan
        reagit = bool(np.isfinite(v) and ((v > 0) == (cote > 0)))
        out.append({"i": i, "cote": cote, "bouge": bouge[i], "dep_ticks": float(dep),
                    "dep_atr": float(dep * lot.TICK / a) if a and a > 0 else None,
                    "reagit": reagit, "issue": f["issue"], "reaction_atr": f.get("reaction_atr")})
    return out, sauts


def mesurer(sym):
    par, sauts = collections.defaultdict(list), collections.defaultdict(collections.Counter)
    jours = 0
    for _, df, _ in lot.journees(sym):
        jours += 1
        wv = str(recalc.window_version(pd.Series([int(df["ts"].iloc[0])])).iloc[0])
        for nature, cols in NATURES.items():
            if nature == "VA_veille_w1" and wv != "w1":
                continue
            for col in cols:
                fs, s = _fiches_niveau(df, col, FIGES_A.get(nature))
                par[nature] += fs
                sauts[nature].update(s)
    return jours, par, sauts


def _q3(vals, nd):
    q = lot.quantiles(vals, (0.5, 0.8, 0.9))
    return "%s / %s / %s" % (lot.fmt(q[0.5], nd), lot.fmt(q[0.8], nd), lot.fmt(q[0.9], nd))


def bloc(sym, jours, par, sauts):
    out = ["## %s — %d journées" % (sym, jours), "",
           "Dépassement = mèche au-delà du niveau sur la barre du test ; **tenus** = tests dont la barre",
           "suivante clôture du côté d'origine (la population de `dehors`, Fable réponse 4). Pour",
           "comparaison, `dedans` = P10 `seuil_ticks` = 0,10 × atr_ref / tick (plancher 2 t).", "",
           "| nature | tests | bougé (exclus) | réagit | cassé (F23) | dép. TENUS ticks p50 / p80 / p90 | dép. TENUS ATR p50 / p80 / p90 | dép. TOUS ATR p50 / p80 / p90 | réaction ATR méd. (tenus) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for nature in NATURES:
        fs = par.get(nature, [])
        ok = [f for f in fs if not f["bouge"]]
        ten = [f for f in ok if f["reagit"]]
        n = len(ok)
        rea = [f["reaction_atr"] for f in ten
               if f["reaction_atr"] is not None and np.isfinite(f["reaction_atr"])]
        nom = nature + (" (non fige, pas une zone)" if nature in NON_FIGES else
                        " (fige a %s)" % ("9h30" if FIGES_A.get(nature) == 0 else "10h30") if nature in FIGES_A else " (tel que livre)")
        if nature == "VA_veille":
            nom += " — w0 : profil anterieur, pas J-1"
        out.append("| %s | %d | %d | %s | %s | %s | %s | %s | %s |" % (
            nom, n, len(fs) - n,
            "%.0f %%" % (100.0 * len(ten) / n) if n else "—",
            "%.0f %%" % (100.0 * sum(f["issue"] == "casse" for f in ok) / n) if n else "—",
            _q3([f["dep_ticks"] for f in ten], 1), _q3([f["dep_atr"] for f in ten], 3),
            _q3([f["dep_atr"] for f in ok], 3),
            lot.fmt(float(np.median(rea)) if rea else None, 3)))
    out += ["", "Sauts du niveau (> 1 tick entre deux barres 15 min) par heure ET — `ZONE_DEPLACEE` :", "",
            "| nature | " + " | ".join("%dh" % h for h in HEURES) + " | total |",
            "|---|" + "---|" * (len(HEURES) + 1)]
    for nature in NATURES:
        c = sauts.get(nature, collections.Counter())
        out.append("| %s | " % nature + " | ".join(str(c.get(h, 0)) for h in HEURES)
                   + " | %d |" % sum(c.values()))
    return out + [""]


def main():
    out = ["# Les réactions par nature de niveau — largeur des zones (prérequis 3 et 3 bis du module SCÉNARIOS)", "",
           "*Définitions écrites avant la mesure : en-tête de `mesure_reactions.py`. Fiches F23 (`z_touche` 0,",
           "`z_reset` 0,5 ATR — L1), niveaux figés seulement, `atr_ref` comme mètre. `depassement` = la mèche",
           "au-delà du niveau sur la barre du test ; `reagit` = tenue causale à la barre suivante ; `casse` =",
           "issue F23 finale. Un niveau qui a bougé entre deux barres est exclu (`ZONE_DEPLACEE`, pas une réaction).",
           "Les valeurs de `seuils.yaml` restent null : la largeur par nature est à FIXER sur ces distributions",
           "(Fable, réponse 4 : `dehors` = p80 des dépassements sur les tests tenus), pas lue dedans. Aucun",
           "devenir de trade.*", ""]
    for sym in ("ES", "NQ"):
        jours, par, sauts = mesurer(sym)
        out += bloc(sym, jours, par, sauts)
    os.makedirs(os.path.dirname(RAPPORT), exist_ok=True)
    open(RAPPORT, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("\n".join(out))
    print("rapport :", RAPPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
