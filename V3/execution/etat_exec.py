"""L'ETAT D'EXECUTION — la verite partagee entre EXEC (qui ECRIT) et le
coureur (qui LIT). Pas 2 du PLAN_ENTREE_EXEC (§3).

    etat_<sym>.json  {position, ordres_en_vol, pnl_jour, fin_cooldown_ms,
                      contrat, dernier_trade, ts_maj}

Ce que les trois bots morts n'avaient pas : un etat que decision et execution
lisent PAREIL. Ici EXEC ecrit atomiquement (`.tmp` + `os.replace` — un kill dur
ne laisse jamais un demi-fichier), et le coureur relit. `ts_maj` est la clef de
surete : un etat plus vieux que `ttl_s` est un TROU, jamais un feu vert — un
etat perime apres un crash ne doit PAS autoriser un ordre (§3).

PERIMETRE (pas 2, avant le gel) : ce module ne fait qu'ECRIRE et LIRE l'etat,
plus les accesseurs que les portes live consommeront. Il N'ordonne pas, ne
touche AUCUNE porte gelee. Brancher `POSITION_OUVERTE` / `STOP_*` / `COOLDOWN`
sur cet etat en live est l'etape SUIVANTE (revue) : la porte `POSITION_OUVERTE`
lit `i <= libre_a` (un indice de barre FUTUR, concept hors-ligne) ; en live la
verite est un booleen `position ouverte ?`. Ce basculement modifie une porte
L0 gelee -> il attend l'avis de Fable et une revue, pas ce commit.

DECISIONS OUVERTES (Fable) : le TTL de `TROU_ETAT` (ici 120 s, provisoire) et
la reconciliation au boot (la verite = `get_open_orders` DU BROKER, jamais le
fichier — lecon V1) ne sont pas figes ici.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

_DOSSIER = "LOGS/etat"
# TTL de surete PROVISOIRE : au-dela, l'etat est un TROU. Ce n'est pas un seuil
# de marche mais une borne de fraicheur ; a caler sur la cadence reelle du
# coureur (question ouverte Fable). Conservateur par defaut.
TTL_DEFAUT_S = 120
# Un ts_maj DANS LE FUTUR n'est pas credible (on n'ecrit pas pour un instant qui
# n'a pas eu lieu) : une horloge corrigee en arriere le rendrait « frais » a
# jamais. Petite tolerance pour le slew benin (w32time), au-dela = TROU.
TOLERANCE_FUTUR_S = 2


def chemin(sym, dossier=_DOSSIER):
    return os.path.join(dossier, "etat_%s.json" % sym)


def _maintenant_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def etat_neuf(sym, contrat):
    """L'etat plat d'ouverture de journee — aucune position, rien en vol."""
    return {
        "sym": sym, "contrat": contrat,
        "position": {"sens": 0, "taille": 0, "prix_entree": None,
                     "ts_entree": None, "snapshot_id": None},
        "ordres_en_vol": [],           # client_order_id en attente de fill
        "pnl_jour": 0.0,
        "fin_cooldown_ms": None,       # None = aucun cooldown en cours
        "dernier_trade": None,         # {snapshot_id, issue, pnl, ts_sortie}
        "ts_maj": None,                # rempli par ecrire_etat
    }


def ecrire_etat(etat, maintenant_ms=None, dossier=_DOSSIER):
    """Ecrit l'etat ATOMIQUEMENT (`.tmp` + `os.replace`), estampille `ts_maj`.

    Rend l'etat ecrit (avec son `ts_maj`). Fail-loud : un etat sans `sym` ne
    sait pas ou aller, il leve plutot que d'ecrire au hasard.
    """
    sym = etat.get("sym")
    if not sym:
        raise ValueError("etat sans sym : impossible de choisir le fichier")
    etat = dict(etat, ts_maj=int(maintenant_ms if maintenant_ms is not None
                                 else _maintenant_ms()))
    c = chemin(sym, dossier)
    os.makedirs(os.path.dirname(c), exist_ok=True)
    tmp = c + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(etat, ensure_ascii=False))
    os.replace(tmp, c)
    return etat


def lire_etat(sym, maintenant_ms, ttl_s=TTL_DEFAUT_S, dossier=_DOSSIER):
    """Rend `(etat, None)` si frais, `(None, motif)` sinon — un TROU n'est
    JAMAIS un etat vide qu'on prendrait pour « rien a signaler ».

    Motifs : `TROU_ETAT_ABSENT` (pas de fichier — jamais ecrit ou efface),
    `TROU_ETAT_ILLISIBLE` (json casse OU champ obligatoire manquant : la forme
    est validee AVANT de declarer frais, sinon l'appelant crashe au KeyError),
    `TROU_ETAT_PERIME` (`ts_maj` plus vieux que `ttl_s` : un crash a fige un
    etat qui ne reflete plus le compte), `TROU_ETAT_FUTUR` (`ts_maj` dans le
    futur : horloge non credible, cf `TOLERANCE_FUTUR_S`).
    """
    c = chemin(sym, dossier)
    if not os.path.exists(c):
        return None, "TROU_ETAT_ABSENT"
    try:
        with open(c, encoding="utf-8") as fh:
            etat = json.loads(fh.read())
        ts_maj = int(etat["ts_maj"])
        # la forme que E1/E2/E6 liront doit exister AVANT « frais » (R2)
        if ("sens" not in etat.get("position", {})
                or "ordres_en_vol" not in etat or "pnl_jour" not in etat):
            raise KeyError("forme d'etat incomplete")
    except (ValueError, KeyError, TypeError):
        return None, "TROU_ETAT_ILLISIBLE"
    ecart_s = (maintenant_ms - ts_maj) / 1000.0
    if ecart_s > ttl_s:
        return None, "TROU_ETAT_PERIME"
    if ecart_s < -TOLERANCE_FUTUR_S:               # ts_maj dans le futur (R1)
        return None, "TROU_ETAT_FUTUR"
    return etat, None


# --- accesseurs que les portes LIVE consommeront (cablage = etape suivante) --
def position_ouverte(etat):
    """Y a-t-il une position ? (LIVE : le booleen que `POSITION_OUVERTE`
    lira, a la place de `i <= libre_a` qui est un concept hors-ligne)."""
    return etat["position"]["sens"] != 0


def ordre_en_vol(etat):
    """Un ordre attend-il son fill ? (futur `ORDRE_EN_VOL`, E2)."""
    return len(etat.get("ordres_en_vol") or []) > 0


def en_cooldown(etat, ts_ms):
    """Le cooldown court-il encore a `ts_ms` ? Meme predicat que la porte
    (`ts < fin_cooldown`), avec None = pas de cooldown."""
    fin = etat.get("fin_cooldown_ms")
    return fin is not None and ts_ms < int(fin)


def main():
    """Sonde manuelle : ecrit un etat plat et le relit. Zero ordre."""
    os.chdir(RACINE)
    sym = sys.argv[1] if len(sys.argv) > 1 else "ES"
    e = ecrire_etat(etat_neuf(sym, "U26"))
    lu, motif = lire_etat(sym, _maintenant_ms())
    print("ecrit %s ts_maj=%s ; relu motif=%s position_ouverte=%s"
          % (chemin(sym), e["ts_maj"], motif,
             position_ouverte(lu) if lu else "n/a"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
