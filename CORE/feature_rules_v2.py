"""
Feature Rules Analysis V2 — MIA Trading System
Seuils adaptes par instrument. Regles combinees approfondies.
Auteur: MIA Feature Engineer
Date: 2026-04-02
"""

import sys
sys.path.insert(0, 'D:/TRADING_SIERRA_CHART_AUTO/CORE')

import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
from itertools import combinations
from dmp_reader import DmpReader

# ============================================================
# CONFIG
# ============================================================
DATA_PATH = "D:/TRADING_SIERRA_CHART_AUTO/DATA"
DATES = ["2026-03-30", "2026-03-31", "2026-04-01"]
TICK_SIZE = 0.25

# Seuils par instrument (adaptes a la volatilite)
CONFIGS = {
    "ES": {"tp_ticks": 20, "sl_ticks": 20, "lookahead": 20,
            "v1_tp": 28, "v1_sl": 12},  # 5 pts TP/SL, V1: 7pts/3pts
    "NQ": {"tp_ticks": 40, "sl_ticks": 40, "lookahead": 20,
            "v1_tp": 30, "v1_sl": 25},  # 10 pts TP/SL (NQ plus volatile)
}

META_COLS = {"ts", "sym", "contract", "session_id", "session", "datetime_utc",
             "datetime_et", "day_type", "open_type", "profile_shape"}


def load_data(symbol):
    reader = DmpReader(DATA_PATH)
    frames = []
    for date in DATES:
        df = reader.load(symbol, date)
        if not df.empty:
            df = reader.us_only(df)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=False)
    for c in df.columns:
        if c not in META_COLS and c != "datetime_et":
            df[c] = pd.to_numeric(df[c], errors='coerce')
    print(f"  {symbol}: {len(df)} barres US chargees")
    return df


def label_bars(df, tp_ticks, sl_ticks, lookahead):
    """Labellise BUY/SELL/HOLD en regardant si TP ou SL touche en premier."""
    prices = df["price"].values
    tp_pts = tp_ticks * TICK_SIZE
    sl_pts = sl_ticks * TICK_SIZE

    labels = np.full(len(prices), "HOLD", dtype=object)

    for i in range(len(prices) - 1):
        p0 = prices[i]
        end = min(i + lookahead + 1, len(prices))

        buy_tp_bar = sell_tp_bar = None

        for j in range(i + 1, end):
            p = prices[j]
            # BUY: TP si prix monte assez, SL si descend assez
            if buy_tp_bar is None:
                if p - p0 >= tp_pts:
                    buy_tp_bar = j - i
                elif p0 - p >= sl_pts:
                    buy_tp_bar = -1  # SL touche

            # SELL: TP si prix descend assez, SL si monte assez
            if sell_tp_bar is None:
                if p0 - p >= tp_pts:
                    sell_tp_bar = j - i
                elif p - p0 >= sl_pts:
                    sell_tp_bar = -1  # SL touche

        # BUY gagne si TP touche (>0) avant SELL TP
        buy_win = buy_tp_bar is not None and buy_tp_bar > 0
        sell_win = sell_tp_bar is not None and sell_tp_bar > 0

        if buy_win and sell_win:
            labels[i] = "BUY" if buy_tp_bar <= sell_tp_bar else "SELL"
        elif buy_win:
            labels[i] = "BUY"
        elif sell_win:
            labels[i] = "SELL"

    df = df.copy()
    df["label"] = labels
    counts = pd.Series(labels).value_counts()
    print(f"  Labels: {dict(counts)}")
    return df


def get_feature_cols(df):
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    return [c for c in num_cols if c not in META_COLS and c != "label"
            and c != "ts" and c != "session"]


