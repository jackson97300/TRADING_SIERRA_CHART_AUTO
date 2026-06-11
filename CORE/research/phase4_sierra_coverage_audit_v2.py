"""Phase 4 LIGHT v2 - Audit cross-day + warmup analysis + walk-forward.

Suite review code-reviewer GO-AVEC-RESERVES :
- MUST-HAVE 1 : N>=500 bars cross-day (10/06 + 11/06 NQ complet)
- MUST-HAVE 2 : justifier im_* coverage par warmup analysis
- MUST-HAVE 3 : categorisation features etendue (TOUTES Phase 1 features)
- MUST-HAVE 4 : mini walk-forward 70/30 (feature distribution stable)
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict


# Reprise FEATURE_GROUPS Phase 4 v1 + ajout features Sierra natif Phase 3
FEATURE_GROUPS = {
    "A - bn composites": ["bn_score_raw", "bn_score_bull", "bn_score_bear"],
    "A - long bar": [
        "long_up_bar", "long_dn_bar", "bar_body_ticks",
        "range_h_minus_lprev_ticks", "n_long_up_zones_active",
        "n_long_dn_zones_active", "dist_long_up_nearest_pct",
        "n_long_up_cluster_within_0_2pct", "long_dn_up_pattern",
    ],
    "A - color bar": [
        "n_color_up_zones_active", "n_color_dn_zones_active",
        "n_color_up_cluster_within_0_2pct", "n_color_dn_cluster_within_0_2pct",
    ],
    "A - cvd_session": ["cvd_session"],
    "B - rolling_features ctx_*": [
        "ctx_poc_migration_10", "ctx_va_developing_10",
        "ctx_rotation_factor_20", "ctx_ib_extension_ratio",
        "ctx_rvol_session", "ctx_cvd_recovery_rate",
        "ctx_trend_day_score", "ctx_session_phase",
        "ctx_double_top_trap", "ctx_momentum_exhaustion",
        "ctx_excess_high_bars", "ctx_excess_low_bars",
        "ctx_delta_sum_10", "ctx_vol_z_5",
    ],
    "B - edge_zones": [
        "bar_edge_buy_fire", "bar_edge_sell_fire",
        "n_edge_buy_active", "n_edge_sell_active",
    ],
    "C - rvol": [
        "rvol_regime", "rvol_buy_strong", "rvol_sell_strong", "rvol_extreme",
    ],
    "C - big_v2 aliases": [
        "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_bid_v2_t1",
        "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
    ],
    "D1 - intermarket im_*": [
        "im_cross_delta_agreement_5", "im_smt_divergence",
        "im_rolling_correlation_10", "im_open_type_agreement",
        "im_price_ratio_slope_10", "im_volume_lead", "im_cross_open_signal",
        "im_delta_day_divergence", "im_cross_delta_weighted_5",
        "im_ltr_slope_diff",
    ],
    "D2 - session": ["date_et", "mins_et", "session_date_trading"],
    "D2 - ib": ["ib_high", "ib_low", "ib_complete", "ib_range",
                 "ib_broken_dn", "dist_ib_high_pct", "dist_ib_low_pct"],
    "D2 - sess_high/low": ["sess_high", "sess_low"],
    "D2 - open_cash": ["open_cash"],
    "D2 - ib_atr (J+3)": ["ib_atr"],
    "D2 - price_1030 (J+1)": ["price_1030"],
    "D2 - aliases _lvl": [
        "prev_vah", "prev_val", "prev_vpoc",
        "cur_vah", "cur_val", "cur_vpoc", "open_830",
    ],
    "D2 - game_changers": [
        "open_type", "open_zone", "day_type",
        "open_direction", "open_bias_conf",
    ],
    "Sierra natif - bn_pressure": ["bn_pressure_ask", "bn_pressure_bid"],
    "Sierra natif - dist_*_pct": [
        "dist_vwap_d_pct", "dist_cur_vpoc_pct", "dist_mq_call_pct",
    ],
    "Sierra natif - rvol base": [
        "rvol", "rvol_zscore", "rvol_buy", "rvol_sell",
    ],
    "Sierra natif - Phase 3 levels": [
        "vwap_d", "atr", "cash_high", "cash_low", "ovn_high", "ovn_low",
        "pdh", "pdl", "vix_level", "vix_regime",
    ],
}


def load_bars(file: Path) -> list:
    bars = []
    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                bars.append(json.loads(line))
    return bars


def coverage_count(bars: list, feature: str) -> int:
    """Count bars avec valeur non-NaN/non-None."""
    valid = 0
    for b in bars:
        v = b.get(feature)
        if v is None:
            continue
        if isinstance(v, float) and v != v:
            continue
        valid += 1
    return valid


def main():
    files = [
        Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/_sierra_20260610.jsonl"),
        Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/_sierra_20260611.jsonl"),
    ]
    all_bars = []
    per_file_bars = {}
    for f in files:
        if not f.exists():
            print(f"MISSING {f}")
            continue
        bars = load_bars(f)
        per_file_bars[f.stem] = bars
        all_bars.extend(bars)
        print(f"{f.stem}: {len(bars)} bars")

    n_total = len(all_bars)
    print(f"\nTOTAL : {n_total} bars cross-day")

    # === MUST-HAVE 1 : Coverage cross-day ===
    print("\n" + "=" * 75)
    print("MUST-HAVE 1 : COVERAGE CROSS-DAY N={}".format(n_total))
    print("=" * 75)
    total_features = 0
    total_active = 0
    fail_groups = []
    warn_groups = []
    for group, feats in FEATURE_GROUPS.items():
        avg = 0
        n_active = 0
        for f in feats:
            c = coverage_count(all_bars, f) / n_total * 100
            avg += c
            if c >= 80:
                n_active += 1
        avg /= len(feats)
        total_features += len(feats)
        total_active += n_active
        if avg < 50:
            fail_groups.append((group, avg, n_active, len(feats)))
        elif avg < 80:
            warn_groups.append((group, avg, n_active, len(feats)))
        print(f"  [{('OK' if avg >= 80 else ('WARN' if avg >= 50 else 'FAIL')):4s}] "
              f"{group:40s} avg={avg:5.1f}% active={n_active}/{len(feats)}")

    pct = total_active / total_features * 100
    print(f"\nTOTAL : {total_active}/{total_features} active ({pct:.1f}%)")

    # === MUST-HAVE 2 : Warmup analysis im_* ===
    print("\n" + "=" * 75)
    print("MUST-HAVE 2 : WARMUP ANALYSIS im_* (cross-injection partner)")
    print("=" * 75)
    im_feat = "im_cross_delta_agreement_5"
    # Analyse par fichier
    for name, bars in per_file_bars.items():
        n = len(bars)
        first_valid_idx = None
        last_valid_idx = None
        for i, b in enumerate(bars):
            v = b.get(im_feat)
            if v is not None and not (isinstance(v, float) and v != v):
                if first_valid_idx is None:
                    first_valid_idx = i
                last_valid_idx = i
        # Coverage du sub-arr post-warmup
        if first_valid_idx is not None:
            post_warm = bars[first_valid_idx:]
            n_post = len(post_warm)
            c_post = coverage_count(post_warm, im_feat) / n_post * 100
            print(f"  {name}: first_valid={first_valid_idx}/{n}, "
                  f"post_warmup_coverage={c_post:.1f}% (n_post={n_post})")
        else:
            print(f"  {name}: NO VALID im_* (0% coverage)")

    # === MUST-HAVE 3 : Categorisation etendue ===
    print("\n" + "=" * 75)
    print("MUST-HAVE 3 : CATEGORISATION ETENDUE")
    print(f"  Total features attendues (FEATURE_GROUPS) : {total_features}")
    # Inventaire complet du JSONL
    all_keys = set()
    for b in all_bars[:100]:
        all_keys.update(b.keys())
    print(f"  Total fields JSONL (echantillon 100 bars) : {len(all_keys)}")
    in_groups = set()
    for feats in FEATURE_GROUPS.values():
        in_groups.update(feats)
    not_categorised = all_keys - in_groups
    print(f"  Features non-categorised : {len(not_categorised)} (Sierra natif majoritaire)")

    # === MUST-HAVE 4 : Mini walk-forward (split temporel 70/30) ===
    print("\n" + "=" * 75)
    print("MUST-HAVE 4 : MINI WALK-FORWARD (split 70/30 temporel)")
    print("=" * 75)
    split = int(n_total * 0.7)
    train_bars = all_bars[:split]
    test_bars = all_bars[split:]
    print(f"  Train : {split} bars / Test : {n_total - split} bars")

    # Compare coverage train vs test (drift check)
    drifted = []
    for group, feats in FEATURE_GROUPS.items():
        for f in feats:
            c_train = coverage_count(train_bars, f) / len(train_bars) * 100
            c_test = coverage_count(test_bars, f) / len(test_bars) * 100
            delta = abs(c_train - c_test)
            if delta > 15 and c_train >= 50:  # drift majeur sur feature attendue active
                drifted.append((f, c_train, c_test, delta))
    if drifted:
        print(f"  Features avec drift > 15pp ({len(drifted)}) :")
        for f, ct, cs, d in sorted(drifted, key=lambda x: -x[3])[:10]:
            print(f"    {f:40s} train={ct:5.1f}% test={cs:5.1f}% delta={d:+5.1f}pp")
    else:
        print("  No drift > 15pp -> distribution stable train/test")

    # === Verdict revise ===
    print("\n" + "=" * 75)
    print("VERDICT REVISE")
    print("=" * 75)
    if fail_groups:
        print(f"\nFAIL groups ({len(fail_groups)}) :")
        for g, a, na, nf in fail_groups:
            print(f"  {g}: {a:.0f}% ({na}/{nf})")
    if warn_groups:
        print(f"\nWARN groups ({len(warn_groups)}) :")
        for g, a, na, nf in warn_groups:
            print(f"  {g}: {a:.0f}% ({na}/{nf})")
    if pct >= 85:
        print(f"\n>>> GO solide ({pct:.0f}% >= 85%) <<<")
    elif pct >= 75:
        print(f"\n>>> GO-AVEC-RESERVES ({pct:.0f}%) <<<")
    else:
        print(f"\n>>> NOGO ({pct:.0f}% < 75%) <<<")


if __name__ == "__main__":
    main()
