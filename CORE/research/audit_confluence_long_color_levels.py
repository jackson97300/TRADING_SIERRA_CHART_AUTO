"""
audit_confluence_long_color_levels.py — Audit walk-forward edge sur combos
{niveau de la veille / VWAP / MenthorQ} x {LONG/COLOR zones >= 2}.

Hypothese Jackson : edge = confluence niveau pre-existant + zones impulsionnelles
multiples actives. Chaque combo teste isole un signal candidat.

Methodologie Lopez-compliant :
  - Walk-forward 5-fold chronologique (4 mois history / 1 mois test rotatif)
  - Forward return : fwd5_ticks = (close.shift(-5) - close) / 0.25 (signed selon direction)
  - DSR (Deflated Sharpe Ratio) avec haircut N strategies = N combos testes
  - Costs : 2 ticks slippage round-trip
  - Verdict : DSR >= 0.5 AND n_total_fires >= 100 AND winrate >= 50%

Combos testes (par direction LONG/SHORT) :
  - {pVWAP / pVWAP_sd1u/d / prev_vpoc / prev_vah / prev_val / pdh / pdl / vwap_d /
     vwap_d_sd1u/d / mq_call / mq_put / mq_hvl / ovn_high / ovn_low}
    × {n_long_up/dn_zones_active >= 2, n_color_up/dn_zones_active >= 2,
       n_long_up/dn_cluster_within_0_2pct >= 2, n_color_up/dn_cluster_within_0_2pct >= 2}

Usage : python -X utf8 CORE/research/audit_confluence_long_color_levels.py
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"

TICK_SIZE = 0.25
SLIPPAGE_TICKS_ROUND_TRIP = 2.0

# Walk-forward (correction ml-trainer 06/05) : 10 folds + 1 fold warmup purge
# Sur 5 mois RTH ~150 trading days, 10 folds = 15j chacun (decent stat power)
N_FOLDS = 10
WARMUP_FOLDS = 1  # fold 0 = warmup, n'est pas evalue (purge first month)

# Haircut DSR multiple testing (correction ml-trainer 06/05) : 500 minimum
# Cf walk_forward_top5_clusters utilise 600. Ici ~200 combos + selection bias prealable
# (audit 1 mois mai a pre-screene 4 zones x 4 directions) -> 500 conservateur.
N_STRATEGIES_TESTED = 500

# Distance threshold pour "near level" (en %) — asymetrique ES/NQ
# ES @ 6700 -> 0.07% = ~19 ticks (trop large 0.10%=27t). NQ @ 21000 -> 0.04% = ~33t.
NEAR_LEVEL_PCT_BY_SYM = {"ES": 0.07, "NQ": 0.04}
NEAR_LEVEL_PCT = 0.07  # fallback

# Zones thresholds
ZONES_MIN = 2

# Rayons confluence (en %) pour mode "confluence multi-niveaux"
# Jackson 06/05 : "la confluence n'est pas obligee d'etre au meme niveau dans un perimetre de X tick"
# Decouple de NEAR_LEVEL_PCT (correction ml-trainer Q4) : rayon plus large pour Phase 2.
# Visualisation Jackson 06/05 (chart NQ 28273.50) : confluence visible dans un rayon ~5-15 ticks
# autour de la bar courante. 0.10% NQ a 28000 = 28 ticks (trop large).
# Cible : ES ~0.10% (~27 ticks), NQ ~0.06% (~17 ticks) pour rester pres du visuel chart.
CONFLUENCE_RADIUS_PCT_BY_SYM = {"ES": 0.10, "NQ": 0.06}
CONFLUENCE_RADIUS_PCT = 0.08

# Min nombre de niveaux dans le rayon pour mode confluence multi-niveaux
N_LEVELS_MIN_CONFLUENCE = 2

# Forward returns multi-horizon (correction ml-trainer Q5)
FWD_HORIZONS = [3, 5, 10, 20]
PRIMARY_FWD = 5  # horizon principal pour verdict (autres = exploratoires)

# Concentration regime threshold (correction ml-trainer Q7)
CONCENTRATION_TOP2_NONSTATIONARY = 0.33  # warning
CONCENTRATION_TOP2_NOGO = 0.60  # force NOGO

# ─────────────────────────────────────────────────────────────────────────────
# Niveaux candidats (cles = nom feature, valeur = label court)
# ─────────────────────────────────────────────────────────────────────────────

LEVELS = {
    # Previous day (Jackson "niveaux de la veille")
    "dist_pvwap_pct": "pVWAP",
    "dist_pvwap_sd1u_pct": "pVWAP_sd1u",
    "dist_pvwap_sd1d_pct": "pVWAP_sd1d",
    "dist_prev_vpoc_pct": "pVPOC",
    "dist_prev_vah_pct": "pVAH",
    "dist_prev_val_pct": "pVAL",
    "dist_pdh_pct": "pdh",
    "dist_pdl_pct": "pdl",
    # VWAP courant (D/W/M)
    "dist_vwap_d_pct": "VWAP_D",
    "dist_vwap_d_sd1u_pct": "VWAP_D_sd1u",
    "dist_vwap_d_sd1d_pct": "VWAP_D_sd1d",
    "dist_vwap_w_pct": "VWAP_W",
    "dist_vwap_m_pct": "VWAP_M",
    # MenthorQ
    "dist_mq_hvl_pct": "MQ_HVL",
    "dist_mq_call_pct": "MQ_call",
    "dist_mq_put_pct": "MQ_put",
    "dist_mq_call_0dte_pct": "MQ_call_0dte",
    "dist_mq_put_0dte_pct": "MQ_put_0dte",
    "dist_mq_hvl_0dte_pct": "MQ_HVL_0dte",
    # OVN
    "dist_ovn_high_pct": "OVN_high",
    "dist_ovn_low_pct": "OVN_low",
}

# ─────────────────────────────────────────────────────────────────────────────
# Zones candidats (cles = (col, direction_attendue))
# ─────────────────────────────────────────────────────────────────────────────

ZONES_LONG = {
    "n_long_up_zones_active": "long_up_zones",
    "n_color_up_zones_active": "color_up_zones",
    "n_long_up_cluster_within_0_2pct": "long_up_cluster",
    "n_color_up_cluster_within_0_2pct": "color_up_cluster",
}

ZONES_SHORT = {
    "n_long_dn_zones_active": "long_dn_zones",
    "n_color_dn_zones_active": "color_dn_zones",
    "n_long_dn_cluster_within_0_2pct": "long_dn_cluster",
    "n_color_dn_cluster_within_0_2pct": "color_dn_cluster",
}


# ─────────────────────────────────────────────────────────────────────────────
# Stats helpers (DSR Lopez)
# ─────────────────────────────────────────────────────────────────────────────

def deflated_sharpe(sr_observed, n_obs, skew, kurt, n_trials):
    """DSR Lopez de Prado AFML ch.14 — haircut multiple testing."""
    if n_obs < 10 or sr_observed <= 0:
        return None, None
    gamma = 0.5772156649  # Euler-Mascheroni
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


def max_dd(pnl_arr):
    if len(pnl_arr) == 0:
        return 0.0
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    return float((peak - cum).max())


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_symbol_all_months(symbol: str) -> pd.DataFrame:
    """Charge tous les mois disponibles pour un symbole + concat trie chrono."""
    sym_root = DATA_ROOT / f"symbol={symbol}.c.0" / "year=2026"
    if not sym_root.exists():
        return pd.DataFrame()

    months = sorted(p for p in sym_root.glob("month=*") if p.is_dir())
    dfs = []
    for m in months:
        f = m / "data.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df.sort_values("ts_event").reset_index(drop=True)


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Filtre RTH 13:30-20:00 UTC (09:30-16:00 ET)."""
    if "ts_event" not in df.columns:
        return df
    ts_utc = pd.to_datetime(df["ts_event"], utc=True)
    h = ts_utc.dt.hour
    m = ts_utc.dt.minute
    minutes_utc = h * 60 + m
    rth_start = 13 * 60 + 30  # 13:30 UTC = 09:30 ET (winter)
    rth_end = 20 * 60         # 20:00 UTC = 16:00 ET
    mask = (minutes_utc >= rth_start) & (minutes_utc < rth_end)
    return df[mask].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Combo evaluation
