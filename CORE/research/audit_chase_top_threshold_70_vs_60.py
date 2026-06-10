"""
audit_chase_top_threshold_70_vs_60.py — Audit walk-forward Lopez 5-fold compare
ChaseTopGate threshold 60 (deploy actuel, validation 05/05 DSR=0.72 +$1264)
vs threshold 70 (proposition Jackson 06/05).

Methodologie (apres review ml-trainer 06/05) :
1. Pour chaque trade Bot 1 historique LONG → trouve snapshot meme `signal_id` →
   lit `range_pos` a entry (dmp_bar.range_pos). Premier snapshot enregistre par
   signal_id = signal cree (creation event), correct pour ChaseTopGate at-entry.
2. Pour threshold 60 et 70 separement :
   - Trade range_pos_at_entry >= threshold → "bloque par filtre"
   - delta_per_trade = -pnl_usd (SL bloque = +$, TP bloque = -$, TIMEOUT typique = ~0$)
3. Walk-forward 5-fold split par DATE (pas index) pour eviter biais 1-jour-par-fold.
4. **DSR Lopez sur trades-blocked individuels** (n=n_blocked, ~20-50). Pas sur folds.
5. n_trials=500 (haircut conservateur multiple testing : 60 deja teste 05/05 +
   variantes possibles 50/65/70/75/80 + selection bias).
6. **Verdict GO_70_REPLACE_60** si TOUS criteres :
   - DSR_70 >= 0.5 (Lopez minimum)
   - DSR_70 >= DSR_60 - 0.05 (pas de degradation risk-adjusted, tolerance 5pp bruit)
   - delta_70 > 0 (filtre profitable)
   - delta_70 - delta_60 > 0 (70 > 60 brut)
   - n_blocked_70 >= 20 (sample size)
   - n_folds_positive_70 >= 4/5 (stabilite)
   - concentration_top2_70 < 0.6 (regime stationnaire)
7. Split par symbole : verdict global (ALL) + NQ-only + ES-only.

Source de verite :
- Trades : DATA/PAPER_TRADES/20*_trades.jsonl (excl databento)
- range_pos a entry : DATA/PAPER_TRADES/20*_snapshots.jsonl (signal_id match)

Run : python -X utf8 CORE/research/audit_chase_top_threshold_70_vs_60.py
"""
from __future__ import annotations

import json
import math
from glob import glob
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = ROOT / "DATA" / "PAPER_TRADES"

N_FOLDS = 5
# Haircut DSR ml-trainer Q3 : 500 conservateur (60 deja teste + variantes possibles)
N_STRATEGIES = 500

# Verdict thresholds
DSR_MIN = 0.5
DSR_DEGRADATION_TOLERANCE = 0.05  # DSR_70 doit etre >= DSR_60 - 0.05
N_BLOCKED_MIN = 20
N_FOLDS_POSITIVE_MIN = 4
CONCENTRATION_TOP2_MAX = 0.60


