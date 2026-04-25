"""
Analyse BN events (Battle Navale footprint) x 18 trades 24/04.

Pour chaque trade : extract BN features AT ENTRY + aggrege BN events sur les
5 barres precedant l'entry (contexte immediat). Cross-tab wins vs losses.

Features BN analysees :
- bn_color_up / bn_color_dn     : bar colorisee bull/bear dans footprint
- bn_long_up / bn_long_dn       : long bar up/down detectee
- bn_long_up_bar / bn_long_dn_bar : persistent (Extension Lines)
- bn_long_up_dn / bn_long_dn_up : Extension Line transition (reversal)
- bn_absorb_bid / bn_absorb_ask : absorption bid/ask (cluster imbalance)
- bn_score_raw / bn_score_bull / bn_score_bear

Output : console tableau pour analyse Jackson.
"""
import json
from collections import defaultdict
from statistics import mean, median

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
SNAPS_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_snapshots.jsonl"
TRADES_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_trades.jsonl"
NQ_F = f"{ROOT}/DATA/NQ/20260424_NQ.jsonl"

# Features BN a extraire (binary 0/1 pour la plupart)
BN_FEATURES = [
    "bn_color_up", "bn_color_dn",
    "bn_long_up", "bn_long_dn",
    "bn_long_up_bar", "bn_long_dn_bar",
    "bn_long_up_dn", "bn_long_dn_up",
    "bn_absorb_bid", "bn_absorb_ask",
    "bn_pressure_bid", "bn_pressure_ask",
    "bn_score_raw", "bn_score_bull", "bn_score_bear",
    "bn_volume_up", "bn_volume_dn",
    # Extension counts (persistent state)
    "dist_ext_long_up_bar", "dist_ext_long_dn_bar",
    "dist_ext_color_up", "dist_ext_color_dn",
    "dist_ext_edge_buy", "dist_ext_edge_sell",
    "dist_ext_absorb_bid", "dist_ext_absorb_ask",
]

