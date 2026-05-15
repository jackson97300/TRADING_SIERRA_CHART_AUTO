"""
rules_discovery.py — Decouverte de regles de trading sur donnees DMP
=====================================================================

Analyse les niveaux previous day, open type, clusters, BN absorptions
pour trouver des edges exploitables.

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from dmp_reader import DmpReader

DATA_DIR = Path(__file__).parent.parent / "DATA"
TICK_SIZE = 0.25
TP_TICKS = 20
SL_TICKS = 20


def load_data(symbol, dates):
    """Charge et concatene les JSONL pour un symbole."""
    reader = DmpReader(str(DATA_DIR))
    frames = []
    for d in dates:
        try:
            df = reader.load_file(str(DATA_DIR / symbol / f"{d}_{symbol}.jsonl"))
            if df is not None and len(df) > 0:
                df["date"] = d
                frames.append(df)
        except Exception as e:
            print(f"  Skip {d}_{symbol}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def filter_us_session(df):
    """Filtre les barres session US."""
    if "session" in df.columns:
        mask = df["session"].astype(str).str.lower().str.contains("us|rth")
        if mask.sum() > 0:
            return df[mask].reset_index(drop=True)
    # Fallback : filtrer par session_id ou heure
    if "session_id" in df.columns:
        # session_id 2 = US typiquement
        mask = df["session_id"].isin([2, 3])
        if mask.sum() > 0:
            return df[mask].reset_index(drop=True)
    return df


def label_bars(df, tp_ticks=TP_TICKS, sl_ticks=SL_TICKS, horizon=30):
    """
    Pour chaque barre, simule BUY et SELL.
    Retourne arrays buy_win, sell_win (bool).
    """
    prices = df["price"].values
    n = len(prices)
    tp_pts = tp_ticks * TICK_SIZE
    sl_pts = sl_ticks * TICK_SIZE

    buy_result = np.zeros(n, dtype=int)   # 1=win, -1=loss, 0=flat
    sell_result = np.zeros(n, dtype=int)

    for i in range(n - 1):
        entry = prices[i]
        # BUY simulation
        for j in range(i + 1, min(i + horizon + 1, n)):
            if prices[j] >= entry + tp_pts:
                buy_result[i] = 1
                break
            if prices[j] <= entry - sl_pts:
                buy_result[i] = -1
                break

        # SELL simulation
        for j in range(i + 1, min(i + horizon + 1, n)):
            if prices[j] <= entry - tp_pts:
                sell_result[i] = 1
                break
            if prices[j] >= entry + sl_pts:
                sell_result[i] = -1
                break

    df["buy_win"] = (buy_result == 1)
    df["buy_loss"] = (buy_result == -1)
    df["sell_win"] = (sell_result == 1)
    df["sell_loss"] = (sell_result == -1)
    return df


def baseline_stats(df):
    """Win rate de base sans filtre."""
    buy_trades = df["buy_win"] | df["buy_loss"]
    sell_trades = df["sell_win"] | df["sell_loss"]

    buy_wr = df.loc[buy_trades, "buy_win"].mean() if buy_trades.sum() > 0 else 0
    sell_wr = df.loc[sell_trades, "sell_win"].mean() if sell_trades.sum() > 0 else 0

    return {
        "buy_wr": buy_wr,
        "sell_wr": sell_wr,
        "buy_trades": buy_trades.sum(),
        "sell_trades": sell_trades.sum(),
    }


def test_level(df, col, threshold, direction, baseline_wr):
    """
    Teste si etre proche d'un niveau ameliore le WR.
    direction: 'buy' ou 'sell'
    """
    if col not in df.columns:
        return None

    mask = df[col].abs() < threshold
    n_signals = mask.sum()
    if n_signals < 10:
        return None

    win_col = f"{direction}_win"
    loss_col = f"{direction}_loss"
    trades_mask = mask & (df[win_col] | df[loss_col])
    n_trades = trades_mask.sum()
    if n_trades < 5:
        return None

    wr = df.loc[trades_mask, win_col].mean()
    wins = df.loc[trades_mask, win_col].sum()

    # Test binomial
    p_value = stats.binomtest(int(wins), int(n_trades), baseline_wr,
                                alternative="greater").pvalue

    pf = (wins * TP_TICKS) / max((n_trades - wins) * SL_TICKS, 1)

    return {
        "col": col,
        "threshold": threshold,
        "direction": direction,
        "n_signals": int(n_signals),
        "n_trades": int(n_trades),
        "wins": int(wins),
        "wr": round(wr, 3),
        "baseline_wr": round(baseline_wr, 3),
        "edge": round(wr - baseline_wr, 3),
        "pf": round(pf, 2),
        "p_value": round(p_value, 4),
    }


def test_feature_high(df, col, quantile, direction, baseline_wr):
    """Teste si une feature au-dessus d'un quantile ameliore le WR."""
    if col not in df.columns:
        return None

    thresh = df[col].quantile(quantile)
    mask = df[col] > thresh
    n_signals = mask.sum()
    if n_signals < 10:
        return None

    win_col = f"{direction}_win"
    loss_col = f"{direction}_loss"
    trades_mask = mask & (df[win_col] | df[loss_col])
    n_trades = trades_mask.sum()
    if n_trades < 5:
        return None

    wr = df.loc[trades_mask, win_col].mean()
    wins = df.loc[trades_mask, win_col].sum()

    p_value = stats.binomtest(int(wins), int(n_trades), baseline_wr,
                                alternative="greater").pvalue

    pf = (wins * TP_TICKS) / max((n_trades - wins) * SL_TICKS, 1)

    return {
        "col": col,
        "condition": f"> q{int(quantile*100)}% ({thresh:.2f})",
        "direction": direction,
        "n_trades": int(n_trades),
        "wins": int(wins),
        "wr": round(wr, 3),
        "baseline_wr": round(baseline_wr, 3),
        "edge": round(wr - baseline_wr, 3),
        "pf": round(pf, 2),
        "p_value": round(p_value, 4),
    }


