"""Inventaire EXHAUSTIF features Python-only (live_enriched) candidates au port C++ Sierra.

Pour chaque feature Python-only :
1. Verifier qu'elle est calculee non-null sur >= 5 jours recents (utile reel)
2. Identifier source code Python (grep dans CORE/)
3. Classifier par famille fonctionnelle (25 familles)
4. Evaluer complexite port C++ (TRIVIAL / EASY / MEDIUM / HARD / IMPOSSIBLE)
5. Evaluer dependances autres features (DAG ordering)

Output : DOCS/PORT_C++_SIERRA_INVENTORY.md exhaustif
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PY_DIR = ROOT / "DATA" / "live_enriched" / "NQ"
SIERRA_DIR = ROOT / "DATA" / "NQ"
CORE_DIR = ROOT / "CORE"
OUT = ROOT / "DOCS" / "PORT_C++_SIERRA_INVENTORY.md"

# === BLACKLIST INFRASTRUCTURE (pas des features) ===
INFRA_BLACKLIST = {
    "schema_version", "n_columns", "instrument_id", "symbol", "sym", "contract",
    "date_et", "ts_event", "ts_event_iso", "ts_event_ns",
    "written_at_iso", "written_at_ts", "age_sec", "latency_s",
    "data_quality_flag", "trades_window_aligned", "trades_window_n",
    "trades_window_sec", "mq_schema_version", "mq_snapshot_ts", "mq_sym",
    "mq_trigger",
    "open", "high", "low", "close", "volume", "avg_price",
    "session_date", "session_date_trading",
    "_last_swing_high_price", "_last_swing_low_price", "bars_since_boot",
    "ts", "ts_int",
}

# === FAMILLES FONCTIONNELLES ===
# Mapping prefix/regex -> famille
FAMILY_PATTERNS = [
    # F1 - Sessions Fine
    ("F1_SessionsFine", [
        r"^is_in_(asia|london|us_cash|us_after)$",
        r"^(asia|london|us|after)_(high|low|open)$",
        r"^(asia|london|us|after)_open_approximate$",
        r"^dist_(asia|london|us|after)_(high|low|open)_pct$",
        r"^(ny|ny_)open$",
        r"^above_(asia|london|us|ny|after)_open$",
        r"^dist_ny_open_pct$",
        r"^mins_et$",
        r"^pct_in_range$",
        r"^position_in_range$",
        r"^is_cash_session$",
        r"^is_ib_window$",
        r"^session_segment$",
    ]),
    # F2 - Previous Levels & Cash Session
    ("F2_PrevLevels", [
        r"^(pdh|pdl|cur_pdh|cur_pdl)$",
        r"^dist_(pdh|pdl)_(pct|atr)$",
        r"^cash_(high|low)$",
        r"^dist_cash_(high|low)_pct$",
        r"^is_new_cash_(high|low)$",
        r"^is_new_sess_(high|low)$",
        r"^(open_cash|open_830_et|open_930_et)$",
        r"^above_open_(830|930)$",
        r"^dist_open_(830|930)_pct$",
        r"^ovn_(high|low|range_ticks|broken_up|broken_dn)$",
        r"^dist_ovn_(high|low)_pct$",
    ]),
    # F3 - Distances Normalisees Pct/ATR
    ("F3_DistNormalisees", [
        r"^dist_.*_(pct|atr)$",  # large
    ]),
    # F4 - VWAP Bands & Slopes
    ("F4_VWAP_Bands", [
        r"^vwap_(d|w|m)$",
        r"^vwap_(d|w|m)_sd[123][udb]?$",
        r"^vwap_(d|w|m)_sd[12]_(above|below)$",
        r"^vwap_d_cross_(up|dn)$",
        r"^vwap_slope_10_atr$",
        r"^pvwap(_sd1[ud])?$",
    ]),
    # F5a - CTX Rolling SIMPLES (peuvent etre portees)
    ("F5a_CTX_Simples", [
        r"^ctx_(delta_sum_[35]|delta_sum_10|delta_slope_5)$",
        r"^ctx_(vol_slope_5|vol_z_5|vol_sell_buy_ratio_5)$",
        r"^ctx_finish_strength_mean_5$",
        r"^ctx_range_vs_atr_10$",
        r"^ctx_price_slope_5$",
        r"^ctx_side_flip_count_10$",
        r"^ctx_absorption_(score|streak)_5$",
        r"^ctx_dist_vwap_velocity$",
        r"^ctx_vwap_slope_accel$",
        r"^ctx_(cvd|rvol)_session$",
        r"^ctx_cvd_recovery_rate$",
        r"^ctx_session_phase$",
        r"^ctx_va_width$",
        r"^ctx_rotation_factor_20$",
        r"^ctx_va_position_velocity$",
        r"^ctx_va_developing_10$",
        r"^ctx_ib_(extension_ratio|position_velocity)$",
        r"^ctx_mq_put_call_ratio$",
        r"^ctx_poc_migration_10$",
        r"^ctx_trend_day_score$",
        r"^ctx_day_type_intensity$",  # IMPORTANT (Spearman +0.83)
    ]),
    # F5b - CTX Rolling COMPLEXES (logiques metier patterns)
    ("F5b_CTX_Complexes", [
        r"^ctx_(climax_signal|failed_auction|instant_absorption)$",
        r"^ctx_(delta_exhaustion|momentum_exhaustion)$",
        r"^ctx_(poor_high|poor_low)$",
        r"^ctx_(excess_high_bars|excess_low_bars)$",
        r"^ctx_double_top_trap$",
        r"^ctx_(bars_since_div|div_density_20|div_at_swing|price_delta_div_3)$",
    ]),
    # F6 - Intermarket ES/NQ (RESTE PYTHON - besoin 2 streams joints)
    ("F6_Intermarket_PYTHON", [
        r"^im_",
    ]),
    # F7 - Divergences enrichies
    ("F7_Divergences", [
        r"^delta_div_(buy|sell)(_clean)?$",
        r"^delta_divergence_clean$",
        r"^delta_div_strength$",
        r"^n_delta_div_(buy|sell)_(zones_active|cluster_within_0_2pct)$",
        r"^dist_delta_div_(buy|sell)_nearest_pct$",
        r"^retest_(high|low)_delta_div$",
        r"^div_(confluence_with_regime|confluence_dmp|regime_proxy_ok|at_key_level_ticks)$",
    ]),
    # F8 - News calendar
    ("F8_News", [
        r"^is_news_\d{3,4}$",
        r"^within_news_\d{3,4}_5m$",
        r"^mins_(since|to_next)_news$",
    ]),
    # F9 - Roll calendar
    ("F9_Roll", [
        r"^(is_roll_day|days_since_roll|roll_phase)$",
    ]),
    # F10 - Swings enrichi
    ("F10_Swings_Enrichi", [
        r"^bars_since_last_swing_(high|low)$",
        r"^(equal_highs|equal_lows)_detected$",
        r"^liquidity_sweep_(high|low)_lag5$",
        r"^last_swing_(high|low)_session$",
        r"^swing_(high|low)_active_lag10$",
        r"^dist_last_swing_(high|low)_pct$",
    ]),
    # F11 - Regime Engine (RESTE PYTHON - orchestrateur)
    ("F11_Regime_PYTHON", [
        r"^regime_(actionable|confidence|favor|mode|range_votes|trend_votes|vol)$",
    ]),
    # F12 - Bar shape Python
    ("F12_BarShape", [
        r"^bar_body_(pct|ticks)$",
        r"^bar_(upper|lower)_wick_pct$",
        r"^bar_no_trade$",
        r"^long_(up|dn)_bar$",
        r"^long_(dn_up|up_dn)_pattern$",
        r"^range_h(prev)?_minus_l(prev)?_ticks$",
        r"^range_size$",
    ]),
    # F13 - RVOL avance
    ("F13_RVOL_Avance", [
        r"^rvol_(buy_strong|sell_strong|extreme|regime)$",
    ]),
    # F14 - Big orders V2
    ("F14_BigV2", [
        r"^n_big_(ask|bid)_v2_t[1234]$",
        r"^n_big_(buy|sell)_t[1234]$",
        r"^n_big_t[1234]$",
        r"^big_(buy|sell)_dominance$",
        r"^max_big_(ask|bid)_vol_in_bar$",
        r"^max_cluster_(size|volume|volume_v2)$",
        r"^n_cluster_groups$",
        r"^n_clusters$",
        r"^cluster_at_(high|low)$",
        r"^dist_(big_ask|big_bid)_nearest_pct$",
        r"^dist_cluster_nearest_(up|dn)_pct$",
    ]),
    # F15 - Trapped buyers/sellers
    ("F15_Trapped", [
        r"^bn_trapped_(buyers|sellers)(_at_(resistance|support)|_raw)?$",
        r"^n_trapped_(buyers|sellers)_(cluster_within_0_2pct|zones_active)$",
        r"^dist_trapped_(buyers|sellers)_nearest_pct$",
        r"^near_(resistance|support)_level$",
    ]),
    # F16 - BN absorb/stack
    ("F16_BN_AbsorbStack", [
        r"^bn_absorb_(ask|bid)(_at_level|_raw)?$",
        r"^bn_stack_(ask|bid)$",
    ]),
    # F17 - Long Up/Dn / Color / Edge zones
    ("F17_LongColorEdge", [
        r"^n_long_(up|dn)_(zones_active|cluster_within_0_2pct)$",
        r"^n_(color_up|color_dn|long_up|long_dn)_cluster_within_0_2pct$",
        r"^n_edge_(buy|sell)_active$",
        r"^dist_(long_up|long_dn|color_up|color_dn|edge_buy|edge_sell)_nearest_pct$",
    ]),
    # F18 - Spike origins
    ("F18_SpikeOrigins", [
        r"^spike_detected_lag3$",
        r"^n_spike_origins_(active|cluster_within_0_2pct)$",
        r"^dist_last_spike_origin_pct$",
        r"^bars_since_last_spike$",
    ]),
    # F19 - VIX Extended
    ("F19_VIX_Extended", [
        r"^vix_above_hvl_0dte$",
    ]),
    # F20 - Daily extremes / Naked POC
    ("F20_DailyExtremes", [
        r"^mq_1d_(min|max)$",
        r"^dist_1d_(min|max)_ticks(_pct)?$",
        r"^dist_naked_poc_nearest_pct$",
        r"^atr_regime_zscore_60d$",
    ]),
    # F21 - Aggressor enrichi
    ("F21_AggressorEnrichi", [
        r"^aggressor_imbalance$",
        r"^diag_imbalance_ofi_proxy$",
        r"^max_delta_bar$",
        r"^min_delta_bar$",
        r"^max_size_(buy|sell)$",
        r"^p99_trade_size$",
        r"^large_trader_max_size_proxy$",
        r"^delta_change$",
        r"^n_ticks_bar$",
        r"^finish_pct_up$",
        r"^finish_strong_(up|dn)$",
        r"^cvd_5d_rolling_ffd$",
    ]),
    # F22 - Position dans range
    ("F22_PositionRange", [
        r"^(premium|discount)_zone$",
        r"^inside_value_area$",
    ]),
    # F23 - VAH/VAL touches & Volume Profile valeurs absolues
    ("F23_VP_Absolus", [
        r"^cur_va_(n_buckets|total_vol)$",
        r"^(cur|prev)_(vah|val|vpoc)$",
    ]),
    # F24 - Quality flags
    ("F24_Quality", [
        r"^vol_spike_(up|dn)$",
        r"^vol_zscore_20$",
        r"^atr_14m_pct$",
    ]),
]


def classify_family(feature: str) -> str:
    for family, patterns in FAMILY_PATTERNS:
        for pat in patterns:
            if re.match(pat, feature):
                return family
    return "F25_Unclassified"


def load_bars(fp: Path) -> pd.DataFrame:
    bars = []
    with open(fp, "r", encoding="utf-8") as fh:
        for line in fh:
            try: bars.append(json.loads(line))
            except: pass
    return pd.DataFrame(bars)


def find_source(feature: str) -> str:
    """Localise le code source Python pour cette feature."""
    candidates = [
        CORE_DIR / "rolling_features_streaming.py",
        CORE_DIR / "rolling_features.py",
        CORE_DIR / "phase_b_helpers.py",
        CORE_DIR / "game_changers_streaming.py",
        CORE_DIR / "intermarket_features.py",
        CORE_DIR / "enricher_chain.py",
        CORE_DIR / "phase_b_plus_streaming.py",
        CORE_DIR / "live_enricher_writer.py",
        CORE_DIR / "vix_lite_reader.py",
        CORE_DIR / "eco_calendar.py",
    ]
    hits = []
    for fp in candidates:
        if not fp.exists(): continue
        try:
            content = fp.read_text(encoding="utf-8")
            if f'"{feature}"' in content or f"['{feature}']" in content or f"\"{feature}\"" in content:
                # Find line num
                for i, line in enumerate(content.split("\n"), 1):
                    if feature in line and ('"' + feature + '"' in line or "['" + feature + "']" in line):
                        hits.append(f"{fp.name}:{i}")
                        break
        except Exception:
            pass
    return " | ".join(hits) if hits else "NOT_FOUND"


def estimate_complexity(feature: str, family: str) -> str:
    """Estime complexite port C++ (TRIVIAL/EASY/MEDIUM/HARD/IMPOSSIBLE)."""
    if family.endswith("_PYTHON"):
        return "IMPOSSIBLE-RESTE-PYTHON"

    # Patterns trivial : juste ratio ou cast
    if "_pct" in feature or "_atr" in feature:
        if family in ("F3_DistNormalisees",):
            return "TRIVIAL"
    if family in ("F1_SessionsFine", "F9_Roll"):
        return "EASY"
    if family in ("F2_PrevLevels", "F4_VWAP_Bands", "F22_PositionRange", "F23_VP_Absolus",
                  "F12_BarShape", "F19_VIX_Extended"):
        return "EASY"
    if family in ("F5a_CTX_Simples", "F8_News", "F10_Swings_Enrichi", "F13_RVOL_Avance",
                  "F14_BigV2", "F18_SpikeOrigins", "F21_AggressorEnrichi", "F20_DailyExtremes",
                  "F24_Quality"):
        return "MEDIUM"
    if family in ("F5b_CTX_Complexes", "F7_Divergences", "F15_Trapped", "F16_BN_AbsorbStack",
                  "F17_LongColorEdge"):
        return "HARD"
    return "MEDIUM"


def main():
    # Recuperer features dans 5 jours recents Python
    files = sorted(PY_DIR.glob("*_NQ.jsonl"))[-5:]
    print(f"=== Inventaire Python-only features sur {len(files)} jours recents ===")
    all_features: Set[str] = set()
    null_counters: Dict[str, int] = {}
    total_bars = 0

    for fp in files:
        df = load_bars(fp)
        if df.empty: continue
        total_bars += len(df)
        for col in df.columns:
            if col in INFRA_BLACKLIST: continue
            all_features.add(col)
            null_counters[col] = null_counters.get(col, 0) + df[col].isna().sum()

    print(f"Features Python recensees (apres filter infra) : {len(all_features)}")

    # Get Sierra features for diff
    sierra_files = sorted(SIERRA_DIR.glob("*_NQ.jsonl"))[-5:]
    sierra_features: Set[str] = set()
    for fp in sierra_files:
        df = load_bars(fp)
        if df.empty: continue
        for col in df.columns:
            if col not in INFRA_BLACKLIST:
                sierra_features.add(col)

    python_only = all_features - sierra_features
    print(f"Python-only (manquantes Sierra) : {len(python_only)}")

    # Classify
    inventory = []
    for feat in sorted(python_only):
        family = classify_family(feat)
        null_pct = round(100 * null_counters.get(feat, 0) / max(total_bars, 1), 1)
        is_useful = null_pct < 50  # >= 50% non-null
        source = find_source(feat) if is_useful else "SKIPPED"
        complexity = estimate_complexity(feat, family)
        inventory.append({
            "feature": feat,
            "family": family,
            "null_pct": null_pct,
            "useful": is_useful,
            "source": source,
            "complexity": complexity,
        })

    df = pd.DataFrame(inventory)
    df = df.sort_values(["family", "feature"])

    # Stats par famille
    fam_stats = df.groupby("family").agg(
        n_features=("feature", "count"),
        n_useful=("useful", "sum"),
    ).reset_index().sort_values("n_features", ascending=False)

    # Stats par complexite
    comp_stats = df.groupby("complexity")["feature"].count().reset_index()

    # Rapport markdown
    md = []
    md.append("# Port C++ Sierra — Inventaire exhaustif features Python-only")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Mode** : ULTRATHINK exhaustif")
    md.append(f"**Echantillon** : 5 jours recents NQ")
    md.append(f"**Total features Python** (apres filter infra) : {len(all_features)}")
    md.append(f"**Sierra features** : {len(sierra_features)}")
    md.append(f"**Python-only (a porter)** : {len(python_only)}")
    md.append("")
    md.append("## Stats par famille")
    md.append("")
    md.append("| Famille | N features | N utiles (<50% null) |")
    md.append("|---|---|---|")
    for _, r in fam_stats.iterrows():
        md.append(f"| {r.family} | {r.n_features} | {r.n_useful} |")
    md.append("")
    md.append("## Stats par complexite C++")
    md.append("")
    md.append("| Complexite | N |")
    md.append("|---|---|")
    for _, r in comp_stats.iterrows():
        md.append(f"| {r.complexity} | {r.feature} |")
    md.append("")

    # Detail par famille
    for fam in sorted(df.family.unique()):
        sub = df[df.family == fam]
        md.append(f"## {fam} ({len(sub)} features, {sub.useful.sum()} utiles)")
        md.append("")
        md.append("| Feature | Null % | Utile | Source Python | Complexite |")
        md.append("|---|---|---|---|---|")
        for _, r in sub.iterrows():
            useful_mark = "✅" if r.useful else "❌"
            md.append(f"| `{r.feature}` | {r.null_pct}% | {useful_mark} | {r.source} | {r.complexity} |")
        md.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")

    # Resume console
    print("\n=== TOP FAMILLES (par count) ===")
    print(fam_stats.head(10).to_string(index=False))
    print("\n=== Complexites ===")
    print(comp_stats.to_string(index=False))


if __name__ == "__main__":
    main()
