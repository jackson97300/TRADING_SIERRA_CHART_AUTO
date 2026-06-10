"""
edge_discovery.py — Script d'analyse edge discovery pour MIA IA System

Usage Claude Code :
    python edge_discovery.py --data-dir DATA/MENTHORQ/ --symbol NQ --output DOCS/EDGE_REPORT.md

Ce que ce script fait :
    1. Charge tous les JSONL (1 par jour) d'un symbole
    2. Identifie les gros moves (>X ticks en 15 min)
    3. Compare les features AVANT les gros moves vs barres neutres
    4. Détecte les combinaisons de features qui prédisent les moves
    5. Teste des setups rules-based avec win rate + PF
    6. Génère un rapport avec les meilleurs setups trouvés

Vision Jackson : Market Profile + niveaux veille + VWAP + options MQ + OrderFlow
"""

from __future__ import annotations
import json
import glob
import argparse
from pathlib import Path
from typing import Optional
from collections import defaultdict

import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════════════
# 1. CHARGEMENT DONNÉES
# ═══════════════════════════════════════════════════════════════════

def load_all_jsonl(data_dir: str, symbol: str = "NQ") -> pd.DataFrame:
    """Charge tous les fichiers JSONL pour un symbole.

    Cherche récursivement :
      - {data_dir}/*_{symbol}.jsonl
      - {data_dir}/**/*_{symbol}.jsonl
      - {data_dir}/*.jsonl (filtre par sym col)
    """
    patterns = [
        f"{data_dir}/*_{symbol}.jsonl",
        f"{data_dir}/**/*_{symbol}.jsonl",
        f"{data_dir}/{symbol}/*.jsonl",
        f"{data_dir}/**/{symbol}*.jsonl",
    ]

    files = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))
    files = sorted(set(files))

    if not files:
        # Fallback : charger tout et filtrer
        all_jsonl = sorted(glob.glob(f"{data_dir}/**/*.jsonl", recursive=True))
        files = [f for f in all_jsonl if symbol.lower() in f.lower()]

    if not files:
        print(f"[ERREUR] Aucun fichier JSONL trouvé pour {symbol} dans {data_dir}")
        print(f"  Patterns testés : {patterns}")
        print(f"  Essayez : python edge_discovery.py --data-dir <chemin> --symbol {symbol}")
        return pd.DataFrame()

    print(f"[LOAD] {len(files)} fichiers JSONL trouvés pour {symbol}")

    all_bars = []
    for f in files:
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    all_bars.append(json.loads(line))
        except Exception as e:
            print(f"  [WARN] Erreur lecture {f}: {e}")

    if not all_bars:
        print("[ERREUR] 0 barres chargées")
        return pd.DataFrame()

    df = pd.DataFrame(all_bars)
    df['ts_dt'] = pd.to_datetime(df['ts'], unit='ms')
    df = df.sort_values('ts_dt').reset_index(drop=True)

    # Identifier session date
    df['session_date'] = df['ts_dt'].dt.date

    print(f"[LOAD] {len(df)} barres, {df['session_date'].nunique()} jours")
    print(f"  Période : {df['ts_dt'].iloc[0]} → {df['ts_dt'].iloc[-1]}")
    print(f"  Sessions : {df['session_id'].value_counts().to_dict() if 'session_id' in df.columns else 'N/A'}")

    return df


# ═══════════════════════════════════════════════════════════════════
# 2. CALCUL FORWARD MOVES (le "label" pour l'analyse)
# ═══════════════════════════════════════════════════════════════════

