"""Audit compute_bias + TIMEOUT analysis sur les 23 trades Bot 1 session 29/04.

Question 1 : compute_bias est-il reste BULL toute la session ou a switche ?
Question 2 : sur les 13 TIMEOUT, le mouvement reel atteint-il au moins 50% du TP ?
"""
import json
from pathlib import Path
import pandas as pd

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# Charger trades Bot 1 du 29/04
fp = PAPER_DIR / "20260429_trades.jsonl"
trades = []
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        s = line.strip()
        if s:
            try:
                trades.append(json.loads(s))
            except json.JSONDecodeError:
                pass

df = pd.DataFrame(trades)
df["entry_dt"] = pd.to_datetime(df["entry_time"], errors="coerce")
df = df.sort_values("entry_dt").reset_index(drop=True)
print(f"Total trades Bot 1 session 29/04 : {len(df)}\n")

# ============================================================
# QUESTION 1 : COMPUTE_BIAS
# ============================================================
print("="*80)
print("  QUESTION 1 : COMPUTE_BIAS — bloquage BULL ou switch ?")
print("="*80)

# bias est-il dans dmp_bar ou ailleurs ?
sample = df.iloc[0]
print(f"\nCols disponibles dans 1er trade : {list(sample.keys())[:30]}")

# bias attribute lookup
if "dmp_bar" in df.columns:
    print("\n=> dmp_bar present, recherche bias dans bar")
    bar0 = sample.get("dmp_bar") or {}
    if isinstance(bar0, dict):
        bias_keys = [k for k in bar0 if "bias" in k.lower() or "regime" in k.lower()]
        print(f"   Cles bias/regime dans dmp_bar : {bias_keys[:10]}")

# Reconstituer bias depuis cvd_5d_rolling_ffd (proxy directionnel)
print("\nDirection trades + cvd_ffd associe (chronologique) :")
print(f"{'Time':<10s} {'Sym':<3s} {'Dir':<6s} {'Outcome':<8s} {'PnL':>6s} {'cvd_ffd':>10s} {'Vwap_slope':>12s} {'Pos_1d':>8s}")
for _, t in df.iterrows():
    bar = t.get("dmp_bar") or {}
    cvd_ffd = bar.get("cvd_5d_rolling_ffd", "?") if isinstance(bar, dict) else "?"
    vwap_slope = bar.get("vwap_slope_10", "?") if isinstance(bar, dict) else "?"
    pos_1d = bar.get("range_pos", "?") if isinstance(bar, dict) else "?"
    if isinstance(cvd_ffd, (int, float)):
        cvd_str = f"{cvd_ffd:+.0f}"
    else:
        cvd_str = str(cvd_ffd)[:10]
    if isinstance(vwap_slope, (int, float)):
        vwap_str = f"{vwap_slope:+.4f}"
    else:
        vwap_str = str(vwap_slope)[:12]
    if isinstance(pos_1d, (int, float)):
        pos_str = f"{pos_1d:.0f}%"
    else:
        pos_str = str(pos_1d)[:8]
    pnl = t.get("pnl_ticks", 0)
    print(f"{str(t['entry_dt'])[11:19]:<10s} "
          f"{t.get('symbol', '?'):<3s} "
          f"{t.get('direction', '?'):<6s} "
          f"{t.get('outcome', '?'):<8s} "
          f"{pnl:+6.0f}t "
          f"{cvd_str:>10s} "
          f"{vwap_str:>12s} "
          f"{pos_str:>8s}")

# Compter direction par tranche horaire
print("\n=== Direction par tranche horaire (UTC) ===")
df["hour"] = df["entry_dt"].dt.hour
hourly = df.groupby(["hour", "direction"]).size().unstack(fill_value=0)
print(hourly.to_string())

# ============================================================
# QUESTION 2 : ANALYSE TIMEOUT
# ============================================================
print("\n"+"="*80)
print("  QUESTION 2 : TIMEOUT — TP atteint en %% sur les 13 TIMEOUT ?")
print("="*80)