def analyze_previous_levels(df, base):
    """Analyse les niveaux previous day."""
    print("\n  === NIVEAUX PREVIOUS DAY ===")
    prev_cols = [c for c in df.columns if "prev" in c.lower() and "dist" in c.lower()]
    print(f"  Colonnes previous trouvees: {len(prev_cols)}")
    print(f"  {prev_cols[:10]}")

    results = []
    for col in prev_cols:
        for thresh in [3, 5]:
            # Proche de prev_vah → SHORT
            if "vah" in col.lower():
                r = test_level(df, col, thresh, "sell", base["sell_wr"])
                if r: results.append(r)
            # Proche de prev_val → LONG
            elif "val" in col.lower():
                r = test_level(df, col, thresh, "buy", base["buy_wr"])
                if r: results.append(r)
            # Proche de prev_vpoc → les deux
            elif "vpoc" in col.lower() or "poc" in col.lower():
                r = test_level(df, col, thresh, "buy", base["buy_wr"])
                if r: results.append(r)
                r = test_level(df, col, thresh, "sell", base["sell_wr"])
                if r: results.append(r)
            else:
                # Autre niveau previous — tester les deux
                r = test_level(df, col, thresh, "buy", base["buy_wr"])
                if r: results.append(r)
                r = test_level(df, col, thresh, "sell", base["sell_wr"])
                if r: results.append(r)

    # Trier par edge
    results.sort(key=lambda x: x["edge"], reverse=True)
    for r in results[:10]:
        verdict = "VALIDE" if r["p_value"] < 0.05 else "FRAGILE" if r["p_value"] < 0.15 else "BRUIT"
        print(f"  {r['direction'].upper():4s} | {r['col']:<25s} < {r['threshold']}t | "
              f"WR={r['wr']:.1%} (base={r['baseline_wr']:.1%}) edge={r['edge']:+.1%} | "
              f"n={r['n_trades']:3d} PF={r['pf']:.2f} p={r['p_value']:.3f} [{verdict}]")

    return results


def analyze_open_type(df, base):
    """Analyse par Open Type."""
    print("\n  === OPEN TYPE ===")
    if "open_type" not in df.columns:
        print("  Colonne open_type non trouvee")
        return []

    results = []
    for ot in sorted(df["open_type"].unique()):
        mask = df["open_type"] == ot
        n = mask.sum()
        if n < 10:
            continue

        for direction in ["buy", "sell"]:
            win_col = f"{direction}_win"
            loss_col = f"{direction}_loss"
            trades_mask = mask & (df[win_col] | df[loss_col])
            n_trades = trades_mask.sum()
            if n_trades < 5:
                continue
            wr = df.loc[trades_mask, win_col].mean()
            bl = base[f"{direction}_wr"]
            edge = wr - bl

            results.append({
                "open_type": ot, "direction": direction,
                "n_bars": int(n), "n_trades": int(n_trades),
                "wr": round(wr, 3), "edge": round(edge, 3),
            })

    results.sort(key=lambda x: x["edge"], reverse=True)
    for r in results[:10]:
        print(f"  OT={r['open_type']:2d} | {r['direction'].upper():4s} | "
              f"WR={r['wr']:.1%} edge={r['edge']:+.1%} | "
              f"n_bars={r['n_bars']:4d} n_trades={r['n_trades']:3d}")

    return results


