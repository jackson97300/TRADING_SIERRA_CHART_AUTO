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
    "L5": ("gamma_block_long", "rvol_zscore"),
}


def verifier_colonnes(df, couches=("L0", "L5")):
    """Rend la liste des colonnes manquantes pour les couches demandees.

    A appeler apres le chargement, avant toute mesure. Une couche qui tourne
    sur une colonne absente ne leve rien : elle rend un resultat d'apparence
    normale, et c'est ce qui rend le defaut indetectable a la lecture.
    """
    return [(c, col) for c in couches
            for col in REQUISES.get(c, ()) if col not in df.columns]


def val(df, col, i):
    if col not in df.columns:
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
        "minute_utc": t.hour * 60 + t.minute,
        "jour": str(df["jour"].iloc[i]) if "jour" in df.columns else "",
        # --- famille A : la donnee est-elle vraie ? ------------------------
        # Hors ligne, `charger_jour` a deja filtre les barres instables : le
        # champ vaut donc `stable` par construction et la porte ne rejette
        # rien. Ce n'est pas une porte inerte, c'est une porte hors de son
        # terrain — son terrain est le live.
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
        "vix_regime": val(df, "vix_regime", i),
        "dist_hvl_atr": _dist_hvl_atr(df, i),
        # --- famille E : puis-je passer l'ordre ? --------------------------
        "dtc_connecte": live.get("dtc_connecte"),
        "contrat_actif": live.get("contrat_actif"),
        # --- L5 ------------------------------------------------------------
        "gamma_block_long": vrai(df, "gamma_block_long", i),
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
    return d / a
