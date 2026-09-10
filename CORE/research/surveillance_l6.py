"""L6 — surveillance quotidienne des donnees.

Tourne sur chaque nouveau fichier, sans rien savoir d'un edge. Repond a une
seule question : **ce que Sierra a ecrit aujourd'hui ressemble-t-il a ce qu'il
ecrivait hier ?**

Cinq controles, chacun ne pouvant se declencher que sur une mesure :

  A  VOLUMETRIE      combien de barres `stable`, contre 1 380 attendues
  B  CONTINUITE      trous INTERNES en seance cash — c'est ce qui distingue une
                     seance ecourtee (bloc continu qui s'arrete tot) d'une panne
                     (trous disperses). Le compte de barres ne les distingue pas :
                     le 19/06 avait 210 barres cash, ce qui ressemblait a une
                     demi-seance de ferie, et 56 trous internes.
  C  FENETRE         le lot melange-t-il `w0` et `w1` ? Un lot mixte sur une
                     colonne de session doit etre refuse, pas moyenne.
  D  RESET VWAP      l'heure du reset de `vwap_d` correspond-elle a 17h ET
                     converti au jour pres ? C'est le check qui porte la dette
                     DST de CONVENTIONS §2 : au 1er novembre, la session doit
                     passer a 22:00 UTC, et si personne ne l'a fait, ce controle
                     le dit au lieu d'un silence de trois mois.
  E  DERIVE          mediane du jour par famille, comparee aux 20 jours
                     precedents. Une famille entiere qui bouge d'un facteur
                     signale un changement de source, pas un mouvement de marche.
                     INFO + motif=derive_feature (Fable 10/09) : une derive
                     INFORME, seule l'integrite FERME — toute ALERTE d'ici
                     ferme la journee live suivante (L0_DATA_L6_ALERTE).
  G  VOLUMETRIE CASH brique 4 (Fable 10/09) : barres cash stable sur 390 — LE
                     compte qui FERME (integrite) ; un ferie rend INFO ; le
                     compte Globex (A) ne ferme plus, il se lit le lendemain.
  H  VIX CASH ZERO   vix_level = 0 en cash = chart VIX mort : ALERTE au-dela
                     de VIX_MORT_MIN minutes (mesure : les pannes du lot
                     durent 101-210 min, jamais une minute).
  I  DERIVE FEATURE  F15 : flag LIVRE par barre (delta_divergence_any, Python)
                     / compte recalcule, contre SA mediane 20 j : un RATIO
                     RELATIF dit feature ou regime. INFO seulement.
  Un roll ATTENDU par le calendrier et un week-end sans fichier rendent INFO
  (review 10/09) : une ALERTE ici ferme le lendemain (L0_DATA_L6_ALERTE).
  F  ECHELLE ATR     brique 1 (Fable 09/09) : avant 11h00 le metre des lieux
                     est l'ATR de la derniere session COMPLETE (`atr_ref`).
                     Un gap d'ouverture >= 2 x cet ATR rend l'echelle de la
                     veille douteuse pour CE jour : INFO `motif=echelle_douteuse`
                     (JAMAIS ALERTE — toute ALERTE ferme la journee live
                     suivante via L0_DATA_L6_ALERTE), et la regle 15 lit ses
                     signaux `atr_source=veille` a part.

Sortie : une ligne JSONL par controle dans `LOGS/surveillance/`, et un code
retour non nul des qu'une ALERTE est levee — de quoi brancher une tache
planifiee.

Usage :
    python -X utf8 CORE/research/surveillance_l6.py            # dernier jour
    python -X utf8 CORE/research/surveillance_l6.py 20260908   # un jour precis
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from CORE.features import recalc  # noqa: E402

BARRES_SESSION = 1380
BARRES_CASH = 390
# En deca, la journee n'est pas exploitable (CONVENTIONS §4).
SEUIL_EXPLOITABLE = 0.90
# Au-dela, les trous ne sont plus une seance courte mais une panne.
MAX_TROUS_CASH = 5
# Une famille dont la mediane bouge de plus de cela contre ses 20 derniers
# jours a change de source, pas de regime.
MAX_DERIVE_FAMILLE = 3.0
N_JOURS_REFERENCE = 20
# Familles dont les niveaux changent tous les jours par construction : de
# nouveaux strikes, un nouveau gamma. Mesure ES du 01 au 03/09 :
# `dist_mq_put` passe de 55 a 162 puis 302 — un facteur 5 en trois jours, sans
# le moindre defaut de donnee. Leur appliquer le seuil commun revient a lever
# une alerte chaque semaine, et une alerte qui se declenche sans action est
# une alerte qu'on finit par ignorer.
FAMILLES_MOUVANTES = {"F11", "F8"}
MAX_DERIVE_MOUVANTE = 10.0
# Brique 1 (Fable 09/09) : au-dela de ce gap d'ouverture, en ATR de la
# derniere session complete, l'echelle de la veille est douteuse pour le jour.
# SEUIL OBSERVE, jamais bloquant (review 10/09, R1), POSE SUR LA DISTRIBUTION
# (Fable Q1) : p90 PAR INSTRUMENT, mesure le 10/09 sur 62 jours (gap = |open
# cash J - close cash J-1 presente| / atr_veille) — ES p50 1,62 p90 5,81 ;
# NQ p50 2,47 p90 6,69. Le « 2,0 » du brief etait la MEDIANE : retire.
MAX_GAP_ATR_VEILLE = {"ES": 5.81, "NQ": 6.69}
N_VEILLES_ECHELLE = 5
# Brique 4 : fenetre (barres 1 min) des divergences delta RECALCULEES —
# definition v1, ecrite dans `_div_recalc`, a valider par Fable.
DIV_FENETRE = 10
MIN_BARRES_RATIO = 5        # sous ca, un compte ne fait pas un ratio (bruit)
# Brique 4 : minutes de vix_level = 0 en cash au-dela desquelles le chart VIX
# est declare mort (pannes du lot : 101-210 min ; une impression en retard de
# 10 min ne ferme pas le lendemain — review R7).
VIX_MORT_MIN = 30
TOLERANCE_MIN_CASH = 10          # une veille a < 380 barres cash est incomplete
COLS_ECHELLE = ["_ts", "_dt", "open", "high", "low", "close", "contract"]


def charger_jour(sym: str, jour: str) -> pd.DataFrame:
    motif = "DATA/live_enriched/sierra/%s/%s*.jsonl" % (sym, jour)
    lignes = []
    for f in sorted(glob.glob(motif)):
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                lignes.append(json.loads(ln))
            except ValueError:
                continue
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    df["_ts"] = recalc.horodatage(df)
    df = df.dropna(subset=["_ts"]).sort_values("_ts").drop_duplicates("_ts")
    df["_dt"] = pd.to_datetime(df["_ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def _res(nom, etat, message, **ctx):
    return {"controle": nom, "etat": etat, "message": message, **ctx}


def controle_volumetrie(df, sym, jour, ecourtee=False):
    st = df[df.get("data_quality_flag", "stable") == "stable"]
    n = len(st)
    part = n / BARRES_SESSION
    dow = pd.Timestamp(jour).day_name()
    if dow == "Sunday":
        return _res("volumetrie", "INFO",
                    "dimanche : %d barres, seance courte attendue" % n,
                    barres=n, part=round(part, 3))
    if ecourtee:
        # La CONTINUITE tranche, pas le compte de barres — c'est la regle du
        # §4. Le 19/06 sur ES : bloc continu de 13:30 a 16:58 UTC, cloture
        # anticipee de Juneteenth, et 209 barres cash sur 390. Sans cette
        # subordination, chaque ferie CME leve une alerte, et une alerte qui se
        # declenche sans action est une alerte qu'on finit par ignorer.
        return _res("volumetrie", "INFO",
                    "%d barres (%.0f %%) — seance ecourtee confirmee par la "
                    "continuite, pas une panne" % (n, 100 * part),
                    barres=n, part=round(part, 3))
    # Brique 4 (Fable 10/09) : le compte Globex (1 380) ne FERME plus — a l'heure
    # du rythme (20h41 UTC) l'after-hours n'est pas fini, et « 90 % » fermait
    # le live du lendemain pour rien. C'est `volumetrie_cash` qui ferme.
    etat = "OK" if part >= SEUIL_EXPLOITABLE else "INFO"
    return _res("volumetrie", etat,
                "%d barres stable sur %d attendues (%.0f %%)%s"
                % (n, BARRES_SESSION, 100 * part,
                   " — Globex incomplet a l'heure du rythme, se lit le lendemain"
                   if etat == "INFO" else ""),
                barres=n, part=round(part, 3),
                degraded=int((df.get("data_quality_flag") != "stable").sum()),
                motif="globex_incomplet" if etat == "INFO" else None)


def controle_continuite(df, sym, jour):
    """Trous INTERNES en cash : ce qui distingue une seance courte d'une panne.

    En minutes ET depuis le 08/09 (revue Fable B2) : ce controle est LE
    chien de garde du 2/11 — s'il etait reste en UTC fige, il aurait
    flagge chaque jour d'hiver « PANNE » et compense l'erreur qu'il doit
    detecter."""
    st = df[df.get("data_quality_flag", "stable") == "stable"]
    m = recalc.est_cash(st["_dt"])
    mn = recalc.minutes_et(st.loc[m, "_dt"]).sort_values()
    if mn.empty:
        return _res("continuite", "ALERTE", "aucune barre en seance cash", trous=None)
    debut, fin = int(mn.iloc[0]), int(mn.iloc[-1])
    trous = (fin - debut + 1) - mn.nunique()
    tot = mn.nunique()
    if trous <= MAX_TROUS_CASH and debut <= recalc.CASH_DEBUT_MIN_ET + 1:
        etat, quoi = ("OK", "complete") if tot >= BARRES_CASH - 5 else \
                     ("INFO", "seance ecourtee (bloc continu)")
    else:
        etat, quoi = "ALERTE", "PANNE (trous disperses)"
    return _res("continuite", etat,
                "%s : %d barres cash, %d trous internes, %02d:%02d -> %02d:%02d ET"
                % (quoi, tot, trous, debut // 60, debut % 60, fin // 60, fin % 60),
                barres_cash=tot, trous=int(trous))


def controle_fenetre(df, sym, jour):
    v = recalc.window_version(df["_ts"])
    vals = sorted(set(v.dropna()))
    etat = "OK" if len(vals) == 1 else "ALERTE"
    return _res("fenetre", etat,
                "window_version = %s" % ", ".join(vals) if vals else "indeterminee",
                versions=vals)


def controle_reset_vwap(df, sym, jour):
    """L'heure du reset de `vwap_d` suit-elle 17h ET ?

    Porte la dette DST de CONVENTIONS §2 : au premier dimanche de novembre, la
    session doit passer de 21:00 a 22:00 UTC. Si le reglage Sierra n'a pas ete
    change, ce controle le dit — au lieu de trois mois de silence.
    """
    if "vwap_d" not in df.columns:
        return _res("reset_vwap", "INFO", "colonne vwap_d absente")
    v = pd.to_numeric(df["vwap_d"], errors="coerce")
    saut = v.diff().abs()
    seuil = max(float(saut.quantile(0.995)), 5.0)
    pas = df["_dt"].diff().dt.total_seconds()
    reset = (saut > seuil) & (pas <= 300)
    if not reset.any():
        return _res("reset_vwap", "INFO", "aucun reset detecte ce jour")
    heures = df.loc[reset, "_dt"].dt.hour
    attendue = int(recalc.ouverture_sess_utc(df["_dt"]).iloc[0])
    proche = int(((heures - attendue).abs() <= 1).sum())
    etat = "OK" if proche else "ALERTE"
    return _res("reset_vwap", etat,
                "%d reset(s), %d a %02dh UTC attendu (17h ET) — heures vues : %s"
                % (int(reset.sum()), proche, attendue,
                   ", ".join("%02dh" % h for h in sorted(set(heures)))),
                attendue_utc=attendue, vues=sorted(int(h) for h in set(heures)))


def _familles():
    try:
        import yaml
        cfg = yaml.safe_load(open("config/families.yaml", encoding="utf-8"))
        return [(re.compile(r["motif"]), r["famille"]) for r in cfg["regles"]]
    except Exception:  # noqa: BLE001
        return []


def controle_derive(df, sym, jour, regles):
    """Mediane par famille, contre les N jours precedents."""
    if not regles:
        return _res("derive", "INFO", "config/families.yaml illisible")
    ref = []
    fichiers = sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))
    fichiers = [f for f in fichiers if os.path.basename(f)[:8] < jour][-N_JOURS_REFERENCE:]
    if len(fichiers) < 5:
        return _res("derive", "INFO", "moins de 5 jours de reference disponibles")
    for f in fichiers:
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln[:1] != "{":
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("data_quality_flag") == "stable":
                ref.append(d)
    if not ref:
        return _res("derive", "INFO", "aucune barre de reference")
    dref = pd.DataFrame(ref)
    st = df[df.get("data_quality_flag", "stable") == "stable"]

    def par_famille(x):
        out = {}
        for c in x.columns:
            if c.startswith("_"):
                continue
            fam = next((fa for rx, fa in regles if rx.search(c)), None)
            if fam is None:
                continue
            s = pd.to_numeric(x[c], errors="coerce")
            if s.notna().sum() > 50 and s.abs().median() > 1e-9:
                out.setdefault(fam, []).append(float(s.abs().median()))
        return {k: float(np.median(v)) for k, v in out.items() if v}

    a, b = par_famille(dref), par_famille(st)
    derives = []
    for fam in sorted(set(a) & set(b)):
        if a[fam] <= 1e-9:
            continue
        r = b[fam] / a[fam]
        seuil = (MAX_DERIVE_MOUVANTE if fam in FAMILLES_MOUVANTES
                 else MAX_DERIVE_FAMILLE)
        if r > seuil or r < 1.0 / seuil:
            derives.append((fam, round(r, 2)))
    # Une DERIVE informe, l'INTEGRITE ferme (Fable, 10/09 avant l'ouverture) :
    # `etat_live.etat_l6` promeut toute ALERTE en L0_DATA_L6_ALERTE (appliquee),
    # et la derive F15 x44 du 09/09 aurait ferme le live du 10/09 entier. Une
    # famille qui change d'echelle n'est pas une atteinte a la donnee : INFO +
    # motif, la lecture y met son caveat (ED10 les jours F15). La taxonomie
    # complete des verdicts L6 (integrite / derive) se formalise apres le gel.
    etat = "INFO" if derives else "OK"
    return _res("derive", etat,
                ("familles derivant d'un facteur > %g : %s" % (
                    MAX_DERIVE_FAMILLE,
                    ", ".join("%s x%.2f" % (f, r) for f, r in derives)))
                if derives else "%d familles comparees, aucune derive" % len(set(a) & set(b)),
                familles_en_derive=[f for f, _ in derives],
                motif="derive_feature" if derives else None)


def controle_rollover(df, sym, jour):
    """Le contrat suivi change-t-il proprement, et tout suit-il le meme jour ?

    Le roll CME sur indices se fait HUIT jours avant l'expiration : pour
    ESU26/NQU26 qui expirent le 18/09, c'est le jeudi 10/09 que le volume
    bascule. Trois choses doivent bouger ensemble ce jour-la — sinon l'une des
    trois est restee sur l'ancien contrat :

      `contract` change      sinon le dumper ne suit pas le front month
      `is_roll_day` vaut 1   sinon le drapeau ne voit pas ce que la colonne dit
      les niveaux F11 bougent sinon MenthorQ publie encore sur l'ancien contrat

    Ce controle n'a de valeur que s'il existe AVANT le roll.
    """
    if "contract" not in df.columns:
        return _res("rollover", "INFO", "colonne contract absente")
    ct = sorted(set(df["contract"].dropna().astype(str)))
    # Un roll ATTENDU par le calendrier n'est pas une atteinte a la donnee
    # (review 10/09, R6) : le jour du roll, une ALERTE ici fermerait le
    # lendemain — le jour du GEL — par L0_DATA_L6_ALERTE. INFO + motif.
    from V3 import calendrier
    attendu = calendrier.contrat_actif(jour)
    vers_attendu = any(attendu in c for c in ct)
    if len(ct) > 1:
        return _res("rollover", "INFO" if vers_attendu else "ALERTE",
                    "deux contrats dans la meme journee : %s%s"
                    % (", ".join(ct), " — bascule EN SEANCE vers le contrat attendu"
                       " (%s) : le bin de bascule porte la base, pas un range"
                       % attendu if vers_attendu else ""),
                    contrats=ct, motif="rollover" if vers_attendu else None)
    veille = None
    for f in sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)):
        if os.path.basename(f)[:8] >= jour:
            continue
        veille = f
    if veille is None:
        return _res("rollover", "INFO", "pas de veille disponible", contrat=ct[0])
    ct_v = None
    for ln in open(veille, encoding="utf-8", errors="ignore"):
        ln = ln.strip()
        if ln[:1] != "{":
            continue
        try:
            ct_v = json.loads(ln).get("contract")
        except ValueError:
            continue
        if ct_v:
            break
    if not ct_v or str(ct_v) == ct[0]:
        return _res("rollover", "OK", "contrat inchange : %s" % ct[0],
                    contrat=ct[0])
    # Le contrat a change : les deux autres doivent suivre.
    flag = pd.to_numeric(df.get("is_roll_day"), errors="coerce")
    flag_ok = bool(flag is not None and (flag == 1).any())
    mq = pd.to_numeric(df.get("dist_mq_call"), errors="coerce")
    mq_bouge = bool(mq is not None and mq.notna().any())
    manques = []
    if not flag_ok:
        manques.append("is_roll_day ne vaut jamais 1")
    if not mq_bouge:
        manques.append("dist_mq_call absente — MenthorQ n'a pas suivi")
    # le roll a eu lieu : attendu -> INFO meme si les deux autres tardent (ils
    # sont NOMMES) ; un roll vers un contrat que le calendrier n'attend pas
    # reste une ALERTE (le dumper suit autre chose que le front month).
    return _res("rollover", "INFO" if vers_attendu else "ALERTE",
                "ROLL %s -> %s%s" % (ct_v, ct[0],
                                     " | " + " ; ".join(manques) if manques
                                     else " — is_roll_day et MenthorQ suivent"),
                contrat=ct[0], contrat_veille=str(ct_v), manques=manques,
                motif="rollover" if vers_attendu else "contrat_inattendu")


def controle_valeurs_par_defaut(df, sym, jour):
    """Les valeurs d'initialisation qui se font passer pour des mesures.

    `DMP_Transform.h:1355-1390` initialise plusieurs champs avant de les faire
    calculer par leur module. Deux de ces defauts sont des valeurs **valides de
    l'enum**, donc indistinguables d'un calcul qui les aurait rendues :

      f.day_type = 2.0f  ("NormVar = le type le plus frequent (42 %)")
      f.rvol     = 1.0f  ("Normal par defaut")

    Mesure du 06/09 sur les 57 jours : `day_type` reste fige a 2.0 pendant TOUT
    le RTH sur 33 jours ES et 29 NQ (sur 53), tandis que `open_type` tourne 52
    jours sur 53 — ce n'est donc pas le module qui tombe, c'est `day_type` seul
    (fix "day_type progressif intra-session", reste TODO depuis le 19/05).
    `rvol == 1.0` ne represente que 0,03 % des barres : le fallback existe mais
    ne se declenche presque jamais.

    L'etat rendu pour `day_type` est **CONNU** et non ALERTE tant que le fix
    n'est pas fait : une alerte qui se leve deux jours sur trois n'est plus lue.
    Il repassera en ALERTE le jour ou le fix sera livre.
    """
    from datetime import datetime, timezone
    if "_ts" not in df.columns or df.empty:
        return _res("valeurs_par_defaut", "OK", "pas d'horodatage")
    mins = df["_ts"].map(
        lambda x: (datetime.fromtimestamp(int(x) / 1000, timezone.utc).hour * 60
                   + datetime.fromtimestamp(int(x) / 1000, timezone.utc).minute)
        if pd.notna(x) else -1)
    rth = df[(mins >= 810) & (mins < 1200)]      # 13:30 - 20:00 UTC

    msg = []
    etat = "OK"
    if "day_type" in df.columns and len(rth) >= 300:
        fige = float((rth["day_type"] == 2.0).mean())
        if fige >= 0.999:
            etat = "CONNU"
            msg.append("day_type fige a 2.0 sur tout le RTH (calcul absent ce jour)")
        elif fige >= 0.95:
            etat = "CONNU"
            msg.append("day_type a 2.0 sur %.1f %% du RTH" % (100 * fige))

    if "rvol" in df.columns and len(df) >= 300:
        part = float((df["rvol"] == 1.0).mean())
        # p90 mesure le 06/09 : 0,09 % ES / 0,15 % NQ ; max 0,22 %.
        if part > 0.01:
            etat = "ALERTE"
            msg.append("rvol == 1.0 exactement sur %.2f %% des barres "
                       "(p90 historique 0,15 %%) : ring buffer non pret" % (100 * part))

    return _res("valeurs_par_defaut", etat,
                " ; ".join(msg) if msg else "aucune valeur par defaut dominante")


def _masque_cash(dt):
    m = recalc.est_cash(dt)
    return m.to_numpy() if hasattr(m, "to_numpy") else np.asarray(m, dtype=bool)


def _veilles(sym, jour, n=N_VEILLES_ECHELLE):
    """Les `n` fichiers 1 min qui PRECEDENT `jour` — de quoi trouver une
    session complete meme apres un ferie ou un fichier tronque."""
    fichiers = sorted(f for f in glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym)
                      if os.path.basename(f)[:8] < jour)[-n:]
    return [charger_jour(sym, os.path.basename(f)[:8]) for f in fichiers]


def _contrat(v):
    if "contract" not in v.columns:
        return None
    c = v["contract"].dropna()
    return str(c.iloc[-1]) if len(c) else None


def controle_echelle_atr(df, sym, jour, veilles=None):
    """F — brique 1 (Fable 09/09). `atr_ref` prend l'ATR de la derniere
    session COMPLETE quand `atr_barre` n'existe pas (9h30-11h00). Un jour de
    GAP d'ouverture >= MAX_GAP_ATR_VEILLE x cet ATR, l'echelle de la veille
    est douteuse pour CETTE journee : `motif = echelle_douteuse`, que la
    LECTURE (regle 15) lit pour mettre les signaux `atr_source = veille` du
    jour A PART.

    JAMAIS ALERTE (review 10/09, R1) : `etat_live.etat_l6` promeut TOUTE
    ligne ALERTE en `L0_DATA_L6_ALERTE` (appliquee), qui fermerait la journee
    live SUIVANTE — et 2,0 ATR-veille etait la MEDIANE des jours NQ (mesure
    sur 62 j : ES 44 %, NQ 58 %, union 66 %). Le seuil est le p90 PAR
    INSTRUMENT (Fable Q1 : ES 5,81 / NQ 6,69), OBSERVE : il etiquette les
    ~10 % de jours ou l'echelle de la veille est vraiment fausse, il ne
    bloque rien. Un changement de
    contrat rend `motif = rollover` (gap de BASE, pas de marche — hors regle
    15). Une veille presente mais incomplete (fichier tronque) rend
    `motif = veille_incomplete` : sa cloture n'en est pas une. Sans session
    complete avant (premier jour du lot) : INFO, jamais un silence."""
    veilles = [v for v in (_veilles(sym, jour) if veilles is None else veilles)
               if not v.empty]
    cash = df[_masque_cash(df["_dt"])]
    if cash.empty:
        return _res("echelle_atr", "INFO", "aucune barre cash — pas de gap mesurable")
    def _cols(v):                      # `contract` n'est pas dans les frames de test
        return v[[c for c in COLS_ECHELLE if c in v.columns]]
    tout = pd.concat([_cols(v) for v in veilles] + [_cols(df)], ignore_index=True)
    med = recalc.atr_veille_15(tout.rename(columns={"_ts": "ts"}), tout["_dt"],
                               minutes=15)
    atr_v = float(med.get(cash["_dt"].iloc[0].date(), np.nan))
    if not np.isfinite(atr_v) or atr_v <= 0:
        return _res("echelle_atr", "INFO",
                    "aucune session complete avant %s : atr_ref = aucun avant "
                    "11h00, les quatre et les seize y restent aveugles" % jour,
                    atr_veille=None, motif=None)
    prec = [v[_masque_cash(v["_dt"])] for v in veilles]
    prec = [v for v in prec if not v.empty]
    if not prec:
        return _res("echelle_atr", "INFO", "veille sans barre cash — gap non mesurable",
                    atr_veille=round(atr_v, 2), motif=None)
    if len(prec[-1]) < BARRES_CASH - TOLERANCE_MIN_CASH:
        return _res("echelle_atr", "INFO",
                    "veille presente mais INCOMPLETE (%d barres cash) : sa cloture "
                    "n'en est pas une, gap non mesurable" % len(prec[-1]),
                    atr_veille=round(atr_v, 2), motif="veille_incomplete")
    close_v = float(pd.to_numeric(prec[-1]["close"], errors="coerce").dropna().iloc[-1])
    open_j = float(pd.to_numeric(cash["open"], errors="coerce").dropna().iloc[0])
    gap = abs(open_j - close_v) / atr_v
    c_j, c_v = _contrat(df), _contrat(veilles[-1])
    if c_j is not None and c_v is not None and c_j != c_v:
        motif, suite = "rollover", (" — ROLLOVER %s -> %s : gap de BASE, pas de "
                                    "marche (hors regle 15)" % (c_v, c_j))
    elif gap >= MAX_GAP_ATR_VEILLE[sym]:          # fail-loud sur un sym inconnu
        motif, suite = "echelle_douteuse", (" — ECHELLE DOUTEUSE (>= p90 %s %.2f) : "
                                            "les signaux atr_source=veille du jour se "
                                            "lisent a part (regle 15)"
                                            % (sym, MAX_GAP_ATR_VEILLE[sym]))
    else:
        motif, suite = None, ""
    return _res("echelle_atr", "INFO" if motif else "OK",
                "gap d'ouverture %.2f ATR-veille (%.2f pts, atr_veille %.2f)%s"
                % (gap, abs(open_j - close_v), atr_v, suite),
                gap_atr=round(gap, 2), atr_veille=round(atr_v, 2),
                close_veille=close_v, open_jour=open_j, motif=motif)


def _flag_stable(df):
    return ((df["data_quality_flag"] == "stable").to_numpy()
            if "data_quality_flag" in df.columns else np.ones(len(df), dtype=bool))


def controle_volumetrie_cash(df, sym, jour):
    """G — brique 4 (Fable 10/09). LE compte qui ferme : barres cash
    9h30-16h00 ET `stable` sur 390. Un jour normal sous 390 - MAX_TROUS_CASH
    est une atteinte a la donnee — le 05/08 tronque a 14h30 aurait ete vu
    (la continuite le lisait « seance ecourtee »). Un ferie / demi-seance
    du calendrier rend INFO : le marche ferme a 13h00 ET, ce n'est pas 390."""
    from V3 import calendrier                 # la source de verite des feries
    n = int((_masque_cash(df["_dt"]) & _flag_stable(df)).sum())
    if _week_end(jour):
        return _res("volumetrie_cash", "INFO", "%d barres cash — week-end, pas un "
                    "compte a %d" % (n, BARRES_CASH), barres=n, motif="week_end")
    ferie = calendrier.est_ferie(jour)
    if ferie:
        return _res("volumetrie_cash", "INFO",
                    "%d barres cash — %s (seance raccourcie) : pas un compte a %d"
                    % (n, ferie, BARRES_CASH), barres=n, motif="ferie")
    if n >= BARRES_CASH - MAX_TROUS_CASH:
        return _res("volumetrie_cash", "OK", "%d barres cash stable sur %d"
                    % (n, BARRES_CASH), barres=n, motif=None)
    return _res("volumetrie_cash", "ALERTE",
                "%d barres cash stable sur %d (manque %d) — donnee TRONQUEE ou "
                "trouee un jour normal" % (n, BARRES_CASH, BARRES_CASH - n),
                barres=n, motif="cash_incomplet")