def add_forward_moves(df: pd.DataFrame, horizons: list = None) -> pd.DataFrame:
    """Ajoute les moves forward par session (pas cross-session).

    Pour chaque barre, calcule le move en ticks dans les N prochaines minutes.
    IMPORTANT : ne traverse pas les sessions (pas de move overnight).
    """
    if horizons is None:
        horizons = [5, 15, 30, 60]

    out = df.copy()

    for h in horizons:
        out[f'fwd_{h}m_ticks'] = np.nan

    # Calcul par session_date pour éviter les moves cross-session
    for date, group in out.groupby('session_date'):
        idx = group.index
        price = group['price'].values
        for h in horizons:
            fwd = np.full(len(price), np.nan)
            for i in range(len(price) - h):
                fwd[i] = (price[i + h] - price[i]) * 4  # en ticks NQ
            out.loc[idx, f'fwd_{h}m_ticks'] = fwd

    return out


# ═══════════════════════════════════════════════════════════════════
# 3. CLASSIFICATION DES BARRES
# ═══════════════════════════════════════════════════════════════════

def classify_bars(df: pd.DataFrame,
                  horizon: int = 15,
                  threshold_big: int = 100,
                  threshold_neutral: int = 30) -> pd.DataFrame:
    """Classifie chaque barre en SHORT_WIN, LONG_WIN, NEUTRAL, ou SMALL."""
    col = f'fwd_{horizon}m_ticks'
    if col not in df.columns:
        raise ValueError(f"Colonne {col} absente. Lancer add_forward_moves d'abord.")

    conditions = [
        df[col] < -threshold_big,
        df[col] > threshold_big,
        (df[col] >= -threshold_neutral) & (df[col] <= threshold_neutral),
    ]
    choices = ['SHORT_WIN', 'LONG_WIN', 'NEUTRAL']
    df['bar_class'] = np.select(conditions, choices, default='SMALL_MOVE')

    # Stats
    counts = df['bar_class'].value_counts()
    print(f"\n[CLASSIFY] Horizon {horizon}min, seuil >{threshold_big}t :")
    for cls in ['SHORT_WIN', 'LONG_WIN', 'NEUTRAL', 'SMALL_MOVE']:
        n = counts.get(cls, 0)
        pct = n / len(df) * 100
        print(f"  {cls:<12}: {n:>5} ({pct:.1f}%)")

    return df


# ═══════════════════════════════════════════════════════════════════
# 4. FEATURE EDGE DETECTOR
# ═══════════════════════════════════════════════════════════════════

# Features à analyser, groupées par ta vision
FEATURE_GROUPS = {
    "MARKET_PROFILE": [
        "va_position_pct", "inside_cur_va", "range_pos", "dist_cur_vpoc",
        "profile_shape", "poc_position", "inside_comp_20d_va",
        "dist_comp_20d_vpoc", "dist_comp_20d_vah", "dist_comp_20d_val",
    ],
    "NIVEAUX_VEILLE": [
        "dist_prev_vpoc", "dist_prev_vah", "dist_prev_val",
        "inside_prev_va", "open_in_prev_va",
        "dist_sess_high", "dist_sess_low", "dist_open_cash",
    ],
    "VWAP": [
        "dist_vwap_d", "dist_vwap_d_atr", "dist_vwap_w", "dist_vwap_m",
        "vwap_triple_align", "vwap_slope_10", "vwap_slope_30",
        "bool_above_vwap_d", "bool_above_vwap_w", "bool_above_vwap_m",
        "dist_vwap_d_sd1u", "dist_vwap_d_sd1d",
        "dist_vwap_d_sd2u", "dist_vwap_d_sd2d",
    ],
    "OPTIONS_MQ": [
        "dist_mq_call", "dist_mq_put", "dist_mq_hvl",
        "dist_mq_call_0dte", "dist_mq_put_0dte",
        "dist_gex_nearest_up", "dist_gex_nearest_dn",
        "gex_cluster_count", "bool_above_mq_hvl",
        "vix_level", "vix_regime",
        "next_wall_dist_ticks", "next_wall_is_call",
    ],
    "ORDERFLOW": [
        "delta_bar", "delta_day", "delta_day_dir",
        "cvd_day", "cvd_day_dir", "cvd_bar_delta",
        "ask_bid_imbalance", "buy_sell_ratio",
        "delta_divergence", "finish_strength",
        "large_trader_ratio", "rvol", "rvol_zscore",
        "avg_trade_size", "vol_per_sec",
        "bn_score_bull", "bn_score_bear",
        "diag_imbalance", "delta_pct",
    ],
    "STRUCTURE": [
        "dist_swing_high", "dist_swing_low", "swing_range_ticks",
        "new_swing_high", "new_swing_low",
        "momentum_3b", "momentum_5b",
        "ib_range_ticks", "ib_broken_up", "ib_broken_down",
        "open_type", "day_type", "open_bias_conf",
    ],
}


