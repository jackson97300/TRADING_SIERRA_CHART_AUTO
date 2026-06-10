"""Audit consolide Bot 2 (databento_paper_trader) — diagnostic 30/04/2026.

Jackson : "Bot 2 est casse, analyse les logs, les biais."
"""
import json
import glob
import os
from collections import Counter

ROOT = "C:/TRADING_SIERRA_CHART_AUTO"
PAPER = f"{ROOT}/DATA/PAPER_TRADES"

# 1. Charger tous les trades Bot 2
files = sorted(
    glob.glob(f"{PAPER}/*databento*trades.jsonl"),
    key=os.path.getmtime,
    reverse=True,
)
all_trades = []
for f in files[:10]:
    fname = os.path.basename(f)
    for line in open(f, encoding="utf-8"):
        if line.strip():
            try:
                t = json.loads(line)
                t["_file"] = fname
                all_trades.append(t)
            except Exception:
                pass

print(f"=== {len(all_trades)} trades Bot 2 charges depuis {len(files)} fichiers ===\n")
if not all_trades:
    print("Aucun trade.")
    raise SystemExit(0)

# 2. Outcome breakdown
tp_n = sum(1 for t in all_trades if t.get("outcome") == "TP")
sl_n = sum(1 for t in all_trades if t.get("outcome") == "SL")
other = len(all_trades) - tp_n - sl_n
pnl_t = sum(t.get("pnl_ticks", 0) for t in all_trades)
pnl_u = sum(t.get("pnl_usd", 0) for t in all_trades)
print(f"TP : {tp_n} / SL : {sl_n} / autre : {other}")
print(f"WR : {tp_n / max(len(all_trades),1) * 100:.1f}%")
print(f"PnL total : {pnl_t:+.0f}t  /  ${pnl_u:+.2f}")
print()

# 3. Direction breakdown (= confirme PROP A market-analyst)
print("=== Direction breakdown ===")
for d in ("LONG", "SHORT"):
    sub = [t for t in all_trades if t.get("direction") == d]
    if not sub:
        continue
    sub_tp = sum(1 for t in sub if t.get("outcome") == "TP")
    sub_pnl = sum(t.get("pnl_ticks", 0) for t in sub)
    sub_pnl_u = sum(t.get("pnl_usd", 0) for t in sub)
    wr = sub_tp / len(sub) * 100
    print(f"{d:6s}: n={len(sub):3d}  WR={wr:5.1f}%  PnL={sub_pnl:+.0f}t  ${sub_pnl_u:+.0f}")
print()

# 4. Symbol breakdown
print("=== Symbol breakdown ===")
for sym in ("ES", "NQ"):
    sub = [t for t in all_trades if t.get("symbol") == sym]
    if not sub:
        continue
    sub_tp = sum(1 for t in sub if t.get("outcome") == "TP")
    sub_pnl = sum(t.get("pnl_ticks", 0) for t in sub)
    sub_pnl_u = sum(t.get("pnl_usd", 0) for t in sub)
    wr = sub_tp / len(sub) * 100
    print(f"{sym}: n={len(sub):3d}  WR={wr:5.1f}%  PnL={sub_pnl:+.0f}t  ${sub_pnl_u:+.0f}")
print()

# 5. Bias regime au moment entry (depuis exit_context si dispo, sinon checks)
print("=== Bias regime / conseil action ===")
bias_counter = Counter()
conseil_counter = Counter()
for t in all_trades:
    ec = t.get("exit_context") or {}
    bias = ec.get("regime_bias") or "UNKNOWN"
    conseil = ec.get("conseil_action") or "UNKNOWN"
    bias_counter[bias] += 1
    conseil_counter[conseil] += 1
print("regime_bias:")
for k, v in bias_counter.most_common():
    print(f"  {k:15s}: {v}")
print("conseil_action:")
for k, v in conseil_counter.most_common():
    print(f"  {k:15s}: {v}")
print()

# 6. MFE / MAE distribution
print("=== MFE / MAE distribution ===")
mfe_list = [t.get("mfe", 0) for t in all_trades if t.get("mfe") is not None]
mae_list = [t.get("mae", 0) for t in all_trades if t.get("mae") is not None]
if mfe_list:
    mfe_sorted = sorted(mfe_list)
    n = len(mfe_sorted)
    print(f"MFE : median={mfe_sorted[n//2]:+.1f}t  mean={sum(mfe_list)/n:+.1f}t  max={max(mfe_list):+.0f}t")
    print(f"      p25={mfe_sorted[n//4]:+.1f}  p75={mfe_sorted[3*n//4]:+.1f}")
