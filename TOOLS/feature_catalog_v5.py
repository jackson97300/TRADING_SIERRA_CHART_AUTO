"""feature_catalog_v5.py - Phase 1 V5 : Catalog 491 features dans 12 familles.

Sortie audit cross-agents ULTRATHINK 12/06/2026 (validation Jackson).

Output :
  - DATA/_AUDIT/feature_catalog_v5.csv  : 491 rows x 10 metadata cols
  - DATA/_AUDIT/feature_catalog_v5.json : structure JSON pour navigation
  - Console : summary report par famille

12 familles validees (Claude grille + 3 agents review) :
  1.  MARKET STRUCTURE (1a TPO + 1b VP courant + 1c Swing/Liquidity)
  2.  NIVEAUX VEILLE (broadcast J-1)
  3.  INITIAL BALANCE & OVERNIGHT
  4.  VWAP & PRICE ANCHOR
  5.  ORDER FLOW & DELTA (5a Delta + 5b Imbalance + 5c Big Orders + 5d RVOL)
  6.  SIERRA CUSTOM SIGNALS (Bataille Navale)
  7.  REVERSAL / EXHAUSTION
  8.  OPTIONS / GAMMA (MenthorQ)
  9.  VOLATILITY / VIX
  10. SESSION & CALENDAR
  11. INTERMARKET / CROSS (ES vs NQ)
  12. CONTEXT ROLLING DERIVATIVES

Metadata par feature :
  - family (1-12 + META si meta-info, OTHER si pas matche)
  - subfamily (1a/1b/1c/5a/5b/5c/5d/etc.)
  - data_type (continuous / binary / categorical / event / meta)
  - dtype_observed (int / float / bool / str)
  - n_total : nombre bars analysees
  - n_null_pct : pourcentage NULL
  - top_value : valeur la plus frequente
  - top_freq_pct : frequence valeur top
  - n_unique : valeurs uniques observees
  - has_negative : True si valeurs negatives observees

Usage :
    python tools/feature_catalog_v5.py \\
        --input DATA/_sierra_20260611.jsonl \\
        --output-dir DATA/_AUDIT/ \\
        --max-bars 5000
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION RULES (ordre = priorite)
# ════════════════════════════════════════════════════════════════════════════
#
# Format : (regex_pattern, family, subfamily)
# Premier match gagne. Specifique avant generique.

CLASSIFICATION_RULES = [
    # ─── META (info bar, pas features ML) ──────────────────────────────────
    # FIX market-analyst review Q1 : atr / atr_14m migres vers 9_VOLATILITY_VIX
    (r"^(ts|sym|contract|price|open|high|low|close|volume)$",
     "META", "0a_bar_meta"),
    (r"^(session_id|session|session_date|session_date_trading|session_segment|date_et|ts_event|ts_event_ns)$",
     "META", "0a_bar_meta"),
    (r"^(bar_high|bar_low)$", "META", "0a_bar_meta"),
    (r"^(_phase3_enriched|_phase3_bars_processed|_mq_gamma_source|_aggressor_source|_dedup_completeness)$",
     "META", "0b_pipeline_meta"),
    (r"^(schema_version|boot_id|bars_since_boot|data_quality_flag)$",
     "META", "0c_observability"),
    (r"^(is_bar_closed|ts_event_minute)$", "META", "0a_bar_meta"),

    # ─── 8. OPTIONS / GAMMA (MenthorQ) ────────────────────────────────────
    (r"^mq_", "8_OPTIONS_GAMMA", "8_mq"),
    (r"^dist_mq_", "8_OPTIONS_GAMMA", "8_mq_dist"),
    (r"^(bool_above_mq_|bool_gex_flip_zone)", "8_OPTIONS_GAMMA", "8_mq_bool"),
    (r"^next_wall_", "8_OPTIONS_GAMMA", "8_mq_walls"),
    (r"^(dist_gex_|gex_cluster_)", "8_OPTIONS_GAMMA", "8_mq_gex"),
    (r"^ctx_mq_", "8_OPTIONS_GAMMA", "8_mq_ctx"),

    # ─── 9. VOLATILITY / VIX ──────────────────────────────────────────────
    # FIX market-analyst review Q1 : atr/atr_14m migres ici (etaient META)
    (r"^vix_", "9_VOLATILITY_VIX", "9_vix_core"),
    (r"^dist_vix_", "9_VOLATILITY_VIX", "9_vix_dist"),
    (r"^(atr|atr_14m|atr_14m_pct)$", "9_VOLATILITY_VIX", "9_atr"),

    # ─── 4. VWAP & PRICE ANCHOR ───────────────────────────────────────────
    (r"^vwap_(d|w|m)(_sd[123][ud])?$", "4_VWAP_ANCHOR", "4_vwap_abs"),
    (r"^pvwap", "4_VWAP_ANCHOR", "4_pvwap_abs"),
    (r"^dist_vwap_", "4_VWAP_ANCHOR", "4_vwap_dist"),
    (r"^dist_cur_vwap_vp", "4_VWAP_ANCHOR", "4_vwap_dist"),
    (r"^dist_prev_vwap", "4_VWAP_ANCHOR", "4_pvwap_dist"),
    (r"^vwap_(slope|ma_align|triple_align)", "4_VWAP_ANCHOR", "4_vwap_dynamics"),
    (r"^vwap_(d|w|m)_side$", "4_VWAP_ANCHOR", "4_vwap_side"),
    (r"^bool_above_vwap_", "4_VWAP_ANCHOR", "4_vwap_bool"),

    # ─── 2. NIVEAUX VEILLE (broadcast J-1) ────────────────────────────────
    (r"^(pdh|pdl|prev_vah|prev_val|prev_vpoc|prev_vah_lvl|prev_val_lvl|prev_vpoc_lvl)$",
     "2_NIVEAUX_VEILLE", "2_prev_levels_abs"),
    (r"^prev_vwap(_sd[123][ud])?$", "2_NIVEAUX_VEILLE", "2_prev_vwap_abs"),
    (r"^dist_(pdh|pdl|prev_vah|prev_val|prev_vpoc)", "2_NIVEAUX_VEILLE", "2_prev_levels_dist"),
    (r"^(open_in_prev_va|inside_prev_va|bool_above_prev_vpoc)$",
     "2_NIVEAUX_VEILLE", "2_prev_bool"),
    (r"^(cash_high|cash_low|open_cash|open_830|open_830_lvl|open_cash_lvl)$",
     "2_NIVEAUX_VEILLE", "2_cash_levels_abs"),
    (r"^dist_(open_830|open_cash|cash_high|cash_low)", "2_NIVEAUX_VEILLE", "2_cash_dist"),

    # ─── 3. INITIAL BALANCE & OVERNIGHT ───────────────────────────────────
    (r"^ib_", "3_IB_OVERNIGHT", "3_ib"),
    (r"^dist_ib_", "3_IB_OVERNIGHT", "3_ib_dist"),
    (r"^ovn_", "3_IB_OVERNIGHT", "3_ovn"),
    (r"^dist_ovn_", "3_IB_OVERNIGHT", "3_ovn_dist"),
    (r"^(asia_|london_|us_high|us_low|after_high|after_low|after_open)",
     "3_IB_OVERNIGHT", "3_sessions_levels"),
    (r"^dist_(asia_|london_|us_high|us_low|after_high|after_low|after_open|ny_open|london_open|asia_open)",
     "3_IB_OVERNIGHT", "3_sessions_dist"),
    (r"^(ny_open|london_open|asia_open|after_open)$", "3_IB_OVERNIGHT", "3_open_abs"),
    (r"^(above_open_cash|above_open_830|bool_ib_inside)$", "3_IB_OVERNIGHT", "3_bool"),
    (r"^price_1030$", "3_IB_OVERNIGHT", "3_intraday_anchor"),
    (r"^open_830_et$", "3_IB_OVERNIGHT", "3_open_abs"),

    # ─── 1a. TPO Concepts (Market Profile Steidlmayer/Dalton) ─────────────
    (r"^(day_type|open_type|open_zone|open_bias_conf|open_direction|rule_80pct)$",
     "1_MARKET_STRUCTURE", "1a_tpo_concepts"),
    # FIX market-analyst review Q1 : poc_position migre vers 5d_poc_dynamics
    # (= dynamique order-flow, pas concept TPO statique)
    (r"^(profile_shape|profile_skew|trend_day_probability)$",
     "1_MARKET_STRUCTURE", "1a_tpo_concepts"),
    (r"^(volume_imbalance|is_double_dist|poc_separation_ticks|profile_hvn_dominant)$",
     "1_MARKET_STRUCTURE", "1a_tpo_profile"),
    (r"^(single_print_mid|single_print_count)$", "1_MARKET_STRUCTURE", "1a_tpo_profile"),

    # ─── 1b. Volume Profile session courante ──────────────────────────────
    (r"^(cur_vah|cur_val|cur_vpoc|cur_vah_lvl|cur_val_lvl|cur_vpoc_lvl)$",
     "1_MARKET_STRUCTURE", "1b_vp_current"),
    (r"^dist_cur_(vah|val|vpoc)", "1_MARKET_STRUCTURE", "1b_vp_current_dist"),
    (r"^(range_pos_va|range_size_ticks|va_position_pct|inside_cur_va|bars_in_va)$",
     "1_MARKET_STRUCTURE", "1b_vp_current_range"),
    (r"^(vah_touches_20b|val_touches_20b)$", "1_MARKET_STRUCTURE", "1b_vp_current_touches"),
    (r"^(bool_above_cur_vpoc|bool_va_confluence)$", "1_MARKET_STRUCTURE", "1b_vp_current_bool"),
    (r"^(premium_zone|discount_zone|position_in_range|pct_in_range)$",
     "1_MARKET_STRUCTURE", "1b_vp_current_zones"),
    (r"^(session_hvn_count|session_lvn_count|dist_session_hvn|dist_session_lvn|lvn_confluence_count|lvn_between|hvn_between)",
     "1_MARKET_STRUCTURE", "1b_session_hvn_lvn"),

    # ─── 1c. Swing & Liquidity (ICT/Smith Money/Wyckoff) ──────────────────
    (r"^(dist_swing_high|dist_swing_low|swing_range_ticks|price_vs_swing_mid|new_swing_high|new_swing_low)$",
     "1_MARKET_STRUCTURE", "1c_swing"),
    (r"^bars_since_last_swing_", "1_MARKET_STRUCTURE", "1c_swing"),
    (r"^(equal_highs_detected|equal_lows_detected)$", "1_MARKET_STRUCTURE", "1c_liquidity"),
    (r"^liquidity_sweep_", "1_MARKET_STRUCTURE", "1c_liquidity"),
    (r"^(retest_high_count|retest_low_count|bars_since_retest_high|bars_since_retest_low)$",
     "1_MARKET_STRUCTURE", "1c_retest"),

    # ─── 7. REVERSAL / EXHAUSTION ─────────────────────────────────────────
    (r"^delta_div", "7_REVERSAL_EXHAUSTION", "7_delta_div"),
    (r"^(retest_high_delta_div|retest_low_delta_div)$", "7_REVERSAL_EXHAUSTION", "7_delta_div"),
    (r"^(n_delta_div_buy_zones_active|n_delta_div_sell_zones_active|dist_delta_div_buy_nearest_atr|dist_delta_div_sell_nearest_atr)$",
     "7_REVERSAL_EXHAUSTION", "7_delta_div_zones"),
    (r"^(delta_divergence|delta_divergence_any|delta_divergence_clean)$",
     "7_REVERSAL_EXHAUSTION", "7_delta_div"),
    (r"^ctx_(climax|failed_auction|delta_exhaustion|momentum_exhaustion|poor_high|poor_low|double_top_trap|excess_high_bars|excess_low_bars)",
     "7_REVERSAL_EXHAUSTION", "7_ctx_exhaustion"),
    (r"^(div_at_key_level_ticks|div_confluence_dmp|div_confluence_with_regime|div_regime_proxy_ok|div_forward_return_20b)",
     "7_REVERSAL_EXHAUSTION", "7_div_aggregates"),
    (r"^ctx_(div_density_20|bars_since_div|div_at_swing|price_delta_div_3)",
     "7_REVERSAL_EXHAUSTION", "7_ctx_div"),

    # ─── 6. SIERRA CUSTOM SIGNALS (Bataille Navale) ───────────────────────
    (r"^bn_color_", "6_SIERRA_BN", "6_bn_color"),
    (r"^bn_(absorb_ask|absorb_bid)$", "6_SIERRA_BN", "6_bn_absorb"),
    (r"^bn_(long_up|long_dn)$", "6_SIERRA_BN", "6_bn_long"),
    (r"^bn_pressure_", "6_SIERRA_BN", "6_bn_pressure"),
    (r"^bn_score_", "6_SIERRA_BN", "6_bn_score"),
    (r"^bn_volume_", "6_SIERRA_BN", "6_bn_volume"),
    (r"^bar_color_", "6_SIERRA_BN", "6_bar_color"),
    (r"^(bar_long_up_bar|bar_long_dn_bar|bar_long_dn_up|bar_long_up_dn|long_up_bar|long_dn_bar|long_up_dn_pattern|long_dn_up_pattern)$",
     "6_SIERRA_BN", "6_bar_long"),
    (r"^bar_(pressure_ask|pressure_bid)$", "6_SIERRA_BN", "6_bar_pressure"),
    (r"^(bar_edge_buy|bar_edge_sell|bar_edge_buy_fire|bar_edge_sell_fire|fp_edge_buy|fp_edge_sell)$",
     "6_SIERRA_BN", "6_edge"),
    (r"^(n_edge_buy_active|n_edge_sell_active|dist_ext_edge_)", "6_SIERRA_BN", "6_edge_zones"),
    (r"^dist_ext_(color|long)_", "6_SIERRA_BN", "6_extensions"),
    (r"^(n_long_(up|dn)_zones_active|n_color_(up|dn)_zones_active|n_long_(up|dn)_cluster|n_color_(up|dn)_cluster)",
     "6_SIERRA_BN", "6_extensions_zones"),
    # FIX market-analyst review Q1 : range_h_minus_* migres vers 1a_bar_microstructure
    # (= microstructure OHLC dependent barre precedente, pas signal BN)

    # ─── 5a. ORDER FLOW - Delta intraday ─────────────────────────────────
    (r"^delta_(bar|day|day_dir|pct|bar_vol_norm)$", "5_ORDER_FLOW", "5a_delta"),
    (r"^cvd_(bar_delta|day|day_dir|close|ohlc_range|ohlc_open|ohlc_high|ohlc_low|session)$",
     "5_ORDER_FLOW", "5a_cvd"),
    (r"^finish_(strength|delta_pct)$", "5_ORDER_FLOW", "5a_finish"),
    (r"^(high_pullback_delta|low_pullback_delta|diag_pos_delta|diag_neg_delta|diag_imbalance)$",
     "5_ORDER_FLOW", "5a_pullback"),
    (r"^(rotation_up|rotation_dn|rotation_zz_osc)$", "5_ORDER_FLOW", "5a_rotation"),
    (r"^momentum_[35]b$", "5_ORDER_FLOW", "5a_momentum"),

    # ─── 5b. ORDER FLOW - Bid/Ask Imbalance ──────────────────────────────
    (r"^(ask_pct|bid_pct|buy_sell_ratio|ask_bid_imbalance)$", "5_ORDER_FLOW", "5b_imbalance"),
    (r"^(buy_vol|sell_vol|total_vol|ticks_count|vol_per_sec|bar_duration_sec)$",
     "5_ORDER_FLOW", "5b_volume_abs"),
    (r"^(avg_trade_size|avg_bid_size|avg_ask_size|large_trader_ratio|large_trader_max_size)$",
     "5_ORDER_FLOW", "5b_trader"),
    (r"^(p99_trade_size_proxy|aggressor_imbalance)$", "5_ORDER_FLOW", "5b_microstructure"),
    (r"^(low_bid_vol_pct|high_ask_vol_pct|max_ask_vol_in_bar|max_bid_vol_in_bar)$",
     "5_ORDER_FLOW", "5b_extreme"),

    # ─── 5c. ORDER FLOW - Big Orders / Clusters ──────────────────────────
    (r"^n_big_(ask|bid)_(v2_)?t[1234]$", "5_ORDER_FLOW", "5c_big_orders"),
    (r"^big_(ask|bid)_cluster_", "5_ORDER_FLOW", "5c_big_clusters"),
    (r"^dist_big_(ask|bid)_nearest_", "5_ORDER_FLOW", "5c_big_nearest"),
    (r"^(dist_cluster_nearest_up|dist_cluster_nearest_dn|n_clusters_20t|n_clusters_50t)$",
     "5_ORDER_FLOW", "5c_clusters_agg"),
    (r"^max_big_(ask|bid)_vol_in_bar$", "5_ORDER_FLOW", "5c_big_volume"),

    # ─── 5d. ORDER FLOW - RVOL ───────────────────────────────────────────
    (r"^rvol", "5_ORDER_FLOW", "5d_rvol"),
    # FIX market-analyst review Q1 : poc_position ajoute (dynamique order-flow)
    (r"^(poc_bar_dist|poc_migration_dir|ctx_poc_migration_10|poc_position)$",
     "5_ORDER_FLOW", "5d_poc_dynamics"),

    # ─── 1a/12 BAR microstructure + open_position ─────────────────────────
    # FIX market-analyst review Q1 : range_h_minus_lprev_ticks + range_hprev_minus_l_ticks
    # ajoutes (etaient en 6_SIERRA_BN / 6_bar_range)
    (r"^(bar_body_pct|bar_body_ticks|bar_upper_wick_pct|bar_lower_wick_pct|bar_no_trade|range_size|range_h_minus_lprev_ticks|range_hprev_minus_l_ticks)$",
     "1_MARKET_STRUCTURE", "1a_bar_microstructure"),
    (r"^(open_position|open_gap_ticks)$", "1_MARKET_STRUCTURE", "1a_open_dynamics"),
    (r"^ma_trend$", "1_MARKET_STRUCTURE", "1a_trend"),

    # ─── 10. SESSION & CALENDAR ───────────────────────────────────────────
    (r"^is_in_(asia|london|us_cash|us_after|cash_session)$", "10_SESSION_CALENDAR", "10_session_flags"),
    (r"^is_(cash_session|ib_window|roll_day|session_blocked|eco_blocked|blocked_combined)$",
     "10_SESSION_CALENDAR", "10_session_flags"),
    (r"^is_news_", "10_SESSION_CALENDAR", "10_news_flags"),
    (r"^within_news_", "10_SESSION_CALENDAR", "10_news_proximity"),
    (r"^(mins_since_news|mins_to_next_news|news_seconds_until|news_minutes_until)$",
     "10_SESSION_CALENDAR", "10_news_countdown"),
    (r"^is_critical_news_60m$", "10_SESSION_CALENDAR", "10_news_flags"),
    # FIX market-analyst review Q1 : dist_sess_high_pct + dist_sess_low_pct
    # ajoutes (etaient orphelins en 1d_dist_pct via catch-all)
    (r"^(is_new_sess_high|is_new_sess_low|is_new_cash_high|is_new_cash_low|sess_range_ticks|sess_range_atr|dist_sess_high|dist_sess_low|sess_high|sess_low|dist_sess_high_pct|dist_sess_low_pct)$",
     "10_SESSION_CALENDAR", "10_session_range"),
    (r"^(roll_phase|days_since_roll)$", "10_SESSION_CALENDAR", "10_roll"),
    (r"^mins_et$", "10_SESSION_CALENDAR", "10_clock"),
    (r"^(tod_bucket_rth|week_of_month|is_opex_week|days_to_next_)", "10_SESSION_CALENDAR", "10_phase0_v5"),
    (r"^bool_session_early$", "10_SESSION_CALENDAR", "10_session_flags"),
    (r"^bool_near_level$", "10_SESSION_CALENDAR", "10_levels_bool"),

    # ─── 11. INTERMARKET / CROSS ES vs NQ ─────────────────────────────────
    (r"^im_", "11_INTERMARKET", "11_im"),

    # ─── 12. CONTEXT ROLLING DERIVATIVES (catch-all ctx_*) ────────────────
    (r"^ctx_", "12_CONTEXT_ROLLING", "12_ctx_rolling"),

    # ─── 9. ATR (general) ─────────────────────────────────────────────────
    (r"^atr(_\d+m_pct)?$", "9_VOLATILITY_VIX", "9_atr"),

    # ─── 1d. Distance percentages (catch-all dist_*_pct dans market struct) ─
    (r"^dist_.*_pct$", "1_MARKET_STRUCTURE", "1d_dist_pct"),
    (r"^dist_.*_atr$", "1_MARKET_STRUCTURE", "1d_dist_atr"),
    (r"^dist_(1d_max_ticks|1d_min_ticks)", "1_MARKET_STRUCTURE", "1d_1d_extremes"),
]


def classify_feature(name: str) -> tuple[str, str]:
    """Classifie feature name -> (family, subfamily). Returns OTHER si no match."""
    for pattern, family, subfamily in CLASSIFICATION_RULES:
        if re.match(pattern, name):
            return family, subfamily
    return "OTHER", "unclassified"


def infer_data_type(values: list[Any]) -> tuple[str, str]:
    """Infere data_type semantique + dtype Python observe.

    Returns (data_type, dtype_observed) :
      data_type   : continuous / binary / categorical / event / meta
      dtype       : float / int / bool / str / mixed
    """
    non_null = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not non_null:
        return ("event", "null_only")

    dtypes_seen = set(type(v).__name__ for v in non_null)
    if "str" in dtypes_seen:
        return ("categorical", "str")
    if "bool" in dtypes_seen and dtypes_seen == {"bool"}:
        return ("binary", "bool")

    unique_vals = set(non_null)
    n_unique = len(unique_vals)

    if n_unique == 2 and unique_vals.issubset({0, 1, 0.0, 1.0, True, False}):
        return ("binary", "bool" if "bool" in dtypes_seen else "int")
    if n_unique == 1:
        return ("event", "constant")
    if n_unique <= 10 and all(isinstance(v, (int, float)) and float(v).is_integer() for v in unique_vals):
        return ("categorical", "int")

    return ("continuous", "float")


def compute_stats(values: list[Any]) -> dict:
    """Compute statistics par feature."""
    n_total = len(values)
    n_null = sum(1 for v in values if v is None or (isinstance(v, float) and math.isnan(v)))
    n_null_pct = round(100.0 * n_null / n_total, 2) if n_total else 0.0

    non_null = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n_unique = len(set(non_null)) if non_null else 0

    if non_null:
        counter = Counter(non_null)
        top_value, top_count = counter.most_common(1)[0]
        top_freq_pct = round(100.0 * top_count / len(non_null), 2)
    else:
        top_value = None
        top_freq_pct = 0.0

    has_negative = any(isinstance(v, (int, float)) and v < 0 for v in non_null)

    data_type, dtype_observed = infer_data_type(values)

    return {
        "n_total": n_total,
        "n_null_pct": n_null_pct,
        "n_unique": n_unique,
        "top_value": repr(top_value)[:30],
        "top_freq_pct": top_freq_pct,
        "has_negative": has_negative,
        "data_type": data_type,
        "dtype_observed": dtype_observed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True,
                         help="JSONL live_enriched a auditer")
    parser.add_argument("--output-dir", type=Path, default=Path("DATA/_AUDIT"))
    parser.add_argument("--max-bars", type=int, default=3000)
    parser.add_argument("--symbol", type=str, default=None)
    args = parser.parse_args()

    # Load bars
    bars = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                bar = json.loads(line)
            except json.JSONDecodeError:
                continue
            if args.symbol and bar.get("sym") != args.symbol:
                continue
            bars.append(bar)
            if len(bars) >= args.max_bars:
                break

    print(f"=> Charge {len(bars)} bars")

    # Collect feature values
    feature_values: dict[str, list[Any]] = defaultdict(list)
    for bar in bars:
        for k, v in bar.items():
            feature_values[k].append(v)
    for k in feature_values:
        if len(feature_values[k]) < len(bars):
            feature_values[k].extend([None] * (len(bars) - len(feature_values[k])))

    # Build catalog
    catalog = []
    for name, values in sorted(feature_values.items()):
        family, subfamily = classify_feature(name)
        stats = compute_stats(values)
        catalog.append({
            "feature": name,
            "family": family,
            "subfamily": subfamily,
            **stats,
        })

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "feature_catalog_v5.csv"
    json_path = args.output_dir / "feature_catalog_v5.json"

    fieldnames = ["feature", "family", "subfamily", "data_type", "dtype_observed",
                   "n_total", "n_null_pct", "n_unique", "top_value", "top_freq_pct",
                   "has_negative"]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(catalog)

    # JSON groupe par famille
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in catalog:
        grouped[row["family"]][row["subfamily"]].append(row)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dict(grouped), f, indent=2, ensure_ascii=False)

    # Summary console
    family_counts = Counter(row["family"] for row in catalog)
    family_other = [r for r in catalog if r["family"] == "OTHER"]

    print(f"\n=== SUMMARY CATALOG ({len(catalog)} features) ===\n")
    family_order = [
        "META", "1_MARKET_STRUCTURE", "2_NIVEAUX_VEILLE", "3_IB_OVERNIGHT",
        "4_VWAP_ANCHOR", "5_ORDER_FLOW", "6_SIERRA_BN", "7_REVERSAL_EXHAUSTION",
        "8_OPTIONS_GAMMA", "9_VOLATILITY_VIX", "10_SESSION_CALENDAR",
        "11_INTERMARKET", "12_CONTEXT_ROLLING", "OTHER",
    ]
    for fam in family_order:
        count = family_counts.get(fam, 0)
        bar = "#" * min(50, count // 2)
        print(f"  {fam:30s} {count:4d}  {bar}")

    if family_other:
        print(f"\n=== ORPHELINES (OTHER, {len(family_other)} features) ===")
        for r in family_other[:30]:
            print(f"  {r['feature']:50s} type={r['data_type']:12s} null%={r['n_null_pct']:5.1f}")
        if len(family_other) > 30:
            print(f"  ... et {len(family_other)-30} autres (cf CSV)")

    print(f"\nCatalog CSV  : {csv_path}")
    print(f"Catalog JSON : {json_path}")


if __name__ == "__main__":
    main()
