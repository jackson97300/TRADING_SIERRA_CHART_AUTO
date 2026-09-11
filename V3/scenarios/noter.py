"""SCÉNARIOS — le bouton NOTER (A6 bis) : la seule chose que la vitrine ÉCRIT,
et c'est dans `V3/journal_manuel/<jour>.md`. Le mécanisme de discipline, pas
une option : il fixe le schéma du journal même si Jackson ne trade pas.

    noter.ecrire(jour, {"heure_et": "11h07", "sym": "ES", "side": "long", ...}, etat)

Une ligne par clic, PRÉ-REMPLIE depuis l'état courant (heure, sym, scénario,
état, zone la plus proche) ; deux champs à Jackson : `side` et `pourquoi`
(dix mots). `HORS_SCENARIO = true` si le scénario ou la zone choisis ne sont
pas dans l'état courant (« autre ») — jamais interdit, toujours journalisé.
Ne fait jamais : écrire ailleurs, inférer le side, effacer une ligne.
`scenarios_visibles : oui` est posé dans le journal le premier jour où la
vitrine a tourné (A6) — deux populations pour le jour 61, jamais fusionnées.
"""

from __future__ import annotations

import os
import re
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

COLONNES = ("heure_et", "sym", "side", "prix_entree", "prix_sortie", "issue", "pourquoi",
            "scenario", "etat_scenario", "zone", "hors_scenario")
ENTETE = "| " + " | ".join(COLONNES) + " |\n|" + "---|" * len(COLONNES) + "\n"


def chemin(jour):
    return os.path.join(RACINE, "V3", "journal_manuel", "%s.md" % jour)


def gabarit(jour):
    return ("# JOURNAL MANUEL — %s/%s/%s (Jackson)\n\n"
            "*La pièce que la machine ne peut pas écrire. Une ligne par clic, dix mots de\n"
            "pourquoi, pas plus. Le jour 61 compare cette page à l'entonnoir : « le trader\n"
            "contre la machine ». Contrat du jour : à compléter.*\n\n"
            "## Les clics (sept champs, Fable — une ligne par trade ; scénario, état, zone, hors_scenario par NOTER)\n\n"
            "%s\nFin de journée — `ce_que_j_ai_vu` (une phrase) :\n\n"
            "`carte_visible` : à compléter\n\n`scenarios_visibles` : oui\n"
            % (jour[6:8], jour[4:6], jour[:4], ENTETE))


def _propre(v):
    return str(v if v is not None else "").replace("|", "/").replace("\n", " ").strip()


def ecrire(jour, champs, etat=None):
    """Ajoute UNE ligne au tableau des clics ; rend le dict écrit (avec
    `hors_scenario`). `etat` = `vitrine.etat_courant()` pour juger HORS_SCENARIO."""
    c = {k: _propre(champs.get(k)) for k in COLONNES if k != "hors_scenario"}
    if c["side"] not in ("long", "short", "plat"):
        raise ValueError("side doit etre long, short ou plat — jamais infere (%r)" % c["side"])
    c["pourquoi"] = " ".join(c["pourquoi"].split()[:10])
    hors = False
    if etat and c["sym"] in etat.get("sym", {}):
        e = etat["sym"][c["sym"]]
        connus_sc = {e.get("scenario_en_cours")} | {b.get("de") for b in e.get("bascules", [])}
        connues_z = {z["nom"] for z in e.get("zones", [])}
        hors = bool((c["scenario"] and c["scenario"] not in connus_sc) or (c["zone"] and c["zone"] not in connues_z))
    c["hors_scenario"] = "true" if hors else "false"
    p = chemin(jour)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(gabarit(jour))
    ligne = "| " + " | ".join(c[k] for k in COLONNES) + " |\n"
    t = open(p, encoding="utf-8").read()
    # la ligne s'insere a la fin du tableau des clics (apres la derniere ligne `|`
    # du premier tableau), jamais ailleurs ; rien n'est efface
    m = list(re.finditer(r"^\|.*\|\s*$", t, flags=re.M))
    if m:
        fin = m[0].end()
        for x in m[1:]:
            if x.start() <= fin + 2:
                fin = x.end()
            else:
                break
        t = t[:fin] + "\n" + ligne.rstrip("\n") + t[fin:]
    else:
        t += "\n" + ENTETE + ligne
    with open(p + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(t)
    os.replace(p + ".tmp", p)
    return c


def marquer_visibles(jour, oui=True):
    """Pose `scenarios_visibles : oui|non` (crée le journal au gabarit s'il manque)."""
    p = chemin(jour)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    t = open(p, encoding="utf-8").read() if os.path.exists(p) else gabarit(jour)
    val = "oui" if oui else "non"
    if re.search(r"`scenarios_visibles` *: *\S+", t):
        t = re.sub(r"(`scenarios_visibles` *: *)\S+", r"\g<1>" + val, t, count=1)
    else:
        t = t.rstrip("\n") + "\n\n`scenarios_visibles` : %s\n" % val
    with open(p + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(t)
    os.replace(p + ".tmp", p)
    return val


def visibles(jour):
    """'oui' | 'non' | None (absent) — lu par `pourquoi_plus`."""
    p = chemin(jour)
    if not os.path.exists(p):
        return None
    m = re.search(r"`scenarios_visibles` *: *(\S+)", open(p, encoding="utf-8").read())
    return m.group(1) if m else None


def lire(jour):
    """Les trades deja notes ce jour-la, dans l'ordre d'ecriture.

    Ajoute le 11/09 pour `mon_module` : Jackson journalise ses trades manuels
    et veut les RELIRE dans la journee, pas seulement les ecrire. Le lecteur
    vit ici, avec `ecrire` et `COLONNES` — le format a UN proprietaire ; un
    lecteur pose ailleurs se desynchronise a la premiere colonne ajoutee.
    Rend [] si le fichier n'existe pas, jamais une exception : une journee
    sans trade est le cas NORMAL d'une campagne en ombre.
    """
    p = chemin(jour)
    if not os.path.exists(p):
        return []
    out = []
    for m in re.finditer(r"^\|(.*)\|\s*$", open(p, encoding="utf-8").read(), flags=re.M):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != len(COLONNES):
            continue
        if cells[0] in ("heure_et", "") or set(cells[0]) <= {"-"}:
            continue                                  # l'entete et le trait
        out.append(dict(zip(COLONNES, cells)))
    return out
