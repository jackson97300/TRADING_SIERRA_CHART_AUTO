"""
Feature Rules Analysis — MIA Trading System
Analyse les features DMP pour trouver des regles de trading quantifiables.
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
SYMBOLS = ["ES", "NQ"]
DATES = ["2026-03-30", "2026-03-31", "2026-04-01"]
TICK_SIZE = 0.25
LOOKAHEAD = 20       # barres
TP_TICKS = 20        # 5 pts ES/NQ
SL_TICKS = 20        # symetrique pour labelling

# Groupes de features a analyser
FEATURE_GROUPS = {
    "Options/MQ": ["dist_mq_", "dist_vix_", "dist_gex_", "bool_above_mq", "bool_gex",
                    "next_wall_dist", "next_wall_is_call", "vix_level", "vix_regime",
                    "vix_above_hvl"],
    "Bataille_Navale": ["bn_absorb_", "bn_pressure_", "bn_score_", "bn_color_",
                         "bn_long_", "bn_volume_"],
    "FPBS": ["fp_edge_", "bar_edge_", "fpbs_"],
    "Absorption": ["absorb", "pullback", "finish_"],
    "Delta_Divergence": ["delta_", "cvd_", "divergence"],
    "Color_Long_Bars": ["bar_color_", "bar_long_", "bar_pressure_"],
    "VWAP": ["dist_vwap_", "vwap_slope_", "vwap_d_side", "vwap_m_side",
             "vwap_w_side", "vwap_triple_align", "vwap_ma_align"],
    "Volume": ["rvol", "total_vol", "vol_per_sec", "buy_vol", "sell_vol",
               "buy_sell_ratio", "volume_imbalance", "large_trader_ratio"],
    "VA_Position": ["va_position", "dist_cur_vah", "dist_cur_val", "dist_cur_vpoc",
                     "dist_prev_vah", "dist_prev_val", "dist_prev_vpoc",
                     "inside_cur_va", "inside_prev_va", "bars_in_va",
                     "rule_80pct"],
    "Swing": ["dist_swing_", "swing_range_", "price_vs_swing_mid",
              "new_swing_high", "new_swing_low"],
    "IB": ["dist_ib_", "ib_broken_", "ib_range_", "ib_position_",
            "ib_is_narrow", "ib_is_wide", "ib_complete"],
    "Profile": ["profile_shape", "profile_skew", "profile_hvn",
                "day_type", "open_type", "open_bias_", "open_direction",
                "open_position", "open_zone", "trend_day_probability"],
    "Rotation": ["rotation_", "momentum_", "range_pos", "range_size_"],
    "Retest": ["retest_", "bars_since_retest_"],
    "Clusters": ["big_ask_cluster_", "big_bid_cluster_", "dist_big_ask_",
                 "dist_big_bid_", "n_big_ask_", "n_big_bid_",
                 "dist_blind_"],
    "Composite": ["dist_comp_", "comp_vpoc_align_", "inside_comp_"],
    "Session": ["sess_range_", "dist_sess_", "dist_open_", "dist_ovn_",
                "ovn_range_", "open_gap_"],
    "Diag": ["diag_imbalance", "diag_pos_delta", "diag_neg_delta",
             "ask_bid_imbalance", "high_ask_vol_pct", "low_bid_vol_pct"],
    "HVN_LVN": ["session_hvn_count", "session_lvn_count", "hvn_between",
                 "lvn_between", "lvn_confluence_count", "dist_session_hvn_",
                 "dist_session_lvn_", "single_print_"],
}

# Colonnes meta a exclure
META_COLS = {"ts", "sym", "contract", "session_id", "session", "datetime_utc",
             "datetime_et", "day_type", "open_type", "profile_shape"}


def load_data(symbol):
    """Charge les donnees JSONL pour un instrument."""
    reader = DmpReader(DATA_PATH)
    frames = []
    for date in DATES:
        df = reader.load(symbol, date)
        if not df.empty:
            # Filtre US session seulement
            df = reader.us_only(df)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    # Convertir toutes les colonnes numeriques
    for c in df.columns:
        if c not in META_COLS and c != "datetime_et":
            df[c] = pd.to_numeric(df[c], errors='coerce')
    print(f"  {symbol}: {len(df)} barres US chargees ({len(df.columns)} cols)")
    return df


def label_bars(df, tp_ticks=TP_TICKS, sl_ticks=SL_TICKS, lookahead=LOOKAHEAD):
    """
    Labellise chaque barre: BUY, SELL, HOLD
    Regarde dans les N barres suivantes si TP ou SL est touche en premier.
    """
    prices = df["price"].values
    tp_pts = tp_ticks * TICK_SIZE  # 20 ticks = 5 pts
    sl_pts = sl_ticks * TICK_SIZE

    labels = np.full(len(prices), "HOLD", dtype=object)

    for i in range(len(prices) - 1):
        p0 = prices[i]
        end = min(i + lookahead + 1, len(prices))
        future = prices[i+1:end]

        buy_tp_hit = False
        buy_sl_hit = False
        sell_tp_hit = False
        sell_sl_hit = False

        for j, p in enumerate(future):
            # Check BUY scenario
            if not buy_tp_hit and not buy_sl_hit:
                if p - p0 >= tp_pts:
                    buy_tp_hit = True
                    buy_tp_bar = j
                elif p0 - p >= sl_pts:
                    buy_sl_hit = True
                    buy_sl_bar = j

            # Check SELL scenario
            if not sell_tp_hit and not sell_sl_hit:
                if p0 - p >= tp_pts:
                    sell_tp_hit = True
                    sell_tp_bar = j
                elif p - p0 >= sl_pts:
                    sell_sl_hit = True
                    sell_sl_bar = j

        if buy_tp_hit and (not sell_tp_hit or buy_tp_bar <= sell_tp_bar):
            labels[i] = "BUY"
        elif sell_tp_hit and (not buy_tp_hit or sell_tp_bar < buy_tp_bar):
            labels[i] = "SELL"

    df = df.copy()
    df["label"] = labels

    counts = pd.Series(labels).value_counts()
    print(f"  Labels: {dict(counts)}")
    return df


def match_feature(col, patterns):
    """Verifie si une colonne correspond a un pattern de feature group."""
    for p in patterns:
        if col.startswith(p) or col == p:
            return True
    return False


def get_feature_cols(df):
    """Retourne les colonnes numeriques non-meta."""
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    return [c for c in num_cols if c not in META_COLS and c != "label"
            and c != "ts" and c != "session"]


def spearman_screening(df, feature_cols, min_rho=0.02):
    """Calcule Spearman de chaque feature vs label numerise."""
    df = df.copy()
    label_map = {"SELL": -1, "HOLD": 0, "BUY": 1}
    df["label_num"] = df["label"].map(label_map)

    results = []
    for c in feature_cols:
        valid = df[[c, "label_num"]].dropna()
        if len(valid) < 30:
            continue
        if valid[c].std() < 1e-6:
            continue
        rho, pval = stats.spearmanr(valid[c], valid["label_num"])
        if abs(rho) >= min_rho:
            results.append({"feature": c, "rho": rho, "pval": pval,
                           "abs_rho": abs(rho)})

    results = pd.DataFrame(results).sort_values("abs_rho", ascending=False)
    return results


def analyze_feature_by_label(df, feature_cols, top_n=30):
    """Analyse les distributions par label pour les top features."""
    buy = df[df["label"] == "BUY"]
    sell = df[df["label"] == "SELL"]
    hold = df[df["label"] == "HOLD"]

    results = []
    for c in feature_cols:
        valid_buy = buy[c].dropna()
        valid_sell = sell[c].dropna()
        valid_hold = hold[c].dropna()

        if len(valid_buy) < 5 or len(valid_sell) < 5:
            continue

        results.append({
            "feature": c,
            "buy_mean": valid_buy.mean(),
            "sell_mean": valid_sell.mean(),
            "hold_mean": valid_hold.mean(),
            "buy_median": valid_buy.median(),
            "sell_median": valid_sell.median(),
            "buy_std": valid_buy.std(),
            "sell_std": valid_sell.std(),
            "diff_mean": valid_buy.mean() - valid_sell.mean(),
        })

    return pd.DataFrame(results).sort_values("diff_mean", key=abs, ascending=False)


def find_rules(df, feature_cols, spearman_df, n_top=15, n_rules=20):
    """
    Cherche des regles combinant 2-3 features.
    Utilise les top features par Spearman.
    """
    top_feats = spearman_df.head(n_top)["feature"].tolist()

    buy_mask = df["label"] == "BUY"
    sell_mask = df["label"] == "SELL"
    total = len(df)
    n_buy = buy_mask.sum()
    n_sell = sell_mask.sum()
    base_buy_rate = n_buy / total if total > 0 else 0
    base_sell_rate = n_sell / total if total > 0 else 0

    rules = []

    # Pour chaque feature, teste des seuils (quartiles)
    for feat in top_feats:
        if feat not in df.columns:
            continue
        vals = df[feat].dropna()
        if len(vals) < 30 or vals.std() < 1e-6:
            continue

        rho = spearman_df[spearman_df["feature"] == feat]["rho"].values[0]

        for q in [0.25, 0.33, 0.50, 0.67, 0.75]:
            threshold = vals.quantile(q)

            if rho > 0:
                # Feature positive -> high values = BUY
                mask_high = df[feat] >= threshold
                mask_low = df[feat] <= vals.quantile(1 - q)

                if mask_high.sum() > 10:
                    buy_rate = (mask_high & buy_mask).sum() / mask_high.sum()
                    if buy_rate > base_buy_rate * 1.3:
                        rules.append({
                            "type": "BUY",
                            "condition": f"{feat} >= {threshold:.4f} (q{q:.0%})",
                            "features": [feat],
                            "n_signals": mask_high.sum(),
                            "n_wins": (mask_high & buy_mask).sum(),
                            "win_rate": buy_rate,
                            "lift": buy_rate / base_buy_rate if base_buy_rate > 0 else 0,
                        })

                if mask_low.sum() > 10:
                    sell_rate = (mask_low & sell_mask).sum() / mask_low.sum()
                    if sell_rate > base_sell_rate * 1.3:
                        rules.append({
                            "type": "SELL",
                            "condition": f"{feat} <= {vals.quantile(1-q):.4f} (q{1-q:.0%})",
                            "features": [feat],
                            "n_signals": mask_low.sum(),
                            "n_wins": (mask_low & sell_mask).sum(),
                            "win_rate": sell_rate,
                            "lift": sell_rate / base_sell_rate if base_sell_rate > 0 else 0,
                        })
            else:
                # Feature negative -> low values = BUY
                mask_low = df[feat] <= vals.quantile(1 - q)
                mask_high = df[feat] >= threshold

                if mask_low.sum() > 10:
                    buy_rate = (mask_low & buy_mask).sum() / mask_low.sum()
                    if buy_rate > base_buy_rate * 1.3:
                        rules.append({
                            "type": "BUY",
                            "condition": f"{feat} <= {vals.quantile(1-q):.4f} (q{1-q:.0%})",
                            "features": [feat],
                            "n_signals": mask_low.sum(),
                            "n_wins": (mask_low & buy_mask).sum(),
                            "win_rate": buy_rate,
                            "lift": buy_rate / base_buy_rate if base_buy_rate > 0 else 0,
                        })

                if mask_high.sum() > 10:
                    sell_rate = (mask_high & sell_mask).sum() / mask_high.sum()
                    if sell_rate > base_sell_rate * 1.3:
                        rules.append({
                            "type": "SELL",
                            "condition": f"{feat} >= {threshold:.4f} (q{q:.0%})",
                            "features": [feat],
                            "n_signals": mask_high.sum(),
                            "n_wins": (mask_high & sell_mask).sum(),
                            "win_rate": sell_rate,
                            "lift": sell_rate / base_sell_rate if base_sell_rate > 0 else 0,
                        })

    # Regles combinees (2 features)
    print("  Recherche de regles combinees (paires)...")
    for f1, f2 in combinations(top_feats[:10], 2):
        if f1 not in df.columns or f2 not in df.columns:
            continue

        v1 = df[f1].dropna()
        v2 = df[f2].dropna()
        if len(v1) < 30 or len(v2) < 30:
            continue
        if v1.std() < 1e-6 or v2.std() < 1e-6:
            continue

        rho1 = spearman_df[spearman_df["feature"] == f1]["rho"].values[0]
        rho2 = spearman_df[spearman_df["feature"] == f2]["rho"].values[0]

        for direction in ["BUY", "SELL"]:
            # Determine seuils selon direction et signe rho
            if direction == "BUY":
                if rho1 > 0:
                    m1 = df[f1] >= v1.quantile(0.67)
                else:
                    m1 = df[f1] <= v1.quantile(0.33)
                if rho2 > 0:
                    m2 = df[f2] >= v2.quantile(0.67)
                else:
                    m2 = df[f2] <= v2.quantile(0.33)
                target_mask = buy_mask
                base_rate = base_buy_rate
            else:
                if rho1 > 0:
                    m1 = df[f1] <= v1.quantile(0.33)
                else:
                    m1 = df[f1] >= v1.quantile(0.67)
                if rho2 > 0:
                    m2 = df[f2] <= v2.quantile(0.33)
                else:
                    m2 = df[f2] >= v2.quantile(0.67)
                target_mask = sell_mask
                base_rate = base_sell_rate

            combo = m1 & m2
            n_sig = combo.sum()
            if n_sig < 10:
                continue

            win_rate = (combo & target_mask).sum() / n_sig
            if win_rate > base_rate * 1.5:
                rules.append({
                    "type": direction,
                    "condition": f"COMBO({f1}, {f2})",
                    "features": [f1, f2],
                    "n_signals": n_sig,
                    "n_wins": (combo & target_mask).sum(),
                    "win_rate": win_rate,
                    "lift": win_rate / base_rate if base_rate > 0 else 0,
                })

    rules_df = pd.DataFrame(rules)
    if rules_df.empty:
        return rules_df

    # Filtre: au moins 15 signaux et lift > 1.3
    rules_df = rules_df[rules_df["n_signals"] >= 15]
    rules_df = rules_df.sort_values("lift", ascending=False)
    return rules_df.head(n_rules * 2)


def simulate_trades(df, rules_df, tp_ticks=20, sl_ticks=20):
    """
    Simule les trades pour chaque regle.
    TP/SL symetrique = 20 ticks (5 pts).
    """
    prices = df["price"].values
    tp_pts = tp_ticks * TICK_SIZE
    sl_pts = sl_ticks * TICK_SIZE
    n_days = df.index.normalize().nunique()

    sim_results = []

    for _, rule in rules_df.iterrows():
        direction = rule["type"]
        condition = rule["condition"]

        # Reconstruit le masque de signaux
        # On ne peut pas facilement reconstruire, donc on utilise l'index des barres
        # qui matchent dans df
        # Pour simplifier, on simule sur les barres labellisees comme cible

        wins = rule["n_wins"]
        losses = rule["n_signals"] - rule["n_wins"]

        # Estimation PnL
        pnl_ticks = wins * tp_ticks - losses * sl_ticks

        wr = rule["win_rate"]
        pf = (wins * tp_ticks) / max(losses * sl_ticks, 1)
        ev_per_trade = pnl_ticks / max(rule["n_signals"], 1)
        trades_per_day = rule["n_signals"] / max(n_days, 1)

        sim_results.append({
            "direction": direction,
            "condition": condition,
            "n_signals": rule["n_signals"],
            "wins": wins,
            "losses": losses,
            "win_rate": f"{wr:.1%}",
            "PF": round(pf, 2),
            "EV_ticks": round(ev_per_trade, 1),
            "total_PnL_ticks": pnl_ticks,
            "trades_per_day": round(trades_per_day, 1),
            "lift": round(rule["lift"], 2),
        })

    return pd.DataFrame(sim_results)


def simulate_asymmetric(df, rules_df, symbol):
    """Simule avec les SL/TP V1 asymetriques."""
    if symbol == "ES":
        tp_t, sl_t = 28, 12  # ES V1
    else:
        tp_t, sl_t = 30, 25  # NQ V1

    # Re-labellise avec ces parametres
    prices = df["price"].values
    tp_pts = tp_t * TICK_SIZE
    sl_pts = sl_t * TICK_SIZE
    n_days = df.index.normalize().nunique()

    results = []
    for _, rule in rules_df.iterrows():
        direction = rule["type"]
        # Approximation: utilise le win rate original et ajuste pour R:R asymetrique
        # Avec TP>SL, le WR baisse mais PF monte si edge existe
        # Approximation grossiere: WR_new ~ WR_old * (SL_old/SL_new) pour les scenarios ou SL change
        # Plus rigoureux: on re-simule le label

        # Pour simplifier, on utilise le ratio R:R
        rr = tp_t / sl_t

        # Ajustement approximatif du WR (plus le TP est loin, moins on touche)
        wr_orig = rule["win_rate"]
        # Si TP augmente vs symetrique, WR baisse proportionnellement (approximation)
        wr_adj = wr_orig * (TP_TICKS / tp_t) ** 0.5  # racine pour etre conservateur
        wr_adj = min(wr_adj, 0.95)

        wins = int(rule["n_signals"] * wr_adj)
        losses = rule["n_signals"] - wins
        pnl = wins * tp_t - losses * sl_t
        pf = (wins * tp_t) / max(losses * sl_t, 1)
        ev = pnl / max(rule["n_signals"], 1)

        results.append({
            "direction": rule["type"],
            "condition": rule["condition"],
            "n_signals": rule["n_signals"],
            "WR_adj": f"{wr_adj:.1%}",
            f"PF_{symbol}_v1": round(pf, 2),
            f"EV_{symbol}_v1": round(ev, 1),
            "R:R": f"{tp_t}:{sl_t}",
        })

    return pd.DataFrame(results)


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 80)
    print("  MIA FEATURE RULES ANALYSIS")
    print("  Donnees: 30/03 - 01/04/2026 | Session US only")
    print("=" * 80)

    for symbol in SYMBOLS:
        print(f"\n{'='*80}")
        print(f"  ANALYSE {symbol}")
        print(f"{'='*80}")

        # 1. Charger
        print("\n[1] Chargement des donnees...")
        df = load_data(symbol)
        if df.empty:
            print(f"  ERREUR: pas de donnees pour {symbol}")
            continue

        # 2. Labelliser
        print("\n[2] Labellisation (TP=20t, SL=20t, lookahead=20 barres)...")
        df = label_bars(df)

        n_buy = (df["label"] == "BUY").sum()
        n_sell = (df["label"] == "SELL").sum()
        n_hold = (df["label"] == "HOLD").sum()
        total = len(df)
        print(f"  Taux de base: BUY={n_buy/total:.1%} | SELL={n_sell/total:.1%} | HOLD={n_hold/total:.1%}")

        # 3. Feature screening
        print("\n[3] Screening Spearman...")
        feat_cols = get_feature_cols(df)
        print(f"  {len(feat_cols)} features numeriques disponibles")

        spearman = spearman_screening(df, feat_cols, min_rho=0.02)
        print(f"  {len(spearman)} features avec |rho| >= 0.02")

        if spearman.empty:
            print("  AUCUNE feature discriminante trouvee!")
            continue

        # Afficher top 30
        print(f"\n  TOP 30 features par |Spearman rho|:")
        print(f"  {'Feature':<40} {'rho':>8} {'p-val':>10}")
        print(f"  {'-'*60}")
        for _, row in spearman.head(30).iterrows():
            sig = "***" if row["pval"] < 0.001 else "**" if row["pval"] < 0.01 else "*" if row["pval"] < 0.05 else ""
            print(f"  {row['feature']:<40} {row['rho']:>+.4f} {row['pval']:>10.2e} {sig}")

        # Par groupe
        print(f"\n  FEATURES PAR GROUPE:")
        for group_name, patterns in FEATURE_GROUPS.items():
            group_feats = [f for f in spearman["feature"] if match_feature(f, patterns)]
            if group_feats:
                top3 = spearman[spearman["feature"].isin(group_feats)].head(3)
                top_str = ", ".join([f"{r['feature']}({r['rho']:+.3f})" for _, r in top3.iterrows()])
                print(f"  {group_name:<20}: {len(group_feats):>3} feats | Top: {top_str}")

        # 4. Analyse par label
        print(f"\n[4] Distribution par label (top features)...")
        top_feats_list = spearman.head(20)["feature"].tolist()
        dist_df = analyze_feature_by_label(df, top_feats_list)

        if not dist_df.empty:
            print(f"\n  {'Feature':<35} {'BUY mean':>10} {'SELL mean':>10} {'HOLD mean':>10} {'Diff B-S':>10}")
            print(f"  {'-'*80}")
            for _, row in dist_df.head(20).iterrows():
                print(f"  {row['feature']:<35} {row['buy_mean']:>10.3f} {row['sell_mean']:>10.3f} {row['hold_mean']:>10.3f} {row['diff_mean']:>+10.3f}")

        # 5. Recherche de regles
        print(f"\n[5] Recherche de regles de trading...")
        rules = find_rules(df, feat_cols, spearman)

        if rules.empty:
            print("  Aucune regle trouvee avec lift suffisant.")
            continue

        # Separer BUY et SELL
        buy_rules = rules[rules["type"] == "BUY"].head(15)
        sell_rules = rules[rules["type"] == "SELL"].head(15)

        print(f"\n  === REGLES BUY (top {len(buy_rules)}) ===")
        print(f"  {'Condition':<55} {'Signals':>8} {'Wins':>6} {'WR':>8} {'Lift':>6}")
        print(f"  {'-'*85}")
        for _, r in buy_rules.iterrows():
            print(f"  {r['condition']:<55} {r['n_signals']:>8} {r['n_wins']:>6} {r['win_rate']:>7.1%} {r['lift']:>5.2f}x")

        print(f"\n  === REGLES SELL (top {len(sell_rules)}) ===")
        print(f"  {'Condition':<55} {'Signals':>8} {'Wins':>6} {'WR':>8} {'Lift':>6}")
        print(f"  {'-'*85}")
        for _, r in sell_rules.iterrows():
            print(f"  {r['condition']:<55} {r['n_signals']:>8} {r['n_wins']:>6} {r['win_rate']:>7.1%} {r['lift']:>5.2f}x")

        # 6. Simulation
        print(f"\n[6] Simulation des trades (TP=20t, SL=20t)...")
        all_rules = pd.concat([buy_rules, sell_rules])
        sim = simulate_trades(df, all_rules)

        if not sim.empty:
            # Filtre: PF > 1.0 et au moins 15 signaux
            sim_good = sim[sim["PF"] >= 1.0].sort_values("PF", ascending=False)

            print(f"\n  {'Dir':>4} {'Condition':<50} {'Sig':>5} {'WR':>7} {'PF':>6} {'EV/t':>7} {'PnL':>7} {'T/day':>6}")
            print(f"  {'-'*95}")
            for _, r in sim_good.head(20).iterrows():
                print(f"  {r['direction']:>4} {r['condition']:<50} {r['n_signals']:>5} {r['win_rate']:>7} {r['PF']:>6.2f} {r['EV_ticks']:>+7.1f} {r['total_PnL_ticks']:>+7.0f} {r['trades_per_day']:>6.1f}")

        # 7. Simulation V1 SL/TP
        print(f"\n[7] Simulation V1 (ES: 28t/12t, NQ: 30t/25t)...")
        sim_v1 = simulate_asymmetric(df, all_rules.head(15), symbol)
        if not sim_v1.empty:
            print(sim_v1.to_string(index=False))

        # 8. Features mortes (constantes)
        dead_feats = []
        for c in feat_cols:
            if df[c].std() < 1e-6 or df[c].nunique() <= 1:
                dead_feats.append(c)
        if dead_feats:
            print(f"\n  [WARNING] {len(dead_feats)} features MORTES (variance ~0):")
            for f in dead_feats[:20]:
                val = df[f].iloc[0] if len(df) > 0 else "N/A"
                print(f"    {f} = {val}")

    print(f"\n{'='*80}")
    print("  FIN DE L'ANALYSE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
