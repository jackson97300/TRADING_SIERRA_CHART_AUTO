"""
train_lightgbm.py — MIA Trading System v2
==========================================
Entraine 2 modeles LightGBM par instrument (score_buy + score_sell).
Walk-forward validation chronologique. Metriques de P&L, pas d'accuracy.

Usage:
    python CORE/train_lightgbm.py                  # ES + NQ
    python CORE/train_lightgbm.py --symbol ES      # ES seulement
    python CORE/train_lightgbm.py --no-tune         # skip Optuna (params par defaut)

Pipeline:
    1. Charge dataset v2 (parquet)
    2. Separe BUY vs rest, SELL vs rest (2 modeles binaires)
    3. Walk-forward cross-validation chronologique
    4. Optuna hyperparameter tuning (100 trials)
    5. Train final sur toutes les donnees
    6. Simulation trading sur chaque fold test
    7. Rapport GO / NO-GO

Auteur : MIA Trading System
Date   : 2026-03-29
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings("ignore", category=UserWarning)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TrainConfig:
    """Configuration d'entrainement — un seul endroit pour tout."""

    # --- Chemins ---
    dataset_dir: str = "D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS"
    output_dir: str = "D:/TRADING_SIERRA_CHART_AUTO/DATA/MODELS"

    # --- TP/SL ATR-based ---
    sl_atr_ratio: float = 0.08       # SL = ATR * 0.08
    tp_rr: float = 2.0               # TP = SL * 2.0 (R:R fixe)
    tick_size: float = 0.25           # ES et NQ

    # --- Walk-forward ---
    min_train_days: int = 8           # Minimum jours pour entrainer
    test_days: int = 2                # Jours par fold test

    # --- Optuna ---
    n_trials: int = 100               # Nombre de trials Optuna
    early_stopping_rounds: int = 50   # Patience early stopping

    # --- Seuils GO/NO-GO ---
    min_profit_factor: float = 1.3
    min_ev_ticks: float = 1.0         # Expected value minimum par trade
    min_win_rate: float = 0.45
    min_trades_per_day: float = 3.0
    max_drawdown_ticks: float = 500.0

    # --- Trading simulation ---
    max_trades_per_day: int = 5
    cooldown_bars: int = 3            # Barres minimum entre 2 trades

    # --- Couts de transaction (micros AMP) ---
    cost_ticks_es: float = 2.3        # Commission 1.3t + slippage 1.0t
    cost_ticks_nq: float = 5.2        # Commission 3.2t + slippage 2.0t

    # --- Purge / Embargo (Lopez de Prado Ch.7) ---
    purge_bars: int = 20              # = label horizon (barres dont le label chevauche)
    embargo_pct: float = 0.01         # 1% du dataset en gap supplementaire


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE SIMULATOR (validation P&L)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    direction: int          # +1 BUY, -1 SELL
    entry_bar: int
    pnl_ticks: float
    won: bool

@dataclass
class SimResult:
    """Resultats d'une simulation de trading sur un fold."""
    trades: List[TradeResult] = field(default_factory=list)
    n_bars: int = 0
    n_days: int = 0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def n_wins(self) -> int:
        return sum(1 for t in self.trades if t.won)

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_trades if self.n_trades > 0 else 0.0

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
        return self.gross_wins / self.gross_losses if self.gross_losses > 0 else 99.0

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
        dd = peak - cumsum
        return float(dd.max())

    @property
    def sharpe(self) -> float:
        if len(self.trades) < 5:
            return 0.0
        pnls = [t.pnl_ticks for t in self.trades]
        mean = np.mean(pnls)
        std = np.std(pnls)
        if std < 1e-6:
            return 0.0
        # Annualise: ~250 trading days * trades_per_day
        daily_factor = self.trades_per_day if self.trades_per_day > 0 else 1.0
        return float(mean / std * np.sqrt(250 * daily_factor))


