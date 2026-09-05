"""Classe les colonnes en trois niveaux avant la reduction.

  A  verifiee par identite      — derriere un des checks a 0,0 % sur ES ET NQ
  B  non verifiable par identite — sa source n'est pas dans le fichier (MenthorQ,
     VIX, GEX, ctx_*, booleens, Battle Navale). Entre si elle passe quatre
     controles de plausibilite.
  C  disqualifiee                — §7 hors noyau, morte, fuite, ou remplacee
     par recalc.py

Le niveau est ecrit dans la colonne `provenance` de la sortie. Une hypothese
qui ne repose que sur du niveau B doit le dire : « source Sierra, formule non
verifiee » n'est pas « verifiee ».

Usage : python -X utf8 CORE/research/classer_colonnes.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.features import recalc  # noqa: E402
from CORE.research.semantic_check_fable import JOURS_EN_PANNE  # noqa: E402

# --- niveau C : listes fermees, tirees de CONVENTIONS.md §7 -----------------
REMPLACEES = {
    "momentum_3b", "momentum_5b", "dist_prev_vwap", "dist_prev_vwap_sd1u",
    "dist_prev_vwap_sd1d", "dist_asia_high_pct", "dist_asia_low_pct",
    "dist_london_high_pct", "dist_london_low_pct", "dist_cash_high_atr",
    "dist_cash_low_atr", "dist_prev_vpoc_pct", "bar_body_ticks", "bar_body_pct",
    "range_size_ticks", "dist_1d_max_ticks", "dist_1d_max_ticks_pct",
}
HORS_NOYAU = {"delta_day", "cvd_session", "ctx_price_slope_5"}
# Niveaux bruts : l'alias DMP pointe vers l'etude courante (INCIDENT #76).
ALIAS_DMP = {"prev_vpoc", "prev_vah", "prev_val", "open_cash", "open_830"}
FUITE = re.compile(r"_fwd|^ts|^date_|^session_date$|^boot_id$|^schema|_id$")

# --- bornes de plausibilite pour le niveau B --------------------------------
BORNES = {
    "vix": (5.0, 90.0),
    "iv_30d": (0.0, 200.0),
    "pc_": (0.0, 20.0),
}
MAX_NULLS_JOUR = 0.10
BOOL_MIN, BOOL_MAX = 0.02, 0.98
# En dessous : la colonne ne se declenche jamais, elle est morte.
BOOL_MORT = 0.001
MAX_DERIVE_BOOT = 0.50


def colonnes_verifiees(sym_csv):
    """Colonnes portees par un check a 0,0 % sur les deux instruments."""
    d = [pd.read_csv(f) for f in sym_csv]
    for x in d:
        x.columns = [c.strip() for c in x.columns]

    def t(x):
        return x[x.columns[1]].astype(str).str.rstrip("%").replace("N/A", "nan").astype(float)

    m = d[0][["check"]].assign(a=t(d[0])).merge(
        d[1][["check"]].assign(b=t(d[1])), on="check")
    ok = m[(m.a == 0) & (m.b == 0)]["check"]
    cols = set()
    for nom in ok:
        # "dist_vwap_d = (vwap_d-close)/tick" -> dist_vwap_d
        tete = re.split(r"\s*(?:=|>=|<=|<->)\s*", nom)[0].strip()
        for mot in re.findall(r"[a-z_][a-z0-9_]{2,}", tete):
            cols.add(mot)
    return cols


def charger(sym, n_jours=None):
    """Tous les jours exploitables par defaut : classer sur 25 jours laisserait
    passer une colonne morte en juin et vivante en aout."""
    fichiers = sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))
    lignes = []
    for f in (fichiers[-n_jours:] if n_jours else fichiers):
        if os.path.basename(f)[:8] in JOURS_EN_PANNE:
            continue
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
            lignes.append(d)
    df = pd.DataFrame(lignes)
    df["_ts"] = recalc.horodatage(df)
    df = df.dropna(subset=["_ts"]).sort_values("_ts").drop_duplicates("_ts")
    df["_jour"] = pd.to_datetime(df["_ts"], unit="ms", utc=True).dt.date
    return df.reset_index(drop=True)


def est_niveau_prix(s, close):
    """Vrai si la colonne porte un prix absolu, quel que soit son nom."""
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() < 100:
        return False
    med, ref = float(x.abs().median()), float(close.median())
    return bool(np.isfinite(med) and np.isfinite(ref) and ref > 0
                and 0.5 * ref <= med <= 2.0 * ref)


def plausible(s, nom, jours, boots, close):
    """Rend (niveau, motif) parmi B, N, R, C.

    N — niveau de prix absolu : entree de `recalc.py`, jamais feature. Ni
        disqualifie ni retenu : sur 51 jours de tendance, `close`, `vwap_d`,
        `pdh`, `ib_high` formeraient un mega-cluster « prix » qui absorberait
        des distances.
    R — evenement rare : booleen actif entre 0,1 % et 2 %. Mis a part pour la
        phase 2, pas disqualifie. Le seuil unique de 2 % confondait
        `delta_divergence` (0,5 %, rare) avec une colonne morte (0,0 %).
    """
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() < 100:
        return "C", "moins de 100 valeurs"
    # 0. niveau de prix absolu : meme ordre de grandeur que le prix
    med_abs = float(x.abs().median())
    ref = float(close.median())
    if np.isfinite(med_abs) and np.isfinite(ref) and ref > 0:
        if 0.5 * ref <= med_abs <= 2.0 * ref:
            return "N", "niveau de prix (entree de recalc, pas feature)"
    # 1. nulls par jour
    nulls = x.isna().groupby(jours).mean()
    if float(nulls.mean()) > MAX_NULLS_JOUR:
        return "C", "nulls %.0f%% par jour" % (100 * nulls.mean())
    # 2. booleen : taux d'activation
    vals = set(x.dropna().unique()[:5])
    if x.nunique(dropna=True) <= 2 and vals <= {0.0, 1.0}:
        p = float(x.mean())
        if p < BOOL_MORT or p > 1 - BOOL_MORT:
            return "C", "booleen actif %.2f%% (mort)" % (100 * p)
        if p < BOOL_MIN or p > BOOL_MAX:
            return "R", "evenement rare, actif %.1f%%" % (100 * p)
        return "B", ""
    # 3. ordre de grandeur — sur le NIVEAU, jamais sur une distance a ce niveau.
    #    `dist_vix_call` oscille autour de zero ; lui appliquer les bornes du
    #    VIX (5-90) la rejetait a tort, avec cinq autres.
    if not nom.startswith("dist_"):
        for cle, (lo, hi) in BORNES.items():
            if cle in nom:
                med = float(x.median())
                if not (lo <= med <= hi):
                    return "C", "mediane %.2f hors [%g, %g]" % (med, lo, hi)
    # 4. derive au changement de boot — comparee a la derive QUOTIDIENNE
    #    NORMALE, pas dans l'absolu. Un niveau d'options change tous les jours
    #    par construction : sans ce rapport, on rejette toute colonne
    #    journaliere des qu'un redemarrage coincide avec un changement de
    #    strike. Dix-sept colonnes du contexte options etaient dans ce cas.
    if boots is not None:
        med_j = x.groupby(jours).median()
        if len(med_j) >= 6:
            saut = med_j.diff().abs()
            b = boots.reindex(med_j.index)
            chg = b.ne(b.shift()) & b.shift().notna()
            normal = float(saut[~chg].median())
            if chg.any() and np.isfinite(normal) and normal > 1e-9:
                au_boot = float(saut[chg].max())
                if np.isfinite(au_boot) and au_boot > 3.0 * normal * (1 + MAX_DERIVE_BOOT):
                    return "C", ("saut au boot %.0fx la derive quotidienne"
                                % (au_boot / normal))
    return "B", ""


def classer(sym, verifiees):
    df = charger(sym)
    close = pd.to_numeric(df["close"], errors="coerce")
    boots = (df.groupby("_jour")["boot_id"].first().astype(str)
             if "boot_id" in df.columns else None)
    out = []
    for c in df.columns:
        if c.startswith("_"):
            continue
        if c in REMPLACEES:
            out.append((c, "C", "remplacee par recalc.py"))
        elif c in HORS_NOYAU or c in ALIAS_DMP:
            out.append((c, "C", "hors noyau (alias ou §7)"))
        elif FUITE.search(c):
            out.append((c, "C", "metadonnee ou fuite"))
        elif est_niveau_prix(df[c], close):
            # Avant le test A : `high` et `sess_high` sont derriere un check a
            # 0 %, donc "verifies", mais ce sont des niveaux de prix. Les
            # laisser en A les ferait entrer dans le clustering.
            out.append((c, "N", "niveau de prix (entree de recalc, pas feature)"))
        elif c in verifiees:
            out.append((c, "A", "verifiee par identite"))
        else:
            niv, motif = plausible(df[c], c, df["_jour"], boots, close)
            out.append((c, niv, motif or "plausibilite OK"))
    return pd.DataFrame(out, columns=["colonne", "provenance", "motif"])


def main():
    verifiees = colonnes_verifiees(["DOCS/semantic_NQ_v4.csv",
                                    "DOCS/semantic_ES_v4.csv"])
    print("colonnes portees par un check a 0 %% sur ES et NQ : %d" % len(verifiees))
    res = {}
    for sym in ("NQ", "ES"):
        r = classer(sym, verifiees)
        res[sym] = r.set_index("colonne")
        print("\n%s — %d colonnes" % (sym, len(r)))
        print(r.provenance.value_counts().sort_index().to_string())
        c = r[r.provenance == "C"]
        top = c.motif.value_counts().head(6)
        print("  motifs de rejet : %s" % ", ".join("%s (%d)" % (k[:38], v)
                                                   for k, v in top.items()))
    # une colonne n'entre que si les deux instruments la retiennent
    com = res["NQ"].join(res["ES"], lsuffix="_NQ", rsuffix="_ES", how="inner")
    # Un desaccord entre les deux instruments vaut disqualification : une
    # colonne qui ne tient que d'un cote n'est pas une colonne sur laquelle
    # batir. C'est la meme exigence que la replication ES/NQ des hypotheses.
    # La replication ES/NQ vaut pour les motifs STRUCTURELS (nulls, morte, saut
    # au boot, effectif) : une colonne absente d'un cote ne sert a rien. Elle
    # ne vaut pas pour les motifs de SEUIL : un booleen a 1,8 % sur ES et 2,4 %
    # sur NQ n'est pas disqualifiable, il est rare des deux cotes.
    STRUCT = re.compile(r"nulls|moins de 100|saut au boot|mort")
    accord = com.provenance_NQ == com.provenance_ES
    struct = (com.motif_NQ.astype(str).str.contains(STRUCT)
              | com.motif_ES.astype(str).str.contains(STRUCT))
    # A defaut d'accord : C si le desaccord est structurel, sinon le niveau le
    # plus permissif des deux (A > B > R > N > C).
    rang = {"A": 0, "B": 1, "R": 2, "N": 3, "C": 4}
    permissif = com.apply(
        lambda r: min(r.provenance_NQ, r.provenance_ES, key=lambda v: rang[v]),
        axis=1)
    com["provenance"] = np.where(accord, com.provenance_NQ,
                                 np.where(struct, "C", permissif))
    com["motif"] = np.where(
        accord, com.motif_NQ,
        np.where(struct, "desaccord structurel ES/NQ",
                 "desaccord de seuil, niveau permissif retenu"))
    des = com[~accord]
    if len(des):
        print("\n=== %d desaccords ES/NQ, liste nominative ===" % len(des))
        for c, r in des.iterrows():
            print("   %-32s NQ=%s / ES=%s -> %s   (%s)"
                  % (c[:32], r.provenance_NQ, r.provenance_ES,
                     r.provenance, str(r.motif_NQ)[:34]))
    fin = com[["provenance", "motif"]].reset_index()
    fin.to_csv("DOCS/features_provenance.csv", index=False)
    print("\n=== RETENU POUR LA REDUCTION ===")
    print(fin.provenance.value_counts().sort_index().to_string())
    print("A + B = %d colonnes" % (fin.provenance != "C").sum())
    print("[ecrit] DOCS/features_provenance.csv")


if __name__ == "__main__":
    main()
