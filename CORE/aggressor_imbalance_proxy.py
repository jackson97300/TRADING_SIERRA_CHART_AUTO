"""aggressor_imbalance_proxy.py — Port Sierra-native de `aggressor_imbalance`.

Phase 5.0.B Sierra Full Migration (11/06/2026).

CONTEXTE :
==========
La feature `aggressor_imbalance` est utilisee par Bot3v4 (filtre sentiment, seuil
`aggro > -0.3`) et BN V5 (Niveau 3 BONUS). Source originale :
`CORE/phase_b_plus_plus_trades_streaming.py:248-252` :

  n_a = sum(1 for _, _, sd, _ in trades_data if sd == "A")  # aggressor ask (buy)
  n_b = sum(1 for _, _, sd, _ in trades_data if sd == "B")  # aggressor bid (sell)
  n_dir = n_a + n_b
  aggressor_imbalance = (n_a - n_b) / n_dir  if n_dir > 0 else 0.0

Semantique : ratio COMPTE de trades agressifs ask vs bid, range [-1, +1].

PROBLEME SIERRA :
=================
Sierra DMP ne fournit PAS de comptes trade-by-trade (`n_trades_ask`,
`n_trades_bid`). Il fournit uniquement des AGGREGATS volume :
  - buy_vol, sell_vol (volume agressif ask / bid)
  - avg_ask_size, avg_bid_size (taille moyenne trade par cote)
  - ask_pct, bid_pct (ratio volume)
  - ask_bid_imbalance = (ask_pct - 0.5) / 0.5 (volume-weighted)

Le drift sémantique compte (Phase B+) vs volume (Sierra `ask_bid_imbalance`)
casse les seuils calibres :
  - Bot3v4 seuil `aggro > -0.3` est cale sur distribution COMPTE
  - `ask_bid_imbalance` a une distribution differente (volume-weighted)
  - Aliaser silencieusement = bug garanti (cf incident SL hybride 27/05)

WORKAROUND :
============
RECONSTRUCTION du compte de trades agressifs via division volume / taille
moyenne par cote :

  n_buy_est  = buy_vol  / avg_ask_size   # ~ nombre trades buy aggressor
  n_sell_est = sell_vol / avg_bid_size   # ~ nombre trades sell aggressor
  n_dir_est  = n_buy_est + n_sell_est
  aggressor_imbalance_proxy = (n_buy_est - n_sell_est) / n_dir_est

Cette approximation preserve la semantique COUNT (pas drift seuil) car
elle reconstruit le nombre de trades.

LIMITATION CONNUE - DRIFT SIZE-ASYMMETRIC (fix I3 review 11/06) :
===================================================================
La moyenne `avg_ask_size` n'est PAS une statistique suffisante pour
reconstruire le compte si la distribution des tailles est asymetrique.

Cas pathologique illustre :
  buy_vol  = 1000, avg_ask_size = 1000 (1 gros ordre institutionnel)
  sell_vol = 1000, avg_bid_size = 10   (100 petits ordres retail HFT)

  Notre proxy :
    n_buy_est  = 1000 / 1000 = 1
    n_sell_est = 1000 / 10   = 100
    proxy = (1 - 100) / 101 = -0.98 (vendeurs dominent en COUNT)

  Versus `ask_bid_imbalance` Sierra natif (volume-weighted) :
    ask_pct = buy_vol / total_vol = 0.5
    ask_bid_imbalance = 0.0 (equilibre en VOLUME)

  Ecart 0.98 en absolu = drift majeur sur ce cas pathologique.

Sur ES/NQ futures RTH, ce scenario est REALISTE (1 institutional iceberg
ICE order + N HFT). Le proxy va donc produire des spikes plus frequents
que le `aggressor_imbalance` Databento original (qui compte aussi
trade-by-trade donc fait pareil) MAIS comparable a la source originale
Databento Phase B+ (qui compte aussi trade-by-trade).

Conclusion : le proxy est COHERENT avec la source Databento (les 2
comptent les trades), donc les seuils Bot3v4 `aggro > -0.3` restent
valides. Le drift n'est pas vs Databento original (qui partage la
sensibilite) mais vs `ask_bid_imbalance` volume-weighted (qui est
sa propre feature distincte).

Validation parity : tools/parity_aggressor_proxy.py (a creer) doit
mesurer correlation Spearman > 0.6 sur 100+ bars Sierra+Databento
equivalents, dans les 7j post-deploy (fix I1 review 11/06).

Auteur : MIA Trading V2 (Phase 5.0.B Sierra Migration)
"""
from __future__ import annotations

from typing import Callable, Optional