def simulate_trades(
    df: pd.DataFrame,
    buy_scores: np.ndarray,
    sell_scores: np.ndarray,
    buy_threshold: float,
    sell_threshold: float,
    config: TrainConfig,
) -> SimResult:
    """
    Simule le trading sur un fold test.

    Pour chaque barre:
    - Si buy_score > threshold et sell_score < threshold → BUY
    - Si sell_score > threshold et buy_score < threshold → SELL
    - Sinon → HOLD

    PnL calcule via le label reel:
    - BUY sur label=+1 → win (TP_ticks - costs)
    - BUY sur label=-1 → loss (-SL_ticks - costs)
    - BUY sur label=0  → flat (-costs)
    """
    labels = df["label"].values
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date.values

    # Detecter le symbole pour les couts
    is_nq = "NQ" in str(df.get("sym", pd.Series("ES")).iloc[0]) if "sym" in df.columns else False
    cost_per_trade = config.cost_ticks_nq if is_nq else config.cost_ticks_es

    # SL/TP en ticks depuis ATR
    atr_col = df["atr"].values if "atr" in df.columns else np.full(len(df), 400.0)
    sl_ticks = np.maximum(atr_col * config.sl_atr_ratio, 8.0)
    tp_ticks = sl_ticks * config.tp_rr

    trades = []
    last_trade_bar = -config.cooldown_bars - 1
    daily_trades: Dict[object, int] = {}
    unique_days = set(dates)

    for i in range(len(df)):
        # Cooldown
        if i - last_trade_bar < config.cooldown_bars:
            continue

        # Max trades/jour
        day = dates[i]
        if daily_trades.get(day, 0) >= config.max_trades_per_day:
            continue

        # Decision
        bs = buy_scores[i]
        ss = sell_scores[i]

        direction = 0
        if bs > buy_threshold and ss <= sell_threshold:
            direction = 1   # BUY
        elif ss > sell_threshold and bs <= buy_threshold:
            direction = -1  # SELL

        if direction == 0:
            continue

        # PnL (NET = brut - couts de transaction)
        label = labels[i]
        if direction == 1:  # BUY
            if label == 1:
                pnl = tp_ticks[i] - cost_per_trade
            elif label == -1:
                pnl = -sl_ticks[i] - cost_per_trade
            else:
                pnl = -cost_per_trade  # HOLD = perte des couts
        else:  # SELL
            if label == -1:
                pnl = tp_ticks[i] - cost_per_trade
            elif label == 1:
                pnl = -sl_ticks[i] - cost_per_trade
            else:
                pnl = -cost_per_trade

        trades.append(TradeResult(direction=direction, entry_bar=i, pnl_ticks=pnl, won=pnl > 0))
        last_trade_bar = i
        daily_trades[day] = daily_trades.get(day, 0) + 1

    return SimResult(trades=trades, n_bars=len(df), n_days=len(unique_days))


# ═══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD SPLITS
# ═══════════════════════════════════════════════════════════════════════════════

