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
from CORE.research import hypotheses as HYP  # noqa: E402

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
# Case 2 du tag : cout par trade en DOLLARS, converti en ATR-5m a chaque trade
# avec l'ATR de la barre — "jamais par une constante", dit le texte tague, et
# c'est exactement ce que la premiere version faisait.
#
# Les constantes 0,23 / 0,14 de la case 2 etaient fausses : elles venaient de
# "ATR-5m ~25 pts = 12,50 $" pour MNQ, or 25 POINTS de MNQ valent 50 $ — 12,50 $,
# c'est 25 TICKS. Cinquieme confusion points/ticks de la semaine. Mesure du
# 06/09 sur l'ATR-5m median :
#     MNQ  ATR-5m 20,05 pts = 40,10 $  ->  2,82 $ = 0,070 ATR   (dit : 0,230)
#     MES  ATR-5m  2,83 pts = 14,15 $  ->  4,32 $ = 0,305 ATR   (dit : 0,140)
# Le cout etait surestime 3,3x sur NQ et sous-estime 2,2x sur ES.
#
# Consequence structurelle, et c'est la vraie decouverte : sur MES un
# aller-retour coute 30 % de l'ATR-5m — 20 % du TP, 30 % du SL. Sur MNQ, 7 %.
# Le micro ES en intraday 5 min ne peut pas gagner : ce n'est pas une hypothese,
# c'est de l'arithmetique.
COUT_DOLLARS = {"NQ": 2.82, "ES": 4.32}      # commissions Tradeify + 1 tick/cote
VAL_POINT = {"NQ": 2.00, "ES": 5.00}         # micros : MNQ 0,50 $/tick, MES 1,25 $/tick


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
    # Ordre unique de CONVENTIONS §4 : `stable` d'abord, puis la ligne la plus
    # COMPLETE, puis la premiere. Ni `keep="first"` ni `keep="last"` : la mesure
    # du 06/09 sur 524 minutes dupliquees montre qu'aucune position ne domine
    # (ES 21,8 / 18,4 %, NQ 28,9 / 29,3 %). C'est la completude qui departage.
    df = df.dropna(subset=["ts"]).sort_values("ts")
    df = recalc.dedoublonner_par_minute(df, cle_ts="ts")
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[recalc.est_cash(df["dt"])].reset_index(drop=True)


# Colonnes lues par les six, classees par mode d'agregation (mission §2 :
# "flux = somme, etats = dernier, extremes = max/min, ratios recalcules").
FLUX = ["total_vol", "delta_bar", "buy_vol", "sell_vol"]
ETATS = ["dist_cur_vah", "dist_cur_val", "inside_cur_va",
         "dist_prev_vah", "dist_prev_val", "prev_vah_lvl", "prev_val_lvl",
         "dist_ib_high", "dist_ib_low", "ib_range_atr", "ib_broken_up",
         "ib_broken_dn", "dist_ovn_high", "dist_ovn_low", "dist_pdh", "dist_pdl",
         "dist_mq_call", "dist_mq_put", "open_within_prev_va",
         "open_outside_prev_range", "finish_delta_pct", "delta_pct", "atr_14m",
         # cibles de la sortie naturelle (mission §7) — sans elles, la
         # mesure rend 0 %% partout, ce qui se lit comme un resultat.
         "dist_cur_vpoc", "dist_cur_vwap_vp", "ib_range_ticks", "atr",
         # les seize setups portes d edge_discovery (mode ombre)
         "inside_prev_va", "dist_prev_vah", "cvd_day_dir",
         "dist_gex_nearest_up", "dist_gex_nearest_dn", "vwap_slope_10",
         "dist_vwap_d"]
DRAPEAUX = ["sweep_high_this_bar", "sweep_low_this_bar"]   # un evenement dans
#            la fenetre de 5 min suffit : max, jamais "dernier"


def colonnes_utiles():
    """Colonnes a charger : le strict necessaire aux six, plus le socle."""
    return tuple(dict.fromkeys(
        ["ts", "open", "high", "low", "close", "data_quality_flag"]
        + FLUX + ETATS + DRAPEAUX))


