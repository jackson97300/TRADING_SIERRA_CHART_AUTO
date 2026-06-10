"""Audit slippage entry/exit Bot 1 vs Bot 2 sur session 29/04.

Question : -43t fill ES Bot 2 vs SL -20t theorique = 23t slippage.
Pattern Sim2 anormal ou observe aussi sur Sim3 ?
"""
import json
from pathlib import Path
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")
TICK_SIZE = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}


def load(fp):
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


def compute_slippage(df, label):
    print(f"\n{'='*80}")
    print(f"  SLIPPAGE — {label}")
    print(f"{'='*80}")
    if df.empty:
        print("  no trades")
        return

    rows = []
    for _, t in df.iterrows():
        sym = t.get("symbol", "ES")
        direction = t.get("direction", t.get("side", ""))
        outcome = t.get("outcome", "?")
        entry = float(t.get("entry_price", 0) or 0)
        exit_p = float(t.get("exit_price", 0) or 0)
        pnl_t = float(t.get("pnl_ticks", 0) or 0)
        sl_ticks = pd.to_numeric(t.get("sl_ticks"), errors="coerce")
        tp_ticks = pd.to_numeric(t.get("tp_ticks"), errors="coerce")
        if pd.isna(sl_ticks) or sl_ticks == 0:
            continue
        if pd.isna(tp_ticks) or tp_ticks == 0:
            tp_ticks = 0
        # Calcul slippage selon outcome
        # Pour SL : pnl theorique = -sl_ticks. Slippage = -pnl_t - sl_ticks
        # Pour TP : pnl theorique = +tp_ticks. Slippage = tp_ticks - pnl_t
        if outcome == "SL":
            theoretical = -float(sl_ticks)
            slippage = pnl_t - theoretical  # negatif si plus mauvais que prevu
        elif outcome == "TP":
            theoretical = float(tp_ticks)
            slippage = pnl_t - theoretical  # negatif si fill avant TP
        else:
            continue
        rows.append({
            "time": str(t.get("entry_time", ""))[11:19],
            "sym": sym,
            "dir": direction,
            "outcome": outcome,
            "entry": entry,
            "exit": exit_p,
            "pnl_t": pnl_t,
            "theo_t": theoretical,
            "slip_t": slippage,
            "slip_$": slippage * TICK_VALUE.get(sym, 1) * 3,
        })

    if not rows:
        print("  Aucun TP/SL avec ticks renseignes")
        return

    sl_df = pd.DataFrame(rows)
    sls = sl_df[sl_df["outcome"] == "SL"]
    tps = sl_df[sl_df["outcome"] == "TP"]
    print(f"\n  SL events : {len(sls)}")
    if len(sls) > 0:
        print(f"    Slippage median : {sls['slip_t'].median():+.1f}t")
        print(f"    Slippage moyen  : {sls['slip_t'].mean():+.1f}t")
        print(f"    Slippage max    : {sls['slip_t'].min():+.1f}t (le pire)")
        print(f"    Total slip $    : ${sls['slip_$'].sum():+.2f}")
    print(f"\n  TP events : {len(tps)}")
    if len(tps) > 0:
        print(f"    Slippage median : {tps['slip_t'].median():+.1f}t")
        print(f"    Slippage moyen  : {tps['slip_t'].mean():+.1f}t")

    # Top worst SL
    if len(sls) > 0:
        worst = sls.nsmallest(min(5, len(sls)), "slip_t")
        print(f"\n  Pire slippage SL :")
        print(f"  {'Time':<10s} {'Sym':<3s} {'Dir':<6s} {'Entry':>9s} {'Exit':>9s} {'PnL_t':>6s} {'Theo':>6s} {'Slip':>6s} {'Slip$':>9s}")
        for _, r in worst.iterrows():
            print(f"  {r['time']:<10s} {r['sym']:<3s} {r['dir']:<6s} {r['entry']:>9.2f} {r['exit']:>9.2f} "
                  f"{r['pnl_t']:>+6.0f} {r['theo_t']:>+6.0f} {r['slip_t']:>+6.0f}t {r['slip_$']:>+8.2f}")


# Bot 1 + Bot 2
df1 = load(PAPER_DIR / "20260429_trades.jsonl")
df2 = load(PAPER_DIR / "20260429_databento_trades.jsonl")

# Bot 2 utilise sl_ticks (déjà ticks) et bot 1 aussi mais nom different
# Vérification names cols
if not df1.empty:
    sample1 = df1.iloc[0]
    print(f"BOT 1 cols sl/tp: sl_ticks={sample1.get('sl_ticks', 'MISSING')} tp_ticks={sample1.get('tp_ticks', 'MISSING')}")
if not df2.empty:
    sample2 = df2.iloc[0]
    print(f"BOT 2 cols sl/tp: sl_ticks={sample2.get('sl_ticks', 'MISSING')} tp_ticks={sample2.get('tp_ticks', 'MISSING')}")

compute_slippage(df1, "BOT 1 SIM3 (mia_paper_trader)")
compute_slippage(df2, "BOT 2 SIM2 (databento_paper_trader)")

# Comparaison globale
print(f"\n{'='*80}")
print(f"  COMPARAISON BOT 1 vs BOT 2")
print(f"{'='*80}")