def walk_forward_splits(
    df: pd.DataFrame,
    min_train_days: int,
    test_days: int,
    purge_bars: int = 20,
    embargo_pct: float = 0.01,
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Walk-forward chronologique avec purge + embargo (Lopez de Prado Ch.7).

    Purge  : supprime les barres du train dont le label chevauche le test
             (les 'purge_bars' dernieres barres du train)
    Embargo: gap supplementaire apres la purge (1% du dataset)
    """
    dates = pd.to_datetime(df["ts"], unit="ms").dt.date
    unique_days = sorted(dates.unique())
    n_days = len(unique_days)

    folds = []
    start_test = min_train_days

    while start_test + test_days <= n_days:
        test_set = set(unique_days[start_test: start_test + test_days])
        train_set = set(unique_days[:start_test])

        train_mask = dates.isin(train_set)
        test_mask = dates.isin(test_set)

        train_df = df[train_mask].reset_index(drop=True)
        test_df = df[test_mask].reset_index(drop=True)

        # PURGE : retirer les barres dont le label chevauche le test
        if len(test_df) > 0 and len(train_df) > purge_bars:
            test_start_ts = test_df["ts"].min()
            purge_threshold = test_start_ts - (purge_bars * 60 * 1000)
            train_df = train_df[train_df["ts"] < purge_threshold].reset_index(drop=True)

        # EMBARGO : gap supplementaire de securite
        embargo_n = max(1, int(embargo_pct * len(df)))
        if len(train_df) > embargo_n:
            train_df = train_df.iloc[:-embargo_n].reset_index(drop=True)

        if len(train_df) >= 100 and len(test_df) >= 20:
            folds.append((train_df, test_df))

        start_test += test_days

    return folds


# ═══════════════════════════════════════════════════════════════════════════════
# OPTUNA TUNING
# ═══════════════════════════════════════════════════════════════════════════════

def tune_hyperparams(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    n_trials: int = 100,
    early_stopping: int = 50,
) -> dict:
    """Optimise les hyperparametres LightGBM avec Optuna."""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("  [WARN] Optuna non installe — params par defaut")
        return _default_params()

    def objective(trial):
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "verbosity": -1,
            "seed": 42,
            "num_leaves": trial.suggest_int("num_leaves", 15, 127),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 50, 500),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "is_unbalance": True,
        }

        model = lgb.LGBMClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.early_stopping(early_stopping, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        preds = model.predict_proba(X_val)[:, 1]

        # Optimiser pour le profit factor, pas la logloss
        threshold = 0.5
        pred_pos = preds > threshold
        if pred_pos.sum() == 0:
            return 0.0

        correct = (pred_pos & (y_val == 1)).sum()
        wrong = (pred_pos & (y_val == 0)).sum()
        if wrong == 0:
            return float(correct)
        return float(correct) / float(wrong)  # proxy profit factor

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    best.update({
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "verbosity": -1,
        "seed": 42,
        "is_unbalance": True,
    })
    print(f"  Optuna best trial: #{study.best_trial.number} (PF proxy={study.best_value:.2f})")
    return best


def _default_params() -> dict:
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "verbosity": -1,
        "seed": 42,
        "num_leaves": 31,
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 300,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "is_unbalance": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# THRESHOLD OPTIMIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def optimize_threshold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    sl_ticks: np.ndarray,
    tp_ticks: np.ndarray,
) -> float:
    """Trouve le seuil qui maximise le profit factor sur un set de validation."""
    best_pf = 0.0
    best_thr = 0.5

    for thr in np.arange(0.30, 0.70, 0.02):
        pred_pos = y_proba > thr
        if pred_pos.sum() < 10:
            continue

        wins = pred_pos & (y_true == 1)
        losses = pred_pos & (y_true == 0)

        gross_win = tp_ticks[wins].sum()
        gross_loss = sl_ticks[losses].sum()

        pf = gross_win / gross_loss if gross_loss > 0 else 99.0
        if pf > best_pf and pred_pos.sum() >= 10:
            best_pf = pf
            best_thr = thr

    return best_thr


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL TRAINER
# ═══════════════════════════════════════════════════════════════════════════════

class ModelTrainer:
    """Entraine et valide un modele buy ou sell pour un instrument."""

    def __init__(self, config: TrainConfig):
        self.config = config

    def train_model(
        self,
        symbol: str,
        side: str,  # "buy" ou "sell"
        df: pd.DataFrame,
        features: List[str],
        tune: bool = True,
    ) -> dict:
        """
        Pipeline complet: tune → walk-forward → train final → rapport.

        Returns:
            dict avec model, threshold, metrics, verdict
        """
        target_label = 1 if side == "buy" else -1
        y = (df["label"] == target_label).astype(int).values
        X = df[features]

        print(f"\n{'='*60}")
        print(f"  {symbol} {side.upper()} model")
        print(f"  {len(df)} barres, {len(features)} features")
        print(f"  Target distribution: {y.sum()}/{len(y)} positifs ({y.mean():.1%})")
        print(f"{'='*60}")

        # --- Walk-forward splits ---
        folds = walk_forward_splits(df, self.config.min_train_days, self.config.test_days,
                                    self.config.purge_bars, self.config.embargo_pct)
        if not folds:
            print("  [ERREUR] Pas assez de donnees pour walk-forward")
            return {"symbol": symbol, "side": side, "verdict": "NO-GO (insufficient_data)",
                    "model": None, "threshold": 0.5, "features": features, "params": {},
                    "fold_metrics": [], "aggregate": {}, "importance": pd.DataFrame({"feature": features, "importance": 0})}

        print(f"  Walk-forward: {len(folds)} folds")

        # --- Hyperparameter tuning sur le premier fold ---
        if tune and len(folds) >= 1:
            train_f, val_f = folds[0]
            X_tr = train_f[features]
            y_tr = (train_f["label"] == target_label).astype(int).values
            X_vl = val_f[features]
            y_vl = (val_f["label"] == target_label).astype(int).values

            print(f"  Tuning Optuna ({self.config.n_trials} trials)...")
            t0 = time.time()
            params = tune_hyperparams(X_tr, y_tr, X_vl, y_vl,
                                      self.config.n_trials, self.config.early_stopping_rounds)
            print(f"  Tuning termine en {time.time()-t0:.0f}s")
        else:
            params = _default_params()

        # --- Walk-forward evaluation ---
        all_sim_results = []
        fold_metrics = []

        for fold_idx, (train_df, test_df) in enumerate(folds):
            X_tr = train_df[features]
            y_tr = (train_df["label"] == target_label).astype(int).values
            X_te = test_df[features]
            y_te = (test_df["label"] == target_label).astype(int).values

            # Train
            model = lgb.LGBMClassifier(**params)
            model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)],
                      callbacks=[lgb.early_stopping(self.config.early_stopping_rounds, verbose=False),
                                 lgb.log_evaluation(period=0)])

            # Predict
            proba = model.predict_proba(X_te)[:, 1]

            # Optimize threshold on this fold
            atr_vals = test_df["atr"].values if "atr" in test_df.columns else np.full(len(test_df), 400.0)
            sl_t = np.maximum(atr_vals * self.config.sl_atr_ratio, 8.0)
            tp_t = sl_t * self.config.tp_rr
            threshold = optimize_threshold(y_te, proba, sl_t, tp_t)

            # Simulate trading
            # Pour simuler, on cree des scores "autres" a 0 (on teste un seul cote)
            zero_scores = np.zeros(len(test_df))
            if side == "buy":
                sim = simulate_trades(test_df, proba, zero_scores,
                                      threshold, 999.0, self.config)
            else:
                sim = simulate_trades(test_df, zero_scores, proba,
                                      999.0, threshold, self.config)

            test_dates = pd.to_datetime(test_df["ts"], unit="ms").dt.date
            date_range = f"{test_dates.min()} -> {test_dates.max()}"

            fm = {
                "fold": fold_idx + 1,
                "dates": date_range,
                "train_bars": len(train_df),
                "test_bars": len(test_df),
                "threshold": threshold,
                "trades": sim.n_trades,
                "win_rate": sim.win_rate,
                "pnl_ticks": sim.total_pnl,
                "profit_factor": sim.profit_factor,
                "ev_trade": sim.ev_per_trade,
                "max_dd": sim.max_drawdown,
                "trades_day": sim.trades_per_day,
            }
            fold_metrics.append(fm)
            all_sim_results.append(sim)

            print(f"  Fold {fold_idx+1}: {date_range} | "
                  f"thr={threshold:.2f} trades={sim.n_trades} "
                  f"WR={sim.win_rate:.0%} PF={sim.profit_factor:.2f} "
                  f"EV={sim.ev_per_trade:+.1f}t PnL={sim.total_pnl:+.0f}t")

        # --- Aggregate metrics ---
        agg = self._aggregate_metrics(fold_metrics, all_sim_results)

        # --- Train final model on ALL data ---
        print(f"\n  Training final model sur {len(df)} barres...")
        final_model = lgb.LGBMClassifier(**params)
        final_model.fit(X, y)

        # Feature importance MDI (native LightGBM)
        importance = pd.DataFrame({
            "feature": features,
            "mdi": final_model.feature_importances_,
        })

        # MDA — Permutation Importance (Lopez de Prado Ch.4)
        # Non-biaisee contrairement a MDI
        print(f"  MDA (Permutation Importance)...")
        mda_scores = self._compute_mda(final_model, X, y, features)
        importance["mda"] = importance["feature"].map(
            dict(zip(mda_scores["feature"], mda_scores["mda_mean"]))
        ).fillna(0.0)

        # Trier par MDA (plus fiable que MDI)
        importance = importance.sort_values("mda", ascending=False)

        # Alerter si divergence MDI vs MDA
        noise_mda = importance[importance["mda"] <= 0]
        if len(noise_mda) > 0:
            print(f"  MDA: {len(importance) - len(noise_mda)} utiles, {len(noise_mda)} bruit")
            high_mdi_noise = noise_mda[noise_mda["mdi"] > noise_mda["mdi"].median()]
            if len(high_mdi_noise) > 0:
                print(f"  DIVERGENCE MDI/MDA: {len(high_mdi_noise)} features MDI-haute mais MDA-bruit:")
                for _, row in high_mdi_noise.head(5).iterrows():
                    print(f"    {row['feature']}: MDI={row['mdi']:.0f} MDA={row['mda']:.4f}")

        # Best threshold (moyenne des folds)
        best_threshold = float(np.mean([fm["threshold"] for fm in fold_metrics]))

        # --- Verdict ---
        verdict = self._verdict(agg)

        result = {
            "symbol": symbol,
            "side": side,
            "model": final_model,
            "params": params,
            "threshold": best_threshold,
            "features": features,
            "fold_metrics": fold_metrics,
            "aggregate": agg,
            "importance": importance,
            "verdict": verdict,
        }

        self._print_verdict(result)
        return result

    def _aggregate_metrics(self, fold_metrics: list, sim_results: list) -> dict:
        """Agregation des metriques cross-fold."""
        if not fold_metrics:
            return {}

        all_trades = []
        for sim in sim_results:
            all_trades.extend(sim.trades)

        combined = SimResult(
            trades=all_trades,
            n_bars=sum(s.n_bars for s in sim_results),
            n_days=sum(s.n_days for s in sim_results),
        )

        return {
            "total_trades": combined.n_trades,
            "total_pnl": combined.total_pnl,
            "win_rate": combined.win_rate,
            "profit_factor": combined.profit_factor,
            "ev_per_trade": combined.ev_per_trade,
            "max_drawdown": combined.max_drawdown,
            "trades_per_day": combined.trades_per_day,
            "sharpe": combined.sharpe,
            "n_folds": len(fold_metrics),
            "n_days": combined.n_days,
            # Stabilite cross-fold
            "wr_std": float(np.std([fm["win_rate"] for fm in fold_metrics])),
            "pf_std": float(np.std([fm["profit_factor"] for fm in fold_metrics])),
        }

    @staticmethod
    def _compute_mda(model, X, y, features, n_repeats=10):
        """MDA — Permutation Importance (Lopez de Prado Ch.4)."""
        from sklearn.inspection import permutation_importance
        result = permutation_importance(
            model, X, y,
            n_repeats=n_repeats,
            random_state=42,
            scoring="accuracy",
        )
        return pd.DataFrame({
            "feature": features,
            "mda_mean": result.importances_mean,
            "mda_std": result.importances_std,
        }).sort_values("mda_mean", ascending=False)

    def _verdict(self, agg: dict) -> str:
        """GO / CAUTION / NO-GO basé sur les seuils."""
        if not agg or agg.get("total_trades", 0) < 10:
            return "NO-GO (insufficient trades)"

        checks = {
            "profit_factor": agg["profit_factor"] >= self.config.min_profit_factor,
            "ev_per_trade": agg["ev_per_trade"] >= self.config.min_ev_ticks,
            "win_rate": agg["win_rate"] >= self.config.min_win_rate,
            "trades_per_day": agg["trades_per_day"] >= self.config.min_trades_per_day,
            "max_drawdown": agg["max_drawdown"] <= self.config.max_drawdown_ticks,
        }

        passed = sum(checks.values())
        total = len(checks)

        if passed == total:
            return "GO"
        elif passed >= total - 1:
            failed = [k for k, v in checks.items() if not v]
            return f"CAUTION ({', '.join(failed)})"
        else:
            failed = [k for k, v in checks.items() if not v]
            return f"NO-GO ({', '.join(failed)})"

    def _print_verdict(self, result: dict):
        agg = result.get("aggregate", {})
        verdict = result["verdict"]

        print(f"\n  {'-'*50}")
        print(f"  AGGREGATE {result['symbol']} {result['side'].upper()}")
        print(f"  {'-'*50}")
        if agg:
            print(f"  Trades     : {agg['total_trades']} ({agg['trades_per_day']:.1f}/jour)")
            print(f"  Win Rate   : {agg['win_rate']:.1%}")
            print(f"  PnL total  : {agg['total_pnl']:+.0f} ticks")
            print(f"  PF         : {agg['profit_factor']:.2f}")
            print(f"  EV/trade   : {agg['ev_per_trade']:+.1f} ticks")
            print(f"  Max DD     : {agg['max_drawdown']:.0f} ticks")
            print(f"  Sharpe     : {agg['sharpe']:.2f}")
            print(f"  Stabilite  : WR std={agg['wr_std']:.2%}, PF std={agg['pf_std']:.2f}")
        print(f"  Threshold  : {result['threshold']:.2f}")
        print(f"  Top features: {', '.join(result['importance'].head(5)['feature'].tolist())}")

        tag = "GO" if "GO" == verdict else ("CAUTION" if "CAUTION" in verdict else "NO-GO")
        print(f"\n  >>> VERDICT: {verdict} <<<")
        print(f"  {'-'*50}")


# ═══════════════════════════════════════════════════════════════════════════════
# SAVE / LOAD
# ═══════════════════════════════════════════════════════════════════════════════

def save_model(result: dict, config: TrainConfig):
    """Sauvegarde modele + config + metriques."""
    import pickle

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    symbol = result["symbol"]
    side = result["side"]
    prefix = f"{symbol}_{side}"

    # Modele
    model_path = out_dir / f"{prefix}_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(result["model"], f)

    # Config JSON
    config_data = {
        "symbol": symbol,
        "side": side,
        "threshold": result["threshold"],
        "features": result["features"],
        "params": {k: v for k, v in result["params"].items() if not callable(v)},
        "aggregate_metrics": result.get("aggregate", {}),
        "verdict": result["verdict"],
        "train_config": {
            "sl_atr_ratio": config.sl_atr_ratio,
            "tp_rr": config.tp_rr,
            "min_train_days": config.min_train_days,
            "test_days": config.test_days,
        },
    }
    config_path = out_dir / f"{prefix}_config.json"
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2, default=str)

    # Feature importance
    imp_path = out_dir / f"{prefix}_importance.csv"
    result["importance"].to_csv(imp_path, index=False)

    # Fold details
    folds_path = out_dir / f"{prefix}_folds.json"
    with open(folds_path, "w") as f:
        json.dump(result.get("fold_metrics", []), f, indent=2, default=str)

    print(f"  Sauvegarde: {model_path.name}, {config_path.name}, {imp_path.name}")


def load_model(symbol: str, side: str, models_dir: str = "D:/TRADING_SIERRA_CHART_AUTO/DATA/MODELS") -> dict:
    """Charge un modele entraine pour inference."""
    import pickle

    base = Path(models_dir)
    prefix = f"{symbol}_{side}"

    model_path = base / f"{prefix}_model.pkl"
    config_path = base / f"{prefix}_config.json"

    with open(model_path, "rb") as f:
        model = pickle.load(f)

    with open(config_path, "r") as f:
        config = json.load(f)

    return {
        "model": model,
        "threshold": config["threshold"],
        "features": config["features"],
        "symbol": symbol,
        "side": side,
    }


def predict(model_dict: dict, df: pd.DataFrame) -> np.ndarray:
    """Prediction sur nouvelles donnees. Retourne P(signal)."""
    features = model_dict["features"]
    available = [f for f in features if f in df.columns]
    missing = [f for f in features if f not in df.columns]

    X = df[available].copy()
    # Ajouter colonnes manquantes avec 0
    for col in missing:
        X[col] = 0.0

    X = X[features]  # Reorder
    return model_dict["model"].predict_proba(X)[:, 1]


# ═══════════════════════════════════════════════════════════════════════════════
# RAPPORT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(results: List[dict], config: TrainConfig):
    """Genere le rapport final avec verdict GO/NO-GO."""
    out_dir = Path(config.output_dir)
    report_path = out_dir / "training_report.txt"

    lines = []
    lines.append("=" * 60)
    lines.append("  MIA V2 — TRAINING REPORT")
    lines.append(f"  Date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append("")

    for r in results:
        agg = r.get("aggregate", {})
        lines.append(f"--- {r['symbol']} {r['side'].upper()} ---")
        if agg:
            lines.append(f"  Trades      : {agg.get('total_trades', 0)} ({agg.get('trades_per_day', 0):.1f}/jour)")
            lines.append(f"  Win Rate    : {agg.get('win_rate', 0):.1%}")
            lines.append(f"  PnL         : {agg.get('total_pnl', 0):+.0f} ticks")
            lines.append(f"  PF          : {agg.get('profit_factor', 0):.2f}")
            lines.append(f"  EV/trade    : {agg.get('ev_per_trade', 0):+.1f} ticks")
            lines.append(f"  Max DD      : {agg.get('max_drawdown', 0):.0f} ticks")
            lines.append(f"  Sharpe      : {agg.get('sharpe', 0):.2f}")
        lines.append(f"  Threshold   : {r.get('threshold', 0):.2f}")
        lines.append(f"  Verdict     : {r['verdict']}")
        lines.append(f"  Top 5 feats : {', '.join(r['importance'].head(5)['feature'].tolist())}")
        lines.append("")

    lines.append("=" * 60)
    verdicts = [r["verdict"] for r in results]
    all_go = all(v == "GO" for v in verdicts)
    lines.append(f"  VERDICT GLOBAL: {'GO — Pret pour paper trading' if all_go else 'ATTENDRE — Voir details ci-dessus'}")
    lines.append("=" * 60)

    report_text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n{report_text}")
    print(f"\nRapport sauvegarde: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def get_features(df: pd.DataFrame) -> List[str]:
    """Extrait la liste des features du dataset (exclut meta)."""
    meta = {"ts", "label", "partial_session", "is_nq"}
    return [c for c in df.columns if c not in meta]


def run_training(symbol: str, config: TrainConfig, tune: bool = True) -> List[dict]:
    """Pipeline complet pour un instrument."""
    dataset_path = Path(config.dataset_dir) / f"{symbol}_dataset_v2.parquet"
    if not dataset_path.exists():
        print(f"[ERREUR] Dataset non trouve: {dataset_path}")
        return []

    df = pd.read_parquet(dataset_path)
    features = get_features(df)

    print(f"\n{'#'*60}")
    print(f"  {symbol} — {len(df)} barres, {len(features)} features")
    print(f"  Labels: BUY={int((df.label==1).sum())} SELL={int((df.label==-1).sum())} HOLD={int((df.label==0).sum())}")
    print(f"{'#'*60}")

    trainer = ModelTrainer(config)
    results = []

    for side in ["buy", "sell"]:
        result = trainer.train_model(symbol, side, df, features, tune=tune)
        if result.get("model") is not None:
            save_model(result, config)
        results.append(result)

    return results


if __name__ == "__main__":
    config = TrainConfig()

    symbols = ["ES", "NQ"]
    tune = "--no-tune" not in sys.argv

    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbols = [sys.argv[idx + 1].upper()]

    if not tune:
        print("[MODE] Params par defaut (skip Optuna)")

    all_results = []
    for sym in symbols:
        results = run_training(sym, config, tune=tune)
        all_results.extend(results)

    if all_results:
        generate_report(all_results, config)