def agreger_5min(df, minutes=None):
    """Barres 5 min alignees sur 9h30 ET.

    Flux sommes, extremes max/min, etats pris a la DERNIERE barre de la fenetre,
    drapeaux d'evenement pris au MAX — un sweep survenu a la deuxieme des cinq
    minutes est un sweep de la barre de 5 min ; le prendre "au dernier" le
    perdrait quatre fois sur cinq.

    L'ATR-5m est recalcule ici, sur les barres agregees. Jamais l'ATR 1 min :
    ils ne sont pas dans le meme rapport selon l'instrument, et normaliser par
    le mauvais rend ES et NQ incomparables. Il est en POINTS (calcule sur des
    prix) — la conversion en ticks est le role de `hypotheses.seuil_ticks`.
    """
    d = df.set_index("dt")
    m = int(minutes or MINUTES_BARRE)
    o = d.resample("%dmin" % m, origin="start_day", label="left", closed="left")
    cols = {"open": o["open"].first(), "high": o["high"].max(),
            "low": o["low"].min(), "close": o["close"].last()}
    for c in FLUX:
        if c in d.columns:
            cols[c] = o[c].sum()
    for c in ETATS:
        if c in d.columns:
            cols[c] = o[c].last()
    for c in DRAPEAUX:
        if c in d.columns:
            cols[c] = o[c].max()
    out = pd.DataFrame(cols).dropna(subset=["close"])
    # ts_ms : unite normalisee + invariant de plage. Cf bot_terminal.agreger.
    out["ts"] = recalc.ts_ms(out.index)
    out["jour"] = out.index.date
    tr = pd.concat([out["high"] - out["low"],
                    (out["high"] - out["close"].shift()).abs(),
                    (out["low"] - out["close"].shift()).abs()], axis=1).max(axis=1)
    out["atr_barre"] = tr.rolling(14, min_periods=7).mean()
    return out.reset_index(drop=True)


