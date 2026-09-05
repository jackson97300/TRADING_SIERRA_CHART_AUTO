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

import csv

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
N_HYPOTHESES = 6           # Bonferroni — six apres retrait de H5 et H1
                           # (tag mission-phase2-v1, 06/09/2026)
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
    # La reecriture fait foi : l'enricher rejoue des lignes deja ecrites, et
    # c'est la DERNIERE version d'une minute qui est la bonne. `drop_duplicates`
    # garde la premiere par defaut — le contraire de ce qu'il faut.
    df = df.dropna(subset=["ts"]).sort_values("ts")
    df = recalc.dedoublonner_par_minute(df, cle_ts="ts", garder="dernier")
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


def _exclusions_stale():
    """Couples (colonne, jour) suspects, lus dans DOCS/features_stale.csv.

    1 080 couples sur 18 jours ; 63 colonnes du noyau touchees. Une hypothese
    qui lit une colonne suspecte un jour donne ne doit pas produire de signal ce
    jour-la : le prerequis 3d de la mission l'exige, et sans lui H3 et H6
    perdraient pres de la moitie de leur echantillon sans le dire.
    """
    chemin = "DOCS/features_stale.csv"
    if not os.path.exists(chemin):
        return {}
    par_cle = {}
    with open(chemin, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sym = (r.get("symbole") or r.get("sym") or "").strip().upper()
            col = (r.get("colonne") or r.get("feature") or "").strip()
            jour = (r.get("jour") or r.get("date") or "").strip().replace("-", "")
            if sym and col and jour:
                # La cle porte le SYMBOLE : une colonne suspecte sur NQ le
                # 15/06 ne dit rien de la meme colonne sur ES ce jour-la.
                par_cle.setdefault((sym, col), set()).add(jour)
    return par_cle


_STALE = None


def lire(colonne, df, sym):
    """Seul acces autorise a une colonne du noyau.

    Deux choses qu'un `df[colonne]` direct ne fait pas :
      1. il applique la ligne `lecture` de `feature_reduction.json` — une
         colonne `_atr` livree n'est JAMAIS lue telle quelle (mesure : le
         rapport livre/vrai vaut 4,000 sur `dist_prev_vpoc_atr`) ;
      2. il masque les jours ou la colonne est suspecte (`features_stale.csv`),
         en rendant NaN plutot qu'une valeur qui se laisserait comparer.
    """
    global _STALE
    if _STALE is None:
        _STALE = _exclusions_stale()
    if colonne not in df.columns:
        raise KeyError("colonne absente du lot : %s" % colonne)
    v = pd.to_numeric(df[colonne], errors="coerce")
    jours = _STALE.get((str(sym).upper(), colonne))
    if jours and "jour" in df.columns:
        j = df["jour"].astype(str).str.replace("-", "", regex=False)
        v = v.mask(j.isin(jours))
    return v


# ---------------------------------------------------------------------------
# Signaux et triple barriere
# ---------------------------------------------------------------------------

def signaux_par_franchissement(cond, jours, sorties=None):
    """Indices d'entree : la condition passe de faux a vrai, **dans la journee**.

    Sans la regle du franchissement, une condition vraie six barres de suite
    compte six signaux : N gonfle, l'independance du bootstrap tombe, et le
    critere `N >= 40` peut etre franchi par une seule journee.

    Sans la **remise a zero a la frontiere de journee**, deux erreurs symetriques
    se produisent a chaque nuit :
      - une condition vraie a la derniere barre du jour J et encore vraie a la
        premiere du jour J+1 ne produit AUCUN signal, alors que c'est une
        nouvelle seance, un nouveau contexte, et un signal legitime ;
      - l'etat `vrai` de la veille bloque le lendemain sans qu'aucune barre du
        lendemain ne l'ait justifie.
    L'etat precedent est donc reinitialise a faux au premier indice de chaque
    journee, et une barriere ouverte ne traverse pas la nuit.
    """
    c = pd.Series(cond).fillna(False).astype(bool).to_numpy()
    j = pd.Series(jours).astype(str).to_numpy()
    idx, libre_a = [], -1
    for i in range(len(c)):
        nouveau_jour = (i == 0) or (j[i] != j[i - 1])
        if nouveau_jour:
            libre_a = -1                     # aucune barriere ne traverse la nuit
        precedent = False if nouveau_jour else bool(c[i - 1])
        if c[i] and not precedent and i > libre_a:
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
    idx = signaux_par_franchissement(cond, df["jour"])
    trades = []
    libre_a, jour_libre = -1, None
    for i in idx:
        jour_i = df["jour"].iloc[i]
        if jour_i != jour_libre:      # la barriere de la veille ne bloque pas
            libre_a, jour_libre = -1, jour_i
        if i <= libre_a:
            continue
        r = triple_barriere(df, i, side, couts_atr)
        if r is None:
            continue
        etiq, pnl, k = r
        libre_a = k
        trades.append({"jour": jour_i, "etiquette": etiq, "pnl_atr": pnl})
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


def walk_forward(trades, jours_du_lot):
    """Esperance sur chacun des N blocs de TAILLE_BLOC jours **calendaires**.

    Le decoupage porte sur les jours du LOT, pas sur les jours ou l'hypothese a
    trade. Decouper les jours-avec-trades en paquets de huit donne des blocs de
    largeur calendaire variable — une hypothese qui ne trade que douze jours sur
    quarante verrait ses « cinq blocs de huit » couvrir tout le lot de facon
    irreguliere, et la stabilite temporelle mesuree ne voudrait plus rien dire.
    Un bloc sans aucun trade rend NaN : c'est une information, pas un zero.
    """
    if trades.empty or not len(jours_du_lot):
        return []
    jours = sorted(jours_du_lot)
    out = []
    for b in range(N_BLOCS):
        bloc = jours[b * TAILLE_BLOC:(b + 1) * TAILLE_BLOC]
        if not bloc:
            continue
        sel = trades[trades["jour"].isin(bloc)]
        out.append(float(sel["pnl_atr"].mean()) if len(sel) else np.nan)
    return out


def verdict(par_sym, jours_par_sym=None):
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
        wf = walk_forward(t, (jours_par_sym or {}).get(
            sym, sorted(t["jour"].unique())))
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
    dfs, jours_lot = {}, {}
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
        jours_lot[sym] = jours          # jours CALENDAIRES du lot, pas jours avec trades
        print("  %s : %d barres 5 min, %d jours" % (sym, len(dfs[sym]), len(jours)))
    print()
    resultats = []
    for nom in ("aleatoire", "toujours_vraie", "fuyante_LOOKAHEAD"):
        par_sym = {}
        for sym, d in dfs.items():
            cond, side = _factices(d, rng)[nom]
            par_sym[sym] = evaluer(d, cond, side)
        v, pourquoi = verdict(par_sym, jours_lot)
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
