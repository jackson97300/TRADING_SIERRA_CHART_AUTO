"""Backtest SWEEP REVERSAL LONG avec un sweep PROPRE (zero look-ahead).

L'analyse Claude.ai donnait PF 1.45 / +131k$ pour le Sweep Reversal LONG, mais
elle s'appuyait sur `liquidity_sweep_low_lag5` = feature LOOK-AHEAD (consulte
close[i+5], cf build_dataset_v4 l.455, blacklist PROHIBITED, incident #13).

Ici on reconstruit le setup avec un sweep detecte SANS look-ahead :
  1. swing low confirme (lag k barres assume - on ne le "connait" qu'a idx+k)
  2. le prix BALAYE ce swing low (low passe sous, prise de stops)
  3. le close REVIENT au-dessus du swing low (rejet = stop hunt echoue)
  -> ENTREE LONG a la barre de reintegration.
Tout est observable en temps reel. Aucune barre future consultee.

Si le PF tient (~1.4) -> l'edge etait reel. S'il s'effondre (~1.0) -> le
PF 1.45 de l'analyse etait l'artefact du leak (comme le subset 9).

USAGE : python -X utf8 tools/backtest_sweep_reversal.py
"""
from __future__ import annotations

import glob
import json

TICK = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}
SWING_K = 5            # confirmation swing (lag assume)
SWEEP_LOOKBACK = 40    # le swing low balaye doit dater de <= 40 barres
SWEEP_MIN_T = 2        # le low doit passer >= 2 ticks SOUS le swing low
REINTEG_MAX = 3        # reintegration dans les 3 barres apres le balayage
BUFFER_T = 10
RR = 1.5
COST_T = 1.0


def detect_swing_lows(H, L, k=SWING_K):
    """Swing lows : creux entoure de k barres plus hautes. Retourne [(idx, price)]."""
    out = []
    n = len(L)
    for i in range(k, n - k):
        if L[i] < min(L[i - k:i]) and L[i] < min(L[i + 1:i + k + 1]):
            out.append((i, L[i]))
    return out


def find_sweep_reversals(H, L, C):
    """Retourne [(entry_idx, sweep_low_price, sweep_bar_low)] — LONG.

    A la barre i : un swing low confirme anterieur a ete balaye (low sous le
    niveau) puis le close[i] est revenu au-dessus, dans les REINTEG_MAX barres.
    """
    swings = detect_swing_lows(H, L)
    out = []
    used = set()
    n = len(C)
    for i in range(SWING_K + 5, n):
        # swing lows confirmes AVANT i (idx + k <= i) et recents
        cand = [(idx, p) for idx, p in swings
                if idx + SWING_K <= i and (i - idx) <= SWEEP_LOOKBACK]
        if not cand:
            continue
        sl_idx, sl_price = cand[-1]  # le plus recent
        if sl_idx in used:
            continue
        # chercher la barre de balayage : low < swing_low - SWEEP_MIN_T, apres sl_idx
        sweep_bar = None
        for b in range(sl_idx + 1, i + 1):
            if L[b] < sl_price - SWEEP_MIN_T * TICK:
                sweep_bar = b
                break
        if sweep_bar is None:
            continue
        # reintegration : close[i] au-dessus du swing low, i proche du balayage
        if C[i] > sl_price and 0 <= (i - sweep_bar) <= REINTEG_MAX:
            sweep_low = min(L[sweep_bar:i + 1])
            out.append((i, sl_price, sweep_low))
            used.add(sl_idx)
    return out


def simulate(H, L, C, entry_idx, entry, stop, tp):
    n = len(C)
    for i in range(entry_idx + 1, n):
        if L[i] <= stop:
            return -(entry - stop) / TICK - COST_T
        if H[i] >= tp:
            return (tp - entry) / TICK - COST_T
    return (C[n - 1] - entry) / TICK - COST_T


def load_day(path):
    H, L, C, M = [], [], [], []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        try:
            H.append(float(d["high"]))
            L.append(float(d["low"]))
            C.append(float(d["close"]))
            M.append(str(d.get("ts_event"))[:7])
        except (KeyError, TypeError, ValueError):
            pass
    return H, L, C, M


def main():
    trades = []
    for sym in ("ES", "NQ"):
        for fp in sorted(glob.glob(f"DATA/live_enriched/{sym}/*.jsonl")):
            H, L, C, M = load_day(fp)
            if len(C) < 60:
                continue
            for entry_idx, sl_price, sweep_low in find_sweep_reversals(H, L, C):
                entry = C[entry_idx]
                stop = sweep_low - BUFFER_T * TICK
                if entry <= stop:
                    continue
                tp = entry + RR * (entry - stop)
                pnl = simulate(H, L, C, entry_idx, entry, stop, tp)
                trades.append({"sym": sym, "pnl": pnl,
                               "month": M[entry_idx] if entry_idx < len(M) else "?"})

    print("=== SWEEP REVERSAL LONG — sweep PROPRE (zero look-ahead) ===\n")
    for sym in ("ES", "NQ", None):
        sub = [t for t in trades if sym is None or t["sym"] == sym]
        if not sub:
            continue
        wins = [t["pnl"] for t in sub if t["pnl"] > 0]
        losses = [t["pnl"] for t in sub if t["pnl"] <= 0]
        pf = sum(wins) / -sum(losses) if losses and sum(losses) < 0 else 999.0
        wr = 100.0 * len(wins) / len(sub)
        tot = sum(t["pnl"] for t in sub)
        usd = sum(t["pnl"] * TICK_VALUE[t["sym"]] * 3 for t in sub)
        print(f"{sym or 'TOTAL':<7} n={len(sub):<5} WR={wr:>5.1f}%  PF={pf:>5.2f}  "
              f"net={tot:>+8.0f}t  ({usd:>+9.0f}$)")

    # stabilite mensuelle (ES — plus de data)
    print("\n  Stabilite mensuelle (ES) :")
    es = [t for t in trades if t["sym"] == "ES"]
    months = sorted(set(t["month"] for t in es))
    for m in months:
        mt = [t for t in es if t["month"] == m]
        w = [t["pnl"] for t in mt if t["pnl"] > 0]
        lo = [t["pnl"] for t in mt if t["pnl"] <= 0]
        pf = sum(w) / -sum(lo) if lo and sum(lo) < 0 else 999.0
        print(f"    {m}  n={len(mt):<4} PF={pf:>5.2f}  net={sum(t['pnl'] for t in mt):>+7.0f}t")


if __name__ == "__main__":
    raise SystemExit(main())
