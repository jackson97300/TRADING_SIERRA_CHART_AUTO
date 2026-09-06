"""Les gates L0 / L5 de Bot 1 v2, appliques a des signaux et **mesures**.

Ce que ce module n'est pas : un filtre qu'on applique et qu'on oublie. Ce qui a
tue les trois bots precedents n'est pas d'avoir refuse des trades, c'est de
n'avoir jamais su ce que les refuses seraient devenus. Chaque blocage est donc
journalise dans `CORE/entonnoir.py` avec son motif, et `completer_devenir()`
remplit vingt barres plus tard ce que le trade refuse aurait rendu.

**Une porte dont les rejetes ont un devenir favorable est une porte a rouvrir —
et c'est mesure, pas debattu.**


D'OU VIENNENT CES GATES
------------------------
`CORE/bot1_v2/config.py`, recopies tels quels. Ils sont notablement meilleurs que
ceux de MIA-IA-SYSTEM-2026 (`launch_production_CLEAN_v2.py`), et surtout ils sont
**conformes au mindset Douglas** au lieu de le contredire :

    | | Bot 1 v2 | V1 |
    |---|---|---|
    | trades par jour | **5** | 50 |
    | stop journalier | **-200 $** | -10 000 $ |
    | drawdown max | — | 50 % |

Cinq trades et -200 $ sont exactement ce que la memoire Douglas prescrit. V1
autorisait dix fois plus de trades et cinquante fois plus de perte : ce n'etait
pas un reglage different, c'etait une autre philosophie, et c'est celle qui fait
sauter les comptes.


CE QUE LA PREMIERE MESURE DIT (06/09, 40 jours, signaux de H3 et H7)
--------------------------------------------------------------------
    ES : 603 signaux bruts -> 271 passent   (55 % bloques)
    NQ : 701 signaux bruts -> 288 passent   (59 % bloques)

    L0_MAX_TRADES_JOUR   739 blocages
    L0_EOD_LOCKOUT         6
    tous les vetos L5       0

**La limite de cinq trades par jour ecarte 57 % des signaux a elle seule.**
C'est de tres loin la porte la plus fermee du systeme, et on ignore encore si
elle ecarte les mauvais trades ou les bons — c'est exactement la question que
 repondra, en mode ombre, sur les jours a venir.

Aucun veto L5 ne se declenche : ni rvol extreme, ni gamma, ni SL sous les frais.
Sur ce lot ils sont inactifs — a savoir avant de croire qu'ils protegent.

UNE LIMITE HONNETE DE CE MODULE
--------------------------------
 n'est jamais mis a jour dans la boucle : le P&L d'un trade n'est connu
qu'apres sa cloture, donc apres le gate suivant. ** ne peut
donc pas se declencher ici, et n'a pas ete teste.** Le brancher demande de boucler
gate -> execution -> resultat, ce qui est le travail du mode ombre, pas d'une
mesure sur historique. Ecrit pour que personne ne croie ce gate valide.


UN DEFAUT CONSERVE, ET SIGNALE
-------------------------------
`NEAR_LEVEL_MAX_TICKS` vaut 8 ticks sur ES et 16 sur NQ. En ATR-5m : **0,71 ATR
sur ES contre 0,20 sur NQ** — le meme concept « pres d'un niveau » recouvre deux
realites, facteur 3,5. C'est la meme maladie que les seuils d'`edge_discovery`
(facteur 17), en plus benin. Les valeurs sont conservees telles quelles ici :
elles sont recopiees, pas corrigees, et l'entonnoir dira ce qu'elles coutent.
Les corriger avant de les avoir mesurees serait refaire l'erreur inverse.
"""

from __future__ import annotations

import pandas as pd

from CORE import entonnoir

# --- CORE/bot1_v2/config.py, recopies ---------------------------------------
MAX_TRADES_PAR_JOUR = 5           # MAX_TRADES_PER_DAY
STOP_JOURNALIER_USD = -200.0      # DAILY_STOP_LOSS_USD
COOLDOWN_APRES_CLOTURE_MIN = 60   # COOLDOWN_POST_CLOSE_MIN
COOLDOWN_APRES_PERTE_MIN = 90     # COOLDOWN_POST_LOSS_MIN (plus strict apres SL)
MAX_HOLD_MINUTES = 45             # MAX_HOLD_MINUTES
EOD_LOCKOUT_MINUTES = 10          # EOD_LOCKOUT_MINUTES
NEWS_LOCKOUT_MIN = 5              # NEWS_LOCKOUT_BEFORE_MIN / AFTER_MIN
RVOL_ZSCORE_VETO = 3.0            # RVOL_ZSCORE_VETO_THRESHOLD
SL_MIN_TICKS = {"ES": 6, "NQ": 10, "MGC": 12}
NEAR_LEVEL_MAX_TICKS = {"ES": 8, "NQ": 16, "MGC": 8}

