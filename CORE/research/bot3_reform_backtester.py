"""bot3_reform_backtester.py — Backtester pertinent/intelligent/robuste Bot 3.

Jackson 24/05/2026 : reform Bot 3 sur dataset propre 15/12/2025 -> 21/05/2026.

ANTI-TRICHE (regle souveraine 03/05) :
  - Entry au close de la bar N (deja calcule, deja visible au close)
  - Fills cherches bars N+1 -> N+timeout (jamais sur la bar d'entree)
  - SL pessimiste si TP+SL meme bar (assume SL fill)
  - Slippage par regime : RTH 1.5t entry / 0.5t TP ; Asia 4t entry / 1t TP
  - News bar veto (mins_since_news <= 5 OR mins_to_next_news <= 5)
  - Commission AMP micros : $0.74/RT
  - Cooldown : 1 trade par bar (pas de re-entry meme bar)
  - 1 position max par symbole (close prev avant new)

STABILITY-BY-FOLD + DSR LOPEZ :
  - 12 folds chronologiques (split par date, pas vrai purged k-fold Lopez :
    on n'entraine pas de modele, c'est juste un test de stabilite temporelle
    des regles ex-ante — cf review ml-trainer 24/05)
  - PSR + DSR avec haircut N=10 trials (10 variantes testees)
  - GO si DSR > 0.95 ET n >= 100 ET pf_min_fold >= 1.0

OUTPUT :
  LOGS/bot3_reform/{variant}/trades.jsonl   (audit 1 ligne par trade)
  LOGS/bot3_reform/summary.csv               (1 ligne par variante)
  LOGS/bot3_reform/REPORT.md                 (verdict + classement)

Usage :
  python -X utf8 CORE/research/bot3_reform_backtester.py --variant V1 --symbol NQ
  python -X utf8 CORE/research/bot3_reform_backtester.py --all
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot3_reform_variants import (
    LevelDef,
    VariantConfig,
    build_variants,
    filter_news_veto,
)


# ════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════
TICK_SIZE = 0.25
COMMISSION_PER_RT = 0.74    # AMP micros aller-retour

# Slippage par session (en ticks, par cote)
SLIPPAGE = {
    "RTH":    {"entry": 1.5, "sl": 1.5, "tp": 0.5},
    "ASIA":   {"entry": 4.0, "sl": 3.0, "tp": 1.0},
    "LONDON": {"entry": 2.5, "sl": 2.0, "tp": 0.7},
}

PERIOD_START = "2025-12-15"  # MenthorQ disponible depuis cette date
PERIOD_END = "2026-05-22"  # exclusif
# IMPORTANT 2026-05-24 : source switchee v4_enriched -> v4_pure (bug pipeline
# v4_enriched avril tronque). Source v4_pure complet, period 15/12 -> 22/05 =
# ~108 jours propres MenthorQ. Limite Lopez 2-ans acceptee (Jackson 24/05).

# Walk-forward
N_FOLDS = 12
EMBARGO_DAYS = 0.5
N_TRIALS_DSR = 10  # haircut DSR (10 variantes)

# GO criteria
MIN_N_TRADES = 100
MIN_DSR = 0.95
MIN_PF_MIN_FOLD = 1.0
MIN_FOLDS_PF_GT_1_3 = 8

LOG_DIR = ROOT / "LOGS" / "bot3_reform"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    trade_id: str
    variant: str
    symbol: str
    level_name: str
    level_tier: int
    level_family: str
    side: str                          # LONG ou SHORT (apres inversion eventuelle)
    side_original: str                 # avant inversion (pour audit V9/V10)
    entry_bar_ts: str
    entry_bar_idx: int
    entry_price: float
    entry_price_with_slip: float
    sl_price: float
    tp_price: float                    # cap TP (peut etre 1d_max/min ou fixe)
    sl_ticks: int
    target_pct: float                  # >0 si adaptatif (dist_1d_max/min)
    # Exit
    exit_bar_ts: str = ""
    exit_bar_idx: int = -1
    exit_price: float = 0.0
    exit_price_with_slip: float = 0.0
    exit_reason: str = ""              # SL / TP / EOD / TIMEOUT
    duration_bars: int = 0
    pnl_ticks_gross: float = 0.0
    pnl_ticks_net: float = 0.0
    pnl_R: float = 0.0
    pnl_dollars_net: float = 0.0
    # Regime / context at entry
    session_at_entry: str = ""
    regime_mode_at_entry: str = ""
    regime_favor_at_entry: str = ""
    rvol_at_entry: float = 0.0
    # Walk-forward attribution
    fold_id: int = -1


# ════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ════════════════════════════════════════════════════════════════════════

def load_v4_enriched(symbol: str) -> pd.DataFrame:
    """Charge tous les parquets v4_PURE pour symbol sur la periode.

    NOTE 2026-05-24 : SOURCE SWITCHEE v4_enriched -> v4_pure car v4_enriched
    avril tronque (3 jours au lieu de 25). v4_pure contient toutes les features
    critiques (40/40 verifie) + couvre oct 2025 -> mai 2026 (194 jours).
    Function name conserve pour back-compat.
    """
    pattern = str(
        ROOT / f"DATA/datasets/v4_pure/symbol={symbol}.c.0/year=*/month=*/data.parquet"
    )
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"Aucun parquet trouve pour {symbol} : {pattern}")
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    # Filtre periode
    start = pd.to_datetime(PERIOD_START, utc=True)
    end = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start) & (df["ts_event"] < end)].reset_index(drop=True)
    df["symbol"] = symbol
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    df["time_utc"] = df["ts_event"].dt.strftime("%H:%M")
    return df


def get_session_label(row: pd.Series) -> str:
    """Mappe la colonne 'session' (0-3) vers label string."""
    s = row.get("session", 0)
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "RTH"
    return {0: "ASIA", 1: "LONDON", 2: "RTH", 3: "RTH_AH"}.get(s, "RTH")


def get_slippage(session_label: str, side_action: str) -> float:
    """Recupere le slippage en ticks pour entry/sl/tp."""
    bucket = "ASIA" if session_label == "ASIA" else (
        "LONDON" if session_label == "LONDON" else "RTH"
    )
    return SLIPPAGE[bucket][side_action]


# ════════════════════════════════════════════════════════════════════════
# CONTACT DETECTION
# ════════════════════════════════════════════════════════════════════════

def _safe_float(v, default=0.0) -> float:
    try:
        f = float(v)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def detect_level_contacts(
    df: pd.DataFrame,
    levels: List[LevelDef],
    cooldown_bars_per_level: int = 120,
    max_trades_per_level_per_day: int = 1,
) -> List[Tuple[int, LevelDef]]:
    """Detecte les FIRST TOUCH de chaque niveau (transition loin -> proche).

    First touch : bar T ou abs(dist_pct) <= threshold ET (T-1 hors threshold OR NaN).
    Evite les sur-declenchements (sinon 80 trades/jour pour 13 niveaux).

    Cooldown : apres un touch sur niveau X, on attend N bars avant re-trigger
    sur ce meme niveau (default 30 bars = 30min). Bot 3 prod = 1 fade/level/jour
    typiquement.

    Retourne liste de (bar_idx, LevelDef). 1 niveau par bar max (priorite tier 1>2>3).
    """
    contacts_by_bar: Dict[int, List[Tuple[float, LevelDef]]] = {}
    dates = df["date"].values if "date" in df.columns else None
    for lv in levels:
        if lv.dist_col not in df.columns:
            continue
        series = df[lv.dist_col]
        abs_dist = series.abs()
        in_zone = (abs_dist <= lv.threshold_pct) & series.notna()
        prev_in = in_zone.shift(1, fill_value=False)
        first_touch_mask = in_zone & (~prev_in)
        # Cooldown bars + cap per day
        last_idx_for_level = -10_000
        count_per_day: Dict[str, int] = {}
        kept_for_level: List[int] = []
        for idx in df.index[first_touch_mask]:
            if idx - last_idx_for_level < cooldown_bars_per_level:
                continue
            day = dates[idx] if dates is not None else str(idx)
            if count_per_day.get(day, 0) >= max_trades_per_level_per_day:
                continue
            kept_for_level.append(int(idx))
            count_per_day[day] = count_per_day.get(day, 0) + 1
            last_idx_for_level = int(idx)
        for idx in kept_for_level:
            dist_abs = float(abs_dist.iloc[idx])
            contacts_by_bar.setdefault(idx, []).append((dist_abs, lv))
    # Selectionne 1 niveau par bar : priorite tier 1>2>3, puis min dist_abs
    contacts: List[Tuple[int, LevelDef]] = []
    for idx, cands in sorted(contacts_by_bar.items()):
        cands.sort(key=lambda x: (x[1].tier, x[0]))
        contacts.append((idx, cands[0][1]))
    return contacts


# ════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ════════════════════════════════════════════════════════════════════════

def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    level: LevelDef,
    side: str,
    side_original: str,
    sl_ticks: int,
    target_pct: float,
    timeout_bars: int,
    variant_name: str,
    symbol: str,
    trade_id: str,
    target_R: float = 0.0,
) -> Optional[Trade]:
    """Simule un trade avec anti-triche.

    Anti-lookahead : entry au close bar N, fills cherches bars N+1..N+timeout.
    """
    if entry_idx >= len(df) - 1:
        return None

    entry_bar = df.iloc[entry_idx]
    entry_price = _safe_float(entry_bar.get("close"))
    if entry_price <= 0:
        return None
    entry_date = entry_bar["date"]
    session = get_session_label(entry_bar)

    # Slippages (en pts, pas en ticks)
    slip_entry_ticks = get_slippage(session, "entry")
    slip_sl_ticks = get_slippage(session, "sl")
    slip_tp_ticks = get_slippage(session, "tp")
    slip_entry = slip_entry_ticks * TICK_SIZE
    slip_sl = slip_sl_ticks * TICK_SIZE
    slip_tp = slip_tp_ticks * TICK_SIZE

    # Entry avec slippage adverse
    if side == "LONG":
        entry_with_slip = entry_price + slip_entry
        sl_price = entry_with_slip - sl_ticks * TICK_SIZE
        # PRIORITE TP : target_R > 0 > pct > 1d_max adaptatif
        if target_R > 0:
            tp_price = entry_with_slip + target_R * sl_ticks * TICK_SIZE
        elif target_pct > 0:
            tp_price = entry_with_slip * (1 + target_pct / 100.0)
        else:
            dist_1d_max = _safe_float(entry_bar.get("dist_1d_max_ticks_pct"))
            if dist_1d_max > 0:
                tp_price = entry_with_slip * (1 + dist_1d_max / 100.0)
            else:
                tp_price = entry_with_slip + 2 * sl_ticks * TICK_SIZE
    else:  # SHORT
        entry_with_slip = entry_price - slip_entry
        sl_price = entry_with_slip + sl_ticks * TICK_SIZE
        if target_R > 0:
            tp_price = entry_with_slip - target_R * sl_ticks * TICK_SIZE
        elif target_pct > 0:
            tp_price = entry_with_slip * (1 - target_pct / 100.0)
        else:
            dist_1d_min = _safe_float(entry_bar.get("dist_1d_min_ticks_pct"))
            if dist_1d_min < 0:
                tp_price = entry_with_slip * (1 + dist_1d_min / 100.0)
            else:
                tp_price = entry_with_slip - 2 * sl_ticks * TICK_SIZE

    # Boucle fills sur bars N+1..N+timeout
    end_idx = min(len(df), entry_idx + 1 + timeout_bars)
    exit_idx = -1
    exit_price = 0.0
    exit_reason = ""

    for j in range(entry_idx + 1, end_idx):
        bj = df.iloc[j]
        # EOD : changement de date trading
        if bj["date"] != entry_date:
            exit_idx = j - 1
            exit_price = _safe_float(df.iloc[j - 1].get("close"))
            exit_reason = "EOD"
            break

        h = _safe_float(bj.get("high"))
        low = _safe_float(bj.get("low"))
        if h <= 0 or low <= 0:
            continue

        if side == "LONG":
            sl_hit = low <= sl_price
            tp_hit = h >= tp_price
            if sl_hit and tp_hit:
                # Pessimiste : SL d'abord
                exit_idx = j
                exit_price = sl_price - slip_sl
                exit_reason = "SL"
                break
            if sl_hit:
                exit_idx = j
                exit_price = sl_price - slip_sl
                exit_reason = "SL"
                break
            if tp_hit:
                exit_idx = j
                exit_price = tp_price - slip_tp
                exit_reason = "TP"
                break
        else:  # SHORT
            sl_hit = h >= sl_price
            tp_hit = low <= tp_price
            if sl_hit and tp_hit:
                exit_idx = j
                exit_price = sl_price + slip_sl
                exit_reason = "SL"
                break
            if sl_hit:
                exit_idx = j
                exit_price = sl_price + slip_sl
                exit_reason = "SL"
                break
            if tp_hit:
                exit_idx = j
                exit_price = tp_price + slip_tp
                exit_reason = "TP"
                break

    # Timeout sans fill
    if exit_idx == -1:
        exit_idx = end_idx - 1
        last_bar = df.iloc[exit_idx]
        exit_price = _safe_float(last_bar.get("close"))
        exit_reason = "TIMEOUT"

    # PnL
    if side == "LONG":
        pnl_pts = exit_price - entry_with_slip
    else:
        pnl_pts = entry_with_slip - exit_price
    pnl_ticks_gross = pnl_pts / TICK_SIZE
    pnl_dollars_gross = pnl_ticks_gross * (1.25 if symbol == "ES" else 0.50)
    pnl_dollars_net = pnl_dollars_gross - COMMISSION_PER_RT
    pnl_R = pnl_ticks_gross / sl_ticks if sl_ticks > 0 else 0.0
    pnl_ticks_net = pnl_dollars_net / (1.25 if symbol == "ES" else 0.50)

    return Trade(
        trade_id=trade_id,
        variant=variant_name,
        symbol=symbol,
        level_name=level.name,
        level_tier=level.tier,
        level_family=level.family,
        side=side,
        side_original=side_original,
        entry_bar_ts=entry_bar["ts_event"].isoformat(),
        entry_bar_idx=int(entry_idx),
        entry_price=round(entry_price, 4),
        entry_price_with_slip=round(entry_with_slip, 4),
        sl_price=round(sl_price, 4),
        tp_price=round(tp_price, 4),
        sl_ticks=sl_ticks,
        target_pct=round(target_pct, 4),
        exit_bar_ts=df.iloc[exit_idx]["ts_event"].isoformat(),
        exit_bar_idx=int(exit_idx),
        exit_price=round(exit_price, 4),
        exit_price_with_slip=round(exit_price, 4),
        exit_reason=exit_reason,
        duration_bars=int(exit_idx - entry_idx),
        pnl_ticks_gross=round(pnl_ticks_gross, 2),
        pnl_ticks_net=round(pnl_ticks_net, 2),
        pnl_R=round(pnl_R, 4),
        pnl_dollars_net=round(pnl_dollars_net, 2),
        session_at_entry=session,
        regime_mode_at_entry=str(entry_bar.get("regime_mode", "")),
        regime_favor_at_entry=str(entry_bar.get("regime_favor", "")),
        rvol_at_entry=_safe_float(entry_bar.get("rvol_5", 0.0)),
    )


# ════════════════════════════════════════════════════════════════════════
# VARIANT EXECUTION
# ════════════════════════════════════════════════════════════════════════

def run_variant(
    variant: VariantConfig,
    symbol: str,
    df: pd.DataFrame,
) -> List[Trade]:
    """Execute une variante sur tout le dataset symbol.

    1 trade max par bar (pas de re-entry meme bar).
    1 position max par symbole (close prev avant new).
    """
    trades: List[Trade] = []
    sl_ticks = variant.sl_ticks_nq if symbol == "NQ" else variant.sl_ticks_es

    contacts = detect_level_contacts(df, variant.levels)

    # Track last exit_idx pour eviter re-entry pendant trade ouvert
    last_exit_idx = -1
    trade_counter = 0

    for idx, level in contacts:
        if idx <= last_exit_idx:
            continue  # encore en trade

        row = df.iloc[idx]

        # Side = side_default OU inverse
        side_original = level.side_default
        if variant.invert_direction:
            side = "SHORT" if side_original == "LONG" else "LONG"
        else:
            side = side_original

        # Filter news veto (toujours actif, hardcoded)
        if not filter_news_veto(row, side):
            continue

        # Filters variant
        skip = False
        for f in variant.filters:
            if not f(row, side):
                skip = True
                break
        if skip:
            continue

        trade_counter += 1
        trade_id = f"{variant.name}_{symbol}_{trade_counter:05d}"

        trade = simulate_trade(
            df=df,
            entry_idx=idx,
            level=level,
            side=side,
            side_original=side_original,
            sl_ticks=sl_ticks,
            target_pct=variant.tp_target_pct,
            timeout_bars=variant.timeout_bars,
            variant_name=variant.name,
            symbol=symbol,
            trade_id=trade_id,
            target_R=variant.target_R,
        )
        if trade is None:
            continue
        trades.append(trade)
        last_exit_idx = trade.exit_bar_idx

    return trades


# ════════════════════════════════════════════════════════════════════════
# WALK-FORWARD + DSR LOPEZ
# ════════════════════════════════════════════════════════════════════════

def assign_folds(trades: List[Trade], n_folds: int = N_FOLDS) -> List[Trade]:
    """Assigne fold_id chronologique a chaque trade.

    Split par date (pas par trade) pour stratifier proprement.
    Embargo 0.5 jour (en pratique, gap naturel entre EOD et new day).
    """
    if not trades:
        return trades
    # Tri chronologique
    trades_sorted = sorted(trades, key=lambda t: t.entry_bar_ts)
    dates = sorted({t.entry_bar_ts[:10] for t in trades_sorted})
    n_dates = len(dates)
    if n_dates < n_folds:
        # Pas assez de jours, on fait des folds par trade
        per_fold = max(1, len(trades_sorted) // n_folds)
        for i, t in enumerate(trades_sorted):
            t.fold_id = min(i // per_fold, n_folds - 1)
        return trades_sorted
    # Split par date
    per_fold_dates = n_dates // n_folds
    date_to_fold = {}
    for fold in range(n_folds):
        start = fold * per_fold_dates
        end = (fold + 1) * per_fold_dates if fold < n_folds - 1 else n_dates
        for d in dates[start:end]:
            date_to_fold[d] = fold
    for t in trades_sorted:
        t.fold_id = date_to_fold.get(t.entry_bar_ts[:10], -1)
    return trades_sorted


def stats_of(trades: List[Trade]) -> Dict[str, float]:
    """Compute stats agreges sur liste de trades."""
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "wr_pct": 0.0, "pf": 0.0, "ev_R": 0.0,
            "pnl_R_total": 0.0, "pnl_dollars_total": 0.0,
            "max_dd_R": 0.0, "sharpe_ann": 0.0,
        }
    rs = np.array([t.pnl_R for t in trades])
    wins = (rs > 0).sum()
    wr_pct = wins / n * 100
    gains = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    pf = gains / max(losses, 0.01) if losses > 0 else (gains if gains > 0 else 0.0)
    ev_R = rs.mean()
    pnl_R = rs.sum()
    pnl_dollars = sum(t.pnl_dollars_net for t in trades)
    # Max drawdown sur R
    cum = np.cumsum(rs)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    max_dd_R = dd.max() if len(dd) > 0 else 0.0
    # Sharpe approx (en R, scaled 252j)
    if rs.std() > 0:
        sharpe_ann = (ev_R / rs.std()) * np.sqrt(252)
    else:
        sharpe_ann = 0.0
    return {
        "n": int(n),
        "wr_pct": round(float(wr_pct), 2),
        "pf": round(float(pf), 3),
        "ev_R": round(float(ev_R), 4),
        "pnl_R_total": round(float(pnl_R), 2),
        "pnl_dollars_total": round(float(pnl_dollars), 2),
        "max_dd_R": round(float(max_dd_R), 2),
        "sharpe_ann": round(float(sharpe_ann), 3),
    }


def compute_walk_forward(trades: List[Trade], n_folds: int = N_FOLDS) -> Dict:
    """Calcule stats par fold + agreges WF."""
    if not trades:
        return {"folds": [], "n_folds_pf_gt_1_3": 0, "pf_min_fold": 0.0,
                "pf_median_fold": 0.0, "wf_consistency": 0.0}
    by_fold: Dict[int, List[Trade]] = {}
    for t in trades:
        by_fold.setdefault(t.fold_id, []).append(t)
    fold_stats = []
    for fold_id in sorted(by_fold.keys()):
        s = stats_of(by_fold[fold_id])
        s["fold_id"] = fold_id
        fold_stats.append(s)
    pfs = [f["pf"] for f in fold_stats if f["n"] > 0]
    n_gt = sum(1 for pf in pfs if pf >= 1.3)
    pf_min = min(pfs) if pfs else 0.0
    pf_median = float(np.median(pfs)) if pfs else 0.0
    wf_consistency = n_gt / len(pfs) if pfs else 0.0
    return {
        "folds": fold_stats,
        "n_folds_pf_gt_1_3": int(n_gt),
        "pf_min_fold": round(pf_min, 3),
        "pf_median_fold": round(pf_median, 3),
        "wf_consistency": round(wf_consistency, 3),
    }


def compute_psr_dsr(trades: List[Trade], n_trials: int = N_TRIALS_DSR) -> Dict:
    """PSR (Lopez 2014) + DSR (haircut multi-testing).

    PSR = Prob(SR_true > SR_benchmark=0) sous bootstrap des returns.
    DSR = PSR ajuste par n_trials (Bonferroni-like).

    Reference : Lopez de Prado, "Advances in Financial Machine Learning" ch.14.
    """
    n = len(trades)
    if n < 30:
        return {"psr": 0.0, "dsr": 0.0, "sharpe": 0.0, "skew": 0.0, "kurt": 0.0}
    rs = np.array([t.pnl_R for t in trades])
    mu = rs.mean()
    sigma = rs.std(ddof=1)
    if sigma <= 0:
        return {"psr": 0.0, "dsr": 0.0, "sharpe": 0.0, "skew": 0.0, "kurt": 0.0}
    sharpe = mu / sigma
    # Moments
    rs_norm = (rs - mu) / sigma
    skew = float((rs_norm ** 3).mean())
    kurt = float((rs_norm ** 4).mean()) - 3.0
    # PSR formula Lopez
    sr_star = 0.0  # benchmark = 0
    num = (sharpe - sr_star) * math.sqrt(n - 1)
    denom = math.sqrt(max(1e-9, 1 - skew * sharpe + ((kurt) / 4.0) * sharpe ** 2))
    z = num / denom
    # Phi(z) via erf
    psr = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    # DSR : haircut via expected max SR sous n_trials independants
    # Approximation Bailey-Lopez : E[max SR] ~ sqrt(2*ln(n_trials)) * sigma_sr
    # sigma_sr = sqrt(1/(n-1) * (1 - skew*sharpe + ((kurt-1)/4) * sharpe^2))
    sigma_sr = math.sqrt(max(1e-9, (1 - skew * sharpe + ((kurt - 1) / 4.0) * sharpe ** 2) / max(1, n - 1)))
    if n_trials > 1:
        expected_max_sr = sigma_sr * (
            (1 - 0.5772) * _norm_inv(1 - 1 / n_trials) +
            0.5772 * _norm_inv(1 - 1 / (n_trials * math.e))
        )
    else:
        expected_max_sr = 0.0
    # DSR = PSR with sr_star = expected_max_sr
    num_dsr = (sharpe - expected_max_sr) * math.sqrt(n - 1)
    z_dsr = num_dsr / denom
    dsr = 0.5 * (1 + math.erf(z_dsr / math.sqrt(2)))
    return {
        "psr": round(float(psr), 4),
        "dsr": round(float(dsr), 4),
        "sharpe": round(float(sharpe), 4),
        "skew": round(float(skew), 4),
        "kurt": round(float(kurt), 4),
        "expected_max_sr": round(float(expected_max_sr), 4),
    }


def _norm_inv(p: float) -> float:
    """Approximation inverse CDF normale (Beasley-Springer-Moro)."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    if p < 0.5:
        return -_norm_inv(1 - p)
    t = math.sqrt(-2 * math.log(1 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t ** 2) / (1 + d1 * t + d2 * t ** 2 + d3 * t ** 3)


# ════════════════════════════════════════════════════════════════════════
# REPORTING
# ════════════════════════════════════════════════════════════════════════

def write_trades_jsonl(trades: List[Trade], variant_name: str, symbol: str) -> Path:
    out_dir = LOG_DIR / variant_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"trades_{symbol}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(asdict(t)) + "\n")
    return out_path


def verdict_from_metrics(metrics: Dict, wf: Dict, dsr_dict: Dict) -> str:
    """GO / RESERVES / NOGO selon criteres Lopez."""
    n = metrics["n"]
    pf = metrics["pf"]
    dsr = dsr_dict["dsr"]
    pf_min = wf["pf_min_fold"]
    n_gt = wf["n_folds_pf_gt_1_3"]

    if n < MIN_N_TRADES:
        return "NOGO_SAMPLE"
    if dsr < MIN_DSR:
        return f"NOGO_DSR_{dsr:.2f}"
    if pf_min < MIN_PF_MIN_FOLD:
        return f"NOGO_FOLD_MIN_{pf_min:.2f}"
    if n_gt < MIN_FOLDS_PF_GT_1_3:
        return f"NOGO_WF_{n_gt}/12"
    if pf < 1.3:
        return f"NOGO_PF_{pf:.2f}"
    return "GO"


def write_summary_csv(results: List[Dict]) -> Path:
    df = pd.DataFrame(results)
    out_path = LOG_DIR / "summary.csv"
    df.to_csv(out_path, index=False)
    return out_path


def write_report_md(results: List[Dict]) -> Path:
    out_path = LOG_DIR / "REPORT.md"
    lines = []
    lines.append("# Bot 3 Reform — Rapport Backtest 10 Variantes")
    lines.append(f"\n_Genere {datetime.now(timezone.utc).isoformat()}_")
    lines.append(f"\nPeriode : {PERIOD_START} -> {PERIOD_END}")
    lines.append(f"Stability-by-fold : {N_FOLDS} folds chronologiques "
                 "(split par date, regles ex-ante donc pas de purged k-fold Lopez)")
    lines.append(f"DSR haircut : N={N_TRIALS_DSR} trials\n")

    lines.append("## Classement par verdict\n")
    # Tri : GO d'abord, puis NOGO par DSR descendant
    go = [r for r in results if r["verdict"] == "GO"]
    nogo = [r for r in results if r["verdict"] != "GO"]
    nogo.sort(key=lambda r: -r["dsr"])
    ordered = go + nogo

    lines.append("| Variante | Symbol | Verdict | n | WR% | PF | EV_R | PnL_R | DSR | PF_min_fold | n_folds_pf>1.3 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in ordered:
        lines.append(
            f"| **{r['variant']}** | {r['symbol']} | "
            f"{r['verdict']} | "
            f"{r['n']} | {r['wr_pct']} | {r['pf']} | "
            f"{r['ev_R']} | {r['pnl_R_total']} | "
            f"{r['dsr']} | {r['pf_min_fold']} | {r['n_folds_pf_gt_1_3']}/12 |"
        )

    lines.append("\n## Verdict global\n")
    n_go = len(go)
    if n_go > 0:
        lines.append(f"**{n_go} variante(s) GO** : refonte Bot 3 regle pure POSSIBLE.")
        for r in go:
            lines.append(f"  - {r['variant']} {r['symbol']} : DSR {r['dsr']}, PF {r['pf']}, n {r['n']}")
    else:
        lines.append("**Aucune variante GO** : pivot ML LightGBM recommande.")
        # Top 3 candidats les moins mauvais
        nogo_sorted = sorted(nogo, key=lambda r: -r["dsr"])[:3]
        lines.append("\nTop 3 candidats par DSR (pour analyse) :")
        for r in nogo_sorted:
            lines.append(f"  - {r['variant']} {r['symbol']} : DSR {r['dsr']}, PF {r['pf']}, "
                         f"PF_min_fold {r['pf_min_fold']}, n {r['n']}")

    lines.append("\n## Note methodologique\n")
    lines.append("- Anti-triche : entry au close bar N, fills cherches N+1..N+timeout, "
                 "SL pessimiste si TP+SL meme bar")
    lines.append("- Slippage par session : RTH 1.5t entry / 0.5t TP ; "
                 "Asia 4t entry / 1t TP ; London 2.5t / 0.7t")
    lines.append(f"- Commission AMP : ${COMMISSION_PER_RT}/RT")
    lines.append("- News veto : skip si mins_since_news <= 5 OR mins_to_next_news <= 5")
    lines.append("- DSR Lopez : PSR ajustee par haircut multiple testing (N=10 variantes)")
    lines.append(f"- Criteres GO : n >= {MIN_N_TRADES} ET DSR >= {MIN_DSR} ET "
                 f"PF_min_fold >= {MIN_PF_MIN_FOLD} ET {MIN_FOLDS_PF_GT_1_3}/12 folds PF >= 1.3")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def run_all(symbols: List[str] = ["NQ", "ES"]) -> List[Dict]:
    variants = build_variants()
    results: List[Dict] = []

    # Cache datasets
    dfs: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        print(f"\n[LOAD] {sym}...", flush=True)
        t0 = time.time()
        dfs[sym] = load_v4_enriched(sym)
        print(f"  {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours "
              f"({time.time()-t0:.1f}s)", flush=True)

    for variant_name, variant in variants.items():
        for sym in symbols:
            print(f"\n[RUN] {variant_name} on {sym}...", flush=True)
            t0 = time.time()
            trades = run_variant(variant, sym, dfs[sym])
            trades = assign_folds(trades)
            elapsed = time.time() - t0

            metrics = stats_of(trades)
            wf = compute_walk_forward(trades)
            dsr_dict = compute_psr_dsr(trades)
            verdict = verdict_from_metrics(metrics, wf, dsr_dict)

            write_trades_jsonl(trades, variant_name, sym)

            row = {
                "variant": variant_name,
                "symbol": sym,
                "description": variant.description,
                "verdict": verdict,
                **metrics,
                "dsr": dsr_dict["dsr"],
                "psr": dsr_dict["psr"],
                "sharpe": dsr_dict["sharpe"],
                "skew": dsr_dict["skew"],
                "kurt": dsr_dict["kurt"],
                "pf_min_fold": wf["pf_min_fold"],
                "pf_median_fold": wf["pf_median_fold"],
                "n_folds_pf_gt_1_3": wf["n_folds_pf_gt_1_3"],
                "wf_consistency": wf["wf_consistency"],
                "runtime_sec": round(elapsed, 1),
            }
            results.append(row)
            print(f"  n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
                  f"PF={metrics['pf']:5.2f} DSR={dsr_dict['dsr']:.3f} "
                  f"verdict={verdict} ({elapsed:.1f}s)", flush=True)

    write_summary_csv(results)
    write_report_md(results)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", type=str, default=None,
                        help="V1..V10 (default: all)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="NQ | ES (default: both)")
    parser.add_argument("--all", action="store_true",
                        help="Run all variants on both symbols")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else ["NQ", "ES"]

    if args.variant and not args.all:
        variants = build_variants()
        if args.variant not in variants:
            print(f"ERREUR : variante inconnue {args.variant}")
            sys.exit(1)
        target = {args.variant: variants[args.variant]}
        # Run single variant
        for sym in symbols:
            df = load_v4_enriched(sym)
            for vname, variant in target.items():
                print(f"\n[RUN] {vname} on {sym}...")
                trades = run_variant(variant, sym, df)
                trades = assign_folds(trades)
                metrics = stats_of(trades)
                wf = compute_walk_forward(trades)
                dsr_dict = compute_psr_dsr(trades)
                verdict = verdict_from_metrics(metrics, wf, dsr_dict)
                write_trades_jsonl(trades, vname, sym)
                print(f"  n={metrics['n']:4d} WR={metrics['wr_pct']:5.1f}% "
                      f"PF={metrics['pf']:5.2f} DSR={dsr_dict['dsr']:.3f} "
                      f"verdict={verdict}")
                # Folds detail
                print("  Folds:")
                for f in wf["folds"]:
                    print(f"    fold {f['fold_id']:2d}: n={f['n']:3d} WR={f['wr_pct']:5.1f}% "
                          f"PF={f['pf']:5.2f} PnL_R={f['pnl_R_total']:+6.2f}")
        return

    # Default : run all
    run_all(symbols)


if __name__ == "__main__":
    main()
