"""Les feries calcules, verifies sur 2026 — et sur les annees ou la regle mord.

    python -X utf8 V3/tests/test_calendrier.py

Sans ces cas, `config/sessions.yaml` reste de la documentation : des regles en
francais que rien n'execute. Les quatre cas demandes a la revue du 06/09 sont
les quatre premiers.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.dirname(RACINE) not in sys.path:
    sys.path.insert(0, os.path.dirname(RACINE))

from V3 import calendrier                                     # noqa: E402

# (date, nom attendu ou None, pourquoi ce cas existe)
CAS = [
    # --- les quatre cas de la revue -------------------------------------
    ("20260907", "Labor Day", "1er lundi de septembre — lundi prochain"),
    ("20261126", "Thanksgiving", "4e jeudi de novembre"),
    ("20260703", "Independence Day",
     "4 juillet 2026 = SAMEDI, observe le vendredi 3. La veille et le ferie "
     "observe tombent le meme jour : le ferie gagne"),
    ("20260908", None, "mardi ordinaire — la porte doit laisser passer"),
    # --- le report week-end, dans les deux sens -------------------------
    ("20260101", "New Year's Day", "1er janvier 2026 = jeudi, pas de report"),
    ("20270101", "New Year's Day", "1er janvier 2027 = vendredi"),
    ("20220101", None, "1er janvier 2022 = samedi -> observe le 31/12/2021"),
    ("20211231", "New Year's Day", "...et c'est bien la veille qui porte"),
    ("20210704", None, "4 juillet 2021 = dimanche -> observe le lundi 5"),
    ("20210705", "Independence Day", "...le lundi suivant"),
    # --- les regles calculees -------------------------------------------
    ("20260119", "Martin Luther King Jr. Day", "3e lundi de janvier"),
    ("20260216", "Presidents Day", "3e lundi de fevrier"),
    ("20260403", "Good Friday", "Paques 2026 = 5 avril, vendredi saint le 3"),
    ("20270326", "Good Friday", "Paques 2027 = 28 mars"),
    ("20260525", "Memorial Day", "dernier lundi de mai"),
    ("20260619", "Juneteenth", "19 juin 2026 = vendredi"),
    ("20261225", "Christmas Day", "25 decembre 2026 = vendredi"),
    # --- demi-seances qui ne sont pas des feries ------------------------
    ("20261127", "Lendemain de Thanksgiving", "le vendredi d'apres"),
    ("20261224", "Veille de Noel", "24 decembre 2026 = jeudi"),
    # --- journees ordinaires, pour que la porte ne ferme pas tout -------
    ("20260903", None, "jeudi ordinaire"),
    ("20260615", None, "lundi ordinaire de juin"),
    ("20261120", None, "vendredi avant Thanksgiving"),
]

# (date, contrat attendu, pourquoi) — le roll est HUIT jours avant la 3e
# vendredi du mois d'echeance, et a partir du jour de roll INCLUS c'est le
# contrat suivant. Sans ces cas, le rollover du 10/09 reposait sur un tuple
# en dur dans campagne.py et une instruction manuelle.
CAS_CONTRAT = [
    ("20260907", "U26", "aujourd'hui — le fichier porte ESU26"),
    ("20260909", "U26", "veille du roll : l'ancien contrat tient"),
    ("20260910", "Z26", "jour du roll U26 -> Z26 (3e vendredi 18/09 - 8 j)"),
    ("20260311", "H26", "veille du roll de mars (3e vendredi 20/03, roll 12/03)"),
    ("20260312", "M26", "roll de mars"),
    ("20261209", "Z26", "veille du roll de decembre"),
    ("20261210", "H27", "roll de decembre : le contrat change d'ANNEE"),
]


def _controle_jour_semaine():
    """Les feries a regle « n-ieme lundi » doivent TOMBER un lundi.

    Un decalage d'index dans `_nieme_jour` se verrait ici et nulle part
    ailleurs : la date resterait plausible.
    """
    attendus = {"Martin Luther King Jr. Day": 0, "Presidents Day": 0,
                "Memorial Day": 0, "Labor Day": 0, "Thanksgiving": 3,
                "Good Friday": 4}
    e = []
    for annee in range(2021, 2031):
        for d, nom in calendrier.feries(annee).items():
            if nom in attendus and d.weekday() != attendus[nom]:
                e.append("%s %s : tombe un %s (attendu %s)"
                         % (annee, nom, d.weekday(), attendus[nom]))
    return e


def _controle_aucun_week_end():
    """Aucun ferie observe ne doit tomber un samedi ou un dimanche.

    Le marche est deja ferme le week-end : un ferie qui y tombe est un ferie
    mal reporte, et la journee ouvree correspondante n'est pas bloquee.
    """
    e = []
    for annee in range(2021, 2031):
        for d, nom in calendrier.feries(annee).items():
            if d.weekday() >= 5:
                e.append("%s %s : %s tombe un week-end" % (annee, nom, d))
    return e


def main():
    echecs = []
    for texte, attendu, pourquoi in CAS:
        obtenu = calendrier.est_ferie(texte)
        if obtenu != attendu:
            echecs.append("%s : attendu %r, obtenu %r  (%s)"
                          % (texte, attendu, obtenu, pourquoi))
    for texte, attendu, pourquoi in CAS_CONTRAT:
        obtenu = calendrier.contrat_actif(texte)
        if obtenu != attendu:
            echecs.append("contrat %s : attendu %s, obtenu %s  (%s)"
                          % (texte, attendu, obtenu, pourquoi))
    echecs += _controle_jour_semaine() + _controle_aucun_week_end()

    print("  calendrier — %d cas feries + %d cas contrat, plus 10 annees "
          "controlees en bloc" % (len(CAS), len(CAS_CONTRAT)))
    if echecs:
        print("  %d ECHEC(S) :" % len(echecs))
        for e in echecs:
            print("     %s" % e)
        return 1
    prochains = sorted(d for d in calendrier.feries(2026)
                       if d >= dt.date(2026, 9, 1))
    print("  OK — prochains jours sans trade : %s"
          % ", ".join("%s (%s)" % (d, calendrier.feries(2026)[d])
                      for d in prochains[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
