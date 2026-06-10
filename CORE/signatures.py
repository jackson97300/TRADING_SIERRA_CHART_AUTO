"""signatures.py — 12 game changers pro pre-entry filter Bot 2 (v2 reformule).

REFORMULATION 30/04 nuit apres 1er backtest : 8/12 signatures avaient
0% presence car features formelles inventees. v2 utilise les VRAIES
features de Bot 2 features_at_entry (398 features dispo).

Features cles utilisees (verifiees presentes dans trades.jsonl Bot 2) :
  - bn_absorb_bid_raw / bn_absorb_ask_raw       (absorb signal)
  - bn_color_up_2_fwd1 / bn_color_dn_fwd1       (color confirmed)
  - bn_trapped_buyers_raw / bn_trapped_sellers_raw (trapped)
  - long_up_bar / long_dn_bar                    (long directional bars)
  - delta_div_buy / delta_div_sell               (divergence)
  - rvol_absorb_buy / rvol_absorb_sell           (absorb rvol)
  - n_big_buy_t1-t4 / n_big_sell_t1-t4           (big orders by tier)
  - dist_color_up/dn_nearest_pct                 (color zone distance)
  - dist_trapped_*                               (trapped zone distance)
  - vwap_slope_10 / dist_vwap_d_pct              (VWAP slope/dist)
  - cvd_5d_rolling_ffd / delta_pct               (delta/CVD)
  - aggressor_imbalance                          (aggressor flip)
  - n_color_up/dn_zones_active                   (active zones)
  - dist_mq_call/put/hvl_pct                     (MQ levels)

USAGE :
  from CORE import signatures
  signals = signatures.compute_all(features, direction="LONG")
"""
from __future__ import annotations
from typing import Optional


def _f(features: dict, key: str, default=0):
    """Safe float extract."""
    v = features.get(key, default)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(features: dict, key: str) -> bool:
    """Safe bool extract."""
    v = features.get(key, 0)
    if v is None:
        return False
    try:
        return bool(int(v)) if isinstance(v, (int, float)) else bool(v)
    except (TypeError, ValueError):
        return False


# ==========================================================================
# TIER 1 — Pression directionnelle pure
# ==========================================================================

def absorb_bid(features: dict, direction: str = "LONG") -> bool:
    """Absorb : gros buyers/sellers absorbent sans bouger le prix."""
    if direction == "LONG":
        return (_b(features, "bn_absorb_bid_raw") or _b(features, "rvol_absorb_buy")) \
               and _f(features, "delta_bar") > 0
    else:
        return (_b(features, "bn_absorb_ask_raw") or _b(features, "rvol_absorb_sell")) \
               and _f(features, "delta_bar") < 0


def trapped_traders(features: dict, direction: str = "LONG") -> bool:
    """Trapped : vendeurs (LONG) ou acheteurs (SHORT) forces de couvrir."""
    if direction == "LONG":
        return _b(features, "bn_trapped_sellers_raw") or \
               _f(features, "n_trapped_sellers_zones_active") > 0
    else:
        return _b(features, "bn_trapped_buyers_raw") or \
               _f(features, "n_trapped_buyers_zones_active") > 0


def long_directional_bar(features: dict, direction: str = "LONG") -> bool:
    """Long up bar (LONG) ou Long dn bar (SHORT)."""
    if direction == "LONG":
        return _b(features, "long_up_bar")
    else:
        return _b(features, "long_dn_bar")


def aggressor_flip(features: dict, direction: str = "LONG") -> bool:
    """Aggressor flip : prise du flux par les market-takers."""
    aggr = _f(features, "aggressor_imbalance", 0)
    if direction == "LONG":
        return aggr > 0.30
    else:
        return aggr < -0.30


# ==========================================================================
# TIER 2 — Confirmation environnementale
# ==========================================================================

