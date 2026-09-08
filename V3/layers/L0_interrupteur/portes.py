"""L0 — l'interrupteur : a-t-on le DROIT de trader, la, maintenant ?

L0 ne cherche pas de trade et n'a pas d'avis sur le marche. Elle dit si une
decision a le droit d'exister. Elle ne lit pas le sens du trade : les vetos
directionnels sont a L5.

Chaque porte est une fonction pure de trois lignes : elle lit une `lecture`
(une barre deja preparee) et un `etat`, elle rend True si elle bloque, `None`
si elle ne peut pas repondre. **Aucun seuil dans le code, et AUCUNE MESURE** —
les nombres vivent dans `seuils.yaml`, les mesures dans `rapports/`.

    from V3.layers.L0_interrupteur import portes, portes_donnees   # famille A
    from V3.layers.L5_risque import vetos
    from V3 import registre
    registre.evaluer_toutes(lecture, etat, seuils)

La famille A (qualite des donnees) est dans `portes_donnees.py`.


POURQUOI PAS DE CHIFFRE DANS CE FICHIER
----------------------------------------
La version precedente annoncait « POSITION_OUVERTE 93,5 % » dans cette
docstring, quand le CSV disait 72,5 %. Un chiffre recopie dans un commentaire
survit au run qui l'a invalide : il ne se met a jour que si quelqu'un y pense,
et personne n'y pense. Les mesures sont dans `rapports/`, datees, produites
par `mesure_57j.py`.
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

    Nee d'une perte de 1 156 $ sur NQ pendant un FOMC. C'est le seul chiffre du
    chantier qui n'a PAS bouge entre l'evaluation en serie et l'evaluation
    independante : aucune autre porte ne fermait ces signaux.
    """
    return lec["news_60m"]


@porte("L0_SESSION_BLOQUEE", "L0")
def _session(lec, etat, s):
    """Ouverture US, close + overnight, week-end. Cf `CORE/eco_calendar.py`."""
    return lec["session_bloquee"]


@porte("L0_FERIE_CME", "L0")
def _ferie(lec, etat, s):
    """Ferie ou demi-seance : le marche est OUVERT et ferme plus tot.

    Rien dans les donnees ne dit « aujourd'hui c'est ferie » : le 19/06 avait
    841 barres et 12 % du volume median, ce qui ressemble a une panne de
    collecte alors que le marche fonctionnait. Seul le calendrier le sait —
    regles dans `config/sessions.yaml`, calculees par `V3/calendrier.py`.

    Le calendrier repond TOUJOURS : `est_ferie` rend le nom du ferie, ou `None`
    quand le jour est ordinaire. Cette porte n'a donc pas de trou possible —
    une premiere version lisait le `None` de « jour ordinaire » comme « je ne
    sais pas », et transformait chaque jeudi banal en information manquante.
    """
    return lec["ferie"] is not None


@porte("L0_ROLLOVER", "L0")
def _rollover(lec, etat, s):
    """Bascule de contrat en cours : les niveaux de la veille ne valent plus."""
    r = lec["rollover"]
    return None if r is None else bool(r)


@porte("L0_PREMIERE_BARRE", "L0")
def _premiere_barre(lec, etat, s):
    """Aucune decision avant que le regime soit lisible.

    Le regime se lit sur la largeur de l'IB et le signe de la distance au HVL :
    les deux demandent quelques barres. Decider a la premiere, c'est decider
    sans contexte.
    """
    return lec["rang_du_jour"] < s["rang_min"]


@porte("L0_EOD_LOCKOUT", "L0")
def _eod(lec, etat, s):
    """Pas de nouvelle entree dans les dernieres minutes avant la cloture.

    REDONDANTE avec `SESSION_BLOQUEE` — pas inerte. La distinction compte :
    une porte inerte ne protege de rien, une porte redondante protege deja,
    par une autre. On la garde comme filet si le calendrier tombe.
    """
    return lec["minute_utc"] >= (s["cloture_utc_min"] - s["marge_min"])


