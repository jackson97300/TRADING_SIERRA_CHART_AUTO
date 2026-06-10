"""analyze_real_reaction_zones.py — Analyse empirique des zones de reaction.

Jackson directive 24/05/2026 :
"AU LIEU DE CHERCHER DES NOUVELLE ZONE DE REACTION ANALYSE LES ZONNE
QUI ONT REAGIS DEJA ET DE LA ON ENTIRE DES CONCLUSSION ZONE DE REACTION
ANALYSE PROFONDE"

OBJECTIF :
  Identifier dans le dataset v4_pure (oct 2025 -> mai 2026) TOUS les bounces
  significatifs (prix qui inverse de >=X ticks dans Y bars), puis pour chaque
  bounce, capturer :
    - quels niveaux MP/MQ/VWAP/IB/GEX/CASH/swing etaient proches (abs dist <= 0.05%)
    - features V4 actives (BN absorb, color, footprint, divergence, etc.)
    - regime, session, CVD direction
    - profile du bounce (magnitude, duration)
  Puis agreger pour tirer une DEFINITION EMPIRIQUE de "zone de reaction valide".

BOUNCE :
  LONG bounce : low_T → high_T+1..T+30 >= 15 ticks NQ / 6 ticks ES (reversal up)
  SHORT bounce : high_T → low_T+1..T+30 >= 15 ticks NQ / 6 ticks ES (reversal dn)

OUTPUT : LOGS/reaction_zones_analysis/REPORT.md + stats CSV
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot3_reform_backtester import (
    PERIOD_END,
    TICK_SIZE,
    _safe_float,
)
import glob

ROOT_DATA = ROOT


def load_v4_pure_custom(symbol: str, period_start: str) -> pd.DataFrame:
    """Charge v4_pure avec period_start customisable (pour test FULL vs MQ_PROPRE)."""
    pattern = str(
        ROOT_DATA / f"DATA/datasets/v4_pure/symbol={symbol}.c.0/year=*/month=*/data.parquet"
    )
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"Aucun parquet : {pattern}")
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    start = pd.to_datetime(period_start, utc=True)
    end = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start) & (df["ts_event"] < end)].reset_index(drop=True)
    df["symbol"] = symbol
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    return df


# ════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════

BOUNCE_MIN_TICKS_NQ = 25      # bounce minimum NQ (significatif, resserre)
BOUNCE_MIN_TICKS_ES = 10      # bounce minimum ES
BOUNCE_WINDOW_BARS = 15       # fenetre detection bounce post-touch (resserre)
LOCAL_LOOKBACK = 5            # lookback pour local low/high (resserre vs 1 = bruit)
PROXIMITY_PCT = 0.05          # abs(dist_pct) <= 0.05% = niveau "proche"

OUT_DIR = ROOT / "LOGS" / "reaction_zones_analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# LEVELS A AUDITER (toutes familles)
# ════════════════════════════════════════════════════════════════════════

LEVELS_FOR_ANALYSIS = [
    # Market Profile (priorite Jackson)
    ("CUR_VAH", "dist_cur_vah_pct", "MP"),
    ("CUR_VAL", "dist_cur_val_pct", "MP"),
    ("CUR_VPOC", "dist_cur_vpoc_pct", "MP"),
    ("PREV_VAH", "dist_prev_vah_pct", "MP"),
    ("PREV_VAL", "dist_prev_val_pct", "MP"),
    ("PREV_VPOC", "dist_prev_vpoc_pct", "MP"),
    ("NAKED_POC", "dist_naked_poc_nearest_pct", "MP"),
    # MenthorQ
    ("MQ_1D_MAX", "dist_1d_max_ticks_pct", "MQ"),
    ("MQ_1D_MIN", "dist_1d_min_ticks_pct", "MQ"),
    ("MQ_CALL", "dist_mq_call_pct", "MQ"),
    ("MQ_PUT", "dist_mq_put_pct", "MQ"),
    ("MQ_CALL_0DTE", "dist_mq_call_0dte_pct", "MQ"),
    ("MQ_PUT_0DTE", "dist_mq_put_0dte_pct", "MQ"),
    ("MQ_HVL", "dist_mq_hvl_pct", "MQ"),
    # VWAP
    ("VWAP_D", "dist_vwap_d_pct", "VWAP"),
    ("VWAP_W", "dist_vwap_w_pct", "VWAP"),
    ("VWAP_M", "dist_vwap_m_pct", "VWAP"),
    ("PVWAP", "dist_pvwap_pct", "VWAP"),
    ("VWAP_D_SD1U", "dist_vwap_d_sd1u_pct", "VWAP"),
    ("VWAP_D_SD1D", "dist_vwap_d_sd1d_pct", "VWAP"),
    ("VWAP_D_SD2U", "dist_vwap_d_sd2u_pct", "VWAP"),
    ("VWAP_D_SD2D", "dist_vwap_d_sd2d_pct", "VWAP"),
    # IB
    ("IB_HIGH", "dist_ib_high_pct", "IB"),
    ("IB_LOW", "dist_ib_low_pct", "IB"),
    # GEX
    ("GEX_UP", "dist_gex_nearest_up_pct", "GEX"),
    ("GEX_DN", "dist_gex_nearest_dn_pct", "GEX"),
    # Cash + Asia
    ("CASH_HIGH", "dist_cash_high_pct", "CASH"),
    ("CASH_LOW", "dist_cash_low_pct", "CASH"),
    ("ASIA_HIGH", "dist_asia_high_pct", "CASH"),
    ("ASIA_LOW", "dist_asia_low_pct", "CASH"),
    # Swing (last session)
    ("SWING_HIGH", "dist_last_swing_high_pct", "SWING"),
    ("SWING_LOW", "dist_last_swing_low_pct", "SWING"),
]


# ════════════════════════════════════════════════════════════════════════
# FEATURES V4 A CAPTURER (signaux contextuels)
# ════════════════════════════════════════════════════════════════════════

CONTEXT_FEATURES = [
    # Pattern reversal V4
    "long_dn_up_pattern",
    "long_up_dn_pattern",
    "long_up_bar",
    "long_dn_bar",
    # BN absorption
    "bn_absorb_bid_raw",
    "bn_absorb_ask_raw",
    "bn_absorb_bid_at_level",
    "bn_absorb_ask_at_level",
    # BN color clusters
    "n_color_up_zones_active",
    "n_color_dn_zones_active",
    "n_color_up_cluster_within_0_2pct",
    "n_color_dn_cluster_within_0_2pct",
    # BN edge / trapped
    "n_edge_buy_active",
    "n_edge_sell_active",
    "bn_trapped_buyers_at_resistance",
    "bn_trapped_sellers_at_support",
    # Delta / divergence
    "delta_div_buy",
    "delta_div_sell",
    # Regime
    "regime_mode",
    "regime_actionable",
    "regime_favor",
    # Volume / extension
    "rvol_extreme",
    # VWAP cross
    "vwap_d_cross_up",
    "vwap_d_cross_dn",
    # Session
    "session",
]


# ════════════════════════════════════════════════════════════════════════
# BOUNCE DETECTION
# ════════════════════════════════════════════════════════════════════════

def detect_bounces(df: pd.DataFrame, symbol: str) -> List[Dict]:
    """Detecte tous les bounces significatifs LONG/SHORT (vectorise numpy).

    LONG bounce : local low T, puis dans T+1..T+30 high atteint low_T + N ticks
    SHORT bounce : local high T, puis dans T+1..T+30 low atteint high_T - N ticks

    Implementation vectorisee :
      - rolling max high sur fenetre (T+1..T+30) via stride / np.lib.stride_tricks
      - simple boucle uniquement sur les bars qualifiees local low/high
    """
    bounce_min = BOUNCE_MIN_TICKS_NQ if symbol == "NQ" else BOUNCE_MIN_TICKS_ES
    bounce_pts = bounce_min * TICK_SIZE
    n = len(df)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    dates = df["date"].values

    # Local low/high (LOCAL_LOOKBACK lookback chaque cote)
    is_local_low = np.zeros(n, dtype=bool)
    is_local_high = np.zeros(n, dtype=bool)
    # Rolling min sur fenetre +/- LOCAL_LOOKBACK
    lb = LOCAL_LOOKBACK
    if n > 2 * lb + 1:
        # low_i est local low si low_i == min(low[i-lb..i+lb])
        rolling_min = pd.Series(lows).rolling(window=2*lb+1, center=True, min_periods=lb+1).min().values
        rolling_max = pd.Series(highs).rolling(window=2*lb+1, center=True, min_periods=lb+1).max().values
        is_local_low = (lows == rolling_min) & ~np.isnan(rolling_min)
        is_local_high = (highs == rolling_max) & ~np.isnan(rolling_max)

    # Rolling max high sur fenetre [T+1, T+30] (vectorise)
    # rolling_max_high[i] = max(highs[i+1..i+30])
    # On utilise pandas rolling pour la lisibilite
    s_high = pd.Series(highs).shift(-1).rolling(window=BOUNCE_WINDOW_BARS, min_periods=1).max()
    s_low_min = pd.Series(lows).shift(-1).rolling(window=BOUNCE_WINDOW_BARS, min_periods=1).min()
    # Pour la "duration", on accepte la 1ere bar qui satisfait le seuil — c'est
    # difficile a vectoriser. On approxime duration par mean ou on l'omet.
    # Ici on calcule la duration par recherche numpy.argmax dans la fenetre
    # uniquement pour les bars qualifiees (n_local_low ~ 30% de n).
    rolling_max_high = s_high.values
    rolling_min_low = s_low_min.values

    bounces: List[Dict] = []
    long_idxs = np.where(is_local_low)[0]
    short_idxs = np.where(is_local_high)[0]

    for i in long_idxs:
        if i >= n - 2:
            continue
        low_i = lows[i]
        max_high = rolling_max_high[i] if not np.isnan(rolling_max_high[i]) else low_i
        if max_high - low_i < bounce_pts:
            continue
        # Verifier que le bounce arrive sur meme journee
        day = dates[i]
        end_j = min(n, i + 1 + BOUNCE_WINDOW_BARS)
        # Trouver premiere bar j ou high[j] >= low_i + bounce_pts ET date == day
        target = low_i + bounce_pts
        duration = 0
        for j in range(i + 1, end_j):
            if dates[j] != day:
                break
            if highs[j] >= target:
                duration = j - i
                break
        if duration > 0:
            bounces.append({
                "bounce_idx": int(i),
                "side": "LONG",
                "magnitude_ticks": (max_high - low_i) / TICK_SIZE,
                "duration_bars": int(duration),
            })

    for i in short_idxs:
        if i >= n - 2:
            continue
        high_i = highs[i]
        min_low = rolling_min_low[i] if not np.isnan(rolling_min_low[i]) else high_i
        if high_i - min_low < bounce_pts:
            continue
        day = dates[i]
        end_j = min(n, i + 1 + BOUNCE_WINDOW_BARS)
        target = high_i - bounce_pts
        duration = 0
        for j in range(i + 1, end_j):
            if dates[j] != day:
                break
            if lows[j] <= target:
                duration = j - i
                break
        if duration > 0:
            bounces.append({
                "bounce_idx": int(i),
                "side": "SHORT",
                "magnitude_ticks": (high_i - min_low) / TICK_SIZE,
                "duration_bars": int(duration),
            })

    return bounces


# ════════════════════════════════════════════════════════════════════════
# SNAPSHOT FEATURES AT BOUNCE
# ════════════════════════════════════════════════════════════════════════

def snapshot_bounce(
    df: pd.DataFrame,
    bounce: Dict,
    symbol: str,
) -> Dict:
    """Capture snapshot des features V4 au point du bounce."""
    i = bounce["bounce_idx"]
    row = df.iloc[i]
    side = bounce["side"]

    snap = {
        "bounce_idx": i,
        "ts_event": row["ts_event"].isoformat(),
        "symbol": symbol,
        "side": side,
        "magnitude_ticks": bounce["magnitude_ticks"],
        "duration_bars": bounce["duration_bars"],
        "close": _safe_float(row.get("close")),
    }

    # Pour chaque niveau, capturer si "proche" (abs dist <= PROXIMITY_PCT)
    for level_name, dist_col, family in LEVELS_FOR_ANALYSIS:
        if dist_col not in df.columns:
            snap[f"near_{level_name}"] = 0
            snap[f"dist_{level_name}_pct"] = None
            continue
        dist = row.get(dist_col)
        if dist is None or pd.isna(dist):
            snap[f"near_{level_name}"] = 0
            snap[f"dist_{level_name}_pct"] = None
            continue
        abs_dist = abs(float(dist))
        snap[f"near_{level_name}"] = 1 if abs_dist <= PROXIMITY_PCT else 0
        snap[f"dist_{level_name}_pct"] = float(dist)

    # Context features V4
    for feat in CONTEXT_FEATURES:
        if feat not in df.columns:
            snap[feat] = None
            continue
        v = row.get(feat)
        if pd.isna(v):
            snap[feat] = None
        else:
            snap[feat] = v if isinstance(v, (str, int, float, np.integer, np.floating)) else str(v)

    return snap


# ════════════════════════════════════════════════════════════════════════
# AGGREGATION & ANALYSIS
# ════════════════════════════════════════════════════════════════════════

def aggregate_stats(snapshots: List[Dict], symbols: List[str]) -> Dict:
    """Agrege les stats sur tous les bounces.

    Outputs :
      - bounces totaux par sym/side
      - top niveaux : % de bounces ou near=1, par family
      - top features V4 actives au moment du bounce
      - confluence : combien de niveaux differents par bounce
      - regime/session breakdown
    """
    df = pd.DataFrame(snapshots)
    stats: Dict = {"global": {}}

    # Global counts
    stats["global"]["total_bounces"] = len(df)
    by_ss = df.groupby(["symbol", "side"]).size().to_dict()
    # Convert tuple keys to string for JSON serialization
    stats["global"]["by_sym_side"] = {f"{k[0]}_{k[1]}": int(v) for k, v in by_ss.items()}
    stats["global"]["magnitude_mean"] = float(df["magnitude_ticks"].mean())
    stats["global"]["magnitude_median"] = float(df["magnitude_ticks"].median())
    stats["global"]["duration_mean"] = float(df["duration_bars"].mean())
    stats["global"]["duration_median"] = float(df["duration_bars"].median())

    # Top levels par % bounces ou near=1
    level_stats = []
    for level_name, _, family in LEVELS_FOR_ANALYSIS:
        col = f"near_{level_name}"
        if col not in df.columns:
            continue
        n_near = int(df[col].sum())
        pct = n_near / len(df) * 100 if len(df) > 0 else 0
        # Split par side
        n_near_long = int(df[(df["side"] == "LONG") & (df[col] == 1)].shape[0])
        n_near_short = int(df[(df["side"] == "SHORT") & (df[col] == 1)].shape[0])
        level_stats.append({
            "level": level_name,
            "family": family,
            "n_bounces_with_level": n_near,
            "pct_bounces": round(pct, 2),
            "n_long_with_level": n_near_long,
            "n_short_with_level": n_near_short,
        })
    stats["levels"] = sorted(level_stats, key=lambda x: -x["pct_bounces"])

    # Top features V4 actives au bounce
    feat_stats = []
    for feat in CONTEXT_FEATURES:
        if feat not in df.columns or feat in ("regime_mode", "regime_favor"):
            continue
        # Try cast to int (0/1 boolean-like)
        try:
            vals = pd.to_numeric(df[feat], errors="coerce").fillna(0)
            n_active = int((vals > 0).sum())
            pct = n_active / len(df) * 100 if len(df) > 0 else 0
            feat_stats.append({
                "feature": feat,
                "n_bounces_with_active": n_active,
                "pct_bounces": round(pct, 2),
                "mean_value": float(vals.mean()),
            })
        except Exception:
            continue
    stats["features"] = sorted(feat_stats, key=lambda x: -x["pct_bounces"])

    # Confluence: nb niveaux proches simultanement
    near_cols = [f"near_{lv[0]}" for lv, *_ in [(l,) for l in LEVELS_FOR_ANALYSIS]]
    near_cols = [c for c in near_cols if c in df.columns]
    df["n_levels_near"] = df[near_cols].sum(axis=1)
    confluence_dist = df["n_levels_near"].value_counts().sort_index().to_dict()
    stats["confluence"] = {int(k): int(v) for k, v in confluence_dist.items()}
    stats["confluence_mean"] = float(df["n_levels_near"].mean())

    # Regime breakdown
    if "regime_mode" in df.columns:
        regime_counts = df["regime_mode"].fillna("UNKNOWN").value_counts().to_dict()
        stats["regime_breakdown"] = {str(k): int(v) for k, v in regime_counts.items()}

    # Session breakdown
    if "session" in df.columns:
        session_counts = pd.to_numeric(df["session"], errors="coerce").value_counts().sort_index().to_dict()
        stats["session_breakdown"] = {f"session_{int(k) if not pd.isna(k) else 'NA'}": int(v) for k, v in session_counts.items()}

    return stats, df


# ════════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ════════════════════════════════════════════════════════════════════════

def write_report(stats: Dict, df_snap: pd.DataFrame) -> Path:
    lines = []
    lines.append("# Analyse Empirique des Zones de Reaction\n")
    lines.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    lines.append(f"Symboles : NQ + ES")
    lines.append(f"Critere bounce : prix inverse de >={BOUNCE_MIN_TICKS_NQ}t NQ / "
                 f"{BOUNCE_MIN_TICKS_ES}t ES dans {BOUNCE_WINDOW_BARS} bars apres local low/high")
    lines.append(f"Proximite niveau : abs(dist_pct) <= {PROXIMITY_PCT}%")

    # Section 1 : Global
    lines.append("\n## 1. Statistiques globales\n")
    lines.append(f"- Total bounces detectes : **{stats['global']['total_bounces']}**")
    lines.append(f"- Par sym/side : {stats['global']['by_sym_side']}")
    lines.append(f"- Magnitude moyenne : {stats['global']['magnitude_mean']:.1f} ticks")
    lines.append(f"- Magnitude mediane : {stats['global']['magnitude_median']:.1f} ticks")
    lines.append(f"- Duration moyenne : {stats['global']['duration_mean']:.1f} bars")
    lines.append(f"- Duration mediane : {stats['global']['duration_median']:.1f} bars")

    # Section 2 : Top niveaux
    lines.append("\n## 2. Top niveaux presents au bounce (% bounces ou abs(dist) <= 0.05%)\n")
    lines.append("| Rank | Level | Family | % bounces | n total | n LONG | n SHORT |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, lv in enumerate(stats["levels"][:20], 1):
        lines.append(f"| {i} | **{lv['level']}** | {lv['family']} | "
                     f"{lv['pct_bounces']}% | {lv['n_bounces_with_level']} | "
                     f"{lv['n_long_with_level']} | {lv['n_short_with_level']} |")

    # Section 2bis : Top par famille
    lines.append("\n## 2bis. Top par famille (% bounces somme famille)\n")
    family_pct = {}
    for lv in stats["levels"]:
        family_pct.setdefault(lv["family"], 0)
        family_pct[lv["family"]] += lv["n_bounces_with_level"]
    n_total = stats["global"]["total_bounces"]
    fam_sorted = sorted(family_pct.items(), key=lambda x: -x[1])
    lines.append("| Family | Sum n_bounces (peut compter doublon) | % moyenne par bounce |")
    lines.append("|---|---|---|")
    for fam, n in fam_sorted:
        pct = n / n_total * 100 if n_total > 0 else 0
        lines.append(f"| {fam} | {n} | {pct:.1f}% |")

    # Section 3 : Top features V4
    lines.append("\n## 3. Top features V4 actives au moment du bounce\n")
    lines.append("| Rank | Feature | % bounces active | n total | mean value |")
    lines.append("|---|---|---|---|---|")
    for i, ft in enumerate(stats["features"][:15], 1):
        lines.append(f"| {i} | **{ft['feature']}** | {ft['pct_bounces']}% | "
                     f"{ft['n_bounces_with_active']} | {ft['mean_value']:.4f} |")

    # Section 4 : Confluence
    lines.append("\n## 4. Confluence (nombre de niveaux proches simultanement)\n")
    lines.append(f"Moyenne niveaux proches par bounce : **{stats['confluence_mean']:.2f}**\n")
    lines.append("Distribution :")
    lines.append("| n_levels_near | n_bounces | % |")
    lines.append("|---|---|---|")
    for k in sorted(stats["confluence"].keys()):
        n = stats["confluence"][k]
        pct = n / n_total * 100 if n_total > 0 else 0
        lines.append(f"| {k} | {n} | {pct:.1f}% |")

    # Section 5 : Regime breakdown
    if "regime_breakdown" in stats:
        lines.append("\n## 5. Distribution par regime au bounce\n")
        lines.append("| regime_mode | n_bounces | % |")
        lines.append("|---|---|---|")
        for r, n in sorted(stats["regime_breakdown"].items(), key=lambda x: -x[1]):
            pct = n / n_total * 100 if n_total > 0 else 0
            lines.append(f"| {r} | {n} | {pct:.1f}% |")

    # Section 6 : Session breakdown
    if "session_breakdown" in stats:
        lines.append("\n## 6. Distribution par session au bounce\n")
        lines.append("| session | n_bounces | % |")
        lines.append("|---|---|---|")
        for s, n in sorted(stats["session_breakdown"].items()):
            pct = n / n_total * 100 if n_total > 0 else 0
            lines.append(f"| {s} (0=Asia 1=London 2=RTH 3=RTH_AH) | {n} | {pct:.1f}% |")

    # Section 7 : Conclusion empirique
    lines.append("\n## 7. Conclusions empiriques\n")
    lines.append("**Definition empirique d'une zone de reaction** : niveau institutionnel "
                 "ou >=N% des bounces historiques se produisent quand le prix est proche "
                 "(abs(dist) <= 0.05%).")
    top3_levels = stats["levels"][:3]
    if top3_levels:
        lines.append("\n**Top 3 niveaux statistiquement les + significatifs** :")
        for lv in top3_levels:
            lines.append(f"- **{lv['level']}** ({lv['family']}) : {lv['pct_bounces']}% des bounces "
                         f"({lv['n_long_with_level']} LONG / {lv['n_short_with_level']} SHORT)")

    # Hypothese trading
    lines.append("\n**Hypothese trading** :")
    top_features = [f for f in stats["features"][:5] if f["pct_bounces"] >= 20]
    if top_features:
        lines.append("Features V4 frequentes au bounce (potentiel trigger entry) :")
        for ft in top_features:
            lines.append(f"- {ft['feature']} : {ft['pct_bounces']}%")
    else:
        lines.append("Aucune feature V4 frequente >=20% au moment du bounce. Le bounce "
                     "semble difficilement predictible via signaux discretizes V4 seuls.")

    report_path = OUT_DIR / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def run_analysis(period_start: str, label: str) -> Dict:
    """Execute analyse complete pour une periode donnee, retourne stats."""
    print(f"\n{'='*80}")
    print(f"ANALYSE PERIODE : {label} ({period_start} -> {PERIOD_END})")
    print(f"{'='*80}\n")

    out_dir_label = OUT_DIR / label
    out_dir_label.mkdir(parents=True, exist_ok=True)

    all_snapshots: List[Dict] = []
    for sym in ["NQ", "ES"]:
        print(f"[LOAD] {sym} ({label})...", flush=True)
        t0 = time.time()
        df = load_v4_pure_custom(sym, period_start)
        print(f"  {len(df)} bars / {df['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

        print(f"[DETECT] Bounces {sym}...", flush=True)
        t0 = time.time()
        bounces = detect_bounces(df, sym)
        print(f"  {len(bounces)} bounces ({time.time()-t0:.1f}s)", flush=True)

        print(f"[SNAPSHOT] Features {sym}...", flush=True)
        t0 = time.time()
        for b in bounces:
            snap = snapshot_bounce(df, b, sym)
            all_snapshots.append(snap)
        print(f"  {time.time()-t0:.1f}s", flush=True)

    print(f"\n[AGGREGATE] {label} stats sur {len(all_snapshots)} bounces...", flush=True)
    stats, df_snap = aggregate_stats(all_snapshots, ["NQ", "ES"])
    stats["_period_label"] = label
    stats["_period_start"] = period_start

    # Save
    df_snap.to_csv(out_dir_label / "bounces_snapshots.csv", index=False)
    with open(out_dir_label / "stats.json", "w", encoding="utf-8") as f:
        def _serializer(obj):
            if isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64)):
                return float(obj)
            return str(obj)
        json.dump(stats, f, indent=2, default=_serializer)

    # Console summary per period
    print(f"\nTOP 10 NIVEAUX PAR % BOUNCES ({label}) :")
    for i, lv in enumerate(stats["levels"][:10], 1):
        print(f"  {i:2d}. {lv['level']:15s} ({lv['family']:6s}) : "
              f"{lv['pct_bounces']:5.1f}% ({lv['n_bounces_with_level']} bounces)")

    return stats


def main():
    print(f"\n{'='*80}")
    print(f"ANALYSE EMPIRIQUE ZONES REACTION — 2 PERIODES COMPAREES")
    print(f"{'='*80}\n")

    # Run 1 : FULL (194 jours, oct 2025 -> mai 2026, MQ peut etre absent pre-15/12)
    stats_full = run_analysis("2025-10-01", "FULL_194j")

    # Run 2 : MQ_PROPRE (130 jours, 15/12 -> mai 2026, MQ disponibles partout)
    stats_mq = run_analysis("2025-12-15", "MQ_PROPRE_130j")

    # COMPARATIF write_report
    print(f"\n{'='*80}")
    print(f"COMPARATIF FULL vs MQ_PROPRE")
    print(f"{'='*80}")

    lines = []
    lines.append("# Analyse Empirique Zones Reaction — Comparatif 2 Periodes\n")
    lines.append(f"_Genere {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append(f"\nDirective Jackson : tester sur dataset FULL (oct-mai 194j) "
                 "et periode MQ propre (15/12-mai 130j) pour cross-validation.\n")

    lines.append("## Comparaison globale\n")
    lines.append("| Periode | Bounces totaux | Magnitude moyenne | Confluence moyenne |")
    lines.append("|---|---|---|---|")
    for s in [stats_full, stats_mq]:
        lines.append(f"| {s['_period_label']} | {s['global']['total_bounces']} | "
                     f"{s['global']['magnitude_mean']:.1f}t | "
                     f"{s['confluence_mean']:.2f} |")

    lines.append("\n## Top 15 niveaux — FULL (194 jours)\n")
    lines.append("| Rank | Level | Family | % bounces | n total |")
    lines.append("|---|---|---|---|---|")
    for i, lv in enumerate(stats_full["levels"][:15], 1):
        lines.append(f"| {i} | **{lv['level']}** | {lv['family']} | "
                     f"{lv['pct_bounces']}% | {lv['n_bounces_with_level']} |")

    lines.append("\n## Top 15 niveaux — MQ_PROPRE (130 jours)\n")
    lines.append("| Rank | Level | Family | % bounces | n total |")
    lines.append("|---|---|---|---|---|")
    for i, lv in enumerate(stats_mq["levels"][:15], 1):
        lines.append(f"| {i} | **{lv['level']}** | {lv['family']} | "
                     f"{lv['pct_bounces']}% | {lv['n_bounces_with_level']} |")

    # Diff analysis : niveaux qui montent ou descendent entre periodes
    lines.append("\n## Variation FULL → MQ_PROPRE (focus niveaux MQ)\n")
    full_map = {lv["level"]: lv["pct_bounces"] for lv in stats_full["levels"]}
    mq_map = {lv["level"]: lv["pct_bounces"] for lv in stats_mq["levels"]}
    diff_rows = []
    for level in full_map:
        pf = full_map.get(level, 0)
        pm = mq_map.get(level, 0)
        diff_rows.append((level, pf, pm, pm - pf))
    diff_rows.sort(key=lambda x: -abs(x[3]))
    lines.append("| Level | % FULL | % MQ_PROPRE | Delta |")
    lines.append("|---|---|---|---|")
    for level, pf, pm, d in diff_rows[:15]:
        sign = "+" if d > 0 else ""
        lines.append(f"| {level} | {pf}% | {pm}% | {sign}{d:.1f}pp |")

    lines.append("\n## Top 10 features V4 actives au bounce — FULL\n")
    lines.append("| Feature | % FULL |")
    lines.append("|---|---|")
    for ft in stats_full["features"][:10]:
        lines.append(f"| {ft['feature']} | {ft['pct_bounces']}% |")

    lines.append("\n## Top 10 features V4 actives au bounce — MQ_PROPRE\n")
    lines.append("| Feature | % MQ_PROPRE |")
    lines.append("|---|---|")
    for ft in stats_mq["features"][:10]:
        lines.append(f"| {ft['feature']} | {ft['pct_bounces']}% |")

    lines.append("\n## Regime breakdown bounces\n")
    lines.append("| Regime | FULL | MQ_PROPRE |")
    lines.append("|---|---|---|")
    fr = stats_full.get("regime_breakdown", {})
    mr = stats_mq.get("regime_breakdown", {})
    all_regimes = set(list(fr.keys()) + list(mr.keys()))
    for r in sorted(all_regimes):
        lines.append(f"| {r} | {fr.get(r, 0)} | {mr.get(r, 0)} |")

    # Conclusions empiriques
    lines.append("\n## Conclusions empiriques\n")
    top3_full = stats_full["levels"][:3]
    top3_mq = stats_mq["levels"][:3]
    lines.append("**Top 3 niveaux universels (FULL)** :")
    for lv in top3_full:
        lines.append(f"- {lv['level']} ({lv['family']}) : {lv['pct_bounces']}% des bounces")
    lines.append("\n**Top 3 niveaux periode MQ propre** :")
    for lv in top3_mq:
        lines.append(f"- {lv['level']} ({lv['family']}) : {lv['pct_bounces']}% des bounces")

    # Hypothese trading
    lines.append("\n**Definition empirique zone de reaction valide** :")
    threshold = 30  # 30% des bounces minimum pour qualifier "vraie zone"
    valid_full = [lv for lv in stats_full["levels"] if lv["pct_bounces"] >= threshold]
    valid_mq = [lv for lv in stats_mq["levels"] if lv["pct_bounces"] >= threshold]
    lines.append(f"Critere : niveau associe a >= {threshold}% des bounces historiques.")
    lines.append(f"\nFULL : {len(valid_full)} niveaux valides")
    for lv in valid_full:
        lines.append(f"  - {lv['level']} ({lv['family']}) : {lv['pct_bounces']}%")
    lines.append(f"\nMQ_PROPRE : {len(valid_mq)} niveaux valides")
    for lv in valid_mq:
        lines.append(f"  - {lv['level']} ({lv['family']}) : {lv['pct_bounces']}%")

    (OUT_DIR / "REPORT_COMPARATIF.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[REPORT] {OUT_DIR / 'REPORT_COMPARATIF.md'}")

    # Final synthesis
    print("\n=== TOP 5 NIVEAUX FULL (194j) ===")
    for lv in stats_full["levels"][:5]:
        print(f"  {lv['level']:15s} ({lv['family']:6s}) : {lv['pct_bounces']:5.1f}% "
              f"({lv['n_bounces_with_level']} bounces)")
    print("\n=== TOP 5 NIVEAUX MQ_PROPRE (130j) ===")
    for lv in stats_mq["levels"][:5]:
        print(f"  {lv['level']:15s} ({lv['family']:6s}) : {lv['pct_bounces']:5.1f}% "
              f"({lv['n_bounces_with_level']} bounces)")


if __name__ == "__main__":
    main()
