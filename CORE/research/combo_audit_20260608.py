"""
Combo Audit ANTI DATA MINING TRAP — 08/06/2026

Mission: identifier combos 2-3 features qui discriminent WIN vs LOSS
Bot 1 SIM1, avec walk-forward 5-fold + DSR Lopez + Bonferroni.

Methodologie:
  1. Load trades Bot 1 SIM1 (sans _databento/_v3/_v6) → 206 trades
  2. Stratification: NQ_LONG, NQ_SHORT, ES_LONG, ES_SHORT
  3. Pour chaque combo (max 30):
     - Calcul AND logic activation (toutes features actives)
     - Walk-forward 5-fold chronologique
     - Effect size Cohen's d, p Welch
     - DSR Lopez avec deflation Bonferroni N_combos
  4. Verdict GO/NOGO par combo
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
from statistics import mean, stdev, NormalDist

DATA_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# === Load trades ===
def load_trades() -> list[dict]:
    trades = []
    files = sorted(DATA_DIR.glob("*_trades.jsonl"))
    files = [f for f in files if not any(s in f.name for s in ["_databento", "_v3", "_v6"])]
    for f in files:
        date_str = f.name[:8]
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                t["_date"] = date_str
                trades.append(t)
    return trades


def extract_features(t: dict) -> dict | None:
    """Extract features at entry context. Uses exit_context as proxy (closest to entry available)."""
    dmp = t.get("dmp_bar_at_exit") or {}
    dash = t.get("dashboard_instrument_at_exit") or {}
    reg = dash.get("regime") or {}
    of = dash.get("order_flow") or {}
    bn = dash.get("battle_navale") or {}
    sess = dash.get("session") or {}
    mp = dash.get("market_profile") or {}
    inter = t.get("intermarket_at_exit") or {}

    if not dmp:
        return None

    direction = t.get("direction")
    if direction not in ("LONG", "SHORT"):
        return None

    # PnL
    pnl_usd = t.get("pnl_usd", 0)
    win = 1 if pnl_usd > 0 else 0

    # === Features actuelles scoring (poids dans build_conseil_global) ===
    # Bias (1=BULLISH, -1=BEARISH, 0=NEUTRAL) — aligne avec direction?
    bias_label = reg.get("bias", "NEUTRAL")
    bias_aligned = 1 if (
        (direction == "LONG" and bias_label == "BULLISH") or
        (direction == "SHORT" and bias_label == "BEARISH")
    ) else 0

    # delta_dir aligned
    delta_day_dir = of.get("delta_day_dir", 0)
    delta_dir_aligned = 1 if (
        (direction == "LONG" and delta_day_dir == 1) or
        (direction == "SHORT" and delta_day_dir == -1)
    ) else 0

    # Range_pos extreme (>85 = top BAD pour LONG / GOOD pour SHORT, <15 = bottom GOOD pour LONG)
    range_pos = reg.get("range_pos", 50.0) or 50.0
    range_pos_favor_long = 1 if range_pos < 15.0 else 0  # bottom = LONG buy zone
    range_pos_favor_short = 1 if range_pos > 85.0 else 0  # top = SHORT zone
    range_pos_aligned = 1 if (
        (direction == "LONG" and range_pos_favor_long) or
        (direction == "SHORT" and range_pos_favor_short)
    ) else 0

    # MTF (4-vote, bulls vs bears)
    mtf_bulls = reg.get("mtf_bulls", 0) or 0
    mtf_bears = reg.get("mtf_bears", 0) or 0
    mtf_aligned = 1 if (
        (direction == "LONG" and mtf_bulls >= 3) or
        (direction == "SHORT" and mtf_bears >= 3)
    ) else 0

    # Divergence
    div_active = 1 if reg.get("div_active") else 0

    # === BN events ===
    bn_color_up = int(dmp.get("bn_color_up", 0) or 0)
    bn_color_dn = int(dmp.get("bn_color_dn", 0) or 0)
    bn_color_up_2 = int(dmp.get("bn_color_up_2", 0) or 0)
    bn_color_dn_2 = int(dmp.get("bn_color_dn_2", 0) or 0)
    bn_absorb_ask = int(dmp.get("bn_absorb_ask", 0) or 0)
    bn_absorb_bid = int(dmp.get("bn_absorb_bid", 0) or 0)
    bn_long_up = int(dmp.get("bn_long_up", 0) or 0)
    bn_long_dn = int(dmp.get("bn_long_dn", 0) or 0)
    bn_volume_up = int(dmp.get("bn_volume_up", 0) or 0)
    bn_volume_dn = int(dmp.get("bn_volume_dn", 0) or 0)
    bar_long_up_bar = int(dmp.get("bar_long_up_bar", 0) or 0)
    bar_long_dn_bar = int(dmp.get("bar_long_dn_bar", 0) or 0)
    bar_edge_buy = int(dmp.get("bar_edge_buy", 0) or 0)
    bar_edge_sell = int(dmp.get("bar_edge_sell", 0) or 0)
    fp_edge_buy = int(dmp.get("fp_edge_buy", 0) or 0)
    fp_edge_sell = int(dmp.get("fp_edge_sell", 0) or 0)
    delta_divergence = int(dmp.get("delta_divergence", 0) or 0)

    # BN aligned events
    bn_color_aligned = 1 if (
        (direction == "LONG" and (bn_color_up or bn_color_up_2)) or
        (direction == "SHORT" and (bn_color_dn or bn_color_dn_2))
    ) else 0

    bn_long_aligned = 1 if (
        (direction == "LONG" and (bn_long_up or bar_long_up_bar)) or
        (direction == "SHORT" and (bn_long_dn or bar_long_dn_bar))
    ) else 0

    bn_absorb_aligned = 1 if (
        (direction == "LONG" and bn_absorb_bid) or
        (direction == "SHORT" and bn_absorb_ask)
    ) else 0

    bn_edge_aligned = 1 if (
        (direction == "LONG" and (bar_edge_buy or fp_edge_buy)) or
        (direction == "SHORT" and (bar_edge_sell or fp_edge_sell))
    ) else 0

    bn_volume_aligned = 1 if (
        (direction == "LONG" and bn_volume_up) or
        (direction == "SHORT" and bn_volume_dn)
    ) else 0

    # === Microstructure ===
    delta_pct = of.get("delta_pct", 0) or 0
    delta_aligned = 1 if (
        (direction == "LONG" and delta_pct > 0.15) or
        (direction == "SHORT" and delta_pct < -0.15)
    ) else 0

    cvd_day_dir = of.get("cvd_day_dir", 0) or 0
    cvd_aligned = 1 if (
        (direction == "LONG" and cvd_day_dir == 1) or
        (direction == "SHORT" and cvd_day_dir == -1)
    ) else 0

    rvol = of.get("rvol", 1.0) or 1.0
    rvol_high = 1 if rvol > 1.2 else 0

    # === Profile / session ===
    open_zone = sess.get("open_zone", 0) or 0
    open_in_prev_va = sess.get("open_in_prev_va", 0) or 0
    inside_cur_va = mp.get("inside_cur_va", 0) or 0

    # === Cross-instrument ===
    cross_delta_agree = inter.get("cross_delta_agreement", 0) or 0
    smt_div = inter.get("smt_divergence", 0) or 0

    # === VIX ===
    vix_regime = reg.get("vix_regime", 1) or 1
    vix_normal = 1 if vix_regime == 1 else 0

    return {
        "date": t["_date"],
        "ts": t.get("entry_ts", 0),
        "symbol": t.get("symbol", ""),
        "direction": direction,
        "strata": f"{t.get('symbol','')}_{direction}",
        "pnl_usd": pnl_usd,
        "win": win,
        "outcome": t.get("outcome", ""),
        # Scoring actuel
        "bias_aligned": bias_aligned,
        "delta_dir_aligned": delta_dir_aligned,
        "range_pos_aligned": range_pos_aligned,
        "mtf_aligned": mtf_aligned,
        "div_active": div_active,
        # BN
        "bn_color_aligned": bn_color_aligned,
        "bn_long_aligned": bn_long_aligned,
        "bn_absorb_aligned": bn_absorb_aligned,
        "bn_edge_aligned": bn_edge_aligned,
        "bn_volume_aligned": bn_volume_aligned,
        # Micro
        "delta_aligned": delta_aligned,
        "cvd_aligned": cvd_aligned,
        "rvol_high": rvol_high,
        # Profile
        "open_zone": open_zone,
        "open_in_prev_va": open_in_prev_va,
        "inside_cur_va": inside_cur_va,
        # Cross
        "cross_delta_agree": cross_delta_agree,
        "smt_div": smt_div,
        # Regime
        "vix_normal": vix_normal,
    }


# === Stats helpers ===
def welch_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Returns (t_stat, p_two_sided). Approximation via Welch-Satterthwaite."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0, 1.0
    m1, m2 = mean(a), mean(b)
    v1, v2 = (stdev(a) ** 2) if n1 > 1 else 0.0, (stdev(b) ** 2) if n2 > 1 else 0.0
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 0.0, 1.0
    t = (m1 - m2) / se
    # Welch df
    num = (v1 / n1 + v2 / n2) ** 2
    denom = ((v1 / n1) ** 2 / max(n1 - 1, 1)) + ((v2 / n2) ** 2 / max(n2 - 1, 1))
    df = num / denom if denom > 0 else 1.0
    # Approx p from normal (df>30 usually fine)
    z = abs(t)
    nd = NormalDist()
    p = 2 * (1 - nd.cdf(z))
    return t, p


def cohens_d(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    m1, m2 = mean(a), mean(b)
    v1 = stdev(a) ** 2
    v2 = stdev(b) ** 2
    pooled = math.sqrt(((len(a) - 1) * v1 + (len(b) - 1) * v2) / (len(a) + len(b) - 2))
    if pooled == 0:
        return 0.0
    return (m1 - m2) / pooled


def sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    s = stdev(pnls)
    if s == 0:
        return 0.0
    return mean(pnls) / s


def dsr_lopez(sharpe_obs: float, n_trials: int, n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Deflated Sharpe Ratio (Lopez de Prado 2014).
    Returns probability that true SR > 0 given multiple testing.
    Simplified: PSR with deflation by sqrt(2*ln(N_trials)).
    """
    if n_obs < 2 or n_trials < 1:
        return 0.0
    # Expected max SR under null with N trials (Bailey & Lopez de Prado 2014)
    nd = NormalDist()
    if n_trials == 1:
        sr_expected_max = 0.0
    else:
        gamma = 0.5772156649  # Euler-Mascheroni
        sr_expected_max = math.sqrt(2 * math.log(n_trials)) * (1 - gamma / math.sqrt(2 * math.log(n_trials))) - nd.inv_cdf(1 - 1/(n_trials * math.e))
        sr_expected_max = sr_expected_max / math.sqrt(n_obs)  # per-obs scale; conservative
    # DSR: probability that observed SR exceeds expected max
    sr_std = math.sqrt((1 - skew * sharpe_obs + (kurt - 1) / 4 * sharpe_obs ** 2) / (n_obs - 1))
    if sr_std == 0:
        return 0.0
    z = (sharpe_obs - sr_expected_max) / sr_std
    return nd.cdf(z)


