"""level_probability_analyzer.py — Analyse probabilite de rejection par niveau.

Created : 2026-05-02 dimanche soir.
Source : DATA/NQ/*.jsonl ou DATA/ES/*.jsonl (DMP Sierra Chart)

OBJECTIF : pour chaque niveau cle, mesurer empiriquement la probabilite que
le prix REJECTE (revient) vs BREAKOUT (continue) apres une touche.

NIVEAUX TESTES (16 + MenthorQ) :

  PREVIOUS DAY (5) :
    PVPOC, PVAH, PVAL, PDH, PDL

  VWAP DAILY (5) :
    PVWAP_D, PVWAP_SD1U, PVWAP_SD1D, PVWAP_SD2U, PVWAP_SD2D

  CURRENT DAY (6) :
    CUR_VPOC, CUR_VAH, CUR_VAL, IB_HIGH, IB_LOW, OPEN_CASH

  MENTHORQ OPTIONS (jackson 02/05) :
    MQ_CALL, MQ_PUT, MQ_HVL, GEX_UP, GEX_DN, BLIND_UP, BLIND_DN

POUR CHAQUE NIVEAU :
  - touch_threshold : prix dans X ticks du niveau
  - rejection : forward return signale dans le sens du retour (vs touche depuis lequel cote)
  - breakout : forward return signale dans le sens de la cassure
  - rejection_rate, avg_rejection_move, PF par niveau

STRATIFICATION CONTEXTUELLE :
  - session : Asia / London / RTH_US / After_Hours_US
  - delta direction : delta_day_dir +1 / -1 / 0
  - rvol regime : low (<0.7) / normal (0.7-1.3) / high (>1.3)
  - vix regime : low (<15) / mid (15-22) / high (>22)

Usage :
  python -X utf8 CORE/research/level_probability_analyzer.py \\
    --data-dir DATA/NQ \\
    --symbol NQ \\
    --horizon 30 \\
    --min-n 10 \\
    --output DOCS/LEVEL_PROB_NQ.md
"""
from __future__ import annotations
import argparse
import glob
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = 0.25


# ═══════════════════════════════════════════════════════════════════
# DEFINITIONS NIVEAUX
# ═══════════════════════════════════════════════════════════════════

# Liste : (level_name, dmp_dist_col, group, side_anchor)
# side_anchor : "above" = niveau de resistance (price > level => SHORT possible)
#               "below" = niveau de support (price < level => LONG possible)
#               "both"  = niveau peut etre testé des 2 cotes
LEVELS = [
    # Previous day
    ("PVPOC",        "dist_prev_vpoc",         "PREV_DAY",   "both"),
    ("PVAH",         "dist_prev_vah",          "PREV_DAY",   "above"),
    ("PVAL",         "dist_prev_val",          "PREV_DAY",   "below"),
    # PDH/PDL : pas dans DMP standard. Approx via dist_prev_vah/val ou dist_sess_high
    # On utilisera dist_sess_high/low pour current day, et prev_vah/val proxies prev day
    # VWAP daily
    ("PVWAP_D",      "dist_vwap_d",            "VWAP",       "both"),
    ("PVWAP_SD1U",   "dist_vwap_d_sd1u",       "VWAP",       "above"),
    ("PVWAP_SD1D",   "dist_vwap_d_sd1d",       "VWAP",       "below"),
    ("PVWAP_SD2U",   "dist_vwap_d_sd2u",       "VWAP",       "above"),
    ("PVWAP_SD2D",   "dist_vwap_d_sd2d",       "VWAP",       "below"),
    # Current day
    ("CUR_VPOC",     "dist_cur_vpoc",          "CUR_DAY",    "both"),
    ("CUR_VAH",      "dist_cur_vah",           "CUR_DAY",    "above"),
    ("CUR_VAL",      "dist_cur_val",           "CUR_DAY",    "below"),
    ("IB_HIGH",      "dist_ib_high",           "CUR_DAY",    "above"),
    ("IB_LOW",       "dist_ib_low",            "CUR_DAY",    "below"),
    ("OPEN_CASH",    "dist_open_cash",         "CUR_DAY",    "both"),
    # MenthorQ options (Jackson 02/05 : PVWAP puissant, MQ aussi)
    ("MQ_CALL",      "dist_mq_call",           "MQ",         "above"),
    ("MQ_PUT",       "dist_mq_put",            "MQ",         "below"),
    ("MQ_HVL",       "dist_mq_hvl",            "MQ",         "both"),
    ("GEX_UP",       "dist_gex_nearest_up",    "MQ",         "above"),
    ("GEX_DN",       "dist_gex_nearest_dn",    "MQ",         "below"),
]

