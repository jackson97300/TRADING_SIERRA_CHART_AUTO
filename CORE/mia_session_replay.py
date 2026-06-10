"""
mia_session_replay.py — Session Replay Analyzer
=================================================
Analyse post-session : detecte les touches de niveaux cles,
mesure bounce/breakout, MAE/MFE, et produit des features
adaptatives pour le ML.

Usage:
    python -X utf8 CORE/mia_session_replay.py                    # toutes les sessions
    python -X utf8 CORE/mia_session_replay.py --date 2026-04-06  # session specifique
    python -X utf8 CORE/mia_session_replay.py --symbol ES         # un seul instrument

Outputs:
    DATA/SESSION_REPORTS/YYYYMMDD_{SYM}_replay.json  — rapport par session
    DATA/SESSION_REPORTS/level_stats.json             — stats cumulees tous niveaux

Auteur : MIA Trading System
Date   : 2026-04-06
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from glob import glob
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from dmp_reader import DmpReader


# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────

DATA_DIR = str(Path(__file__).parent.parent / "DATA")
REPORT_DIR = os.path.join(DATA_DIR, "SESSION_REPORTS")
TICK_SIZE = 0.25

# Seuil de proximite pour detecter un "touch" (en ticks)
TOUCH_THRESHOLD = 5

# Horizons pour MAE/MFE (en barres 1-min)
HORIZONS = [3, 5, 10, 20]

# Seuil minimum pour qualifier un "bounce" (en ticks)
BOUNCE_MIN_TICKS = 8

# Niveaux a surveiller avec leur colonne dist_* et direction attendue
LEVELS_CONFIG = [
    # Previous day levels
    {"name": "prev_VPOC", "col": "dist_prev_vpoc", "bounce_dir": "both"},
    {"name": "prev_VAH", "col": "dist_prev_vah", "bounce_dir": "sell"},
    {"name": "prev_VAL", "col": "dist_prev_val", "bounce_dir": "buy"},
    {"name": "prev_VWAP", "col": "dist_prev_vwap", "bounce_dir": "both"},
    # Current session
    {"name": "cur_VPOC", "col": "dist_cur_vpoc", "bounce_dir": "both"},
    {"name": "cur_VAH", "col": "dist_cur_vah", "bounce_dir": "sell"},
    {"name": "cur_VAL", "col": "dist_cur_val", "bounce_dir": "buy"},
    # Swing
    {"name": "swing_high", "col": "dist_swing_high", "bounce_dir": "sell"},
    {"name": "swing_low", "col": "dist_swing_low", "bounce_dir": "buy"},
    # IB
    {"name": "IB_high", "col": "dist_ib_high", "bounce_dir": "sell"},
    {"name": "IB_low", "col": "dist_ib_low", "bounce_dir": "buy"},
    # VWAP SD bands
    {"name": "VWAP_D", "col": "dist_vwap_d", "bounce_dir": "both"},
    {"name": "VWAP_SD1U", "col": "dist_vwap_d_sd1u", "bounce_dir": "sell"},
    {"name": "VWAP_SD1D", "col": "dist_vwap_d_sd1d", "bounce_dir": "buy"},
    {"name": "VWAP_SD2U", "col": "dist_vwap_d_sd2u", "bounce_dir": "sell"},
    {"name": "VWAP_SD2D", "col": "dist_vwap_d_sd2d", "bounce_dir": "buy"},
    # Options
    {"name": "MQ_call", "col": "dist_mq_call", "bounce_dir": "sell"},
    {"name": "MQ_put", "col": "dist_mq_put", "bounce_dir": "buy"},
    {"name": "MQ_HVL", "col": "dist_mq_hvl", "bounce_dir": "both"},
    {"name": "MQ_call_0DTE", "col": "dist_mq_call_0dte", "bounce_dir": "sell"},
    {"name": "MQ_put_0DTE", "col": "dist_mq_put_0dte", "bounce_dir": "buy"},
    # Session
    {"name": "sess_high", "col": "dist_sess_high", "bounce_dir": "sell"},
    {"name": "sess_low", "col": "dist_sess_low", "bounce_dir": "buy"},
    # OVN
    {"name": "OVN_high", "col": "dist_ovn_high", "bounce_dir": "sell"},
    {"name": "OVN_low", "col": "dist_ovn_low", "bounce_dir": "buy"},
    # Open
    {"name": "open_cash", "col": "dist_open_cash", "bounce_dir": "both"},
    # Previous VWAP SD bands
    {"name": "prev_VWAP_SD1U", "col": "dist_prev_vwap_sd1u", "bounce_dir": "sell"},
    {"name": "prev_VWAP_SD1D", "col": "dist_prev_vwap_sd1d", "bounce_dir": "buy"},
    # VWAP SD3 (extremes)
    {"name": "VWAP_SD3U", "col": "dist_vwap_d_sd3u", "bounce_dir": "sell"},
    {"name": "VWAP_SD3D", "col": "dist_vwap_d_sd3d", "bounce_dir": "buy"},
    # VWAP Weekly / Monthly
    {"name": "VWAP_W", "col": "dist_vwap_w", "bounce_dir": "both"},
    {"name": "VWAP_M", "col": "dist_vwap_m", "bounce_dir": "both"},
    # Open 8:30
    {"name": "open_830", "col": "dist_open_830", "bounce_dir": "both"},
    # Composites 20d
    {"name": "comp_20d_VPOC", "col": "dist_comp_20d_vpoc", "bounce_dir": "both"},
    {"name": "comp_20d_VAH", "col": "dist_comp_20d_vah", "bounce_dir": "sell"},
    {"name": "comp_20d_VAL", "col": "dist_comp_20d_val", "bounce_dir": "buy"},
    {"name": "comp_20d_VWAP", "col": "dist_comp_20d_vwap", "bounce_dir": "both"},
    # Composites 50d
    {"name": "comp_50d_VPOC", "col": "dist_comp_50d_vpoc", "bounce_dir": "both"},
    {"name": "comp_50d_VAH", "col": "dist_comp_50d_vah", "bounce_dir": "sell"},
    {"name": "comp_50d_VAL", "col": "dist_comp_50d_val", "bounce_dir": "buy"},
    {"name": "comp_50d_VWAP", "col": "dist_comp_50d_vwap", "bounce_dir": "both"},
    # VIX Gamma
    {"name": "VIX_put", "col": "dist_vix_put", "bounce_dir": "buy"},
    {"name": "VIX_call", "col": "dist_vix_call", "bounce_dir": "sell"},
    {"name": "VIX_HVL", "col": "dist_vix_hvl", "bounce_dir": "both"},
    # GEX nearest
    {"name": "GEX_up", "col": "dist_gex_nearest_up", "bounce_dir": "sell"},
    {"name": "GEX_dn", "col": "dist_gex_nearest_dn", "bounce_dir": "buy"},
    # Blind Spots (LVN footprint)
    {"name": "blind_up", "col": "dist_blind_nearest_up", "bounce_dir": "sell"},
    {"name": "blind_dn", "col": "dist_blind_nearest_dn", "bounce_dir": "buy"},
    # Session Profile HVN/LVN
    {"name": "sess_HVN_above", "col": "dist_session_hvn_above", "bounce_dir": "sell"},
    {"name": "sess_HVN_below", "col": "dist_session_hvn_below", "bounce_dir": "buy"},
    {"name": "sess_LVN_above", "col": "dist_session_lvn_above", "bounce_dir": "sell"},
    {"name": "sess_LVN_below", "col": "dist_session_lvn_below", "bounce_dir": "buy"},
    # Edge Zones (footprint extension lines)
    {"name": "edge_buy", "col": "dist_ext_edge_buy", "bounce_dir": "buy"},
    {"name": "edge_sell", "col": "dist_ext_edge_sell", "bounce_dir": "sell"},
    # Big Orders (quand detectes)
    {"name": "big_ask_up", "col": "dist_big_ask_nearest_up", "bounce_dir": "sell"},
    {"name": "big_ask_dn", "col": "dist_big_ask_nearest_dn", "bounce_dir": "sell"},
    {"name": "big_bid_up", "col": "dist_big_bid_nearest_up", "bounce_dir": "buy"},
    {"name": "big_bid_dn", "col": "dist_big_bid_nearest_dn", "bounce_dir": "buy"},
]

# Niveaux signal-based (pas de dist_*, detectes par valeur de colonne)
SIGNAL_LEVELS_CONFIG = [
    {"name": "delta_div_BUY", "col": "delta_divergence", "bounce_dir": "buy",
     "signal_val": 1, "desc": "Extension line divergence delta bullish"},
    {"name": "delta_div_SELL", "col": "delta_divergence", "bounce_dir": "sell",
     "signal_val": -1, "desc": "Extension line divergence delta bearish"},
]


# ─────────────────────────────────────────────────────────────────────
# DATACLASS
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TouchEvent:
    """Un evenement de contact avec un niveau."""
    level_name: str
    bar_idx: int
    ts: int
    price: float
    dist_ticks: float
    direction: str          # "approaching_from_below" ou "approaching_from_above"
    # Contexte
    rvol: float = 0.0
    delta_bar: float = 0.0
    delta_pct: float = 0.0
    absorb_bid: float = 0.0
    absorb_ask: float = 0.0
    vix_level: float = 0.0
    session: int = 0
    atr: float = 0.0
    # Resultats
    bounce: bool = False
    breakout: bool = False
    magnitude_ticks: float = 0.0
    time_to_react: int = 0
    penetration_depth: float = 0.0
    mae: dict = field(default_factory=dict)    # {3: x, 5: x, 10: x, 20: x}
    mfe: dict = field(default_factory=dict)
    r_multiple: float = 0.0


# ─────────────────────────────────────────────────────────────────────
# CORE ENGINE
# ─────────────────────────────────────────────────────────────────────

def get_field(row, col, default=0.0):
    """Extrait un champ d'une row pandas avec fallback."""
    val = row.get(col, default)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return float(val)


