"""Quelle feature predit reellement si le marche va tendre ou tourner en rond ?

Pourquoi cet audit existe
-------------------------
Le vote MODE de `CORE/regime_engine.py` a ete construit a partir de la theorie
Market Profile, avec des poids inventes (IB=2, day_type=2, autres=1) et un
seuil invente, puis n'a JAMAIS ete confronte au marche. L'audit du 04/09 a
montre que ses criteres etaient soit des horloges de session, soit des
constantes :

    day_type = "NormVariation" sur 20 jours / 20, ES et NQ
    open_type = UNKNOWN sur 74 % des barres
    profile_shape du cote range sur 75 % des barres
    single_print_count, bars_in_va, sess_range_atr : compteurs cumules

Reparer les seuils d'un tel systeme ne sert a rien. Il faut repartir d'un
resultat OBSERVABLE et mesurer ce qui le predit.

Methode
-------
1. **Resultat observable** : l'Efficiency Ratio de Kaufman sur les H barres
   suivantes.

       ER = |close[t+H] - close[t]| / somme(|close[i+1] - close[i]|)

   ER proche de 1 : le marche est alle quelque part en ligne droite (trend).
   ER proche de 0 : il a parcouru du chemin pour revenir au point de depart
   (range). C'est une mesure standard, objective, sans parametre discutable
   autre que l'horizon.

2. **Classes extremes** : TREND = ER au-dessus du 70e percentile, RANGE = ER
   sous le 30e. On ecarte volontairement le milieu, ou l'etiquette est
   ambigue et n'apprend rien.

3. **AUC par feature** : probabilite qu'une barre TREND ait une valeur plus
   elevee qu'une barre RANGE. 0.50 = aucune information. On mesure l'ecart
   |AUC - 0.50|.

4. **Anti data-mining** (incident #28 : 600 combinaisons, 5/5 NOGO) :
   - decoupage TEMPOREL train / test, le test n'est jamais utilise pour
     choisir quoi que ce soit ;
   - une feature n'est retenue que si elle tient sur les DEUX periodes,
     avec le MEME signe ;
   - correction de Benjamini-Hochberg sur les p-values, parce que tester
     500 features garantit des faux positifs ;
   - mesure separee ES et NQ : ce qui marche sur l'un ne vaut pas pour
     l'autre.

5. **Exclusions** : prix absolus (fuite de niveau), horodatages, features
   deja identifiees comme horloges, colonnes quasi-constantes.

Usage :
    python -X utf8 CORE/research/audit_features_vs_regime.py
    python -X utf8 CORE/research/audit_features_vs_regime.py --horizon 60
    python -X utf8 CORE/research/audit_features_vs_regime.py --tout  (hors RTH inclus)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# Colonnes a ne jamais tester : elles fuiteraient un niveau de prix, une date,
# ou repeteraient la cible.
_PREFIXES_EXCLUS = (
    "ts", "date", "session_date", "mins_", "hour",
    "price", "close", "open", "high", "low", "bar_high", "bar_low",
    "vwap_d", "vwap_m", "vwap_w",
)
_EXACTS_EXCLUS = {
    "price", "close", "open", "high", "low", "bar_high", "bar_low",
    "ts", "mins_et", "session", "session_id",
    # Cible et derives directs
    "er_forward", "classe",
}
# Horloges de session identifiees par tools/check_regime_calibration.py.
_HORLOGES = {
    "single_print_count", "bars_in_va", "sess_range_atr", "poc_bar_dist",
    "vwap_slope_10", "sess_range_ticks", "ib_range_ticks",
    "cvd_session", "ctx_cvd_session", "total_vol", "buy_vol", "sell_vol",
}


def est_exclue(nom: str) -> bool:
    if nom in _EXACTS_EXCLUS or nom in _HORLOGES:
        return True
    bas = nom.lower()
    if bas.startswith(_PREFIXES_EXCLUS):
        return True
    # Niveaux de prix absolus nommes explicitement.
    if bas.startswith(("prev_vpoc", "prev_vah", "prev_val", "cur_vpoc",
                       "cur_vah", "cur_val", "comp_", "pdh", "pdl",
                       "poc_price", "vah_price", "val_price")):
        return True
    return False


def est_niveau_de_prix(serie: pd.Series, prix_median: float) -> bool:
    """Detecte un niveau de prix absolu par son ordre de grandeur.

    Le filtre par nom ne suffit pas : `vwap_w`, `pdh`, `mq_call_resistance`
    et une dizaine d'autres sont des PRIX. Les laisser entrer revient a
    apprendre "quand ES cote 7700, le marche tend" — une propriete de la
    periode etudiee, pas du marche. C'est la fuite classique documentee dans
    `.claude/rules/data-quality.md`.

    Test robuste et independant du nommage : la mediane de la feature est-elle
    du meme ordre de grandeur que le prix ?
    """
    med = serie.median()
    if med is None or med != med or med <= 0:
        return False
    return 0.5 * prix_median <= med <= 2.0 * prix_median


def charger(symbole: str, jours: int, dossier: str) -> pd.DataFrame:
    motif = os.path.join(dossier, symbole, "2026*.jsonl")
    lignes = []
    for chemin in sorted(glob.glob(motif))[-jours:]:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    lignes.append(json.loads(ligne))
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    df = df.sort_values("ts").drop_duplicates(subset="ts", keep="last")
    return df.reset_index(drop=True)


def efficiency_ratio_forward(close: pd.Series, horizon: int) -> pd.Series:
    """ER de Kaufman calcule sur les `horizon` barres SUIVANTES.

    Le chemin parcouru est la somme des variations absolues barre a barre.
    Une somme nulle (marche fige) rend l'ER indefini : on renvoie NaN plutot
    que d'inventer une valeur.
    """
    deplacement = (close.shift(-horizon) - close).abs()
    pas = close.diff().abs()
    # somme glissante des `horizon` pas a venir
    chemin = pas.shift(-1).rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))
    er = deplacement / chemin.replace(0.0, np.nan)
    return er


def auc_et_p(valeurs_trend: np.ndarray, valeurs_range: np.ndarray):
    """AUC (proba qu'une barre TREND depasse une barre RANGE) et p-value."""
    n1, n2 = len(valeurs_trend), len(valeurs_range)
    if n1 < 30 or n2 < 30:
        return None, None
    try:
        u, p = stats.mannwhitneyu(valeurs_trend, valeurs_range,
                                  alternative="two-sided")
    except ValueError:
        return None, None
    return u / (n1 * n2), p


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    """Retourne un masque des hypotheses retenues apres correction BH."""
    n = len(pvals)
    if n == 0:
        return []
    ordre = np.argsort(pvals)
    seuils = (np.arange(1, n + 1) / n) * alpha
    tries = np.array(pvals)[ordre]
    passe = tries <= seuils
    if not passe.any():
        return [False] * n
    dernier = np.max(np.where(passe)[0])
    garde = np.zeros(n, dtype=bool)
    garde[ordre[:dernier + 1]] = True
    return garde.tolist()


def analyser(df: pd.DataFrame, horizon: int, part_train: float,
             seuil_train: float, seuil_test: float, chevauchant: bool = False):
    df = df.copy()
    df["er_forward"] = efficiency_ratio_forward(df["close"].astype(float), horizon)
    valides = df["er_forward"].notna()
    df = df[valides].reset_index(drop=True)

    # ECHANTILLONNAGE NON CHEVAUCHANT (defaut).
    # Deux barres consecutives partagent horizon-1 barres de futur : leurs ER
    # sont quasi identiques. Mann-Whitney et Benjamini-Hochberg supposent
    # l'independance des observations ; avec du chevauchement les p-values sont
    # massivement sous-estimees et l'on "decouvre" des features par dizaines.
    # Symptome observe le 04/09 : 0 feature retenue a H=15, 3 a H=30, 70 a
    # H=60, 91 a H=90 — le nombre suit l'horizon, pas le marche.
    # Cf Lopez de Prado, AFML ch.4 (sample uniqueness).
    if not chevauchant:
        df = df.iloc[::horizon].reset_index(drop=True)
    if len(df) < 200:
        return None, "pas assez d'observations independantes (%d)" % len(df)

    haut = df["er_forward"].quantile(0.70)
    bas = df["er_forward"].quantile(0.30)
    df["classe"] = np.where(df["er_forward"] >= haut, 1,
                            np.where(df["er_forward"] <= bas, 0, -1))
    df = df[df["classe"] >= 0].reset_index(drop=True)

    coupe = int(len(df) * part_train)
    train, test = df.iloc[:coupe], df.iloc[coupe:]

    prix_median = float(df["close"].astype(float).median())
    colonnes, exclues_prix = [], []
    for c in df.columns:
        if est_exclue(c):
            continue
        s = df[c]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        if s.notna().sum() < 0.5 * len(s):
            continue
        if s.nunique(dropna=True) < 3:
            continue
        if est_niveau_de_prix(s, prix_median):
            exclues_prix.append(c)
            continue
        colonnes.append(c)

    resultats = []
    for c in colonnes:
        a_tr, p_tr = auc_et_p(
            train.loc[train["classe"] == 1, c].dropna().to_numpy(),
            train.loc[train["classe"] == 0, c].dropna().to_numpy())
        if a_tr is None:
            continue
        a_te, p_te = auc_et_p(
            test.loc[test["classe"] == 1, c].dropna().to_numpy(),
            test.loc[test["classe"] == 0, c].dropna().to_numpy())
        if a_te is None:
            continue
        resultats.append({
            "feature": c,
            "auc_train": a_tr, "p_train": p_tr,
            "auc_test": a_te, "p_test": p_te,
            "ecart_train": abs(a_tr - 0.5),
            "ecart_test": abs(a_te - 0.5),
            "meme_sens": (a_tr - 0.5) * (a_te - 0.5) > 0,
        })

    if not resultats:
        return None, "aucune feature exploitable"

    res = pd.DataFrame(resultats)
    res["bh_train"] = benjamini_hochberg(res["p_train"].tolist())
    res["bh_test"] = benjamini_hochberg(res["p_test"].tolist())
    res["retenue"] = (res["bh_train"] & res["bh_test"] & res["meme_sens"]
                      & (res["ecart_train"] >= seuil_train)
                      & (res["ecart_test"] >= seuil_test))
    # Les retenues d'abord : c'est ce qui compte, pas le plus gros ecart brut.
    res = res.sort_values(["retenue", "ecart_test"],
                          ascending=[False, False]).reset_index(drop=True)
    info = {
        "n_total": len(df), "n_train": len(train), "n_test": len(test),
        "seuil_haut": haut, "seuil_bas": bas, "n_features": len(colonnes),
        "exclues_prix": exclues_prix,
    }
    return (res, info), None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=49)
    ap.add_argument("--horizon", type=int, default=30,
                    help="barres futures pour l'Efficiency Ratio (defaut 30)")
    ap.add_argument("--part-train", type=float, default=0.6)
    ap.add_argument("--seuil-train", type=float, default=0.05,
                    help="ecart minimal |AUC-0.5| sur la periode d'entrainement")
    ap.add_argument("--seuil-test", type=float, default=0.03,
                    help="ecart minimal |AUC-0.5| sur la periode de test")
    ap.add_argument("--chevauchant", action="store_true",
                    help="garder toutes les barres (echantillons NON "
                         "independants : p-values invalides, a n'utiliser que "
                         "pour comparaison)")
    ap.add_argument("--tout", action="store_true",
                    help="inclure les barres hors seance (defaut : RTH seul)")
    ap.add_argument("--sortie", default="DOCS/AUDIT_FEATURES_VS_REGIME.md")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    rapport = ["# Quelles features predisent le regime ?\n",
               "\nGenere par `CORE/research/audit_features_vs_regime.py`.\n",
               "\nCible : Efficiency Ratio de Kaufman sur les %d barres suivantes. "
               "TREND = ER au-dessus du 70e percentile, RANGE = sous le 30e.\n"
               % args.horizon,
               "\nUne feature est **retenue** seulement si elle est significative "
               "sur la periode d'entrainement ET sur la periode de test "
               "(Benjamini-Hochberg a 5 %%), avec le meme sens, et un ecart "
               "|AUC-0.50| d'au moins %.2f sur l'entrainement et %.2f sur le "
               "test.\n" % (args.seuil_train, args.seuil_test)]

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        df = charger(sym, args.jours, args.data)
        if df.empty:
            print("[%s] aucune donnee" % sym)
            continue
        if not args.tout and "is_cash_session" in df.columns:
            df = df[df["is_cash_session"] == True].reset_index(drop=True)  # noqa: E712

        sortie, erreur = analyser(df, args.horizon, args.part_train,
                                  args.seuil_train, args.seuil_test,
                                  chevauchant=args.chevauchant)
        if erreur:
            print("[%s] %s" % (sym, erreur))
            continue
        res, info = sortie

        entete = ("%s — %d barres classees (%d train / %d test), %d features testees"
                  % (sym, info["n_total"], info["n_train"], info["n_test"],
                     info["n_features"]))
        print("\n" + "=" * len(entete))
        print(entete)
        print("=" * len(entete))
        print("  seuil TREND : ER >= %.3f   seuil RANGE : ER <= %.3f"
              % (info["seuil_haut"], info["seuil_bas"]))
        print("  ecartees comme niveaux de prix absolus : %d  (%s%s)"
              % (len(info["exclues_prix"]),
                 ", ".join(info["exclues_prix"][:6]),
                 " ..." if len(info["exclues_prix"]) > 6 else ""))

        gardees = res[res["retenue"]]
        print("  features retenues : %d / %d" % (len(gardees), len(res)))
        print()
        print("  %-34s %9s %9s %8s" % ("feature", "AUC train", "AUC test", "retenue"))
        for _, r in res.head(args.top).iterrows():
            print("  %-34s %9.3f %9.3f %8s"
                  % (r["feature"][:34], r["auc_train"], r["auc_test"],
                     "OUI" if r["retenue"] else ""))

        rapport.append("\n## %s\n\n" % entete)
        rapport.append("Seuil TREND : ER >= %.3f. Seuil RANGE : ER <= %.3f.\n\n"
                       % (info["seuil_haut"], info["seuil_bas"]))
        rapport.append("**%d features retenues sur %d testees.**\n\n"
                       % (len(gardees), len(res)))
        rapport.append("| feature | AUC train | AUC test | ecart test | retenue |\n")
        rapport.append("|---|---|---|---|---|\n")
        for _, r in res.head(args.top).iterrows():
            rapport.append("| `%s` | %.3f | %.3f | %.3f | %s |\n"
                           % (r["feature"], r["auc_train"], r["auc_test"],
                              r["ecart_test"], "**OUI**" if r["retenue"] else ""))

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rapport)
    print("\nRapport : %s" % args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
