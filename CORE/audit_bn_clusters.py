"""Audit ULTRATHINK comportement features BN en clusters.

Jackson : "audit cluster de 1, 2, 3 features BN ensemble pas isolees".

Methodologie :
1. Inventaire 14 features BN + baseline isolees (fire rate, distribution)
2. Matrice de co-occurrence PAIRS (Jaccard + Lift + PMI)
3. Triplets prometteurs (lift >> 1, sample_size >= 50)
4. Edge predictif : forward return horizon 5/15 bars apres cluster fire
5. Split regime : RTH vs OFF, Trend vs Range
6. Pieges methodologiques flag (lookahead _fwd1, multiple testing)

Anti-Pattern 11 V1 : pas de gate hardcode, juste mesure edge documente.
Lopez compliant : Sharpe + base rate + sample size pour chaque cluster.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# ====================================================================
# Config
# ====================================================================
BN_FEATURES = [
    # Absorbtion (acceptation passive)
    "bn_absorb_ask_at_level",
    "bn_absorb_ask_raw",
    "bn_absorb_bid_at_level",
    "bn_absorb_bid_raw",
    # Color (forward-looking, lookahead potentiel)
    "bn_color_dn_fwd1",
    "bn_color_dn_2_fwd1",
    "bn_color_up_fwd1",
    "bn_color_up_2_fwd1",
    # Stack (orders empilees DOM)
    "bn_stack_ask",
    "bn_stack_bid",
    # Trapped (prix piege au niveau)
    "bn_trapped_buyers_at_resistance",
    "bn_trapped_buyers_raw",
    "bn_trapped_sellers_at_support",
    "bn_trapped_sellers_raw",
]

FORWARD_HORIZONS = [5, 15]      # bars
MIN_SAMPLE_PAIR = 30            # pour statistique paire
MIN_SAMPLE_TRIPLET = 20         # pour statistique triplet
TICK_SIZE = 0.25


# ====================================================================
# Helpers stats
# ====================================================================
def fire_rate(s: pd.Series) -> float:
    """% bars ou feature == truthy non-zero."""
    if s.dtype == bool:
        return float(s.mean())
    return float((s != 0).mean())


def jaccard(a: pd.Series, b: pd.Series) -> float:
    """Intersection / union (sur fires uniquement)."""
    af = (a != 0).astype(int)
    bf = (b != 0).astype(int)
    inter = (af & bf).sum()
    union = (af | bf).sum()
    return inter / union if union > 0 else 0.0


def lift(a: pd.Series, b: pd.Series) -> float:
    """P(A & B) / (P(A) * P(B)). Lift > 1 = co-fire au-dela du hasard."""
    pa = float((a != 0).mean())
    pb = float((b != 0).mean())
    pab = float(((a != 0) & (b != 0)).mean())
    if pa * pb == 0:
        return 0.0
    return pab / (pa * pb)


def pmi(a: pd.Series, b: pd.Series) -> float:
    """Pointwise Mutual Information : log2(lift)."""
    L = lift(a, b)
    return float(np.log2(L)) if L > 0 else float("-inf")


def conditional_forward_return(
    df: pd.DataFrame,
    cond_mask: pd.Series,
    horizon: int,
    price_col: str = "close",
) -> dict:
    """Mesure forward return en TICKS apres cond_mask=True.

    Retourne :
      n: sample size
      mean_ticks: edge moyen
      median_ticks: edge median (robuste)
      win_rate_up: % returns > 0
      sharpe: ratio mean/std (ad-hoc 1-bar units)
      vs_base: edge - edge_global
    """
    if price_col not in df.columns or cond_mask.sum() == 0:
        return {"n": 0}
    fwd = (df[price_col].shift(-horizon) - df[price_col]) / TICK_SIZE
    fwd_cond = fwd[cond_mask & fwd.notna()]
    fwd_global = fwd[fwd.notna()]
    if len(fwd_cond) < 5:
        return {"n": int(len(fwd_cond))}
    return {
        "n": int(len(fwd_cond)),
        "mean_ticks": float(fwd_cond.mean()),
        "median_ticks": float(fwd_cond.median()),
        "win_rate_up": float((fwd_cond > 0).mean()),
        "sharpe": float(fwd_cond.mean() / fwd_cond.std()) if fwd_cond.std() > 0 else 0.0,
        "vs_base_mean": float(fwd_cond.mean() - fwd_global.mean()),
        "vs_base_winrate": float((fwd_cond > 0).mean() - (fwd_global > 0).mean()),
    }


# ====================================================================
# Audit niveaux
# ====================================================================
def audit_isolated(df: pd.DataFrame, sym: str, bn_cols: list[str]) -> pd.DataFrame:
    """Niveau 1 : baseline par feature isolee."""
    rows = []
    for c in bn_cols:
        s = df[c].dropna()
        if len(s) == 0:
            continue
        fr = fire_rate(s)
        rows.append({
            "feature": c,
            "n_bars": len(s),
            "fire_rate_pct": round(100 * fr, 3),
            "n_fires": int((s != 0).sum()),
            "mean": round(float(s.mean()), 4),
            "std": round(float(s.std()), 4),
            "max": float(s.max()),
            "autocorr_lag1": round(float(s.autocorr(lag=1)), 3) if s.std() > 0 else 0.0,
        })
    return pd.DataFrame(rows).sort_values("fire_rate_pct", ascending=False)


def audit_pairs(df: pd.DataFrame, bn_cols: list[str]) -> pd.DataFrame:
    """Niveau 2 : matrice de co-occurrence sur paires."""
    rows = []
    for a, b in combinations(bn_cols, 2):
        sa, sb = df[a], df[b]
        af, bf = (sa != 0), (sb != 0)
        n_a, n_b = int(af.sum()), int(bf.sum())
        n_ab = int((af & bf).sum())
        if n_a < 10 or n_b < 10:
            continue
        rows.append({
            "pair": f"{a} + {b}",
            "n_a": n_a,
            "n_b": n_b,
            "n_co_fire": n_ab,
            "jaccard": round(jaccard(sa, sb), 3),
            "lift": round(lift(sa, sb), 2),
            "pmi": round(pmi(sa, sb), 2),
            "p_b_given_a": round(n_ab / n_a, 3) if n_a > 0 else 0.0,
            "p_a_given_b": round(n_ab / n_b, 3) if n_b > 0 else 0.0,
        })
    return pd.DataFrame(rows).sort_values("lift", ascending=False)


def audit_triplets(df: pd.DataFrame, bn_cols: list[str], top_n: int = 30) -> pd.DataFrame:
    """Niveau 3 : top triplets par lift, filtrer sample_size."""
    rows = []
    for a, b, c in combinations(bn_cols, 3):
        sa, sb, sc = (df[a] != 0), (df[b] != 0), (df[c] != 0)
        n_abc = int((sa & sb & sc).sum())
        if n_abc < MIN_SAMPLE_TRIPLET:
            continue
        pa, pb, pc = float(sa.mean()), float(sb.mean()), float(sc.mean())
        pabc = float((sa & sb & sc).mean())
        lift3 = pabc / (pa * pb * pc) if (pa * pb * pc) > 0 else 0.0
        rows.append({
            "triplet": f"{a} + {b} + {c}",
            "n_co_fire": n_abc,
            "lift_3way": round(lift3, 2),
            "p_abc": round(pabc, 5),
        })
    if not rows:
        return pd.DataFrame(columns=["triplet", "n_co_fire", "lift_3way", "p_abc"])
    df_t = pd.DataFrame(rows).sort_values("lift_3way", ascending=False)
    return df_t.head(top_n)


def audit_edge(
    df: pd.DataFrame,
    bn_cols: list[str],
    cluster_size: int = 1,
    horizons: list[int] = FORWARD_HORIZONS,
) -> pd.DataFrame:
    """Niveau 4 : edge predictif (forward return) pour cluster size N."""
    rows = []
    if cluster_size == 1:
        clusters = [(c,) for c in bn_cols]
    elif cluster_size == 2:
        clusters = list(combinations(bn_cols, 2))
    elif cluster_size == 3:
        clusters = list(combinations(bn_cols, 3))
    else:
        return pd.DataFrame()

    for combo in clusters:
        # cond = AND de toutes les features du cluster
        cond = pd.Series(True, index=df.index)
        for f in combo:
            cond = cond & (df[f] != 0)
        n = int(cond.sum())
        if n < (MIN_SAMPLE_PAIR if cluster_size <= 2 else MIN_SAMPLE_TRIPLET):
            continue
        row = {
            "cluster": " + ".join(combo),
            "size": cluster_size,
            "n_fires": n,
        }
        for h in horizons:
            res = conditional_forward_return(df, cond, h)
            if res.get("n", 0) >= 5:
                row[f"fwd{h}_mean_ticks"] = round(res["mean_ticks"], 2)
                row[f"fwd{h}_winrate"] = round(res["win_rate_up"], 3)
                row[f"fwd{h}_sharpe"] = round(res["sharpe"], 2)
                row[f"fwd{h}_vs_base_winrate"] = round(res["vs_base_winrate"], 3)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def audit_regime_split(
    df: pd.DataFrame,
    cluster: tuple,
    horizon: int = 5,
) -> dict:
    """Niveau 5 : edge par regime (RTH/OFF, VIX, day_type)."""
    cond = pd.Series(True, index=df.index)
    for f in cluster:
        cond = cond & (df[f] != 0)

    out = {"cluster": " + ".join(cluster), "horizon": horizon}

    # Global
    res = conditional_forward_return(df, cond, horizon)
    out["global_n"] = res.get("n", 0)
    out["global_mean_ticks"] = res.get("mean_ticks")
    out["global_winrate"] = res.get("win_rate_up")

    # RTH split (utilise is_rth si dispo, sinon use ts_event UTC 13:30-20:00)
    if "is_rth" in df.columns:
        rth_mask = df["is_rth"] == 1
    else:
        ts = pd.to_datetime(df["ts_event"]).dt.tz_localize(None) if df["ts_event"].dtype == "O" else pd.to_datetime(df["ts_event"])
        rth_mask = (ts.dt.hour >= 13) & ((ts.dt.hour < 20) | ((ts.dt.hour == 20) & (ts.dt.minute == 0)))

    res_rth = conditional_forward_return(df[rth_mask], cond[rth_mask], horizon)
    res_off = conditional_forward_return(df[~rth_mask], cond[~rth_mask], horizon)
    out["rth_n"] = res_rth.get("n", 0)
    out["rth_winrate"] = res_rth.get("win_rate_up")
    out["off_n"] = res_off.get("n", 0)
    out["off_winrate"] = res_off.get("win_rate_up")

    # day_type (Dalton) si dispo
    if "day_type" in df.columns:
        for dt_val in [0, 1, 2, 3]:  # NORMAL, NORMAL_VAR, TREND, NEUTRAL etc
            mask = df["day_type"] == dt_val
            if mask.sum() < 100:
                continue
            res = conditional_forward_return(df[mask], cond[mask], horizon)
            if res.get("n", 0) >= 10:
                out[f"day_type_{dt_val}_n"] = res["n"]
                out[f"day_type_{dt_val}_winrate"] = round(res["win_rate_up"], 3)

    return out


# ====================================================================
# Main
# ====================================================================
def run_audit(symbol: str = "ES"):
    print(f"\n{'='*72}")
    print(f"  AUDIT BN CLUSTERS — {symbol} — ULTRATHINK")
    print(f"{'='*72}")

    parq = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5e.parquet"
    if not parq.exists():
        print(f"MISSING {parq}")
        return
    df = pd.read_parquet(parq)
    print(f"\nDataset: {parq.name}")
    print(f"  shape: {df.shape}")
    print(f"  ts range: {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # Filter aux cols BN presentes
    bn_present = [c for c in BN_FEATURES if c in df.columns]
    bn_missing = [c for c in BN_FEATURES if c not in df.columns]
    print(f"\n  BN cols presentes: {len(bn_present)}/{len(BN_FEATURES)}")
    if bn_missing:
        print(f"  BN cols MANQUANTES: {bn_missing}")

    if not bn_present:
        print("  AUCUNE BN col — abort")
        return

    # ===== NIVEAU 1 : isolees =====
    print(f"\n{'-'*72}")
    print(f" NIVEAU 1 — Baseline isolees ({len(bn_present)} BN)")
    print(f"{'-'*72}")
    iso = audit_isolated(df, symbol, bn_present)
    print(iso.to_string(index=False))

    # Filter pour suite : drop features 0% fire rate (pas exploitables)
    bn_active = [c for c in bn_present if (df[c] != 0).sum() >= 30]
    print(f"\n  BN avec >= 30 fires: {len(bn_active)}/{len(bn_present)}")
    if len(bn_active) < 2:
        print("  Pas assez de BN actives pour clusters — abort")
        return

    # ===== NIVEAU 2 : paires =====
    print(f"\n{'-'*72}")
    print(f" NIVEAU 2 — Co-occurrence PAIRS (top 15 par lift)")
    print(f"{'-'*72}")
    pairs = audit_pairs(df, bn_active)
    print(pairs.head(15).to_string(index=False))

    # Identifie paires "doublons" (lift > 5 et jaccard > 0.5 = redondance)
    doublons = pairs[(pairs["lift"] > 5) & (pairs["jaccard"] > 0.5)]
    if len(doublons) > 0:
        print(f"\n  ⚠️  PAIRS POTENTIELLEMENT REDONDANTES (lift>5 jaccard>0.5):")
        print(doublons[["pair", "lift", "jaccard"]].to_string(index=False))

    # ===== NIVEAU 3 : triplets =====
    print(f"\n{'-'*72}")
    print(f" NIVEAU 3 — Top TRIPLETS par lift (sample >= {MIN_SAMPLE_TRIPLET})")
    print(f"{'-'*72}")
    triplets = audit_triplets(df, bn_active, top_n=15)
    print(triplets.to_string(index=False))

    # ===== NIVEAU 4 : EDGE PREDICTIF =====
    print(f"\n{'-'*72}")
    print(f" NIVEAU 4 — EDGE PREDICTIF (forward return ticks horizons {FORWARD_HORIZONS})")
    print(f"{'-'*72}")

    # Edge isolees
    print(f"\n  -- ISOLEES --")
    edge1 = audit_edge(df, bn_active, cluster_size=1)
    edge1 = edge1.sort_values("fwd5_vs_base_winrate", ascending=False) if "fwd5_vs_base_winrate" in edge1.columns else edge1
    print(edge1.to_string(index=False))

    # Edge paires top 10 par lift
    print(f"\n  -- PAIRES (top 10 par edge fwd5 vs base winrate) --")
    edge2 = audit_edge(df, bn_active, cluster_size=2)
    if not edge2.empty and "fwd5_vs_base_winrate" in edge2.columns:
        edge2 = edge2.sort_values("fwd5_vs_base_winrate", ascending=False)
        print(edge2.head(10).to_string(index=False))

    # Edge triplets top 10
    print(f"\n  -- TRIPLETS (top 10 par edge fwd5 vs base winrate) --")
    edge3 = audit_edge(df, bn_active, cluster_size=3)
    if not edge3.empty and "fwd5_vs_base_winrate" in edge3.columns:
        edge3 = edge3.sort_values("fwd5_vs_base_winrate", ascending=False)
        print(edge3.head(10).to_string(index=False))

    # ===== NIVEAU 5 : REGIME SPLIT pour top 3 clusters =====
    print(f"\n{'-'*72}")
    print(f" NIVEAU 5 — REGIME SPLIT (top 3 triplets fwd5)")
    print(f"{'-'*72}")
    if not edge3.empty:
        top3 = edge3.head(3)
        for _, row in top3.iterrows():
            cluster = tuple(row["cluster"].split(" + "))
            split = audit_regime_split(df, cluster, horizon=5)
            print(f"\n  CLUSTER: {row['cluster']}")
            print(f"    n_fires={int(row['n_fires'])}, fwd5_winrate={row.get('fwd5_winrate'):.3f}, vs_base={row.get('fwd5_vs_base_winrate'):+.3f}")
            print(f"    RTH:  n={split.get('rth_n', 0):>4d}  winrate={split.get('rth_winrate', 0):.3f}" if split.get('rth_winrate') else "")
            print(f"    OFF:  n={split.get('off_n', 0):>4d}  winrate={split.get('off_winrate', 0):.3f}" if split.get('off_winrate') else "")
            for k in sorted([k for k in split if k.startswith("day_type_")]):
                if "winrate" in k:
                    n_key = k.replace("_winrate", "_n")
                    print(f"    {k.replace('_winrate', ''):20s}: n={split.get(n_key, 0):>4d}  winrate={split[k]:.3f}")

    # ===== WARNINGS METHODOLOGIQUES =====
    print(f"\n{'-'*72}")
    print(f" WARNINGS METHODOLOGIQUES")
    print(f"{'-'*72}")
    print("""
  ⚠️  LOOKAHEAD : `bn_color_*_fwd1` sont FORWARD-LOOKING (color de la BAR
      SUIVANTE). Si tu utilises ces features pour predire forward return,
      tu DOIS soustraire 1 bar a horizon. Sinon edge artificielle.

  ⚠️  MULTIPLE TESTING : C(14,3) = 364 triplets testes. Au seuil 0.05,
      18 triplets seraient "significatifs" par hasard pur. Filtrer par
      sample_size >= 30 ET vs_base_winrate >= 5% absolus avant trust.

  ⚠️  CLUSTER SIZE 3 = sample size petit. Edge mesure peut etre du noise.
      Repliquer cross-validation rolling avant trust.

  ⚠️  PATTERN 11 V1 INTERDIT : ne JAMAIS hardcode un cluster comme gate
      bloquant. Documenter l'edge, mesurer empiriquement, integrer comme
      bonus/malus de score (cf feedback_cross_instrument_bonus_not_gate.md).

  ⚠️  REGIME : edge global peut masquer comportements opposes par regime
      (ex: bull en RTH + bear en OFF). Toujours splitter avant deploy.
""")


if __name__ == "__main__":
    syms = sys.argv[1:] if len(sys.argv) > 1 else ["ES", "NQ"]
    for sym in syms:
        run_audit(sym)