def detect_touches(df: pd.DataFrame, levels: list[dict],
                   threshold: int = TOUCH_THRESHOLD,
                   cooldown: int = 10) -> list[TouchEvent]:
    """Detecte les barres ou le prix touche un niveau cle.

    Args:
        df: DataFrame avec colonnes dist_*, prix, volume, etc.
        levels: Config des niveaux (name, col, bounce_dir)
        threshold: Seuil de proximite en ticks
        cooldown: Barres minimum entre 2 touches du meme niveau

    Returns:
        Liste de TouchEvent
    """
    if "price" not in df.columns or df.empty:
        return []

    touches = []
    prices = df["price"].values
    n = len(df)

    # --- A. Niveaux distance-based (dist_* columns) ---
    for lvl in levels:
        col = lvl["col"]
        if col not in df.columns:
            continue

        dists = df[col].values
        last_touch_idx = -cooldown - 1

        for i in range(n):
            dist = dists[i]
            if pd.isna(dist):
                continue

            dist = float(dist)
            if abs(dist) > threshold:
                continue

            if i - last_touch_idx < cooldown:
                continue
            last_touch_idx = i

            if i > 0:
                prev_dist = dists[i - 1]
                if not pd.isna(prev_dist):
                    direction = "from_below" if float(prev_dist) > dist else "from_above"
                else:
                    direction = "unknown"
            else:
                direction = "unknown"

            row = df.iloc[i]
            touch = TouchEvent(
                level_name=lvl["name"],
                bar_idx=i,
                ts=int(get_field(row, "ts", 0)),
                price=prices[i],
                dist_ticks=dist,
                direction=direction,
                rvol=get_field(row, "rvol"),
                delta_bar=get_field(row, "delta_bar"),
                delta_pct=get_field(row, "delta_pct"),
                absorb_bid=get_field(row, "bn_absorb_bid"),
                absorb_ask=get_field(row, "bn_absorb_ask"),
                vix_level=get_field(row, "vix_level"),
                session=int(get_field(row, "session", 0)),
                atr=get_field(row, "atr"),
            )
            touches.append(touch)

    # --- B. Niveaux signal-based (delta_divergence, etc.) ---
    for slvl in SIGNAL_LEVELS_CONFIG:
        col = slvl["col"]
        if col not in df.columns:
            continue

        vals = df[col].values
        target = slvl["signal_val"]
        last_touch_idx = -cooldown - 1

        for i in range(n):
            v = vals[i]
            if pd.isna(v) or float(v) != target:
                continue

            # Cooldown : eviter de fire chaque barre pendant que le signal est actif
            if i - last_touch_idx < cooldown:
                continue

            # Transition : signal doit venir d'apparaitre (barre precedente != target)
            if i > 0 and not pd.isna(vals[i - 1]) and float(vals[i - 1]) == target:
                continue
            last_touch_idx = i

            direction = "from_below" if target > 0 else "from_above"

            row = df.iloc[i]
            touch = TouchEvent(
                level_name=slvl["name"],
                bar_idx=i,
                ts=int(get_field(row, "ts", 0)),
                price=prices[i],
                dist_ticks=0.0,
                direction=direction,
                rvol=get_field(row, "rvol"),
                delta_bar=get_field(row, "delta_bar"),
                delta_pct=get_field(row, "delta_pct"),
                absorb_bid=get_field(row, "bn_absorb_bid"),
                absorb_ask=get_field(row, "bn_absorb_ask"),
                vix_level=get_field(row, "vix_level"),
                session=int(get_field(row, "session", 0)),
                atr=get_field(row, "atr"),
            )
            touches.append(touch)

    return touches


