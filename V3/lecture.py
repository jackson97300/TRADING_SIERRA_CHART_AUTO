"""La lecture d'une barre — le seul endroit qui calcule.

Les portes comparent, elles ne calculent pas. Une porte qui calcule est une
porte qu'on ne peut pas tester sans un DataFrame complet ; avec ce decoupage,
chaque porte se teste avec un dict de trois cles.

C'est aussi le seul endroit qui connait les noms de colonnes. Le jour ou une
colonne change de nom, une ligne bouge — pas quinze portes.


CE QU'UN CHAMP A `None` VEUT DIRE
----------------------------------
`None` n'est pas `False`. Il veut dire « cette information n'existe pas ici ».
Hors ligne, l'age de la derniere barre et l'etat du connecteur DTC n'ont pas de
sens : les champs correspondants valent `None`, les portes qui les lisent
rendent `None`, et la chaine les journalise comme des TROUS au lieu de les lire
comme des feux verts.

C'est la moitie que le mode hors ligne ne peut pas montrer, et c'est celle qui
compte a 9h30 : en live, ces memes portes ont une vraie valeur a comparer, et
elles bloquent.
"""

from __future__ import annotations

import pandas as pd

from CORE.features import recalc
from V3 import calendrier


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

# Les PROVENANCES AUTO-DECLAREES du flux : un champ `_X_source` gouverne des
# colonnes, et quand il contient « proxy », ces colonnes se REFUSENT — point 7
# de la nuit du 08/09 (`_mq_gamma_source: sierra_proxy_v2` : le gamma est
# reconstruit depuis un scraper mort le 27/05, decision souveraine du 06/09 :
# aucun proxy). lecture.py est le seul endroit qui connait les noms de
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


def lire(df, i, sym="ES", live=None):
    """Prepare la barre `i` pour toutes les portes.

    `live` porte ce qui n'existe qu'en execution reelle — age de la barre en
    secondes, connecteur DTC, contrat du compte, verdict L6 du jour. Hors
    ligne il vaut `None` et ces champs restent `None` : les portes de la
    famille A rendent alors « je ne peux pas repondre », jamais « tout va
    bien ».
    """
    live = live or {}
    ts = int(df["ts"].iloc[i])
    t = pd.Timestamp(ts, unit="ms", tz="UTC")
    return {
        "ts": ts, "sym": sym, "i": i,
        "minutes_et": int(recalc.minutes_et(pd.Series([t])).iloc[0]),
        "jour": str(df["jour"].iloc[i]) if "jour" in df.columns else "",
        # --- famille A : la donnee est-elle vraie ? ------------------------
        # Hors ligne, `charger_jour` a deja filtre les barres instables : le
        # champ vaut `stable` par construction, la porte ne rejette rien. Pas
        # une porte inerte : une porte hors de son terrain — le live.
        "qualite": _texte(df, "data_quality_flag", i),
        "fenetre_melangee": _fenetre_melangee(df),
        "barre_complete": (bool(df["barre_complete"].iloc[i])
                           if "barre_complete" in df.columns else None),
        "rang_du_jour": i,
        "age_s": live.get("age_s"),
        "l6_alerte": live.get("l6_alerte"),
        "colonnes_mortes": live.get("colonnes_mortes"),
        # --- famille B : est-ce un moment ou decider ? ---------------------
        "news_60m": vrai(df, "is_news_60m", i),
        "session_bloquee": vrai(df, "is_session_blocked", i),
        # calcule, plus jamais `None` : les regles de sessions.yaml sont
        # branchees dans `calendrier.est_ferie`. Sans la fonction, le YAML
        # etait de la documentation.
        "ferie": calendrier.est_ferie(_jour(df, i)),
        "rollover": live.get("rollover"),
        # --- famille C : le marche est-il tradable ? -----------------------
        # vix_level == 0.0 est un DEFAUT DANS LE DOMAINE, pas une lecture : le
        # C++ rend regime=1 quand meme. Un regime sans niveau est un trou.
        # Duree corrigee (09/09) : panne = MATIN du 08/09 seulement — nuit,
        # dimanche et ferie pris pour une panne. INCIDENT_LOG 09/09.
        "vix_regime": (val(df, "vix_regime", i)
                       if (val(df, "vix_level", i) or 0.0) > 0.0 else None),
        "dist_hvl_atr": _dist_hvl_atr(df, i),
        # --- famille E : puis-je passer l'ordre ? --------------------------
        "dtc_connecte": live.get("dtc_connecte"),
        "contrat_actif": live.get("contrat_actif"),
        # --- L5 ------------------------------------------------------------
        # Tri-etat : None (absent OU refuse proxy) doit rester None jusqu'au
        # veto, qui rendra un TROU — `vrai()` l'ecraserait en False, le faux
        # feu vert du pattern « gamma hardcode a 0.0 ».
        "gamma_block_long": (None if val(df, "gamma_block_long", i) is None
                             else vrai(df, "gamma_block_long", i)),
        "rvol_zscore": val(df, "rvol_zscore", i),
        "atr_barre": val(df, "atr_barre", i),
    }