# === Combos ===
SIGNALS_BASE = ["bias_aligned", "delta_dir_aligned", "range_pos_aligned", "mtf_aligned"]
BN_FEATURES = ["bn_color_aligned", "bn_long_aligned", "bn_absorb_aligned", "bn_edge_aligned", "bn_volume_aligned"]
MICRO = ["delta_aligned", "cvd_aligned", "rvol_high"]
PROFILE = ["open_zone", "inside_cur_va"]
CROSS = ["cross_delta_agree"]

# Construct max 30 combos
COMBOS = []
# Pairs scoring × BN
for s in SIGNALS_BASE:
    for bn in BN_FEATURES:
        COMBOS.append((s, bn))
# Pairs BN × micro
for bn in BN_FEATURES:
    for m in ["delta_aligned", "cvd_aligned"]:
        COMBOS.append((bn, m))
# Triples bias + delta + bn_color
COMBOS.append(("bias_aligned", "delta_aligned", "bn_color_aligned"))
COMBOS.append(("bias_aligned", "mtf_aligned", "bn_color_aligned"))
COMBOS.append(("mtf_aligned", "delta_aligned", "bn_long_aligned"))
COMBOS.append(("bias_aligned", "cvd_aligned", "bn_color_aligned"))
COMBOS.append(("mtf_aligned", "cross_delta_agree", "bn_color_aligned"))
# Range_pos × BN edge (Jackson lesson 07/05 sur color DN dans zone basse)
COMBOS.append(("range_pos_aligned", "bn_color_aligned"))
COMBOS.append(("range_pos_aligned", "bn_edge_aligned"))
# Dedupe
COMBOS = list(dict.fromkeys(tuple(sorted(c)) for c in COMBOS))
N_COMBOS = len(COMBOS)


