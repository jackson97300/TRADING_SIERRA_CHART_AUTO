"""L1 — couverture, séparation, coût de l'obéissance, sur les 57 jours.

    python -X utf8 V3/layers/L1_biais/mesure_57j.py
    python -X utf8 V3/layers/L1_biais/mesure_57j.py --distributions

`--distributions` produit les seuils manquants (`z1_atr`) au lieu de mesurer.

TROIS GRANDEURS, PAS UN TAUX DE REJET. Un biais ne rejette pas, il oriente.

L'IC est bootstrappé **par jour**, pas par signal : les signaux d'une même
journée partagent le même biais et le même marché. Un IC qui les suppose
indépendants sous-estime l'intervalle — et fait sortir du bruit ce qui n'en
sort pas.

LA COUVERTURE CROISÉE est affichée par déclencheur, parce que la mesure du
06/09 a montré que le groupe « avec » peut être un résidu : 12 signaux contre
195 sur ES. Nos quatre déclencheurs sont des FADES ; un biais de tendance les
contredit par construction. Une séparation calculée sur douze cas n'est pas une
séparation.
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
from CORE.research.hypothesis_runner import triple_barriere      # noqa: E402
from V3.layers.L1_biais import biais                             # noqa: E402

HORIZON = 20
COUTS = {"NQ": (2.82, 2.00), "ES": (4.32, 5.00)}
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
    """(barre, sens, déclencheur), dédoublonnés par (barre, sens)."""
    out, vus = [], set()
    for nom, fn in DECLENCHEURS.items():
        for _cote, (cond, side) in fn(df).items():
            for i in range(len(df)):
                try:
                    if bool(cond.iloc[i]) and (i, side) not in vus:
                        vus.add((i, side))
                        out.append((i, side, nom))
                except Exception:
                    break
    return sorted(out)


def lire_l1(df, i, sym):
    """Le dict que les composantes attendent. `lecture.py` fera ça en propre ;
    ici on le construit au plus court pour mesurer."""
    a = df["atr_barre"].iloc[i]
    d = pd.to_numeric(pd.Series([df["dist_vwap_w"].iloc[i]]),
                      errors="coerce").iloc[0] if "dist_vwap_w" in df.columns else np.nan
    # `dist` est en TICKS, l'ATR en POINTS : sans le tick, le rapport est faux
    # d'un facteur quatre — la confusion qui a coûté huit incidents.
    dv = (float(d) * 0.25 / float(a)) if np.isfinite(d) and np.isfinite(a) and a > 0 else None
    vah = pd.to_numeric(pd.Series([df["dist_prev_vah"].iloc[i]]), errors="coerce").iloc[0] \
        if "dist_prev_vah" in df.columns else np.nan
    val = pd.to_numeric(pd.Series([df["dist_prev_val"].iloc[i]]), errors="coerce").iloc[0] \
        if "dist_prev_val" in df.columns else np.nan
    ouv = None
    if np.isfinite(vah) and np.isfinite(val):
        ouv = 1 if vah < 0 else (-1 if val > 0 else 0)
    return {"d_vwap_w": dv, "d_vwap_w_autre": dv, "smt_div": False,
            "issue_vwap_w": "tenu", "open_vs_va": ouv,
            "barres_inside_prev_va": 0}


def _ic_par_jour(par_jour, n=2000, graine=7):
    """Moyenne et IC 95 % bootstrappés sur les JOURS, pas sur les signaux."""
    jours = [np.mean(v) for v in par_jour.values() if len(v)]
    if len(jours) < 3:
        return (float(np.mean(jours)) if jours else np.nan), np.nan, len(jours)
    a = np.array(jours, dtype=float)
    rng = np.random.default_rng(graine)
    tirages = rng.choice(a, size=(n, len(a)), replace=True).mean(axis=1)
    lo, hi = np.percentile(tirages, [2.5, 97.5])
    return float(a.mean()), float((hi - lo) / 2), len(a)


def mesurer(sym, minutes, cfg):
    avec, contre, fantomes = {}, {}, []
    h_avec, h_contre = {}, {}
    croise = {n: [0, 0, 0] for n in DECLENCHEURS}     # avec, contre, sans
    n_jours_avis = n_jours = 0
    rng = np.random.default_rng(4242)

    for jour in jours_du_lot(sym):
        df = charger_jour(sym, jour, minutes)
        if df.empty or len(df) < 6:
            continue
        n_jours += 1
        # le biais se lit UNE FOIS par jour, a la 4e barre (le regime est lisible)
        b = biais.evaluer(lire_l1(df, min(4, len(df) - 1), sym), cfg)
        if b["cote"] != "AUCUN":
            n_jours_avis += 1
        faux = {"cote": "LONG" if rng.random() < 0.5 else "SHORT"}

        for i, side, nom in signaux(df):
            d = devenir(df, i, side)
            r = biais.relation(b, side)
            croise[nom][0 if r == "avec" else 1 if r == "contre" else 2] += 1
            if r == "avec":
                avec.setdefault(jour, []).append(d)
            elif r == "contre":
                contre.setdefault(jour, []).append(d)
                t = triple_barriere(df, i, side, COUTS.get(sym, COUTS["ES"]))
                if t is not None:
                    fantomes.append(float(t[1]))
            rh = biais.relation(faux, side)
            (h_avec if rh == "avec" else h_contre).setdefault(jour, []).append(d)

    m_a, ic_a, nj_a = _ic_par_jour(avec)
    m_c, ic_c, nj_c = _ic_par_jour(contre)
    hm_a, _x, _y = _ic_par_jour(h_avec)
    hm_c, _z, _w = _ic_par_jour(h_contre)
    sep = m_a - m_c if np.isfinite(m_a) and np.isfinite(m_c) else np.nan
    ic = float(np.hypot(ic_a, ic_c)) if np.isfinite(ic_a) and np.isfinite(ic_c) else np.nan
    sep_h = hm_a - hm_c if np.isfinite(hm_a) and np.isfinite(hm_c) else np.nan
    f = np.array(fantomes, dtype=float)
    n_avec = sum(len(v) for v in avec.values())
    n_contre = sum(len(v) for v in contre.values())

    return {
        "sym": sym, "jours": n_jours,
        "couverture": round(n_jours_avis / max(n_jours, 1), 4),
        "n_avec": n_avec, "jours_avec": nj_a,
        "n_contre": n_contre, "jours_contre": nj_c,
        "devenir_avec": round(m_a, 4) if np.isfinite(m_a) else None,
        "devenir_contre": round(m_c, 4) if np.isfinite(m_c) else None,
        "separation": round(sep, 4) if np.isfinite(sep) else None,
        "ic_par_jour": round(ic, 4) if np.isfinite(ic) else None,
        "separation_hasard": round(sep_h, 4) if np.isfinite(sep_h) else None,
        "cout_obeissance": round(float(f.sum()), 2) if len(f) else None,
        "n_fantomes": int(len(f)),
        "croise": croise,
    }


def verdict(r):
    n_a, n_c = r["n_avec"], r["n_contre"]
    if n_a < 30 or n_c < 30:
        return ("NON MESURABLE — %d signaux « avec » contre %d « contre ». Le "
                "groupe minoritaire est un residu, pas un echantillon."
                % (n_a, n_c))
    s, ic, sh = r["separation"], r["ic_par_jour"], r["separation_hasard"]
    if s is None or ic is None or not np.isfinite(ic):
        return "NON CALCULABLE"
    if abs(s) - ic <= 0:
        return "LE BIAIS N'INFORME PAS — separation %.3f +/- %.3f, zero dedans" % (s, ic)
    if sh is not None and abs(s) <= abs(sh):
        return "pas mieux que le hasard (%.3f contre %.3f)" % (s, sh)
    return "ORIENTE — separation %.3f +/- %.3f, hasard %.3f" % (s, ic, sh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=15)
    a = ap.parse_args()
    os.chdir(RACINE)
    cfg = biais.charger_seuils()
    seuils = {n: (d or {}).get("seuils") or {}
              for n, d in (cfg.get("composantes") or {}).items()}
    seuils["b1_actif"] = cfg.get("b1_actif", "B1p")
    if seuils.get("B1p", {}).get("z1_atr") is None:
        print("  z1_atr est null — lancer d'abord --distributions.\n")
    lignes = []
    print("L1 — couverture, separation (IC par JOUR), cout de l'obeissance\n")
    for sym in ("ES", "NQ"):
        r = mesurer(sym, a.minutes, seuils)
        lignes.append({k: v for k, v in r.items() if k != "croise"})
        print("  %s : %d jours, couverture %.0f %%"
              % (sym, r["jours"], 100 * r["couverture"]))
        print("     avec   n=%4d sur %2d jours  devenir %s"
              % (r["n_avec"], r["jours_avec"], r["devenir_avec"]))
        print("     contre n=%4d sur %2d jours  devenir %s"
              % (r["n_contre"], r["jours_contre"], r["devenir_contre"]))
        print("     couverture croisee par declencheur (avec / contre / sans) :")
        for nom, (x, y, z) in r["croise"].items():
            t = x + y + z
            print("        %-4s %4d / %4d / %4d   %5.1f %% avec"
                  % (nom, x, y, z, 100 * x / max(t, 1)))
        print("     %s\n" % verdict(r))
    sortie = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapports")
    os.makedirs(sortie, exist_ok=True)
    pd.DataFrame(lignes).to_csv(os.path.join(sortie, "biais_57j.csv"),
                                index=False, encoding="utf-8")
    print("Douze comparaisons sont affichees. A 5 %, une sort par hasard :")
    print("aucune lecture sur un seul intervalle.")
    print("\necrit : %s" % os.path.join(sortie, "biais_57j.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
