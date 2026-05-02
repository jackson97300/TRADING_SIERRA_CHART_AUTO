"""
build_v5_dataset.py — Orchestrateur V5 PROPRE (Jackson Option Y validee)

Created : 2026-05-02 samedi V5 build (post-recadrage Jackson)
Strategy : tout reproduit Databento + V4 propre (jamais re-import DMP polluant).

Pipeline complet :
  1. Load V4 propre (429 cols ES/NQ post-audits qualite)
  2. enrich_1m_with_all_htf (resample 1m → 5m/15m/1h + 12 HTF features × 3 TF
     + MQ × 3 TF (51) + Trapped HTF aggregates (18))
  3. add_top_78_features_per_tf (78 CAT2 selectionnees critere A × 3 TF = 234)
  4. add_v5_simple_features (6 booleans contextuels)
  5. add_hvn_lvn_features (9 HVN/LVN session via Databento trades, rolling anti-leak)
  6. add_im_features_per_tf (CAT4 cross-instrument ES/NQ × 3 TF, 30 cols)
  7. RTH filter (9:30-16:00 ET DST-safe)
  8. apply labeler_v3 calibre (pt_sl=(1.5, 1.0) horizon=8 RTH-only)
  9. Save → DATA/DATASETS/v5/

Output cible : ~743 features V5 propre + labels Lopez.

Exclusions :
  - Phase B 5 features (vwap_ma_align, volume_imbalance, etc.) - DMP polluant, skip
  - Signal rules × 4 TF (96 cols) - Step 3b separate (adapt batch_tagger)
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import argparse
import time
import pandas as pd
import numpy as np
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

DATASETS_ROOT = ROOT / "DATA" / "DATASETS"
V5_OUTPUT = DATASETS_ROOT / "v5"
V5_OUTPUT.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════
# 1. LOAD V4 PROPRE
# ═════════════════════════════════════════════════════════════════════

def load_v4_propre(symbol: str,
                     date_min: Optional[str] = None,
                     date_max: Optional[str] = None) -> pd.DataFrame:
    """Charge V4 ES ou NQ avec filtre periode optionnel.

    Args:
        symbol : 'ES' ou 'NQ'
        date_min, date_max : 'YYYY-MM-DD' optionnels
    """
    fp = DATASETS_ROOT / f"{symbol}_dataset_v4.parquet"
    if not fp.exists():
        raise FileNotFoundError(f"V4 dataset absent : {fp}")
    df = pd.read_parquet(fp)
    print(f"[V5] V4 {symbol} : {df.shape[0]} rows × {df.shape[1]} cols")

    # Normalize ts_event tz-naive UTC
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(None)

    if date_min:
        df = df[df["ts_event"] >= pd.Timestamp(date_min)]
    if date_max:
        end_ts = pd.Timestamp(date_max) + pd.Timedelta(days=1)
        df = df[df["ts_event"] < end_ts]
    df = df.sort_values("ts_event").reset_index(drop=True)
    if date_min or date_max:
        print(f"[V5] Filter periode : {len(df)} rows ({date_min} → {date_max})")
    return df


# ═════════════════════════════════════════════════════════════════════
# 2. APPLY HTF PIPELINE (existant)
# ═════════════════════════════════════════════════════════════════════

def apply_htf_pipeline(df_v4: pd.DataFrame) -> pd.DataFrame:
    """Apply enrich_dataset_v5_htf : 12 HTF features × 3 TF + MQ × 3 TF + Trapped HTF."""
    from enrich_dataset_v5_htf import (
        enrich_1m_with_all_htf,
        add_mq_levels_per_tf,
        add_trapped_htf_aggregates,
    )

    n_before = df_v4.shape[1]

    # enrich_1m_with_all_htf : resample 1m → 5m/15m/1h + 12 HTF features × 3 TF
    print("[V5] HTF features (EMA/RSI/ATR × 3 TF)...")
    df = enrich_1m_with_all_htf(df_v4)
    print(f"[V5]   +{df.shape[1] - n_before} HTF base cols")
    n_pre_mq = df.shape[1]

    # MQ × 3 TF : 51 cols
    print("[V5] MenthorQ × 3 TF...")
    df = add_mq_levels_per_tf(df)
    print(f"[V5]   +{df.shape[1] - n_pre_mq} MQ cols")
    n_pre_trapped = df.shape[1]

    # Trapped HTF aggregates : 18 cols
    print("[V5] Trapped traders HTF aggregates...")
    df = add_trapped_htf_aggregates(df)
    print(f"[V5]   +{df.shape[1] - n_pre_trapped} Trapped HTF cols")

    return df


# ═════════════════════════════════════════════════════════════════════
# 3. APPLY TOP 78 CAT2 × TF
# ═════════════════════════════════════════════════════════════════════

def apply_top_78_cat2(df: pd.DataFrame) -> pd.DataFrame:
    """Apply 78 CAT2 features × 3 TF = 234 cols."""
    from enrich_dataset_v5_htf import add_top_78_features_per_tf

    cat2_csv = ROOT / "DATA" / "CAT2_TOP78_SELECTION.csv"
    if not cat2_csv.exists():
        raise FileNotFoundError(f"Top 78 CAT2 selection absent : {cat2_csv}")

    top78 = pd.read_csv(cat2_csv)["feature"].tolist()
    print(f"[V5] Top 78 CAT2 × 3 TF...")
    n_before = df.shape[1]
    df = add_top_78_features_per_tf(df, top78)
    print(f"[V5]   +{df.shape[1] - n_before} top 78 cols")
    return df


# ═════════════════════════════════════════════════════════════════════
# 4. APPLY 6 SIMPLES
# ═════════════════════════════════════════════════════════════════════

def apply_simples(df: pd.DataFrame) -> pd.DataFrame:
    """Apply 6 booleans contextuels (bool_near_level, bool_ib_inside, etc.)."""
    from v5_simple_features import add_v5_simple_features
    print("[V5] 6 simples (booleans + vwap_triple_align + dist_open_cash)...")
    n_before = df.shape[1]
    df = add_v5_simple_features(df)
    print(f"[V5]   +{df.shape[1] - n_before} simples cols")
    return df


# ═════════════════════════════════════════════════════════════════════
# 5. APPLY HVN/LVN SESSION
# ═════════════════════════════════════════════════════════════════════

def apply_hvn_lvn(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Apply 9 HVN/LVN session features (rolling anti-leak Databento trades).

    Note : module lent (~7 min/7 mois data, ~3h/15 ans).
    """
    from v5_hvn_lvn_features import add_hvn_lvn_features
    print(f"[V5] HVN/LVN session × 9 cols (rolling anti-leak Databento trades)...")
    n_before = df.shape[1]
    t0 = time.time()
    df = add_hvn_lvn_features(df, symbol=symbol)
    print(f"[V5]   +{df.shape[1] - n_before} HVN/LVN cols ({time.time()-t0:.0f}s)")
    return df


