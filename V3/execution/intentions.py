"""L'INTENTION D'ENTREE — l'objet qui manque entre la ligne PASSE et l'ordre.

Le premier pas d'EXEC (PLAN_ENTREE_EXEC.md §1 et §6, pas 1). Trois bots sont
morts parce que decision et execution ne partageaient pas le meme etat. Entre
la ligne PASSE (decision sur `t`) et l'ordre (acte sur `t+1`), il n'y avait
rien. Ce module cree l'objet du milieu : **immuable, idempotent, perissable**.

    python -X utf8 V3/execution/intentions.py [YYYYMMDD]

ZERO ORDRE, aucun import DTC, rien qui touche ce que la chaine DECIDE. Il LIT
les PASSE deja journalisees et ECRIT une intention par PASSE dans
`LOGS/intentions/intentions_<jour>.jsonl`. Un `test_structure`-like garde-fou
du test interdit tout jeton d'ordre dans ce fichier.

POURQUOI LE BRACKET TIENT SANS LE PRIX DE FILL
-----------------------------------------------
A l'emission (`t` clos), `open(t+1)` n'existe pas encore. Mais B-ATR est un
MULTIPLE d'ATR (`sl_prix = entree - sl_atr*atr*side`), donc en TICKS le bracket
ne depend PAS du prix d'entree : `sl_ticks = sl_atr*atr/tick`. On l'ecrit a
l'emission depuis l'`atr_barre` de la barre du signal ; EXEC posera le SL/TP
autour du fill reel a `t+1`. La seule donnee de marche necessaire est l'ATR.

IDEMPOTENCE (R8 applique a la decision)
----------------------------------------
Une intention emise ne se reecrit ni ne se supprime. Si un cycle ulterieur
re-ferme le signal, l'intention reste EMISE (EXEC la perimera, ou une ligne
`RETRO_BLOQUEE` viendra a cote — pour la lecture, jamais pour l'action). Un
journal qui change d'avis n'est pas un journal. `emettre` n'ecrit donc que si
le `snapshot_id` n'est pas deja la : relancable sans doublon.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import charger_jour                       # noqa: E402
from CORE.constants import get_tick_size                         # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs   # noqa: E402
from V3 import calendrier                                        # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min, dernier_jour  # noqa: E402
from V3.layers.L5_risque import barrieres as B                   # noqa: E402

_DOSSIER = "LOGS/intentions"
DUREE_BARRE_MS = 15 * 60 * 1000
# delai_max_s : nombre INVENTE (90 s). Regle souveraine du projet : aucun seuil
# sans distribution (PLAN §2 [AJOUT]). Ici il ne REFUSE rien — il n'est
# qu'ECRIT dans `au_plus_tard_ms`, pour batir la distribution latence en SIM.
# E3 (fraicheur) ne deviendra une porte qu'apres l'avoir mesure.
DELAI_MAX_S = 90


def chemin_du_jour(jour):
    return os.path.join(_DOSSIER, "intentions_%s.jsonl" % jour)


def _parse_snapshot(sid):
    """« NQ:13:S » -> (sym, i, side). Fail-loud : un id mal forme n'invente rien."""
    parts = str(sid).split(":")
    if len(parts) != 3 or parts[2] not in ("L", "S") or not parts[1].isdigit():
        raise ValueError("snapshot_id mal forme : %r" % sid)
    return parts[0], int(parts[1]), (1 if parts[2] == "L" else -1)


def intention(passe, atr, contrat, tick, s_batr, horloge_ms=None):
    """L'objet immuable depuis UNE ligne PASSE. Ne journalise pas, N'ORDONNE pas.

    `passe`   la ligne PASSE (ts, sym, hypothese, snapshot_id).
    `atr`     l'ATR-15m (`atr_barre`) de la barre du signal — la SEULE donnee
              de marche requise (cf docstring module : le bracket est en ticks).
    `contrat` le code trimestriel actif (`calendrier.contrat_actif`).
    `tick`    `get_tick_size(sym)`.
    `horloge_ms` l'instant d'emission reel (live) ; hors ligne, defaut =
              l'ouverture de `t+1`, l'instant ou l'ordre PARTIRAIT.
    """
    sym, _i, side = _parse_snapshot(passe["snapshot_id"])
    if sym != passe.get("sym"):
        raise ValueError("snapshot_id %s incoherent avec sym %r"
                         % (passe["snapshot_id"], passe.get("sym")))
    if atr is None or not (float(atr) > 0):
        raise ValueError("ATR invalide pour %s : %r" % (passe["snapshot_id"], atr))
    ts = int(passe["ts"])
    t1_open_ms = ts + DUREE_BARRE_MS                # t+1 ouvre a la barre suivante
    emission_ms = int(horloge_ms) if horloge_ms is not None else t1_open_ms
    seuils = s_batr["seuils"]
    return {
        "snapshot_id": passe["snapshot_id"],        # cle d'idempotence
        "sym": sym, "side": side,
        # `hypothese` = LABEL DE MODE (« ombre1 »), PAS la famille : campagne
        # le fige pour tous les signaux. La famille se retrouve par snapshot_id
        # (journal barrieres) — ne PAS s'en servir comme discriminant.
        "hypothese": passe.get("hypothese", "?"),
        "ts_signal": ts, "contrat": contrat,
        # entree : MKT a l'ouverture de t+1. `au_plus_tard_ms` = deadline de
        # fill ; DELAI_MAX_S est OBSERVE, pas applique (cf constante).
        "entree": {"type": "MKT", "ref": "open(t+1)",
                   "au_plus_tard_ms": t1_open_ms + DELAI_MAX_S * 1000},
        "barriere": {"sl_ticks": round(seuils["sl_atr"] * float(atr) / tick, 1),
                     "tp_ticks": round(seuils["tp_atr"] * float(atr) / tick, 1),
                     "expiration_barres": seuils["expiration_barres"]},
        "taille": 1,
        "emission_ms": emission_ms,
        "etat": "EMISE",
    }


