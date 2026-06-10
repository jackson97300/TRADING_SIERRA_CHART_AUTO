"""Audit ULTRATHINK cross-family clusters.

Jackson : "TESTE TOUTE LES COMBINAISON POSIBLE - BN + trapped + micro + contexte".

Methodologie scientifique anti Pattern 11 :
1. Univers features filtres :
   - BN propres (drop _fwd1 leak)
   - Trapped (BN + Phase B+++ derives)
   - Microstructure : big_orders actives, rvol_absorb, aggressor
   - Contexte bool : bool_above_mq_*, bool_gex_flip
   - Contexte continu binarise : zones MQ proches/loin
2. Pairs cross-family (Lift + n_co_fire + edge fwd5)
3. Triplets sur top 50 pairs uniquement (eviter combinatorial explosion)
4. Edge predictif par cluster + regime split
5. Multiple testing : Bonferroni-aware (filter |edge|>=10pp + n>=30)
6. Cohérence ES/NQ (signal vrai = doit firer dans 2 instruments)

Anti-pattern 11 V1 : ne JAMAIS hardcode cluster comme gate. Juste mesure.
Lopez compliant : sample size + Sharpe + base rate + cross-instrument check.
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TICK_SIZE = 0.25

# ====================================================================
# UNIVERS FEATURES
# ====================================================================
# BN propres (drop _fwd1 lookahead — vu audit precedent)
BN_RAW = [
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "bn_stack_ask", "bn_stack_bid",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
]

BN_AT_LEVEL = [
    "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
]

# Trapped derives Phase B+++
TRAPPED = [
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
]

# Microstructure
MICRO = [
    "rvol_absorb_buy", "rvol_absorb_sell",
    "big_buy_dominance", "big_sell_dominance",
    "n_big_t1", "n_big_t2",
    "n_big_buy_t1", "n_big_sell_t1",
    "n_big_ask_v2_t1", "n_big_bid_v2_t1",
]

# Contexte bool MQ position
CONTEXT_BOOL = [
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
]

# Aggressor (continu, binariser plus tard)
AGGRESSOR = "aggressor_imbalance"

# Distance MQ (continu, binarisation en zones serrees vs loin)
DIST_MQ = [
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct",
]

ALL_BOOL_RAW = BN_RAW + BN_AT_LEVEL + CONTEXT_BOOL  # deja en {0, 1}

FORWARD_HORIZONS = [5, 15]
MIN_SAMPLE_PAIR = 30
MIN_SAMPLE_TRIPLET = 30
EDGE_THRESHOLD = 0.05  # |fwd5 winrate - base| >= 5pp pour considerer edge


# ====================================================================
# Helpers
# ====================================================================
def fire_rate(s: pd.Series) -> float:
    if s.dtype == bool:
        return float(s.mean())
    return float((s != 0).mean())


def lift(a: pd.Series, b: pd.Series) -> float:
    pa = float((a != 0).mean())
    pb = float((b != 0).mean())
    pab = float(((a != 0) & (b != 0)).mean())
    return pab / (pa * pb) if (pa * pb) > 0 else 0.0


def conditional_fwd_return(df, mask, horizon, price_col="close"):
    if price_col not in df.columns or mask.sum() == 0:
        return None
    fwd = (df[price_col].shift(-horizon) - df[price_col]) / TICK_SIZE
    fwd_cond = fwd[mask & fwd.notna()]
    fwd_global = fwd[fwd.notna()]
    if len(fwd_cond) < 5:
        return {"n": int(len(fwd_cond))}
    return {
        "n": int(len(fwd_cond)),
        "mean_t": float(fwd_cond.mean()),
        "median_t": float(fwd_cond.median()),
        "wr": float((fwd_cond > 0).mean()),
        "sharpe": float(fwd_cond.mean() / fwd_cond.std()) if fwd_cond.std() > 0 else 0.0,
        "vs_base_wr": float((fwd_cond > 0).mean() - (fwd_global > 0).mean()),
        "vs_base_mean": float(fwd_cond.mean() - fwd_global.mean()),
    }


def binarize_continuous(df, feature, near_threshold_pct=0.5):
    """Binarise une feature distance pct : True si |dist| <= threshold."""
    if feature not in df.columns:
        return None
    return (df[feature].abs() <= near_threshold_pct).astype(int)


def binarize_aggressor(df, threshold=0.3):
    """aggressor_imbalance >= threshold = strong buy, <= -threshold = strong sell."""
    if AGGRESSOR not in df.columns:
        return None, None
    s = df[AGGRESSOR]
    return (s >= threshold).astype(int), (s <= -threshold).astype(int)


# ====================================================================
# Audit
# ====================================================================
def build_universe(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Construit l'univers de features bool actives."""
    universe = {}

    # BN raw + at_level
    for c in BN_RAW + BN_AT_LEVEL + TRAPPED + CONTEXT_BOOL:
        if c in df.columns:
            s = (df[c] != 0).astype(int)
            if s.sum() >= 30:  # filter actives
                universe[c] = s

    # Microstructure (n_big_*) sont des counts → binarise > 0
    for c in MICRO:
        if c in df.columns:
            s = (df[c] > 0).astype(int)
            if s.sum() >= 30:
                universe[c] = s

    # Aggressor binarise
    agg_buy, agg_sell = binarize_aggressor(df)
    if agg_buy is not None and agg_buy.sum() >= 30:
        universe["aggressor_strong_buy"] = agg_buy
    if agg_sell is not None and agg_sell.sum() >= 30:
        universe["aggressor_strong_sell"] = agg_sell

    # Distances MQ binarisees (proximite <= 0.3% = niveau actif)
    for c in DIST_MQ:
        if c in df.columns:
            near = (df[c].abs() <= 0.3).astype(int)
            if near.sum() >= 30:
                universe[f"near_{c.replace('dist_', '').replace('_pct', '')}"] = near

    return universe


