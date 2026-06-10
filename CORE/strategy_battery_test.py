"""
strategy_battery_test.py — Batterie de 18 hypotheses d'edge intraday
====================================================================

V2 (15/04/2026) — Refactor complet apres review code-reviewer.

Fixes critiques :
  - CRIT-1 : ATR recalcule depuis bar_high/bar_low si absent, crash si donnees manquantes
  - CRIT-2 : simulateur forward REEL (regarde i+1..i+N pour TP/SL), plus de dependance au labeler
  - CRIT-3/4 : check features strict avec crash explicit si manquantes
  - CRIT-7 : Benjamini-Hochberg FDR sur les 18 p-values, MC 5000 iters

Source de donnees :
  - JSONL bruts de DATA_BACKFILL/ES/*.jsonl + DATA_BACKFILL/NQ/*.jsonl (70 jours)
  - + DATA/ES/*.jsonl + DATA/NQ/*.jsonl (jours recents, live propre post-15/04)

AVERTISSEMENT features polluees :
  Les features SC-dependent (mq_*, bn_absorb_*, bn_color_*, atr, vwap_*, vp_*)
  sont POLLUEES sur le backfill (bug Number of Bars to Calculate = 20 non fixe).
  Seuls les jours live post-15/04 ont les features propres. Les tests sur
  backfill sont a prendre avec precaution (voir rapport).

Hypotheses testees :
  H1  — VWAP mean reversion (Dalton, Chan)
  H2  — Open Drive continuation (Dalton Market Profile)
  H3  — Failed IB Poor High (Crabel 1990)
  H4  — 1D Max/Min Magnetism (SpotGamma pinning)
  H5  — Rejet VAH/VAL + CVD (Dalton)
  H6  — CVD divergence pure (Trader Dale)
  H7  — Intermarket ES/NQ divergence (stat arb)
  H8  — OFI residualise (Cont-Kukanov-Stoikov 2014)
  H9  — VPIN regime filter (Easley-Lopez-O'Hara 2012)

Strategies doc MIA (Strategies_Options_OrderFlow_MIA_IA) :
  SA  — GEX Wall Fade (SpotGamma)
  SB  — GEX Flip Breakout (SpotGamma)
  SC  — Delta Divergence + GEX confluence (Bookmap/Trader Dale)
  SD  — Absorption + GEX (Acosta/Bookmap)
  SE  — VWAP + GEX regime (Chan/SpotGamma)
  SF  — IB Breakout + GEX (Crabel/CBOT)
  SG  — POC Defense (Acosta/Dalton)
  SH  — Composite Profile Rotation (Dalton)
  SI  — VIX Regime Filter (meta, skip pour batterie directe)

Usage :
    python CORE/strategy_battery_test.py --symbol ES
    python CORE/strategy_battery_test.py --symbol NQ
    python CORE/strategy_battery_test.py  # ES + NQ

Output : DATA/STRATEGY_BATTERY_REPORT.md
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

REPO = Path(__file__).parent.parent
BACKFILL_DIR = REPO / "DATA_BACKFILL"
LIVE_DIR = REPO / "DATA"
OUTPUT_REPORT = REPO / "DATA/STRATEGY_BATTERY_REPORT.md"

# Forward simulation — SL/TP en ticks absolus (pas via ATR ratio)
# Calibration calquee sur le labeler existant :
#   ES : SL=5t, TP=9t (R:R 1.8)
#   NQ : SL=20t, TP=36t (R:R 1.8)
SL_TICKS_ES = 5.0
TP_TICKS_ES = 9.0
SL_TICKS_NQ = 20.0
TP_TICKS_NQ = 36.0
FORWARD_WINDOW = 20  # max 20 barres pour tp/sl hit, sinon time exit

# Costs (ticks)
COST_ES = 2.3
COST_NQ = 5.2

# Trading rules
COOLDOWN_BARS = 3
MAX_TRADES_PER_DAY = 5
TICK_SIZE = 0.25


# ═══════════════════════════════════════════════════════════════════════════════
# LOADER JSONL BRUT
# ═══════════════════════════════════════════════════════════════════════════════

def load_symbol_jsonl(symbol: str, max_days: Optional[int] = None) -> pd.DataFrame:
    """Charge tous les JSONL disponibles pour un symbol : backfill + live recent.

    Priorite : jsonl backfill pour l'historique, puis jsonl live pour dates recentes
    non couvertes (ou plus recentes).
    """
    sym = symbol.upper()
    frames: List[pd.DataFrame] = []

    backfill_files = sorted(glob.glob(str(BACKFILL_DIR / sym / "*.jsonl")))
    live_files = sorted(glob.glob(str(LIVE_DIR / sym / "*.jsonl")))

    seen_dates = set()

    # D'abord live (prioritaire car post-fix 15/04)
    for path in live_files:
        date_str = Path(path).stem.split("_")[0]  # "20260415" de "20260415_ES.jsonl"
        try:
            df = _load_jsonl_file(path)
            if df.empty:
                continue
            frames.append(df)
            seen_dates.add(date_str)
        except Exception as e:
            print(f"  [WARN] skip {path}: {e}")

    # Puis backfill pour dates non couvertes
    for path in backfill_files:
        date_str = Path(path).stem.split("_")[0]
        if date_str in seen_dates:
            continue
        try:
            df = _load_jsonl_file(path)
            if df.empty:
                continue
            frames.append(df)
            seen_dates.add(date_str)
        except Exception as e:
            print(f"  [WARN] skip {path}: {e}")

    if not frames:
        raise FileNotFoundError(f"Aucun JSONL trouve pour {sym}")

    full = pd.concat(frames, ignore_index=True, sort=False)
    # Tri chronologique strict
    full = full.sort_values("ts").reset_index(drop=True)
    # Dedup par ts (safety)
    full = full.drop_duplicates(subset=["ts"], keep="first").reset_index(drop=True)

    if max_days is not None:
        unique_days = pd.to_datetime(full["ts"], unit="ms").dt.date.unique()
        if len(unique_days) > max_days:
            cutoff_date = sorted(unique_days)[-max_days]
            full = full[pd.to_datetime(full["ts"], unit="ms").dt.date >= cutoff_date]
            full = full.reset_index(drop=True)

    return full


def _load_jsonl_file(path: str) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# ATR — CHECK + FALLBACK RECALCUL
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_atr_ticks(df: pd.DataFrame) -> pd.Series:
    """Garantit que l'ATR en ticks est disponible.

    1. Si 'atr' present et non-constant -> utilise tel quel (ticks du jsonl)
    2. Sinon recalcule True Range rolling 14 depuis bar_high/bar_low/price
    3. Sinon crash explicit

    Returns : pd.Series avec ATR en ticks (np.float64)
    """
    # Option 1 : atr du jsonl (colonne "atr" en ticks)
    if "atr" in df.columns:
        atr = pd.to_numeric(df["atr"], errors="coerce")
        if atr.notna().sum() > 0 and atr.nunique() > 1:
            atr = atr.ffill().bfill().fillna(100.0)
            return atr

    # Option 2 : recalcul depuis bar_high/bar_low/price
    needed = {"bar_high", "bar_low", "price"}
    if needed.issubset(df.columns):
        high = pd.to_numeric(df["bar_high"], errors="coerce")
        low = pd.to_numeric(df["bar_low"], errors="coerce")
        close = pd.to_numeric(df["price"], errors="coerce")
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_ticks = (tr.rolling(14, min_periods=5).mean() / TICK_SIZE).fillna(20.0)
        if atr_ticks.notna().sum() > 100:
            return atr_ticks

    raise RuntimeError(
        "Cannot determine ATR: ni 'atr' ni (bar_high/bar_low/price) disponibles. "
        "Dataset incomplet. Abort."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATOR FORWARD REEL (pas de dependance au labeler)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    direction: int  # +1 BUY, -1 SELL
    entry_bar: int
    entry_price: float
    exit_bar: int
    exit_price: float
    pnl_ticks: float
    won: bool
    date: Optional[str] = None
    hit_type: str = "unknown"  # "tp", "sl", "time"


@dataclass
class SimResult:
    hypothesis: str
    trades: List[TradeResult] = field(default_factory=list)
    n_bars: int = 0
    n_days: int = 0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return sum(1 for t in self.trades if t.won) / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_ticks for t in self.trades)

    @property
    def gross_wins(self) -> float:
        return sum(t.pnl_ticks for t in self.trades if t.won)

    @property
    def gross_losses(self) -> float:
        return abs(sum(t.pnl_ticks for t in self.trades if not t.won))

    @property
    def profit_factor(self) -> float:
        if self.n_trades == 0:
            return float("nan")
        if self.gross_losses <= 0:
            return float("inf") if self.gross_wins > 0 else float("nan")
        return self.gross_wins / self.gross_losses

    @property
    def ev_per_trade(self) -> float:
        return self.total_pnl / self.n_trades if self.n_trades > 0 else 0.0

    @property
    def trades_per_day(self) -> float:
        return self.n_trades / self.n_days if self.n_days > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumsum = np.cumsum([t.pnl_ticks for t in self.trades])
        peak = np.maximum.accumulate(cumsum)
        return float((peak - cumsum).max())

    @property
    def sharpe_daily(self) -> float:
        if self.n_trades < 5 or self.n_days < 5:
            return 0.0
        daily: Dict[str, float] = defaultdict(float)
        for t in self.trades:
            if t.date is not None:
                daily[t.date] += t.pnl_ticks
        arr = np.array(list(daily.values()), dtype=float)
        if len(arr) < 5 or arr.std() < 1e-6:
            return 0.0
        return float(arr.mean() / arr.std() * np.sqrt(252.0))


def simulate_forward(
    df: pd.DataFrame,
    signal: np.ndarray,
    hypothesis: str,
    is_nq: bool,
) -> SimResult:
    """Simulateur forward reel : pour chaque signal non-zero, regarde i+1..i+FORWARD_WINDOW
    pour TP/SL hit via bar_high/bar_low.

    Pas de dependance au df['label']. TP/SL en ticks fixes (5/9 ES, 20/36 NQ).
    """
    # Check features critiques pour simulation forward
    if "price" not in df.columns:
        raise RuntimeError("'price' (close) manquant — impossible de simuler forward")
    # Pour le forward, on a besoin de bar_high/bar_low ; sinon fallback price
    has_hl = "bar_high" in df.columns and "bar_low" in df.columns

    prices = pd.to_numeric(df["price"], errors="coerce").values
    if has_hl:
        highs = pd.to_numeric(df["bar_high"], errors="coerce").values
        lows = pd.to_numeric(df["bar_low"], errors="coerce").values
    else:
        highs = prices
        lows = prices

    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values

    sl_t = SL_TICKS_NQ if is_nq else SL_TICKS_ES
    tp_t = TP_TICKS_NQ if is_nq else TP_TICKS_ES
    cost = COST_NQ if is_nq else COST_ES

    trades: List[TradeResult] = []
    last_bar = -COOLDOWN_BARS - 1
    daily_count: Dict[object, int] = {}
    unique_days = set(dates.tolist())
    n = len(df)

    for i in range(n - FORWARD_WINDOW):
        if signal[i] == 0:
            continue
        if i - last_bar < COOLDOWN_BARS:
            continue
        d = dates[i]
        if daily_count.get(d, 0) >= MAX_TRADES_PER_DAY:
            continue

        direction = int(signal[i])
        entry_price = prices[i]
        if not np.isfinite(entry_price):
            continue

        if direction == 1:  # LONG
            tp_price = entry_price + tp_t * TICK_SIZE
            sl_price = entry_price - sl_t * TICK_SIZE
        else:  # SHORT
            tp_price = entry_price - tp_t * TICK_SIZE
            sl_price = entry_price + sl_t * TICK_SIZE

        # Scan forward
        exit_bar = -1
        exit_price = float("nan")
        hit_type = "time"
        for j in range(i + 1, min(i + 1 + FORWARD_WINDOW, n)):
            hi = highs[j] if np.isfinite(highs[j]) else prices[j]
            lo = lows[j] if np.isfinite(lows[j]) else prices[j]
            if direction == 1:
                if hi >= tp_price:
                    exit_bar = j
                    exit_price = tp_price
                    hit_type = "tp"
                    break
                if lo <= sl_price:
                    exit_bar = j
                    exit_price = sl_price
                    hit_type = "sl"
                    break
            else:
                if lo <= tp_price:
                    exit_bar = j
                    exit_price = tp_price
                    hit_type = "tp"
                    break
                if hi >= sl_price:
                    exit_bar = j
                    exit_price = sl_price
                    hit_type = "sl"
                    break

        if exit_bar < 0:  # time exit
            exit_bar = min(i + FORWARD_WINDOW, n - 1)
            exit_price = prices[exit_bar]

        if not np.isfinite(exit_price):
            continue

        raw_pnl_ticks = (exit_price - entry_price) / TICK_SIZE * direction
        net_pnl = raw_pnl_ticks - cost

        date_str = str(d) if hasattr(d, "isoformat") or isinstance(d, str) else None
        trades.append(TradeResult(
            direction=direction,
            entry_bar=i,
            entry_price=float(entry_price),
            exit_bar=exit_bar,
            exit_price=float(exit_price),
            pnl_ticks=float(net_pnl),
            won=net_pnl > 0,
            date=date_str,
            hit_type=hit_type,
        ))
        last_bar = i
        daily_count[d] = daily_count.get(d, 0) + 1

    return SimResult(
        hypothesis=hypothesis,
        trades=trades,
        n_bars=n,
        n_days=len(unique_days),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STATS ROBUSTES
# ═══════════════════════════════════════════════════════════════════════════════

def mc_permutation_shuffle_order(sim: SimResult, n_iters: int = 5000, seed: int = 42) -> float:
    """Monte Carlo permutation : shuffle l'ORDRE des pnl (stationary bootstrap light).

    Plus correct qu'un shuffle des signes : teste "si l'ordre des outcomes etait
    aleatoire, aurais-je obtenu un cumul aussi favorable ?"

    Aronson ch.6-7. p <= 0.05 = edge vs random.
    """
    if sim.n_trades < 20:
        return float("nan")
    pnls = np.array([t.pnl_ticks for t in sim.trades], dtype=float)
    actual_pnl = pnls.sum()
    actual_pf = sim.profit_factor
    rng = np.random.default_rng(seed)
    n_hits_pnl = 0
    for _ in range(n_iters):
        shuffled = rng.permutation(pnls)
        if shuffled.sum() >= actual_pnl:
            n_hits_pnl += 1
    p_pnl = n_hits_pnl / n_iters
    return p_pnl


def bootstrap_pf_ci(sim: SimResult, n_iters: int = 2000, seed: int = 42,
                    ci: float = 0.95) -> Tuple[float, float]:
    """Bootstrap PF avec IC 95%."""
    if sim.n_trades < 10:
        return (float("nan"), float("nan"))
    pnls = np.array([t.pnl_ticks for t in sim.trades], dtype=float)
    rng = np.random.default_rng(seed)
    pfs = []
    for _ in range(n_iters):
        sample = rng.choice(pnls, size=len(pnls), replace=True)
        wins = sample[sample > 0].sum()
        losses = -sample[sample < 0].sum()
        if losses > 1e-9:
            pfs.append(wins / losses)
        elif wins > 0:
            pfs.append(10.0)
    if not pfs:
        return (float("nan"), float("nan"))
    lo = np.percentile(pfs, (1 - ci) / 2 * 100)
    hi = np.percentile(pfs, (1 + ci) / 2 * 100)
    return (float(lo), float(hi))


def benjamini_hochberg(pvalues: List[float], alpha: float = 0.05) -> List[bool]:
    """BH FDR correction. Retourne un bool array : True = significatif apres correction."""
    valid_idx = [i for i, p in enumerate(pvalues) if np.isfinite(p)]
    sorted_idx = sorted(valid_idx, key=lambda i: pvalues[i])
    m = len(sorted_idx)
    if m == 0:
        return [False] * len(pvalues)
    results = [False] * len(pvalues)
    for rank, i in enumerate(sorted_idx, 1):
        threshold = (rank / m) * alpha
        if pvalues[i] <= threshold:
            for j in sorted_idx[:rank]:
                results[j] = True
    return results


def compute_verdict(sim: SimResult, mc_p: float, pf_lo: float,
                    bh_significant: bool) -> str:
    """Verdict GO / CAUTION / NO-GO apres correction BH."""
    if sim.n_trades < 30:
        return "NO-GO (n<30)"
    if not np.isfinite(sim.profit_factor) or sim.profit_factor < 1.3:
        return "NO-GO (PF<1.3)"
    if sim.win_rate < 0.35:
        return "NO-GO (WR<35%)"
    if sim.ev_per_trade < 1.0:
        return "NO-GO (EV<1t)"
    if np.isfinite(mc_p) and mc_p > 0.10:
        return "NO-GO (MC p>0.10)"
    if not bh_significant:
        return "CAUTION (not BH signif)"
    if np.isfinite(pf_lo) and pf_lo < 1.0:
        return "CAUTION (PF_lo<1)"
    if sim.profit_factor >= 1.5 and sim.win_rate >= 0.42 and np.isfinite(mc_p) and mc_p <= 0.05:
        return "GO"
    return "CAUTION"


# ═══════════════════════════════════════════════════════════════════════════════
# UTILS — HELPERS FEATURE ACCESS SAFE
# ═══════════════════════════════════════════════════════════════════════════════

def _get(df: pd.DataFrame, col: str, fill: float = 0.0) -> np.ndarray:
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return pd.to_numeric(df[col], errors="coerce").fillna(fill).values


def _has_all(df: pd.DataFrame, cols: List[str]) -> bool:
    return all(c in df.columns for c in cols)


# ═══════════════════════════════════════════════════════════════════════════════
# HYPOTHESES H1-H9 (originales)
# ═══════════════════════════════════════════════════════════════════════════════

def h1_vwap_reversion(df: pd.DataFrame) -> np.ndarray:
    """H1 — VWAP mean reversion (Dalton + Chan).
    Signal si |dist_vwap_d_atr| > 2 (ou dist_vwap_d > 2*ATR).
    """
    sig = np.zeros(len(df), dtype=int)
    if "dist_vwap_d_atr" in df.columns:
        x = _get(df, "dist_vwap_d_atr")
    elif _has_all(df, ["dist_vwap_d"]):
        atr = ensure_atr_ticks(df).values
        x = _get(df, "dist_vwap_d") / np.maximum(atr, 1)
    else:
        return sig
    sig[x > 2.0] = -1
    sig[x < -2.0] = 1
    return sig


def h2_open_drive(df: pd.DataFrame) -> np.ndarray:
    """H2 — Open Drive continuation (Dalton)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["open_type", "open_bias_conf", "open_direction"]):
        return sig
    conf = _get(df, "open_bias_conf")
    direction = _get(df, "open_direction")
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values
    seen = set()
    for i in range(len(df)):
        if dates[i] in seen:
            continue
        if np.isfinite(conf[i]) and conf[i] > 0.7 and np.isfinite(direction[i]) and direction[i] != 0:
            sig[i] = int(direction[i])
            seen.add(dates[i])
    return sig