def combo_active(row: dict, features: tuple[str, ...]) -> int:
    return int(all(row.get(f, 0) == 1 for f in features))


# === Walk-forward 5-fold chronologique ===
def walk_forward_5fold(rows: list[dict], features: tuple[str, ...]) -> dict:
    """Returns: n_active_total, mean_pnl_active, n_per_fold, mean_pnl_per_fold, dsr."""
    # Sort chrono
    rows_sorted = sorted(rows, key=lambda r: (r["date"], r["ts"]))
    n = len(rows_sorted)
    if n < 25:
        return {"feasible": False, "reason": f"N total {n} <25"}
    fold_size = n // 5
    folds = [rows_sorted[i * fold_size:(i + 1) * fold_size] for i in range(4)]
    folds.append(rows_sorted[4 * fold_size:])

    fold_stats = []
    all_active_pnl = []
    all_inactive_pnl = []
    for i, fold in enumerate(folds):
        active = [r["pnl_usd"] for r in fold if combo_active(r, features)]
        inactive = [r["pnl_usd"] for r in fold if not combo_active(r, features)]
        fold_stats.append({
            "fold": i + 1,
            "n_active": len(active),
            "n_inactive": len(inactive),
            "wr_active": (sum(1 for p in active if p > 0) / len(active)) if active else 0.0,
            "mean_pnl_active": mean(active) if active else 0.0,
            "mean_pnl_inactive": mean(inactive) if inactive else 0.0,
        })
        all_active_pnl.extend(active)
        all_inactive_pnl.extend(inactive)

    n_active = len(all_active_pnl)
    if n_active == 0:
        return {"feasible": False, "reason": "0 actif sur tout l'echantillon"}

    # Concentration: max fold share
    max_fold_share = max(fs["n_active"] for fs in fold_stats) / max(n_active, 1)
    # Per-fold mean PnL stability: std of fold means
    fold_means = [fs["mean_pnl_active"] for fs in fold_stats if fs["n_active"] >= 5]
    fold_mean_std = stdev(fold_means) if len(fold_means) >= 2 else 0.0

    # Effect size
    d = cohens_d(all_active_pnl, all_inactive_pnl)
    t, p = welch_t_test(all_active_pnl, all_inactive_pnl)
    # Sharpe
    sr = sharpe(all_active_pnl)
    dsr = dsr_lopez(sr, n_trials=N_COMBOS, n_obs=n_active)

    # WR active
    wr_active = sum(1 for p in all_active_pnl if p > 0) / n_active if n_active else 0
    wr_inactive = sum(1 for p in all_inactive_pnl if p > 0) / len(all_inactive_pnl) if all_inactive_pnl else 0

    return {
        "feasible": True,
        "n_total": n,
        "n_active": n_active,
        "n_inactive": len(all_inactive_pnl),
        "wr_active": wr_active,
        "wr_inactive": wr_inactive,
        "mean_pnl_active": mean(all_active_pnl) if all_active_pnl else 0,
        "mean_pnl_inactive": mean(all_inactive_pnl) if all_inactive_pnl else 0,
        "cohens_d": d,
        "p_welch": p,
        "sharpe_active": sr,
        "dsr_lopez": dsr,
        "fold_stats": fold_stats,
        "max_fold_share": max_fold_share,
        "fold_mean_std": fold_mean_std,
        "folds_with_n_ge_30": sum(1 for fs in fold_stats if fs["n_active"] >= 30),
    }


