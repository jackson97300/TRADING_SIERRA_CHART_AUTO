"""Sierra enriched compat layer pour Order Flow Avance (dashboard).

Mission : migration des 9 features OFA depuis le parquet V4 Databento
(stale depuis 16/06 - NQ 22h, MGC 5j) vers le JSONL sierra_enriched (source
canonique unique). Calque sur CORE/bot_bn_v4/sierra_compat.py.

Features migrees (9) :
  1. near_resistance_level  - proximity niveau cle resistance (symbol-aware)
  2. near_support_level     - idem support
  3. n_cluster_groups       - alias n_clusters_20t (presents en sierra)
  4. dist_big_ask_nearest_pct - convert ticks -> %
  5. dist_big_bid_nearest_pct - idem
  6. big_buy_dominance      - reuse CORE/bot_bn_v4/sierra_compat (source unique)
  7. big_sell_dominance     - reuse
  8. bn_trapped_buyers_at_resistance - heuristique footprint proxy
  9. bn_trapped_sellers_at_support   - idem

Reserves agent Plan 16/06 :
  - R1 CRITIQUE : near_* utilise proximity symbol-aware (pas 0.05% constant)
    Formule : proximity_ticks * tick / close * 100
    ES=5t, NQ=10t, MGC=10t (defaut sym inconnu)
  - R2 : reuse enrich_big_dominance de bot_bn_v4 (anti-duplication)
  - R3 : tick depuis get_tick_size(symbol) (pas hardcode 0.25)
  - R4 : trap proxy heuristique = finish_pct + delta + close vs open + big orders

Non-migre (Phase 5) :
  - naked_poc_* (widget K) : tracking historique POCs >5j, complexe.
    Renvoie npoc_unavailable=True (frontend affiche "--").
"""
from __future__ import annotations

from typing import Optional


# Constantes portees depuis CORE/phase_b_plus_plus_engine.py:209
# (source : ABSORPTION_PROXIMITY_TICKS, validee par agent Plan R1)
PROXIMITY_TICKS_BY_SYM = {"ES": 5, "NQ": 10, "MGC": 10}
PROXIMITY_TICKS_DEFAULT = 10

# Constantes heuristique trap (port phase_b_plus_plus_engine.py:625-626)
TRAPPED_FINISH_PCT_BUYERS = 30  # close dans le bottom 30% du range bar
TRAPPED_FINISH_PCT_SELLERS = 70  # close dans le top 70% du range bar