# Cout par trade, pour le veto « SL trop serre » : un SL qui ne couvre pas deux
# fois les frais est une position dont l'esperance est mangee avant d'exister.
COUT_DOLLARS = {"NQ": 2.82, "ES": 4.32}
VAL_POINT = {"NQ": 2.00, "ES": 5.00}          # micros


def _minutes(ts_ms):
    t = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
    return t.hour * 60 + t.minute


def appliquer(signaux, df, sym, journal=None, hypothese="?"):
    """Passe une liste de signaux dans les gates, dans l'ordre chronologique.

    `signaux` : indices de barres, croissants. `df` : les barres 5 min.
    Rend la liste des indices qui PASSENT, et journalise tous les BLOQUE avec
    leur motif — c'est la sortie qui compte.

    Les gates sont sequentiels par nature : le nombre de trades du jour, le P&L
    cumule et l'heure du dernier trade ne se lisent pas sur une barre isolee.
    D'ou une boucle, et non un masque.
    """
    passes = []
    jour_courant, n_jour, pnl_jour = None, 0, 0.0
    fin_cooldown = -1

    for i in signaux:
        jour = str(df["jour"].iloc[i])
        ts = int(df["ts"].iloc[i])
        if jour != jour_courant:                       # remise a zero quotidienne
            jour_courant, n_jour, pnl_jour, fin_cooldown = jour, 0, 0.0, -1

        motif = None
        m = _minutes(ts)

        # --- L0 : les blocages en serie ------------------------------------
        if n_jour >= MAX_TRADES_PAR_JOUR:
            motif = "L0_MAX_TRADES_JOUR"
        elif pnl_jour <= STOP_JOURNALIER_USD:
            motif = "L0_STOP_JOURNALIER"
        elif ts < fin_cooldown:
            motif = "L0_COOLDOWN"
        elif m >= (20 * 60 - EOD_LOCKOUT_MINUTES):     # 16:00 ET = 20:00 UTC ete
            motif = "L0_EOD_LOCKOUT"
        elif _vrai(df, "is_news_60m", i):
            motif = "L0_NEWS"
        elif _vrai(df, "is_session_blocked", i):
            motif = "L0_SESSION_BLOQUEE"

        # --- L5 : les vetos de risque ---------------------------------------
        if motif is None:
            z = _val(df, "rvol_zscore", i)
            if z is not None and abs(z) >= RVOL_ZSCORE_VETO:
                motif = "L5_VETO_RVOL_EXTREME"
            elif _vrai(df, "gamma_block_long", i):
                motif = "L5_VETO_GAMMA"
            else:
                # Le SL REEL de la mission est -1,0 ATR-5m, pas le plancher de
                # config `SL_MIN_TICKS`. Comparer le plancher aux frais bloquait
                # 100 % des signaux — arithmetiquement juste, semantiquement faux :
                # 6 ticks ES = 7,50 $ contre 8,64 $ de frais doubles, alors que
                # 1,0 ATR-5m vaut 14,15 $. Bug attrape par le test empirique.
                atr = _val(df, "atr5", i) or 0.0
                if atr > 0:
                    sl_usd = atr * VAL_POINT.get(sym, 5.0)     # 1,0 ATR-5m, en $
                    plancher = SL_MIN_TICKS.get(sym, 6) * 0.25 * VAL_POINT.get(sym, 5.0)
                    sl_usd = max(sl_usd, plancher)             # le plancher est un MINIMUM
                    if sl_usd < 2 * COUT_DOLLARS.get(sym, 4.32):
                        motif = "L5_VETO_SL_SOUS_2X_FRAIS"

        if journal is not None:
            entonnoir.journaliser(
                ts=ts, sym=sym, couche="L0" if (motif or "").startswith("L0") else
                ("L5" if motif else "L5"),
                hypothese=hypothese,
                decision="BLOQUE" if motif else "PASSE",
                motif=motif or "", snapshot_id="%s:%d" % (sym, i),
                chemin=journal)

        if motif is None:
            passes.append(i)
            n_jour += 1
    return passes


def _val(df, col, i):
    if col not in df.columns:
        return None
    v = pd.to_numeric(pd.Series([df[col].iloc[i]]), errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)


def _vrai(df, col, i):
    v = _val(df, col, i)
    return v is not None and v != 0
