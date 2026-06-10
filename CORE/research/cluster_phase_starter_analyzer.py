"""cluster_phase_starter_analyzer.py — Analyse clusters de niveaux au demarrage des phases.

Hypothese (livre Jackson 09/05) : a chaque phase montee/descente, le prix laisse des
traces structurelles qu'on peut exploiter. En particulier :
  - Au DEMARRAGE d'une phase haussiere = prix touche un cluster de niveaux SUPPORT
    (CUR_VAL, IB_LOW, MQ_PUT, GEX_DN, etc.) qui ont rebondi ensemble
  - Au DEMARRAGE d'une phase baissiere = prix touche un cluster RESISTANCE
    (CUR_VAH, IB_HIGH, MQ_CALL, GEX_UP, etc.) qui ont rejete ensemble

Si vrai statistiquement, ce cluster est un signal d'entree plus fort que niveau seul.

Methodologie :
  1. Definir PHASE = mouvement directionnel >= X ATR en N bars (ex: 25 ticks ES en 3-10 bars)
  2. Identifier BAR DEMARRAGE = local extremum (low pour up, high pour down)
  3. Compter NIVEAUX ACTIFS au demarrage dans un rayon (ex: dist_*_pct < 0.05% = ~5t ES)
  4. CLUSTER = >= 3 niveaux dans rayon
  5. Statistique :
     - % phases avec cluster (vs random bars baseline)
     - PF moyen apres cluster vs sans cluster
     - Top combinaisons de niveaux qui apparaissent ensemble

Source : DATA/datasets/v4_enriched/symbol={NQ,ES}.c.0/year=*/month=*/data.parquet

Run :
    python -X utf8 CORE/research/cluster_phase_starter_analyzer.py --symbol NQ
    python -X utf8 CORE/research/cluster_phase_starter_analyzer.py --symbol ES
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# Niveaux a tracker pour clustering (les 51 V4 + symetriques up/dn)
# Group SUPPORT = candidats au demarrage d'une UP phase (rebond)
SUPPORT_LEVELS = {
    "IB_LOW":      "dist_ib_low_pct",
    "CUR_VAL":     "dist_cur_val_pct",
    "PVAL":        "dist_prev_val_pct",
    "PDL":         "dist_pdl_pct",
    "SESS_LOW":    "dist_sess_low_pct",
    "CASH_LOW":    "dist_cash_low_pct",
    "OVN_LOW":     "dist_ovn_low_pct",
    "ASIA_LOW":    "dist_asia_low_pct",
    "LONDON_LOW":  "dist_london_low_pct",
    "MQ_PUT":      "dist_mq_put_pct",
    "MQ_PUT_0DTE": "dist_mq_put_0dte_pct",
    "GEX_DN":      "dist_gex_nearest_dn_pct",
    "MQ_HVL":      "dist_mq_hvl_pct",  # bidirectional
    "VWAP_SD1D":   "dist_vwap_d_sd1d_pct",
    "VWAP_SD2D":   "dist_vwap_d_sd2d_pct",
    "PVWAP_SD1D":  "dist_pvwap_sd1d_pct",
    "SWING_LOW":   "dist_last_swing_low_pct",
    "MQ_1D_MIN":   "dist_1d_min_ticks_pct",
    "TRAPPED_SELL":"dist_trapped_sellers_nearest_pct",  # trapped sellers = rebound LONG
    "EDGE_BUY":    "dist_edge_buy_nearest_pct",
    "DELTA_DIV_BUY":"dist_delta_div_buy_nearest_pct",
    "OPEN_830":    "dist_open_830_pct",  # bidirectional
    "OPEN_930":    "dist_open_930_pct",
}

# Group RESISTANCE = candidats au demarrage d'une DOWN phase (rejet)
RESISTANCE_LEVELS = {
    "IB_HIGH":     "dist_ib_high_pct",
    "CUR_VAH":     "dist_cur_vah_pct",
    "PVAH":        "dist_prev_vah_pct",
    "PDH":         "dist_pdh_pct",
    "SESS_HIGH":   "dist_sess_high_pct",
    "CASH_HIGH":   "dist_cash_high_pct",
    "OVN_HIGH":    "dist_ovn_high_pct",
    "ASIA_HIGH":   "dist_asia_high_pct",
    "LONDON_HIGH": "dist_london_high_pct",
    "MQ_CALL":     "dist_mq_call_pct",
    "MQ_CALL_0DTE":"dist_mq_call_0dte_pct",
    "GEX_UP":      "dist_gex_nearest_up_pct",
    "MQ_HVL":      "dist_mq_hvl_pct",
    "VWAP_SD1U":   "dist_vwap_d_sd1u_pct",
    "VWAP_SD2U":   "dist_vwap_d_sd2u_pct",
    "PVWAP_SD1U":  "dist_pvwap_sd1u_pct",
    "SWING_HIGH":  "dist_last_swing_high_pct",
    "MQ_1D_MAX":   "dist_1d_max_ticks_pct",
    "TRAPPED_BUY": "dist_trapped_buyers_nearest_pct",  # trapped buyers = rejection SHORT
    "EDGE_SELL":   "dist_edge_sell_nearest_pct",
    "DELTA_DIV_SELL":"dist_delta_div_sell_nearest_pct",
    "OPEN_830":    "dist_open_830_pct",
    "OPEN_930":    "dist_open_930_pct",
}

# Tick size par sym
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}


def load_v4(symbol: str, max_months: int = 6) -> pd.DataFrame:
    """Charge derniers max_months parquets v4 enriched."""
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_parquet(f))
        except Exception as e:
            print(f"  [WARN] {f}: {e}")
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_phases(df: pd.DataFrame, sym: str,
                  min_move_ticks: int = 25,
                  min_bars: int = 3, max_bars: int = 15):
    """Detect phases : mouvement directionnel >= min_move_ticks en [min_bars, max_bars] bars.

    Returns list of dicts:
      {start_idx, end_idx, direction (UP/DOWN), move_ticks, dur_bars}
    """
    tick = TICK_SIZE[sym]
    phases = []
    n = len(df)
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    i = 0
    while i < n - max_bars:
        # Cherche UP phase : low @ i puis monte de min_move en max max_bars
        end_max = min(i + max_bars, n - 1)
        # Up: max(highs[i+1:end_max]) - lows[i] >= min_move
        local_low = lows[i]
        for j in range(i + min_bars, end_max + 1):
            move_ticks_up = (highs[j] - local_low) / tick
            if move_ticks_up >= min_move_ticks:
                # Phase UP detectee : start=i (low), end=j (high reached)
                # Verifier que i est bien le local low (pas plus bas dans i-3..i)
                back = max(0, i - 3)
                if lows[i] == np.min(lows[back:j+1]):
                    phases.append({
                        "start_idx": i, "end_idx": j,
                        "direction": "UP",
                        "move_ticks": float(round(move_ticks_up, 1)),
                        "dur_bars": j - i,
                        "start_ts": df.iloc[i]["ts_event"],
                        "start_price": float(closes[i]),
                    })
                    i = j  # jump apres la phase pour eviter overlap
                    break
                else:
                    pass  # local low pas confirme

            # Down: lows[i+1:j] - highs[i] <= -min_move
            move_ticks_dn = (highs[i] - lows[j]) / tick
            if move_ticks_dn >= min_move_ticks:
                back = max(0, i - 3)
                if highs[i] == np.max(highs[back:j+1]):
                    phases.append({
                        "start_idx": i, "end_idx": j,
                        "direction": "DOWN",
                        "move_ticks": float(round(move_ticks_dn, 1)),
                        "dur_bars": j - i,
                        "start_ts": df.iloc[i]["ts_event"],
                        "start_price": float(closes[i]),
                    })
                    i = j
                    break
        else:
            i += 1
            continue
        # Ne pas reincrementer i ici (deja jumpe au j de break)

    return phases


def count_levels_at_bar(bar: pd.Series, levels_map: dict, threshold_pct: float = 0.05):
    """Compte les niveaux dans un rayon threshold_pct de prix au bar.

    Returns: list of (level_name, dist_pct_abs) actives.
    """
    actives = []
    for name, col in levels_map.items():
        v = bar.get(col)
        if v is None or pd.isna(v):
            continue
        try:
            dist_pct = float(v)
        except (ValueError, TypeError):
            continue
        if abs(dist_pct) <= threshold_pct:
            actives.append((name, abs(dist_pct)))
    actives.sort(key=lambda x: x[1])
    return actives


def analyze(symbol: str):
    print(f"=== Cluster Phase Starter Analyzer — {symbol} ===")
    df = load_v4(symbol, max_months=6)
    if df.empty:
        print("  Aucune data")
        return
    print(f"  Loaded {len(df)} bars, {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # 1. Detect phases
    phases = detect_phases(df, symbol, min_move_ticks=25, min_bars=3, max_bars=15)
    n_up = sum(1 for p in phases if p["direction"] == "UP")
    n_dn = sum(1 for p in phases if p["direction"] == "DOWN")
    print(f"  Phases detectees : {len(phases)} (UP={n_up} / DOWN={n_dn})")

    if not phases:
        return

    # 2. Pour chaque phase, compter niveaux au bar demarrage
    cluster_threshold = 3      # >= 3 niveaux dans rayon = cluster
    rayon_pct = 0.05           # ~5 ticks ES, ~12 ticks NQ
    phase_clusters = []
    combo_counter = Counter()

    for p in phases:
        bar = df.iloc[p["start_idx"]]
        levels_map = SUPPORT_LEVELS if p["direction"] == "UP" else RESISTANCE_LEVELS
        actives = count_levels_at_bar(bar, levels_map, threshold_pct=rayon_pct)
        is_cluster = len(actives) >= cluster_threshold
        phase_clusters.append({
            "phase": p,
            "n_levels": len(actives),
            "levels": [a[0] for a in actives],
            "is_cluster": is_cluster,
        })
        if is_cluster:
            # Track combinaisons (top niveaux par phase)
            top_combo = tuple(sorted(a[0] for a in actives[:5]))
            combo_counter[top_combo] += 1

    # 3. Stats globales
    n_phases = len(phases)
    n_with_cluster = sum(1 for pc in phase_clusters if pc["is_cluster"])
    pct_phases_cluster = n_with_cluster / n_phases * 100 if n_phases else 0
    print(f"\n--- STATS PHASES ---")
    print(f"  Total phases : {n_phases}")
    print(f"  Phases avec cluster (>={cluster_threshold} niveaux dans {rayon_pct}% rayon) : "
          f"{n_with_cluster} ({pct_phases_cluster:.0f}%)")

    # 4. Baseline : random bars combien ont >= cluster_threshold niveaux ?
    n_sample = min(n_phases * 5, len(df))  # 5x la taille phases
    rng = np.random.default_rng(42)
    random_idx = rng.choice(len(df), size=n_sample, replace=False)
    n_random_cluster_up = 0
    n_random_cluster_dn = 0
    for idx in random_idx:
        bar_r = df.iloc[idx]
        actives_up = count_levels_at_bar(bar_r, SUPPORT_LEVELS, threshold_pct=rayon_pct)
        actives_dn = count_levels_at_bar(bar_r, RESISTANCE_LEVELS, threshold_pct=rayon_pct)
        if len(actives_up) >= cluster_threshold:
            n_random_cluster_up += 1
        if len(actives_dn) >= cluster_threshold:
            n_random_cluster_dn += 1
    pct_random_cluster_up = n_random_cluster_up / n_sample * 100
    pct_random_cluster_dn = n_random_cluster_dn / n_sample * 100
    print(f"\n--- BASELINE RANDOM (n={n_sample}) ---")
    print(f"  Bars random avec cluster SUPPORT (>={cluster_threshold}) : "
          f"{n_random_cluster_up} ({pct_random_cluster_up:.0f}%)")
    print(f"  Bars random avec cluster RESISTANCE (>={cluster_threshold}) : "
          f"{n_random_cluster_dn} ({pct_random_cluster_dn:.0f}%)")

    # Effet edge = pct_phases_cluster - pct_random_cluster
    avg_random = (pct_random_cluster_up + pct_random_cluster_dn) / 2
    edge = pct_phases_cluster - avg_random
    print(f"\n  EDGE clusters au demarrage : {edge:+.0f}pp vs random "
          f"({pct_phases_cluster:.0f}% phases vs {avg_random:.0f}% random)")

    # 5. Top combinaisons de niveaux qui se reproduisent
    print(f"\n--- TOP 10 COMBINAISONS de niveaux au demarrage ---")
    for combo, n in combo_counter.most_common(10):
        print(f"  ({n}x) {' + '.join(combo)}")

    # 6. Distribution n_levels par phase
    n_level_dist = Counter(pc["n_levels"] for pc in phase_clusters)
    print(f"\n--- Distribution n_levels au demarrage phase ---")
    for k in sorted(n_level_dist):
        marker = " <- CLUSTER" if k >= cluster_threshold else ""
        print(f"  {k} niveaux : {n_level_dist[k]} phases{marker}")

    # 7. Phases UP vs DOWN separement
    up_clusters = [pc for pc in phase_clusters if pc["phase"]["direction"] == "UP"]
    dn_clusters = [pc for pc in phase_clusters if pc["phase"]["direction"] == "DOWN"]
    pct_up_cluster = sum(1 for pc in up_clusters if pc["is_cluster"]) / len(up_clusters) * 100 if up_clusters else 0
    pct_dn_cluster = sum(1 for pc in dn_clusters if pc["is_cluster"]) / len(dn_clusters) * 100 if dn_clusters else 0
    print(f"\n  UP phases avec cluster : {pct_up_cluster:.0f}% (n={len(up_clusters)})")
    print(f"  DOWN phases avec cluster : {pct_dn_cluster:.0f}% (n={len(dn_clusters)})")

    # Verdict simple
    print(f"\n=== VERDICT ===")
    if edge >= 20:
        print(f"  EDGE FORT : +{edge:.0f}pp = signal exploitable")
    elif edge >= 10:
        print(f"  EDGE MOYEN : +{edge:.0f}pp = potentiel, valider avec backtest trade")
    else:
        print(f"  EDGE FAIBLE : +{edge:.0f}pp = peu different du random")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES"], default="NQ")
    args = ap.parse_args()
    analyze(args.symbol)


if __name__ == "__main__":
    main()