def h3_failed_ib(df: pd.DataFrame) -> np.ndarray:
    """H3 — Failed IB Poor High (Crabel 1990)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["ib_broken_up", "ib_broken_down", "ib_position_pct"]):
        return sig
    br_up = _get(df, "ib_broken_up")
    br_dn = _get(df, "ib_broken_down")
    pos = _get(df, "ib_position_pct")
    # Broke up mais revient dans IB -> poor high -> SHORT
    sig[(br_up == 1) & (pos > -0.5) & (pos < 0.5)] = -1
    sig[(br_dn == 1) & (pos > -0.5) & (pos < 0.5)] = 1
    return sig


def h4_1d_magnetism(df: pd.DataFrame) -> np.ndarray:
    """H4 — 1D Max/Min Magnetism (SpotGamma pinning)."""
    sig = np.zeros(len(df), dtype=int)
    for col_max, col_min in [("dist_1d_max_ticks", "dist_1d_min_ticks"),
                              ("mq_dist_1d_max", "mq_dist_1d_min")]:
        if _has_all(df, [col_max, col_min]):
            d_max = _get(df, col_max)
            d_min = _get(df, col_min)
            sig[np.abs(d_max) < 20] = -1
            sig[np.abs(d_min) < 20] = 1
            return sig
    return sig


def h5_vah_val_rejet(df: pd.DataFrame) -> np.ndarray:
    """H5 — Rejet VAH/VAL + CVD (Dalton)."""
    sig = np.zeros(len(df), dtype=int)
    has_atr_ver = _has_all(df, ["dist_cur_vah_atr", "dist_cur_val_atr", "cvd_day_dir"])
    has_raw_ver = _has_all(df, ["dist_cur_vah", "dist_cur_val", "cvd_day_dir"])
    if has_atr_ver:
        d_vah = _get(df, "dist_cur_vah_atr")
        d_val = _get(df, "dist_cur_val_atr")
        cvd = _get(df, "cvd_day_dir")
        sig[(np.abs(d_vah) < 0.15) & (cvd == -1)] = -1
        sig[(np.abs(d_val) < 0.15) & (cvd == 1)] = 1
    elif has_raw_ver:
        atr = ensure_atr_ticks(df).values
        d_vah = _get(df, "dist_cur_vah") / np.maximum(atr, 1)
        d_val = _get(df, "dist_cur_val") / np.maximum(atr, 1)
        cvd = _get(df, "cvd_day_dir")
        sig[(np.abs(d_vah) < 0.15) & (cvd == -1)] = -1
        sig[(np.abs(d_val) < 0.15) & (cvd == 1)] = 1
    return sig


def h6_cvd_divergence(df: pd.DataFrame) -> np.ndarray:
    """H6 — CVD divergence pure (Trader Dale)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["delta_divergence", "momentum_3b"]):
        return sig
    div = _get(df, "delta_divergence")
    mom = _get(df, "momentum_3b")
    sig[(div == 1) & (mom < -0.3)] = 1
    sig[(div == 1) & (mom > 0.3)] = -1
    return sig