def _f(v) -> Optional[float]:
    """Cast safe float (None/NaN/non-castable -> None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check
        return None
    return f


def _tick_for(symbol: str) -> float:
    """Tick size symbol-aware (source unique CORE.constants.get_tick_size).

    Fallback 0.25 si import echoue (defense en profondeur). ES/NQ=0.25, MGC=0.10.
    """
    try:
        from CORE.constants import get_tick_size
        return float(get_tick_size(symbol))
    except Exception:  # noqa: BLE001
        # Fallback hardcode minimal
        return 0.10 if symbol.upper().startswith("MGC") else 0.25


def _proximity_pct(symbol: str, close: float) -> float:
    """Proximity en % du prix pour near_* (symbol-aware).

    Formule (port phase_b_plus_plus_engine.py:912-913) :
      proximity_pct = proximity_ticks * tick / close * 100

    Exemples :
      ES @ 6000  : 5t * 0.25 / 6000 * 100 = 0.0208%
      NQ @ 21000 : 10t * 0.25 / 21000 * 100 = 0.0119%
      MGC @ 3500 : 10t * 0.10 / 3500 * 100 = 0.0286%
    """
    if close <= 0:
        return 0.05  # fallback raisonnable
    sym = symbol.upper().split(".")[0]
    proximity_ticks = PROXIMITY_TICKS_BY_SYM.get(sym, PROXIMITY_TICKS_DEFAULT)
    tick = _tick_for(symbol)
    return proximity_ticks * tick / close * 100.0


def _compute_near_levels(row: dict, symbol: str) -> tuple[int, int]:
    """Calcule near_resistance_level + near_support_level (port phase_b_plus_plus).

    Verifie dist_*_pct des niveaux cles : si |dist| <= proximity_pct, near=1.

    Niveaux RESISTANCE consultes (sierra_enriched) :
      - dist_mq_call_pct, dist_mq_call_0dte_pct (MenthorQ call wall)
      - dist_prev_vah_pct (Value Area High J-1)
      - dist_pdh_pct (Previous Day High)
      - dist_vwap_d_sd2u_pct (VWAP +2SD upper, calcule par enrich_bn_v4)

    Niveaux SUPPORT consultes :
      - dist_mq_put_pct, dist_mq_put_0dte_pct
      - dist_prev_val_pct, dist_pdl_pct
      - dist_vwap_d_sd2d_pct

    Niveaux NEUTRES (ambivalents, ajoutes aux 2) :
      - dist_mq_hvl_pct (High Volume Level)
    """
    close = _f(row.get("close"))
    if close is None or close <= 0:
        return 0, 0

    prox_pct = _proximity_pct(symbol, close)

    res_cols = [
        "dist_mq_call_pct", "dist_mq_call_0dte_pct",
        "dist_prev_vah_pct", "dist_pdh_pct",
        "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd1u_pct",
    ]
    sup_cols = [
        "dist_mq_put_pct", "dist_mq_put_0dte_pct",
        "dist_prev_val_pct", "dist_pdl_pct",
        "dist_vwap_d_sd2d_pct", "dist_vwap_d_sd1d_pct",
    ]
    neutral_cols = ["dist_mq_hvl_pct"]  # ambivalent : check des 2 cotes

    near_res = 0
    for col in res_cols + neutral_cols:
        d = _f(row.get(col))
        if d is not None and abs(d) <= prox_pct:
            near_res = 1
            break

    near_sup = 0
    for col in sup_cols + neutral_cols:
        d = _f(row.get(col))
        if d is not None and abs(d) <= prox_pct:
            near_sup = 1
            break

    return near_res, near_sup


def _compute_dist_big_nearest_pct(row: dict, symbol: str) -> tuple[float, float]:
    """Convertit dist_big_*_nearest_up/dn (en ticks) -> dist_big_*_nearest_pct (en %).

    Source sierra_enriched : dist_big_ask_nearest_up/dn et dist_big_bid_nearest_up/dn
    sont en TICKS (signed : up > 0 = niveau au-dessus, dn < 0 = niveau en-dessous).

    Formule :
      min_dist_ticks = min(abs(up), abs(dn)) parmi les valeurs > 0
      pct = min_dist_ticks * tick / close * 100

    Retour : (dist_ask_pct, dist_bid_pct). 0.0 si pas de big order detecte.
    """
    close = _f(row.get("close"))
    if close is None or close <= 0:
        return 0.0, 0.0

    tick = _tick_for(symbol)

    def _min_dist_ticks(up_key: str, dn_key: str) -> float:
        up = _f(row.get(up_key))
        dn = _f(row.get(dn_key))
        candidates = []
        if up is not None and up > 0:
            candidates.append(abs(up))
        if dn is not None and dn < 0:
            candidates.append(abs(dn))
        return min(candidates) if candidates else 0.0

    ask_ticks = _min_dist_ticks("dist_big_ask_nearest_up", "dist_big_ask_nearest_dn")
    bid_ticks = _min_dist_ticks("dist_big_bid_nearest_up", "dist_big_bid_nearest_dn")

    ask_pct = (ask_ticks * tick / close * 100.0) if ask_ticks > 0 else 0.0
    bid_pct = (bid_ticks * tick / close * 100.0) if bid_ticks > 0 else 0.0

    return ask_pct, bid_pct


def _compute_trap_proxies(row: dict, near_res: int, near_sup: int) -> tuple[int, int]:
    """Heuristique footprint proxy pour bn_trapped_*_at_* (validation agent Plan R4).

    L'original phase_b_plus_plus_engine.py:712-740 utilise trap_buy_raw qui
    necessite le footprint complet (cellules VAP). Sierra_enriched n'expose
    PAS trap_buy_raw / trap_sell_raw.

    Approximation footprint sans cellules (R4) :
      trap_buy_proxy = (delta_bar > 0) AND (close < open)
                       AND (n_big_ask_v2_t1 >= 1)
                       AND (finish_pct <= TRAPPED_FINISH_PCT_BUYERS)

      finish_pct = (close - low) / (high - low) * 100

    Semantique : marche affiche un delta positif (acheteurs lifts) MAIS la barre
    cloture rouge dans le bottom 30% du range + presence d'1 gros ordre ASK
    -> acheteurs PIEGES, supply pressante.

    Retour : (bn_trapped_buyers_at_resistance, bn_trapped_sellers_at_support).
    """
    high = _f(row.get("high")) or _f(row.get("bar_high"))
    low = _f(row.get("low")) or _f(row.get("bar_low"))
    open_v = _f(row.get("open"))
    close = _f(row.get("close"))
    delta = _f(row.get("delta_bar"))
    n_big_ask = _f(row.get("n_big_ask_v2_t1")) or _f(row.get("n_big_ask_t1")) or 0.0
    n_big_bid = _f(row.get("n_big_bid_v2_t1")) or _f(row.get("n_big_bid_t1")) or 0.0

    if None in (high, low, open_v, close, delta):
        return 0, 0

    bar_range = high - low
    if bar_range <= 0:
        return 0, 0  # bar doji, pas de signal

    finish_pct = (close - low) / bar_range * 100.0

    trap_buy_proxy = int(
        delta > 0
        and close < open_v
        and n_big_ask >= 1
        and finish_pct <= TRAPPED_FINISH_PCT_BUYERS
    )

    trap_sell_proxy = int(
        delta < 0
        and close > open_v
        and n_big_bid >= 1
        and finish_pct >= TRAPPED_FINISH_PCT_SELLERS
    )

    # Combine avec near_levels (semantique V4 : trap raw AND near level)
    return (
        int(trap_buy_proxy and near_res),
        int(trap_sell_proxy and near_sup),
    )


def enrich_sierra_for_ofa(bar: dict, symbol: str) -> dict:
    """Reconstruit les 9 features Order Flow Avance manquantes en sierra_enriched.

    Mute le dict in-place ET le retourne (chainable, idempotent via setdefault).

    Args:
        bar    : barre dict depuis JSONL sierra_enriched
        symbol : "ES" / "NQ" / "MGC" pour proximity + tick size symbol-aware

    Returns:
        bar enrichi avec 9 features OFA (+ flag npoc_unavailable=True).

    Idempotence : si une feature existe deja dans bar, elle n'est PAS overwrite
    (utilise setdefault). Permet d'appeler safe meme si parquet V4 partiellement
    present (transition deploy).
    """
    if not bar:
        return bar

    # 1. big_buy/sell_dominance : delegate a la source unique partagee
    try:
        from CORE.bot_bn_v4.sierra_compat import enrich_big_dominance
        enrich_big_dominance(bar)
    except ImportError:
        # Defense : fallback minimal si import casse
        pass

    # 2. near_resistance_level + near_support_level (symbol-aware, R1)
    if "near_resistance_level" not in bar or "near_support_level" not in bar:
        near_res, near_sup = _compute_near_levels(bar, symbol)
        bar.setdefault("near_resistance_level", near_res)
        bar.setdefault("near_support_level", near_sup)
    else:
        near_res = int(bar.get("near_resistance_level") or 0)
        near_sup = int(bar.get("near_support_level") or 0)

    # 3. n_cluster_groups : alias n_clusters_20t (preferred precision 0.2%)
    if "n_cluster_groups" not in bar:
        n_clusters = _f(bar.get("n_clusters_20t")) or _f(bar.get("n_clusters_50t")) or 0.0
        bar.setdefault("n_cluster_groups", int(n_clusters))

    # 4 + 5. dist_big_ask/bid_nearest_pct : convert ticks -> %
    if "dist_big_ask_nearest_pct" not in bar or "dist_big_bid_nearest_pct" not in bar:
        ask_pct, bid_pct = _compute_dist_big_nearest_pct(bar, symbol)
        bar.setdefault("dist_big_ask_nearest_pct", ask_pct)
        bar.setdefault("dist_big_bid_nearest_pct", bid_pct)

    # 8 + 9. bn_trapped_*_at_* : heuristique footprint proxy (R4)
    if ("bn_trapped_buyers_at_resistance" not in bar
            or "bn_trapped_sellers_at_support" not in bar):
        trap_buy, trap_sell = _compute_trap_proxies(bar, near_res, near_sup)
        bar.setdefault("bn_trapped_buyers_at_resistance", trap_buy)
        bar.setdefault("bn_trapped_sellers_at_support", trap_sell)

    # Phase 5 : naked_poc widget K - non migre (tracking historique 5j complexe).
    # Frontend lira ce flag pour afficher "--" + tooltip.
    bar.setdefault("npoc_unavailable", True)

    return bar


def list_required_inputs() -> dict[str, list[str]]:
    """Liste les inputs sierra_enriched necessaires par feature OFA.

    Utile pour audit cross-data (verifier qu'un fichier sierra a tous les inputs
    avant de tenter l'enrichment).
    """
    return {
        "near_resistance_level": [
            "close", "dist_mq_call_pct", "dist_mq_call_0dte_pct",
            "dist_prev_vah_pct", "dist_pdh_pct", "dist_mq_hvl_pct",
        ],
        "near_support_level": [
            "close", "dist_mq_put_pct", "dist_mq_put_0dte_pct",
            "dist_prev_val_pct", "dist_pdl_pct", "dist_mq_hvl_pct",
        ],
        "n_cluster_groups": ["n_clusters_20t"],
        "dist_big_ask_nearest_pct": [
            "close", "dist_big_ask_nearest_up", "dist_big_ask_nearest_dn",
        ],
        "dist_big_bid_nearest_pct": [
            "close", "dist_big_bid_nearest_up", "dist_big_bid_nearest_dn",
        ],
        "big_buy_dominance": ["n_big_ask_v2_t1", "n_big_ask_t1"],
        "big_sell_dominance": ["n_big_bid_v2_t1", "n_big_bid_t1"],
        "bn_trapped_buyers_at_resistance": [
            "high", "low", "open", "close", "delta_bar", "n_big_ask_v2_t1",
            "near_resistance_level",  # calcule en amont
        ],
        "bn_trapped_sellers_at_support": [
            "high", "low", "open", "close", "delta_bar", "n_big_bid_v2_t1",
            "near_support_level",
        ],
    }
