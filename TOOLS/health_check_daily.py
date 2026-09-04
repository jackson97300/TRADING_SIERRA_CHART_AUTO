"""Controle de sante quotidien MIA — detecte ce qui a reellement coute cher.

Ne surveille que 3 choses, choisies sur la base des incidents constates :

  1. COLLECTE  : les JSONL live_enriched avancent-ils ? C'est l'actif principal
                 du projet. S'ils s'arretent, tout le reste devient inutile.
  2. BOUCLE    : des MARKET CLOSE partent-ils en rafale sans trade en face ?
                 Motif de l'INCIDENT #98 : ~6000 ordres emis a vide en 7 semaines,
                 personne n'a rien vu. Idem #70 (9 closes en 8 min).
  3. SERVICES  : les services critiques tournent-ils ?

Volontairement PAS de metrique de performance ici. Un bot qui perd de l'argent
est un probleme de strategie ; un bot qui emet 6000 ordres fantomes est un
probleme d'infrastructure. Ce script traite le second.

Usage (VPS, tache planifiee quotidienne) :
    python -X utf8 tools/health_check_daily.py
    python -X utf8 tools/health_check_daily.py --no-discord   # test a sec
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Seuils. Volontairement larges : on veut zero faux positif, sinon l'alerte
# devient du bruit et on cesse de la lire (cf regle awesome-monitoring :
# "si une alerte fire 3 fois sans action, la tuner ou la retirer").
MAX_COLLECTE_AGE_MIN = 90        # marche ferme le week-end -> voir _marche_ouvert
MAX_CLOSES_SANS_TRADE = 5        # au-dela = boucle (motif #98 : ~65/jour)
SERVICES_CRITIQUES = ("MIA-Sierra-Enricher-ES", "MIA-Dashboard")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _marche_ouvert() -> bool:
    """Heuristique simple : le CME est ferme du vendredi 22h UTC au dimanche 22h UTC."""
    n = _now()
    if n.weekday() == 5:                      # samedi
        return False
    if n.weekday() == 4 and n.hour >= 22:     # vendredi soir
        return False
    if n.weekday() == 6 and n.hour < 22:      # dimanche avant reouverture
        return False
    return True


def check_collecte(root: Path) -> list[dict]:
    """Le dernier JSONL live_enriched a-t-il ete ecrit recemment ?"""
    out = []
    for sym in ("ES", "NQ"):
        d = root / "DATA" / "live_enriched" / "sierra" / sym
        if not d.is_dir():
            out.append({"niveau": "CRITIQUE", "sujet": f"collecte {sym}",
                        "detail": f"dossier absent : {d}"})
            continue
        fichiers = sorted(d.glob("*_sierra_enriched.jsonl"))
        if not fichiers:
            out.append({"niveau": "CRITIQUE", "sujet": f"collecte {sym}",
                        "detail": "aucun fichier"})
            continue
        dernier = max(fichiers, key=lambda p: p.stat().st_mtime)
        age_min = (time.time() - dernier.stat().st_mtime) / 60.0
        if age_min > MAX_COLLECTE_AGE_MIN and _marche_ouvert():
            out.append({"niveau": "CRITIQUE", "sujet": f"collecte {sym}",
                        "detail": f"{dernier.name} fige depuis {age_min:.0f} min"})
        else:
            out.append({"niveau": "OK", "sujet": f"collecte {sym}",
                        "detail": f"{dernier.name} ({age_min:.0f} min)"})
    return out


def check_boucle_ordres(root: Path) -> list[dict]:
    """Des MARKET CLOSE partent-ils sans trade en face ? (motif INCIDENT #98)"""
    out = []
    jour = _now().strftime("%Y%m%d")
    d = root / "LOGS" / "execution"
    if not d.is_dir():
        return [{"niveau": "ALERTE", "sujet": "boucle ordres",
                 "detail": f"dossier absent : {d}"}]

    for f in sorted(d.glob(f"execution_{jour}_*.jsonl")):
        n_close = n_open = 0
        try:
            for ligne in f.open("r", encoding="utf-8", errors="replace"):
                if "MIA_CLOSE" in ligne:
                    n_close += 1
                if "TRADE_OPEN" in ligne or "ORDER_SENT" in ligne:
                    n_open += 1
        except OSError as e:
            out.append({"niveau": "ALERTE", "sujet": "boucle ordres",
                        "detail": f"lecture {f.name} : {e}"})
            continue

        if n_close > MAX_CLOSES_SANS_TRADE and n_open == 0:
            out.append({"niveau": "CRITIQUE", "sujet": "boucle ordres",
                        "detail": f"{f.name} : {n_close} MARKET CLOSE, 0 ouverture "
                                  f"en face (motif INCIDENT #98)"})
        elif n_close:
            out.append({"niveau": "OK", "sujet": "boucle ordres",
                        "detail": f"{f.name} : {n_close} close / {n_open} open"})
    if not out:
        out.append({"niveau": "OK", "sujet": "boucle ordres",
                    "detail": "aucun ordre aujourd'hui"})
    return out


def check_services() -> list[dict]:
    """Les services critiques tournent-ils ? (Windows uniquement)"""
    if not sys.platform.startswith("win"):
        return [{"niveau": "OK", "sujet": "services", "detail": "skip (hors Windows)"}]
    import subprocess
    out = []
    for svc in SERVICES_CRITIQUES:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Service -Name '{svc}' -ErrorAction SilentlyContinue).Status"],
                capture_output=True, text=True, timeout=30)
            statut = (r.stdout or "").strip() or "INTROUVABLE"
        except Exception as e:  # noqa: BLE001
            statut = f"ERREUR:{type(e).__name__}"
        niveau = "OK" if statut == "Running" else "ALERTE"
        out.append({"niveau": niveau, "sujet": f"service {svc}", "detail": statut})
    return out


