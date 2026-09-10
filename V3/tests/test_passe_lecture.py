"""La passe lecture (brief Fable 10/09) — R3 + A1 + B3, sur le vrai chemin.

    python -X utf8 V3/tests/test_passe_lecture.py

Ce que ça prouve, écrit avant :
  0. Le découpage est invisible : `lecture.val`, `lecture.verifier_colonnes`,
     `lecture.SOURCES_DECLAREES` sont les objets de `lecture_colonnes`.
  1. R3 — une barre du MATIN réelle (`atr_barre` NaN, `atr_ref` fini) passée
     dans `chaine.appliquer(strict=True, live sain)` : `L5_FRAIS_TROP_LOURDS`
     et `L0_REGIME_INDETERMINE` RÉPONDENT (aucune ligne TROU_ pour elles), la
     ligne porte `atr_source = veille`. Sans recalculs (df nu), `atr_ref`
     retombe sur `atr_barre` et `atr_source = absent` — visible, pas muet.
  2. A1 — le veto gamma par sens : LONG + `gamma_block_long` → bloque ; le
     même SHORT → None (TROU_L5_VETO_GAMMA : la colonne short n'est pas dans
     l'agrégation) ; sens inconnu → None.
  3. B3 — `rang_du_jour` vient de l'HEURE : un df qui commence à 9h15 rend
     −1 puis 0 à 9h30 ; un df à 9h45 en tête rend 1 (plus jamais 0) ; une
     barre HORS grille 15 min lève avec son ts.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from CORE.bot_terminal import charger_jour                    # noqa: E402
from CORE.research.hypothesis_runner import injecter_recalculs  # noqa: E402
from V3 import chaine, lecture, lecture_colonnes, registre    # noqa: E402
from V3.campagne import COLS_RECALC, chauffe_1min             # noqa: E402
from V3.layers.L0_interrupteur import portes                  # noqa: E402

PASSED = FAILED = 0
JOUR, SYM = "20260903", "ES"
LIVE_SAIN = {"age_s": 12.0, "l6_alerte": False, "colonnes_mortes": False,
             "rollover": False, "contrat_actif": True, "dtc_connecte": True}


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-60s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


def lignes_chaine(df, signaux, strict=True, live=None):
    fd, chemin = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(chemin)
    try:
        chaine.appliquer(signaux, df, SYM, journal=chemin, hypothese="passe",
                         strict=strict, live=live)
        return ([json.loads(ln) for ln in open(chemin, encoding="utf-8") if ln.strip()]
                if os.path.exists(chemin) else [])
    finally:
        if os.path.exists(chemin):
            os.remove(chemin)


def df_grille(debut_utc, n=6, pas_min=15):
    t0 = pd.Timestamp("2026-09-03 %s" % debut_utc, tz="UTC")
    ts = [int((t0 + pd.Timedelta(minutes=k * pas_min)).value // 1_000_000) for k in range(n)]
    return pd.DataFrame({"ts": ts, "jour": "20260903", "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.0, "atr_barre": 2.0, "atr_ref": 2.0,
                         "atr_source": "barre", "dist_mq_hvl": 40.0})


def main():
    # 0. le decoupage est invisible
    check("[0] lecture re-exporte lecture_colonnes (val, verifier_colonnes, SOURCES)",
          lecture.val is lecture_colonnes.val
          and lecture.verifier_colonnes is lecture_colonnes.verifier_colonnes
          and lecture.SOURCES_DECLAREES is lecture_colonnes.SOURCES_DECLAREES)

    # 1. R3 — barre du matin reelle
    df, brut = charger_jour(SYM, JOUR, 15, avec_1min=True)
    if df.empty:
        check("[1] journee %s indisponible" % JOUR, False)
    else:
        agg = injecter_recalculs(pd.concat(chauffe_1min(SYM, JOUR) + [brut[COLS_RECALC]],
                                           ignore_index=True), df, minutes=15)
        i = 4                                    # 10h30 ET : rang 4, atr_barre NaN
        matin = pd.isna(agg["atr_barre"].iloc[i]) and pd.notna(agg["atr_ref"].iloc[i])
        check("[1a] la barre 4 est bien une barre du matin (atr_barre NaN, atr_ref fini)",
              bool(matin), (agg["atr_barre"].iloc[i], agg["atr_ref"].iloc[i]))
        lec = lecture.lire(agg, i, SYM, live=LIVE_SAIN, side=+1)
        trio = {k: lec.get(k) for k in ("atr_ref", "atr_source", "atr_barre")}
        check("[1b] lec expose atr_ref (fini) et atr_source=veille, atr_barre toujours la",
              lec.get("atr_ref") is not None and lec.get("atr_source") == "veille"
              and "atr_barre" in lec, trio)
        L = lignes_chaine(agg, [(i, +1)], strict=True, live=LIVE_SAIN)
        motifs = {o["motif"] for o in L}
        check("[1c] L5_FRAIS_TROP_LOURDS repond (pas de TROU_) sur la barre du matin",
              "TROU_L5_FRAIS_TROP_LOURDS" not in motifs, sorted(motifs))
        check("[1d] L0_REGIME_INDETERMINE repond (pas de TROU_) sur la barre du matin",
              "TROU_L0_REGIME_INDETERMINE" not in motifs, sorted(motifs))
        check("[1e] chaque ligne porte atr_source=veille",
              bool(L) and all(o.get("atr_source") == "veille" for o in L),
              [o.get("atr_source") for o in L])
        nu = lecture.lire(df, i, SYM, side=+1)     # df nu : pas de recalculs
        check("[1f] df sans recalculs : atr_ref = atr_barre, atr_source=absent (visible)",
              nu["atr_source"] == "absent" and nu["atr_ref"] == nu["atr_barre"],
              {k: nu.get(k) for k in ("atr_ref", "atr_source", "atr_barre")})

    # 2. A1 — le gamma par sens
    g = registre.REGISTRE["L5_VETO_GAMMA"]["fn"]
    base = {"gamma_block_long": True, "sym": "ES"}
    check("[2a] LONG + gamma_block_long -> veto", g(dict(base, side=+1), {}, {}) is True)
    check("[2b] le meme SHORT -> None (TROU, colonne short absente)",
          g(dict(base, side=-1), {}, {}) is None)
    check("[2c] sens inconnu -> None, jamais un veto invente",
          g(dict(base, side=None), {}, {}) is None)
    check("[2d] LONG sans mur -> False", g({"gamma_block_long": False, "sym": "ES",
                                            "side": +1}, {}, {}) is False)

    # 3. B3 — rang_du_jour depuis l'heure
    d915 = df_grille("13:15")                    # 9h15 ET (EDT)
    r = [lecture.lire(d915, k, SYM)["rang_du_jour"] for k in range(3)]
    check("[3a] df qui commence a 9h15 : rangs -1, 0, 1 (l'heure, pas l'indice)",
          r == [-1, 0, 1], r)
    d945 = df_grille("13:45")                    # trou a l'ouverture
    check("[3b] df qui commence a 9h45 : rang 1 (plus jamais 0)",
          lecture.lire(d945, 0, SYM)["rang_du_jour"] == 1)
    try:
        lecture.lire(df_grille("13:20"), 0, SYM)
        check("[3c] barre hors grille 15 min -> leve avec le ts", False)
    except ValueError as e:
        check("[3c] barre hors grille 15 min -> leve avec le ts", "ts" in str(e), e)
    d930 = df_grille("13:30", n=8)
    L = lignes_chaine(d930, [(2, +1), (5, +1)], strict=False,
                      live={"contrat_actif": True, "rollover": False})
    par_i = {}
    for o in L:
        par_i.setdefault(int(o["snapshot_id"].split(":")[1]), set()).add(o["motif"])
    check("[3d] L0_PREMIERE_BARRE inchangee : rang 2 bloque, rang 5 passe (rang_min 4)",
          "L0_PREMIERE_BARRE" in par_i.get(2, set())
          and "L0_PREMIERE_BARRE" not in par_i.get(5, set()), par_i)
    # review R3 : le battement live passe full_agg (la nuit d'abord). Rang lu
    # sur l'heure : negatif la nuit -> PREMIERE_BARRE bloque (avant, i grand
    # passait) ; 18h00 ET (22:00 UTC) = rang 34 -> passe (l'artefact d'indice
    # qui bloquait 18h00-18h45 disparait). Decision inchangee : la nuit est
    # deja fermee par la session.
    pb = registre.REGISTRE["L0_PREMIERE_BARRE"]["fn"]
    s_pb = portes.charger_seuils()[0]["L0_PREMIERE_BARRE"]
    nuit = lecture.lire(df_grille("04:00"), 0, SYM)          # 00h00 ET
    soir = lecture.lire(df_grille("22:00"), 0, SYM)          # 18h00 ET
    check("[3e] barre de nuit (00h00 ET) : rang %d < 0 -> PREMIERE_BARRE bloque"
          % nuit["rang_du_jour"], nuit["rang_du_jour"] < 0 and pb(nuit, {}, s_pb) is True)
    check("[3f] barre de 18h00 ET : rang 34 -> passe",
          soir["rang_du_jour"] == 34 and pb(soir, {}, s_pb) is False)

    # review R4 : la garde YAML est un commentaire — ceci est la garde.
    _s, appliquees, _a = portes.charger_seuils()
    check("[4] L5_VETO_GAMMA reste OBSERVEE tant que gamma_block_short n'est pas dans "
          "l'agregation (en strict, le trou bloquerait tous les shorts)",
          "L5_VETO_GAMMA" not in appliquees, sorted(appliquees))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
