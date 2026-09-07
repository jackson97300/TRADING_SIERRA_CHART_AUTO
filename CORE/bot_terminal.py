"""MIA — le scrutateur. Un bot qui regarde le marche et dit ce qu'il fait.

**Il ne trade pas.** Il lit les barres, les passe dans les couches, et affiche
chaque decision avec son motif. Tout ce qu'il refuse est journalise dans
`CORE/entonnoir.py` avec son `devenir_atr` a 20 barres — ce qui a manque aux
trois bots precedents : savoir ce que les rejetes seraient devenus.

    python -X utf8 CORE/bot_terminal.py --replay 20260904
    python -X utf8 CORE/bot_terminal.py --replay 20260904 --sym NQ --vitesse 0
    python -X utf8 CORE/bot_terminal.py --live

CE QU'ON VOIT
-------------
Un bandeau d'etat (prix, ATR, regime gamma, largeur d'IB, biais), puis une ligne
par barre de decision, et pour chaque signal la couche qui l'a arrete :

    14:35  L0  ................  PASSE
    14:35  REG au-dessus HVL / IB etroite
    14:40  L3  H3-VAH short .....  LIEU ok, REACTION non (finish 0.82)
    14:45  L3  H3-VAH short .....  SIGNAL
    14:45  L5  ................  BLOQUE  mur a 0,7 ATR dans le sens du TP

et en pied de page, le compteur de portes : combien chacune a ferme, et sa plage
attendue. Une porte hors de sa plage est inerte ou etrangleuse — c'est la mesure
que Bot 1 v2 n'avait jamais eue, et qui a montre le 06/09 que
`L0_MAX_TRADES_JOUR` fermait 57 % des signaux a lui seul.

CE QU'IL N'EST PAS
------------------
Ni un backtest (il ne rend pas de P&L d'hypothese), ni un executeur (aucun ordre,
aucune connexion DTC). Le P&L des hypotheses se juge en mode ombre, sur des jours
que personne n'a vus — pas dans un terminal qu'on regarde en direct.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from CORE import entonnoir  # noqa: E402
from CORE.features import recalc  # noqa: E402
from CORE.research import hypotheses as H  # noqa: E402
from V3 import chaine  # noqa: E402

# --- couleurs ANSI, desactivees si la sortie n'est pas un terminal -----------
_TTY = sys.stdout.isatty()


def _c(txt, code):
    return "\033[%sm%s\033[0m" % (code, txt) if _TTY else txt


VERT, ROUGE, JAUNE, GRIS, CYAN, GRAS = "32", "31", "33", "90", "36", "1"

PLAGES = {                       # part de rejet attendue, par couche
    "L0": (0.15, 0.30), "REGIME": (0.30, 0.70), "BIAIS": (0.20, 0.50),
    "L4": (0.30, 0.50), "L5": (0.10, 0.25),
}


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def charger_jour(sym, jour, minutes, avec_1min=False, cash_only=True):
    """Barres agregees d'une journee. Rend un DataFrame ou vide.

    `avec_1min` rend `(agregees, minutes)` au lieu des seules agregees.

    `cash_only=False` garde la SESSION ENTIERE : le coureur live evalue les
    portes aussi la nuit (SESSION bloquee, TROU_VIX quand vix_level==0) — la
    detection de signaux L3, elle, reste sur le cash, comme le rejeu.

    LE 1 MIN EST NECESSAIRE, il n'est pas un confort. La fiche de test de F23
    a besoin des deux echelles : l'effort se lit sur la barre agregee (flux
    sommes), mais le VOLUME PIEGE au-dela d'un niveau se compte barre par barre
    d'une minute — combien de contrats se sont echanges de l'autre cote avant
    le regain, et avec quel delta. Une barre de quinze minutes qui traverse un
    niveau et revient ne dit pas combien de monde est reste coince.

    La meche et le finish du test se lisent aussi mieux sur la minute qui a
    touche : c'est le pont vers L4.
    """
    motif = "DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)
    vide = (pd.DataFrame(), pd.DataFrame()) if avec_1min else pd.DataFrame()
    fichiers = sorted(glob.glob(motif))
    if not fichiers:
        return vide
    lignes = []
    for f in fichiers:
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("data_quality_flag") == "stable":
                lignes.append(d)
    if not lignes:
        return vide
    lignes = recalc.dedoublonner_par_minute(lignes)
    df = pd.DataFrame(lignes)
    df["ts"] = recalc.horodatage(df)
    df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    if cash_only:
        df = df[recalc.est_cash(df["dt"])].reset_index(drop=True)
    if df.empty:
        return (df, df) if avec_1min else df
    aggregees = agreger(df, minutes)
    return (aggregees, df) if avec_1min else aggregees


def agreger(df, minutes):
    """Flux sommes, etats au dernier, drapeaux au max, ATR recalcule dessus."""
    d = df.set_index("dt")
    o = d.resample("%dmin" % minutes, origin="start_day", label="left", closed="left")
    cols = {"open": o["open"].first(), "high": o["high"].max(),
            "low": o["low"].min(), "close": o["close"].last()}
    for c in ("total_vol", "delta_bar"):
        if c in d.columns:
            cols[c] = o[c].sum()
    for c in ("dist_cur_vah", "dist_cur_val", "dist_mq_hvl", "ib_range_ticks",
              # Les niveaux du NARRATIF (F23). Ils sont tous dans le JSONL et en
              # provenance A — verifies par identite —, mais quatre d'entre eux
              # ne survivaient pas a l'agregation : le compteur de touches
              # n'aurait eu que deux niveaux sur six a observer, sans que rien
              # ne le signale. Meme defaut que `data_quality_flag`, meme jour.
              "dist_cur_vpoc", "dist_prev_vah", "dist_prev_val",
              "dist_prev_vpoc", "dist_vwap_w", "poc_migration_dir",
              # NIVEAUX_H8 (hypotheses.py) : les DIX doivent survivre a
              # l'agregation. Six manquaient — H8p etait evaluee sur 4 niveaux
              # sur 10, en silence (review campagne.py 08/09, reserve 1).
              "dist_mq_call", "dist_mq_put", "dist_pdh", "dist_pdl",
              "dist_ovn_high", "dist_ovn_low",
              "atr", "atr_14m", "finish_delta_pct", "delta_pct", "rvol",
              "dist_vwap_w", "is_news_60m", "is_session_blocked",
              "gamma_block_long", "rvol_zscore", "vix_level", "vix_regime",
              "inside_prev_va",
              "dist_ib_high", "dist_ib_low", "ib_broken_up", "ib_broken_dn",
              # compteurs de touches — ils EXISTENT (niveau B) et la mission
              # affirmait a tort le contraire. Trois hypotheses ont ete
              # ecrites sans eux pour cette raison.
              "vah_touches_20b", "val_touches_20b",
              "retest_high_count", "retest_low_count"):
        if c in d.columns:
            cols[c] = o[c].last()
    for c in ("sweep_high_this_bar", "sweep_low_this_bar",
              # gros ordres : le MAXIMUM du bloc, pas la derniere minute. Un
              # print de 400 lots a la 3e minute compte encore a la 15e.
              "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
              "n_big_ask_t3", "n_big_ask_t4", "n_big_bid_t3", "n_big_bid_t4"):
        if c in d.columns:
            cols[c] = o[c].max()
    # etats cumulatifs : la derniere valeur du bloc est la bonne
    for c in ("cvd_day", "cvd_session", "dist_big_ask_nearest_up",
              "dist_big_ask_nearest_dn", "dist_big_bid_nearest_up",
              "dist_big_bid_nearest_dn"):
        if c in d.columns:
            cols[c] = o[c].last()
    # Combien de barres d'une minute composent chaque bloc : c'est ce qui dit
    # si la barre agregee est ENTIERE. Une barre partielle en fin de seance
    # fausse l'ATR, donc le SL et le TP — et rien d'autre ne la signale.
    cols["minutes_reelles"] = o["open"].count()
    # La qualite de la PIRE minute du bloc. `charger_jour` ne garde deja que
    # les barres `stable`, donc hors ligne la colonne vaut toujours `stable` —
    # mais si elle disparait a l'agregation, la porte `L0_DATA_INSTABLE` n'a
    # rien a lire et repond « je ne sais pas » sur chaque barre. En live, ou un
    # trou bloque, cela fermerait la seance entiere. Detecte par le test de
    # faux live, jamais par la mesure hors ligne.
    if "data_quality_flag" in d.columns:
        rang = {"stable": 0, "warmup": 1, "degraded": 2}
        pire = d["data_quality_flag"].map(rang).fillna(2)
        cols["data_quality_flag"] = (
            pire.resample("%dmin" % minutes, origin="start_day",
                          label="left", closed="left").max()
            .map({0: "stable", 1: "warmup", 2: "degraded"}))
    out = pd.DataFrame(cols).dropna(subset=["close"])
    out["ts"] = out.index.astype("int64") // 1_000_000
    out["jour"] = out.index.date
    out["barre_complete"] = out["minutes_reelles"] >= minutes
    # `window_version` se deduit du ts : elle qualifie les colonnes DUMPEES en
    # live, pas la date de la barre. Elle ne survivait pas a l'agregation ; la
    # porte L0_DATA_FENETRE ne pouvait donc rien voir hors ligne.
    out["window_version"] = recalc.window_version(out["ts"])
    tr = pd.concat([out["high"] - out["low"],
                    (out["high"] - out["close"].shift()).abs(),
                    (out["low"] - out["close"].shift()).abs()], axis=1).max(axis=1)
    out["atr_barre"] = tr.rolling(14, min_periods=7).mean()

    # --- ce qui NE S'AGREGE PAS, et se RECALCULE -----------------------------
    # `ask_pct` et les meches sont des RAPPORTS. Prendre leur derniere valeur
    # d'une minute pour caracteriser quinze minutes est faux : `ask_pct` a
    # 14h44 ne dit rien du bloc 14h30-14h45. Ils se reconstruisent exactement.
    if "delta_bar" in out.columns and "total_vol" in out.columns:
        # delta = ask - bid et total = ask + bid  =>  ask = (total + delta) / 2
        v = out["total_vol"].replace(0, float("nan"))
        out["ask_pct"] = ((v + out["delta_bar"]) / (2 * v)).clip(0, 1)
        out["bid_pct"] = 1.0 - out["ask_pct"]
    corps_haut = out[["open", "close"]].max(axis=1)
    corps_bas = out[["open", "close"]].min(axis=1)
    amplitude = (out["high"] - out["low"]).replace(0, float("nan"))
    out["bar_upper_wick_pct"] = (out["high"] - corps_haut) / amplitude
    out["bar_lower_wick_pct"] = (corps_bas - out["low"]) / amplitude
    # Le finish aussi : `.last()` prelevait la DERNIERE MINUTE (saturee a 1,0
    # plus d'une fois sur trois), correlation 0,158 avec la barre. H3 a juge
    # sa REACTION la-dessus au cycle 1 — INCIDENT_LOG 07/09.
    out["finish_delta_pct"] = (out["close"] - out["low"]) / amplitude
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Regime — journee, lu a 10h30 ET
# ---------------------------------------------------------------------------

def regime_gamma(df, i, zone_morte_atr=1.0):
    """signe(dist_mq_hvl) avec zone morte. Trois etats.

    Sans zone morte, le regime bascule 10,2 fois par jour sur ES : ce n'est pas
    un regime. A 1,0 ATR, 1,8 fois, et 93 % des barres restent couvertes
    (mesure du 06/09).
    """
    v = df["dist_mq_hvl"].iloc[i] if "dist_mq_hvl" in df.columns else None
    atr = df["atr_barre"].iloc[i]
    if v is None or pd.isna(v) or pd.isna(atr) or atr <= 0:
        return "indetermine"
    seuil = zone_morte_atr * atr / 0.25          # ATR en points -> ticks
    if abs(v) < seuil:
        return "indetermine"
    return "au-dessus HVL" if v < 0 else "sous HVL"


def regime_ib(df, i):
    """`ib_range_ticks x tick / atr` — points sur points. La colonne livree
    `ib_range_atr` divise des ticks par des points (facteur 4, cf recalc)."""
    ir = df["ib_range_ticks"].iloc[i] if "ib_range_ticks" in df.columns else None
    at = df["atr"].iloc[i] if "atr" in df.columns else None
    if ir is None or at is None or pd.isna(ir) or pd.isna(at) or at <= 0 or ir <= 0:
        return "indetermine", None
    r = ir * 0.25 / at
    # Dalton : IB etroite -> tendance probable ; IB large -> range.
    return ("IB etroite" if r < 0.40 else "IB large"), r


def biais(df, i):
    """B1 seul pour l'instant : signe de `dist_vwap_w` (niveau A)."""
    v = df["dist_vwap_w"].iloc[i] if "dist_vwap_w" in df.columns else None
    if v is None or pd.isna(v):
        return 0
    return 1 if v < 0 else -1        # dist = niveau - close : negatif = au-dessus


