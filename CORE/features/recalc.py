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

# Cash : 9h30-16h00 ET. En UTC : 13:30-20:00 (EDT) / 14:30-21:00 (EST).
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

    Suit l'heure d'ete via `ouverture_sess_utc` (decalage 4 h EDT / 5 h EST) —
    jamais de constante UTC en dur : la campagne traverse le 1er novembre, et
    la barre « 15h15 ET » saute de 19:15 a 20:15 UTC ce jour-la. C'est la
    meme dette DST que `est_cash` (CONVENTIONS §2), reglee ici a la source.
    """
    d = pd.to_datetime(dt, utc=True)
    dec = (ouverture_sess_utc(d) - 17) * 60
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

    Fenetre : `_rth`, 9h30-16h00 ET (13:30-20:00 UTC en EDT).
    Unite : booleen.
    Signe : sans objet.
    """
    d = pd.to_datetime(dt, utc=True)
    mn = d.dt.hour * 60 + d.dt.minute
    return (mn >= CASH_DEBUT_MIN_EDT) & (mn < CASH_FIN_MIN_EDT)


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
    mn = d.dt.hour * 60 + d.dt.minute
    dans_ib = est_cash(dt) & (mn < CASH_DEBUT_MIN_EDT + minutes)
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