def compute_touch_metrics(df: pd.DataFrame, touches: list[TouchEvent],
                          horizons: list[int] = HORIZONS,
                          bounce_min: int = BOUNCE_MIN_TICKS) -> list[TouchEvent]:
    """Calcule MAE/MFE/bounce/breakout pour chaque touch.

    Args:
        df: DataFrame complet de la session
        touches: Liste de TouchEvent detectes
        horizons: Barres a analyser (3, 5, 10, 20)
        bounce_min: Ticks minimum pour qualifier un bounce
    """
    prices = df["price"].values
    highs = df["bar_high"].values if "bar_high" in df.columns else prices
    lows = df["bar_low"].values if "bar_low" in df.columns else prices
    n = len(prices)

    for touch in touches:
        i = touch.bar_idx
        entry = touch.price

        # Determiner la direction attendue du bounce
        if touch.direction == "from_below":
            # Prix monte vers le niveau → bounce = rejet vers le bas
            sign = -1
        elif touch.direction == "from_above":
            # Prix descend vers le niveau → bounce = rebond vers le haut
            sign = 1
        else:
            sign = 0

        # MAE et MFE par horizon
        for h in horizons:
            end = min(i + h, n)
            if end <= i:
                touch.mae[h] = 0.0
                touch.mfe[h] = 0.0
                continue

            future_highs = highs[i + 1:end]
            future_lows = lows[i + 1:end]

            if len(future_highs) == 0:
                touch.mae[h] = 0.0
                touch.mfe[h] = 0.0
                continue

            if sign >= 0:
                # Attendu haussier (bounce up)
                mfe = (np.max(future_highs) - entry) / TICK_SIZE
                mae = (entry - np.min(future_lows)) / TICK_SIZE
            else:
                # Attendu baissier (bounce down)
                mfe = (entry - np.min(future_lows)) / TICK_SIZE
                mae = (np.max(future_highs) - entry) / TICK_SIZE

            touch.mae[h] = round(float(mae), 1)
            touch.mfe[h] = round(float(mfe), 1)

        # Magnitude : deplacement net en 10 barres
        h10 = min(i + 10, n - 1)
        touch.magnitude_ticks = round((prices[h10] - entry) / TICK_SIZE * (sign if sign != 0 else 1), 1)

        # Bounce vs Breakout (sur horizon 10 barres)
        mfe_10 = touch.mfe.get(10, 0)
        mae_10 = touch.mae.get(10, 0)

        if mfe_10 >= bounce_min:
            touch.bounce = True
        if mae_10 >= bounce_min and mfe_10 < bounce_min:
            touch.breakout = True

        # Time to React : premiere barre ou le prix bouge >= 4 ticks
        for j in range(i + 1, min(i + 20, n)):
            move = abs(prices[j] - entry) / TICK_SIZE
            if move >= 4:
                touch.time_to_react = j - i
                break

        # Penetration depth : max excursion au-dela du niveau
        level_col = next((l["col"] for l in LEVELS_CONFIG if l["name"] == touch.level_name), None)
        if level_col and level_col in df.columns:
            dists_slice = df[level_col].values[i:min(i + 10, n)]
            valid_dists = [float(d) for d in dists_slice if not pd.isna(d)]
            if sign > 0:
                cross = [abs(d) for d in valid_dists if d < 0]
            elif sign < 0:
                cross = [abs(d) for d in valid_dists if d > 0]
            else:
                cross = []
            touch.penetration_depth = round(max(cross), 1) if cross else abs(touch.dist_ticks)
        else:
            # Signal-based levels : MAE = penetration adverse
            touch.penetration_depth = touch.mae.get(10, 0.0)

        # R-multiple (si ATR disponible)
        if touch.atr > 0:
            sl_ticks = touch.atr * 0.08
            if sl_ticks > 0:
                touch.r_multiple = round(mfe_10 / sl_ticks, 2)

    return touches


