"""Reduction de features par clustering de correlation — le noyau non redondant.

La demande (Jackson, 04/09/2026)
--------------------------------
"Je collecte 626 colonnes. Les grands fonds arrivent a les mettre dans des
clusters et a reduire. Je veux continuer a tout collecter mais reduire en
local. Ce sera la base sur laquelle on prendra nos trades."

Ce que fait ce script, et ce qu'il ne fait pas
-----------------------------------------------
Il repond a UNE question : **quelles features apportent une information que
les autres n'apportent pas deja ?** Il ne dit rien de leur rentabilite.

Cette distinction est la protection principale contre le data mining. Une
selection fondee sur ce que les features PREDISENT fabrique des edges
imaginaires — l'incident #28 de ce projet a teste 600 combinaisons et
recolte 5 rejets sur 5. Une selection fondee sur la REDONDANCE n'a pas de
cible, donc rien a sur-ajuster : le resultat vaut quelle que soit la
strategie qu'on batira dessus ensuite.

Les six garde-fous
------------------
1. **Nettoyage avant tout calcul.** Vides, constantes, niveaux de prix
   absolus (fuite du niveau de marche — `.claude/rules/data-quality.md`), et
   horloges de session : une feature dont la mediane suit l'heure mesure le
   temps ecoule plus que le marche (INCIDENT_LOG #100 — `vwap_slope_10` varie
   d'un facteur 703 entre le creux et le pic de journee sur ES).

2. **Spearman, en valeur absolue.** Spearman parce que ces donnees sont
   pleines de valeurs extremes et qu'on veut "bougent ensemble" au sens des
   rangs. Valeur absolue parce qu'une correlation de -0.95 est une redondance
   aussi forte qu'une de +0.95.

3. **Decoupage 80/20 STRICTEMENT TEMPOREL.** Jamais aleatoire : deux barres
   de la meme journee sont quasi identiques ; un tirage au sort les met des
   deux cotes et tout valide toujours. Les clusters sont appris sur les 80 %
   les plus anciens et verifies sur les 20 % les plus recents, jamais
   regardes.

4. **ES et NQ separement.** Deux tiers des features different d'un facteur
   superieur a 1.5 entre les deux instruments (`audit_ecart_es_nq.py`). Un
   clustering commun melangerait deux marches.

5. **Le nombre de features est un resultat, pas une cible.** On balaie
   plusieurs seuils et on montre le compromis, au lieu de forcer un chiffre
   decide d'avance.

6. **La perte d'information est mesuree.** Pour chaque feature ecartee au
   profit de son representant, on rapporte leur correlation. Une feature mal
   representee est signalee plutot que silencieusement perdue.

Perimetre — a garder en tete
-----------------------------
Par defaut le script ne retient que les barres de **seance US cash**
(`is_cash_session`), soit environ 381 barres par jour sur 41 jours. Le noyau
obtenu est donc un **noyau cash US** : ni la seance asiatique ni la seance
europeenne ne sont couvertes, et rien ne garantit que les memes redondances
s'y observent. Pour un noyau 24 h, relancer avec `--tout` — mais les profils
horaires et les correlations y seront differents, ce qui est precisement la
raison du decoupage par defaut.

Usage :
    python -X utf8 CORE/research/feature_reduction.py
    python -X utf8 CORE/research/feature_reduction.py --seuil 0.6
    python -X utf8 CORE/research/feature_reduction.py --seuils 0.5,0.6,0.7,0.8
    python -X utf8 CORE/research/feature_reduction.py --tout   # 24 h
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# Colonnes structurelles : jamais candidates.
_TECHNIQUES = {
    "ts", "date", "session", "session_id", "session_date", "session_segment",
    "session_date_trading", "sym", "symbol", "contract", "instrument",
    "mins_et", "is_cash_session", "schema_version", "seq", "bar_index",
    "ts_event", "bars_since_boot",
    # Ajouts 2e revue : horodatages bruts et metadonnees de pipeline. Sans
    # eux, `ts_raw_ms` etait retenu comme REPRESENTANT d'un cluster — un
    # timestamp dans le noyau de decision, qui encode la date et donc tout ce
    # qui s'est passe ce jour-la.
    "ts_raw_ms", "ts_event_ns", "days_since_roll", "_phase3_bars_processed",
}


def est_fuite(nom: str) -> str | None:
    """Motif de fuite, ou None. Ecarte AVANT tout calcul.

    Une feature qui regarde le futur ne doit jamais entrer dans le pool, meme
    pour y etre absorbee par un cluster : elle contaminerait son representant
    par transitivite. `bn_color_up_fwd1` etait fusionnee avec `bn_color_up`,
    ce qui revenait a faire porter au representant une information posterieure
    a la barre.
    """
    bas = nom.lower()
    if "_fwd" in bas or bas.endswith("_fwd") or "_future" in bas or "_next_" in bas:
        return "regarde le futur"
    if nom.startswith("_"):
        return "metadonnee de pipeline"
    if bas.startswith("ts_") or bas.endswith(("_ns", "_ms", "_us")):
        return "horodatage brut"
    return None

FACTEUR_HORLOGE = 2.0

# En dessous de cette correlation interne sur la periode de test, une fusion
# est un accident de la periode d'apprentissage : les membres sont separes
# plutot que resumes par un representant qui ne les represente plus.
STABILITE_MIN = 0.60

# Une binaire qui se declenche moins de 2 % ou plus de 98 % du temps ne
# discrimine plus rien ; entre les deux, elle porte de l'information.
BINAIRE_MIN = 0.02
BINAIRE_MAX = 0.98

# Au-dela de cette derive du profil horaire entre la periode d'apprentissage
# et celle de test, la normalisation n'enleve plus une horloge : elle ajoute
# du bruit de regime. On prefere alors ecarter la feature.
MAX_DERIVE_PROFIL = 0.30

# --- perimetre : sortie de CORE/research/classer_colonnes.py ---------------
# A verifiee par identite | B plausible | N niveau de prix (entree de recalc)
# R evenement rare (phase 2) | C disqualifiee. Seuls A et B sont clusterises.
JOURS_EN_PANNE = {"20260612", "20260619", "20260624", "20260625", "20260630",
                  "20260703", "20260803", "20260805", "20260810", "20260904"}
PROVENANCE = {}
try:
    import pandas as _pd
    _p = _pd.read_csv("DOCS/features_provenance.csv")
    PROVENANCE = dict(zip(_p.colonne, _p.provenance))
except Exception as _e:  # noqa: BLE001
    print("[avert] features_provenance.csv illisible (%s) : perimetre non filtre" % _e)
RETENUES = {c for c, n in PROVENANCE.items() if n in ("A", "B")}

# Features dont la dependance a l'heure EST l'information. Les normaliser
# reviendrait a retirer ce qu'elles disent : l'Initial Balance se construit
# dans la premiere heure, un compteur de minutes depuis une news mesure un
# delai, un flag de session decrit une fenetre horaire.
_EXEMPT_NORMALISATION = (
    "ib_", "news", "session", "mins_", "open_type", "open_drive",
    "hour", "rth", "_830", "_open_cash", "london_open", "ny_open",
)

# Exemptions NOMMEES du test d'horloge : leur dependance a l'heure est la
# definition meme de la feature, pas un defaut. Jamais de relevement du seuil
# global pour faire passer un cas particulier.
_EXEMPT_HORLOGE = {
    "ib_range_ticks": "l'Initial Balance se construit de 9h30 a 10h30 ET puis "
                      "se fige — sa variation horaire est sa definition",
}

# Familles = les ingredients de la methode de Jackson, dans son ordre
# d'importance declare ("au centre de tout ca, c'est le market profile").
FAMILLES: list[tuple[str, tuple[str, ...]]] = [
    ("MARKET PROFILE", ("vpoc", "vah", "val", "profile_", "poc_", "va_",
                        "single_print", "tpo", "naked_poc", "composite",
                        "day_type", "open_type", "bars_in_va", "inside_")),
    ("VOLUME PROFILE", ("hvn", "lvn", "vol_at_price", "vol_node")),
    ("NIVEAUX VEILLE", ("prev_", "pdh", "pdl", "pvwap", "psd", "1d_min", "1d_max")),
    ("VWAP", ("vwap",)),
    ("INITIAL BALANCE", ("ib_",)),
    ("OPTIONS / MENTHORQ", ("mq_", "gex", "gamma", "dex", "0dte", "call_",
                            "put_", "blind", "vol_trigger", "vix")),
    ("ORDER FLOW", ("delta", "cvd", "absorb", "big_", "edge_", "imbalance",
                    "trapped", "aggressor", "buy_vol", "sell_vol", "ask_",
                    "bid_", "cluster", "footprint", "stack", "diag_")),
    ("SWINGS / STRUCTURE", ("swing", "sweep", "bos", "retest", "fvg",
                            "judas", "liquidity", "momentum")),
    ("VOLATILITE / REGIME", ("atr", "rvol", "regime", "volatil", "range_",
                             "sess_range", "pct_in_range")),
    ("BATTLE NAVALE", ("bn_", "long_up", "long_dn", "color_")),
    ("INTERMARKET", ("im_", "correl")),
    ("CONTEXTE ROLLING", ("ctx_",)),
    ("SESSION / TEMPS", ("session", "open_", "hour", "rth", "london", "asia",
                         "us_", "cash_", "ovn", "news")),
    ("BARRE / OHLC", ("bar_", "price", "close", "open", "high", "low",
                      "tick", "wick", "body")),
]


def famille_de(cle: str) -> str:
    c = cle.lower()
    for nom, motifs in FAMILLES:
        if any(m in c for m in motifs):
            return nom
    return "AUTRES"


def charger(symbole: str, jours: int, dossier: str,
            rth_seul: bool = True) -> pd.DataFrame:
    """Charge les JSONL enrichis, en filtrant DES LA LECTURE.

    Le filtrage de seance se fait ligne par ligne plutot qu'apres construction
    du DataFrame : la source complete pese pres de 2 Go et seule la seance US
    (~26 % des barres) est retenue par defaut. Charger puis filtrer ferait
    passer la memoire par un pic inutile de plusieurs gigaoctets.
    """
    lignes = []
    motif = os.path.join(dossier, symbole, "*.jsonl")
    fichiers = [c for c in sorted(glob.glob(motif))
                if os.path.basename(c)[:8] not in JOURS_EN_PANNE]
    for chemin in (fichiers[-jours:] if jours else fichiers):
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                bar = json.loads(ligne)
                if rth_seul and not bar.get("is_cash_session"):
                    continue
                # Filtre unique de CONVENTIONS.md §4 : une ligne degraded a des
                # colonnes derivees vides et des OHLC non fiables.
                if bar.get("data_quality_flag") not in (None, "stable"):
                    continue
                lignes.append(bar)
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    if "ts" in df.columns:
        # Selection mesuree, pas raisonnee : la derniere occurrence est la moins
        # complete (548 champs contre 573 le 04/09) et porte les nulls.
        _ordre = {"stable": 0, "warmup": 1, "degraded": 2}
        _r = (df["data_quality_flag"].map(_ordre).fillna(3)
              if "data_quality_flag" in df.columns else 0)
        df = (df.assign(_r=_r, _n=-df.notna().sum(axis=1))
                .sort_values(["ts", "_r", "_n"], kind="mergesort")
                .drop_duplicates("ts", keep="first")
                .drop(columns=["_r", "_n"]).reset_index(drop=True))
    return injecter_recalcul(df.reset_index(drop=True), symbole)


def injecter_recalcul(df: pd.DataFrame, symbole: str) -> pd.DataFrame:
    """Ajoute les colonnes recalculees par `recalc.py` au pool candidat.

    Sans elles, le noyau n'a aucune distance a la VWAP de la veille ni aucun
    momentum reel : leurs versions livrees sont en C (fausses) et rien ne les
    remplacait. La famille NIVEAUX VEILLE etait amputee de son membre
    principal, alors que trois des dix hypotheses en dependent.

    Elles sont marquees provenance A : recalculees depuis OHLCV, c'est le
    niveau le plus verifie qui soit.

    LIMITE — `charger` filtre la seance cash a la lecture, donc les barres
    d'Asie et de Londres ne sont pas en memoire : `dist_asia_*` et
    `dist_london_*` ne peuvent pas etre recalculees ici. Elles restent hors
    noyau tant que la reduction tourne en `--tout`.
    """
    if df.empty or "close" not in df.columns:
        return df
    from CORE.features import recalc as _rc
    dt = pd.to_datetime(_rc.horodatage(df), unit="ms", utc=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    jour = pd.Series(dt.dt.date, index=df.index)
    ajouts = {}

    # VWAP de seance cash et ses bandes, puis la valeur de la veille
    if {"high", "low", "total_vol"} <= set(df.columns):
        vw = _rc.vwap_cumule(df, jour)
        ajouts["dist_vwap_rth_r"] = _rc.dist_ticks(vw, close, symbole)
        b = _rc.vwap_bandes(df, jour, vw)
        ajouts["dist_vwap_rth_sd1u_r"] = _rc.dist_ticks(b["sup"], close, symbole)
        ajouts["dist_vwap_rth_sd1d_r"] = _rc.dist_ticks(b["inf"], close, symbole)
        veille = vw.groupby(jour).last().shift(1)
        ajouts["dist_prev_vwap_rth_r"] = _rc.dist_ticks(
            jour.map(veille), close, symbole)
        ext = _rc.extremes_veille(df, jour)
        ajouts["dist_pdh_rth_r"] = _rc.dist_ticks(ext["pdh"], close, symbole)
        ajouts["dist_pdl_rth_r"] = _rc.dist_ticks(ext["pdl"], close, symbole)

    # Momentum aux vrais decalages, remis a zero a chaque seance pour ne pas
    # enjamber la nuit.
    for n in (3, 5, 10):
        ajouts["momentum_%db_r" % n] = close.groupby(jour).transform(
            lambda s, k=n: s - s.shift(k))

    for nom, serie in ajouts.items():
        df[nom] = pd.to_numeric(serie, errors="coerce")
        PROVENANCE[nom] = "A"
        RETENUES.add(nom)
    return df


def facteur_horloge(serie: pd.Series, heures: pd.Series) -> float | None:
    """Rapport pic/creux des medianes horaires, calcule sur la MAGNITUDE.

    CORRECTION 04/09 (bug signale par la revue croisee Fable) : la premiere
    version calculait le ratio sur les medianes brutes en ne conservant que
    les positives. Sur une feature SIGNEE dont les medianes horaires oscillent
    autour de zero, cela produisait un ratio enorme par pur artefact numerique
    — une division par une valeur proche de zero, pas une horloge.

    Mesure du degat : `dist_vwap_d` sur NQ avait des medianes horaires
    [0.39, 58.1, -58.9, -95.1, 6.0, 24.4, -0.9] ; en ne gardant que les
    positives, 58.1 / 0.39 = x150. La feature etait ecartee alors qu'elle est
    saine. 48 features ES et 60 NQ etaient dans ce cas.

    La grandeur qui trahit reellement une horloge est l'AMPLITUDE : un
    compteur ou un cumul de session voit sa magnitude croitre avec l'heure.
    On travaille donc sur |valeur|, ce qui traite identiquement les features
    signees et les magnitudes.

    Garde supplementaire : si la plus petite mediane horaire est negligeable
    devant la plus grande (moins de 1 %), le rapport n'est pas interpretable
    — on renvoie None plutot qu'un chiffre qui declencherait un rejet.
    """
    medianes = []
    for _, groupe in serie.abs().groupby(heures):
        vals = groupe.dropna()
        if len(vals) < 20:
            continue
        medianes.append(float(vals.median()))
    medianes = [m for m in medianes if np.isfinite(m)]
    if len(medianes) < 3:
        return None
    haut, bas = max(medianes), min(medianes)
    if haut <= 0:
        return None
    if bas <= 0.01 * haut:
        return None  # rapport domine par le bruit, pas par l'heure
    return haut / bas


def est_magnitude(serie: pd.Series) -> bool:
    """Une magnitude ne prend jamais de valeur negative."""
    m = serie.min()
    return bool(np.isfinite(m) and m >= 0)


def profil_horaire(serie: pd.Series, heures: pd.Series, magnitude: bool) -> dict:
    """Profil de reference par heure, calcule sur LES BARRES FOURNIES.

    Garde-fou n°1 de la revue : ce profil doit etre construit sur la seule
    periode d'apprentissage, puis applique fige a la periode de test. Le
    calculer sur l'ensemble ferait normaliser chaque barre de test par un
    profil qui la contient — une fuite discrete qui gonflerait artificiellement
    la stabilite des clusters.

    Garde-fou n°2 : magnitudes et grandeurs signees ne se normalisent pas de
    la meme facon. Un volume ou un comptage se rapporte a sa mediane horaire
    (ratio). Un delta ou une distance passe par zero : un ratio y exploserait,
    on utilise un z-score robuste (ecart a la mediane, divise par l'ecart
    absolu median) qui reste defini de part et d'autre de zero.
    """
    med = serie.groupby(heures).median()
    if magnitude:
        return {"type": "ratio", "med": med}
    ecarts = (serie - heures.map(med)).abs()
    return {"type": "zscore", "med": med, "mad": ecarts.groupby(heures).median()}


def appliquer_profil(serie: pd.Series, heures: pd.Series, profil: dict) -> pd.Series:
    med_h = heures.map(profil["med"])
    if profil["type"] == "ratio":
        return serie / med_h.replace(0.0, np.nan)
    mad_h = heures.map(profil["mad"]).replace(0.0, np.nan)
    return (serie - med_h) / mad_h


def derive_profil(profil_train: dict, serie_test: pd.Series,
                  heures_test: pd.Series, magnitude: bool) -> float | None:
    """Ecart relatif median entre le profil appris et celui de la periode test.

    Garde-fou n°4 de la revue : si la reference horaire d'une heure donnee a
    bouge de plus de MAX_DERIVE_PROFIL entre les deux periodes, le profil
    n'est pas une propriete stable de la seance mais l'empreinte d'un regime.
    Normaliser par lui reviendrait a injecter ce regime dans la feature.
    """
    p_test = profil_horaire(serie_test, heures_test, magnitude)
    a, b = profil_train["med"], p_test["med"]
    communes = a.index.intersection(b.index)
    if len(communes) < 3:
        return None
    ref = a[communes].abs().replace(0.0, np.nan)
    ecart = (b[communes] - a[communes]).abs() / ref
    ecart = ecart[np.isfinite(ecart)]
    return float(ecart.median()) if len(ecart) else None


def nettoyer(df: pd.DataFrame, rth_seul: bool, part_train: float = 0.8):
    """Ecarte ce qui ne peut apprendre a personne. -> (df_propre, motifs)."""
    if rth_seul and "is_cash_session" in df.columns:
        df = df[df["is_cash_session"] == True].reset_index(drop=True)  # noqa: E712

    heures = (pd.to_datetime(df["ts"], unit="ms", utc=True).dt.hour
              if "ts" in df.columns else None)
    prix_median = float(pd.to_numeric(df["close"], errors="coerce").median())

    # Frontiere train/test, utilisee uniquement pour apprendre les profils
    # horaires : le clustering refera son propre decoupage ensuite.
    coupe = int(len(df) * part_train)
    idx_train = df.index[:coupe]
    idx_test = df.index[coupe:]

    motifs: dict[str, list] = defaultdict(list)
    colonnes = {}
    normalisees: dict[str, str] = {}
    evenements: list[tuple[str, float]] = []

    for c in df.columns:
        if c in _TECHNIQUES:
            continue
        # Perimetre arrete en amont (classer_colonnes.py) : seuls A et B sont
        # clusterises. N = niveau de prix, entree de recalc.py ; R = evenement
        # rare, garde pour la phase 2 ; C = disqualifiee.
        if RETENUES and c not in RETENUES:
            motifs["hors perimetre (%s)" % PROVENANCE.get(c, "?")].append(
                (c, "niveau %s" % PROVENANCE.get(c, "inconnu")))
            continue
        fuite = est_fuite(c)
        if fuite:
            motifs["FUITE ecartee avant calcul"].append((c, fuite))
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() < 0.5 * len(df):
            motifs["vide"].append((c, "%.0f %% de trous" % (100 * s.isna().mean())))
            continue
        nu = s.nunique(dropna=True)
        if nu == 2:
            # CORRECTION 04/09 (revue croisee Fable) : la premiere version
            # ecartait toute colonne a moins de 3 valeurs distinctes, donc
            # TOUS les booleens — 92 features ES et 96 NQ, dont
            # `inside_cur_va` (le prix est-il dans la Value Area, 52 % du
            # temps) qui est un pilier de la lecture Market Profile.
            # Un booleen qui se declenche parfois porte de l'information ;
            # seul celui qui ne varie quasiment jamais n'en porte pas.
            valeurs = sorted(s.dropna().unique())
            taux = float((s == valeurs[-1]).mean())
            if taux > BINAIRE_MAX:
                motifs["binaire quasi-toujours vraie"].append(
                    (c, "se declenche %.1f %% du temps" % (100 * taux)))
                continue
            if taux < BINAIRE_MIN:
                # 2e revue : une binaire rare n'est pas redondante, elle est
                # RARE. Un evenement a 0.5 % peut etre la feature la plus
                # informative du jeu (`delta_divergence`, `ib_is_narrow`).
                # Le clustering de correlation ne sait rien en dire — trop peu
                # d'occurrences pour un rho fiable. On les met de cote au lieu
                # de les jeter : elles relevent d'une analyse d'evenements.
                evenements.append((c, taux))
                motifs["EVENEMENT RARE (a traiter a part, non jete)"].append(
                    (c, "se declenche %.2f %% du temps" % (100 * taux)))
                continue
        elif nu < 3:
            motifs["constante"].append((c, "%d valeur(s) distincte(s)" % nu))
            continue
        if s.std(skipna=True) == 0:
            motifs["constante"].append((c, "variance nulle"))
            continue
        med = s.median()
        if np.isfinite(med) and med > 0 and 0.5 * prix_median <= med <= 2.0 * prix_median:
            motifs["prix absolu"].append((c, "mediane %.1f ~ prix %.1f" % (med, prix_median)))
            continue
        if heures is not None:
            f = facteur_horloge(s, heures)
            if f is not None and f > FACTEUR_HORLOGE:
                bas = c.lower()
                if c in _EXEMPT_HORLOGE or bas.startswith(_EXEMPT_NORMALISATION) \
                        or any(m in bas for m in _EXEMPT_NORMALISATION):
                    # Garde-fou n°3 : l'heure est la definition de la feature.
                    motifs["horloge assumee (l'heure est l'information)"].append(
                        (c, "x%.1f" % f))
                    colonnes[c] = s
                    continue

                mag = est_magnitude(s)
                profil = profil_horaire(s.loc[idx_train], heures.loc[idx_train], mag)
                derive = derive_profil(profil, s.loc[idx_test],
                                       heures.loc[idx_test], mag)
                if derive is None or derive > MAX_DERIVE_PROFIL:
                    # CORRECTION 2e revue — inversion de logique.
                    # Un profil horaire qui derive fortement entre les deux
                    # periodes PROUVE que l'heure ne determine pas la feature :
                    # si elle le faisait, le profil serait stable. Le ratio
                    # pic/creux qui l'avait rendue suspecte etait donc un faux
                    # positif, pas une horloge.
                    # Le garde-fou 4 decide si l'on NORMALISE, jamais si l'on
                    # GARDE. Version precedente : 48 features ES et 61 NQ
                    # ecartees a tort, dont `dist_vwap_d` — la variable du
                    # confidence_score, la seule validee sur trades reels.
                    motifs["suspectee horloge, PROFIL INSTABLE -> gardee brute"].append(
                        (c, "x%.1f, derive train->test %s : l'heure ne la "
                            "determine pas"
                         % (f, "indecidable" if derive is None
                            else "%.0f %%" % (100 * derive))))
                    colonnes[c] = s
                    continue

                norm = appliquer_profil(s, heures, profil)
                norm = norm.replace([np.inf, -np.inf], np.nan)
                if norm.notna().sum() < 0.5 * len(df) or norm.nunique(dropna=True) < 3:
                    motifs["normalisation degeneree"].append((c, "x%.1f" % f))
                    continue
                f2 = facteur_horloge(norm, heures)
                if f2 is not None and f2 > FACTEUR_HORLOGE:
                    motifs["horloge residuelle apres normalisation"].append(
                        (c, "x%.1f -> x%.1f" % (f, f2)))
                    continue

                nom = c + "_hnorm"
                colonnes[nom] = norm
                normalisees[nom] = ("%s — %s par heure (x%.1f -> x%.1f, derive %.0f %%)"
                                    % (c, "ratio a la mediane" if mag
                                       else "z-score robuste",
                                       f, f2 if f2 is not None else 1.0,
                                       100 * derive))
                continue
        colonnes[c] = s

    if normalisees:
        motifs["NORMALISEE par l'heure (recuperee)"] = sorted(normalisees.items())
    return pd.DataFrame(colonnes), dict(motifs), sorted(evenements, key=lambda x: -x[1])


def matrice_rho(df: pd.DataFrame) -> pd.DataFrame:
    return df.corr(method="spearman")


def clusteriser(rho: pd.DataFrame, seuil: float) -> dict[int, list[str]]:
    """Regroupe les colonnes dont |rho| depasse `seuil`."""
    cols = list(rho.columns)
    if len(cols) < 2:
        return {0: cols}
    d = 1.0 - rho.abs().to_numpy()
    d[~np.isfinite(d)] = 1.0
    np.fill_diagonal(d, 0.0)
    d = (d + d.T) / 2.0
    liens = hierarchy.linkage(squareform(d, checks=False), method="average")
    etiquettes = hierarchy.fcluster(liens, t=1.0 - seuil, criterion="distance")
    groupes = defaultdict(list)
    for col, lab in zip(cols, etiquettes):
        groupes[int(lab)].append(col)
    return dict(groupes)


def choisir_representant(membres, rho, df) -> str:
    """Le membre le plus CENTRAL — celui qui resume le mieux son groupe.

    Central = correlation absolue moyenne la plus forte avec les autres
    membres. A centralite comparable (2 % pres), on prefere le mieux rempli,
    puis le nom le plus court : un nom court designe generalement la grandeur
    de base plutot qu'une variante derivee (`dist_vwap_d` plutot que
    `dist_vwap_d_sd1u_atr`).

    CONTRAINTE — un representant CONTINU est obligatoire des que le cluster
    contient au moins une feature continue. Un booleen ne peut prendre que
    deux valeurs : elu porte-drapeau d'un groupe de grandeurs continues, il
    en resume la direction mais en perd toute l'amplitude. Le bot lirait
    "au-dessus / en-dessous" la ou le cluster disait "de combien".
    Un cluster entierement binaire garde evidemment un representant binaire.
    """
    if len(membres) == 1:
        return membres[0]

    continues = [m for m in membres if df[m].nunique(dropna=True) > 2]
    eligibles = continues if continues else list(membres)

    scores = []
    for m in eligibles:
        autres = [x for x in membres if x != m]
        scores.append((m,
                       float(rho.loc[m, autres].abs().mean()),
                       float(df[m].notna().mean())))
    meilleure = max(s[1] for s in scores)
    # PROVENANCE — une colonne verifiee par identite (niveau A) est preferee a
    # une colonne seulement plausible (B), mais SEULEMENT parmi les candidats
    # a moins de 10 % de la meilleure centralite : un A a 0,60 ne resume pas
    # un cluster dont le B central est a 0,92.
    proches = [s for s in scores if s[1] >= meilleure * 0.90]
    niveau_a = [s for s in proches if PROVENANCE.get(s[0]) == "A"]
    if niveau_a:
        meilleure = max(s[1] for s in niveau_a)
        finalistes = [s for s in niveau_a if s[1] >= meilleure - 0.02]
    else:
        finalistes = [s for s in scores if s[1] >= meilleure - 0.02]
    finalistes.sort(key=lambda s: (-s[2], len(s[0])))
    return finalistes[0][0]


def stabilite_cluster(membres, df_test) -> float:
    """Correlation interne moyenne sur la periode jamais regardee."""
    presents = [m for m in membres if m in df_test.columns]
    if len(presents) < 2:
        return float("nan")
    sous = df_test[presents]
    if sous.notna().sum().min() < 50:
        return float("nan")
    r = sous.corr(method="spearman").abs().to_numpy()
    n = len(presents)
    hors = r[~np.eye(n, dtype=bool)]
    hors = hors[np.isfinite(hors)]
    return float(hors.mean()) if len(hors) else float("nan")


def analyser_symbole(sym, args):
    brut = charger(sym, args.jours, args.data, rth_seul=not args.tout)
    if brut.empty:
        return None

    propre, motifs, evenements = nettoyer(brut, rth_seul=not args.tout,
                                          part_train=args.part_train)
    coupe = int(len(propre) * args.part_train)
    train, test = propre.iloc[:coupe], propre.iloc[coupe:]
    rho = matrice_rho(train)

    # --- Balayage de seuils : le nombre de features est un RESULTAT ---
    balayage = []
    for s in args.seuils:
        g = clusteriser(rho, s)
        balayage.append((s, len(g), sum(1 for m in g.values() if len(m) > 1)))

    # --- Clustering au seuil retenu ---
    groupes = clusteriser(rho, args.seuil)

    # 2e revue : eclater les clusters dont la correlation interne s'effondre
    # sur la periode de test. Une fusion qui ne se reforme pas hors echantillon
    # n'est pas une redondance, c'est une coincidence — garder un seul
    # representant reviendrait a jeter les autres membres sans raison.
    eclates = []
    suivant = max(groupes) + 1 if groupes else 0
    for cid in list(groupes):
        membres = groupes[cid]
        if len(membres) < 2:
            continue
        st = stabilite_cluster(membres, test)
        if st == st and st < STABILITE_MIN:
            eclates.append((cid, [m for m in membres], st))
            del groupes[cid]
            for m in membres:
                groupes[suivant] = [m]
                suivant += 1
    representants, details = {}, {}
    for cid, membres in groupes.items():
        rep = choisir_representant(membres, rho, train)
        representants[cid] = rep
        # Perte d'information : correlation de chaque ecarte avec son representant
        perte = []
        for m in membres:
            if m == rep:
                continue
            r = rho.loc[m, rep]
            perte.append((m, float(abs(r)) if np.isfinite(r) else 0.0))
        details[cid] = {
            "representant": rep,
            "membres": membres,
            "famille": famille_de(rep),
            "stabilite_test": stabilite_cluster(membres, test),
            "remplaces": sorted(perte, key=lambda x: x[1]),
        }

    return {
        "symbole": sym,
        "evenements": evenements,
        "clusters_eclates": [{"membres": m, "stabilite_test": st}
                             for _, m, st in eclates],
        "n_depart": len([c for c in brut.columns if c not in _TECHNIQUES]),
        "n_propre": propre.shape[1],
        "n_barres": len(propre),
        "n_train": len(train),
        "n_test": len(test),
        "motifs": motifs,
        "balayage": balayage,
        "groupes": groupes,
        "details": details,
        "retenues": sorted(representants.values()),
    }


def aligner_representants(resultats: dict, recouvrement_min: float = 0.5) -> list:
    """Impose un representant commun aux clusters partages entre instruments.

    2e revue : le meme cluster pouvait recevoir un representant different sur
    chaque instrument — `range_pos` sur ES, `vwap_d_side` sur NQ pour un
    groupe aux membres largement identiques. Le croisement ES/NQ comptait
    alors ces features comme "propres a un symbole" alors qu'elles designent
    le meme groupe, ce qui sous-estime mecaniquement le socle commun.

    Deux clusters sont juges identiques quand leur intersection couvre au
    moins `recouvrement_min` du plus petit des deux. Le representant retenu
    est celui qui appartient aux deux clusters et qui etait deja representant
    d'au moins un des deux ; a defaut, le membre commun le plus court.
    """
    if len(resultats) != 2:
        return []
    a, b = list(resultats)
    da, db = resultats[a]["details"], resultats[b]["details"]
    alignements = []

    for cid_a, det_a in da.items():
        ens_a = set(det_a["membres"])
        meilleur, score = None, 0.0
        for cid_b, det_b in db.items():
            ens_b = set(det_b["membres"])
            inter = ens_a & ens_b
            if not inter:
                continue
            r = len(inter) / min(len(ens_a), len(ens_b))
            if r > score:
                meilleur, score = cid_b, r
        if meilleur is None or score < recouvrement_min:
            continue
        det_b = db[meilleur]
        if det_a["representant"] == det_b["representant"]:
            continue
        commun = set(det_a["membres"]) & set(det_b["membres"])
        if not commun:
            continue
        # Preferer un representant deja choisi de part ou d'autre
        candidats = [x for x in (det_a["representant"], det_b["representant"])
                     if x in commun] or sorted(commun, key=len)
        choisi = candidats[0]
        alignements.append({
            "recouvrement": score,
            "avant": {a: det_a["representant"], b: det_b["representant"]},
            "apres": choisi,
            "membres_communs": sorted(commun),
        })
        det_a["representant"] = choisi
        det_b["representant"] = choisi

    for sym, r in resultats.items():
        r["retenues"] = sorted({d["representant"] for d in r["details"].values()})
    return alignements


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--symbols", default="ES,NQ")
    ap.add_argument("--jours", type=int, default=0,
                    help="0 = tous les jours restants apres exclusion des "
                         "pannes ; 49 en prenait 49 sur 51, silencieusement")
    ap.add_argument("--seuil", type=float, default=0.7)
    ap.add_argument("--seuils", default="0.5,0.6,0.7,0.8")
    ap.add_argument("--part-train", type=float, default=0.8)
    ap.add_argument("--seuil-perte", type=float, default=0.5,
                    help="en dessous de cette correlation avec son representant, "
                         "une feature ecartee est signalee comme mal representee")
    ap.add_argument("--tout", action="store_true")
    ap.add_argument("--sortie", default="DOCS/FEATURE_REDUCTION.md")
    ap.add_argument("--json", default="DATA/feature_reduction.json")
    args = ap.parse_args()
    args.seuils = [float(x) for x in args.seuils.split(",")]

    resultats = {}
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        r = analyser_symbole(sym, args)
        if r is None:
            print("[%s] aucune donnee" % sym)
            continue
        resultats[sym] = r

        print("\n" + "=" * 78)
        print("%s — %d colonnes au depart, %d apres nettoyage, %d barres "
              "(%d train / %d test)"
              % (sym, r["n_depart"], r["n_propre"], r["n_barres"],
                 r["n_train"], r["n_test"]))
        print("=" * 78)

        print("\n  1. NETTOYAGE — ce qui ne peut rien apprendre a personne")
        for motif, items in sorted(r["motifs"].items(), key=lambda x: -len(x[1])):
            print("     %-22s %4d" % (motif, len(items)))
            for nom, raison in items[:2]:
                print("        %-34s %s" % (nom[:34], raison))
            if len(items) > 2:
                print("        ... et %d autres" % (len(items) - 2))

        print("\n  2. BALAYAGE DE SEUILS — le nombre est un resultat, pas une cible")
        print("     %-10s %10s %14s" % ("seuil", "clusters", "regroupements"))
        for s, n, multi in r["balayage"]:
            marque = "   <== retenu" if abs(s - args.seuil) < 1e-9 else ""
            print("     %-10.2f %10d %14d%s" % (s, n, multi, marque))

        multi = {c: d for c, d in r["details"].items() if len(d["membres"]) > 1}
        stables = [c for c, d in multi.items()
                   if d["stabilite_test"] == d["stabilite_test"]
                   and d["stabilite_test"] >= args.seuil]
        print("\n  3. VALIDATION TEMPORELLE (20 %% jamais regardes)")
        print("     %d clusters, dont %d regroupent plusieurs features"
              % (len(r["groupes"]), len(multi)))
        print("     clusters qui se reforment sur la periode de test : %d / %d"
              % (len(stables), len(multi)))

        mal_repr = [(c, m, v) for c, d in r["details"].items()
                    for m, v in d["remplaces"] if v < args.seuil_perte]
        print("\n  4. PERTE D'INFORMATION")
        if mal_repr:
            print("     %d features ecartees sont mal resumees par leur "
                  "representant (rho < %.2f) :" % (len(mal_repr), args.seuil_perte))
            for cid, m, v in sorted(mal_repr, key=lambda x: x[2])[:8]:
                print("        %-32s rho=%.2f avec %s"
                      % (m[:32], v, r["details"][cid]["representant"][:24]))
        else:
            print("     Perte bornee a %.2f : aucune feature ecartee n'est "
                  "moins correlee que cela a son representant." % args.seuil_perte)
            print("     (la liaison average tolere qu'un membre soit a %.2f du "
                  "representant tant que la moyenne du cluster tient — ce "
                  "n'est donc pas 'aucune perte')" % args.seuil_perte)

        if r["clusters_eclates"]:
            print("\n  4bis. CLUSTERS ECLATES (fusion non reproduite hors echantillon)")
            for e in sorted(r["clusters_eclates"], key=lambda x: x["stabilite_test"])[:6]:
                print("        rho_test=%.2f  %s"
                      % (e["stabilite_test"], ", ".join(e["membres"][:4])))
            print("        -> leurs membres restent separes plutot que resumes")

        if r["evenements"]:
            print("\n  4ter. EVENEMENTS RARES mis de cote (%d) — non jetes"
                  % len(r["evenements"]))
            for nom, taux in r["evenements"][:6]:
                print("        %-34s %.2f %% des barres" % (nom[:34], 100 * taux))
            print("        -> trop rares pour un rho fiable ; relevent d'une")
            print("           analyse d'evenements, pas d'un clustering")

        print("\n  5. NOYAU RETENU — %d features, par famille" % len(r["retenues"]))
        par_fam = defaultdict(list)
        for cid, d in r["details"].items():
            par_fam[d["famille"]].append((d["representant"], len(d["membres"])))
        for nom, _ in FAMILLES + [("AUTRES", ())]:
            if nom not in par_fam:
                continue
            items = sorted(par_fam[nom], key=lambda x: -x[1])
            total_couvert = sum(n for _, n in items)
            print("     %-22s %2d features  (couvrent %d colonnes)"
                  % (nom, len(items), total_couvert))
            for rep, n in items[:4]:
                suffixe = "  (+%d)" % (n - 1) if n > 1 else ""
                print("        %s%s" % (rep, suffixe))
            if len(items) > 4:
                print("        ... et %d autres" % (len(items) - 4))

    alignements = aligner_representants(resultats)
    if alignements:
        print("\n" + "=" * 78)
        print("ALIGNEMENT DES REPRESENTANTS ENTRE INSTRUMENTS")
        print("=" * 78)
        print("  %d clusters partages recevaient un representant different"
              % len(alignements))
        for al in alignements[:10]:
            avant = " / ".join("%s=%s" % (k, v) for k, v in al["avant"].items())
            print("     %-46s -> %s  (recouvrement %.0f %%)"
                  % (avant[:46], al["apres"], 100 * al["recouvrement"]))
        if len(alignements) > 10:
            print("     ... et %d autres" % (len(alignements) - 10))

    # --- Croisement ES / NQ ---
    if len(resultats) == 2:
        a, b = list(resultats)
        ra, rb = set(resultats[a]["retenues"]), set(resultats[b]["retenues"])
        communes = sorted(ra & rb)
        print("\n" + "=" * 78)
        print("CROISEMENT %s / %s" % (a, b))
        print("=" * 78)
        print("  communes aux deux instruments : %d" % len(communes))
        print("  propres a %s : %d    propres a %s : %d"
              % (a, len(ra - rb), b, len(rb - ra)))
        print("\n  Les communes sont le socle : elles decrivent le marche, pas")
        print("  l'instrument. Les propres a un symbole sont a traiter separement.")
        for c in communes[:20]:
            print("     %s" % c)
        if len(communes) > 20:
            print("     ... et %d autres" % (len(communes) - 20))

    # ------------------------------------------------------------- rapport
    rap = ["# Reduction de features — le noyau non redondant\n\n",
           "Genere par `CORE/research/feature_reduction.py`.\n\n",
           "**Ce que ce document repond** : quelles features apportent une "
           "information que les autres n'apportent pas deja.\n\n",
           "**Ce qu'il ne dit PAS** : lesquelles sont rentables. Cette "
           "question demande une cible, un walk-forward et un DSR — elle est "
           "traitee ailleurs. La selection ci-dessous porte sur la "
           "*redondance*, jamais sur la performance : c'est ce qui la protege "
           "du data mining.\n\n",
           "Methode : nettoyage (vides, constantes, prix absolus, horloges de "
           "session), distance `1 - |rho de Spearman|`, clustering "
           "hierarchique average coupe a **%.2f**, un representant central par "
           "cluster. Validation par decoupage **temporel** %.0f/%.0f — les "
           "clusters sont appris sur les barres les plus anciennes et "
           "verifies sur les plus recentes, jamais regardees.\n"
           % (args.seuil, 100 * args.part_train, 100 * (1 - args.part_train))]

    for sym, r in resultats.items():
        rap.append("\n## %s\n\n" % sym)
        rap.append("%d colonnes au depart, %d apres nettoyage, "
                   "**%d features retenues** (%d barres, %d train / %d test).\n\n"
                   % (r["n_depart"], r["n_propre"], len(r["retenues"]),
                      r["n_barres"], r["n_train"], r["n_test"]))

        rap.append("### Balayage de seuils\n\n")
        rap.append("| seuil de correlation | clusters | regroupements |\n|---|---|---|\n")
        for s, n, m in r["balayage"]:
            rap.append("| %.2f%s | %d | %d |\n"
                       % (s, " **(retenu)**" if abs(s - args.seuil) < 1e-9 else "", n, m))

        rap.append("\n### Ecartees au nettoyage\n\n")
        rap.append("| motif | nombre | exemples |\n|---|---|---|\n")
        for motif, items in sorted(r["motifs"].items(), key=lambda x: -len(x[1])):
            ex = ", ".join("`%s` (%s)" % (n, ra) for n, ra in items[:3])
            rap.append("| %s | %d | %s |\n" % (motif, len(items), ex))

        rap.append("\n### Noyau retenu, par famille\n\n")
        par_fam = defaultdict(list)
        for cid, d in r["details"].items():
            par_fam[d["famille"]].append(d)
        for nom, _ in FAMILLES + [("AUTRES", ())]:
            if nom not in par_fam:
                continue
            rap.append("\n**%s**\n\n" % nom)
            for d in sorted(par_fam[nom], key=lambda x: -len(x["membres"])):
                s = d["stabilite_test"]
                if len(d["membres"]) == 1:
                    rap.append("- `%s`\n" % d["representant"])
                else:
                    rap.append("- `%s` — remplace %d features%s : %s\n"
                               % (d["representant"], len(d["membres"]) - 1,
                                  "" if s != s else " (stabilite test %.2f)" % s,
                                  ", ".join("`%s`" % m for m, _ in d["remplaces"])))

    if len(resultats) == 2:
        a, b = list(resultats)
        communes = sorted(set(resultats[a]["retenues"]) & set(resultats[b]["retenues"]))
        rap.append("\n## Croisement %s / %s\n\n" % (a, b))
        rap.append("**%d features communes** aux deux instruments — le socle : "
                   "elles decrivent le marche, pas l'instrument.\n\n" % len(communes))
        for c in communes:
            rap.append("- `%s`\n" % c)

    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as fh:
        fh.writelines(rap)

    js = {sym: {"seuil": args.seuil,
                "n_depart": r["n_depart"], "n_apres_nettoyage": r["n_propre"],
                "features_retenues": r["retenues"],
                "balayage_seuils": [{"seuil": s, "clusters": n, "regroupements": m}
                                    for s, n, m in r["balayage"]],
                "clusters": {str(cid): {"representant": d["representant"],
                                        "famille": d["famille"],
                                        "membres": d["membres"],
                                        "stabilite_test": (None if d["stabilite_test"] != d["stabilite_test"]
                                                           else d["stabilite_test"]),
                                        "remplaces": [{"feature": m, "rho_avec_representant": v}
                                                      for m, v in d["remplaces"]]}
                             for cid, d in r["details"].items()},
                "evenements_rares": [{"feature": f, "taux": tx}
                                     for f, tx in r["evenements"]],
                "clusters_eclates": r["clusters_eclates"],
                "perimetre": "seance US cash uniquement",
                "ecartees": {k: [{"feature": n, "raison": ra} for n, ra in v]
                             for k, v in r["motifs"].items()}}
          for sym, r in resultats.items()}
    if len(resultats) == 2:
        a, b = list(resultats)
        js["communes"] = sorted(set(resultats[a]["retenues"]) & set(resultats[b]["retenues"]))

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(js, fh, indent=2, ensure_ascii=False)

    print("\nRapport   : %s" % args.sortie)
    print("Liste JSON : %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