def compute_aggressor_imbalance_proxy(
    buy_vol: Optional[float],
    sell_vol: Optional[float],
    avg_ask_size: Optional[float],
    avg_bid_size: Optional[float],
) -> Optional[float]:
    """Estimation aggressor_imbalance count-based depuis aggregats Sierra.

    Args:
        buy_vol      : volume agressif ask (acheteur agresse) — Sierra DMP.
        sell_vol     : volume agressif bid (vendeur agresse) — Sierra DMP.
        avg_ask_size : taille moyenne des trades cote ask — Sierra DMP.
        avg_bid_size : taille moyenne des trades cote bid — Sierra DMP.

    Returns:
        float : aggressor_imbalance_proxy dans [-1, +1].
            > 0 : buyers agresses dominent (ask aggressor count majoritaire)
            < 0 : sellers agresses dominent (bid aggressor count majoritaire)
            0.0 : equilibre OR division par zero (fail-safe)
        None : si au moins un input est None OU invalide.

    Convention semantique conservee :
        proxy ~ (n_aggressor_ask - n_aggressor_bid) / n_total_aggressor
        Comparable a seuils Bot3v4 (`aggro > -0.3`) et BN V5 (`aggressor_min`).

    Examples:
        >>> # Cas equilibre
        >>> compute_aggressor_imbalance_proxy(100.0, 100.0, 2.0, 2.0)
        0.0
        >>> # Cas buyers dominent (138 buy vol / 2.22 size = 62 trades vs 39 sells)
        >>> v = compute_aggressor_imbalance_proxy(138.0, 74.0, 2.2258, 1.8974)
        >>> 0.20 < v < 0.30  # ~0.228
        True
        >>> # Cas total_vol = 0
        >>> compute_aggressor_imbalance_proxy(0.0, 0.0, 0.0, 0.0)
        0.0
        >>> # Cas None
        >>> compute_aggressor_imbalance_proxy(None, 100.0, 2.0, 2.0)
        >>> # None
    """
    if buy_vol is None or sell_vol is None:
        return None
    if avg_ask_size is None or avg_bid_size is None:
        return None

    try:
        buy_vol_f = float(buy_vol)
        sell_vol_f = float(sell_vol)
        avg_ask_f = float(avg_ask_size)
        avg_bid_f = float(avg_bid_size)
    except (ValueError, TypeError):
        return None

    # NaN detection
    if (buy_vol_f != buy_vol_f or sell_vol_f != sell_vol_f
        or avg_ask_f != avg_ask_f or avg_bid_f != avg_bid_f):
        return None

    # Edge case : tailles moyennes nulles (bar sans trades sur ce side)
    # On utilise un fallback : si une side a avg_size=0 mais vol>0, on ne peut
    # pas estimer le nombre de trades. Retour 0.0 (equilibre fail-safe).
    if avg_ask_f <= 0.0 and avg_bid_f <= 0.0:
        return 0.0  # bar muette

    # Reconstruction nombre de trades estime
    n_buy_est = (buy_vol_f / avg_ask_f) if avg_ask_f > 0.0 else 0.0
    n_sell_est = (sell_vol_f / avg_bid_f) if avg_bid_f > 0.0 else 0.0
    n_dir_est = n_buy_est + n_sell_est

    if n_dir_est <= 0.0:
        return 0.0  # aucune activite agressive

    imbalance = (n_buy_est - n_sell_est) / n_dir_est

    # Clamp [-1, +1] (defense in depth, devrait toujours etre dans cet intervalle)
    if imbalance > 1.0:
        return 1.0
    if imbalance < -1.0:
        return -1.0
    return imbalance


def inject_aggressor_imbalance_proxy(
    payload: dict,
    log_fn: Optional[Callable] = None,
    sym: str = "?",
) -> dict:
    """Injection proxy aggressor_imbalance dans payload enrichi.

    A appeler dans `sierra_pipeline.SierraPipelineOrchestrator.enrich_bar()`
    apres Phase 3.

    POLITIQUE DE NON-OVERWRITE :
        Si payload contient deja `aggressor_imbalance` non-None (source
        originale Databento Phase B+), on PRESERVE la valeur originale.
        Le proxy n'est injecte QUE si `aggressor_imbalance` est absent ou None.

    LOGGING TRACABILITE (regle souveraine Jackson 01/05/2026) :
        Si log_fn fourni, emit un code par cas :
        - AGGRESSOR_PROXY_INJECTED : proxy injecte (INFO)
        - AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS : inputs manquants (ALERTE)
        - AGGRESSOR_PROXY_PRESERVED_ORIGINAL : source originale preservee (INFO)

    Args:
        payload : dict bar enrichi (Sierra ou hybride).
        log_fn  : Callable(code: str, **kwargs) optional.
        sym     : symbole pour log context (ES/NQ/MGC).

    Returns:
        payload modifie in-place ET retourne pour chainage.
    """
    existing = payload.get("aggressor_imbalance")
    if existing is not None:
        if log_fn is not None:
            try:
                log_fn("AGGRESSOR_PROXY_PRESERVED_ORIGINAL", sym=sym)
            except Exception:  # noqa: BLE001
                pass
        return payload  # source originale prioritaire

    proxy = compute_aggressor_imbalance_proxy(
        buy_vol=payload.get("buy_vol"),
        sell_vol=payload.get("sell_vol"),
        avg_ask_size=payload.get("avg_ask_size"),
        avg_bid_size=payload.get("avg_bid_size"),
    )

    if proxy is not None:
        payload["aggressor_imbalance"] = proxy
        payload["_aggressor_source"] = "sierra_proxy_count"  # tracabilite
        if log_fn is not None:
            try:
                log_fn("AGGRESSOR_PROXY_INJECTED", aggro=proxy, sym=sym)
            except Exception:  # noqa: BLE001
                pass
    else:
        if log_fn is not None:
            try:
                log_fn("AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS", sym=sym)
            except Exception:  # noqa: BLE001
                pass

    return payload