# ─────────────────────────────────────────────────────────────────────────────

def build_signal(df, level_col, zone_col, direction, near_pct=NEAR_LEVEL_PCT):
    """Signal = dist_level <= near_pct AND zone_count >= ZONES_MIN.
    direction : 'LONG' ou 'SHORT'.
    near_pct : seuil distance configurable (par symbole).
    """
    if level_col not in df.columns or zone_col not in df.columns:
        return None
    near = df[level_col].abs() <= near_pct
    zones = df[zone_col] >= ZONES_MIN
    return (near & zones).fillna(False).astype(int)


def build_n_levels_in_radius(df, level_cols, radius_pct=CONFLUENCE_RADIUS_PCT):
    """Calcule pour chaque bar le nombre de niveaux a distance < radius_pct.

    Jackson 06/05 : confluence = plusieurs niveaux dans un perimetre de X ticks
    (pas obligatoirement au meme prix exact). Ce compteur est invariant a la
    direction (LONG ou SHORT).
    """
    counts = pd.Series(0, index=df.index, dtype=int)
    for c in level_cols:
        if c in df.columns:
            counts = counts + (df[c].abs() <= radius_pct).fillna(False).astype(int)
    return counts


def build_signal_multi_confluence(df, n_levels_col, zone_col, n_levels_min=N_LEVELS_MIN_CONFLUENCE):
    """Signal type 2 : >=N_levels niveaux dans le rayon AND zone_cluster >=2."""
    if zone_col not in df.columns:
        return None
    multi = df[n_levels_col] >= n_levels_min
    zones = df[zone_col] >= ZONES_MIN
    return (multi & zones).fillna(False).astype(int)


