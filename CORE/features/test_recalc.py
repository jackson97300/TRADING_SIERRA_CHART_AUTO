"""Validation empirique de `recalc.py` contre les colonnes livrees par Sierra.

Le principe : chaque fonction est confrontee a une colonne dont on connait
desormais la definition exacte. Si la fonction reproduit la colonne, elle est
juste ; si elle ne la reproduit pas, l'une des deux est fausse et on sait
laquelle grace aux mesures de CONVENTIONS.md.

La VWAP est comparee sur la fenetre 17:00 UTC — celle que Sierra utilisait
jusqu'au 05/09 — parce que c'est la seule pour laquelle on dispose d'une
reference. La meme fonction appliquee a `session_sess` produira la VWAP juste.

Usage : python -X utf8 CORE/features/test_recalc.py [NQ|ES]
"""

from __future__ import annotations

import glob
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from CORE.features import recalc  # noqa: E402

COLS = ("ts_raw_ms", "data_quality_flag", "high", "low", "close", "total_vol",
        "vwap_d", "pdh", "pdl", "dist_pdh", "momentum_3b", "momentum_5b",
        "atr", "dist_prev_vpoc_atr", "prev_vpoc_lvl")
N_JOURS = 12


def charger(sym: str) -> pd.DataFrame:
    lignes = []
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))[-N_JOURS:]:
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("data_quality_flag") != "stable":
                continue
            lignes.append({c: d.get(c) for c in COLS})
    df = pd.DataFrame(lignes)
    for c in COLS:
        if c != "data_quality_flag":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts_norm"] = recalc.normaliser_ts(df["ts_raw_ms"])
    df = (df.dropna(subset=["ts_norm", "close"])
            .sort_values("ts_norm").drop_duplicates("ts_norm")
            .reset_index(drop=True))
    df["dt"] = pd.to_datetime(df["ts_norm"], unit="ms", utc=True)
    return df


def verdict(nom: str, ecart: pd.Series, seuil: float, unite: str) -> bool:
    e = ecart.dropna().abs()
    if e.empty:
        print("  %-34s AUCUNE DONNEE" % nom)
        return False
    ok = float(e.lt(seuil).mean())
    print("  %-34s median %8.4f %-6s | sous %g : %5.1f%%  %s"
          % (nom, e.median(), unite, seuil, 100 * ok,
             "OK" if ok > 0.90 else "ECHEC"))
    return ok > 0.90


def valider(sym: str) -> bool:
    df = charger(sym)
    print("\n########## %s — %d barres stable, %d jours"
          % (sym, len(df), df["dt"].dt.date.nunique()))

    # 0. la normalisation restitue-t-elle une minute par barre ?
    minutes = (df["ts_norm"] // 60000).nunique()
    print("  normaliser_ts : %d barres -> %d minutes distinctes (%s)"
          % (len(df), minutes, "OK" if minutes == len(df) else "COLLISIONS"))

    res = []
    # 1. VWAP sur la fenetre 17:00 UTC, la seule dont on a une reference
    cle_17 = (df["dt"] - pd.Timedelta(hours=17)).dt.date
    res.append(verdict("vwap_cumule vs vwap_d (17h UTC)",
                       recalc.vwap_cumule(df, cle_17) - df["vwap_d"], 1.0, "pt"))

    # 2. PDH / PDL — colonnes que le §6 fait recalculer par l'enricher, donc
    #    on valide les PROPRIETES, pas la correspondance avec Sierra. Exiger
    #    qu'un recalcul reproduise la colonne qu'il remplace n'a pas de sens :
    #    la fenetre exacte de `pdh` cote Sierra reste inconnue (aucune des six
    #    testees ne depasse 70,4 %), et c'est justement pourquoi on recalcule.
    cle_22 = (df["dt"] + pd.Timedelta(hours=2)).dt.date
    ext = recalc.extremes_veille(df, cle_22)
    # Une comparaison avec NaN renvoie False : le premier jour du lot n'a pas
    # de veille, il faut l'ecarter au lieu de le compter comme une violation.
    dispo = ext["pdh"].notna() & ext["pdl"].notna()
    ordre = (ext["pdh"] >= ext["pdl"])[dispo]
    print("  %-34s %5.1f%%  %s" % ("pdh >= pdl", 100 * ordre.mean(),
                                   "OK" if ordre.all() else "ECHEC"))
    res.append(bool(ordre.all()))
    nu = ext["pdh"].groupby(cle_22).nunique()
    nu = nu[nu > 0]
    fige = float(nu.eq(1).mean())
    print("  %-34s %5.1f%% des sessions  %s"
          % ("pdh fige sur la session", 100 * fige, "OK" if fige > 0.99 else "ECHEC"))
    res.append(fige > 0.99)
    acc = float((ext["pdh"] - df["pdh"]).abs().lt(0.51).mean())
    print("  %-34s %5.1f%%  (information, pas critere)"
          % ("dont concordant avec pdh Sierra", 100 * acc))

    # 3. distance en ticks, convention (niveau - close)
    res.append(verdict("dist_ticks vs dist_pdh",
                       recalc.dist_ticks(df["pdh"], df["close"], sym) - df["dist_pdh"],
                       1.5, "tick"))

    # 4. momentum : la colonne livree est un lag 1, pas un lag 3
    res.append(verdict("momentum(1) vs momentum_3b",
                       recalc.momentum(df["close"], 1) - df["momentum_3b"], 0.01, "pt"))
    res.append(verdict("momentum(2) vs momentum_5b",
                       recalc.momentum(df["close"], 2) - df["momentum_5b"], 0.01, "pt"))

    # 5. dist_atr : la colonne livree vaut 4x le vrai (ticks / atr en points)
    vrai = recalc.dist_atr(df["prev_vpoc_lvl"], df["close"], df["atr"])
    r = (df["dist_prev_vpoc_atr"] / vrai.replace(0, np.nan)).dropna()
    r = r[np.isfinite(r)]
    print("  %-34s rapport median %.3f (attendu 4,000)"
          % ("dist_prev_vpoc_atr livre / vrai", r.median() if len(r) else float("nan")))
    res.append(bool(len(r)) and abs(r.median() - 4.0) < 0.05)

    print("  --> %d / %d controles passes" % (sum(res), len(res)))
    return all(res)


if __name__ == "__main__":
    tout = [valider(s) for s in (sys.argv[1:] or ["NQ", "ES"])]
    print("\nRESULTAT : %s" % ("TOUS LES CONTROLES PASSENT" if all(tout)
                               else "AU MOINS UN CONTROLE ECHOUE"))
    sys.exit(0 if all(tout) else 1)
