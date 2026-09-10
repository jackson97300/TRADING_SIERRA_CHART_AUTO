"""SCÉNARIOS — les zones d'intervention (spec §2, §2 bis ; décisions Fable du
10/09). Une zone est une BANDE en prix, jamais un point ; elle a une nature,
une largeur asymétrique, une mémoire (F23, causale) et un rôle que le
scénario lui donne. Ce module ne décide rien : il décrit où sont les niveaux
figés de la journée et ce que le prix en a fait jusqu'à la barre courante.

    zones = construire(df15, brut, sym)          # les niveaux figés à 9h30
    ajouter_ib(zones, df15, sym)                  # l'IB, figée à 10h30
    etat = observer(zones, df15, i)               # la mémoire de chaque zone à la barre i

Définitions (écrites avant tout usage) :
  dedans  = P10 `seuil_ticks` sur atr_ref — la proximité qui DÉCLENCHE, du
            côté d'où vient le prix ;
  dehors  = p80 des dépassements sur les tests tenus, par nature et par
            instrument (`seuils.yaml`, fixé par Fable) — la bande qui CONTIENT,
            de l'autre côté. Une nature sans `dehors` (null) n'est pas une zone.
  test    = la barre englobe le niveau (touche F23, hystérésis de L1) ;
  tenue   = la barre suivante clôture du côté d'où le prix venait (CAUSALE,
            connue à i + 1 — jamais l'`issue` F23) ;
  cassée  = deux clôtures consécutives strictement au-delà ;
  regagnée = après cassée, deux clôtures consécutives revenues ;
  atteinte = la barre est entrée dans la bande sans englober le niveau.
Les 0DTE sont `dormant` avant 14h00 ET ; un mur qui bouge de plus d'un tick
entre deux barres = `ZONE_DEPLACEE`, journalisé avec l'heure, jamais corrigé.
Le HVL n'est pas une zone : `cote_hvl` est un côté, porté par la grammaire.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.features import f23, recalc                           # noqa: E402
from V3.scenarios import lot                                    # noqa: E402

Z_TOUCHE, Z_RESET = 0.0, 0.5                 # L1 seuils.yaml (06/09), réutilisés
# (nom, colonne dist du brut, nature, source, rôle par défaut)
FIGES = (("prev_vah", "dist_prev_vah", "VA_veille", "derniere_complete"),
         ("prev_val", "dist_prev_val", "VA_veille", "derniere_complete"),
         ("prev_vpoc", "dist_prev_vpoc", "VA_veille", "derniere_complete"),
         ("pdh", "dist_pdh", "PDH_PDL", "sierra"), ("pdl", "dist_pdl", "PDH_PDL", "sierra"),
         ("ovn_high", "dist_ovn_high", "OVN", "sierra"), ("ovn_low", "dist_ovn_low", "OVN", "sierra"),
         ("mq_call", "dist_mq_call", "MUR_call_put", "snapshot_mq"),
         ("mq_put", "dist_mq_put", "MUR_call_put", "snapshot_mq"),
         ("mq_call_0dte", "dist_mq_call_0dte", "MUR_call_put", "snapshot_mq"),
         ("mq_put_0dte", "dist_mq_put_0dte", "MUR_call_put", "snapshot_mq"))
ETATS = ("intacte", "atteinte", "testee", "cassee", "regagnee")


def _p10(atr, tick=lot.TICK):
    return max(0.10 * float(atr) / tick, 2.0) if atr and np.isfinite(atr) and atr > 0 else None


def _zone(nom, nature, source, prix, dedans, dehors, provisoire, dormant=False):
    return {"nom": nom, "nature": nature, "source": source, "prix": round(float(prix), 2),
            "dedans_ticks": round(dedans, 2), "dehors_ticks": float(dehors), "provisoire": bool(provisoire),
            "dormant": dormant, "deplacements": [], "role": None, "setups_armes": [],
            "fiche": {"n_tests": 0, "dernier_test_i": None, "dernier_tenu": None, "etat": "intacte"}}


def construire(df15, brut, sym, seuils=None):
    """Les zones figées à la PREMIÈRE minute cash (9h30) — jamais relues
    ensuite, sauf `ZONE_DEPLACEE` pour les murs. Une nature dont `dehors` est
    null n'entre pas (VWAP, GEX_nearest, murs NQ en v0)."""
    s = seuils or lot.seuils()
    dehors_par = s["zones"]["dehors_ticks"]
    prov = s["zones"].get("provenance", {})
    if brut.empty or df15.empty:
        return []
    r0 = brut.iloc[0]
    close0 = float(r0["close"])
    a = float(df15["atr_ref"].iloc[0]) if "atr_ref" in df15.columns else np.nan
    dedans = _p10(a)
    if dedans is None:
        return []
    zones = []
    for nom, col, nature, source in FIGES:
        dehors = (dehors_par.get(nature) or {}).get(sym)
        d = pd.to_numeric(pd.Series([r0.get(col)]), errors="coerce").iloc[0]
        if dehors is None or not np.isfinite(d):
            continue
        provisoire = (nature == "VA_veille") or (nature == "MUR_call_put" and "MUR_call_put_%s" % sym in prov)
        zones.append(_zone(nom, nature, source, close0 + float(d) * lot.TICK, dedans, dehors, provisoire,
                           dormant=nom.endswith("_0dte")))
    return zones


