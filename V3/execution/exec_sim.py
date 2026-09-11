"""EXEC SIM — le pas 3 : les intentions deviennent des ordres sur compte SIM.

    python -X utf8 V3/execution/exec_sim.py --un-tour      # un passage, sans boucle
    python -X utf8 V3/execution/exec_sim.py                # la boucle (Ctrl-C)

CE QU'IL FAIT : consomme les INTENTIONS emises par le coureur (pas 1), les
passe en ordres SIM sur Sierra via DTC, pose le bracket, ecrit l'etat, et
journalise CHAQUE verdict — jamais un refus silencieux. UN micro par
instrument, un compte de simulation par instrument (les noms vivent dans
`config/comptes.local.yaml`, hors depot).

CE QU'IL NE FAIT JAMAIS : decider (c'est la chaine), choisir une taille,
poser un ordre limite, lire un devenir, toucher un seuil, ecrire ailleurs
que dans son journal et `etat_<sym>.json`.

DEUX CORRECTIONS AU SQUELETTE (11/09, relecture croisee Claude Code / Fable) :

1. **Le connecteur est `BOT/dtc_connector.py`, PAS `V1_ARCHIVE`** — et il est
   IMPORTE, pas copie (une copie diverge en silence). Le squelette pointait
   vers V1, qui pose son bracket avec `SUBMIT_NEW_OCO_ORDER` (206),
   `IsParentOrder` et `ParentTriggerClientOrderID` : **les trois ont ete
   testes et REJETES le 02/04 — Sierra Chart en serveur DTC les ignore
   SILENCIEUSEMENT** (CLAUDE.md, tableau des bugs connus). Le code qui tourne
   fait l'inverse : trois ordres Type 208 separes + OCO gere a la main.
2. **La paire OCO est enregistree AVANT l'envoi des enfants** (fix du 04/05
   dans `BOT/`) : un TP rempli en 596 ms sur NQ arrivait avant l'enregistrement
   et l'annulation du jumeau echouait sans un mot — l'ordre orphelin en seance.
   V1 n'a pas ce fix. C'est la raison de fond de la correction 1 : `BOT/` n'est
   pas seulement le bon code, c'est celui qui a le PLUS de lecons.

CE QUI N'EST PAS ICI, ET POURQUOI : le pas 2b (L0 qui LIT cet etat) touche
`L0_POSITION_OUVERTE`, une porte GELEE par `campagne-ombre-1b` le 11/09 au
matin. EXEC ECRIT l'etat ; L0 le lira au cycle 2, ou sur decision explicite
avec un nouveau tag. Tant que ce n'est pas fait, les trois portes
(`STOP_JOURNALIER`, `POSITION_OUVERTE`, `COOLDOWN`) restent inertes cote
chaine — EXEC les applique pour lui-meme, via E1/E2/E6.

E3 (fraicheur) et E4 (gap) sont **OBSERVES, pas appliques** les deux premieres
semaines (PLAN_ENTREE_EXEC, regle souveraine : aucun seuil sans distribution) :
ils journalisent `observe_e3` / `observe_e4` et laissent passer. Le glissement
des intentions tardives EST la distribution qui posera `delai_max_s`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from CORE.constants import get_tick_size                        # noqa: E402
from V3 import calendrier                                       # noqa: E402
from V3.execution import etat_exec                              # noqa: E402

# Les NOMS de comptes ne sont nulle part dans le code : ils vivent dans
# `config/comptes.local.yaml`, ignore par git. Un nom de compte de trading
# n'a rien a faire dans un depot public, meme simule — le jour ou il passe en
# reel, il serait deja expose. Ici on ne garde que la FORME admise : un compte
# de SIMULATION Sierra, et rien d'autre. Tout autre nom leve a la construction.
MOTIF_COMPTE_SIM = re.compile(r"^%s[0-9]$" % "Sim")
FICHIER_STOP = os.path.join(RACINE, "LOGS", "STOP")
JOURNAL_DIR = os.path.join(RACINE, "LOGS", "execution")
BASCULE_JOUR_UTC_H = 22          # la journee de trading bascule a 22:00 UTC (incident 07/09)
CYCLE_S = 5
TTL_ETAT_S = 120


def jour_de_trading(maintenant_ms=None):
    d = datetime.fromtimestamp((maintenant_ms or int(time.time() * 1000)) / 1000, timezone.utc)
    if d.hour >= BASCULE_JOUR_UTC_H:
        d = d.replace(hour=0) + __import__("datetime").timedelta(days=1)
    return d.strftime("%Y%m%d")


def chemin_journal(jour):
    return os.path.join(JOURNAL_DIR, "exec_%s.jsonl" % jour)


def charger_comptes(chemin=None):
    """`config/comptes.local.yaml` -> {sym: compte}. Absent = on ne trade pas :
    EXEC ne devine JAMAIS un nom de compte."""
    import yaml
    p = chemin or os.path.join(RACINE, "V3", "config", "comptes.local.yaml")
    if not os.path.exists(p):
        raise FileNotFoundError(
            "comptes.local.yaml absent — copier comptes.example.yaml et le renseigner. "
            "EXEC ne devine pas un nom de compte.")
    cfg = yaml.safe_load(open(p, encoding="utf-8")) or {}
    comptes = {sym: cfg.get("COMPTE_%s" % sym) for sym in ("ES", "NQ")}
    manquants = [s for s, c in comptes.items() if not c]
    if manquants:
        raise ValueError("comptes.local.yaml : COMPTE_%s manquant" % ", COMPTE_".join(manquants))
    return comptes


class ExecSim:
    """Un exemplaire par processus ; il porte les deux instruments."""

    def __init__(self, connecteur=None, comptes=None, maintenant_ms=None, seuil_stop_jour=None):
        self.comptes = dict(comptes) if comptes is not None else charger_comptes()
        for sym, compte in self.comptes.items():
            if not (isinstance(compte, str) and MOTIF_COMPTE_SIM.match(compte)):
                raise ValueError("compte NON SIM refuse pour %s : %r — EXEC SIM n'a aucun "
                                 "chemin vers un compte reel" % (sym, compte))
        self.dtc = connecteur                     # injecte en test ; cree par `connecter()` sinon
        self.seuil_stop_jour = seuil_stop_jour    # None = E6 OBSERVE (aucun seuil invente)
        self.jour = jour_de_trading(maintenant_ms)
        self.emis = self._relire_journal()        # idempotence qui survit au redemarrage

    # --- connexion : le connecteur qui TOURNE, importe, jamais recopie -------
    def connecter(self):
        if self.dtc is not None:
            return True
        from BOT.dtc_connector import DTCConnector      # import tardif : les tests n'en ont pas besoin
        self.dtc = DTCConnector()
        if not self.dtc.connect():
            raise RuntimeError("DTC : connexion refusee — aucun ordre ne part")
        self.nettoyer_orphelins()
        return True

    def nettoyer_orphelins(self):
        """Au boot : un bracket sans intention connue est un INCIDENT, pas un
        heritage. On ne le reprend jamais ; on pose STOP et on attend un humain
        (reconciliation broker -> fichier -> journal, PLAN §2b)."""
        for sym, compte in self.comptes.items():
            try:
                ouverts = self.dtc.request_open_orders_blocking(trade_account=compte)
            except Exception as e:                    # noqa: BLE001 — un boot qui echoue ne trade pas
                self._ligne({"verdict": "incident", "motif": "open_orders_illisible",
                             "sym": sym, "erreur": "%s: %s" % (type(e).__name__, e)})
                continue
            orphelins = [o for o in (ouverts or []) if str(o.get("ClientOrderID", "")) not in self.emis]
            if orphelins:
                open(FICHIER_STOP, "w", encoding="utf-8").write(
                    "orphelins au boot %s : %d ordre(s) sans intention connue\n" % (sym, len(orphelins)))
                self._ligne({"verdict": "incident", "motif": "orphelins_au_boot", "sym": sym,
                             "n": len(orphelins), "action": "STOP pose, aucun ordre repris"})

    # --- le cycle : une intention -> un ordre, ou un refus journalise --------
    def traiter(self, intent, maintenant_ms=None, contexte=None):
        now = maintenant_ms or int(time.time() * 1000)
        sym = intent["sym"]
        if intent["snapshot_id"] in self.emis:
            return self._refus(intent, "doublon", now)
        motif, observations = self._verifier_entree(intent, now, contexte or {})
        if motif:
            return self._refus(intent, motif, now, observations)
        return self._executer(intent, now, observations)

    def _verifier_entree(self, intent, now, contexte):
        """E1-E9. Rend (motif | None, observations). La source de verite de
        l'etat est `etat_exec`, JAMAIS une simulation."""
        obs, sym = {}, intent["sym"]
        if os.path.exists(FICHIER_STOP):                                   # E7, d'abord
            return "kill", obs
        etat, trou = etat_exec.lire_etat(sym, now, ttl_s=TTL_ETAT_S)
        if trou:                                                            # pas d'etat = pas d'ordre
            return trou, obs
        if etat_exec.position_ouverte(etat):                                # E1
            return "position_ouverte", obs
        if etat_exec.ordre_en_vol(etat):                                    # E2
            return "ordre_en_vol", obs
        if etat_exec.en_cooldown(etat, now):
            return "cooldown", obs
        obs["observe_e3"] = {"retard_ms": now - int(intent["entree"]["au_plus_tard_ms"]),
                             "expiree": now > int(intent["entree"]["au_plus_tard_ms"])}
        if "open_t1" in contexte and "close_t" in contexte:                 # E4 observe
            obs["observe_e4"] = {"gap_pts": round(abs(contexte["open_t1"] - contexte["close_t"]), 4),
                                 "atr_pts": intent["barriere"]["atr_pts"]}
        if contexte.get("l0_motif"):                                        # E5
            return "L0:" + contexte["l0_motif"], obs
        if self.seuil_stop_jour is not None and etat.get("pnl_jour", 0.0) <= self.seuil_stop_jour:
            return "stop_journalier", obs                                   # E6
        obs["observe_e6"] = {"pnl_jour": etat.get("pnl_jour"), "seuil": self.seuil_stop_jour}
        actif = calendrier.contrat_actif(self.jour)                         # E8
        if intent["contrat"] != actif:
            obs["contrat_attendu"] = actif
            return "contrat", obs
        return None, obs

    def _executer(self, intent, now, obs):
        """UN micro, marche, bracket en TICKS autour du fill reel. Le connecteur
        pose trois ordres 208 separes et enregistre la paire OCO AVANT l'envoi."""
        sym, side = intent["sym"], intent["side"]
        compte, tick = self.comptes[sym], get_tick_size(sym)
        b = intent["barriere"]
        try:
            resultat = self.dtc.send_market_order(
                symbol=intent["contrat"], side=side, quantity=int(intent["taille"]),
                trade_account=compte, sl_ticks=int(b["sl_ticks"]), tp_ticks=int(b["tp_ticks"]),
                tick_size=tick)
        except Exception as e:                        # noqa: BLE001 — un rejet ne relance jamais tout seul
            return self._refus(intent, "rejet_dtc", now, dict(obs, erreur="%s: %s" % (type(e).__name__, e)))
        if not resultat or (isinstance(resultat, tuple) and not resultat[0]):
            return self._refus(intent, "rejet_dtc", now, dict(obs, resultat=str(resultat)))
        parent = resultat[0] if isinstance(resultat, tuple) else resultat
        self.emis.add(intent["snapshot_id"])
        etat, _ = etat_exec.lire_etat(sym, now, ttl_s=TTL_ETAT_S)
        etat = etat or etat_exec.etat_neuf(sym, intent["contrat"])
        etat["ordres_en_vol"] = list(etat.get("ordres_en_vol", [])) + [str(parent)]
        etat_exec.ecrire_etat(etat, maintenant_ms=now)
        return self._ligne({"verdict": "envoye", "snapshot_id": intent["snapshot_id"], "sym": sym,
                            "side": side, "compte": compte, "contrat": intent["contrat"],
                            "parent_id": str(parent), "sl_ticks": b["sl_ticks"], "tp_ticks": b["tp_ticks"],
                            "hypothese": intent.get("hypothese"), "ts": now, **obs})

    # --- sorties ------------------------------------------------------------
    def plat_si_besoin(self, sym, minutes_et, sortie_horaire_et, now=None):
        """A l'heure de sortie de la FAMILLE (portee par l'intention, jamais
        devinee) : plat. Jamais de position apres la cloture cash."""
        if minutes_et < int(sortie_horaire_et):
            return None
        now = now or int(time.time() * 1000)
        etat, _ = etat_exec.lire_etat(sym, now, ttl_s=TTL_ETAT_S)
        if not etat or not etat_exec.position_ouverte(etat):
            return None
        self.dtc.send_close_market(symbol=etat["contrat"], side=-etat["position"]["sens"],
                                   quantity=int(etat["position"]["taille"]),
                                   trade_account=self.comptes[sym])
        return self._ligne({"verdict": "sortie", "motif": "EOD", "sym": sym,
                            "minutes_et": minutes_et, "ts": now})

    def kill(self, now=None):
        """STOP present -> plat les deux, journal, arret propre."""
        now = now or int(time.time() * 1000)
        for sym in self.comptes:
            etat, _ = etat_exec.lire_etat(sym, now, ttl_s=TTL_ETAT_S)
            if etat and etat_exec.position_ouverte(etat):
                self.dtc.send_close_market(symbol=etat["contrat"], side=-etat["position"]["sens"],
                                           quantity=int(etat["position"]["taille"]),
                                           trade_account=self.comptes[sym])
        return self._ligne({"verdict": "sortie", "motif": "KILL", "ts": now})

    # --- journal : un ecrivain, jamais un refus silencieux -------------------
    def _refus(self, intent, motif, now, obs=None):
        return self._ligne({"verdict": "refus", "motif": motif, "snapshot_id": intent["snapshot_id"],
                            "sym": intent["sym"], "side": intent["side"],
                            "hypothese": intent.get("hypothese"), "ts": now, **(obs or {})})

    def _ligne(self, d):
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        d.setdefault("ts", int(time.time() * 1000))
        d.setdefault("jour", self.jour)
        with open(chemin_journal(self.jour), "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
        return d

    def _relire_journal(self):
        """Les snapshot_id deja ENVOYES aujourd'hui — l'idempotence survit au
        redemarrage (E9). Un refus ne compte pas : il peut etre retente."""
        p = chemin_journal(self.jour)
        if not os.path.exists(p):
            return set()
        out = set()
        for ln in open(p, encoding="utf-8"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("verdict") == "envoye" and d.get("snapshot_id"):
                out.add(d["snapshot_id"])
        return out


def main(argv=None):
    a = argparse.ArgumentParser(description="EXEC SIM — pas 3")
    a.add_argument("--un-tour", action="store_true", help="un passage, sans boucle")
    args = a.parse_args(argv)
    os.chdir(RACINE)
    if os.path.exists(FICHIER_STOP):
        print("STOP present : aucun ordre. Retirer LOGS/STOP pour reprendre.")
        return 2
    ex = ExecSim()
    ex.connecter()
    print("EXEC SIM connecte — comptes %s, jour %s, %d intention(s) deja envoyee(s)"
          % (ex.comptes, ex.jour, len(ex.emis)), flush=True)
    if args.un_tour:
        return 0
    while not os.path.exists(FICHIER_STOP):
        # BRANCHER lundi : lire les intentions EMISES du coureur et appeler
        # `ex.traiter(intent, contexte={...})`. Le contexte porte open_t1 /
        # close_t (E4 observe) et l0_motif (E5). Tant que ce fil n'est pas
        # branche, EXEC tourne a vide : il se connecte, nettoie, et n'ordonne rien.
        time.sleep(CYCLE_S)
    ex.kill()
    print("STOP : plat et arret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
