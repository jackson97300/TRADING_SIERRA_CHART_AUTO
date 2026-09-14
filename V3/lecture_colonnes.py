"""Les NOMS de colonnes et les convertisseurs — ce que `lecture.lire()` lit.

Sorti de `lecture.py` le 10/09 (passe lecture, brief Fable : R3 + A1 + B3),
qui etait au plafond de 300 lignes. AUCUN changement de comportement : les
memes noms, les memes fonctions, re-exportes par `lecture` — `lecture.val`,
`lecture.verifier_colonnes`, `lecture.SOURCES_DECLAREES` restent le chemin
des appelants.

Ici vivent : les colonnes REQUISES par couche (un chainon rompu entre le JSONL
et la decision est SILENCIEUX — `verifier_colonnes` le dit), les provenances
auto-declarees (`SOURCES_DECLAREES` : une colonne gouvernee par une `_source`
qui dit « proxy » se lit None, jamais un faux feu vert), et les trois lectures
d'une cellule : `val` (flottant ou None), `vrai` (bool), `_texte` (str ou None).
"""

from __future__ import annotations

import pandas as pd

# Les colonnes dont les couches DEPENDENT. Une absente n'est pas une donnee
# manquante qu'on lira `None` : c'est un chainon rompu entre le JSONL et la
# decision, et il est SILENCIEUX.
#
# Deux fois le 06/09, une colonne presente dans les donnees s'est perdue a
# l'agregation sans que rien ne le signale :
#   - `data_quality_flag` — la porte L0_DATA_INSTABLE aurait ferme la seance
#     entiere en live, en repondant « je ne sais pas » sur chaque barre ;
#   - `dist_vwap_w` — `biais()` rendait 0 EN PERMANENCE, donc B1 n'existait
#     pas, et aucune mesure ne consultait sa sortie pour s'en apercevoir.
#
# `test_rien_de_cache` protege les portes contre ce genre de derive ; rien ne
# protegeait les COLONNES. C'est ce que fait `verifier_colonnes`.
REQUISES = {
    "L0": ("ts", "high", "low", "close", "atr_barre", "data_quality_flag",
           "window_version", "barre_complete", "is_news_60m",
           "is_session_blocked", "vix_regime", "dist_mq_hvl"),
    "L1": ("dist_vwap_w", "dist_cur_vah", "dist_cur_val", "dist_cur_vpoc",
           "dist_prev_vah", "dist_prev_val", "dist_prev_vpoc",
           "poc_migration_dir"),
    "L5": ("gamma_block_long", "rvol_zscore", "atr_ref", "atr_source"),
}

# --- bloc l4 : la fenetre de confirmation (SPEC L4 §2) ----------------------
# `finish_delta_pct` n'y est PAS : saturee a 1,0 et de formule inconnue
# (seuils.yaml V5), elle est hors du chemin decisionnel — le finish de la
# fenetre se RECALCULE depuis OHLC (position de la cloture dans le range).
REQUISES_L4 = ("ts", "open", "high", "low", "close", "total_vol", "delta_bar",
               "ask_pct", "bid_pct",
               "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar")
# verifier_colonnes declare le bloc L4 (SPEC §9.1) — a appeler sur le frame
# 1 MIN, pas le 15.
REQUISES["L4"] = REQUISES_L4

# Les PROVENANCES AUTO-DECLAREES du flux : un champ `_X_source` gouverne des
# colonnes, et quand il contient « proxy », ces colonnes se REFUSENT — point 7
# de la nuit du 08/09 (`_mq_gamma_source: sierra_proxy_v2` : le gamma est
# reconstruit depuis un scraper mort le 27/05, decision souveraine du 06/09 :
# aucun proxy). Ce module est le seul endroit qui connait les noms de
# colonnes ; c'est donc le seul endroit qui peut refuser MECANIQUEMENT.
# Une colonne refusee se lit None — un TROU, jamais un faux « tout va bien ».
SOURCES_DECLAREES = {
    # CORRIGE le 07/09 au soir (DECISIONS) : le proxy ne produit QUE le label
    # mq_gamma_condition. Les gamma_block_* viennent de gamma_veto_engine
    # (murs A + atr + bool_gex_flip_zone DMP natif) — REPRODUITS, 0 ecart
    # sur 7 313 barres (5 275 + 2 038 independantes). La table du matin les
    # condamnait par association de famille.
    "_mq_gamma_source": ("mq_gamma_condition",),
    "_aggressor_source": ("aggressor_imbalance",),   # non consommee ce jour
}


def _refusee_proxy(df, col, i):
    """True si `col` est gouvernee par une `_source` qui contient « proxy »."""
    for src, cols in SOURCES_DECLAREES.items():
        if col in cols and src in df.columns:
            v = df[src].iloc[i]
            if v is not None and not pd.isna(v) and "proxy" in str(v).lower():
                return True
    return False


