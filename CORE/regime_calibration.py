"""Seuils de regime calibres PAR SYMBOLE ET PAR FENETRE DE SESSION.

Source unique de verite : aucun seuil de decision ne doit etre code en dur
dans `regime_engine.py`.

Historique (audit 04/09/2026, INCIDENT_LOG #100)
------------------------------------------------
Le vote MODE comptait dix criteres. La mesure sur 23 794 barres reelles
(10 jours ES + NQ) a montre que **la moitie ne fonctionnait pas** :

  single_print_count > 100   ES max observe 84        -> 0.00 %
  vwap_slope_10 > 3.5        ES p75 = 0.29            -> 1.89 %
  sess_range_atr > 1.0       ES p25 = 1.77            -> 94.96 %
  poc_bar_dist > 15          ES p75 = 2               -> 0.35 %
  trend_day_probability<0.10 74.9 % de zeros          -> vote sur l'absence

Cause n°1 : tous ces seuils venaient d'un grid search sur NQ, applique tel
quel a ES. Or ES et NQ different d'un facteur ~5 (single_print_count :
ES p75=31, NQ p75=176). Les commentaires du code citaient les percentiles NQ.

Cause n°2, decouverte en recalibrant : **quatre criteres etaient des
horloges**, pas des mesures de regime. Mediane par heure UTC en seance :

  single_print_count   33  33  32  35   3   9   9   facteur x11.7
  vwap_slope_abs     0.55 0.84 0.60 0.33 2.31 0.56 0.24   x9.6
  bars_in_va            0   0   0   0   1   3   9   x9.0
  poc_bar_dist          3   3   2   2   2   1   2   x3.0
  trend_day_probability .35 .35 .35 .35 .35 .35 .35  x1.0  <- seul stable

`single_print_count` et `bars_in_va` sont des compteurs cumules depuis le
debut de session (reset net entre 16h50 et 17h00 UTC). Ils mesurent le temps
ecoulé autant que l'etat du marche. Recalibrer leurs seuils ne corrige rien :
la grandeur elle-meme est mal posee.

`trend_day_probability` a survecu au test d'horloge (x1.0) mais pas au test
de declenchement : la feature n'a que deux valeurs utiles en seance, 0.15 et
0.35, et 0.35 couvre 70.53 % des barres ES. Au-dessus de 0.30 le vote part
70.68 % du temps, au-dessus de 0.35 il ne part plus jamais. C'est un booleen
deguise en probabilite : aucun seuil ne le rend exploitable.

Decision : **le vote MODE ne retient que quatre etats Market Profile** —
IB breakout, day type, open type, profile shape. Tous categoriels, tous
verifies stables dans la journee. Les compteurs pourront revenir s'ils sont
un jour normalises par le temps ecoule dans la session : chantier separe, qui
suppose d'expliquer d'abord le reset observe a 13h ET.

Consequence : plus aucun seuil numerique dans le vote MODE, donc plus rien
qui puisse deriver en silence de ce cote. C'est le resultat recherche.

Garde-fou : `tools/check_regime_calibration.py` mesure les taux de
declenchement reels PAR FENETRE et refait le test d'horloge. A lancer apres
toute modification et periodiquement.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CALIB_VERSION = "v3_etats_20260904"
CALIB_SOURCE = "live_enriched_clean 10j (ES 11896 barres, NQ 11898)"

# Fenetres de session. La liquidite et la dynamique different trop entre la
# seance US et le reste pour partager des seuils : sur ES, |vwap_slope| a un
# p75 de 1.256 en seance contre 0.114 hors seance (facteur 11).
FENETRE_RTH = "rth"
FENETRE_HORS_RTH = "hors_rth"

# Position dans la Value Area, echelle [0,100]. Deja un pourcentage : pas de
# calibration par symbole necessaire.
RANGE_POS_HAUT = 70.0
RANGE_POS_BAS = 30.0

# VIX : regime de volatilite. Seuils traders standards pour indices US.
# Deux candidats ont ete ecartes :
#   - atr_regime_zscore_60d : jamais positif en live (ES max +0.27) alors que
#     les seuils etaient a +1.5 et +2.5. A noter : ce champ EST positif dans
#     les parquets V4 (max +6.90), ce qui suggere que la fenetre roulante 60j
#     n'est jamais amorcee dans l'enricher live. C'est un bug de la feature,
#     a traiter separement — pas une preuve qu'elle est inutile.
#   - sess_range_atr : cumul de session, croit avec l'heure (facteur 6.8).
# Le VIX est rempli a 100 %, stable dans la journee (0.49 pt d'ecart entre
# medianes horaires) et interpretable directement par un trader d'indices.
# NOTE : sur les 49 jours disponibles le VIX plafonne a 20.84. L'etat EXTREME
# est donc inatteignable en pratique — c'est un disjoncteur de crise, pas un
# discriminant quotidien. Assume tel quel.
VIX_LOW = 13.0
VIX_HIGH = 20.0
VIX_EXTREME = 30.0

# Seuils par symbole puis par fenetre : (seuil_trend, seuil_range).
# None desactive le vote correspondant.
#
# VIDE A CE JOUR — et c'est le resultat recherche. Les quatre criteres du
# vote MODE sont des categories Market Profile (IB, day type, open type,
# profile shape) : elles n'ont pas de seuil numerique, donc rien qui puisse
# deriver en silence. Le dernier candidat, `trend_day_probability`, a ete
# retire le 04/09 faute de seuil exploitable (deux valeurs utiles seulement,
# 70.53 % des barres ES a 0.35).
#
# La structure est conservee pour accueillir un futur critere calibre sans
# re-cabler les appelants. Tout ajout ici doit passer les deux controles de
# `tools/check_regime_calibration.py` : taux de declenchement 5-60 % PAR
# FENETRE, et absence de dependance a l'heure.
_SEUILS: dict[str, dict[str, dict[str, tuple[float | None, float | None]]]] = {
    "ES": {FENETRE_RTH: {}, FENETRE_HORS_RTH: {}},
    "NQ": {FENETRE_RTH: {}, FENETRE_HORS_RTH: {}},
}

# Repli quand le symbole est inconnu : ES, l'instrument trade au quotidien.
# Le repli est LOGUE (voir get_seuils) — un repli muet est un anti-pattern
# du projet.
_SYMBOLE_DEFAUT = "ES"

_ALIAS = {"SPX": "ES", "NDX": "NQ"}

# Symboles deja signales, pour ne pas inonder les logs a chaque barre.
_symboles_signales: set[str] = set()


def normaliser_symbole(symbole: str | None) -> str | None:
    """Ramene 'ESU26-CME', 'MES', 'es' a 'ES'. None si non reconnu."""
    if not symbole:
        return None
    s = str(symbole).upper().strip()
    # Micros d'abord : "MES" ne commence pas par "ES", pas de collision.
    if s.startswith("MES"):
        return "ES"
    if s.startswith("MNQ"):
        return "NQ"
    # Couvre "ES", "ESU26", "ESU26-CME", "ESZ26" et le rollover a venir.
    if s.startswith("ES"):
        return "ES"
    if s.startswith("NQ"):
        return "NQ"
    return _ALIAS.get(s)


def symbole_de_barre(bar: dict) -> str | None:
    """Extrait le symbole d'une barre. Les barres live exposent `sym` ('ES')
    et `contract` ('ESU26-CME') ; les parquets V4 n'ont ni l'un ni l'autre,
    d'ou l'obligation pour les builders de passer le symbole explicitement.
    """
    for cle in ("sym", "symbol", "instrument", "contract"):
        norm = normaliser_symbole(bar.get(cle))
        if norm:
            return norm
    return None


def fenetre_de_barre(bar: dict) -> str:
    """Fenetre de session de la barre.

    `is_cash_session` vaut True exactement sur les heures UTC 13 a 19,
    c'est-a-dire la seance US (verifie sur 23 794 barres). En son absence on
    retombe sur `session_segment == "us_cash"`, puis sur hors-RTH : le repli
    le plus conservateur, car les seuils RTH sont les plus permissifs.
    """
    v = bar.get("is_cash_session")
    if isinstance(v, bool):
        return FENETRE_RTH if v else FENETRE_HORS_RTH
    if str(bar.get("session_segment", "")).lower() == "us_cash":
        return FENETRE_RTH
    return FENETRE_HORS_RTH


def seuils_sont_par_defaut(symbole: str | None) -> bool:
    """True si l'appelant recevra les seuils de repli (symbole non calibre)."""
    return normaliser_symbole(symbole) not in _SEUILS