def controle_vix_cash_zero(df, sym, jour):
    """H — brique 4. `vix_level == 0` (ou NaN, compte mort) en cash = le chart
    VIX mort. Mesure sur 130 jour-instruments (10/09) : 08/09 101 min, 10/08
    147, 05/08 160, 07/09 210/210 — jamais une panne courte. ALERTE au-dela
    de VIX_MORT_MIN minutes (30 : sous les pannes observees, au-dessus d'une
    premiere impression VIX en retard de 10 min — review R7). L0 VIX_REGIME
    lit le trou barre par barre ; une panne se dit le jour meme."""
    m = _masque_cash(df["_dt"])
    if "vix_level" not in df.columns:
        return _res("vix_cash_zero", "INFO", "colonne vix_level absente",
                    motif="colonne_absente")
    v = pd.to_numeric(df.loc[m, "vix_level"], errors="coerce").fillna(0.0)
    if not len(v):
        return _res("vix_cash_zero", "INFO", "aucune barre cash — non mesurable",
                    minutes_zero=None, motif="non_mesurable")
    n0 = int((v <= 0).sum())
    if n0 == 0:
        return _res("vix_cash_zero", "OK", "vix_level > 0 sur %d barres cash" % len(v),
                    minutes_zero=0, motif=None)
    etat = "ALERTE" if n0 > VIX_MORT_MIN else "INFO"
    return _res("vix_cash_zero", etat,
                "vix_level = 0 sur %d barres cash / %d — chart VIX mort%s"
                % (n0, len(v), " (> %d min : ALERTE)" % VIX_MORT_MIN
                   if etat == "ALERTE" else " (court, <= %d min)" % VIX_MORT_MIN),
                minutes_zero=n0, motif="vix_zero")