def injecter_recalculs(brut_1min, cinq, minutes=None):
    """Ajoute aux barres 5 min les deux colonnes que les six exigent recalculees.

    `minutes` : taille de la barre agregee cible (defaut `MINUTES_BARRE`, comme
    `agreger_5min`). La campagne 15 min passe 15 — sans quoi le merge sur `ts`
    prendrait `rvol_r` et les bandes au TIERS de la fenetre, pas au dernier.

    `cvd_sess_r` (prerequis L4, 07/09) : cumul du delta depuis 17h ET
    (`recalc.cumul_delta` sur cle `session_sess`), pris au dernier de chaque
    fenetre — JAMAIS la colonne livree `cvd_day`, qui repart de zero au
    redemarrage du processus. Si le 1 min ne porte pas `delta_bar`, la
    colonne rend NaN — un trou, jamais un zero invente.

    `rvol_r`  — H8. Le C++ initialise `f.rvol = 1.0f` et 1,0 est une valeur
                valide de la variable : "normal mesure" et "jamais calcule" y
                sont indistinguables (CONVENTIONS §3.1). Recalcule sur les
                barres 1 min, puis pris au dernier de chaque fenetre.
    `dist_vwap_rth_sd2u_r` / `..._sd2d_r` — H2. Bandes a 2 ecarts-types autour
                de la VWAP RTH, en TICKS et signees `niveau - close`, comme
                toutes les `dist_*` du lot.
    `vwap_rth_r` / `dist_vwap_rth_r` — brief OMBRE_C2 §3 (08/09). La VWAP RTH
                elle-meme (points, prise au dernier de chaque fenetre) et sa
                distance en ticks, meme convention signee que les bandes.
    `finish_r`  — position de la cloture dans le range de la BARRE AGREGEE
                (`recalc.finish` sur le frame cible, PAS sur le 1 min — c'est
                l'erreur de `finish_delta_pct`, VALIDATION_MISS 07/09).
    `vwap_slope_r` — pente de `vwap_rth_r` sur 4 barres agregees, en ATR
                (`recalc.pente_vwap`, cle `jour` : jamais de pente entre deux
                sessions ; NaN AU MOINS les 4 premieres barres — un trou).
    `atr_ref` / `atr_veille` / `atr_source` — audit Fable 08/09 (arbitrage
                B) : atr_barre si disponible, sinon la MEDIANE de l'ATR
                agrege de la VEILLE cash (`recalc.atr_veille_15`, chauffe
                multi-jours, sans fuite) — bouche le trou 9h30-11h00 pour
                tout setup NON GELE. `atr_source` dit lequel a servi.
    """
    b = brut_1min.copy()
    b["dt"] = pd.to_datetime(b["ts"], unit="ms", utc=True)

    rv = recalc.rvol(b, b["dt"])
    cle = recalc.session_rth(b["dt"])
    vw = recalc.vwap_cumule(b, cle)
    bandes = recalc.vwap_bandes(b, cle, vw, n_sd=2.0)
    cvd = (recalc.cumul_delta(b, recalc.session_sess(b["dt"]))
           if "delta_bar" in b.columns
           else pd.Series(np.nan, index=b.index))

    aux = pd.DataFrame({
        "dt": b["dt"], "rvol_r": rv, "cvd_sess_r": cvd, "vwap": vw,
        "sd2u": bandes["sup"], "sd2d": bandes["inf"], "c": b["close"],
    }).set_index("dt")
    o = aux.resample("%dmin" % int(minutes or MINUTES_BARRE), origin="start_day",
                     label="left", closed="left").last()
    o = o.dropna(subset=["c"])
    # ts_ms OBLIGATOIRE ici : cette cle sert au merge(on="ts") avec `cinq` —
    # une unite differente ne casse pas, elle rend TOUTES les colonnes _r NaN
    # en silence. L'invariant de ts_ms rend ce mode BRUYANT.
    o["ts"] = recalc.ts_ms(o.index)
    # `niveau - close`, en ticks : meme convention et meme signe que dist_cur_vah
    o["dist_vwap_rth_sd2u_r"] = (o["sd2u"] - o["c"]) / HYP.TICK
    o["dist_vwap_rth_sd2d_r"] = (o["sd2d"] - o["c"]) / HYP.TICK
    o["dist_vwap_rth_r"] = (o["vwap"] - o["c"]) / HYP.TICK
    garde = ["ts", "rvol_r", "cvd_sess_r", "vwap_rth_r",
             "dist_vwap_rth_r", "dist_vwap_rth_sd2u_r", "dist_vwap_rth_sd2d_r"]
    out = cinq.merge(o.rename(columns={"vwap": "vwap_rth_r"})[garde],
                     on="ts", how="left")
    # Sur le frame CIBLE, pas sur le 1 min : finish de la barre agregee et
    # pente de la VWAP en unites d'ATR de barre (NaN si atr_barre absent).
    out["finish_r"] = recalc.finish(out)
    atr_b = (out["atr_barre"] if "atr_barre" in out.columns
             else pd.Series(np.nan, index=out.index))
    out["vwap_slope_r"] = recalc.pente_vwap(out["vwap_rth_r"], atr_b, n=4,
                                            jours=out.get("jour"))
    # atr_ref : le secours de la veille pour le trou 9h30-11h00 (non gele)
    veille = recalc.atr_veille_15(b, b["dt"], minutes=int(minutes or MINUTES_BARRE))
    out["atr_veille"] = (out["jour"].map(veille) if "jour" in out.columns
                         else np.nan)
    out["atr_ref"] = atr_b.fillna(out["atr_veille"])
    out["atr_source"] = np.where(atr_b.notna(), "barre",
                                 np.where(out["atr_ref"].notna(), "veille",
                                          "aucun"))
    return out


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
    """Entree a l'OUVERTURE de t+1. Rend (etiquette, pnl_atr, i_sortie).

    `couts_atr` est ici un COUT EN DOLLARS accompagne de la valeur du point :
    il est converti en multiples d'ATR avec l'ATR de CETTE barre, jamais par une
    constante. Une barre calme paie proportionnellement plus cher qu'une barre
    agitee, et c'est precisement ce qu'une constante efface.
    """
    j = i_signal + 1
    if j >= len(df):
        return None
    atr = df["atr_barre"].iloc[i_signal]
    if not np.isfinite(atr) or atr <= 0:
        return None
    if isinstance(couts_atr, tuple):             # (dollars, $/point)
        dollars, val_pt = couts_atr
        couts_atr = dollars / (atr * val_pt)
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


def sortie_naturelle(df, i_entree, i_sortie, side):
    """La cible naturelle du setup a-t-elle ete atteinte avant la barriere ?

    Mesure d'information, JAMAIS un critere (mission §7). Un setup de retour a
    la valeur a pour cible le VPOC ou la VWAP, a une distance bien inferieure a
    1,5 ATR : la barriere de continuation peut le tuer alors qu'il fait ce qu'on
    lui demande. Si H3 atteint le VPOC dans 60 % des cas, le setup n'est pas
    mort — c'est la barriere qui ne lui correspond pas (constat 0.1).
    """
    for col in ("dist_cur_vpoc", "dist_cur_vwap_vp"):
        if col not in df.columns:
            continue
        d0 = pd.to_numeric(df[col], errors="coerce").iloc[i_entree]
        if not np.isfinite(d0) or d0 == 0:
            continue
        # la cible est franchie quand la distance signee change de signe
        seq = pd.to_numeric(df[col], errors="coerce").iloc[i_entree:i_sortie + 1]
        if (np.sign(seq) != np.sign(d0)).any():
            return col
    return None