# ---------------------------------------------------------------------------
# Boucle
# ---------------------------------------------------------------------------

def scruter(sym, jour, minutes=15, vitesse=0.0, journal=None):
    df = charger_jour(sym, jour, minutes)
    if df.empty:
        print(_c("  aucune barre exploitable pour %s le %s" % (sym, jour), ROUGE))
        return 1

    fns = {"H3": H.h3, "H6": H.h6, "H7": H.h7, "H8": H.h8}
    conds = {n: f(df) for n, f in fns.items()}
    lieux = H.lieux(df)
    compte = {"barres": 0, "signaux": 0, "trades": 0}
    portes = {}

    # Les gates sont SEQUENTIELS : le nombre de trades du jour, le P&L cumule et
    # l'heure du dernier trade ne se lisent pas sur une barre isolee. Les appeler
    # signal par signal remet le compteur a zero a chaque fois — L0_MAX_TRADES
    # ne pouvait alors jamais se declencher (8 signaux retenus pour une limite
    # de 5, au premier run). On collecte donc TOUS les signaux de la journee,
    # on les passe aux portes en UNE fois, puis on rejoue l'affichage.
    signaux = []
    for i in range(len(df)):
        for nom, paires in conds.items():
            for cote, (cond, side) in paires.items():
                try:
                    if bool(cond.iloc[i]):
                        signaux.append((i, nom, cote, side))
                except Exception:
                    continue
    signaux.sort(key=lambda x: x[0])
    retenus = set(chaine.appliquer([(s[0], s[3]) for s in signaux], df, sym,
                                   journal=journal, hypothese="scrutateur"))
    motifs = _motifs_par_barre(journal)

    entete(sym, jour, minutes, len(df))
    for i in range(len(df)):
        compte["barres"] += 1
        ts = int(df["ts"].iloc[i])
        hhmm = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%H:%M")
        rg = regime_gamma(df, i)
        rib, rib_v = regime_ib(df, i)
        bi = biais(df, i)

        if i == 0 or rg != regime_gamma(df, i - 1):
            print("  %s  %s  %s" % (_c(hhmm, GRIS), _c("REG", CYAN),
                                    _c("%s / %s%s" % (rg, rib,
                                       "" if rib_v is None else " (%.2f)" % rib_v), CYAN)))

        for (bi_, nom, cote, _side) in [s for s in signaux if s[0] == i]:
            compte["signaux"] += 1
            if i in retenus:
                compte["trades"] += 1
                print("  %s  %s  %-14s %s" % (
                    _c(hhmm, GRIS), _c("L3 ", VERT), "%s %s" % (nom, cote),
                    _c("SIGNAL RETENU", VERT + ";" + GRAS)))
            else:
                m = motifs.get(int(df["ts"].iloc[i]), "porte L0/L5")
                portes[m] = portes.get(m, 0) + 1
                couche = "L0 " if m.startswith("L0") else "L5 "
                print("  %s  %s  %-14s %s" % (
                    _c(hhmm, GRIS), _c(couche, ROUGE), "%s %s" % (nom, cote),
                    _c("BLOQUE  %s" % m, ROUGE)))
        if vitesse:
            time.sleep(vitesse)

    pied(compte, portes, lieux, df)
    return 0