def _jour(df, i):
    """La date de la barre, pour le calendrier."""
    return pd.Timestamp(int(df["ts"].iloc[i]), unit="ms", tz="UTC").date()


def _fenetre_melangee(df):
    """La journee melange-t-elle deux versions de fenetre glissante ?

    Ce qui est dangereux n'est PAS d'etre en `w0` — tout l'historique l'est, et
    c'est normal. C'est de MELANGER : « un lot qui melange les deux sur une
    colonne de session doit etre refuse, pas moyenne »
    (`recalc.window_version`). Une porte qui exigerait `w1` fermerait 100 % du
    lot historique et ne dirait rien de vrai.
    """
    if "window_version" not in df.columns:
        return None
    return int(df["window_version"].nunique(dropna=True)) > 1


def _dist_hvl_atr(df, i):
    """Distance au HVL en ATR — le HVL est un REGIME, pas un lieu.

    Mesure du 06/09 : 1,65 % des barres sont a portee du HVL si on le traite
    comme un lieu, contre 99,7 % de couverture si on lit le SIGNE de la
    distance. La zone morte de 1,0 ATR fait tomber les bascules de 10,2 a 1,8
    par jour.
    """
    d = val(df, "dist_mq_hvl", i)
    a = val(df, "atr_barre", i)
    if d is None or not a or a <= 0:
        return None
    # Fable C2 09/09 : dist TICKS x0,25 / atr POINTS ; seuil YAML 1,0->0,25
    return (d * 0.25) / a


# --- bloc l4 : la fenetre de confirmation (SPEC L4 §2) ----------------------

# `finish_delta_pct` n'y est PAS : saturee a 1,0 et de formule inconnue
# (seuils.yaml V5), elle est hors du chemin decisionnel — le finish de la
# fenetre se RECALCULE depuis OHLC (position de la cloture dans le range).
REQUISES_L4 = ("ts", "open", "high", "low", "close", "total_vol", "delta_bar",
               "ask_pct", "bid_pct",
               "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar")
REQUISES["L4"] = REQUISES_L4      # verifier_colonnes declare le bloc (SPEC §9.1)
                                  # — a appeler sur le frame 1 MIN, pas le 15


