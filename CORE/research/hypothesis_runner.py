"""Le runner de la mission phase 2 — a l'aveugle.

Il calcule signaux et triple barriere pour toutes les hypotheses, sur ES et NQ,
**sans afficher le moindre resultat intermediaire**. Le tableau de survie
s'affiche une fois, complet. Ce n'est pas de la mise en scene : c'est ce qui
empeche « tiens, H6 marche mieux avec 1,3 au lieu de 1,5 » de se produire sans
que personne s'en apercoive.

Regles d'execution, toutes tirees de MISSION_PHASE2.md §2 :

  ENTREE       la condition est evaluee sur la barre 5 min CLOTUREE t ;
               l'entree est a l'OUVERTURE de t+1. Aucune feature de t+1 n'est
               lue avant d'entrer. C'est la frontiere entre un backtest et un
               look-ahead — une barre de decalage, mais la seule qui compte.
  SIGNAUX      un signal par FRANCHISSEMENT (faux -> vrai), jamais par barre ou
               la condition reste vraie ; et pas de nouveau signal tant que le
               precedent n'a pas atteint une barriere.
  CIBLE        TP +1,5 ATR-5m, SL -1,0 ATR-5m, expiration 20 barres.
  ESPERANCE    P&L reel en ATR, net de couts. L'etiquette +1/-1/0 sert au taux
               de reussite, jamais au critere de survie : quand les expirations
               dominent, les deux signes divergent, et c'est le P&L qui paie.
  LECTURE      toute feature passe par `lire()`, qui applique la ligne
               `lecture` de feature_reduction.json. Un seuil « moins d'un ATR »
               lu directement sur une colonne `_atr` livree filtrerait a 0,25.
  EXCLUSIONS   les couples (colonne, jour) de features_stale.csv sont retires
               pour toute hypothese qui lit la colonne concernee.

LE LIVRABLE DE CE FICHIER N'EST PAS SON CODE, C'EST SON TEST.

Trois hypotheses factices, dont une doit SURVIVRE :

  aleatoire      condition tiree au sort           -> doit MOURIR
  toujours_vraie condition constante               -> doit MOURIR ou etre NON
                                                      TESTABLE (elle verifie la
                                                      regle du franchissement :
                                                      une condition toujours
                                                      vraie ne franchit qu'une
                                                      fois par jour)
  fuyante        lit le futur (close[t+3] - close[t]) -> doit SURVIVRE, avec un
                                                      N enorme et une esperance
                                                      insolente

Le troisieme est le seul controle POSITIF, et c'est lui qui valide
l'instrument. Un runner casse qui rend zero sur tout est indiscernable d'un
marche sans edge. La fuyante reste dans la suite de tests pour toujours — comme
les identites de `semantic_check`, elle doit crier le jour ou quelqu'un touche
au calcul de la triple barriere.

Usage :
    python -X utf8 CORE/research/hypothesis_runner.py --factices
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.features import recalc  # noqa: E402
from CORE.research.semantic_check_fable import JOURS_EN_PANNE  # noqa: E402

TP_ATR, SL_ATR, EXPIRATION = 1.5, -1.0, 20
MINUTES_BARRE = 5
N_JOURS_RECHERCHE = 40
N_BLOCS, TAILLE_BLOC = 5, 8
N_MIN_SIGNAUX = 40
N_MIN_JOURS = 5
MAX_CONCENTRATION = 0.60
N_HYPOTHESES = 10          # pour Bonferroni
N_BOOTSTRAP = 2000


# ---------------------------------------------------------------------------
# Chargement et agregation
# ---------------------------------------------------------------------------

def charger(sym, cols=None):
    lignes = []
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)):
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
            lignes.append({c: d.get(c) for c in cols} if cols else d)
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    df["ts"] = recalc.horodatage(df)
    df = df.dropna(subset=["ts"]).sort_values("ts").drop_duplicates("ts")
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[recalc.est_cash(df["dt"])].reset_index(drop=True)


def agreger_5min(df):
    """Barres 5 min alignees sur 9h30 ET. Flux sommes, extremes max/min,
    etats pris a la derniere barre."""
    d = df.set_index("dt")
    o = d.resample("5min", origin="start_day", label="left", closed="left")
    out = pd.DataFrame({
        "open": o["open"].first(), "high": o["high"].max(),
        "low": o["low"].min(), "close": o["close"].last(),
        "total_vol": o["total_vol"].sum() if "total_vol" in d else np.nan,
        "delta_bar": o["delta_bar"].sum() if "delta_bar" in d else np.nan,
    }).dropna(subset=["close"])
    out["ts"] = (out.index.astype("int64") // 1_000_000)
    out["jour"] = out.index.date
    # ATR-5m recalcule sur les barres agregees : jamais l'ATR 1 min.
    tr = pd.concat([out["high"] - out["low"],
                    (out["high"] - out["close"].shift()).abs(),
                    (out["low"] - out["close"].shift()).abs()], axis=1).max(axis=1)
    out["atr5"] = tr.rolling(14, min_periods=7).mean()
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Signaux et triple barriere
# ---------------------------------------------------------------------------

def signaux_par_franchissement(cond, sorties):
    """Indices d'entree : la condition passe de faux a vrai, et le signal
    precedent a atteint une barriere.

    Sans cette regle, une condition vraie six barres de suite compte six
    signaux : N gonfle, l'independance du bootstrap tombe, et le critere
    `N >= 40` peut etre franchi par une seule journee.
    """
    c = pd.Series(cond).fillna(False).astype(bool).to_numpy()
    idx, libre_a = [], -1
    for i in range(1, len(c)):
        if c[i] and not c[i - 1] and i > libre_a:
            idx.append(i)
            libre_a = sorties[i] if sorties is not None else i
    return idx


def triple_barriere(df, i_signal, side, couts_atr):
    """Entree a l'OUVERTURE de t+1. Rend (etiquette, pnl_atr, i_sortie)."""
    j = i_signal + 1
    if j >= len(df):
        return None
    atr = df["atr5"].iloc[i_signal]
    if not np.isfinite(atr) or atr <= 0:
        return None
    entree = df["open"].iloc[j]
    tp = entree + side * TP_ATR * atr
    sl = entree + side * SL_ATR * atr
    fin = min(j + EXPIRATION, len(df) - 1)
    for k in range(j, fin + 1):
        h, b = df["high"].iloc[k], df["low"].iloc[k]
        if side > 0:
            if b <= sl:
                return -1, SL_ATR - couts_atr, k
            if h >= tp:
                return 1, TP_ATR - couts_atr, k
        else:
            if h >= sl:
                return -1, SL_ATR - couts_atr, k
            if b <= tp:
                return 1, TP_ATR - couts_atr, k
    pnl = side * (df["close"].iloc[fin] - entree) / atr - couts_atr
    return 0, float(pnl), fin