# === Main ===
def main():
    trades = load_trades()
    rows = []
    for t in trades:
        row = extract_features(t)
        if row is not None:
            rows.append(row)
    print(f"Total trades loaded: {len(trades)}")
    print(f"Rows with features: {len(rows)}")

    # Strata counts
    from collections import Counter
    strata_counts = Counter(r["strata"] for r in rows)
    print(f"Strata: {dict(strata_counts)}")

    bonferroni_p = 0.05 / N_COMBOS
    print(f"\nN_COMBOS tested: {N_COMBOS}")
    print(f"Bonferroni threshold p: {bonferroni_p:.5f}")
    print()

    # GLOBAL analysis (all symbols all directions pooled)
    print("=" * 100)
    print("GLOBAL POOL (all symbols, all directions)")
    print("=" * 100)
    print(f"{'Combo':<70} {'N_act':>6} {'WR_act':>7} {'Mean_PnL':>10} {'d':>6} {'p':>8} {'DSR':>6} {'Conc':>5} {'Folds>=30':>9}")

    global_results = []
    for combo in COMBOS:
        res = walk_forward_5fold(rows, combo)
        if not res.get("feasible"):
            continue
        global_results.append((combo, res))

    # Sort by Cohen's d magnitude
    global_results.sort(key=lambda x: abs(x[1]["cohens_d"]), reverse=True)
    for combo, res in global_results:
        cstr = "+".join(combo)[:68]
        print(f"{cstr:<70} {res['n_active']:>6} {res['wr_active']:>7.2%} "
              f"{res['mean_pnl_active']:>10.2f} {res['cohens_d']:>6.3f} "
              f"{res['p_welch']:>8.4f} {res['dsr_lopez']:>6.3f} "
              f"{res['max_fold_share']:>5.2f} {res['folds_with_n_ge_30']:>9}")

    print()
    print("=" * 100)
    print("Top 5 par |Cohen's d|")
    print("=" * 100)
    for combo, res in global_results[:5]:
        verdict = make_verdict(res, bonferroni_p)
        print(f"\nCombo: {' AND '.join(combo)}")
        print(f"  N actif: {res['n_active']} / {res['n_total']}")
        print(f"  WR actif: {res['wr_active']:.2%} vs WR inactif: {res['wr_inactive']:.2%}")
        print(f"  Mean PnL actif: ${res['mean_pnl_active']:.2f} vs inactif ${res['mean_pnl_inactive']:.2f}")
        print(f"  Cohen's d: {res['cohens_d']:.3f}")
        print(f"  p Welch: {res['p_welch']:.4f} (Bonf seuil {bonferroni_p:.4f})")
        print(f"  Sharpe actif: {res['sharpe_active']:.3f}")
        print(f"  DSR Lopez: {res['dsr_lopez']:.3f} (seuil 0.5)")
        print(f"  Max fold concentration: {res['max_fold_share']:.1%}")
        print(f"  Folds avec N actif >=30: {res['folds_with_n_ge_30']}/5")
        print(f"  Fold stats:")
        for fs in res["fold_stats"]:
            print(f"    F{fs['fold']}: n_act={fs['n_active']:>3} wr={fs['wr_active']:.0%} mean=${fs['mean_pnl_active']:>7.2f}")
        print(f"  VERDICT: {verdict}")

    # Sort by DSR
    print()
    print("=" * 100)
    print("Top 5 par DSR Lopez")
    print("=" * 100)
    by_dsr = sorted(global_results, key=lambda x: x[1]["dsr_lopez"], reverse=True)
    for combo, res in by_dsr[:5]:
        verdict = make_verdict(res, bonferroni_p)
        print(f"  {' AND '.join(combo):<60} DSR={res['dsr_lopez']:.3f} d={res['cohens_d']:.3f} N={res['n_active']:>3} verdict={verdict}")

    # STRATIFICATION
    print()
    print("=" * 100)
    print("STRATIFICATION par symbole+direction")
    print("=" * 100)
    for stratum in ["NQ_LONG", "NQ_SHORT", "ES_LONG", "ES_SHORT"]:
        sub = [r for r in rows if r["strata"] == stratum]
        if len(sub) < 25:
            print(f"\n{stratum}: N={len(sub)} <25 → SKIP (insufficient)")
            continue
        print(f"\n{stratum}: N={len(sub)}")
        sub_results = []
        for combo in COMBOS:
            res = walk_forward_5fold(sub, combo)
            if not res.get("feasible"):
                continue
            sub_results.append((combo, res))
        sub_results.sort(key=lambda x: abs(x[1]["cohens_d"]), reverse=True)
        for combo, res in sub_results[:5]:
            verdict_short = "GO" if (
                res["folds_with_n_ge_30"] >= 3 and
                res["dsr_lopez"] > 0.5 and
                res["p_welch"] < bonferroni_p and
                res["max_fold_share"] < 0.33
            ) else "NOGO"
            print(f"  {' AND '.join(combo):<60} N_act={res['n_active']:>3} WR={res['wr_active']:.0%} "
                  f"d={res['cohens_d']:>6.3f} p={res['p_welch']:.4f} DSR={res['dsr_lopez']:.3f} {verdict_short}")


def make_verdict(res: dict, bonf_p: float) -> str:
    """Determine GO/NOGO based on 5 controls."""
    reasons = []
    if res["folds_with_n_ge_30"] < 3:
        reasons.append(f"N<30 dans {5 - res['folds_with_n_ge_30']}/5 folds")
    if res["dsr_lopez"] < 0.5:
        reasons.append(f"DSR={res['dsr_lopez']:.2f}<0.5")
    if res["p_welch"] > bonf_p:
        reasons.append(f"p={res['p_welch']:.4f}>Bonf({bonf_p:.4f})")
    if res["max_fold_share"] > 0.33:
        reasons.append(f"conc={res['max_fold_share']:.0%}>33%")
    if abs(res["cohens_d"]) < 0.30:
        reasons.append(f"|d|={abs(res['cohens_d']):.2f}<0.30")

    if not reasons:
        return "GO"
    if len(reasons) == 1:
        return f"GO-AVEC-RESERVES ({reasons[0]})"
    if res["n_active"] < 30:
        return f"INSUFFICIENT N ({'; '.join(reasons)})"
    return f"REJET ({'; '.join(reasons)})"


if __name__ == "__main__":
    main()