TOUCH_THRESHOLD_TICKS = 5  # 5 ticks autour du niveau = "touche"


# ═══════════════════════════════════════════════════════════════════
# CHARGEMENT DATA
# ═══════════════════════════════════════════════════════════════════

def load_jsonl_data(data_dir: str, symbol: str) -> pd.DataFrame:
    """Charge tous les JSONL DMP du dossier."""
    patterns = [f"{data_dir}/*_{symbol}.jsonl"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files))
    # Filter out _PRE_FIX, _v2, _fresh, _live, etc. (variantes)
    files = [f for f in files if "_PRE_FIX" not in f and "_v2" not in f
             and "_fresh" not in f and "_live" not in f]
    if not files:
        print(f"[ERROR] Aucun JSONL trouve dans {data_dir} pour {symbol}")
        return pd.DataFrame()
    print(f"[load] {len(files)} fichiers JSONL pour {symbol}")
    bars = []
    for fp in files:
        try:
            with open(fp) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    bars.append(json.loads(line))
        except Exception as e:
            print(f"  [WARN] {fp}: {e}")
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.sort_values("ts_dt").reset_index(drop=True)
    df["session_date"] = df["ts_dt"].dt.date
    print(f"[load] {len(df)} barres, {df['session_date'].nunique()} jours")
    return df


# ═══════════════════════════════════════════════════════════════════
# FORWARD MOVES
# ═══════════════════════════════════════════════════════════════════

def add_forward_moves(df: pd.DataFrame, horizon: int = 30) -> pd.DataFrame:
    """Calcule fwd_<H>m_ticks par session (anti cross-session bug)."""
    out = df.copy()
    col = f"fwd_{horizon}m_ticks"
    out[col] = np.nan
    for date, group in out.groupby("session_date"):
        idx = group.index
        price = group["price"].values
        fwd = np.full(len(price), np.nan)
        for i in range(len(price) - horizon):
            fwd[i] = (price[i + horizon] - price[i]) / TICK_SIZE
        out.loc[idx, col] = fwd
    return out


# ═══════════════════════════════════════════════════════════════════
# CONTEXT LABELS
# ═══════════════════════════════════════════════════════════════════

def session_label(hour_utc: int) -> str:
    if 23 <= hour_utc or hour_utc < 7:
        return "ASIA"
    if 7 <= hour_utc < 13:
        return "LONDON"
    if (hour_utc == 13 and 30 <= hour_utc) or (14 <= hour_utc < 20):
        return "RTH_US"
    return "AFTER_HOURS_US"


def session_label_full(ts_dt) -> str:
    h = ts_dt.hour
    m = ts_dt.minute
    if 23 <= h or h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "LONDON"
    if (h == 13 and m >= 30) or (14 <= h < 20):
        return "RTH_US"
    if 20 <= h < 23:
        return "AFTER_HOURS_US"
    return "LONDON"  # 13:00-13:30 = end London


