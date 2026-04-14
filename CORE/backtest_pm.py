"""
Backtest Primary Model Framework — MIA V2

Framework de backtest pour les primary models MIA, avec :
  1. Triple Barrier labeling (Lopez AFML ch.3)
  2. Walk-forward purged split (Lopez ch.7 simplifie — CPCV complet viendra apres)
  3. Metriques PF, EV/trade, Sharpe, Max DD, Win Rate
  4. Monte Carlo Permutation Test (Aronson) → p-value
  5. Probabilistic Sharpe Ratio + Deflated Sharpe (Lopez ch.15)
  6. Verdict GO / NO-GO selon les seuils de la Target Sheet

Usage :
    from CORE.primary_models import PrimaryModel
    from CORE.backtest_pm import BacktestFramework

    model = VwapReversionModel()
    bt = BacktestFramework(
        dataset_path="DATA/DATASETS/ES_dataset_v2.parquet",
        tp_ticks=36,
        sl_ticks=20,
        tick_value_usd=1.25,  # ES micro
    )
    report = bt.run(model, n_permutations=1000)
    print(report.verdict)
    report.save("DATA/BACKTEST/vwap_reversion_es.json")

Auteur : MIA Trading System
Date   : 2026-04-14
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Lazy import-tolerant : accepter 2 layouts sys.path
#   - Lance depuis racine repo    : from CORE.primary_models.base import ...
#   - Lance depuis CORE/           : from primary_models.base import ...
# Fix 2026-04-14 pour que train_lightgbm puisse importer monte_carlo_permutation
# sans faire crasher toute la chaine d'imports.
try:
    from CORE.primary_models.base import PrimaryModel, SignalType
except ImportError:
    try:
        from primary_models.base import PrimaryModel, SignalType
    except ImportError:
        # Fallback ultime : les fonctions statistiques (MC, PSR, DSR) ne
        # dependent pas de PrimaryModel/SignalType. On accepte que BacktestFramework
        # ne soit pas utilisable dans ce contexte, mais les stats restent ok.
        PrimaryModel = None  # type: ignore[assignment,misc]
        SignalType = None    # type: ignore[assignment,misc]


# ─────────────────────────────────────────────────────────────────────
# LABELING : Triple Barrier simplifie (Lopez ch.3)
# ─────────────────────────────────────────────────────────────────────

def triple_barrier_labels(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    tp_ticks: int,
    sl_ticks: int,
    horizon_bars: int,
    tick_size: float,
    price_col: str = "price",
    high_col: str = "bar_high",
    low_col: str = "bar_low",
    commission_ticks: float = 0.0,
    cooldown_bars: int = 0,
) -> pd.DataFrame:
    """
    Triple Barrier Method (Lopez AFML ch.3) — version corrigee.

    Conventions critiques :
      1. Entry au prix de la bar SUIVANTE (bar i+1), pas au close de la bar signal.
         Evite le look-ahead bias.
      2. Scan TP/SL via bar_high / bar_low (pas un prix unique). Simule les intrabar moves.
      3. Pessimistic same-bar : si bar_high >= tp ET bar_low <= sl dans la meme barre,
         on assume SL touche en premier (worst case). Lopez AFML ch.3.
      4. Commission appliquee sur le pnl final (round-trip).

    Args:
        df: DataFrame avec colonnes price_col, high_col, low_col, ts
        signals: DataFrame avec colonnes ts, signal (BUY/SELL/HOLD)
        tp_ticks: Take Profit en ticks
        sl_ticks: Stop Loss en ticks
        horizon_bars: Duree max de holding en barres
        tick_size: Taille du tick (0.25 pour ES/NQ)
        commission_ticks: Commission round-trip en ticks (default 0)

    Returns:
        DataFrame avec ts, signal, entry, exit, bars_held, label, pnl_ticks
    """
    required = {price_col, high_col, low_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing price columns in df: {missing}")

    if len(signals) != len(df):
        raise ValueError(
            f"signals length ({len(signals)}) != df length ({len(df)}). "
            "Expected 1 signal per bar (HOLD for no-op)."
        )

    prices = df[price_col].values
    highs = df[high_col].values
    lows = df[low_col].values
    n = len(df)

    results = []
    last_trade_idx = -cooldown_bars - 1
    for i in range(n):
        sig_type = signals.iloc[i]["signal"]
        if sig_type not in ("BUY", "SELL"):
            continue

        # Cooldown : evite multi-comptage des signaux d'etat persistants
        # (ex: ib_broken_up reste 1 pendant toute la session apres le breakout)
        if cooldown_bars > 0 and (i - last_trade_idx) < cooldown_bars:
            continue

        # Entry au open de la bar i+1 (pas au close de la bar i = look-ahead)
        if i + 1 >= n:
            continue  # Signal sur derniere bar, impossible d'entrer
        entry_idx = i + 1
        entry_price = prices[entry_idx]
        if not np.isfinite(entry_price):
            continue  # NaN/inf dans les prix, skip le trade (data corruption)
        last_trade_idx = i

        direction = 1 if sig_type == "BUY" else -1
        tp_price = entry_price + direction * tp_ticks * tick_size
        sl_price = entry_price - direction * sl_ticks * tick_size

        end_idx = min(entry_idx + horizon_bars, n - 1)
        label = 0
        exit_idx = end_idx
        exit_price = prices[end_idx]
        pnl_ticks = 0.0

        for j in range(entry_idx, end_idx + 1):
            bar_h = highs[j]
            bar_l = lows[j]

            if direction == 1:
                tp_hit = bar_h >= tp_price
                sl_hit = bar_l <= sl_price
                if tp_hit and sl_hit:
                    # Pessimistic : SL wins when both touched same bar
                    label = -1
                    exit_idx = j
                    exit_price = sl_price
                    pnl_ticks = -sl_ticks
                    break
                if sl_hit:
                    label = -1
                    exit_idx = j
                    exit_price = sl_price
                    pnl_ticks = -sl_ticks
                    break
                if tp_hit:
                    label = 1
                    exit_idx = j
                    exit_price = tp_price
                    pnl_ticks = tp_ticks
                    break
            else:
                tp_hit = bar_l <= tp_price
                sl_hit = bar_h >= sl_price
                if tp_hit and sl_hit:
                    label = -1
                    exit_idx = j
                    exit_price = sl_price
                    pnl_ticks = -sl_ticks
                    break
                if sl_hit:
                    label = -1
                    exit_idx = j
                    exit_price = sl_price
                    pnl_ticks = -sl_ticks
                    break
                if tp_hit:
                    label = 1
                    exit_idx = j
                    exit_price = tp_price
                    pnl_ticks = tp_ticks
                    break

        if label == 0:
            pnl_ticks = direction * (exit_price - entry_price) / tick_size

        pnl_ticks -= commission_ticks

        results.append({
            "ts": signals.iloc[i].get("ts"),
            "signal": sig_type,
            "entry": float(entry_price),
            "exit": float(exit_price),
            "bars_held": int(exit_idx - entry_idx),
            "label": int(label),
            "pnl_ticks": float(pnl_ticks),
        })

    if not results:
        return pd.DataFrame(columns=[
            "ts", "signal", "entry", "exit", "bars_held", "label", "pnl_ticks"
        ])
    return pd.DataFrame(results)


# ─────────────────────────────────────────────────────────────────────
# METRIQUES
# ─────────────────────────────────────────────────────────────────────

@dataclass
class BacktestMetrics:
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_ticks: float = 0.0
    expectancy_usd: float = 0.0
    avg_win_ticks: float = 0.0
    avg_loss_ticks: float = 0.0
    max_drawdown_ticks: float = 0.0
    max_drawdown_usd: float = 0.0
    sharpe_annualized: float = 0.0
    psr: float = 0.0
    dsr: float = 0.0
    p_value_mc: float = 1.0
    total_pnl_ticks: float = 0.0
    total_pnl_usd: float = 0.0


def compute_metrics(labels: pd.DataFrame, tick_value_usd: float) -> BacktestMetrics:
    m = BacktestMetrics()
    if len(labels) == 0:
        return m

    pnl = labels["pnl_ticks"].values.astype(float)
    m.n_trades = len(pnl)
    m.total_pnl_ticks = float(pnl.sum())
    m.total_pnl_usd = m.total_pnl_ticks * tick_value_usd

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    m.win_rate = float(len(wins) / len(pnl)) if len(pnl) > 0 else 0.0
    m.avg_win_ticks = float(wins.mean()) if len(wins) > 0 else 0.0
    m.avg_loss_ticks = float(losses.mean()) if len(losses) > 0 else 0.0

    gross_win = float(wins.sum()) if len(wins) > 0 else 0.0
    gross_loss = float(-losses.sum()) if len(losses) > 0 else 0.0
    m.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    m.expectancy_ticks = float(pnl.mean())
    m.expectancy_usd = m.expectancy_ticks * tick_value_usd

    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    m.max_drawdown_ticks = float(dd.max()) if len(dd) > 0 else 0.0
    m.max_drawdown_usd = m.max_drawdown_ticks * tick_value_usd

    if m.n_trades > 1 and "ts" in labels.columns and labels["ts"].notna().any():
        labels_daily = labels.copy()
        labels_daily["day"] = pd.to_datetime(labels_daily["ts"]).dt.date
        daily_pnl = labels_daily.groupby("day")["pnl_ticks"].sum()
        if len(daily_pnl) > 1 and daily_pnl.std() > 0:
            m.sharpe_annualized = float(
                daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)
            )

    return m


# ─────────────────────────────────────────────────────────────────────
# PROBABILISTIC SHARPE / DEFLATED SHARPE (Lopez ch.15)
# ─────────────────────────────────────────────────────────────────────

def probabilistic_sharpe_ratio(
    sr_obs: float, sr_benchmark: float, n: int, skew: float, kurt: float
) -> float:
    """
    PSR(SR*) = Phi( (SR_obs - SR*) * sqrt(n-1) / sqrt(1 - skew*SR_obs + (kurt-1)/4 * SR_obs^2) )
    Retourne la probabilite que le vrai Sharpe depasse le benchmark.

    kurt = kurtosis RAW (pas excess). Pour pd.Series.kurt() qui retourne excess,
    passer `kurt_raw = kurt_excess + 3.0`.
    """
    from scipy.stats import norm
    if n < 2:
        return 0.0
    arg = 1 - skew * sr_obs + ((kurt - 1) / 4) * sr_obs ** 2
    if not np.isfinite(arg) or arg <= 0:
        return 0.0
    denom = np.sqrt(arg)
    if not np.isfinite(denom) or denom <= 0:
        return 0.0
    z = (sr_obs - sr_benchmark) * np.sqrt(n - 1) / denom
    result = float(norm.cdf(z))
    if not np.isfinite(result):
        return 0.0
    return result


def deflated_sharpe_ratio(
    sr_obs: float, n: int, skew: float, kurt: float, n_trials: int
) -> float:
    """
    DSR ajuste pour le multiple testing (Bailey & Lopez de Prado 2014).
    Si n_trials strategies ont ete testees, SR_max_chance = sqrt(2*ln(n_trials)).

    n_trials doit etre >= 1.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return probabilistic_sharpe_ratio(sr_obs, 0.0, n, skew, kurt)
    euler_mascheroni = 0.5772156649
    sr_max_chance = np.sqrt(2 * np.log(n_trials)) - euler_mascheroni / np.sqrt(
        2 * np.log(n_trials)
    )
    return probabilistic_sharpe_ratio(sr_obs, sr_max_chance, n, skew, kurt)