def _walkforward_eval(df, sig, direction, n_trials):
    """Walk-forward 10-fold (1 warmup purge) + DSR + concentration regime.

    Corrections ml-trainer 06/05 :
    - N_FOLDS=10 (vs 5), fold 0 = warmup purge
    - n_trials=500 (vs 168) pour haircut DSR conservateur
    - Multi-horizon fwd r3/r5/r10/r20 (verdict sur PRIMARY_FWD=5)
    - Concentration regime top2 (NONSTATIONARY si > 33%, NOGO si > 60%)
    """
    df = df.copy()
    df["_sig"] = sig
    sign = +1 if direction == "LONG" else -1

    # Multi-horizon fwd returns
    for h in FWD_HORIZONS:
        fwd_raw = (df["close"].shift(-h) - df["close"]) / TICK_SIZE
        df[f"_fwd{h}"] = sign * fwd_raw
    primary_col = f"_fwd{PRIMARY_FWD}"

    # Folds chronologiques (purge fold 0 = warmup)
    ts_min = df["ts_event"].min()
    ts_max = df["ts_event"].max()
    total_days = (ts_max - ts_min).total_seconds() / 86400
    fold_days = total_days / N_FOLDS

    fold_n_fires = []
    all_pnl_net = []
    fwd_h_pnl = {h: [] for h in FWD_HORIZONS}

    for i in range(WARMUP_FOLDS, N_FOLDS):
        fold_start = ts_min + pd.Timedelta(days=fold_days * i)
        fold_end = ts_min + pd.Timedelta(days=fold_days * (i + 1))
        mask = (df["ts_event"] >= fold_start) & (df["ts_event"] < fold_end)
        sub = df[mask & (df["_sig"] == 1)].dropna(subset=[primary_col])
        n = len(sub)
        fold_n_fires.append(n)
        if n >= 5:
            pnl = sub[primary_col].values - SLIPPAGE_TICKS_ROUND_TRIP
            all_pnl_net.extend(pnl.tolist())
            for h in FWD_HORIZONS:
                hpnl = sub[f"_fwd{h}"].dropna().values - SLIPPAGE_TICKS_ROUND_TRIP
                fwd_h_pnl[h].extend(hpnl.tolist())

    n_total = len(all_pnl_net)
    n_test_folds = N_FOLDS - WARMUP_FOLDS

    # Concentration regime : % du total dans 2 folds les plus actifs
    fires_arr = np.array(fold_n_fires)
    if fires_arr.sum() > 0:
        top2 = np.sort(fires_arr)[::-1][:2].sum()
        concentration_top2 = float(top2 / fires_arr.sum())
    else:
        concentration_top2 = 0.0

    if n_total < 20:
        return {
            "n_total": n_total, "n_folds_active": int((fires_arr > 0).sum()),
            "winrate": np.nan, "mean_ticks_net": np.nan, "sharpe": np.nan,
            "psr": np.nan, "dsr": np.nan, "max_dd": 0.0,
            "concentration_top2": concentration_top2,
            "fwd3_dsr": np.nan, "fwd10_dsr": np.nan, "fwd20_dsr": np.nan,
            "verdict": "NOGO_LOW_N",
        }

    pnl_arr = np.array(all_pnl_net)
    pnl_gross = pnl_arr + SLIPPAGE_TICKS_ROUND_TRIP
    winrate = float((pnl_gross > 0).mean())
    mean_net = float(pnl_arr.mean())
    std = float(pnl_gross.std())
    sharpe = (pnl_gross.mean() / std) if std > 1e-9 else 0.0
    sk = float(stats.skew(pnl_gross)) if len(pnl_gross) >= 4 else 0.0
    kt = float(stats.kurtosis(pnl_gross, fisher=False)) if len(pnl_gross) >= 4 else 3.0
    psr, dsr = deflated_sharpe(sharpe, n_total, sk, kt, n_trials)
    dd = max_dd(pnl_arr)

    # DSR multi-horizon (exploratoire, verdict reste sur PRIMARY)
    multi_dsr = {}
    for h in FWD_HORIZONS:
        if h == PRIMARY_FWD: continue
        h_arr = np.array(fwd_h_pnl[h])
        if len(h_arr) < 20:
            multi_dsr[h] = np.nan
            continue
        h_gross = h_arr + SLIPPAGE_TICKS_ROUND_TRIP
        h_std = h_gross.std()
        h_sharpe = (h_gross.mean() / h_std) if h_std > 1e-9 else 0.0
        h_sk = float(stats.skew(h_gross)) if len(h_gross) >= 4 else 0.0
        h_kt = float(stats.kurtosis(h_gross, fisher=False)) if len(h_gross) >= 4 else 3.0
        _, h_dsr = deflated_sharpe(h_sharpe, len(h_arr), h_sk, h_kt, n_trials)
        multi_dsr[h] = h_dsr if h_dsr is not None else np.nan

    # Garde-fou ml-trainer R1 : n_folds_active >= 6/9 pour GO_STRONG (sinon NOGO_LOW_FOLDS)
    n_folds_active = int((fires_arr > 0).sum())
    MIN_FOLDS_ACTIVE_GO = 6  # sur 9 folds testes (apres warmup)

    # Horizon shopping warning ml-trainer R2 : flag si DSR autre horizon > primary + 0.2
    primary_dsr_val = dsr if dsr is not None else 0.0
    other_dsrs = [v for v in multi_dsr.values() if v is not None and not np.isnan(v)]
    horizon_shopping_flag = bool(other_dsrs and (max(other_dsrs) > primary_dsr_val + 0.20))

    # Verdict avec concentration + folds_active checks
    if concentration_top2 > CONCENTRATION_TOP2_NOGO:
        verdict = "NOGO_NONSTATIONARY"
    elif dsr is None:
        verdict = "NOGO_DSR_FAIL"
    elif dsr >= 0.95 and n_total >= 100 and winrate >= 0.50 and mean_net > 0:
        if n_folds_active < MIN_FOLDS_ACTIVE_GO:
            verdict = "NOGO_LOW_FOLDS"
        elif concentration_top2 <= CONCENTRATION_TOP2_NONSTATIONARY:
            verdict = "GO_STRONG"
        else:
            verdict = "GO_STRONG_NONSTAT"
    elif winrate >= 0.55 and n_total >= 50:
        verdict = "OBSERVE_DSR" if (dsr is not None and dsr >= 0.5) else "OBSERVE_WR"
    else:
        verdict = "NOGO"

    # Append horizon_shopping suffix si applicable (warning post-verdict)
    if horizon_shopping_flag and verdict.startswith("GO"):
        verdict += "_HSHOP"

    return {
        "n_total": n_total, "n_folds_active": n_folds_active,
        "winrate": winrate, "mean_ticks_net": mean_net, "sharpe": sharpe,
        "psr": psr, "dsr": dsr, "max_dd": dd,
        "concentration_top2": concentration_top2,
        "fwd3_dsr": multi_dsr.get(3, np.nan),
        "fwd10_dsr": multi_dsr.get(10, np.nan),
        "fwd20_dsr": multi_dsr.get(20, np.nan),
        "horizon_shopping": horizon_shopping_flag,
        "verdict": verdict,
    }


