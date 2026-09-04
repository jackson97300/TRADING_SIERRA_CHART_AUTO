"""Sur quelles features ES et NQ sont-ils trop differents pour partager un seuil ?

Pourquoi cet audit existe
-------------------------
Le projet a ete developpe d'abord sur NQ, puis applique a ES. Les seuils ont
suivi sans etre re-mesures. Le code l'avoue lui-meme :

    CORE/regime_engine.py:267    "grid search 03/05/2026 sur 14j NQ"
    CORE/mia_paper_trader.py:294 "grid search 14j NQ"
    CORE/bot3_v4_data_driven_engine.py:187  "15t NQ optimal backtest"

Consequence mesuree le 04/09 : sur ES, `single_print_count > 100` (seuil issu
de NQ) se declenchait 0,00 % du temps — le maximum observe sur ES est 84.
Six seuils du vote MODE etaient dans ce cas.

Ce script mesure l'ampleur du probleme sur TOUTES les features, pour qu'on
sache lesquelles peuvent partager un seuil et lesquelles ne le peuvent pas.

Methode
-------
Comparaison du 75e percentile de chaque feature entre ES et NQ, en seance US
uniquement (hors seance, les distributions sont encore differentes et le
melange brouillerait la mesure). Le facteur rapporte est toujours >= 1 :
    facteur = max(|p75_ES|, |p75_NQ|) / min(|p75_ES|, |p75_NQ|)

Lecture : un facteur de 5 signifie qu'un seuil unique se declenchera cinq fois
plus souvent sur un instrument que sur l'autre — donc qu'il sera faux pour au
moins l'un des deux.

Deux resultats contre-intuitifs, a garder en tete :
  - la normalisation en pourcentage ne suffit pas (`dist_mq_put_0dte_pct`
    garde un facteur 21) ;
  - le sens de l'ecart s'inverse selon la famille de features (ES est plus
    grand sur les tailles d'ordres, plus petit sur les distances), donc aucun
    facteur correctif global ne peut marcher.

Usage :
    python -X utf8 CORE/research/audit_ecart_es_nq.py
    python -X utf8 CORE/research/audit_ecart_es_nq.py --jours 40 --top 40
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd


def charger(symbole: str, jours: int, dossier: str, rth_seul: bool) -> pd.DataFrame:
    lignes = []
    motif = os.path.join(dossier, symbole, "2026*.jsonl")
    for chemin in sorted(glob.glob(motif))[-jours:]:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    lignes.append(json.loads(ligne))
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes).sort_values("ts").drop_duplicates("ts")
    if rth_seul and "is_cash_session" in df.columns:
        df = df[df["is_cash_session"] == True]  # noqa: E712
    return df.reset_index(drop=True)


def comparer(es: pd.DataFrame, nq: pd.DataFrame, min_barres: int) -> pd.DataFrame:
    lignes = []
    for c in [x for x in es.columns if x in nq.columns]:
        a, b = es[c], nq[c]
        if a.dtype == bool or b.dtype == bool:
            continue
        if not (pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)):
            continue
        a = pd.to_numeric(a, errors="coerce")
        b = pd.to_numeric(b, errors="coerce")
        if a.notna().sum() < min_barres or b.notna().sum() < min_barres:
            continue
        # Une feature quasi-binaire n'a pas de "seuil" a partager.
        if a.nunique() < 5 or b.nunique() < 5:
            continue
        pa, pb = a.quantile(0.75), b.quantile(0.75)
        if not (np.isfinite(pa) and np.isfinite(pb)):
            continue
        if abs(pa) < 1e-9 or abs(pb) < 1e-9:
            continue
        facteur = abs(pb / pa) if abs(pb) > abs(pa) else abs(pa / pb)
        lignes.append({
            "feature": c,
            "p75_ES": pa,
            "p75_NQ": pb,
            "facteur": facteur,
            "sens": "NQ plus grand" if abs(pb) > abs(pa) else "ES plus grand",
            "seuil_partageable": facteur < 1.5,
        })
    return (pd.DataFrame(lignes)
            .sort_values("facteur", ascending=False)
            .reset_index(drop=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--jours", type=int, default=20)
    ap.add_argument("--min-barres", type=int, default=500)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--tout", action="store_true",
                    help="inclure les barres hors seance (defaut : seance US seule)")
    ap.add_argument("--sortie", default="DOCS/ECART_ES_NQ_PAR_FEATURE.csv")
    args = ap.parse_args()

    es = charger("ES", args.jours, args.data, not args.tout)
    nq = charger("NQ", args.jours, args.data, not args.tout)
    if es.empty or nq.empty:
        print("donnees manquantes dans %s" % args.data)
        return 1

    df = comparer(es, nq, args.min_barres)
    if df.empty:
        print("aucune feature comparable")
        return 1

    total = len(df)
    print("%d features numeriques comparables (%s, %d jours)"
          % (total, "24h" if args.tout else "seance US", args.jours))
    print("ES : %d barres    NQ : %d barres\n" % (len(es), len(nq)))

    for seuil in (1.5, 2.0, 3.0, 5.0, 10.0):
        n = int((df["facteur"] >= seuil).sum())
        print("   ecart >= x%-5.1f : %4d features  (%5.1f %%)"
              % (seuil, n, 100.0 * n / total))

    partageables = int(df["seuil_partageable"].sum())
    print("\n   seuil partageable entre ES et NQ (ecart < x1.5) : %d / %d (%.1f %%)"
          % (partageables, total, 100.0 * partageables / total))

    print("\nTOP %d — un seuil unique y est FAUX pour au moins un des deux :" % args.top)
    print("   %-32s %11s %11s %9s" % ("feature", "p75 ES", "p75 NQ", "facteur"))
    for _, r in df.head(args.top).iterrows():
        print("   %-32s %11.2f %11.2f     x%.1f"
              % (r["feature"][:32], r["p75_ES"], r["p75_NQ"], r["facteur"]))

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    df.to_csv(args.sortie, index=False)
    print("\nTable complete -> %s" % args.sortie)
    print("Avant de poser un seuil sur une feature, verifier sa ligne ici.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
