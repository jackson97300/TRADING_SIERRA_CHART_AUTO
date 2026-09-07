"""Le lien avec le VPS — hôte, chemin, scp du fichier du jour, journée courante.

Extrait de `coureur_live.py` (garde-fou : un fichier se relit, 300 lignes max).

RIEN de machine dans le code : l'hôte (`VPS_HOTE`) ET le chemin des données
(`VPS_CHEMIN_DONNEES`) vivent dans `comptes.local.yaml`, ignoré par git. Le
garde-fou du miroir refuse toute adresse IP, et son motif « chemin de machine »
voulait interdire exactement ce genre de fuite — on ne publie pas la topologie
d'une machine de production, même anodine en apparence.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))


def journee_courante():
    """La journée de trading : 22:00 UTC ouvre celle du lendemain (Globex).

    Dette DST connue (partagée avec `est_cash`) : en EST (nov-mars) Globex
    ouvre à 23:00 UTC — une heure par soir où le fichier du lendemain n'existe
    pas encore. Sans risque : « pas de fichier », et ça se résorbe seul.
    À traiter d'un bloc en novembre."""
    d = datetime.now(timezone.utc)
    if d.hour >= 22:
        d = d + timedelta(days=1)
    return d.strftime("%Y%m%d")


def config_vps():
    """(hôte, chemin données) lus dans `comptes.local.yaml`, ou (None, None)."""
    import yaml
    chemin = os.path.join(RACINE, "V3", "config", "comptes.local.yaml")
    if not os.path.exists(chemin):
        return None, None
    cfg = yaml.safe_load(open(chemin, encoding="utf-8")) or {}
    return cfg.get("VPS_HOTE"), cfg.get("VPS_CHEMIN_DONNEES")


def synchroniser(sym, jour, hote, chemin_donnees):
    """Tire le fichier du jour depuis le VPS. Rend False si le scp échoue —
    le cycle continue sur le fichier local, et `age_s` dira la vérité.

    Le chemin distant ne porte AUCUN guillemet : `subprocess` sans shell les
    passerait littéralement au serveur (« "C:/..." : No such file »), mesuré
    au premier run du 07/09. Un timeout ou un scp absent du PATH sont des
    échecs ATTENDUS du réseau : ils rendent False, jamais une exception."""
    src = "%s:%s/%s/%s_%s_sierra_enriched.jsonl" % (
        hote, chemin_donnees, sym, jour, sym)
    dst = os.path.join("DATA", "live_enriched", "sierra", sym) + os.sep
    try:
        r = subprocess.run(["scp", "-q", src, dst],
                           capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        print("  sync %s : %s" % (sym, type(e).__name__))
        return False
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "ignore").strip()
        print("  sync %s : %s" % (sym, err[:80] or "scp code %d" % r.returncode))
        return False
    return True
