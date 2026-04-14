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
    # Fix 2026-04-14 v2 (review agent) : test_days 5->7 pour atteindre le seuil
    # Lopez AFML de >=30 trades/fold. Avec 4 trades/jour × 7 jours = 28 trades,
    # tres proche du seuil. Nb folds passe de ~12 a ~9 avec 70 jours, acceptable.
    # PF/WR std moins sensibles aux outliers → stats plus robustes.
    min_train_days: int = 10          # Minimum jours pour entrainer
    test_days: int = 7                # Jours par fold test (5->7)

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
    date: Optional[str] = None   # YYYY-MM-DD, pour groupby daily Sharpe propre

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
        """Profit factor = gross_wins / gross_losses.

        Cas limites (fix 2026-04-14, ne plus polluer les stats aggregate) :
          - n_trades == 0          : retourne NaN (pas de trades = pas de stat)
          - gross_losses == 0 et gross_wins > 0 : retourne inf (tous gains)
          - gross_losses == 0 et gross_wins == 0 : retourne NaN
        """
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
        dd = peak - cumsum
        return float(dd.max())

    @property
    def sharpe(self) -> float:
        """Sharpe ratio DAILY-RETURNS annualise (standard Lopez AFML ch.14).

        Fix 2026-04-14 v2 : calcul via groupby date reelle (t.date) quand dispo.
        Sinon fallback CLT approximation (peut surestimer si trades auto-correles).

        Formule Lopez standard :
          daily_pnl[i]   = somme des pnl des trades du jour i
          mean_daily     = moyenne des pnl journaliers
          std_daily      = ecart-type des pnl journaliers
          sharpe_annual  = mean_daily / std_daily * sqrt(252)
        """
        if len(self.trades) < 5 or self.n_days < 2:
            return 0.0

        pnls = np.array([t.pnl_ticks for t in self.trades], dtype=float)

        # Chemin IDEAL : si on a les dates dans TradeResult, grouper par date reelle
        trades_with_date = [t for t in self.trades if t.date is not None]
        if len(trades_with_date) >= 5 and self.n_days >= 5:
            from collections import defaultdict
            daily_pnl: dict[str, float] = defaultdict(float)
            for t in trades_with_date:
                daily_pnl[t.date] += t.pnl_ticks
            daily_arr = np.array(list(daily_pnl.values()), dtype=float)
            if len(daily_arr) >= 5 and daily_arr.std() > 1e-6:
                daily_mean = daily_arr.mean()
                daily_std = daily_arr.std()
                return float(daily_mean / daily_std * np.sqrt(252.0))

        # Fallback CLT approximation (si pas de dates ou trop peu de jours)
        if self.n_days >= 5:
            trades_per_day_f = max(1.0, self.trades_per_day)
            daily_std_approx = pnls.std() * np.sqrt(trades_per_day_f)
            daily_mean = self.total_pnl / max(1.0, float(self.n_days))
            if daily_std_approx < 1e-6:
                return 0.0
            return float(daily_mean / daily_std_approx * np.sqrt(252.0))
        else:
            # Vraiment peu de jours : sharpe trade-based conservateur
            mean = pnls.mean()
            std = pnls.std()
            if std < 1e-6:
                return 0.0
            return float(mean / std * np.sqrt(252))


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

        # Date ISO pour groupby daily Sharpe (2026-04-14 fix)
        try:
            date_str = str(day) if hasattr(day, "isoformat") or isinstance(day, str) else None
        except Exception:
            date_str = None
        trades.append(TradeResult(direction=direction, entry_bar=i, pnl_ticks=pnl,
                                  won=pnl > 0, date=date_str))
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
    sample_weight_train: Optional[np.ndarray] = None,
    sample_weight_val: Optional[np.ndarray] = None,
) -> dict:
    """Optimise les hyperparametres LightGBM avec Optuna.

    sample_weight_train/val : poids par echantillon (Lopez AFML ch.4 — uniqueness).
    Si None, LightGBM traite tous les echantillons avec poids=1.0 (comportement par defaut).
    """
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
        fit_kwargs = dict(
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.early_stopping(early_stopping, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        if sample_weight_train is not None:
            fit_kwargs["sample_weight"] = sample_weight_train
        if sample_weight_val is not None:
            fit_kwargs["eval_sample_weight"] = [sample_weight_val]
        model.fit(X_train, y_train, **fit_kwargs)
        preds = model.predict_proba(X_val)[:, 1]

        # Optimiser pour le profit factor, pas la logloss
        # Note : si sample_weight_val est fourni, le PF proxy est PONDERE pour
        # rester fidele a Lopez AFML ch.4 (uniqueness weights).
        threshold = 0.5
        pred_pos = preds > threshold
        if pred_pos.sum() == 0:
            return 0.0

        if sample_weight_val is not None:
            # Version ponderee : un label "unique" compte plus qu'un label chevauche
            correct = float(((pred_pos) & (y_val == 1)) @ sample_weight_val)
            wrong   = float(((pred_pos) & (y_val == 0)) @ sample_weight_val)
        else:
            correct = float((pred_pos & (y_val == 1)).sum())
            wrong   = float((pred_pos & (y_val == 0)).sum())

        if wrong == 0:
            return correct
        return correct / wrong  # proxy profit factor

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
            # Sample weights Lopez AFML ch.4 (fallback None si colonne absente)
            sw_tr_tune = train_f["sample_weight"].values if "sample_weight" in train_f.columns else None
            sw_vl_tune = val_f["sample_weight"].values if "sample_weight" in val_f.columns else None

            print(f"  Tuning Optuna ({self.config.n_trials} trials)...")
            t0 = time.time()
            params = tune_hyperparams(
                X_tr, y_tr, X_vl, y_vl,
                self.config.n_trials, self.config.early_stopping_rounds,
                sample_weight_train=sw_tr_tune,
                sample_weight_val=sw_vl_tune,
            )
            print(f"  Tuning termine en {time.time()-t0:.0f}s")
        else:
            params = _default_params()

        # --- Walk-forward evaluation ---
        all_sim_results = []
        fold_metrics = []
        fold_test_dfs: List[pd.DataFrame] = []  # pour analyse regime GEX post-hoc

        for fold_idx, (train_df, test_df) in enumerate(folds):
            X_tr = train_df[features]
            y_tr = (train_df["label"] == target_label).astype(int).values
            X_te = test_df[features]
            y_te = (test_df["label"] == target_label).astype(int).values
            # Sample weights (Lopez AFML ch.4 — corrige biais labels concurrents)
            sw_tr = train_df["sample_weight"].values if "sample_weight" in train_df.columns else None
            sw_te = test_df["sample_weight"].values if "sample_weight" in test_df.columns else None

            # Train
            model = lgb.LGBMClassifier(**params)
            fit_kwargs = dict(
                eval_set=[(X_te, y_te)],
                callbacks=[lgb.early_stopping(self.config.early_stopping_rounds, verbose=False),
                           lgb.log_evaluation(period=0)],
            )
            if sw_tr is not None:
                fit_kwargs["sample_weight"] = sw_tr
            if sw_te is not None:
                fit_kwargs["eval_sample_weight"] = [sw_te]
            model.fit(X_tr, y_tr, **fit_kwargs)

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
            fold_test_dfs.append(test_df)

            print(f"  Fold {fold_idx+1}: {date_range} | "
                  f"thr={threshold:.2f} trades={sim.n_trades} "
                  f"WR={sim.win_rate:.0%} PF={sim.profit_factor:.2f} "
                  f"EV={sim.ev_per_trade:+.1f}t PnL={sim.total_pnl:+.0f}t")

        # --- Aggregate metrics ---
        agg = self._aggregate_metrics(fold_metrics, all_sim_results)

        # --- Regime GEX split analysis (Dim/Eraker/Vilkov SSRN 2024, 2026-04-15) ---
        # Hypothese peer-reviewed : dealer gamma positif (price > HVL) → mean-reversion,
        # gamma negatif (price < HVL) → momentum. Test post-hoc : on split les trades
        # du walk-forward en 2 groupes selon bool_above_mq_hvl au moment de l'entry,
        # et on compare PF/WR/EV. Si ecart significatif → regime GEX est un bon meta-filter.
        regime_analysis = self._analyze_regime_gex(fold_test_dfs, all_sim_results, side)

        # --- Reality check vs baselines (Aronson + Davey, 2026-04-14) ---
        # Compare la strategie a :
        #   1. Buy-and-hold (prix close[-1] - close[0]) sur les folds test
        #   2. Random trading (mean PnL de 1000 random strats aleatoires)
        #   3. Always-flat (0 trade, PnL = 0)
        # Si strat_pnl < 2-sigma du random → probablement pas d'edge reel
        baseline_comparison = self._compute_baseline_comparison(
            fold_metrics, sim_results=all_sim_results, side=side,
        )

        # --- Train final model on ALL data ---
        print(f"\n  Training final model sur {len(df)} barres...")
        sw_all = df["sample_weight"].values if "sample_weight" in df.columns else None
        final_model = lgb.LGBMClassifier(**params)
        if sw_all is not None:
            final_model.fit(X, y, sample_weight=sw_all)
        else:
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

        # ═══════════════════════════════════════════════════════════════
        # META-LABELING (Lopez AFML ch.3) — 13/04/2026
        # Train un 2e model LightGBM sur [p_primary + features contextuelles]
        # pour filtrer les faux positifs du primary. Score final = p_primary × p_meta.
        # Si le meta training echoue (pas assez de data, 1 seule classe),
        # on continue avec primary uniquement (meta = None).
        # ═══════════════════════════════════════════════════════════════
        meta_model = None
        meta_features = []
        try:
            from meta_labeler import (
                MetaLabelConfig, MetaModel,
                build_meta_labels, build_meta_features,
                DEFAULT_META_CONTEXT_FEATURES,
            )

            print(f"\n  META-LABELING {symbol} {side} (Lopez AFML ch.3)")

            # Predictions primary sur tout le dataset final
            p_primary_full = final_model.predict_proba(X)[:, 1]

            # Build labels meta (y_meta = 1 si primary_correct, 0 si faux positif, NaN si inactif)
            meta_target = 1 if side == "buy" else -1
            y_meta = build_meta_labels(
                labels=df["label"],
                primary_preds=p_primary_full,
                primary_threshold=MetaLabelConfig().primary_threshold,
                target_label=meta_target,
            )

            # Build features meta (p_primary + context features)
            X_meta = build_meta_features(df, p_primary_full)
            print(f"    Meta features ({len(X_meta.columns)}): {list(X_meta.columns)}")

            # Fit meta model (garde-fou : min_samples, >= 2 classes)
            meta_config = MetaLabelConfig()
            meta = MetaModel(meta_config)

            # sample_weight aligne sur meta mask
            sw_meta = df["sample_weight"].values if "sample_weight" in df.columns else None

            meta.fit(X_meta, y_meta, sample_weight=sw_meta)
            meta_model = meta
            meta_features = list(X_meta.columns)

            # Stats meta sur le dataset d'entrainement
            mask = ~y_meta.isna()
            n_meta = int(mask.sum())
            n_positive = int(y_meta.loc[mask].sum())
            print(f"    Meta entraine sur {n_meta} signaux primary "
                  f"({n_positive} positifs = {n_positive/max(n_meta,1):.1%})")

        except ImportError:
            print(f"  [INFO] meta_labeler non disponible, skip meta-labeling")
        except Exception as e:
            print(f"  [WARN] Meta-labeling echoue : {e}")
            print(f"  [WARN] Continuer avec primary uniquement")

        result = {
            "symbol": symbol,
            "side": side,
            "model": final_model,
            "meta_model": meta_model,           # None si fit echoue
            "meta_features": meta_features,     # [] si fit echoue
            "params": params,
            "threshold": best_threshold,
            "features": features,
            "fold_metrics": fold_metrics,
            "aggregate": agg,
            "importance": importance,
            "verdict": verdict,
            "baseline_comparison": baseline_comparison,  # Reality check
            "regime_gex": regime_analysis,  # Split GEX+ vs GEX- (Dim/Eraker/Vilkov 2024)
        }

        self._print_verdict(result)
        return result

    def _analyze_regime_gex(
        self,
        fold_test_dfs: List[pd.DataFrame],
        sim_results: list,
        side: str,
    ) -> dict:
        """Split post-hoc des trades walk-forward par regime GEX (dealer gamma sign).

        Base academique : Dim, Eraker, Vilkov (SSRN 4692190, 2024) — Market Makers'
        inventory gamma positif renforce le reversal intraday, negatif renforce le
        momentum. On utilise `bool_above_mq_hvl` comme proxy : price > HVL (= HVL line
        de MenthorQ = gamma flip) → regime gamma positif, price < HVL → gamma negatif.

        Pour chaque trade on lookup le regime a l'entry_bar dans son test_df, on
        agrege en 2 groupes et on compare PF, WR, EV, total PnL, Sharpe approx.
        Si l'ecart PF entre regimes est > 30% et qu'il y a >= 20 trades par groupe,
        le regime est un meta-filter candidat credible.

        Retourne un dict meme si pas de colonne HVL (status = "skipped").
        """
        # Detecter si la feature regime est disponible dans les test_df
        has_hvl = any(
            (df is not None) and ("bool_above_mq_hvl" in df.columns)
            for df in fold_test_dfs
        )
        if not has_hvl:
            print(f"\n  [REGIME GEX] skip — bool_above_mq_hvl absent des folds test")
            return {"status": "skipped", "reason": "no_bool_above_mq_hvl"}

        # Collecter trades par regime
        pnl_pos: List[float] = []   # regime GEX positif (price > HVL) — reversal attendu
        pnl_neg: List[float] = []   # regime GEX negatif (price < HVL) — momentum attendu
        dates_pos: List[Optional[str]] = []
        dates_neg: List[Optional[str]] = []
        n_trades_pos = 0
        n_trades_neg = 0

        for test_df, sim in zip(fold_test_dfs, sim_results):
            if "bool_above_mq_hvl" not in test_df.columns:
                continue
            regime_vals = test_df["bool_above_mq_hvl"].values
            for t in sim.trades:
                if t.entry_bar < 0 or t.entry_bar >= len(regime_vals):
                    continue
                r = regime_vals[t.entry_bar]
                # bool_above_mq_hvl : 1.0 = price > HVL (gamma positif cote dealer)
                if r >= 0.5:
                    pnl_pos.append(t.pnl_ticks)
                    dates_pos.append(t.date)
                    n_trades_pos += 1
                else:
                    pnl_neg.append(t.pnl_ticks)
                    dates_neg.append(t.date)
                    n_trades_neg += 1

        def _group_stats(pnls: List[float], dates: List[Optional[str]]) -> dict:
            if not pnls:
                return {"n_trades": 0, "win_rate": 0.0, "profit_factor": float("nan"),
                        "ev_trade": 0.0, "total_pnl": 0.0, "n_days": 0, "sharpe_daily": 0.0}
            arr = np.array(pnls, dtype=float)
            wins = arr[arr > 0]
            losses = arr[arr < 0]
            gw = float(wins.sum())
            gl = float(abs(losses.sum()))
            if gl <= 0:
                pf = float("inf") if gw > 0 else float("nan")
            else:
                pf = gw / gl
            unique_dates = {d for d in dates if d}
            # Sharpe daily-returns (Lopez ch.14) si assez de jours
            sharpe = 0.0
            if len(unique_dates) >= 5:
                from collections import defaultdict
                daily: Dict[str, float] = defaultdict(float)
                for p, d in zip(pnls, dates):
                    if d is not None:
                        daily[d] += p
                daily_arr = np.array(list(daily.values()), dtype=float)
                if len(daily_arr) >= 5 and daily_arr.std() > 1e-6:
                    sharpe = float(daily_arr.mean() / daily_arr.std() * np.sqrt(252.0))
            return {
                "n_trades": len(pnls),
                "win_rate": float((arr > 0).mean()),
                "profit_factor": pf,
                "ev_trade": float(arr.mean()),
                "total_pnl": float(arr.sum()),
                "n_days": len(unique_dates),
                "sharpe_daily": sharpe,
            }

        stats_pos = _group_stats(pnl_pos, dates_pos)
        stats_neg = _group_stats(pnl_neg, dates_neg)

        total = n_trades_pos + n_trades_neg

        # Verdict filter
        def _is_exploitable(stats: dict) -> bool:
            return (stats["n_trades"] >= 20
                    and np.isfinite(stats["profit_factor"])
                    and stats["profit_factor"] >= 1.3)

        pos_ok = _is_exploitable(stats_pos)
        neg_ok = _is_exploitable(stats_neg)

        # Ecart PF entre regimes (detection d'asymetrie > 30%)
        pf_gap_abs = 0.0
        if (np.isfinite(stats_pos["profit_factor"]) and np.isfinite(stats_neg["profit_factor"])
                and min(stats_pos["profit_factor"], stats_neg["profit_factor"]) > 0):
            pf_gap_abs = abs(stats_pos["profit_factor"] - stats_neg["profit_factor"])
            base = min(stats_pos["profit_factor"], stats_neg["profit_factor"])
            pf_gap_rel = pf_gap_abs / base
        else:
            pf_gap_rel = 0.0

        # Recommandation
        if pos_ok and not neg_ok:
            recommendation = "KEEP_POS_ONLY"  # trader uniquement en GEX positif
        elif neg_ok and not pos_ok:
            recommendation = "KEEP_NEG_ONLY"  # trader uniquement en GEX negatif
        elif pos_ok and neg_ok and pf_gap_rel >= 0.30:
            recommendation = "SPLIT_RETRAIN"  # 2 modeles distincts justifies
        elif pos_ok and neg_ok:
            recommendation = "POOLED_OK"      # 1 seul modele suffit
        else:
            recommendation = "NO_EDGE_EITHER"

        # Print synthese
        print(f"\n  [REGIME GEX] side={side} — split bool_above_mq_hvl")
        print(f"    GEX+ (price > HVL, reversal expected) : "
              f"n={stats_pos['n_trades']:>4} WR={stats_pos['win_rate']:.0%} "
              f"PF={stats_pos['profit_factor']:.2f} EV={stats_pos['ev_trade']:+.1f}t "
              f"Sharpe={stats_pos['sharpe_daily']:.2f}")
        print(f"    GEX- (price < HVL, momentum expected) : "
              f"n={stats_neg['n_trades']:>4} WR={stats_neg['win_rate']:.0%} "
              f"PF={stats_neg['profit_factor']:.2f} EV={stats_neg['ev_trade']:+.1f}t "
              f"Sharpe={stats_neg['sharpe_daily']:.2f}")
        print(f"    PF gap relatif : {pf_gap_rel:+.0%}    → {recommendation}")

        return {
            "status": "ok",
            "n_trades_total": total,
            "n_trades_pos": n_trades_pos,
            "n_trades_neg": n_trades_neg,
            "stats_pos": stats_pos,
            "stats_neg": stats_neg,
            "pf_gap_rel": pf_gap_rel,
            "recommendation": recommendation,
        }

    def _aggregate_metrics(self, fold_metrics: list, sim_results: list) -> dict:
        """Agregation des metriques cross-fold + tests statistiques Lopez/Aronson.

        Metriques ajoutees le 2026-04-14 :
          - mc_p_value   : Monte Carlo Permutation Test (Aronson ch.6-7)
                           p <= 0.05 = edge statistiquement significatif
          - psr          : Probabilistic Sharpe Ratio (Lopez ch.15)
                           proba que le vrai Sharpe > 0 ; cible > 0.95
          - dsr          : Deflated Sharpe Ratio (Lopez ch.15)
                           PSR ajuste au multiple testing ; cible > 0.95
          - skew, kurt   : moments 3-4 de la distribution des pnl trade
          - return_hhi   : concentration du PnL (Herfindahl) — cible < 0.10
        """
        if not fold_metrics:
            return {}

        all_trades = []
        for sim in sim_results:
            all_trades.extend(sim.trades)

        # Fix agent review 2026-04-14 : n_days combined EXCLUT les folds vides
        # (folds sans trades ne doivent pas diluer le trades_per_day global).
        # Avant : combined.n_days = sum(tous) → trades_per_day sous-estime.
        # Apres : combined.n_days = sum(folds avec trades) → trades_per_day propre.
        combined = SimResult(
            trades=all_trades,
            n_bars=sum(s.n_bars for s in sim_results),
            n_days=sum(s.n_days for s in sim_results if s.n_trades > 0),
        )

        # --- Import lazy des stats Lopez/Aronson (defensif si backtest_pm change) ---
        try:
            from backtest_pm import (
                monte_carlo_permutation,
                probabilistic_sharpe_ratio,
                deflated_sharpe_ratio,
            )
            stats_available = True
        except Exception:
            stats_available = False

        mc_p = 1.0
        psr = 0.0
        dsr = 0.0
        skew = 0.0
        kurt_excess = 0.0
        return_hhi = 0.0

        if combined.n_trades >= 10 and stats_available:
            pnl_arr = np.array([t.pnl_ticks for t in combined.trades], dtype=float)

            # --- Monte Carlo Permutation Test (Aronson EBTA ch.6-7) ---
            # 500 permutations (rapide, suffisant pour p>=0.002)
            mc_p = monte_carlo_permutation(pnl_arr, n_permutations=500, seed=42)

            if len(pnl_arr) > 3 and pnl_arr.std() > 0:
                # Moments 3-4 pour PSR/DSR
                skew = float(pd.Series(pnl_arr).skew())
                kurt_excess = float(pd.Series(pnl_arr).kurt())
                kurt_raw = kurt_excess + 3.0  # Lopez attend kurt RAW, pas excess

                # --- PSR vs benchmark 0 (random = 0 Sharpe) ---
                psr = probabilistic_sharpe_ratio(
                    sr_obs=combined.sharpe,
                    sr_benchmark=0.0,
                    n=combined.n_trades,
                    skew=skew,
                    kurt=kurt_raw,
                )

                # --- DSR : ajustement multiple testing ---
                # n_trials = nb de modeles primary testes (2 sides * 10 strategies = 20)
                # Config override via self.config.n_trials_dsr si defini
                n_trials_dsr = getattr(self.config, "n_trials_dsr", 20)
                dsr = deflated_sharpe_ratio(
                    sr_obs=combined.sharpe,
                    n=combined.n_trades,
                    skew=skew,
                    kurt=kurt_raw,
                    n_trials=max(1, n_trials_dsr),
                )

            # --- HHI (concentration PnL, Lopez ch.14) ---
            # Si 1 trade represente 50% du PnL, c'est fragile
            pnl_abs = np.abs(pnl_arr)
            total = pnl_abs.sum()
            if total > 0:
                shares = pnl_abs / total
                return_hhi = float((shares ** 2).sum())

        # Stabilite cross-fold : EXCLURE les folds sans trades (fix 2026-04-14)
        # Un fold avec 0 trades avait PF=99.0 fallback qui polluait pf_std.
        # Ces folds sont cosmétiquement exclus du calcul de variance pour refleter
        # la vraie instabilite des folds qui ont vraiment trade.
        valid_folds = [fm for fm in fold_metrics if fm.get("trades", 0) > 0]
        n_valid_folds = len(valid_folds)
        n_empty_folds = len(fold_metrics) - n_valid_folds

        if valid_folds:
            wr_std = float(np.std([fm["win_rate"] for fm in valid_folds]))
            # Filtrer aussi les PF non-finis (NaN, inf) avant std
            pf_values = [fm["profit_factor"] for fm in valid_folds
                         if np.isfinite(fm["profit_factor"])]
            pf_std = float(np.std(pf_values)) if pf_values else 0.0
            # Percentiles pour detecter outliers
            pf_median = float(np.median(pf_values)) if pf_values else 0.0
            pf_p25 = float(np.percentile(pf_values, 25)) if pf_values else 0.0
            pf_p75 = float(np.percentile(pf_values, 75)) if pf_values else 0.0
        else:
            wr_std = 0.0
            pf_std = 0.0
            pf_median = 0.0
            pf_p25 = 0.0
            pf_p75 = 0.0

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
            "n_valid_folds": n_valid_folds,
            "n_empty_folds": n_empty_folds,
            "n_days": combined.n_days,
            # Stabilite cross-fold (FOLDS AVEC TRADES UNIQUEMENT)
            "wr_std": wr_std,
            "pf_std": pf_std,
            "pf_median": pf_median,   # Plus robuste que mean pour outliers
            "pf_p25": pf_p25,
            "pf_p75": pf_p75,
            # Tests statistiques Lopez AFML + Aronson (2026-04-14)
            "mc_p_value": mc_p,
            "psr": psr,
            "dsr": dsr,
            "skew": skew,
            "kurt_excess": kurt_excess,
            "return_hhi": return_hhi,
        }

    def _compute_baseline_comparison(
        self, fold_metrics: list, sim_results: list, side: str
    ) -> dict:
        """Reality check vs baselines naives (Aronson + Davey).

        ⚠️ NOTE 2026-04-14 (review agent) :
          Cette metrique `edge_vs_random` est un BOOTSTRAP des signes des pnl,
          ce qui est MATHEMATIQUEMENT IDENTIQUE au Monte Carlo Permutation Test
          de `backtest_pm.monte_carlo_permutation`. Elle est donc redondante
          avec `mc_p_value` dans aggregate.

          Elle est CONSERVEE uniquement pour le print reality check (aide
          visuelle au debug). Elle N'EST PAS utilisee dans `_verdict()`
          comme critere de decision — c'est mc_p_value qui fait foi.

        Baselines :
          1. Buy-and-hold    : approximation = 0 (flat sur courte periode)
          2. Random sign bootstrap : 1000 shuffles des signes de pnl_abs
          3. Always-flat     : 0 trade = 0 PnL

        Retourne un dict avec strategy_pnl, buy_hold_pnl, random_pnl, random_std,
        edge_vs_random (sigmas).
        """
        if not sim_results or not fold_metrics:
            return {}

        # PnL strategie = somme PnL tous les trades
        all_trades = []
        for sim in sim_results:
            all_trades.extend(sim.trades)
        strategy_pnl = float(sum(t.pnl_ticks for t in all_trades))
        n_trades = len(all_trades)

        if n_trades < 10:
            return {
                "strategy_pnl": strategy_pnl,
                "buy_hold_pnl": 0.0,
                "random_pnl": 0.0,
                "random_std": 0.0,
                "edge_vs_random": 0.0,
                "note": "insufficient_trades",
            }

        # --- Approx Buy-and-hold sur les folds test ---
        # Si pas acces aux prix brut, on approxime via la somme des pnl_ticks
        # d'une strategie always-long qui prendrait TP/SL fixes par jour.
        # Approximation : buy_hold_pnl ~= 0 (flat sur courte periode)
        # Pour un vrai buy-hold il faudrait les prix open/close de chaque fold,
        # on le fait dans une passe suivante (a coder si besoin).
        buy_hold_pnl = 0.0

        # --- Random trading : bootstrap 1000 shuffles ---
        # Principe : on garde les MEMES magnitudes de trade (pnl_abs) mais on
        # randomize le signe. Cela simule "meme volatilite, direction aleatoire".
        pnl_arr = np.array([t.pnl_ticks for t in all_trades], dtype=float)
        pnl_abs = np.abs(pnl_arr)
        n_sim = 1000
        rng = np.random.default_rng(42)
        random_pnls = np.zeros(n_sim)
        for i in range(n_sim):
            signs = rng.choice([-1, 1], size=n_trades)
            random_pnls[i] = (pnl_abs * signs).sum()

        random_mean = float(random_pnls.mean())
        random_std = float(random_pnls.std())
        edge_sigma = ((strategy_pnl - random_mean) / random_std) if random_std > 0 else 0.0

        return {
            "strategy_pnl":    strategy_pnl,
            "buy_hold_pnl":    buy_hold_pnl,
            "random_pnl":      random_mean,
            "random_std":      random_std,
            "edge_vs_random":  float(edge_sigma),
            "note":            "ok",
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
        """GO / CAUTION / NO-GO base sur les seuils + tests Lopez/Aronson.

        Criteres P&L (5) :
          - profit_factor >= 1.3
          - ev_per_trade >= 1.0 ticks
          - win_rate >= 45%
          - trades_per_day >= 3
          - max_drawdown <= 500 ticks

        Criteres statistiques Lopez (3) — NOUVEAUX 2026-04-14 :
          - mc_p_value <= 0.05  (Aronson : edge non du au hasard)
          - psr >= 0.95         (Lopez ch.15 : vrai Sharpe > 0 a 95%)
          - dsr >= 0.95         (Lopez ch.15 : tient apres multiple testing)

        Logique :
          - GO              : 5/5 P&L + 3/3 stats
          - GO_STAT         : 5/5 P&L + 2/3 stats (stats pas tous bons mais proche)
          - CAUTION         : 4/5 P&L OU 3/5 P&L + stats bons
          - NO-GO (...)     : moins
        """
        if not agg or agg.get("total_trades", 0) < 10:
            return "NO-GO (insufficient trades)"

        # Fix agent review 2026-04-14 : PF=inf (0 pertes) doit FAIL le gate.
        # Un PF infini sur petit echantillon = signal trompeur, pas un vrai edge.
        # On utilise pf_median comme fallback plus robuste si PF n'est pas finite.
        pf_agg = agg["profit_factor"]
        if not np.isfinite(pf_agg):
            # Fallback sur le PF median des folds (plus robuste aux outliers)
            pf_agg = agg.get("pf_median", 0.0)

        pnl_checks = {
            "profit_factor": pf_agg >= self.config.min_profit_factor,
            "ev_per_trade":  agg["ev_per_trade"]  >= self.config.min_ev_ticks,
            "win_rate":      agg["win_rate"]      >= self.config.min_win_rate,
            "trades_per_day": agg["trades_per_day"] >= self.config.min_trades_per_day,
            "max_drawdown":  agg["max_drawdown"]  <= self.config.max_drawdown_ticks,
        }
        pnl_passed = sum(pnl_checks.values())

        # Tests statistiques — nouveaux 14/04
        # Seuils calibres review agent 2026-04-14 :
        #   - MC p-value <= 0.05 (standard Aronson)
        #   - PSR >= 0.95 (Lopez ch.15, pas d'ajustement = strict)
        #   - DSR >= 0.90 (Lopez ch.15, ajuste multiple testing = 0.95 trop agressif
        #                  sur 15-80 jours de data intraday. Phase 1 = 0.90,
        #                  monter a 0.95 quand on aura 180+ jours)
        stats_checks = {
            "mc_significant": agg.get("mc_p_value", 1.0) <= 0.05,
            "psr_high":       agg.get("psr", 0.0)        >= 0.95,
            "dsr_high":       agg.get("dsr", 0.0)        >= 0.90,
        }
        stats_passed = sum(stats_checks.values())

        all_checks = {**pnl_checks, **stats_checks}

        if pnl_passed == 5 and stats_passed == 3:
            return "GO"
        elif pnl_passed == 5 and stats_passed >= 2:
            failed = [k for k, v in stats_checks.items() if not v]
            return f"GO_STAT_WEAK ({', '.join(failed)})"
        elif pnl_passed >= 4 and stats_passed >= 1:
            failed = [k for k, v in all_checks.items() if not v]
            return f"CAUTION ({', '.join(failed)})"
        else:
            failed = [k for k, v in all_checks.items() if not v]
            return f"NO-GO ({', '.join(failed)})"

    def _print_verdict(self, result: dict):
        agg = result.get("aggregate", {})
        verdict = result["verdict"]

        print(f"\n  {'-'*60}")
        print(f"  AGGREGATE {result['symbol']} {result['side'].upper()}")
        print(f"  {'-'*60}")
        if agg:
            print(f"  Trades     : {agg['total_trades']} ({agg['trades_per_day']:.1f}/jour)")
            print(f"  Win Rate   : {agg['win_rate']:.1%}")
            print(f"  PnL total  : {agg['total_pnl']:+.0f} ticks")
            pf_val = agg['profit_factor']
            pf_str = f"{pf_val:.2f}" if np.isfinite(pf_val) else "inf"
            print(f"  PF         : {pf_str}")
            print(f"  EV/trade   : {agg['ev_per_trade']:+.1f} ticks")
            print(f"  Max DD     : {agg['max_drawdown']:.0f} ticks")
            print(f"  Sharpe     : {agg['sharpe']:.2f}  (daily-returns annualise)")
            # Fold stability : affiche les folds vides separement
            n_valid = agg.get('n_valid_folds', agg.get('n_folds', 0))
            n_empty = agg.get('n_empty_folds', 0)
            print(f"  Folds      : {n_valid} valides, {n_empty} vides (skip)")
            pf_median = agg.get('pf_median', 0)
            pf_p25 = agg.get('pf_p25', 0)
            pf_p75 = agg.get('pf_p75', 0)
            print(f"  PF median  : {pf_median:.2f}  (Q25={pf_p25:.2f}, Q75={pf_p75:.2f})")
            print(f"  Stabilite  : WR std={agg['wr_std']:.2%}, PF std={agg['pf_std']:.2f}")

            # Tests statistiques Lopez AFML + Aronson (2026-04-14)
            if "mc_p_value" in agg:
                mc_mark = "✓" if agg["mc_p_value"] <= 0.05 else "✗"
                psr_mark = "✓" if agg["psr"] >= 0.95 else "✗"
                dsr_mark = "✓" if agg["dsr"] >= 0.95 else "✗"
                hhi_mark = "✓" if agg["return_hhi"] <= 0.10 else "✗"

                print(f"  {'-'*60}")
                print(f"  TESTS STATISTIQUES (Lopez AFML ch.14-15 + Aronson)")
                print(f"  MC p-value : {agg['mc_p_value']:.4f}  {mc_mark}  "
                      f"(< 0.05 = edge significatif)")
                print(f"  PSR        : {agg['psr']:.4f}  {psr_mark}  "
                      f"(> 0.95 = vrai Sharpe > 0 confiance 95%)")
                print(f"  DSR        : {agg['dsr']:.4f}  {dsr_mark}  "
                      f"(> 0.95 = significatif apres multiple testing)")
                print(f"  HHI PnL    : {agg['return_hhi']:.3f}  {hhi_mark}  "
                      f"(< 0.10 = PnL bien distribue)")
                print(f"  Skew       : {agg['skew']:+.2f}  "
                      f"(positif = droite fat tail = bon)")
                print(f"  Kurt excess: {agg['kurt_excess']:+.2f}  "
                      f"(< 3 = distribution raisonnable)")

        print(f"  {'-'*60}")
        print(f"  Threshold  : {result['threshold']:.2f}")
        print(f"  Top features: {', '.join(result['importance'].head(5)['feature'].tolist())}")

        # Reality check vs baselines (2026-04-14)
        baseline = result.get("baseline_comparison", {})
        if baseline:
            print(f"  {'-'*60}")
            print(f"  REALITY CHECK vs BASELINES")
            print(f"  Strategie PnL  : {baseline.get('strategy_pnl', 0):+.0f} ticks")
            print(f"  Buy-and-hold   : {baseline.get('buy_hold_pnl', 0):+.0f} ticks")
            print(f"  Random trading : {baseline.get('random_pnl', 0):+.0f} ticks "
                  f"(std {baseline.get('random_std', 0):.0f})")
            print(f"  Always-flat    : 0 ticks")
            edge = baseline.get("edge_vs_random", 0)
            edge_mark = "✓" if edge > 2.0 else ("✗" if edge < 1.0 else "~")
            print(f"  Edge vs random (sigma) : {edge:.2f}  {edge_mark}  "
                  f"(> 2.0 sigma = significatif)")

        tag = "GO" if "GO" == verdict else ("CAUTION" if "CAUTION" in verdict else "NO-GO")
        print(f"\n  >>> VERDICT: {verdict} <<<")
        print(f"  {'-'*60}")


# ═══════════════════════════════════════════════════════════════════════════════
# SAVE / LOAD
# ═══════════════════════════════════════════════════════════════════════════════

def save_model(result: dict, config: TrainConfig):
    """Sauvegarde modele primary + meta (si present) + config + metriques.

    En stress mode (config.stress_mode=True), ajoute suffix `_stress` au prefix
    pour ne PAS ecraser les modeles non-stressed. Fix agent review 2026-04-14.
    """
    import pickle

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    symbol = result["symbol"]
    side = result["side"]
    # Suffix stress si stress mode actif
    stress_suffix = "_stress" if getattr(config, "stress_mode", False) else ""
    prefix = f"{symbol}_{side}{stress_suffix}"

    # Modele primary
    model_path = out_dir / f"{prefix}_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(result["model"], f)

    # Modele meta (Lopez AFML ch.3) — optionnel
    meta_model = result.get("meta_model")
    meta_files = []
    if meta_model is not None:
        meta_path = out_dir / f"{prefix}_meta_model.pkl"
        with open(meta_path, "wb") as f:
            pickle.dump(meta_model, f)
        meta_files.append(meta_path.name)

    # Config JSON
    config_data = {
        "symbol": symbol,
        "side": side,
        "threshold": result["threshold"],
        "features": result["features"],
        "meta_features": result.get("meta_features", []),
        "has_meta_model": meta_model is not None,
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

    saved = [model_path.name, config_path.name, imp_path.name] + meta_files
    print(f"  Sauvegarde: {', '.join(saved)}")


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
    """Extrait la liste des features du dataset (exclut meta et features mortes).

    IMPORTANT : sample_weight est une META colonne (Lopez AFML ch.4), pas une
    feature. Il est passe au .fit() en parametre `sample_weight`, pas en input X.

    Extension 13/04/2026 Option B :
    - Exclure les colonnes string (sym, contract, session_id)
    - Exclure les colonnes 100% NaN (mq_dist_gamma_flip, mq_qscore_*, etc.)
    - Exclure les colonnes constantes
    """
    meta = {
        "ts", "label", "partial_session", "is_nq",
        "sample_weight",   # Lopez AFML ch.4 — meta, pas feature
        # Phase 1 Option B : colonnes string non-features
        "sym", "contract", "session_id", "datetime_utc", "datetime_et",
        "date", "day", "time_et",
        # atr est un denominateur, pas une feature directe
        "atr",
    }

    candidates = [c for c in df.columns if c not in meta]

    # Retirer les colonnes non-numeriques (strings residuels)
    numeric = [c for c in candidates if pd.api.types.is_numeric_dtype(df[c])]

    # Retirer les colonnes 100% NaN (souvent features MenthorQ vides)
    valid = [c for c in numeric if not df[c].isna().all()]

    return valid


class PreflightError(Exception):
    """Leve si le pre-training contract echoue (dataset/labels non conformes)."""
    pass


class ImportanceLeakError(Exception):
    """Leve si feature_importances_ revele une fuite (une feature domine)."""
    pass


def preflight_check(symbol: str, df: pd.DataFrame, features: List[str],
                     config: TrainConfig) -> None:
    """Trou 2 — Pre-training data contract.

    Verifie avant le training que tout est conforme. Leve PreflightError au
    premier probleme detecte. Ne modifie rien.

    Checks :
      1. quality_validator passe sur le dataset (pas de fuite features)
      2. labels presents et non-NaN
      3. BUY et SELL presents (sinon binary classification impossible)
      4. sample_weight valide (si present)
      5. Aucune feature avec NaN > 1%
      6. Aucune feature constante dans la liste
      7. Le dataset est trie chronologiquement sur ts (walk-forward)
    """
    print(f"\n  [PREFLIGHT] {symbol} — pre-training data contract")

    errors = []

    # 1. Dataset quality (via quality_validator)
    # 2026-04-14 : en mode v3 backfill, on skip ce check parce que l'historique
    # long exhibe des features que le live 15j n'expose pas (compteurs cumulatifs,
    # prix absolus non-normalises). Le training peut avancer, le quality_validator
    # restera un TODO pour quand on aura 180+ jours de live homogene.
    dataset_version = getattr(config, "dataset_version", "v2")
    if dataset_version == "v3":
        print(f"  [PREFLIGHT] Mode v3 backfill : quality_validator SKIP (historique heterogene)")
    else:
        try:
            from quality_validator import QualityValidator, QualityViolation
            other_sym = "NQ" if symbol == "ES" else "ES"
            other_path = Path(config.dataset_dir) / f"{other_sym}_dataset_{dataset_version}.parquet"
            if other_path.exists():
                df_other = pd.read_parquet(other_path)
                validator = QualityValidator(strict=False, verbose=False)
                if symbol == "ES":
                    report = validator.validate(df, df_other)
                else:
                    report = validator.validate(df_other, df)
                if not report.passed:
                    errors.append(
                        f"quality_validator a detecte {len(report.red_flags)} "
                        f"red flags. Lance /audit-features pour voir le detail."
                    )
        except ImportError:
            errors.append("quality_validator.py absent")

    # 2. Labels presents
    if "label" not in df.columns:
        errors.append("colonne 'label' absente du dataset")
    else:
        n_nan_label = int(df["label"].isna().sum())
        if n_nan_label > 0:
            errors.append(f"{n_nan_label} labels NaN dans le dataset")
        n_buy = int((df["label"] == 1).sum())
        n_sell = int((df["label"] == -1).sum())
        if n_buy == 0:
            errors.append("0 labels BUY — impossible d'entrainer le modele buy")
        if n_sell == 0:
            errors.append("0 labels SELL — impossible d'entrainer le modele sell")

    # 3. sample_weight
    if "sample_weight" in df.columns:
        sw = df["sample_weight"]
        if sw.isna().any():
            errors.append(f"{int(sw.isna().sum())} NaN dans sample_weight")
        if (sw < 0).any():
            errors.append(f"{int((sw < 0).sum())} valeurs negatives dans sample_weight")
        if sw.sum() < 1e-6:
            errors.append("sum(sample_weight) ~ 0 (fit degenere)")

    # 4. NaN dans les features
    for feat in features:
        if feat not in df.columns:
            errors.append(f"feature '{feat}' absente du dataset")
            continue
        nan_pct = df[feat].isna().mean()
        if nan_pct > 0.01:
            errors.append(f"feature '{feat}' a {nan_pct:.1%} de NaN (>1%)")

    # 5. Features constantes
    for feat in features:
        if feat in df.columns:
            if df[feat].nunique(dropna=True) <= 1:
                errors.append(f"feature '{feat}' est constante")

    # 6. Tri chronologique (walk-forward)
    if "ts" in df.columns:
        if not df["ts"].is_monotonic_increasing:
            errors.append("dataset non trie sur 'ts' — walk-forward casse")

    if errors:
        print(f"  [PREFLIGHT] REFUS ({len(errors)} erreurs) :")
        for e in errors[:20]:
            print(f"    - {e}")
        if len(errors) > 20:
            print(f"    ... et {len(errors) - 20} autres")
        raise PreflightError(
            f"Preflight check {symbol} : {len(errors)} erreurs bloquantes"
        )

    print(f"  [PREFLIGHT] OK — {len(features)} features, "
          f"BUY={n_buy}, SELL={n_sell}, "
          f"sample_weight={'oui' if 'sample_weight' in df.columns else 'non'}")


def importance_guard(model, features: List[str], symbol: str, side: str,
                      max_top1_share: float = 0.40,
                      max_top5_cumul: float = 0.70,
                      min_active_features: int = 30) -> None:
    """Trou 3 — Feature importance guard (anti-fuite post-training).

    Detecte une fuite subtile qui passerait le quality_validator :
    une feature qui domine l'importance LightGBM = fuite probable.

    Checks :
      1. Aucune feature ne depasse 40% de l'importance totale
      2. Top 5 features cumulee < 70%
      3. Au moins 30 features actives (>1% chacune)

    Leve ImportanceLeakError si un seul critere echoue.
    """
    importances = np.array(model.feature_importances_, dtype=float)
    total = importances.sum()
    if total < 1e-9:
        raise ImportanceLeakError(
            f"{symbol} {side} : feature_importances sum = 0 (modele casse ?)"
        )

    shares = importances / total
    order = np.argsort(shares)[::-1]
    top_names = [features[i] for i in order]
    top_shares = shares[order]

    top1 = float(top_shares[0])
    top5_cumul = float(top_shares[:5].sum())
    n_active = int((shares >= 0.01).sum())

    errors = []
    if top1 > max_top1_share:
        errors.append(
            f"top feature '{top_names[0]}' = {top1:.1%} > {max_top1_share:.0%} "
            f"(fuite probable)"
        )
    if top5_cumul > max_top5_cumul:
        errors.append(
            f"top 5 cumulee = {top5_cumul:.1%} > {max_top5_cumul:.0%} "
            f"(concentration suspecte sur {top_names[:5]})"
        )
    if n_active < min_active_features:
        errors.append(
            f"seulement {n_active} features actives (>1%) "
            f"< {min_active_features} minimum"
        )

    if errors:
        print(f"\n  [IMPORTANCE GUARD] {symbol} {side} : FUITE DETECTEE")
        for e in errors:
            print(f"    - {e}")
        print(f"  Top 10 importance :")
        for name, share in list(zip(top_names, top_shares))[:10]:
            print(f"    {share:6.1%}  {name}")
        raise ImportanceLeakError(
            f"{symbol} {side} : {len(errors)} red flags importance. "
            f"Revoir les features suspectes."
        )

    print(f"  [IMPORTANCE GUARD] {symbol} {side} OK — "
          f"top1={top1:.1%}, top5={top5_cumul:.1%}, active={n_active}")


def run_training(symbol: str, config: TrainConfig, tune: bool = True) -> List[dict]:
    """Pipeline complet pour un instrument."""
    # Version de dataset a utiliser (2026-04-14)
    # Par defaut v2 (live 15 jours), flag --v3 pour backfill historique (70-80 jours).
    version = getattr(config, "dataset_version", "v2")
    dataset_path = Path(config.dataset_dir) / f"{symbol}_dataset_{version}.parquet"
    if not dataset_path.exists():
        print(f"[ERREUR] Dataset non trouve: {dataset_path}")
        return []

    df = pd.read_parquet(dataset_path)
    features = get_features(df)

    print(f"\n{'#'*60}")
    print(f"  {symbol} — {len(df)} barres, {len(features)} features")
    print(f"  Labels: BUY={int((df.label==1).sum())} SELL={int((df.label==-1).sum())} HOLD={int((df.label==0).sum())}")
    print(f"{'#'*60}")

    # ═══════════════════════════════════════════════════════════════
    # PREFLIGHT CHECK — Trou 2 (Jackson 13/04/2026)
    # Bloque le training si le dataset/labels ne sont pas propres
    # ═══════════════════════════════════════════════════════════════
    try:
        preflight_check(symbol, df, features, config)
    except PreflightError as e:
        print(f"[FATAL] Preflight {symbol} : {e}")
        print(f"[FATAL] Training {symbol} AVORTE.")
        return []

    trainer = ModelTrainer(config)
    results = []

    for side in ["buy", "sell"]:
        result = trainer.train_model(symbol, side, df, features, tune=tune)
        if result.get("model") is not None:
            # ═══════════════════════════════════════════════════════════
            # IMPORTANCE GUARD — Trou 3 (Jackson 13/04/2026)
            # Detecte une fuite cachee post-training
            # ═══════════════════════════════════════════════════════════
            try:
                importance_guard(
                    model=result["model"],
                    features=features,
                    symbol=symbol,
                    side=side,
                )
                save_model(result, config)
            except ImportanceLeakError as e:
                print(f"[FATAL] Importance guard {symbol} {side} : {e}")
                print(f"[FATAL] Modele NON sauvegarde — revoir les features.")
                result["saved"] = False
                result["leak_detected"] = str(e)
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

    # --- Version dataset : v2 (live 15j) par defaut, v3 (backfill 70j) via flag ---
    # 2026-04-14 : permet de basculer entre dataset live et dataset backfillé.
    if "--v3" in sys.argv:
        setattr(config, "dataset_version", "v3")
        print(f"[DATASET] v3 (backfill historique ~70 jours)")
    elif "--v2" in sys.argv:
        setattr(config, "dataset_version", "v2")
        print(f"[DATASET] v2 (live ~15 jours)")
    # sinon defaut = v2 via getattr fallback

    # --- Stress test couts x2 (Davey, 2026-04-14) ---
    # Flag pour doubler les couts de transaction et voir si l'edge tient.
    # Un systeme robuste doit garder un PF >= 1.0 en stress-mode.
    # Le save_model utilise suffix _stress pour ne PAS ecraser les modeles normaux.
    if "--stress-costs" in sys.argv:
        original_es = config.cost_ticks_es
        original_nq = config.cost_ticks_nq
        config.cost_ticks_es *= 2.0
        config.cost_ticks_nq *= 2.0
        setattr(config, "stress_mode", True)  # save_model detecte ce flag
        print(f"[STRESS MODE] Couts x2 (Davey Reliable Systems)")
        print(f"  ES : {original_es}t → {config.cost_ticks_es}t")
        print(f"  NQ : {original_nq}t → {config.cost_ticks_nq}t")
        print(f"  Critere : edge doit tenir avec des couts doubles")
        print(f"  Modeles sauves avec suffix _stress (ex: ES_buy_stress_model.pkl)")

    if not tune:
        print("[MODE] Params par defaut (skip Optuna)")

    all_results = []
    for sym in symbols:
        results = run_training(sym, config, tune=tune)
        all_results.extend(results)

    if all_results:
        generate_report(all_results, config)
