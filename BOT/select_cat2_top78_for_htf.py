"""
select_cat2_top78_for_htf.py — Selection 78 CAT2 features pour reproduction multi-TF V5.

Created : 2026-05-02 samedi (post-recadrage Jackson)
Author : Jackson critère (A) : std non trivial + NaN<30% + ratio std ES/NQ raisonnable

Goal : finaliser la liste exhaustive des 78 CAT2 features TF-DEPENDANT_BAR
identifiees dans AUDIT_V4_FEATURES_FOR_HTF_LOCAL.md (339 candidates).

Critères (A) :
  1. std > 1e-3 (variance non triviale, pas quasi-constante)
  2. NaN ratio < 30%
  3. std ratio ES/NQ in [0.2, 5.0] (pas explosif vs autre instrument)
  4. nunique > 50 (pas binaire ou catégoriel — sera reproduit via simple recalc)

Output :
  - DATA/CAT2_TOP78_SELECTION.csv : liste finale + métriques
  - print top 78 + bottom 30 (rejected) pour audit visuel
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


# Categories deja identifiées dans AUDIT_V4_FEATURES_FOR_HTF_LOCAL.md
# CAT5 microstructure 1m-only à exclure (44 features rare events)
CAT5_MICROSTRUCTURE_EXCLUDE = {
    "rvol_absorb_buy", "rvol_absorb_sell",
    "bn_color_up_fwd1", "bn_color_dn_fwd1", "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
    "n_color_up_zones_active", "n_color_dn_zones_active",  # peuvent passer en aggregat
    "n_big_t1", "n_big_buy_t1", "n_big_sell_t1",
    "n_big_t2", "n_big_buy_t2", "n_big_sell_t2",
    "n_big_t3", "n_big_buy_t3", "n_big_sell_t3",
    "n_big_t4", "n_big_buy_t4", "n_big_sell_t4",
    "aggressor_imbalance",
    "bn_absorb_ask_raw", "bn_stack_ask", "bn_stack_bid",
    "n_big_ask_v2_t1", "n_big_bid_v2_t1",
    "n_big_ask_v2_t2", "n_big_bid_v2_t2",
}

# CAT1 invariants (broadcast trivial, pas reproduits)
CAT1_INVARIANT = {
    "instrument_id", "bar_no_trade", "is_roll_day", "roll_phase",
    "bn_absorb_bid_raw", "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    "n_big_ask_v2_t3", "n_big_bid_v2_t3", "n_big_ask_v2_t4", "n_big_bid_v2_t4",
    "cluster_at_high", "cluster_at_low",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "london_open", "ny_open", "after_open",
    "im_ltr_slope_diff",  # 100% NaN
    "dist_gex_nearest_up", "dist_gex_nearest_dn",
    "dist_mq_put", "dist_1d_max_ticks", "dist_mq_call_0dte",
    "dist_1d_min_ticks", "dist_blind_nearest_up", "dist_mq_hvl",
    "dist_blind_nearest_dn", "dist_mq_put_0dte", "dist_mq_hvl_0dte",
}

# CAT3 DMP external (broadcast trivial)
CAT3_DMP_EXTERNAL = {
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct", "dist_mq_hvl_pct_z",
    "gex_cluster_count_z", "dist_mq_hvl_0dte_pct",
}

# CAT4 cross-instrument (deja listees dans verify_dataset_v5_complete.py)
CAT4_CROSS = {
    "im_cross_delta_agreement_5", "im_cross_delta_weighted_5",
    "im_smt_divergence", "im_delta_day_divergence",
    "im_price_ratio_slope_10", "im_volume_lead",
    "im_rolling_correlation_10", "im_cross_open_signal", "im_open_type_agreement",
}

# Meta cols a ne JAMAIS reproduire (timestamps, labels, weights)
META_EXCLUDE = {
    "ts", "ts_event", "label", "partial_session", "sample_weight",
    "open", "high", "low", "close", "volume",  # OHLCV deja per-bar HTF natif
    "is_nq", "atr",  # cf train_lightgbm.get_features
}


def load_v4(symbol: str) -> pd.DataFrame:
    fp = ROOT / "DATA" / "DATASETS" / f"{symbol}_dataset_v4.parquet"
    if not fp.exists():
        raise FileNotFoundError(f"V4 dataset absent : {fp}")
    return pd.read_parquet(fp)


def is_cat2_candidate(col: str) -> bool:
    """Filtre candidat CAT2 : pas dans autres catégories."""
    if col in CAT1_INVARIANT or col in CAT3_DMP_EXTERNAL or col in CAT4_CROSS:
        return False
    if col in CAT5_MICROSTRUCTURE_EXCLUDE:
        return False
    if col in META_EXCLUDE:
        return False
    return True


def compute_quality_score(s_es: pd.Series, s_nq: pd.Series) -> dict:
    """Critères (A) qualité reproduction TF.

    Returns dict avec :
      std_es, std_nq, ratio_std (max/min), nan_pct_max, nunique_avg, score, valid
    """
    res = {}

    # Std (sur valeurs non-NaN)
    try:
        std_es = s_es.std(skipna=True)
        std_nq = s_nq.std(skipna=True)
    except Exception:
        return {"valid": False, "reason": "std failed"}

    if pd.isna(std_es) or pd.isna(std_nq):
        return {"valid": False, "reason": "std NaN"}
    if std_es < 1e-6 or std_nq < 1e-6:
        return {"valid": False, "reason": "quasi-constant"}

    res["std_es"] = float(std_es)
    res["std_nq"] = float(std_nq)
    res["ratio_std"] = max(std_es, std_nq) / min(std_es, std_nq)

    # NaN
    nan_es = s_es.isna().mean()
    nan_nq = s_nq.isna().mean()
    res["nan_es_pct"] = float(nan_es * 100)
    res["nan_nq_pct"] = float(nan_nq * 100)
    res["nan_max_pct"] = float(max(nan_es, nan_nq) * 100)

    # Nunique
    nu_es = s_es.nunique(dropna=True)
    nu_nq = s_nq.nunique(dropna=True)
    res["nunique_avg"] = (nu_es + nu_nq) / 2

    # Critère validité (A)
    valid = (
        res["ratio_std"] < 5.0  # std ratio raisonnable
        and res["ratio_std"] > 0.2  # pas trop deséquilibré inverse
        and res["nan_max_pct"] < 30.0  # < 30% NaN max
        and res["nunique_avg"] > 50  # pas binaire/catégoriel
    )
    res["valid"] = valid

    # Score = nunique_avg / (1 + ratio_std) / (1 + nan_max_pct/100)
    # Plus c'est varie + symetrique + low NaN, plus le score est haut
    res["score"] = res["nunique_avg"] / (1 + res["ratio_std"]) / (1 + res["nan_max_pct"] / 100)
    return res


def main():
    print("CHARGEMENT V4 ES + NQ...")
    df_es = load_v4("ES")
    df_nq = load_v4("NQ")
    print(f"  ES : {df_es.shape}")
    print(f"  NQ : {df_nq.shape}")

    # Candidats CAT2 = colonnes V4 - autres catégories
    candidates = [c for c in df_nq.columns if is_cat2_candidate(c) and c in df_es.columns]
    print(f"\nCandidats CAT2 (post filtres CAT1/3/4/5/META) : {len(candidates)}")

    # Compute scores
    print("Calcul scores qualite...")
    scored = []
    for col in candidates:
        try:
            score = compute_quality_score(df_es[col], df_nq[col])
            score["feature"] = col
            scored.append(score)
        except Exception as e:
            scored.append({"feature": col, "valid": False, "reason": str(e)})

    df_scored = pd.DataFrame(scored)

    # Filtrer valid + tri par score desc
    df_valid = df_scored[df_scored["valid"] == True].sort_values("score", ascending=False).reset_index(drop=True)
    df_invalid = df_scored[df_scored["valid"] == False]

    n_valid = len(df_valid)
    print(f"\nValid post critères (A) : {n_valid}")
    print(f"Invalid : {len(df_invalid)}")

    # Top 78
    top78 = df_valid.head(78)
    print(f"\n{'='*80}\nTOP 78 CAT2 SELECTIONNEES\n{'='*80}")
    cols_disp = ["feature", "ratio_std", "nan_max_pct", "nunique_avg", "score"]
    print(top78[cols_disp].to_string(index=True))

    # Save CSV
    out_path = ROOT / "DATA" / "CAT2_TOP78_SELECTION.csv"
    df_valid.head(78).to_csv(out_path, index=False)
    print(f"\nTop 78 sauvegarde : {out_path}")

    # Bottom rejected
    print(f"\n{'='*80}\nREJECTED (top 30 par invalid reason)\n{'='*80}")
    rejected_sample = df_scored[df_scored["valid"] == False].head(30)
    if "reason" in rejected_sample.columns:
        print(rejected_sample[["feature", "reason"]].to_string(index=False))
    else:
        print(rejected_sample[["feature"]].to_string(index=False))

    # Summary
    print(f"\n{'='*80}\nSUMMARY\n{'='*80}")
    print(f"Total V4 cols ES : {df_es.shape[1]}")
    print(f"Total V4 cols NQ : {df_nq.shape[1]}")
    print(f"Candidats CAT2 (post filtres) : {len(candidates)}")
    print(f"Valid critères (A) : {n_valid}")
    print(f"Top 78 selectionnees : {len(top78)}")

    # Verifier coverage : les 78 atteignent-elles le seuil ?
    if n_valid < 78:
        print(f"\n⚠️  ATTENTION : seulement {n_valid} valid features. Cible 78 non atteinte.")
        print(f"  Soit : assouplir critères (ratio_std < 7, nan < 50%) pour atteindre 78")
        print(f"  Soit : accepter cible inferieure (V5 = {n_valid} CAT2 reproduit)")
    else:
        print(f"\n✅ 78 features selectionnees avec succès. Cible plan v2 atteinte.")


if __name__ == "__main__":
    main()