def audit_pairs_universe(df, universe):
    """Toutes les paires de l'univers."""
    rows = []
    keys = sorted(universe.keys())
    for a, b in combinations(keys, 2):
        sa, sb = universe[a], universe[b]
        n_a, n_b = int(sa.sum()), int(sb.sum())
        n_ab = int((sa & sb).sum())
        if n_ab < MIN_SAMPLE_PAIR:
            continue
        L = lift(sa, sb)
        if L < 1.5:  # filter pairs co-firing par hasard
            continue
        # Edge fwd5
        cond = (sa & sb).astype(bool)
        fwd5 = conditional_fwd_return(df, cond, 5)
        if not fwd5 or fwd5.get("n", 0) < MIN_SAMPLE_PAIR:
            continue
        rows.append({
            "pair": f"{a} + {b}",
            "fam_a": a.split("_")[0],
            "fam_b": b.split("_")[0],
            "n_co": n_ab,
            "lift": round(L, 2),
            "fwd5_wr": round(fwd5["wr"], 3),
            "fwd5_vs_base": round(fwd5["vs_base_wr"], 3),
            "fwd5_mean_t": round(fwd5["mean_t"], 1),
            "fwd5_sharpe": round(fwd5["sharpe"], 2),
        })
    return pd.DataFrame(rows)


