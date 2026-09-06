"""vrp_phase0_backtest.py — Go/No-Go VRP friction-aware (Phase 0).

Question unique : le Variance Risk Premium survit-il aux frictions (bid/ask
options + commissions) ? Si oui -> feu vert paper. Sinon -> stop avant infra.

Methodo (convergence agents market-analyst + Plan, 16/06) :
  - Structure : Iron Condor DEFINI-RISQUE, ~10 DTE (pas 0DTE = gamma-bomb).
  - Pricing : Black-76 (options sur futures ES) avec IV30D MenthorQ.
  - Strikes : short put < Put Support, short call > Call Resistance (au-dela des
    murs gamma). Ailes a largeur fixe (perte bornee).
  - Frictions : bid/ask % du credit + commission/jambe (AMP).
  - Gestion : hold-to-expiry (baseline) ET stop 2x credit (compare).
  - Filtre timing : IV 14-22% ET en detente (anti 23/03/2026).
  - Focus : comportement sur le cluster stress mars 2026 (le test de queue).

CAVEAT acte : pricing proxy IV30D (pas de chaine IV par strike). Directionnel
fiable (l'edge survit-il aux couts ?), pas le niveau exact de P&L.
"""
from __future__ import annotations

import glob
import json
import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

# ── Parametres (ES) ─────────────────────────────────────────────────────────
MULT_ES = 50.0           # $/point option ES standard (micro MES = 5.0)
COMMISSION_PER_LEG = 1.5  # $ AMP par jambe (IC = 4 jambes)
BIDASK_FRAC = 0.05        # 5% du prix theorique perdu en spread bid/ask par jambe
RISK_FREE = 0.04
DTE_DAYS = 10             # jours calendaires a l'expiry
HOLD_BARS = 10            # ~10 jours de trading (approx DTE en trading days)
WING_WIDTH_PCT = 0.010    # ailes a 1% du spot (largeur du spread defini)
OTM_BUFFER_PCT = 0.003    # buffer au-dela des murs MenthorQ


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76(is_call: bool, F: float, K: float, T: float, sigma: float, r: float = RISK_FREE) -> float:
    """Prix Black-76 option europeenne sur future. T en annees, sigma en decimal."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (F - K) if is_call else (K - F))
        return intrinsic
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    if is_call:
        return disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    return disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))


def load_es_daily() -> Dict[str, float]:
    """date YYYYMMDD -> close ES de fin de journee."""
    out: Dict[str, float] = {}
    for f in sorted(glob.glob("DATA/live_enriched/ES/*.jsonl")):
        last = None
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = o.get("close")
            if isinstance(c, (int, float)):
                last = c
        if last is not None:
            out[os.path.basename(f)[:8]] = float(last)
    return out


def load_menthorq() -> Dict[str, dict]:
    """date YYYYMMDD -> {iv, put_support, call_resistance, d1max, d1min}."""
    out: Dict[str, dict] = {}
    for f in sorted(glob.glob("DATA/MENTHORQ/*menthorq_complete.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        es = d.get("ES", {}).get("structured", {})
        kl = es.get("key_levels", {})
        res = kl.get("resource", {}) if isinstance(kl, dict) else {}
        data = res.get("data", {}) if isinstance(res, dict) else {}
        if not isinstance(data, dict):
            continue
        iv = None
        for k in data:
            if "implied vol" in k.lower():
                iv = data[k]
        if iv is None:
            continue
        def _num(key):
            v = data.get(key)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        out[os.path.basename(f)[:8]] = {
            "iv": float(iv),
            "put_support": _num("Put Support"),
            "call_resistance": _num("Call Resistance"),
            "d1max": _num("1D Max."),
            "d1min": _num("1D Min."),
        }
    return out


def simulate(use_timing_filter: bool, use_stop: bool) -> dict:
    es = load_es_daily()
    mq = load_menthorq()
    dates = sorted(set(es) & set(mq))
    es_dates = sorted(es)
    idx = {dt: i for i, dt in enumerate(es_dates)}

    trades: List[dict] = []
    prev_iv: Optional[float] = None
    T = DTE_DAYS / 365.0

    for dt in dates:
        m = mq[dt]
        iv_pct = m["iv"]
        iv = iv_pct / 100.0
        F = es[dt]

        # Filtre timing (anti 23/03 : IV haute MAIS en detente seulement)
        passes = True
        if use_timing_filter:
            passes = (14.0 <= iv_pct <= 22.0) and (prev_iv is not None and iv_pct <= prev_iv)
        prev_iv = iv_pct
        if not passes:
            continue

        # Spot a l'expiry (10 jours de trading plus tard)
        if dt not in idx or idx[dt] + HOLD_BARS >= len(es_dates):
            continue
        S_T = es[es_dates[idx[dt] + HOLD_BARS]]

        # Strikes : au-dela des murs MenthorQ (fallback : 1 ecart-type)
        em = F * iv * math.sqrt(T)  # expected move ~1 sigma
        put_short = m["put_support"] or (F - em)
        call_short = m["call_resistance"] or (F + em)
        put_short = min(put_short, F - 0.5 * em) - F * OTM_BUFFER_PCT
        call_short = max(call_short, F + 0.5 * em) + F * OTM_BUFFER_PCT
        wing = F * WING_WIDTH_PCT
        put_long = put_short - wing
        call_long = call_short + wing

        # Credit IC (Black-76)
        put_credit = black76(False, F, put_short, T, iv) - black76(False, F, put_long, T, iv)
        call_credit = black76(True, F, call_short, T, iv) - black76(True, F, call_long, T, iv)
        gross_credit = put_credit + call_credit  # en points ES
        if gross_credit <= 0:
            continue

        # Frictions : bid/ask par jambe (4) + commissions
        bidask_cost = BIDASK_FRAC * (
            black76(False, F, put_short, T, iv) + black76(False, F, put_long, T, iv)
            + black76(True, F, call_short, T, iv) + black76(True, F, call_long, T, iv)
        )
        net_credit = gross_credit - bidask_cost
        commissions_pts = (4 * COMMISSION_PER_LEG * 2) / MULT_ES  # 4 jambes, open+close

        # P&L a l'expiry (perte bornee par la largeur)
        if S_T <= put_long:
            payoff = -wing
        elif S_T < put_short:
            payoff = -(put_short - S_T)
        elif S_T <= call_short:
            payoff = 0.0
        elif S_T < call_long:
            payoff = -(S_T - call_short)
        else:
            payoff = -wing
        pnl_pts = net_credit + payoff - commissions_pts

        # Gestion ACTIVE (coeur de l'edge VRP per agents) : re-price chaque jour
        #   - profit target : fermer a 50% du credit capture (encaisse theta,
        #     evite gamma de fin) -> ne necessite PAS de path IV
        #   - stop : couper si rachat coute >= 2x net_credit (perte limitee)
        stopped = False
        exited = False
        if use_stop:
            for h in range(1, HOLD_BARS):
                if idx[dt] + h >= len(es_dates):
                    break
                S_h = es[es_dates[idx[dt] + h]]
                T_h = max((DTE_DAYS - h) / 365.0, 1e-4)
                cur = (black76(False, S_h, put_short, T_h, iv) - black76(False, S_h, put_long, T_h, iv)
                       + black76(True, S_h, call_short, T_h, iv) - black76(True, S_h, call_long, T_h, iv))
                profit = net_credit - cur  # encaisse a la cloture maintenant
                if profit >= 0.5 * net_credit:  # profit target 50%
                    pnl_pts = 0.5 * net_credit - commissions_pts
                    exited = True
                    break
                if cur - net_credit >= 2.0 * net_credit:  # stop 2x credit
                    pnl_pts = -2.0 * net_credit - commissions_pts
                    stopped = True
                    break

        trades.append({
            "date": dt, "pnl_pts": pnl_pts, "pnl_usd": pnl_pts * MULT_ES,
            "net_credit": net_credit, "iv": iv_pct, "stopped": stopped,
            "month": dt[:6],
        })

    return _report(trades, use_timing_filter, use_stop)


def _report(trades: List[dict], tf: bool, stop: bool) -> dict:
    if not trades:
        return {"n": 0, "label": f"timing={tf} stop={stop}", "msg": "0 trades"}
    pnl = np.array([t["pnl_usd"] for t in trades])
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else 99.0
    # cluster mars 2026
    mar = [t for t in trades if t["month"] == "202603"]
    mar_pnl = sum(t["pnl_usd"] for t in mar)
    return {
        "label": f"timing={tf} stop={stop}",
        "n": len(trades),
        "win_rate": 100 * float(np.mean(pnl > 0)),
        "pf": float(pf),
        "ev_usd": float(pnl.mean()),
        "total_usd": float(pnl.sum()),
        "max_dd_usd": dd,
        "worst_trade": float(pnl.min()),
        "best_trade": float(pnl.max()),
        "mar2026_n": len(mar),
        "mar2026_pnl": mar_pnl,
    }


if __name__ == "__main__":
    print("=== VRP PHASE 0 — Go/No-Go friction-aware (Iron Condor ES ~10 DTE, $50 mult) ===")
    print(f"Frictions : bid/ask {BIDASK_FRAC*100:.0f}%/jambe + ${COMMISSION_PER_LEG}/jambe x4 open+close\n")
    for tf in (False, True):
        for stop in (False, True):
            r = simulate(use_timing_filter=tf, use_stop=stop)
            if r.get("n", 0) == 0:
                print(f"  {r['label']}: 0 trades")
                continue
            print(f"  {r['label']}:")
            print(f"    n={r['n']} WR={r['win_rate']:.0f}% PF={r['pf']:.2f} "
                  f"EV=${r['ev_usd']:+.0f}/trade total=${r['total_usd']:+.0f}")
            print(f"    maxDD=${r['max_dd_usd']:.0f} worst=${r['worst_trade']:+.0f} "
                  f"best=${r['best_trade']:+.0f}")
            print(f"    >>> cluster mars 2026 : n={r['mar2026_n']} pnl=${r['mar2026_pnl']:+.0f} (test queue)")
    print("\nGO si : total>0 ET PF>1.1 ET mars 2026 survivable (pas de wipe-out).")
    print("Rappel : pricing proxy IV30D, niveau P&L indicatif, le SENS (survit aux couts?) est fiable.")