def triple_barriere_vpoc(df, i_signal, side, couts_atr):
    """Barriere PAR FAMILLE : la cible est le VPOC, pas +1,5 ATR.

    Un setup de retour a la valeur vise le VPOC ou la VWAP, a une distance bien
    inferieure a 1,5 ATR. Le juger sur une cible de continuation, c'est exiger
    d'un retour a la moyenne qu'il devienne une tendance — constat 0.1, mesure au
    cycle 1 : H3 atteint sa cible naturelle 66,7 % du temps et meurt quand meme.

    Une seule chose change par rapport a `triple_barriere` : le TP.
    SL a -1,0 ATR et expiration a 20 barres sont inchanges, pour que tout ecart
    avec le cycle 1 s'impute a la cible et a rien d'autre.

    A ne pas se raconter : une cible plus proche encaisse moins par trade. Le
    taux de reussite montera mecaniquement ; l'esperance peut ne pas suivre.
    """
    j = i_signal + 1
    if j >= len(df):
        return None
    atr = df["atr_barre"].iloc[i_signal]
    if not np.isfinite(atr) or atr <= 0:
        return None
    if "dist_cur_vpoc" not in df.columns:
        return None
    d0 = pd.to_numeric(df["dist_cur_vpoc"], errors="coerce").iloc[i_signal]
    if not np.isfinite(d0) or d0 == 0:
        return None
    if isinstance(couts_atr, tuple):
        dollars, val_pt = couts_atr
        couts_atr = dollars / (atr * val_pt)

    entree = df["open"].iloc[j]
    vpoc = entree + d0 * 0.25                 # dist_cur_vpoc est en TICKS
    sl = entree + side * SL_ATR * atr
    fin = min(j + EXPIRATION, len(df) - 1)
    for k in range(j, fin + 1):
        h, b = df["high"].iloc[k], df["low"].iloc[k]
        if side > 0:
            if b <= sl:
                return -1, SL_ATR - couts_atr, k
            if h >= vpoc:
                return 1, (vpoc - entree) / atr - couts_atr, k
        else:
            if h >= sl:
                return -1, SL_ATR - couts_atr, k
            if b <= vpoc:
                return 1, (entree - vpoc) / atr - couts_atr, k
    pnl = side * (df["close"].iloc[fin] - entree) / atr - couts_atr
    return 0, float(pnl), fin


def evaluer(df, cond, side, couts_atr=0.0, barriere=None):
    """Rend un DataFrame de trades : jour, etiquette, pnl_atr, sortie_naturelle."""
    idx = signaux_par_franchissement(cond, df["jour"])
    trades = []
    libre_a, jour_libre = -1, None
    for i in idx:
        jour_i = df["jour"].iloc[i]
        if jour_i != jour_libre:      # la barriere de la veille ne bloque pas
            libre_a, jour_libre = -1, jour_i
        if i <= libre_a:
            continue
        r = (barriere or triple_barriere)(df, i, side, couts_atr)
        if r is None:
            continue
        etiq, pnl, k = r
        libre_a = k
        trades.append({"jour": jour_i, "etiquette": etiq, "pnl_atr": pnl,
                       "sortie_naturelle": sortie_naturelle(df, i, k, side)})
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


HASH_MISSION = "8bec98eff0860e16a81a4804913ad31ff2f807f6"