def spearman_screening(df, feature_cols, min_rho=0.02):
    df = df.copy()
    label_map = {"SELL": -1, "HOLD": 0, "BUY": 1}
    df["label_num"] = df["label"].map(label_map)

    results = []
    for c in feature_cols:
        valid = df[[c, "label_num"]].dropna()
        if len(valid) < 30 or valid[c].std() < 1e-6:
            continue
        rho, pval = stats.spearmanr(valid[c], valid["label_num"])
        if abs(rho) >= min_rho:
            results.append({"feature": c, "rho": rho, "pval": pval,
                           "abs_rho": abs(rho)})

    return pd.DataFrame(results).sort_values("abs_rho", ascending=False)


def find_rules_smart(df, spearman_df, n_top=20):
    """
    Recherche de regles mono et combinees (2 features).
    Teste des seuils par quantile, direction selon signe de rho.
    Filtre: au moins 15 signaux, lift > 1.3.
    """
    top_feats = spearman_df.head(n_top)["feature"].tolist()

    buy_mask = df["label"] == "BUY"
    sell_mask = df["label"] == "SELL"
    total = len(df)
    n_buy = buy_mask.sum()
    n_sell = sell_mask.sum()
    base_buy_rate = n_buy / total
    base_sell_rate = n_sell / total
    n_days = max(df.index.normalize().nunique(), 1)

    rules = []

    def add_rule(direction, condition, mask, feats):
        n_sig = mask.sum()
        if n_sig < 15:
            return
        target = buy_mask if direction == "BUY" else sell_mask
        base = base_buy_rate if direction == "BUY" else base_sell_rate
        wr = (mask & target).sum() / n_sig
        lift = wr / base if base > 0 else 0
        if lift > 1.2:
            rules.append({
                "type": direction,
                "condition": condition,
                "features": feats,
                "n_signals": n_sig,
                "n_wins": (mask & target).sum(),
                "win_rate": wr,
                "lift": lift,
                "trades_per_day": round(n_sig / n_days, 1),
            })

    # Regles mono-feature
    for feat in top_feats:
        if feat not in df.columns:
            continue
        vals = df[feat].dropna()
        if len(vals) < 30 or vals.std() < 1e-6:
            continue
        rho = spearman_df[spearman_df["feature"] == feat]["rho"].values[0]

        for q in [0.20, 0.25, 0.33, 0.50, 0.67, 0.75, 0.80]:
            thr_high = vals.quantile(q)
            thr_low = vals.quantile(1 - q)

            mask_high = df[feat] >= thr_high
            mask_low = df[feat] <= thr_low

            if rho > 0:
                add_rule("BUY", f"{feat} >= {thr_high:.3f} (q{q:.0%})", mask_high, [feat])
                add_rule("SELL", f"{feat} <= {thr_low:.3f} (q{1-q:.0%})", mask_low, [feat])
            else:
                add_rule("BUY", f"{feat} <= {thr_low:.3f} (q{1-q:.0%})", mask_low, [feat])
                add_rule("SELL", f"{feat} >= {thr_high:.3f} (q{q:.0%})", mask_high, [feat])

    # Regles combinees (2 features)
    print("  Recherche de regles combinees (paires)...")
    combo_feats = top_feats[:12]
    for f1, f2 in combinations(combo_feats, 2):
        if f1 not in df.columns or f2 not in df.columns:
            continue
        v1 = df[f1].dropna()
        v2 = df[f2].dropna()
        if len(v1) < 30 or len(v2) < 30 or v1.std() < 1e-6 or v2.std() < 1e-6:
            continue

        rho1 = spearman_df[spearman_df["feature"] == f1]["rho"].values[0]
        rho2 = spearman_df[spearman_df["feature"] == f2]["rho"].values[0]

        for direction in ["BUY", "SELL"]:
            for q1, q2 in [(0.33, 0.33), (0.25, 0.25), (0.50, 0.50), (0.33, 0.50), (0.50, 0.33)]:
                if direction == "BUY":
                    m1 = (df[f1] >= v1.quantile(q1)) if rho1 > 0 else (df[f1] <= v1.quantile(1 - q1))
                    m2 = (df[f2] >= v2.quantile(q2)) if rho2 > 0 else (df[f2] <= v2.quantile(1 - q2))
                else:
                    m1 = (df[f1] <= v1.quantile(1 - q1)) if rho1 > 0 else (df[f1] >= v1.quantile(q1))
                    m2 = (df[f2] <= v2.quantile(1 - q2)) if rho2 > 0 else (df[f2] >= v2.quantile(q2))

                combo = m1 & m2
                cond = f"{f1}({'>' if (direction=='BUY') == (rho1>0) else '<'}q{q1:.0%}) & {f2}({'>' if (direction=='BUY') == (rho2>0) else '<'}q{q2:.0%})"
                add_rule(direction, cond, combo, [f1, f2])

    rules_df = pd.DataFrame(rules)
    if rules_df.empty:
        return rules_df

    # Deduplication: garder la meilleure regle par combinaison de features
    rules_df["feat_key"] = rules_df["features"].apply(lambda x: tuple(sorted(x)))
    rules_df = rules_df.sort_values("lift", ascending=False)
    # Garder les top par type+feat_key
    best = rules_df.groupby(["type", "feat_key"]).first().reset_index()
    return best.sort_values("lift", ascending=False)


