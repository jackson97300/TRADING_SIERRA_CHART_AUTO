"""L0 — l'interrupteur : a-t-on le DROIT de trader, la, maintenant ?

L0 ne cherche pas de trade et n'a pas d'avis sur le marche. Elle dit si une
decision a le droit d'exister. Elle ne lit pas le sens du trade : les vetos
directionnels sont a L5.

Chaque porte est une fonction pure de trois lignes : elle lit une `lecture`
(une barre deja preparee) et un `etat`, elle rend True si elle bloque. **Aucun
seuil dans le code** — tout vient de `seuils.yaml`, qui est la source unique
des nombres et le seul endroit ou l'on change une classe.

    from V3.layers.L0_interrupteur import portes      # enregistre les portes
    from V3 import registre
    registre.evaluer_toutes(lecture, etat, seuils)

Mesure du 06/09 sur 57 jours, devenir signe dans le sens du trade :
    L0_POSITION_OUVERTE   93,5 % ES / 94,0 % NQ   +0,125 / +0,190
    L0_SESSION_BLOQUEE    10,1 %                  +0,069
    L0_NEWS                1,0 %                  -4,82   <- la meilleure porte
"""

from __future__ import annotations

import os

from V3.registre import porte

SEUILS_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "seuils.yaml")


# --- famille B — TEMPS ET CALENDRIER ----------------------------------------
@porte("L0_NEWS", "L0")
def _news(lec, etat, s):
    """Fenetre -15/+30 min autour des evenements CRITIQUES (FOMC, NFP, CPI).

    Nee d'une perte de 1 156 $ sur NQ pendant un FOMC. Devenir des rejetes
    -4,82 ATR sur ES contre un hasard a -0,06 +/- 0,08 : trente ecarts-types.
    C'est le seul chiffre qui n'a PAS bouge entre l'evaluation en serie et
    l'evaluation independante — aucune autre porte ne fermait ces signaux.
    """
    return lec["news_60m"]


@porte("L0_SESSION_BLOQUEE", "L0")
def _session(lec, etat, s):
    """Ouverture US, close + overnight, week-end, feries, demi-seances."""
    return lec["session_bloquee"]


@porte("L0_EOD_LOCKOUT", "L0")
def _eod(lec, etat, s):
    """Pas de nouvelle entree dans les dernieres minutes avant la cloture."""
    return lec["minute_utc"] >= (s["cloture_utc_min"] - s["marge_min"])


# --- famille C — CONDITIONS DE MARCHE ---------------------------------------
@porte("L0_VIX_REGIME", "L0")
def _vix(lec, etat, s):
    """DORMANTE sur ce lot : le VIX a plafonne a 22,01 sur 57 jours.

    Les codes 2 (>25) et 3 (>35) n'ont jamais existe. Le jour ou elle ferme
    quelque chose, ce sera la premiere fois — a lire comme tel, pas comme une
    anomalie.
    """
    v = lec["vix_regime"]
    return v is not None and v >= s["regime_max"]


# --- famille D — ETAT DU RISQUE ---------------------------------------------
@porte("L0_MAX_TRADES_JOUR", "L0")
def _max_trades(lec, etat, s):
    """OBSERVEE : ferme 41,6 % ES / 47,9 % NQ, et ses rejetes font MIEUX que
    les retenus (+0,196 / +0,253). Une porte qui coute se mesure avant de
    s'appliquer — meme quand la regle Douglas dit 5."""
    return etat["n_jour"] >= s["max"]


@porte("L0_STOP_JOURNALIER", "L0")
def _stop_jour(lec, etat, s):
    """INERTE PAR CONSTRUCTION en SIM, et c'est assume : -1 000 $ demande
    31,8 pertes d'affilee sur ES contre ~7 signaux par jour."""
    return etat["pnl_jour"] <= s["usd"]


@porte("L0_STOP_PROPFIRM", "L0")
def _stop_propfirm(lec, etat, s):
    """La vraie regle Douglas, en observation : combien de jours coupes."""
    return etat["pnl_jour"] <= s["usd"]


@porte("L0_COOLDOWN", "L0")
def _cooldown(lec, etat, s):
    """Jamais atteint en 15 min sur 57 jours — reste observee."""
    return lec["ts"] < etat["fin_cooldown"]


# --- famille E — ETAT DE L'EXECUTION ----------------------------------------
@porte("L0_POSITION_OUVERTE", "L0")
def _position(lec, etat, s):
    """Une position a la fois par instrument. **Bloque l'entree, ne bloque pas
    la mesure.**

    Ce que la regle « pas de nouveau signal tant que la barriere n'est pas
    atteinte » masquait : elle EST cette porte. L'exposer l'a rendue mesurable
    — 93,5 % ES / 94,0 % NQ, de loin la plus fermee du systeme, et elle
    n'apparaissait dans AUCUNE mesure jusqu'au 06/09.

    Tout signal qu'elle bloque est simule en TRADE FANTOME complet (triple
    barriere, couts), cf `V3/chaine.py`. Sans cela on saurait qu'elle ferme
    beaucoup, jamais ce qu'elle coute.
    """
    return lec["i"] <= etat["libre_a"]


def charger_seuils(chemin=SEUILS_YAML):
    """Rend (seuils, appliquees, absentes) depuis le YAML. Aucun defaut cache :
    une porte sans ligne YAML fait echouer `test_portes.py`."""
    import yaml
    with open(chemin, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    seuils, appliquees, absentes = {}, set(), set()
    for nom, d in (cfg.get("portes") or {}).items():
        mode = (d or {}).get("mode", "observee")
        seuils[nom] = (d or {}).get("seuils") or {}
        if mode == "appliquee":
            appliquees.add(nom)
        elif mode == "absente":
            absentes.add(nom)
    return seuils, appliquees, absentes