def add_context_labels(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sess"] = out["ts_dt"].apply(session_label_full)
    # Delta direction
    if "delta_day_dir" in out.columns:
        out["dd"] = out["delta_day_dir"].fillna(0).astype(int)
    else:
        out["dd"] = 0
    # RVOL regime
    if "rvol" in out.columns:
        rvol = out["rvol"].fillna(0)
        out["rvol_reg"] = pd.cut(rvol, [-1, 0.7, 1.3, 100],
                                   labels=["low", "normal", "high"])
    else:
        out["rvol_reg"] = "normal"
    # VIX regime
    if "vix_level" in out.columns:
        vix = out["vix_level"].fillna(20)
        out["vix_reg"] = pd.cut(vix, [-1, 15, 22, 100],
                                  labels=["low", "mid", "high"])
    else:
        out["vix_reg"] = "mid"
    return out


# ═══════════════════════════════════════════════════════════════════
# DETECTION TOUCHES + REJECTION/BREAKOUT
# ═══════════════════════════════════════════════════════════════════

def detect_level_touches(df: pd.DataFrame, level_name: str, dist_col: str,
                         side_anchor: str, horizon: int,
                         threshold_ticks: int = TOUCH_THRESHOLD_TICKS) -> pd.DataFrame:
    """Pour un niveau donne, retourne les bars 'touch' et leur outcome.

    Rejection definition selon le cote :
      - side_anchor=="above" : touch = price s'approche de level d'en bas (dist > 0).
        Rejection = price baisse (fwd < 0) apres touch.
        Breakout = price monte (fwd > 0).
      - side_anchor=="below" : touch = price s'approche de level d'en haut (dist < 0).
        Rejection = price monte (fwd > 0) apres touch.
        Breakout = price baisse (fwd < 0).
      - side_anchor=="both" : detecte des 2 cotes, on regarde |fwd| par rapport au signe de dist.
        Rejection = signe(fwd) opposé au signe(dist) de touch (price s'eloigne du niveau).
    """
    if dist_col not in df.columns:
        return pd.DataFrame()
    fwd_col = f"fwd_{horizon}m_ticks"
    if fwd_col not in df.columns:
        return pd.DataFrame()
    # Touch : abs(dist) < threshold
    touched = df[df[dist_col].abs() < threshold_ticks].copy()
    touched = touched.dropna(subset=[fwd_col])
    if len(touched) == 0:
        return pd.DataFrame()
    # Compute rejection signal
    fwd = touched[fwd_col].values
    dist = touched[dist_col].values

    if side_anchor == "above":
        # price approche d'en bas (dist > 0). Rejection = baisse (fwd<0).
        # Pour les bars avec dist negatif (prix au-dessus du niveau), on est en breakout
        # confirme - on les classe en "breakout side" (rejection inverse possible).
        # Simplification : on garde uniquement dist > -threshold (= test from below)
        mask = dist >= -threshold_ticks
        touched = touched[mask].copy()
        fwd = fwd[mask]
        # rejection = fwd < 0 (price baisse apres touch)
        touched["rejection"] = (fwd < 0).astype(int)
        touched["move_ticks"] = -fwd  # rejection = mouvement positif si fwd negatif
    elif side_anchor == "below":
        # price approche d'en haut (dist < 0). Rejection = monte (fwd>0).
        mask = dist <= threshold_ticks
        touched = touched[mask].copy()
        fwd = fwd[mask]
        touched["rejection"] = (fwd > 0).astype(int)
        touched["move_ticks"] = fwd
    else:  # both
        # Rejection = signe(fwd) opposé au signe(dist).
        # Si dist > 0 (price en-dessous niveau), rejection = price baisse plus = fwd < 0
        # Si dist < 0 (price au-dessus niveau), rejection = price monte plus = fwd > 0
        # → rejection si signe(fwd) == signe(dist) = price s'eloigne du niveau
        # En realite c'est l'inverse : si dist > 0 et fwd > 0 = price franchit le niveau (breakout)
        # Si dist > 0 et fwd < 0 = price s'eloigne du niveau d'en bas (rejection)
        # → rejection = signe(fwd) != signe(dist) approche en valeur absolue
        # Plus simple : rejection si abs(dist + fwd*tick_size_inverse) > abs(dist)
        # Approche pragmatique : rejection si price a EXPANSION dans le sens oppose a son approche
        # Si price approchait d'en bas (dist>0 puis 0), apres touch fwd<0 = rejection
        # Si price approchait d'en haut (dist<0 puis 0), apres touch fwd>0 = rejection
        # → rejection = sign(dist) * sign(fwd) < 0 (signes opposes) OU dist=0 (pile sur level)
        sign_dist = np.sign(dist)
        sign_fwd = np.sign(fwd)
        rejection_mask = ((sign_dist != 0) & (sign_dist != sign_fwd)) | (sign_dist == 0)
        touched["rejection"] = rejection_mask.astype(int)
        # move_ticks = magnitude du mouvement de rejection (positif si rejection)
        touched["move_ticks"] = np.where(rejection_mask, np.abs(fwd), -np.abs(fwd))

    touched["level_name"] = level_name
    return touched


# ═══════════════════════════════════════════════════════════════════
# ANALYSE
# ═══════════════════════════════════════════════════════════════════

def analyze_level(level_name: str, dist_col: str, side_anchor: str,
                   df: pd.DataFrame, horizon: int, min_n: int) -> dict:
    """Analyse complete d'un niveau."""
    touched = detect_level_touches(df, level_name, dist_col, side_anchor, horizon)
    if len(touched) < min_n:
        return {"level": level_name, "n_touches": len(touched),
                "skip_reason": f"n_touches<{min_n}"}

    n = len(touched)
    n_rej = int(touched["rejection"].sum())
    rejection_rate = n_rej / n
    avg_move = float(touched["move_ticks"].mean())
    median_move = float(touched["move_ticks"].median())

    # PF (Profit Factor) en supposant qu'on trade chaque touch
    moves = touched["move_ticks"].values
    gains = moves[moves > 0].sum()
    losses = abs(moves[moves < 0].sum())
    pf = float(gains / losses) if losses > 0 else 999.0

    # Stratification : rejection rate par contexte
    by_session = (touched.groupby("sess")["rejection"]
                  .agg(["mean", "count"])
                  .reset_index()
                  .rename(columns={"mean": "rejection_rate", "count": "n"})
                  .to_dict("records"))
    by_dd = (touched.groupby("dd")["rejection"]
             .agg(["mean", "count"])
             .reset_index()
             .rename(columns={"mean": "rejection_rate", "count": "n"})
             .to_dict("records"))
    by_rvol = (touched.groupby("rvol_reg", observed=True)["rejection"]
               .agg(["mean", "count"])
               .reset_index()
               .rename(columns={"mean": "rejection_rate", "count": "n"})
               .to_dict("records"))
    by_vix = (touched.groupby("vix_reg", observed=True)["rejection"]
              .agg(["mean", "count"])
              .reset_index()
              .rename(columns={"mean": "rejection_rate", "count": "n"})
              .to_dict("records"))

    # Best contexte
    contexts = []
    for s in by_session:
        if s["n"] >= min_n:
            contexts.append({"ctx": f"session={s['sess']}", "rate": s["rejection_rate"], "n": s["n"]})
    for d in by_dd:
        if d["n"] >= min_n:
            contexts.append({"ctx": f"delta_day={d['dd']}", "rate": d["rejection_rate"], "n": d["n"]})
    for r in by_rvol:
        if r["n"] >= min_n:
            contexts.append({"ctx": f"rvol={r['rvol_reg']}", "rate": r["rejection_rate"], "n": r["n"]})
    for v in by_vix:
        if v["n"] >= min_n:
            contexts.append({"ctx": f"vix={v['vix_reg']}", "rate": v["rejection_rate"], "n": v["n"]})

    contexts.sort(key=lambda x: x["rate"], reverse=True)
    best_ctx = contexts[:5] if contexts else []
    worst_ctx = sorted(contexts, key=lambda x: x["rate"])[:3] if contexts else []

    return {
        "level": level_name,
        "n_touches": n,
        "n_rejection": n_rej,
        "rejection_rate": round(rejection_rate * 100, 1),
        "avg_move_ticks": round(avg_move, 1),
        "median_move_ticks": round(median_move, 1),
        "pf": round(pf, 2),
        "by_session": by_session,
        "by_delta": by_dd,
        "by_rvol": by_rvol,
        "by_vix": by_vix,
        "best_contexts": best_ctx,
        "worst_contexts": worst_ctx,
    }


# ═══════════════════════════════════════════════════════════════════
# RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════

def render_report(symbol: str, results: list[dict],
                   df: pd.DataFrame, horizon: int, output_path: str):
    lines = []
    lines.append(f"# LEVEL PROBABILITY ANALYSIS — {symbol}\n")
    lines.append(f"**Genere** : {datetime.now().isoformat()}")
    lines.append(f"**Donnees** : {df['session_date'].min()} → {df['session_date'].max()}")
    lines.append(f"**Barres** : {len(df)} ({df['session_date'].nunique()} jours)")
    lines.append(f"**Horizon** : {horizon} min")
    lines.append(f"**Niveaux testes** : {len(LEVELS)}\n")

    # 1. Top niveaux par rejection_rate (n>=min_n)
    valid = [r for r in results if "skip_reason" not in r]
    if valid:
        valid.sort(key=lambda x: x["rejection_rate"], reverse=True)

        lines.append("## 1. RANKING par rejection rate (baseline tous contextes)\n")
        lines.append("| Niveau | N touches | Rejection % | Move avg t | PF | Verdict |")
        lines.append("|---|---|---|---|---|---|")
        for r in valid:
            verdict = ""
            if r["rejection_rate"] >= 60 and r["pf"] >= 1.5:
                verdict = "⭐⭐⭐ FORT"
            elif r["rejection_rate"] >= 55 and r["pf"] >= 1.3:
                verdict = "⭐⭐ Solide"
            elif r["rejection_rate"] >= 52:
                verdict = "⭐ Marginal"
            else:
                verdict = "❌ Pas d'edge"
            lines.append(
                f"| {r['level']} | {r['n_touches']} | {r['rejection_rate']}% | "
                f"{r['avg_move_ticks']} | {r['pf']} | {verdict} |"
            )
        lines.append("")

        # 2. Detail par niveau (top 10)
        lines.append("## 2. DETAIL par niveau (top 10)\n")
        for r in valid[:10]:
            lines.append(f"### {r['level']} (n={r['n_touches']}, rejection={r['rejection_rate']}%, PF={r['pf']})\n")
            if r.get("best_contexts"):
                lines.append("**Top 5 contextes (rejection rate max)** :")
                for c in r["best_contexts"]:
                    lines.append(f"- {c['ctx']} : {round(c['rate']*100,1)}% (n={c['n']})")
                lines.append("")
            if r.get("worst_contexts"):
                lines.append("**3 pires contextes** :")
                for c in r["worst_contexts"]:
                    lines.append(f"- {c['ctx']} : {round(c['rate']*100,1)}% (n={c['n']})")
                lines.append("")
            # Par session
            lines.append("**Par session** :")
            lines.append("| Session | Rejection % | N |")
            lines.append("|---|---|---|")
            for s in r["by_session"]:
                lines.append(f"| {s['sess']} | {round(s['rejection_rate']*100,1)}% | {s['n']} |")
            lines.append("")

        # 3. Skipped
        skipped = [r for r in results if "skip_reason" in r]
        if skipped:
            lines.append("## 3. NIVEAUX SKIPPED (n trop faible)\n")
            for r in skipped:
                lines.append(f"- {r['level']} : {r.get('skip_reason', 'unknown')} (n={r['n_touches']})")
            lines.append("")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[REPORT] {output_path}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--horizon", type=int, default=30, help="Forward minutes")
    parser.add_argument("--min-n", type=int, default=10, help="Min touches for level")
    parser.add_argument("--output", default="DOCS/LEVEL_PROB.md")
    parser.add_argument("--rth-only", action="store_true",
                        help="Filter US RTH only (default = all sessions)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"LEVEL PROBABILITY ANALYZER — {args.symbol}")
    print(f"Data dir : {args.data_dir}")
    print(f"Horizon  : {args.horizon} min")
    print(f"Min N    : {args.min_n}")
    print(f"Sessions : {'RTH only' if args.rth_only else 'ALL (Asia/London/RTH/AH)'}")
    print("=" * 70)

    # Load
    df = load_jsonl_data(args.data_dir, args.symbol)
    if df.empty:
        return

    # RTH filter optional
    if args.rth_only and "session_id" in df.columns:
        n_before = len(df)
        df = df[df["session_id"] == "US"].reset_index(drop=True)
        print(f"[RTH] {n_before} -> {len(df)}")

    # Forward moves
    print(f"\n[FORWARD] Calcul fwd_{args.horizon}m_ticks par session...")
    df = add_forward_moves(df, horizon=args.horizon)

    # Context labels
    print("[CONTEXT] Labels session/delta/rvol/vix...")
    df = add_context_labels(df)

    # Analyze each level
    print(f"\n[ANALYZE] {len(LEVELS)} niveaux...")
    results = []
    for level_name, dist_col, group, side_anchor in LEVELS:
        if dist_col not in df.columns:
            print(f"  [SKIP] {level_name}: col '{dist_col}' absente")
            continue
        r = analyze_level(level_name, dist_col, side_anchor, df,
                            args.horizon, args.min_n)
        results.append(r)
        if "skip_reason" in r:
            print(f"  [SKIP] {level_name}: {r['skip_reason']} (n={r['n_touches']})")
        else:
            print(f"  {level_name:14s} : n={r['n_touches']:>5} rej={r['rejection_rate']:>4.1f}% "
                  f"avg_move={r['avg_move_ticks']:>+5.1f}t PF={r['pf']:>4.2f}")

    # Report
    render_report(args.symbol, results, df, args.horizon, args.output)

    # Summary
    valid = [r for r in results if "skip_reason" not in r]
    valid.sort(key=lambda x: x["rejection_rate"], reverse=True)
    print(f"\n{'=' * 70}")
    print(f"TOP 5 NIVEAUX par rejection rate")
    for r in valid[:5]:
        print(f"  {r['level']:14s} : {r['rejection_rate']:>5.1f}% (n={r['n_touches']}) PF={r['pf']:.2f}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