# ═════════════════════════════════════════════════════════════════════
# 6. APPLY CAT4 CROSS-INSTRUMENT (besoin ES + NQ)
# ═════════════════════════════════════════════════════════════════════

def apply_cat4_cross(df_es: pd.DataFrame, df_nq: pd.DataFrame) -> tuple:
    """CAT4 cross-instrument × 3 TF (besoin ES + NQ enrichis ensemble).

    FIX review R2 : drop cols CAT4 100% NaN apres compute (data-quality.md).
    Cause connue : V4 manque delta_day + large_trader_ratio (DMP polluant non-reingere).
    → 6 cols (im_delta_day_divergence_*, im_ltr_slope_diff_*) × 3 TF = 100% NaN.
    """
    from enrich_dataset_v5_htf import add_im_features_per_tf
    print("[V5] CAT4 cross-instrument × 3 TF (ES + NQ)...")
    n_before_es = df_es.shape[1]
    n_before_nq = df_nq.shape[1]
    df_es, df_nq = add_im_features_per_tf(df_es, df_nq)
    n_added_es = df_es.shape[1] - n_before_es
    n_added_nq = df_nq.shape[1] - n_before_nq
    print(f"[V5]   ES +{n_added_es} CAT4 cols")
    print(f"[V5]   NQ +{n_added_nq} CAT4 cols")

    # FIX R2 : drop cols 100% NaN ajoutees par CAT4
    cat4_cols_es = [c for c in df_es.columns[-n_added_es:]] if n_added_es > 0 else []
    cat4_cols_nq = [c for c in df_nq.columns[-n_added_nq:]] if n_added_nq > 0 else []
    nan_only_es = [c for c in cat4_cols_es if df_es[c].isna().all()]
    nan_only_nq = [c for c in cat4_cols_nq if df_nq[c].isna().all()]
    if nan_only_es:
        df_es = df_es.drop(columns=nan_only_es)
        print(f"[V5]   ES drop {len(nan_only_es)} CAT4 cols 100% NaN : {nan_only_es[:3]}...")
    if nan_only_nq:
        df_nq = df_nq.drop(columns=nan_only_nq)
        print(f"[V5]   NQ drop {len(nan_only_nq)} CAT4 cols 100% NaN : {nan_only_nq[:3]}...")

    return df_es, df_nq


