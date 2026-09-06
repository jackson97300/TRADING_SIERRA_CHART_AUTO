"""Les feries CME, calcules — pas ecrits en dur.

`config/sessions.yaml` porte les REGLES en francais (« 3e lundi de janvier »).
Sans cette fonction, c'etait de la documentation : un fichier qu'on lit et qui
ne bloque rien. Le voici branche.

Des dates en dur se perimeraient au 1er janvier. Les regles, non.

CE QUE LE BOT FAIT CES JOURS-LA : aucun nouveau trade. Les TP/SL en cours
restent actifs — meme regle que les fenetres de session.

**Un ferie US n'est PAS une fermeture du CME** : le marche reste ouvert et
ferme plus tot, 13:00 ET au lieu de 16:00. Rien dans les donnees ne dit
« aujourd'hui c'est ferie » : le 19/06 avait 841 barres et 12 % du volume
median, ce qui ressemble a une panne de collecte alors que le marche
fonctionnait. Seul le calendrier le sait.

A VERIFIER CHAQUE ANNEE contre le calendrier officiel CME Equity Index : les
regles ci-dessous sont celles du marche US, mais le CME publie sa propre liste
et peut s'en ecarter (fermetures exceptionnelles, deuils nationaux).
"""

from __future__ import annotations

import datetime as _dt


def _nieme_jour(annee, mois, jour_semaine, n):
    """Le n-ieme `jour_semaine` du mois. `jour_semaine` : 0 = lundi."""
    d = _dt.date(annee, mois, 1)
    decalage = (jour_semaine - d.weekday()) % 7
    return d + _dt.timedelta(days=decalage + 7 * (n - 1))


def _dernier_jour(annee, mois, jour_semaine):
    """Le dernier `jour_semaine` du mois."""
    d = (_dt.date(annee, mois + 1, 1) if mois < 12
         else _dt.date(annee + 1, 1, 1)) - _dt.timedelta(days=1)
    return d - _dt.timedelta(days=(d.weekday() - jour_semaine) % 7)


def _observe(d):
    """Un ferie a date fixe tombant le week-end est observe un jour ouvre.

    Samedi -> vendredi, dimanche -> lundi. Convention des marches US.
    """
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def _paques(annee):
    """Dimanche de Paques, algorithme de Meeus/Jones/Butcher.

    Sert au Vendredi saint, seul jour ou le CME ferme vraiment.

    Une premiere version melangeait deux variantes de l'algorithme — elle
    donnait juste de 2021 a 2029 et tombait un JEUDI en 2030. Une date de
    Paques fausse reste une date plausible : rien ne la signale sauf le
    controle « le Vendredi saint tombe un vendredi », qui l'a attrapee.
    """
    a = annee % 19
    b, c = divmod(annee, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lg = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lg) // 451
    mois = (h + lg - 7 * m + 114) // 31
    jour = ((h + lg - 7 * m + 114) % 31) + 1
    return _dt.date(annee, mois, jour)


def feries(annee):
    """Rend {date: nom} pour l'annee. Les regles de `config/sessions.yaml`."""
    f = {
        _observe(_dt.date(annee, 1, 1)): "New Year's Day",
        _nieme_jour(annee, 1, 0, 3): "Martin Luther King Jr. Day",
        _nieme_jour(annee, 2, 0, 3): "Presidents Day",
        _paques(annee) - _dt.timedelta(days=2): "Good Friday",
        _dernier_jour(annee, 5, 0): "Memorial Day",
        _observe(_dt.date(annee, 6, 19)): "Juneteenth",
        _observe(_dt.date(annee, 7, 4)): "Independence Day",
        _nieme_jour(annee, 9, 0, 1): "Labor Day",
        _nieme_jour(annee, 11, 3, 4): "Thanksgiving",
        _observe(_dt.date(annee, 12, 25)): "Christmas Day",
    }
    # Demi-seances qui ne sont PAS des feries : les veilles et lendemains.
    # Le volume s'effondre apres 11:00 ET et la cloture arrive avant la Power
    # Hour : les objets de reference (IB etendue, VA du jour) n'ont pas le
    # temps de se former, et les declencheurs qui les lisent n'ont rien a lire.
    veille_4j = _dt.date(annee, 7, 3)
    if veille_4j.weekday() < 5:
        f.setdefault(veille_4j, "Veille d'Independence Day")
    lendemain_tg = _nieme_jour(annee, 11, 3, 4) + _dt.timedelta(days=1)
    f.setdefault(lendemain_tg, "Lendemain de Thanksgiving")
    veille_noel = _dt.date(annee, 12, 24)
    if veille_noel.weekday() < 5:
        f.setdefault(veille_noel, "Veille de Noel")
    # Un 1er janvier tombant un SAMEDI est observe le vendredi precedent —
    # c'est-a-dire le 31 decembre de l'annee d'AVANT. Sans cette ligne, le
    # ferie disparait : il n'est ni dans l'annee qui le nomme, ni dans celle
    # qui le porte. Le 31/12/2021 n'etait bloque par personne.
    report = _observe(_dt.date(annee + 1, 1, 1))
    if report.year == annee:
        f.setdefault(report, "New Year's Day")
    return f


def est_ferie(jour):
    """`jour` : date, datetime, ou chaine `YYYYMMDD` / `YYYY-MM-DD`.

    Rend le NOM du ferie, ou `None`. Le nom sert au journal : « bloque » sans
    dire lequel n'est pas verifiable.
    """
    d = _en_date(jour)
    return feries(d.year).get(d)


def _en_date(jour):
    if isinstance(jour, _dt.datetime):
        return jour.date()
    if isinstance(jour, _dt.date):
        return jour
    s = str(jour).strip().replace("-", "").replace("/", "")[:8]
    return _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