def color_zone_proximity(features: dict, direction: str = "LONG") -> bool:
    """Color UP/DN zone active proche."""
    if direction == "LONG":
        return _f(features, "n_color_up_zones_active") > 0 and \
               abs(_f(features, "dist_color_up_nearest_pct", 99)) < 0.1
    else:
        return _f(features, "n_color_dn_zones_active") > 0 and \
               abs(_f(features, "dist_color_dn_nearest_pct", 99)) < 0.1


def vwap_aligned(features: dict, direction: str = "LONG") -> bool:
    """VWAP slope dans le sens + prix au-dessus/dessous VWAP daily."""
    slope = _f(features, "vwap_slope_10", 0)
    dist = _f(features, "dist_vwap_d_pct", 0)
    if direction == "LONG":
        return slope > 0 and dist > 0
    else:
        return slope < 0 and dist < 0


def cvd_divergence(features: dict, direction: str = "LONG") -> bool:
    """CVD divergence : cvd haussier malgre prix bas (LONG).

    FIX code-reviewer 30/04 nuit (B2) : seuil absolu 200 violait `data-quality.md`
    rechute #3 (valeurs absolues ES vs NQ asymetriques NQ ~3-5x ES). Migration
    vers `cvd_5d_rolling_ffd_norm` si disponible (z-score), sinon ratio sur ATR
    pour auto-normalisation cross-instrument. Fallback seuil generique 0.5
    (z-score >= 0.5 std).
    """
    # Preferer la version normalisee si disponible
    cvd_norm = _f(features, "cvd_5d_rolling_ffd_z", None) or \
               _f(features, "cvd_5d_rolling_ffd_norm", None)
    cvd_raw = _f(features, "cvd_5d_rolling_ffd", 0)
    atr_pct = _f(features, "atr_14m_pct", 0.005)  # default ~0.5% pour eviter div/0
    pos = _f(features, "position_in_range", 0.5)

    # Si la version normalisee n'existe pas, on calcule un proxy normalise
    if cvd_norm is None or cvd_norm == 0:
        # Proxy : cvd / (atr_pct * 100000) — normalise grossierement ES vs NQ
        cvd_norm = cvd_raw / (atr_pct * 100000) if atr_pct > 0 else 0

    if direction == "LONG":
        return cvd_norm > 0.5 and pos < 0.4
    else:
        return cvd_norm < -0.5 and pos > 0.6


def big_order_dominance(features: dict, direction: str = "LONG") -> bool:
    """Big buyers (LONG) ou big sellers (SHORT) Tier 3-4 dominants."""
    if direction == "LONG":
        return _f(features, "big_buy_dominance", 0) > 0.5 or \
               (_f(features, "n_big_buy_t3") + _f(features, "n_big_buy_t4")) > 1
    else:
        return _f(features, "big_sell_dominance", 0) > 0.5 or \
               (_f(features, "n_big_sell_t3") + _f(features, "n_big_sell_t4")) > 1


# ==========================================================================
# TIER 3 — Absence de l'inverse (filtres negatifs)
# ==========================================================================

def no_inverse_color(features: dict, direction: str = "LONG") -> bool:
    """Pas de color zone INVERSE proche."""
    if direction == "LONG":
        n_dn = _f(features, "n_color_dn_zones_active")
        dist_dn = abs(_f(features, "dist_color_dn_nearest_pct", 99))
        return n_dn == 0 or dist_dn > 0.2
    else:
        n_up = _f(features, "n_color_up_zones_active")
        dist_up = abs(_f(features, "dist_color_up_nearest_pct", 99))
        return n_up == 0 or dist_up > 0.2


def no_big_inverse(features: dict, direction: str = "LONG") -> bool:
    """Pas de gros vendeurs (LONG) ou acheteurs (SHORT) Tier 3-4 visibles."""
    if direction == "LONG":
        big_sell_t34 = _f(features, "n_big_sell_t3") + _f(features, "n_big_sell_t4")
        return big_sell_t34 < 1
    else:
        big_buy_t34 = _f(features, "n_big_buy_t3") + _f(features, "n_big_buy_t4")
        return big_buy_t34 < 1