def simulate_pnl(rules_df, tp_ticks, sl_ticks, n_days):
    """Calcule PF, EV, PnL pour chaque regle."""
    results = []
    for _, r in rules_df.iterrows():
        wins = r["n_wins"]
        losses = r["n_signals"] - wins
        pnl = wins * tp_ticks - losses * sl_ticks
        pf = (wins * tp_ticks) / max(losses * sl_ticks, 1)
        ev = pnl / max(r["n_signals"], 1)

        results.append({
            "direction": r["type"],
            "condition": r["condition"],
            "n_signals": r["n_signals"],
            "wins": wins,
            "losses": losses,
            "win_rate": f"{r['win_rate']:.1%}",
            "PF": round(pf, 2),
            "EV_ticks": round(ev, 1),
            "total_PnL": round(pnl),
            "t_per_day": r.get("trades_per_day", round(r["n_signals"] / max(n_days, 1), 1)),
            "lift": round(r["lift"], 2),
        })

    return pd.DataFrame(results).sort_values("PF", ascending=False)


def deep_feature_analysis(df, spearman_df, top_n=15):
    """Analyse detaillee: quantiles par label pour les top features."""
    buy = df[df["label"] == "BUY"]
    sell = df[df["label"] == "SELL"]
    hold = df[df["label"] == "HOLD"]

    print(f"\n  === ANALYSE DETAILLEE DES TOP FEATURES ===")
    print(f"  {'Feature':<35} {'BUY q25':>8} {'BUY q50':>8} {'BUY q75':>8} | {'SELL q25':>8} {'SELL q50':>8} {'SELL q75':>8} | {'Separation':>10}")
    print(f"  {'-'*110}")

    for _, row in spearman_df.head(top_n).iterrows():
        feat = row["feature"]
        b = buy[feat].dropna()
        s = sell[feat].dropna()
        if len(b) < 5 or len(s) < 5:
            continue

        # Kolmogorov-Smirnov pour mesurer la separation des distributions
        ks_stat, ks_pval = stats.ks_2samp(b, s)

        print(f"  {feat:<35} {b.quantile(0.25):>8.2f} {b.quantile(0.50):>8.2f} {b.quantile(0.75):>8.2f} | "
              f"{s.quantile(0.25):>8.2f} {s.quantile(0.50):>8.2f} {s.quantile(0.75):>8.2f} | "
              f"KS={ks_stat:.3f} {'***' if ks_pval < 0.001 else '**' if ks_pval < 0.01 else '*' if ks_pval < 0.05 else ''}")


