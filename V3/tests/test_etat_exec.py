"""L'etat d'execution — les primitives partagees EXEC/coureur, avant tout ordre.

Verifie : l'ecriture atomique (aucun `.tmp` laisse), le round-trip, les TROIS
TROU (absent / perime / illisible — un etat qu'on ne peut pas croire n'est
jamais un feu vert), le fail-loud (etat sans sym), et les accesseurs que les
portes live consommeront.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.execution import etat_exec as E                          # noqa: E402

PASSED = 0
FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("  %-40s PASS" % nom)
    else:
        FAILED += 1
        print("  %-40s FAIL %s" % (nom, detail))


T0 = 1788540300000

# --- forme de l'etat neuf --------------------------------------------------
neuf = E.etat_neuf("ES", "U26")
check("neuf : plat (sens 0)", neuf["position"]["sens"] == 0)
check("neuf : rien en vol", neuf["ordres_en_vol"] == [])
check("neuf : pnl 0", neuf["pnl_jour"] == 0.0)
check("neuf : pas de cooldown", neuf["fin_cooldown_ms"] is None)
check("neuf : contrat porte", neuf["contrat"] == "U26")

with tempfile.TemporaryDirectory() as tmp:
    # --- ecriture atomique + round-trip ------------------------------------
    ecrit = E.ecrire_etat(neuf, maintenant_ms=T0, dossier=tmp)
    check("ecrire estampille ts_maj", ecrit["ts_maj"] == T0)
    fichiers = os.listdir(tmp)
    check("aucun .tmp laisse (atomique)",
          fichiers == ["etat_ES.json"], str(fichiers))
    lu, motif = E.lire_etat("ES", T0 + 1000, ttl_s=120, dossier=tmp)
    check("round-trip : frais, motif None", motif is None and lu is not None)
    check("round-trip : contenu identique",
          lu["sym"] == "ES" and lu["position"]["sens"] == 0)

    # --- les trois TROU ----------------------------------------------------
    _, m_abs = E.lire_etat("NQ", T0, dossier=tmp)          # jamais ecrit
    check("absent -> TROU_ETAT_ABSENT", m_abs == "TROU_ETAT_ABSENT")

    lu_p, m_per = E.lire_etat("ES", T0 + 121 * 1000, ttl_s=120, dossier=tmp)
    check("perime (ts_maj + 121 s > ttl 120) -> TROU_ETAT_PERIME",
          lu_p is None and m_per == "TROU_ETAT_PERIME")
    lu_f, m_ok = E.lire_etat("ES", T0 + 119 * 1000, ttl_s=120, dossier=tmp)
    check("119 s < ttl 120 -> encore frais", m_ok is None and lu_f is not None)

    # json casse -> illisible, pas un etat invente
    with open(os.path.join(tmp, "etat_GC.json"), "w", encoding="utf-8") as fh:
        fh.write("{pas du json")
    _, m_ill = E.lire_etat("GC", T0, dossier=tmp)
    check("json casse -> TROU_ETAT_ILLISIBLE", m_ill == "TROU_ETAT_ILLISIBLE")
    # champ ts_maj manquant -> illisible aussi
    with open(os.path.join(tmp, "etat_MG.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"sym": "MG", "position": {"sens": 0}}))
    _, m_sans = E.lire_etat("MG", T0, dossier=tmp)
    check("ts_maj manquant -> TROU_ETAT_ILLISIBLE", m_sans == "TROU_ETAT_ILLISIBLE")
    # R2 : json valide + ts_maj present mais PAS de position -> ILLISIBLE
    # (sinon l'appelant crashe au KeyError plus tard), pas « frais ».
    with open(os.path.join(tmp, "etat_XX.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"sym": "XX", "ts_maj": T0,
                             "ordres_en_vol": [], "pnl_jour": 0.0}))
    _, m_forme = E.lire_etat("XX", T0, dossier=tmp)
    check("forme sans position -> TROU_ETAT_ILLISIBLE (R2)",
          m_forme == "TROU_ETAT_ILLISIBLE")

    # R1 : ts_maj DANS LE FUTUR (maintenant < ts_maj - tolerance) -> non
    # credible, TROU_ETAT_FUTUR, jamais « frais a jamais ».
    _, m_fut = E.lire_etat("ES", T0 - 10 * 1000, ttl_s=120, dossier=tmp)
    check("ts_maj futur -> TROU_ETAT_FUTUR (R1)", m_fut == "TROU_ETAT_FUTUR")

    # --- fail-loud : etat sans sym -----------------------------------------
    try:
        E.ecrire_etat({"position": {"sens": 0}}, dossier=tmp)
        leve = False
    except ValueError:
        leve = True
    check("ecrire sans sym -> leve", leve)

# --- accesseurs (le contrat que les portes live liront) --------------------
ouverte = E.etat_neuf("ES", "U26")
ouverte["position"]["sens"] = -1
check("position_ouverte : sens != 0 -> True", E.position_ouverte(ouverte))
check("position_ouverte : plat -> False", not E.position_ouverte(neuf))
en_vol = E.etat_neuf("ES", "U26")
en_vol["ordres_en_vol"] = ["cid-1"]
check("ordre_en_vol : liste non vide -> True", E.ordre_en_vol(en_vol))
check("ordre_en_vol : vide -> False", not E.ordre_en_vol(neuf))
cd = E.etat_neuf("ES", "U26")
cd["fin_cooldown_ms"] = T0 + 5000
check("en_cooldown : ts avant fin -> True", E.en_cooldown(cd, T0))
check("en_cooldown : ts apres fin -> False", not E.en_cooldown(cd, T0 + 6000))
check("en_cooldown : None -> False (jamais bloque)",
      not E.en_cooldown(neuf, T0))

print("etat_exec : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
