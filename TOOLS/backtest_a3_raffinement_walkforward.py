"""Backtest 2 (raffinement A3) + Backtest 3 (walk-forward 4-fold).

Backtest 2 : tester 6 variantes pour booster |rho| de A3 baseline (0.20)
Backtest 3 : walk-forward 4-fold sur best variante pour confirmer stabilite

Output : DOCS/BACKTEST_A3_RAFFINEMENT.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR_NQ = ROOT / "DATA" / "live_enriched" / "NQ"
DATA_DIR_ES = ROOT / "DATA" / "live_enriched" / "ES"
OUT = ROOT / "DOCS" / "BACKTEST_A3_RAFFINEMENT.md"

FORWARD_LABEL = 60  # bars


def load_day(fp: Path) -> pd.DataFrame:
    bars = []
    with open(fp, "r", encoding="utf-8") as fh:
        for line in fh:
            try: bars.append(json.loads(line))
            except: pass
    df = pd.DataFrame(bars)
    if df.empty: return df
    if "ts" in df.columns:
        df["ts_event"] = pd.to_datetime(df["ts"], utc=True, unit="ms")
        df["ts_et"] = df["ts_event"].dt.tz_convert("America/New_York")
        df["mins_et"] = df["ts_et"].dt.hour * 60 + df["ts_et"].dt.minute
    for col in ("close", "delta_bar", "atr", "atr_14m", "vwap_slope_10",
                "n_big_ask_t1", "n_big_bid_t1", "cvd_day", "cvd_day_dir",
                "cvd_session", "range_pos", "single_print_count",
                "dist_pdh_pct", "dist_pdl_pct", "delta_day"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def compute_variants(df: pd.DataFrame) -> pd.DataFrame:
    """6 variantes A3 raffinees."""
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns or "atr" not in df.columns:
        return out

    # Components base
    mom_5 = (df["close"] - df["close"].shift(5)) / df["atr"]
    mom_20 = (df["close"] - df["close"].shift(20)) / df["atr"]
    mom_60 = (df["close"] - df["close"].shift(60)) / df["atr"]
    coh = np.sign(mom_5) * np.sign(mom_20) * np.sign(mom_60)
    mag = (mom_5.abs() + mom_20.abs() + mom_60.abs()) / 3

    vs = df.get("vwap_slope_10", pd.Series(0, index=df.index)).fillna(0)
    vwap_sign = np.sign(vs)

    if "atr_14m" in df.columns:
        atr_long = df["atr_14m"].rolling(120, min_periods=30).mean()
        range_exp = (df["atr_14m"] / atr_long.clip(lower=0.1) - 1).clip(-1, 2)
    else:
        range_exp = pd.Series(0, index=df.index)

    near_pdh = (df.get("dist_pdh_pct", pd.Series(99, index=df.index)).fillna(99).abs() < 0.2).astype(float)
    near_pdl = (df.get("dist_pdl_pct", pd.Series(99, index=df.index)).fillna(99).abs() < 0.2).astype(float)
    near_key = (near_pdh + near_pdl).clip(0, 1)

    # V1 : Baseline A3 (deja teste rho 0.20)
    out["V1_baseline"] = (
        coh * mag * 0.4 +
        vwap_sign * mag.clip(upper=2) * 0.3 +
        range_exp.fillna(0) * np.sign(mom_20) * 0.2 +
        (1 - near_key) * np.sign(mom_20) * 0.1
    )

    # V2 : V1 + delta_bar persistence (% bars positifs sur 20)
    if "delta_bar" in df.columns:
        delta_pers = (df["delta_bar"] > 0).rolling(20, min_periods=10).mean() - 0.5  # [-0.5, +0.5]
        out["V2_with_delta_pers"] = (
            coh * mag * 0.35 +
            vwap_sign * mag.clip(upper=2) * 0.25 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.15 +
            (1 - near_key) * np.sign(mom_20) * 0.05 +
            delta_pers * 2 * np.sign(mom_20) * 0.2  # nouveau
        )

    # V3 : V1 + big_spawn_rate (% bars avec big_ask spawn)
    if "n_big_ask_t1" in df.columns and "n_big_bid_t1" in df.columns:
        big_diff = (df["n_big_ask_t1"] - df["n_big_bid_t1"]).rolling(20, min_periods=10).mean()
        big_diff_norm = big_diff / (df["n_big_ask_t1"] + df["n_big_bid_t1"]).rolling(20, min_periods=10).mean().clip(lower=1)
        out["V3_with_big_spawn"] = (
            coh * mag * 0.35 +
            vwap_sign * mag.clip(upper=2) * 0.25 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.15 +
            (1 - near_key) * np.sign(mom_20) * 0.05 +
            big_diff_norm.fillna(0).clip(-1, 1) * np.sign(mom_20) * 0.2
        )

    # V4 : V1 + CVD session direction
    if "cvd_session" in df.columns:
        cvd_sess = df["cvd_session"]
        cvd_norm = np.sign(cvd_sess) * np.log1p(cvd_sess.abs() / 100).clip(upper=5) / 5
        out["V4_with_cvd_session"] = (
            coh * mag * 0.3 +
            vwap_sign * mag.clip(upper=2) * 0.25 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.15 +
            (1 - near_key) * np.sign(mom_20) * 0.05 +
            cvd_norm.fillna(0) * 0.25  # CVD a un poids important
        )

    # V5 : V1 + range_pos position dans VA (Sierra sain)
    if "range_pos" in df.columns:
        rp = df["range_pos"].fillna(0.5)
        # extremes (>0.8 ou <0.2) = signal mean rev probable
        extremes = ((rp - 0.5).abs() - 0.3).clip(lower=0) * 2  # [0, +0.4]
        # Signe extreme inverse au momentum dominant
        out["V5_with_range_pos"] = (
            coh * mag * 0.35 +
            vwap_sign * mag.clip(upper=2) * 0.25 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.15 +
            (1 - near_key) * np.sign(mom_20) * 0.05 +
            extremes * np.sign(mom_20) * 0.2  # bonus si en extremes ET aligned trend
        )

    # V6 : MIX BEST (poids optimises empiriquement)
    if "delta_bar" in df.columns and "cvd_session" in df.columns and "range_pos" in df.columns:
        delta_pers = (df["delta_bar"] > 0).rolling(20, min_periods=10).mean() - 0.5
        cvd_sess = df["cvd_session"]
        cvd_norm = np.sign(cvd_sess) * np.log1p(cvd_sess.abs() / 100).clip(upper=5) / 5
        rp = df["range_pos"].fillna(0.5)
        extremes = ((rp - 0.5).abs() - 0.3).clip(lower=0) * 2
        out["V6_mix_best"] = (
            coh * mag * 0.30 +
            vwap_sign * mag.clip(upper=2) * 0.20 +
            range_exp.fillna(0) * np.sign(mom_20) * 0.10 +
            (1 - near_key) * np.sign(mom_20) * 0.05 +
            delta_pers * 2 * np.sign(mom_20) * 0.15 +
            cvd_norm.fillna(0) * 0.15 +
            extremes * np.sign(mom_20) * 0.05
        )

    return out


def evaluate_day(df: pd.DataFrame) -> Dict[str, float]:
    """Spearman vs forward 60."""
    if df.empty or "close" not in df.columns:
        return {}
    feats = compute_variants(df)
    if feats.empty: return {}

    if "mins_et" in df.columns:
        mask_rth = (df.mins_et >= 570) & (df.mins_et < 960)
    else:
        mask_rth = pd.Series(True, index=df.index)

    label = df["close"].shift(-FORWARD_LABEL) - df["close"]
    out = {}
    for col in feats.columns:
        sub = feats[mask_rth].join(label.rename("y"), how="inner").dropna(subset=[col, "y"])
        if len(sub) < 30: continue
        try:
            rho = sub[col].rank().corr(sub["y"].rank())
            out[col] = float(rho)
        except Exception:
            pass
    return out


def run_backtest(files: List[Path], symbol_label: str) -> pd.DataFrame:
    """Run backtest et retourne DataFrame daily."""
    print(f"=== Run backtest {symbol_label} sur {len(files)} jours ===")
    daily = []
    for i, fp in enumerate(files):
        try:
            df = load_day(fp)
            if df.empty: continue
            stats = evaluate_day(df)
            if stats:
                stats["day"] = fp.stem.split("_")[0]
                stats["symbol"] = symbol_label
                daily.append(stats)
        except Exception as e:
            pass
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{len(files)} jours...")
    return pd.DataFrame(daily)


def walk_forward_4fold(d: pd.DataFrame, best_variant: str) -> Dict:
    """Walk-forward 4 folds sur best variante."""
    d_sorted = d.sort_values("day").reset_index(drop=True)
    n = len(d_sorted)
    quarter = n // 4
    folds = {}
    for q in range(4):
        lo = q * quarter
        hi = (q+1) * quarter if q < 3 else n
        sub = d_sorted.iloc[lo:hi].dropna(subset=[best_variant])
        if len(sub) < 10:
            folds[f"Q{q+1}"] = None
            continue
        rho = float(sub[best_variant].mean())
        rho_med = float(sub[best_variant].median())
        sig_pct = round(100 * (sub[best_variant].abs() > 0.1).sum() / len(sub), 1)
        folds[f"Q{q+1}"] = {
            "n_days": len(sub),
            "rho_mean": round(rho, 4),
            "rho_median": round(rho_med, 4),
            "sig_pct": sig_pct,
            "day_first": sub.day.iloc[0],
            "day_last": sub.day.iloc[-1],
        }
    return folds


def main():
    # NQ
    files_nq = sorted(DATA_DIR_NQ.glob("*_NQ.jsonl"))[-100:]
    d_nq = run_backtest(files_nq, "NQ")
    print(f"  NQ : {len(d_nq)} jours exploitables")

    # ES (si dispo)
    if DATA_DIR_ES.exists():
        files_es = sorted(DATA_DIR_ES.glob("*_ES.jsonl"))[-100:]
        d_es = run_backtest(files_es, "ES") if files_es else pd.DataFrame()
        print(f"  ES : {len(d_es)} jours exploitables")
    else:
        d_es = pd.DataFrame()

    # === Backtest 2 : raffinement ===
    print("\n=== Backtest 2 : Raffinement A3 variantes ===")
    variants = [c for c in d_nq.columns if c.startswith("V")]
    summary_nq = []
    for v in variants:
        s = d_nq[v].dropna()
        if len(s) < 10: continue
        summary_nq.append({
            "variant": v,
            "n_days_nq": len(s),
            "rho_mean_nq": round(float(s.mean()), 4),
            "rho_median_nq": round(float(s.median()), 4),
            "abs_rho_nq": round(float(s.abs().mean()), 4),
            "sig_pct_nq": round(100 * (s.abs() > 0.1).sum() / len(s), 1),
        })

    if not d_es.empty:
        for row in summary_nq:
            s_es = d_es[row["variant"]].dropna() if row["variant"] in d_es.columns else pd.Series([])
            if len(s_es) >= 10:
                row["rho_mean_es"] = round(float(s_es.mean()), 4)
                row["abs_rho_es"] = round(float(s_es.abs().mean()), 4)
                row["sig_pct_es"] = round(100 * (s_es.abs() > 0.1).sum() / len(s_es), 1)
            else:
                row["rho_mean_es"] = None

    summary_df = pd.DataFrame(summary_nq).sort_values("abs_rho_nq", ascending=False)
    print(summary_df.to_string(index=False))

    # === Backtest 3 : walk-forward 4-fold ===
    print("\n=== Backtest 3 : Walk-forward 4-fold ===")
    best_variant = summary_df.iloc[0]["variant"]
    folds_nq = walk_forward_4fold(d_nq, best_variant)
    print(f"  Best variante : {best_variant}")
    for q, info in folds_nq.items():
        if info:
            print(f"    {q} (n={info['n_days']}, {info['day_first']}->{info['day_last']}) : rho={info['rho_mean']:+.3f} sig={info['sig_pct']}%")

    # Rapport
    md = []
    md.append("# Backtest 2 Raffinement + Backtest 3 Walk-forward")
    md.append("")
    md.append(f"**Date** : 2026-06-07")
    md.append(f"**Mode** : FULL REGLES (pas de ML)")
    md.append(f"**NQ jours** : {len(d_nq)}")
    md.append(f"**ES jours** : {len(d_es)}")
    md.append(f"**Label** : forward {FORWARD_LABEL} bars (close[t+{FORWARD_LABEL}] - close[t])")
    md.append("")
    md.append("## Backtest 2 — Raffinement A3 (6 variantes)")
    md.append("")
    md.append("Variantes testees :")
    md.append("- V1 : Baseline A3 (Multi-temporal momentum + Confluence)")
    md.append("- V2 : V1 + delta_bar persistence (% bars positifs sur 20)")
    md.append("- V3 : V1 + big_spawn_rate (n_big_ask - n_big_bid normalise)")
    md.append("- V4 : V1 + cvd_session direction (log-scaled)")
    md.append("- V5 : V1 + range_pos extremes (Sierra sain)")
    md.append("- V6 : MIX BEST (combinaison V2+V3+V4+V5)")
    md.append("")
    md.append("### Resultats NQ + ES")
    md.append("")
    if "rho_mean_es" in summary_df.columns:
        md.append("| Variant | n_NQ | rho_NQ | |rho|_NQ | sig% NQ | n_ES | rho_ES | |rho|_ES | sig% ES |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for _, r in summary_df.iterrows():
            es_n = r.get("rho_mean_es", "N/A")
            es_abs = r.get("abs_rho_es", "N/A")
            es_sig = r.get("sig_pct_es", "N/A")
            md.append(f"| `{r.variant}` | {r.n_days_nq} | {r.rho_mean_nq} | {r.abs_rho_nq} | {r.sig_pct_nq}% | - | {es_n} | {es_abs} | {es_sig}{'%' if es_sig != 'N/A' else ''} |")
    else:
        md.append("| Variant | n_NQ | rho_NQ | |rho|_NQ | sig% NQ |")
        md.append("|---|---|---|---|---|")
        for _, r in summary_df.iterrows():
            md.append(f"| `{r.variant}` | {r.n_days_nq} | {r.rho_mean_nq} | {r.abs_rho_nq} | {r.sig_pct_nq}% |")
    md.append("")
    md.append(f"**BEST** : `{best_variant}` (|rho| = {summary_df.iloc[0].abs_rho_nq})")
    md.append("")

    md.append("## Backtest 3 — Walk-forward 4-fold NQ")
    md.append("")
    md.append(f"Best variante teste : `{best_variant}`")
    md.append("")
    md.append("| Fold | Periode | n_days | rho_mean | rho_median | sig% (>0.1) |")
    md.append("|---|---|---|---|---|---|")
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        info = folds_nq.get(q)
        if info:
            md.append(f"| {q} | {info['day_first']}->{info['day_last']} | {info['n_days']} | {info['rho_mean']} | {info['rho_median']} | {info['sig_pct']}% |")
    md.append("")

    # Verdict stabilite
    rhos = [info["rho_mean"] for info in folds_nq.values() if info]
    if rhos:
        rho_min = min(rhos)
        rho_max = max(rhos)
        rho_range = rho_max - rho_min
        if all(abs(r) > 0.10 for r in rhos):
            md.append("✅ **STABLE** : tous les 4 folds ont |rho| > 0.10")
        elif sum(abs(r) > 0.10 for r in rhos) >= 3:
            md.append("⚠️ **PARTIEL** : 3/4 folds significatifs, 1 fold faible")
        else:
            md.append("❌ **INSTABLE** : moins de 3 folds significatifs")
        md.append(f"\nRange rho : [{rho_min:+.3f}, {rho_max:+.3f}], variance = {rho_range:.3f}")
    md.append("")

    md.append("## Verdict global")
    md.append("")
    if rhos and all(abs(r) > 0.10 for r in rhos) and summary_df.iloc[0].abs_rho_nq > 0.15:
        md.append(f"🎯 **L'ELUE TROUVEE** : `{best_variant}`")
        md.append(f"- |rho|_mean global = {summary_df.iloc[0].abs_rho_nq}")
        md.append(f"- Stable sur 4 folds (variance {rho_range:.3f})")
        md.append("- DEPLOYABLE comme gate Bot 2/3")
    elif summary_df.iloc[0].abs_rho_nq > 0.15:
        md.append(f"⚠️ **CANDIDATE** : `{best_variant}` solide global mais instabilite cross-period.")
    else:
        md.append("❌ **NOGO** : aucune variante > 0.15 globally, redesign requis.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"\n=== Rapport ecrit : {OUT} ===")


if __name__ == "__main__":
    main()