# ═════════════════════════════════════════════════════════════════════
# 7. RTH FILTER (DST-safe)
# ═════════════════════════════════════════════════════════════════════

def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Garde uniquement bars RTH 9:30-16:00 ET (DST-safe via tz_convert).

    Cf labeler_v3 grid search : RTH-only obligatoire pour distribution
    50/50 BUY/SELL (sans = biais SL 57/43 sur overnight).
    """
    if "ts_event" not in df.columns:
        return df
    n_before = len(df)
    ts = pd.to_datetime(df["ts_event"], utc=True)
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    ts_et = ts.dt.tz_convert("America/New_York")
    mask = (
        ((ts_et.dt.hour == 9) & (ts_et.dt.minute >= 30))
        | ((ts_et.dt.hour > 9) & (ts_et.dt.hour < 16))
    )
    df = df[mask].reset_index(drop=True)
    print(f"[V5] RTH filter : {n_before} → {len(df)} bars ({len(df)/max(n_before,1):.1%})")
    return df


# ═════════════════════════════════════════════════════════════════════
# 8. APPLY LABELER V3 CALIBRE
# ═════════════════════════════════════════════════════════════════════

def apply_labeler_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Apply labeler v3 Triple Barrier Lopez calibre 1m natif.

    HISTORIQUE FIXES :
    - Original : tf_name='1m' pt_sl=(1.5, 1.0) h=8 → biais 44/55 (h trop court)
    - Fix audit mobile 9/10 : h=40 (40 min cible) → biais 42/58 (pire,
      car vol 1m ≠ vol 5m × sqrt(5), pt_sl=(1.5, 1.0) tight sur 1m)
    - Mini grid 1m bars : (1.0, 1.0) h=60 → 52/48 symetrique ✅

    Calibrage final 1m natif :
      pt_sl = (1.0, 1.0)  : RR=1.0 symetrique (TP=SL distance vol)
      horizon = 60        : 60 min (1h cible)
      tf_name = '1m'      : vol_span 390 (1 jour 1m bars)

    Note : differe du grid search 5m (1.5/1.0 h=8). C'est NORMAL — chaque TF
    a sa propre dynamique de vol-scaling. Pour 1m bars, RR=1.0 + horizon=60
    donne distribution 50/50 cible.

    Output : labels {-1, 0, +1} + sample_weight uniqueness Lopez ch.4.
    """
    from labeler_v3 import label_dataset_v3

    df_for_label = df[["ts_event", "open", "high", "low", "close", "volume"]].copy()
    print("[V5] Labeler v3 (pt_sl=(1.0, 1.0), horizon=60 bars 1m = 1h, RTH-only)...")
    events = label_dataset_v3(
        df_for_label,
        tf_name="1m",
        pt_sl=(1.0, 1.0),
        horizon_bars=60,
        rvol_threshold=0.3,
    )
    if events.empty:
        # FIX R3 : fail-loud (au lieu de return silent sans labels)
        # Si labeler retourne empty alors qu'on a demande labels, c'est un BUG
        # qu'il faut investiguer (pas un dataset utilisable shippe en silence).
        raise RuntimeError(
            f"[V5] Labeler v3 : 0 events produits sur {len(df)} bars. "
            f"Investiguer (bars insuffisantes ? pre-filter trop agressif ?)."
        )

    # Drop anciens labels V4 (label v2) AVANT merge labels v3 (sinon conflit)
    cols_to_drop = [c for c in ["label", "sample_weight"] if c in df.columns]
    if cols_to_drop:
        print(f"[V5] Drop V4 cols (replacees par labeler v3) : {cols_to_drop}")
        df = df.drop(columns=cols_to_drop)

    # Merge labels par ts_event
    out = df.set_index("ts_event").join(
        events[["label", "sample_weight", "barrier_type", "ts_t1_actual"]],
        how="inner",
    ).reset_index()
    dist = out["label"].value_counts(normalize=True)
    print(f"[V5] Labels distribution : "
          f"+1={dist.get(1, 0):.1%}, 0={dist.get(0, 0):.1%}, "
          f"-1={dist.get(-1, 0):.1%}")
    return out