def evaluate_combo(df, level_col, zone_col, direction, n_trials, near_pct):
    """Walk-forward + DSR pour combo 1 niveau x 1 zone."""
    sig = build_signal(df, level_col, zone_col, direction, near_pct=near_pct)
    if sig is None:
        return None
    r = _walkforward_eval(df, sig, direction, n_trials)
    r["level"] = LEVELS.get(level_col, level_col)
    r["zone"] = (ZONES_LONG | ZONES_SHORT).get(zone_col, zone_col)
    r["direction"] = direction
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

# Groupes de niveaux pour confluence multi-categorie
LEVEL_GROUPS = {
    "PREV_DAY": [
        "dist_pvwap_pct", "dist_pvwap_sd1u_pct", "dist_pvwap_sd1d_pct",
        "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
        "dist_pdh_pct", "dist_pdl_pct",
    ],
    "VWAP": [
        "dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
        "dist_vwap_w_pct", "dist_vwap_m_pct",
    ],
    "MQ": [
        "dist_mq_hvl_pct", "dist_mq_call_pct", "dist_mq_put_pct",
        "dist_mq_call_0dte_pct", "dist_mq_put_0dte_pct", "dist_mq_hvl_0dte_pct",
    ],
}


def run_audit(symbol: str, rth_only: bool = True, n_trials_global: int = N_STRATEGIES_TESTED):
    print(f"\n{'=' * 80}")
    print(f"  AUDIT CONFLUENCE NIVEAUX VEILLE x ZONES LONG/COLOR — {symbol}")
    print(f"{'=' * 80}\n")

    df = load_symbol_all_months(symbol)
    if df.empty:
        print(f"  AUCUNE DATA pour {symbol}")
        return []

    if rth_only:
        df = filter_rth(df)
    print(f"  Total bars: {len(df)} ({df['ts_event'].min().date()} -> {df['ts_event'].max().date()})")
    print(f"  RTH only: {rth_only}")

    # Per-symbol thresholds (correction ml-trainer Q3)
    near_pct = NEAR_LEVEL_PCT_BY_SYM.get(symbol, NEAR_LEVEL_PCT)
    radius_pct = CONFLUENCE_RADIUS_PCT_BY_SYM.get(symbol, CONFLUENCE_RADIUS_PCT)
    print(f"  NEAR_LEVEL_PCT={near_pct}% / CONFLUENCE_RADIUS_PCT={radius_pct}%")
    print(f"  N_FOLDS={N_FOLDS} (warmup purge {WARMUP_FOLDS}) / haircut DSR n_trials={n_trials_global}")
    print(f"  FWD horizons: {FWD_HORIZONS} (primary={PRIMARY_FWD})")

    levels_present = {k: v for k, v in LEVELS.items() if k in df.columns}
    zones_long_present = {k: v for k, v in ZONES_LONG.items() if k in df.columns}
    zones_short_present = {k: v for k, v in ZONES_SHORT.items() if k in df.columns}

    print(f"  Niveaux dispo: {len(levels_present)}/{len(LEVELS)}")
    print(f"  Zones LONG dispo: {len(zones_long_present)}/{len(ZONES_LONG)}")
    print(f"  Zones SHORT dispo: {len(zones_short_present)}/{len(ZONES_SHORT)}")

    # ─── Phase 1 : combos {1 niveau x 1 zone} ───
    combos_long = list(product(levels_present.keys(), zones_long_present.keys()))
    combos_short = list(product(levels_present.keys(), zones_short_present.keys()))

    # ─── Phase 2 : multi-niveaux dans rayon (categories veille/VWAP/MQ + ALL) ───
    df = df.copy()
    df["_n_lvl_PREV"] = build_n_levels_in_radius(df, LEVEL_GROUPS["PREV_DAY"], radius_pct)
    df["_n_lvl_VWAP"] = build_n_levels_in_radius(df, LEVEL_GROUPS["VWAP"], radius_pct)
    df["_n_lvl_MQ"] = build_n_levels_in_radius(df, LEVEL_GROUPS["MQ"], radius_pct)
    df["_n_lvl_ALL"] = (df["_n_lvl_PREV"] + df["_n_lvl_VWAP"] + df["_n_lvl_MQ"])

    multi_combos_long = [(grp, zc) for grp in ["_n_lvl_PREV", "_n_lvl_VWAP", "_n_lvl_MQ", "_n_lvl_ALL"]
                          for zc in zones_long_present.keys()]
    multi_combos_short = [(grp, zc) for grp in ["_n_lvl_PREV", "_n_lvl_VWAP", "_n_lvl_MQ", "_n_lvl_ALL"]
                           for zc in zones_short_present.keys()]

    n_combos_local = len(combos_long) + len(combos_short) + len(multi_combos_long) + len(multi_combos_short)
    # n_trials reste le global (selection bias prealable + 2 symboles)
    print(f"  Combos Phase 1 (1 niveau x 1 zone): LONG {len(combos_long)} / SHORT {len(combos_short)}")
    print(f"  Combos Phase 2 (multi-niveaux x zone): LONG {len(multi_combos_long)} / SHORT {len(multi_combos_short)}")
    print(f"  Local combos: {n_combos_local} | DSR n_trials (global): {n_trials_global}\n")

    results = []

    # Phase 1
    for level_col, zone_col in combos_long:
        r = evaluate_combo(df, level_col, zone_col, "LONG", n_trials_global, near_pct)
        if r is not None:
            r["symbol"] = symbol
            r["mode"] = "1lvl"
            results.append(r)
    for level_col, zone_col in combos_short:
        r = evaluate_combo(df, level_col, zone_col, "SHORT", n_trials_global, near_pct)
        if r is not None:
            r["symbol"] = symbol
            r["mode"] = "1lvl"
            results.append(r)

    # Phase 2 — confluence multi-niveaux (utilise _walkforward_eval directement)
    for grp_col, zone_col in multi_combos_long:
        sig = build_signal_multi_confluence(df, grp_col, zone_col)
        if sig is None: continue
        r = _walkforward_eval(df, sig, "LONG", n_trials_global)
        r["symbol"] = symbol
        r["mode"] = "multi"
        r["level"] = grp_col.replace("_n_lvl_", "MULTI_")
        r["zone"] = (ZONES_LONG | ZONES_SHORT).get(zone_col, zone_col)
        r["direction"] = "LONG"
        results.append(r)
    for grp_col, zone_col in multi_combos_short:
        sig = build_signal_multi_confluence(df, grp_col, zone_col)
        if sig is None: continue
        r = _walkforward_eval(df, sig, "SHORT", n_trials_global)
        r["symbol"] = symbol
        r["mode"] = "multi"
        r["level"] = grp_col.replace("_n_lvl_", "MULTI_")
        r["zone"] = (ZONES_LONG | ZONES_SHORT).get(zone_col, zone_col)
        r["direction"] = "SHORT"
        results.append(r)

    return results