def verifier_colonnes(df, couches=("L0", "L5")):
    """Rend la liste des colonnes manquantes pour les couches demandees.

    A appeler apres le chargement, avant toute mesure. Une couche qui tourne
    sur une colonne absente ne leve rien : elle rend un resultat d'apparence
    normale, et c'est ce qui rend le defaut indetectable a la lecture.
    """
    return [(c, col) for c in couches
            for col in REQUISES.get(c, ()) if col not in df.columns]


def val(df, col, i):
    if col not in df.columns or _refusee_proxy(df, col, i):
        return None
    v = pd.to_numeric(pd.Series([df[col].iloc[i]]), errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)


def vrai(df, col, i):
    v = val(df, col, i)
    return v is not None and v != 0


def _texte(df, col, i):
    if col not in df.columns:
        return None
    v = df[col].iloc[i]
    return None if pd.isna(v) else str(v)


# B5b demande « les N premieres barres ». Le nombre vit dans
# `V3/layers/L1_biais/seuils.yaml` (`B5b.barres_acceptation`) ; il est
# redeclare ici pour que le lecteur ne depende pas de la config d'une couche
# — et `test_biais` INTERDIT aux deux de diverger. Meme geste que les
# constantes DTC du pont : une copie non gardee derive en silence.
N_ACCEPTATION = 3


def _ouverture_vs_va(df):
    """OU LA SEANCE A OUVERT par rapport a la valeur de la veille. +1 au-dessus
    de la VAH, -1 sous la VAL, 0 dedans, `None` si les niveaux manquent.

    C'est un FAIT DU MATIN, constant toute la journee — d'ou la lecture de la
    PREMIERE barre de la trame et non de la barre courante. La trame est
    cash-only (`charger_jour(cash_only=True)`), donc `iloc[0]` est bien la
    premiere barre de seance. Aucun look-ahead : la barre 0 est dans le passe
    de toutes les autres.

    LA RECETTE VIENT DU DEPOT, elle n'est pas inventee ici
    (`mesure_57j.lire_l1` l.122-125) : `dist_prev_vah < 0` veut dire que la VAH
    est SOUS le prix — donc le prix est au-dessus. C'est la convention INVERSEE
    du registre, et c'est la seule ligne de `lire_l1` qui l'appliquait
    correctement le jour ou le reste du module se trompait de signe.

    AMBIGUITE A TRANCHER, signalee et NON decidee ici : `seuils.yaml` dit de B5
    « lue UNE FOIS a 10h30 ET : avant, la valeur du jour n'est pas formee ».
    Cette phrase decrit une comparaison a la valeur du JOUR, pas a l'ouverture.
    Le NOM de la cle dit « ouverture ». On produit donc l'ouverture, qui est ce
    que la cle nomme ; si l'intention etait l'autre, c'est un changement de
    composante, pas de lecteur.
    """
    if df is None or len(df) == 0:
        return None
    if "dist_prev_vah" not in df.columns or "dist_prev_val" not in df.columns:
        return None
    haut, bas = val(df, "dist_prev_vah", 0), val(df, "dist_prev_val", 0)
    if haut is None or bas is None:
        return None
    return 1 if haut < 0 else (-1 if bas > 0 else 0)


def _barres_dedans(df, i):
    """Combien des PREMIERES barres du jour sont restees dans la valeur veille.

    `None` TANT QUE LE COMPTE N'EST PAS UN FAIT. B5b demande « les N premieres
    barres » (N = `barres_acceptation`, 3 dans `seuils.yaml`) : a la barre 0 ou
    1, ce compte n'existe pas encore. Rendre un compte partiel serait inventer
    une valeur ; rendre 0 serait pire — `0` veut dire « aucune », pas « je ne
    sais pas encore ».

    C'est le piege de look-ahead le plus facile a commettre ici : un
    `groupby(jour).head(3)` vectorise ecrirait la meme valeur sur TOUTES les
    barres, rangs 0 et 1 compris, et ferait lire deux barres du futur. On
    compte donc en fenetre ouvrante, et on se tait avant.

    `inside_prev_va` est le booleen du dumper ; il coincide a 100,00 % avec
    « close entre les deux niveaux reconstruits », mesure du 14/09 sur 2940
    barres par instrument (cf. registre, controle `entre_niveaux`).
    """
    if df is None or "inside_prev_va" not in df.columns:
        return None
    if i < N_ACCEPTATION - 1 or len(df) < N_ACCEPTATION:
        return None
    n = 0
    for k in range(N_ACCEPTATION):
        v = val(df, "inside_prev_va", k)
        if v is None:
            return None                  # une barre illisible : on ne devine pas
        n += int(v > 0)
    return n