def no_inverse_long_bar(features: dict, direction: str = "LONG") -> bool:
    """Pas de long bar INVERSE recent."""
    if direction == "LONG":
        return not _b(features, "long_dn_bar")
    else:
        return not _b(features, "long_up_bar")


def mq_no_inverse_resistance(features: dict, direction: str = "LONG") -> bool:
    """Pas de mq_call (LONG) ou mq_put (SHORT) tres proche."""
    if direction == "LONG":
        d = _f(features, "dist_mq_call_pct", 999)
        return not (0 < d < 0.05)
    else:
        d = _f(features, "dist_mq_put_pct", 999)
        return not (-0.05 < d < 0)


# ==========================================================================
# Compute all signatures
# ==========================================================================

ALL_SIGNATURES = {
    "absorb_bid": absorb_bid,
    "trapped_traders": trapped_traders,
    "long_directional_bar": long_directional_bar,
    "aggressor_flip": aggressor_flip,
    "color_zone_proximity": color_zone_proximity,
    "vwap_aligned": vwap_aligned,
    "cvd_divergence": cvd_divergence,
    "big_order_dominance": big_order_dominance,
    "no_inverse_color": no_inverse_color,
    "no_big_inverse": no_big_inverse,
    "no_inverse_long_bar": no_inverse_long_bar,
    "mq_no_inverse_resistance": mq_no_inverse_resistance,
}

TIER_1 = ["absorb_bid", "trapped_traders", "long_directional_bar", "aggressor_flip"]
TIER_2 = ["color_zone_proximity", "vwap_aligned", "cvd_divergence", "big_order_dominance"]
TIER_3 = ["no_inverse_color", "no_big_inverse", "no_inverse_long_bar", "mq_no_inverse_resistance"]


def compute_all(features: dict, direction: str = "LONG") -> dict:
    if not isinstance(features, dict):
        return {name: False for name in ALL_SIGNATURES}
    result = {}
    for name, fn in ALL_SIGNATURES.items():
        try:
            result[name] = bool(fn(features, direction=direction))
        except Exception:
            result[name] = False
    return result


def score_tier1(signals: dict) -> int:
    return sum(1 for s in TIER_1 if signals.get(s))


def score_tier2(signals: dict) -> int:
    return sum(1 for s in TIER_2 if signals.get(s))


def score_tier3(signals: dict) -> int:
    return sum(1 for s in TIER_3 if signals.get(s))


def overall_score(signals: dict) -> dict:
    t1 = score_tier1(signals)
    t2 = score_tier2(signals)
    t3 = score_tier3(signals)
    return {
        "tier1": t1, "tier1_max": len(TIER_1),
        "tier2": t2, "tier2_max": len(TIER_2),
        "tier3": t3, "tier3_max": len(TIER_3),
        "total": t1 + t2 + t3,
        "max": len(ALL_SIGNATURES),
    }


if __name__ == "__main__":
    fake = {
        "bn_absorb_bid_raw": 1, "delta_bar": 200,
        "long_up_bar": 1,
        "aggressor_imbalance": 0.4,
        "n_color_up_zones_active": 1, "dist_color_up_nearest_pct": 0.05,
        "vwap_slope_10": 0.001, "dist_vwap_d_pct": 0.1,
        "cvd_5d_rolling_ffd": 500, "position_in_range": 0.3,
        "big_buy_dominance": 0.7,
        "n_color_dn_zones_active": 0,
        "n_big_sell_t3": 0, "n_big_sell_t4": 0,
        "dist_mq_call_pct": 0.5,
    }
    signals = compute_all(fake, "LONG")
    print("Smoke test (fake LONG strong) :")
    for k, v in signals.items():
        print(f"  {k:30s} : {'+' if v else '-'}")
    score = overall_score(signals)
    print(f"\nScore : T1={score['tier1']}/{score['tier1_max']} "
          f"T2={score['tier2']}/{score['tier2_max']} "
          f"T3={score['tier3']}/{score['tier3_max']} "
          f"= {score['total']}/{score['max']}")