def envoyer_discord(root: Path, anomalies: list[dict]) -> bool:
    """Alerte Discord via le DiscordAlerter existant. Ne leve jamais."""
    try:
        sys.path.insert(0, str(root))
        from BOT.discord_alerter import DiscordAlerter  # type: ignore
        alerter = DiscordAlerter()
        corps = "\n".join(f"[{a['niveau']}] {a['sujet']} : {a['detail']}"
                          for a in anomalies)
        alerter.send_crash("health_check_daily", corps[:1800])
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[health] envoi Discord impossible : {type(e).__name__}: {e}")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Controle de sante quotidien MIA.")
    p.add_argument("--root", default=None, help="racine du projet")
    p.add_argument("--no-discord", action="store_true", help="n'envoie rien")
    args = p.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]

    resultats: list[dict] = []
    for fn in (lambda: check_collecte(root), lambda: check_boucle_ordres(root),
               check_services):
        try:
            resultats.extend(fn())
        except Exception as e:  # noqa: BLE001
            # Un check qui plante ne doit jamais tuer la surveillance : c'est
            # exactement comme ca qu'on se retrouve aveugle pendant 7 semaines.
            resultats.append({"niveau": "ALERTE", "sujet": "health_check",
                              "detail": f"check en echec : {type(e).__name__}: {e}"})

    print(f"=== MIA health check — {_now():%Y-%m-%d %H:%M} UTC ===")
    for r in resultats:
        print(f"  [{r['niveau']:<8}] {r['sujet']:<28} {r['detail']}")

    anomalies = [r for r in resultats if r["niveau"] != "OK"]
    print(f"\n{len(anomalies)} anomalie(s) sur {len(resultats)} controles.")

    if anomalies and not args.no_discord:
        envoyer_discord(root, anomalies)

    # Trace persistante : permet de reconstituer l'historique meme sans Discord.
    try:
        d = root / "LOGS" / "health_checks"
        d.mkdir(parents=True, exist_ok=True)
        ligne = {"ts": _now().isoformat(), "n_anomalies": len(anomalies),
                 "resultats": resultats}
        with (d / f"health_{_now():%Y%m}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[health] trace non ecrite : {e}")

    return 1 if any(a["niveau"] == "CRITIQUE" for a in anomalies) else 0


if __name__ == "__main__":
    sys.exit(main())
