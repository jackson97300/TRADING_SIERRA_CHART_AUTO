"""L'intention d'entree — le premier pas d'EXEC, teste avant tout ordre.

Verifie : le bracket B-ATR en TICKS depuis l'ATR seul (independant du prix de
fill) ; le sens lu du snapshot_id ; l'idempotence (une intention emise ne se
reecrit jamais) ; le fail-loud (snapshot_id mal forme, ATR nul, sym incoherent) ;
et le garde-fou souverain du pas 1 : ZERO ordre, aucun import DTC dans le module.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3.execution import intentions as I                          # noqa: E402

PASSED = 0
FAILED = 0


def check(nom, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("  %-38s PASS" % nom)
    else:
        FAILED += 1
        print("  %-38s FAIL %s" % (nom, detail))


TS = 1788540300000
S_BATR = {"seuils": {"sl_atr": 1.0, "tp_atr": 1.5, "expiration_barres": 20}}
PASSE_S = {"ts": TS, "sym": "NQ", "hypothese": "ombre1",
           "decision": "PASSE", "motif": "", "snapshot_id": "NQ:13:S"}
PASSE_L = dict(PASSE_S, snapshot_id="NQ:13:L")

# --- l'objet pur -----------------------------------------------------------
it = I.intention(PASSE_S, atr=10.0, contrat="U26", tick=0.25, s_batr=S_BATR)
check("etat EMISE", it["etat"] == "EMISE")
check("taille 1", it["taille"] == 1)
check("side S -> -1", it["side"] == -1)
check("side L -> +1",
      I.intention(PASSE_L, 10.0, "U26", 0.25, S_BATR)["side"] == 1)
check("contrat porte", it["contrat"] == "U26")
# B-ATR en ticks : 1,0*10/0,25 = 40 ; 1,5*10/0,25 = 60
check("sl_ticks ENTIER = round(sl_atr*atr/tick)",
      it["barriere"]["sl_ticks"] == 40 and isinstance(it["barriere"]["sl_ticks"], int),
      str(it["barriere"]))
check("tp_ticks ENTIER",
      it["barriere"]["tp_ticks"] == 60 and isinstance(it["barriere"]["tp_ticks"], int))
check("sl/tp_ticks_exact gardes (parite B-ATR)",
      it["barriere"]["sl_ticks_exact"] == 40.0
      and it["barriere"]["tp_ticks_exact"] == 60.0)
check("barriere porte ses SOURCES (atr_pts/tick/sl_atr/tp_atr)",
      it["barriere"]["atr_pts"] == 10.0 and it["barriere"]["tick"] == 0.25
      and it["barriere"]["sl_atr"] == 1.0 and it["barriere"]["tp_atr"] == 1.5)
check("expiration portee", it["barriere"]["expiration_barres"] == 20)
check("sortie_horaire_et defaut = 15h55 (955)", it["sortie_horaire_et"] == 955)
check("sortie_horaire_et C2_EOD = 16h00 (960)",
      I.intention(dict(PASSE_S, hypothese="C2_EOD"), 10.0, "U26", 0.25,
                  S_BATR)["sortie_horaire_et"] == 960)
# la propriete-cle : PAS de prix absolu (fill-independant, anti-peek)
check("aucun prix de fill dans le bracket",
      "sl_prix" not in it["barriere"] and "tp_prix" not in it["barriere"])
check("entree MKT", it["entree"]["type"] == "MKT")
check("au_plus_tard = t+1_open + delai",
      it["entree"]["au_plus_tard_ms"] == TS + I.DUREE_BARRE_MS + I.DELAI_MAX_S * 1000)
check("snapshot_id = cle d'idempotence", it["snapshot_id"] == "NQ:13:S")

# le bracket ne depend QUE de l'ATR : deux ATR -> deux brackets, meme tick
it20 = I.intention(PASSE_S, atr=20.0, contrat="U26", tick=0.25, s_batr=S_BATR)
check("bracket suit l'ATR (20 -> sl 80)", it20["barriere"]["sl_ticks"] == 80)

# --- point 4 : deux PASSE meme barre, sens opposes -> conflit ---------------
p_l = {"ts": TS, "sym": "NQ", "snapshot_id": "NQ:13:L"}
p_s = {"ts": TS, "sym": "NQ", "snapshot_id": "NQ:13:S"}
p_autre = {"ts": TS + 900000, "sym": "NQ", "snapshot_id": "NQ:14:L"}
conflit = I._barres_en_conflit([p_l, p_s, p_autre])
check("meme barre L+S -> conflit", ("NQ", TS) in conflit)
check("barre a un seul sens -> pas de conflit", ("NQ", TS + 900000) not in conflit)
check("meme sens meme barre -> pas de conflit",
      I._barres_en_conflit([p_l, dict(p_l)]) == set())

# --- fail-loud -------------------------------------------------------------
def leve(fn):
    try:
        fn()
        return False
    except (ValueError, KeyError):
        return True


check("snapshot_id mal forme -> leve",
      leve(lambda: I._parse_snapshot("NQ:13")))
check("snapshot_id sens absent -> leve",
      leve(lambda: I._parse_snapshot("NQ:13:X")))
check("ATR nul -> leve",
      leve(lambda: I.intention(PASSE_S, 0.0, "U26", 0.25, S_BATR)))
check("ATR None -> leve",
      leve(lambda: I.intention(PASSE_S, None, "U26", 0.25, S_BATR)))
check("ATR minuscule -> bracket < 1 tick leve (R1)",
      leve(lambda: I.intention(PASSE_S, 0.1, "U26", 0.25, S_BATR)))
check("sym incoherent -> leve",
      leve(lambda: I.intention(dict(PASSE_S, sym="ES"), 10.0, "U26", 0.25, S_BATR)))

# --- idempotence -----------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    chemin = os.path.join(tmp, "intentions_20260904.jsonl")
    deja = I.snapshot_ids_emis(chemin)
    a = I.emettre(it, chemin, deja)
    b = I.emettre(it, chemin, deja)                    # meme snapshot_id
    c = I.emettre(I.intention(PASSE_L, 10.0, "U26", 0.25, S_BATR), chemin, deja)
    lignes = [json.loads(x) for x in open(chemin, encoding="utf-8")]
    check("emise 1re fois", a is True)
    check("re-emission ignoree (idempotent)", b is False)
    check("snapshot_id different -> ecrit", c is True)
    check("2 lignes au total", len(lignes) == 2, "%d" % len(lignes))
    # relecture a froid : l'idempotence survit au redemarrage (set relu)
    d = I.emettre(it, chemin)                          # deja=None -> relit le fichier
    check("idempotent apres relecture disque", d is False)

# --- I2 : regression contre une derive de la reconstruction du df ----------
# Epingle le bracket du signal REEL NQ:13:S du 04/09 contre le B-ATR gele
# (journal barrieres : atr_pts=58.61, sl=234.4 t, tp=351.6 t). Si un jour
# injecter_recalculs/chauffe_1min derivent, atr_barre change et CE test tombe
# AVANT qu'EXEC ne pose un SL/TP faux en silence (regle sizing/SL/TP 27/05).
TS_REG = 1788540300000
atrs = I._atr_par_ts("20260904", [])
atr_reg = atrs.get(("NQ", TS_REG))
if atr_reg is None:
    print("  [I2] donnees 20260904 absentes — regression NON verifiee (SKIP)")
else:
    reg = I.intention({"ts": TS_REG, "sym": "NQ", "hypothese": "ombre1",
                       "snapshot_id": "NQ:13:S"}, atr_reg, "U26",
                      I.get_tick_size("NQ"), I.B.charger_seuils()["B-ATR"])
    check("[I2] atr_barre NQ 04/09 fige a 58.61", round(atr_reg, 2) == 58.61,
          "%.4f" % atr_reg)
    check("[I2] sl_ticks ENTIER fige a 234", reg["barriere"]["sl_ticks"] == 234,
          str(reg["barriere"]))
    check("[I2] tp_ticks ENTIER fige a 352", reg["barriere"]["tp_ticks"] == 352)
    check("[I2] exact garde la parite (234.4 / 351.6)",
          round(reg["barriere"]["sl_ticks_exact"], 1) == 234.4
          and round(reg["barriere"]["tp_ticks_exact"], 1) == 351.6)

# --- garde-fou souverain du pas 1 : ZERO ORDRE -----------------------------
src = (RACINE / "V3" / "execution" / "intentions.py").read_text(encoding="utf-8")
imports = [l for l in src.splitlines()
           if l.strip().startswith(("import ", "from "))]
check("aucun import DTC/order",
      all("dtc" not in l.lower() and "order" not in l.lower() for l in imports),
      str([l for l in imports if "dtc" in l.lower() or "order" in l.lower()]))
INTERDITS = ("SUBMIT_NEW", "dtc_connector", "OrderStatus", "OCO",
             "send_order", "place_order", "\"Type\": 208")
presents = [t for t in INTERDITS if t in src]
check("aucun jeton d'ordre dans le code", not presents, str(presents))

print("intentions : %d PASS, %d FAIL" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