def snapshot_ids_emis(chemin):
    """Les snapshot_id deja dans le journal du jour — set, pour l'idempotence."""
    out = set()
    if not os.path.exists(chemin):
        return out
    with open(chemin, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                try:
                    out.add(json.loads(ln)["snapshot_id"])
                except (ValueError, KeyError):
                    continue
    return out


def emettre(intent, chemin, deja=None):
    """Ecrit l'intention SI son snapshot_id n'est pas deja emis (idempotence).

    Rend True si ecrite, False si deja la. `deja` : le set des snapshot_id
    presents, fourni par l'appelant pour ne pas relire le fichier a chaque
    ligne ; absent -> relu du fichier.
    """
    if deja is None:
        deja = snapshot_ids_emis(chemin)
    if intent["snapshot_id"] in deja:
        return False
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(intent, ensure_ascii=False) + "\n")
    deja.add(intent["snapshot_id"])
    return True


def _atr_par_ts(jour, incidents):
    """{(sym, ts): atr_barre} — le df reconstruit COMME le rejeu (barrieres).

    Meme chauffe, memes recalculs : le mapping par TS est l'invariant « meme
    df que la chaine ». Un instrument illisible est note incident, jamais
    silencieusement absent.
    """
    from V3 import lecture
    out = {}
    for sym in ("ES", "NQ"):
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or len(df) < 6:
            continue
        brut = pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                         ignore_index=True)
        df = injecter_recalculs(brut, df, minutes=15)
        if lecture.verifier_colonnes(df, ("L0", "L5")):
            incidents.append(sym)
            continue
        a = pd.to_numeric(df["atr_barre"], errors="coerce")
        for ts, atr in zip(df["ts"], a):
            out[(sym, int(ts))] = float(atr) if pd.notna(atr) and atr > 0 else None
    return out


def courir(jour):
    """Rejoue les PASSE du jour -> intentions. OBSERVATION, ZERO ordre.

    Idempotent : relancable sans doublon. Le code retour porte l'AVEUGLEMENT
    (un ts introuvable = divergence entonnoir/df, incident), jamais le nombre
    de lignes — meme convention que `barrieres_du_jour`.
    """
    from CORE import entonnoir
    src = entonnoir.chemin_du_jour(jour)
    if not os.path.exists(src):
        print("  pas de journal entonnoir pour %s — rien a faire" % jour)
        return 0
    passes = []
    with open(src, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            o = json.loads(ln)
            # couche L0 : defense en profondeur — l'entonnoir principal n'a
            # qu'un producteur, mais une PASSE non-L0 ne doit jamais passer.
            if o.get("decision") == "PASSE" and o.get("couche") == "L0":
                passes.append(o)
    if not passes:
        print("  %s : aucun PASSE — aucune intention" % jour)
        return 0

    s = B.charger_seuils()
    chemin = chemin_du_jour(jour)
    deja = snapshot_ids_emis(chemin)
    contrat = calendrier.contrat_actif(jour)
    incidents = []
    atrs = _atr_par_ts(jour, incidents)
    n = 0
    for p in passes:
        cle = (p["sym"], int(p["ts"]))
        atr = atrs.get(cle)
        if atr is None:
            print("  ATTENTION %s ts %d introuvable/ATR nul — divergence"
                  " entonnoir/intentions (incident)" % (p["sym"], p["ts"]))
            incidents.append("%s:intention_ts" % p["sym"])
            continue
        # une ligne PASSE illisible n'arrete PAS le rejeu du jour : incident +
        # on continue (politique incident uniforme avec ts introuvable).
        try:
            intent = intention(p, atr, contrat, get_tick_size(p["sym"]), s["B-ATR"])
        except (ValueError, KeyError) as e:
            print("  ATTENTION PASSE illisible %r : %s" % (p.get("snapshot_id"), e))
            incidents.append("%s:intention_illisible" % p.get("sym", "?"))
            continue
        if emettre(intent, chemin, deja):
            n += 1
    print("  %s : %d intention(s) EMISE(s), contrat %s -> %s"
          % (jour, n, contrat, chemin))
    if incidents:
        print("  INCIDENT sur %s — code retour 1." % ", ".join(sorted(set(incidents))))
    return 1 if incidents else 0


def main():
    os.chdir(RACINE)
    jour = sys.argv[1] if len(sys.argv) > 1 else dernier_jour()
    if not jour:
        print("aucun fichier de donnees")
        return 1
    print("INTENTIONS — journee %s (une intention par PASSE, zero ordre)" % jour)
    return courir(jour)


if __name__ == "__main__":
    sys.exit(main())
