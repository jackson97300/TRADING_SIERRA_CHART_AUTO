"""phase_signature_audit.py — Audit pre-phase signatures (lookback 10-15 bars).

Jackson 09/05 : "j'ai dezoumer les graphs, on voit bien les phases. Regarder ce
qui se passe a chaque debut de phase, pas juste la barre mais qu'est-ce qui
s'est passe dans les 10-15 barres avant. UP et DOWN traites separement.
Intime conviction = tout est lie au BN. Bien determiner les phases c'est
primordial."

3 phases d'audit :
  A. Audit detection phases (duree + amplitude distribution)
  B. Audit fire rates features BN core (vivantes ?)
  C. Mining signatures pre-phase UP vs DOWN sur lookback 15 bars
     - Comparaison vs baseline (15 bars avant point random)
     - Identification features discriminantes (z-score vs random)

Ne fait QUE l'audit (pas backtest forward). Output = stats descriptives
+ ranking features par discriminance pre-UP / pre-DOWN.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}

# ─── Features BN core a auditer (Jackson focus) ───
BN_FEATURES = [
    # LONG bars (BN core impulsion)
    "long_up_bar",
    "long_dn_bar",
    "long_up_dn_pattern",
    "long_dn_up_pattern",
    # COLOR (Wyckoff phases)
    "bn_color_up_fwd1",
    "bn_color_dn_fwd1",
    "bn_color_up_2_fwd1",
    "bn_color_dn_2_fwd1",
    # DELTA DIVERGENCE
    "delta_div_buy",
    "delta_div_sell",
    # ABSORB
    "bn_absorb_bid_at_level",
    "bn_absorb_ask_at_level",
    "bn_absorb_bid_raw",
    "bn_absorb_ask_raw",
    # TRAPPED
    "bn_trapped_sellers_at_support",
    "bn_trapped_buyers_at_resistance",
    "bn_trapped_sellers_raw",
    "bn_trapped_buyers_raw",
    # STACK imbalances
    "bn_stack_bid",
    "bn_stack_ask",
    # RVOL absorb
    "rvol_absorb_buy",
    "rvol_absorb_sell",
]


def load_v4(symbol: str, max_months: int = 6) -> pd.DataFrame:
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def detect_phases(df: pd.DataFrame, sym: str,
                   min_move_ticks: int = 25, min_bars: int = 3, max_bars: int = 15,
                   pivot_lookback: int = 3):
    """Detection v3 : pivot strict-exclusif + move minimum.

    Args:
        min_move_ticks: amplitude minimum pour confirmer phase (25t = 6.25 pts)
        min_bars: duree minimum
        max_bars: duree maximum
        pivot_lookback: nombre de bars avant i pour confirmer extremum
            (3 = pivot leger, 5-10 = pivot zoomed-out comme l'oeil de Jackson)
    """
    tick = TICK_SIZE[sym]
    phases = []
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    i = 0
    while i < n - max_bars:
        end_max = min(i + max_bars, n - 1)
        local_low = lows[i]
        local_high = highs[i]
        found = False

        back = max(0, i - pivot_lookback)
        if back >= i:
            i += 1
            continue
        prev_lows = lows[back:i]
        prev_highs = highs[back:i]
        is_local_low_confirmed = lows[i] < np.min(prev_lows) if len(prev_lows) > 0 else False
        is_local_high_confirmed = highs[i] > np.max(prev_highs) if len(prev_highs) > 0 else False

        if not (is_local_low_confirmed or is_local_high_confirmed):
            i += 1
            continue

        for j in range(i + min_bars, end_max + 1):
            move_up = (highs[j] - local_low) / tick
            move_dn = (local_high - lows[j]) / tick

            if move_up >= min_move_ticks and is_local_low_confirmed:
                phases.append({
                    "start_idx": i, "end_idx": j, "direction": "UP",
                    "move_ticks": float(round(move_up, 1)),
                    "dur_bars": j - i, "start_price": float(closes[i]),
                })
                i = j
                found = True
                break
            if move_dn >= min_move_ticks and is_local_high_confirmed:
                phases.append({
                    "start_idx": i, "end_idx": j, "direction": "DOWN",
                    "move_ticks": float(round(move_dn, 1)),
                    "dur_bars": j - i, "start_price": float(closes[i]),
                })
                i = j
                found = True
                break
        if not found:
            i += 1
    return phases


def audit_phases(phases, sym):
    print(f"\n=== AUDIT A : DETECTION PHASES {sym} ===")
    n_up = sum(1 for p in phases if p["direction"] == "UP")
    n_dn = sum(1 for p in phases if p["direction"] == "DOWN")
    print(f"  Total phases : {len(phases)} (UP={n_up} / DOWN={n_dn})")

    for direction in ["UP", "DOWN"]:
        ph = [p for p in phases if p["direction"] == direction]
        if not ph:
            continue
        durs = [p["dur_bars"] for p in ph]
        amps = [p["move_ticks"] for p in ph]
        print(f"\n  {direction} (n={len(ph)}) :")
        print(f"    Duree : median={np.median(durs):.0f} bars, mean={np.mean(durs):.1f}, "
              f"p25={np.percentile(durs, 25):.0f}, p75={np.percentile(durs, 75):.0f}, p95={np.percentile(durs, 95):.0f}")
        print(f"    Amplitude : median={np.median(amps):.1f}t, mean={np.mean(amps):.1f}, "
              f"p25={np.percentile(amps, 25):.1f}, p75={np.percentile(amps, 75):.1f}, p95={np.percentile(amps, 95):.1f}")
        # Bucketing duree
        buckets = {"3-5": 0, "6-8": 0, "9-12": 0, "13-15": 0}
        for d in durs:
            if d <= 5: buckets["3-5"] += 1
            elif d <= 8: buckets["6-8"] += 1
            elif d <= 12: buckets["9-12"] += 1
            else: buckets["13-15"] += 1
        print(f"    Buckets duree : ", ", ".join(f"{k}={v} ({v*100/len(ph):.0f}%)" for k, v in buckets.items()))


def audit_fire_rates(df, sym):
    print(f"\n=== AUDIT B : FIRE RATES BN/COLOR/LONG {sym} ===")
    print(f"  Total bars : {len(df)}")
    print(f"  {'Feature':<35s} {'fire %':>8s} {'n':>8s}  {'mean if >0':>10s}")
    for f in BN_FEATURES:
        if f not in df.columns:
            print(f"  {f:<35s}  ABSENT")
            continue
        vals = df[f].fillna(0)
        # binaire : count >0
        n_fired = int((vals > 0).sum())
        rate = n_fired / len(df) * 100
        mean_when_fired = float(vals[vals > 0].mean()) if n_fired > 0 else 0.0
        flag = ""
        if rate < 0.1:
            flag = "  <-- TRES BAS (suspect mort)"
        elif rate > 50:
            flag = "  <-- TRES HAUT"
        print(f"  {f:<35s} {rate:>7.2f}% {n_fired:>8d}  {mean_when_fired:>10.2f}{flag}")


def extract_pre_phase_signature(df, phase, lookback=15):
    """Extrait counts BN dans fenetre [start_idx-lookback, start_idx-1]."""
    start = max(0, phase["start_idx"] - lookback)
    end = phase["start_idx"]  # exclusif
    if start >= end:
        return None
    window = df.iloc[start:end]
    sig = {}
    for f in BN_FEATURES:
        if f not in window.columns:
            continue
        v = window[f].fillna(0)
        sig[f"n_{f}"] = int((v > 0).sum())
        sig[f"max_{f}"] = float(v.max())
    return sig


def extract_random_signatures(df, n_random=500, lookback=15, seed=42):
    """Baseline : tire n_random points et extrait signatures sur les 15 bars avant."""
    rng = np.random.default_rng(seed)
    n = len(df)
    if n < lookback + 100:
        return []
    sigs = []
    idxs = rng.choice(np.arange(lookback + 50, n - 50), size=min(n_random, n - lookback - 100), replace=False)
    for idx in idxs:
        window = df.iloc[idx - lookback:idx]
        sig = {}
        for f in BN_FEATURES:
            if f not in window.columns:
                continue
            v = window[f].fillna(0)
            sig[f"n_{f}"] = int((v > 0).sum())
            sig[f"max_{f}"] = float(v.max())
        sigs.append(sig)
    return sigs


def report_signatures(sigs_up, sigs_dn, sigs_rand, sym):
    print(f"\n=== AUDIT C : SIGNATURES PRE-PHASE {sym} (lookback 15 bars) ===")
    if not sigs_up or not sigs_dn:
        print(f"  Pas assez de phases (UP={len(sigs_up)}, DOWN={len(sigs_dn)})")
        return

    df_up = pd.DataFrame(sigs_up)
    df_dn = pd.DataFrame(sigs_dn)
    df_rand = pd.DataFrame(sigs_rand)

    # Calcul means + std baseline
    cols = sorted(set(df_up.columns) & set(df_dn.columns) & set(df_rand.columns))
    print(f"\n  Signatures (mean count sur 15 bars lookback)")
    print(f"  {'Feature':<35s}  {'PRE-UP':>10s}  {'PRE-DOWN':>10s}  {'RANDOM':>10s}  "
          f"{'Z(UP)':>8s}  {'Z(DN)':>8s}  {'DISCRIM':>8s}")

    rows = []
    for c in cols:
        if not c.startswith("n_"):
            continue
        m_up = df_up[c].mean()
        m_dn = df_dn[c].mean()
        m_rand = df_rand[c].mean()
        s_rand = df_rand[c].std() if df_rand[c].std() > 0 else 1.0
        z_up = (m_up - m_rand) / s_rand
        z_dn = (m_dn - m_rand) / s_rand
        # Discrimination = abs(z_up - z_dn) (separe UP vs DOWN)
        discrim = abs(z_up - z_dn)
        rows.append({
            "feature": c,
            "m_up": m_up, "m_dn": m_dn, "m_rand": m_rand,
            "z_up": z_up, "z_dn": z_dn, "discrim": discrim,
        })

    # Trie par discrimination
    rows.sort(key=lambda r: -r["discrim"])
    for r in rows[:25]:
        flag = ""
        if r["discrim"] >= 1.0:
            flag = "  *** TOP DISCRIM"
        elif r["discrim"] >= 0.5:
            flag = "  ** discrim moyen"
        print(f"  {r['feature']:<35s}  {r['m_up']:>10.2f}  {r['m_dn']:>10.2f}  "
              f"{r['m_rand']:>10.2f}  {r['z_up']:>+8.2f}  {r['z_dn']:>+8.2f}  "
              f"{r['discrim']:>8.2f}{flag}")


def find_dominant_signatures(sigs, direction, top_k=10):
    """Cluster simple : compte les co-occurrences de paires/triplets de features
    (n_X >= 1 binarise) dans les signatures pre-phase."""
    if not sigs:
        return
    df = pd.DataFrame(sigs)
    # Binarise : feature presente >=1 fois dans le lookback ?
    bin_cols = [c for c in df.columns if c.startswith("n_") and "raw" not in c]
    df_bin = (df[bin_cols] >= 1).astype(int)
    # Renommer pour lisibilite
    df_bin.columns = [c.replace("n_bn_", "").replace("n_", "") for c in df_bin.columns]
    # Singles
    print(f"\n  TOP SINGLE features presentes pre-{direction} (lookback 15 bars) :")
    presence = df_bin.mean().sort_values(ascending=False)
    for f, p in presence.head(15).items():
        print(f"    {f:<35s} {p*100:>5.1f}% des phases")

    # Pairs (binarise simultaneite)
    from itertools import combinations
    pair_counts = {}
    for c1, c2 in combinations(df_bin.columns, 2):
        co = ((df_bin[c1] == 1) & (df_bin[c2] == 1)).sum()
        if co >= 5:
            pair_counts[(c1, c2)] = co
    pair_sorted = sorted(pair_counts.items(), key=lambda x: -x[1])[:top_k]
    if pair_sorted:
        print(f"\n  TOP PAIRS co-presentes pre-{direction} (lookback 15 bars) :")
        for (c1, c2), n in pair_sorted:
            pct = n / len(df_bin) * 100
            print(f"    {c1:<25s} + {c2:<25s} : {n} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--min-move", type=int, default=25, help="Min ticks pour confirmer phase")
    parser.add_argument("--min-bars", type=int, default=3, help="Min bars duration phase")
    parser.add_argument("--max-bars", type=int, default=15, help="Max bars duration phase")
    parser.add_argument("--pivot-lookback", type=int, default=3, help="Bars avant i pour confirmer pivot")
    parser.add_argument("--lookback", type=int, default=15, help="Lookback pre-phase en bars")
    args = parser.parse_args()

    sym = args.symbol
    print(f"\n{'='*70}")
    print(f"=== PHASE SIGNATURE AUDIT — {sym} ({args.months} mois) ===")
    print(f"=== Detection : min_move={args.min_move}t, min_bars={args.min_bars}-{args.max_bars}, pivot={args.pivot_lookback} ===")
    print(f"=== Lookback pre-phase : {args.lookback} bars ===")
    print(f"{'='*70}")

    df = load_v4(sym, args.months)
    if df.empty:
        print(f"  Pas de data pour {sym}")
        return
    print(f"  Loaded {len(df)} bars : {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # AUDIT A : phases
    phases = detect_phases(df, sym, min_move_ticks=args.min_move,
                            min_bars=args.min_bars, max_bars=args.max_bars,
                            pivot_lookback=args.pivot_lookback)
    audit_phases(phases, sym)

    # AUDIT B : fire rates
    audit_fire_rates(df, sym)

    # AUDIT C : signatures
    sigs_up, sigs_dn = [], []
    for p in phases:
        sig = extract_pre_phase_signature(df, p, lookback=args.lookback)
        if sig is None:
            continue
        if p["direction"] == "UP":
            sigs_up.append(sig)
        else:
            sigs_dn.append(sig)
    sigs_rand = extract_random_signatures(df, n_random=500, lookback=args.lookback)

    report_signatures(sigs_up, sigs_dn, sigs_rand, sym)
    find_dominant_signatures(sigs_up, "UP")
    find_dominant_signatures(sigs_dn, "DOWN")


if __name__ == "__main__":
    main()