# ─────────────────────────────────────────────────────────────────────
# MONTE CARLO PERMUTATION TEST (Aronson)
# ─────────────────────────────────────────────────────────────────────

def monte_carlo_permutation(
    pnl_ticks: np.ndarray, n_permutations: int = 1000, seed: int = 42
) -> float:
    """
    Test de permutation rigoureux (Aronson, Evidence-Based TA ch.6-7).

    Methode : permuter les SIGNES des pnl via rng.permutation (pas rng.choice)
    pour preserver exactement le nombre de gains/pertes de l'echantillon original.
    Compute la fraction de permutations ou le mean egale ou depasse l'observed.

    Warning : si tous les pnl sont du meme signe (WR=0% ou 100%), la permutation
    de signes est degeneree et la p-value devient triviale (= 1.0). Dans ce cas,
    on bascule sur un bootstrap des magnitudes pour tester H0 : mean <= 0.

    Returns:
        p-value : probabilite d'observer un mean >= observed sous H0 (edge = 0).
        p <= 0.05 → rejet H0 → edge statistiquement significatif.
    """
    if len(pnl_ticks) == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    observed_mean = float(pnl_ticks.mean())
    signs = np.sign(pnl_ticks)
    magnitudes = np.abs(pnl_ticks)

    unique_signs = set(signs[signs != 0].tolist())
    if len(unique_signs) < 2:
        if observed_mean <= 0:
            return 1.0
        count_above = 0
        n = len(pnl_ticks)
        for _ in range(n_permutations):
            boot_signs = rng.choice([-1, 1], size=n)
            if (magnitudes * boot_signs).mean() >= observed_mean:
                count_above += 1
        return (count_above + 1) / (n_permutations + 1)

    count_above = 0
    for _ in range(n_permutations):
        perm_signs = rng.permutation(signs)
        perm_pnl = magnitudes * perm_signs
        if perm_pnl.mean() >= observed_mean:
            count_above += 1
    return (count_above + 1) / (n_permutations + 1)


