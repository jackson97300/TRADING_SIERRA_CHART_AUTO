"""Bibliotheque unique des formules de recalcul.

Version executable de `DOCS/CONVENTIONS.md`. Importee par les scripts de
recherche aujourd'hui, par l'enricher le jour ou le VPS est modifie — jamais
reimplementee ailleurs. Un test de parite compare les deux sorties sur 51 jours.

**Chaque fonction porte dans sa docstring : la fenetre, l'unite de sortie, la
convention de signe.** C'est ce que lit le test de parite.

Ce module ne lit ni n'ecrit aucun fichier et ne deploie rien.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from CORE.constants import get_tick_size
except ImportError:  # lance depuis CORE/
    from constants import get_tick_size

# Cash : 9h30-16h00 HEURE DE L'EST — en minutes ET (`minutes_et`), plus
# jamais en UTC fige : la fenetre UTC bouge au changement d'heure.
CASH_DEBUT_MIN_ET = 9 * 60 + 30
CASH_FIN_MIN_ET = 16 * 60
# Constantes UTC-EDT : MORTES depuis la migration de surveillance_l6
# (08/09 — plus AUCUN consommateur dans CORE/V3). Gardees annotees jusqu'au
# solde du residuel A_FAIRE pt 19 (classer_colonnes fait son UTC en dur,
# sans les lire) ; retrait a ce moment-la, jamais silencieusement.
CASH_DEBUT_MIN_EDT = 13 * 60 + 30
CASH_FIN_MIN_EDT = 20 * 60
BARRES_SESSION = 1380


def _est_edt(d: pd.Timestamp) -> bool:
    """Heure d'ete americaine : 2e dimanche de mars -> 1er dimanche de novembre.

    Bascule a MINUIT UTC du dimanche de transition, pas a 2h locales — la
    fenetre d'ecart tombe le samedi soir ET, sans barre cash : sans
    consequence sur les colonnes, mais assume ici (review 08/09)."""
    an = d.year
    mars = pd.Timestamp(year=an, month=3, day=1, tz="UTC")
    debut = mars + pd.Timedelta(days=(6 - mars.dayofweek) % 7 + 7)
    nov = pd.Timestamp(year=an, month=11, day=1, tz="UTC")
    fin = nov + pd.Timedelta(days=(6 - nov.dayofweek) % 7)
    return debut <= d < fin


def ouverture_sess_utc(dt) -> pd.Series:
    """Heure UTC d'ouverture de la session Sierra (17h ET).

    Fenetre : `_sess`. Unite : heure entiere UTC. Signe : sans objet.

    Rend 21 en heure d'ete, 22 en heure d'hiver. Remplace la constante en dur
    qui aurait fallu corriger a la main au 1er novembre — la dette DST de
    `CONVENTIONS.md` §2 disparait le jour ou l'appelant utilise cette fonction.
    """
    d = pd.to_datetime(dt, utc=True)
    return pd.Series([21 if _est_edt(x) else 22 for x in d], index=d.index)


def minutes_et(dt):
    """Minutes depuis minuit, HEURE DE L'EST (9h30 cash = 570, 15h15 = 915).

    Fenetre : aucune. Unite : minutes [0, 1440). Signe : sans objet.

    Suit l'heure d'ete (decalage 4 h EDT / 5 h EST via `_est_edt`) — jamais
    de constante UTC en dur : la campagne traverse le 1er novembre, et la
    barre « 15h15 ET » saute de 19:15 a 20:15 UTC ce jour-la. Depuis le
    08/09 c'est LA base d'`est_cash` (la dette CONVENTIONS §2 est fermee a
    la source) : vectorise par date unique, pas de boucle par barre.
    """
    d = pd.to_datetime(dt, utc=True)
    dates = pd.Series(d.dt.date, index=d.index)
    dec = dates.map({x: (240 if _est_edt(pd.Timestamp(str(x), tz="UTC"))
                         else 300) for x in dates.unique()})
    return (d.dt.hour * 60 + d.dt.minute - dec) % 1440


# ---------------------------------------------------------------------------
# 0. Horodatage
# ---------------------------------------------------------------------------

def horodatage(df):
    """Horodatage de reference d'une barre.

    Fenetre : aucune. Unite : millisecondes epoch UTC. Signe : sans objet.

    **Lire `ts`, pas `ts_raw_ms`.** Le fichier porte les deux : `ts` est aligne
    sur la minute a 100 %, `ts_raw_ms` a 68,8 % seulement. Mesure sur 23 417
    lignes ES + NQ.
    """
    if "ts" in df.columns and pd.to_numeric(df["ts"], errors="coerce").notna().any():
        return pd.to_numeric(df["ts"], errors="coerce")
    return normaliser_ts(df["ts_raw_ms"])


def normaliser_ts(ts_ms):
    """Aligne un `ts_raw_ms` sur le debut de minute.

    Fenetre : aucune (transformation ponctuelle).
    Unite : millisecondes epoch UTC.
    Signe : sans objet.

    Deux conventions coexistent dans `ts_raw_ms` : `HH:MM:00` (debut de barre)
    et `HH:MM:59` (fin de barre moins une seconde), cette derniere sur 31 % des
    lignes. Sans normalisation, un groupby par minute perd 30 % des barres —
    mesure : 950 minutes distinctes au lieu de 1379.

    Cette fonction reproduit exactement la colonne `ts` du fichier (100 % sur
    23 417 lignes) : elle sert de repli quand `ts` est absent, et de preuve que
    la convention est bien celle du dumper. Preferer `horodatage(df)`.
    """
    ts = pd.to_numeric(ts_ms, errors="coerce")
    sec = (ts // 1000) % 60
    return ts.where(sec != 59, ts + 1000)


TS_MS_MIN = 1_500_000_000_000    # 2017-07 — plancher de l'invariant d'unite
TS_MS_MAX = 3_000_000_000_000    # 2065-01 — plafond


def ts_plage(valeurs):
    """Invariant FAIL-LOUD : un `ts` est en MILLISECONDES epoch, ou il n'est pas.

    Reserve 1 revue Fable 08/09 : un test par site ne couvre que les sites
    connus. Hors [2017..2065], on refuse de continuer et on nomme l'unite
    probable (cf INCIDENT_LOG 08/09 : pandas 3 + astype nu = mega-secondes,
    ferie fantome 1970).
    """
    v = pd.to_numeric(valeurs, errors="coerce").dropna()
    if len(v) == 0:
        return
    lo, hi = int(v.min()), int(v.max())
    if lo < TS_MS_MIN or hi > TS_MS_MAX:
        unite = ("secondes" if 1e9 <= abs(hi) < 1e11 else
                 "microsecondes" if abs(hi) > 1e14 else
                 "mega-secondes" if 1e5 <= abs(hi) < 1e8 else "inconnue")
        raise ValueError(
            "ts hors plage ms [%d..%d] : min=%d max=%d — unite probable : %s"
            % (TS_MS_MIN, TS_MS_MAX, lo, hi, unite))


def ts_ms(index):
    """Index datetime -> epoch ms, unite normalisee PUIS invariant verifie."""
    ts = index.as_unit("ns").astype("int64") // 1_000_000
    ts_plage(pd.Series(ts))
    return ts


# ---------------------------------------------------------------------------
# 1. Fenetres
# ---------------------------------------------------------------------------

def session_sess(dt):
    """Cle de session complete, 17h ET -> 17h ET.

    Fenetre : `_sess`.
    Unite : date.
    Signe : sans objet.

    Ne jamais utiliser `session_date` du fichier : elle bascule a 04:01 UTC dans
    60 cas et a 21:59 dans 10, sur la meme periode.

    Le decalage suit l'heure d'ete : ouverture a 21:00 UTC en EDT, 22:00 en EST.
    """
    d = pd.to_datetime(dt, utc=True)
    h = ouverture_sess_utc(d)
    return (d + pd.to_timedelta(24 - h, unit="h")).dt.date


def est_cash(dt):
    """Masque de la seance cash.

    Fenetre : `_rth`, 9h30-16h00 ET — en minutes ET (`minutes_et`), EDT et
    EST. La constante UTC figee (dette CONVENTIONS §2) ratait l'heure
    d'hiver : des le 2/11 la barre 15h15 ET quittait la fenetre et 8h30 ET
    y entrait — L0 elle-meme aurait deplace la session d'une heure. Fermee
    le 08/09 (audit Fable §2 : dette L0, pas C2). LA PREUVE est l'annee
    synthetique 2026 (la seule qui contient de l'EST : ecarts uniquement
    aux bords de fenetre attendus) ; le lot reel, ENTIEREMENT EDT, ne
    prouve rien sur l'hiver — il sert de NON-REGRESSION : 0/271 940 barres
    (revue 08/09, B2 : l'ordre des deux compte).
    Unite : booleen. Signe : sans objet.
    """
    mn = minutes_et(dt)
    return (mn >= CASH_DEBUT_MIN_ET) & (mn < CASH_FIN_MIN_ET)


def session_rth(dt):
    """Cle de seance cash. Fenetre `_rth`. Unite : date. Vide hors cash."""
    d = pd.to_datetime(dt, utc=True)
    return pd.Series(d.dt.date, index=d.index).where(est_cash(dt))


# ---------------------------------------------------------------------------
# 2. VWAP
# ---------------------------------------------------------------------------

def _hlc3(df):
    return (pd.to_numeric(df["high"], errors="coerce")
            + pd.to_numeric(df["low"], errors="coerce")
            + pd.to_numeric(df["close"], errors="coerce")) / 3.0


def vwap_cumule(df, cle, col_vol="total_vol"):
    """VWAP cumulee depuis le debut de la fenetre, prix de reference `hlc3`.

    Fenetre : celle portee par `cle` (`session_sess` ou `session_rth`).
    Unite : POINTS (meme echelle que `close`).
    Signe : sans objet.

    `hlc3` et non `close` : verifie a 0,043 point d'ecart median sur ES contre
    0,138 avec `close`.
    """
    v = pd.to_numeric(df[col_vol], errors="coerce").fillna(0.0)
    num = (_hlc3(df) * v).groupby(cle).cumsum()
    den = v.groupby(cle).cumsum().replace(0, np.nan)
    return num / den


def vwap_bandes(df, cle, vwap, n_sd=1.0, col_vol="total_vol"):
    """Bandes d'ecart-type ponderees volume autour de la VWAP.

    Fenetre : celle de `cle`. Unite : POINTS. Signe : `sup` > vwap > `inf`.
    """
    v = pd.to_numeric(df[col_vol], errors="coerce").fillna(0.0)
    num = ((_hlc3(df) - vwap) ** 2 * v).groupby(cle).cumsum()
    den = v.groupby(cle).cumsum().replace(0, np.nan)
    sd = np.sqrt(num / den)
    return pd.DataFrame({"sup": vwap + n_sd * sd, "inf": vwap - n_sd * sd})


# ---------------------------------------------------------------------------
# 3. Niveaux de session
# ---------------------------------------------------------------------------

def extremes_session(df, cle):
    """Plus haut et plus bas courants de la fenetre, cumules.

    Fenetre : celle de `cle`. Unite : POINTS. Signe : `haut` >= `bas`.
    """
    return pd.DataFrame({
        "haut": pd.to_numeric(df["high"], errors="coerce").groupby(cle).cummax(),
        "bas": pd.to_numeric(df["low"], errors="coerce").groupby(cle).cummin(),
    })


def extremes_veille(df, cle):
    """PDH / PDL : extremes de la fenetre precedente, diffuses sur la courante.

    Fenetre : `_sess`. Unite : POINTS. Signe : `pdh` >= `pdl`.

    La "veille" est la session PRESENTE precedente, pas la date moins un jour :
    le lundi renvoie au vendredi, ce qui est correct. Mais le lendemain d'une
    journee absente, elle renvoie a l'avant-veille — d'ou la colonne
    `veille_contigue` (booleen), a `False` quand l'ecart depasse trois jours
    calendaires. Ne jamais consommer `pdh` sans la regarder.

    Ne concorde qu'a 70 % avec le `pdh` de Sierra, dont la fenetre reste
    inconnue (six testees, aucune au-dela de 70,4 %). C'est la raison pour
    laquelle le §6 fait recalculer cette famille plutot que la lire.
    """
    agg = pd.DataFrame({
        "h": pd.to_numeric(df["high"], errors="coerce").groupby(cle).max(),
        "l": pd.to_numeric(df["low"], errors="coerce").groupby(cle).min(),
    }).sort_index()
    prec = agg.shift(1)
    jours = pd.Series(agg.index, index=agg.index)
    ecart = (pd.to_datetime(jours) - pd.to_datetime(jours).shift(1)).dt.days
    prec["contigue"] = (ecart <= 3).fillna(False)
    cle_s = pd.Series(list(cle), index=df.index)
    return pd.DataFrame({"pdh": cle_s.map(prec["h"]),
                         "pdl": cle_s.map(prec["l"]),
                         "veille_contigue": cle_s.map(prec["contigue"]).fillna(False)})


def initial_balance(df, dt, minutes=60):
    """Initial Balance : extremes des N premieres minutes de cash.

    Fenetre : `_rth`. Unite : POINTS. Signe : `ib_high` >= `ib_low`.
    Fige apres la fin de l'IB, diffuse jusqu'a la cloture cash.
    """
    d = pd.to_datetime(dt, utc=True)
    mn = minutes_et(dt)
    dans_ib = est_cash(dt) & (mn < CASH_DEBUT_MIN_ET + minutes)
    jour = pd.Series(d.dt.date, index=df.index)
    h = pd.to_numeric(df["high"], errors="coerce").where(dans_ib)
    l = pd.to_numeric(df["low"], errors="coerce").where(dans_ib)
    return pd.DataFrame({"ib_high": h.groupby(jour).transform("max"),
                         "ib_low": l.groupby(jour).transform("min")})


# ---------------------------------------------------------------------------
# 4. Distances — convention unique
# ---------------------------------------------------------------------------

def dist_ticks(niveau, close, symbole):
    """Distance a un niveau, en ticks.

    Fenetre : celle du niveau. Unite : TICKS.
    Signe : `(niveau - close) / tick` — positif si le niveau est AU-DESSUS du
    prix. C'est la convention de toutes les distances exactes du fichier
    (`dist_vwap_d`, `dist_prev_vpoc`, `dist_pdh`).
    """
    return (pd.to_numeric(niveau, errors="coerce")
            - pd.to_numeric(close, errors="coerce")) / get_tick_size(symbole)


def dist_atr(niveau, close, atr):
    """Distance a un niveau, en multiples d'ATR journalier.

    Unite : multiples d'ATR. Signe : `(niveau - close) / atr`, meme convention.

    `atr` est en POINTS (controle : 0,5-3 % du prix). Ne jamais utiliser
    `atr_14m`, qui est en TICKS. Les colonnes `dist_*_atr` livrees divisent des
    ticks par des points et valent 4x le vrai nombre d'ATR.
    """
    return ((pd.to_numeric(niveau, errors="coerce")
             - pd.to_numeric(close, errors="coerce"))
            / pd.to_numeric(atr, errors="coerce").replace(0, np.nan))


def dist_pct(niveau, close):
    """Distance a un niveau, en % du prix.

    Unite : pourcentage. Signe : `(niveau - close) / close * 100`.

    Six colonnes livrees utilisent la convention inverse (`close - niveau`), a
    0,0 % de conformite sur ES et NQ : `dist_asia_high_pct`, `dist_asia_low_pct`,
    `dist_london_high_pct`, `dist_london_low_pct`, `dist_cash_high_atr`,
    `dist_cash_low_atr`.
    """
    c = pd.to_numeric(close, errors="coerce")
    return (pd.to_numeric(niveau, errors="coerce") - c) / c * 100.0


# ---------------------------------------------------------------------------
# 5. Cumuls de session — TOUS recalcules, sans exception
# ---------------------------------------------------------------------------
# Un cumul depuis une borne de session repart de zero au redemarrage du
# processus, par construction : ce n'est pas un defaut de la colonne, c'est sa
# nature. Sept colonnes livrees sont dans ce cas (`cvd_day`, `delta_day`,
# `cvd_session`, `ctx_cvd_session`, `ctx_delta_sum_3`, `ctx_delta_sum_10`,
# `cvd_bar_delta`) et elles franchissent le seuil de suspicion a des
# frequences differentes seulement parce qu'elles s'accumulent a des vitesses
# differentes. Mesure : `cvd_day` suspect 8 jours sur 51, `ctx_delta_sum_3` 1.

def cumul_delta(df, cle, col_delta="delta_bar"):
    """Cumul du delta depuis le debut de la fenetre portee par `cle`.

    Fenetre : celle de `cle` — `session_sess` pour un cumul de session
    complete, `session_rth` pour un cumul de seance cash.
    Unite : contrats (meme unite que `delta_bar`).
    Signe : positif quand les acheteurs dominent depuis la borne.

    Les deux ne disent PAS la meme chose et ne doivent jamais porter le meme
    nom : `cvd_sess_r` cumule depuis 17h ET, `cvd_rth_r` depuis 9h30 ET. La
    colonne livree `cvd_day` melange les deux selon le moment du redemarrage.
    """
    d = pd.to_numeric(df[col_delta], errors="coerce").fillna(0.0)
    return d.groupby(cle).cumsum()


def atr_veille_15(df, dt, minutes=15):
    """Mediane de l'ATR de barre agregee de la SESSION CASH PRECEDENTE.

    Fenetre : la veille cash entiere. Unite : POINTS (echelle atr_barre).
    Signe : sans objet.

    LE SECOURS DU TROU DE CHAUFFE (audit Fable 08/09) : `atr_barre`
    (rolling 14, min_periods 7) est NaN sur 100 % des barres 9h30-11h00 —
    zero lieu en ATR possible pendant l'IB, 0 signal des quatre avant
    11h00 sur 52 j x 2 (rapport trou_atr_les_quatre). La veille est
    disponible des la barre 0, SANS FUITE : la valeur d'une date ne lit
    que les barres 1 min de la date cash PRECEDENTE. C'est la solution
    deja adoptee par L1 (DECISIONS 07/09 : « l'ATR de reference du biais
    est celui de la VEILLE »), generalisee.

    Prend le 1 min MULTI-JOURS (la chauffe), rend une Series indexee par
    DATE cash : valeur a la date d = mediane de l'ATR agrege de la derniere
    date cash COMPLETE strictement avant d. NaN tant qu'aucune ne precede.

    DERNIERE SESSION COMPLETE, PAS DERNIERE SESSION (brique 1 Fable, 09/09,
    DECISIONS) : le lendemain d'une demi-seance ou d'un fichier tronque
    (08/05 : derniere barre 14h30), la veille utile est celle d'avant — la
    mediane d'une demi-journee est un metre faux. Complete = toutes les
    barres agregees de la fenetre cash (9h30-16h00 ET = 390 min) presentes,
    >= 380 minutes, UN SEUL contrat. Exemple (CONVENTIONS §10) : le 08/09
    lit le vendredi 04/09 (8,2054 ES), pas la demi-seance de Labor Day.
    Fige a 9h30 par construction : la valeur d'une date ne lit que les
    dates precedentes, rien de la seance en cours.
    """
    cash_min = 390                            # la fenetre d'`est_cash`, en minutes
    d = pd.to_datetime(dt, utc=True)
    cash = est_cash(d)
    g = pd.DataFrame({
        "j": pd.Series(d.dt.date, index=df.index).where(cash),
        "b": pd.to_numeric(df["ts"], errors="coerce") // (minutes * 60_000),
        "h": pd.to_numeric(df["high"], errors="coerce"),
        "l": pd.to_numeric(df["low"], errors="coerce"),
        "c": pd.to_numeric(df["close"], errors="coerce"),
        # UN SEUL CONTRAT PAR SESSION (Fable Q7, 10/09) : une session qui
        # bascule U26 -> Z26 en seance porte un bin dont le TR est la BASE
        # entre contrats, pas un range — elle n'est pas complete, par
        # definition. La campagne porte `contract` (COLS_RECALC) ; un frame
        # sans la colonne ne peut pas appliquer le critere (les autres tiennent).
        "k": (df["contract"].astype(str) if "contract" in df.columns
              else pd.Series("?", index=df.index)),
    }).dropna(subset=["j"])
    if g.empty:
        return pd.Series(dtype=float)
    agg = (g.groupby(["j", "b"])
            .agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
            .reset_index().sort_values(["j", "b"]))
    prev_c = agg.groupby("j")["c"].shift()
    tr = pd.concat([agg["h"] - agg["l"], (agg["h"] - prev_c).abs(),
                    (agg["l"] - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.groupby(agg["j"].values).transform(
        lambda s: s.rolling(14, min_periods=7).mean())
    med = atr.groupby(agg["j"].values).median().sort_index()
    n_barres = agg.groupby("j").size().reindex(med.index)
    n_min = g.groupby("j").size().reindex(med.index)
    n_contrats = g.groupby("j")["k"].nunique().reindex(med.index)
    # complete = tous les bins ET (review 10/09, Q1) presque toutes les minutes
    # — un bin qui n'a qu'UNE barre 1 min compte « present », pas le jour —
    # ET un seul contrat.
    complete = ((n_barres >= (cash_min // minutes)) & (n_min >= cash_min - 10)
                & (n_contrats <= 1))
    # where(complete) efface les demi-seances ; ffill porte la derniere
    # complete jusqu'a la date suivante ; shift(1) = « strictement avant ».
    # Indexee sur TOUTES les dates du frame, cash ou nuit (review 10/09, R1 :
    # a 9h25 le jour n'a que sa nuit Globex et doit lire la veille quand
    # meme) — valeurs inchangees pour les dates qui ont du cash.
    toutes = pd.Index(sorted(set(x for x in d.dt.date if x is not None and x == x)
                             | set(med.index)))
    return med.where(complete).reindex(toutes).ffill().shift(1)


def rvol(df, dt, n_jours=20, col_vol="total_vol"):
    """Volume relatif : volume de la barre / mediane de la MEME MINUTE de
    session sur les `n_jours` precedents.

    Fenetre : aucune (glissante sur l'historique).
    Unite : ratio sans dimension, 1,0 = volume habituel de cette minute.
    Signe : sans objet, toujours positif.

    **La reference ne regarde que le PASSE** : les jours precedents
    strictement, jamais le jour courant ni les suivants. Sans cette
    contrainte, un volume anormal se normaliserait par lui-meme.

    **Chauffe** : les `n_jours` premiers jours du lot n'ont pas de reference
    complete et rendent NaN plutot qu'un ratio calcule sur trois jours. Pour
    les couvrir, passer un `df` qui commence `n_jours` avant la periode
    etudiee — les journees ecartees comme pannes restent utilisables ici : le
    volume brut d'une journee a trous reste une reference valide pour les
    minutes qu'elle couvre.
    """
    d = pd.to_datetime(dt, utc=True)
    v = pd.to_numeric(df[col_vol], errors="coerce")
    jour = pd.Series(d.dt.date, index=df.index)
    minute = d.dt.hour * 60 + d.dt.minute

    tab = pd.DataFrame({"j": jour, "m": minute, "v": v})
    # Mediane du volume par (minute, jour), puis mediane glissante sur les
    # jours STRICTEMENT PRECEDENTS. `shift(axis=1)` decale d'un jour avant le
    # rolling : sans lui, le jour courant entrerait dans sa propre reference.
    # Jours en LIGNES, minutes en colonnes : le rolling se fait alors sur l'axe
    # standard. `rolling(axis=1)` est deprecie dans pandas 2 et rend du NaN en
    # silence — le premier essai sortait zero valeur sur 33 826 barres.
    par = tab.groupby(["j", "m"])["v"].median().unstack("m").sort_index()
    # FENETRE de n_jours, mais seulement n_jours/2 OBSERVATIONS exigees. Les
    # deux ne sont pas la meme chose : 18 % des couples (jour, minute) sont
    # vides — des minutes overnight sans echange. Avec `min_periods=n_jours`,
    # aucune cellule ne survit (mesure : 0 sur 41 400), parce qu'il faudrait
    # vingt jours consecutifs sans le moindre trou sur cette minute precise.
    # A la moitie, 24 413 cellules, et une mediane de dix jours reste robuste.
    ref = par.shift(1).rolling(n_jours, min_periods=max(n_jours // 2, 5)).median()
    ref = ref.stack(future_stack=True).rename("ref").reset_index()
    ref.columns = ["j", "m", "ref"]
    fusion = tab.reset_index().merge(ref, on=["m", "j"], how="left").set_index("index")
    r = fusion["v"] / fusion["ref"].replace(0.0, np.nan)
    return r.reindex(df.index).replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# 6. Version de fenetre
# ---------------------------------------------------------------------------

# Premiere session ecrite apres la correction des session times Sierra
# (05/09/2026). Avant : les etudes se reinitialisaient a 17:00 UTC, soit 13h ET,
# en pleine seance. Cf CONVENTIONS.md §9.
BASCULE_W1_MS = 1788728400000  # 2026-09-06 21:00:00 UTC (verifie)


def window_version(ts_ms):
    """Version de fenetre de chaque barre : `w0` ou `w1`.

    Fenetre : sans objet. Unite : chaine. Signe : sans objet.

    Qualifie les colonnes DUMPEES EN LIVE, pas la date de la barre : des VA
    exportees de l'historique apres recalcul Sierra sont `w1` meme pour des
    dates anterieures. Un lot qui melange les deux sur une colonne de session
    doit etre refuse, pas moyenne.
    """
    ts = pd.to_numeric(ts_ms, errors="coerce")
    return pd.Series(np.where(ts >= BASCULE_W1_MS, "w1", "w0"),
                     index=getattr(ts, "index", None))


# ---------------------------------------------------------------------------
# 7. Momentum
# ---------------------------------------------------------------------------

def momentum(close, n):
    """Variation du prix sur n barres.

    Fenetre : aucune (glissante). Unite : POINTS.
    Signe : positif si le prix monte.

    Les colonnes livrees `momentum_3b` et `momentum_5b` valent en realite
    `close - close[-1]` et `close - close[-2]` (mesure : 100 % sur ES et NQ).
    Leur cause reste inconnue ; elles ne doivent pas etre utilisees telles quelles.
    """
    c = pd.to_numeric(close, errors="coerce")
    return c - c.shift(n)


def finish(df):
    """Position de la cloture dans le range de la barre : (close-low)/(high-low).

    Fenetre : la barre elle-meme, a l'echelle du frame passe (1 min ou 15 min).
    Unite : sans dimension, [0 ; 1]. Signe : 1 = cloture au plus haut.

    Remplace `finish_delta_pct` livre : mesure du 07/09 (INCIDENT
    VALIDATION_MISS), la colonne 15 min est calculee sur la DERNIERE MINUTE
    de la fenetre, pas sur la barre agregee. NaN quand high == low — un trou,
    jamais un 0,5 invente.
    """
    h = pd.to_numeric(df["high"], errors="coerce")
    bas = pd.to_numeric(df["low"], errors="coerce")
    c = pd.to_numeric(df["close"], errors="coerce")
    rng = h - bas
    return (c - bas) / rng.where(rng > 0)


def pente_vwap(vwap, atr, n=4, jours=None):
    """Pente de la VWAP sur n barres, en multiples d'ATR.

    Fenetre : n barres du frame passe (defaut 4, brief OMBRE_C2 §3 — quatre
    barres de 15 min). Unite : ATR, sans dimension. Signe : positif quand la
    VWAP monte.

    Remplace `vwap_slope_10/30` livrees (provenance B, jamais reproduites) :
    le brief exige la pente RECALCULEE de `vwap_rth_r`. AU MOINS les n
    premieres barres rendent NaN (l'ATR ajoute les siens) — un trou, jamais
    un zero. `jours` : cle de journee ; sans elle, un frame multi-jours
    calculerait une pente entre DEUX sessions RTH sans rapport — la valeur
    fausse et non-NaN, la classe de bug que le franchissement a deja reglee
    par sa remise a zero (review 08/09).
    """
    v = pd.to_numeric(vwap, errors="coerce")
    a = pd.to_numeric(atr, errors="coerce")
    prec = v.groupby(jours).shift(n) if jours is not None else v.shift(n)
    return (v - prec) / a.where(a > 0)


# ---------------------------------------------------------------------------
# 8. Dedoublonnage — le chemin correct doit etre le chemin court
# ---------------------------------------------------------------------------

def dedoublonner_par_minute(lignes, cle_ts="ts"):
    """Une ligne par minute, selon l'ordre de CONVENTIONS §4. **Seul ordre admis.**

    L'enricher reecrit des lignes deja ecrites : un fichier peut porter 20 940
    lignes pour 1 259 barres reelles. Un comptage fait sans cette etape donne un
    resultat plausible et faux — c'est arrive deux fois le 06/09, sur le nombre
    de jours exploitables puis sur `day_type`.

    ORDRE DE DEPARTAGE, mesure et non suppose :
      1. `data_quality_flag == stable` avant `warmup` avant `degraded` ;
      2. a egalite, **la ligne la plus complete** (le plus de champs non nuls) ;
      3. a egalite encore, la premiere — par convention, pour etre deterministe.

    Pourquoi pas « la derniere fait foi », et pourquoi pas « la premiere » non
    plus : mesure du 06/09 sur les 524 minutes dupliquees des 57 jours, lignes
    `stable` seulement —

        ES   premiere plus complete 21,8 %   derniere 18,4 %   egalite 59,8 %
        NQ   premiere plus complete 28,9 %   derniere 29,3 %   egalite 41,8 %

    Aucune position ne domine. L'ecart de 548 contre 573 champs observe le 04/09,
    qui avait motive le « jamais keep=last » du §4, etait une propriete de ce
    jour-la, pas de la serie. **C'est la completude qui departage, pas le rang.**
    Une politique par position lirait des nulls une fois sur cinq, et une
    hypothese qui tombe sur un null a la barre t ne declenche pas sans le dire.

    Accepte une liste de dicts (JSONL) ou un DataFrame, et rend le meme type.

    >>> l = [{"ts": 60000, "a": 1, "b": None}, {"ts": 60000, "a": 1, "b": 2},
    ...      {"ts": 120000, "a": 3, "b": 4}]
    >>> [d["b"] for d in dedoublonner_par_minute(l)]      # la plus complete gagne
    [2, 4]
    """
    rang = {"stable": 0, "warmup": 1, "degraded": 2}

    if isinstance(lignes, pd.DataFrame):
        if lignes.empty or cle_ts not in lignes.columns:
            return lignes
        d = lignes.copy()
        d["_minute"] = pd.to_numeric(d[cle_ts], errors="coerce") // 60000
        d = d.dropna(subset=["_minute"])
        d["_rang"] = (d["data_quality_flag"].map(rang).fillna(3)
                      if "data_quality_flag" in d.columns else 0)
        d["_plein"] = -d.notna().sum(axis=1)          # negatif : plus complet = plus petit
        d["_ordre"] = range(len(d))
        d = (d.sort_values(["_minute", "_rang", "_plein", "_ordre"])
              .drop_duplicates("_minute", keep="first")
              .drop(columns=["_minute", "_rang", "_plein", "_ordre"])
              .sort_values(cle_ts)
              .reset_index(drop=True))
        return d

    best = {}
    for pos, d in enumerate(lignes):
        ts = d.get(cle_ts)
        if ts is None:
            continue
        m = int(ts) // 60000
        cle = (rang.get(d.get("data_quality_flag"), 3),
               -sum(1 for v in d.values() if v is not None),
               pos)
        if m not in best or cle < best[m][0]:
            best[m] = (cle, d)
    return [best[m][1] for m in sorted(best)]


def ib_range_atr_r(df, tick=0.25):
    """Largeur de l'IB en multiples d'ATR. **Ne pas lire `ib_range_atr` livre.**

    La colonne livree vaut `ib_range_ticks / atr` : des TICKS divises par des
    POINTS. Mesure du 06/09 sur 12 580 barres ES + NQ — la formule ci-dessous
    reproduit le livre a 100 %, ce qui identifie le diviseur sans ambiguite :

        livre            mediane  1,713 ES  /  1,775 NQ
        ticks / atr      identique au livre a 100,0 %
        ticks x 0,25 / atr (points / points)   mediane  0,428  /  0,444

    Facteur 4 (= 1 / 0,25), le meme que sur les `dist_*_atr`. Quatrieme bug de
    la famille ATR, et le premier sur une CONDITION DE REGIME : le tableau
    tague de MISSION_PHASE2 lit « `ib_range_atr` < 0,4 » pour H6 et « < 0,8 »
    pour H2. Avec la colonne livree, ces seuils couvrent 0,13 % et 5,9 % des
    barres ; avec la formule juste, 52,9 % et 96,9 %. H6 n'a jamais pu
    declencher — facteur 400 sur le lieu.

    Les seuils du paradigme de Jackson (« < 0,40 = IB etroite, 0,40-0,80 =
    rotation ») etaient donc JUSTES dans l'unite ou ils ont ete penses. La
    mediane corrigee, 0,43, tombe exactement a leur frontiere.

    Fenetre : constante apres 10h30 ET. Unite : sans dimension (points/points).
    """
    ir = pd.to_numeric(df.get("ib_range_ticks"), errors="coerce")
    at = pd.to_numeric(df.get("atr"), errors="coerce")
    return (ir * tick / at.where(at > 0))


# ---------------------------------------------------------------------------
# SCENARIOS — prerequis 1 : le type d'ouverture Dalton, RECALCULE (10/09/2026)
# ---------------------------------------------------------------------------

# v0 (Fable, relecture du 10/09 a e26236a) : TROIS types. DRIVE n'existe pas a
# 30 minutes (mesure : ES 1 / NQ 0 sur 57) : fusionne dans TEST_DRIVE, avec le
# booleen journalise `retour_open` (False = jamais revenu sur l'ouverture, ce
# qu'il reste du drive) et `traverse_b1` (False = l'ancien DRIVE pur). La
# traversee sur les premieres minutes 1 min = candidat cycle 2.
OPEN_TYPES = ("TEST_DRIVE", "REJET_RENVERSEMENT", "ENCHERE")


def open_type_r(df15, atr_ref, tick=0.25, open_lvl=None, p10=0.10, plancher=2.0):
    """Le type d'ouverture (Dalton) depuis les DEUX premieres barres 15 min cash
    et le retour ou non sur l'ouverture — definition ECRITE AVANT la mesure
    (SCENARIOS_SPEC §1, prerequis 1). Rend un dict, jamais un score.

    O = `open_lvl` (open_cash_lvl du brut) sinon l'open de la barre 0.
    bande = max(p10 x atr_ref / tick, plancher) ticks — la proximite P10 des
    fonctions gelees, LA SEULE unite admise ici (aucun autre seuil).
      s1, s2   : cote de la cloture de la barre 1 / 2 par rapport a O, 0 si
                 dans la bande.
      traverse : la barre 1 a depasse la bande des DEUX cotes de O.
      retour   : le range de la barre 2 touche la bande autour de O.
    Types, dans cet ordre de priorite :
      REJET_RENVERSEMENT  s1 et s2 non nuls, opposes — l'ouverture pousse d'un
                          cote, la 2e barre repasse O et cloture de l'autre.
      TEST_DRIVE          meme cote sans retour (s1 == s2 != 0), que la barre 1
                          ait traverse l'autre cote (`traverse_b1`) ou non
                          (False = l'ancien DRIVE pur : 1 jour ES / 0 NQ sur
                          57, pas un type a ce grain) — ou barre 1 indecise
                          (s1 == 0) et barre 2 partie sans retour.
      ENCHERE             tout le reste : clotures dans la bande, ou retour sur
                          O apres etre parti — l'enchere a deux sens.
    `retour_open` (= `retour_ouverture`) est journalise avec le type.
    Deux barres = 30 minutes : c'est le grain de la campagne, pas celui de
    Dalton (qui lit les premieres minutes). La distribution sur le lot
    (rapports/open_type_57j.md) a precede tout usage."""
    if df15 is None or len(df15) < 2:
        return {"type": None, "motif": "moins_de_deux_barres"}
    a = float(atr_ref) if atr_ref is not None and atr_ref == atr_ref else None
    if a is None or a <= 0:
        return {"type": None, "motif": "atr_ref_absent"}
    b1, b2 = df15.iloc[0], df15.iloc[1]
    o = float(open_lvl) if open_lvl is not None and open_lvl == open_lvl else float(b1["open"])
    bande = max(p10 * a / tick, plancher) * tick            # en points
    def cote(c):
        d = float(c) - o
        return 0 if abs(d) <= bande else (1 if d > 0 else -1)
    s1, s2 = cote(b1["close"]), cote(b2["close"])
    traverse = float(b1["high"]) > o + bande and float(b1["low"]) < o - bande
    retour = float(b2["low"]) <= o + bande and float(b2["high"]) >= o - bande
    if s1 and s2 and s2 == -s1:
        typ = "REJET_RENVERSEMENT"
    elif (s1 and s2 == s1 and not retour) or (s1 == 0 and s2 and not retour):
        typ = "TEST_DRIVE"
    else:
        typ = "ENCHERE"
    return {"type": typ, "direction": s2 or s1, "retour_ouverture": bool(retour),
            "retour_open": bool(retour), "traverse_b1": bool(traverse), "open_cash": round(o, 2),
            "bande_ticks": round(bande / tick, 2),
            "ext_b1_ticks": round((float(b1["close"]) - o) / tick, 2),
            "ext_b2_ticks": round((float(b2["close"]) - o) / tick, 2), "motif": None}


# ---------------------------------------------------------------------------
# SCENARIOS — prerequis 2 : le range, machine a quatre etats (post-it §2.2)
# ---------------------------------------------------------------------------

ETATS_RANGE = ("FORMATION", "ETABLI", "CASSE", "RETEST")


def _fiches_bord(df, col, tick, z_touche, z_reset, decalage):
    """Les fiches F23 d'un bord, indices ramenes dans le frame complet."""
    from CORE.features import f23                       # import tardif : pas de cycle
    dist = pd.to_numeric(df[col], errors="coerce")
    out = []
    for f in f23.fiches(df, None, col, tick, z_touche, z_reset):
        g = dict(f)
        # TENUE CAUSALE : la barre suivante cloture du cote d'ou le prix venait,
        # connue a i + 1 et rien d'autre. L'`issue` F23 finale attend jusqu'a
        # huit barres pour dire « casse » : elle decrit le futur du test, pas
        # ce qu'un observateur savait a i + 1 — direct et retrospectif
        # divergeraient (MISSION, test 6). L'acceptation se lit a part.
        j = g["i"] + 1
        v = dist.iloc[j] if j < len(dist) else np.nan
        g["tenu_a"] = (j + decalage) if np.isfinite(v) and ((v > 0) == (g["cote"] > 0)) else None
        g["i"] += decalage
        g["i_connu"] += decalage
        out.append(g)
    return out


def _pression(df15, fiches_vus, bord_haut, bord_bas, k):
    """Distance des extremes des k derniers tests au milieu / demi-largeur
    (post-it §2.6, nee « compression »). MESURE 10/09 sur l'IB : 1,18 / 1,08 a
    la barre AVANT la premiere cassure contre 1,05 / 1,07 sans — les meches
    S'ALLONGENT avant la cassure. On ne renverse pas l'hypothese apres coup
    (Fable) : meme definition, nom `pression` (> 1 = le marche s'appuie sur le
    bord), COLONNE JOURNALISEE, PAS UN ETAT ; H-PRESSION pre-enregistree pour
    le cycle 2 (NEXT_CYCLE §5 nonies). Aucun seuil.

    Pour chaque test : |EXTREME de la barre du test vers son bord - milieu| /
    (largeur / 2) — le high pour un test du bord haut, le low pour le bas.
    L'extreme, pas la cloture (Fable, 10/09, reponse 6) : la colonne mesure
    jusqu'ou le marche est alle chercher le bord, c'est la meche qui le
    porte ; la cloture porte la reaction. 1 = les meches atteignent les
    bords ; > 1 = elles les depassent ; vers 0 = elles s'arretent avant, le
    range ne se teste plus — ce qui annonce la cassure. Un ratio
    journalise, jamais un seuil ici."""
    if not fiches_vus:
        return None
    milieu, demi = (bord_haut + bord_bas) / 2.0, (bord_haut - bord_bas) / 2.0
    derniers = sorted(fiches_vus, key=lambda f: f["i"])[-k:]
    h = pd.to_numeric(df15["high"], errors="coerce")
    l_ = pd.to_numeric(df15["low"], errors="coerce")
    ext = [float(h.iloc[f["i"]]) if f["niveau"] == "dist_bord_haut" else float(l_.iloc[f["i"]])
           for f in derniers]
    return round(float(np.mean([abs(x - milieu) / demi for x in ext])), 3)


def range_r(df15, bord_haut, bord_bas, i_debut=0, tick=0.25, z_touche=0.0,
            z_reset=0.5, w_min=None, w_max=None, k_pression=4):
    """La machine a quatre etats du post-it (§2.2) sur DEUX FICHES F23 FACE A
    FACE — definition ECRITE AVANT la mesure. Rend une ligne par barre 15 min
    a partir de `i_debut`, jamais un score.

    Les bords sont FIGES par l'appelant (apres 10h30 l'IB est le premier
    range ; sinon deux swings, ou VAH/VAL apres stabilite) : cette fonction
    ne les cherche pas, elle dit ce que le prix en fait. Chaque mot est une
    definition F23 existante, avec ses parametres de L1 (`z_touche`,
    `z_reset`) :
      test    une barre qui englobe le bord (F23 touche + hysteresis)
      tenue   la barre suivante cloture du cote d'ou le prix venait — lue a
              i + 1, CAUSALE (pas l'`issue` F23 finale, qui regarde 8 barres)
      acceptation au-dela  DEUX clotures consecutives au-dela du bord —
              strictement au-dela : une cloture SUR le bord est dedans
      regain  apres une acceptation, DEUX clotures consecutives dedans
    Etats :
      FORMATION  les deux bords existent, pas encore tenus deux fois chacun
      ETABLI     chaque bord : >= 2 tests TENUS et CONNUS (tenu_a <= i) ; largeur
                 dans [w_min, w_max] ATR-15m (None = pas de borne ; fixes
                 le 10/09 par Fable a p10 / p90 de l'IB dans `scenarios/seuils.yaml`) ; aucune acceptation dehors
      CASSE      acceptation au-dela d'un bord (evenement TRANSITION, `casse_par`
                 +1 par le haut / -1 par le bas)
      RETEST     apres CASSE, un test du bord casse PAR L'AUTRE COTE (la fiche
                 F23 de cote oppose) ; s'il tient : evenement CONTINUATION
    Un regain (deux clotures dedans) rend l'etat d'AVANT la cassure —
    evenement REGAIN, le head-fake du post-it, le desequilibre se lit a cote.
    Rien de ce qui n'est pas encore connu n'est revele : l'issue d'un test
    n'entre dans l'etat qu'a `i_connu`. Les bords ne bougent jamais ; un
    nouveau range = un nouvel appel.
    `largeur_atr` = (haut - bas) / atr de la barre (`atr_ref` si present,
    sinon `atr_barre`) ; `pression` : voir `_pression` ; `age_barres`
    depuis ETABLI ; `barres_depuis_pose` depuis `i_debut` — la grammaire en
    fait l'etat de sequence POSE (« bords poses, aucune acceptation dehors »,
    Fable 10/09 reponse 3 : il decrit, il ne valide pas ; FORMATION ici).
    v0 : UN range par journee, l'IB ; pas de second range apres une CASSE
    (les journees a deux ranges tombent en S_AUTRE et se comptent — reponse 2).
    Unite des bords : POINTS."""
    n = len(df15)
    if n == 0 or not (bord_haut > bord_bas) or i_debut >= n:
        return []
    d = df15.iloc[i_debut:].reset_index(drop=True).copy()
    close = pd.to_numeric(d["close"], errors="coerce")
    d["dist_bord_haut"] = (bord_haut - close) / tick
    d["dist_bord_bas"] = (bord_bas - close) / tick
    if "atr_ref" in d.columns:
        d["atr_barre"] = d["atr_ref"]              # le metre de la chaine (brique 1)
    fh = _fiches_bord(d, "dist_bord_haut", tick, z_touche, z_reset, i_debut)
    fb = _fiches_bord(d, "dist_bord_bas", tick, z_touche, z_reset, i_debut)
    atr = pd.to_numeric(d["atr_barre"], errors="coerce") if "atr_barre" in d.columns else pd.Series(np.nan, index=d.index)
    largeur = bord_haut - bord_bas
    etat, avant_casse, casse_par, i_casse, i_etabli = "FORMATION", None, None, None, None
    lignes = []
    for j in range(len(d)):
        i = j + i_debut
        c = float(close.iloc[j])
        cp = float(close.iloc[j - 1]) if j > 0 else None
        evenement = None
        a = float(atr.iloc[j]) if np.isfinite(atr.iloc[j]) and atr.iloc[j] > 0 else None
        l_atr = round(largeur / a, 3) if a else None
        largeur_ok = ((w_min is None or (l_atr is not None and l_atr >= w_min))
                      and (w_max is None or (l_atr is not None and l_atr <= w_max)))
        accepte_haut = c > bord_haut and cp is not None and cp > bord_haut
        accepte_bas = c < bord_bas and cp is not None and cp < bord_bas
        dedans = bord_bas <= c <= bord_haut
        dedans_p = cp is not None and bord_bas <= cp <= bord_haut
        tenus_h = [f for f in fh if f["tenu_a"] is not None and f["tenu_a"] <= i]
        tenus_b = [f for f in fb if f["tenu_a"] is not None and f["tenu_a"] <= i]
        if etat in ("FORMATION", "ETABLI"):
            if accepte_haut or accepte_bas:
                avant_casse, etat, casse_par, i_casse = etat, "CASSE", (1 if accepte_haut else -1), i
                evenement = "TRANSITION"
            elif etat == "FORMATION" and len(tenus_h) >= 2 and len(tenus_b) >= 2 and largeur_ok:
                etat, i_etabli, evenement = "ETABLI", i, "ETABLI"
        else:                                      # CASSE ou RETEST
            if dedans and dedans_p:
                etat, evenement, casse_par = avant_casse, "REGAIN", None
            else:
                fiches_bord = fh if casse_par > 0 else fb
                retests = [f for f in fiches_bord if i_casse < f["i"] <= i and f["cote"] == -casse_par]
                if etat == "CASSE" and retests:
                    etat, evenement = "RETEST", "RETEST"
                elif etat == "RETEST" and retests and retests[-1]["tenu_a"] == i:
                    evenement = "CONTINUATION"
        vus = [f for f in fh + fb if f["i"] <= i]
        lignes.append({
            "i": i, "ts": int(d["ts"].iloc[j]) if "ts" in d.columns else None, "etat": etat,
            "bord_haut": bord_haut, "bord_bas": bord_bas, "largeur_atr": l_atr,
            "n_tests_haut": sum(1 for f in fh if f["i"] <= i),
            "n_tests_bas": sum(1 for f in fb if f["i"] <= i),
            "age_barres": (i - i_etabli) if i_etabli is not None else None,
            "barres_depuis_pose": j,       # bords poses depuis j barres (etat POSE de la grammaire)
            "pression": _pression(d, [dict(f, i=f["i"] - i_debut) for f in vus],
                                        bord_haut, bord_bas, k_pression),
            "evenement": evenement, "casse_par": casse_par,
        })
    return lignes