def compute_feature_edge(df: pd.DataFrame,
                         min_samples: int = 20) -> pd.DataFrame:
    """Compare chaque feature entre SHORT_WIN, LONG_WIN et NEUTRAL.

    Retourne un DataFrame avec :
      - feature, group
      - mean_short, mean_long, mean_neutral
      - edge_short (% diff short vs neutral)
      - edge_long (% diff long vs neutral)
      - edge_score (combiné)
    """
    shorts = df[df['bar_class'] == 'SHORT_WIN']
    longs = df[df['bar_class'] == 'LONG_WIN']
    neutrals = df[df['bar_class'] == 'NEUTRAL']

    if len(shorts) < min_samples or len(longs) < min_samples or len(neutrals) < min_samples:
        print(f"[WARN] Pas assez de samples: SHORT={len(shorts)}, LONG={len(longs)}, NEUTRAL={len(neutrals)}")

    results = []
    for group_name, features in FEATURE_GROUPS.items():
        for feat in features:
            if feat not in df.columns:
                continue

            s_val = shorts[feat].mean() if len(shorts) > 0 else np.nan
            l_val = longs[feat].mean() if len(longs) > 0 else np.nan
            n_val = neutrals[feat].mean() if len(neutrals) > 0 else np.nan

            # Edge = % de différence vs neutral
            edge_short = 0
            edge_long = 0
            if not np.isnan(n_val) and abs(n_val) > 0.001:
                if not np.isnan(s_val):
                    edge_short = abs(s_val - n_val) / abs(n_val)
                if not np.isnan(l_val):
                    edge_long = abs(l_val - n_val) / abs(n_val)

            # T-test simplifié (différence significative ?)
            try:
                s_std = shorts[feat].std() if len(shorts) > 1 else np.nan
                n_std = neutrals[feat].std() if len(neutrals) > 1 else np.nan
                if not np.isnan(s_std) and s_std > 0 and not np.isnan(n_std) and n_std > 0:
                    t_stat = abs(s_val - n_val) / np.sqrt(
                        s_std**2 / len(shorts) + n_std**2 / len(neutrals)
                    )
                else:
                    t_stat = 0
            except Exception:
                t_stat = 0

            results.append({
                'group': group_name,
                'feature': feat,
                'mean_short': s_val,
                'mean_long': l_val,
                'mean_neutral': n_val,
                'edge_short': edge_short,
                'edge_long': edge_long,
                'edge_score': max(edge_short, edge_long),
                't_stat': t_stat,
            })

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values('edge_score', ascending=False)
    return result_df


# ═══════════════════════════════════════════════════════════════════
# 5. SETUP TESTER — teste des combinaisons de conditions
# ═══════════════════════════════════════════════════════════════════