# ═════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR PRINCIPAL
# ═════════════════════════════════════════════════════════════════════

def build_v5_single_symbol(symbol: str,
                              date_min: Optional[str] = None,
                              date_max: Optional[str] = None,
                              apply_rth_first: bool = True) -> pd.DataFrame:
    """Build V5 dataset pour 1 symbole (sans CAT4 cross-instrument).

    OPTIM (audit Claude.com point 3) : RTH filter AVANT HVN/LVN economise
    ~30% temps calcul (HVN/LVN ne process que bars qui survivront).
    """
    print(f"\n{'='*70}\nBUILD V5 — {symbol} ({date_min} → {date_max})\n{'='*70}")
    t_total = time.time()

    df = load_v4_propre(symbol, date_min, date_max)
    df = apply_htf_pipeline(df)
    df = apply_top_78_cat2(df)
    df = apply_simples(df)

    # OPTIM : RTH filter avant HVN/LVN (30% economie temps)
    # Justification : HVN/LVN session calcule features SUR la bar courante.
    # Si bar overnight droppee plus tard, on a calcule pour rien.
    # Anti-leak preserve : profile session reste calcule sur trades RTH only.
    # NOTE : load_trades_session filtre RTH via tz_localize("America/New_York")
    # (DST-safe, applique tz_convert UTC apres) → 13:30-20:00 UTC en EDT,
    # 14:30-21:00 UTC en EST. Les fenetres glissent automatiquement avec DST.
    if apply_rth_first:
        df = filter_rth(df)

    df = apply_hvn_lvn(df, symbol)

    print(f"[V5] {symbol} build temps total: {time.time()-t_total:.0f}s")
    return df