def evaluer(df, cond, side, couts_atr=0.0):
    """Rend un DataFrame de trades : jour, etiquette, pnl_atr."""
    sorties = np.full(len(df), -1)
    idx = signaux_par_franchissement(cond, None)
    trades = []
    libre_a = -1
    for i in idx:
        if i <= libre_a:
            continue
        r = triple_barriere(df, i, side, couts_atr)
        if r is None:
            continue
        etiq, pnl, k = r
        libre_a = k
        trades.append({"jour": df["jour"].iloc[i], "etiquette": etiq,
                       "pnl_atr": pnl})
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def bootstrap_par_jour(trades, n=N_BOOTSTRAP, graine=12345):
    """p-valeur unilaterale, blocs = journees entieres.

    Jamais par barre : les barres 5 min d'une meme journee sont autocorrelees,
    l'effectif reel est le nombre de JOURS.
    """
    if trades.empty:
        return 1.0
    par_jour = trades.groupby("jour")["pnl_atr"].mean()
    obs = float(par_jour.mean())
    if len(par_jour) < 3:
        return 1.0
    rng = np.random.default_rng(graine)
    v = par_jour.to_numpy()
    tirages = rng.choice(v, size=(n, len(v)), replace=True).mean(axis=1)
    return float((tirages <= 0).mean()) if obs > 0 else 1.0


def walk_forward(trades):
    """Signe de l'esperance sur chacun des N blocs de jours consecutifs."""
    if trades.empty:
        return []
    jours = sorted(trades["jour"].unique())
    blocs = [jours[i * TAILLE_BLOC:(i + 1) * TAILLE_BLOC] for i in range(N_BLOCS)]
    out = []
    for b in blocs:
        if not b:
            continue
        t = trades[trades["jour"].isin(b)]
        out.append(float(t["pnl_atr"].mean()) if len(t) else np.nan)
    return out


