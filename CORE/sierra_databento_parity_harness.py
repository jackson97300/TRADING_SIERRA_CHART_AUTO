"""Sierra / Databento Parity Harness : drift detection bar-par-bar.

Phase 0 Sierra Pipeline Port (11/06/2026) - Decision G design v2.

Harness pour comparer les outputs de Live-Enricher Databento (production prod)
vs Sierra-Enricher (en cours de validation) sur les memes bars d'une meme
journee. Sortie : drift report Markdown bar-par-bar par feature.

UTILISATION :
============
1. Choisir un jour avec collecte Databento ET Sierra (~24h post deploy Sierra).
2. Charger live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl (Databento).
3. Charger live_enriched/sierra/{SYM}/{YYYYMMDD}_{SYM}_sierra_enriched.jsonl.
4. Aligner par ts_event (bar 1m).
5. Pour chaque feature classée C1 (identique par construction) : drift mean abs.
6. Pour C2 (Sierra-only), C3 (Databento-only/degradation), C4 : exclusion ou seuil.

CRITERES GO/NOGO :
==================
- C1 OHLCV exact match : drift = 0% (NOGO si != 0)
- C1 derivees : drift mean abs < 5%, bars KO < 10%
- C1 signed (delta_bar, side) : match > 95%
- C2 Sierra-only : log INFO
- C3 Databento-only : log ALERTE si manquant
- C4 Phase 3c : drift mean abs < 5%, bars KO < 10%

Cf design doc : 2026-06-11-sierra-pipeline-port-phase0-design-v2.md section G.

STATUS Phase 0 : SKELETON. Implementation Phase 1.4.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# Categorisation features
# ═══════════════════════════════════════════════════════════════════════════════

# C1 - Features identiques par construction (drift mean abs < 5%)
C1_FEATURES_EXACT = (
    "open", "high", "low", "close", "volume", "total_vol",
    "session_id", "ts_event_ns",
)

C1_FEATURES_DERIVED = (
    # Distances ATR-normalisees
    "dist_pdh_atr", "dist_pdl_atr", "dist_vwap_d_atr",
    # MQ distances pct
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    # ATR
    "atr", "atr_14m", "atr_14m_pct",
    # Volume Profile
    "dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
    "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
    # Rolling ctx
    "ctx_vol_z_20", "ctx_delta_sum_3", "ctx_finish_strength_mean_5",
    # Sessions
    "asia_high", "asia_low", "london_high", "london_low",
    # Roll
    "is_roll_day", "days_since_roll", "roll_phase",
    # Wicks
    "bar_upper_wick_pct", "bar_lower_wick_pct",
)

C1_FEATURES_SIGNED = (
    "delta_bar", "vwap_d_side", "delta_day_dir", "cvd_day_dir",
)

# C2 - Sierra-only (acceptees, exclues drift)
C2_FEATURES_SIERRA_ONLY = (
    "cvd_day", "bn_absorb_ask", "bn_absorb_bid",
    "n_big_ask_t1", "n_big_ask_t2", "n_big_bid_t1", "n_big_bid_t2",
    "delta_div_strength",
)

# C3 - Databento-only / degradation acceptee (B2)
# Features VAP→trades aggreges : ecart 10-100x acceptable
C3_FEATURES_DEGRADED = (
    "p99_trade_size", "max_size_buy", "max_size_sell",
)

# C4 - Phase 3c features (drift standard 5%)
C4_FEATURES_PHASE3C = (
    "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
    "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct",
    "atr_regime_zscore_60d", "dist_naked_poc_nearest_pct",
)

# C5 - Python override autoritatif (B3+B5 design v2, decision Jackson)
# Sierra emet 0/placeholder casse, Python recalcul prioritaire via whitelist
# _safe_update (cf SierraPipelineOrchestrator.SIERRA_ZERO_NEVER_CALCULATED).
# EXCLU du drift check parity (Sierra=0.0 vs Python=X = drift infini par design).
# Log INFO uniquement en harness.
C5_FEATURES_PYTHON_OVERRIDE = (
    # B3 - BN famille recodee Python decision Jackson 11/06
    "bn_score_raw", "bn_score_bull", "bn_score_bear",
    "bn_pressure_ask", "bn_pressure_bid",
    # B5 - game_changers placeholders Sierra DMP
    "trend_day_probability",
    "open_direction",
)

# Seuils GO/NOGO
DRIFT_THRESHOLD_C1_DERIVED = 0.05      # 5% mean abs
BARS_KO_THRESHOLD_C1_DERIVED = 0.10    # 10% bars KO
SIGNED_MATCH_THRESHOLD_C1 = 0.95       # 95% bars signed match
DRIFT_THRESHOLD_C4_PHASE3C = 0.05      # 5%
BARS_KO_THRESHOLD_C4 = 0.10            # 10%


# ═══════════════════════════════════════════════════════════════════════════════
# Resultat harness
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParityReport:
    """Resultat parity check Sierra vs Databento sur 1 jour."""
    date: str
    symbol: str
    n_bars_db: int = 0
    n_bars_sierra: int = 0
    n_bars_matched: int = 0

    # Per-categorie stats
    c1_exact_match: int = 0
    c1_exact_mismatch: int = 0
    c1_derived_pass: int = 0
    c1_derived_fail: int = 0
    c1_signed_match_rate: dict = field(default_factory=dict)  # {feature: rate}

    # Drift details per feature
    drifts_mean_abs: dict = field(default_factory=dict)
    drifts_max: dict = field(default_factory=dict)
    n_bars_ko_per_feat: dict = field(default_factory=dict)

    # Verdict
    verdict: str = "PENDING"  # GO / NOGO / RESERVE

    @property
    def c1_pass_rate(self) -> float:
        total = self.c1_exact_match + self.c1_exact_mismatch
        if total == 0:
            return 0.0
        return self.c1_exact_match / total


# ═══════════════════════════════════════════════════════════════════════════════
# Implementation (Phase 1.4 - skeleton)
# ═══════════════════════════════════════════════════════════════════════════════

def load_jsonl_to_df(path: Path) -> pd.DataFrame:
    """Charge JSONL en DataFrame.

    Args:
        path : Path vers JSONL.

    Returns:
        pd.DataFrame avec une ligne par bar.
    """
    if not path.exists():
        raise FileNotFoundError(f"JSONL not found: {path}")
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(records)


def align_dataframes(
    df_db: pd.DataFrame,
    df_sierra: pd.DataFrame,
    on: str = "ts_event_ns",
) -> pd.DataFrame:
    """Aligne Databento et Sierra bars sur ts_event_ns (inner join).

    Args:
        df_db : Databento bars.
        df_sierra : Sierra bars (peut avoir ts en ms, convertir si necessaire).
        on : colonne join (default ts_event_ns).

    Returns:
        pd.DataFrame : colonnes _db et _sierra pour chaque feature commune.
    """
    # Conversion ts Sierra (ms) -> ts_event_ns si necessaire
    if "ts_event_ns" not in df_sierra.columns and "ts" in df_sierra.columns:
        df_sierra = df_sierra.copy()
        df_sierra["ts_event_ns"] = df_sierra["ts"].astype("int64") * 1_000_000

    return pd.merge(
        df_db, df_sierra,
        on=on,
        suffixes=("_db", "_sierra"),
        how="inner",
    )


def compute_drift_feature(
    aligned_df: pd.DataFrame,
    feature: str,
    threshold: float,
) -> tuple[float, float, int]:
    """Calcule drift mean abs + max + n_bars_ko pour 1 feature.

    Args:
        aligned_df : DataFrame avec colonnes {feature}_db et {feature}_sierra.
        feature : nom feature.
        threshold : seuil drift mean abs au-dessus duquel bar = KO.

    Returns:
        (drift_mean_abs, drift_max, n_bars_ko)
    """
    col_db = f"{feature}_db"
    col_sierra = f"{feature}_sierra"
    if col_db not in aligned_df.columns or col_sierra not in aligned_df.columns:
        return (float("nan"), float("nan"), 0)

    db_vals = pd.to_numeric(aligned_df[col_db], errors="coerce")
    sierra_vals = pd.to_numeric(aligned_df[col_sierra], errors="coerce")
    valid_mask = db_vals.notna() & sierra_vals.notna()
    if not valid_mask.any():
        return (float("nan"), float("nan"), 0)

    db_v = db_vals[valid_mask]
    sierra_v = sierra_vals[valid_mask]

    # Drift relatif : |sierra - db| / max(|db|, 1e-9)
    abs_drift = (sierra_v - db_v).abs() / db_v.abs().clip(lower=1e-9)
    drift_mean_abs = float(abs_drift.mean())
    drift_max = float(abs_drift.max())
    n_bars_ko = int((abs_drift > threshold).sum())

    return drift_mean_abs, drift_max, n_bars_ko


def compute_signed_match(
    aligned_df: pd.DataFrame,
    feature: str,
) -> float:
    """Pour features signed : ratio bars ou sign(sierra) == sign(db).

    Args:
        aligned_df : DataFrame avec colonnes {feature}_db et {feature}_sierra.
        feature : nom feature.

    Returns:
        float : ratio [0, 1] ou NaN si feature absent.
    """
    import numpy as np
    col_db = f"{feature}_db"
    col_sierra = f"{feature}_sierra"
    if col_db not in aligned_df.columns or col_sierra not in aligned_df.columns:
        return float("nan")

    db_vals = pd.to_numeric(aligned_df[col_db], errors="coerce")
    sierra_vals = pd.to_numeric(aligned_df[col_sierra], errors="coerce")
    valid_mask = db_vals.notna() & sierra_vals.notna()
    if not valid_mask.any():
        return float("nan")

    sign_db = np.sign(db_vals[valid_mask])
    sign_sierra = np.sign(sierra_vals[valid_mask])
    return float((sign_db == sign_sierra).mean())


def run_parity_harness(
    symbol: str,
    date: str,
    databento_path: Optional[Path] = None,
    sierra_path: Optional[Path] = None,
) -> ParityReport:
    """Execute le harness parity sur 1 jour pour 1 symbole.

    Args:
        symbol : ES, NQ.
        date : YYYYMMDD.
        databento_path : Path JSONL Databento (default DATA/live_enriched/{SYM}/{date}_{SYM}.jsonl).
        sierra_path : Path JSONL Sierra (default DATA/live_enriched/sierra/{SYM}/{date}_{SYM}_sierra_enriched.jsonl).

    Returns:
        ParityReport.

    STATUS Phase 0 : SKELETON. Implementation Phase 1.4 completion.
    """
    ROOT = Path(__file__).resolve().parents[1]

    if databento_path is None:
        databento_path = ROOT / "DATA" / "live_enriched" / symbol / f"{date}_{symbol}.jsonl"
    if sierra_path is None:
        sierra_path = (ROOT / "DATA" / "live_enriched" / "sierra" / symbol
                       / f"{date}_{symbol}_sierra_enriched.jsonl")

    df_db = load_jsonl_to_df(databento_path)
    df_sierra = load_jsonl_to_df(sierra_path)

    report = ParityReport(
        date=date,
        symbol=symbol,
        n_bars_db=len(df_db),
        n_bars_sierra=len(df_sierra),
    )

    aligned = align_dataframes(df_db, df_sierra)
    report.n_bars_matched = len(aligned)

    if report.n_bars_matched == 0:
        report.verdict = "NOGO_NO_ALIGNMENT"
        return report

    # Categorie C1 exact
    for feat in C1_FEATURES_EXACT:
        col_db = f"{feat}_db"
        col_sierra = f"{feat}_sierra"
        if col_db not in aligned.columns or col_sierra not in aligned.columns:
            continue
        exact_match = (aligned[col_db] == aligned[col_sierra]).sum()
        report.c1_exact_match += exact_match
        report.c1_exact_mismatch += len(aligned) - exact_match

    # Categorie C1 derivees
    for feat in C1_FEATURES_DERIVED:
        drift_mean, drift_max, n_ko = compute_drift_feature(
            aligned, feat, DRIFT_THRESHOLD_C1_DERIVED)
        report.drifts_mean_abs[feat] = drift_mean
        report.drifts_max[feat] = drift_max
        report.n_bars_ko_per_feat[feat] = n_ko
        ko_rate = n_ko / max(report.n_bars_matched, 1)
        if drift_mean < DRIFT_THRESHOLD_C1_DERIVED and ko_rate < BARS_KO_THRESHOLD_C1_DERIVED:
            report.c1_derived_pass += 1
        else:
            report.c1_derived_fail += 1

    # Categorie C1 signed
    for feat in C1_FEATURES_SIGNED:
        match_rate = compute_signed_match(aligned, feat)
        report.c1_signed_match_rate[feat] = match_rate

    # Verdict global
    c1_pass_rate_overall = (
        report.c1_pass_rate * 0.5
        + (report.c1_derived_pass / max(
            report.c1_derived_pass + report.c1_derived_fail, 1)) * 0.5
    )
    signed_min = min((v for v in report.c1_signed_match_rate.values()
                       if not pd.isna(v)), default=1.0)
    if c1_pass_rate_overall >= 0.95 and signed_min >= SIGNED_MATCH_THRESHOLD_C1:
        report.verdict = "GO"
    elif c1_pass_rate_overall >= 0.80:
        report.verdict = "RESERVE"
    else:
        report.verdict = "NOGO"

    return report


def report_to_markdown(report: ParityReport) -> str:
    """Convertit ParityReport en string Markdown."""
    lines = [
        f"# Parity Report {report.date} {report.symbol}",
        "",
        f"- Bars Databento : {report.n_bars_db}",
        f"- Bars Sierra : {report.n_bars_sierra}",
        f"- Bars matched : {report.n_bars_matched}",
        "",
        "## C1 Categorie",
        f"- Exact match rate : {report.c1_pass_rate*100:.1f}%",
        f"- Derivees PASS : {report.c1_derived_pass} / "
        f"FAIL : {report.c1_derived_fail}",
        "",
        "## Top drifts (C1 derived)",
        "| Feature | drift_mean_abs | drift_max | n_bars_ko |",
        "|---|---|---|---|",
    ]
    sorted_drifts = sorted(report.drifts_mean_abs.items(),
                            key=lambda kv: kv[1] if not pd.isna(kv[1]) else 0,
                            reverse=True)
    for feat, drift in sorted_drifts[:10]:
        max_d = report.drifts_max.get(feat, float("nan"))
        n_ko = report.n_bars_ko_per_feat.get(feat, 0)
        lines.append(f"| {feat} | {drift:.4f} | {max_d:.4f} | {n_ko} |")

    lines.append("")
    lines.append("## Signed match (C1)")
    for feat, rate in report.c1_signed_match_rate.items():
        lines.append(f"- {feat} : {rate*100:.1f}%")

    lines.append("")
    lines.append(f"## Verdict : **{report.verdict}**")

    return "\n".join(lines)
