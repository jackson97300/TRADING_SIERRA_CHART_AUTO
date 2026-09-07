"""L1 v2 — la mesure refaite après l'audit du 07/09.

    python -X utf8 V3/layers/L1_biais/mesure_57j.py

Sortie : `rapports/biais_57j_v2.csv`. La v1 reste dans `rapports/`, annotée.

QUATRE CORRECTIONS, toutes venues de l'audit, toutes dans le même sens : la v1
donnait des intervalles trop étroits.

1. **Bootstrap par BLOC SEMAINE**, pas par jour. B1 lit la VWAP *semaine* : le
   prix y reste du lundi au vendredi. 60 jours, ce sont 9 semaines.
2. **Bootstrap APPARIÉ** : `avec` et `contre` partagent les jours en sens
   opposés. `hypot` supposait l'indépendance et sous-estimait l'IC.
3. **Contrôle négatif à 1 000 tirages**, un côté par SEMAINE. Un tirage unique
   est un exemple, pas une distribution.
4. **Le test SANS DÉCLENCHEUR** — la seule mesure d'un biais qui ne dépende
   d'aucun setup : devenir d'un long hypothétique sur toutes les barres cash,
   jours LONG contre jours SHORT.

LE CONFONDANT QUE CES TESTS CHERCHENT. `|dist_vwap_w|` médian vaut 2,13 ATR :
le côté de B1 mesure surtout **dans quel sens le prix est étiré**. Les signaux
« contre » sont à 91 % des sweep + reclaim — un fade. « Fader un prix étiré
marche mieux que le suivre » n'est pas un biais à l'envers, c'est de la
réversion intrajour lue à travers un déclencheur de réversion.

ATTENDU, ÉCRIT AVANT LA RELANCE (sinon ce n'est pas une prédiction) :
    - l'IC contient zéro sur les deux instruments ;
    - le test sans déclencheur est nul ;
    - l'effet ES, s'il existe, vit dans le tercile « loin ».

**Quoi qu'ils disent, rien n'est inversé.** Inverser B1 sur les 60 jours qui
l'ont produit, c'est `optimal_config.json`.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 3))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.research import hypotheses as H                        # noqa: E402
from V3 import stats                                             # noqa: E402
from V3.layers.L1_biais import biais                             # noqa: E402

HORIZON = 20
DECLENCHEURS = {"H3": H.h3, "H6": H.h6, "H7": H.h7, "H8": H.h8}


def jours_du_lot(sym):
    out = []
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)):
        m = re.search(r"(\d{8})", os.path.basename(f))
        if m:
            out.append(m.group(1))
    return out


def devenir(df, i, side):
    j = min(i + HORIZON, len(df) - 1)
    a = df["atr_barre"].iloc[i]
    if not np.isfinite(a) or a <= 0:
        return np.nan
    return float(side * (df["close"].iloc[j] - df["close"].iloc[i]) / a)


def signaux(df):
    out, vus = [], set()
    for nom, fn in DECLENCHEURS.items():
        for _c, (cond, side) in fn(df).items():
            for i in range(len(df)):
                try:
                    if bool(cond.iloc[i]) and (i, side) not in vus:
                        vus.add((i, side))
                        out.append((i, side, nom))
                except Exception:
                    break
    return sorted(out)


def _num(df, col, i):
    if col not in df.columns:
        return np.nan
    return pd.to_numeric(pd.Series([df[col].iloc[i]]), errors="coerce").iloc[0]


def lire_l1(df, i, atr_ref):
    """Le dict des composantes. `atr_ref` est l'ATR DE LA VEILLE.

    `atr_barre` est NaN avant la 7e barre : lire le biais plus tard
    normaliserait l'ouverture par la matinée qui la suit — une fuite. L'ATR de
    la veille est ce qu'un desk a sous les yeux à l'ouverture.

    Les deux autres ATR du dumper ont été identifiés le 07/09 :
    `atr_14m` = ATR-14 sur barres 1 min en TICKS (5,21 mesuré contre 5,29
    recalculé, écart 1,5 %) ; `atr` = 60,62 ticks, une fenêtre plus large que
    15 min (rapport 1,40 à l'ATR-15m converti). Aucun des deux n'est
    interchangeable avec `atr_barre`, qui est en POINTS sur la barre agrégée.
    """
    d = _num(df, "dist_vwap_w", i)
    dv = (float(d) * 0.25 / atr_ref) if np.isfinite(d) and atr_ref else None
    vah, val = _num(df, "dist_prev_vah", i), _num(df, "dist_prev_val", i)
    ouv = None
    if np.isfinite(vah) and np.isfinite(val):
        ouv = 1 if vah < 0 else (-1 if val > 0 else 0)
    return {"d_vwap_w": dv, "d_vwap_w_autre": dv, "smt_div": False,
            "issue_vwap_w": "tenu", "open_vs_va": ouv,
            "barres_inside_prev_va": 0, "_absdist": abs(dv) if dv else None}


def collecter(sym, minutes, cfg):
    """Une passe sur le lot. Rend tout ce dont les mesures ont besoin."""
    par_jour = {}
    atr_veille = None
    for jour in jours_du_lot(sym):
        df = charger_jour(sym, jour, minutes)
        if df.empty or len(df) < 6:
            continue
        # B1 est lu a la PREMIERE barre : avec l'ATR de la veille, rien
        # n'oblige a attendre. La v1 lisait a i=4, un decalage avec la spec.
        lec = lire_l1(df, 0, atr_veille)
        b = (biais.evaluer(lec, cfg) if atr_veille
             else dict(biais.AUCUN, trous=["atr_veille"], motif="premier_jour"))
        d = df["atr_barre"].dropna()
        if len(d):
            atr_veille = float(d.iloc[-1])
        par_jour[jour] = {
            "biais": b, "df": df, "absdist": lec.get("_absdist"),
            "trou": bool(b.get("trous")),
            "signaux": [(i, s, n, devenir(df, i, s)) for i, s, n in signaux(df)],
        }
    return par_jour


def sans_declencheur(par_jour, blocs):
    """LA mesure d'un biais qui ne dépend d'aucun setup.

    Devenir d'un LONG hypothétique sur **toutes** les barres cash, les jours où
    B1 dit LONG contre les jours où il dit SHORT. Si c'est nul, B1 n'oriente
    pas — et toute séparation par déclencheur est un artefact de sélection.
    """
    lg, sh = {}, {}
    for jour, p in par_jour.items():
        c = p["biais"]["cote"]
        if c not in ("LONG", "SHORT"):
            continue
        df = p["df"]
        v = [devenir(df, i, 1) for i in range(len(df))]
        v = [x for x in v if np.isfinite(x)]
        (lg if c == "LONG" else sh)[jour] = v
    return stats.difference_appariee(lg, sh, blocs)


def separation(par_jour, blocs, garder=None):
    """E[devenir | avec] − E[devenir | contre], IC apparié par bloc semaine.

    `garder(nom_declencheur, absdist)` filtre les signaux — sert aux terciles
    et à la lecture par déclencheur.
    """
    a, c, pour_hasard = {}, {}, {}
    for jour, p in par_jour.items():
        b = p["biais"]
        for i, side, nom, dev in p["signaux"]:
            if not np.isfinite(dev) or (garder and not garder(nom, p["absdist"])):
                continue
            pour_hasard.setdefault(jour, []).append((side, dev))
            r = biais.relation(b, side)
            if r == "avec":
                a.setdefault(jour, []).append(dev)
            elif r == "contre":
                c.setdefault(jour, []).append(dev)
    s, ic, nb = stats.difference_appariee(a, c, blocs)
    h = stats.distribution_hasard(pour_hasard, blocs)
    n_a = sum(len(v) for v in a.values())
    n_c = sum(len(v) for v in c.values())
    return {"separation": s, "ic": ic, "blocs": nb, "n_avec": n_a,
            "n_contre": n_c, "hasard_p5": h[0], "hasard_p50": h[1],
            "hasard_p95": h[2]}


def _f(x, n=3):
    return "None" if x is None or not np.isfinite(x) else ("%+.*f" % (n, x))


def verdict(r):
    s, ic = r["separation"], r["ic"]
    if r["n_avec"] < 30 or r["n_contre"] < 30:
        return "NON MESURABLE — %d avec / %d contre" % (r["n_avec"], r["n_contre"])
    if s is None or ic is None or not np.isfinite(ic):
        return "NON CALCULABLE"
    if abs(s) - ic <= 0:
        return "N'INFORME PAS — %s +/- %.3f, zero dedans" % (_f(s), ic)
    p5, p95 = r["hasard_p5"], r["hasard_p95"]
    if np.isfinite(p5) and p5 <= s <= p95:
        return ("DANS LE HASARD — %s, la distribution aleatoire va de %s a %s"
                % (_f(s), _f(p5), _f(p95)))
    # le SIGNE avant la magnitude : la v1 declarait ORIENTE une separation de
    # -0,78, ou les signaux CONTRE faisaient mieux que ceux qui suivaient.
    if s < 0:
        return "ORIENTE A L'ENVERS — %s : le suivre couterait" % _f(s)
    return "ORIENTE — %s +/- %.3f, hors du hasard [%s ; %s]" % (_f(s), ic, _f(p5), _f(p95))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=15)
    a = ap.parse_args()
    os.chdir(RACINE)
    cfg = biais.charger_seuils()
    seuils = {n: (d or {}).get("seuils") or {}
              for n, d in (cfg.get("composantes") or {}).items()}
    seuils["b1_actif"] = cfg.get("b1_actif", "B1p")

    print("L1 v2 — bootstrap par BLOC SEMAINE, apparie, hasard sur 1 000 tirages\n")
    lignes = []
    for sym in ("ES", "NQ"):
        pj = collecter(sym, a.minutes, seuils)
        blocs = stats.blocs_semaine(list(pj))
        n_trous = sum(1 for p in pj.values() if p["trou"])
        n_avis = sum(1 for p in pj.values()
                     if p["biais"]["cote"] != "AUCUN")
        n_sans_trou = len(pj) - n_trous
        print("  %s : %d jours, %d semaines" % (sym, len(pj), len(set(blocs.values()))))
        print("     couverture %d/%d jours SANS TROU (%.0f %%) ; %d trous a part"
              % (n_avis, n_sans_trou, 100 * n_avis / max(n_sans_trou, 1), n_trous))

        g = separation(pj, blocs)
        print("     TOUS declencheurs   %s" % verdict(g))

        # --- le test qui ne depend d'aucun setup --------------------------
        sd, sd_ic, sd_n = sans_declencheur(pj, blocs)
        etat = ("nul" if not np.isfinite(sd_ic) or abs(sd) - sd_ic <= 0
                else "NON NUL")
        print("     SANS DECLENCHEUR    %s +/- %s sur %d semaines -> %s"
              % (_f(sd), _f(sd_ic), sd_n, etat))

        # --- terciles d'extension : l'effet vit-il « loin » ? --------------
        ad = sorted(p["absdist"] for p in pj.values() if p["absdist"])
        if len(ad) >= 9:
            t1, t2 = np.percentile(ad, [33, 67])
            for nom, f in (("pres", lambda n, d: d is not None and d <= t1),
                           ("milieu", lambda n, d: d is not None and t1 < d <= t2),
                           ("loin", lambda n, d: d is not None and d > t2)):
                r = separation(pj, blocs, f)
                print("     tercile %-7s %s" % (nom, verdict(r)))

        # --- par declencheur ----------------------------------------------
        for nom in DECLENCHEURS:
            r = separation(pj, blocs, lambda n, d, _n=nom: n == _n)
            if r["n_avec"] or r["n_contre"]:
                print("     %-4s                %s" % (nom, verdict(r)))
        print()
        lignes.append({"sym": sym, "jours": len(pj),
                       "semaines": len(set(blocs.values())), "trous": n_trous,
                       "couverture_sans_trou": round(n_avis / max(n_sans_trou, 1), 4),
                       "separation": g["separation"], "ic_bloc_semaine": g["ic"],
                       "hasard_p5": g["hasard_p5"], "hasard_p95": g["hasard_p95"],
                       "sans_declencheur": sd, "sans_declencheur_ic": sd_ic,
                       "verdict": verdict(g)})

    sortie = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapports")
    os.makedirs(sortie, exist_ok=True)
    pd.DataFrame(lignes).to_csv(os.path.join(sortie, "biais_57j_v2.csv"),
                                index=False, encoding="utf-8")
    print("Quinze comparaisons affichees. A 5 %, une sort par hasard.")
    print("ecrit : %s" % os.path.join(sortie, "biais_57j_v2.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