# --- famille C — CONDITIONS DE MARCHE ---------------------------------------
@porte("L0_VIX_REGIME", "L0")
def _vix(lec, etat, s):
    """DORMANTE sur ce lot : le VIX a plafonne a 22,01 sur 57 jours.

    APPLIQUEE quand meme : elle dort, elle ne coute rien, et le jour ou elle se
    reveille c'est de la securite elementaire. Ce jour-la sera le PREMIER — a
    lire comme tel, pas comme une anomalie.

    Elle rendait `False` quand la colonne etait absente : un FEU VERT INVENTE,
    exactement ce qu'on interdit ailleurs. Et la colonne l'etait — `vix_regime`
    ne survivait pas a l'agregation. Son verdict « INERTE, le VIX a plafonne a
    22,01 » etait donc faux : elle etait inerte parce qu'elle ne lisait rien.
    Troisieme colonne perdue au resample le meme jour, trouvee par
    `lecture.verifier_colonnes` a son premier lancement.
    """
    v = lec["vix_regime"]
    return None if v is None else v >= s["regime_max"]


@porte("L0_REGIME_INDETERMINE", "L0")
def _regime(lec, etat, s):
    """Zone morte autour du HVL : ni au-dessus, ni en dessous.

    Le HVL est un REGIME, pas un lieu. Sans zone morte, le regime bascule 10,2
    fois par jour ; avec 1,0 ATR, 1,8 fois. Un regime qui change dix fois par
    jour n'est pas un regime.
    """
    d = lec["dist_hvl_atr"]
    return None if d is None else abs(d) < s["zone_morte_atr"]


# --- famille D — ETAT DU RISQUE ---------------------------------------------
# DEUX COMPTEURS, pas un. `MAX_TRADES` lisait `n_jour`, incremente aux seuls
# signaux RETENUS : elle comptait donc les TRADES PRIS. Quand elle fermait
# 40 %, la position ouverte n'etait pas suivie, beaucoup plus de signaux
# passaient, et le compteur montait vite. Sa definition n'a pas change — son
# CONTEXTE si. Mais « combien de trades ai-je pris » et « le combientieme
# signal est-ce » sont deux questions differentes, et chacune merite son nom.
@porte("L0_MAX_TRADES_PRIS", "L0")
def _max_trades(lec, etat, s):
    """Combien de trades EXECUTES aujourd'hui."""
    return etat["n_jour"] >= s["max"]


@porte("L0_RANG_DU_SIGNAL", "L0")
def _rang(lec, etat, s):
    """Le combientieme signal de la journee, execute ou non.

    Le 15e signal vaut-il moins que le 3e ? La question ne se pose pas avec le
    compteur de trades : quand une seule position tient a la fois, on n'atteint
    jamais le 15e trade. On atteint tres bien le 15e signal.
    """
    return etat["n_signaux_jour"] >= s["max"]


@porte("L0_STOP_JOURNALIER", "L0")
def _stop_jour(lec, etat, s):
    """Garde-fou SIM — PEU PROBABLE sur NQ (4,9 SL de 1 ATR), improbable
    sur ES (13,2), MESURABLE : jamais « inerte par construction » (revue
    08/09, A2). Une seance fermee dessus se lit A PART (LECTURE regle 16)."""
    return etat["pnl_jour"] <= s["usd"]


@porte("L0_STOP_PROPFIRM", "L0")
def _stop_propfirm(lec, etat, s):
    """La vraie regle Douglas, en observation."""
    return etat["pnl_jour"] <= s["usd"]


@porte("L0_COOLDOWN", "L0")
def _cooldown(lec, etat, s):
    """Delai apres un trade. 90/60 min, pas les 3/5 min de janvier : en barres
    de 15 min, trois minutes ne sautent meme pas une barre."""
    return lec["ts"] < etat["fin_cooldown"]


# --- famille E — ETAT DE L'EXECUTION ----------------------------------------
@porte("L0_POSITION_OUVERTE", "L0")
def _position(lec, etat, s):
    """Une position a la fois par instrument. **Bloque l'entree, ne bloque pas
    la mesure.**

    Ce que la regle « pas de nouveau signal tant que la barriere n'est pas
    atteinte » masquait : elle EST cette porte. L'exposer l'a rendue mesurable.
    Tout signal qu'elle bloque est simule en TRADE FANTOME complet — triple
    barriere, couts deduits — cf `V3/chaine.py`. Sans cela on saurait qu'elle
    ferme beaucoup, jamais ce qu'elle coute.
    """
    return lec["i"] <= etat["libre_a"]


@porte("L0_CONTRAT_INACTIF", "L0")
def _contrat(lec, etat, s):
    """Le contrat du JSONL doit etre celui du compte."""
    c = lec["contrat_actif"]
    return None if c is None else not c


@porte("L0_DTC_DECONNECTE", "L0")
def _dtc(lec, etat, s):
    """Connecteur tombe : repli PAPER, jamais d'ordre a l'aveugle."""
    d = lec["dtc_connecte"]
    return None if d is None else not d


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