# ─────────────────────────────────────────────────────────────────────
# AGGREGATION
# ─────────────────────────────────────────────────────────────────────

def aggregate_by_level(touches: list[TouchEvent]) -> dict:
    """Agrege les stats par niveau.

    Returns:
        {level_name: {bounce_rate, avg_magnitude, count, ...}}
    """
    by_level = {}
    for t in touches:
        if t.level_name not in by_level:
            by_level[t.level_name] = []
        by_level[t.level_name].append(t)

    stats = {}
    for name, events in by_level.items():
        n = len(events)
        bounces = sum(1 for e in events if e.bounce)
        breakouts = sum(1 for e in events if e.breakout)
        magnitudes = [e.magnitude_ticks for e in events]
        mfe_10 = [e.mfe.get(10, 0) for e in events]
        mae_10 = [e.mae.get(10, 0) for e in events]
        ttrs = [e.time_to_react for e in events if e.time_to_react > 0]
        rvols = [e.rvol for e in events]
        r_multiples = [e.r_multiple for e in events if e.r_multiple > 0]

        avg_mfe = np.mean(mfe_10) if mfe_10 else 0
        avg_mae = np.mean(mae_10) if mae_10 else 0

        stats[name] = {
            "count": n,
            "bounces": bounces,
            "breakouts": breakouts,
            "neutral": n - bounces - breakouts,
            "bounce_rate": round(bounces / n, 3) if n > 0 else 0,
            "breakout_rate": round(breakouts / n, 3) if n > 0 else 0,
            "avg_magnitude": round(float(np.mean(magnitudes)), 1) if magnitudes else 0,
            "median_magnitude": round(float(np.median(magnitudes)), 1) if magnitudes else 0,
            "avg_mfe_10": round(float(avg_mfe), 1),
            "avg_mae_10": round(float(avg_mae), 1),
            "mfe_mae_ratio": round(avg_mfe / max(avg_mae, 1e-6), 2) if avg_mae > 0 else 0.0,
            "median_ttr": int(np.median(ttrs)) if ttrs else 0,
            "avg_rvol_at_touch": round(float(np.mean(rvols)), 2) if rvols else 0,
            "avg_r_multiple": round(float(np.mean(r_multiples)), 2) if r_multiples else 0,
        }

    return stats


