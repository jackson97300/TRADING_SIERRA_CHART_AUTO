"""
Backtest Phase 1 - sanity check regle regime + recherche pattern losses.

Inputs (read-only) :
- DATA/PAPER_TRADES/20260424_snapshots.jsonl (13 snapshots V2 ML-ready avec dmp_bar)
- DATA/PAPER_TRADES/20260424_trades.jsonl    (13 trades avec PnL/MAE/outcome)
- LOGS/rejections/rejections_20260424_paper.jsonl (~150 rejections step 6)

Outputs :
- Verdict regle "TREND aligne keep / TREND contre kill / RANGE keep" sur 13 trades
- Comparaison features 8 wins vs 5 losses
- Pattern candidat pour recalifier les losses
"""
import json
from collections import defaultdict
from statistics import median

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
SNAPS_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_snapshots.jsonl"
TRADES_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_trades.jsonl"


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def classify_regime(db: dict, mtf_bulls: int, mtf_bears: int) -> str:
    atr = abs(db.get("dist_vwap_d_atr") or 0)
    mtf_agree = max(mtf_bulls, mtf_bears)
    if atr > 1.5 and mtf_agree >= 3:
        return "TREND"
    if atr < 0.5 or mtf_agree < 3:
        return "RANGE"
    return "TRANSITION"


def mtf_aligned(direction: str, mtf_bulls: int, mtf_bears: int) -> bool:
    if direction == "LONG":
        return mtf_bulls >= 3
    return mtf_bears >= 3


