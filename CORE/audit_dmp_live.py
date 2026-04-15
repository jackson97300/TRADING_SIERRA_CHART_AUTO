"""
audit_dmp_live.py — Audit exhaustif du DMP live (15/04/2026)
=============================================================

Objectif : rapport definitif de chaque feature du dumper live pour :
  1. Identifier ce qui marche vraiment (pas de decouverte accidentelle ulterieure)
  2. Lister les features mortes/cassees avec root cause probable
  3. Fournir une source de verite pour les futurs audits

Classification (5 categories) :
  - PROPRE          : varie normalement, exploitable par le ML
  - EVENT_BASED     : signal rare mais legitime (< 5% fire)
  - MORTE           : constant 0 ou uniq=1 sur toute la session
  - QUASI_CONSTANTE : top_value_freq > 95% (mais pas forcement 0)
  - OUTLIER         : NaN, Inf, ou distribution suspecte

Usage :
    python CORE/audit_dmp_live.py

Output :
    DATA/DMP_LIVE_VALIDATION_REPORT.md
"""

import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

REPO = Path(__file__).parent.parent
ES_PATH = REPO / "DATA/ES/20260415_ES.jsonl"
NQ_PATH = REPO / "DATA/NQ/20260415_NQ.jsonl"
OUTPUT = REPO / "DATA/DMP_LIVE_VALIDATION_REPORT.md"

# Meta colonnes (exclues de l'audit ML, ce sont des identifiants)
META_COLS = {"ts", "sym", "contract", "session", "session_id", "timestamp_ms"}

# Features binaires attendues (0/1, fire event-based)
EXPECTED_BINARY = {
    "bn_color_up", "bn_color_dn", "bn_color_up_2", "bn_color_dn_2",
    "bn_absorb_ask", "bn_absorb_bid",
    "bn_long_up", "bn_long_dn",
    "bn_pressure_ask", "bn_pressure_bid",
    "bn_volume_up", "bn_volume_dn",
    "fp_edge_buy", "fp_edge_sell",
    "bar_color_up", "bar_color_dn",
    "bar_long_up_bar", "bar_long_dn_bar",
    "bar_long_dn_up", "bar_long_up_dn",
    "bar_edge_buy", "bar_edge_sell",
    "bar_pressure_ask", "bar_pressure_bid",
    "delta_divergence",
    "new_swing_high", "new_swing_low",
    "retest_high_delta_div", "retest_low_delta_div",
    "ib_broken_up", "ib_broken_down", "ib_complete",
    "ib_is_narrow", "ib_is_wide",
    "is_rth_session",
    "rvol_buy", "rvol_sell", "rvol_buy_strong", "rvol_sell_strong",
    "rvol_absorb_buy", "rvol_absorb_sell", "rvol_extreme",
    "bool_above_cur_vpoc", "bool_above_prev_vpoc",
    "bool_above_vwap_d", "bool_above_vwap_w", "bool_above_vwap_m",
    "bool_above_mq_hvl", "bool_above_mq_call",
    "bool_near_level", "bool_ib_inside", "bool_session_early",
    "vwap_triple_align", "bool_va_confluence", "bool_gex_flip_zone",
    "open_in_prev_va", "inside_cur_va", "inside_prev_va",
    "inside_comp_20d_va", "inside_comp_50d_va",
    "comp_vpoc_align_20_50", "comp_vpoc_align_day_20",
    "vah_touches_20b", "val_touches_20b",
    "lvn_between", "hvn_between",
    "vwap_d_side", "vwap_w_side", "vwap_m_side",
    "next_wall_is_call",
    "is_double_dist",
    "vix_above_hvl", "vix_above_hvl_0dte",
    "rotation_up", "rotation_dn",
    "vwap_slope_10_dir",
    "ma_trend", "vwap_ma_align",
    "data_quality_ok",
    "poor_high", "poor_low",
    "amd_sweep_up", "amd_sweep_dn",
    "amd_manip_dir", "amd_judas_swing",
    "amd_po3_bullish", "amd_po3_bearish",
    "amd_session_bias",
    "rule_80pct",
    "open_direction",
}