def main():
    all_results = []
    # n_trials = somme des combos sur 2 symboles + selection bias prealable (audit 1 mois mai)
    # Conservateur : 500 (correction ml-trainer Q2)
    for sym in ["ES", "NQ"]:
        all_results.extend(run_audit(sym, rth_only=True, n_trials_global=N_STRATEGIES_TESTED))

    if not all_results:
        print("\nAucun resultat genere.")
        return

    df_res = pd.DataFrame(all_results)
    df_res = df_res.sort_values(["dsr", "winrate"], ascending=[False, False], na_position="last")

    cols_print = ["symbol", "mode", "direction", "level", "zone", "n_total", "n_folds_active",
                  "winrate", "mean_ticks_net", "sharpe", "psr", "dsr",
                  "fwd3_dsr", "fwd10_dsr", "fwd20_dsr",
                  "concentration_top2", "horizon_shopping", "max_dd", "verdict"]
    for c in ["winrate", "mean_ticks_net", "sharpe", "psr", "dsr",
              "fwd3_dsr", "fwd10_dsr", "fwd20_dsr", "concentration_top2", "max_dd"]:
        if c in df_res.columns:
            df_res[c] = df_res[c].astype(float).round(3)

    print(f"\n{'=' * 80}")
    print(f"  TOP 30 COMBOS (sorted by DSR desc)")
    print(f"{'=' * 80}\n")
    print(df_res[cols_print].head(30).to_string(index=False))

    # GO candidates seulement (DSR>=0.95 obligatoire selon ml-trainer)
    go_verdicts = ["GO_STRONG", "GO_STRONG_NONSTAT", "GO_STRONG_HSHOP", "GO_STRONG_NONSTAT_HSHOP"]
    go_combos = df_res[df_res["verdict"].isin(go_verdicts)]
    print(f"\n  --- GO_STRONG CANDIDATES ({len(go_combos)}) — Lopez DSR>=0.95 + n>=100 + WR>=50% + folds_active>=6 ---")
    if len(go_combos):
        print(go_combos[cols_print].to_string(index=False))
        print("  /!\\  GO_STRONG_NONSTAT = concentration top2 > 33% (regime non-stationnaire)")
        print("  /!\\  *_HSHOP = horizon shopping risk (DSR autre fwd > primary + 0.2)")
    else:
        print("  Aucun combo GO_STRONG. Verdict honnete : pas d'edge robuste.")

    obs_combos = df_res[df_res["verdict"].isin(["OBSERVE_DSR", "OBSERVE_WR"])]
    print(f"\n  --- OBSERVE CANDIDATES ({len(obs_combos)}) — WR>=55% + n>=50 (NE PAS deployer sans walk-forward etendu) ---")
    if len(obs_combos):
        print(obs_combos[cols_print].head(20).to_string(index=False))

    nogo_nonstat = df_res[df_res["verdict"] == "NOGO_NONSTATIONARY"]
    print(f"\n  --- NOGO_NONSTATIONARY ({len(nogo_nonstat)}) — concentration top2 > 60% ---")
    if len(nogo_nonstat):
        print(nogo_nonstat[cols_print].head(10).to_string(index=False))

    # Save full report
    out_path = ROOT / "DATA" / f"audit_confluence_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv"
    df_res.to_csv(out_path, index=False)
    print(f"\n  Report sauve: {out_path}")
    print(f"\n  RAPPEL ml-trainer : tout combo GO_STRONG -> dispatch ml-trainer obligatoire avant integration phase_b_plus.")


if __name__ == "__main__":
    main()
