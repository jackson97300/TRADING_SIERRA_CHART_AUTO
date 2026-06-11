"""Phase 4 LIGHT - Audit feature coverage Sierra enriched.

Objectif : decision GO/NO-GO sur qualite dataset Sierra prod.

Approche :
1. Lire 100 bars Sierra enriched live (NQ 11/06)
2. Identifier features actives (non-NaN > 90% bars)
3. Categoriser : Group A, B, C, D, D1, D2 + Sierra natif + Phase 3
4. Quantify coverage par categorie
5. Verdict : GO si >= 80% coverage, CONDITIONNEL si 60-80%, NOGO si < 60%
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


# Features attendues post-Phase 1 + D1 + D2
FEATURE_GROUPS = {
    # Group A (Phase 1 commit e43ab8e)
    "Group A - bn composites": [
        "bn_score_raw", "bn_score_bull", "bn_score_bear",
    ],
    "Group A - long bar": [
        "long_up_bar", "long_dn_bar", "bar_body_ticks",
        "range_h_minus_lprev_ticks", "n_long_up_zones_active",
        "n_long_dn_zones_active", "dist_long_up_nearest_pct",
        "n_long_up_cluster_within_0_2pct", "long_dn_up_pattern",
    ],
    "Group A - color bar": [
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    ],
    "Group A - cvd_session": ["cvd_session"],
    # Group B (Phase 1 commit a4be3d7)
    "Group B - rolling_features ctx_*": [
        "ctx_poc_migration_10", "ctx_va_developing_10",
        "ctx_rotation_factor_20", "ctx_ib_extension_ratio",
        "ctx_rvol_session", "ctx_cvd_recovery_rate",
        "ctx_trend_day_score", "ctx_session_phase",
        "ctx_double_top_trap", "ctx_momentum_exhaustion",
        "ctx_excess_high_bars", "ctx_excess_low_bars",
        "ctx_delta_sum_10", "ctx_vol_z_5",
    ],
    "Group B - edge_zones": [
        "bar_edge_buy_fire", "bar_edge_sell_fire",
        "n_edge_buy_active", "n_edge_sell_active",
    ],
    # Group C (Phase 1 commit 690f7c6)
    "Group C - rvol": [
        "rvol_regime", "rvol_buy_strong", "rvol_sell_strong", "rvol_extreme",
    ],
    "Group C - big_v2 aliases": [
        "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_bid_v2_t1",
        "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
    ],
    # Group D (commit 60e5461) + D1 (155dc62)
    "D1 - intermarket im_*": [
        "im_cross_delta_agreement_5", "im_smt_divergence",
        "im_rolling_correlation_10", "im_open_type_agreement",
        "im_price_ratio_slope_10", "im_volume_lead", "im_cross_open_signal",
        "im_delta_day_divergence", "im_cross_delta_weighted_5",
        "im_ltr_slope_diff",
    ],
    # D2 (commit 7da7713)
    "D2 - phase_b_helpers session": [
        "date_et",
    ],
    "D2 - phase_b_helpers ib": [
        "ib_high", "ib_low", "ib_complete", "ib_range",
        "ib_broken_dn", "dist_ib_high_pct", "dist_ib_low_pct",
    ],
    "D2 - phase_b_helpers session_high_low": [
        "sess_high", "sess_low",
    ],
    "D2 - phase_b_helpers open_cash": [
        "open_cash",
    ],
    "D2 - phase_b_helpers ib_atr (J+3)": [
        "ib_atr",
    ],
    "D2 - phase_b_helpers price_1030 (J+1)": [
        "price_1030",
    ],
    "D2 - aliases _lvl": [
        "prev_vah", "prev_val", "prev_vpoc",
        "cur_vah", "cur_val", "cur_vpoc", "open_830",
    ],
    "D2 - game_changers (J+3)": [
        "open_type", "open_zone", "day_type",
        "open_direction", "open_bias_conf",
    ],
    # Sierra natif (validation preservation)
    "Sierra natif - bn_pressure (Sierra wins)": [
        "bn_pressure_ask", "bn_pressure_bid",
    ],
    "Sierra natif - dist_*_pct": [
        "dist_vwap_d_pct", "dist_cur_vpoc_pct", "dist_mq_call_pct",
    ],
    "Sierra natif - rvol base": [
        "rvol", "rvol_zscore", "rvol_buy", "rvol_sell",
    ],
}


def main():
    import os
    file = Path(os.environ.get("SIERRA_AUDIT_FILE",
                                 "D:/TRADING_SIERRA_CHART_AUTO/DATA/_tmp_sierra_last100.jsonl"))
    if not file.exists():
        print(f"ERROR : {file} introuvable")
        sys.exit(1)

    bars = []
    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            bars.append(json.loads(line))
    n_bars = len(bars)
    print(f"Bars analyzed : {n_bars}")
    print(f"Total fields per bar : {len(bars[-1])}")
    print()

    # Counter par feature : count non-NaN / non-None
    results = {}
    for group_name, features in FEATURE_GROUPS.items():
        group_stats = []
        for f in features:
            valid_count = 0
            for bar in bars:
                v = bar.get(f)
                if v is None:
                    continue
                if isinstance(v, float) and v != v:  # NaN
                    continue
                valid_count += 1
            coverage = valid_count / n_bars * 100
            group_stats.append((f, coverage))
        results[group_name] = group_stats

    # Affichage par groupe
    print("=" * 70)
    print("FEATURE COVERAGE BY GROUP (% bars avec valeur non-NaN/non-None)")
    print("=" * 70)
    total_features = 0
    total_active = 0
    for group_name, stats in results.items():
        avg_coverage = sum(c for _, c in stats) / len(stats) if stats else 0
        active_count = sum(1 for _, c in stats if c >= 80)
        total_features += len(stats)
        total_active += active_count
        flag = "OK" if avg_coverage >= 80 else ("WARN" if avg_coverage >= 50 else "FAIL")
        print(f"\n[{flag}] {group_name} ({avg_coverage:.0f}% moyenne, {active_count}/{len(stats)} actives)")
        for f, c in stats:
            mark = "OK" if c >= 80 else ("WARN" if c >= 50 else "FAIL")
            print(f"    {mark:4s} {f:50s} {c:5.1f}%")

    print()
    print("=" * 70)
    print(f"TOTAL : {total_active}/{total_features} features actives (>=80% bars non-NaN)")
    pct = total_active / total_features * 100
    print(f"Coverage : {pct:.1f}%")
    print("=" * 70)
    # Verdict GO/NO-GO
    if pct >= 80:
        print(f"VERDICT : GO Sierra prod (coverage {pct:.0f}% >= 80%)")
    elif pct >= 60:
        print(f"VERDICT : GO CONDITIONNEL ({pct:.0f}%) - identifier features manquantes")
    else:
        print(f"VERDICT : NOGO ({pct:.0f}% < 60%) - D3 VAP wrapper requis + investigation")


if __name__ == "__main__":
    main()