def main():
    snaps = load_jsonl(SNAPS_F)
    trades = load_jsonl(TRADES_F)
    trade_by_id = {t["trade_id"]: t for t in trades}

    print("=" * 100)
    print("PHASE 1 - BACKTEST REGLE REGIME-AWARE sur 24/04 (13 trades)")
    print("=" * 100)

    rows = []
    for s in snaps:
        t = trade_by_id.get(s["trade_id"])
        if not t:
            continue
        db = s.get("dmp_bar") or {}
        regime = classify_regime(db, s.get("mtf_bulls", 0), s.get("mtf_bears", 0))
        aligned = mtf_aligned(s["direction"], s.get("mtf_bulls", 0), s.get("mtf_bears", 0))
        rows.append({
            "trade_id": s["trade_id"],
            "time": s["entry_time"][11:19],
            "dir": s["direction"],
            "outcome": t["outcome"],
            "pnl": t["pnl_ticks"],
            "mae": t["mae"],
            "mfe": t["mfe"],
            "regime": regime,
            "mtf_aligned": aligned,
            "mtf_bulls": s["mtf_bulls"],
            "mtf_bears": s["mtf_bears"],
            "conf": s["confidence"],
            "conseil": s.get("conseil_action"),
            "atr_14m": db.get("atr_14m"),
            "dist_vwap_atr": db.get("dist_vwap_d_atr"),
            "momentum_5b": db.get("momentum_5b"),
            "range_pos": db.get("range_pos"),
            "session": db.get("session_id"),
            "rvol_1m": db.get("rvol_1m"),
            "vix": db.get("vix"),
            "sl_tier": t.get("sl_tier"),
            "sl_wall": t.get("sl_wall"),
        })

    print(f"\n{len(rows)} trades analyses\n")

    print("-" * 110)
    hdr = f"{'time':<10}{'dir':<5}{'out':<8}{'pnl':<7}{'regime':<12}{'align':<7}{'mtf':<6}"
    hdr += f"{'conf':<6}{'atr':<6}{'dvwap':<8}{'mom5':<7}{'rgpos':<8}{'sess':<8}"
    print(hdr)
    print("-" * 110)
    for r in rows:
        mtf_s = f"{r['mtf_bulls']}/{r['mtf_bears']}"
        align_s = "Y" if r["mtf_aligned"] else "N"
        line = f"{r['time']:<10}{r['dir']:<5}{r['outcome']:<8}{r['pnl']:+5.0f}t "
        line += f"{r['regime']:<12}{align_s:<7}{mtf_s:<6}{r['conf']:.2f}  "
        line += f"{r['atr_14m']:5.1f}{r['dist_vwap_atr']:+7.2f}{r['momentum_5b']:+6.1f}  "
        line += f"{r['range_pos']:5.0f}%  {r['session']:<8}"
        print(line)

    print()
    print("=" * 100)
    print("REGLE A : TREND aligne keep / TREND contre kill / RANGE keep / TRANSITION keep")
    print("=" * 100)
    keep, kill = [], []
    for r in rows:
        if r["regime"] == "TREND" and not r["mtf_aligned"]:
            kill.append(r)
        else:
            keep.append(r)
    wins_kept = [r for r in keep if r["pnl"] > 0]
    losses_kept = [r for r in keep if r["pnl"] <= 0]
    wins_killed = [r for r in kill if r["pnl"] > 0]
    losses_killed = [r for r in kill if r["pnl"] <= 0]
    print(f"  GARDES ({len(keep)}/13) : wins={len(wins_kept)} losses={len(losses_kept)} "
          f"pnl={sum(r['pnl'] for r in keep):+.0f}t")
    print(f"  KILLED ({len(kill)}/13) : wins={len(wins_killed)} losses={len(losses_killed)} "
          f"pnl={sum(r['pnl'] for r in kill):+.0f}t (positif si edge gagne)")
    if keep:
        wr_keep = len(wins_kept) / len(keep) * 100
        loss_sum = sum(abs(r["pnl"]) for r in losses_kept) or 1
        win_sum = sum(r["pnl"] for r in wins_kept) or 0
        pf_keep = win_sum / loss_sum if loss_sum else float("inf")
        print(f"  WR garde : {wr_keep:.1f}%   PF garde : {pf_keep:.2f}")
        print(f"  Baseline : WR 61.5%, PF 3.12")

    print()
    print("=" * 100)
    print("ANALYSE WINS vs LOSSES - recherche pattern recalification")
    print("=" * 100)
    wins = [r for r in rows if r["pnl"] > 0]
    losses = [r for r in rows if r["pnl"] <= 0]
    print(f"  {len(wins)} wins vs {len(losses)} losses\n")

    features_to_compare = [
        ("conf", "Confidence"),
        ("atr_14m", "ATR 14m (ticks)"),
        ("dist_vwap_atr", "Dist VWAP ATR"),
        ("momentum_5b", "Momentum 5b"),
        ("range_pos", "Range pos %"),
        ("rvol_1m", "RVOL 1m"),
        ("mtf_bulls", "MTF bulls"),
        ("mae", "MAE ticks"),
        ("vix", "VIX"),
    ]
    print(f"{'feature':<22}{'WINS med':<14}{'LOSSES med':<14}{'gap':<10}")
    print("-" * 65)
    for k, lbl in features_to_compare:
        w = [r[k] for r in wins if r.get(k) is not None]
        l_ = [r[k] for r in losses if r.get(k) is not None]
        if not w or not l_:
            continue
        mw, ml = median(w), median(l_)
        gap = mw - ml
        flag = "  <- DIFF" if abs(gap) > 0.3 * max(abs(mw), abs(ml), 0.01) else ""
        print(f"{lbl:<22}{mw:>11.2f}   {ml:>11.2f}   {gap:>+7.2f}{flag}")

    print()
    sl_tier_w = defaultdict(int)
    sl_tier_l = defaultdict(int)
    for r in wins:
        sl_tier_w[r["sl_tier"]] += 1
    for r in losses:
        sl_tier_l[r["sl_tier"]] += 1
    print(f"SL Tier wins: {dict(sl_tier_w)}  losses: {dict(sl_tier_l)}")

    sess_w = defaultdict(int)
    sess_l = defaultdict(int)
    for r in wins:
        sess_w[r["session"]] += 1
    for r in losses:
        sess_l[r["session"]] += 1
    print(f"Session wins: {dict(sess_w)}  losses: {dict(sess_l)}")

    conf_w = defaultdict(int)
    conf_l = defaultdict(int)
    for r in wins:
        conf_w[r["conf"]] += 1
    for r in losses:
        conf_l[r["conf"]] += 1
    print(f"Conf wins: {dict(conf_w)}  losses: {dict(conf_l)}")

    print()
    print("DETAIL 5 LOSSES :")
    for r in losses:
        line = f"  {r['time']} {r['dir']} pnl={r['pnl']:+.0f}t MAE={r['mae']:+.0f} "
        line += f"regime={r['regime']} mtf={r['mtf_bulls']}/{r['mtf_bears']} conf={r['conf']} "
        line += f"dvwap={r['dist_vwap_atr']:+.2f} mom5={r['momentum_5b']:+.1f} "
        line += f"rgpos={r['range_pos']:.0f}% atr={r['atr_14m']:.1f} "
        line += f"sl_tier={r['sl_tier']} wall={r['sl_wall']}"
        print(line)

    print()
    print("DETAIL 8 WINS :")
    for r in wins:
        line = f"  {r['time']} {r['dir']} pnl={r['pnl']:+.0f}t MAE={r['mae']:+.0f} "
        line += f"regime={r['regime']} mtf={r['mtf_bulls']}/{r['mtf_bears']} conf={r['conf']} "
        line += f"dvwap={r['dist_vwap_atr']:+.2f} mom5={r['momentum_5b']:+.1f} "
        line += f"rgpos={r['range_pos']:.0f}% atr={r['atr_14m']:.1f} "
        line += f"sl_tier={r['sl_tier']} wall={r['sl_wall']}"
        print(line)

    print()
    print("=" * 100)
    print("REGLES CANDIDATES - filtres qui distinguent wins de losses")
    print("=" * 100)
    candidates = [
        ("conf == 0.40 (mode)", lambda r: r["conf"] == 0.40),
        ("conf == 0.52", lambda r: r["conf"] == 0.52),
        ("range_pos > 80% (top range)", lambda r: r["range_pos"] > 80),
        ("range_pos < 20% (bottom range)", lambda r: r["range_pos"] < 20),
        ("dvwap < -1.5 (loin sous VWAP)", lambda r: r["dist_vwap_atr"] < -1.5),
        ("dvwap > -0.5 (proche VWAP)", lambda r: r["dist_vwap_atr"] > -0.5),
        ("momentum_5b < -2 (bear momentum)", lambda r: r["momentum_5b"] < -2),
        ("momentum_5b > 0 (bull momentum)", lambda r: r["momentum_5b"] > 0),
        ("atr_14m < 22 (vol basse)", lambda r: r["atr_14m"] < 22),
        ("atr_14m > 26 (vol haute)", lambda r: r["atr_14m"] > 26),
        ("sl_tier == 1 (mur primaire)", lambda r: r["sl_tier"] == 1),
        ("sl_tier == 2 (fallback swing)", lambda r: r["sl_tier"] == 2),
        ("session Asia", lambda r: r["session"] == "Asia"),
        ("session London", lambda r: r["session"] == "London"),
        ("MAE = 0 (entry parfaite)", lambda r: r["mae"] == 0),
        ("MFE > 30t (objectif atteint)", lambda r: r["mfe"] > 30),
    ]
    print(f"{'regle':<42}{'matches':<11}{'wins':<7}{'losses':<8}{'pnl':<10}{'WR':<6}")
    print("-" * 84)
    for label, fn in candidates:
        match = [r for r in rows if fn(r)]
        if not match:
            continue
        w_n = sum(1 for r in match if r["pnl"] > 0)
        l_n = sum(1 for r in match if r["pnl"] <= 0)
        pnl = sum(r["pnl"] for r in match)
        wr = w_n / len(match) * 100
        print(f"{label:<42}{len(match):>5}/13   {w_n:>4}   {l_n:>4}    {pnl:+5.0f}t   {wr:>4.0f}%")

    print()
    print("=" * 100)
    print("VERDICT")
    print("=" * 100)
    print("N=13 = MICRO-ECHANTILLON. Tout pattern = HYPOTHESE A VALIDER N=100+.")
    print("Cette analyse = sanity check + idees a tester en backtest serieux.")


if __name__ == "__main__":
    main()
