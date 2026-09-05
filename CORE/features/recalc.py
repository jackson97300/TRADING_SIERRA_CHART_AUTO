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

# Session Sierra : ouverture 17h ET. En UTC : 21:00 (EDT) / 22:00 (EST).
OUVERTURE_SESS_UTC_EDT = 21
# Cash : 9h30-16h00 ET. En UTC : 13:30-20:00 (EDT).
CASH_DEBUT_MIN_EDT = 13 * 60 + 30
CASH_FIN_MIN_EDT = 20 * 60
BARRES_SESSION = 1380


# ---------------------------------------------------------------------------
# 0. Horodatage
# ---------------------------------------------------------------------------

def normaliser_ts(ts_ms):
    """Aligne les horodatages sur le debut de minute.

    Fenetre : aucune (transformation ponctuelle).
    Unite : millisecondes epoch UTC.
    Signe : sans objet.

    Deux conventions coexistent dans les donnees : `HH:MM:00` (debut de barre)
    et `HH:MM:59` (fin de barre moins une seconde), cette derniere sur 31 % des
    lignes. Sans normalisation, un groupby par minute perd 30 % des barres —
    mesure : 950 minutes distinctes au lieu de 1379.
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
    """
    d = pd.to_datetime(dt, utc=True)
    return (d + pd.Timedelta(hours=24 - OUVERTURE_SESS_UTC_EDT)).dt.date


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
    """
    agg = pd.DataFrame({
        "h": pd.to_numeric(df["high"], errors="coerce").groupby(cle).max(),
        "l": pd.to_numeric(df["low"], errors="coerce").groupby(cle).min(),
    }).sort_index().shift(1)
    cle_s = pd.Series(list(cle), index=df.index)
    return pd.DataFrame({"pdh": cle_s.map(agg["h"]), "pdl": cle_s.map(agg["l"])})


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
# 5. Momentum
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