# Features qui peuvent legitimement etre constantes sur une seule session
# (se calculent sur toute la journee / session, pas per-bar)
EXPECTED_SESSION_CONSTANT = {
    "atr", "ma_trend",  # daily
    "mq_call", "mq_put", "mq_hvl",  # daily MenthorQ
    "mq_call_0dte", "mq_put_0dte",
    "1d_max", "1d_min",  # daily levels
    "vix_call", "vix_put", "vix_hvl",  # VIX daily
    "vix_call_0dte", "vix_put_0dte", "vix_hvl_0dte",
    "open_cash", "open_830",
    "ovn_high", "ovn_low",
    "prev_vpoc", "prev_vah", "prev_val", "prev_vwap",
    "comp_20d_vpoc", "comp_20d_vah", "comp_20d_val", "comp_20d_vwap",
    "comp_50d_vpoc", "comp_50d_vah", "comp_50d_val", "comp_50d_vwap",
    "contract",
}

# Features dont le nom laisse penser event-based normal (rare by design)
EVENT_BASED_HINTS = (
    "swing", "retest", "absorb", "edge", "long_up", "long_dn",
    "color_up", "color_dn", "pressure", "volume_up", "volume_dn",
    "divergence", "sweep", "judas", "po3", "rvol_buy", "rvol_sell",
    "rvol_absorb", "rvol_extreme",
)


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════════════════

def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return pd.DataFrame(rows)


def classify_feature(name: str, series: pd.Series, is_binary_expected: bool) -> dict:
    """Classifie une feature en PROPRE / EVENT_BASED / MORTE / QUASI_CONSTANTE / OUTLIER."""
    # Conversion numerique si possible
    try:
        col = pd.to_numeric(series, errors="coerce")
    except Exception:
        return {
            "category": "NON_NUMERIC",
            "reason": "colonne non convertible",
            "stats": {},
        }

    n = len(col)
    n_nan = col.isna().sum()
    n_inf = np.isinf(col.fillna(0)).sum()
    col_clean = col.fillna(0)
    uniq = col_clean.nunique()

    # Outliers : NaN ou Inf
    if n_nan > 0 and not (n_nan == n):  # NaN partiels
        nan_rate = n_nan / n
        if nan_rate > 0.1:
            return {
                "category": "OUTLIER",
                "reason": f"{nan_rate*100:.1f}% NaN",
                "stats": {"n_nan": int(n_nan), "n": n},
            }
    if n_inf > 0:
        return {
            "category": "OUTLIER",
            "reason": f"{n_inf} Inf",
            "stats": {"n_inf": int(n_inf), "n": n},
        }

    # Tout NaN = morte
    if n_nan == n:
        return {
            "category": "MORTE",
            "reason": "100% NaN",
            "stats": {"n": n},
        }

    # Stats de base
    vmin = float(col_clean.min())
    vmax = float(col_clean.max())
    vmean = float(col_clean.mean())
    vstd = float(col_clean.std())

    # Top value frequency
    vc = col_clean.value_counts(normalize=True)
    top_value = float(vc.index[0]) if len(vc) > 0 else 0.0
    top_freq = float(vc.iloc[0]) if len(vc) > 0 else 1.0

    # Fire rate (% non-zero)
    nz = int((col_clean != 0).sum())
    fire_rate = nz / n

    stats = {
        "min": vmin, "max": vmax, "mean": vmean, "std": vstd,
        "uniq": int(uniq), "fire_rate": fire_rate,
        "top_value": top_value, "top_freq": top_freq,
        "n_nan": int(n_nan), "n": n,
    }

    # 1. MORTE : uniq == 1 OU fire_rate = 0 (pour binaires attendus)
    if uniq == 1:
        return {
            "category": "MORTE",
            "reason": f"constant = {top_value}",
            "stats": stats,
        }

    # 2. QUASI-CONSTANTE : 1 valeur domine à > 99% (strict)
    if top_freq > 0.99:
        return {
            "category": "QUASI_CONSTANTE",
            "reason": f"top_value {top_value} freq {top_freq*100:.1f}%",
            "stats": stats,
        }

    # 3. Classification selon type (binaire vs numerique)
    if is_binary_expected or (uniq <= 3 and set(col_clean.unique()).issubset({0, 1, -1})):
        # Binaire : analyse par fire rate
        if fire_rate == 0:
            return {
                "category": "MORTE",
                "reason": "0% fire",
                "stats": stats,
            }
        if fire_rate < 0.05:
            return {
                "category": "EVENT_BASED",
                "reason": f"fire {fire_rate*100:.2f}% (rare, legitime)",
                "stats": stats,
            }
        if fire_rate > 0.95:
            return {
                "category": "QUASI_CONSTANTE",
                "reason": f"fire {fire_rate*100:.1f}% (quasi tout le temps actif)",
                "stats": stats,
            }
        return {
            "category": "PROPRE",
            "reason": f"binaire fire {fire_rate*100:.1f}%",
            "stats": stats,
        }

    # 4. Numerique : analyse par std / distribution
    if vstd < 1e-9:
        return {
            "category": "MORTE",
            "reason": f"std {vstd:.2e} quasi-zero",
            "stats": stats,
        }

    # Coefficient de variation (std/|mean|)
    if abs(vmean) > 1e-6:
        cv = vstd / abs(vmean)
    else:
        cv = vstd  # fallback

    if uniq <= 5 and top_freq > 0.90:
        return {
            "category": "QUASI_CONSTANTE",
            "reason": f"uniq={uniq} top_freq={top_freq*100:.0f}%",
            "stats": stats,
        }

    return {
        "category": "PROPRE",
        "reason": f"std={vstd:.4f} uniq={uniq}",
        "stats": stats,
    }


