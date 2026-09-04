"""Garde-fou anti-derive du moteur de regime.

Pourquoi cet outil existe
-------------------------
Ce projet a connu six fois le meme scenario : un seuil fige dans le code
pendant que la feature sous-jacente change d'echelle, d'instrument ou de
definition. L'echec est toujours SILENCIEUX — pas d'exception, pas de NaN,
le critere vote simplement toujours pareil.

  #57    MIN_DELTA_SLOPE = 100            distribution reelle 0.001-0.05
  #99    range_pos seuils 70/30           echelle reelle [0,1] -> 0 % de SHORT
  #100   single_print_count > 100 (ES)    maximum observe 84   -> 0.00 %
  #100   sess_range_atr > 1.0             p25 = 1.77           -> 94.96 %
  #100   atr_regime_zscore_60d >= 1.5     jamais positif       -> 0 %
  #100   poc_bar_dist > 15 (ES)           p75 = 2              -> 0.35 %

Cet outil fait DEUX controles, parce que le premier ne suffit pas.

**Controle 1 — taux de declenchement, PAR FENETRE DE SESSION.**
Un vote qui part moins de 5 % ou plus de 60 % du temps n'informe pas. La
mesure doit etre faite separement en seance et hors seance : agreger les deux
masque le probleme. Lecon apprise a nos depens le 04/09 — une premiere version
de ce script mesurait sur 24 h, annoncait "tous les criteres dans la plage",
alors que deux votes partaient a ~70 % pendant les seules heures ou l'on trade.
Un garde-fou qui rassure a tort est pire que pas de garde-fou.

**Controle 2 — test d'horloge.**
Une feature cumulee depuis le debut de session (un compteur, un range) croit
mecaniquement avec l'heure. Elle mesure alors le temps ecoule plus que le
marche, et AUCUN seuil ne peut la sauver. On mesure sa mediane par heure UTC
en seance : si le rapport pic/creux depasse 2, c'est une horloge.

C'est ce controle qui a fait retirer quatre criteres du vote MODE le 04/09 :
single_print_count (x11.7), vwap_slope_abs (x9.6), bars_in_va (x9.0),
poc_bar_dist (x3.0). Un cinquieme, trend_day_probability, a passe le test
d'horloge mais echoue au controle 1 (deux valeurs utiles seulement, vote a
70.68 % sur ES) : il a ete retire aussi.

Certaines features doivent dependre de l'heure — l'Initial Balance se
construit entre 9h30 et 10h30 ET, c'est sa definition. Ces cas sont exemptes
UN PAR UN dans `_EXEMPTIONS_HORLOGE`, avec justification. On ne releve jamais
le seuil global pour faire passer un cas particulier.

Usage :
    python -X utf8 tools/check_regime_calibration.py
    python -X utf8 tools/check_regime_calibration.py --jours 30
    python -X utf8 tools/check_regime_calibration.py --recalibrer
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from CORE.regime_calibration import (  # noqa: E402
    CALIB_SOURCE, CALIB_VERSION, FENETRE_HORS_RTH, FENETRE_RTH,
    fenetre_de_barre, fenetres, get_seuils, symboles_calibres,
)

# Plage acceptable de declenchement d'un vote, par fenetre.
TAUX_MIN = 5.0
TAUX_MAX = 60.0

# Au-dela de ce rapport pic/creux entre medianes horaires, la feature est
# consideree comme une horloge : elle suit la session, pas le marche.
FACTEUR_HORLOGE = 2.0

# Critere calibre -> (cle de la barre, valeur absolue ?)
_SOURCE = {
    "trend_day_probability": ("trend_day_probability", False),
}

# Toutes les features lues par compute_regime, y compris celles sans seuil.
# Le test d'horloge doit couvrir CE QUE LE MOTEUR CONSOMME, pas seulement ce
# qui est calibre — sinon on ne detecte pas le probleme la ou il naitra.
_FEATURES_MOTEUR = [
    ("ib_range_ticks", False),
    ("day_type", False),
    ("open_type", False),
    ("profile_shape", False),
    ("vix_level", False),
    ("range_pos_va", False),
]

# Exemptions NOMMEES du test d'horloge. Certaines features DOIVENT dependre de
# l'heure : c'est leur definition, pas un defaut. On les exempte une par une
# avec justification, jamais en relevant le seuil global — meme regle que les
# exemptions de CORE/quality_validator.py.
_EXEMPTIONS_HORLOGE = {
    "ib_range_ticks":
        "l'Initial Balance se construit entre 9h30 et 10h30 ET puis se fige. "
        "Sa variation horaire est semantique. Le moteur n'en lit d'ailleurs "
        "que le booleen derive (formee / pas formee).",
}

# Features retirees du MODE le 04/09 : surveillees pour documenter qu'elles
# restent des horloges, et pour detecter le jour ou elles seraient corrigees.
_FEATURES_RETIREES = [
    ("trend_day_probability", False),
    ("single_print_count", False),
    ("vwap_slope_10", True),
    ("bars_in_va", False),
    ("poc_bar_dist", False),
    ("sess_range_atr", False),
]


def charger(dossier: str, symbole: str, jours: int) -> list[dict]:
    motif = os.path.join(dossier, symbole, "2026*.jsonl")
    barres: list[dict] = []
    for chemin in sorted(glob.glob(motif))[-jours:]:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    barres.append(json.loads(ligne))
    return barres


def valeurs(barres, cle: str, absolu: bool) -> list[float]:
    out = []
    for b in barres:
        v = b.get(cle)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
            if f == f:
                out.append(abs(f) if absolu else f)
    return out


def percentile(tries: list[float], p: float) -> float:
    return tries[int(p * (len(tries) - 1))]


def heure_utc(bar: dict):
    ts = bar.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    return dt.datetime.fromtimestamp(ts / 1000.0, dt.timezone.utc).hour


def facteur_horloge(barres, cle: str, absolu: bool):
    """Rapport pic/creux des medianes horaires en seance. None si indecidable."""
    par_heure = defaultdict(list)
    for b in barres:
        h = heure_utc(b)
        if h is None:
            continue
        v = b.get(cle)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
            if f == f:
                par_heure[h].append(abs(f) if absolu else f)
    medianes = []
    for h, vals in par_heure.items():
        if len(vals) < 20:
            continue
        vals.sort()
        m = vals[len(vals) // 2]
        if m > 0:
            medianes.append(m)
    if len(medianes) < 3:
        return None
    return max(medianes) / min(medianes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="DATA/live_enriched_clean")
    ap.add_argument("--jours", type=int, default=10)
    ap.add_argument("--recalibrer", action="store_true",
                    help="affiche les percentiles par symbole ET par fenetre, "
                         "a reporter dans CORE/regime_calibration.py")
    args = ap.parse_args()

    print("Calibration en vigueur : %s" % CALIB_VERSION)
    print("Source d'origine       : %s" % CALIB_SOURCE)
    print("Plage acceptable       : %.0f%% a %.0f%% par fenetre" % (TAUX_MIN, TAUX_MAX))
    print("Seuil horloge          : facteur pic/creux > %.1f\n" % FACTEUR_HORLOGE)

    alertes: list[str] = []
    propositions: dict = {}

    for symbole in symboles_calibres():
        toutes = charger(args.data, symbole, args.jours)
        if not toutes:
            print("[%s] aucune donnee dans %s" % (symbole, args.data))
            continue

        par_fenetre = {f: [] for f in fenetres()}
        for b in toutes:
            par_fenetre[fenetre_de_barre(b)].append(b)
        rth = par_fenetre[FENETRE_RTH]

        print("=" * 74)
        print("%s — %d barres (%d en seance, %d hors seance)"
              % (symbole, len(toutes), len(rth), len(par_fenetre[FENETRE_HORS_RTH])))
        print("=" * 74)

        # ---- Controle 1 : taux de declenchement par fenetre ----
        print("\n  CONTROLE 1 — taux de declenchement des votes")
        propositions[symbole] = {}
        for fen in fenetres():
            barres = par_fenetre[fen]
            if not barres:
                continue
            seuils = get_seuils(symbole, fen)
            propositions[symbole][fen] = {}
            for critere, (cle, absolu) in _SOURCE.items():
                vals = valeurs(barres, cle, absolu)
                if not vals:
                    print("    [%-8s] %-24s FEATURE ABSENTE" % (fen, critere))
                    continue
                s_trend, s_range = seuils.get(critere, (None, None))
                tries = sorted(vals)
                propositions[symbole][fen][critere] = (percentile(tries, 0.75),
                                                       percentile(tries, 0.25))
                if s_trend is None and s_range is None:
                    print("    [%-8s] %-24s vote desactive" % (fen, critere))
                    continue
                bouts = []
                for nom, seuil, sens in (("TREND", s_trend, "sup"),
                                         ("RANGE", s_range, "inf")):
                    if seuil is None:
                        bouts.append("%s OFF" % nom)
                        continue
                    if sens == "sup":
                        taux = 100.0 * sum(1 for v in vals if v > seuil) / len(vals)
                    else:
                        taux = 100.0 * sum(1 for v in vals if v < seuil) / len(vals)
                    marque = ""
                    if taux < TAUX_MIN or taux > TAUX_MAX:
                        marque = " HORS PLAGE"
                        alertes.append("%s/%s/%s vote %s : %.2f%% (attendu %.0f-%.0f%%)"
                                       % (symbole, fen, critere, nom, taux,
                                          TAUX_MIN, TAUX_MAX))
                    bouts.append("%s %.2f%%%s" % (nom, taux, marque))
                print("    [%-8s] %-24s %s" % (fen, critere, "  |  ".join(bouts)))

        # ---- Controle 2 : test d'horloge (en seance) ----
        print("\n  CONTROLE 2 — test d'horloge en seance (mediane par heure UTC)")
        for titre, liste, bloquant in (("consommees par le moteur", _FEATURES_MOTEUR, True),
                                       ("retirees le 04/09", _FEATURES_RETIREES, False)):
            print("    %s :" % titre)
            for cle, absolu in liste:
                f = facteur_horloge(rth, cle, absolu)
                if f is None:
                    print("      %-24s (pas assez de donnees)" % cle)
                    continue
                if f > FACTEUR_HORLOGE and cle in _EXEMPTIONS_HORLOGE:
                    etat = "HORLOGE (exemptee)"
                elif f > FACTEUR_HORLOGE:
                    etat = "HORLOGE"
                    if bloquant:
                        alertes.append("%s/%s : facteur horloge x%.1f — cette "
                                       "feature suit la session, pas le marche"
                                       % (symbole, cle, f))
                else:
                    etat = "stable"
                print("      %-24s x%-6.1f %s" % (cle, f, etat))
        print()

    if args.recalibrer:
        print("=" * 74)
        print("Percentiles p75/p25 par symbole et par fenetre")
        print("=" * 74)
        for symbole, fens in propositions.items():
            print('    "%s": {' % symbole)
            for fen, crits in fens.items():
                print('        %s: {' % ("FENETRE_RTH" if fen == FENETRE_RTH
                                         else "FENETRE_HORS_RTH"))
                for critere, (p75, p25) in crits.items():
                    print('            "%s": (%.4g, %.4g),' % (critere, p75, p25))
                print("        },")
            print("    },")
        print()

    if alertes:
        print("%d ALERTE(S) :" % len(alertes))
        for a in alertes:
            print("  - %s" % a)
        print("\nUn vote hors plage ne discrimine plus rien : recalibrer ou le "
              "desactiver.\nUne feature horloge ne peut PAS etre sauvee par un "
              "seuil : la normaliser par\nle temps ecoule dans la session, ou "
              "la retirer du moteur.")
        return 1

    print("Controles 1 et 2 passes. Rien a signaler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
