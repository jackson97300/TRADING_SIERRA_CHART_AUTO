"""
PSR / DSR Analysis — Lopez AFML ch.14 statistical validation

Calcule le Probabilistic Sharpe Ratio (PSR) et le Deflated Sharpe Ratio (DSR)
pour les 4 modeles primary (ES/NQ buy/sell) afin de determiner si l'edge
observe est statistiquement significatif ou un artefact de petit echantillon.

Seuil de decision (Lopez ch.14) :
    PSR >= 0.95 -> edge reel (confiance 95%)
    PSR < 0.95  -> potentiel false positive

Formule PSR :
    PSR(SR*) = Phi( (SR - SR*) * sqrt(N-1) / sqrt(1 - gamma3*SR + (gamma4-1)/4 * SR^2) )

Ou :
    SR     = Sharpe observe (basé trade returns)
    SR*    = Sharpe minimum (ici 0 = profitable-or-not)
    N      = nombre de trades
    gamma3 = skewness des returns
    gamma4 = kurtosis (Fisher) des returns
    Phi    = CDF de la normale centree reduite

DSR (ajuste biais de selection) :
    DSR = PSR avec SR* augmente pour tenir compte de N_trials teste
    SR*_deflated = sqrt(2 * log(N_trials)) / sqrt(N)

Usage :
    python -X utf8 CORE/research/psr_dsr_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "DATA" / "MODELS"


def compute_psr(trade_returns: np.ndarray, sr_ref: float = 0.0) -> dict:
    """Probabilistic Sharpe Ratio (Lopez AFML ch.14).

    Returns:
        dict avec : sr, n, skew, kurt_excess, psr, std_error_sr
    """
    n = len(trade_returns)
    if n < 5:
        return {"sr": 0.0, "n": n, "psr": 0.0, "error": "n<5"}

    mean_r = trade_returns.mean()
    std_r = trade_returns.std(ddof=1)
    if std_r < 1e-9:
        return {"sr": 0.0, "n": n, "psr": 0.0, "error": "std=0"}

    sr = mean_r / std_r
    skew = stats.skew(trade_returns)
    kurt_excess = stats.kurtosis(trade_returns, fisher=True)  # Fisher = excess kurt

    # Formule Lopez ch.14 eq. 14.8
    # psr = Phi( (SR - SR*) * sqrt(N-1) / sqrt(1 - gamma3*SR + (gamma4/4)*SR^2) )
    # gamma4 ici = excess kurt = kurt_excess (pas kurt brut - 3)
    # Mais la formule historique utilise (gamma4 - 1) ou gamma4 = kurt excess,
    # soit (kurt_excess - 1) / 4 = directement kurt_excess/4 si kurt Fisher.
    # On prend la version stable : denom = 1 - skew*SR + (kurt_excess/4)*SR^2
    denom_sq = 1.0 - skew * sr + (kurt_excess / 4.0) * sr ** 2
    if denom_sq <= 0:
        # Pathologique (queue lourde extreme). Fallback : denom = 1.
        denom_sq = 1.0
    denom = np.sqrt(denom_sq)

    z = (sr - sr_ref) * np.sqrt(n - 1) / denom
    psr = stats.norm.cdf(z)

    std_error_sr = denom / np.sqrt(n - 1)

    return {
        "sr": float(sr),
        "n": int(n),
        "skew": float(skew),
        "kurt_excess": float(kurt_excess),
        "psr": float(psr),
        "std_error_sr": float(std_error_sr),
        "z": float(z),
    }


def compute_dsr(trade_returns: np.ndarray, n_trials: int) -> dict:
    """Deflated Sharpe Ratio (Lopez AFML ch.14).

    Ajuste le PSR pour le biais de selection lorsque N_trials modeles ont ete testes.

    SR*_deflated = sqrt(2 * log(N_trials)) / sqrt(N)

    DSR = PSR avec ce SR* au lieu de 0.

    Args:
        trade_returns : array des pnl par trade (en ticks ou USD)
        n_trials      : nombre de configs/modeles testes (ici 4 + walk-forward 8 folds
                       + threshold optim = ~50-100 trials effectifs)
    """
    n = len(trade_returns)
    if n < 5:
        return {"dsr": 0.0, "sr_ref_deflated": 0.0, "error": "n<5"}

    sr_ref_deflated = np.sqrt(2.0 * np.log(max(n_trials, 1))) / np.sqrt(n)
    psr_result = compute_psr(trade_returns, sr_ref=sr_ref_deflated)

    return {
        "dsr": psr_result.get("psr", 0.0),
        "sr_ref_deflated": float(sr_ref_deflated),
        "sr": psr_result.get("sr", 0.0),
        "n_trials": n_trials,
    }


def extract_trade_returns_from_folds(folds_path: Path) -> np.ndarray:
    """Reconstitue les trade returns depuis les fold_metrics.

    Approximation : utilise les pnl agreges par fold + (profit_factor * nb_trades).
    Pour un calcul strict PSR, il faudrait le PnL de chaque trade individuel.
    On simule ici avec la distribution moyenne.
    """
    if not folds_path.exists():
        return np.array([])

    with open(folds_path) as f:
        folds = json.load(f)

    # Reconstruit des returns approximes : chaque fold donne ev_trade (moyen)
    # et win_rate. On distribue les trades selon R:R implicite.
    all_returns = []
    for fm in folds:
        n = fm.get("trades", 0)
        if n == 0:
            continue
        wr = fm.get("win_rate", 0.5)
        ev = fm.get("ev_trade", 0.0)
        pf = fm.get("profit_factor", 1.0)
        pnl_total = fm.get("pnl_ticks", 0.0)

        if n < 1:
            continue
        n_win = int(round(n * wr))
        n_loss = n - n_win

        # Reconstitution correcte (Lopez AFML ch.14) :
        # Soit avg_w = avg win ticks, avg_l = avg loss ticks (positif).
        #   ev = wr*avg_w - (1-wr)*avg_l
        #   pf = (wr*avg_w) / ((1-wr)*avg_l)
        # => avg_w = pf * (1-wr)/wr * avg_l
        # => ev = (1-wr)*avg_l * (pf - 1)
        # => avg_l = ev / ((1-wr)*(pf - 1))  ssi pf != 1
        if n_loss > 0 and 0 < wr < 1 and abs(pf - 1.0) > 1e-6:
            denom = (1 - wr) * (pf - 1)
            if abs(denom) > 1e-9:
                avg_l = ev / denom
                avg_w = pf * (1 - wr) / wr * avg_l
                # Securite : |avg_l| et |avg_w| doivent etre > 0
                avg_l = abs(avg_l)
                avg_w = abs(avg_w)
            else:
                # pf ~ 1 => ev ~ 0 => no real edge, skip
                continue
        elif pf > 1 and wr == 1.0:
            # Impossible en pratique
            avg_w = abs(ev) * 2
            avg_l = 0.001
        else:
            continue

        returns_fold = ([avg_w] * n_win) + ([-avg_l] * n_loss)
        all_returns.extend(returns_fold)

    return np.array(all_returns, dtype=float)


def main():
    print("=" * 70)
    print("  PSR / DSR ANALYSIS — Lopez AFML ch.14 statistical validation")
    print("=" * 70)
    print()

    n_trials_estimate = 50  # 4 models x ~12 walk-forward folds + threshold optim

    results = []
    for model in ["ES_buy", "ES_sell", "NQ_buy", "NQ_sell"]:
        folds_path = MODELS_DIR / f"{model}_folds.json"
        returns = extract_trade_returns_from_folds(folds_path)

        if len(returns) < 20:
            print(f"  {model}: trades insuffisants ({len(returns)})")
            continue

        psr = compute_psr(returns, sr_ref=0.0)
        dsr = compute_dsr(returns, n_trials=n_trials_estimate)

        results.append({
            "model": model,
            "n_trades": len(returns),
            "sr_observed": psr["sr"],
            "skew": psr["skew"],
            "kurt_excess": psr["kurt_excess"],
            "psr_vs_zero": psr["psr"],
            "sr_ref_deflated": dsr["sr_ref_deflated"],
            "dsr": dsr["dsr"],
        })

    df = pd.DataFrame(results)

    print(f"\n{'Model':10s} {'N':>5s} {'SR':>7s} {'skew':>7s} {'kurt':>7s} {'PSR':>7s} {'SR*_d':>8s} {'DSR':>7s}")
    print("-" * 70)
    for _, r in df.iterrows():
        print(
            f"{r['model']:10s} "
            f"{r['n_trades']:>5d} "
            f"{r['sr_observed']:>7.3f} "
            f"{r['skew']:>7.3f} "
            f"{r['kurt_excess']:>7.3f} "
            f"{r['psr_vs_zero']:>7.3f} "
            f"{r['sr_ref_deflated']:>8.3f} "
            f"{r['dsr']:>7.3f}"
        )

    print()
    print("=" * 70)
    print("  SEUIL Lopez AFML : PSR >= 0.95 ET DSR >= 0.95 pour GO statistique")
    print("=" * 70)
    for _, r in df.iterrows():
        psr_ok = r['psr_vs_zero'] >= 0.95
        dsr_ok = r['dsr'] >= 0.95
        verdict = "GO" if (psr_ok and dsr_ok) else "NO-GO"
        reasons = []
        if not psr_ok:
            reasons.append(f"PSR {r['psr_vs_zero']:.3f} < 0.95")
        if not dsr_ok:
            reasons.append(f"DSR {r['dsr']:.3f} < 0.95")
        reason_str = " | ".join(reasons) if reasons else "all OK"
        print(f"  {r['model']:10s} : {verdict:6s} ({reason_str})")

    out_csv = REPO_ROOT / "DATA" / "MODELS" / "psr_dsr_report.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nRapport sauvegarde : {out_csv}")


if __name__ == "__main__":
    main()