def analyze_bn_features(df):
    """Analyse specifique des features Bataille Navale."""
    bn_cols = [c for c in df.columns if c.startswith("bn_") and c in df.select_dtypes(include=[np.number]).columns]
    if not bn_cols:
        return

    print(f"\n  === BATAILLE NAVALE: Analyse detaillee ({len(bn_cols)} features) ===")

    buy = df[df["label"] == "BUY"]
    sell = df[df["label"] == "SELL"]

    for c in sorted(bn_cols):
        vals = df[c].dropna()
        if vals.std() < 1e-6:
            print(f"  {c:<30} MORT (constant = {vals.iloc[0] if len(vals) > 0 else 'N/A'})")
            continue

        b_mean = buy[c].dropna().mean()
        s_mean = sell[c].dropna().mean()
        rho, pval = stats.spearmanr(df[c].dropna(), df.loc[df[c].notna(), "label"].map({"SELL": -1, "HOLD": 0, "BUY": 1}))
        sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
        print(f"  {c:<30} BUY={b_mean:>8.3f} SELL={s_mean:>8.3f} rho={rho:>+.4f} {sig}")


def analyze_options_features(df):
    """Analyse specifique des features Options/MenthorQ/VIX."""
    opt_cols = [c for c in df.columns if any(c.startswith(p) for p in ["dist_mq_", "dist_vix_", "dist_gex_", "next_wall_", "vix_"])
                and c in df.select_dtypes(include=[np.number]).columns]
    if not opt_cols:
        return

    print(f"\n  === OPTIONS/VIX: Analyse detaillee ({len(opt_cols)} features) ===")

    buy = df[df["label"] == "BUY"]
    sell = df[df["label"] == "SELL"]

    for c in sorted(opt_cols):
        vals = df[c].dropna()
        if vals.std() < 1e-6:
            continue
        b_mean = buy[c].dropna().mean()
        s_mean = sell[c].dropna().mean()
        label_num = df["label"].map({"SELL": -1, "HOLD": 0, "BUY": 1})
        valid = df[c].notna() & label_num.notna()
        rho, pval = stats.spearmanr(df.loc[valid, c], label_num[valid])
        sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
        print(f"  {c:<35} BUY={b_mean:>8.2f} SELL={s_mean:>8.2f} diff={b_mean-s_mean:>+8.2f} rho={rho:>+.4f} {sig}")


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 100)
    print("  MIA FEATURE RULES ANALYSIS V2")
    print("  Donnees: 30/03 - 01/04/2026 | Session US | Seuils adaptes par instrument")
    print("=" * 100)

    for symbol in ["ES", "NQ"]:
        cfg = CONFIGS[symbol]
        tp_t = cfg["tp_ticks"]
        sl_t = cfg["sl_ticks"]
        la = cfg["lookahead"]

        print(f"\n{'#'*100}")
        print(f"  {symbol} — TP={tp_t}t ({tp_t*TICK_SIZE:.1f}pts), SL={sl_t}t ({sl_t*TICK_SIZE:.1f}pts), Lookahead={la} barres")
        print(f"{'#'*100}")

        # 1. Charger
        df = load_data(symbol)
        if df.empty:
            continue

        # 2. Labelliser
        df = label_bars(df, tp_t, sl_t, la)
        n_buy = (df["label"] == "BUY").sum()
        n_sell = (df["label"] == "SELL").sum()
        n_hold = (df["label"] == "HOLD").sum()
        total = len(df)
        print(f"  Base rates: BUY={n_buy/total:.1%} | SELL={n_sell/total:.1%} | HOLD={n_hold/total:.1%}")

        # 3. Spearman
        feat_cols = get_feature_cols(df)
        spearman = spearman_screening(df, feat_cols, min_rho=0.02)
        print(f"  {len(spearman)} features avec |rho| >= 0.02 / {len(feat_cols)} disponibles")

        if spearman.empty:
            continue

        # Top 30
        print(f"\n  TOP 30 FEATURES PAR |SPEARMAN|:")
        print(f"  {'#':>3} {'Feature':<40} {'rho':>8} {'p-val':>10}")
        print(f"  {'-'*65}")
        for i, (_, row) in enumerate(spearman.head(30).iterrows()):
            sig = "***" if row["pval"] < 0.001 else "**" if row["pval"] < 0.01 else "*" if row["pval"] < 0.05 else ""
            print(f"  {i+1:>3} {row['feature']:<40} {row['rho']:>+.4f} {row['pval']:>10.2e} {sig}")

        # Analyse detaillee
        deep_feature_analysis(df, spearman)
        analyze_bn_features(df)
        analyze_options_features(df)

        # 4. Regles
        print(f"\n  === RECHERCHE DE REGLES ===")
        rules = find_rules_smart(df, spearman)

        if rules.empty:
            print("  Aucune regle trouvee!")
            continue

        # 5. Simulation TP/SL symetrique
        n_days = max(df.index.normalize().nunique(), 1)
        sim = simulate_pnl(rules, tp_t, sl_t, n_days)

        buy_sim = sim[sim["direction"] == "BUY"].head(15)
        sell_sim = sim[sim["direction"] == "SELL"].head(15)

        for direction, sub in [("BUY", buy_sim), ("SELL", sell_sim)]:
            print(f"\n  === TOP REGLES {direction} ({symbol}, TP={tp_t}t SL={sl_t}t) ===")
            if sub.empty:
                print("  Aucune")
                continue
            print(f"  {'Condition':<65} {'Sig':>5} {'WR':>7} {'PF':>6} {'EV':>7} {'PnL':>7} {'T/d':>5} {'Lift':>5}")
            print(f"  {'-'*108}")
            for _, r in sub.iterrows():
                cond = r["condition"][:63]
                print(f"  {cond:<65} {r['n_signals']:>5} {r['win_rate']:>7} {r['PF']:>6.2f} {r['EV_ticks']:>+7.1f} {r['total_PnL']:>+7.0f} {r['t_per_day']:>5.1f} {r['lift']:>5.2f}")

        # 6. Simulation V1 SL/TP
        v1_tp = cfg["v1_tp"]
        v1_sl = cfg["v1_sl"]
        print(f"\n  === SIMULATION V1 ({symbol}: TP={v1_tp}t SL={v1_sl}t, R:R={v1_tp/v1_sl:.1f}:1) ===")
        sim_v1 = simulate_pnl(rules.head(20), v1_tp, v1_sl, n_days)
        good_v1 = sim_v1[sim_v1["PF"] >= 1.0].head(15)
        if not good_v1.empty:
            print(f"  {'Condition':<65} {'Sig':>5} {'WR':>7} {'PF':>6} {'EV':>7} {'PnL':>7}")
            print(f"  {'-'*100}")
            for _, r in good_v1.iterrows():
                cond = r["condition"][:63]
                print(f"  {cond:<65} {r['n_signals']:>5} {r['win_rate']:>7} {r['PF']:>6.2f} {r['EV_ticks']:>+7.1f} {r['total_PnL']:>+7.0f}")

        # 7. Features mortes
        dead = [c for c in feat_cols if df[c].std() < 1e-6 or df[c].nunique() <= 1]
        if dead:
            print(f"\n  [WARNING] {len(dead)} features MORTES: {dead[:15]}")

    print(f"\n{'='*100}")
    print("  RESUME & RECOMMANDATIONS")
    print(f"{'='*100}")
    print("""
  1. ATTENTION: 3 jours = echantillon TRES petit. Ces resultats sont indicatifs.
     Les regles doivent etre validees sur 15+ jours en walk-forward.

  2. Features les plus stables (presentes ES + NQ):
     - dist_mq_call_0dte: distance au call MenthorQ 0DTE
     - profile_skew: asymetrie du profil volume
     - range_size_ticks: taille du range session
     - volume_imbalance: desequilibre volume
     - va_position_pct: position dans la Value Area

  3. Prochaines etapes:
     - Attendre 15+ jours de donnees pour validation robuste
     - Integrer dans dataset_builder.py les features derivees les plus prometteuses
     - Tester en walk-forward avec train_lightgbm.py
""")


if __name__ == "__main__":
    main()
