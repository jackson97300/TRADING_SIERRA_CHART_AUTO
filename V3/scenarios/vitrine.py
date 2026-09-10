"""SCÉNARIOS — LA VITRINE (A2) : une page sans état qui LIT le journal de
l'écrivain et l'affiche. `SPEC_VITRINE.md` dit ce qu'elle a le droit de faire.

    python -X utf8 V3/scenarios/vitrine.py            # http://localhost:8765

Routes : `/` → `vitrine.html` (la seule source HTML : desk, dashboard, stream) ;
`/etat.json` → `etat_courant()` ; `/noter` (POST, formulaire) → `noter.ecrire`
dans le journal manuel ; `/muet` (POST) → bascule le marqueur MUET.
Aucun seuil, aucune logique de scénario ici : ce qui s'affiche est ce que
l'écrivain a écrit. Un état « en cours, non validé » n'arme rien ; un
heartbeat de plus de `heartbeat_max_s` grise la page (« écrivain muet »).
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from V3.scenarios import alertes, carnet, lot, noter, scenarios, sorties   # noqa: E402

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vitrine.html")
HEARTBEAT = os.path.join(RACINE, "LOGS", "heartbeat_scenarios.json")
MESURE_W1 = os.path.join(scenarios.JOURNAL_DIR, "mesure_w1.json")


def age_heartbeat():
    try:
        d = json.load(open(HEARTBEAT, encoding="utf-8"))
        q = datetime.fromisoformat(d["quand_utc"])
        if q.tzinfo is None:
            q = q.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - q).total_seconds()
    except (OSError, ValueError, KeyError):
        return None


def _sorties(d):
    """Les sorties du scénario au dernier close, pour les deux sens — seulement
    si le scénario est validé (armé) : un état en cours n'arme rien."""
    if not d.get("arme"):
        return None
    out = {}
    for side, nom in ((1, "long"), (-1, "short")):
        s = sorties.b_scen(d["zones"], d["scenario_en_cours"], side, d["close"], d.get("atr_ref") or 0.0, d["sym"])
        out[nom] = {"tp": s["tp_prix"], "sl": s["sl_prix"], "texte": sorties.texte(s), "r": s["r_multiple"]}
    return out


def etat_courant(jour=None, seuils=None):
    """L'état que la page affiche : dernière ligne du journal DIRECT par
    instrument (repli : le rejeu du soir, marqué), heartbeat, alertes et
    validations récentes, zones triées par distance, sorties, muet."""
    s = seuils or lot.seuils()
    cfg = s["vitrine"]
    if jour is None:
        from V3.scenarios import boucle
        jour, _ = boucle.maintenant_et()
    lignes, source = scenarios.lire(scenarios.chemin_direct(jour)), "direct"
    if not lignes:
        lignes, source = scenarios.lire(scenarios.chemin_rejeu(jour)), "rejeu"
    age = age_heartbeat()
    out = {"jour": jour, "source": source, "heartbeat_age_s": None if age is None else round(age, 1),
           "ecrivain_muet": age is None or age > cfg["heartbeat_max_s"],
           "non_mesure_w1": not os.path.exists(MESURE_W1), "muet": alertes.muet(s["alertes"]),
           "genere_a": int(time.time() * 1000), "sym": {},
           "hier": carnet.hier(jour), "carnet": {k: v["compte"] for k, v in carnet.charger().get("types", {}).items()}}
    fen = cfg["fenetre_minutes"] * 60_000
    al = scenarios.lire(alertes.chemin_alertes(jour))
    for sym in ("ES", "NQ"):
        ls = [l for l in lignes if l["sym"] == sym]
        if not ls:
            continue
        d = max(ls, key=lambda x: x["i"])
        d.setdefault("atr_ref", None)
        zones = sorted(d["zones"], key=lambda z: abs(z["prix"] - d["close"]))
        out["sym"][sym] = {
            "heure_et": d["heure_et"], "close": d["close"], "titre": d["titre"], "etat_scenario": d["etat_scenario"],
            "scenario_en_cours": d["scenario_en_cours"], "precision": d.get("precision"), "arme": d.get("arme", False),
            "position_ouverture": d["position_ouverture"], "type_ouverture": d["type_ouverture"],
            "cote_hvl": d.get("cote_hvl"), "range": d.get("range"), "ib": d.get("ib"),
            "sequence": [e["etat"] + ("(%s)" % e.get("vers", e.get("type", "")) if e["etat"] in ("BASCULE", "TYPE_OUVERTURE") else "")
                         for e in d["sequence_etats"]],
            "validations": [v for v in d["validations"] if v["ts"] >= d["ts"] - fen],
            "invalidations": [v for v in d["invalidations"] if v["ts"] >= d["ts"] - fen],
            "bascules": d["bascules"],
            "zones": [{"nom": z["nom"], "prix": z["prix"], "bas": z["bas"], "haut": z["haut"], "role": z["role"],
                       "etat": z["fiche"]["etat"], "n_tests": z["fiche"]["n_tests"], "n_tenues": z["fiche"].get("n_tenues", 0),
                       "provisoire": z.get("provisoire"), "setups_armes": z.get("setups_armes", []),
                       "dist_ticks": round((z["prix"] - d["close"]) / lot.TICK, 1)} for z in zones],
            "prochaine_zone_haut": d.get("prochaine_zone_haut"), "prochaine_zone_bas": d.get("prochaine_zone_bas"),
            "ce_qui_ne_se_trade_pas": d.get("ce_qui_ne_se_trade_pas", []),
            "sorties": _sorties(d), "setups_hors_zones": d.get("setups_hors_zones", []),
            "setups_armes_motif": d.get("setups_armes_motif"),
            "alertes": [a for a in al if a["sym"] == sym and a["ts"] >= d["ts"] - fen],
            "grammaire_version": d.get("grammaire_version"), "confiance": None,
        }
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def _envoyer(self, code, corps, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps if isinstance(corps, bytes) else corps.encode("utf-8"))

    def do_GET(self):                                     # noqa: N802
        if self.path.startswith("/etat.json"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._envoyer(200, json.dumps(etat_courant(q.get("jour", [None])[0]), ensure_ascii=False, default=str))
        if self.path in ("/", "/index.html", "/vitrine.html"):
            return self._envoyer(200, open(HTML, encoding="utf-8").read(), "text/html; charset=utf-8")
        self._envoyer(404, json.dumps({"erreur": "inconnu"}))

    def do_POST(self):                                    # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
        champs = {k: v[0] for k, v in form.items()}
        if self.path == "/noter":
            try:
                jour = champs.pop("jour", None) or etat_courant()["jour"]
                c = noter.ecrire(jour, champs, etat_courant(jour))
                return self._envoyer(200, json.dumps({"ok": True, "ligne": c}, ensure_ascii=False))
            except ValueError as e:
                return self._envoyer(400, json.dumps({"ok": False, "erreur": str(e)}, ensure_ascii=False))
        if self.path == "/muet":
            return self._envoyer(200, json.dumps({"muet": alertes.basculer_muet()}))
        self._envoyer(404, json.dumps({"erreur": "inconnu"}))

    def log_message(self, *a):                            # pas de bruit console
        return


def servir(port=None):
    port = port or lot.seuils()["vitrine"]["port"]
    srv = http.server.ThreadingHTTPServer(("localhost", port), Handler)   # local seulement
    print("vitrine : http://localhost:%d  (Ctrl-C pour arreter)" % port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    os.chdir(RACINE)
    servir()