def lire_l4(b, i_debut, k):
    """Les `k` premieres barres 1 MIN de t+1 — la matiere des cinq vetos.

    `b` : le frame 1 min de la journee, trie, dedoublonne (charger_jour).
    Rend None si la fenetre n'existe pas en entier (fin de fichier, journee
    de trading differente) : la confirmation sera INDISPONIBLE, jamais devinee.

    UNE FENETRE TROUEE EST UN TROU : un seul NaN dans une colonne rend le
    champ None — agreger le reste fabriquerait un faux veto (ask_pct moyenne
    sur un volume qui reste au denominateur) ou un faux feu vert (le delta
    contraire cache par le NaN). Demontre a la review du 07/09, R1.

    Lecture SEULEMENT : les vetos comparent aux seuils, ce bloc ne connait
    aucun nombre. La meche, le momentum ET le finish sont RECALCULES depuis
    OHLC — `bar_upper_wick_pct` est une part du PRIX, `finish_delta_pct`
    sature (pieges des mesures du 07/09, cf seuils.yaml V5)."""
    fin = i_debut + k
    if i_debut < 0 or fin > len(b) or "ts" not in b.columns:
        return None
    f = b.iloc[i_debut:fin]
    # La fenetre ne traverse pas la nuit — lu du ts (22:00 UTC ouvre la
    # journee de trading suivante), pas d'une colonne `jour` que le frame
    # 1 min reel ne porte pas (garde mort detecte a la review, R5).
    t0 = pd.Timestamp(int(f["ts"].iloc[0]), unit="ms", tz="UTC")
    t1 = pd.Timestamp(int(f["ts"].iloc[-1]), unit="ms", tz="UTC")
    if ((t0 + pd.Timedelta(hours=2)).date()
            != (t1 + pd.Timedelta(hours=2)).date()):
        return None

    def _serie(col):
        """La colonne de la fenetre, ENTIERE ou rien : un NaN rend None."""
        if col not in f.columns:
            return None
        v = pd.to_numeric(f[col], errors="coerce")
        return None if v.isna().any() else v

    vols = _serie("total_vol")
    vol_total = float(vols.sum()) if vols is not None else None

    def _pondere(col):
        v = _serie(col)
        if v is None or vols is None or not vol_total:
            return None
        return float((v * vols).sum() / vol_total)

    d = _serie("delta_bar")
    delta_k = float(d.sum() / vol_total) if d is not None and vol_total else None
    o, c = val(f, "open", 0), val(f, "close", len(f) - 1)
    hs, ls = _serie("high"), _serie("low")
    h = float(hs.max()) if hs is not None else None
    lo = float(ls.min()) if ls is not None else None
    etendue = (h - lo) if (h is not None and lo is not None and h > lo) else None
    barres = []
    for j in range(len(f)):
        bh, bl, bc = val(f, "high", j), val(f, "low", j), val(f, "close", j)
        bv = val(f, "total_vol", j)
        rng = (bh - bl) if (bh is not None and bl is not None) else None
        pos = ((bc - bl) / rng if rng else None) if bc is not None else None
        barres.append({"vol": bv, "range_pts": rng, "range_pos": pos})
    big_ask = _serie("max_big_ask_vol_in_bar")
    big_bid = _serie("max_big_bid_vol_in_bar")
    return {
        "k": int(k), "ts_fin": int(f["ts"].iloc[-1]),
        "vol_k": vol_total,
        "ask_pct_k": _pondere("ask_pct"), "bid_pct_k": _pondere("bid_pct"),
        "delta_k": delta_k,
        # le finish RECALCULE : position de la cloture de la derniere barre
        # dans SON range — jamais `finish_delta_pct` (saturee, condamnee)
        "finish_k": barres[-1]["range_pos"] if barres else None,
        "meche_haute_k": ((h - max(o, c)) / etendue
                          if etendue and o is not None and c is not None
                          else None),
        "meche_basse_k": ((min(o, c) - lo) / etendue
                          if etendue and o is not None and c is not None
                          else None),
        "momentum_k": ((c - o) / etendue
                       if etendue and o is not None and c is not None else None),
        "big_ask_max_k": float(big_ask.max()) if big_ask is not None else None,
        "big_bid_max_k": float(big_bid.max()) if big_bid is not None else None,
        "barres": barres,
        "ouverture_t1": o, "prix_entree_l4": c,
    }