def _motifs_par_barre(chemin):
    """{ts: motif} des BLOQUE, lu dans le journal de l'entonnoir."""
    out = {}
    if not chemin or not os.path.exists(chemin):
        return out
    try:
        for ln in open(chemin, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            o = json.loads(ln)
            if o.get("decision") == "BLOQUE":
                out[int(o["ts"])] = o.get("motif", "?")
    except Exception:
        pass
    return out


def entete(sym, jour, minutes, n):
    print()
    print(_c("  MIA — scrutateur   %s   %s   barres %d min   %d barres cash"
             % (sym, jour, minutes, n), GRAS))
    print(_c("  il n'ouvre aucune position — il regarde et il journalise", GRIS))
    print(_c("  " + "-" * 74, GRIS))


def pied(compte, portes, lieux, df):
    print(_c("  " + "-" * 74, GRIS))
    print("  %-22s %d barres | %d signaux bruts | %s"
          % ("BILAN", compte["barres"], compte["signaux"],
             _c("%d retenus" % compte["trades"], VERT if compte["trades"] else JAUNE)))
    if compte["signaux"]:
        part = 1 - compte["trades"] / compte["signaux"]
        print("  %-22s %.0f %% des signaux fermes par les portes" % ("", 100 * part))
    for m, n in sorted(portes.items(), key=lambda x: -x[1]):
        print("     %-34s %4d" % (m, n))
    print()
    print(_c("  lieux atteints dans la journee (avant reaction) :", GRIS))
    for nom, s in lieux.items():
        try:
            n = int(pd.Series(s).fillna(False).astype(bool).sum())
        except Exception:
            n = 0
        print("     %-6s %4d barres" % (nom, n))
    print()


def main():
    ap = argparse.ArgumentParser(description="MIA — le scrutateur (n'execute rien)")
    ap.add_argument("--replay", metavar="AAAAMMJJ", help="rejoue une journee")
    ap.add_argument("--sym", default="ES", choices=("ES", "NQ"))
    ap.add_argument("--minutes", type=int, default=15, help="unite de decision")
    ap.add_argument("--vitesse", type=float, default=0.0,
                    help="secondes entre barres (0 = plein regime)")
    ap.add_argument("--journal", default=None,
                    help="chemin JSONL de l'entonnoir (defaut : LOGS/entonnoir/<jour>)")
    a = ap.parse_args()

    if not a.replay:
        print("  --replay AAAAMMJJ requis. Le mode --live viendra quand le bot")
        print("  aura tourne en replay sur assez de journees pour qu'on sache")
        print("  ce que chaque porte ferme.")
        return 2
    j = a.journal or ("LOGS/entonnoir/scrutateur_%s_%s.jsonl" % (a.sym, a.replay))
    os.makedirs(os.path.dirname(j), exist_ok=True)
    return scruter(a.sym, a.replay, a.minutes, a.vitesse, j)


if __name__ == "__main__":
    sys.exit(main())