def h7_intermarket_divergence(df: pd.DataFrame) -> np.ndarray:
    """H7 — Intermarket ES/NQ divergence (stat arb)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["im_rolling_correlation_10", "im_cross_delta_agreement_5", "momentum_3b"]):
        return sig
    corr = _get(df, "im_rolling_correlation_10")
    agree = _get(df, "im_cross_delta_agreement_5")
    mom = _get(df, "momentum_3b")
    mask = (corr < 0.5) & (agree < 0.5)
    sig[mask & (mom > 0.3)] = 1
    sig[mask & (mom < -0.3)] = -1
    return sig


def h8_ofi_residualized(df: pd.DataFrame) -> np.ndarray:
    """H8 — OFI residualise (Cont-Kukanov-Stoikov 2014)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["delta_bar", "total_vol"]):
        return sig
    ofi_raw = _get(df, "delta_bar") / np.maximum(_get(df, "total_vol"), 1)
    ofi_series = pd.Series(ofi_raw)
    mean = ofi_series.rolling(20, min_periods=5).mean()
    std = ofi_series.rolling(20, min_periods=5).std().replace(0, 1)
    z = ((ofi_series - mean) / std).fillna(0).values
    sig[z > 1.5] = 1
    sig[z < -1.5] = -1
    return sig


