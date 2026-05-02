"""
dsr_calculator.py — Deflated Sharpe Ratio (Bailey & Lopez De Prado 2014)

Created : 2026-05-02 samedi
Author : Jackson + GATE_17H_METHODOLOGY section 4.3

Lopez AFML ch.13 (eq. 13.4-13.5) :
DSR = Φ( (SR_obs - SR_threshold) × √(N-1) /
          √(1 - γ₃·SR_obs + ((γ₄-1)/4)·SR_obs²) )

ou:
- SR_obs       = Sharpe ratio annualise OOS (returns trade-par-trade)
- SR_threshold = E[max{SR_k}] sur n_trials trials Optuna+manual
                 ≈ √(2·ln(n_trials)) pour n_trials >= 8
- γ₃, γ₄       = skewness, kurtosis returns trade
- N            = nb returns OOS

DSR > 0.95 = strategie statistiquement robuste apres correction selection bias.
DSR > 0.6  = realiste pour 1m bars futures (cf GATE_17H seuils).

n_trials_DECLARE_MIN = 120 (4 baselines × 30 Optuna trials, samedi)
n_trials_DECLARE_MAX = 290 (cumul samedi + dimanche + iterations historiques)
"""

from __future__ import annotations
from typing import Optional
import numpy as np
from scipy.stats import norm


def compute_dsr(returns: np.ndarray,
                 n_trials: int,
                 sr_threshold: Optional[float] = None,
                 annualization_factor: float = 252.0) -> dict:
    """
    Deflated Sharpe Ratio Bailey-Lopez 2014.

    Args:
        returns : array trade-by-trade returns (cost-adjusted ideally)
        n_trials : nb configurations testees historiquement (Optuna + manual)
                   Convention V5 : MIN 120 (samedi seul), MAX 290 (full cumul)
        sr_threshold : si None, calcule via sqrt(2*ln(n_trials))
        annualization_factor : 252 jours par an default. Pour returns intraday
                               trade-by-trade, 252 reste correct (annualisation
                               via sqrt(N_trades_per_year)).

    Returns:
        dict avec :
            dsr : DSR ∈ [0, 1] — proba SR_true > SR_threshold
            sr_obs : Sharpe observe annualise
            sr_threshold : seuil minimal Sharpe (Bailey eq. 13.4)
            n : nb returns
            skew : skewness returns
            kurt : kurtosis returns (Pearson, ≥1)
            n_trials : declaree
            warning : str si numeric issue (ex: var_term <= 0)
    """
    n = len(returns)
    if n < 30:
        return {
            "dsr": 0.0,
            "sr_obs": np.nan,
            "warning": f"N={n} too small for DSR (Lopez recommends >=30)",
            "n": n, "n_trials": n_trials,
        }

    returns_arr = np.asarray(returns, dtype=float)

    # Sharpe non-annualise (per-trade)
    mu = returns_arr.mean()
    sigma = returns_arr.std(ddof=1)
    if sigma <= 0:
        return {
            "dsr": 0.0,
            "sr_obs": np.nan,
            "warning": "std(returns) <= 0",
            "n": n, "n_trials": n_trials,
        }

    sr_per_trade = mu / sigma
    # Annualise : Lopez eq 13.5 utilise SR per-period × sqrt(periods_per_year)
    # Ici returns trade-par-trade : annualiser via sqrt(N_trades_per_year)
    # Heuristique : si N=1000 trades sur 1 an, sr_obs = sr_per_trade * sqrt(1000)
    # Plus simple et conservateur : annualisation via factor user-specified.
    sr_obs = sr_per_trade * np.sqrt(annualization_factor)

    # Skewness / Kurtosis (Pearson, kurt = 3 pour normale)
    skew = ((returns_arr - mu) ** 3).mean() / sigma ** 3
    kurt = ((returns_arr - mu) ** 4).mean() / sigma ** 4

    # SR threshold via E[max{SR_k}] eq. 13.4
    if sr_threshold is None:
        if n_trials < 1:
            return {
                "dsr": 0.0,
                "sr_obs": float(sr_obs),
                "warning": f"n_trials={n_trials} invalid",
                "n": n, "n_trials": n_trials,
            }
        sr_threshold = np.sqrt(2.0 * np.log(max(n_trials, 1)))
        # Si n_trials = 1, seuil = 0 (pas de bias)

    # Variance term (eq 13.5 numerator)
    var_term = 1.0 - skew * sr_per_trade + ((kurt - 1.0) / 4.0) * sr_per_trade ** 2
    if var_term <= 0:
        return {
            "dsr": 0.0,
            "sr_obs": float(sr_obs),
            "sr_threshold": float(sr_threshold),
            "n": n, "skew": float(skew), "kurt": float(kurt),
            "n_trials": n_trials,
            "warning": f"var_term={var_term:.4f} <= 0 (kurt extreme)",
        }

    # DSR = Φ( (SR_per_trade - SR_threshold_per_trade) × √(N-1) / √(var_term) )
    # Note : convention Lopez = SR per-period (pas annualise) pour le DSR.
    # Mais Bailey 2014 annonce souvent SR annualise — convention V5 = per-trade
    # pour eviter ambiguite annualization.
    dsr = norm.cdf(
        (sr_per_trade - sr_threshold / np.sqrt(annualization_factor))
        * np.sqrt(n - 1) / np.sqrt(var_term)
    )

    return {
        "dsr": float(dsr),
        "sr_obs": float(sr_obs),
        "sr_per_trade": float(sr_per_trade),
        "sr_threshold": float(sr_threshold),
        "n": int(n),
        "skew": float(skew),
        "kurt": float(kurt),
        "n_trials": int(n_trials),
        "var_term": float(var_term),
    }


# ═════════════════════════════════════════════════════════════════════
# CLI / Tests synthetiques
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test 1 : returns positifs Sharpe ~2 sur 500 trades, n_trials=120
    np.random.seed(42)
    rets_good = np.random.normal(0.005, 0.02, 500)  # SR ≈ 0.25 per-trade ≈ 4 annualise
    res = compute_dsr(rets_good, n_trials=120)
    print(f"[test 1] Good returns SR=2 N=500 n_trials=120 :")
    print(f"  DSR={res['dsr']:.3f}, SR_obs={res['sr_obs']:.2f}, "
          f"SR_thresh={res['sr_threshold']:.2f}")

    # Test 2 : returns ~0 mean, n_trials=120
    rets_neutral = np.random.normal(0.0, 0.02, 500)
    res2 = compute_dsr(rets_neutral, n_trials=120)
    print(f"\n[test 2] Neutral returns SR≈0 N=500 n_trials=120 :")
    print(f"  DSR={res2['dsr']:.3f}, SR_obs={res2['sr_obs']:.2f}")

    # Test 3 : returns negatifs
    rets_bad = np.random.normal(-0.005, 0.02, 500)
    res3 = compute_dsr(rets_bad, n_trials=120)
    print(f"\n[test 3] Bad returns SR<0 N=500 n_trials=120 :")
    print(f"  DSR={res3['dsr']:.3f}, SR_obs={res3['sr_obs']:.2f}")