# Setups prédéfinis basés sur la vision Jackson
SETUPS = [
    {
        "name": "SELL_OPEN_ABOVE_PREV_VA",
        "description": "Prix hors prev VA par le haut à l'open, CVD positif (piège bull)",
        "side": "SHORT",
        "conditions": {
            "inside_prev_va": ("==", 0),
            "dist_prev_vah": ("<", -500),
            "cvd_day_dir": ("==", 1),
            "session_early": True,  # flag spécial : 30 premières min RTH
        },
    },
    {
        "name": "BUY_PREV_VA_RECLAIM",
        "description": "Prix revient dans prev VA + CVD flip négatif (vendeurs épuisés)",
        "side": "LONG",
        "conditions": {
            "inside_prev_va": ("==", 1),
            "cvd_day_dir": ("==", -1),
            "dist_vwap_d": (">", 100),  # sous le VWAP daily
            "rvol": (">", 0.7),
        },
    },
    {
        "name": "SELL_VPOC_FAR_ABOVE",
        "description": "Prix très loin au-dessus du VPOC session = retour probable",
        "side": "SHORT",
        "conditions": {
            "dist_cur_vpoc": ("<", -300),
            "finish_strength": ("<", -10),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "BUY_VPOC_RECLAIM",
        "description": "Prix revient au VPOC session + delta positif = acheteurs reviennent",
        "side": "LONG",
        "conditions": {
            "dist_cur_vpoc": ("abs<", 100),
            "delta_bar": (">", 30),
            "rvol": (">", 0.8),
        },
    },
    {
        "name": "SELL_GEX_REJECTION",
        "description": "Prix proche niveau GEX down + delta négatif = rejet",
        "side": "SHORT",
        "conditions": {
            "dist_gex_nearest_dn": ("abs<", 80),
            "delta_bar": ("<", -30),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "BUY_GEX_SUPPORT",
        "description": "Prix rebondit sur GEX up + delta positif",
        "side": "LONG",
        "conditions": {
            "dist_gex_nearest_up": ("<", 100),
            "delta_bar": (">", 30),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "SELL_MQ_CALL_WALL",
        "description": "Prix au-dessus du MQ Call wall = résistance options",
        "side": "SHORT",
        "conditions": {
            "dist_mq_call": ("<", -150),
            "finish_strength": ("<", -10),
        },
    },
    {
        "name": "BUY_VWAP_RECLAIM_TREND",
        "description": "Prix traverse VWAP daily + slope positive = trend",
        "side": "LONG",
        "conditions": {
            "dist_vwap_d": ("abs<", 100),
            "vwap_slope_10": (">", 3),
            "rvol": (">", 0.5),
        },
    },
    {
        "name": "SELL_CVD_DIVERGENCE",
        "description": "Prix monte mais CVD descend = divergence bearish",
        "side": "SHORT",
        "conditions": {
            "cvd_day_dir": ("==", -1),
            "dist_vwap_d": ("<", -100),  # au-dessus du VWAP (prix haut)
            "range_pos": (">", 70),
        },
    },
    {
        "name": "BUY_CVD_DIVERGENCE",
        "description": "Prix descend mais CVD monte = divergence bullish",
        "side": "LONG",
        "conditions": {
            "cvd_day_dir": ("==", 1),
            "dist_vwap_d": (">", 100),  # sous le VWAP (prix bas)
            "range_pos": ("<", 30),
        },
    },
    {
        "name": "SELL_IB_BREAK_DOWN",
        "description": "IB cassée par le bas + delta négatif = continuation",
        "side": "SHORT",
        "conditions": {
            "ib_broken_down": ("==", 1),
            "delta_bar": ("<", -20),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "BUY_IB_BREAK_UP",
        "description": "IB cassée par le haut + delta positif = continuation",
        "side": "LONG",
        "conditions": {
            "ib_broken_up": ("==", 1),
            "delta_bar": (">", 20),
            "rvol": (">", 0.6),
        },
    },
    {
        "name": "BUY_EXTREME_LOW_RANGE",
        "description": "Prix au bas extrême du range + RVOL spike = reversal",
        "side": "LONG",
        "conditions": {
            "range_pos": ("<", 10),
            "rvol": (">", 1.5),
            "delta_bar": (">", 0),
        },
    },
    {
        "name": "SELL_EXTREME_HIGH_RANGE",
        "description": "Prix au haut extrême du range + finish faible",
        "side": "SHORT",
        "conditions": {
            "range_pos": (">", 95),
            "finish_strength": ("<", -20),
        },
    },
    {
        "name": "SELL_VWAP_SD2_REJECTION",
        "description": "Prix touche VWAP SD2 upper = suracheté, rejet probable",
        "side": "SHORT",
        "conditions": {
            "dist_vwap_d_sd2u": ("abs<", 50),
            "delta_bar": ("<", 0),
        },
    },
    {
        "name": "BUY_VWAP_SD2_SUPPORT",
        "description": "Prix touche VWAP SD2 lower = survendu, rebond probable",
        "side": "LONG",
        "conditions": {
            "dist_vwap_d_sd2d": ("abs<", 50),
            "delta_bar": (">", 0),
        },
    },
]


def apply_condition(series: pd.Series, op: str, value) -> pd.Series:
    """Applique une condition sur une Series pandas."""
    if op == "==":
        return series == value
    elif op == ">":
        return series > value
    elif op == "<":
        return series < value
    elif op == ">=":
        return series >= value
    elif op == "<=":
        return series <= value
    elif op == "abs<":
        return series.abs() < value
    elif op == "abs>":
        return series.abs() > value
    else:
        raise ValueError(f"Opérateur inconnu: {op}")


def test_setup(df: pd.DataFrame, setup: dict,
               horizon: int = 15, tick_value: float = 0.50) -> dict:
    """Teste un setup sur les données et retourne les métriques.

    Args:
        df: DataFrame avec ts_dt, price, fwd_Xm_ticks, features
        setup: dict avec name, side, conditions
        horizon: horizon forward en minutes
        tick_value: valeur d'un tick en $ (NQ=0.50, ES=1.25)

    Returns:
        dict avec n_triggers, win_rate, avg_move, pf, best, worst, etc.
    """
    fwd_col = f'fwd_{horizon}m_ticks'
    if fwd_col not in df.columns:
        return {"name": setup["name"], "error": f"Colonne {fwd_col} absente"}

    mask = pd.Series(True, index=df.index)

    for feat, cond in setup.get("conditions", {}).items():
        if feat == "session_early":
            if cond is True:
                if 'ts_dt' in df.columns:
                    mask &= (df['ts_dt'].dt.hour == 13) & (df['ts_dt'].dt.minute <= 30)
            continue
        if not isinstance(cond, (tuple, list)) or len(cond) != 2:
            continue
        op, value = cond
        if feat not in df.columns:
            mask &= False
            break
        mask &= apply_condition(df[feat], op, value)

    triggered = df[mask & df[fwd_col].notna()]

    if len(triggered) == 0:
        return {
            "name": setup["name"],
            "side": setup.get("side", "?"),
            "n_triggers": 0,
            "n_days": 0,
        }

    fwd = triggered[fwd_col].values
    side = setup.get("side", "LONG")

    # Ajuster le signe selon le side
    if side == "SHORT":
        pnl = -fwd  # short gagne quand fwd est négatif
    else:
        pnl = fwd  # long gagne quand fwd est positif

    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]

    win_rate = len(winners) / len(pnl) if len(pnl) > 0 else 0
    pf = (winners.sum() / -losers.sum()) if len(losers) > 0 and losers.sum() != 0 else 999
    avg_move = pnl.mean()
    n_days = triggered['session_date'].nunique()
    triggers_per_day = len(triggered) / max(n_days, 1)

    return {
        "name": setup["name"],
        "description": setup.get("description", ""),
        "side": side,
        "n_triggers": len(triggered),
        "n_days": n_days,
        "triggers_per_day": round(triggers_per_day, 1),
        "win_rate": round(win_rate * 100, 1),
        "pf": round(pf, 2),
        "avg_move_ticks": round(avg_move, 0),
        "avg_move_dollars": round(avg_move * tick_value, 2),
        "best_ticks": round(pnl.max(), 0),
        "worst_ticks": round(pnl.min(), 0),
        "max_consecutive_loss": _max_consecutive(pnl < 0),
        "total_pnl_ticks": round(pnl.sum(), 0),
    }


def _max_consecutive(bool_series) -> int:
    """Compte le max de True consécutifs."""
    arr = np.array(bool_series, dtype=int)
    if len(arr) == 0:
        return 0
    max_run = 0
    current = 0
    for v in arr:
        if v:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


# ═══════════════════════════════════════════════════════════════════
# 6. TIMING ANALYSIS
# ═══════════════════════════════════════════════════════════════════

def analyze_timing(df: pd.DataFrame, horizon: int = 15) -> pd.DataFrame:
    """Analyse les moves par tranche horaire."""
    fwd_col = f'fwd_{horizon}m_ticks'
    if fwd_col not in df.columns or 'ts_dt' not in df.columns:
        return pd.DataFrame()

    df_valid = df[df[fwd_col].notna()].copy()
    df_valid['hour_utc'] = df_valid['ts_dt'].dt.hour
    df_valid['half_hour'] = df_valid['hour_utc'] * 2 + (df_valid['ts_dt'].dt.minute >= 30).astype(int)

    results = []
    for hh, group in df_valid.groupby('half_hour'):
        h = hh // 2
        m = "00" if hh % 2 == 0 else "30"
        fwd = group[fwd_col]
        results.append({
            'time_utc': f"{h:02d}:{m}",
            'n_bars': len(group),
            'avg_move': round(fwd.mean(), 1),
            'big_short': int((fwd < -100).sum()),
            'big_long': int((fwd > 100).sum()),
            'win_long_pct': round((fwd > 0).mean() * 100, 1),
            'std': round(fwd.std(), 1),
        })

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════════
# 7. RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════

def generate_report(df: pd.DataFrame,
                    edge_df: pd.DataFrame,
                    setup_results: list,
                    timing_df: pd.DataFrame,
                    symbol: str,
                    output_path: str) -> str:
    """Génère le rapport Markdown complet."""

    lines = []
    lines.append(f"# EDGE DISCOVERY REPORT — {symbol}")
    lines.append(f"")
    lines.append(f"**Généré** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Données** : {df['session_date'].min()} → {df['session_date'].max()}")
    lines.append(f"**Barres** : {len(df)} ({df['session_date'].nunique()} jours)")
    lines.append(f"")

    # Section 1 : Top features avec edge
    lines.append(f"## 1. TOP FEATURES AVEC EDGE")
    lines.append(f"")
    lines.append(f"Features qui séparent le plus les gros moves (>100t) des barres neutres (<30t).")
    lines.append(f"Edge score = % de différence entre winners et neutral. Plus c'est haut, plus la feature est prédictive.")
    lines.append(f"")
    lines.append(f"| Rang | Groupe | Feature | Short Win | Long Win | Neutral | Edge % | T-stat |")
    lines.append(f"|------|--------|---------|-----------|----------|---------|--------|--------|")

    top_edges = edge_df.head(25)
    for i, row in top_edges.iterrows():
        rank = top_edges.index.get_loc(i) + 1
        stars = "⭐" * min(3, int(row['edge_score'] / 0.3))
        lines.append(
            f"| {rank} | {row['group'][:12]} | {row['feature'][:28]} | "
            f"{row['mean_short']:.1f} | {row['mean_long']:.1f} | {row['mean_neutral']:.1f} | "
            f"{row['edge_score']:.0%} {stars} | {row['t_stat']:.1f} |"
        )

    # Section 2 : Setups testés
    lines.append(f"")
    lines.append(f"## 2. SETUPS RULES-BASED TESTÉS")
    lines.append(f"")
    lines.append(f"| Setup | Side | Triggers | Jours | /jour | WR% | PF | Avg ticks | Best | Worst | Total PnL |")
    lines.append(f"|-------|------|----------|-------|-------|-----|-----|-----------|------|-------|-----------|")

    # Trier par PF décroissant
    valid_setups = [s for s in setup_results if s.get('n_triggers', 0) >= 5]
    valid_setups.sort(key=lambda x: x.get('pf', 0), reverse=True)

    for s in valid_setups:
        verdict = ""
        pf = s.get('pf', 0)
        wr = s.get('win_rate', 0)
        if pf >= 1.5 and wr >= 55:
            verdict = " ⭐⭐⭐"
        elif pf >= 1.3 and wr >= 50:
            verdict = " ⭐⭐"
        elif pf >= 1.1 and wr >= 45:
            verdict = " ⭐"

        lines.append(
            f"| {s['name'][:30]} | {s['side']} | {s['n_triggers']} | {s['n_days']} | "
            f"{s.get('triggers_per_day', 0)} | {wr:.0f}% | {pf:.2f} | "
            f"{s.get('avg_move_ticks', 0):+.0f} | {s.get('best_ticks', 0):+.0f} | "
            f"{s.get('worst_ticks', 0):+.0f} | {s.get('total_pnl_ticks', 0):+.0f}{verdict} |"
        )

    # Setups sans assez de triggers
    low_triggers = [s for s in setup_results if 0 < s.get('n_triggers', 0) < 5]
    if low_triggers:
        lines.append(f"")
        lines.append(f"*Setups avec < 5 triggers (insuffisant pour conclure) :*")
        for s in low_triggers:
            lines.append(f"- {s['name']} : {s['n_triggers']} triggers")

    # Section 3 : Timing
    if not timing_df.empty:
        lines.append(f"")
        lines.append(f"## 3. TIMING (par demi-heure UTC)")
        lines.append(f"")
        lines.append(f"| Heure UTC | Barres | Avg move | SHORT>100t | LONG>100t | Win Long % | Volatilité |")
        lines.append(f"|-----------|--------|---------|-----------|----------|-----------|-----------|")
        for _, row in timing_df.iterrows():
            bias = ""
            if row['avg_move'] < -50:
                bias = " 🔴"
            elif row['avg_move'] > 50:
                bias = " 🟢"
            lines.append(
                f"| {row['time_utc']} | {row['n_bars']} | {row['avg_move']:+.0f}t{bias} | "
                f"{row['big_short']} | {row['big_long']} | {row['win_long_pct']:.0f}% | {row['std']:.0f}t |"
            )

    # Section 4 : Recommandations
    lines.append(f"")
    lines.append(f"## 4. RECOMMANDATIONS")
    lines.append(f"")

    best_setups = [s for s in valid_setups if s.get('pf', 0) >= 1.3 and s.get('win_rate', 0) >= 50]
    if best_setups:
        lines.append(f"### Setups à déployer en observation (PF >= 1.3 + WR >= 50%) :")
        lines.append(f"")
        for s in best_setups:
            lines.append(f"- **{s['name']}** ({s['side']}) : PF {s['pf']:.2f}, WR {s['win_rate']:.0f}%, "
                        f"{s['n_triggers']} triggers sur {s['n_days']} jours")
            lines.append(f"  - {s.get('description', '')}")
        lines.append(f"")
        lines.append(f"### Action : coder ces setups dans le bot en mode OBSERVE-ONLY")
        lines.append(f"et collecter 100+ triggers pour valider sur données live.")
    else:
        lines.append(f"Aucun setup ne passe PF >= 1.3 + WR >= 50%.")
        lines.append(f"Augmenter les données (plus de jours) ou ajuster les conditions.")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*Généré par edge_discovery.py — MIA IA System*")

    report = "\n".join(lines)

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(report)
    print(f"\n[REPORT] Sauvegardé : {output_path}")

    return report


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Edge Discovery — MIA IA System")
    parser.add_argument("--data-dir", required=True, help="Répertoire avec les fichiers JSONL")
    parser.add_argument("--symbol", default="NQ", help="Symbole (NQ ou ES)")
    parser.add_argument("--output", default="DOCS/EDGE_REPORT.md", help="Chemin rapport output")
    parser.add_argument("--horizon", type=int, default=15, help="Horizon forward en minutes (default 15)")
    parser.add_argument("--threshold", type=int, default=100, help="Seuil gros move en ticks (default 100)")
    parser.add_argument("--rth-only", action="store_true", help="Filtrer RTH uniquement (session US)")
    parser.add_argument("--tick-value", type=float, default=0.50, help="Valeur tick en $ (NQ=0.50, ES=1.25)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"EDGE DISCOVERY — {args.symbol}")
    print(f"Data dir : {args.data_dir}")
    print(f"Horizon  : {args.horizon} min")
    print(f"Seuil    : {args.threshold} ticks")
    print("=" * 70)

    # 1. Load
    df = load_all_jsonl(args.data_dir, args.symbol)
    if df.empty:
        return

    # 2. Filter RTH si demandé
    if args.rth_only and 'session_id' in df.columns:
        n_before = len(df)
        df = df[df['session_id'] == 'US'].reset_index(drop=True)
        print(f"[RTH] Filtre US session : {n_before} → {len(df)} barres")

    # 3. Forward moves
    print(f"\n[FORWARD] Calcul moves {args.horizon}min par session...")
    df = add_forward_moves(df, horizons=[5, 15, 30, 60])

    # 4. Classification
    df = classify_bars(df, horizon=args.horizon, threshold_big=args.threshold)

    # 5. Feature edge
    print(f"\n[EDGE] Analyse {sum(len(v) for v in FEATURE_GROUPS.values())} features...")
    edge_df = compute_feature_edge(df)
    top10 = edge_df.head(10)
    print(f"\nTOP 10 features avec edge :")
    for _, row in top10.iterrows():
        stars = "⭐" * min(3, int(row['edge_score'] / 0.3))
        print(f"  {row['edge_score']:.0%} {stars} {row['group'][:10]:>10} / {row['feature']}")

    # 6. Test setups
    print(f"\n[SETUPS] Test {len(SETUPS)} setups prédéfinis...")
    setup_results = []
    for setup in SETUPS:
        result = test_setup(df, setup, horizon=args.horizon, tick_value=args.tick_value)
        setup_results.append(result)
        n = result.get('n_triggers', 0)
        if n > 0:
            pf = result.get('pf', 0)
            wr = result.get('win_rate', 0)
            avg = result.get('avg_move_ticks', 0)
            verdict = "⭐" if pf >= 1.3 and wr >= 50 else ""
            print(f"  {setup['name'][:35]:<35} {n:>4} triggers | WR {wr:>5.1f}% | PF {pf:>5.2f} | Avg {avg:>+6.0f}t {verdict}")

    # 7. Timing
    print(f"\n[TIMING] Analyse par tranche horaire...")
    timing_df = analyze_timing(df, horizon=args.horizon)

    # 8. Rapport
    report = generate_report(df, edge_df, setup_results, timing_df,
                            args.symbol, args.output)

    # Print summary
    best = [s for s in setup_results if s.get('pf', 0) >= 1.3 and s.get('win_rate', 0) >= 50 and s.get('n_triggers', 0) >= 5]
    print(f"\n{'=' * 70}")
    print(f"RÉSUMÉ : {len(best)} setups avec PF >= 1.3 et WR >= 50%")
    for s in best:
        print(f"  ⭐ {s['name']} : PF {s['pf']:.2f}, WR {s['win_rate']:.0f}%, {s['n_triggers']} triggers")
    if not best:
        print("  Aucun setup validé. Ajouter plus de données ou ajuster les conditions.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
