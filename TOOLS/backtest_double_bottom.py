"""Backtest du pattern DOUBLE BOTTOM sur le dataset live_enriched (118 jours).

Le double bottom n'utilise que high/low/close -> testable sans le delta
(donc sur le dataset replay local meme si les trades manquent).

Pattern : creux1 (swing low) -> rebond (swing high) -> creux2 (swing low)
  - 2 creux a <= ECART_MAX_T ticks
  - rebond intermediaire >= REBOND_MIN_T ticks au-dessus des creux
  - espacement 5-60 barres
  - creux2 pas plus bas que creux1 - ECART_MAX_T
Entree : LONG au close de la barre de confirmation (creux2 + CONFIRM_LAG barres).
Stop   : min(creux1, creux2) - BUFFER_T ticks.
TP     : entree + RR * (entree - stop).
Exit bar-aware, ordre pessimiste (SL avant TP).

USAGE : python -X utf8 tools/backtest_double_bottom.py
"""
from __future__ import annotations

import glob
import json

TICK = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}
SWING_K = 5
ECART_MAX_T = 15
REBOND_MIN_T = 30
SPAN_MIN, SPAN_MAX = 5, 60
CONFIRM_LAG = 5
BUFFER_T = 10
RR = 1.5
COST_T = 1.0


def detect_swings(H, L, k=SWING_K):
    sw = []
    n = len(H)
    for i in range(k, n - k):
        if H[i] > max(H[i - k:i]) and H[i] > max(H[i + 1:i + k + 1]):
            sw.append((i, H[i], "H"))
        if L[i] < min(L[i - k:i]) and L[i] < min(L[i + 1:i + k + 1]):
            sw.append((i, L[i], "L"))
    sw.sort()
    return sw


def find_double_bottoms(sw):
    """Retourne liste de (i1, p1, i2, p2, i3, p3)."""
    out = []
    for a in range(len(sw) - 2):
        if sw[a][2] != "L":
            continue
        b = next((j for j in range(a + 1, len(sw)) if sw[j][2] == "H"), None)
        if b is None:
            continue
        c = next((j for j in range(b + 1, len(sw)) if sw[j][2] == "L"), None)
        if c is None:
            continue
        i1, p1, _ = sw[a]
        i2, p2, _ = sw[b]
        i3, p3, _ = sw[c]
        ecart = abs(p1 - p3) / TICK
        rebond = (p2 - max(p1, p3)) / TICK
        span = i3 - i1
        if (ecart <= ECART_MAX_T and rebond >= REBOND_MIN_T
                and SPAN_MIN <= span <= SPAN_MAX and p3 >= p1 - ECART_MAX_T * TICK):
            out.append((i1, p1, i2, p2, i3, p3))
    return out


def simulate(df_h, df_l, df_c, entry_idx, entry, stop, tp):
    """LONG bar-aware. Retourne pnl_ticks."""
    n = len(df_c)
    for i in range(entry_idx + 1, n):
        if df_l[i] <= stop:
            return -(entry - stop) / TICK - COST_T
        if df_h[i] >= tp:
            return (tp - entry) / TICK - COST_T
    return (df_c[n - 1] - entry) / TICK - COST_T


def load_day(path):
    H, L, C = [], [], []
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
        except (KeyError, TypeError, ValueError):
            pass
    return H, L, C


def main():
    trades = []
    for sym in ("NQ", "ES"):
        files = sorted(glob.glob(f"DATA/live_enriched/{sym}/*.jsonl"))
        for fp in files:
            H, L, C = load_day(fp)
            if len(C) < 60:
                continue
            sw = detect_swings(H, L)
            for i1, p1, i2, p2, i3, p3 in find_double_bottoms(sw):
                entry_idx = i3 + CONFIRM_LAG
                if entry_idx >= len(C):
                    continue
                entry = C[entry_idx]
                stop = min(p1, p3) - BUFFER_T * TICK
                if entry <= stop:
                    continue
                tp = entry + RR * (entry - stop)
                pnl = simulate(H, L, C, entry_idx, entry, stop, tp)
                trades.append({"sym": sym, "pnl": pnl})

    for sym in ("NQ", "ES", None):
        sub = [t for t in trades if sym is None or t["sym"] == sym]
        if not sub:
            continue
        wins = [t["pnl"] for t in sub if t["pnl"] > 0]
        losses = [t["pnl"] for t in sub if t["pnl"] <= 0]
        gains = sum(wins)
        pertes = -sum(losses)
        pf = gains / pertes if pertes > 0 else 999.0
        wr = 100.0 * len(wins) / len(sub)
        tot_t = sum(t["pnl"] for t in sub)
        tot_usd = sum(t["pnl"] * TICK_VALUE[t["sym"]] * 3 for t in sub)
        label = sym or "TOTAL"
        print(f"{label:<7} n={len(sub):<5} WR={wr:>5.1f}%  PF={pf:>5.2f}  "
              f"net={tot_t:>+8.0f}t  ({tot_usd:>+9.0f}$ a 3 micros)")


if __name__ == "__main__":
    raise SystemExit(main())
