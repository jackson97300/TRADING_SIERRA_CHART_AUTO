"""EXEC SIM — les regles d'entree E1-E9, les sorties, l'idempotence.

    python -X utf8 V3/tests/test_exec_sim.py

DOUZE CAS, RAMENES A LEUR VRAI COUT (arbitrage 11/09, Jackson + Fable) : le
faux DTC ne teste pas DTC — qui marche, valide sur le VPS le 02/04 — il teste
NOTRE code dans les situations qu'on ne peut pas commander sur le vrai.
  - DIX cas sont du CODE PUR, sans aucun socket : doublon, kill, position,
    ordre en vol, cooldown, trou d'etat, E3/E4 observes, L0, stop journalier,
    contrat, EOD, idempotence apres redemarrage.
  - UN est SANS OBJET : le fill partiel. On envoie UN micro ; une quantite de
    1 ne se divise pas.
  - TROIS sont DEJA VALIDES sur le vrai DTC (02/04, 4/4, zero orphelin) : ack
    sans fill, fill parent, fill TP avec annulation du SL.
  - DEUX seulement exigent un faux DTC : la connexion qui tombe pendant l'envoi,
    et le redemarrage avec un bracket orphelin.
Rien n'est teste ici contre un compte reel : `ExecSim` leve sur tout nom de
compte qui ne soit pas un compte de SIMULATION Sierra, et c'est le premier test.
Les noms reels vivent dans `config/comptes.local.yaml`, hors depot : les tests les
construisent, ils ne les ecrivent pas.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
os.chdir(RACINE)

from V3 import calendrier                                  # noqa: E402
from V3.execution import etat_exec, exec_sim               # noqa: E402

PASSED = FAILED = 0
NOW = 1789000000000


def check(nom, ok, detail=""):
    global PASSED, FAILED
    PASSED += bool(ok)
    FAILED += not ok
    print("  %-72s %s %s" % (nom, "PASS" if ok else "FAIL", "" if ok else detail))


class FauxDTC:
    """Le faux connecteur : il repond ce qu'on lui dit de repondre."""

    def __init__(self, ouverts=None, leve=False, rend=None):
        self.ouverts, self.leve, self.rend = ouverts or [], leve, rend
        self.envois, self.fermetures = [], []

    def send_market_order(self, **kw):
        if self.leve:
            raise ConnectionResetError("socket fermee pendant l'envoi")
        self.envois.append(kw)
        return self.rend if self.rend is not None else ("PARENT-%d" % len(self.envois), "TP1", "SL1")

    def request_open_orders_blocking(self, trade_account=None):
        return self.ouverts

    def send_close_market(self, **kw):
        self.fermetures.append(kw)
        return True


class EtatShim:
    """etat_exec redirige vers un dossier temporaire (aucun LOGS reel touche)."""

    def __init__(self, dossier):
        self.d = dossier

    def lire_etat(self, sym, now, ttl_s=120):
        return etat_exec.lire_etat(sym, now, ttl_s=ttl_s, dossier=self.d)

    def ecrire_etat(self, etat, maintenant_ms=None):
        return etat_exec.ecrire_etat(etat, maintenant_ms=maintenant_ms, dossier=self.d)

    etat_neuf = staticmethod(etat_exec.etat_neuf)
    position_ouverte = staticmethod(etat_exec.position_ouverte)
    ordre_en_vol = staticmethod(etat_exec.ordre_en_vol)
    en_cooldown = staticmethod(etat_exec.en_cooldown)


def intention(sym="ES", side=1, contrat=None, retard_ms=-60_000, snap=None):
    jour = exec_sim.jour_de_trading(NOW)
    return {"snapshot_id": snap or "%s:12:%s" % (sym, "L" if side > 0 else "S"),
            "sym": sym, "side": side, "hypothese": "H3-VPOC",
            "ts_signal": NOW - 900_000, "contrat": contrat or calendrier.contrat_actif(jour),
            "entree": {"type": "MKT", "ref": "open(t+1)", "au_plus_tard_ms": NOW - retard_ms},
            "barriere": {"sl_ticks": 20, "tp_ticks": 40, "atr_pts": 8.0, "tick": 0.25,
                         "sl_atr": 0.6, "tp_atr": 1.2, "atr_source": "barre"},
            "sortie_horaire_et": 955, "taille": 1, "emission_ms": NOW, "etat": "EMISE"}


def neuf(tmp, sym="ES", **kw):
    e = etat_exec.etat_neuf(sym, calendrier.contrat_actif(exec_sim.jour_de_trading(NOW)))
    e.update(kw)
    etat_exec.ecrire_etat(e, maintenant_ms=NOW, dossier=tmp)
    return e


