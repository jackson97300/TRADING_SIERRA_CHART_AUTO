"""La chaine — evalue toutes les portes, applique celles qui doivent l'etre,
et SIMULE ce qu'elle refuse.

Ce qui a tue les trois bots precedents n'est pas d'avoir refuse des trades :
c'est de n'avoir jamais su ce que les refuses seraient devenus. Ce module
existe pour que « bloquer » et « mesurer ce que bloquer coute » soient le meme
geste.


LES TRADES FANTOMES — decision du 06/09
----------------------------------------
`L0_POSITION_OUVERTE` est de loin la porte la plus fermee du systeme — le
chiffre est dans `layers/L0_interrupteur/rapports/`, pas ici : un taux recopie
dans un commentaire survit au run qui l'a invalide. La bloquer ne suffit
pas : il faut savoir ce qu'elle COUTE. Chaque signal qu'elle bloque est donc
simule en trade fantome COMPLET — la triple barriere entiere, comme s'il avait
ete pris : entree a l'ouverture de t+1, TP +1,5 / SL -1,0 ATR, expiration a 20
barres, couts deduits. Il produit un `pnl_atr` exactement comme un trade reel.

Trois champs de plus, parce que c'est la qu'est l'information :
    meme_sens                le signal allait-il dans le sens de la position
                             ouverte, ou contre ?
    barres_depuis_entree     a quel moment de la vie de la position il arrive
    issue_position_ouverte   ce que la position en cours a finalement fait

Ce que ca permet de lire a soixante jours, et qu'aucune campagne n'a su :
  - le COUT de « une position par instrument » : somme des pnl fantomes. Si
    elle est nettement positive, le pyramidage devient une hypothese mesuree,
    pas une envie.
  - les signaux CONTRAIRES comme sortie : s'ils sont profitables ET que la
    position finit en SL dans ces cas-la, un signal contraire est une regle de
    sortie — la meilleure facon de trouver une sortie sans l'inventer.
  - les signaux MEME SENS comme renfort : s'ils arrivent tot et que la position
    finit en TP, c'est un argument pour le renfort ; tard, pour rien.

**Ca ne change rien a l'execution.** Une position par instrument reste
appliquee. On mesure, on ne pyramide pas : la decision viendra de la lecture.
"""

from __future__ import annotations

import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE import entonnoir                                        # noqa: E402
from CORE.research.hypothesis_runner import (                     # noqa: E402
    COUT_DOLLARS, VAL_POINT, triple_barriere)
from V3 import lecture, lieux, registre                           # noqa: E402
from V3.layers.L0_interrupteur import portes                      # noqa: E402
from V3.layers.L0_interrupteur import portes_donnees              # noqa: E402,F401
from V3.layers.L5_risque import vetos                             # noqa: E402  (enregistre L5)

# B1 (audit Fable) : source UNIQUE des couts = hypothesis_runner. Plus de copie ;
# meme construction que barrieres.py. Les nombres ne vivent qu'a UN endroit.
COUTS = {s: (COUT_DOLLARS[s], VAL_POINT[s]) for s in COUT_DOLLARS}
ETIQUETTES = {1: "TP", -1: "SL", 0: "EXPIRATION"}

_SEUILS, _APPLIQUEES, _ABSENTES = portes.charger_seuils()


def _id(sym, i, side):
    """L'identite d'une decision : instrument, barre ET SENS.

    Le sens fait partie de l'identite. Sans lui, un LONG et un SHORT sur la
    meme barre partagent le meme identifiant : deux lignes de journal
    indiscernables, et une mesure qui compte le devenir deux fois pour chacune
    — 312 rejets annonces pour 282 journalises sur ES.
    """
    return "%s:%d:%s" % (sym, i, "L" if side > 0 else "S")


def etat_neuf():
    """L'etat qui ne se lit pas sur une barre isolee.

    `n_jour` compte les trades PRIS, `n_signaux_jour` les signaux VUS. Les deux
    repondent a des questions differentes : avec une seule position a la fois,
    on n'atteint jamais le 15e trade, on atteint tres bien le 15e signal.
    """
    return {"n_jour": 0, "n_signaux_jour": 0, "pnl_jour": 0.0,
            "fin_cooldown": -1, "libre_a": -1, "side_ouvert": 0,
            "i_entree": -1, "issue_ouverte": None}