def analyze_clusters(df, base):
    """Analyse les clusters de niveaux."""
    print("\n  === CLUSTERS DE NIVEAUX ===")
    dist_cols = [c for c in df.columns if c.startswith("dist_") and df[c].dtype in ['float64', 'float32', 'int64']]
    print(f"  Colonnes dist_* : {len(dist_cols)}")

    # Compter combien de niveaux sont proches (< 5 ticks) pour chaque barre
    close_count = pd.DataFrame()
    for col in dist_cols:
        close_count[col] = df[col].abs() < (5 * TICK_SIZE)

    df["n_close_levels"] = close_count.sum(axis=1)

    print(f"  Distribution clusters:")
    for n_lvl in [3, 5, 7, 10]:
        mask = df["n_close_levels"] >= n_lvl
        print(f"    {n_lvl}+ niveaux: {mask.sum()} barres ({mask.mean():.1%})")

    # Test : cluster >= 5 niveaux proches
    results = []
    for min_levels in [3, 5, 7]:
        cluster_mask = df["n_close_levels"] >= min_levels
        if cluster_mask.sum() < 10:
            continue

        # FIX BUG D 15/05/2026 : convention NEW (level - close) compliant DMP C++
        # dist_vwap_d > 0 = VWAP au-dessus du prix = prix EN-DESSOUS VWAP (zone basse)
        # dist_vwap_d < 0 = VWAP sous le prix = prix AU-DESSUS VWAP (zone haute)
        if "dist_vwap_d" in df.columns:
            high_mask = cluster_mask & (df["dist_vwap_d"] < 0)  # price above vwap
            low_mask = cluster_mask & (df["dist_vwap_d"] > 0)   # price below vwap
        else:
            high_mask = cluster_mask
            low_mask = cluster_mask

        for mask, direction, label in [
            (low_mask, "buy", f"cluster>={min_levels} SOUS vwap"),
            (high_mask, "sell", f"cluster>={min_levels} AU-DESSUS vwap"),
        ]:
            win_col = f"{direction}_win"
            loss_col = f"{direction}_loss"
            trades_mask = mask & (df[win_col] | df[loss_col])
            n_trades = trades_mask.sum()
            if n_trades < 5:
                continue
            wr = df.loc[trades_mask, win_col].mean()
            bl = base[f"{direction}_wr"]
            wins = df.loc[trades_mask, win_col].sum()
            pf = (wins * TP_TICKS) / max((n_trades - wins) * SL_TICKS, 1)

            results.append({
                "rule": label, "direction": direction,
                "n_trades": int(n_trades), "wr": round(wr, 3),
                "edge": round(wr - bl, 3), "pf": round(pf, 2),
            })
            print(f"  {label:35s} | {direction.upper():4s} WR={wr:.1%} (base={bl:.1%}) "
                  f"edge={wr-bl:+.1%} n={n_trades} PF={pf:.2f}")

    return results


def analyze_bn_absorptions(df, base):
    """Analyse bataille navale et absorptions."""
    print("\n  === BATAILLE NAVALE & ABSORPTIONS ===")
    bn_cols = [c for c in df.columns if "bn_" in c.lower() or "absorb" in c.lower()
               or "pressure" in c.lower()]
    print(f"  Colonnes BN trouvees: {len(bn_cols)}")

    results = []
    for col in bn_cols:
        if df[col].dtype not in ['float64', 'float32', 'int64']:
            continue
        if df[col].std() < 0.001:
            continue  # Colonne morte

        for direction, quantile in [("buy", 0.75), ("sell", 0.75)]:
            r = test_feature_high(df, col, quantile, direction, base[f"{direction}_wr"])
            if r and r["edge"] > 0.02:
                results.append(r)

    results.sort(key=lambda x: x["edge"], reverse=True)
    for r in results[:10]:
        verdict = "VALIDE" if r["p_value"] < 0.05 else "FRAGILE" if r["p_value"] < 0.15 else "BRUIT"
        print(f"  {r['direction'].upper():4s} | {r['col']:<25s} {r['condition']:>20s} | "
              f"WR={r['wr']:.1%} edge={r['edge']:+.1%} | "
              f"n={r['n_trades']:3d} PF={r['pf']:.2f} p={r['p_value']:.3f} [{verdict}]")

    return results