def ajouter_ib(zones, df15, sym, i_debut=4, seuils=None):
    """L'IB, figée à 10h30 : max / min des quatre premières barres 15 min."""
    if len(df15) <= i_debut or any(z["nom"] == "ib_high" for z in zones):
        return zones
    s = seuils or lot.seuils()
    dehors = (s["zones"]["dehors_ticks"].get("IB") or {}).get(sym)
    a = float(df15["atr_ref"].iloc[i_debut])
    dedans = _p10(a)
    if dehors is None or dedans is None:
        return zones
    zones.append(_zone("ib_high", "IB", "calcul_jour", df15["high"].iloc[:i_debut].max(), dedans, dehors, False))
    zones.append(_zone("ib_low", "IB", "calcul_jour", df15["low"].iloc[:i_debut].min(), dedans, dehors, False))
    return zones


def bande(zone, close):
    """(bas, haut) de la bande, ASYMÉTRIQUE selon le côté d'où vient le prix :
    `dedans` du côté du prix, `dehors` au-delà."""
    de, dh = zone["dedans_ticks"] * lot.TICK, zone["dehors_ticks"] * lot.TICK
    if close < zone["prix"]:
        return round(zone["prix"] - de, 2), round(zone["prix"] + dh, 2)
    return round(zone["prix"] - dh, 2), round(zone["prix"] + de, 2)


def _touches(df15, zone):
    """Les tests F23 du niveau (touche + hystérésis), CAUSAUX par construction
    (la boucle de `fiches` ne lit que le passé) ; l'`issue` n'est pas lue."""
    d = df15[["ts", "high", "low", "close"]].copy()
    d["atr_barre"] = df15["atr_ref"]
    d["dist_zone"] = (zone["prix"] - pd.to_numeric(d["close"], errors="coerce")) / lot.TICK
    return [(f["i"], f["cote"]) for f in f23.fiches(d, None, "dist_zone", lot.TICK, Z_TOUCHE, Z_RESET)]


def observer(zones, df15, i, brut=None):
    """La mémoire de chaque zone à la barre i — rien de ce qui n'est pas connu
    à i n'est révélé. Rend la liste des événements de la barre (ZONE_DEPLACEE,
    TEST, TENUE, CASSEE, REGAGNEE, ATTEINTE, ACTIVE_0DTE)."""
    close = pd.to_numeric(df15["close"], errors="coerce")
    high, low = pd.to_numeric(df15["high"], errors="coerce"), pd.to_numeric(df15["low"], errors="coerce")
    m_et = int(recalc.minutes_et(pd.Series([int(df15["ts"].iloc[i])]).pipe(pd.to_datetime, unit="ms", utc=True)).iloc[0])
    evenements = []
    for z in zones:
        if z["dormant"] and m_et >= lot.seuils()["zones"]["zero_dte_minutes_et"]:
            z["dormant"] = False
            evenements.append({"quoi": "ACTIVE_0DTE", "zone": z["nom"], "i": i})
        if z["source"] == "snapshot_mq" and brut is not None:
            _deplacement(z, df15, brut, i, evenements)
        if "_touches" not in z:
            z["_touches"] = _touches(df15, z)
        if z["dormant"]:
            continue                                  # un 0DTE dormant n'a ni memoire ni evenement avant 14h00 ET
        f = z["fiche"]
        vus = [(j, c) for j, c in z["_touches"] if j <= i]
        if vus and vus[-1][0] == i:
            cote = vus[-1][1]
            dep = ((float(high.iloc[i]) - z["prix"]) if cote > 0 else (z["prix"] - float(low.iloc[i]))) / lot.TICK
            f["n_tests"], f["dernier_test_i"], f["dernier_cote"] = len(vus), i, cote
            f["dernier_tenu"], f["dernier_depassement_ticks"] = None, round(max(0.0, dep), 2)
            f["depassement_max_ticks"] = max(f.get("depassement_max_ticks") or 0.0, round(max(0.0, dep), 2))
            if f["etat"] in ("intacte", "atteinte"):
                f["etat"] = "testee"
            evenements.append({"quoi": "TEST", "zone": z["nom"], "i": i, "cote": cote,
                               "depassement_ticks": round(max(0.0, dep), 2)})
        elif vus and vus[-1][0] == i - 1:
            cote = vus[-1][1]
            tenu = (close.iloc[i] < z["prix"]) if cote > 0 else (close.iloc[i] > z["prix"])
            f["dernier_tenu"] = bool(tenu)
            if tenu:
                f["n_tenues"] = f.get("n_tenues", 0) + 1
                evenements.append({"quoi": "TENUE", "zone": z["nom"], "i": i, "cote": cote})
        _acceptation(z, close, i, evenements)
        if f["etat"] == "intacte" and low.iloc[i] <= z["prix"] <= high.iloc[i]:
            f["etat"] = "atteinte"
            evenements.append({"quoi": "ATTEINTE", "zone": z["nom"], "i": i})
    return evenements


