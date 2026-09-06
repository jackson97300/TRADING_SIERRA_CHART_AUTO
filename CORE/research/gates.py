"""Les portes L0 / L5, evaluees INDEPENDAMMENT et mesurees.

Ce module n'est pas un filtre qu'on applique et qu'on oublie. Ce qui a tue les
trois bots precedents n'est pas d'avoir refuse des trades, c'est de n'avoir
jamais su ce que les refuses seraient devenus. Chaque porte est journalisee avec
son motif, et `entonnoir.completer_devenir()` remplit vingt barres plus tard ce
que le trade refuse aurait rendu.

**Une porte dont les rejetes ont un devenir favorable est une porte a rouvrir —
et c'est mesure, pas debattu.**


POURQUOI INDEPENDAMMENT, ET PAS EN SERIE (Q7, corrigee le 06/09)
-----------------------------------------------------------------
La premiere version evaluait les portes en serie : le premier `if` qui fermait
donnait le motif, et les portes suivantes ne voyaient jamais ce signal.

Consequence, relevee par Fable : si `max_trades` est evaluee avant `news`, elle
« vole » les rejets de news — et le -4,82 ATR attribue a news etait mesure sur
ce que `max_trades` avait laisse passer. Tous les chiffres du premier tableau
dependaient d'un ordre arbitraire.

Le remede n'est pas de trouver le bon ordre : **il n'y en a pas.** Toutes les
portes sont evaluees sur chaque signal, une ligne de journal par porte qui
aurait bloque. La decision appliquee reste le ET des portes APPLIQUEES ;
l'attribution du devenir se fait par porte, sur tous les signaux qu'elle AURAIT
fermes, quel que soit le sort des autres.


DEUX CLASSES DE PORTES
-----------------------
APPLIQUEES : elles bloquent. N'y entre que ce dont l'effet protecteur est mesure,
             ou ce qui releve de la securite elementaire.
OBSERVEES  : elles journalisent « j'aurais bloque » sans agir. « Ouvrir une
             porte » est ce qui a tue decembre ; « la mettre en observation »
             est une mesure.
Source de verite : `V3/config/campagne.yaml`.


D'OU VIENNENT CES SEUILS
-------------------------
`CORE/bot1_v2/config.py`, recopies. Ils sont conformes au mindset Douglas la ou
ceux de MIA-IA-SYSTEM-2026 ne l'etaient pas : 5 trades par jour contre 50,
-200 $ contre -10 000 $. Ce n'etait pas un reglage different, c'etait une autre
philosophie — et c'est celle-la qui fait sauter les comptes.

Le stop journalier est a -1000 $ en SIM, decision Jackson du 06/09 : il faut
31,8 pertes d'affilee sur ES pour l'atteindre contre ~7 signaux par jour, donc
il est INERTE par construction et c'est assume. Le stop reel (-200 $) est
observe a cote.
"""

from __future__ import annotations

import pandas as pd

from CORE import entonnoir

# --- CORE/bot1_v2/config.py, recopies ---------------------------------------
MAX_TRADES_PAR_JOUR = 5           # ferme 36-43 % des signaux -> OBSERVEE
STOP_JOURNALIER_USD = -1000.0     # SIM. Inerte par construction, cf campagne.yaml
STOP_PROPFIRM_USD = -200.0        # la vraie regle Douglas -> OBSERVEE
COOLDOWN_APRES_CLOTURE_MIN = 60
COOLDOWN_APRES_PERTE_MIN = 90
MAX_HOLD_MINUTES = 45
EOD_LOCKOUT_MINUTES = 10
RVOL_ZSCORE_VETO = 3.0
SL_MIN_TICKS = {"ES": 6, "NQ": 10, "MGC": 12}

# Cout par trade, pour le veto « SL trop serre » : un SL qui ne couvre pas deux
# fois les frais est une position dont l'esperance est mangee avant d'exister.
COUT_DOLLARS = {"NQ": 2.82, "ES": 4.32}
VAL_POINT = {"NQ": 2.00, "ES": 5.00}          # micros MNQ / MES

APPLIQUEES = {
    "L0_NEWS",                    # -4,82 ATR sur ES : la meilleure porte
    "L0_SESSION_BLOQUEE",
    "L0_EOD_LOCKOUT",
    "L0_STOP_JOURNALIER",
    "L0_POSITION_OUVERTE",        # securite elementaire : une position a la fois
    "L5_VETO_GAMMA",              # -0,48 ATR sur ES
    "L5_VETO_RVOL_EXTREME",
    "L5_VETO_SL_SOUS_2X_FRAIS",
}
# Tout le reste est OBSERVE : MAX_TRADES_JOUR, COOLDOWN, STOP_PROPFIRM.


