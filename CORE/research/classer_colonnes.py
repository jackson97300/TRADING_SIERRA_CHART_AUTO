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


def charger(sym, n_jours=25):
    lignes = []
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))[-n_jours:]:
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


def plausible(s, nom, jours, boots, close):
    """Quatre controles pour une colonne de niveau B. Rend (ok, motif)."""
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() < 100:
        return False, "moins de 100 valeurs"
    # 1. nulls par jour
    nulls = x.isna().groupby(jours).mean()
    if float(nulls.mean()) > MAX_NULLS_JOUR:
        return False, "nulls %.0f%% par jour" % (100 * nulls.mean())
    # 2. booleen : taux d'activation
    vals = set(x.dropna().unique()[:5])
    if x.nunique(dropna=True) <= 2 and vals <= {0.0, 1.0}:
        p = float(x.mean())
        if not (BOOL_MIN <= p <= BOOL_MAX):
            return False, "booleen actif %.1f%%" % (100 * p)
        return True, ""
    # 3. ordre de grandeur — sur le NIVEAU, jamais sur une distance a ce niveau.
    #    `dist_vix_call` oscille autour de zero ; lui appliquer les bornes du
    #    VIX (5-90) la rejetait a tort, avec cinq autres.
    if not nom.startswith("dist_"):
        for cle, (lo, hi) in BORNES.items():
            if cle in nom:
                med = float(x.median())
                if not (lo <= med <= hi):
                    return False, "mediane %.2f hors [%g, %g]" % (med, lo, hi)
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
                    return False, ("saut au boot %.0fx la derive quotidienne"
                                   % (au_boot / normal))
    return True, ""


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
        elif c in verifiees:
            out.append((c, "A", "verifiee par identite"))
        else:
            ok, motif = plausible(df[c], c, df["_jour"], boots, close)
            out.append((c, "B" if ok else "C",
                        "plausibilite OK" if ok else motif))
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
    accord = com.provenance_NQ == com.provenance_ES
    com["provenance"] = np.where(accord, com.provenance_NQ, "C")
    com["motif"] = np.where(accord, com.motif_NQ,
                            "desaccord ES/NQ : " + com.provenance_NQ
                            + " vs " + com.provenance_ES)
    fin = com[["provenance", "motif"]].reset_index()
    fin.to_csv("DOCS/features_provenance.csv", index=False)
    print("\n=== RETENU POUR LA REDUCTION ===")
    print(fin.provenance.value_counts().sort_index().to_string())
    print("A + B = %d colonnes" % (fin.provenance != "C").sum())
    print("[ecrit] DOCS/features_provenance.csv")


if __name__ == "__main__":
    main()