def _acceptation(z, close, i, evenements):
    """Cassée = deux clôtures au-delà (par rapport au côté d'où le prix
    venait) ; regagnée = deux clôtures revenues. Le côté d'origine est celui
    de la clôture d'avant la première clôture au-delà."""
    if i < 2:
        return
    f = z["fiche"]
    c0, c1, c2 = float(close.iloc[i - 2]), float(close.iloc[i - 1]), float(close.iloc[i])
    p = z["prix"]
    if f["etat"] != "cassee":
        au_dessus = c1 > p and c2 > p and c0 <= p
        en_dessous = c1 < p and c2 < p and c0 >= p
        if au_dessus or en_dessous:
            f["etat"], f["casse_par"] = "cassee", (1 if au_dessus else -1)
            evenements.append({"quoi": "CASSEE", "zone": z["nom"], "i": i, "cote": f["casse_par"]})
    else:
        revenu = (c1 < p and c2 < p) if f.get("casse_par", 0) > 0 else (c1 > p and c2 > p)
        if revenu:
            f["etat"] = "regagnee"
            evenements.append({"quoi": "REGAGNEE", "zone": z["nom"], "i": i, "cote": -f["casse_par"]})


def _deplacement(z, df15, brut, i, evenements):
    """Un mur dont le niveau livré a bougé de plus d'un tick depuis la zone :
    ZONE_DEPLACEE, avec l'heure — jamais une correction silencieuse."""
    col = "dist_" + z["nom"]
    if col not in brut.columns:
        return
    ts_fin = int(df15["ts"].iloc[i]) + 15 * 60 * 1000 - 1
    b = brut[pd.to_numeric(brut["ts"]) <= ts_fin]
    if b.empty:
        return
    d = pd.to_numeric(b[col], errors="coerce").iloc[-1]
    if not np.isfinite(d):
        return
    prix = round(float(b["close"].iloc[-1]) + float(d) * lot.TICK, 2)
    if abs(prix - z["prix"]) > lot.seuils()["zones"]["zone_deplacee_ticks"] * lot.TICK:
        z["deplacements"].append({"i": i, "de": z["prix"], "vers": prix})
        evenements.append({"quoi": "ZONE_DEPLACEE", "zone": z["nom"], "i": i, "de": z["prix"], "vers": prix})
        z["prix"] = prix
        z.pop("_touches", None)


def actives(zones):
    return [z for z in zones if not z["dormant"]]


def prochaines(zones, close):
    """La prochaine zone au-dessus et en dessous du prix, parmi les actives."""
    haut = [z for z in actives(zones) if z["prix"] > close]
    bas = [z for z in actives(zones) if z["prix"] < close]
    return (min(haut, key=lambda z: z["prix"])["nom"] if haut else None,
            max(bas, key=lambda z: z["prix"])["nom"] if bas else None)


def exporter(zones, close):
    """Les zones telles que le journal les écrit (spec §2), sans le cache."""
    out = []
    for z in actives(zones):
        bas, haut = bande(z, close)
        out.append({k: v for k, v in z.items() if not k.startswith("_")} | {"bas": bas, "haut": haut})
    return out