def analyze_va_plus_previous(df, base):
    """Combine VA position + niveaux previous."""
    print("\n  === VA POSITION + PREVIOUS LEVELS ===")
    results = []

    if "va_position_pct" not in df.columns:
        # Chercher alternative
        va_col = None
        for c in df.columns:
            if "va_pos" in c.lower():
                va_col = c
                break
        if va_col is None:
            print("  Pas de colonne VA position")
            return []
    else:
        va_col = "va_position_pct"

    prev_vah_cols = [c for c in df.columns if "prev" in c and "vah" in c.lower()]
    prev_val_cols = [c for c in df.columns if "prev" in c and "val" in c.lower()]

    # SHORT : VA haute + proche prev_vah
    for pvah in prev_vah_cols:
        mask = (df[va_col] > 0.8) & (df[pvah].abs() < 5 * TICK_SIZE)
        win_col, loss_col = "sell_win", "sell_loss"
        trades_mask = mask & (df[win_col] | df[loss_col])
        n = trades_mask.sum()
        if n >= 5:
            wr = df.loc[trades_mask, win_col].mean()
            wins = df.loc[trades_mask, win_col].sum()
            pf = (wins * TP_TICKS) / max((n - wins) * SL_TICKS, 1)
            edge = wr - base["sell_wr"]
            print(f"  SHORT: {va_col}>0.8 + |{pvah}|<5t | WR={wr:.1%} edge={edge:+.1%} n={n} PF={pf:.2f}")
            results.append({"rule": f"{va_col}>0.8+{pvah}<5t", "direction": "sell",
                            "n_trades": int(n), "wr": round(wr, 3), "edge": round(edge, 3), "pf": round(pf, 2)})

    # LONG : VA basse + proche prev_val
    for pval in prev_val_cols:
        mask = (df[va_col] < 0.2) & (df[pval].abs() < 5 * TICK_SIZE)
        win_col, loss_col = "buy_win", "buy_loss"
        trades_mask = mask & (df[win_col] | df[loss_col])
        n = trades_mask.sum()
        if n >= 5:
            wr = df.loc[trades_mask, win_col].mean()
            wins = df.loc[trades_mask, win_col].sum()
            pf = (wins * TP_TICKS) / max((n - wins) * SL_TICKS, 1)
            edge = wr - base["buy_wr"]
            print(f"  LONG:  {va_col}<0.2 + |{pval}|<5t | WR={wr:.1%} edge={edge:+.1%} n={n} PF={pf:.2f}")
            results.append({"rule": f"{va_col}<0.2+{pval}<5t", "direction": "buy",
                            "n_trades": int(n), "wr": round(wr, 3), "edge": round(edge, 3), "pf": round(pf, 2)})

    return results


def main():
    dates = ["20260330", "20260331", "20260401"]

    for symbol in ["ES", "NQ"]:
        print(f"\n{'='*60}")
        print(f"  ANALYSE REGLES — {symbol}")
        print(f"{'='*60}")

        df = load_data(symbol, dates)
        if len(df) == 0:
            print(f"  Pas de donnees pour {symbol}")
            continue

        print(f"  Barres totales: {len(df)}")

        # Filtrer US
        df = filter_us_session(df)
        print(f"  Barres US: {len(df)}")

        if len(df) < 50:
            print(f"  Pas assez de barres US, skip filtre session")
            df = load_data(symbol, dates)

        # Labelliser
        print(f"  Labellisation (TP={TP_TICKS}t SL={SL_TICKS}t)...")
        df = label_bars(df)

        # Baseline
        base = baseline_stats(df)
        print(f"\n  BASELINE (sans filtre):")
        print(f"    BUY:  WR={base['buy_wr']:.1%} ({base['buy_trades']} trades)")
        print(f"    SELL: WR={base['sell_wr']:.1%} ({base['sell_trades']} trades)")

        # Analyses
        analyze_previous_levels(df, base)
        analyze_open_type(df, base)
        analyze_clusters(df, base)
        analyze_bn_absorptions(df, base)
        analyze_va_plus_previous(df, base)


if __name__ == "__main__":
    main()
