"""COUREUR LIVE — la brique qui fait passer « le bot a-t-il tourné en
`strict=True` ? » de NON à OUI.

    python -X utf8 V3/execution/coureur_live.py                # boucle
    python -X utf8 V3/execution/coureur_live.py --une-fois     # un cycle (test)
    python -X utf8 V3/execution/coureur_live.py --sync         # + scp du jour

Il boucle sur le fichier VIVANT de la journée de trading courante et fait, à
chaque cycle, les deux choses que le rejeu ne peut pas faire :

  BATTEMENT  à chaque nouvelle barre 15 min COMPLÈTE — cash comme nuit —
             l'état des portes passe dans `chaine.appliquer(strict=True,
             live={...})` et se journalise. C'est ce qui rend visibles la nuit
             (`L0_SESSION_BLOQUEE`), le VIX à zéro (`TROU_L0_VIX_REGIME`), le
             férié (`L0_FERIE_CME`) — et chaque trou, parce qu'en strict un
             trou BLOQUE.
  SIGNAUX    la détection L3 du rejeu, à l'identique (mêmes fonctions, mêmes
             colonnes injectées, même franchissement), sur le cash seulement —
             chaque signal NOUVEAU passe la chaîne stricte et se journalise
             une seule fois.

JOURNAL : `LOGS/entonnoir/live_<jour>.jsonl`, APPEND-ONLY — SÉPARÉ de
l'entonnoir officiel. Le rejeu de 21:01 reste LA mesure (il rejoue le jour
entier, déterministe) ; le journal live est la PREUVE que le jour a été couru
en strict, avec l'âge réel des barres. Les deux ne se mélangent jamais.

L'ÉTAT LIVE (six clés, chacune sourcée ou laissée en trou) vit dans
`etat_live.py` ; le lien VPS (scp, hôte et chemin hors du code) dans
`sync_vps.py`.

ATTENDU PRÉ-ENREGISTRÉ (écrit le 07/09 AVANT le premier run, règle 5) :
  - férié US en séance cash : chaque battement BLOQUE avec `L0_FERIE_CME` ;
  - tout battement porte `TROU_L0_DTC_DECONNECTE` et
    `TROU_L0_DATA_COLONNE_MORTE` tant que leurs sources n'existent pas ;
  - la nuit : `L0_SESSION_BLOQUEE` bloque, et `TROU_L0_VIX_REGIME` apparaît
    quand `vix_level == 0` ;
  - fichier non synchronisé depuis > 90 s : `L0_DATA_PERIMEE` bloque ;
  - aucun signal ni battement n'est journalisé deux fois (relance comprise).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.bot_terminal import agreger, charger_jour               # noqa: E402
from CORE.features import recalc                                  # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs    # noqa: E402
from V3 import chaine, lecture                                    # noqa: E402
from V3.campagne import (COLS_RECALC, MIN_JOURS_CHAUFFE,          # noqa: E402
                         chauffe_1min, signaux_l3)
from V3.execution.etat_live import etat_live                      # noqa: E402
from V3.execution.sync_vps import (config_vps, journee_courante,  # noqa: E402
                                   synchroniser)

MINUTES = 15
CYCLE_S = 60          # une barre par minute ; le scp de deux fichiers de
                      # 10-30 Mo interdit plus court sans rien apporter


def _dans_chaine(df, signaux, sym, hypothese, live, jour):
    """Passe `signaux` dans la chaîne stricte via un journal temporaire, rend
    les lignes émises. Un SEUL appel par lot : l'état de la chaîne est
    séquentiel (cf `chaine.appliquer`), l'appeler signal par signal fausserait
    les compteurs du jour."""
    tmp = "LOGS/entonnoir/.tmp_live_%s_%s.jsonl" % (jour, sym)
    if os.path.exists(tmp):
        os.remove(tmp)
    try:
        chaine.appliquer(signaux, df, sym, journal=tmp, hypothese=hypothese,
                         strict=True, live=live)
        if not os.path.exists(tmp):
            return []
        return [ln.strip() for ln in open(tmp, encoding="utf-8") if ln.strip()]
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _base_id(objet):
    """L'id sans le suffixe de classe (`:A`/`:O`/`:T`) — les trois formats de
    `snapshot_id` se réduisent au même « SYM:i:sens »."""
    sid = objet.get("snapshot_id") or ""
    return sid.rsplit(":", 1)[0] if sid.count(":") >= 3 else sid


def relire_journal(chemin):
    """Reprise après relance : ce qui est déjà journalisé ne l'est plus jamais.
    Rend (ids de signaux déjà vus, dernière barre battue par sym)."""
    vus, battues = set(), {}
    if not os.path.exists(chemin):
        return vus, battues
    for ln in open(chemin, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        o = json.loads(ln)
        base = _base_id(o)
        morceaux = base.split(":")
        if o.get("hypothese") == "battement":
            if len(morceaux) >= 2 and morceaux[1].lstrip("-").isdigit():
                battues[morceaux[0]] = max(battues.get(morceaux[0], -1),
                                           int(morceaux[1]))
        else:
            vus.add(base)
    return vus, battues


def _sans_barre_partielle_finale(agg):
    """La détection n'a pas le droit de lire une barre en cours d'écriture :
    un signal né d'une barre partielle disparaîtrait une fois la barre
    complète, et son id resterait. Les partielles EN MILIEU de journée
    restent : le rejeu les garde aussi, et `L0_DATA_INCOMPLETE` les juge."""
    while len(agg) and not bool(agg["barre_complete"].iloc[-1]):
        agg = agg.iloc[:-1]
    return agg.reset_index(drop=True)


def cycle(sym, jour, chauffe, vus, battues, chemin, sync=None):
    sync_rate = bool(sync) and not synchroniser(sym, jour, *sync)
    full_agg, full_1min = charger_jour(sym, jour, MINUTES, avec_1min=True,
                                       cash_only=False)
    if full_1min.empty:
        return "%s : pas de fichier pour %s" % (sym, jour)
    live = etat_live(sym, jour, full_1min)

    # --- battement : la derniere barre complete pas encore battue -----------
    nb_batt = 0
    complets = full_agg.index[full_agg["barre_complete"].fillna(False)]
    if len(complets):
        i = int(complets[-1])
        if i > battues.get(sym, -1):
            lignes = _dans_chaine(full_agg, [(i, 1)], sym, "battement",
                                  live, jour)
            with open(chemin, "a", encoding="utf-8") as fh:
                for ln in lignes:
                    fh.write(ln + "\n")
            battues[sym] = i
            nb_batt = len(lignes)

    # --- signaux : le cash, exactement comme le rejeu -----------------------
    nb_sig = 0
    cash_1min = full_1min[recalc.est_cash(full_1min["dt"])].reset_index(drop=True)
    if len(cash_1min) >= MINUTES * 6:
        cash_agg = _sans_barre_partielle_finale(agreger(cash_1min, MINUTES))
        if len(cash_agg) >= 6:
            brut = pd.concat(chauffe[sym] + [cash_1min[COLS_RECALC]],
                             ignore_index=True)
            cash_agg = injecter_recalculs(brut, cash_agg, minutes=MINUTES)
            manquantes = lecture.verifier_colonnes(cash_agg, ("L0", "L5"))
            if manquantes:
                # Meme diagnostic que le rejeu : un jour couru sur des
                # colonnes absentes est pire qu'un jour manque.
                return ("%s : COLONNES MANQUANTES %s — signaux NON detectes,"
                        " incident" % (sym, manquantes))
            sig, _comptes = signaux_l3(cash_agg)
            lignes = _dans_chaine(cash_agg, [(i, s) for i, s, _n in sig],
                                  sym, "ombre1-live", live, jour)
            paires = [(ln, _base_id(json.loads(ln))) for ln in lignes]
            nouvelles = [(ln, b) for ln, b in paires if b not in vus]
            with open(chemin, "a", encoding="utf-8") as fh:
                for ln, _b in nouvelles:
                    fh.write(ln + "\n")
            for _ln, b in nouvelles:
                vus.add(b)
            nb_sig = len(nouvelles)

    trous = [k for k, v in live.items() if v is None]
    return ("%s : age %s s%s, battement +%d ligne(s), signaux +%d, trous [%s]"
            % (sym, "?" if live["age_s"] is None else "%.0f" % live["age_s"],
               ", SYNC EN ECHEC — fichier local" if sync_rate else "",
               nb_batt, nb_sig, " ".join(trous)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jour", nargs="?", default=None)
    ap.add_argument("--une-fois", action="store_true")
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args()
    os.chdir(RACINE)

    jour = a.jour or journee_courante()
    chemin = "LOGS/entonnoir/live_%s.jsonl" % jour
    os.makedirs(os.path.dirname(chemin), exist_ok=True)

    sync = None
    if a.sync:
        hote, chemin_vps = config_vps()
        if hote and chemin_vps:
            sync = (hote, chemin_vps)
        else:
            print("--sync demandé mais VPS_HOTE/VPS_CHEMIN_DONNEES absents de "
                  "comptes.local.yaml — fichier local, age_s dira la vérité.")

    print("COUREUR LIVE — journée %s, strict=True, journal %s" % (jour, chemin))
    vus, battues = relire_journal(chemin)
    if vus or battues:
        print("  reprise : %d signal(aux) déjà vus, battements %s"
              % (len(vus), battues or "aucun"))
    chauffe = {sym: chauffe_1min(sym, jour) for sym in ("ES", "NQ")}
    for sym, ch in chauffe.items():
        if len(ch) < MIN_JOURS_CHAUFFE:
            print("  %s : CHAUFFE INSUFFISANTE (%d j < %d) — rvol_r rendra "
                  "NaN, H8p non évaluable" % (sym, len(ch), MIN_JOURS_CHAUFFE))

    while True:
        debut = time.time()
        for sym in ("ES", "NQ"):
            try:
                print("  " + cycle(sym, jour, chauffe, vus, battues, chemin,
                                   sync=sync))
            except KeyboardInterrupt:
                raise
            except Exception as e:                    # un cycle rate se dit,
                print("  %s : CYCLE EN ECHEC — %s: %s"     # jamais muet
                      % (sym, type(e).__name__, e))
        if a.une_fois:
            return 0
        time.sleep(max(1.0, CYCLE_S - (time.time() - debut)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\narrêt demandé — le journal reste, la reprise dédoublonne.")
        sys.exit(0)