def _div_recalc(df, m, n=DIV_FENETRE):
    """Divergences delta RECALCULEES sur le 1 min cash — definition v1, ecrite
    ici, a valider par Fable : une barre est en divergence si sa cloture fait
    un plus-haut STRICT sur `n` barres sans plus-haut strict du CVD (bear), ou
    le miroir (bull). UNITE : barres en etat de divergence (pas des episodes).
    CVD = cumul de `delta_bar` sur le cash (un decalage constant par rapport a
    `cvd_sess_r`, sans effet sur des extremes glissants)."""
    d = df[m]
    if "delta_bar" not in d.columns or len(d) < n + 1:
        return None
    c = pd.to_numeric(d["close"], errors="coerce")
    cvd = pd.to_numeric(d["delta_bar"], errors="coerce").fillna(0.0).cumsum()
    hh = c > c.shift(1).rolling(n).max()             # strict des deux cotes (R8)
    ll = c < c.shift(1).rolling(n).min()
    cvd_hh = cvd > cvd.shift(1).rolling(n).max()
    cvd_ll = cvd < cvd.shift(1).rolling(n).min()
    return int(((hh & ~cvd_hh) | (ll & ~cvd_ll)).sum())


COL_DIV_LIVREE = "delta_divergence_any"     # flag PYTHON par barre (divergences_v2)