def verifier_le_tag():
    """Le runner refuse de tourner si la mission a change depuis le tag.

    Le tag `mission-phase2-v1` fige le TEXTE des hypotheses. Si le fichier a
    bouge depuis, ce qui va tourner n'est plus ce qui a ete pre-enregistre, et
    le resultat ne vaut rien — c'est la seule protection contre la retouche
    d'apres-coup, celle qui transforme une recherche en peche.
    """
    import subprocess
    try:
        h = subprocess.run(["git", "hash-object", "DOCS/MISSION_PHASE2.md"],
                           capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:                      # pas de git : on le dit, on n'invente pas
        print("[tag] verification impossible (%s) — resultat a considerer comme non "
              "pre-enregistre" % e)
        return False
    if h != HASH_MISSION:
        print("[tag] MISSION_PHASE2.md a change depuis le tag mission-phase2-v1.")
        print("      attendu %s" % HASH_MISSION)
        print("      trouve  %s" % h)
        print("      Le runner ne tourne pas : ce qui serait mesure ne serait plus")
        print("      ce qui a ete pre-enregistre. Toute idee nee depuis va dans")
        print("      NEXT_CYCLE.md, pas dans la mission.")
        return False
    return True


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
        "fuyante_LOOKAHEAD": (fwd > 0.5 * df["atr_barre"], 1),
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
        tous = [x for x in par_sym.values() if len(x)]
        naturelles[nom] = pd.concat(tous, ignore_index=True) if tous else None
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


def preparer(sym):
    """Barres 5 min pretes : agregees, recalculs injectes, 40 jours de recherche.

    Rend (df, jours). Les jours 41-57 restent SCELLES : ils ne sont ouverts
    qu'une fois, a la fin, et pour les survivantes seulement.
    """
    brut = charger(sym, cols=colonnes_utiles())
    if brut.empty:
        return pd.DataFrame(), []
    cinq = injecter_recalculs(brut, agreger_5min(brut))
    jours = sorted(cinq["jour"].unique())[:N_JOURS_RECHERCHE]
    return cinq[cinq["jour"].isin(jours)].reset_index(drop=True), jours


def entonnoir_par_etage(df, cond_lieu, cond_totale):
    """N a chaque etage. Sans ces chiffres, « non testable » ne dit pas OU
    l'hypothese perd ses signaux : si c'est le lieu qui est rare, ou la reaction
    qui est trop stricte."""
    lieu = int(len(signaux_par_franchissement(cond_lieu, df["jour"])))
    tot = int(len(signaux_par_franchissement(cond_totale, df["jour"])))
    return lieu, tot


def lecture_unique():
    """Les six sur les 40 jours de recherche. Un seul affichage, a la fin."""
    if not verifier_le_tag():
        return 1
    print("MISSION PHASE 2 — lecture unique des six hypotheses.")
    print("Tag mission-phase2-v1 verifie. Bonferroni 0,05 / %d.\n" % N_HYPOTHESES)

    dfs, jours_lot = {}, {}
    for sym in ("NQ", "ES"):
        d, j = preparer(sym)
        if d.empty:
            print("[%s] aucune donnee" % sym)
            return 1
        dfs[sym], jours_lot[sym] = d, j
        print("  %s : %d barres 5 min, %d jours" % (sym, len(d), len(j)))
    print()

    lignes, naturelles = [], {}
    for nom, fn in HYP.LES_SIX.items():
        par_sym, etages = {}, {}
        for sym, d in dfs.items():
            trades = []
            for cote, (cond, side) in fn(d).items():
                t_ = evaluer(d, cond, side,
                             couts_atr=(COUT_DOLLARS[sym], VAL_POINT[sym]))
                if len(t_):
                    trades.append(t_)
            par_sym[sym] = (pd.concat(trades, ignore_index=True)
                            if trades else pd.DataFrame(columns=["jour", "etiquette", "pnl_atr"]))
            L, R = HYP.lieux(d), HYP.regimes(d)
            n = lambda c: len(signaux_par_franchissement(c, d["jour"]))
            etages[sym] = (n(L[nom]), n(L[nom] & R[nom]),
                           sum(n(c) for c, _ in fn(d).values()))
        tous = [x for x in par_sym.values() if len(x)]
        naturelles[nom] = pd.concat(tous, ignore_index=True) if tous else None
        v, pourquoi = verdict(par_sym, jours_lot)
        lignes.append((nom, v, pourquoi, {s: len(x) for s, x in par_sym.items()},
                       {s: (round(float(x["pnl_atr"].mean()), 3) if len(x) else None)
                        for s, x in par_sym.items()}, etages))

    print("%-5s %-14s %-24s %-17s %s"
          % ("hyp", "verdict", "ENTONNOIR ES  lieu>reg>reac", "esperance ATR", "pourquoi"))
    print("-" * 118)
    for nom, v, p, n, e, et in lignes:
        a = et.get("ES", (0, 0, 0))
        print("%-5s %-14s %-24s %-17s %s"
              % (nom, v, "%d > %d > %d  (N=%d)" % (a[0], a[1], a[2], n.get("ES", 0)),
                 "%s / %s" % (e.get("NQ"), e.get("ES")), p[:40]))
    print()
    print("Sorties naturelles atteintes avant la barriere (mesure, jamais un critere) :")
    for nom, _, _, _, _, _ in lignes:
        tr = naturelles.get(nom)
        if tr is not None and len(tr):
            part = 100 * tr["sortie_naturelle"].notna().mean()
            print("  %-4s %5.1f %% des trades (N=%d)" % (nom, part, len(tr)))

    print()
    for nom, v, _, _, _, _ in lignes:
        if v == "NON TESTABLE" and nom in HYP.SOUS_DIMENSIONNEES:
            print("%s : « NON TESTABLE » signifie TROP RARE POUR CE LOT, pas « le setup est"
                  % nom)
            print("     mauvais ». C'etait annonce avant de tourner. Sur 40 jours, une"
                  " hypothese")
            print("     a un signal par jour plafonne a 39 — sous le minimum de 40, quelle"
                  " que")
            print("     soit sa qualite. Le mode ombre est sa seule voie.")
    print("\nJours 41-57 : SCELLES. Ouverts une seule fois, pour les survivantes"
          " uniquement.")
    return 0


def lecture_cycle2():
    """Cycle 2. Pre-enregistre dans DOCS/MISSION_CYCLE2.md, ecrit avant de lancer."""
    print("MISSION CYCLE 2 — second regard declare sur les memes 40 jours.")
    print("Bonferroni 0,05 / 4. Trois hypotheses sur quatre sont ANNONCEES non")
    print("testables avant de tourner ; seule H3-VPOC peut conclure.\n")
    dfs, jours_lot = {}, {}
    for sym in ("NQ", "ES"):
        d, j = preparer(sym)
        if d.empty:
            print("[%s] aucune donnee" % sym)
            return 1
        dfs[sym], jours_lot[sym] = d, j
        print("  %s : %d barres 5 min, %d jours" % (sym, len(d), len(j)))
    print()

    lignes = []
    for nom, fn in HYP.LES_QUATRE.items():
        bar = triple_barriere_vpoc if nom in HYP.CIBLE_VPOC else None
        par_sym = {}
        for sym, d in dfs.items():
            trades = []
            for cote, (cond, side) in fn(d).items():
                t_ = evaluer(d, cond, side,
                             couts_atr=(COUT_DOLLARS[sym], VAL_POINT[sym]),
                             barriere=bar)
                if len(t_):
                    trades.append(t_)
            par_sym[sym] = (pd.concat(trades, ignore_index=True) if trades
                            else pd.DataFrame(columns=["jour", "etiquette", "pnl_atr"]))
        v, pourquoi = verdict(par_sym, jours_lot)
        lignes.append((nom, v, pourquoi, {s: len(x) for s, x in par_sym.items()},
                       {s: (round(float(x["pnl_atr"].mean()), 3) if len(x) else None)
                        for s, x in par_sym.items()},
                       {s: (round(float((x["etiquette"] == 1).mean()), 3) if len(x) else None)
                        for s, x in par_sym.items()}))

    print("%-9s %-14s %-11s %-17s %-13s %s"
          % ("hyp", "verdict", "N (NQ/ES)", "esperance ATR", "taux TP", "pourquoi"))
    print("-" * 118)
    for nom, v, p, n, e, w in lignes:
        print("%-9s %-14s %-11s %-17s %-13s %s"
              % (nom, v, "%d/%d" % (n.get("NQ", 0), n.get("ES", 0)),
                 "%s / %s" % (e.get("NQ"), e.get("ES")),
                 "%s / %s" % (w.get("NQ"), w.get("ES")), p[:38]))

    print()
    for nom, v, _, _, _, _ in lignes:
        if nom in HYP.NON_TESTABLES_ANNONCEES:
            print("  %-9s non testable ANNONCE avant de tourner — dimensionnement mesure"
                  " dans MISSION_CYCLE2 §1." % nom)
    print("\nJours 42-57 : SCELLES, et fermes pour ce cycle aussi.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factices", action="store_true",
                    help="teste le runner sur trois hypotheses factices")
    ap.add_argument("--lecture", action="store_true",
                    help="LECTURE UNIQUE des six. Ne se relance pas sans raison.")
    ap.add_argument("--cycle2", action="store_true",
                    help="Cycle 2 : H3-VPOC + les trois regimes recalcules.")
    a = ap.parse_args()
    if a.factices:
        return tester_factices()
    if a.lecture:
        return lecture_unique()
    if a.cycle2:
        return lecture_cycle2()
    print("Rien a executer. --factices pour valider l'instrument, --lecture pour"
          " la lecture unique des six.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