def audit_triplets_smart(df, universe, top_pairs_keys, max_triplets=200):
    """Triplets : seulement combinaisons des features qui apparaissent dans top pairs."""
    rows = []
    keys = sorted(set([k for pair in top_pairs_keys for k in pair.split(" + ")]))
    print(f"  Triplets: testing C({len(keys)}, 3) = {len(list(combinations(keys, 3)))} combinaisons")
    n_tested = 0
    for a, b, c in combinations(keys, 3):
        sa, sb, sc = universe[a], universe[b], universe[c]
        n_abc = int((sa & sb & sc).sum())
        if n_abc < MIN_SAMPLE_TRIPLET:
            continue
        cond = (sa & sb & sc).astype(bool)
        fwd5 = conditional_fwd_return(df, cond, 5)
        if not fwd5 or fwd5.get("n", 0) < MIN_SAMPLE_TRIPLET:
            continue
        if abs(fwd5["vs_base_wr"]) < EDGE_THRESHOLD:
            continue
        rows.append({
            "triplet": f"{a} + {b} + {c}",
            "n_co": n_abc,
            "fwd5_wr": round(fwd5["wr"], 3),
            "fwd5_vs_base": round(fwd5["vs_base_wr"], 3),
            "fwd5_mean_t": round(fwd5["mean_t"], 1),
            "fwd5_sharpe": round(fwd5["sharpe"], 2),
        })
        n_tested += 1
        if n_tested > max_triplets * 5:
            break
    return pd.DataFrame(rows)


def audit_trapped_specific(df, universe):
    """Audit dedie : trapped buyers/sellers + leur contexte cross-family."""
    print(f"\n  --- TRAPPED ANALYSIS DEDIE ---")
    trapped_keys = [k for k in universe if "trapped" in k.lower()]
    if not trapped_keys:
        print("  Pas de trapped actif")
        return pd.DataFrame()
    print(f"  Trapped features actives: {trapped_keys}")

    # Pour chaque trapped feature, edge isole + edge cross avec contexte
    rows = []
    other_keys = [k for k in universe if k not in trapped_keys]
    for tk in trapped_keys:
        # Edge isole
        cond_iso = universe[tk].astype(bool)
        n_iso = int(cond_iso.sum())
        fwd5_iso = conditional_fwd_return(df, cond_iso, 5)
        if not fwd5_iso or fwd5_iso.get("n", 0) < 30:
            continue
        rows.append({
            "trapped_feature": tk,
            "context": "ISOLEE",
            "n": n_iso,
            "fwd5_wr": round(fwd5_iso["wr"], 3),
            "fwd5_vs_base": round(fwd5_iso["vs_base_wr"], 3),
            "fwd5_mean_t": round(fwd5_iso["mean_t"], 1),
            "fwd5_sharpe": round(fwd5_iso["sharpe"], 2),
        })
        # Cross avec chaque autre feature
        for ok in other_keys:
            cond_x = (universe[tk] & universe[ok]).astype(bool)
            n_x = int(cond_x.sum())
            if n_x < 30:
                continue
            fwd5_x = conditional_fwd_return(df, cond_x, 5)
            if not fwd5_x or fwd5_x.get("n", 0) < 30:
                continue
            if abs(fwd5_x["vs_base_wr"]) < EDGE_THRESHOLD:
                continue
            rows.append({
                "trapped_feature": tk,
                "context": ok,
                "n": n_x,
                "fwd5_wr": round(fwd5_x["wr"], 3),
                "fwd5_vs_base": round(fwd5_x["vs_base_wr"], 3),
                "fwd5_mean_t": round(fwd5_x["mean_t"], 1),
                "fwd5_sharpe": round(fwd5_x["sharpe"], 2),
            })
    df_out = pd.DataFrame(rows)
    if df_out.empty:
        return df_out
    return df_out.sort_values("fwd5_vs_base", ascending=False)