timeouts = df[df["outcome"] == "TIMEOUT"].copy()
print(f"\n{len(timeouts)} TIMEOUTs sur {len(df)} trades total\n")

print(f"{'Time':<10s} {'Sym':<3s} {'Dir':<6s} {'Entry':>10s} {'TP':>10s} {'Exit':>10s} {'TP_t':>5s} {'MFE_t':>6s} {'MAE_t':>6s} {'%TP_atteint':>12s}")
for _, t in timeouts.iterrows():
    entry = t.get("entry_price", 0)
    exit_p = t.get("exit_price", 0)
    tp_p = t.get("tp_price", 0)
    sl_p = t.get("sl_price", 0)
    tp_t = t.get("tp_ticks", 0)
    direction = t.get("direction", "")
    mfe = t.get("mfe", 0) or 0
    mae = t.get("mae", 0) or 0
    # Calcul %TP atteint
    if tp_t > 0 and direction in ("LONG", "SHORT"):
        # MFE = mouvement favorable max en ticks
        pct_tp = (mfe / tp_t * 100) if tp_t else 0
    else:
        pct_tp = 0
    print(f"{str(t['entry_dt'])[11:19]:<10s} "
          f"{t.get('symbol', '?'):<3s} "
          f"{direction:<6s} "
          f"{entry:>10.2f} "
          f"{tp_p:>10.2f} "
          f"{exit_p:>10.2f} "
          f"{tp_t:>5.0f} "
          f"{mfe:+6.1f} "
          f"{mae:+6.1f} "
          f"{pct_tp:>11.0f}%")

# Stats agregees
if len(timeouts) > 0:
    timeouts["pct_tp_atteint"] = (
        pd.to_numeric(timeouts["mfe"], errors="coerce").fillna(0) /
        pd.to_numeric(timeouts["tp_ticks"], errors="coerce").fillna(1) * 100
    )
    print(f"\n=== Stats %TP_atteint sur TIMEOUTs ===")
    print(f"  Median  : {timeouts['pct_tp_atteint'].median():.0f}%")
    print(f"  Mean    : {timeouts['pct_tp_atteint'].mean():.0f}%")
    print(f"  Max     : {timeouts['pct_tp_atteint'].max():.0f}%")
    print(f"  Trades atteignant >= 50% du TP : "
          f"{(timeouts['pct_tp_atteint'] >= 50).sum()}/{len(timeouts)}")
    print(f"  Trades atteignant >= 75% du TP : "
          f"{(timeouts['pct_tp_atteint'] >= 75).sum()}/{len(timeouts)}")

# ============================================================
# QUESTION 3 : R/R MOYEN ET TP TICKS
# ============================================================
print("\n"+"="*80)
print("  R/R + TP ticks distribution (tous trades)")
print("="*80)
df["sl_ticks_n"] = pd.to_numeric(df["sl_ticks"], errors="coerce")
df["tp_ticks_n"] = pd.to_numeric(df["tp_ticks"], errors="coerce")
df["rr"] = df["tp_ticks_n"] / df["sl_ticks_n"]
print(f"\nR/R median : {df['rr'].median():.2f}")
print(f"R/R mean   : {df['rr'].mean():.2f}")
print(f"R/R range  : {df['rr'].min():.2f} - {df['rr'].max():.2f}")
print(f"\nTP ticks median  : {df['tp_ticks_n'].median():.0f}")
print(f"SL ticks median  : {df['sl_ticks_n'].median():.0f}")
print(f"TP ticks par symbol :")
for sym in sorted(df["symbol"].unique()):
    sub = df[df["symbol"] == sym]
    print(f"  {sym}: TP median {sub['tp_ticks_n'].median():.0f}t, SL median {sub['sl_ticks_n'].median():.0f}t, R/R {sub['rr'].median():.2f}")
