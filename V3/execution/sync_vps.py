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
    dossier = os.path.join("DATA", "live_enriched", "sierra", sym)
    final = os.path.join(dossier, "%s_%s_sierra_enriched.jsonl" % (jour, sym))
    # ECRITURE ATOMIQUE — `.tmp` puis `os.replace` (11/09, incident).
    # `scp` ecrivait DIRECTEMENT sous le nom final : pendant la copie, le
    # fichier existe et il est PARTIEL. Le rejeu officiel du soir, qui le lit,
    # a plante dessus sur `PermissionError` et a EFFACE ses trois journaux par
    # conception — une course de quelques secondes a coute UNE JOURNEE DE
    # CAMPAGNE sur soixante-et-une. Le commentaire de `campagne.courir` notait
    # deja le meme accident le 08/09 (`ombre_c2` tombe de 8 lignes a 1).
    # Avec `os.replace`, un lecteur voit soit l'ANCIEN fichier complet, soit le
    # NOUVEAU complet, jamais un entre-deux. C'est la convention deja suivie
    # partout ailleurs dans le depot ; la synchro etait le dernier endroit a ne
    # pas la respecter. Et ce correctif est INDEPENDANT de la bascule VPS : la
    # course est entre le `scp` et le rejeu, pas entre les deux coureurs.
    tmp = final + ".tmp"
    os.makedirs(dossier, exist_ok=True)
    try:
        # CREATE_NO_WINDOW : lance detache (sans console), chaque scp
        # ouvrait SA fenetre noire au-dessus des graphiques — une par
        # minute et par instrument (vu par Jackson le 08/09 en seance).
        r = subprocess.run(["scp", "-q", src, tmp],
                           capture_output=True, timeout=120,
                           creationflags=0x08000000)
    except (subprocess.TimeoutExpired, OSError) as e:
        print("  sync %s : %s" % (sym, type(e).__name__))
        _effacer(tmp)
        return False
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "ignore").strip()
        print("  sync %s : %s" % (sym, err[:80] or "scp code %d" % r.returncode))
        _effacer(tmp)
        return False
    try:
        os.replace(tmp, final)
    except OSError as e:
        # Le fichier final est lu a cet instant : on garde l'ancien, intact.
        # Perdre une synchro n'est rien ; livrer un fichier partiel coute un
        # jour de campagne.
        print("  sync %s : bascule impossible (%s) — l'ancien fichier reste"
              % (sym, type(e).__name__))
        _effacer(tmp)
        return False
    return True


def _effacer(chemin):
    """Retire un `.tmp` laisse par une copie ratee — sans jamais lever."""
    try:
        if os.path.exists(chemin):
            os.remove(chemin)
    except OSError:
        pass