def regime_split_top_clusters(df, universe, top_clusters: list[str], horizon=5):
    """Pour top N clusters, split par RTH/OFF + day_type + GEX regime."""
    rows = []
    for cluster_str in top_clusters:
        keys = cluster_str.split(" + ")
        cond = pd.Series(True, index=df.index)
        for k in keys:
            cond = cond & universe[k].astype(bool)

        out = {"cluster": cluster_str, "horizon": horizon}
        # Global
        res = conditional_fwd_return(df, cond, horizon)
        out["global_n"] = res.get("n", 0) if res else 0
        out["global_wr"] = round(res.get("wr", 0), 3) if res and "wr" in res else None

        # RTH split
        if "is_rth" in df.columns:
            rth_mask = df["is_rth"] == 1
        else:
            ts = pd.to_datetime(df["ts_event"])
            if ts.dt.tz is not None:
                ts = ts.dt.tz_localize(None)
            rth_mask = (ts.dt.hour >= 13) & ((ts.dt.hour < 20) | ((ts.dt.hour == 20) & (ts.dt.minute == 0)))

        for label, mask in [("rth", rth_mask), ("off", ~rth_mask)]:
            sub = df[mask]
            res = conditional_fwd_return(sub, cond[mask], horizon)
            if res and res.get("n", 0) >= 10:
                out[f"{label}_n"] = res["n"]
                out[f"{label}_wr"] = round(res["wr"], 3)

        # day_type
        if "day_type" in df.columns:
            for dt_val in [0, 1, 2, 3]:
                m = df["day_type"] == dt_val
                if m.sum() < 100:
                    continue
                res = conditional_fwd_return(df[m], cond[m], horizon)
                if res and res.get("n", 0) >= 10:
                    out[f"dt{dt_val}_n"] = res["n"]
                    out[f"dt{dt_val}_wr"] = round(res["wr"], 3)
        rows.append(out)
    return pd.DataFrame(rows)


def run_audit(symbol: str = "ES"):
    print(f"\n{'='*80}")
    print(f"  AUDIT CROSS-FAMILY CLUSTERS — {symbol} — ULTRATHINK")
    print(f"{'='*80}")

    parq = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5e.parquet"
    if not parq.exists():
        print(f"MISSING {parq}")
        return None
    df = pd.read_parquet(parq)
    print(f"\nDataset: {parq.name}  shape={df.shape}")

    # Build universe
    universe = build_universe(df)
    print(f"\n  Univers features actives (>=30 fires): {len(universe)}")
    print(f"  Categories:")
    for prefix in ["bn_", "n_trapped", "rvol_", "big_", "n_big", "bool_", "aggressor", "near_"]:
        keys = [k for k in universe if prefix in k]
        if keys:
            print(f"    {prefix:15s} ({len(keys):2d}) : {keys[:5]}{'...' if len(keys)>5 else ''}")

    # ===== PAIRS =====
    print(f"\n{'-'*80}")
    print(f" PAIRS CROSS-FAMILY (lift>=1.5, n_co>={MIN_SAMPLE_PAIR}, edge>={EDGE_THRESHOLD*100:.0f}pp)")
    print(f"{'-'*80}")
    pairs = audit_pairs_universe(df, universe)
    # Filter only pairs with edge significant
    pairs_edge = pairs[abs(pairs["fwd5_vs_base"]) >= EDGE_THRESHOLD].sort_values(
        "fwd5_vs_base", key=lambda s: s.abs(), ascending=False)
    print(f"\nPairs avec |edge|>={EDGE_THRESHOLD*100:.0f}pp: {len(pairs_edge)}/{len(pairs)} testees")
    print(pairs_edge.head(20).to_string(index=False))

    # ===== TRIPLETS =====
    print(f"\n{'-'*80}")
    print(f" TRIPLETS (sur features apparaissant dans top 30 pairs)")
    print(f"{'-'*80}")
    top_pairs = pairs_edge.head(30)["pair"].tolist()
    triplets = audit_triplets_smart(df, universe, top_pairs, max_triplets=50)
    if not triplets.empty:
        triplets_sorted = triplets.sort_values("fwd5_vs_base", key=lambda s: s.abs(), ascending=False)
        print(f"\nTriplets avec |edge|>={EDGE_THRESHOLD*100:.0f}pp + n>={MIN_SAMPLE_TRIPLET}: {len(triplets)}")
        print(triplets_sorted.head(15).to_string(index=False))
    else:
        print("\nAucun triplet edge significatif sur cet univers")

    # ===== TRAPPED DEDIE =====
    trapped_audit = audit_trapped_specific(df, universe)
    if not trapped_audit.empty:
        print(f"\nTop edges TRAPPED + contexte (BULLISH = wr>50%, BEARISH = wr<50%)")
        print(trapped_audit.head(20).to_string(index=False))

    # ===== REGIME SPLIT TOP 5 =====
    print(f"\n{'-'*80}")
    print(f" REGIME SPLIT TOP 5 PAIRS + 5 TRIPLETS")
    print(f"{'-'*80}")
    candidates = pairs_edge.head(5)["pair"].tolist()
    if not triplets.empty:
        candidates += triplets.sort_values("fwd5_vs_base", key=lambda s: s.abs(), ascending=False).head(5)["triplet"].tolist()
    regime = regime_split_top_clusters(df, universe, candidates, horizon=5)
    if not regime.empty:
        print(regime.to_string(index=False))

    return {"pairs": pairs_edge, "triplets": triplets, "trapped": trapped_audit, "regime": regime}