# Window contexte : combien de barres avant entry on regarde
CONTEXT_BARS_BEFORE = 5


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def main():
    snaps = load_jsonl(SNAPS_F)
    trades = load_jsonl(TRADES_F)
    nq = sorted(load_jsonl(NQ_F), key=lambda b: b.get("ts", 0))
    trade_by_id = {t["trade_id"]: t for t in trades}

    print("=" * 110)
    print("ANALYSE BN EVENTS x 18 TRADES 24/04 (BN = Battle Navale footprint)")
    print("=" * 110)
    print(f"Contexte : {CONTEXT_BARS_BEFORE} barres avant entry + bar entry")
    print()

    rows = []
    for s in snaps:
        t = trade_by_id.get(s["trade_id"])
        if not t:
            continue
        db = s.get("dmp_bar", {}) or {}
        entry_ts = db.get("ts")
        if not entry_ts:
            continue
        # Extract entry bar BN
        bn_entry = {k: db.get(k, 0) for k in BN_FEATURES}
        # Aggregate 5 bars before entry
        try:
            idx = next(i for i, b in enumerate(nq) if b.get("ts") == entry_ts)
        except StopIteration:
            idx = None
        bn_context_sum = {k: 0 for k in BN_FEATURES}
        bn_context_any = {k: 0 for k in BN_FEATURES}  # any bar with event
        if idx is not None:
            prev_bars = nq[max(0, idx - CONTEXT_BARS_BEFORE): idx]
            for b in prev_bars:
                for k in BN_FEATURES:
                    v = b.get(k, 0) or 0
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        v = 0
                    bn_context_sum[k] += v
                    if v != 0:
                        bn_context_any[k] = 1
        rows.append({
            "trade_id": s["trade_id"],
            "time": s["entry_time"][11:19],
            "dir": s["direction"],
            "outcome": t["outcome"],
            "pnl": t["pnl_ticks"],
            "mae": t["mae"],
            "mfe": t["mfe"],
            "bn_entry": bn_entry,
            "bn_context_sum": bn_context_sum,
            "bn_context_any": bn_context_any,
        })

    wins = [r for r in rows if r["pnl"] > 0]
    losses = [r for r in rows if r["pnl"] <= 0]
    print(f"Wins: {len(wins)}  |  Losses: {len(losses)}")
    print()

    # ============ Section 1 : BN AT ENTRY ============
    print("=" * 110)
    print("SECTION 1 : BN FEATURES AU MOMENT DE L'ENTRY")
    print("=" * 110)
    print(f"{'feature':<25}{'wins (n=' + str(len(wins)) + ')':<25}{'losses (n=' + str(len(losses)) + ')':<25}{'interpretation':<30}")
    print("-" * 110)
    for k in BN_FEATURES:
        # Wins stats
        w_vals = [r["bn_entry"][k] for r in wins]
        l_vals = [r["bn_entry"][k] for r in losses]
        # Binary vs numeric : si max <= 1, binaire
        all_vals = w_vals + l_vals
        is_binary = all(v in (0, 1, True, False, None) for v in all_vals)
        if is_binary:
            w_pct = sum(1 for v in w_vals if v) / max(1, len(w_vals)) * 100
            l_pct = sum(1 for v in l_vals if v) / max(1, len(l_vals)) * 100
            w_str = f"{sum(1 for v in w_vals if v)}/{len(w_vals)} ({w_pct:.0f}%)"
            l_str = f"{sum(1 for v in l_vals if v)}/{len(l_vals)} ({l_pct:.0f}%)"
            diff = w_pct - l_pct
            flag = "  <-- pattern" if abs(diff) >= 20 else ""
        else:
            try:
                w_med = median(w_vals) if w_vals else 0
                l_med = median(l_vals) if l_vals else 0
                w_str = f"med={w_med:+.2f}"
                l_str = f"med={l_med:+.2f}"
                diff = w_med - l_med
                flag = "  <-- pattern" if abs(diff) > 0.3 else ""
            except Exception:
                w_str = "-"; l_str = "-"; flag = ""
        print(f"{k:<25}{w_str:<25}{l_str:<25}{flag}")

    # ============ Section 2 : BN CONTEXT (5 bars before) ============
    print()
    print("=" * 110)
    print(f"SECTION 2 : BN EVENTS DANS LES {CONTEXT_BARS_BEFORE} BARRES AVANT ENTRY (count total)")
    print("=" * 110)
    print(f"{'feature':<25}{'wins avg/trade':<22}{'losses avg/trade':<22}{'gap':<10}{'interpretation':<30}")
    print("-" * 110)
    for k in BN_FEATURES:
        w_sum = [r["bn_context_sum"][k] for r in wins]
        l_sum = [r["bn_context_sum"][k] for r in losses]
        if not w_sum or not l_sum:
            continue
        w_avg = mean(w_sum) if w_sum else 0
        l_avg = mean(l_sum) if l_sum else 0
        gap = w_avg - l_avg
        flag = ""
        if abs(gap) > 0.5:
            if gap > 0:
                flag = "  <-- MORE chez wins"
            else:
                flag = "  <-- MORE chez losses"
        print(f"{k:<25}{w_avg:<10.2f}            {l_avg:<10.2f}            {gap:+.2f}     {flag}")

    # ============ Section 3 : DETAIL PAR TRADE ============
    print()
    print("=" * 110)
    print("SECTION 3 : DETAIL PAR TRADE (BN events entry + sum 5 bars before)")
    print("=" * 110)
    headers = ["time", "dir", "out", "pnl"] + [k.replace("bn_", "") for k in [
        "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
        "bn_absorb_bid", "bn_absorb_ask", "bn_score_raw",
    ]]
    # Header ligne
    print(f"{'time':<10}{'dir':<5}{'out':<8}{'pnl':<7} | entry:{'color_up/dn':<14}{'long_up/dn':<14}{'absorb_bid/ask':<17}{'score':<7} | ctx5:{'col_u':<7}{'col_d':<7}{'lng_u':<7}{'lng_d':<7}")
    print("-" * 130)
    for r in rows:
        e = r["bn_entry"]
        c = r["bn_context_sum"]
        line = f"{r['time']:<10}{r['dir']:<5}{r['outcome']:<8}{r['pnl']:+5.0f}t | "
        line += f"{int(e['bn_color_up'])}/{int(e['bn_color_dn']):<10} "
        line += f"{int(e['bn_long_up'])}/{int(e['bn_long_dn']):<10} "
        line += f"{int(e['bn_absorb_bid'])}/{int(e['bn_absorb_ask']):<13} "
        line += f"{e['bn_score_raw']:+.1f}   | "
        line += f"{int(c['bn_color_up']):<6}{int(c['bn_color_dn']):<6}"
        line += f"{int(c['bn_long_up']):<6}{int(c['bn_long_dn']):<6}"
        print(line)

    # ============ Section 4 : PATTERN AUTOMATIQUE WIN vs LOSS ============
    print()
    print("=" * 110)
    print("SECTION 4 : REGLES BN CANDIDATES (filtres potentiels a tester)")
    print("=" * 110)
    # Test quelques combinaisons
    def test_rule(name, fn):
        match = [r for r in rows if fn(r)]
        if not match:
            return None
        w = sum(1 for r in match if r["pnl"] > 0)
        l = len(match) - w
        pnl = sum(r["pnl"] for r in match)
        wr = w / len(match) * 100
        return (name, len(match), w, l, pnl, wr)

    candidates = [
        ("bn_color_up at entry (LONG)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_color_up"] == 1),
        ("bn_long_up at entry (LONG)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_long_up"] == 1),
        ("bn_absorb_bid at entry (LONG=bullish)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_absorb_bid"] == 1),
        ("bn_absorb_ask at entry (LONG=warning)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_absorb_ask"] == 1),
        ("bn_score_raw > 0 at entry (LONG)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_score_raw"] > 0),
        ("bn_score_raw < 0 at entry (LONG)", lambda r: r["dir"] == "LONG" and r["bn_entry"]["bn_score_raw"] < 0),
        ("Ctx: bn_color_up>=2 in last 5 bars", lambda r: r["bn_context_sum"]["bn_color_up"] >= 2),
        ("Ctx: bn_color_dn>=2 in last 5 bars", lambda r: r["bn_context_sum"]["bn_color_dn"] >= 2),
        ("Ctx: bn_long_up>=1 in last 5 bars", lambda r: r["bn_context_sum"]["bn_long_up"] >= 1),
        ("Ctx: bn_long_dn>=1 in last 5 bars (warning LONG)", lambda r: r["dir"] == "LONG" and r["bn_context_sum"]["bn_long_dn"] >= 1),
        ("Ctx: bn_absorb_bid>=1 (support confirm LONG)", lambda r: r["dir"] == "LONG" and r["bn_context_sum"]["bn_absorb_bid"] >= 1),
        ("Ctx: bn_absorb_ask>=1 (warning LONG)", lambda r: r["dir"] == "LONG" and r["bn_context_sum"]["bn_absorb_ask"] >= 1),
    ]
    print(f"{'regle':<55}{'n':<6}{'wins':<6}{'losses':<8}{'pnl':<8}{'WR':<6}")
    print("-" * 95)
    for label, fn in candidates:
        res = test_rule(label, fn)
        if res is None:
            continue
        name, n, w, l, pnl, wr = res
        flag = ""
        if n >= 4:  # min sample pour flagger
            if wr >= 70:
                flag = "  <-- EDGE ?"
            elif wr <= 30:
                flag = "  <-- WARNING"
        print(f"{label:<55}{n:<6}{w:<6}{l:<8}{pnl:+5.0f}t  {wr:.0f}%{flag}")

    print()
    print("=" * 110)
    print("CAVEAT STATISTIQUE : N=18 trades = ECHANTILLON MICRO. Patterns = hypotheses.")
    print("Valider sur N=100+ avant de coder un gate. Utile pour intuition marche.")


if __name__ == "__main__":
    main()
