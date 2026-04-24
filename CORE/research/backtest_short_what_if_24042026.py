"""
Backtest Phase 1 BIS - "et si on avait pris les SHORT rejetes par MTF gate ?"

Pour chaque rejection step 6 mtf_insufficient direction=SHORT du 24/04 :
  1. Identifier timestamp + prix NQ au moment du rejet (depuis JSONL DMP)
  2. Calculer SL/TP fictifs SHORT (NQ : SL=20t TP=36t selon CLAUDE.md ML)
  3. Lookforward 120 bars dans JSONL NQ : SL ou TP hit ?
  4. Stats wins/losses/timeout

LIMITES :
  - Slippage = 0 (broker reel aurait + slip)
  - Pas de fill realiste (assume entry au close de la barre du rejet)
  - SL/TP fixes ATR-ratio standard (pas de SLTPEngine murs MQ)
  - 1 jour de data = pas de cross-val
"""
import json
from collections import Counter

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
NQ_F = f"{ROOT}/DATA/NQ/20260424_NQ.jsonl"
REJ_F = f"{ROOT}/LOGS/rejections/rejections_20260424_paper.jsonl"

TICK = 0.25
SL_TICKS = 20  # NQ short SL
TP_TICKS = 36  # NQ short TP (RR 1.8 cf CLAUDE.md)
MAX_BARS = 120  # timeout


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def main():
    nq = sorted(load_jsonl(NQ_F), key=lambda b: b.get("ts", 0))
    rejects = load_jsonl(REJ_F)

    short_rejects = [
        r for r in rejects
        if r.get("reason") == "mtf_insufficient"
        and r.get("direction") == "SHORT"
        and r.get("sym") == "NQ"
    ]
    print(f"=== BACKTEST 'ET SI' SHORT NQ rejetes par MTF gate (24/04) ===")
    print(f"{len(short_rejects)} SHORT rejetes par MTF gate")
    print(f"Hypothese SL={SL_TICKS}t TP={TP_TICKS}t (NQ standard ML)")
    print(f"Timeout 120 bars (2h)")
    print()

    results = []
    for r in short_rejects:
        ts_iso = r["ts"]
        # Convertir ISO en ms
        from datetime import datetime
        ts = datetime.fromisoformat(ts_iso.replace("+00:00", "+00:00"))
        ts_ms = int(ts.timestamp() * 1000)

        # Trouver barre NQ au moment du rejet (premiere barre >= ts)
        entry_bar = None
        idx = None
        for i, b in enumerate(nq):
            bts = b.get("ts", 0)
            if bts >= ts_ms:
                entry_bar = b
                idx = i
                break
        if entry_bar is None:
            continue

        entry_price = entry_bar.get("price", 0)
        if entry_price <= 0:
            continue

        # SHORT : SL = entry + SL_TICKS, TP = entry - TP_TICKS
        sl_px = entry_price + SL_TICKS * TICK
        tp_px = entry_price - TP_TICKS * TICK

        # Lookforward MAX_BARS bars apres entry
        future = nq[idx + 1: idx + 1 + MAX_BARS]
        if not future:
            continue

        outcome = "TIMEOUT"
        exit_px = future[-1].get("price", entry_price)
        bars_held = len(future)
        for j, b in enumerate(future):
            h = b.get("bar_high", b.get("price", 0)) or b.get("price", 0)
            l_ = b.get("bar_low", b.get("price", 0)) or b.get("price", 0)
            # SHORT : SL hit si high >= sl_px, TP hit si low <= tp_px
            sl_hit = h >= sl_px
            tp_hit = l_ <= tp_px
            if sl_hit and tp_hit:
                # Ambiguite intra-barre - on assume worst case (SL d'abord)
                outcome = "SL"
                exit_px = sl_px
                bars_held = j + 1
                break
            if sl_hit:
                outcome = "SL"
                exit_px = sl_px
                bars_held = j + 1
                break
            if tp_hit:
                outcome = "TP"
                exit_px = tp_px
                bars_held = j + 1
                break

        # PnL en ticks (SHORT : +(entry - exit) / TICK)
        pnl_ticks = (entry_price - exit_px) / TICK
        results.append({
            "ts": ts_iso[11:19],
            "entry": entry_price,
            "sl": sl_px,
            "tp": tp_px,
            "exit": exit_px,
            "outcome": outcome,
            "pnl_ticks": round(pnl_ticks, 1),
            "bars_held": bars_held,
            "mtf_bulls": r.get("mtf_bulls"),
            "confidence": r.get("confidence"),
        })

    print(f"Resultats : {len(results)} simulations completes")
    print()

    if not results:
        print("Aucune simulation valide.")
        return

    # Stats
    counts = Counter(r["outcome"] for r in results)
    pnl_total = sum(r["pnl_ticks"] for r in results)
    wins = [r for r in results if r["pnl_ticks"] > 0]
    losses = [r for r in results if r["pnl_ticks"] <= 0]

    print("=== RESULTATS HYPOTHETIQUES ===")
    print(f"  Total trades simules: {len(results)}")
    print(f"  Outcomes: {dict(counts)}")
    print(f"  Wins: {len(wins)} ({len(wins)/len(results)*100:.1f}%)")
    print(f"  Losses: {len(losses)} ({len(losses)/len(results)*100:.1f}%)")
    print(f"  PnL total: {pnl_total:+.0f}t")
    print(f"  PnL moyen: {pnl_total/len(results):+.1f}t/trade")
    if wins and losses:
        win_sum = sum(r["pnl_ticks"] for r in wins)
        loss_sum = sum(abs(r["pnl_ticks"]) for r in losses)
        pf = win_sum / loss_sum if loss_sum else float("inf")
        print(f"  PF: {pf:.2f}")
        print(f"  Avg win: {win_sum/len(wins):+.1f}t")
        print(f"  Avg loss: {-loss_sum/len(losses):+.1f}t")
    print(f"  PnL en USD (paper, 3 micros NQ x $0.50): {pnl_total * 3 * 0.50:+.2f}")
    print()

    print("=== Sample 10 trades simules (debut, milieu, fin) ===")
    for r in results[:5]:
        print(f"  {r['ts']} entry={r['entry']:.2f} SL={r['sl']:.2f} TP={r['tp']:.2f} "
              f"-> exit={r['exit']:.2f} {r['outcome']:7s} pnl={r['pnl_ticks']:+5.0f}t bars={r['bars_held']}")
    print(f"  ... ({len(results)-10} milieu)")
    for r in results[-5:]:
        print(f"  {r['ts']} entry={r['entry']:.2f} SL={r['sl']:.2f} TP={r['tp']:.2f} "
              f"-> exit={r['exit']:.2f} {r['outcome']:7s} pnl={r['pnl_ticks']:+5.0f}t bars={r['bars_held']}")
    print()

    # Comparaison avec les wins/losses du bot reel
    print("=== COMPARAISON ===")
    print(f"  Bot reel (LONG only): 14 trades, +360t = +$540")
    print(f"  Si SHORT pris en plus: {pnl_total:+.0f}t = {pnl_total*1.5:+.2f}$ supplementaires")
    print(f"  Total combine: {360 + pnl_total:+.0f}t = ${(360 + pnl_total)*1.5:+.2f}")
    print()

    # Verdict
    print("=== VERDICT ===")
    if pnl_total > 0:
        print(f"  Les SHORT auraient ete GAGNANTS (+{pnl_total:.0f}t).")
        print(f"  Le gate MTF a probablement BLOQUE des trades qui auraient ete profitables.")
        print(f"  ATTENTION : N={len(results)} = sample biaise (1 jour, pas de slippage realiste).")
    else:
        print(f"  Les SHORT auraient ete PERDANTS ({pnl_total:+.0f}t).")
        print(f"  Le gate MTF a JUSTEMENT BLOQUE des trades contre-trend perdants.")
        print(f"  Confirme : le gate est utile aujourd'hui (proteccion contre-trend).")


if __name__ == "__main__":
    main()