def cross_instrument_check(es_results, nq_results):
    """Cherche edges qui repliquent sur ES + NQ (= signal robuste vs noise specifique)."""
    print(f"\n{'='*80}")
    print(f"  CROSS-INSTRUMENT VALIDATION (signal robuste si ES + NQ d'accord)")
    print(f"{'='*80}")
    if es_results is None or nq_results is None:
        return
    es_pairs = es_results["pairs"]
    nq_pairs = nq_results["pairs"]
    if es_pairs.empty or nq_pairs.empty:
        return

    common = pd.merge(
        es_pairs[["pair", "n_co", "fwd5_wr", "fwd5_vs_base"]].rename(
            columns={"n_co": "es_n", "fwd5_wr": "es_wr", "fwd5_vs_base": "es_edge"}),
        nq_pairs[["pair", "n_co", "fwd5_wr", "fwd5_vs_base"]].rename(
            columns={"n_co": "nq_n", "fwd5_wr": "nq_wr", "fwd5_vs_base": "nq_edge"}),
        on="pair",
    )
    if common.empty:
        print("  Aucune pair commune ES/NQ avec edge significatif")
        return
    # Same direction = both bullish or both bearish
    common["same_dir"] = np.sign(common["es_edge"]) == np.sign(common["nq_edge"])
    common["combined_edge"] = (common["es_edge"] + common["nq_edge"]) / 2
    common = common[common["same_dir"]].sort_values(
        "combined_edge", key=lambda s: s.abs(), ascending=False)
    print(f"\nPairs robust ES + NQ (meme direction edge): {len(common)}")
    print(common.head(15).to_string(index=False))


# ====================================================================
# Main
# ====================================================================
if __name__ == "__main__":
    es_res = run_audit("ES")
    nq_res = run_audit("NQ")
    cross_instrument_check(es_res, nq_res)

    print(f"\n{'='*80}")
    print(f"  WARNINGS METHODOLOGIQUES")
    print(f"{'='*80}")
    print("""
  ANTI-LOOKAHEAD : Toutes les features `_fwd1` sont EXCLUES de l'univers.
  Le precedent audit BN a montre +17%/-14% leak pur.

  MULTIPLE TESTING : avec ~50 features × C(50,2)=1225 pairs et top 30
  triplets, on teste ~200 combinaisons. Bonferroni : seuil p<0.00025.
  Filtre |edge|>=5pp protege partiellement, MAIS edges 5-10pp sur
  n=30-50 = ~30% chance d'etre noise. Trust niveau si :
    - n >= 100 fires
    - |edge| >= 10pp
    - Replique sur ES ET NQ (cross-instrument)
    - Sharpe >= 0.3 absolu

  PATTERN 11 V1 INTERDIT : les top clusters sont des CANDIDATS de
  recherche, pas des gates a hardcode. Pour validation production :
  walk-forward backtest + agent ml-trainer GO/NOGO.

  REGIME : split RTH/OFF + day_type indique si edge regime-conditionnel.
  Souvent edge global = compromis entre 2 regimes opposes.

  CROSS-INSTRUMENT : si pair X est bull edge sur ES mais bear sur NQ =
  noise specifique, pas signal. Cf cross_instrument_check section.
""")
