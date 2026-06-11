"""menthorq_v2_sierra_proxy.py — Proxy temporaire mq_gamma_condition Sierra-native.

Phase 5.0.A Sierra Full Migration (11/06/2026).

CONTEXTE :
==========
MenthorQ n'a PAS d'API publique generale (Jackson sur liste d'attente early
access). La seule source viable long terme est Sierra Chart (paid plan MenthorQ
de Jackson, etude MQ_GAMMA sur charts ES=2/NQ=25).

L'etude SC MQ_GAMMA fournit les NIVEAUX DE PRIX (mq_call, mq_put, mq_hvl,
mq_gex[10]) mais PAS l'agregat `Net_GEX` (somme algebrique des positions
dealers). Le `mq_gamma_condition = 1 si net_gex > 0` n'est donc PAS
reconstructible directement depuis Sierra DMP.

WORKAROUND TEMPORAIRE :
=======================
Ce module fournit un PROXY de `mq_gamma_condition` derive depuis
`bool_gex_flip_zone` (Sierra natif, calcule par DMP_Transform.h:1731) :

  Sierra bool_gex_flip_zone :
    1 = prix dans zone [Put_Support, Call_Resistance] = VOLATILE (short gamma)
    0 = prix hors zone = STABLE (long gamma)

  Proxy mq_gamma_condition (binaire, inverse) :
    1 = stable (long gamma, hedge dealers mean-revert)
    0 = volatile (short gamma, amplifie trend)

CETTE SEMANTIQUE EST ALIGNEE AVEC LA REGLE JACKSON 21/04/2026 :
  "gamma_condition = 1 si net_gex > 0 (dealer long gamma, stabilisant)"

LIMITATION FINANCIERE (a savoir) :
==================================
Le proxy `flip_zone (prix entre put_support et call_resistance)` est
STRUCTURELLEMENT DIFFERENT de `net_gex > 0` (somme algebrique reelle des
positions dealers cross strikes). Cas de divergence connus :

  - Prix juste au-dessus de call_resistance avec net_gex toujours positif
    (long gamma persiste) -> proxy dit volatile, realite dit stable
  - Prix dans zone avec net_gex tres faible (~0) -> proxy dit volatile,
    realite est marginale (peu de hedge)
  - Regime exceptionnel (FOMC, opex week) avec structure GEX dominee par
    un strike unique -> proxy structurel decouple de la realite agregee

Pour le ML : la feature reste informative (la zone [put, call] est un
fait observable et exploite par les dealers locaux), mais sa distribution
sera fondamentalement differente du regime Databento historique. Tout modele
entraine sur Databento qui aurait appris a faire confiance a
`mq_gamma_condition` aura un REGIME SHIFT silencieux en passant sur proxy.

Pertinence ML a re-evaluer Phase 5.3 ml-trainer DSR Lopez sur backfill
6 mois Sierra-only. Si distribution >95% d'un cote (verif empirique
10/06 NQ : 97% volatile / 3% stable), quality_validator.py va DROP la
feature (regle quasi-constante seuil 95%). Decision Jackson requise sur
ce point (cf reserves R1 review code-reviewer 11/06).

REVERT QUAND API MQ DISPONIBLE :
================================
Jackson est sur liste d'attente API MenthorQ generale. Quand l'API sera
disponible :
  1. Restaurer pipeline scraper Python OU integration API directe
  2. Retirer ce proxy (mettre `_USE_PROXY = False` ou supprimer l'injection)
  3. Brancher source MenthorQ originale dans enricher_chain + sierra_pipeline
  4. Verifier coherence backtests avec et sans proxy (parity check)

Cf IDEAS_BACKLOG.md entree SIERRA-5.0-MQ-PROXY (2026-06-11).
Cf INCIDENT_LOG.md entree 2026-06-11 MENTHORQ_SCRAPER_DOWN.
Cf BOT_CHANGELOG.md entree 2026-06-11 Phase 5.0.A.

Auteur : MIA Trading V2 (Phase 5.0.A Sierra Migration)
"""
from __future__ import annotations

from typing import Callable, Optional