def get_seuils(symbole: str | None,
               fenetre: str = FENETRE_RTH) -> dict[str, tuple[float | None, float | None]]:
    """Seuils (trend, range) pour ce symbole et cette fenetre.

    Repli sur ES si le symbole est inconnu, avec un avertissement emis une
    seule fois par symbole. Un repli silencieux a deja coute cher a ce projet
    (INCIDENT #100 : les builders de dataset construisaient NQ avec les
    seuils ES sans que rien ne le signale).
    """
    norm = normaliser_symbole(symbole)
    if norm not in _SEUILS:
        cle = str(symbole)
        if cle not in _symboles_signales:
            _symboles_signales.add(cle)
            logger.warning(
                "regime_calibration : symbole %r non calibre, repli sur les "
                "seuils %s. Ajouter une entree dans _SEUILS si cet instrument "
                "doit etre trade.", symbole, _SYMBOLE_DEFAUT)
        norm = _SYMBOLE_DEFAUT
    par_fenetre = _SEUILS[norm]
    return par_fenetre.get(fenetre, par_fenetre[FENETRE_RTH])


def symboles_calibres() -> tuple[str, ...]:
    return tuple(_SEUILS)


def fenetres() -> tuple[str, ...]:
    return (FENETRE_RTH, FENETRE_HORS_RTH)


def criteres_calibres() -> tuple[str, ...]:
    return tuple(_SEUILS[_SYMBOLE_DEFAUT][FENETRE_RTH])
