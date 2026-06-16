"""Sierra enriched compat layer pour Bot BN V4.

Le moteur CORE.bn_v4_engine exige certaines features qui ne sont PAS encore
emises par le pipeline sierra_enriched (verification empirique 16/06/2026 sur
DATA/live_enriched/sierra/NQ/20260615_NQ_sierra_enriched.jsonl). Plutot que
casser le pipeline enrichment, on les RECONSTRUIT a la volee dans le bot.

Features manquantes confirmees (6) :
  - dist_pvwap_pct, dist_pvwap_sd1u_pct, dist_pvwap_sd1d_pct
  - dist_vwap_w_sd2u_pct, dist_vwap_w_sd2d_pct
  - big_buy_dominance / big_sell_dominance

Convention dist_*_pct (alignee bn_v4_engine.INSTITUTIONAL_LEVELS_LONG) :
  positif = niveau AU-DESSUS du prix
  negatif = niveau EN-DESSOUS du prix
  formule = (level - close) / close * 100
"""
from __future__ import annotations

from typing import Optional


def _f(v) -> Optional[float]:
    """Cast safe float (None/NaN/non-castable -> None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check (NaN != NaN)
        return None
    return f


def enrich_big_dominance(row: dict) -> dict:
    """Calcule big_buy_dominance / big_sell_dominance dans row (in-place).

    SOURCE UNIQUE 16/06 (Plan agent review R2) : factorisee depuis
    enrich_sierra_bar_for_bn_v4 pour mutualisation avec DASHBOARD/api/sierra_ofa_compat.py
    (widget Order Flow Avance). Anti-pattern : duplication formule entre bot et dashboard
    -> divergence garantie. Source unique = ici.

    Convention semantique (confirmee par Lopez de Prado / Kyle 1985) :
      n_big_ask_* = ordres ASK liftes = market BUY agressif -> ask_buyer_dominance
      n_big_bid_* = ordres BID hits = market SELL agressif -> bid_seller_dominance

    Sources possibles (fallback en cascade) :
      - n_big_ask_v2_t1 + n_big_bid_v2_t1 (v2 enriched, prioritaire)
      - n_big_ask_t1 + n_big_bid_t1 (legacy fallback)

    Si total_big = 0 (pas de big orders dans la barre) : valeur neutre 0.5
    (PAS de signal, evite division par zero + faux signal directionnel).

    Idempotent : skip si les 2 cles existent deja (setdefault).
    """
    if "big_buy_dominance" not in row or "big_sell_dominance" not in row:
        n_ask = _f(row.get("n_big_ask_v2_t1")) or _f(row.get("n_big_ask_t1")) or 0.0
        n_bid = _f(row.get("n_big_bid_v2_t1")) or _f(row.get("n_big_bid_t1")) or 0.0
        total_big = n_ask + n_bid
        if total_big > 0:
            row.setdefault("big_buy_dominance", n_ask / total_big)
            row.setdefault("big_sell_dominance", n_bid / total_big)
        else:
            row.setdefault("big_buy_dominance", 0.5)
            row.setdefault("big_sell_dominance", 0.5)
    return row


def enrich_sierra_bar_for_bn_v4(row: dict) -> dict:
    """Reconstruit les 5 dist_*_pct manquants + big_buy/sell_dominance.

    Mute le dict in-place ET le retourne (chainable).

    Args:
        row : bar dict depuis JSONL sierra_enriched

    Returns:
        row enrichi (in-place mute).
    """
    close = _f(row.get("close"))
    if close is None or close <= 0:
        close = _f(row.get("price"))

    # 1. dist_pvwap_pct + SD1 (convention level - close > 0 si niveau au-dessus)
    if close and close > 0:
        pvwap = _f(row.get("pvwap"))
        if pvwap is not None and "dist_pvwap_pct" not in row:
            row["dist_pvwap_pct"] = (pvwap - close) / close * 100.0

        pvwap_sd1u = _f(row.get("pvwap_sd1u"))
        if pvwap_sd1u is not None and "dist_pvwap_sd1u_pct" not in row:
            row["dist_pvwap_sd1u_pct"] = (pvwap_sd1u - close) / close * 100.0

        pvwap_sd1d = _f(row.get("pvwap_sd1d"))
        if pvwap_sd1d is not None and "dist_pvwap_sd1d_pct" not in row:
            row["dist_pvwap_sd1d_pct"] = (pvwap_sd1d - close) / close * 100.0

        # 2. dist_vwap_w_sd2u/d_pct
        vwap_w_sd2u = _f(row.get("vwap_w_sd2u"))
        if vwap_w_sd2u is not None and "dist_vwap_w_sd2u_pct" not in row:
            row["dist_vwap_w_sd2u_pct"] = (vwap_w_sd2u - close) / close * 100.0

        vwap_w_sd2d = _f(row.get("vwap_w_sd2d"))
        if vwap_w_sd2d is not None and "dist_vwap_w_sd2d_pct" not in row:
            row["dist_vwap_w_sd2d_pct"] = (vwap_w_sd2d - close) / close * 100.0

    # 3. big_buy/sell_dominance : delegate a la fonction partagee
    enrich_big_dominance(row)

    return row


def list_required_features() -> list[str]:
    """Liste des features que bn_v4_engine consomme (pour audit degraded)."""
    return [
        "close", "high", "low", "open",
        "vwap_slope_10",
        "n_color_up_cluster_within_0_2pct", "n_long_up_cluster_within_0_2pct",
        "n_color_dn_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
        "n_edge_buy_active", "n_edge_sell_active",
        "long_up_bar", "long_dn_bar",
        "long_dn_up_pattern", "long_up_dn_pattern",
        "aggressor_imbalance", "delta_bar",
        "big_buy_dominance", "big_sell_dominance",
        "total_vol",
        "dist_pdh_pct", "dist_pdl_pct",
        "dist_prev_vah_pct", "dist_prev_val_pct",
        "dist_pvwap_pct",
        "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
        "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct",
        "dist_vwap_w_pct",
        "dist_cur_vpoc_pct",
        "dist_mq_hvl_pct", "dist_mq_call_pct", "dist_mq_put_pct",
        "ts_event", "ts_event_ns",
    ]


def detect_missing_features(row: dict) -> list[str]:
    """Liste les features critiques absentes du row (pour BOTBN_FEATURE_DEGRADED).

    OHLC est BLOQUANT (returne par fail-loud en aval). Le reste est informatif.
    """
    critical = ["close", "high", "low", "vwap_slope_10", "ts_event_ns"]
    return [f for f in critical if row.get(f) is None]