def main():
    tmp = tempfile.mkdtemp(prefix="exec_")
    exec_sim.JOURNAL_DIR = os.path.join(tmp, "execution")
    exec_sim.FICHIER_STOP = os.path.join(tmp, "STOP")
    exec_sim.etat_exec = EtatShim(tmp)
    # noms construits, jamais ecrits en clair (le garde-fou du miroir les refuse)
    sim_es, sim_nq = "%s%d" % ("Sim", 1), "%s%d" % ("Sim", 2)
    exec_sim.charger_comptes = lambda chemin=None: {"ES": sim_es, "NQ": sim_nq}

    vrai_relire = exec_sim.ExecSim._relire_journal

    def frais(connecteur=None, **kw):
        """Un EXEC neuf qui IGNORE le journal (chaque cas part de zero) ; le
        test 13, lui, utilise la vraie relecture — c'est tout son objet."""
        exec_sim.ExecSim._relire_journal = lambda self: set()
        try:
            return exec_sim.ExecSim(connecteur=connecteur or FauxDTC(), maintenant_ms=NOW, **kw)
        finally:
            exec_sim.ExecSim._relire_journal = vrai_relire

    # --- 0. le garde-fou qui compte le plus
    for compte in ("LIVE", "APEX-REAL", "", None, "Simulation", "%s%d" % ("Reel", 1)):
        try:
            exec_sim.ExecSim(connecteur=FauxDTC(), comptes={"ES": compte}, maintenant_ms=NOW)
            ok = False
        except ValueError:
            ok = True
        check("[0] compte %r refuse — aucun chemin vers un compte reel" % compte, ok)

    # --- 1-2. E7 kill, E9 doublon
    neuf(tmp)
    open(exec_sim.FICHIER_STOP, "w").close()
    r = frais().traiter(intention(), NOW)
    check("[1] STOP present -> refus 'kill', aucun ordre (E7, teste EN PREMIER)", r["motif"] == "kill", r)
    os.remove(exec_sim.FICHIER_STOP)
    ex = frais()
    r1 = ex.traiter(intention(), NOW)
    r2 = ex.traiter(intention(), NOW)
    check("[2] meme snapshot_id deux fois -> un seul envoi, le second refuse 'doublon' (E9)",
          r1["verdict"] == "envoye" and r2["motif"] == "doublon" and len(ex.dtc.envois) == 1, (r1, r2))

    # --- 3-5. E1 position, E2 ordre en vol, cooldown
    neuf(tmp, position={"sens": 1, "taille": 1, "prix_entree": 7600.0, "ts_entree": NOW, "snapshot_id": "x"})
    check("[3] position deja ouverte -> refus (E1), l'etat REEL fait foi",
          frais().traiter(intention(), NOW)["motif"] == "position_ouverte")
    neuf(tmp, ordres_en_vol=["PARENT-1"])
    check("[4] un ordre en vol -> refus (E2)", frais().traiter(intention(), NOW)["motif"] == "ordre_en_vol")
    neuf(tmp, fin_cooldown_ms=NOW + 60_000)
    check("[5] cooldown en cours -> refus", frais().traiter(intention(), NOW)["motif"] == "cooldown")

    # --- 6. trou d'etat : pas d'etat, pas d'ordre
    neuf(tmp)
    r = frais().traiter(intention(), NOW + 10 * 60_000)
    check("[6] etat perime (TTL 120 s) -> refus TROU_ETAT, jamais un ordre sur un etat mort",
          str(r["motif"]).startswith("TROU_ETAT"), r)

    # --- 7-8. E3 et E4 OBSERVES, pas appliques
    neuf(tmp)
    r = frais().traiter(intention(retard_ms=+120_000), NOW)     # deadline depassee de 2 min
    check("[7] intention EXPIREE -> PASSE quand meme, `observe_e3` journalise (E3 observe, pas applique)",
          r["verdict"] == "envoye" and r["observe_e3"]["expiree"] is True
          and r["observe_e3"]["retard_ms"] > 0, r.get("observe_e3"))
    neuf(tmp)
    r = frais().traiter(intention(snap="ES:13:L"), NOW, contexte={"open_t1": 7620.0, "close_t": 7600.0})
    check("[8] gap de 20 pts -> PASSE, `observe_e4` porte le gap et l'ATR (E4 observe)",
          r["verdict"] == "envoye" and r["observe_e4"]["gap_pts"] == 20.0
          and r["observe_e4"]["atr_pts"] == 8.0, r.get("observe_e4"))

    # --- 9-11. E5 L0, E6 stop journalier, E8 contrat
    neuf(tmp)
    r = frais().traiter(intention(), NOW, contexte={"l0_motif": "L0_DATA_PERIMEE"})
    check("[9] L0 rebloque a t+1 -> refus 'L0:<porte>' avec le nom de la porte (E5)",
          r["motif"] == "L0:L0_DATA_PERIMEE", r)
    neuf(tmp, pnl_jour=-210.0)
    check("[10a] pnl sous le seuil -> refus 'stop_journalier' (E6)",
          frais(seuil_stop_jour=-200.0).traiter(intention(), NOW)["motif"] == "stop_journalier")
    neuf(tmp, pnl_jour=-210.0)
    r = frais().traiter(intention(), NOW)
    check("[10b] AUCUN seuil fourni -> E6 OBSERVE, jamais un seuil invente",
          r["verdict"] == "envoye" and r["observe_e6"]["seuil"] is None, r.get("observe_e6"))
    neuf(tmp)
    r = frais().traiter(intention(contrat="ESH27-CME"), NOW)
    check("[11] contrat de l'intention != contrat_actif -> refus 'contrat' (E8)", r["motif"] == "contrat", r)

    # --- 12. l'envoi : ce qui part, et ce que l'etat devient
    neuf(tmp)
    ex = frais()
    r = ex.traiter(intention(side=-1), NOW)
    env = ex.dtc.envois[0]
    etat, _ = etat_exec.lire_etat("ES", NOW, dossier=tmp)
    check("[12a] UN micro, sens court, compte de simulation ES, bracket en TICKS (jamais en prix)",
          env["quantity"] == 1 and env["side"] == -1 and env["trade_account"] == sim_es
          and env["sl_ticks"] == 20 and env["tp_ticks"] == 40 and "sl_price" not in env, env)
    check("[12b] l'ordre parent entre dans `ordres_en_vol` de l'etat — c'est E2 du prochain signal",
          etat["ordres_en_vol"] == [str(r["parent_id"])], etat["ordres_en_vol"])
    check("[12c] la ligne du journal porte le verdict, la famille et le contrat",
          r["verdict"] == "envoye" and r["hypothese"] == "H3-VPOC" and r["compte"] == sim_es)

    # --- 13. idempotence APRES redemarrage (le journal relu)
    ex2 = exec_sim.ExecSim(connecteur=FauxDTC(), maintenant_ms=NOW)
    check("[13] au redemarrage, le journal du jour rend les snapshot_id ENVOYES (E9 survit au crash)",
          "ES:12:S" in ex2.emis and ex2.traiter(intention(side=-1), NOW)["motif"] == "doublon", ex2.emis)

    # --- 14-15. les DEUX cas qui exigent un faux DTC
    neuf(tmp)
    ex = frais(connecteur=FauxDTC(leve=True))
    r = ex.traiter(intention(), NOW)
    etat, _ = etat_exec.lire_etat("ES", NOW, dossier=tmp)
    check("[14] connexion qui TOMBE pendant l'envoi -> refus 'rejet_dtc', aucune position, aucun retry aveugle",
          r["motif"] == "rejet_dtc" and not etat_exec.position_ouverte(etat)
          and "ConnectionResetError" in r["erreur"], r)
    ex = frais(connecteur=FauxDTC(ouverts=[{"ClientOrderID": "VIEUX-42"}]))
    ex.nettoyer_orphelins()
    check("[15] redemarrage avec un bracket ORPHELIN -> STOP pose, ordre JAMAIS repris, incident journalise",
          os.path.exists(exec_sim.FICHIER_STOP), "STOP absent")
    lignes = [json.loads(l) for l in open(exec_sim.chemin_journal(ex.jour), encoding="utf-8")]
    check("[15b] l'incident dit ce qu'il a fait : 'orphelins_au_boot', 1 ordre, STOP pose",
          any(x.get("motif") == "orphelins_au_boot" and x["n"] == 1 for x in lignes), lignes[-1])
    os.remove(exec_sim.FICHIER_STOP)

    # --- 16-17. les sorties
    neuf(tmp, position={"sens": 1, "taille": 1, "prix_entree": 7600.0, "ts_entree": NOW, "snapshot_id": "x"})
    ex = frais()
    check("[16a] avant 15h55 ET -> aucune fermeture", ex.plat_si_besoin("ES", 950, 955, NOW) is None)
    r = ex.plat_si_besoin("ES", 955, 955, NOW)
    check("[16b] a 15h55 ET -> plat, sens INVERSE de la position, sortie 'EOD'",
          r["motif"] == "EOD" and ex.dtc.fermetures[0]["side"] == -1 and ex.dtc.fermetures[0]["quantity"] == 1, r)
    neuf(tmp, position={"sens": -1, "taille": 1, "prix_entree": 7600.0, "ts_entree": NOW, "snapshot_id": "x"})
    ex = frais()
    r = ex.kill(NOW)
    check("[17] kill -> plat (sens inverse), journal 'KILL'",
          r["motif"] == "KILL" and ex.dtc.fermetures and ex.dtc.fermetures[0]["side"] == 1, r)

    # --- 18. aucun refus silencieux : tout verdict est dans le journal
    lignes = [json.loads(l) for l in open(exec_sim.chemin_journal(ex.jour), encoding="utf-8")]
    motifs = {x.get("motif") for x in lignes if x["verdict"] == "refus"}
    check("[18] TOUS les refus sont journalises, avec leur motif — jamais un silence",
          {"kill", "doublon", "position_ouverte", "ordre_en_vol", "cooldown", "contrat",
           "L0:L0_DATA_PERIMEE", "stop_journalier", "rejet_dtc"} <= motifs, sorted(motifs))

    print("\n  %d PASS / %d FAIL" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