def compute_confluence(df: pd.DataFrame, levels: list[dict],
                       threshold: int = 10) -> pd.Series:
    """Calcule le nombre de niveaux confluents dans un rayon de N ticks.

    Returns:
        Series avec le count de niveaux proches par barre
    """
    confluence = pd.Series(0, index=df.index)
    for lvl in levels:
        col = lvl["col"]
        if col not in df.columns:
            continue
        dists = df[col].abs()
        confluence += (dists <= threshold).astype(int)
    return confluence


# ─────────────────────────────────────────────────────────────────────
# ADAPTIVE FEATURES (pour le ML)
# ─────────────────────────────────────────────────────────────────────

def compute_level_reliability(all_sessions_stats: list[dict],
                              decay: float = 0.95) -> dict:
    """Calcule un score de fiabilite par niveau avec decay exponentiel.

    Args:
        all_sessions_stats: Liste de dicts {date, symbol, stats}
            ou stats = output de aggregate_by_level()
        decay: Facteur de decay par session (0.95 = perd 5% par jour)

    Returns:
        {level_name: reliability_score}
    """
    # Trier par date (plus recent en dernier)
    sorted_sessions = sorted(all_sessions_stats, key=lambda x: x["date"])
    n_sessions = len(sorted_sessions)

    reliability = {}
    for session_idx, session in enumerate(sorted_sessions):
        age = n_sessions - 1 - session_idx  # 0 = plus recent
        weight = decay ** age

        for level_name, stats in session.get("stats", {}).items():
            if level_name not in reliability:
                reliability[level_name] = {"weighted_bounces": 0, "weighted_total": 0}

            reliability[level_name]["weighted_bounces"] += stats["bounces"] * weight
            reliability[level_name]["weighted_total"] += stats["count"] * weight

    result = {}
    for name, r in reliability.items():
        total = r["weighted_total"]
        result[name] = {
            "reliability_score": round(r["weighted_bounces"] / total, 3) if total > 0 else 0,
            "weighted_touches": round(total, 1),
        }
    return result