def _compte_div(df):
    """(livre, recalc) sur le cash d'un frame : livre = barres ou le flag
    LIVRE `delta_divergence_any` (Python, divergences_v2 — PAS le C++
    `delta_divergence`, 0-8 barres par jour, trop rare pour un ratio) est vrai."""
    m = _masque_cash(df["_dt"])
    if COL_DIV_LIVREE not in df.columns:
        return None, None
    livre = int((pd.to_numeric(df.loc[m, COL_DIV_LIVREE],
                               errors="coerce").fillna(0) > 0).sum())
    return livre, _div_recalc(df, m)


def _reference_div(sym, jour, n=N_JOURS_REFERENCE):
    """Les ratios cpp/recalc des `n` jours precedents (jours mesurables)."""
    fichiers = sorted(glob.glob("DATA/live_enriched/sierra/%s/*.jsonl" % sym))
    fichiers = [f for f in fichiers if os.path.basename(f)[:8] < jour][-n:]
    ratios = []
    for f in fichiers:
        cpp, rec = _compte_div(charger_jour(sym, os.path.basename(f)[:8]))
        if cpp is not None and rec:
            ratios.append(cpp / rec)
    return ratios


def controle_derive_feature(df, sym, jour, reference=None):
    """I — brique 4 (review R5). « F15 x44 » seul ne dit rien. Le MEME
    phenomene compte par le flag LIVRE `delta_divergence_any` (Python,
    divergences_v2, par barre — le C++ `delta_divergence` fait 0-8 barres par
    jour : trop rare pour un ratio, mediane nulle) et par `_div_recalc`. Les
    deux definitions ne coincident pas par construction (ratio ~2-4 un jour
    normal) : le ratio du jour se compare a SA PROPRE mediane des
    N_JOURS_REFERENCE jours precedents, par instrument — hors [1/MAX ; MAX]
    x mediane = la feature LIVREE s'emballe (INFO, motif derive_feature, les
    ED10 du jour portent caveat_F15). Jamais ALERTE."""
    livre, rec = _compte_div(df)
    if livre is None:
        return _res("derive_feature", "INFO", "%s absente" % COL_DIV_LIVREE,
                    motif="colonne_absente")
    if not rec or livre < MIN_BARRES_RATIO:
        return _res("derive_feature", "INFO", "F15 : livre %d, recalcule %s — trop "
                    "rare pour un ratio" % (livre, rec), livre=livre, recalc=rec,
                    motif="non_mesurable")
    ref = [x for x in (_reference_div(sym, jour) if reference is None else reference)
           if x > 0]
    r = livre / rec
    if len(ref) < 5:
        return _res("derive_feature", "INFO", "F15 : livre %d / recalcule %d = x%.2f — "
                    "moins de 5 jours de reference" % (livre, rec, r), livre=livre,
                    recalc=rec, ratio=round(r, 2), motif="non_mesurable")
    med = float(np.median(ref))
    rel = r / med
    derive = rel > MAX_DERIVE_FAMILLE or rel < 1.0 / MAX_DERIVE_FAMILLE
    return _res("derive_feature", "INFO" if derive else "OK",
                "F15 : livre %d / recalcule %d = x%.2f, mediane %d j = x%.2f (rel x%.2f)%s"
                % (livre, rec, r, len(ref), med, rel,
                   " — la feature LIVREE s'emballe, pas le marche (caveat_F15 sur les"
                   " ED10 du jour)" if derive else " — dans sa plage : un regime"),
                livre=livre, recalc=rec, ratio=round(r, 2), mediane_ref=round(med, 2),
                n_ref=len(ref), motif="derive_feature" if derive else None)