def compute_gamma_condition_proxy(
    bool_gex_flip_zone: Optional[float],
) -> Optional[int]:
    """Proxy mq_gamma_condition depuis bool_gex_flip_zone Sierra natif.

    Args:
        bool_gex_flip_zone : Sierra natif, 0 ou 1.
            1 = prix dans zone [Put, Call] = volatile (short gamma)
            0 = prix hors zone = stable (long gamma)

    Returns:
        int (0/1) : proxy mq_gamma_condition (inverse).
            1 = stable (long gamma) = bool_gex_flip_zone == 0
            0 = volatile (short gamma) = bool_gex_flip_zone == 1
        None : si bool_gex_flip_zone absent OU invalide
               (Sierra MQ etude non chargee).

    Convention sémantique conservee :
        gamma_condition = 1 = stabilisant (mean revert, pinning)
        gamma_condition = 0 = amplifiant (trend, vol)

    Cf menthorq_backfill_injector.py:148 formule originale Databento.

    Defense in depth :
        - None -> None (fail-closed downstream)
        - float non-binaire (0.5, 1.5...) -> None (Sierra emit 0.0/1.0 strict
          depuis DMP_Transform.h:1731, donc tout float autre = bug a flagger)
        - str, list, dict -> None

    Examples:
        >>> compute_gamma_condition_proxy(0)  # zone stable
        1
        >>> compute_gamma_condition_proxy(1)  # flip zone volatile
        0
        >>> compute_gamma_condition_proxy(None)  # Sierra MQ etude absente
        None
        >>> compute_gamma_condition_proxy(0.5)  # invalid (Sierra ne devrait pas)
        None
    """
    if bool_gex_flip_zone is None:
        return None

    # Defense in depth : float non-binaire = bug Sierra a flagger
    if isinstance(bool_gex_flip_zone, float):
        if bool_gex_flip_zone not in (0.0, 1.0):
            return None

    try:
        flip = int(bool_gex_flip_zone)
    except (ValueError, TypeError):
        return None

    if flip not in (0, 1):
        return None

    # Inverse : flip_zone=0 (stable) -> gamma=1 (long gamma)
    #           flip_zone=1 (volatile) -> gamma=0 (short gamma)
    return 1 - flip


def inject_gamma_condition_proxy(
    payload: dict,
    log_fn: Optional[Callable] = None,
    sym: str = "?",
) -> dict:
    """Injection proxy mq_gamma_condition dans payload enrichi.

    A appeler dans enricher_chain.compose_enriched_payload() (mode Databento)
    ET dans sierra_pipeline.SierraPipelineOrchestrator.enrich_bar() (mode Sierra).

    POLITIQUE DE NON-OVERWRITE :
        Si payload contient deja mq_gamma_condition non-None (source originale
        Databento ou autre), on PRESERVE la valeur originale.
        Le proxy n'est injecte QUE si mq_gamma_condition est absent ou None.

    LOGGING TRACABILITE (regle souveraine Jackson 01/05/2026) :
        Si log_fn fourni, emit un code par cas :
        - MQ_PROXY_INJECTED : proxy injecte avec succes (INFO)
        - MQ_PROXY_SKIPPED_NO_FLIP_ZONE : flip_zone absent (ALERTE = anomalie
          a investiguer car Sierra DMP devrait toujours emettre flip_zone)
        - MQ_PROXY_PRESERVED_ORIGINAL : source originale preservee (INFO)

    Args:
        payload : dict bar enrichi (Sierra ou Databento).
        log_fn : Callable(code: str, **kwargs) optional. Pour audit J+1.
        sym : symbole pour log context (ES/NQ/MGC...).

    Returns:
        payload modifie in-place ET retourne pour chainage.

    Behavior:
        - Si payload["mq_gamma_condition"] existe et non-None : INCHANGE
          (+ emit MQ_PROXY_PRESERVED_ORIGINAL si log_fn)
        - Si absent/None + bool_gex_flip_zone disponible : injection proxy
          (+ emit MQ_PROXY_INJECTED si log_fn)
        - Si absent/None + bool_gex_flip_zone absent : reste None (fail-closed
          downstream) (+ emit MQ_PROXY_SKIPPED_NO_FLIP_ZONE si log_fn)
    """
    existing = payload.get("mq_gamma_condition")
    if existing is not None:
        if log_fn is not None:
            try:
                log_fn("MQ_PROXY_PRESERVED_ORIGINAL", sym=sym)
            except Exception:  # noqa: BLE001 - log non bloquant
                pass
        return payload  # source originale prioritaire

    flip = payload.get("bool_gex_flip_zone")
    proxy = compute_gamma_condition_proxy(flip)
    if proxy is not None:
        payload["mq_gamma_condition"] = proxy
        payload["_mq_gamma_source"] = "sierra_proxy_v2"  # tracabilite
        if log_fn is not None:
            try:
                log_fn("MQ_PROXY_INJECTED", gamma=proxy, flip=flip, sym=sym)
            except Exception:  # noqa: BLE001
                pass
    else:
        if log_fn is not None:
            try:
                log_fn("MQ_PROXY_SKIPPED_NO_FLIP_ZONE", sym=sym)
            except Exception:  # noqa: BLE001
                pass

    return payload