# ─────────────────────────────────────────────────────────────────────
# REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────

def generate_session_report(symbol: str, date: str, df: pd.DataFrame,
                            touches: list[TouchEvent],
                            stats: dict) -> dict:
    """Genere un rapport JSON pour une session."""
    n_bars = len(df)
    n_us = int((df["session"] == 2).sum()) if "session" in df.columns else n_bars

    # Top niveaux par bounce rate (min 2 touches)
    ranked = sorted(
        [(name, s) for name, s in stats.items() if s["count"] >= 2],
        key=lambda x: x[1]["bounce_rate"],
        reverse=True,
    )

    # Niveaux casses (breakout_rate > 50%)
    broken = [(name, s) for name, s in stats.items()
              if s["count"] >= 2 and s["breakout_rate"] > 0.5]

    # Resume
    total_touches = sum(s["count"] for s in stats.values())
    total_bounces = sum(s["bounces"] for s in stats.values())
    total_breakouts = sum(s["breakouts"] for s in stats.values())

    report = {
        "date": date,
        "symbol": symbol,
        "bars_total": n_bars,
        "bars_us": n_us,
        "summary": {
            "total_touches": total_touches,
            "total_bounces": total_bounces,
            "total_breakouts": total_breakouts,
            "global_bounce_rate": round(total_bounces / max(total_touches, 1), 3),
            "levels_analyzed": len(stats),
        },
        "top_levels": [
            {"name": name, "bounce_rate": s["bounce_rate"], "count": s["count"],
             "avg_mfe": s["avg_mfe_10"], "mfe_mae_ratio": s["mfe_mae_ratio"]}
            for name, s in ranked[:10]
        ],
        "broken_levels": [
            {"name": name, "breakout_rate": s["breakout_rate"], "count": s["count"]}
            for name, s in broken
        ],
        "level_stats": stats,
        "touches": [
            {
                "level": t.level_name,
                "bar_idx": t.bar_idx,
                "price": t.price,
                "direction": t.direction,
                "bounce": t.bounce,
                "breakout": t.breakout,
                "magnitude": t.magnitude_ticks,
                "mfe_10": t.mfe.get(10, 0),
                "mae_10": t.mae.get(10, 0),
                "rvol": t.rvol,
                "delta_bar": t.delta_bar,
                "ttr": t.time_to_react,
            }
            for t in touches
        ],
    }
    return report