def _week_end(jour):
    return pd.Timestamp(jour).dayofweek >= 5


def surveiller(sym: str, jour: str, regles) -> list:
    df = charger_jour(sym, jour)
    if df.empty:
        # un samedi / dimanche sans fichier n'est pas une atteinte (review R6) :
        # une ALERTE ici fermerait le LUNDI par L0_DATA_L6_ALERTE
        if _week_end(jour):
            return [_res("chargement", "INFO", "%s : week-end, pas de fichier attendu"
                         % jour, motif="week_end")]
        return [_res("chargement", "ALERTE", "aucune donnee pour %s %s" % (sym, jour))]
    # La continuite d'abord : c'est elle qui tranche entre seance ecourtee et
    # panne, et la volumetrie s'y subordonne.
    cont = controle_continuite(df, sym, jour)
    ecourtee = "ecourtee" in cont["message"]
    return [controle_volumetrie(df, sym, jour, ecourtee=ecourtee),
            cont,
            controle_fenetre(df, sym, jour),
            controle_reset_vwap(df, sym, jour),
            controle_rollover(df, sym, jour),
            controle_derive(df, sym, jour, regles),
            controle_valeurs_par_defaut(df, sym, jour),
            controle_echelle_atr(df, sym, jour),
            controle_volumetrie_cash(df, sym, jour),
            controle_vix_cash_zero(df, sym, jour),
            controle_derive_feature(df, sym, jour)]