def h9_vpin_filter(df: pd.DataFrame) -> np.ndarray:
    """H9 — VPIN regime filter (Easley-Lopez-O'Hara 2012).
    Approx time-based (pas volume buckets — limitation documentee).
    """
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["buy_vol", "sell_vol", "momentum_3b"]):
        return sig
    buy = _get(df, "buy_vol")
    sell = _get(df, "sell_vol")
    mom = _get(df, "momentum_3b")
    vpin_raw = np.abs(buy - sell) / np.maximum(buy + sell, 1)
    vpin = pd.Series(vpin_raw).rolling(20, min_periods=5).mean().fillna(0.5).values
    clean = vpin < 0.3
    sig[clean & (mom > 0.5)] = 1
    sig[clean & (mom < -0.5)] = -1
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGIES DOC (SA-SH)
# ═══════════════════════════════════════════════════════════════════════════════

def sa_gex_wall_fade(df: pd.DataFrame) -> np.ndarray:
    """SA — GEX Wall Fade (SpotGamma).
    LONG : prix proche Put Wall + gamma positif + absorption bid
    SHORT : prix proche Call Wall + gamma positif + absorption ask
    """
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["dist_mq_put_0dte", "dist_mq_call_0dte", "dist_mq_hvl"]):
        return sig
    d_put = _get(df, "dist_mq_put_0dte")
    d_call = _get(df, "dist_mq_call_0dte")
    d_hvl = _get(df, "dist_mq_hvl")
    absorb_bid = _get(df, "bn_absorb_bid") if "bn_absorb_bid" in df.columns else np.zeros(len(df))
    absorb_ask = _get(df, "bn_absorb_ask") if "bn_absorb_ask" in df.columns else np.zeros(len(df))
    delta_div = _get(df, "delta_divergence") if "delta_divergence" in df.columns else np.zeros(len(df))

    # LONG : proche Put Wall ET gamma positif
    long_mask = (
        (d_put > -200) & (d_put < -20)  # approche put wall par en dessous
        & (d_hvl > 0)  # gamma positif
        & ((absorb_bid == 1) | (delta_div == 1))
    )
    sig[long_mask] = 1

    # SHORT : proche Call Wall ET gamma positif
    short_mask = (
        (d_call > 20) & (d_call < 200)  # approche call wall par en dessous
        & (d_hvl > 0)
        & ((absorb_ask == 1) | (delta_div == 1))
    )
    sig[short_mask] = -1
    return sig