def audit_dataset(df: pd.DataFrame, label: str) -> list:
    """Audit complet d'un dataset live."""
    results = []
    for col in df.columns:
        if col in META_COLS:
            continue
        is_binary = col in EXPECTED_BINARY
        result = classify_feature(col, df[col], is_binary)
        result["name"] = col
        result["is_binary_expected"] = is_binary
        results.append(result)
    return results


def summarize(results: list) -> dict:
    """Statistiques globales."""
    cats = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r["name"])
    return cats


# ═══════════════════════════════════════════════════════════════════════════
# RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(es_results: list, nq_results: list,
                    es_df: pd.DataFrame, nq_df: pd.DataFrame) -> str:
    """Genere le rapport markdown."""
    es_cats = summarize(es_results)
    nq_cats = summarize(nq_results)

    lines = []
    lines.append("# DMP Live Validation Report — 15/04/2026")
    lines.append("")
    lines.append(f"**Genere le** : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Source ES** : `{ES_PATH.name}` — {len(es_df)} barres")
    lines.append(f"**Source NQ** : `{NQ_PATH.name}` — {len(nq_df)} barres")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append("Apres la spirale de decouverte de bugs dumper (delta_divergence, big_orders,")
    lines.append("MenthorQ, bn_absorb, fp_edge, bar_edge, arr[sz-1], Number of Bars to Calculate),")
    lines.append("ce rapport constitue la **source de verite** definitive pour les features du")
    lines.append("DMP live apres tous les fixes appliques (07/04, 13/04, 14/04, 15/04).")
    lines.append("")
    lines.append("Objectif : zero decouverte accidentelle ulterieure. Toute feature non listee")
    lines.append("comme PROPRE ou EVENT_BASED doit etre consideree comme connue et documentee ici.")
    lines.append("")

    # Vue d'ensemble
    lines.append("## Vue d'ensemble")
    lines.append("")
    lines.append("| Categorie | ES | NQ |")
    lines.append("|---|---|---|")
    all_cats = sorted(set(es_cats.keys()) | set(nq_cats.keys()))
    for cat in ["PROPRE", "EVENT_BASED", "QUASI_CONSTANTE", "MORTE", "OUTLIER", "NON_NUMERIC"]:
        if cat not in all_cats:
            continue
        es_n = len(es_cats.get(cat, []))
        nq_n = len(nq_cats.get(cat, []))
        lines.append(f"| **{cat}** | {es_n} | {nq_n} |")
    lines.append("")

    # Section divergente : feature morte ES mais vivante NQ (ou vice versa)
    es_map = {r["name"]: r for r in es_results}
    nq_map = {r["name"]: r for r in nq_results}
    divergent = []
    for name in set(es_map) & set(nq_map):
        e = es_map[name]
        n = nq_map[name]
        if e["category"] != n["category"]:
            divergent.append((name, e["category"], n["category"]))

    if divergent:
        lines.append("## ⚠️ Features avec comportement divergent ES vs NQ")
        lines.append("")
        lines.append("| Feature | Categorie ES | Categorie NQ |")
        lines.append("|---|---|---|")
        for name, es_cat, nq_cat in sorted(divergent):
            lines.append(f"| `{name}` | {es_cat} | {nq_cat} |")
        lines.append("")

    # Section categorie par categorie
    for cat, title, emoji in [
        ("MORTE", "Features MORTES", "🔴"),
        ("QUASI_CONSTANTE", "Features QUASI-CONSTANTES", "⚠️"),
        ("OUTLIER", "Features OUTLIERS", "🚨"),
        ("EVENT_BASED", "Features EVENT-BASED (rare, legitime)", "⚡"),
        ("PROPRE", "Features PROPRES (variation normale)", "✅"),
    ]:
        if not (es_cats.get(cat) or nq_cats.get(cat)):
            continue
        lines.append(f"## {emoji} {title}")
        lines.append("")
        union = sorted(set(es_cats.get(cat, [])) | set(nq_cats.get(cat, [])))
        if not union:
            lines.append("_(aucune)_")
            lines.append("")
            continue
        lines.append("| Feature | Raison ES | Raison NQ |")
        lines.append("|---|---|---|")
        for name in union:
            es_info = es_map.get(name, {})
            nq_info = nq_map.get(name, {})
            es_r = es_info.get("reason", "-") if es_info.get("category") == cat else "-"
            nq_r = nq_info.get("reason", "-") if nq_info.get("category") == cat else "-"
            lines.append(f"| `{name}` | {es_r} | {nq_r} |")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print(f"Loading ES : {ES_PATH}")
    es_df = load_jsonl(ES_PATH)
    print(f"  {len(es_df)} barres, {es_df.shape[1]} colonnes")

    print(f"Loading NQ : {NQ_PATH}")
    nq_df = load_jsonl(NQ_PATH)
    print(f"  {len(nq_df)} barres, {nq_df.shape[1]} colonnes")

    print("\nAudit ES...")
    es_results = audit_dataset(es_df, "ES")
    es_cats = summarize(es_results)

    print("Audit NQ...")
    nq_results = audit_dataset(nq_df, "NQ")
    nq_cats = summarize(nq_results)

    print("\n=== RESUME ===")
    print(f"{'Categorie':<20} {'ES':<6} {'NQ':<6}")
    for cat in ["PROPRE", "EVENT_BASED", "QUASI_CONSTANTE", "MORTE", "OUTLIER", "NON_NUMERIC"]:
        es_n = len(es_cats.get(cat, []))
        nq_n = len(nq_cats.get(cat, []))
        if es_n + nq_n > 0:
            print(f"  {cat:<18} {es_n:>4}   {nq_n:>4}")

    report = generate_report(es_results, nq_results, es_df, nq_df)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"\nRapport ecrit : {OUTPUT}")
    print(f"  {len(report.splitlines())} lignes")


if __name__ == "__main__":
    main()