def _minutes(ts_ms):
    t = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
    return t.hour * 60 + t.minute


def _val(df, col, i):
    if col not in df.columns:
        return None
    v = pd.to_numeric(pd.Series([df[col].iloc[i]]), errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)


def _vrai(df, col, i):
    v = _val(df, col, i)
    return v is not None and v != 0


def evaluer_portes(df, i, sym, etat):
    """Toutes les portes sur une barre. Rend {nom: True si elle bloquerait}.

    `etat` porte ce qui ne se lit pas sur une barre isolee : nombre de trades du
    jour, P&L cumule, fin de cooldown, position ouverte.
    """
    m = _minutes(int(df["ts"].iloc[i]))
    p = {
        # --- L0 : a-t-on le droit de trader, la, maintenant ? --------------
        "L0_MAX_TRADES_JOUR": etat["n_jour"] >= MAX_TRADES_PAR_JOUR,
        "L0_STOP_JOURNALIER": etat["pnl_jour"] <= STOP_JOURNALIER_USD,
        "L0_STOP_PROPFIRM": etat["pnl_jour"] <= STOP_PROPFIRM_USD,
        "L0_COOLDOWN": int(df["ts"].iloc[i]) < etat["fin_cooldown"],
        "L0_POSITION_OUVERTE": bool(etat["position_ouverte"]),
        "L0_EOD_LOCKOUT": m >= (20 * 60 - EOD_LOCKOUT_MINUTES),
        "L0_NEWS": _vrai(df, "is_news_60m", i),
        "L0_SESSION_BLOQUEE": _vrai(df, "is_session_blocked", i),
        # --- L5 : combien, et ou est le stop ? ------------------------------
        "L5_VETO_GAMMA": _vrai(df, "gamma_block_long", i),
    }
    z = _val(df, "rvol_zscore", i)
    p["L5_VETO_RVOL_EXTREME"] = z is not None and abs(z) >= RVOL_ZSCORE_VETO

    # Le SL REEL est -1,0 ATR-5m, pas le plancher de config. Comparer le
    # plancher aux frais bloquait 100 % des signaux au premier essai :
    # arithmetiquement juste, semantiquement faux.
    atr = _val(df, "atr5", i) or 0.0
    if atr > 0:
        sl_usd = max(atr * VAL_POINT.get(sym, 5.0),
                     SL_MIN_TICKS.get(sym, 6) * 0.25 * VAL_POINT.get(sym, 5.0))
        p["L5_VETO_SL_SOUS_2X_FRAIS"] = sl_usd < 2 * COUT_DOLLARS.get(sym, 4.32)
    else:
        p["L5_VETO_SL_SOUS_2X_FRAIS"] = False
    return p


def appliquer(signaux, df, sym, journal=None, hypothese="?"):
    """Rend les indices qui passent toutes les portes APPLIQUEES.

    Journalise, pour chaque signal, une ligne par porte qui aurait bloque —
    appliquee comme observee. Le `snapshot_id` porte un suffixe `:A` ou `:O`
    pour les distinguer a la lecture.

    L'etat reste sequentiel (trades du jour, P&L, cooldown, position) : il ne se
    lit pas sur une barre isolee. Appeler cette fonction signal par signal
    remettrait le compteur a zero a chaque appel — c'est le bug du premier run
    du scrutateur, huit signaux retenus pour une limite de cinq.
    """
    passes = []
    jour_courant = None
    etat = {"n_jour": 0, "pnl_jour": 0.0, "fin_cooldown": -1,
            "position_ouverte": False}

    for i in signaux:
        jour = str(df["jour"].iloc[i])
        ts = int(df["ts"].iloc[i])
        if jour != jour_courant:
            jour_courant = jour
            etat.update(n_jour=0, pnl_jour=0.0, fin_cooldown=-1,
                        position_ouverte=False)

        portes = evaluer_portes(df, i, sym, etat)
        bloquantes = [k for k, v in portes.items() if v and k in APPLIQUEES]
        observees = [k for k, v in portes.items() if v and k not in APPLIQUEES]

        if journal is not None:
            for k in bloquantes + observees:
                entonnoir.journaliser(
                    ts=ts, sym=sym,
                    couche="L0" if k.startswith("L0") else "L5",
                    hypothese=hypothese, decision="BLOQUE", motif=k,
                    snapshot_id="%s:%d:%s" % (
                        sym, i, "A" if k in APPLIQUEES else "O"),
                    chemin=journal)
            if not bloquantes:
                entonnoir.journaliser(
                    ts=ts, sym=sym, couche="L0", hypothese=hypothese,
                    decision="PASSE", motif="",
                    snapshot_id="%s:%d" % (sym, i), chemin=journal)

        if not bloquantes:
            passes.append(i)
            etat["n_jour"] += 1
    return passes