def deflated_sharpe(sr_observed, n_obs, skew, kurt, n_trials):
    if n_obs < 10 or sr_observed <= 0:
        return None, None
    gamma = 0.5772156649
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))
    denom = 1 - skew * sr_observed + (kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr_observed * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    dsr = stats.norm.cdf((sr_observed - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    return float(psr), float(dsr)


def load_trades_with_range_pos():
    """Joine trades + snapshots via signal_id. Premier snapshot par signal_id =
    creation event (correct pour ChaseTopGate at-entry).
    Retourne LONG-only (ChaseTopGate = LONG-only filter).
    """
    snap_files = sorted(glob(str(PAPER_DIR / "20*_snapshots.jsonl")))
    snap_by_sig = {}
    for fp in snap_files:
        if "databento" in fp:
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        s = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sig = s.get("signal_id")
                    if not sig or sig in snap_by_sig:
                        continue  # premier = creation
                    rp = (s.get("dmp_bar") or {}).get("range_pos")
                    if rp is not None:
                        snap_by_sig[sig] = float(rp)
        except OSError:
            continue
    print(f"  Snapshots indexed by signal_id : {len(snap_by_sig)}")

    trade_files = sorted(glob(str(PAPER_DIR / "20*_trades.jsonl")))
    trade_files = [f for f in trade_files if "databento" not in f]
    trades = []
    n_total, n_with_rp, n_long = 0, 0, 0
    for fp in trade_files:
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    n_total += 1
                    if r.get("direction", "") != "LONG":
                        continue
                    n_long += 1
                    sig = r.get("signal_id")
                    rp = snap_by_sig.get(sig)
                    if rp is None:
                        continue
                    n_with_rp += 1
                    entry_time = r.get("entry_time", "")
                    entry_date = entry_time[:10] if entry_time else ""
                    trades.append({
                        "signal_id": sig,
                        "ts": entry_time,
                        "date": entry_date,
                        "sym": r.get("symbol"),
                        "outcome": r.get("outcome"),
                        "pnl_usd": float(r.get("pnl_usd", 0) or 0),
                        "pnl_ticks": float(r.get("pnl_ticks", 0) or 0),
                        "range_pos_at_entry": rp,
                    })
        except OSError:
            continue
    trades.sort(key=lambda t: t["ts"])
    print(f"  Total trades : {n_total} | LONG : {n_long} | LONG avec range_pos : {n_with_rp}")
    return trades


def split_folds_by_date(trades, n_folds=N_FOLDS):
    """Split trades en n_folds chronologiques par DATE (ml-trainer Q5).
    Distribue les dates entre folds pour repartition equilibree.
    """
    dates = sorted({t["date"] for t in trades if t["date"]})
    n_dates = len(dates)
    if n_dates < n_folds:
        # Fallback : split par index si moins de jours que folds
        fold_size = max(1, len(trades) // n_folds)
        return [trades[i*fold_size:(i+1)*fold_size if i<n_folds-1 else len(trades)]
                for i in range(n_folds)]
    dates_per_fold = n_dates // n_folds
    folds = []
    for i in range(n_folds):
        lo = i * dates_per_fold
        hi = (i + 1) * dates_per_fold if i < n_folds - 1 else n_dates
        fold_dates = set(dates[lo:hi])
        fold_trades = [t for t in trades if t["date"] in fold_dates]
        folds.append(fold_trades)
    return folds


def evaluate_threshold(trades, threshold):
    """Pour un threshold, retourne metriques + delta_per_trade list (pour DSR)."""
    blocked = [t for t in trades if t["range_pos_at_entry"] >= threshold]
    if not blocked:
        return {
            "n_blocked": 0, "tp_perdus": 0, "sl_evites": 0, "timeout_evites": 0,
            "delta_total_usd": 0.0, "delta_per_trade": [],
            "delta_timeout_usd": 0.0,
        }
    tp_perdus = sum(1 for t in blocked if t["outcome"] == "TP")
    sl_evites = sum(1 for t in blocked if t["outcome"] == "SL")
    timeout_evites = sum(1 for t in blocked if t["outcome"] == "TIMEOUT")
    # delta_per_trade : -pnl_usd (savings du filtre)
    delta_per_trade = [-t["pnl_usd"] for t in blocked]
    delta_total = sum(delta_per_trade)
    # ml-trainer Q6 : split TIMEOUT
    delta_timeout = sum(-t["pnl_usd"] for t in blocked if t["outcome"] == "TIMEOUT")
    return {
        "n_blocked": len(blocked),
        "tp_perdus": tp_perdus,
        "sl_evites": sl_evites,
        "timeout_evites": timeout_evites,
        "delta_total_usd": delta_total,
        "delta_per_trade": delta_per_trade,
        "delta_timeout_usd": delta_timeout,
    }


def walk_forward_with_dsr(trades, threshold, n_trials):
    """Walk-forward : DSR sur trades-blocked individuels (ml-trainer Q1+Q2).
    Folds = stat de stabilite (n_folds_positive, concentration).
    """
    folds = split_folds_by_date(trades, N_FOLDS)
    fold_metrics = []
    fold_deltas = []
    all_blocked_deltas = []  # toutes les savings individuelles
    for i, fold_tr in enumerate(folds):
        m = evaluate_threshold(fold_tr, threshold)
        m["fold"] = i + 1
        m["fold_n"] = len(fold_tr)
        fold_metrics.append(m)
        fold_deltas.append(m["delta_total_usd"])
        all_blocked_deltas.extend(m["delta_per_trade"])

    fold_deltas_arr = np.array(fold_deltas)
    n_folds_positive = int((fold_deltas_arr > 0).sum())
    if abs(fold_deltas_arr).sum() > 0:
        sorted_abs = np.sort(np.abs(fold_deltas_arr))[::-1]
        concentration_top2 = float(sorted_abs[:2].sum() / np.abs(fold_deltas_arr).sum())
    else:
        concentration_top2 = 0.0

    # DSR sur trades-blocked individuels (n=n_blocked_total)
    arr = np.array(all_blocked_deltas)
    n_blocked = len(arr)
    if n_blocked >= 10 and arr.std() > 1e-9:
        sharpe = arr.mean() / arr.std()
        sk = float(stats.skew(arr)) if n_blocked >= 4 else 0.0
        kt = float(stats.kurtosis(arr, fisher=False)) if n_blocked >= 4 else 3.0
        psr, dsr = deflated_sharpe(sharpe, n_blocked, sk, kt, n_trials)
    else:
        sharpe, psr, dsr = 0.0, None, None

    return {
        "threshold": threshold,
        "n_blocked_total": n_blocked,
        "delta_total_usd": float(arr.sum()),
        "delta_timeout_usd": sum(m["delta_timeout_usd"] for m in fold_metrics),
        "sl_evites_total": sum(m["sl_evites"] for m in fold_metrics),
        "tp_perdus_total": sum(m["tp_perdus"] for m in fold_metrics),
        "timeout_evites_total": sum(m["timeout_evites"] for m in fold_metrics),
        "fold_metrics": fold_metrics,
        "n_folds_positive": n_folds_positive,
        "concentration_top2": concentration_top2,
        "sharpe": float(sharpe) if sharpe else 0.0,
        "psr": psr,
        "dsr": dsr,
    }


def render_verdict(label, results_60, results_70):
    print(f"\n  {'='*80}")
    print(f"  VERDICT : {label}")
    print(f"  {'='*80}")
    print(f"  threshold | n_blocked | SL_ev | TP_pd | TIMEOUT | "
          f"delta_$ | delta_TIMEOUT_$ | Sharpe | DSR | folds+ | conc_top2")
    for r in (results_60, results_70):
        dsr_str = f"{r['dsr']:.3f}" if r['dsr'] is not None else "N/A"
        print(f"     {r['threshold']:3d}    |    {r['n_blocked_total']:3d}    |"
              f"  {r['sl_evites_total']:2d}   |  {r['tp_perdus_total']:2d}   |"
              f"   {r['timeout_evites_total']:2d}    | "
              f"${r['delta_total_usd']:+8.2f} | "
              f"${r['delta_timeout_usd']:+8.2f}     |"
              f" {r['sharpe']:+.3f} | {dsr_str:5s} |"
              f"  {r['n_folds_positive']}/{N_FOLDS}  |"
              f"  {r['concentration_top2']*100:5.1f}%")

    # Verdict criteria
    delta_diff = results_70['delta_total_usd'] - results_60['delta_total_usd']
    print(f"\n  Diff (70-60): ${delta_diff:+.2f}")
    crit = []
    if results_70['dsr'] is None:
        crit.append("FAIL: DSR_70 = None (n_blocked < 10 OR std=0)")
    elif results_70['dsr'] < DSR_MIN:
        crit.append(f"FAIL: DSR_70={results_70['dsr']:.3f} < {DSR_MIN}")
    if (results_60['dsr'] is not None and results_70['dsr'] is not None
            and results_70['dsr'] < results_60['dsr'] - DSR_DEGRADATION_TOLERANCE):
        crit.append(f"FAIL: DSR_70={results_70['dsr']:.3f} < DSR_60-{DSR_DEGRADATION_TOLERANCE}={results_60['dsr']-DSR_DEGRADATION_TOLERANCE:.3f}")
    if results_70['delta_total_usd'] <= 0:
        crit.append(f"FAIL: delta_70={results_70['delta_total_usd']:.2f} <= 0")
    if delta_diff <= 0:
        crit.append(f"FAIL: delta_diff={delta_diff:.2f} <= 0")
    if results_70['n_blocked_total'] < N_BLOCKED_MIN:
        crit.append(f"FAIL: n_blocked_70={results_70['n_blocked_total']} < {N_BLOCKED_MIN}")
    if results_70['n_folds_positive'] < N_FOLDS_POSITIVE_MIN:
        crit.append(f"FAIL: n_folds_positive_70={results_70['n_folds_positive']} < {N_FOLDS_POSITIVE_MIN}")
    if results_70['concentration_top2'] >= CONCENTRATION_TOP2_MAX:
        crit.append(f"FAIL: concentration_top2_70={results_70['concentration_top2']*100:.1f}% >= {CONCENTRATION_TOP2_MAX*100:.0f}%")

    if not crit:
        print(f"\n  >>> {label} : GO threshold 70 REPLACE 60 (tous criteres OK)")
        return True
    else:
        print(f"\n  >>> {label} : NOGO")
        for c in crit:
            print(f"      {c}")
        return False


def main():
    print("=" * 80)
    print("  AUDIT ChaseTopGate threshold 60 (deploy) vs 70 (Jackson 06/05)")
    print("  Methodologie corrigee post-review ml-trainer 06/05")
    print("=" * 80)

    trades_all = load_trades_with_range_pos()
    if len(trades_all) < 30:
        print(f"\n  NOGO : sample insuffisant ({len(trades_all)} LONG). Min 30.")
        return

    # Distribution
    rps = [t["range_pos_at_entry"] for t in trades_all]
    print(f"\n  range_pos at entry distribution (LONG n={len(rps)}):")
    print(f"    min={min(rps):.1f} max={max(rps):.1f} mean={np.mean(rps):.1f} median={np.median(rps):.1f}")
    for lo, hi in [(0, 59), (60, 69), (70, 79), (80, 89), (90, 99), (100, 100)]:
        n_in = sum(1 for r in rps if lo <= r <= hi)
        print(f"    [{lo}-{hi}]: {n_in} ({n_in/len(rps)*100:.1f}%)")

    # Outcome breakdown
    by_outcome = defaultdict(lambda: {"n": 0, "pnl_total": 0.0})
    for t in trades_all:
        by_outcome[t["outcome"]]["n"] += 1
        by_outcome[t["outcome"]]["pnl_total"] += t["pnl_usd"]
    print(f"\n  Outcome global LONG:")
    for o, d in sorted(by_outcome.items()):
        print(f"    {o}: n={d['n']} pnl_total=${d['pnl_total']:+.2f}")

    # Date span + folds par date
    dates = sorted({t["date"] for t in trades_all})
    print(f"\n  Date span: {dates[0]} -> {dates[-1]} ({len(dates)} jours)")

    # ============ 3 verdicts : ALL / NQ / ES (ml-trainer Q7) ============
    verdicts = {}
    for label, filter_fn in [
        ("ALL (NQ+ES)", lambda t: True),
        ("NQ-only", lambda t: t["sym"] == "NQ"),
        ("ES-only", lambda t: t["sym"] == "ES"),
    ]:
        sub = [t for t in trades_all if filter_fn(t)]
        if len(sub) < 20:
            print(f"\n  --- {label} : skip (n={len(sub)} < 20) ---")
            continue
        print(f"\n  --- {label} : n={len(sub)} ---")
        r60 = walk_forward_with_dsr(sub, 60, N_STRATEGIES)
        r70 = walk_forward_with_dsr(sub, 70, N_STRATEGIES)
        go = render_verdict(label, r60, r70)
        verdicts[label] = {"go": go, "r60": r60, "r70": r70}

    # ============ Synthese finale ============
    print(f"\n  {'='*80}")
    print(f"  SYNTHESE FINALE")
    print(f"  {'='*80}")
    for label, v in verdicts.items():
        status = "GO ✓" if v["go"] else "NOGO ✗"
        print(f"  {label:15s} : {status}")

    all_go = verdicts.get("ALL (NQ+ES)", {}).get("go", False)
    nq_go = verdicts.get("NQ-only", {}).get("go", False)
    es_go = verdicts.get("ES-only", {}).get("go", False)
    if all_go and nq_go and es_go:
        print(f"\n  >>> DEPLOY GO : threshold 70 valide sur ALL + NQ + ES")
    elif all_go and (nq_go or es_go):
        print(f"\n  >>> DEPLOY GO_PARTIEL : ALL OK mais asymetrie sym (deploy threshold per-sym ?)")
    else:
        print(f"\n  >>> DEPLOY NOGO : pas tous criteres remplis (cf details ci-dessus)")

    # Save report
    out_path = ROOT / "DATA" / f"audit_chase_top_70_vs_60_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    payload = {
        "n_trades": len(trades_all),
        "verdicts": {
            label: {
                "go": v["go"],
                "r60": {k: (v["r60"][k] if k != "fold_metrics" else None) for k in v["r60"]},
                "r70": {k: (v["r70"][k] if k != "fold_metrics" else None) for k in v["r70"]},
            } for label, v in verdicts.items()
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report sauve: {out_path}")


if __name__ == "__main__":
    main()