def main() -> int:
    jour = sys.argv[1] if len(sys.argv) > 1 else None
    if jour is None:
        fichiers = sorted(glob.glob("DATA/live_enriched/sierra/NQ/*.jsonl"))
        if not fichiers:
            print("aucun fichier")
            return 1
        jour = os.path.basename(fichiers[-1])[:8]
    regles = _familles()
    os.makedirs("LOGS/surveillance", exist_ok=True)
    chemin = "LOGS/surveillance/surveillance_%s.jsonl" % jour
    alertes = 0
    with open(chemin, "w", encoding="utf-8") as fh:
        for sym in ("NQ", "ES"):
            print("\n=== %s — %s" % (sym, jour))
            for r in surveiller(sym, jour, regles):
                r.update({"symbole": sym, "jour": jour,
                          "ecrit_a": datetime.now(timezone.utc).isoformat()})
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                marque = {"OK": "  ", "INFO": "  ", "ALERTE": ">>"}[r["etat"]]
                print("%s %-12s %-7s %s" % (marque, r["controle"], r["etat"],
                                            r["message"]))
                alertes += r["etat"] == "ALERTE"
    print("\n[ecrit] %s — %d alerte(s)" % (chemin, alertes))
    return 1 if alertes else 0


if __name__ == "__main__":
    sys.exit(main())