def appliquer(signaux, df, sym, journal=None, hypothese="?",
              strict=False, live=None):
    """Rend les indices qui passent toutes les portes APPLIQUEES.

    `signaux` : liste de (i, side) OU (i, side, famille), croissante en i.
    `side` vaut +1 ou -1 ; la famille par signal, si presente, l'emporte sur
    `hypothese` dans le journal (un 2-tuple garde le defaut — retro-compatible).

    Journalise une ligne par porte qui aurait bloque — appliquee comme observee,
    avec un suffixe `:A` ou `:O` sur le `snapshot_id`. Les signaux fermes par
    `L0_POSITION_OUVERTE` portent en plus leurs quatre champs de fantome.

    `strict` decide du sort des portes qui rendent `None` — « je ne peux pas
    repondre », faute de la donnee dont elles ont besoin. En LIVE il vaut True
    et un trou BLOQUE : une porte de qualite des donnees qui ne sait pas si la
    barre est fraiche ne doit pas laisser passer. Hors ligne il vaut False, le
    trou est journalise sous le motif `TROU_<porte>` et n'empeche rien : l'age
    d'une barre et l'etat du connecteur n'existent pas dans un backtest, et les
    compter comme des blocages rendrait toute mesure ininterpretable.

    L'etat reste sequentiel : appeler cette fonction signal par signal
    remettrait le compteur du jour a zero a chaque appel — c'est le bug du
    premier run du scrutateur, huit signaux retenus pour une limite de cinq.
    """
    passes, jour_courant, etat = [], None, etat_neuf()

    for sig in signaux:
        # (i, side) OU (i, side, famille) : la famille PAR SIGNAL l'emporte sur
        # le `hypothese` par defaut. Retro-compatible — un 2-tuple garde le
        # defaut. campagne passe la vraie famille pour ne pas figer « ombre1 »
        # sur soixante jours de journal (revue Fable 09/09).
        i, side = sig[0], sig[1]
        hyp = sig[2] if len(sig) > 2 else hypothese
        lec = lecture.lire(df, i, sym, live=live, side=side)   # A1 : L5 lit le sens
        if lec["jour"] != jour_courant:
            jour_courant, etat = lec["jour"], etat_neuf()
        # atr_source (brique 1, 09/09) : d'ou vient le metre du lieu, sur
        # CHAQUE ligne de signal — « veille » avant 11h00 se lit a part au
        # jour 61 (regle 15). « absent » quand le df n'a pas les recalculs :
        # le BATTEMENT live (full_agg, ~26 lignes/jour/sym, hypothese=
        # battement) et les df de test. Visible, jamais un None muet.
        src = {"atr_source": (str(df["atr_source"].iloc[i])
                              if "atr_source" in df.columns else "absent")}
        # LE LIEU (V1-lesson 4, 10/09) : sur chaque ligne du signal, lu par
        # personne — `lieux.py`. None porte toujours son motif.
        src.update(lieux.pour_signal(df, i, hyp, side))

        etat["n_signaux_jour"] += 1
        p = registre.evaluer_toutes(lec, etat, _SEUILS, _ABSENTES)
        # Un `None` n'est ni un blocage ni un feu vert : c'est un TROU.
        trous = [k for k, v in p.items() if v is None]
        bloquantes = [k for k, v in p.items() if v and k in _APPLIQUEES]
        observees = [k for k, v in p.items() if v and k not in _APPLIQUEES]
        if strict:
            bloquantes += [k for k in trous if k in _APPLIQUEES]

        if journal is not None:
            # Un trou promu bloquant (strict) ne se journalise QU'UNE fois,
            # sous TROU_<porte> — pas aussi sous le nom plein (audit 09/09 :
            # 210/624 lignes du jour 1 en double, pourquoi.py annoncait 204
            # blocages L0 pour 99 reels). Le COMPORTEMENT bloquant, lui, ne
            # change pas d'un bit : `bloquantes` reste augmentee des trous.
            for k in [x for x in bloquantes if x not in trous] + observees:
                extra = dict(src, **(_fantome(df, i, side, sym, etat)
                                     if k == "L0_POSITION_OUVERTE" else {}))
                entonnoir.journaliser(
                    ts=lec["ts"], sym=sym, couche=registre.REGISTRE[k]["couche"],
                    hypothese=hyp, decision="BLOQUE", motif=k,
                    snapshot_id="%s:%s" % (_id(sym, i, side),
                                           "A" if k in _APPLIQUEES else "O"),
                    chemin=journal, extra=extra)
            for k in trous:
                entonnoir.journaliser(
                    ts=lec["ts"], sym=sym, couche=registre.REGISTRE[k]["couche"],
                    hypothese=hyp, decision="BLOQUE",
                    motif="TROU_%s" % k,
                    snapshot_id="%s:T" % _id(sym, i, side), chemin=journal,
                    extra=src)
            if not bloquantes:
                entonnoir.journaliser(
                    ts=lec["ts"], sym=sym, couche="L0", hypothese=hyp,
                    decision="PASSE", motif="",
                    snapshot_id=_id(sym, i, side), chemin=journal, extra=src)

        if not bloquantes:
            passes.append(i)
            etat["n_jour"] += 1
            _ouvrir(df, i, side, sym, etat)
    return passes


