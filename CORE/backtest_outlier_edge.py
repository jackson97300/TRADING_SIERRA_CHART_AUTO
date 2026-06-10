"""Backtest 50 LOC — l'edge Bot 1 est-il OUTLIER-DRIVEN ?

Verdict agent market-analyst 29/04 : refuser tout fix avant ce test.
Methodologie : pour chaque jour, retirer le top trade et recalculer PF.
Si >50% des jours ont PF < 1.0 sans top trade -> edge outlier-driven.
"""
import json
from pathlib import Path
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")


def load_trades(fp):
    rows = []
    if not fp.exists():
        return pd.DataFrame()
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                try:
                    rows.append(json.loads(s))
                except json.JSONDecodeError:
                    pass
    return pd.DataFrame(rows)


def calc_pf_wr(pnl_series):
    """PF + WR depuis serie pnl_ticks."""
    if len(pnl_series) == 0:
        return 0, 0, 0, 0
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series <= 0].sum())
    pf = wins / losses if losses > 0 else float("inf")
    wr = (pnl_series > 0).mean()
    n = len(pnl_series)
    total = pnl_series.sum()
    return pf, wr, n, total


# Charger TOUS les trades Bot 1 (tous les fichiers *_trades.jsonl sauf databento)
all_trades = []
for fp in sorted(PAPER_DIR.glob("*_trades.jsonl")):
    if "databento" in fp.name:
        continue
    df = load_trades(fp)
    if not df.empty:
        df["_date"] = fp.name[:8]  # YYYYMMDD
        all_trades.append(df)

if not all_trades:
    print("Aucun trade Bot 1")
    raise SystemExit(0)

df_all = pd.concat(all_trades, ignore_index=True)
df_all["_pnl"] = pd.to_numeric(df_all.get("pnl_ticks", 0), errors="coerce").fillna(0)
print(f"Total trades Bot 1 (tous jours) : {len(df_all)}\n")

# Stats par jour
print("="*90)
print("  PF / WR — AVEC vs SANS top trade — par jour")
print("="*90)
print(f"{'Date':<10s} {'N':>3s} {'WR':>5s} {'PF':>7s} {'PnL':>8s} | "
      f"{'TopTrade':>10s} | {'WR_sans':>7s} {'PF_sans':>8s} {'PnL_sans':>9s}")
print("-"*90)

n_jours = 0
n_outlier_driven = 0
results = []
for date, grp in df_all.groupby("_date"):
    pnl = grp["_pnl"]
    pf, wr, n, total = calc_pf_wr(pnl)
    # Retirer le top trade (max positif)
    if pnl.max() > 0:
        top_trade = pnl.max()
        pnl_without = pnl[pnl != pnl.max()]  # retire 1 occurrence du max
        # Si plusieurs trades same max, on retire 1 seul
        idx_max = pnl.idxmax()
        pnl_without = pnl.drop(idx_max)
        pf_w, wr_w, n_w, total_w = calc_pf_wr(pnl_without)
    else:
        top_trade = 0
        pf_w, wr_w, n_w, total_w = pf, wr, n, total

    is_outlier = pf >= 1.0 and pf_w < 1.0
    flag = "🚨 OUTLIER" if is_outlier else "✓"
    print(f"{date:<10s} {n:>3d} {wr*100:>4.0f}% {pf:>7.2f} {total:>+7.0f}t | "
          f"+{top_trade:>+8.0f}t | {wr_w*100:>6.0f}% {pf_w:>8.2f} {total_w:>+8.0f}t  {flag}")
    n_jours += 1
    if is_outlier:
        n_outlier_driven += 1
    results.append({
        "date": date,
        "pf": pf, "pf_sans": pf_w,
        "wr": wr, "wr_sans": wr_w,
        "total": total, "total_sans": total_w,
        "top_trade": top_trade,
        "is_outlier_driven": is_outlier,
    })

# Verdict
print("\n"+"="*90)
print("  VERDICT")
print("="*90)
ratio = n_outlier_driven / n_jours if n_jours else 0
print(f"  Jours outlier-driven : {n_outlier_driven}/{n_jours} = {ratio*100:.0f}%")
if ratio > 0.5:
    print(f"\n  🚨 EDGE OUTLIER-DRIVEN : >50% jours sont sauvés par 1 trade")
    print(f"     → ARRETER paper. Retravailler logique d'entree.")
elif ratio > 0.3:
    print(f"\n  ⚠️  PARTIELLEMENT outlier-driven : {n_outlier_driven} jours")
    print(f"     → ATTENTION mais edge tient sur majorite des jours")
    print(f"     → Continuer paper 30j minimum, monitorer ratio")
else:
    print(f"\n  ✓ EDGE TIENT : <30% jours outlier-driven")
    print(f"     → Continuer paper 30j minimum")
    print(f"     → Aucun code change avant n>=200 trades cumul")

# Stats globales avec/sans top
total_pnl = df_all["_pnl"].sum()
top_trades_per_day = sum(r["top_trade"] for r in results)
total_sans_tops = total_pnl - top_trades_per_day
print(f"\n  Total PnL cumul : {total_pnl:+.0f}t")
print(f"  Total PnL SANS top trade chaque jour : {total_sans_tops:+.0f}t")
print(f"  Contribution outliers : {top_trades_per_day:+.0f}t = {top_trades_per_day/abs(total_pnl)*100:.0f}% de l'absolu")

# Summary
n_total = len(df_all)
total_wins = df_all[df_all["_pnl"] > 0]["_pnl"].sum()
total_losses = abs(df_all[df_all["_pnl"] <= 0]["_pnl"].sum())
pf_all = total_wins / total_losses if total_losses > 0 else 0
wr_all = (df_all["_pnl"] > 0).mean()
print(f"\n  Stats cumul tous jours :")
print(f"    n={n_total}, WR={wr_all*100:.0f}%, PF={pf_all:.2f}, PnL={total_pnl:+.0f}t")

# DSR-style minimal : variance entre jours
pnl_by_day = [r["total"] for r in results]
if len(pnl_by_day) >= 2:
    s = pd.Series(pnl_by_day)
    print(f"\n  Variance PnL inter-jours :")
    print(f"    median {s.median():+.0f}t  |  mean {s.mean():+.0f}t  |  std {s.std():.0f}t")
    print(f"    Si std/|mean| > 1.5 = PnL ne se distingue pas du bruit aleatoire")
    if abs(s.mean()) > 0:
        print(f"    Ratio actuel std/|mean| = {s.std()/abs(s.mean()):.2f}")