# ─────────────────────────────────────────────────────────────────────
# WALK-FORWARD SPLIT
# ─────────────────────────────────────────────────────────────────────

def walk_forward_splits(
    n_samples: int, n_folds: int = 5, embargo_bars: int = 0
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Walk-forward chronologique avec embargo (Lopez AFML ch.7).

    Train = [0 .. k*size - embargo], Test = [k*size .. (k+1)*size].
    L'embargo empeche le leakage des labels overlappes entre train et test.

    Args:
        n_samples: Nombre total de samples
        n_folds: Nombre de folds (default 5)
        embargo_bars: Nombre de barres a retirer en fin de train pour eviter leakage.
                      Doit etre >= horizon_bars du labeler. Default 0 (no embargo).

    Returns:
        Liste de (train_idx, test_idx) pour chaque fold.
    """
    if n_folds <= 0:
        raise ValueError(f"n_folds must be > 0, got {n_folds}")
    if n_samples < (n_folds + 1):
        return []

    splits = []
    fold_size = n_samples // (n_folds + 1)
    for k in range(1, n_folds + 1):
        train_end_raw = k * fold_size
        train_end = max(0, train_end_raw - embargo_bars)
        test_start = train_end_raw
        test_end = min((k + 1) * fold_size, n_samples)
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        if len(train_idx) > 0 and len(test_idx) > 0:
            splits.append((train_idx, test_idx))
    return splits


# ─────────────────────────────────────────────────────────────────────
# RAPPORT BACKTEST
# ─────────────────────────────────────────────────────────────────────

@dataclass
class BacktestReport:
    model_name: str
    dataset: str
    n_bars: int
    tp_ticks: int
    sl_ticks: int
    horizon_bars: int
    tick_value_usd: float
    metrics_oos: BacktestMetrics
    metrics_is: BacktestMetrics = field(default_factory=BacktestMetrics)
    metrics_per_fold: list[BacktestMetrics] = field(default_factory=list)
    degradation_is_oos_pct: float = 0.0
    verdict: str = "UNKNOWN"
    reasons: list[str] = field(default_factory=list)

    @property
    def metrics_all(self) -> BacktestMetrics:
        """Alias backward-compat : retourne metrics_oos (le report se base sur l'OOS)."""
        return self.metrics_oos

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────
# FRAMEWORK PRINCIPAL
# ─────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    tp_ticks: int = 36
    sl_ticks: int = 20
    horizon_bars: int = 60
    tick_size: float = 0.25
    tick_value_usd: float = 1.25
    commission_ticks_per_rt: float = 0.5
    price_col: str = "price"
    high_col: str = "bar_high"
    low_col: str = "bar_low"
    cooldown_bars: int = 60
    n_folds: int = 5
    embargo_bars: int = 60
    n_permutations: int = 1000
    n_trials_optuna: int = 1
    min_trades: int = 100
    min_profit_factor: float = 1.3
    min_expectancy_ticks: float = 2.0
    max_degradation_pct: float = 30.0
    max_p_value: float = 0.05


class BacktestFramework:
    """
    Framework de backtest pour un primary model MIA.
    Applique Triple Barrier + Walk-forward + Monte Carlo + PSR.
    """

    def __init__(self, dataset_path: str | Path, config: Optional[BacktestConfig] = None):
        self.dataset_path = Path(dataset_path)
        self.config = config or BacktestConfig()
        self.df: Optional[pd.DataFrame] = None

    def load(self) -> pd.DataFrame:
        if self.dataset_path.suffix == ".parquet":
            self.df = pd.read_parquet(self.dataset_path)
        else:
            self.df = pd.read_csv(self.dataset_path)
        return self.df

    def run(self, model: PrimaryModel, save_path: Optional[str | Path] = None) -> BacktestReport:
        if self.df is None:
            self.load()
        df = self.df
        c = self.config

        signals = model.run(df)
        labels = triple_barrier_labels(
            df, signals,
            tp_ticks=c.tp_ticks,
            sl_ticks=c.sl_ticks,
            horizon_bars=c.horizon_bars,
            tick_size=c.tick_size,
            price_col=c.price_col,
            high_col=c.high_col,
            low_col=c.low_col,
            commission_ticks=c.commission_ticks_per_rt,
            cooldown_bars=c.cooldown_bars,
        )

        metrics_all = compute_metrics(labels, c.tick_value_usd)

        if metrics_all.n_trades == 0:
            return self._empty_report(model, df, verdict="NO-GO",
                                       reasons=["No trades generated"])

        splits = walk_forward_splits(len(labels), c.n_folds, c.embargo_bars)
        if not splits:
            return self._empty_report(
                model, df, verdict="NO-GO",
                reasons=[f"walk_forward_splits empty (n_samples={len(labels)}, "
                         f"n_folds={c.n_folds}, embargo={c.embargo_bars})"]
            )

        fold_metrics = []
        oos_labels_all = []
        for train_idx, test_idx in splits:
            if len(test_idx) > 0:
                test_labels = labels.iloc[test_idx]
                fm = compute_metrics(test_labels, c.tick_value_usd)
                fold_metrics.append(fm)
                oos_labels_all.append(test_labels)

        # IS = train_idx du DERNIER fold (le plus proche des OOS, convention
        # walk-forward expanding window Lopez AFML ch.7)
        last_train_idx = splits[-1][0]
        is_labels = labels.iloc[last_train_idx] if len(last_train_idx) > 0 else labels.iloc[0:0]
        metrics_is = compute_metrics(is_labels, c.tick_value_usd)

        oos_concat = pd.concat(oos_labels_all, ignore_index=True) if oos_labels_all else labels.iloc[0:0]
        metrics_oos = compute_metrics(oos_concat, c.tick_value_usd)
        if len(oos_concat) > 0:
            metrics_oos.p_value_mc = monte_carlo_permutation(
                oos_concat["pnl_ticks"].values, c.n_permutations
            )

        pnl_oos = (oos_concat["pnl_ticks"].values
                   if oos_labels_all else labels["pnl_ticks"].values)
        if len(pnl_oos) > 2 and pnl_oos.std() > 0:
            sr_obs = metrics_oos.sharpe_annualized
            skew = float(pd.Series(pnl_oos).skew())
            kurt_excess = float(pd.Series(pnl_oos).kurt())
            kurt_raw = kurt_excess + 3.0
            metrics_oos.psr = probabilistic_sharpe_ratio(
                sr_obs, sr_benchmark=1.0, n=len(pnl_oos), skew=skew, kurt=kurt_raw
            )
            metrics_oos.dsr = deflated_sharpe_ratio(
                sr_obs, n=len(pnl_oos), skew=skew, kurt=kurt_raw,
                n_trials=c.n_trials_optuna
            )

        degradation = 0.0
        if metrics_is.profit_factor > 0 and metrics_oos.profit_factor > 0 \
                and metrics_oos.profit_factor != float("inf"):
            degradation = (metrics_is.profit_factor - metrics_oos.profit_factor) \
                          / metrics_is.profit_factor * 100

        verdict, reasons = self._verdict(metrics_oos, degradation)

        report = BacktestReport(
            model_name=model.name,
            dataset=str(self.dataset_path),
            n_bars=len(df),
            tp_ticks=c.tp_ticks,
            sl_ticks=c.sl_ticks,
            horizon_bars=c.horizon_bars,
            tick_value_usd=c.tick_value_usd,
            metrics_oos=metrics_oos,
            metrics_is=metrics_is,
            metrics_per_fold=fold_metrics,
            degradation_is_oos_pct=float(degradation),
            verdict=verdict,
            reasons=reasons,
        )

        if save_path:
            report.save(save_path)
        return report

    def _empty_report(self, model, df, verdict, reasons) -> BacktestReport:
        c = self.config
        return BacktestReport(
            model_name=model.name,
            dataset=str(self.dataset_path),
            n_bars=len(df),
            tp_ticks=c.tp_ticks,
            sl_ticks=c.sl_ticks,
            horizon_bars=c.horizon_bars,
            tick_value_usd=c.tick_value_usd,
            metrics_oos=BacktestMetrics(),
            metrics_is=BacktestMetrics(),
            metrics_per_fold=[],
            degradation_is_oos_pct=0.0,
            verdict=verdict,
            reasons=reasons,
        )

    def _verdict(self, m: BacktestMetrics, degradation: float) -> tuple[str, list[str]]:
        c = self.config
        reasons = []
        go = True

        if m.n_trades < c.min_trades:
            reasons.append(f"Trades {m.n_trades} < {c.min_trades}")
            go = False
        if not np.isfinite(m.profit_factor):
            reasons.append(f"PF is infinite (zero losses suspicious — need both wins and losses)")
            go = False
        elif m.profit_factor < c.min_profit_factor:
            reasons.append(f"PF {m.profit_factor:.2f} < {c.min_profit_factor}")
            go = False
        if m.expectancy_ticks < c.min_expectancy_ticks:
            reasons.append(f"EV {m.expectancy_ticks:.2f}t < {c.min_expectancy_ticks}t")
            go = False
        if m.p_value_mc > c.max_p_value:
            reasons.append(f"p-value {m.p_value_mc:.3f} > {c.max_p_value}")
            go = False
        if degradation > c.max_degradation_pct:
            reasons.append(f"Degradation OOS {degradation:.1f}% > {c.max_degradation_pct}%")
            go = False

        if go:
            return "GO", reasons or ["All criteria passed"]
        return "NO-GO", reasons