def verdict(par_sym):
    """SURVIT / CANDIDATE / MEURT / NON TESTABLE, et POURQUOI."""
    motifs = []
    for sym, t in par_sym.items():
        if len(t) < N_MIN_SIGNAUX:
            return "NON TESTABLE", "N=%d sur %s (< %d)" % (len(t), sym, N_MIN_SIGNAUX)
    for sym, t in par_sym.items():
        if t["jour"].nunique() < N_MIN_JOURS:
            motifs.append("%d jours distincts sur %s" % (t["jour"].nunique(), sym))
        esp = float(t["pnl_atr"].mean())
        if esp <= 0:
            motifs.append("esperance %.3f ATR sur %s" % (esp, sym))
        gains = t[t["pnl_atr"] > 0].groupby("jour")["pnl_atr"].sum()
        if len(gains) and gains.max() / max(gains.sum(), 1e-9) > MAX_CONCENTRATION:
            motifs.append("concentration %.0f %% sur %s"
                          % (100 * gains.max() / gains.sum(), sym))
        wf = walk_forward(t)
        positifs = sum(1 for x in wf if np.isfinite(x) and x > 0)
        if positifs < 4:
            motifs.append("%d/%d blocs positifs sur %s" % (positifs, len(wf), sym))
    if motifs:
        return "MEURT", " ; ".join(motifs[:3])
    ps = [bootstrap_par_jour(t) for t in par_sym.values()]
    seuil = 0.05 / N_HYPOTHESES
    if max(ps) >= seuil:
        return "CANDIDATE", "p=%.4f >= %.4f (Bonferroni)" % (max(ps), seuil)
    return "SURVIT", "p=%.4f < %.4f" % (max(ps), seuil)


# ---------------------------------------------------------------------------
# Hypotheses factices — le test du runner
# ---------------------------------------------------------------------------

def _factices(df, rng):
    """Rend {nom: (condition, side)}. La fuyante lit le futur EXPRES."""
    n = len(df)
    fwd = df["close"].shift(-3) - df["close"]
    return {
        "aleatoire": (pd.Series(rng.random(n) < 0.02, index=df.index), 1),
        "toujours_vraie": (pd.Series(True, index=df.index), 1),
        "fuyante_LOOKAHEAD": (fwd > 0.5 * df["atr5"], 1),
    }


def tester_factices():
    print("TEST DU RUNNER — trois hypotheses factices.")
    print("Attendu : aleatoire MEURT, toujours_vraie MEURT ou NON TESTABLE,")
    print("          fuyante SURVIT. Si la fuyante meurt, le runner est faux.\n")
    rng = np.random.default_rng(4242)
    dfs = {}
    for sym in ("NQ", "ES"):
        brut = charger(sym, cols=("ts", "open", "high", "low", "close",
                                  "total_vol", "delta_bar",
                                  "data_quality_flag"))
        if brut.empty:
            print("[%s] aucune donnee" % sym)
            return 1
        d = agreger_5min(brut)
        jours = sorted(d["jour"].unique())[:N_JOURS_RECHERCHE]
        dfs[sym] = d[d["jour"].isin(jours)].reset_index(drop=True)
        print("  %s : %d barres 5 min, %d jours" % (sym, len(dfs[sym]), len(jours)))
    print()
    resultats = []
    for nom in ("aleatoire", "toujours_vraie", "fuyante_LOOKAHEAD"):
        par_sym = {}
        for sym, d in dfs.items():
            cond, side = _factices(d, rng)[nom]
            par_sym[sym] = evaluer(d, cond, side)
        v, pourquoi = verdict(par_sym)
        resultats.append((nom, v, pourquoi,
                          {s: len(t) for s, t in par_sym.items()},
                          {s: round(float(t["pnl_atr"].mean()), 3) if len(t) else None
                           for s, t in par_sym.items()}))
    print("%-20s %-14s %-9s %-16s %s"
          % ("hypothese", "verdict", "N (NQ/ES)", "esperance ATR", "pourquoi"))
    print("-" * 108)
    for nom, v, p, n, e in resultats:
        print("%-20s %-14s %-9s %-16s %s"
              % (nom, v, "%d/%d" % (n.get("NQ", 0), n.get("ES", 0)),
                 "%s / %s" % (e.get("NQ"), e.get("ES")), p[:44]))
    attendu = {"aleatoire": {"MEURT", "NON TESTABLE"},
               "toujours_vraie": {"MEURT", "NON TESTABLE"},
               "fuyante_LOOKAHEAD": {"SURVIT", "CANDIDATE"}}
    echecs = [n for n, v, _, _, _ in resultats if v not in attendu[n]]
    print()
    if echecs:
        print("ECHEC DU TEST : %s hors de l'attendu." % ", ".join(echecs))
        print("Le runner est faux — ne pas l'utiliser sur les vraies hypotheses.")
        return 1
    print("Le runner rejette le bruit ET reconnait un edge. Instrument valide.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factices", action="store_true",
                    help="teste le runner sur trois hypotheses factices")
    a = ap.parse_args()
    if a.factices:
        return tester_factices()
    print("Les dix hypotheses ne sont pas encore figees "
          "(MISSION_PHASE2.md, cases a trancher). Rien a executer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