def _metre(df):
    """Le df que CORE lit avec le MEME metre que L3 et L5 (brique 1, review
    10/09 R2) : `atr_barre` remplace par `atr_ref` quand il existe. Identique
    a partir de 11h00 (atr_ref == atr_barre partout ou celui-ci est fini) ;
    le matin, `triple_barriere` rend enfin un devenir — sans quoi un PASSE de
    9h45 n'ouvrait JAMAIS la position virtuelle et `L0_POSITION_OUVERTE`
    restait inerte jusqu'a 20 barres. Sans `atr_ref` (battement live sur
    full_agg, df de test) : le df tel quel, la ligne porte atr_source=absent."""
    return df.assign(atr_barre=df["atr_ref"]) if "atr_ref" in df.columns else df


def _ouvrir(df, i, side, sym, etat):
    """Ouvre la position virtuelle : elle occupe la place jusqu'a SA sortie.

    La sortie est celle de la triple barriere REELLE — TP, SL ou expiration —
    pas un forfait de 20 barres. Un trade qui touche son TP en trois barres
    libere la place en trois barres, et `POSITION_OUVERTE` ne doit pas fermer
    les dix-sept suivantes pour rien.
    """
    r = triple_barriere(_metre(df), i, side, COUTS[sym])
    if r is None:
        etat.update(libre_a=-1, side_ouvert=0, i_entree=-1, issue_ouverte=None)
        return
    etiquette, _pnl, i_sortie = r
    etat.update(libre_a=int(i_sortie), side_ouvert=int(side), i_entree=int(i),
                issue_ouverte=ETIQUETTES.get(etiquette, "?"))


def _fantome(df, i, side, sym, etat):
    """Le signal refuse, simule EN ENTIER. Rend les champs a journaliser.

    Pas seulement un devenir a 20 barres : la triple barriere complete, couts
    deduits, exactement comme un trade reel. Le runner sait deja le faire —
    c'est `triple_barriere()` appelee sur un signal qu'on n'execute pas.
    """
    r = triple_barriere(_metre(df), i, side, COUTS[sym])
    champs = {
        "fantome": True,
        "meme_sens": bool(side == etat["side_ouvert"]),
        "barres_depuis_entree": (int(i - etat["i_entree"])
                                 if etat["i_entree"] >= 0 else None),
        "issue_position_ouverte": etat["issue_ouverte"],
    }
    if r is not None:
        etiquette, pnl, i_sortie = r
        champs.update(fantome_issue=ETIQUETTES.get(etiquette, "?"),
                      fantome_pnl_atr=round(float(pnl), 4),
                      fantome_barres=int(i_sortie - i))
    return champs