def build_v5_pair(date_min: str = "2025-12-15",
                    date_max: str = "2026-04-30",
                    output_dir: Optional[Path] = None,
                    apply_labels: bool = True,
                    apply_rth: bool = True) -> dict:
    """Build pipeline V5 complet ES + NQ + CAT4 cross-instrument + labeler.

    Default periode : 2025-12-15 (start MenthorQ) → 2026-04-30.
    Justification : MenthorQ data dispo depuis 2025-12-15. Avant = mq_* NaN
    massif. Si V5 593 baseline GO, etendre a 15 ans pour final train.

    Args:
        date_min/date_max : periode V5
        output_dir : default DATA/DATASETS/v5/
        apply_labels : run labeler_v3 (default True)
        apply_rth : RTH filter avant labeler (default True, recommande)
    """
    output_dir = output_dir or V5_OUTPUT
    output_dir.mkdir(parents=True, exist_ok=True)
    t_total = time.time()

    # 1. Build chaque symbole (RTH filter applique avant HVN/LVN si apply_rth=True)
    df_es = build_v5_single_symbol("ES", date_min, date_max, apply_rth_first=apply_rth)
    df_nq = build_v5_single_symbol("NQ", date_min, date_max, apply_rth_first=apply_rth)

    # 2. CAT4 cross-instrument (ES + NQ ensemble, post-RTH si applique)
    print(f"\n{'='*70}\nCAT4 CROSS-INSTRUMENT\n{'='*70}")
    df_es, df_nq = apply_cat4_cross(df_es, df_nq)

    # 3. Labeler v3 calibre (RTH deja applique en step 1 si requested)
    if apply_labels:
        print(f"\n{'='*70}\nLABELER V3 CALIBRE\n{'='*70}")
        df_es = apply_labeler_v3(df_es)
        df_nq = apply_labeler_v3(df_nq)

    # 5. Save
    suffix = f"{date_min.replace('-', '')}_{date_max.replace('-', '')}"
    es_out = output_dir / f"ES_v5_{suffix}.parquet"
    nq_out = output_dir / f"NQ_v5_{suffix}.parquet"
    df_es.to_parquet(es_out, index=False)
    df_nq.to_parquet(nq_out, index=False)

    print(f"\n{'='*70}\nV5 BUILD COMPLETE — {time.time()-t_total:.0f}s\n{'='*70}")
    print(f"[V5] ES : {df_es.shape} → {es_out}")
    print(f"[V5] NQ : {df_nq.shape} → {nq_out}")
    return {"es": df_es, "nq": df_nq, "es_path": es_out, "nq_path": nq_out}


# ═════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-12-15")
    parser.add_argument("--end", default="2026-04-30")
    parser.add_argument("--no-labels", action="store_true",
                        help="Skip labeler_v3 (just dataset features)")
    parser.add_argument("--no-rth", action="store_true",
                        help="Skip RTH filter (24h dataset)")
    args = parser.parse_args()

    # FIX R1 (CRITIQUE review) : --no-rth + apply_labels = INCOHERENT
    # Grid search calibre labeler v3 (pt_sl=(1.5, 1.0) horizon=8) sur RTH-only.
    # Sans RTH filter, labels biaises 57/43 SL (cf grid search 2 passes).
    # → forcer --no-labels OU emettre WARNING explicite si caller insiste.
    if args.no_rth and not args.no_labels:
        print("=" * 70)
        print("[V5] WARN : --no-rth + apply_labels = labels potentiellement biaises")
        print("[V5]   Grid search calibre labeler sur RTH-only.")
        print("[V5]   Sur 24h, distribution observee : 57/43 SL (vs 50/50 RTH).")
        print("[V5]   Forcer --no-labels (recommande) ou continuer avec biais documente ?")
        print("=" * 70)
        # Default : forcer --no-labels pour eviter ship dataset biaise silencieusement
        # Si user veut explicitement, qu'il use --force-labels-without-rth (a coder si besoin)
        print("[V5] DEFAULT : --no-labels force pour eviter biais. Use --force pour override.")
        args.no_labels = True

    build_v5_pair(
        date_min=args.start,
        date_max=args.end,
        apply_labels=not args.no_labels,
        apply_rth=not args.no_rth,
    )