if mae_list:
    mae_sorted = sorted(mae_list)
    n = len(mae_sorted)
    print(f"MAE : median={mae_sorted[n//2]:+.1f}t  mean={sum(mae_list)/n:+.1f}t  min={min(mae_list):+.0f}t")
print()

# 7. % "rendu" — MFE > 0 mais exit SL
print("=== Pattern 'rendu' (MFE >= 20t mais exit SL) ===")
rendu = []
for t in all_trades:
    mfe = t.get("mfe") or 0
    pnl = t.get("pnl_ticks") or 0
    if mfe >= 20 and pnl < 0:
        rendu.append(t)
n_rendu = len(rendu)
n_sl = sum(1 for t in all_trades if t.get("outcome") == "SL")
print(f"Trades 'rendu' : {n_rendu}/{len(all_trades)} = {n_rendu/max(len(all_trades),1)*100:.0f}%")
print(f"Trades 'rendu' parmi SL : {n_rendu}/{n_sl} = {n_rendu/max(n_sl,1)*100:.0f}%")
if rendu:
    rendu_pnl = sum(t.get("pnl_ticks", 0) for t in rendu)
    rendu_mfe = sum(t.get("mfe", 0) for t in rendu)
    print(f"  → cumul rendu : MFE atteint {rendu_mfe:+.0f}t  PnL realise {rendu_pnl:+.0f}t  (perdu {rendu_mfe - rendu_pnl:+.0f}t)")
print()

# 8. Score consensus distribution (bull_pts / bear_pts au moment entry)
print("=== Score consensus distribution au moment entry ===")
bull_pts_list = []
bear_pts_list = []
for t in all_trades:
    # Tente de retrouver bull/bear depuis active_positions snapshot
    bp = t.get("bull_pts")
    br = t.get("bear_pts")
    if bp is None and t.get("checks"):
        # reconstruire approximativement depuis checks
        pass
    if bp is not None:
        bull_pts_list.append(bp)
    if br is not None:
        bear_pts_list.append(br)
if bull_pts_list:
    print(f"bull_pts : median={sorted(bull_pts_list)[len(bull_pts_list)//2]}  mean={sum(bull_pts_list)/len(bull_pts_list):.1f}")
if bear_pts_list:
    print(f"bear_pts : median={sorted(bear_pts_list)[len(bear_pts_list)//2]}  mean={sum(bear_pts_list)/len(bear_pts_list):.1f}")

# 9. Top 5 trades les plus perdants (anomalies)
print()
print("=== Top 5 trades les + perdants (analyse pattern) ===")
worst = sorted(all_trades, key=lambda t: t.get("pnl_ticks", 0))[:5]
for t in worst:
    direction = t.get("direction", "?")
    sym = t.get("symbol", "?")
    pnl = t.get("pnl_ticks", 0)
    mfe = t.get("mfe", 0)
    mae = t.get("mae", 0)
    bull = t.get("bull_pts", "?")
    bear = t.get("bear_pts", "?")
    entry_t = t.get("entry_time", "?")[:19]
    print(f"  {sym} {direction:5s} entry={entry_t} pnl={pnl:+.0f}t mfe={mfe:+.0f} mae={mae:+.0f} bull={bull}/bear={bear}")

# 10. Top 5 trades les plus gagnants
print()
print("=== Top 5 trades les + gagnants ===")
best = sorted(all_trades, key=lambda t: t.get("pnl_ticks", 0), reverse=True)[:5]
for t in best:
    direction = t.get("direction", "?")
    sym = t.get("symbol", "?")
    pnl = t.get("pnl_ticks", 0)
    mfe = t.get("mfe", 0)
    bull = t.get("bull_pts", "?")
    bear = t.get("bear_pts", "?")
    entry_t = t.get("entry_time", "?")[:19]
    print(f"  {sym} {direction:5s} entry={entry_t} pnl={pnl:+.0f}t mfe={mfe:+.0f} bull={bull}/bear={bear}")