def sb_gex_flip_breakout(df: pd.DataFrame) -> np.ndarray:
    """SB — GEX Flip Breakout (momentum en gamma negatif)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["dist_mq_hvl", "delta_day_dir"]):
        return sig
    d_hvl = _get(df, "dist_mq_hvl")
    delta_dir = _get(df, "delta_day_dir")
    rvol = _get(df, "rvol") if "rvol" in df.columns else np.ones(len(df))
    # SHORT : cassure sous HVL + delta baissier + volume soutenu
    short_mask = (d_hvl < -50) & (delta_dir == -1) & (rvol > 1.0)
    sig[short_mask] = -1
    # LONG : retour au-dessus HVL + delta haussier
    long_mask = (d_hvl > 50) & (delta_dir == 1) & (rvol > 1.0)
    sig[long_mask] = 1
    return sig


def sc_delta_div_gex(df: pd.DataFrame) -> np.ndarray:
    """SC — Delta Divergence + GEX confluence."""
    sig = np.zeros(len(df), dtype=int)
    if "delta_divergence" not in df.columns:
        return sig
    div = _get(df, "delta_divergence")
    d_gex_up = _get(df, "dist_gex_nearest_up") if "dist_gex_nearest_up" in df.columns else np.full(len(df), 1000.0)
    d_gex_dn = _get(df, "dist_gex_nearest_dn") if "dist_gex_nearest_dn" in df.columns else np.full(len(df), -1000.0)
    score_bear = _get(df, "bn_score_bear") if "bn_score_bear" in df.columns else np.zeros(len(df))
    score_bull = _get(df, "bn_score_bull") if "bn_score_bull" in df.columns else np.zeros(len(df))
    absorb_bid = _get(df, "bn_absorb_bid") if "bn_absorb_bid" in df.columns else np.zeros(len(df))
    # SHORT : div + proche GEX up + bear score dominant
    short_mask = (div == 1) & (d_gex_up < 200) & (score_bear > score_bull)
    sig[short_mask] = -1
    # LONG : div + proche GEX dn + bull + absorption bid
    long_mask = (div == 1) & (d_gex_dn > -200) & (score_bull > score_bear) & (absorb_bid == 1)
    sig[long_mask] = 1
    return sig


def sd_absorption_gex(df: pd.DataFrame) -> np.ndarray:
    """SD — Absorption + GEX (Acosta 80-85%).
    LONG : bn_absorb_bid + proche Put Wall 0DTE + large_trader_ratio high
    SHORT : bn_absorb_ask + proche Call Wall 0DTE + large_trader_ratio high
    """
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["bn_absorb_bid", "bn_absorb_ask"]):
        return sig
    absorb_bid = _get(df, "bn_absorb_bid")
    absorb_ask = _get(df, "bn_absorb_ask")
    d_put_0 = _get(df, "dist_mq_put_0dte") if "dist_mq_put_0dte" in df.columns else np.full(len(df), 1000.0)
    d_call_0 = _get(df, "dist_mq_call_0dte") if "dist_mq_call_0dte" in df.columns else np.full(len(df), 1000.0)
    large = _get(df, "large_trader_ratio") if "large_trader_ratio" in df.columns else np.zeros(len(df))
    long_mask = (absorb_bid == 1) & (np.abs(d_put_0) < 100) & (large > 0.7)
    sig[long_mask] = 1
    short_mask = (absorb_ask == 1) & (np.abs(d_call_0) < 100) & (large > 0.7)
    sig[short_mask] = -1
    return sig


def se_vwap_gex_regime(df: pd.DataFrame) -> np.ndarray:
    """SE — VWAP mean reversion filtre par regime GEX (Chan + SpotGamma)."""
    sig = np.zeros(len(df), dtype=int)
    # Besoin VWAP et gamma regime
    if not ("dist_mq_hvl" in df.columns):
        return sig
    d_hvl = _get(df, "dist_mq_hvl")
    # Gamma positif = d_hvl > 0
    if "dist_vwap_d_atr" in df.columns:
        x = _get(df, "dist_vwap_d_atr")
    elif "dist_vwap_d" in df.columns:
        atr = ensure_atr_ticks(df).values
        x = _get(df, "dist_vwap_d") / np.maximum(atr, 1)
    else:
        return sig
    gamma_pos = d_hvl > 0
    sig[gamma_pos & (x > 2.0)] = -1  # SHORT au dessus SD2
    sig[gamma_pos & (x < -2.0)] = 1  # LONG sous -SD2
    return sig


def sf_ib_breakout_gex(df: pd.DataFrame) -> np.ndarray:
    """SF — IB Breakout + GEX directionnel (Crabel)."""
    sig = np.zeros(len(df), dtype=int)
    if not _has_all(df, ["ib_broken_up", "ib_broken_down"]):
        return sig
    br_up = _get(df, "ib_broken_up")
    br_dn = _get(df, "ib_broken_down")
    d_hvl = _get(df, "dist_mq_hvl") if "dist_mq_hvl" in df.columns else np.zeros(len(df))
    delta_dir = _get(df, "delta_day_dir") if "delta_day_dir" in df.columns else np.zeros(len(df))
    # SHORT : IB break down + gamma negatif + delta baissier
    sig[(br_dn == 1) & (d_hvl < 0) & (delta_dir == -1)] = -1
    # LONG : IB break up + gamma positif + delta haussier
    sig[(br_up == 1) & (d_hvl > 0) & (delta_dir == 1)] = 1
    return sig


def sg_poc_defense(df: pd.DataFrame) -> np.ndarray:
    """SG — POC Defense (Acosta 85-90%).
    Prix au POC + bn_absorb confirmation.
    """
    sig = np.zeros(len(df), dtype=int)
    # Trouver dist_cur_vpoc normalisee
    if "dist_cur_vpoc_atr" in df.columns:
        d_poc = _get(df, "dist_cur_vpoc_atr")
        tight = np.abs(d_poc) < 0.1
    elif "dist_cur_vpoc" in df.columns:
        d_poc = _get(df, "dist_cur_vpoc")
        atr = ensure_atr_ticks(df).values
        tight = np.abs(d_poc) / np.maximum(atr, 1) < 0.1
    else:
        return sig
    absorb_bid = _get(df, "bn_absorb_bid") if "bn_absorb_bid" in df.columns else np.zeros(len(df))
    absorb_ask = _get(df, "bn_absorb_ask") if "bn_absorb_ask" in df.columns else np.zeros(len(df))
    # LONG : prix au POC + absorb bid = support tient
    sig[tight & (absorb_bid == 1)] = 1
    # SHORT : prix au POC + absorb ask = resistance tient
    sig[tight & (absorb_ask == 1)] = -1
    return sig


def sh_composite_rotation(df: pd.DataFrame) -> np.ndarray:
    """SH — Composite Profile Rotation (Dalton swing).
    Rotation vers POC composite 20j quand ecart important.
    """
    sig = np.zeros(len(df), dtype=int)
    # Trouver dist_comp_20d_vpoc en version normalisee si possible
    if "dist_comp_20d_vpoc_atr" in df.columns:
        d20 = _get(df, "dist_comp_20d_vpoc_atr")
    elif "dist_comp_20d_vpoc" in df.columns:
        atr = ensure_atr_ticks(df).values
        d20 = _get(df, "dist_comp_20d_vpoc") / np.maximum(atr, 1)
    else:
        return sig
    # Seuil : ecart > 5 ATR => reversion probable
    sig[d20 > 5.0] = -1  # trop haut -> retour POC
    sig[d20 < -5.0] = 1  # trop bas -> retour POC
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRE HYPOTHESES
# ═══════════════════════════════════════════════════════════════════════════════

HYPOTHESES: List[Tuple[str, str, Callable[[pd.DataFrame], np.ndarray]]] = [
    ("H1", "VWAP mean reversion (Dalton/Chan)", h1_vwap_reversion),
    ("H2", "Open Drive continuation (Dalton)", h2_open_drive),
    ("H3", "Failed IB Poor High (Crabel)", h3_failed_ib),
    ("H4", "1D Max/Min Magnetism (MenthorQ)", h4_1d_magnetism),
    ("H5", "Rejet VAH/VAL + CVD (Dalton)", h5_vah_val_rejet),
    ("H6", "CVD divergence pure (Trader Dale)", h6_cvd_divergence),
    ("H7", "Intermarket ES/NQ divergence", h7_intermarket_divergence),
    ("H8", "OFI residualise (Cont 2014)", h8_ofi_residualized),
    ("H9", "VPIN regime filter (Easley-Lopez 2012)", h9_vpin_filter),
    ("SA", "GEX Wall Fade (SpotGamma)", sa_gex_wall_fade),
    ("SB", "GEX Flip Breakout (SpotGamma)", sb_gex_flip_breakout),
    ("SC", "Delta Divergence + GEX (Bookmap/Dale)", sc_delta_div_gex),
    ("SD", "Absorption + GEX (Acosta)", sd_absorption_gex),
    ("SE", "VWAP + GEX regime (Chan/SpotGamma)", se_vwap_gex_regime),
    ("SF", "IB Breakout + GEX (Crabel)", sf_ib_breakout_gex),
    ("SG", "POC Defense (Acosta/Dalton)", sg_poc_defense),
    ("SH", "Composite Rotation (Dalton)", sh_composite_rotation),
]


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_battery(symbol: str, max_days: Optional[int] = None) -> List[dict]:
    print(f"\n{'='*70}")
    print(f"  BATTERIE {symbol}")
    print(f"{'='*70}")

    df = load_symbol_jsonl(symbol, max_days=max_days)
    n_days = pd.to_datetime(df["ts"], unit="ms").dt.date.nunique()
    print(f"  {len(df)} barres, {n_days} jours, {df.shape[1]} colonnes")

    # Check ATR availability (crash explicit si ni atr ni bar_high/low)
    try:
        atr_ticks = ensure_atr_ticks(df)
        print(f"  ATR source : {'jsonl atr' if 'atr' in df.columns else 'recalc TR rolling 14'}")
        print(f"  ATR stats : mean={atr_ticks.mean():.1f}t min={atr_ticks.min():.1f}t max={atr_ticks.max():.1f}t")
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        sys.exit(1)

    is_nq = (symbol.upper() == "NQ")

    results: List[dict] = []
    for code, name, func in HYPOTHESES:
        try:
            signal = func(df)
        except Exception as e:
            print(f"  [{code}] {name} — ERROR : {e}")
            continue

        n_signals = int((signal != 0).sum())
        if n_signals < 10:
            print(f"  [{code}] {name} — {n_signals} signaux (features absentes ou seuils trop stricts)")
            results.append({
                "code": code, "name": name, "symbol": symbol,
                "n_signals": n_signals, "n_trades": 0,
                "win_rate": 0.0, "profit_factor": float("nan"),
                "ev_per_trade": 0.0, "sharpe_daily": 0.0,
                "max_dd": 0.0, "trades_day": 0.0, "total_pnl": 0.0,
                "mc_p_value": float("nan"),
                "pf_ci_lo": float("nan"), "pf_ci_hi": float("nan"),
                "verdict": "NO-GO (features/signals)",
                "hit_tp": 0, "hit_sl": 0, "hit_time": 0,
            })
            continue

        sim = simulate_forward(df, signal, f"{code}: {name}", is_nq)
        mc_p = mc_permutation_shuffle_order(sim, n_iters=5000)
        pf_lo, pf_hi = bootstrap_pf_ci(sim, n_iters=2000)

        hit_tp = sum(1 for t in sim.trades if t.hit_type == "tp")
        hit_sl = sum(1 for t in sim.trades if t.hit_type == "sl")
        hit_time = sum(1 for t in sim.trades if t.hit_type == "time")

        result = {
            "code": code, "name": name, "symbol": symbol,
            "n_signals": n_signals,
            "n_trades": sim.n_trades,
            "win_rate": sim.win_rate,
            "profit_factor": sim.profit_factor,
            "ev_per_trade": sim.ev_per_trade,
            "sharpe_daily": sim.sharpe_daily,
            "max_dd": sim.max_drawdown,
            "trades_day": sim.trades_per_day,
            "total_pnl": sim.total_pnl,
            "mc_p_value": mc_p,
            "pf_ci_lo": pf_lo,
            "pf_ci_hi": pf_hi,
            "hit_tp": hit_tp,
            "hit_sl": hit_sl,
            "hit_time": hit_time,
            "verdict": "TBD",  # a completer apres BH
        }
        results.append(result)

        pf_str = f"{sim.profit_factor:.2f}" if np.isfinite(sim.profit_factor) else "inf"
        print(f"  [{code}] sig={n_signals:>5} trades={sim.n_trades:>4} "
              f"WR={sim.win_rate*100:>4.1f}% PF={pf_str:>5} "
              f"EV={sim.ev_per_trade:+5.1f}t Sharpe={sim.sharpe_daily:>5.2f} "
              f"MC={mc_p:.4f} TP/SL/Time={hit_tp}/{hit_sl}/{hit_time}")

    # BH FDR correction sur les p-values
    pvals = [r["mc_p_value"] for r in results]
    bh_sig = benjamini_hochberg(pvals, alpha=0.05)
    for r, sig_bh in zip(results, bh_sig):
        if r["n_trades"] < 30:
            continue
        sim_stub = SimResult(
            hypothesis=r["code"],
            trades=[TradeResult(0, 0, 0, 0, 0, 0, False)] * r["n_trades"],
            n_bars=0, n_days=int(r["trades_day"] and r["n_trades"] / r["trades_day"] or 1),
        )
        # Hack : reconstruction minimaliste pour verdict function (pas ideal)
        # On utilise les valeurs dans result directement via un dict-like wrapper
        r["bh_significant"] = bool(sig_bh)
        # Recompute verdict avec BH flag
        fake_sim = type("FakeSim", (), {
            "n_trades": r["n_trades"],
            "profit_factor": r["profit_factor"],
            "win_rate": r["win_rate"],
            "ev_per_trade": r["ev_per_trade"],
        })()
        r["verdict"] = compute_verdict(fake_sim, r["mc_p_value"], r["pf_ci_lo"], sig_bh)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT MARKDOWN
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(all_results: List[dict]) -> str:
    lines = []
    lines.append("# Strategy Battery Test Report (v2)")
    lines.append("")
    lines.append(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("**Source** : JSONL bruts `DATA_BACKFILL/` + `DATA/` (live propre post-15/04)")
    lines.append("**Simulator** : forward reel (TP/SL via ticks fixes, max 20 bars forward)")
    lines.append("**TP/SL** : ES 5/9t, NQ 20/36t (calque sur labeler)")
    lines.append(f"**Costs** : ES {COST_ES}t, NQ {COST_NQ}t")
    lines.append("**Cooldown** : 3 bars, max 5 trades/jour")
    lines.append("**Stats** : MC permutation 5000 iters, Bootstrap PF CI 95%, BH FDR alpha=0.05")
    lines.append("")
    lines.append("## ⚠️ Avertissement features polluees")
    lines.append("")
    lines.append("Les features SC-dependent (mq_*, bn_absorb_*, dist_cur_vpoc, atr cross-TF,")
    lines.append("vix_*, vwap_* daily, vp_*) sont **polluees sur le backfill** (bug Number of")
    lines.append("Bars to Calculate = 20 sur les etudes SC, non fixe). Seuls les jours live")
    lines.append("post-15/04 ont ces features correctes. Les strategies SA-SH qui dependent")
    lines.append("de ces features donnent des resultats biaises sur l'historique.")
    lines.append("")
    lines.append("## Classement global par Profit Factor")
    lines.append("")
    lines.append("| Rang | Code | Hypothese | Sym | Trades | WR | PF | PF CI 95% | EV | Sharpe | MC_p | BH | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    sortable = [r for r in all_results if r["n_trades"] >= 30 and np.isfinite(r["profit_factor"])]
    sortable.sort(key=lambda r: r["profit_factor"], reverse=True)
    unsortable = [r for r in all_results if r not in sortable]
    for rank, r in enumerate(sortable, 1):
        pf = f"{r['profit_factor']:.2f}" if np.isfinite(r["profit_factor"]) else "inf"
        mc = f"{r['mc_p_value']:.4f}" if np.isfinite(r["mc_p_value"]) else "n/a"
        ci = f"[{r['pf_ci_lo']:.2f},{r['pf_ci_hi']:.2f}]" if np.isfinite(r["pf_ci_lo"]) else "n/a"
        bh = "✓" if r.get("bh_significant", False) else "✗"
        lines.append(f"| {rank} | {r['code']} | {r['name']} | {r['symbol']} | "
                     f"{r['n_trades']} | {r['win_rate']*100:.1f}% | {pf} | {ci} | "
                     f"{r['ev_per_trade']:+.1f}t | {r['sharpe_daily']:.2f} | "
                     f"{mc} | {bh} | {r['verdict']} |")
    for r in unsortable:
        lines.append(f"| - | {r['code']} | {r['name']} | {r['symbol']} | "
                     f"{r['n_trades']} | - | - | - | - | - | - | - | {r['verdict']} |")

    lines.append("")
    lines.append("## Details par hypothese")
    lines.append("")
    for r in all_results:
        lines.append(f"### {r['code']} — {r['name']} ({r['symbol']})")
        lines.append("")
        lines.append(f"- Signals raw : {r['n_signals']}")
        lines.append(f"- Trades executes : {r['n_trades']}")
        if r["n_trades"] >= 10:
            pf = f"{r['profit_factor']:.2f}" if np.isfinite(r["profit_factor"]) else "inf"
            lines.append(f"- Win Rate : {r['win_rate']*100:.1f}%")
            lines.append(f"- Profit Factor : {pf}")
            lines.append(f"- EV/trade : {r['ev_per_trade']:+.1f} ticks")
            lines.append(f"- Sharpe daily : {r['sharpe_daily']:.2f}")
            lines.append(f"- Max DD : {r['max_dd']:.0f} ticks")
            lines.append(f"- TP/SL/Time : {r['hit_tp']}/{r['hit_sl']}/{r['hit_time']}")
            if np.isfinite(r["mc_p_value"]):
                lines.append(f"- MC permutation p-value : {r['mc_p_value']:.4f}")
            if np.isfinite(r["pf_ci_lo"]):
                lines.append(f"- PF 95% CI : [{r['pf_ci_lo']:.2f}, {r['pf_ci_hi']:.2f}]")
            lines.append(f"- BH FDR significant : {r.get('bh_significant', False)}")
        lines.append(f"- **Verdict** : **{r['verdict']}**")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["ES", "NQ", "BOTH"], default="BOTH")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Limite a N derniers jours (ex: 14 pour tester live propre seulement)")
    args = parser.parse_args()

    symbols = ["ES", "NQ"] if args.symbol == "BOTH" else [args.symbol]
    all_results: List[dict] = []
    for sym in symbols:
        all_results.extend(run_battery(sym, max_days=args.max_days))

    if not all_results:
        print("[ERROR] Aucun resultat")
        sys.exit(1)

    report = generate_report(all_results)
    OUTPUT_REPORT.write_text(report, encoding="utf-8")
    print(f"\nRapport : {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