def print_report(report: dict):
    """Affiche un rapport lisible."""
    sym = report["symbol"]
    date = report["date"]
    s = report["summary"]

    print(f"\n{'='*60}")
    print(f"  SESSION REPLAY — {sym} {date}")
    print(f"{'='*60}")
    print(f"  Barres: {report['bars_total']} total, {report['bars_us']} US")
    print(f"  Touches: {s['total_touches']} | Bounces: {s['total_bounces']} | "
          f"Breakouts: {s['total_breakouts']}")
    print(f"  Bounce Rate Global: {s['global_bounce_rate']*100:.1f}%")

    if report["top_levels"]:
        print(f"\n  --- TOP NIVEAUX (bounce rate, min 2 touches) ---")
        for lv in report["top_levels"]:
            bar = "#" * int(lv["bounce_rate"] * 20)
            print(f"  {lv['name']:20s} {lv['bounce_rate']*100:5.1f}% "
                  f"[{bar:20s}] n={lv['count']} MFE={lv['avg_mfe']:.1f}t "
                  f"ratio={lv['mfe_mae_ratio']:.1f}")

    if report["broken_levels"]:
        print(f"\n  --- NIVEAUX CASSES (breakout > 50%) ---")
        for lv in report["broken_levels"]:
            print(f"  {lv['name']:20s} breakout={lv['breakout_rate']*100:.0f}% n={lv['count']}")

    print(f"\n{'='*60}\n")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def analyze_session(symbol: str, date: str, reader: DmpReader) -> dict | None:
    """Analyse une session complete."""
    df = reader.load(symbol, date)
    if df.empty:
        return None

    # Filtrer US only si possible
    df_us = reader.us_only(df)
    if df_us.empty:
        df_us = df

    # Detecter les touches
    touches = detect_touches(df_us, LEVELS_CONFIG)
    if not touches:
        print(f"  [{symbol} {date}] Aucune touch detectee")
        return None

    # Calculer les metriques
    touches = compute_touch_metrics(df_us, touches)

    # Agreger par niveau
    stats = aggregate_by_level(touches)

    # Generer le rapport
    report = generate_session_report(symbol, date, df_us, touches, stats)
    return report


def run_all(symbols: list[str] = None, target_date: str = None):
    """Lance l'analyse sur toutes les sessions disponibles."""
    if symbols is None:
        symbols = ["ES", "NQ"]

    reader = DmpReader(DATA_DIR)
    os.makedirs(REPORT_DIR, exist_ok=True)

    all_reports = []

    for sym in symbols:
        data_dir = os.path.join(DATA_DIR, sym)
        pattern = os.path.join(data_dir, f"*_{sym}.jsonl")
        files = sorted(glob(pattern))

        for fpath in files:
            fname = os.path.basename(fpath)
            date_str = fname.split("_")[0]

            # Skip weekend (< 100KB)
            try:
                if os.path.getsize(fpath) < 100000:
                    continue
            except OSError:
                continue

            # Filtrer par date si specifie
            if target_date:
                target_compact = target_date.replace("-", "")
                if date_str != target_compact:
                    continue

            date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            print(f"  [{sym}] Analyse {date_fmt}...")

            report = analyze_session(sym, date_fmt, reader)
            if report:
                print_report(report)

                # Sauvegarder le rapport
                out_path = os.path.join(REPORT_DIR, f"{date_str}_{sym}_replay.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2, ensure_ascii=False, default=str)

                all_reports.append({
                    "date": date_fmt,
                    "symbol": sym,
                    "stats": report["level_stats"],
                })

    # Stats cumulees avec decay
    if all_reports:
        for sym in symbols:
            sym_reports = [r for r in all_reports if r["symbol"] == sym]
            if not sym_reports:
                continue

            reliability = compute_level_reliability(sym_reports)

            print(f"\n{'='*60}")
            print(f"  FIABILITE CUMULEE — {sym} ({len(sym_reports)} sessions, decay=0.95)")
            print(f"{'='*60}")

            ranked = sorted(reliability.items(),
                            key=lambda x: x[1]["reliability_score"], reverse=True)
            for name, r in ranked:
                if r["weighted_touches"] < 1:
                    continue
                bar = "#" * int(r["reliability_score"] * 20)
                print(f"  {name:20s} {r['reliability_score']*100:5.1f}% "
                      f"[{bar:20s}] touches={r['weighted_touches']:.1f}")

            # Sauvegarder
            stats_path = os.path.join(REPORT_DIR, f"level_reliability_{sym}.json")
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump({"symbol": sym, "sessions": len(sym_reports),
                           "decay": 0.95, "levels": reliability},
                          f, indent=2, ensure_ascii=False)
            print(f"  Sauvegarde: {stats_path}")

    print(f"\n  Total: {len(all_reports)} sessions analysees")
    return all_reports


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MIA Session Replay Analyzer")
    parser.add_argument("--date", type=str, default=None,
                        help="Date specifique (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Symbole (ES ou NQ)")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else None
    run_all(symbols=symbols, target_date=args.date)
